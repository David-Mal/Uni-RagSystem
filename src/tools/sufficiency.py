"""Tool: ``check_data_sufficiency`` (issue M2, #33; plan §2.5, §5.7).

Decides what analyses can run on a stored workout log and when the system must abstain
(fully or partially). Implements section 6 of ``docs/indicator-spec.md``; thresholds are in ``configs/indicators.yaml``.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from src.tools.common import (
    Provenance,
    ToolResult,
    Value,
    ValueIdFactory,
    config_hash,
    load_indicator_config,
)

TOOL_VERSION = "check_data_sufficiency-1.0.0"

SUFFICIENCY_KEYS = (
    "min_history_weeks",
    "min_sessions_per_exercise",
    "min_rpe_coverage",
    "max_gap_days",
    "min_matched_exercises",
)
SLACK = 1e-9

AnalysisName = Literal["e1rm_trend", "rpe_drift", "weekly_volume", "load_ratio"]

class SetStore(Protocol):
    """Minimal store interface compatible with D4's DuckDB store."""

    def get_sets(
        self, log_id: str, filters: Mapping[str, Any] | None = None
    ) -> Iterable[Any]:
        """Return canonical sets (Pydantic models or dicts) for ``log_id``."""
        ...


class SufficiencyResult(ToolResult):
    """Structured output of ``check_data_sufficiency``."""

    tool_version: str = TOOL_VERSION
    sufficient: bool
    partial_abstention: bool = False
    reasons: list[str] = Field(default_factory=list)
    allowed_analyses: list[AnalysisName] = Field(default_factory=list)
    eligible_exercise_ids: list[str] = Field(default_factory=list)


def load_sufficiency_config(path: Path | str | None = None) -> dict[str, Any]:
    """Thresholds of spec §6 as one flat dict. A missing key is an error, never a silent default."""
    cfg = load_indicator_config(Path(path) if path is not None else None)
    return {
        **{k: cfg["sufficiency"][k] for k in SUFFICIENCY_KEYS},
        "analysis_window_weeks": cfg["window"]["analysis_weeks"],
        "comparable_load_tolerance": cfg["drift"]["load_tolerance"],
        "min_comparable_load_sessions": cfg["drift"]["min_sessions"],
    }


def _get_field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _to_date(ts: Any) -> date:
    if isinstance(ts, datetime):
        return ts.date()
    if isinstance(ts, date):
        return ts
    if isinstance(ts, str):
        return datetime.fromisoformat(ts).date()
    raise ValueError(f"Unsupported workout_ts value: {ts!r}")


def _is_working_set(row: Any) -> bool:
    set_type = str(_get_field(row, "set_type", "normal") or "normal").lower()
    if set_type in {"warmup", "warm-up", "warm_up"}:
        return False
    failed = bool(_get_field(row, "failed", False))
    reps = _get_field(row, "reps", None)
    return not (failed or reps is not None and reps == 0)


def _is_matched_exercise(exercise_id: Any) -> bool:
    return isinstance(exercise_id, str) and bool(exercise_id.strip()) and exercise_id != "unknown"


def _max_comparable_load_sessions(
    working_sets: Sequence[Any],
    tolerance: float,
) -> int:
    """Count the maximum number of sessions sharing a comparable load (+-tolerance) per exercise."""
    by_exercise: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in working_sets:
        ex_id = _get_field(row, "exercise_id")
        weight = _get_field(row, "weight_kg")
        rpe = _get_field(row, "rpe")
        if _is_matched_exercise(ex_id) and weight is not None and weight > 0 and rpe is not None:
            by_exercise[ex_id].append((_to_date(_get_field(row, "workout_ts")), float(weight)))

    best = 0
    for entries in by_exercise.values():
        # Reference load = most frequent load, compared at 2 decimals (ties broken by highest load)
        counts = Counter(round(w, 2) for _, w in entries)
        ref_weight = min(counts.items(), key=lambda kv: (-kv[1], -kv[0]))[0]
        sessions = {d for d, w in entries if abs(w - ref_weight) <= tolerance * ref_weight + SLACK}
        best = max(best, len(sessions))
    return best


