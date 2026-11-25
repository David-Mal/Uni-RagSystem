"""Chunking-independent retrieval evaluation and E1 pruning runner (issue M7, #38).

Metrics: Recall@3, Recall@5, MRR, reported separately for the exercise corpus and the
synthesis corpus. A synthesis chunk counts as relevant iff it belongs to the labeled
``doc_id`` and its character span ``[char_start, char_end]`` overlaps the labeled span.
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from src.rag.bm25 import BM25Index
from src.rag.build import build_index
from src.rag.corpus import ChunkingMode
from src.rag.retrieve import HybridRetriever, RetrievalMode
from src.rag.store import (
    ChromaVectorStore,
    Embedder,
    HashEmbedder,
    ScoredChunk,
    SentenceTransformerEmbedder,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_E1_CONFIG = REPO_ROOT / "configs" / "e1_pruning.yaml"


class RetrievalMetrics(BaseModel):
    """Aggregate retrieval metrics over a query set."""

    corpus: str
    n_queries: int
    recall_at_3: float
    recall_at_5: float
    mrr: float


def load_dev_queries(path: Path | str) -> list[dict[str, Any]]:
    """Load JSONL dev retrieval queries."""
    target = Path(path)
    records: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def spans_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    """Return True iff half-open character spans ``[start_a, end_a)`` and ``[start_b, end_b)`` overlap."""
    return min(end_a, end_b) > max(start_a, start_b)


def is_chunk_relevant(chunk: ScoredChunk, query_record: Mapping[str, Any]) -> bool:
    """Chunking-independent relevance predicate for both corpora."""
    corpus = query_record["corpus"]
    meta = chunk.metadata
    if corpus == "exercises":
        return meta.get("exercise_id") == query_record.get("exercise_id")
    if corpus == "synthesis":
        if meta.get("doc_id") != query_record.get("doc_id"):
            return False
        c_start = meta.get("char_start")
        c_end = meta.get("char_end")
        q_start = query_record.get("char_start")
        q_end = query_record.get("char_end")
        if None in (c_start, c_end, q_start, q_end):
            return meta.get("section") == query_record.get("section")
        return spans_overlap(int(c_start), int(c_end), int(q_start), int(q_end))
    raise ValueError(f"Unknown corpus in query record: {corpus!r}")


def evaluate_corpus(
    queries: Sequence[Mapping[str, Any]],
    retriever: HybridRetriever,
    *,
    corpus: str,
    mode: RetrievalMode,
    top_k: int = 5,
) -> RetrievalMetrics:
    """Evaluate Recall@3, Recall@5, and MRR for a single corpus.

    Recall@k is the share of queries with at least one relevant chunk in the top k (each query has one labeled span).
    """
    corpus_queries = [q for q in queries if q["corpus"] == corpus]
    if not corpus_queries:
        return RetrievalMetrics(
            corpus=corpus, n_queries=0, recall_at_3=0.0, recall_at_5=0.0, mrr=0.0
        )

    r3_hits = 0
    r5_hits = 0
    rr_sum = 0.0

    for q in corpus_queries:
        hits = retriever.retrieve(
            str(q["query"]),
            k=max(top_k, 5),
            mode=mode,
            where={"corpus": corpus},
        )
        first_rank: int | None = None
        for rank, chunk in enumerate(hits, start=1):
            if is_chunk_relevant(chunk, q):
                first_rank = rank
                break
        if first_rank is not None:
            if first_rank <= 3:
                r3_hits += 1
            if first_rank <= 5:
                r5_hits += 1
            rr_sum += 1.0 / first_rank

    n = len(corpus_queries)
    return RetrievalMetrics(
        corpus=corpus,
        n_queries=n,
        recall_at_3=round(r3_hits / n, 4),
        recall_at_5=round(r5_hits / n, 4),
        mrr=round(rr_sum / n, 4),
    )


def rank_variants_with_size_tiebreak(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Sort variants by descending MRR, descending Recall@5, descending Recall@3, ascending params_m."""
    return [
        dict(r)
        for r in sorted(
            rows,
            key=lambda r: (
                -float(r["mrr"]),
                -float(r["recall_at_5"]),
                -float(r["recall_at_3"]),
                float(r.get("params_m", 999.0)),
                str(r["embedder"]),
                str(r["chunking"]),
                str(r["mode"]),
            ),
        )
    ]


