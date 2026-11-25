"""DuckDB store of canonical sets, notes and tool values (plan §2.2, §5.7)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import duckdb

from src.ingest.model import CanonicalSet, Note
from src.tools.common import Value

_SET_COLUMNS = list(CanonicalSet.model_fields)
_NOTE_COLUMNS = list(Note.model_fields)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sets (
    set_id VARCHAR NOT NULL, log_id VARCHAR NOT NULL, workout_ts TIMESTAMP NOT NULL, workout_name VARCHAR NOT NULL,
    exercise_name_raw VARCHAR NOT NULL, exercise_id VARCHAR, set_index INTEGER NOT NULL, set_type VARCHAR NOT NULL,
    weight_kg DOUBLE, source_unit VARCHAR NOT NULL, reps INTEGER, rpe DOUBLE, failed BOOLEAN NOT NULL,
    distance DOUBLE, duration_s DOUBLE, set_note VARCHAR, workout_note VARCHAR, superset_id VARCHAR,
    source_app VARCHAR NOT NULL, row_order BIGINT NOT NULL, PRIMARY KEY (log_id, set_id));
CREATE TABLE IF NOT EXISTS workouts (
    log_id VARCHAR NOT NULL, workout_ts TIMESTAMP NOT NULL, workout_name VARCHAR NOT NULL, source_app VARCHAR NOT NULL,
    PRIMARY KEY (log_id, workout_ts, workout_name));
CREATE TABLE IF NOT EXISTS notes (
    note_id VARCHAR NOT NULL, log_id VARCHAR NOT NULL, scope VARCHAR NOT NULL, workout_ts TIMESTAMP NOT NULL,
    workout_name VARCHAR NOT NULL, exercise_name_raw VARCHAR, exercise_id VARCHAR, text VARCHAR NOT NULL,
    PRIMARY KEY (log_id, note_id));
CREATE TABLE IF NOT EXISTS ingest_log (
    log_id VARCHAR NOT NULL, file_sha256 VARCHAR NOT NULL, source_app VARCHAR NOT NULL, rows_read INTEGER NOT NULL,
    sets_added INTEGER NOT NULL, workouts_added INTEGER NOT NULL, flags VARCHAR NOT NULL);
CREATE TABLE IF NOT EXISTS "values" (
    run_id VARCHAR NOT NULL, value_id VARCHAR NOT NULL, payload VARCHAR NOT NULL, PRIMARY KEY (run_id, value_id));
"""


@dataclass(frozen=True)
class AppendResult:
    """What ``append_sets`` did."""

    sets_added: int
    workouts_added: int
    workouts_known: int
    duplicates: tuple[CanonicalSet, ...]
    changed_workouts: tuple[tuple[datetime, str], ...]


