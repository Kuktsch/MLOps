# ДЗ 6–7. Учёт экспериментов и оценка LoRA-адаптера

## Результат

Выполнен поиск по шести LoRA-конфигурациям на собственном Russian Encyclopedia QA,
подготовленном в ДЗ 3–5. Выбран all-r8-high: val loss 2.086758 → 1.936619.
В реестре зарегистрирована версия 2 с alias candidate.

Quality gate отклонил кандидата: accuracy 4/54 → 0/54, format rate 8/54 → 0/54.
Champion отсутствует. Baseline сохранён без изменений. Итоговая приёмка:
9/9 проверок MLflow и загрузки, 24/24 теста оценки. Отпечаток tests/: c42ac7788026.

## Среда и версии

- Ubuntu WSL, Python 3.12, uv, Docker Compose v2 через Docker Desktop.
- Qwen/Qwen3-0.6B, revision c1899de289a04d12100db370d81485cdf75e47ca.
- Зависимости закреплены в исходном uv.lock.
- Train/val, golden, behavioral и training-index версионируются DVC.
- Код, конфигурация и данные связаны с runs через SHA256 и снимки исходников.

## Документы и результаты

| Файл | Содержание |
|---|---|
| [docs/conclusion.md](docs/conclusion.md) | Методика, результаты, срезы, пять пар ответов, решение о выпуске |
| [docs/comparison.csv](docs/comparison.csv) | Сравнение шести runs, выгруженное из MLflow |
| [docs/defects.md](docs/defects.md) | Четыре дефекта, исправления и измеренные подтверждения |
| [docs/data.md](docs/data.md) | Источники данных, контроль пересечений и DVC |
| metrics/tokenization-proof.json | Равенство тензоров повторной токенизации исходных JSONL |
| metrics/evidence.json | Идентификаторы runs, ссылки, хеши и состояние реестра |
| [submission/reports.zip](submission/reports.zip) | Итоговые отчёты, метрики и логи проверок |
| [submission/evaluation-data.zip](submission/evaluation-data.zip) | Данные оценки и соответствующие DVC-объекты |

Оба архива включены в репозиторий. `reports.zip` содержит сырые ответы,
результаты оценки, решения gate, таблицы, логи и контрольные суммы файлов.
`evaluation-data.zip` содержит golden, behavioral, полный training-index
и DVC-объекты набора оценки. Порядок восстановления данных приведён в
[docs/data.md](docs/data.md#dvc-и-доступ-преподавателю).

## Воспроизведение эксперимента

Рабочий каталог: mlops26-hw6-7/hw67-broken.

```bash
uv sync --frozen --python 3.12
make prepare
make up
make sweep
make report
make candidate
make baseline-init
make evaluate
make eval
```

baseline-init создаёт baseline.json однократно и отклоняет перезапись.
Команда eval возвращает ненулевой статус при отказе quality gate.
В сохранённом эксперименте причина отказа — общая регрессия accuracy.
Регистрация champion выполняется командой promote только после PASS.

## Проверка сохранённых результатов

```bash
make up
make check-negative
make check-storage
make check-all
make evidence
make submission
```

check-negative изменяет копию ответов. check-storage пересоздаёт только
MLflow проекта mlops-hw6, сохраняет volumes и сверяет SHA256 probe.
check-all проверяет загрузку candidate в отдельном процессе и запускает
тесты оценки. evidence обновляет ссылки и доказательства в evaluation run.
submission формирует архивы и контрольные суммы итогового комплекта.

## Условия воспроизводимости

Изменение src, params.yaml или train/val требует нового sweep.
Изменение кода оценки, протокола или проверочного набора требует генерации
ответов обеих версий. Правки документации не изменяют эти хеши.
Обновление baseline выполняется отдельно после успешного допуска и сохраняет историю.

MLflow UI: http://127.0.0.1:5006. Остановка сервисов с сохранением данных:

```bash
docker compose -p mlops-hw6 stop
```

В архивы не включаются веса, train/val-тензоры, окружения, volumes и секреты.
Требования задания приведены в EVALUATION.md и ../Задание.html.
