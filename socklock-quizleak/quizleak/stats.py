"""Small, dependency-free statistics. Every function is a few lines so it can be explained."""
import math
from statistics import NormalDist

_N = NormalDist()


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """Two-sided pooled two-proportion z-test. Returns (z, p_value)."""
    if min(n1, n2) == 0:
        return 0.0, 1.0
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (x1 / n1 - x2 / n2) / se
    return z, 2 * (1 - _N.cdf(abs(z)))


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    """FDR-adjusted q-values, returned in the original order.

    We test hundreds of segments; without this correction a few would look 'significant' by pure chance.
    """
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    running_min = 1.0
    for rank in range(m, 0, -1):          # walk from the largest p-value down
        i = order[rank - 1]
        running_min = min(running_min, pvals[i] * m / rank)
        q[i] = running_min
    return q


def sample_size_per_arm(p: float, delta: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Sessions needed in EACH arm of an A/B test to detect an absolute lift `delta` on base rate `p`."""
    p2 = p + delta
    za, zb = _N.inv_cdf(1 - alpha / 2), _N.inv_cdf(power)
    pbar = (p + p2) / 2
    num = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p * (1 - p) + p2 * (1 - p2))) ** 2
    return math.ceil(num / delta ** 2)
