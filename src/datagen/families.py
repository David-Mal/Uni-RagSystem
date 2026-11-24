"""Phrasing families for the training/dev message generator (issue F3).

A phrasing family is a whole writing style (plan §2.4 control 3: split by family, not by item). Each family is a
render function from sampled slots to text. Family ids are proposals for the train/dev pools of the P1 manifest.
They must never appear in the golden pool, and the generator checks this against the manifest at run time.

Text rules every family follows, so labels stay correct by construction:
- a load is always written with its unit; reps, RPE and the exercise are written only when the label has them;
- partial and failed outcomes are always stated explicitly;
- symptom, figurative and negation clauses come only from ``vocab`` and are chosen by the generator, not here.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from src.schemas import Load, Outcome

EMOJI: tuple[str, ...] = ("😅", "😩", "💪", "🙃", "👍", "😬")


@dataclass(frozen=True)
class Slots:
    """Content chosen by the generator. ``None``/empty means "not mentioned in the text"."""

    exercise: str | None
    load: Load | None
    reps: int | None
    rpe: float | None
    outcome: Outcome
    outcome_phrase: str
    kinematic: str
    symptom: str
    extra: str


Renderer = Callable[[Slots, random.Random], str]


@dataclass(frozen=True)
class PhrasingFamily:
    """A phrasing family: id, intended pool, style description and renderer."""

    family_id: str
    pool: str
    description: str
    render: Renderer
    hard_negative: str | None = None
    """``None`` for regular families, else the hard-negative kind: ``figurative``, ``negated`` or ``mixed``."""


# ---------------------------------------------------------------- formatting helpers


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def fmt_load(load: Load, style: str) -> str:
    """Render a load with its unit in one of several styles."""
    v = _num(load.value)
    if load.unit == "kg":
        return {"tight": f"{v}kg", "spaced": f"{v} kg", "word": f"{v} kilos", "formal": f"{v} kilograms"}[style]
    return {"tight": f"{v}lb", "spaced": f"{v} lbs", "word": f"{v} pounds", "formal": f"{v} pounds"}[style]


def fmt_rpe(rpe: float, style: str) -> str:
    """Render an RPE value (``@8``, ``RPE 8``, ``felt like an 8``...)."""
    v = _num(rpe)
    article = "an" if v.startswith("8") else "a"
    return {
        "at": f"@{v}",
        "upper": f"RPE {v}",
        "lower": f"rpe {v}",
        "felt": f"felt like {article} {v}",
        "formal": f"at an RPE of {v}",
    }[style]


def clauses(slots: Slots) -> list[str]:
    """Non-empty free clauses in a stable order: outcome, kinematic, symptom, extra."""
    return [c for c in (slots.outcome_phrase, slots.kinematic, slots.symptom, slots.extra) if c]


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _sentences(parts: list[str]) -> str:
    return " ".join(_cap(p.rstrip(".")) + "." for p in parts if p)


def _typos(text: str, rng: random.Random, rate: float = 0.15) -> str:
    """Swap or double letters inside a few alphabetic words longer than 3 chars; digits are never touched."""
    words = text.split(" ")
    for i, word in enumerate(words):
        if len(word) > 3 and word.isalpha() and rng.random() < rate:
            j = rng.randrange(1, len(word) - 1)
            words[i] = (
                word[:j] + word[j + 1] + word[j] + word[j + 2 :]
                if rng.random() < 0.6
                else word[:j] + word[j] + word[j:]
            )
    return " ".join(words)


def _ex(slots: Slots, fallback: str = "my sets") -> str:
    return slots.exercise or fallback


# ---------------------------------------------------------------- core renderers (train pool)


def _terse_log(s: Slots, rng: random.Random) -> str:
    core = [_ex(s, "sets")]
    if s.load:
        core.append(fmt_load(s.load, "tight"))
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        core.append(f"x{s.reps}")
    if s.rpe is not None:
        core.append(fmt_rpe(s.rpe, "at"))
    return ", ".join([" ".join(core), *clauses(s)])


def _formal_sentence(s: Slots, rng: random.Random) -> str:
    first = f"Today I performed {s.exercise}" if s.exercise else "Today I completed my working sets"
    if s.load:
        first += f" with {fmt_load(s.load, 'formal')}"
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        first += f" for {s.reps} repetitions"
    if s.rpe is not None:
        first += f" {fmt_rpe(s.rpe, 'formal')}"
    return _sentences([first, *clauses(s)])


def _abbrev_heavy(s: Slots, rng: random.Random) -> str:
    core = _ex(s, "sets")
    if s.load and s.reps is not None and s.outcome is Outcome.COMPLETED:
        core += f" {fmt_load(s.load, 'tight')} x{s.reps}"
    elif s.load:
        core += f" {fmt_load(s.load, 'tight')}"
    elif s.reps is not None and s.outcome is Outcome.COMPLETED:
        core += f" {s.reps}r"
    if s.rpe is not None:
        core += f" {fmt_rpe(s.rpe, 'at')}"
    rest = " / ".join(c.replace(" and ", " & ").replace(" with ", " w/ ") for c in clauses(s))
    return f"{core} / {rest}" if rest else core


def _emoji_typos(s: Slots, rng: random.Random) -> str:
    core = _ex(s, "workout")
    if s.load:
        core += f" {fmt_load(s.load, 'tight')}"
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        core += f" {s.reps} reps"
    if s.rpe is not None:
        core += f" {fmt_rpe(s.rpe, 'lower')}"
    text = " ".join([core, *clauses(s)])
    return f"{_typos(text.lower(), rng)} {rng.choice(EMOJI)}"


def _story_style(s: Slots, rng: random.Random) -> str:
    opener = rng.choice(
        (
            "Got to the gym a bit late today.",
            "Quick session after work.",
            "Long day but made it in.",
            "Morning session.",
        )
    )
    main = f"After warming up I went for {_ex(s, 'my main work')}"
    if s.load:
        main += f" at {fmt_load(s.load, 'spaced')}"
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        main += f" for {s.reps}"
    if s.rpe is not None:
        main += f", {fmt_rpe(s.rpe, 'felt')}"
    return f"{opener} {_sentences([main, *clauses(s)])}"


def _lowercase_runon(s: Slots, rng: random.Random) -> str:
    core = _ex(s, "did my sets")
    if s.load:
        core += f" {fmt_load(s.load, 'spaced')}"
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        core += f" for {s.reps}"
    if s.rpe is not None:
        core += f" at {_num(s.rpe)} rpe"
    return " ".join([core, *clauses(s)]).lower()


def _question_style(s: Slots, rng: random.Random) -> str:
    info = f"did {_ex(s, 'my usual sets')}"
    if s.load:
        info += f" {fmt_load(s.load, 'spaced')}"
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        info += f" {s.reps} reps"
    if s.rpe is not None:
        info += f" {fmt_rpe(s.rpe, 'upper')}"
    extra = clauses(s)
    question = rng.choice(("Is this normal?", "Should I be worried?", "Any thoughts?", "What do you think?"))
    return f"{_cap(info)}. {_sentences(extra)} {question}".replace("  ", " ").strip()


def _bullet_log(s: Slots, rng: random.Random) -> str:
    head = f"- {_cap(_ex(s, 'Session'))}"
    details = []
    if s.load:
        details.append(fmt_load(s.load, "spaced"))
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        details.append(f"{s.reps} reps")
    if s.rpe is not None:
        details.append(fmt_rpe(s.rpe, "upper"))
    if details:
        head += ": " + ", ".join(details)
    return "\n".join([head, *(f"- {c}" for c in clauses(s))])


def _numbers_first(s: Slots, rng: random.Random) -> str:
    parts = []
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        parts.append(f"{s.reps} reps")
    if s.load:
        parts.append(f"@ {fmt_load(s.load, 'tight')}" if parts else fmt_load(s.load, "tight"))
    if s.exercise:
        parts.append(f"on {s.exercise}" if parts else s.exercise)
    core = " ".join(parts) or "sets done"
    if s.rpe is not None:
        core += f", {fmt_rpe(s.rpe, 'lower')}"
    return ". ".join([core, *clauses(s)]) + "."


def _coach_report(s: Slots, rng: random.Random) -> str:
    fields = [f"exercise {s.exercise}" if s.exercise else "exercise not specified"]
    if s.load:
        fields.append(f"load {fmt_load(s.load, 'spaced')}")
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        fields.append(f"{s.reps} reps")
    if s.rpe is not None:
        fields.append(fmt_rpe(s.rpe, "upper"))
    notes = "; ".join(clauses(s))
    return f"Session note: {', '.join(fields)}." + (f" Comments: {notes}." if notes else "")


# ---------------------------------------------------------------- dev pool renderers (disjoint styles)


def _gym_chat(s: Slots, rng: random.Random) -> str:
    opener = rng.choice(("yo", "ok so", "update:", "hey"))
    core = f"hit {_ex(s, 'my stuff')}"
    if s.load:
        core += f" {fmt_load(s.load, 'word')}"
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        core += f" for {s.reps}"
    if s.rpe is not None:
        core += f" ({fmt_rpe(s.rpe, 'lower')})"
    return f"{opener} {core}" + "".join(f", {c}" for c in clauses(s))


def _caps_terse(s: Slots, rng: random.Random) -> str:
    core = _ex(s, "SETS").upper()
    if s.load:
        core += f" {fmt_load(s.load, 'tight').upper()}"
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        core += f" X{s.reps}"
    if s.rpe is not None:
        core += f" {fmt_rpe(s.rpe, 'at')}"
    return " - ".join([core, *(c.upper() for c in clauses(s))])


def _diary(s: Slots, rng: random.Random) -> str:
    day = rng.choice(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))
    main = f"Dear log, {day}: worked on {_ex(s, 'my program')}"
    if s.load:
        main += f", {fmt_load(s.load, 'spaced')}"
    if s.reps is not None and s.outcome is Outcome.COMPLETED:
        main += f", {s.reps} times"
    if s.rpe is not None:
        main += f", {fmt_rpe(s.rpe, 'felt')}"
    return _sentences([main, *clauses(s)])


# ---------------------------------------------------------------- registry of families

FAMILIES: dict[str, PhrasingFamily] = {
    f.family_id: f
    for f in (
        PhrasingFamily("pf_tr_terse_log", "train", "terse gym-log shorthand, comma separated", _terse_log),
        PhrasingFamily("pf_tr_formal_sentence", "train", "complete formal sentences", _formal_sentence),
        PhrasingFamily("pf_tr_abbrev_heavy", "train", "abbreviation-heavy, slash separated", _abbrev_heavy),
        PhrasingFamily("pf_tr_emoji_typos", "train", "lowercase with typos and a trailing emoji", _emoji_typos),
        PhrasingFamily("pf_tr_story_style", "train", "short story with an opener sentence", _story_style),
        PhrasingFamily("pf_tr_lowercase_runon", "train", "lowercase run-on, no punctuation", _lowercase_runon),
        PhrasingFamily("pf_tr_question_style", "train", "report followed by a question", _question_style),
        PhrasingFamily("pf_tr_bullet_log", "train", "markdown bullet list", _bullet_log),
        PhrasingFamily("pf_tr_numbers_first", "train", "numbers first, then exercise", _numbers_first),
        PhrasingFamily("pf_tr_coach_report", "train", "third-person structured session note", _coach_report),
        PhrasingFamily(
            "pf_tr_hn_figurative",
            "train",
            "hard negatives: hyperbole about effort",
            _terse_log,
            hard_negative="figurative",
        ),
        PhrasingFamily(
            "pf_tr_hn_negated",
            "train",
            "hard negatives: explicit negation of pain",
            _formal_sentence,
            hard_negative="negated",
        ),
        PhrasingFamily("pf_dev_gym_chat", "dev", "chatty gym-buddy message with an opener", _gym_chat),
        PhrasingFamily("pf_dev_caps_terse", "dev", "all caps, dash separated", _caps_terse),
        PhrasingFamily("pf_dev_diary", "dev", "diary entry with a weekday", _diary),
        PhrasingFamily(
            "pf_dev_hn_mixed",
            "dev",
            "hard negatives: figurative or negated, chat style",
            _gym_chat,
            hard_negative="mixed",
        ),
    )
}
