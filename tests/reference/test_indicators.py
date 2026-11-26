"""Tests of the reference indicators. Expected values are computed by hand from docs/indicator-spec.md.

Tests named `test_pending_5_item_N_*` pin a proposal from the P3 comment on issue #5 (marker `PENDING #5 item N`).
"""

import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.reference import indicators as ref

ROOT = Path(__file__).resolve().parents[2]
START = date(2026, 1, 5)  # a Monday; row(day) is START + day
LB = 0.45359237
SQUAT = "Barbell_Squat"
BENCH = "Barbell_Bench_Press_-_Medium_Grip"  # primary chest; secondary shoulders, triceps
EXERCISES = {e["id"]: e for e in json.loads(
    (ROOT / "data/exercises/free-exercise-db.json").read_text(encoding="utf-8"))}


def row(day, weight=100, reps=5, rpe=None, kind="normal", failed=False, ex=SQUAT, name=None):
    return {"workout_ts": (START + timedelta(days=day)).isoformat() + "T10:00", "exercise_id": ex, "set_type": kind,
            "weight_kg": weight, "reps": reps, "rpe": rpe, "failed": failed, "exercise_name": name}


def day(n):
    return START + timedelta(days=n)


def code(function, *args, **kwargs):
    with pytest.raises(ref.IndicatorError) as caught:
        function(*args, **kwargs)
    return caught.value.code


def close(value):
    return pytest.approx(value, abs=1e-9)


def values(series):
    return [v for _, v in series]


EXAMPLE_2 = [
    row(0, 60, 10, kind="warmup"), row(0, 100, 5), row(0, 100, 4),
    row(7, 100, 6), row(7, 110, 0),
    row(14, 105, 5), row(14, 60, 12),
    row(21, 105, 6),
]
EXAMPLE_3 = [
    row(0, rpe=7), row(0, rpe=7), row(7, rpe=7.5), row(14, rpe=8), row(14, rpe=8), row(14, 90, rpe=6),
    row(21, rpe=8), row(21, rpe=9),
]
# Section 5 counts days before as_of, so spec day d is row(35 - d).
EXAMPLE_5 = [row(35, reps=5), row(29, reps=8), row(28, reps=3), row(27, reps=5), row(1, reps=3), row(0, reps=10)]


# --- section 2 ------------------------------------------------------------------------------------------------------


def test_e1rm_example():
    got = ref.e1rm_trend(EXAMPLE_2, SQUAT)
    # 100*35/30 = 350/3; 100*36/30 = 120; 105*35/30 = 122.5; 105*36/30 = 126
    assert values(got["series"]["epley"]) == close([350 / 3, 120, 122.5, 126])
    assert got["e1rm_slope"] == close(3.05)  # 15.25 / 5
    # p = 100 * 3.05 / (1455.5 / 12) = 3660 / 1455.5 = 2.5146 %
    assert got["percent_per_week"] == close(3660 / 1455.5)
    assert got["label"] == "up" and got["e1rm_latest"] == close(126) and got["sessions"] == 4
    assert got["excluded"] == Counter(warmup=1, failed=1, reps_gt_max=1)
    assert got["series"]["brzycki"][0][1] == close(112.5)  # 100*36/32
    assert got["series"]["rpe_adjusted"] == []


def test_e1rm_rpe_adjusted_example_and_limit():
    # 5 + (10 - 8) = 7: 100 * 37/30 = 370/3. 8 + 2 = 10 is included: 60 * 40/30 = 80. 9 + 2 = 11 is not.
    got = ref.e1rm_series([row(0, 100, 5, 8), row(7, 60, 8, 8), row(14, 60, 9, 8)], SQUAT)
    assert values(got["rpe_adjusted"]) == close([370 / 3, 80])


def test_e1rm_single_rep_has_no_special_case():
    # Epley 100 * 31/30 = 310/3; Brzycki 100 * 36/36 = 100
    got = ref.e1rm_series([row(0, 100, 1)], SQUAT)
    assert got["epley"][0][1] == close(310 / 3) and got["brzycki"][0][1] == close(100)


