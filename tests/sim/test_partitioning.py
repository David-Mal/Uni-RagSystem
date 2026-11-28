from dataclasses import replace

import pytest

from src.datagen.partition import PoolError
from src.sim.partitioning import select_development_inputs


def test_seeds_ids_and_provenance_are_actually_partitioned(development_partition):
    p = development_partition
    selected = select_development_inputs(p, seed=398, scenario_template_ids=["st_dev_unit"] * 3)
    assert [v.seed for v in selected] == [398, 399, 100]  # Inclusive dev range wraps without leaving its pool.
    assert selected == select_development_inputs(p, seed=398, scenario_template_ids=["st_dev_unit"] * 3)
    for item in selected:
        item.validate(p)
        assert item.to_dict(p)["pool"] == "dev"
        assert item.to_dict(p)["generator_model"] == "deterministic-code/no-LLM"
        assert item.to_dict(p)["phrasing_family_ids"] == ()


@pytest.mark.parametrize("changes", (
    {"seed": 0}, {"seed": 1000}, {"seed": True}, {"seed": "100"},
    {"persona_ids": ["ps_tr_unit"]}, {"persona_ids": ["ps_dev_missing"]},
    {"scenario_template_ids": ["st_dev_missing"]}, {"consumer": "tier2_notes"},
    {"consumer": "messages"}, {"phrasing_family_ids": ["pf_dev_missing"]},
    {"consumer": "extractor", "phrasing_family_ids": ["pf_dev_classifier"]},
    {"phrasing_family_ids": ["pf_dev_extractor"]},
))
def test_wrong_pool_unknown_ids_and_consumers_rejected(development_partition, changes):
    kwargs = {"seed": 100, "scenario_template_ids": ["st_dev_unit"]}
    kwargs.update(changes)
    with pytest.raises((PoolError, ValueError)):
        select_development_inputs(development_partition, **kwargs)


def test_public_consumer_selection_is_deterministic_metadata_only(development_partition):
    selected = select_development_inputs(development_partition, seed=100,
                                         scenario_template_ids=["st_dev_unit"], consumer="extractor")
    assert selected[0].phrasing_family_ids == ("pf_dev_extractor",)
    assert "description" not in selected[0].to_dict(development_partition)
    with pytest.raises(PoolError, match="development"):
        replace(selected[0], pool="golden").validate(development_partition)
    with pytest.raises(PoolError, match="distinct"):
        select_development_inputs(development_partition, seed=100, scenario_template_ids=["st_dev_unit"] * 301)
