# Heuristic Load & Fatigue Analyzer

Analyzes strength-training logs (OpenGym, Strong or Hevy exports) and returns labeled hypotheses about a plateau.
Numbers come from deterministic tools, citations from a local knowledge base, and a mandatory safety gate runs first.
It gives no medical, injury or diet advice, and it abstains when the data is insufficient.

Design and schedule: [docs/milestone2-architecture-and-plan.md](docs/milestone2-architecture-and-plan.md).
Baseline: [RFC](RFC_Heuristic_Load_Fatigue_Analyzer.md). How we work: [CONTRIBUTING.md](CONTRIBUTING.md).

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then, from the repository root (Windows, macOS
or Linux):

```
uv sync
uv run pytest
uv run ruff check
```

`uv` downloads Python 3.11 if it is missing. `uv sync` installs the `core` and `dev` groups. The others are opt-in:

| Group | Install | Contents |
|---|---|---|
| `rag` | `uv sync --group rag` | Chroma, BM25, sentence-transformers |
| `mcp` | `uv sync --group mcp` | Official MCP Python SDK |
| `ml` | `uv sync --group ml` | transformers, PEFT, TRL, bitsandbytes, Outlines (needs a GPU, never installed in CI) |

Add a dependency with `uv add --group <group> <package>` and commit `uv.lock` in the same PR.

## Layout

| Path | Content |
|---|---|
| `src/schemas/` | Shared enums, pydantic models, exported JSON Schemas (F2) |
| `src/ingest/` | Canonical set model, DuckDB store, app adapters |
| `src/exercises/` | free-exercise-db loader and aliases (D7) |
| `src/tools/` | The 7 tools as plain Python functions, no MCP import |
| `src/mcp_server/` | MCP registration, the only SDK-dependent code |
| `src/gate/` | Safety gate |
| `src/verifier/` | `output_verifier` |
| `src/rag/` | Index build and hybrid retrieval |
| `src/eval/` | Evaluation harness |
| `src/reference/` | Independent reference implementation (never imports `src/tools`) |
| `src/sim/` | Lifter simulator (Fi2) |
| `src/datagen/`, `src/training/` | Training-data generators, training scripts |
| `configs/` | Thresholds and rule lists |
| `data/` | Fixtures, manifests, exercise database; `data/golden/` is restricted until the freeze |
| `tests/` | Mirrors `src/` |

## Pinned versions

| Package | Version | Why |
|---|---|---|
| Python | 3.11 | `.python-version`; one interpreter for the team and CI |
| `mcp` (official MCP Python SDK) | **2.3.0** (major version 2) | Current stable release on PyPI (checked 2026-11-25). v2 renamed `FastMCP` to `MCPServer`: use `from mcp.server.mcpserver import MCPServer`. The v1 path `mcp.server.fastmcp` does not exist in v2. |

All other versions are fixed by `uv.lock`.
