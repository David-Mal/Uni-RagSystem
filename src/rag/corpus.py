"""Corpus loaders and chunkers for free-exercise-db and synthesis docs (issue M5, #36)."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from src.exercises.loader import Exercise, load_exercises

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYNTHESIS_DIR = REPO_ROOT / "docs" / "knowledge"
DEFAULT_ALIASES_PATH = REPO_ROOT / "data" / "exercises" / "aliases.yaml"

# Canonical 9 allowed topic tags (docs/knowledge/TAGS.md, issue #24, plan §4.1)
DEFAULT_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "volume",
        "intensity",
        "rpe",
        "fatigue_load",
        "load_monitoring",
        "progression",
        "frequency",
        "logging",
        "confounders",
    }
)

APPROVALS_FILE = "approvals.yaml"

NON_SYNTHESIS_FILES: frozenset[str] = frozenset({"SOURCES.md", "TAGS.md", "TEMPLATE.md"})

ChunkingMode = Literal["heading", "fixed_256", "fixed_512", "sentence_window"]

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_WORD_RE = re.compile(r"\S+")
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")


class Chunk(BaseModel):
    """Unified chunk/document record shared across Chroma and BM25."""

    chunk_id: str
    corpus: Literal["exercises", "synthesis"]
    text: str
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def compute_content_hash(text: str, metadata: Mapping[str, Any]) -> str:
    """Deterministic SHA-256 hash over text and sorted metadata (excluding volatile fields)."""
    stable_meta = {k: v for k, v in sorted(metadata.items()) if k != "content_hash"}
    payload = f"{text}\n{yaml.safe_dump(stable_meta, sort_keys=True)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_allowed_tags(synthesis_dir: Path | str | None = None) -> frozenset[str]:
    """Parse allowed topic tags from ``docs/knowledge/TAGS.md`` if present, else use canonical set."""
    base = Path(synthesis_dir) if synthesis_dir is not None else DEFAULT_SYNTHESIS_DIR
    tags_file = base / "TAGS.md"
    if not tags_file.exists():
        return DEFAULT_ALLOWED_TAGS
    content = tags_file.read_text(encoding="utf-8")
    parsed = set(re.findall(r"^\s*-\s+`([a-z0-9_]+)`\s*$", content, re.MULTILINE))
    return frozenset(parsed) if parsed else DEFAULT_ALLOWED_TAGS


def load_approved_doc_ids(synthesis_dir: Path | str | None = None) -> frozenset[str]:
    """Documents that may be retrieved, from ``approvals.yaml``. No file means nothing is approved."""
    base = Path(synthesis_dir) if synthesis_dir is not None else DEFAULT_SYNTHESIS_DIR
    path = base / APPROVALS_FILE
    if not path.exists():
        return frozenset()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    approved = raw.get("approved") or {}
    if not isinstance(approved, dict):
        raise TypeError(f"{path}: 'approved' must map doc ids to their verification record")
    return frozenset(str(k) for k in approved)


def _load_aliases_by_id(aliases_path: Path | str | None = None) -> dict[str, list[str]]:
    target = Path(aliases_path) if aliases_path is not None else DEFAULT_ALIASES_PATH
    if not target.exists():
        return {}
    raw_doc = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    raw_aliases: Mapping[str, str] = raw_doc.get("aliases", raw_doc)
    by_id: dict[str, list[str]] = defaultdict(list)
    for alias, ex_id in raw_aliases.items():
        by_id[str(ex_id)].append(str(alias))
    return {k: sorted(set(v)) for k, v in by_id.items()}


def load_exercise_chunks(
    *,
    exercises: Mapping[str, Exercise] | None = None,
    exercises_path: Path | str | None = None,
    aliases_path: Path | str | None = None,
) -> list[Chunk]:
    """Build one unsplit document per free-exercise-db entry (plan §4.1)."""
    ex_map = exercises if exercises is not None else load_exercises(exercises_path)
    aliases_by_id = _load_aliases_by_id(aliases_path)

    chunks: list[Chunk] = []
    for ex_id in sorted(ex_map.keys()):
        ex = ex_map[ex_id]
        ex_aliases = aliases_by_id.get(ex_id, [])
        primary = [m.value for m in ex.primary_muscles]
        secondary = [m.value for m in ex.secondary_muscles]

        parts = [f"Exercise: {ex.name}"]
        if ex_aliases:
            parts.append(f"Aliases: {', '.join(ex_aliases)}")
        if primary:
            parts.append(f"Primary muscles: {', '.join(primary)}")
        if secondary:
            parts.append(f"Secondary muscles: {', '.join(secondary)}")
        if ex.equipment:
            parts.append(f"Equipment: {ex.equipment}")
        if ex.category:
            parts.append(f"Category: {ex.category}")
        if ex.mechanic:
            parts.append(f"Mechanic: {ex.mechanic}")

        text = "\n".join(parts)
        meta: dict[str, Any] = {
            "corpus": "exercises",
            "chunk_id": ex_id,
            "exercise_id": ex_id,
            "name": ex.name,
            "primary_muscles": primary,
            "secondary_muscles": secondary,
        }
        chunks.append(
            Chunk(
                chunk_id=ex_id,
                corpus="exercises",
                text=text,
                content_hash=compute_content_hash(text, meta),
                metadata=meta,
            )
        )
    return chunks


def _parse_front_matter(content: str, path: Path) -> tuple[dict[str, Any], str, int]:
    match = _FRONT_MATTER_RE.match(content)
    if not match:
        raise ValueError(f"Synthesis document {path} is missing YAML front matter")
    front = yaml.safe_load(match.group(1)) or {}
    if not isinstance(front, dict):
        raise TypeError(f"Front matter in {path} must be a YAML mapping")
    body = content[match.end() :]
    return front, body, match.end()


def _split_tokens_with_spans(
    text: str, base_offset: int, max_tokens: int, overlap: int
) -> list[tuple[str, int, int]]:
    matches = list(_WORD_RE.finditer(text))
    if not matches:
        return []
    if len(matches) <= max_tokens:
        start = base_offset + matches[0].start()
        end = base_offset + matches[-1].end()
        return [(text[matches[0].start() : matches[-1].end()], start, end)]

    step = max(1, max_tokens - overlap)
    windows: list[tuple[str, int, int]] = []
    idx = 0
    while idx < len(matches):
        end_idx = min(len(matches), idx + max_tokens)
        c_start = matches[idx].start()
        c_end = matches[end_idx - 1].end()
        windows.append((text[c_start:c_end], base_offset + c_start, base_offset + c_end))
        if end_idx >= len(matches):
            break
        idx += step
    return windows


def _chunk_by_heading(
    body: str, body_offset: int, max_tokens: int = 450, overlap: int = 50
) -> list[tuple[str, str, int, int]]:
    headings = list(_HEADING_RE.finditer(body))
    if not headings:
        spans = _split_tokens_with_spans(body, body_offset, max_tokens, overlap)
        return [("Introduction", text, s, e) for text, s, e in spans]

    sections: list[tuple[str, str, int, int]] = []
    for i, h_match in enumerate(headings):
        section_title = h_match.group(1).strip()
        sec_start = h_match.start()
        sec_end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        sec_text = body[sec_start:sec_end].strip()
        if not sec_text:
            continue
        inner_offset = body_offset + body.find(sec_text, sec_start, sec_end)
        for chunk_text, c_start, c_end in _split_tokens_with_spans(
            sec_text, inner_offset, max_tokens, overlap
        ):
            sections.append((section_title, chunk_text, c_start, c_end))
    return sections


def _chunk_sentence_window(
    body: str, body_offset: int, window_sentences: int = 6, stride: int = 4
) -> list[tuple[str, str, int, int]]:
    sents = [m for m in _SENTENCE_RE.finditer(body) if m.group(0).strip()]
    if not sents:
        return []
    headings = [(m.start(), m.group(1).strip()) for m in _HEADING_RE.finditer(body)]

    def section_for(pos: int) -> str:
        title = "Document"
        for h_pos, h_title in headings:
            if h_pos <= pos:
                title = h_title
            else:
                break
        return title

    results: list[tuple[str, str, int, int]] = []
    idx = 0
    while idx < len(sents):
        end_idx = min(len(sents), idx + window_sentences)
        c_start = sents[idx].start()
        c_end = sents[end_idx - 1].end()
        text = body[c_start:c_end].strip()
        if text:
            results.append((section_for(c_start), text, body_offset + c_start, body_offset + c_end))
        if end_idx >= len(sents):
            break
        idx += max(1, stride)
    return results


def load_synthesis_chunks(
    synthesis_dir: Path | str | None = None,
    *,
    chunking: ChunkingMode = "heading",
    allowed_tags: frozenset[str] | None = None,
    max_tokens: int = 450,
    overlap: int = 50,
    include_drafts: bool = False,
) -> list[Chunk]:
    """Load and chunk Markdown synthesis documents, failing if any chunk lacks an allowed tag.

    Every document is validated, but only documents listed in ``approvals.yaml`` give chunks, unless
    ``include_drafts`` is set (retrieval experiments only). ``max_tokens`` counts whitespace-separated words.
    """
    base = Path(synthesis_dir) if synthesis_dir is not None else DEFAULT_SYNTHESIS_DIR
    if not base.exists():
        return []

    valid_tags = allowed_tags if allowed_tags is not None else load_allowed_tags(base)
    approved = load_approved_doc_ids(base)
    seen_doc_ids: set[str] = set()
    md_files = sorted(
        p for p in base.glob("*.md") if p.name not in NON_SYNTHESIS_FILES and p.is_file()
    )

    chunks: list[Chunk] = []
    for path in md_files:
        raw_content = path.read_text(encoding="utf-8")
        front, body, body_offset = _parse_front_matter(raw_content, path)

        doc_id = str(front.get("doc_id") or path.stem).strip()
        topic_tags = [str(t).strip() for t in (front.get("topic_tags") or []) if str(t).strip()]
        citation_keys = [
            str(c).strip() for c in (front.get("citation_keys") or []) if str(c).strip()
        ]
        exercise_ids = [
            str(e).strip() for e in (front.get("exercise_ids") or []) if str(e).strip()
        ]

        if not topic_tags:
            raise ValueError(f"Synthesis doc {doc_id!r} ({path.name}) has no topic_tags")
        invalid = [t for t in topic_tags if t not in valid_tags]
        if invalid:
            raise ValueError(
                f"Synthesis doc {doc_id!r} ({path.name}) contains disallowed topic_tags: {invalid}"
            )

        if doc_id in seen_doc_ids:
            raise ValueError(f"Duplicate doc_id {doc_id!r} ({path.name})")
        seen_doc_ids.add(doc_id)
        if not include_drafts and doc_id not in approved:
            continue

        if chunking == "heading":
            raw_chunks = _chunk_by_heading(body, body_offset, max_tokens=max_tokens, overlap=overlap)
        elif chunking == "fixed_256":
            spans = _split_tokens_with_spans(body, body_offset, max_tokens=256, overlap=32)
            raw_chunks = [("fixed_256", text, s, e) for text, s, e in spans]
        elif chunking == "fixed_512":
            spans = _split_tokens_with_spans(body, body_offset, max_tokens=512, overlap=50)
            raw_chunks = [("fixed_512", text, s, e) for text, s, e in spans]
        elif chunking == "sentence_window":
            raw_chunks = _chunk_sentence_window(body, body_offset)
        else:
            raise ValueError(f"Unsupported chunking mode: {chunking!r}")

        for idx, (section, text, char_start, char_end) in enumerate(raw_chunks, start=1):
            chunk_id = f"{doc_id}#c{idx:02d}"
            meta: dict[str, Any] = {
                "corpus": "synthesis",
                "doc_id": doc_id,
                "section": section,
                "chunk_id": chunk_id,
                "citation_keys": citation_keys,
                "topic_tags": topic_tags,
                "exercise_ids": exercise_ids,
                "char_start": char_start,
                "char_end": char_end,
            }
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    corpus="synthesis",
                    text=text,
                    content_hash=compute_content_hash(text, meta),
                    metadata=meta,
                )
            )
    return chunks


def filter_matches(metadata: Mapping[str, Any], where: Mapping[str, Any] | None) -> bool:
    """Evaluate a unified metadata filter against a chunk's metadata dictionary.

    Supported filter keys:
      - ``corpus``: exact string match
      - ``doc_id``: exact string match
      - ``exercise_id``: exact string match
      - ``topic_tags_any``: list[str] — chunk's ``topic_tags`` must intersect this set
      - ``exclude_exercise_ids``: list[str] — chunk's ``exercise_ids`` must NOT intersect this set
      - ``allowed_exercise_ids``: list[str] — if chunk has non-empty ``exercise_ids``, all must be allowed
      - Any other key: exact equality (or membership if metadata value is a list)
    """
    if not where:
        return True
    for key, expected in where.items():
        if key == "topic_tags_any":
            chunk_tags = set(metadata.get("topic_tags") or [])
            if not (chunk_tags & set(expected)):
                return False
        elif key == "exclude_exercise_ids":
            chunk_exs = set(metadata.get("exercise_ids") or [])
            if chunk_exs & set(expected):
                return False
        elif key == "allowed_exercise_ids":
            chunk_exs = set(metadata.get("exercise_ids") or [])
            allowed = set(expected)
            if chunk_exs and not chunk_exs.issubset(allowed):
                return False
        else:
            val = metadata.get(key)
            if isinstance(val, Sequence) and not isinstance(val, str):
                if expected not in val:
                    return False
            elif val != expected:
                return False
    return True
