"""Shared helpers for the harness tests: made-up gold (tests/data/toy_gold.jsonl) and predictions for it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TOY_GOLD = Path(__file__).resolve().parents[1] / "data" / "toy_gold.jsonl"


def label(**kw: Any) -> dict[str, Any]:
    """A valid label object with overrides."""
    base: dict[str, Any] = {
        "exercise_id": "squat",
        "kinematic_observation": "none",
        "load": {"value": 100, "unit": "kg"},
        "reps": 5,
        "outcome": "completed",
        "rpe": 8,
        "triage_level": "green",
    }
    base.update(kw)
    return base


def write_jsonl(path: Path, rows: list[Any]) -> Path:
    """Write rows (dicts, or raw strings for deliberately broken lines) as JSONL."""
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def pred_row(item_id: str, pred: Any, error: str | None = None) -> dict[str, Any]:
    """A prediction row in the F5 format, with a raw text that must never reach the outputs."""
    return {"item_id": item_id, "pred": pred, "raw": f"RAWTEXT for {item_id}", "error": error}


def toy_preds() -> list[dict[str, Any]]:
    """Predictions for the six toy gold items (see test_eval_metrics.py for the hand computation)."""
    gold = [json.loads(line) for line in TOY_GOLD.read_text(encoding="utf-8").splitlines()]
    labels = {g["item_id"]: g["labels"] for g in gold}
    p2 = dict(labels["g2"], kinematic_observation="slow_bar_speed", load={"value": 80, "unit": "lb"}, rpe=7)
    p4 = dict(labels["g4"], load={"value": 60.0, "unit": "lb"}, kinematic_observation="none", reps=None)
    p5 = dict(labels["g5"], load={"value": 20, "unit": "kg"}, reps=None, triage_level="yellow")
    p6 = dict(labels["g6"], rpe=11)
    return [
        pred_row("g1", labels["g1"]),
        pred_row("g2", p2),
        pred_row("g3", None, "no_json"),
        pred_row("g4", p4),
        pred_row("g5", p5),
        pred_row("g6", p6),
    ]
