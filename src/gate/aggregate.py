"""Signal aggregation and the fail-safe policy (plan §5.3)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from src.gate.rules import GateRules, default_rules
from src.gate.signals import GateSignals, ModelSignal, SignalFailure, SignalReading
from src.schemas import TriageLevel, at_least, max_level

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalStatus:
    """What one model signal said. ``level`` is ``None`` if it failed and nothing could be salvaged."""

    level: TriageLevel | None
    failed: bool
    error: str | None = None
    exercise_id: str | None = None


@dataclass(frozen=True)
class TextAssessment:
    """The three signals of one text and the resulting level."""

    rule_level: TriageLevel
    matched_patterns: tuple[str, ...]
    extractor: SignalStatus
    classifier: SignalStatus
    level: TriageLevel

    @property
    def unassessed_by_model(self) -> bool:
        """True if any model signal failed for this text."""
        return self.extractor.failed or self.classifier.failed


def read_signal(signal: ModelSignal | None, text: str) -> SignalStatus:
    """Query one model signal. Every error, and every answer that is not a level, is a failure."""
    if signal is None:
        return SignalStatus(None, True, "not available")
    try:
        answer = signal.assess(text)
        if isinstance(answer, SignalReading):
            return SignalStatus(TriageLevel(answer.level), False, exercise_id=answer.exercise_id)
        return SignalStatus(TriageLevel(answer), False)
    except SignalFailure as exc:
        return SignalStatus(exc.salvaged, True, str(exc))
    except Exception as exc:  # noqa: BLE001 - the policy covers every technical failure
        return SignalStatus(None, True, f"{type(exc).__name__}: {exc}")


def assess_text(text: str, signals: GateSignals, rules: GateRules | None = None) -> TextAssessment:
    """Level of one text: the most severe available signal, and at least yellow if a model signal failed.

    A technical failure alone never gives red. A surviving green never cancels a failed signal.
    """
    rule = (rules or default_rules()).assess(text)
    extractor = read_signal(signals.extractor, text)
    classifier = read_signal(signals.classifier, text)
    levels = [rule.level, *(s.level for s in (extractor, classifier) if s.level is not None)]
    level = max_level(levels)
    if extractor.failed or classifier.failed:
        level = at_least(level, TriageLevel.YELLOW)
        # The note text is personal data and is not logged.
        LOGGER.warning("unassessed_by_model: extractor=%s classifier=%s", extractor.error, classifier.error)
    return TextAssessment(rule.level, tuple(rule.matched_patterns), extractor, classifier, level)


def log_level(levels: Iterable[TriageLevel]) -> TriageLevel:
    """Most severe level of a log. Green only if there was nothing to assess or everything is green."""
    found = list(levels)
    return max_level(found) if found else TriageLevel.GREEN
