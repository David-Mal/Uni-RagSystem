"""Canonical set model, DuckDB store, normalization and app adapters."""

from src.ingest.adapters.base import AdapterRegistry, BaseAdapter, SourceProbe
from src.ingest.errors import IngestError
from src.ingest.model import CanonicalSet, CanonicalSets, IngestFlag, Note, SetType
from src.ingest.pipeline import IngestResult, ingest_workout_log
from src.ingest.store import SetStore, open_store

__all__ = [
    "AdapterRegistry",
    "BaseAdapter",
    "CanonicalSet",
    "CanonicalSets",
    "IngestError",
    "IngestFlag",
    "IngestResult",
    "Note",
    "SetStore",
    "SetType",
    "SourceProbe",
    "ingest_workout_log",
    "open_store",
]
