import json

import pytest

from src.sim.config import load_development_config


def test_explicit_configuration_loads_existing_core_models(tmp_path, development_config_data):
    path = tmp_path / "development.json"
    path.write_text(json.dumps(development_config_data), encoding="utf-8")
    config = load_development_config(path)
    assert len(config.families) == 6
    assert config.metadata.duration_minutes == 45
    assert config.families[0].design.session_offsets[1].total_seconds() == 3 * 24 * 60 * 60
    with pytest.raises(TypeError):
        config.template_bindings["unit-volume"] = "st_dev_changed"


@pytest.mark.parametrize("value", (
    '{"families":[],"export":{},"extra":1}',
    '{"families":NaN,"export":{}}',
    '{"families":Infinity,"export":{}}',
    '{"families":[],"families":[],"export":{}}',
    '[]', 'not JSON',
))
def test_invalid_configuration_is_rejected(tmp_path, value):
    path = tmp_path / "invalid.json"
    path.write_text(value, encoding="utf-8")
    with pytest.raises(ValueError):
        load_development_config(path)


@pytest.mark.parametrize("change", ("unknown-cause", "invented-export-column", "fractional-minute", "bad-unit"))
def test_contract_errors_rejected(tmp_path, development_config_data, change):
    if change == "unknown-cause":
        development_config_data["families"][0]["injections"][0]["kind"] = "InventedCause"
    elif change == "invented-export-column":
        development_config_data["export"]["automatic_unit_guess"] = True
    elif change == "fractional-minute":
        development_config_data["families"][0]["design"]["session_offsets_minutes"] = [0, 0.5]
    elif change == "bad-unit":
        development_config_data["families"][0]["params"]["units"] = "stone"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(development_config_data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_development_config(path)
