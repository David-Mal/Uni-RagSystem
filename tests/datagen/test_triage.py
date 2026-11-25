"""Tests for triage-classifier data (issue F8). Real manifest."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.datagen import vocab
from src.datagen.build_training import iter_jsonl, normalize_text, read_drop_ids
from src.datagen.families import FAMILIES
from src.datagen.messages import GeneratorConfig, generate
from src.datagen.partition import load_partition
from src.datagen.triage import ID2LABEL, LABEL2ID, build_triage
from src.schemas import TriageLevel

REPO_ROOT = Path(__file__).resolve().parents[2]
TRIAGE_FAMILIES = {f.family_id for f in FAMILIES.values() if f.consumer == "classifier"}
EXTRACTOR_FAMILIES = {f.family_id for f in FAMILIES.values() if f.consumer == "extractor"}


@pytest.fixture(scope="module")
def built() -> tuple[list[dict], list[dict], dict]:
    return build_triage(load_partition(), n_train=150, n_dev=60)


def test_label_mapping_is_fixed() -> None:
    assert LABEL2ID == {"green": 0, "yellow": 1, "red": 2}
    assert ID2LABEL[2] == "red"


def test_items_are_text_label_and_manifest_fields(built: tuple) -> None:
    train, dev, _ = built
    assert len(train) == 150 and len(dev) == 60
    for it in train + dev:
        assert "labels" not in it  # text + label only
        assert it["label_id"] == LABEL2ID[it["label"]]
        assert it["item_id"].startswith("tc-") and it["task"] == "triage"
        assert {"pool", "persona_id", "phrasing_family", "seed", "generator"} <= it.keys()
    assert {it["pool"] for it in train} == {"train"} and {it["pool"] for it in dev} == {"dev"}


def test_classifier_families_are_disjoint_from_extractor_families(built: tuple) -> None:
    train, dev, _ = built
    assert TRIAGE_FAMILIES and not TRIAGE_FAMILIES & EXTRACTOR_FAMILIES
    assert {it["phrasing_family"] for it in train + dev} <= TRIAGE_FAMILIES


def test_extractor_generation_never_uses_classifier_families() -> None:
    cfg = GeneratorConfig(pool="train", per_class=dict.fromkeys(TriageLevel, 100), base_seed=1)
    assert not {it["phrasing_family"] for it in generate(cfg, load_partition())} & TRIAGE_FAMILIES


def test_seeds_do_not_overlap_extractor_seed_block(built: tuple) -> None:
    _, _, seeds = built
    assert seeds["triage_train"][0] == 5001  # train range starts at 1
    assert seeds["triage_dev"][0] == 20500


def test_texts_unique_across_splits_and_hard_negatives_present(built: tuple) -> None:
    train, dev, _ = built
    texts = [normalize_text(it["text"]) for it in train + dev]
    assert len(texts) == len(set(texts))
    assert any(it["hard_negative"] for it in train)


def test_every_manifest_classifier_family_is_used() -> None:
    reg = load_partition()
    train, dev, _ = build_triage(reg, n_train=900, n_dev=300)
    assert {it["phrasing_family"] for it in train} == set(reg.members("phrasing_families", "train")) & TRIAGE_FAMILIES
    assert {it["phrasing_family"] for it in dev} == set(reg.members("phrasing_families", "dev")) & TRIAGE_FAMILIES
    assert {it["hard_negative"] for it in train} >= {"mixed", "soreness"}  # family kind, as for the extractor
    assert "past_pain" in {it["hard_negative"] for it in dev}


def test_checklist_and_detail_state_severity_consistently() -> None:
    train, _, _ = build_triage(load_partition(), n_train=900, n_dev=30)
    severity = {"green": "none", "yellow": "mild", "red": "serious"}
    for it in train:
        if it["phrasing_family"] == "pf_tr_cls_checklist":
            assert f"any symptoms: {'no' if it['label'] == 'green' else 'yes'}" in it["text"], it
            assert f"severity: {severity[it['label']]}" in it["text"], it
        if it["phrasing_family"] == "pf_tr_cls_symptom_detail":
            assert f"Intensity: {severity[it['label']]}." in it["text"], it


def test_every_style_contains_every_class() -> None:
    train, dev, _ = build_triage(load_partition(), n_train=1500, n_dev=300)
    for items in (train, dev):
        seen: dict[str, set[str]] = {}
        for it in items:
            seen.setdefault(it["phrasing_family"], set()).add(it["label"])
        assert all(labels == {"green", "yellow", "red"} for labels in seen.values()), seen


def test_soreness_and_past_pain_turn_red_only_with_a_real_red_symptom() -> None:
    train, dev, _ = build_triage(load_partition(), n_train=1500, n_dev=300)
    cues = [c for p in ("train", "dev") for c in (*vocab.CLAUSES[p].red, *vocab.CLAUSES[p].red_systemic)]
    heads = [c.split("{part}")[0].strip().lower() for c in cues if c.split("{part}")[0].strip()]
    tails = [c.split("{part}")[-1].strip().lower() for c in cues if "{part}" in c]
    red = [it for it in train + dev if it["hard_negative"] in ("soreness", "past_pain") and it["label"] == "red"]
    assert red
    for it in red:
        text = it["text"].lower()
        assert ", but " in text and any(x and x in text for x in (*heads, *tails)), it


def test_committed_files_are_what_the_builder_makes() -> None:
    drop = read_drop_ids(REPO_ROOT / "data" / "manifests" / "drop_ids.txt")
    train, dev, _ = build_triage(load_partition(), n_train=1500, n_dev=300, drop_ids=drop)
    for name, items in (("triage_train", train), ("triage_dev", dev)):
        assert list(iter_jsonl(REPO_ROOT / "data" / "training" / f"{name}.jsonl")) == items
