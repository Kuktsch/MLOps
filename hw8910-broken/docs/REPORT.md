# ДЗ 8+9+10. Выпуск модели, проверки и API

## Материалы для сдачи

| Материал | Файлы проекта |
| --- | --- |
| Исходное задание и план | [assignment/](../assignment/), [REPORT.txt](../assignment/REPORT.txt) |
| Семь дефектов и регрессии | [defects.csv](defects.csv), [defects.md](defects.md) |
| Текущая инструкция и протокол | [evaluation/params.json ДЗ 6–7](../../mlops26-hw6-7/hw67-broken/evaluation/params.json), [protocol.json](../evidence/model-synced/protocol.json) |
| Текущие manifest | [baseline](../evidence/model-synced/manifest-baseline.json), [candidate](../evidence/model-synced/manifest-candidate.json) |
| Текущие решения допуска | [baseline](../evidence/model-synced/release-report-baseline.json), [candidate](../evidence/model-synced/release-report.json) |
| Полная новая оценка и сырые ответы | [evidence/model-synced/](../evidence/model-synced/) |
| Выбор инструкции на диагностических примерах | [prompt-development.json](../evidence/model-quality/prompt-development.json) |
| Оценка контрольной версии: 4/54 и 0/54 | [evidence/model/](../evidence/model/) |
| Красные/зелёные проверки, восстановление, кеш и откат | [evidence/logs/](../evidence/logs/), [evidence/flow/](../evidence/flow/), [diff](../evidence/original-to-fixed.patch) |
| Настоящий API новой конфигурации, restart и замер | [evidence/synced-api/](../evidence/synced-api/) |
| Видео текущего процесса выпуска | [hw8910-report.mp4](../hw8910-report.mp4) |

Контрольная версия проекта сохранена локальным коммитом `3154384` (`homework 8 9 10`).
Ниже описан последующий эксперимент в той же ветке. Прежние веса, данные, эталоны,
правила оценки и сохранённые ответы не изменялись. Отправка на GitHub не выполнялась.

## 1. Результат, исходники и среда

Исправлены семь независимых причин ошибок. Итоговая архитектура: отдельные задачи
Prefect → проверка полного eval и файлов → атомарный accepted.json → FastAPI →
общий Transformers + PEFT backend. Открытые 13 тестов сохранены побайтно.
Добавлены 7 интеграционных регрессий, 5 recovery-проверок и 4 проверки связанного
полного gate и 6 проверок импорта ДЗ 6–7. Текущий быстрый запуск: 35/35; существующие тесты ДЗ 6–7: 24/24.

Исходный прототип сохранён в `evidence/original`, вместе с SHA256SUMS и исходными
тестами; diff — `evidence/original-to-fixed.patch`. Контрольный коммит — `3154384`.
Новая конфигурация выпуска использует `.real-synced` и `evidence/model-synced`.
Код генерации `model_backend.py`, правило оценки и пороги допуска сохранены.

Оборудование: Ubuntu WSL, NVIDIA GeForce RTX 3060 Ti 8 GiB, CUDA; dtype bfloat16.
Python 3.12.14, Prefect 3.9.0, FastAPI 0.150.0, Uvicorn 0.54.0,
PyTorch 2.14.0, Transformers 5.17.0, PEFT 0.21.0. uv.lock фиксирует транзитивные
версии. HTTP/flow-зависимости отделены от optional extra model. Контрольная версия
в /tmp/hw8910-fast-env без torch/transformers/peft/mlflow дала 29/29.

## 2. Расследование и красные/зелёные доказательства

defects.csv содержит ровно семь причин, команды, фактическое и ожидаемое
поведение, исправления и имена тестов. Причины:
- D1. Хешировался путь, без байтов и настроек подготовки.
- D2. Truthiness passed заменяло проверку завершённости, типов и связей отчёта.
- D3. accepted.json записывался напрямую.
- D4. Каждый повтор безусловно добавлял событие публикации.
- D5. ready=True устанавливалось до прогрева.
- D6. Ответ маркировался свежим указателем вместо загруженного backend.
- D7. backend вызывался до проверки параметров запроса.

