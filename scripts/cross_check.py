"""Cross-check the indicator tools against the independent reference implementation (issue P3, #17).

Both sides run on the same inputs: the worked examples of docs/indicator-spec.md, the cases decided on #5, and the
OpenGym fixtures. The table compares every value; tolerances follow spec section 7 ([verifier] in
configs/indicators.yaml).

Status: OK = equal (within 1e-9), DIFF = different but within the section 7 tolerance, FAIL = beyond it, or a
different label, error or count. The exit code is 1 on any FAIL, and also on DIFF with --strict.

Usage: uv run python scripts/cross_check.py [--all] [--strict]
"""

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.model import CanonicalSet  # noqa: E402
from src.ingest.pipeline import ingest_workout_log  # noqa: E402
from src.ingest.store import open_store  # noqa: E402
from src.reference import indicators as ref  # noqa: E402
from src.reference.opengym import read_opengym  # noqa: E402
from src.tools.common import ToolError, ValueIdFactory  # noqa: E402
from src.tools.e1rm import compute_e1rm_and_drift  # noqa: E402
from src.tools.load import uncoupled_load_analyzer  # noqa: E402
from src.tools.sufficiency import check_data_sufficiency  # noqa: E402
from src.tools.weekly_sets import weekly_sets_per_muscle  # noqa: E402

CONFIG = ref.load_config()
VERIFIER = CONFIG["verifier"]
EXERCISES = {e["id"]: e for e in json.loads(
    (ROOT / "data/exercises/free-exercise-db.json").read_text(encoding="utf-8"))}
ALIASES = yaml.safe_load((ROOT / "data/exercises/aliases.yaml").read_text(encoding="utf-8"))["aliases"]
FIXTURES = ROOT / "data/fixtures/opengym"
LOG_ID = "cross_check"
START = datetime(2026, 1, 5, 10, 0)  # a Monday
LB = 0.45359237
SQUAT, BENCH = "Barbell_Squat", "Barbell_Bench_Press_-_Medium_Grip"
MISSING = "-"


# --- inputs ---------------------------------------------------------------------------------------------------------


def match_name(name):
    """Exercise matcher shared by both sides: exact alias, then lowercase alias."""
    return ALIASES.get(name) or ALIASES.get(name.strip().lower())


def s(day, weight=100, reps=5, rpe=None, kind="normal", ex=SQUAT):
    return {"workout_ts": START + timedelta(days=day), "exercise_id": ex, "exercise_name": ex, "set_type": kind,
            "weight_kg": weight, "reps": reps, "rpe": rpe, "failed": reps == 0}


def before(*days, **kwargs):
    return [s(50 - d, **kwargs) for d in days]