def test_e1rm_reasons_in_order():
    # 60 x 10 to failure is valid: 60 * 40/30 = 80. Missing reps with no weight is missing_reps (listed first).
    sets = [row(0, 60, 10, kind="failure"), row(0, None, None), row(0, 0, 5), row(0, None, 5), row(0, 90, 11),
            row(0, 90, 0, kind="warmup"), row(0, 90, 5, failed=True)]
    got = ref.e1rm_series(sets, SQUAT)
    assert got["epley"] == [(START, close(80))]
    assert got["excluded"] == Counter(missing_reps=1, no_load=2, reps_gt_max=1, warmup=1, failed=1)


def test_e1rm_each_series_takes_its_own_maximum():
    # Epley: 100 x 5 = 116.67 beats 110 x 1 = 113.67. RPE-adjusted exists only for 110 x 1 @ 10: 110 * 31/30 = 341/3.
    got = ref.e1rm_series([row(0, 100, 5), row(0, 110, 1, 10)], SQUAT)
    assert got["epley"][0][1] == close(350 / 3) and got["rpe_adjusted"][0][1] == close(341 / 3)


def test_e1rm_window_days_41_and_42():
    # as_of is day 42: day 1 is 41 days before (inside), day 0 is 42 days before (outside)
    got = ref.e1rm_series([row(0), row(1), row(42)], SQUAT)["epley"]
    assert [d for d, _ in got] == [day(1), day(42)]


def test_e1rm_as_of_is_last_working_set_of_any_exercise():
    # Another exercise on day 42 moves as_of; a warm-up on day 60 does not.
    sets = [row(0), row(1), row(42, ex="Other"), row(60, ex="Other", kind="warmup")]
    assert [d for d, _ in ref.e1rm_series(sets, SQUAT)["epley"]] == [day(1)]


def test_e1rm_passed_as_of_ignores_later_sets():
    # as_of day 14: sessions 0, 7, 14 only
    assert len(ref.e1rm_series(EXAMPLE_2, SQUAT, as_of=day(14))["epley"]) == 3


def test_e1rm_errors():
    assert code(ref.e1rm_trend, EXAMPLE_2[:7], SQUAT) == "insufficient_sessions"  # 3 sessions
    for name in ("", None, "unknown", "Missing"):
        assert code(ref.e1rm_trend, EXAMPLE_2, name) == "unknown_exercise"
    assert code(ref.relative_strength, 126, 0) == "invalid_bodyweight"
    assert code(ref.relative_strength, 126, -1) == "invalid_bodyweight"
    assert ref.relative_strength(126, 84) == close(1.5)


def test_e1rm_labels():
    # With r = 1 every value is w * 31/30, so p depends on w only. Slope 1, mean 200: exactly 0.5 %, flat.
    sets = [row(7 * i, w, 1) for i, w in enumerate([198.5, 199.5, 200.5, 201.5])]
    assert ref.e1rm_trend(sets, SQUAT)["label"] == "flat"
    # Slope -1, mean 200: exactly -0.5 %, flat. Slope -2: -1 %, down.
    sets = [row(7 * i, w, 1) for i, w in enumerate([201.5, 200.5, 199.5, 198.5])]
    assert ref.e1rm_trend(sets, SQUAT)["label"] == "flat"
    sets = [row(7 * i, w, 1) for i, w in enumerate([203, 201, 199, 197])]
    assert ref.e1rm_trend(sets, SQUAT)["label"] == "down"


def test_combined_example_with_bodyweight():
    got = ref.compute_e1rm_and_drift(EXAMPLE_2, SQUAT, bodyweight=84)
    assert got["e1rm"]["relative_strength"] == close(1.5)  # 126 / 84
    assert got["drift"] == {"error": "rpe_missing"}  # a drift error does not discard e1RM


# --- section 3 ------------------------------------------------------------------------------------------------------


