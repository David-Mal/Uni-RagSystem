"""2-method Chroma vector store wrapper + pluggable embedders (issue M5, #36)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import chromadb
from pydantic import BaseModel, Field

from src.rag.corpus import Chunk, filter_matches

PINNED_CHROMA_VERSION = "1.5.9"
DEFAULT_EMBEDDER_MODEL = "BAAI/bge-small-en-v1.5"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class ScoredChunk(BaseModel):
    """Retrieved chunk with similarity or fusion score."""

    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class Embedder(Protocol):
    """Minimal embedding interface supporting query/document prefixes (e.g. e5, nomic)."""

    model_name: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class HashEmbedder:
    """Fast, deterministic, offline bag-of-words hash embedder for unit tests."""

    def __init__(self, dim: int = 64, model_name: str = "fake-hash-64") -> None:
        self.dim = dim
        self.model_name = model_name
        self.embed_doc_calls: int = 0
        self.embedded_texts_count: int = 0

    def _encode_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(text.lower())
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [v / norm for v in vec]
        return vec

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.embed_doc_calls += 1
        self.embedded_texts_count += len(texts)
        return [self._encode_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._encode_one(text)


class SentenceTransformerEmbedder:
    """Sentence-Transformers embedder with automatic query/passage prefixes for e5 and nomic."""

    def __init__(self, model_name: str = DEFAULT_EMBEDDER_MODEL) -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            trust = "nomic" in self.model_name.lower()
            self._model = SentenceTransformer(self.model_name, trust_remote_code=trust)
        return self._model

    def format_document(self, text: str) -> str:
        lower = self.model_name.lower()
        if "e5-" in lower or "/e5" in lower:
            return f"passage: {text}"
        if "nomic-embed" in lower:
            return f"search_document: {text}"
        return text

    def format_query(self, text: str) -> str:
        lower = self.model_name.lower()
        if "e5-" in lower or "/e5" in lower:
            return f"query: {text}"
        if "nomic-embed" in lower:
            return f"search_query: {text}"
        return text

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        prefixed = [self.format_document(t) for t in texts]
        vectors = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        model = self._load()
        vec = model.encode([self.format_query(text)], normalize_embeddings=True, show_progress_bar=False)[0]
        return vec.tolist()


def _serialize_metadata(meta: Mapping[str, Any]) -> dict[str, str | int | float | bool]:
    out: dict[str, str | int | float | bool] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif v is None:
            out[k] = ""
        else:
            out[f"__json__{k}"] = json.dumps(v)
    return out


def _deserialize_metadata(raw: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k.startswith("__json__"):
            out[k.removeprefix("__json__")] = json.loads(str(v))
        else:
            out[k] = v
    return out


class ChromaVectorStore:
    """Thin 2-method wrapper (``upsert``, ``query``) over persistent ChromaDB."""

    def __init__(
        self,
        persist_dir: Path | str,
        embedder: Embedder,
        *,
        collection_name: str = "rag_chunks",
    ) -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: Sequence[Chunk]) -> int:
        """Embed and upsert ``chunks`` into Chroma; returns number of chunks upserted."""
        if not chunks:
            return 0
        ids = [c.chunk_id for c in chunks]
        texts = [c.text for c in chunks]
        embeddings = self.embedder.embed_documents(texts)
        metadatas = [_serialize_metadata({**c.metadata, "content_hash": c.content_hash}) for c in chunks]
        self._collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return len(chunks)

    def query(
        self,
        text: str,
        k: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        """Query Chroma by dense similarity with optional metadata filtering."""
        total = self._collection.count()
        if total == 0 or k <= 0:
            return []

        query_vec = self.embedder.embed_query(text)
        # Push simple scalar filters (e.g. corpus, doc_id) down to Chroma; apply list filters cleanly in Python
        chroma_where: dict[str, Any] | None = None
        if where and "corpus" in where:
            chroma_where = {"corpus": where["corpus"]}

        # Over-fetch when list-based metadata filters are present so top-k after filtering is accurate
        needs_post_filter = bool(
            where and any(key != "corpus" for key in where)
        )
        fetch_k = total if needs_post_filter else min(k, total)

        res = self._collection.query(
            query_embeddings=[query_vec],
            n_results=max(1, fetch_k),
            where=chroma_where,
            include=["documents", "metadatas", "distances"],
        )

        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        results: list[ScoredChunk] = []
        for cid, doc, raw_meta, dist in zip(ids, docs, metas, dists, strict=False):
            meta = _deserialize_metadata(raw_meta or {})
            if not filter_matches(meta, where):
                continue
            # Cosine distance in [0, 2] -> similarity in [-1, 1]
            similarity = 1.0 - float(dist)
            results.append(
                ScoredChunk(
                    chunk_id=str(cid),
                    text=str(doc),
                    score=round(similarity, 6),
                    metadata=meta,
                )
            )
            if len(results) >= k:
                break
        return results
