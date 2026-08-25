# NoClick Community — backend (FastAPI + Socket.IO + in-process scheduler/relay).
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


FROM python:3.12-slim AS runtime

# libsndfile is soundfile's runtime library; the rest is what outbound TLS and
# a readable `docker logs` timestamp need.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NOCLICK_LOCAL=1
COPY --from=deps /opt/venv /opt/venv

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
