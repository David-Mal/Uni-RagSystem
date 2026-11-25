"""Boundary tests for retrieve_knowledge (issue M6, #37; plan §5.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rag.bm25 import BM25Index
from src.rag.build import build_index
from src.rag.retrieve import HybridRetriever
from src.rag.store import ChromaVectorStore, HashEmbedder
from src.schemas import HypothesisLabel
from src.tools.common import ToolError
from src.tools.retrieve_knowledge import KnowledgeResult, load_retrieval_filter_config, retrieve_knowledge

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
        "achy elbow on bench",
        "soreness and training volume",
        "stiff back warm up",
        "pins and needles in the hand",
        "felt light-headed after a set",
        "my vision went dark",
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


@pytest.mark.parametrize("query", ["squats RPE progression", "SQUAT volume", "knees and progression", "barbell squat"])
def test_plural_and_case_do_not_bypass_the_exclusion(test_retriever: HybridRetriever, query: str) -> None:
    res = retrieve_knowledge(
        query=query,
        allowed_exercise_ids=["Barbell_Bench_Press_-_Medium_Grip"],
        allowed_hypotheses=[h.value for h in HypothesisLabel],
        excluded_exercise_ids=["Barbell_Squat"],
        retriever=test_retriever,
    )
    assert isinstance(res, KnowledgeResult) and res.chunks == []


def test_chunks_of_exercises_outside_the_allowed_set_are_never_returned(test_retriever: HybridRetriever) -> None:
    # Also when the caller does not pass the excluded list
    res = retrieve_knowledge(
        query="tracking RPE across sessions at comparable load",
        allowed_exercise_ids=["Barbell_Bench_Press_-_Medium_Grip"],
        allowed_hypotheses=[h.value for h in HypothesisLabel],
        retriever=test_retriever,
    )
    assert isinstance(res, KnowledgeResult)
    assert all(c.chunk_id != "syn_squat#c01" for c in res.chunks)


def test_every_hypothesis_has_topics() -> None:
    cfg = load_retrieval_filter_config()
    assert set(cfg["hypothesis_to_topic_tags"]) == {h.value for h in HypothesisLabel}


def test_missing_or_empty_filter_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_retrieval_filter_config(tmp_path / "nope.yaml")
    path = tmp_path / "f.yaml"
    path.write_text("rejected_patterns: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_retrieval_filter_config(path)
