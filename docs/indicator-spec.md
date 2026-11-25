# Indicator specification

Version 1 (issue D3). This is the contract for the tools (D8, F7, M2, M3) **and** for the independent reference
implementation (P3). Both are written from this text. If code and text disagree, the text decides; if the text is
ambiguous, fix the text first.

Every threshold is a key in [`configs/indicators.yaml`](../configs/indicators.yaml), written here as `[section.key]`. The
defaults are tuned on the dev set only and frozen before the golden logs layer is frozen. Nothing in this document is an
injury or health statement.

## 1. Common definitions

### 1.1 Input

Canonical sets (issue D4). Fields used: `set_id`, `workout_ts`, `exercise_id`, `set_type`
(`warmup`/`normal`/`failure`/`drop`), `weight_kg`, `reps`, `rpe`, `failed`. Any of `weight_kg`, `reps`, `rpe`,
`exercise_id` may be missing (`None`).

- **Units.** `weight_kg` is always kilograms (1 lb = 0.45359237 kg). Results are in kilograms.
- **`set_type = failure`** means the set was taken to failure. It is **not** a failed set.
- **Failed set.** `failed` is true, or `reps = 0`.
- **Date.** The calendar date of `workout_ts`, local time, no timezone conversion.
- **Session.** One exercise on one date. Two workouts on the same date form one session.

### 1.2 Working set

A set is a **working set** if it is not a warm-up and not failed. Drop sets and sets taken to failure are working sets.
A set with missing reps that is not failed is still a working set. Each indicator adds its own requirements below.

### 1.3 Reasons for exclusion

A set is counted under the **first** reason that applies, in this order: `warmup`, `failed`, then the indicator's own
reasons in the order they are listed in its section. Excluded sets are counted, never silently dropped.

### 1.4 `as_of` and windows

- `as_of` is the date of the **last working set of the whole log** (all exercises), unless the caller passes a date.
  No tool reads the clock. Two indicators narrow this default: load (§5) uses the last set valid for its metric, and
  weekly sets (§4) the last set of the log.
- `days_before = as_of - date(set)` in whole days. A set with `days_before < 0` is ignored.
- **Analysis window** = `0 <= days_before < 7 * [window.analysis_weeks]` (6 weeks, 42 days). Days 0 and 41 are inside, day
  42 is outside.

### 1.5 Least-squares slope

For points `(x_i, y_i)`: `slope = sum((x_i - mean(x)) * (y_i - mean(y))) / sum((x_i - mean(x))^2)`. `x` is in **weeks**:
`x_i = (date_i - date_first).days / 7`, where `date_first` is the date of the first point. Dates are distinct by
construction, so the denominator is positive with two or more points.

### 1.6 Rounding

Values keep full floating-point precision. Only the `summary` for the model is rounded, to
`[rounding.summary_decimals]` (2) decimals, half to even (Python `round`). Comparisons use unrounded numbers with an
absolute slack of `1e-9` on inclusive bounds.

## 2. Estimated 1RM (`compute_e1rm_and_drift`, part 1)

**Definition.** The strength trend of one exercise over the analysis window.

**Valid set:** a working set of the exercise, inside the analysis window, that passes, in this order:

| Reason if it fails | Requirement |
|---|---|
| `missing_reps` | `reps` is present |
| `no_load` | `weight_kg` is present and > 0. Weight 0 means bodyweight only, so e1RM is undefined |
| `reps_gt_max` | `reps <= [e1rm.max_reps]` (10, inclusive) |

**Formulas** (w = `weight_kg`, r = `reps`):

| Series | Formula | Set used |
|---|---|---|
| Epley (primary) | `w * (1 + r / 30)` | every valid set |
| Brzycki (sensitivity) | `w * 36 / (37 - r)` | every valid set |
| RPE-adjusted | `w * (1 + rtf / 30)`, `rtf = r + (10 - RPE)` | valid sets with RPE and `rtf <= [e1rm.max_reps]` |

No special case for r = 1: Epley is applied as written.

**Steps.**
1. Group valid sets by session.
2. The session value of a series is the **maximum** over its sets. Each series takes its own maximum.
3. Sessions with no valid set are absent from the series (not zero). The RPE-adjusted series may have fewer points or
   be empty.
4. If the Epley series has fewer than `[e1rm.min_sessions]` (4) sessions, stop: `insufficient_sessions`.
5. `e1rm_slope` = slope (§1.5) of the **Epley** series, kg per week.
6. `e1rm_latest` = Epley value of the last session. If a bodyweight > 0 is given,
   `relative_strength = e1rm_latest / bodyweight`.
7. Trend label for the summary: `p = 100 * slope / mean(Epley series)`, in percent per week. `up` if
   `p > [e1rm.flat_pct_per_week]` (0.5), `down` if `p < -0.5`, otherwise `flat`. Exactly 0.5 is `flat`.

**Errors.** `unknown_exercise` (id is empty, `unknown`, or has no set in the log); `insufficient_sessions`. Also
`invalid_bodyweight` when a bodyweight <= 0 is passed.

