# RFC: Heuristic Load & Fatigue Analyzer

**Team:** [team name] | **Members:** [names] | **Status:** Draft for Week 4

## 1. Overview

We will build an agent, powered by a fine-tuned small language model (SLM, 1–3B parameters), that analyzes strength-training logs (CSV exports from Strong/Hevy) and produces **labeled hypotheses** about why a lifter has plateaued. The agent relies on indicators computed by tools, not by the model: estimated 1RM (e1RM), RPE drift, effective sets per muscle group, and uncoupled acute/chronic load. It adds cited background knowledge through RAG. It does not diagnose, prescribe, or give diet advice, and it abstains when the data is insufficient. All tools are exposed through an MCP server.

## 2. Motivation

Lifters accumulate large amounts of data, but apps only store it. Generic LLMs answer with confident, unverifiable advice and make arithmetic errors. Logs and free-text notes are personal (notes may mention pain), so a small model that runs locally is a real advantage.

This project demonstrates a trustworthy agent pattern: calculations are done by tools, claims are limited to the data and to cited sources, a mandatory safety gate runs before the agent, and the system abstains when evidence is weak. The acute:chronic workload ratio is contested in the literature, so we report acute load, chronic load, and their ratio separately and label the ratio as a heuristic, never as an injury threshold.

## 3. Goals

1. **Agent and MCP server.** At least 7 tools: `ingest_workout_log`, `match_exercise_rag`, `check_data_sufficiency`, `weekly_sets_per_muscle`, `compute_e1rm_and_drift` (failed reps excluded; body weight optional for relative strength), `uncoupled_load_analyzer`, `retrieve_knowledge`. An `output_verifier` checks the final answer. The agent decides which tools to call and stops with "insufficient data" when needed.
2. **Mandatory safety gate.** A three-level triage (green / yellow / red) runs *before* the agent and cannot be skipped. The final level is the most severe of three signals: deterministic rules, an SLM classifier, and the extracted `triage_level` field. Red (sharp pain, swelling, dizziness, chest pain) blocks the analysis and shows a fixed referral message. Yellow (mild discomfort) continues the load analysis but excludes the affected exercise and adds a disclaimer.
3. **Fine-tuned SLM.** QLoRA fine-tuning for closed-vocabulary extraction into a strict JSON schema (canonical `exercise_id`, `kinematic_observation` from a fixed enum, load, reps, outcome, RPE, triage level). All prompts and data are in English. We compare four setups: zero-shot, few-shot, zero-shot with constrained decoding, and the fine-tuned model with constrained decoding. The main metric is field-level F1, not JSON validity.
4. **RAG.** Two sources: a public-domain exercise database (free-exercise-db) for exercise matching and muscle mapping, and 5–10 team-written synthesis documents that summarize open-licensed sources with explicit citations. We report an ablation with and without RAG on `exercise_id` accuracy and citation validity.
5. **Golden Dataset, two layers, written by members who do not build the model.**
   - *Messages:* at least 250 held-out messages (110 green, 60 yellow, 80 red), never used in training.
   - *Logs:* at least 60 end-to-end scenarios, including at least 20 abstention cases, injected confounders (e.g., sleep loss), and numeric traps.
   - Labels come from two independent annotators; we report Cohen's kappa.
6. **Evaluation and hallucination control.**
   - *Safety:* target zero missed red cases on at least 80 red messages; with 80/80, the lower bound of the 95% Wilson interval is about 95%. We report the interval whatever the result.
   - *Verification:* the verifier checks that every number matches tool output (with tolerance) and that every citation exists; we manually check at least 30 outputs to confirm that citations support the claims.
   - *Experiments:* 3 models × 5 prompt variants, with the commercial model used only as a reference ceiling.

## 4. Non-goals

No diet or nutrition advice, no medical diagnosis, no exercise recommendations for areas with reported discomfort, no form diagnosis from text, and no claim that the acute:chronic ratio predicts injury.
