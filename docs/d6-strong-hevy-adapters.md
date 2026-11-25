# D6: Strong and Hevy source parsing

Status: **source parsers and D4 integration implemented.** Both formats remain
**[TO VERIFY against real exports]**.

> **Integration update (2026-11-25).** D4 is merged. `StrongAdapter` and `HevyAdapter` implement `BaseAdapter` and are in
> the default registry of `ingest_workout_log`. Where a later section still says that D4 is missing or blocked, this
> note replaces it. Decisions taken:
> - Parse errors are reported as `IngestError`; nothing is stored.
> - Strong's `unit_hint` is an argument of `ingest_workout_log`; a file without a unit and without a hint is an error.
> - Set indices are stored as exported (Strong from 1, Hevy from 0). Distances are stored in kilometres.
> - Hevy `set_type = failure` means **taken to failure**. Only 0 reps make a set failed (`docs/indicator-spec.md` §1.1).
> - Negative numbers are errors; an RPE outside 0-10 is flagged and treated as missing.
> - Workout duration is parsed but not stored: the canonical model has no field for it.

## References

- [Architecture plan section 2.2](milestone2-architecture-and-plan.md#22-input-formats-and-ingestion): community headers and ingestion rules.
- [D6, issue #11](https://github.com/David-Mal/Uni-RagSystem/issues/11): adapter, warning, fixture and test requirements.
- [D4, issue #9](https://github.com/David-Mal/Uni-RagSystem/issues/9): shared models, normalization, storage and pipeline.
- [RFC](../RFC_Heuristic_Load_Fatigue_Analyzer.md): deterministic processing and failed-set exclusion.

## Dependency check: 2026-11-25

D4 remains unavailable on `feature/filip-d6-adapters`. The new
`src/ingest/adapters/` and `tests/ingest/` files are D6 source parsers and their
tests, not evidence that D4 has arrived. There is still no canonical model,
shared adapter base, normalization/error layer, registry, storage or ingestion
pipeline. No `pyproject.toml` or `uv.lock` is present. Issue #9's written contract
was inspected; an issue description is not an integrated interface.

| Missing D4 dependency | Remaining integration work |
|---|---|
| `CanonicalSet`, `CanonicalSets` and actual model imports | Construct validated canonical results, including IDs, index handling, nulls and note fields. |
| `BaseAdapter` | Connect the working parsers to the actual `detect(header_or_probe)` and `to_canonical(source)` interfaces. |
| Shared `normalize.py` | Convert raw weights to kg while retaining source units; reuse final failed/type/date handling rather than introduce a second normalizer. |
| Shared `IngestError` | Translate local parsing failures to the actual shared error contract. |
| Registry, `ingest_workout_log`, `IngestResult` | Register both adapters and confirm how Strong's hint reaches the pipeline. |
| Workout/storage interface and idempotency | Preserve workout duration separately from set duration; leave grouping, hashing and storage to D4. |

The plan illustrates `to_canonical(df)`; issue #9 requires a source path and says
not to hardcode CSV in the shared interface. D6 currently accepts CSV paths in its
source-specific parsers. Final adapters must use D4's actual interface. No
replacement canonical schema, `BaseAdapter`, shared `IngestError`, normalization
module, registry or persistence was added.

## Implemented parsing API

`StrongParser` and `HevyParser` live in `src/ingest/adapters/`. Each exposes:

- `detect(header)`: accepts decoded column names or a single CSV header record;
  returns a boolean without reading a file.
- `parse_source(path)`: reads a UTF-8 comma CSV and returns an ordered tuple of
  private, frozen source records. Strong also accepts `unit_hint="kg"` or
  `unit_hint="lb"`. The raw string cells are retained in a read-only snapshot.

For example, `StrongParser().parse_source(path, unit_hint="kg")` supplies a
deliberate unit decision; `HevyParser().parse_source(path)` uses its unit-bearing
header. These methods do not return `CanonicalSets` and have no
`to_canonical` or pipeline registration yet.

Common implemented behavior:

- Accept the complete documented header sets in any column order, with exactly
  one supported weight column and, for Hevy, one supported distance column.
  Reject missing, extra, duplicate, unrelated or ambiguous headers. This is a
  conservative supported format, not a claim about vendor-required subsets.
- Read UTF-8 with or without a BOM. Preserve CSV record order, duplicate rows,
  quoted commas, escaped quotes, multiline notes and text whitespace. Reject
  malformed CSV, invalid UTF-8 and incorrect row widths.
- Parse finite plain ASCII decimal numbers; repetition/index fields require
  integers. Only an empty cell is missing. Preserve numeric zero separately from
  absence. Reject `NULL`, `NaN`, whitespace-only numbers, decimal commas and
  unsupported numeric syntax instead of guessing.
- Require a nonempty exercise name and the documented source index base.
  Preserve raw numeric outliers without inventing physiological limits.
- Preserve source weights and units without conversion, and source distances
  with their original column names. Preserve source indices without offset,
  deduplication, exercise matching or canonical ID generation.
- Use only the Python standard library, deterministic date/number parsing and
  no network or LLM calls. Invalid input raises local `StrongParseError` or
  `HevyParseError` (`ValueError` subclasses), **not D4's missing `IngestError`**.

Missing optional numeric cells become `None`; missing notes stay empty strings.
Missing Hevy superset IDs become `None`, while populated IDs remain opaque
strings, including leading zeros. Source parsing accepts an empty Strong
workout duration as `None`. Canonical nullability and additional source missing
conventions remain [TO VERIFY]. Header-only files produce no rows after header
and unit validation; the templates are not populated fixtures.

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

The templates follow S1/S2's Strong order and H2's Hevy order. Parsing uses column
names and the complete documented header sets, so reordered columns are accepted.
Hevy month parsing uses a fixed English lookup, independent of the host locale.
Both parsers return naive local datetimes without guessing a timezone; real-export
timezone semantics and D4's parsing API remain [TO VERIFY].

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

Implemented Strong behavior:

- `Date` must use `YYYY-MM-DD HH:MM:SS` and be a valid calendar timestamp.
- Workout duration accepts elapsed minute, hour, or spaced hour/minute tokens,
  such as `45m`, `3h`, `1h 20m`; seconds and clock-time guesses are rejected.
- `Set Order` is an integer starting at one. Per-exercise reset/contiguity is
  not imposed by the parser.
- `Weight (kg)` establishes kg. Ambiguous `Weight` requires an explicit
  `unit_hint="kg"` or `"lb"`; missing/unsupported hints and a pounds hint
  conflicting with `Weight (kg)` raise `StrongParseError`. Values remain raw.
- Every parsed row has `mapped_set_type="normal"` and
  `source_failure_flag=False`; `failed` is true for zero repetitions.
  No source warm-up, drop or failure encoding is inferred.
- Every successful parse logs one warning through the module's standard-library
  logger: "Strong source set types are unverified; treating all parsed sets as
  normal." This includes a zero-repetition row, whose type stays normal.

The warning and hint forwarding must be reconciled with D4's actual logging and
pipeline conventions when available [TO VERIFY]. The issue's normal-set
requirement applies regardless of additional community claims about Strong.

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

Implemented Hevy behavior:

- Start/end timestamps must use `D MMM YYYY, HH:mm` with English month
  abbreviations. Workout duration is end minus start in seconds, including
  intervals crossing midnight; an end before start is rejected.
- `set_index` is an integer starting at zero; reset scope is not inferred.
- Independently accept `weight_kg`/`weight_lbs` and
  `distance_km`/`distance_miles`. Weight units become source `kg`/`lb`;
  weights and distances remain unconverted.
- Preserve description as workout notes, exercise notes as supplied, and
  superset IDs as opaque source text. Per-set duration stays separate from
  derived workout duration.
- Map documented source strings using issue #9's vocabulary:

| Source type | Candidate D4 type | Source failure flag |
|---|---|---|
| `normal` | `normal` | False |
| `warmup` | `warmup` | False |
| `dropset` | `drop` | False |
| `failure` | `failure` | False (taken to failure, see the update above) |

The source parser exposes `failed = reps == 0` and keeps the original type.
Unknown source spellings are rejected. These candidate strings are not a new
canonical enum. Final mapping must reuse the real shared implementation
[TO VERIFY]; no source type is inferred from weight or RPE.

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

### Fixture validation: 2026-11-25

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
warning. Hevy weights have kg established by `weight_kg`; the source parser
currently exposes `dropset -> drop` using the written D4 vocabulary.

Strong's ambiguous fixture `Weight` unit remains **[TO VERIFY]**. No unit is
inferred from Hevy or chosen as a default. The parser tests explicitly use
`unit_hint="kg"` as a conditional test setting, expecting unchanged raw weights
and `source_unit="kg"`. A pounds-hint parsing test preserves the same raw value
with source `lb`; final kg normalization must use D4. Canonical index bases,
exact blank-note/null handling and the workout-duration destination also await
D4. No `set_id`, `log_id`,
canonical exercise identifier or `source_app` enum value was invented here.

All Strong `Distance`/`Seconds` and all Hevy `distance_km`/`duration_seconds`/
`superset_id` cells are blank. They were preserved as missing during validation,
not coerced to zero. The blank Strong metrics differ from S1's zero convention;
blank Hevy set durations differ from H2's example. Their source-format and D4
nullability acceptance remain [TO VERIFY]. These fixture files do not cover
populated supersets, pounds/miles variants, hour tokens, escaped notes or
positive-repetition failure flags. Those cases are now exercised by isolated
programmatic test inputs in temporary directories. The completed CSVs and
header templates remain unchanged.

## Automated parsing validation: 2026-11-25

**95 tests passed** with Python **3.11.18** and pytest **9.2.0**. Pytest was
installed only into a temporary isolated uv environment; no project dependency, permanent validation
script or unrelated infrastructure was added. With that environment active,
the executed test invocation was:

```powershell
$env:VIRTUAL_ENV = "$d6TestTemp\venv"
$env:UV_CACHE_DIR = "$d6TestTemp\uv-cache"
$env:PYTHONDONTWRITEBYTECODE = "1"
uv run --no-project --active --offline python -B -m pytest tests/ingest -q -p no:cacheprovider --confcutdir=tests/ingest --basetemp "$d6TestTemp\pytest-verified"
```

`$d6TestTemp` represents the isolated environment's temporary parent directory;
the installed uv executable was invoked by its absolute path. The final run
returned **95 passed in 1.11s**, exit code **0**. The `--confcutdir` limits
collection to D6 ingestion tests; `PYTHONDONTWRITEBYTECODE=1` and the disabled cache provider avoid permanent
test artifacts. This is source-parser validation, not a D4 integration pass.

Tests cover both real local synthetic files (24 rows total), supported header
variants/reordering, cross-app rejection, missing/unknown/duplicate/ambiguous
headers, row width, strict timestamps, malformed CSV/UTF-8, numeric errors and
overflow, blank-versus-zero values, source index bases, deterministic records,
Strong hints and warning, Hevy duration arithmetic and all four type mappings.
Separate temporary inputs cover pounds/miles, hour tokens, quoted/multiline
notes, populated supersets, optional metrics and positive-repetition failures.
Expected source values and duration arithmetic are independently stated in
assertions/comments; kg conversion is deliberately not implemented.

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

Final D4 adapters must report unknown formats and unsupported headers through
shared `IngestError`. Current source parsers reject them with their local errors.
Both detectors reject the other app and unrelated formats. The header-only
templates do not establish vendor-required column subsets.

## Remaining D4 integration and human review

After D4 is available locally:

1. Read its actual models, normalization, errors, adapter interfaces and registry.
   Adapt the two source parsers to those interfaces without a parallel schema.
2. Implement canonical conversion and shared kg normalization, reconcile
   failed/type/date handling, and translate local parse errors to `IngestError`.
   Preserve source units and notes through the actual shared model.
3. Register the adapters in the real ingestion pipeline and resolve Strong hint
   forwarding, workout duration storage, canonical index and distance policies.
   Leave hashing, deduplication, exercise matching and storage to D4.
4. Add canonical/pipeline tests using the existing fixture expectations and D4's
   actual conversion factor/tolerance. Issue #9 gives `225 lb = 102.0583 kg`
   as a reference check; no new factor is defined here.
5. Run the integrated ingestion suite through the eventual project configuration.
   Current parser tests remain useful independent coverage.

Human/team work remains: approve the recorded AI-assisted fixture provenance
against the hand-written requirement, confirm the Strong fixture's unit,
review the conservative supported formats, and verify compatibility against
separately authorized real exports. No real exports or personal logs were used.
D6 is ready for review of functional parsing, but final canonical ingestion and
issue acceptance are not complete.
