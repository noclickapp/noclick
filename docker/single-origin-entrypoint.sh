#!/bin/bash
# Start the backend, the app and the front door, and stay alive exactly as long
# as all three do.
#
# One container running three processes is a deliberate choice, not a shortcut:
# this edition already requires exactly one backend — the scheduler ticks inside
# it and the realtime relay lives in it — so there is nothing to scale out, and
# a single container is what platforms that hand out one URL per service can
# actually host.
set -eu

PORT="${PORT:-8080}"
export PORT

# The app's server talks to the backend over the loopback interface; the browser
# talks to both through nginx on one origin, which is why the bundle needs no
# API URL baked into it.
export VITE_API_URL="${VITE_API_URL:-http://127.0.0.1:8000}"

# The instance's own address, which webhooks, OAuth callbacks and MCP discovery
# are minted from. Hosts that assign it publish it under their own name, so
# there is usually nothing to set.
: "${VITE_PUBLIC_URL:=${PUBLIC_URL:-}}" # legacy PUBLIC_URL compatibility
: "${VITE_PUBLIC_URL:=${PUBLIC_HOST:+https://$PUBLIC_HOST}}"
: "${VITE_PUBLIC_URL:=${RENDER_EXTERNAL_URL:-}}"
: "${VITE_PUBLIC_URL:=${RAILWAY_PUBLIC_DOMAIN:+https://$RAILWAY_PUBLIC_DOMAIN}}"
: "${VITE_PUBLIC_URL:=${FLY_APP_NAME:+https://$FLY_APP_NAME.fly.dev}}"
: "${VITE_PUBLIC_URL:=${KOYEB_PUBLIC_DOMAIN:+https://$KOYEB_PUBLIC_DOMAIN}}"
: "${VITE_PUBLIC_URL:=http://localhost:$PORT}"
export VITE_PUBLIC_URL

: "${PUBLIC_API_URL:=${VITE_PUBLIC_URL:-}}"
: "${FRONTEND_URL:=${VITE_PUBLIC_URL:-}}"
: "${PUBLIC_WEBHOOK_URL:=${PUBLIC_API_URL:-}}"
: "${APP_WEBHOOK_BASE_URL:=${PUBLIC_API_URL:-}}"
: "${MCP_BASE_URL:=${PUBLIC_API_URL:-}}"
: "${CRON_SCHEDULER_URL:=http://127.0.0.1:8000/local-cron}"
export PUBLIC_API_URL FRONTEND_URL PUBLIC_WEBHOOK_URL APP_WEBHOOK_BASE_URL \
       MCP_BASE_URL CRON_SCHEDULER_URL

# This image is the self-hosted edition and has no Turnstile configuration, so
# the sign-in form would ask a captcha nobody can answer. The browser bundle
# already knows (its widget compiles away without a site key); this is the
# server half of the same fact.
: "${VITE_DISABLE_CAPTCHA:=true}"
export VITE_DISABLE_CAPTCHA

embedded_auth=0

