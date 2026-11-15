"""Run and record the Kubernetes experiments against the isolated hw11 kind cluster."""

import argparse
import contextlib
import concurrent.futures
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
KUBE = ["kubectl", "--kubeconfig", str(ROOT / ".kubeconfig")]
HELM = os.environ.get("HW11_HELM", "helm")
NS = "hw11"
TARGET = "http://api:8091"


def command(args, **kwargs):
    result = subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, **kwargs)
    return result.stdout


def k(namespace, *args):
    return command([*KUBE, "-n", namespace, *args])


def h(namespace, *args):
    return command([HELM, "--kubeconfig", str(ROOT / ".kubeconfig"), "-n", namespace, *args])


def record(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        out.write(json.dumps(value, ensure_ascii=False) + "\n")


def save(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)


def setup(namespace, **values):
    overrides = [value for key, val in values.items() for value in ("--set", f"{key}={val}")]
    return h(namespace, "upgrade", "--install", "hw11", str(ROOT / "chart"), "--history-max", "10", *overrides)


def wait_ready(namespace):
    return k(namespace, "rollout", "status", "deployment/api", "--timeout=150s")


def until(predicate, timeout, description, period=.75):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(period)
    raise TimeoutError(description)


def snapshot(namespace, include_hpa=False):
    kinds = "pods,endpointslices" + (",hpa" if include_hpa else "")
    obj = json.loads(k(namespace, "get", kinds, "-o", "json"))
    snap = {"epoch": time.time(), "pods": {}, "slices": {}}
    for item in obj["items"]:
        name, spec, status = item["metadata"]["name"], item.get("spec", {}), item.get("status", {})
        if item["kind"] == "Pod" and item["metadata"]["labels"].get("app") == "hw11-api":
            container = spec["containers"][0]
            snap["pods"][name] = {
                "created": item["metadata"]["creationTimestamp"],
                "ready": next((c for c in status.get("conditions", []) if c["type"] == "Ready"), None),
                "deletion": item["metadata"].get("deletionTimestamp"), "ip": status.get("podIP"),
                "version": next(e["value"] for e in container["env"] if e["name"] == "MODEL_VERSION"),
                "container": status.get("containerStatuses", []),
            }
        elif item["kind"] == "EndpointSlice":
            service = item["metadata"]["labels"]["kubernetes.io/service-name"]
            if service in ("api", "api-sticky"):
                snap["slices"].setdefault(service, []).extend(item.get("endpoints") or [])
        elif item["kind"] == "HorizontalPodAutoscaler":
            snap["hpa"] = {"spec": spec, "status": status}
    return snap


def poller(namespace, path, stop, include_hpa=False):
    while not stop.wait(.65):
        record(path, snapshot(namespace, include_hpa))


@contextlib.contextmanager
def watch(pool, namespace, path, hpa=False):
    from threading import Event

    stop = Event()
    future = pool.submit(poller, namespace, path, stop, hpa)
    try:
        yield
    finally:
        stop.set()
        future.result()


def check(namespace, path, name, target=TARGET, *args):
    data = k(namespace, "exec", "client-0", "--", "python", "/app/checks.py", name, target, *args)
    save(path, data)
    return [json.loads(line) for line in data.splitlines()]


def wait_check_started(path):
    def read():
        if path.exists():
            contents = path.read_text().splitlines()
            if contents:
                return json.loads(contents[0])

    row = until(read, 12, "long stream never sent its first fragment", .15)
    assert row["signal"] == "first_fragment", row
    return row


def long_stream(namespace, path, target, label):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as out:
        return subprocess.Popen([*KUBE, "-n", namespace, "exec", "client-0", "--", "python",
                                 "/app/checks.py", "stream", target, "--label", label], stdout=out, text=True)


def load(pool, namespace, directory, run, target=TARGET, **options):
    start = round(time.time() + 2.5, 3)
    record(directory / "runs.jsonl", {"run": run, "target": target, "start": start, **options})
    directory.mkdir(parents=True, exist_ok=True)

    def worker(client):
        args = [arg for name, val in options.items() for arg in ("--" + name.replace("_", "-"), str(val))]
        cmd = [*KUBE, "-n", namespace, "exec", f"client-{client}", "--", "python", "/app/client.py",
               "--client", str(client), "--run", run, "--start", str(start), "--target", target,
               "--cache-epoch", run[:90], *args]
        with (directory / f"{run}-client-{client}.jsonl").open("w") as out:
            subprocess.run(cmd, check=True, stdout=out, text=True)

    return [pool.submit(worker, client) for client in range(4)]


def join(jobs):
    for job in jobs:
        job.result()


def logs(namespace, path):
    return save(path, k(namespace, "logs", "-l", "app=hw11-api", "--all-containers", "--prefix",
                        "--tail=-1", "--max-log-requests=8"))


def mark(path, event, **kwargs):
    record(path, {"event": event, "epoch": time.time(), **kwargs})


def model_hash(version):
    return next(iter(json.loads((ROOT / f"models/manifest-{version.lower()}.json").read_text())["file_hashes"].values()))


def experiment_a():
    out = RESULTS / "a"
    trace = out / "timeline.jsonl"
    with concurrent.futures.ThreadPoolExecutor(10) as pool, watch(pool, NS, out / "kube.jsonl"):
        if h(NS, "list", "--filter", "^hw11$", "--short").strip():
            h(NS, "uninstall", "hw11", "--wait", "--timeout", "70s")
        for defective in (True, False):
            mode = "bad" if defective else "fixed"
            if not defective:
                k(NS, "scale", "deploy/api", "--replicas=0")
                until(lambda: not snapshot(NS)["pods"], 65, "old pods not deleted")
            mark(trace, "warmup_start", mode=mode)
            setup(NS, earlyProbes=str(defective).lower(), maxParallel=2)
            check(NS, out / f"warmup-{mode}.jsonl", "warmup", TARGET, *(["--expect-early"] if defective else []))
            wait_ready(NS)
            logs(NS, out / f"warmup-{mode}-server.log")
            mark(trace, "warmup_verified", mode=mode)

        rollout_load = load(pool, NS, out, "a-rollout", duration=64, rate=5, traffic="even")
        old = snapshot(NS)["pods"]
        streams = []
        for i, (pod, state) in enumerate(old.items()):
            path = out / f"rollout-long-{i}.jsonl"
            streams.append((path, long_stream(NS, path, f"http://{state['ip']}:8091", f"a-rollout-long-{i}")))
        first = [wait_check_started(path) for path, _ in streams]
        mark(trace, "rollout_a_to_b", stream_pods=[row["pod"] for row in first])
        setup(NS, modelVersion="B", maxParallel=2)
        for path, stream in streams:
            assert stream.wait(38) == 0
            long_row = json.loads(path.read_text().splitlines()[-1])
            assert long_row["outcome"] == "completed" and long_row["parts"] == 32, long_row
        wait_ready(NS)
        check(NS, out / "rollout-version-b.jsonl", "version", TARGET, "--version", "B", "--sha256", model_hash("B"))
        join(rollout_load)
        rows = [json.loads(line) for path in out.glob("a-rollout-client-*.jsonl") for line in path.read_text().splitlines()]
        assert len(rows) == 64 * 5 and all(row["outcome"] == "completed" for row in rows), [
            row for row in rows if row["outcome"] != "completed"][:4]
        mark(trace, "rollout_validated", requests=len(rows) + len(streams))

        revision = json.loads(h(NS, "history", "hw11", "-o", "json"))[-2]["revision"]
        mark(trace, "return_to_a_for_failure", revision=revision)
        h(NS, "rollback", "hw11", str(revision))
        wait_ready(NS)
        revision = json.loads(h(NS, "history", "hw11", "-o", "json"))[-1]["revision"]
        bad_load = load(pool, NS, out, "a-unready", duration=35, rate=2, traffic="even")
        mark(trace, "unready_b")
        setup(NS, modelVersion="B", failLoad="true", maxParallel=2)
        until(lambda: any(p["version"] == "B" and p["ip"] and p["ready"] and p["ready"]["status"] == "False"
                          for p in snapshot(NS)["pods"].values()), 35, "unready B missing")
        time.sleep(12)
        logs(NS, out / "unready-b-server.log")
        save(out / "unready-b-endpoints.json", k(NS, "get", "endpointslices", "-o", "json"))
        mark(trace, "rollback_to_a", revision=revision)
        h(NS, "rollback", "hw11", str(revision))
        wait_ready(NS)
        check(NS, out / "check-rollback.jsonl", "version", TARGET, "--version", "A", "--sha256", model_hash("A"),
              "--label", "check-rollback")
        join(bad_load)
        bad_rows = [json.loads(line) for path in out.glob("a-unready-client-*.jsonl")
                    for line in path.read_text().splitlines()]
        assert len(bad_rows) == 70 and all(r["version"] == "A" and r["outcome"] == "completed" for r in bad_rows)

        kill_path = out / "check-forced-stream.jsonl"
        stream = long_stream(NS, kill_path, TARGET, "check-forced-stream")
        first = wait_check_started(kill_path)
        pod = first["pod"]
        mark(trace, "sigkill", pod=pod)
        state = snapshot(NS)["pods"][pod]
        container_id = state["container"][0]["containerID"].removeprefix("containerd://")
        command(["docker", "exec", "hw11-control-plane", "crictl", "stop", "--timeout", "0", container_id])
        assert stream.wait(12) == 0
        killed = json.loads(kill_path.read_text().splitlines()[-1])
        assert killed["outcome"] == "aborted" and 0 < killed["parts"] < 32, killed
        until(lambda: any(c.get("restartCount", 0) for c in snapshot(NS)["pods"][pod]["container"]),
              40, "restart not observed")
        k(NS, "wait", "--for=condition=Ready", f"pod/{pod}", "--timeout=100s")
        mark(trace, "restarted_ready", pod=pod)
        save(out / "sigkill-previous-server.log", k(NS, "logs", "--previous", pod))

        identity = snapshot(NS)["pods"]
        k(NS, "delete", "pod", pod, "--wait=false")
        mark(trace, "replace_pod", pod=pod)
        fresh = until(lambda: next(((name, state["ip"]) for name, state in snapshot(NS)["pods"].items()
                                    if name not in identity and state["ready"] and
                                    state["ready"]["status"] == "True"), None), 90, "replacement did not become ready")
        new_pod, new_ip = fresh
        check(NS, out / "check-replacement.jsonl", "version", f"http://{new_ip}:8091",
              "--sha256", model_hash("A"), "--old-pod", pod, "--label", "check-replacement")
        continuation = k(NS, "exec", "client-0", "--", "python", "-c",
                         "from client import attempt; import json,sys; "
                         "print(json.dumps(attempt(sys.argv[1], "
                         "{'prompt':'CONTINUED','history':['PREVIOUS-STATE'],'session_id':'replacement-dialogue',"
                         "'chunks':1},'check-history'))) ", f"http://{new_ip}:8091")
        history = json.loads(continuation)
        assert history["outcome"] == "completed" and history["pod"] == new_pod
        assert history["text"] == "PREVIOUS-STATE | CONTINUED"
        save(out / "check-history.jsonl", continuation)
        check(NS, out / "check-dialogue.jsonl", "dialogue")
        check(NS, out / "check-overload.jsonl", "overload", f"http://{new_ip}:8091")
        logs(NS, out / "final-server.log")
        mark(trace, "checks_passed", names=["warmup", "rollback", "replacement", "history", "dialogue", "overload", "abort"])


def experiment_b(repeat):
    namespace = f"hw11-b{repeat}"
    out = RESULTS / "b" / f"repeat-{repeat}"
    if not k(namespace, "get", "namespace", namespace, "--ignore-not-found", "-o", "name"):
        k(namespace, "create", "namespace", namespace)
    k(namespace, "apply", "-f", str(ROOT / "clients.yaml"))
    setup(namespace)
    wait_ready(namespace)
    k(namespace, "rollout", "status", "statefulset/client", "--timeout=90s")
    save(out / "pods.txt", k(namespace, "get", "pods", "-o", "wide"))
    save(out / "services.yaml", k(namespace, "get", "svc", "api", "api-sticky", "-o", "yaml"))
    save(out / "deployment.yaml", h(namespace, "get", "manifest", "hw11"))
    phases = (("even", "sticky"), ("even", "plain"), ("skew", "sticky"), ("skew", "plain"))
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        for traffic, policy in phases:
            name = f"b{repeat}-{traffic}-{policy}"
            target = "http://api-sticky:8091" if policy == "sticky" else TARGET
            with watch(pool, namespace, out / "kube.jsonl"):
                join(load(pool, namespace, out, name, target, duration=120, rate=8, traffic=traffic))
            print(f"{name} completed", flush=True)
    logs(namespace, out / "server.log")


def get_http(url):
    return k(NS, "exec", "client-0", "--", "python", "-c",
             "import sys,urllib.request; print(urllib.request.urlopen(sys.argv[1],timeout=12).read().decode())", url)


def prom(path, **params):
    return get_http(f"http://prometheus:9090/api/v1/{path}?" + urlencode(params))


def alert_watch(directory, stop):
    while not stop.wait(4):
        value = json.loads(prom("alerts"))
        record(directory / "alerts.jsonl", {"epoch": time.time(), "alerts": value["data"]["alerts"]})


def current_hpa():
    return json.loads(k(NS, "get", "hpa", "api", "-o", "json"))["status"]


def experiment_c():
    out = RESULTS / "c"
    timeline = out / "timeline.jsonl"
    setup(NS, **{"hpa.enabled": "true"})
    wait_ready(NS)
    save(out / "resource-api.json", k(NS, "get", "--raw", "/apis/metrics.k8s.io/v1beta1"))
    save(out / "hpa.yaml", k(NS, "get", "hpa", "api", "-o", "yaml"))
    save(out / "deployment.yaml", k(NS, "get", "deploy", "api", "-o", "yaml"))
    until(lambda: any(metric.get("resource", {}).get("current", {}).get("averageUtilization") is not None
                      for metric in current_hpa().get("currentMetrics", [])),
          120, "HPA CPU metrics unavailable")

    from threading import Event
    stop = Event()
    with concurrent.futures.ThreadPoolExecutor(10) as pool, watch(pool, NS, out / "kube.jsonl", hpa=True):
        alerts = pool.submit(alert_watch, out, stop)
        try:
            initial = {name for name, pod in snapshot(NS)["pods"].items() if not pod["deletion"]}
            assert len(initial) == 2, initial
            mark(timeline, "idle", pods=sorted(initial))
            time.sleep(12)
            jobs = load(pool, NS, out, "c-sticky-cpu", "http://api-sticky:8091", duration=115, rate=9,
                        chunks=4, chunk_delay=10, traffic="solo", cpu_iterations=320000)
            record(timeline, {"event": "cpu_load_started", "epoch": time.time()})
            new = until(lambda: next((name for name in snapshot(NS)["pods"] if name not in initial), None),
                        100, "HPA did not create a third pod", 1)
            mark(timeline, "third_created", pod=new, status=current_hpa())
            until(lambda: (snapshot(NS)["pods"].get(new, {}).get("ready") or {}).get("status") == "True",
                  60, "third pod did not become ready", 1)
            mark(timeline, "third_ready", pod=new)
            save(out / "resource-metrics-high.json", k(NS, "get", "--raw", "/apis/metrics.k8s.io/v1beta1/namespaces/hw11/pods"))
            save(out / "top-high.txt", k(NS, "top", "pod", "-l", "app=hw11-api", "--containers"))
            join(jobs)
            mark(timeline, "load_finished")

            until(lambda: current_hpa().get("currentReplicas") == 2 and current_hpa().get("desiredReplicas") == 2,
                  130, "HPA did not scale back to two pods", 2)
            mark(timeline, "back_at_two", status=current_hpa())
            time.sleep(12)
            join(load(pool, NS, out, "c-quiet-comparison", duration=55, rate=6, chunks=3,
                      chunk_delay=35, traffic="even"))
            mark(timeline, "comparison_finished")

            run = json.loads((out / "runs.jsonl").read_text().splitlines()[-1])
            end = run["start"] + 48
            delta = "api_ttfc_seconds_bucket - api_ttfc_seconds_bucket offset 30s"
            for quantile in (.5, .95):
                query = f"histogram_quantile({quantile}, sum by (le) ({delta}))"
                save(out / f"ttfc-prom-p{int(quantile * 100)}.json", prom("query", query=query, time=end))
            save(out / "ttfc-prom-count.json",
                 prom("query", query="sum(api_ttfc_seconds_count - api_ttfc_seconds_count offset 30s)", time=end))
            for name, instant in (("start", end - 30), ("end", end)):
                save(out / f"ttfc-scrape-{name}.json",
                     prom("query", query="timestamp(api_ttfc_seconds_count)", time=instant))
            record(out / "comparison-window.jsonl", {"start": end - 30, "end": end})
            save(out / "prometheus-targets.json", prom("targets"))
            save(out / "prometheus-rules.json", prom("rules"))
            save(out / "grafana-export.json", get_http("http://grafana:3000/api/dashboards/uid/hw11-inference"))
            for label, expr in {
                "cpu": 'sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="hw11",container="api"}[30s]))',
                "memory": 'sum by (pod) (container_memory_working_set_bytes{namespace="hw11",container="api"})',
                "running": "api_running",
                "waiting": "api_waiting",
                "ready": 'sum(kube_pod_status_ready{namespace="hw11",condition="true",pod=~"api-.*"})',
            }.items():
                beginning = json.loads(timeline.read_text().splitlines()[0])["epoch"]
                save(out / f"prom-{label}.json", prom("query_range", query=expr, start=beginning, end=time.time(), step="5s"))
            logs(NS, out / "server.log")
        finally:
            stop.set()
            alerts.result()
    alerts = [json.loads(line)["alerts"] for line in (out / "alerts.jsonl").read_text().splitlines()]
    for name in ("InferenceHighTTFC", "InferenceRejectedRequests"):
        states = [{r["state"] for r in group if r["labels"]["alertname"] == name} for group in alerts]
        assert {"pending", "firing"}.issubset(set.union(set(), *states)), (name, states)
        assert not states[-1], (name, states[-1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment", choices=["a", "b", "c"])
    parser.add_argument("--repeat", choices=[1, 2, 3], type=int)
    args = parser.parse_args()
    if args.experiment == "a":
        experiment_a()
    elif args.experiment == "b" and args.repeat:
        experiment_b(args.repeat)
    elif args.experiment == "c":
        experiment_c()
    else:
        parser.error("experiment b requires --repeat")
