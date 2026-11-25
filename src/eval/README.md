# Evaluation harness (P2)

Scores extraction predictions against a gold file. It reads files only, so builders never need golden labels.
Standard library, `pydantic` and `pyyaml` only. Only `--task extraction` exists in v0.

## Usage

```
python -m src.eval.run --task extraction --pred preds.jsonl --gold gold.jsonl --out results/E3/<run_id>/eval/ \
    [--exercise-ids ids.json] [--slice-by stratum --slice-by hard_negative] [--cluster-by family] \
    [--resamples 2000] [--seed 0]

python -m src.eval.run --mode compare --pred a.jsonl --pred-b b.jsonl --gold gold.jsonl --out <dir> \
    [--cluster-by family]
```

Exit code 0 on success, 2 on invalid input or usage (message on stderr, nothing written). `--out` must be a separate
directory from the prediction run (the file names `config.yaml` and `run_manifest.json` collide). The run refuses if
`metrics.json`, `config.yaml` or `run_manifest.json` already exists there. Outputs are written all together or not at
all. The gold sha256 is printed on every run.

## File formats

Predictions (the F5 baseline format), one object per line:

```
{"item_id": "a1", "pred": {<seven label keys>} | null, "raw": "...", "error": null | "no_json" | "invalid_json" | "schema_error"}
```

Gold, one object per line: `{"item_id": "a1", "labels": {<seven label keys>}, ...}`. Other top-level keys (for example
`stratum`, `hard_negative`, `family`) are available to `--slice-by` and `--cluster-by`. Their values must be scalars.

`--exercise-ids` is a JSON list of ids or one id per line. The same membership check applies to gold labels (an error)
and to predictions (a failure).

Input rules (all are errors): empty file, malformed JSON line, duplicate JSON key in an object, `NaN`/`Infinity`, a line
that is not an object, missing `item_id` or `pred`, duplicate `item_id`, ids that differ between gold and predictions
(missing or extra), invalid gold `labels`, an unknown `error` code, a non-null `pred` together with an `error`. Blank
lines are skipped. A failed item must be written as `pred: null`. Error messages name file, line, `item_id` and field
names only, never input values.

Gold and `pred` are validated with `ExtractionResult` (not only the JSON Schema). Labels compare after validation, so
`80` and `80.0` are equal, and `load` is the pair (value, unit) with no conversion.

## Metrics

A prediction is a **failure** if `pred` is null or fails `ExtractionResult` revalidation. **JSON validity** is the share
of items with a non-null `pred` (even if it fails revalidation) or `error: schema_error`; a null `pred` with no error or
with `no_json` / `invalid_json` is not valid JSON. **Failure rate** is the share of failures. Both are secondary.

Field counts, per item and field:

| Gold | Prediction | Counts |
|---|---|---|
| value | same value | TP |
| value | other value | FP + FN |
| value | null or failure | FN |
| null | value | FP |
| null | null or failure | nothing |

Precision, recall and F1 are `null` when undefined, never 0 or 1. F1 is 0 when there are FP or FN but no TP.
**Micro** F1 pools TP/FP/FN over the 7 fields; **macro** F1 is the mean of the defined field F1 values (fields with no TP,
FP or FN are left out, with a warning). Reported blocks:

- `headline`: per field, micro and macro. Default values (`kinematic_observation: none`, `outcome: completed`,
  `exercise_id: unknown`) count as normal values.
- `default_as_null`: the same with default values treated as null on both gold and prediction.
- `majority_baseline`: headline metrics of predicting, for every item, the most frequent gold value of each field (null
  included; ties go to the smallest `repr`), scored by the same code.
- `triage`: confusion matrix (gold green/yellow/red by predicted green/yellow/red/failed); `red_recall` = red items
  predicted red / all gold red items (a failure is a miss; `null` with no red items) with a Wilson 95% interval;
  `green_fpr` = green items predicted yellow or red / all green items; `green_fpr_failsafe` also counts failures.
- `bootstrap`: 95% percentile intervals (default and minimum 2000 resamples, `random.Random(seed)`) for micro F1, macro
  F1, red recall and per-field F1. It resamples items, or whole clusters with `--cluster-by` (the number of clusters is
  reported, with a warning under 10; a missing or null cluster value is an error). A resample where a value is undefined
  is skipped for that value; `n_used` says how many resamples counted.
- `slices` (`--slice-by`, score mode): the metrics above per value of a gold field, without bootstrap. Null or missing is
  its own group. A group with fewer than 10 items reports only `n_items`. A field absent from every gold item is an error.

## Compare mode

`--mode compare --pred A --pred-b B` uses the same gold. It reports both models' metrics, the differences, and:

- `difference_point` and a paired bootstrap (the same resampled items or clusters for A and B) of **B - A** for micro F1,
  macro F1 and red recall.
- `mcnemar`: exact two-sided McNemar (`2 * P(X <= min(a, b))`, capped at 1, 1 with no discordant pairs) on correct versus
  incorrect per field (exact equality, null equals null, a failure is incorrect), for the fully correct item (all 7
  fields), and for red (predicted red, on gold red items). `a_only_correct` counts items only A gets right.

Any plain McNemar or paired-bootstrap p-value on pooled or clustered sets is an approximation (plan §3.5).

## Outputs

`metrics.json` (sorted keys, no NaN), `config.yaml` (the CLI arguments) and `run_manifest.json`. The manifest holds the
harness and schema versions, the git commit and dirty flag (any change, untracked files included; `null` if git is
unavailable), a freeze tag (the first tag at HEAD, alphabetically, whose name contains `golden` or `freeze`, else
`null`), sha256 of every input file (raw bytes), and `gold_is_golden` (the resolved gold path contains `data/golden`).
The manifest records and never blocks. No text, raw model output or per-item labels are written or printed.
