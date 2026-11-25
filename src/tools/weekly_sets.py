"""Tool: ``weekly_sets_per_muscle`` (issue M3, #34; plan §5.7).

Computes effective sets per muscle per calendar week (Monday-start ISO weeks):
- Effective set = non-warm-up, non-failed (not ``failed`` and ``reps != 0``), and
  ``rpe >= 7.0`` when RPE is logged. If RPE is not logged (``None``), the set is
  counted and the result carries the ``"no_rpe"`` flag.
- Primary muscle receives 1.0 set, secondary muscle receives 0.5 set (from free-exercise-db, D7).
- Exercises with ``exercise_id == "unknown"`` or ``None`` are excluded and listed.
- Every numeric cell carries a unique ``value_id`` and full ``Provenance``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from src.exercises.loader import Exercise, load_exercises, muscle_weights
from src.tools._common_provisional import (
    Provenance,
    ToolResult,
    Value,
    ValueIdFactory,
    config_hash,
)

TOOL_VERSION = "weekly_sets_per_muscle-0.1.0"

DEFAULT_CONFIG: dict[str, Any] = {
    "default_weeks": 6,
    "min_effective_rpe": 7.0,
    "week_start": "monday",
    "primary_muscle_weight": 1.0,
    "secondary_muscle_weight": 0.5,
    "trend_flat_band": 0.5,
}


class SetStore(Protocol):
    """Minimal store interface compatible with D4's DuckDB store."""

    def get_sets(
        self, log_id: str, filters: Mapping[str, Any] | None = None
    ) -> Iterable[Any]:
        ...


class MuscleWeekCell(BaseModel):
    """Single muscle x week effective-set cell with its provenance value_id."""

    muscle: str
    week_start: str
    effective_sets: float
    value_id: str


class MuscleSummary(BaseModel):
    """Compact per-muscle summary for LLM consumption."""

    muscle: str
    total_sets: float
    mean_weekly_sets: float
    trend: Literal["up", "flat", "down"]


class WeeklySetsResult(ToolResult):
    """Structured output of ``weekly_sets_per_muscle``."""

    tool_version: str = TOOL_VERSION
    week_start_day: str = "monday"
    weeks_evaluated: list[str] = Field(default_factory=list)
    table: list[MuscleWeekCell] = Field(default_factory=list)
    unknown_exercises: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    excluded_counts: dict[str, int] = Field(default_factory=dict)


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


def _monday_of(d: date) -> date:
    """Return the Monday (ISO weekday 1) of the calendar week containing ``d``."""
    return d - timedelta(days=d.weekday())


def _trend_direction(series: Sequence[float], flat_band: float) -> Literal["up", "flat", "down"]:
    if len(series) < 2:
        return "flat"
    delta = series[-1] - series[0]
    if delta > flat_band:
        return "up"
    if delta < -flat_band:
        return "down"
    return "flat"


