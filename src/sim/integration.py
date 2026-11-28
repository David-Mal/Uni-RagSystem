"""Partitioned development export pipeline, with no inferred evaluation labels."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import MappingProxyType

from src.datagen.partition import Partition

from .opengym import OpenGymMetadata, serialize_opengym
from .partitioning import select_development_inputs
from .plans import plan_development_cases, planned_coverage
from .quotas import QuotaRequirements, quota_shortfalls
from .scenarios import SimulationFamily, injected_coverage, simulate_family
from .schema import freeze_json, json_bytes

# Readiness facts, not new indicator rules or alternative annotation algorithms.
PENDING_EVALUATION_DECISIONS = (
    "human-authored held-out note templates and bindings",
    "approved hypothesis/evidence and full-versus-partial abstention rubric",
    "explicit gate annotations and human review",
)
POST_GENERATION_CHECKS = ("independent detectability checks", "blind audit and adjudication", "freeze")


@dataclass(frozen=True)
class DevelopmentExport:
    """Immutable, fully prepared development artifacts; never GroundTruth files."""

    files: Mapping[str, bytes]
    summary: Mapping[str, object]

    def __post_init__(self) -> None:
        if any(Path(name).name != name or name in (".", "..") or not isinstance(value, bytes)
               for name, value in self.files.items()):
            raise ValueError("development artifacts require plain file names and byte content")
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))
        object.__setattr__(self, "summary", freeze_json(self.summary))

    def write(self, directory: Path) -> None:
        """Write only to a new, non-golden directory after all validation passed."""
        target = directory.resolve()
        parts = tuple(part.lower() for part in target.parts)
        if "golden" in parts or "pilot" in parts:
            raise ValueError("development artifacts cannot be written to a golden or pilot path")
        target.mkdir(parents=True, exist_ok=False)
        for name, content in sorted(self.files.items()):
            (target / name).write_bytes(content)


def prepare_development_export(
    families: Sequence[SimulationFamily], metadata: OpenGymMetadata, partition: Partition,
    template_bindings: Mapping[str, str], *, n: int, seed: int, known_exercise_ids: Collection[str],
    persona_ids: Sequence[str] | None = None,
) -> DevelopmentExport:
    """Generate actual partitioned logs and CSVs without touching an output path.

    Balanced development coverage does not claim the issue's final annotation
    quotas. Confounder text is unavailable in dev: requests for notes fail instead
    of borrowing held-out families or silently dropping configured injections.
    """
    if not isinstance(metadata, OpenGymMetadata):
        raise ValueError("validated OpenGym metadata is required")
    if not isinstance(template_bindings, Mapping) or set(template_bindings) != {f.family_id for f in families}:
        raise ValueError("every simulation family needs exactly one explicit P1 template binding")
    metadata.validate_canonical_ids(known_exercise_ids)
    if metadata.workout_note or any(item.note or item.set_note for item in metadata.sets.values()):
        raise ValueError("development workflow omits notes; no authorized development tier2_notes family exists")
    for family in families:
        if family.params.notes_frequency or family.design.note_templates or any(
            request for request in family.planning_family().requests.confounders
        ):
            raise ValueError("development note generation is pending; use note-free families")
    plans = plan_development_cases([f.planning_family() for f in families], n=n, unit_test_seed=seed)
    selected = select_development_inputs(
        partition, seed=seed, scenario_template_ids=[template_bindings[p.cluster_id] for p in plans],
        persona_ids=persona_ids,
    )
    by_family = {f.family_id: f for f in families}
    files: dict[str, bytes] = {}
    scenarios = []
    sessions = rows = 0
    for plan, provenance in zip(plans, selected, strict=True):
        scenario = simulate_family(by_family[plan.cluster_id], seed=provenance.seed, scenario_id=plan.plan_id)
        if scenario.expected_annotations is not None:
            raise ValueError("development output cannot be presented as validated ground truth")
        csv_data = serialize_opengym(scenario.log, metadata)
        scenarios.append(scenario)
        sessions += len(scenario.log.sessions)
        rows += sum(len(e.sets) for s in scenario.log.sessions for e in s.exercises)
        files[f"{scenario.scenario_id}.csv"] = csv_data
        items = [item for session in scenario.log.sessions for exercise in session.exercises for item in exercise.sets]
        rejection_reasons = (["empty_log"] if not items else []) + sorted({
            reason for item in items for reason, invalid in (("negative_weight", item.load < 0),
                                                            ("negative_rpe", item.rpe is not None and item.rpe < 0))
            if invalid
        })
        files[f"{scenario.scenario_id}.development.json"] = json_bytes({
            **scenario.to_dict(), "provenance": provenance.to_dict(partition),
            "export": {
                "csv_sha256": hashlib.sha256(csv_data).hexdigest(), "column_variant": metadata.variant,
                "workout_name": metadata.workout_name, "duration_minutes": metadata.duration_minutes,
                "exercise_mappings": [vars(item) for item in metadata.exercises],
                "set_metadata": {key: vars(value) for key, value in metadata.sets.items()},
                "d5_contract_expected_rejection_reasons": rejection_reasons,
                "d4_contract_expected_rpe_flags": sum(item.rpe is not None and item.rpe > 10 for item in items),
            },
            "validated_evaluation_ground_truth": False,
        })
    observed = injected_coverage(scenarios)
    summary = {
        "development_only": True, "scenarios": n, "sessions": sessions, "set_rows": rows,
        "planned_coverage": planned_coverage(plans).to_dict(), "injected_coverage": observed.to_dict(),
        "issue_injected_pattern_shortfalls": quota_shortfalls(observed, QuotaRequirements()),
        "validated_evaluation_ground_truth_records": 0, "partition_validation": "passed/dev",
        "manifest_version": partition.manifest_version, "master_seed": seed,
        "notes_mode": "omitted/no-authorized-dev-tier2-notes", "indicator_contract": "D3 v1 (merged)",
        "annotation_decisions": "pending; no production tools or reference implementation consulted",
        "evaluation_blockers": PENDING_EVALUATION_DECISIONS,
        "post_generation_requirements": POST_GENERATION_CHECKS,
        "ingestion_validation": "not_run_by_exporter",
        "csv_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in files.items() if name.endswith(".csv")},
    }
    files["development-batch.json"] = json_bytes(summary)
    return DevelopmentExport(files, summary)
