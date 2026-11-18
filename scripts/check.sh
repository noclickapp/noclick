#!/usr/bin/env bash
# Builds and tests everything in this repository, as CI does: the Python SDK (its tests and its
# wheel), the examples (each parses), the TypeScript SDK (typecheck, tests, build), then the app
# (install from its lockfile, typecheck, tests, build).
# Needs python3, Node 22.12 or later, and pnpm 10 on the PATH (`corepack enable pnpm` provides the
# version app/package.json names). The rest goes into a throwaway virtualenv,
# sdk/typescript/node_modules and app/node_modules.
set -euo pipefail

cd "$(dirname "$0")/.."
root="$(pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
# Only what the virtualenv holds.
unset PYTHONPATH

if ! command -v pnpm > /dev/null; then
  echo "scripts/check.sh needs pnpm for the app: run 'corepack enable pnpm' (or see https://pnpm.io/installation)" >&2
  exit 1
fi

echo "== Python SDK"
python3 -m venv "$work/venv"
python="$work/venv/bin/python"
"$python" -m pip install --quiet --disable-pip-version-check -e "sdk/python[dev,cli]"
(cd sdk/python && "$python" -m pytest -q -p no:cacheprovider)
"$python" -m pip wheel --quiet --disable-pip-version-check --no-deps --wheel-dir "$work/wheel" sdk/python

echo "== Examples"
"$python" - <<'PY'
import ast
from pathlib import Path

for path in sorted(Path("sdk/examples").rglob("*.py")):
    ast.parse(path.read_text(), str(path))
PY

echo "== TypeScript SDK"
cd "$root/sdk/typescript"
npm ci --no-audit --no-fund
npm run typecheck
PYTHON="$python" npm test
npm run build

echo "== App"
cd "$root/app"
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm test
pnpm run build
