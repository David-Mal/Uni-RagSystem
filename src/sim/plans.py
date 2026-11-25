"""Seeded intent planning for isolated unit tests, never evaluation generation."""

from dataclasses import asdict, dataclass, field
import random
from typing import Literal, Sequence, get_args

from .params import LifterParams
from .quotas import QuotaCounts, QuotaRequirements, quota_shortfalls
from .schema import HYPOTHESIS_LABELS, HypothesisLabel, json_bytes, nonempty

AbstentionCase = Literal["too_little_history", "too_few_sessions", "long_gaps", "missing_rpe"]
NumericTrap = Literal["mixed_units", "duplicates", "missing_rpe", "outliers"]
Confounder = Literal["sleep_loss", "illness", "travel"]


@dataclass(frozen=True)
class InjectionRequest:
    """Describe requested patterns without thresholds, evidence or note text."""

    hypotheses: tuple[HypothesisLabel, ...] = ()
    abstention_cases: tuple[AbstentionCase, ...] = ()
    numeric_traps: tuple[NumericTrap, ...] = ()
    confounders: tuple[Confounder, ...] = ()
    human_note_template_id: str | None = None

    def __post_init__(self) -> None:
        for name, allowed in (
            ("hypotheses", HYPOTHESIS_LABELS),
            ("abstention_cases", get_args(AbstentionCase)),
            ("numeric_traps", get_args(NumericTrap)),
            ("confounders", get_args(Confounder)),
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(value not in allowed for value in values):
                raise ValueError(f"invalid {name}")
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name}")
        if self.human_note_template_id is not None:
            nonempty(self.human_note_template_id, "human_note_template_id")


@dataclass(frozen=True)
class DevelopmentFamily:
    """An unpartitioned unit-test family, not an actual manifest entry."""

    family_id: str
    params: LifterParams
    requests: InjectionRequest

    def __post_init__(self) -> None:
        nonempty(self.family_id, "family_id")
        if not isinstance(self.params, LifterParams) or not isinstance(self.requests, InjectionRequest):
            raise ValueError("a development family requires validated params and requests")


@dataclass(frozen=True)
class ScenarioPlan:
    """A non-exportable intent record; deliberately not GroundTruth."""

    plan_id: str
    cluster_id: str
    params: LifterParams
    requests: InjectionRequest
    development_only: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        nonempty(self.plan_id, "plan_id")
        nonempty(self.cluster_id, "cluster_id")
        if not isinstance(self.params, LifterParams) or not isinstance(self.requests, InjectionRequest):
            raise ValueError("a plan requires validated params and requests")

    def to_json_bytes(self) -> bytes:
        return json_bytes(asdict(self))


def plan_development_cases(
    families: Sequence[DevelopmentFamily], *, n: int, unit_test_seed: int
) -> tuple[ScenarioPlan, ...]:
    """Balance supplied test families and shuffle using a local RNG.

    The seed controls only test-plan ordering, not physiological behavior or
    pool membership. No manifest is substituted, no workout rows are produced,
    and these plans cannot be submitted to the ground-truth quota validator.
    """
    if type(n) is not int or n < 1:
        raise ValueError("n must be a positive integer")
    if type(unit_test_seed) is not int:
        raise ValueError("unit_test_seed must be an integer")
    if not families or not all(isinstance(item, DevelopmentFamily) for item in families):
        raise ValueError("at least one development family is required")
    if len({item.family_id for item in families}) != len(families):
        raise ValueError("development family identifiers must be unique")
    selected = [families[index % len(families)] for index in range(n)]
    random.Random(unit_test_seed).shuffle(selected)
    return tuple(
        ScenarioPlan(f"development-{index:06d}", family.family_id, family.params, family.requests)
        for index, family in enumerate(selected, 1)
    )


def planned_coverage(plans: Sequence[ScenarioPlan]) -> QuotaCounts:
    """Requested coverage only, never validated annotation or realized coverage."""
    if not all(isinstance(item, ScenarioPlan) for item in plans):
        raise TypeError("planned coverage requires ScenarioPlan")
    if len({item.plan_id for item in plans}) != len(plans):
        raise ValueError("plan IDs must be unique")
    return QuotaCounts(
        len(plans),
        {label: sum(label in item.requests.hypotheses for item in plans) for label in HYPOTHESIS_LABELS},
        sum(bool(item.requests.abstention_cases) for item in plans),
        sum(bool(item.requests.confounders) for item in plans),
        sum(bool(item.requests.numeric_traps) for item in plans),
        len({item.cluster_id for item in plans}),
    )


def allocate_development_cases(
    families: Sequence[DevelopmentFamily], *, n: int, seed: int,
    requirements: QuotaRequirements | None = None,
) -> tuple[ScenarioPlan, ...]:
    """Greedily allocate overlapping requested coverage, then fill and shuffle.

    Insufficient family coverage or an unsuccessful allocation raises an error;
    an intent quota never certifies a simulated pattern or a ground-truth label.
    """
    required = QuotaRequirements() if requirements is None else requirements
    if not isinstance(required, QuotaRequirements):
        raise ValueError("requirements must be QuotaRequirements")
    # Reuse established validation without borrowing any real manifest entries.
    plan_development_cases(families, n=n, unit_test_seed=seed)
    if n < required.total:
        raise ValueError("n is below the requested total quota")
    rng = random.Random(seed)
    ordered = list(families)
    rng.shuffle(ordered)
    chosen: list[DevelopmentFamily] = []

    def materialize(items: Sequence[DevelopmentFamily]) -> tuple[ScenarioPlan, ...]:
        return tuple(ScenarioPlan(f"development-{index:06d}", item.family_id, item.params, item.requests)
                     for index, item in enumerate(items, 1))

    while True:
        missing = quota_shortfalls(planned_coverage(materialize(chosen)), required)
        missing.pop("total", None)
        if not missing:
            break
        if len(chosen) >= n:
            raise ValueError(f"cannot allocate requested coverage within n: {missing}")

        def score(family: DevelopmentFamily) -> int:
            request = family.requests
            categories = set(request.hypotheses)
            if request.abstention_cases:
                categories.add("abstention")
            if request.confounders:
                categories.add("confounders")
            if request.numeric_traps:
                categories.add("numeric_traps")
            return len(categories & missing.keys())

        best = max(ordered, key=score)
        if score(best) == 0:
            raise ValueError(f"supplied families cannot cover requested categories: {missing}")
        chosen.append(best)
    for index in range(n - len(chosen)):
        chosen.append(ordered[index % len(ordered)])
    rng.shuffle(chosen)
    plans = materialize(chosen)
    assert not quota_shortfalls(planned_coverage(plans), required)
    return plans
