"""Database pool — native asyncpg on the main event loop.

One pool, one policy. The pool lives on the app's event loop, created in
``app_lifespan`` startup (``init_native_pool``) and closed in shutdown
(``close_native_pool``). Everything that touches Postgres at runtime goes
through it:

- ``async with pool.acquire() as conn:`` yields a real pinned connection —
  every statement in the block runs on the same physical conn, and
  ``conn.transaction()`` is a real asyncpg transaction.
- Pool-level verbs (``pool.fetch`` / ``fetchrow`` / ``fetchval`` /
  ``execute`` / ``executemany``) are single-statement convenience calls.
- ``DatabasePoolMixin`` adds the ``fetch_*_async`` ergonomic layer that
  handlers inherit; it is stateless and delegates 1:1 to the pool.

``get_native_pool()`` fails fast: it raises if the pool is uninitialized or
bound to a different event loop than the caller's. Pool lifecycle is owned
by ``app_lifespan`` alone — nothing in production code closes or re-creates
the pool. Tests own their per-loop lifecycle in ``tests/conftest.py``
(``ensure_native_db_pool``).

Connection setup (``setup_asyncpg_codecs``, ``get_runtime_database_url``,
``get_asyncpg_connect_kwargs``) is shared with every other runtime asyncpg
call site — new call sites must use these rather than reading env vars or
registering codecs themselves.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import asyncpg

logger = logging.getLogger(__name__)


# ─────────────────────────── connection setup helpers ─────────────────────


async def setup_asyncpg_codecs(conn: asyncpg.Connection) -> None:
    """Register asyncpg type codecs on a fresh connection.

    Adds automatic JSONB ↔ dict conversion so callers don't have to
    ``json.dumps()`` / ``json.loads()`` around JSONB columns. Wired as the
    ``init`` callback on ``asyncpg.create_pool`` so every conn in the pool
    gets it — short-lived maintenance pools reuse it too.
    """
    import json

    def _encode_jsonb(value):
        # JSONB binary format requires the version-1 prefix byte.
        return b"\x01" + json.dumps(value).encode("utf-8")

    def _decode_jsonb(value):
        return json.loads(value[1:].decode("utf-8"))

    await conn.set_type_codec(
        "jsonb",
        encoder=_encode_jsonb,
        decoder=_decode_jsonb,
        schema="pg_catalog",
        format="binary",
    )


_asyncpg_settings_logged = False
_runtime_url_logged = False


def get_runtime_database_url() -> Optional[str]:
    """Return the asyncpg URL for runtime traffic (pools + short-lived connects).

    Reads ``POSTGRES_POOLER_URL`` only — Supabase PgBouncer in transaction mode,
    typically ``aws-0-<region>.pooler.supabase.com:6543`` with username
    ``postgres.<project_ref>``. There is intentionally no fallback to
    ``POSTGRES_URL``: production runtime must go through PgBouncer to multiplex
    onto Supabase's bounded backend pool, and a silent fallback to a direct
    URL would hide a deploy-config bug exactly where the consequences are
    worst (connection exhaustion under load).

    ``POSTGRES_URL`` still exists for migrations, advisory locks,
    ``LISTEN``/``NOTIFY``, and one-shot scripts — anything that needs session
    state across transactions and so cannot use the pooler. No such caller
    exists in the backend hot path today (audit 2026-05-10).
    """
    global _runtime_url_logged
    pooler = os.getenv("POSTGRES_POOLER_URL")
    if not _runtime_url_logged:
        if pooler:
            logger.info("[DB] using POSTGRES_POOLER_URL (PgBouncer transaction mode)")
        else:
            logger.warning("[DB] POSTGRES_POOLER_URL is not set — no runtime database connection")
        _runtime_url_logged = True
    return pooler


def _parse_int_env(var_name: str, default: int) -> int:
    """Parse an integer env var, falling back on invalid input."""
    raw_value = os.getenv(var_name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return int(raw_value)
    except ValueError:
        logger.warning("Invalid value '%s' for %s; using default %s", raw_value, var_name, default)
        return default


def get_asyncpg_connect_kwargs() -> Dict[str, Any]:
    """Return connection kwargs tuned for environments that use PgBouncer.

    ``statement_cache_size=0`` is REQUIRED for PgBouncer transaction pooling
    — server-side prepared statements don't survive being handed to a
    different backend connection. Override via ``ASYNC_PG_STATEMENT_CACHE_SIZE``
    only when pointing at a non-pooled Postgres (local dev is fine either way).
    ``statement_timeout=30000`` is the last-line server-side deadline; the
    async handlers' own timeouts should fire first, but this catches anything
    that slips.
    """
    statement_cache_size = _parse_int_env("ASYNC_PG_STATEMENT_CACHE_SIZE", 0)
    connect_kwargs: Dict[str, Any] = {"statement_cache_size": statement_cache_size}
    server_settings = {"statement_timeout": "30000"}
    prepare_threshold = os.getenv("ASYNC_PG_PREPARE_THRESHOLD")
    if prepare_threshold:
        server_settings["prepare_threshold"] = prepare_threshold
    connect_kwargs["server_settings"] = server_settings

    global _asyncpg_settings_logged
    if not _asyncpg_settings_logged:
        logger.info(
            "[DB] asyncpg connect kwargs: %s",
            {"statement_cache_size": statement_cache_size, "server_settings": server_settings},
        )
        _asyncpg_settings_logged = True
    return connect_kwargs


# ─────────────────────────── native pool lifecycle ────────────────────────
# Module-level pool + main-loop reference. Set once by ``init_native_pool``
# during lifespan startup; cleared by ``close_native_pool`` in shutdown.

_native_pool: Optional[asyncpg.Pool] = None
_native_pool_loop: Optional[asyncio.AbstractEventLoop] = None
_init_error: Optional[str] = None

# Tuning matches the pre-refactor DB-thread pool 1:1 so this is a semantic
# no-op for the underlying Postgres. Change these if traffic patterns shift.
_POOL_MIN_SIZE = 1
_POOL_MAX_SIZE = 30
_POOL_COMMAND_TIMEOUT = 30
_POOL_ACQUIRE_TIMEOUT = 10
_POOL_MAX_INACTIVE_SECS = 300
_POOL_MAX_QUERIES = 1000


async def init_native_pool() -> None:
    """Create the asyncpg pool on the current event loop. Idempotent.

    Called from ``app_lifespan`` BEFORE ``socketio_proxy.setup()`` so any
    handler instantiation that touches DB sees a ready pool. Raises on
    misconfiguration (missing URL, connect failure) — the container should
    fail to boot rather than serve traffic without a DB.

    Post-fork constraint: under a prefork server, this MUST be called from
    lifespan and not module import. asyncpg pools hold sockets that don't
    survive fork; creating the pool post-fork per-container is the correct
    lifecycle. Prior code enforced this via a threading.enumerate() == 1
    assertion at fork time; the new pool ownership is scoped to the lifespan
    which runs post-fork by construction.
    """
    global _native_pool, _native_pool_loop, _init_error
    if _native_pool is not None:
        return  # already up

    url = get_runtime_database_url()
    if not url:
        _init_error = "POSTGRES_POOLER_URL is not set"
        raise RuntimeError(f"[DB] Cannot init native pool: {_init_error}")

    try:
        parsed = urlparse(url)
        dest = f"{parsed.hostname}:{parsed.port or 5432}"
        logger.info("[DB] Connecting native pool to %s", dest)
    except Exception:
        pass

    connect_kwargs = get_asyncpg_connect_kwargs()
    _native_pool = await asyncpg.create_pool(
        url,
        min_size=_POOL_MIN_SIZE,
        max_size=_POOL_MAX_SIZE,
        command_timeout=_POOL_COMMAND_TIMEOUT,
        timeout=_POOL_ACQUIRE_TIMEOUT,
        max_inactive_connection_lifetime=_POOL_MAX_INACTIVE_SECS,
        max_queries=_POOL_MAX_QUERIES,
        init=setup_asyncpg_codecs,
        **connect_kwargs,
    )
    _native_pool_loop = asyncio.get_running_loop()
    _init_error = None
    logger.info("[DB] Native pool created on main event loop (max_size=%d)", _POOL_MAX_SIZE)


async def close_native_pool() -> None:
    """Close the pool. Called from ``app_lifespan`` shutdown.

    Clear the process-global reference before awaiting so new work fails fast
    once shutdown starts. If graceful close is cancelled (for example by the
    lifespan timeout) or raises, terminate the captured pool synchronously;
    otherwise the cleared reference would make its sockets unreachable and
    impossible to clean up.
    """
    global _native_pool, _native_pool_loop
    if _native_pool is None:
        return
    pool_to_close, _native_pool = _native_pool, None
    _native_pool_loop = None
    try:
        await pool_to_close.close()
        logger.info("[DB] Native pool closed cleanly")
    except asyncio.CancelledError:
        try:
            pool_to_close.terminate()
        except Exception as terminate_error:
            logger.warning(
                "[DB] Native pool terminate after cancelled close failed: %s",
                terminate_error,
            )
        raise
    except Exception as e:
        logger.warning("[DB] Native pool close failed: %s", e)
        try:
            pool_to_close.terminate()
        except Exception as terminate_error:
            logger.warning(
                "[DB] Native pool terminate after close failure failed: %s",
                terminate_error,
            )


def get_native_pool() -> asyncpg.Pool:
    """Return the native pool. Raises RuntimeError if uninitialized.

    Fail-fast so a pre-lifespan caller or a config gap surfaces at the call
    site instead of leaking as a mystery hang or NoneType error downstream.

    If the pool is bound to a stale event loop (e.g. pytest-asyncio's
    per-test loop cycle), raises the same way — the caller is expected to
    re-init via ``init_native_pool()`` on the correct loop.
    """
    if _native_pool is None:
        raise RuntimeError(
            "[DB] Native pool not initialized. "
            "init_native_pool() must run in app_lifespan startup before any "
            f"DB access. Cause: {_init_error or 'lifespan startup has not run yet'}"
        )
    # Cross-loop check: asyncpg pools are bound to the loop they were
    # created on. Using one from a different loop deadlocks the calling
    # coroutine. Surface it loudly so test/lifespan bugs fail fast rather
    # than hanging in production.
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    if current is not None and _native_pool_loop is not None and current is not _native_pool_loop:
        raise RuntimeError(
            "[DB] Native pool is bound to a different event loop than the "
            "caller's. This is a lifecycle bug — the pool was created on one "
            "loop and is being used from another. Re-init on the current loop."
        )
    return _native_pool


def get_pool_status() -> dict:
    """Snapshot for the container.health emitter and monitoring."""
    if _native_pool is None:
        return {"status": "unavailable", "size": 0, "max_size": 0, "idle_size": 0}
    try:
        return {
            "status": "healthy" if not _native_pool.is_closing() else "closing",
            "size": _native_pool.get_size(),
            "idle_size": _native_pool.get_idle_size(),
            "max_size": _native_pool.get_max_size(),
            "is_closing": _native_pool.is_closing(),
        }
    except Exception as e:
        logger.debug("[DB] get_pool_status failed: %s", e)
        return {"status": "error", "error": str(e)}


# ─────────────────────────── DatabasePoolMixin ────────────────────────────
# The ergonomic layer the ~72 handler / helper classes inherit. Stateless:
# every method delegates 1:1 to the native pool.


class DatabasePoolMixin:
    """Async database access for handlers, backed by the native pool.

    ``get_pool()`` returns the native ``asyncpg.Pool`` — use
    ``async with pool.acquire() as conn:`` for multi-statement blocks
    (real pinning) and ``async with conn.transaction():`` for atomicity.
    The ``fetch_*_async`` / ``execute_query_async`` helpers are
    single-statement conveniences.

    Everything here must be awaited from the main event loop. There is no
    sync surface and no worker-thread bridge — code running off-loop must
    hand its DB work to the loop (e.g. ``asyncio.run_coroutine_threadsafe``)
    rather than reach for the pool directly.
    """

    async def execute_query_async(self, query: str, *args) -> str:
        """Run a single statement; returns asyncpg's status string.

        For a ``RETURNING`` value use ``fetch_value_async``; for
        fire-and-forget writes use ``spawn(pool.execute(...))`` at the call
        site so the durability tradeoff is visible where it's made.
        """
        return await get_native_pool().execute(query, *args)

    async def fetch_value_async(self, query: str, *args, timeout: float = _POOL_COMMAND_TIMEOUT) -> Any:
        return await get_native_pool().fetchval(query, *args, timeout=timeout)

    async def fetch_rows_async(self, query: str, *args) -> List[Any]:
        return await get_native_pool().fetch(query, *args)

    async def fetch_row_async(self, query: str, *args) -> Any:
        return await get_native_pool().fetchrow(query, *args)

    async def get_pool(self) -> asyncpg.Pool:
        """Return the native ``asyncpg.Pool``.

        Raises (via ``get_native_pool``) if the pool is uninitialized or
        bound to another loop — pool lifecycle is owned by ``app_lifespan``
        in production and by ``ensure_native_db_pool`` in tests; nothing
        else may close or re-create it.
        """
        return get_native_pool()
