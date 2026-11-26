"""Reference indicators, written from docs/indicator-spec.md (version 1) only.

Where the text is open, the code follows the proposals in the P3 comment on issue #5. Each such place is marked
`# PENDING #5 item N` and has its own test with the same marker.

Input: canonical set dicts (`workout_ts`, `exercise_id`, `set_type`, `weight_kg`, `reps`, `rpe`, `failed`, and
optionally `exercise_name`). `workout_ts` may be a datetime, a date or an ISO string.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "indicators.yaml"
SLACK = 1e-9  # spec 1.6
ANALYSES = ("e1rm_trend", "rpe_drift", "weekly_volume", "load_ratio")


class IndicatorError(Exception):
    """An error named by the spec, e.g. `insufficient_sessions`."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# --- common definitions (section 1) ---------------------------------------------------------------------------------


def _at_most(value, bound):
    """Inclusive upper bound with the slack of 1.6."""
    return value <= bound + SLACK


def _label(value, band):
    """`up` / `down` outside the band, `flat` inside it; the band edge itself is flat."""
    if _at_most(abs(value), band):
        return "flat"
    return "up" if value > 0 else "down"


def set_date(row):
    ts = row["workout_ts"]
    if isinstance(ts, datetime):
        return ts.date()
    return ts if isinstance(ts, date) else datetime.fromisoformat(ts).date()


def is_failed(row):
    return bool(row.get("failed")) or row.get("reps") == 0


def is_working(row):
    return row.get("set_type") != "warmup" and not is_failed(row)


def rpe_of(row):
    """The set's RPE, or None when it is missing."""
    rpe = row.get("rpe")
    # PENDING #5 item 8: an RPE outside [1, 10] is treated as missing.
    if rpe is not None and not (1 - SLACK <= rpe <= 10 + SLACK):
        return None
    return rpe


def _has_weight(row):
    return row.get("weight_kg") is not None and row["weight_kg"] > 0


def _first_reason(row, checks):
    """The first exclusion reason (1.3): warmup, failed, then the indicator's own (name, passes) checks."""
    if row.get("set_type") == "warmup":
        return "warmup"
    if is_failed(row):
        return "failed"
    for name, passes in checks:
        if not passes(row):
            return name
    return None


def _split(rows, checks):
    """Valid rows and a Counter of exclusion reasons."""
    valid, excluded = [], Counter()
    for row in rows:
        reason = _first_reason(row, checks)
        if reason is None:
            valid.append(row)
        else:
            excluded[reason] += 1
    return valid, excluded


def default_as_of(sets):
    """Date of the last working set of the whole log (1.4), or None."""
    return max((set_date(row) for row in sets if is_working(row)), default=None)


def days_before(as_of, row):
    return (as_of - set_date(row)).days


def in_analysis_window(as_of, row, config):
    return 0 <= days_before(as_of, row) < 7 * config["window"]["analysis_weeks"]


def slope(series):
    """Least-squares slope per week of date-sorted (date, value) pairs (1.5)."""
    xs = [(day - series[0][0]).days / 7 for day, _ in series]
    ys = [value for _, value in series]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    top = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return top / sum((x - mean_x) ** 2 for x in xs)


def _exercise_rows(sets, exercise_id, as_of, config):
    """All sets of the exercise in the analysis window, warm-ups and failed sets included (for counting)."""
    if not exercise_id or exercise_id == "unknown" or not any(r.get("exercise_id") == exercise_id for r in sets):
        raise IndicatorError("unknown_exercise")
    as_of = as_of or default_as_of(sets)
    if as_of is None:
        return []
    # PENDING #5 item 9: an exercise whose only sets follow as_of is known; its empty window gives
    # insufficient_sessions (e1RM) and rpe_missing (drift), not unknown_exercise.
    # PENDING #5 item 5: exclusions are counted inside the analysis window only.
    return [r for r in sets if r.get("exercise_id") == exercise_id and in_analysis_window(as_of, r, config)]


# --- estimated 1RM (section 2) --------------------------------------------------------------------------------------


def epley(weight, reps):
    return weight * (1 + reps / 30)


def brzycki(weight, reps):
    return weight * 36 / (37 - reps)


