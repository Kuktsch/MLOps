"""Offline regression tests for real-source-only length-stratified sampler."""
import random
import unittest

from src.sampling import select_balanced
from src.stats import spread


class TestAnswerLengthSampling(unittest.TestCase):
    @staticmethod
    def fixture(n=12000):
        randomizer = random.Random(456)
        rows = []
        for i in range(n):
            length = max(60, min(800, int(randomizer.gauss(350, 60))))
            key = f"{i:08d}"
            rows.append((f"{randomizer.getrandbits(160):040x}", key,
                         {"id": key, "topic": f"wiki_{i}",
                          "messages": [{}, {}, {"content": "x" * length}]}))
        return sorted(rows, key=lambda row: (row[0], row[1]))

    def test_nested_versions_reach_ratio_without_changing_answers(self):
        candidates = self.fixture()
        by_id = {row[2]["id"]: row[2]["messages"][2]["content"] for row in candidates}
        original_random = [len(x[2]["messages"][2]["content"]) for x in candidates[:2600]]
        self.assertLess(spread(original_random)["ratio_p90_p10"], 1.7)
        selected, diag = select_balanced(candidates, {"v1": 2600, "v2": 4200}, 3, 1.7)
        self.assertEqual(len(selected), 4200)
        self.assertEqual(len({r["id"] for r in selected}), 4200)
        self.assertEqual(diag["method"], "answer-length-stratified real-source sampling")
        self.assertTrue(all(r["messages"][2]["content"] == by_id[r["id"]] for r in selected))
        self.assertGreaterEqual(spread([len(r["messages"][2]["content"]) for r in selected[:2600]])["ratio_p90_p10"], 1.7)
        self.assertGreaterEqual(spread([len(r["messages"][2]["content"]) for r in selected])["ratio_p90_p10"], 1.7)
        second, _ = select_balanced(candidates, {"v1": 2600, "v2": 4200}, 3, 1.7)
        self.assertEqual([r["id"] for r in selected], [r["id"] for r in second])

    def test_tiny_fixture_preserves_original_semantics(self):
        candidates = self.fixture(5)
        selected, diag = select_balanced(candidates, {"v1": 2}, 1, 1.7)
        self.assertEqual(len(selected), 2)
        self.assertIn("tiny", diag["method"])

    def test_raises_if_source_lacks_variation(self):
        candidates = self.fixture()
        for item in candidates:
            item[2]["messages"][2]["content"] = "a" * 350
        with self.assertRaisesRegex(ValueError, "нужного разброса"):
            select_balanced(candidates, {"v1": 2600, "v2": 4200}, 3, 1.7)


if __name__ == "__main__":
    unittest.main()
