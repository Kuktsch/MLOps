"""Generate a concise datasheet for both recorded DVC dataset versions."""
import json
import subprocess
from pathlib import Path

from src.config import load_params

STAGES = ("collect", "clean", "diversity", "split")


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def read_current(paths):
    return {stage: json.loads(Path(paths[f"metrics_{stage}"]).read_text(encoding="utf-8"))
            for stage in STAGES}


def read_history(paths):
    try:
        prefix = git("rev-parse", "--show-prefix")
        commits = git("log", "--format=%H", "--", paths["metrics_clean"]).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return {}

    versions = {}
    for commit in commits:
        try:
            metrics = {
                stage: json.loads(git("show", f"{commit}:{prefix}{paths[f'metrics_{stage}']}"))
                for stage in STAGES
            }
        except (OSError, subprocess.CalledProcessError, ValueError):
            continue
        names = {item.get("version") for item in metrics.values()}
        if len(names) == 1:
            name = names.pop()
            if name in ("v1", "v2") and name not in versions:
                versions[name] = metrics
        if len(versions) == 2:
            break
    return versions


def fmt(value):
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    return str(value).replace(".", ",")


def get(metrics, stage, *keys):
    if metrics is None:
        return None
    value = metrics[stage]
    for key in keys:
        value = value[key]
    return value


def main():
    params = load_params()
    paths = params["paths"]
    current = read_current(paths)
    current_versions = {item["version"] for item in current.values()}
    if len(current_versions) != 1:
        raise SystemExit("Версии метрик не совпадают")

    versions = read_history(paths)
    versions[current_versions.pop()] = current
    v1, v2 = versions.get("v1"), versions.get("v2")

    def table_row(label, stage, *keys):
        return f"| {label} | {fmt(get(v1, stage, *keys))} | {fmt(get(v2, stage, *keys))} |"

    def split_value(metrics):
        if metrics is None:
            return "—"
        sizes = metrics["split"]["sizes"]
        return " / ".join(fmt(sizes[key]) for key in ("train", "val", "test"))

    def check_value(metrics):
        if metrics is None:
            return "—"
        return "Пройдена" if metrics["diversity"]["passed"] else "Не пройдена"

    table = "\n".join([
        "| Показатель | v1 | v2 |",
        "|---|---:|---:|",
        table_row("Собрано записей", "collect", "rows_written"),
        table_row("Удалено по длине при очистке", "clean", "dropped_length"),
        table_row("Удалено точных дубликатов", "clean", "dropped_exact_dup"),
        table_row("Удалено почти-дубликатов", "clean", "dropped_near_dup"),
        table_row("Строк с замаскированными ПДн", "clean", "pii_rows_masked"),
        table_row("**После очистки**", "clean", "rows_out"),
        table_row("Групп по статьям", "diversity", "groups"),
        table_row("Системных инструкций", "diversity", "system_prompts"),
        table_row("Длина ответа, p10 (символов)", "diversity", "answer_len", "p10"),
        table_row("Разброс длин ответа, p90/p10", "diversity", "answer_len", "ratio_p90_p10"),
        f"| Train / val / test | {split_value(v1)} | {split_value(v2)} |",
        table_row("Почти-дубликатов между train и test", "split", "contamination", "near_dup_pairs"),
        f"| Проверка разнообразия | {check_value(v1)} | {check_value(v2)} |",
    ])

    delta = ""
    if v1 and v2:
        added = v2["clean"]["rows_out"] - v1["clean"]["rows_out"]
        delta = f"**v2 расширяет v1 на {fmt(added)} записи после очистки.** "
    baseline = v2 or v1
    source_rows = baseline["collect"].get("eligible_candidates") if baseline else None
    context = current["collect"].get("context_included", False)
    task_note = (
        "Контекст исходной статьи включён в вопрос."
        if context else
        "Текстов статей в использованном Parquet нет: задача — **ответ на вопрос без предоставленного контекста**."
    )
    limitation = (
        "Ответы не проверялись вручную на фактическую точность."
        if context else
        "Ответы не проверялись вручную на фактическую точность; без текстов статей их нельзя сверить с первоисточником."
    )
    path = params["source"]["filename"]
    repository = params["source"]["repository"]
    count = f" ({fmt(source_rows)} подходящих исходных записей)" if source_rows is not None else ""

    text = f"""# Datasheet — Russian Encyclopedia QA (v1 и v2)

## 1. Назначение и источник

Русскоязычный датасет энциклопедических вопросов и ответов для дообучения языковой модели в формате chat. Источник — [levos06/ru_wiki_qa](https://huggingface.co/datasets/{repository}), файл `{path}`{count}. На карточке набора указана лицензия **MIT**; при распространении переработанных материалов Википедии необходимо отдельно учитывать их условия использования и атрибуцию.

Источник содержит `question`, `answer` и `original_id`. {task_note}

## 2. Как подготовлен датасет

Из готового источника сформированы две собственные выборки с воспроизводимым отбором коротких, средних и длинных ответов. Записи преобразованы в JSONL с полями `id`, `topic`, `messages` (роли `system → user → assistant`); используется пять вариантов системной инструкции. `original_id` сохранён как `topic` для группировки по исходной статье.

Пайплайн `collect → clean → diversity → split` проверяет схему, фильтрует длины, маскирует телефоны, email и даты рождения, удаляет точные и почти одинаковые вопросы (MinHash). Гейт разнообразия останавливает обработку при нарушении порогов из `params.yaml`.

## 3. Результаты двух версий

{table}

{delta}Разделение выполнено примерно в пропорции 80/10/10 по исходным статьям, а не по отдельным строкам; вопросы из одной статьи не распределяются между выборками. Проверка контаминации использует тот же порог похожести, что и очистка.

Версии данных сохранены в DVC, код и метрики — в Git. Разница между v1 и v2 подтверждается командой `dvc metrics diff`.

## 4. Ограничения

- {limitation} Сведения могут устаревать.
- Отбор по длине специально увеличивает разнообразие, поэтому распределение длин не отражает исходный набор в точности.
- Маскирование ПДн и MinHash не гарантируют обнаружения всех персональных данных и семантических парафразов.
- Датасет ограничен русскоязычными энциклопедическими вопросами; его не следует считать универсальным набором для любых диалоговых задач.
"""
    dest = Path(paths["datasheet"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"datasheet: {dest} ({', '.join(v for v in ('v1', 'v2') if v in versions)})")


if __name__ == "__main__":
    main()
