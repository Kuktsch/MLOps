#!/usr/bin/env bash
# One-command finalization on user's online WSL environment. Does create Git commits.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo 'Не установлен uv: https://docs.astral.sh/uv/' >&2; exit 1; }
uv sync --python 3.12
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  git init
fi
if ! git var GIT_AUTHOR_IDENT >/dev/null 2>&1; then
  echo 'Настройте имя/email автора через git config user.name и git config user.email' >&2
  exit 1
fi
make versions
make check
printf '\nHW3: проверено; сохраните лог проверки и видео выполнения make check.\n'
