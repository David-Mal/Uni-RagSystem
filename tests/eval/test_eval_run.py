"""End-to-end tests for the harness CLI (src.eval.run, issue P2). Hand computations are in test_eval_metrics.py."""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.eval.eval_helpers import TOY_GOLD, label, pred_row, toy_preds, write_jsonl
from src.eval import run as R

OUTPUTS = ("metrics.json", "config.yaml", "run_manifest.json")


def cli(tmp_path: Path, *extra: str, pred: Path | None = None, gold: Path = TOY_GOLD, out: str = "out") -> int:
    pred = pred or write_jsonl(tmp_path / "preds.jsonl", toy_preds())
    return R.main(["--pred", str(pred), "--gold", str(gold), "--out", str(tmp_path / out), *extra])


def metrics(tmp_path: Path, out: str = "out") -> dict[str, Any]:
    return json.loads((tmp_path / out / "metrics.json").read_text(encoding="utf-8"))


def perfect_preds() -> list[dict[str, Any]]:
    gold = [json.loads(x) for x in TOY_GOLD.read_text(encoding="utf-8").splitlines()]
    return [pred_row(g["item_id"], g["labels"]) for g in gold]


def test_score_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(tmp_path, "--slice-by", "stratum", "--slice-by", "hard_negative") == 0
    m = metrics(tmp_path)
    assert m["headline"]["micro"]["f1"] == pytest.approx(38 / 59)  # hand computation in test_eval_metrics.py
    assert m["headline"]["macro_f1"] == pytest.approx(0.64354, abs=1e-5)
    assert m["triage"]["red_recall"] == 0.5
    assert m["secondary"]["n_failures"] == 2
    assert m["slices"]["stratum"] == {"a": {"n_items": 2}, "b": {"n_items": 4}}
    assert m["majority_baseline"]["micro"]["f1"] == pytest.approx(22 / 58)
    assert m["bootstrap"]["unit"] == "items" and m["bootstrap"]["n_resamples"] == 2000
    micro = m["bootstrap"]["metrics"]["micro_f1"]
    assert micro["point"] == pytest.approx(38 / 59) and micro["n_used"] == 2000
    assert micro["lo"] <= micro["hi"]
    assert "gold sha256: " + hashlib.sha256(TOY_GOLD.read_bytes()).hexdigest() in capsys.readouterr().out


def test_output_format_and_config(tmp_path: Path) -> None:
    assert cli(tmp_path, "--seed", "5") == 0
    for name in OUTPUTS:
        assert b"\r" not in (tmp_path / "out" / name).read_bytes()
    raw = (tmp_path / "out" / "metrics.json").read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), indent=2, sort_keys=True, allow_nan=False) + "\n"
    config = yaml.safe_load((tmp_path / "out" / "config.yaml").read_text(encoding="utf-8"))
    assert config["seed"] == 5 and config["resamples"] == 2000 and config["mode"] == "score"
    assert config["gold"] == str(TOY_GOLD)


