"""Tool: ``uncoupled_load_analyzer`` (issue F7, plan §5.7).

Acute load = the last 7 days. Chronic load = the 28 days before the acute window (the acute window is not inside it),
expressed as an average weekly load. The ratio is acute / chronic and is always labeled ``"heuristic"``: it describes
load change only. It is not a predictor of anything else, and this tool never produces wording about injury.

Pure and deterministic: no clock, no randomness, no network. ``as_of`` defaults to the date of the last valid set.

Window semantics (``days_before = (as_of - set_date).days``; provisional until ``docs/indicator-spec.md``, D3):
- acute:   0 <= days_before < 7        (as_of and the 6 days before it)
- chronic: 7 <= days_before < 7 + 28   (days 7 .. 34); a set at day 35 or later is ignored
- chronic_weekly = chronic_total / (28 / 7)
- history required: first valid set at days_before >= 34 (the log covers the whole chronic window)

Set validity: warm-ups excluded; failed sets (``failed`` or reps == 0) excluded; sets without weight or with weight 0
(bodyweight) contribute nothing and are counted in ``excluded``.
Metrics: ``tonnage`` = sum(weight_kg * reps). ``rpe_weighted`` = sum(weight_kg * reps * rpe / 10), over sets with RPE
only; sets without RPE are excluded and counted (weighting provisional, D3).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol

from src.tools._common_provisional import (  # replace with src.tools.common when D3 (#5) merges
    Provenance,
    ToolError,
    ToolResult,
    Value,
    ValueIdFactory,
    config_hash,
)

TOOL_VERSION = "uncoupled_load_analyzer-0.1.0"
Metric = Literal["tonnage", "rpe_weighted"]

DEFAULT_CONFIG: dict[str, Any] = {
    "acute_days": 7,
    "chronic_days": 28,
    "rpe_weight_divisor": 10.0,
    "summary_decimals": 2,
}
"""Provisional thresholds; move to ``configs/indicators.yaml`` keys once D3 defines them."""


class SetRow(Protocol):
    """The fields of a canonical set (D4 ``CanonicalSet``) that this tool reads."""

    set_id: str
    workout_ts: datetime
    weight_kg: float | None
    reps: int | None
    rpe: float | None
    set_type: str
    failed: bool


class SetSource(Protocol):
    """Anything that returns the stored sets of a log (the D4 store, or a fake in tests)."""

    def get_sets(self, log_id: str) -> Iterable[SetRow]: ...


class LoadResult(ToolResult):
    """Acute, chronic (weekly average) and ratio values plus a compact summary."""


@dataclass
class _Window:
    total: float
    set_ids: list[str]


def _exclusion_reason(s: SetRow, metric: Metric) -> str | None:
    if s.set_type == "warmup":
        return "warmup"
    if s.failed or not s.reps:
        return "failed"
    if not s.weight_kg:
        return "no_weight"
    if metric == "rpe_weighted" and s.rpe is None:
        return "no_rpe"
    return None


def _set_load(s: SetRow, metric: Metric, divisor: float) -> float:
    base = float(s.weight_kg) * int(s.reps)  # type: ignore[arg-type]
    return base * float(s.rpe) / divisor if metric == "rpe_weighted" else base  # type: ignore[arg-type]


def compute_uncoupled_load(
    sets: Iterable[SetRow],
    metric: Metric = "tonnage",
    as_of: date | None = None,
    config: Mapping[str, Any] | None = None,
    ids: ValueIdFactory | None = None,
) -> LoadResult | ToolError:
    """Compute acute load, chronic weekly load and their heuristic ratio from canonical sets."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    if metric not in ("tonnage", "rpe_weighted"):
        return ToolError(code="invalid_metric", message=f"metric must be 'tonnage' or 'rpe_weighted', got {metric!r}")
    ids = ids or ValueIdFactory()
    acute_days, chronic_days = int(cfg["acute_days"]), int(cfg["chronic_days"])
    horizon = acute_days + chronic_days

    excluded: dict[str, int] = {}
    valid: list[SetRow] = []
    for s in sets:
        reason = _exclusion_reason(s, metric)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
        else:
            valid.append(s)
    if not valid:
        return ToolError(code="no_valid_sets", message=f"no valid sets for metric {metric!r}; excluded: {excluded}")

    as_of = as_of or max(s.workout_ts.date() for s in valid)
    first = min(s.workout_ts.date() for s in valid)
    span_days = (as_of - first).days
    if span_days < horizon - 1:
        return ToolError(
            code="insufficient_history",
            message=(
                f"history covers {span_days + 1} days up to {as_of.isoformat()}; "
                f"{horizon} days are needed ({acute_days} acute + {chronic_days} chronic)"
            ),
        )

    acute = _Window(0.0, [])
    chronic = _Window(0.0, [])
    future = 0
    for s in sorted(valid, key=lambda r: (r.workout_ts, r.set_id)):
        days_before = (as_of - s.workout_ts.date()).days
        if days_before < 0:
            future += 1
            continue
        if days_before < acute_days:
            window = acute
        elif days_before < horizon:
            window = chronic
        else:
            continue
        window.total += _set_load(s, metric, float(cfg["rpe_weight_divisor"]))
        window.set_ids.append(s.set_id)
    if future:
        excluded["after_as_of"] = future

    weeks = chronic_days / 7
    chronic_weekly = chronic.total / weeks
    chash = config_hash({**cfg, "metric": metric, "as_of": as_of.isoformat()})
    unit = "kg" if metric == "tonnage" else "kg_rpe_weighted"
    per_set = "weight_kg*reps" if metric == "tonnage" else f"weight_kg*reps*rpe/{cfg['rpe_weight_divisor']:g}"

    def prov(formula: str, row_ids: list[str]) -> Provenance:
        return Provenance(formula=formula, input_row_ids=row_ids, tool_version=TOOL_VERSION, config_hash=chash)

    values = [
        Value(
            value_id=ids.new("acute_load"),
            name="acute_load",
            value=acute.total,
            unit=unit,
            provenance=prov(
                f"sum({per_set}) over valid sets with 0 <= days_before(as_of) < {acute_days}", acute.set_ids
            ),
        ),
        Value(
            value_id=ids.new("chronic_load_weekly"),
            name="chronic_load_weekly",
            value=chronic_weekly,
            unit=f"{unit}/week",
            provenance=prov(
                f"sum({per_set}) over valid sets with {acute_days} <= days_before(as_of) < {horizon}, / {weeks:g}",
                chronic.set_ids,
            ),
        ),
    ]
    flags: list[str] = []
    ratio: float | None = None
    if chronic_weekly == 0:
        flags.append("chronic_zero_ratio_undefined")
    else:
        ratio = acute.total / chronic_weekly
        values.append(
            Value(
                value_id=ids.new("acute_chronic_ratio"),
                name="acute_chronic_ratio",
                value=ratio,
                unit=None,
                provenance=prov(
                    "acute_load / chronic_load_weekly (uncoupled, heuristic)", acute.set_ids + chronic.set_ids
                ),
            )
        )
    if excluded.get("no_rpe"):
        flags.append("rpe_missing_on_some_sets")

    d = int(cfg["summary_decimals"])
    summary = {
        "metric": metric,
        "as_of": as_of.isoformat(),
        "acute_window_days": acute_days,
        "chronic_window_days": chronic_days,
        "acute_load": {"value_id": values[0].value_id, "value": round(acute.total, d), "unit": unit},
        "chronic_load_weekly": {
            "value_id": values[1].value_id,
            "value": round(chronic_weekly, d),
            "unit": f"{unit}/week",
        },
        "ratio": None
        if ratio is None
        else {"value_id": values[2].value_id, "value": round(ratio, d), "label": "heuristic"},
        "label": "heuristic",
        "n_sets": {"acute": len(acute.set_ids), "chronic": len(chronic.set_ids)},
        "excluded": dict(sorted(excluded.items())),
        "flags": flags,
    }
    return LoadResult(tool_version=TOOL_VERSION, values=values, summary=summary)


def uncoupled_load_analyzer(
    store: SetSource,
    log_id: str,
    metric: Metric = "tonnage",
    as_of: date | None = None,
    config: Mapping[str, Any] | None = None,
    ids: ValueIdFactory | None = None,
) -> LoadResult | ToolError:
    """Tool entry point: read the log's stored sets and compute the uncoupled acute/chronic load.

    Returns ``LoadResult`` (acute, chronic weekly and ratio as separate ``Value``s with provenance) or a structured
    ``ToolError``: ``insufficient_history``, ``no_valid_sets`` or ``invalid_metric``. When the chronic load is zero,
    the ratio is undefined: it is omitted and flagged ``chronic_zero_ratio_undefined``.
    """
    return compute_uncoupled_load(store.get_sets(log_id), metric=metric, as_of=as_of, config=config, ids=ids)
