---
doc_id: syn04
title: "Progressive overload and plateaus"
topic_tags: ["progression", "frequency", "logging"]
citation_keys: ["plotkin2022"]
---

# Progressive overload and plateaus

> Draft: human citation verification and non-author review are pending; see SOURCES.md.

## Progression and interpreting stagnation

Progressive overload concerns an increasing training demand; increasing the
external load is one way to describe progression. Plotkin and colleagues
compared load progression with repetition progression at a fixed load in an
eight-week study of resistance-trained participants. Both approaches produced
adaptations, with uncertainty around differences between outcomes
[plotkin2022](SOURCES.md#plotkin2022). The study does not show that a particular
approach will resolve every plateau or that fixed load necessarily means fixed
training demand.

For log analysis, inspect what changed. Stable load with more repetitions differs
from stable load and repetitions. Lower reported effort at comparable work also
changes the record's interpretation. One variable is not a complete account of
performance.

The project uses `stagnant_load_progression` for stagnant estimated 1RM alongside
stable working load, according to
[architecture plan section 5.6](../milestone2-architecture-and-plan.md). This is
a hypothesis about an observed pattern, not proof that absent overload caused
stagnation. The estimated-strength calculation must use eligible data;
warm-up and failed sets must not contribute to e1RM.

Evaluate the observed pattern only after the project's data-sufficiency check.
Missing sessions, changes in exercise identity and incomplete repetition or
effort records can limit what comparisons support. Keep these logging
limitations separate from the overload hypothesis rather than treating absent
records as evidence of absent training.

The minimum meaningful change and plateau duration are
[TO VERIFY] with the indicator specification; this document creates neither.
Describe the observed time window and inputs, retain uncertainty, and abstain
from unsupported explanations. The cited experiment concerns group outcomes
under its own protocol, not a deterministic explanation for an individual's
training history.
