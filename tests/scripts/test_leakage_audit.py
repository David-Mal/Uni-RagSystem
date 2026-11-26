"""Tests for scripts/leakage_audit.py (issue P4). Made-up data only, written into tmp dirs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.datagen.build_training import read_drop_ids
from scripts import leakage_audit as la
from src.datagen.partition import load_partition


REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data" / "manifests" / "partition.yaml"
PART = load_partition(MANIFEST)
MARKER = "zqxsecretmarker"
DIM = 64


def _families(pool: str, consumer: str) -> list[str]:
    return [f.id for f in PART.phrasing_families[pool] if f.consumer == consumer]


class FakeEmbedder:
    """Texts in ``table`` get the given 2-D vector (padded). Any other text gets its own orthogonal axis."""

    model_name = "fake"
    revision = "fake-rev"
    library_version = "0"

    def __init__(self, table: dict[str, tuple[float, float]] | None = None) -> None:
        self.table = table or {}
        self.axes: dict[str, int] = {}

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            if t in self.table:
                v = [0.0] * DIM
                v[0], v[1] = self.table[t]
            else:
                v = [0.0] * DIM
                v[2 + self.axes.setdefault(t, len(self.axes))] = 1.0
            out.append(v)
        return out


def item(item_id: str, text: str, stem: str = "train", /, **over) -> dict:
    pool, consumer = la.FILE_STEMS[stem]
    obj = {
        "item_id": item_id,
        "text": text,
        "pool": pool,
        "seed": PART.seed_range(pool)[0],
        "persona_id": PART.members("personas", pool)[0],
        "phrasing_family": _families(pool, consumer)[0],
    }
    obj.update(over)
    return {k: v for k, v in obj.items() if v is not None}


def write(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def golden(tmp: Path, texts: list[str], name: str = "g.jsonl") -> Path:
    return write(tmp / name, [{"item_id": f"g{i}", "text": t} for i, t in enumerate(texts)])


def audit(tmp: Path, rows: list[dict], texts: list[str], stem: str = "train", embedder=None):
    train = write(tmp / f"{stem}.jsonl", rows)
    return la.run_audit([train], [golden(tmp, texts)], MANIFEST, embedder or FakeEmbedder(), 1)


def reasons(result, item_id: str) -> set[str]:
    return result.drops.get(item_id, set())


# ---- references ----


def test_reference_examples_found_on_real_files() -> None:
    # docs/labeling-guideline.md has 8 rows marked "guideline example:" (lines 170-177);
    # plan section 3.3 has 1 quoted Input (the bench example).
    assert len(la.guideline_examples()) == 8
    assert len(la.plan_examples()) == 1
    assert len(la.reference_examples()) == 9
    assert "That set killed me." in la.guideline_examples()


def test_reference_extraction_on_small_files(tmp_path: Path) -> None:
    g = tmp_path / "g.md"
    g.write_text('| a | **guideline example:** "One two." Green. |\nnot **guideline example:** x\n', encoding="utf-8")
    p = tmp_path / "p.md"
    p.write_text('### 3.2 x\nInput: "outside"\n### 3.3 Messages\nInput: "inside here"\n### 3.4 y\nInput: "no"\n')
    assert la.guideline_examples(g) == ["One two."]
    assert la.plan_examples(p) == ["inside here"]


def test_reference_reasons(tmp_path: Path) -> None:
    ref = la.reference_examples()[0]  # "That set killed me."
    rows = [
        item("a", ref),  # same words: exact
        item("b", "Totally different words here"),
    ]
    res = audit(tmp_path, rows, ["something else entirely"])
    # same text gets the same fake vector, so the cosine check fires too
    assert reasons(res, "a") == {"reference_exact_duplicate", "reference_jaccard", "reference_cosine"}
    assert "b" not in res.drops
    assert res.n_reference == 9


# ---- normalization ----


def test_tokens_normalization() -> None:
    assert la.tokens("Bench, PRESS!!  80kg") == ["bench", "press", "80kg"]
    assert la.tokens("a-b_c/d e") == ["a", "b", "c", "d", "e"]
    # NFKC: fullwidth letters and the ligature fold to plain letters
    assert la.tokens("Ｂｅｎｃｈ ﬁne") == ["bench", "fine"]
    assert la.tokens("naïve café") == ["naïve", "café"]  # unicode letters are kept
    assert la.tokens("...") == []


def test_exact_duplicate_ignores_case_and_punctuation(tmp_path: Path) -> None:
    res = audit(tmp_path, [item("a", "BENCH, 80 kg!!! x5 felt ok")], ["bench 80 kg x5 felt ok"])
    assert reasons(res, "a") == {"exact_duplicate", "jaccard"}  # raw texts differ, so the fake vectors differ


# ---- jaccard thresholds ----


def test_jaccard_exactly_at_threshold_drops(tmp_path: Path) -> None:
    # golden "a b c d" -> grams {abc, bcd}; train "a b c x" -> {abc, bcx}; inter 1, union 3 -> 0.33 (keep)
    # train "a b c d e" -> {abc, bcd, cde}; inter 2, union 3 -> 0.67 (drop)
    # train "x a b c d" -> {xab, abc, bcd}; same 0.67. Exactly 0.5: golden {abc, bcd}, train {abc, bcd, cde, def}? no:
    # inter 2 union 4 = 0.5 -> train "a b c d e f" = {abc, bcd, cde, def} (drop, inclusive)
    # just under: "a b c d e f g" = {abc, bcd, cde, def, efg}: 2/5 = 0.4 (keep)
    rows = [
        item("third", "a b c x"),
        item("half", "a b c d e f"),
        item("two_thirds", "a b c d e"),
        item("two_fifths", "a b c d e f g"),
    ]
    res = audit(tmp_path, rows, ["a b c d"])
    assert "third" not in res.drops
    assert reasons(res, "half") == {"jaccard"}
    assert reasons(res, "two_thirds") == {"jaccard"}
    assert "two_fifths" not in res.drops


def test_under_three_words_use_single_words(tmp_path: Path) -> None:
    # golden "bench press": {bench, press}. "press bench" -> same set, 1.0 but not an identical sequence.
    # "bench" -> 1/2 = 0.5 drop (inclusive); "bench row curl" -> 3-grams, no overlap with words.
    # "bench row" -> {bench, row}: 1/3 keep.
    rows = [
        item("swap", "press bench"),
        item("one", "bench"),
        item("long", "bench row curl"),
        item("other", "bench row"),
    ]
    res = audit(tmp_path, rows, ["bench press"])
    assert reasons(res, "swap") == {"jaccard"}
    assert reasons(res, "one") == {"jaccard"}
    assert "long" not in res.drops
    assert "other" not in res.drops


def test_jaccard_helper_values() -> None:
    assert la.jaccard(frozenset(), frozenset()) == 0
    assert la.jaccard(la.grams(["a", "b"]), la.grams(["a", "b"])) == 1
    assert la.grams(["a", "b", "c", "d"]) == {("a", "b", "c"), ("b", "c", "d")}


# ---- cosine ----


def test_cosine_thresholds() -> None:
    table = {"g": (1.0, 0.0), "at": (0.9, 0.19**0.5), "below": (0.89, (1 - 0.89**2) ** 0.5), "same": (2.0, 0.0)}
    # cos(g, at) = 0.9 exactly (inclusive, drop); below = 0.89 (keep); same direction = 1.0 (drop)
    for text, hit in (("at", True), ("below", False), ("same", True)):
        assert la.cosine_hit(la.unit(table["g"]), la.unit(table[text])) is hit


def test_cosine_check_in_audit(tmp_path: Path) -> None:
    table = {"golden words": (1.0, 0.0), "x one": (0.9, 0.19**0.5), "x two": (0.89, (1 - 0.89**2) ** 0.5)}
    rows = [item("hit", "x one"), item("miss", "x two"), item("far", "unrelated words here")]
    res = audit(tmp_path, rows, ["golden words"], embedder=FakeEmbedder(table))
    assert reasons(res, "hit") == {"cosine"}
    assert "miss" not in res.drops and "far" not in res.drops


def test_reference_cosine(tmp_path: Path) -> None:
    ref = la.reference_examples()[1]
    table = {ref: (1.0, 0.0), "paraphrase of it": (1.0, 0.0)}
    res = audit(tmp_path, [item("a", "paraphrase of it")], ["golden words"], embedder=FakeEmbedder(table))
    assert reasons(res, "a") == {"reference_cosine"}


# ---- compliance ----


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"pool": "dev"}, "compliance_pool"),
        ({"pool": "golden"}, "compliance_pool"),
        ({"seed": 0}, "compliance_seed"),
        ({"seed": 10000}, "compliance_seed"),
        ({"seed": 20000}, "compliance_seed"),
        ({"seed": "7"}, "compliance_seed"),
        ({"persona_id": PART.members("personas", "dev")[0]}, "compliance_persona"),
        ({"persona_id": "ps_tr_unknown"}, "compliance_persona"),
        ({"phrasing_family": PART.members("phrasing_families", "dev")[0]}, "compliance_family"),
        ({"phrasing_family": "pf_tr_unknown"}, "compliance_family"),
        ({"phrasing_family": _families("train", "classifier")[0]}, "compliance_consumer"),
        ({"text": None}, "compliance_missing_field"),
        ({"text": "  "}, "compliance_missing_field"),
        ({"pool": None}, "compliance_missing_field"),
        ({"seed": None}, "compliance_missing_field"),
        ({"persona_id": None}, "compliance_missing_field"),
        ({"phrasing_family": None}, "compliance_missing_field"),
    ],
)
def test_each_compliance_reason(tmp_path: Path, over: dict, reason: str) -> None:
    res = audit(tmp_path, [item("a", "some training words here", **over)], ["golden words"])
    assert reasons(res, "a") == {reason}


def test_seed_range_bounds_are_inclusive(tmp_path: Path) -> None:
    lo, hi = PART.seed_range("train")
    rows = [item("lo", "first words here", seed=lo), item("hi", "second words here", seed=hi)]
    assert not audit(tmp_path, rows, ["golden words"]).drops


@pytest.mark.parametrize("stem", list(la.FILE_STEMS))
def test_consumer_mapping_per_stem(tmp_path: Path, stem: str) -> None:
    pool, consumer = la.FILE_STEMS[stem]
    other = "classifier" if consumer == "extractor" else "extractor"
    good = item("good", "good words here", stem)
    bad = item("bad", "bad words here", stem, phrasing_family=_families(pool, other)[0])
    res = audit(tmp_path, [good, bad], ["golden words"], stem)
    assert set(res.drops) == {"bad"}
    assert reasons(res, "bad") == {"compliance_consumer"}


def test_stem_table() -> None:
    assert la.FILE_STEMS == {
        "train": ("train", "extractor"),
        "dev": ("dev", "extractor"),
        "red_dev": ("dev", "extractor"),
        "triage_train": ("train", "classifier"),
        "triage_dev": ("dev", "classifier"),
    }


def test_multiple_reasons_on_one_item(tmp_path: Path) -> None:
    row = item("a", "golden words here", pool="dev", seed=5, persona_id="nope")
    res = audit(tmp_path, [row], ["golden words here"])
    # seed 5 is inside the train range, so only the pool and persona fields fail besides the two duplicate checks
    assert reasons(res, "a") == {"exact_duplicate", "jaccard", "cosine", "compliance_pool", "compliance_persona"}


# ---- errors ----


def test_unknown_stem_is_error(tmp_path: Path) -> None:
    bad = write(tmp_path / "other.jsonl", [item("a", "x y z")])
    with pytest.raises(la.AuditInputError, match="unknown training file"):
        la.run_audit([bad], [golden(tmp_path, ["g"])], MANIFEST, FakeEmbedder(), 1)


def test_duplicate_item_id_across_files_is_error(tmp_path: Path) -> None:
    a = write(tmp_path / "train.jsonl", [item("same", "one two three")])
    b = write(tmp_path / "dev.jsonl", [item("same", "four five six", "dev")])
    with pytest.raises(la.AuditInputError, match="duplicate item_id"):
        la.run_audit([a, b], [golden(tmp_path, ["g"])], MANIFEST, FakeEmbedder(), 1)


def test_golden_required_and_validated(tmp_path: Path) -> None:
    train = write(tmp_path / "train.jsonl", [item("a", "one two three")])
    with pytest.raises(la.AuditInputError, match="at least one --golden"):
        la.run_audit([train], [], MANIFEST, FakeEmbedder(), 1)
    nodir = tmp_path / "empty"
    nodir.mkdir()
    with pytest.raises(la.AuditInputError, match="no messages_"):
        la.run_audit([train], [nodir], MANIFEST, FakeEmbedder(), 1)
    no_text = write(tmp_path / "g.jsonl", [{"item_id": "g1"}])
    with pytest.raises(la.AuditInputError, match=r"g\.jsonl:1: missing or empty 'text'"):
        la.run_audit([train], [no_text], MANIFEST, FakeEmbedder(), 1)
    with pytest.raises(la.AuditInputError, match="missing or empty 'item_id'"):
        la.run_audit([train], [write(tmp_path / "h.jsonl", [{"text": "t"}])], MANIFEST, FakeEmbedder(), 1)


def test_training_item_without_id_is_error(tmp_path: Path) -> None:
    train = write(tmp_path / "train.jsonl", [item("a", "x y z"), item("b", "x y z", item_id=None)])
    with pytest.raises(la.AuditInputError, match=r"train\.jsonl:2"):
        la.run_audit([train], [golden(tmp_path, ["g"])], MANIFEST, FakeEmbedder(), 1)


def test_golden_directory_takes_messages_files_only(tmp_path: Path) -> None:
    d = tmp_path / "golden"
    golden(d, ["alpha beta gamma"], "messages_a.jsonl")
    golden(d, ["delta epsilon zeta"], "messages_b.jsonl")
    golden(d, ["eta theta iota"], "notes.jsonl")
    train = write(tmp_path / "train.jsonl", [item("a", "alpha beta gamma"), item("b", "delta epsilon zeta"),
                                             item("c", "eta theta iota")])
    res = la.run_audit([train], [d], MANIFEST, FakeEmbedder(), 1)
    assert set(res.drops) == {"a", "b"}
    assert res.n_golden == 2


# ---- outputs ----


def test_drop_ids_file_format_and_read_drop_ids(tmp_path: Path) -> None:
    rows = [item("tm-z", "golden words here"), item("tm-a", "ok fine words", seed=0), item("tm-m", "unique stuff here")]
    res = audit(tmp_path, rows, ["golden words here"])
    text = la.drop_ids_text(res)
    lines = text.splitlines()
    assert lines[0].startswith("# leakage audit round 1")
    assert lines[1] == "tm-a  # compliance_seed"
    assert lines[2] == "tm-z  # cosine,exact_duplicate,jaccard"  # the fake embedder gives equal texts one vector
    out = tmp_path / "drop_ids.txt"
    out.write_text(text, encoding="utf-8")
    assert read_drop_ids(out) == {"tm-a", "tm-z"}


def test_empty_drop_file_is_written_and_parsed(tmp_path: Path) -> None:
    out = tmp_path / "o" / "drop_ids.txt"
    rep = tmp_path / "o" / "r.md"
    code = run_cli(tmp_path, [item("a", "fine words here")], ["golden words"], out, rep)
    assert code == 0
    assert out.exists() and read_drop_ids(out) == set()
    assert "Clean (no new drop): yes" in rep.read_text(encoding="utf-8")


def run_cli(tmp: Path, rows, texts, out: Path, rep: Path, *extra: str, embedder=None, stem: str = "train") -> int:
    train = write(tmp / f"{stem}.jsonl", rows)
    argv = ["--train", str(train), "--golden", str(golden(tmp, texts)), "--manifest", str(MANIFEST),
            "--out-drop-ids", str(out), "--out-report", str(rep), "--round", "2", *extra]
    return la.main(argv, embedder or FakeEmbedder())


def test_expect_clean_exit_codes(tmp_path: Path) -> None:
    out, rep = tmp_path / "d.txt", tmp_path / "r.md"
    dirty = [item("a", "golden words here")]
    clean = [item("a", "fine unrelated text")]
    assert run_cli(tmp_path, dirty, ["golden words here"], out, rep) == 0
    assert run_cli(tmp_path, dirty, ["golden words here"], out, rep, "--expect-clean") == 1
    assert read_drop_ids(out) == {"a"}  # outputs are still written
    assert run_cli(tmp_path, clean, ["golden words here"], out, rep, "--expect-clean") == 0
    assert read_drop_ids(out) == {"a"}  # cumulative: the rebuilt data regenerates the same id from the same seed


def test_input_error_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "train.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    argv = ["--train", str(bad), "--golden", str(golden(tmp_path, ["g"])), "--round", "1",
            "--out-drop-ids", str(tmp_path / "d.txt"), "--out-report", str(tmp_path / "r.md"),
            "--manifest", str(MANIFEST)]
    assert la.main(argv, FakeEmbedder()) == 2
    assert "train.jsonl:1: invalid JSON" in capsys.readouterr().err
    assert not (tmp_path / "d.txt").exists()


def test_deterministic_output(tmp_path: Path) -> None:
    rows = [item("b", "golden words here"), item("a", "x y z", seed=0), item("c", "fine text here")]
    runs = []
    for n in (1, 2):
        out, rep = tmp_path / f"d{n}.txt", tmp_path / f"r{n}.md"
        run_cli(tmp_path, rows, ["golden words here"], out, rep)
        runs.append((out.read_bytes(), rep.read_bytes()))
    assert runs[0] == runs[1]


def test_report_contents(tmp_path: Path) -> None:
    out, rep = tmp_path / "d.txt", tmp_path / "r.md"
    run_cli(tmp_path, [item("a", "golden words here"), item("b", "fine text here")], ["golden words here"], out, rep)
    text = rep.read_text(encoding="utf-8")
    for needle in ("Round: 2", "Golden items checked against: 1", "Reference examples", "`fake-rev`",
                   "| train | 2 | 1 |", "| train | jaccard | 1 |", "golden/g.jsonl", "manifest", "guideline", "plan"):
        assert needle in text
    assert la.sha256_of(MANIFEST) in text
    assert "golden words here" not in text and "fine text here" not in text


def test_atomic_write_on_failure(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    out = tmp_path / "ok" / "d.txt"
    code = run_cli(tmp_path, [item("a", "fine text here")], ["golden words"], out, blocker / "r.md")
    assert code == 2
    assert not out.exists()
    assert not list((tmp_path / "ok").glob(".*"))  # no temp file left behind


def test_no_golden_content_in_any_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    secret_text = f"{MARKER} lifts heavy {MARKER}"
    g = write(tmp_path / "g.jsonl", [{"item_id": f"id-{MARKER}", "text": secret_text}])
    train = write(tmp_path / "train.jsonl", [item("a", secret_text), item("b", "fine text here")])
    out, rep = tmp_path / "d.txt", tmp_path / "r.md"
    argv = ["--train", str(train), "--golden", str(g), "--manifest", str(MANIFEST), "--out-drop-ids", str(out),
            "--out-report", str(rep), "--round", "1"]
    assert la.main(argv, FakeEmbedder()) == 0
    seen = capsys.readouterr()
    assert read_drop_ids(out) == {"a"}  # the leak was found ...
    blob = out.read_text(encoding="utf-8") + rep.read_text(encoding="utf-8") + seen.out + seen.err
    assert MARKER not in blob  # ... and reported without golden content

    # error paths: broken golden line, golden line without text, and a missing training field
    for content in (f'{{"item_id": "{MARKER}", "text": "{MARKER}" \n', json.dumps({"item_id": f"id-{MARKER}"}) + "\n"):
        g.write_text(content, encoding="utf-8")
        assert la.main(argv, FakeEmbedder()) == 2
        seen = capsys.readouterr()
        assert MARKER not in seen.out + seen.err
        assert "g.jsonl:1" in seen.err
    g.write_text(json.dumps({"item_id": "x", "text": secret_text}) + "\n" + "[1]\n", encoding="utf-8")
    assert la.main(argv, FakeEmbedder()) == 2
    seen = capsys.readouterr()
    assert MARKER not in seen.out + seen.err


def test_line_separator_characters_inside_text_are_legal(tmp_path: Path) -> None:
    # U+2028 and U+0085 are legal unescaped in JSON strings; str.splitlines() would cut the line there.
    path = tmp_path / "golden.jsonl"
    text = "a" + chr(0x2028) + "b" + chr(0x85) + "c"
    path.write_text(json.dumps({"item_id": "g1", "text": text}, ensure_ascii=False) + "\n", encoding="utf-8")
    assert la.read_golden([path]) == [text]


def test_drop_list_is_cumulative_across_rounds(tmp_path: Path) -> None:
    # Round 1 drops x1. The builder regenerates the same ids from the same seeds, so round 2 must keep x1 in the list
    # even though x1 is no longer in the rebuilt file.
    drop = tmp_path / "drop_ids.txt"
    drop.write_text("# leakage audit round 1\nx1  # jaccard\n", encoding="utf-8")
    result = la.AuditResult(
        drops={"x2": {"cosine"}}, stats={}, n_golden=1, n_reference=0, round_no=2, model="m", revision="r",
        library_version="0", hashes={}, carried=la.read_previous_drops(drop),
    )
    drop.write_text(la.drop_ids_text(result), encoding="utf-8")
    assert read_drop_ids(drop) == {"x1", "x2"}
    assert "x1  # jaccard" in drop.read_text(encoding="utf-8")
    assert not result.clean
    clean = la.AuditResult(
        drops={}, stats={}, n_golden=1, n_reference=0, round_no=3, model="m", revision="r",
        library_version="0", hashes={}, carried=la.read_previous_drops(drop),
    )
    assert clean.clean
    assert set(la.read_previous_drops(drop)) == {"x1", "x2"}
    assert "New drops in this round: 0" in la.report_text(clean)
    assert "from earlier rounds: 2" in la.report_text(clean)
