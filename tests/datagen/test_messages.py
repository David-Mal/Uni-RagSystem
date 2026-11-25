"""Tests for the template message generator (issue F3) on the real manifest. Never reads golden data."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from src.datagen import vocab
from src.datagen.families import FAMILIES
from src.datagen.messages import GeneratorConfig, generate, generate_item, write_jsonl
from src.datagen.partition import DEFAULT_PATH, Partition, PoolError, load_partition
from src.schemas import ExtractionResult, Outcome, TriageLevel

REPO_ROOT = Path(__file__).resolve().parents[2]
FEDB = REPO_ROOT / "data" / "exercises" / "free-exercise-db.json"


@pytest.fixture(scope="module")
def registry() -> Partition:
    return load_partition()


@pytest.fixture(scope="module")
def train_items(registry: Partition) -> list[dict]:
    cfg = GeneratorConfig(pool="train", per_class=dict.fromkeys(TriageLevel, 200), base_seed=1)
    return list(generate(cfg, registry))


TYPO_FAMILY = (
    "pf_tr_emoji_typos"  # typos are intentional there, so word-level checks skip it (digits are never touched)
)


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


# ---------------- determinism


def test_same_seed_same_item(registry: Partition) -> None:
    a = generate_item(TriageLevel.RED, 42, "train", registry)
    b = generate_item(TriageLevel.RED, 42, "train", registry)
    assert a == b


def test_same_config_same_file(registry: Partition, tmp_path: Path) -> None:
    cfg = GeneratorConfig(pool="train", per_class=dict.fromkeys(TriageLevel, 20), base_seed=500)
    write_jsonl(generate(cfg, registry), tmp_path / "a.jsonl")
    write_jsonl(generate(cfg, registry), tmp_path / "b.jsonl")
    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()


def test_different_seeds_differ(registry: Partition) -> None:
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
            assert it["labels"]["reps"] is None  # no count is written, and a missing number is not zero
            assert it["labels"]["rpe"] in (None, 10)
            assert it["labels"]["kinematic_observation"] != "grinding_rep"
            assert it["phrasing_family"] == TYPO_FAMILY or any(
                p.lower() in it["text"].lower() for p in vocab.CLAUSES["train"].outcome[Outcome.FAILED]
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


def test_hand_checked_examples(registry: Partition) -> None:
    # Pinned items, read and checked by hand. A change to vocab/families changes them: re-check by hand, then update.
    a = generate_item(TriageLevel.YELLOW, 3, "train", registry)
    # "mild discomfort" -> yellow; bodyweight exercise, so no load; 8 reps and RPE 9.5 as written.
    assert a["text"] == "- Tricep dips: 8 reps, RPE 9.5\n- some mild discomfort around the shoulder"
    assert a["labels"] == {
        "exercise_id": "Dips_-_Triceps_Version",
        "kinematic_observation": "none",
        "load": None,
        "reps": 8,
        "outcome": "completed",
        "rpe": 9.5,
        "triage_level": "yellow",
    }

    b = generate_item(TriageLevel.RED, 12, "train", registry)
    # A negated mild symptom before a real red symptom (dizzy) is red, in the negated hard-negative style. Failed lift:
    # no rep count in the text, so reps is null; RPE 10 as written.
    assert b["phrasing_family"] == "pf_tr_hn_negated" and b["hard_negative"] == "negated"
    assert b["text"] == (
        "Status: couldn't lock it out; no soreness this time, but got really dizzy after the set. (pull ups, RPE 10)"
    )
    assert b["labels"] == {
        "exercise_id": "Pullups",
        "kinematic_observation": "none",
        "load": None,
        "reps": None,
        "outcome": "failed",
        "rpe": 10.0,
        "triage_level": "red",
    }

    c = generate_item(TriageLevel.GREEN, 2, "train", registry)
    # Hard negative (negated pain) in the same "Status:" style -> green; numbers in brackets are labeled.
    assert c["phrasing_family"] == "pf_tr_hn_negated" and c["hard_negative"] == "negated"
    assert c["text"] == "Status: left knee felt fine, zero pain. (hack squat, 85 kg, 6 reps, RPE 8)"
    assert c["labels"] == {
        "exercise_id": "Hack_Squat",
        "kinematic_observation": "none",
        "load": {"value": 85.0, "unit": "kg"},
        "reps": 6,
        "outcome": "completed",
        "rpe": 8.0,
        "triage_level": "green",
    }


# ---------------- pool rules


def test_refuses_golden_pool(registry: Partition) -> None:
    with pytest.raises(PoolError):
        generate_item(TriageLevel.GREEN, 100_000, "golden", registry)


def test_refuses_seed_outside_pool(registry: Partition) -> None:
    with pytest.raises(PoolError):
        generate_item(TriageLevel.GREEN, 20_000, "train", registry)  # dev seed
    with pytest.raises(PoolError):
        generate_item(TriageLevel.GREEN, 100_500, "train", registry)  # golden seed


def _manifest() -> dict:
    return yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))


def test_refuses_family_moved_to_golden() -> None:
    data = _manifest()
    families = data["phrasing_families"]
    moved = families["train"].pop(0)
    families["golden"].append({**moved, "consumer": "messages"})
    with pytest.raises(PoolError):  # the manifest itself is invalid: golden ids have their own prefix
        Partition.from_mapping(data)


def test_families_of_another_consumer_are_not_used() -> None:
    data = _manifest()
    for fam in data["phrasing_families"]["train"]:
        if fam["id"] == "pf_tr_terse_log":
            fam["consumer"] = "classifier"
    reg = Partition.from_mapping(data)
    cfg = GeneratorConfig(pool="train", per_class=dict.fromkeys(TriageLevel, 100), base_seed=1)
    used = {it["phrasing_family"] for it in generate(cfg, reg)}
    assert "pf_tr_terse_log" not in used and not any("_cls_" in f for f in used)


def test_every_extractor_family_of_the_manifest_is_rendered(registry: Partition) -> None:
    wanted = {f.id for p in ("train", "dev") for f in registry.phrasing_families[p] if f.consumer == "extractor"}
    assert wanted == {f.family_id for f in FAMILIES.values() if f.consumer == "extractor"}


def test_dev_pool_uses_only_dev_ids(registry: Partition) -> None:
    cfg = GeneratorConfig(pool="dev", per_class=dict.fromkeys(TriageLevel, 30), base_seed=20_000)
    items = list(generate(cfg, registry))
    assert {it["phrasing_family"] for it in items} <= set(registry.members("phrasing_families", "dev"))
    assert {it["persona_id"] for it in items} <= set(registry.members("personas", "dev"))


def test_no_family_of_this_generator_is_golden(registry: Partition) -> None:
    golden = set(registry.members("phrasing_families", "golden"))
    assert not golden & set(FAMILIES)
    for fam in FAMILIES.values():
        assert registry.pool_of("phrasing_families", fam.family_id) == fam.pool


def test_write_jsonl_refuses_golden_dir(tmp_path: Path) -> None:
    with pytest.raises(PoolError):
        write_jsonl([], tmp_path / "data" / "golden" / "x.jsonl")


def test_paraphraser_is_recorded(registry: Partition) -> None:
    class Upper:
        name = "fake-upper-v1"

        def paraphrase(self, text: str, *, seed: int) -> str:
            return text.upper()

    item = generate_item(TriageLevel.GREEN, 5, "train", registry, paraphraser=Upper())
    assert item["paraphraser"] == "fake-upper-v1"
    assert item["text"] == item["text"].upper()


# ---------------- vocabulary


def test_vocab_exercise_ids_are_well_formed_and_unique() -> None:
    ids = [e.exercise_id for e in vocab.EXERCISES]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[A-Za-z0-9_\-]+", i) for i in ids)
    families = {e.family for e in vocab.EXERCISES}
    assert {"squat", "bench", "deadlift", "row", "overhead_press", "accessories"} == families


@pytest.mark.skipif(not FEDB.exists(), reason="free-exercise-db not vendored yet (D7)")
def test_vocab_exercise_ids_exist_in_free_exercise_db() -> None:
    known = {e["id"] for e in json.loads(FEDB.read_text(encoding="utf-8"))}
    assert {e.exercise_id for e in vocab.EXERCISES} <= known


# ---------------- review #71: held-out dev vocabulary, plan/guideline phrases, contradictions


def _clause_phrases(cv: vocab.ClauseVocab) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    names = ("yellow", "red", "red_systemic", "green_positive", "figurative", "negated", "negated_red_plus_mild")
    for name in (*names, "soreness_ok", "past_pain_resolved"):
        out[name] = {x for x in getattr(cv, name) if x}
    out["red_distractor"] = set(cv.red_distractor)
    out["kinematic"] = {x for xs in cv.kinematic.values() for x in xs if x}
    out["outcome"] = {x for xs in cv.outcome.values() for x in xs if x}
    return out


def test_train_and_dev_clause_vocabularies_are_disjoint() -> None:
    train, dev = _clause_phrases(vocab.CLAUSES["train"]), _clause_phrases(vocab.CLAUSES["dev"])
    all_train = set().union(*train.values())
    for name, phrases in dev.items():
        assert phrases, f"dev has no {name} phrases"
        assert not phrases & all_train, f"dev {name} phrases also used in train: {phrases & all_train}"


# Examples from the plan (§3.3) and the labeling guideline (Fi1, #74). Kept here only as a blocklist for this check;
# no training text may reuse their wording (plan §2.4 control 2).
PLAN_AND_GUIDELINE_EXAMPLES = (
    "my quads were dying",
    "this set killed me",
    "no pain at all today",
    "Bench 80 kg x 5 @8, last rep was a grind. Left shoulder a bit achy since Tuesday.",
    "That set killed me.",
    "No pain today, just mild knee stiffness.",
    "My shoulder hurt last month; it is fine now.",
    "Rows felt normal; my knee was stiff during squats.",
    "My shoulder hurts badly.",
    "bnch: sharp shoulder pain.",
    "Squats were fine; pressing caused sharp shoulder pain.",
    "Rows felt smooth and symptom-free.",
)


def _grams(text: str, n: int = 3) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def test_no_clause_reuses_plan_or_guideline_wording() -> None:
    blocked = set().union(*(_grams(x) for x in PLAN_AND_GUIDELINE_EXAMPLES))
    for pool, cv in vocab.CLAUSES.items():
        for name, phrases in _clause_phrases(cv).items():
            for phrase in phrases:
                text = phrase.replace("{part}", "knee").replace("{reps_word}", "three")
                assert not _grams(text) & blocked, f"{pool}/{name}: {phrase!r} reuses {_grams(text) & blocked}"


def test_dev_items_use_only_dev_clauses(registry: Partition) -> None:
    cfg = GeneratorConfig(pool="dev", per_class=dict.fromkeys(TriageLevel, 60), base_seed=20_000)
    train_clauses = set().union(*_clause_phrases(vocab.CLAUSES["train"]).values())
    templated = [c for c in train_clauses if "{" in c]
    plain = [c for c in train_clauses if "{" not in c]
    for it in generate(cfg, registry):
        text = it["text"].lower()
        assert not any(c.lower() in text for c in plain), it
        for c in templated:  # e.g. "sharp pain in my {part}" -> regex
            pattern = re.escape(c.lower()).replace(r"\{part\}", r"[a-z ]+").replace(r"\{reps_word\}", r"[a-z]+")
            assert not re.search(pattern, text), it


def test_red_items_include_negated_or_figurative_distractors(train_items: list[dict]) -> None:
    red = [it for it in train_items if it["labels"]["triage_level"] == "red"]
    mixed = [it for it in red if it["hard_negative"]]
    assert len(mixed) >= 0.05 * len(red), f"{len(mixed)} of {len(red)} red items have a distractor clause"
    assert all(", but " in it["text"].lower() for it in mixed)


@pytest.mark.parametrize(("pool", "base"), [("train", 1), ("dev", 20_000)])
def test_the_style_does_not_give_the_label_away(registry: Partition, pool: str, base: int) -> None:
    per_class = dict.fromkeys(TriageLevel, 300)
    seen: dict[str, set[str]] = {}
    for it in generate(GeneratorConfig(pool=pool, per_class=per_class, base_seed=base), registry):
        seen.setdefault(it["phrasing_family"], set()).add(it["labels"]["triage_level"])
    assert all(levels == {"green", "yellow", "red"} for levels in seen.values()), seen


def test_regular_styles_have_no_negated_or_figurative_red(train_items: list[dict]) -> None:
    clauses = vocab.CLAUSES["train"]
    for it in train_items:
        if it["labels"]["triage_level"] == "red" and not it["hard_negative"]:
            assert not any(c.lower() in it["text"].lower() for c in clauses.red_distractor), it


def test_failed_sets_mention_no_completed_reps(registry: Partition) -> None:
    for pool, base in (("train", 1), ("dev", 20_000)):
        phrases = [p for ps in vocab.CLAUSES[pool].kinematic.values() for p in ps if p]
        bad = [p for p in phrases if re.search(r"\b(final|last|reps?|couple|end)\b", p) or "grind" in p or "fight" in p]
        assert bad
        cfg = GeneratorConfig(pool=pool, per_class=dict.fromkeys(TriageLevel, 300), base_seed=base)
        for it in generate(cfg, registry):
            if it["labels"]["outcome"] == "failed":
                assert not any(p in it["text"].lower() for p in bad), it


def test_rep_number_words_match_the_label(train_items: list[dict]) -> None:
    words = {w: n for n, w in vocab.NUMBER_WORDS.items()}
    for it in train_items:
        m = re.search(r"dying by rep ([a-z]+)", it["text"].lower())
        if m:
            assert it["labels"]["outcome"] == "completed" and it["labels"]["reps"] == words[m.group(1)], it


def test_no_contradictory_clauses(train_items: list[dict]) -> None:
    positives = [p for p in vocab.CLAUSES["train"].green_positive if p]
    for it in train_items:
        lab, text = it["labels"], it["text"].lower()
        if lab["outcome"] != "completed" or lab["kinematic_observation"] != "none":
            assert not any(re.search(rf"\b{re.escape(p)}\b", text) for p in positives), it
        assert not ("completed my working sets" in text and lab["outcome"] == "failed"), it


def test_hard_negative_families_have_their_own_renderers() -> None:
    regular = {f.render for f in FAMILIES.values() if f.hard_negative is None}
    for fam in FAMILIES.values():
        if fam.hard_negative is not None:
            assert fam.render not in regular, fam.family_id


def test_missing_hard_negative_families_raise() -> None:
    data = _manifest()
    train = data["phrasing_families"]["train"]
    data["phrasing_families"]["train"] = [f for f in train if "_hn_" not in f["id"]]
    reg = Partition.from_mapping(data)
    with pytest.raises(PoolError, match="hard-negative"):
        cfg = GeneratorConfig(pool="train", per_class={TriageLevel.GREEN: 200}, base_seed=1)
        list(generate(cfg, reg))


def test_write_jsonl_creates_no_golden_dir_and_keeps_old_file_on_error(tmp_path: Path) -> None:
    with pytest.raises(PoolError):
        write_jsonl([], tmp_path / "data" / "golden" / "x.jsonl")
    assert not (tmp_path / "data").exists()

    out = tmp_path / "out.jsonl"
    out.write_text("previous\n", encoding="utf-8")

    def broken():
        yield {"a": 1}
        raise RuntimeError("generator failed mid-run")

    with pytest.raises(RuntimeError):
        write_jsonl(broken(), out)
    assert out.read_text(encoding="utf-8") == "previous\n"
    assert [p.name for p in tmp_path.iterdir()] == ["out.jsonl"]  # no leftover temp file
