"""Shared result models of all tools (issue D3): values with provenance, errors, ids and config hashing.

The contract for names, units and tolerances is ``docs/indicator-spec.md``; thresholds are in ``configs/indicators.yaml``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
INDICATORS_CONFIG_PATH = REPO_ROOT / "configs" / "indicators.yaml"

_NAME_RE = re.compile(r"[a-z0-9_]+")


class _Model(BaseModel):
    """Unknown keys are rejected, so a typo in a field name fails instead of being dropped."""

    model_config = ConfigDict(extra="forbid")


class Provenance(_Model):
    """Where a number came from."""

    formula: str
    input_row_ids: list[str]
    tool_version: str
    config_hash: str


class Value(_Model):
    """One tool output with an id that is unique in the run. Floats must be finite."""

    value_id: str
    name: str
    value: float | int | str
    unit: str | None
    provenance: Provenance

    @field_validator("value")
    @classmethod
    def _finite(cls, value: float | int | str) -> float | int | str:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("value must be finite")
        return value


class ToolError(_Model):
    """Structured tool failure. Tools return it instead of raising for expected conditions."""

    code: str
    message: str


class ToolResult(BaseModel):
    """Base result of every tool; tools subclass it and may add fields."""

    tool_version: str
    values: list[Value] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ValueIdFactory:
    """Per-run counter producing ``v_<name>_<NNNN>``; share one instance across the tools of a run."""

    def __init__(self) -> None:
        self._n = 0

    def new(self, name: str) -> str:
        """Return the next id for ``name`` (lowercase ``[a-z0-9_]``)."""
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f"value name {name!r} must match [a-z0-9_]+")
        self._n += 1
        return f"v_{name}_{self._n:04d}"


def config_hash(cfg: Mapping[str, Any]) -> str:
    """Stable sha256 of the config as sorted, compact JSON. Fails on values that JSON cannot represent."""
    text = json.dumps(dict(cfg), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_indicator_config(path: Path | None = None) -> dict[str, Any]:
    """Read ``configs/indicators.yaml`` (or ``path``) as a dict of sections."""
    with (path or INDICATORS_CONFIG_PATH).open(encoding="utf-8") as stream:
        cfg = yaml.safe_load(stream)
    if not isinstance(cfg, dict):
        raise ValueError("indicator config must be a mapping of sections")
    return cfg
