"""
End-to-end tests for the Linear trigger webhook delivery + register/deregister path.

Mirrors test_stripe_trigger_e2e.py but for Linear. Drives the REAL webhook handler
(`utils.webhook_routes.handle_webhook_payload`) with a Linear-signed event, and
exercises the row-driven register/deregister lifecycle (load_field_value's
already_registered guard, `deregister_node_webhooks`, `handle_operation_change`).

Only DB and execution stubs are mocked — everything Linear-specific runs for real.

Run: pytest nodes/tests/test_linear_trigger_e2e.py
"""
import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from nodes.tests.conftest import TEST_WEBHOOK_URL, find_sql_calls, make_pool, webhook_row_state
from utils import webhook_routes

WEBHOOK_ID = str(uuid.uuid4())
SIGNING_SECRET = "linear_e2e_test_secret_hex"


def _linear_sig(body: str, secret: str = SIGNING_SECRET) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def _linear_headers(body: str, secret: str = SIGNING_SECRET) -> dict:
    return {
        "Linear-Signature": _linear_sig(body, secret),
        "Content-Type": "application/json",
    }


def _issue_payload(action: str = "create") -> str:
    return json.dumps({
        "type": "Issue",
        "action": action,
        "data": {"id": "issue-1", "title": "Bug report", "teamId": "team-1"},
    })


def _workflow_config(operation: str = "on_issue_created") -> dict:
    return {
        "nodes": [
            {
                "id": "linear-trigger",
                "type": "automation-linear",
                "config": {
                    "operation": operation,
                    "webhook_id": WEBHOOK_ID,
                    "signing_secret": SIGNING_SECRET,
                },
            },
            {"id": "downstream", "type": "automation-log", "config": {}},
        ],
        "edges": [{"source": "linear-trigger", "target": "downstream"}],
    }


@pytest.fixture
def harness(deliver_webhook):
    config = {
        "is_active": True,
        "user_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "node_id": "linear-trigger",
        "secret": None,
        "workflow_config": _workflow_config(),
    }
    return config, deliver_webhook(config)


async def test_valid_linear_event_fires_workflow(harness):
    """Correctly-signed Linear webhook → workflow fired with injected payload."""
    _config, exec_mock = harness
    body = _issue_payload("create")
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _linear_headers(body), {}, method="POST"
    )
    assert result is True
    exec_mock.assert_awaited_once()
    kwargs = exec_mock.await_args.kwargs
    assert kwargs["start_node_id"] == "linear-trigger"
    trigger = next(n for n in kwargs["nodes"] if n["id"] == "linear-trigger")
    injected = trigger["config"]["_triggerPayload"]
    assert injected["type"] == "Issue"
    assert injected["action"] == "create"


async def test_tampered_body_rejected(harness):
    """Tampered body → 401."""
    _config, exec_mock = harness
    body = _issue_payload("create")
    headers = _linear_headers(body)
    tampered = body.replace("Bug report", "INJECTED")
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, tampered, headers, {}, method="POST", return_response=True
    )
    assert result.get("status") == 401
    exec_mock.assert_not_awaited()


async def test_wrong_secret_rejected(harness):
    """Wrong signing secret → 401."""
    _config, exec_mock = harness
    body = _issue_payload("create")
    bad_headers = _linear_headers(body, secret="attacker_secret")
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, bad_headers, {}, method="POST", return_response=True
    )
    assert result.get("status") == 401
    exec_mock.assert_not_awaited()


async def test_filter_rejects_wrong_action(harness):
    """on_issue_created op: update event (correct sig) → filtered out."""
    _config, exec_mock = harness
    body = _issue_payload("update")  # signed correctly, wrong action
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _linear_headers(body), {}, method="POST"
    )
    assert result is True  # acked
    exec_mock.assert_not_awaited()  # but not executed


