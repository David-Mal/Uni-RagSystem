"""Strict explicit development configuration; no project or export defaults."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import MappingProxyType

from . import injections as causes
from .opengym import ExerciseExport, OpenGymMetadata, SetExport
from .params import LifterParams
from .scenarios import SimulationFamily
from .schema import nonempty
from .workouts import ExerciseSpec, SimulationDesign


def _object(value: object, required: set[str], optional: set[str] = frozenset()) -> dict[str, object]:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise ValueError(f"configuration requires {sorted(required)}; optional keys: {sorted(optional)}")
    return dict(value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON configuration key: {key}")
        result[key] = value
    return result


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("simulation datetime must be explicit ISO text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError("simulation datetime must be naive local time")
    return parsed


def _minutes(value: object) -> timedelta:
    if type(value) is not int:
        raise ValueError("simulation minute offsets must be strict integers")
    return timedelta(minutes=value)


_CAUSE_TYPES = {
    cls.__name__: cls for cls in (
        causes.ReduceSets, causes.RisingRPE, causes.StagnantLoads, causes.LoadSpike, causes.SessionGap,
        causes.MixedUnits, causes.DuplicateSets, causes.MissingRPE, causes.Outlier, causes.ShortHistory, causes.FewSessions,
    )
}


def _injection(value: object) -> causes.Injection:
    data = _object(value, {"kind", "parameters"})
    if not isinstance(data["kind"], str) or data["kind"] not in _CAUSE_TYPES:
        raise ValueError("unknown development injection; ConfounderNotes requires unavailable dev note policy")
    if not isinstance(data["parameters"], dict):
        raise ValueError("injection parameters must be an object")
    parameters = dict(data["parameters"])
    if "interval" in parameters:
        parameters["interval"] = causes.SessionRange(**_object(parameters["interval"], set(), {"start", "stop"}))
    if data["kind"] == "SessionGap":
        for key in ("start", "end"):
            if key not in parameters:
                raise ValueError("SessionGap requires start and end")
            parameters[key] = _datetime(parameters[key])
        if "reschedule_minutes" in parameters:
            parameters["reschedule_by"] = _minutes(parameters.pop("reschedule_minutes"))
    try:
        return _CAUSE_TYPES[data["kind"]](**parameters)
    except TypeError as exc:
        raise ValueError(f"invalid {data['kind']} parameters: {exc}") from exc


@dataclass(frozen=True)
class DevelopmentConfig:
    families: tuple[SimulationFamily, ...]
    metadata: OpenGymMetadata
    template_bindings: Mapping[str, str]
    persona_ids: tuple[str, ...] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "template_bindings", MappingProxyType(dict(self.template_bindings)))


def load_development_config(path: Path) -> DevelopmentConfig:
    """Read only caller-supplied development JSON, never a golden catalog."""
    if any(part.lower() in ("golden", "pilot") for part in path.resolve().parts):
        raise ValueError("development configuration cannot be read from a golden or pilot path")
    def invalid_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")
    data = _object(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=invalid_constant), {"families", "export"}, {"persona_ids"})
    if not isinstance(data["families"], list) or not data["families"]:
        raise ValueError("at least one explicit simulation family is required")
    families = []
    bindings: dict[str, str] = {}
    for raw in data["families"]:
        family = _object(raw, {"family_id", "scenario_template_id", "params", "design", "injections"})
        nonempty(family["scenario_template_id"], "scenario_template_id")
        params = LifterParams(**_object(family["params"], {
            "sessions_per_week", "start_e1rm", "progression_rate", "noise", "units", "rpe_habit", "notes_frequency",
        }))
        design = _object(family["design"], {
            "start", "weeks", "session_offsets_minutes", "exercises", "base_rpe", "rpe_logging_probability",
        })
        if not all(isinstance(design[key], list) for key in ("session_offsets_minutes", "exercises")):
            raise ValueError("session offsets and exercises must be arrays")
        design = SimulationDesign(
            _datetime(design["start"]), design["weeks"],
            tuple(_minutes(value) for value in design["session_offsets_minutes"]),
            tuple(ExerciseSpec(**_object(item, {"exercise_key", "sets_per_session", "reps", "load_multiplier"}))
                  for item in design["exercises"]),
            design["base_rpe"], design["rpe_logging_probability"],
        )
        if not isinstance(family["injections"], list):
            raise ValueError("injections must be an array")
        item = SimulationFamily(family["family_id"], params, design, tuple(_injection(v) for v in family["injections"]))
        if item.family_id in bindings:
            raise ValueError("duplicate simulation family ID")
        bindings[item.family_id] = family["scenario_template_id"]
        families.append(item)
    raw_export = _object(data["export"], {"workout_name", "duration_minutes", "variant", "exercises"}, {"sets"})
    if not isinstance(raw_export["exercises"], list):
        raise ValueError("export exercises must be an array")
    raw_export["exercises"] = tuple(ExerciseExport(**_object(item, {
        "exercise_key", "source_catalog_id", "name", "body_part", "canonical_exercise_id",
    })) for item in raw_export["exercises"])
    sets = raw_export.get("sets", {})
    if not isinstance(sets, dict):
        raise ValueError("export sets must be an object")
    raw_export["sets"] = {key: SetExport(**_object(value, set(), {"set_type", "distance_km", "seconds"}))
                          for key, value in sets.items()}
    metadata = OpenGymMetadata(**raw_export)
    personas = data.get("persona_ids")
    if personas is not None:
        if not isinstance(personas, list) or not personas:
            raise ValueError("persona_ids must be a nonempty array")
        for value in personas:
            nonempty(value, "persona ID")
        if len(set(personas)) != len(personas):
            raise ValueError("duplicate persona ID")
    return DevelopmentConfig(tuple(families), metadata, bindings, None if personas is None else tuple(personas))
