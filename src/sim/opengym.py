"""Deterministic D2 CSV output; source metadata stays separate from D4 models.

Only the two documented column layouts and D5's known set types are emitted.
Optional fields remain empty unless supplied explicitly. No units, identities,
outliers, repetition counts or RPE values are repaired by this serializer.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
import csv
import io
import re
from types import MappingProxyType
from typing import Literal

from src.schemas.models import EXERCISE_ID_PATTERN, UNKNOWN_EXERCISE_ID

from .schema import nonempty
from .workouts import SimulatedLog, count, finite

COMMON_COLUMNS = (
    "date", "start_time", "end_time", "workout", "workout_note", "exercise", "exercise_id", "body_part",
    "superset_id", "set", "set_type", "side", "weight", "unit", "reps", "rpe", "rir", "distance_km", "seconds", "incline",
)
COLUMNS_21 = (*COMMON_COLUMNS, "note")
COLUMNS_26 = (*COMMON_COLUMNS, "resistance_level", "note", "set_note", "tempo", "bands", "set_color")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class ExerciseExport:
    exercise_key: str
    source_catalog_id: str
    name: str
    body_part: str
    canonical_exercise_id: str

    def __post_init__(self) -> None:
        for name in ("exercise_key", "name", "body_part", "canonical_exercise_id"):
            nonempty(getattr(self, name), name)
        if not isinstance(self.source_catalog_id, str) or not re.fullmatch(r"[0-9]{4}", self.source_catalog_id):
            raise ValueError("source_catalog_id must be explicit four-digit OpenGym text")
        if not re.fullmatch(EXERCISE_ID_PATTERN, self.canonical_exercise_id):
            raise ValueError("invalid canonical exercise ID")


@dataclass(frozen=True)
class SetExport:
    """Explicit extra source fields, keyed by stable internal set ID.

    The same extras apply to intentional copies of that set. The normal default
    represents the simulator's working sets; failure is never inferred from RPE.
    """

    set_type: Literal["normal", "warmup", "failure"] = "normal"
    distance_km: float | None = None
    seconds: float | None = None
    note: str | None = None
    set_note: str | None = None

    def __post_init__(self) -> None:
        if self.set_type not in ("normal", "warmup", "failure"):
            raise ValueError("unsupported OpenGym set_type; drop spelling is [TO VERIFY]")
        for name in ("distance_km", "seconds"):
            value = getattr(self, name)
            if value is not None:
                finite(value, name)
                if value < 0:
                    raise ValueError(f"{name} cannot be negative")
        for name in ("note", "set_note"):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be text or null")


@dataclass(frozen=True)
class OpenGymMetadata:
    workout_name: str
    duration_minutes: int
    exercises: tuple[ExerciseExport, ...]
    variant: Literal[21, 26]
    workout_note: str | None = None
    sets: Mapping[str, SetExport] = field(default_factory=dict)

    def __post_init__(self) -> None:
        nonempty(self.workout_name, "workout_name")
        count(self.duration_minutes, "duration_minutes")
        if type(self.variant) is not int or self.variant not in (21, 26):
            raise ValueError("variant must be 21 or 26")
        if not isinstance(self.exercises, tuple) or not self.exercises or not all(
            isinstance(item, ExerciseExport) for item in self.exercises
        ):
            raise ValueError("explicit exercise export mappings are required")
        for attribute in ("exercise_key", "source_catalog_id", "name"):
            values = [getattr(item, attribute) for item in self.exercises]
            if len(set(values)) != len(values):
                raise ValueError(f"duplicate export mapping {attribute}")
        if self.workout_note is not None and not isinstance(self.workout_note, str):
            raise ValueError("workout_note must be text or null")
        if not isinstance(self.sets, Mapping) or not all(
            isinstance(key, str) and key.strip() and isinstance(value, SetExport) for key, value in self.sets.items()
        ):
            raise ValueError("set metadata must map internal set IDs to SetExport")
        if self.variant == 21 and any(value.set_note is not None for value in self.sets.values()):
            raise ValueError("set_note requires the documented 26-column variant")
        object.__setattr__(self, "sets", MappingProxyType(dict(self.sets)))

    def validate_canonical_ids(self, known_ids: Collection[str]) -> None:
        if isinstance(known_ids, str):
            raise ValueError("known IDs must be a collection")
        for item in self.exercises:
            if item.canonical_exercise_id != UNKNOWN_EXERCISE_ID and item.canonical_exercise_id not in known_ids:
                raise ValueError(f"canonical exercise ID is not in D7 vocabulary: {item.canonical_exercise_id}")

    def match_exercise(self, raw_name: str) -> str | None:
        """D4 matcher contract: exact explicit bindings only, no guessed aliases."""
        return next((item.canonical_exercise_id for item in self.exercises if item.name == raw_name), None)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is not None or value.second or value.microsecond:
        raise ValueError("OpenGym requires naive timestamps with exact minute precision")
    return value.strftime(TIMESTAMP_FORMAT)


def _number(value: float | int | None) -> str:
    if value is None:
        return ""
    finite(value, "CSV number")
    # Plain decimal prevents D5's strict parser rejecting exponent notation.
    # Decimal(str(...)) preserves the simulator's numeric value without rounding.
    text = format(Decimal(str(value)), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def serialize_opengym(log: SimulatedLog, metadata: OpenGymMetadata) -> bytes:
    """Emit BOM/CRLF CSV in original stable order, including duplicate rows.

    Finite negative traps are preserved: D5 will reject them, rather than this
    layer silently changing the value. Positive outliers and RPE outside 0-10
    likewise remain intact. Opaque note references require human integration.
    """
    if not isinstance(log, SimulatedLog) or not isinstance(metadata, OpenGymMetadata):
        raise ValueError("validated simulation log and export metadata are required")
    if any(session.note_refs for session in log.sessions):
        raise ValueError("human note references are unresolved; no note text was substituted")
    by_key = {item.exercise_key: item for item in metadata.exercises}
    all_ids = {item.set_id for s in log.sessions for e in s.exercises for item in e.sets}
    if set(metadata.sets) - all_ids:
        raise ValueError("set export metadata targets an unknown set ID")
    starts = [_timestamp(session.at) for session in log.sessions]
    if len(starts) != len(set(starts)):
        raise ValueError("multiple internal sessions collide at one OpenGym workout start")
    stream = io.StringIO(newline="")
    columns = COLUMNS_21 if metadata.variant == 21 else COLUMNS_26
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for session in log.sessions:
        end = session.at + timedelta(minutes=metadata.duration_minutes)
        for exercise in session.exercises:
            if exercise.exercise_key not in by_key:
                raise ValueError(f"missing explicit export mapping: {exercise.exercise_key}")
            identity = by_key[exercise.exercise_key]
            slots = [item.slot for item in exercise.sets]
            if slots != sorted(slots) or sorted(set(slots)) != list(range(len(set(slots)))):
                raise ValueError("OpenGym requires ordered contiguous set slots; duplicates may repeat a slot")
            for item in exercise.sets:
                extra = metadata.sets.get(item.set_id, SetExport())
                row = dict.fromkeys(columns, "")
                row.update(
                    date=session.at.strftime("%Y-%m-%d"), start_time=_timestamp(session.at), end_time=_timestamp(end),
                    workout=metadata.workout_name, workout_note=metadata.workout_note or "", exercise=identity.name,
                    exercise_id=identity.source_catalog_id, body_part=identity.body_part, set=str(item.slot + 1),
                    set_type=extra.set_type, weight=_number(item.load), unit=item.unit, reps=str(item.reps),
                    rpe=_number(item.rpe), distance_km=_number(extra.distance_km), seconds=_number(extra.seconds),
                    note=extra.note or "",
                )
                if metadata.variant == 26:
                    row["set_note"] = extra.set_note or ""
                writer.writerow(row)
    return stream.getvalue().encode("utf-8-sig")
