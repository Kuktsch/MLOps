"""Audit the raw traces and regenerate the submission figures and summaries."""

import collections
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
A, B, C = (RESULTS / name for name in ("a", "b", "c"))
FIGURES = ROOT / "figures"
COLORS = ("#007386", "#b84626", "#334a88", "#768942")


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def group(base, pattern):
    return [row for path in sorted(base.glob(pattern)) for row in read(path)]


def sample(path):
    return json.loads(path.read_text())["data"]["result"]


def percentile(values, probability):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * probability) - 1)] if values else None


def elapsed(row, first, last):
    return (row[last] - row[first]) / 1e6


def summary(rows):
    completed = [row for row in rows if row["outcome"] == "completed"]
    outcomes = collections.Counter(row["outcome"] for row in rows)
    interrupted = sum(row["status"] == 200 and row["outcome"] == "aborted" for row in rows)
    ttfc = [elapsed(row, "sent_ns", "first_ns") for row in completed]
    full = [elapsed(row, "sent_ns", "finished_ns") for row in completed]
    gaps = [(end - start) / 1e6 for row in completed
            for start, end in zip(row["fragment_ns"], row["fragment_ns"][1:])]
    queue = [row["queue_seconds"] * 1000 for row in completed if row.get("queue_seconds") is not None]
    lag = [elapsed(row, "planned_ns", "sent_ns") for row in rows if "planned_ns" in row]
    status = [row["status"] for row in rows if row.get("status") is not None]
    return dict(
        scheduled=sum("planned_ns" in row for row in rows), sent=len(rows),
        completed=len(completed), rejected=outcomes["rejected"], aborted=interrupted,
        transport_errors=outcomes["aborted"] - interrupted,
        timed_out=outcomes["timed_out"], http_5xx=sum(500 <= code < 600 for code in status),
        ttfc_p50=percentile(ttfc, .50), ttfc_p95=percentile(ttfc, .95),
        full_p50=percentile(full, .50), full_p95=percentile(full, .95),
        gap_p50=percentile(gaps, .50), gap_p95=percentile(gaps, .95),
        queue_p95=percentile(queue, .95), lag_p95=percentile(lag, .95), lag_max=max(lag, default=None),
        hit_rate=(sum(row["cache_hit"] == "true" for row in completed) / len(completed)) if completed else None,
    )


def tags(rows, by):
    return dict(collections.Counter(row.get(by) or "(без ответа)" for row in rows))


def planned(rows, spec):
    count = int(spec["duration"] * spec["rate"])
    assert len(rows) == count, (spec, len(rows), count)
    indexes = {row["seq"] for row in rows}
    assert indexes == set(range(count)), (spec["run"], indexes.symmetric_difference(range(count)))
    assert all(row["sent_ns"] >= row["planned_ns"] - 1_000_000 for row in rows), spec["run"]
    return sorted((row["seq"], row["client"], round(row["planned_epoch"] - spec["start"], 5),
                   {key: value for key, value in row["payload"].items() if key != "prefix"}) for row in rows)


def finish(fig, name):
    fig.tight_layout(pad=1.8)
    fig.savefig(FIGURES / name, dpi=165, facecolor="#ffffff", bbox_inches="tight")
    plt.close(fig)


def axis(ax, title, ylabel):
    ax.set_title(title, loc="left", fontweight="bold", fontsize=11)
    ax.set_ylabel(ylabel)
    ax.grid(True, axis="y", alpha=.22)
    ax.spines[["top", "right"]].set_visible(False)


def readiness(ax, trace, start, end):
    points = [line for line in trace if start <= line["epoch"] <= end]
    wall = [p["epoch"] - start for p in points]
    ready_counts = [sum(p["ready"] is not None and p["ready"]["status"] == "True" and p["deletion"] is None
                        for p in row["pods"].values()) for row in points]
    endpoints = [sum(e["conditions"]["ready"] for e in row["slices"].get("api", [])) for row in points]
    ax.step(wall, ready_counts, where="post", color=COLORS[0], lw=2.2, label="Pod Ready: без Terminating")
    ax.step(wall, endpoints, where="post", color=COLORS[1], ls="--", lw=1.4, label="EndpointSlice Ready")
    ax.set_yticks(range(4))


