"""PROVISIONAL stand-in for ``src/tools/common.py`` (owned by issue D3, #5). Delete when D3 merges."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    formula: str
    input_row_ids: list[str]
    tool_version: str
    config_hash: str


class Value(BaseModel):
    value_id: str
    name: str
    value: float | int | str
    unit: str | None
    provenance: Provenance


class ToolError(BaseModel):
    code: str
    message: str


class ToolResult(BaseModel):
    tool_version: str
    values: list[Value] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ValueIdFactory:
    def __init__(self) -> None:
        self._n = 0

    def new(self, name: str) -> str:
        self._n += 1
        return f"v_{name}_{self._n:04d}"


def config_hash(cfg: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
