from typing import Callable

import pytest

from src.sim.schema import ExpectedHypothesis, GroundTruth, HYPOTHESIS_LABELS


@pytest.mark.parametrize("label", HYPOTHESIS_LABELS)
@pytest.mark.parametrize("evidence", ("supported", "weak", "insufficient"))
def test_established_vocabulary(label: str, evidence: str) -> None:
    assert ExpectedHypothesis(label, evidence).label == label


@pytest.mark.parametrize("label", ("abstain", "injury_prediction", ""))
def test_reject_non_hypothesis_labels(label: str) -> None:
    with pytest.raises(ValueError):
        ExpectedHypothesis(label, "supported")


@pytest.mark.parametrize("gate", ("green", "yellow", "red"))
def test_explicit_gate_and_json_round_trip(annotation: Callable[..., GroundTruth], gate: str) -> None:
    original = annotation(gate_outcome=gate, expected_hypotheses=(ExpectedHypothesis("load_spike", "weak"),))
    encoded = original.to_json_bytes()
    assert GroundTruth.from_json_bytes(encoded) == original
    assert encoded.endswith(b"\n") and b"\r" not in encoded


@pytest.mark.parametrize(
    "changes",
    [
        {"abstain": True},
        {"abstain": "false"},
        {"has_numeric_trap": 1},
        {"cluster_id": " "},
        {"scenario_id": ""},
        {"gate_outcome": "allow"},
        {"abstention_reasons": ("",)},
        {"injected_parameters": {"x": float("nan")}},
        {"injected_parameters": {"x": {1: "not a string key"}}},
        {"injected_parameters": {"x": object()}},
        {"expected_hypotheses": (ExpectedHypothesis("load_spike", "weak"),) * 2},
    ],
)
def test_reject_invalid_annotation(annotation: Callable[..., GroundTruth], changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        annotation(**changes)


def test_abstention_is_an_outcome(annotation: Callable[..., GroundTruth]) -> None:
    item = annotation(abstain=True, abstention_reasons=("unit-only reason supplied by caller",))
    assert item.expected_hypotheses == ()


def test_json_rejects_unknown_fields_and_invalid_input(annotation: Callable[..., GroundTruth]) -> None:
    data = annotation().to_dict()
    data["unexpected"] = True
    with pytest.raises(ValueError):
        GroundTruth.from_dict(data)
    with pytest.raises(ValueError):
        GroundTruth.from_json_bytes(b"not JSON")
    with pytest.raises(ValueError):
        ExpectedHypothesis("load_spike", "certain")


def test_parameter_snapshot_isolated_from_input(annotation: Callable[..., GroundTruth]) -> None:
    injected = {"unit": [2, 3]}
    item = annotation(injected_parameters=injected)
    injected["unit"].append(4)
    assert item.to_dict()["injected_parameters"] == {"unit": [2, 3]}


def test_nested_parameter_immutability(annotation: Callable[..., GroundTruth]) -> None:
    item = annotation(injected_parameters={"nested": {"items": [{"value": 4}]}})
    encoded = item.to_json_bytes()
    with pytest.raises(TypeError):
        item.injected_parameters["new"] = 1
    with pytest.raises(TypeError):
        item.injected_parameters["nested"]["items"][0]["value"] = 5
    with pytest.raises(AttributeError):
        item.injected_parameters["nested"]["items"].append(6)
    detached = item.to_dict()
    detached["injected_parameters"]["nested"]["items"][0]["value"] = 99
    assert item.to_json_bytes() == encoded
    assert GroundTruth.from_json_bytes(encoded) == item
