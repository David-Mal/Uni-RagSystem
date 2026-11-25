from collections.abc import Callable
import csv
import io
from pathlib import Path

import pytest

from src.ingest.adapters.hevy import HevyParseError, HevyParser
from src.ingest.adapters.strong import StrongParseError, StrongParser


def test_detection_rejects_other_formats(strong_values: dict[str, str], hevy_values: dict[str, str]) -> None:
    assert StrongParser.detect(tuple(strong_values)) and not StrongParser.detect(tuple(hevy_values))
    assert HevyParser.detect(tuple(hevy_values)) and not HevyParser.detect(tuple(strong_values))
    for header in ((), ("date", "weight", "reps"), ("Date", "Date"), (None,), ""):
        assert not StrongParser.detect(header) and not HevyParser.detect(header)
    for parser, values in ((StrongParser, strong_values), (HevyParser, hevy_values)):
        text = io.StringIO()
        csv.writer(text, quoting=csv.QUOTE_ALL).writerow(tuple(values))
        assert parser.detect('\ufeff' + text.getvalue())


@pytest.mark.parametrize("app", ("strong", "hevy"))
@pytest.mark.parametrize("mutation", ("unknown", "missing", "duplicate", "ambiguous_weight", "ambiguous_distance"))
def test_invalid_headers(
    app: str, mutation: str, write_csv: Callable[..., Path],
    strong_values: dict[str, str], hevy_values: dict[str, str],
) -> None:
    values = strong_values if app == "strong" else hevy_values
    parser = StrongParser() if app == "strong" else HevyParser()
    error = StrongParseError if app == "strong" else HevyParseError
    header = list(values)
    if mutation == "unknown":
        header.append("unsupported_column")
    elif mutation == "missing":
        header.pop()
    elif mutation == "duplicate":
        header[-1] = header[0]
    elif mutation == "ambiguous_weight":
        header.append("Weight (kg)" if app == "strong" else "weight_lbs")
    else:
        header.append("distance_miles")
    assert not parser.detect(header)
    path = write_csv(header, [])
    with pytest.raises(error, match="headers"):
        parser.parse_source(path, **({"unit_hint": "kg"} if app == "strong" else {}))


@pytest.mark.parametrize("app", ("strong", "hevy"))
@pytest.mark.parametrize("delta", (-1, 1))
def test_wrong_row_width(
    app: str, delta: int, write_csv: Callable[..., Path],
    strong_values: dict[str, str], hevy_values: dict[str, str],
) -> None:
    values = strong_values if app == "strong" else hevy_values
    record = list(values.values())
    record = record[:-1] if delta < 0 else record + ["extra"]
    path = write_csv(tuple(values), [record])
    parser, error = (StrongParser(), StrongParseError) if app == "strong" else (HevyParser(), HevyParseError)
    with pytest.raises(error, match="data row 1: expected"):
        parser.parse_source(path, **({"unit_hint": "kg"} if app == "strong" else {}))


@pytest.mark.parametrize("app", ("strong", "hevy"))
@pytest.mark.parametrize(("field", "bad"), [("weight", "bad"), ("weight", "NaN"), ("rpe", "inf"),
    ("rpe", " "), ("reps", "1.5"), ("index", "W"), ("distance", "1,25"), ("seconds", "NaN")])
def test_invalid_numbers(
    app: str, field: str, bad: str, write_csv: Callable[..., Path],
    strong_values: dict[str, str], hevy_values: dict[str, str],
) -> None:
    values = dict(strong_values if app == "strong" else hevy_values)
    columns = dict(zip(("weight", "rpe", "reps", "index", "distance", "seconds"),
                       ("Weight", "RPE", "Reps", "Set Order", "Distance", "Seconds") if app == "strong" else
                       ("weight_kg", "rpe", "reps", "set_index", "distance_km", "duration_seconds"), strict=True))
    values[columns[field]] = bad
    parser, error = (StrongParser(), StrongParseError) if app == "strong" else (HevyParser(), HevyParseError)
    with pytest.raises(error, match="data row 1"):
        parser.parse_source(
            write_csv(tuple(values), [tuple(values.values())]), **({"unit_hint": "kg"} if app == "strong" else {}),
        )


