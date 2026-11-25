# Strong synthetic fixture

**synthetic, built from community headers**

Status: [synthetic.csv](synthetic.csv) contains **12 data rows**, validated with
Python 3.11.18 on **2026-11-25**, and parsed by the implemented Strong source
parser in the passing D6 test suite. Team approval is pending. The format remains
**[TO VERIFY against real exports]**, unverified against real application exports.
[header-template.csv](header-template.csv) remains a separate header-only reference.

## Provenance

The fixture values are **AI-assisted and manually inserted by Filip George
Bumbar**, as reported by the user. This is not a claim of independent human-only
authorship. Team approval of this provenance against issue #11's hand-written
fixture requirement remains **[TO VERIFY]**. No CSV rows were regenerated or
overwritten during validation.

## Documented headers

Column names come from [architecture plan section 2.2](../../../docs/milestone2-architecture-and-plan.md#22-input-formats-and-ingestion).
The order below is corroborated by the [community format reference](https://github.com/smyrick/sugarwod-to-hevy/blob/main/docs/STRONG_FORMAT.md)
and the [Intervals.icu opening post](https://forum.intervals.icu/t/import-strong-data-weightlifting-app/5531),
inspected on **2026-11-25**. Neither is a verified official export specification.

```csv
Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,Notes,Workout Notes,RPE
```

The plan also reports `Weight (kg)` in place of `Weight`. This baseline keeps
ambiguous `Weight`; its unit must be explicit in test metadata and passed as
`unit_hint`. Do not adopt the converter's Hevy-import kg assumption.

## Community conventions for this synthetic fixture

- Date pattern: `YYYY-MM-DD HH:MM:SS`, with padded numeric components.
- Workout duration: elapsed tokens such as `45m` or `1h 20m`.
- Set order: one-based, reported as restarting for each exercise.
- The reference describes UTF-8, commas and minimal CSV quoting. Quote fields
  containing commas or quotes; escape an embedded quote by doubling it.
- Blank notes/RPE and zero unused numeric metrics are reported. Do not treat
  a blank as zero or invent `NULL`/`NaN` sentinels. Preserve all 12 fields,
  including a trailing empty RPE field.

## Actual validation results

All 12 rows have exactly 12 columns in the documented order. All 12 timestamps
match the stated pattern and are valid calendar datetimes. All 47 nonempty
numeric cells parse as finite numbers; set indices and repetitions are integers.
No new numeric bounds were selected. Blank numerical cells were recorded as
missing, not replaced with zero.

There are two workouts, each with six rows, two exercises and three sets per
exercise. Source indices are `1, 2, 3` in each exercise group. Workout-level
duration and notes are consistent within each workout.

| Data rows | Workout / `workout_ts` | Workout duration | `workout_note` |
|---|---|---|---|
| 1-6 | Upper Body / `2026-11-10 18:00:00` | `45m`: `45 * 60 = 2700` seconds | Evening workout |
| 7-12 | Lower Body / `2026-11-12 17:00:00` | `50m`: `50 * 60 = 3000` seconds | Afternoon workout |

Data-row numbers below exclude the header; CSV line numbers are one greater.

## Source expectations and future canonical tests

These expectations follow the actual source values and issue #9's field names.
The implemented `StrongParser` tests verify source records against these values;
no canonical model is instantiated.
`rpe=None` on row 11 follows D4's specified nullable RPE. `failed=True` on row 12
follows `reps == 0`; all other rows have positive repetitions and no source
failure marker. All Strong rows must retain internal `set_type=normal` with the
warning required by issue #11.

| Data row | `exercise_name_raw` | Source index | Raw `Weight` | `reps` | `rpe` | `failed` |
|---:|---|---:|---:|---:|---|---|
| 1 | Bench Press | 1 | 60 | 10 | 7 | False |
| 2 | Bench Press | 2 | 65 | 8 | 8 | False |
| 3 | Bench Press | 3 | 70 | 6 | 9 | False |
| 4 | Barbell Row | 1 | 40 | 12 | 7 | False |
| 5 | Barbell Row | 2 | 45 | 10 | 8 | False |
| 6 | Barbell Row | 3 | 50 | 8 | 9 | False |
| 7 | Squat | 1 | 70 | 10 | 7 | False |
| 8 | Squat | 2 | 80 | 8 | 8 | False |
| 9 | Squat | 3 | 90 | 6 | 9 | False |
| 10 | Deadlift | 1 | 80 | 8 | 7 | False |
| 11 | Deadlift | 2 | 90 | 6 | None | False |
| 12 | Deadlift | 3 | 110 | 0 | 10 | True |

**Strong's weight unit is not declared in the CSV or confirmed fixture metadata
[TO VERIFY].** No default unit was assigned. Parser tests explicitly supply
`unit_hint="kg"`, expecting raw `weight` equal to the values above and
`source_unit="kg"`. This is a conditional test setup, not a declaration of the
fixture's unit. A pounds-hint parsing test retains raw 60 as 60 lb; final
`weight_kg` conversion and its tolerance must use D4. Parsing without a hint
raises `StrongParseError`. Do not infer units from similar Hevy values.

Preserve nonempty `Notes` as `set_note`: row 1 is `Controlled reps`, row 2 is
`Stable tempo`, row 6 is `Controlled movement`, row 7 is `Stable tempo`, and row 12
is `Attempt not completed`. Rows 3, 4, 5, 8, 9, 10 and 11 have blank notes;
the source parser preserves them as empty strings. Final canonical empty/null
and index-base handling await D4; source indices are preserved without offset.

`Distance` and `Seconds` are blank in all 12 rows. Preserve that missingness;
do not fill it with zero or copy workout duration into per-set `duration_s`.
Their canonical nullable handling and the workout-duration storage destination
remain [TO VERIFY] with D4.

## Coverage limits and remaining work

The populated fixture uses `45m` and `50m`, not the earlier proposed `1h 20m`.
These rows alone do not exercise hour tokens, pounds hints, `Weight (kg)`,
populated distance/set duration, commas or embedded quotes in notes, or invalid
input. Isolated temporary test inputs now cover those source-parsing cases,
including multiline notes, BOMs and header reordering. Weight conversion
remains D4's responsibility. Blank unused metrics differ from S1's reported
zero convention and remain subject to team/source-format review. These are
coverage/conformance limitations, not malformed CSV records; the file was kept
unchanged. See [the D6 implementation and handoff](../../../docs/d6-strong-hevy-adapters.md)
for the private parsing API, exact supported formats and remaining integration.

Strong source set-type encoding remains [TO VERIFY]. Do not manufacture export
markers for warm-up, failure or drop sets. Issue #11 requires the adapter to
treat sets as internal `normal` and log a warning; shared failed-set handling
still applies independently. The source parser exposes `mapped_set_type="normal"`,
detects `reps == 0` and emits one warning per successful parse. It does not infer
Strong set-type markers, normalize weights, assign canonical IDs or register
itself in a pipeline.

## Automated test result

The D6 ingestion suite passed **95 tests** under Python **3.11.18** in an
isolated temporary uv environment. Tests read this exact 12-row file without
modification; extra cases are programmatic inputs outside the fixture. Local
parser failures currently raise `StrongParseError`, not shared `IngestError`.
See the D6 document for the command and final run result.

## Completion status

- [x] Exactly 12 populated rows read and validated with Python 3.11.
- [x] AI-assisted values and manual insertion by Filip recorded as user-reported provenance.
- [x] Row-level source expectations and future canonical expectations documented.
- [x] Source detection, both unit hints, explicit kg header, unknown-header rejection and warning tests executed.
- [x] All 12 source records, missing RPE, zero-repetition failure and duration arithmetic tested.
- [ ] Team approves the fixture/provenance and confirms the Strong weight unit.
- [ ] D4 available; canonical expectations and remaining coverage reviewed.
- [ ] Canonical conversion, shared error translation and pipeline registration tested.