class SetStore:
    """Thin wrapper around one DuckDB connection; reads return models, writes are transactional."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._con = connection
        self._con.execute(_SCHEMA)

    def close(self) -> None:
        """Close the connection."""
        self._con.close()

    def __enter__(self) -> SetStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def append_sets(
        self, log_id: str, sets: Iterable[CanonicalSet], ingest_entry: Mapping[str, Any] | None = None
    ) -> AppendResult:
        """Add the workouts of ``sets`` that this log does not contain yet, with their notes.

        A known workout is left as it is. If its content differs from the new file, it is reported in
        ``changed_workouts``. Rows with the same content hash are stored once and reported as ``duplicates``.
        """
        if not log_id:
            raise ValueError("log_id must not be empty")
        by_workout: dict[tuple[datetime, str], list[CanonicalSet]] = {}
        for s in sets:
            by_workout.setdefault((s.workout_ts, s.workout_name), []).append(s)

        duplicates: list[CanonicalSet] = []
        changed: list[tuple[datetime, str]] = []
        added = new_workouts = known = 0
        all_ids = {r[0] for r in self._con.execute("SELECT set_id FROM sets WHERE log_id = ?", [log_id]).fetchall()}
        order = self._one("SELECT coalesce(max(row_order), -1) + 1 FROM sets WHERE log_id = ?", [log_id])
        self._con.execute("BEGIN")
        try:
            for key, rows in by_workout.items():
                unique: dict[str, CanonicalSet] = {}
                for s in rows:
                    if s.set_id in unique:
                        duplicates.append(s)
                    else:
                        unique[s.set_id] = s
                if self._is_known(log_id, key):
                    known += 1
                    if not set(unique) <= all_ids or not self._stored_ids(log_id, key) <= set(unique):
                        changed.append(key)
                    continue
                new_workouts += 1
                first = rows[0]
                for set_id in [i for i in unique if i in all_ids]:  # same row under another workout name
                    duplicates.append(unique.pop(set_id))
                all_ids |= set(unique)
                self._con.execute("INSERT INTO workouts VALUES (?, ?, ?, ?)", [log_id, *key, first.source_app])
                for s in unique.values():
                    row = s.model_copy(update={"log_id": log_id}).model_dump(mode="python")
                    marks = ", ".join("?" * (len(_SET_COLUMNS) + 1))
                    params = [str(row[c]) if c == "set_type" else row[c] for c in _SET_COLUMNS]
                    cols = ", ".join([*_SET_COLUMNS, "row_order"])
                    self._con.execute(f"INSERT INTO sets ({cols}) VALUES ({marks})", [*params, order])
                    order += 1
                    added += 1
                for note in _notes_of(log_id, unique.values()):
                    self._con.execute(
                        f"INSERT INTO notes ({', '.join(_NOTE_COLUMNS)}) VALUES ({', '.join('?' * len(_NOTE_COLUMNS))})",
                        [note.model_dump()[c] for c in _NOTE_COLUMNS],
                    )
            if ingest_entry is not None:
                self._con.execute(
                    "INSERT INTO ingest_log VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        log_id,
                        ingest_entry["file_sha256"],
                        ingest_entry["source_app"],
                        ingest_entry["rows_read"],
                        added,
                        new_workouts,
                        json.dumps(ingest_entry.get("flags", [])),
                    ],
                )
            self._con.execute("COMMIT")
        except BaseException:
            self._con.execute("ROLLBACK")
            raise
        return AppendResult(added, new_workouts, known, tuple(duplicates), tuple(changed))

    def get_sets(self, log_id: str, filters: Mapping[str, Any] | None = None) -> list[CanonicalSet]:
        """Return the sets of a log in time order.

        Filters: ``exercise_id``, ``exercise_name_raw``, ``set_type``, ``workout_ts`` (exact), and the inclusive dates
        ``since`` and ``until``. An unknown filter is an error, so a typo cannot return unfiltered data.
        """
        where, params = ["log_id = ?"], [log_id]
        for key, value in (filters or {}).items():
            if key in ("exercise_id", "exercise_name_raw", "set_type", "workout_ts"):
                where.append(f"{key} = ?")
                params.append(str(value) if key == "set_type" else value)
            elif key == "since":
                where.append("workout_ts >= ?")
                params.append(datetime.combine(_as_date(value), time.min))
            elif key == "until":
                where.append("workout_ts < ?")
                params.append(datetime.combine(_as_date(value) + timedelta(days=1), time.min))
            else:
                raise ValueError(f"unknown filter {key!r}")
        rows = self._con.execute(
            f"SELECT {', '.join(_SET_COLUMNS)} FROM sets WHERE {' AND '.join(where)} ORDER BY workout_ts, row_order",
            params,
        ).fetchall()
        return [CanonicalSet(**dict(zip(_SET_COLUMNS, r, strict=True))) for r in rows]

    def get_notes(self, log_id: str) -> list[Note]:
        """Return the distinct notes of a log in time order; workout notes before exercise notes."""
        rows = self._con.execute(
            f"SELECT {', '.join(_NOTE_COLUMNS)} FROM notes WHERE log_id = ? "
            "ORDER BY workout_ts, workout_name, scope DESC, exercise_name_raw, text",
            [log_id],
        ).fetchall()
        return [Note(**dict(zip(_NOTE_COLUMNS, r, strict=True))) for r in rows]

    def log_ids(self) -> list[str]:
        """Return all stored log ids."""
        return [r[0] for r in self._con.execute("SELECT DISTINCT log_id FROM sets ORDER BY 1").fetchall()]

    def assign_exercise_ids(self, log_id: str, matcher: Callable[[str], str | None]) -> list[str]:
        """Fill missing exercise ids of sets and notes by raw name; return the names that stay unmatched.

        A matcher result of ``None`` or ``"unknown"`` leaves the name unmatched. Ids already set are kept.
        """
        names = self._con.execute(
            "SELECT DISTINCT exercise_name_raw FROM sets WHERE log_id = ? AND exercise_id IS NULL ORDER BY 1", [log_id]
        ).fetchall()
        unmatched: list[str] = []
        for (name,) in names:
            exercise_id = matcher(name)
            if exercise_id in (None, "unknown"):
                unmatched.append(name)
                continue
            for table in ("sets", "notes"):
                self._con.execute(
                    f"UPDATE {table} SET exercise_id = ? "
                    "WHERE log_id = ? AND exercise_name_raw = ? AND exercise_id IS NULL",
                    [exercise_id, log_id, name],
                )
        return unmatched

    def save_values(self, run_id: str, values: Iterable[Value]) -> None:
        """Store the values of one run. A value id can be stored only once per run."""
        for v in values:
            self._con.execute('INSERT INTO "values" VALUES (?, ?, ?)', [run_id, v.value_id, v.model_dump_json()])

    def get_values(self, run_id: str) -> dict[str, Value]:
        """Return the values of a run by value id."""
        rows = self._con.execute('SELECT value_id, payload FROM "values" WHERE run_id = ?', [run_id]).fetchall()
        return {vid: Value.model_validate_json(payload) for vid, payload in rows}

    def _is_known(self, log_id: str, key: tuple[datetime, str]) -> bool:
        sql = "SELECT count(*) FROM workouts WHERE log_id = ? AND workout_ts = ? AND workout_name = ?"
        return bool(self._one(sql, [log_id, *key]))

    def _stored_ids(self, log_id: str, key: tuple[datetime, str]) -> set[str]:
        rows = self._con.execute(
            "SELECT set_id FROM sets WHERE log_id = ? AND workout_ts = ? AND workout_name = ?", [log_id, *key]
        ).fetchall()
        return {r[0] for r in rows}

    def _one(self, sql: str, params: list[Any]) -> Any:
        row = self._con.execute(sql, params).fetchone()
        assert row is not None
        return row[0]


def open_store(path: str | Path = ":memory:") -> SetStore:
    """Open (and create if needed) a store. The default is in memory."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return SetStore(duckdb.connect(str(path)))


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _notes_of(log_id: str, sets: Iterable[CanonicalSet]) -> list[Note]:
    """Distinct notes of one workout. A note repeated on every row of its workout or exercise becomes one note."""
    notes: dict[str, Note] = {}
    for s in sets:
        for scope, text, name in (
            ("workout", s.workout_note, None),
            ("exercise", s.set_note, s.exercise_name_raw),
        ):
            clean = (text or "").strip()
            if not clean:
                continue
            key = json.dumps([scope, s.workout_ts.isoformat(), s.workout_name, name, clean], ensure_ascii=False)
            note_id = hashlib.sha256(key.encode("utf-8")).hexdigest()
            notes[note_id] = Note(
                note_id=note_id,
                log_id=log_id,
                scope=scope,  # type: ignore[arg-type]
                workout_ts=s.workout_ts,
                workout_name=s.workout_name,
                exercise_name_raw=name,
                exercise_id=s.exercise_id if name else None,
                text=clean,
            )
    return list(notes.values())
