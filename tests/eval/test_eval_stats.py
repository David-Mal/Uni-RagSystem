"""Tests for src.eval.stats (issue P2). Expected values are computed by hand, not with the code under test."""

from __future__ import annotations

import pytest

from src.eval.stats import bootstrap, group_sum, mcnemar_exact, percentile, wilson


def test_wilson_80_of_80() -> None:
    # k = n = 80: lower = n / (n + z^2) = 80 / (80 + 1.96^2) = 80 / 83.8416 = 0.9542 (plan §3.5: ~0.954); upper = 1.
    lo, hi = wilson(80, 80)  # type: ignore[misc]
    assert lo == pytest.approx(0.9542, abs=5e-4)
    assert hi == pytest.approx(1.0)


def test_wilson_1_of_2() -> None:
    # p = .5, n = 2, z^2 = 3.8415: centre = (0.5 + 3.8415/4) / (1 + 3.8415/2) = 0.5, half-width = 0.4055
    lo, hi = wilson(1, 2)  # type: ignore[misc]
    assert (lo, hi) == (pytest.approx(0.0945, abs=1e-3), pytest.approx(0.9055, abs=1e-3))


def test_wilson_undefined_for_empty_denominator() -> None:
    assert wilson(0, 0) is None


def test_mcnemar_15_vs_5() -> None:
    # n = 20, tail P(X <= 5) = (1+20+190+1140+4845+15504) / 2^20 = 21700 / 1048576 = 0.020695; two-sided 0.04139
    assert mcnemar_exact(15, 5) == pytest.approx(0.0414, abs=5e-4)
    assert mcnemar_exact(5, 15) == mcnemar_exact(15, 5)


def test_mcnemar_14_vs_6() -> None:
    # tail P(X <= 6) = (21700 + 38760) / 2^20 = 0.057659; two-sided 0.11532
    assert mcnemar_exact(14, 6) == pytest.approx(0.1153, abs=5e-4)


def test_mcnemar_edges() -> None:
    assert mcnemar_exact(0, 0) == 1.0  # no discordant pairs
    assert mcnemar_exact(3, 3) == 1.0  # 2 * P(X <= 3) = 2 * 42/64 = 1.31, capped at 1
    assert mcnemar_exact(0, 5) == pytest.approx(2 / 32)  # 2 * 1 / 2^5


def test_percentile_interpolates() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0
    assert percentile([0.0, 10.0], 0.25) == 2.5


def _acc(sums: list[float]) -> dict[str, float | None]:
    return {"acc": sums[0] / sums[1] if sums[1] else None}


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    units = [[float(i % 3 == 0), 1.0] for i in range(30)]
    a = bootstrap(units, _acc, 300, seed=7)
    assert a == bootstrap(units, _acc, 300, seed=7)
    assert a != bootstrap(units, _acc, 300, seed=8)
    assert a["acc"]["point"] == pytest.approx(10 / 30)
    assert a["acc"]["n_used"] == 300


def test_cluster_bootstrap_resamples_whole_clusters() -> None:
    # Cluster X: 3 items, all correct. Cluster Y: 3 items, all wrong. Resampling clusters gives accuracy in {0, .5, 1}
    # only. Resampling the 6 items gives k/6 with k ~ Binomial(6, .5): P(k in {0, 3, 6}) = 22/64, so other values occur.
    units = [[1.0, 1.0]] * 3 + [[0.0, 1.0]] * 3
    keys = ["X"] * 3 + ["Y"] * 3

    def whole(sums: list[float]) -> dict[str, float | None]:
        return {"ok": 1.0 if sums[0] / sums[1] in (0.0, 0.5, 1.0) else 0.0}

    clustered = bootstrap(group_sum(units, keys), whole, 200, seed=1)["ok"]
    assert (clustered["lo"], clustered["hi"]) == (1.0, 1.0)
    assert bootstrap(units, whole, 200, seed=1)["ok"]["lo"] == 0.0


def test_group_sum() -> None:
    assert group_sum([[1, 2], [3, 4], [5, 6]], ["a", "b", "a"]) == [[6, 8], [3, 4]]


def test_undefined_resamples_are_skipped_and_counted() -> None:
    # Only 1 of 10 units has a denominator, so about 35% of resamples (0.9^10) have none and are skipped.
    units = [[1.0, 1.0]] + [[0.0, 0.0]] * 9
    out = bootstrap(units, _acc, 200, seed=3)["acc"]
    assert 0 < out["n_used"] < 200
    assert out["lo"] == out["hi"] == 1.0


def test_bootstrap_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        bootstrap([], _acc, 10, seed=0)
