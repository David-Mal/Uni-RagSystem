"""OpenGym CSV adapter, written from two real exports and ``docs/opengym-export-format.md`` (issue D5).

Columns are read by header name, because the two exports have different column sets. Values that no real export shows
(pounds, RPE, notes, supersets, timed sets) are parsed strictly and fail loudly on a surprise; nothing is guessed.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from src.ingest.adapters.base import BaseAdapter, SourceProbe
from src.ingest.errors import IngestError
from src.ingest.model import CanonicalSet, CanonicalSets, IngestFlag, SetType
from src.ingest.normalize import clean_rpe, is_failed, parse_local_timestamp, parse_set_type, parse_unit, to_kg

REQUIRED_COLUMNS = frozenset(
    {
        "date", "start_time", "end_time", "workout", "workout_note", "exercise", "exercise_id", "body_part",
        "superset_id", "set", "set_type", "side", "weight", "unit", "reps", "rpe", "rir", "distance_km", "seconds",
        "incline", "note",
    }
)  # fmt: skip
"""Columns present in both real exports."""

OPTIONAL_COLUMNS = frozenset({"resistance_level", "set_note", "tempo", "bands", "set_color"})
"""Columns present in one of the two exports."""

SET_TYPES = {"normal": SetType.NORMAL, "warmup": SetType.WARMUP, "failure": SetType.FAILURE}
"""Spellings seen in real exports. ``failure`` = taken to failure with the reps completed, not a failed set."""

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
_NUMBER = re.compile(r"\d+(\.\d+)?", re.ASCII)
_INTEGER = re.compile(r"\d+", re.ASCII)


class OpenGymAdapter(BaseAdapter):
    """Reads OpenGym CSV exports (UTF-8 with or without BOM, one row per set)."""

    name = "opengym"

    def detect(self, probe: SourceProbe) -> bool:
        """True only if every required column is there, nothing unknown is, and no column repeats."""
        if probe.header is None:
            return False
        columns = set(probe.header)
        return (
            len(columns) == len(probe.header)
            and columns >= REQUIRED_COLUMNS
            and columns <= REQUIRED_COLUMNS | OPTIONAL_COLUMNS
        )

    def to_canonical(self, source: Path) -> CanonicalSets:
        """Convert every row to one canonical set, in file order."""
        sets: list[CanonicalSet] = []
        flags: list[IngestFlag] = []
        with source.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            for row in reader:
                where = f"line {reader.line_num}"
                if None in row or None in row.values():
                    raise IngestError(f"{where}: wrong number of columns")
                try:
                    parsed, flag = self._row(row, where)
                except IngestError as exc:
                    raise IngestError(f"{where}: {exc}") from exc
                sets.append(parsed)
                if flag is not None:
                    flags.append(flag)
        return CanonicalSets(sets=tuple(sets), flags=tuple(flags))

    def _row(self, row: dict[str, str], where: str) -> tuple[CanonicalSet, IngestFlag | None]:
        start = parse_local_timestamp(row["start_time"], TIMESTAMP_FORMAT)
        if start.strftime("%Y-%m-%d") != row["date"]:
            raise IngestError(f"date {row['date']!r} does not match start_time {row['start_time']!r}")
        exercise = row["exercise"].strip()
        if not exercise:
            raise IngestError("exercise name is missing")
        unit = parse_unit(row["unit"])
        reps = _integer(row["reps"], "reps")
        set_index = _integer(row["set"], "set")
        if set_index is None:
            raise IngestError("set number is missing")
        rpe, flag = clean_rpe(_number(row["rpe"], "rpe"), where)
        notes = [text for text in (row.get("set_note", "").strip(), row["note"].strip()) if text]
        canonical = CanonicalSet.build(
            workout_ts=start,
            workout_name=row["workout"].strip(),
            exercise_name_raw=exercise,
            set_index=set_index,
            set_type=parse_set_type(row["set_type"], SET_TYPES),
            weight_kg=to_kg(_number(row["weight"], "weight"), unit),
            source_unit=unit,
            reps=reps,
            rpe=rpe,
            failed=is_failed(reps),
            distance=_number(row["distance_km"], "distance_km"),
            duration_s=_number(row["seconds"], "seconds"),
            set_note="\n".join(dict.fromkeys(notes)) or None,
            workout_note=row["workout_note"].strip() or None,
            superset_id=row["superset_id"] or None,
            source_app=self.name,
        )
        return canonical, flag


def _number(value: str, column: str) -> float | None:
    if value == "":
        return None
    if not _NUMBER.fullmatch(value):
        raise IngestError(f"{column} {value!r} is not a number")
    return float(value)


def _integer(value: str, column: str) -> int | None:
    if value == "":
        return None
    if not _INTEGER.fullmatch(value):
        raise IngestError(f"{column} {value!r} is not a whole number")
    return int(value)
