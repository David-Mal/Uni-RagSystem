"""OpenGym adapter against the two real exports and the hand-edited traps (issue D5)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from src.ingest import IngestError, IngestResult, SetStore, SetType, SourceProbe, ingest_workout_log, open_store
from src.ingest.adapters.opengym import OpenGymAdapter

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "opengym"
DAVID = FIXTURES / "david_anonymized.csv"
FINEAS = FIXTURES / "fineas_anonymized.csv"
TRAPS = FIXTURES / "traps"


@pytest.fixture
def store():
    with open_store() as db:
        yield db


def ingest(store: SetStore, path: Path, log_id: str = "u") -> IngestResult:
    return ingest_workout_log(path, log_id=log_id, store=store)


def codes(result: IngestResult) -> list[str]:
    return [f.code for f in result.flags]


def edited(tmp_path: Path, **changes: str) -> Path:
    """David's file reduced to the header and its first row (line 2), with some cells replaced."""
    header, first, *_ = DAVID.read_text(encoding="utf-8-sig").splitlines()
    names, cells = header.split(","), first.split(",")
    for name, value in changes.items():
        cells[names.index(name)] = value
    path = tmp_path / "edited.csv"
    path.write_text(f"{header}\n{','.join(cells)}\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("path", "rows", "workouts", "notes"), [(DAVID, 211, 11, 2), (FINEAS, 276, 19, 0)], ids=["david", "fineas"]
)
def test_real_exports_end_to_end_without_losing_rows(
    store: SetStore, path: Path, rows: int, workouts: int, notes: int
) -> None:
    r = ingest(store, path)
    data_lines = len(path.read_text(encoding="utf-8-sig").splitlines()) - 1
    assert r.source_app == "opengym"
    assert r.counts["rows_read"] == r.counts["sets_added"] == len(store.get_sets("u")) == rows == data_lines
    assert (r.counts["workouts_added"], r.counts["duplicates"], len(r.notes)) == (workouts, 0, notes)
    assert r.flags == []

    again = ingest(store, path)  # idempotent
    assert (again.counts["sets_added"], again.counts["workouts_known"]) == (0, workouts)
    assert again.flags == [] and len(store.get_sets("u")) == rows


def test_set_types_and_failed_sets_in_real_exports(store: SetStore) -> None:
    ingest(store, DAVID, "d")
    ingest(store, FINEAS, "f")
    david, fineas = store.get_sets("d"), store.get_sets("f")
    assert Counter(s.set_type for s in david) == {SetType.NORMAL: 208, SetType.WARMUP: 2, SetType.FAILURE: 1}
    assert Counter(s.set_type for s in fineas) == {SetType.NORMAL: 266, SetType.WARMUP: 10}
    # The only failed set is the 0-rep crunch, 2026-11-13; the set taken to failure is not failed.
    assert [(s.exercise_name_raw, s.set_index, s.weight_kg) for s in david if s.failed] == [("Lever Seated Crunch", 3, 35)]
    assert not any(s.failed for s in fineas)
    to_failure = next(s for s in david if s.set_type is SetType.FAILURE)
    assert (to_failure.weight_kg, to_failure.reps, to_failure.failed) == (45, 10, False)


def test_hand_checked_rows(store: SetStore) -> None:
    ingest(store, DAVID, "d")
    ingest(store, FINEAS, "f")
    # david_anonymized.csv, last line
    last = store.get_sets("d")[-1]
    assert last.workout_ts == datetime(2026, 11, 25, 16, 8) and last.workout_name == "UpperBody2"
    assert last.exercise_name_raw == "Cable Standing Lat Pushdown (Rope Equipment)"
    assert (last.set_index, last.weight_kg, last.source_unit, last.reps, last.rpe) == (2, 70, "kg", 10, None)
    # fineas_anonymized.csv, lines 2 and 3 and the last line
    first, second, *_, end = store.get_sets("f")
    assert (first.workout_ts, first.workout_name) == (datetime(2026, 10, 26, 20, 14), "Upper1")
    assert (first.set_type, first.weight_kg, first.reps) == (SetType.WARMUP, 60, 10)
    assert (second.set_index, second.weight_kg, second.reps) == (2, 100, 9)
    assert (end.exercise_name_raw, end.weight_kg, end.reps) == ("Dumbbell Hammer Curls (With Arm Blaster)", 17.5, 9)
    # OpenGym's own catalog id never ends up in exercise_id
    assert {s.exercise_id for s in store.get_sets("d")} == {None}


def test_units_bodyweight_and_missing_rpe(store: SetStore) -> None:
    ingest(store, DAVID, "d")
    ingest(store, FINEAS, "f")
    every = store.get_sets("d") + store.get_sets("f")
    assert {s.source_unit for s in every} == {"kg"}
    assert {s.rpe for s in every} == {None}
    assert sum(s.weight_kg == 0 for s in store.get_sets("d")) == 12
    assert sum(s.weight_kg == 0 for s in store.get_sets("f")) == 4


