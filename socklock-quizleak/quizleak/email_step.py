"""Micro-funnel for the email step, from optional events: email_focus, email_error (+error, email_domain), email_submit."""
from collections import Counter
from dataclasses import dataclass, field

from .events import Session


@dataclass
class EmailReport:
    n: int
    groups: dict = field(default_factory=dict)       # name -> (count, share_of_n)
    errors: list = field(default_factory=list)       # (error_code, sessions, quit_rate, egp_month_ceiling)
    egp_all_errors: float = 0.0                      # ceiling if error sessions passed like error-free ones
    bad_domains: list = field(default_factory=list)  # (domain, sessions, quit_rate)


GROUP_LABELS = {
    "never_touched": "не торкнулися поля email",
    "typed_and_left": "почали вводити й пішли без помилки",
    "error_then_quit": "отримали помилку й пішли",
    "error_then_passed": "отримали помилку, але пройшли",
    "clean_pass": "пройшли без помилок",
}


def analyse(sessions: dict[str, Session], steps: list[str], step: str, next_step: str, *,
            scale: float, downstream: float, ltv: float) -> EmailReport | None:
    seen = set().union(*(s.events for s in sessions.values()))
    if not {"email_focus", "email_submit"} & seen and "email_error" not in seen:
        return None
    k = steps.index(step)
    pop = [s for s in sessions.values() if s.depth > k]
    passed = lambda s: s.depth > steps.index(next_step)
    rep = EmailReport(n=len(pop))
    g = Counter()
    err_n, err_quit = Counter(), Counter()
    dom_n, dom_quit = Counter(), Counter()
    for s in pop:
        had_err = bool(s.errors)
        if had_err:
            g["error_then_passed" if passed(s) else "error_then_quit"] += 1
            for code in {c for c, _ in s.errors}:
                err_n[code] += 1
                err_quit[code] += not passed(s)
            for dom in {d for _, d in s.errors if d}:
                dom_n[dom] += 1
                dom_quit[dom] += not passed(s)
        elif passed(s):
            g["clean_pass"] += 1
        elif "email_focus" in s.events:
            g["typed_and_left"] += 1
        else:
            g["never_touched"] += 1
    rep.groups = {k_: (g[k_], g[k_] / len(pop)) for k_ in GROUP_LABELS}
    with_err = [s for s in pop if s.errors]
    clean = [s for s in pop if not s.errors]
    clean_rate = sum(passed(s) for s in clean) / len(clean) if clean else 0.0
    egp = lambda extra_sessions: max(extra_sessions, 0.0) * scale * downstream * ltv   # same chain as for segments
    rep.errors = sorted(((c, err_n[c], err_quit[c] / err_n[c],
                          egp(err_n[c] * (clean_rate - (1 - err_quit[c] / err_n[c])))) for c in err_n), key=lambda t: -t[1])
    rep.egp_all_errors = egp(len(with_err) * (clean_rate - sum(passed(s) for s in with_err) / len(with_err))) if with_err else 0.0
    rep.bad_domains = sorted(((d, dom_n[d], dom_quit[d] / dom_n[d]) for d in dom_n), key=lambda t: -t[1])[:8]
    return rep
