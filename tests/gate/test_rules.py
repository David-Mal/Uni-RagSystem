"""Deterministic rules of the safety gate (issue D9). All texts were written for this file."""

from __future__ import annotations

import re

import pytest
import yaml

from src.gate.rules import RULES_PATH, GateRules, assess_text
from src.schemas import TriageLevel

RED = [
    "Sharp pain in my left knee on rep 3",
    "the pain was really sharp",
    "stabbing feeling under the shoulder blade",
    "a shooting pain down the leg",
    "Knee is swollen after squats",
    "some SWELLING around the ankle",
    "got dizzy after the last set",
    "felt light-headed, sat down",
    "almost fainted on deadlifts",
    "nearly passed out",
    "chest pain during warm up",
    "pain in the middle of my chest",
    "my chest felt very tight on the stairs",
    "tightness in my chest",
    "fingers went numb",
    "numbness in the left hand",
    "tingling down my arm",
    "pain radiating to the elbow",
    "heard a pop and then it started to hurt",
    "felt something snap in the hamstring. Immediate pain.",
    "it hurts really bad",
    "Elbow hurts badly",
    "no pain in the squat but sharp pain on deadlift",
    "something cracked in my wrist and now it aches",
    "shoulder really hurts",
    "the room was spinning after the set",
    "vision went dark for a second",
    "No pain at first, then my knee was swollen",
    "pain’s intense today",
]

YELLOW = [
    "mild discomfort in the right shoulder",
    "left elbow a bit achy",
    "slight ache in the hip",
    "lower back stiff this morning",
    "stiffness in the neck",
    "hamstring tightness",
    "still sore from last week",
    "sore for four days now",
    "soreness persists",
    "felt a twinge in the groin",
    "shoulder pain on the way down",
    "knee hurts a little",
    "tweaked my back",
    "not pain free today",
    "wasn't pain-free",
    "no pain until the last set",
    "didn't hurt until rep 8",
    "no sharp pain, just a dull ache",
    "painful lockout",
    "knee is a bit sore",
    "elbow tender to touch",
    "nothing hurts until I go heavy",
    "no pain meds today, shoulder aches",
]

GREEN = [
    "",
    "Easy session, moved well",
    "my quads were dying",
    "this set killed me",
    "dead legs after the run",
    "legs were dead",
    "no pain at all today",
    "no knee pain, felt strong",
    "Completely pain free",
    "pain-free squats",
    "shoulder didn't hurt",
    "the knee doesn’t hurt anymore",
    "no pain or swelling",
    "no pain, dizziness or numbness",
    "without any discomfort",
    "no chest pain",
    "nothing hurt today",
    "not a hint of pain in the knee",
    "quads are very sore from squats",
    "no pain no gain",
    "rest periods were painfully long",
    "stayed tight off the chest",
    "kept everything tight",
    "tight form on all reps",
    "a bit sore from yesterday's legs",
    "popped a new PR",
    "great pump in the chest",
    "bench press, chest up",
    "sharp looking new belt",
]


@pytest.mark.parametrize("text", RED)
def test_red(text: str) -> None:
    result = assess_text(text)
    assert result.level is TriageLevel.RED, result
    assert any(p.startswith("red:") for p in result.matched_patterns)


@pytest.mark.parametrize("text", YELLOW)
def test_yellow(text: str) -> None:
    result = assess_text(text)
    assert result.level is TriageLevel.YELLOW, result
    assert result.matched_patterns


@pytest.mark.parametrize("text", GREEN)
def test_green_and_hard_negatives(text: str) -> None:
    result = assess_text(text)
    assert result.level is TriageLevel.GREEN, result
    assert result.matched_patterns == []


@pytest.mark.parametrize("phrase", ["my quads were dying", "this set killed me", "no pain in the squat"])
def test_a_harmless_phrase_never_hides_a_symptom(phrase: str) -> None:
    for symptom in ("sharp pain in the knee", "dizzy", "swollen ankle", "chest pain"):
        assert assess_text(f"{phrase}, {symptom}").level is TriageLevel.RED
        assert assess_text(f"{symptom}. {phrase}").level is TriageLevel.RED


def test_every_listed_red_symptom_of_the_issue_is_covered() -> None:
    for text in ("sharp pain", "stabbing", "swelling", "dizziness", "faint", "chest pain", "chest tightness", "numbness",
                 "tingling radiating", "pop with pain", "snap with pain"):  # fmt: skip
        assert assess_text(text).level is TriageLevel.RED, text


def test_every_listed_yellow_symptom_of_the_issue_is_covered() -> None:
    for text in ("mild discomfort", "ache", "achy", "stiffness", "tightness", "soreness that persists", "twinge"):
        assert assess_text(text).level is TriageLevel.YELLOW, text


def test_line_breaks_and_case_do_not_matter() -> None:
    assert assess_text("ALL GOOD\nCHEST PAIN").level is TriageLevel.RED
    assert assess_text("no pain\n\n  Dizzy").level is TriageLevel.RED


def test_real_notes_from_the_exports_are_green() -> None:
    for note in ("Both sets 12 w 50 lat pulldowns", "Cable high row is lbs nu kg"):
        assert assess_text(note).level is TriageLevel.GREEN


def test_long_text_is_handled_quickly() -> None:
    assert assess_text("pain " * 2000).level is TriageLevel.YELLOW
    assert assess_text("chest up and tight core " * 1000) is not None


def test_broken_configs_are_rejected() -> None:
    cfg = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    for change in ({"red": {}}, {"yellow": {}}):
        with pytest.raises(ValueError, match="empty"):
            GateRules.from_config(cfg | change)
    with pytest.raises(KeyError):
        GateRules.from_config({k: v for k, v in cfg.items() if k != "red"})
    with pytest.raises(KeyError):
        GateRules.from_config(cfg | {"red": {"x": "<nope>"}})
    with pytest.raises(re.error):
        GateRules.from_config(cfg | {"red": {"x": "("}})
