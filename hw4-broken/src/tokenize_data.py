"""Стадия tokenize: JSONL -> токенизированный датасет на диске + метрики + отчёт.

Что здесь происходит с каждым примером: применяется шаблон чата,
текст режется по max_seq_len, собираются input_ids / attention_mask / labels.

Формат на диске: torch.save одного словаря со списком примеров
(input_ids / attention_mask / labels — списки int, тензоры делает коллатор).
Так проще, чем datasets.save_to_disk, и файл целиком годится в `outs`
DVC-стадии:
    deps: data/train.jsonl, data/val.jsonl, src/, params.yaml
    outs: data/tokenized/
"""

import json
from pathlib import Path

import numpy as np
import torch
from transformers import AutoTokenizer

from src.collate import LABEL_PAD_ID
from src.config import load_params
from src.pack import pack_examples, packing_report
from src.prompt import build_chat_text, prompt_token_len

METRICS_PATH = Path("metrics/tokenize.json")
REPORT_PATH = Path("docs/tokenize_report.md")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"Нет {path}.\n"
            "Сюда кладётся ВАШ датасет из ДЗ 3 — выход стадии split, тот же формат "
            "(id, topic, messages). Курсовой срез собирает `make sample`, но parquet "
            "для него есть только у преподавателя."
        )
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def mask_prompt(input_ids: list[int], n_prompt: int) -> list[int]:
    """labels для лосса."""
    if n_prompt < 0:
        raise ValueError(f"отрицательная граница промпта: {n_prompt}")
    # После truncation весь ответ может исчезнуть: маскируем ВСЁ,
    # process_split посчитает такой пример и отбросит.
    prefix = min(n_prompt, len(input_ids))
    return [LABEL_PAD_ID] * prefix + list(input_ids[prefix:])


def encode_example(tokenizer, record: dict, params: dict, max_seq_len: int) -> dict:
    """Один пример -> input_ids / attention_mask / labels + служебная статистика."""
    messages = record["messages"]
    full_text = build_chat_text(tokenizer, messages, params, add_generation_prompt=False)

    prompt_text = build_chat_text(tokenizer, messages, params, add_generation_prompt=True)
    if not full_text.startswith(prompt_text):
        raise ValueError(
            f"{record.get('id')}: train-путь не начинается с inference-промпта; "
            "проверьте chat template и enable_thinking"
        )

    encoded = tokenizer(full_text, add_special_tokens=False, return_offsets_mapping=True)
    input_ids = encoded["input_ids"]
    n_prompt, used_fallback = prompt_token_len(
        tokenizer, prompt_text, input_ids, encoded["offset_mapping"]
    )

    full_len = len(input_ids)
    truncated = full_len > max_seq_len
    if truncated:
        input_ids = input_ids[:max_seq_len]

    labels = mask_prompt(input_ids, n_prompt)
    return {
        "id": record.get("id"),
        "input_ids": input_ids,
        "attention_mask": [1] * len(input_ids),
        "labels": labels,
        "_meta": {
            "id": record.get("id"),
            "full_len": full_len,
            "prompt_len": n_prompt,
            "answer_len": full_len - n_prompt,
            "truncated": truncated,
            "bpe_fallback": used_fallback,
            "supervised": sum(1 for x in labels if x != LABEL_PAD_ID),
        },
    }


def describe(values: list[int]) -> dict:
    """Распределение длин: перцентили важнее среднего — хвост решает max_seq_len."""
    a = np.asarray(values)
    return {
        "count": int(a.size),
        "mean": round(float(a.mean()), 1),
        "p50": int(np.percentile(a, 50)),
        "p90": int(np.percentile(a, 90)),
        "p99": int(np.percentile(a, 99)),
        "max": int(a.max()),
    }


def truncation_stats(metas: list[dict], name: str, params: dict) -> dict:
    """Статистика обрезки по max_seq_len."""
    total = len(metas)
    truncated = sum(bool(m["truncated"]) for m in metas)
    ratio = truncated / total if total else 0.0
    limit = float(params["tokenize"]["truncated_warn_ratio"])
    if ratio > limit:
        print(
            f"  ВНИМАНИЕ: {name}: обрезано {truncated}/{total} ({ratio:.1%}), "
            f"порог {limit:.1%}; пересмотрите tokenize.max_seq_len"
        )
    return {
        "truncated": truncated,
        "truncated_ratio": round(ratio, 6),
        "truncated_above_threshold": ratio > limit,
    }


