from dataclasses import replace
import json

import pytest

from src.sim.integration import prepare_development_export
from src.sim.schema import ExpectedHypothesis, GroundTruth
from src.schemas.enums import EvidenceLevel, HypothesisLabel, TriageLevel


def prepare(simulation_families, export_metadata, development_partition, **kwargs):
    families = simulation_families[:-1]
    return prepare_development_export(
        families, export_metadata, development_partition, {f.family_id: "st_dev_unit" for f in families},
        n=6, seed=100, known_exercise_ids={v.canonical_exercise_id for v in export_metadata.exercises}, **kwargs,
    )


def test_integrated_scenarios_use_actual_pool_seeds_and_family_clusters(
    simulation_families, export_metadata, development_partition,
):
    result = prepare(simulation_families, export_metadata, development_partition)
    records = [json.loads(content) for name, content in result.files.items() if name.endswith(".development.json")]
    assert {r["seed"] for r in records} == set(range(100, 106))
    assert {r["cluster_id"] for r in records} == {f.family_id for f in simulation_families[:-1]}
    assert all(r["provenance"]["scenario_template_id"] == "st_dev_unit" for r in records)
    assert all(not s["note_refs"] for r in records for s in r["log"]["sessions"])
    changed = prepare(simulation_families, replace(export_metadata, duration_minutes=46), development_partition)
    assert result.files != changed.files


def test_confounds_are_blocked_in_export_not_silently_omitted(simulation_families, export_metadata, development_partition):
    with pytest.raises(ValueError, match="note"):
        prepare_development_export(
            simulation_families, export_metadata, development_partition,
            {f.family_id: "st_dev_unit" for f in simulation_families}, n=7, seed=100,
            known_exercise_ids={v.canonical_exercise_id for v in export_metadata.exercises},
        )


def test_merged_f2_enums_are_reused_without_inferred_labels(annotation):
    hypothesis = ExpectedHypothesis("load_spike", "weak")
    assert hypothesis.label is HypothesisLabel.LOAD_SPIKE
    assert hypothesis.evidence is EvidenceLevel.WEAK
    item = annotation(expected_hypotheses=(hypothesis,), gate_outcome="green")
    assert item.gate_outcome is TriageLevel.GREEN
    assert GroundTruth.from_json_bytes(item.to_json_bytes()) == item


def test_no_ground_truth_file_is_written(simulation_families, export_metadata, development_partition, tmp_path):
    exported = prepare(simulation_families, export_metadata, development_partition)
    output = tmp_path / "development"
    exported.write(output)
    assert not list(output.glob("*.ground-truth.json"))
    assert all(json.loads(p.read_bytes())["expected_annotations"] is None for p in output.glob("*.development.json"))


def test_rejected_traps_are_explicit_without_silently_repairing_values(
    simulation_families, export_metadata, development_partition,
):
    from src.sim.injections import Outlier
    family = replace(simulation_families[0], injections=(Outlier("load", -20),))
    result = prepare_development_export(
        (family,), export_metadata, development_partition, {family.family_id: "st_dev_unit"},
        n=1, seed=100, known_exercise_ids={v.canonical_exercise_id for v in export_metadata.exercises},
    )
    record = json.loads(result.files["development-000001.development.json"])
    assert record["export"]["d5_contract_expected_rejection_reasons"] == ["negative_weight"]
    assert b",-20,kg," in result.files["development-000001.csv"]
    assert result.summary["validated_evaluation_ground_truth_records"] == 0


def test_prepared_artifact_summary_is_deeply_immutable(simulation_families, export_metadata, development_partition):
    result = prepare(simulation_families, export_metadata, development_partition)
    with pytest.raises(TypeError):
        result.summary["injected_coverage"]["by_hypothesis"]["load_spike"] = 999
    with pytest.raises(TypeError):
        result.files["development-batch.json"] = b"invalid"
