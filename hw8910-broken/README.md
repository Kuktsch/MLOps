# ДЗ 8+9+10. Выпуск модели и API

Задание: [homework8-9-10.html](assignment/homework8-9-10.html). Итоговый отчёт и перечень материалов для сдачи: [REPORT.md](docs/REPORT.md). Семь дефектов: [defects.csv](docs/defects.csv).

Оригинальный план отчёта сохранён в [REPORT.txt](assignment/REPORT.txt). Заполненный отчёт оформлен в Markdown: [docs/REPORT.md](docs/REPORT.md). Структурированные отчёты, сырые результаты и журналы сохраняют форматы JSON, CSV, JSONL и log.

Текстовый разбор семи исправленных ошибок: [docs/defects.md](docs/defects.md).

## Проверки

Команды выполняются из `hw8910-broken`, Python 3.12. Зависимости закреплены в `pyproject.toml` и `uv.lock`.

```bash
uv sync --frozen
make check
make check-negative
```

Ожидается 29/29 тестов и успешная проверка намеренной поломки/восстановления. Только приложенные 13 тестов работают без сторонних пакетов:

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
curl -H 'Content-Type: application/json' -d '{"prompt":"Какой химический символ у кислорода? choices: O, H, N.","max_new_tokens":32}' http://127.0.0.1:8091/generate
make benchmark
```

Кандидат честно отклонён по quality gate, обслуживается frozen baseline. `make real-baseline` сохраняет её, `make real-candidate` ожидаемо завершается отказом.

## Повтор полной оценки без обучения

```bash
docker compose -f ../mlops26-hw6-7/hw67-broken/compose.yaml -p mlops-hw6 up -d
make real-prepare REAL_WORKSPACE=.real-recheck EVALUATION_EVIDENCE=evidence/model-recheck
make real-baseline REAL_WORKSPACE=.real-recheck
make real-candidate REAL_WORKSPACE=.real-recheck
make real-api REAL_WORKSPACE=.real-recheck
```

Выбирайте новые workspace/evidence: источники принятого решения не перезаписываются. Доступ к артефактам и таблица «код / данные / адаптер» описаны в `docs/REPORT.md`.

Тесты ДЗ 6–7 сохранены в исходном проекте:

```bash
cd ../mlops26-hw6-7/hw67-broken
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

## Форматы файлов

- `assignment/REPORT.txt` — исходный план преподавателя; `docs/REPORT.md` — заполненный отчёт; `README.md` — команды запуска.
- `docs/defects.csv`, `evidence/model/*.json`, `*.jsonl` и журналы — результаты и доказательства из задания.
- `assignment/` — оригиналы задания: HTML, `REPORT.txt`, `CONTRACTS.txt`, `INCIDENTS.txt`.
- `requirements-fast.txt`, `requirements-flow.txt` — списки зависимостей для установки, не отчёты.
- `input.txt`, `model-A.txt`, `model-B.txt` в STUB-опытах — вход и синтетические артефакты; имена используются исходным прототипом и тестами.

Веса, окружения, кеши и видео исключены из Git. Текущий результат сохраняется локальным коммитом `homework 8 9 10`; отправка на GitHub не выполняется. Видео предоставляется отдельно. Удалённый CI и защита merge не заявляются.
