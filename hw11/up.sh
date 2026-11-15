#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export KUBECONFIG="$PWD/.kubeconfig"
tools="$PWD/.tools"
mkdir -p "$tools" results
fetch() {
  if [ ! -f "$2" ]; then
    curl --fail --location --retry 2 --silent --show-error "$1" -o "$2.part"
    mv "$2.part" "$2"
  fi
}
fetch https://github.com/kubernetes-sigs/kind/releases/download/v0.27.0/kind-linux-amd64 "$tools/kind"
fetch https://get.helm.sh/helm-v3.18.4-linux-amd64.tar.gz "$tools/helm-v3.18.4-linux-amd64.tar.gz"
fetch https://get.helm.sh/helm-v3.18.4-linux-amd64.tar.gz.sha256sum "$tools/helm.sha256"
fetch https://dl.k8s.io/release/v1.32.2/bin/linux/amd64/kubectl "$tools/kubectl"
(
  cd "$tools"
  printf '%s  %s\n' a6875aaea358acf0ac07786b1a6755d08fd640f4c79b7a2e46681cc13f49a04b kind | sha256sum -c -
  printf '%s  %s\n' 4f6a959dcc5b702135f8354cc7109b542a2933c46b808b248a214c1f69f817ea kubectl | sha256sum -c -
  sha256sum -c helm.sha256
  tar -xzf helm-v3.18.4-linux-amd64.tar.gz linux-amd64/helm
  mv linux-amd64/helm helm
  chmod +x kind kubectl
)
export PATH="$tools:$PATH"
if [ ! -f results/environment-before.txt ]; then
  df -h . > .disk-before.txt
  {
    date -Iseconds
    printf '%s\n' 'Состояние диска перед запуском сохранено локально.'
    docker info --format 'CPU={{.NCPU}} RAM={{.MemTotal}} Root={{.DockerRootDir}}'
    docker system df
    docker version
  } > results/environment-before.txt
fi
if ! kind get clusters | grep -qx hw11; then
  kind create cluster --name hw11 --kubeconfig "$KUBECONFIG" --config kind.yaml --wait 90s \
    --image kindest/node:v1.32.2@sha256:f226345927d7e348497136874b6d207e0b32cc52154ad8323129352923a3142f
fi
if [ ! -f "$KUBECONFIG" ]; then
  kind export kubeconfig --name hw11 --kubeconfig "$KUBECONFIG"
fi
if [ "$(kubectl config current-context)" != kind-hw11 ]; then
  echo 'Expected dedicated kind-hw11 context' >&2
  exit 1
fi
docker build --provenance=false -f "$PWD/Dockerfile" -t hw11-api:1.0.0 ..
docker tag hw11-api:1.0.0 hw11-api:1.0.1
while read -r tag ref; do
  docker pull --platform linux/amd64 "$ref"
  docker tag "$ref" "$tag"
  docker image save --platform linux/amd64 "$tag" | \
    docker exec --privileged -i hw11-control-plane ctr --namespace=k8s.io images import --platform linux/amd64 --snapshotter=overlayfs -
done < monitoring/images.lock
docker image save --platform linux/amd64 hw11-api:1.0.0 hw11-api:1.0.1 | \
  docker exec --privileged -i hw11-control-plane ctr --namespace=k8s.io images import --platform linux/amd64 --snapshotter=overlayfs -
fetch https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml "$tools/metrics-server.yaml"
kubectl apply -f "$tools/metrics-server.yaml"
kubectl -n kube-system patch deployment metrics-server --type=strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"metrics-server","imagePullPolicy":"Never","args":["--cert-dir=/tmp","--secure-port=10250","--kubelet-preferred-address-types=InternalIP,ExternalIP,Hostname","--kubelet-use-node-status-port","--metric-resolution=15s","--kubelet-insecure-tls"]}]}}}}'
kubectl -n kube-system rollout status deploy/metrics-server --timeout=120s
if [ ! -f results/versions-network.txt ]; then
  {
  date -Iseconds
  kubectl version
  kind version
  helm version --short
  kubectl get nodes -o wide
  kubectl -n kube-system get cm kube-proxy -o jsonpath='{.data.config\.conf}'
  docker network inspect kind --format '{{json .IPAM.Config}}'
  } > results/versions-network.txt
fi
kubectl create namespace hw11 --dry-run=client -o yaml | kubectl apply -f -
kubectl -n hw11 apply -f clients.yaml
kubectl -n hw11 rollout status statefulset/client --timeout=90s
bash up-monitoring.sh
helm -n hw11 upgrade --install hw11 "$PWD/chart"
kubectl -n hw11 rollout status deployment/api --timeout=90s
