"""Synthetic label projections only; no golden messages, labels or pilot items are read."""

from __future__ import annotations

import json
from inspect import cleandoc
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from src.exercises.loader import exercise_ids
from src.schemas.enums import EvidenceLevel, HypothesisLabel, KinematicObservation, Outcome, TriageLevel
from src.schemas.json_schema import extraction_json_schema, model_json_schema
from src.schemas.models import ExtractionResult, Load

from scripts.kappa import (
    AgreementReport,
    AnnotationError,
    CATEGORICAL_VALUES,
    EXERCISE_ID_PATTERN,
    FieldSpec,
    cohens_kappa,
    EXTRACTION_FIELDS,
    HEADLINE_FIELDS,
    compare_annotations,
    lookup_pointer,
    pointer_parts,
    read_annotations,
)


ROOT = Path(__file__).resolve().parents[1]
TRIAGE = [FieldSpec("triage_level", "/labels/triage_level")]
TEST_FIELDS = ("exercise_id", "kinematic_observation", "load", "reps", "outcome", "rpe", "triage_level")


class KappaArithmeticTests(unittest.TestCase):
    def test_perfect_non_degenerate_agreement(self) -> None:
        labels = ["green", "green", "yellow", "yellow"]
        result = cohens_kappa(labels, labels)
        # Po = 4/4 = 1; Pe = (2*2 + 2*2)/16 = 1/2; kappa = 1.
        self.assertEqual(result.n_items, 4)
        self.assertEqual(result.agreements, 4)
        self.assertEqual(result.observed_agreement, 1)
        self.assertEqual(result.expected_agreement, 0.5)
        self.assertEqual(result.kappa, 1)

    def test_partial_agreement(self) -> None:
        result = cohens_kappa(
            ["green", "green", "red", "red"],
            ["green", "red", "red", "red"],
        )
        # Po = 3/4; Pe = (2*1 + 2*3)/16 = 1/2; kappa = 1/2.
        self.assertEqual(result.observed_agreement, 0.75)
        self.assertEqual(result.expected_agreement, 0.5)
        self.assertEqual(result.kappa, 0.5)

    def test_systematic_disagreement(self) -> None:
        result = cohens_kappa(
            ["green", "green", "red", "red"],
            ["red", "red", "green", "green"],
        )
        # Po = 0; Pe = 1/2; kappa = (0 - 1/2)/(1 - 1/2) = -1.
        self.assertEqual(result.kappa, -1)

    def test_chance_agreement(self) -> None:
        result = cohens_kappa(["green", "red"], ["green", "green"])
        # Po = 1/2; Pe = (1*2 + 1*0)/4 = 1/2; kappa = 0.
        self.assertEqual(result.kappa, 0)

    def test_single_identical_class_is_undefined(self) -> None:
        for labels in (["green"], ["red", "red", "red"]):
            with self.subTest(n=len(labels)):
                result = cohens_kappa(labels, labels)
                # Both marginals put all probability in one class: Pe = 1.
                self.assertEqual(result.observed_agreement, 1)
                self.assertEqual(result.expected_agreement, 1)
                self.assertIsNone(result.kappa)

    def test_empty_or_different_lengths_are_invalid(self) -> None:
        for left, right in (([], []), (["green"], []), (["red"], ["red", "red"])):
            with self.subTest(left=left, right=right):
                with self.assertRaises(AnnotationError):
                    cohens_kappa(left, right)


class AnnotationFiles(unittest.TestCase):
    def setUp(self) -> None:
        # Synthetic label projections use the OS temp directory, never golden or repository files.
        workspace = tempfile.TemporaryDirectory(prefix="fi1-test-")
        self.addCleanup(workspace.cleanup)
        self.folder = Path(workspace.name)

    def write_rows(self, name: str, rows: list[dict[str, object]]) -> Path:
        path = self.folder / name
        # Expand isolated test projections into issue #19's item_id / labels envelope.
        records = []
        for row in rows:
            record = dict(row)
            labels = {name: record.pop(name) for name in TEST_FIELDS if name in record}
            if labels:
                if "labels" in record:
                    raise ValueError("A test fixture must not mix flat and nested labels.")
                record["labels"] = labels
            records.append(record)
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
        )
        return path

    def write_raw(self, content: str) -> Path:
        path = self.folder / "invalid.jsonl"
        path.write_text(content, encoding="utf-8")
        return path

    def cli(self, a: Path, b: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "scripts/kappa.py"),
                str(a),
                str(b),
                "--id-pointer",
                "/item_id",
                "--field",
                "triage_level=/labels/triage_level",
                *extra,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

