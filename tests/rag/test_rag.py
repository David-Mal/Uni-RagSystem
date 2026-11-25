"""Offline unit tests for Chroma + BM25 + RRF RAG index (issue M5, #36)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.exercises.loader import load_exercises
from src.rag.bm25 import BM25Index
from src.rag.build import build_index
from src.rag.corpus import load_approved_doc_ids, load_synthesis_chunks
from src.rag.retrieve import ExerciseRetriever, HybridRetriever, reciprocal_rank_fusion
from src.rag.store import (
    ChromaVectorStore,
    HashEmbedder,
    ScoredChunk,
    SentenceTransformerEmbedder,
)


def _write_sample_synthesis(syn_dir: Path) -> None:
    syn_dir.mkdir(parents=True, exist_ok=True)
    (syn_dir / "TAGS.md").write_text(
        "- `volume`\n- `rpe`\n- `progression`\n",
        encoding="utf-8",
    )
    (syn_dir / "approvals.yaml").write_text(
        "approved:\n  syn01: {verified_by: a, reviewed_by: b}\n  syn02: {verified_by: a, reviewed_by: b}\n",
        encoding="utf-8",
    )
    (syn_dir / "syn01-volume.md").write_text(
        """---
doc_id: syn01
topic_tags: ["volume"]
citation_keys: ["ralston2017"]
exercise_ids: ["Barbell_Bench_Press_-_Medium_Grip"]
---

# Training volume

## Weekly effective sets

Weekly effective sets drive hypertrophy and strength adaptation when RPE is at least 7.

## Secondary muscle counting

Primary muscles count 1.0 and secondary muscles count 0.5 per effective set.
""",
        encoding="utf-8",
    )
    (syn_dir / "syn02-rpe.md").write_text(
        """---
doc_id: syn02
topic_tags: ["rpe"]
citation_keys: ["zourdos2016"]
exercise_ids: ["Barbell_Squat"]
---

# RPE and RIR

## RPE drift at comparable load

