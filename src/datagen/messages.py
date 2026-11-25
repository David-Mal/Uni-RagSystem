"""Template-based generator of synthetic training/dev messages for the extractor and triage (issue F3).

Every item records its pool, persona, phrasing family, seed and generator (plan §2.4). The generator refuses any
seed, persona or phrasing family outside the requested pool, and it always refuses the golden pool. Labels are correct
by construction: the slots are sampled first, then the text is rendered from them, and ``ExtractionResult``
validates the labels.

CLI (until P1 merges, point ``--manifest`` at a manifest with the same shape, e.g. the test stub)::

    python -m src.datagen.messages --manifest data/manifests/partition.yaml --pool train \
        --per-class 100 --base-seed 1 --out data/training/sample.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.datagen import vocab
from src.datagen.families import FAMILIES, PhrasingFamily, Slots
from src.datagen.registry import PoolError, PoolRegistry
from src.schemas import (
    SCHEMA_VERSION,
    UNKNOWN_EXERCISE_ID,
    ExtractionResult,
    KinematicObservation,
    Load,
    Outcome,
    TriageLevel,
)

GENERATOR_NAME = "template"
GENERATOR_VERSION = "v0"
GENERATOR = f"{GENERATOR_NAME}-{GENERATOR_VERSION}"
ALLOWED_POOLS = ("train", "dev")
CONSUMERS = ("extractor", "classifier")

# Sampling probabilities (documented in docs/datagen-messages.md)
P_UNKNOWN_EXERCISE = 0.10  # half unresolvable phrase, half no exercise mentioned
P_LOAD = 0.85
P_LB = 0.25
P_REPS = 0.85
P_RPE = 0.45
P_OUTCOME = {Outcome.COMPLETED: 0.80, Outcome.PARTIAL: 0.10, Outcome.FAILED: 0.10}
P_KINEMATIC_NONE = 0.55
P_RED_SYSTEMIC = 0.30
P_RED_DISTRACTOR = 0.15  # red items whose real red symptom follows a negated or figurative clause
P_HARD_NEGATIVE = {TriageLevel.GREEN: 0.25, TriageLevel.YELLOW: 0.15, TriageLevel.RED: 0.0}
GENERIC_BODY_PARTS = ("knee", "shoulder", "lower back", "elbow", "hip", "wrist")


class Paraphraser(Protocol):
    """Optional rewrite step (e.g. an open-weight LLM). Must keep every number, unit and symptom intact.

    ``name`` is recorded on each item (model id and version). Prompts must never contain golden or guideline examples.
    """

    name: str

    def paraphrase(self, text: str, *, seed: int) -> str: ...


@dataclass(frozen=True)
class GeneratorConfig:
    """What to generate: pool, per-class counts and the first seed (seeds are consecutive)."""

    pool: str
    per_class: Mapping[TriageLevel, int]
    base_seed: int


def persona_strength(persona_id: str) -> float:
    """Deterministic load multiplier in [0.6, 1.3] derived from the persona id (personas carry no numeric fields)."""
    h = int(hashlib.sha256(persona_id.encode("utf-8")).hexdigest()[:8], 16)
    return 0.6 + 0.7 * (h / 0xFFFFFFFF)


def _round_load(kg: float, unit: str) -> Load:
    if unit == "kg":
        return Load(value=max(2.5, round(kg / 2.5) * 2.5), unit="kg")
    return Load(value=max(5.0, round(kg * 2.20462 / 5) * 5), unit="lb")


def _weighted(rng: random.Random, weights: Mapping[Any, float]) -> Any:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def _families_for(pool: str, registry: PoolRegistry, hard_negative: bool, consumer: str) -> list[PhrasingFamily]:
    """Families of ``consumer`` that the manifest puts in ``pool``. Never returns a golden-pool family."""
    out = []
    for fam in FAMILIES.values():
        if fam.consumer != consumer or (fam.hard_negative is not None) != hard_negative:
            continue
        try:
            actual = registry.pool_of("phrasing_families", fam.family_id)
        except PoolError:
            continue
        if actual == "golden":
            raise PoolError(f"phrasing family {fam.family_id!r} is in the golden pool; generator refuses")
        if actual == pool:
            out.append(fam)
    return out


def _symptom(
    level: TriageLevel,
    part: str,
    hn_kind: str | None,
    rng: random.Random,
    clauses: vocab.ClauseVocab,
    reps_word: str | None,
    allow_positive: bool,
) -> str:
    """Sample the triage-bearing clause from the pool's own vocabulary.

    ``hn_kind`` is the family's hard-negative kind (``figurative``, ``negated``, ``mixed``) or ``None``.
    ``reps_word`` is the labeled completed rep count as a word, or ``None``: templates that mention a rep number are
    only used when it is set, so the text never invents a number. ``allow_positive`` is false for failed or partial
    sets and for sets with a kinematic observation, where "moved well" or "felt strong" would contradict the text.
    """
    kind = rng.choice(("figurative", "negated")) if hn_kind == "mixed" else hn_kind

    def pick(options: tuple[str, ...]) -> str:
        usable = [o for o in options if reps_word is not None or "{reps_word}" not in o]
        return rng.choice(usable).format(part=part, reps_word=reps_word or "")

    if level is TriageLevel.GREEN:
        if kind == "figurative":
            return pick(clauses.figurative)
        if kind == "negated":
            return pick(clauses.negated)
        if kind == "soreness":
            return pick(clauses.soreness_ok)
        if kind == "past_pain":
            return pick(clauses.past_pain_resolved)
        return pick(clauses.green_positive) if allow_positive else ""
    if level is TriageLevel.YELLOW:
        if kind == "negated":
            return pick(clauses.negated_red_plus_mild)
        if kind == "figurative":
            return f"{pick(clauses.figurative)}, and {pick(clauses.yellow)}"
        if kind == "soreness":
            return f"{pick(clauses.soreness_ok)}, but also {pick(clauses.yellow)}"
        if kind == "past_pain":
            return f"{pick(clauses.past_pain_resolved)}, but now {pick(clauses.yellow)}"
        return pick(clauses.yellow)
    red = pick(clauses.red_systemic) if rng.random() < P_RED_SYSTEMIC else pick(clauses.red)
    if rng.random() < P_RED_DISTRACTOR:
        return f"{pick(clauses.red_distractor)}, but {red}"
    return red


def generate_item(
    level: TriageLevel,
    seed: int,
    pool: str,
    registry: PoolRegistry,
    paraphraser: Paraphraser | None = None,
    consumer: str = "extractor",
) -> dict[str, Any]:
    """Generate one item deterministically from ``seed``. Raises ``PoolError`` on any pool violation.

    ``consumer`` selects the family set, as in the P1 manifest: ``extractor`` (default) or ``classifier`` (F8).
    """
    if pool not in ALLOWED_POOLS:
        raise PoolError(f"generator only writes pools {ALLOWED_POOLS}, got {pool!r}")
    if consumer not in CONSUMERS:
        raise ValueError(f"consumer must be one of {CONSUMERS}, got {consumer!r}")
    registry.assert_in_pool(pool, seed=seed)
    key = f"{GENERATOR}|{seed}|{level.value}"
    if consumer != "extractor":  # the extractor stream stays unchanged so its pinned items hold
        key = f"{GENERATOR}|{consumer}|{seed}|{level.value}"
    rng = random.Random(key)

    hard_negative = rng.random() < P_HARD_NEGATIVE[level]
    families = _families_for(pool, registry, hard_negative, consumer)
    if not families:
        kind = "hard-negative" if hard_negative else "regular"
        raise PoolError(f"no {kind} phrasing family of this generator is in the {pool!r} pool of the manifest")
    family = rng.choice(families)
    hn_kind = family.hard_negative
    personas = registry.members("personas", pool)
    if not personas:
        raise PoolError(f"no persona in the {pool!r} pool")
    persona_id = rng.choice(personas)
    registry.assert_in_pool(pool, personas=persona_id, phrasing_families=family.family_id)

    # --- exercise
    ex_text: str | None
    roll = rng.random()
    if roll < P_UNKNOWN_EXERCISE / 2:
        ex, ex_text, exercise_id = None, rng.choice(vocab.UNRESOLVABLE_EXERCISE_PHRASES), UNKNOWN_EXERCISE_ID
    elif roll < P_UNKNOWN_EXERCISE:
        ex, ex_text, exercise_id = None, None, UNKNOWN_EXERCISE_ID
    else:
        ex = rng.choice(vocab.EXERCISES)
        ex_text, exercise_id = rng.choice(ex.aliases), ex.exercise_id

    # --- numbers
    load: Load | None = None
    if ex is not None and ex.load_kg != (0, 0) and rng.random() < P_LOAD:
        lo, hi = ex.load_kg
        kg = rng.uniform(lo, hi) * persona_strength(persona_id)
        load = _round_load(kg, "lb" if rng.random() < P_LB else "kg")
    clauses = vocab.CLAUSES[pool]
    outcome: Outcome = _weighted(rng, P_OUTCOME)
    reps: int | None = None
    outcome_phrase = ""
    if outcome is Outcome.FAILED:
        # No count is written for a failed attempt, so reps stays null (a missing number is not zero).
        outcome_phrase = rng.choice(clauses.outcome[Outcome.FAILED])
    elif outcome is Outcome.PARTIAL:
        reps = rng.randint(1, 8)
        planned = reps + rng.randint(1, 3)
        outcome_phrase = rng.choice(clauses.outcome[Outcome.PARTIAL]).format(reps=reps, planned=planned)
    elif rng.random() < P_REPS:
        reps = rng.randint(1, 12)
    rpe = rng.choice([6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10]) if rng.random() < P_RPE else None
    if outcome is Outcome.FAILED and rpe is not None:
        rpe = 10  # a failed attempt can only be reported as RPE 10

    # --- kinematic + triage clauses
    if rng.random() < P_KINEMATIC_NONE:
        kin = KinematicObservation.NONE
    else:
        options = [k for k in KinematicObservation if k is not KinematicObservation.NONE]
        if outcome is Outcome.FAILED:  # a grind implies the rep went up, which contradicts a failed attempt
            options.remove(KinematicObservation.GRINDING_REP)
        kin = rng.choice(options)
    kin_phrase = rng.choice(clauses.kinematic[kin])
    part = rng.choice(vocab.SIDES) + rng.choice(ex.body_parts if ex else GENERIC_BODY_PARTS)
    reps_word = vocab.NUMBER_WORDS.get(reps) if outcome is Outcome.COMPLETED and reps else None
    allow_positive = outcome is Outcome.COMPLETED and kin is KinematicObservation.NONE
    symptom = _symptom(level, part, hn_kind, rng, clauses, reps_word, allow_positive)

    slots = Slots(
        exercise=ex_text,
        load=load,
        reps=reps,
        rpe=rpe,
        outcome=outcome,
        outcome_phrase=outcome_phrase,
        kinematic=kin_phrase,
        symptom=symptom,
        extra="",
        level=level.value,
        part=part,
    )
    text = family.render(slots, rng).strip()
    paraphraser_name = None
    if paraphraser is not None:
        text = paraphraser.paraphrase(text, seed=seed)
        paraphraser_name = paraphraser.name

    labels = ExtractionResult(
        exercise_id=exercise_id,
        kinematic_observation=kin,
        load=load,
        reps=reps,
        outcome=outcome,
        rpe=rpe,
        triage_level=level,
    )
    return {
        "item_id": f"tm-{pool}-{seed:06d}",
        "text": text,
        "labels": labels.model_dump(mode="json"),
        "pool": pool,
        "persona_id": persona_id,
        "phrasing_family": family.family_id,
        "hard_negative": hn_kind,
        "seed": seed,
        "generator": GENERATOR,
        "generator_model": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "paraphraser": paraphraser_name,
        "schema_version": SCHEMA_VERSION,
    }


def generate(
    config: GeneratorConfig, registry: PoolRegistry, paraphraser: Paraphraser | None = None
) -> Iterator[dict[str, Any]]:
    """Yield ``per_class[level]`` items per level with consecutive seeds starting at ``base_seed``."""
    seed = config.base_seed
    for level in vocab.TRIAGE_ORDER:
        for _ in range(config.per_class.get(level, 0)):
            yield generate_item(level, seed, config.pool, registry, paraphraser)
            seed += 1


def write_jsonl(items: Iterator[dict[str, Any]] | list[dict[str, Any]], out: Path) -> int:
    """Write items as UTF-8 JSONL with LF line endings; return the count.

    The golden check runs before any directory is created. Items go to a temporary file that replaces ``out`` only
    after every item was written, so an error mid-run leaves the previous file untouched.
    """
    if "golden" in {part.lower() for part in out.resolve().parts}:
        raise PoolError("refusing to write generated data into data/golden/")
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
    n = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for item in items:
                fh.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
                n += 1
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return n


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate synthetic training/dev messages (template-v0).")
    parser.add_argument("--manifest", type=Path, required=True, help="partition manifest YAML (P1)")
    parser.add_argument("--pool", choices=ALLOWED_POOLS, default="train")
    parser.add_argument("--per-class", type=int, default=100)
    parser.add_argument("--base-seed", type=int, help="first seed (default: start of the pool's seed range)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    registry = PoolRegistry.load(args.manifest)
    base = args.base_seed if args.base_seed is not None else registry.seed_range(args.pool)[0]
    config = GeneratorConfig(
        pool=args.pool, per_class=dict.fromkeys(vocab.TRIAGE_ORDER, args.per_class), base_seed=base
    )
    n = write_jsonl(generate(config, registry), args.out)
    print(f"wrote {n} items to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
