"""output_verifier v0 (issue D10), including the injected-error cases reused in E6."""

from __future__ import annotations

from typing import Any

import pytest

from src.schemas import Claim, HypothesisLabel
from src.tools.common import Provenance, Value, load_indicator_config
from src.verifier.numbers import find_quantities, tolerance_class
from src.verifier.verify import ABSTENTION, ChunkInfo, VerificationResult, fallback_template, hypothesis_topics, verify

PROV = Provenance(formula="f", input_row_ids=["a"], tool_version="t", config_hash="h")


def value(vid: str, name: str, number: float | int | str, unit: str | None) -> Value:
    return Value(value_id=vid, name=name, value=number, unit=unit, provenance=PROV)


VALUES = {
    v.value_id: v
    for v in (
        value("v_e1rm_epley_0001", "e1rm_epley", 102.5, "kg"),
        value("v_e1rm_slope_0002", "e1rm_slope", -0.4, "kg/week"),
        value("v_rpe_drift_slope_0003", "rpe_drift_slope", 0.4, "rpe/week"),
        value("v_acute_chronic_ratio_0004", "acute_chronic_ratio", 1300 / 275, None),
        value("v_e1rm_sessions_0005", "e1rm_sessions", 5, "sessions"),
        value("v_chronic_load_weekly_0006", "chronic_load_weekly", 1300.0, "kg/week"),
        value("v_weekly_sets_0007", "weekly_sets", 3.0, "effective_sets"),
        value("v_label_0008", "label", "flat", None),
    )
}
E1RM, SLOPE, DRIFT, RATIO, COUNT, CHRONIC, SETS, TEXTUAL = VALUES
CHUNKS: dict[str, Any] = {
    "syn03#c04": ChunkInfo(topic_tags={"rpe"}, exercise_ids=set()),
    "syn01#c01": {"topic_tags": ["volume"], "exercise_ids": ["Barbell_Squat"], "section": "x"},
    "syn02#c02": ChunkInfo(topic_tags={"rpe"}, exercise_ids={"Excluded_Lift"}),
    "untagged": ChunkInfo(),
    "broken": {"topic_tags": 3},
}
EXERCISES = {"Barbell_Squat", "Bench"}


def claim(text: str = "RPE rose while strength stayed flat.", **kw: Any) -> dict[str, Any]:
    base = {"hypothesis_label": "fatigue_accumulation", "evidence_level": "supported", "exercise_id": "Barbell_Squat",
            "numbers": list(VALUES), "citations": ["syn03#c04"], "text": text}  # fmt: skip
    return base | kw


def check(*claims: Any, exercises: Any = EXERCISES, hypotheses: Any = tuple(HypothesisLabel)) -> VerificationResult:
    return verify(claims, VALUES, CHUNKS, exercises, hypotheses)


def codes(result: VerificationResult) -> list[str]:
    return [e.code for e in result.errors]


def test_pass() -> None:
    r = check(claim("e1RM is 102.5 kg, RPE drift +0.4 per week over 5 sessions."), claim(numbers=[], citations=[]))
    assert r.ok and r.errors == () and [c.ok for c in r.per_claim] == [True, True]


def test_claim_objects_are_accepted() -> None:
    assert check(Claim(**claim())).ok


def test_no_claims_is_not_ok() -> None:
    r = check()
    assert not r.ok and codes(r) == ["no_claims"] and r.errors[0].claim_index is None


# --- 1. value ids ------------------------------------------------------------------------------------------------


def test_missing_value_id() -> None:
    r = check(claim(numbers=["v_e1rm_epley_0001", "v_e1rm_epley_0999"]))
    assert codes(r) == ["unknown_value_id"] and "v_e1rm_epley_0999" in r.errors[0].message


def test_a_value_of_another_run_is_unknown() -> None:
    assert codes(verify([claim("No number.", numbers=[E1RM])], {}, CHUNKS, EXERCISES, HypothesisLabel)) == ["unknown_value_id"]


