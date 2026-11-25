"""Tests for weekly_sets_per_muscle with hand-computed fixtures (issue M3, #34)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from src.tools.weekly_sets import weekly_sets_per_muscle


class InMemoryStore:
    def __init__(self, sets_by_log: dict[str, list[dict[str, Any]]]) -> None:
        self._sets_by_log = sets_by_log

    def get_sets(
        self, log_id: str, filters: Mapping[str, Any] | None = None
    ) -> Iterable[dict[str, Any]]:
        return list(self._sets_by_log.get(log_id, []))


def test_hand_computed_bench_press_fixture() -> None:
    """Hand-computed fixture from issue M3 description:

    Exercise: Barbell_Bench_Press_-_Medium_Grip
      primaryMuscles:   [chest]        -> weight 1.0 per effective set
      secondaryMuscles: [shoulders, triceps] -> weight 0.5 per effective set

    Sets in week starting Monday 2026-10-05 (logged on Wed 2026-10-07):
      - 3 normal sets at RPE 8.0  -> counted (3 effective sets)
      - 1 warm-up set at RPE 5.0  -> excluded (warmup)
      - 1 failed set at RPE 10.0  -> excluded (failed)
      - 1 normal set at RPE 6.5   -> excluded (RPE < 7.0)

    Expected arithmetic:
      chest:     3 * 1.0 = 3.0
      shoulders: 3 * 0.5 = 1.5
      triceps:   3 * 0.5 = 1.5
    """
    ts = datetime(2026, 10, 7, 18, 0)
    sets = [
        {"set_id": "s1", "workout_ts": ts, "exercise_id": "Barbell_Bench_Press_-_Medium_Grip", "set_type": "normal", "reps": 5, "rpe": 8.0, "failed": False},
        {"set_id": "s2", "workout_ts": ts, "exercise_id": "Barbell_Bench_Press_-_Medium_Grip", "set_type": "normal", "reps": 5, "rpe": 8.0, "failed": False},
        {"set_id": "s3", "workout_ts": ts, "exercise_id": "Barbell_Bench_Press_-_Medium_Grip", "set_type": "normal", "reps": 5, "rpe": 8.0, "failed": False},
        {"set_id": "s4", "workout_ts": ts, "exercise_id": "Barbell_Bench_Press_-_Medium_Grip", "set_type": "warmup", "reps": 8, "rpe": 5.0, "failed": False},
        {"set_id": "s5", "workout_ts": ts, "exercise_id": "Barbell_Bench_Press_-_Medium_Grip", "set_type": "normal", "reps": 3, "rpe": 10.0, "failed": True},
        {"set_id": "s6", "workout_ts": ts, "exercise_id": "Barbell_Bench_Press_-_Medium_Grip", "set_type": "normal", "reps": 8, "rpe": 6.5, "failed": False},
    ]

    res = weekly_sets_per_muscle(InMemoryStore({"log1": sets}), "log1", weeks=1)
    by_muscle = {cell.muscle: cell.effective_sets for cell in res.table}

    assert res.week_start_day == "monday"
    assert res.weeks_evaluated == ["2026-10-05"]
    assert by_muscle == {"chest": 3.0, "shoulders": 1.5, "triceps": 1.5}
    assert res.excluded_counts["warmup"] == 1
    assert res.excluded_counts["failed"] == 1
    assert res.excluded_counts["low_rpe"] == 1
    assert res.flags == []

    # Every cell has a unique value_id and provenance listing exactly s1, s2, s3
    value_ids = [v.value_id for v in res.values]
    assert len(value_ids) == len(set(value_ids)) == 3
    for val in res.values:
        assert val.provenance.input_row_ids == ["s1", "s2", "s3"]


def test_no_rpe_sets_are_counted_and_flagged() -> None:
    ts = datetime(2026, 10, 12, 10, 0)  # Monday
    sets = [
        {"set_id": "s1", "workout_ts": ts, "exercise_id": "Barbell_Squat", "set_type": "normal", "reps": 5, "rpe": None, "failed": False},
        {"set_id": "s2", "workout_ts": ts, "exercise_id": "Barbell_Squat", "set_type": "normal", "reps": 5, "rpe": None, "failed": False},
    ]
    res = weekly_sets_per_muscle(InMemoryStore({"log1": sets}), "log1", weeks=1)
    by_muscle = {cell.muscle: cell.effective_sets for cell in res.table}
    # Barbell_Squat: primary quadriceps (2 * 1.0 = 2.0), secondary calves/glutes/hamstrings/lower back (2 * 0.5 = 1.0)
    assert by_muscle["quadriceps"] == 2.0
    assert by_muscle["glutes"] == 1.0
    assert "no_rpe" in res.flags


def test_unknown_exercises_excluded_and_listed() -> None:
    ts = datetime(2026, 10, 12, 10, 0)
    sets = [
        {"set_id": "s1", "workout_ts": ts, "exercise_id": "unknown", "exercise_name_raw": "Weird Machine Fly", "set_type": "normal", "reps": 10, "rpe": 8.0, "failed": False},
        {"set_id": "s2", "workout_ts": ts, "exercise_id": "Barbell_Curl", "exercise_name_raw": "Barbell Curl", "set_type": "normal", "reps": 10, "rpe": 8.0, "failed": False},
    ]
    res = weekly_sets_per_muscle(InMemoryStore({"log1": sets}), "log1", weeks=1)
    assert res.unknown_exercises == ["Weird Machine Fly"]
    assert "unknown_exercises_excluded" in res.flags
    assert res.excluded_counts["unknown"] == 1
    by_muscle = {cell.muscle: cell.effective_sets for cell in res.table}
    assert by_muscle["biceps"] == 1.0


def test_multi_week_trend_upward() -> None:
    sets = [
        {"set_id": "w1_1", "workout_ts": datetime(2026, 10, 5, 10, 0), "exercise_id": "Barbell_Curl", "set_type": "normal", "reps": 10, "rpe": 8.0, "failed": False},
        {"set_id": "w2_1", "workout_ts": datetime(2026, 10, 12, 10, 0), "exercise_id": "Barbell_Curl", "set_type": "normal", "reps": 10, "rpe": 8.0, "failed": False},
        {"set_id": "w2_2", "workout_ts": datetime(2026, 10, 12, 10, 5), "exercise_id": "Barbell_Curl", "set_type": "normal", "reps": 10, "rpe": 8.5, "failed": False},
        {"set_id": "w2_3", "workout_ts": datetime(2026, 10, 12, 10, 10), "exercise_id": "Barbell_Curl", "set_type": "normal", "reps": 10, "rpe": 9.0, "failed": False},
    ]
    res = weekly_sets_per_muscle(InMemoryStore({"log1": sets}), "log1", weeks=2)
    assert res.weeks_evaluated == ["2026-10-05", "2026-10-12"]
    biceps_summary = next(m for m in res.summary["top_muscles"] if m["muscle"] == "biceps")
    assert biceps_summary["total_sets"] == 4.0
    assert biceps_summary["trend"] == "up"
