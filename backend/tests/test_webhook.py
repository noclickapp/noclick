"""
Test suite for webhook system.

Tests cover:
1. WebhookManager utility functions (create/delete webhooks, schema detection)
2. send_event with user_id parameter (broadcasts via Event Relay)
3. Webhook trigger node execution
4. Webhook HTTP routes (handle_webhook_payload, receive_webhook endpoint)

Key testing primitives:
- send_event with user_id uses broadcast_to_user_safe instead of Socket.IO
- Webhook payload is passed to workflow execution via mocked output
"""

import pytest
import pytest_asyncio
import asyncio
import uuid
import json
import base64
from typing import Dict, Any, List
from unittest.mock import patch, AsyncMock, MagicMock
from pydantic import BaseModel

from tests.utils.base_handler_test import BaseHandlerTest
from tests.mocks.mock_asyncpg import configure_mock_query_responses, clear_executed_queries, get_executed_queries
from utils import webhook_delivery


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_mock_state():
    """Reset mock state before each test."""
    clear_executed_queries()
    configure_mock_query_responses({})
    yield
    clear_executed_queries()
    configure_mock_query_responses({})


@pytest.fixture
def mock_broadcast():
    """Mock the broadcast_to_user_safe function for testing send_event with user_id."""
    broadcast_calls = []

    async def mock_broadcast_to_user_safe(
        user_id: str,
        event: BaseModel,
        workflow_id=None,
        timeout=5.0,
    ):
        broadcast_calls.append({
            'user_id': user_id,
            'event': event,
            'event_name': getattr(event, 'event_name', None),
            'data': event.model_dump() if hasattr(event, 'model_dump') else {},
            'workflow_id': workflow_id,
        })
        return {'success': True, 'sentCount': 1, 'connectionCount': 1}

    # Patch the import location in wss.sender module where it's imported from
    with patch('utils.event_relay.broadcast_to_user_safe', new=mock_broadcast_to_user_safe):
        yield broadcast_calls


class _FakeRelay:
    """A registered relay client — a developer's backend, in delivery terms."""

    def __init__(self, register_ok=True):
        self.register_ok = register_ok
        self.registered = []
        self.unregistered = []

    def is_connected(self):
        return True

    def session_id(self):
        return "session-1"

    async def register(self, webhook_id, user_id=None):
        self.registered.append(webhook_id)
        return self.register_ok

    async def unregister(self, webhook_id):
        self.unregistered.append(webhook_id)
        return True

    async def register_user(self, user_id):
        return 0

    async def unregister_user(self, user_id):
        return 0

    async def reconnect(self):
        return True


