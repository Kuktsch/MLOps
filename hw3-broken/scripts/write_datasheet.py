"""Generate factual datasheet from measured pipeline metrics; no invented counts."""
import json
from pathlib import Path

from src.config import load_params


def main() -> None:
    p = load_params()
    paths = p["paths"]
    metrics = {}
    for name in ("collect", "clean", "diversity", "split"):
        metrics[name] = json.loads(Path(paths[f"metrics_{name}"]).read_text(encoding="utf-8"))
    c, d, div, s = (metrics[x] for x in ("collect", "clean", "diversity", "split"))
    if len({x["version"] for x in (c, d, div, s)}) != 1:
        raise SystemExit("Версии метрик не совпадают: datasheet нельзя обновлять")
    clean = p["clean"]
    context_description = (
        "Контекст исходной статьи передаётся вместе с вопросом."
        if c["context_included"] else
        "Компактный источник **не содержит контекста**: модель получает только вопрос."
    )
    text = f"""# Datasheet: Russian Encyclopedia QA — {c['version']}

> Generated from actual pipeline metrics. Do not modify the numbers manually.
> Тема для согласования с преподавателем: «Русскоязычные энциклопедические вопросы и ответы».

## Назначение

Instruction fine-tuning для содержательных ответов на русскоязычные
фактологические вопросы. {context_description} Не предназначен
для медицинских, юридических или иных решений с высоким риском. Ответы исходного
набора сгенерированы автоматически и **не прошли ручную фактологическую проверку**.

## Источник и условия использования

- Репозиторий: https://huggingface.co/datasets/{p['source']['repository']}
- Использованный файл: `{p['source']['filename']}`, revision `{p['source']['revision']}`.
- Контрольная сумма SHA256: `{p['source']['sha256']}`.
- На карточке исходного набора указана MIT; исходный материал основан на статьях
  Википедии, для которых необходимо отдельно учитывать CC BY-SA и атрибуцию.
  Исходные `original_id` сохранены в `topic`, для восстановления происхождения;
  это **не** полный список авторов статей. Перед публичным распространением
  проверьте условия атрибуции/совместимости лицензий.
- Не включайте в Git исходный parquet, raw, clean или три split-файла.

## Переработка готового источника

1. Обязательны `question`, `answer`, `original_id`; `text` и `quality_prob`
   используются только если присутствуют. Эмбеддинги и кластерные метки отброшены.
   Реальные столбцы: `{', '.join(c['source_columns'])}`. Контекст есть: **{c['context_included']}**.
2. Отсеиваются пропуски, короткие/длинные вопросы и ответы; контекст по длине
   фильтруется только при наличии. `quality_prob ≥ {p['collect']['min_quality_prob']}`
   только при наличии столбца: **{c['quality_filter_applied']}**.
3. Источник детерминированно семплируется по SHA256(seed, article+question)
   с выборкой реально коротких, средних и длинных ответов (20%/60%/20%).
   Исходные ответы не меняются, пороги diversity не ослабляются.
   Доля хвостов источника: {c['sampling']['source_tail_fraction']};
   коэффициенты разброса сырых v1/v2: {c['sampling']['raw_answer_len_ratios']}.
   Отбор не является случайной репрезентативной выборкой длин ответов: намеренно
   сильнее представлены короткие и длинные ответы для разнообразия инструкций.
   Стабильный порядок использует SHA256(seed, article+question),
   максимум {p['collect']['max_examples_per_article']} вопроса на статью,\n   v1 — {p['collect']['rows']['v1']}, v2 — {p['collect']['rows']['v2']} входных строк.
   v1 — префикс v2 в пределах этой версии кода/исходника.
4. В компактном Parquet исходный вопрос составляет сообщение пользователя;
   контекст добавляется только из реального поля `text`, если оно существует.
   Ответ сохраняется; пять формулировок системной инструкции выбираются хешем id.
5. Валидация chat-схемы; фильтры длины; маскирование телефона/email/даты
   рождения; exact и MinHash/LSH near-duplicate дедупликация по *вопросу*, а
   не контексту, если он присутствует.
6. 80/10/10 group-disjoint split по `original_id` (статья Википедии);
   проверка id/текста/LSH near-dup и отсутствия общих статей между train/test.

## Измеренные показатели {c['version']}

| Показатель | Значение |
|---|---:|
| Просмотрено строк источника | {c['rows_scanned']} |
| Допущено к выборке после первичных фильтров | {c['eligible_candidates']} |
| Собрано сырых примеров | {c['rows_written']} |
| Отброшено за отсутствие полей | {c['dropped_missing']} |
| Отброшено по длине | {c['dropped_lengths']} |
| Отброшено по quality_prob (если применимо) | {c['dropped_quality']} |
| Отброшено повторных article+question в источнике | {c['dropped_source_duplicate']} |
| Дошло до clean | {d['rows_in']} |
| Отброшено при clean по длине | {d['dropped_length']} |
| Удалено точных дубликатов | {d['dropped_exact_dup']} |
| Удалено почти-дубликатов | {d['dropped_near_dup']} |
| Маскировано строк с ПДн | {d['pii_rows_masked']} |
| **Примеров после очистки** | **{d['rows_out']}** |
| **Статей / групп** | **{div['groups']}** |
| Системных инструкций | {div['system_prompts']} |
| Доля крупнейшей группы | {div['largest_group_share']:.2%} |
| p10 / p50 / p90 длины ответа (символы) | {div['answer_len']['p10']} / {div['answer_len']['p50']} / {div['answer_len']['p90']} |
| p90/p10 длины ответа | {div['answer_len']['ratio_p90_p10']} |
| Доля наиболее частой длины | {div['same_length_share']:.2%} |
| Доля повторов текста ответа | {div['duplicate_answer_share']:.2%} |
| Длина запроса: p50 / p90 / p99 | {d['user_chars']['p50']} / {d['user_chars']['p90']} / {d['user_chars']['p99']} |
| Длина ответа: p50 / p90 / p99 | {d['assistant_chars']['p50']} / {d['assistant_chars']['p90']} / {d['assistant_chars']['p99']} |
| Diversity gate | {div['passed']} |
| Train | {s['sizes']['train']} ({s['ratios_actual']['train']:.1%}) |
| Validation | {s['sizes']['val']} ({s['ratios_actual']['val']:.1%}) |
| Test | {s['sizes']['test']} ({s['ratios_actual']['test']:.1%}) |
| Пересечений групп train/test | {s['contamination']['group_overlap']} |
| Near-duplicate пар train/test | {s['contamination']['near_dup_pairs']} |

## Известные ограничения и риски

- QA-ответы могут галлюцинировать или перефразировать неточно; source `quality_prob`
  отсутствует в компактном parquet и **не применялся**, если `quality_filter_applied=False`.
- Компактный источник не позволяет автоматически проверить, следует ли ответ из
  исходной статьи: полного контекста нет. Не проверяется фактологическая корректность.
- Не проверяется семантическая корректность ответа относительно текста и не
  выполняется ручная разметка. Near-dup MinHash/LSH приближённый, не обнаруживает
  все возможные семантические парафразы и может оставлять небольшие лексически
  непохожие переформулировки.
- Random-split строк завышал бы качество; split по исходной статье строже.
- Статьи и корпус отражают перекосы/неполноту Википедии; сведения могут устареть.
- Маскирование ПДн регулярными выражениями не является полной анонимизацией.
- В архив не включаются скачанные исходные материалы и результат реального DVC
  запуска, если он ещё не запускался пользователем.

## Воспроизводимость

`uv sync && make repro && make check`; затем `make versions` для двух Git/DVC
ревизий и `make diff` для их сравнения. Данные версионируются DVC; Git хранит код,
конфиг, lock-файлы и метрики. Настройки в `params.yaml`; исходник зафиксирован SHA256.
"""
    outfile = Path(paths["datasheet"])
    outfile.parent.mkdir(parents=True, exist_ok=True)
    outfile.write_text(text, encoding="utf-8")
    print(f"datasheet: {outfile} ({c['version']}, {d['rows_out']} clean rows)")


if __name__ == "__main__":
    main()
