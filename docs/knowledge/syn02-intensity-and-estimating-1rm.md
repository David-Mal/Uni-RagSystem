---
doc_id: syn02
title: "Intensity and estimating 1RM"
topic_tags: ["intensity", "logging"]
citation_keys: ["simonsen2025"]
---

# Intensity and estimating 1RM

> Draft: human citation verification and non-author review are pending; historical provenance is recorded separately in SOURCES.md.

## Intensity, equations and estimation limits

Intensity can describe load relative to a person's exercise-specific capacity;
it should be distinguished from perceived effort. One-repetition maximum is the
load completed for one repetition under a defined test. An estimated 1RM is a
model-derived quantity, not a newly observed maximal lift. Simonsen and colleagues
compared estimates with measured 1RM across ten lower-extremity exercises in
22 participants. Their discussion cautions that equations developed in different
populations and exercises do not automatically transfer to another context
[simonsen2025](SOURCES.md#simonsen2025).

The equations below are specified by
[architecture plan section 5.7](../milestone2-architecture-and-plan.md), rather
than introduced here as new research findings. With eligible load `w` and
completed repetitions `r`, Epley is `e1RM = w * (1 + r / 30)`. The specified
Brzycki sensitivity calculation is `e1RM = w * 36 / (37 - r)`. Keep the load unit
consistent. Report the estimator used; a difference between estimates does not
mean the person performed a different lift. Table 1 in the consulted study lists
Epley and Brzycki with rounded coefficients; it is not an exact transcription of
the project's equations.

The plan limits eligible repetition counts to at most 10. This is the project's
stated operating range, not a universal validity guarantee for every population.
Warm-up and failed sets must not contribute to e1RM. The RPE-adjusted variant
described in the plan substitutes `reps + (10 - RPE)` as repetitions to failure.
The repetition limit applies to both the logged and the adjusted count, see
[indicator specification, section 2](../indicator-spec.md).

The study's repetitions-to-failure test is a specific research protocol, not
validation of every logged working set. Its equation table and references provide
open secondary support and historical leads, not a new reading of the original
Epley or Brzycki publications. Those originals are documented separately without
requiring their purchase for this synthesis.

Missing inputs, changed exercise identity or a change of estimator limit
comparisons. Preserve those limitations rather than manufacturing a precise
strength change or treating a research comparison as a project threshold.
