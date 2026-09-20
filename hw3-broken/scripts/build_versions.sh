#!/usr/bin/env bash
# Explicitly requested operation: create *real* v1 / v2 git revisions with DVC locks.
set -euo pipefail
cd "$(dirname "$0")/.."
git rev-parse --show-toplevel >/dev/null || { echo 'Сначала инициализируйте Git' >&2; exit 1; }
for version in v1 v2; do
  uv run python scripts/set_version.py "$version"
  make repro
  uv run dvc push
  git add params.yaml dvc.yaml dvc.lock .dvc/config .gitignore docs/datasheet.md \
          docs/defects.md README.md pyproject.toml uv.lock Makefile src scripts tests
  git add -f metrics/collect.json metrics/clean.json metrics/diversity.json metrics/split.json
  if ! git diff --cached --quiet; then
    git commit -m "HW3 dataset ${version}: DVC pipeline and observed metrics"
  else
    echo "Отсутствуют изменения для ${version}; проверьте git status" >&2
    exit 1
  fi
done
uv run dvc metrics diff HEAD~1 HEAD
