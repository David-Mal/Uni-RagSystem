from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from src.ingest.adapters.hevy import HevyParseError, HevyParser, parse_timestamp

FIXTURE = Path(__file__).resolve().parents[2] / "data/fixtures/hevy/synthetic.csv"


def test_existing_12_row_fixture() -> None:
    rows = HevyParser().parse_source(FIXTURE)
    assert len(rows) == 12
    assert [row.weight for row in rows] == [20, 60, 65, 40, 45, 30, 40, 70, 80, 80, 90, 110]
    assert [row.reps for row in rows] == [15, 10, 8, 12, 10, 12, 12, 10, 8, 8, 6, 0]
    assert Counter(row.mapped_set_type for row in rows) == {"warmup": 2, "normal": 8, "drop": 1, "failure": 1}
    assert rows[0].started_at == datetime(2026, 11, 10, 18)
    # 18:45 - 18:00 = 45 minutes = 2700 seconds; 17:50 - 17:00 = 3000.
    assert {row.workout_duration_seconds for row in rows[:6]} == {2700}
    assert {row.workout_duration_seconds for row in rows[6:]} == {3000}
    assert rows[10].rpe is None and [row.row_number for row in rows if row.failed] == [12]
    assert [row.set_index for row in rows[:3]] == [0, 1, 2]
    assert rows[5].exercise_notes == "Reduced load" and rows[5].source_set_type == "dropset"
    assert rows[0].workout_notes == "Evening workout" and rows[-1].workout_notes == "Afternoon workout"
    assert all(row.superset_id is None and row.duration_seconds is None and row.distance is None for row in rows)


@pytest.mark.parametrize(("weight_column", "unit"), [("weight_kg", "kg"), ("weight_lbs", "lb")])
@pytest.mark.parametrize("distance_column", ("distance_km", "distance_miles"))
def test_independent_unit_column_variants(
    write_csv: Callable[..., Path], hevy_values: dict[str, str],
    weight_column: str, unit: str, distance_column: str,
) -> None:
    values = {
        weight_column if key == "weight_kg" else distance_column if key == "distance_km" else key: value
        for key, value in hevy_values.items()
    }
    values[distance_column] = "1.5"
    path = write_csv(tuple(values), [tuple(values.values())])
    assert HevyParser.detect(tuple(values))
    row = HevyParser().parse_source(path)[0]
    # 225 stays 225 in the declared source unit; D4 alone performs kg conversion.
    assert row.weight == 225 and row.source_unit == unit and row.weight_column == weight_column
    assert row.distance == 1.5 and row.distance_column == distance_column


@pytest.mark.parametrize(("source_type", "mapped", "flagged"), [
    ("normal", "normal", False), ("warmup", "warmup", False),
    ("dropset", "drop", False), ("failure", "failure", True),
])
def test_source_types_and_positive_rep_failure(
    write_csv: Callable[..., Path], hevy_values: dict[str, str], source_type: str, mapped: str, flagged: bool,
) -> None:
    values = dict(hevy_values, set_type=source_type)
    path = write_csv(tuple(values), [tuple(values.values())])
    row = HevyParser().parse_source(path)[0]
    assert row.reps == 8 and row.mapped_set_type == mapped
    # Taken to failure with 8 reps completed: not a failed set
    assert row.taken_to_failure == flagged and row.failed is False


def test_zero_reps_is_independent_of_failure_type(write_csv: Callable[..., Path], hevy_values: dict[str, str]) -> None:
    values = dict(hevy_values, reps="0", rpe="")
    row = HevyParser().parse_source(write_csv(tuple(values), [tuple(values.values())]))[0]
    assert row.failed and not row.taken_to_failure and row.rpe is None


@pytest.mark.parametrize("source_type", ("working", "drop", "Warmup", ""))
def test_reject_unknown_source_types(
    write_csv: Callable[..., Path], hevy_values: dict[str, str], source_type: str,
) -> None:
    values = dict(hevy_values, set_type=source_type)
    with pytest.raises(HevyParseError, match="set_type"):
        HevyParser().parse_source(write_csv(tuple(values), [tuple(values.values())]))


def test_populated_superset_quoted_notes_and_separate_duration(
    write_csv: Callable[..., Path], hevy_values: dict[str, str],
) -> None:
    values = dict(hevy_values, superset_id="007", exercise_notes='Exercise, "quote"\nsecond line',
                  description="  Workout, notes  ", duration_seconds="75")
    path = write_csv(tuple(values), [tuple(values.values())], bom=True)
    row = HevyParser().parse_source(path)[0]
    assert row.superset_id == "007"  # Preserve opaque text, including leading zeros.
    assert row.exercise_notes == values["exercise_notes"] and row.workout_notes == values["description"]
    # 09:37 - 09:00 = 37*60 = 2220 workout seconds; set duration stays 75.
    assert row.workout_duration_seconds == 2220 and row.duration_seconds == 75


def test_midnight_duration_and_reverse_interval(write_csv: Callable[..., Path], hevy_values: dict[str, str]) -> None:
    values = dict(hevy_values, start_time="2 Apr 2030, 23:40", end_time="3 Apr 2030, 00:15")
    row = HevyParser().parse_source(write_csv(tuple(values), [tuple(values.values())]))[0]
    assert row.workout_duration_seconds == 2100  # 20 + 15 = 35 minutes; *60 = 2100.
    values["end_time"] = "2 Apr 2030, 23:39"
    with pytest.raises(HevyParseError, match="precedes"):
        HevyParser().parse_source(write_csv(tuple(values), [tuple(values.values())]))


@pytest.mark.parametrize("value", (
    "29 Feb 2030, 09:00", "2 April 2030, 09:00", "2 apr 2030, 09:00",
    "2030-04-02 09:00:00", "2 Apr 2030, 09:00Z", "",
))
def test_strict_locale_independent_timestamps(value: str) -> None:
    with pytest.raises(HevyParseError):
        parse_timestamp(value)


def test_valid_leap_day_and_deterministic_parsing() -> None:
    assert parse_timestamp("29 Feb 2028, 09:00") == datetime(2028, 2, 29, 9)
    first = HevyParser().parse_source(FIXTURE)
    assert first == HevyParser().parse_source(FIXTURE)
    with pytest.raises(TypeError):
        first[0].raw["weight_kg"] = "999"
    assert not hasattr(first[0], "log_id") and not hasattr(HevyParser(), "to_canonical")
