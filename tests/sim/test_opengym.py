"""D2/D5 source contract checks, without importing protected ingestion dependencies."""

import ast
import csv
from dataclasses import replace
from datetime import timedelta
import io
from pathlib import Path

import pytest

from src.sim.injections import DuplicateSets, MissingRPE, MixedUnits, Outlier, apply_injection
from src.sim.opengym import COLUMNS_21, COLUMNS_26, ExerciseExport, SetExport, serialize_opengym
from src.sim.workouts import SimulatedLog, generate_workouts


def read_csv(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True))


def test_both_layouts_match_the_merged_d5_header_contract() -> None:
    # Inspect public adapter constants without executing src.ingest's package init.
    source = Path(__file__).resolve().parents[2] / "src/ingest/adapters/opengym.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    constants = {node.targets[0].id: ast.literal_eval(node.value.args[0])
                 for node in tree.body if isinstance(node, ast.Assign)
                 and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in {"REQUIRED_COLUMNS", "OPTIONAL_COLUMNS"}}
    assert set(COLUMNS_21) == constants["REQUIRED_COLUMNS"]
    assert set(COLUMNS_26) == constants["REQUIRED_COLUMNS"] | constants["OPTIONAL_COLUMNS"]


@pytest.mark.parametrize("variant", (21, 26))
def test_byte_stable_layout_bom_minutes_and_explicit_metadata(simulation_params, design, export_metadata, variant):
    log = generate_workouts(simulation_params, design, seed=3)
    metadata = replace(export_metadata, variant=variant)
    data = serialize_opengym(log, metadata)
    assert data == serialize_opengym(log, metadata)
    assert data.startswith(b"\xef\xbb\xbf") and data.endswith(b"\r\n")
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert len(data.decode("utf-8-sig").splitlines()[0].split(",")) == variant
    rows = read_csv(data)
    assert len(rows) == 8 * 2 * (3 + 2)  # 8 weeks, 2 workouts/week, 5 sets/workout.
    assert rows[0]["start_time"] == "2031-01-06 09:00"
    assert rows[0]["end_time"] == "2031-01-06 09:45"  # Explicit 45-minute workout.
    assert rows[0]["exercise_id"] == "9901"
    assert rows[0]["set"] == "1" and rows[3]["set"] == "1"
    assert rows[0]["weight"] == "50"  # 100 starting units * 0.5 multiplier; D2 uses integer spelling.
    assert rows[0]["reps"] == "5" and rows[0]["rpe"] == "6"
    assert rows[0]["rir"] == rows[0]["superset_id"] == rows[0]["side"] == ""
    assert metadata.match_exercise("Synthetic lift A") == metadata.exercises[0].canonical_exercise_id
    assert metadata.match_exercise("not mapped") is None


def test_duplicates_units_missing_rpe_and_outliers_are_not_repaired(simulation_params, design, export_metadata):
    log = generate_workouts(simulation_params, design, seed=3)
    for injection in (MixedUnits(2), Outlier("load", 9000), Outlier("rpe", 12), MissingRPE(3), DuplicateSets(1)):
        log = apply_injection(log, injection)
    rows = read_csv(serialize_opengym(log, export_metadata))
    assert len(rows) == 81 and rows[0] == rows[1]
    assert rows[0]["set"] == rows[1]["set"] == "1"
    assert {row["unit"] for row in rows} == {"kg", "lb"}
    assert rows[0]["weight"] == "9000" and rows[0]["rpe"] == ""
    log = apply_injection(log, Outlier("rpe", 12))
    assert read_csv(serialize_opengym(log, export_metadata))[0]["rpe"] == "12"