def test_drift_example():
    got = ref.rpe_drift(EXAMPLE_3, SQUAT)
    assert values(got["series"]) == close([7, 7.5, 8, 8.5])
    assert got["rpe_drift_slope"] == close(0.5) and got["label"] == "up"  # 2.5 / 5
    assert got["reference_load"] == 100 and got["excluded"] == Counter()  # 90 kg is valid, only not comparable


def test_drift_tolerance_is_inclusive_and_has_no_reps_limit():
    # Two sets at 100 make it the reference. 95 and 105 are exactly 5 % away; 94.9 is outside. 20 reps count.
    sets = [row(0, rpe=7), row(0, 94.9, rpe=1), row(7, 95, 20, 7), row(14, 105, 20, 7), row(21, rpe=7)]
    got = ref.rpe_drift(sets, SQUAT)
    assert values(got["series"]) == close([7, 7, 7, 7]) and got["label"] == "flat"


def test_drift_tie_takes_the_heavier_weight():
    # 80 and 100 occur four times each; only 100 gives 8, 8, 8, 8
    sets = [row(7 * i, w, rpe=r) for i in range(4) for w, r in ((80, 6), (100, 8))]
    got = ref.rpe_drift(sets, SQUAT)
    assert got["reference_load"] == 100 and values(got["series"]) == close([8, 8, 8, 8])


def test_drift_label_band():
    # Means 7, 7.1, 7.2, 7.3: slope 0.1 exactly, flat. 7, 7.2, 7.4, 7.6: slope 0.2, up.
    flat = [row(7 * i, rpe=7 + 0.1 * i) for i in range(4)]
    up = [row(7 * i, rpe=7 + 0.2 * i) for i in range(4)]
    assert ref.rpe_drift(flat, SQUAT)["label"] == "flat" and ref.rpe_drift(up, SQUAT)["label"] == "up"


def test_drift_errors_and_reasons():
    assert code(ref.rpe_drift, EXAMPLE_2, SQUAT) == "rpe_missing"
    assert code(ref.rpe_drift, [row(0, 0, rpe=8)], SQUAT) == "rpe_missing"  # bodyweight is no_load
    assert code(ref.rpe_drift, EXAMPLE_3[:6], SQUAT) == "insufficient_comparable_sessions"  # 3 sessions
    sets = EXAMPLE_3 + [row(21, 0, rpe=8), row(21), row(21, kind="warmup", rpe=5)]
    assert ref.rpe_drift(sets, SQUAT)["excluded"] == Counter(no_load=1, no_rpe=1, warmup=1)


# --- section 4 ------------------------------------------------------------------------------------------------------


def test_weekly_example():
    sets = [row(0, rpe=8, ex=BENCH) for _ in range(3)]
    sets += [row(0, kind="warmup", ex=BENCH), row(0, reps=0, ex=BENCH), row(0, rpe=6, ex=BENCH)]
    got = ref.weekly_sets(sets, EXERCISES)
    assert got["totals"] == {"chest": 3.0, "shoulders": 1.5, "triceps": 1.5}  # 3 * 1, 3 * 0.5
    assert got["excluded"] == Counter(warmup=1, failed=1, low_rpe=1)
    assert got["cells"]["chest"] == {START: 3.0} and not got["no_rpe"]
    # Means over 6 weeks: 3 / 6 = 0.5, 1.5 / 6 = 0.25. A single week: last minus first is 0, flat.
    assert got["means"] == {"chest": 0.5, "shoulders": 0.25, "triceps": 0.25}
    assert set(got["trends"].values()) == {"flat"}


def test_weekly_reasons_and_bounds():
    # RPE 7, bodyweight without RPE, and missing weight and reps count: 1 + 1 + 1 = 3. RPE 6.99 is low_rpe.
    sets = [row(0, rpe=7, ex=BENCH), row(0, rpe=6.99, ex=BENCH), row(0, 0, 5, ex=BENCH),
            row(0, None, None, ex=BENCH), row(0, ex="0198", name="Cable Pulldown"), row(0, ex=None)]
    got = ref.weekly_sets(sets, EXERCISES)
    assert got["totals"]["chest"] == 3.0 and got["no_rpe"]
    assert got["excluded"] == Counter(low_rpe=1, unknown=2)
    assert got["unknown_exercises"] == ["", "Cable Pulldown"]
    got = ref.weekly_sets(sets, EXERCISES, allowed={SQUAT})
    assert got["totals"] == {} and got["excluded"] == Counter(unknown=2, not_allowed=4)


