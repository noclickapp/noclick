#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# Reject alternate content channels in both the current index and every object
# reachable from HEAD. The exporter deliberately masks graft/shallow metadata
# while rewriting; remove only those masks for the history audit so the scanner
# can see and reject the repository's real metadata. All other Git environment
# and configuration remains fail-closed inside the scanner.
python3 scripts/check-repository-transport.py .
env -u GIT_GRAFT_FILE -u GIT_SHALLOW_FILE python3 scripts/check-repository-transport.py --history HEAD .

# Pin the public runtime surface contributors are expected to preserve.
for required_runtime_path in \
  backend/coder/openai_agent/sandbox.py \
  backend/nodes/agent/local_harness.py \
  backend/utils/local_relay.py \
  backend/utils/volume_backend.py \
  backend/utils/agent_workspace.py \
  backend/utils/agent_workspace_routes.py
do
  if [[ ! -f "$required_runtime_path" ]]; then
    echo "Community boundary violation: required local runtime path is missing: $required_runtime_path" >&2
    exit 1
  fi
done

# backend/billing is the shared metering engine. The community edition records
# provider cost at list price unless its operator explicitly configures otherwise,
# so assert the loaded value rather than depending on a source-code spelling.
if [[ ! -f backend/billing/markup.py ]]; then
  echo "Community boundary violation: backend/billing is missing" >&2
  exit 1
fi
# Loaded by path rather than imported: `billing/__init__` pulls in pydantic, and
# this check has to run for a contributor who has not installed anything.
if ! ( env -u PLATFORM_MARKUP python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("_markup", "backend/billing/markup.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.exit(0 if module.PLATFORM_MIN_MARKUP == 1 else 1)
' ); then
  echo "Community boundary violation: backend/billing applies a markup by default" >&2
  exit 1
fi

# Keep the code-generation package deliberately small. Any additional engine
# under backend/coder requires an explicit edition-boundary review.
while IFS= read -r coder_entry; do
  case "$coder_entry" in
    backend/coder/__init__.py|backend/coder/openai_agent|backend/coder/workflow) ;;
    *)
      echo "Community boundary violation: unreviewed backend/coder entry: $coder_entry" >&2
      exit 1
      ;;
  esac
done < <(find backend/coder -mindepth 1 -maxdepth 1 ! -name '__pycache__' | sort)

