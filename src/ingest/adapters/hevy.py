"""Hevy adapter: community-format source parser plus conversion to canonical sets (D6, format unverified)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from types import MappingProxyType
from typing import Literal

from src.ingest.adapters.base import BaseAdapter, SourceProbe
from src.ingest.errors import IngestError
from src.ingest.model import CanonicalSet, CanonicalSets, IngestFlag

from ._canonical import KM_PER_MILE, build_set
from ._csv_source import header_fields, integer, number, read_csv

HEVY_HEADERS = (
    "title", "start_time", "end_time", "description", "exercise_title", "superset_id",
    "exercise_notes", "set_index", "set_type", "weight_kg", "reps", "distance_km", "duration_seconds", "rpe",
)
_MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}
_SET_TYPES = {"normal": "normal", "warmup": "warmup", "dropset": "drop", "failure": "failure"}


class HevyParseError(ValueError):
    """Hevy parsing failure; the adapter reports it as ``IngestError``."""


def parse_timestamp(value: str) -> datetime:
    match = re.fullmatch(r'([0-9]{1,2}) ([A-Z][a-z]{2}) ([0-9]{4}), ([0-9]{2}):([0-9]{2})', value)
    if match is None:
        raise HevyParseError("timestamps must use D MMM YYYY, HH:mm with English month abbreviations")
    day, month, year, hour, minute = match.groups()
    try:
        return datetime(int(year), _MONTHS[month], int(day), int(hour), int(minute))
    except (ValueError, KeyError) as exc:
        raise HevyParseError("invalid calendar timestamp or unsupported month abbreviation") from exc


@dataclass(frozen=True)
class _HevyRow:
    """Private source values and candidate mappings; weights remain unconverted."""

    row_number: int
    started_at: datetime
    ended_at: datetime
    workout_name: str
    workout_duration_seconds: int
    exercise_name: str
    set_index: int
    source_set_type: str
    mapped_set_type: str
    weight: float | None
    source_unit: Literal["kg", "lb"]
    weight_column: str
    reps: int | None
    rpe: float | None
    distance: float | None
    distance_column: str
    duration_seconds: float | None
    exercise_notes: str
    workout_notes: str
    superset_id: str | None
    raw: Mapping[str, str]

    @property
    def taken_to_failure(self) -> bool:
        """Set type ``failure``: the reps were completed and the set ended at failure. Not a failed set (spec §1.1)."""
        return self.source_set_type == "failure"

    @property
    def failed(self) -> bool:
        return self.reps == 0


class HevyParser:
    """Detection and parsing of the source file."""

    @staticmethod
    def detect(header: Sequence[str] | str) -> bool:
        fields = header_fields(header)
        if fields is None:
            return False
        fixed = set(HEVY_HEADERS) - {"weight_kg", "distance_km"}
        return any(set(fields) == fixed | {weight, distance}
                   for weight in ("weight_kg", "weight_lbs") for distance in ("distance_km", "distance_miles"))

    def parse_source(self, source: str | Path) -> tuple[_HevyRow, ...]:
        header, records = read_csv(source, self.detect, HevyParseError)
        weight_column = "weight_kg" if "weight_kg" in header else "weight_lbs"
        distance_column = "distance_km" if "distance_km" in header else "distance_miles"
        source_unit: Literal["kg", "lb"] = "kg" if weight_column == "weight_kg" else "lb"
        parsed: list[_HevyRow] = []
        for index, row in records:
            try:
                start = parse_timestamp(row["start_time"])
                end = parse_timestamp(row["end_time"])
            except HevyParseError as exc:
                raise HevyParseError(f"data row {index}: {exc}") from exc
            if end < start:
                raise HevyParseError(f"data row {index}: end_time precedes start_time")
            if not row["exercise_title"].strip():
                raise HevyParseError(f"data row {index}: exercise_title is missing")
            source_type = row["set_type"]
            if source_type not in _SET_TYPES:
                raise HevyParseError(f"data row {index}: unsupported set_type")
            set_index = integer(row["set_index"], "set_index", index, HevyParseError, required=True, minimum=0)
            assert set_index is not None  # A required integer has already been validated.
            parsed.append(_HevyRow(
                row_number=index, started_at=start, ended_at=end, workout_name=row["title"],
                workout_duration_seconds=int((end - start).total_seconds()), exercise_name=row["exercise_title"],
                set_index=set_index,
                source_set_type=source_type, mapped_set_type=_SET_TYPES[source_type],
                weight=number(row[weight_column], weight_column, index, HevyParseError), source_unit=source_unit,
                weight_column=weight_column, reps=integer(row["reps"], "reps", index, HevyParseError),
                rpe=number(row["rpe"], "rpe", index, HevyParseError),
                distance=number(row[distance_column], distance_column, index, HevyParseError),
                distance_column=distance_column,
                duration_seconds=number(row["duration_seconds"], "duration_seconds", index, HevyParseError),
                exercise_notes=row["exercise_notes"], workout_notes=row["description"],
                superset_id=row["superset_id"] if row["superset_id"] != "" else None, raw=MappingProxyType(dict(row)),
            ))
        return tuple(parsed)


class HevyAdapter(BaseAdapter):
    """Hevy CSV export; the unit comes from the column names."""

    name = "hevy"

    def detect(self, probe: SourceProbe) -> bool:
        """True for the documented header sets only."""
        return probe.header is not None and HevyParser.detect(probe.header)

    def to_canonical(self, source: Path) -> CanonicalSets:
        """Parse and convert. Distances become kilometres."""
        try:
            rows = HevyParser().parse_source(source)
        except HevyParseError as exc:
            raise IngestError(f"hevy: {exc}") from exc
        sets: list[CanonicalSet] = []
        flags: list[IngestFlag] = []
        for r in rows:
            miles = r.distance_column == "distance_miles" and r.distance is not None
            canonical, flag = build_set(
                app=self.name, row_number=r.row_number, workout_ts=r.started_at, workout_name=r.workout_name,
                exercise=r.exercise_name, set_index=r.set_index, set_type=r.mapped_set_type, weight=r.weight,
                unit=r.source_unit, reps=r.reps, rpe=r.rpe,
                distance_km=r.distance * KM_PER_MILE if miles else r.distance,  # type: ignore[operator]
                duration_s=r.duration_seconds, set_note=r.exercise_notes, workout_note=r.workout_notes,
                superset_id=r.superset_id,
            )  # fmt: skip
            sets.append(canonical)
            flags.extend([flag] if flag else [])
        return CanonicalSets(sets=tuple(sets), flags=tuple(flags))
