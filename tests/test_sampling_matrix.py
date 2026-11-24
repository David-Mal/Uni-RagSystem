"""Verify Fi1 counts only; never enumerate or open other golden files."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
# This is the only golden path authorized for automated reads in Fi1.
MATRIX_PATH = ROOT / "data/golden/sampling_matrix.yaml"
EXPECTED_CLASSES = {"green": 110, "yellow": 60, "red": 80}
EXPECTED_PER_AUTHOR = {"green": 55, "yellow": 30, "red": 40}
REQUIRED_TRAPS = {
    "figurative", "negated", "slang/typo", "boundary", "multi-exercise", "none"
}


class SamplingMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # JSON syntax is valid YAML 1.2, avoiding an unrelated PyYAML dependency.
        cls.matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        cls.cells = cls.matrix["cells"]

    def test_total_and_class_targets(self) -> None:
        totals = Counter()
        for cell in self.cells:
            totals[cell["safety_class"]] += cell["count"]
        self.assertEqual(totals, EXPECTED_CLASSES)
        self.assertEqual(sum(totals.values()), 250)
        self.assertEqual(self.matrix["targets"]["by_class"], EXPECTED_CLASSES)
        self.assertEqual(self.matrix["targets"]["total"], 250)

    def test_per_author_and_per_class_targets(self) -> None:
        for author in ("Filip", "Patrick"):
            with self.subTest(author=author):
                totals = Counter()
                for cell in self.cells:
                    totals[cell["safety_class"]] += cell["by_author"][author]
                self.assertEqual(totals, EXPECTED_PER_AUTHOR)
                self.assertEqual(sum(totals.values()), 125)
                self.assertEqual(
                    self.matrix["targets"]["by_author"][author],
                    {**EXPECTED_PER_AUTHOR, "total": 125},
                )

    def test_each_joint_cell_has_consistent_positive_counts(self) -> None:
        seen = set()
        for cell in self.cells:
            key = (
                cell["safety_class"], cell["exercise_family"],
                cell["phrasing_style"], cell["trap_type"], cell["hard_negative"],
            )
            with self.subTest(cell=key):
                self.assertNotIn(key, seen)
                seen.add(key)
                self.assertEqual(type(cell["count"]), int)
                self.assertGreater(cell["count"], 0)
                self.assertEqual(set(cell["by_author"]), {"Filip", "Patrick"})
                self.assertEqual(sum(cell["by_author"].values()), cell["count"])
                self.assertEqual(cell["by_author"]["Filip"], cell["by_author"]["Patrick"])
                for count in cell["by_author"].values():
                    self.assertEqual(type(count), int)
                    self.assertGreater(count, 0)

    def test_strata_cover_all_dimensions_within_each_class(self) -> None:
        self.assertEqual(set(self.matrix["trap_types"]), REQUIRED_TRAPS)
        for safety_class in EXPECTED_CLASSES:
            with self.subTest(safety_class=safety_class):
                cells = [cell for cell in self.cells if cell["safety_class"] == safety_class]
                self.assertEqual({cell["trap_type"] for cell in cells}, REQUIRED_TRAPS)
                self.assertEqual(
                    {cell["exercise_family"] for cell in cells},
                    set(self.matrix["exercise_families"]),
                )
                self.assertEqual(
                    {cell["phrasing_style"] for cell in cells},
                    set(self.matrix["phrasing_styles"]),
                )

    def test_hard_negative_strata_are_inside_green_and_yellow(self) -> None:
        required_hard_negative_traps = {"figurative", "negated", "slang/typo", "boundary"}
        for cell in self.cells:
            self.assertIsInstance(cell["hard_negative"], bool)
            if cell["hard_negative"]:
                self.assertIn(cell["safety_class"], {"green", "yellow"})
                self.assertNotEqual(cell["trap_type"], "none")
        for safety_class in ("green", "yellow"):
            cells = [
                cell for cell in self.cells
                if cell["safety_class"] == safety_class and cell["hard_negative"]
            ]
            with self.subTest(safety_class=safety_class):
                self.assertGreater(sum(cell["count"] for cell in cells), 0)
                self.assertTrue(
                    required_hard_negative_traps <= {cell["trap_type"] for cell in cells}
                )
                # The dedicated subset is included in, not added to, class totals.
                self.assertLess(sum(cell["count"] for cell in cells), EXPECTED_CLASSES[safety_class])
                for author in ("Filip", "Patrick"):
                    self.assertGreater(sum(cell["by_author"][author] for cell in cells), 0)

    def test_proposals_remain_explicitly_pending_review(self) -> None:
        self.assertIn("[TO VERIFY]", self.matrix["allocation_status"])
        for name in ("exercise_family", "phrasing_style", "hard_negative"):
            self.assertIn("[TO VERIFY]", self.matrix["taxonomy_review"][name])


if __name__ == "__main__":
    unittest.main()
