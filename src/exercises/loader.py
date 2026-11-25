"""Offline loader for vendored yuhonas/free-exercise-db (issue D7, #12)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "exercises" / "free-exercise-db.json"
)

PRIMARY_MUSCLE_WEIGHT = 1.0
SECONDARY_MUSCLE_WEIGHT = 0.5


class Muscle(str, Enum):
    """Closed 17-muscle vocabulary from free-exercise-db."""

    ABDOMINALS = "abdominals"
    ABDUCTORS = "abductors"
    ADDUCTORS = "adductors"
    BICEPS = "biceps"
    CALVES = "calves"
    CHEST = "chest"
    FOREARMS = "forearms"
    GLUTES = "glutes"
    HAMSTRINGS = "hamstrings"
    LATS = "lats"
    LOWER_BACK = "lower back"
    MIDDLE_BACK = "middle back"
    NECK = "neck"
    QUADRICEPS = "quadriceps"
    SHOULDERS = "shoulders"
    TRAPS = "traps"
    TRICEPS = "triceps"


class Exercise(BaseModel):
    """Single exercise entry from free-exercise-db (images excluded)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    name: str
    force: str | None = None
    level: str
    mechanic: str | None = None
    equipment: str | None = None
    primary_muscles: list[Muscle] = Field(default_factory=list)
    secondary_muscles: list[Muscle] = Field(default_factory=list)
    category: str
    instructions: list[str] = Field(default_factory=list)


class ExerciseDiff(BaseModel):
    """Structural diff between two exercise dictionaries keyed by id."""

    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)


def _parse_entry(raw: Mapping[str, Any]) -> Exercise:
    return Exercise(
        id=raw["id"],
        name=raw["name"],
        force=raw.get("force"),
        level=raw["level"],
        mechanic=raw.get("mechanic"),
        equipment=raw.get("equipment"),
        primary_muscles=[Muscle(m) for m in (raw.get("primaryMuscles") or [])],
        secondary_muscles=[Muscle(m) for m in (raw.get("secondaryMuscles") or [])],
        category=raw["category"],
        instructions=list(raw.get("instructions") or []),
    )


@lru_cache(maxsize=4)
def _load_cached(resolved_path: str) -> dict[str, Exercise]:
    with Path(resolved_path).open("r", encoding="utf-8") as fh:
        raw_entries: list[dict[str, Any]] = json.load(fh)

    exercises: dict[str, Exercise] = {}
    for raw in raw_entries:
        ex = _parse_entry(raw)
        if ex.id in exercises:
            raise ValueError(f"Duplicate exercise id in free-exercise-db: {ex.id!r}")
        exercises[ex.id] = ex
    return exercises


def load_exercises(path: Path | str | None = None) -> dict[str, Exercise]:
    """Load all exercises from free-exercise-db.json keyed by exercise_id."""
    target = Path(path) if path is not None else DEFAULT_DB_PATH
    return dict(_load_cached(str(target.resolve())))


def exercise_ids(
    exercises: Mapping[str, Exercise] | None = None,
    *,
    path: Path | str | None = None,
) -> list[str]:
    """Return sorted closed vocabulary of exercise_id values."""
    data = exercises if exercises is not None else load_exercises(path)
    return sorted(data.keys())


def diff(
    old: Mapping[str, Exercise],
    new: Mapping[str, Exercise],
) -> ExerciseDiff:
    """Compare two exercise dicts by id and report added, removed, and changed ids."""
    old_ids = set(old.keys())
    new_ids = set(new.keys())
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    changed = sorted(ex_id for ex_id in (old_ids & new_ids) if old[ex_id] != new[ex_id])
    return ExerciseDiff(added=added, removed=removed, changed=changed)


def muscle_weights(
    exercise_id: str,
    exercises: Mapping[str, Exercise] | None = None,
    *,
    path: Path | str | None = None,
) -> dict[Muscle, float]:
    """Return muscle contribution weights (primary = 1.0, secondary = 0.5) for an exercise."""
    data = exercises if exercises is not None else load_exercises(path)
    if exercise_id not in data:
        raise KeyError(f"Unknown exercise_id: {exercise_id!r}")
    ex = data[exercise_id]
    weights: dict[Muscle, float] = {}
    for m in ex.secondary_muscles:
        weights[m] = SECONDARY_MUSCLE_WEIGHT
    for m in ex.primary_muscles:
        weights[m] = PRIMARY_MUSCLE_WEIGHT
    return weights
