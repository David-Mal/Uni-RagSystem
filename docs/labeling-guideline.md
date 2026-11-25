# Labeling guideline v0

Status: revised after Patrick's requested changes on commit `186c53d` of
[Fi1 PR #74](https://github.com/David-Mal/Uni-RagSystem/pull/74).
The revised allocation awaits Patrick's final confirmation. Expanded symptom
policy awaits David and Fineas. Human pilot measurements remain pending; Fi1 is
not complete.

## Sources and authority

- [Architecture plan](milestone2-architecture-and-plan.md): sections 2.2, 2.4-2.5,
  3.1-3.4, 5.3-5.8, 6.3 and 9.1.
- [RFC](../RFC_Heuristic_Load_Fatigue_Analyzer.md): section 3, especially goals 2 and 5.
- [Patrick's review](https://github.com/David-Mal/Uni-RagSystem/pull/74#pullrequestreview-6060865279)
  of `186c53d`, dated **2026-11-25**: eight requested changes and annotation decisions.
- [F2 PR #69](https://github.com/David-Mal/Uni-RagSystem/pull/69), schema **v0**:
  `src/schemas/enums.py`, `models.py`, `json_schema.py` and exported
  `schemas/extraction_result.json`, `load.json`, `claim.json`, inspected read-only
  at `7f5e5b27fcff17164af5f52d08248bbe4d2d82a8` on
  `origin/feat/F2-schemas-enums`. This is not a merged dependency in this checkout.
- [D9 / issue #14](https://github.com/David-Mal/Uni-RagSystem/issues/14):
  proposed red/yellow pattern lists and gate behavior.
- [P5 / issue #19](https://github.com/David-Mal/Uni-RagSystem/issues/19):
  `item_id` and `labels` envelope, human authoring and Patrick's real-note-style slice.
- [P1 PR #80](https://github.com/David-Mal/Uni-RagSystem/pull/80):
  only the eight public opaque golden `messages` IDs and six exercise-family
  names supplied for this review. Restricted descriptions and partition contents
  were not inspected.

Patrick's decisions below resolve Fi1's earlier open annotation questions. They
are distinguished from the remaining cross-owner approvals. Review markers are
never extraction enum values. No shared F2 model, gate, dataset or training code
is implemented here.

## Independence and contamination controls

Filip George Bumbar and Patrick Marchis each author 125 of the 250 messages:
55 green, 30 yellow and 40 red. Each item receives an author-sealed intended label
and a second label assigned blind to that label and intended sampling class.
The matrix controls authoring, not what the second annotator sees.

Follow plan sections 2.4 and 3.1-3.2: separate training and golden phrasing families,
seeds and templates; never use held-out items for tuning. A third party
re-randomizes an at-least-20% subset both annotators label blind and removes
sealed labels. Builders do not adjudicate golden disagreements. Instructor
confirmation of the sealed-author-label protocol remains open.

Every illustrative message below is explicitly marked **guideline example**.
Never copy, paraphrase or reuse these examples in golden messages, the human
pilot, training examples or generator prompts. They do not define golden
phrasing families. No golden or pilot text or labels were inspected or generated
for this revision; automated tests use isolated synthetic label projections
without messages.

## Extraction fields and allowed values

Every message receives the full seven-key F2 extraction object, not triage alone
(plan section 3.3). Preserve reported information without inventing numbers,
canonical exercise identities or diagnoses.

| Field | F2 v0 contract | Fi1 annotation decision |
|---|---|---|
| `exercise_id` | Required non-null string matching `^[A-Za-z0-9_\-]+$`, or lowercase `unknown` | Use a confirmed vocabulary ID; unresolved identity stays `unknown`. F2 rejects mixed-case versions of the reserved sentinel. Pinned vocabulary/alias confirmation remains [TO VERIFY]. |
| `kinematic_observation` | Required non-null: `none`, `slow_bar_speed`, `grinding_rep`, `reduced_range_of_motion`, `lost_balance`, `other` | Choose the first mentioned matching named observation; `other` only if no named observation fits, `none` if none is reported. Never diagnose form. |
| `load` | Required key; `null` or object with exactly `value` and `unit`; finite number `value >= 0`, unit `kg` or `lb` | Preserve value/unit. A load without a unit is `null`. Do not infer a unit, convert or copy another set's load. Zero is allowed; F2 defines no upper bound. |
| `reps` | Required key; strict integer `>= 0` or `null` | Record only an explicitly supplied count; otherwise `null`, including when partial/failed status is clear. No upper bound is defined. |
| `outcome` | Required non-null: `completed`, `failed`, `partial`; no model default | Follow F2 and Patrick's failure clarification below. Always supply the key. |
| `rpe` | Required key; finite numeric value in inclusive `[0, 10]`, or `null` | Record explicit RPE; fractional values are valid. Do not infer it from effort or round it. Unclear shorthand needs human clarification. |
| `triage_level` | Required non-null: `green`, `yellow`, `red` | Assess the whole message, including timing and negation, using the policy below. |

All **seven keys are required**. Only `load`, `reps` and `rpe` may be `null`;
missing keys are invalid, not another spelling of absence. Never default a
missing number to zero. F2 rejects additional properties in `ExtractionResult`
and `Load`, numeric strings, booleans, NaN and infinities. Integer JSON numbers
are accepted for load/RPE float fields; floating-point repetitions are rejected.
The actual runtime validators contain details beyond the static JSON Schema.

Exercise IDs are case-sensitive ASCII letters, digits, underscores and hyphens,
without whitespace. With `context={"exercise_ids": ids}`, F2 validates canonical
membership; `unknown` is always legal. Without that context, it checks shape,
not membership. Its `extraction_json_schema(ids)` constrains decoding to the
supplied IDs plus `unknown`; the plain exported schema contains only the shape
pattern. A matrix group or P1 pool coordinate is not a canonical exercise ID.
The separate `Claim.exercise_id` may be null; that does not make the extraction
field nullable.

### Patrick's outcome, exercise, set and observation decisions

These are the reviewer's Fi1 decisions, following F2 PR #69. They are annotation
conventions, not automatic defaults or cross-field validators:

1. `completed` means no failure or partial completion was reported, including
   an unreported outcome. It is a conventional extraction label, not proof that
   the set physically succeeded.
2. When failure/partial completion is described, use `partial` if at least one
   repetition was completed; otherwise use `failed`. Do not invent a repetition
   count from this classification: `reps` is null unless the text supplies it.
3. For multiple exercises, select the exercise linked to the most severe symptom.
   With no symptom, or a tie, choose the first exercise with set data, as in F2.
   Use `unknown` if the chosen identity cannot be resolved. Triage is always
   assessed across the whole message, not just the selected exercise.
4. Within that exercise, choose the set associated with the symptom or movement
   observation; otherwise choose the first mentioned set. Keep its load, reps,
   outcome, RPE and movement observation together. Do not combine different sets.
5. When several named movement observations fit, choose the first mentioned.
   Use `other` only when an observation is reported but no named value fits;
   use `none` when no movement observation is reported.
6. Load without a unit is null. Missing counts and RPE are null even when other
   set fields can be labeled.

If the stated selection rules still cannot resolve a specific linkage, retain
that case for human adjudication rather than add a new field, enum or tie-breaking
threshold. Patrick's decisions are recorded; they are not left as unanswered
questions. Cross-owner symptom-policy approval is tracked separately below.

### Annotation envelope

Issue #19 establishes **`item_id` and `labels`**. The full seven-key
`ExtractionResult` is inside `labels`; `item_id` is metadata outside the
strict extraction object. Keep the source author's prescribed identifiers stable.
The kappa utility retains flexible JSON Pointers for label projections and other
agreed nesting; this does not redefine the issue's authoring envelope.

## Safety classes and scope

These are conservative **project annotation rules**, not medical diagnoses,
injury predictions or advice. Patrick proposes combining the RFC and issue #14.
**The expanded red/yellow policy remains [TO VERIFY] with David and Fineas.**
The review does not establish their approval or change the production gate.

| Class | Annotation definition | Project gate effect |
|---|---|---|
| `green` | No symptoms; Patrick also classifies explicitly resolved non-red symptoms as green. | Normal analysis subject to sufficiency. |
| `yellow` | Mild discomfort, ache/achy, stiffness, non-chest tightness, persistent soreness or a twinge; also unqualified pain and explicitly resolved red symptoms under Patrick's conservative rule. | Exclude affected exercise(s), use the fixed disclaimer and continue only with sufficient eligible data. |
| `red` | Any applicable combined red trigger below, or intense pain under Patrick's reviewer decision. | Block analysis and use only the fixed referral message. |

The complete **proposed combined red list** is:

- Sharp pain.
- Stabbing pain.
- Swelling.
- Dizziness.
- Fainting.
- Chest pain or chest tightness.
- Numbness.
- Radiating tingling.
- Pop or snap accompanied by pain.

Issue #14's yellow list is mild discomfort, ache, achy, stiffness, tightness,
soreness that persists and a twinge. Chest tightness belongs to the proposed red
list; generic tightness must not hide that distinction. No time cutoff, symptom
score, numerical intensity threshold or additional medical trigger is invented.

Patrick's additional decisions are: **unqualified pain is yellow; intense pain
is red; explicitly resolved symptoms are green except that a resolved red symptom
is yellow; unclear timing counts as present**. These reviewer decisions resolve
the former Fi1 questions. Their reconciliation with gate and training policy,
together with the expanded trigger lists, still requires David and Fineas's
confirmation. No gate, classifier, extractor or training data is changed here.

Evaluate negation and timing before taking the most severe applicable class
across the message. The production gate takes the maximum of its signals per
note, then per log (plan section 5.3); human labels do not imitate potentially
mistaken model predictions.

### Edge cases

| Case | Rule | Illustration |
|---|---|---|
| Figurative language | A clearly figurative effort expression alone does not establish a symptom. Assess any separate literal symptom. | **guideline example:** "That set killed me." Green when context clearly expresses effort without symptoms. |
| Negation | Apply negation within its scope; a negated symptom does not cancel a separate positive one. | **guideline example:** "No pain today, just mild knee stiffness." Yellow because stiffness is reported. |
| Past versus present | Explicitly resolved non-red symptoms are green; resolved red symptoms are yellow. Unclear timing counts as present. | **guideline example:** "My shoulder hurt last month; it is fine now." Green under Patrick's rule for resolved unqualified pain. |
| A different exercise | Link the symptom to the exercise actually affected, then apply F2's single-exercise selection. | **guideline example:** "Rows felt normal; my knee was stiff during squats." Yellow; the symptom concerns squats. |
| Yellow/red boundary | Unqualified pain is yellow; intense pain is red. No numerical severity scale is added. | **guideline example:** "My shoulder hurts badly." Red under Patrick's intense-pain decision. |
| Slang, abbreviations and typos | Interpret unambiguous wording; confirm aliases against the vocabulary. Unresolved identity does not downgrade a clear symptom. | **guideline example:** "bnch: sharp shoulder pain." Red despite uncertain exercise mapping. |
| Multiple exercises | Assess the whole message; select exercise/set fields using the decisions above. | **guideline example:** "Squats were fine; pressing caused sharp shoulder pain." Red for the message. |
| Missing numbers | Keep all seven keys; unreported numbers are null. Follow the required outcome convention separately. | **guideline example:** "Rows felt smooth and symptom-free." Green; load, reps and RPE are unreported. |

Every red-versus-not-red disagreement must be adjudicated and logged even when
kappa exceeds 0.70. An unresolved item remains outside the finalized label export;
never add `ambiguous` or `pending` as extraction enum values.

For yellow linking, plan section 5.3 and issue #14 prioritize the structured CSV
exercise link, then extractor identity. An unresolved workout-level yellow note
excludes all exercises in that workout. An unresolved yellow free-text message
requests clarification; non-interactive handling remains insufficient data plus
the disclaimer. The demo-front-end choice is still [TO VERIFY] in plan section
9.3; this guideline does not implement it.

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

[sampling_matrix.yaml](../data/golden/sampling_matrix.yaml) is a count-only
**revised proposal awaiting Patrick's final confirmation [TO VERIFY]**.

Each safety class fully crosses **five grouped exercise families × six traps**:
30 populated base cells per class, **90 total**, with at least two items in every
base cell. The base-cell key is `(safety_class, exercise_family, trap_type)`.
Phrasing and manifest subfamily are separate nested allocation coordinates,
not extra base-cell axes. Each base cell splits equally between Filip and Patrick.

| Safety class | Total | Filip | Patrick | Hard negatives | Hard negatives per author |
|---|---:|---:|---:|---:|---:|
| Green | 110 | 55 | 55 | 54 | 27 |
| Yellow | 60 | 30 | 30 | 40 | 20 |
| Red | 80 | 40 | 40 | 0 | 0 |
| **Total** | **250** | **125** | **125** | **94** | **47** |

Green hard negatives are **54/110**, approximately **49.1%**, replacing 78/110.
All figurative, negated, slang/typo and boundary cells within green/yellow form
the dedicated hard-negative subset. Every exercise group has all six traps.
Multi-exercise and none cells are outside that subset. Red cells never count as
hard negatives, even when their primary trap is figurative or negated; an
affirmative applicable red symptom must justify their red class.

### Five groups and P1's six public manifest families

| Grouped exercise axis | Public manifest family coordinate |
|---|---|
| squat pattern | `squat` |
| hip hinge | `deadlift` |
| upper-body press | `bench` and `overhead_press` |
| upper-body pull | `row` |
| other or unresolved family | `accessories`, with identity handled separately |

Both `bench` and `overhead_press` have positive allocations for **each author
in all three safety classes**. They remain nested inside upper-body press, so
there are five grouped axes, not six.

| Class | Filip bench | Filip overhead_press | Patrick bench | Patrick overhead_press |
|---|---:|---:|---:|---:|
| Green | 5 | 6 | 6 | 5 |
| Yellow | 3 | 3 | 3 | 3 |
| Red | 4 | 4 | 4 | 4 |

Each nested allocation records `phrasing_family`, `manifest_family`,
`identity_target`, `count` and `by_author`. `identity_target` is a planning
coordinate (`resolved` or `unresolved`), not a new F2 enum or an assigned label.
For the other-or-unresolved group, `accessories` is the P1 authoring-pool
coordinate. A separate unresolved identity target is **not** a canonical accessory:
the human label must retain unresolved exercise identity rather than invent an
accessories ID. Resolved targets need an actual confirmed vocabulary ID.
No canonical exercise IDs are generated in the matrix.

### Opaque phrasing rotation and counting

The only phrasing coordinates are the public golden `messages` IDs
`pf_gd_01`, `pf_gd_02`, `pf_gd_03`, `pf_gd_04`,
`pf_gd_05`, `pf_gd_06`, `pf_gd_07`, `pf_gd_08`.
No restricted description or golden style wording is defined here.

All eight IDs are used for each author in every class. All **40** used grouped
exercise × phrasing pairs occur in **all three classes**. Across the matrix,
every ID occurs with all six traps; phrasing and trap are distinct planning
coordinates. This rotation is not a claim that all eight IDs can be fully
crossed inside every two-item base cell.

| Opaque ID | Green | Yellow | Red | Total |
|---|---:|---:|---:|---:|
| `pf_gd_01` | 16 | 8 | 9 | 33 |
| `pf_gd_02` | 15 | 8 | 11 | 34 |
| `pf_gd_03` | 10 | 8 | 11 | 29 |
| `pf_gd_04` | 13 | 7 | 10 | 30 |
| `pf_gd_05` | 14 | 6 | 12 | 32 |
| `pf_gd_06` | 12 | 7 | 8 | 27 |
| `pf_gd_07` | 15 | 8 | 8 | 31 |
| `pf_gd_08` | 15 | 8 | 11 | 34 |
| **Total** | **110** | **60** | **80** | **250** |

The 180 nested allocations **partition** the 90 base cells. Add child counts
to recover the parent's count; do not add parent and child totals together.
Author-specific children may have zero for the other author; equality is
required for each complete base cell. One primary trap per item determines the
cell; secondary traps never add another allocation. The JSON-syntax YAML 1.2
file remains readable with the standard library.

Issue #19 specifies 15 of Patrick's items modeled on his own real-note style.
Humans must coordinate that slice within the 125 and these counts; no extra
messages or a matching quota for Filip are invented. No personal logs were
accessed. Authoring remains outside Fi1's technical implementation.

**Private draft compatibility:** any private Fi4 assistant using the former
30-cell matrix, generic styles or flat-cell layout is now outdated. Refresh its
matrix locally and revalidate counts/mappings before further authoring. No
private folder or draft was accessed, inspected or modified here.

## Agreement script: seven nominal fields

Run [scripts/kappa.py](../scripts/kappa.py) on independent label projections,
matched by identifier, without message text. Issue #19's envelope uses
`--id-pointer /item_id` and pointers under `/labels/`. The interface still
allows explicit alternate JSON Pointers without guessing their nesting.

| Headline fields | Acceptance |
|---|---|
| `triage_level`, `exercise_id`, `kinematic_observation`, `outcome` | Nominal unweighted Cohen's kappa **>= 0.70 on every headline field**, plus adjudication of every red-versus-not-red disagreement. Undefined headline kappa requires review. |

| Numeric field | Proposed exact-match categories |
|---|---|
| `load` | Exact numeric value **and** exact `kg`/`lb` unit, or explicit null. |
| `reps` | Exact strict nonnegative integer, or explicit null. |
| `rpe` | Exact finite numeric value in inclusive `[0, 10]`, or explicit null. |

Patrick proposed this numeric convention; it is implemented for review, with
**final team/evaluation-owner confirmation pending [TO VERIFY]**. Numeric fields
are reported separately and have **no automatic acceptance threshold**.

Two nulls agree; null and a value disagree. Equal load/RPE numeric values such
as 80 and 80.0 agree. Units remain different categories even when physically
equivalent. There is no conversion, rounding, tolerance, binning or ordinal
weighting. Repetitions such as 5.0 are invalid, even though numerically equal
to 5, because F2 requires a strict integer.
JSON decimal values are retained exactly for category comparison rather than
rounded into binary floats; this also prevents artificial agreements between
distinct reported decimals. Non-finite/unrepresentable floating values are
rejected. This concerns agreement categories, not a replacement F2 model.

For all seven fields, missing selected keys are invalid, never null by default.
The script rejects invalid enums/IDs, malformed load objects, invalid units,
negative loads/reps, RPE outside 0-10, booleans, numeric strings, NaN/infinity,
duplicate JSON keys/identifiers, malformed JSONL and mismatched item sets.
It preserves identifier types and source label counts; null items are not dropped.
Canonical ID membership still requires the pinned vocabulary/F2 validation
context. This utility validates selected field projections, not the full F2
record, its exercise linkage or its semantic truth.

Humans execute this locally with Python 3.11:

```powershell
python scripts/kappa.py filip-labels.jsonl patrick-labels.jsonl --id-pointer /item_id --field exercise_id=/labels/exercise_id --field kinematic_observation=/labels/kinematic_observation --field load=/labels/load --field reps=/labels/reps --field outcome=/labels/outcome --field rpe=/labels/rpe --field triage_level=/labels/triage_level --json
```

The filenames above are local placeholders, not newly prescribed pilot paths.
This command was not executed against pilot data. A configured uv environment
may use `uv run --python 3.11 python` in place of `python`.

The JSON report keeps headline metrics in `fields` and numeric metrics in
`numeric_fields`. Top-level `threshold` and `review_required` apply to selected
headlines and red disagreements only. Numeric status is `reported_only` or
`undefined`; it never becomes `meets_threshold`/`below_threshold`.
Unselected headlines are listed explicitly. A numeric-only run makes no
headline acceptance decision.

For each field:
`kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement)`.
Expected agreement of one makes kappa undefined, including identical
single-category/null labels. Undefined numeric kappa is reported for human
interpretation without applying a headline threshold. No artificial pooled
kappa across fields is calculated; the plan's overall-summary definition still
requires coordination.

Exit **0**: selected headlines meet 0.70 with no red disagreement, or a valid
numeric-only report. Exit **1**: a selected headline is below threshold,
undefined, or needs red/non-red adjudication. Exit **2**: invalid input/arguments,
including invalid numeric fields. Numeric disagreement does not fail passing
headlines, and numeric agreement cannot rescue failed headlines. A subset report
does not establish acceptance across all four headline fields.

### Technical validation, not pilot agreement

On **2026-11-25**, the complete Fi1 suite passed under Python **3.11.18** and
pytest **9.2.0**: **66 tests and 233 subtests passed in 13.91 seconds**, exit code
**0**. All three pinned F2 conformance checks ran successfully in this checkout;
unavailable Git objects elsewhere produce explicit skips, never fabricated
compatibility claims. F2 code was not executed or merged.

The test command, with an isolated temporary uv environment active, was:

```powershell
uv run --no-project --active --offline python -B -m pytest tests/test_kappa.py tests/test_sampling_matrix.py -q -p no:cacheprovider --confcutdir=tests --basetemp "$fi1TestTemp\pytest-verified"
```

`$fi1TestTemp` denotes the temporary run directory. No permanent dependency or
validation script was added. The complete five-file diff, type annotations,
local references and whitespace were checked. Only synthetic label projections,
schema blobs and the authorized count-only matrix were read by these checks.
The tests cover the 90-cell crossing and nested accounting, family/phrasing
coverage, all seven agreement fields, explicit nulls, strict invalid inputs,
exact numeric comparison, and separate headline/numeric acceptance behavior.
These are technical test results, not pilot agreement measurements.

## Human pilot and review procedure

1. Patrick confirms the revised allocations and reviews these changes. Obtain
   David/Fineas's expanded symptom-policy confirmation and final confirmation of
   the numeric exact-match convention. Confirm pinned exercise IDs and the
   instructor's sealed-author-label protocol. Do not re-open the reviewer
   decisions already recorded above as unanswered questions.
2. Filip and Patrick each author **10 new human-only pilot items**, kept separate
   from the 250 unless the team explicitly decides otherwise. Actual pilot data
   belongs in restricted `data/golden/pilot/`. Reuse neither guideline examples
   nor AI-written/paraphrased messages.
3. Seal full seven-field labels; supply the other annotator randomized items with
   stable `item_id` values, hiding sealed labels, intended classes and sampling
   hints. Lock both submissions before revealing labels. A third party handles
   the at-least-20% separately blind subset under plan section 3.2 (at least four
   of 20 if applied to the pilot); confirm the procedure with the instructor.
4. Both comparison JSONL files must cover the **same 20 identifiers**, assembling
   each annotator's sealed author labels and blind labels for the other's items.
   Do not compare disjoint 10-item author files. Validate each full `labels`
   object with shared F2 and the pinned vocabulary separately.
5. Humans run the seven-field command above locally. Retain original submissions
   and pre-adjudication results. Report the four headline kappas and three numeric
   kappas separately, plus sample sizes and the separately blind subset.
6. Revise the guideline/re-label the affected subset if any headline kappa is
   below 0.70; investigate undefined headline fields. Adjudicate and log every
   red/non-red disagreement regardless of kappa. Record revisions and repeated
   measurements without overwriting the original report. Freeze only after
   human review and actual agreement measurements; no Git operations are
   performed by this AI-assisted work.

## Pilot results

**Status: pending.** No actual pilot messages or labels were created, inspected
or measured during this work. Synthetic test results are not pilot agreement.

| Required record | Current status |
|---|---|
| 10 human-authored items from Filip | Pending human authoring. |
| 10 human-authored items from Patrick | Pending human authoring. |
| Independent seven-field labels for the same 20 identifiers | Pending. |
| Four headline kappas and three separate numeric kappas | Pending; no measurements fabricated. |
| Red/non-red adjudication log and guideline revisions | Pending actual findings. |
| Patrick's review | Requested changes received at `186c53d`; follow-up confirmation of this revision pending. |
| David/Fineas symptom-policy approval | Pending. |
| Final numeric agreement convention confirmation | Pending. |

Fi1 remains open until the human pilot, any required revisions and final review
are available.
