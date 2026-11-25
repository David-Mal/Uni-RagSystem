# Partition manifest

`partition.yaml` is the single source of truth for which seeds, personas, scenario templates and phrasing families
belong to the **train**, **dev** or **golden** pool (plan section 2.4, control 1). The split is fixed before any data is
generated. The only loader is `src/datagen/partition.py`.

## Contents

| Section | Pooled | Notes |
|---|---|---|
| `seeds` | yes | Inclusive `[first, last]`: train 1-9999, dev 20000-20999, golden 100000-100999. No sub-ranges. |
| `personas` | yes | Ids `ps_<pool>_<name>`. |
| `scenario_templates` | yes | Ids `st_<pool>_<name>`. A template is a cause x parameter variant. Train and dev record a `category`. |
| `phrasing_families` | yes | Ids `pf_<pool>_<name>`. Each has a `consumer`. |
| `exercise_families` | no | Flat list shared by every pool. |

Pool codes in ids: `tr` (train), `dev`, `gd` (golden). Ids are unique across the whole manifest.

`consumer` values: `extractor` and `classifier` (train, dev); `messages` and `tier2_notes` (golden only).
The classifier (F8) uses only `consumer: classifier` families.

Golden entries are opaque (`pf_gd_01`, "golden phrasing family 1"). They carry no style content and no category. The
hand-written descriptions live in `data/golden/partition_details.yaml` on the golden branches until the freeze, not on
`main`.

## How generators must read it

```python
from src.datagen.partition import load_partition, assert_pool

partition = load_partition()
lo, hi = partition.seed_range("train")
families = partition.members("phrasing_families", "train")   # filter by consumer on partition.phrasing_families["train"]

# before making an item:
partition.assert_in_pool("train", seed=seed, personas=persona_id, phrasing_families=family_id)
assert_pool([persona_id, family_id], "train")                # same check by id only, no section needed
```

F3 and F4 can import `PoolRegistry` from this module instead of `registry.py`: it is an alias of `Partition`, with the
same `load` and `from_manifest`. Both accept only a complete manifest, not the partial ones the old registry tolerated.

- Never hard-code ids or seed ranges. Read them from the manifest.
- Check every seed, persona, template and family against the pool you are generating for **before** making the item.
  A wrong pool or an unknown id raises `PoolError` (a `ValueError`). Do not catch it.
- Training generators never request the golden pool.
- An item is identified by `(generator, seed)`.

## What every item records

Every generated item records:

| Field | Value |
|---|---|
| `pool` | `train`, `dev` or `golden` |
| `persona_id` | from the manifest, same pool |
| `phrasing_family` | from the manifest, same pool |
| `seed` | integer inside the pool's range |
| `generator_model` | model or generator name |
| `generator_version` | version string |

Log scenarios also record their scenario template id (`scenario_template_id`).

Human-written golden items use `seed: null`, `generator_model: human` and `generator_version: null`.

## Append-only (D11)

After merge, an id never changes pool, is never removed and is never reused. Adding an entry needs a new
`manifest_version` and a reviewed PR. The `partition-v1` tag marks the first merged version. This rule is documented
only and is not enforced in code.