def test_outputs_and_messages_contain_no_text_or_labels(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The toy gold has a text field and the preds a raw field; neither, nor label values, may appear anywhere.
    assert cli(tmp_path, "--slice-by", "stratum") == 0
    seen = capsys.readouterr()
    blob = seen.out + seen.err + "".join((tmp_path / "out" / n).read_text(encoding="utf-8") for n in OUTPUTS)
    for forbidden in ("TOYTEXT", "RAWTEXT", "deadlift", "grinding_rep", "slow_bar_speed"):
        assert forbidden not in blob


def test_bootstrap_deterministic_across_runs(tmp_path: Path) -> None:
    for out, seed in (("a", "1"), ("b", "1"), ("c", "2")):
        assert cli(tmp_path, "--seed", seed, out=out) == 0
    a, b, c = (metrics(tmp_path, o)["bootstrap"] for o in "abc")
    assert a == b
    assert a["metrics"]["micro_f1"] != c["metrics"]["micro_f1"]


def test_cluster_bootstrap_reports_clusters_and_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(tmp_path, "--cluster-by", "family") == 0
    boot = metrics(tmp_path)["bootstrap"]
    assert (boot["unit"], boot["n_units"]) == ("clusters", 3)
    assert "only 3 clusters" in capsys.readouterr().err
    assert any("only 3 clusters" in w for w in metrics(tmp_path)["warnings"])


def test_red_recall_undefined_resamples_are_skipped(tmp_path: Path) -> None:
    # Two red items out of six: a resample misses both with probability (4/6)^6 = 9%, so red recall is undefined there.
    assert cli(tmp_path) == 0
    used = metrics(tmp_path)["bootstrap"]["metrics"]["red_recall"]["n_used"]
    assert 1500 < used < 2000


# --- compare -----------------------------------------------------------------------------------------------------


def test_compare_difference_is_b_minus_a(tmp_path: Path) -> None:
    a = write_jsonl(tmp_path / "a.jsonl", toy_preds())
    b = write_jsonl(tmp_path / "b.jsonl", perfect_preds())
    assert cli(tmp_path, "--mode", "compare", "--pred-b", str(b), pred=a, out="ab") == 0
    m = metrics(tmp_path, "ab")
    # B is perfect: micro F1 1, macro 1, red recall 1; A: 38/59, 0.64354, 1/2.
    assert m["difference_point"]["micro_f1"] == pytest.approx(1 - 38 / 59)
    assert m["difference_point"]["red_recall"] == 0.5
    assert m["model_a"]["headline"]["micro"]["f1"] == pytest.approx(38 / 59)
    assert m["model_b"]["headline"]["micro"]["f1"] == 1.0
    assert "B - A" in m["difference_definition"]
    assert m["bootstrap"]["metrics"]["micro_f1"]["point"] == pytest.approx(1 - 38 / 59)
    assert m["mcnemar"]["fully_correct_item"]["p_value"] == 0.0625  # 5 vs 0 discordant: 2 / 2^5
    manifest = json.loads((tmp_path / "ab" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["inputs"]["pred_b"]["sha256"] == hashlib.sha256(b.read_bytes()).hexdigest()
    # Swapping A and B flips the sign and the discordant counts.
    assert cli(tmp_path, "--mode", "compare", "--pred-b", str(a), pred=b, out="ba") == 0
    s = metrics(tmp_path, "ba")
    assert s["difference_point"]["micro_f1"] == pytest.approx(-(1 - 38 / 59))
    assert s["mcnemar"]["fully_correct_item"]["a_only_correct"] == 5


def test_compare_supports_cluster_by_and_is_paired(tmp_path: Path) -> None:
    a = write_jsonl(tmp_path / "a.jsonl", toy_preds())
    # Identical A and B: every paired resample has difference exactly 0, so the interval is [0, 0].
    assert cli(tmp_path, "--mode", "compare", "--pred-b", str(a), "--cluster-by", "family", pred=a, out="same") == 0
    m = metrics(tmp_path, "same")
    assert m["bootstrap"]["unit"] == "clusters"
    assert (m["bootstrap"]["metrics"]["micro_f1"]["lo"], m["bootstrap"]["metrics"]["micro_f1"]["hi"]) == (0.0, 0.0)
    assert m["mcnemar"]["red"]["p_value"] == 1.0  # no discordant pairs


def test_compare_argument_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(tmp_path, "--mode", "compare") == 2
    assert cli(tmp_path, "--pred-b", str(TOY_GOLD)) == 2
    assert not (tmp_path / "out").exists()


# --- input errors (D2): exit code 2, nothing written, no input values in messages -------------------------------


def expect_error(tmp_path: Path, capsys: pytest.CaptureFixture[str], *extra: str, **kw: Any) -> str:
    assert cli(tmp_path, *extra, **kw) == 2
    assert not (tmp_path / kw.get("out", "out")).exists(), "no output may be left behind"
    return capsys.readouterr().err


def test_missing_and_extra_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = toy_preds()
    err = expect_error(tmp_path, capsys, pred=write_jsonl(tmp_path / "p.jsonl", rows[:-1]))
    assert "1 missing ('g6')" in err
    rows.append(pred_row("zzz", None, "no_json"))
    err = expect_error(tmp_path, capsys, pred=write_jsonl(tmp_path / "p.jsonl", rows))
    assert "1 extra ('zzz')" in err


def test_duplicate_ids(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = toy_preds()
    err = expect_error(tmp_path, capsys, pred=write_jsonl(tmp_path / "p.jsonl", [*rows, rows[0]]))
    assert "duplicate item_id 'g1'" in err and "p.jsonl:7" in err
    gold_rows = [json.loads(x) for x in TOY_GOLD.read_text(encoding="utf-8").splitlines()]
    gold = write_jsonl(tmp_path / "g.jsonl", [*gold_rows, gold_rows[0]])
    assert "duplicate item_id 'g1'" in expect_error(tmp_path, capsys, gold=gold)


def test_invalid_gold_is_an_error_without_echoing_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gold = write_jsonl(tmp_path / "g.jsonl", [{"item_id": "a", "labels": label(rpe=11, exercise_id="LEAK VALUE")}])
    err = expect_error(tmp_path, capsys, gold=gold, pred=write_jsonl(tmp_path / "p.jsonl", [pred_row("a", label())]))
    assert "g.jsonl:1" in err and "'a'" in err and "rpe" in err and "exercise_id" in err
    assert "LEAK" not in err and "11" not in err


def test_malformed_and_duplicate_key_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = json.dumps(pred_row("g1", None, "no_json"))
    bad_lines = [
        '{"item_id": "LEAK", broken',
        '{"item_id": "a", "item_id": "LEAK"}',
        '{"item_id": "a", "pred": NaN}',
        "[1]",
    ]
    for bad in bad_lines:
        err = expect_error(tmp_path, capsys, pred=write_jsonl(tmp_path / "p.jsonl", [good, bad]))
        assert "p.jsonl:2" in err and "LEAK" not in err


def test_empty_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "empty.jsonl").write_text("\n\n", encoding="utf-8")
    assert "no items" in expect_error(tmp_path, capsys, pred=tmp_path / "empty.jsonl")
    assert "no items" in expect_error(tmp_path, capsys, gold=tmp_path / "empty.jsonl")


def test_contradictory_and_unknown_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = toy_preds()
    rows[0] = pred_row("g1", rows[0]["pred"], "schema_error")  # non-null pred with an error
    err = expect_error(tmp_path, capsys, pred=write_jsonl(tmp_path / "p.jsonl", rows))
    assert "non-null pred together with error" in err and "'g1'" in err
    rows = toy_preds()
    rows[2] = pred_row("g3", None, "LEAKCODE")
    err = expect_error(tmp_path, capsys, pred=write_jsonl(tmp_path / "p.jsonl", rows))
    assert "unknown error code" in err and "LEAKCODE" not in err
    rows = toy_preds()
    del rows[0]["pred"]
    assert "missing key 'pred'" in expect_error(tmp_path, capsys, pred=write_jsonl(tmp_path / "p.jsonl", rows))


def test_invalid_pred_is_a_failure_not_an_error(tmp_path: Path) -> None:
    rows = toy_preds()
    rows[0]["pred"] = dict(rows[0]["pred"], reps=5.0)  # the JSON Schema accepts this, ExtractionResult does not
    assert cli(tmp_path, pred=write_jsonl(tmp_path / "p.jsonl", rows)) == 0
    assert metrics(tmp_path)["secondary"]["n_failures"] == 3


def test_resamples_below_minimum_and_bad_cluster_or_slice_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "at least 2000" in expect_error(tmp_path, capsys, "--resamples", "1999")
    assert "absent from every gold item" in expect_error(tmp_path, capsys, "--slice-by", "nope")
    assert "absent from every gold item" in expect_error(tmp_path, capsys, "--cluster-by", "nope")
    assert "not a scalar" in expect_error(tmp_path, capsys, "--slice-by", "labels")


def test_exercise_ids_apply_to_gold_and_preds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ids = tmp_path / "ids.txt"
    ids.write_text("squat\nbench\ndeadlift\n", encoding="utf-8")
    assert cli(tmp_path, "--exercise-ids", str(ids)) == 0
    # Same set applies to gold: squat is not in it, so gold g1 is invalid. For preds it is only a failure (below).
    ids2 = tmp_path / "ids.json"
    ids2.write_text(json.dumps(["bench", "deadlift"]), encoding="utf-8")
    err = expect_error(tmp_path, capsys, "--exercise-ids", str(ids2), out="out2")
    assert "invalid labels" in err and "exercise_id" in err  # gold g1 uses squat
    gold = write_jsonl(tmp_path / "g.jsonl", [{"item_id": "a", "labels": label(exercise_id="bench")}])
    pred = write_jsonl(tmp_path / "p.jsonl", [pred_row("a", label(exercise_id="squat"))])
    assert cli(tmp_path, "--exercise-ids", str(ids2), gold=gold, pred=pred, out="out3") == 0
    assert metrics(tmp_path, "out3")["secondary"]["n_failures"] == 1


# --- outputs -----------------------------------------------------------------------------------------------------


def test_refuses_to_overwrite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(tmp_path) == 0
    before = {n: (tmp_path / "out" / n).read_bytes() for n in OUTPUTS}
    assert cli(tmp_path) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert before == {n: (tmp_path / "out" / n).read_bytes() for n in OUTPUTS}
    # One existing file is enough, and nothing else is created.
    (tmp_path / "part").mkdir()
    (tmp_path / "part" / "config.yaml").write_text("keep", encoding="utf-8")
    assert cli(tmp_path, out="part") == 2
    assert sorted(os.listdir(tmp_path / "part")) == ["config.yaml"]


def test_failure_midway_leaves_no_partial_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real, calls = os.replace, []

    def flaky(src: Any, dst: Any) -> None:
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("disk full")
        real(src, dst)

    monkeypatch.setattr(R.os, "replace", flaky)
    with pytest.raises(OSError):
        cli(tmp_path)
    assert not (tmp_path / "out").exists()
    (tmp_path / "out").mkdir()
    calls.clear()
    with pytest.raises(OSError):
        cli(tmp_path)
    assert os.listdir(tmp_path / "out") == []


def test_manifest_contents(tmp_path: Path) -> None:
    ids = tmp_path / "ids.json"
    ids.write_text('["squat", "bench", "deadlift"]', encoding="utf-8")
    pred = write_jsonl(tmp_path / "preds.jsonl", toy_preds())
    assert cli(tmp_path, "--exercise-ids", str(ids), pred=pred) == 0
    man = json.loads((tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8"))
    sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (TOY_GOLD, pred, ids)}
    assert man["inputs"]["gold"]["sha256"] == sha["toy_gold.jsonl"]
    assert man["inputs"]["pred"]["sha256"] == sha["preds.jsonl"]
    assert man["inputs"]["exercise_ids"]["sha256"] == sha["ids.json"]
    assert man["inputs"]["pred_b"] is None
    assert man["gold_is_golden"] is False
    assert man["harness_version"] == R.HARNESS_VERSION and man["task"] == "extraction"
    assert set(man) >= {"git_commit", "git_dirty", "freeze_tag", "schema_version"}


def test_is_golden_path_needs_consecutive_parts_case_insensitive(tmp_path: Path) -> None:
    assert R.is_golden_path(tmp_path / "data" / "golden" / "messages.jsonl")
    assert R.is_golden_path(tmp_path / "Data" / "GOLDEN" / "x.jsonl")
    assert not R.is_golden_path(tmp_path / "data" / "dev" / "golden.jsonl")
    assert not R.is_golden_path(tmp_path / "golden" / "data" / "x.jsonl")


def test_git_info_tolerates_missing_git_and_picks_freeze_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_git(*_: Any, **__: Any) -> Any:
        raise FileNotFoundError("git")

    monkeypatch.setattr(R.subprocess, "run", no_git)
    assert R.git_info() == {"commit": None, "dirty": None, "freeze_tag": None}
    answers = {"status": " M x", "rev-parse": "abc123", "tag": "v1\nmessages-golden-v1\nfreeze-a"}
    monkeypatch.setattr(R, "_git", lambda *a: answers[a[0]])
    assert R.git_info() == {"commit": "abc123", "dirty": True, "freeze_tag": "freeze-a"}


def test_250_items_with_2000_resamples_is_fast(tmp_path: Path) -> None:
    rng = random.Random(1)
    gold_rows, pred_rows = [], []
    for i in range(250):
        lab = label(reps=rng.choice([None, 3, 5]), triage_level=rng.choice(["green", "yellow", "red"]))
        noisy = dict(lab, reps=rng.choice([None, 3, 5]), triage_level=rng.choice(["green", "yellow", "red"]))
        gold_rows.append({"item_id": f"i{i}", "cluster": f"c{i % 25}", "labels": lab})
        pred_rows.append(pred_row(f"i{i}", noisy if rng.random() < 0.8 else None, None))
    pred_rows = [r if r["pred"] is not None else pred_row(r["item_id"], None, "no_json") for r in pred_rows]
    gold = write_jsonl(tmp_path / "g.jsonl", gold_rows)
    start = time.perf_counter()
    assert cli(tmp_path, "--cluster-by", "cluster", gold=gold, pred=write_jsonl(tmp_path / "p.jsonl", pred_rows)) == 0
    assert cli(tmp_path, gold=gold, pred=tmp_path / "p.jsonl", out="items") == 0
    assert time.perf_counter() - start < 30


def test_line_separator_characters_inside_text_are_legal(tmp_path: Path) -> None:
    # U+2028 and U+0085 are legal unescaped in JSON strings; str.splitlines() would cut the line there.
    row = {"item_id": "x", "text": "a" + chr(0x2028) + "b" + chr(0x85) + "c", "labels": label()}
    gold = write_jsonl(tmp_path / "gold.jsonl", [json.dumps(row, ensure_ascii=False)])
    pred = write_jsonl(tmp_path / "p.jsonl", [pred_row("x", label())])
    assert cli(tmp_path, pred=pred, gold=gold) == 0
    assert metrics(tmp_path)["headline"]["micro"]["f1"] == 1.0


def test_unexpected_gold_key_is_not_echoed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gold = write_jsonl(tmp_path / "gold.jsonl", [{"item_id": "x", "labels": label(**{"SECRET note": 1})}])
    pred = write_jsonl(tmp_path / "p.jsonl", [pred_row("x", label())])
    assert cli(tmp_path, pred=pred, gold=gold) == 2
    err = capsys.readouterr().err
    assert "unexpected key" in err and "SECRET" not in err