def test_weekly_empty_log():
    got = ref.weekly_sets([], EXERCISES)
    assert got["cells"] == {} and got["weeks"] == []


def test_weekly_weeks_shown_and_warmup_as_last_set():
    # The warm-up on day 35 (a Monday) is the last set, so the weeks start on days 0 to 35: day -1 is out, day 0 is in.
    sets = [row(-1, ex=BENCH), row(0, ex=BENCH), row(6, ex=BENCH), row(35, kind="warmup", ex=BENCH)]
    got = ref.weekly_sets(sets, EXERCISES)
    assert got["weeks"] == [day(7 * i) for i in range(6)]
    assert got["cells"]["chest"] == {START: 2.0}


def test_weekly_muscle_listed_twice_is_primary_only():
    record = {"primaryMuscles": ["quads"], "secondaryMuscles": ["quads", "calves"]}
    assert ref.weekly_sets([row(0, ex="X")], {"X": record})["totals"] == {"quads": 1.0, "calves": 0.5}


def test_weekly_mean_is_rounded():
    # 1 set / 6 = 0.1667 -> 0.17; shoulders 0.5 / 6 = 0.0833 -> 0.08
    got = ref.weekly_sets([row(0, ex=BENCH)], EXERCISES)
    assert got["means"]["chest"] == 0.17 and got["means"]["shoulders"] == 0.08


def test_weekly_trend_band_with_complete_last_week():
    # Last date day 20 is a Sunday. P adds 1 to chest, S adds 0.5. W1 1, W3 1.5: change 0.5, flat. W1 1, W3 2: up.
    records = {"P": {"primaryMuscles": ["chest"], "secondaryMuscles": []},
               "S": {"primaryMuscles": ["back"], "secondaryMuscles": ["chest"]}}
    flat = [row(0, ex="P"), row(20, ex="P"), row(20, ex="S")]
    assert ref.weekly_sets(flat, records)["trends"]["chest"] == "flat"
    up = [row(0, ex="P"), row(20, ex="P"), row(20, ex="P")]
    assert ref.weekly_sets(up, records)["trends"]["chest"] == "up"
    down = [row(0, ex="P"), row(0, ex="P"), row(20, ex="S")]  # 0.5 - 2 = -1.5
    assert ref.weekly_sets(down, records)["trends"]["chest"] == "down"


# --- section 5 ------------------------------------------------------------------------------------------------------


def test_load_example():
    got = ref.uncoupled_load(EXAMPLE_5)
    # 500 + 800; (300 + 500 + 300) / 4; 1300 / 275 = 52/11 = 4.7273
    assert (got["acute_load"], got["chronic_load_weekly"]) == (close(1300), close(275))
    assert got["acute_chronic_ratio"] == close(52 / 11) and got["ratio_label"] == "heuristic"
    assert got["as_of"] == day(35) and got["excluded"] == Counter()


def test_load_rpe_weighted():
    # 100*5*8/10 = 400; 100*4*9/10 = 360, weekly 90; ratio 40/9. The set without RPE is not valid.
    got = ref.uncoupled_load([row(34, rpe=8), row(0, reps=4, rpe=9), row(50)], "rpe_weighted")
    assert got["as_of"] == day(34)
    assert (got["acute_load"], got["chronic_load_weekly"]) == (close(400), close(90))
    assert got["acute_chronic_ratio"] == close(40 / 9)


def test_load_history_bound():
    assert ref.uncoupled_load([row(0), row(34)])["acute_load"] == close(500)  # day 34 is enough
    assert code(ref.uncoupled_load, [row(0), row(33)]) == "insufficient_history"