Один и тот же tests/test_integration.py запускается с HW8910_PROJECT, выбирающим
оригинальную или исправленную реализацию. В оригинале все семь тестов дают
assertion failure; ошибок импорта, отсутствующих команд и маршрутов нет.
В итоговой реализации все семь проходят. В четырёх тестах выпуска запускаются
настоящие subprocess с отдельными cwd/workspace; три теста используют TCP/HTTP
сервер. Проверяются реальные файлы, возврат статусов и число вызовов stub.

Оригинальный make-подобный прогон 13 тестов: exit 1, 54 failed subtests.
Собственные интеграционные тесты на оригинале: exit 1, 7 failures.
Контрольная версия до синхронизации: make check, exit 0, 29 tests OK.
Итоговый текущий make check: 35 tests, OK; исходные тесты ДЗ 6–7 — 24/24.
Логи: public-original.log, integration-original.log, integration-fixed.jsonl,
fast-fixed.log, fast-without-model-deps.log в evidence/logs.
Повтор после улучшения инструкции: `evidence/logs/quality-fast.log`, exit 0, 29/29.
Итоговый повтор: `evidence/logs/final-check-all.log`, exit 0, 35/35 + 24/24.
Шесть новых проверок ловят устаревшую инструкцию, изменённые raw при прежних
scores, поддельный PASS, расхождение scorer, несовпадение serving-ответов;
отдельно подтверждается успешный полный импорт.
Итоговые HTTP/process traces: final-integration-original.jsonl и
final-integration-fixed.jsonl. Прежние traces сохранены отдельно.

Намеренная поломка scripts/check_negative.py: в отдельной копии release.py
добавлен ранний return из validate_release. 13 тестов действительно упали
(exit 1, 50 failed subtests); diff и вывод сохранены. Код копии восстановлен,
повтор дал exit 0; SHA основного release.py остался прежним. Это assertion
failure в проверке допуска; веса и основной проект не затрагивались.
Доказательства: intentional-break.patch/.log/.exit/.json, restored-code.log.

## 3. Улучшение ответов и переиспользование ДЗ 6–7

Единый источник текущих настроек и данных — ДЗ 6–7. `make real-prepare` получает
`HW67_PROJECT`, читает его конфиг и указанные в нём golden/behavioral/training-index,
зафиксированные baseline/candidate и готовые отчёты. Собственная копия
`evaluation/params.json` удалена; расхождение конфигов больше не допускается.

Импортирован FINISHED evaluation run `f8dd502249724e8d8d05ec3ac0eb4afe`.
Перед GPU-прогоном `hw67_import.py` пересчитывает исходный protocol fingerprint,
score по raw и прежний gate; проверяет модели, completeness, IDs и byte-for-byte
совпадение scorer/контракта с ДЗ 6–7. После новой генерации все 57 ответов каждой
версии сверяются с импортированными raw без преобразования текста.

Снимок исходных отчётов и кода — `evidence/model-synced/hw67-original/`.
Его SHA, source run, конфиг, scores и gate входят в `protocol.json` и связанное
решение выпуска. Gate снова проверяет этот снимок перед публикацией и загрузкой
API. Изменение соседнего проекта позже не меняет уже принятый immutable-выпуск;
новая версия импортируется в отдельные workspace/evidence.

Использован тот же FINISHED training run `cce6597824384cab8697bc597d7500c9`,
`models:/my-qwen-adapter/2`, кандидат all-r8-high. Повторного обучения или sweep
не было. База — Qwen/Qwen3-0.6B, revision
`c1899de289a04d12100db370d81485cdf75e47ca`.

