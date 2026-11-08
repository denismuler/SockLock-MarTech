"""Read an Amplitude-style events CSV (one row per event) and turn it into the generic shape the analyser uses.

What an Amplitude export looks like (columns we use):
  amplitude_id / user_id / device_id   who
  session_id                           start of the session in ms (NOT unique across people)
  event_type                           e.g. 'Quiz Started', 'Quiz Step Viewed', 'Email Error'
  event_time (or client_event_time)    UTC time
  platform, os_name, device_family, country, ...   plain attribute columns
  event_properties, user_properties    JSON inside the cell: {"step": 4, "creative_id": "c03"}, {"utm_source": "instagram"}

What we do: session = person + session_id; event name = a short snake_case name ('Quiz Step Viewed' + step 4 -> step_4);
JSON properties are unpacked into ordinary attribute columns.
"""
import json
import re
from collections import Counter

AMPLITUDE_COLS = {"event_type", "amplitude_id", "device_id", "user_id"}
ATTRIBUTE_COLS = ["platform", "os_name", "os_version", "device_family", "device_type", "country", "region", "city", "language"]
PERSON_COLS = ["amplitude_id", "user_id", "device_id"]
STEP_KEYS = ("step", "step_number", "question_number", "screen")
ERROR_KEYS = ("error", "error_type", "error_code", "error_message")
DOMAIN_KEYS = ("email_domain", "domain")
NOT_AN_ATTRIBUTE = set(STEP_KEYS) | set(ERROR_KEYS) | set(DOMAIN_KEYS) | {"revenue", "price", "email"}


def looks_like_amplitude(cols: list[str]) -> bool:
    c = set(cols)
    return "event_type" in c and bool(c & {"amplitude_id", "device_id", "user_id"}) and "event" not in c


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _json(cell: str) -> dict:
    if not cell or cell in ("null", "{}"):
        return {}
    try:
        v = json.loads(cell)
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _first(d: dict, keys) -> str:
    for k in keys:
        if d.get(k) not in (None, ""):
            return str(d[k])
    return ""


def event_name(event_type: str, props: dict) -> str:
    """'Quiz Step Viewed' + {"step": 4} -> 'step_4'; 'Email Focused' -> 'email_focus'; others -> snake_case."""
    slug = _slug(event_type)
    step = _first(props, STEP_KEYS)
    if step and "step" in slug or (step and slug in ("question_answered", "question_viewed", "screen_viewed")):
        n = re.sub(r"\D", "", step)
        if n:
            return f"step_{n}"
    if re.fullmatch(r"email_focus(ed)?", slug):
        return "email_focus"
    if re.fullmatch(r"email_submit(ted)?", slug):
        return "email_submit"
    if re.fullmatch(r"email_(error|validation_error|invalid)", slug):
        return "email_error"
    return slug


def normalize(reader, cols: list[str]):
    """-> (rows, dims, has_ts). Rows are generic dicts: session_id, event, ts, error, email_domain + attribute columns."""
    from .events import InputError
    if "event_type" not in cols:
        raise InputError("Amplitude format: column event_type is missing.")
    if not (set(cols) & set(PERSON_COLS)):
        raise InputError("Amplitude format: need at least one of amplitude_id, user_id, device_id to tell people apart.")
    time_col = next((c for c in ("event_time", "client_event_time") if c in cols), None)
    attr_cols = [c for c in ATTRIBUTE_COLS if c in cols]
    rows, ev_keys, user_keys = [], Counter(), Counter()
    for r in reader:
        person = next((r[c] for c in PERSON_COLS if c in cols and r.get(c)), "")
        if not person or not r.get("event_type"):
            continue
        sid = f"{person}_{r['session_id']}" if r.get("session_id") not in (None, "", "-1") else person
        ep, up = _json(r.get("event_properties", "")), _json(r.get("user_properties", ""))
        ev_keys.update(k for k in ep if k not in NOT_AN_ATTRIBUTE)
        user_keys.update(k for k in up if k not in NOT_AN_ATTRIBUTE)
        row = {"session_id": sid, "event": event_name(r["event_type"], ep),
               "ts": (r.get(time_col) or "").strip() if time_col else "",
               "error": _first(ep, ERROR_KEYS), "email_domain": _first(ep, DOMAIN_KEYS)}
        for c in attr_cols:
            row[c] = r.get(c, "")
        for k, v in ep.items():
            if k not in NOT_AN_ATTRIBUTE and not isinstance(v, (dict, list)):
                row[k] = str(v)
        for k, v in up.items():
            if k not in NOT_AN_ATTRIBUTE and not isinstance(v, (dict, list)):
                row.setdefault(k if k not in attr_cols and k not in ev_keys else f"user_{k}", str(v))
        rows.append(row)
    dims = attr_cols + [k for k in ev_keys if k not in attr_cols] + [k if k not in ev_keys and k not in attr_cols else f"user_{k}"
                                                                      for k in user_keys]
    dims = list(dict.fromkeys(dims))
    return rows, dims, bool(time_col)


def default_steps(events_seen: set[str]) -> list[str]:
    """Guess the funnel from event names: [first event] + step_1..step_N + offer + purchase."""
    first = next((e for e in ("session_start", "landing_viewed", "page_viewed", "quiz_started", "quiz_start", "quiz_open",
                              "quiz_opened") if e in events_seen), None)
    nums = sorted(int(e[5:]) for e in events_seen if re.fullmatch(r"step_\d+", e))
    offer = next((e for e in ("offer_viewed", "offer_view", "offer_shown", "paywall_viewed", "checkout_started") if e in events_seen), None)
    buy = next((e for e in ("purchase", "purchase_completed", "order_completed", "payment_completed", "subscription_started")
                if e in events_seen), None)
    steps = [first] + [f"step_{n}" for n in nums] + [offer, buy]
    steps = [s for s in steps if s]
    # 'Quiz Started' plus 'Landing Viewed' both present: keep the earlier one first
    if "landing_viewed" in events_seen and "quiz_started" in events_seen and steps[0] == "landing_viewed":
        steps.insert(1, "quiz_started")
    return steps
