"""Triage-classifier data: ``triage_train.jsonl`` and ``triage_dev.jsonl`` (issue F8, plan §6.4).

Items are text + label only, plus the manifest fields. They come from the classifier's own phrasing families
(``consumer="classifier"`` in ``families.py`` and in the P1 manifest), which are disjoint from the extractor's
families. Seeds come from the train/dev pools at an offset, so they never coincide with the extractor's seeds in F4.

Usage::

    python -m src.datagen.triage --manifest data/manifests/partition.yaml --n-train 1500 --n-dev 300
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.datagen.build_training import DEFAULT_RATIOS, build_split, class_targets, read_drop_ids
from src.datagen.messages import write_jsonl
from src.datagen.registry import PoolRegistry
from src.schemas import TriageLevel

LABEL2ID: dict[str, int] = {"green": 0, "yellow": 1, "red": 2}
ID2LABEL: dict[int, str] = {v: k for k, v in LABEL2ID.items()}
TRAIN_SEED_OFFSET = 5000
"""Triage train seeds start at ``train_range_start + 5000`` (extractor train data uses the start of the range)."""
DEV_SEED_OFFSET = 500
"""Triage dev seeds start at ``dev_range_start + 500`` (extractor dev + red_dev use the first ~400 dev seeds)."""


def to_triage_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce a generated item to the classifier format: text + label + manifest fields."""
    label = item["labels"]["triage_level"]
    return {
        "item_id": "tc-" + item["item_id"].removeprefix("tm-"),
        "text": item["text"],
        "label": label,
        "label_id": LABEL2ID[label],
        "task": "triage",
        **{
            k: item[k]
            for k in (
                "pool",
                "persona_id",
                "phrasing_family",
                "hard_negative",
                "seed",
                "generator",
                "generator_model",
                "generator_version",
                "paraphraser",
                "schema_version",
            )
        },
    }


def build_triage(
    registry: PoolRegistry,
    n_train: int,
    n_dev: int,
    ratios: Mapping[TriageLevel, float] = DEFAULT_RATIOS,
    drop_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, tuple[int, int]]]:
    """Return ``(train_items, dev_items, seed_ranges_used)``; texts are unique across both splits."""
    drop_ids = drop_ids or set()
    seen: set[str] = set()
    train_start = registry.seed_range("train")[0] + TRAIN_SEED_OFFSET
    dev_start = registry.seed_range("dev")[0] + DEV_SEED_OFFSET
    train, _ = build_split(
        "triage_train",
        "train",
        class_targets(n_train, ratios),
        train_start,
        registry,
        seen,
        set(),
        consumer="classifier",
    )
    dev, _ = build_split(
        "triage_dev", "dev", class_targets(n_dev, ratios), dev_start, registry, seen, set(), consumer="classifier"
    )
    out_train = [t for t in map(to_triage_item, train.items) if t["item_id"] not in drop_ids]
    out_dev = [t for t in map(to_triage_item, dev.items) if t["item_id"] not in drop_ids]
    return out_train, out_dev, {"triage_train": train.seeds, "triage_dev": dev.seeds}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Build triage-classifier train/dev data.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--n-train", type=int, default=1500)
    parser.add_argument("--n-dev", type=int, default=300)
    parser.add_argument("--drop-ids", type=Path, default=Path("data/manifests/drop_ids.txt"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/training"))
    args = parser.parse_args(argv)

    registry = PoolRegistry.load(args.manifest)
    train, dev, seeds = build_triage(registry, args.n_train, args.n_dev, drop_ids=read_drop_ids(args.drop_ids))
    for name, items in (("triage_train", train), ("triage_dev", dev)):
        path = args.out_dir / f"{name}.jsonl"
        write_jsonl(items, path)
        print(f"{name}: {len(items)} items, seeds {seeds[name][0]}-{seeds[name][1]} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
