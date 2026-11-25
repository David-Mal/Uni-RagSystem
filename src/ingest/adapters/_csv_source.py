"""Adapter-private CSV lexical helpers, not a D4 normalization or error layer."""

from collections.abc import Callable, Sequence
import csv
import io
import math
from pathlib import Path
import re


def header_fields(header: Sequence[str] | str) -> tuple[str, ...] | None:
    """Accept decoded names or one CSV header record without probing files."""
    if isinstance(header, str):
        try:
            records = list(csv.reader(io.StringIO(header.removeprefix('\ufeff')), strict=True))
        except csv.Error:
            return None
        if len(records) != 1:
            return None
        values = tuple(records[0])
    elif isinstance(header, Sequence):
        values = tuple(header)
    else:
        return None
    if not values or not all(isinstance(item, str) and item for item in values):
        return None
    values = (values[0].removeprefix('\ufeff'), *values[1:])
    return values if all(values) and len(values) == len(set(values)) else None


def read_csv(
    source: str | Path, detect: Callable[[Sequence[str] | str], bool], error: type[ValueError],
) -> tuple[tuple[str, ...], tuple[tuple[int, dict[str, str]], ...]]:
    """Read exactly the supported UTF-8 comma CSV, preserving record order/text."""
    try:
        with Path(source).open('r', encoding='utf-8-sig', newline='') as stream:
            reader = csv.reader(stream, strict=True)
            original = next(reader, None)
            header = None if original is None else header_fields(original)
            if header is None or not detect(header):
                raise error("unsupported, missing, duplicate or ambiguous headers")
            rows = []
            for number, values in enumerate(reader, 1):
                if len(values) != len(header):
                    raise error(f"data row {number}: expected {len(header)} fields, got {len(values)}")
                rows.append((number, dict(zip(header, values, strict=True))))
            return header, tuple(rows)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise error(f"cannot read UTF-8 comma CSV: {exc}") from exc


def number(value: str, field: str, row: int, error: type[ValueError]) -> float | None:
    """Only empty cells are missing; parse finite plain ASCII decimal numbers."""
    if value == '':
        return None
    if not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', value):
        raise error(f"data row {row}: {field} must be a plain decimal number or empty")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise error(f"data row {row}: {field} must be finite")
    return parsed


def integer(
    value: str, field: str, row: int, error: type[ValueError], *, required: bool = False, minimum: int | None = None,
) -> int | None:
    if value == '' and not required:
        return None
    if not re.fullmatch(r'-?[0-9]+', value):
        raise error(f"data row {row}: {field} must be an integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise error(f"data row {row}: {field} cannot be represented as an integer") from exc
    if minimum is not None and parsed < minimum:
        raise error(f"data row {row}: {field} must be at least {minimum}")
    return parsed
