"""compute_e1rm_and_drift against hand-computed fixtures (issue D8). Arithmetic is in the comments."""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.ingest import CanonicalSet, CanonicalSets, SetStore, SetType, ingest_workout_log, open_store
from src.tools.common import ToolError, Value, ValueIdFactory, load_indicator_config
from src.tools.e1rm import E1rmResult, brzycki, compute_e1rm_and_drift, epley, ols_slope_per_week, reps_to_failure

SQUAT = "Barbell_Squat"
DAY0 = datetime(2026, 11, 2, 18, 0)
Row = tuple[int, float | None, int | None]


def make_set(day: int, weight: float | None, reps: int | None, **kw: Any) -> CanonicalSet:
    fields: dict[str, Any] = {
        "workout_ts": DAY0 + timedelta(days=day), "exercise_name_raw": "Squat", "exercise_id": SQUAT, "set_index": 1,
        "weight_kg": weight, "source_unit": "kg", "reps": reps, "failed": reps == 0, "source_app": "test",
    }  # fmt: skip
    return CanonicalSet.build(**(fields | kw))


def stored(*sets: CanonicalSet) -> SetStore:
    db = open_store()
    unique = [s.model_copy(update={"set_id": f"s{i}", "set_index": i}) for i, s in enumerate(sets)]
    db.append_sets("u", CanonicalSets(sets=tuple(unique)))
    return db


def run(*sets: CanonicalSet, **kw: Any) -> E1rmResult:
    result = compute_e1rm_and_drift(stored(*sets), "u", SQUAT, **kw)
    assert isinstance(result, E1rmResult), result
    return result


def error(*sets: CanonicalSet, exercise: str = SQUAT, **kw: Any) -> ToolError:
    result = compute_e1rm_and_drift(stored(*sets), "u", exercise, **kw)
    assert isinstance(result, ToolError)
    return result


def series(result: E1rmResult, name: str) -> list[float]:
    return [v.value for v in result.values if v.name == name]  # type: ignore[misc]


def one(result: E1rmResult, name: str) -> Value:
    (value,) = [v for v in result.values if v.name == name]
    return value


WEEKLY = [make_set(d, 100, 5) for d in (0, 7, 14, 21)]

# The worked example of spec section 2
SPEC = [
    make_set(0, 60, 10, set_type="warmup"), make_set(0, 100, 5), make_set(0, 100, 4),
    make_set(7, 100, 6), make_set(7, 110, 0),
    make_set(14, 105, 5), make_set(14, 60, 12),
    make_set(21, 105, 6),
]  # fmt: skip


def test_formulas() -> None:
    assert epley(100, 5) == pytest.approx(116.6667, abs=1e-4)  # 100 * (1 + 5/30) = 100 * 1.166667
    assert brzycki(100, 5) == 112.5  # 100 * 36 / (37 - 5) = 3600 / 32
    assert reps_to_failure(5, 8) == 7  # 5 + (10 - 8)
    assert epley(100, 7) == pytest.approx(123.3333, abs=1e-4)


def test_spec_worked_example() -> None:
    r = run(*SPEC)
    # day 0: 100*(1+5/30); day 7: 100*(1+6/30); day 14: 105*(1+5/30); day 21: 105*(1+6/30)
    assert series(r, "e1rm_epley") == pytest.approx([116.6667, 120, 122.5, 126], abs=1e-4)
    # 100*36/32, 100*36/31, 105*36/32, 105*36/31
    assert series(r, "e1rm_brzycki") == pytest.approx([112.5, 116.1290, 118.125, 121.9355], abs=1e-4)
    # x = 0..3, mean 1.5; numerator 15.25, denominator 5
    assert one(r, "e1rm_slope").value == pytest.approx(3.05)
    assert r.trend == "up"  # 100 * 3.05 / 121.2917 = 2.51 % per week
    assert r.excluded == {"warmup": 1, "failed": 1, "missing_reps": 0, "no_load": 0, "reps_gt_max": 1}
    assert r.sessions_used == one(r, "e1rm_sessions").value == 4
    assert r.summary["excluded_sets"] == {"warmup": 1, "failed": 1, "reps_gt_max": 1}


def test_failed_set_never_sets_the_session_maximum() -> None:
    r = run(*WEEKLY, make_set(21, 300, 0), make_set(21, 300, 3, failed=True))
    assert series(r, "e1rm_epley")[-1] == pytest.approx(116.6667, abs=1e-4)
    assert r.excluded["failed"] == 2


def test_set_taken_to_failure_counts() -> None:
    r = run(*WEEKLY, make_set(21, 120, 5, set_type="failure"))
    assert series(r, "e1rm_epley")[-1] == pytest.approx(140)  # 120 * (1 + 5/30)


def test_reps_boundary_is_ten() -> None:
    r = run(*WEEKLY, make_set(21, 120, 10), make_set(21, 200, 11))
    assert series(r, "e1rm_epley")[-1] == pytest.approx(160)  # 120 * (1 + 10/30)
    assert r.excluded["reps_gt_max"] == 1


