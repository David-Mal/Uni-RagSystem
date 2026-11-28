"""Real D4/D5 round trips using isolated synthetic development sets.

Normal ingestion transitively imports src.tools.common.Value. This shared model
import is authorized for verification; no numerical tool is invoked or mocked.
"""

from dataclasses import replace

import pytest

from src.sim.injections import DuplicateSets, MissingRPE, MixedUnits, Outlier, apply_injection
from src.sim.opengym import SetExport, serialize_opengym
from src.sim.workouts import generate_workouts

def ingest_twice(tmp_path, log, metadata):
    from src.ingest.pipeline import ingest_workout_log
    from src.ingest.store import open_store
    path = tmp_path / "synthetic.csv"
    path.write_bytes(serialize_opengym(log, metadata))
    store = open_store(tmp_path / "synthetic.duckdb")
    first = ingest_workout_log(path, store=store, matcher=metadata.match_exercise, log_id="synthetic-fi2")
    second = ingest_workout_log(path, store=store, matcher=metadata.match_exercise, log_id="synthetic-fi2")
    return store, first, second


def test_normalization_resolution_duplicates_and_storage_idempotence(simulation_params, design, export_metadata, tmp_path):
    log = generate_workouts(simulation_params, design, seed=1)
    for injection in (MixedUnits(2), MissingRPE(3), DuplicateSets(1)):
        log = apply_injection(log, injection)
    store, first, second = ingest_twice(tmp_path, log, export_metadata)
    try:
        sets = store.get_sets(first.log_id)
        assert first.counts["rows_read"] == 81 and first.counts["sets_added"] == 80
        assert first.counts["duplicates"] == 1 and second.counts["sets_added"] == 0
        assert len(sets) == 80 and not first.unmatched_names
        first_set = next(v for v in sets if v.workout_ts == design.start and v.set_index == 1
                         and v.exercise_name_raw == "Synthetic lift A")
        # 100 * 0.5 = 50 kg; source lb value is 50 / 0.45359237.
        assert first_set.weight_kg == pytest.approx(50)
        assert first_set.source_unit == "lb" and first_set.rpe is None
        assert first_set.exercise_id == export_metadata.exercises[0].canonical_exercise_id
        assert {flag.code for flag in first.flags} >= {"duplicate_set", "unit_mix"}
    finally:
        store.close()


def test_positive_outlier_kept_invalid_rpe_flagged(simulation_params, design, export_metadata, tmp_path):
    log = generate_workouts(simulation_params, design, seed=1)
    log = apply_injection(apply_injection(log, Outlier("load", 9000)), Outlier("rpe", 12))
    store, first, _ = ingest_twice(tmp_path, log, export_metadata)
    try:
        assert any(v.weight_kg == 9000 and v.rpe is None for v in store.get_sets(first.log_id))
        assert {flag.code for flag in first.flags} >= {"implausible_weight", "implausible_rpe"}
    finally:
        store.close()


def test_failure_and_warmup_canonical_semantics(simulation_params, design, export_metadata, tmp_path):
    from src.ingest.adapters.opengym import OpenGymAdapter
    log = generate_workouts(simulation_params, design, seed=1)
    session = log.sessions[0]
    exercise = session.exercises[0]
    log = replace(log, sessions=(replace(session, exercises=(replace(exercise, sets=(
        replace(exercise.sets[0], reps=0), *exercise.sets[1:],
    )), *session.exercises[1:])), *log.sessions[1:]))
    metadata = replace(export_metadata, sets={exercise.sets[1].set_id: SetExport("failure"),
                                              exercise.sets[2].set_id: SetExport("warmup")})
    path = tmp_path / "synthetic.csv"
    path.write_bytes(serialize_opengym(log, metadata))
    canonical = OpenGymAdapter().to_canonical(path)
    assert canonical.sets[0].failed and canonical.sets[0].reps == 0
    assert canonical.sets[1].set_type.value == "failure" and not canonical.sets[1].failed
    assert canonical.sets[2].set_type.value == "warmup" and not canonical.sets[2].failed


def test_negative_trap_rejected_without_storage_repair(simulation_params, design, export_metadata, tmp_path):
    from src.ingest.errors import IngestError
    from src.ingest.pipeline import ingest_workout_log
    from src.ingest.store import open_store
    log = apply_injection(generate_workouts(simulation_params, design, seed=1), Outlier("load", -10))
    path = tmp_path / "synthetic.csv"
    path.write_bytes(serialize_opengym(log, export_metadata))
    store = open_store(tmp_path / "synthetic.duckdb")
    try:
        with pytest.raises(IngestError):
            ingest_workout_log(path, store=store, matcher=export_metadata.match_exercise, log_id="synthetic")
        assert not store.get_sets("synthetic")
    finally:
        store.close()
