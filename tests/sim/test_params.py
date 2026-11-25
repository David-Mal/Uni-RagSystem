from dataclasses import asdict, replace

import pytest

from src.sim.params import LifterParams


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("sessions_per_week", -1),
        ("sessions_per_week", True),
        ("sessions_per_week", 1.5),
        ("start_e1rm", 0),
        ("start_e1rm", "83.5"),
        ("start_e1rm", 10**400),
        ("progression_rate", float("nan")),
        ("progression_rate", False),
        ("noise", float("inf")),
        ("noise", -0.1),
        ("notes_frequency", -1),
        ("notes_frequency", float("-inf")),
        ("units", "lbs"),
        ("rpe_habit", "occasionally"),
    ],
)
def test_reject_invalid_parameters(params: LifterParams, name: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(params, **{name: value})


def test_no_undocumented_upper_limits_or_rate_scale(params: LifterParams) -> None:
    configured = replace(params, sessions_per_week=20, progression_rate=-3, notes_frequency=9)
    assert configured.sessions_per_week == 20
    assert configured.progression_rate == -3
    assert configured.notes_frequency == 9
    assert replace(params, sessions_per_week=0, noise=0, notes_frequency=0).sessions_per_week == 0


def test_no_implicit_defaults(params: LifterParams) -> None:
    with pytest.raises(TypeError):
        LifterParams()
    assert LifterParams(**asdict(params)) == params
