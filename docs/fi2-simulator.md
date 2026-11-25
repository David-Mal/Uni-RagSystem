# Fi2: functional development simulator

Status: the simulator generates real internal workout logs, applies cause and
abstention-pattern transformations, and produces deterministic development batches
with planned and observed injection coverage. It is ready for core code review.
**Evaluation export and final annotations remain blocked on external contracts.**
The production CLI refuses incomplete evaluation output without opening its path.

## References and dependency check: 2026-11-25

- [Fi2, issue #25](https://github.com/David-Mal/Uni-RagSystem/issues/25).
- [Architecture plan](milestone2-architecture-and-plan.md), sections 2.5, 3.4,
  3.5, 5.3, 5.5 and 5.6; [RFC](../RFC_Heuristic_Load_Fatigue_Analyzer.md), sections 1-3.
- [D2 #3](https://github.com/David-Mal/Uni-RagSystem/issues/3),
  [D3 #5](https://github.com/David-Mal/Uni-RagSystem/issues/5),
  [P1 #6](https://github.com/David-Mal/Uni-RagSystem/issues/6),
  [D5 #10](https://github.com/David-Mal/Uni-RagSystem/issues/10).

| Dependency | Local status | Consequence |
|---|---|---|
| D2: `docs/opengym-export-format.md` | Missing | No OpenGym row model, field names, timestamp/unit encoding or serialization is guessed. |
| D3: `docs/indicator-spec.md` | Missing | Physical patterns work, but final indicator/evidence/sufficiency decisions are not inferred. |
| P1: `data/manifests/partition.yaml`, `src/datagen/partition.py` | Missing | Unpartitioned development simulation works; actual pool selection and evaluation generation remain blocked. |
| D5: `src/ingest/adapters/opengym.py` | Missing | Clean-ingestion acceptance cannot be tested. |

There is no local `pyproject.toml` or lockfile. Runtime code uses typed, immutable
standard-library dataclasses; it adds no dependency or replacement canonical model.
A temporary uv environment supplies pytest. Pydantic v2 integration can follow
the actual project configuration when available; no D1 infrastructure is added.

## Implemented independent behavior

### Parameters

`src/sim/params.py` defines `LifterParams`, with all seven required inputs and
**no simulation defaults**. Units are `kg` or `lb`; RPE habits are `always`,
`sometimes` or `never`.

Necessary input checks reject booleans masquerading as numbers, nonfinite
numbers, negative session counts, nonpositive starting e1RM, and negative noise
magnitude or notes frequency. Zero sessions is allowed for inactive/abstention
configurations. There are no physiological upper limits, seven-session cap,
progression-rate bounds or assumed probability ceiling for notes frequency.

The generation semantics below are explicit simulation-design choices authorized
for development, not scientific claims or D3 thresholds. Their suitability for
the final dataset requires team review **[TO VERIFY]**. Test/demo configurations
are isolated inputs, not project defaults.

### Actual workout generation

`src/sim/workouts.py` implements `generate_workouts(params, design, seed=...)`.
`SimulationDesign` requires a start datetime, period in weeks, explicit within-week
session offsets, exercise specifications, base RPE and the probability used by
`sometimes`. Offset count must match sessions per week. Offsets are strictly
increasing within a seven-day calendar block; multiple sessions/day are allowed.
Exercise specifications provide an opaque exercise key, set count, repetitions
and a starting-load multiplier. Empty periods/session schedules are supported.

For each exercise/set the toy model uses:

```text
load = start_e1rm * load_multiplier
       + progression_rate * zero_based_session_index
       + uniform(-noise, noise)
```

`start_e1rm`, the increment and noise are expressed in the selected kg/lb unit.
This is an explicit linear simulator, not an e1RM estimation/adaptation formula.
There is no plate rounding, silent clipping, inferred repetitions or physiological
ceiling. Negative generated working loads fail; deliberately corrupt outlier loads
can be inserted later. RPE is the explicit base value when logged. `always` and
`never` work directly; `sometimes` uses the supplied probability in [0,1]. Load,
RPE logging and note selection use independent local RNG streams.

Notes frequency means expected opaque references/session: attach its integer
part plus one with probability equal to its fractional part, sampled without
replacement from the externally supplied reference catalog. The catalog must
contain enough entries; no missing template is replaced with generated wording.
No template bodies are accepted or rendered. Unit conversion uses the exact
avoirdupois factor `1 lb = 0.45359237 kg`, documented by
[NIST SP 811, footnote 22](https://www.nist.gov/pml/special-publication-811/nist-guide-si-footnotes).

`SimulatedLog`, `SimSession`, `SimExercise` and `SimSet` are internal frozen data
structures, **not D4 CanonicalSet or OpenGym**. Naive datetimes and zero-based set
slots are internal design conventions, not inferred export encodings. Sessions
remain chronologically sorted, exercises retain design order, and sets retain
their order. IDs are deterministic internal identities, not D4 content hashes;
intentional duplicate rows preserve the same set ID and values. Internal JSON is
marked `development_only`/`fi2-internal` and is not an ingestion format.

### Actual cause and abstention-pattern injections

`src/sim/injections.py` implements pure, ordered, copy-on-write transformations.
All magnitudes, target intervals and selectors are caller-controlled.

| Family/pattern | Working transformation |
|---|---|
| `insufficient_weekly_volume` | `ReduceSets` retains a configured number of sets per exercise in a selected session interval. |
| `fatigue_accumulation` | `RisingRPE` copies reference working loads across the interval and writes an explicit rising RPE sequence. It intentionally overrides missing logging there. |
| `stagnant_load_progression` | `StagnantLoads` copies reference loads, units and repetitions through the configured interval. |
| `load_spike` | `LoadSpike` multiplies working loads in an explicit window by a factor >1, without changing reps or the rest of the log. |
| `inconsistent_frequency` | `SessionGap` removes sessions in a date interval or shifts them by an explicit timedelta, then restores stable ordering. |
| `logging_quality_issue` | `MixedUnits` converts selected rows while mixing unit labels, `DuplicateSets` inserts identical rows, `MissingRPE` clears ratings, and `Outlier` writes a configured load/RPE value. |
| `confounder_present` | `ConfounderNotes` attaches externally supplied opaque, tagged template references to selected actual sessions. Tags cover sleep loss, illness and travel; no wording is generated. |
| Short history | `ShortHistory` retains the last configured number of days. |
| Few sessions | `FewSessions` retains the last configured number of sessions, including zero. |
| Long gap | `SessionGap(..., for_abstention=True)` requires an observed increase in the raw gap, not a guessed D3 cutoff. |
| No RPE | `MissingRPE(1, for_abstention=True)` clears every rating and checks that actual sets have no logged RPE. |

Observations describe raw facts: counts, gap seconds, fixed-load/repetition
profiles, rising ratings, duplicate rows, mixed units, written outlier candidates
and attached references. Raw load-times-reps sums describe the configured spike
window only; no D3 exclusions, acute/chronic ratio, OLS slope or band is implemented.
The `1e-12` relative comparison tolerance handles floating-point unit conversion,
not D3's comparable-load band. A configured outlier is not declared implausible by
an invented physiological limit.

`src/sim/scenarios.py` generates a baseline, applies every transformation, and
rechecks observations against the **final** log. Erased/no-op patterns cannot
borrow unrelated later changes for coverage. Transform order is explicit and can
affect results; conflicting designs raise coverage shortfalls rather than silently
being counted. These observations are not final evidence or detectability checks.

### Scenario planning and pipeline

`allocate_development_cases` in `src/sim/plans.py` uses seeded greedy allocation
of requested, overlapping categories, then fills/shuffles the remaining cases.
It rejects missing coverage or an unsuccessful allocation within the requested n.
The original small balanced-plan API remains available for isolated tests.

`SimulationFamily` combines parameters, a workout design and transformations.
`simulate_family` returns actual workouts and observed patterns.
`generate_development_batch` allocates families, generates every workout log,
applies injections and enforces **observed development coverage** separately from
planned coverage. It is a working in-memory pipeline; internal byte serialization
and temporary development outputs need neither D2 nor D3.

The explicit family ID becomes `cluster_id` for every replicate; it is not derived
from individual case IDs or seeds. Master/per-case RNG seeds here are unpartitioned
development inputs, not claims of P1 pool membership. These helpers do not select
real personas, template families or held-out content.

From the repository root, this complete example runs the core without external
contracts or note content. Its values are development choices, not defaults:

```python
from datetime import datetime, timedelta
from src.sim import LifterParams, ExerciseSpec, SimulationDesign, SimulationFamily, simulate_family
from src.sim.injections import RisingRPE

params = LifterParams(2, 100, 1, 0, "kg", "always", 0)
design = SimulationDesign(
    datetime(2033, 1, 3, 9), 3, (timedelta(0), timedelta(days=3)),
    (ExerciseSpec("development-lift", 3, 5, 0.6),),
    base_rpe=6, rpe_logging_probability=0.5,
)
family = SimulationFamily("development-rpe-family", params, design, (RisingRPE(6, 0.1),))
case = simulate_family(family, seed=901233124, scenario_id="development-case")
assert len(case.log.sessions) == 6
assert case.expected_annotations is None
```

### Ground-truth schema

`src/sim/schema.py` defines a simulator annotation schema, not an ingestion or
tool result schema. Shared canonical definitions are unavailable in this checkout.
It uses the architecture's exact seven label strings, three evidence levels
(`supported`, `weak`, `insufficient`) and gate colors (`green`, `yellow`, `red`),
without creating production enums.

Each `GroundTruth` requires:

- `scenario_id`, `cluster_id` and JSON-compatible `injected_parameters`;
- explicit `expected_hypotheses` label/evidence pairs;
- explicit `abstain`, `abstention_reasons` and `gate_outcome`;
- explicit `has_confounder` and `has_numeric_trap` scenario annotations for quotas.

There is no automatic conversion from an injection request into ground truth.
Abstention is never accepted as a hypothesis label. Abstaining annotations need
a nonempty reason; reason codes and full/partial abstention policy await D3
**[TO VERIFY]**. No gate outcome is derived from confounder tags or missing notes.
The schema validates structure, duplicate labels, finite JSON values and round-trip
serialization; it does not certify empirical correctness. `injected_parameters`
is now recursively snapshotted into read-only mappings/tuples. Nested mutation
fails; `to_dict()` returns a detached mutable copy and JSON round-trips retain
the existing object/array wire shape.

`DevelopmentScenario` separates requested injections, realized `injected_causes`,
`observed_patterns`, optional `expected_annotations` and `pending_decisions`.
All generated cases have `expected_annotations=None`; evidence, abstention and
gate decisions remain pending. Attaching explicit annotations requires matching
scenario/family/parameters and a specification reference. No such final annotations
are created by the development pipeline. Actual expected indicator numbers and
their validation remain external integration work.

### Quotas

`src/sim/quotas.py` implements the exact issue minima: total 150, 20 per hypothesis,
30 abstention, 20 confounder and 20 numeric-trap scenarios. Overlaps count toward
each applicable category while total scenarios are counted once. A hypothesis
counts once per scenario from its explicit annotation, at any established evidence
level; no additional supported-only quota is invented. Cluster counts are reported
without inventing a minimum cluster count.

The three stages remain distinct:

1. `planned_coverage`: requested families and patterns, before simulation.
2. `injected_coverage`: patterns actually observed after all transformations.
   Its abstention count means cases with abstention-related data patterns, not
   `abstain=True`; confounder coverage means actual opaque-reference attachment.
3. `validate_quotas`: complete explicit `GroundTruth` annotations only. It rejects
   plans and development scenario objects; no automatic promotion is provided.

Duplicate scenario IDs are rejected. Coverage metadata is read-only. The legacy
annotation-counter tests still use mocks, while new development tests generate
real workouts. Neither kind of test completes evaluation scenarios or proves D3
detectability/pool compliance. **No final Tier 2 ground-truth quotas are claimed.**

## P1 interface and human-only notes

[PR #80](https://github.com/David-Mal/Uni-RagSystem/pull/80) was inspected through
public metadata and its partition-loader interface only. It was **open and not
merged** at inspection; PR availability is not local availability. The inspected
head was `b4db318c826b5f9a9c54707b2a09f0b3ee6fb0c9`.

The public contract provides `load_partition(path=None) -> Partition`,
`assert_pool(item_ids, pool, partition=None)`, and `Partition.pool_of_seed`,
`pool_of(section, item_id)`, `members(section, pool)`, `seed_range(pool)` and
`assert_in_pool(pool, seed=..., **section_ids)`. Errors use `PoolError`.
This code was not copied, imported or replaced here.

Once locally available, actual generation must use that loader and pool validation
for seeds, personas, scenario templates and phrasing families, including the
`tier2_notes` consumer. Required generator/partition metadata must follow P1's
actual contract. There is no fallback pool registry, guessed manifest, replacement
loader or invented golden family ID.
Golden note selection specifically requires the golden pool's `tier2_notes`
families. Any development-note policy must follow the actual manifest consumers;
do not relabel extractor/classifier families as held-out note families.
For future evaluation, supply each actual P1-validated seed to the simulator and
record the real partition metadata. Do not reuse the development batch's arbitrary
derived RNG seeds as approved evaluation seeds. Its unit family IDs are not actual
manifest entries, and the demo's seven clusters do not establish golden template
quantities or categorization.

Patrick and Filip must author/review the held-out note templates and private
family details without an LLM. This session neither opens those files nor
constructs any note wording. Reference attachment works now; a human-operated
integration step must associate
approved templates with actual manifest families and check consumer/pool membership
before use. Unrestricted unit-test content must never substitute for held-out notes.

## CLI behavior

The intended future human-operated command is:

```powershell
python scripts/generate_tier2.py --n 150 --out data/golden/tier2/
```

**Do not run that command during AI-assisted development. It was not run here.**
`scripts/generate_tier2.py` currently validates arguments, reports missing D2/D3/P1/
D5 paths, and exits with status 2 without inspecting or creating `--out`. Even if
those paths exist, it still refuses until actual evaluation annotation, partition,
held-out template and OpenGym/ingestion integrations are implemented. The core is
functional independently; file existence is not treated as successful integration.

No OpenGym output extension, column, date format or indicator formula is selected
by this CLI. Restricted output is never used by tests or the development demo.

## Validation and integration handoff

Tests live only under `tests/sim/`. The existing useful tests are preserved and
extended with actual sessions/sets, load progression, seeded noise, all RPE habits,
unit conversion, every cause/abstention transformation, conflicting/no-op effects,
deep parameter immutability, planned/injected quotas and actual 150-case generation.
All data is isolated development input, unrelated to actual partition entries.
Temporary files contain marked internal logs/batches, never OpenGym exports,
held-out note wording or evaluation ground truth.

The test command uses a temporary uv-managed Python 3.11 environment with pytest:

```powershell
uv run --no-project --active --offline python -B -m pytest tests/sim -q -p no:cacheprovider --confcutdir=tests/sim --basetemp <temporary-test-directory>
```

Set `VIRTUAL_ENV` and `UV_CACHE_DIR` to the temporary environment/cache; this does
not initialize a project or add dependencies to the repository.

Observed result on **2026-11-25**: **135 passed in 2.81s**, using Python 3.11.18
and pytest 9.2.0. This is the complete Fi2 suite, not P1's PR test result or
an end-to-end scenario/ingestion acceptance result. No restricted-output command
was executed.

### Actual development demonstration

A separate run used explicit, noisy, six-week development designs with three
sessions/week, two exercises, three/two sets, local RNG seed `901233124`, and seven
caller-defined families. These are demonstration choices, not proposed scientific
defaults. Both runs produced **150 actual scenarios, 1,965 sessions and 9,531 set
rows**, with the following equal planned/observed injection counts:

| Family / category | Count |
|---|---:|
| insufficient_weekly_volume | 21 |
| fatigue_accumulation | 22 |
| stagnant_load_progression | 21 |
| load_spike | 22 |
| inconsistent_frequency | 21 |
| logging_quality_issue | 21 |
| confounder_present | 22 |
| Abstention-related data patterns | 84 |
| Confounder-reference cases | 22 |
| Numeric-trap cases | 21 |
| Family clusters | 7 |

Each of the four abstention patterns occurred in 21 cases. Each numeric trap
(unit mix, duplicate, missing RPE and configured outlier) occurred in 21 cases,
overlapping within the logging family. Final annotation records: **0**; all
evidence/abstention/gate decisions remained pending. No note wording was generated.

The two temporary internal JSON outputs were byte-identical, **1,628,710 bytes**,
SHA-256 `43a32b541e8446e07e227b728bf953729eebfb3bddf525b7ab42345be105834b`.
They were outside restricted data and are removed with the temporary test
environment. No development output is committed as an evaluation artifact.

Remaining integration work:

1. David supplies D2's actual export contract and D3's resolved specification.
   Do not substitute Strong/Hevy fields, architecture examples or production tools.
2. P1 must become available locally before real pool selection. No open PR is
   assumed merged and no manifest enforcement is bypassed.
3. Keep the working simulator, but bind final sufficiency/evidence decisions to D3
   and serialization to D2. Do not replace those contracts with the toy model's
   design settings or observed-pattern counters.
4. Integrate approved human-authored template rendering/families through actual
   P1 validation; no unrestricted development reference may substitute for them.
5. Validate clean ingestion through D5 when it exists. Patrick's independent
   reference values and P3 detectability review remain separate, human/team-run
   steps; Fi2 must not inspect that reference implementation.
6. Only authorized humans later generate the restricted dataset, complete the
   detectability/audit process and freeze it. The architecture requires at least
   a 20% blind audit and cluster-aware reporting; neither is fabricated here.

Simulation design choices requiring review are the linear per-session increment,
absolute uniform noise, explicit exercise load multipliers/reps, fixed base RPE,
logging probability, expected note-reference count, naive internal calendar,
unrounded loads, transformation composition/order and greedy family allocation.
They are configurable development choices, not physiological conclusions, official
export conventions or indicator thresholds. No remaining external contract blocks
these already working core functions.

The functional core is ready for normal code review and integration. **Production
evaluation generation/final ingestion acceptance remain blocked exclusively by
D2/D3/P1/D5 and the required human-owned held-out templates/review workflow.**