def test_failure_zero_reps_and_optional_fields(simulation_params, design, export_metadata):
    log = generate_workouts(simulation_params, design, seed=1)
    session = log.sessions[0]
    exercise = session.exercises[0]
    zero = replace(exercise.sets[0], reps=0)
    log = replace(log, sessions=(replace(session, exercises=(
        replace(exercise, sets=(zero, *exercise.sets[1:])), *session.exercises[1:],
    )), *log.sessions[1:]))
    metadata = replace(export_metadata, sets={
        exercise.sets[1].set_id: SetExport("failure", 0, 30, 'synthetic comma, quote "field"', "synthetic set field"),
        exercise.sets[2].set_id: SetExport("warmup"),
    })
    rows = read_csv(serialize_opengym(log, metadata))
    assert rows[0]["reps"] == "0" and rows[0]["set_type"] == "normal"
    assert rows[1]["reps"] == "5" and rows[1]["set_type"] == "failure"
    assert rows[2]["set_type"] == "warmup"
    assert rows[1]["distance_km"] == "0" and rows[1]["seconds"] == "30"
    assert rows[1]["note"] == 'synthetic comma, quote "field"'
    assert rows[1]["set_note"] == "synthetic set field"


@pytest.mark.parametrize("field,value", (("load", -10), ("rpe", -2), ("load", 1e-20), ("load", 1e20)))
def test_extreme_and_negative_values_preserved_as_plain_decimals(simulation_params, design, export_metadata, field, value):
    log = apply_injection(generate_workouts(simulation_params, design, seed=1), Outlier(field, value))
    text = read_csv(serialize_opengym(log, export_metadata))[0]["weight" if field == "load" else "rpe"]
    assert float(text) == value and "e" not in text.lower()


def test_precision_collisions_and_unresolved_refs_rejected(simulation_params, design, export_metadata):
    log = generate_workouts(simulation_params, design, seed=1)
    for change in (timedelta(seconds=1), timedelta(microseconds=1)):
        bad = replace(log, sessions=(replace(log.sessions[0], at=log.sessions[0].at + change), *log.sessions[1:]))
        with pytest.raises(ValueError, match="minute precision"):
            serialize_opengym(bad, export_metadata)
    duplicate = replace(log.sessions[0], session_id="different internal ID")
    bad = SimulatedLog(tuple(sorted((duplicate, *log.sessions), key=lambda v: (v.at, v.session_id))))
    with pytest.raises(ValueError, match="collide"):
        serialize_opengym(bad, export_metadata)


def test_missing_mapping_and_unknown_canonical_id_rejected(simulation_params, design, export_metadata):
    log = generate_workouts(simulation_params, design, seed=1)
    with pytest.raises(ValueError, match="mapping"):
        serialize_opengym(log, replace(export_metadata, exercises=export_metadata.exercises[:1]))
    with pytest.raises(ValueError, match="D7"):
        export_metadata.validate_canonical_ids(set())
    with pytest.raises(ValueError, match="four-digit"):
        ExerciseExport("a", "1", "a", "a", "a")
    with pytest.raises(ValueError, match="set_note"):
        replace(export_metadata, variant=21, sets={"a": SetExport(set_note="synthetic")})
    with pytest.raises(ValueError, match="unsupported"):
        SetExport("drop")


def test_set_gaps_unknown_metadata_and_note_refs_fail_loudly(simulation_params, design, export_metadata):
    from src.sim.workouts import NoteTemplateRef
    log = generate_workouts(simulation_params, design, seed=1)
    session = log.sessions[0]
    exercise = session.exercises[0]
    gapped = replace(session, exercises=(replace(exercise, sets=exercise.sets[1:]), *session.exercises[1:]))
    with pytest.raises(ValueError, match="contiguous"):
        serialize_opengym(replace(log, sessions=(gapped, *log.sessions[1:])), export_metadata)
    with pytest.raises(ValueError, match="unknown set ID"):
        serialize_opengym(log, replace(export_metadata, sets={"unknown": SetExport()}))
    referenced = replace(session, note_refs=(NoteTemplateRef("synthetic-opaque-ref"),))
    with pytest.raises(ValueError, match="unresolved"):
        serialize_opengym(replace(log, sessions=(referenced, *log.sessions[1:])), export_metadata)
