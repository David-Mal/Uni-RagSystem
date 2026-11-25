"""Shared step of the Strong and Hevy adapters: one parsed source row -> one canonical set."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from src.ingest.errors import IngestError
from src.ingest.model import CanonicalSet, IngestFlag, SetType
from src.ingest.normalize import clean_rpe, is_failed, to_kg

KM_PER_MILE = 1.609344


def build_set(
    *,
    app: str,
    row_number: int,
    workout_ts: datetime,
    workout_name: str,
    exercise: str,
    set_index: int,
    set_type: str,
    weight: float | None,
    unit: Literal["kg", "lb"],
    reps: int | None,
    rpe: float | None,
    distance_km: float | None,
    duration_s: float | None,
    set_note: str,
    workout_note: str,
    superset_id: str | None,
) -> tuple[CanonicalSet, IngestFlag | None]:
    """Normalize one row. Negative numbers are an error; an RPE outside 0-10 is flagged and ignored."""
    for name, value in (("weight", weight), ("reps", reps), ("distance", distance_km), ("duration", duration_s)):
        if value is not None and value < 0:
            raise IngestError(f"data row {row_number}: {name} must not be negative")
    clean, flag = clean_rpe(rpe, f"data row {row_number}")
    canonical = CanonicalSet.build(
        workout_ts=workout_ts,
        workout_name=workout_name.strip(),
        exercise_name_raw=exercise.strip(),
        set_index=set_index,
        set_type=SetType(set_type),
        weight_kg=to_kg(weight, unit),
        source_unit=unit,
        reps=reps,
        rpe=clean,
        failed=is_failed(reps),
        distance=distance_km,
        duration_s=duration_s,
        set_note=set_note.strip() or None,
        workout_note=workout_note.strip() or None,
        superset_id=superset_id,
        source_app=app,
    )
    return canonical, flag