def run_e1_pruning(
    config_path: Path | str = DEFAULT_E1_CONFIG,
    *,
    fake_embedder: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Run the E1 pruning grid from YAML config and write JSON + CSV results."""
    cfg_path = Path(config_path)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    queries = load_dev_queries(REPO_ROOT / cfg["queries_path"])
    syn_dir = REPO_ROOT / cfg["synthesis_dir"]
    ex_path = REPO_ROOT / cfg["exercises_path"]
    out_dir = REPO_ROOT / cfg["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    chunkings: list[ChunkingMode] = list(cfg["chunkings"])
    embedders_cfg: list[dict[str, Any]] = list(cfg["embedders"])
    modes: list[RetrievalMode] = list(cfg["modes"])
    rrf_k = int(cfg.get("rrf_k", 60))
    top_k = int(cfg.get("top_k", 5))

    exercise_rows: list[dict[str, Any]] = []
    synthesis_rows: list[dict[str, Any]] = []

    # Chroma keeps its files open on Windows, so cleanup errors are ignored
    with tempfile.TemporaryDirectory(prefix="e1_pruning_", ignore_cleanup_errors=True) as tmp_root:
        tmp_path = Path(tmp_root)

        for emb_cfg in embedders_cfg:
            emb_name = str(emb_cfg["name"])
            params_m = float(emb_cfg.get("params_m", 0.0))
            embedder: Embedder = (
                HashEmbedder(model_name=f"fake-{emb_name}")
                if fake_embedder
                else SentenceTransformerEmbedder(emb_name)
            )
            safe_emb = emb_name.replace("/", "__")

            # 1. Exercise corpus (unsplit, one entry = one document)
            ex_idx_dir = tmp_path / f"ex_{safe_emb}"
            build_index(
                index_dir=ex_idx_dir,
                embedder=embedder,
                exercises_path=ex_path,
                include_exercises=True,
                include_synthesis=False,
            )
            ex_retriever = HybridRetriever(
                ChromaVectorStore(ex_idx_dir / "chroma", embedder),
                BM25Index.load(ex_idx_dir / "bm25_chunks.json"),
                rrf_k=rrf_k,
            )
            for mode in modes:
                m = evaluate_corpus(queries, ex_retriever, corpus="exercises", mode=mode, top_k=top_k)
                exercise_rows.append(
                    {
                        "corpus": "exercises",
                        "chunking": "unsplit",
                        "embedder": emb_name,
                        "params_m": params_m,
                        "mode": mode,
                        "n_queries": m.n_queries,
                        "recall_at_3": m.recall_at_3,
                        "recall_at_5": m.recall_at_5,
                        "mrr": m.mrr,
                    }
                )

            # 2. Synthesis corpus (4 chunking strategies)
            for chunking in chunkings:
                syn_idx_dir = tmp_path / f"syn_{safe_emb}_{chunking}"
                build_index(
                    index_dir=syn_idx_dir,
                    embedder=embedder,
                    synthesis_dir=syn_dir,
                    chunking=chunking,
                    include_exercises=False,
                    include_synthesis=True,
                    include_drafts=True,  # dev experiment, nothing is cited
                )
                syn_retriever = HybridRetriever(
                    ChromaVectorStore(syn_idx_dir / "chroma", embedder),
                    BM25Index.load(syn_idx_dir / "bm25_chunks.json"),
                    rrf_k=rrf_k,
                )
                for mode in modes:
                    m = evaluate_corpus(
                        queries, syn_retriever, corpus="synthesis", mode=mode, top_k=top_k
                    )
                    synthesis_rows.append(
                        {
                            "corpus": "synthesis",
                            "chunking": chunking,
                            "embedder": emb_name,
                            "params_m": params_m,
                            "mode": mode,
                            "n_queries": m.n_queries,
                            "recall_at_3": m.recall_at_3,
                            "recall_at_5": m.recall_at_5,
                            "mrr": m.mrr,
                        }
                    )

    ranked_ex = rank_variants_with_size_tiebreak(exercise_rows)
    ranked_syn = rank_variants_with_size_tiebreak(synthesis_rows)
    results = {"exercises": ranked_ex, "synthesis": ranked_syn}

    (out_dir / "metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")

    all_rows = ranked_ex + ranked_syn
    if all_rows:
        fieldnames = list(all_rows[0].keys())
        with (out_dir / "metrics.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(all_rows)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run E1 retrieval pruning benchmark from config.")
    parser.add_argument("--config", type=Path, default=DEFAULT_E1_CONFIG)
    parser.add_argument("--fake-embedder", action="store_true")
    args = parser.parse_args()

    results = run_e1_pruning(args.config, fake_embedder=args.fake_embedder)
    for corpus, rows in results.items():
        print(f"\n=== {corpus.upper()} (sorted by MRR, R@5, R@3, smaller model) ===")
        for r in rows:
            print(
                f"{r['chunking']:16s} | {r['embedder']:38s} | {r['mode']:6s} | "
                f"R@3={r['recall_at_3']:.4f} | R@5={r['recall_at_5']:.4f} | MRR={r['mrr']:.4f}"
            )


if __name__ == "__main__":
    main()
