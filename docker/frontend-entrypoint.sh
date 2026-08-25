#!/bin/sh
# Platforms that assign a hostname at create time (Render, Railway, Fly) can only
# hand it over as a bare host — there is nothing to interpolate a scheme into a
# blueprint with. Compose the URLs from `*_HOST` when the explicit URL is absent,
# so one image works whether the operator knows their URLs up front or not.
#
# The same composition runs at build time in frontend.Dockerfile, because these
# values are also compiled into the browser bundle.
set -eu

: "${VITE_API_URL:=${VITE_API_HOST:+https://$VITE_API_HOST}}"
: "${VITE_PUBLIC_URL:=${PUBLIC_URL:-}}" # legacy PUBLIC_URL compatibility
: "${VITE_PUBLIC_URL:=${VITE_APP_HOST:+https://$VITE_APP_HOST}}"
: "${FRONTEND_URL:=${VITE_PUBLIC_URL:-}}"
export VITE_API_URL VITE_PUBLIC_URL FRONTEND_URL

exec "$@"
