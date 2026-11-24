"""Prompt building and output parsing for the extraction SLM (issues F5, F6). No ML imports.

Shared by the baselines (F5) and the QLoRA smoke run (F6) so both use the same prompt and parser.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.datagen import vocab
from src.schemas import EXERCISE_IDS_CONTEXT_KEY, UNKNOWN_EXERCISE_ID, ExtractionResult

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
PROMPT_FILES = {"zero_shot": "extraction_v0_zeroshot.txt", "few_shot": "extraction_v0_fewshot.txt"}
FEWSHOT_PER_CLASS = 2
"""Few-shot uses 2 training-pool examples per triage class (6 total), picked deterministically."""


def default_exercise_ids() -> list[str]:
    """Closed exercise vocabulary for the v0 baselines: the generator's exercises + ``unknown`` (sorted).

    The full free-exercise-db (876 ids) is too long for a prompt. The same list is used for CD, so prompted and
    constrained runs see one vocabulary. See docs/results/week9_baselines.md.
    """
    return sorted({e.exercise_id for e in vocab.EXERCISES} | {UNKNOWN_EXERCISE_ID})


def label_json(labels: dict[str, Any]) -> str:
    """Canonical compact JSON of a label (training target and few-shot answer)."""
    ordered = {k: labels[k] for k in ExtractionResult.model_fields}
    return json.dumps(ordered, ensure_ascii=False, separators=(", ", ": "))


def pick_fewshot(train_items: Sequence[dict[str, Any]], per_class: int = FEWSHOT_PER_CLASS) -> list[dict[str, Any]]:
    """First ``per_class`` training-pool items of each class in file order (deterministic). Refuses non-train items."""
    picked: list[dict[str, Any]] = []
    for level in ("green", "yellow", "red"):
        picked += [it for it in train_items if it["labels"]["triage_level"] == level][:per_class]
    if any(it.get("pool") != "train" for it in picked):
        raise ValueError("few-shot examples must come from the training pool only")
    return picked


def build_prompt(text: str, setup: str, exercise_ids: Iterable[str], examples: Sequence[dict[str, Any]] = ()) -> str:
    """Fill the prompt template for ``setup`` (``zero_shot``/``few_shot``; CD variants reuse the zero-shot prompt)."""
    template = (PROMPTS_DIR / PROMPT_FILES["few_shot" if setup.startswith("few_shot") else "zero_shot"]).read_text(
        encoding="utf-8"
    )
    shots = "".join(f"Note: {ex['text']}\nJSON: {label_json(ex['labels'])}\n\n" for ex in examples)
    return (
        template.replace("{exercise_ids}", ", ".join(exercise_ids)).replace("{examples}", shots).replace("{text}", text)
    )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_output(raw: str, exercise_ids: Iterable[str] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Parse model output into a validated label dict. Returns ``(labels, None)`` or ``(None, error_code)``.

    Error codes: ``no_json`` (no braces), ``invalid_json``, ``schema_error`` (valid JSON, fails ``ExtractionResult``).
    Thinking blocks (``<think>…</think>``) are stripped first. Only the first top-level object is used.
    """
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    match = _JSON_RE.search(text)
    if not match:
        return None, "no_json"
    candidate = match.group(0)
    obj: Any = None
    for end in range(len(candidate), 0, -1):  # shrink to the first complete object if trailing text follows
        if candidate[end - 1] != "}":
            continue
        try:
            obj = json.loads(candidate[:end])
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(obj, dict):
        return None, "invalid_json"
    context = {EXERCISE_IDS_CONTEXT_KEY: set(exercise_ids)} if exercise_ids is not None else None
    try:
        return ExtractionResult.model_validate(obj, context=context).model_dump(mode="json"), None
    except ValidationError:
        return None, "schema_error"
