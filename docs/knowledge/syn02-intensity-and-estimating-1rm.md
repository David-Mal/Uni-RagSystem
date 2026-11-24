---
doc_id: syn02
title: "Intensity and estimating 1RM"
topic_tags: ["intensity", "logging"]
citation_keys: ["richens2014"]
---

# Intensity and estimating 1RM

> Draft: human verification and full-text inspection of the cited study remain pending; see SOURCES.md.

## Intensity, equations and estimation limits

Intensity can describe load relative to a person's exercise-specific capacity;
it should be distinguished from perceived effort. One-repetition maximum is the
load completed for one repetition under a defined test. An estimated 1RM is a
model-derived quantity, not a newly observed maximal lift. Richens and Cleather's
publisher abstract reports different repetition capacities at the same relative
loads between training-background groups in a leg-press study
[richens2014](SOURCES.md#richens2014). That finding cautions against assuming one
repetition-to-load relationship fits every lifter and exercise.

The equations below are specified by
[architecture plan section 5.7](../milestone2-architecture-and-plan.md), rather
than introduced here as new research findings. With eligible load `w` and
completed repetitions `r`, Epley is `e1RM = w * (1 + r / 30)`. The specified
Brzycki sensitivity calculation is `e1RM = w * 36 / (37 - r)`. Keep the load unit
consistent. Report the estimator used; a difference between estimates does not
mean the person performed a different lift.

The plan limits eligible repetition counts to at most 10. This is the project's
stated operating range, not a universal validity guarantee for every population.
Warm-up and failed sets must not contribute to e1RM. The RPE-adjusted variant
described in the plan substitutes `reps + (10 - RPE)` as repetitions to failure.
Whether the repetition limit applies before or after that adjustment remains
[TO VERIFY]; this synthesis does not select an implementation.

Original Epley and Brzycki bibliographic provenance remains [TO VERIFY], as the
plan itself acknowledges. The cited study supports the individual-variation
caveat, not verification of those original formula sources. Missing inputs,
changed exercise identity or a change of estimator limit comparisons; preserve
those limitations rather than manufacturing a precise strength change.
