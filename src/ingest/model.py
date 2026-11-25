"""Canonical models every adapter converts to (issue D4, plan §2.2)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SetType(StrEnum):
    """Set type. ``failure`` = taken to failure with the reps completed; it does not mean a failed set."""

    WARMUP = "warmup"
    NORMAL = "normal"
    FAILURE = "failure"
    DROP = "drop"


def compute_set_id(
    workout_ts: datetime,
    exercise_name: str,
    set_index: int,
    weight_kg: float | None,
    reps: int | None,
    rpe: float | None,
) -> str:
    """Content hash of a set row (plan §2.2). The log id is not part of it."""
    payload = [
        workout_ts.isoformat(),
        exercise_name,
        set_index,
        None if weight_kg is None else round(weight_kg, 6),
        reps,
        None if rpe is None else round(rpe, 6),
    ]
    # float() so that 100 and 100.0 hash the same
    payload[3] = None if payload[3] is None else float(payload[3])
    payload[5] = None if payload[5] is None else float(payload[5])
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonicalSet(_Frozen):
    """One logged set in kilograms and naive local time."""

    set_id: str
    log_id: str = ""
    workout_ts: datetime
    workout_name: str = ""
    exercise_name_raw: str = Field(min_length=1)
    exercise_id: str | None = None
    set_index: int = Field(ge=0)
    set_type: SetType = SetType.NORMAL
    weight_kg: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source_unit: Literal["kg", "lb"]
    reps: int | None = Field(default=None, ge=0)
    rpe: float | None = Field(default=None, ge=0, le=10, allow_inf_nan=False)
    failed: bool = False
    distance: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    duration_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    set_note: str | None = None
    workout_note: str | None = None
    superset_id: str | None = None
    source_app: str

    @field_validator("workout_ts")
    @classmethod
    def _naive(cls, value: datetime) -> datetime:
        if value.tzinfo is not None:
            raise ValueError("workout_ts must be naive local time")
        return value

    @classmethod
    def build(cls, **fields: Any) -> CanonicalSet:
        """Create a set and fill in its content hash. Adapters use this instead of the constructor."""
        keys = ("set_index", "weight_kg", "reps", "rpe")
        set_id = compute_set_id(
            fields["workout_ts"], fields["exercise_name_raw"], *(fields.get(k) for k in keys)  # type: ignore[arg-type]
        )
        return cls(set_id=set_id, **fields)


class IngestFlag(_Frozen):
    """A data-quality finding that does not stop ingestion."""

    code: str
    detail: str


class CanonicalSets(_Frozen):
    """Adapter output: sets in file order, plus the flags the adapter raised."""

    sets: tuple[CanonicalSet, ...]
    flags: tuple[IngestFlag, ...] = ()

    def __len__(self) -> int:
        return len(self.sets)

    def __iter__(self) -> Iterator[CanonicalSet]:  # type: ignore[override]
        return iter(self.sets)

    def to_dataframe(self) -> pd.DataFrame:
        """One row per set, columns in field order (also when empty)."""
        return pd.DataFrame(
            [s.model_dump(mode="python") | {"set_type": s.set_type.value} for s in self.sets],
            columns=list(CanonicalSet.model_fields),
        )


class Note(_Frozen):
    """One distinct free-text note, with the exercise or workout it belongs to.

    ``scope='exercise'`` notes come from a set or exercise note column; ``scope='workout'`` notes belong to the whole
    workout and carry no exercise.
    """

    note_id: str
    log_id: str
    scope: Literal["exercise", "workout"]
    workout_ts: datetime
    workout_name: str = ""
    exercise_name_raw: str | None = None
    exercise_id: str | None = None
    text: str = Field(min_length=1)
