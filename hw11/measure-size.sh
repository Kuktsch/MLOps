#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export KUBECONFIG="$PWD/.kubeconfig"
export PATH="$PWD/.tools:$PATH"
node=kindest/node:v1.32.2@sha256:f226345927d7e348497136874b6d207e0b32cc52154ad8323129352923a3142f
images=(hw11-api:1.0.0 hw11-api:1.0.1 "$node")
while read -r tag ref; do
  images+=("$tag")
done < monitoring/images.lock
{
  date -Iseconds
  docker system df
  docker ps --filter name=hw11-control-plane --size
  docker image inspect --format '{{.Id}} {{.Size}} {{join .RepoTags " "}}' "${images[@]}"
  docker exec hw11-control-plane du -sh /var/lib/containerd /var/lib/kubelet
  kubectl get pod -A -o wide
  kubectl -n hw11 exec deploy/prometheus -- du -sh /prometheus
  kubectl -n hw11 exec deploy/grafana -- du -sh /var/lib/grafana
} > results/environment-after.txt
python3.12 - <<'PY'
import json
import re
from pathlib import Path

results = Path("results")
before = (results / "environment-before.txt").read_text()
after = (results / "environment-after.txt").read_text()

def volume_gb(text):
    value, unit = re.search(r"Local Volumes\s+\d+\s+\d+\s+([\d.]+)([MG])B", text).groups()
    return float(value) if unit == "G" else float(value) / 1000

data = {"volume_delta_gb": volume_gb(after) - volume_gb(before)}
data["api_mib"] = int(re.search(r"^sha256:[\da-f]+ (\d+) hw11-api:1\.0\.0", after, re.M)[1]) / 2**20
for name, path in (("containerd", "/var/lib/containerd"), ("prometheus", "/prometheus"),
                   ("grafana", "/var/lib/grafana")):
    data[name] = re.search(r"^(\S+)\s+" + path + r"$", after, re.M)[1]
(results / "size.json").write_text(json.dumps(data, indent=2) + "\n")
PY
