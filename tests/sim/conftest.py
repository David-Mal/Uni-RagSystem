"""Isolated development inputs; no actual note wording or manifest entries."""

from typing import Callable
from datetime import datetime, timedelta

import pytest

from src.sim.params import LifterParams
from src.sim.schema import GroundTruth
from src.sim.workouts import ExerciseSpec, NoteTemplateRef, SimulationDesign
from src.sim.injections import (
    ConfounderNotes, DuplicateSets, FewSessions, LoadSpike, MissingRPE, MixedUnits,
    Outlier, ReduceSets, RisingRPE, SessionGap, SessionRange, ShortHistory, StagnantLoads,
)
from src.sim.scenarios import SimulationFamily


@pytest.fixture
def params() -> LifterParams:
    # Arbitrary unit-test inputs, not proposed project defaults or a lifter model.
    return LifterParams(2, 83.5, -0.02, 0.3, "kg", "sometimes", 2.0)


@pytest.fixture
def annotation() -> Callable[..., GroundTruth]:
    def make(**changes: object) -> GroundTruth:
        # Explicit test annotations exercise the schema/counter only. There is
        # no workout behind them and no inferred evidence or detectability claim.
        values: dict[str, object] = {
            "scenario_id": "unit-item",
            "expected_hypotheses": (),
            "abstain": False,
            "abstention_reasons": (),
            "gate_outcome": "green",
            "injected_parameters": {"unit_parameter": 2},
            "cluster_id": "unit-family",
            "has_confounder": False,
            "has_numeric_trap": False,
        }
        values.update(changes)
        return GroundTruth(**values)

    return make


@pytest.fixture
def simulation_params() -> LifterParams:
    # Explicit, arbitrary development design. These are not project defaults.
    return LifterParams(2, 100, 2, 0, "kg", "always", 0)


@pytest.fixture
def design() -> SimulationDesign:
    return SimulationDesign(
        datetime(2031, 1, 6, 9), 8, (timedelta(0), timedelta(days=3)),
        (ExerciseSpec("unit-lift-a", 3, 5, 0.5), ExerciseSpec("unit-lift-b", 2, 8, 0.25)),
        base_rpe=6, rpe_logging_probability=0.5,
    )


@pytest.fixture
def simulation_families(simulation_params: LifterParams, design: SimulationDesign) -> tuple[SimulationFamily, ...]:
    # Opaque unit references only. No human note wording or real partition IDs.
    refs = tuple(NoteTemplateRef(f"unit-ref-{topic}", topic) for topic in ("sleep_loss", "illness", "travel"))
    configurations = (
        ("unit-volume", (ReduceSets(1), ShortHistory(10))),
        ("unit-fatigue", (RisingRPE(6, 0.1),)),
        ("unit-stagnant", (StagnantLoads(), FewSessions(3))),
        ("unit-spike", (LoadSpike(2, SessionRange(14, 16)),)),
        ("unit-frequency", (SessionGap(design.start + timedelta(days=14), design.start + timedelta(days=35), for_abstention=True),)),
        ("unit-logging", (MixedUnits(2), DuplicateSets(1), Outlier("load", 9000, session_index=1), MissingRPE(1, for_abstention=True))),
        ("unit-confounder", (ConfounderNotes(refs, (0,)),)),
    )
    return tuple(SimulationFamily(name, simulation_params, design, injections) for name, injections in configurations)


@pytest.fixture
def partition_data() -> dict[str, object]:
    # Entirely synthetic P1 inputs. Golden has no descriptions or evaluation IDs.
    return {
        "manifest_version": "synthetic-fi2-test", "seeds": {"train": [0, 9], "dev": [100, 399], "golden": [1000, 1009]},
        "personas": {"train": [{"id": "ps_tr_unit", "description": "synthetic"}],
                     "dev": [{"id": "ps_dev_unit", "description": "synthetic"}], "golden": []},
        "scenario_templates": {"train": [], "dev": [
            {"id": "st_dev_unit", "description": "synthetic", "category": "unit-test"},
        ], "golden": []},
        "phrasing_families": {"train": [], "dev": [
            {"id": "pf_dev_extractor", "description": "synthetic", "consumer": "extractor"},
            {"id": "pf_dev_classifier", "description": "synthetic", "consumer": "classifier"},
        ], "golden": []},
        "exercise_families": ["squat"],
    }


@pytest.fixture
def development_partition(partition_data: dict[str, object]):
    from src.datagen.partition import Partition
    return Partition.from_mapping(partition_data)


@pytest.fixture
def export_metadata():
    from src.sim.opengym import ExerciseExport, OpenGymMetadata
    # Explicit synthetic source catalog IDs and matcher bindings, not real exports.
    return OpenGymMetadata("Synthetic development workout", 45, (
        ExerciseExport("unit-lift-a", "9901", "Synthetic lift A", "chest", "Barbell_Bench_Press_-_Medium_Grip"),
        ExerciseExport("unit-lift-b", "9902", "Synthetic lift B", "quadriceps", "Barbell_Full_Squat"),
    ), 26)


@pytest.fixture
def development_config_data(simulation_families: tuple[SimulationFamily, ...], export_metadata) -> dict[str, object]:
    from src.sim.workouts import development_value
    families = []
    # Note-free six-family development coverage. Confounder coverage is pending,
    # rather than supplying an invented dev tier2_notes family.
    for family in simulation_families[:-1]:
        design_data = development_value(family.design)
        del design_data["note_templates"]
        design_data["session_offsets_minutes"] = [int(v.total_seconds() / 60) for v in family.design.session_offsets]
        del design_data["session_offsets"]
        families.append({
            "family_id": family.family_id, "scenario_template_id": "st_dev_unit",
            "params": development_value(family.params), "design": design_data,
            "injections": [{"kind": type(v).__name__, "parameters": development_value(v)} for v in family.injections],
        })
    return {
        "families": families,
        "export": {"workout_name": export_metadata.workout_name, "duration_minutes": 45, "variant": 26,
                   "exercises": [vars(v) for v in export_metadata.exercises]},
    }
