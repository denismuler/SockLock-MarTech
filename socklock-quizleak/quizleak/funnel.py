from dataclasses import dataclass

from .events import InputError, Session

DEFAULT_STEPS = ["session_start", "quiz_open", "step_2", "step_3", "step_4", "step_5", "offer_view", "purchase"]


@dataclass
class Transition:
    src: str
    dst: str
    n_src: int
    n_dst: int
    rate: float
    lost_pct_of_start: float   # (n_src - n_dst) / n_start, in percentage points


def annotate(sessions: dict[str, Session], steps: list[str]) -> None:
    """depth = how many consecutive funnel steps (from the first) the session has. A missing step cuts the chain."""
    for s in sessions.values():
        d = 0
        for step in steps:
            if step not in s.events:
                break
            d += 1
        s.depth = d


def reached(sessions: dict[str, Session], steps: list[str], step: str) -> int:
    k = steps.index(step)
    return sum(1 for s in sessions.values() if s.depth > k)


def check_steps(sessions: dict[str, Session], steps: list[str]) -> None:
    seen = set().union(*(s.events for s in sessions.values()))
    unknown = [st for st in steps if st not in seen]
    if unknown:
        raise InputError(f"Funnel step(s) not found in the data: {', '.join(unknown)}. "
                         f"Events present: {', '.join(sorted(seen))}. Use --steps to set your own order.")


def transitions(sessions: dict[str, Session], steps: list[str]) -> list[Transition]:
    n = [reached(sessions, steps, st) for st in steps]
    out = []
    for i in range(len(steps) - 1):
        out.append(Transition(steps[i], steps[i + 1], n[i], n[i + 1],
                              n[i + 1] / n[i] if n[i] else 0.0, (n[i] - n[i + 1]) / n[0] * 100))
    return out


def default_focus(trs: list[Transition]) -> Transition:
    """Biggest loss (in points of all starts) inside the quiz: skip the first hop (landing -> quiz open,
    not a quiz problem) and the last hop (the payment decision, a different problem)."""
    inner = trs[1:-1] or trs
    return max(inner, key=lambda t: t.lost_pct_of_start)
