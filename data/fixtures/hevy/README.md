# Hevy synthetic fixture

**synthetic, built from community headers**

Status: [synthetic.csv](synthetic.csv) contains **12 data rows**, validated with
Python 3.11.18 on **2026-11-25**. Team approval is pending. The format remains
**[TO VERIFY against real exports]**, unverified against real application exports.
[header-template.csv](header-template.csv) remains a separate header-only reference.

## Provenance

The fixture values are **AI-assisted and manually inserted by Filip George
Bumbar**, as reported by the user. This is not a claim of independent human-only
authorship. Team approval of this provenance against issue #11's hand-written
fixture requirement remains **[TO VERIFY]**. No CSV rows were regenerated or
overwritten during validation.

## Documented headers

Column names follow [architecture plan section 2.2](../../../docs/milestone2-architecture-and-plan.md#22-input-formats-and-ingestion).
Order and quoted headers match the [public community sample](https://github.com/matanabudy/workout-data-sync/blob/main/examples/hevy_export_sample.csv).
The [Gym Log guide](https://gymlog.info/analyze/hevy-workout-data/) supplies further
conventions. Both were inspected on **2026-11-25**; neither verifies an official
Hevy export schema. This validation did not insert source example rows into the
fixture.

```csv
"title","start_time","end_time","description","exercise_title","superset_id","exercise_notes","set_index","set_type","weight_kg","reps","distance_km","duration_seconds","rpe"
```

The documented alternatives are `weight_lbs` instead of `weight_kg`, and
`distance_miles` instead of `distance_km`. Selecting kg/km here prepares one
documented variant; it does not assert that all Hevy exports use it. Weight and
distance settings are independent according to Gym Log. No extra columns or
required-column subsets are inferred from this sample.

## Community conventions for this synthetic fixture

- Timestamp pattern: `D MMM YYYY, HH:mm`, with English month abbreviations;
  double-quote timestamps because they contain commas. Do not let a spreadsheet
  change their appearance or use locale-dependent month names.
- Gym Log reports zero-based indices within an exercise. The limited sample does
  not corroborate resets; scope/reset remains [TO VERIFY].
- Reported raw set types: `normal`, `warmup`, `dropset`, `failure`. Preserve these
  spellings; `dropset` is not the canonical spelling `drop` from issue #9.
- The sample has quoted text/headers, unquoted numbers, empty quoted notes,
  empty unquoted superset/distance fields and zero `duration_seconds`. Do not
  conflate zero with absence or invent missing-value tokens for other fields.

## Actual validation results

All 12 rows have exactly 14 columns in the documented order. All 24 start/end
timestamp cells match the stated pattern and form valid datetimes; parsing used
an explicit English-month lookup, independent of the host locale. Every end time
is after its start. All 47 nonempty numeric cells parse as finite numbers;
indices and repetitions are integers. No new numeric bounds were selected.

There are two six-row workouts and four exercise groups. Each exercise group
uses source indices `0, 1, 2`. This confirms the synthetic fixture's chosen
convention, not the indexing of real exports. The source type counts are
**2 warmup, 8 normal, 1 dropset, 1 failure**, with no unknown values.

| Data rows | Workout / `workout_ts` | End time | Expected workout duration | `workout_note` from `description` |
|---|---|---|---|---|
| 1-6 | Upper Body / `2026-11-10 18:00:00` | `18:45` | `45 * 60 = 2700` seconds | Evening workout |
| 7-12 | Lower Body / `2026-11-12 17:00:00` | `17:50` | `50 * 60 = 3000` seconds | Afternoon workout |

All six rows in each workout agree on start, end and description. Derived
workout duration is separate from `duration_seconds`, which is blank in every
row. Data-row numbers below exclude the header; CSV line numbers are one greater.

## Expected values for future adapter tests

These are source-derived expectations under issue #9's contract, not results
from an adapter or an instantiated replacement schema. The `weight_kg` header
unambiguously establishes kg; values below should remain unchanged and retain
`source_unit="kg"`. Row 11 should yield `rpe=None`. Row 12 must yield `failed=True`
from zero repetitions independently of the future source failure-flag mapping;
the other rows have positive repetitions and no source failure type.

| Data row | `exercise_name_raw` | Source index | `weight_kg` | `reps` | `rpe` | Raw `set_type` | `failed` |
|---:|---|---:|---:|---:|---|---|---|
| 1 | Bench Press | 0 | 20 | 15 | 5 | warmup | False |
| 2 | Bench Press | 1 | 60 | 10 | 7 | normal | False |
| 3 | Bench Press | 2 | 65 | 8 | 8 | normal | False |
| 4 | Barbell Row | 0 | 40 | 12 | 7 | normal | False |
| 5 | Barbell Row | 1 | 45 | 10 | 8 | normal | False |
| 6 | Barbell Row | 2 | 30 | 12 | 9 | dropset | False |
| 7 | Squat | 0 | 40 | 12 | 5 | warmup | False |
| 8 | Squat | 1 | 70 | 10 | 7 | normal | False |
| 9 | Squat | 2 | 80 | 8 | 8 | normal | False |
| 10 | Deadlift | 0 | 80 | 8 | 7 | normal | False |
| 11 | Deadlift | 1 | 90 | 6 | None | normal | False |
| 12 | Deadlift | 2 | 110 | 0 | 10 | failure | True |

Use D4's actual set-type mapping: the intended canonical types for `normal`,
`warmup` and `failure` have the corresponding issue #9 names; source `dropset`
is intended to map to canonical `drop`. That mapping remains [TO VERIFY] with
the shared implementation, and must not be replaced with an adapter-local enum.
Canonical index-base handling also awaits D4; the table records source indices.

Preserve nonempty `exercise_notes` as `set_note`: rows 1 and 7 are `Warmup set`,
row 2 is `Controlled reps`, row 6 is `Reduced load`, and row 12 is
`Attempt not completed`. Rows 3, 4, 5, 8, 9, 10 and 11 have blank notes. Empty
note representation, blank distance/set duration, and blank superset handling
await D4; no blank was converted to zero or a fabricated identifier.

## Coverage limits and remaining work

Every `superset_id`, `distance_km` and `duration_seconds` is blank. Nonempty
superset preservation, set duration distinct from workout duration, distance
conversion and lbs/miles variants are therefore not exercised. Blank set
duration differs from the zero duration shown in the inspected public example
and needs team/source-format review. A `failure` row with positive repetitions,
escaped quotation marks in notes, and invalid-input rejection are not covered.
The existing quoted timestamps do exercise CSV fields containing commas.
These are coverage/conformance limitations, not malformed CSV records; the file
was kept unchanged. See [the D6 handoff](../../../docs/d6-strong-hevy-adapters.md).

## Completion status

- [x] Exactly 12 populated rows read and validated with Python 3.11.
- [x] AI-assisted values and manual insertion by Filip recorded as user-reported provenance.
- [x] Row-level future expectations and duration arithmetic documented without adapter output.
- [ ] Team approves the fixture/provenance and blank-field conventions.
- [ ] D4 available; canonical mapping and remaining coverage reviewed.
- [ ] Adapter detection, unit, unknown-header and preservation tests executed.
