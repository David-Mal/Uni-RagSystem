"""Tests for the partition manifest loader (issue P1). The real manifest is data/manifests/partition.yaml."""

from __future__ import annotations

import copy
import re
from itertools import combinations
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.datagen.partition import ID_SECTIONS, Partition, PoolError, PoolRegistry, assert_pool, load_partition

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "data" / "manifests" / "partition.yaml"

F3_TRAIN = [
    "pf_tr_terse_log", "pf_tr_formal_sentence", "pf_tr_abbrev_heavy", "pf_tr_emoji_typos", "pf_tr_story_style",
    "pf_tr_lowercase_runon", "pf_tr_question_style", "pf_tr_bullet_log", "pf_tr_numbers_first", "pf_tr_coach_report",
    "pf_tr_hn_figurative", "pf_tr_hn_negated",
]  # fmt: skip
F3_DEV = ["pf_dev_gym_chat", "pf_dev_caps_terse", "pf_dev_diary", "pf_dev_hn_mixed"]
F8_TRAIN = ["pf_tr_cls_short_note", "pf_tr_cls_coach_checkin", "pf_tr_cls_set_comment", "pf_tr_cls_hn_effort"]
F8_DEV = ["pf_dev_cls_voice_memo", "pf_dev_cls_hn_memo"]
CATEGORIES = {
    "insufficient_weekly_volume", "fatigue_accumulation", "stagnant_load_progression", "load_spike",
    "inconsistent_frequency", "logging_quality_issue", "confounder_present", "abstention", "numeric_trap",
}  # fmt: skip
OPAQUE = {
    "personas": "golden persona {n}",
    "phrasing_families": "golden phrasing family {n}",
    "scenario_templates": "golden scenario template {n}",
}
PREFIX = {"personas": "ps", "phrasing_families": "pf", "scenario_templates": "st"}


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def part() -> Partition:
    return load_partition()


def mutated(raw: dict[str, Any], fn) -> dict[str, Any]:
    data = copy.deepcopy(raw)
    fn(data)
    return data


# ---- the real manifest ----


def test_real_manifest_loads(part: Partition) -> None:
    assert part.manifest_version == "v1"
    assert part.exercise_families == ["squat", "bench", "deadlift", "row", "overhead_press", "accessories"]


def test_seed_ranges_match_d9(part: Partition) -> None:
    assert part.seed_range("train") == (1, 9999)
    assert part.seed_range("dev") == (20000, 20999)
    assert part.seed_range("golden") == (100000, 100999)
    assert part.pool_of_seed(1) == "train"
    assert part.pool_of_seed(9999) == "train"
    assert part.pool_of_seed(20000) == "dev"
    assert part.pool_of_seed(100999) == "golden"
    for outside in (0, 10000, 19999, 21000, 99999, 101000):
        with pytest.raises(PoolError):
            part.pool_of_seed(outside)


def test_pools_are_disjoint(part: Partition) -> None:
    for section in ID_SECTIONS:
        pools = {p: set(part.members(section, p)) for p in ("train", "dev", "golden")}
        for a, b in combinations(pools, 2):
            assert not pools[a] & pools[b], (section, a, b)
    lo_hi = sorted(part.seeds.values())
    assert all(a[1] < b[0] for a, b in zip(lo_hi, lo_hi[1:], strict=False))


def test_every_id_is_unique_across_the_manifest(part: Partition) -> None:
    ids = [i for s in ID_SECTIONS for p in ("train", "dev", "golden") for i in part.members(s, p)]
    assert len(ids) == len(set(ids))


def test_minimum_quantities(part: Partition) -> None:
    n = {s: {p: len(part.members(s, p)) for p in ("train", "dev", "golden")} for s in ID_SECTIONS}
    assert n["personas"]["train"] >= 12 and n["personas"]["dev"] >= 4 and n["personas"]["golden"] >= 6
    fam = n["phrasing_families"]
    assert fam["train"] >= 20 and fam["dev"] >= 4 and fam["golden"] >= 8
    tpl = n["scenario_templates"]
    assert tpl["train"] >= 9 and tpl["dev"] >= 9 and tpl["golden"] >= 18


def test_consumer_split(part: Partition) -> None:
    def count(pool: str, consumer: str) -> int:
        return sum(f.consumer == consumer for f in part.phrasing_families[pool])  # type: ignore[index]

    assert count("train", "extractor") >= 12 and count("train", "classifier") >= 10
    assert count("dev", "extractor") >= 4 and count("dev", "classifier") >= 4
    assert count("golden", "messages") >= 8 and count("golden", "tier2_notes") >= 4
    assert all(f.consumer in {"messages", "tier2_notes"} for f in part.phrasing_families["golden"])
    assert all(f.consumer in {"extractor", "classifier"} for p in ("train", "dev") for f in part.phrasing_families[p])


