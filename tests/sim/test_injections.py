from dataclasses import replace
from collections.abc import Callable
from datetime import timedelta

import pytest

from src.sim.injections import (
    ConfounderNotes, DuplicateSets, FewSessions, LoadSpike, MissingRPE, MixedUnits,
    Outlier, ReduceSets, RisingRPE, SessionGap, SessionRange, ShortHistory, StagnantLoads,
    apply_injection, flat_sets, max_gap_seconds, observe_injection,
)
from src.sim.params import LifterParams
from src.sim.workouts import NoteTemplateRef, SimulationDesign, SimulatedLog, convert_load, generate_workouts


def test_reduce_actual_set_volume_without_mutating_baseline(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    snapshot = before.to_json_bytes()
    config = ReduceSets(1)
    after = apply_injection(before, config)
    # 16 sessions * 2 exercises * 1 retained set = 32; baseline has 80.
    assert len(flat_sets(after)) == 32
    assert observe_injection(before, after, config).present
    assert before.to_json_bytes() == snapshot


def test_rising_rpe_at_exactly_fixed_load(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    config = RisingRPE(5, 0.25, SessionRange(0, 3))
    after = apply_injection(before, config)
    # Caller-selected sequence 5, 5+.25, 5+2*.25; loads remain the first 50.
    assert [item.exercises[0].sets[0].rpe for item in after.sessions[:3]] == [5, 5.25, 5.5]
    assert [item.exercises[0].sets[0].load for item in after.sessions[:3]] == [50, 50, 50]
    assert after.sessions[3] == before.sessions[3]
    assert observe_injection(before, after, config).present


def test_stagnant_interval_preserves_working_loads_and_reps(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    config = StagnantLoads(SessionRange(1, 4))
    after = apply_injection(before, config)
    assert [item.exercises[0].sets[0].load for item in after.sessions[1:4]] == [52, 52, 52]
    assert [item.exercises[0].sets[0].reps for item in after.sessions[1:4]] == [5, 5, 5]
    assert after.sessions[0] == before.sessions[0] and after.sessions[4] == before.sessions[4]
    assert observe_injection(before, after, config).present


def test_selected_window_workload_increase(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    config = LoadSpike(2, SessionRange(14, 16))
    after = apply_injection(before, config)
    observed = observe_injection(before, after, config)
    # Session 14: 78*5*3 + 53*8*2 = 2018. Session 15: 80*5*3 + 55*8*2 = 2080.
    # Total 4098 becomes 8196 with doubled working weights and unchanged reps.
    assert observed.facts["before_load_times_reps_kg"] == 4098
    assert observed.facts["after_load_times_reps_kg"] == 8196
    assert observed.present and after.sessions[:14] == before.sessions[:14]


def test_gap_removal_and_rescheduling(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    gap = SessionGap(design.start + timedelta(days=14), design.start + timedelta(days=35), for_abstention=True)
    after = apply_injection(before, gap)
    # Remove six sessions on days 14,17,21,24,28,31. Day 10 to day 35 is 25 days.
    assert len(after.sessions) == 10
    assert max_gap_seconds(after) == 25 * 24 * 60 * 60
    assert observe_injection(before, after, gap).present
    shifted = SessionGap(design.start, design.start + timedelta(days=1), reschedule_by=timedelta(days=7))
    moved = apply_injection(before, shifted)
    assert len(moved.sessions) == 16
    assert next(item for item in moved.sessions if item.session_id == before.sessions[0].session_id).at == design.start + timedelta(days=7)
    assert moved.sessions == tuple(sorted(moved.sessions, key=lambda item: (item.at, item.session_id)))


def test_unit_mix_preserves_physical_loads(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    config = MixedUnits(2)
    after = apply_injection(before, config)
    first, second = flat_sets(after)[:2]
    assert first.unit == "lb" and first.load == pytest.approx(110.2311310924)
    assert second.unit == "kg" and second.load == 50
    for original, transformed in zip(flat_sets(before), flat_sets(after), strict=True):
        assert convert_load(transformed.load, transformed.unit, "kg") == pytest.approx(original.load)
    assert observe_injection(before, after, config).present
    # Flipping every row changes the unit but does not create mixed units.
    assert not observe_injection(before, apply_injection(before, MixedUnits(1)), MixedUnits(1)).present


def test_identical_duplicate_rows(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    config = DuplicateSets(1)
    after = apply_injection(before, config)
    assert len(flat_sets(after)) == 81
    assert after.sessions[0].exercises[0].sets[0] == after.sessions[0].exercises[0].sets[1]
    assert observe_injection(before, after, config).facts["identical_copies"] == 2


def test_missing_rpe_and_no_rpe_pattern(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    half = apply_injection(before, MissingRPE(2))
    assert sum(item.rpe is None for item in flat_sets(half)) == 40
    config = MissingRPE(1, for_abstention=True)
    after = apply_injection(before, config)
    assert all(item.rpe is None for item in flat_sets(after))
    assert observe_injection(before, after, config).present


@pytest.mark.parametrize(("field", "value"), [("load", -9000), ("rpe", 47)])
def test_configurable_outliers_without_detection_thresholds(simulation_params: LifterParams, design: SimulationDesign, field: str, value: float) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    config = Outlier(field, value)
    after = apply_injection(before, config)
    assert getattr(flat_sets(after)[0], field) == value
    assert observe_injection(before, after, config).present
    assert flat_sets(before)[0].load == 50 and flat_sets(before)[0].rpe == 6


def test_confounder_template_reference_integration(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    refs = tuple(NoteTemplateRef(f"unit-template-{topic}", topic) for topic in ("sleep_loss", "illness", "travel"))
    config = ConfounderNotes(refs, (0, 2))
    after = apply_injection(before, config)
    assert after.sessions[0].note_refs == refs and after.sessions[2].note_refs == refs
    assert not after.sessions[1].note_refs
    observed = observe_injection(before, after, config)
    assert observed.present and observed.facts["attached_template_references"] == 6
    assert all(not hasattr(item, "text") for item in refs)


def test_actual_history_and_session_abstention_patterns(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    short = ShortHistory(10)
    after = apply_injection(before, short)
    # The original schedule ends on day 52; retain days 42,45,49,52.
    assert len(after.sessions) == 4
    assert (after.sessions[-1].at - after.sessions[0].at).days == 10
    assert observe_injection(before, after, short).present
    few = FewSessions(2)
    assert len(apply_injection(before, few).sessions) == 2
    assert observe_injection(before, apply_injection(before, few), few).present
    assert apply_injection(before, FewSessions(0)).sessions == ()


@pytest.mark.parametrize("factory", [
    lambda: ReduceSets(-1), lambda: RisingRPE(6, 0), lambda: LoadSpike(1, SessionRange()),
    lambda: MixedUnits(0), lambda: DuplicateSets(0), lambda: MissingRPE(2, for_abstention=True),
    lambda: Outlier("reps", 1), lambda: Outlier("load", float("nan")),
    lambda: ShortHistory(-1), lambda: FewSessions(-1), lambda: SessionRange(3, 2),
    lambda: ConfounderNotes((NoteTemplateRef("unit-neutral"),), (0,)),
])
def test_invalid_injection_configuration(factory: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        factory()


def test_invalid_targets_and_empty_logs(simulation_params: LifterParams, design: SimulationDesign) -> None:
    log = generate_workouts(simulation_params, design, seed=1)
    for config in (DuplicateSets(1, session_index=100), Outlier("load", 1, set_index=100), LoadSpike(2, SessionRange(100, 101))):
        with pytest.raises(ValueError):
            apply_injection(log, config)
    empty = SimulatedLog(())
    assert apply_injection(empty, ShortHistory(2)) == empty
    assert not observe_injection(empty, empty, MissingRPE(1)).present


def test_no_op_injections_do_not_borrow_later_changes(simulation_params: LifterParams, design: SimulationDesign) -> None:
    before = generate_workouts(simulation_params, design, seed=1)
    later = apply_injection(before, FewSessions(2))
    assert not observe_injection(before, later, ReduceSets(100)).present
    assert not observe_injection(before, later, ShortHistory(1000)).present
    assert not observe_injection(before, later, FewSessions(100)).present
    absent_gap = SessionGap(design.start - timedelta(days=20), design.start - timedelta(days=10))
    assert not observe_injection(before, later, absent_gap).present
