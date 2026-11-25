"""``ingest_workout_log``: detect the format, convert, normalize, store (plan §2.2)."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from src.ingest.adapters.base import AdapterRegistry, SourceProbe
from src.ingest.adapters.hevy import HevyAdapter
from src.ingest.adapters.opengym import OpenGymAdapter
from src.ingest.adapters.strong import StrongAdapter
from src.ingest.errors import IngestError
from src.ingest.model import IngestFlag, Note
from src.ingest.normalize import implausible_weight_flags, unit_mix_flags
from src.ingest.store import SetStore, open_store

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "index" / "logs.duckdb"
"""Used only when the caller passes no store; the folder is not tracked by git."""


class IngestResult(BaseModel):
    """Outcome of one ingestion. ``notes`` are all distinct notes of the log, for the safety gate."""

    model_config = ConfigDict(extra="forbid")

    log_id: str
    source_app: str
    counts: dict[str, int]
    unmatched_names: list[str]
    notes: list[Note]
    flags: list[IngestFlag]


def default_registry(unit_hint: Literal["kg", "lb"] | None = None) -> AdapterRegistry:
    """The adapters shipped with the project. ``unit_hint`` is for Strong files without a unit in the header."""
    return AdapterRegistry([OpenGymAdapter(), StrongAdapter(unit_hint), HevyAdapter()])


def ingest_workout_log(
    path: str | Path,
    app_hint: str | None = None,
    log_id: str | None = None,
    *,
    store: SetStore | None = None,
    registry: AdapterRegistry | None = None,
    matcher: Callable[[str], str | None] | None = None,
    unit_hint: Literal["kg", "lb"] | None = None,
) -> IngestResult:
    """Parse, normalize and store one export file.

    ``log_id`` is the namespace of one lifter: pass the same id to add a newer export, and only unseen workouts are
    appended. Without it, the id is derived from the file content, so the same file always gives the same id.
    ``matcher`` maps a raw exercise name to an exercise id (``None`` or ``"unknown"`` if it cannot). ``unit_hint`` is used
    only for formats that do not state the weight unit (Strong).

    Raises ``IngestError`` if the file cannot be read; nothing is stored in that case.
    """
    probe = SourceProbe.from_path(path)
    adapter = (registry if registry is not None else default_registry(unit_hint)).select(probe, app_hint)
    try:
        canonical = adapter.to_canonical(probe.path)
        digest = hashlib.sha256(probe.path.read_bytes()).hexdigest()
    except IngestError:
        raise
    except (ValidationError, UnicodeDecodeError, csv.Error, OSError) as exc:
        raise IngestError(f"{adapter.name}: cannot parse the file: {exc}") from exc
    if not len(canonical):
        raise IngestError("file contains no sets")

    log = log_id or f"log_{digest[:12]}"
    owned = store is None
    db = store if store is not None else open_store(DEFAULT_STORE_PATH)
    try:
        flags = [*canonical.flags, *implausible_weight_flags(canonical)]
        appended = db.append_sets(
            log,
            canonical,
            {
                "file_sha256": digest,
                "source_app": adapter.name,
                "rows_read": len(canonical),
                "flags": [f.model_dump() for f in flags],
            },
        )
        for s in appended.duplicates:
            flags.append(
                IngestFlag(
                    code="duplicate_set",
                    detail=f"{s.exercise_name_raw} on {s.workout_ts:%Y-%m-%d}, set {s.set_index}: stored once",
                )
            )
        for ts, name in appended.changed_workouts:
            flags.append(
                IngestFlag(
                    code="changed_workout",
                    detail=f"{name or 'workout'} at {ts:%Y-%m-%d %H:%M} differs from the stored version, which was kept",
                )
            )
        flags.extend(unit_mix_flags(db.get_sets(log)))
        unmatched = db.assign_exercise_ids(log, matcher if matcher is not None else lambda _: None)
        notes = db.get_notes(log)
    finally:
        if owned:
            db.close()
    return IngestResult(
        log_id=log,
        source_app=adapter.name,
        counts={
            "rows_read": len(canonical),
            "sets_added": appended.sets_added,
            "duplicates": len(appended.duplicates),
            "workouts_added": appended.workouts_added,
            "workouts_known": appended.workouts_known,
            "notes": len(notes),
        },
        unmatched_names=unmatched,
        notes=notes,
        flags=flags,
    )