async def test_filter_issue_deleted_uses_remove_action(harness):
    """on_issue_deleted: Linear uses 'remove', not 'delete'."""
    config, exec_mock = harness
    config["workflow_config"] = _workflow_config("on_issue_deleted")

    # 'remove' fires
    body = _issue_payload("remove")
    assert await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _linear_headers(body), {}, method="POST"
    ) is True
    exec_mock.assert_awaited_once()

    # 'delete' does NOT fire (Linear doesn't send this)
    exec_mock.reset_mock()
    body2 = _issue_payload("delete")
    assert await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body2, _linear_headers(body2), {}, method="POST"
    ) is True
    exec_mock.assert_not_awaited()


async def test_signing_secret_fallback_from_webhooks_table(deliver_webhook):
    """Race-condition: signing_secret absent from node config but present in
    webhooks.secret → event still verifies and workflow fires."""
    config = {
        "is_active": True,
        "user_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "node_id": "linear-trigger",
        "secret": SIGNING_SECRET,  # present in webhooks row
        "workflow_config": {
            "nodes": [
                {
                    "id": "linear-trigger",
                    "type": "automation-linear",
                    "config": {
                        "operation": "on_issue_created",
                        "webhook_id": WEBHOOK_ID,
                        # signing_secret intentionally absent — autosave race
                    },
                },
            ],
            "edges": [],
        },
    }
    exec_mock = deliver_webhook(config)

    body = _issue_payload("create")
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _linear_headers(body), {}, method="POST"
    )
    assert result is True, "Should succeed via webhooks.secret fallback"
    exec_mock.assert_awaited_once()


async def test_no_signing_secret_anywhere_rejects(deliver_webhook):
    """No signing_secret in node config AND nothing in webhooks.secret → 401."""
    config = {
        "is_active": True,
        "user_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "node_id": "linear-trigger",
        "secret": None,
        "workflow_config": {
            "nodes": [
                {
                    "id": "linear-trigger",
                    "type": "automation-linear",
                    "config": {
                        "operation": "on_issue_created",
                        "webhook_id": WEBHOOK_ID,
                        # no signing_secret anywhere
                    },
                },
            ],
            "edges": [],
        },
    }
    exec_mock = deliver_webhook(config)

    body = _issue_payload("create")
    result = await webhook_routes.handle_webhook_payload(
        WEBHOOK_ID, body, _linear_headers(body), {}, method="POST", return_response=True
    )
    assert result.get("status") == 401
    exec_mock.assert_not_awaited()


# ─── load_field_value: row-driven registration guard ─────────────────────────


async def test_operation_change_triggers_reregistration():
    """Switching operation must bypass the row-driven already_registered guard
    (row.registered_operation records the OLD op) and re-register."""
    from nodes.linear_node import LinearNode

    cred_id = str(uuid.uuid4())
    register_mock = AsyncMock(return_value=("new_wh_id", "new_secret"))
    pool, conn = make_pool()

    ctx = {
        "operation": "on_issue_updated",
        "trigger_registered": True,
        "signing_secret": "old_secret",
        "external_webhook_id": "old_wh_id",
        "webhook_url": TEST_WEBHOOK_URL,
    }
    row = webhook_row_state(
        is_active=True,
        secret_set=True,
        external_webhook_id="old_wh_id",
        registered_operation="on_issue_created",  # row recorded the OLD op
        registered_credential_id=cred_id,
    )

    with patch("nodes.linear_node.register_linear_webhook", register_mock), \
         patch("nodes.linear_node.unregister_linear_webhook", AsyncMock()), \
         patch.object(LinearNode, "_resolve_trigger_credential",
                      AsyncMock(return_value={"api_key": "lin_test_key"})), \
         patch("utils.webhook_manager.WebhookManager.get_or_create_webhook",
               AsyncMock(return_value=row)):
        result = await LinearNode.load_field_value(
            field_name="webhook_url",
            user_id=str(uuid.uuid4()),
            workflow_id=uuid.uuid4(),
            node_id="linear-1",
            pool=pool,
            context=ctx,
            credential_ids={"linear_api_key": cred_id},
        )

    vals = result["values"]
    assert vals["trigger_registered"] is True
    assert vals["signing_secret"] == "new_secret"
    assert vals["external_webhook_id"] == "new_wh_id"
    register_mock.assert_awaited_once()
    # The webhooks row (system of record) now carries the NEW registration.
    persists = find_sql_calls(conn, "is_active = true")
    assert len(persists) == 1
    _, secret, ext_id, reg_op, reg_cred, _fp, _ = persists[0].args
    assert (secret, ext_id, reg_op, reg_cred) == ("new_secret", "new_wh_id", "on_issue_updated", cred_id)