shopt -s nullglob
for route in frontend/app/routes/api/auth/*.authorize.tsx frontend/app/routes/api/auth/x/authorize.tsx; do
  if ! rg -q 'oauthRedirect[(]' "$route"; then
    echo "Community boundary violation: OAuth authorize route bypasses state sealing: $route" >&2
    exit 1
  fi
done

for route in frontend/app/routes/api/auth/*.callback.tsx frontend/app/routes/api/auth/x/callback.tsx; do
  [[ "$route" == *mcp.callback.tsx ]] && continue
  if ! rg -q 'oauthCallbackUrl[(]' "$route"; then
    echo "Community boundary violation: OAuth callback bypasses browser binding: $route" >&2
    exit 1
  fi
done

# A client secret in a query string is written to browser history and access
# logs. Custom app credentials now use a same-origin POST body, so this is a
# permanent regression gate rather than accepted debt.
if rg -n -e '(searchParams|params)[.](get|set)[(][^)]*(client_secret|custom_client_secret)' \
    frontend/app/routes/api/auth frontend/app/hooks/oauth \
    --glob '*.ts' --glob '*.tsx'; then
  echo "Community boundary violation: an OAuth client secret travels in a URL" >&2
  exit 1
fi

# A hardcoded fallback signing key is a published signing key once this
# repository is public: anyone can mint a session or a CSRF token. Both cookies
# derive their key from getServerSecret(), which fails closed.
if rg -n -e "SESSION_SECRET[^\\n]*[|][|][^\\n]*[\"'][^\"']+[\"']" \
    frontend/app --glob '*.ts' --glob '*.tsx'; then
  echo "Community boundary violation: fixed SESSION_SECRET fallback" >&2
  exit 1
fi


if rg -n -e "noclick[.]com/[^\"'[:space:]]*(ref|token|link_id|linkId)=" \
    frontend backend sdk --glob '!**/node_modules/**' --glob '!**/dist/**'; then
  echo "Community boundary violation: capability identifier sent to NoClick" >&2
  exit 1
fi

# Auth mail must not make a recipient contact an unrelated fixed host merely
# by opening the message. Supabase's own action links remain templated; branding
# is a self-contained text wordmark rather than a remotely loaded image.
if rg -n "<img[^>]+src=[\"']https?://" infra/supabase/templates --glob '*.html'; then
  echo "Community boundary violation: auth email loads a remote image" >&2
  exit 1
fi

# Credential-like values and provider response bodies do not belong in logs or
# exceptions. OAuth bodies can echo authorization codes or newly minted tokens;
# status-only diagnostics are sufficient for the public runtime.
if rg -n \
    -e '(console[.](log|error|warn)|logger[.](debug|info|warning|error|exception)).*(substring[(]0, *[0-9]+[)]|fullResponse|[.](text|content|headers))' \
    -e '(raise [A-Za-z_][A-Za-z0-9_]*|error_(msg|text) *=|return) .*response[.]text' \
    frontend/app/lib/auth.server.ts backend/nodes/oauth \
    backend/nodes/agent/harness_oauth_flows.py backend/utils/api_keys.py \
    backend/utils/credential_request_routes.py; then
  echo "Community boundary violation: sensitive token or provider response reaches diagnostics" >&2
  exit 1
fi

# Repository-local PR numbers become misleading links after publication. An
# external reference must be qualified as owner/repository#number instead.
if rg -n 'PR #[0-9]+' backend frontend sdk docs --glob '!**/node_modules/**'; then
  echo "Community boundary violation: unqualified private pull-request reference" >&2
  exit 1
fi

# NoClick-managed hostnames fail closed. The managed API default is deliberate
# only in the reviewed SDK implementations and their contract documentation;
# the public website and docs hosts are ordinary links. Everything else must
# use operator configuration.
managed_domain='noclick.io'
public_domain='noclick.com'
approved_api_host="api.$managed_domain"
while IFS=: read -r managed_path managed_host; do
  managed_path=${managed_path#./}
  managed_host=$(printf '%s' "$managed_host" | tr '[:upper:]' '[:lower:]')
  case "$managed_host" in
    "www.$public_domain"|"docs.$public_domain") continue ;;
  esac
  case "$managed_path" in
    sdk/typescript/src/index.ts|sdk/typescript/src/transports/websocket.ts|sdk/python/noclick/client.py|\
    docs/edition-boundary.md|sdk/typescript/README.md|sdk/python/README.md|docs/public/sdk/external-apps.mdx)
      if [[ "$managed_host" == "$approved_api_host" ]]; then
        continue
      fi
      ;;
    *)
      ;;
  esac
  echo "Community boundary violation: unapproved managed-service hostname: $managed_path" >&2
  exit 1
done < <(
  rg -o -i --no-filename -N '([A-Za-z0-9-]+[.])+noclick[.](io|com)' . \
    --glob '!scripts/check-community-boundary.sh' --glob '!.git/**' \
    --glob '!**/node_modules/**' --glob '!**/build/**' --glob '!**/dist/**' \
    | while IFS= read -r managed_host; do
        rg -l -i -F "$managed_host" . \
          --glob '!scripts/check-community-boundary.sh' --glob '!.git/**' \
          --glob '!**/node_modules/**' --glob '!**/build/**' --glob '!**/dist/**' \
          | while IFS= read -r managed_path; do
              printf '%s:%s\n' "$managed_path" "$managed_host"
            done
      done | sort -u
)

# Numeric WhatsApp JIDs often come straight from real webhook payloads. Public
# examples may exercise each suffix, but their local parts must be the reviewed
# fictional values produced by the exporter rather than account identifiers.
while IFS= read -r whatsapp_jid; do
  case "$whatsapp_jid" in
    12025550100@s.whatsapp.net|12025550101@c.us|\
    12025550102@lid|12025550103@lid|\
    12025550104@s.whatsapp.net|120000000000000001@g.us|\
    120000000000000002@newsletter|12025550107@c.us|\
    12025550108@c.us) ;;
    *)
      echo "Community boundary violation: unreviewed account-shaped WhatsApp fixture: $whatsapp_jid" >&2
      exit 1
      ;;
  esac
done < <(
  rg -o --no-filename -N \
    '[0-9]{10,20}@(s[.]whatsapp[.]net|c[.]us|g[.]us|newsletter|lid)' \
    backend frontend --glob '!**/node_modules/**' --glob '!**/dist/**' \
    | sort -u || true
)

# Hiding the canvas badge is a deliberate UI choice under the MIT license. Pin
# both the three visible settings and the retained upstream notice together.
for canvas_marker in \
  'frontend/app/components/workflow/FlowCanvas.tsx:const proOptions = { hideAttribution: true };' \
  'frontend/app/components/workflow/ReadOnlyFlowCanvas.tsx:const proOptions = { hideAttribution: true };' \
  'frontend/widgets/workflow-viewer/WorkflowViewer.tsx:proOptions={{ hideAttribution: true }}'
do
  canvas_file=${canvas_marker%%:*}
  marker=${canvas_marker#*:}
  if ! rg -q -F "$marker" "$canvas_file"; then
    echo "Community boundary violation: React Flow attribution setting drifted: $canvas_file" >&2
    exit 1
  fi
done
for notice_marker in '@xyflow/react` 12.10.0' '@xyflow/system` 0.0.74' \
  'Copyright (c) 2019-2025 webkid GmbH' 'Permission is hereby granted' \
  'THE SOFTWARE IS PROVIDED "AS IS"'
do
  if ! rg -q -F "$notice_marker" THIRD_PARTY_NOTICES.md; then
    echo "Community boundary violation: XYFlow MIT notice is incomplete" >&2
    exit 1
  fi
done

# Tracked files only. The rule is about what ships, and a developer who has
# run `docker compose up` has a real .env sitting in the working tree — failing
# on that makes the check fire on the documented setup.
while IFS= read -r env_file; do
  case "$env_file" in
    .env.example|*/.env.example) ;;
    *)
      echo "Community boundary violation: environment file must not be committed: $env_file" >&2
      exit 1
      ;;
  esac
done < <(git ls-files -- '.env' '.env.*' '**/.env' '**/.env.*')

echo "Community boundary checks passed."