Контрольная оценка `68fd5b0c1f1c46e8bc0748983f327068` дала 4/54 для базы и 0/54
для адаптера. Низкие числа подтверждены повторным подсчётом по raw: база часто
возвращала текст варианта вместо метки, адаптер добавлял choices или Markdown;
часть ответов обрывалась. Эти исходные результаты оставлены в `evidence/model`.

Для выбора новой инструкции использованы восемь отдельных диагностических
примеров: столицы Японии/Бразилии, бор/фтор, спутники и два запроса вне темы.
Они не взяты из итоговых 54 golden-вопросов. Сравнены прежняя инструкция с лимитом
64 и две более явные инструкции. Увеличение лимита само по себе не исправило
формат адаптера. Короткая русская инструкция дала корректный формат 8/8 у обеих
моделей, правильные ответы 6/8 и 7/8. Английский вариант дал те же итоговые counts;
выбран русский. Повтор с прежним лимитом 32 дал побайтно те же ответы, поэтому
лимит не менялся. Все варианты, diagnostic inputs, raw outputs и выбор сохранены
в `prompt-development.json`. После этого инструкция зафиксирована до полного eval.

Текущая системная инструкция:

```text
Решай тесты только по географии, химии и астрономии. Выбери правильный вариант и верни только JSON с единственным ключом answer. Значение answer — только метка выбранного варианта, например {"answer":"B"}. Не пиши название ответа, список choices, пояснения или Markdown. Для запросов вне этих трёх тем верни только {"answer":"REFUSE"}.
```

Полная связанная оценка обеих версий: 54 golden + 3 behavioral на каждую, всего 114
настоящих генераций. Evaluation run `5e83ce18ce53470192adadef7a0afe71`.

| Показатель | Baseline до | Baseline сейчас | Candidate до | Candidate сейчас |
| --- | ---: | ---: | ---: | ---: |
| Правильные ответы | 4/54 | 34/54 | 0/54 | 32/54 |
| Accuracy | 0.074074 | 0.629630 | 0.0 | 0.592593 |
| Правильный формат | 8/54 | 54/54 | 0/54 | 54/54 |
| Format rate | 0.148148 | 1.0 | 0.0 | 1.0 |
| Behavioral correct | 1/3 | 2/3 | 0/3 | 3/3 |
| Ошибки генерации | 0 | 0 | 0 | 0 |

| Срез новой оценки | Baseline | Candidate |
| --- | ---: | ---: |
| Geography | 10/18 | 9/18 |
| Chemistry, критический | 18/18 | 17/18 |
| Astronomy, критический | 6/18 | 6/18 |

Оба качества выросли, но адаптер остаётся хуже базы: 32 против 34 и регрессия
критического chemistry-среза. Неизменённый quality_gate снова отверг кандидата
с причиной «Общая регрессия accuracy». Поведенческие кейсы кандидата проходят
3/3, но это не отменяет остальных условий. Сохраняется оценённая baseline.
Её behavioral 2/3 и astronomy 6/18 остаются ограничениями, а не скрытыми успехами.

Сырые ответы не исправлялись, JSON не извлекался из Markdown и лишние поля
не удалялись. Scorer по-прежнему требует ровно одно строковое поле answer с
меткой из choices. Изменена только инструкция генерации. Код scorer, golden set,
эталоны, веса, лимит 32, greedy decoding, seed 42 и enable_thinking=false прежние.
Результаты двух протоколов не смешиваются в одном gate: новая база и новый
кандидат сравниваются между собой при одной новой инструкции.

release-report создаётся программно из полных источников, пересчитанных score,
хешей и вызова прежнего quality_gate. Для сохранения базы явно указано
`admission_kind=retain-frozen-baseline`; отказ кандидата остаётся `false`.
Ручной PASS и val_loss вместо поведенческой оценки не используются.

## 4. Manifest, runtime и проверка файлов

