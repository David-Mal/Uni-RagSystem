"""Tests for src.schemas: enums, models, JSON Schema export (issue F2)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from src.schemas import (
    EXERCISE_IDS_CONTEXT_KEY,
    SCHEMA_VERSION,
    VALUE_ID_PATTERN,
    Claim,
    EvidenceLevel,
    ExtractionResult,
    HypothesisLabel,
    KinematicObservation,
    Load,
    Outcome,
    TriageLevel,
    at_least,
    extraction_json_schema,
    max_level,
    read_triage_level,
)
from src.schemas.json_schema import EXPORTED_MODELS, export_schemas, render_schema

REPO_ROOT = Path(__file__).resolve().parents[2]

# Example item from plan §3.3:
# "Bench 80 kg x 5 @8, last rep was a grind. Left shoulder a bit achy since Tuesday."
PLAN_EXAMPLE = {
    "exercise_id": "Barbell_Bench_Press_-_Medium_Grip",
    "kinematic_observation": "grinding_rep",
    "load": {"value": 80, "unit": "kg"},
    "reps": 5,
    "outcome": "completed",
    "rpe": 8,
    "triage_level": "yellow",
}

VALID_CLAIM = {
    "hypothesis_label": "fatigue_accumulation",
    "evidence_level": "supported",
    "exercise_id": "Barbell_Squat",
    "numbers": ["v_e1rm_slope_0007", "v_rpe_drift_0003"],
    "citations": ["syn03#c04"],
    "text": "RPE at comparable load rose over the last four weeks while e1RM stayed flat.",
}


# ---------- enums ----------


def test_enum_values_are_frozen_v0() -> None:
    assert SCHEMA_VERSION == "v0"
    assert [m.value for m in TriageLevel] == ["green", "yellow", "red"]
    assert [m.value for m in Outcome] == ["completed", "failed", "partial"]
    assert [m.value for m in KinematicObservation] == [
        "none",
        "slow_bar_speed",
        "grinding_rep",
        "reduced_range_of_motion",
        "lost_balance",
        "other",
    ]
    assert [m.value for m in HypothesisLabel] == [
        "insufficient_weekly_volume",
        "fatigue_accumulation",
        "stagnant_load_progression",
        "load_spike",
        "inconsistent_frequency",
        "logging_quality_issue",
        "confounder_present",
    ]
    assert [m.value for m in EvidenceLevel] == ["supported", "weak", "insufficient"]


def test_max_level_takes_most_severe() -> None:
    assert max_level(["green", "green"]) is TriageLevel.GREEN
    assert max_level([TriageLevel.GREEN, "yellow"]) is TriageLevel.YELLOW
    assert max_level(["yellow", "red", "green"]) is TriageLevel.RED


def test_max_level_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        max_level([])


def test_at_least_raises_but_never_lowers() -> None:
    # failed model signal + surviving green -> yellow (plan §5.3)
    assert at_least("green", "yellow") is TriageLevel.YELLOW
    assert at_least("red", "yellow") is TriageLevel.RED


# ---------- ExtractionResult ----------


def test_plan_example_item_validates() -> None:
    result = ExtractionResult.model_validate(PLAN_EXAMPLE)
    assert result.load == Load(value=80, unit="kg")
    assert result.triage_level is TriageLevel.YELLOW


def test_plan_example_validates_against_id_set() -> None:
    ids = {"Barbell_Bench_Press_-_Medium_Grip", "Barbell_Squat"}
    ExtractionResult.model_validate(PLAN_EXAMPLE, context={EXERCISE_IDS_CONTEXT_KEY: ids})


def test_minimal_unknown_exercise_without_numbers() -> None:
    result = ExtractionResult.model_validate(
        {
            "exercise_id": "unknown",
            "kinematic_observation": "none",
            "load": None,
            "reps": None,
            "outcome": "completed",
            "rpe": None,
            "triage_level": "green",
        },
        context={EXERCISE_IDS_CONTEXT_KEY: set()},  # unknown is legal even with an empty id set
    )
    assert result.exercise_id == "unknown"


@pytest.mark.parametrize(
    ("patch", "why"),
    [
        ({"exercise_id": "Bench Press"}, "space is not a valid id character"),
        ({"exercise_id": ""}, "empty id"),
        ({"kinematic_observation": "bad_form"}, "not in the enum (no form diagnosis)"),
        ({"triage_level": "orange"}, "not a triage level"),
        ({"outcome": "done"}, "not an outcome"),
        ({"load": {"value": 80, "unit": "stone"}}, "unit must be kg or lb"),
        ({"load": {"value": -5, "unit": "kg"}}, "negative load"),
        ({"reps": -1}, "negative reps"),
        ({"rpe": 10.5}, "rpe above 10"),
        ({"rpe": -0.5}, "rpe below 0"),
        ({"comment": "extra"}, "extra keys are forbidden"),
    ],
)
def test_invalid_extraction_results(patch: dict, why: str) -> None:
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({**PLAN_EXAMPLE, **patch})


def test_missing_triage_level_is_invalid() -> None:
    # The gate's failure policy depends on detecting a missing triage level (plan §5.3).
    data = {k: v for k, v in PLAN_EXAMPLE.items() if k != "triage_level"}
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(data)


def test_exercise_id_outside_provided_id_set_is_invalid() -> None:
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(PLAN_EXAMPLE, context={EXERCISE_IDS_CONTEXT_KEY: {"Barbell_Squat"}})


def test_extraction_result_round_trips_json() -> None:
    result = ExtractionResult.model_validate(PLAN_EXAMPLE)
    assert ExtractionResult.model_validate_json(result.model_dump_json()) == result


# ---------- Claim ----------


def test_plan_example_claim_validates() -> None:
    claim = Claim.model_validate(VALID_CLAIM)
    assert claim.hypothesis_label is HypothesisLabel.FATIGUE_ACCUMULATION


def test_claim_without_exercise_numbers_or_citations() -> None:
    Claim.model_validate(
        {"hypothesis_label": "logging_quality_issue", "evidence_level": "weak", "text": "RPE is rarely logged."}
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"hypothesis_label": "overtraining"},
        {"evidence_level": "strong"},
        {"numbers": ["e1rm_slope"]},
        {"numbers": ["v_e1rm_slope_7"]},
        {"citations": ["syn03 c04"]},
        {"citations": [""]},
        {"text": ""},
        {"exercise_id": "Barbell Squat"},
    ],
)
def test_invalid_claims(patch: dict) -> None:
    with pytest.raises(ValidationError):
        Claim.model_validate({**VALID_CLAIM, **patch})


# ---------- JSON Schema ----------


def test_extraction_json_schema_restricts_exercise_id() -> None:
    schema = extraction_json_schema(["Barbell_Squat", "Barbell_Bench_Press_-_Medium_Grip", "Barbell_Squat"])
    assert schema["properties"]["exercise_id"]["enum"] == [
        "Barbell_Bench_Press_-_Medium_Grip",
        "Barbell_Squat",
        "unknown",
    ]
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(PLAN_EXAMPLE, schema)
    jsonschema.validate({**PLAN_EXAMPLE, "exercise_id": "unknown"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**PLAN_EXAMPLE, "exercise_id": "Dumbbell_Flyes"}, schema)


def test_extraction_json_schema_with_no_ids_allows_only_unknown() -> None:
    assert extraction_json_schema([])["properties"]["exercise_id"]["enum"] == ["unknown"]


def test_exported_schemas_are_valid_and_reject_bad_input(tmp_path: Path) -> None:
    paths = export_schemas(tmp_path)
    assert sorted(p.name for p in paths) == ["claim.json", "extraction_result.json", "load.json"]
    extraction = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(extraction)
    assert extraction["$comment"] == "schema_version=v0"
    jsonschema.validate(PLAN_EXAMPLE, extraction)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**PLAN_EXAMPLE, "triage_level": "orange"}, extraction)
    claim = json.loads((tmp_path / "claim.json").read_text(encoding="utf-8"))
    jsonschema.validate(VALID_CLAIM, claim)


def test_committed_schemas_are_up_to_date() -> None:
    for stem, model in EXPORTED_MODELS.items():
        committed = (REPO_ROOT / "schemas" / f"{stem}.json").read_text(encoding="utf-8")
        assert committed == render_schema(model), f"schemas/{stem}.json is stale: run scripts/export_schemas.py"


# ---------- review #69: required keys, strict numbers, minor fixes ----------

ALL_KEYS = ["exercise_id", "kinematic_observation", "load", "reps", "outcome", "rpe", "triage_level"]


def test_cd_schema_requires_all_seven_keys_but_allows_null() -> None:
    schema = extraction_json_schema(["Barbell_Squat"])
    assert schema["required"] == ALL_KEYS
    for key in ("load", "reps", "rpe"):
        missing = {k: v for k, v in PLAN_EXAMPLE.items() if k != key}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(missing, schema)
        jsonschema.validate({**PLAN_EXAMPLE, "exercise_id": "unknown", key: None}, schema)


@pytest.mark.parametrize("key", ["load", "reps", "rpe"])
def test_model_requires_nullable_keys(key: str) -> None:
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({k: v for k, v in PLAN_EXAMPLE.items() if k != key})


@pytest.mark.parametrize(
    "patch",
    [
        {"load": {"value": float("inf"), "unit": "kg"}},
        {"load": {"value": float("nan"), "unit": "kg"}},
        {"load": {"value": True, "unit": "kg"}},
        {"load": {"value": "80", "unit": "kg"}},
        {"rpe": True},
        {"rpe": "8"},
        {"rpe": float("nan")},
        {"reps": True},
        {"reps": "5"},
        {"reps": 5.0},
    ],
)
def test_numbers_are_strict(patch: dict) -> None:
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({**PLAN_EXAMPLE, **patch})


def test_json_overflow_is_rejected_and_ints_are_accepted_as_floats() -> None:
    bad = json.dumps(PLAN_EXAMPLE).replace('"value": 80', '"value": 1e999')
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate_json(bad)
    ok = ExtractionResult.model_validate_json(json.dumps(PLAN_EXAMPLE))  # value 80, rpe 8 written as ints
    assert ok.load is not None and ok.load.value == 80.0 and ok.rpe == 8.0
    assert ExtractionResult.model_validate_json(ok.model_dump_json()) == ok


def test_string_id_set_is_rejected_not_matched_as_substring() -> None:
    with pytest.raises((TypeError, ValidationError)):
        ExtractionResult.model_validate(
            {**PLAN_EXAMPLE, "exercise_id": "Squat"}, context={EXERCISE_IDS_CONTEXT_KEY: "Barbell_Squat"}
        )
    with pytest.raises(TypeError):
        extraction_json_schema("Barbell_Squat")


@pytest.mark.parametrize("value", ["Unknown", "UNKNOWN"])
def test_unknown_must_be_lowercase(value: str) -> None:
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({**PLAN_EXAMPLE, "exercise_id": value})


def test_claim_schema_carries_id_patterns_and_rejects_blank_text() -> None:
    claim = json.loads(render_schema(Claim))
    assert claim["properties"]["numbers"]["items"]["pattern"] == VALUE_ID_PATTERN
    assert "pattern" in claim["properties"]["citations"]["items"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**VALID_CLAIM, "numbers": ["e1rm"]}, claim)
    with pytest.raises(ValidationError):
        Claim.model_validate({**VALID_CLAIM, "text": "   "})


def test_read_triage_level_survives_other_invalid_fields() -> None:
    raw = {**PLAN_EXAMPLE, "triage_level": "red", "rpe": 11}
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(raw)
    assert read_triage_level(raw) is TriageLevel.RED
    assert read_triage_level({"triage_level": "orange"}) is None
    assert read_triage_level("red") is None
