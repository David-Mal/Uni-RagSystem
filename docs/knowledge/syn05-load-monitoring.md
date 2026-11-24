---
doc_id: syn05
title: "Load monitoring"
topic_tags: ["load_monitoring", "fatigue_load"]
citation_keys: ["lolli2019", "impellizzeri2020"]
---

# Load monitoring

> Draft blocked for corpus approval: source-license clearance, full-text access to Impellizzeri, human verification and non-author review remain [TO VERIFY].

## Coupled and uncoupled ratios

Acute workload summarizes recent exposure; chronic workload covers a longer
reference period. Their ratio does not independently measure adaptation or
fatigue. A coupled calculation includes the
acute observations in the chronic reference. For the conventional four-week
example discussed by Lolli and colleagues, the denominator averages the acute
week together with three preceding weeks. Their analysis demonstrates that
shared observations can create correlation by construction
[lolli2019](SOURCES.md#lolli2019).

An uncoupled calculation excludes acute observations from the chronic reference.
Removing overlap addresses the shared-term problem without validating the ratio.
The accessible abstract of Impellizzeri
and colleagues' critique also questions normalization by ratios, including
uncoupled versions [impellizzeri2020](SOURCES.md#impellizzeri2020). Detailed
full-text verification remains [TO VERIFY]; the abstract is not a substitute
for reading the original article.

The project follows
[architecture plan section 5.7](../milestone2-architecture-and-plan.md):
acute means the last seven days, and chronic uses the preceding 21-28 days
excluding the acute period. The allowed load metrics are tonnage or RPE-weighted
tonnage. Report acute load, chronic load and their ratio separately, preserving
the metric and time windows. The ratio is a descriptive heuristic only, never a
predictive indicator or a causal conclusion.

Chronic duration within 21-28 days and normalization to comparable period units
remain [TO VERIFY]. Do not silently compare a
weekly total with an unnormalized multi-week total, choose a new smoothing
method or fill an absent chronic window. Window definitions and aggregation
belong to the numerical specification, not this synthesis.

Show the underlying exposures and coverage. Different denominators can alter the
ratio for identical recent training. No ratio threshold or explanation of
performance change follows from the ratio alone.
