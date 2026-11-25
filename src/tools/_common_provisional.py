"""PROVISIONAL stand-in for ``src/tools/common.py`` (owned by issue D3, #5). Delete when D3 merges.

Mirrors the exact D3 contract used in F7: ``Provenance``, ``Value``, ``ToolError``, ``ToolResult``,
``ValueIdFactory`` (``v_<name>_<NNNN>``), and ``config_hash`` (stable sha256 of sorted JSON).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    """Where a number came from."""

    formula: str
    input_row_ids: list[str]
    tool_version: str
    config_hash: str


class Value(BaseModel):
    """One numeric (or string) tool output with a run-unique id."""

    value_id: str
    name: str
    value: float | int | str
    unit: str | None
    provenance: Provenance


class ToolError(BaseModel):
    """Structured tool failure."""

    code: str
    message: str


class ToolResult(BaseModel):
    """Base result of every tool."""

    tool_version: str
    values: list[Value] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ValueIdFactory:
    """Per-run counter producing ``v_<name>_<NNNN>`` ids."""

    def __init__(self) -> None:
        self._n = 0

    def new(self, name: str) -> str:
        """Return the next id for ``name``."""
        self._n += 1
        return f"v_{name}_{self._n:04d}"


def config_hash(cfg: dict[str, Any]) -> str:
    """Stable sha256 of the config as sorted, compact JSON."""
    return hashlib.sha256(
        json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
