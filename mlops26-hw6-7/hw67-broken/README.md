# ДЗ 6–7. Учёт экспериментов и оценка LoRA-адаптера

## Результат

Выполнен поиск по шести LoRA-конфигурациям на собственном Russian Encyclopedia QA,
подготовленном в ДЗ 3–5. Выбран all-r8-high: val loss 2.086758 → 1.936619.
В реестре зарегистрирована версия 2 с alias candidate.

После переноса уточнённой инструкции из ДЗ 8–10 выполнена новая штатная оценка:
база улучшилась с 4/54 до **34/54**, адаптер — с 0/54 до **32/54**.
Валидный JSON — **54/54** у обеих моделей. Quality gate по-прежнему отклоняет
адаптер: 32/54 против 34/54 и регрессия критического chemistry-среза.
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

Оба архива включены в репозиторий и сохранены как уже сданная версия до
уточнения инструкции; новое содержимое в них не записывалось.
Текущие ответы и оценки — в `metrics/`, предыдущие — в
`metrics/history/cf4fea2cb0ef40e4841c52076d436880/`. Текущий evaluation run: `f8dd502249724e8d8d05ec3ac0eb4afe`.
`reports.zip` содержит прежние сырые ответы,
результаты оценки, решения gate, таблицы, логи и контрольные суммы файлов.
`evaluation-data.zip` содержит golden, behavioral, полный training-index
и DVC-объекты набора оценки. Порядок восстановления данных приведён в
[docs/data.md](docs/data.md#dvc-и-доступ-преподавателю).

## Повтор оценки с текущей инструкцией

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 make evaluate
make eval
make check-negative
make check-all
```

Используются прежние FINISHED training run, версия 2 и закреплённая база;
повторное обучение не требуется. `make evaluate` генерирует все 54 golden +
3 behavioral для каждой модели, сохраняет raw и новый run в MLflow.
Инструкция — `evaluation/params.json`; пороги, scorer, эталоны и лимит 32 прежние.
`make eval` ожидаемо возвращает make exit 2 из-за регрессии кандидата.
Успешная приёмка — 9/9 и 24/24 — проверяет корректность процесса и артефактов,
а не означает прохождение моделью всех вопросов.

Эти команды обновляют текущие `metrics/`. Результаты исходной сдачи сохранены
в history и сданных архивах; сами архивы команды оценки не меняют.
`src.predict` загружает неизменённый пакет с прежней инструкцией открытого QA;
MCQ/JSON проверяется отдельной общей инструкцией через `make evaluate`, как
предусмотрено заданием.

## Воспроизведение обучения с начала

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
submission заново формирует архивы и контрольные суммы, заменяя уже сданные
файлы. При текущем обновлении эта команда не запускалась.

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
