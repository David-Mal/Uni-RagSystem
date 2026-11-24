"""Compare independently assigned categorical labels without using message text.

Only explicitly supplied JSONL files and JSON Pointers are read. This is a
comparison utility, not the F2 extraction schema or the evaluation harness.
Categorical values below come from David-Mal/Uni-RagSystem issue #8 (F2);
reconcile them with the shared schema when it lands. No extra dependencies.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Literal, NotRequired, Sequence, TypedDict


AGREEMENT_THRESHOLD = 0.70  # Architecture plan section 3.2 / Fi1.

# F2 issue #8 specifies these values. No new extraction enum is introduced.
# [TO VERIFY] Import shared enums once F2 exists in this checkout.
# exercise_id membership needs the pinned D7 vocabulary; only shape is checked.
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

ItemKey = tuple[str, str | int]
Annotations = dict[ItemKey, dict[str, str]]
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


class FieldReport(TypedDict):
    n_items: int
    agreements: int
    observed_agreement: float
    expected_agreement: float
    kappa: float | None
    status: AgreementStatus
    red_vs_not_red_disagreements: NotRequired[int]


class AgreementReport(TypedDict):
    threshold: float
    fields: dict[str, FieldReport]
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
        elif (
            isinstance(current, list)
            and re.fullmatch(r"0|[1-9][0-9]*", part)
            and int(part) < len(current)
        ):
            current = current[int(part)]
        else:
            raise AnnotationError("A configured identifier or label is missing.")
    return current


def parse_field(argument: str) -> FieldSpec:
    name, separator, pointer = argument.partition("=")
    if not separator or name not in CATEGORICAL_VALUES:
        raise argparse.ArgumentTypeError(
            "Use NAME=/pointer; supported names: "
            + ", ".join(CATEGORICAL_VALUES)
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


def read_annotations(
    path: Path, id_pointer: str, fields: Sequence[FieldSpec]
) -> Annotations:
    """Read selected categorical labels; never infer missing labels or IDs."""
    pointer_parts(id_pointer)
    if not fields or len({field.name for field in fields}) != len(fields):
        raise AnnotationError("Select at least one field, with no duplicate names.")
    for field in fields:
        if field.name not in CATEGORICAL_VALUES:
            raise AnnotationError("Unsupported categorical field.")
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
                labels: dict[str, str] = {}
                for field in fields:
                    value = lookup_pointer(record, field.pointer)
                    allowed = CATEGORICAL_VALUES[field.name]
                    if not isinstance(value, str) or not value.strip():
                        raise AnnotationError(
                            f"{field.name} must be a non-empty categorical string."
                        )
                    if allowed is not None and value not in allowed:
                        raise AnnotationError(
                            f"{field.name} is outside the F2 specified enum."
                        )
                    labels[field.name] = value
                annotations[item_key] = labels
            except AnnotationError as exc:
                raise AnnotationError(f"{location}: {exc}") from exc
    if not annotations:
        raise AnnotationError(f"{path.name}: no labeled items.")
    return annotations


def cohens_kappa(left: Sequence[str], right: Sequence[str]) -> KappaResult:
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
    only_left = left.keys() - right.keys()
    only_right = right.keys() - left.keys()
    if only_left or only_right:
        raise AnnotationError(
            "Mismatched item identifiers: "
            f"{len(only_left)} only in A; {len(only_right)} only in B."
        )
    results: dict[str, FieldReport] = {}
    review_required = False
    for field in fields:
        labels_left = [labels[field.name] for labels in left.values()]
        labels_right = [right[item_key][field.name] for item_key in left]
        result = cohens_kappa(labels_left, labels_right)
        status: AgreementStatus
        if result.kappa is None:
            status = "undefined"
        elif result.kappa >= AGREEMENT_THRESHOLD:
            status = "meets_threshold"
        else:
            status = "below_threshold"
        details: FieldReport = {
            "n_items": result.n_items,
            "agreements": result.agreements,
            "observed_agreement": result.observed_agreement,
            "expected_agreement": result.expected_agreement,
            "kappa": result.kappa,
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
        "review_required": review_required,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Match two independent JSONL label files by identifier and report "
            "unweighted categorical Cohen's kappa. No message text is needed."
        ),
        epilog=(
            "Exit 0: threshold met, no red disagreement; 1: review needed "
            "(below 0.70, undefined, or red disagreement); 2: invalid input. "
            "F2/D7 vocabulary and the final headline-field list remain [TO VERIFY]."
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
            "Repeat for each categorical field: exercise_id, "
            "kinematic_observation, outcome, triage_level. "
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
        print(f"Cohen's kappa; agreement threshold >= {AGREEMENT_THRESHOLD:.2f}")
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
        print("Human review required." if report["review_required"] else "Threshold met.")
        print(
            "Scope: selected categorical fields; exercise-ID membership, numeric "
            "agreement and final headline selection remain [TO VERIFY]."
        )
    return 1 if report["review_required"] else 0


if __name__ == "__main__":
    sys.exit(main())