@pytest.mark.parametrize("app", ("strong", "hevy"))
def test_header_reordering_and_missing_numbers(
    app: str, write_csv: Callable[..., Path], strong_values: dict[str, str], hevy_values: dict[str, str],
) -> None:
    values = dict(strong_values if app == "strong" else hevy_values)
    for field in (("Weight", "Reps", "RPE") if app == "strong" else ("weight_kg", "reps", "rpe")):
        values[field] = ""
    header = tuple(reversed(values))
    parser = StrongParser() if app == "strong" else HevyParser()
    row = parser.parse_source(
        write_csv(header, [tuple(values[name] for name in header)]), **({"unit_hint": "kg"} if app == "strong" else {}),
    )[0]
    assert row.weight is None and row.reps is None and row.rpe is None
    assert row.distance is None and row.duration_seconds is None and not row.failed


@pytest.mark.parametrize("app", ("strong", "hevy"))
def test_no_undocumented_physiological_bounds(
    app: str, write_csv: Callable[..., Path], strong_values: dict[str, str], hevy_values: dict[str, str],
) -> None:
    values = dict(strong_values if app == "strong" else hevy_values)
    values["Weight" if app == "strong" else "weight_kg"] = "-20"
    values["RPE" if app == "strong" else "rpe"] = "47"
    row = (StrongParser() if app == "strong" else HevyParser()).parse_source(
        write_csv(tuple(values), [tuple(values.values())]), **({"unit_hint": "kg"} if app == "strong" else {}))[0]
    assert row.weight == -20 and row.rpe == 47  # Preserved outliers, not physiology validation.


@pytest.mark.parametrize("app", ("strong", "hevy"))
@pytest.mark.parametrize("content", (b"", b"\xff\xfeinvalid", b'"unterminated'))
def test_invalid_csv_input(app: str, content: bytes, tmp_path: Path) -> None:
    path = tmp_path / "invalid.csv"
    path.write_bytes(content)
    parser, error = (StrongParser(), StrongParseError) if app == "strong" else (HevyParser(), HevyParseError)
    with pytest.raises(error):
        parser.parse_source(path, **({"unit_hint": "kg"} if app == "strong" else {}))


@pytest.mark.parametrize("app", ("strong", "hevy"))
def test_finite_numeric_overflow_and_documented_index_base(
    app: str, write_csv: Callable[..., Path], strong_values: dict[str, str], hevy_values: dict[str, str],
) -> None:
    values = dict(strong_values if app == "strong" else hevy_values)
    parser, error = (StrongParser(), StrongParseError) if app == "strong" else (HevyParser(), HevyParseError)
    options = {"unit_hint": "kg"} if app == "strong" else {}
    weight = "Weight" if app == "strong" else "weight_kg"
    values[weight] = "9" * 400
    with pytest.raises(error, match="finite"):
        parser.parse_source(write_csv(tuple(values), [tuple(values.values())]), **options)
    values[weight] = "0"
    values["Set Order" if app == "strong" else "set_index"] = "0" if app == "strong" else "-1"
    with pytest.raises(error, match="at least"):
        parser.parse_source(write_csv(tuple(values), [tuple(values.values())]), **options)


@pytest.mark.parametrize("app", ("strong", "hevy"))
def test_zero_numeric_values_are_not_missing(
    app: str, write_csv: Callable[..., Path], strong_values: dict[str, str], hevy_values: dict[str, str],
) -> None:
    values = dict(strong_values if app == "strong" else hevy_values)
    numeric_fields = (("Weight", "Reps", "RPE", "Distance", "Seconds") if app == "strong" else
                      ("weight_kg", "reps", "rpe", "distance_km", "duration_seconds"))
    for field in numeric_fields:
        values[field] = "0"
    parser = StrongParser() if app == "strong" else HevyParser()
    row = parser.parse_source(
        write_csv(tuple(values), [tuple(values.values())]), **({"unit_hint": "kg"} if app == "strong" else {}),
    )[0]
    assert row.weight == row.reps == row.rpe == row.distance == row.duration_seconds == 0
    assert row.failed
