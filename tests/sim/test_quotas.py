from typing import Callable

import pytest

from src.sim.quotas import QuotaError, QuotaRequirements, count_quotas, validate_quotas
from src.sim.schema import ExpectedHypothesis, GroundTruth, HYPOTHESIS_LABELS


def test_full_issue_quota_arithmetic(annotation: Callable[..., GroundTruth]) -> None:
    records = []
    for index in range(150):
        # These annotation mocks have no underlying log and certify no evidence.
        # 7 * 20 = 140 labelled records, plus 10 unlabelled records = 150.
        # Last 30 abstain; 20 of those also carry the confounder annotation.
        label = HYPOTHESIS_LABELS[index // 20] if index < 140 else None
        records.append(annotation(
            scenario_id=f"unit-{index}",
            expected_hypotheses=() if label is None else (ExpectedHypothesis(label, "weak"),),
            abstain=index >= 120,
            abstention_reasons=("unit-only reason",) if index >= 120 else (),
            cluster_id=f"unit-family-{index // 20}",
            has_confounder=120 <= index < 140,
            has_numeric_trap=100 <= index < 120,
        ))
    counts = validate_quotas(records)
    assert counts.total == 150
    assert set(counts.by_hypothesis.values()) == {20}
    assert (counts.abstention, counts.confounders, counts.numeric_traps, counts.clusters) == (30, 20, 20, 8)


def test_overlaps_count_scenarios_not_labels(annotation: Callable[..., GroundTruth]) -> None:
    records = [annotation(
        scenario_id=f"unit-{index}",
        expected_hypotheses=tuple(ExpectedHypothesis(label, "insufficient") for label in HYPOTHESIS_LABELS),
        abstain=True, abstention_reasons=("unit-only reason",),
        has_confounder=True, has_numeric_trap=True,
    ) for index in range(2)]
    # Two records each carry all seven labels: every label has 2, total stays 2.
    counts = validate_quotas(records, QuotaRequirements(2, 2, 2, 2, 2))
    assert counts.total == 2 and set(counts.by_hypothesis.values()) == {2}
    assert counts.clusters == 1


def test_shortfalls_report_exact_missing_counts() -> None:
    with pytest.raises(QuotaError) as caught:
        validate_quotas([])
    assert caught.value.shortfalls["total"] == 150
    assert caught.value.shortfalls["abstention"] == 30
    assert all(caught.value.shortfalls[label] == 20 for label in HYPOTHESIS_LABELS)


def test_duplicate_items_do_not_inflate_counts(annotation: Callable[..., GroundTruth]) -> None:
    item = annotation()
    with pytest.raises(ValueError, match="duplicate"):
        count_quotas([item, item])


@pytest.mark.parametrize("value", (-1, True, 1.5))
def test_reject_invalid_quota(value: int) -> None:
    with pytest.raises(ValueError):
        QuotaRequirements(total=value)
