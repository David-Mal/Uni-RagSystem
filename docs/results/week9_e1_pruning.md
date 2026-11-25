# Week 9 — E1 Retrieval Pruning Round (Issue M7, #38)

## Experimental Setup

- **Config:** `configs/e1_pruning.yaml` (reproducible via `uv run --group embed python -m src.eval.retrieval --config configs/e1_pruning.yaml`)
- **Dev query set:** `data/dev/rag_queries.jsonl` (20 dev queries: 10 synthesis queries with paragraph-level character spans, 10 exercise queries with `exercise_id` labels; held-out `data/golden/` untouched)
- **Relevance definition:** Chunking-independent span overlap (`doc_id` match + half-open character span overlap) for synthesis; exact `exercise_id` match for free-exercise-db.
- **Grid evaluated:**
  - Chunkings (synthesis): `fixed_256`, `fixed_512`, `heading`, `sentence_window` (free-exercise-db is unsplit: 1 entry = 1 document)
  - Embedders: `sentence-transformers/all-MiniLM-L6-v2` (22.7M), `BAAI/bge-small-en-v1.5` (33.4M), `intfloat/e5-small-v2` (33.4M, with `query: `/`passage: ` prefixes)
  - Retrieval modes: `dense`, `hybrid` (BM25 + dense with RRF `k=60`; cross-encoder reranker cut per M7)
- **Tie-break rule:** Ties go to the smaller model (`params_m`).
- **Raw outputs:** `results/E1/dev/metrics.json`, `results/E1/dev/metrics.csv`
- **Drafts:** the five documents are not approved yet (`docs/knowledge/approvals.yaml`), so this experiment indexes them with `include_drafts`.
- **Rerun on `main`, 2026-11-25.** The first run did not contain the alias dictionary (M1) and used a BM25 index that also returned documents without any query term. The tables below are from the rerun.

---

## Results: exercise corpus (free-exercise-db, 876 documents, 10 dev queries)

| Chunking | Embedder | Params (M) | Mode | Recall@3 | Recall@5 | MRR |
|---|---|---:|---|---:|---:|---:|
| `unsplit` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 0.9000 | 0.9000 | 0.6667 |
| `unsplit` | `intfloat/e5-small-v2` | 33.4 | `dense` | 0.5000 | 0.8000 | 0.4533 |
| `unsplit` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | 0.3000 | 0.6000 | 0.3200 |
| `unsplit` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 0.4000 | 0.4000 | 0.2833 |
| `unsplit` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 0.3000 | 0.3000 | 0.2500 |
| `unsplit` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 0.2000 | 0.3000 | 0.1750 |

**Effect of the aliases** (MRR, same queries). Without aliases the first run is reproduced exactly for dense and hybrid:

| Embedder | Dense, without | Dense, with | BM25, without | BM25, with | Hybrid, without | Hybrid, with |
|---|---:|---:|---:|---:|---:|---:|
| `all-MiniLM-L6-v2` | 0.2000 | 0.1750 | 0.4833 | 0.7333 | 0.4333 | 0.2833 |
| `bge-small-en-v1.5` | 0.5333 | 0.2500 | 0.4833 | 0.7333 | 0.5950 | 0.3200 |
| `e5-small-v2` | 0.3950 | 0.4533 | 0.4833 | 0.7333 | 0.5450 | 0.6667 |

The aliases help BM25 and hurt dense retrieval with MiniLM and bge. **BM25 alone (0.7333) is better than every hybrid** here.

---

## Results: synthesis corpus (`syn01`-`syn05`, 10 dev queries)

| Chunking | Embedder | Params (M) | Mode | Recall@3 | Recall@5 | MRR |
|---|---|---:|---|---:|---:|---:|
| `fixed_512` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `intfloat/e5-small-v2` | 33.4 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_512` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `intfloat/e5-small-v2` | 33.4 | `dense` | 1.0000 | 1.0000 | 1.0000 |
| `heading` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 1.0000 |
| `fixed_256` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 1.0000 | 1.0000 | 0.9500 |
| `fixed_256` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 1.0000 | 1.0000 | 0.9500 |
| `fixed_256` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 0.9500 |
| `fixed_256` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 0.9500 |
| `fixed_256` | `intfloat/e5-small-v2` | 33.4 | `dense` | 1.0000 | 1.0000 | 0.9000 |
| `fixed_256` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 1.0000 | 1.0000 | 0.8500 |
| `sentence_window` | `BAAI/bge-small-en-v1.5` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 0.8333 |
| `sentence_window` | `intfloat/e5-small-v2` | 33.4 | `hybrid` | 1.0000 | 1.0000 | 0.8333 |
| `sentence_window` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `hybrid` | 0.9000 | 1.0000 | 0.8083 |
| `sentence_window` | `intfloat/e5-small-v2` | 33.4 | `dense` | 1.0000 | 1.0000 | 0.7667 |
| `sentence_window` | `BAAI/bge-small-en-v1.5` | 33.4 | `dense` | 0.9000 | 1.0000 | 0.7533 |
| `sentence_window` | `sentence-transformers/all-MiniLM-L6-v2` | 22.7 | `dense` | 0.8000 | 0.9000 | 0.7083 |

**These numbers separate little.** Each document is one section, so `heading` and `fixed_512` give five chunks in total and Recall@5 is 1 by construction. Only `fixed_256` and `sentence_window` have more chunks than the top 5.

---

## Pruning decision for the Week 10 final run (held-out set)

With 10 queries per corpus, one query is 0.1 of any metric. The decisions below are for pruning only; nothing is chosen as the winner.

1. **Chunkings kept:** `heading` and `fixed_512`. *Pruned:* `sentence_window` (MRR 0.71-0.83) and `fixed_256` (0.85-0.95). Note that "512" counts words; bge and e5 cut their input at 512 model tokens.
2. **Embedders kept:** `intfloat/e5-small-v2` (best on exercises with aliases) and `BAAI/bge-small-en-v1.5` (index default, best without aliases). *Pruned:* `all-MiniLM-L6-v2`, last on exercises in every setting. It ties on synthesis, so the smaller-model rule alone would keep it. `nomic-embed-text-v1.5` was not run.
3. **Retrieval modes kept:** `hybrid`, `dense` (required baseline), and **`bm25`**, added because it is the best mode on the exercise corpus. *Cut:* cross-encoder reranker.
4. **To decide before the final run:** whether aliases belong in the dense text or only in the BM25 text. Test both on dev.
