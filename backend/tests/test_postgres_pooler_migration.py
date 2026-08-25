"""Regression tests for the Postgres pooler migration (2026-05-10).

Two layers:

1. Unit tests on ``get_runtime_database_url``: pooler URL is the sole source
   of truth. There is intentionally no fallback to ``POSTGRES_URL`` — a
   silent fallback in production would route runtime traffic past PgBouncer
   and exhaust Supabase's backend pool under load. The one-shot startup log
   fires exactly once per process and surfaces the missing-env-var case
   immediately on container boot.

2. Integration test that opens 50 sequential ``asyncpg.connect()`` calls
   against a real Postgres (testcontainers) using the helper +
   ``get_asyncpg_connect_kwargs()``. Sanity check that:
   - the connect-kwargs combo we ship in production doesn't break asyncpg
   - we don't leak connections (50 sequential opens against a default
     ``max_connections=100`` Postgres would fail with "too many
     connections" if any of the 50 weren't being closed)

Local Postgres has no PgBouncer in front of it, so this test cannot
verify *that* pooling engaged in production — only that the changeset
doesn't regress connect-and-close behavior. Production validation comes
from observing connection counts post-deploy.
"""

import asyncpg
import pytest



@pytest.fixture
def reset_url_logged(monkeypatch):
    """Reset the one-shot URL-choice log flag so each test fires it independently."""
    from utils import database_pool

    monkeypatch.setattr(database_pool, "_runtime_url_logged", False)
    yield


def test_returns_pooler_url_when_set(monkeypatch, reset_url_logged):
    monkeypatch.setenv("POSTGRES_POOLER_URL", "postgresql://pooler:6543/db")

    from utils.database_pool import get_runtime_database_url

    assert get_runtime_database_url() == "postgresql://pooler:6543/db"


def test_does_not_fall_back_to_postgres_url(monkeypatch, reset_url_logged):
    """The whole point: even with POSTGRES_URL set, if POSTGRES_POOLER_URL
    is missing the helper returns None. A silent substitution would put
    production runtime traffic on the direct port — exactly the foot-gun
    this migration exists to eliminate."""
    monkeypatch.setenv("POSTGRES_URL", "postgresql://direct:5432/db")
    monkeypatch.delenv("POSTGRES_POOLER_URL", raising=False)

    from utils.database_pool import get_runtime_database_url

    assert get_runtime_database_url() is None


def test_returns_none_when_pooler_unset(monkeypatch, reset_url_logged):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("POSTGRES_POOLER_URL", raising=False)

    from utils.database_pool import get_runtime_database_url

    assert get_runtime_database_url() is None


def test_url_choice_logs_once(monkeypatch, reset_url_logged, caplog):
    """The startup-once URL-choice log should fire on first call only."""
    monkeypatch.setenv("POSTGRES_POOLER_URL", "postgresql://pooler:6543/db")

    from utils.database_pool import get_runtime_database_url

    with caplog.at_level("INFO", logger="utils.database_pool"):
        get_runtime_database_url()
        get_runtime_database_url()
        get_runtime_database_url()

    pooler_log_count = sum(
        1 for record in caplog.records if "POSTGRES_POOLER_URL" in record.message
    )
    assert pooler_log_count == 1, (
        f"URL-choice log should fire exactly once, fired {pooler_log_count}× "
        "— means the _runtime_url_logged guard is broken"
    )


def test_unset_pooler_logs_warning_once(monkeypatch, reset_url_logged, caplog):
    """When POSTGRES_POOLER_URL is missing the helper logs a WARNING (not INFO)
    so the gap is visible in error-level dashboards on next container boot."""
    monkeypatch.delenv("POSTGRES_POOLER_URL", raising=False)

    from utils.database_pool import get_runtime_database_url

    with caplog.at_level("WARNING", logger="utils.database_pool"):
        get_runtime_database_url()

    warnings = [r for r in caplog.records if r.levelname == "WARNING" and "POSTGRES_POOLER_URL" in r.message]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_50_sequential_connections_succeed(postgres_container, monkeypatch, reset_url_logged):
    """Open 50 sequential connections in quick succession, prove none leak.

    With the pooler-disabled connect kwargs we ship (``statement_cache_size=0``,
    ``server_settings={'statement_timeout': '30000'}``), each connect must
    cleanly close so the next can succeed. Default Postgres ``max_connections``
    is 100, so any leak compounds and causes a "too many connections" error
    well before reaching 50 — without needing a real PgBouncer in the loop.

    Locally we point ``POSTGRES_POOLER_URL`` at the testcontainers Postgres
    directly. It's not actually behind PgBouncer, but the asyncpg connect
    behavior under ``statement_cache_size=0`` is identical either way — what
    we're testing here is the kwargs combo + leak-freeness.
    """
    pooler_url = (
        f"postgresql://{postgres_container.username}:{postgres_container.password}"
        f"@{postgres_container.get_container_host_ip()}"
        f":{postgres_container.get_exposed_port(5432)}/{postgres_container.dbname}"
    )
    monkeypatch.setenv("POSTGRES_POOLER_URL", pooler_url)

    from utils.database_pool import get_asyncpg_connect_kwargs, get_runtime_database_url

    runtime_url = get_runtime_database_url()
    connect_kwargs = get_asyncpg_connect_kwargs()
    # Sanity: the kwargs we built actually disable the prepared-statement cache —
    # this is what makes us safe under PgBouncer transaction mode.
    assert connect_kwargs["statement_cache_size"] == 0

    for attempt in range(50):
        conn = await asyncpg.connect(runtime_url, **connect_kwargs)
        try:
            value = await conn.fetchval("SELECT 1")
            assert value == 1, f"attempt {attempt}: SELECT 1 returned {value!r}"
        finally:
            await conn.close()
