"""BM25 lexical index over the shared RAG chunk table (issue M5, #36)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from src.rag.corpus import Chunk, filter_matches
from src.rag.store import ScoredChunk

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Deterministic lowercase alphanumeric tokenizer for BM25."""
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    """In-memory and JSON-persisted BM25Okapi index with metadata filtering."""

    def __init__(self, chunks: Sequence[Chunk] = ()) -> None:
        self._chunks: list[Chunk] = list(chunks)
        self._tokenized: list[list[str]] = [tokenize(c.text) for c in self._chunks]
        self._bm25: BM25Okapi | None = BM25Okapi(self._tokenized) if self._chunks else None

    @property
    def chunks(self) -> list[Chunk]:
        return list(self._chunks)

    def query(
        self,
        text: str,
        k: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        """Return top-k chunks by BM25 score matching ``where``."""
        if not self._chunks or self._bm25 is None or k <= 0:
            return []
        q_tokens = tokenize(text)
        if not q_tokens:
            return []
        scores = self._bm25.get_scores(q_tokens)
        wanted = set(q_tokens)
        scored_indices = sorted(
            # A document without any query term is not a hit; ranking it would add noise to RRF.
            (i for i in range(len(self._chunks)) if wanted.intersection(self._tokenized[i])),
            key=lambda i: (-float(scores[i]), self._chunks[i].chunk_id),
        )
        results: list[ScoredChunk] = []
        for idx in scored_indices:
            chunk = self._chunks[idx]
            if not filter_matches(chunk.metadata, where):
                continue
            results.append(
                ScoredChunk(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    score=round(float(scores[idx]), 6),
                    metadata=dict(chunk.metadata),
                )
            )
            if len(results) >= k:
                break
        return results

    def save(self, path: Path | str) -> None:
        """Persist the shared chunk table to JSON so BM25 can be reconstructed deterministically."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = [c.model_dump() for c in self._chunks]
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> BM25Index:
        """Load a persisted BM25Index from JSON."""
        target = Path(path)
        if not target.exists():
            return cls([])
        raw = json.loads(target.read_text(encoding="utf-8"))
        return cls([Chunk.model_validate(item) for item in raw])
