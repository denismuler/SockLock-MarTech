"""Scan segments (single attributes and pairs) for a worse-than-the-rest conversion on one funnel transition."""
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from . import stats
from .events import Session


@dataclass
class Segment:
    parts: tuple            # ((dim, value), ...)  1 or 2 items
    n: int                  # sessions that reached the step
    x: int                  # ...and moved on
    rate: float
    rest_rate: float
    gap_pp: float           # rest_rate - rate, percentage points (positive = this segment is worse)
    p: float
    q: float = 1.0
    extra_purchases_month: float = 0.0
    egp_month: float = 0.0

    @property
    def label(self) -> str:
        return " + ".join(f"{d}={v}" for d, v in self.parts)


def select_dims(sessions: dict[str, Session], dims: list[str], max_card: int) -> tuple[list[str], list[str]]:
    """Keep low-cardinality attributes; high-cardinality ones (ids, emails) cannot form meaningful segments."""
    values = {d: set() for d in dims}
    for s in sessions.values():
        for d in dims:
            v = s.props.get(d)
            if v:
                values[d].add(v)
    kept = [d for d in dims if 1 < len(values[d]) <= max_card]
    return kept, [d for d in dims if len(values[d]) > max_card]


def _scan_once(pop: list[Session], moved: list[bool], dims: list[str], *, min_n: int, depth: int = 2,
         min_gap_pp: float = 2.0, alpha: float = 0.05, downstream_rate: float, scale: float, ltv: float) -> tuple[list[Segment], int]:
    """One pass. Returns (significant worse segments sorted by EGP impact, number of tests run)."""
    N, X = len(pop), sum(moved)
    cnt: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for s, ok in zip(pop, moved):
        items = [(d, s.props[d]) for d in dims if d in s.props]
        for it in items:
            c = cnt[(it,)]; c[0] += 1; c[1] += ok
        if depth >= 2:
            for a, b in combinations(items, 2):
                c = cnt[(a, b)]; c[0] += 1; c[1] += ok

    cands: list[Segment] = []
    for parts, (n, x) in cnt.items():
        rest_n, rest_x = N - n, X - x
        if n < min_n or rest_n < min_n:
            continue
        _, p = stats.two_prop_z(x, n, rest_x, rest_n)
        cands.append(Segment(parts, n, x, x / n, rest_x / rest_n, (rest_x / rest_n - x / n) * 100, p))
    qs = stats.benjamini_hochberg([c.p for c in cands])   # correct over ALL tests, better and worse
    for c, q in zip(cands, qs):
        c.q = q

    def parent_rate(part):
        n, x = cnt[(part,)]
        return x / n

    found = []
    for c in cands:
        if c.gap_pp < min_gap_pp or c.q >= alpha:
            continue
        if len(c.parts) == 2:   # a pair must be clearly worse than BOTH parents, otherwise it adds nothing
            if c.rate > min(parent_rate(c.parts[0]), parent_rate(c.parts[1])) - min_gap_pp / 100:
                continue
        # If the segment matched the rest, this many more sessions would move on, and convert downstream:
        extra_next = c.n * (c.gap_pp / 100)
        c.extra_purchases_month = extra_next * downstream_rate * scale
        c.egp_month = c.extra_purchases_month * ltv
        found.append(c)
    found.sort(key=lambda c: c.egp_month, reverse=True)
    return found, len(cands)


SPECIFIC_BONUS = 1.15   # near-ties go to the more specific explanation (a pair over its parent)


def _matches(s: Session, parts: tuple) -> bool:
    return all(s.props.get(d) == v for d, v in parts)


