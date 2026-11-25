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
