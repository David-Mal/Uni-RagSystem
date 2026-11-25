"""Offline unit tests for Chroma + BM25 + RRF RAG index (issue M5, #36)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rag.bm25 import BM25Index
from src.rag.build import build_index
from src.rag.corpus import load_synthesis_chunks
from src.rag.retrieve import HybridRetriever, reciprocal_rank_fusion
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
