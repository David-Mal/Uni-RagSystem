"""Closed enums shared by the extractor, the safety gate, the harness, the verifier and the golden labels.

Frozen as schema version ``v0`` (see ``src.schemas.SCHEMA_VERSION``). Adding, removing or renaming a
member is a breaking change: bump the version and note it in the PR.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class TriageLevel(StrEnum):
    """Safety triage level of a note or message (plan §5.3).

    ``green``: no symptoms. ``yellow``: mild discomfort, stiffness, persistent soreness.
    ``red``: sharp pain, swelling, dizziness, chest pain. Ordered by severity: green < yellow < red.
    """

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"

    @property
    def severity(self) -> int:
        """Integer severity used for max-aggregation: green=0, yellow=1, red=2."""
        return _SEVERITY[self]


_SEVERITY: dict[TriageLevel, int] = {
    TriageLevel.GREEN: 0,
    TriageLevel.YELLOW: 1,
    TriageLevel.RED: 2,
}

GateLevel = TriageLevel
"""The gate's final level uses the same three values as the per-signal triage level."""


def max_level(levels: Iterable[TriageLevel | str]) -> TriageLevel:
    """Return the most severe level in ``levels`` (plan §5.3: final level = maximum severity).

    Accepts enum members or their string values. Raises ``ValueError`` on an empty iterable:
    the gate must never silently default to green when no signal was assessed.
    """
    parsed = [TriageLevel(level) for level in levels]
    if not parsed:
        raise ValueError("max_level() needs at least one level; an empty set must not default to green")
    return max(parsed, key=lambda level: level.severity)


def at_least(level: TriageLevel | str, floor: TriageLevel | str) -> TriageLevel:
    """Return ``level`` raised to ``floor`` if it is less severe (e.g. failed model signal -> at least yellow)."""
    return max_level([level, floor])


class Outcome(StrEnum):
    """Outcome of the set described in a note or message. The field is never null.

    ``completed``: no failure or partial completion is reported, which includes notes that do not mention the
    outcome at all. ``partial``: fewer reps than planned were completed. ``failed``: the attempted rep or set was not
    completed. Proposed in the #69 review, and the Fi1 guideline should carry the same definition.
    """

    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class KinematicObservation(StrEnum):
    """What the user reported about how the set moved (v0, plan §6.3).

    This records the user's own words, never a form diagnosis made by the system.
    """

    NONE = "none"
    SLOW_BAR_SPEED = "slow_bar_speed"
    GRINDING_REP = "grinding_rep"
    REDUCED_RANGE_OF_MOTION = "reduced_range_of_motion"
    LOST_BALANCE = "lost_balance"
    OTHER = "other"


class HypothesisLabel(StrEnum):
    """Closed hypothesis taxonomy for plateau explanations (plan §5.6, 7 labels)."""

    INSUFFICIENT_WEEKLY_VOLUME = "insufficient_weekly_volume"
    FATIGUE_ACCUMULATION = "fatigue_accumulation"
    STAGNANT_LOAD_PROGRESSION = "stagnant_load_progression"
    LOAD_SPIKE = "load_spike"
    INCONSISTENT_FREQUENCY = "inconsistent_frequency"
    LOGGING_QUALITY_ISSUE = "logging_quality_issue"
    CONFOUNDER_PRESENT = "confounder_present"


class EvidenceLevel(StrEnum):
    """How strongly the tool outputs support a hypothesis (plan §5.6)."""

    SUPPORTED = "supported"
    WEAK = "weak"
    INSUFFICIENT = "insufficient"
