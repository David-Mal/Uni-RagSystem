# OpenGym export format

Ground truth for the OpenGym adapter (D5), the simulator (Fi2) and the tests. Everything below was read from two real
exports: `data/fixtures/opengym/david_anonymized.csv` (211 rows, 26 columns) and
`data/fixtures/opengym/fineas_anonymized.csv` (276 rows, 21 columns). Anything the files cannot show is marked
`[TO VERIFY]`; do not guess it in code. Sections A-F come from D2; the numbered sections at the end are Fineas's
comparison (F1).

## A. How to export

- David's export: OpenGym on **iOS**, made on 2026-11-25 with the app's own workout export. Exact menu path and app
  version: `[TO VERIFY]`.
- The app produces **one CSV file** with all workouts, named `opengym-workouts-YYYY-MM-DD.csv` (date of the export;
  seen once, `[TO VERIFY]`).
- Keep the raw file outside the repository. `scripts/anonymize_opengym.py` writes the committed fixture.

**Anonymization of `david_anonymized.csv`:** no date shift, no blanked columns. The file holds no names, emails, account
or device ids. The only free text is three workout names (`Upper1`, `UpperBody2`, `Vineri`) and two workout notes, kept
on purpose because one of them is a real unit error. The fixture is therefore byte-identical to the app export.

**What the fixture does not contain:** no session with RPE or RIR (never logged by either member), and no per-set note.
Two sessions have a workout note. The log spans 2026-11-05 to 2026-11-25, about three weeks, so it is **shorter than the
5 weeks of history** required by plan §2.5 and is a natural partial-abstention case.

## B. File format

| Property | Value |
|---|---|
| Type | CSV, one row per **set**, one header row |
| Encoding | UTF-8 **with BOM** (`EF BB BF`); read with `utf-8-sig` |
| Separator / line ending | `,` / CRLF, with a trailing newline |
| Quoting | None seen. A note with a comma or a quote would need it; use a real CSV reader `[TO VERIFY]` |
| Decimal mark | `.` (`12.5`); whole numbers have no decimals (`50`) |
| Empty value | Empty cell. `0` is a real value, not "missing" |
| Row order | By `start_time` ascending, then exercise order inside the workout, then `set` |

## C. Columns

Order as in David's file. Columns marked † are missing from Fineas's file, so map by **header name, never by position**.

| Column | Type | Example | Unit | Nullable | Meaning |
|---|---|---|---|---|---|
| `date` | `YYYY-MM-DD` | `2026-11-05` | local date | no | Same day as `start_time` on every row |
| `start_time` | `YYYY-MM-DD HH:MM` | `2026-11-05 14:22` | local time | no | Workout start, repeated on all rows of the workout |
| `end_time` | `YYYY-MM-DD HH:MM` | `2026-11-05 15:59` | local time | no | Workout end |
| `workout` | text | `Upper1` | | no | Workout name; not unique |
| `workout_note` | text | `Cable high row is lbs nu kg` | | yes | Note on the whole workout, **repeated on every row** |
| `exercise` | text | `Cable Pulldown` | | no | Catalog name |
| `exercise_id` | 4-digit text | `0198` | | no | OpenGym catalog id; keep leading zeros. **Not** a free-exercise-db id |
| `body_part` | text | `back` | | no | Coarse catalog group |
| `superset_id` | | (empty) | | yes | Never filled `[TO VERIFY]` |
| `set` | integer | `1` | | no | 1-based, restarts for each exercise of a workout, no gaps |
| `set_type` | enum | `normal` | | no | `normal`, `warmup`, `failure` seen; others `[TO VERIFY]` |
| `side` | | (empty) | | yes | Never filled `[TO VERIFY]` |
| `weight` | number | `12.5` | see `unit` | no | `0` = no added load (bodyweight) |
| `unit` | text | `kg` | | no | Per row; only `kg` seen. Spelling for pounds `[TO VERIFY]` |
| `reps` | integer | `12` | | no | `0` = failed set |
| `rpe` | | (empty) | | yes | Never filled `[TO VERIFY]` |
| `rir` | | (empty) | | yes | Never filled `[TO VERIFY]` |
| `distance_km` | | (empty) | km by name | yes | Never filled `[TO VERIFY]` |
| `seconds` | | (empty) | s by name | yes | Never filled `[TO VERIFY]` |
| `incline` | | (empty) | | yes | Never filled `[TO VERIFY]` |
| `resistance_level` † | | (empty) | | yes | Never filled `[TO VERIFY]` |
| `note` | | (empty) | | yes | Presumably the exercise note; never filled `[TO VERIFY]` |
| `set_note` † | | (empty) | | yes | Presumably the set note; never filled `[TO VERIFY]` |
| `tempo` †, `bands` †, `set_color` † | | (empty) | | yes | Never filled `[TO VERIFY]` |

