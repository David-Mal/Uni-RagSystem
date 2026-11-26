"""Leakage audit (issue P4, plan section 2.4 controls 5 and 3).

Run by someone who can see the golden messages. Checks every training item against the golden messages and the
reference examples (labeling guideline, plan section 3.3), and against the partition manifest. Writes only two files:
``drop_ids.txt`` (ids and reason codes) and a counts-only report. Golden text and golden ids never reach an output
file, a message or an error.

Usage::

    python scripts/leakage_audit.py --train data/training/train.jsonl --golden data/golden \\
        --manifest data/manifests/partition.yaml --out-drop-ids data/manifests/drop_ids.txt \\
        --out-report docs/results/leakage_audit.md --round 1 [--expect-clean]

The drop list is cumulative: ids already in ``--out-drop-ids`` stay there, because the builders regenerate the same
ids from the same seeds. Exit codes: 0 done, 1 ``--expect-clean`` and this round drops a new item, 2 input error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import operator
import os
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.datagen.partition import DEFAULT_PATH, Partition, PoolError, load_partition  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GUIDELINE_PATH = REPO / "docs" / "labeling-guideline.md"
PLAN_PATH = REPO / "docs" / "milestone2-architecture-and-plan.md"

JACCARD_THRESHOLD = Fraction(1, 2)
COSINE_THRESHOLD = 0.9
COSINE_DECIMALS = 9  # cosine is rounded before the comparison so a value on the threshold is not decided by noise
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Main-branch commit of the model repository, read from the Hugging Face API on 2026-11-26.
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

# file stem -> (expected pool, expected consumer of the phrasing family)
FILE_STEMS: dict[str, tuple[str, str]] = {
    "train": ("train", "extractor"),
    "dev": ("dev", "extractor"),
    "red_dev": ("dev", "extractor"),
    "triage_train": ("train", "classifier"),
    "triage_dev": ("dev", "classifier"),
}
REASONS = (
    "exact_duplicate",
    "jaccard",
    "cosine",
    "reference_exact_duplicate",
    "reference_jaccard",
    "reference_cosine",
    "compliance_missing_field",
    "compliance_pool",
    "compliance_seed",
    "compliance_persona",
    "compliance_family",
    "compliance_consumer",
)
_GUIDELINE_RE = re.compile(r'\*\*guideline example:\*\*\s*["“]([^"”]+)["”]')
_PLAN_INPUT_RE = re.compile(r'Input:\s*["“]([^"”]+)["”]')


class AuditInputError(ValueError):
    """Bad input. The message names a file and a line, never content."""


class Embedder(Protocol):
    """Anything that turns texts into vectors."""

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """The real embedder. Imports the library lazily so tests and CI do not need torch."""

    def __init__(self, model_name: str = MODEL_NAME, revision: str = MODEL_REVISION) -> None:
        import sentence_transformers
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.revision = revision
        self.library_version = sentence_transformers.__version__
        self._model = SentenceTransformer(model_name, revision=revision)

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in row] for row in self._model.encode(texts, show_progress_bar=False)]


# ---- normalization and similarity ----


def tokens(text: str) -> list[str]:
    """NFKC, lowercase, every non-alphanumeric character becomes a space, split on whitespace."""
    folded = unicodedata.normalize("NFKC", text).lower()
    return "".join(c if c.isalnum() else " " for c in folded).split()


def grams(toks: Sequence[str]) -> frozenset[tuple[str, ...]]:
    """Word 3-grams; fewer than 3 words give the set of single words."""
    if len(toks) < 3:
        return frozenset((t,) for t in toks)
    return frozenset(tuple(toks[i : i + 3]) for i in range(len(toks) - 2))


def jaccard(a: frozenset, b: frozenset) -> Fraction:
    """|A and B| / |A or B|, 0 when both are empty."""
    union = len(a | b)
    return Fraction(len(a & b), union) if union else Fraction(0)


def unit(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else [0.0] * len(vec)


_dot = getattr(math, "sumprod", None) or (lambda a, b: sum(map(operator.mul, a, b)))


def cosine_hit(a: Sequence[float], b: Sequence[float]) -> bool:
    """Both vectors are unit vectors."""
    return round(_dot(a, b), COSINE_DECIMALS) >= COSINE_THRESHOLD


# ---- reference examples ----


def guideline_examples(path: Path = GUIDELINE_PATH) -> list[str]:
    """Quoted text after each ``**guideline example:**`` marker."""
    return _GUIDELINE_RE.findall(path.read_text(encoding="utf-8"))


def plan_examples(path: Path = PLAN_PATH) -> list[str]:
    """Quoted ``Input:`` texts inside section 3.3 of the plan."""
    text = path.read_text(encoding="utf-8")
    start = text.find("### 3.3 ")
    if start < 0:
        raise AuditInputError(f"{path.name}: section 3.3 not found")
    end = text.find("\n### ", start + 1)
    return _PLAN_INPUT_RE.findall(text[start : end if end > 0 else len(text)])


def reference_examples(guideline: Path = GUIDELINE_PATH, plan: Path = PLAN_PATH) -> list[str]:
    return [*guideline_examples(guideline), *plan_examples(plan)]


# ---- reading ----


def read_jsonl(path: Path) -> list[tuple[int, dict]]:
    """Return ``(line number, object)`` pairs. Errors name the file and line only."""
    rows: list[tuple[int, dict]] = []
    try:
        # Not splitlines(): it also splits on characters such as U+2028, which are legal inside JSON strings.
        lines = path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise AuditInputError(f"{path.name}: cannot read file ({type(exc).__name__})") from None
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            raise AuditInputError(f"{path.name}:{n}: invalid JSON") from None
        if not isinstance(obj, dict):
            raise AuditInputError(f"{path.name}:{n}: line is not a JSON object")
        rows.append((n, obj))
    return rows


def expand_golden(paths: Sequence[Path]) -> list[Path]:
    """A directory stands for its ``messages_*.jsonl`` files. Nothing else is globbed."""
    if not paths:
        raise AuditInputError("at least one --golden path is required")
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            found = sorted(p.glob("messages_*.jsonl"))
            if not found:
                raise AuditInputError(f"{p.name}: no messages_*.jsonl files in directory")
            files.extend(found)
        elif p.is_file():
            files.append(p)
        else:
            raise AuditInputError(f"{p.name}: golden path does not exist")
    return files


def read_golden(files: Sequence[Path]) -> list[str]:
    texts: list[str] = []
    for f in files:
        for n, obj in read_jsonl(f):
            for key in ("item_id", "text"):
                if not isinstance(obj.get(key), str) or not obj[key].strip():
                    raise AuditInputError(f"{f.name}:{n}: missing or empty {key!r}")
            texts.append(obj["text"])
    if not texts:
        raise AuditInputError("golden files contain no items")
    return texts


@dataclass
class TrainItem:
    item_id: str
    obj: dict
    file: str
    line: int


def read_training(path: Path) -> list[TrainItem]:
    items = []
    for n, obj in read_jsonl(path):
        item_id = obj.get("item_id")
        if not isinstance(item_id, str) or not item_id or "#" in item_id or any(c.isspace() for c in item_id):
            raise AuditInputError(f"{path.name}:{n}: missing or unusable 'item_id'")
        items.append(TrainItem(item_id, obj, path.name, n))
    return items


# ---- compliance ----


def compliance_reasons(obj: dict, pool: str, consumer: str, partition: Partition) -> set[str]:
    """Manifest compliance of one item (D6). Every failure has its own reason."""
    reasons: set[str] = set()
    if not _has_text(obj):
        reasons.add("compliance_missing_field")

    got_pool = obj.get("pool")
    if got_pool is None:
        reasons.add("compliance_missing_field")
    elif got_pool != pool:
        reasons.add("compliance_pool")

    seed = obj.get("seed")
    if seed is None:
        reasons.add("compliance_missing_field")
    else:
        lo, hi = partition.seed_range(pool)
        if isinstance(seed, bool) or not isinstance(seed, int) or not lo <= seed <= hi:
            reasons.add("compliance_seed")

    persona = obj.get("persona_id")
    if persona is None:
        reasons.add("compliance_missing_field")
    elif not isinstance(persona, str) or persona not in partition.members("personas", pool):
        reasons.add("compliance_persona")

    family = obj.get("phrasing_family")
    if family is None:
        reasons.add("compliance_missing_field")
    else:
        fams = {f.id: f for f in partition.phrasing_families[pool]}  # type: ignore[index]
        if not isinstance(family, str) or family not in fams:
            reasons.add("compliance_family")
        elif fams[family].consumer != consumer:
            reasons.add("compliance_consumer")
    return reasons


# ---- the audit ----


@dataclass
class FileStats:
    checked: int = 0
    dropped: int = 0
    reasons: Counter = field(default_factory=Counter)


@dataclass
class AuditResult:
    drops: dict[str, set[str]]
    """Items dropped by this round's checks."""
    stats: dict[str, FileStats]
    n_golden: int
    n_reference: int
    round_no: int
    model: str
    revision: str
    library_version: str
    hashes: dict[str, str]
    carried: dict[str, str] = field(default_factory=dict)
    """Ids already in the drop list from earlier rounds, with their recorded reasons. They are kept: the builders
    regenerate the same ids from the same seeds, so removing them from the list would bring them back."""

    @property
    def clean(self) -> bool:
        """No new drop in this round."""
        return not self.drops


