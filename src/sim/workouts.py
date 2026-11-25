"""Deterministic internal workout data, deliberately independent of ingest/export."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta
import math
import random
from typing import Literal

from .params import LifterParams
from .schema import json_bytes, nonempty

Unit = Literal["kg", "lb"]
# Exact avoirdupois conversion: NIST SP 811, footnote 22. Not an indicator rule.
KG_PER_LB = 0.45359237


def finite(value: object, name: str) -> None:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a finite number")


def count(value: object, name: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def convert_load(load: float, source: Unit, target: Unit) -> float:
    finite(load, "load")
    if source not in ("kg", "lb") or target not in ("kg", "lb"):
        raise ValueError("unknown simulation unit")
    result = load if source == target else load * KG_PER_LB if source == "lb" else load / KG_PER_LB
    finite(result, "converted load")
    return result


def development_value(value: object) -> object:
    """Encode internal metadata, not an OpenGym or canonical export contract."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: development_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [development_value(item) for item in value]
    return value


@dataclass(frozen=True)
class NoteTemplateRef:
    """Externally supplied metadata only: no human template wording is stored."""

    template_id: str
    confounder: Literal["sleep_loss", "illness", "travel"] | None = None

    def __post_init__(self) -> None:
        nonempty(self.template_id, "template_id")
        if self.confounder not in (None, "sleep_loss", "illness", "travel"):
            raise ValueError("unknown confounder tag")


@dataclass(frozen=True)
class SimSet:
    set_id: str
    slot: int
    load: float
    unit: Unit
    reps: int
    rpe: float | None

    def __post_init__(self) -> None:
        nonempty(self.set_id, "set_id")
        count(self.slot, "slot")
        count(self.reps, "reps")
        finite(self.load, "load")
        if self.unit not in ("kg", "lb"):
            raise ValueError("unknown simulation unit")
        if self.rpe is not None:
            finite(self.rpe, "rpe")
        # Negative loads and unusual RPE can deliberately represent logging traps.


@dataclass(frozen=True)
class SimExercise:
    exercise_key: str
    sets: tuple[SimSet, ...]

    def __post_init__(self) -> None:
        nonempty(self.exercise_key, "exercise_key")
        if not isinstance(self.sets, tuple) or not all(isinstance(item, SimSet) for item in self.sets):
            raise ValueError("sets must be an immutable tuple of SimSet")


@dataclass(frozen=True)
class SimSession:
    session_id: str
    at: datetime
    exercises: tuple[SimExercise, ...]
    note_refs: tuple[NoteTemplateRef, ...] = ()

    def __post_init__(self) -> None:
        nonempty(self.session_id, "session_id")
        if not isinstance(self.at, datetime) or self.at.tzinfo is not None:
            raise ValueError("internal session timestamps must be naive datetimes")
        if not isinstance(self.exercises, tuple) or not all(isinstance(item, SimExercise) for item in self.exercises):
            raise ValueError("exercises must be an immutable tuple")
        if len({item.exercise_key for item in self.exercises}) != len(self.exercises):
            raise ValueError("exercise keys must be unique within a session")
        if not isinstance(self.note_refs, tuple) or not all(isinstance(item, NoteTemplateRef) for item in self.note_refs):
            raise ValueError("note_refs must contain references, never note wording")


@dataclass(frozen=True)
class SimulatedLog:
    sessions: tuple[SimSession, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.sessions, tuple) or not all(isinstance(item, SimSession) for item in self.sessions):
            raise ValueError("sessions must be an immutable tuple")
        if len({item.session_id for item in self.sessions}) != len(self.sessions):
            raise ValueError("session IDs must be unique")
        if tuple(sorted(self.sessions, key=lambda item: (item.at, item.session_id))) != self.sessions:
            raise ValueError("sessions must have stable chronological ordering")

    def to_dict(self) -> dict[str, object]:
        return {"development_only": True, "representation": "fi2-internal", "sessions": development_value(self.sessions)}

    def to_json_bytes(self) -> bytes:
        return json_bytes(self.to_dict())


@dataclass(frozen=True)
class ExerciseSpec:
    exercise_key: str
    sets_per_session: int
    reps: int
    load_multiplier: float

    def __post_init__(self) -> None:
        nonempty(self.exercise_key, "exercise_key")
        count(self.sets_per_session, "sets_per_session")
        count(self.reps, "reps")
        finite(self.load_multiplier, "load_multiplier")
        if self.load_multiplier < 0:
            raise ValueError("load_multiplier cannot be negative")


