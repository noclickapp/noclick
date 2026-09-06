# NoClick Community — backend (FastAPI + Socket.IO + in-process scheduler/relay),
# with the agent CLI harnesses the single-origin image also ships: an agent node
# on Codex or Claude Code must work from the compose stack too, not only the
# one-click image.
#
# The wheels are built in a throwaway stage so the runtime image carries no
# compiler: a few dependencies (quickjs, soundfile) have no universal wheel and
# would otherwise pull ~400 MB of toolchain into production.

FROM python:3.12-slim AS deps

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install -r requirements.txt


# ── Agent CLI harnesses ──────────────────────────────────────────────────────
# codex, claude, opencode, openclaw and hermes run as subprocesses of the backend, signed in with
# the ChatGPT / Claude subscription or API key attached to the agent node. The
# pins are the versions the agent runtime was verified against
# (backend/nodes/agent/config/_cli_models.json); a test keeps them in step.
FROM node:22-bookworm-slim AS cli
RUN npm install -g --prefix /opt/noclick-cli \
        @openai/codex@0.153.4 \
        @anthropic-ai/claude-code@2.1.261 \
        opencode-ai@1.18.29 \
        openclaw@2026.9.1 \
    && npm cache clean --force

# hermes is a Python CLI that pins its own openai SDK, which the backend's venv
# cannot share; it gets a venv of its own, built on the same interpreter path
# as the runtime stage so the copy stays valid. Pinned to the ref the agent
# runtime is tested against (_cli_models.json "hermes.ref").
FROM python:3.12-slim AS hermes
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*
# hermes refuses wheel builds; it is installed editable from a checkout, the
# way its own installer and the hosted runtime do.
RUN git clone --filter=blob:none https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent \
    && git -C /opt/hermes-agent checkout v2026.8.31 \
    && python -m venv /opt/hermes \
    && /opt/hermes/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/hermes/bin/pip install --no-cache-dir -e "/opt/hermes-agent[mcp]" \
    && rm -rf /opt/hermes-agent/.git \
    && /opt/hermes/bin/hermes --version



FROM python:3.12-slim AS runtime

# libsndfile is soundfile's runtime library; git is what the harness CLIs and
# agent workspaces expect; the rest is what outbound TLS and a readable
# `docker logs` timestamp need.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 \
        ca-certificates \
        git \
        tini \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/noclick-cli/bin:/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NOCLICK_LOCAL=1
COPY --from=deps /opt/venv /opt/venv
# The harness CLIs are node programs; node itself rides along from the cli stage.
COPY --from=cli /usr/local/bin/node /usr/local/bin/node
COPY --from=cli /opt/noclick-cli /opt/noclick-cli
COPY --from=hermes /opt/hermes /opt/hermes
COPY --from=hermes /opt/hermes-agent /opt/hermes-agent
RUN ln -s /opt/hermes/bin/hermes /opt/noclick-cli/bin/hermes

# Runs unprivileged: this process executes user-authored workflow code.
RUN useradd --create-home --uid 10001 noclick
WORKDIR /app

COPY --chown=noclick:noclick backend ./backend
COPY --chown=noclick:noclick infra/supabase/migrations ./infra/supabase/migrations
COPY --chown=noclick:noclick docker/bootstrap.py ./docker/bootstrap.py
COPY docker/backend-entrypoint.sh /usr/local/bin/noclick-entrypoint

# Agent workspaces, local volumes and generated state.
# `logs/` too: the builder opens a rotating log under the repository root at
# import time and a failure there takes down startup, not just logging.
RUN mkdir -p /var/lib/noclick /app/logs \
    && chown noclick:noclick /var/lib/noclick /app/logs
ENV NOCLICK_HOME=/var/lib/noclick
VOLUME ["/var/lib/noclick"]

USER noclick
WORKDIR /app/backend
EXPOSE 8000

# One process only. The scheduler ticks in-process and the relay hub is
# in-process, so a second worker means duplicate runs and lost events —
# see docs/self-hosting.md.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/noclick-entrypoint"]
CMD ["sh", "-c", "exec python -m uvicorn server:web_app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