class _Index:
    """Texts to compare against: exact token sequences, an inverted index on grams, and unit vectors."""

    def __init__(self, texts: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        toks = [tokens(t) for t in texts]
        self.exact = {tuple(t) for t in toks if t}
        self.sets = [grams(t) for t in toks]
        self.inverted: dict[tuple[str, ...], list[int]] = {}
        for i, s in enumerate(self.sets):
            for g in s:
                self.inverted.setdefault(g, []).append(i)
        self.units = [unit(v) for v in vectors]

    def jaccard_hit(self, g: frozenset) -> bool:
        counts: Counter = Counter()
        for gram in g:
            counts.update(self.inverted.get(gram, ()))
        return any(Fraction(c, len(g) + len(self.sets[i]) - c) >= JACCARD_THRESHOLD for i, c in counts.items())

    def cosine_hit(self, vec: Sequence[float]) -> bool:
        return any(cosine_hit(vec, u) for u in self.units)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_text(obj: dict) -> bool:
    return isinstance(obj.get("text"), str) and bool(obj["text"].strip())


def run_audit(
    train_files: Sequence[Path],
    golden_files: Sequence[Path],
    manifest: Path,
    embedder: Embedder,
    round_no: int,
    guideline: Path = GUIDELINE_PATH,
    plan: Path = PLAN_PATH,
) -> AuditResult:
    """Compute every check. Writes nothing."""
    golden_paths = expand_golden(golden_files)
    partition = load_partition(manifest)
    per_file: list[tuple[str, str, str, list[TrainItem]]] = []
    seen: set[str] = set()
    stems: set[str] = set()
    for path in train_files:
        if path.stem not in FILE_STEMS:
            raise AuditInputError(f"{path.name}: unknown training file (expected one of {', '.join(FILE_STEMS)})")
        if path.stem in stems:
            raise AuditInputError(f"{path.name}: training file given twice")
        stems.add(path.stem)
        pool, consumer = FILE_STEMS[path.stem]
        items = read_training(path)
        for it in items:
            if it.item_id in seen:
                raise AuditInputError(f"{it.file}:{it.line}: duplicate item_id across training files")
            seen.add(it.item_id)
        per_file.append((path.stem, pool, consumer, items))
    if not per_file:
        raise AuditInputError("at least one --train file is required")

    golden_texts = read_golden(golden_paths)
    ref_texts = reference_examples(guideline, plan)
    all_train = [it for _, _, _, items in per_file for it in items if _has_text(it.obj)]
    vectors = embedder.encode([*golden_texts, *ref_texts, *(it.obj["text"] for it in all_train)])
    if len(vectors) != len(golden_texts) + len(ref_texts) + len(all_train):
        raise AuditInputError("embedder returned the wrong number of vectors")
    n_g, n_r = len(golden_texts), len(ref_texts)
    golden = _Index(golden_texts, vectors[:n_g])
    refs = _Index(ref_texts, vectors[n_g : n_g + n_r])
    train_vec = {it.item_id: unit(v) for it, v in zip(all_train, vectors[n_g + n_r :], strict=True)}

    drops: dict[str, set[str]] = {}
    stats: dict[str, FileStats] = {}
    for stem, pool, consumer, items in per_file:
        st = stats[stem] = FileStats()
        for it in items:
            reasons = compliance_reasons(it.obj, pool, consumer, partition)
            if _has_text(it.obj):
                toks = tokens(it.obj["text"])
                g = grams(toks)
                for prefix, index in (("", golden), ("reference_", refs)):
                    if toks and tuple(toks) in index.exact:
                        reasons.add(prefix + "exact_duplicate")
                    if index.jaccard_hit(g):
                        reasons.add(prefix + "jaccard")
                    if index.cosine_hit(train_vec[it.item_id]):
                        reasons.add(prefix + "cosine")
            st.checked += 1
            if reasons:
                drops[it.item_id] = reasons
                st.dropped += 1
                st.reasons.update(reasons)

    inputs = {f"train/{p.name}": p for p in train_files}
    inputs.update({f"golden/{p.name}": p for p in golden_paths})
    inputs.update({"manifest": manifest, "guideline": guideline, "plan": plan})
    return AuditResult(
        drops=drops,
        stats=stats,
        n_golden=n_g,
        n_reference=n_r,
        round_no=round_no,
        model=getattr(embedder, "model_name", type(embedder).__name__),
        revision=getattr(embedder, "revision", "n/a"),
        library_version=getattr(embedder, "library_version", "n/a"),
        hashes={k: sha256_of(p) for k, p in sorted(inputs.items())},
    )


# ---- outputs ----


def read_previous_drops(path: Path) -> dict[str, str]:
    """Ids and reason text of an existing drop list (same format as ``drop_ids_text``); missing file = empty."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        item_id, _, reasons = line.partition("#")
        item_id = item_id.strip()
        if item_id:
            out[item_id] = reasons.strip() or "earlier_round"
    return out


def drop_ids_text(result: AuditResult) -> str:
    """The cumulative drop list: earlier rounds plus this round, one id per line, sorted."""
    merged = dict(result.carried)
    for i, r in result.drops.items():
        merged[i] = ",".join(sorted(r))
    lines = [f"# leakage audit round {result.round_no}: ids to drop (cumulative over rounds), with the reasons"]
    lines += [f"{i}  # {r}" for i, r in sorted(merged.items())]
    return "\n".join(lines) + "\n"


def report_text(result: AuditResult) -> str:
    out = [
        "# Leakage audit",
        "",
        f"- Round: {result.round_no}",
        f"- Clean (no new drop): {'yes' if result.clean else 'no'}",
        f"- New drops in this round: {len(result.drops)}",
        f"- Ids in the drop list from earlier rounds: {len(set(result.carried) - set(result.drops))}",
        f"- Golden items checked against: {result.n_golden}",
        f"- Reference examples (guideline, plan section 3.3): {result.n_reference}",
        "",
        "## Thresholds",
        "",
        "- Text normalization: NFKC, lowercase, non-alphanumeric characters become spaces.",
        f"- Word 3-gram Jaccard >= {float(JACCARD_THRESHOLD)} (texts under 3 words: single words)",
        f"- Embedding cosine >= {COSINE_THRESHOLD} (rounded to {COSINE_DECIMALS} decimals)",
        "- Exact duplicate: identical normalized word sequence",
        f"- Model: `{result.model}`",
        f"- Revision: `{result.revision}`",
        f"- sentence-transformers version: `{result.library_version}`",
        "",
        "## Training files",
        "",
        "| File | Items checked | New drops |",
        "|---|---|---|",
    ]
    out += [f"| {s} | {st.checked} | {st.dropped} |" for s, st in sorted(result.stats.items())]
    out += ["", "## Drops per reason", "", "| File | Reason | Count |", "|---|---|---|"]
    for s, st in sorted(result.stats.items()):
        out += [f"| {s} | {r} | {st.reasons[r]} |" for r in REASONS if st.reasons[r]]
    out += ["", "## Input files (sha256)", "", "| Input | sha256 |", "|---|---|"]
    out += [f"| {k} | `{v}` |" for k, v in sorted(result.hashes.items())]
    return "\n".join(out) + "\n"


def write_pair(first: tuple[Path, str], second: tuple[Path, str]) -> None:
    """Write both files through temp files, so a failure while writing leaves neither of them changed."""
    pairs = [first, second]
    tmps = [p.with_name(f".{p.name}.tmp") for p, _ in pairs]
    try:
        for path, _ in pairs:
            path.parent.mkdir(parents=True, exist_ok=True)
        for (_, content), tmp in zip(pairs, tmps, strict=True):
            tmp.write_text(content, encoding="utf-8", newline="\n")
        for (path, _), tmp in zip(pairs, tmps, strict=True):
            os.replace(tmp, path)
    finally:
        for tmp in tmps:
            tmp.unlink(missing_ok=True)


# ---- CLI ----


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Leakage audit of the training data against the golden messages.")
    ap.add_argument("--train", type=Path, action="append", default=[], help="training JSONL, repeatable")
    ap.add_argument("--golden", type=Path, action="append", default=[], help="golden JSONL or directory, repeatable")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--out-drop-ids", type=Path, default=Path("data/manifests/drop_ids.txt"))
    ap.add_argument("--out-report", type=Path, default=Path("docs/results/leakage_audit.md"))
    ap.add_argument("--round", type=int, required=True, dest="round_no")
    ap.add_argument("--expect-clean", action="store_true", help="exit 1 if this round drops any new item")
    return ap


def main(argv: list[str] | None = None, embedder: Embedder | None = None) -> int:
    """CLI entry point. ``embedder`` is for tests, the command line always uses the real model."""
    args = _parser().parse_args(argv)
    try:
        if embedder is None:
            try:
                embedder = SentenceTransformerEmbedder()
            except ImportError:
                raise AuditInputError("sentence-transformers is not installed (uv sync --group embed)") from None
        result = run_audit(args.train, args.golden, args.manifest, embedder, args.round_no)
        result.carried = read_previous_drops(args.out_drop_ids)
        write_pair((args.out_drop_ids, drop_ids_text(result)), (args.out_report, report_text(result)))
    except (AuditInputError, PoolError, OSError) as exc:
        print(f"error: {exc}" if isinstance(exc, AuditInputError) else f"error: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"round {result.round_no}: {len(result.drops)} new items to drop, {len(result.carried)} from earlier rounds")
    print(f"wrote {args.out_drop_ids} and {args.out_report}")
    return 1 if args.expect_clean and not result.clean else 0


if __name__ == "__main__":
    raise SystemExit(main())