# ── Auth ─────────────────────────────────────────────────────────────────────
# A SUPABASE_URL means an external project, and nothing below runs. Without one,
# this container is the whole instance: GoTrue and PostgREST run here against
# the database, served on this origin under the paths supabase-js addresses. A
# host that can hand out a Postgres URL can then deploy NoClick with no other
# input at all — which is the difference between a one-click deploy and a form.
if [ -z "${SUPABASE_URL:-}" ]; then
    if [ -z "${POSTGRES_URL:-}" ]; then
        echo "Set POSTGRES_URL (or a SUPABASE_URL for an external project)." >&2
        exit 1
    fi
    : "${POSTGRES_POOLER_URL:=$POSTGRES_URL}"
    export POSTGRES_POOLER_URL

    # The instance's secrets, and the two role DSNs derived from them. A failure
    # here aborts under `set -e` rather than eval'ing an empty string.
    instance_env="$(python /app/docker/bootstrap.py secrets)"
    eval "$instance_env"
    unset instance_env

    # The browser reaches the auth API on the instance's public origin; this
    # process reaches it through its own front door, because the public
    # hostname resolves to the platform's edge and not back into this container.
    export SUPABASE_URL="$VITE_PUBLIC_URL"
    export SUPABASE_INTERNAL_URL="http://127.0.0.1:$PORT"

    export GOTRUE_DB_DRIVER=postgres
    export GOTRUE_API_HOST=127.0.0.1
    export GOTRUE_API_PORT=9999
    # GoTrue builds emailed links from this, and the path it is reachable on is
    # /auth/v1 — the prefix nginx strips below. It reads the unprefixed name too.
    export API_EXTERNAL_URL="$VITE_PUBLIC_URL/auth/v1"
    export GOTRUE_API_EXTERNAL_URL="$API_EXTERNAL_URL"
    export GOTRUE_SITE_URL="$VITE_PUBLIC_URL"
    export GOTRUE_URI_ALLOW_LIST="$VITE_PUBLIC_URL/**"
    export GOTRUE_JWT_SECRET="$JWT_SECRET"
    export GOTRUE_JWT_EXP=3600
    export GOTRUE_JWT_AUD=authenticated
    export GOTRUE_JWT_DEFAULT_GROUP_NAME=authenticated
    export GOTRUE_JWT_ADMIN_ROLES=service_role
    export GOTRUE_DISABLE_SIGNUP="${NOCLICK_DISABLE_SIGNUP:-false}"
    export GOTRUE_EXTERNAL_EMAIL_ENABLED=true
    # No mail server is configured by default, and an instance whose first
    # account can never be confirmed is an instance nobody can sign in to.
    export GOTRUE_MAILER_AUTOCONFIRM="${NOCLICK_AUTOCONFIRM_EMAIL:-true}"
    export GOTRUE_SMTP_HOST="${SMTP_HOST:-}"
    export GOTRUE_SMTP_PORT="${SMTP_PORT:-587}"
    export GOTRUE_SMTP_USER="${SMTP_USERNAME:-}"
    export GOTRUE_SMTP_PASS="${SMTP_PASSWORD:-}"
    export GOTRUE_SMTP_ADMIN_EMAIL="${FROM_EMAIL:-}"
    export GOTRUE_HOOK_CUSTOM_ACCESS_TOKEN_ENABLED=true
    export GOTRUE_HOOK_CUSTOM_ACCESS_TOKEN_URI=pg-functions://postgres/public/custom_access_token_hook

    export PGRST_SERVER_HOST=127.0.0.1
    export PGRST_SERVER_PORT=3001
    export PGRST_DB_SCHEMAS=public
    export PGRST_DB_ANON_ROLE=anon
    export PGRST_JWT_SECRET="$JWT_SECRET"
    export PGRST_DB_USE_LEGACY_GUCS=false
    export PGRST_APP_SETTINGS_JWT_SECRET="$JWT_SECRET"
    export PGRST_APP_SETTINGS_JWT_EXP=3600

    # Ordered, not raced: the roles and schemas GoTrue needs, then its own
    # migrations, then ours — which carry foreign keys onto auth.users.
    python /app/docker/bootstrap.py prepare
    gotrue migrate
    python /app/docker/bootstrap.py

    cp /etc/nginx/supabase-upstreams.conf /etc/nginx/supabase/upstreams.conf
    embedded_auth=1
elif [ "${NOCLICK_BOOTSTRAP_ON_START:-}" = "1" ]; then
    # An external project, on a platform with no release phase to run it in.
    python /app/docker/bootstrap.py
fi

# The relay. The app server resolves this when its modules load, and the browser
# bundle deliberately carries no build-time URL, so nothing else would supply
# one: without it the server throws before it ever listens, and the container
# exits. https -> wss, http -> ws.
: "${VITE_RELAY_URL:=$(printf '%s' "$VITE_PUBLIC_URL" | sed 's|^http|ws|')/relay}"
export VITE_RELAY_URL

envsubst '${PORT}' < /etc/nginx/single-origin.conf.template > /etc/nginx/conf.d/default.conf

pids=""
stop() {
    # Ask everything to finish, then let the container exit; the supervisor
    # loop below stops looking as soon as one of them is gone.
    for pid in $pids; do kill -TERM "$pid" 2>/dev/null || true; done
}
trap stop TERM INT

if [ "$embedded_auth" = 1 ]; then
    gotrue serve &
    pids="$pids $!"
    postgrest &
    pids="$pids $!"
fi

python -m uvicorn server:web_app --host 127.0.0.1 --port 8000 --workers 1 \
    --app-dir /app/backend &
pids="$pids $!"

( cd /app/frontend && PORT=3000 exec node_modules/.bin/react-router-serve ./build/server/index.js ) &
pids="$pids $!"

nginx -g 'daemon off;' &
pids="$pids $!"

# `wait -n` (a bash builtin — hence the shebang) returns as soon as ANY of them exits. A backend that dies leaving
# nginx serving 502s is not a running instance, and a platform's restart policy
# can only see a container that has actually stopped.
wait -n
status=$?
stop
wait || true
exit "$status"