def test_load_chronic_zero():
    got = ref.uncoupled_load([row(0), row(35)])
    assert got["acute_chronic_ratio"] is None and got["flags"] == ["chronic_zero_ratio_undefined"]
    assert (got["acute_load"], got["chronic_load_weekly"]) == (500, 0)


def test_load_passed_as_of():
    # as_of day 34: the set on day 35 is ignored, day 0 is 34 days before
    got = ref.uncoupled_load([row(0), row(34, reps=2), row(35)], as_of=day(34))
    assert (got["acute_load"], got["chronic_load_weekly"]) == (close(200), close(125))  # 500 / 4


def test_load_errors_reasons_and_allowed():
    assert code(ref.uncoupled_load, []) == "no_valid_sets"
    assert code(ref.uncoupled_load, EXAMPLE_5, "volume") == "invalid_metric"
    assert code(ref.uncoupled_load, EXAMPLE_5, allowed={"Other"}) == "no_valid_sets"
    assert code(ref.uncoupled_load, [row(0, 0), row(0, reps=None)]) == "no_valid_sets"
    # Unknown exercises count without an allowed set.
    assert ref.uncoupled_load([row(0, ex="unknown"), row(34, ex=None)])["acute_load"] == close(500)
    sets = EXAMPLE_5 + [row(35, reps=None), row(35, 0), row(35, ex="Other")]
    got = ref.uncoupled_load(sets, allowed={SQUAT})
    assert got["excluded"] == Counter(missing_reps=1, no_weight=1, not_allowed=1)


# --- section 6 ------------------------------------------------------------------------------------------------------


def before(*days, **kwargs):
    """One set per session, `days` before the last one (day 50)."""
    return [row(50 - d, **kwargs) for d in days]


def test_sufficiency_example():
    """Also relies on PENDING #5 item 2 (one reason)."""
    got = ref.check_data_sufficiency(before(0, 10, 20, 34))
    # gaps 10, 10, 14 pass; covered 35 passes; 4 sessions pass; RPE on 0 of 4 fails
    assert got["allowed_analyses"] == ["e1rm_trend", "weekly_volume", "load_ratio"] and got["sufficient"]
    assert got["failed_checks"] == ["5a"]
    assert got["reasons"] == ["RPE logged on 0 of 4 working sets; RPE drift not assessed"]
    got = ref.check_data_sufficiency(before(0, 10, 20, 33))  # covered 34
    assert got["allowed_analyses"] == ["e1rm_trend", "weekly_volume"] and got["failed_checks"] == ["3", "5a"]


def test_sufficiency_all_checks_pass():
    got = ref.check_data_sufficiency(before(0, 10, 20, 34, rpe=8))
    assert got["allowed_analyses"] == list(ref.ANALYSES) and got["reasons"] == []


def test_sufficiency_gap_blocks_everything():
    got = ref.check_data_sufficiency(before(0, 15, 30, 40))  # gaps 10, 15, 15
    assert not got["sufficient"] and got["allowed_analyses"] == [] and "2" in got["failed_checks"]


def test_sufficiency_sessions_and_matched_exercises():
    # Squat 3 sessions, bench 1: gaps 10, 10, 14 and 35 days covered pass, check 4 fails.
    got = ref.check_data_sufficiency(before(0, 10, 20) + before(34, ex=BENCH))
    assert got["allowed_analyses"] == ["weekly_volume", "load_ratio"] and got["failed_checks"] == ["4", "5a"]
    got = ref.check_data_sufficiency(before(0, 10, ex="unknown") + before(20, ex=None))
    assert got["failed_checks"] == ["1"] and not got["sufficient"]
    assert ref.check_data_sufficiency(before(0, 10, 20, 34), allowed={"Other"})["failed_checks"] == ["1"]


