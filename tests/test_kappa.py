"""Synthetic categorical fixtures only; no golden or pilot messages are read."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.kappa import (
    AnnotationError,
    CATEGORICAL_VALUES,
    EXERCISE_ID_PATTERN,
    FieldSpec,
    cohens_kappa,
    compare_annotations,
    lookup_pointer,
    pointer_parts,
    read_annotations,
)


ROOT = Path(__file__).resolve().parents[1]
TRIAGE = [FieldSpec("triage_level", "/triage_level")]


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


class AnnotationInputTests(unittest.TestCase):
    def setUp(self) -> None:
        # Keep temporary writes inside this repository, never in data/golden.
        workspace = tempfile.TemporaryDirectory(prefix="fi1-test-", dir=ROOT)
        self.addCleanup(workspace.cleanup)
        self.folder = Path(workspace.name)

    def write_rows(self, name: str, rows: list[dict[str, object]]) -> Path:
        path = self.folder / name
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
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
                "/id",
                "--field",
                "triage_level=/triage_level",
                *extra,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_items_are_matched_by_identifier_not_order(self) -> None:
        rows = [
            {"id": "fixture-a", "triage_level": "green"},
            {"id": "fixture-b", "triage_level": "yellow"},
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
            {"id": "fixture-a", "triage_level": "green", "outcome": "completed"},
            {"id": "fixture-b", "triage_level": "yellow", "outcome": "completed"},
        ]
        a = self.write_rows("a.jsonl", rows)
        b = self.write_rows("b.jsonl", rows)
        result = self.cli(a, b, "--field", "outcome=/outcome", "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        fields = json.loads(result.stdout)["fields"]
        self.assertEqual(fields["triage_level"]["status"], "meets_threshold")
        self.assertEqual(fields["outcome"]["status"], "undefined")
        self.assertIsNone(fields["outcome"]["kappa"])

    def test_all_four_f2_categorical_fields_can_be_selected(self) -> None:
        # The concrete exercise ID is published in plan section 3.3, not invented.
        rows = [
            {
                "id": "fixture-a",
                "exercise_id": "unknown",
                "kinematic_observation": "none",
                "outcome": "failed",
                "triage_level": "green",
            },
            {
                "id": "fixture-b",
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
            "--field", "exercise_id=/exercise_id",
            "--field", "kinematic_observation=/kinematic_observation",
            "--field", "outcome=/outcome",
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
            {"id": i, "triage_level": label} for i, label in enumerate(left)
        ])
        b = self.write_rows("b.jsonl", [
            {"id": i, "triage_level": label} for i, label in enumerate(right)
        ])
        result = self.cli(a, b, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["fields"]["triage_level"]["kappa"], 0.7)

    def test_partial_agreement_requires_revision(self) -> None:
        a = self.write_rows("a.jsonl", [
            {"id": i, "triage_level": label}
            for i, label in enumerate(["green", "green", "yellow", "yellow"])
        ])
        b = self.write_rows("b.jsonl", [
            {"id": i, "triage_level": label}
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
            {"id": i, "triage_level": label} for i, label in enumerate(left)
        ])
        b = self.write_rows("b.jsonl", [
            {"id": i, "triage_level": label} for i, label in enumerate(right)
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
        rows = [{"id": "fixture-a", "triage_level": "green"}]
        a = self.write_rows("a.jsonl", rows)
        b = self.write_rows("b.jsonl", rows)
        result = self.cli(a, b)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("undefined (Pe = 1)", result.stdout)
        self.assertIn("Human review required", result.stdout)

    def test_missing_identifier(self) -> None:
        path = self.write_rows("a.jsonl", [{"triage_level": "green"}])
        with self.assertRaisesRegex(AnnotationError, "missing"):
            read_annotations(path, "/id", TRIAGE)

    def test_mismatched_identifier_sets(self) -> None:
        a = self.write_rows("a.jsonl", [{"id": "fixture-a", "triage_level": "green"}])
        b = self.write_rows("b.jsonl", [{"id": "fixture-b", "triage_level": "green"}])
        result = self.cli(a, b)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Mismatched item identifiers", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_different_item_counts(self) -> None:
        a = self.write_rows("a.jsonl", [
            {"id": "fixture-a", "triage_level": "green"},
            {"id": "fixture-b", "triage_level": "yellow"},
        ])
        b = self.write_rows("b.jsonl", [{"id": "fixture-a", "triage_level": "green"}])
        with self.assertRaisesRegex(AnnotationError, "1 only in A; 0 only in B"):
            compare_annotations(
                read_annotations(a, "/id", TRIAGE),
                read_annotations(b, "/id", TRIAGE),
                TRIAGE,
            )

    def test_duplicate_identifier(self) -> None:
        path = self.write_rows("a.jsonl", [
            {"id": "fixture-a", "triage_level": "green"},
            {"id": "fixture-a", "triage_level": "yellow"},
        ])
        with self.assertRaisesRegex(AnnotationError, "Duplicate item identifier"):
            read_annotations(path, "/id", TRIAGE)

    def test_identifier_types_are_not_coerced(self) -> None:
        a = self.write_rows("a.jsonl", [{"id": 1, "triage_level": "green"}])
        b = self.write_rows("b.jsonl", [{"id": "1", "triage_level": "green"}])
        self.assertEqual(self.cli(a, b).returncode, 2)

    def test_invalid_identifiers(self) -> None:
        for identifier in (None, True, False, "", "  ", 1.5, [], {}):
            with self.subTest(identifier=identifier):
                path = self.write_rows("a.jsonl", [
                    {"id": identifier, "triage_level": "green"}
                ])
                with self.assertRaisesRegex(AnnotationError, "Identifier must"):
                    read_annotations(path, "/id", TRIAGE)

    def test_invalid_jsonl(self) -> None:
        cases = [
            "",
            "\n",
            "{not-json}\n",
            '{"id":"fixture-a","triage_level":"green"} trailing\n',
            "[]\n",
            "null\n",
            '{"id":"fixture-a","id":"fixture-b","triage_level":"green"}\n',
            '{"id":"fixture-a","triage_level":"green","unused":NaN}\n',
            '{"id":"fixture-a","triage_level":"green","unused":Infinity}\n',
            '{"id":"fixture-a","triage_level":"green","unused":1e999}\n',
            '{"id":"fixture-a","triage_level":"green"}\n\n',
        ]
        for content in cases:
            with self.subTest(content=content):
                with self.assertRaises(AnnotationError):
                    read_annotations(self.write_raw(content), "/id", TRIAGE)

    def test_missing_or_invalid_selected_labels(self) -> None:
        for value in (None, "", "  ", "invalid-label", "Green", 0, [], {}):
            with self.subTest(value=value):
                path = self.write_rows("a.jsonl", [
                    {"id": "fixture-a", "triage_level": value}
                ])
                with self.assertRaises(AnnotationError):
                    read_annotations(path, "/id", TRIAGE)
        path = self.write_rows("a.jsonl", [{"id": "fixture-a"}])
        with self.assertRaises(AnnotationError):
            read_annotations(path, "/id", TRIAGE)

    def test_other_f2_enums_are_validated(self) -> None:
        for name in ("outcome", "kinematic_observation", "exercise_id"):
            with self.subTest(field=name):
                path = self.write_rows("a.jsonl", [{"id": "fixture-a", name: None}])
                with self.assertRaises(AnnotationError):
                    read_annotations(path, "/id", [FieldSpec(name, "/" + name)])
        for name in ("outcome", "kinematic_observation"):
            with self.subTest(field=name):
                path = self.write_rows("a.jsonl", [
                    {"id": "fixture-a", name: "invalid-label"}
                ])
                with self.assertRaisesRegex(AnnotationError, "outside the F2"):
                    read_annotations(path, "/id", [FieldSpec(name, "/" + name)])

    def test_exercise_id_pattern_and_lowercase_unknown(self) -> None:
        field = [FieldSpec("exercise_id", "/exercise_id")]
        for value in ("unknown", "Barbell_Bench_Press_-_Medium_Grip"):
            with self.subTest(valid=value):
                path = self.write_rows("a.jsonl", [{"id": "fixture-a", "exercise_id": value}])
                self.assertEqual(read_annotations(path, "/id", field)[("string", "fixture-a")]["exercise_id"], value)
        for value in (
            "UNKNOWN", "Unknown", "unKnown", "bench press", "bench/press", "bench.press", "bénch", "unknown\n",
        ):
            with self.subTest(invalid=value):
                path = self.write_rows("a.jsonl", [{"id": "fixture-a", "exercise_id": value}])
                with self.assertRaisesRegex(AnnotationError, "F2's ID pattern"):
                    read_annotations(path, "/id", field)

    def test_exercise_id_rejection_is_a_private_cli_error(self) -> None:
        path = self.write_rows("a.jsonl", [{
            "id": "fixture-a", "triage_level": "green", "exercise_id": "not/an/id",
        }])
        result = self.cli(path, path, "--field", "exercise_id=/exercise_id")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("not/an/id", result.stderr)
        self.assertNotIn("fixture-a", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_incompatible_categorical_pointer_mapping_is_rejected(self) -> None:
        path = self.write_rows("a.jsonl", [{
            "id": "fixture-a", "triage_level": "green", "outcome": "completed",
        }])
        for field in (FieldSpec("outcome", "/triage_level"), FieldSpec("triage_level", "/outcome")):
            with self.subTest(field=field.name):
                with self.assertRaisesRegex(AnnotationError, "outside the F2"):
                    read_annotations(path, "/id", [field])

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
        for pointer in ("id", "/id~", "/id~2"):
            with self.subTest(pointer=pointer):
                with self.assertRaises(AnnotationError):
                    pointer_parts(pointer)
        for pointer in ("/items/01", "/items/-1", "/items/1", "/items/" + "9" * 5000):
            with self.subTest(pointer_length=len(pointer)):
                with self.assertRaises(AnnotationError):
                    lookup_pointer({"items": ["green"]}, pointer)

    def test_invalid_comparison_selection_is_not_a_pass(self) -> None:
        labels = {("string", "fixture-a"): {"triage_level": "green"}}
        for fields in ([], TRIAGE * 2, [FieldSpec("rpe", "/rpe")], [FieldSpec("outcome", "/outcome")]):
            with self.subTest(fields=fields):
                with self.assertRaises(AnnotationError):
                    compare_annotations(labels, labels, fields)
        with self.assertRaises(AnnotationError):
            compare_annotations({}, {}, TRIAGE)

    def test_utf8_bom_from_windows_editor(self) -> None:
        path = self.write_raw('\ufeff{"id":"fixture-a","triage_level":"green"}\n')
        self.assertEqual(len(read_annotations(path, "/id", TRIAGE)), 1)

    def test_missing_file_and_invalid_encoding_are_cli_errors(self) -> None:
        good = self.write_rows("good.jsonl", [{"id": "fixture-a", "triage_level": "green"}])
        missing = self.folder / "missing.jsonl"
        self.assertEqual(self.cli(good, missing).returncode, 2)
        bad = self.folder / "bad-encoding.jsonl"
        bad.write_bytes(b"\xff")
        result = self.cli(good, bad)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_duplicate_fields_or_unsupported_numeric_scoring_are_errors(self) -> None:
        path = self.write_rows("a.jsonl", [{"id": "fixture-a", "triage_level": "green"}])
        for field in ("triage_level=/triage_level", "rpe=/rpe", "outcome=bad-pointer"):
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


class F2ContractCompatibilityTests(unittest.TestCase):
    """Compare Fi1 mappings to the inspected schema using Git only, never F2 data/code execution."""

    @classmethod
    def setUpClass(cls) -> None:
        # Pin the reviewed contract; never fetch, checkout, merge or import F2.
        revision = "7f5e5b27fcff17164af5f52d08248bbe4d2d82a8"
        try:
            result = subprocess.run(
                ["git", "show", f"{revision}:schemas/extraction_result.json"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
            )
        except FileNotFoundError as exc:
            raise unittest.SkipTest("Git is unavailable for the optional F2 contract check.") from exc
        if result.returncode:
            raise unittest.SkipTest("Pinned F2 contract is not present locally; no network access is attempted.")
        cls.schema = json.loads(result.stdout)

    def test_categorical_mappings_match_the_exported_f2_schema(self) -> None:
        properties = self.schema["properties"]
        expected_names = {name for name, spec in properties.items() if "$ref" in spec} | {"exercise_id"}
        self.assertEqual(set(CATEGORICAL_VALUES), expected_names)
        for name in expected_names - {"exercise_id"}:
            with self.subTest(field=name):
                definition = properties[name]["$ref"].removeprefix("#/$defs/")
                self.assertEqual(CATEGORICAL_VALUES[name], frozenset(self.schema["$defs"][definition]["enum"]))

    def test_exercise_id_shape_matches_f2(self) -> None:
        self.assertEqual(EXERCISE_ID_PATTERN, self.schema["properties"]["exercise_id"]["pattern"])
        # Membership is deliberately not asserted: no pinned D7 vocabulary was supplied.
        self.assertIsNone(CATEGORICAL_VALUES["exercise_id"])


if __name__ == "__main__":
    unittest.main()
