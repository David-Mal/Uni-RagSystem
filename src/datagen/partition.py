"""Loader for the partition manifest (issue P1, plan section 2.4 control 1). The only loader of ``partition.yaml``.

Seeds, personas, scenario templates and phrasing families are split into train, dev and golden pools before any data
is generated. Generators read pool membership only through this module. ``Partition`` keeps the method names of the
temporary ``PoolRegistry`` (``pool_of_seed``, ``pool_of``, ``members``, ``seed_range``, ``assert_in_pool``) so F3 and F4
can switch by changing imports. ``Partition.load`` and ``Partition.from_manifest`` are the constructors of
``PoolRegistry``, and ``PoolRegistry`` is an alias of ``Partition``.

Errors raise ``PoolError`` (a ``ValueError``). ``exercise_families`` is a flat list and is not pooled.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

Pool = Literal["train", "dev", "golden"]
POOLS: tuple[Pool, ...] = ("train", "dev", "golden")
Consumer = Literal["extractor", "classifier", "messages", "tier2_notes"]
CONSUMERS_BY_POOL: dict[str, frozenset[str]] = {
    "train": frozenset({"extractor", "classifier"}),
    "dev": frozenset({"extractor", "classifier"}),
    "golden": frozenset({"messages", "tier2_notes"}),
}
ID_SECTIONS: tuple[str, ...] = ("personas", "scenario_templates", "phrasing_families")
SECTION_PREFIX = {"personas": "ps", "scenario_templates": "st", "phrasing_families": "pf"}
POOL_CODE = {"train": "tr", "dev": "dev", "golden": "gd"}
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "partition.yaml"


class PoolError(ValueError):
    """Raised when an id or seed is unknown or in the wrong pool, or when the manifest is invalid."""


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    description: str


class Persona(_Entry):
    pass


class ScenarioTemplate(_Entry):
    """``category`` is recorded for train and dev only. Golden categories live in the restricted details (D5, D7)."""

    category: str | None = None


class PhrasingFamily(_Entry):
    consumer: Consumer


class Partition(BaseModel):
    """Validated partition manifest. Build it with ``load_partition`` or ``Partition.from_mapping``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: str
    seeds: dict[Pool, tuple[int, int]]
    personas: dict[Pool, list[Persona]]
    scenario_templates: dict[Pool, list[ScenarioTemplate]]
    phrasing_families: dict[Pool, list[PhrasingFamily]]
    exercise_families: list[str]

    @model_validator(mode="after")
    def _check(self) -> Partition:
        _check_seeds(self.seeds)
        sections: dict[str, dict[Pool, list[Any]]] = {s: getattr(self, s) for s in ID_SECTIONS}
        seen: dict[str, str] = {}
        for section, pools in sections.items():
            for pool in POOLS:
                if pool not in pools:
                    raise PoolError(f"{section}: missing pool {pool!r}")
            for pool, entries in pools.items():
                for entry in entries:
                    if entry.id in seen:
                        raise PoolError(f"{entry.id!r} appears twice: in {seen[entry.id]} and in {section}/{pool}")
                    seen[entry.id] = f"{section}/{pool}"
        for section, pools in sections.items():
            for pool, entries in pools.items():
                prefix = f"{SECTION_PREFIX[section]}_{POOL_CODE[pool]}_"
                for entry in entries:
                    if not entry.id.startswith(prefix):
                        raise PoolError(f"{section}/{pool}: id {entry.id!r} must start with {prefix!r}")
        for pool, entries in self.phrasing_families.items():
            for fam in entries:
                if fam.consumer not in CONSUMERS_BY_POOL[pool]:
                    raise PoolError(f"phrasing_families/{pool}: {fam.id!r} has illegal consumer {fam.consumer!r}")
        for pool, entries in self.scenario_templates.items():
            for tpl in entries:
                if (pool == "golden") != (tpl.category is None):
                    raise PoolError(f"scenario_templates/{pool}: {tpl.id!r} category must be set only outside golden")
        if len(set(self.exercise_families)) != len(self.exercise_families):
            raise PoolError("exercise_families has duplicates")
        return self

    # ---- queries (same names as PoolRegistry) ----

    def pool_of_seed(self, seed: int) -> str:
        """Return the pool whose inclusive seed range contains ``seed``; raise ``PoolError`` if none does."""
        for pool, (lo, hi) in self.seeds.items():
            if lo <= seed <= hi:
                return pool
        raise PoolError(f"seed {seed} is in no pool")

    def pool_of(self, section: str, item_id: str) -> str:
        """Return the pool of ``item_id`` in ``section``; raise if the section is not pooled or the id is unknown."""
        for pool, entries in self._section(section).items():
            if any(e.id == item_id for e in entries):
                return pool
        raise PoolError(f"{section}: {item_id!r} is not in the manifest")

    def members(self, section: str, pool: str) -> list[str]:
        """Sorted ids of ``section`` in ``pool``."""
        if pool not in POOLS:
            raise PoolError(f"unknown pool {pool!r}")
        return sorted(e.id for e in self._section(section)[pool])

    def seed_range(self, pool: str) -> tuple[int, int]:
        """Inclusive seed range of ``pool``."""
        if pool not in self.seeds:
            raise PoolError(f"no seed range for pool {pool!r}")
        return self.seeds[pool]

    def assert_in_pool(self, pool: str, *, seed: int | None = None, **section_ids: Iterable[str] | str) -> None:
        """Raise ``PoolError`` unless the seed and every given id belong to ``pool``.

        Example: ``p.assert_in_pool("train", seed=7, personas="ps_tr_novice_linear", phrasing_families=[...])``.
        """
        if seed is not None and (actual := self.pool_of_seed(seed)) != pool:
            raise PoolError(f"seed {seed} belongs to pool {actual!r}, not {pool!r}")
        for section, ids in section_ids.items():
            for item_id in [ids] if isinstance(ids, str) else ids:
                if (actual := self.pool_of(section, item_id)) != pool:
                    raise PoolError(f"{section}: {item_id!r} belongs to pool {actual!r}, not {pool!r}")

    def assert_pool(self, item_ids: Iterable[str] | str, pool: str) -> None:
        """Raise ``PoolError`` if an id is unknown or belongs to another pool. Ids are unique, so no section is needed."""
        if pool not in POOLS:
            raise PoolError(f"unknown pool {pool!r}")
        index = self._id_index()
        for item_id in [item_ids] if isinstance(item_ids, str) else item_ids:
            if item_id not in index:
                raise PoolError(f"{item_id!r} is not in the manifest")
            if (actual := index[item_id]) != pool:
                raise PoolError(f"{item_id!r} belongs to pool {actual!r}, not {pool!r}")

    # ---- construction ----

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Partition:
        """Validate a parsed manifest. Every failure is a ``PoolError``."""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise PoolError(f"invalid partition manifest: {exc}") from exc

    @classmethod
    def from_manifest(cls, data: Mapping[str, Any]) -> Partition:
        """``PoolRegistry`` name for ``from_mapping``. Only a complete manifest is accepted."""
        return cls.from_mapping(data)

    @classmethod
    def load(cls, path: Path | str) -> Partition:
        """``PoolRegistry`` name for reading a manifest file."""
        text = Path(path).read_text(encoding="utf-8")
        try:
            data = yaml.load(text, Loader=_UniqueKeyLoader) or {}
        except yaml.YAMLError as exc:
            raise PoolError(f"cannot parse {path}: {exc}") from exc
        return cls.from_mapping(data)

    # ---- internals ----

    def _section(self, section: str) -> dict[Pool, list[Any]]:
        if section not in ID_SECTIONS:
            raise PoolError(f"{section!r} is not a pooled section (expected one of {', '.join(ID_SECTIONS)})")
        return getattr(self, section)

    def _id_index(self) -> dict[str, str]:
        return {e.id: pool for s in ID_SECTIONS for pool, entries in self._section(s).items() for e in entries}


