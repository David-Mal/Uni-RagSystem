"""Field-level, triage and slice metrics for the extraction task (issue P2, plan §7).

Counting rules per field (D3): same value TP; other value FP + FN; gold value but pred null or failure FN;
gold null but pred value FP; gold null and pred null or failure nothing. Precision, recall and F1 are ``None``
when undefined; F1 is 0 when there are FP or FN but no TP.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from src.eval.stats import mcnemar_exact, wilson
from src.schemas import UNKNOWN_EXERCISE_ID, ExtractionResult, KinematicObservation, Outcome

FIELDS: tuple[str, ...] = tuple(ExtractionResult.model_fields)
DEFAULT_VALUES: dict[str, Any] = {
    "exercise_id": UNKNOWN_EXERCISE_ID,
    "kinematic_observation": KinematicObservation.NONE.value,
    "outcome": Outcome.COMPLETED.value,
}
"""Default values of D4: treated as null in the "default values as null" view."""
LEVELS = ("green", "yellow", "red")
FAILED = "failed"
MIN_SLICE_N = 10
VECTOR_LEN = 3 * len(FIELDS) + 2
"""Per-item count vector: (tp, fp, fn) for each field, then red gold items and red hits."""

Counts = list[tuple[int, int, int]]


class EvalError(ValueError):
    """Invalid input. Messages name files, lines, item ids and fields, never input values."""


@dataclass(frozen=True)
class Item:
    """One scored item. ``pred`` is ``None`` for a failure; ``meta`` is the gold row (slice and cluster fields)."""

    item_id: str
    gold: dict[str, Any]
    pred: dict[str, Any] | None
    valid_json: bool
    meta: Mapping[str, Any]


def label_values(result: ExtractionResult) -> dict[str, Any]:
    """Comparable values of a validated label: plain scalars, and ``(value, unit)`` for load."""
    raw = result.model_dump(mode="json")
    load = raw["load"]
    raw["load"] = None if load is None else (load["value"], load["unit"])
    return raw


def prf(tp: int, fp: int, fn: int) -> dict[str, float | int | None]:
    """Precision, recall and F1 from counts; undefined values are ``None``."""
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None,
    }


def field_counts(gold: Any, pred: Any) -> tuple[int, int, int]:
    """(tp, fp, fn) of one field; ``pred`` is ``None`` for null or failure."""
    if gold is None:
        return (0, 1, 0) if pred is not None else (0, 0, 0)
    if pred is None:
        return (0, 0, 1)
    return (1, 0, 0) if gold == pred else (0, 1, 1)


def _view(values: Mapping[str, Any] | None, default_null: bool) -> dict[str, Any]:
    out = {f: None if values is None else values[f] for f in FIELDS}
    if default_null:
        out = {f: None if f in DEFAULT_VALUES and v == DEFAULT_VALUES[f] else v for f, v in out.items()}
    return out


def item_counts(item: Item, default_null: bool = False) -> Counts:
    """Per-field (tp, fp, fn) of one item; with ``default_null`` default values count as null on both sides."""
    gold, pred = _view(item.gold, default_null), _view(item.pred, default_null)
    return [field_counts(gold[f], pred[f]) for f in FIELDS]


def _red_counts(item: Item) -> tuple[int, int]:
    is_red = item.gold["triage_level"] == "red"
    return int(is_red), int(is_red and item.pred is not None and item.pred["triage_level"] == "red")


def item_vector(item: Item) -> list[float]:
    """Additive count vector of one item, the unit of the bootstrap."""
    vec: list[float] = [x for c in item_counts(item) for x in c]
    vec.extend(_red_counts(item))
    return vec


def counts_from_sums(sums: Sequence[float]) -> Counts:
    """Per-field counts from a summed count vector."""
    return [(int(sums[3 * i]), int(sums[3 * i + 1]), int(sums[3 * i + 2])) for i in range(len(FIELDS))]


def sum_counts(items: Sequence[Item], default_null: bool = False) -> Counts:
    """Pooled per-field counts over items."""
    total = [(0, 0, 0)] * len(FIELDS)
    for item in items:
        total = [(a[0] + b[0], a[1] + b[1], a[2] + b[2]) for a, b in zip(total, item_counts(item, default_null))]
    return total


def headline(counts: Counts) -> dict[str, Any]:
    """Per-field metrics, micro (pooled) and macro (mean of defined field F1) from per-field counts."""
    fields = {f: prf(*c) for f, c in zip(FIELDS, counts, strict=True)}
    micro = prf(sum(c[0] for c in counts), sum(c[1] for c in counts), sum(c[2] for c in counts))
    f1s = [m["f1"] for m in fields.values() if m["f1"] is not None]
    macro = sum(f1s) / len(f1s) if f1s else None
    return {"micro": micro, "macro_f1": macro, "n_fields_in_macro": len(f1s), "fields": fields}


def stats_from_sums(sums: Sequence[float]) -> dict[str, float | None]:
    """Bootstrap statistics of a summed vector: micro and macro F1, red recall, per-field F1."""
    block = headline(counts_from_sums(sums))
    red_n, red_hit = sums[-2], sums[-1]
    out: dict[str, float | None] = {
        "micro_f1": block["micro"]["f1"],
        "macro_f1": block["macro_f1"],
        "red_recall": red_hit / red_n if red_n else None,
    }
    out.update({f"field_f1.{f}": m["f1"] for f, m in block["fields"].items()})
    return out


def paired_stats(sums: Sequence[float]) -> dict[str, float | None]:
    """Difference B - A of micro F1, macro F1 and red recall, from the concatenated vectors of A and B."""
    half = len(sums) // 2
    a, b = stats_from_sums(sums[:half]), stats_from_sums(sums[half:])
    out: dict[str, float | None] = {}
    for key in ("micro_f1", "macro_f1", "red_recall"):
        va, vb = a[key], b[key]
        out[key] = None if va is None or vb is None else vb - va
    return out


def triage_block(items: Sequence[Item]) -> dict[str, Any]:
    """Confusion matrix (gold rows, predicted columns incl. ``failed``), red recall with Wilson CI, green FPR."""
    conf = {g: {p: 0 for p in (*LEVELS, FAILED)} for g in LEVELS}
    for item in items:
        conf[item.gold["triage_level"]][FAILED if item.pred is None else item.pred["triage_level"]] += 1
    red_n = sum(conf["red"].values())
    red_hit = conf["red"]["red"]
    green_n = sum(conf["green"].values())
    fp = conf["green"]["yellow"] + conf["green"]["red"]
    ci = wilson(red_hit, red_n)
    return {
        "confusion": conf,
        "red_n": red_n,
        "red_hits": red_hit,
        "red_recall": red_hit / red_n if red_n else None,
        "red_recall_wilson_lo": ci[0] if ci else None,
        "red_recall_wilson_hi": ci[1] if ci else None,
        "green_n": green_n,
        "green_fpr": fp / green_n if green_n else None,
        "green_fpr_failsafe": (fp + conf["green"][FAILED]) / green_n if green_n else None,
    }


def compute_metrics(items: Sequence[Item]) -> dict[str, Any]:
    """All metrics of one set of items (the whole file, a slice, or one model of a comparison)."""
    n = len(items)
    failures = sum(1 for i in items if i.pred is None)
    valid = sum(1 for i in items if i.valid_json)
    return {
        "n_items": n,
        "headline": headline(sum_counts(items)),
        "default_as_null": headline(sum_counts(items, default_null=True)),
        "secondary": {
            "n_failures": failures,
            "failure_rate": failures / n if n else None,
            "n_valid_json": valid,
            "json_validity_rate": valid / n if n else None,
        },
        "triage": triage_block(items),
    }


def majority_baseline(items: Sequence[Item]) -> dict[str, Any]:
    """Headline metrics of predicting, for every item, the most frequent gold value of each field (null included).

    Ties go to the value with the smallest ``repr``. Scored by the same counting code as real predictions.
    """
    modal: dict[str, Any] = {}
    for f in FIELDS:
        counter = Counter(i.gold[f] for i in items)
        modal[f] = min(counter, key=lambda v: (-counter[v], repr(v)))
    return headline(sum_counts([replace(i, pred=modal) for i in items]))


def undefined_warnings(block: Mapping[str, Any], label: str = "") -> list[str]:
    """Warnings for fields whose F1 is undefined (no TP, FP or FN) and so is left out of macro F1."""
    return [
        f"{label}field {f!r} has no TP, FP or FN: F1 is null and left out of macro F1"
        for f, m in block["fields"].items()
        if m["f1"] is None
    ]


def _require_field(items: Sequence[Item], field: str) -> None:
    if not any(field in i.meta for i in items):
        raise EvalError(f"field {field!r} is absent from every gold item")


def group_key(item: Item, field: str, allow_missing: bool) -> str:
    """Group label of an item for a top-level gold field: strings as is, other scalars as JSON, null as ``null``."""
    value = item.meta.get(field)
    if isinstance(value, (list, dict)):
        raise EvalError(f"item {item.item_id!r}: field {field!r} is not a scalar")
    if value is None and not allow_missing:
        raise EvalError(f"item {item.item_id!r}: field {field!r} is missing or null")
    return value if isinstance(value, str) else json.dumps(value)


def cluster_keys(items: Sequence[Item], field: str) -> list[str]:
    """Cluster label of every item; missing or null cluster values are an error."""
    _require_field(items, field)
    return [group_key(i, field, allow_missing=False) for i in items]


def slice_metrics(items: Sequence[Item], field: str) -> dict[str, Any]:
    """Metrics per value of a gold field (null or missing is its own group); groups under 10 items report only n."""
    _require_field(items, field)
    groups: dict[str, list[Item]] = {}
    for item in items:
        groups.setdefault(group_key(item, field, allow_missing=True), []).append(item)
    return {k: compute_metrics(g) if len(g) >= MIN_SLICE_N else {"n_items": len(g)} for k, g in groups.items()}


def item_correct(item: Item) -> dict[str, bool]:
    """Per-field exact equality with gold (null equals null); a failure is incorrect everywhere."""
    return {f: item.pred is not None and item.pred[f] == item.gold[f] for f in FIELDS}


def mcnemar_tests(items_a: Sequence[Item], items_b: Sequence[Item]) -> dict[str, dict[str, float | int]]:
    """Exact McNemar per field, for the fully correct item, and for red (predicted red on gold red items)."""
    cols: dict[str, list[tuple[bool, bool]]] = {f"field.{f}": [] for f in FIELDS}
    cols["fully_correct_item"], cols["red"] = [], []
    for a, b in zip(items_a, items_b, strict=True):
        ca, cb = item_correct(a), item_correct(b)
        for f in FIELDS:
            cols[f"field.{f}"].append((ca[f], cb[f]))
        cols["fully_correct_item"].append((all(ca.values()), all(cb.values())))
        if a.gold["triage_level"] == "red":
            cols["red"].append((_red_counts(a)[1] == 1, _red_counts(b)[1] == 1))
    out: dict[str, dict[str, float | int]] = {}
    for name, pairs in cols.items():
        a_only = sum(1 for x, y in pairs if x and not y)
        b_only = sum(1 for x, y in pairs if y and not x)
        out[name] = {
            "n": len(pairs),
            "a_only_correct": a_only,
            "b_only_correct": b_only,
            "p_value": mcnemar_exact(a_only, b_only),
        }
    return out
