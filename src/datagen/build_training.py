"""Build training data v1: train / dev / red_dev splits, dedup, validation, audit drops, stats report (issue F4).

Splits:
- ``train.jsonl``: train pool seeds; class mix from ``--train-ratios`` (default 35/30/35 green/yellow/red).
- ``dev.jsonl``: dev pool seeds, same class mix; used for model selection and baselines (F5).
- ``red_dev.jsonl``: dev pool seeds after the dev split, red only; used to tune gate rules.

Every item is validated against ``ExtractionResult`` and the manifest. Texts are deduplicated after normalization
within each split and across splits (dev items never repeat a train text). Ids listed in the leakage-audit file
(P4, ``data/manifests/drop_ids.txt``) are removed and reported. The output is deterministic for a given manifest
and arguments.

Usage::

    python -m src.datagen.build_training --manifest data/manifests/partition.yaml --version train_v1
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.datagen import vocab
from src.datagen.messages import GENERATOR, generate_item, write_jsonl
from src.datagen.registry import PoolError, PoolRegistry
from src.schemas import ExtractionResult, TriageLevel

DEFAULT_RATIOS: dict[TriageLevel, float] = {TriageLevel.GREEN: 0.35, TriageLevel.YELLOW: 0.30, TriageLevel.RED: 0.35}
EXERCISE_FAMILY: dict[str, str] = {e.exercise_id: e.family for e in vocab.EXERCISES}
MAX_ATTEMPTS_FACTOR = 20
"""Give up if a split needs more than ``factor * target`` seeds (dedup can't reach the target)."""


def normalize_text(text: str) -> str:
    """Normalization used for dedup: NFKC, lowercase, punctuation and emoji removed, whitespace collapsed."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s.]", " ", text)  # keep word chars and decimal points
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)  # drop sentence dots, keep 12.5
    return re.sub(r"\s+", " ", text).strip()


def class_targets(total: int, ratios: Mapping[TriageLevel, float]) -> dict[TriageLevel, int]:
    """Split ``total`` by ``ratios``; rounding remainder goes to the classes in triage order."""
    raw = {lvl: int(total * ratios[lvl]) for lvl in vocab.TRIAGE_ORDER}
    for lvl in vocab.TRIAGE_ORDER[: total - sum(raw.values())]:
        raw[lvl] += 1
    return raw


@dataclass
class SplitResult:
    """Items of one split plus what was skipped while building it."""

    name: str
    items: list[dict[str, Any]] = field(default_factory=list)
    seeds: tuple[int, int] | None = None
    duplicates_within: int = 0
    duplicates_cross: int = 0
    dropped_by_audit: list[str] = field(default_factory=list)


def build_split(
    name: str,
    pool: str,
    targets: Mapping[TriageLevel, int],
    first_seed: int,
    registry: PoolRegistry,
    seen_texts: set[str],
    drop_ids: set[str],
    consumer: str = "extractor",
) -> tuple[SplitResult, int]:
    """Generate one split until every class reaches its target. Returns the split and the next free seed.

    Seeds are consumed in order, one per attempt and class, so the result depends only on the inputs.
    """
    result = SplitResult(name=name)
    lo, hi = registry.seed_range(pool)
    seed = first_seed
    own_texts: set[str] = set()
    for level in vocab.TRIAGE_ORDER:
        need, attempts = targets.get(level, 0), 0
        while need > 0:
            attempts += 1
            if attempts > MAX_ATTEMPTS_FACTOR * max(targets.get(level, 0), 1):
                raise RuntimeError(f"{name}/{level}: cannot reach target after {attempts} attempts (dedup)")
            if not lo <= seed <= hi:
                raise PoolError(f"{name}: ran out of {pool} seeds at {seed}")
            item = generate_item(level, seed, pool, registry, consumer=consumer)
            seed += 1
            if item["item_id"] in drop_ids:
                result.dropped_by_audit.append(item["item_id"])
                continue
            key = normalize_text(item["text"])
            if key in own_texts:
                result.duplicates_within += 1
                continue
            if key in seen_texts:
                result.duplicates_cross += 1
                continue
            ExtractionResult.model_validate(item["labels"])
            registry.assert_in_pool(
                pool, seed=item["seed"], personas=item["persona_id"], phrasing_families=item["phrasing_family"]
            )
            own_texts.add(key)
            result.items.append(item)
            need -= 1
    seen_texts |= own_texts
    result.seeds = (first_seed, seed - 1)
    return result, seed


def build_all(
    registry: PoolRegistry,
    n_train: int,
    n_dev: int,
    n_red_dev: int,
    ratios: Mapping[TriageLevel, float] = DEFAULT_RATIOS,
    drop_ids: set[str] | None = None,
) -> list[SplitResult]:
    """Build train, dev and red_dev in that order (train texts are reserved first)."""
    drop_ids = drop_ids or set()
    seen: set[str] = set()
    train, _ = build_split(
        "train", "train", class_targets(n_train, ratios), registry.seed_range("train")[0], registry, seen, drop_ids
    )
    dev, next_dev_seed = build_split(
        "dev", "dev", class_targets(n_dev, ratios), registry.seed_range("dev")[0], registry, seen, drop_ids
    )
    red_dev, _ = build_split("red_dev", "dev", {TriageLevel.RED: n_red_dev}, next_dev_seed, registry, seen, drop_ids)
    return [train, dev, red_dev]


# ------------------------------------------------------------------ report


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _table(counter: Mapping[str, int], total: int, header: str) -> list[str]:
    lines = [f"| {header} | n | % |", "|---|---:|---:|"]
    for key, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {key} | {n} | {100 * n / total:.1f} |")
    return lines


def stats(items: list[dict[str, Any]]) -> dict[str, collections.Counter[str]]:
    """Counters used by the report: class, phrasing family, exercise family, generator and a few others."""
    c: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for it in items:
        lab = it["labels"]
        c["class"][lab["triage_level"]] += 1
        c["phrasing_family"][it["phrasing_family"]] += 1
        c["exercise_family"][EXERCISE_FAMILY.get(lab["exercise_id"], "unknown")] += 1
        c["generator"][it["generator"] + (f" + {it['paraphraser']}" if it["paraphraser"] else "")] += 1
        c["hard_negative"][f"{it['hard_negative'] or 'none'} / {lab['triage_level']}"] += 1
        c["outcome"][lab["outcome"]] += 1
        c["kinematic_observation"][lab["kinematic_observation"]] += 1
        c["load_unit"][lab["load"]["unit"] if lab["load"] else "none"] += 1
        c["rpe"]["present" if lab["rpe"] is not None else "absent"] += 1
    return c


def write_report(splits: list[SplitResult], files: Mapping[str, Path], version: str, manifest: Path, out: Path) -> None:
    """Write the markdown stats report (counts per class, phrasing family, exercise family, generator)."""
    lines = [
        f"# Training data {version}",
        "",
        "Generated by `python -m src.datagen.build_training` (issue F4). Do not edit by hand.",
        "",
        f"- Generator: `{GENERATOR}`",
        f"- Manifest: `{manifest.as_posix()}` (sha256 `{_sha256(manifest)[:16]}`)",
        "- Class ratios (train and dev): green 35% / yellow 30% / red 35% (plan §6.3: a few thousand items)",
        "",
        "## Splits",
        "",
        "| split | file | items | seeds | dup within | dup vs earlier splits | dropped by audit | sha256 |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for s in splits:
        path = files[s.name]
        lines.append(
            f"| {s.name} | `{path.as_posix()}` | {len(s.items)} | {s.seeds[0]}-{s.seeds[1]} | "
            f"{s.duplicates_within} | {s.duplicates_cross} | {len(s.dropped_by_audit)} | `{_sha256(path)[:16]}` |"
        )
    for s in splits:
        c = stats(s.items)
        n = len(s.items)
        lines += ["", f"## {s.name}", ""]
        for key, header in (
            ("class", "triage class"),
            ("phrasing_family", "phrasing family"),
            ("exercise_family", "exercise family"),
            ("generator", "generator"),
            ("hard_negative", "hard negative / class"),
            ("outcome", "outcome"),
            ("kinematic_observation", "kinematic observation"),
            ("load_unit", "load unit"),
            ("rpe", "RPE"),
        ):
            lines += [*_table(c[key], n, header), ""]
        if s.dropped_by_audit:
            lines += ["Dropped by the leakage audit (ids only): " + ", ".join(sorted(s.dropped_by_audit)), ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


def read_drop_ids(path: Path | None) -> set[str]:
    """Read the leakage-audit drop list (one id per line, ``#`` comments allowed); missing file = empty set."""
    if path is None or not path.exists():
        return set()
    return {line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()} - {""}


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Read a JSONL file."""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Build training data (train/dev/red_dev) and its stats report.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--version", default="train_v1")
    parser.add_argument("--n-train", type=int, default=3000)
    parser.add_argument("--n-dev", type=int, default=300)
    parser.add_argument("--n-red-dev", type=int, default=100)
    parser.add_argument("--drop-ids", type=Path, default=Path("data/manifests/drop_ids.txt"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/training"))
    parser.add_argument("--report", type=Path, default=None, help="default: docs/results/training_data_<v>.md")
    args = parser.parse_args(argv)

    registry = PoolRegistry.load(args.manifest)
    drop_ids = read_drop_ids(args.drop_ids)
    splits = build_all(registry, args.n_train, args.n_dev, args.n_red_dev, drop_ids=drop_ids)
    files = {s.name: args.out_dir / f"{s.name}.jsonl" for s in splits}
    for s in splits:
        for item in s.items:
            item["data_version"] = args.version
        write_jsonl(s.items, files[s.name])
    version_tag = args.version.removeprefix("train_")
    report = args.report or Path("docs/results") / f"training_data_{version_tag}.md"
    write_report(splits, files, args.version, args.manifest, report)
    for s in splits:
        print(f"{s.name}: {len(s.items)} items -> {files[s.name]}")
    print(f"report -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
