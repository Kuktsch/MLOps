#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export KUBECONFIG="$PWD/.kubeconfig"
k=(kubectl -n hw11)
"${k[@]}" create configmap prometheus-config \
  --from-file=monitoring/prometheus.yaml --from-file=monitoring/alerts.yaml \
  --dry-run=client -o yaml | "${k[@]}" apply -f -
"${k[@]}" create configmap grafana-provision \
  --from-file=monitoring/datasource.yaml --from-file=monitoring/dashboards.yaml \
  --dry-run=client -o yaml | "${k[@]}" apply -f -
"${k[@]}" create configmap grafana-dashboard --from-file=monitoring/dashboard.json \
  --dry-run=client -o yaml | "${k[@]}" apply -f -
"${k[@]}" apply -f monitoring/stack.yaml
"${k[@]}" rollout restart deployment/prometheus deployment/grafana
"${k[@]}" rollout status deployment/prometheus --timeout=90s
"${k[@]}" rollout status deployment/grafana --timeout=90s
"${k[@]}" rollout status deployment/kube-state-metrics --timeout=90s
