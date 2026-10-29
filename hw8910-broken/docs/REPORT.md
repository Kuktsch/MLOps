# ДЗ 8+9+10. Выпуск модели, проверки и API
Выполнено локально 29 октября 2026 года, Europe/Moscow.

## Материалы для сдачи

| Материал из задания | Файлы проекта |
| --- | --- |
| Описание по плану отчёта | [REPORT.md](REPORT.md) |
| Семь дефектов и регрессии | [defects.csv](defects.csv); текстовый разбор — [defects.md](defects.md) |
| Manifest кандидата и принятой baseline | [manifest-candidate.json](../evidence/model/manifest-candidate.json), [manifest-baseline.json](../evidence/model/manifest-baseline.json) |
| Решения допуска | [release-report.json](../evidence/model/release-report.json), [release-report-baseline.json](../evidence/model/release-report-baseline.json) |
| Полный baseline/candidate eval и сырые ответы | [baseline-eval.json](../evidence/model/baseline-eval.json), [candidate-eval.json](../evidence/model/candidate-eval.json), [baseline-outputs.json](../evidence/model/baseline-outputs.json), [candidate-outputs.json](../evidence/model/candidate-outputs.json) |
| Протокол, набор оценки, происхождение и хеши | [evidence/model/](../evidence/model/) — protocol, golden, behavioral, training-index, training-import, file-verification |
| Красные/зелёные проверки и намеренная поломка | [evidence/logs/](../evidence/logs/), [diff исправлений](../evidence/original-to-fixed.patch) |
| Сбой, восстановление, кеш, отказ, повтор и откат | [evidence/flow/](../evidence/flow/), [evidence/real-flow/](../evidence/real-flow/), [SHA указателя до/после отказа](../evidence/model/refusal-pointer.json) |
| Настоящий API: ответ, готовность, неверный запрос и restart | [real-response.json](../evidence/api/real-response.json), [requests.jsonl](../evidence/api/requests.jsonl), [restart.json](../evidence/api/restart.json) |
| Видеоотчёт | [hw8910-report.mp4](../hw8910-report.mp4) |
| Каждая попытка замера и сравнительная сводка | [attempts.jsonl](../evidence/benchmark/attempts.jsonl), [summary.csv](../evidence/benchmark/summary.csv), [summary.json](../evidence/benchmark/summary.json) |

Таблица триггеров, объяснение результатов, ограничения, команды и доступ к артефактам приведены ниже. Сам исправленный проект включает код, тесты, `Makefile`, `pyproject.toml` и `uv.lock`. Текущий результат сохраняется локальным коммитом `homework 8 9 10`. Видео предоставляется отдельно; отправка на GitHub не выполняется.

## 1. Результат, исходники и среда

Исправлены семь независимых причин ошибок. Итоговая архитектура: отдельные задачи
Prefect → проверка полного eval и файлов → атомарный accepted.json → FastAPI →
общий Transformers + PEFT backend. Открытые 13 тестов сохранены побайтно.
Добавлены 7 интеграционных регрессий, 5 recovery-проверок и 4 проверки связанного
полного gate. Быстрый запуск: 29/29; существующие тесты ДЗ 6–7: 24/24.

Исправленная версия фиксируется локальным коммитом `homework 8 9 10`; видео предоставляется отдельно.
Исходная версия сохранена в evidence/original, вместе с SHA256SUMS и исходными
тестами; изменения представлены evidence/original-to-fixed.patch. Отдельный коммит
исходной версии не создавался. PR и удалённой отправки нет. Версии среды приведены ниже.

Оборудование: Ubuntu WSL, NVIDIA GeForce RTX 3060 Ti 8 GiB, CUDA; dtype bfloat16.
Python 3.12.14, Prefect 3.9.0, FastAPI 0.150.0, Uvicorn 0.54.0,
PyTorch 2.14.0, Transformers 5.17.0, PEFT 0.21.0. uv.lock фиксирует транзитивные
версии. HTTP/flow-зависимости отделены от optional extra model. Проверка в новом
/tmp/hw8910-fast-env без torch/transformers/peft/mlflow также дала 29/29.

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
Итоговый make check: exit 0, 29 tests OK.
Логи: public-original.log, integration-original.log, integration-fixed.jsonl,
fast-fixed.log, fast-without-model-deps.log в evidence/logs.
Полный HTTP/process trace оригинала: integration-original.jsonl.

