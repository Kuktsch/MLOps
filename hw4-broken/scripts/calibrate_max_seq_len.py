import re
from pathlib import Path

import numpy as np
from transformers import AutoTokenizer

from src.config import load_params
from src.prompt import build_chat_text
from src.tokenize_data import read_jsonl

CANDIDATES = (256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096, 8192)


def main() -> None:
    params = load_params()
    tokenizer = AutoTokenizer.from_pretrained(params["model"]["name"])
    all_lengths = {}
    for split, key in (("train", "train_jsonl"), ("val", "val_jsonl")):
        records = read_jsonl(Path(params["data"][key]))
        if not records:
            raise SystemExit(f"{split} пуст: нет данных для калибровки")
        lengths = np.asarray([
            len(tokenizer(
                build_chat_text(tokenizer, row["messages"], params, add_generation_prompt=False),
                add_special_tokens=False,
            )["input_ids"])
            for row in records
        ])
        all_lengths[split] = lengths
        print(f"{split}: {len(lengths)} примеров, p50={int(np.percentile(lengths, 50))}, "
              f"p90={int(np.percentile(lengths, 90))}, "
              f"p99={int(np.percentile(lengths, 99))}, max={int(lengths.max())}")

    budget = next((c for c in CANDIDATES if all(float(np.mean(a > c)) <= .01
                                               for a in all_lengths.values())), None)
    if budget is None:
        raise SystemExit("Даже 8192 токена обрезает >1%; изучите распределение, не меняйте порог вслепую")
    path = Path("params.yaml")
    text = path.read_text(encoding="utf-8")
    replaced, n = re.subn(r"(?m)^(  max_seq_len:)[ \t]*\d+([ \t]*(?:#.*)?)$",
                          lambda m: f"{m[1]} {budget}{m[2]}", text)
    if n != 1:
        raise SystemExit("Не удалось однозначно найти tokenize.max_seq_len в params.yaml")
    if text != replaced:
        path.write_text(replaced, encoding="utf-8")
    ratios = ", ".join(f"{k}={np.mean(v > budget):.2%}" for k, v in all_lengths.items())
    print(f"tokenize.max_seq_len = {budget}; ожидаемая доля обрезки: {ratios}")


if __name__ == "__main__":
    main()