def _refine(best: Segment, pop: list[Session], moved: list[bool], dims: list[str], *, min_n: int, min_gap_pp: float = 2.0,
            alpha: float = 0.05, downstream_rate: float, scale: float, ltv: float, **_) -> Segment:
    """Drill down: is the leak of a single-attribute segment really concentrated in a sub-segment?

    Example: 'device=mobile' looks bad only because Android + Instagram IAB inside it is broken. Reporting the parent
    would overstate the money and send the team to the wrong place. We test every child (parent + one more attribute)
    against the REST OF THE PARENT; a child that is clearly and significantly worse replaces the parent.
    If the parent is uniformly bad, no child stands out and the parent stays.
    """
    if len(best.parts) >= 3:
        return best
    used = {d for d, _ in best.parts}
    inside = [(s, ok) for s, ok in zip(pop, moved) if _matches(s, best.parts)]
    n, x = len(inside), sum(ok for _, ok in inside)
    cnt: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for s, ok in inside:
        for d in dims:
            if d not in used and d in s.props:
                c = cnt[(d, s.props[d])]; c[0] += 1; c[1] += ok
    kids = [(it, c) for it, c in cnt.items() if c[0] >= min_n and n - c[0] >= min_n]
    pick = None
    for it, (nc, xc) in kids:
        gap = ((x - xc) / (n - nc) - xc / nc) * 100
        _, pv = stats.two_prop_z(xc, nc, x - xc, n - nc)
        if gap >= min_gap_pp and min(1.0, pv * len(kids)) < alpha:
            score = nc * gap
            if pick is None or score > pick[0]:
                pick = (score, it, nc, xc, pv)
    if pick is None:
        return best
    _, it, nc, xc, pv = pick
    N, X = len(pop), sum(moved)
    rate, rest_rate = xc / nc, (X - xc) / (N - nc)
    seg = Segment(best.parts + (it,), nc, xc, rate, rest_rate, (rest_rate - rate) * 100,
                  pv, q=min(1.0, pv * len(kids)))
    seg.extra_purchases_month = nc * (seg.gap_pp / 100) * downstream_rate * scale
    seg.egp_month = seg.extra_purchases_month * ltv
    return seg


def _simplify(seg: Segment, pop: list[Session], moved: list[bool]) -> Segment:
    """Drop a condition that adds nothing (e.g. 'device=mobile' next to 'os=Android': Android is always mobile)."""
    parts = seg.parts
    for part in seg.parts:
        rest = tuple(q for q in parts if q != part)
        if rest and sum(_matches(s, rest) for s in pop) == seg.n:
            parts = rest
    if parts == seg.parts:
        return seg
    return Segment(parts, seg.n, seg.x, seg.rate, seg.rest_rate, seg.gap_pp, seg.p, seg.q,
                   seg.extra_purchases_month, seg.egp_month)


def find_leaks(pop: list[Session], moved: list[bool], dims: list[str], *, max_segments: int = 10, **kw) -> tuple[list[Segment], int]:
    """Greedy 'peeling': take the strongest leaking segment, remove its sessions, look again in what is left.

    Why: parents and children overlap (Android, Instagram, Android+Instagram all look bad because of ONE problem).
    Peeling reports the root segment once, and the reported segments do not overlap, so their EGP can be summed.
    Returns (segments, number of tests in the first pass).
    """
    chosen: list[Segment] = []
    n_tests_first = 0
    for i in range(max_segments):
        if not pop:
            break
        found, n_tests = _scan_once(pop, moved, dims, **kw)
        if i == 0:
            n_tests_first = n_tests
        if not found:
            break
        best = max(found, key=lambda c: c.egp_month * (SPECIFIC_BONUS if len(c.parts) == 2 else 1.0))
        if kw.get("depth", 2) >= 2:
            for _ in range(2):
                finer = _refine(best, pop, moved, dims, **kw)
                if finer is best:
                    break
                best = finer
            best = _simplify(best, pop, moved)
        chosen.append(best)
        keep = [k for k, s in enumerate(pop) if not _matches(s, best.parts)]
        pop, moved = [pop[k] for k in keep], [moved[k] for k in keep]
    return chosen, n_tests_first
