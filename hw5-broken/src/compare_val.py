import argparse
import json
import re
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM

from src.compare import load_adapter_tokenizer
from src.config import load_params
from src.data import LABEL_PAD_ID, load_split
from src.runtime import resolve_device, resolve_dtype


def extract_example(example: dict, tok) -> dict | None:
    ids = list(example["input_ids"])
    labels = list(example["labels"])
    supervised = [i for i, x in enumerate(labels) if x != LABEL_PAD_ID]
    if not supervised:
        return None

    start = supervised[0]
    prompt_ids = ids[:start]
    answer_ids = [x for x in labels[start:] if x != LABEL_PAD_ID]
    prompt_text = tok.decode(prompt_ids, skip_special_tokens=False)
    answer = tok.decode(answer_ids, skip_special_tokens=True).strip()

    match = re.search(r"<\|im_start\|>user\s*\n?(.*?)<\|im_end\|>", prompt_text, re.S)
    question = match.group(1).strip() if match else tok.decode(prompt_ids, skip_special_tokens=True).strip()
    if not question or not answer:
        return None
    return {"question": question, "reference": answer, "prompt_ids": prompt_ids}


def choose_examples(examples: list[dict], tok, n: int = 5) -> list[dict]:
    candidates = []
    for example in examples:
        item = extract_example(example, tok)
        if item is None:
            continue
        q, a = item["question"], item["reference"]
        if 15 <= len(q) <= 180 and 2 <= len(a) <= 240 and re.search(r"[А-Яа-яЁё]", q):
            candidates.append(item)

    if len(candidates) < n:
        raise SystemExit(f"подходящих validation-примеров только {len(candidates)}")

    if n == 1:
        return [candidates[len(candidates) // 2]]
    positions = [round(i * (len(candidates) - 1) / (n - 1)) for i in range(n)]
    return [candidates[i] for i in positions]


@torch.no_grad()
def generate_from_ids(model, tok, samples: list[dict], max_new_tokens: int, device) -> list[str]:
    answers = []
    for sample in samples:
        input_ids = torch.tensor([sample["prompt_ids"]], dtype=torch.long, device=device)
        attention_mask = torch.ones_like(input_ids)
        out = model.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tok.pad_token_id,
        )
        answers.append(tok.decode(out[0, input_ids.shape[1]:], skip_special_tokens=True).strip())
    return answers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="all_layers")
    ap.add_argument("--count", type=int, default=5)
    args = ap.parse_args()

    params = load_params()
    device = resolve_device(params["model"]["device"])
    dtype = resolve_dtype(params["model"]["dtype"])
    adapter_dir = Path(params["paths"]["models"]) / f"adapter_{args.variant}"
    cfg = json.loads((adapter_dir / "adapter_config.json").read_text(encoding="utf-8"))
    tok = load_adapter_tokenizer(adapter_dir)

    val = load_split(params["data"]["val"])
    samples = choose_examples(val["examples"], tok, args.count)

    base = AutoModelForCausalLM.from_pretrained(cfg["base_model_name_or_path"], dtype=dtype).to(device).eval()
    before = generate_from_ids(base, tok, samples, params["compare"]["max_new_tokens"], device)
    model = PeftModel.from_pretrained(base, adapter_dir).to(device).eval()
    after = generate_from_ids(model, tok, samples, params["compare"]["max_new_tokens"], device)

    rows = []
    for sample, b, a in zip(samples, before, after):
        rows.append({
            "question": sample["question"],
            "reference": sample["reference"],
            "base": b,
            "adapter": a,
        })

    metrics = Path(params["paths"]["metrics"]) / f"compare_val_{args.variant}.json"
    metrics.parent.mkdir(parents=True, exist_ok=True)
    metrics.write_text(json.dumps({"variant": args.variant, "examples": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Сравнение на validation-примерах",
        "",
        f"Адаптер: `{adapter_dir}`. Пять фиксированных примеров из validation split.",
        "",
    ]
    for i, row in enumerate(rows, 1):
        lines += [
            f"## {i}. {row['question']}",
            "",
            "**Эталон:**",
            "",
            f"> {row['reference'].replace(chr(10), ' / ')}",
            "",
            "**База:**",
            "",
            f"> {row['base'].replace(chr(10), ' / ')}",
            "",
            "**Адаптер:**",
            "",
            f"> {row['adapter'].replace(chr(10), ' / ')}",
            "",
        ]

    report = Path("docs/compare_val.md")
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"-> {metrics}, {report}")
    for row in rows:
        print(f"  вопрос:  {row['question'][:80]!r}")
        print(f"  эталон:  {row['reference'][:80]!r}")
        print(f"  база:    {row['base'][:80]!r}")
        print(f"  адаптер: {row['adapter'][:80]!r}")


if __name__ == "__main__":
    main()
