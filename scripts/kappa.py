"""Compare seven independently assigned extraction fields without message text.

Only explicitly supplied JSONL files and JSON Pointers are read. This is a
comparison utility, not the F2 extraction schema or the evaluation harness.
Categorical values and exercise-ID shape were checked against F2 PR #69,
commit 7f5e5b27fcff17164af5f52d08248bbe4d2d82a8 (schema v0), using read-only
Git inspection. F2 is not merged here. No extra dependencies.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
import sys
from typing import Literal, NotRequired, Sequence, TypedDict


AGREEMENT_THRESHOLD = 0.70  # Architecture plan section 3.2 / Fi1.

# These match the inspected F2 v0 contract, not a new extraction enum.
# Reuse the shared enums once F2 is integrated; do not import an unmerged branch.
# Canonical membership still needs the pinned D7 vocabulary and F2 validation.
CATEGORICAL_VALUES: dict[str, frozenset[str] | None] = {
    "exercise_id": None,
    "kinematic_observation": frozenset(
        {
            "none",
            "slow_bar_speed",
            "grinding_rep",
            "reduced_range_of_motion",
            "lost_balance",
            "other",
        }
    ),
    "outcome": frozenset({"completed", "failed", "partial"}),
    "triage_level": frozenset({"green", "yellow", "red"}),
}
EXERCISE_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"  # F2 models.EXERCISE_ID_PATTERN.
HEADLINE_FIELDS = frozenset(CATEGORICAL_VALUES)
NUMERIC_FIELDS = frozenset({"load", "reps", "rpe"})
EXTRACTION_FIELDS = (
    "exercise_id", "kinematic_observation", "load", "reps", "outcome", "rpe", "triage_level",
)

ItemKey = tuple[str, str | int]
NumericValue = int | float | Decimal
Category = str | NumericValue | tuple[NumericValue, str] | None
Annotations = dict[ItemKey, dict[str, Category]]
AgreementStatus = Literal["undefined", "meets_threshold", "below_threshold"]


class AnnotationError(ValueError):
    """Invalid input that must not be silently omitted from agreement."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    pointer: str


@dataclass(frozen=True)
class KappaResult:
    n_items: int
    agreements: int
    observed_agreement: float
    expected_agreement: float
    kappa: float | None


class KappaMetrics(TypedDict):
    n_items: int
    agreements: int
    observed_agreement: float
    expected_agreement: float
    kappa: float | None


class FieldReport(KappaMetrics):
    status: AgreementStatus
    red_vs_not_red_disagreements: NotRequired[int]


class NumericFieldReport(KappaMetrics):
    status: Literal["reported_only", "undefined"]


class AgreementReport(TypedDict):
    # The threshold and review decision apply only to the selected headlines.
    threshold: float
    fields: dict[str, FieldReport]
    numeric_fields: dict[str, NumericFieldReport]
    unselected_headline_fields: list[str]
    review_required: bool


def pointer_parts(pointer: str) -> tuple[str, ...]:
    """Decode a JSON Pointer, rejecting invalid escaping."""
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise AnnotationError("JSON Pointers must be empty or start with '/'.")
    parts = pointer[1:].split("/")
    if any(re.search(r"~(?![01])", part) for part in parts):
        raise AnnotationError("Invalid JSON Pointer escape; use ~0 or ~1.")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in parts)


def lookup_pointer(record: object, pointer: str) -> object:
    """Resolve an explicit pointer without guessing an annotation envelope."""
    current = record
    for part in pointer_parts(pointer):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            try:
                index = int(part)
            except ValueError as exc:
                raise AnnotationError("A configured array index cannot be represented.") from exc
            if index >= len(current):
                raise AnnotationError("A configured identifier or label is missing.")
            current = current[index]
        else:
            raise AnnotationError("A configured identifier or label is missing.")
    return current


