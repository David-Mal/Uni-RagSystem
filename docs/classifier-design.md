# Triage classifier: data and design

Issue F8 (#31). Review: David, against the gate interface (D9, #14). Training happens in week 10. This document,
the data tooling and the training skeleton are week 9.

## 1. Role in the gate

The safety gate takes the maximum severity of three signals: the rules, this classifier and the extractor's
`triage_level` (plan §5.3). The classifier is the second model signal. It exists to **decorrelate errors** from the
extractor, so it is trained separately, on a model of the **other family**, with its own phrasing families.

## 2. Model choice rule (plan §6.4)

| Extractor chosen after E3 | Classifier |
|---|---|
| `Qwen/Qwen3-1.7B` | `meta-llama/Llama-3.2-1B-Instruct` (gated: accept the Llama 3.2 Community License on Hugging Face; license card `[TO VERIFY]`) |
| `meta-llama/Llama-3.2-3B-Instruct` | `Qwen/Qwen3-1.7B` (Apache-2.0 `[TO VERIFY card]`) |

The ablation "same model, different prompt" is reported in E4 but not shipped.

## 3. Task, input and labels

- **3-way sequence classification**: `AutoModelForSequenceClassification` with `num_labels=3` and a LoRA adapter
  (PEFT `TaskType.SEQ_CLS`, so the classification head is trained fully).
- **Input**: a single note *or* a single free-text message, raw text with no prompt template, truncated at 128
  tokens. One note is one call. The gate calls the classifier once per note, plus once for the user message.
- **Label mapping (fixed)**: `green = 0`, `yellow = 1`, `red = 2`. These are the `TriageLevel` values from
  `src/schemas`, and the mapping is constant in `src/datagen/triage.py` and `src/training/train_classifier.py`.
- **Decision rule**: argmax by default. If dev shows red recall below target, use a threshold rule instead: predict
  `red` if `p(red) >= tau_red`, else `yellow` if `p(yellow) >= tau_yellow`, else `green`. `tau_red` is tuned on
  `triage_dev` + `red_dev` for red recall >= 0.95, then frozen before any golden run `[SET in week 10]`.

## 4. Data (`src/datagen/triage.py`)

| File | Pool | Size (default) | Classes |
|---|---|---|---|
| `data/training/triage_train.jsonl` | train | 1500 | 35 / 30 / 35% green / yellow / red |
| `data/training/triage_dev.jsonl` | dev | 300 | same |

- Each item holds `item_id` (`tc-…`), `text`, `label`, `label_id`, `task: triage`, plus the manifest fields
  `pool, persona_id, phrasing_family, hard_negative, seed, generator, generator_model, generator_version,
  paraphraser, schema_version`.
- **Its own phrasing families**, disjoint from the extractor's. Families carry `task="triage"` and the extractor
  generator can never pick them. A test enforces this.

  | Id | Pool | Style |
  |---|---|---|
  | `pf_tr_cls_short_note` | train | short lowercase note |
  | `pf_tr_cls_coach_checkin` | train | check-in message to a coach |
  | `pf_tr_cls_set_comment` | train | bracketed per-set comment |
  | `pf_tr_cls_hn_effort` | train | hard negatives (figurative or negated) |
  | `pf_dev_cls_voice_memo` | dev | transcribed voice memo |
  | `pf_dev_cls_hn_memo` | dev | hard negatives, voice memo style |

  **Manifest (P1):** these ids belong in the train and dev pools of `phrasing_families`. They should be marked as
  classifier families, e.g. with a `classifier:` sub-list or a `task` field, so the split is documented in the
  manifest itself.
- **Seeds**: triage train starts at `train_start + 5000` and triage dev at `dev_start + 500`. Extractor data (F4)
  uses the beginning of both ranges, so no seed is shared.
- Texts are deduplicated (normalized) within and across the two splits. Leakage-audit drop ids (P4) are removed.
- Same labeling conventions as the extractor data (`docs/datagen-messages.md`). They must agree with the Fi1
  guideline `[TO VERIFY with Fi1]`.

## 5. Metrics (priority order)

1. **Red recall** on `triage_dev` ∪ `red_dev`, with a Wilson 95% interval. A missed red is the costly error.
2. **Green false-positive rate**: the share of green notes flagged yellow or red (needless exclusions).
3. Per-class F1, macro F1, accuracy and the confusion matrix (`src/training/triage_metrics.py`).

Golden data is never used for training, tuning or threshold selection. E4 scores the frozen classifier once on
golden (week 12).

## 6. Training hyperparameters (proposal, `configs/classifier_smoke.yaml`)

LoRA r = 16, alpha = 32, dropout 0.05 on `q,k,v,o,gate,up,down` projections. lr 2e-4, 3 epochs, batch 16,
max length 128, fp16, seed 13. A 1B model with LoRA at length 128 fits easily on a 16 GB Colab/Kaggle GPU, and
locally on 4 GB with batch 4 + gradient accumulation `[TO VERIFY in week 10]`. Early stopping and checkpoint
selection use dev red recall, then macro F1.

## 7. How the gate calls it (D9 interface)

```python
class ClassifierSignal:                      # implements D9's ModelSignal protocol
    def assess(self, text: str) -> TriageLevel:   # may raise
        ...                                   # tokenize (max 128), forward pass, decision rule above
```

- **Timeout**: one forward pass per note. The timeout is `[SET]` after E8 latency (proposal: 2 s on GPU, 10 s on
  CPU). A timeout or exception raises inside `assess`.
- **Failure policy** (plan §5.3, owned by D9): a raised error marks the signal as failed for that note. The note's
  level is raised to at least `yellow` and logged as `unassessed_by_model`. A technical failure alone never produces
  `red`. The classifier itself never swallows errors and never returns a default level.
- The adapter is loaded once per process. The base model and adapter hashes are recorded in the run manifest.

## 8. Skeleton and smoke test

`python -m src.training.train_classifier --config configs/classifier_smoke.yaml --smoke` loads 50 stratified items,
LoRA-wraps the model, trains a few steps, evaluates on 30 dev items, and writes `metrics.json`, `config.yaml` and
`run_manifest.json` (library versions, GPU, peak memory, data sha256) under `results/E4/classifier_smoke/<run_id>/`.
`--model` overrides the base model, e.g. with a tiny model for a pipeline-only check.
