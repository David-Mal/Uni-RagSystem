"""Tests for prompt building and output parsing (issues F5, F6). No ML imports."""

from __future__ import annotations

import re

import pytest

from src.training.extraction_io import (
    PROMPTS_DIR,
    build_prompt,
    default_exercise_ids,
    label_json,
    parse_output,
    pick_fewshot,
)

LABELS = {
    "exercise_id": "Barbell_Squat",
    "kinematic_observation": "grinding_rep",
    "load": {"value": 140.0, "unit": "kg"},
    "reps": 3,
    "outcome": "completed",
    "rpe": 9.0,
    "triage_level": "yellow",
}


def item(level: str, pool: str = "train", text: str = "squat 140kg x3") -> dict:
    return {"text": text, "pool": pool, "labels": {**LABELS, "triage_level": level}}


def test_vocab_includes_unknown_and_is_sorted() -> None:
    ids = default_exercise_ids()
    assert "unknown" in ids and ids == sorted(ids) and "Barbell_Squat" in ids


def test_zero_shot_prompt_has_text_and_ids_but_no_examples() -> None:
    p = build_prompt("bench 100kg x5", "zero_shot", ["Barbell_Squat", "unknown"])
    assert "Note: bench 100kg x5\nJSON:" in p
    assert "Barbell_Squat, unknown" in p
    assert "{examples}" not in p and "{text}" not in p and p.count("Note:") == 1


def test_few_shot_prompt_contains_training_examples() -> None:
    shots = pick_fewshot([item("green"), item("yellow"), item("red"), item("red")], per_class=1)
    p = build_prompt("bench 100kg x5", "few_shot", ["Barbell_Squat", "unknown"], shots)
    # 3 examples + the real note; the field list in the instructions names "triage_level" once more
    assert p.count("Note:") == 4 and p.count('"triage_level"') == 1 + 3
    assert label_json(shots[0]["labels"]) in p


def test_few_shot_refuses_non_train_examples() -> None:
    with pytest.raises(ValueError):
        pick_fewshot([item("green", pool="dev")], per_class=1)


def test_parse_valid_output_with_noise() -> None:
    raw = "<think>hmm</think>\nSure! " + label_json(LABELS) + "\nHope this helps {really}"
    labels, err = parse_output(raw)
    assert err is None and labels == LABELS


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("no json here", "no_json"),
        ('{"exercise_id": "Barbell_Squat", ', "no_json"),
        ("{not json}", "invalid_json"),
        ('{"exercise_id": "Barbell_Squat"}', "schema_error"),
    ],
)
def test_parse_errors(raw: str, code: str) -> None:
    assert parse_output(raw) == (None, code)


def test_parse_rejects_id_outside_vocabulary() -> None:
    raw = label_json({**LABELS, "exercise_id": "Made_Up_Press"})
    assert parse_output(raw, exercise_ids=["Barbell_Squat", "unknown"]) == (None, "schema_error")


def _grams(text: str, n: int = 3) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def test_prompts_hold_no_plan_or_guideline_example() -> None:
    # plan 2.4 control 2; examples of plan 3.3 and of docs/labeling-guideline.md
    examples = ("my quads were dying", "this set killed me", "no pain at all today", "That set killed me.",
                "No pain today, just mild knee stiffness.", "My shoulder hurts badly.", "last rep was a grind")  # fmt: skip
    blocked = set().union(*(_grams(e) for e in examples))
    for path in PROMPTS_DIR.glob("*.txt"):
        assert not _grams(path.read_text(encoding="utf-8")) & blocked, path.name


def test_placeholders_inside_a_note_are_not_expanded() -> None:
    p = build_prompt("weird {examples} {exercise_ids} note", "zero_shot", ["Barbell_Squat"])
    assert "weird {examples} {exercise_ids} note" in p and p.count("Barbell_Squat") == 1


def test_prompt_agrees_with_the_failed_set_labels() -> None:
    for path in PROMPTS_DIR.glob("extraction_v0_*shot.txt"):
        assert "0 reps" not in path.read_text(encoding="utf-8")  # no count in the text means null