**Worked example.** `Barbell_Squat`, one session per week on days 0, 7, 14, 21:

| Day | Sets (kg x reps) | Epley session value |
|---|---|---|
| 0 | 60 x 10 warm-up; 100 x 5; 100 x 4 | 100 * (1 + 5/30) = **116.6667** |
| 7 | 100 x 6; 110 x 0 (failed) | 100 * (1 + 6/30) = **120** |
| 14 | 105 x 5; 60 x 12 (reps > 10) | 105 * (1 + 5/30) = **122.5** |
| 21 | 105 x 6 | 105 * (1 + 6/30) = **126** |

Excluded: warmup 1, failed 1, reps_gt_max 1. x = 0, 1, 2, 3, mean 1.5. Mean y = 485.1667 / 4 = 121.2917.
Numerator = -1.5 * -4.6250 + -0.5 * -1.2917 + 0.5 * 1.2083 + 1.5 * 4.7083 = 6.9375 + 0.6458 + 0.6042 + 7.0625 = 15.25.
Denominator = 5. **Slope = 3.05 kg/week.** p = 100 * 3.05 / 121.2917 = 2.51 %, so `up`.
Brzycki for 100 x 5 = 100 * 36 / 32 = **112.5**. RPE-adjusted for 100 x 5 @ 8: rtf = 7, 100 * (1 + 7/30) = **123.3333**.

## 3. RPE drift (`compute_e1rm_and_drift`, part 2)

**Definition.** The change of RPE at comparable load, for one exercise over the analysis window.

**Valid set:** a working set of the exercise in the window, that passes `no_load` (weight > 0) and `no_rpe` (RPE
present). There is **no** reps limit here.

**Steps.**
1. No valid set: `rpe_missing`.
2. Reference load = the weight that occurs in the **most valid sets** (weights compared after rounding to 2 decimals). Tie:
   the **heavier** weight.
3. Comparable set: `abs(w - ref) <= [drift.load_tolerance] * ref` (5 %, inclusive).
4. Per session with at least one comparable set: mean RPE over its comparable sets.
5. Fewer than `[drift.min_sessions]` (4) such sessions: `insufficient_comparable_sessions`.
6. `rpe_drift_slope` = slope (§1.5) of the session means, RPE units per week.
7. Label: `up` if slope > `[drift.flat_per_week]` (0.1), `down` if < -0.1, otherwise `flat`.

A drift error does **not** discard the e1RM result: it is reported next to it. The real exports have no RPE at all, so
this is the normal case on real data.

**Worked example.** 100 kg on days 0, 7, 14, 21 with RPE: day 0 {7, 7}, day 7 {7.5}, day 14 {8, 8}, day 21 {8, 9}; plus
day 14 one set 90 kg @ 6 (outside 95-105, ignored). Reference 100. Means 7, 7.5, 8, 8.5. Mean y = 7.75. Numerator =
-1.5 * -0.75 + -0.5 * -0.25 + 0.5 * 0.25 + 1.5 * 0.75 = 2.5. Denominator 5. **Slope = 0.5 RPE/week**, `up`.

## 4. Effective sets per muscle per week (`weekly_sets_per_muscle`)

**Definition.** Weighted number of effective sets for each muscle and calendar week.

**Effective set:** a working set that passes, in this order: `unknown` (the exercise id is in free-exercise-db),
`not_allowed` (the exercise is in the allowed set, if one was passed), `low_rpe` (RPE missing, **or**
RPE >= `[weekly_sets.min_effective_rpe]` (7, inclusive)). A set without RPE counts and raises the flag `no_rpe`. Weight
and reps are not required, so bodyweight sets count.

**Steps.**
1. Week = Monday to Sunday (`[weekly_sets.week_start]`), named by its Monday.
2. Weeks shown: the week containing the date of the last set of the log (or the passed date) and the
   `[weekly_sets.default_weeks] - 1` (5) weeks before it. The last week may be incomplete. Sets outside are ignored.
3. Each effective set adds `[weekly_sets.primary_muscle_weight]` (1.0) to every primary muscle and
   `[weekly_sets.secondary_muscle_weight]` (0.5) to every secondary muscle. A muscle listed as both counts as primary only.
4. One value per muscle and week with at least one contributing set. A missing cell means 0.

**Edge cases.** No sets: empty table, no error. Unknown exercises are listed by raw name.

**Worked example.** One week: bench press (primary chest; secondary shoulders, triceps) 3 sets @ 8, 1 warm-up, 1 failed, 1 set
@ 6. Effective sets: 3 (excluded: warmup 1, failed 1, low_rpe 1). **Chest 3.0, shoulders 1.5, triceps 1.5.**

## 5. Uncoupled acute and chronic load (`uncoupled_load_analyzer`)

**Definition.** Recent load next to the load before it. The acute week is **not** part of the chronic window. The ratio is
always labeled `"heuristic"` and is never mapped to injury risk.

**Valid set:** a working set that passes, in this order: `missing_reps`, `no_weight` (weight present and > 0), `no_rpe` (RPE
present; **only** for the metric `rpe_weighted`). All exercises count, including `unknown` ones.

