"""Tool: ``match_exercise_rag`` — 4-stage exercise name resolution cascade (issue M1, #32).

Stages:
1. Alias dictionary (``data/exercises/aliases.yaml``) or exact exercise name, word order ignored. Text in parentheses is
   part of the name; it is dropped only if it is nothing but equipment that the matched exercise really uses.
2. Fuzzy matching (rapidfuzz) against exercise names and aliases. ``token_set_ratio`` alone is 100 for any subset
   ("Row" in every row), so ``token_sort_ratio`` must be high too, the equipment must agree, and the best candidate must
   be clearly ahead of the next one.
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

TOOL_VERSION = "match_exercise_rag-1.0.0"

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


EQUIPMENT_WORDS: dict[str, str] = {
    "barbell": "barbell", "bb": "barbell", "dumbbell": "dumbbell", "dumbbells": "dumbbell", "db": "dumbbell",
    "cable": "cable", "machine": "machine", "smith": "machine", "lever": "machine", "kettlebell": "kettlebells",
    "kb": "kettlebells", "band": "bands", "bands": "bands", "bodyweight": "body only", "bw": "body only",
}  # fmt: skip
"""Words in app names -> ``equipment`` values of free-exercise-db."""

_COMPATIBLE = {("barbell", "e-z curl bar")}


def _clean(text: str) -> str:
    return _SPACE_RE.sub(" ", _PUNCT_RE.sub(" ", text.lower())).strip()


def normalize_exercise_name(raw: str) -> str:
    """Lowercase, strip parenthetical equipment/modifiers, strip punctuation, collapse spaces."""
    return _clean(_PARENS_RE.sub(" ", raw))


def normalize_full_name(raw: str) -> str:
    """Like ``normalize_exercise_name``, but the words in parentheses are kept."""
    return _clean(raw)


def _key(normalized: str) -> tuple[str, ...]:
    """Word-order independent key, so "Bench Press (Dumbbell)" equals "Dumbbell Bench Press"."""
    return tuple(sorted(normalized.split()))


def _equipment(normalized: str) -> set[str]:
    return {EQUIPMENT_WORDS[w] for w in normalized.split() if w in EQUIPMENT_WORDS}


def _equipment_agrees(named: set[str], exercise: Exercise | None) -> bool:
    """False if the name mentions equipment and the exercise uses something else."""
    if not named or exercise is None or exercise.equipment is None:
        return True
    return any(n == exercise.equipment or (n, exercise.equipment) in _COMPATIBLE for n in named)


def _adds_equipment(query: str, target: str) -> bool:
    """True if ``target`` names equipment that ``query`` does not (typos such as "Barbel" count as named)."""
    words = query.split()
    return any(
        w in EQUIPMENT_WORDS
        and EQUIPMENT_WORDS[w] not in _equipment(query)
        and not any(fuzz.ratio(w, q) >= 85 for q in words)
        for w in target.split()
    )


def _droppable_parens(raw: str) -> bool:
    """True if every word in parentheses names equipment."""
    words = " ".join(_PARENS_RE.findall(raw.lower()))
    inside = _clean(words).split()
    return bool(inside) and all(w in EQUIPMENT_WORDS for w in inside)


def load_matching_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load matching thresholds from ``configs/matching.yaml``."""
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with target.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {
        "fuzzy_threshold": float(data.get("fuzzy_threshold", 90.0)),
        "fuzzy_min_sort": float(data.get("fuzzy_min_sort", 80.0)),
        "fuzzy_margin": float(data.get("fuzzy_margin", 3.0)),
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
        key = normalize_full_name(str(alias))
        if normalized.get(key, ex_id) != ex_id:
            raise ValueError(f"Alias {alias!r} maps to both {normalized[key]!r} and {ex_id!r}")
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
    cfg = {**load_matching_config(), **(config or {})}
    alias_map = (
        {normalize_full_name(k): v for k, v in aliases.items() if normalize_full_name(k)}
        if aliases is not None
        else load_aliases(exercises=ex_map)
    )
    active_retriever: Retriever = retriever if retriever is not None else StubRetriever()

    norm_query = normalize_full_name(name)
    if not norm_query:
        return MatchResult(exercise_id="unknown", stage="unknown", score=0.0, candidates=[])
    named_equipment = _equipment(norm_query)

    # Stage 1: alias or exact exercise name, word order ignored. Aliases win over names.
    exact: dict[tuple[str, ...], str] = {_key(normalize_full_name(ex.name)): i for i, ex in ex_map.items()}
    exact.update({_key(alias): i for alias, i in alias_map.items()})
    matched_id = exact.get(_key(norm_query))
    if matched_id is None and _droppable_parens(name):
        stripped = exact.get(_key(normalize_exercise_name(name)))
        if stripped is not None and _equipment_agrees(named_equipment, ex_map.get(stripped)):
            matched_id = stripped
    if matched_id is not None:
        matched_name = ex_map[matched_id].name if matched_id in ex_map else None
        return MatchResult(
            exercise_id=matched_id,
            stage="alias",
            score=100.0,
            candidates=[Candidate(exercise_id=matched_id, score=100.0, name=matched_name)],
        )

    # Stage 2: fuzzy matching against exercise names and aliases
    top_k = int(cfg["top_k"])
    best: dict[str, tuple[float, float]] = {}  # exercise_id -> (sort ratio, set ratio)
    targets = [(normalize_full_name(ex.name), i) for i, ex in ex_map.items()]
    targets += list(alias_map.items())
    for target, ex_id in targets:
        if _adds_equipment(norm_query, target) or not _equipment_agrees(named_equipment, ex_map.get(ex_id)):
            continue
        set_score = float(fuzz.token_set_ratio(norm_query, target))
        sort_score = float(fuzz.token_sort_ratio(norm_query, target))
        best[ex_id] = max(best.get(ex_id, (-1.0, -1.0)), (sort_score, set_score))
    ranked = sorted(best.items(), key=lambda item: (-item[1][0], -item[1][1], item[0]))[:top_k]
    fuzzy_candidates = [
        Candidate(exercise_id=i, score=round(set_score, 4), name=ex_map[i].name if i in ex_map else None)
        for i, (_, set_score) in ranked
    ]
    if ranked:
        top_id, (top_sort, top_set) = ranked[0]
        runner_up = ranked[1][1][0] if len(ranked) > 1 else 0.0
        if (
            top_set >= float(cfg["fuzzy_threshold"])
            and top_sort >= float(cfg["fuzzy_min_sort"])
            and top_sort - runner_up >= float(cfg["fuzzy_margin"])
        ):
            return MatchResult(
                exercise_id=top_id, stage="fuzzy", score=round(top_set, 4), candidates=fuzzy_candidates
            )

    # Stage 3: Hybrid retrieval over exercise documents (M5)
    retrieval_threshold = float(cfg["retrieval_threshold"])
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


def match_exercise_id(name: str) -> str:
    """Exercise id or ``"unknown"``: the ``matcher`` argument of ``ingest_workout_log`` (stages 1-2)."""
    return match_exercise_rag(name).exercise_id
