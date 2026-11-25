"""Count declared annotations, never injected intentions or tool-derived labels."""

from dataclasses import dataclass, fields
from collections.abc import Mapping
from types import MappingProxyType
from typing import Iterable

from .schema import GroundTruth, HYPOTHESIS_LABELS


@dataclass(frozen=True)
class QuotaRequirements:
    """Defaults are the issue #25 minima, not invented simulation thresholds."""

    total: int = 150
    per_hypothesis: int = 20
    abstention: int = 30
    confounders: int = 20
    numeric_traps: int = 20

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not int or value < 0:
                raise ValueError("quota requirements must be nonnegative integers")


@dataclass(frozen=True)
class QuotaCounts:
    total: int
    by_hypothesis: Mapping[str, int]
    abstention: int
    confounders: int
    numeric_traps: int
    clusters: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "by_hypothesis", MappingProxyType(dict(self.by_hypothesis)))

    def to_dict(self) -> dict[str, object]:
        return {item.name: dict(self.by_hypothesis) if item.name == "by_hypothesis" else getattr(self, item.name)
                for item in fields(self)}


class QuotaError(ValueError):
    def __init__(self, counts: QuotaCounts, shortfalls: dict[str, int]) -> None:
        self.counts = counts
        self.shortfalls = shortfalls
        super().__init__(f"Quota shortfalls: {shortfalls}")


def count_quotas(scenarios: Iterable[GroundTruth]) -> QuotaCounts:
    """Count each annotation once per scenario; this is not detectability proof."""
    labels = dict.fromkeys(HYPOTHESIS_LABELS, 0)
    identifiers: set[str] = set()
    clusters: set[str] = set()
    abstention = confounders = traps = 0
    for scenario in scenarios:
        if not isinstance(scenario, GroundTruth):
            raise TypeError("quotas require explicit GroundTruth annotations, not intent plans")
        if scenario.scenario_id in identifiers:
            raise ValueError("duplicate scenario_id")
        identifiers.add(scenario.scenario_id)
        clusters.add(scenario.cluster_id)
        for hypothesis in scenario.expected_hypotheses:
            labels[hypothesis.label] += 1
        abstention += scenario.abstain
        confounders += scenario.has_confounder
        traps += scenario.has_numeric_trap
    return QuotaCounts(len(identifiers), labels, abstention, confounders, traps, len(clusters))


def quota_shortfalls(counts: QuotaCounts, required: QuotaRequirements) -> dict[str, int]:
    """Shared arithmetic only; callers must preserve their coverage stage."""
    if not isinstance(required, QuotaRequirements):
        raise ValueError("requirements must be QuotaRequirements")
    return {
        name: minimum - actual
        for name, actual, minimum in (
            ("total", counts.total, required.total),
            ("abstention", counts.abstention, required.abstention),
            ("confounders", counts.confounders, required.confounders),
            ("numeric_traps", counts.numeric_traps, required.numeric_traps),
            *((label, counts.by_hypothesis[label], required.per_hypothesis) for label in HYPOTHESIS_LABELS),
        )
        if actual < minimum
    }


def validate_quotas(
    scenarios: Iterable[GroundTruth], requirements: QuotaRequirements | None = None
) -> QuotaCounts:
    """Validate coverage of supplied annotations, not their truth or pool origin."""
    required = QuotaRequirements() if requirements is None else requirements
    counts = count_quotas(scenarios)
    shortfalls = quota_shortfalls(counts, required)
    if shortfalls:
        raise QuotaError(counts, shortfalls)
    return counts