def experience_a():
    markers = read(A / "timeline.jsonl")
    timeline = read(A / "kube.jsonl")
    events = {m["event"]: m for m in markers}
    warmup = {m["mode"]: m["epoch"] for m in markers if m["event"] == "warmup_start"}
    bad, fixed = (read(A / f"warmup-{key}.jsonl") for key in ("bad", "fixed"))
    early = [row for row in bad if row.get("status") == 503 and row.get("ready") == "false"]
    assert early and not any(row.get("ready") == "false" for row in fixed)
    assert any(row["outcome"] == "completed" for row in fixed)
    windows = {}
    for mode, rows in (("bad", bad), ("fixed", fixed)):
        start = warmup[mode]
        relevant = [p for p in timeline if start <= p["epoch"] < start + 32]
        entered = next(p["epoch"] for p in relevant if any(
            e["conditions"]["ready"] for e in p["slices"].get("api", [])))
        first_success = min(row["sent_epoch"] for row in rows if row["outcome"] == "completed")
        windows[mode] = {"endpoint_after": entered - start, "success_after": first_success - start}

    rollout = group(A, "a-rollout-client-*.jsonl")
    planned(rollout, read(A / "runs.jsonl")[0])
    long = [read(A / f"rollout-long-{index}.jsonl")[-1] for index in range(2)]
    assert all(r["parts"] == 32 and r["outcome"] == "completed" for r in long)
    assert all(r["sent_epoch"] < events["rollout_a_to_b"]["epoch"] < r["finished_epoch"] for r in long)
    assert len(rollout) == 320 and all(r["status"] == 200 and r["outcome"] == "completed" for r in rollout)
    assert {r["version"] for r in rollout} == {"A", "B"}
    terminated_during_stream = []
    for row in long:
        deletion = [snap["epoch"] for snap in timeline
                    if snap["pods"].get(row["pod"], {}).get("deletion")]
        if deletion and deletion[0] < row["finished_epoch"]:
            terminated_during_stream.append(row["finished_epoch"] - deletion[0])
    assert terminated_during_stream
    unready = group(A, "a-unready-client-*.jsonl")
    planned(unready, read(A / "runs.jsonl")[1])
    assert len(unready) == 70 and all(r["version"] == "A" and r["outcome"] == "completed" for r in unready)
    excluded = [p for p in timeline if events["unready_b"]["epoch"] <= p["epoch"] <= events["rollback_to_a"]["epoch"]]
    assert any(pod["version"] == "B" and pod["ip"] for snap in excluded for pod in snap["pods"].values())
    assert any(not endpoint["conditions"]["ready"] and snap["pods"].get(
        endpoint.get("targetRef", {}).get("name"), {}).get("version") == "B"
        for snap in excluded for endpoint in snap["slices"].get("api", []))
    assert not any(endpoint["conditions"]["ready"] and snap["pods"].get(
        endpoint.get("targetRef", {}).get("name"), {}).get("version") == "B"
        for snap in excluded for endpoint in snap["slices"].get("api", []))

    forced = read(A / "check-forced-stream.jsonl")[-1]
    assert forced["outcome"] == "aborted" and 0 < forced["parts"] < 32
    detected = next(snap["epoch"] for snap in timeline
                    if events["sigkill"]["epoch"] <= snap["epoch"] <= events["restarted_ready"]["epoch"]
                    and (snap["pods"].get(forced["pod"], {}).get("ready") or {}).get("status") == "False"
                    and any(container.get("lastState", {}).get("terminated", {}).get("exitCode") == 137
                            for container in snap["pods"][forced["pod"]]["container"]))
    replacement, rollback, history = (read(A / f"check-{name}.jsonl")[0] for name in ("replacement", "rollback", "history"))
    assert replacement["version"] == rollback["version"] == "A"
    assert replacement["model_sha256"] == rollback["model_sha256"]
    assert replacement["pod"] == history["pod"] != forced["pod"] and history["text"] == "PREVIOUS-STATE | CONTINUED"
    assert {row["text"] for row in read(A / "check-dialogue.jsonl")} == {"BLUE-1 | BLUE-2", "ORANGE-1 | ORANGE-2"}
    overload = read(A / "check-overload.jsonl")
    assert any(r["outcome"] == "rejected" and r["status"] == 429 for r in overload)
    assert events["checks_passed"]

    fig, ax = plt.subplots(2, 2, figsize=(13, 7.3), gridspec_kw={"height_ratios": [1, 1]})
    for j, (mode, rows) in enumerate((("bad", bad), ("fixed", fixed))):
        start = warmup[mode]
        panel = ax[0, j]
        readiness(panel, timeline, start, start + 34)
        for status, label, color in [(503, "HTTP 503", COLORS[1]), (200, "HTTP 200", COLORS[0])]:
            points = [r["sent_epoch"] - start for r in rows if r["status"] == status]
            if points:
                panel.scatter(points, [-.35] * len(points), s=10, color=color, label=label)
        panel.set_xlim(0, 34)
        panel.set_xlabel("Секунды от установки профиля")
        axis(panel, "Ранняя готовность через /health" if mode == "bad" else "Готовность после прогрева", "Реплики, шт.")
        panel.legend(loc="center right", fontsize=7, frameon=True)
    start = events["rollout_a_to_b"]["epoch"]
    panel = ax[1, 0]
    readiness(panel, timeline, start, start + 62)
    for i, row in enumerate(long):
        panel.hlines(-.27 - i * .20, max(0, row["sent_epoch"] - start), row["finished_epoch"] - start,
                     color=COLORS[2], linewidth=2, label="Активный длинный поток A" if i == 0 else None)
    for version, color in zip(("A", "B"), COLORS):
        xs = [r["sent_epoch"] - start for r in rollout if r["version"] == version and r["sent_epoch"] >= start]
        panel.scatter(xs, [-.80] * len(xs), s=5, color=color, label=f"Ответ версии {version}")
    axis(panel, "Штатный rollout A → B при 5 запросах/с", "Реплики, шт.")
    panel.set_xlabel("Секунды от команды Helm upgrade")
    panel.legend(loc="center right", fontsize=7, frameon=True)
    start = events["unready_b"]["epoch"]
    panel = ax[1, 1]
    readiness(panel, timeline, start, start + 35)
    panel.axvline(events["rollback_to_a"]["epoch"] - start, color=COLORS[2], ls=":", label="Helm rollback")
    panel.scatter([r["sent_epoch"] - start for r in unready], [-.35] * len(unready), s=9, color=COLORS[0],
                  label="Ответы A")
    axis(panel, "Неготовая B и управляемый откат", "Реплики, шт.")
    panel.set_xlabel("Секунды от выпуска неготовой B")
    panel.legend(loc="center right", fontsize=7, frameon=True)
    finish(fig, "01-rollout.png")
    return {**windows, "early_503": len(early), "warmup_bad": summary(bad), "warmup_fixed": summary(fixed),
            "rollout": summary(rollout + long), "long_parts": [r["parts"] for r in long],
            "long_seconds": [elapsed(r, "sent_ns", "finished_ns") / 1000 for r in long],
            "drained_seconds": terminated_during_stream,
            "unready": summary(unready), "forced": summary([forced]), "forced_parts": forced["parts"],
            "forced_detail": forced.get("detail", "EOF до завершающего NDJSON-фрагмента"), "overload": summary(overload),
            "detected_seconds": detected - events["sigkill"]["epoch"],
            "restart_seconds": events["restarted_ready"]["epoch"] - events["sigkill"]["epoch"],
            "replacement_seconds": history["sent_epoch"] - events["replace_pod"]["epoch"],
            "rollback": rollback, "replacement": replacement}


