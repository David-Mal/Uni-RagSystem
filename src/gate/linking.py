"""Which exercises a yellow note excludes (plan §5.3, "Linking notes to exercises")."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Literal

from src.ingest import CanonicalSet, Note
from src.schemas import UNKNOWN_EXERCISE_ID

LinkSource = Literal["structure", "extractor", "workout", "unresolved"]


@dataclass(frozen=True)
class Link:
    """Exclusions caused by one text. ``names`` are raw names, also for exercises without a matched id."""

    source: LinkSource
    exercise_ids: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()


def _usable(exercise_id: str | None) -> bool:
    return bool(exercise_id) and exercise_id != UNKNOWN_EXERCISE_ID


def link_note(note: Note, extractor_exercise_id: str | None, sets: Iterable[CanonicalSet]) -> Link:
    """Link a yellow log note.

    1. A set or exercise note belongs to its exercise in the file.
    2. Otherwise the extractor's exercise, if that exercise was performed in the note's workout.
    3. Otherwise every exercise of that workout. An extractor id that was not performed there is not trusted to
       narrow the exclusion; it is excluded as well.
    """
    if note.scope == "exercise":
        ids = frozenset({note.exercise_id}) if _usable(note.exercise_id) else frozenset()
        return Link("structure", ids, frozenset({note.exercise_name_raw or ""} - {""}))  # type: ignore[arg-type]

    workout = [s for s in sets if (s.workout_ts, s.workout_name) == (note.workout_ts, note.workout_name)]
    performed = {s.exercise_id for s in workout if _usable(s.exercise_id)}
    if _usable(extractor_exercise_id) and extractor_exercise_id in performed:
        names = {s.exercise_name_raw for s in workout if s.exercise_id == extractor_exercise_id}
        return Link("extractor", frozenset({extractor_exercise_id}), frozenset(names))  # type: ignore[arg-type]
    extra = {extractor_exercise_id} if _usable(extractor_exercise_id) else set()
    return Link("workout", frozenset(performed | extra), frozenset(s.exercise_name_raw for s in workout))  # type: ignore[arg-type]


def link_message(extractor_exercise_id: str | None, known_exercise_ids: Collection[str]) -> Link:
    """Link a yellow free-text message. Without an exercise of this log it stays unresolved."""
    if _usable(extractor_exercise_id) and extractor_exercise_id in known_exercise_ids:
        return Link("extractor", frozenset({extractor_exercise_id}))  # type: ignore[arg-type]
    return Link("unresolved")