def example_scenarios():
    """(name, canonical set dicts, bodyweight) built from the spec text and the #5 decisions."""
    ex2 = [s(0, 60, 10, kind="warmup"), s(0, 100, 5, 8), s(0, 100, 4), s(7, 100, 6), s(7, 110, 0), s(14, 105, 5),
           s(14, 60, 12), s(21, 105, 6)]
    ex3 = [s(0, rpe=7), s(0, rpe=7), s(7, rpe=7.5), s(14, rpe=8), s(14, rpe=8), s(14, 90, rpe=6), s(21, rpe=8),
           s(21, rpe=9)]
    ex4 = [s(0, rpe=8, ex=BENCH)] * 3 + [s(0, kind="warmup", ex=BENCH), s(0, reps=0, ex=BENCH), s(0, rpe=6, ex=BENCH)]
    ex5 = [s(35 - d, reps=r) for d, r in ((0, 5), (6, 8), (7, 3), (8, 5), (34, 3), (35, 10))]
    return [
        ("spec 2 e1RM", ex2, 84.0),
        ("spec 3 drift", ex3, None),
        ("spec 4 weekly", ex4, None),
        ("spec 5 load", ex5, None),
        ("spec 6 sufficiency", before(0, 10, 20, 34), None),
        ("spec 6 day 33", before(0, 10, 20, 33), None),
        ("#5 item 1 lb reference", [s(0, 100 * LB, rpe=7), s(0, 100 * LB, rpe=7), s(7, 95 * LB, rpe=8),
                                    s(14, 105 * LB, rpe=8), s(21, 100 * LB, rpe=9)], None),
        ("#5 item 2 5b skipped", before(0, rpe=8) + before(10, 20, 34), None),
        ("#5 item 3 drift kept", [s(7 * i, 60, 12, r) for i, r in enumerate([7, 7.5, 8, 8.5])], None),
        ("#5 item 4 trend per muscle", [s(d, ex=BENCH) for d in (0, 0, 0, 0, 7, 7, 7, 7)] + [s(20)], None),
        ("#5 item 5 exclusions in window", [s(0, kind="warmup"), s(40, kind="warmup"), s(50)]
         + [s(d) for d in (16, 23, 30, 37, 44)] + [s(15, kind="warmup"), s(16, kind="warmup")], None),
        ("#5 item 7 mean over 6 weeks", [s(d, ex=BENCH) for d in (0, 0, 0, 13, 13, 13)], None),
        # #5 item 8 (RPE outside [1, 10]) has no scenario: CanonicalSet rejects such an RPE before any tool runs.
        ("#5 item 10 history", before(0, 10, 20, 30, 50), None),
        ("#5 item 11 unknown only", before(0, 10, ex="unknown"), None),
    ]


def canonical(rows):
    return [CanonicalSet(set_id=f"s{i}", workout_ts=r["workout_ts"], exercise_name_raw=r["exercise_name"] or "",
                         exercise_id=r["exercise_id"], set_index=1, set_type=r["set_type"], weight_kg=r["weight_kg"],
                         reps=r["reps"], rpe=r["rpe"], failed=r["failed"], source_unit="kg", source_app="cross_check")
            for i, r in enumerate(rows)]


class ListStore:
    """A store holding one log, for the synthetic scenarios."""

    def __init__(self, sets):
        self.sets = sets

    def get_sets(self, log_id, filters=None):
        return list(self.sets)


def fixture_scenarios():
    """(name, reference sets, tool store, log id) for the OpenGym fixtures."""
    paths = [FIXTURES / "david_anonymized.csv", FIXTURES / "fineas_anonymized.csv"]
    paths += sorted((FIXTURES / "traps").glob("*.csv"))
    for path in paths:
        raw = read_opengym(path)
        mapping = {r["exercise_id"]: match_name(r["exercise_name"]) for r in raw}
        store = open_store()
        log_id = ingest_workout_log(path, store=store, matcher=match_name).log_id
        yield path.relative_to(FIXTURES).as_posix(), read_opengym(path, mapping), store, log_id


# --- comparison -----------------------------------------------------------------------------------------------------


def tolerance(name, unit, value):
    """Section 7 tolerance class of a value; None means exact."""
    if name.endswith(VERIFIER["slope_suffix"]):
        return VERIFIER["slope_abs"]
    if name in VERIFIER["ratio_names"]:
        return VERIFIER["ratio_abs"]
    if unit in VERIFIER["load_units"] or name in VERIFIER["load_names"]:
        return max(VERIFIER["load_abs"], VERIFIER["load_rel"] * abs(value))
    return None


