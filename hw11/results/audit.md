# Проверка требований ДЗ 11

Ссылки ведут к результатам реальных запусков в kind. Для повторной машинной проверки используйте `hw11/.venv/bin/python hw11/analyze.py` из корня репозитория.

| Требование | Реализация и проверяемое доказательство |
|---|---|
| Сервис из ДЗ 8–10, локальный Kubernetes, HTTP, CPU-имитатор | [Dockerfile](../Dockerfile) повторно использует backend и проверку артефактов предыдущей работы. [Сервис](../service.py) выдаёт NDJSON и `backend_mode=simulated`. [Сведения о кластере](versions-network.txt). |
| Размеры, лимиты, версии и удаление | [До запуска](environment-before.txt), [после измерений](environment-after.txt), [контрольные суммы образов](../monitoring/images.lock), [зависимости](../requirements.txt) и [инструкция](../README.md). |
| Deployment, Service, ConfigMap, два Pod, Helm, CPU/RAM | [Шаблоны](../chart/templates), [values](../chart/values.yaml), [фактический Deployment в C](c/deployment.yaml). |
| Раздельные probes, прогрев, защита от ранних запросов | [HTTP до](a/warmup-bad.jsonl), [HTTP после](a/warmup-fixed.jsonl), [Ready и EndpointSlice](a/kube.jsonl), [логи исправленного API](a/warmup-fixed-server.log). |
| Закреплённая версия артефакта, повторная загрузка и продолжение диалога | [Манифесты](../models), [ответ новой реплики](a/check-replacement.jsonl), [продолжение истории](a/check-history.jsonl). |
| Request ID, Pod, реально загруженная версия и хеш | [Общий журнал HTTP](requests.jsonl), [серверный журнал A](a/final-server.log). |
| Prometheus обнаруживает реплики, Grafana и сохранённая конфигурация | [Конфигурация discovery](../monitoring/prometheus.yaml), [состояние целей](c/prometheus-targets.json), [экспорт из Grafana](c/grafana-export.json). |
| A: около 20 с прогрева и воспроизведение дефекта, затем исправление | [Отметки](a/timeline.jsonl) и [график](../figures/01-rollout.png). |
| A: стабильный rollout A→B и длинный поток во время обновления | [Длинный поток 0](a/rollout-long-0.jsonl), [длинный поток 1](a/rollout-long-1.jsonl), [запросы через Service](requests.jsonl), [Ready/Endpoints](a/kube.jsonl). Сводка подтверждает 0 HTTP 5xx и 0 обрывов. |
| A: неготовая B исключена, откат подтверждён клиентом | [Ошибка загрузки B](a/unready-b-server.log), [EndpointSlice](a/unready-b-endpoints.json), [HTTP после отката](a/check-rollback.jsonl). |
| A: принудительное завершение и восстановление | [Разрыв потока](a/check-forced-stream.jsonl), [CRΙ exit 137 и Ready](a/kube.jsonl), [время возврата](a/timeline.jsonl). Клиентский повтор учитывается отдельной попыткой, автоматические повторы выключены. |
| B: обычный Service и ClientIP над теми же Pod, четыре IP, keep-alive учтён | [Service и Pod в повторе 1](b/repeat-1), [настройки сети](versions-network.txt), [код клиента](../client.py), соответствие IP и Pod в [сводке](summary.json). |
| B: ровный трафик, затем 80/20, те же запросы и расписание | [Три повтора](b), [сопоставление последовательностей](../analyze.py), плановая и фактическая отправка в [JSONL](requests.jsonl). |
| B: имитация LRU, стоимость hit/miss, предел параллельности | [CPU backend](../service.py), [профиль](../chart/values.yaml), результаты hit/miss и очередь в [сводке](summary.json). |
| B: горячая реплика, свободная ёмкость, сохранён исход без перекоса | [График по Pod](../figures/02-queue-by-pod.png), [таблица прогона и фактическая маршрутизация](../report.html#b). |
| B: исправление и 3×120 с для каждой комбинации | [Четыре режима × три повтора](../figures/03-policy-repeats.png). [Отчёт](../report.html#b) обосновывает выбор по задержкам, отказам, распределению и локальности кеша. |
| C: autoscaling/v2 по CPU, Metrics API и requests | [Конфигурация и условия HPA](c/hpa.yaml), [Resource Metrics API](c/resource-api.json), [метрики контейнеров](c/resource-metrics-high.json), [Deployment](c/deployment.yaml). |
| C: 2→3→2, создание/Ready, фактическая задержка scale-down | [Линия времени](c/timeline.jsonl), [снимки HPA/Ready](c/kube.jsonl), [график с нагрузкой](../figures/04-autoscaling.png). |
| C: привязка после масштабирования и два алерта | [Доля по Pod](summary.json), [правила](../monitoring/alerts.yaml), [pending/firing/inactive](c/alerts.jsonl). |
| Измерения: монотонные часы, исходы и метаданные | [Код клиента](../client.py), [данные по запросу](requests.jsonl), [сводные p50/p95 и число ответов](summary.json). Полная методика TTFC, inter-chunk и формулы для реальной модели — [в отчёте](../report.html#measurements). |
| Classic Histogram, агрегация bucket с le, сопоставление с клиентом | [PromQL дашборда](../monitoring/promql.json), [границы scrape, счётчик и перцентили](c), [сопоставление](../report.html#measurements). |
| Дашборд: TTFC, полный ответ, running/waiting, RPS, ошибки, CPU/RAM, Ready | [Экспорт Grafana](c/grafana-export.json). Метки ограничены по набору, идентификаторы только в журнале. |
| Собственные проверки прогрева, отката, замены, отказов/обрыва и диалогов | [Проверки сервиса](../checks.py), [оркестрация](../experiments.py), [записи проверок](a) и [повторная валидация сырых данных](../analyze.py). Изоляция дополнительно проверена [на одном Pod](a/check-dialogue-same-pod.json). |
| Ревью PR с кейсом лекции и первоисточником | [Ревью PR «Постоянная привязка диалога к Pod»](../report.html#review) и [первичный кейс Google Cloud](https://cloud.google.com/blog/products/containers-kubernetes/how-gke-inference-gateway-improved-latency-for-vertex-ai). |
| Репозиторий, коммит, отчёт, инструкция, сырые файлы, 4 графика | [Состав сдачи](../README.md), [коммит исходников](source-commit.txt), отчёт [PDF](../report.pdf) и [HTML](../report.html), [графики](../figures), [сырые HTTP-попытки](requests.jsonl). Ссылка на коммит станет доступна на GitHub после публикации ветки. |

Дополнительный опыт с настоящими весами или готовой cache-aware политикой не входит в обязательную часть. Численные результаты относятся к CPU-имитатору.
