"""Strong and Hevy end to end through the ingest pipeline (issue D6, after D4)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from src.ingest import IngestError, SetType, SourceProbe, ingest_workout_log, open_store
from src.ingest.adapters.hevy import HevyAdapter
from src.ingest.adapters.opengym import OpenGymAdapter
from src.ingest.adapters.strong import StrongAdapter
from src.tools.match_exercise import match_exercise_id

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures"
STRONG = FIXTURES / "strong" / "synthetic.csv"
HEVY = FIXTURES / "hevy" / "synthetic.csv"


@pytest.fixture
def store():
    with open_store() as db:
        yield db


def test_strong_end_to_end(store) -> None:
    r = ingest_workout_log(STRONG, log_id="u", store=store, unit_hint="kg", matcher=match_exercise_id)
    assert r.source_app == "strong" and r.counts["sets_added"] == 12 and r.counts["workouts_added"] == 2
    assert r.flags == []
    sets = store.get_sets("u")
    assert sets[0].workout_ts == datetime(2026, 11, 10, 18) and sets[0].weight_kg == 60 and sets[0].rpe == 7
    assert {s.set_type for s in sets} == {SetType.NORMAL}
    assert [(s.exercise_name_raw, s.set_index) for s in sets if s.failed] == [("Deadlift", 3)]
    assert r.unmatched_names == []
    assert Counter(n.scope for n in r.notes) == {"workout": 2, "exercise": 5}


def test_hevy_end_to_end(store) -> None:
    r = ingest_workout_log(HEVY, log_id="u", store=store, matcher=match_exercise_id)
    assert r.source_app == "hevy" and r.counts["sets_added"] == 12 and r.flags == []
    types = Counter(s.set_type for s in store.get_sets("u"))
    assert types == {SetType.WARMUP: 2, SetType.NORMAL: 8, SetType.DROP: 1, SetType.FAILURE: 1}
    assert [s.reps for s in store.get_sets("u") if s.failed] == [0]


@pytest.mark.parametrize("path", [STRONG, HEVY])
def test_reingest_is_idempotent(store, path: Path) -> None:
    for expected in (12, 0):
        assert ingest_workout_log(path, log_id="u", store=store, unit_hint="kg").counts["sets_added"] == expected


def test_strong_without_a_unit_asks_for_one(store) -> None:
    with pytest.raises(IngestError, match="unit_hint"):
        ingest_workout_log(STRONG, log_id="u", store=store)
    assert store.log_ids() == []


def test_strong_in_pounds(store) -> None:
    ingest_workout_log(STRONG, log_id="u", store=store, unit_hint="lb")
    first = store.get_sets("u")[0]
    assert first.weight_kg == pytest.approx(60 * 0.45359237) and first.source_unit == "lb"


def test_hevy_set_to_failure_with_reps_is_not_failed(
    store, write_csv: Callable[..., Path], hevy_values: dict[str, str]
) -> None:
    values = dict(hevy_values, set_type="failure", reps="8")
    ingest_workout_log(write_csv(tuple(values), [tuple(values.values())]), log_id="u", store=store)
    (s,) = store.get_sets("u")
    assert s.set_type is SetType.FAILURE and s.failed is False


def test_hevy_miles_and_pounds(store, write_csv: Callable[..., Path], hevy_values: dict[str, str]) -> None:
    values = {{"weight_kg": "weight_lbs", "distance_km": "distance_miles"}.get(k, k): v for k, v in hevy_values.items()}
    values["distance_miles"] = "2"
    ingest_workout_log(write_csv(tuple(values), [tuple(values.values())]), log_id="u", store=store)
    (s,) = store.get_sets("u")
    assert s.weight_kg == pytest.approx(102.0583, abs=1e-4)  # 225 * 0.45359237
    assert s.distance == pytest.approx(3.218688)  # 2 * 1.609344


@pytest.mark.parametrize("column", ["weight_kg", "reps"])
def test_negative_numbers_are_errors(
    store, write_csv: Callable[..., Path], hevy_values: dict[str, str], column: str
) -> None:
    values = dict(hevy_values) | {column: "-5"}
    with pytest.raises(IngestError, match="data row 1"):
        ingest_workout_log(write_csv(tuple(values), [tuple(values.values())]), log_id="u", store=store)


def test_rpe_out_of_range_is_flagged(store, write_csv: Callable[..., Path], hevy_values: dict[str, str]) -> None:
    values = dict(hevy_values, rpe="11")
    r = ingest_workout_log(write_csv(tuple(values), [tuple(values.values())]), log_id="u", store=store)
    assert [f.code for f in r.flags] == ["implausible_rpe"]


def test_each_file_is_detected_by_exactly_one_adapter() -> None:
    adapters = [OpenGymAdapter(), StrongAdapter(), HevyAdapter()]
    files = {STRONG: "strong", HEVY: "hevy", FIXTURES / "opengym" / "david_anonymized.csv": "opengym"}
    for path, app in files.items():
        probe = SourceProbe.from_path(path)
        assert [a.name for a in adapters if a.detect(probe)] == [app]
