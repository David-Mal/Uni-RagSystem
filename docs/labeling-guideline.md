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

The checkout currently contains no F2 implementation, exported JSON Schema,
exercise vocabulary loader or annotation export contract. The table below records
the F2 issue's specification; it does not define a competing Pydantic schema.
Confirm it against F2 when available. Unsettled decisions are marked [TO VERIFY].
Do not put review markers into extraction fields as new enum values.

## Independence and contamination controls

Filip George Bumbar and Patrick Marchis each author 125 of the 250 messages:
55 green, 30 yellow and 40 red. Each item receives an author-sealed intended label
and a second label assigned blind to that label and intended sampling class.
The matrix controls authoring, not what the second annotator sees.

Follow plan sections 2.4 and 3.1-3.2: separate training and golden phrasing families,
seeds and templates; never use held-out items for tuning. A third party
re-randomizes the approximately 20% subset both annotators label blind and removes
sealed labels. Builders do not adjudicate golden disagreements. Instructor
confirmation of the sealed-author-label protocol remains open.

Every illustrative message below is explicitly marked **guideline example**.
These examples are explanatory material only. Never copy, paraphrase or reuse
them in golden messages, the human pilot, training examples or generator prompts.
Do not use the guideline's examples as a source of golden phrasing families.

## Extraction fields and allowed values

Every message needs the full F2 extraction label, not triage alone
(plan section 3.3). Preserve what was reported; do not infer missing numbers,
canonical exercises, diagnoses or a successful outcome.

| Field | F2 specification | Annotation rule and unresolved details |
|---|---|---|
| `exercise_id` | String from the free-exercise-db loader's IDs, or `unknown` | Use a confirmed canonical ID. Do not manufacture an ID from a name or abbreviation. [TO VERIFY] pinned vocabulary, aliases and disambiguation rules with F2 and D7. |
| `kinematic_observation` | `none`, `slow_bar_speed`, `grinding_rep`, `reduced_range_of_motion`, `lost_balance`, `other` | These describe what the user reported, never a form diagnosis. [TO VERIFY] precedence when several observations occur and missing/ambiguous observation handling. |
| `load` | `Load(value: float, unit: Literal['kg', 'lb'])` or `None` | Record the reported value and explicit unit; no guessed unit or conversion in the label. [TO VERIFY] how to represent a number with an omitted unit and multiple loads. |
| `reps` | `int` or `None` | Use an explicit count; do not infer intended repetitions. F2 does not yet specify additional bounds or multi-set representation. |
| `outcome` | `completed`, `failed`, `partial` | Preserve an explicit outcome. [TO VERIFY] the failed/partial boundary and what to do when outcome is unreported; F2's requested field is not nullable. Do not default it to completed. |
| `rpe` | `float` or `None`, range 0-10 | Use an explicit RPE, including an unambiguous gym notation only after its convention is confirmed. Do not infer RPE from effort language. |
| `triage_level` | `green`, `yellow`, `red` | Label symptoms using the definitions and scope rules below. |

The published kinematic values distinguish no reported observation, slow bar
speed, a grinding repetition, reduced range of motion, lost balance and another
reported observation. The exact policy for `none` versus `other` remains
[TO VERIFY]; neither is permission to infer movement quality.

An annotation identifier is metadata, not an extra extraction field. Its name,
type, nesting and relationship to any label envelope are [TO VERIFY] with F2 and
the evaluation harness. Multi-exercise cardinality and symptom-to-exercise links
also need coordination: the requested F2 model contains a single `exercise_id`.

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
| A different exercise | Identify the symptomatic exercise separately from the exercise being discussed. Do not transfer symptoms simply to the first exercise named. | **guideline example:** "Rows felt normal; my knee was stiff during squats." Yellow; the explicit symptom concerns squats. Multi-exercise serialization is [TO VERIFY]. |
| Yellow/red boundary | Use explicit project triggers. Unqualified or intense pain wording without a clear trigger is unresolved, not a new severity threshold. Preserve uncertainty for adjudication. | **guideline example:** "My shoulder hurts badly." Yellow/red assignment [TO VERIFY]; do not force an unsupported label. |
| Slang, abbreviations and typos | Interpret only unambiguous wording; confirm aliases against the approved vocabulary. Unclear exercise identity becomes `unknown`, without downgrading an explicit symptom. | **guideline example:** "bnch: sharp shoulder pain." Red; an uncertain exercise mapping does not remove the sharp-pain report. |
| Multiple exercises | Assess each reported symptom, then use the highest applicable severity for the message. Never silently keep only the first exercise or its numbers. | **guideline example:** "Squats were fine; pressing caused sharp shoulder pain." Red for the message. |
| Missing numbers | Missing load, reps and RPE are not zero; use the F2 nullable fields. Do not invent an outcome or observation to complete a record. | **guideline example:** "Rows felt smooth and symptom-free." Green; load, reps and RPE are unreported. |

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
The plan names them but does not define quantitative boundaries. The following
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

## Agreement script

Run [scripts/kappa.py](../scripts/kappa.py) only on independently assigned labels.
The caller explicitly maps the existing identifier and label locations using
JSON Pointers; no annotation envelope or identifier field name is prescribed.
For instance, the following command assumes that the human export has top-level
`id` metadata and top-level extraction fields. These paths are illustrative,
not a project export schema:

```powershell
python scripts/kappa.py annotator-a.jsonl annotator-b.jsonl --id-pointer /id --field exercise_id=/exercise_id --field kinematic_observation=/kinematic_observation --field outcome=/outcome --field triage_level=/triage_level
```

Use `uv run python` instead of `python` once the team's uv environment exists.
Repeat `--field NAME=/pointer` for each applicable categorical field. Nested
exports can use paths such as `/labels/triage_level`. The four selectable names
above are from F2. Their final designation as headline agreement fields is
[TO VERIFY] with F2 and the evaluation owner. Do not silently omit a troublesome
field from the pilot report.

The script computes unweighted nominal Cohen's kappa by exact string agreement,
after matching items by identifier rather than line order:
`kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement)`.
It validates selected categorical enums, not the whole F2 extraction model.
Exercise IDs are checked only for non-empty strings until the pinned D7
vocabulary is available; canonical membership remains a blocker [TO VERIFY].
The script accepts non-empty string or integer identifiers, with types kept
distinct. Confirm this operational identifier restriction with the export owner.

Load, reps and RPE agreement rules, missing-value treatment and multi-exercise
alignment are [TO VERIFY]. Numerical extraction remains required for human
labels; the script does not guess bins, tolerances, weighted kappa or an
artificial pooled kappa across unrelated fields.

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

## Human pilot and review procedure

1. Resolve the schema and rubric questions above with Patrick and the relevant
   owners. Patrick reviews this guideline and the proposed matrix.
2. Filip and Patrick each author 10 new human-only items following the sampling
   dimensions. Store actual pilot items only in restricted `data/golden/pilot/`.
   Do not reuse guideline examples.
3. Seal intended labels and independently assign blind labels. Preserve
   identifiers and original labels; agree the pilot class allocation and blind
   subset procedure before authoring [TO VERIFY].
4. Compute agreement per agreed headline field on the 20 items. Review every
   red-versus-not-red disagreement regardless of kappa.
5. If any headline kappa is below 0.70, revise the guideline and re-label the
   affected subset. Investigate undefined fields rather than accepting them.
   Record the sample sizes, pre-adjudication results, disagreements, revisions
   and any repeat measurements honestly.
6. Keep pilot items separate from the 250 unless the team explicitly decides
   otherwise. Follow the plan's human freeze procedure only after agreement and
   review; no Git operations are part of this implementation.

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
