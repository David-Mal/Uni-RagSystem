"""Hybrid retrieval with Reciprocal Rank Fusion (RRF, k=60), dense-only, and BM25-only modes (M5, #36)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from src.rag.bm25 import BM25Index
from src.rag.store import ChromaVectorStore, ScoredChunk
from src.tools.match_exercise import Candidate

RetrievalMode = Literal["hybrid", "dense", "bm25"]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[ScoredChunk]],
    *,
    rrf_k: int = 60,
    top_k: int = 5,
) -> list[ScoredChunk]:
    """Fuse multiple ranked lists via RRF: ``score(d) = sum(1 / (rrf_k + rank_i(d)))``."""
    fused_scores: dict[str, float] = {}
    chunk_by_id: dict[str, ScoredChunk] = {}

    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused_scores[item.chunk_id] = fused_scores.get(item.chunk_id, 0.0) + 1.0 / (
                rrf_k + rank
            )
            if item.chunk_id not in chunk_by_id:
                chunk_by_id[item.chunk_id] = item

    ordered = sorted(fused_scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
    return [
        ScoredChunk(
            chunk_id=cid,
            text=chunk_by_id[cid].text,
            score=round(score, 6),
            metadata=dict(chunk_by_id[cid].metadata),
        )
        for cid, score in ordered
    ]


class HybridRetriever:
    """Unified retriever over Chroma dense store + BM25 index with RRF fusion."""

    def __init__(
        self,
        vector_store: ChromaVectorStore,
        bm25_index: BM25Index,
        *,
        rrf_k: int = 60,
    ) -> None:
        self.vector_store = vector_store
        self.bm25_index = bm25_index
        self.rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        mode: RetrievalMode = "hybrid",
        where: Mapping[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        """Retrieve top-k chunks in ``hybrid``, ``dense``, or ``bm25`` mode."""
        if mode == "dense":
            return self.vector_store.query(query, k=k, where=where)
        if mode == "bm25":
            return self.bm25_index.query(query, k=k, where=where)
        if mode == "hybrid":
            fetch_k = max(k * 3, 20)
            dense_hits = self.vector_store.query(query, k=fetch_k, where=where)
            bm25_hits = self.bm25_index.query(query, k=fetch_k, where=where)
            return reciprocal_rank_fusion([dense_hits, bm25_hits], rrf_k=self.rrf_k, top_k=k)
        raise ValueError(f"Unsupported retrieval mode: {mode!r}")


class ExerciseRetriever:
    """Stage 3 of ``match_exercise_rag`` (its ``Retriever`` protocol) on top of the hybrid index.

    Order comes from the fused ranking. The score is the cosine similarity, because an RRF score (at most 2/61) says
    nothing about confidence. ``retrieval_threshold`` in ``configs/matching.yaml`` applies to it and is still to be tuned
    on dev for the chosen embedder.
    """

    def __init__(self, retriever: HybridRetriever) -> None:
        self._retriever = retriever

    def retrieve(self, query: str, k: int = 5) -> list[Candidate]:
        """Return exercise candidates, best first."""
        where = {"corpus": "exercises"}
        similarity = {
            h.chunk_id: h.score
            for h in self._retriever.vector_store.query(query, k=max(3 * k, 20), where=where)
        }
        return [
            Candidate(exercise_id=h.chunk_id, score=similarity.get(h.chunk_id, 0.0), name=h.metadata.get("name"))
            for h in self._retriever.retrieve(query, k=k, where=where)
        ]
