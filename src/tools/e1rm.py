"""Tool: ``compute_e1rm_and_drift`` (issue D8). Implements sections 1-3 of ``docs/indicator-spec.md``.

Pure and deterministic: no clock, no randomness, no network. Numbers keep full precision; only the summary is rounded.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from src.tools.common import (
    Provenance,
    ToolError,
    ToolResult,
    Value,
    ValueIdFactory,
    config_hash,
    load_indicator_config,
)

TOOL_VERSION = "compute_e1rm_and_drift-1.0.0"
SLACK = 1e-9
SUMMARY_SESSIONS = 6

Trend = Literal["up", "flat", "down"]


class SetRow(Protocol):
    """The fields of a canonical set that this tool reads."""

    set_id: str
    workout_ts: datetime
    exercise_id: str | None
    set_type: str
    weight_kg: float | None
    reps: int | None
    rpe: float | None
    failed: bool


class SetSource(Protocol):
    """Anything that returns the stored sets of a log."""

    def get_sets(self, log_id: str) -> Iterable[SetRow]: ...


class SessionE1rm(BaseModel):
    """e1RM of one session; each field is the value id of a series point, or ``None`` if the series has none there."""

    date: date
    epley: str
    brzycki: str
    rpe_adjusted: str | None = None


class E1rmResult(ToolResult):
    """e1RM series and trend. ``drift_error`` says why RPE drift is missing; it does not invalidate the rest."""

    exercise_id: str
    sessions: list[SessionE1rm]
    sessions_used: int
    trend: Trend
    drift_trend: Trend | None = None
    drift_error: ToolError | None = None
    excluded: dict[str, int] = Field(default_factory=dict)


@dataclass(frozen=True)
class _Point:
    day: date
    value: float
    set_ids: list[str]


def epley(weight: float, reps: float) -> float:
    """Epley e1RM."""
    return weight * (1 + reps / 30)


def brzycki(weight: float, reps: float) -> float:
    """Brzycki e1RM."""
    return weight * 36 / (37 - reps)


def reps_to_failure(reps: int, rpe: float) -> float:
    """Reps the set would have had at failure (reps in reserve = 10 - RPE)."""
    return reps + (10 - rpe)


def ols_slope_per_week(points: Sequence[tuple[date, float]]) -> float:
    """Least-squares slope against time in weeks since the first point (spec §1.5)."""
    first = points[0][0]
    xs = [(d - first).days / 7 for d, _ in points]
    ys = [y for _, y in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum((x - mx) ** 2 for x in xs)


def _is_warmup(s: SetRow) -> bool:
    return s.set_type == "warmup"


def _is_failed(s: SetRow) -> bool:
    return s.failed or s.reps == 0


def _trend(value: float, flat: float) -> Trend:
    if value > flat + SLACK:
        return "up"
    if value < -flat - SLACK:
        return "down"
    return "flat"


def _session_max(sets: Iterable[SetRow], estimate: Callable[[SetRow], float | None]) -> list[_Point]:
    by_day: dict[date, list[tuple[float, str]]] = {}
    for s in sets:
        value = estimate(s)
        if value is not None:
            by_day.setdefault(s.workout_ts.date(), []).append((value, s.set_id))
    return [_Point(d, max(v for v, _ in by_day[d]), [i for _, i in by_day[d]]) for d in sorted(by_day)]


def _drift_points(sets: Iterable[SetRow], cfg: Mapping[str, Any]) -> tuple[list[_Point], float] | ToolError:
    """Session means of RPE at the reference load, and that load (spec §3, steps 1-5)."""
    valid = [s for s in sets if s.weight_kg and s.rpe is not None]
    if not valid:
        return ToolError(code="rpe_missing", message="no loaded working set with RPE in the window; drift not assessed")
    counts = Counter(round(float(s.weight_kg), 2) for s in valid)  # type: ignore[arg-type]
    reference = max(counts, key=lambda w: (counts[w], w))
    tolerance = float(cfg["load_tolerance"]) * reference + SLACK
    by_day: dict[date, list[SetRow]] = {}
    for s in valid:
        if abs(float(s.weight_kg) - reference) <= tolerance:  # type: ignore[arg-type]
            by_day.setdefault(s.workout_ts.date(), []).append(s)
    points = [
        _Point(d, sum(float(s.rpe) for s in by_day[d]) / len(by_day[d]), [s.set_id for s in by_day[d]])  # type: ignore[arg-type]
        for d in sorted(by_day)
    ]
    if len(points) < int(cfg["min_sessions"]):
        return ToolError(
            code="insufficient_comparable_sessions",
            message=(
                f"{len(points)} sessions with RPE at comparable load (around {reference:g} kg); "
                f"{cfg['min_sessions']} needed; drift not assessed"
            ),
        )
    return points, reference


def compute_e1rm_and_drift(
    store: SetSource,
    log_id: str,
    exercise_id: str,
    bodyweight_kg: float | None = None,
    *,
    as_of: date | None = None,
    config: Mapping[str, Any] | None = None,
    ids: ValueIdFactory | None = None,
) -> E1rmResult | ToolError:
    """Estimated 1RM per session, its weekly trend, and RPE drift at comparable load for one exercise.

    Returns ``ToolError`` for ``unknown_exercise``, ``invalid_bodyweight`` or ``insufficient_sessions``. Missing or
    insufficient RPE only sets ``drift_error``. Pass the run's ``ids`` so that value ids stay unique across tools.
    """
    cfg = dict(config) if config is not None else load_indicator_config()
    e1rm_cfg, drift_cfg = cfg["e1rm"], cfg["drift"]
    decimals = int(cfg["rounding"]["summary_decimals"])
    ids = ids or ValueIdFactory()

    if bodyweight_kg is not None and not bodyweight_kg > 0:
        return ToolError(code="invalid_bodyweight", message=f"bodyweight must be positive, got {bodyweight_kg}")
    log = list(store.get_sets(log_id))
    of_exercise = [s for s in log if s.exercise_id == exercise_id]
    if not exercise_id or exercise_id == "unknown" or not of_exercise:
        return ToolError(code="unknown_exercise", message=f"no sets of exercise {exercise_id!r} in this log")

    working_days = [s.workout_ts.date() for s in log if not _is_warmup(s) and not _is_failed(s)]
    end = as_of or max(working_days, default=None)
    window_days = 7 * int(cfg["window"]["analysis_weeks"])
    excluded = {"warmup": 0, "failed": 0, "missing_reps": 0, "no_load": 0, "reps_gt_max": 0}
    working: list[SetRow] = []
    valid: list[SetRow] = []
    for s in sorted(of_exercise, key=lambda r: (r.workout_ts, r.set_id)):
        if end is None or not 0 <= (end - s.workout_ts.date()).days < window_days:
            continue
        if _is_warmup(s):
            excluded["warmup"] += 1
            continue
        if _is_failed(s):
            excluded["failed"] += 1
            continue
        working.append(s)
        if s.reps is None:
            excluded["missing_reps"] += 1
        elif not s.weight_kg:
            excluded["no_load"] += 1
        elif s.reps > int(e1rm_cfg["max_reps"]):
            excluded["reps_gt_max"] += 1
        else:
            valid.append(s)

    def adjusted(s: SetRow) -> float | None:
        if s.rpe is None:
            return None
        rtf = reps_to_failure(int(s.reps), float(s.rpe))  # type: ignore[arg-type]
        return epley(float(s.weight_kg), rtf) if rtf <= float(e1rm_cfg["max_reps"]) + SLACK else None  # type: ignore[arg-type]

    epley_points = _session_max(valid, lambda s: epley(float(s.weight_kg), int(s.reps)))  # type: ignore[arg-type]
    if len(epley_points) < int(e1rm_cfg["min_sessions"]):
        return ToolError(
            code="insufficient_sessions",
            message=(
                f"{len(epley_points)} sessions with valid sets of {exercise_id} in the last "
                f"{cfg['window']['analysis_weeks']} weeks; {e1rm_cfg['min_sessions']} needed; excluded sets: {excluded}"
            ),
        )
    brzycki_points = {
        p.day: p for p in _session_max(valid, lambda s: brzycki(float(s.weight_kg), int(s.reps)))  # type: ignore[arg-type]
    }
    adjusted_points = {p.day: p for p in _session_max(valid, adjusted)}

    used = {k: cfg[k] for k in ("window", "e1rm", "drift")}
    chash = config_hash({**used, "exercise_id": exercise_id, "as_of": str(end), "bodyweight_kg": bodyweight_kg})
    values: list[Value] = []

    def add(name: str, value: float | int, unit: str | None, formula: str, row_ids: Iterable[str]) -> Value:
        v = Value(
            value_id=ids.new(name),
            name=name,
            value=value,
            unit=unit,
            provenance=Provenance(
                formula=formula, input_row_ids=list(row_ids), tool_version=TOOL_VERSION, config_hash=chash
            ),
        )
        values.append(v)
        return v

    def brief(v: Value) -> dict[str, Any]:
        number = round(v.value, decimals) if isinstance(v.value, float) else v.value
        return {"value_id": v.value_id, "value": number, "unit": v.unit}

    sessions: list[SessionE1rm] = []
    recent: list[dict[str, Any]] = []
    for p in epley_points:
        ep = add("e1rm_epley", p.value, "kg", "max over session sets of weight_kg*(1+reps/30)", p.set_ids)
        bp = brzycki_points[p.day]
        bv = add("e1rm_brzycki", bp.value, "kg", "max over session sets of weight_kg*36/(37-reps)", bp.set_ids)
        ap = adjusted_points.get(p.day)
        av = None
        if ap is not None:
            formula = "max over session sets of weight_kg*(1+(reps+10-rpe)/30)"
            av = add("e1rm_rpe_adjusted", ap.value, "kg", formula, ap.set_ids)
        sessions.append(
            SessionE1rm(
                date=p.day, epley=ep.value_id, brzycki=bv.value_id, rpe_adjusted=av.value_id if av is not None else None
            )
        )
        recent.append({"date": p.day.isoformat(), "epley": brief(ep)})

    epley_ids = [i for p in epley_points for i in p.set_ids]
    slope = ols_slope_per_week([(p.day, p.value) for p in epley_points])
    mean = sum(p.value for p in epley_points) / len(epley_points)
    trend = _trend(100 * slope / mean, float(e1rm_cfg["flat_pct_per_week"]))
    slope_value = add("e1rm_slope", slope, "kg/week", "OLS slope of session Epley e1RM against weeks", epley_ids)
    count = add("e1rm_sessions", len(epley_points), "sessions", "count of sessions with a valid set", epley_ids)
    summary: dict[str, Any] = {
        "exercise_id": exercise_id,
        "as_of": end.isoformat() if end else None,
        "e1rm_trend": trend,
        "e1rm_slope": brief(slope_value),
        "flat_band_pct_per_week": e1rm_cfg["flat_pct_per_week"],
        "sessions_used": brief(count),
        "recent_sessions": recent[-SUMMARY_SESSIONS:],
    }
    if bodyweight_kg is not None:
        last = epley_points[-1]
        relative = add(
            "relative_strength", last.value / bodyweight_kg, None, "latest session Epley e1RM / bodyweight_kg", last.set_ids
        )
        summary["relative_strength"] = brief(relative)

    drift = _drift_points(working, drift_cfg)
    drift_error: ToolError | None = None
    drift_trend: Trend | None = None
    if isinstance(drift, ToolError):
        drift_error = drift
        summary["rpe_drift"] = {"not_assessed": drift.code}
    else:
        points, reference = drift
        drift_ids = [i for p in points for i in p.set_ids]
        drift_slope = ols_slope_per_week([(p.day, p.value) for p in points])
        drift_trend = _trend(drift_slope, float(drift_cfg["flat_per_week"]))
        tolerance = 100 * float(drift_cfg["load_tolerance"])
        dv = add(
            "rpe_drift_slope",
            drift_slope,
            "rpe/week",
            f"OLS slope of session mean RPE at {reference:g} kg +-{tolerance:g}% against weeks",
            drift_ids,
        )
        rv = add("drift_reference_load", reference, "kg", "most frequent weight among sets with RPE", drift_ids)
        nv = add("drift_sessions", len(points), "sessions", "count of sessions with a comparable set", drift_ids)
        summary["rpe_drift"] = {
            "trend": drift_trend,
            "slope": brief(dv),
            "reference_load": brief(rv),
            "sessions": brief(nv),
            "flat_band_per_week": drift_cfg["flat_per_week"],
        }
    summary["excluded_sets"] = {k: n for k, n in excluded.items() if n}

    return E1rmResult(
        tool_version=TOOL_VERSION,
        values=values,
        summary=summary,
        exercise_id=exercise_id,
        sessions=sessions,
        sessions_used=len(epley_points),
        trend=trend,
        drift_trend=drift_trend,
        drift_error=drift_error,
        excluded=excluded,
    )
