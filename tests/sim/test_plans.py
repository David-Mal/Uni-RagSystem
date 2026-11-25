from pathlib import Path
import random

import pytest

from src.sim.params import LifterParams
from src.sim.plans import DevelopmentFamily, InjectionRequest, plan_development_cases
from src.sim.quotas import count_quotas
from src.sim.schema import HYPOTHESIS_LABELS


def test_all_requests_are_intents_without_notes_or_ground_truth(params: LifterParams) -> None:
    request = InjectionRequest(
        hypotheses=HYPOTHESIS_LABELS,
        abstention_cases=("too_little_history", "too_few_sessions", "long_gaps", "missing_rpe"),
        numeric_traps=("mixed_units", "duplicates", "missing_rpe", "outliers"),
        confounders=("sleep_loss", "illness", "travel"),
        human_note_template_id="unit-only-opaque-reference",
    )
    plans = plan_development_cases([DevelopmentFamily("unit-family", params, request)], n=3, unit_test_seed=7)
    assert all(plan.development_only for plan in plans)
    assert all(not hasattr(plan, "expected_hypotheses") for plan in plans)
    with pytest.raises(TypeError, match="not intent plans"):
        count_quotas(plans)


def test_deterministic_bytes_and_family_clusters(params: LifterParams, tmp_path: Path) -> None:
    families = [
        DevelopmentFamily("unit-family-a", params, InjectionRequest(hypotheses=("load_spike",))),
        DevelopmentFamily("unit-family-b", params, InjectionRequest(abstention_cases=("missing_rpe",))),
    ]
    state = random.getstate()
    first = plan_development_cases(families, n=8, unit_test_seed=11)
    assert random.getstate() == state
    second = plan_development_cases(families, n=8, unit_test_seed=11)
    # Only unit-test plans are serialized here, not logs or evaluation scenarios.
    for name, plans in (("first.jsonl", first), ("second.jsonl", second)):
        (tmp_path / name).write_bytes(b"".join(item.to_json_bytes() for item in plans))
    assert (tmp_path / "first.jsonl").read_bytes() == (tmp_path / "second.jsonl").read_bytes()
    assert len({item.plan_id for item in first}) == 8
    assert {item.cluster_id for item in first} == {"unit-family-a", "unit-family-b"}
    assert [sum(item.cluster_id == family.family_id for item in first) for family in families] == [4, 4]
    changed_seed = plan_development_cases(families, n=8, unit_test_seed=12)
    assert {item.cluster_id for item in changed_seed} == {item.cluster_id for item in first}


@pytest.mark.parametrize(
    "changes",
    [
        {"hypotheses": ("abstain",)},
        {"hypotheses": ("load_spike", "load_spike")},
        {"numeric_traps": ("guessed_trap",)},
        {"abstention_cases": ("guessed_reason_code",)},
        {"confounders": ("invented_cause",)},
        {"human_note_template_id": ""},
    ],
)
def test_reject_invalid_request(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        InjectionRequest(**changes)


@pytest.mark.parametrize(("n", "seed"), [(0, 1), (-1, 1), (True, 1), (1, False), (1, 1.5)])
def test_reject_invalid_plan_input(params: LifterParams, n: int, seed: int) -> None:
    family = DevelopmentFamily("unit-family", params, InjectionRequest())
    with pytest.raises(ValueError):
        plan_development_cases([family], n=n, unit_test_seed=seed)


def test_reject_empty_or_duplicate_families(params: LifterParams) -> None:
    family = DevelopmentFamily("unit-family", params, InjectionRequest())
    for families in ([], [family, family]):
        with pytest.raises(ValueError):
            plan_development_cases(families, n=2, unit_test_seed=1)
