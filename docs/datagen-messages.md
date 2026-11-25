# Training message generator (template-v0)

Issue F3 (#26). Code: `src/datagen/messages.py`, `families.py`, `vocab.py`, `registry.py`.
It generates synthetic messages labeled with the full `ExtractionResult` (schema v0) for the extractor and the triage
signal. **Training and dev pools only.** It never reads, writes or imitates golden data.

## Leakage controls (plan §2.4)

| Control | How the generator enforces it |
|---|---|
| 1. Disjoint generation inputs | Every seed, persona and phrasing family is checked against the partition manifest (P1) before an item is made. A golden-pool seed, persona or family raises `PoolError`, as does asking for the golden pool. |
| 2. Clean prompts | v0 is template-only, with no LLM. The optional `Paraphraser` interface states that prompts must never contain golden or guideline examples. |
| 3. Split by phrasing family | Each family is a whole style (one render function). Train families (`pf_tr_*`) and dev families (`pf_dev_*`) are disjoint, and the manifest decides their pool. |
| 6. Generator recorded | Each item stores `generator`, `generator_model`, `generator_version` and `paraphraser`. |

`write_jsonl` refuses any output path inside a `golden` directory.

## Item format (JSONL, one object per line)

```
item_id            tm-<pool>-<seed:06d>
text               the message
labels             ExtractionResult as JSON (exercise_id, kinematic_observation, load, reps, outcome, rpe, triage_level)
pool               train | dev
persona_id         from the manifest, same pool
phrasing_family    from the manifest, same pool
hard_negative      null | figurative | negated
seed               the item's seed (inside the pool's seed range); output is byte-identical for the same seeds
generator          template-v0   (generator_model: template, generator_version: v0)
paraphraser        null, or the paraphrasing model id + version
schema_version     v0
```

## Proposed phrasing families (for the P1 manifest)

These ids must be in the manifest's **train** and **dev** pools respectively. They must never be in golden.

| Id | Pool | Style |
|---|---|---|
| `pf_tr_terse_log` | train | terse gym-log shorthand, comma separated |
| `pf_tr_formal_sentence` | train | complete formal sentences |
| `pf_tr_abbrev_heavy` | train | abbreviation-heavy, slash separated |
| `pf_tr_emoji_typos` | train | lowercase with typos and a trailing emoji |
| `pf_tr_story_style` | train | short story with an opener sentence |
| `pf_tr_lowercase_runon` | train | lowercase run-on, no punctuation |
| `pf_tr_question_style` | train | report followed by a question |
| `pf_tr_bullet_log` | train | markdown bullet list |
| `pf_tr_numbers_first` | train | numbers first, then exercise |
| `pf_tr_coach_report` | train | third-person structured session note |
| `pf_tr_hn_figurative` | train | hard negatives: hyperbole about effort, exclamations (own renderer) |
| `pf_tr_hn_negated` | train | hard negatives: explicit negation of pain, status update (own renderer) |
| `pf_dev_gym_chat` | dev | chatty gym-buddy message |
| `pf_dev_caps_terse` | dev | all caps, dash separated |
| `pf_dev_diary` | dev | diary entry with a weekday |
| `pf_dev_hn_mixed` | dev | hard negatives (figurative or negated), texting style (own renderer) |

If P1 uses other ids, map them here, or rename the keys in `families.py`. The generator reads the pool from the
manifest, never from this table.

## Labeling conventions used by the generator

These are made by construction and must agree with the labeling guideline (Fi1, #7) `[TO VERIFY with Fi1]`:

- **Triage.** `green`: no symptom, a positive remark, figurative effort language ("legs are dead after that") or an
  explicit negation ("pain free today"). `yellow`: mild discomfort, ache, stiffness, tightness, a twinge, or soreness that
  persists for days. `red`: sharp or stabbing pain, swelling, a pop or snap with pain, numbness or tingling,
  dizziness or fainting, chest pain or tightness. A **yellow hard negative** is a negated red cue plus a real mild
  symptom ("no sharp pain, just a bit of stiffness in my knee") or figurative language plus a real mild symptom.
  **Red with a distractor**: 15% of red items put a negated mild symptom or figurative effort before the real red
  symptom ("legs are dead after that, but stabbing pain in my shoulder"), so negation never means "not red".
- **Outcome** (never null; definition agreed in the #69 review). `completed`: no failure or partial completion is
  reported. `partial`: fewer reps than planned, and `reps` = reps completed ("managed 2 out of 3" gives `reps=2`).
  `failed`: the attempted rep was not completed. The text gives no count, so `reps` is `null` (a missing number is not
  zero), `rpe` is `null` or `10`, and the kinematic observation is never `grinding_rep`.
- **No contradictions.** Positive remarks ("moved well", "felt strong") appear only on completed sets with no
  kinematic observation. A rep number in a figurative clause ("dying by rep five") always equals the labeled `reps`.
- **Load.** Labeled only when the text states it, always with a unit. The value and unit are as written: 225 lbs stays
  `{"value": 225, "unit": "lb"}`. Dumbbell loads are as written (usually per hand). Bodyweight exercises carry no
  load.
- **RPE.** Labeled only when stated (`@8`, `RPE 8`, `felt like an 8`), with 0.5 steps.
- **Exercise.** A known alias gives its free-exercise-db id. A vague phrase ("the new machine") or no exercise at all
  gives `unknown`.
- **Kinematic observation.** Labeled only from what the user says: slow bar speed, a grind, shortened range of
  motion, lost balance, other (grip slipped, bar drifted, setup felt different). This is never a form diagnosis.

## Held-out dev vocabulary and blocked wording

`vocab.CLAUSES` holds one clause vocabulary per pool (symptoms, systemic red cues, positive remarks, figurative,
negated, negated-red-plus-mild, red distractors, kinematic and outcome phrases). **Train and dev share no phrase**, so
dev scores and gate rules tuned on `red_dev` are not inflated by phrases seen in training. A test enforces this.
No phrase reuses wording from the plan's examples (§3.3) or the labeling guideline's examples (Fi1). A test checks word
3-gram overlap against both.

## Sampling (template-v0 defaults, constants in `messages.py`)

unknown exercise 10% · load present 85% (lb 25%) · reps present 85% · RPE present 45% ·
outcome completed/partial/failed 80/10/10% · kinematic `none` 55% · red systemic (dizziness/chest) 30% of red ·
hard negatives 25% of green, 15% of yellow, never red · red distractor 15% of red.
Loads come from per-exercise working ranges scaled by a persona multiplier in [0.6, 1.3]. The multiplier is derived
deterministically from the persona id, because personas carry no numeric fields.

Sample run (stub manifest, 3000 train / 300 dev, 35/30/35): 0 plan or guideline phrases; 161 of 1050 red items with a
distractor; 205 figurative and 201 negated hard negatives; 0 positive remarks on failed, partial or kinematic items;
0 failed items with a rep count or a grind; 0 rep-number mismatches.

## Usage

```
python -m src.datagen.messages --manifest data/manifests/partition.yaml --pool train --per-class 100 \
    --out data/training/sample.jsonl
```

Until P1 is merged, `tests/data/datagen/partition_stub.yaml` (test only, placeholder golden ids) can be passed as
`--manifest`.

## Known limits

- The style variety is bounded by 12 train templates. F4 adds dedup, and an optional paraphrase pass can add variety
  later, behind `Paraphraser` and recorded per item.
- English only. The real-note probe (F1) found real notes in Romanian or mixed language ("lbs nu kg"), so the gap is
  measured by the real-note slice.
