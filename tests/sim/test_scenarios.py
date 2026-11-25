from dataclasses import replace
from pathlib import Path

import pytest

from src.sim.injections import MissingRPE, MixedUnits, RisingRPE, flat_sets
from src.sim.params import LifterParams
from src.sim.plans import allocate_development_cases, planned_coverage
from src.sim.quotas import QuotaRequirements, count_quotas, quota_shortfalls
from src.sim.scenarios import SimulationFamily, generate_development_batch, injected_coverage, simulate_family
from src.sim.workouts import SimulationDesign


def test_150_actual_development_scenarios_and_all_coverage(simulation_families: tuple[SimulationFamily, ...], tmp_path: Path) -> None:
    batch = generate_development_batch(simulation_families, n=150, seed=37)
    assert len(batch.scenarios) == 150
    assert all(item.log.sessions and flat_sets(item.log) for item in batch.scenarios)
    assert not quota_shortfalls(batch.planned, QuotaRequirements())
    assert not quota_shortfalls(batch.injected, QuotaRequirements())
    assert min(batch.injected.by_hypothesis.values()) >= 20
    assert batch.injected.abstention >= 30
    assert batch.injected.confounders >= 20 and batch.injected.numeric_traps >= 20
    assert batch.injected.clusters == 7
    assert len({item.scenario_id for item in batch.scenarios}) == 150
    assert all(item.expected_annotations is None and len(item.pending_decisions) == 3 for item in batch.scenarios)
    assert all(observation.present for item in batch.scenarios for observation in item.observations)
    # This is internal development data, not an OpenGym or held-out file.
    output = tmp_path / "development-batch.json"
    output.write_bytes(batch.to_json_bytes())
    assert output.read_bytes() == generate_development_batch(simulation_families, n=150, seed=37).to_json_bytes()
    with pytest.raises(TypeError):
        count_quotas(batch.scenarios)


def test_cluster_ids_group_parameter_families(simulation_families: tuple[SimulationFamily, ...]) -> None:
    family = simulation_families[1]
    first = simulate_family(family, seed=1, scenario_id="unit-case-a")
    second = simulate_family(family, seed=2, scenario_id="unit-case-b")
    assert first.cluster_id == second.cluster_id == family.family_id
    assert first.scenario_id != second.scenario_id


def test_final_data_recheck_detects_erased_rpe_pattern(simulation_params: LifterParams, design: SimulationDesign) -> None:
    family = SimulationFamily("unit-conflict", simulation_params, design, (RisingRPE(6, 0.1), MissingRPE(1)))
    scenario = simulate_family(family, seed=3, scenario_id="unit-case")
    assert not scenario.observations[0].present
    assert scenario.observations[0].facts["fixed_load"] is True
    assert scenario.observations[1].present
    assert "fatigue_accumulation" not in scenario.injected_causes
    coverage = injected_coverage((scenario,))
    assert coverage.by_hypothesis["fatigue_accumulation"] == 0


def test_planned_coverage_cannot_substitute_for_actual_injection(simulation_params: LifterParams, design: SimulationDesign) -> None:
    # Flipping every set's unit leaves a single unit, so no mixed-unit trap exists.
    family = SimulationFamily("unit-unrealized", simulation_params, design, (MixedUnits(1),))
    required = QuotaRequirements(total=1, per_hypothesis=0, abstention=0, confounders=0, numeric_traps=1)
    plans = allocate_development_cases([family.planning_family()], n=1, seed=1, requirements=required)
    assert planned_coverage(plans).numeric_traps == 1
    with pytest.raises(ValueError, match="injected development coverage"):
        generate_development_batch([family], n=1, seed=1, requirements=required)


def test_infeasible_and_invalid_plans(simulation_families: tuple[SimulationFamily, ...]) -> None:
    families = [item.planning_family() for item in simulation_families]
    with pytest.raises(ValueError, match="cannot cover"):
        allocate_development_cases(families[:1], n=150, seed=1)
    with pytest.raises(ValueError, match="below"):
        allocate_development_cases(families, n=149, seed=1)
    with pytest.raises(ValueError, match="unique"):
        allocate_development_cases([families[0], families[0]], n=150, seed=1)
    with pytest.raises(ValueError):
        generate_development_batch([], n=150, seed=1)


def test_scenario_metadata_is_immutable_and_decisions_are_not_fabricated(simulation_families: tuple[SimulationFamily, ...]) -> None:
    scenario = simulate_family(simulation_families[0], seed=1, scenario_id="unit-case")
    snapshot = scenario.to_json_bytes()
    with pytest.raises(TypeError):
        scenario.injected_parameters["lifter"]["noise"] = 99
    with pytest.raises(TypeError):
        scenario.observations[0].facts["after_sets"] = 0
    detached = scenario.to_dict()
    detached["injected_parameters"]["lifter"]["noise"] = 999
    assert scenario.to_json_bytes() == snapshot
    assert scenario.to_dict()["expected_annotations"] is None
    assert scenario.to_dict()["pending_decisions"] == ("evidence_levels", "abstention_outcome", "gate_outcome")
    with pytest.raises(ValueError):
        replace(scenario, annotation_specification="unsupported reference alone")
