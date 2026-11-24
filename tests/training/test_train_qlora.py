"""Pure-Python parts of the QLoRA script (issue F6). No ML imports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.training.train_qlora import read_train, to_examples

ROW = {
    "text": "squat 100kg x5",
    "pool": "train",
    "labels": {
        "exercise_id": "Barbell_Squat",
        "kinematic_observation": "none",
        "load": {"value": 100.0, "unit": "kg"},
        "reps": 5,
        "outcome": "completed",
        "rpe": None,
        "triage_level": "green",
    },
}


def test_examples_are_prompt_completion_with_strict_json() -> None:
    ex = to_examples([ROW], chat=lambda p: f"<user>{p}</user><assistant>", eos="<eos>")[0]
    assert ex["prompt"].startswith("<user>") and "squat 100kg x5" in ex["prompt"]
    assert ex["completion"].endswith("<eos>")
    assert json.loads(ex["completion"].removesuffix("<eos>")) == ROW["labels"]


def test_read_train_first_cut_and_guards(tmp_path: Path) -> None:
    f = tmp_path / "train.jsonl"
    f.write_text("\n".join(json.dumps({**ROW, "i": i}) for i in range(10)) + "\n", encoding="utf-8")
    assert [r["i"] for r in read_train(f, 3)] == [0, 1, 2]
    dev = tmp_path / "dev.jsonl"
    dev.write_text(json.dumps({**ROW, "pool": "dev"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_train(dev, None)
    golden = tmp_path / "golden" / "g.jsonl"
    golden.parent.mkdir()
    golden.write_text(json.dumps(ROW) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_train(golden, None)
