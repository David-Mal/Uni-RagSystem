"""Tests for the shared tool models (issue D3)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.schemas import VALUE_ID_PATTERN
from src.tools.common import (
    Provenance,
    ToolError,
    ToolResult,
    Value,
    ValueIdFactory,
    config_hash,
    load_indicator_config,
)

SPEC = Path(__file__).resolve().parents[2] / "docs" / "indicator-spec.md"
PROV = Provenance(formula="w*r", input_row_ids=["a"], tool_version="t-1", config_hash="h")


def make_value(**kw: Any) -> Value:
    return Value(**{"value_id": "v_x_0001", "name": "x", "value": 1.5, "unit": "kg", "provenance": PROV, **kw})


def test_value_ids_are_unique_across_names_and_match_the_claim_schema() -> None:
    ids = ValueIdFactory()
    got = [ids.new(n) for n in ("e1rm_slope", "e1rm_slope", "rpe_drift_slope")]
    assert got == ["v_e1rm_slope_0001", "v_e1rm_slope_0002", "v_rpe_drift_slope_0003"]
    assert all(re.fullmatch(VALUE_ID_PATTERN, v) for v in got)


def test_value_ids_stay_unique_past_four_digits() -> None:
    ids = ValueIdFactory()
    got = [ids.new("x") for _ in range(10_001)]
    assert len(set(got)) == len(got)
    assert got[-1] == "v_x_10001"
    assert re.fullmatch(VALUE_ID_PATTERN, got[-1])


def test_counter_is_per_factory() -> None:
    assert ValueIdFactory().new("x") == ValueIdFactory().new("x")


@pytest.mark.parametrize("name", ["", "E1RM", "a b", "a-b", "x\n"])
def test_bad_value_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="value name"):
        ValueIdFactory().new(name)


def test_config_hash_is_stable_and_order_independent() -> None:
    assert config_hash({"a": 1, "b": {"c": 2, "d": 3}}) == config_hash({"b": {"d": 3, "c": 2}, "a": 1})
    # sha256 of the 7 bytes {"a":1}
    assert config_hash({"a": 1}) == "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"


def test_config_hash_changes_with_a_value_and_rejects_nan() -> None:
    assert config_hash({"a": 1}) != config_hash({"a": 2})
    with pytest.raises(ValueError):
        config_hash({"a": float("nan")})


def test_value_keeps_the_type_of_its_number() -> None:
    assert isinstance(make_value(value=3).value, int)
    assert isinstance(make_value(value=3.0).value, float)
    assert make_value(value="flat", unit=None).value == "flat"


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_values_are_rejected(bad: float) -> None:
    with pytest.raises(ValidationError):
        make_value(value=bad)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolError(code="c", message="m", detail="typo")  # type: ignore[call-arg]


def test_tool_result_round_trips_through_json() -> None:
    result = ToolResult(tool_version="t-1", values=[make_value()], summary={"k": 1})
    assert ToolResult.model_validate_json(result.model_dump_json()) == result


def test_every_config_key_named_in_the_spec_exists() -> None:
    cfg = load_indicator_config()
    refs = re.findall(r"\[([a-z0-9_]+)\.([a-z0-9_]+)\]", SPEC.read_text(encoding="utf-8"))
    refs = [(s, k) for s, k in refs if (s, k) != ("section", "key")]
    assert len(refs) > 15
    assert [f"{s}.{k}" for s, k in refs if k not in cfg.get(s, {})] == []


def test_bad_config_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("- 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_indicator_config(path)
