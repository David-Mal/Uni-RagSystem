---
doc_id: syn03
title: "RPE and RIR"
topic_tags: ["rpe", "fatigue_load"]
citation_keys: ["greig2020"]
---

# RPE and RIR

> Draft: human citation verification and non-author review are pending; see SOURCES.md.

## Effort, reserve and comparable-load drift

Rating of Perceived Exertion describes perceived effort. Repetitions in Reserve
describes additional repetitions the lifter believes were possible.
On a resistance-training RIR-based RPE scale, higher ratings correspond to fewer
estimated repetitions remaining. Greig and colleagues describe this perceptual
relationship and its use in performance monitoring
[greig2020](SOURCES.md#greig2020). Do not mix this scale with another RPE scale
without an explicit mapping.

The project's use of reserve follows its specified numerical convention:
[architecture plan section 5.7](../milestone2-architecture-and-plan.md) links
RPE at least 7 with RIR at most 3 and describes the adjustment `10 - RPE` when
estimating repetitions to failure. That convention does not make an unreported
effort rating recoverable from a load or repetition count.

RPE drift in this project is the slope of logged RPE at comparable load. The
plan's section 2.5 requires RPE on at least 50% of working sets and at least four
comparable-load sessions. Section 5.7 specifies loads within 5% and at least four
points. These are project rules, not universal fatigue boundaries.
An upward trend means the recorded work was being rated as harder;
it supports the qualified `fatigue_accumulation` hypothesis rather than
identifying a unique cause.

Greig's framework distinguishes fatigue from other performance variation.
A changed rating does not identify one hidden mechanism. Keep
exercise identity, repetition counts and rating coverage visible when comparing
sessions. Missing ratings cannot be replaced by assumed effort, and changing the
task can weaken comparability even when the external load looks similar.

Drift is the least-squares slope of session mean RPE per week; the steps and the
decision band are fixed in [indicator specification, section 3](../indicator-spec.md).
If the supplied records cannot support a comparable series, explain that drift
was not assessed rather than asserting fatigue from sparse entries.
