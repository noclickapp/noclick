#!/usr/bin/env bash
# Audits every manifest the open edition installs from against today's
# advisories. CI runs it on every push, so an advisory published after a release
# fails an unchanged tree; the fix is an upgrade. Every audit runs, so one run
# names every package to upgrade. Needs pip-audit, npm and pnpm.
set -uo pipefail
cd "$(dirname "$0")/.." || exit

failed=()

audit() {
  echo "==> $*"
  "$@" || failed+=("$*")
}

# pnpm exits 0 when the registry can't answer (--ignore-registry-errors), and
# then prints the error rather than its "... vulnerabilities found" summary,
# which it prints for a clean audit and one with findings below --audit-level.
pnpm_audit() {
  local dir=$1
  shift
  local output status=0
  echo "==> pnpm --dir $dir audit --prod --ignore-registry-errors $*"
  output="$(pnpm --dir "$dir" audit --prod --ignore-registry-errors "$@" 2>&1)" || status=$?
  printf '%s\n' "$output"
  if [ "$status" -ne 0 ]; then
    failed+=("pnpm audit in $dir")
  elif [[ "$output" != *"vulnerabilities found"* ]]; then
    echo "::warning title=npm security audit unavailable::The registry could not complete the $dir dependency audit; see the log."
  fi
}

audit pip-audit -r requirements.txt -r requirements-dev.txt
audit npm audit --omit=dev
pnpm_audit backend
audit npm --prefix sdk/typescript audit --omit=dev
pnpm_audit frontend --audit-level=high

if [ "${#failed[@]}" -gt 0 ]; then
  printf '::error title=Dependency audit::%s\n' "${failed[@]}"
  exit 1
fi
