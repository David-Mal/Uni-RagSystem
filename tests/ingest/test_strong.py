from collections.abc import Callable
from datetime import datetime
import logging
from pathlib import Path

import pytest

from src.ingest.adapters.strong import StrongParseError, StrongParser, parse_timestamp, parse_workout_duration

FIXTURE = Path(__file__).resolve().parents[2] / "data/fixtures/strong/synthetic.csv"


def test_existing_12_row_fixture_and_required_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="src.ingest.adapters.strong"):
        rows = StrongParser().parse_source(FIXTURE, unit_hint="kg")
    assert len(rows) == 12
    assert [row.weight for row in rows] == [60, 65, 70, 40, 45, 50, 70, 80, 90, 80, 90, 110]
    assert [row.reps for row in rows] == [10, 8, 6, 12, 10, 8, 10, 8, 6, 8, 6, 0]
    assert rows[0].workout_at == datetime(2026, 11, 10, 18)
    # 45 minutes * 60 = 2700; 50 minutes * 60 = 3000 seconds.
    assert {row.workout_duration_seconds for row in rows[:6]} == {2700}
    assert {row.workout_duration_seconds for row in rows[6:]} == {3000}
    assert rows[10].rpe is None and rows[11].rpe == 10
    assert [row.row_number for row in rows if row.failed] == [12]
    assert all(row.mapped_set_type == "normal" and not row.source_failure_flag for row in rows)
    assert rows[0].notes == "Controlled reps" and rows[0].workout_notes == "Evening workout"
    assert rows[-1].notes == "Attempt not completed"
    assert all(row.distance is None and row.duration_seconds is None for row in rows)
    assert [row.set_order for row in rows[:3]] == [1, 2, 3]
    assert len(caplog.records) == 1
    assert "unverified" in caplog.text and "normal" in caplog.text


def test_ambiguous_units_never_default() -> None:
    with pytest.raises(StrongParseError, match="no declared unit"):
        StrongParser().parse_source(FIXTURE)
    pounds = StrongParser().parse_source(FIXTURE, unit_hint="lb")
    # Raw 60 lb remains 60; kg normalization belongs to D4.
    assert pounds[0].weight == 60 and pounds[0].source_unit == "lb"


@pytest.mark.parametrize("hint", ("lbs", "", 0, True))
def test_invalid_hint(hint: object) -> None:
    with pytest.raises(StrongParseError, match="unit_hint"):
        StrongParser().parse_source(FIXTURE, unit_hint=hint)


def test_explicit_kg_header_and_conflicting_hint(write_csv: Callable[..., Path], strong_values: dict[str, str]) -> None:
    values = {"Weight (kg)" if key == "Weight" else key: value for key, value in strong_values.items()}
    source = write_csv(tuple(values), [tuple(values.values())])
    parser = StrongParser()
    assert parser.detect(tuple(values))
    row = parser.parse_source(source)[0]
    assert row.weight == 225 and row.source_unit == "kg"
    assert row.raw["Weight (kg)"] == "225"
    with pytest.raises(StrongParseError, match="conflicts"):
        parser.parse_source(source, unit_hint="lb")


@pytest.mark.parametrize(("value", "seconds"), [
    ("45m", 2700), ("1h 20m", 4800), ("3h", 10800), ("0m", 0),
    ("1h 8m", 4080), ("2h 38m", 9480), ("", None),
])
def test_elapsed_duration_tokens(value: str, seconds: int | None) -> None:
    # Hours contribute 3600 seconds; minutes contribute 60. No clock-time guess.
    assert parse_workout_duration(value) == seconds


@pytest.mark.parametrize("value", ("00:45:00", "45s", "1h20m", " 45m", "45m ", "-1m"))
def test_reject_undocumented_duration(value: str) -> None:
    with pytest.raises(StrongParseError):
        parse_workout_duration(value)


@pytest.mark.parametrize("value", (
    "2030-02-29 09:00:00", "02/04/2030 09:00", "2030-04-02T09:00:00", "2030-04-02 09:00:00Z", "",
))
def test_strict_timestamps(value: str) -> None:
    with pytest.raises(StrongParseError):
        parse_timestamp(value)


def test_notes_optional_values_and_duplicate_rows_preserved(
    write_csv: Callable[..., Path], strong_values: dict[str, str],
) -> None:
    values = dict(strong_values, Notes='Comma, quotation "here"\nsecond line', **{
        "Workout Notes": "  Workout, text  ", "Distance": "1.25", "Seconds": "75", "RPE": "", "Reps": "0",
    })
    path = write_csv(tuple(values), [tuple(values.values())] * 2, bom=True)
    rows = StrongParser().parse_source(path, unit_hint="kg")
    assert len(rows) == 2  # No hashing, grouping or deduplication is performed.
    assert rows[0].notes == values["Notes"] and rows[0].workout_notes == values["Workout Notes"]
    assert rows[0].distance == 1.25 and rows[0].duration_seconds == 75
    assert rows[0].rpe is None and rows[0].failed
    assert rows[0].raw == rows[1].raw


def test_deterministic_parsing_and_private_snapshot() -> None:
    first = StrongParser().parse_source(FIXTURE, unit_hint="kg")
    assert first == StrongParser().parse_source(FIXTURE, unit_hint="kg")
    with pytest.raises(TypeError):
        first[0].raw["Weight"] = "999"
    assert not hasattr(first[0], "log_id") and not hasattr(StrongParser(), "to_canonical")