@pytest.fixture
def webhook_domain(monkeypatch):
    """Mint wildcard-subdomain URLs on a test domain."""
    for name in ("PUBLIC_WEBHOOK_URL", "WEBHOOK_URL_BASE", "PUBLIC_API_URL", "WEBHOOK_DOMAIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(webhook_delivery, "_wildcard_domain", "hooks.example.test")


@pytest.fixture
def relay(monkeypatch, webhook_domain):
    """Local development: deliveries come through a registered relay client."""
    fake = _FakeRelay()
    monkeypatch.setattr(webhook_delivery, "_relay", fake)
    return fake


@pytest.fixture
def direct_delivery(monkeypatch, webhook_domain):
    """Production or self-hosted: deliveries reach this backend directly."""
    monkeypatch.setattr(webhook_delivery, "_relay", None)


# ============================================================================
# Mock pool helpers
# ============================================================================


def _mock_pool():
    """MagicMock pool whose ``acquire()`` yields a single shared AsyncMock conn."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


def _webhook_row(webhook_id, *, is_active=True, secret_set=False,
                 external_webhook_id=None, registered_operation=None,
                 registered_credential_id=None):
    """A full webhooks-row dict as get_or_create_webhook's SELECT returns it."""
    return {
        'id': webhook_id,
        'is_active': is_active,
        'secret_set': secret_set,
        'external_webhook_id': external_webhook_id,
        'registered_operation': registered_operation,
        'registered_credential_id': registered_credential_id,
    }


def _deregister_pool(owner_id, webhook_rows):
    """Pool wired for the deregister_node_webhooks flow: owner lookup +
    webhooks-row fetch + recorded UPDATEs."""
    pool, conn = _mock_pool()
    conn.fetchrow = AsyncMock(return_value={'owner_id': owner_id})
    conn.fetch = AsyncMock(return_value=webhook_rows)
    return pool, conn


# ============================================================================
# WebhookManager Tests
# ============================================================================

@pytest.mark.asyncio
class TestWebhookManager:
    """Test WebhookManager utility class."""

    async def test_get_or_create_webhook_creates_new(self, relay):
        """A missing row is INSERTed; the fresh row reports empty registration
        state (nothing registered provider-side, no secret)."""
        from utils.webhook_manager import WebhookManager

        user_id = str(uuid.uuid4())
        workflow_id = uuid.uuid4()
        node_id = "webhook-node-1"
        webhook_id = str(uuid.uuid4())

        pool, conn = _mock_pool()
        conn.fetchrow = AsyncMock(side_effect=[
            None,  # SELECT — no existing webhook
            {'id': webhook_id, 'is_active': True},  # INSERT ... RETURNING id, is_active
        ])

        result = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        assert result['webhook_id'] == webhook_id
        assert result['webhook_url'] == f"https://{webhook_id}.hooks.example.test"
        assert result['relay_connected'] is True
        assert result['is_production'] is False
        # A fresh row carries empty registration state
        assert result['is_active'] is True
        assert result['secret_set'] is False
        assert result['external_webhook_id'] is None
        assert result['registered_operation'] is None
        assert result['registered_credential_id'] is None
        # The old `reactivated` key is gone
        assert 'reactivated' not in result

        assert relay.registered == [webhook_id]

    async def test_get_or_create_webhook_returns_existing(self, relay):
        """An existing ACTIVE row is returned with its registration state
        passed through, and no auto-activation UPDATE is issued."""
        from utils.webhook_manager import WebhookManager

        user_id = str(uuid.uuid4())
        workflow_id = uuid.uuid4()
        node_id = "webhook-node-1"
        existing_webhook_id = str(uuid.uuid4())

        pool, conn = _mock_pool()
        conn.fetchrow = AsyncMock(return_value=_webhook_row(
            existing_webhook_id,
            is_active=True,
            secret_set=True,
            external_webhook_id="ext-42",
            registered_operation="on_issue_created",
            registered_credential_id="cred-1",
        ))

        result = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        assert result['webhook_id'] == existing_webhook_id
        assert result['webhook_url'] == f"https://{existing_webhook_id}.hooks.example.test"
        assert result['is_active'] is True
        assert result['secret_set'] is True
        assert result['external_webhook_id'] == "ext-42"
        assert result['registered_operation'] == "on_issue_created"
        assert result['registered_credential_id'] == "cred-1"
        # Active row → nothing to auto-activate
        conn.execute.assert_not_called()

    async def test_get_or_create_webhook_reactivates_simple_inactive_row(self, relay):
        """An inactive row WITHOUT the registered_operation marker (plain
        webhook/cron/alarm — nothing registered provider-side) re-activates on
        touch: deactivation only meant "node was deleted"."""
        from utils.webhook_manager import WebhookManager

        webhook_id = str(uuid.uuid4())
        pool, conn = _mock_pool()
        conn.fetchrow = AsyncMock(return_value=_webhook_row(
            webhook_id, is_active=False, registered_operation=None,
        ))

        result = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=str(uuid.uuid4()),
            workflow_id=uuid.uuid4(),
            node_id="webhook-node-1",
        )

        assert result['is_active'] is True
        conn.execute.assert_awaited_once()
        activate_sql = conn.execute.await_args.args[0]
        assert "is_active = true" in activate_sql

    async def test_get_or_create_webhook_marked_row_stays_inactive(self, relay):
        """An inactive row CARRYING the registered_operation marker stays
        inactive: only a successful re-registration
        (persist_registration_state) may activate it, so a torn-down trigger
        can't present as live just because its config panel was opened."""
        from utils.webhook_manager import WebhookManager

        webhook_id = str(uuid.uuid4())
        pool, conn = _mock_pool()
        conn.fetchrow = AsyncMock(return_value=_webhook_row(
            webhook_id, is_active=False, registered_operation="on_new_row",
        ))

        result = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=str(uuid.uuid4()),
            workflow_id=uuid.uuid4(),
            node_id="webhook-node-1",
        )

        assert result['is_active'] is False
        assert result['registered_operation'] == "on_new_row"
        conn.execute.assert_not_called()

    async def test_get_or_create_webhook_production_mode(self, direct_delivery):
        """Test webhook creation in production (relay_connected always True)."""
        from utils.webhook_manager import WebhookManager

        user_id = str(uuid.uuid4())
        workflow_id = uuid.uuid4()
        node_id = "webhook-node-1"
        webhook_id = str(uuid.uuid4())

        pool, conn = _mock_pool()
        conn.fetchrow = AsyncMock(return_value=_webhook_row(webhook_id))

        result = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        assert result['is_production'] is True
        assert result['relay_connected'] is True

    async def test_get_or_create_webhook_registration_fails(self, relay):
        """Test relay_connected is False when registration fails."""
        from utils.webhook_manager import WebhookManager

        user_id = str(uuid.uuid4())
        workflow_id = uuid.uuid4()
        node_id = "webhook-node-1"
        webhook_id = str(uuid.uuid4())

        pool, conn = _mock_pool()
        conn.fetchrow = AsyncMock(return_value=_webhook_row(webhook_id))
        relay.register_ok = False

        result = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        # relay_connected should be False because registration failed
        assert result['relay_connected'] is False
        assert result['is_production'] is False

    async def test_delete_webhook_success(self, relay):
        """Test successful webhook deletion."""
        from utils.webhook_manager import WebhookManager

        workflow_id = str(uuid.uuid4())
        node_id = "webhook-node-1"
        webhook_id = str(uuid.uuid4())

        # Create mock pool
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={'id': webhook_id})
        mock_conn.execute = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await WebhookManager.delete_webhook(
            pool=mock_pool,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        assert result is True
        assert relay.unregistered == [webhook_id]

    async def test_delete_webhook_not_found(self, relay):
        """Test deleting a webhook that doesn't exist."""
        from utils.webhook_manager import WebhookManager

        workflow_id = str(uuid.uuid4())
        node_id = "webhook-node-1"

        # Create mock pool - no webhook found
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await WebhookManager.delete_webhook(
            pool=mock_pool,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        assert result is False
        assert relay.unregistered == []

    def test_schema_requires_webhook_with_marker(self):
        """Test schema_requires_webhook with x-requires-webhook marker."""
        from utils.webhook_manager import WebhookManager

        schema = {
            "x-requires-webhook": True,
            "properties": {
                "message": {"type": "string"}
            }
        }

        assert WebhookManager.schema_requires_webhook(schema) is True

    def test_schema_requires_webhook_with_widget(self):
        """Test schema_requires_webhook with ui:widget='webhook' field."""
        from utils.webhook_manager import WebhookManager

        schema = {
            "properties": {
                "webhook_url": {
                    "type": "string",
                    "ui:widget": "webhook"
                },
                "other_field": {"type": "string"}
            }
        }

        assert WebhookManager.schema_requires_webhook(schema) is True

    def test_schema_requires_webhook_without_webhook(self):
        """Test schema_requires_webhook returns False for normal schema."""
        from utils.webhook_manager import WebhookManager

        schema = {
            "properties": {
                "message": {"type": "string"},
                "chat_id": {"type": "string"}
            }
        }

        assert WebhookManager.schema_requires_webhook(schema) is False

    def test_get_webhook_field(self):
        """Test get_webhook_field extracts the correct field name."""
        from utils.webhook_manager import WebhookManager

        schema = {
            "properties": {
                "webhook_url": {
                    "type": "string",
                    "ui:widget": "webhook"
                },
                "other_field": {"type": "string"}
            }
        }

        assert WebhookManager.get_webhook_field(schema) == "webhook_url"


# ============================================================================
# handle_operation_change Tests
# ============================================================================

@pytest.mark.asyncio
class TestHandleOperationChange:
    """Test WebhookManager.handle_operation_change cleans up resources
    when a node's operation switches away from a webhook-requiring one."""

    async def test_noop_when_same_operation(self):
        from utils.webhook_manager import WebhookManager
        result = await WebhookManager.handle_operation_change(
            pool=None,
            node_type="automation-google-sheets",
            workflow_id="wf-1",
            node_id="n-1",
            old_operation="on_new_row",
            new_operation="on_new_row",
        )
        assert result is False

    async def test_noop_when_switching_between_non_webhook_ops(self):
        from utils.webhook_manager import WebhookManager
        pool = MagicMock()
        result = await WebhookManager.handle_operation_change(
            pool=pool,
            node_type="automation-google-sheets",
            workflow_id="wf-1",
            node_id="n-1",
            old_operation="read_sheet_data",
            new_operation="append_rows_to_sheet",
        )
        assert result is False

    async def test_trigger_to_action_reconciles(self):
        """Switching off a trigger op delegates to the reconciler — the
        level-triggered converger owns teardown (row context drives provider
        cleanup); this hook passes no old-vs-new state (the old_config
        plumbing raced the debounced mirror and orphaned provider hooks,
        2026-07-19). Detailed convergence behavior is pinned in
        tests/test_webhook_reconciler.py."""
        from utils.webhook_manager import WebhookManager
        workflow_id = str(uuid.uuid4())
        pool = MagicMock()
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = {"state": "deregistered"}
            result = await WebhookManager.handle_operation_change(
                pool=pool,
                node_type="automation-google-sheets",
                workflow_id=workflow_id,
                node_id="n-1",
                old_operation="on_new_row",
                new_operation="append_rows_to_sheet",
                user_id="user-1",
            )
        assert result is True
        mock_rec.assert_awaited_once_with(
            pool, workflow_id, "n-1", user_id="user-1", org_id=None,
            nodes_override=None,
        )

    async def test_trigger_to_trigger_reconciles_once(self):
        """webhook op → DIFFERENT webhook op is ONE reconcile, not a
        deregister-then-register sequence this hook choreographs."""
        from utils.webhook_manager import WebhookManager
        pool = MagicMock()
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = {"state": "registered"}
            result = await WebhookManager.handle_operation_change(
                pool=pool,
                node_type="automation-linear",
                workflow_id=str(uuid.uuid4()),
                node_id="n-1",
                old_operation="on_issue_created",
                new_operation="on_issue_updated",
                user_id="user-1",
            )
        assert result is True
        assert mock_rec.await_count == 1

    async def test_reconcile_no_op_returns_false(self):
        # The panel already converged (fingerprint match) → this hook reports
        # no action taken.
        from utils.webhook_manager import WebhookManager
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = {"state": "live"}
            result = await WebhookManager.handle_operation_change(
                pool=MagicMock(),
                node_type="automation-linear",
                workflow_id=str(uuid.uuid4()),
                node_id="n-1",
                old_operation="on_issue_created",
                new_operation="on_issue_updated",
            )
        assert result is False

    async def test_reconcile_exception_is_contained(self):
        from utils.webhook_manager import WebhookManager
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.side_effect = RuntimeError("provider 500")
            result = await WebhookManager.handle_operation_change(
                pool=MagicMock(),
                node_type="automation-linear",
                workflow_id=str(uuid.uuid4()),
                node_id="n-1",
                old_operation="on_issue_created",
                new_operation="append_rows_to_sheet",
            )
        assert result is False

    async def test_switching_to_trigger_reconciles_headlessly(self):
        """action → trigger op reconciles too: a headless MCP/builder
        set_operation registers without waiting for a config-panel open
        (desired-state semantics)."""
        from utils.webhook_manager import WebhookManager
        pool = MagicMock()
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = {"state": "registered"}
            result = await WebhookManager.handle_operation_change(
                pool=pool,
                node_type="automation-google-sheets",
                workflow_id="wf-1",
                node_id="n-1",
                old_operation="read_sheet_data",
                new_operation="on_new_row",
            )
        assert result is True
        assert mock_rec.await_count == 1


# ============================================================================
# handle_credential_change Tests — credential-swap leak (verified 2026-06-25
# against a WhatsApp/WAHooks user): swapping a credential on a trigger node
# left an active provider-side webhook on the OLD connection. When both
# connections naturally saw the same event (a WhatsApp group message both
# of the user's phones were in), every event produced a duplicate run.
# ============================================================================


class _MockTriggerProviderNode:
    """Mock trigger node that records cleanup invocations per credential.

    Stands in for any auto-registering trigger node (WhatsApp QR, Slack,
    Discord, Telegram, GitHub, etc.) — the diff loop in update_workflow
    cleans up via ``cleanup_external_webhook`` and the provider-specific
    behavior is opaque to the diff layer."""

    cleanup_calls: List[tuple] = []

    @classmethod
    def reset(cls):
        cls.cleanup_calls = []

    @classmethod
    async def cleanup_external_webhook(
        cls, pool, workflow_id, node_id, config, credentials=None
    ):
        cls.cleanup_calls.append((workflow_id, node_id, config, credentials))


@pytest.mark.asyncio
class TestHandleCredentialChange:
    """WebhookManager.handle_credential_change must deregister the OLD
    credential's provider webhook whenever a node's credentialIds change,
    then handle the webhooks row: deactivate it ONLY when it still records a
    swapped-away credential (or is a legacy pre-marker row), and self-heal
    via register_node_webhooks.

    The mock node + patched NODE_REGISTRY makes this provider-agnostic so
    the same hook covers every auto-registering trigger node."""

    @pytest.fixture(autouse=True)
    def _patch_registry(self):
        from nodes.core.registry import NODE_REGISTRY
        _MockTriggerProviderNode.reset()
        with patch.dict(NODE_REGISTRY, {"mock-trigger": _MockTriggerProviderNode}, clear=False):
            yield

    def _pool_with_row(self, row):
        """Pool whose webhooks-row fetch returns *row* and records UPDATEs."""
        pool, conn = _mock_pool()
        conn.fetchrow = AsyncMock(return_value=row)
        return pool, conn

    @staticmethod
    def _deactivations(conn):
        return [c for c in conn.execute.await_args_list if "is_active = false" in c.args[0]]

    async def test_noop_when_no_credential_change(self):
        from utils.webhook_manager import WebhookManager
        pool = MagicMock()
        old_cfg = {"operation": "receive_message", "credentialIds": {"x": "A"}, "body": "foo"}
        new_cfg = {"operation": "receive_message", "credentialIds": {"x": "A"}, "body": "bar"}
        result = await WebhookManager.handle_credential_change(
            pool, "mock-trigger", str(uuid.uuid4()), "n-1", old_cfg, new_cfg, user_id="user-1",
        )
        assert result == 0
        assert _MockTriggerProviderNode.cleanup_calls == []

    async def test_credential_swap_reconciles(self):
        """cred A → cred B delegates to the reconciler: the fingerprint covers
        the credential, and provider teardown of the OLD registration resolves
        the row's registered_credential_id inside deregister (no old-credential
        plumbing here — it raced the panel's own re-register). Detailed
        convergence behavior is pinned in tests/test_webhook_reconciler.py."""
        from utils.webhook_manager import WebhookManager
        workflow_id = str(uuid.uuid4())
        pool = MagicMock()
        old_cfg = {"operation": "receive_message", "credentialIds": {"x": "cred-A"}}
        new_cfg = {"operation": "receive_message", "credentialIds": {"x": "cred-B"}}
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = {"state": "registered"}
            result = await WebhookManager.handle_credential_change(
                pool, "mock-trigger", workflow_id, "n-1", old_cfg, new_cfg, user_id="user-1",
            )
        assert result == 1
        mock_rec.assert_awaited_once_with(
            pool, workflow_id, "n-1", user_id="user-1", org_id=None,
            nodes_override=None,
        )

    async def test_credential_removed_reconciles(self):
        from utils.webhook_manager import WebhookManager
        pool = MagicMock()
        old_cfg = {"operation": "receive_message", "credentialIds": {"x": "cred-A"}}
        new_cfg = {"operation": "receive_message", "credentialIds": {}}
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = {"state": "unregistered"}
            result = await WebhookManager.handle_credential_change(
                pool, "mock-trigger", str(uuid.uuid4()), "n-1", old_cfg, new_cfg, user_id="user-1",
            )
        assert result == 1
        assert mock_rec.await_count == 1

    async def test_multi_credential_swap_counts_each_but_reconciles_once(self):
        from utils.webhook_manager import WebhookManager
        pool = MagicMock()
        old_cfg = {"credentialIds": {"x": "cred-X-old", "y": "cred-Y-old"}}
        new_cfg = {"credentialIds": {"x": "cred-X-new", "y": "cred-Y-new"}}
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = {"state": "registered"}
            result = await WebhookManager.handle_credential_change(
                pool, "mock-trigger", str(uuid.uuid4()), "n-1", old_cfg, new_cfg, user_id="user-1",
            )
        assert result == 2          # both swaps detected
        assert mock_rec.await_count == 1  # ONE reconcile converges the node

    async def test_panel_already_converged_returns_zero(self):
        # The config panel re-registered under the new credential before this
        # hook ran: the fingerprint matches → reconcile no-ops → 0.
        from utils.webhook_manager import WebhookManager
        old_cfg = {"credentialIds": {"x": "cred-A"}}
        new_cfg = {"credentialIds": {"x": "cred-B"}}
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = {"state": "live"}
            result = await WebhookManager.handle_credential_change(
                MagicMock(), "mock-trigger", str(uuid.uuid4()), "n-1",
                old_cfg, new_cfg, user_id="user-1",
            )
        assert result == 0

    async def test_unknown_node_type_is_noop(self):
        from utils.webhook_manager import WebhookManager
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            result = await WebhookManager.handle_credential_change(
                MagicMock(), "definitely-not-registered", str(uuid.uuid4()), "n-1",
                {"credentialIds": {"x": "A"}}, {"credentialIds": {"x": "B"}},
                user_id="user-1",
            )
        assert result == 0
        mock_rec.assert_not_awaited()

    async def test_reconcile_exception_is_contained(self):
        from utils.webhook_manager import WebhookManager
        with patch("utils.webhook_manager.WebhookManager.reconcile_node",
                   new_callable=AsyncMock) as mock_rec:
            mock_rec.side_effect = RuntimeError("provider 500")
            result = await WebhookManager.handle_credential_change(
                MagicMock(), "mock-trigger", str(uuid.uuid4()), "n-1",
                {"credentialIds": {"x": "A"}}, {"credentialIds": {"x": "B"}},
                user_id="user-1",
            )
        assert result == 0


class TestStaleScheduleTick:
    """A cron-scheduler tick must only fire nodes whose CURRENT operation is a
    trigger. Pins the 2026-07-05 fix: schedules provisioned against the wrong
    operation (or surviving an operation change) ran action ops every tick."""

    def _node(self, operation=None, node_type="automation-google-sheets"):
        config = {"operation": operation} if operation else {}
        return {"id": "n1", "type": node_type, "config": config}

    def test_prunes_scheduler_tick_on_action_operation(self):
        from utils.webhook_routes import _is_stale_schedule_tick
        headers = {"x-cron-schedule-id": "sched-1"}
        assert _is_stale_schedule_tick(headers, self._node("append_rows_to_sheet"), False) is True

    def test_allows_scheduler_tick_on_trigger_operation(self):
        from utils.webhook_routes import _is_stale_schedule_tick
        headers = {"x-cron-schedule-id": "sched-1"}
        assert _is_stale_schedule_tick(headers, self._node("on_new_row"), False) is False

    def test_prunes_tick_on_node_with_no_operation(self):
        from utils.webhook_routes import _is_stale_schedule_tick
        headers = {"x-cron-schedule-id": "sched-1"}
        assert _is_stale_schedule_tick(headers, self._node(None), False) is True

    def test_ignores_non_scheduler_deliveries(self):
        from utils.webhook_routes import _is_stale_schedule_tick
        assert _is_stale_schedule_tick({}, self._node("append_rows_to_sheet"), False) is False

    def test_alarm_nodes_exempt(self):
        from utils.webhook_routes import _is_stale_schedule_tick
        headers = {"x-cron-schedule-id": "sched-1"}
        assert _is_stale_schedule_tick(headers, self._node(None, node_type="alarm"), True) is False

    def test_trigger_prefixed_node_types_exempt(self):
        from utils.webhook_routes import _is_stale_schedule_tick
        headers = {"x-cron-schedule-id": "sched-1"}
        assert _is_stale_schedule_tick(headers, self._node(None, node_type="trigger-cron"), False) is False

    def test_capitalized_scheduler_header(self):
        from utils.webhook_routes import _is_stale_schedule_tick
        headers = {"X-Cron-Schedule-Id": "sched-1"}
        assert _is_stale_schedule_tick(headers, self._node("read_sheet_data"), False) is True


class TestScheduleTickConfigGate:
    """A cron tick landing on a trigger whose SAVED config doesn't validate
    must not dispatch while the trigger is still being set up. Pins the
    2026-08-04 fix: schedule registration runs from the panel's unsaved
    context, so a 1-min poll trigger sprayed red "form_id: Field required"
    runs until the debounced graph save landed. Loud-vs-quiet is decided by
    _trigger_ever_ran (a definitive signal, not a timer)."""

    HEADERS = {"x-cron-schedule-id": "sched-1"}

    def _node(self, config: dict, node_type: str = "automation-google-forms"):
        return {"id": "n1", "type": node_type, "config": dict(config)}

    # Saved mid-setup: operation + webhook mirror landed, form_id hasn't.
    MID_SETUP_CONFIG = {
        "operation": "on_form_response",
        "schedule": {"interval": "1", "frequency": "minutes"},
        "webhook_id": "w1",
        "is_active": True,
    }

    def test_invalid_config_reports_error(self):
        from utils.webhook_routes import _schedule_tick_config_error
        err = _schedule_tick_config_error(
            self.HEADERS, self._node(self.MID_SETUP_CONFIG), False
        )
        assert err and "form_id" in err

    def test_valid_config_dispatches(self):
        # Prod-shaped config (string interval, injected _triggerPayload) must
        # judge valid — a false skip here would silence a working trigger.
        from utils.webhook_routes import _schedule_tick_config_error
        config = {**self.MID_SETUP_CONFIG, "form_id": "abc123", "_triggerPayload": {"x": 1}}
        assert _schedule_tick_config_error(self.HEADERS, self._node(config), False) is None

    def test_reference_valued_required_field_dispatches(self):
        # {{ref}} values resolve at runtime — valid pending resolution.
        from utils.webhook_routes import _schedule_tick_config_error
        config = {**self.MID_SETUP_CONFIG, "form_id": "{{other.output.id}}"}
        assert _schedule_tick_config_error(self.HEADERS, self._node(config), False) is None

    def test_non_scheduler_delivery_always_dispatches(self):
        # A real provider event must fail loudly — the error run is the only
        # record of the lost event.
        from utils.webhook_routes import _schedule_tick_config_error
        assert _schedule_tick_config_error({}, self._node(self.MID_SETUP_CONFIG), False) is None

    def test_alarm_exempt(self):
        from utils.webhook_routes import _schedule_tick_config_error
        assert _schedule_tick_config_error(
            self.HEADERS, self._node({}, node_type="alarm"), True
        ) is None

    def test_unknown_node_type_dispatches(self):
        from utils.webhook_routes import _schedule_tick_config_error
        assert _schedule_tick_config_error(
            self.HEADERS, self._node({}, node_type="not-a-real-node"), False
        ) is None


@pytest.mark.asyncio
class TestTriggerEverRan:
    """_trigger_ever_ran: clean-run history decides loud (dispatch) vs quiet
    (skip) for an invalid-config schedule tick. Must fail OPEN — a DB blip
    never silences a previously-working trigger."""

    WF = "11111111-2222-3333-4444-555555555555"

    async def test_clean_history_returns_true(self):
        from utils.webhook_routes import _trigger_ever_ran
        with patch("utils.webhook_routes.get_native_pool") as gp:
            gp.return_value.fetchrow = AsyncMock(return_value={"?column?": 1})
            assert await _trigger_ever_ran(self.WF, "n1") is True

    async def test_no_history_returns_false(self):
        from utils.webhook_routes import _trigger_ever_ran
        with patch("utils.webhook_routes.get_native_pool") as gp:
            gp.return_value.fetchrow = AsyncMock(return_value=None)
            assert await _trigger_ever_ran(self.WF, "n1") is False

    async def test_db_error_fails_open(self):
        from utils.webhook_routes import _trigger_ever_ran
        with patch("utils.webhook_routes.get_native_pool") as gp:
            gp.return_value.fetchrow = AsyncMock(side_effect=RuntimeError("db down"))
            assert await _trigger_ever_ran(self.WF, "n1") is True

    async def test_only_clean_statuses_count(self):
        # The query must exclude 'error' rows: a trigger that only ever
        # error-ticked (the pre-fix mid-setup state) has NOT run cleanly.
        from utils.webhook_routes import _trigger_ever_ran
        with patch("utils.webhook_routes.get_native_pool") as gp:
            gp.return_value.fetchrow = AsyncMock(return_value=None)
            await _trigger_ever_ran(self.WF, "n1")
            sql = gp.return_value.fetchrow.call_args.args[0]
            assert "'completed'" in sql and "'skipped'" in sql and "'error'" not in sql