def test_train_and_dev_templates_cover_every_category(part: Partition) -> None:
    for pool in ("train", "dev"):
        assert {t.category for t in part.scenario_templates[pool]} == CATEGORIES  # type: ignore[index]


def test_f3_family_ids_are_in_the_right_pools(part: Partition) -> None:
    assert len(F3_TRAIN) == 12 and len(F3_DEV) == 4
    assert set(F3_TRAIN) <= set(part.members("phrasing_families", "train"))
    assert set(F3_DEV) <= set(part.members("phrasing_families", "dev"))
    part.assert_pool(F3_TRAIN, "train")
    part.assert_pool(F3_DEV, "dev")
    by_id = {f.id: f for p in ("train", "dev") for f in part.phrasing_families[p]}  # type: ignore[index]
    assert all(by_id[i].consumer == "extractor" for i in F3_TRAIN + F3_DEV)


def test_f8_family_ids_are_classifier_families_in_the_right_pools(part: Partition) -> None:
    part.assert_pool(F8_TRAIN, "train")
    part.assert_pool(F8_DEV, "dev")
    by_id = {f.id: f for p in ("train", "dev") for f in part.phrasing_families[p]}  # type: ignore[index]
    assert all(by_id[i].consumer == "classifier" for i in F8_TRAIN + F8_DEV)


def test_golden_entries_are_opaque(raw: dict[str, Any]) -> None:
    for section, template in OPAQUE.items():
        for entry in raw[section]["golden"]:
            match = re.fullmatch(rf"{PREFIX[section]}_gd_(\d{{2}})", entry["id"])
            assert match, entry
            assert entry["description"] == template.format(n=int(match[1]))
            allowed = {"id", "description"} | ({"consumer"} if section == "phrasing_families" else set())
            assert set(entry) == allowed, entry


# ---- loader validation ----


def test_overlapping_seed_ranges_fail(raw: dict[str, Any]) -> None:
    with pytest.raises(PoolError, match="overlap"):
        Partition.from_mapping(mutated(raw, lambda d: d["seeds"].update(dev=[9999, 20999])))


def test_empty_seed_range_fails(raw: dict[str, Any]) -> None:
    with pytest.raises(PoolError, match="empty"):
        Partition.from_mapping(mutated(raw, lambda d: d["seeds"].update(dev=[21000, 20000])))


def test_id_in_two_pools_fails(raw: dict[str, Any]) -> None:
    with pytest.raises(PoolError, match="twice"):
        Partition.from_mapping(
            mutated(raw, lambda d: d["personas"]["dev"].append(dict(d["personas"]["train"][0])))
        )


def test_id_in_two_sections_fails(raw: dict[str, Any]) -> None:
    def dup(d: dict[str, Any]) -> None:
        d["scenario_templates"]["train"].append({"id": "ps_tr_novice_linear", "category": "abstention", "description": "x"})

    with pytest.raises(PoolError, match="twice"):
        Partition.from_mapping(mutated(raw, dup))


def test_id_with_wrong_pool_prefix_fails(raw: dict[str, Any]) -> None:
    def move(d: dict[str, Any]) -> None:
        d["personas"]["train"].append({"id": "ps_gd_99", "description": "golden persona 99"})

    with pytest.raises(PoolError, match="must start with"):
        Partition.from_mapping(mutated(raw, move))


def test_illegal_consumer_fails(raw: dict[str, Any]) -> None:
    with pytest.raises(PoolError):
        Partition.from_mapping(mutated(raw, lambda d: d["phrasing_families"]["train"][0].update(consumer="messages")))
    with pytest.raises(PoolError):
        Partition.from_mapping(mutated(raw, lambda d: d["phrasing_families"]["golden"][0].update(consumer="extractor")))
    with pytest.raises(PoolError):
        Partition.from_mapping(mutated(raw, lambda d: d["phrasing_families"]["train"][0].update(consumer="nope")))


def test_illegal_pool_fails(raw: dict[str, Any]) -> None:
    with pytest.raises(PoolError):
        Partition.from_mapping(mutated(raw, lambda d: d["personas"].update(test=[])))