def process_split(
    tokenizer, name: str, path: Path, params: dict
) -> tuple[list[dict], dict, list[dict]]:
    """Токенизировать сплит и собрать по нему статистику."""
    cfg = params["tokenize"]
    max_seq_len = cfg["max_seq_len"]
    records = read_jsonl(path)
    if not records:
        raise ValueError(f"{name}: {path} не содержит ни одного примера")

    examples: list[dict] = []
    metas: list[dict] = []
    dropped = 0
    for record in records:
        encoded = encode_example(tokenizer, record, params, max_seq_len)
        # Статистика длин считается по ВСЕМ записям, включая выброшенные:
        # иначе доля обрезанных занижается ровно на самые длинные примеры.
        meta = encoded.pop("_meta")
        metas.append(meta)
        # Обрезка съела весь ответ: учить нечему, такой пример только шумит.
        if meta["supervised"] == 0:
            dropped += 1
            continue
        examples.append(encoded)

    stats = {
        "examples_in": len(records),
        "examples_kept": len(examples),
        "dropped_no_supervision": dropped,
        "length_tokens": describe([m["full_len"] for m in metas]),
        "prompt_tokens": describe([m["prompt_len"] for m in metas]),
        "answer_tokens": describe([m["answer_len"] for m in metas]),
        "bpe_boundary_fallback": sum(m["bpe_fallback"] for m in metas),
        "template_prefix_matches": len(metas),
        "total_tokens": sum(len(e["input_ids"]) for e in examples),
        "supervised_tokens": sum(m["supervised"] for m in metas),
        "supervised_share": round(
            sum(m["supervised"] for m in metas) / sum(len(e["input_ids"]) for e in examples), 6
        ) if examples else 0.0,
    }
    print(
        f"  {name}: {len(examples)} примеров, токенов {stats['total_tokens']} "
        f"(в лосс идёт {stats['supervised_tokens']}), p50/p90/max = "
        f"{stats['length_tokens']['p50']}/{stats['length_tokens']['p90']}/"
        f"{stats['length_tokens']['max']}"
    )
    stats.update(truncation_stats(metas, name, params))

    if params["packing"]["enabled"]:
        bins = pack_examples(examples, max_seq_len)
        stats["packing"] = packing_report(examples, bins, max_seq_len, params["packing"]["batch_size"])
    else:
        stats["packing"] = None
        bins = []

    return examples, stats, bins


def estimate_train_time(total_tokens: int, params: dict) -> dict:
    """Прогноз из скорости генерации ДЗ 1 с честной поправкой на обучение."""
    cfg = params["train_estimate"]
    generation_tps = float(cfg["tokens_per_sec"])
    slowdown_min = float(cfg.get("training_slowdown_min", 2.0))
    slowdown_max = float(cfg.get("training_slowdown_max", 3.0))
    if generation_tps <= 0:
        raise ValueError("train_estimate.tokens_per_sec должен быть > 0")
    if not (1.0 <= slowdown_min <= slowdown_max):
        raise ValueError("training_slowdown_min/max должны задавать корректный диапазон >= 1")

    generation_equivalent_seconds = total_tokens * cfg["epochs"] / generation_tps
    training_seconds_min = generation_equivalent_seconds * slowdown_min
    training_seconds_max = generation_equivalent_seconds * slowdown_max
    return {
        "epochs": cfg["epochs"],
        "tokens_per_epoch": total_tokens,
        "generation_tokens_per_sec": generation_tps,
        "generation_equivalent_seconds": round(generation_equivalent_seconds, 1),
        "generation_equivalent_hours": round(generation_equivalent_seconds / 3600, 2),
        "training_slowdown_min": slowdown_min,
        "training_slowdown_max": slowdown_max,
        "training_seconds_min": round(training_seconds_min, 1),
        "training_seconds_max": round(training_seconds_max, 1),
        "training_hours_min": round(training_seconds_min / 3600, 2),
        "training_hours_max": round(training_seconds_max / 3600, 2),
        "note": (
            "Скорость взята из замера ГЕНЕРАЦИИ в ДЗ 1. По условию ДЗ 4 обучение "
            "с forward + backward + optimizer ожидается медленнее примерно в 2–3 раза; "
            "точное время будет измерено в ДЗ 5."
        ),
    }

