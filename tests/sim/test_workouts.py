from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
import random

import pytest

from src.sim.params import LifterParams
from src.sim.injections import flat_sets
from src.sim.workouts import ExerciseSpec, NoteTemplateRef, SimulationDesign, convert_load, generate_workouts


def test_real_sessions_sets_progression_and_order(simulation_params: LifterParams, design: SimulationDesign) -> None:
    log = generate_workouts(simulation_params, design, seed=17)
    # 8 weeks * 2 sessions = 16; (3 + 2) sets/session * 16 = 80.
    assert len(log.sessions) == 16
    assert len(flat_sets(log)) == 80
    assert [item.exercise_key for item in log.sessions[0].exercises] == ["unit-lift-a", "unit-lift-b"]
    assert [item.slot for item in log.sessions[0].exercises[0].sets] == [0, 1, 2]
    assert [item.at - design.start for item in log.sessions[:3]] == [timedelta(0), timedelta(days=3), timedelta(days=7)]
    # 100 * .5 = 50, then an explicitly selected +2 load units/session.
    assert [item.exercises[0].sets[0].load for item in log.sessions[:3]] == [50, 52, 54]
    # The second exercise starts at 100 * .25 = 25, with the same increment.
    assert [item.exercises[1].sets[0].load for item in log.sessions[:3]] == [25, 27, 29]
    assert {item.reps for item in log.sessions[0].exercises[0].sets} == {5}
    assert len({item.set_id for item in flat_sets(log)}) == 80


def test_seeded_noise_byte_identity_and_rng_isolation(simulation_params: LifterParams, design: SimulationDesign, tmp_path: Path) -> None:
    params = replace(simulation_params, noise=0.75, progression_rate=0)
    state = random.getstate()
    first = generate_workouts(params, design, seed=18)
    second = generate_workouts(params, design, seed=18)
    assert random.getstate() == state
    assert first.to_json_bytes() == second.to_json_bytes()
    assert first.to_json_bytes() != generate_workouts(params, design, seed=19).to_json_bytes()
    assert all(49.25 <= item.load <= 50.75 for session in first.sessions for item in session.exercises[0].sets)
    (tmp_path / "internal-development.json").write_bytes(first.to_json_bytes())
    assert b'"development_only":true' in (tmp_path / "internal-development.json").read_bytes()


@pytest.mark.parametrize("habit", ("always", "sometimes", "never"))
def test_rpe_habits_do_not_change_load_noise(simulation_params: LifterParams, design: SimulationDesign, habit: str) -> None:
    params = replace(simulation_params, noise=0.2, rpe_habit=habit)
    log = generate_workouts(params, design, seed=22)
    logged = sum(item.rpe is not None for item in flat_sets(log))
    if habit == "always":
        assert logged == 80
    elif habit == "never":
        assert logged == 0
    else:
        assert 0 < logged < 80
    always = generate_workouts(replace(params, rpe_habit="always"), design, seed=22)
    assert [item.load for item in flat_sets(log)] == [item.load for item in flat_sets(always)]


def test_sometimes_probability_endpoints(simulation_params: LifterParams, design: SimulationDesign) -> None:
    params = replace(simulation_params, rpe_habit="sometimes")
    assert all(item.rpe is None for item in flat_sets(generate_workouts(params, replace(design, rpe_logging_probability=0), seed=3)))
    assert all(item.rpe == 6 for item in flat_sets(generate_workouts(params, replace(design, rpe_logging_probability=1), seed=3)))


def test_imperial_support_and_exact_unit_conversion(simulation_params: LifterParams, design: SimulationDesign) -> None:
    log = generate_workouts(replace(simulation_params, units="lb"), design, seed=1)
    first = flat_sets(log)[0]
    assert first.unit == "lb" and first.load == 50
    # Exact NIST factor: 50 lb * 0.45359237 = 22.6796185 kg.
    assert convert_load(first.load, first.unit, "kg") == pytest.approx(22.6796185)
    assert convert_load(50, "kg", "lb") == pytest.approx(110.2311310924)


def test_notes_frequency_uses_only_external_references(simulation_params: LifterParams, design: SimulationDesign) -> None:
    references = (NoteTemplateRef("unit-reference-a"), NoteTemplateRef("unit-reference-b"))
    selected = replace(design, note_templates=references)
    log = generate_workouts(replace(simulation_params, notes_frequency=1.5), selected, seed=8)
    assert {len(item.note_refs) for item in log.sessions} == {1, 2}
    assert all(ref in references for item in log.sessions for ref in item.note_refs)
    assert all(not hasattr(ref, "text") for item in log.sessions for ref in item.note_refs)
    with pytest.raises(ValueError, match="enough externally supplied"):
        generate_workouts(replace(simulation_params, notes_frequency=1), design, seed=8)


@pytest.mark.parametrize("changes", [
    {"weeks": -1}, {"weeks": True}, {"session_offsets": (timedelta(days=7),)},
    {"session_offsets": (timedelta(days=3), timedelta(0))}, {"rpe_logging_probability": 1.1},
    {"base_rpe": float("nan")}, {"exercises": (ExerciseSpec("same", 1, 1, 1),) * 2},
])
def test_invalid_design(design: SimulationDesign, changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(design, **changes)


def test_invalid_generation_and_empty_period(simulation_params: LifterParams, design: SimulationDesign) -> None:
    with pytest.raises(ValueError, match="offsets must match"):
        generate_workouts(replace(simulation_params, sessions_per_week=3), design, seed=1)
    with pytest.raises(ValueError, match="negative working load"):
        generate_workouts(replace(simulation_params, progression_rate=-100), design, seed=1)
    with pytest.raises(ValueError):
        generate_workouts(simulation_params, design, seed=True)
    with pytest.raises(ValueError, match="naive"):
        replace(design, start=design.start.replace(tzinfo=timezone.utc))
    assert generate_workouts(simulation_params, replace(design, weeks=0), seed=1).sessions == ()
