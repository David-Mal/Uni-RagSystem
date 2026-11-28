# Fi2 simulator and development integration

Issue: [#25](https://github.com/David-Mal/Uni-RagSystem/issues/25). Integration update: 2026-11-28.

The existing deterministic simulator is preserved. Development generation now selects actual P1 pool inputs,
generates workouts, applies injections, writes D2/D5-compatible source CSVs and records explicit provenance.
Development output contains no inferred expected annotations and is never a completed Tier 2 evaluation dataset.
Final golden generation remains blocked on the requirements below.

## Merged contracts

| Contract | Current use |
|---|---|
| D2, `docs/opengym-export-format.md` | Both documented column layouts, encoding, timestamps, indexing and source semantics |
| P1, `src/datagen/partition.py` | Actual loader, pool selection and membership/consumer enforcement |
| F2, `src/schemas/enums.py` | Shared hypothesis, evidence and triage enums in the ground-truth schema |
| D4, `src/ingest/` | Real canonical ingestion, explicit matcher, normalization and storage round trips verified |
| D5, `src/ingest/adapters/opengym.py` | Source contracts and four real synthetic ingestion tests verified |
| D7, `src/exercises/loader.py` | CLI validates explicit canonical exercise bindings against the real vocabulary |
| D3 v1, `docs/indicator-spec.md`, `configs/indicators.yaml` | Settled written rules; no production or reference algorithms used |

PR #101 is unmerged. Its proposed D3 clarifications are not silently adopted here.

## Working simulation core

`params.py`, `workouts.py`, `injections.py`, `plans.py` and `scenarios.py` provide actual sessions, exercises and sets,
ordered schedules, progression, numerical noise, kg/lb loads and always/sometimes/never RPE logging. Copy-on-write
transformations implement reduced sets, rising RPE at fixed load, stagnant loads/repetitions, acute load increases,
session removal/rescheduling, mixed units, duplicates, missing RPE, outliers and opaque confounder references.
Short-history, few-session, long-gap and no-RPE patterns remain supported.

Simulation choices are explicit inputs, not physiological findings or D3 indicator thresholds. Working load is starting
e1RM times an explicit multiplier, plus load units per session and uniform bounded noise. This toy equation does not
estimate e1RM or claim adaptation. Schedules, repetitions, weeks, logging probability and injection magnitudes are
caller-specified. The supplied persona/template IDs identify partition inputs; the code does not infer physiological
presets from their descriptions. Explicit family-to-template bindings need normal review for semantic suitability.

The original `generate_development_batch` remains an isolated, unpartitioned development API. Its derived seeds are
not recorded as partition seeds by the new integrated workflow. Use `prepare_development_export` or the CLI for
partition-enforced output. `cluster_id` remains the simulation template/parameter family, shared across cases.

## OpenGym source serialization

`src/sim/opengym.py` separates export metadata from internal simulation records and D4 canonical sets.

- `ExerciseExport` requires an internal key, explicit four-digit source catalog ID, source name/body part and canonical
  exercise ID. Source IDs retain leading zeros and are never substituted for free-exercise-db IDs. D7 membership is
  checked by the integrated pipeline; `unknown` is an explicit unresolved binding, not a guessed identity.
- `OpenGymMetadata` requires a workout name, integer duration in minutes, mappings and the 21- or 26-column variant.
  The duration applies to every workout in that export. Different designs can use different metadata; no duration is
  invented or added to D4's schema.
- CSV uses UTF-8 BOM, commas, standard CSV quoting, CRLF and a trailing newline. Whole numbers have integer spelling;
  other numbers use plain decimals without exponent notation or numeric rounding.
- Start/end timestamps use exactly `YYYY-MM-DD HH:MM`, naive local time. Seconds, microseconds and colliding starts
  raise errors rather than being truncated. End time is start plus the explicit duration.
- Internal zero-based slots become one-based set numbers. Gaps or unstable slot ordering are rejected. Intentional
  repeated slots/rows are preserved, allowing D4 to identify duplicate sets instead of accidentally renumbering them.
- Values and source kg/lb units are preserved. Empty optional cells represent missing values; numeric zero remains zero.
  Unused RIR, supersets, side and other unconfirmed optional fields stay empty.
- Ordinary simulated working sets export as `normal`. Explicit per-set metadata supports D5's known `warmup` and
  `failure` spellings, optional distance/time and source notes. Positive-repetition `failure` means taken to failure;
  zero repetitions remain a failed set. Failure is never inferred from RPE. OpenGym drop encoding remains [TO VERIFY].
- The low-level serializer supports explicit synthetic note fields for CSV quoting tests. The integrated development
  workflow rejects note text and unresolved note references because no dev `tier2_notes` family is authorized.
- Finite negative traps and out-of-range RPE are not clamped, converted to null or repaired. Development sidecars record
  expected D5 rejection for negative numbers/empty logs and the expected D4 flag for RPE above 10. These are written
  source-contract expectations, not evidence that ingestion ran. Positive outliers remain present.

Pounds, populated RPE/RIR and several optional fields are supported by the merged adapter but remain [TO VERIFY
against real application exports] in D2. Synthetic compatibility tests do not resolve those empirical questions.

## Partition selection and provenance

`partitioning.py` calls the shared P1 interface. The first seed is an explicit dev-pool seed; successive scenario seeds
advance inside the inclusive dev range, wrapping if needed. A batch cannot request more scenarios than distinct dev
seeds. Boolean/non-integer seeds, wrong-pool and unknown identifiers are rejected. Public persona IDs rotate in sorted
order; family bindings supply the scenario template. Selection never reads golden descriptions or restricted details.

The helper also validates public phrasing-family selection against its declared consumer. The integrated Fi2 development
pipeline uses no consumer and an empty phrasing-family list. P1 permits only extractor/classifier consumers in dev;
it does not currently authorize dev `tier2_notes`. Neither consumer's phrasing is borrowed for simulator notes.
[TO VERIFY with P1 owner: whether a future dev note consumer/family should be introduced.] No replacement family is
invented here. Existing opaque-reference core tests do not constitute authorized note generation.

Every scenario sidecar records pool, actual scenario seed, persona ID, scenario-template ID, phrasing-family IDs,
consumer, manifest version, `generator_model = deterministic-code/no-LLM`, generator version, simulation parameters,
export metadata and CSV SHA-256. Notes mode is explicitly omitted. Balanced family planning uses the master dev seed;
the workout RNG uses the actual scenario pool seed with the existing distinct internal substreams.

## Configuration and commands

Use the project's Python 3.11 core/dev environment. The CLI requires explicit `--development`, `--config` and `--seed`.
Configuration is strict JSON; unknown/duplicate keys, non-finite numbers and invalid parameters fail before output.
The configuration is a Fi2 simulation design, not an alternative export or canonical schema.

The following complete small configuration illustrates the shape. It uses the public D2 example and D7 alias for
close-grip bench press, with an explicit arbitrary development schedule. It covers one pattern, not all issue quotas.
Save it as a development JSON file outside restricted directories:

```json
{
  "families": [{
    "family_id": "development-press-rpe",
    "scenario_template_id": "st_dev_rpe_drift_press",
    "params": {
      "sessions_per_week": 2, "start_e1rm": 100, "progression_rate": 0,
      "noise": 0, "units": "kg", "rpe_habit": "always", "notes_frequency": 0
    },
    "design": {
      "start": "2031-01-06T09:00:00", "weeks": 8,
      "session_offsets_minutes": [0, 4320],
      "exercises": [{"exercise_key": "development-press", "sets_per_session": 3,
                     "reps": 5, "load_multiplier": 0.5}],
      "base_rpe": 6, "rpe_logging_probability": 1
    },
    "injections": [{"kind": "RisingRPE", "parameters": {"start_rpe": 6, "step_per_session": 0.1}}]
  }],
  "export": {
    "workout_name": "Synthetic development workout", "duration_minutes": 45, "variant": 26,
    "exercises": [{"exercise_key": "development-press", "source_catalog_id": "0030",
                   "name": "Barbell Close-Grip Bench Press", "body_part": "upper arms",
                   "canonical_exercise_id": "Close-Grip_Barbell_Bench_Press"}]
  }
}
```

From the repository root in PowerShell, after saving that JSON at the stated temporary path:

```powershell
uv sync --frozen --no-default-groups --group core --group dev
$devSeed = uv run --no-sync python -c "from src.datagen.partition import load_partition; print(load_partition().seed_range('dev')[0])"
uv run --no-sync python scripts/generate_tier2.py --development --n 150 --seed $devSeed `
  --config "$env:TEMP\fi2-development-config.json" --out "$env:TEMP\fi2-development-a"
uv run --no-sync python scripts/generate_tier2.py --development --n 150 --seed $devSeed `
  --config "$env:TEMP\fi2-development-config.json" --out "$env:TEMP\fi2-development-b"
```

Both output directories must be new. `--partition PATH` optionally selects another valid P1 manifest; tests use only
isolated synthetic manifests. Optional top-level `persona_ids` restricts selection to an explicit nonempty dev subset.
The development count can be any positive integer within seed capacity; this does not waive the final issue quotas.
No existing output is overwritten. Golden/pilot input and output paths are rejected.

To broaden the configuration, add explicit families with their own parameter/design/injection objects and correct
public dev template bindings. Supported configuration injection kinds are `ReduceSets`, `RisingRPE`, `StagnantLoads`,
`LoadSpike`, `SessionGap`, `MixedUnits`, `DuplicateSets`, `MissingRPE`, `Outlier`, `ShortHistory` and `FewSessions`.
Their parameters match `injections.py`; intervals are `{ "start": 0, "stop": 4 }`, using exclusive stop. `SessionGap`
uses ISO start/end and optional integer `reschedule_minutes`. No numerical defaults from this example are project rules.
Optional export `sets` maps stable internal set IDs to explicit `set_type`, `distance_km` or `seconds` metadata.

Each successful run writes:

- `development-NNNNNN.csv`: OpenGym source CSV, stable scenario order and internal row order.
- `development-NNNNNN.development.json`: requested/observed patterns, internal data, export metadata, provenance,
  `expected_annotations: null` and `validated_evaluation_ground_truth: false`.
- `development-batch.json`: planned/injected coverage, sessions/set rows, hashes, issue-pattern shortfalls and blockers.

There is no ground-truth filename or fabricated annotation. The generic coverage counter's `abstention` entry means
an injected abstention-related pattern at this stage, not an adjudicated abstention outcome. Repeating identical inputs,
code version, vocabulary and manifest in the same supported Python environment produces byte-identical file names and
contents; paths and wall-clock dates are not serialized. Cross-version/runtime equivalence is not asserted.

## D4/D5 ingestion verification

The normal import chain is `src.ingest.__init__ -> src.ingest.pipeline -> src.ingest.store ->
src.tools.common.Value`. For the 2026-11-28 ingestion verification, Filip explicitly authorized the transitive runtime
import of that shared model. No `src/tools/` source was inspected and no production numerical algorithm was invoked.
The tests use normal imports and the real implementations, without mocks, stubs or replacement packages. An external
runtime guard permitted only this model import and its necessary package initialization; no additional protected
module was imported. This narrow exception does not authorize inspecting numerical code or the independent reference.

`tests/sim/test_ingestion_roundtrip.py` contains four passing integration tests for normalization/exercise
resolution/duplicates/idempotence, positive outliers and invalid RPE, failed versus failure/warmup sets, and rejection
of negative traps without storage repair. They use the actual D4 store/pipeline and the explicit metadata matcher;
the previous skip marker is removed. All input CSVs and DuckDB stores are synthetic and temporary. Source-header
conformance is also tested separately against D5's public constants.

Observed results: 81 input rows containing one intentional duplicate produce 80 stored canonical sets; re-ingesting
the same export adds zero sets. A source pound load of `50 / 0.45359237` normalizes to 50 kg, missing RPE stays missing,
and explicit exercise mappings resolve. A positive 9000 kg outlier stays present with a flag; RPE 12 becomes missing
with `implausible_rpe`, following D4 rather than repairing the source CSV. Zero reps is failed, positive-repetition
`failure` is not failed, and warmup is preserved. Negative weight is rejected without storing any sets.

These tests establish compatibility for the tested synthetic cases. The development exporter itself does not ingest
each output batch: its manifest explicitly records `ingestion_validation: not_run_by_exporter`. Test-suite success
must not be substituted for per-batch validation, final annotations or verification against real application exports.

## D3 alignment and evaluation blockers

Merged D3 v1 governs future annotations: warmups and failed sets are excluded from working sets; completed
failure-type sets remain working sets. History, sessions, RPE coverage and comparable-load checks have analysis-specific
effects. Acute days 0-6 and preceding chronic days 7-34 with weekly normalization are settled. Missing RPE must not be
promoted automatically to full abstention. These written rules are not reimplemented as a competing numerical tool.

`GroundTruth` uses shared F2 enums and keeps recursively immutable injected parameters. It validates caller-supplied
annotations but does not establish their correctness. Requests, final observed patterns, expected annotations and
validated evaluation ground truth remain separate. No production tool or Patrick reference output is an oracle here.

Remaining requirements:

1. [TO VERIFY with D3/agent owners] Complete approved mappings from observed indicators to hypotheses and
   `supported`/`weak`/`insufficient`; insufficient-volume bands and other hypothesis boundaries; final scenario-level
   full/partial abstention representation. Reconcile approved specification wording after PR #101, not before merge.
2. Human-authored held-out note templates, authorized golden bindings and explicit gate annotations. No held-out note
   wording or golden family details are generated or inspected by this implementation.
3. Before final dataset acceptance, run ingestion validation on the actual human-operated output batch. Synthetic
   canonical ingestion/storage tests are now verified; D4/D5 availability is no longer a blocker.
4. Final pool-aware evaluation orchestration, actual ground-truth annotations and quota enforcement only after the
   preceding contracts/approvals exist. Calling the script without `--development` still exits 2 before opening inputs
   or creating output; missing-file checks no longer masquerade as integration readiness.
5. Independent detectability checks (P3), dropping/relabeling undetectable cases, then the architecture's blind audit of
   at least 20% by both annotators, agreement/adjudication and freeze. These are human/non-builder follow-up work.

Final issue minima remain 150 scenarios, 20 per each of seven hypotheses, 30 abstentions, 20 confounders and 20 numeric
traps. Overlaps are allowed. Development pattern counts never certify these validated evaluation quotas.

## Actual validation, 2026-11-28

Python 3.11.18; uv's frozen core/dev groups in an isolated temporary environment, no new project dependencies.

```powershell
python -B -m pytest tests/sim -q -p no:cacheprovider --confcutdir=tests -ra
python -B -m pytest tests/sim/test_ingestion_roundtrip.py -q -p no:cacheprovider --confcutdir=tests -ra
ruff check --no-cache src/sim tests/sim scripts/generate_tier2.py
git diff --check -- src/sim tests/sim scripts/generate_tier2.py docs/fi2-simulator.md
```

The test run uses a temporary pytest base directory. An external audit hook prevents restricted file reads, additional
protected imports and network calls, including subprocesses. It permits only the authorized normal transitive shared
model import; no permanent validation infrastructure is introduced.

- The four previously skipped ingestion tests: **4 passed**, zero failures and zero skips (3.91 seconds).
- Complete Fi2 suite: **189 passed**, zero failures and zero skips (8.79 seconds). The CLI's repeated 150-case
  deterministic development-output test remains passing.
- Ruff and scoped Git whitespace checks: passed. New files also passed explicit whitespace/source parsing checks;
  shared implementations and project dependency files were unchanged.
- Actual CLI smoke run using the shared real P1 manifest through its public dev interface: **150 scenarios, 1,625
  sessions, 7,850 set rows, 150 unique dev seeds, six family clusters, 301 files**. Two runs were byte-identical.
- Observed injected coverage: 25 each for insufficient volume, fatigue, stagnation, load spike, frequency and logging
  quality; 100 abstention-related patterns; 25 numeric-trap cases. Confounders: **0**, explicitly pending authorized notes.
- Every scenario's seed/persona/template membership passed P1 validation. These smoke-test bindings use synthetic
  parameters and source catalog identities, not claims about real lifters or verified app catalog entries. Template
  semantics/parameter suitability are review tasks; partition membership alone does not validate them.
- All 150 CSVs serialized in that earlier CLI smoke run. None of that batch's values met the written D5 rejection
  conditions. That earlier 150-case batch was not ingested; the subsequent four real round-trip tests above establish
  synthetic integration compatibility, not retrospective validation of an output batch that was already removed.
- A fresh, separate **150-case synthetic development batch** was generated using isolated synthetic P1 inputs and
  validated with the real D4/D5 pipeline. It contained **1,625 sessions and 7,850 source rows**. Both 21- and 26-column
  CSVs were parsed for every scenario (**300 CSVs**) and produced identical canonical adapter records. First ingestion
  stored **7,825 sets**, eliminating **25 intentional duplicates**; re-ingestion through the other CSV layout added
  **zero sets**. All exercise names resolved through the explicit matcher. The expected flags were 25
  `implausible_weight`, 25 `duplicate_set` and 50 `unit_mix`. Two preparations were byte-identical. This validates a
  fresh synthetic batch only, with no golden content, note wording or final annotations.
- Final validated evaluation ground-truth records: **0**. The batch reports both confounder-pattern shortfalls.

The temporary development outputs were generated outside the repository and removed after verification.
The complete pending diff, including all nine new files and six modified files, was reviewed as Fi2-only. No D4, D5,
D6, shared schema, exercise loader, partition implementation or project dependency file was modified.
No restricted golden/pilot data, private folders, personal workout exports, production numerical source or independent
reference code were inspected. Only the explicitly authorized shared-model runtime import occurred.