def mask_line(share: float) -> str:
    """Строка отчёта про долю токенов, попавших в лосс.

    Доля около единицы означает, что промпт не замаскирован: такой отчёт
    обязан сказать об этом прямо, а не молча показать красивое число.
    """
    if share > 0.99:
        return (
            "В лосс идут ПОЧТИ ВСЕ токены последовательности — похоже, промпт "
            "не замаскирован, и модель учится воспроизводить вопрос наравне с ответом."
        )
    return (
        f"Промпт занимает {1 - share:.0%} токенов. Без маски эти позиции тоже "
        "участвовали бы в лоссе, заставляя модель учиться воспроизводить системную "
        "инструкцию и вопрос вместе с ответом."
    )


def truncation_line(metrics: dict, train: dict) -> str:
    """Строка отчёта про обрезку — или честное признание, что её не считали."""
    warn = metrics["truncated_warn_ratio"]
    if "truncated_ratio" not in train:
        return (
            "Доля обрезанных НЕ ПОСЧИТАНА: стадия не знает, сколько ответов "
            f"потеряла на max_seq_len = {metrics['max_seq_len']}."
        )
    ratio = train["truncated_ratio"]
    verdict = "в норме" if ratio <= warn else "ВЫШЕ ПОРОГА"
    return f"Порог предупреждения: {warn:.1%}. Фактически обрезано (train): {ratio:.1%} — {verdict}."


def truncated_cell(s: dict) -> str:
    """Ячейка «обрезано». Если статистики нет — так и пишем, а не молчим."""
    if "truncated_ratio" not in s:
        return "НЕ СЧИТАЛАСЬ"
    return f"{s['truncated']} ({s['truncated_ratio']:.1%})"