class Table:
    def __init__(self):
        self.rows = []

    def add(self, scenario, key, reference, tool, name="", unit=None):
        numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (reference, tool))
        if numeric:
            diff = abs(reference - tool)
            tol = tolerance(name, unit, reference)
            if diff <= 1e-9:
                status = "OK"
            elif tol is not None and diff <= tol + 1e-9:
                status = "DIFF"
            else:
                status = "FAIL"
            self.rows.append((scenario, key, reference, tool, diff, tol, status))
        else:
            self.rows.append((scenario, key, reference, tool, None, None, "OK" if reference == tool else "FAIL"))

    def show(self, show_all):
        def fmt(v):
            if v is None:
                return ""
            if isinstance(v, float):
                return f"{v:.6g}" if math.isfinite(v) else str(v)
            return str(v)

        head = ("scenario", "value", "reference", "tool", "|diff|", "tol", "status")
        shown = [r for r in self.rows if show_all or r[-1] != "OK"]
        cells = [head] + [tuple(fmt(v) for v in r) for r in shown]
        widths = [min(48, max(len(c[i]) for c in cells)) for i in range(len(head))]
        for c in cells:
            print("  ".join(v[:48].ljust(w) for v, w in zip(c, widths)).rstrip())
        counts = Counter(r[-1] for r in self.rows)
        print(f"\n{len(self.rows)} values: " + ", ".join(f"{k} {counts[k]}" for k in ("OK", "DIFF", "FAIL")))
        return counts


def nonzero(counts):
    return {k: v for k, v in dict(counts or {}).items() if v}


