"""Tests for check_data_sufficiency boundary semantics (issue M2, #33)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from src.tools.sufficiency import check_data_sufficiency


class InMemoryStore:
    """Minimal store stub implementing the D4 get_sets protocol."""

    def __init__(self, sets_by_log: dict[str, list[dict[str, Any]]]) -> None:
        self._sets_by_log = sets_by_log

    def get_sets(
        self, log_id: str, filters: Mapping[str, Any] | None = None
    ) -> Iterable[dict[str, Any]]:
        return list(self._sets_by_log.get(log_id, []))


def _make_set(
    day_offset: int,
    *,
    exercise_id: str | None = "Barbell_Bench_Press_-_Medium_Grip",
    weight_kg: float = 100.0,
    reps: int = 5,
    rpe: float | None = 8.0,
    set_type: str = "normal",
    failed: bool = False,
    base: datetime = datetime(2026, 10, 1, 10, 0),
) -> dict[str, Any]:
    return {
        "set_id": f"s_{day_offset}_{exercise_id}_{set_type}_{reps}",
        "log_id": "log1",
        "workout_ts": base + timedelta(days=day_offset),
        "exercise_id": exercise_id,
        "weight_kg": weight_kg,
        "reps": reps,
        "rpe": rpe,
        "set_type": set_type,
        "failed": failed,
    }


def _full_valid_log() -> list[dict[str, Any]]:
    # 6 sessions spaced 7 days apart -> span = 35 days (exact 5 weeks), no gap > 14d,
    # 6 sessions in last 6 weeks (>= 4), 100% RPE, 6 comparable-load sessions.
    return [_make_set(day_offset=d) for d in (0, 7, 14, 21, 28, 35)]


def test_all_checks_pass_at_exact_boundaries() -> None:
    store = InMemoryStore({"log1": _full_valid_log()})
    res = check_data_sufficiency(store, "log1")
    assert res.sufficient is True
    assert res.partial_abstention is False
    assert res.reasons == []
    assert set(res.allowed_analyses) == {"e1rm_trend", "rpe_drift", "weekly_volume", "load_ratio"}


def test_history_span_boundary_34_vs_35_days() -> None:
    # 34 days -> just below 5 weeks (35 days): load_ratio blocked, partial abstention
    sets_34 = [_make_set(day_offset=d) for d in (0, 7, 14, 21, 28, 34)]
    res_34 = check_data_sufficiency(InMemoryStore({"log1": sets_34}), "log1")
    assert res_34.sufficient is True
    assert res_34.partial_abstention is True
    assert "load_ratio" not in res_34.allowed_analyses
    assert "e1rm_trend" in res_34.allowed_analyses
    assert any("34 days" in r for r in res_34.reasons)

    # 35 days -> exact boundary passes
    res_35 = check_data_sufficiency(InMemoryStore({"log1": _full_valid_log()}), "log1")
    assert "load_ratio" in res_35.allowed_analyses


def test_sessions_per_exercise_boundary_3_vs_4() -> None:
    # 3 working sessions + 1 warmup + 1 failed -> still only 3 valid sessions (< 4)
    sets_3 = [
        _make_set(0),
        _make_set(12),
        _make_set(24),
        _make_set(30, set_type="warmup"),
        _make_set(32, failed=True),
        _make_set(35, reps=0),
    ]
    res_3 = check_data_sufficiency(InMemoryStore({"log1": sets_3}), "log1")
    assert "e1rm_trend" not in res_3.allowed_analyses
    assert "rpe_drift" not in res_3.allowed_analyses
    assert any("Maximum 3 sessions" in r for r in res_3.reasons)

    # 4 working sessions -> passes e1rm_trend
    sets_4 = [_make_set(d) for d in (0, 12, 24, 35)]
    res_4 = check_data_sufficiency(InMemoryStore({"log1": sets_4}), "log1")
    assert "e1rm_trend" in res_4.allowed_analyses


def test_rpe_coverage_boundary_below_and_at_50_percent() -> None:
    # 2 of 6 working sets with RPE (33%) -> partial abstention, no rpe_drift
    sets_low_rpe = [
        _make_set(0, rpe=8.0),
        _make_set(7, rpe=8.0),
        _make_set(14, rpe=None),
        _make_set(21, rpe=None),
        _make_set(28, rpe=None),
        _make_set(35, rpe=None),
    ]
    res_low = check_data_sufficiency(InMemoryStore({"log1": sets_low_rpe}), "log1")
    assert res_low.sufficient is True
    assert res_low.partial_abstention is True
    assert "rpe_drift" not in res_low.allowed_analyses
    assert "e1rm_trend" in res_low.allowed_analyses
    assert "RPE logged on 2 of 6 working sets; RPE drift not assessed" in res_low.reasons

    # Exact 50% (4 of 8 working sets with RPE at comparable load across 4 sessions) -> passes
    sets_50 = [
        _make_set(0, rpe=8.0),
        _make_set(0, rpe=None, reps=6),
        _make_set(10, rpe=8.5),
        _make_set(10, rpe=None, reps=6),
        _make_set(22, rpe=8.5),
        _make_set(22, rpe=None, reps=6),
        _make_set(35, rpe=9.0),
        _make_set(35, rpe=None, reps=6),
    ]
    res_50 = check_data_sufficiency(InMemoryStore({"log1": sets_50}), "log1")
    assert "rpe_drift" in res_50.allowed_analyses


def test_comparable_load_boundary_3_vs_4_sessions() -> None:
    # 3 sessions within +-5% of 100kg (95, 100, 105) + 2 sessions outside (80, 120) -> fails drift
    sets_3_comp = [
        _make_set(0, weight_kg=95.0, rpe=8.0),
        _make_set(7, weight_kg=100.0, rpe=8.0),
        _make_set(14, weight_kg=105.0, rpe=8.5),
        _make_set(21, weight_kg=80.0, rpe=7.5),
        _make_set(35, weight_kg=120.0, rpe=9.5),
    ]
    res = check_data_sufficiency(InMemoryStore({"log1": sets_3_comp}), "log1")
    assert "rpe_drift" not in res.allowed_analyses
    assert any("comparable load" in r for r in res.reasons)


def test_gap_boundary_14_vs_15_days() -> None:
    # Gap of exactly 14 days -> passes
    sets_14 = [_make_set(d) for d in (0, 14, 21, 28, 35)]
    res_14 = check_data_sufficiency(InMemoryStore({"log1": sets_14}), "log1")
    assert res_14.sufficient is True
    assert res_14.reasons == []

    # Gap of 15 days -> fails
    sets_15 = [_make_set(d) for d in (0, 15, 22, 29, 36)]
    res_15 = check_data_sufficiency(InMemoryStore({"log1": sets_15}), "log1")
    assert res_15.sufficient is False
    assert res_15.allowed_analyses == []
    assert any("15 days" in r for r in res_15.reasons)


def test_unmatched_exercises_only_abstains() -> None:
    sets = [_make_set(d, exercise_id="unknown") for d in (0, 7, 14, 21, 28, 35)]
    res = check_data_sufficiency(InMemoryStore({"log1": sets}), "log1")
    assert res.sufficient is False
    assert res.allowed_analyses == []
    assert any("Matched exercises: 0" in r for r in res.reasons)


def test_allowed_exercise_ids_filter_yellow_exclusion() -> None:
    # Squat has 6 sessions, Bench has 0 -> excluding Squat leaves no working sets
    sets = [_make_set(d, exercise_id="Barbell_Squat") for d in (0, 7, 14, 21, 28, 35)]
    res = check_data_sufficiency(
        InMemoryStore({"log1": sets}),
        "log1",
        allowed_exercise_ids=["Barbell_Bench_Press_-_Medium_Grip"],
    )
    assert res.sufficient is False
    assert res.allowed_analyses == []