def parse_field(argument: str) -> FieldSpec:
    name, separator, pointer = argument.partition("=")
    if not separator or name not in EXTRACTION_FIELDS:
        raise argparse.ArgumentTypeError(
            "Use NAME=/pointer; supported names: "
            + ", ".join(EXTRACTION_FIELDS)
        )
    try:
        pointer_parts(pointer)
    except AnnotationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return FieldSpec(name, pointer)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AnnotationError("Duplicate JSON object keys are invalid.")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise AnnotationError("Non-finite constants are invalid JSON.")


def _finite_float(value: str) -> Decimal:
    """Retain a JSON decimal exactly after checking F2 float representability."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise AnnotationError("JSON numbers must be representable as finite values.")
    try:
        return Decimal(value)  # Do not merge distinct JSON values through binary-float rounding.
    except InvalidOperation as exc:
        raise AnnotationError("A JSON number cannot be represented exactly.") from exc


def _nonnegative_number(value: object, field: str) -> NumericValue:
    """Validate reported numbers without coercion, rounding or unit conversion."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise AnnotationError(f"{field} must be a JSON number, not a boolean or string.")
    if isinstance(value, float) and not math.isfinite(value):
        raise AnnotationError(f"{field} must be finite.")
    if isinstance(value, Decimal) and not value.is_finite():
        raise AnnotationError(f"{field} must be finite.")
    if value < 0:
        raise AnnotationError(f"{field} must be nonnegative.")
    return value


def _label_category(name: str, value: object) -> Category:
    """Make a hashable nominal category under Patrick's exact-match convention."""
    if name in NUMERIC_FIELDS:
        if value is None:
            return None  # Explicit null is a category, never a missing record.
        if name == "load":
            if not isinstance(value, dict) or set(value) != {"value", "unit"}:
                raise AnnotationError("load must be null or an object with exactly value and unit.")
            magnitude = _nonnegative_number(value["value"], "load.value")
            unit = value["unit"]
            if not isinstance(unit, str) or unit not in ("kg", "lb"):
                raise AnnotationError("load.unit must be kg or lb.")
            return magnitude, unit
        if name == "reps":
            if type(value) is not int or value < 0:
                raise AnnotationError("reps must be null or a strict nonnegative integer.")
            return value
        rpe = _nonnegative_number(value, "rpe")
        if rpe > 10:
            raise AnnotationError("rpe must be between 0 and 10 inclusive.")
        return rpe
    allowed = CATEGORICAL_VALUES[name]
    if not isinstance(value, str) or not value.strip():
        raise AnnotationError(f"{name} must be a non-empty categorical string.")
    if allowed is not None and value not in allowed:
        raise AnnotationError(f"{name} is outside the F2 specified enum.")
    if name == "exercise_id" and (
        not re.fullmatch(EXERCISE_ID_PATTERN, value)
        or (value.lower() == "unknown" and value != "unknown")
    ):
        raise AnnotationError("exercise_id must match F2's ID pattern or lowercase 'unknown'.")
    return value


def read_annotations(
    path: Path, id_pointer: str, fields: Sequence[FieldSpec]
) -> Annotations:
    """Read selected fields; explicit nulls count, missing keys and IDs fail."""
    pointer_parts(id_pointer)
    if not fields or len({field.name for field in fields}) != len(fields):
        raise AnnotationError("Select at least one field, with no duplicate names.")
    for field in fields:
        if field.name not in EXTRACTION_FIELDS:
            raise AnnotationError("Unsupported extraction field.")
        pointer_parts(field.pointer)

    annotations: Annotations = {}
    # Accept an optional UTF-8 BOM from Windows editors.
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, start=1):
            location = f"{path.name}:{line_number}"
            try:
                record: object = json.loads(
                    line,
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                    parse_float=_finite_float,
                )
            except ValueError as exc:
                # Do not echo input text, labels or identifiers into diagnostics.
                raise AnnotationError(f"{location}: invalid JSONL object.") from exc
            if not isinstance(record, dict):
                raise AnnotationError(f"{location}: each row must be an object.")
            try:
                identifier = lookup_pointer(record, id_pointer)
                if isinstance(identifier, str) and identifier.strip():
                    item_key: ItemKey = ("string", identifier)
                elif type(identifier) is int:
                    item_key = ("integer", identifier)
                else:
                    raise AnnotationError(
                        "Identifier must be a non-empty string or an integer."
                    )
                if item_key in annotations:
                    raise AnnotationError("Duplicate item identifier.")
                labels: dict[str, Category] = {}
                for field in fields:
                    value = lookup_pointer(record, field.pointer)
                    labels[field.name] = _label_category(field.name, value)
                annotations[item_key] = labels
            except AnnotationError as exc:
                raise AnnotationError(f"{location}: {exc}") from exc
    if not annotations:
        raise AnnotationError(f"{path.name}: no labeled items.")
    return annotations


