"""Adapter interface and registry (plan §2.2). A new app needs one adapter class and its fixtures."""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from src.ingest.errors import IngestError
from src.ingest.model import CanonicalSets


@dataclass(frozen=True)
class SourceProbe:
    """What an adapter may look at to recognize a file, without reading all of it.

    ``header`` holds the fields of the first CSV record (BOM removed), or ``None`` if the first line is not UTF-8 text.
    Formats that are not CSV can inspect ``path``.
    """

    path: Path
    header: tuple[str, ...] | None

    @classmethod
    def from_path(cls, path: str | Path) -> SourceProbe:
        """Read the first record of ``path``. A missing or empty file raises ``IngestError``."""
        source = Path(path)
        if not source.is_file():
            raise IngestError(f"file not found: {source.name}")
        if source.stat().st_size == 0:
            raise IngestError("file is empty")
        try:
            with source.open(encoding="utf-8-sig", newline="") as stream:
                header = tuple(next(csv.reader(stream), ()))
        except (UnicodeDecodeError, csv.Error):
            return cls(source, None)
        except OSError as exc:
            raise IngestError(f"cannot read {source.name}") from exc
        return cls(source, header)


class BaseAdapter(ABC):
    """Converts one app's export to canonical sets. Parsing problems raise ``IngestError``."""

    name: str
    """Short app name, also used as ``app_hint`` and ``source_app`` (e.g. ``opengym``)."""

    @abstractmethod
    def detect(self, probe: SourceProbe) -> bool:
        """Return whether this adapter can read the file. Must be false for every other format."""

    @abstractmethod
    def to_canonical(self, source: Path) -> CanonicalSets:
        """Read the whole file at ``source``. The adapter decides how to read it."""


class AdapterRegistry:
    """The adapters tried by ``ingest_workout_log``."""

    def __init__(self, adapters: Iterable[BaseAdapter] = ()) -> None:
        self._adapters: dict[str, BaseAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: BaseAdapter) -> None:
        """Add an adapter; a second one with the same name is an error."""
        if adapter.name in self._adapters:
            raise ValueError(f"adapter {adapter.name!r} is already registered")
        self._adapters[adapter.name] = adapter

    def __iter__(self) -> Iterator[BaseAdapter]:
        return iter(self._adapters.values())

    def select(self, probe: SourceProbe, app_hint: str | None = None) -> BaseAdapter:
        """Return the only adapter that recognizes the file. A hint restricts the choice but never skips detection."""
        if app_hint is not None and app_hint not in self._adapters:
            raise IngestError(f"unknown app {app_hint!r}; known: {sorted(self._adapters)}")
        candidates = [a for a in self if app_hint in (None, a.name) and a.detect(probe)]
        if not candidates:
            raise IngestError("unknown format")
        if len(candidates) > 1:
            raise IngestError(f"ambiguous format: {sorted(a.name for a in candidates)}; pass app_hint")
        return candidates[0]