def test_workout_notes_are_kept_once_each(store: SetStore) -> None:
    r = ingest(store, DAVID)
    assert [(n.scope, f"{n.workout_ts:%Y-%m-%d}", n.text) for n in r.notes] == [
        ("workout", "2026-11-05", "Both sets 12 w 50 lat pulldowns"),
        ("workout", "2026-11-12", "Cable high row is lbs nu kg"),
    ]
    # The note contradicts the unit column; the weights stay as exported and unit_mix is not raised.
    rows = store.get_sets("u", {"exercise_name_raw": "Cable High Row (Kneeling)"})
    assert {s.weight_kg for s in rows} == {70, 80, 90}


def test_unmatched_names_are_all_raw_names_without_a_matcher(store: SetStore) -> None:
    assert len(ingest(store, DAVID, "d").unmatched_names) == 27
    assert len(ingest(store, FINEAS, "f").unmatched_names) == 21


def test_trap_duplicate_sets(store: SetStore) -> None:
    r = ingest(store, TRAPS / "duplicate_sets.csv")
    assert codes(r) == ["duplicate_set"] and (r.counts["rows_read"], r.counts["sets_added"]) == (5, 4)


def test_trap_unit_mix(store: SetStore) -> None:
    r = ingest(store, TRAPS / "unit_mix.csv")
    assert codes(r) == ["unit_mix"] and "Cable Triceps Pushdown (V-Bar)" in r.flags[0].detail
    pounds = next(s for s in store.get_sets("u") if s.source_unit == "lb")
    assert pounds.weight_kg == pytest.approx(102.0583, abs=1e-4)  # 225 * 0.45359237


def test_trap_failed_set(store: SetStore) -> None:
    ingest(store, TRAPS / "failed_set.csv")
    assert [(s.reps, s.failed) for s in store.get_sets("u")] == [(10, False), (10, False), (0, True)]


def test_trap_missing_rpe(store: SetStore) -> None:
    r = ingest(store, TRAPS / "missing_rpe.csv")
    assert r.flags == []
    assert [s.rpe for s in store.get_sets("u")] == [8, None, 7.5, None]


def test_trap_impossible_weight(store: SetStore) -> None:
    r = ingest(store, TRAPS / "impossible_weight.csv")
    assert codes(r) == ["implausible_weight"]
    assert [s.weight_kg for s in store.get_sets("u")] == [5500, 50]  # flagged, not changed


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"set_type": "dropset"}, "unknown set type"),
        ({"unit": "stone"}, "unknown weight unit"),
        ({"unit": ""}, "unknown weight unit"),
        ({"weight": "12;5"}, "weight"),
        ({"weight": "-5"}, "weight"),
        ({"weight": "nan"}, "weight"),
        ({"reps": "8.5"}, "reps"),
        ({"rpe": "8-9"}, "rpe"),
        ({"set": ""}, "set number"),
        ({"exercise": " "}, "exercise name"),
        ({"start_time": "05.11.2026 14:22"}, "cannot parse date"),
        ({"start_time": "2026-11-06 14:22"}, "does not match"),
    ],
)
def test_unexpected_cells_fail_loudly_with_the_line(
    store: SetStore, tmp_path: Path, changes: dict[str, str], message: str
) -> None:
    with pytest.raises(IngestError, match=f"line 2: .*{message}"):
        ingest(store, edited(tmp_path, **changes))
    assert store.log_ids() == []


def test_rpe_out_of_range_is_flagged(store: SetStore, tmp_path: Path) -> None:
    r = ingest(store, edited(tmp_path, rpe="80"))
    assert codes(r) == ["implausible_rpe"] and store.get_sets("u")[0].rpe is None


def test_set_and_exercise_notes_are_kept(store: SetStore, tmp_path: Path) -> None:
    r = ingest(store, edited(tmp_path, note="left elbow", set_note="slow", workout_note=""))
    assert [(n.scope, n.text) for n in r.notes] == [("exercise", "slow\nleft elbow")]


def test_rows_with_a_wrong_number_of_cells(store: SetStore, tmp_path: Path) -> None:
    for tail in (",extra", None):
        path = edited(tmp_path)
        header, line, *_ = path.read_text(encoding="utf-8").splitlines()
        bad = line + tail if tail else line.rsplit(",", 1)[0]
        path.write_text(f"{header}\n{bad}\n", encoding="utf-8")
        with pytest.raises(IngestError, match="number of columns"):
            ingest(store, path)


def test_detect_accepts_column_order_and_rejects_other_formats(tmp_path: Path) -> None:
    adapter = OpenGymAdapter()
    header = SourceProbe.from_path(DAVID).header
    assert header is not None

    def probe(columns: tuple[str, ...] | None) -> bool:
        return adapter.detect(SourceProbe(tmp_path, columns))

    assert probe(header) and probe(tuple(reversed(header)))
    assert probe(SourceProbe.from_path(FINEAS).header)
    assert not probe(None)
    assert not probe(())
    assert not probe(tuple(c for c in header if c != "unit"))
    assert not probe((*header, "new_column"))
    assert not probe((*header, "unit"))
    assert not probe(("Date", "Workout Name", "Exercise Name", "Set Order", "Weight", "Reps"))