Намеренная поломка scripts/check_negative.py: в отдельной копии release.py
добавлен ранний return из validate_release. 13 тестов действительно упали
(exit 1, 50 failed subtests); diff и вывод сохранены. Код копии восстановлен,
повтор дал exit 0; SHA основного release.py остался прежним. Это assertion
failure в проверке допуска; веса и основной проект не затрагивались.
Доказательства: intentional-break.patch/.log/.exit/.json, restored-code.log.

## 3. Переиспользование ДЗ 6–7 и связь с реальной моделью

Training run cce6597824384cab8697bc597d7500c9, all-r8-high, FINISHED,
models:/my-qwen-adapter/2; исходный sweep 3fb720f030184dccb7e98b82434bd1e9.
Использованы готовые веса из MLflow. Повторного sweep и обучения не было.
Исходный evaluation run: cf4fea2cb0ef40e4841c52076d436880.
Зафиксированная baseline: Qwen/Qwen3-0.6B,
base commit c1899de289a04d12100db370d81485cdf75e47ca.

При введении общего serving backend, точных library/runtime/file hashes
выполнена новая полная оценка обеих версий: 54 golden + 3 behavioral на версию.
Evaluation run 68fd5b0c1f1c46e8bc0748983f327068, experiment hw8910-evaluation (3).
MLflow UI: http://127.0.0.1:5006/#/experiments/3/runs/68fd5b0c1f1c46e8bc0748983f327068
Полные исходники оценки, данные и сырые ответы: evidence/model; первоначальная
оценка и конфиги ДЗ 6–7: evidence/model/hw67-original.

| Показатель | Baseline | Candidate |
| --- | ---: | ---: |
| Golden, примеров | 54 | 54 |
| Правильные ответы | 4/54 | 0/54 |
| Accuracy | 0.074074 | 0.0 |
| Правильный формат | 8/54 | 0/54 |
| Format rate | 0.148148 | 0.0 |
| Behavioral correct | 1/3 | 0/3 |
| Ошибки генерации | 0 | 0 |

Критические chemistry и astronomy: baseline accuracy 1/18 в каждом срезе,
candidate 0/18 в каждом. Geography: 2/18 против 0/18. Исходное правило допуска
сохранено в vendor/hw67_gate.py побайтно: общая accuracy/format rate не ниже
baseline, accuracy критических срезов без регрессий, все behavioral-кейсы
кандидата должны проходить. Порог не ослаблялся. Отказ: «Общая регрессия accuracy»;
остальные регрессии также видны в полных отчётах. val_loss не использовался
как замена поведенческой оценки.

release-report.json создаётся программно: заново вычисляются score по сырым
ответам, проверяются все id/срезы/counts и вызывается quality_gate. Отчёт связывает
training run, evaluation run, model/runtime/protocol/golden и SHA256 каждого
исходного отчёта/сырого вывода. Ручное passed=true отвергается тестом.
Повреждение raw outputs даже с пересчитанным SHA источника выявляет несоответствие
сохранённым scores; неполный source-eval тоже закрывает выпуск.

Принятая baseline сохраняется явно по происхождению evaluation/baseline.json.
Её admission_kind=retain-frozen-baseline; candidate_gate.passed=false остаётся
в отчёте. passed для сохранения baseline выводится из совпадения закреплённой
спецификации и полной проверки источников, а не из нового успешного candidate gate.
Baseline имеет низкую accuracy и behavioral 1/3: эти ограничения не скрыты.

## 4. Manifest, runtime и файлы

Manifest содержит model_id, artifact URI, закреплённый относительный список
файлов и их SHA256, агрегат model_sha256, commit базы, tokenizer files/hash,
chat template hash, полный system, max_new_tokens=32, do_sample=false, seed=42,
enable_thinking=false, dtype=bfloat16, device=cuda, версии библиотек,
хеш model_backend.py и protocol/golden hashes. Для адаптера включены веса,
adapter_config, tokenizer и manifest обучения; для базы проверяется сам snapshot.

model_sha256 = SHA256 канонического JSON {relative_file: SHA256(bytes)}.
runtime_sha256 = SHA256 канонического runtime. Канонизация: UTF-8,
sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False.

Файлы пересчитываются перед публикацией и загрузкой. API не читает params.yaml
обучения и не подменяет runtime настройками окружения. TransformersBackend
проверяет фактические версии библиотек, template и dtype. Изменившийся runtime
требует новой полной оценки; редактирование хеша старого отчёта не поможет.
Подготовленный input обязан побайтно совпадать с golden-источником eval;
изменение реального входа при старом отчёте закрывает выпуск. Это отдельно
проверено через Prefect: real-flow-changed-input.log и changed-input-refusal.json.
Старые источники eval не перезаписываются: prepare_real.py требует отдельные
--workspace и --evidence для новой оценки.