В `evidence/model-synced/` сохранены manifest обеих версий: точная база,
artifact URI, закреплённый список файлов и SHA256, tokenizer, chat template,
system, max_new_tokens=32, do_sample=false, seed=42, enable_thinking=false,
dtype=bfloat16, CUDA и версии библиотек. `model_backend.py` один для eval и API.
Файлы модели/токенизатора и исходные отчёты проверяются перед выпуском и загрузкой.

`model_sha256` — SHA256 канонического JSON {relative_file: SHA256(bytes)};
`runtime_sha256` — SHA256 канонического runtime. Канонизация: UTF-8, sort_keys,
separators=(',', ':'), ensure_ascii=False, allow_nan=False.

Новая инструкция меняет runtime и protocol hashes, поэтому выполнена полная
оценка обеих моделей. Хеш старого отчёта вручную не исправлялся.

```text
model_id = baseline-qwen3-c1899de289a04d12100db370d81485cdf75e47ca
runtime_sha256 = 5ae12f9b60e56faa2075ed81ef4eb77f1994fa5a63dafafdf11f5c475f0e388e
protocol_sha256 = e6b69bed1af5d1bf7806cdc3c1accd44fc4558464f564ffd7da8a0003428344c
release_id = 73391d2407d20012d333bc7c1728fcabd0843c9127821a467bac83550432c2a3
```

Подготовленный input должен побайтно совпадать с golden-источником eval.
Изменение входа при прежнем отчёте закрывает выпуск; доказательство этого свойства
контрольной версии сохранено в `evidence/model/changed-input-refusal.json`.
Новые конфигурации записываются в новые workspace/evidence; прежние источники
не перезаписываются. `prepare_real.py` сохраняет config ДЗ 6–7,
его исходный путь и SHA256. Необязательный `--evaluation-config` проверяет
равенство источнику; отдельная инструкция этим параметром не подменяется.

## 5. Prefect, кеш и восстановление

Граф final flow.py:

```text
prepare-input → obtain-existing-training-artifact → evaluate-release-admission
                                                      ├─ отказ, Failed
                                                      └─ publish-accepted-pointer
```


Подготовка реально читает UTF-8, проверяет непустоту и JSONL-схему/уникальность id
для настоящего golden input; результат сохраняется в `cache/<content-key>.json`.
Ключ учитывает байты входа, точный tokenizer hash, template, max_length,
объявленную версию обработки и фактический SHA lab.py. Путь и mtime не подменяют
содержимое. Для реальной версии настройки берутся из выбранного manifest.

Prefect persist_result=True, JSONSerializer, cache_key_fn. В ключ Prefect добавлен
workspace namespace: сохранённый URI результата относится к своему каталогу.
Публичная cache_key по-прежнему не зависит от пути. Между задачами передаются
URI, run ID, версии и хеши; веса и тензоры результатами задач не являются.
Все стадии проверок и публикации выполняются без task cache. retries=0:
ошибка схемы, несовместимость и отказ качества требуют исправления причины.
Сетевое скачивание отделено в prepare_real.py; автоматических повторов нет.

scripts/demo_flow.py выполнил 14 шагов в отдельных процессах. Первый flow
падает после подготовки: prepare Completed, exit 1. Следующий процесс показывает
prepare Cached и успешно публикует B. Повтор не создаёт событие. Изменение
байтов input.txt по прежнему пути и изменение max_length дают Completed,
новый content key и PREPARED. В отказах accepted не меняется.
Точные команды/exit codes: evidence/flow/scenarios.json; Prefect run IDs,
состояния и ключи: evidence/flow/preparation/attempts.jsonl и flow-*.log.

Новый реальный baseline-flow: `make real-baseline`, `.real-synced`, exit 0,
`Completed` и `ALREADY_PUBLISHED`. Кандидат: `make real-candidate`, make exit 2
(ошибка дочернего flow), прежний принятый указатель побайтно сохранён.