PoolRegistry = Partition
"""Name used by F3 and F4."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe loader that refuses a repeated key. Plain YAML silently keeps the last value."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[str] = set()
        for key_node, _ in node.value:
            if not isinstance(key_node, yaml.ScalarNode):
                continue
            if key_node.value in seen:
                raise PoolError(f"duplicate key {key_node.value!r} at line {key_node.start_mark.line + 1}")
            seen.add(key_node.value)
        return super().construct_mapping(node, deep=deep)


def _check_seeds(seeds: Mapping[str, tuple[int, int]]) -> None:
    for pool in POOLS:
        if pool not in seeds:
            raise PoolError(f"seeds: missing pool {pool!r}")
    ranges = sorted((lo, hi, pool) for pool, (lo, hi) in seeds.items())
    for lo, hi, pool in ranges:
        if lo > hi:
            raise PoolError(f"seed range for {pool} is empty: {lo}-{hi}")
    for (_lo1, hi1, p1), (lo2, _hi2, p2) in pairwise(ranges):
        if lo2 <= hi1:
            raise PoolError(f"seed ranges of {p1} and {p2} overlap")


def load_partition(path: Path | str | None = None) -> Partition:
    """Load and validate the manifest (default: ``data/manifests/partition.yaml``)."""
    return Partition.load(path if path is not None else DEFAULT_PATH)


@cache
def _default_partition() -> Partition:
    return load_partition()


def assert_pool(item_ids: Iterable[str] | str, pool: str, partition: Partition | None = None) -> None:
    """Raise ``PoolError`` if an id is unknown or belongs to another pool (uses the real manifest by default)."""
    (partition or _default_partition()).assert_pool(item_ids, pool)
