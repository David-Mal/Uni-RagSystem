"""Tests for the template message generator (issue F3). Uses the test stub manifest, never the golden data."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.datagen import vocab
from src.datagen.families import FAMILIES
from src.datagen.messages import GeneratorConfig, generate, generate_item, write_jsonl
from src.datagen.registry import PoolError, PoolRegistry
from src.schemas import ExtractionResult, Outcome, TriageLevel

REPO_ROOT = Path(__file__).resolve().parents[2]
STUB = REPO_ROOT / "tests" / "data" / "datagen" / "partition_stub.yaml"
FEDB = REPO_ROOT / "data" / "exercises" / "free-exercise-db.json"


@pytest.fixture(scope="module")
def registry() -> PoolRegistry:
    return PoolRegistry.load(STUB)


@pytest.fixture(scope="module")
def train_items(registry: PoolRegistry) -> list[dict]:
    cfg = GeneratorConfig(pool="train", per_class=dict.fromkeys(TriageLevel, 200), base_seed=1)
    return list(generate(cfg, registry))


TYPO_FAMILY = (
    "pf_tr_emoji_typos"  # typos are intentional there, so word-level checks skip it (digits are never touched)
)


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


# ---------------- determinism


def test_same_seed_same_item(registry: PoolRegistry) -> None:
    a = generate_item(TriageLevel.RED, 42, "train", registry)
    b = generate_item(TriageLevel.RED, 42, "train", registry)
    assert a == b


def test_same_config_same_file(registry: PoolRegistry, tmp_path: Path) -> None:
    cfg = GeneratorConfig(pool="train", per_class=dict.fromkeys(TriageLevel, 20), base_seed=500)
    write_jsonl(generate(cfg, registry), tmp_path / "a.jsonl")
    write_jsonl(generate(cfg, registry), tmp_path / "b.jsonl")
    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()


def test_different_seeds_differ(registry: PoolRegistry) -> None:
    texts = {generate_item(TriageLevel.GREEN, s, "train", registry)["text"] for s in range(1, 51)}
    assert len(texts) > 45


# ---------------- counts, schema, manifest fields


def test_counts_and_schema(train_items: list[dict]) -> None:
    assert len(train_items) == 600
    for level in TriageLevel:
        assert sum(it["labels"]["triage_level"] == level.value for it in train_items) == 200
    for it in train_items:
        ExtractionResult.model_validate(it["labels"])
        assert it["pool"] == "train"
        assert it["generator"] == "template-v0"
        assert it["paraphraser"] is None
        assert {"item_id", "persona_id", "phrasing_family", "seed", "generator_model", "generator_version"} <= it.keys()
    assert len({it["item_id"] for it in train_items}) == 600


def test_hard_negatives_only_from_their_own_families(train_items: list[dict]) -> None:
    hn = [it for it in train_items if it["hard_negative"]]
    assert hn, "hard negatives must be present in training data"
    assert {it["phrasing_family"] for it in hn} <= {"pf_tr_hn_figurative", "pf_tr_hn_negated"}
    assert all(it["labels"]["triage_level"] != "red" for it in hn)
    assert all(not it["hard_negative"] for it in train_items if "_hn_" not in it["phrasing_family"])


# ---------------- label correctness by construction (checked on every item)


def test_numbers_in_labels_appear_in_text(train_items: list[dict]) -> None:
    for it in train_items:
        text, lab = it["text"].lower(), it["labels"]
        if lab["load"]:
            value = _num(lab["load"]["value"])
            assert value in text, it
            unit_words = ("kg", "kilo") if lab["load"]["unit"] == "kg" else ("lb", "pound")
            assert any(u in text for u in unit_words), it
        if lab["rpe"] is not None:
            assert _num(lab["rpe"]) in text, it
        if lab["reps"] and lab["outcome"] in ("completed", "partial"):
            assert re.search(rf"(?<![\d.]){lab['reps']}(?!\d|\.\d)", text), it


def test_unit_never_written_without_load(train_items: list[dict]) -> None:
    for it in train_items:
        if it["labels"]["load"] is None:
            assert not re.search(r"\d\s?(kg|kilos|lbs?|pounds)\b", it["text"].lower()), it


def test_outcomes_are_stated(train_items: list[dict]) -> None:
    for it in train_items:
        if it["labels"]["outcome"] == "failed":
            assert it["labels"]["reps"] == 0
            assert it["labels"]["rpe"] in (None, 10)
            assert it["phrasing_family"] == TYPO_FAMILY or any(
                p.lower() in it["text"].lower() for p in vocab.OUTCOME_PHRASES[Outcome.FAILED]
            ), it


def test_green_regular_items_have_no_symptom_vocabulary(train_items: list[dict]) -> None:
    symptom_words = ("pain", "ache", "achy", "sore", "stiff", "twinge", "swell", "dizzy", "numb", "tight", "pop")
    for it in train_items:
        if it["labels"]["triage_level"] == "green" and not it["hard_negative"]:
            assert not any(w in it["text"].lower() for w in symptom_words), it


def test_red_items_carry_a_red_cue(train_items: list[dict]) -> None:
    cues = ("sharp", "stabbing", "swell", "pop", "snap", "numb", "dizzy", "fainted", "blacked out", "chest")
    for it in train_items:
        if it["labels"]["triage_level"] == "red" and it["phrasing_family"] != TYPO_FAMILY:
            assert any(c in it["text"].lower() for c in cues), it


def test_unknown_exercise_iff_no_known_alias(train_items: list[dict]) -> None:
    unknown = [it for it in train_items if it["labels"]["exercise_id"] == "unknown"]
    assert unknown, "unknown exercises must be represented"
    by_id = {e.exercise_id: e for e in vocab.EXERCISES}
    for it in train_items:
        ex_id = it["labels"]["exercise_id"]
        if ex_id != "unknown" and it["phrasing_family"] != TYPO_FAMILY:
            assert any(a.lower() in it["text"].lower() for a in by_id[ex_id].aliases), it


def test_hand_checked_examples(registry: PoolRegistry) -> None:
    # Pinned items, read and checked by hand. A change to vocab/families changes them: re-check by hand, then update.
    a = generate_item(TriageLevel.YELLOW, 7, "train", registry)
    # "managed 2 out of 3" -> partial with 2 completed reps; "bar speed was slow" -> slow_bar_speed;
    # soreness persisting for a week -> yellow (persistent soreness); no load or RPE written -> None.
    assert a["text"] == (
        "pull-ups. managed 2 out of 3. bar speed was slow. "
        "left shoulder still sore from last week, it hasn't gone away."
    )
    assert a["labels"] == {
        "exercise_id": "Pullups",
        "kinematic_observation": "slow_bar_speed",
        "load": None,
        "reps": 2,
        "outcome": "partial",
        "rpe": None,
        "triage_level": "yellow",
    }

    b = generate_item(TriageLevel.RED, 11, "train", registry)
    # 35 kg x 11 at RPE 9.5, completed; "setup felt different" -> other; "chest pain" -> red.
    assert b["text"] == (
        "Got to the gym a bit late today. After warming up I went for dumbbell bench at 35 kg for 11, "
        "felt like a 9.5. My setup felt different today. Chest pain during the last set."
    )
    assert b["labels"] == {
        "exercise_id": "Dumbbell_Bench_Press",
        "kinematic_observation": "other",
        "load": {"value": 35.0, "unit": "kg"},
        "reps": 11,
        "outcome": "completed",
        "rpe": 9.5,
        "triage_level": "red",
    }

    c = generate_item(TriageLevel.GREEN, 3, "train", registry)
    # No exercise named -> unknown; 3 reps; "moved slow" -> slow_bar_speed; no symptom -> green.
    assert c["text"] == "did my sets for 3 reps moved slow good energy today"
    assert c["labels"]["exercise_id"] == "unknown"
    assert c["labels"]["reps"] == 3
    assert c["labels"]["kinematic_observation"] == "slow_bar_speed"
    assert c["labels"]["triage_level"] == "green"


# ---------------- pool rules


def test_refuses_golden_pool(registry: PoolRegistry) -> None:
    with pytest.raises(PoolError):
        generate_item(TriageLevel.GREEN, 100_000, "golden", registry)


def test_refuses_seed_outside_pool(registry: PoolRegistry) -> None:
    with pytest.raises(PoolError):
        generate_item(TriageLevel.GREEN, 20_000, "train", registry)  # dev seed
    with pytest.raises(PoolError):
        generate_item(TriageLevel.GREEN, 100_500, "train", registry)  # golden seed


def test_refuses_family_moved_to_golden() -> None:
    data = {
        "seeds": {"train": [1, 10], "golden": [100, 110]},
        "personas": {"train": ["p1"]},
        "phrasing_families": {
            "train": [f for f in FAMILIES if f.startswith("pf_tr_") and f != "pf_tr_terse_log"],
            "golden": ["pf_tr_terse_log"],
        },
    }
    reg = PoolRegistry.from_manifest(data)
    with pytest.raises(PoolError, match="golden"):
        generate_item(TriageLevel.GREEN, 1, "train", reg)


def test_dev_pool_uses_only_dev_ids(registry: PoolRegistry) -> None:
    cfg = GeneratorConfig(pool="dev", per_class=dict.fromkeys(TriageLevel, 30), base_seed=20_000)
    items = list(generate(cfg, registry))
    assert {it["phrasing_family"] for it in items} <= set(registry.members("phrasing_families", "dev"))
    assert {it["persona_id"] for it in items} <= set(registry.members("personas", "dev"))


def test_no_family_of_this_generator_is_golden(registry: PoolRegistry) -> None:
    golden = set(registry.members("phrasing_families", "golden"))
    assert not golden & set(FAMILIES)
    for fam in FAMILIES.values():
        assert registry.pool_of("phrasing_families", fam.family_id) == fam.pool


def test_write_jsonl_refuses_golden_dir(tmp_path: Path) -> None:
    with pytest.raises(PoolError):
        write_jsonl([], tmp_path / "data" / "golden" / "x.jsonl")


def test_paraphraser_is_recorded(registry: PoolRegistry) -> None:
    class Upper:
        name = "fake-upper-v1"

        def paraphrase(self, text: str, *, seed: int) -> str:
            return text.upper()

    item = generate_item(TriageLevel.GREEN, 5, "train", registry, paraphraser=Upper())
    assert item["paraphraser"] == "fake-upper-v1"
    assert item["text"] == item["text"].upper()


# ---------------- registry


def test_registry_rejects_overlaps() -> None:
    with pytest.raises(PoolError):
        PoolRegistry.from_manifest({"seeds": {"train": [1, 100], "dev": [50, 150]}})
    with pytest.raises(PoolError):
        PoolRegistry.from_manifest({"seeds": {"train": [1, 2]}, "personas": {"train": ["a"], "golden": ["a"]}})


def test_registry_accepts_manifest_shapes() -> None:
    reg = PoolRegistry.from_manifest(
        {
            "seeds": {"train": "1-9", "dev": {"start": 10, "end": 19}},
            "personas": {"train": [{"id": "p1", "description": "beginner"}], "dev": {"p2": "returning lifter"}},
        }
    )
    assert reg.pool_of_seed(9) == "train" and reg.pool_of_seed(10) == "dev"
    assert reg.pool_of("personas", "p2") == "dev"


# ---------------- vocabulary


def test_vocab_exercise_ids_are_well_formed_and_unique() -> None:
    ids = [e.exercise_id for e in vocab.EXERCISES]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[A-Za-z0-9_\-]+", i) for i in ids)
    families = {e.family for e in vocab.EXERCISES}
    assert {"squat", "bench", "deadlift", "row", "overhead_press", "accessory"} == families


@pytest.mark.skipif(not FEDB.exists(), reason="free-exercise-db not vendored yet (D7)")
def test_vocab_exercise_ids_exist_in_free_exercise_db() -> None:
    known = {e["id"] for e in json.loads(FEDB.read_text(encoding="utf-8"))}
    assert {e.exercise_id for e in vocab.EXERCISES} <= known
