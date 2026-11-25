"""Tool: ``match_exercise_rag`` — 4-stage exercise name resolution cascade (issue M1, #32).

Stages:
1. Alias dictionary lookup (``data/exercises/aliases.yaml``) on normalized names.
2. Fuzzy matching (rapidfuzz ``token_set_ratio``) against exercise names and aliases.
3. Retrieval over free-exercise-db documents via the ``Retriever`` protocol (M5).
4. Low confidence -> ``exercise_id = "unknown"`` (never guess).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from src.exercises.loader import Exercise, load_exercises

TOOL_VERSION = "match_exercise_rag-0.1.0"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALIASES_PATH = REPO_ROOT / "data" / "exercises" / "aliases.yaml"
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "matching.yaml"

MatchStage = Literal["alias", "fuzzy", "retrieval", "unknown"]

_PARENS_RE = re.compile(r"\([^)]*\)")
_PUNCT_RE = re.compile(r"[^a-z0-9\s]+")
_SPACE_RE = re.compile(r"\s+")


class Candidate(BaseModel):
    """Candidate exercise match with similarity or retrieval score."""

    exercise_id: str
    score: float
    name: str | None = None


class MatchResult(BaseModel):
    """Structured output of ``match_exercise_rag`` with stage attribution for E2."""

    exercise_id: str
    stage: MatchStage
    score: float
    candidates: list[Candidate] = Field(default_factory=list)
    tool_version: str = TOOL_VERSION


class Retriever(Protocol):
    """Protocol implemented by the M5 hybrid retriever over exercise documents."""

    def retrieve(self, query: str, k: int = 5) -> list[Candidate]:
        """Return top-k exercise candidates ordered by descending score."""
        ...


class StubRetriever:
    """No-op retriever used when M5 is not wired in."""

    def retrieve(self, query: str, k: int = 5) -> list[Candidate]:
        return []


def normalize_exercise_name(raw: str) -> str:
    """Lowercase, strip parenthetical equipment/modifiers, strip punctuation, collapse spaces."""
    without_parens = _PARENS_RE.sub(" ", raw.lower())
    without_punct = _PUNCT_RE.sub(" ", without_parens)
    return _SPACE_RE.sub(" ", without_punct).strip()


def load_matching_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load matching thresholds from ``configs/matching.yaml``."""
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with target.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {
        "fuzzy_threshold": float(data.get("fuzzy_threshold", 90.0)),
        "retrieval_threshold": float(data.get("retrieval_threshold", 0.65)),
        "top_k": int(data.get("top_k", 5)),
    }


def load_aliases(
    path: Path | str | None = None,
    *,
    exercises: Mapping[str, Exercise] | None = None,
) -> dict[str, str]:
    """Load alias dictionary keyed by normalized alias string -> exercise_id."""
    target = Path(path) if path is not None else DEFAULT_ALIASES_PATH
    with target.open("r", encoding="utf-8") as fh:
        raw_doc = yaml.safe_load(fh) or {}
    raw_aliases: Mapping[str, str] = raw_doc.get("aliases", raw_doc)
    valid_ids = set(exercises.keys()) if exercises is not None else None

    normalized: dict[str, str] = {}
    for alias, ex_id in raw_aliases.items():
        if valid_ids is not None and ex_id not in valid_ids:
            raise ValueError(f"Alias {alias!r} maps to unknown exercise_id {ex_id!r}")
        key = normalize_exercise_name(str(alias))
        if key:
            normalized[key] = str(ex_id)
    return normalized


def match_exercise_rag(
    name: str,
    *,
    exercises: Mapping[str, Exercise] | None = None,
    aliases: Mapping[str, str] | None = None,
    retriever: Retriever | None = None,
    config: Mapping[str, Any] | None = None,
) -> MatchResult:
    """Resolve a raw exercise name string to a free-exercise-db ``exercise_id`` or ``"unknown"``."""
    ex_map = exercises if exercises is not None else load_exercises()
    cfg = dict(load_matching_config()) if config is None else {
        "fuzzy_threshold": float(config.get("fuzzy_threshold", 90.0)),
        "retrieval_threshold": float(config.get("retrieval_threshold", 0.65)),
        "top_k": int(config.get("top_k", 5)),
    }
    alias_map = (
        {normalize_exercise_name(k): v for k, v in aliases.items() if normalize_exercise_name(k)}
        if aliases is not None
        else load_aliases(exercises=ex_map)
    )
    active_retriever: Retriever = retriever if retriever is not None else StubRetriever()

    norm_query = normalize_exercise_name(name)
    if not norm_query:
        return MatchResult(exercise_id="unknown", stage="unknown", score=0.0, candidates=[])

    # Stage 1: Exact normalized alias dictionary lookup (or exact canonical exercise name)
    if norm_query in alias_map:
        matched_id = alias_map[norm_query]
        matched_name = ex_map[matched_id].name if matched_id in ex_map else None
        return MatchResult(
            exercise_id=matched_id,
            stage="alias",
            score=100.0,
            candidates=[Candidate(exercise_id=matched_id, score=100.0, name=matched_name)],
        )

    for ex_id, ex in ex_map.items():
        if normalize_exercise_name(ex.name) == norm_query:
            return MatchResult(
                exercise_id=ex_id,
                stage="alias",
                score=100.0,
                candidates=[Candidate(exercise_id=ex_id, score=100.0, name=ex.name)],
            )

    # Stage 2: Fuzzy matching with rapidfuzz token_set_ratio against exercise names and aliases
    fuzzy_threshold = cfg["fuzzy_threshold"]
    top_k = cfg["top_k"]

    best_score_by_id: dict[str, float] = {}
    for ex_id, ex in ex_map.items():
        norm_target = normalize_exercise_name(ex.name)
        score = float(fuzz.token_set_ratio(norm_query, norm_target))
        if score > best_score_by_id.get(ex_id, -1.0):
            best_score_by_id[ex_id] = score

    for norm_alias, ex_id in alias_map.items():
        score = float(fuzz.token_set_ratio(norm_query, norm_alias))
        if score > best_score_by_id.get(ex_id, -1.0):
            best_score_by_id[ex_id] = score

    ranked_fuzzy = sorted(
        best_score_by_id.items(),
        key=lambda item: (-item[1], item[0]),
    )[:top_k]

    fuzzy_candidates = [
        Candidate(
            exercise_id=ex_id,
            score=round(score, 4),
            name=ex_map[ex_id].name if ex_id in ex_map else None,
        )
        for ex_id, score in ranked_fuzzy
    ]

    if fuzzy_candidates and fuzzy_candidates[0].score >= fuzzy_threshold:
        top = fuzzy_candidates[0]
        return MatchResult(
            exercise_id=top.exercise_id,
            stage="fuzzy",
            score=top.score,
            candidates=fuzzy_candidates,
        )

    # Stage 3: Hybrid retrieval over exercise documents (M5)
    retrieval_threshold = cfg["retrieval_threshold"]
    retrieved = active_retriever.retrieve(name, k=top_k)
    if retrieved:
        top_ret = retrieved[0]
        if top_ret.score >= retrieval_threshold:
            return MatchResult(
                exercise_id=top_ret.exercise_id,
                stage="retrieval",
                score=round(float(top_ret.score), 4),
                candidates=list(retrieved[:top_k]),
            )

    # Stage 4: Low confidence -> unknown (never guess)
    best_candidates = list(retrieved[:top_k]) if retrieved else fuzzy_candidates
    best_score = best_candidates[0].score if best_candidates else 0.0
    return MatchResult(
        exercise_id="unknown",
        stage="unknown",
        score=best_score,
        candidates=best_candidates,
    )
