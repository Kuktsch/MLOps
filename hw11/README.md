# ДЗ 11. Сервис работает, пользователи ждут

Решение продолжает FastAPI-сервис ДЗ 8–10. Сборка берёт из предыдущей работы класс backend и проверку манифеста с SHA-256. API расширен NDJSON-потоком, управляемой очередью, LRU-кешем префиксов и метриками. Обязательные опыты используют `backend_mode=simulated`.

[Отчёт PDF](report.pdf) · [Отчёт HTML](report.html) · [Проверка требований](results/audit.md) · [Сырые запросы](results/requests.jsonl) · [Исходное задание](homework11.html)

## Запуск

Нужны Linux amd64, Docker с доступным демоном, Bash, curl и Python 3.12. Стенд использует отдельный кластер `kind-hw11` и локальный `hw11/.kubeconfig`. Для запуска из корня репозитория:

```bash
bash hw11/up.sh
export PATH="$PWD/hw11/.tools:$PATH"
export KUBECONFIG="$PWD/hw11/.kubeconfig"
kubectl -n hw11 get pods,svc
kubectl -n hw11 port-forward svc/api 8091:8091
```

В другом терминале:

```bash
curl -N http://127.0.0.1:8091/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Продолжи диалог","history":["Первое сообщение"],"chunks":4}'
```

Grafana доступна через `kubectl -n hw11 port-forward svc/grafana 3000:3000`, Prometheus через `kubectl -n hw11 port-forward svc/prometheus 9090:9090`. Обе команды по умолчанию слушают только loopback. В Grafana откройте дашборд **HW 11 / CPU inference**.

## Повтор опытов

Команды записывают данные в `hw11/results/`. В чистом checkout для повторов без перезаписи результатов сначала перенесите уже приложенный каталог `results` в другое место. A переустанавливает только релиз `hw11` в собственном кластере. C запускается после A. B использует отдельные пространства имён, каждый повтор занимает около 8 минут. Три повтора B можно выполнить параллельно.

```bash
python3.12 hw11/experiments.py a
python3.12 hw11/experiments.py b --repeat 1 &
p1=$!
python3.12 hw11/experiments.py b --repeat 2 &
p2=$!
python3.12 hw11/experiments.py b --repeat 3 &
p3=$!
wait "$p1" && wait "$p2" && wait "$p3"
python3.12 hw11/experiments.py c
bash hw11/measure-size.sh
git rev-parse HEAD > hw11/results/source-commit.txt

uv venv --python 3.12 hw11/.venv
uv pip sync --python hw11/.venv/bin/python hw11/requirements-report.txt
hw11/.venv/bin/python hw11/analyze.py
python3.12 hw11/report.py
```

Повторяемость сравнения задаётся расписанием входов. У каждой политики в паре одинаковые request shape, ограничения ответа и интервалы отправки. Новая группа ключей имитирует холодный кеш для измеряемых префиксов. Сопоставление ClientIP с Pod зависит от kube-proxy и может меняться при повторном создании стенда.

## Удаление

```bash
hw11/.tools/kind delete cluster --name hw11 --kubeconfig "$PWD/hw11/.kubeconfig"
docker image rm hw11-api:1.0.0 hw11-api:1.0.1
```

Первая команда удаляет кластер, временные тома, данные Prometheus и Grafana. Вторая удаляет локальный образ задания. Общие образы Docker остаются в кеше. Журналы и результаты на хосте остаются доступны.