async def test_credential_change_triggers_reregistration():
    """Changing credential must bypass the row-driven guard
    (row.registered_credential_id != the picked credential id)."""
    from nodes.linear_node import LinearNode

    new_cred_id = str(uuid.uuid4())
    register_mock = AsyncMock(return_value=("new_wh_cred", "new_secret_cred"))
    pool, conn = make_pool()

    ctx = {
        "operation": "on_issue_created",
        "trigger_registered": True,
        "signing_secret": "old_secret",
        "external_webhook_id": "old_wh",
        "webhook_url": TEST_WEBHOOK_URL,
    }
    row = webhook_row_state(
        is_active=True,
        secret_set=True,
        external_webhook_id="old_wh",
        registered_operation="on_issue_created",     # same op...
        registered_credential_id=str(uuid.uuid4()),  # ...but OLD credential
    )

    with patch("nodes.linear_node.register_linear_webhook", register_mock), \
         patch("nodes.linear_node.unregister_linear_webhook", AsyncMock()), \
         patch.object(LinearNode, "_resolve_trigger_credential",
                      AsyncMock(return_value={"api_key": "lin_new_key"})), \
         patch("utils.webhook_manager.WebhookManager.get_or_create_webhook",
               AsyncMock(return_value=row)):
        result = await LinearNode.load_field_value(
            field_name="webhook_url",
            user_id=str(uuid.uuid4()),
            workflow_id=uuid.uuid4(),
            node_id="linear-1",
            pool=pool,
            context=ctx,
            credential_ids={"linear_api_key": new_cred_id},
        )

    vals = result["values"]
    assert vals["trigger_registered"] is True
    assert vals["signing_secret"] == "new_secret_cred"
    register_mock.assert_awaited_once()
    # The row records the NEW credential as the registration owner.
    persists = find_sql_calls(conn, "is_active = true")
    assert len(persists) == 1
    _, secret, ext_id, reg_op, reg_cred, _fp, _ = persists[0].args
    assert (secret, ext_id, reg_cred) == ("new_secret_cred", "new_wh_cred", new_cred_id)
    assert reg_op == "on_issue_created"


async def test_already_registered_guard_preserves_secret():
    """When the ROW records a matching registration (active + same operation +
    same credential + secret set), the guard holds: no re-registration, no row
    writes, signing_secret preserved from context and external_webhook_id
    falling back to the row's copy when the autosave never landed it."""
    from nodes.linear_node import LinearNode

    cred_id = str(uuid.uuid4())
    register_mock = AsyncMock(return_value=("wh_id", "a_secret"))
    pool, conn = make_pool()

    ctx = {
        "operation": "on_issue_created",
        "trigger_registered": True,
        "signing_secret": "stored_secret",
        # external_webhook_id absent — autosave never landed it
        "webhook_url": TEST_WEBHOOK_URL,
    }
    row = webhook_row_state(
        is_active=True,
        secret_set=True,
        external_webhook_id="existing_wh",
        registered_operation="on_issue_created",
        registered_credential_id=cred_id,
    )

    with patch("nodes.linear_node.register_linear_webhook", register_mock), \
         patch.object(LinearNode, "_resolve_trigger_credential",
                      AsyncMock(return_value={"api_key": "lin_key"})), \
         patch("utils.webhook_manager.WebhookManager.get_or_create_webhook",
               AsyncMock(return_value=row)):
        result = await LinearNode.load_field_value(
            field_name="webhook_url",
            user_id=str(uuid.uuid4()),
            workflow_id=uuid.uuid4(),
            node_id="linear-1",
            pool=pool,
            context=ctx,
            credential_ids={"linear_api_key": cred_id},
        )

    vals = result["values"]
    assert vals["trigger_registered"] is True
    assert vals["signing_secret"] == "stored_secret"  # preserved from ctx
    assert vals["external_webhook_id"] == "existing_wh"  # row fallback
    register_mock.assert_not_awaited()  # guard held — no re-registration
    conn.execute.assert_not_awaited()  # and no row writes