def e1rm_series(sets, exercise_id, as_of=None, config=None):
    """Session maxima per series, as {"epley" | "brzycki" | "rpe_adjusted": [(date, kg), ...], "excluded": Counter}."""
    config = config or load_config()
    limit = config["e1rm"]["max_reps"]
    valid, excluded = _split(_exercise_rows(sets, exercise_id, as_of, config), [
        ("missing_reps", lambda r: r.get("reps") is not None),
        ("no_load", _has_weight),
        ("reps_gt_max", lambda r: _at_most(r["reps"], limit)),
    ])
    best = {"epley": {}, "brzycki": {}, "rpe_adjusted": {}}
    for row in valid:
        day, weight, reps, rpe = set_date(row), row["weight_kg"], row["reps"], rpe_of(row)
        values = {"epley": epley(weight, reps), "brzycki": brzycki(weight, reps)}
        if rpe is not None and _at_most(reps + (10 - rpe), limit):
            values["rpe_adjusted"] = epley(weight, reps + (10 - rpe))
        for name, value in values.items():
            best[name][day] = max(value, best[name].get(day, value))
    result = {name: sorted(points.items()) for name, points in best.items()}
    result["excluded"] = excluded
    return result


def e1rm_trend(sets, exercise_id, as_of=None, config=None):
    """Epley slope, latest value and trend label (section 2, steps 4-7)."""
    config = config or load_config()
    series = e1rm_series(sets, exercise_id, as_of, config)
    points = series["epley"]
    if len(points) < config["e1rm"]["min_sessions"]:
        raise IndicatorError("insufficient_sessions")
    value = slope(points)
    percent = 100 * value / (sum(y for _, y in points) / len(points))
    return {
        "series": series,
        "sessions": len(points),
        "e1rm_slope": value,
        "e1rm_latest": points[-1][1],
        "percent_per_week": percent,
        "label": _label(percent, config["e1rm"]["flat_pct_per_week"]),
        "excluded": series["excluded"],
    }


def relative_strength(e1rm_latest, bodyweight):
    if bodyweight <= 0:
        raise IndicatorError("invalid_bodyweight")
    return e1rm_latest / bodyweight


# --- RPE drift (section 3) ------------------------------------------------------------------------------------------


def _drift_checks():
    return [("no_load", _has_weight), ("no_rpe", lambda r: rpe_of(r) is not None)]


def comparable_sets(valid, tolerance):
    """Section 3, steps 2-3: the sets within `tolerance` of the reference load, and that load."""
    counts = Counter(round(r["weight_kg"], 2) for r in valid)
    key = max(counts, key=lambda weight: (counts[weight], weight))
    # PENDING #5 item 1: weights are rounded only to form groups. The reference is the heaviest raw weight of the
    # winning group, and raw weights are compared with it.
    ref = max(r["weight_kg"] for r in valid if round(r["weight_kg"], 2) == key)
    return [r for r in valid if _at_most(abs(r["weight_kg"] - ref), tolerance * ref)], ref


def _comparable_sessions(valid, tolerance):
    """Section 3, step 4: {date: mean RPE over the comparable sets}."""
    if not valid:
        return {}
    by_day = defaultdict(list)
    for row in comparable_sets(valid, tolerance)[0]:
        by_day[set_date(row)].append(rpe_of(row))
    return {day: sum(rpes) / len(rpes) for day, rpes in by_day.items()}


def rpe_drift(sets, exercise_id, as_of=None, config=None):
    """RPE drift at comparable load (section 3)."""
    config = config or load_config()
    valid, excluded = _split(_exercise_rows(sets, exercise_id, as_of, config), _drift_checks())
    if not valid:
        raise IndicatorError("rpe_missing")
    reference = comparable_sets(valid, config["drift"]["load_tolerance"])[1]
    sessions = _comparable_sessions(valid, config["drift"]["load_tolerance"])
    if len(sessions) < config["drift"]["min_sessions"]:
        raise IndicatorError("insufficient_comparable_sessions")
    points = sorted(sessions.items())
    value = slope(points)
    return {
        "series": points,
        "reference_load": reference,
        "rpe_drift_slope": value,
        "label": _label(value, config["drift"]["flat_per_week"]),
        "excluded": excluded,
    }


def compute_e1rm_and_drift(sets, exercise_id, as_of=None, bodyweight=None, config=None):
    """Both parts for one exercise. A part that fails is reported as {"error": code} next to the other."""
    config = config or load_config()
    # PENDING #5 item 9: invalid arguments first, then unknown_exercise, then the errors of each part.
    if bodyweight is not None and bodyweight <= 0:
        raise IndicatorError("invalid_bodyweight")
    _exercise_rows(sets, exercise_id, as_of, config)  # raises unknown_exercise
    result = {}
    # PENDING #5 item 3: insufficient_sessions stops the e1RM part only; drift is still computed and reported.
    for name, part in (("e1rm", e1rm_trend), ("drift", rpe_drift)):
        try:
            result[name] = part(sets, exercise_id, as_of, config)
        except IndicatorError as error:
            result[name] = {"error": error.code}
    if bodyweight is not None and "error" not in result["e1rm"]:
        result["e1rm"]["relative_strength"] = relative_strength(result["e1rm"]["e1rm_latest"], bodyweight)
    return result


