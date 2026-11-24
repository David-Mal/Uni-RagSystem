"""Tests for uncoupled_load_analyzer (issue F7). Hand-computed fixtures; arithmetic in comments.

as_of = 2026-03-31. days_before = (as_of - set_date).days.
Acute: days 0..6. Chronic: days 7..34 (28 days = 4 weeks). Day 35 and later: ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pytest

from src.tools._common_provisional import ToolError, ValueIdFactory
from src.tools.load import LoadResult, compute_uncoupled_load, uncoupled_load_analyzer

AS_OF = date(2026, 3, 31)


@dataclass
class S:
    """Minimal canonical set for tests (fields read by the tool)."""

    set_id: str
    workout_ts: datetime
    weight_kg: float | None
    reps: int | None
    rpe: float | None = None
    set_type: str = "normal"
    failed: bool = False


def at(days_before: int) -> datetime:
    return datetime.combine(AS_OF - timedelta(days=days_before), datetime.min.time()).replace(hour=18)


def fixture_sets() -> list[S]:
    return [
        S("a0", at(0), 100, 5, rpe=8),  # acute: 100*5 = 500     | rpe-weighted 500*0.8 = 400
        S("a6", at(6), 80, 10, rpe=7),  # acute: 80*10 = 800     | 800*0.7 = 560
        S("c7", at(7), 100, 3, rpe=9),  # chronic (day 7 boundary): 300 | 300*0.9 = 270
        S("c8", at(8), 50, 10),  # chronic: 500            | no RPE -> excluded from rpe_weighted
        S("c34", at(34), 60, 5, rpe=6),  # chronic (last day): 300 | 300*0.6 = 180
        S("x35", at(35), 200, 5, rpe=9),  # day 35: outside both windows
        S("w0", at(0), 40, 10, set_type="warmup"),  # warm-up: excluded
        S("f1", at(1), 120, 0, failed=True),  # failed (reps 0): excluded
        S("bw2", at(2), 0, 12),  # bodyweight (weight 0): excluded
    ]


def vals(res: LoadResult) -> dict[str, float]:
    return {v.name: v.value for v in res.values}


def test_tonnage_hand_computed() -> None:
    res = compute_uncoupled_load(fixture_sets(), "tonnage", as_of=AS_OF)
    assert isinstance(res, LoadResult)
    v = vals(res)
    # acute = 500 + 800 = 1300
    assert v["acute_load"] == 1300
    # chronic total = 300 + 500 + 300 = 1100 over 4 weeks -> 275 per week
    assert v["chronic_load_weekly"] == 275
    # ratio = 1300 / 275 = 4.72727...
    assert v["acute_chronic_ratio"] == pytest.approx(4.727272, abs=1e-6)
    assert res.summary["ratio"] == {"value_id": "v_acute_chronic_ratio_0003", "value": 4.73, "label": "heuristic"}
    assert res.summary["excluded"] == {"failed": 1, "no_weight": 1, "warmup": 1}
    assert res.summary["n_sets"] == {"acute": 2, "chronic": 3}


def test_window_boundaries_day_7_8_35() -> None:
    res = compute_uncoupled_load(fixture_sets(), "tonnage", as_of=AS_OF)
    by_name = {v.name: v for v in res.values}
    acute_ids = by_name["acute_load"].provenance.input_row_ids
    chronic_ids = by_name["chronic_load_weekly"].provenance.input_row_ids
    assert acute_ids == ["a6", "a0"]  # days 6 and 0, in time order; day 7 is not acute
    assert "c7" in chronic_ids and "c8" in chronic_ids and "c34" in chronic_ids  # day 7 and 8: chronic, 34: chronic
    assert "x35" not in acute_ids + chronic_ids  # day 35: ignored


def test_rpe_weighted_hand_computed() -> None:
    res = compute_uncoupled_load(fixture_sets(), "rpe_weighted", as_of=AS_OF)
    v = vals(res)
    # acute = 400 + 560 = 960
    assert v["acute_load"] == pytest.approx(960)
    # chronic = 270 + 180 = 450 (c8 has no RPE) -> 450 / 4 = 112.5 per week
    assert v["chronic_load_weekly"] == pytest.approx(112.5)
    # ratio = 960 / 112.5 = 8.5333...
    assert v["acute_chronic_ratio"] == pytest.approx(8.533333, abs=1e-6)
    assert res.summary["excluded"]["no_rpe"] == 1
    assert "rpe_missing_on_some_sets" in res.summary["flags"]


def test_each_number_is_a_value_with_provenance() -> None:
    res = compute_uncoupled_load(fixture_sets(), "tonnage", as_of=AS_OF, ids=ValueIdFactory())
    assert [v.value_id for v in res.values] == [
        "v_acute_load_0001",
        "v_chronic_load_weekly_0002",
        "v_acute_chronic_ratio_0003",
    ]
    for v in res.values:
        assert v.provenance.tool_version == res.tool_version
        assert len(v.provenance.config_hash) == 64 and v.provenance.formula


def test_as_of_defaults_to_last_valid_set() -> None:
    a = compute_uncoupled_load(fixture_sets(), "tonnage")
    b = compute_uncoupled_load(fixture_sets(), "tonnage", as_of=AS_OF)
    assert a.summary["as_of"] == "2026-03-31"
    assert vals(a) == vals(b)


def test_insufficient_history_is_a_tool_error() -> None:
    # first valid set at day 20 < 34: the chronic window is not covered
    res = compute_uncoupled_load([S("a", at(0), 100, 5), S("b", at(20), 100, 5)], "tonnage", as_of=AS_OF)
    assert isinstance(res, ToolError) and res.code == "insufficient_history"


def test_history_exactly_35_days_is_enough() -> None:
    # first set at day 34 -> span 34 days -> 35 calendar days covered (0..34): sufficient
    res = compute_uncoupled_load([S("a", at(0), 100, 5), S("b", at(34), 100, 5)], "tonnage", as_of=AS_OF)
    assert isinstance(res, LoadResult)
    # chronic = 500 / 4 = 125, acute = 500 -> ratio 4.0
    assert vals(res)["acute_chronic_ratio"] == 4.0


def test_zero_chronic_load_has_no_ratio() -> None:
    sets = [
        S("a", at(0), 100, 5),
        S("w", at(10), 40, 10, set_type="warmup"),  # only warm-ups in the chronic window
        S("old", at(40), 100, 5),  # covers history; outside both windows
    ]
    res = compute_uncoupled_load(sets, "tonnage", as_of=AS_OF)
    assert isinstance(res, LoadResult)
    assert vals(res)["chronic_load_weekly"] == 0
    assert "acute_chronic_ratio" not in vals(res)
    assert res.summary["ratio"] is None
    assert "chronic_zero_ratio_undefined" in res.summary["flags"]


def test_no_valid_sets_and_bad_metric() -> None:
    assert compute_uncoupled_load([S("w", at(0), 40, 10, set_type="warmup")]).code == "no_valid_sets"
    assert compute_uncoupled_load(fixture_sets(), "volume").code == "invalid_metric"  # type: ignore[arg-type]


def test_sets_after_as_of_are_ignored_and_counted() -> None:
    sets = [*fixture_sets(), S("future", at(-3), 500, 5)]
    res = compute_uncoupled_load(sets, "tonnage", as_of=AS_OF)
    assert vals(res)["acute_load"] == 1300
    assert res.summary["excluded"]["after_as_of"] == 1


def test_no_injury_wording_anywhere() -> None:
    res = compute_uncoupled_load(fixture_sets(), "tonnage", as_of=AS_OF)
    blob = res.model_dump_json().lower()
    for word in ("injur", "risk", "danger", "safe zone", "sweet spot"):
        assert word not in blob


def test_deterministic_and_store_entry_point() -> None:
    class FakeStore:
        def get_sets(self, log_id: str) -> list[S]:
            assert log_id == "log-1"
            return fixture_sets()

    a = uncoupled_load_analyzer(FakeStore(), "log-1", as_of=AS_OF)
    b = uncoupled_load_analyzer(FakeStore(), "log-1", as_of=AS_OF)
    assert a.model_dump() == b.model_dump()