# ─── deregister_node_webhooks / handle_operation_change ──────────────────────


async def test_webhook_deregister_on_node_delete():
    """Node deletion → `deregister_node_webhooks` calls unregister_linear_webhook
    with the stored webhook id and deactivates (never deletes) the row,
    clearing the registration on confirmed teardown."""
    wf_id = str(uuid.uuid4())
    node_id = "linear-trigger"
    external_id = "lin_wh_existing"
    cred_id = str(uuid.uuid4())

    workflow_json = {
        "nodes": [
            {
                "id": node_id,
                "type": "automation-linear",
                "config": {
                    "operation": "on_issue_created",
                    "external_webhook_id": external_id,
                    "credentialIds": {"linear_api_key": cred_id},
                },
            }
        ],
        "edges": [],
    }
    pool, conn = make_pool(
        fetchrow={"owner_id": uuid.uuid4(), "workflow": workflow_json},
        fetch=[{"node_id": node_id, "external_webhook_id": external_id,
                "registered_operation": "on_issue_created", "registered_credential_id": None}],
    )
    unregister_mock = AsyncMock()

    with patch("nodes.linear_node.unregister_linear_webhook", unregister_mock), \
         patch("utils.credential_loader.load_credential",
               AsyncMock(return_value={"api_key": "lin_key"})):
        from utils.webhook_manager import WebhookManager
        result = await WebhookManager.deregister_node_webhooks(pool, wf_id, [node_id])

    assert result == {"deregistered": 1, "failed": 0}
    unregister_mock.assert_awaited_once()
    # The external_webhook_id must be passed to unregister
    assert unregister_mock.await_args.args[1] == external_id
    # Row deactivated with registration cleared (confirmed teardown), marker
    # stamped — never hard-deleted.
    deacts = find_sql_calls(conn, "is_active = false")
    assert len(deacts) == 1
    sql = deacts[0].args[0]
    assert "secret = NULL" in sql and "external_webhook_id = NULL" in sql
    assert deacts[0].args[3] == "on_issue_created"
    assert not find_sql_calls(conn, "DELETE FROM webhooks")


async def test_operation_change_to_action_reconciles_teardown_end_to_end():
    """Full flow through the NEW spec: handle_operation_change delegates to
    reconcile_node, which reads the SAVED graph (node now on an action op →
    desired None) and tears down via the row's synchronously-persisted
    external_webhook_id — the provider teardown cannot silently no-op even
    when the autosaved config never carried the endpoint id. The row is
    deactivated, never hard-deleted."""
    wf_id = str(uuid.uuid4())
    node_id = "linear-trigger"
    external_id = "lin_wh_to_delete"
    cred_id = str(uuid.uuid4())

    saved_node = {
        "id": node_id, "type": "automation-linear",
        "config": {"operation": "list_issues",
                   "credentialIds": {"linear_api_key": cred_id}},
    }
    webhook_row = {
        "id": uuid.uuid4(), "is_active": True,
        "external_webhook_id": external_id,
        "registered_operation": "on_issue_created",
        "registered_credential_id": cred_id,
        "registered_fingerprint": "stale-fp",
        "node_id": node_id,
    }
    pool, conn = make_pool(fetch=[webhook_row])

    async def routed_fetchrow(sql, *args):
        if "FROM workflows" in sql:
            return {"owner_id": uuid.uuid4(),
                    "workflow": {"nodes": [saved_node]}}
        if "FROM webhooks" in sql:
            return webhook_row
        return None

    conn.fetchrow = AsyncMock(side_effect=routed_fetchrow)
    unregister_mock = AsyncMock()
    delete_webhook_mock = AsyncMock()

    with patch("nodes.linear_node.unregister_linear_webhook", unregister_mock), \
         patch("utils.credential_loader.load_credential",
               AsyncMock(return_value={"api_key": "lin_key"})), \
         patch("utils.webhook_manager.WebhookManager.delete_webhook", delete_webhook_mock), \
         patch("utils.redis_client.get_shared_redis", lambda: None):
        from utils.webhook_manager import WebhookManager
        changed = await WebhookManager.handle_operation_change(
            pool,
            node_type="automation-linear",
            workflow_id=wf_id,
            node_id=node_id,
            old_operation="on_issue_created",   # was a trigger
            new_operation="list_issues",        # not a trigger
        )

    assert changed is True
    unregister_mock.assert_awaited_once()
    assert unregister_mock.await_args.args[1] == external_id
    # Rows are deactivated + preserved by the choke point — never hard-deleted.
    delete_webhook_mock.assert_not_awaited()
    deacts = find_sql_calls(conn, "is_active = false")
    assert len(deacts) >= 1
    assert not find_sql_calls(conn, "DELETE FROM webhooks")


