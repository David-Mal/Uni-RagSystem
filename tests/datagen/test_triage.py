"""Tests for triage-classifier data (issue F8). Stub manifest only."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.datagen.build_training import normalize_text
from src.datagen.families import FAMILIES
from src.datagen.messages import GeneratorConfig, generate
from src.datagen.registry import PoolRegistry
from src.datagen.triage import ID2LABEL, LABEL2ID, build_triage
from src.schemas import TriageLevel

STUB = Path(__file__).resolve().parents[1] / "data" / "datagen" / "partition_stub.yaml"
TRIAGE_FAMILIES = {f.family_id for f in FAMILIES.values() if f.consumer == "classifier"}
EXTRACTOR_FAMILIES = {f.family_id for f in FAMILIES.values() if f.consumer == "extractor"}


@pytest.fixture(scope="module")
def built() -> tuple[list[dict], list[dict], dict]:
    return build_triage(PoolRegistry.load(STUB), n_train=150, n_dev=60)


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
    assert not {it["phrasing_family"] for it in generate(cfg, PoolRegistry.load(STUB))} & TRIAGE_FAMILIES


def test_seeds_do_not_overlap_extractor_seed_block(built: tuple) -> None:
    _, _, seeds = built
    assert seeds["triage_train"][0] == 5001  # train range starts at 1 in the stub
    assert seeds["triage_dev"][0] == 20500


def test_texts_unique_across_splits_and_hard_negatives_present(built: tuple) -> None:
    train, dev, _ = built
    texts = [normalize_text(it["text"]) for it in train + dev]
    assert len(texts) == len(set(texts))
    assert any(it["hard_negative"] for it in train)
    assert all(it["label"] != "red" for it in train + dev if it["hard_negative"])


def test_every_manifest_classifier_family_is_used() -> None:
    reg = PoolRegistry.load(STUB)
    train, dev, _ = build_triage(reg, n_train=900, n_dev=300)
    assert {it["phrasing_family"] for it in train} == set(reg.members("phrasing_families", "train")) & TRIAGE_FAMILIES
    assert {it["phrasing_family"] for it in dev} == set(reg.members("phrasing_families", "dev")) & TRIAGE_FAMILIES
    assert {it["hard_negative"] for it in train} >= {"mixed", "soreness"}  # family kind, as for the extractor
    assert "past_pain" in {it["hard_negative"] for it in dev}


def test_checklist_and_detail_state_severity_consistently() -> None:
    train, _, _ = build_triage(PoolRegistry.load(STUB), n_train=900, n_dev=30)
    severity = {"green": "none", "yellow": "mild", "red": "serious"}
    for it in train:
        if it["phrasing_family"] == "pf_tr_cls_checklist":
            assert f"any symptoms: {'no' if it['label'] == 'green' else 'yes'}" in it["text"], it
            assert f"severity: {severity[it['label']]}" in it["text"], it
        if it["phrasing_family"] == "pf_tr_cls_symptom_detail":
            assert f"Intensity: {severity[it['label']]}." in it["text"], it


def test_soreness_and_past_pain_hard_negatives_are_never_red(built: tuple) -> None:
    train, dev, _ = built
    for it in train + dev:
        if it["hard_negative"] in ("soreness", "past_pain"):
            assert it["label"] in ("green", "yellow"), it