# --- effective sets per muscle per week (section 4) -----------------------------------------------------------------


def _monday(day):
    return day - timedelta(days=day.weekday())


def weekly_sets(sets, exercises, as_of=None, allowed=None, config=None):
    """Effective sets per muscle and week (section 4).

    `exercises` maps a free-exercise-db id to its record (`primaryMuscles`, `secondaryMuscles`).
    """
    config = config or load_config()
    rules = config["weekly_sets"]
    if rules["week_start"] != "monday":
        raise ValueError("only monday weeks are defined in the spec")
    last = as_of or max((set_date(r) for r in sets), default=None)
    result = {"weeks": [], "cells": {}, "totals": {}, "means": {}, "trends": {}, "excluded": Counter(),
              "unknown_exercises": [], "no_rpe": False}
    if last is None:
        return result
    shown = rules["default_weeks"]
    weeks = [_monday(last) - timedelta(weeks=back) for back in range(shown - 1, -1, -1)]
    # PENDING #5 item 6: sets after the passed date are ignored even inside the last week shown.
    # PENDING #5 item 5: exclusions are counted inside the weeks shown only.
    rows = [r for r in sets if _monday(set_date(r)) >= weeks[0] and set_date(r) <= last]
    floor = rules["min_effective_rpe"]
    valid, excluded = _split(rows, [
        ("unknown", lambda r: r.get("exercise_id") in exercises),
        ("not_allowed", lambda r: allowed is None or r["exercise_id"] in allowed),
        ("low_rpe", lambda r: rpe_of(r) is None or _at_most(floor, rpe_of(r))),
    ])
    unknown = {r.get("exercise_name") or r.get("exercise_id") or "" for r in rows
               if _first_reason(r, []) is None and r.get("exercise_id") not in exercises}
    cells = defaultdict(lambda: defaultdict(float))
    for row in valid:
        week = _monday(set_date(row))
        record = exercises[row["exercise_id"]]
        primary = set(record["primaryMuscles"])
        for muscle in primary:
            cells[muscle][week] += rules["primary_muscle_weight"]
        for muscle in set(record["secondaryMuscles"]) - primary:
            cells[muscle][week] += rules["secondary_muscle_weight"]
    incomplete = last.weekday() != 6
    for muscle, values in cells.items():
        total = sum(values.values())
        result["totals"][muscle] = total
        # PENDING #5 item 7: the divisor is always the number of weeks shown, also for a shorter log.
        result["means"][muscle] = round(total / shown, 2)
        # PENDING #5 item 4: "weeks with sets" are the weeks in which this muscle has a value.
        with_sets = sorted(values)
        if incomplete and with_sets[-1] == weeks[-1] and len(with_sets) >= 3:
            with_sets = with_sets[:-1]
        change = values[with_sets[-1]] - values[with_sets[0]]
        result["trends"][muscle] = _label(change, rules["trend_flat_band"])
    result.update(weeks=weeks, excluded=excluded, unknown_exercises=sorted(unknown),
                  no_rpe=any(rpe_of(r) is None for r in valid))
    result["cells"] = {muscle: dict(values) for muscle, values in cells.items()}
    return result


# --- uncoupled acute and chronic load (section 5) -------------------------------------------------------------------


def uncoupled_load(sets, metric="tonnage", as_of=None, allowed=None, config=None):
    """Acute load, weekly chronic load and their heuristic ratio (section 5)."""
    config = config or load_config()
    rules = config["load"]
    # PENDING #5 item 9: an invalid argument is reported before any data error.
    if metric not in ("tonnage", "rpe_weighted"):
        raise IndicatorError("invalid_metric")
    weighted = metric == "rpe_weighted"
    checks = [
        ("missing_reps", lambda r: r.get("reps") is not None),
        ("no_weight", _has_weight),
        ("no_rpe", lambda r: not weighted or rpe_of(r) is not None),
        ("not_allowed", lambda r: allowed is None or r.get("exercise_id") in allowed),
    ]
    candidates = [r for r in sets if as_of is None or set_date(r) <= as_of]
    valid = [r for r in candidates if _first_reason(r, checks) is None]
    if not valid:
        raise IndicatorError("no_valid_sets")
    end = as_of or max(set_date(r) for r in valid)
    acute_days, chronic_days = rules["acute_days"], rules["chronic_days"]
    span = acute_days + chronic_days
    if max(days_before(end, r) for r in valid) < span - 1:
        raise IndicatorError("insufficient_history")
    acute = chronic = 0.0
    for row in valid:
        load = row["weight_kg"] * row["reps"]
        if weighted:
            load = load * rpe_of(row) / rules["rpe_divisor"]
        before = days_before(end, row)
        if before < acute_days:
            acute += load
        elif before < span:
            chronic += load
    # PENDING #5 item 5: exclusions are counted inside days 0 to 34 only.
    excluded = _split([r for r in candidates if 0 <= days_before(end, r) < span], checks)[1]
    weekly = chronic / (chronic_days / 7)
    return {
        "as_of": end,
        "acute_load": acute,
        "chronic_load_weekly": weekly,
        "acute_chronic_ratio": acute / weekly if weekly else None,
        "ratio_label": "heuristic",
        "flags": [] if weekly else ["chronic_zero_ratio_undefined"],
        "excluded": excluded,
    }


