"""Build the submission report from verified runs."""

import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
REPO = "https://github.com/Kuktsch/MLOps"
MSK = timezone(timedelta(hours=3))


def num(value, places=1):
    return "—" if value is None else f"{value:.{places}f}".replace(".", ",")


def percent(part, whole):
    return num(part / whole * 100) + "%"


def table(headers, rows):
    def cells(row, name):
        return "<tr>" + "".join(f"<{name}>{html.escape(str(value))}</{name}>" for value in row) + "</tr>"

    return ("<div class='table'><table><thead>" + cells(headers, "th") + "</thead><tbody>"
            + "".join(cells(row, "td") for row in rows) + "</tbody></table></div>")


def figure(file, text):
    return (f'<figure><a class="plot" href="figures/{file}" target="_blank" rel="noopener">'
            f'<img src="figures/{file}" alt="{text}"></a><figcaption>{text}</figcaption></figure>')


def time_at(epoch):
    return datetime.fromtimestamp(epoch, MSK).strftime("%H:%M:%S.%f")[:-3]


def request_row(label, data):
    return (label, data["scheduled"] or "—", data["sent"], data["completed"], data["rejected"], data["aborted"],
            data["transport_errors"], data["timed_out"], data["http_5xx"], num(data["ttfc_p50"]), num(data["ttfc_p95"]),
            num(data["full_p50"]), num(data["full_p95"]))


