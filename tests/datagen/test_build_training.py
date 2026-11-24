"""Tests for the training-data builder (issue F4). Small sizes, stub manifest only."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.datagen.build_training import (
    build_all,
    class_targets,
    iter_jsonl,
    main,
    normalize_text,
    read_drop_ids,
)
from src.datagen.registry import PoolRegistry
from src.schemas import ExtractionResult, TriageLevel

STUB = Path(__file__).resolve().parents[1] / "data" / "datagen" / "partition_stub.yaml"


@pytest.fixture(scope="module")
def registry() -> PoolRegistry:
    return PoolRegistry.load(STUB)


def test_class_targets_sum_and_ratio() -> None:
    # 3000 * 0.35 = 1050, 3000 * 0.30 = 900, 3000 * 0.35 = 1050
    assert class_targets(3000, {TriageLevel.GREEN: 0.35, TriageLevel.YELLOW: 0.30, TriageLevel.RED: 0.35}) == {
        TriageLevel.GREEN: 1050,
        TriageLevel.YELLOW: 900,
        TriageLevel.RED: 1050,
    }
    # 301: floors 105 + 90 + 105 = 300, remainder 1 goes to green
    t = class_targets(301, {TriageLevel.GREEN: 0.35, TriageLevel.YELLOW: 0.30, TriageLevel.RED: 0.35})
    assert sum(t.values()) == 301 and t[TriageLevel.GREEN] == 106


def test_normalize_text_merges_trivial_variants_but_keeps_decimals() -> None:
    assert normalize_text("Bench 100kg x5, felt GOOD! 💪") == normalize_text("bench   100kg x5 felt good")
    assert "12.5" in normalize_text("Curls 12.5 kg.")
    assert normalize_text("12.5 kg") != normalize_text("125 kg")


def test_build_counts_pools_and_no_cross_split_duplicates(registry: PoolRegistry) -> None:
    train, dev, red_dev = build_all(registry, n_train=120, n_dev=40, n_red_dev=15)
    assert len(train.items) == 120 and len(dev.items) == 40 and len(red_dev.items) == 15
    assert {it["pool"] for it in train.items} == {"train"}
    assert {it["pool"] for it in dev.items + red_dev.items} == {"dev"}
    assert {it["labels"]["triage_level"] for it in red_dev.items} == {"red"}
    texts = [normalize_text(it["text"]) for s in (train, dev, red_dev) for it in s.items]
    assert len(texts) == len(set(texts))
    ids = [it["item_id"] for s in (train, dev, red_dev) for it in s.items]
    assert len(ids) == len(set(ids))
    assert dev.seeds[1] < red_dev.seeds[0]  # red_dev seeds follow dev seeds, no reuse
    for s in (train, dev, red_dev):
        for it in s.items:
            ExtractionResult.model_validate(it["labels"])


def test_build_is_deterministic(registry: PoolRegistry) -> None:
    a = build_all(registry, n_train=60, n_dev=20, n_red_dev=5)
    b = build_all(registry, n_train=60, n_dev=20, n_red_dev=5)
    assert [s.items for s in a] == [s.items for s in b]


def test_audit_drop_ids_are_removed_and_replaced(registry: PoolRegistry) -> None:
    baseline = build_all(registry, n_train=30, n_dev=9, n_red_dev=3)[0]
    victim = baseline.items[0]["item_id"]
    train = build_all(registry, n_train=30, n_dev=9, n_red_dev=3, drop_ids={victim})[0]
    assert victim not in {it["item_id"] for it in train.items}
    assert len(train.items) == 30  # replaced by the next seed
    assert train.dropped_by_audit == [victim]


def test_read_drop_ids(tmp_path: Path) -> None:
    f = tmp_path / "drop_ids.txt"
    f.write_text("# audit 2026-11-27\ntm-train-000001\n\ntm-train-000002  # near-duplicate\n", encoding="utf-8")
    assert read_drop_ids(f) == {"tm-train-000001", "tm-train-000002"}
    assert read_drop_ids(tmp_path / "missing.txt") == set()


def test_cli_writes_files_and_report(tmp_path: Path) -> None:
    out, report = tmp_path / "training", tmp_path / "report.md"
    args = ["--manifest", str(STUB), "--n-train", "30", "--n-dev", "9", "--n-red-dev", "3"]
    assert main([*args, "--out-dir", str(out), "--report", str(report), "--drop-ids", str(tmp_path / "none")]) == 0
    train = list(iter_jsonl(out / "train.jsonl"))
    assert len(train) == 30 and all(it["data_version"] == "train_v1" for it in train)
    text = report.read_text(encoding="utf-8")
    for heading in ("## train", "## dev", "## red_dev", "triage class", "phrasing family", "exercise family"):
        assert heading in text
