"""Synthetic quiz events, calibrated to the SockLock data room, with KNOWN planted problems.

This is test data, not real SockLock data. The planted problems let us check that the analyser finds them
(and does not invent others):
  1. Android + Instagram in-app browser: email step converts far worse (think: keyboard hides the button).
  2. creative_id=c07: low-intent traffic, worse on the email step and slightly on the early steps.
  3. Email errors: typo domains (gmial.com ...) and '+' addresses rejected by validation; many users quit after them.
  Noise controls with NO effect: weekday, utm_source, country.
"""
import argparse
import csv
import random
from datetime import datetime, timedelta

FIELDS = ["session_id", "ts", "event", "error", "email_domain", "os", "device", "browser",
          "country", "utm_source", "creative_id"]

# P(move on) per hop, from the data room: 88, 75(*), 61, 58, 36, 31, 2.0 (% of all starts). (*) step 2 is not in the data room.
P_OPEN, P_2, P_3, P_4 = 0.88, 75 / 88, 61 / 75, 58 / 61
P_OFFER, P_BUY = 31 / 36, 2.0 / 31
BASE_EMAIL = 0.725                                   # step_4 -> step_5 for 'healthy' sessions without an error
TYPO_DOMAINS = ["gmial.com", "gmai.com", "yaho.com", "hotmial.com", "gmail.con"]
OK_DOMAINS = [("gmail.com", .62), ("yahoo.com", .12), ("icloud.com", .12), ("outlook.com", .09), ("aol.com", .05)]
ERROR_MIX = [("typo_domain", .45), ("plus_sign_rejected", .30), ("invalid_format", .25)]
ERROR_PASS = {"typo_domain": .50, "plus_sign_rejected": .22, "invalid_format": .60}
CREATIVES = [f"c{i:02d}" for i in range(1, 11)]


# What is planted in each scenario. 'planted' is the default used by the tests and the sample.
SCENARIOS = {
    "planted":   dict(android_iab=True,  c07=True,  ios_fb_iab=False, evening=False, err_rate=0.10, err_mix=ERROR_MIX),
    "clean":     dict(android_iab=False, c07=False, ios_fb_iab=False, evening=False, err_rate=0.10, err_mix=ERROR_MIX),
    "email_bug": dict(android_iab=False, c07=False, ios_fb_iab=False, evening=False, err_rate=0.30,
                      err_mix=[("plus_sign_rejected", .80), ("typo_domain", .15), ("invalid_format", .05)]),
    "evening":   dict(android_iab=False, c07=False, ios_fb_iab=False, evening=True,  err_rate=0.10, err_mix=ERROR_MIX),
    "ios_fb":    dict(android_iab=False, c07=False, ios_fb_iab=True,  evening=False, err_rate=0.10, err_mix=ERROR_MIX),
}


def _pick(rng, pairs):
    r, acc = rng.random(), 0.0
    for v, w in pairs:
        acc += w
        if r < acc:
            return v
    return pairs[-1][0]


def _profile(rng):
    os_ = _pick(rng, [("iOS", .46), ("Android", .38), ("Windows", .09), ("macOS", .07)])
    browser = {
        "iOS": [("Safari", .45), ("Instagram IAB", .25), ("Facebook IAB", .22), ("Chrome", .08)],
        "Android": [("Chrome", .35), ("Instagram IAB", .30), ("Facebook IAB", .25), ("Samsung Internet", .10)],
        "Windows": [("Chrome", .70), ("Edge", .30)],
        "macOS": [("Safari", .50), ("Chrome", .50)],
    }[os_]
    return {
        "os": os_, "device": "mobile" if os_ in ("iOS", "Android") else "desktop",
        "browser": _pick(rng, browser),
        "country": _pick(rng, [("US", .88), ("UK", .05), ("CA", .04), ("AU", .03)]),
        "utm_source": _pick(rng, [("instagram", .55), ("facebook", .45)]),
        "creative_id": _pick(rng, [(c, 0.08 if c == "c07" else 0.92 / 9) for c in CREATIVES]),
    }


