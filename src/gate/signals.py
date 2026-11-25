"""Model-signal interfaces of the safety gate (plan §5.3). The models themselves are trained elsewhere (F6, F8)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import ValidationError

from src.schemas import EXERCISE_IDS_CONTEXT_KEY, ExtractionResult, TriageLevel, max_level, read_triage_level

T = TypeVar("T")


class SignalFailure(RuntimeError):
    """A model signal could not assess a text.

    ``salvaged`` is a valid ``triage_level`` found in an otherwise invalid output. It may raise the note's level, but
    the signal still counts as failed.
    """

    def __init__(self, message: str, salvaged: TriageLevel | None = None) -> None:
        super().__init__(message)
        self.salvaged = salvaged


@dataclass(frozen=True)
class SignalReading:
    """A model's level for one text, and the exercise it linked the text to, if any."""

    level: TriageLevel
    exercise_id: str | None = None


class ModelSignal(Protocol):
    """One model signal. ``assess`` may raise anything; the gate then treats the signal as failed."""

    def assess(self, text: str) -> TriageLevel | SignalReading: ...


def call_with_timeout(fn: Callable[[], T], timeout_s: float | None) -> T:
    """Run ``fn`` and raise ``TimeoutError`` if it takes longer than ``timeout_s`` (``None`` = no limit).

    Python cannot stop the worker thread; it is a daemon and its late result is ignored.
    """
    if timeout_s is None:
        return fn()
    box: list[tuple[bool, Any]] = []

    def work() -> None:
        try:
            box.append((True, fn()))
        except BaseException as exc:  # noqa: BLE001 - handed over to the caller
            box.append((False, exc))

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if not box:
        raise TimeoutError(f"no answer within {timeout_s:g} s")
    ok, payload = box[0]
    if not ok:
        raise payload
    return payload


class ExtractorSignal:
    """Third gate signal: ``triage_level`` of the SLM extractor, with one retry on an unusable output.

    ``generate`` returns the raw model output, as JSON text or as a mapping. ``exercise_ids`` is the known id set.
    """

    ATTEMPTS = 2

    def __init__(
        self,
        generate: Callable[[str], str | Mapping[str, Any]],
        exercise_ids: Collection[str] | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._generate = generate
        self._context = None if exercise_ids is None else {EXERCISE_IDS_CONTEXT_KEY: exercise_ids}
        self._timeout_s = timeout_s

    def assess(self, text: str) -> SignalReading:
        """Return the extracted level and exercise, or raise ``SignalFailure`` after the retry."""
        salvaged: list[TriageLevel] = []
        error: Exception | None = None
        for _ in range(self.ATTEMPTS):
            raw: Any = None
            try:
                raw = call_with_timeout(lambda: self._generate(text), self._timeout_s)
                raw = json.loads(raw) if isinstance(raw, str) else raw
                result = ExtractionResult.model_validate(raw, context=self._context)
            except Exception as exc:  # noqa: BLE001 - any model problem is a failed attempt
                error = exc
                level = read_triage_level(raw)
                if level is not None:
                    salvaged.append(level)
                continue
            # A red seen in a discarded first attempt is not lost.
            return SignalReading(max_level([result.triage_level, *salvaged]), result.exercise_id)
        kind = "invalid output" if isinstance(error, ValidationError | json.JSONDecodeError) else type(error).__name__
        raise SignalFailure(f"extractor: {kind}", max_level(salvaged) if salvaged else None)


class ClassifierSignal:
    """Second gate signal: the triage classifier (F8). Errors and timeouts are not retried."""

    def __init__(self, predict: Callable[[str], TriageLevel | str], timeout_s: float | None) -> None:
        self._predict = predict
        self._timeout_s = timeout_s

    def assess(self, text: str) -> TriageLevel:
        """Return the predicted level; an unknown label, an error or a timeout raises."""
        return TriageLevel(call_with_timeout(lambda: self._predict(text), self._timeout_s))


@dataclass(frozen=True)
class GateSignals:
    """The two model signals. ``None`` means the model is not available, which counts as failed, never as green."""

    extractor: ModelSignal | None = None
    classifier: ModelSignal | None = None
