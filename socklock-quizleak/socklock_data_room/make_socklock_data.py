"""Generates the ONE demo dataset for this project: SockLock_quiz_events_SYNTHETIC.csv (Amplitude-style events).

It is synthetic (the data room has no event-level data) but calibrated to the case:
the funnel is checked against the data-room numbers and must match within 0.5 pp.
Seed 34 was picked by searching seeds 1..60 for the closest match. Step 2 is not in the data room (~75% is our estimate).
Run from socklock-quizleak/:  python3 socklock_data_room/make_socklock_data.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from quizleak import synth  # noqa: E402

SESSIONS, SEED = 20_000, 34
OUT = Path(__file__).with_name("SockLock_quiz_events_SYNTHETIC.csv")
# data room, % of ALL clicks that reached the step
CASE = [("quiz_open", "Відкрили квіз", 88.0), ("step_3", "Крок 3 з 6", 61.0), ("step_4", "Крок 4 з 6 (email)", 58.0),
        ("step_5", "Крок 5 з 6", 36.0), ("offer_view", "Персональна пропозиція", 31.0), ("purchase", "Оплата", 2.0)]

if __name__ == "__main__":
    n = synth.write_amplitude(str(OUT), SESSIONS, SEED, "planted")
    reach = {e: 0 for e, _, _ in CASE}
    for row in synth.generate(SESSIONS, SEED, scenario="planted"):
        if row["event"] in reach:
            reach[row["event"]] += 1
    print(f"wrote {n} events, {SESSIONS} sessions -> {OUT.name}\n")
    print(f"{'Крок':<26}{'Кейс':>8}{'Файл':>8}{'Різниця':>9}")
    worst = 0.0
    for ev, name, case in CASE:
        got = reach[ev] / SESSIONS * 100
        worst = max(worst, abs(got - case))
        print(f"{name:<26}{case:>7.1f}%{got:>7.1f}%{got - case:>+8.1f}")
    print(f"\nнайбільше відхилення: {worst:.2f} п.п. ({'OK' if worst <= 0.5 else 'ПОГАНО'})")
    sys.exit(0 if worst <= 0.5 else 1)
