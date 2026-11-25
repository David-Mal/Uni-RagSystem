"""Numbers quoted in claim text: finding them and comparing them with tool values (plan §5.8, spec §7).

Rules
-----
Every digit in the text must belong to one of these, otherwise it is an error:

1. **Quantity.** ``102.5``, ``102,5`` (decimal comma), ``+0.4``, ``-0.4``, ``50%``, and each side of ``3x5`` or ``7-9``.
   It must match a referenced value within its tolerance. ``1,300`` is accepted as 1300 or as 1.3.
   An explicit sign must agree with the value. Without a sign the absolute value is compared ("fell by 0.4").
   A quantity followed by ``kg`` matches only values in kg; one followed by ``lb``, ``lbs`` or ``pounds`` never matches.
2. **Not a quantity**, skipped: the terms ``e1RM`` and ``1RM``; ISO dates (``2026-11-25``); a day with an English month
   name (``25 November``, ``Nov 25, 2026``); ordinals (``1st``, ``22nd``); ids listed in the claim's own ``numbers`` or
   ``citations``.

Anything else with a digit (``v2``, ``1e3``, ``1.2.3``, ``½``) is an error. Numbers written as words are not scanned.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from src.tools.common import Value

SLACK = 1e-9
ToleranceClass = Literal["load", "slope", "ratio", "count"]

_MONTH = (
    "(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|"
    "Nov(?:ember)?|Dec(?:ember)?)"
)
_DAY = r"(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
_SKIPPED = [
    re.compile(r"(?<![\w.,])\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?!\w|[.,-]\d)"),
    re.compile(rf"(?<![\w.,-]){_DAY} {_MONTH}\b\.?(?:,? \d{{4}}(?![\w%]|[.,]\d))?"),
    re.compile(rf"\b{_MONTH}\.? {_DAY}(?![\w%]|[.,]\d)(?:,? \d{{4}}(?![\w%]|[.,]\d))?"),
    re.compile(r"(?<![\w.,])\d*(?:1st|2nd|3rd|\dth)\b"),
    re.compile(r"\be?1RM\b", re.IGNORECASE),
]
_SETS_BY_REPS = re.compile(r"(?<=\d)\s*[x×]\s*(?=\d)")
_RANGE = re.compile(r"(?<=\d)\s*[-–]\s*(?=\d)")
_QUANTITY = re.compile(
    r"(?<![\w.,])(?P<sign>[+\-−])?(?P<number>\d+(?:[.,]\d+)?)(?![.,]?\d)"
    r"(?:\s*(?P<unit>kg|kilos?|kilograms?|lbs?|pounds?|%)(?!\w)|(?!\w))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Quantity:
    """One number found in text, with its possible readings."""

    raw: str
    readings: tuple[float, ...]
    signed: bool
    unit: Literal["kg", "lb"] | None


def find_quantities(text: str, own_ids: Iterable[str] = ()) -> tuple[list[Quantity], list[str]]:
    """Return the quantities in ``text`` and the digits that fit no rule."""
    rest = text
    for own in sorted(own_ids, key=len, reverse=True):
        rest = re.sub(rf"(?<!\w){re.escape(own)}(?!\w)", " ", rest)
    for pattern in _SKIPPED:
        rest = pattern.sub(" ", rest)
    rest = _RANGE.sub(" to ", _SETS_BY_REPS.sub(" by ", rest))

    found: list[Quantity] = []
    for m in _QUANTITY.finditer(rest):
        sign = -1.0 if m["sign"] in ("-", "−") else 1.0
        number = m["number"]
        readings = [float(number.replace(",", "."))]
        if re.fullmatch(r"\d{1,3},\d{3}", number):
            readings.append(float(number.replace(",", "")))
        unit = (m["unit"] or "").lower()
        kind: Literal["kg", "lb"] | None = "kg" if unit.startswith("k") else "lb" if unit.startswith(("lb", "po")) else None
        found.append(Quantity(m[0].strip(), tuple(sign * r for r in readings), m["sign"] is not None, kind))
    leftover = _QUANTITY.sub(" ", rest)
    stray = [word for word in leftover.split() if any(ch.isnumeric() for ch in word)]
    return found, stray


def tolerance_class(value: Value, cfg: Mapping[str, Any]) -> ToleranceClass:
    """Tolerance class of a value by name and unit (spec §7)."""
    if value.name in cfg["ratio_names"]:
        return "ratio"
    if value.name.endswith(cfg["slope_suffix"]):
        return "slope"
    if value.unit in cfg["load_units"] or value.name in cfg["load_names"]:
        return "load"
    return "count"


def tolerance(value: Value, cfg: Mapping[str, Any]) -> float:
    """Absolute tolerance for quoting ``value``."""
    kind = tolerance_class(value, cfg)
    if kind == "load":
        return max(float(cfg["load_abs"]), float(cfg["load_rel"]) * abs(float(value.value)))
    return {"slope": float(cfg["slope_abs"]), "ratio": float(cfg["ratio_abs"]), "count": 0.0}[kind]


def matches(quantity: Quantity, value: Value, cfg: Mapping[str, Any]) -> bool:
    """Whether the quantity may be a quotation of ``value``."""
    if isinstance(value.value, str) or quantity.unit == "lb":
        return False
    if quantity.unit == "kg" and not (value.unit or "").startswith("kg"):
        return False
    target = float(value.value)
    allowed = tolerance(value, cfg) + SLACK
    for reading in quantity.readings:
        if abs(reading - target) <= allowed:
            return True
        if not quantity.signed and abs(reading - abs(target)) <= allowed:
            return True
    return False