## D. Encoding and mapping to the canonical fields (plan §2.2, issue D4)

| Canonical field | OpenGym source | Encoding |
|---|---|---|
| workout timestamp | `start_time` | Naive local time, minute resolution, **no timezone** |
| workout duration | `end_time` - `start_time` | Derived |
| workout name | `workout` | As is |
| exercise name | `exercise` | As is; `exercise_id` is a better alias key than the name |
| set index | `set` | 1-based per exercise and workout |
| set type | `set_type` | `warmup` = warm-up, `normal` = normal, `failure` = **taken to failure, reps completed**. `drop`: `[TO VERIFY]` |
| failed set | `reps` | `reps = 0`, on a `normal` row. **Not** `set_type=failure` |
| weight | `weight` + `unit` | Unit is per row, not per profile |
| reps | `reps` | Integer |
| RPE | `rpe` | Never filled; value format `[TO VERIFY]` |
| distance / time | `distance_km`, `seconds` | Never filled |
| exercise / set notes | `note`, `set_note` † | Never filled |
| workout notes | `workout_note` | Deduplicate to one note per workout |
| superset | `superset_id` | Never filled |

Every canonical field has an OpenGym column; a drop-set marker was not seen. OpenGym columns with no canonical field:
`date` (redundant), `body_part`, `side`, `rir`, `incline`, `resistance_level`, `tempo`, `bands`, `set_color`.

## E. Example rows (real)

```
date,start_time,end_time,workout,workout_note,exercise,exercise_id,body_part,superset_id,set,set_type,side,weight,unit,reps,rpe,rir,distance_km,seconds,incline,resistance_level,note,set_note,tempo,bands,set_color
2026-11-05,2026-11-05 14:22,2026-11-05 15:59,Upper1,Both sets 12 w 50 lat pulldowns,Barbell Close-Grip Bench Press,0030,upper arms,,1,failure,,45,kg,10,,,,,,,,,,,
2026-11-11,2026-11-11 16:19,2026-11-11 18:13,UpperBody2,,Dumbbell Incline Bench Press,0314,chest,,1,warmup,,30,kg,15,,,,,,,,,,,
2026-11-12,2026-11-12 15:19,2026-11-12 17:05,Upper1,Cable high row is lbs nu kg,Cable High Row (Kneeling),0167,back,,1,normal,,80,kg,15,,,,,,,,,,,
2026-11-13,2026-11-13 16:16,2026-11-13 17:17,Vineri,,Lever Seated Crunch,1452,waist,,3,normal,,35,kg,0,,,,,,,,,,,
```

In order: a set taken to failure (completed), a warm-up, a row whose unit is contradicted by its note, and a failed set
(`reps=0`).

## F. Quirks and open questions

1. **`unit` can be wrong.** The note "Cable high row is lbs nu kg" ("nu" = "not") contradicts `unit=kg`. The columns
   alone cannot reveal it. `Cable High Row (Kneeling)` is logged only as 70, 80 and 90 "kg", so its rows in other
   workouts may be in pounds too. Never convert automatically; surface a logging-quality flag.
2. **`set_type=failure` is not a failed set** (45 kg x 10 completed).
3. **Workout notes repeat on every row** (20 rows each).
4. **Weight 0** is used for `Pull-Up` and `Decline Sit-Up` (12 sets): no added load, not a 0 kg lift.
5. **Reps above 10 are frequent** (74 of 211 sets), so e1RM exclusions will be common.
6. **At most 3 sets per exercise and workout**, so there are few points per session.
7. `[TO VERIFY]` with a small test export: pounds, RPE/RIR, supersets, drop sets, `side`, notes with commas or quotes,
   timed or distance exercises, and the exact export menu and app version.

## Differences observed in a second export

Compared files (CSV exports from the OpenGym app; A made on 2026-11-24, B refreshed to the committed export of
2026-11-25, which adds one workout):

