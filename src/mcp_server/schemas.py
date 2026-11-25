"""Pydantic input and output models for all MCP tools (issue M4, #35; plan §5.7).

Zero MCP SDK imports live in this module. Contract tests compare the JSON input schemas
returned by ``MCPServer.list_tools()`` against the input models defined here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from src.ingest import IngestResult
from src.tools.common import ToolError
from src.tools.e1rm import E1rmResult
from src.tools.load import LoadResult
from src.tools.match_exercise import MatchResult
from src.tools.retrieve_knowledge import KnowledgeResult
from src.tools.sufficiency import SufficiencyResult
from src.tools.weekly_sets import WeeklySetsResult

INGEST_TOOL_VERSION = "ingest_workout_log-1.0.0"


class IngestWorkoutLogInput(BaseModel):
    path: str
    app_hint: str | None = None
    log_id: str | None = None


class MatchExerciseInput(BaseModel):
    name: str


class CheckDataSufficiencyInput(BaseModel):
    log_id: str
    allowed_exercise_ids: list[str] | None = None


class WeeklySetsInput(BaseModel):
    log_id: str
    weeks: int = 6
    allowed_exercise_ids: list[str] | None = None


class ComputeE1rmInput(BaseModel):
    log_id: str
    exercise_id: str
    bodyweight_kg: float | None = None
    allowed_exercise_ids: list[str] | None = None


class UncoupledLoadInput(BaseModel):
    log_id: str
    metric: Literal["tonnage", "rpe_weighted"] = "tonnage"
    allowed_exercise_ids: list[str] | None = None


class RetrieveKnowledgeInput(BaseModel):
    query: str
    allowed_exercise_ids: list[str]
    allowed_hypotheses: list[str]
    k: int = 5
    excluded_exercise_ids: list[str] | None = None


TOOL_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "ingest_workout_log": IngestWorkoutLogInput,
    "match_exercise_rag": MatchExerciseInput,
    "check_data_sufficiency": CheckDataSufficiencyInput,
    "weekly_sets_per_muscle": WeeklySetsInput,
    "compute_e1rm_and_drift": ComputeE1rmInput,
    "uncoupled_load_analyzer": UncoupledLoadInput,
    "retrieve_knowledge": RetrieveKnowledgeInput,
}


class IngestWorkoutLogOutput(IngestResult):
    tool_version: str


class ToolErrorOutput(ToolError):
    tool_version: str


TOOL_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "ingest_workout_log": IngestWorkoutLogOutput,
    "match_exercise_rag": MatchResult,
    "check_data_sufficiency": SufficiencyResult,
    "weekly_sets_per_muscle": WeeklySetsResult,
    "compute_e1rm_and_drift": E1rmResult,
    "uncoupled_load_analyzer": LoadResult,
    "retrieve_knowledge": KnowledgeResult,
}
"""Successful outputs. Any tool may return ``ToolErrorOutput`` instead."""