def test_sufficiency_comparable_load():
    # RPE on all sets, but loads 100, 80, 60, 40: the reference is 100 and only one session is comparable.
    sets = [row(50 - d, w, rpe=8) for d, w in ((0, 100), (10, 80), (20, 60), (34, 40))]
    got = ref.check_data_sufficiency(sets)
    assert got["failed_checks"] == ["5b"] and "rpe_drift" not in got["allowed_analyses"]
    # Coverage of exactly 0.5 passes 5a; with RPE on two sessions only, 5b fails.
    got = ref.check_data_sufficiency(before(0, 10, rpe=8) + before(20, 34))
    assert got["failed_checks"] == ["5b"]


# --- PENDING #5 -----------------------------------------------------------------------------------------------------


def test_pending_5_item_1_raw_reference_load():
    """PENDING #5 item 1: raw weights, reference is the heaviest raw weight of the most frequent rounded group."""
    # Reference 100 lb. 95 lb (5 % exactly) and 105 lb are comparable. Means 7, 8, 8, 9: slope 3 / 5 = 0.6.
    sets = [row(0, 100 * LB, rpe=7), row(0, 100 * LB, rpe=7), row(7, 95 * LB, rpe=8), row(14, 105 * LB, rpe=8),
            row(21, 100 * LB, rpe=9)]
    got = ref.rpe_drift(sets, SQUAT)
    assert values(got["series"]) == close([7, 8, 8, 9]) and got["rpe_drift_slope"] == close(0.6)
    # 100.004, 100.004 and 99.996 all round to 100.00; the reference is 100.004, so 95 is 5.004 > 5.0002 away.
    group = [row(0, 100.004, rpe=7), row(7, 100.004, rpe=7), row(14, 99.996, rpe=7), row(21, 95, rpe=9)]
    comparable, reference = ref.comparable_sets(group, 0.05)
    assert reference == 100.004 and len(comparable) == 3


def test_pending_5_item_2_check_5b_skipped_when_5a_fails():
    """PENDING #5 item 2: with RPE on 1 of 4 sets both 5a and 5b would fail; only 5a is reported."""
    got = ref.check_data_sufficiency(before(0, rpe=8) + before(10, 20, 34))
    assert got["failed_checks"] == ["5a"] and len(got["reasons"]) == 1


def test_pending_5_item_3_drift_reported_when_e1rm_stops():
    """PENDING #5 item 3: 60 x 12 is never a valid e1RM set, but drift is computed: means 7 to 8.5, slope 0.5."""
    sets = [row(7 * i, 60, 12, rpe) for i, rpe in enumerate([7, 7.5, 8, 8.5])]
    got = ref.compute_e1rm_and_drift(sets, SQUAT)
    assert got["e1rm"] == {"error": "insufficient_sessions"}
    assert got["drift"]["rpe_drift_slope"] == close(0.5)


def test_pending_5_item_4_weekly_trend_per_muscle():
    """PENDING #5 item 4: weeks with sets are per muscle, also for the incomplete-week rule."""
    # Chest 4, 4, then a legs-only week ending on Sunday day 20: per muscle 4 - 4 = 0, flat (per log it would be down).
    sets = [row(d, ex=BENCH) for d in (0, 0, 0, 0, 7, 7, 7, 7)] + [row(20, ex=SQUAT)]
    assert ref.weekly_sets(sets, EXERCISES)["trends"]["chest"] == "flat"
    # Last date day 16 (Wednesday). Chest 2, 4, 1: the incomplete week is left out, 4 - 2 = 2, up.
    sets = [row(d, ex=BENCH) for d in (0, 0, 7, 7, 7, 7, 16)]
    assert ref.weekly_sets(sets, EXERCISES)["trends"]["chest"] == "up"
    # Chest 4, 1 only: two other weeks do not remain, so the last week stays: 1 - 4 = -3, down.
    assert ref.weekly_sets(sets[2:], EXERCISES)["trends"]["chest"] == "down"


