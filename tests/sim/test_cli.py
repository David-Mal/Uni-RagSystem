from pathlib import Path
import json
import subprocess
import sys

import pytest
import yaml

from scripts.generate_tier2 import main

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/generate_tier2.py"


def write_inputs(tmp_path, development_config_data, partition_data):
    config = tmp_path / "development-config.json"
    config.write_text(json.dumps(development_config_data), encoding="utf-8")
    manifest = tmp_path / "synthetic-partition.yaml"
    manifest.write_text(yaml.safe_dump(partition_data), encoding="utf-8")
    return config, manifest


def test_final_evaluation_always_fails_closed_before_opening_input(tmp_path, capsys):
    output = tmp_path / "output"
    assert main(["--n", "150", "--out", str(output)], repository_root=tmp_path) == 2
    assert not output.exists()
    assert "Final evaluation generation is blocked" in capsys.readouterr().err


@pytest.mark.parametrize("n", ("0", "-1", "1.5", "invalid"))
def test_invalid_cli_input(n, tmp_path):
    with pytest.raises(SystemExit) as caught:
        main(["--n", n, "--out", str(tmp_path / "output")])
    assert caught.value.code == 2
    assert not (tmp_path / "output").exists()


def test_development_requires_explicit_config_and_seed(tmp_path):
    with pytest.raises(SystemExit):
        main(["--development", "--out", str(tmp_path / "output")])
    assert not (tmp_path / "output").exists()


def test_full_development_cli_byte_identical(tmp_path, development_config_data, partition_data):
    config, manifest = write_inputs(tmp_path, development_config_data, partition_data)
    common = ["--development", "--n", "150", "--seed", "100", "--config", str(config), "--partition", str(manifest)]
    a, b = tmp_path / "a", tmp_path / "b"
    assert main([*common, "--out", str(a)]) == main([*common, "--out", str(b)]) == 0
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())
    for path in a.iterdir():
        assert path.read_bytes() == (b / path.name).read_bytes()
    summary = json.loads((a / "development-batch.json").read_bytes())
    assert summary["scenarios"] == 150 and summary["partition_validation"] == "passed/dev"
    assert summary["validated_evaluation_ground_truth_records"] == 0
    assert summary["ingestion_validation"] == "not_run_by_exporter"
    assert summary["injected_coverage"]["confounders"] == 0
    assert summary["issue_injected_pattern_shortfalls"] == {"confounder_present": 20, "confounders": 20}
    cases = sorted(a.glob("*.development.json"))
    assert len(cases) == len(list(a.glob("*.csv"))) == 150
    for path in cases:
        record = json.loads(path.read_bytes())
        assert 100 <= record["seed"] <= 399
        assert record["seed"] == record["provenance"]["seed"]
        assert record["expected_annotations"] is None
        assert record["validated_evaluation_ground_truth"] is False
    before = (a / "development-batch.json").read_bytes()
    assert main([*common, "--out", str(a)]) == 2
    assert (a / "development-batch.json").read_bytes() == before


@pytest.mark.parametrize("problem", ("wrong-seed", "unknown-template", "unknown-exercise", "notes", "invalid-json"))
def test_invalid_contracts_leave_output_absent(tmp_path, development_config_data, partition_data, problem):
    config_data = development_config_data
    if problem == "unknown-template":
        config_data["families"][0]["scenario_template_id"] = "st_dev_missing"
    elif problem == "unknown-exercise":
        config_data["export"]["exercises"][0]["canonical_exercise_id"] = "unknown_unit_id"
    elif problem == "notes":
        config_data["families"][0]["params"]["notes_frequency"] = 1
    config, manifest = write_inputs(tmp_path, config_data, partition_data)
    if problem == "invalid-json":
        config.write_text('{"families":[],"families":[]}', encoding="utf-8")
    output = tmp_path / "output"
    assert main(["--development", "--n", "6", "--seed", "0" if problem == "wrong-seed" else "100",
                 "--config", str(config), "--partition", str(manifest), "--out", str(output)]) == 2
    assert not output.exists()


def test_restricted_output_rejected_before_loading_config(tmp_path):
    output = tmp_path / "golden" / "output"
    assert main(["--development", "--seed", "100", "--config", str(tmp_path / "does-not-exist.json"),
                 "--out", str(output)]) == 2
    assert not output.parent.exists()


def test_documented_script_invocation_from_other_directory(tmp_path):
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--n", "150", "--out", str(tmp_path / "output")],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 2 and "generation is blocked" in result.stderr
    assert not (tmp_path / "output").exists()


def test_development_script_from_other_directory(tmp_path, development_config_data, partition_data):
    config, manifest = write_inputs(tmp_path, development_config_data, partition_data)
    output = tmp_path / "output"
    result = subprocess.run([
        sys.executable, "-B", str(SCRIPT), "--development", "--n", "6", "--seed", "100", "--config", str(config),
        "--partition", str(manifest), "--out", str(output),
    ], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert len(list(output.glob("*.csv"))) == 6