@dataclass(frozen=True)
class SimulationDesign:
    """Explicit development design; no physiological or indicator defaults."""

    start: datetime
    weeks: int
    session_offsets: tuple[timedelta, ...]
    exercises: tuple[ExerciseSpec, ...]
    base_rpe: float
    rpe_logging_probability: float
    note_templates: tuple[NoteTemplateRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.start, datetime) or self.start.tzinfo is not None:
            raise ValueError("start must be a naive datetime")
        count(self.weeks, "weeks")
        if not isinstance(self.session_offsets, tuple) or not all(
            isinstance(item, timedelta) and timedelta(0) <= item < timedelta(weeks=1)
            for item in self.session_offsets
        ):
            raise ValueError("session offsets must fall within one calendar week")
        if tuple(sorted(set(self.session_offsets))) != self.session_offsets:
            raise ValueError("session offsets must be strictly increasing")
        if not isinstance(self.exercises, tuple) or not all(isinstance(item, ExerciseSpec) for item in self.exercises):
            raise ValueError("exercises must contain ExerciseSpec")
        if len({item.exercise_key for item in self.exercises}) != len(self.exercises):
            raise ValueError("exercise keys must be unique")
        finite(self.base_rpe, "base_rpe")
        finite(self.rpe_logging_probability, "rpe_logging_probability")
        if not 0 <= self.rpe_logging_probability <= 1:
            raise ValueError("a logging probability must be between zero and one")
        if not isinstance(self.note_templates, tuple) or not all(isinstance(item, NoteTemplateRef) for item in self.note_templates):
            raise ValueError("note_templates must contain opaque references only")
        if len({item.template_id for item in self.note_templates}) != len(self.note_templates):
            raise ValueError("template reference identifiers must be unique")


def generate_workouts(params: LifterParams, design: SimulationDesign, *, seed: int) -> SimulatedLog:
    """Generate real sets using an explicit linear, bounded-noise toy model.

    load = start_e1rm * exercise multiplier + progression_rate * session index
    + uniform(-noise, noise), in the selected unit. This is not an e1RM estimator
    or a scientific adaptation model. Invalid negative working loads are rejected,
    never silently clamped. RPE/notes use independent RNG streams.
    """
    if not isinstance(params, LifterParams) or not isinstance(design, SimulationDesign):
        raise ValueError("validated parameters and design are required")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if len(design.session_offsets) != params.sessions_per_week:
        raise ValueError("session offsets must match sessions_per_week")
    if math.ceil(params.notes_frequency) > len(design.note_templates):
        raise ValueError("notes frequency requires enough externally supplied template references")
    loads = random.Random(f"{seed}:loads")
    ratings = random.Random(f"{seed}:rpe")
    notes = random.Random(f"{seed}:notes")
    sessions = []
    for week in range(design.weeks):
        for offset in design.session_offsets:
            index = len(sessions)
            session_id = f"session-{index:06d}"
            exercises = []
            for exercise_index, spec in enumerate(design.exercises):
                sets = []
                for slot in range(spec.sets_per_session):
                    load = params.start_e1rm * spec.load_multiplier + params.progression_rate * index
                    load += loads.uniform(-params.noise, params.noise)
                    finite(load, "generated load")
                    if load < 0:
                        raise ValueError("design produces a negative working load")
                    logged = params.rpe_habit == "always" or (
                        params.rpe_habit == "sometimes" and ratings.random() < design.rpe_logging_probability
                    )
                    sets.append(SimSet(f"{session_id}/exercise-{exercise_index}/set-{slot}", slot,
                                       load, params.units, spec.reps, design.base_rpe if logged else None))
                exercises.append(SimExercise(spec.exercise_key, tuple(sets)))
            note_count = math.floor(params.notes_frequency)
            if notes.random() < params.notes_frequency - note_count:
                note_count += 1
            refs = tuple(notes.sample(design.note_templates, note_count))
            sessions.append(SimSession(session_id, design.start + timedelta(weeks=week) + offset, tuple(exercises), refs))
    return SimulatedLog(tuple(sessions))
