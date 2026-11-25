"""Provisional in-memory store and tool adapters for D4/D8/F7 until those PRs merge (issue M4, #35).

Zero MCP SDK imports live here. Replace with ``src.ingest`` (D4), ``src.tools.e1rm`` (D8),
and ``src.tools.load`` (F7) once merged into ``main``.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.tools._common_provisional import (
    Provenance,
    ToolError,
    Value,
    ValueIdFactory,
    config_hash,
)
from src.tools.match_exercise import match_exercise_rag

INGEST_TOOL_VERSION = "ingest_workout_log-0.1.0-provisional"
E1RM_TOOL_VERSION = "compute_e1rm_and_drift-0.1.0-provisional"
LOAD_TOOL_VERSION = "uncoupled_load_analyzer-0.1.0-provisional"


class SessionSetStore:
    """In-memory session store implementing the D4 ``get_sets`` protocol."""

    def __init__(self) -> None:
        self._sets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._seen_ids: dict[str, set[str]] = defaultdict(set)

    def append_sets(self, log_id: str, rows: Iterable[dict[str, Any]]) -> int:
        added = 0
        for row in rows:
            sid = str(row["set_id"])
            if sid not in self._seen_ids[log_id]:
                self._seen_ids[log_id].add(sid)
                self._sets[log_id].append(dict(row))
                added += 1
        return added

    def get_sets(
        self, log_id: str, filters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return list(self._sets.get(log_id, []))


def _parse_float(raw: str | None) -> float | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


def _parse_int(raw: str | None) -> int | None:
    val = _parse_float(raw)
    return round(val) if val is not None else None


def _parse_ts(raw: str) -> datetime:
    text = raw.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(text)


def ingest_workout_log_provisional(
    store: SessionSetStore,
    path: str,
    app_hint: str | None = None,
    log_id: str | None = None,
) -> dict[str, Any]:
    """Ingest a CSV workout export (OpenGym or canonical CSV) into ``store``."""
    file_path = Path(path)
    if not file_path.exists():
        return ToolError(code="file_not_found", message=f"Workout log not found: {path}").model_dump()

    effective_log_id = log_id or hashlib.sha256(str(file_path.resolve()).encode("utf-8")).hexdigest()[:12]
    rows_to_add: list[dict[str, Any]] = []
    unmatched: set[str] = set()
    notes: list[str] = []
    workouts: set[str] = set()

    with file_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return ToolError(code="unknown_format", message="Empty or headerless CSV").model_dump()

        for idx, rec in enumerate(reader):
            norm = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in rec.items() if k}
            ts_raw = (
                norm.get("workout_ts")
                or norm.get("date")
                or norm.get("start_time")
                or norm.get("timestamp")
            )
            ex_raw = (
                norm.get("exercise_name_raw")
                or norm.get("exercise_name")
                or norm.get("exercise")
                or norm.get("name")
            )
            if not ts_raw or not ex_raw:
                continue

            ts = _parse_ts(ts_raw)
            workouts.add(ts.date().isoformat())

            weight = _parse_float(norm.get("weight_kg") or norm.get("weight"))
            unit = (norm.get("source_unit") or norm.get("unit") or "kg").lower()
            if weight is not None and unit in {"lb", "lbs"}:
                weight = round(weight * 0.45359237, 4)

            reps = _parse_int(norm.get("reps"))
            rpe = _parse_float(norm.get("rpe"))
            set_type = (norm.get("set_type") or "normal").lower()
            failed = str(norm.get("failed", "")).lower() in {"true", "1", "yes"} or reps == 0
            note = norm.get("set_note") or norm.get("notes") or norm.get("note") or ""
            if note:
                notes.append(note)

            ex_id = norm.get("exercise_id")
            if not ex_id:
                match = match_exercise_rag(ex_raw)
                ex_id = match.exercise_id
            if ex_id == "unknown":
                unmatched.add(ex_raw)

            sig = f"{ts.isoformat()}|{ex_raw}|{idx}|{weight}|{reps}|{rpe}"
            set_id = hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]
            rows_to_add.append(
                {
                    "set_id": set_id,
                    "log_id": effective_log_id,
                    "workout_ts": ts,
                    "exercise_name_raw": ex_raw,
                    "exercise_id": ex_id,
                    "set_type": set_type,
                    "weight_kg": weight,
                    "reps": reps,
                    "rpe": rpe,
                    "failed": failed,
                    "set_note": note or None,
                    "source_app": app_hint or "opengym",
                }
            )

    added = store.append_sets(effective_log_id, rows_to_add)
    return {
        "tool_version": INGEST_TOOL_VERSION,
        "log_id": effective_log_id,
        "set_count": added,
        "workout_count": len(workouts),
        "unmatched_names": sorted(unmatched),
        "notes": notes,
        "flags": [],
    }


def _ols_slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0.0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False)) / denom


def compute_e1rm_and_drift_provisional(
    store: SessionSetStore,
    log_id: str,
    exercise_id: str,
    bodyweight_kg: float | None = None,
) -> dict[str, Any]:
    """Provisional e1RM (Epley & Brzycki) and trend slope calculator until D8 merges."""
    if not exercise_id or exercise_id == "unknown":
        return ToolError(code="unknown_exercise", message="Cannot compute e1RM for unknown exercise").model_dump()

    rows = [r for r in store.get_sets(log_id) if r.get("exercise_id") == exercise_id]
    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    excluded = {"warmup": 0, "failed": 0, "reps_gt_10": 0}

    for r in rows:
        if str(r.get("set_type", "normal")).lower() in {"warmup", "warm-up", "warm_up"}:
            excluded["warmup"] += 1
            continue
        reps = r.get("reps")
        weight = r.get("weight_kg")
        if r.get("failed") or reps is None or reps <= 0 or weight is None or weight <= 0:
            excluded["failed"] += 1
            continue
        if reps > 10:
            excluded["reps_gt_10"] += 1
            continue
        ts = r["workout_ts"]
        d = ts.date() if isinstance(ts, datetime) else ts
        by_day[d].append(r)

    if len(by_day) < 4:
        return ToolError(
            code="insufficient_sessions",
            message=f"Only {len(by_day)} valid sessions for {exercise_id} (minimum 4 required).",
        ).model_dump()

    cfg_digest = config_hash({"formula": "epley_brzycki", "max_reps": 10})
    ids = ValueIdFactory()
    values: list[Value] = []
    series: list[dict[str, Any]] = []

    sorted_days = sorted(by_day.keys())
    first_day = sorted_days[0]
    xs: list[float] = []
    ys: list[float] = []

    for d in sorted_days:
        day_sets = by_day[d]
        best_epley = max(float(s["weight_kg"]) * (1.0 + int(s["reps"]) / 30.0) for s in day_sets)
        best_brzycki = max(float(s["weight_kg"]) * 36.0 / (37.0 - int(s["reps"])) for s in day_sets)
        row_ids = [str(s["set_id"]) for s in day_sets]
        vid = ids.new("e1rm")
        values.append(
            Value(
                value_id=vid,
                name=f"e1rm_{d.isoformat()}",
                value=round(best_epley, 2),
                unit="kg",
                provenance=Provenance(
                    formula="max(w * (1 + r / 30))",
                    input_row_ids=row_ids,
                    tool_version=E1RM_TOOL_VERSION,
                    config_hash=cfg_digest,
                ),
            )
        )
        xs.append((d - first_day).days / 7.0)
        ys.append(best_epley)
        series.append(
            {
                "date": d.isoformat(),
                "epley_kg": round(best_epley, 2),
                "brzycki_kg": round(best_brzycki, 2),
                "value_id": vid,
            }
        )

    slope = round(_ols_slope(xs, ys), 3)
    slope_vid = ids.new("e1rm_slope")
    values.append(
        Value(
            value_id=slope_vid,
            name="e1rm_slope_kg_per_week",
            value=slope,
            unit="kg/week",
            provenance=Provenance(
                formula="OLS(epley_e1rm ~ weeks)",
                input_row_ids=[str(r["set_id"]) for d in sorted_days for r in by_day[d]],
                tool_version=E1RM_TOOL_VERSION,
                config_hash=cfg_digest,
            ),
        )
    )
    direction = "up" if slope > 0.25 else ("down" if slope < -0.25 else "flat")

    summary: dict[str, Any] = {
        "exercise_id": exercise_id,
        "sessions_used": len(sorted_days),
        "trend_direction": direction,
        "slope_kg_per_week": slope,
        "slope_value_id": slope_vid,
        "recent_sessions": series[-6:],
    }
    if bodyweight_kg and bodyweight_kg > 0:
        summary["relative_strength"] = round(ys[-1] / bodyweight_kg, 2)

    return {
        "tool_version": E1RM_TOOL_VERSION,
        "values": [v.model_dump() for v in values],
        "summary": summary,
        "excluded_counts": excluded,
    }


def uncoupled_load_analyzer_provisional(
    store: SessionSetStore,
    log_id: str,
    metric: str = "tonnage",
) -> dict[str, Any]:
    """Provisional uncoupled 7d acute / 28d chronic load ratio until F7 merges."""
    rows = [
        r
        for r in store.get_sets(log_id)
        if str(r.get("set_type", "normal")).lower() not in {"warmup", "warm-up", "warm_up"}
        and not r.get("failed")
        and (r.get("weight_kg") or 0) > 0
        and (r.get("reps") or 0) > 0
    ]
    if not rows:
        return ToolError(code="no_data", message="No valid working sets for load analysis").model_dump()

    dates = [r["workout_ts"].date() if isinstance(r["workout_ts"], datetime) else r["workout_ts"] for r in rows]
    as_of = max(dates)
    if (as_of - min(dates)).days < 34:
        return ToolError(
            code="insufficient_history",
            message="Need at least 35 days of history for uncoupled acute/chronic load.",
        ).model_dump()

    def _set_load(r: dict[str, Any]) -> float:
        base = float(r["weight_kg"]) * int(r["reps"])
        if metric == "rpe_weighted":
            rpe = r.get("rpe")
            return base * (float(rpe) / 10.0) if rpe is not None else 0.0
        return base

    acute = sum(_set_load(r) for r, d in zip(rows, dates, strict=False) if 0 <= (as_of - d).days < 7)
    chronic_total = sum(_set_load(r) for r, d in zip(rows, dates, strict=False) if 7 <= (as_of - d).days < 35)
    chronic_weekly = chronic_total / 4.0
    ratio = round(acute / chronic_weekly, 2) if chronic_weekly > 0 else None

    ids = ValueIdFactory()
    cfg_digest = config_hash({"acute_days": 7, "chronic_days": 28, "metric": metric})
    all_ids = [str(r["set_id"]) for r in rows]
    values = [
        Value(
            value_id=ids.new("acute_load"),
            name="acute_load",
            value=round(acute, 2),
            unit="kg",
            provenance=Provenance(formula="sum(load, 0<=days<7)", input_row_ids=all_ids, tool_version=LOAD_TOOL_VERSION, config_hash=cfg_digest),
        ),
        Value(
            value_id=ids.new("chronic_load"),
            name="chronic_weekly_load",
            value=round(chronic_weekly, 2),
            unit="kg/week",
            provenance=Provenance(formula="sum(load, 7<=days<35)/4", input_row_ids=all_ids, tool_version=LOAD_TOOL_VERSION, config_hash=cfg_digest),
        ),
    ]
    if ratio is not None:
        values.append(
            Value(
                value_id=ids.new("load_ratio"),
                name="uncoupled_load_ratio",
                value=ratio,
                unit="heuristic_ratio",
                provenance=Provenance(formula="acute/chronic_weekly (heuristic)", input_row_ids=all_ids, tool_version=LOAD_TOOL_VERSION, config_hash=cfg_digest),
            )
        )
    return {
        "tool_version": LOAD_TOOL_VERSION,
        "values": [v.model_dump() for v in values],
        "summary": {
            "acute_load": round(acute, 2),
            "chronic_weekly_load": round(chronic_weekly, 2),
            "ratio": ratio,
            "ratio_label": "heuristic",
        },
    }
