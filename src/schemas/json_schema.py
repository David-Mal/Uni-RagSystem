"""JSON Schema export, including the constrained-decoding schema for the extractor (plan §6.5)."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.schemas.models import UNKNOWN_EXERCISE_ID, Claim, ExtractionResult, Load
from src.schemas.version import SCHEMA_VERSION

EXPORTED_MODELS: dict[str, type[BaseModel]] = {
    "load": Load,
    "extraction_result": ExtractionResult,
    "claim": Claim,
}
"""File stem -> model for every schema written to ``schemas/``."""


def model_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return the validation JSON Schema of ``model`` with the schema version in ``$comment``."""
    schema = model.model_json_schema(mode="validation")
    schema["$comment"] = f"schema_version={SCHEMA_VERSION}"
    return schema


def extraction_json_schema(exercise_ids: Iterable[str]) -> dict[str, Any]:
    """Schema for ``ExtractionResult`` with ``exercise_id`` restricted to ``exercise_ids`` plus ``unknown``.

    Used for constrained decoding (Outlines). ``unknown`` is always legal so the grammar never forces a
    guess. Ids are de-duplicated and sorted so the schema (and its hash) is stable for a given id set.
    """
    ids = sorted({*exercise_ids, UNKNOWN_EXERCISE_ID})
    schema = copy.deepcopy(model_json_schema(ExtractionResult))
    prop = schema["properties"]["exercise_id"]
    prop.pop("pattern", None)
    prop["enum"] = ids
    return schema


def export_schemas(out_dir: Path) -> list[Path]:
    """Write one ``<stem>.json`` per model in ``EXPORTED_MODELS`` to ``out_dir`` and return the paths.

    Output is deterministic (sorted keys, 2-space indent, LF, trailing newline) so the committed files
    can be checked for staleness in tests.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for stem, model in EXPORTED_MODELS.items():
        path = out_dir / f"{stem}.json"
        path.write_text(render_schema(model), encoding="utf-8", newline="\n")
        written.append(path)
    return written


def render_schema(model: type[BaseModel]) -> str:
    """Serialize a model's schema exactly as it is written to disk."""
    return json.dumps(model_json_schema(model), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
