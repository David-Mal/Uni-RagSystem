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

## Leakage audit (P4)

Run by Patrick, locally, with the golden files at hand. The script needs the real embedding model
(`uv sync --group embed`, pulls in torch). Golden text never leaves the machine and never goes to an LLM session.

```
python scripts/leakage_audit.py \
  --train data/training/train.jsonl --train data/training/dev.jsonl --train data/training/red_dev.jsonl \
  --train data/training/triage_train.jsonl --train data/training/triage_dev.jsonl \
  --golden data/golden --manifest data/manifests/partition.yaml \
  --out-drop-ids data/manifests/drop_ids.txt --out-report docs/results/leakage_audit.md --round 1
```

`--golden` is repeatable and takes a JSONL file (`item_id`, `text`) or a directory (its `messages_*.jsonl`). The pool and
consumer expected for each training file come from its name (`train`, `dev`, `red_dev`, `triage_train`, `triage_dev`).

Each item is dropped for: exact duplicate, word 3-gram Jaccard >= 0.5, cosine >= 0.9 (all-MiniLM-L6-v2, pinned
revision) against golden, the same three against the guideline and plan examples (`reference_*`), or a manifest
violation (`compliance_*`). Outputs: `drop_ids.txt` (`<id>  # <reasons>`) and a counts-only report. Both are safe to
commit and to show to builders.

Fixed point: audit, then rebuild with `build_training.py` (F4) and `triage.py` (F8), which skip every id in
`drop_ids.txt` and take the next seed. Audit again with `--round N+1`. Repeat until a run with `--expect-clean` exits 0
(exit 1: this round drops new items, exit 2: input error). The drop list is cumulative: earlier ids stay in it,
because the builders regenerate the same ids from the same seeds. Commit the drop list, the report and the data of the
last, clean round.