def test_bodyweight_and_missing_fields_are_excluded_and_counted() -> None:
    r = run(*WEEKLY, make_set(21, 0, 8), make_set(21, None, 8), make_set(21, 100, None))
    assert (r.excluded["no_load"], r.excluded["missing_reps"]) == (2, 1)
    assert series(r, "e1rm_epley")[-1] == pytest.approx(116.6667, abs=1e-4)


def test_rpe_adjusted_series_has_its_own_points() -> None:
    sets = [make_set(0, 100, 5, rpe=8), *WEEKLY[1:3], make_set(21, 100, 8, rpe=7), make_set(21, 90, 8, rpe=8)]
    r = run(*sets)
    # day 0: rtf 7 -> 123.3333; days 7, 14: no RPE; day 21: 8@7 has rtf 11 > 10, so 90 * (1 + 10/30) = 120
    assert series(r, "e1rm_rpe_adjusted") == pytest.approx([123.3333, 120], abs=1e-4)
    assert [s.rpe_adjusted is not None for s in r.sessions] == [True, False, False, True]


def test_three_sessions_are_not_enough() -> None:
    e = error(*WEEKLY[:3])
    assert e.code == "insufficient_sessions" and e.message.startswith("3 sessions")


def test_two_workouts_on_one_day_are_one_session() -> None:
    late = make_set(14, 100, 5).model_copy(update={"workout_ts": DAY0 + timedelta(days=14, hours=3)})
    assert error(*WEEKLY[:3], late).code == "insufficient_sessions"


def test_window_keeps_day_41_and_drops_day_42() -> None:
    later = [make_set(d, 100, 5) for d in (21, 28, 35, 42)]
    assert run(make_set(1, 100, 5), *later).sessions_used == 5  # 42 - 1 = 41 days before
    assert run(make_set(0, 100, 5), *later).sessions_used == 4  # 42 days before


def test_as_of_is_the_last_working_set_of_the_whole_log() -> None:
    other = make_set(60, 50, 5, exercise_id="Other", exercise_name_raw="Other")
    warmup = other.model_copy(update={"set_type": SetType.WARMUP})
    assert error(*WEEKLY, other).code == "insufficient_sessions"  # 60 - 21 = 39, only day 21 is in the window
    assert run(*WEEKLY, warmup).sessions_used == 4  # a warm-up does not move as_of
    assert run(*WEEKLY, other, as_of=date(2026, 11, 23)).sessions_used == 4


def test_unknown_exercise() -> None:
    for name in ("unknown", "", "Bench"):
        assert error(*WEEKLY, exercise=name).code == "unknown_exercise"


def test_exercise_with_only_warmups() -> None:
    assert error(make_set(0, 60, 5, set_type="warmup")).code == "insufficient_sessions"


def test_relative_strength() -> None:
    r = run(*SPEC, bodyweight_kg=84)
    assert one(r, "relative_strength").value == pytest.approx(1.5)  # 126 / 84
    assert not [v for v in run(*SPEC).values if v.name == "relative_strength"]
    for bad in (0, -80, float("nan")):
        assert error(*SPEC, bodyweight_kg=bad).code == "invalid_bodyweight"


def test_trend_bands() -> None:
    assert run(*WEEKLY).trend == "flat"
    down = [make_set(7 * i, 100 - 2 * i, 5) for i in range(4)]
    r = run(*down)
    # slope = -2 * 7/6 = -2.3333 kg per week, about -2.06 % of the mean
    assert one(r, "e1rm_slope").value == pytest.approx(-2.3333, abs=1e-4) and r.trend == "down"


DRIFT = [
    make_set(0, 100, 5, rpe=7), make_set(0, 100, 5, rpe=7), make_set(7, 100, 5, rpe=7.5),
    make_set(14, 100, 5, rpe=8), make_set(14, 100, 5, rpe=8), make_set(14, 90, 5, rpe=6),
    make_set(21, 100, 5, rpe=8), make_set(21, 100, 5, rpe=9),
]  # fmt: skip


def test_drift_worked_example() -> None:
    r = run(*DRIFT)
    # means 7, 7.5, 8, 8.5; numerator 2.5, denominator 5
    assert one(r, "rpe_drift_slope").value == pytest.approx(0.5)
    assert r.drift_trend == "up" and r.drift_error is None
    assert one(r, "drift_reference_load").value == 100 and one(r, "drift_sessions").value == 4
    # the 90 kg set is outside 95-105 kg
    assert len(one(r, "rpe_drift_slope").provenance.input_row_ids) == 7


def test_drift_with_exactly_three_sessions_is_an_error_but_e1rm_stays() -> None:
    r = run(*[make_set(d, 100, 5, rpe=8) for d in (0, 7, 14)], make_set(21, 100, 5))
    assert r.drift_error is not None and r.drift_error.code == "insufficient_comparable_sessions"
    assert r.drift_error.message.startswith("3 sessions")
    assert r.drift_trend is None and not series(r, "rpe_drift_slope")
    assert r.summary["rpe_drift"] == {"not_assessed": "insufficient_comparable_sessions"}
    assert r.sessions_used == 4