def safe(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except ref.IndicatorError as error:
        return ToolError(code=error.code, message="")
    except Exception as error:  # noqa: BLE001 - reported in the table
        return ToolError(code=f"exception {type(error).__name__}: {error}", message="")


def compare_e1rm(table, scenario, ref_sets, store, log_id, exercise, bodyweight):
    tag = f"{exercise} "
    mine = safe(ref.compute_e1rm_and_drift, ref_sets, exercise, bodyweight=bodyweight, config=CONFIG)
    tool = safe(compute_e1rm_and_drift, store, log_id, exercise, bodyweight, ids=ValueIdFactory())
    if isinstance(mine, ToolError):
        table.add(scenario, tag + "error", mine.code, getattr(tool, "code", None))
        return
    e1rm, drift = mine["e1rm"], mine["drift"]
    table.add(scenario, tag + "e1rm error", e1rm.get("error"), tool.code if isinstance(tool, ToolError) else None)
    if isinstance(tool, ToolError):
        tool_drift_slope = tool_drift_error = tool_drift_trend = MISSING  # the tool returned no drift part
    elif "error" not in e1rm:
        values = {v.value_id: v.value for v in tool.values}
        by_name = {v.name: v.value for v in tool.values}
        for series in ("epley", "brzycki", "rpe_adjusted"):
            mine_points = dict(e1rm["series"][series])
            tool_points = {sess.date: values.get(getattr(sess, series)) for sess in tool.sessions
                           if getattr(sess, series) is not None}
            for day in sorted(set(mine_points) | set(tool_points)):
                table.add(scenario, f"{tag}{series} {day}", mine_points.get(day, MISSING),
                          tool_points.get(day, MISSING), "e1rm", "kg")
        table.add(scenario, tag + "e1rm_slope", e1rm["e1rm_slope"], by_name.get("e1rm_slope", MISSING), "e1rm_slope")
        table.add(scenario, tag + "sessions", e1rm["sessions"], tool.sessions_used)
        table.add(scenario, tag + "trend", e1rm["label"], tool.trend)
        table.add(scenario, tag + "excluded", nonzero(e1rm["excluded"]), nonzero(tool.excluded))
        if bodyweight is not None:
            table.add(scenario, tag + "relative_strength", e1rm["relative_strength"],
                      by_name.get("relative_strength", MISSING), "relative_strength")
        tool_drift_slope = by_name.get("rpe_drift_slope", MISSING)
        tool_drift_error = tool.drift_error.code if tool.drift_error else None
        tool_drift_trend = tool.drift_trend
    else:
        tool_drift_slope = tool_drift_error = tool_drift_trend = MISSING  # both sides stopped the e1RM part
    table.add(scenario, tag + "drift error", drift.get("error"), tool_drift_error)
    if "error" not in drift:
        table.add(scenario, tag + "rpe_drift_slope", drift["rpe_drift_slope"], tool_drift_slope, "rpe_drift_slope")
        table.add(scenario, tag + "drift trend", drift["label"], tool_drift_trend)


def compare_weekly(table, scenario, ref_sets, store, log_id):
    mine = safe(ref.weekly_sets, ref_sets, EXERCISES, config=CONFIG)
    tool = safe(weekly_sets_per_muscle, store, log_id, ids=ValueIdFactory())
    if isinstance(mine, ToolError) or isinstance(tool, ToolError):
        table.add(scenario, "weekly error", getattr(mine, "code", None), getattr(tool, "code", None))
        return
    tool_cells = {(c.muscle, c.week_start): c.effective_sets for c in tool.table}
    mine_cells = {(m, week.isoformat()): v for m, weeks in mine["cells"].items() for week, v in weeks.items()}
    for key in sorted(set(mine_cells) | set(tool_cells)):
        table.add(scenario, f"weekly {key[0]} {key[1]}", mine_cells.get(key, MISSING), tool_cells.get(key, MISSING),
                  "effective_sets")
    by_name = {v.name: v.value for v in tool.values}
    for muscle in sorted(mine["totals"]):
        slug = muscle.replace(" ", "_")
        table.add(scenario, f"weekly total {muscle}", mine["totals"][muscle],
                  by_name.get(f"weekly_sets_total_{slug}", MISSING), "effective_sets")
        table.add(scenario, f"weekly mean {muscle}", mine["means"][muscle],
                  by_name.get(f"weekly_sets_mean_{slug}", MISSING), "effective_sets")
    for item in tool.summary.get("top_muscles", []):  # the tool reports trends for its top muscles only
        table.add(scenario, f"weekly trend {item['muscle']}", mine["trends"].get(item["muscle"], MISSING),
                  item["trend"])
    table.add(scenario, "weekly weeks", [w.isoformat() for w in mine["weeks"]], list(tool.weeks_evaluated))
    table.add(scenario, "weekly excluded", nonzero(mine["excluded"]), nonzero(tool.excluded_counts))
    table.add(scenario, "weekly no_rpe flag", mine["no_rpe"], "no_rpe" in tool.flags)
    table.add(scenario, "weekly unknown exercises", sorted(mine["unknown_exercises"]),
              sorted(tool.unknown_exercises))


def compare_load(table, scenario, ref_sets, store, log_id):
    for metric, unit in (("tonnage", "kg"), ("rpe_weighted", "kg_rpe_weighted")):
        tag = f"load {metric} "
        mine = safe(ref.uncoupled_load, ref_sets, metric, config=CONFIG)
        tool = safe(uncoupled_load_analyzer, store, log_id, metric, ids=ValueIdFactory())
        if isinstance(mine, ToolError) or isinstance(tool, ToolError):
            table.add(scenario, tag + "error", getattr(mine, "code", None), getattr(tool, "code", None))
            continue
        by_name = {v.name: v.value for v in tool.values}
        table.add(scenario, tag + "acute_load", mine["acute_load"], by_name.get("acute_load", MISSING),
                  "acute_load", unit)
        table.add(scenario, tag + "chronic_load_weekly", mine["chronic_load_weekly"],
                  by_name.get("chronic_load_weekly", MISSING), "chronic_load_weekly", unit)
        ratio = mine["acute_chronic_ratio"]
        table.add(scenario, tag + "acute_chronic_ratio", MISSING if ratio is None else ratio,
                  by_name.get("acute_chronic_ratio", MISSING), "acute_chronic_ratio")
        table.add(scenario, tag + "flags", mine["flags"], list(tool.summary.get("flags", [])))
        table.add(scenario, tag + "excluded", nonzero(mine["excluded"]), nonzero(tool.summary.get("excluded")))


def compare_sufficiency(table, scenario, ref_sets, store, log_id):
    mine = safe(ref.check_data_sufficiency, ref_sets, config=CONFIG)
    tool = safe(check_data_sufficiency, store, log_id, ids=ValueIdFactory())
    if isinstance(mine, ToolError) or isinstance(tool, ToolError):
        table.add(scenario, "sufficiency error", getattr(mine, "code", None), getattr(tool, "code", None))
        return
    # "the four names minus the blocked ones" is a set, so the order is not compared
    table.add(scenario, "sufficiency allowed", sorted(mine["allowed_analyses"]), sorted(tool.allowed_analyses))
    table.add(scenario, "sufficiency sufficient", mine["sufficient"], tool.sufficient)
    table.add(scenario, "sufficiency reasons", len(mine["reasons"]), len(tool.reasons))


def run_scenario(table, scenario, ref_sets, store, log_id, bodyweight=None):
    exercises = sorted({r["exercise_id"] for r in ref_sets if r["exercise_id"] not in (None, "", "unknown")})
    for exercise in exercises:
        compare_e1rm(table, scenario, ref_sets, store, log_id, exercise, bodyweight)
    compare_weekly(table, scenario, ref_sets, store, log_id)
    compare_load(table, scenario, ref_sets, store, log_id)
    compare_sufficiency(table, scenario, ref_sets, store, log_id)


def compare_arguments(table):
    """Cases that need a passed as_of or invalid arguments (#5 items 6 and 9)."""
    rows = [s(4, ex=BENCH)] * 3 + [s(-30, ex=BENCH)]
    store = ListStore(canonical(rows))
    as_of = (START + timedelta(days=2)).date()  # Wednesday; the sets on Friday follow it
    mine = ref.weekly_sets(rows, EXERCISES, as_of=as_of, config=CONFIG)
    tool = safe(weekly_sets_per_muscle, store, LOG_ID, as_of=as_of, ids=ValueIdFactory())
    tool_total = {v.name: v.value for v in getattr(tool, "values", [])}.get("weekly_sets_total_chest", 0.0)
    table.add("#5 item 6 passed date", "weekly total chest", mine["totals"].get("chest", 0.0), tool_total,
              "effective_sets")
    ex2 = example_scenarios()[0][1]
    store = ListStore(canonical(ex2))
    cases = [
        ("bodyweight 0 and unknown exercise", (ex2, "Nope", 0.0), (store, LOG_ID, "Nope", 0.0)),
        ("sets only after as_of", (ex2, SQUAT, None, (START - timedelta(days=1)).date()),
         (store, LOG_ID, SQUAT, None)),
    ]
    for name, mine_args, tool_args in cases:
        if len(mine_args) == 4:
            mine = safe(ref.compute_e1rm_and_drift, mine_args[0], mine_args[1], as_of=mine_args[3], config=CONFIG)
            tool = safe(compute_e1rm_and_drift, *tool_args, as_of=mine_args[3], ids=ValueIdFactory())
            mine_code = mine.code if isinstance(mine, ToolError) else mine["e1rm"].get("error")
        else:
            mine = safe(ref.compute_e1rm_and_drift, mine_args[0], mine_args[1], bodyweight=mine_args[2],
                        config=CONFIG)
            tool = safe(compute_e1rm_and_drift, *tool_args, ids=ValueIdFactory())
            mine_code = getattr(mine, "code", None)
        table.add("#5 item 9 precedence", name, mine_code, getattr(tool, "code", None))
    tool = safe(uncoupled_load_analyzer, ListStore([]), LOG_ID, "volume")
    table.add("#5 item 9 precedence", "invalid metric on empty log",
              safe(ref.uncoupled_load, [], "volume", config=CONFIG).code, getattr(tool, "code", None))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="show OK rows too")
    parser.add_argument("--strict", action="store_true", help="exit 1 on DIFF as well")
    args = parser.parse_args(argv)
    table = Table()
    for scenario, rows, bodyweight in example_scenarios():
        run_scenario(table, scenario, rows, ListStore(canonical(rows)), LOG_ID, bodyweight)
    for scenario, ref_sets, store, log_id in fixture_scenarios():
        run_scenario(table, scenario, ref_sets, store, log_id)
    compare_arguments(table)
    counts = table.show(args.all)
    return 1 if counts["FAIL"] or (args.strict and counts["DIFF"]) else 0


if __name__ == "__main__":
    sys.exit(main())
