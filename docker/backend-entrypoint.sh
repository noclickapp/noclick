#!/bin/sh
# Compose the public URLs from bare hostnames when the explicit URLs are absent.
#
# A hosting platform assigns the hostname when it creates the service, so a
# blueprint can only pass the host itself — there is nowhere to interpolate a
# scheme. Everything the backend actually reads is a full URL, so the join
# happens once, here, instead of in each platform's config.
#
# Explicit values always win, which is what docker-compose.yml and any hand
# configuration set.
set -eu

: "${PUBLIC_API_URL:=${PUBLIC_API_HOST:+https://$PUBLIC_API_HOST}}"
: "${PUBLIC_WEBHOOK_URL:=${PUBLIC_API_URL:-}}"
: "${APP_WEBHOOK_BASE_URL:=${PUBLIC_API_URL:-}}"
: "${MCP_BASE_URL:=${PUBLIC_API_URL:-}}"
: "${FRONTEND_URL:=${PUBLIC_APP_HOST:+https://$PUBLIC_APP_HOST}}"
# The scheduler calls its own API over the loopback interface; it never needs
# to leave the container, and routing it through the public URL would make a
# schedule tick depend on the instance being reachable from itself.
: "${CRON_SCHEDULER_URL:=http://127.0.0.1:${PORT:-8000}/local-cron}"
export PUBLIC_API_URL PUBLIC_WEBHOOK_URL APP_WEBHOOK_BASE_URL MCP_BASE_URL \
       FRONTEND_URL CRON_SCHEDULER_URL

exec "$@"