def experience_b():
    runs, by_run = {}, {}
    for i in range(1, 4):
        base = B / f"repeat-{i}"
        specs = read(base / "runs.jsonl")
        assert len(specs) == 4
        fingerprints = {}
        mapping = {}
        for spec in specs:
            name = spec["run"]
            _, traffic, policy = name.split("-")
            rows = group(base, f"{name}-client-*.jsonl")
            data = planned(rows, spec)
            assert spec["duration"] == 120 and spec["rate"] == 8
            numbers = summary(rows)
            assert numbers["lag_p95"] < 100, (name, numbers["lag_p95"])
            if traffic in fingerprints:
                assert fingerprints[traffic] == data
            fingerprints[traffic] = data
            clients = {r["client"]: r["client_ip"] for r in rows}
            assert len(clients) == len(set(clients.values())) == 4
            owners = collections.Counter(r["client"] for r in rows)
            assert owners == ({0: 768, 1: 64, 2: 64, 3: 64} if traffic == "skew" else dict.fromkeys(range(4), 240))
            pods = tags(rows, "pod")
            assert len(pods) <= 2 and "(без ответа)" not in pods
            if policy == "sticky":
                for client in clients:
                    targets = {r["pod"] for r in rows if r["client"] == client}
                    assert len(targets) == 1, (name, client, targets)
                    mapping[client] = next(iter(targets))
            by_run[name] = rows
            runs[name] = {
                **numbers, "pods": pods, "clients": clients,
                "by_pod": {pod: summary([r for r in rows if r["pod"] == pod]) for pod in pods},
                "client_to_pod": mapping.copy() if policy == "sticky" else {},
            }
    hot_name = max((n for n in runs if n.endswith("skew-sticky")), key=lambda name: max(runs[name]["pods"].values()))
    plain_name = hot_name.replace("sticky", "plain")
    fig, axes = plt.subplots(2, 2, figsize=(13, 7.2), sharex=True)
    for j, name in enumerate((hot_name, plain_name)):
        rows = by_run[name]
        baseline = min(r["planned_epoch"] for r in rows)
        for i, pod in enumerate(sorted(runs[name]["pods"])):
            chosen = [r for r in rows if r["pod"] == pod and r["outcome"] == "completed"]
            x = [r["sent_epoch"] - baseline for r in chosen]
            label = pod.rsplit("-", 1)[-1]
            axes[0, j].scatter(x, [elapsed(r, "sent_ns", "first_ns") for r in chosen],
                               s=8, alpha=.5, color=COLORS[i], label=f"Pod {label}")
            axes[1, j].scatter(x, [r["queue_seconds"] * 1000 for r in chosen],
                               s=8, alpha=.5, color=COLORS[i], label=f"Pod {label}")
        axis(axes[0, j], "ClientIP, перекос 80/20" if j == 0 else "Без affinity, тот же поток 80/20", "TTFC, мс")
        axis(axes[1, j], "Ожидание слота", "Очередь, мс")
        axes[0, j].legend(frameon=False, fontsize=8)
        axes[1, j].set_xlabel(f"Секунды фазы · {name} · 8 запросов/с")
        for i in range(2):
            axes[i, j].set_ylim(bottom=0)
    for i in range(2):
        top = max(ax.get_ylim()[1] for ax in axes[i])
        for ax in axes[i]:
            ax.set_ylim(0, top)
    finish(fig, "02-queue-by-pod.png")
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    labels = ["Ровно\nClientIP", "Ровно\nбез affinity", "80/20\nClientIP", "80/20\nбез affinity"]
    combos = ["even-sticky", "even-plain", "skew-sticky", "skew-plain"]
    for panel, description, ylabel, metric in zip(
        axes, ("Задержка успешных ответов", "Доля отказов", "Доля на самом занятом Pod"),
        ("p95 TTFC, мс", "Доля HTTP отказов, %", "Доля запросов, %"),
        (lambda run: run["ttfc_p95"], lambda run: run["rejected"] / run["sent"] * 100,
         lambda run: max(run["pods"].values()) / run["sent"] * 100),
    ):
        for repeat in range(1, 4):
            x = [i + (repeat - 2) * .20 for i in range(4)]
            panel.bar(x, [metric(runs[f"b{repeat}-{key}"]) for key in combos], width=.19,
                      color=COLORS[repeat - 1], label=f"Повтор {repeat}")
        panel.set_xticks(range(4), labels, fontsize=8)
        axis(panel, description, ylabel)
    axes[0].legend(frameon=False, fontsize=8)
    finish(fig, "03-policy-repeats.png")
    return {"runs": runs, "hot_run": hot_name, "plain_run": plain_name}


