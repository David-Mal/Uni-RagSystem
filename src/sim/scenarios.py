"""Actual development scenario generation with explicit evaluation boundaries."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib

from .injections import Injection, InjectionObservation, apply_injection, injection_request, observe_injection
from .params import LifterParams
from .plans import DevelopmentFamily, InjectionRequest, allocate_development_cases, planned_coverage
from .quotas import QuotaCounts, QuotaRequirements, quota_shortfalls
from .schema import GroundTruth, HYPOTHESIS_LABELS, freeze_json, json_bytes, nonempty, thaw_json
from .workouts import SimulationDesign, SimulatedLog, development_value, generate_workouts


@dataclass(frozen=True)
class SimulationFamily:
    family_id: str
    params: LifterParams
    design: SimulationDesign
    injections: tuple[Injection, ...]

    def __post_init__(self) -> None:
        nonempty(self.family_id, "family_id")
        if not isinstance(self.params, LifterParams) or not isinstance(self.design, SimulationDesign):
            raise ValueError("simulation families require validated parameters and design")
        if not isinstance(self.injections, tuple):
            raise ValueError("injections must be an immutable ordered tuple")
        for config in self.injections:
            injection_request(config)

    def planning_family(self) -> DevelopmentFamily:
        requests = [injection_request(config) for config in self.injections]
        merged: dict[str, tuple[str, ...]] = {}
        for name in ("hypotheses", "abstention_cases", "numeric_traps", "confounders"):
            merged[name] = tuple(dict.fromkeys(value for request in requests for value in getattr(request, name)))
        reference = next((item.human_note_template_id for item in requests if item.human_note_template_id), None)
        return DevelopmentFamily(self.family_id, self.params, InjectionRequest(**merged, human_note_template_id=reference))


@dataclass(frozen=True)
class DevelopmentScenario:
    scenario_id: str
    cluster_id: str
    seed: int
    requested: InjectionRequest
    log: SimulatedLog
    observations: tuple[InjectionObservation, ...]
    injected_parameters: Mapping[str, object]
    expected_annotations: GroundTruth | None = None
    annotation_specification: str | None = None
    development_only: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        nonempty(self.scenario_id, "scenario_id")
        nonempty(self.cluster_id, "cluster_id")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        if not isinstance(self.requested, InjectionRequest) or not isinstance(self.log, SimulatedLog):
            raise ValueError("a scenario requires requests and an actual internal log")
        if not isinstance(self.observations, tuple) or not all(isinstance(item, InjectionObservation) for item in self.observations):
            raise ValueError("observations must be an immutable tuple")
        if not isinstance(self.injected_parameters, Mapping):
            raise ValueError("injected_parameters must be an object")
        object.__setattr__(self, "injected_parameters", freeze_json(self.injected_parameters))
        if self.expected_annotations is not None:
            if not isinstance(self.expected_annotations, GroundTruth):
                raise ValueError("expected annotations must use the GroundTruth schema")
            nonempty(self.annotation_specification, "annotation_specification")
            if (self.expected_annotations.scenario_id, self.expected_annotations.cluster_id) != (self.scenario_id, self.cluster_id):
                raise ValueError("annotation identity/family does not match the scenario")
            if self.expected_annotations.injected_parameters != self.injected_parameters:
                raise ValueError("annotation parameters do not match the simulated parameters")
        elif self.annotation_specification is not None:
            raise ValueError("a specification reference alone is not an annotation decision")

    @property
    def injected_causes(self) -> tuple[str, ...]:
        return tuple(label for label in HYPOTHESIS_LABELS if any(
            observation.present and label in observation.request.hypotheses for observation in self.observations
        ))

    @property
    def pending_decisions(self) -> tuple[str, ...]:
        return ("evidence_levels", "abstention_outcome", "gate_outcome") if self.expected_annotations is None else ()

    def to_dict(self) -> dict[str, object]:
        return {
            "development_only": True, "scenario_id": self.scenario_id, "cluster_id": self.cluster_id, "seed": self.seed,
            "requested": development_value(self.requested), "injected_causes": self.injected_causes,
            "observed_patterns": [{"pattern": item.pattern, "present": item.present, "facts": thaw_json(item.facts)} for item in self.observations],
            "injected_parameters": thaw_json(self.injected_parameters), "log": self.log.to_dict(),
            "expected_annotations": None if self.expected_annotations is None else self.expected_annotations.to_dict(),
            "annotation_specification": self.annotation_specification, "pending_decisions": self.pending_decisions,
        }

    def to_json_bytes(self) -> bytes:
        return json_bytes(self.to_dict())


def simulate_family(family: SimulationFamily, *, seed: int, scenario_id: str) -> DevelopmentScenario:
    """Generate workouts and apply ordered transformations, not final D3 labels."""
    if not isinstance(family, SimulationFamily):
        raise ValueError("family must be SimulationFamily")
    log = generate_workouts(family.params, family.design, seed=seed)
    stages = []
    for config in family.injections:
        stages.append((log, config))
        log = apply_injection(log, config)
    # Recheck against the final log: later operations can erase an earlier pattern.
    observations = tuple(observe_injection(before, log, config) for before, config in stages)
    parameters = {
        "lifter": development_value(family.params), "design": development_value(family.design),
        "injections": [{"kind": type(config).__name__, "parameters": development_value(config)} for config in family.injections],
    }
    return DevelopmentScenario(scenario_id, family.family_id, seed, family.planning_family().requests, log, observations, parameters)


def injected_coverage(scenarios: Sequence[DevelopmentScenario]) -> QuotaCounts:
    """Count only configured patterns actually observed after all transformations."""
    if not all(isinstance(item, DevelopmentScenario) for item in scenarios):
        raise TypeError("injected coverage requires DevelopmentScenario")
    if len({item.scenario_id for item in scenarios}) != len(scenarios):
        raise ValueError("scenario identifiers must be unique")
    return QuotaCounts(
        len(scenarios),
        {label: sum(label in item.injected_causes for item in scenarios) for label in HYPOTHESIS_LABELS},
        sum(any(observation.present and observation.request.abstention_cases for observation in item.observations) for item in scenarios),
        sum(any(observation.present and observation.request.confounders for observation in item.observations) for item in scenarios),
        sum(any(observation.present and observation.request.numeric_traps for observation in item.observations) for item in scenarios),
        len({item.cluster_id for item in scenarios}),
    )


@dataclass(frozen=True)
class DevelopmentBatch:
    scenarios: tuple[DevelopmentScenario, ...]
    planned: QuotaCounts
    injected: QuotaCounts

    def to_json_bytes(self) -> bytes:
        return json_bytes({
            "development_only": True, "planned_coverage": self.planned.to_dict(), "injected_coverage": self.injected.to_dict(),
            "expected_annotation_records": sum(item.expected_annotations is not None for item in self.scenarios),
            "scenarios": [item.to_dict() for item in self.scenarios],
        })


def generate_development_batch(
    families: Sequence[SimulationFamily], *, n: int, seed: int,
    requirements: QuotaRequirements | None = None,
) -> DevelopmentBatch:
    """Generate actual development logs with planned and realized quota coverage.

    No pool, annotation or export integration is substituted here. The returned
    data remains explicitly non-evaluation data with pending final decisions.
    """
    if not families or not all(isinstance(item, SimulationFamily) for item in families):
        raise ValueError("at least one SimulationFamily is required")
    required = QuotaRequirements() if requirements is None else requirements
    plans = allocate_development_cases([item.planning_family() for item in families], n=n, seed=seed, requirements=required)
    by_family = {item.family_id: item for item in families}
    scenarios = []
    for plan in plans:
        digest = hashlib.sha256(f"{seed}:{plan.plan_id}".encode("utf-8")).digest()
        case_seed = int.from_bytes(digest[:8], "big")
        scenarios.append(simulate_family(by_family[plan.cluster_id], seed=case_seed, scenario_id=plan.plan_id))
    realized = injected_coverage(scenarios)
    missing = quota_shortfalls(realized, required)
    if missing:
        raise ValueError(f"injected development coverage is below the requested quotas: {missing}")
    return DevelopmentBatch(tuple(scenarios), planned_coverage(plans), realized)
