# NoClick Community — the whole application in one container.
#
# The backend, the app and an nginx front door on a single port, which is what
# makes a one-click deploy possible: hosts that give a service one URL can run
# this, and there is nothing to configure but that URL. The compose file remains
# the shape to run on a machine you control, where separate containers are worth
# their separate logs.
#
# Nothing is lost by combining them. This edition already requires exactly one
# backend process — the scheduler ticks inside it, the realtime relay lives in
# it — so there was never anything here to scale out independently.
#
# All it needs is a Postgres URL. Supabase's auth layer — GoTrue and PostgREST —
# runs inside this image against that database, served on the same origin under
# the paths supabase-js addresses, so there is no project to create and nothing
# to paste: the entrypoint prepares the database and mints the instance's own
# secrets. Point SUPABASE_URL at a real Supabase project to use one instead.

# ── The app's browser bundle and server build ────────────────────────────────
FROM node:22-bookworm-slim AS frontend

RUN corepack enable
WORKDIR /src
# Vite's production build is the memory high-water mark of the whole image, and
# it needs more than V8's default ceiling: at 4096 the build aborts inside
# JsonParse with "JavaScript heap out of memory". Give Docker itself at least
# 8 GiB, or the kernel kills the build instead (exit 137).
ENV NODE_OPTIONS=--max-old-space-size=6144
# This image IS the self-hosted edition, and the flag is read at BUILD time by
# the bundle. Without it the app ships hosted-only UI: a Google sign-in button
# with no provider behind it, the onboarding questionnaire, a credit balance.
ENV VITE_NOCLICK_LOCAL=1

COPY sdk/typescript ./sdk/typescript
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/.npmrc ./frontend/
WORKDIR /src/frontend
RUN pnpm install --frozen-lockfile

COPY frontend ./
# No VITE_API_URL on purpose. The bundle asks the origin it was served from,
# which is the whole point of this image — and it means one build works for
# every hostname anyone deploys it under.
ARG VITE_INBOUND_EMAIL_DOMAIN
ENV VITE_INBOUND_EMAIL_DOMAIN=$VITE_INBOUND_EMAIL_DOMAIN
RUN pnpm run build

# Production dependencies only, for the runtime image.
RUN pnpm prune --prod --ignore-scripts


# ── Agent CLI harnesses ──────────────────────────────────────────────────────
# codex, claude and opencode run as subprocesses of the backend, signed in with
# the ChatGPT / Claude subscription or API key attached to the agent node. The
# pins are the versions the agent runtime was verified against
# (backend/nodes/agent/config/_cli_models.json); a test keeps them in step.
FROM node:22-bookworm-slim AS cli
RUN npm install -g --prefix /opt/noclick-cli \
        @openai/codex@0.147.0 \
        @anthropic-ai/claude-code@2.1.231 \
        opencode-ai@1.18.18 \
    && npm cache clean --force


# ── Python dependencies ──────────────────────────────────────────────────────
FROM python:3.12-slim AS backend-deps

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt ./
RUN pip install -r requirements.txt


# ── The image ────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx \
        gettext-base \
        libsndfile1 \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Node from the official image rather than Debian's, so the app runs on the
# version it was built against. Both are bookworm, so the binary is at home.
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node

ENV PATH="/opt/noclick-cli/bin:/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NOCLICK_LOCAL=1
COPY --from=backend-deps /opt/venv /opt/venv
COPY --from=cli /opt/noclick-cli /opt/noclick-cli

WORKDIR /app
COPY backend ./backend
COPY infra/supabase/migrations ./infra/supabase/migrations
COPY docker/bootstrap.py ./docker/bootstrap.py
COPY --from=frontend /src/frontend/build ./frontend/build
COPY --from=frontend /src/frontend/public ./frontend/public
COPY --from=frontend /src/frontend/node_modules ./frontend/node_modules
COPY --from=frontend /src/frontend/package.json ./frontend/package.json

COPY docker/gateway/single-origin.conf.template /etc/nginx/single-origin.conf.template
COPY docker/gateway/noclick-proxy.conf /etc/nginx/noclick-proxy.conf
COPY docker/gateway/supabase-upstreams.conf /etc/nginx/supabase-upstreams.conf
COPY docker/single-origin-entrypoint.sh /usr/local/bin/noclick-entrypoint

# Supabase's API layer, so an instance needs a database and nothing else. Both
# are statically linked, so they are two files rather than two base images —
# and both are the same builds their own published images run. GoTrue carries
# its migrations inside the binary; `gotrue migrate` is what creates auth.users.
COPY --from=supabase/gotrue:v2.196.0 /usr/local/bin/auth /usr/local/bin/gotrue
COPY --from=postgrest/postgrest:v16.1 /bin/postgrest /usr/local/bin/postgrest

# Runs unprivileged: this process executes user-authored workflow code. nginx
# ships expecting root — its pid file and its `user` directive both assume it —
# so the packaged config is pointed somewhere writable instead. Hence also the
# port above 1024 below.
RUN sed -i 's|^pid .*|pid /tmp/nginx.pid;|; s|^user .*||' /etc/nginx/nginx.conf \
    && useradd --create-home --uid 10001 noclick \
    && mkdir -p /var/lib/noclick /app/logs /var/log/nginx /etc/nginx/supabase \
                /var/lib/nginx/body /var/lib/nginx/proxy /var/lib/nginx/fastcgi \
                /var/lib/nginx/uwsgi /var/lib/nginx/scgi \
    && chown -R noclick:noclick /var/lib/noclick /app/logs /var/lib/nginx /var/log/nginx \
                                /etc/nginx/conf.d /etc/nginx/supabase \
    && ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log
ENV NOCLICK_HOME=/var/lib/noclick
VOLUME ["/var/lib/noclick"]

USER noclick
ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/noclick-entrypoint"]
