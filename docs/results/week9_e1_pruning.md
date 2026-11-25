# Week 9 — E1 Retrieval Pruning Round (Issue M7, #38)

## Experimental Setup

- **Config:** `configs/e1_pruning.yaml` (reproducible via `PYTHONPATH=. python -m src.eval.retrieval --config configs/e1_pruning.yaml`)
- **Dev query set:** `data/dev/rag_queries.jsonl` (20 dev queries: 10 synthesis queries with paragraph-level character spans, 10 exercise queries with `exercise_id` labels; held-out `data/golden/` untouched)
- **Relevance definition:** Chunking-independent span overlap (`doc_id` match + half-open character span overlap) for synthesis; exact `exercise_id` match for free-exercise-db.
- **Grid evaluated:**
  - Chunkings (synthesis): `fixed_256`, `fixed_512`, `heading`, `sentence_window` (free-exercise-db is unsplit: 1 entry = 1 document)
  - Embedders: `sentence-transformers/all-MiniLM-L6-v2` (22.7M), `BAAI/bge-small-en-v1.5` (33.4M), `intfloat/e5-small-v2` (33.4M, with `query: `/`passage: ` prefixes)
  - Retrieval modes: `dense`, `hybrid` (BM25 + dense with RRF `k=60`; cross-encoder reranker cut per M7)
- **Tie-break rule:** Ties go to the smaller model (`params_m`).
- **Raw outputs:** `results/E1/dev/metrics.json`, `results/E1/dev/metrics.csv`

---

## Results — Exercise Corpus (free-exercise-db, 876 docs, 10 dev queries)

| Chunking | Embedder | Params (M) | Mode | Recall@3 | Recall@5 | MRR |
|---|---|---:|---|---:|---:|---:|
| `unsplit` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | **0.7000** | **0.9000** | **0.5950** |
| `unsplit` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 0.7000 | 0.9000 | 0.5450 |
| `unsplit` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 0.7000 | 0.7000 | 0.5333 |
| `unsplit` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 0.6000 | 0.6000 | 0.4333 |
| `unsplit` | `intfloat/e5-small-v2` | 33.4 | `dense` | 0.5000 | 0.7000 | 0.3950 |
| `unsplit` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 0.3000 | 0.3000 | 0.2000 |

---

## Results — Synthesis Corpus (Fi3 `syn01`–`syn05`, 10 dev queries)

| Chunking | Embedder | Params (M) | Mode | Recall@3 | Recall@5 | MRR |
|---|---|---:|---|---:|---:|---:|
| `heading` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_256` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_256` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_256` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `intfloat/e5-small-en-v2` | 33.4 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `intfloat/e5-small-v2` | 33.4 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_256` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_256` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 1.0000 | 1.0000 | 0.9500 |
| `fixed_256` | `intfloat/e5-small-v2` | 33.4 | `dense` | 1.0000 | 1.0000 | 0.9500 |
| `sentence_window` | `intfloat/e5-small-v2` | 33.4 | `dense` | 1.0000 | 1.0000 | 0.8333 |
| `sentence_window` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 0.8333 |
| `sentence_window` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 0.8167 |
| `sentence_window` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 0.9000 | 1.0000 | 0.8033 |
| `sentence_window` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 0.9000 | 1.0000 | 0.8033 |
| `sentence_window` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 0.8000 | 0.8000 | 0.6833 |

---

## Pruning Decision for Week 10 Final Run (Held-Out Golden Set)

1. **Chunkings kept:**
   - **`heading` (default):** Achieves 1.00 MRR across all embedders and aligns chunk boundaries with section-level citations.
   - **`fixed_512` (baseline):** Kept as the fixed-token comparison for Week 10 when additional synthesis documents (6–10) are added.
   - *Pruned:* `sentence_window` (drops MRR to 0.68–0.83 by fragmenting context) and `fixed_256` (splits single-topic sections and drops dense MRR to 0.95).
2. **Embedders kept:**
   - **`BAAI/bge-small-en-v1.5` (33.4M, default):** #1 overall on the exercise corpus (MRR 0.5950, R@5 0.90) and 1.00 MRR on synthesis.
   - **`intfloat/e5-small-v2` (33.4M):** Strong runner-up on exercises (MRR 0.5450, R@5 0.90) and 1.00 MRR on synthesis; kept for final held-out verification.
   - *Pruned:* `sentence-transformers/all-MiniLM-L6-v2` (22.7M) — although it ties on the small 5-doc synthesis corpus, it lags severely on the 876-entry exercise corpus (dense MRR 0.20 vs 0.53; hybrid MRR 0.43 vs 0.60). `nomic-embed-text-v1.5` was omitted due to larger footprint (~137M) with no headroom left on synthesis.
3. **Retrieval modes kept:**
   - **`hybrid` (BM25 + dense RRF, k=60, default):** Consistently outperforms dense-only on every embedder on the exercise corpus (+0.06 to +0.23 MRR; +0.20 to +0.30 R@5).
   - **`dense`:** Kept as the required E1 ablation baseline (plan §4.2).
   - *Cut:* Cross-encoder reranker (cut per issue M7).
