"""Functional community-format Strong source parser, not a D4 BaseAdapter."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import re
from types import MappingProxyType
from typing import Literal

from ._csv_source import header_fields, integer, number, read_csv

LOGGER = logging.getLogger(__name__)
STRONG_HEADERS = (
    "Date", "Workout Name", "Duration", "Exercise Name", "Set Order", "Weight",
    "Reps", "Distance", "Seconds", "Notes", "Workout Notes", "RPE",
)


class StrongParseError(ValueError):
    """Local Strong parsing failure; not the missing shared D4 IngestError."""


def parse_timestamp(value: str) -> datetime:
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}', value):
        raise StrongParseError("Date must use YYYY-MM-DD HH:MM:SS")
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except ValueError as exc:
        raise StrongParseError("Date is not a valid calendar timestamp") from exc


def parse_workout_duration(value: str) -> int | None:
    """Parse documented elapsed tokens, without guessing clock-time variants."""
    if value == '':
        return None
    match = re.fullmatch(r'(?:(\d+)h(?: (\d+)m)?|(\d+)m)', value, flags=re.ASCII)
    if match is None:
        raise StrongParseError("Duration must be elapsed tokens such as 45m, 3h or 1h 20m")
    try:
        hours, minutes, minutes_only = (int(item or 0) for item in match.groups())
    except ValueError as exc:
        raise StrongParseError("Duration cannot be represented as elapsed minutes") from exc
    return hours * 3600 + (minutes + minutes_only) * 60


@dataclass(frozen=True)
class _StrongRow:
    """Private source values: no canonical IDs, kg normalization or persistence."""

    row_number: int
    workout_at: datetime
    workout_name: str
    workout_duration_seconds: int | None
    exercise_name: str
    set_order: int
    weight: float | None
    source_unit: Literal["kg", "lb"]
    reps: int | None
    rpe: float | None
    distance: float | None
    duration_seconds: float | None
    notes: str
    workout_notes: str
    raw: Mapping[str, str]

    @property
    def mapped_set_type(self) -> str:
        return "normal"

    @property
    def source_failure_flag(self) -> bool:
        return False  # Strong's unverified set encoding is never guessed.

    @property
    def failed(self) -> bool:
        return self.reps == 0


class StrongParser:
    """Expose detection and parsing now; real D4 conversion/registration later."""

    @staticmethod
    def detect(header: Sequence[str] | str) -> bool:
        fields = header_fields(header)
        if fields is None:
            return False
        baseline = set(STRONG_HEADERS)
        return set(fields) in (baseline, baseline - {"Weight"} | {"Weight (kg)"})

    def parse_source(
        self, source: str | Path, *, unit_hint: Literal["kg", "lb"] | None = None,
    ) -> tuple[_StrongRow, ...]:
        if unit_hint not in (None, "kg", "lb"):
            raise StrongParseError("unit_hint must be kg or lb")
        header, records = read_csv(source, self.detect, StrongParseError)
        source_unit: Literal["kg", "lb"]
        if "Weight (kg)" in header:
            if unit_hint not in (None, "kg"):
                raise StrongParseError("unit_hint conflicts with the explicit Weight (kg) header")
            weight_column, source_unit = "Weight (kg)", "kg"
        else:
            if unit_hint is None:
                raise StrongParseError("Weight has no declared unit; supply unit_hint='kg' or 'lb'")
            weight_column, source_unit = "Weight", unit_hint
        parsed: list[_StrongRow] = []
        for index, row in records:
            try:
                at = parse_timestamp(row["Date"])
                elapsed = parse_workout_duration(row["Duration"])
            except StrongParseError as exc:
                raise StrongParseError(f"data row {index}: {exc}") from exc
            if not row["Exercise Name"].strip():
                raise StrongParseError(f"data row {index}: Exercise Name is missing")
            set_order = integer(row["Set Order"], "Set Order", index, StrongParseError, required=True, minimum=1)
            assert set_order is not None  # A required integer has already been validated.
            parsed.append(_StrongRow(
                row_number=index, workout_at=at, workout_name=row["Workout Name"],
                workout_duration_seconds=elapsed, exercise_name=row["Exercise Name"],
                set_order=set_order,
                weight=number(row[weight_column], weight_column, index, StrongParseError), source_unit=source_unit,
                reps=integer(row["Reps"], "Reps", index, StrongParseError),
                rpe=number(row["RPE"], "RPE", index, StrongParseError),
                distance=number(row["Distance"], "Distance", index, StrongParseError),
                duration_seconds=number(row["Seconds"], "Seconds", index, StrongParseError),
                notes=row["Notes"], workout_notes=row["Workout Notes"], raw=MappingProxyType(dict(row)),
            ))
        LOGGER.warning("Strong source set types are unverified; treating all parsed sets as normal.")
        return tuple(parsed)
