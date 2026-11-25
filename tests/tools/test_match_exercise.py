"""Tests for match_exercise_rag cascade (issue M1, #32)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.exercises.loader import load_exercises
from src.tools.match_exercise import (
    Candidate,
    load_aliases,
    match_exercise_id,
    match_exercise_rag,
    normalize_exercise_name,
)


class FakeRetriever:
    """Deterministic test retriever for Stage 3 tests."""

    def __init__(self, candidates: list[Candidate]) -> None:
        self._candidates = candidates

    def retrieve(self, query: str, k: int = 5) -> list[Candidate]:
        return self._candidates[:k]


def test_normalization_strips_parentheses_and_punctuation() -> None:
    assert normalize_exercise_name("Bench Press (Barbell)") == "bench press"
    assert normalize_exercise_name("Cable Rear Delt Row (With Rope)") == "cable rear delt row"
    assert normalize_exercise_name("T-Bar Row!") == "t bar row"


def test_all_aliases_map_to_valid_free_exercise_db_ids() -> None:
    exercises = load_exercises()
    aliases = load_aliases(exercises=exercises)
    assert len(aliases) >= 50
    for alias, ex_id in aliases.items():
        assert ex_id in exercises, f"Alias {alias!r} points to invalid id {ex_id!r}"


@pytest.mark.parametrize(
    ("raw_name", "expected_id"),
    [
        ("RDL", "Romanian_Deadlift"),
        ("OHP", "Standing_Military_Press"),
        ("T-bar", "T-Bar_Row_with_Handle"),
        ("DB Bench", "Dumbbell_Bench_Press"),
        ("BB Row", "Bent_Over_Barbell_Row"),
        ("BW Pull-Up", "Pullups"),
        ("SSB", "Barbell_Squat"),
    ],
)
def test_common_abbreviations_resolve_at_alias_stage(raw_name: str, expected_id: str) -> None:
    res = match_exercise_rag(raw_name)
    assert res.exercise_id == expected_id
    assert res.stage == "alias"
    assert res.score == 100.0


def test_real_export_hand_picked_cases() -> None:
    cases = {
        "Barbell Bench Press": "Barbell_Bench_Press_-_Medium_Grip",
        "Cable High Row (Kneeling)": "Kneeling_High_Pulley_Row",
        "Cable Triceps Pushdown (V-Bar)": "Triceps_Pushdown_-_V-Bar_Attachment",
        "Dumbbell Hammer Curls (With Arm Blaster)": "Hammer_Curls",
        "Lever Leg Extension": "Leg_Extensions",
        "Weighted Pull-Up": "Weighted_Pull_Ups",
    }
    for raw, expected in cases.items():
        res = match_exercise_rag(raw)
        assert res.exercise_id == expected
        assert res.stage == "alias"


def test_fuzzy_edge_around_threshold() -> None:
    exercises = load_exercises()
    # Slight typo on a real exercise name: should resolve via fuzzy stage at threshold 85
    # and fall through to unknown if threshold is raised above its score.
    query = "Barbell Incline Bench Pres"
    res_pass = match_exercise_rag(
        query,
        exercises=exercises,
        aliases={},
        config={"fuzzy_threshold": 85.0, "retrieval_threshold": 0.65, "top_k": 5},
    )
    assert res_pass.stage == "fuzzy"
    assert res_pass.exercise_id != "unknown"
    assert res_pass.score >= 85.0

    res_fail = match_exercise_rag(
        query,
        exercises=exercises,
        aliases={},
        config={"fuzzy_threshold": res_pass.score + 0.5, "retrieval_threshold": 0.65, "top_k": 5},
    )
    assert res_fail.stage == "unknown"
    assert res_fail.exercise_id == "unknown"


def test_stage_3_retrieval_attribution() -> None:
    retriever = FakeRetriever(
        [Candidate(exercise_id="Barbell_Squat", score=0.82, name="Barbell Squat")]
    )
    res = match_exercise_rag(
        "Completely Custom Gym Name XYZ",
        aliases={},
        retriever=retriever,
        config={"fuzzy_threshold": 90.0, "retrieval_threshold": 0.65, "top_k": 5},
    )
    assert res.exercise_id == "Barbell_Squat"
    assert res.stage == "retrieval"
    assert res.score == 0.82


def test_unknown_path_when_all_stages_below_threshold() -> None:
    retriever = FakeRetriever(
        [Candidate(exercise_id="Barbell_Squat", score=0.30, name="Barbell Squat")]
    )
    res = match_exercise_rag(
        "Unrecognized Acrobatic Movement QQQ",
        retriever=retriever,
    )
    assert res.exercise_id == "unknown"
    assert res.stage == "unknown"


def test_empty_string_returns_unknown() -> None:
    res = match_exercise_rag("   ()  ")
    assert res.exercise_id == "unknown"
    assert res.stage == "unknown"
    assert res.score == 0.0


@pytest.mark.parametrize("name", ["Curl", "Row", "Press", "Triceps Extension", "Leg Curl", "Incline Row", "Dumbbell Row"])
def test_a_fragment_of_many_names_is_unknown(name: str) -> None:
    # token_set_ratio is 100 for each of these
    assert match_exercise_rag(name).exercise_id == "unknown"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Bench Press (Barbell)", "Barbell_Bench_Press_-_Medium_Grip"),
        ("Bench Press (Dumbbell)", "Dumbbell_Bench_Press"),
        ("Bench Press (Machine)", "Machine_Bench_Press"),
        ("Squat (Barbell)", "Barbell_Squat"),
        ("Deadlift (Barbell)", "Barbell_Deadlift"),
        ("Deadlift (Trap Bar)", "Trap_Bar_Deadlift"),
        ("Squat (Smith Machine)", "Smith_Machine_Squat"),
        ("Shoulder Press (Dumbbell)", "Dumbbell_Shoulder_Press"),
        ("Barbel Squat", "Barbell_Squat"),
        ("Dumbell Shrug", "Dumbbell_Shrug"),
    ],
)
def test_equipment_in_parentheses_counts(name: str, expected: str) -> None:
    assert match_exercise_rag(name).exercise_id == expected


@pytest.mark.parametrize("name", ["Deadlift (Suitcase)", "Bench Press (Band)", "Squat (Kettlebell)"])
def test_parentheses_are_never_dropped_to_force_a_match(name: str) -> None:
    assert match_exercise_rag(name).exercise_id not in {
        "Barbell_Deadlift", "Barbell_Squat", "Barbell_Bench_Press_-_Medium_Grip",
    }  # fmt: skip


def test_conflicting_aliases_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.yaml"
    path.write_text('aliases:\n  "Squat": Barbell_Squat\n  "squat!": Leg_Press\n', encoding="utf-8")
    with pytest.raises(ValueError, match="maps to both"):
        load_aliases(path)


def test_every_name_of_the_real_exports() -> None:
    names = set()
    for who in ("david", "fineas"):
        path = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "opengym" / f"{who}_anonymized.csv"
        with path.open(encoding="utf-8-sig", newline="") as stream:
            names |= {row["exercise"] for row in csv.DictReader(stream)}
    unknown = {n for n in names if match_exercise_id(n) == "unknown"}
    assert len(names) == 41 and unknown == {"Cable Leaning Lateral Raise"}