def weekly_sets_per_muscle(
    store: SetStore,
    log_id: str,
    weeks: int = 6,
    *,
    allowed_exercise_ids: Sequence[str] | None = None,
    as_of: date | None = None,
    exercises: Mapping[str, Exercise] | None = None,
    config: Mapping[str, Any] | None = None,
) -> WeeklySetsResult:
    """Compute effective sets per muscle per Monday-start week over the last ``weeks`` weeks."""
    cfg = dict(DEFAULT_CONFIG)
    if config is not None:
        cfg.update(config)
    cfg["weeks"] = weeks
    cfg_digest = config_hash(cfg)

    min_rpe = float(cfg["min_effective_rpe"])
    flat_band = float(cfg["trend_flat_band"])
    ex_map = exercises if exercises is not None else load_exercises()
    allowed_set = set(allowed_exercise_ids) if allowed_exercise_ids is not None else None

    rows = list(store.get_sets(log_id))
    if not rows:
        return WeeklySetsResult(
            weeks_evaluated=[],
            table=[],
            values=[],
            unknown_exercises=[],
            flags=[],
            excluded_counts={"warmup": 0, "failed": 0, "low_rpe": 0, "unknown": 0, "not_allowed": 0},
            summary={"top_muscles": [], "weeks_covered": 0, "unknown_exercises": []},
        )

    latest_date = as_of if as_of is not None else max(_to_date(_get_field(r, "workout_ts")) for r in rows)
    latest_monday = _monday_of(latest_date)
    week_mondays = [
        latest_monday - timedelta(weeks=offset) for offset in range(weeks - 1, -1, -1)
    ]
    week_labels = [w.isoformat() for w in week_mondays]
    week_set = set(week_labels)

    excluded = {"warmup": 0, "failed": 0, "low_rpe": 0, "unknown": 0, "not_allowed": 0}
    unknown_names: set[str] = set()
    flags_set: set[str] = set()

    # Accumulate weighted sets and contributing set_ids per (muscle, week_start)
    totals: dict[tuple[str, str], float] = defaultdict(float)
    row_ids: dict[tuple[str, str], list[str]] = defaultdict(list)

    for idx, row in enumerate(rows):
        d = _to_date(_get_field(row, "workout_ts"))
        wk = _monday_of(d).isoformat()
        if wk not in week_set:
            continue

        set_type = str(_get_field(row, "set_type", "normal") or "normal").lower()
        if set_type in {"warmup", "warm-up", "warm_up"}:
            excluded["warmup"] += 1
            continue

        failed = bool(_get_field(row, "failed", False))
        reps = _get_field(row, "reps", None)
        if failed or (reps is not None and reps == 0):
            excluded["failed"] += 1
            continue

        ex_id = _get_field(row, "exercise_id")
        if not isinstance(ex_id, str) or not ex_id.strip() or ex_id == "unknown" or ex_id not in ex_map:
            excluded["unknown"] += 1
            raw_name = _get_field(row, "exercise_name_raw") or str(ex_id or "unknown")
            unknown_names.add(str(raw_name))
            continue

        if allowed_set is not None and ex_id not in allowed_set:
            excluded["not_allowed"] += 1
            continue

        rpe = _get_field(row, "rpe", None)
        if rpe is None:
            flags_set.add("no_rpe")
        elif float(rpe) < min_rpe:
            excluded["low_rpe"] += 1
            continue

        set_id = str(_get_field(row, "set_id") or f"row_{idx}")
        weights = muscle_weights(ex_id, ex_map)
        for muscle, weight in weights.items():
            key = (muscle.value, wk)
            totals[key] += weight
            row_ids[key].append(set_id)

    if unknown_names:
        flags_set.add("unknown_exercises_excluded")

    id_factory = ValueIdFactory()
    values: list[Value] = []
    table: list[MuscleWeekCell] = []

    muscles_present = sorted({m for m, _ in totals})
    for muscle in muscles_present:
        for wk in week_labels:
            val = round(totals.get((muscle, wk), 0.0), 4)
            if val == 0.0 and (muscle, wk) not in totals:
                continue
            vid = id_factory.new("weekly_sets")
            values.append(
                Value(
                    value_id=vid,
                    name=f"weekly_sets_{muscle.replace(' ', '_')}_{wk}",
                    value=val,
                    unit="effective_sets",
                    provenance=Provenance(
                        formula="sum(1.0*primary + 0.5*secondary for effective sets in Monday-start week)",
                        input_row_ids=list(row_ids.get((muscle, wk), [])),
                        tool_version=TOOL_VERSION,
                        config_hash=cfg_digest,
                    ),
                )
            )
            table.append(
                MuscleWeekCell(
                    muscle=muscle,
                    week_start=wk,
                    effective_sets=val,
                    value_id=vid,
                )
            )

    muscle_summaries: list[MuscleSummary] = []
    for muscle in muscles_present:
        series = [round(totals.get((muscle, wk), 0.0), 4) for wk in week_labels]
        total_sets = round(sum(series), 4)
        active_weeks = [v for v in series if v > 0.0]
        mean_sets = round(total_sets / len(week_labels), 2) if week_labels else 0.0
        muscle_summaries.append(
            MuscleSummary(
                muscle=muscle,
                total_sets=total_sets,
                mean_weekly_sets=mean_sets,
                trend=_trend_direction(active_weeks if len(active_weeks) >= 2 else series, flat_band),
            )
        )

    muscle_summaries.sort(key=lambda m: (-m.total_sets, m.muscle))
    top_muscles = [m.model_dump() for m in muscle_summaries[:5]]

    return WeeklySetsResult(
        week_start_day="monday",
        weeks_evaluated=week_labels,
        table=table,
        values=values,
        unknown_exercises=sorted(unknown_names),
        flags=sorted(flags_set),
        excluded_counts=excluded,
        summary={
            "week_start_day": "monday",
            "weeks_covered": len(week_labels),
            "top_muscles": top_muscles,
            "unknown_exercises": sorted(unknown_names),
            "flags": sorted(flags_set),
        },
    )