def test_no_rpe_at_all() -> None:
    r = run(*WEEKLY)
    assert r.drift_error is not None and r.drift_error.code == "rpe_missing"
    assert series(r, "e1rm_rpe_adjusted") == []


def test_drift_load_tolerance_is_inclusive() -> None:
    at = [make_set(7 * i, w, 5, rpe=8) for i, w in enumerate((100, 100, 95, 105))]
    assert one(run(*at), "drift_sessions").value == 4
    outside = [make_set(7 * i, w, 5, rpe=8) for i, w in enumerate((100, 100, 94.9, 105))]
    assert run(*outside).drift_error is not None


def test_drift_reference_tie_takes_the_heavier_load() -> None:
    sets = [make_set(7 * i, w, 5, rpe=8) for i, w in enumerate((80, 80, 100, 100))]
    r = run(*sets)
    assert r.drift_error is not None and "100 kg" in r.drift_error.message


def test_drift_has_no_reps_limit() -> None:
    sets = [make_set(7 * i, 100, 12, rpe=7 + i) for i in range(4)]
    r = run(*sets, *[make_set(7 * i, 60, 5) for i in range(4)])
    assert one(r, "rpe_drift_slope").value == pytest.approx(1)


def test_every_value_has_unique_id_and_provenance() -> None:
    r = run(*DRIFT, bodyweight_kg=80)
    ids = [v.value_id for v in r.values]
    assert len(set(ids)) == len(ids)
    for v in r.values:
        assert v.provenance.input_row_ids and v.provenance.formula and len(v.provenance.config_hash) == 64
        assert set(v.provenance.input_row_ids) <= {f"s{i}" for i in range(len(DRIFT))}
    assert {x for s in r.sessions for x in (s.epley, s.brzycki, s.rpe_adjusted) if x} <= set(ids)


def test_ids_continue_across_tools_of_a_run() -> None:
    ids = ValueIdFactory()
    db = stored(*WEEKLY)
    first = compute_e1rm_and_drift(db, "u", SQUAT, ids=ids)
    second = compute_e1rm_and_drift(db, "u", SQUAT, ids=ids)
    assert isinstance(first, E1rmResult) and isinstance(second, E1rmResult)
    assert not {v.value_id for v in first.values} & {v.value_id for v in second.values}


def test_result_is_deterministic_and_independent_of_row_order() -> None:
    assert run(*DRIFT) == run(*DRIFT)
    a, b = run(*SPEC), run(*reversed(SPEC))
    assert [(v.name, v.value) for v in a.values] == [(v.name, pytest.approx(v.value)) for v in b.values]


def test_config_changes_the_result_and_the_hash() -> None:
    cfg = copy.deepcopy(load_indicator_config())
    cfg["e1rm"]["max_reps"] = 5
    sets = [*WEEKLY, make_set(21, 120, 6)]
    strict, default = run(*sets, config=cfg), run(*sets)
    assert (strict.excluded["reps_gt_max"], default.excluded["reps_gt_max"]) == (1, 0)
    assert series(default, "e1rm_epley")[-1] == pytest.approx(144)  # 120 * (1 + 6/30)
    assert strict.values[0].provenance.config_hash != default.values[0].provenance.config_hash


def test_summary_is_compact_and_rounded() -> None:
    r = run(*[make_set(4 * i, 100 + i, 5) for i in range(9)])
    assert len(r.summary["recent_sessions"]) == 6
    shown = r.summary["recent_sessions"][-1]["epley"]
    assert shown["value"] == 126 and shown["unit"] == "kg"  # 108 * 35/30
    assert r.summary["e1rm_slope"]["value"] == round(one(r, "e1rm_slope").value, 2)


def test_real_export_has_e1rm_but_no_drift() -> None:
    path = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "opengym" / "fineas_anonymized.csv"
    with open_store() as db:
        ingest_workout_log(path, log_id="f", store=db, matcher={"Barbell Bench Press": "Bench"}.get)
        r = compute_e1rm_and_drift(db, "f", "Bench")
    assert isinstance(r, E1rmResult)
    # 2026-10-26: 100 kg x 9 is the best set of the session, 100 * (1 + 9/30) = 130
    assert series(r, "e1rm_epley")[0] == pytest.approx(130)
    assert r.drift_error is not None and r.drift_error.code == "rpe_missing"
    assert r.excluded["warmup"] == 10


def test_ols_slope_on_uneven_spacing() -> None:
    # x = 0, 1, 3 weeks, y = 1, 3, 4: means 4/3 and 8/3; numerator 26/6 = 4.3333, denominator 14/3
    pts = [(date(2026, 1, 1), 1.0), (date(2026, 1, 8), 3.0), (date(2026, 1, 22), 4.0)]
    assert ols_slope_per_week(pts) == pytest.approx(13 / 14)