async def test_operation_change_trigger_to_trigger_reconverges_end_to_end():
    """trigger → DIFFERENT trigger through the reconciler: the stale
    registration is torn down (provider unregister with the row's endpoint id)
    and the NEW operation registers in the same convergence — including for
    headless MCP/agentic operation changes, with no config-panel involved."""
    wf_id = str(uuid.uuid4())
    node_id = "linear-trigger"
    cred_id = str(uuid.uuid4())

    saved_node = {
        "id": node_id, "type": "automation-linear",
        "config": {"operation": "on_issue_updated",
                   "credentialIds": {"linear_api_key": cred_id}},
    }
    webhook_row = {
        "id": uuid.uuid4(), "is_active": True,
        "external_webhook_id": "lin_wh_old",
        "registered_operation": "on_issue_created",
        "registered_credential_id": cred_id,
        "registered_fingerprint": "old-fp",
        "node_id": node_id,
    }
    pool, conn = make_pool(fetch=[webhook_row])

    async def routed_fetchrow(sql, *args):
        if "FROM workflows" in sql:
            return {"owner_id": uuid.uuid4(),
                    "workflow": {"nodes": [saved_node]}}
        if "FROM webhooks" in sql:
            return webhook_row
        return None

    conn.fetchrow = AsyncMock(side_effect=routed_fetchrow)
    unregister_mock = AsyncMock()
    register_mock = AsyncMock(return_value=("lin_wh_new", "new_secret"))

    with patch("nodes.linear_node.unregister_linear_webhook", unregister_mock), \
         patch("nodes.linear_node.register_linear_webhook", register_mock), \
         patch("utils.credential_loader.load_credential",
               AsyncMock(return_value={"api_key": "lin_key"})), \
         patch("nodes.core.webhook_trigger.load_credential",
               AsyncMock(return_value={"api_key": "lin_key"})), \
         patch("utils.webhook_manager.WebhookManager.get_or_create_webhook",
               AsyncMock(return_value=webhook_row_state())), \
         patch("utils.redis_client.get_shared_redis", lambda: None):
        from utils.webhook_manager import WebhookManager
        changed = await WebhookManager.handle_operation_change(
            pool,
            node_type="automation-linear",
            workflow_id=wf_id,
            node_id=node_id,
            old_operation="on_issue_created",
            new_operation="on_issue_updated",  # still a trigger
        )

    assert changed is True
    # Old endpoint torn down, new operation registered, row activated with the
    # NEW registration (fingerprint included).
    unregister_mock.assert_awaited_once()
    register_mock.assert_awaited_once()
    persists = find_sql_calls(conn, "is_active = true")
    assert len(persists) == 1
    _, secret, ext_id, reg_op, _reg_cred, fp, _wid = persists[0].args
    assert (secret, ext_id, reg_op) == ("new_secret", "lin_wh_new", "on_issue_updated")
    assert isinstance(fp, str) and len(fp) == 16