def render_report(metrics: dict) -> str:
    """Отчёт по датасету — то, что читают глазами перед запуском обучения."""
    lines = [
        "# Отчёт стадии tokenize",
        "",
        "Сгенерирован `make tokenize`, руками не правится.",
        "",
        f"- модель: `{metrics['model']}`",
        f"- `max_seq_len`: {metrics['max_seq_len']}",
        f"- `enable_thinking`: {str(metrics['enable_thinking']).lower()}",
        f"- `padding_side`: {metrics['padding_side']}",
        "",
        "## Длины в токенах",
        "",
        "| сплит | примеров | p50 | p90 | p99 | max | обрезано | всего токенов | в лосс |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in metrics["splits"].items():
        L = s["length_tokens"]
        lines.append(
            f"| {name} | {s['examples_kept']} | {L['p50']} | {L['p90']} | {L['p99']} | "
            f"{L['max']} | {truncated_cell(s)} | "
            f"{s['total_tokens']} | {s['supervised_tokens']} |"
        )

    train = metrics["splits"]["train"]
    est = metrics["train_time_estimate"]
    share = train["supervised_tokens"] / train["total_tokens"]
    lines += [
        "",
        mask_line(share),
        "",
        "## Обрезка",
        "",
        truncation_line(metrics, train),
        "",
        (
            f"Train: p99={train['length_tokens']['p99']}, max={train['length_tokens']['max']}; "
            f"val: p99={metrics['splits']['val']['length_tokens']['p99']}, "
            f"max={metrics['splits']['val']['length_tokens']['max']}. "
            f"При `max_seq_len={metrics['max_seq_len']}` обрезано "
            f"{train['truncated']} train и {metrics['splits']['val']['truncated']} val примеров. "
            f"Полностью потеряли supervision: {train['dropped_no_supervision']} train и "
            f"{metrics['splits']['val']['dropped_no_supervision']} val."
        ),
        "",
        "## Граница маски и BPE",
        "",
        f"Запасной путь по символьным офсетам сработал на {train['bpe_boundary_fallback']} "
        "примерах train. Основной путь (токены промпта совпадают с началом токенов "
        "полного текста) держится, потому что шаблон Qwen3 заканчивает промпт "
        "переводом строки — BPE не склеивает его с началом ответа. У шаблона, "
        "который обрывается посреди слова, склейка будет, и тогда границу задаёт "
        "первый токен, начинающийся не раньше конца промпта.",
        "",
        "## Прогноз времени обучения",
        "",
        f"Токенов за эпоху: {est['tokens_per_epoch']}, эпох: {est['epochs']}. "
        f"Скорость генерации из ДЗ 1: {est['generation_tokens_per_sec']} ток/с.",
        "",
        (
            f"Если механически разделить объём на скорость генерации, получится "
            f"{est['generation_equivalent_hours']} ч. Это не время обучения. "
            f"С поправкой из задания (обучение медленнее в "
            f"{est['training_slowdown_min']:.0f}–{est['training_slowdown_max']:.0f} раза) "
            f"ориентир составляет {est['training_hours_min']}–{est['training_hours_max']} ч."
        ),
        "",
        est["note"],
        "",
    ]

    pack = train.get("packing")
    if pack:
        lines += [
            "## Packing",
            "",
            f"Последовательностей до packing: {pack['sequences_before']}, "
            f"бинов по {metrics['max_seq_len']} токенов после: {pack['sequences_after']} "
            f"(заполнение {pack['fill_ratio']:.0%}, до {pack['max_examples_per_bin']} "
            "примеров в бине).",
            "",
            f"Шагов оптимизатора при batch_size {pack['batch_size']}: "
            f"{pack['steps_before']} -> {pack['steps_after']} "
            f"(-{pack['steps_saved_ratio']:.0%}).",
            "",
            "Внимание: без блочно-диагональной маски токены соседних примеров "
            "в бине видят друг друга. Рядом с упакованным датасетом сохранены "
            "`seq_lens` — по ним такая маска строится.",
            "",
        ]
    return "\n".join(lines)



def render_defects(metrics: dict) -> str:
    """Разбор исходных дефектов с численным подтверждением текущего запуска.

    Значения берём из фактической токенизации, не переносим числа из лекции.
    """
    train = metrics["splits"]["train"]
    val = metrics["splits"]["val"]
    total = train["total_tokens"]
    supervised = train["supervised_tokens"]
    masked = total - supervised
    share = supervised / total if total else 0.0
    pad = metrics["padding_side"]
    limit = metrics["max_seq_len"]
    warning = metrics["truncated_warn_ratio"]
    return f"""# HW4 — четыре намеренных дефекта

Отчёт сформирован на реальных `data/train.jsonl` и `data/val.jsonl` стадией
`make tokenize`. Те же числа находятся в `metrics/tokenize.json`.

## 1. Промпт ошибочно попадал в лосс

**Было:** `mask_prompt` возвращала копию всех `input_ids`, то есть потери
начислялись за system, user и assistant сразу. Модель получала обучающий сигнал
за повторение инструкции и вопроса, а не только за ответ.

**Исправлено:** перед токенизацией формируем текст инференс-промпта, определяем
границу по токенам (при BPE-склейке — по символьным офсетам), затем записываем
`-100` на всех позициях промпта. В `input_ids` промпт сохраняется. В лосс
попадают только ответ ассистента и его завершающий токен.

**Числа (train):** всего сохранено **{total:,}** токенов; `-100` на **{masked:,}**
позициях; в лосс идут **{supervised:,}** ({share:.1%}). Граница BPE определялась
по запасному пути на **{train['bpe_boundary_fallback']}** примерах.

## 2. Обучение и инференс использовали разные шаблоны

**Было:** train-текст собирался через ручной `TURN.format`, а inference-текст —
штатным методом токенизатора для шаблона чата. Для Qwen3 эти строки не обязаны
были совпадать по префиксу, особенно при `enable_thinking: false`.

**Исправлено:** оба пути используют единый шаблон из `src/prompt.py` с одинаковым
`enable_thinking`. `encode_example` останавливает стадию, если полный train-текст
не начинается с inference-текста.

**Числа:** проверено **{train['template_prefix_matches']}** train и
**{val['template_prefix_matches']}** val диалогов, расхождений префикса — **0**.
Модель из `params.yaml`: `{metrics['model']}`; `enable_thinking` =
`{str(metrics['enable_thinking']).lower()}`.

## 3. Паддинг был справа

**Было:** `DynamicPaddingCollator` имел `padding_side='right'` по умолчанию,
а настройка в `params.yaml` не применялась к токенизатору. При пакетной
генерации последний токен короткого промпта становился PAD.

**Исправлено:** умолчание коллатора — `left`; у токенизатора и в сохранённых
тензорах используется `tokenize.padding_side`; позиции PAD всегда получают
`attention_mask=0`, `labels=-100`. Ширина определяется максимумом в батче.

**Числа:** `padding_side={pad}`, ID метки PAD = **-100**,
маска внимания PAD = **0**; тест проверяет разные длины при `batch_size=2`.

## 4. Обрезка ответа замалчивалась

**Было:** `input_ids` обрезались по `max_seq_len`, а
`truncation_stats` возвращала пустой словарь. В отчёте нельзя было увидеть,
сколько ответов частично или целиком потеряно.

**Исправлено:** длины считаются ДО обрезки, вместе с отбрасываемыми примерами.
В метрики по каждому сплиту записаны `truncated`, `truncated_ratio` и
`dropped_no_supervision`. Лимит контекста настраивается только в `params.yaml`;
`make calibrate` выбирает первый `max_seq_len` из фиксированной сетки размеров,
при котором ожидаемая доля обрезки на каждом сплите не превышает 1%. Порог
приёмки задания 5% при этом не меняется. Если обрезка уничтожила весь ответ,
пример исключается.

**Числа:** `max_seq_len={limit}`, допустимая доля — **{warning:.1%}**.
Train: **{train['truncated']}/{train['examples_in']}** ({train['truncated_ratio']:.2%})
обрезано, целиком без ответа **{train['dropped_no_supervision']}**;
val: **{val['truncated']}/{val['examples_in']}** ({val['truncated_ratio']:.2%})
обрезано, целиком без ответа **{val['dropped_no_supervision']}**.
"""

def main() -> None:
    params = load_params()
    tokenizer = AutoTokenizer.from_pretrained(params["model"]["name"])
    tokenizer.padding_side = params["tokenize"]["padding_side"]
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token is None:
            raise ValueError("у токенизатора нет ни pad_token, ни eos_token")
        tokenizer.pad_token = tokenizer.eos_token

    out_dir = Path(params["data"]["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    splits = {}
    for name, key in (("train", "train_jsonl"), ("val", "val_jsonl")):
        examples, stats, bins = process_split(tokenizer, name, Path(params["data"][key]), params)
        torch.save(
            {
                "examples": examples,
                "model": params["model"]["name"],
                "max_seq_len": params["tokenize"]["max_seq_len"],
                "padding_side": tokenizer.padding_side,
                "pad_token_id": tokenizer.pad_token_id,
            },
            out_dir / f"{name}.pt",
        )
        if bins:
            torch.save({"bins": bins, "max_seq_len": params["tokenize"]["max_seq_len"]},
                       out_dir / f"{name}_packed.pt")
        splits[name] = stats

    metrics = {
        "model": params["model"]["name"],
        "enable_thinking": params["model"].get("enable_thinking"),
        "max_seq_len": params["tokenize"]["max_seq_len"],
        "padding_side": tokenizer.padding_side,
        "truncated_warn_ratio": params["tokenize"]["truncated_warn_ratio"],
        "splits": splits,
        "train_time_estimate": estimate_train_time(splits["train"]["total_tokens"], params),
    }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(metrics) + "\n", encoding="utf-8")
    defects_path = Path("docs/defects.md")
    defects_path.write_text(render_defects(metrics) + "\n", encoding="utf-8")
    print(f"  -> {out_dir}/, {METRICS_PATH}, {REPORT_PATH}, {defects_path}")


if __name__ == "__main__":
    main()