def generate(n_sessions: int, seed: int = 7, days: int = 14, scenario: str = "planted"):
    sc = SCENARIOS[scenario]
    rng = random.Random(seed)
    t0 = datetime(2026, 10, 5)
    for i in range(n_sessions):
        sid = f"s{i:06d}"
        prof = _profile(rng)
        t = t0 + timedelta(seconds=rng.randrange(days * 86400))
        rows = []

        def emit(event, error="", domain=""):
            nonlocal t
            t += timedelta(seconds=rng.randint(4, 35))
            rows.append({"session_id": sid, "ts": t.isoformat(timespec="seconds"), "event": event,
                         "error": error, "email_domain": domain, **prof})

        low_intent = sc["c07"] and prof["creative_id"] == "c07"
        early = 0.93 if low_intent else 1.0
        emit("session_start")
        if rng.random() > P_OPEN * early: yield from rows; continue
        emit("quiz_open")
        if rng.random() > P_2 * early: yield from rows; continue
        emit("step_2")
        if rng.random() > P_3: yield from rows; continue
        emit("step_3")
        if rng.random() > P_4: yield from rows; continue
        emit("step_4")

        # ---- the email step
        base = BASE_EMAIL
        if sc["android_iab"] and prof["os"] == "Android" and prof["browser"] == "Instagram IAB":
            base = 0.45
        if sc["ios_fb_iab"] and prof["os"] == "iOS" and prof["browser"] == "Facebook IAB":
            base = 0.48
        if sc["evening"] and 18 <= t.hour < 24:
            base = 0.50
        if low_intent:
            base -= 0.12
        passed = False
        if rng.random() < 0.07:                       # never touches the field (autofill, or just leaves)
            passed = rng.random() < 0.15
        else:
            emit("email_focus")
            if rng.random() < sc["err_rate"]:         # validation problem
                code = _pick(rng, sc["err_mix"])
                dom = rng.choice(TYPO_DOMAINS) if code == "typo_domain" else "gmail.com"
                emit("email_error", code, dom)
                passed = rng.random() < ERROR_PASS[code]
            else:
                passed = rng.random() < base
            if passed:
                emit("email_submit", domain=_pick(rng, OK_DOMAINS))
        if not passed: yield from rows; continue
        emit("step_5")
        if rng.random() > P_OFFER: yield from rows; continue
        emit("offer_view")
        if rng.random() < P_BUY:
            emit("purchase")
        yield from rows


def write(path: str, n_sessions: int, seed: int, scenario: str = "planted") -> int:
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in generate(n_sessions, seed, scenario=scenario):
            w.writerow(row); n += 1
    return n


AMP_NAMES = {"session_start": "Landing Viewed", "quiz_open": "Quiz Started", "email_focus": "Email Focused",
             "email_error": "Email Error", "email_submit": "Email Submitted", "offer_view": "Offer Viewed", "purchase": "Purchase"}
AMP_FIELDS = ["uuid", "amplitude_id", "user_id", "device_id", "session_id", "event_type", "event_time", "platform", "os_name",
              "os_version", "device_family", "device_type", "country", "city", "language", "event_properties", "user_properties"]


def write_amplitude(path: str, n_sessions: int, seed: int, scenario: str = "planted") -> int:
    """The same synthetic data, laid out like an Amplitude export (web SDK: os_name = browser, device_family = OS)."""
    import json
    n = 0
    start_ms: dict[str, int] = {}
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=AMP_FIELDS)
        w.writeheader()
        for row in generate(n_sessions, seed, scenario=scenario):
            sid = row["session_id"]
            ts = datetime.fromisoformat(row["ts"])
            start_ms.setdefault(sid, int(ts.timestamp() * 1000))
            ev, props = row["event"], {"creative_id": row["creative_id"]}
            if ev.startswith("step_"):
                name, props["step"] = "Quiz Step Viewed", int(ev[5:])
            else:
                name = AMP_NAMES[ev]
            if row["error"]:
                props["error"] = row["error"]
            if row["email_domain"]:
                props["email_domain"] = row["email_domain"]
            if ev == "purchase":
                props["revenue"] = 68
            idx = int(sid[1:])
            w.writerow({"uuid": f"{n:08x}-4c2e-9b1a-{idx:012d}", "amplitude_id": 1_100_000_000 + idx, "user_id": "",
                        "device_id": f"d{idx:07d}", "session_id": start_ms[sid], "event_type": name,
                        "event_time": ts.strftime("%Y-%m-%d %H:%M:%S.%f"), "platform": "Web", "os_name": row["browser"],
                        "os_version": "", "device_family": row["os"], "device_type": row["device"], "country": row["country"],
                        "city": "", "language": "English", "event_properties": json.dumps(props),
                        "user_properties": json.dumps({"utm_source": row["utm_source"], "utm_campaign": "socks_q4"})})
            n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate synthetic SockLock quiz events (TEST DATA).")
    ap.add_argument("--sessions", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="out/quiz_events.csv")
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="planted")
    ap.add_argument("--layout", choices=["generic", "amplitude"], default="generic", help="column layout of the CSV")
    a = ap.parse_args()
    rows = (write_amplitude if a.layout == "amplitude" else write)(a.out, a.sessions, a.seed, a.scenario)
    print(f"wrote {rows} events for {a.sessions} sessions -> {a.out}")