def test_pending_5_item_5_exclusions_counted_inside_window():
    """PENDING #5 item 5: a warm-up 10 days before as_of counts, one 50 days before does not."""
    sets = [row(0, kind="warmup"), row(40, kind="warmup"), row(50)]
    assert ref.e1rm_series(sets, SQUAT)["excluded"] == Counter(warmup=1)
    # Load: inside days 0-34 only; warm-ups 34 and 35 days before as_of day 35.
    sets = [row(1), row(35), row(1, kind="warmup"), row(0, kind="warmup")]
    assert ref.uncoupled_load(sets)["excluded"] == Counter(warmup=1)
    # Weekly: inside the weeks shown only; day -1 is in the week before.
    sets = [row(-1, kind="warmup", ex=BENCH), row(0, kind="warmup", ex=BENCH), row(35, ex=BENCH)]
    assert ref.weekly_sets(sets, EXERCISES)["excluded"] == Counter(warmup=1)


def test_pending_5_item_6_sets_after_passed_date_ignored():
    """PENDING #5 item 6: passed date Wednesday day 2, 3 chest sets on Friday day 4: 0, not 3.0."""
    got = ref.weekly_sets([row(4, ex=BENCH)] * 3, EXERCISES, as_of=day(2))
    assert got["totals"] == {} and got["weeks"][-1] == START


def test_pending_5_item_7_mean_over_all_weeks_shown():
    """PENDING #5 item 7: two weeks with 3 chest sets each: 6 / 6 = 1.0, not 6 / 2 = 3.0."""
    sets = [row(d, ex=BENCH) for d in (0, 0, 0, 13, 13, 13)]
    assert ref.weekly_sets(sets, EXERCISES)["means"]["chest"] == 1.0


def test_pending_5_item_8_rpe_outside_scale_is_missing():
    """PENDING #5 item 8: RPE outside [1, 10] is treated as missing in every indicator."""
    assert ref.e1rm_series([row(0, rpe=55)], SQUAT)["rpe_adjusted"] == []
    assert ref.e1rm_series([row(0, rpe=10)], SQUAT)["rpe_adjusted"][0][1] == close(350 / 3)  # 10 is on the scale
    assert code(ref.rpe_drift, [row(0, rpe=55), row(0, rpe=0.5)], SQUAT) == "rpe_missing"
    got = ref.weekly_sets([row(0, rpe=55, ex=BENCH)], EXERCISES)
    assert got["totals"]["chest"] == 1.0 and got["no_rpe"]
    assert code(ref.uncoupled_load, [row(0, rpe=55)], "rpe_weighted") == "no_valid_sets"


def test_pending_5_item_9_error_precedence():
    """PENDING #5 item 9: invalid arguments first, then unknown_exercise; sets only after as_of are not unknown."""
    assert code(ref.compute_e1rm_and_drift, EXAMPLE_2, "Missing", bodyweight=0) == "invalid_bodyweight"
    assert code(ref.compute_e1rm_and_drift, EXAMPLE_2, "Missing", bodyweight=80) == "unknown_exercise"
    assert code(ref.uncoupled_load, [], "volume") == "invalid_metric"
    assert code(ref.e1rm_trend, EXAMPLE_2, SQUAT, as_of=day(-1)) == "insufficient_sessions"
    assert code(ref.rpe_drift, EXAMPLE_3, SQUAT, as_of=day(-1)) == "rpe_missing"


def test_pending_5_item_11_no_considered_rows_only_check_1():
    """PENDING #5 item 11: an empty log, or one with unknown exercises only, gives the check 1 reason alone."""
    for sets in ([], before(0, 10, ex="unknown") + before(20, ex=None)):
        got = ref.check_data_sufficiency(sets)
        assert got["failed_checks"] == ["1"] and got["as_of"] is None and not got["sufficient"]
        assert got["reasons"] == ["0 matched exercises; at least 1 needed; no analysis"]


def test_pending_5_item_10_history_over_whole_log():
    """PENDING #5 item 10: sessions 0, 10, 20, 30, 50 days before: covered 51 passes (31 inside the window)."""
    got = ref.check_data_sufficiency(before(0, 10, 20, 30, 50))
    assert got["failed_checks"] == ["5a"] and "load_ratio" in got["allowed_analyses"]
