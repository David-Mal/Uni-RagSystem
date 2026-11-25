"""Interval and test statistics for the harness: Wilson, bootstrap (items or clusters), exact McNemar (plan §3.5)."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence

Z_95 = 1.959963984540054
"""Normal quantile for a two-sided 95% interval."""


def wilson(successes: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """Wilson score interval for a proportion; ``None`` when ``n`` is 0. For 80/80 the lower bound is ~0.954."""
    if n <= 0:
        return None
    p = successes / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    denom = 1 + z2 / n
    return max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom)


def mcnemar_exact(a_only: int, b_only: int) -> float:
    """Exact two-sided McNemar p-value from the two discordant counts; 1.0 with no discordant pairs, capped at 1."""
    n = a_only + b_only
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(a_only, b_only) + 1))
    return min(1.0, 2 * tail / 2**n)


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Percentile ``q`` in [0, 1] of an ascending list, with linear interpolation."""
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def group_sum(vectors: Sequence[Sequence[float]], keys: Sequence[str]) -> list[list[float]]:
    """Sum the per-item count vectors of each cluster (clusters in order of first appearance)."""
    sums: dict[str, list[float]] = {}
    for vec, key in zip(vectors, keys, strict=True):
        acc = sums.setdefault(key, [0.0] * len(vec))
        for j, x in enumerate(vec):
            acc[j] += x
    return list(sums.values())


def bootstrap(
    units: Sequence[Sequence[float]],
    statistic: Callable[[list[float]], Mapping[str, float | None]],
    n_resamples: int,
    seed: int,
    level: float = 0.95,
) -> dict[str, dict[str, float | int | None]]:
    """Percentile bootstrap over ``units`` (items, or clusters summed with ``group_sum``).

    Each unit is a vector of additive counts; ``statistic`` maps the summed vector of a resample to named values.
    A resample where a value is undefined (``None``) is skipped for that value only; ``n_used`` reports how many
    resamples contributed. The same drawn indices apply to every column, so paired designs concatenate the vectors
    of both models into one unit. Deterministic for a given ``seed``.
    """
    if not units:
        raise ValueError("bootstrap needs at least one unit")
    if n_resamples < 1:
        raise ValueError("n_resamples must be at least 1")
    rng = random.Random(seed)
    k = len(units)
    cols = list(zip(*units, strict=True))
    point = statistic([sum(c) for c in cols])
    draws: dict[str, list[float]] = {name: [] for name in point}
    population = range(k)
    for _ in range(n_resamples):
        idx = rng.choices(population, k=k)
        stat = statistic([sum(map(c.__getitem__, idx)) for c in cols])
        for name, value in stat.items():
            if value is not None:
                draws[name].append(value)
    out: dict[str, dict[str, float | int | None]] = {}
    for name, values in draws.items():
        values.sort()
        lo = percentile(values, (1 - level) / 2) if values else None
        hi = percentile(values, 1 - (1 - level) / 2) if values else None
        out[name] = {"point": point[name], "lo": lo, "hi": hi, "n_used": len(values)}
    return out