| | Export A (`fineas_anonymized.csv`, F1) | Export B (`david_anonymized.csv`, D2) |
|---|---|---|
| Data rows (one row = one set) | 276 | 211 |
| Workouts (distinct `start_time`) | 19, 2026-10-26 to 2026-11-24 | 11, 2026-11-05 to 2026-11-25 |
| Distinct exercises | 21 | 27 (7 shared with A) |
| Sets per workout | 12-17 | 10-26 |
| Columns | **21** | **26** |

Both files are UTF-8 **with BOM**, comma-separated, **CRLF** line endings, a header row, a trailing newline, rows sorted
by `start_time` ascending and decimal point `.` (`12.5`, `17.5`, `27.5`, `7.5`). No value is quoted in either file.
`data/fixtures/opengym/.gitattributes` marks the fixtures `-text` so git keeps the BOM and CRLF byte-exact on every OS.

### 1. Column sets differ

Columns present in both, in this order:
`date, start_time, end_time, workout, workout_note, exercise, exercise_id, body_part, superset_id, set, set_type,
side, weight, unit, reps, rpe, rir, distance_km, seconds, incline`.
Then:

- **Export A** ends with `note` (21 columns).
- **Export B** continues with `resistance_level, note, set_note, tempo, bands, set_color` (26 columns). In B, `note`
  is therefore no longer the last column.

Consequence for the adapter (D5): **map columns by header name, never by position**. Treat
`resistance_level, set_note, tempo, bands, set_color` as optional. Why the sets differ is unknown: app version,
platform or an export setting. `[TO VERIFY]` David's app runs on iOS; version not recorded. Fineas's export
was made from the app's default CSV export.

Columns that are **empty in every row of both files**: `superset_id, side, rpe, rir, distance_km, seconds, incline`,
plus B's `resistance_level, note, set_note, tempo, bands, set_color`. Their encoding when filled cannot be derived
from these files `[TO VERIFY]`. Do not guess it in the adapter.

### 2. Units

- `unit` is a **per-row** column. It is `kg` on every row of both files, so neither export shows how an `lb`
  profile is encoded. `[TO VERIFY]` Someone should export a small test log with the unit set to lb.
- **The unit column can be wrong.** In B, the workout on 2026-11-12 has the workout note
  `"Cable high row is lbs nu kg"` ("nu" = "not" in Romanian): those rows say `unit=kg` but the user means lb. This is a
  real-world `logging_quality_issue` / unit-mix case. The adapter cannot detect it from the columns. It belongs to note
  handling and is a good D5 trap fixture.

### 3. Set types, failed sets and warm-ups

| `set_type` value | Export A | Export B |
|---|---|---|
| `normal` | 266 | 208 |
| `warmup` | 10 (always `set` = 1) | 2 (`set` = 1) |
| `failure` | 0 | 1 |

- **`set_type=failure` does NOT mean a failed set.** The only `failure` row in B is `Barbell Close-Grip Bench Press,
  45 kg x 10`: reps were completed and the set was taken *to* failure. D4's rule `failed = reps == 0 or flagged`
  must not derive the flag from `set_type=failure`. Map it to canonical `set_type=failure` with `failed=False`
  when reps > 0.
- **A failed set appears as `reps=0` on a `normal` set.** B has one: `Lever Seated Crunch, 35 kg x 0`. A has none.
- Warm-ups exist only as `set_type=warmup` and are always set 1 in these files. No other warm-up marker was seen.
- `drop` sets: not seen in either file `[TO VERIFY]`.

### 4. RPE / RIR

Neither user logs RPE or RIR: the `rpe` and `rir` columns are empty on all 487 rows. Consequences:
- Every real-data analysis hits the "no RPE" paths: effective sets are counted and flagged `no_rpe`, and RPE drift
  is not assessed. The RPE-based hypotheses (`fatigue_accumulation` via drift) **cannot be exercised on real data**.
  They need the simulator (Fi2).
- The RPE value format (integer? half steps? `8.5`?) cannot be derived from these files `[TO VERIFY]`.

### 5. Notes

- **Export A has no free text at all**: `workout_note` and `note` are empty everywhere.
- **Export B uses only `workout_note`.** It has 2 distinct notes, and the note is **repeated on every row of its
  workout** (20 rows each). The adapter must deduplicate it to one workout-level note, otherwise the gate would see it
  20 times.
- Notes can be in **Romanian or mixed language** ("lbs nu kg"). The plan says everything is in English, so the
  extractor and the gate will meet non-English real notes. This matters for the real-note probe (§2.4 control 4).
