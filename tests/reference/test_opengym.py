"""Tests of the OpenGym reader against docs/opengym-export-format.md and the trap fixtures."""

from pathlib import Path

import pytest

from src.reference import indicators as ref
from src.reference.opengym import read_opengym

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/opengym"


def read(name):
    return read_opengym(FIXTURES / name)


def test_real_exports():
    david, fineas = read("david_anonymized.csv"), read("fineas_anonymized.csv")
    assert (len(david), len(fineas)) == (211, 276)  # comparison table
    assert sum(r["failed"] for r in david) == 1 and sum(r["failed"] for r in fineas) == 0  # section 3
    assert all(r["rpe"] is None for r in david + fineas)  # section 4
    assert all(r["weight_kg"] is not None and r["reps"] is not None for r in david + fineas)
    # The only failure row: Barbell Close-Grip Bench Press, 45 kg x 10, taken to failure and completed
    failure = [r for r in david if r["set_type"] == "failure"]
    assert [(r["exercise_id"], r["failed"], r["weight_kg"], r["reps"]) for r in failure] == [("0030", False, 45, 10)]
    assert {r["set_type"] for r in fineas} == {"normal", "warmup"}


def test_real_export_load_is_too_short():
    # David's log spans 2026-11-05 to 2026-11-25: the first valid set is 20 days before as_of.
    with pytest.raises(ref.IndicatorError, match="insufficient_history"):
        ref.uncoupled_load(read("david_anonymized.csv"))


def test_traps():
    assert len(read("traps/duplicate_sets.csv")) == 4  # 5 rows, one repeated
    assert [r["failed"] for r in read("traps/failed_set.csv")] == [False, False, True]
    assert [r["rpe"] for r in read("traps/missing_rpe.csv")] == [8, None, 7.5, None]
    assert read("traps/unit_mix.csv")[1]["weight_kg"] == pytest.approx(102.05828325, abs=1e-9)  # 225 * 0.45359237
    assert read("traps/impossible_weight.csv")[0]["weight_kg"] == 5500  # value kept


def test_exercise_map():
    path = FIXTURES / "traps/failed_set.csv"
    assert {r["exercise_id"] for r in read_opengym(path)} == {"1452"}
    assert {r["exercise_id"] for r in read_opengym(path, {"1452": "Some_Id"})} == {"Some_Id"}
    assert {r["exercise_id"] for r in read_opengym(path, {})} == {None}


def test_unknown_unit_is_rejected(tmp_path):
    text = (FIXTURES / "traps/failed_set.csv").read_text(encoding="utf-8-sig").replace(",kg,", ",stone,", 1)
    path = tmp_path / "bad.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="unknown unit"):
        read_opengym(path)
