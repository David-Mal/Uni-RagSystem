"""``output_verifier`` v0 (plan §5.8): exact-lookup checks of structured claims. Lives in the orchestrator, not in MCP."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.schemas import Claim, EvidenceLevel, HypothesisLabel
from src.tools.common import Value, load_indicator_config
from src.verifier.numbers import find_quantities, matches

TOPICS_PATH = Path(__file__).resolve().parents[2] / "configs" / "hypothesis_topics.yaml"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChunkInfo(BaseModel):
    """What the verifier needs to know about a knowledge chunk (the metadata written by the index build, M5)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    topic_tags: frozenset[str] = frozenset()
    exercise_ids: frozenset[str] = frozenset()


class VerificationError(_Model):
    """One problem, structured so that the retry prompt can list it. ``claim_index`` is ``None`` for the whole answer."""

    code: str
    claim_index: int | None
    message: str


class ClaimCheck(_Model):
    """Result for one claim."""

    claim_index: int
    ok: bool
    errors: tuple[VerificationError, ...] = ()


class VerificationResult(_Model):
    """``ok`` only if there is at least one claim and every claim passes."""

    ok: bool
    errors: tuple[VerificationError, ...] = Field(default=())
    per_claim: tuple[ClaimCheck, ...] = Field(default=())


@lru_cache(maxsize=1)
def hypothesis_topics() -> dict[str, frozenset[str]]:
    """Allowed topic tags per hypothesis label. Every label must be listed."""
    with TOPICS_PATH.open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream)
    if set(raw) != {h.value for h in HypothesisLabel}:
        raise ValueError("hypothesis_topics.yaml must list exactly the hypothesis labels")
    return {label: frozenset(tags) for label, tags in raw.items()}


def parse_claim(raw: Claim | Mapping[str, Any]) -> Claim | list[tuple[str, str]]:
    """Return the claim, or (code, message) pairs if it does not fit the schema."""
    if isinstance(raw, Claim):
        return raw
    try:
        return Claim.model_validate(raw)
    except ValidationError as exc:
        codes = {"hypothesis_label": "bad_label", "evidence_level": "bad_evidence_level"}
        return [
            (codes.get(str(e["loc"][0]) if e["loc"] else "", "invalid_claim"), f"{'.'.join(map(str, e['loc']))}: {e['msg']}")
            for e in exc.errors()
        ]


def verify(
    claims: Sequence[Claim | Mapping[str, Any]],
    value_store: Mapping[str, Value],
    chunk_store: Mapping[str, ChunkInfo | Mapping[str, Any]],
    allowed_exercise_ids: Collection[str],
    allowed_hypotheses: Collection[HypothesisLabel | str],
    *,
    config: Mapping[str, Any] | None = None,
) -> VerificationResult:
    """Check every claim against this run's values, the chunk store and the sets the gate allows.

    ``value_store`` holds the values of **this** run only. Claims may be raw JSON objects, so that a bad enum value
    becomes a structured error. The allowed sets come from the gate, never from the agent.
    """
    cfg = (config if config is not None else load_indicator_config())["verifier"]
    labels = {HypothesisLabel(h) for h in allowed_hypotheses}
    tags = frozenset().union(*(hypothesis_topics()[h.value] for h in labels))
    exercises = frozenset(allowed_exercise_ids)

    checks: list[ClaimCheck] = []
    for index, raw in enumerate(claims):
        claim = parse_claim(raw)
        if isinstance(claim, Claim):
            found = [
                *_check_labels(claim, labels, exercises),
                *_check_numbers(claim, value_store, cfg),
                *_check_citations(claim, chunk_store, exercises, tags),
            ]
        else:
            found = claim
        errors = tuple(VerificationError(code=c, claim_index=index, message=m) for c, m in found)
        checks.append(ClaimCheck(claim_index=index, ok=not errors, errors=errors))

    errors = tuple(e for c in checks for e in c.errors)
    if not checks:
        errors = (VerificationError(code="no_claims", claim_index=None, message="the answer contains no claims"),)
    return VerificationResult(ok=not errors, errors=errors, per_claim=tuple(checks))


def _check_labels(
    claim: Claim, labels: Collection[HypothesisLabel], exercises: Collection[str]
) -> Iterable[tuple[str, str]]:
    if claim.hypothesis_label not in labels:
        yield "hypothesis_not_allowed", f"hypothesis {claim.hypothesis_label.value} is not allowed for this log"
    if claim.exercise_id is not None and claim.exercise_id not in exercises:
        yield "exercise_not_allowed", f"exercise {claim.exercise_id} is not in the allowed set"