# --- 2. numbers in text ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "numbers"),
    [
        ("e1RM 102.5 kg", [E1RM]),
        ("e1RM 102,5 kg", [E1RM]),
        ("1RM about 102.5kg.", [E1RM]),
        ("e1RM 102", [E1RM]),  # within max(0.5, 1 % = 1.025)
        ("drift of +0.4 per week", [DRIFT]),
        ("slope -0.4", [SLOPE]),
        ("slope −0.4", [SLOPE]),
        ("fell by 0.4 per week", [SLOPE]),
        ("ratio 4.73 (heuristic)", [RATIO]),
        ("5 sessions", [COUNT]),
        ("3x5 logged", [SETS, COUNT]),
        ("3 × 5 logged", [SETS, COUNT]),
        ("3-5 sets", [SETS, COUNT]),
        ("load of 1,300 kg", [CHRONIC]),
        ("load of 1300 kg per week", [CHRONIC]),
        ("On 2026-11-25 it was 102.5 kg", [E1RM]),
        ("On 25 November, e1RM was 102.5 kg", [E1RM]),
        ("Since Nov 25, 2026 nothing changed", []),
        ("the 2nd and 11th week", []),
        ("see syn03#c04", []),
        ("value v_e1rm_epley_0001", [E1RM]),
        ("stayed flat over four weeks", []),
    ],
)
def test_accepted_texts(text: str, numbers: list[str]) -> None:
    r = check(claim(text, numbers=numbers))
    assert r.ok, r.errors


@pytest.mark.parametrize(
    ("text", "numbers", "code"),
    [
        ("e1RM 112.5 kg", [E1RM], "number_mismatch"),
        ("drift of -0.4", [DRIFT], "number_mismatch"),  # wrong sign
        ("slope +0.4", [SLOPE], "number_mismatch"),
        ("6 sessions", [COUNT], "number_mismatch"),
        ("5.5 sessions", [COUNT], "number_mismatch"),
        ("3x6 logged", [SETS, COUNT], "number_mismatch"),
        ("5 kg", [COUNT], "number_mismatch"),  # a count is not a weight
        ("50%", [COUNT], "number_mismatch"),
        ("label 7", [TEXTUAL], "number_mismatch"),
        ("225 lb", [E1RM], "wrong_unit"),
        ("102.5 lbs", [E1RM], "wrong_unit"),
        ("102.5 pounds", [E1RM], "wrong_unit"),
        ("rose 7 points", [], "unreferenced_number"),
        ("since 2026", [], "unreferenced_number"),
        ("2026-13-45", [], "unreferenced_number"),
        ("version v2", [E1RM], "stray_digit"),
        ("1e3 reps", [E1RM], "stray_digit"),
        ("1.2.3", [E1RM], "stray_digit"),
        ("½ of sets", [E1RM], "stray_digit"),
        ("syn09#c09 says so", [E1RM], "stray_digit"),  # an id that is not in the claim's own lists
        ("week5", [COUNT], "stray_digit"),
    ],
)
def test_rejected_texts(text: str, numbers: list[str], code: str) -> None:
    r = check(claim(text, numbers=numbers, citations=[]))
    assert not r.ok and set(codes(r)) == {code}, r.errors


@pytest.mark.parametrize(
    ("number", "quoted", "ok"),
    [
        # e1RM 40: 1 % = 0.4, so the bound is 0.5
        (value("v_x_0001", "e1rm_epley", 40.0, "kg"), "40.5", True),
        (value("v_x_0001", "e1rm_epley", 40.0, "kg"), "40.51", False),
        # e1RM 200: 1 % = 2
        (value("v_x_0001", "e1rm_epley", 200.0, "kg"), "198", True),
        (value("v_x_0001", "e1rm_epley", 200.0, "kg"), "197.9", False),
        (value("v_x_0001", "acute_chronic_ratio", 1.2, None), "1.21", True),
        (value("v_x_0001", "acute_chronic_ratio", 1.2, None), "1.22", False),
        (value("v_x_0001", "rpe_drift_slope", 0.5, "rpe/week"), "0.51", True),
        (value("v_x_0001", "rpe_drift_slope", 0.5, "rpe/week"), "0.52", False),
        (value("v_x_0001", "e1rm_slope", 3.05, "kg/week"), "3.5", False),  # not the 0.5 kg bound
        (value("v_x_0001", "e1rm_sessions", 4, "sessions"), "4", True),
        (value("v_x_0001", "e1rm_sessions", 4, "sessions"), "4.01", False),
    ],
)
def test_tolerance_edges(number: Value, quoted: str, ok: bool) -> None:
    r = verify([claim(f"It is {quoted}.", numbers=["v_x_0001"])], {"v_x_0001": number}, CHUNKS, EXERCISES, HypothesisLabel)
    assert r.ok is ok


def test_tolerance_classes() -> None:
    cfg = load_indicator_config()["verifier"]
    assert [tolerance_class(v, cfg) for v in VALUES.values()] == [
        "load", "slope", "slope", "ratio", "count", "load", "count", "count",
    ]  # fmt: skip


def test_every_bad_number_is_reported() -> None:
    r = check(claim("From 70 to 80 kg", numbers=[E1RM]))
    assert codes(r) == ["number_mismatch", "number_mismatch"]


