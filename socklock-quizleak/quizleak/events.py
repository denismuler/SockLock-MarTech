"""Load an events CSV (one row per event) into per-session records.

Required columns: session_id, event.  Optional: ts (ISO 8601), error, email_domain.
Every other column is treated as a session attribute (device, os, browser, creative_id, ...).
"""
import csv
from dataclasses import dataclass, field
from datetime import datetime

RESERVED = {"session_id", "event", "ts", "error", "email_domain", "user_id"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class InputError(Exception):
    """Raised with a message meant for the end user (a Growth PM, not a developer)."""


@dataclass
class Session:
    events: set = field(default_factory=set)
    props: dict = field(default_factory=dict)
    first_ts: datetime | None = None
    errors: list = field(default_factory=list)          # [(error_code, email_domain), ...] in order
    depth: int = 0                                      # filled by funnel.annotate()
    event_ts: dict = field(default_factory=dict)        # event -> first time it happened
    last_event: str = ""                                # the last thing the session did
    last_ts: datetime | None = None                     # ...and when


def _daypart(h: int) -> str:
    return "night" if h < 6 else "morning" if h < 12 else "afternoon" if h < 18 else "evening"


def detect_format(path: str, fmt: str = "auto") -> str:
    """'generic' (session_id, event, ts, ...) or 'amplitude' (event_type, amplitude_id, JSON properties)."""
    if fmt != "auto":
        return fmt
    from . import amplitude
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            cols = csv.DictReader(f).fieldnames or []
    except OSError as e:
        raise InputError(f"Cannot open {path}: {e.strerror}") from e
    return "amplitude" if amplitude.looks_like_amplitude(cols) else "generic"


def load(path: str, fmt: str = "auto") -> tuple[dict[str, Session], list[str]]:
    sessions: dict[str, Session] = {}
    fmt = detect_format(path, fmt)
    try:
        f = open(path, newline="", encoding="utf-8-sig")
    except OSError as e:
        raise InputError(f"Cannot open {path}: {e.strerror}") from e
    with f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        if fmt == "amplitude":
            from . import amplitude
            rows, dims, has_ts = amplitude.normalize(reader, cols)
        else:
            missing = {"session_id", "event"} - set(cols)
            if missing:
                raise InputError(f"Missing required column(s): {', '.join(sorted(missing))}. Found: {', '.join(cols) or 'none'}. "
                                 "Потрібен експорт ПОДІЙ (один рядок = одна подія), а не агрегований CSV з графіка.")
            dims = [c for c in cols if c not in RESERVED]
            has_ts = "ts" in cols
            rows = reader
        for row in rows:
            sid = row["session_id"]
            if not sid:
                continue
            s = sessions.setdefault(sid, Session())
            s.events.add(row["event"])
            for d in dims:
                v = (row.get(d) or "").strip()
                if v and d not in s.props:
                    s.props[d] = v
            if row["event"].endswith("error") and row.get("error"):
                s.errors.append((row["error"], (row.get("email_domain") or "").lower()))
            t = None
            if has_ts and row.get("ts"):
                try:
                    t = datetime.fromisoformat(row["ts"])
                except ValueError:
                    t = None
            if t is not None:
                if s.first_ts is None or t < s.first_ts:
                    s.first_ts = t
                if row["event"] not in s.event_ts or t < s.event_ts[row["event"]]:
                    s.event_ts[row["event"]] = t
                if s.last_ts is None or t >= s.last_ts:
                    s.last_event, s.last_ts = row["event"], t
            elif s.last_ts is None:                       # no usable timestamp: fall back to file order
                s.last_event = row["event"]
    if not sessions:
        raise InputError("The file has no usable rows.")
    if has_ts:  # derived dimensions; 'weekday' doubles as a built-in noise control
        dims += ["weekday", "daypart"]
        for s in sessions.values():
            if s.first_ts:
                s.props["weekday"] = WEEKDAYS[s.first_ts.weekday()]
                s.props["daypart"] = _daypart(s.first_ts.hour)
    return sessions, dims