class AnnotationInputTests(AnnotationFiles):
    def test_items_are_matched_by_identifier_not_order(self) -> None:
        rows = [
            {"item_id": "fixture-a", "triage_level": "green"},
            {"item_id": "fixture-b", "triage_level": "yellow"},
        ]
        a = self.write_rows("a.jsonl", rows)
        b = self.write_rows("b.jsonl", list(reversed(rows)))
        result = self.cli(a, b, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["fields"]["triage_level"]["kappa"], 1)
        self.assertFalse(report["review_required"])

    def test_each_selected_field_is_reported_independently(self) -> None:
        rows = [
            {"item_id": "fixture-a", "triage_level": "green", "outcome": "completed"},
            {"item_id": "fixture-b", "triage_level": "yellow", "outcome": "completed"},
        ]
        a = self.write_rows("a.jsonl", rows)
        b = self.write_rows("b.jsonl", rows)
        result = self.cli(a, b, "--field", "outcome=/labels/outcome", "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        fields = json.loads(result.stdout)["fields"]
        self.assertEqual(fields["triage_level"]["status"], "meets_threshold")
        self.assertEqual(fields["outcome"]["status"], "undefined")
        self.assertIsNone(fields["outcome"]["kappa"])

    def test_all_four_f2_categorical_fields_can_be_selected(self) -> None:
        # The concrete exercise ID is published in plan section 3.3, not invented.
        rows = [
            {
                "item_id": "fixture-a",
                "exercise_id": "unknown",
                "kinematic_observation": "none",
                "outcome": "failed",
                "triage_level": "green",
            },
            {
                "item_id": "fixture-b",
                "exercise_id": "Barbell_Bench_Press_-_Medium_Grip",
                "kinematic_observation": "grinding_rep",
                "outcome": "completed",
                "triage_level": "yellow",
            },
        ]
        a = self.write_rows("a.jsonl", rows)
        b = self.write_rows("b.jsonl", list(reversed(rows)))
        result = self.cli(
            a,
            b,
            "--field", "exercise_id=/labels/exercise_id",
            "--field", "kinematic_observation=/labels/kinematic_observation",
            "--field", "outcome=/labels/outcome",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = json.loads(result.stdout)["fields"]
        self.assertEqual(len(fields), 4)
        self.assertTrue(all(field["kappa"] == 1 for field in fields.values()))

    def test_exact_threshold_is_accepted(self) -> None:
        left = ["green"] * 10 + ["yellow"] * 10
        right = ["yellow"] * 3 + ["green"] * 7 + ["yellow"] * 10
        # Po = 17/20; Pe = (10*7 + 10*13)/400 = 1/2; kappa = 0.70.
        a = self.write_rows("a.jsonl", [
            {"item_id": i, "triage_level": label} for i, label in enumerate(left)
        ])
        b = self.write_rows("b.jsonl", [
            {"item_id": i, "triage_level": label} for i, label in enumerate(right)
        ])
        result = self.cli(a, b, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["fields"]["triage_level"]["kappa"], 0.7)

    def test_partial_agreement_requires_revision(self) -> None:
        a = self.write_rows("a.jsonl", [
            {"item_id": i, "triage_level": label}
            for i, label in enumerate(["green", "green", "yellow", "yellow"])
        ])
        b = self.write_rows("b.jsonl", [
            {"item_id": i, "triage_level": label}
            for i, label in enumerate(["green", "yellow", "yellow", "yellow"])
        ])
        result = self.cli(a, b, "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        field = json.loads(result.stdout)["fields"]["triage_level"]
        self.assertEqual(field["kappa"], 0.5)
        self.assertEqual(field["status"], "below_threshold")

    def test_red_disagreement_requires_review_even_above_threshold(self) -> None:
        left = ["green"] * 5 + ["red"] * 5
        right = ["green"] * 6 + ["red"] * 4
        # Po = 9/10; Pe = (5*6 + 5*4)/100 = 1/2; kappa = 0.8.
        a = self.write_rows("a.jsonl", [
            {"item_id": i, "triage_level": label} for i, label in enumerate(left)
        ])
        b = self.write_rows("b.jsonl", [
            {"item_id": i, "triage_level": label} for i, label in enumerate(right)
        ])
        result = self.cli(a, b, "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        field = report["fields"]["triage_level"]
        self.assertEqual(field["kappa"], 0.8)
        self.assertEqual(field["status"], "meets_threshold")
        self.assertEqual(field["red_vs_not_red_disagreements"], 1)
        self.assertTrue(report["review_required"])

    def test_undefined_kappa_is_not_a_pass(self) -> None:
        rows = [{"item_id": "fixture-a", "triage_level": "green"}]
        a = self.write_rows("a.jsonl", rows)
        b = self.write_rows("b.jsonl", rows)
        result = self.cli(a, b)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("undefined (Pe = 1)", result.stdout)
        self.assertIn("Human review required", result.stdout)

    def test_missing_identifier(self) -> None:
        path = self.write_rows("a.jsonl", [{"triage_level": "green"}])
        with self.assertRaisesRegex(AnnotationError, "missing"):
            read_annotations(path, "/item_id", TRIAGE)

    def test_mismatched_identifier_sets(self) -> None:
        a = self.write_rows("a.jsonl", [{"item_id": "fixture-a", "triage_level": "green"}])
        b = self.write_rows("b.jsonl", [{"item_id": "fixture-b", "triage_level": "green"}])
        result = self.cli(a, b)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Mismatched item identifiers", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_different_item_counts(self) -> None:
        a = self.write_rows("a.jsonl", [
            {"item_id": "fixture-a", "triage_level": "green"},
            {"item_id": "fixture-b", "triage_level": "yellow"},
        ])
        b = self.write_rows("b.jsonl", [{"item_id": "fixture-a", "triage_level": "green"}])
        with self.assertRaisesRegex(AnnotationError, "1 only in A; 0 only in B"):
            compare_annotations(
                read_annotations(a, "/item_id", TRIAGE),
                read_annotations(b, "/item_id", TRIAGE),
                TRIAGE,
            )

    def test_duplicate_identifier(self) -> None:
        path = self.write_rows("a.jsonl", [
            {"item_id": "fixture-a", "triage_level": "green"},
            {"item_id": "fixture-a", "triage_level": "yellow"},
        ])
        with self.assertRaisesRegex(AnnotationError, "Duplicate item identifier"):
            read_annotations(path, "/item_id", TRIAGE)

    def test_identifier_types_are_not_coerced(self) -> None:
        a = self.write_rows("a.jsonl", [{"item_id": 1, "triage_level": "green"}])
        b = self.write_rows("b.jsonl", [{"item_id": "1", "triage_level": "green"}])
        self.assertEqual(self.cli(a, b).returncode, 2)

    def test_invalid_identifiers(self) -> None:
        for identifier in (None, True, False, "", "  ", 1.5, [], {}):
            with self.subTest(identifier=identifier):
                path = self.write_rows("a.jsonl", [
                    {"item_id": identifier, "triage_level": "green"}
                ])
                with self.assertRaisesRegex(AnnotationError, "Identifier must"):
                    read_annotations(path, "/item_id", TRIAGE)

    def test_invalid_jsonl(self) -> None:
        cases = [
            "",
            "\n",
            "{not-json}\n",
            '{"item_id":"fixture-a","labels":{"triage_level":"green"}} trailing\n',
            "[]\n",
            "null\n",
            '{"item_id":"fixture-a","item_id":"fixture-b","triage_level":"green"}\n',
            '{"item_id":"fixture-a","labels":{"triage_level":"green"},"unused":NaN}\n',
            '{"item_id":"fixture-a","labels":{"triage_level":"green"},"unused":Infinity}\n',
            '{"item_id":"fixture-a","labels":{"triage_level":"green"},"unused":1e999}\n',
            '{"item_id":"fixture-a","labels":{"triage_level":"green"},"unused":1e-999999999999999999999}\n',
            '{"item_id":"fixture-a","labels":{"triage_level":"green"}}\n\n',
        ]
        for content in cases:
            with self.subTest(content=content):
                with self.assertRaises(AnnotationError):
                    read_annotations(self.write_raw(content), "/item_id", TRIAGE)

    def test_missing_or_invalid_selected_labels(self) -> None:
        for value in (None, "", "  ", "invalid-label", "Green", 0, [], {}):
            with self.subTest(value=value):
                path = self.write_rows("a.jsonl", [
                    {"item_id": "fixture-a", "triage_level": value}
                ])
                with self.assertRaises(AnnotationError):
                    read_annotations(path, "/item_id", TRIAGE)
        path = self.write_rows("a.jsonl", [{"item_id": "fixture-a"}])
        with self.assertRaises(AnnotationError):
            read_annotations(path, "/item_id", TRIAGE)

    def test_other_f2_enums_are_validated(self) -> None:
        for name in ("outcome", "kinematic_observation", "exercise_id"):
            with self.subTest(field=name):
                path = self.write_rows("a.jsonl", [{"item_id": "fixture-a", name: None}])
                with self.assertRaises(AnnotationError):
                    read_annotations(path, "/item_id", [FieldSpec(name, "/labels/" + name)])
        for name in ("outcome", "kinematic_observation"):
            with self.subTest(field=name):
                path = self.write_rows("a.jsonl", [
                    {"item_id": "fixture-a", name: "invalid-label"}
                ])
                with self.assertRaisesRegex(AnnotationError, "outside the F2"):
                    read_annotations(path, "/item_id", [FieldSpec(name, "/labels/" + name)])

    def test_exercise_id_pattern_and_lowercase_unknown(self) -> None:
        field = [FieldSpec("exercise_id", "/labels/exercise_id")]
        for value in ("unknown", "Barbell_Bench_Press_-_Medium_Grip"):
            with self.subTest(valid=value):
                path = self.write_rows("a.jsonl", [{"item_id": "fixture-a", "exercise_id": value}])
                loaded = read_annotations(path, "/item_id", field)
                self.assertEqual(loaded[("string", "fixture-a")]["exercise_id"], value)
        for value in (
            "UNKNOWN", "Unknown", "unKnown", "bench press", "bench/press", "bench.press", "bénch", "unknown\n",
        ):
            with self.subTest(invalid=value):
                path = self.write_rows("a.jsonl", [{"item_id": "fixture-a", "exercise_id": value}])
                with self.assertRaisesRegex(AnnotationError, "F2's ID pattern"):
                    read_annotations(path, "/item_id", field)

    def test_exercise_id_rejection_is_a_private_cli_error(self) -> None:
        path = self.write_rows("a.jsonl", [{
            "item_id": "fixture-a", "triage_level": "green", "exercise_id": "not/an/id",
        }])
        result = self.cli(path, path, "--field", "exercise_id=/labels/exercise_id")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("not/an/id", result.stderr)
        self.assertNotIn("fixture-a", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_incompatible_categorical_pointer_mapping_is_rejected(self) -> None:
        path = self.write_rows("a.jsonl", [{
            "item_id": "fixture-a", "triage_level": "green", "outcome": "completed",
        }])
        for field in (FieldSpec("outcome", "/labels/triage_level"), FieldSpec("triage_level", "/labels/outcome")):
            with self.subTest(field=field.name):
                with self.assertRaisesRegex(AnnotationError, "outside the F2"):
                    read_annotations(path, "/item_id", [field])

    def test_nested_metadata_and_labels_need_no_new_export_format(self) -> None:
        path = self.write_rows("a.jsonl", [{
            "metadata": {"item/id~key": "fixture-a"},
            "labels": {"triage_level": "yellow"},
        }])
        loaded = read_annotations(
            path,
            "/metadata/item~1id~0key",
            [FieldSpec("triage_level", "/labels/triage_level")],
        )
        self.assertEqual(loaded[("string", "fixture-a")]["triage_level"], "yellow")
        self.assertEqual(lookup_pointer({"items": [{"value": "green"}]}, "/items/0/value"), "green")

    def test_invalid_pointers(self) -> None:
        for pointer in ("item_id", "/id~", "/id~2"):
            with self.subTest(pointer=pointer):
                with self.assertRaises(AnnotationError):
                    pointer_parts(pointer)
        for pointer in ("/items/01", "/items/-1", "/items/1", "/items/" + "9" * 5000):
            with self.subTest(pointer_length=len(pointer)):
                with self.assertRaises(AnnotationError):
                    lookup_pointer({"items": ["green"]}, pointer)

    def test_invalid_comparison_selection_is_not_a_pass(self) -> None:
        labels = {("string", "fixture-a"): {"triage_level": "green"}}
        for fields in ([], TRIAGE * 2, [FieldSpec("rpe", "/labels/rpe")], [FieldSpec("outcome", "/labels/outcome")]):
            with self.subTest(fields=fields):
                with self.assertRaises(AnnotationError):
                    compare_annotations(labels, labels, fields)
        with self.assertRaises(AnnotationError):
            compare_annotations({}, {}, TRIAGE)

    def test_utf8_bom_from_windows_editor(self) -> None:
        path = self.write_raw('\ufeff{"item_id":"fixture-a","labels":{"triage_level":"green"}}\n')
        self.assertEqual(len(read_annotations(path, "/item_id", TRIAGE)), 1)

    def test_missing_file_and_invalid_encoding_are_cli_errors(self) -> None:
        good = self.write_rows("good.jsonl", [{"item_id": "fixture-a", "triage_level": "green"}])
        missing = self.folder / "missing.jsonl"
        self.assertEqual(self.cli(good, missing).returncode, 2)
        bad = self.folder / "bad-encoding.jsonl"
        bad.write_bytes(b"\xff")
        result = self.cli(good, bad)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_duplicate_fields_or_unsupported_mappings_are_errors(self) -> None:
        path = self.write_rows("a.jsonl", [{"item_id": "fixture-a", "triage_level": "green"}])
        for field in ("triage_level=/labels/triage_level", "unsupported=/labels/rpe", "outcome=bad-pointer"):
            with self.subTest(field=field):
                result = self.cli(path, path, "--field", field)
                self.assertEqual(result.returncode, 2)

    def test_cli_requires_explicit_identifier_and_fields(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/kappa.py"), "a.jsonl", "b.jsonl"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--id-pointer", result.stderr)
        self.assertIn("--field", result.stderr)


class NumericAgreementTests(AnnotationFiles):
    def report_for(self, name: str, left: list[object], right: list[object]) -> AgreementReport:
        a = self.write_rows("a.jsonl", [{"item_id": i, name: value} for i, value in enumerate(left)])
        b = self.write_rows("b.jsonl", [{"item_id": i, name: value} for i, value in enumerate(right)])
        fields = [FieldSpec(name, "/labels/" + name)]
        return compare_annotations(
            read_annotations(a, "/item_id", fields), read_annotations(b, "/item_id", fields), fields,
        )

    def cli_fields(
        self, a: Path, b: Path, names: tuple[str, ...], *, json_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-B", str(ROOT / "scripts/kappa.py"), str(a), str(b),
                   "--id-pointer", "/item_id"]
        for name in names:
            command.extend(("--field", name + "=/labels/" + name))
        if json_output:
            command.append("--json")
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    def full_rows(self) -> list[dict[str, object]]:
        # Synthetic label projections, without any source message or assigned golden identifier.
        return [
            {"item_id": "fixture-a", "labels": {
                "exercise_id": "unknown", "kinematic_observation": "none", "load": None,
                "reps": None, "outcome": "completed", "rpe": None, "triage_level": "green",
            }},
            {"item_id": "fixture-b", "labels": {
                "exercise_id": "Barbell_Bench_Press_-_Medium_Grip", "kinematic_observation": "grinding_rep",
                "load": {"value": 80, "unit": "kg"}, "reps": 5, "outcome": "partial", "rpe": 8,
                "triage_level": "yellow",
            }},
        ]

    def test_all_seven_fields_align_with_issue19_envelope(self) -> None:
        rows = self.full_rows()
        a = self.write_rows("a.jsonl", rows)
        b = self.write_rows("b.jsonl", list(reversed(rows)))
        result = self.cli_fields(a, b, TEST_FIELDS)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(set(report["fields"]), set(HEADLINE_FIELDS))
        self.assertEqual(set(report["numeric_fields"]), {"load", "reps", "rpe"})
        self.assertEqual(report["unselected_headline_fields"], [])
        self.assertFalse(report["review_required"])
        for details in (*report["fields"].values(), *report["numeric_fields"].values()):
            # Two distinct categories, aligned by ID despite reversed file order: Po=1, Pe=1/2, kappa=1.
            self.assertEqual(details["n_items"], 2)
            self.assertEqual(details["kappa"], 1)

    def test_null_is_a_category_and_never_drops_items(self) -> None:
        for name, value in (("load", {"value": 80, "unit": "kg"}), ("reps", 5), ("rpe", 8)):
            with self.subTest(field=name):
                report = self.report_for(name, [None, None, value, value], [None, value, value, value])
                details = report["numeric_fields"][name]
                # Null matches null once; the value matches twice: Po=3/4, Pe=1/2, kappa=1/2.
                self.assertEqual(details["n_items"], 4)
                self.assertEqual(details["agreements"], 3)
                self.assertEqual(details["kappa"], 0.5)
                self.assertEqual(details["status"], "reported_only")
                self.assertFalse(report["review_required"])

    def test_two_null_categories_can_agree_with_non_degenerate_kappa(self) -> None:
        for name, value in (("load", {"value": 0, "unit": "lb"}), ("reps", 0), ("rpe", 0)):
            with self.subTest(field=name):
                details = self.report_for(name, [None, value], [None, value])["numeric_fields"][name]
                self.assertEqual(details["agreements"], 2)
                self.assertEqual(details["kappa"], 1)

    def test_all_null_numeric_agreement_is_explicitly_undefined(self) -> None:
        for name in ("load", "reps", "rpe"):
            with self.subTest(field=name):
                report = self.report_for(name, [None, None], [None, None])
                details = report["numeric_fields"][name]
                self.assertEqual(details["observed_agreement"], 1)
                self.assertEqual(details["expected_agreement"], 1)
                self.assertIsNone(details["kappa"])
                self.assertEqual(details["status"], "undefined")
                self.assertFalse(report["review_required"])

    def test_equal_integer_and_float_load_and_rpe_values_agree(self) -> None:
        cases = [
            ("load", [{"value": 80, "unit": "kg"}, {"value": 90, "unit": "kg"}],
             [{"value": 80.0, "unit": "kg"}, {"value": 90.0, "unit": "kg"}]),
            ("rpe", [7, 8], [7.0, 8.0]),
        ]
        for name, left, right in cases:
            with self.subTest(field=name):
                self.assertEqual(self.report_for(name, left, right)["numeric_fields"][name]["kappa"], 1)

    def test_no_rounding_or_tolerance_is_applied(self) -> None:
        cases = [
            ("load", [{"value": 80, "unit": "kg"}, {"value": 90, "unit": "kg"}],
             [{"value": 80.0001, "unit": "kg"}, {"value": 90, "unit": "kg"}]),
            ("rpe", [7, 8], [7.0001, 8]),
        ]
        for name, left, right in cases:
            with self.subTest(field=name):
                details = self.report_for(name, left, right)["numeric_fields"][name]
                # Only the second item agrees: Po=1/2; only its category overlaps, Pe=1/4; kappa=1/3.
                self.assertEqual(details["agreements"], 1)
                self.assertAlmostEqual(details["kappa"], 1 / 3)

    def test_load_units_remain_distinct_even_at_zero(self) -> None:
        details = self.report_for(
            "load", [{"value": 0, "unit": "kg"}, None], [{"value": 0.0, "unit": "lb"}, None],
        )["numeric_fields"]["load"]
        # Zero magnitude does not erase its unit. Only null agrees: Po=1/2, Pe=1/4, kappa=1/3.
        self.assertEqual(details["agreements"], 1)
        self.assertAlmostEqual(details["kappa"], 1 / 3)

    def test_json_decimal_precision_is_not_rounded_into_agreement(self) -> None:
        # The first reported values differ, even though both become 7.0 in binary-float parsing.
        a = self.folder / "a.jsonl"
        b = self.folder / "b.jsonl"
        a.write_text(
            '{"item_id":0,"labels":{"rpe":7.0000000000000001}}\n'
            '{"item_id":1,"labels":{"rpe":8}}\n', encoding="utf-8",
        )
        b.write_text(
            '{"item_id":0,"labels":{"rpe":7}}\n'
            '{"item_id":1,"labels":{"rpe":8.0}}\n', encoding="utf-8",
        )
        result = self.cli_fields(a, b, ("rpe",))
        self.assertEqual(result.returncode, 0, result.stderr)
        details = json.loads(result.stdout)["numeric_fields"]["rpe"]
        # Only item 1 agrees: Po=1/2, Pe=1/4 => kappa=1/3.
        self.assertEqual(details["agreements"], 1)
        self.assertAlmostEqual(details["kappa"], 1 / 3)

    def test_repetition_counts_use_nominal_not_distance_weighted_kappa(self) -> None:
        details = self.report_for("reps", [1, 100], [100, 1])["numeric_fields"]["reps"]
        # Po=0; balanced marginals give Pe=1/2. Nominal kappa=-1, regardless of numeric distances.
        self.assertEqual(details["kappa"], -1)

    def test_invalid_numeric_values_and_load_objects_are_rejected(self) -> None:
        cases = {
            "load": [
                True, False, 80, "80", [], {}, {"value": 80}, {"unit": "kg"},
                {"value": None, "unit": "kg"}, {"value": True, "unit": "kg"},
                {"value": "80", "unit": "kg"}, {"value": -1, "unit": "kg"},
                {"value": 80, "unit": "lbs"}, {"value": 80, "unit": "KG"},
                {"value": 80, "unit": None}, {"value": 80, "unit": True},
                {"value": 80, "unit": "kg", "extra": 1},
                *({"value": value, "unit": "kg"} for value in (float("nan"), float("inf"), -float("inf"))),
            ],
            "reps": [True, False, -1, 1.0, "1", [], {}, float("nan"), float("inf"), -float("inf")],
            "rpe": [True, False, -0.01, 10.01, "8", [], {}, float("nan"), float("inf"), -float("inf")],
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(field=name, invalid=value):
                    path = self.write_rows("a.jsonl", [{"item_id": "fixture-a", name: value}])
                    with self.assertRaises(AnnotationError):
                        read_annotations(path, "/item_id", [FieldSpec(name, "/labels/" + name)])

    def test_numeric_boundaries_and_strict_reps(self) -> None:
        for name, values in (
            ("load", [{"value": 0, "unit": "kg"}, {"value": 0.0, "unit": "lb"}]),
            ("reps", [0, 1000]), ("rpe", [0, 7.5, 10]),
        ):
            with self.subTest(field=name):
                path = self.write_rows("a.jsonl", [{"item_id": i, name: value} for i, value in enumerate(values)])
                loaded = read_annotations(path, "/item_id", [FieldSpec(name, "/labels/" + name)])
                self.assertEqual(len(loaded), len(values))

    def test_missing_numeric_key_is_not_explicit_null(self) -> None:
        for name in ("load", "reps", "rpe"):
            with self.subTest(field=name):
                fields = [FieldSpec(name, "/labels/" + name)]
                missing = self.write_rows("missing.jsonl", [{"item_id": "fixture-a", "labels": {}}])
                with self.assertRaisesRegex(AnnotationError, "missing"):
                    read_annotations(missing, "/item_id", fields)
                explicit = self.write_rows("null.jsonl", [{"item_id": "fixture-a", name: None}])
                self.assertIsNone(read_annotations(explicit, "/item_id", fields)[("string", "fixture-a")][name])

    def test_null_items_still_detect_duplicates_and_mismatches(self) -> None:
        fields = [FieldSpec("rpe", "/labels/rpe")]
        duplicate = self.write_rows("duplicate.jsonl", [
            {"item_id": "fixture-a", "rpe": None}, {"item_id": "fixture-a", "rpe": None},
        ])
        with self.assertRaisesRegex(AnnotationError, "Duplicate item"):
            read_annotations(duplicate, "/item_id", fields)
        a = self.write_rows("a.jsonl", [{"item_id": "fixture-a", "rpe": None}])
        b = self.write_rows("b.jsonl", [{"item_id": "fixture-b", "rpe": None}])
        with self.assertRaisesRegex(AnnotationError, "Mismatched item"):
            compare_annotations(
                read_annotations(a, "/item_id", fields), read_annotations(b, "/item_id", fields), fields,
            )

    def test_numeric_disagreement_does_not_fail_perfect_headlines(self) -> None:
        left, right = self.full_rows(), self.full_rows()
        for i in range(2):
            for rows, value in ((left, i + 1), (right, 2 - i)):
                labels = rows[i]["labels"]
                assert isinstance(labels, dict)
                labels.update(load={"value": value, "unit": "kg"}, reps=value, rpe=value)
        a, b = self.write_rows("a.jsonl", left), self.write_rows("b.jsonl", right)
        result = self.cli_fields(a, b, TEST_FIELDS)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(all(value["kappa"] == 1 for value in report["fields"].values()))
        # Both numeric categories are swapped: Po=0, Pe=1/2, kappa=-1 for each numeric field.
        for details in report["numeric_fields"].values():
            self.assertEqual(details["kappa"], -1)
            self.assertEqual(details["status"], "reported_only")
            self.assertNotIn("threshold", details)
        self.assertFalse(report["review_required"])

    def test_undefined_numeric_kappa_does_not_fail_valid_headlines(self) -> None:
        rows = self.full_rows()
        for row in rows:
            labels = row["labels"]
            assert isinstance(labels, dict)
            labels.update(load=None, reps=5, rpe=8)
        a, b = self.write_rows("a.jsonl", rows), self.write_rows("b.jsonl", rows)
        result = self.cli_fields(a, b, TEST_FIELDS)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["review_required"])
        self.assertTrue(all(value["kappa"] is None for value in report["numeric_fields"].values()))

    def test_numeric_agreement_cannot_rescue_a_failed_headline(self) -> None:
        left = [{"item_id": i, "triage_level": level, "rpe": 6 + i}
                for i, level in enumerate(("green", "green", "yellow", "yellow"))]
        right = [{"item_id": i, "triage_level": level, "rpe": 6 + i}
                 for i, level in enumerate(("green", "yellow", "yellow", "yellow"))]
        a, b = self.write_rows("a.jsonl", left), self.write_rows("b.jsonl", right)
        result = self.cli_fields(a, b, ("triage_level", "rpe"))
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        # Triage: Po=3/4, Pe=1/2 => kappa=1/2. Numeric RPE is perfectly matched.
        self.assertEqual(report["fields"]["triage_level"]["kappa"], 0.5)
        self.assertEqual(report["numeric_fields"]["rpe"]["kappa"], 1)
        self.assertTrue(report["review_required"])

    def test_numeric_only_text_output_does_not_claim_headline_acceptance(self) -> None:
        a = self.write_rows("a.jsonl", [{"item_id": i, "rpe": value} for i, value in enumerate((7, 8))])
        result = self.cli_fields(a, a, ("rpe",), json_output=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Numeric fields", result.stdout)
        self.assertIn("no acceptance threshold", result.stdout)
        self.assertIn("No headline fields selected", result.stdout)
        self.assertNotIn("meets_threshold", result.stdout)

    def test_invalid_numeric_input_has_exit_two_and_private_diagnostics(self) -> None:
        a = self.write_rows("a.jsonl", [{"item_id": "fixture-a", "reps": "not-a-number"}])
        result = self.cli_fields(a, a, ("reps",))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("not-a-number", result.stderr)
        self.assertNotIn("fixture-a", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class F2ContractCompatibilityTests(unittest.TestCase):
    """Use merged schema/model contracts and public D7 metadata, without message content."""

    @classmethod
    def setUpClass(cls) -> None:
        # Historical inspection at 7f5e5b27 is documented in the guideline only.
        # Missing current contracts must fail; normal tests never depend on an old Git object.
        cls.schema = json.loads((ROOT / "schemas/extraction_result.json").read_text(encoding="utf-8"))
        cls.load_schema = json.loads((ROOT / "schemas/load.json").read_text(encoding="utf-8"))
        cls.known_ids = frozenset(exercise_ids())
        cls.validator = Draft202012Validator(cls.schema)
        Draft202012Validator.check_schema(cls.schema)
        Draft202012Validator.check_schema(cls.load_schema)

    def projection(self, **changes: object) -> dict[str, object]:
        # Synthetic structural projection only: no source message or golden identifier.
        value = {
            "exercise_id": "unknown", "kinematic_observation": "none", "load": None,
            "reps": None, "outcome": "completed", "rpe": None, "triage_level": "green",
        }
        value.update(changes)
        return value

    def test_current_exported_schemas_match_the_merged_models(self) -> None:
        self.assertEqual(self.schema, model_json_schema(ExtractionResult))
        self.assertEqual(self.load_schema, model_json_schema(Load))

    def test_categorical_mappings_match_the_exported_f2_schema(self) -> None:
        properties = self.schema["properties"]
        expected_names = {name for name, spec in properties.items() if "$ref" in spec} | {"exercise_id"}
        self.assertEqual(set(CATEGORICAL_VALUES), expected_names)
        for name in expected_names - {"exercise_id"}:
            with self.subTest(field=name):
                definition = properties[name]["$ref"].removeprefix("#/$defs/")
                self.assertEqual(CATEGORICAL_VALUES[name], frozenset(self.schema["$defs"][definition]["enum"]))

    def test_all_seven_supported_fields_match_f2(self) -> None:
        self.assertEqual(set(EXTRACTION_FIELDS), set(self.schema["required"]))

    def test_exercise_id_shape_matches_f2(self) -> None:
        self.assertEqual(EXERCISE_ID_PATTERN, self.schema["properties"]["exercise_id"]["pattern"])
        self.assertIsNone(CATEGORICAL_VALUES["exercise_id"])

    def test_shared_enum_values_and_numeric_bounds(self) -> None:
        for name, enum in (("outcome", Outcome), ("kinematic_observation", KinematicObservation),
                           ("triage_level", TriageLevel)):
            self.assertEqual(CATEGORICAL_VALUES[name], {item.value for item in enum})
            for item in enum:
                value = self.projection(**{name: item.value})
                self.validator.validate(value)
                self.assertEqual(getattr(ExtractionResult.model_validate(value), name), item)
        for value in (
            self.projection(load={"value": 0, "unit": "kg"}, reps=0, rpe=0),
            self.projection(load={"value": 80.0, "unit": "lb"}, reps=10000, rpe=10),
            self.projection(load={"value": 1e100, "unit": "kg"}, rpe=7.5),
        ):
            # No invented physiological cap: load/reps have no specified upper bound.
            self.validator.validate(value)
            ExtractionResult.model_validate(value)
        self.assertEqual(set(HypothesisLabel), {
            "insufficient_weekly_volume", "fatigue_accumulation", "stagnant_load_progression", "load_spike",
            "inconsistent_frequency", "logging_quality_issue", "confounder_present",
        })
        self.assertEqual(set(EvidenceLevel), {"supported", "weak", "insufficient"})

    def test_all_keys_required_and_exactly_three_nullable(self) -> None:
        nullable = {"load", "reps", "rpe"}
        self.assertEqual(set(self.schema["properties"]), set(TEST_FIELDS))
        for name in TEST_FIELDS:
            with self.subTest(field=name):
                value = self.projection()
                del value[name]
                self.assertTrue(list(self.validator.iter_errors(value)))
                with self.assertRaises(ValidationError):
                    ExtractionResult.model_validate(value)
                value = self.projection(**{name: None})
                if name in nullable:
                    self.validator.validate(value)
                    self.assertIsNone(getattr(ExtractionResult.model_validate(value), name))
                else:
                    self.assertTrue(list(self.validator.iter_errors(value)))
                    with self.assertRaises(ValidationError):
                        ExtractionResult.model_validate(value)

    def test_runtime_strictness_and_invalid_ranges(self) -> None:
        invalid = {
            "load": [True, {"value": True, "unit": "kg"}, {"value": "80", "unit": "kg"},
                     {"value": -1, "unit": "kg"}, {"value": 80, "unit": "lbs"},
                     {"value": float("nan"), "unit": "kg"}, {"value": float("inf"), "unit": "kg"},
                     {"value": 10**400, "unit": "kg"}, {"value": 80, "unit": "kg", "extra": 1}],
            "reps": [True, "5", 5.0, -1],
            "rpe": [True, "8", -0.1, 10.1, float("nan"), float("inf")],
            "outcome": ["unknown", "failure"],
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(field=name, invalid=value):
                    with self.assertRaises(ValidationError):
                        ExtractionResult.model_validate(self.projection(**{name: value}))
        with self.assertRaises(ValidationError):
            ExtractionResult.model_validate({**self.projection(), "item_id": "synthetic-outside-envelope"})

    def test_outcome_definitions_are_disjoint_and_do_not_supply_reps(self) -> None:
        # Semantic definitions are reviewed policy, not cross-field inference from a model.
        definition = cleandoc(Outcome.__doc__)
        self.assertIn("set fell short of the plan", definition)
        self.assertIn("at least one rep was completed", definition)
        self.assertIn("no rep was completed", definition)
        self.assertIn("do not overlap", definition)
        self.assertEqual(self.schema["$defs"]["Outcome"]["description"], definition.strip())
        for outcome in Outcome:
            parsed = ExtractionResult.model_validate(self.projection(outcome=outcome.value))
            self.assertIsNone(parsed.reps)  # Outcome never invents an unstated count.

    def test_d7_vocabulary_is_compatible_with_f2_context_and_decoding_schema(self) -> None:
        self.assertTrue(self.known_ids)
        valid = ("Barbell_Bench_Press_-_Medium_Grip", "Barbell_Full_Squat")
        for item in (*valid, "unknown"):
            with self.subTest(exercise_id=item):
                if item != "unknown":
                    self.assertIn(item, self.known_ids)
                self.assertEqual(ExtractionResult.model_validate(
                    self.projection(exercise_id=item), context={"exercise_ids": self.known_ids},
                ).exercise_id, item)
        for item in ("UNKNOWN", "Unknown", "bench press", "bench_press", "not_in_pinned_vocabulary", "bench/press"):
            with self.subTest(invalid=item), self.assertRaises(ValidationError):
                ExtractionResult.model_validate(self.projection(exercise_id=item),
                                                context={"exercise_ids": self.known_ids})
        # Without context the exported schema/model check shape, not membership.
        self.validator.validate(self.projection(exercise_id="not_in_pinned_vocabulary"))
        self.assertEqual(ExtractionResult.model_validate(
            self.projection(exercise_id="not_in_pinned_vocabulary"),
        ).exercise_id, "not_in_pinned_vocabulary")
        constrained = extraction_json_schema(self.known_ids)
        self.assertEqual(set(constrained["properties"]["exercise_id"]["enum"]), self.known_ids | {"unknown"})


class D7KappaCompatibilityTests(AnnotationFiles):
    def test_canonical_exercise_categories_remain_exact_and_align_by_item_id(self) -> None:
        names = ("Barbell_Bench_Press_-_Medium_Grip", "Barbell_Full_Squat", "unknown")
        rows = [{"item_id": number, "exercise_id": value} for number, value in enumerate(names)]
        field = [FieldSpec("exercise_id", "/labels/exercise_id")]
        a = read_annotations(self.write_rows("a.jsonl", rows), "/item_id", field)
        b = read_annotations(self.write_rows("b.jsonl", list(reversed(rows))), "/item_id", field)
        self.assertEqual(compare_annotations(a, b, field)["fields"]["exercise_id"]["kappa"], 1)
        self.assertEqual([a[("integer", number)]["exercise_id"] for number in range(3)], list(names))

    def test_aliases_and_unlisted_ids_are_rejected_without_guessing(self) -> None:
        for value in ("bench", "bench_press", "not_in_pinned_vocabulary"):
            with self.subTest(exercise_id=value):
                path = self.write_rows("invalid.jsonl", [{"item_id": "synthetic-only", "exercise_id": value}])
                with self.assertRaisesRegex(AnnotationError, "pinned D7 vocabulary"):
                    read_annotations(path, "/item_id", [FieldSpec("exercise_id", "/labels/exercise_id")])

    def test_load_rejects_integers_not_representable_by_the_shared_float_contract(self) -> None:
        path = self.write_rows("invalid.jsonl", [{"item_id": "synthetic-only", "load": {"value": 10**400, "unit": "kg"}}])
        with self.assertRaisesRegex(AnnotationError, "finite F2 number"):
            read_annotations(path, "/item_id", [FieldSpec("load", "/labels/load")])


if __name__ == "__main__":
    unittest.main()
