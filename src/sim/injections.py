"""Copy-on-write workout transformations and direct, non-indicator observations."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import math
from typing import Callable, Literal, TypeAlias

from .plans import InjectionRequest
from .schema import freeze_json, nonempty
from .workouts import NoteTemplateRef, SimulatedLog, SimSession, SimSet, convert_load, count, finite


@dataclass(frozen=True)
class SessionRange:
    start: int = 0
    stop: int | None = None

    def __post_init__(self) -> None:
        count(self.start, "range start")
        if self.stop is not None:
            count(self.stop, "range stop")
            if self.stop < self.start:
                raise ValueError("range stop must not precede start")

    def indices(self, log: SimulatedLog) -> range:
        count(self.start, "range start")
        stop = len(log.sessions) if self.stop is None else self.stop
        count(stop, "range stop")
        if not self.start <= stop <= len(log.sessions):
            raise ValueError("session range is outside the simulated log")
        return range(self.start, stop)


@dataclass(frozen=True)
class ReduceSets:
    keep_per_exercise: int
    interval: SessionRange = SessionRange()

    def __post_init__(self) -> None:
        count(self.keep_per_exercise, "keep_per_exercise")
        if not isinstance(self.interval, SessionRange):
            raise ValueError("interval must be SessionRange")


@dataclass(frozen=True)
class RisingRPE:
    start_rpe: float
    step_per_session: float
    interval: SessionRange = SessionRange()

    def __post_init__(self) -> None:
        finite(self.start_rpe, "start_rpe")
        finite(self.step_per_session, "step_per_session")
        if self.step_per_session <= 0:
            raise ValueError("a rising RPE step must be positive")
        if not isinstance(self.interval, SessionRange):
            raise ValueError("interval must be SessionRange")


@dataclass(frozen=True)
class StagnantLoads:
    interval: SessionRange = SessionRange()

    def __post_init__(self) -> None:
        if not isinstance(self.interval, SessionRange):
            raise ValueError("interval must be SessionRange")


@dataclass(frozen=True)
class LoadSpike:
    factor: float
    interval: SessionRange

    def __post_init__(self) -> None:
        finite(self.factor, "spike factor")
        if self.factor <= 1:
            raise ValueError("an increase requires a factor greater than one")
        if not isinstance(self.interval, SessionRange):
            raise ValueError("interval must be SessionRange")


@dataclass(frozen=True)
class SessionGap:
    start: datetime
    end: datetime
    reschedule_by: timedelta | None = None
    for_abstention: bool = False

    def __post_init__(self) -> None:
        if not all(isinstance(item, datetime) and item.tzinfo is None for item in (self.start, self.end)):
            raise ValueError("gap endpoints must be naive datetimes")
        if self.end <= self.start:
            raise ValueError("gap end must follow its start")
        if self.reschedule_by is not None and (
            not isinstance(self.reschedule_by, timedelta) or self.reschedule_by == timedelta(0)
        ):
            raise ValueError("rescheduling needs a nonzero timedelta")
        if type(self.for_abstention) is not bool:
            raise ValueError("for_abstention must be a boolean")


@dataclass(frozen=True)
class MixedUnits:
    every: int

    def __post_init__(self) -> None:
        count(self.every, "every", 1)


@dataclass(frozen=True)
class DuplicateSets:
    copies: int
    session_index: int = 0
    exercise_index: int = 0
    set_index: int = 0

    def __post_init__(self) -> None:
        count(self.copies, "copies", 1)
        for name in ("session_index", "exercise_index", "set_index"):
            count(getattr(self, name), name)


@dataclass(frozen=True)
class MissingRPE:
    every: int
    for_abstention: bool = False

    def __post_init__(self) -> None:
        count(self.every, "every", 1)
        if type(self.for_abstention) is not bool:
            raise ValueError("for_abstention must be a boolean")
        if self.for_abstention and self.every != 1:
            raise ValueError("the no-RPE abstention pattern clears all ratings")


@dataclass(frozen=True)
class Outlier:
    field: Literal["load", "rpe"]
    value: float
    session_index: int = 0
    exercise_index: int = 0
    set_index: int = 0

    def __post_init__(self) -> None:
        if self.field not in ("load", "rpe"):
            raise ValueError("an outlier must target load or rpe")
        finite(self.value, "outlier value")
        for name in ("session_index", "exercise_index", "set_index"):
            count(getattr(self, name), name)


@dataclass(frozen=True)
class ConfounderNotes:
    template_refs: tuple[NoteTemplateRef, ...]
    session_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.template_refs, tuple) or not self.template_refs or not all(
            isinstance(item, NoteTemplateRef) and item.confounder is not None for item in self.template_refs
        ):
            raise ValueError("confounders need externally supplied tagged template references")
        if not isinstance(self.session_indices, tuple) or not self.session_indices:
            raise ValueError("at least one session must receive the references")
        for index in self.session_indices:
            count(index, "note session index")
        if len(set(self.session_indices)) != len(self.session_indices):
            raise ValueError("note session indices must be unique")
        if len({item.template_id for item in self.template_refs}) != len(self.template_refs):
            raise ValueError("note reference IDs must be unique")


@dataclass(frozen=True)
class ShortHistory:
    keep_days: int

    def __post_init__(self) -> None:
        count(self.keep_days, "keep_days")


@dataclass(frozen=True)
class FewSessions:
    keep: int

    def __post_init__(self) -> None:
        count(self.keep, "keep")


Injection: TypeAlias = ReduceSets | RisingRPE | StagnantLoads | LoadSpike | SessionGap | MixedUnits | DuplicateSets | MissingRPE | Outlier | ConfounderNotes | ShortHistory | FewSessions


def injection_request(config: Injection) -> InjectionRequest:
    """Declare intent only; final coverage must inspect transformed data."""
    if isinstance(config, ReduceSets):
        return InjectionRequest(hypotheses=("insufficient_weekly_volume",))
    if isinstance(config, RisingRPE):
        return InjectionRequest(hypotheses=("fatigue_accumulation",))
    if isinstance(config, StagnantLoads):
        return InjectionRequest(hypotheses=("stagnant_load_progression",))
    if isinstance(config, LoadSpike):
        return InjectionRequest(hypotheses=("load_spike",))
    if isinstance(config, SessionGap):
        return InjectionRequest(hypotheses=("inconsistent_frequency",), abstention_cases=("long_gaps",) if config.for_abstention else ())
    if isinstance(config, ConfounderNotes):
        topics = tuple(dict.fromkeys(item.confounder for item in config.template_refs))
        return InjectionRequest(hypotheses=("confounder_present",), confounders=topics,
                                human_note_template_id=config.template_refs[0].template_id)
    if isinstance(config, (MixedUnits, DuplicateSets, MissingRPE, Outlier)):
        trap = {MixedUnits: "mixed_units", DuplicateSets: "duplicates", MissingRPE: "missing_rpe", Outlier: "outliers"}[type(config)]
        abstention = ("missing_rpe",) if isinstance(config, MissingRPE) and config.for_abstention else ()
        return InjectionRequest(hypotheses=("logging_quality_issue",), numeric_traps=(trap,), abstention_cases=abstention)
    if isinstance(config, ShortHistory):
        return InjectionRequest(abstention_cases=("too_little_history",))
    if isinstance(config, FewSessions):
        return InjectionRequest(abstention_cases=("too_few_sessions",))
    raise ValueError("unknown injection configuration")


def flat_sets(log: SimulatedLog) -> tuple[SimSet, ...]:
    return tuple(item for session in log.sessions for exercise in session.exercises for item in exercise.sets)


def _map_sets(log: SimulatedLog, transform: Callable[[int, int, int, SimSet], SimSet]) -> SimulatedLog:
    return SimulatedLog(tuple(replace(session, exercises=tuple(
        replace(exercise, sets=tuple(transform(si, ei, ti, item) for ti, item in enumerate(exercise.sets)))
        for ei, exercise in enumerate(session.exercises)
    )) for si, session in enumerate(log.sessions)))


def _target(log: SimulatedLog, config: DuplicateSets | Outlier) -> SimSet:
    try:
        return log.sessions[config.session_index].exercises[config.exercise_index].sets[config.set_index]
    except IndexError as exc:
        raise ValueError("injection target does not exist") from exc


def _profile(session: SimSession) -> dict[tuple[str, int], SimSet]:
    return {(exercise.exercise_key, item.slot): item for exercise in session.exercises for item in exercise.sets}


def apply_injection(log: SimulatedLog, config: Injection) -> SimulatedLog:
    """Transform actual immutable workout data; never assign expected annotations."""
    injection_request(config)
    if isinstance(config, (ReduceSets, RisingRPE, StagnantLoads, LoadSpike)):
        selected = config.interval.indices(log)
        if isinstance(config, ReduceSets):
            return SimulatedLog(tuple(replace(session, exercises=tuple(
                replace(exercise, sets=exercise.sets[:config.keep_per_exercise]) for exercise in session.exercises
            )) if index in selected else session for index, session in enumerate(log.sessions)))
        reference = _profile(log.sessions[selected.start]) if selected else {}

        def transform(si: int, ei: int, ti: int, item: SimSet) -> SimSet:
            if si not in selected:
                return item
            if isinstance(config, LoadSpike):
                return replace(item, load=item.load * config.factor)
            key = (log.sessions[si].exercises[ei].exercise_key, item.slot)
            if key not in reference:
                raise ValueError("stable-load injection requires matching exercise/set slots")
            base = reference[key]
            if isinstance(config, RisingRPE):
                return replace(item, load=base.load, unit=base.unit,
                               rpe=config.start_rpe + config.step_per_session * (si - selected.start))
            return replace(item, load=base.load, unit=base.unit, reps=base.reps)

        return _map_sets(log, transform)
    if isinstance(config, SessionGap):
        sessions = []
        for session in log.sessions:
            if config.start <= session.at < config.end:
                if config.reschedule_by is not None:
                    sessions.append(replace(session, at=session.at + config.reschedule_by))
            else:
                sessions.append(session)
        return SimulatedLog(tuple(sorted(sessions, key=lambda item: (item.at, item.session_id))))
    if isinstance(config, (MixedUnits, MissingRPE)):
        position = 0

        def transform(si: int, ei: int, ti: int, item: SimSet) -> SimSet:
            nonlocal position
            selected = position % config.every == 0
            position += 1
            if not selected:
                return item
            if isinstance(config, MissingRPE):
                return replace(item, rpe=None)
            unit = "lb" if item.unit == "kg" else "kg"
            return replace(item, load=convert_load(item.load, item.unit, unit), unit=unit)

        return _map_sets(log, transform)
    if isinstance(config, DuplicateSets):
        target = _target(log, config)
        sessions = list(log.sessions)
        session = sessions[config.session_index]
        exercises = list(session.exercises)
        exercise = exercises[config.exercise_index]
        at = config.set_index + 1
        exercises[config.exercise_index] = replace(exercise, sets=exercise.sets[:at] + (target,) * config.copies + exercise.sets[at:])
        sessions[config.session_index] = replace(session, exercises=tuple(exercises))
        return SimulatedLog(tuple(sessions))
    if isinstance(config, Outlier):
        _target(log, config)
        return _map_sets(log, lambda si, ei, ti, item: replace(item, **{config.field: config.value})
                         if (si, ei, ti) == (config.session_index, config.exercise_index, config.set_index) else item)
    if isinstance(config, ConfounderNotes):
        if any(index >= len(log.sessions) for index in config.session_indices):
            raise ValueError("note session does not exist")
        return SimulatedLog(tuple(replace(session, note_refs=session.note_refs + config.template_refs)
                                  if index in config.session_indices else session
                                  for index, session in enumerate(log.sessions)))
    if isinstance(config, ShortHistory):
        if not log.sessions:
            return log
        cutoff = log.sessions[-1].at - timedelta(days=config.keep_days)
        return SimulatedLog(tuple(session for session in log.sessions if session.at >= cutoff))
    if isinstance(config, FewSessions):
        return SimulatedLog(log.sessions[-config.keep:] if config.keep else ())
    raise ValueError("unknown injection configuration")


def max_gap_seconds(log: SimulatedLog) -> float:
    return max(((b.at - a.at).total_seconds() for a, b in zip(log.sessions, log.sessions[1:])), default=0.0)


def _span(log: SimulatedLog) -> float:
    return (log.sessions[-1].at - log.sessions[0].at).total_seconds() if log.sessions else 0.0


def _work(log: SimulatedLog) -> float:
    # Raw internal working-set arithmetic only: no D3 exclusions/windows/ratio.
    return sum(convert_load(item.load, item.unit, "kg") * item.reps for item in flat_sets(log))


@dataclass(frozen=True)
class InjectionObservation:
    pattern: str
    request: InjectionRequest
    present: bool
    facts: Mapping[str, object]

    def __post_init__(self) -> None:
        nonempty(self.pattern, "pattern")
        if not isinstance(self.request, InjectionRequest) or type(self.present) is not bool:
            raise ValueError("an observation requires a request and explicit presence boolean")
        if not isinstance(self.facts, Mapping):
            raise ValueError("observation facts must be an object")
        object.__setattr__(self, "facts", freeze_json(self.facts))


def observe_injection(before: SimulatedLog, final: SimulatedLog, config: Injection) -> InjectionObservation:
    """Check the final data, including whether later transformations erased a pattern.

    Comparisons describe raw changes, not D3 evidence or sufficiency decisions.
    Two points suffice to describe a rise/constant pair, not to validate a trend.
    """
    request = injection_request(config)
    facts: dict[str, object] = {}
    present = False
    if isinstance(config, (ReduceSets, RisingRPE, StagnantLoads, LoadSpike)):
        selected_ids = {before.sessions[index].session_id for index in config.interval.indices(before)}
        old = SimulatedLog(tuple(item for item in before.sessions if item.session_id in selected_ids))
        new = SimulatedLog(tuple(item for item in final.sessions if item.session_id in selected_ids))
        if isinstance(config, ReduceSets):
            facts = {"before_sets": len(flat_sets(old)), "after_sets": len(flat_sets(new)), "keep": config.keep_per_exercise}
            reduced_at_application = any(len(exercise.sets) > config.keep_per_exercise for session in old.sessions for exercise in session.exercises)
            present = reduced_at_application and facts["after_sets"] < facts["before_sets"] and all(
                len(exercise.sets) <= config.keep_per_exercise for session in new.sessions for exercise in session.exercises
            )
        elif isinstance(config, LoadSpike):
            facts = {"before_load_times_reps_kg": _work(old), "after_load_times_reps_kg": _work(new), "configured_factor": config.factor}
            present = facts["after_load_times_reps_kg"] > facts["before_load_times_reps_kg"]
        else:
            profiles = [_profile(session) for session in new.sessions]
            common = set.intersection(*(set(item) for item in profiles)) if profiles else set()
            fixed_load = stable_reps = rising_rpe = True
            for key in sorted(common):
                series = [profile[key] for profile in profiles]
                physical = [convert_load(item.load, item.unit, "kg") for item in series]
                # Only floating-point conversion precision; not a comparable-load band.
                fixed_load &= all(math.isclose(value, physical[0], rel_tol=1e-12, abs_tol=0.0) for value in physical)
                if isinstance(config, StagnantLoads):
                    stable_reps &= all(item.reps == series[0].reps for item in series)
                else:
                    rising_rpe &= all(item.rpe is not None for item in series) and all(
                        a.rpe < b.rpe for a, b in zip(series, series[1:]) if a.rpe is not None and b.rpe is not None
                    )
            present = len(profiles) >= 2 and bool(common) and fixed_load and (
                stable_reps if isinstance(config, StagnantLoads) else rising_rpe
            )
            facts = {"sessions": len(profiles), "common_set_slots": len(common), "fixed_load": bool(common) and bool(fixed_load)}
            if isinstance(config, RisingRPE) and profiles and common:
                key = sorted(common)[0]
                facts.update(first_rpe=profiles[0][key].rpe, last_rpe=profiles[-1][key].rpe)
    elif isinstance(config, SessionGap):
        facts = {"before_sessions": len(before.sessions), "after_sessions": len(final.sessions),
                 "before_max_gap_seconds": max_gap_seconds(before), "after_max_gap_seconds": max_gap_seconds(final)}
        final_times = {item.session_id: item.at for item in final.sessions}
        changed = any(final_times.get(item.session_id) != item.at for item in before.sessions if config.start <= item.at < config.end)
        present = changed and (not config.for_abstention or max_gap_seconds(final) > max_gap_seconds(before))
    elif isinstance(config, MixedUnits):
        def mixed_exercises(log: SimulatedLog) -> list[str]:
            units: dict[str, set[str]] = defaultdict(set)
            for session in log.sessions:
                for exercise in session.exercises:
                    units[exercise.exercise_key].update(item.unit for item in exercise.sets)
            return sorted(key for key, values in units.items() if len(values) > 1)

        mixed = mixed_exercises(final)
        present = bool(mixed) and bool(mixed_exercises(apply_injection(before, config)))
        facts = {"mixed_exercises": mixed}
    elif isinstance(config, DuplicateSets):
        target = _target(before, config)
        matching = [item for item in flat_sets(final) if item.set_id == target.set_id]
        counts = Counter(matching)
        present = bool(counts) and max(counts.values()) >= config.copies + 1
        facts = {"target_set_id": target.set_id, "identical_copies": max(counts.values(), default=0)}
    elif isinstance(config, MissingRPE):
        sets = flat_sets(final)
        missing = sum(item.rpe is None for item in sets)
        present = bool(sets) and (missing == len(sets) if config.for_abstention else missing > 0)
        facts = {"sets": len(sets), "missing_rpe": missing}
    elif isinstance(config, Outlier):
        target = _target(before, config)
        matching = [item for item in flat_sets(final) if item.set_id == target.set_id]
        present = bool(matching) and getattr(target, config.field) != config.value and any(
            getattr(item, config.field) == config.value for item in matching
        )
        facts = {"field": config.field, "before": getattr(target, config.field), "configured_value": config.value}
    elif isinstance(config, ConfounderNotes):
        wanted = set(config.template_refs)
        matches = sum(ref in wanted for session in final.sessions for ref in session.note_refs)
        present = matches > 0
        facts = {"attached_template_references": matches, "template_ids": [item.template_id for item in config.template_refs]}
    elif isinstance(config, ShortHistory):
        present = _span(apply_injection(before, config)) < _span(before) and _span(final) < _span(before)
        facts = {"before_span_seconds": _span(before), "after_span_seconds": _span(final), "configured_days": config.keep_days}
    elif isinstance(config, FewSessions):
        present = config.keep < len(before.sessions) and len(final.sessions) < len(before.sessions) and len(final.sessions) <= config.keep
        facts = {"before_sessions": len(before.sessions), "after_sessions": len(final.sessions), "configured_keep": config.keep}
    return InjectionObservation(type(config).__name__, request, bool(present), facts)
