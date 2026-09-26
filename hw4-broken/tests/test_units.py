"""Малые регрессионные проверки без сети и без загрузки весов Qwen."""

import unittest

from src.collate import DynamicPaddingCollator
from src.prompt import build_chat_text, prompt_token_len
from src.tokenize_data import encode_example, mask_prompt, truncation_stats


class SmallTokenizer:
    """Простой символьный double для проверки маски, НЕ замена Qwen в пайплайне."""

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False, **kwargs):
        pre = "".join(f"[{x['role']}]{x['content']}[/]" for x in messages[:-1])
        if add_generation_prompt:
            return pre + f"[{messages[-1]['role']}]{messages[-1]['content']}[/][assistant][no_think]"
        last = messages[-1]
        return pre + f"[{last['role']}][no_think]{last['content']}[EOS]"

    def __call__(self, text, *, add_special_tokens=False, return_offsets_mapping=False):
        ids = [ord(char) + 10 for char in text]
        out = {"input_ids": ids}
        if return_offsets_mapping:
            out["offset_mapping"] = [(i, i + 1) for i in range(len(text))]
        return out


class TestHw4Units(unittest.TestCase):
    def setUp(self):
        self.tokenizer = SmallTokenizer()
        self.params = {
            "model": {"enable_thinking": False},
            "tokenize": {"truncated_warn_ratio": 0.05},
        }
        self.record = {
            "id": "example_1",
            "messages": [
                {"role": "system", "content": "Инструкция."},
                {"role": "user", "content": "Вопрос?"},
                {"role": "assistant", "content": "Ответ."},
            ],
        }

    def test_prompt_masks_only_prefix(self):
        labels = mask_prompt([1, 2, 3, 4], 2)
        self.assertEqual(labels, [-100, -100, 3, 4])
        self.assertEqual(mask_prompt([1, 2, 3], 15), [-100] * 3)

    def test_train_inference_prefix_and_answer_boundary(self):
        all_text = build_chat_text(self.tokenizer, self.record["messages"], self.params, False)
        inference = build_chat_text(self.tokenizer, self.record["messages"], self.params, True)
        self.assertTrue(all_text.startswith(inference))
        full = self.tokenizer(all_text, return_offsets_mapping=True)
        boundary, used_fallback = prompt_token_len(
            self.tokenizer, inference, full["input_ids"], full["offset_mapping"]
        )
        self.assertEqual(boundary, len(inference))
        self.assertFalse(used_fallback)
        ex = encode_example(self.tokenizer, self.record, self.params, 500)
        answer_text = "".join(chr(i - 10) for i, label in zip(ex["input_ids"], ex["labels"])
                              if label != -100)
        self.assertEqual(answer_text, "Ответ.[EOS]")

    def test_truncation_keeps_zero_supervision_counted(self):
        cut = encode_example(self.tokenizer, self.record, self.params, 2)
        self.assertTrue(cut["_meta"]["truncated"])
        self.assertEqual(cut["_meta"]["supervised"], 0)
        result = truncation_stats([cut["_meta"]], "tiny", self.params)
        self.assertEqual(result["truncated"], 1)
        self.assertEqual(result["truncated_ratio"], 1.0)
        self.assertTrue(result["truncated_above_threshold"])

    def test_collator_left_padding(self):
        c = DynamicPaddingCollator(0)
        a = c([
            {"input_ids": [9], "labels": [9], "attention_mask": [1]},
            {"input_ids": [7, 8], "labels": [-100, 8], "attention_mask": [1, 1]},
        ])
        self.assertEqual(a["input_ids"].tolist(), [[0, 9], [7, 8]])
        self.assertEqual(a["attention_mask"].tolist(), [[0, 1], [1, 1]])
        self.assertEqual(a["labels"].tolist(), [[-100, 9], [-100, 8]])


if __name__ == "__main__":
    unittest.main()
