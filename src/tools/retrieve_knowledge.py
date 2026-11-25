"""Tool: ``retrieve_knowledge`` (issue M6, #37; plan §5.4, §5.7).

Enforces the knowledge-retrieval boundary:
1. Rejects symptom/pain/injury queries, using the filter in ``configs/retrieval_filter.yaml`` **and** the safety-gate
   rules, returning ``ToolError(code="rejected_query")``.
2. Enforces orchestrator-supplied ``allowed_exercise_ids`` and ``allowed_hypotheses``:
   - When ``allowed_exercise_ids`` is empty (red gate), returns empty ``KnowledgeResult(chunks=[])``.
   - Only chunks whose ``topic_tags`` map to ``allowed_hypotheses`` are returned.
   - Chunks whose ``exercise_ids`` intersect an excluded exercise (or fall outside
     ``allowed_exercise_ids``) are never returned.
   - Queries naming an excluded exercise or body-part joint associated with an excluded exercise
     return an empty result.
3. Empty result is a valid, normal outcome.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from src.gate.rules import assess_text
from src.rag.retrieve import HybridRetriever, RetrievalMode
from src.schemas import TriageLevel
from src.tools.common import ToolError

TOOL_VERSION = "retrieve_knowledge-1.0.0"

TOOL_DESCRIPTION = (
    "Retrieve cited training-science synthesis chunks for allowed hypotheses and exercises. "
    "Precondition: allowed_exercise_ids and allowed_hypotheses are injected by the orchestrator "
    "from the safety gate (never chosen by the agent). Symptom, pain, or injury queries are "
    "rejected with ToolError('rejected_query'). An empty chunks list is a valid outcome "
    "(e.g., under red safety gate, excluded exercises, or when no synthesis chunk matches) "
    "and means no citation is available for that query."
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILTER_CONFIG = REPO_ROOT / "configs" / "retrieval_filter.yaml"
TOPICS_CONFIG = REPO_ROOT / "configs" / "hypothesis_topics.yaml"
"""Shared with the output verifier, so retrieval and verification cannot drift apart."""

# Joint / body-part terms commonly appearing in yellow-gate symptom notes
_BODY_PART_TERMS: frozenset[str] = frozenset(
    {
        "knee",
        "knees",
        "elbow",
        "elbows",
        "wrist",
        "wrists",
        "ankle",
        "ankles",
        "hip",
        "hips",
        "groin",
        "rotator",
        "tendon",
        "ligament",
        "meniscus",
        "lumbar",
        "spine",
        "disc",
        "joint",
        "joints",
    }
)


class KnowledgeChunk(BaseModel):
    """Single retrieved synthesis chunk with citation keys."""

    chunk_id: str
    text: str
    citation_keys: list[str] = Field(default_factory=list)


class KnowledgeResult(BaseModel):
    """Structured output of ``retrieve_knowledge``. Empty ``chunks`` is a valid outcome."""

    tool_version: str = TOOL_VERSION
    chunks: list[KnowledgeChunk] = Field(default_factory=list)


def load_retrieval_filter_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load rejected regex patterns and hypothesis->tag mapping from YAML."""
    target = Path(path) if path is not None else DEFAULT_FILTER_CONFIG
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    patterns = list(raw["rejected_patterns"])
    if not patterns:
        raise ValueError(f"{target}: the symptom filter must not be empty")
    return {
        "rejected_patterns": patterns,
        "hypothesis_to_topic_tags": yaml.safe_load(TOPICS_CONFIG.read_text(encoding="utf-8")),
    }


def _matches_rejected_query(query: str, patterns: Sequence[str]) -> str | None:
    lower = query.lower()
    for pat in patterns:
        if re.search(pat, lower):
            return pat
    return None


def _tokens(text: str) -> set[str]:
    """Lowercase words without a plural "s", so that "squats" equals "squat"."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words}


def _query_mentions_excluded(
    query: str,
    excluded_exercise_ids: Sequence[str] | None,
) -> bool:
    if not excluded_exercise_ids:
        return False
    q_tokens = _tokens(query)
    # If any exercise was excluded by a yellow note, block queries mentioning anatomical joints
    if q_tokens & _tokens(" ".join(_BODY_PART_TERMS)):
        return True
    # Also block queries naming any distinctive token of an excluded exercise id
    generic_equipment = {"barbell", "dumbbell", "cable", "machine", "smith", "lever", "grip", "medium", "wide", "close", "seated", "standing", "incline", "decline", "with"}
    for ex_id in excluded_exercise_ids:
        ex_tokens = _tokens(ex_id.replace("_", " ").replace("-", " ")) - generic_equipment
        if ex_tokens and (q_tokens & ex_tokens):
            return True
    return False


def retrieve_knowledge(
    query: str,
    allowed_exercise_ids: Sequence[str],
    allowed_hypotheses: Sequence[str],
    k: int = 5,
    *,
    retriever: HybridRetriever | None = None,
    excluded_exercise_ids: Sequence[str] | None = None,
    filter_config: Mapping[str, Any] | None = None,
    mode: RetrievalMode = "hybrid",
) -> KnowledgeResult | ToolError:
    """Retrieve synthesis chunks strictly within the gate's allowed sets (plan §5.4)."""
    cfg = dict(load_retrieval_filter_config())
    if filter_config is not None:
        cfg.update(filter_config)

    # 1. Rule filter: reject symptom / pain / injury queries
    matched_pat = _matches_rejected_query(query, cfg["rejected_patterns"])
    if matched_pat is not None or assess_text(query).level is not TriageLevel.GREEN:
        return ToolError(
            code="rejected_query",
            message=(
                "Query rejected by medical-safety filter: pain, injury, and symptom queries "
                "are out of scope for knowledge retrieval."
            ),
        )

    # 2. Red gate or no allowed hypotheses -> empty result (valid outcome)
    allowed_ex = list(allowed_exercise_ids)
    if not allowed_ex or not allowed_hypotheses or k <= 0:
        return KnowledgeResult(chunks=[])

    # 3. Yellow exclusion guard: block queries naming an excluded exercise or anatomical joint
    if _query_mentions_excluded(query, excluded_exercise_ids):
        return KnowledgeResult(chunks=[])

    # 4. Map allowed_hypotheses -> allowed topic_tags
    hyp_to_tags: Mapping[str, Sequence[str]] = cfg["hypothesis_to_topic_tags"]
    allowed_tags: set[str] = set()
    for hyp in allowed_hypotheses:
        allowed_tags.update(hyp_to_tags.get(hyp, ()))
    if not allowed_tags:
        return KnowledgeResult(chunks=[])

    if retriever is None:
        return KnowledgeResult(chunks=[])

    where: dict[str, Any] = {
        "corpus": "synthesis",
        "topic_tags_any": sorted(allowed_tags),
        "allowed_exercise_ids": allowed_ex,
    }
    if excluded_exercise_ids:
        where["exclude_exercise_ids"] = list(excluded_exercise_ids)

    hits = retriever.retrieve(query, k=k, mode=mode, where=where)

    chunks = [
        KnowledgeChunk(
            chunk_id=h.chunk_id,
            text=h.text,
            citation_keys=list(h.metadata.get("citation_keys") or []),
        )
        for h in hits
    ]
    return KnowledgeResult(chunks=chunks)
