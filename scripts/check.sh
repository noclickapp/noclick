#!/usr/bin/env bash
# Builds and tests everything in this repository, as CI does: the Python SDK (its tests and its
# wheel), the examples (each parses), the workflow builder (its tests, on that SDK), the TypeScript
# SDK (typecheck, tests, build), then the app (install from its lockfile, typecheck, tests, build, then its build
# started as a Worker on the Workers runtime, with the wrangler scripts/check-worker.mjs fetches).
# Needs python3, Node 22.12 or later, and pnpm 10 on the PATH (`corepack enable pnpm` provides the
# version app/package.json names). The rest goes into a throwaway virtualenv,
# sdk/typescript/node_modules and app/node_modules.
#
#   scripts/check.sh [PART...]   only the parts named, of: sdk-python, examples, builder,
#                                sdk-typescript, app, worker (none named: all of them)
#
# APP_TESTS_RELATED, a list of the app's files (relative to app/, space-separated), runs only the app's
# tests that import one of them (vitest related), and test/'s, which read the app's files rather than
# import them; unset, every test runs.
set -euo pipefail

parts=(sdk-python examples builder sdk-typescript app worker)
if [ $# -gt 0 ]; then
  for part in "$@"; do
    case " ${parts[*]} " in *" $part "*) ;; *) echo "scripts/check.sh: no part named $part (${parts[*]})" >&2; exit 2 ;; esac
  done
  parts=("$@")
fi
runs() { case " ${parts[*]} " in *" $1 "*) return 0 ;; esac; return 1; }

cd "$(dirname "$0")/.."
root="$(pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
# Only what the virtualenv holds.
unset PYTHONPATH

if { runs app || runs worker; } && ! command -v pnpm > /dev/null; then
  echo "scripts/check.sh needs pnpm for the app: run 'corepack enable pnpm' (or see https://pnpm.io/installation)" >&2
  exit 1
fi

# The Python SDK, which the builder's tests and the TypeScript SDK's (checking its API against it) use too.
python3 -m venv "$work/venv"
python="$work/venv/bin/python"
"$python" -m pip install --quiet --disable-pip-version-check -e "sdk/python[dev,cli]"

if runs sdk-python; then
  echo "== Python SDK"
  (cd sdk/python && "$python" -m pytest -q -p no:cacheprovider)
  "$python" -m pip wheel --quiet --disable-pip-version-check --no-deps --wheel-dir "$work/wheel" sdk/python
fi

if runs examples; then
  echo "== Examples"
  "$python" - <<'PY'
import ast
from pathlib import Path

for path in sorted(Path("sdk/examples").rglob("*.py")):
    ast.parse(path.read_text(), str(path))
PY
fi

if runs builder; then
  echo "== Workflow builder"
  (cd agents/builder && "$python" -m pytest -q -p no:cacheprovider)
fi

if runs sdk-typescript; then
  echo "== TypeScript SDK"
  cd "$root/sdk/typescript"
  npm ci --no-audit --no-fund
  npm run typecheck
  PYTHON="$python" npm test
  npm run build
fi

if runs app || runs worker; then
  echo "== App"
  cd "$root/app"
  pnpm install --frozen-lockfile
  pnpm run typecheck
  if [ -n "${APP_TESTS_RELATED:-}" ]; then
    read -ra related <<< "$APP_TESTS_RELATED"
    pnpm exec vitest related --run --passWithNoTests "${related[@]}"
    pnpm exec vitest run test/
  else
    pnpm test
  fi
  pnpm run build
fi

if runs worker; then
  echo "== App as a Worker"
  node "$root/scripts/check-worker.mjs"
fi
