# D6: Strong and Hevy adapter preparation

Status: **blocked on D4 in this checkout**. Both application formats remain
**[TO VERIFY against real exports]**, unverified against real application exports.
This document and the fixture directories prepare issue #11 without defining a
replacement ingestion system.

## References

- [Architecture plan section 2.2](milestone2-architecture-and-plan.md#22-input-formats-and-ingestion): community headers and ingestion rules.
- [D6, issue #11](https://github.com/David-Mal/Uni-RagSystem/issues/11): adapter, warning, fixture and test requirements.
- [D4, issue #9](https://github.com/David-Mal/Uni-RagSystem/issues/9): shared models, normalization, storage and pipeline.
- [RFC](../RFC_Heuristic_Load_Fatigue_Analyzer.md): deterministic numerical processing and failed-set exclusion.

## Dependency check: 2026-11-25

The checkout on `feature/filip-d6-adapters` has no `src/ingest/`,
`tests/ingest/`, `pyproject.toml` or `uv.lock`. Python 3.11.18 is available, but
pytest is not installed in the inspected Python 3.11 interpreter. GitHub issue
#9 describes D4; that description is not an implemented interface.
These paths were rechecked while validating the two populated `synthetic.csv`
files; D4 is still unavailable locally.

The missing D4 dependencies are:

| Dependency | D6 work blocked by its absence |
|---|---|
| `CanonicalSet`, `CanonicalSets` and their actual model module | Constructing and validating canonical results, including null and note handling. |
| `BaseAdapter` and the established adapters directory | Implementing `strong.py` and `hevy.py` using the real detection and conversion signatures. |
| Shared `normalize.py` implementation | Weight conversion, source units, failed-set rules, set-type normalization and explicit date parsing. |
| `IngestError` and its actual import path | Reporting unknown headers, invalid dates and format failures consistently. |
| Adapter registration, `ingest_workout_log` and `IngestResult` | Selecting the adapters and passing `unit_hint` through the supported pipeline API. |
| D4 workout/storage interface and idempotent ingest behavior | Preserving workout duration separately from set duration, grouping workouts and integrating canonical results. |
| Project dependency configuration and ingestion test setup | Running the required Python 3.11 pytest checks against the shared implementation. |

The plan illustrates `to_canonical(df)`, whereas issue #9 requires a source path
and says not to hardcode CSV in the shared interface. Use D4's actual interface
when it arrives; do not implement a second base class to reconcile these examples.
No models, normalization, adapters, registry, storage or test infrastructure are
introduced by this preparation.

## Community evidence inspected: 2026-11-25

These sources report community behavior, not a verified official export schema.
They narrow the fixture conventions without establishing compatibility with all
app versions. The public example was inspected only for format evidence; this
validation did not insert its workout rows into the local fixtures.

| Reference | Inspected evidence | Qualification |
|---|---|---|
| [S1: Strong format reference](https://github.com/smyrick/sugarwod-to-hevy/blob/main/docs/STRONG_FORMAT.md) | File shape, 12-column order, date/duration formatting, one-based indices, quoting and blanks. | A community converter's reference, not Strong's official specification. Its fixed noon timestamps, estimated durations and Hevy-import kg behavior must not become native-export assumptions. |
| [S2: Intervals.icu forum, opening post](https://forum.intervals.icu/t/import-strong-data-weightlifting-app/5531) | Corroborates Strong's column sequence, with `RPE` last. | A user report; it does not establish date formats or units. No attached logs were accessed. |
| [H1: Gym Log's Hevy guide](https://gymlog.info/analyze/hevy-workout-data/) | Timestamp appearance, zero-based indices, source set types, independent weight/distance units and field meanings. | A third-party importer author's report, not Hevy's official schema. |
| [H2: public Hevy example](https://github.com/matanabudy/workout-data-sync/blob/main/examples/hevy_export_sample.csv) | Header order, comma-containing timestamps, quoted text, empty fields and numeric zero. | A limited community sample; it shows `normal`, not every reported set type. |

### Reported conventions used for fixture preparation

| App / field | Evidence-backed community convention |
|---|---|
| Strong `Date` | S1 specifies `YYYY-MM-DD HH:MM:SS`. |
| Strong `Duration` | S1 describes elapsed tokens: minutes, hours, or hours plus minutes. `45m` and `1h 20m` follow that pattern; these are not clock times or rest durations. |
| Strong `Set Order` | S1 reports one-based numbering restarted for each exercise. |
| Strong CSV and blanks | S1 specifies UTF-8, commas and minimal CSV quoting. Notes and RPE may be empty; its unused numeric metrics use zero. This is not permission to turn every missing value into zero. |
| Hevy timestamps | H1/H2 support `D MMM YYYY, HH:mm`, using English month abbreviations in the inspected examples. The comma requires CSV quoting. |
| Hevy `set_index` | H1 reports zero-based positions within an exercise. H2 starts at zero but lists successive indices for different exercises; it does not corroborate per-exercise resets. Scope/reset behavior remains [TO VERIFY]. |
| Hevy `set_type` | H1 reports `normal`, `warmup`, `dropset`, `failure`. These are source spellings, not a newly defined canonical enum. |
| Hevy CSV and blanks | H2 has comma-separated fields, quoted headers/text, empty quoted notes, empty unquoted superset/distance fields, and zero set duration. Blank and zero remain distinct; other missing-number conventions are not established. |

The templates now follow S1/S2's Strong order and H2's Hevy order. That does not
make order a universal detection requirement or determine required-column subsets.
English month parsing must remain deterministic rather than depend silently on
the host locale. Timestamp timezone semantics and D4's parsing API remain
[TO VERIFY]; no permissive date guessing is authorized.

## Documented Strong mapping

The target names below come from issue #9, not from a new schema.

| Community header | Intended D4 destination or handling |
|---|---|
| `Date` | `workout_ts`; S1 reports `YYYY-MM-DD HH:MM:SS`, still [TO VERIFY against real exports]. |
| `Workout Name` | `workout_name`. |
| `Duration` | Reported elapsed hour/minute tokens; D4 workout-duration destination [TO VERIFY]. |
| `Exercise Name` | `exercise_name_raw`; exercise matching is outside D6. |
| `Set Order` | Reported one-based index; canonical indexing and nonnumeric/source set-type encoding [TO VERIFY]. |
| `Weight` or the reported `Weight (kg)` variant | Shared weight normalization and retained `source_unit`; ambiguous `Weight` requires an explicit unit decision. |
| `Reps` | `reps`; use the shared failed-set rule. |
| `RPE` | `rpe`; S1 allows blank values, with D4 null handling [TO VERIFY]. |
| `Distance` | `distance`; source and canonical distance units [TO VERIFY]. |
| `Seconds` | Per-set `duration_s`; do not replace it with workout `Duration`. |
| `Notes` | `set_note`, preserving the supplied text. |
| `Workout Notes` | `workout_note`, preserving the supplied text. |

Provide the optional `unit_hint` required by issue #11. Never silently assign a
unit to ambiguous `Weight`. Hint values, conflicts with an explicit unit-bearing
header, and pipeline forwarding must use D4's actual conventions [TO VERIFY].

Strong's export set-type encoding is unknown. As required by issue #11, map
Strong sets to the internal `normal` type and emit a warning that source set
types are unverified. This does not override `failed = reps == 0 or flagged`
from shared normalization. Do not invent source failure, warm-up or drop markers.
Warning integration must follow the existing logger once available [TO VERIFY].
S1's report that no separate set-type flag is exported does not change this
explicit D6 requirement. Its zero-for-unused-metrics advice must not suppress
D4's failed-set rule, including when a source uses zero repetitions for timed work.

## Documented Hevy mapping

| Community header | Intended D4 destination or handling |
|---|---|
| `start_time` | `workout_ts`; reported `D MMM YYYY, HH:mm`, still [TO VERIFY against real exports]. |
| `end_time` | Derive workout duration from parsed end minus start; storage interface [TO VERIFY]. |
| `title` | `workout_name`. |
| `exercise_title` | `exercise_name_raw`. |
| `set_index` | Reported zero-based position; index scope/reset and canonical base [TO VERIFY]. |
| `set_type` | Reported `normal`, `warmup`, `dropset`, `failure`; use D4's actual shared mapping when available. |
| `weight_kg` or `weight_lbs` | Unit identified by the header; shared conversion to `weight_kg`, retaining the source unit. |
| `reps` | `reps`; use shared failed-set handling. |
| `rpe` | `rpe`; missing-value representation [TO VERIFY]. |
| `distance_km` or `distance_miles` | `distance`; shared destination unit and conversion policy [TO VERIFY]. |
| `duration_seconds` | Per-set `duration_s`, distinct from derived workout duration. |
| `exercise_notes` | `set_note`, preserving the supplied text. |
| `description` | `workout_note`, preserving the supplied text. |
| `superset_id` | H1 describes a shared number, absent when unused; preserve through D4's actual field type. |

In particular, reported Hevy `dropset` differs from D4's issue-defined `drop`.
The eventual shared mapping and interpretation of a source `failure` marker must
be confirmed with D4 [TO VERIFY]; working to failure and a zero-repetition row
must not be conflated by new adapter assumptions. Neither adapter may call a
network service or an LLM.

## Populated synthetic fixtures

- [Strong fixture and row expectations](../data/fixtures/strong/README.md).
- [Hevy fixture and row expectations](../data/fixtures/hevy/README.md).

The actual files are [Strong synthetic.csv](../data/fixtures/strong/synthetic.csv)
and [Hevy synthetic.csv](../data/fixtures/hevy/synthetic.csv), with **12 data rows
each, 24 total**, within issue #11's 10-20-row range. Their separate
`header-template.csv` files remain header-only references. The populated CSVs
were read and validated, not regenerated or overwritten. Both READMEs retain
the label **"synthetic, built from community headers"**.

**Provenance:** the values are **AI-assisted and manually inserted by Filip
George Bumbar**, as reported by the user. This does not claim independent
human-only authorship. Team approval of the fixtures and of this provenance
against issue #11's hand-written requirement is pending **[TO VERIFY]**.
Synthetic validation does not verify compatibility with real exports.

### Actual validation: 2026-11-25

An inline, standard-library-only Python **3.11.18** check read every data row
using strict CSV parsing. It checked exact header order and row widths, valid
timestamps, finite nonempty numeric cells, integer repetition/index fields,
missing RPE, source indices, set types, workout consistency and duration
arithmetic. Hevy date parsing used an explicit English-month lookup instead of
the host locale. No new numeric ranges or canonical schemas were introduced.
SHA-256 checks confirmed both source CSVs were unchanged.

| Check | Strong | Hevy |
|---|---|---|
| Actual data rows | 12 | 12 |
| Columns on every row | 12 | 14 |
| Valid timestamp cells | 12 | 24 |
| Finite nonempty numeric cells checked | 47 | 47 |
| Missing RPE | Data row 11 | Data row 11 |
| Zero-repetition / expected failed row | Data row 12 | Data row 12, also source `failure` |
| Workout/exercise grouping | 2 workouts, 4 exercise groups, 3 sets per group | Same |
| Source indices in each exercise group | `1, 2, 3` | `0, 1, 2` |
| Source set types | Not exported; all 12 must become internal `normal`, with warning | 2 `warmup`, 8 `normal`, 1 `dropset`, 1 `failure` |
| Structural/numeric/timestamp result | Passed | Passed |

Data-row numbers exclude the header. The workouts in both fixtures are:

| Data rows | Workout / expected `workout_ts` | Expected workout duration | Expected `workout_note` |
|---|---|---|---|
| 1-6 | Upper Body / `2026-11-10 18:00:00` | `45 * 60 = 2700` seconds | Evening workout |
| 7-12 | Lower Body / `2026-11-12 17:00:00` | `50 * 60 = 3000` seconds | Afternoon workout |

Hevy end times are `18:45` and `17:50` on their respective start dates; direct
subtraction agrees with Strong's `45m` and `50m` tokens. Do not put these workout
durations into the per-set `duration_s` field, whose source values are missing.

### Canonical expectations and coverage boundaries

The READMEs list expected numeric values and failed status for all 24 rows,
plus populated note mappings. Both row-11 RPE values should become `None` under
issue #9's nullable RPE contract. Both row-12 sets must be failed from zero
repetitions; Strong's row 12 still has internal type `normal` with the mandatory
warning. Hevy weights have kg established by `weight_kg`; source `dropset` is
intended for D4's `drop` mapping once that shared mapping is confirmed.

Strong's ambiguous `Weight` unit remains **[TO VERIFY]**. No unit is inferred
from Hevy or chosen as a default. A future test explicitly using `unit_hint="kg"`
can expect unchanged raw weight values and `source_unit="kg"`; a pounds case
must use D4's conversion. Canonical index bases, exact blank-note/null handling,
and the workout-duration destination also await D4. No `set_id`, `log_id`,
canonical exercise identifier or `source_app` enum value was invented here.

All Strong `Distance`/`Seconds` and all Hevy `distance_km`/`duration_seconds`/
`superset_id` cells are blank. They were preserved as missing during validation,
not coerced to zero. The blank Strong metrics differ from S1's zero convention;
blank Hevy set durations differ from H2's example. Their source-format and D4
nullability acceptance remain [TO VERIFY]. Populated supersets, distance/set
duration preservation, pounds/miles headers, hour-token durations, note escaping,
and invalid-input behavior are not established by these fixtures. The only Hevy
`failure` row also has zero repetitions, so positive-repetition failure-flag
handling is not independently covered. These coverage limits did not justify
rewriting the completed CSVs.

**Validation scope:** source-file checks passed; adapter/Pydantic integration
and pytest tests were **not run**, because D4 and the project test setup are
missing. The inline check is not a replacement adapter or shared normalizer.

## Export specifications still [TO VERIFY]

- Confirm the reported timestamps, duration tokens, index bases and Hevy source
  vocabulary against authorized real exports separately; no such verification
  was performed here. Confirm locale/timezone semantics and D4's strict parsing.
- Strong `Distance` units, any encoded set types or nonnumeric `Set Order`
  tokens, and handling of formats beyond the documented duration patterns.
- Hevy index scope/reset, source-to-canonical set-type mapping and failure flags.
- Required versus optional columns, allowed simultaneous unit columns, duplicate
  header handling and the policy for conflicting unit hints.
- CSV dialect/encoding variants beyond the limited reports, escaped or multiline
  text behavior, decimal representations and unobserved missing-number cases.
  Do not convert blank fields to zero without D4's explicit rule.
- Workout grouping, workout duration storage, interval validation, and preservation
  of per-set duration and superset identifiers in D4's actual models.
- Canonical distance unit and conversion policy; weight normalization does not
  establish the distance convention.

Unknown formats and unsupported headers must fail with shared `IngestError`.
Detection must reject the other app and unrelated formats. The header-only
templates are not a specification of required-column subsets.

## Implementation and test handoff

After David's D4 implementation is available in this checkout:

1. Inspect its actual models, normalization, errors, adapter directory, registration
   and test conventions. Resolve the interface questions above with the D4 owner.
2. Implement only the two D6 adapters and their pipeline registration. Reuse D4's
   conversion, failed-set and date handling; leave hashing, storage and exercise
   matching with their existing owners.
3. Obtain team approval of the existing 12-row fixtures and their recorded
   AI-assisted/manual-insertion provenance. Confirm Strong's unit and D4's
   blank-field/type/index mappings. Review the documented coverage gaps without
   regenerating the files or accessing personal exports as part of this task.
4. Add tests under the existing ingestion test conventions:

| Check | Required evidence |
|---|---|
| Format detection | Strong and Hevy headers select their own adapters; each rejects the other and unrelated headers. |
| Unknown headers | Shared `IngestError` is raised rather than accepting an unsupported layout. |
| Canonical values | A few hand-selected fixture rows have independently calculated expectations for all preserved fields, including any index-base handling. |
| Weight handling | Strong explicit hint and ambiguous-weight behavior; Hevy kg/lbs header handling; shared source-unit retention. |
| Hevy time and notes | Workout duration equals parsed end minus start; set duration is separate; description, exercise notes and superset IDs survive. |
| Strong warning | Capture the required unverified-set-type warning and verify internal `normal` mapping without suppressing failed-set handling. |
| Shared normalization | Cover zero repetitions and any confirmed failure mapping without reimplementing D4. |
| Source representations | Exercise the reported timestamp/duration formats, Hevy source type spellings, quoted commas and observed empty fields without silently replacing blanks with zero. |

Expected conversions must use D4's actual conversion factor and state the chosen
tolerance in test comments. Issue #9 gives `225 lb = 102.0583 kg` as its reference
check; no new factor or tolerance is specified here. Duration expectations must
show the subtraction and conversion to seconds in comments.

Once D4, dependencies and fixture approval are available, run:

```powershell
uv run --python 3.11 pytest tests/ingest
```

This is the planned command, **not a reported test pass**. No adapter tests can
run in the current checkout. D6 remains incomplete until implementation,
fixture approval and the required tests are available.
