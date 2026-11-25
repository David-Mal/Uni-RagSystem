"""Verify the authorized count matrix only, never golden items or partition details."""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import product
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "data/golden/sampling_matrix.yaml"
EXPECTED_CLASSES = {"green": 110, "yellow": 60, "red": 80}
EXPECTED_PER_AUTHOR = {"green": 55, "yellow": 30, "red": 40}
FAMILY_MAPPING = {
    "squat pattern": ["squat"],
    "hip hinge": ["deadlift"],
    "upper-body press": ["bench", "overhead_press"],
    "upper-body pull": ["row"],
    "other or unresolved family": ["accessories"],
}
REQUIRED_TRAPS = {"figurative", "negated", "slang/typo", "boundary", "multi-exercise", "none"}
HARD_NEGATIVE_TRAPS = {"figurative", "negated", "slang/typo", "boundary"}
PHRASING_IDS = {f"pf_gd_{number:02d}" for number in range(1, 9)}


class SamplingMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # JSON is a YAML 1.2 subset; no extra dependency or golden enumeration.
        cls.matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        cls.cells = cls.matrix["cells"]

    def test_exact_full_family_trap_crossing_in_each_class(self) -> None:
        self.assertEqual(len(self.cells), 90)
        expected = set(product(FAMILY_MAPPING, REQUIRED_TRAPS))
        for safety_class in EXPECTED_CLASSES:
            cells = [cell for cell in self.cells if cell["safety_class"] == safety_class]
            with self.subTest(safety_class=safety_class):
                self.assertEqual(len(cells), 30)
                pairs = [(cell["exercise_family"], cell["trap_type"]) for cell in cells]
                self.assertEqual(len(pairs), len(set(pairs)))
                self.assertEqual(set(pairs), expected)

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
            totals = Counter()
            for cell in self.cells:
                totals[cell["safety_class"]] += cell["by_author"][author]
            with self.subTest(author=author):
                self.assertEqual(totals, EXPECTED_PER_AUTHOR)
                self.assertEqual(sum(totals.values()), 125)
                self.assertEqual(
                    self.matrix["targets"]["by_author"][author], {**EXPECTED_PER_AUTHOR, "total": 125},
                )

    def test_base_cells_have_equal_author_counts_and_at_least_two_items(self) -> None:
        for cell in self.cells:
            with self.subTest(group=cell["exercise_family"], trap=cell["trap_type"], level=cell["safety_class"]):
                self.assertIs(type(cell["count"]), int)
                self.assertGreaterEqual(cell["count"], 2)
                self.assertEqual(set(cell["by_author"]), {"Filip", "Patrick"})
                self.assertEqual(sum(cell["by_author"].values()), cell["count"])
                self.assertEqual(cell["by_author"]["Filip"], cell["by_author"]["Patrick"])
                for count in cell["by_author"].values():
                    self.assertIs(type(count), int)
                    self.assertGreaterEqual(count, 1)

    def test_nested_allocations_partition_base_cells_without_double_counting(self) -> None:
        allocated = 0
        for cell in self.cells:
            totals = Counter()
            seen = set()
            for allocation in cell["allocations"]:
                key = (allocation["phrasing_family"], allocation["manifest_family"], allocation["identity_target"])
                self.assertNotIn(key, seen)
                seen.add(key)
                self.assertIs(type(allocation["count"]), int)
                self.assertGreater(allocation["count"], 0)
                self.assertEqual(set(allocation["by_author"]), {"Filip", "Patrick"})
                self.assertEqual(sum(allocation["by_author"].values()), allocation["count"])
                for author, count in allocation["by_author"].items():
                    self.assertIs(type(count), int)
                    self.assertGreaterEqual(count, 0)
                    totals[author] += count
                self.assertIn(allocation["phrasing_family"], PHRASING_IDS)
                self.assertIn(allocation["manifest_family"], FAMILY_MAPPING[cell["exercise_family"]])
                self.assertIn(allocation["identity_target"], {"resolved", "unresolved"})
                allocated += allocation["count"]
            self.assertEqual(totals, cell["by_author"])
            self.assertEqual(sum(part["count"] for part in cell["allocations"]), cell["count"])
        # Child counts partition parents: 250, not 250 + 250.
        self.assertEqual(allocated, 250)

    def test_five_groups_map_to_the_six_public_manifest_families(self) -> None:
        self.assertEqual(self.matrix["exercise_family_mapping"], FAMILY_MAPPING)
        self.assertEqual(set(self.matrix["exercise_families"]), set(FAMILY_MAPPING))
        self.assertEqual(len(self.matrix["exercise_families"]), 5)
        self.assertEqual(
            {family for values in FAMILY_MAPPING.values() for family in values},
            {"squat", "deadlift", "bench", "overhead_press", "row", "accessories"},
        )

    def test_bench_and_overhead_press_exist_for_each_author_and_safety_class(self) -> None:
        for level, author in product(EXPECTED_CLASSES, ("Filip", "Patrick")):
            totals = Counter()
            for cell in self.cells:
                if cell["safety_class"] == level and cell["exercise_family"] == "upper-body press":
                    for allocation in cell["allocations"]:
                        totals[allocation["manifest_family"]] += allocation["by_author"][author]
            with self.subTest(level=level, author=author):
                self.assertEqual(set(totals), {"bench", "overhead_press"})
                self.assertGreater(totals["bench"], 0)
                self.assertGreater(totals["overhead_press"], 0)

    def test_unresolved_identity_is_distinct_from_resolved_accessories(self) -> None:
        for level, author in product(EXPECTED_CLASSES, ("Filip", "Patrick")):
            totals = Counter()
            for cell in self.cells:
                for allocation in cell["allocations"]:
                    if cell["exercise_family"] == "other or unresolved family" and cell["safety_class"] == level:
                        self.assertEqual(allocation["manifest_family"], "accessories")
                        totals[allocation["identity_target"]] += allocation["by_author"][author]
                        self.assertNotIn("exercise_id", allocation)  # No canonical ID or actual label is fabricated.
                    elif cell["exercise_family"] != "other or unresolved family":
                        self.assertEqual(allocation["identity_target"], "resolved")
            with self.subTest(level=level, author=author):
                self.assertEqual(set(totals), {"resolved", "unresolved"})
                self.assertGreater(totals["resolved"], 0)
                self.assertGreater(totals["unresolved"], 0)

    def test_all_eight_opaque_phrasing_ids_are_used(self) -> None:
        self.assertEqual(set(self.matrix["phrasing_families"]), PHRASING_IDS)
        self.assertNotIn("phrasing_styles", self.matrix)
        for level, author in product(EXPECTED_CLASSES, ("Filip", "Patrick")):
            used = {
                part["phrasing_family"] for cell in self.cells if cell["safety_class"] == level
                for part in cell["allocations"] if part["by_author"][author] > 0
            }
            self.assertEqual(used, PHRASING_IDS)

    def test_every_used_group_phrasing_pair_spans_all_three_classes(self) -> None:
        levels_by_pair = defaultdict(set)
        levels_by_manifest_pair = defaultdict(set)
        for cell in self.cells:
            for part in cell["allocations"]:
                levels_by_pair[(cell["exercise_family"], part["phrasing_family"])].add(cell["safety_class"])
                levels_by_manifest_pair[(part["manifest_family"], part["phrasing_family"])].add(cell["safety_class"])
        self.assertEqual(set(levels_by_pair), set(product(FAMILY_MAPPING, PHRASING_IDS)))
        self.assertTrue(all(levels == set(EXPECTED_CLASSES) for levels in levels_by_pair.values()))
        self.assertTrue(all(levels == set(EXPECTED_CLASSES) for levels in levels_by_manifest_pair.values()))

    def test_phrasing_and_trap_are_separate_planning_coordinates(self) -> None:
        traps_by_phrase = defaultdict(set)
        for cell in self.cells:
            self.assertNotIn("phrasing_style", cell)
            for part in cell["allocations"]:
                traps_by_phrase[part["phrasing_family"]].add(cell["trap_type"])
        self.assertEqual(set(traps_by_phrase), PHRASING_IDS)
        self.assertTrue(all(traps == REQUIRED_TRAPS for traps in traps_by_phrase.values()))

    def test_hard_negative_traps_cover_every_green_and_yellow_group(self) -> None:
        self.assertEqual(set(self.matrix["trap_types"]), REQUIRED_TRAPS)
        for cell in self.cells:
            self.assertIsInstance(cell["hard_negative"], bool)
            self.assertEqual(
                cell["hard_negative"],
                cell["safety_class"] in {"green", "yellow"} and cell["trap_type"] in HARD_NEGATIVE_TRAPS,
            )
        for level, family in product(("green", "yellow"), FAMILY_MAPPING):
            traps = {
                cell["trap_type"] for cell in self.cells
                if cell["safety_class"] == level and cell["exercise_family"] == family and cell["hard_negative"]
            }
            self.assertEqual(traps, HARD_NEGATIVE_TRAPS)

    def test_exact_hard_negative_totals_by_class_and_author(self) -> None:
        # 20 baseline hard-negative cells * 2 = 40 green; seven extra pairs add 14 => 54.
        # Yellow: 20 * 2 = 40. Red: none. These 94 items are already inside the 250.
        totals = Counter({"green": 0, "yellow": 0, "red": 0})
        for cell in self.cells:
            if cell["hard_negative"]:
                totals[cell["safety_class"]] += cell["count"]
        self.assertEqual(totals, {"green": 54, "yellow": 40, "red": 0})
        self.assertEqual(self.matrix["hard_negative_targets"]["by_class"], totals)
        self.assertEqual(sum(totals.values()), 94)
        self.assertEqual(self.matrix["hard_negative_targets"]["total"], 94)
        for author in ("Filip", "Patrick"):
            per_class = Counter({"green": 0, "yellow": 0, "red": 0})
            for cell in self.cells:
                if cell["hard_negative"]:
                    per_class[cell["safety_class"]] += cell["by_author"][author]
            self.assertEqual(per_class, {"green": 27, "yellow": 20, "red": 0})
            self.assertEqual(
                self.matrix["hard_negative_targets"]["by_author"][author], {**per_class, "total": 47},
            )
        plain = sum(cell["count"] for cell in self.cells if not cell["hard_negative"])
        self.assertEqual(plain, 156)
        self.assertEqual(plain + sum(totals.values()), 250)


if __name__ == "__main__":
    unittest.main()
