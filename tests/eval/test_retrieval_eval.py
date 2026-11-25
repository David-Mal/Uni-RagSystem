"""Offline unit tests for retrieval evaluation metrics and E1 pruning (issue M7, #38)."""

from __future__ import annotations

from pathlib import Path

from src.exercises.loader import load_exercises
from src.eval.retrieval import (
    is_chunk_relevant,
    load_dev_queries,
    rank_variants_with_size_tiebreak,
    spans_overlap,
)
from src.rag.store import ScoredChunk

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dev_queries_jsonl_has_20_well_formed_entries() -> None:
    queries = load_dev_queries(REPO_ROOT / "data" / "dev" / "rag_queries.jsonl")
    assert len(queries) == 20
    syn = [q for q in queries if q["corpus"] == "synthesis"]
    ex = [q for q in queries if q["corpus"] == "exercises"]
    assert len(syn) == 10
    assert len(ex) == 10
    for q in syn:
        assert q["doc_id"]
        assert q["char_end"] > q["char_start"]
    for q in ex:
        assert q["exercise_id"]


def test_span_overlap_chunking_independent() -> None:
    assert spans_overlap(100, 300, 250, 400) is True
    assert spans_overlap(100, 250, 250, 400) is False
    assert spans_overlap(260, 280, 100, 500) is True


def test_is_chunk_relevant_for_both_corpora() -> None:
    syn_chunk = ScoredChunk(
        chunk_id="syn01#c01",
        text="...",
        score=0.9,
        metadata={"doc_id": "syn01", "char_start": 200, "char_end": 800},
    )
    assert is_chunk_relevant(
        syn_chunk, {"corpus": "synthesis", "doc_id": "syn01", "char_start": 265, "char_end": 760}
    )
    assert not is_chunk_relevant(
        syn_chunk, {"corpus": "synthesis", "doc_id": "syn02", "char_start": 265, "char_end": 760}
    )
    assert not is_chunk_relevant(
        syn_chunk, {"corpus": "synthesis", "doc_id": "syn01", "char_start": 900, "char_end": 1200}
    )

    ex_chunk = ScoredChunk(
        chunk_id="Barbell_Squat",
        text="...",
        score=0.9,
        metadata={"exercise_id": "Barbell_Squat"},
    )
    assert is_chunk_relevant(ex_chunk, {"corpus": "exercises", "exercise_id": "Barbell_Squat"})
    assert not is_chunk_relevant(ex_chunk, {"corpus": "exercises", "exercise_id": "Pullups"})


def test_ties_go_to_smaller_model() -> None:
    rows = [
        {"embedder": "BAAI/bge-small-en-v1.5", "params_m": 33.4, "chunking": "heading", "mode": "hybrid", "recall_at_3": 1.0, "recall_at_5": 1.0, "mrr": 0.9},
        {"embedder": "sentence-transformers/all-MiniLM-L6-v2", "params_m": 22.7, "chunking": "heading", "mode": "hybrid", "recall_at_3": 1.0, "recall_at_5": 1.0, "mrr": 0.9},
    ]
    ranked = rank_variants_with_size_tiebreak(rows)
    assert ranked[0]["embedder"] == "sentence-transformers/all-MiniLM-L6-v2"


def test_dev_spans_are_whole_paragraphs_of_the_committed_documents() -> None:
    root = Path(__file__).resolve().parents[2]
    docs = {p.name.split("-")[0]: p.read_text(encoding="utf-8") for p in (root / "docs" / "knowledge").glob("syn*.md")}
    for q in load_dev_queries(root / "data" / "dev" / "rag_queries.jsonl"):
        if q["corpus"] != "synthesis":
            continue
        text = docs[q["doc_id"]]
        assert text[q["char_start"] - 2 : q["char_start"]] == "\n\n", q["query_id"]
        assert text[q["char_end"] :].strip() == "" or text[q["char_end"] : q["char_end"] + 2] == "\n\n", q["query_id"]


def test_dev_exercise_labels_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    ids = set(load_exercises())
    queries = load_dev_queries(root / "data" / "dev" / "rag_queries.jsonl")
    assert {q["exercise_id"] for q in queries if q["corpus"] == "exercises"} <= ids
