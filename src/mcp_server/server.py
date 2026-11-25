"""Thin MCP server registering deterministic analysis and retrieval tools (issue M4, #35).

This is the ONLY module in the repository that imports from the ``mcp`` SDK (pinned in ``pyproject.toml``).
Safety gate and output verifier are intentionally NOT registered as MCP tools (plan §5.7).
Exposes tools only — no MCP resources or prompts. One server process serves one request (one run).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from src.ingest import IngestError, SetStore, open_store
from src.ingest import ingest_workout_log as _ingest_workout_log
from src.mcp_server.schemas import INGEST_TOOL_VERSION
from src.rag.retrieve import HybridRetriever
from src.tools.common import ToolError, ValueIdFactory
from src.tools.e1rm import TOOL_VERSION as E1RM_VERSION
from src.tools.e1rm import compute_e1rm_and_drift as _compute_e1rm_and_drift
from src.tools.load import TOOL_VERSION as LOAD_VERSION
from src.tools.load import uncoupled_load_analyzer as _uncoupled_load_analyzer
from src.tools.match_exercise import TOOL_VERSION as MATCH_VERSION
from src.tools.match_exercise import match_exercise_id
from src.tools.match_exercise import match_exercise_rag as _match_exercise_rag
from src.tools.retrieve_knowledge import TOOL_DESCRIPTION as RETRIEVE_KNOWLEDGE_DESCRIPTION
from src.tools.retrieve_knowledge import TOOL_VERSION as KNOWLEDGE_VERSION
from src.tools.retrieve_knowledge import retrieve_knowledge as _retrieve_knowledge
from src.tools.sufficiency import TOOL_VERSION as SUFFICIENCY_VERSION
from src.tools.sufficiency import check_data_sufficiency as _check_data_sufficiency
from src.tools.weekly_sets import TOOL_VERSION as WEEKLY_VERSION
from src.tools.weekly_sets import weekly_sets_per_muscle as _weekly_sets_per_muscle

DEFAULT_INDEX_DIR = Path(__file__).resolve().parents[2] / "data" / "index"


def _dump(result: BaseModel, tool_version: str) -> dict[str, Any]:
    """JSON-ready output; every output, also an error, carries ``tool_version``."""
    return {"tool_version": tool_version, **result.model_dump(mode="json")}


class _Session:
    """State of one run: the store, the value-id counter and the sufficiency checks done so far."""

    def __init__(self, store: SetStore) -> None:
        self.store = store
        self.ids = ValueIdFactory()
        self.lock = threading.RLock()  # DuckDB connections and the counter are not thread-safe
        self._allowed: dict[str, frozenset[str] | None] = {}

    def record_check(self, log_id: str, allowed: list[str] | None) -> None:
        """Remember a check. A later check can only narrow the allowed exercises, never widen them."""
        self._allowed[log_id] = self.allowed(log_id, allowed)

    def allowed(self, log_id: str, requested: list[str] | None) -> frozenset[str] | None:
        """Exercises a tool may use: the requested ones inside the set of the first check."""
        base = self._allowed.get(log_id)
        wanted = None if requested is None else frozenset(requested)
        if base is None:
            return wanted
        return base if wanted is None else base & wanted

    def precondition(self, log_id: str, tool_name: str) -> ToolError | None:
        if log_id in self._allowed:
            return None
        return ToolError(
            code="precondition_failed",
            message=(
                f"Tool '{tool_name}' cannot run for log_id='{log_id}' until "
                f"'check_data_sufficiency' has been called for that log_id in this session."
            ),
        )


def create_server(
    *,
    store: SetStore | None = None,
    knowledge_retriever: HybridRetriever | None = None,
) -> MCPServer:
    """Create and configure the stdio MCPServer with session-scoped precondition state."""
    server = MCPServer("heuristic-load-fatigue-analyzer")
    session = _Session(store if store is not None else open_store())

    @server.tool(
        name="ingest_workout_log",
        description=(
            "Parse, normalize, and store a workout log file (OpenGym CSV) into the session store. Call this first "
            "when given a file path. Returns log_id, counts, unmatched exercise names, notes and data-quality flags. "
            "Returns ToolError('ingest_error') on unreadable or unrecognized formats; ask for a valid export then."
        ),
    )
    def ingest_workout_log(path: str, app_hint: str | None = None, log_id: str | None = None) -> dict[str, Any]:
        with session.lock:
            try:
                result = _ingest_workout_log(
                    path, app_hint=app_hint, log_id=log_id, store=session.store, matcher=match_exercise_id
                )
            except IngestError as exc:
                return _dump(ToolError(code="ingest_error", message=str(exc)), INGEST_TOOL_VERSION)
            return _dump(result, INGEST_TOOL_VERSION)

    @server.tool(
        name="match_exercise_rag",
        description=(
            "Resolve a raw exercise name string to a canonical free-exercise-db exercise_id using the cascade "
            "alias -> fuzzy -> retrieval -> unknown. Returns exercise_id='unknown' when confidence is low; never guesses."
        ),
    )
    def match_exercise_rag(name: str) -> dict[str, Any]:
        return _dump(_match_exercise_rag(name), MATCH_VERSION)

    @server.tool(
        name="check_data_sufficiency",
        description=(
            "Assess whether a stored workout log meets data-sufficiency thresholds (history span, sessions per "
            "exercise, RPE coverage, comparable load, max gap, matched exercises). MUST be called for a log_id before "
            "any analysis tool (weekly_sets_per_muscle, compute_e1rm_and_drift, uncoupled_load_analyzer). Empty "
            "allowed_analyses means full abstention; a partial list means partial abstention."
        ),
    )
    def check_data_sufficiency(log_id: str, allowed_exercise_ids: list[str] | None = None) -> dict[str, Any]:
        with session.lock:
            if log_id not in session.store.log_ids():
                error = ToolError(code="unknown_log", message=f"no log {log_id!r} in this session; ingest a file first")
                return _dump(error, SUFFICIENCY_VERSION)
            session.record_check(log_id, allowed_exercise_ids)
            allowed = session.allowed(log_id, None)
            result = _check_data_sufficiency(
                session.store, log_id, None if allowed is None else sorted(allowed), ids=session.ids
            )
            return _dump(result, SUFFICIENCY_VERSION)

    @server.tool(
        name="weekly_sets_per_muscle",
        description=(
            "Compute effective weekly sets per muscle (primary=1.0, secondary=0.5, Monday-start weeks, non-warmup, "
            "non-failed, RPE>=7 when logged). Precondition: check_data_sufficiency must have been called for log_id in "
            "this session, otherwise returns ToolError('precondition_failed'). Empty table means no eligible sets."
        ),
    )
    def weekly_sets_per_muscle(
        log_id: str, weeks: int = 6, allowed_exercise_ids: list[str] | None = None
    ) -> dict[str, Any]:
        with session.lock:
            if error := session.precondition(log_id, "weekly_sets_per_muscle"):
                return _dump(error, WEEKLY_VERSION)
            if weeks < 1:
                return _dump(ToolError(code="invalid_weeks", message="weeks must be at least 1"), WEEKLY_VERSION)
            allowed = session.allowed(log_id, allowed_exercise_ids)
            result = _weekly_sets_per_muscle(
                session.store,
                log_id,
                weeks=weeks,
                allowed_exercise_ids=None if allowed is None else sorted(allowed),
                ids=session.ids,
            )
            return _dump(result, WEEKLY_VERSION)

    @server.tool(
        name="compute_e1rm_and_drift",
        description=(
            "Compute the per-session e1RM series (Epley, Brzycki, RPE-adjusted), its weekly trend, and RPE drift at "
            "comparable load for one exercise_id (valid sets: non-warmup, non-failed, reps<=10). Precondition: "
            "check_data_sufficiency must have been called for log_id in this session, otherwise returns "
            "ToolError('precondition_failed'). Returns ToolError if there are fewer than 4 valid sessions or the "
            "exercise is excluded. drift_error says why RPE drift is missing; the e1RM trend is still valid then."
        ),
    )
    def compute_e1rm_and_drift(
        log_id: str,
        exercise_id: str,
        bodyweight_kg: float | None = None,
        allowed_exercise_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        with session.lock:
            if error := session.precondition(log_id, "compute_e1rm_and_drift"):
                return _dump(error, E1RM_VERSION)
            allowed = session.allowed(log_id, allowed_exercise_ids)
            if allowed is not None and exercise_id not in allowed:
                error = ToolError(code="exercise_not_allowed", message=f"{exercise_id} is excluded from this analysis")
                return _dump(error, E1RM_VERSION)
            result = _compute_e1rm_and_drift(
                session.store, log_id, exercise_id, bodyweight_kg, ids=session.ids
            )
            return _dump(result, E1RM_VERSION)

    @server.tool(
        name="uncoupled_load_analyzer",
        description=(
            "Compute uncoupled 7-day acute load, 28-day prior chronic weekly load, and their heuristic ratio (never an "
            "injury predictor). Precondition: check_data_sufficiency must have been called for log_id in this session, "
            "otherwise returns ToolError('precondition_failed'). Returns ToolError('insufficient_history') below 35 days."
        ),
    )
    def uncoupled_load_analyzer(
        log_id: str,
        metric: Literal["tonnage", "rpe_weighted"] = "tonnage",
        allowed_exercise_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        with session.lock:
            if error := session.precondition(log_id, "uncoupled_load_analyzer"):
                return _dump(error, LOAD_VERSION)
            result = _uncoupled_load_analyzer(
                session.store,
                log_id,
                metric=metric,
                ids=session.ids,
                allowed_exercise_ids=session.allowed(log_id, allowed_exercise_ids),
            )
            return _dump(result, LOAD_VERSION)

    @server.tool(name="retrieve_knowledge", description=RETRIEVE_KNOWLEDGE_DESCRIPTION)
    def retrieve_knowledge(
        query: str,
        allowed_exercise_ids: list[str],
        allowed_hypotheses: list[str],
        k: int = 5,
        excluded_exercise_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        with session.lock:
            result = _retrieve_knowledge(
                query=query,
                allowed_exercise_ids=allowed_exercise_ids,
                allowed_hypotheses=allowed_hypotheses,
                k=k,
                excluded_exercise_ids=excluded_exercise_ids,
                retriever=knowledge_retriever,
            )
            return _dump(result, KNOWLEDGE_VERSION)

    return server


def load_retriever(index_dir: Path = DEFAULT_INDEX_DIR) -> HybridRetriever | None:
    """Open the index written by ``python -m src.rag.build``; ``None`` if it has not been built."""
    from src.rag.bm25 import BM25Index
    from src.rag.store import ChromaVectorStore, HashEmbedder, SentenceTransformerEmbedder

    manifest = index_dir / "manifest.json"
    if not manifest.is_file():
        return None
    model = str(json.loads(manifest.read_text(encoding="utf-8"))["embedding_model"])
    embedder = HashEmbedder() if model == HashEmbedder().model_name else SentenceTransformerEmbedder(model)
    return HybridRetriever(
        ChromaVectorStore(index_dir / "chroma", embedder), BM25Index.load(index_dir / "bm25_chunks.json")
    )


def main() -> None:
    """Run the MCP server over stdio transport."""
    create_server(knowledge_retriever=load_retriever()).run(transport="stdio")


if __name__ == "__main__":
    main()
