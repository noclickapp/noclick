"""Shared scaffolding for the provider trigger e2e tests (Stripe, Linear, ...).

Only generic plumbing lives here — the asyncpg pool mock, the post-refactor
``get_or_create_webhook`` row-state shape, and the ``utils.webhook_routes``
delivery stubs — so each test file's provider-specific signing/registration
logic runs for real.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# Node code resolves the DB via ``get_native_pool()``, which fail-fasts when the
# pool was never initialized (in prod that happens in ``app_lifespan``). Reuse
# the shared autouse fixture that binds a pool to each test's event loop.
from tests.conftest import ensure_native_db_pool  # noqa: F401

TEST_WEBHOOK_URL = "https://test.hooks.example.test/test"


def make_pool(*, fetchrow=None, fetch=(), execute="UPDATE 1"):
    """Async-context-manager pool mock (``async with pool.acquire() as conn``).

    Returns ``(pool, conn)``. ``conn.fetchrow``/``fetch``/``execute`` are
    AsyncMocks with the given returns; ``execute`` defaults to a 1-row UPDATE
    status tag so ``persist_registration_state``'s zero-rows guard passes.
    """
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetch = AsyncMock(return_value=list(fetch))
    conn.execute = AsyncMock(return_value=execute)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    return pool, conn


def webhook_row_state(**overrides):
    """A ``WebhookManager.get_or_create_webhook`` result in the post-refactor
    shape: URL provisioning info plus the webhooks ROW's registration state
    (the system of record the mixin's idempotency guard reads)."""
    state = {
        "webhook_id": str(uuid.uuid4()),
        "webhook_url": TEST_WEBHOOK_URL,
        "relay_connected": True,
        "is_production": False,
        "is_active": False,
        "secret_set": False,
        "external_webhook_id": None,
        "registered_operation": None,
        "registered_credential_id": None,
    }
    state.update(overrides)
    return state


def find_sql_calls(conn, snippet):
    """All ``conn.execute`` calls whose SQL contains *snippet*."""
    return [c for c in conn.execute.await_args_list if snippet in str(c.args[0])]


@pytest.fixture
def deliver_webhook(monkeypatch):
    """Install the standard delivery stubs (DB lookup, execution relay, stats,
    watch-claim) on ``utils.webhook_routes`` and return the execution mock.

    Usage: ``exec_mock = deliver_webhook(config)``. The config dict is served
    by reference, so tests may mutate it between deliveries.
    """
    from utils import webhook_routes

    def _install(config):
        exec_mock = AsyncMock(return_value={"status": "ok"})
        monkeypatch.setattr(webhook_routes, "get_webhook_config", AsyncMock(return_value=config))
        monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", exec_mock)
        monkeypatch.setattr(webhook_routes, "update_webhook_stats", lambda *a, **k: None)
        monkeypatch.setattr(webhook_routes, "_claim_google_watch_delivery", AsyncMock(return_value=True))
        return exec_mock

    return _install
