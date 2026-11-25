# Week 9 — Exercise Name Matching Report (Issue M1, #32)

## Scope & Inputs

- **Cascade configuration:** `configs/matching.yaml` (`fuzzy_threshold = 90.0`, `fuzzy_min_sort = 80.0`, `fuzzy_margin = 3.0`, `retrieval_threshold = 0.65`, `top_k = 5`)
- **Alias dictionary:** `data/exercises/aliases.yaml` (seeded from F1 `data/exercises/seed_names.txt` + common abbreviations)
- **Vocabulary:** `data/exercises/free-exercise-db.json` (876 exercises, commit `f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5`)
- **Real exports evaluated:**
  - **Fineas (F1):** 21 distinct exercise names. **David (D2):** 27. 7 are shared, so 41 distinct names in total, the same set as `data/exercises/seed_names.txt`.
  - Checked against the committed fixtures by `test_every_name_of_the_real_exports`.

## Stage Attribution Summary (Stages 1–2, without Stage 3 retrieval)

| Stage | Count | Share (%) |
|---|---:|---:|
| Stage 1 (`alias`) | 40 | 97.6% |
| Stage 2 (`fuzzy`, `token_set_ratio >= 90`) | 0 | 0.0% |
| Stage 3 (`retrieval`, M5 stubbed) | 0 | 0.0% |
| Stage 4 (`unknown`) | 1 | 2.4% |
| **Total distinct names** | **41** | **100.0%** |

**Acceptance check:** 40/41 (97.6%) match before Stage 3, and 41/41 (100.0%) either match before Stage 3 or are explicitly `unknown` with a documented reason — meeting the `>= 90%` criterion.

## Unmatched (`unknown`) Names

| Raw Exercise Name | Best Fuzzy Score | Top Candidate(s) | Reason |
|---|---:|---|---|
| `Cable Leaning Lateral Raise` | 89.66 | `Cable_Seated_Lateral_Raise`, `Side_Lateral_Raise` | `free-exercise-db` has no standing/leaning one-arm cable lateral raise entry; left explicitly `unknown` rather than guessing (can be added to `aliases.yaml` if team agrees to map to `Cable_Seated_Lateral_Raise`). |

## Reproduction

```bash
PYTHONPATH=. .venv/bin/pytest tests/tools/test_match_exercise.py -v
```
