"""Read-only view of the partition manifest used by the generators (issues F3, F4, F8; manifest from P1).

P1 (#6) owns ``data/manifests/partition.yaml`` and ``src/datagen/partition.py``. Until it lands, generators depend
only on this small view: which pool a seed, persona or phrasing family belongs to. ``PoolRegistry.from_manifest``
accepts the structure described in issue P1 and tolerates a few spellings:

    seeds:             {train: [1, 9999] | "1-9999" | {start: 1, end: 9999}, golden: ..., dev: ...}
    personas:          {train: [id, ...] | [{id: ..., description: ...}, ...], golden: ..., dev: ...}
    phrasing_families: same as personas

When P1 merges, adapt ``from_manifest`` (or build the registry from its ``Partition``) and keep this interface.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import yaml

Pool = Literal["train", "golden", "dev"]
POOLS: tuple[Pool, ...] = ("train", "golden", "dev")
ID_SECTIONS: tuple[str, ...] = ("personas", "phrasing_families", "scenario_templates", "exercise_families")


class PoolError(ValueError):
    """Raised when an id is unknown, in the wrong pool, or when pools overlap."""


@dataclass(frozen=True)
class PoolRegistry:
    """Pool membership of seeds and ids. Pools must be disjoint."""

    seed_ranges: Mapping[str, tuple[int, int]]
    ids: Mapping[str, Mapping[str, frozenset[str]]] = field(default_factory=dict)
    """section -> pool -> ids"""

    def __post_init__(self) -> None:
        ranges = sorted((lo, hi, pool) for pool, (lo, hi) in self.seed_ranges.items())
        for lo, hi, pool in ranges:
            if lo > hi:
                raise PoolError(f"seed range for {pool} is empty: {lo}-{hi}")
        for (_lo1, hi1, p1), (lo2, _hi2, p2) in pairwise(ranges):
            if lo2 <= hi1:
                raise PoolError(f"seed ranges of {p1} and {p2} overlap")
        for section, pools in self.ids.items():
            seen: dict[str, str] = {}
            for pool, members in pools.items():
                for item in members:
                    if item in seen:
                        raise PoolError(f"{section}: {item!r} is in both {seen[item]} and {pool}")
                    seen[item] = pool

    # ---- queries ----

    def pool_of_seed(self, seed: int) -> str:
        """Return the pool whose seed range contains ``seed``; raise ``PoolError`` if none does."""
        for pool, (lo, hi) in self.seed_ranges.items():
            if lo <= seed <= hi:
                return pool
        raise PoolError(f"seed {seed} is in no pool")

    def pool_of(self, section: str, item_id: str) -> str:
        """Return the pool of ``item_id`` in ``section`` (e.g. ``phrasing_families``); raise if unknown."""
        for pool, members in self.ids.get(section, {}).items():
            if item_id in members:
                return pool
        raise PoolError(f"{section}: {item_id!r} is not in the manifest")

    def members(self, section: str, pool: str) -> list[str]:
        """Sorted ids of ``section`` in ``pool``."""
        return sorted(self.ids.get(section, {}).get(pool, frozenset()))

    def seed_range(self, pool: str) -> tuple[int, int]:
        """Inclusive seed range of ``pool``."""
        if pool not in self.seed_ranges:
            raise PoolError(f"no seed range for pool {pool!r}")
        return self.seed_ranges[pool]

    def assert_in_pool(self, pool: str, *, seed: int | None = None, **section_ids: Iterable[str] | str) -> None:
        """Raise ``PoolError`` unless the seed and every given id belong to ``pool``.

        Example: ``registry.assert_in_pool("train", seed=7, personas="p_t01", phrasing_families=["pf_a"])``.
        """
        if seed is not None and (actual := self.pool_of_seed(seed)) != pool:
            raise PoolError(f"seed {seed} belongs to pool {actual!r}, not {pool!r}")
        for section, ids in section_ids.items():
            for item_id in [ids] if isinstance(ids, str) else ids:
                if (actual := self.pool_of(section, item_id)) != pool:
                    raise PoolError(f"{section}: {item_id!r} belongs to pool {actual!r}, not {pool!r}")

    # ---- construction ----

    @classmethod
    def from_manifest(cls, data: Mapping[str, Any]) -> PoolRegistry:
        """Build a registry from a parsed partition manifest (see module docstring for accepted shapes)."""
        seeds = {pool: _parse_range(spec) for pool, spec in (data.get("seeds") or {}).items()}
        ids = {
            section: {pool: frozenset(_parse_ids(spec)) for pool, spec in (data.get(section) or {}).items()}
            for section in ID_SECTIONS
            if section in data
        }
        return cls(seed_ranges=seeds, ids=ids)

    @classmethod
    def load(cls, path: Path) -> PoolRegistry:
        """Load a partition manifest YAML file."""
        return cls.from_manifest(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def _parse_range(spec: Any) -> tuple[int, int]:
    if isinstance(spec, str) and "-" in spec:
        lo, hi = spec.split("-", 1)
        return int(lo), int(hi)
    if isinstance(spec, Mapping):
        return int(spec["start"]), int(spec["end"])
    if isinstance(spec, list | tuple) and len(spec) == 2:
        return int(spec[0]), int(spec[1])
    raise PoolError(f"cannot parse seed range {spec!r}")


def _parse_ids(spec: Any) -> list[str]:
    if isinstance(spec, Mapping):  # {id: description}
        return [str(k) for k in spec]
    out: list[str] = []
    for entry in spec or []:
        out.append(str(entry["id"]) if isinstance(entry, Mapping) else str(entry))
    return out
