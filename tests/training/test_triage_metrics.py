"""Tests for triage metrics and data loading of the classifier skeleton (issue F8). No ML imports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.training.train_classifier import ID2LABEL, LABEL2ID, load_jsonl
from src.training.triage_metrics import triage_metrics, wilson_interval


def test_label_mapping() -> None:
    assert LABEL2ID == {"green": 0, "yellow": 1, "red": 2}
    assert ID2LABEL == {0: "green", 1: "yellow", 2: "red"}


def test_hand_computed_metrics() -> None:
    # 4 red: 3 predicted red, 1 yellow -> red recall 3/4 = 0.75
    # 4 green: 3 green, 1 yellow       -> green FPR 1/4 = 0.25
    # 2 yellow: both yellow
    y_true = ["red"] * 4 + ["green"] * 4 + ["yellow"] * 2
    y_pred = ["red", "red", "red", "yellow", "green", "green", "green", "yellow", "yellow", "yellow"]
    m = triage_metrics(y_true, y_pred)
    assert m["red_recall"] == 0.75
    assert m["green_fpr"] == 0.25
    # yellow: tp=2, fp=2 (1 red, 1 green), fn=0 -> F1 = 4 / (4 + 2) = 0.6667
    assert m["f1"]["yellow"] == pytest.approx(2 / 3)
    # red: tp=3, fp=0, fn=1 -> 6/7; green: tp=3, fp=0, fn=1 -> 6/7
    assert m["macro_f1"] == pytest.approx((6 / 7 + 6 / 7 + 2 / 3) / 3)
    assert m["accuracy"] == 0.8
    assert m["confusion"]["red"]["yellow"] == 1


def test_wilson_interval_80_of_80() -> None:
    lo, hi = wilson_interval(80, 80)
    # n=80, z^2=3.8415: centre = (1 + 0.02401) / 1.04802 = 0.97709, half = 0.02401 / 1.04802 = 0.02291 -> lo = 0.9542
    assert lo == pytest.approx(0.954, abs=1e-3)
    assert hi == pytest.approx(1.0)


def test_load_jsonl_stratified_limit_and_golden_guard(tmp_path: Path) -> None:
    f = tmp_path / "triage.jsonl"
    rows = [{"text": f"t{i}", "label": lab} for i, lab in enumerate(["green", "yellow", "red"] * 30)]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    picked = load_jsonl(f, limit=50, seed=1)
    assert len(picked) == 50
    assert sorted(sum(p["label"] == lab for p in picked) for lab in ("green", "yellow", "red")) == [16, 17, 17]
    assert picked == load_jsonl(f, limit=50, seed=1)
    golden = tmp_path / "golden" / "x.jsonl"
    golden.parent.mkdir()
    golden.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        load_jsonl(golden)
