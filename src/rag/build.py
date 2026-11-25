"""Incremental index build script for Chroma + BM25 (issue M5, #36).

Usage:
    python -m src.rag.build [--index-dir data/index] [--embedder BAAI/bge-small-en-v1.5]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.rag.bm25 import BM25Index
from src.rag.corpus import (
    ChunkingMode,
    load_exercise_chunks,
    load_synthesis_chunks,
)
from src.rag.store import (
    DEFAULT_EMBEDDER_MODEL,
    PINNED_CHROMA_VERSION,
    ChromaVectorStore,
    Embedder,
    HashEmbedder,
    SentenceTransformerEmbedder,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX_DIR = REPO_ROOT / "data" / "index"


@dataclass
class BuildReport:
    """Summary of an incremental index build run."""

    total_chunks: int
    upserted_chunks: int
    skipped_unchanged: int
    exercise_chunks: int
    synthesis_chunks: int
    manifest_path: Path


def _git_head_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_index(
    *,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    embedder: Embedder | None = None,
    embedder_name: str = DEFAULT_EMBEDDER_MODEL,
    exercises_path: Path | str | None = None,
    synthesis_dir: Path | str | None = None,
    aliases_path: Path | str | None = None,
    chunking: ChunkingMode = "heading",
    include_exercises: bool = True,
    include_synthesis: bool = True,
) -> BuildReport:
    """Incrementally embed/upsert only changed chunks into Chroma, rebuild BM25, write manifest."""
    idx_dir = Path(index_dir)
    idx_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = idx_dir / "manifest.json"
    bm25_path = idx_dir / "bm25_chunks.json"

    active_embedder: Embedder = (
        embedder if embedder is not None else SentenceTransformerEmbedder(embedder_name)
    )

    ex_chunks = (
        load_exercise_chunks(exercises_path=exercises_path, aliases_path=aliases_path)
        if include_exercises
        else []
    )
    syn_chunks = (
        load_synthesis_chunks(synthesis_dir=synthesis_dir, chunking=chunking)
        if include_synthesis
        else []
    )
    all_chunks = ex_chunks + syn_chunks

    prev_manifest: dict[str, Any] = {}
    if manifest_path.exists():
        prev_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    same_model = prev_manifest.get("embedding_model") == active_embedder.model_name
    same_chunking = prev_manifest.get("chunking") == chunking
    prev_hashes: dict[str, str] = (
        dict(prev_manifest.get("chunk_hashes", {})) if (same_model and same_chunking) else {}
    )

    changed_chunks = [c for c in all_chunks if prev_hashes.get(c.chunk_id) != c.content_hash]
    skipped = len(all_chunks) - len(changed_chunks)

    store = ChromaVectorStore(idx_dir / "chroma", active_embedder)
    upserted = store.upsert(changed_chunks)

    if changed_chunks or not bm25_path.exists() or len(prev_hashes) != len(all_chunks):
        bm25 = BM25Index(all_chunks)
        bm25.save(bm25_path)

    manifest = {
        "source_commit": _git_head_commit(),
        "chroma_version": PINNED_CHROMA_VERSION,
        "embedding_model": active_embedder.model_name,
        "chunking": chunking,
        "exercise_chunks": len(ex_chunks),
        "synthesis_chunks": len(syn_chunks),
        "chunk_hashes": {c.chunk_id: c.content_hash for c in all_chunks},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return BuildReport(
        total_chunks=len(all_chunks),
        upserted_chunks=upserted,
        skipped_unchanged=skipped,
        exercise_chunks=len(ex_chunks),
        synthesis_chunks=len(syn_chunks),
        manifest_path=manifest_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Chroma + BM25 RAG index incrementally.")
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--embedder", type=str, default=DEFAULT_EMBEDDER_MODEL)
    parser.add_argument("--synthesis-dir", type=Path, default=None)
    parser.add_argument("--exercises-path", type=Path, default=None)
    parser.add_argument("--chunking", type=str, default="heading")
    parser.add_argument("--fake-embedder", action="store_true")
    args = parser.parse_args()

    embedder: Embedder | None = HashEmbedder() if args.fake_embedder else None
    report = build_index(
        index_dir=args.index_dir,
        embedder=embedder,
        embedder_name=args.embedder,
        exercises_path=args.exercises_path,
        synthesis_dir=args.synthesis_dir,
        chunking=args.chunking,
    )
    print(
        f"Indexed {report.total_chunks} chunks "
        f"(exercises={report.exercise_chunks}, synthesis={report.synthesis_chunks}; "
        f"upserted={report.upserted_chunks}, skipped={report.skipped_unchanged}). "
        f"Manifest: {report.manifest_path}"
    )


if __name__ == "__main__":
    main()
