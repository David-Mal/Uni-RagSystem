"""Simulation annotation contract, not a canonical ingest or tool result model.

Only the architecture's established labels, evidence levels and gate colors are
closed vocabularies here. No evidence, gate result or abstention is inferred.
"""

from dataclasses import dataclass, fields
from collections.abc import Mapping
import json
import math
from types import MappingProxyType
from typing import Literal, get_args

HypothesisLabel = Literal[
    "insufficient_weekly_volume",
    "fatigue_accumulation",
    "stagnant_load_progression",
    "load_spike",
    "inconsistent_frequency",
    "logging_quality_issue",
    "confounder_present",
]
EvidenceLevel = Literal["supported", "weak", "insufficient"]
GateOutcome = Literal["green", "yellow", "red"]
HYPOTHESIS_LABELS: tuple[str, ...] = get_args(HypothesisLabel)


def nonempty(value: object, name: str) -> None:
    """Reject absent identifiers/text without inventing an identifier grammar."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _check_json(value: object) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _check_json(item)
        return
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _check_json(item)
        return
    raise ValueError("injected parameters must contain finite JSON values")


def freeze_json(value: object) -> object:
    """Snapshot JSON-compatible input recursively, including nested arrays."""
    _check_json(value)
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


def thaw_json(value: object) -> object:
    """Return a detached mutable JSON representation of an immutable snapshot."""
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_json(item) for item in value]
    return value


def json_bytes(value: Mapping[str, object]) -> bytes:
    """Use fixed JSON formatting and LF, independent of the operating system."""
    _check_json(value)
    return (json.dumps(thaw_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


@dataclass(frozen=True)
class ExpectedHypothesis:
    label: HypothesisLabel
    evidence: EvidenceLevel

    def __post_init__(self) -> None:
        if self.label not in HYPOTHESIS_LABELS:
            raise ValueError("unknown hypothesis label; abstention is not a label")
        if self.evidence not in get_args(EvidenceLevel):
            raise ValueError("unknown evidence level")


@dataclass(frozen=True)
class GroundTruth:
    """Validate caller-supplied annotations, not their empirical correctness.

    Causes alone cannot create this record. Evidence and outcomes are required
    inputs from the eventual specification/review workflow. The two presence
    flags are explicit scenario annotations for the issue #25 quotas.
    """

    scenario_id: str
    expected_hypotheses: tuple[ExpectedHypothesis, ...]
    abstain: bool
    abstention_reasons: tuple[str, ...]
    gate_outcome: GateOutcome
    injected_parameters: Mapping[str, object]
    cluster_id: str
    has_confounder: bool
    has_numeric_trap: bool

    def __post_init__(self) -> None:
        nonempty(self.scenario_id, "scenario_id")
        nonempty(self.cluster_id, "cluster_id")
        if not isinstance(self.expected_hypotheses, tuple) or not all(
            isinstance(item, ExpectedHypothesis) for item in self.expected_hypotheses
        ):
            raise ValueError("expected_hypotheses must be a tuple of ExpectedHypothesis")
        labels = [item.label for item in self.expected_hypotheses]
        if len(labels) != len(set(labels)):
            raise ValueError("a hypothesis may occur only once per scenario")
        for name in ("abstain", "has_confounder", "has_numeric_trap"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if not isinstance(self.abstention_reasons, tuple):
            raise ValueError("abstention_reasons must be a tuple")
        for reason in self.abstention_reasons:
            nonempty(reason, "abstention reason")
        if self.abstain and not self.abstention_reasons:
            raise ValueError("abstention requires an explicit reason")
        if self.gate_outcome not in get_args(GateOutcome):
            raise ValueError("unknown gate outcome")
        if not isinstance(self.injected_parameters, Mapping):
            raise ValueError("injected_parameters must be an object")
        _check_json(self.injected_parameters)
        object.__setattr__(self, "injected_parameters", freeze_json(self.injected_parameters))

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "expected_hypotheses": [
                {"label": item.label, "evidence": item.evidence} for item in self.expected_hypotheses
            ],
            "abstain": self.abstain,
            "abstention_reasons": list(self.abstention_reasons),
            "gate_outcome": self.gate_outcome,
            "injected_parameters": json.loads(json_bytes(self.injected_parameters)),
            "cluster_id": self.cluster_id,
            "has_confounder": self.has_confounder,
            "has_numeric_trap": self.has_numeric_trap,
        }

    def to_json_bytes(self) -> bytes:
        return json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "GroundTruth":
        if not isinstance(value, dict) or set(value) != {item.name for item in fields(cls)}:
            raise ValueError("ground truth has missing or unknown fields")
        data = dict(value)
        hypotheses = data["expected_hypotheses"]
        reasons = data["abstention_reasons"]
        if not isinstance(hypotheses, list) or not all(isinstance(item, dict) for item in hypotheses):
            raise ValueError("expected_hypotheses must be an array of objects")
        if any(set(item) != {"label", "evidence"} for item in hypotheses):
            raise ValueError("hypothesis objects require label and evidence only")
        if not isinstance(reasons, list):
            raise ValueError("abstention_reasons must be an array")
        data["expected_hypotheses"] = tuple(ExpectedHypothesis(**item) for item in hypotheses)
        data["abstention_reasons"] = tuple(reasons)
        return cls(**data)

    @classmethod
    def from_json_bytes(cls, value: bytes) -> "GroundTruth":
        return cls.from_dict(json.loads(value))