Модель в памяти:

```text
model_id = baseline-qwen3-c1899de289a04d12100db370d81485cdf75e47ca
runtime_sha256 = 23b1355a29a26128665fd6766b91ed6b9b5df16b29407670de66c11a1b9d974d
release_id = fe0f35d2bbe677a93bb31563b6cc0860ee4c23cc79b91f109911c8188c9aaea5
```


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

Повтор real baseline flow дал Completed и ALREADY_PUBLISHED; real candidate flow
завершился Failed (exit 1). SHA accepted.json до и после реального отказа:

```text
8879d420cb104d981ff0a7d76df38adf5fc58149362ce498df8b23cf4e937c70
8879d420cb104d981ff0a7d76df38adf5fc58149362ce498df8b23cf4e937c70
```

Доказательства: real-flow-baseline.log, real-flow-rejection.log,
evidence/model/refusal-pointer.json. Предыдущая версия сохранена побайтно.

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

## 7. FastAPI и настоящий ответ

/health подтверждает жизнь процесса. В lifespan создаётся фоновая загрузка;
/ready и /generate возвращают 503 до проверки файлов, загрузки и настоящего
warmup. После ошибки загрузки health остаётся 200, ready 503. Это проверено
HTTP-тестом с повреждённым принятым артефактом.

Сервис удерживает снимок принятого manifest. Ответ берёт model_id/runtime_sha256
из загруженного backend. Замена accepted.json не меняет веса в памяти.
Backend interface: validate_prompt, warmup, generate; factory внедряется в
create_app/ServiceState. Stub и Transformers используют один HTTP/control код.
Фактическая генерация и eval используют один model_backend.py.

Лимит генерации закреплён: только 32, как в протоколе. Другие значения, включая
меньшие, не наследуют допуск и получают 422. Непустой prompt <=8192 символов,
полный токенизированный ввод <=1024, тело <=65536 байт, неизвестные поля запрещены.
Semaphore допускает одно вычисление; ожидание ограничено 30 секундами (429 при
истечении). /debug доступен для stub и при явном локальном --debug; обычный
реальный запуск его не включает. Сервис привязан к 127.0.0.1.

Первоначальный реальный smoke: вопрос geography-06 о столице Ирландии, A=Лондон,
B=Эдинбург, C=Дублин. Ответ модели: {"answer":"C"}, 10 выходных токенов,
generation_seconds=0.645143, queue_seconds=0.001008, total_seconds=0.646151.
request_id=35faf00d-d494-46a9-ad5b-ae83daca76f4.
Полный ответ и prompt: evidence/api/real-response.json.
Неверный max_new_tokens=100000: HTTP 422; calls до/после = 0/0.
После 1 валидного smoke и 16 benchmark-запросов calls=17, warmup_calls=1.
После реального restart совпали model_id, runtime hash и текст ответа.
Доказательства: evidence/api/requests.jsonl, restart.json, real-api-*.log.

## 8. Замер 8+8 и интерпретация

Ниже сохранён первоначальный замер. Все попытки повторного замера сохранены
в evidence/recheck/benchmark/attempts.jsonl, сводка — summary.csv и summary.json.
Повторный smoke и restart сохранены в evidence/recheck/api/.

После прогрева один набор первых восьми golden inputs, те же prompts и limit=32.
Сначала concurrency=1, затем concurrency=2. Клиент сохраняет каждую попытку:
attempt ID, prompt ID, режим, HTTP status/error, request_id, model/runtime,
фактические токены, полную клиентскую задержку, время вычисления/ожидания и ответ.
Ошибки и timeout не отбрасываются. Здесь их оказалось 0.

| Параллельность | n | Успехи | Ошибки | Пакет, с | Успех/с | Средняя задержка, с | Max задержка, с | Токены |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 8 | 8 | 0 | 9.266 | 0.863 | 1.158 | 2.016 | 134 |
| 2 | 8 | 8 | 0 | 5.194 | 1.540 | 1.148 | 2.077 | 134 |

Среднее generation_seconds: 1.154 и 0.649.
Среднее queue_seconds: 0.001 и 0.496.
Средняя/максимальная задержка ошибок: null — ошибок не было.
Полная точность: evidence/benchmark/summary.csv и summary.json.
Все 16 попыток с ответами: evidence/benchmark/attempts.jsonl.