# --- data sufficiency (section 6) -----------------------------------------------------------------------------------


def check_data_sufficiency(sets, as_of=None, allowed=None, config=None):
    """Checks 1-5b of section 6 with the analyses they block."""
    config = config or load_config()
    rules = config["sufficiency"]
    rows = [
        r for r in sets
        if is_working(r) and r.get("exercise_id") not in (None, "", "unknown")
        and (allowed is None or r["exercise_id"] in allowed)
    ]
    end = as_of or max((set_date(r) for r in rows), default=None)
    rows = [r for r in rows if end is not None and days_before(end, r) >= 0]
    failed = []  # (check, message, blocked analyses)

    exercises = {r["exercise_id"] for r in rows}
    if len(exercises) < rules["min_matched_exercises"]:
        failed.append(("1", f"{len(exercises)} matched exercises; at least {rules['min_matched_exercises']} needed; "
                            "no analysis", ANALYSES))
    # PENDING #5 item 11: with no considered row there is no as_of, so only check 1 is evaluated.
    if rows:
        window = [r for r in rows if in_analysis_window(end, r, config)]
        dates = sorted({set_date(r) for r in window})
        gap = max(((b - a).days for a, b in zip(dates, dates[1:])), default=0)
        if gap > rules["max_gap_days"]:
            failed.append(("2", f"Largest gap of {gap} days inside the window; at most {rules['max_gap_days']} "
                                "allowed; no analysis", ANALYSES))
        # PENDING #5 item 10: days covered are counted over all considered rows, not only the window.
        covered = (max(set_date(r) for r in rows) - min(set_date(r) for r in rows)).days + 1
        if covered < 7 * rules["min_history_weeks"]:
            failed.append(("3", f"{covered} days of history; {7 * rules['min_history_weeks']} needed; "
                                "load ratio not assessed", ("load_ratio",)))
        per_exercise = defaultdict(list)
        for row in window:
            per_exercise[row["exercise_id"]].append(row)
        sessions = max(len({set_date(r) for r in group}) for group in per_exercise.values())
        if sessions < rules["min_sessions_per_exercise"]:
            failed.append(("4", f"At most {sessions} sessions per exercise in the window; "
                                f"{rules['min_sessions_per_exercise']} needed; e1RM trend and RPE drift not assessed",
                           ("e1rm_trend", "rpe_drift")))
        with_rpe = sum(rpe_of(r) is not None for r in window)
        if with_rpe / len(window) < rules["min_rpe_coverage"] - SLACK:
            failed.append(("5a", f"RPE logged on {with_rpe} of {len(window)} working sets; RPE drift not assessed",
                           ("rpe_drift",)))
        else:
            # PENDING #5 item 2: check 5b is evaluated only when check 5a passes.
            tolerance = config["drift"]["load_tolerance"]
            best = max(len(_comparable_sessions(_split(group, _drift_checks())[0], tolerance))
                       for group in per_exercise.values())
            if best < config["drift"]["min_sessions"]:
                failed.append(("5b", f"At most {best} sessions with RPE at comparable load; "
                                     f"{config['drift']['min_sessions']} needed; RPE drift not assessed",
                               ("rpe_drift",)))
    blocked = {name for _, _, names in failed for name in names}
    allowed_analyses = [name for name in ANALYSES if name not in blocked]
    return {
        "as_of": end,
        "sufficient": bool(allowed_analyses),
        "allowed_analyses": allowed_analyses,
        "failed_checks": [check for check, _, _ in failed],
        "reasons": [message for _, message, _ in failed],
    }
