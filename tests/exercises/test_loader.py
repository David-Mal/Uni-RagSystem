"""Tests for free-exercise-db offline loader (issue D7, #12)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.exercises.loader import (
    DEFAULT_DB_PATH,
    Exercise,
    Muscle,
    diff,
    exercise_ids,
    load_exercises,
    muscle_weights,
)


def test_source_md_present_and_complete() -> None:
    source_md = DEFAULT_DB_PATH.parent / "SOURCE.md"
    assert source_md.exists()
    content = source_md.read_text(encoding="utf-8")
    assert "yuhonas/free-exercise-db" in content
    assert "Unlicense" in content
    assert "`f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5`" in content
    assert re.search(r"`[0-9a-f]{40}`", content)


def test_loads_all_entries_with_unique_ids() -> None:
    exercises = load_exercises()
    assert len(exercises) >= 800
    ids = exercise_ids(exercises)
    assert len(ids) == len(exercises)
    assert len(set(ids)) == len(ids)


def test_muscle_enum_has_17_values() -> None:
    assert len(Muscle) == 17
    expected = {
        "abdominals",
        "abductors",
        "adductors",
        "biceps",
        "calves",
        "chest",
        "forearms",
        "glutes",
        "hamstrings",
        "lats",
        "lower back",
        "middle back",
        "neck",
        "quadriceps",
        "shoulders",
        "traps",
        "triceps",
    }
    assert {m.value for m in Muscle} == expected


def test_null_optional_fields_handled() -> None:
    exercises = load_exercises()
    assert any(ex.force is None for ex in exercises.values())
    assert any(ex.mechanic is None for ex in exercises.values())
    assert any(ex.equipment is None for ex in exercises.values())


def test_muscle_weights_for_known_exercise() -> None:
    exercises = load_exercises()
    bench_id = "Barbell_Bench_Press_-_Medium_Grip"
    assert bench_id in exercises
    weights = muscle_weights(bench_id, exercises)
    assert weights[Muscle.CHEST] == 1.0
    assert weights[Muscle.SHOULDERS] == 0.5
    assert weights[Muscle.TRICEPS] == 0.5


def test_muscle_weights_unknown_raises() -> None:
    with pytest.raises(KeyError):
        muscle_weights("NonExistent_Exercise_XYZ")


def test_diff_detects_added_removed_and_changed() -> None:
    ex_a = Exercise(
        id="Ex_A",
        name="Exercise A",
        force="push",
        level="beginner",
        mechanic="compound",
        equipment="barbell",
        primary_muscles=[Muscle.CHEST],
        secondary_muscles=[Muscle.TRICEPS],
        category="strength",
        instructions=["Step 1"],
    )
    ex_b = Exercise(
        id="Ex_B",
        name="Exercise B",
        force=None,
        level="intermediate",
        mechanic=None,
        equipment=None,
        primary_muscles=[Muscle.QUADRICEPS],
        secondary_muscles=[],
        category="strength",
        instructions=[],
    )
    ex_a_modified = ex_a.model_copy(update={"name": "Exercise A Updated"})
    ex_c = ex_b.model_copy(update={"id": "Ex_C", "name": "Exercise C"})

    old = {"Ex_A": ex_a, "Ex_B": ex_b}
    new = {"Ex_A": ex_a_modified, "Ex_C": ex_c}

    result = diff(old, new)
    assert result.added == ["Ex_C"]
    assert result.removed == ["Ex_B"]
    assert result.changed == ["Ex_A"]


def test_duplicate_id_raises(tmp_path: Path) -> None:
    bad_file = tmp_path / "dup.json"
    bad_file.write_text(
        '[{"id":"Dup","name":"A","level":"beginner","category":"strength","primaryMuscles":[],"secondaryMuscles":[],"instructions":[]},'
        '{"id":"Dup","name":"B","level":"beginner","category":"strength","primaryMuscles":[],"secondaryMuscles":[],"instructions":[]}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate exercise id"):
        load_exercises(bad_file)