Клиентская задержка включает очередь, вычисление, HTTP и сериализацию.
generation_seconds начинается после semaphore; queue_seconds включает ожидание
и предварительную обработку. При c=2 запросы ожидают занятое вычисление.
Рост requests/s сопровождается изменением среднего времени самой генерации:
из единственного последовательного опыта причина этого изменения не установлена.
Возможны эффекты прогрева разных длин, частот GPU и фоновой нагрузки; это гипотезы,
а не измеренные причины. Очередность режимов не рандомизирована; серии повторных измерений не проводилось.
Из этих восьми запросов не следует устойчивый выигрыш параллельного backend.
Успех в таблице означает HTTP 200; качество независимо показано полным eval.

JSON приходит целиком: измерена полная задержка, TTFT и ITL не измерялись.
Надёжный p95 по этой выборке не заявляется. Prefill обрабатывает входной контекст;
decode последовательно добавляет выходные токены. KV-cache хранит ключи/значения
attention: больший контекст и больше активных последовательностей требуют памяти.
Объяснение механизма: https://huggingface.co/docs/transformers/kv_cache
Один последовательный Transformers backend с semaphore не измеряет SGLang/vLLM:
их планирование, batching и управление KV-памятью здесь не тестировались.
Документация механизма vLLM: https://docs.vllm.ai/en/latest/design/paged_attention/

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
behavioral, training index или протокол: полная оценка обеих версий в новых
--workspace/--evidence. Golden/eval не являются обучающими данными и сами по
себе не требуют обучения. Изменение train требует нового training run и eval.
```


Новый адаптер:

```text
Проверить FINISHED training run, получить artifact, точную базу и file hashes;
scripts/prepare_real.py --hw67 <project-with-selected-run> --workspace .real-adapter
  --evidence evidence/model-adapter
make real-candidate REAL_WORKSPACE=.real-adapter
Только после программного PASS обновлять принятый указатель, перезапускать API,
проверять /ready и идентификаторы. Новый адаптер проходит полную оценку.
```


Локальный CI выполнен. ci.example.yml — необязательный шаблон; удалённый
GitHub Actions не запускался, обязательная защита merge не заявляется.

## 10. Доступ, воспроизведение и ограничения

Команды выполняются из корня `hw8910-broken` и перечислены в [README.md](../README.md) и `Makefile`. Все исходные отчёты включены
маленькими файлами. Принятая baseline доступна публично по точной HF-ревизии.
Baseline: https://huggingface.co/Qwen/Qwen3-0.6B/tree/c1899de289a04d12100db370d81485cdf75e47ca
SHA256 model.safetensors: f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b.
Отклонённый адаптер доступен локально: .artifacts/model/artifacts/adapter,
либо MLflow http://127.0.0.1:5006, run cce6597824384cab8697bc597d7500c9, path model.
Загрузка из сохранённого artifact store:

```text
docker compose -f ../mlops26-hw6-7/hw67-broken/compose.yaml -p mlops-hw6 up -d
MLFLOW_TRACKING_URI=http://127.0.0.1:5006 .venv/bin/mlflow artifacts download --run-id cce6597824384cab8697bc597d7500c9 --artifact-path model --dst-path .artifacts
```

Для независимого запуска candidate-eval на другой машине потребуется доступ
к тому же artifact store или отдельная передача адаптера. Публичный адрес
кандидата не заявляется. Сохранённый gate пересчитывается из raw без весов.
Новая полная оценка выполняется в новых --workspace и --evidence.
 Веса, окружения, кеши и Docker volumes в Git
и материалы сдачи не включены; отправка и внешняя публикация не выполнялись.

Допущения: один писатель, локальная файловая система, явный restart; нет
автоматического hot reload и распределённого координатора. Прототипные A/B
проверяют процессы и версионность; реальное качество подтверждается отдельным
полным eval и настоящий backend отдельным smoke. Низкая baseline accuracy
сохраняется открыто. Замер мал и зависит от порядка/среды. Кластер, Docker image,
SGLang/vLLM, streaming и облачный CI не входят в обязательный объём.
Текущая версия сохраняется локальным Git-коммитом; отправка и внешняя публикация исключены пользователем.

Проверки: make check; make check-negative. Журналы — evidence/logs/.

Справка по использованным интерфейсам:

```text
Prefect tasks/cache/persist_result: https://reference.prefect.io/prefect/tasks/
FastAPI lifespan: https://fastapi.tiangolo.com/advanced/events/
```

