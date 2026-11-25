---
doc_id: syn01
title: "Training volume"
topic_tags: ["volume", "logging"]
citation_keys: ["ralston2017"]
---

# Training volume

> Draft: human citation verification and non-author review are pending; see SOURCES.md.

## Weekly effective sets and dose response

Weekly set volume describes repeated training exposure over a week. Ralston and
colleagues' meta-analysis found that medium or high weekly set conditions
generally produced somewhat larger strength improvements than low-volume
conditions. The evidence involved male participants and a small collection of
studies with design differences. It supports a qualified dose-response
relationship, not an unlimited benefit from adding sets or an individual optimum
[ralston2017](SOURCES.md#ralston2017).

The project's effective-set count is a separate operational definition. In
[architecture plan section 5.7](../milestone2-architecture-and-plan.md),
eligible sets are neither warm-up nor failed sets. When RPE is recorded, the
specified cutoff is RPE at least 7, corresponding to RIR at most 3. The planned
muscle accounting gives a primary muscle weight of 1.0 and a secondary muscle
weight of 0.5. Sets without RPE are counted as working sets and flagged. These
are project conventions, not validated universal conversion factors.

The research counts sets per exercise, whereas the project reports weighted
sets per muscle. Those quantities must not be treated as interchangeable.
Preserve the distinction between an observed weekly count, the eligibility rules
that produced it, and a configurable comparison band. A low count supports only
the project's qualified volume hypothesis when the required data are available;
it does not establish why an individual's performance has stalled.

The numerical band for `insufficient_weekly_volume` is not fixed in this document
[TO VERIFY]. Missing effort ratings should remain visible rather than becoming
invented ratings. Interpret weekly comparisons alongside consistent exercise
mapping and logging coverage. Cite the research for its group-level finding,
and cite the project configuration for any operational cutoff used in an
individual report.
