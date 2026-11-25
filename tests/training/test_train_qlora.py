"""Pure-Python parts of the QLoRA script (issue F6). No ML imports."""

from __future__ import annotations

import json
from collections import Counter
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


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _row(i: int, level: str) -> dict:
    return {**ROW, "item_id": f"tm-{i}", "labels": {**ROW["labels"], "triage_level": level}}


def test_subset_is_balanced_seeded_and_shuffled(tmp_path: Path) -> None:
    levels = ["green"] * 20 + ["yellow"] * 20 + ["red"] * 20  # sorted by class, like the real file
    f = _write(tmp_path / "train.jsonl", [_row(i, lvl) for i, lvl in enumerate(levels)])
    rows = read_train(f, 10, seed=13)
    got = [r["labels"]["triage_level"] for r in rows]
    assert Counter(got) == {"green": 4, "red": 3, "yellow": 3}  # 10 = 4 + 3 + 3, classes in alphabetical order
    assert got != sorted(got)
    assert rows == read_train(f, 10, seed=13) != read_train(f, 10, seed=14)
    assert len(read_train(f, None)) == 60


def test_first_cut_of_the_real_file_has_every_class() -> None:
    f = Path(__file__).resolve().parents[2] / "data" / "training" / "train.jsonl"
    rows = read_train(f, 500, seed=13, allow_unaudited=True)
    assert len(rows) == 500 and set(Counter(r["labels"]["triage_level"] for r in rows).values()) == {166, 167}


def test_unaudited_data_is_refused(tmp_path: Path) -> None:
    f = _write(tmp_path / "t.jsonl", [{**_row(1, "red"), "data_version": "train_v1_unaudited"}])
    with pytest.raises(ValueError, match="leakage audit"):
        read_train(f, None)
    assert len(read_train(f, None, allow_unaudited=True)) == 1
    ok = _write(tmp_path / "ok.jsonl", [{**_row(1, "red"), "data_version": "train_v1"}])
    assert len(read_train(ok, None)) == 1


def test_golden_and_dev_items_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="train pool"):
        read_train(_write(tmp_path / "dev.jsonl", [{**ROW, "pool": "dev"}]), None)
    (tmp_path / "golden").mkdir()
    with pytest.raises(ValueError, match="golden"):
        read_train(_write(tmp_path / "golden" / "g.jsonl", [ROW]), None)
