"""Pydantic models for extraction results and agent claims (plan §3.3, §5.8, §6.3).

``ExtractionResult`` is the strict JSON the SLM extractor emits for one note or message; the golden
messages are labeled with the same model. ``Claim`` is one structured statement emitted by the agent
and checked by ``output_verifier``.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, field_validator

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

CHUNK_ID_PATTERN = r"^\S+$"
"""Knowledge chunk ids (e.g. ``syn03#c04``): non-empty, no whitespace. Existence is checked by the verifier."""

EXERCISE_IDS_CONTEXT_KEY = "exercise_ids"
"""Validation-context key holding the loader's id set, e.g.
``ExtractionResult.model_validate(data, context={"exercise_ids": ids})``."""

_EXERCISE_ID_RE = re.compile(EXERCISE_ID_PATTERN)

ValueId = Annotated[str, StringConstraints(pattern=VALUE_ID_PATTERN)]
ChunkId = Annotated[str, StringConstraints(pattern=CHUNK_ID_PATTERN)]


def _check_exercise_id(value: str, info: ValidationInfo) -> str:
    """Validate an exercise id structurally and, if the context carries an id set, by membership."""
    if value == UNKNOWN_EXERCISE_ID:
        return value
    if value.lower() == UNKNOWN_EXERCISE_ID:
        raise ValueError(f"exercise_id {value!r}: write 'unknown' in lowercase")
    if not _EXERCISE_ID_RE.fullmatch(value):
        raise ValueError(f"exercise_id {value!r} is not a valid free-exercise-db id or 'unknown'")
    known: Collection[str] | None = (info.context or {}).get(EXERCISE_IDS_CONTEXT_KEY)
    if isinstance(known, str):
        raise TypeError(f"context[{EXERCISE_IDS_CONTEXT_KEY!r}] must be a collection of ids, not a string")
    if known is not None and value not in known:
        raise ValueError(f"exercise_id {value!r} is not in the provided exercise id set")
    return value


class _StrictModel(BaseModel):
    """Base: unknown keys are rejected so the extractor cannot smuggle extra fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Load(_StrictModel):
    """A load as reported by the user, in the user's unit (conversion to kg happens in ingest)."""

    value: float = Field(
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="Load magnitude; 0 is allowed for bodyweight-only sets. Ints are accepted (80 -> 80.0).",
    )
    unit: Literal["kg", "lb"]


class ExtractionResult(_StrictModel):
    """Structured extraction of one note or free-text message (plan §6.3).

    All seven keys are required. ``load``, ``reps`` and ``rpe`` are ``null`` when not reported: never omitted and
    never 0 by default. Numbers are strict, so booleans, numeric strings and inf/NaN are rejected. Ints are accepted
    for float fields (8 -> 8.0).

    Multi-exercise messages (proposed in the #69 review; final wording in the Fi1 guideline): if a symptom is
    reported, ``exercise_id`` and the set fields describe the exercise linked to the most severe symptom. With no
    symptom, or a tie, they describe the first exercise that has set data. If that cannot be resolved, use
    ``unknown``. ``triage_level`` is always the maximum over the whole message.
    """

    exercise_id: str = Field(
        pattern=EXERCISE_ID_PATTERN,
        description="free-exercise-db id, or 'unknown' when the exercise cannot be resolved.",
    )
    kinematic_observation: KinematicObservation = Field(
        description="What the user reported about the movement; never a form diagnosis."
    )
    load: Load | None = Field(description="Reported load, or null when no load is stated.")
    reps: int | None = Field(ge=0, strict=True, description="Explicit repetition count, or null when not stated.")
    outcome: Outcome
    rpe: float | None = Field(
        ge=0, le=10, strict=True, allow_inf_nan=False, description="Explicit RPE (0-10), or null when not stated."
    )
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
    numbers: list[ValueId] = Field(default_factory=list, description="Tool value ids, format v_<name>_<NNNN>.")
    citations: list[ChunkId] = Field(default_factory=list, description="Knowledge chunk ids, e.g. syn03#c04.")
    text: str = Field(min_length=1)

    @field_validator("exercise_id")
    @classmethod
    def _validate_exercise_id(cls, value: str | None, info: ValidationInfo) -> str | None:
        return None if value is None else _check_exercise_id(value, info)

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


def read_triage_level(obj: Any) -> TriageLevel | None:
    """Return a valid ``triage_level`` from a raw extractor output even if other fields are invalid, else ``None``.

    Helper for the gate (D9, open point 5 in the #69 review): a red level should not be lost because another field
    (e.g. ``rpe: 11``) fails validation. Whether the gate uses it is D9's decision.
    """
    if not isinstance(obj, Mapping):
        return None
    value = obj.get("triage_level")
    return TriageLevel(value) if isinstance(value, str) and value in TriageLevel._value2member_map_ else None
