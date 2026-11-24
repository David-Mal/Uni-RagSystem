"""Pydantic models for extraction results and agent claims (plan §3.3, §5.8, §6.3).

``ExtractionResult`` is the strict JSON the SLM extractor emits for one note or message; the golden
messages are labeled with the same model. ``Claim`` is one structured statement emitted by the agent
and checked by ``output_verifier``.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from src.schemas.enums import (
    EvidenceLevel,
    HypothesisLabel,
    KinematicObservation,
    Outcome,
    TriageLevel,
)

UNKNOWN_EXERCISE_ID = "unknown"
"""Always-legal ``exercise_id`` meaning "could not be resolved"; the extractor must never guess."""

EXERCISE_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"
"""Character set of free-exercise-db ids (e.g. ``Barbell_Bench_Press_-_Medium_Grip``)."""

VALUE_ID_PATTERN = r"^v_[a-z0-9_]+_\d{4,}$"
"""Format of tool value ids: ``v_<name>_<NNNN>`` (issue D3, ``ValueIdFactory``)."""

EXERCISE_IDS_CONTEXT_KEY = "exercise_ids"
"""Validation-context key holding the loader's id set, e.g.
``ExtractionResult.model_validate(data, context={"exercise_ids": ids})``."""

_EXERCISE_ID_RE = re.compile(EXERCISE_ID_PATTERN)
_VALUE_ID_RE = re.compile(VALUE_ID_PATTERN)


def _check_exercise_id(value: str, info: ValidationInfo) -> str:
    """Validate an exercise id structurally and, if the context carries an id set, by membership."""
    if value == UNKNOWN_EXERCISE_ID:
        return value
    if not _EXERCISE_ID_RE.fullmatch(value):
        raise ValueError(f"exercise_id {value!r} is not a valid free-exercise-db id or 'unknown'")
    known: Collection[str] | None = (info.context or {}).get(EXERCISE_IDS_CONTEXT_KEY)
    if known is not None and value not in known:
        raise ValueError(f"exercise_id {value!r} is not in the provided exercise id set")
    return value


class _StrictModel(BaseModel):
    """Base: unknown keys are rejected so the extractor cannot smuggle extra fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Load(_StrictModel):
    """A load as reported by the user, in the user's unit (conversion to kg happens in ingest)."""

    value: float = Field(ge=0, description="Load magnitude; 0 is allowed for bodyweight-only sets.")
    unit: Literal["kg", "lb"]


class ExtractionResult(_StrictModel):
    """Structured extraction of one note or free-text message (plan §6.3)."""

    exercise_id: str = Field(description="free-exercise-db id, or 'unknown' when the exercise cannot be resolved.")
    kinematic_observation: KinematicObservation = Field(
        description="What the user reported about the movement; never a form diagnosis."
    )
    load: Load | None = None
    reps: int | None = Field(default=None, ge=0)
    outcome: Outcome
    rpe: float | None = Field(default=None, ge=0, le=10)
    triage_level: TriageLevel

    @field_validator("exercise_id")
    @classmethod
    def _validate_exercise_id(cls, value: str, info: ValidationInfo) -> str:
        return _check_exercise_id(value, info)


class Claim(_StrictModel):
    """One structured claim emitted by the agent (plan §5.8).

    ``numbers`` hold tool value ids and ``citations`` hold knowledge chunk ids. The verifier checks
    that both exist in this run and that every digit in ``text`` matches a referenced value.
    """

    hypothesis_label: HypothesisLabel
    evidence_level: EvidenceLevel
    exercise_id: str | None = None
    numbers: list[str] = Field(default_factory=list, description="Tool value ids, format v_<name>_<NNNN>.")
    citations: list[str] = Field(default_factory=list, description="Knowledge chunk ids, e.g. syn03#c04.")
    text: str = Field(min_length=1)

    @field_validator("exercise_id")
    @classmethod
    def _validate_exercise_id(cls, value: str | None, info: ValidationInfo) -> str | None:
        return None if value is None else _check_exercise_id(value, info)

    @field_validator("numbers")
    @classmethod
    def _validate_value_ids(cls, value: list[str]) -> list[str]:
        bad = [v for v in value if not _VALUE_ID_RE.fullmatch(v)]
        if bad:
            raise ValueError(f"value ids must match {VALUE_ID_PATTERN}: {bad}")
        return value

    @field_validator("citations")
    @classmethod
    def _validate_citations(cls, value: list[str]) -> list[str]:
        bad = [c for c in value if not c or any(ch.isspace() for ch in c)]
        if bad:
            raise ValueError(f"chunk ids must be non-empty and contain no whitespace: {bad}")
        return value