def _check_numbers(claim: Claim, store: Mapping[str, Value], cfg: Mapping[str, Any]) -> Iterable[tuple[str, str]]:
    for value_id in claim.numbers:
        if value_id not in store:
            yield "unknown_value_id", f"{value_id} is not a tool value of this run"
    referenced = [store[i] for i in claim.numbers if i in store]
    quantities, stray = find_quantities(claim.text, [*claim.numbers, *claim.citations])
    for q in quantities:
        if any(matches(q, v, cfg) for v in referenced):
            continue
        if q.unit == "lb":
            yield "wrong_unit", f"{q.raw!r}: values are in kg"
        elif referenced:
            yield "number_mismatch", f"{q.raw!r} does not match any referenced value"
        else:
            yield "unreferenced_number", f"{q.raw!r} appears in the text, but the claim references no value"
    for word in stray:
        yield "stray_digit", f"{word!r} contains a digit that is not a quotable number"


def _check_citations(
    claim: Claim,
    store: Mapping[str, ChunkInfo | Mapping[str, Any]],
    exercises: frozenset[str],
    tags: frozenset[str],
) -> Iterable[tuple[str, str]]:
    for chunk_id in claim.citations:
        if chunk_id not in store:
            yield "unknown_chunk", f"{chunk_id} does not exist in the knowledge base"
            continue
        raw = store[chunk_id]
        try:
            chunk = raw if isinstance(raw, ChunkInfo) else ChunkInfo.model_validate(raw)
        except ValidationError:
            yield "bad_chunk_metadata", f"{chunk_id}: topic tags or exercise ids are unreadable"
            continue
        if not chunk.topic_tags & tags:
            yield "citation_topic_not_allowed", f"{chunk_id}: no topic tag is allowed here"
        outside = sorted(chunk.exercise_ids - exercises)
        if outside:
            yield "citation_exercise_not_allowed", f"{chunk_id} is about excluded exercises: {', '.join(outside)}"


ABSTENTION = "No hypothesis could be verified against the data, so no explanation is given."

_LABEL_TEXT = {
    HypothesisLabel.INSUFFICIENT_WEEKLY_VOLUME: "Weekly training volume may be low.",
    HypothesisLabel.FATIGUE_ACCUMULATION: "Effort at comparable load may be rising.",
    HypothesisLabel.STAGNANT_LOAD_PROGRESSION: "The load may not be progressing.",
    HypothesisLabel.LOAD_SPIKE: "Recent load is high next to the weeks before (a heuristic, not an injury statement).",
    HypothesisLabel.INCONSISTENT_FREQUENCY: "Training may be irregular.",
    HypothesisLabel.LOGGING_QUALITY_ISSUE: "The log has quality problems that limit the analysis.",
    HypothesisLabel.CONFOUNDER_PRESENT: "The notes mention something else that may explain the result.",
}
_EVIDENCE_TEXT = {
    EvidenceLevel.SUPPORTED: "supported by the data",
    EvidenceLevel.WEAK: "weak evidence",
    EvidenceLevel.INSUFFICIENT: "insufficient evidence",
}


def fallback_template(
    claims: Sequence[Claim | Mapping[str, Any]], result: VerificationResult, value_store: Mapping[str, Value]
) -> str:
    """Answer built only from fixed texts and tool values, for the claims that passed ``verify``.

    The agent's own text is never used. Without any passing claim, the answer is the abstention text.
    """
    if len(claims) != len(result.per_claim):
        raise ValueError("the verification result does not belong to these claims")
    lines: list[str] = []
    for raw, check in zip(claims, result.per_claim, strict=True):
        claim = parse_claim(raw) if check.ok else None
        if not isinstance(claim, Claim):
            continue
        subject = f" [{claim.exercise_id}]" if claim.exercise_id else ""
        lines.append(f"- {_LABEL_TEXT[claim.hypothesis_label]}{subject} ({_EVIDENCE_TEXT[claim.evidence_level]})")
        lines.extend(f"  - {_show(value_store[i])}" for i in claim.numbers)
        if claim.citations:
            lines.append(f"  - Sources: {', '.join(claim.citations)}")
    return "\n".join(lines) if lines else ABSTENTION


def _show(value: Value) -> str:
    number = f"{value.value:.2f}".rstrip("0").rstrip(".") if isinstance(value.value, float) else str(value.value)
    number = "0" if number == "-0" else number
    return f"{value.name.replace('_', ' ')}: {number}{f' {value.unit}' if value.unit else ''}"