def check_data_sufficiency(
    store: SetStore,
    log_id: str,
    allowed_exercise_ids: Sequence[str] | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    ids: ValueIdFactory | None = None,
) -> SufficiencyResult:
    """Evaluate all plan §2.5 sufficiency thresholds for ``log_id``.

    ``config`` overrides single thresholds of ``load_sufficiency_config``. Pass the run's ``ids`` so that value ids stay
    unique across tools.
    """
    cfg = dict(load_sufficiency_config())
    if config is not None:
        cfg.update(config)

    min_history_weeks = int(cfg["min_history_weeks"])
    min_history_days = min_history_weeks * 7
    window_weeks = int(cfg["analysis_window_weeks"])
    window_days = window_weeks * 7
    min_sessions = int(cfg["min_sessions_per_exercise"])
    min_rpe_cov = float(cfg["min_rpe_coverage"])
    min_comp_sessions = int(cfg["min_comparable_load_sessions"])
    comp_tol = float(cfg["comparable_load_tolerance"])
    max_gap_days = int(cfg["max_gap_days"])
    min_matched = int(cfg["min_matched_exercises"])

    all_rows = list(store.get_sets(log_id))

    # Apply allowed_exercise_ids filter (e.g. yellow exclusions from safety gate)
    if allowed_exercise_ids is not None:
        allowed_set = set(allowed_exercise_ids)
        rows = [r for r in all_rows if _get_field(r, "exercise_id") in allowed_set]
    else:
        rows = all_rows

    working_sets = [r for r in rows if _is_working_set(r)]

    if not working_sets:
        return SufficiencyResult(
            sufficient=False,
            partial_abstention=False,
            reasons=["0 working sets available after exclusions; no analyses allowed"],
            allowed_analyses=[],
            eligible_exercise_ids=[],
            summary={"working_sets": 0, "matched_exercises": 0},
        )

    matched_sets = [r for r in working_sets if _is_matched_exercise(_get_field(r, "exercise_id"))]
    matched_exercise_ids = sorted({_get_field(r, "exercise_id") for r in matched_sets})

    reasons: list[str] = []

    # Check 1: Matched exercises >= min_matched_exercises
    if len(matched_exercise_ids) < min_matched:
        reasons.append(
            f"Matched exercises: {len(matched_exercise_ids)} "
            f"(minimum {min_matched} required); no analyses allowed"
        )
        return SufficiencyResult(
            sufficient=False,
            partial_abstention=False,
            reasons=reasons,
            allowed_analyses=[],
            eligible_exercise_ids=[],
            summary={"working_sets": len(working_sets), "matched_exercises": 0},
        )

    all_dates = sorted({_to_date(_get_field(r, "workout_ts")) for r in matched_sets})
    earliest_date = all_dates[0]
    latest_date = all_dates[-1]
    # Days covered, so a first and last date 34 days apart cover 35 days = 5 weeks (spec §6, check 3)
    covered_days = (latest_date - earliest_date).days + 1
    window_start = latest_date - timedelta(days=window_days - 1)  # days 0..41

    window_sets = [r for r in matched_sets if _to_date(_get_field(r, "workout_ts")) >= window_start]
    window_dates = sorted({_to_date(_get_field(r, "workout_ts")) for r in window_sets})

    # Check 2: Gaps > max_gap_days inside the analyzed window (gap == max_gap_days passes)
    largest_gap = 0
    for prev_d, curr_d in itertools.pairwise(window_dates):
        gap = (curr_d - prev_d).days
        largest_gap = max(largest_gap, gap)
    has_blocking_gap = largest_gap > max_gap_days
    if has_blocking_gap:
        reasons.append(
            f"Training gap of {largest_gap} days inside the last {window_weeks} weeks "
            f"(maximum allowed is {max_gap_days} days); trend and load analyses not assessed"
        )

    # Check 3: days covered >= min_history_weeks (35 days)
    has_sufficient_history = covered_days >= min_history_days
    if not has_sufficient_history:
        reasons.append(
            f"History covers {covered_days} days "
            f"(minimum {min_history_days} days = {min_history_weeks} weeks required); load_ratio not assessed"
        )

    # Check 4: Sessions per analyzed exercise in the last 6 weeks >= 4
    sessions_by_ex: dict[str, set[date]] = defaultdict(set)
    for r in window_sets:
        sessions_by_ex[_get_field(r, "exercise_id")].add(_to_date(_get_field(r, "workout_ts")))

    eligible_for_trend = sorted(
        ex_id for ex_id, dates in sessions_by_ex.items() if len(dates) >= min_sessions
    )
    has_sufficient_sessions = len(eligible_for_trend) >= 1
    if not has_sufficient_sessions:
        max_sess = max((len(d) for d in sessions_by_ex.values()), default=0)
        reasons.append(
            f"Maximum {max_sess} sessions per exercise in the last {window_weeks} weeks "
            f"(minimum {min_sessions} required); e1rm_trend and rpe_drift not assessed"
        )

    # Check 5: RPE coverage >= 50% of working sets AND >= 4 sessions at comparable load (+-5%)
    rpe_count = sum(1 for r in window_sets if _get_field(r, "rpe") is not None)
    total_window_sets = len(window_sets)
    rpe_coverage = (rpe_count / total_window_sets) if total_window_sets > 0 else 0.0
    comparable_sessions = _max_comparable_load_sessions(window_sets, comp_tol)

    rpe_cov_ok = rpe_coverage >= min_rpe_cov - SLACK
    comp_ok = comparable_sessions >= min_comp_sessions

    if not rpe_cov_ok:
        reasons.append(
            f"RPE logged on {rpe_count} of {total_window_sets} working sets; "
            f"RPE drift not assessed"
        )
    elif not comp_ok:
        reasons.append(
            f"Only {comparable_sessions} sessions at comparable load "
            f"(+/-{int(comp_tol * 100)}%, minimum {min_comp_sessions} required); "
            f"RPE drift not assessed"
        )

    # Determine allowed_analyses (partial abstention supported)
    allowed_analyses: list[AnalysisName] = []
    if not has_blocking_gap:
        allowed_analyses.append("weekly_volume")
        if has_sufficient_history:
            allowed_analyses.append("load_ratio")
        if has_sufficient_sessions:
            allowed_analyses.append("e1rm_trend")
            if rpe_cov_ok and comp_ok:
                allowed_analyses.append("rpe_drift")

    sufficient = len(allowed_analyses) > 0
    partial_abstention = sufficient and len(reasons) > 0

    ids = ids or ValueIdFactory()
    digest = config_hash(cfg)

    def count(name: str, number: int, unit: str, formula: str, rows_used: Sequence[Any]) -> Value:
        return Value(
            value_id=ids.new(name),
            name=name,
            value=number,
            unit=unit,
            provenance=Provenance(
                formula=formula,
                input_row_ids=[str(_get_field(r, "set_id")) for r in rows_used],
                tool_version=TOOL_VERSION,
                config_hash=digest,
            ),
        )

    values = [
        count("history_days_covered", covered_days, "days", "(last date - first date) + 1", matched_sets),
        count("largest_gap_days", largest_gap, "days", "max days between consecutive dates in the window", window_sets),
        count("window_working_sets", total_window_sets, "sets", "count of matched working sets in the window", window_sets),
        count("rpe_logged_sets", rpe_count, "sets", "count of those sets with RPE", window_sets),
        count(
            "comparable_load_sessions", comparable_sessions, "sessions",
            "max over exercises of sessions with RPE at comparable load", window_sets,
        ),
    ]  # fmt: skip

    return SufficiencyResult(
        values=values,
        sufficient=sufficient,
        partial_abstention=partial_abstention,
        reasons=reasons,
        allowed_analyses=allowed_analyses,
        eligible_exercise_ids=eligible_for_trend,
        summary={
            "working_sets": len(working_sets),
            "matched_exercises": len(matched_exercise_ids),
            "history_days_covered": covered_days,
            "largest_gap_days": largest_gap,
            "rpe_logged_sets": rpe_count,
            "window_working_sets": total_window_sets,
            "comparable_load_sessions": comparable_sessions,
            "allowed_analyses": allowed_analyses,
        },
    )