**Set load.** `tonnage`: `w * r`. `rpe_weighted`: `w * r * RPE / [load.rpe_divisor]` (10).

**Steps.** `as_of` defaults to the date of the last **valid** set.
1. Acute = sum of set loads with `0 <= days_before < [load.acute_days]` (7).
2. Chronic total = sum with `7 <= days_before < 7 + [load.chronic_days]` (28), so days 7 to 34.
3. `chronic_load_weekly` = chronic total / (28 / 7) = **chronic total / 4**. Weeks without training count as 0.
4. `acute_chronic_ratio` = acute / chronic_load_weekly.

**Errors and edge cases.**
- `no_valid_sets`, `invalid_metric`.
- `insufficient_history`: the first valid set is at `days_before < 34`. Day 34 is enough (35 days covered).
- Chronic = 0: no ratio value, flag `chronic_zero_ratio_undefined`. Acute and chronic are still returned.

**Worked example** (tonnage). Day 0: 100 x 5 = 500. Day 6: 100 x 8 = 800. Day 7: 100 x 3 = 300. Day 8: 100 x 5 = 500. Day 34:
100 x 3 = 300. Day 35: 100 x 10 (ignored). Acute = **1300**. Chronic total = 1100, weekly = **275**. Ratio = 1300 / 275 =
**4.7273** (heuristic).

## 6. Data sufficiency (`check_data_sufficiency`)

Rows considered: working sets with a matched exercise (id present and not `unknown`) and, if an allowed set was passed,
inside it. `as_of` = date of the last such set. The window is the analysis window of §1.4.

| # | Check | Passes when | If it fails, blocked analyses |
|---|---|---|---|
| 1 | Matched exercises | distinct matched exercises **>=** `[sufficiency.min_matched_exercises]` (1) | all |
| 2 | Gap | the largest difference in days between consecutive training dates **inside the window** is **<=** `[sufficiency.max_gap_days]` (14). 14 passes, 15 fails | all |
| 3 | History | days covered `(last date - first date) + 1` **>=** `7 * [sufficiency.min_history_weeks]` (35). First and last date 34 days apart passes, 33 fails | `load_ratio` |
| 4 | Sessions | at least one exercise has **>=** `[sufficiency.min_sessions_per_exercise]` (4) sessions in the window | `e1rm_trend`, `rpe_drift` |
| 5a | RPE coverage | sets with RPE / all considered sets in the window **>=** `[sufficiency.min_rpe_coverage]` (0.5) | `rpe_drift` |
| 5b | Comparable load | at least one exercise has **>=** `[drift.min_sessions]` (4) sessions with RPE at comparable load (§3, steps 2-4) | `rpe_drift` |

Analysis names: `e1rm_trend`, `rpe_drift`, `weekly_volume`, `load_ratio`. `rpe_drift` also needs check 4.

- `allowed_analyses` = the four names minus the blocked ones. `sufficient` = at least one is allowed. Partial abstention =
  sufficient, with at least one failed check.
- Each failed check gives one reason with its numbers, for example
  `RPE logged on 2 of 18 working sets; RPE drift not assessed`.
- Check 3 is the same bound as `insufficient_history` in §5 on purpose.

**Worked example.** Sessions of one exercise on days 0, 10, 20, 34 before `as_of`, no RPE. Gaps 10, 10, 14: pass. Covered days
35: pass. Sessions 4: pass. Coverage 0 of n: fail. Allowed: `e1rm_trend`, `weekly_volume`, `load_ratio`. One reason.
If the first session is at day 33 instead, the covered days are 34 and `load_ratio` is blocked too.

## 7. Value names and verifier tolerances

`value_id` = `v_<name>_<NNNN>`, with one counter **per run** shared by all tools, starting at 0001. `<name>` is lowercase
`[a-z0-9_]`. The tolerance class depends on the value's unit and name, see `[verifier]`:

| Class | Applies to | Tolerance for a number quoted in text |
|---|---|---|
| `load` | unit `kg` or `kg_rpe_weighted`, and chronic weekly load | `max(0.5, 1 % of the value)`, inclusive |
| `slope` | names ending in `_slope` | ±0.01 |
| `ratio` | `acute_chronic_ratio`, `relative_strength` | ±0.01 |
| `count` | everything else (sessions, sets, exclusion counts) | exact |

A quoted number is compared with the unrounded value, so `4.73` matches 4.7273 and `3.05` matches 3.05.

## 8. Decisions this text fixes

| Question | Decision |
|---|---|
| Weight 0 (bodyweight sets in both real exports) | Excluded from e1RM and drift, adds nothing to load, counts as an effective set |
| Reps > 10 (about a third of real sets) | Excluded from e1RM only, counted as `reps_gt_max` |
| A note that contradicts the unit ("lbs nu kg") | Never converted. Ingest keeps the value; it is a `logging_quality_issue`, not a `unit_mix` flag |
| `set_type = failure` with reps | A normal working set |
| Missing RPE | Drift is not assessed; e1RM, volume and tonnage continue |