def render():
    data = json.loads((RESULTS / "summary.json").read_text())
    a, b, c = (data[key] for key in "abc")
    source = (RESULTS / "source-commit.txt").read_text().strip()
    sizing = json.loads((RESULTS / "size.json").read_text())
    case = (ROOT / "review.html").read_text()
    run_rows = []
    for name, run in b["runs"].items():
        repeat, traffic, policy = name.split("-")
        run_rows.append((repeat[1:], "80/20" if traffic == "skew" else "25/25/25/25",
                         "ClientIP" if policy == "sticky" else "None",
                         " / ".join(map(str, sorted(run["pods"].values(), reverse=True))), run["completed"],
                         f'{run["rejected"]} ({percent(run["rejected"], run["sent"])})',
                         num(run["ttfc_p50"]), num(run["ttfc_p95"]), num(run["full_p50"]), num(run["full_p95"]),
                         percent(run["hit_rate"], 1), num(run["lag_p95"])))
    hot = b["runs"][b["hot_run"]]
    plain = b["runs"][b["plain_run"]]
    per_pod = [
        (tag, pod, run["pods"][pod], metrics["completed"], metrics["rejected"],
         num(metrics["ttfc_p50"]), num(metrics["ttfc_p95"]), num(metrics["queue_p95"]))
        for tag, run in (("ClientIP", hot), ("None", plain)) for pod, metrics in run["by_pod"].items()
    ]
    balanced = min((run for name, run in b["runs"].items() if name.endswith("even-sticky")),
                   key=lambda run: max(run["pods"].values()))
    ip_map = ", ".join(f'{balanced["clients"][i]} → {pod.rsplit("-", 1)[-1]}'
                       for i, pod in balanced["client_to_pod"].items())
    sticky_percentiles = [b["runs"][f"b{i}-skew-sticky"]["ttfc_p95"] for i in (1, 2, 3)]
    plain_percentiles = [b["runs"][f"b{i}-skew-plain"]["ttfc_p95"] for i in (1, 2, 3)]
    alert_rows = [(name, *(num(states[status]) for status in ("pending", "firing", "inactive")))
                  for name, states in c["alerts"].items()]
    bounds = [(pod, time_at(start), time_at(c["scrape_end"][pod])) for pod, start in c["scrape_start"].items()]
    client = c["compare"]
    count_gap = c["prom_count"] - client["completed"]

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ДЗ 11 · Kubernetes под нагрузкой</title>
<style>
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;background:#edf2f6;color:#203049;font:16px/1.55 system-ui,sans-serif}}
main{{max-width:1140px;margin:0 auto;background:#fff;padding:38px clamp(18px,4vw,58px) 60px}}
h1,h2,h3{{line-height:1.19;color:#172e49}}
h1{{font-size:clamp(32px,6vw,52px);margin:.3em 0}}
h2{{font-size:29px;margin:1.7em 0 .6em}}
h3{{margin:1.4em 0 .45em}}
a{{color:#006879}}
nav{{display:flex;flex-wrap:wrap;gap:8px 16px;margin:28px 0;border-block:1px solid #dce7ef;padding:14px 0}}
figure{{margin:22px 0 28px}}
.plot{{display:block;cursor:zoom-in}}
img{{max-width:100%;height:auto;display:block;border:1px solid #e1e9ef}}
figcaption,small{{color:#506078}}
p{{max-width:91ch}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;padding:9px;border-bottom:1px solid #dce7ef}}
th{{background:#edf3f7}}
.table{{overflow:auto}}
pre{{overflow:auto;background:#edf3f7;padding:14px}}
code{{overflow-wrap:anywhere}}
@page{{size:A4;margin:13mm 14mm 16mm;@bottom-right{{content:counter(page);color:#506078;font-size:9pt}}}}
@media print{{
  body{{background:#fff;font:10pt/1.4 "DejaVu Sans",sans-serif}}
  main{{max-width:none;padding:0}}
  nav,.pdf-link{{display:none}}
  h1{{font-size:25pt}}h2{{font-size:17pt}}h3{{font-size:12pt}}
  h2,h3{{break-after:avoid}}
  figure,tr{{break-inside:avoid}}
  figure{{margin:10pt 0}}
  .table{{overflow:visible}}
  table{{font-size:7pt;line-height:1.2}}
  th,td{{padding:4pt 2.5pt;overflow-wrap:anywhere}}
  pre{{padding:6pt;white-space:pre-wrap}}
}}
</style></head><body><main>
<small>МГТУ · MLOPS-26 · 14 ноября 2026</small>
<h1>ДЗ 11. Сервис работает, пользователи ждут</h1>
<p>FastAPI из ДЗ 8–10 в одноузловом kind. Две реплики, поток NDJSON, CPU-имитатор <code>backend_mode=simulated</code>.</p>
<p><a href="{REPO}">Репозиторий GitHub</a> · Коммит исходников <code>{html.escape(source)}</code> · <a href="README.md">Запуск и удаление</a><span class="pdf-link"> · <a href="report.pdf">Открыть PDF</a></span></p>
<nav aria-label="Разделы отчёта"><a href="#stand">Стенд</a><a href="#a">Прогрев и выпуск</a><a href="#b">Привязка к Pod</a><a href="#c">HPA и алерты</a><a href="#measurements">Методика</a><a href="#review">Ревью PR</a><a href="results/audit.md">Проверка требований</a></nav>
<section id="stand">
<h2>Стенд</h2>
<p>Docker Desktop 4.75.0, Docker Engine 29.5.2, 8 CPU и 15,59 GiB RAM, kind 0.27.0, Kubernetes 1.32.2, Helm 3.18.4. Перед запуском проверено, что свободного места достаточно для стенда. Параметры API закреплены в Helm. На один Pod запрошено 200 mCPU и 96 MiB, лимиты — 850 mCPU, 192 MiB и 128 MiB временного диска. Prometheus 3.3.1 хранит до 6 ч и до 96 MB блоков на томе до 128 MiB, том Grafana 11.6.1 ограничен 64 MiB. Есть отдельные лимиты для клиентских Pod, Prometheus, Grafana и kube-state-metrics.</p>
<p>Образ API занимает {num(sizing["api_mib"])} MiB по Docker inspect, каталог containerd узла — {html.escape(sizing["containerd"])}, данные Prometheus — {html.escape(sizing["prometheus"])}, Grafana — {html.escape(sizing["grafana"])}. Прирост Docker volumes составил около {num(sizing["volume_delta_gb"], 2)} GB. Каталог containerd уже входит в Docker volume. Оценка для удаления собственного узла и его volume — около 3 GB плюс локальный кеш образов. <a href="results/environment-before.txt">До запуска</a> · <a href="results/environment-after.txt">Фактические размеры и список Pod</a> · <a href="monitoring/images.lock">Дайджесты образов</a></p>
<p>Версии имитатора A и B хранятся в образе. При старте сервис читает манифест и проверяет SHA-256 файла тем же кодом, что и в ДЗ 8–10. A после отката и на новом Pod вернула один SHA-256 <code>{a["rollback"]["model_sha256"]}</code>. В заголовках и журналах запроса сохраняются request ID, имя Pod и загруженная версия. История приходит в теле запроса. <a href="models/">Артефакты</a> · <a href="results/a/check-rollback.jsonl">Ответ после отката</a> · <a href="results/a/check-replacement.jsonl">Ответ новой реплики</a></p>
</section>
<section id="a">
<h2>A. Прогрев, штатное обновление и откат</h2>
<p><strong>Гипотеза.</strong> HTTP-процесс принимает соединение раньше, чем проверен и прогрет backend. Сначала startup и readiness направлены на <code>/health</code>. При 20 с заданного прогрева первый готовый endpoint появился через {num(a["bad"]["endpoint_after"])} с после установки профиля. Сервис получил {a["early_503"]} запросов на непрогретый backend и вернул 503. После разделения probes первый готовый endpoint виден через {num(a["fixed"]["endpoint_after"])} с, запросов к непрогретому backend стало 0. Пока у Service не было готовых endpoint, контрольные вызовы получили TCP-отказ до HTTP, что видно по отсутствию статуса в журнале.</p>
<p><code>/startup</code> проверяет завершение первичного прогрева и допускает до 45 с на старте профиля. <code>/ready</code> проверяет пригодность загруженной версии к трафику. <code>/health</code> используется liveness для проверки живого процесса. Снимки Kubernetes сняты опросом, поэтому первый зафиксированный Ready может отставать от первого успешного HTTP-ответа примерно на интервал опроса.</p>
<p>При A→B запущено по одному 32-фрагментному потоку на каждую старую реплику. Оба пережили начало обновления, длительность составила {num(a["long_seconds"][0], 2)} и {num(a["long_seconds"][1], 2)} с. Один поток завершился через {num(a["drained_seconds"][0], 2)} с после того, как его Pod был замечен в Terminating. Первая новая B прогревалась рядом с двумя A. <code>maxSurge=1</code>, <code>maxUnavailable=0</code>, <code>minReadySeconds=2</code>. При удалении Pod пауза <code>preStop</code> 3 с даёт время обновить маршруты. Uvicorn завершает активные ответы с тайм-аутом 32 с в пределах Kubernetes grace period 45 с. Все 322 попытки завершились с HTTP 200, включая 320 запросов через Service и два длинных потока напрямую к старым Pod.</p>
<p>После возврата к A выпущена B с инъекцией ошибки загрузки. B появилась в EndpointSlice с <code>ready=false</code>, все 70 фоновых запросов отдали A. После <code>helm rollback</code> отдельная проверка получила A с фактическим хешем. При принудительной остановке контейнера через CRI клиент успел получить {a["forced_parts"]} из 32 фрагментов и зафиксировал незавершённый поток. Состояние Ready=false и exit 137 обнаружены через {num(a["detected_seconds"])} с. Тот же Pod снова Ready через {num(a["restart_seconds"])} с. После удаления Pod история <code>PREVIOUS-STATE | CONTINUED</code> и SHA-256 версии A подтверждены ответом новой реплики через {num(a["replacement_seconds"])} с после команды. Повторов на уровне HTTP-клиента в этих опытах не было.</p>
{figure("01-rollout.png", "Рисунок 1. Прогрев, Ready и EndpointSlice по времени, штатный rollout и откат.")}
<p><a href="results/a/kube.jsonl">Снимки Pod и EndpointSlice</a> · <a href="results/a/timeline.jsonl">Команды и отметки времени</a> · <a href="results/a/unready-b-server.log">Ошибка загрузки B</a> · <a href="results/a/check-forced-stream.jsonl">Обрыв потока и фрагменты</a></p>
<p><strong>Граница проверки.</strong> Нулевой 5xx подтверждён для 5 запросов/с, клиентского тайм-аута 40 с и двух потоков продолжительностью около 30,5 с. Жёсткая остановка обходится без graceful shutdown.</p>
</section>
<section id="b">
<h2>B. Привязка к Pod и горячая реплика</h2>
<p><strong>Гипотеза.</strong> <code>ClientIP</code> концентрирует трафик большого клиента и может заполнить очередь, пока у второй реплики есть слоты. Сравнивались два ClusterIP Service над той же парой Pod, через kube-proxy в режиме iptables. Клиенты внутри кластера имеют четыре IP. Каждая попытка создаёт новый TCP-сеанс с <code>Connection: close</code>. IP в журнале backend совпадает с Pod IP клиента. Профиль <code>even</code> даёт 240 запросов на клиента, <code>skew</code> — 768 для клиента 0 и по 64 для трёх остальных.</p>
<p>В каждой комбинации 3 прогона по 120 с, 8 запросов/с и 960 попыток. Входы одинаковой длины, по четыре фрагмента с интервалом 45 мс. У реплики один слот, очередь до 12 ожидающих и тайм-аут 3 с. Локальный LRU хранит до восьми префиксов, задержка hit/miss — 8/60 мс. Pod прогреты к старту, префиксы каждой фазы новые. Расписание идентично в паре, задержка отправки проверена отдельно. Пилот выявил насыщение пула клиента по отставанию от плана, после чего выделили 96 рабочих потоков на клиент и повторили всю матрицу.</p>
{table(("Повтор", "Трафик", "Affinity", "Запросов по Pod", "Успешно", "HTTP отказов",
        "TTFC p50, мс", "TTFC p95, мс", "Полный p50, мс", "Полный p95, мс", "Cache hit¹", "Отставание p95, мс"), run_rows)}
<p><small>¹ Доля попаданий среди полных ответов. В каждом прогоне 960 отправок, 0 тайм-аутов и 0 обрывов. Плановая доля горячего клиента относится к отправкам, а доля по Pod учитывает и HTTP-отказы.</small></p>
<p>В профиле B с максимальным перекосом выбран прогон <code>{b["hot_run"]}</code>. Покажем очередь и TTFC по двум Pod для него и для того же расписания на исправленной конфигурации. При равномерном профиле сохранён и случай без перекоса: {list(sorted(balanced["pods"].values()))}. Его ClientIP-трасса: {html.escape(ip_map)}. По два клиента попали на каждую реплику.</p>
{table(("Политика", "Pod", "Попыток", "Успешно", "Отказов", "TTFC p50, мс", "TTFC p95, мс", "Очередь p95, мс"), per_pod)}
{figure("02-queue-by-pod.png", "Рисунок 2. TTFC и время ожидания слота по Pod под перекосом 80/20.")}
{figure("03-policy-repeats.png", "Рисунок 3. Двенадцать прогонов по 120 секунд и разброс результатов.")}
<p><strong>Изменение.</strong> Для этого трафика выбрали Service без ClientIP. p95 TTFC под перекосом менялся от {num(min(sticky_percentiles))} до {num(max(sticky_percentiles))} мс с ClientIP и от {num(min(plain_percentiles))} до {num(max(plain_percentiles))} мс после изменения. В показанной паре отказов {hot["rejected"]} и {plain["rejected"]}, доля попаданий у успешных ответов {percent(hot["hit_rate"], 1)} и {percent(plain["hit_rate"], 1)}. Каждый горячий префикс после начальных промахов способен прогреться на обеих репликах. Здесь ключей мало, кеш мал и его модель упрощена. На inference engine нужны отдельные замеры KV-cache, пересчёта длинных префиксов, TTFT, TPOT, распределения по Pod и churn кеша при масштабировании. <a href="results/b/">Сырые журналы всех трёх повторов и конфигурации Service</a></p>
</section>
<section id="c">
<h2>C. CPU, HPA и мониторинг</h2>
<p><strong>Гипотеза.</strong> Автомасштабирование по средней CPU срабатывает при достаточной суммарной нагрузке. Дополнительный Pod может простаивать, пока источник остаётся привязан к старому. HPA <code>autoscaling/v2</code> использует Metrics Server 0.7.2, CPU requests по 200 mCPU, цель 65%, минимум 2 и максимум 3. При двух равных requests порог соответствует примерно 260 mCPU суммарно, с поправкой на допуск и алгоритм HPA. Если горячий Pod потребляет 200 mCPU, а второй почти простаивает, среднее около 50% даже при очереди.</p>
<p>Один клиент послал 9 запросов/с через ClientIP в течение 115 с. Вычислительная нагрузка — PBKDF2-HMAC-SHA256 по 320&nbsp;000 итераций на фрагмент, четыре фрагмента на запрос. HPA запросил 3 реплики при CPU {c["scale_status"]["currentMetrics"][0]["resource"]["current"]["averageUtilization"]}%. Третий Pod появился через {num(c["create_seconds"])} с от запланированного начала, затем прогрелся и стал Ready через {num(c["ready_seconds"])} с. Трафик после его готовности по Pod: {html.escape(str(c["after_ready"]))}. Новая реплика <code>{c["new_pod"]}</code> получила {c["after_ready"].get(c["new_pod"], 0)} запросов при сохранённой привязке. После окончания запросов HPA вернулся к минимуму через {num(c["back_seconds"])} с. Окно стабилизации задано 45 с, снаружи к нему добавляются периоды Metrics Server и контроллера. После возврата повторили контрольный лёгкий профиль через обычный Service.</p>
{figure("04-autoscaling.png", "Рисунок 4. Переход 2→3→2, CPU по Pod и фактическая нагрузка.")}
<p>Prometheus обнаруживает каждый API Pod отдельно, CAdvisor отдаёт CPU и RAM, kube-state-metrics отдаёт Ready по Kubernetes. Алерты проверяют окно 30 с, минимум 10 наблюдений и удержание 15 с. Пороги — p95 TTFC &gt; 650 мс и доля HTTP-отказов &gt; 10% среди терминальных исходов. Ниже показаны переходы от начала отправки CPU-профиля. Время перехода измерено с точностью опроса.</p>
{table(("Алерт", "Pending, с", "Firing, с", "Снова inactive, с"), alert_rows)}
<p><a href="results/c/hpa.yaml">HPA</a> · <a href="results/c/resource-api.json">Resource Metrics API</a> · <a href="results/c/alerts.jsonl">Переходы алертов</a> · <a href="results/c/prometheus-targets.json">Состояние целей Prometheus</a> · <a href="results/c/grafana-export.json">Дашборд, выгруженный из Grafana</a></p>
</section>
<section id="measurements">
<h2>Что измерено</h2>
<p>На клиенте <code>time.monotonic_ns()</code> фиксирует плановую отправку, начало HTTP-попытки, первый содержательный NDJSON-фрагмент, каждый промежуточный фрагмент и завершение. TTFC = первый фрагмент минус отправка. Полный ответ — завершение минус отправка. Межфрагментная задержка считается между соседними частями. У ответа из одной части она отсутствует. Клиент считает поток полным при получении корректного <code>done</code> и ожидаемого числа частей. EOF без <code>done</code> — обрыв, HTTP не 200 — отказ, тайм-аут фиксируется отдельно. Перед стартом TCP отсутствие доступного endpoint обозначено как транспортная ошибка с пустым HTTP-статусом. Для асинхронного опроса и сопоставления с сервером хранится и epoch.</p>
{table(("Фаза", "По плану", "Отправлено", "Завершено", "Отказ", "Обрыв HTTP 200", "Транспортная ошибка", "Тайм-аут", "HTTP 5xx",
        "TTFC p50, мс", "TTFC p95, мс", "Полный p50, мс", "Полный p95, мс"),
        [request_row(label, run) for label, run in (("Ранний Ready", a["warmup_bad"]),
            ("Исправленный Ready", a["warmup_fixed"]), ("Штатный rollout", a["rollout"]), ("Неготовая B", a["unready"]),
            ("Принудительная остановка", a["forced"]),
            ("Ограничение очереди", a["overload"]), ("CPU / ClientIP", c["hot"]), ("Контроль C", c["quiet"]))])}
<p>Отдельно для тихого профиля C межфрагментная задержка p50/p95 равна {num(c["quiet"]["gap_p50"])} / {num(c["quiet"]["gap_p95"])} мс. В B и C метрики имитатора выражены в миллисекундах на части ответа. Для проверки на реальном backend TTFT идёт до первого содержательного токена. TPOT = (время последнего токена − время первого) / (N−1), где N — число выходных токенов фактического tokenizer inference engine. При N=1 TPOT отсутствует. N можно получить из токенизированного префикса/окончания с фиксированной версией tokenizer или непосредственно из идентификаторов, возвращаемых engine. Подключение настоящих весов и соответствующие измерения относятся к дополнительному опыту.</p>
<h3>Клиент и Prometheus в одном контрольном окне</h3>
<p>Для выбранного 30-секундного окна взяли разность накопленных bucket-счётчиков двух снимков без рестартов, сохранили <code>le</code> и сложили по Pod. Реальные границы scrape для каждого Pod сопоставлены с клиентским журналом по времени завершения только успешных запросов. Во временных рядах дашборда используется <code>rate(...[30s])</code> с агрегацией <code>sum by (pod, le)</code>. Request ID и session ID хранятся в журнале, а метки ограничены Pod и исходом запроса.</p>
<pre>histogram_quantile(0.95, sum by (le) (
  api_ttfc_seconds_bucket - api_ttfc_seconds_bucket offset 30s
))</pre>
{table(("Pod", "Начальный scrape (МСК)", "Конечный scrape (МСК)"), bounds)}
{table(("Источник TTFC", "Число ответов", "p50, мс", "p95, мс"), (
    ("Клиент", client["completed"], num(client["ttfc_p50"]), num(client["ttfc_p95"])),
    ("Prometheus", c["prom_count"], num(c["prom_p50"]), num(c["prom_p95"])),
))}
<p>Разность числа наблюдений Prometheus и клиента: {count_gap}. Сервер измеряет время от входа в обработчик до отправки первого фрагмента, клиент включает транспорт, а Prometheus интерполирует внутри bucket. Поэтому перцентили могут расходиться при близком или одинаковом объёме выборки. <a href="monitoring/promql.json">PromQL всех панелей</a> · <a href="results/requests.jsonl">Общий JSONL с сырыми попытками</a></p>
</section>
<section>
<h2>Собственные проверки</h2>
<ol>
<li>Ранняя готовность воспроизводится, после исправления запрос непрогретой реплике через Service не проходит. <a href="results/a/warmup-bad.jsonl">До</a> · <a href="results/a/warmup-fixed.jsonl">После</a></li>
<li>После управляемого отката Kubernetes API-сервис отвечает с версией A и ожидаемым SHA-256. <a href="results/a/check-rollback.jsonl">Результат</a></li>
<li>После замены Pod подтверждены новое имя, готовность, версия A, прежний хеш и продолжение диалога. <a href="results/a/check-replacement.jsonl">Артефакт</a> · <a href="results/a/check-history.jsonl">Диалог</a></li>
<li>Отклонённые попытки получают 429. Поток с HTTP 200 и одним фрагментом классифицирован как обрыв после принудительной остановки. <a href="results/a/check-overload.jsonl">429</a> · <a href="results/a/check-forced-stream.jsonl">Обрыв</a></li>
<li>Два параллельных диалога на одном Pod вернули <code>BLUE-1 | BLUE-2</code> и <code>ORANGE-1 | ORANGE-2</code>. <a href="results/a/check-dialogue-same-pod.json">Результат</a></li>
</ol>
</section>
{case}
</main></body></html>
"""


if __name__ == "__main__":
    (ROOT / "report.html").write_text(render())