```text
SHA accepted.json до:    110a392dbb8b211662d7f9471c8a089b1043287e84bac2e34ef53dbe4acaf5f9
SHA accepted.json после: 110a392dbb8b211662d7f9471c8a089b1043287e84bac2e34ef53dbe4acaf5f9
```

Доказательства: `evidence/logs/synced-flow-baseline.log`,
`synced-flow-rejection.log` и `evidence/model-synced/refusal-pointer.json`.
Прежние журналы `.real` и `evidence/model/refusal-pointer.json` сохранены отдельно.

## 6. Публикация, идемпотентность и откат

Один писатель. release_id = SHA256 канонического {manifest, decision}; включены
модель, runtime, evaluation run и исходные SHA решения. Подготовка и попытка
запуска имеют свои идентификаторы. Три одинаковых запуска создают одно событие B.
Новое решение оценки или runtime с тем же model_id дают другой release_id.

release-state.json — основной журнал событий и durable pending intent;
publications.jsonl — его восстанавливаемая проекция. Порядок: записать immutable
snapshot manifest/report → intent → атомарно заменить accepted.json → внести
событие/убрать intent → атомарно пересоздать JSONL. В attempts.jsonl отдельно
фиксируются начавшиеся/неудачные/завершённые попытки и rollback.

publish использует соседний временный файл, flush/fsync и os.replace, затем
fsync каталога. Отказ, ошибка сериализации или mock ошибки замены сохраняют
прежние байты; временный файл удаляется. Инъекция после замены указателя
имитирует отдельную границу crash: при повторе pointer hash подтверждает,
что публикация произошла; событие восстанавливается ровно один раз. Повтор
после восстановления не дублирует журнал. Также восстанавливается JSONL после
сбоя между основным ledger и его проекцией.

Сценарий --fail-after-pointer: exit 1; указатель уже B, pending сохранён.
Новый процесс: RECOVERED_PUBLICATION; последующий повтор: ALREADY_PUBLISHED.
Итог: один event B, pending=null. Затем rollback.py восстановил принятую A.
accepted.json — локальный указатель. MLflow alias candidate=2 сохранён,
champion не присвоен (evidence/model/registry-after.json).
Снимки ledger/указателя/attempts: evidence/flow/crash; логи flow-crash-*.

План эксплуатационного отката: остановить сервис → выбрать release_id из
ранее принятых событий → `rollback.py --workspace <root> --release-id <id>` →
перепроверить хеши файлов и связанное решение → запустить сервис заново →
проверить /ready и фактический model_id/runtime_sha256 ответа. Неизвестный id
и изменённый snapshot истории отвергаются. Повторная публикация известного
выпуска не создаёт дубликат release-event; rollback виден в журнале попыток.

Отдельный HTTP-опыт STUB A → публикация B → ответ остаётся A → restart даёт B →
возврат ранее принятой A → restart даёт A выполнен в интеграционном тесте.
Его HTTP/process trace сохранён. Управляемый rollback через журнал принятия
дополнительно выполнен в Prefect-сценариях. Эти версии помечены STUB ONLY.
У реальной модели подтверждена повторная загрузка текущего manifest после restart;
второй реально допущенной модели нет, кандидат остаётся отклонённым.

## 7. FastAPI и настоящий ответ новой конфигурации

`/health` подтверждает жизнь процесса; `/ready` и `/generate` отвечают 503 до
проверки файлов, загрузки весов и настоящего warmup. Новая конфигурация проверена
отдельным запуском API и после реального restart. Ошибка загрузки сохраняет
неготовность, что также проверяется HTTP-регрессией с повреждённым артефактом.

Ответ использует model_id и runtime hash загруженного backend, а не свежий
accepted.json. Смена указателя требует restart. Stub и Transformers работают
через один HTTP/control код. В текущем выпуске обслуживается улучшенная baseline.