def experience_c():
    trace = read(C / "kube.jsonl")
    events = {r["event"]: r for r in read(C / "timeline.jsonl")}
    specs = read(C / "runs.jsonl")
    hot = group(C, "c-sticky-cpu-client-*.jsonl")
    quiet = group(C, "c-quiet-comparison-client-*.jsonl")
    planned(hot, specs[0])
    planned(quiet, specs[1])
    third = events["third_ready"]["pod"]
    assert events["third_created"]["status"]["desiredReplicas"] == 3
    assert events["back_at_two"]["status"]["currentReplicas"] == 2
    after = [r for r in hot if r["sent_epoch"] >= events["third_ready"]["epoch"]]
    assert after and sum(r.get("pod") == third for r in after) < len(after) * .1
    alert_rows = read(C / "alerts.jsonl")
    alert_summary = {}
    for name in ("InferenceHighTTFC", "InferenceRejectedRequests"):
        states = [(row["epoch"], next((a["state"] for a in row["alerts"] if a["labels"]["alertname"] == name),
                                     "inactive")) for row in alert_rows]
        assert "firing" in dict(states).values() and "pending" in dict(states).values() and states[-1][1] == "inactive"
        end_of_firing = max(t for t, state in states if state == "firing")
        alert_summary[name] = {state: next(t for t, actual in states if actual == state and
                                          (state != "inactive" or t > end_of_firing)) - specs[0]["start"]
                               for state in ("pending", "firing", "inactive")}

    def scrape(edge):
        return {row["metric"]["pod"]: float(row["value"][1]) for row in sample(C / f"ttfc-scrape-{edge}.json")}

    starts, ends = scrape("start"), scrape("end")
    assert starts.keys() == ends.keys() and len(starts) == 2
    window = [r for r in quiet if r["outcome"] == "completed"
              and starts[r["pod"]] < r["finished_epoch"] <= ends[r["pod"]]]
    comparison = summary(window)
    prom_count = int(float(sample(C / "ttfc-prom-count.json")[0]["value"][1]))
    assert prom_count == comparison["completed"], (prom_count, comparison["completed"])
    targets = json.loads((C / "prometheus-targets.json").read_text())["data"]["activeTargets"]
    assert sum(t["labels"]["job"] == "api" and t["health"] == "up" for t in targets) == 2
    assert all(t["health"] == "up" for t in targets), targets
    dashboard = json.loads((C / "grafana-export.json").read_text())["dashboard"]
    assert dashboard["uid"] == "hw11-inference" and len(dashboard["panels"]) == 10

    start = events["idle"]["epoch"]
    end = events["back_at_two"]["epoch"] + 8
    fig, axes = plt.subplots(3, 1, figsize=(11.8, 8.5), sharex=True)
    readiness(axes[0], trace, start, end)
    samples = [r for r in trace if start <= r["epoch"] <= end and r.get("hpa", {}).get("status", {}).get("desiredReplicas")]
    axes[0].step([r["epoch"] - start for r in samples], [r["hpa"]["status"]["desiredReplicas"] for r in samples],
                 where="post", ls=":", color=COLORS[2], lw=1.6, label="HPA desired")
    axis(axes[0], "HPA autoscaling/v2 · целевой CPU 65% от requests", "Реплики, шт.")
    axes[0].legend(frameon=True, loc="center right", fontsize=8)
    for i, line in enumerate(sample(C / "prom-cpu.json")):
        points = [(t - start, float(value) * 1000) for t, value in line["values"] if start <= t <= end]
        if points:
            axes[1].plot(*zip(*points), lw=1.8, color=COLORS[i % len(COLORS)],
                         label=f"Pod {line['metric']['pod'].rsplit('-', 1)[-1]}")
    axes[1].axhline(130, color="#64748b", ls=":", label="65% × 200 mCPU")
    axis(axes[1], "CPU по Pod", "mCPU")
    axes[1].legend(frameon=False, loc="upper right", fontsize=8)
    bins = collections.Counter(int(r["sent_epoch"] - start) for r in hot)
    axes[2].step(range(int(end - start) + 1), [bins[i] for i in range(int(end - start) + 1)],
                 where="mid", color=COLORS[0])
    axis(axes[2], "Фактическая отправка · CPU-нагрузка через ClientIP", "Запросы/с")
    axes[2].set_xlabel("Секунды от начала наблюдения")
    for ax in axes:
        ax.axvline(events["third_ready"]["epoch"] - start, color=COLORS[2], ls="--", alpha=.65)
    finish(fig, "04-autoscaling.png")

    return {"hot": summary(hot), "quiet": summary(quiet), "after_ready": tags(after, "pod"),
            "all_hot_pods": tags(hot, "pod"), "new_pod": third,
            "create_seconds": events["third_created"]["epoch"] - specs[0]["start"],
            "ready_seconds": events["third_ready"]["epoch"] - events["third_created"]["epoch"],
            "back_seconds": events["back_at_two"]["epoch"] - events["load_finished"]["epoch"],
            "scale_status": events["third_created"]["status"], "alerts": alert_summary,
            "compare": comparison, "prom_count": prom_count, "scrape_start": starts, "scrape_end": ends,
            "prom_p50": float(sample(C / "ttfc-prom-p50.json")[0]["value"][1]) * 1000,
            "prom_p95": float(sample(C / "ttfc-prom-p95.json")[0]["value"][1]) * 1000}


def combined_requests():
    with (RESULTS / "requests.jsonl").open("w") as out:
        for path in sorted(RESULTS.glob("*/**/*.jsonl")):
            if path.name in {"kube.jsonl", "alerts.jsonl", "timeline.jsonl", "runs.jsonl"}:
                continue
            for row in read(path):
                if "request_id" in row and "signal" not in row:
                    out.write(json.dumps({**row, "source": str(path.relative_to(RESULTS))},
                                         ensure_ascii=False, allow_nan=False) + "\n")


if __name__ == "__main__":
    FIGURES.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.labelcolor": "#26354a",
                         "axes.titlecolor": "#182c43", "text.color": "#182c43"})
    output = {"a": experience_a(), "b": experience_b(), "c": experience_c()}
    combined_requests()
    (RESULTS / "summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