def cohens_kappa(left: Sequence[Category], right: Sequence[Category]) -> KappaResult:
    """Compute unweighted nominal kappa with exact-count degeneracy detection."""
    if not left or len(left) != len(right):
        raise AnnotationError("Kappa requires non-empty, equally sized label lists.")
    n_items = len(left)
    agreements = sum(a == b for a, b in zip(left, right))
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected_count = sum(
        count * right_counts[label] for label, count in left_counts.items()
    )
    denominator = n_items * n_items - expected_count
    # Algebraically (Po - Pe) / (1 - Pe). Integer counts avoid rounding Pe to 1.
    kappa = (
        (agreements * n_items - expected_count) / denominator
        if denominator
        else None
    )
    return KappaResult(
        n_items,
        agreements,
        agreements / n_items,
        expected_count / (n_items * n_items),
        kappa,
    )


def compare_annotations(
    left: Annotations, right: Annotations, fields: Sequence[FieldSpec]
) -> AgreementReport:
    """Compare matching items and flag every red-versus-not-red disagreement."""
    if not left or not right:
        raise AnnotationError("Comparison requires non-empty annotations from both annotators.")
    if not fields or len({field.name for field in fields}) != len(fields):
        raise AnnotationError("Select at least one field, with no duplicate names.")
    for field in fields:
        if field.name not in EXTRACTION_FIELDS:
            raise AnnotationError("Unsupported extraction field.")
        if any(field.name not in labels for labels in (*left.values(), *right.values())):
            raise AnnotationError("A selected extraction label is missing.")
    only_left = left.keys() - right.keys()
    only_right = right.keys() - left.keys()
    if only_left or only_right:
        raise AnnotationError(
            "Mismatched item identifiers: "
            f"{len(only_left)} only in A; {len(only_right)} only in B."
        )
    results: dict[str, FieldReport] = {}
    numeric_results: dict[str, NumericFieldReport] = {}
    review_required = False
    for field in fields:
        labels_left = [labels[field.name] for labels in left.values()]
        labels_right = [right[item_key][field.name] for item_key in left]
        result = cohens_kappa(labels_left, labels_right)
        metrics: KappaMetrics = {
            "n_items": result.n_items,
            "agreements": result.agreements,
            "observed_agreement": result.observed_agreement,
            "expected_agreement": result.expected_agreement,
            "kappa": result.kappa,
        }
        if field.name in NUMERIC_FIELDS:
            numeric_results[field.name] = {
                **metrics, "status": "undefined" if result.kappa is None else "reported_only",
            }
            continue  # Numeric kappa never inherits the headline acceptance threshold.
        status: AgreementStatus
        if result.kappa is None:
            status = "undefined"
        elif result.kappa >= AGREEMENT_THRESHOLD:
            status = "meets_threshold"
        else:
            status = "below_threshold"
        details: FieldReport = {
            **metrics,
            "status": status,
        }
        if field.name == "triage_level":
            red_disagreements = sum(
                (a == "red") != (b == "red")
                for a, b in zip(labels_left, labels_right)
            )
            details["red_vs_not_red_disagreements"] = red_disagreements
            review_required |= red_disagreements > 0
        review_required |= status != "meets_threshold"
        results[field.name] = details
    return {
        "threshold": AGREEMENT_THRESHOLD,
        "fields": results,
        "numeric_fields": numeric_results,
        "unselected_headline_fields": sorted(HEADLINE_FIELDS - results.keys()),
        "review_required": review_required,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Match two independent JSONL label files by identifier and report "
            "nominal unweighted Cohen's kappa for all seven extraction fields. "
            "Numeric fields use exact values, source units and explicit null categories. No message text is needed."
        ),
        epilog=(
            "Exit 0: selected headlines meet 0.70 with no red disagreement, or numeric-only report; "
            "1: headline review needed (below 0.70, undefined, or red disagreement); 2: invalid input. "
            "Numeric kappa has no acceptance threshold. Canonical ID membership needs the pinned vocabulary."
        ),
    )
    parser.add_argument("annotator_a", type=Path)
    parser.add_argument("annotator_b", type=Path)
    parser.add_argument(
        "--id-pointer", required=True, help="JSON Pointer to existing item metadata."
    )
    parser.add_argument(
        "--field",
        dest="fields",
        type=parse_field,
        action="append",
        required=True,
        metavar="NAME=/POINTER",
        help=(
            "Repeat for any of: " + ", ".join(EXTRACTION_FIELDS) + ". "
            "Example: --field triage_level=/labels/triage_level"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON report.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        left = read_annotations(args.annotator_a, args.id_pointer, args.fields)
        right = read_annotations(args.annotator_b, args.id_pointer, args.fields)
        report = compare_annotations(left, right, args.fields)
    except (AnnotationError, OSError, UnicodeError, RecursionError) as exc:
        parser.exit(2, f"error: {exc}\n")
    if args.json:
        print(json.dumps(report, indent=2, allow_nan=False))
    else:
        print(f"Cohen's kappa; headline agreement threshold >= {AGREEMENT_THRESHOLD:.2f}")
        print("Headline fields:")
        for name, details in report["fields"].items():
            value = details["kappa"]
            rendered = f"{value:.6f}" if value is not None else "undefined (Pe = 1)"
            print(
                f"{name}: n={details['n_items']}, "
                f"agreements={details['agreements']}, "
                f"Po={details['observed_agreement']:.6f}, "
                f"Pe={details['expected_agreement']:.6f}, "
                f"kappa={rendered}, {details['status']}"
            )
            if name == "triage_level":
                print(
                    "  red-vs-not-red disagreements requiring adjudication: "
                    f"{details['red_vs_not_red_disagreements']}"
                )
        print("Numeric fields (exact match, null included; no acceptance threshold):")
        for name, details in report["numeric_fields"].items():
            value = details["kappa"]
            rendered = f"{value:.6f}" if value is not None else "undefined (Pe = 1)"
            print(
                f"{name}: n={details['n_items']}, agreements={details['agreements']}, "
                f"Po={details['observed_agreement']:.6f}, Pe={details['expected_agreement']:.6f}, "
                f"kappa={rendered}, {details['status']}"
            )
        if report["review_required"]:
            print("Human review required for selected headline fields.")
        elif report["fields"]:
            print("Selected headline fields meet the threshold.")
        else:
            print("No headline fields selected; numeric report only, no headline acceptance decision.")
        if report["unselected_headline_fields"]:
            print("Unselected headline fields: " + ", ".join(report["unselected_headline_fields"]))
        print(
            "Scope: selected F2 v0 fields; numeric exact-match convention awaits final team confirmation. "
            "A report on a subset does not establish pilot acceptance across all four headline fields."
        )
    return 1 if report["review_required"] else 0


if __name__ == "__main__":
    sys.exit(main())
