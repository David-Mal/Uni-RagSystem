"""Tests for scripts/anonymize_opengym.py (issue F1). Tiny synthetic input, no real data."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "anonymize_opengym", Path(__file__).resolve().parents[2] / "scripts" / "anonymize_opengym.py"
)
assert _SPEC and _SPEC.loader
anon = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(anon)

HEADER = "date,start_time,end_time,workout,workout_note,exercise,set,set_type,weight,unit,reps,rpe,note"
ROWS = [
    "2026-11-02,2026-11-02 19:35,2026-11-02 20:45,Upper1,slept badly,Barbell Bench Press,1,normal,100,kg,5,8,",
    "2026-11-02,2026-11-02 19:35,2026-11-02 20:45,Upper1,slept badly,Barbell Bench Press,2,normal,102.5,kg,4,,",
]
RAW = b"\xef\xbb\xbf" + ("\r\n".join([HEADER, *ROWS]) + "\r\n").encode("utf-8")


def test_no_options_is_byte_identical() -> None:
    out, free_text = anon.anonymize(RAW)
    assert out == RAW  # BOM, CRLF and column order preserved
    assert free_text["workout_note"] == {"slept badly"}
    assert free_text["note"] == set()


def test_shift_weeks_keeps_weekday_and_numbers() -> None:
    out, _ = anon.anonymize(RAW, shift_weeks=-3)
    text = out.decode("utf-8-sig")
    # 2026-11-02 (Monday) - 21 days = 2026-10-12 (Monday)
    assert text.splitlines()[1].startswith("2026-10-12,2026-10-12 19:35,2026-10-12 20:45,")
    assert ",102.5,kg,4,," in text  # weight/unit/reps untouched
    assert out.startswith(b"\xef\xbb\xbf") and b"\r\n" in out


def test_blank_columns() -> None:
    out, free_text = anon.anonymize(RAW, blank=("workout_note",))
    assert b"slept badly" not in out
    assert free_text["workout_note"] == set()


def test_unknown_blank_column_raises() -> None:
    with pytest.raises(ValueError):
        anon.anonymize(RAW, blank=("nickname",))


def test_bad_timestamp_raises_when_shifting() -> None:
    bad = RAW.replace(b"2026-11-02 19:35", b"02/11/2026 7:35 PM", 1)
    with pytest.raises(ValueError):
        anon.anonymize(bad, shift_weeks=1)


def test_refuses_golden_output(tmp_path: Path) -> None:
    raw = tmp_path / "raw.csv"
    raw.write_bytes(RAW)
    with pytest.raises(SystemExit):
        anon.main([str(raw), str(tmp_path / "data" / "golden" / "x.csv")])
