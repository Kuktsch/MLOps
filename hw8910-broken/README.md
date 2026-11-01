# ДЗ 8+9+10. Выпуск модели и API

Задание: [homework8-9-10.html](assignment/homework8-9-10.html). Итоговый отчёт и перечень материалов для сдачи: [REPORT.md](docs/REPORT.md). Семь дефектов: [defects.csv](docs/defects.csv).

Оригинальный план отчёта сохранён в [REPORT.txt](assignment/REPORT.txt). Заполненный отчёт оформлен в Markdown: [docs/REPORT.md](docs/REPORT.md). Структурированные отчёты, сырые результаты и журналы сохраняют форматы JSON, CSV, JSONL и log.

Текстовый разбор семи исправленных ошибок: [docs/defects.md](docs/defects.md).

Результат выпуска: API обслуживает baseline с оценкой **34/54**.
Кандидат с готовым LoRA-адаптером получил **32/54** и отклонён правилом качества
из ДЗ 6–7. У обеих моделей корректный JSON в 54/54 случаях. Manifest, полная
оценка, сырые ответы и решения допуска — [evidence/model-synced/](evidence/model-synced/).
Конфигурация оценки — [evaluation/params.json ДЗ 6–7](../mlops26-hw6-7/hw67-broken/evaluation/params.json).

## Проверки

Команды выполняются из `hw8910-broken`, Python 3.12. Зависимости закреплены в `pyproject.toml` и `uv.lock`.

```bash
uv sync --frozen
make check-all
make check-negative
```

Ожидается 35/35 тестов ДЗ 8–10 и 24/24 сохранённых теста ДЗ 6–7 и успешная проверка намеренной поломки/восстановления. Только приложенные 13 тестов работают без сторонних пакетов:

```bash
make unit
```

Одинаковые интеграционные регрессии на оригинале и исправленном проекте:

```bash
HW8910_PROJECT=evidence/original .venv/bin/python -m unittest discover -s tests -p test_integration.py -v
.venv/bin/python -m unittest discover -s tests -p test_integration.py -v
```

Первый прогон ожидаемо возвращает 1 с семью assertion failures, второй — 0. Исходник сохранён в `evidence/original/`, diff — `evidence/original-to-fixed.patch`.

## Процесс и реальный API

```bash
make demo-flow
uv sync --frozen --extra model
make real-api
```

```bash
curl http://127.0.0.1:8091/health
curl http://127.0.0.1:8091/ready
curl -H 'Content-Type: application/json' -d '{"prompt":"Какой город является столицей Финляндии?\nA: Хельсинки; B: Осло; C: Стокгольм. Допустимые метки choices: A, B, C.","max_new_tokens":32}' http://127.0.0.1:8091/generate
make benchmark BENCHMARK_OUTPUT=evidence/synced-api-recheck/benchmark
```

`make real-api` использует оценённый выпуск из `.real-synced`.
Обслуживается baseline: 34/54. `make real-baseline` сохраняет её,
`make real-candidate` ожидаемо завершается отказом; указатель не меняется.
Benchmark запускается во втором терминале, пока API работает. Для повторов
выбирайте новый `BENCHMARK_OUTPUT`, чтобы сохранить прежние измерения.

Реальный smoke, неверный запрос до генерации, 16 benchmark-запросов и restart
уже проверены: [evidence/synced-api/](evidence/synced-api/).
Повтор в новый каталог:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python scripts/demo_api.py --workspace .real-synced --evaluation-evidence evidence/model-synced --output-root evidence/synced-api-recheck
```

## Повтор полной оценки без обучения

```bash
docker compose -f ../mlops26-hw6-7/hw67-broken/compose.yaml -p mlops-hw6 up -d
make real-prepare REAL_WORKSPACE=.real-synced-repeat EVALUATION_EVIDENCE=evidence/model-synced-repeat
make real-baseline REAL_WORKSPACE=.real-synced-repeat
make real-candidate REAL_WORKSPACE=.real-synced-repeat
make real-api REAL_WORKSPACE=.real-synced-repeat
```

`make real-prepare` читает актуальный проект `HW67_PROJECT` (по умолчанию
`../mlops26-hw6-7/hw67-broken`): его `evaluation/params.json`, пути данных из
этого конфига, baseline, candidate, отчёты, raw и код scorer/gate. Отдельной
копии инструкции в ДЗ 8–10 больше нет. Если настройки/данные ДЗ 6–7 меняются,
сначала выполните там `make evaluate` и `make eval`; затем импортируйте в новые
workspace/evidence. Ожидаемый отказ кандидата не препятствует импорту базы.

Перед генерацией проверяются актуальность обоих отчётов и решение прежнего gate;
при выпуске проверка повторяется по сохранённому снимку. Все 114 ответов serving
backend должны совпасть с raw ДЗ 6–7. Обучение и sweep не запускаются.
Оценка использует те же готовые веса и полный набор 54 golden + 3 behavioral
для каждой модели. Выбирайте новые workspace/evidence: источники принятого решения не перезаписываются. Доступ к артефактам и таблица «код / данные / адаптер» описаны в `docs/REPORT.md`.

Текущий источник — evaluation run `f8dd502249724e8d8d05ec3ac0eb4afe` ДЗ 6–7;
связанный serving evaluation run — `5e83ce18ce53470192adadef7a0afe71`. Связи, хеши и исходные
отчёты сохранены в `evidence/model-synced/protocol.json` и `hw67-original/`.

`make check` запускает 35 тестов текущего проекта; `make check-hw67` —
сохранённые 24 теста ДЗ 6–7; `make check-all` объединяет оба набора.
Тесты ДЗ 6–7 сохранены в исходном проекте:

```bash
cd ../mlops26-hw6-7/hw67-broken
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

## Форматы файлов

- `assignment/REPORT.txt` — исходный план преподавателя; `docs/REPORT.md` — заполненный отчёт; `README.md` — команды запуска.
- `docs/defects.csv`, `evidence/model-synced/*.json`, `*.jsonl` и журналы — результаты и доказательства из задания.
- `assignment/` — оригиналы задания: HTML, `REPORT.txt`, `CONTRACTS.txt`, `INCIDENTS.txt`.
- `requirements-fast.txt`, `requirements-flow.txt` — списки зависимостей для установки, не отчёты.
- `input.txt`, `model-A.txt`, `model-B.txt` в STUB-опытах — вход и синтетические артефакты; имена используются исходным прототипом и тестами.

Веса, окружения, кеши и видео исключены из Git. Исправленная реализация сохранена
в локальном коммите `6e19e28`; исходный прототип — в `evidence/original/`.
Отправка на GitHub не выполнялась.
Видео `hw8910-report.mp4` показывает текущие результаты: 34/54 у базы и
32/54 у кандидата, проверки и работу реального API. Удалённый CI и защита merge не заявляются.
