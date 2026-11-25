"""Programmatic isolated parser inputs, separate from the provenance-gated CSVs."""

from collections.abc import Callable, Sequence
import csv
from pathlib import Path

import pytest

# Independently transcribed community headers, not imported from adapter code.
STRONG_COLUMNS = (
    "Date", "Workout Name", "Duration", "Exercise Name", "Set Order", "Weight",
    "Reps", "Distance", "Seconds", "Notes", "Workout Notes", "RPE",
)
HEVY_COLUMNS = (
    "title", "start_time", "end_time", "description", "exercise_title", "superset_id",
    "exercise_notes", "set_index", "set_type", "weight_kg", "reps", "distance_km", "duration_seconds", "rpe",
)


@pytest.fixture
def write_csv(tmp_path: Path) -> Callable[..., Path]:
    def write(header: Sequence[str], records: Sequence[Sequence[str]], *, bom: bool = False) -> Path:
        path = tmp_path / "isolated.csv"
        with path.open('w', encoding='utf-8-sig' if bom else 'utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(records)
        return path

    return write


@pytest.fixture
def strong_values() -> dict[str, str]:
    return dict(zip(STRONG_COLUMNS, (
        "2030-04-02 09:00:00", "Synthetic workout", "1h 20m", "Unit lift", "1", "225",
        "8", "", "", "Set note", "Workout note", "7.5",
    ), strict=True))


@pytest.fixture
def hevy_values() -> dict[str, str]:
    return dict(zip(HEVY_COLUMNS, (
        "Synthetic workout", "2 Apr 2030, 09:00", "2 Apr 2030, 09:37", "Workout note",
        "Unit lift", "", "Exercise note", "0", "normal", "225", "8", "", "", "7.5",
    ), strict=True))
