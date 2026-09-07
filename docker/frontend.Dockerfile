# NoClick Community — frontend (React Router 7 server + built browser bundles).
#
# NOTE: `VITE_*` values are compiled into the browser bundle, so the public URLs
# below are build arguments, not runtime environment. Rebuild the image when the
# instance's public URLs change.

FROM node:22-bookworm-slim AS build

RUN corepack enable
WORKDIR /src

# Vite's production build is the memory high-water mark of the whole stack; the
# default heap aborts it (SIGABRT) on a machine already running the rest of the
# services. Raise it rather than making the build order matter.
# The SSR bundle peaks just over 4 GB — roughly 6000 modules plus 21 MB of
# generated node schemas in the graph — so a 4 GB ceiling aborts the build at
# exit 134 after about forty seconds. `docker compose up --build`, the
# documented way to run this, could not complete on any machine.
ENV NODE_OPTIONS=--max-old-space-size=6144

# The frontend build compiles the TypeScript SDK and serves it from /public, so
# the SDK sources are part of the build context.
COPY sdk/typescript ./sdk/typescript
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/.npmrc ./frontend/
WORKDIR /src/frontend
RUN pnpm install --frozen-lockfile

COPY frontend ./

ARG VITE_API_URL
ARG VITE_RELAY_URL
ARG VITE_PUBLIC_URL
ARG VITE_DISABLE_CAPTCHA
ARG VITE_CLOUDFLARE_TURNSTILE_SITE_KEY
ARG VITE_INBOUND_EMAIL_DOMAIN
# Hosting platforms assign a hostname at create time and can only pass the bare
# host into a blueprint, so accept that shape too and compose the URL below.
ARG VITE_API_HOST
ARG VITE_APP_HOST
# This image only ever builds the self-hosted edition, and the flag is read at
# BUILD time. Unset, the bundle ships hosted-only UI: a Google sign-in button
# with no provider behind it, the onboarding questionnaire, a credit balance.
ENV VITE_NOCLICK_LOCAL=1
ENV NOCLICK_BUNDLE_SERVER=1
ENV VITE_RELAY_URL=$VITE_RELAY_URL \
    VITE_DISABLE_CAPTCHA=$VITE_DISABLE_CAPTCHA \
    VITE_CLOUDFLARE_TURNSTILE_SITE_KEY=$VITE_CLOUDFLARE_TURNSTILE_SITE_KEY \
    VITE_INBOUND_EMAIL_DOMAIN=$VITE_INBOUND_EMAIL_DOMAIN
RUN VITE_API_URL="${VITE_API_URL:-${VITE_API_HOST:+https://$VITE_API_HOST}}" \
    VITE_PUBLIC_URL="${VITE_PUBLIC_URL:-${VITE_APP_HOST:+https://$VITE_APP_HOST}}" \
    VITE_RELAY_URL="${VITE_RELAY_URL:-${VITE_API_HOST:+wss://$VITE_API_HOST/relay}}" \
    pnpm run build

# The server build bundles every dependency (NOCLICK_BUNDLE_SERVER, read by
# vite.config.ts), so the runtime needs only the serve process and the packages
# kept external there, at the versions the lockfile resolved.
RUN mkdir /runtime && cd /runtime && npm init -y >/dev/null \
    && specs=$(for p in react react-dom react-router @react-router/node @react-router/serve; do \
           printf '%s@%s ' "$p" "$(node -p "require('/src/frontend/node_modules/$p/package.json').version")"; done) \
    && npm install --omit=dev --ignore-scripts --no-audit --no-fund $specs \
    && npm cache clean --force


FROM node:22-alpine AS runtime

RUN apk add --no-cache tini && adduser -D -u 10002 noclick

WORKDIR /app
# package.json carries "type": "module", which is how node reads the server build.
COPY frontend/package.json ./
COPY --from=build /runtime/node_modules ./node_modules
COPY --from=build /src/frontend/build ./build
COPY --from=build /src/frontend/public ./public
COPY docker/frontend-entrypoint.sh /usr/local/bin/noclick-entrypoint

# The server only reads what is here, and root-owned files are world-readable,
# so it does not need to own them.
USER noclick
EXPOSE 3000

ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/noclick-entrypoint"]
CMD ["node_modules/.bin/react-router-serve", "./build/server/index.js"]
