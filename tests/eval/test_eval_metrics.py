"""Tests for src.eval.metrics (issue P2) on the made-up toy gold in tests/data/toy_gold.jsonl.

Gold (exercise_id, kinematic_observation, load, reps, outcome, rpe, triage_level):
  g1 squat none 100kg 5 completed 8 green      g4 squat slow_bar_speed 60lb 10 failed 7.5 red
  g2 bench grinding_rep 80kg 8 partial null yellow   g5 bench none null 12 completed null green
  g3 deadlift none null null completed 9 red         g6 unknown other null null completed null yellow
Predictions (eval_helpers.toy_preds): g1 exact; g2 kinematic slow_bar_speed, load 80lb, rpe 7, rest right; g3 failure
(no_json); g4 kinematic none, reps null, load 60.0lb (equal to 60), rest right; g5 load 20kg, reps null, triage
yellow, rest right; g6 invalid pred (rpe 11, a failure that is still valid JSON).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.eval.eval_helpers import TOY_GOLD, label, pred_row, toy_preds, write_jsonl
from src.eval import metrics as M
from src.eval import run as R


def load_items(tmp_path: Path, pred_rows: list[Any], gold_path: Path = TOY_GOLD) -> list[M.Item]:
    _, gold = R.load_gold(gold_path, None)
    pred_path = write_jsonl(tmp_path / "p.jsonl", pred_rows)
    _, preds = R.load_preds(pred_path, None)
    return R.build_items(gold, preds, pred_path, gold_path)


@pytest.fixture
def items(tmp_path: Path) -> list[M.Item]:
    return load_items(tmp_path, toy_preds())


def test_counting_table_every_row() -> None:
    assert M.field_counts("a", "a") == (1, 0, 0)  # value, same value: TP
    assert M.field_counts("a", "b") == (0, 1, 1)  # value, other value: FP + FN
    assert M.field_counts("a", None) == (0, 0, 1)  # value, null or failure: FN
    assert M.field_counts(None, "b") == (0, 1, 0)  # null, value: FP
    assert M.field_counts(None, None) == (0, 0, 0)  # null, null or failure: nothing


def test_prf_undefined_values_are_none_not_fake() -> None:
    assert M.prf(0, 0, 0) == {"tp": 0, "fp": 0, "fn": 0, "precision": None, "recall": None, "f1": None}
    only_fn = M.prf(0, 0, 3)  # no TP but FN: F1 is 0, precision undefined, recall 0
    assert (only_fn["f1"], only_fn["precision"], only_fn["recall"]) == (0.0, None, 0.0)
    assert M.prf(0, 2, 0)["f1"] == 0.0
    assert M.prf(3, 0, 0)["f1"] == 1.0


def test_per_field_counts_and_f1(items: list[M.Item]) -> None:
    # (tp, fp, fn) and F1 = 2tp / (2tp + fp + fn), per item g1..g6:
    # exercise_id: g1 TP, g2 TP, g3 FN (failure), g4 TP, g5 TP, g6 FN (failure)        -> 4, 0, 2  F1 8/10 = 0.8
    # kinematic:   g1 TP, g2 FP+FN, g3 FN, g4 FP+FN (pred none), g5 TP, g6 FN          -> 2, 2, 4  F1 4/10 = 0.4
    # load:        g1 TP, g2 FP+FN (unit), g3 null/failure -, g4 TP (60 == 60.0),
    #              g5 gold null, pred value FP, g6 null/failure -                       -> 2, 2, 1  F1 4/7
    # reps:        g1 TP, g2 TP, g3 null/failure -, g4 FN (pred null), g5 FN, g6 -      -> 2, 0, 2  F1 4/6
    # outcome:     g1 TP, g2 TP, g3 FN, g4 TP, g5 TP, g6 FN                             -> 4, 0, 2  F1 0.8
    # rpe:         g1 TP, g2 gold null pred 7 FP, g3 FN, g4 TP, g5 null/null -, g6 -    -> 2, 1, 1  F1 4/6
    # triage:      g1 TP, g2 TP, g3 FN, g4 TP, g5 FP+FN (yellow vs green), g6 FN        -> 3, 1, 3  F1 6/10 = 0.6
    fields = M.headline(M.sum_counts(items))["fields"]
    expected = {
        "exercise_id": (4, 0, 2, 0.8),
        "kinematic_observation": (2, 2, 4, 0.4),
        "load": (2, 2, 1, 4 / 7),
        "reps": (2, 0, 2, 4 / 6),
        "outcome": (4, 0, 2, 0.8),
        "rpe": (2, 1, 1, 4 / 6),
        "triage_level": (3, 1, 3, 0.6),
    }
    assert set(fields) == set(expected) == set(M.FIELDS)
    for name, (tp, fp, fn, f1) in expected.items():
        got = fields[name]
        assert (got["tp"], got["fp"], got["fn"]) == (tp, fp, fn), name
        assert got["f1"] == pytest.approx(f1), name
    assert fields["exercise_id"]["precision"] == 1.0
    assert fields["exercise_id"]["recall"] == pytest.approx(4 / 6)


def test_micro_and_macro(items: list[M.Item]) -> None:
    # micro: TP 4+2+2+2+4+2+3 = 19, FP 0+2+2+0+0+1+1 = 6, FN 2+4+1+2+2+1+3 = 15 -> F1 38 / (38 + 6 + 15) = 38/59
    # macro: (0.8 + 0.4 + 4/7 + 2/3 + 0.8 + 2/3 + 0.6) / 7 = 4.50476 / 7 = 0.64354
    block = M.headline(M.sum_counts(items))
    assert (block["micro"]["tp"], block["micro"]["fp"], block["micro"]["fn"]) == (19, 6, 15)
    assert block["micro"]["f1"] == pytest.approx(38 / 59)
    assert block["micro"]["precision"] == pytest.approx(19 / 25)
    assert block["macro_f1"] == pytest.approx(0.64354, abs=1e-5)


def test_default_values_as_null(items: list[M.Item]) -> None:
    # Defaults (unknown / none / completed) become null on both sides.
    # exercise_id: gold g6 'unknown' -> null, its pred is a failure -> nothing:             4, 0, 1  F1 8/9
    # kinematic: gold null for g1, g3, g5; g2 pred slow_bar_speed vs grinding_rep FP+FN; g4 gold slow, pred none->null
    #            FN; g6 gold 'other' failure FN; g1/g5 null/null -, g3 null/failure -:      0, 1, 3  F1 0
    # outcome: gold completed -> null for g1, g3, g5, g6, preds null or failure -; g2, g4 TP: 2, 0, 0  F1 1
    # load, reps, rpe, triage unchanged: (2,2,1) (2,0,2) (2,1,1) (3,1,3)
    # micro: TP 4+0+2+2+2+2+3 = 15, FP 0+1+2+0+0+1+1 = 5, FN 1+3+1+2+0+1+3 = 11 -> F1 30/46
    # macro: (8/9 + 0 + 4/7 + 2/3 + 1 + 2/3 + 0.6) / 7 = 4.39365 / 7 = 0.62766
    block = M.headline(M.sum_counts(items, default_null=True))
    assert block["fields"]["kinematic_observation"]["f1"] == 0.0
    assert block["fields"]["kinematic_observation"]["precision"] == 0.0
    assert block["fields"]["outcome"]["f1"] == 1.0
    assert block["fields"]["exercise_id"]["f1"] == pytest.approx(8 / 9)
    assert block["micro"]["f1"] == pytest.approx(30 / 46)
    assert block["macro_f1"] == pytest.approx(0.62766, abs=1e-5)
    assert M.compute_metrics(items)["default_as_null"] == block


def test_majority_baseline_per_field_with_deterministic_tie_break(items: list[M.Item]) -> None:
    # Modal gold values (ties -> smallest repr): exercise_id bench (squat, bench both 2), kinematic none (3),
    # load null (3), reps null (2), outcome completed (4), rpe null (3), triage green (green, yellow, red all 2).
    # exercise_id: TP g2, g5; FP+FN for 4 others: 2, 4, 4 -> 1/3.  kinematic: 3, 3, 3 -> 0.5.
    # load: null predicted, 3 gold values FN: 0, 0, 3 -> 0.   reps: 0, 0, 4 -> 0.   outcome: 4, 2, 2 -> 2/3.
    # rpe: 0, 0, 3 -> 0.   triage: 2, 4, 4 -> 1/3.
    # micro: TP 11, FP 13, FN 23 -> 22/58;  macro: (1/3 + 1/2 + 0 + 0 + 2/3 + 0 + 1/3) / 7 = 1.83333 / 7
    base = M.majority_baseline(items)
    got = {f: (m["tp"], m["fp"], m["fn"]) for f, m in base["fields"].items()}
    assert got == {
        "exercise_id": (2, 4, 4),
        "kinematic_observation": (3, 3, 3),
        "load": (0, 0, 3),
        "reps": (0, 0, 4),
        "outcome": (4, 2, 2),
        "rpe": (0, 0, 3),
        "triage_level": (2, 4, 4),
    }
    assert base["micro"]["f1"] == pytest.approx(22 / 58)
    assert base["macro_f1"] == pytest.approx(1.83333 / 7, abs=1e-5)
    assert M.majority_baseline(list(reversed(items))) == base


def test_undefined_field_is_null_and_left_out_of_macro(tmp_path: Path) -> None:
    # Two items, rpe null in gold and pred, so rpe has no TP, FP or FN: F1 null, macro is the mean of the other six.
    gold = write_jsonl(tmp_path / "g.jsonl", [{"item_id": f"x{i}", "labels": label(rpe=None)} for i in (1, 2)])
    rows = [pred_row("x1", label(rpe=None)), pred_row("x2", label(rpe=None))]
    its = load_items(tmp_path, rows, gold)
    block = M.headline(M.sum_counts(its))
    assert block["fields"]["rpe"]["f1"] is None
    assert block["macro_f1"] == 1.0 and block["n_fields_in_macro"] == 6
    assert any("'rpe'" in w for w in M.undefined_warnings(block))


def test_triage_confusion_red_recall_and_green_fpr(items: list[M.Item]) -> None:
    # gold green g1, g5: g1 -> green, g5 -> yellow.  gold yellow g2, g6: g2 -> yellow, g6 -> failed (invalid pred).
    # gold red g3, g4: g3 -> failed, g4 -> red.
    t = M.triage_block(items)
    assert t["confusion"] == {
        "green": {"green": 1, "yellow": 1, "red": 0, "failed": 0},
        "yellow": {"green": 0, "yellow": 1, "red": 0, "failed": 1},
        "red": {"green": 0, "yellow": 0, "red": 1, "failed": 1},
    }
    assert t["red_recall"] == 0.5  # red miss: g3 is a failure on a red item
    assert (t["red_recall_wilson_lo"], t["red_recall_wilson_hi"]) == (
        pytest.approx(0.0945, abs=1e-3),
        pytest.approx(0.9055, abs=1e-3),
    )
    assert t["green_fpr"] == 0.5  # 1 of 2 green items predicted yellow or red
    assert t["green_fpr_failsafe"] == 0.5  # no green failure here


def test_green_fpr_failsafe_counts_failures(tmp_path: Path) -> None:
    # g1 (green) fails: plain FPR = g5 only = 1/2; fail-safe adds the failure = 2/2.
    rows = toy_preds()
    rows[0] = pred_row("g1", None, "invalid_json")
    t = M.triage_block(load_items(tmp_path, rows))
    assert t["green_fpr"] == 0.5
    assert t["green_fpr_failsafe"] == 1.0


def test_triage_undefined_without_red_or_green(tmp_path: Path) -> None:
    gold = write_jsonl(tmp_path / "g.jsonl", [{"item_id": "a", "labels": label(triage_level="yellow")}])
    t = M.triage_block(load_items(tmp_path, [pred_row("a", label(triage_level="yellow"))], gold))
    assert t["red_recall"] is None and t["red_recall_wilson_lo"] is None
    assert t["green_fpr"] is None and t["green_fpr_failsafe"] is None


def test_json_validity_and_failure_rate(items: list[M.Item]) -> None:
    # Failures: g3 (null pred) and g6 (fails revalidation) = 2/6. Valid JSON: all but g3 (no_json) = 5/6.
    s = M.compute_metrics(items)["secondary"]
    assert (s["n_failures"], s["failure_rate"]) == (2, pytest.approx(1 / 3))
    assert (s["n_valid_json"], s["json_validity_rate"]) == (5, pytest.approx(5 / 6))


def test_schema_error_is_valid_json_but_null_pred_without_error_is_not(tmp_path: Path) -> None:
    rows = toy_preds()
    rows[2] = pred_row("g3", None, "schema_error")
    assert M.compute_metrics(load_items(tmp_path, rows))["secondary"]["n_valid_json"] == 6
    rows[2] = pred_row("g3", None, None)
    assert M.compute_metrics(load_items(tmp_path, rows))["secondary"]["n_valid_json"] == 5


def test_labels_compare_after_validation(tmp_path: Path) -> None:
    # gold load 100 (int) and pred 100.0 are the same label; rpe 8 vs 8.0 too: all seven fields TP.
    rows = toy_preds()
    rows[0]["pred"] = dict(rows[0]["pred"], load={"value": 100.0, "unit": "kg"}, rpe=8.0)
    first = load_items(tmp_path, rows)[0]
    assert M.item_counts(first) == [(1, 0, 0)] * 7


def test_slices_under_ten_items_report_only_n(items: list[M.Item]) -> None:
    assert M.slice_metrics(items, "stratum") == {"a": {"n_items": 2}, "b": {"n_items": 4}}
    assert M.slice_metrics(items, "hard_negative") == {"true": {"n_items": 2}, "false": {"n_items": 4}}


def test_slices_with_ten_or_more_report_the_same_metrics(tmp_path: Path) -> None:
    rows = [{"item_id": f"b{i}", "stratum": "big", "labels": label()} for i in range(10)]
    rows += [{"item_id": "s0", "labels": label()}, {"item_id": "s1", "stratum": None, "labels": label()}]
    gold = write_jsonl(tmp_path / "g.jsonl", rows)
    its = load_items(tmp_path, [pred_row(r["item_id"], label()) for r in rows], gold)
    out = M.slice_metrics(its, "stratum")
    assert out["null"] == {"n_items": 2}  # missing and null form their own group
    assert out["big"]["n_items"] == 10
    assert out["big"]["headline"]["micro"]["f1"] == 1.0
    assert set(out["big"]) == set(M.compute_metrics(its))


def test_slice_and_cluster_field_errors(items: list[M.Item], tmp_path: Path) -> None:
    with pytest.raises(M.EvalError, match="absent from every gold item"):
        M.slice_metrics(items, "nope")
    with pytest.raises(M.EvalError, match="absent from every gold item"):
        M.cluster_keys(items, "nope")
    with pytest.raises(M.EvalError, match="not a scalar"):
        M.slice_metrics(items, "labels")
    rows = [{"item_id": "a", "family": "x", "labels": label()}, {"item_id": "b", "labels": label()}]
    gold = write_jsonl(tmp_path / "g.jsonl", rows)
    its = load_items(tmp_path, [pred_row("a", label()), pred_row("b", label())], gold)
    with pytest.raises(M.EvalError, match="'b'.*missing or null"):
        M.cluster_keys(its, "family")


def test_mcnemar_counts(tmp_path: Path, items: list[M.Item]) -> None:
    # B = gold itself (every item fully correct). Discordant pairs are the items where A is wrong.
    # exercise_id: A wrong on g3, g6 -> b_only 2 -> p = 2 * C(2,0) / 2^2 = 0.5
    # kinematic: A right on g1, g5 only (g5 is none vs none) -> b_only 4 -> p = 2 / 16 = 0.125
    # fully correct item: A right only on g1 -> b_only 5 -> p = 2 / 32 = 0.0625
    # red: gold red g3, g4; A hits g4 only -> b_only 1 -> p = min(1, 2 * 1 / 2) = 1
    gold_labels = [json.loads(x)["labels"] for x in TOY_GOLD.read_text(encoding="utf-8").splitlines()]
    perfect = load_items(tmp_path, [pred_row(f"g{i}", lab) for i, lab in enumerate(gold_labels, 1)])
    t = M.mcnemar_tests(items, perfect)
    assert (t["field.exercise_id"]["b_only_correct"], t["field.exercise_id"]["p_value"]) == (2, 0.5)
    kin = t["field.kinematic_observation"]
    assert (kin["b_only_correct"], kin["p_value"]) == (4, 0.125)
    full = t["fully_correct_item"]
    assert (full["b_only_correct"], full["p_value"]) == (5, 0.0625)
    assert (t["red"]["n"], t["red"]["b_only_correct"], t["red"]["p_value"]) == (2, 1, 1.0)
    swapped = M.mcnemar_tests(perfect, items)["fully_correct_item"]
    assert (swapped["a_only_correct"], swapped["p_value"]) == (5, 0.0625)
