"""The mandatory safety gate (plan §5.3): ``assess`` is the only source of a ``GateResult``, and an ``AgentContext``
cannot exist without one. ``run_gated`` is the only path from a log to an agent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import InitVar, dataclass
from typing import Final, Generic, TypeVar

from src.gate.aggregate import TextAssessment, assess_text, log_level
from src.gate.linking import Link, link_message, link_note
from src.gate.messages import (
    CLARIFICATION_FLAG,
    NEEDS_CLARIFICATION,
    RED_REFERRAL,
    UNASSESSED_FLAG,
    WORKOUT_FLAG,
    YELLOW_FLAG,
)
from src.gate.signals import GateSignals
from src.ingest import Note, SetStore
from src.schemas import UNKNOWN_EXERCISE_ID, HypothesisLabel, TriageLevel

T = TypeVar("T")

MESSAGE_ID: Final = "message"
"""Id of the free-text message among the assessed texts; note ids are content hashes."""

_TOKEN: Final = object()


class GateBlocked(RuntimeError):
    """The gate result does not allow an analysis (red, or a clarification is needed)."""


@dataclass(frozen=True)
class NoteAssessment:
    """One assessed text: the signals, the level and what it excludes (``link`` only for yellow)."""

    note_id: str
    assessment: TextAssessment
    link: Link | None = None

    @property
    def level(self) -> TriageLevel:
        """Level of this text."""
        return self.assessment.level


@dataclass(frozen=True)
class GateResult:
    """Outcome of the gate for one log. Created only by ``assess``."""

    log_id: str
    level: TriageLevel
    excluded_exercise_ids: frozenset[str]
    excluded_names: frozenset[str]
    disclaimer_flags: tuple[str, ...]
    per_note: tuple[NoteAssessment, ...]
    unassessed_notes: tuple[str, ...]
    needs_clarification: bool
    allowed_exercise_ids: frozenset[str]
    _token: InitVar[object] = None

    def __post_init__(self, _token: object) -> None:
        # An InitVar is not copied by dataclasses.replace(), so an altered copy is rejected here too.
        if _token is not _TOKEN:
            raise TypeError("GateResult is created only by gate.assess()")


class AgentContext:
    """What the agent may work on. The only way to build one is from a ``GateResult`` that allows analysis."""

    __slots__ = ("_gate",)

    def __init__(self, gate: GateResult) -> None:
        if not isinstance(gate, GateResult):
            raise TypeError("AgentContext requires a GateResult")
        if gate.level is TriageLevel.RED:
            raise GateBlocked("red: analysis is blocked")
        if gate.needs_clarification:
            raise GateBlocked("the message needs a clarification before any analysis")
        self._gate = gate

    @property
    def gate(self) -> GateResult:
        """The gate result this context came from."""
        return self._gate

    @property
    def log_id(self) -> str:
        """The log to analyze."""
        return self._gate.log_id

    @property
    def allowed_exercise_ids(self) -> frozenset[str]:
        """Matched exercises of the log minus the excluded ones."""
        return self._gate.allowed_exercise_ids

    @property
    def allowed_hypotheses(self) -> frozenset[HypothesisLabel]:
        """Hypotheses the agent may assert. Nothing is allowed if no exercise is left."""
        return frozenset(HypothesisLabel) if self.allowed_exercise_ids else frozenset()


def assess(
    notes: Iterable[Note], message: str | None, store: SetStore, signals: GateSignals, *, log_id: str
) -> GateResult:
    """Assess every note of the log and the optional message, and return the gate result.

    Notes stored for ``log_id`` are always assessed, also if the caller forgets to pass them. A note of another log is
    an error.
    """
    by_id = {n.note_id: n for n in store.get_notes(log_id)}
    for note in notes:
        if note.log_id != log_id:
            raise ValueError(f"note of log {note.log_id!r} passed for log {log_id!r}")
        by_id.setdefault(note.note_id, note)
    sets = store.get_sets(log_id)
    known = frozenset(s.exercise_id for s in sets if s.exercise_id and s.exercise_id != UNKNOWN_EXERCISE_ID)

    per_note: list[NoteAssessment] = []
    for note in by_id.values():
        a = assess_text(note.text, signals)
        link = link_note(note, a.extractor.exercise_id, sets) if a.level is TriageLevel.YELLOW else None
        per_note.append(NoteAssessment(note.note_id, a, link))
    if message is not None and message.strip():
        a = assess_text(message, signals)
        link = link_message(a.extractor.exercise_id, known) if a.level is TriageLevel.YELLOW else None
        per_note.append(NoteAssessment(MESSAGE_ID, a, link))

    level = log_level(n.level for n in per_note)
    links = [n.link for n in per_note if n.link is not None]
    excluded = frozenset().union(*(link.exercise_ids for link in links))
    unassessed = tuple(n.note_id for n in per_note if n.assessment.unassessed_by_model)
    clarify = level is not TriageLevel.RED and any(link.source == "unresolved" for link in links)
    raised = {
        YELLOW_FLAG: level is TriageLevel.YELLOW,
        UNASSESSED_FLAG: bool(unassessed),
        WORKOUT_FLAG: any(link.source == "workout" for link in links),
        CLARIFICATION_FLAG: clarify,
    }
    red = level is TriageLevel.RED
    return GateResult(
        log_id=log_id,
        level=level,
        excluded_exercise_ids=excluded,
        excluded_names=frozenset().union(*(link.names for link in links)),
        # Red shows the referral text and nothing else (plan §5.5).
        disclaimer_flags=() if red else tuple(flag for flag, on in raised.items() if on),
        per_note=tuple(per_note),
        unassessed_notes=unassessed,
        needs_clarification=clarify,
        allowed_exercise_ids=frozenset() if red else known - excluded,
        _token=_TOKEN,
    )


@dataclass(frozen=True)
class GatedRun(Generic[T]):
    """Result of ``run_gated``: either the agent's output, or a blocked run."""

    gate: GateResult
    output: T | None = None
    blocked_text: str | None = None


def run_gated(
    agent: Callable[[AgentContext], T],
    notes: Iterable[Note],
    message: str | None,
    store: SetStore,
    signals: GateSignals,
    *,
    log_id: str,
) -> GatedRun[T]:
    """Run the gate, then the agent only if the gate allows it. If the gate raises, the agent is not reached."""
    result = assess(notes, message, store, signals, log_id=log_id)
    if result.level is TriageLevel.RED:
        return GatedRun(result, blocked_text=RED_REFERRAL)
    if result.needs_clarification:
        return GatedRun(result, blocked_text=NEEDS_CLARIFICATION)
    return GatedRun(result, output=agent(AgentContext(result)))
