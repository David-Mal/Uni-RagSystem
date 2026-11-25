"""Normalization rules shared by all adapters (plan §2.2): units, dates, failed sets, plausibility flags."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml

from src.ingest.errors import IngestError
from src.ingest.model import CanonicalSet, IngestFlag, SetType

KG_PER_LB = 0.45359237
"""Exact definition of the international pound."""

INGEST_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "ingest.yaml"

_UNITS: dict[str, Literal["kg", "lb"]] = {"kg": "kg", "lb": "lb", "lbs": "lb"}


def parse_unit(value: str) -> Literal["kg", "lb"]:
    """Return the canonical unit; fail on anything that is not kg, lb or lbs."""
    unit = _UNITS.get(value.strip().lower())
    if unit is None:
        raise IngestError(f"unknown weight unit {value!r}")
    return unit


def to_kg(value: float | None, unit: Literal["kg", "lb"]) -> float | None:
    """Convert a weight to kilograms without rounding."""
    if value is None:
        return None
    return value * KG_PER_LB if unit == "lb" else value


def parse_local_timestamp(value: str, fmt: str) -> datetime:
    """Parse a timestamp with one explicit format; no timezone conversion and no guessing.

    The value must round-trip through the format, so partial spellings such as ``2026-1-5`` are rejected.
    """
    try:
        parsed = datetime.strptime(value, fmt)
    except ValueError as exc:
        raise IngestError(f"cannot parse date {value!r} (expected format {fmt})") from exc
    if parsed.strftime(fmt) != value:
        raise IngestError(f"ambiguous date {value!r} (expected format {fmt})")
    return parsed


def parse_set_type(value: str, mapping: Mapping[str, SetType]) -> SetType:
    """Map an app's set type with the adapter's explicit table; unknown spellings fail loudly."""
    try:
        return mapping[value]
    except KeyError:
        raise IngestError(f"unknown set type {value!r}") from None


def is_failed(reps: int | None, flagged: bool = False) -> bool:
    """A set is failed if it has 0 reps or the app marks it as failed (not: taken to failure)."""
    return reps == 0 or flagged


def clean_rpe(value: float | None, where: str) -> tuple[float | None, IngestFlag | None]:
    """Return a usable RPE. A value outside 0-10 becomes missing and is flagged, never clamped."""
    if value is None or 0 <= value <= 10:
        return value, None
    return None, IngestFlag(code="implausible_rpe", detail=f"{where}: RPE {value:g} ignored")


def unit_mix_flags(sets: Iterable[CanonicalSet]) -> list[IngestFlag]:
    """One flag per exercise whose loaded sets use both kg and lb."""
    units: dict[str, set[str]] = {}
    for s in sets:
        if s.weight_kg:
            units.setdefault(s.exercise_name_raw, set()).add(s.source_unit)
    return [
        IngestFlag(code="unit_mix", detail=f"{name}: sets logged in both kg and lb")
        for name in sorted(units)
        if len(units[name]) > 1
    ]


def implausible_weight_flags(sets: Iterable[CanonicalSet], limit_kg: float | None = None) -> list[IngestFlag]:
    """One flag per set heavier than the configured limit. The set is kept."""
    limit = limit_kg if limit_kg is not None else _max_weight()
    return [
        IngestFlag(
            code="implausible_weight",
            detail=f"{s.exercise_name_raw} on {s.workout_ts:%Y-%m-%d}, set {s.set_index}: {s.weight_kg:g} kg",
        )
        for s in sets
        if s.weight_kg is not None and s.weight_kg > limit
    ]


def _max_weight() -> float:
    with INGEST_CONFIG_PATH.open(encoding="utf-8") as stream:
        return float(yaml.safe_load(stream)["max_plausible_weight_kg"])
