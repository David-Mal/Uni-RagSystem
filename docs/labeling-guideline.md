# Labeling guideline v0

Status: draft for Patrick's review. Fi1 / [issue #7](https://github.com/David-Mal/Uni-RagSystem/issues/7).
The human pilot and its agreement measurements are pending. This document does not
claim that Fi1 is complete.

## Sources and authority

- [Architecture plan](milestone2-architecture-and-plan.md): sections 2.2, 2.4-2.5,
  3.1-3.4, 5.3-5.8, 6.3 and 9.1.
- [RFC](../RFC_Heuristic_Load_Fatigue_Analyzer.md): section 3, especially goal 5.
- [F2 / issue #8](https://github.com/David-Mal/Uni-RagSystem/issues/8):
  the requested extraction types and enums.
- [F2 PR #69](https://github.com/David-Mal/Uni-RagSystem/pull/69), schema **v0**:
  `src/schemas/enums.py`, `models.py`, `json_schema.py` and exported schemas
  `schemas/extraction_result.json`, `load.json`, `claim.json` at commit
  `7f5e5b27fcff17164af5f52d08248bbe4d2d82a8` on
  `origin/feat/F2-schemas-enums`, inspected with read-only Git on **2026-11-25**.

F2 is available on that remote-tracking ref but **is not merged into this
checkout**. Its source contracts and exported JSON schemas were inspected without
checkout, merge or code execution. The table below now reflects that concrete
implementation; it does not introduce a competing schema. A pinned exercise
vocabulary and the annotation export envelope remain unavailable. Recheck the
contract when F2 is integrated or changes. Unsettled human policy decisions are
marked [TO VERIFY]; review markers are never extraction enum values.

## Independence and contamination controls

Filip George Bumbar and Patrick Marchis each author 125 of the 250 messages:
55 green, 30 yellow and 40 red. Each item receives an author-sealed intended label
and a second label assigned blind to that label and intended sampling class.
The matrix controls authoring, not what the second annotator sees.

Follow plan sections 2.4 and 3.1-3.2: separate training and golden phrasing families,
seeds and templates; never use held-out items for tuning. A third party
re-randomizes the at-least-20% subset both annotators label blind and removes
sealed labels. Builders do not adjudicate golden disagreements. Instructor
confirmation of the sealed-author-label protocol remains open.

Every illustrative message below is explicitly marked **guideline example**.
These examples are explanatory material only. Never copy, paraphrase or reuse
them in golden messages, the human pilot, training examples or generator prompts.
Do not use the guideline's examples as a source of golden phrasing families.

## Extraction fields and allowed values

Every message needs the full F2 extraction label, not triage alone
(plan section 3.3). Preserve what was reported; do not infer missing numbers,
canonical exercises or diagnoses. Distinguish F2's proposed conventional outcome
label below from evidence that a set physically succeeded.

| Field | F2 specification | Annotation rule and unresolved details |
|---|---|---|
| `exercise_id` | Required, non-null string matching `^[A-Za-z0-9_\-]+$`, or lowercase `unknown` | Use a confirmed canonical ID. Mixed-case versions of the reserved `unknown` sentinel are rejected. [TO VERIFY] pinned vocabulary, aliases and disambiguation rules with F2/D7. |
| `kinematic_observation` | Required, non-null: `none`, `slow_bar_speed`, `grinding_rep`, `reduced_range_of_motion`, `lost_balance`, `other` | Reported movement only, never a form diagnosis. [TO VERIFY] precedence for several observations and `none` versus `other` in ambiguous cases. |
| `load` | Required key; `Load` object or `null`. Object keys: finite numeric `value >= 0`, `unit` exactly `kg` or `lb` | Both object keys are required. Zero is allowed; no upper bound is defined. Preserve the reported unit, without conversion. [TO VERIFY] an explicit number without a unit and multiple loads. |
| `reps` | Required key; strict integer `>= 0` or `null` | Zero is valid; no upper bound is defined. Do not infer intended repetitions or accept a numeric string/float as an integer. Multi-set selection remains [TO VERIFY]. |
| `outcome` | Required, non-null: `completed`, `failed`, `partial`; no model default | F2 documents proposed definitions and an unreported-outcome convention below. The key must always be supplied explicitly. Human policy approval remains [TO VERIFY]. |
| `rpe` | Required key; finite strict numeric value in inclusive `[0, 10]`, or `null` | Fractional values are allowed. No rounding or inference from effort language; gym notation conventions remain [TO VERIFY]. |
| `triage_level` | Required, non-null: `green`, `yellow`, `red` | Assess the whole message using the definitions and scope rules below. |

All **seven keys are required**. Only `load`, `reps` and `rpe` may be `null`;
unreported values use explicit `null`, never an omitted key or a default zero.
`Load` and `ExtractionResult` reject additional properties. The actual Pydantic
validators reject booleans, numeric strings, infinities and NaN for numeric
fields. Integer JSON numbers are accepted for load/RPE floats; a floating-point
repetition value is rejected. These runtime details are not all captured by the
static JSON Schema alone. This guideline does not implement those validators.

Exercise IDs are case-sensitive and contain only ASCII letters, digits,
underscores and hyphens, with no whitespace. F2's runtime validator additionally
rejects `Unknown`, `UNKNOWN` and other case variants of `unknown`. With
`context={"exercise_ids": ids}`, every other ID must belong to that supplied
collection; lowercase `unknown` is always allowed. Without that context, F2
checks shape, not canonical membership. Its `extraction_json_schema(ids)` helper
restricts decoding to the supplied IDs plus `unknown`. The plain exported
`extraction_result.json` has the shape pattern, not a pinned vocabulary.

### Outcome and exercise selection: F2 proposals for human approval

F2 PR #69 explicitly describes the following **proposed annotation policies**;
they are docstring/schema-description conventions, not automatic defaults or
cross-field validators. Carry them into the Fi1 review rather than inventing a
different convention:

- `completed`: no failure or partial completion is reported, including when the
  note says nothing about outcome. This is a conventional extraction label,
  not proof of actual completion.
- `partial`: fewer repetitions than planned were completed.
- `failed`: the attempted repetition or set was not completed.
- For multiple exercises, select the exercise linked to the most severe reported
  symptom and keep its exercise/set fields together. With no symptom, or a tie,
  F2 proposes selecting the first exercise with set data. Use `unknown` if the
  selected exercise cannot be resolved; triage remains the maximum over the
  whole message. Never borrow another exercise's numbers to fill missing values.

Patrick and the F2/safety owners must confirm these policies before the human
pilot **[TO VERIFY]**, including overlapping failed/partial wording, tie cases,
symptoms without set data and multiple sets of one exercise. No AI-assigned pilot
labels are supplied here. An unresolved policy case stays in the human review
queue rather than receiving a new enum, `null` outcome or fabricated result.

The published kinematic values distinguish no reported observation, slow bar
speed, a grinding repetition, reduced range of motion, lost balance and another
reported observation. The exact policy for `none` versus `other` remains
[TO VERIFY]; neither is permission to infer movement quality.

An annotation identifier is metadata outside the strict extraction object, not
an eighth extraction field. Its name, type and nesting in the export envelope
remain [TO VERIFY] with the harness owner. `ExtractionResult.exercise_id` is
non-null; the separate `Claim.exercise_id` may be null and must not be confused
with it. F2 has one extraction object per message; no per-exercise array or
symptom-link field may be added locally.

## Safety classes and scope

| Class | Project definition | Expected gate effect |
|---|---|---|
| `green` | No symptoms | Normal analysis, subject to data sufficiency. |
| `yellow` | Mild discomfort, stiffness or persistent soreness | Exclude the affected exercise(s); use the fixed disclaimer. Continue only with sufficient eligible data. |
| `red` | Sharp pain, swelling, dizziness or chest pain | Block analysis and show only the fixed referral message. |

These are project annotation categories, not a diagnosis. Do not add symptom
severity scores, time cutoffs, new medical triggers or injury-risk thresholds.
For co-occurring symptoms, retain the most severe applicable class. The production
gate takes the maximum severity of its three signals per note, then per log
(plan section 5.3); the human label describes the message rather than imitating
a potentially mistaken rule or model prediction.

### Edge cases

| Case | Rule | Illustration |
|---|---|---|
| Figurative language | A clearly figurative effort expression alone does not establish a symptom. Literal or unclear pain still needs symptom assessment. | **guideline example:** "That set killed me." Green only when context clearly expresses effort without symptoms. |
| Negation | Negation applies to the symptom within its scope. A negated symptom does not cancel a separate positive symptom. | **guideline example:** "No pain today, just mild knee stiffness." Yellow because stiffness is still reported. |
| Past versus present | Keep timing explicit. Continuing symptoms count even if they began earlier. Clearly resolved history and unclear timing need the temporal policy below. | **guideline example:** "My shoulder hurt last month; it is fine now." Proposed current-symptom reading: green; temporal scope [TO VERIFY]. |
| A different exercise | Identify the symptomatic exercise. Use the F2 selection proposal above for review; do not transfer symptoms to the first exercise named. | **guideline example:** "Rows felt normal; my knee was stiff during squats." Yellow; the explicit symptom concerns squats. Policy approval is [TO VERIFY]. |
| Yellow/red boundary | Use explicit project triggers. Unqualified or intense pain wording without a clear trigger is unresolved, not a new severity threshold. Preserve uncertainty for adjudication. | **guideline example:** "My shoulder hurts badly." Yellow/red assignment [TO VERIFY]; do not force an unsupported label. |
| Slang, abbreviations and typos | Interpret only unambiguous wording; confirm aliases against the approved vocabulary. Unclear exercise identity becomes `unknown`, without downgrading an explicit symptom. | **guideline example:** "bnch: sharp shoulder pain." Red; an uncertain exercise mapping does not remove the sharp-pain report. |
| Multiple exercises | Assess all symptoms, then take the highest severity. Selection of the single exercise/set record follows the F2 proposal above, pending approval. | **guideline example:** "Squats were fine; pressing caused sharp shoulder pain." Red for the message. |
| Missing numbers | Keep all seven keys; unreported load, reps and RPE use `null`. The required outcome follows the proposed convention above, subject to human approval. | **guideline example:** "Rows felt smooth and symptom-free." Green; load, reps and RPE are unreported. |

Temporal window, historical red symptoms without an explicit resolution, and an
ambiguous yellow/red boundary are not fully defined by the plan. The example
interpretations above are v0 proposals [TO VERIFY] with Patrick and the safety/F2
owners before final labeling. Keep an unresolved item outside the finalized
label export until adjudicated; do not add `ambiguous` or `pending` to the enum.
Every red-versus-not-red disagreement must be adjudicated and logged even when
kappa exceeds 0.70. Review includes literal versus figurative interpretation and
the scope of negation.

For yellow linking, plan section 5.3 prioritizes the structured CSV exercise link,
then the extractor's `exercise_id`. Record an explicit different-exercise
reference for review if it conflicts with that order; do not silently override the
specified gate behavior. An unresolved workout-level yellow note excludes all
exercises in that workout. An unresolved yellow free-text message requests
clarification; non-interactive handling is insufficient data plus the disclaimer.
The plan's section 9.3 leaves the demo-front-end choice open [TO VERIFY].

## Log hypotheses and evidence

The following closed labels and primary evidence come directly from plan section
5.6. Several hypotheses can apply to a scenario. None is a diagnosis or proof of
causation.

| Hypothesis label | Primary evidence |
|---|---|
| `insufficient_weekly_volume` | Effective sets per muscle below a configurable band. |
| `fatigue_accumulation` | Upward RPE drift at comparable load. |
| `stagnant_load_progression` | Stagnant e1RM with stable working load. |
| `load_spike` | Acute load high relative to chronic load; a heuristic, never an injury claim. |
| `inconsistent_frequency` | Irregular sessions or gaps for the exercise or muscle. |
| `logging_quality_issue` | Missing RPE, mixed units, duplicates or implausible values. |
| `confounder_present` | Notes report sleep loss, illness or travel during the window. |

The three allowed evidence levels are `supported`, `weak` and `insufficient`.
F2 v0's `HypothesisLabel` and `EvidenceLevel` match the seven/three values above;
its `Claim` model does not define a full log-label envelope or an abstention
field. The plan does not define quantitative evidence boundaries. The following
readings require review [TO VERIFY]; they do not introduce scoring thresholds:

| Evidence level | Proposed operational reading [TO VERIFY] |
|---|---|
| `supported` | The specified primary evidence is present in sufficient eligible data, with traceable tool outputs supporting the claim. |
| `weak` | Relevant evidence exists but is limited or confounded; the limitation must be explicit. |
| `insufficient` | Available data cannot support that hypothesis; abstain from the affected claim or analysis. |

Indicator cutoffs, the final evidence rubric and how insufficient candidates are
serialized versus omitted need the relevant owners' specification. Do not invent
volume bands, trend cutoffs, confounder causality or citations. Numbers come from
deterministic tools or the separately specified independent reference, not an LLM.
Warm-up and failed sets do not contribute to e1RM. Plan section 2.2 defines failed
sets as zero repetitions or explicitly marked failed.

### Abstention rules

Abstention is an outcome, not an eighth hypothesis label. Log labels include
expected hypotheses with evidence levels, abstain yes/no with reasons, and the
gate outcome (plan section 3.4); their final export structure is [TO VERIFY].
F2's `GateLevel` is an alias of `TriageLevel` (`green`, `yellow`, `red`), not a
separate enum of gate actions or an abstention schema.

Apply plan section 5.5's precedence: unreadable input, red block, insufficient
data, yellow exclusions, then green analysis. Red referral must not be replaced by
a request for more data. Yellow exclusions can cause insufficiency.

Use the configurable defaults from plan section 2.5, subject to dev-only tuning
and freezing by their owner:

| Sufficiency check | Published default |
|---|---|
| History span | At least 5 weeks with data. |
| Exercise sessions | At least 4 sessions in the last 6 weeks after excluding warm-up and failed sets. |
| RPE drift eligibility | RPE on at least 50% of working sets and at least 4 sessions at comparable load (within 5%). |
| Gaps | No gap longer than 14 days in the analyzed window. |
| Exercise matching | At least one analyzed exercise resolved with high confidence, other than `unknown`. |

State the actual missing evidence. Abstain partially when only some analyses are
unavailable; abstain fully when none is supportable. Do not infer missing RPE,
loads or exercise identity. After verifier retry, abstain if no verified claim
survives (plan section 5.8). Numeric tolerances for verifier checks are not
annotation-agreement tolerances.

## Sampling matrix

[sampling_matrix.yaml](../data/golden/sampling_matrix.yaml) contains counts only:
250 messages, 110 green / 60 yellow / 80 red, split 125 per author.
It is a sparse joint matrix of safety class, exercise family, phrasing style and
primary trap. Unlisted combinations have a zero target in v0. Each cell is split
equally between Filip and Patrick. Secondary traps may overlap without counting
an item twice. Dedicated hard-negative cells occur within green and yellow.

Safety classes and required trap names are specified by Fi1 and the plan.
Exercise-family groupings, phrasing-style groupings, cell counts and hard-negative
quotas are proposed planning allocations [TO VERIFY] with Patrick, not F2 enums
or canonical exercise IDs. Check compatibility with the separate phrasing-family
partition manifest before authoring. Human real-note probe selection and its
quota are [TO VERIFY]; no quota is invented here.

The YAML file uses JSON syntax, a YAML 1.2 subset, so the count tests can read the
same file with Python's standard library without introducing a YAML dependency.
F2 v0 confirms the three safety values; the exercise/phrasing planning groups
are not F2 enums. All 30 populated joint cells retain their existing targets.
The dedicated hard-negative subset is **78 green + 42 yellow = 120** items
within the 250, split **39 green + 21 yellow = 60** per author. These are
existing proposed allocations, not additional quotas.

## Agreement script

Run [scripts/kappa.py](../scripts/kappa.py) only on independently assigned labels.
The caller explicitly maps the existing identifier and label locations using
JSON Pointers; no annotation envelope or identifier field name is prescribed.
For instance, this command assumes `id` metadata and a separate `labels` object
containing the seven extraction keys. The paths illustrate pointer mapping,
not a prescribed export schema; replace them with the agreed metadata/label
locations:

```powershell
python scripts/kappa.py filip-labels.jsonl patrick-labels.jsonl --id-pointer /id --field exercise_id=/labels/exercise_id --field kinematic_observation=/labels/kinematic_observation --field outcome=/labels/outcome --field triage_level=/labels/triage_level --json
```

Use Python 3.11; `uv run --python 3.11 python` may replace `python` once the team's
uv environment exists. This command is for humans to execute locally; it was not
run against pilot data during this work. Repeat `--field NAME=/pointer` for each
applicable categorical field. The four selectable names exactly match F2 v0's
categorical extraction fields. Their final designation as headline fields is
[TO VERIFY] with F2 and the evaluation owner. Do not silently omit a troublesome
field from the pilot report.

The script computes unweighted nominal Cohen's kappa by exact string agreement,
after matching items by identifier rather than line order:
`kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement)`.
It validates the selected non-null categorical enums and F2's exercise-ID shape,
including the lowercase-only `unknown` sentinel. No selected null/missing label
is silently omitted. Canonical ID membership still needs the pinned D7
vocabulary and F2's validation context [TO VERIFY].
The script accepts non-empty string or integer identifiers, with types kept
distinct. Confirm this operational identifier restriction with the export owner.

**A kappa report does not validate a complete extraction record.** Before export,
human operators must validate each seven-key extraction object with the actual
shared F2 model and pinned exercise-ID context once available; keep identifier
metadata outside that strict object. This utility does not reproduce F2's
numeric validators or import the unmerged branch. Its input checks do reject
duplicate JSON keys, malformed JSONL and non-finite JSON numbers.

Load/reps/RPE types, bounds and extraction nullability are now established by
F2. Their **agreement scoring** (tolerances, unit equivalence and null comparisons)
is a separate policy [TO VERIFY]. Multi-exercise/set selection still needs human
approval. The utility does not invent numeric bins, weighted kappa or a pooled
kappa across unrelated fields. Plan section 3.1's overall agreement definition
also requires coordination; no artificial overall statistic is reported.

The output reports sample count, observed and expected agreement, kappa and the
0.70 threshold per selected field. Red-versus-not-red disagreements are counted
separately and always require adjudication. Expected agreement of one makes
kappa undefined, including identical single-class labels; it is never reported
as perfect kappa. An undefined field requires human review.

Exit codes: 0 when every selected field reaches 0.70 and no red disagreement
requires adjudication; 1 when agreement is below threshold, undefined, or a red
disagreement needs review; 2 for invalid input or arguments. `--json` emits the
same report as JSON. Original independent labels must be retained for reporting;
agreement is measured before adjudication, not on reconciled labels.

### Technical validation, not pilot agreement

On **2026-11-25**, the complete Fi1 test suite passed with Python **3.11.18** and
pytest **9.2.0**: **42 tests and 103 subtests passed**. Pytest was installed only
in an isolated temporary uv environment; no permanent dependency was added.
With that environment active, the command was:

```powershell
uv run --no-project --active --offline python -B -m pytest tests/test_kappa.py tests/test_sampling_matrix.py -q -p no:cacheprovider --confcutdir=tests --basetemp "$fi1TestTemp\pytest-tmp"
```

`$fi1TestTemp` denotes that temporary run directory. Tests use synthetic label
fixtures without message text and the authorized count-only matrix. The F2
conformance tests read only the pinned `schemas/extraction_result.json` blob
through `git show`; they never execute F2 code or fetch branches. Those two
checks explicitly skip if the pinned Git object is unavailable elsewhere; both
ran successfully in this checkout. The remaining tests do not depend on F2.
The 250 allocation targets and all 30 cells were verified unchanged.

## Human pilot and review procedure

1. Patrick reviews this guideline and the proposed matrix. Confirm the F2 outcome
   and exercise-selection proposals, remaining ambiguity rubric, pinned exercise
   IDs, export pointers and headline fields. Agree the pilot class allocation;
   the 250-message targets do not prescribe a new 20-item class quota.
2. Filip and Patrick each author **10 new human-only items**. Store actual pilot
   items only in restricted `data/golden/pilot/`. Reuse neither guideline examples
   nor AI-written messages. Keep pilot items outside the 250 unless the team
   explicitly decides otherwise.
3. Seal each author's intended full seven-key labels. Give the other annotator
   randomized items with stable identifiers, hiding sealed labels, intended
   class and sampling hints. Do not expose one person's labels to the other
   before both submissions are locked. Plan section 3.2 additionally requires a
   third party to re-randomize an at-least-20% subset for both to label blind
   (at least 4 of 20 if applied to this pilot); confirm the subset procedure and
   sealed-author protocol with the instructor [TO VERIFY].
4. Each comparison JSONL must contain labels for the **same 20 identifiers**.
   Assemble each annotator's own sealed labels and blind labels for the other's
   items; do not compare two disjoint 10-item author files. Retain original
   independent submissions. Validate full extraction objects with F2 separately;
   message text is unnecessary in the files supplied to kappa.
5. Humans run the command above locally, adjusting pointers to the agreed
   envelope. Save pre-adjudication per-field results and sample sizes. Measure
   the separately blind subset separately. A single-class field has undefined
   kappa even with exact agreement; investigate instead of treating it as a pass.
6. If any headline kappa is below **0.70**, revise the guideline and re-label the
   affected subset. Adjudicate and log every red-versus-not-red disagreement
   regardless of kappa. Record disagreements, policy decisions, revisions and
   repeat measurements without replacing the original agreement report.
   Follow the human freeze procedure only after review and actual measurements;
   no Git operations or pilot-data access are part of this AI-assisted work.

## Pilot results

**Status: pending.** No actual pilot messages were created, inspected or labeled
during this work, and no human agreement measurement is available.

| Required record | Current status |
|---|---|
| 10 human-authored items from Filip | Pending human authoring. |
| 10 human-authored items from Patrick | Pending human authoring. |
| Independent labels and agreed headline fields | Pending. |
| Per-field kappa and sample sizes | Pending; synthetic test results are not pilot results. |
| Red-versus-not-red adjudication log | Pending. |
| Guideline revisions based on pilot findings | Pending; no findings fabricated. |
| Patrick's guideline and matrix review | Pending. |

Fi1 remains open until the human pilot, any required revisions and Patrick's
review are available.
