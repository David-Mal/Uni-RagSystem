# OpenGym trap fixtures (issue D5)

Rows copied from `../david_anonymized.csv` with single cells edited. **Not real logs.** Workout notes were blanked in the
rows of 2026-11-05. BOM and CRLF are kept as in the real export.

| File | Edit | Expected |
|---|---|---|
| `duplicate_sets.csv` | First curl row repeated | Stored once, flag `duplicate_set` |
| `unit_mix.csv` | Second pushdown row changed to 225 `lb` (spelling of pounds `[TO VERIFY]`) | 102.0583 kg, flag `unit_mix` |
| `failed_set.csv` | None: real rows of the 0-rep crunch | `failed = true` on the third set only |
| `missing_rpe.csv` | RPE 8 and 7.5 added to two of four rows | RPE kept on two rows, missing on two, no flag |
| `impossible_weight.csv` | 50 changed to 5500 kg | Value kept, flag `implausible_weight` |