def test_find_quantities_reads_commas_both_ways_only_for_thousands() -> None:
    (a,), _ = find_quantities("1,300")
    (b,), _ = find_quantities("102,5")
    assert a.readings == (1.3, 1300) and b.readings == (102.5,)


# --- 3. citations ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chunk", "code"),
    [
        ("syn99#c01", "unknown_chunk"),
        ("syn02#c02", "citation_exercise_not_allowed"),
        ("untagged", "citation_topic_not_allowed"),
        ("broken", "bad_chunk_metadata"),
    ],
)
def test_bad_citations(chunk: str, code: str) -> None:
    assert codes(check(claim(citations=["syn03#c04", chunk]))) == [code]


def test_citation_topic_must_belong_to_an_allowed_hypothesis() -> None:
    c = claim(citations=["syn01#c01"])
    assert check(c).ok
    assert codes(check(c, hypotheses=["fatigue_accumulation"])) == ["citation_topic_not_allowed"]


def test_chunk_about_several_exercises_needs_all_of_them_allowed() -> None:
    store = {"c": ChunkInfo(topic_tags={"rpe"}, exercise_ids={"Barbell_Squat", "Excluded_Lift"})}
    r = verify([claim(citations=["c"])], VALUES, store, EXERCISES, HypothesisLabel)
    assert codes(r) == ["citation_exercise_not_allowed"] and "Excluded_Lift" in r.errors[0].message


# --- 4. labels and exercise --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"hypothesis_label": "bad_form"}, "bad_label"),
        ({"evidence_level": "certain"}, "bad_evidence_level"),
        ({"exercise_id": "Excluded_Lift"}, "exercise_not_allowed"),
        ({"exercise_id": "unknown"}, "exercise_not_allowed"),
        ({"numbers": ["e1rm"]}, "invalid_claim"),
        ({"text": " "}, "invalid_claim"),
        ({"extra": 1}, "invalid_claim"),
    ],
)
def test_bad_fields(change: dict[str, Any], code: str) -> None:
    assert codes(check(claim(**change))) == [code]


@pytest.mark.parametrize("raw", [None, "text", 3, []])
def test_claims_that_are_not_objects(raw: Any) -> None:
    assert codes(check(raw)) == ["invalid_claim"]


def test_exercise_is_optional() -> None:
    assert check(claim(exercise_id=None)).ok


def test_hypothesis_outside_the_allowed_set() -> None:
    assert "hypothesis_not_allowed" in codes(check(claim(citations=[]), hypotheses=["load_spike"]))


def test_nothing_is_allowed_with_empty_sets() -> None:
    assert set(codes(check(claim(), exercises=(), hypotheses=()))) == {
        "hypothesis_not_allowed", "exercise_not_allowed", "citation_topic_not_allowed",
    }  # fmt: skip


def test_errors_carry_the_claim_index_and_do_not_affect_other_claims() -> None:
    r = check(claim(), claim("9 sessions"), claim(hypothesis_label="x"))
    assert not r.ok and [e.claim_index for e in r.errors] == [1, 2]
    assert [c.ok for c in r.per_claim] == [True, False, False]


def test_topics_cover_every_label() -> None:
    assert set(hypothesis_topics()) == {h.value for h in HypothesisLabel}


# --- fallback ----------------------------------------------------------------------------------------------------


def fallback(*claims: Any) -> str:
    return fallback_template(claims, check(*claims), VALUES)


def test_fallback_uses_only_passing_claims_and_never_the_agent_text() -> None:
    text = fallback(claim("SECRET wording.", numbers=[E1RM, SLOPE, COUNT]), claim("999 kg SECRET"))
    assert text == (
        "- Effort at comparable load may be rising. [Barbell_Squat] (supported by the data)\n"
        "  - e1rm epley: 102.5 kg\n"
        "  - e1rm slope: -0.4 kg/week\n"
        "  - e1rm sessions: 5 sessions\n"
        "  - Sources: syn03#c04"
    )


def test_fallback_abstains_if_nothing_survives() -> None:
    assert fallback(claim("999 kg")) == fallback() == ABSTENTION
    assert not any(ch.isdigit() for ch in ABSTENTION)


def test_fallback_covers_every_label() -> None:
    for label in HypothesisLabel:
        assert fallback(claim(hypothesis_label=label.value, citations=[])) != ABSTENTION


def test_fallback_rejects_a_result_of_other_claims() -> None:
    with pytest.raises(ValueError, match="does not belong"):
        fallback_template([claim()], check(claim(), claim()), VALUES)
