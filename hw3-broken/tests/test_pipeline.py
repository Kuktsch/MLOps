"""Offline structural regression tests using synthetic fixture ONLY, not submission data."""
import json
import tempfile
import unittest
from pathlib import Path

from src.dedup import exact_duplicates, near_duplicates
from src.diversity import measure, violations
from src.schema import Example, SchemaError, iter_examples
from src.split import assign_groups


SYS = "Ответь по предоставленному контексту."


def ex(i, article):
    return Example.model_validate({"id": f"ex_{i}", "topic": article, "messages": [
        {"role": "system", "content": SYS},
        {"role": "user", "content": f"Контекст:\nСтатья номер {i}.\n\nВопрос:\nКакой факт описывает статья {i}?"},
        {"role": "assistant", "content": f"Статья {i} описывает уникальный факт."},
    ]})


class TestPipeline(unittest.TestCase):
    def test_near_duplicate_punctuation(self):
        a = "Какой класс препаратов рекомендован как терапия первой линии пациенту с артериальной гипертензией? 0. первый препарат 1. второй препарат"
        b = "Какой класс препаратов рекомендован как терапия первой линии пациенту с артериальной гипертензией ? 0) первый препарат 1) второй препарат"
        self.assertEqual(exact_duplicates([a, b]), [])
        self.assertEqual(near_duplicates([a, b], 4, 128, 0.85), [1])

    def test_group_split(self):
        items = {f"article_{i}": [ex(i * 3 + k, f"article_{i}") for k in range(3)] for i in range(100)}
        split = assign_groups(items, {"train": .8, "val": .1, "test": .1}, 42)
        groups = {k: {e.topic for e in v} for k, v in split.items()}
        self.assertFalse(groups["train"] & groups["test"])
        self.assertFalse(groups["train"] & groups["val"])
        self.assertFalse(groups["val"] & groups["test"])
        self.assertEqual(sum(map(len, split.values())), 300)

    def test_schema_line_number(self):
        good = ex(1, "one").model_dump()
        bad = ex(2, "two").model_dump()
        bad["messages"][2]["role"] = "user"
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "raw.jsonl"
            file.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(SchemaError, r"raw\.jsonl:2:"):
                list(iter_examples(file))

    def test_diversity_rejects_degenerate(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "degenerate.jsonl"
            with file.open("w", encoding="utf-8") as fh:
                for i in range(1200):
                    fh.write(json.dumps(ex(i, "one article").model_dump(), ensure_ascii=False) + "\n")
            stats = measure(str(file), "topic")
            cfg = {"min_examples": 1000, "min_system_prompts": 3, "min_groups": 50,
                   "max_group_share": 0.1, "min_answer_len_ratio": 1.6,
                   "max_same_length_share": .25, "max_duplicate_answer_share": .30}
            self.assertGreaterEqual(len(violations(stats, cfg)), 2)


if __name__ == "__main__":
    unittest.main()