- Neither file has a note about pain or discomfort. See `data/fixtures/real_notes_probe.txt`.

### 6. Weights, reps and bodyweight exercises

- `weight=0` is used for bodyweight exercises: `Weighted Pull-Up` in A (4 sets) and `Pull-Up` and `Decline Sit-Up` in
  B (12 sets). It means "no added load", not a 0 kg set. e1RM and tonnage over these sets are meaningless without
  bodyweight. D3 should state that weight-0 sets are excluded from e1RM and contribute 0 to tonnage, or else add
  bodyweight `[decision for D3]`.
- **reps > 10 is very common**: 111 of 276 sets (40%) in A and 74 of 211 (35%) in B. The e1RM rule
  "reps > 10 excluded from e1RM" will drop a large share of real sets, especially accessories. This is not a bug,
  but D3/D8 should expect many exclusion flags on real data.
- Weights use `.` decimals in 2.5 kg steps. No impossible values were seen.

### 7. Exercise names and ids

- `exercise_id` is an **OpenGym-internal 4-digit catalog id** (e.g. `0025` = Barbell Bench Press), not a free-exercise-db
  id. `body_part` uses a coarse vocabulary (`back, chest, lower arms, lower legs, shoulders, upper arms, upper legs,
  waist`). It looks like the ExerciseDB catalog `[TO VERIFY]` and does not match the free-exercise-db muscle enum.
- The id is **consistent across both exports**: every name maps to exactly one id and every id to exactly one name. It
  is therefore a better alias key than the name for M1's matcher.
- **Variants are separate catalog entries**, e.g. `Cable Straight Arm Pulldown` (`0238`) vs
  `Cable Straight Arm Pulldown V. 2` (`6036`), and `Dumbbell Hammer Curls (With Arm Blaster)` (`2402`) vs
  `Dumbbell Hammer Curl V. 2` (`0312`). Equipment and attachments appear in parentheses: `(V-Bar)`, `(With Rope)`,
  `(Rope Equipment)`, `(Kneeling)`. Machine exercises are prefixed `Lever` and Smith-machine ones `Smith`.
- Typos come from the app catalog itself: `Cable Cross-Over Revers Fly`.
- All 41 distinct names are in `data/exercises/seed_names.txt` with a best-guess free-exercise-db id (35 of 41). The
  6 left empty are ambiguous: `Barbell Wrist Curl` (palms up or down?), `Cable Pulldown` (grip?), `Dumbbell Rear Fly`
  (seated, bent-over or incline?), and three with no close entry (`Cable Incline Rear Delt Fly With Back Support`,
  `Cable Leaning Lateral Raise`, `Decline Sit-Up`).

### 8. Timestamps and workout names

- `date` is `YYYY-MM-DD`. `start_time` and `end_time` are `YYYY-MM-DD HH:MM`: **minute resolution, no seconds, no
  timezone**. Treat them as naive local time (D4). `date` is redundant with `start_time` in both files.
- All sets of a workout share the same `start_time`/`end_time`. The workout key is (`start_time`, `workout`), and
  `set` restarts at 1 for each exercise.
- Workout names are free text and partly non-English (`Umeri brate` = "shoulders arms", `Vineri` = "Friday"). Several
  workouts can share a name (`Upper1` occurs in both files and on many dates), so the name is not a key.

### 9. Anonymization of export A

`scripts/anonymize_opengym.py` was run with no date shift and no blanked columns. The file holds no names, emails,
account or device ids, and no free-text notes. The only free text is the workout names listed above, which identify
nobody. The committed fixture is therefore **byte-identical** to the app export. This was kept on purpose so the adapter
is tested against the real format. Dates were not shifted, because both members' logs overlap in time (e.g. both
trained on 2026-11-24) and a shift applied to only one file would break that alignment.

### Open questions raised by this comparison

1. Why do the two exports have different column sets? (app version, platform, export option) `[TO VERIFY]`
2. How does an `lb` profile look: does `unit` change per row, and are values converted? `[TO VERIFY]`
3. What is the encoding of `rpe`, `rir`, `superset_id`, `side` and `drop` sets when used? Needs a small test export
   with these features turned on.
4. D3: how to treat weight-0 (bodyweight) sets in e1RM and tonnage.
5. D3/D5: a note that contradicts the `unit` column ("lbs nu kg"). Should this be flagged as `unit_mix` by the note
   pipeline, or only reported as `logging_quality_issue`?