Upward RPE drift at constant load signals accumulated fatigue across sessions.
""",
        encoding="utf-8",
    )


def test_chunking_by_heading_and_stable_ids(tmp_path: Path) -> None:
    syn_dir = tmp_path / "knowledge"
    _write_sample_synthesis(syn_dir)

    chunks_first = load_synthesis_chunks(syn_dir)
    chunks_second = load_synthesis_chunks(syn_dir)

    assert [c.chunk_id for c in chunks_first] == ["syn01#c01", "syn01#c02", "syn02#c01"]
    assert [c.chunk_id for c in chunks_first] == [c.chunk_id for c in chunks_second]
    assert [c.content_hash for c in chunks_first] == [c.content_hash for c in chunks_second]
    assert chunks_first[0].metadata["section"] == "Weekly effective sets"
    assert chunks_first[0].metadata["citation_keys"] == ["ralston2017"]


def test_build_fails_on_untagged_or_disallowed_tag(tmp_path: Path) -> None:
    syn_dir = tmp_path / "knowledge"
    syn_dir.mkdir()
    (syn_dir / "TAGS.md").write_text("- `volume`\n", encoding="utf-8")

    # Missing topic_tags
    (syn_dir / "bad_untagged.md").write_text(
        "---\ndoc_id: bad1\ntopic_tags: []\n---\n\n## Section\nSome text.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no topic_tags"):
        load_synthesis_chunks(syn_dir)

    # Disallowed tag (e.g. medical/injury)
    (syn_dir / "bad_untagged.md").unlink()
    (syn_dir / "bad_tag.md").write_text(
        "---\ndoc_id: bad2\ntopic_tags: [\"injury_rehab\"]\n---\n\n## Section\nSome text.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="disallowed topic_tags"):
        load_synthesis_chunks(syn_dir)


def test_incremental_rebuild_is_noop_and_only_reembeds_changed(tmp_path: Path) -> None:
    syn_dir = tmp_path / "knowledge"
    _write_sample_synthesis(syn_dir)
    index_dir = tmp_path / "index"
    embedder = HashEmbedder()

    # First build indexes all 3 synthesis chunks
    r1 = build_index(
        index_dir=index_dir,
        embedder=embedder,
        synthesis_dir=syn_dir,
        include_exercises=False,
        include_synthesis=True,
    )
    assert r1.total_chunks == 3
    assert r1.upserted_chunks == 3
    assert r1.skipped_unchanged == 0
    assert embedder.embedded_texts_count == 3

    # Second build with no changes is a complete no-op
    r2 = build_index(
        index_dir=index_dir,
        embedder=embedder,
        synthesis_dir=syn_dir,
        include_exercises=False,
        include_synthesis=True,
    )
    assert r2.upserted_chunks == 0
    assert r2.skipped_unchanged == 3
    assert embedder.embedded_texts_count == 3

    # Modify only syn02 -> only 1 chunk re-embedded
    syn02 = syn_dir / "syn02-rpe.md"
    syn02.write_text(
        syn02.read_text(encoding="utf-8") + "\nAdditional detail on fatigue accumulation.\n",
        encoding="utf-8",
    )
    r3 = build_index(
        index_dir=index_dir,
        embedder=embedder,
        synthesis_dir=syn_dir,
        include_exercises=False,
        include_synthesis=True,
    )
    assert r3.upserted_chunks == 1
    assert r3.skipped_unchanged == 2
    assert embedder.embedded_texts_count == 4


def test_rrf_ordering_on_toy_case() -> None:
    a = ScoredChunk(chunk_id="A", text="a", score=0.9)
    b = ScoredChunk(chunk_id="B", text="b", score=0.8)
    c = ScoredChunk(chunk_id="C", text="c", score=0.7)

    # B is #2 in list 1 and #1 in list 2 -> 1/62 + 1/61
    # A is #1 in list 1 and #3 in list 2 -> 1/61 + 1/63
    # C is #3 in list 1 and #2 in list 2 -> 1/63 + 1/62
    fused = reciprocal_rank_fusion([[a, b, c], [b, c, a]], rrf_k=60, top_k=3)
    assert [x.chunk_id for x in fused] == ["B", "A", "C"]


def test_hybrid_and_metadata_filtering(tmp_path: Path) -> None:
    syn_dir = tmp_path / "knowledge"
    _write_sample_synthesis(syn_dir)
    index_dir = tmp_path / "index"
    embedder = HashEmbedder()

    build_index(
        index_dir=index_dir,
        embedder=embedder,
        synthesis_dir=syn_dir,
        include_exercises=False,
        include_synthesis=True,
    )
    store = ChromaVectorStore(index_dir / "chroma", embedder)
    bm25 = BM25Index.load(index_dir / "bm25_chunks.json")
    retriever = HybridRetriever(store, bm25)

    # Filter to topic_tags_any=["rpe"] -> must only return syn02#c01
    for mode in ("dense", "bm25", "hybrid"):
        hits = retriever.retrieve(
            "RPE drift fatigue",
            k=5,
            mode=mode,
            where={"corpus": "synthesis", "topic_tags_any": ["rpe"]},
        )
        assert len(hits) == 1
        assert hits[0].chunk_id == "syn02#c01"

    # Exclude Barbell_Squat -> syn02#c01 must be excluded
    hits_excl = retriever.retrieve(
        "RPE drift fatigue",
        k=5,
        mode="hybrid",
        where={"corpus": "synthesis", "exclude_exercise_ids": ["Barbell_Squat"]},
    )
    assert all(h.chunk_id != "syn02#c01" for h in hits_excl)


def test_e5_and_nomic_prefix_formatting() -> None:
    e5 = SentenceTransformerEmbedder("intfloat/e5-small-v2")
    assert e5.format_query("bench press") == "query: bench press"
    assert e5.format_document("bench press") == "passage: bench press"

    nomic = SentenceTransformerEmbedder("nomic-ai/nomic-embed-text-v1.5")
    assert nomic.format_query("bench press") == "search_query: bench press"
    assert nomic.format_document("bench press") == "search_document: bench press"


def _build(tmp_path: Path, embedder: HashEmbedder, **kw):
    return build_index(
        index_dir=tmp_path / "index", embedder=embedder, synthesis_dir=tmp_path / "knowledge", include_exercises=False, **kw
    )


def _ids(tmp_path: Path, embedder: HashEmbedder) -> set[str]:
    return set(ChromaVectorStore(tmp_path / "index" / "chroma", embedder).stored_hashes())


def test_deleted_documents_leave_both_indexes(tmp_path: Path) -> None:
    _write_sample_synthesis(tmp_path / "knowledge")
    embedder = HashEmbedder()
    _build(tmp_path, embedder)
    (tmp_path / "knowledge" / "syn02-rpe.md").unlink()
    assert _build(tmp_path, embedder).deleted_chunks == 1
    assert _ids(tmp_path, embedder) == {"syn01#c01", "syn01#c02"}
    assert {c.chunk_id for c in BM25Index.load(tmp_path / "index" / "bm25_chunks.json").chunks} == {
        "syn01#c01", "syn01#c02",
    }  # fmt: skip


def test_withdrawn_approval_removes_the_document(tmp_path: Path) -> None:
    _write_sample_synthesis(tmp_path / "knowledge")
    embedder = HashEmbedder()
    _build(tmp_path, embedder)
    (tmp_path / "knowledge" / "approvals.yaml").write_text("approved: {syn01: {}}\n", encoding="utf-8")
    _build(tmp_path, embedder)
    assert _ids(tmp_path, embedder) == {"syn01#c01", "syn01#c02"}


def test_drafts_are_indexed_only_on_request(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    _write_sample_synthesis(knowledge)
    (knowledge / "approvals.yaml").unlink()
    assert load_approved_doc_ids(knowledge) == frozenset()
    assert load_synthesis_chunks(knowledge) == []
    assert len(load_synthesis_chunks(knowledge, include_drafts=True)) == 3


def test_drafts_are_still_validated(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    _write_sample_synthesis(knowledge)
    text = (knowledge / "syn02-rpe.md").read_text(encoding="utf-8")
    (knowledge / "syn03.md").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate doc_id"):
        load_synthesis_chunks(knowledge)


def test_changing_the_model_or_the_chunking_rebuilds_cleanly(tmp_path: Path) -> None:
    _write_sample_synthesis(tmp_path / "knowledge")
    _build(tmp_path, HashEmbedder(dim=64, model_name="a"))
    other = HashEmbedder(dim=32, model_name="b")
    assert _build(tmp_path, other).upserted_chunks == 3
    assert _build(tmp_path, other, chunking="fixed_512").total_chunks == 2
    assert _ids(tmp_path, other) == {"syn01#c01", "syn02#c01"}


def test_an_interrupted_build_repairs_itself(tmp_path: Path) -> None:
    _write_sample_synthesis(tmp_path / "knowledge")
    embedder = HashEmbedder()
    _build(tmp_path, embedder)
    ChromaVectorStore(tmp_path / "index" / "chroma", embedder).delete(["syn01#c01"])
    assert _build(tmp_path, embedder).upserted_chunks == 1


def test_bm25_returns_no_document_without_a_query_term(tmp_path: Path) -> None:
    _write_sample_synthesis(tmp_path / "knowledge")
    index = BM25Index(load_synthesis_chunks(tmp_path / "knowledge"))
    assert [h.chunk_id for h in index.query("drift")] == ["syn02#c01"]
    assert index.query("zzz") == []


def test_the_committed_documents_are_valid() -> None:
    chunks = load_synthesis_chunks(include_drafts=True)
    assert {c.metadata["doc_id"] for c in chunks} >= {"syn01", "syn02", "syn03", "syn04", "syn05"}


def test_exercise_retriever_gives_candidates_with_a_similarity(tmp_path: Path) -> None:
    embedder = HashEmbedder(dim=256)
    build_index(index_dir=tmp_path / "index", embedder=embedder, include_synthesis=False)
    retriever = ExerciseRetriever(
        HybridRetriever(
            ChromaVectorStore(tmp_path / "index" / "chroma", embedder),
            BM25Index.load(tmp_path / "index" / "bm25_chunks.json"),
        )
    )
    hits = retriever.retrieve("zottman curl", k=3)
    assert hits[0].exercise_id == "Zottman_Curl" and 0 < hits[0].score <= 1
    assert all(h.exercise_id in load_exercises() for h in hits)
