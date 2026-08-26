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

# Platforms with a release/pre-deploy phase run bootstrap there so a failed
# migration never replaces the healthy release. Simpler container platforms
# can opt into the same idempotent preparation immediately before startup.
if [ "${NOCLICK_BOOTSTRAP_ON_START:-}" = "1" ]; then
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
