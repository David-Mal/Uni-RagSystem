"""Thin MCP server registering deterministic analysis and retrieval tools (issue M4, #35).

This is the ONLY module in the repository that imports from the ``mcp`` SDK (pinned to v2.3.0).
Safety gate and output verifier are intentionally NOT registered as MCP tools (plan §5.7).
Exposes tools only — no MCP resources or prompts.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from src.mcp_server.provisional_tools import (
    SessionSetStore,
    compute_e1rm_and_drift_provisional,
    ingest_workout_log_provisional,
    uncoupled_load_analyzer_provisional,
)
from src.rag.retrieve import HybridRetriever
from src.tools._common_provisional import ToolError
from src.tools.match_exercise import match_exercise_rag as _match_exercise_rag
from src.tools.retrieve_knowledge import (
    TOOL_DESCRIPTION as RETRIEVE_KNOWLEDGE_DESCRIPTION,
)
from src.tools.retrieve_knowledge import (
    retrieve_knowledge as _retrieve_knowledge,
)
from src.tools.sufficiency import check_data_sufficiency as _check_data_sufficiency
from src.tools.weekly_sets import weekly_sets_per_muscle as _weekly_sets_per_muscle

PINNED_MCP_SDK_VERSION = "2.3.0"


def _precondition_error(log_id: str, tool_name: str) -> dict[str, Any]:
    return ToolError(
        code="precondition_failed",
        message=(
            f"Tool '{tool_name}' cannot run for log_id='{log_id}' until "
            f"'check_data_sufficiency' has been called for that log_id in this session."
        ),
    ).model_dump()


def create_server(
    *,
    store: SessionSetStore | None = None,
    knowledge_retriever: HybridRetriever | None = None,
) -> MCPServer:
    """Create and configure the stdio MCPServer with session-scoped precondition state."""
    server = MCPServer("heuristic-load-fatigue-analyzer")
    session_store = store if store is not None else SessionSetStore()
    checked_log_ids: set[str] = set()

    @server.tool(
        name="ingest_workout_log",
        description=(
            "Parse, normalize, and store a workout log file (OpenGym/Strong/Hevy CSV) into the "
            "session store. Call this first when given a file path. Returns log_id, set/workout "
            "counts, unmatched exercise names, and notes. Returns ToolError on unreadable or "
            "unrecognized formats."
        ),
    )
    def ingest_workout_log(
        path: str,
        app_hint: str | None = None,
        log_id: str | None = None,
    ) -> dict[str, Any]:
        return ingest_workout_log_provisional(session_store, path, app_hint=app_hint, log_id=log_id)

    @server.tool(
        name="match_exercise_rag",
        description=(
            "Resolve a raw exercise name string to a canonical free-exercise-db exercise_id using "
            "the 4-stage cascade (alias -> fuzzy -> hybrid retrieval -> unknown). Returns "
            "exercise_id='unknown' when confidence is low; never guesses."
        ),
    )
    def match_exercise_rag(name: str) -> dict[str, Any]:
        return _match_exercise_rag(name).model_dump()

    @server.tool(
        name="check_data_sufficiency",
        description=(
            "Assess whether a stored workout log meets data-sufficiency thresholds (history span, "
            "sessions per exercise, RPE coverage, comparable load, max gap, matched exercises). "
            "MUST be called for a log_id before calling any analysis tool (weekly_sets_per_muscle, "
            "compute_e1rm_and_drift, uncoupled_load_analyzer). Empty allowed_analyses means full "
            "abstention; partial lists mean partial abstention."
        ),
    )
    def check_data_sufficiency(
        log_id: str,
        allowed_exercise_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        checked_log_ids.add(log_id)
        return _check_data_sufficiency(
            session_store, log_id, allowed_exercise_ids=allowed_exercise_ids
        ).model_dump()

    @server.tool(
        name="weekly_sets_per_muscle",
        description=(
            "Compute effective weekly sets per muscle (primary=1.0, secondary=0.5, Monday-start "
            "weeks, non-warmup, non-failed, RPE>=7 when logged). Precondition: "
            "check_data_sufficiency must have been called for log_id in this session, otherwise "
            "returns ToolError('precondition_failed'). Empty table means no eligible sets."
        ),
    )
    def weekly_sets_per_muscle(
        log_id: str,
        weeks: int = 6,
        allowed_exercise_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if log_id not in checked_log_ids:
            return _precondition_error(log_id, "weekly_sets_per_muscle")
        return _weekly_sets_per_muscle(
            session_store, log_id, weeks=weeks, allowed_exercise_ids=allowed_exercise_ids
        ).model_dump()

    @server.tool(
        name="compute_e1rm_and_drift",
        description=(
            "Compute per-session Epley and Brzycki e1RM series and weekly trend slope for one "
            "exercise_id (valid sets: non-warmup, non-failed, reps<=10). Precondition: "
            "check_data_sufficiency must have been called for log_id in this session, otherwise "
            "returns ToolError('precondition_failed'). Returns ToolError if <4 valid sessions."
        ),
    )
    def compute_e1rm_and_drift(
        log_id: str,
        exercise_id: str,
        bodyweight_kg: float | None = None,
    ) -> dict[str, Any]:
        if log_id not in checked_log_ids:
            return _precondition_error(log_id, "compute_e1rm_and_drift")
        return compute_e1rm_and_drift_provisional(
            session_store, log_id, exercise_id, bodyweight_kg=bodyweight_kg
        )

    @server.tool(
        name="uncoupled_load_analyzer",
        description=(
            "Compute uncoupled 7-day acute load, 28-day prior chronic weekly load, and their "
            "heuristic ratio (never an injury predictor). Precondition: check_data_sufficiency "
            "must have been called for log_id in this session, otherwise returns "
            "ToolError('precondition_failed')."
        ),
    )
    def uncoupled_load_analyzer(
        log_id: str,
        metric: str = "tonnage",
    ) -> dict[str, Any]:
        if log_id not in checked_log_ids:
            return _precondition_error(log_id, "uncoupled_load_analyzer")
        return uncoupled_load_analyzer_provisional(session_store, log_id, metric=metric)

    @server.tool(
        name="retrieve_knowledge",
        description=RETRIEVE_KNOWLEDGE_DESCRIPTION,
    )
    def retrieve_knowledge(
        query: str,
        allowed_exercise_ids: list[str],
        allowed_hypotheses: list[str],
        k: int = 5,
        excluded_exercise_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        res = _retrieve_knowledge(
            query=query,
            allowed_exercise_ids=allowed_exercise_ids,
            allowed_hypotheses=allowed_hypotheses,
            k=k,
            excluded_exercise_ids=excluded_exercise_ids,
            retriever=knowledge_retriever,
        )
        return res.model_dump()

    return server


def main() -> None:
    """Run the MCP server over stdio transport."""
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