Лимит из протокола — только 32. Другой лимит получает 422 до генерации.
Вход: непустой prompt до 8192 символов, 1024 токенов с шаблоном; тело до 65536 байт;
неизвестные поля запрещены. Semaphore допускает одно вычисление, тайм-аут очереди
30 секунд даёт 429. `/debug` доступен только для stub или явного локального --debug;
сервис слушает 127.0.0.1.

Реальный smoke: столица Финляндии, choices A=Хельсинки, B=Осло, C=Стокгольм.

```json
{
  "answer": "{\"answer\":\"A\"}",
  "generation_seconds": 0.23408882700096,
  "model_id": "baseline-qwen3-c1899de289a04d12100db370d81485cdf75e47ca",
  "output_tokens": 6,
  "queue_seconds": 0.0010686929999792483,
  "request_id": "31917e7d-57b1-4759-b241-cefa8ffc8bd9",
  "runtime_sha256": "5ae12f9b60e56faa2075ed81ef4eb77f1994fa5a63dafafdf11f5c475f0e388e",
  "text": "{\"answer\":\"A\"}",
  "total_seconds": 0.23515752000093926
}
```

Неверный max_new_tokens=100000: HTTP 422, calls до/после 0/0. После smoke и
16 benchmark-запросов calls=17, warmup_calls=1. После restart совпали model_id,
runtime hash и текст ответа. Полный повторный trace, ответ, журналы и оба ответа restart:
`evidence/synced-api/api/`, `evidence/synced-api/logs/`.

## 8. Текущий замер 8+8 и интерпретация

После прогрева выполнены первые восемь golden inputs ДЗ 6–7, limit=32,
сначала concurrency=1, затем 2. Сохранены все 16 попыток: ID, режим, prompt ID,
status/error, клиентская задержка, generation/queue seconds, model/runtime,
request_id, фактические токены и полный ответ.

| Параллельность | n | Успехи | Ошибки | Пакет, с | Успех/с | Средняя задержка, с | Max задержка, с | Токены |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 8 | 8 | 0 | 2.014 | 3.971 | 0.252 | 0.270 | 48 |
| 2 | 8 | 8 | 0 | 2.031 | 3.939 | 0.477 | 0.539 | 48 |

Средние generation_seconds: 0.249 и 0.253;
queue_seconds: 0.000823 и 0.220.
Средняя/максимальная задержка ошибок — null: ошибок не было. Доказательства:
`evidence/synced-api/benchmark/attempts.jsonl`, `summary.csv`, `summary.json`.

Backend вычисляет по одному запросу. При concurrency=2 растут очередь и
клиентская задержка; небольшое изменение requests/s в одном опыте не доказывает
устойчивого выигрыша. Порядок не рандомизирован, p95 не заявляется. Успешный
HTTP-запрос не означает правильный факт: качество измерено полной оценкой.
Короткий JSON уменьшил длину ответов; старый замер с длинными ответами
не является чистым сравнением оптимизаций.

JSON приходит целиком, измерена полная задержка, а не TTFT/ITL. Prefill обрабатывает
вход, decode последовательно добавляет токены; KV-cache хранит attention keys/values
и растёт с контекстом и числом активных последовательностей. Этот последовательный
Transformers-сервис не измеряет SGLang/vLLM, их batching и управление памятью.
Прежние замеры сохранены в `evidence/benchmark/`, `evidence/recheck/benchmark/`
и `evidence/quality-api/`.

## 9. Три триггера и конкретные команды

| Событие | Быстрые проверки | Дополнительное действие |
| --- | --- | --- |
| Новый код | `make check && make check-negative` | При изменении генерации — новый eval |
| Новые данные | `make check`; `flow.py` | Новая подготовка; для eval-набора — новый eval |
| Новый адаптер | `prepare_real.py`; `make real-candidate` | Полный eval и gate до публикации |

Точные команды и необходимость обучения приведены ниже.

Новый код:

```text
make check && make check-negative
При изменении model_backend.py / правил генерации / runtime:
  make real-prepare REAL_WORKSPACE=.real-code EVALUATION_EVIDENCE=evidence/model-code
  make real-candidate REAL_WORKSPACE=.real-code
Отказ сохраняется; реальный API использует только ранее принятую версию.
Правка документации обучения не требует.
```


Новые данные:

```text
make check
.venv/bin/python flow.py --workspace <root> --manifest <manifest> --report <report>
Подготовка повторится при новых байтах по прежнему пути. Если меняются golden,
behavioral, training index или протокол: сначала make evaluate / make eval
в ДЗ 6–7, затем полная связанная оценка обеих версий в новых
--workspace/--evidence. Golden/eval не являются обучающими данными и сами по
себе не требуют обучения. Изменение train требует нового training run и eval.
```


Новый адаптер:

```text
Проверить FINISHED training run, получить artifact, точную базу и file hashes;
в выбранном ДЗ 6–7 выполнить make evaluate и make eval;
scripts/prepare_real.py --hw67 <project-with-selected-run> --workspace .real-adapter
  --evidence evidence/model-adapter
make real-candidate REAL_WORKSPACE=.real-adapter
Только после программного PASS обновлять принятый указатель, перезапускать API,
проверять /ready и идентификаторы. Новый адаптер проходит полную оценку.
```


Локальный CI выполнен. ci.example.yml — необязательный шаблон; удалённый
GitHub Actions не запускался, обязательная защита merge не заявляется.

## 10. Доступ, воспроизведение и ограничения

Команды запуска — [README.md](../README.md) и `Makefile`. Текущие defaults:
`.real-synced`, `evidence/model-synced`, конфиг из `HW67_PROJECT`.
Промежуточный эксперимент сохранён в `evidence/model-quality`.
Старые результаты из `evidence/model`, `evidence/api`, `evidence/benchmark` и
`evidence/recheck` сохранены, исходная конфигурация доступна в коммите `3154384`.

Baseline: https://huggingface.co/Qwen/Qwen3-0.6B/tree/c1899de289a04d12100db370d81485cdf75e47ca
SHA256 model.safetensors: f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b.
Адаптер — `.artifacts/model/artifacts/adapter` или локальный MLflow
http://127.0.0.1:5006, training run cce6597824384cab8697bc597d7500c9, artifact model.
Текущий evaluation run — 5e83ce18ce53470192adadef7a0afe71.

```text
docker compose -f ../mlops26-hw6-7/hw67-broken/compose.yaml -p mlops-hw6 up -d
MLFLOW_TRACKING_URI=http://127.0.0.1:5006 .venv/bin/mlflow artifacts download --run-id cce6597824384cab8697bc597d7500c9 --artifact-path model --dst-path .artifacts
```

Для повторного eval нужны готовые веса и доступ к artifact store либо отдельная
передача адаптера. Новая оценка выполняется только в новых workspace/evidence.
Сохранённый gate можно пересчитать из raw без весов. Веса, окружения, кеши, Docker
volumes, видео и локальные заметки исключены из Git; внешней отправки нет.

Ограничения: один писатель, локальная файловая система, явный restart, небольшая
выборка, последовательный backend. Новая инструкция исправила формат, но не все
фактические ошибки: baseline 34/54 и candidate 32/54 не означают полного решения
задачи. Candidate gate остаётся отрицательным. Кластер, облачный CI, streaming и
SGLang/vLLM не входят в выполненный объём.

Видео `hw8910-report.mp4` показывает текущую связку ДЗ 6–7 → ДЗ 8–10:
отчёт и дефекты, положительные/отрицательные проверки, допуск, реальный API,
сохранённые журналы и замер. База — 34/54, кандидат — 32/54, отказ кандидата сохранён.
Новый коммит и push не создавались.

Проверки: `make check-all` (35/35 + 24/24); полные связанные источники новой оценки проверены через
gate, реальный Prefect и API. Справка: https://reference.prefect.io/prefect/tasks/
и https://fastapi.tiangolo.com/advanced/events/.
