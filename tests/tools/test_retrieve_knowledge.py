"""Boundary tests for retrieve_knowledge (issue M6, #37; plan §5.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rag.bm25 import BM25Index
from src.rag.build import build_index
from src.rag.retrieve import HybridRetriever
from src.rag.store import ChromaVectorStore, HashEmbedder
from src.tools._common_provisional import ToolError
from src.tools.retrieve_knowledge import KnowledgeResult, retrieve_knowledge

TEST_KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge"


@pytest.fixture
def test_retriever(tmp_path: Path) -> HybridRetriever:
    embedder = HashEmbedder()
    index_dir = tmp_path / "idx"
    build_index(
        index_dir=index_dir,
        embedder=embedder,
        synthesis_dir=TEST_KNOWLEDGE_DIR,
        include_exercises=False,
        include_synthesis=True,
    )
    store = ChromaVectorStore(index_dir / "chroma", embedder)
    bm25 = BM25Index.load(index_dir / "bm25_chunks.json")
    return HybridRetriever(store, bm25)


@pytest.mark.parametrize(
    "query",
    [
        "sharp knee pain during squat",
        "shoulder injury recovery exercises",
        "my lower back hurts after deadlift",
        "hamstring strain treatment",
        "swelling around the elbow joint",
    ],
)
def test_symptom_pain_injury_queries_are_rejected(
    test_retriever: HybridRetriever, query: str
) -> None:
    res = retrieve_knowledge(
        query=query,
        allowed_exercise_ids=["Barbell_Bench_Press_-_Medium_Grip"],
        allowed_hypotheses=["insufficient_weekly_volume"],
        retriever=test_retriever,
    )
    assert isinstance(res, ToolError)
    assert res.code == "rejected_query"


def test_yellow_knee_note_on_squat_returns_nothing_for_squat_or_knee(
    test_retriever: HybridRetriever,
) -> None:
    # Gate excluded Barbell_Squat (yellow knee note); only Bench Press is allowed
    allowed = ["Barbell_Bench_Press_-_Medium_Grip"]
    excluded = ["Barbell_Squat"]
    hypotheses = ["stagnant_load_progression", "fatigue_accumulation", "insufficient_weekly_volume"]

    res_squat = retrieve_knowledge(
        query="squat RPE progression",
        allowed_exercise_ids=allowed,
        allowed_hypotheses=hypotheses,
        excluded_exercise_ids=excluded,
        retriever=test_retriever,
    )
    assert isinstance(res_squat, KnowledgeResult)
    assert res_squat.chunks == []

    res_knee = retrieve_knowledge(
        query="knee stability during heavy lower body training",
        allowed_exercise_ids=allowed,
        allowed_hypotheses=hypotheses,
        excluded_exercise_ids=excluded,
        retriever=test_retriever,
    )
    assert isinstance(res_knee, KnowledgeResult)
    assert res_knee.chunks == []


def test_allowed_query_returns_chunks_with_citation_keys(
    test_retriever: HybridRetriever,
) -> None:
    res = retrieve_knowledge(
        query="weekly effective sets volume for strength",
        allowed_exercise_ids=["Barbell_Bench_Press_-_Medium_Grip"],
        allowed_hypotheses=["insufficient_weekly_volume"],
        retriever=test_retriever,
    )
    assert isinstance(res, KnowledgeResult)
    assert len(res.chunks) == 1
    assert res.chunks[0].chunk_id == "syn_vol#c01"
    assert res.chunks[0].citation_keys == ["ralston2017"]


def test_disallowed_hypothesis_filters_out_unmatched_topic_tags(
    test_retriever: HybridRetriever,
) -> None:
    # Only allow confounders; volume doc should NOT be returned
    res = retrieve_knowledge(
        query="weekly effective sets volume",
        allowed_exercise_ids=["Barbell_Bench_Press_-_Medium_Grip"],
        allowed_hypotheses=["confounder_present"],
        retriever=test_retriever,
    )
    assert isinstance(res, KnowledgeResult)
    assert res.chunks == []


def test_red_gate_empty_allowed_exercises_returns_nothing(
    test_retriever: HybridRetriever,
) -> None:
    res = retrieve_knowledge(
        query="weekly effective sets volume",
        allowed_exercise_ids=[],
        allowed_hypotheses=["insufficient_weekly_volume"],
        retriever=test_retriever,
    )
    assert isinstance(res, KnowledgeResult)
    assert res.chunks == []