@pytest.mark.parametrize("pool", ["train", "dev", "golden"])
@pytest.mark.parametrize("section", ["seeds", *ID_SECTIONS])
def test_missing_pool_fails(raw: dict[str, Any], section: str, pool: str) -> None:
    with pytest.raises(PoolError, match=f"{section}: missing pool '{pool}'"):
        Partition.from_mapping(mutated(raw, lambda d: d[section].pop(pool)))


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ("  dev: [20000, 20999]\n", "  dev: [20000, 20999]\n  dev: [30000, 30999]\n", "dev"),
        ("id: ps_gd_01,", "id: st_gd_01, id: ps_gd_01,", "id"),
        ("exercise_families:", "manifest_version: v1\nexercise_families:", "manifest_version"),
        # a bad merge that would leave one train persona
        (
            "  dev:\n    - {id: ps_dev_shift_worker",
            "  train:\n    - {id: ps_tr_x, description: x}\n  dev:\n    - {id: ps_dev_shift_worker",
            "train",
        ),
    ],
)
def test_duplicate_yaml_key_fails(tmp_path: Path, old: str, new: str, key: str) -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path = tmp_path / "partition.yaml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(PoolError, match=f"duplicate key '{key}'"):
        load_partition(path)


@pytest.mark.parametrize("load", [load_partition, PoolRegistry.load])
def test_load_reads_the_given_path(raw: dict[str, Any], tmp_path: Path, load) -> None:
    path = tmp_path / "other.yaml"
    data = mutated(raw, lambda d: d["seeds"].update(train=[1, 50]))
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert load(path).seed_range("train") == (1, 50)
    assert load(str(path)).seed_range("train") == (1, 50)


def test_malformed_yaml_fails(tmp_path: Path) -> None:
    path = tmp_path / "partition.yaml"
    path.write_text("seeds: {train: [1, 2", encoding="utf-8")
    with pytest.raises(PoolError, match="cannot parse"):
        load_partition(path)


def test_golden_category_is_rejected(raw: dict[str, Any]) -> None:
    with pytest.raises(PoolError):
        Partition.from_mapping(mutated(raw, lambda d: d["scenario_templates"]["golden"][0].update(category="abstention")))


# ---- assert_pool and registry-compatible queries ----


def test_assert_pool_accepts_right_pool(part: Partition) -> None:
    ids = ["ps_tr_novice_linear", "pf_tr_terse_log", "st_tr_too_few_sessions"]
    part.assert_pool(ids, "train")
    assert_pool("pf_gd_01", "golden")
    assert_pool(["ps_dev_shift_worker", "st_dev_irregular_cadence"], "dev")


def test_assert_pool_rejects_unknown_and_wrong_pool(part: Partition) -> None:
    with pytest.raises(PoolError, match="not in the manifest"):
        assert_pool(["ps_tr_novice_linear", "ps_tr_does_not_exist"], "train")
    with pytest.raises(PoolError, match="belongs to pool 'golden'"):
        assert_pool(["pf_tr_terse_log", "pf_gd_01"], "train")
    with pytest.raises(PoolError, match="belongs to pool 'train'"):
        assert_pool("ps_tr_novice_linear", "dev")
    with pytest.raises(PoolError):
        assert_pool("pf_tr_terse_log", "validation")
    with pytest.raises(PoolError, match="not in the manifest"):
        assert_pool("squat", "train")  # exercise families are not pooled


def test_poolerror_is_a_valueerror() -> None:
    assert issubclass(PoolError, ValueError)


def test_pool_registry_constructors(raw: dict[str, Any], part: Partition) -> None:
    assert PoolRegistry.load(MANIFEST) == part
    assert PoolRegistry.from_manifest(raw) == part
    with pytest.raises(PoolError):
        PoolRegistry.from_manifest({"seeds": {"train": [1, 2]}})


def test_registry_compatible_queries(part: Partition) -> None:
    assert part.pool_of("phrasing_families", "pf_dev_gym_chat") == "dev"
    assert part.members("personas", "golden") == [f"ps_gd_0{i}" for i in range(1, 7)]
    part.assert_in_pool("train", seed=7, personas="ps_tr_novice_linear", phrasing_families=["pf_tr_terse_log"])
    with pytest.raises(PoolError):
        part.assert_in_pool("train", seed=20000)
    with pytest.raises(PoolError):
        part.assert_in_pool("train", phrasing_families=["pf_gd_01"])
    with pytest.raises(PoolError):
        part.pool_of("personas", "pf_tr_terse_log")  # right id, wrong section
    with pytest.raises(PoolError):
        part.members("exercise_families", "train")
