"""Development selection through P1's actual public partition interface."""

from dataclasses import dataclass
from collections.abc import Sequence

from src.datagen.partition import CONSUMERS_BY_POOL, Partition, PoolError

from .schema import json_bytes, nonempty
from .workouts import count

GENERATOR_MODEL = "deterministic-code/no-LLM"
GENERATOR_VERSION = "fi2-development-v1"


@dataclass(frozen=True)
class DevelopmentProvenance:
    seed: int
    persona_id: str
    scenario_template_id: str
    phrasing_family_ids: tuple[str, ...] = ()
    consumer: str | None = None
    pool: str = "dev"

    def validate(self, partition: Partition) -> None:
        if self.pool != "dev":
            raise PoolError("this workflow permits development inputs only")
        if type(self.seed) is not int:
            raise PoolError("partition seed must be a strict integer")
        for value in (self.persona_id, self.scenario_template_id):
            nonempty(value, "partition identifier")
        if not isinstance(self.phrasing_family_ids, tuple) or len(set(self.phrasing_family_ids)) != len(
            self.phrasing_family_ids
        ):
            raise PoolError("phrasing families must be an immutable unique tuple")
        if self.consumer is not None and self.consumer not in CONSUMERS_BY_POOL["dev"]:
            raise PoolError("consumer is not authorized in the development pool; tier2_notes is pending")
        if self.phrasing_family_ids and self.consumer is None:
            raise PoolError("phrasing selection requires an explicit consumer")
        partition.assert_in_pool(
            "dev", seed=self.seed, personas=self.persona_id, scenario_templates=self.scenario_template_id,
            phrasing_families=self.phrasing_family_ids,
        )
        consumers = {item.id: item.consumer for item in partition.phrasing_families["dev"]}
        if any(consumers[item] != self.consumer for item in self.phrasing_family_ids):
            raise PoolError("phrasing family does not belong to the declared consumer")

    def to_dict(self, partition: Partition) -> dict[str, object]:
        self.validate(partition)
        return {
            "pool": self.pool, "seed": self.seed, "persona_id": self.persona_id,
            "scenario_template_id": self.scenario_template_id, "phrasing_family_ids": self.phrasing_family_ids,
            "consumer": self.consumer, "manifest_version": partition.manifest_version,
            "generator_model": GENERATOR_MODEL, "generator_version": GENERATOR_VERSION,
            "notes_mode": "omitted/no-authorized-dev-tier2-notes",
        }

    def to_json_bytes(self, partition: Partition) -> bytes:
        return json_bytes(self.to_dict(partition))


def select_development_inputs(
    partition: Partition, *, seed: int, scenario_template_ids: Sequence[str],
    persona_ids: Sequence[str] | None = None, consumer: str | None = None,
    phrasing_family_ids: Sequence[str] | None = None,
) -> tuple[DevelopmentProvenance, ...]:
    """Select unique pool seeds and rotate public IDs in stable sorted order.

    The requested seed is the first actual pool seed, not an arbitrary seed later
    relabeled as partitioned. No golden entries or descriptions are consulted.
    Phrasing selection is optional metadata; this function never renders text.
    """
    if not isinstance(partition, Partition):
        raise ValueError("the actual P1 Partition is required")
    if type(seed) is not int:
        raise PoolError("seed must be a strict integer")
    partition.assert_in_pool("dev", seed=seed)
    if isinstance(scenario_template_ids, str) or not scenario_template_ids:
        raise PoolError("an ordered nonempty template ID sequence is required")
    count(len(scenario_template_ids), "scenario count", 1)
    personas = partition.members("personas", "dev") if persona_ids is None else sorted(set(persona_ids))
    if isinstance(persona_ids, str) or not personas:
        raise PoolError("at least one development persona is required")
    if consumer is not None and consumer not in CONSUMERS_BY_POOL["dev"]:
        raise PoolError("consumer is not authorized in development")
    if isinstance(phrasing_family_ids, str):
        raise PoolError("phrasing IDs must be a sequence, not a string")
    phrasing = (
        sorted(item.id for item in partition.phrasing_families["dev"] if item.consumer == consumer)
        if phrasing_family_ids is None and consumer is not None else sorted(set(phrasing_family_ids or ()))
    )
    if consumer is not None and not phrasing:
        raise PoolError("no authorized phrasing family for the requested development consumer")
    partition.assert_in_pool("dev", personas=personas, scenario_templates=scenario_template_ids,
                             phrasing_families=phrasing)
    lo, hi = partition.seed_range("dev")
    if len(scenario_template_ids) > hi - lo + 1:
        raise PoolError("not enough distinct development seeds for this batch")
    selected = tuple(
        DevelopmentProvenance(
            lo + (seed - lo + index) % (hi - lo + 1), personas[index % len(personas)], template_id,
            (phrasing[index % len(phrasing)],) if phrasing else (), consumer,
        )
        for index, template_id in enumerate(scenario_template_ids)
    )
    for item in selected:
        item.validate(partition)
    return selected
