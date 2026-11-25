"""Pydantic input and output models for all MCP tools (issue M4, #35; plan §5.7).

Zero MCP SDK imports live in this module. Contract tests compare the JSON input schemas
returned by ``MCPServer.list_tools()`` against the input models defined here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestWorkoutLogInput(BaseModel):
    path: str
    app_hint: str | None = None
    log_id: str | None = None


class IngestWorkoutLogOutput(BaseModel):
    tool_version: str
    log_id: str
    set_count: int
    workout_count: int
    unmatched_names: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class MatchExerciseInput(BaseModel):
    name: str


class MatchExerciseOutput(BaseModel):
    tool_version: str
    exercise_id: str
    stage: str
    score: float
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class CheckDataSufficiencyInput(BaseModel):
    log_id: str
    allowed_exercise_ids: list[str] | None = None


class CheckDataSufficiencyOutput(BaseModel):
    tool_version: str
    sufficient: bool
    partial_abstention: bool = False
    reasons: list[str] = Field(default_factory=list)
    allowed_analyses: list[str] = Field(default_factory=list)
    eligible_exercise_ids: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class WeeklySetsInput(BaseModel):
    log_id: str
    weeks: int = 6
    allowed_exercise_ids: list[str] | None = None


class ComputeE1rmInput(BaseModel):
    log_id: str
    exercise_id: str
    bodyweight_kg: float | None = None


class UncoupledLoadInput(BaseModel):
    log_id: str
    metric: str = "tonnage"


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
