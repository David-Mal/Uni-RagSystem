"""CLI of the evaluation harness (issue P2).

    python -m src.eval.run --task extraction --pred preds.jsonl --gold gold.jsonl --out results/E3/<run_id>/eval/
    python -m src.eval.run --mode compare --pred a.jsonl --pred-b b.jsonl --gold gold.jsonl --out <dir>

Everything is validated and computed before anything is written. Exit code 2 on any invalid input. Neither the
outputs nor the messages contain text, raw model output or per-item labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from src.eval import metrics as M
from src.eval.metrics import EvalError, Item
from src.eval.stats import bootstrap, group_sum
from src.schemas import EXERCISE_IDS_CONTEXT_KEY, SCHEMA_VERSION, ExtractionResult

HARNESS_VERSION = "0.1.0"
ERROR_CODES = ("no_json", "invalid_json", "schema_error")
MIN_RESAMPLES = 2000
MIN_CLUSTERS = 10
OUTPUT_FILES = ("metrics.json", "config.yaml", "run_manifest.json")


@dataclass(frozen=True)
class Pred:
    """A loaded prediction: label values, or ``None`` for a failure."""

    values: dict[str, Any] | None
    valid_json: bool


# --- input -------------------------------------------------------------------------------------------------------


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate key")
    return obj


def _no_constant(_: str) -> Any:
    raise ValueError("NaN or Infinity")


def read_jsonl(path: Path) -> tuple[str, list[tuple[int, dict[str, Any]]]]:
    """Return (sha256 of the raw bytes, [(line number, object)]). Blank lines are skipped; empty files are errors."""
    try:
        data = path.read_bytes()
        text = data.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvalError(f"{path}: cannot read file as UTF-8 ({type(exc).__name__})") from None
    rows: list[tuple[int, dict[str, Any]]] = []
    # Not splitlines(): it also splits on characters such as U+2028, which are legal inside JSON strings.
    for no, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        except (ValueError, RecursionError):
            raise EvalError(f"{path}:{no}: malformed JSON or duplicate key") from None
        if not isinstance(obj, dict):
            raise EvalError(f"{path}:{no}: line is not a JSON object")
        rows.append((no, obj))
    if not rows:
        raise EvalError(f"{path}: file has no items")
    return hashlib.sha256(data).hexdigest(), rows


def load_exercise_ids(path: Path) -> tuple[str, frozenset[str]]:
    """Read an id set from a JSON list or one id per line; returns (sha256, ids)."""
    try:
        data = path.read_bytes()
        text = data.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvalError(f"{path}: cannot read file as UTF-8 ({type(exc).__name__})") from None
    if text.lstrip().startswith("["):
        try:
            ids = json.loads(text)
        except ValueError:
            raise EvalError(f"{path}: malformed JSON list") from None
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise EvalError(f"{path}: expected a JSON list of strings")
    else:
        ids = [line.strip() for line in text.splitlines() if line.strip()]
    if not ids:
        raise EvalError(f"{path}: no exercise ids")
    return hashlib.sha256(data).hexdigest(), frozenset(ids)


def _item_id(path: Path, no: int, row: dict[str, Any], seen: dict[str, Any]) -> str:
    item_id = row.get("item_id")
    if not isinstance(item_id, str) or not item_id:
        raise EvalError(f"{path}:{no}: item_id must be a non-empty string")
    if item_id in seen:
        raise EvalError(f"{path}:{no}: duplicate item_id {item_id!r}")
    return item_id


def _validate(labels: Any, ids: frozenset[str] | None) -> ExtractionResult | None:
    """Revalidate with ``ExtractionResult``; ``None`` if invalid. Never reports input values."""
    try:
        context = None if ids is None else {EXERCISE_IDS_CONTEXT_KEY: ids}
        return ExtractionResult.model_validate(labels, context=context)
    except ValidationError:
        return None


def load_gold(path: Path, ids: frozenset[str] | None) -> tuple[str, dict[str, tuple[dict[str, Any], dict[str, Any]]]]:
    """Load and validate gold items; any invalid item is an error. Returns (sha256, id -> (row, label values))."""
    sha, rows = read_jsonl(path)
    gold: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for no, row in rows:
        item_id = _item_id(path, no, row, gold)
        result = _validate(row.get("labels"), ids)
        if result is None:
            fields = _bad_fields(row.get("labels"), ids)
            raise EvalError(f"{path}:{no}: item {item_id!r}: invalid labels (fields: {fields})")
        gold[item_id] = (row, M.label_values(result))
    return sha, gold


def _bad_fields(labels: Any, ids: frozenset[str] | None) -> str:
    if not isinstance(labels, dict):
        return "labels is not an object"
    try:
        context = None if ids is None else {EXERCISE_IDS_CONTEXT_KEY: ids}
        ExtractionResult.model_validate(labels, context=context)
    except ValidationError as exc:
        # Only schema field names: an unexpected key is input and is never echoed.
        names = {e["loc"][0] if e["loc"] else "labels" for e in exc.errors()}
        return ", ".join(sorted({n if n in (*M.FIELDS, "labels") else "unexpected key" for n in names}))
    return "?"


def load_preds(path: Path, ids: frozenset[str] | None) -> tuple[str, dict[str, Pred]]:
    """Load predictions ``{item_id, pred, raw?, error?}``; a null or invalid ``pred`` is a failure.

    A non-null ``pred`` together with ``error``, or an unknown ``error`` code, is contradictory input and an error.
    JSON validity: a non-null ``pred`` (even if it fails revalidation) or ``error == schema_error``.
    """
    sha, rows = read_jsonl(path)
    preds: dict[str, Pred] = {}
    for no, row in rows:
        item_id = _item_id(path, no, row, preds)
        if "pred" not in row:
            raise EvalError(f"{path}:{no}: item {item_id!r}: missing key 'pred'")
        pred, error = row["pred"], row.get("error")
        if error is not None and error not in ERROR_CODES:
            raise EvalError(f"{path}:{no}: item {item_id!r}: unknown error code (expected one of {ERROR_CODES})")
        if pred is not None and error is not None:
            raise EvalError(f"{path}:{no}: item {item_id!r}: non-null pred together with error")
        if pred is None:
            preds[item_id] = Pred(None, error == "schema_error")
            continue
        result = _validate(pred, ids)
        preds[item_id] = Pred(None if result is None else M.label_values(result), True)
    return sha, preds


def _check_ids(name: str, path: Path, ids: Sequence[str], gold_ids: Sequence[str]) -> None:
    missing, extra = sorted(set(gold_ids) - set(ids)), sorted(set(ids) - set(gold_ids))
    if missing or extra:
        def show(xs: list[str]) -> str:
            return ", ".join(repr(x) for x in xs[:10]) + (f" and {len(xs) - 10} more" if len(xs) > 10 else "")

        parts = [f"{len(missing)} missing ({show(missing)})"] if missing else []
        parts += [f"{len(extra)} extra ({show(extra)})"] if extra else []
        raise EvalError(f"{path}: item_ids do not match {name}: " + "; ".join(parts))


def build_items(
    gold: dict[str, tuple[dict[str, Any], dict[str, Any]]], preds: dict[str, Pred], path: Path, gold_path: Path
) -> list[Item]:
    """Pair gold and predictions in gold file order; the id sets must be identical."""
    _check_ids(f"gold file {gold_path}", path, list(preds), list(gold))
    return [Item(i, vals, preds[i].values, preds[i].valid_json, row) for i, (row, vals) in gold.items()]


# --- reports -----------------------------------------------------------------------------------------------------


def _bootstrap_block(
    items: Sequence[Item], paired: Sequence[Item] | None, cluster_by: str | None, resamples: int, seed: int
) -> tuple[dict[str, Any], list[str]]:
    """Bootstrap over items or clusters; with ``paired`` (model B) it bootstraps B - A on the same indices."""
    vectors = [M.item_vector(a) for a in items]
    if paired is not None:
        vectors = [va + M.item_vector(b) for va, b in zip(vectors, paired, strict=True)]
    warnings: list[str] = []
    unit = "items"
    if cluster_by:
        vectors = group_sum(vectors, M.cluster_keys(items, cluster_by))
        unit = "clusters"
        if len(vectors) < MIN_CLUSTERS:
            warnings.append(f"only {len(vectors)} clusters: bootstrap intervals are unreliable")
    stat = M.paired_stats if paired is not None else M.stats_from_sums
    block = {
        "unit": unit,
        "n_units": len(vectors),
        "n_resamples": resamples,
        "seed": seed,
        "level": 0.95,
        "metrics": bootstrap(vectors, stat, resamples, seed),
    }
    return block, warnings


def score_report(
    items: Sequence[Item], slices: Sequence[str], cluster_by: str | None, resamples: int, seed: int
) -> dict:
    """Report of ``--mode score``."""
    report = M.compute_metrics(items)
    report["majority_baseline"] = M.majority_baseline(items)
    report["bootstrap"], warnings = _bootstrap_block(items, None, cluster_by, resamples, seed)
    report["slices"] = {f: M.slice_metrics(items, f) for f in slices}
    report["warnings"] = M.undefined_warnings(report["headline"]) + warnings
    return report


def compare_report(
    items_a: Sequence[Item], items_b: Sequence[Item], cluster_by: str | None, resamples: int, seed: int
) -> dict:
    """Report of ``--mode compare``; differences are defined as B - A."""
    ma, mb = M.compute_metrics(items_a), M.compute_metrics(items_b)
    boot, warnings = _bootstrap_block(items_a, items_b, cluster_by, resamples, seed)
    diff = {
        "micro_f1": _sub(mb["headline"]["micro"]["f1"], ma["headline"]["micro"]["f1"]),
        "macro_f1": _sub(mb["headline"]["macro_f1"], ma["headline"]["macro_f1"]),
        "red_recall": _sub(mb["triage"]["red_recall"], ma["triage"]["red_recall"]),
    }
    return {
        "n_items": len(items_a),
        "difference_definition": "B - A (pred-b minus pred)",
        "model_a": ma,
        "model_b": mb,
        "majority_baseline": M.majority_baseline(items_a),
        "difference_point": diff,
        "bootstrap": boot,
        "mcnemar": M.mcnemar_tests(items_a, items_b),
        "warnings": M.undefined_warnings(ma["headline"], "A: ")
        + M.undefined_warnings(mb["headline"], "B: ")
        + warnings,
    }


def _sub(b: float | None, a: float | None) -> float | None:
    return None if a is None or b is None else b - a


# --- manifest and output ------------------------------------------------------------------------------------------


def _git(*args: str) -> str | None:
    try:
        cwd = Path(__file__).resolve().parent
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=30)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def git_info() -> dict[str, Any]:
    """Commit, dirty flag (any change or untracked file) and freeze tag; ``None`` where git is unavailable.

    The freeze tag is the first tag (alphabetical) at HEAD whose name contains ``golden`` or ``freeze``.
    """
    status = _git("status", "--porcelain")
    tags = _git("tag", "--points-at", "HEAD")
    named = sorted(t for t in (tags or "").split() if "golden" in t.lower() or "freeze" in t.lower())
    return {
        "commit": _git("rev-parse", "HEAD") or None,
        "dirty": None if status is None else bool(status),
        "freeze_tag": named[0] if named else None,
    }


def is_golden_path(path: Path) -> bool:
    """True if the resolved path has the consecutive parts ``data/golden`` (case-insensitive)."""
    parts = [p.lower() for p in path.resolve().parts]
    return any(a == "data" and b == "golden" for a, b in zip(parts, parts[1:]))


def build_manifest(args: argparse.Namespace, hashes: dict[str, str | None]) -> dict[str, Any]:
    """Run manifest (D10): records, never blocks."""
    git = git_info()
    inputs = {
        name: None if path is None else {"path": str(path), "sha256": hashes[name]}
        for name, path in (
            ("gold", args.gold),
            ("pred", args.pred),
            ("pred_b", args.pred_b),
            ("exercise_ids", args.exercise_ids),
        )
    }
    return {
        "harness_version": HARNESS_VERSION,
        "schema_version": SCHEMA_VERSION,
        "task": args.task,
        "mode": args.mode,
        "git_commit": git["commit"],
        "git_dirty": git["dirty"],
        "freeze_tag": git["freeze_tag"],
        "gold_is_golden": is_golden_path(args.gold),
        "inputs": inputs,
    }


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_outputs(out: Path, contents: dict[str, str]) -> None:
    """Write all files via temporary names, then rename; on failure remove everything written."""
    created_dir = not out.exists()
    out.mkdir(parents=True, exist_ok=True)
    tmps = {name: out / f".{name}.tmp" for name in contents}
    done: list[Path] = []
    try:
        for name, text in contents.items():
            with open(tmps[name], "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        for name in contents:
            os.replace(tmps[name], out / name)
            done.append(out / name)
    except BaseException:
        for path in [*tmps.values(), *done]:
            path.unlink(missing_ok=True)
        if created_dir:
            try:
                out.rmdir()
            except OSError:
                pass
        raise


# --- CLI ---------------------------------------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    p = argparse.ArgumentParser(prog="python -m src.eval.run", description="Score extraction predictions (P2).")
    p.add_argument("--task", choices=("extraction",), default="extraction")
    p.add_argument("--mode", choices=("score", "compare"), default="score")
    p.add_argument("--pred", type=Path, required=True, help="predictions JSONL (model A in compare mode)")
    p.add_argument("--pred-b", type=Path, help="predictions JSONL of model B (compare mode only)")
    p.add_argument("--gold", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True, help="output directory (separate from the run directory)")
    p.add_argument("--exercise-ids", type=Path, help="JSON list or one id per line; checked for gold and preds")
    p.add_argument("--slice-by", action="append", default=[], metavar="FIELD", help="top-level gold field; repeatable")
    p.add_argument("--cluster-by", metavar="FIELD", help="top-level gold field; resample whole clusters")
    p.add_argument("--resamples", type=int, default=MIN_RESAMPLES)
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args(argv)


def _check_args(args: argparse.Namespace) -> None:
    if args.resamples < MIN_RESAMPLES:
        raise EvalError(f"--resamples must be at least {MIN_RESAMPLES}")
    if args.mode == "compare" and args.pred_b is None:
        raise EvalError("--mode compare needs --pred-b")
    if args.mode == "score" and args.pred_b is not None:
        raise EvalError("--pred-b needs --mode compare")
    if args.mode == "compare" and args.slice_by:
        raise EvalError("--slice-by is only supported in score mode")
    if args.out.exists() and not args.out.is_dir():
        raise EvalError(f"{args.out}: not a directory")
    existing = [n for n in OUTPUT_FILES if (args.out / n).exists()]
    if existing:
        raise EvalError(f"{args.out}: refusing to overwrite existing output files: {', '.join(existing)}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Validate, compute and write; returns the report."""
    _check_args(args)
    hashes: dict[str, str | None] = {"gold": None, "pred": None, "pred_b": None, "exercise_ids": None}
    ids = None
    if args.exercise_ids is not None:
        hashes["exercise_ids"], ids = load_exercise_ids(args.exercise_ids)
    hashes["gold"], gold = load_gold(args.gold, ids)
    hashes["pred"], preds = load_preds(args.pred, ids)
    items = build_items(gold, preds, args.pred, args.gold)
    if args.mode == "compare":
        hashes["pred_b"], preds_b = load_preds(args.pred_b, ids)
        items_b = build_items(gold, preds_b, args.pred_b, args.gold)
        report = compare_report(items, items_b, args.cluster_by, args.resamples, args.seed)
    else:
        report = score_report(items, args.slice_by, args.cluster_by, args.resamples, args.seed)
    report.update({"harness_version": HARNESS_VERSION, "task": args.task, "mode": args.mode})
    config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    contents = {
        "metrics.json": _dumps(report),
        "config.yaml": yaml.safe_dump(config, sort_keys=True),
        "run_manifest.json": _dumps(build_manifest(args, hashes)),
    }
    write_outputs(args.out, contents)
    print(f"gold sha256: {hashes['gold']}")
    return report


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.4f}"


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: 0 on success, 2 on invalid input or usage."""
    args = parse_args(argv)
    try:
        report = run(args)
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for warning in report["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    if args.mode == "compare":
        d = report["difference_point"]
        print("B - A: " + ", ".join(f"{k} {_fmt(v)}" for k, v in d.items()))
    else:
        print(
            f"micro F1 {_fmt(report['headline']['micro']['f1'])}, macro F1 {_fmt(report['headline']['macro_f1'])}, "
            f"red recall {_fmt(report['triage']['red_recall'])}"
        )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
