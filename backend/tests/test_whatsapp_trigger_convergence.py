"""The registration converger and a trigger its own loader registers.

WhatsApp's incoming messages on a QR session are registered by
``WhatsAppNode.load_field_value`` (a WAHooks webhook on the session's
connection), the panel's path. ``WebhookManager.reconcile_node`` (run by
every lifecycle surface and the nightly resync) once treated such a node as
"desires nothing" and tore the registration down while the node still said it
was registered: the trigger went deaf. Over real PostgreSQL, with WAHooks'
SDK faked at its client: the converger keeps a live registration, moves it
with a credential swap, drops it with the operation, and brings back one it
tore down before.
"""
import sys
import types
import uuid

import pytest

from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.encryption import get_encryption
from utils.webhook_manager import WebhookManager

pytestmark = pytest.mark.asyncio

NODE = "messages"


class FakeWAHooks:
    """WAHooks' webhook and connection API, in memory."""

    hooks: dict = {}
    live: set = set()

    def __init__(self, api_key):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def list_connections(self):
        return [{"id": cid, "status": "connected"} for cid in self.live]

    def list_webhooks(self, connection_id):
        return list(self.hooks.get(connection_id, []))

    def create_webhook(self, connection_id, url, events):
        self.hooks.setdefault(connection_id, []).append(
            {"id": f"wh-{uuid.uuid4().hex[:6]}", "url": url, "events": list(events)})

    def update_webhook(self, webhook_id, events):
        for hooks in self.hooks.values():
            for hook in hooks:
                if hook["id"] == webhook_id:
                    hook["events"] = list(events)

    def delete_webhook(self, webhook_id):
        for cid, hooks in self.hooks.items():
            self.hooks[cid] = [h for h in hooks if h["id"] != webhook_id]


@pytest.fixture
def wahooks(monkeypatch):
    import utils.whatsapp_qr as whatsapp_qr

    FakeWAHooks.hooks, FakeWAHooks.live = {}, set()
    module = types.ModuleType("wahooks")
    module.WAHooks = FakeWAHooks
    module.WAHooksError = type("WAHooksError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "wahooks", module)
    monkeypatch.setenv("WAHOOKS_API_KEY", "wh_test")
    monkeypatch.setattr(whatsapp_qr, "_status_cache", None)
    return FakeWAHooks


async def _seed(db, wahooks, operation="receive_message"):
    """An owner with two QR-linked WhatsApps (credentials and their live sessions) and a trigger on the first."""
    owner, workflow_id = str(uuid.uuid4()), str(uuid.uuid4())
    await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2)", owner, f"{owner}@example.test")
    credentials, connections = {}, {name: f"conn-{name}-{uuid.uuid4().hex[:8]}" for name in "ab"}
    wahooks.live |= set(connections.values())
    for name, connection in connections.items():
        credentials[name] = str(await db.fetchval(
            "INSERT INTO credentials (owner_id, credential_type, name, credential, metadata) "
            "VALUES ($1, 'whatsapp_qr', $2, $3, $4::jsonb) RETURNING id",
            owner, f"WhatsApp {name}",
            get_encryption().encrypt_credential({"credential_type": "whatsapp_qr", "connection_id": connection}),
            {"connection_id": connection}))
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1, $2, 'Inbox', $3::jsonb)",
                     workflow_id, owner, _graph(operation, credentials["a"]))
    return owner, workflow_id, credentials, connections


def _graph(operation, credential_id):
    return {"nodes": [{"id": NODE, "type": "automation-whatsapp", "config": {
        "operation": operation, "credentialIds": {"whatsapp_qr": credential_id}}}], "edges": []}


async def _save(db, workflow_id, operation, credential_id):
    """An edit saved the way the canvas saves it: the node's mirrored registration fields stay."""
    graph = await db.fetchval("SELECT workflow FROM workflows WHERE id = $1", workflow_id)
    graph["nodes"][0]["config"].update({"operation": operation, "credentialIds": {"whatsapp_qr": credential_id}})
    await db.execute("UPDATE workflows SET workflow = $2::jsonb WHERE id = $1", workflow_id, graph)


async def _row(db, workflow_id):
    return await db.fetchrow("SELECT is_active, registered_operation, registered_credential_id FROM webhooks "
                             "WHERE workflow_id = $1 AND node_id = $2", workflow_id, NODE)


def _urls(wahooks, connection_id):
    return [h["url"] for h in wahooks.hooks.get(connection_id, [])]


async def test_a_loader_registered_trigger_stays_registered_and_follows_its_config(real_database, wahooks):  # noqa: F811
    db = real_database
    owner, workflow_id, credentials, connections = await _seed(db, wahooks)

    # Never registered: the converger registers it through the node's own loader, as the panel would.
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "registered"
    row = await _row(db, workflow_id)
    assert row["is_active"] and row["registered_operation"] == "receive_message"
    [url] = _urls(wahooks, connections["a"])

    # Live: reconciled again (the nightly resync, any lifecycle surface), nothing moves.
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "live"
    assert (await _row(db, workflow_id))["is_active"] and _urls(wahooks, connections["a"]) == [url]

    # Another WhatsApp: the old session stops delivering here, the new one starts.
    await _save(db, workflow_id, "receive_message", credentials["b"])
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "registered"
    assert _urls(wahooks, connections["a"]) == [] and _urls(wahooks, connections["b"]) == [url]
    row = await _row(db, workflow_id)
    assert row["is_active"] and str(row["registered_credential_id"]) == credentials["b"]

    # No longer a trigger: torn down.
    await _save(db, workflow_id, "send_text_message", credentials["b"])
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "deregistered"
    assert _urls(wahooks, connections["b"]) == [] and not (await _row(db, workflow_id))["is_active"]

    # A trigger again, its row torn down before: the nightly resync finds it and registers it.
    await _save(db, workflow_id, "receive_message", credentials["b"])
    await WebhookManager.resync_trigger_registrations(db.pool)
    assert (await _row(db, workflow_id))["is_active"] and _urls(wahooks, connections["b"]) == [url]


async def test_a_cloud_api_message_trigger_is_left_alone(real_database, wahooks):  # noqa: F811
    """With a Meta access token the URL is set in Meta's console: nothing for the converger to register."""
    db = real_database
    owner, workflow_id, _, _ = await _seed(db, wahooks)
    token = str(await db.fetchval(
        "INSERT INTO credentials (owner_id, credential_type, name, credential) "
        "VALUES ($1, 'whatsapp_access_token', 'Cloud', $2) RETURNING id",
        owner, get_encryption().encrypt_credential({"access_token": "EAAG-test", "phone_number_id": "1"})))
    await db.execute("UPDATE workflows SET workflow = $2::jsonb WHERE id = $1", workflow_id,
                     {"nodes": [{"id": NODE, "type": "automation-whatsapp", "config": {
                         "operation": "receive_message", "credentialIds": {"whatsapp_access_token": token}}}],
                      "edges": []})
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "noop"
    assert wahooks.hooks == {}
