"""Tests of the ingest core with a fake adapter and synthetic rows (issue D4)."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.ingest import (
    AdapterRegistry,
    BaseAdapter,
    CanonicalSet,
    CanonicalSets,
    IngestError,
    SetType,
    SourceProbe,
    ingest_workout_log,
    open_store,
)
from src.ingest.normalize import (
    clean_rpe,
    implausible_weight_flags,
    is_failed,
    parse_local_timestamp,
    parse_set_type,
    parse_unit,
    to_kg,
)
from src.tools.common import Provenance, Value

HEADER = ["when", "workout", "exercise", "n", "type", "w", "unit", "reps", "rpe", "note", "wnote"]


class FakeAdapter(BaseAdapter):
    """Minimal CSV adapter used only here."""

    name = "fake"

    def detect(self, probe: SourceProbe) -> bool:
        return probe.header == tuple(HEADER)

    def to_canonical(self, source: Path) -> CanonicalSets:
        sets, flags = [], []
        with source.open(encoding="utf-8-sig", newline="") as stream:
            for line, r in enumerate(csv.DictReader(stream), start=2):
                unit = parse_unit(r["unit"])
                reps = int(r["reps"]) if r["reps"] else None
                rpe, flag = clean_rpe(float(r["rpe"]) if r["rpe"] else None, f"line {line}")
                if flag:
                    flags.append(flag)
                sets.append(
                    CanonicalSet.build(
                        workout_ts=parse_local_timestamp(r["when"], "%Y-%m-%d %H:%M"),
                        workout_name=r["workout"],
                        exercise_name_raw=r["exercise"],
                        set_index=int(r["n"]),
                        set_type=parse_set_type(r["type"], {t.value: t for t in SetType}),
                        weight_kg=to_kg(float(r["w"]) if r["w"] else None, unit),
                        source_unit=unit,
                        reps=reps,
                        rpe=rpe,
                        failed=is_failed(reps),
                        set_note=r["note"] or None,
                        workout_note=r["wnote"] or None,
                        source_app=self.name,
                    )
                )
        return CanonicalSets(sets=tuple(sets), flags=tuple(flags))


def row(**kw: str) -> dict[str, str]:
    base = dict(zip(HEADER, ["2026-11-02 18:00", "A", "Squat", "1", "normal", "100", "kg", "5", "8", "", ""], strict=True))
    return base | kw


DAY1 = [row(), row(n="2", reps="4"), row(exercise="Bench", w="60", reps="8")]
DAY2 = [row(when="2026-11-04 18:00"), row(when="2026-11-04 18:00", n="2", reps="0")]


def write(path: Path, rows: list[dict[str, str]], header: list[str] = HEADER) -> Path:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, header)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def reg() -> AdapterRegistry:
    return AdapterRegistry([FakeAdapter()])


def codes(result) -> list[str]:
    return [f.code for f in result.flags]


def test_first_ingest(tmp_path: Path, reg: AdapterRegistry) -> None:
    with open_store() as db:
        r = ingest_workout_log(write(tmp_path / "a.csv", DAY1 + DAY2), log_id="u1", store=db, registry=reg)
        assert r.log_id == "u1" and r.source_app == "fake"
        assert r.counts == {
            "rows_read": 5, "sets_added": 5, "duplicates": 0, "workouts_added": 2, "workouts_known": 0, "notes": 0,
        }  # fmt: skip
        assert r.unmatched_names == ["Bench", "Squat"]
        assert r.flags == []
        got = db.get_sets("u1")
        assert [(s.exercise_name_raw, s.set_index) for s in got] == [
            ("Squat", 1), ("Squat", 2), ("Bench", 1), ("Squat", 1), ("Squat", 2),
        ]  # fmt: skip
        assert {s.log_id for s in got} == {"u1"}


def test_reingest_is_idempotent(tmp_path: Path, reg: AdapterRegistry) -> None:
    path = write(tmp_path / "a.csv", DAY1 + DAY2)
    with open_store() as db:
        first = ingest_workout_log(path, store=db, registry=reg)
        before = db.get_sets(first.log_id)
        second = ingest_workout_log(path, store=db, registry=reg)
        assert second.log_id == first.log_id  # derived from the content
        assert second.counts["sets_added"] == 0 and second.counts["workouts_known"] == 2
        assert db.get_sets(first.log_id) == before
        assert second.flags == []


def test_new_export_appends_only_unseen_workouts(tmp_path: Path, reg: AdapterRegistry) -> None:
    with open_store() as db:
        ingest_workout_log(write(tmp_path / "a.csv", DAY1), log_id="u1", store=db, registry=reg)
        r = ingest_workout_log(write(tmp_path / "b.csv", DAY1 + DAY2), log_id="u1", store=db, registry=reg)
        assert (r.counts["sets_added"], r.counts["workouts_added"], r.counts["workouts_known"]) == (2, 1, 1)
        assert len(db.get_sets("u1")) == 5


def test_an_edited_workout_is_kept_and_flagged(tmp_path: Path, reg: AdapterRegistry) -> None:
    with open_store() as db:
        ingest_workout_log(write(tmp_path / "a.csv", DAY1), log_id="u1", store=db, registry=reg)
        edited = [row(w="105"), *DAY1[1:]]
        r = ingest_workout_log(write(tmp_path / "b.csv", edited), log_id="u1", store=db, registry=reg)
        assert codes(r) == ["changed_workout"] and r.counts["sets_added"] == 0
        assert db.get_sets("u1")[0].weight_kg == 100


def test_logs_are_separate_namespaces(tmp_path: Path, reg: AdapterRegistry) -> None:
    path = write(tmp_path / "a.csv", DAY1)
    with open_store() as db:
        ingest_workout_log(path, log_id="u1", store=db, registry=reg)
        ingest_workout_log(path, log_id="u2", store=db, registry=reg)
        assert db.log_ids() == ["u1", "u2"]
        assert len(db.get_sets("u1")) == len(db.get_sets("u2")) == 3


def test_store_on_disk_survives_reopening(tmp_path: Path, reg: AdapterRegistry) -> None:
    path = write(tmp_path / "a.csv", DAY1)
    for expected in (3, 0):
        with open_store(tmp_path / "sub" / "s.duckdb") as db:
            assert ingest_workout_log(path, log_id="u1", store=db, registry=reg).counts["sets_added"] == expected


def test_duplicate_rows_are_stored_once_and_flagged(tmp_path: Path, reg: AdapterRegistry) -> None:
    with open_store() as db:
        r = ingest_workout_log(write(tmp_path / "a.csv", [*DAY1, DAY1[0]]), store=db, registry=reg)
        assert codes(r) == ["duplicate_set"]
        assert (r.counts["rows_read"], r.counts["sets_added"], r.counts["duplicates"]) == (4, 3, 1)


def test_same_rows_under_another_workout_name_are_duplicates(tmp_path: Path, reg: AdapterRegistry) -> None:
    path = write(tmp_path / "a.csv", [*DAY1, *(r | {"workout": "B"} for r in DAY1)])
    with open_store() as db:
        first = ingest_workout_log(path, log_id="u", store=db, registry=reg)
        assert (first.counts["sets_added"], first.counts["duplicates"]) == (3, 3)
        again = ingest_workout_log(path, log_id="u", store=db, registry=reg)
        assert again.counts["sets_added"] == 0 and "changed_workout" not in codes(again)


def test_unit_mix_is_flagged_within_one_exercise(tmp_path: Path, reg: AdapterRegistry) -> None:
    rows = [row(), row(n="2", w="225", unit="lb"), row(exercise="Bench", w="135", unit="lbs")]
    with open_store() as db:
        r = ingest_workout_log(write(tmp_path / "a.csv", rows), log_id="u", store=db, registry=reg)
        assert [(f.code, f.detail.split(":")[0]) for f in r.flags] == [("unit_mix", "Squat")]
        squat = db.get_sets("u", {"exercise_name_raw": "Squat"})
        assert [s.source_unit for s in squat] == ["kg", "lb"]
        # 225 lb * 0.45359237 = 102.05828 kg
        assert squat[1].weight_kg == pytest.approx(102.0583, abs=1e-4)


def test_unit_mix_across_two_exports(tmp_path: Path, reg: AdapterRegistry) -> None:
    with open_store() as db:
        ingest_workout_log(write(tmp_path / "a.csv", DAY1), log_id="u", store=db, registry=reg)
        new = [row(when="2026-11-06 18:00", unit="lb")]
        assert codes(ingest_workout_log(write(tmp_path / "b.csv", new), log_id="u", store=db, registry=reg)) == ["unit_mix"]


def test_bodyweight_rows_do_not_cause_a_unit_mix(tmp_path: Path, reg: AdapterRegistry) -> None:
    rows = [row(w="0"), row(n="2", unit="lb")]
    with open_store() as db:
        assert ingest_workout_log(write(tmp_path / "a.csv", rows), store=db, registry=reg).flags == []


@pytest.mark.parametrize("bad", ["04/11/2026 18:00", "2026-11-31 18:00", "2026-1-5 18:00", "2026-11-02", "", "soon"])
def test_bad_dates_fail_and_store_nothing(tmp_path: Path, reg: AdapterRegistry, bad: str) -> None:
    with open_store() as db:
        with pytest.raises(IngestError, match="date"):
            ingest_workout_log(write(tmp_path / "a.csv", [*DAY1, row(when=bad)]), log_id="u", store=db, registry=reg)
        assert db.get_sets("u") == []


def test_unknown_format(tmp_path: Path, reg: AdapterRegistry) -> None:
    with open_store() as db, pytest.raises(IngestError, match="^unknown format$"):
        ingest_workout_log(write(tmp_path / "a.csv", [], ["x", "y"]), store=db, registry=reg)


@pytest.mark.parametrize("content", [b"\xff\xfe\x00\x01", b"PK\x03\x04\x00\xff", b"\n"])
def test_non_csv_content_is_unknown_format(tmp_path: Path, reg: AdapterRegistry, content: bytes) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(content)
    with open_store() as db, pytest.raises(IngestError, match="unknown format"):
        ingest_workout_log(path, store=db, registry=reg)


def test_bad_bytes_after_a_valid_header(tmp_path: Path, reg: AdapterRegistry) -> None:
    path = write(tmp_path / "a.csv", DAY1 * 3000)
    path.write_bytes(path.read_bytes() + b"\xff\xfe\n")
    with open_store() as db, pytest.raises(IngestError):
        ingest_workout_log(path, store=db, registry=reg)


def test_missing_empty_and_header_only_files(tmp_path: Path, reg: AdapterRegistry) -> None:
    (tmp_path / "empty.csv").touch()
    cases = {"nope.csv": "not found", "empty.csv": "empty", "header.csv": "no sets"}
    write(tmp_path / "header.csv", [])
    for name, message in cases.items():
        with open_store() as db, pytest.raises(IngestError, match=message):
            ingest_workout_log(tmp_path / name, store=db, registry=reg)


def test_app_hint(tmp_path: Path, reg: AdapterRegistry) -> None:
    path = write(tmp_path / "a.csv", DAY1)
    with open_store() as db:
        assert ingest_workout_log(path, app_hint="fake", store=db, registry=reg).source_app == "fake"
        with pytest.raises(IngestError, match="unknown app"):
            ingest_workout_log(path, app_hint="strong", store=db, registry=reg)
        other = write(tmp_path / "b.csv", [], ["x"])
        with pytest.raises(IngestError, match="unknown format"):  # a hint does not skip detection
            ingest_workout_log(other, app_hint="fake", store=db, registry=reg)


def test_two_matching_adapters_are_ambiguous(tmp_path: Path) -> None:
    class Other(FakeAdapter):
        name = "other"

    registry = AdapterRegistry([FakeAdapter(), Other()])
    path = write(tmp_path / "a.csv", DAY1)
    with open_store() as db:
        with pytest.raises(IngestError, match="ambiguous"):
            ingest_workout_log(path, store=db, registry=registry)
        assert ingest_workout_log(path, app_hint="other", store=db, registry=registry).source_app == "other"
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Other())


def test_failed_sets(tmp_path: Path, reg: AdapterRegistry) -> None:
    rows = [row(reps="0"), row(n="2", type="failure"), row(n="3", reps="")]
    with open_store() as db:
        ingest_workout_log(write(tmp_path / "a.csv", rows), log_id="u", store=db, registry=reg)
        # 0 reps = failed; taken to failure with reps is not failed; missing reps is not failed
        assert [s.failed for s in db.get_sets("u")] == [True, False, False]
    assert is_failed(5, flagged=True)


def test_notes_are_deduplicated_and_linked(tmp_path: Path, reg: AdapterRegistry) -> None:
    rows = [row(wnote="long day"), row(n="2", wnote="long day", note="felt heavy"), row(n="3", note="felt heavy ")]
    with open_store() as db:
        r = ingest_workout_log(
            write(tmp_path / "a.csv", rows), log_id="u", store=db, registry=reg, matcher={"Squat": "Barbell_Squat"}.get
        )
        assert [(n.scope, n.text, n.exercise_name_raw) for n in r.notes] == [
            ("workout", "long day", None),
            ("exercise", "felt heavy", "Squat"),
        ]
        assert r.notes[1].exercise_id == "Barbell_Squat" and r.notes[0].exercise_id is None


def test_matcher_fills_ids_and_never_overwrites(tmp_path: Path, reg: AdapterRegistry) -> None:
    path = write(tmp_path / "a.csv", DAY1)
    with open_store() as db:
        r = ingest_workout_log(path, log_id="u", store=db, registry=reg, matcher={"Squat": "S", "Bench": "unknown"}.get)
        assert r.unmatched_names == ["Bench"]
        r = ingest_workout_log(path, log_id="u", store=db, registry=reg, matcher=lambda _: "NEW")
        assert {s.exercise_name_raw: s.exercise_id for s in db.get_sets("u")} == {"Squat": "S", "Bench": "NEW"}
        assert r.unmatched_names == []


def test_get_sets_filters(tmp_path: Path, reg: AdapterRegistry) -> None:
    with open_store() as db:
        ingest_workout_log(write(tmp_path / "a.csv", DAY1 + DAY2), log_id="u", store=db, registry=reg)
        assert len(db.get_sets("u", {"exercise_name_raw": "Squat"})) == 4
        assert len(db.get_sets("u", {"since": date(2026, 11, 3)})) == 2
        assert len(db.get_sets("u", {"until": date(2026, 11, 2)})) == 3  # inclusive
        assert len(db.get_sets("u", {"set_type": SetType.NORMAL})) == 5
        with pytest.raises(ValueError, match="unknown filter"):
            db.get_sets("u", {"exercise": "Squat"})


def test_implausible_values_are_flagged(tmp_path: Path, reg: AdapterRegistry) -> None:
    rows = [row(w="5000"), row(n="2", rpe="12")]
    with open_store() as db:
        r = ingest_workout_log(write(tmp_path / "a.csv", rows), log_id="u", store=db, registry=reg)
        assert sorted(codes(r)) == ["implausible_rpe", "implausible_weight"]
        got = db.get_sets("u")
        assert got[0].weight_kg == 5000 and got[1].rpe is None
    at_limit = CanonicalSet.build(
        workout_ts=datetime(2026, 1, 1), exercise_name_raw="x", set_index=1, weight_kg=500.0, source_unit="kg",
        source_app="t",
    )  # fmt: skip
    assert implausible_weight_flags([at_limit]) == []


def test_set_id_depends_on_content_only() -> None:
    base = dict(workout_ts=datetime(2026, 1, 1, 9), exercise_name_raw="x", set_index=1, source_unit="kg", source_app="t")
    a = CanonicalSet.build(**base, weight_kg=100.0, reps=5, rpe=8.0)
    assert a.set_id == CanonicalSet.build(**base, weight_kg=100, reps=5, rpe=8, workout_name="other").set_id
    for change in ({"weight_kg": 101}, {"reps": 6}, {"rpe": 8.5}, {"rpe": None}):
        assert a.set_id != CanonicalSet.build(**(base | {"weight_kg": 100, "reps": 5, "rpe": 8} | change)).set_id


def test_model_rejects_timezones_and_negative_numbers() -> None:
    base = dict(exercise_name_raw="x", set_index=1, source_unit="kg", source_app="t")
    with pytest.raises(ValidationError):
        CanonicalSet.build(workout_ts=datetime.fromisoformat("2026-01-01T09:00:00+02:00"), **base)
    with pytest.raises(ValidationError):
        CanonicalSet.build(workout_ts=datetime(2026, 1, 1), weight_kg=-1.0, **base)


def test_units() -> None:
    assert [parse_unit(u) for u in ("kg", "LB", " lbs ")] == ["kg", "lb", "lb"]
    for bad in ("", "stone"):
        with pytest.raises(IngestError, match="unit"):
            parse_unit(bad)
    assert to_kg(None, "lb") is None and to_kg(80.0, "kg") == 80.0
    with pytest.raises(IngestError, match="set type"):
        parse_set_type("amrap", {})


def test_dataframe_conversion() -> None:
    s = CanonicalSet.build(
        workout_ts=datetime(2026, 1, 1), exercise_name_raw="x", set_index=1, weight_kg=10.0, source_unit="kg",
        source_app="t",
    )  # fmt: skip
    df = CanonicalSets(sets=(s,)).to_dataframe()
    assert df.loc[0, "set_type"] == "normal" and df.loc[0, "weight_kg"] == 10.0
    assert list(CanonicalSets(sets=()).to_dataframe().columns) == list(CanonicalSet.model_fields)


def test_tool_values_round_trip() -> None:
    v = Value(
        value_id="v_x_0001", name="x", value=1.5, unit="kg",
        provenance=Provenance(formula="f", input_row_ids=["a"], tool_version="t", config_hash="h"),
    )  # fmt: skip
    with open_store() as db:
        db.save_values("run1", [v])
        assert db.get_values("run1") == {"v_x_0001": v}
        assert db.get_values("run2") == {}
        with pytest.raises(Exception, match="(?i)constraint|duplicate"):
            db.save_values("run1", [v])
