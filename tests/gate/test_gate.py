"""Signals, aggregation, failure policy, linking and the unbypassable gate (issue D9, plan §5.3)."""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from datetime import datetime
from typing import Any

import pytest

from src.gate import gate as gate_module
from src.gate import messages
from src.gate.aggregate import assess_text, log_level
from src.gate.gate import MESSAGE_ID, AgentContext, GateBlocked, GateResult, assess, run_gated
from src.gate.linking import link_message
from src.gate.signals import ClassifierSignal, ExtractorSignal, GateSignals, SignalReading
from src.ingest import CanonicalSet, CanonicalSets, Note, SetStore, open_store
from src.schemas import HypothesisLabel, TriageLevel

G, Y, R = TriageLevel.GREEN, TriageLevel.YELLOW, TriageLevel.RED
LOG = "u"
MON, WED = datetime(2026, 11, 2, 18), datetime(2026, 11, 4, 18)


class Fixed:
    """A model signal with a fixed answer, or a fixed exception."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer

    def assess(self, text: str) -> Any:
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def both(extractor: Any = G, classifier: Any = G) -> GateSignals:
    return GateSignals(Fixed(extractor), Fixed(classifier))


def obj(level: str = "green", **kw: Any) -> dict[str, Any]:
    base = {"exercise_id": "unknown", "kinematic_observation": "none", "load": None, "reps": None,
            "outcome": "completed", "rpe": None, "triage_level": level}  # fmt: skip
    return base | kw


def make_set(ts: datetime, name: str, exercise_id: str | None, **kw: Any) -> CanonicalSet:
    return CanonicalSet.build(
        workout_ts=ts, workout_name="W", exercise_name_raw=name, exercise_id=exercise_id, set_index=1, weight_kg=50.0,
        source_unit="kg", reps=5, source_app="t", **kw,
    )  # fmt: skip


@pytest.fixture
def store():
    with open_store() as db:
        yield db


def fill(db: SetStore, set_note: str | None = None, workout_note: str | None = None) -> list[Note]:
    """Monday: Squat (with the set note) and Bench, and one unmatched exercise. Wednesday: Row."""
    sets = (
        make_set(MON, "Squat", "Squat_ID", set_note=set_note, workout_note=workout_note),
        make_set(MON, "Bench", "Bench_ID", workout_note=workout_note),
        make_set(MON, "Odd machine", None, workout_note=workout_note),
        make_set(WED, "Row", "Row_ID"),
    )
    db.append_sets(LOG, CanonicalSets(sets=sets))
    return db.get_notes(LOG)


def gate(db: SetStore, signals: GateSignals | None = None, message: str | None = None) -> GateResult:
    return assess(db.get_notes(LOG), message, db, signals or both(), log_id=LOG)


# --- aggregation -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("extractor", [G, Y, R])
@pytest.mark.parametrize("classifier", [G, Y, R])
@pytest.mark.parametrize(("text", "rule"), [("good", G), ("knee aches", Y), ("dizzy", R)])
def test_level_is_the_maximum_of_the_three_signals(text: str, rule: TriageLevel, extractor, classifier) -> None:
    a = assess_text(text, both(extractor, classifier))
    assert a.level is max((rule, extractor, classifier), key=lambda x: x.severity)
    assert a.rule_level is rule and not a.unassessed_by_model


def test_log_level() -> None:
    assert log_level([]) is G and log_level([G, Y, G]) is Y and log_level([Y, R]) is R


# --- failure policy, one test per row of the table in plan 5.3 ----------------------------------------------------


def test_rules_always_give_a_signal_when_both_models_fail() -> None:
    a = assess_text("dizzy", both(RuntimeError("x"), RuntimeError("y")))
    assert a.rule_level is R and a.level is R and a.unassessed_by_model


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "",
        "[]",
        json.dumps({k: v for k, v in obj().items() if k != "triage_level"}),
        json.dumps(obj("purple")),
        json.dumps(obj(None)),  # type: ignore[arg-type]
        None,
    ],
    ids=["text", "empty", "list", "missing level", "bad level", "null level", "none"],
)
def test_extractor_unusable_after_one_retry_is_a_failed_signal(raw: Any) -> None:
    calls = []
    signal = ExtractorSignal(lambda t: calls.append(t) or raw)
    a = assess_text("good", GateSignals(signal, Fixed(G)))
    assert len(calls) == 2  # exactly one retry
    assert a.extractor.failed and a.level is Y and a.unassessed_by_model


def test_extractor_error_is_retried_and_then_failed() -> None:
    calls = []

    def broken(text: str) -> str:
        calls.append(text)
        raise ConnectionError("down")

    a = assess_text("good", GateSignals(ExtractorSignal(broken), Fixed(G)))
    assert len(calls) == 2 and a.level is Y and a.extractor.error == "extractor: ConnectionError"


def test_extractor_retry_can_succeed() -> None:
    answers = iter(["garbage", json.dumps(obj("green", exercise_id="Squat_ID"))])
    a = assess_text("good", GateSignals(ExtractorSignal(lambda _: next(answers)), Fixed(G)))
    assert a.level is G and not a.unassessed_by_model and a.extractor.exercise_id == "Squat_ID"


def test_classifier_error_is_a_failed_signal_without_retry() -> None:
    calls = []

    def broken(text: str) -> str:
        calls.append(text)
        raise RuntimeError("cuda")

    a = assess_text("good", GateSignals(Fixed(G), ClassifierSignal(broken, timeout_s=None)))
    assert len(calls) == 1 and a.classifier.failed and a.level is Y


def test_classifier_timeout_is_a_failed_signal() -> None:
    slow = ClassifierSignal(lambda _: time.sleep(5) or "green", timeout_s=0.05)
    start = time.monotonic()
    a = assess_text("good", GateSignals(Fixed(G), slow))
    assert time.monotonic() - start < 2
    assert a.classifier.failed and "TimeoutError" in (a.classifier.error or "") and a.level is Y


@pytest.mark.parametrize("answer", [None, "purple", 2, object(), SignalReading("purple")])  # type: ignore[arg-type]
def test_an_answer_that_is_not_a_level_is_a_failed_signal(answer: Any) -> None:
    assert assess_text("good", both(answer, G)).level is Y
    assert assess_text("good", both(G, answer)).level is Y


@pytest.mark.parametrize("signals", [both(RuntimeError(), G), both(G, RuntimeError()), GateSignals(), GateSignals(Fixed(G))])
def test_a_surviving_green_does_not_cancel_a_failed_signal(signals: GateSignals) -> None:
    a = assess_text("good", signals)
    assert a.level is Y and a.unassessed_by_model


@pytest.mark.parametrize("signals", [both(R, RuntimeError()), both(RuntimeError(), R)])
def test_a_surviving_red_stays_red(signals: GateSignals) -> None:
    assert assess_text("good", signals).level is R


def test_technical_failure_alone_never_gives_red() -> None:
    for error in (RuntimeError("red"), TimeoutError(), MemoryError(), ValueError()):
        assert assess_text("good", both(error, error)).level is Y


def test_a_valid_red_in_an_invalid_object_is_not_lost() -> None:
    signal = ExtractorSignal(lambda _: json.dumps(obj("red", rpe=11)))
    a = assess_text("good", GateSignals(signal, Fixed(G)))
    assert a.level is R and a.extractor.failed and a.unassessed_by_model


def test_a_salvaged_green_does_not_count_as_assessed() -> None:
    a = assess_text("good", GateSignals(ExtractorSignal(lambda _: obj("green", rpe=11)), Fixed(G)))
    assert a.level is Y and a.unassessed_by_model


def test_a_red_in_the_discarded_first_attempt_is_kept() -> None:
    answers = iter([obj("red", rpe=11), obj("green")])
    assert assess_text("good", GateSignals(ExtractorSignal(lambda _: next(answers)), Fixed(G))).level is R


def test_failures_are_logged_without_the_note_text(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assess_text("private words", both(RuntimeError("down"), G))
    assert "unassessed_by_model" in caplog.text and "private" not in caplog.text


def test_unknown_exercise_id_is_an_invalid_output() -> None:
    signal = ExtractorSignal(lambda _: obj("green", exercise_id="Invented"), exercise_ids={"Squat_ID"})
    assert assess_text("good", GateSignals(signal, Fixed(G))).level is Y


# --- linking -----------------------------------------------------------------------------------------------------


def test_set_note_excludes_its_own_exercise(store: SetStore) -> None:
    fill(store, set_note="knee aches")
    r = gate(store, both(SignalReading(Y, "Bench_ID"), G))  # the file structure wins over the extractor
    assert (r.level, r.excluded_exercise_ids, r.excluded_names) == (Y, {"Squat_ID"}, {"Squat"})
    assert r.allowed_exercise_ids == {"Bench_ID", "Row_ID"}
    assert r.disclaimer_flags == (messages.YELLOW_FLAG,)


def test_workout_note_linked_by_the_extractor(store: SetStore) -> None:
    fill(store, workout_note="shoulder aches")
    r = gate(store, both(SignalReading(Y, "Bench_ID"), G))
    assert r.excluded_exercise_ids == {"Bench_ID"} and messages.WORKOUT_FLAG not in r.disclaimer_flags


@pytest.mark.parametrize("hint", [None, "unknown"])
def test_unlinked_workout_note_excludes_the_whole_workout(store: SetStore, hint: str | None) -> None:
    fill(store, workout_note="shoulder aches")
    r = gate(store, both(SignalReading(Y, hint), G))
    assert r.excluded_exercise_ids == {"Squat_ID", "Bench_ID"}
    assert r.excluded_names == {"Squat", "Bench", "Odd machine"}  # listed for the user, also the unmatched one
    assert r.allowed_exercise_ids == {"Row_ID"}
    assert messages.WORKOUT_FLAG in r.disclaimer_flags


def test_extractor_id_outside_the_workout_does_not_narrow_the_exclusion(store: SetStore) -> None:
    fill(store, workout_note="shoulder aches")
    r = gate(store, both(SignalReading(Y, "Row_ID"), G))
    assert r.excluded_exercise_ids == {"Squat_ID", "Bench_ID", "Row_ID"} and r.allowed_exercise_ids == frozenset()


def test_note_on_an_unmatched_exercise(store: SetStore) -> None:
    store.append_sets(LOG, [make_set(MON, "Odd machine", None, set_note="elbow aches")])
    r = gate(store)
    assert r.excluded_names == {"Odd machine"} and r.excluded_exercise_ids == frozenset()


def test_unassessed_green_note_excludes_its_exercise(store: SetStore) -> None:
    notes = fill(store, set_note="moved well")
    r = gate(store, both(G, RuntimeError()))
    assert r.level is Y and r.excluded_exercise_ids == {"Squat_ID"}
    assert r.unassessed_notes == (notes[0].note_id,)
    assert r.disclaimer_flags == (messages.YELLOW_FLAG, messages.UNASSESSED_FLAG)


def test_green_log(store: SetStore) -> None:
    fill(store, set_note="moved well", workout_note="good day")
    r = gate(store, message="why did I stall?")
    assert (r.level, r.excluded_exercise_ids, r.disclaimer_flags, r.unassessed_notes) == (G, frozenset(), (), ())
    assert len(r.per_note) == 3


def test_yellow_message_with_a_resolvable_exercise(store: SetStore) -> None:
    fill(store)
    r = gate(store, both(SignalReading(Y, "Row_ID"), G), message="my elbow aches on rows")
    assert r.excluded_exercise_ids == {"Row_ID"} and not r.needs_clarification


@pytest.mark.parametrize("hint", [None, "unknown", "Not_In_This_Log"])
def test_yellow_message_without_a_resolvable_exercise_needs_clarification(store: SetStore, hint: str | None) -> None:
    fill(store)
    r = gate(store, both(SignalReading(Y, hint), G), message="my elbow aches")
    assert r.needs_clarification and messages.CLARIFICATION_FLAG in r.disclaimer_flags
    with pytest.raises(GateBlocked):
        AgentContext(r)
    assert link_message(hint, {"Row_ID"}).source == "unresolved"


# --- the gate as a whole -----------------------------------------------------------------------------------------


def test_one_red_note_makes_the_log_red(store: SetStore) -> None:
    fill(store, set_note="got dizzy", workout_note="knee aches")
    r = gate(store)
    assert r.level is R and r.allowed_exercise_ids == frozenset()
    assert r.disclaimer_flags == () and not r.needs_clarification  # red hides everything else


def test_red_message(store: SetStore) -> None:
    fill(store)
    r = gate(store, message="chest pain yesterday")
    assert r.level is R and r.per_note[-1].note_id == MESSAGE_ID


def test_notes_the_caller_forgets_are_still_assessed(store: SetStore) -> None:
    fill(store, set_note="got dizzy")
    assert assess([], None, store, both(), log_id=LOG).level is R


def test_notes_of_another_log_are_rejected(store: SetStore) -> None:
    note = fill(store, set_note="ok")[0].model_copy(update={"log_id": "other"})
    with pytest.raises(ValueError, match="other"):
        assess([note], None, store, both(), log_id=LOG)


def test_no_notes_and_blank_message_is_green(store: SetStore) -> None:
    fill(store)
    r = gate(store, GateSignals(), message="  ")
    assert r.level is G and r.per_note == ()


def test_every_note_is_in_the_result(store: SetStore) -> None:
    notes = fill(store, set_note="fine", workout_note="long day")
    r = gate(store, both(RuntimeError(), RuntimeError()))
    assert {n.note_id for n in r.per_note} == {n.note_id for n in notes} == set(r.unassessed_notes)


# --- unbypassable ------------------------------------------------------------------------------------------------


class Agent:
    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    def __call__(self, context: AgentContext) -> str:
        self.contexts.append(context)
        return "analysis"


def run(db: SetStore, agent: Agent, signals: GateSignals | None = None, message: str | None = None):
    return run_gated(agent, db.get_notes(LOG), message, db, signals or both(), log_id=LOG)


def test_agent_runs_on_green_and_yellow_with_the_allowed_sets(store: SetStore) -> None:
    fill(store, set_note="knee aches")
    agent = Agent()
    assert run(store, agent).output == "analysis"
    (context,) = agent.contexts
    assert context.log_id == LOG and context.allowed_exercise_ids == {"Bench_ID", "Row_ID"}
    assert context.allowed_hypotheses == frozenset(HypothesisLabel)


def test_agent_is_not_reached_on_red(store: SetStore) -> None:
    fill(store, set_note="chest pain")
    agent = Agent()
    r = run(store, agent)
    assert agent.contexts == [] and r.output is None and r.blocked_text == messages.RED_REFERRAL


def test_agent_is_not_reached_when_clarification_is_needed(store: SetStore) -> None:
    fill(store)
    agent = Agent()
    r = run(store, agent, message="something aches")
    assert agent.contexts == [] and r.blocked_text == messages.NEEDS_CLARIFICATION


def test_agent_is_not_reached_if_the_gate_raises(store: SetStore, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: Any, **__: Any) -> GateResult:
        raise RuntimeError("gate down")

    monkeypatch.setattr(gate_module, "assess", broken)
    agent = Agent()
    with pytest.raises(RuntimeError, match="gate down"):
        run(store, agent)
    assert agent.contexts == []


def test_gate_result_cannot_be_built_or_altered_outside_assess(store: SetStore) -> None:
    fill(store, set_note="chest pain")
    r = gate(store)
    fields = {f.name: getattr(r, f.name) for f in dataclasses.fields(r)}
    with pytest.raises(TypeError, match="only by gate.assess"):
        GateResult(**(fields | {"level": G}))
    with pytest.raises(TypeError, match="only by gate.assess"):
        dataclasses.replace(r, level=G)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.level = G  # type: ignore[misc]


@pytest.mark.parametrize("fake", [None, {"level": "green"}, "green", object()])
def test_agent_context_needs_a_gate_result(fake: Any) -> None:
    with pytest.raises(TypeError, match="GateResult"):
        AgentContext(fake)
    with pytest.raises(TypeError):
        AgentContext()  # type: ignore[call-arg]


def test_agent_context_refuses_red(store: SetStore) -> None:
    fill(store, set_note="chest pain")
    with pytest.raises(GateBlocked, match="red"):
        AgentContext(gate(store))


def test_no_hypothesis_is_allowed_without_exercises(store: SetStore) -> None:
    store.append_sets(LOG, [make_set(MON, "Squat", "Squat_ID", set_note="knee aches")])
    assert AgentContext(gate(store)).allowed_hypotheses == frozenset()


# --- fixed messages ----------------------------------------------------------------------------------------------


def test_fixed_messages_have_no_placeholders_and_every_flag_has_a_text() -> None:
    texts = [messages.RED_REFERRAL, *messages.FLAG_TEXTS.values()]
    assert len(texts) == 5
    for text in texts:
        assert text.strip() == text and not set("{}%") & set(text) and not any(c.isdigit() for c in text)
    assert "healthcare professional" in messages.RED_REFERRAL
