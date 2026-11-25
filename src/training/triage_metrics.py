"""Triage metrics, in priority order: red recall, then green false-positive rate (plan §6.4, §7). No ML imports."""

from __future__ import annotations

import math
from collections.abc import Sequence

LABELS: tuple[str, ...] = ("green", "yellow", "red")


def confusion(y_true: Sequence[str], y_pred: Sequence[str]) -> dict[str, dict[str, int]]:
    """Confusion matrix as ``{true: {pred: count}}`` over green/yellow/red."""
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred differ in length")
    matrix = {t: dict.fromkeys(LABELS, 0) for t in LABELS}
    for t, p in zip(y_true, y_pred, strict=True):
        matrix[t][p] += 1
    return matrix


def wilson_interval(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a proportion (95% by default). Returns (0, 1) when n == 0."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def triage_metrics(y_true: Sequence[str], y_pred: Sequence[str]) -> dict[str, object]:
    """Red recall (+ Wilson 95% CI), green FPR, per-class F1, macro F1, accuracy and the confusion matrix.

    Green FPR = share of truly green items predicted yellow or red (needless alarms).
    """
    m = confusion(y_true, y_pred)
    n_red = sum(m["red"].values())
    n_green = sum(m["green"].values())
    f1 = {}
    for c in LABELS:
        tp = m[c][c]
        fp = sum(m[t][c] for t in LABELS if t != c)
        fn = sum(m[c][p] for p in LABELS if p != c)
        f1[c] = 0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn)
    lo, hi = wilson_interval(m["red"]["red"], n_red)
    return {
        "red_recall": m["red"]["red"] / n_red if n_red else None,
        "red_recall_wilson95": [lo, hi],
        "green_fpr": (n_green - m["green"]["green"]) / n_green if n_green else None,
        "f1": f1,
        "macro_f1": sum(f1.values()) / len(LABELS),
        "accuracy": sum(m[c][c] for c in LABELS) / max(1, len(y_true)),
        "n": len(y_true),
        "confusion": m,
    }
