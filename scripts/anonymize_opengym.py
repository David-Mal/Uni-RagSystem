"""Anonymize an OpenGym CSV export before committing it as a fixture (issues D2, F1).

What it does:
- keeps the file byte-compatible with the app export (UTF-8 BOM, line endings, column order, quoting);
- optionally shifts every date/timestamp by a whole number of weeks (keeps weekdays);
- optionally blanks free-text columns;
- prints every distinct non-empty free-text value so a human can check it before committing.

Weights, reps, RPE and exercise names are never touched.

Usage::

    python scripts/anonymize_opengym.py RAW.csv data/fixtures/opengym/<name>_anonymized.csv [--shift-weeks -3]
        [--blank workout_note note set_note]
"""

from __future__ import annotations

import argparse
import csv
import io
from datetime import datetime, timedelta
from pathlib import Path

BOM = b"\xef\xbb\xbf"
DATE_COLUMNS: dict[str, str] = {
    "date": "%Y-%m-%d",
    "start_time": "%Y-%m-%d %H:%M",
    "end_time": "%Y-%m-%d %H:%M",
}
"""Timestamp columns and their exact OpenGym format (no seconds, no timezone)."""

FREE_TEXT_COLUMNS = ("workout", "workout_note", "note", "set_note")
"""Columns that can contain user-written text and must be reviewed by a human."""


def anonymize(raw: bytes, shift_weeks: int = 0, blank: tuple[str, ...] = ()) -> tuple[bytes, dict[str, set[str]]]:
    """Return the anonymized file bytes and the distinct free-text values left in it.

    Raises ``ValueError`` for an unknown timestamp format or a ``blank`` column that does not exist.
    """
    has_bom = raw.startswith(BOM)
    text = raw[len(BOM) :].decode("utf-8") if has_bom else raw.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"

    reader = csv.DictReader(io.StringIO(text, newline=""))
    fieldnames = list(reader.fieldnames or [])
    missing = [c for c in blank if c not in fieldnames]
    if missing:
        raise ValueError(f"cannot blank unknown columns: {missing}")

    delta = timedelta(weeks=shift_weeks)
    out_rows: list[dict[str, str]] = []
    free_text: dict[str, set[str]] = {c: set() for c in FREE_TEXT_COLUMNS if c in fieldnames}
    for line_no, row in enumerate(reader, start=2):
        for column, fmt in DATE_COLUMNS.items():
            value = row.get(column, "")
            if value and shift_weeks:
                try:
                    row[column] = (datetime.strptime(value, fmt) + delta).strftime(fmt)
                except ValueError as exc:
                    raise ValueError(f"line {line_no}: {column}={value!r} does not match {fmt}") from exc
        for column in blank:
            row[column] = ""
        for column, seen in free_text.items():
            if row[column]:
                seen.add(row[column])
        out_rows.append(row)

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator=newline)
    writer.writeheader()
    writer.writerows(out_rows)
    data = buffer.getvalue().encode("utf-8")
    return (BOM + data if has_bom else data), free_text


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; refuses to write into ``data/golden/``."""
    parser = argparse.ArgumentParser(description="Anonymize an OpenGym CSV export.")
    parser.add_argument("raw", type=Path, help="raw export (keep it outside the repo)")
    parser.add_argument("out", type=Path, help="anonymized fixture path")
    parser.add_argument("--shift-weeks", type=int, default=0, help="shift all dates by N weeks (keeps weekdays)")
    parser.add_argument("--blank", nargs="*", default=[], help="columns to empty, e.g. workout_note note")
    args = parser.parse_args(argv)

    if "golden" in {part.lower() for part in args.out.resolve().parts}:
        parser.error("refusing to write into data/golden/")

    data, free_text = anonymize(args.raw.read_bytes(), args.shift_weeks, tuple(args.blank))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f"wrote {args.out} ({len(data)} bytes)")
    print("Free-text values left in the file (check that none identifies a person):")
    for column, values in free_text.items():
        print(f"  {column}: {sorted(values) if values else '(empty)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
