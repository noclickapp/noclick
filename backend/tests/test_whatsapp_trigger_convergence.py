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

A trigger hears only the WhatsApp its credential is on. Runs answer through
the node's current credential, so a webhook left on a previous credential's
connection made the agent reply from a different number than the one the
sender wrote to. The row records the connection a registration is on, so a
swap or a teardown removes it even when the previous credential belongs to
another member of the workflow or no longer exists, and a delivery from any
other account is acknowledged without a run.
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


class WAHooksError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


class FakeWAHooks:
    """WAHooks' webhook and connection API, in memory. ``down`` makes every
    webhook call fail the way an outage does."""

    hooks: dict = {}
    live: set = set()
    down: bool = False

    def __init__(self, api_key):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def list_connections(self):
        return [{"id": cid, "status": "connected"} for cid in self.live]

    def list_webhooks(self, connection_id):
        if self.down:
            raise WAHooksError("Service Unavailable", 503)
        if connection_id not in self.live:
            raise WAHooksError("Connection not found", 404)
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

    FakeWAHooks.hooks, FakeWAHooks.live, FakeWAHooks.down = {}, set(), False
    module = types.ModuleType("wahooks")
    module.WAHooks = FakeWAHooks
    module.WAHooksError = WAHooksError
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


# ── A trigger hears only the WhatsApp its credential is on ──────────────────

OWNER_PHONE, MEMBER_PHONE = "12025550101", "12025550107"


async def _user(db):
    user = str(uuid.uuid4())
    await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2)", user, f"{user}@example.test")
    return user


async def _whatsapp(db, wahooks, owner, phone):
    """A QR-linked WhatsApp of ``owner``'s: its credential id and live connection."""
    connection = f"conn-{uuid.uuid4().hex[:8]}"
    wahooks.live.add(connection)
    credential = str(await db.fetchval(
        "INSERT INTO credentials (owner_id, credential_type, name, credential, metadata) "
        "VALUES ($1, 'whatsapp_qr', $2, $3, $4::jsonb) RETURNING id",
        owner, f"WhatsApp (+{phone})",
        get_encryption().encrypt_credential({"credential_type": "whatsapp_qr", "connection_id": connection}),
        {"connection_id": connection, "phone_number": phone}))
    return credential, connection


async def _shared(db, wahooks):
    """An owner's workflow, shared with a member whose own WhatsApp is on the trigger;
    the member's panel registered it, and the owner has a WhatsApp of their own."""
    owner, member = await _user(db), await _user(db)
    theirs, their_connection = await _whatsapp(db, wahooks, member, MEMBER_PHONE)
    mine, my_connection = await _whatsapp(db, wahooks, owner, OWNER_PHONE)
    workflow_id = str(uuid.uuid4())
    await db.execute("INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1, $2, 'Inbox', $3::jsonb)",
                     workflow_id, owner, _graph("receive_message", theirs))
    await _open_panel(db, member, workflow_id, theirs)
    return types.SimpleNamespace(owner=owner, member=member, workflow_id=workflow_id, theirs=theirs, mine=mine,
                                 their_connection=their_connection, my_connection=my_connection)


async def _open_panel(db, user, workflow_id, credential_id):
    """The trigger's config panel opening for ``user`` with ``credential_id`` picked; what it
    shows lands in the node's config the way the canvas autosave mirrors it."""
    from nodes.whatsapp_node import WhatsAppNode

    values = (await WhatsAppNode.load_field_value(
        "webhook_url", user, uuid.UUID(workflow_id), NODE, db.pool,
        context={"operation": "receive_message", "credentialIds": {"whatsapp_qr": credential_id}},
        credential_ids={"whatsapp_qr": credential_id},
    ))["values"]
    await WebhookManager.merge_node_config_patch(
        db.pool, uuid.UUID(workflow_id), NODE, {k: v for k, v in values.items() if v is not None})
    return values


async def _url(db, workflow_id):
    from utils.webhook_delivery import get_webhook_url

    return get_webhook_url(str(await db.fetchval(
        "SELECT id FROM webhooks WHERE workflow_id = $1 AND node_id = $2", workflow_id, NODE)))


async def _recorded(db, workflow_id):
    return await db.fetchval("SELECT external_webhook_id FROM webhooks WHERE workflow_id = $1 AND node_id = $2",
                             workflow_id, NODE)


async def test_the_owner_picking_their_whatsapp_in_the_panel_unhooks_the_members(real_database, wahooks):  # noqa: F811
    db = real_database
    wf = await _shared(db, wahooks)
    url = await _url(db, wf.workflow_id)
    assert _urls(wahooks, wf.their_connection) == [url]
    assert await _recorded(db, wf.workflow_id) == wf.their_connection

    # The owner can't read the member's credential; the row says which connection it's on.
    values = await _open_panel(db, wf.owner, wf.workflow_id, wf.mine)
    assert values["trigger_registered"] is True and "external_webhook_id" not in values
    assert _urls(wahooks, wf.their_connection) == [] and _urls(wahooks, wf.my_connection) == [url]
    row = await _row(db, wf.workflow_id)
    assert row["is_active"] and str(row["registered_credential_id"]) == wf.mine
    assert await _recorded(db, wf.workflow_id) == wf.my_connection

    # The save lands and the lifecycle hook converges: already there, nothing moves.
    before = (await db.fetchval("SELECT workflow FROM workflows WHERE id = $1", wf.workflow_id))["nodes"][0]["config"]
    await _save(db, wf.workflow_id, "receive_message", wf.mine)
    after = (await db.fetchval("SELECT workflow FROM workflows WHERE id = $1", wf.workflow_id))["nodes"][0]["config"]
    await WebhookManager.handle_credential_change(
        db.pool, "automation-whatsapp", wf.workflow_id, NODE, before, after, wf.owner)
    assert _urls(wahooks, wf.their_connection) == [] and _urls(wahooks, wf.my_connection) == [url]


@pytest.mark.parametrize("previous", ["another member's", "from before connections were recorded", "deleted"])
async def test_a_headless_swap_unhooks_the_previous_connection(real_database, wahooks, previous):  # noqa: F811
    db = real_database
    wf = await _shared(db, wahooks)
    url = await _url(db, wf.workflow_id)
    if previous == "from before connections were recorded":
        await db.execute("UPDATE webhooks SET external_webhook_id = NULL WHERE workflow_id = $1", wf.workflow_id)
    elif previous == "deleted":
        await db.execute("DELETE FROM credentials WHERE id = $1", wf.theirs)

    await _save(db, wf.workflow_id, "receive_message", wf.mine)
    result = await WebhookManager.reconcile_node(db.pool, wf.workflow_id, NODE, user_id=wf.owner)
    assert result["state"] == "registered"
    assert _urls(wahooks, wf.their_connection) == [] and _urls(wahooks, wf.my_connection) == [url]


@pytest.mark.parametrize("change", ["node removed", "operation changed"])
async def test_tearing_down_needs_no_access_to_the_credential(real_database, wahooks, change):  # noqa: F811
    db = real_database
    wf = await _shared(db, wahooks)
    if change == "node removed":
        await WebhookManager.deregister_node_webhooks(
            db.pool, wf.workflow_id, [NODE], requesting_user_id=wf.owner)
    else:
        await _save(db, wf.workflow_id, "send_text_message", wf.theirs)
        assert (await WebhookManager.reconcile_node(
            db.pool, wf.workflow_id, NODE, user_id=wf.owner))["state"] == "deregistered"
    assert _urls(wahooks, wf.their_connection) == []
    assert not (await _row(db, wf.workflow_id))["is_active"] and await _recorded(db, wf.workflow_id) is None


async def test_a_teardown_wahooks_refused_is_retried_until_it_lands(real_database, wahooks):  # noqa: F811
    db = real_database
    wf = await _shared(db, wahooks)
    url = await _url(db, wf.workflow_id)
    await _save(db, wf.workflow_id, "send_text_message", wf.theirs)

    wahooks.down = True
    await WebhookManager.reconcile_node(db.pool, wf.workflow_id, NODE, user_id=wf.owner)
    assert _urls(wahooks, wf.their_connection) == [url]
    assert not (await _row(db, wf.workflow_id))["is_active"]
    assert await _recorded(db, wf.workflow_id) == wf.their_connection  # kept: the retry knows where to look

    wahooks.down = False
    assert (await WebhookManager.reconcile_node(db.pool, wf.workflow_id, NODE))["state"] == "deregistered"
    assert _urls(wahooks, wf.their_connection) == [] and await _recorded(db, wf.workflow_id) is None
    assert (await WebhookManager.reconcile_node(db.pool, wf.workflow_id, NODE))["state"] == "noop"


async def test_a_connection_wahooks_no_longer_has_is_already_unhooked(real_database, wahooks):  # noqa: F811
    db = real_database
    wf = await _shared(db, wahooks)
    wahooks.live.discard(wf.their_connection)
    wahooks.hooks.pop(wf.their_connection)
    await WebhookManager.deregister_node_webhooks(db.pool, wf.workflow_id, [NODE], requesting_user_id=wf.owner)
    assert await _recorded(db, wf.workflow_id) is None  # done, not kept for a retry


def _message(connection_id, receiving_phone, *, stamped=True):
    """A WAHooks message delivery as it reaches the trigger's webhook."""
    envelope = {
        "event": "message", "session": "u_test_s_000001",
        "me": {"id": f"{receiving_phone}@c.us", "pushName": "Shop"},
        "payload": {"from": "12025550102@lid", "fromMe": False, "body": "hi",
                    "_data": {"key": {"remoteJid": "12025550102@lid", "fromMe": False}}},
    }
    if stamped:
        envelope["connectionId"] = connection_id
    return envelope


async def _deliver(db, workflow_id, envelope, monkeypatch):
    """Post ``envelope`` to the trigger's webhook; the response and the runs it started."""
    import json

    from utils import webhook_routes

    runs = []

    def run(**kwargs):
        runs.append(kwargs)

        async def ran():
            return {}
        return ran()

    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", run)
    webhook_id = str(await db.fetchval(
        "SELECT id FROM webhooks WHERE workflow_id = $1 AND node_id = $2", workflow_id, NODE))
    response = await webhook_routes.handle_webhook_payload(
        webhook_id, json.dumps(envelope), {}, {}, return_response=True)
    return response, runs


async def _owner_on_their_own(db, wahooks):
    """The shared workflow after the owner moved the trigger onto their own WhatsApp, with the
    member's webhook still on the member's connection (left by a registration nothing recorded)."""
    wf = await _shared(db, wahooks)
    stale_url = await _url(db, wf.workflow_id)
    await db.execute("UPDATE webhooks SET external_webhook_id = NULL, registered_credential_id = NULL "
                     "WHERE workflow_id = $1", wf.workflow_id)
    await _open_panel(db, wf.owner, wf.workflow_id, wf.mine)
    await _save(db, wf.workflow_id, "receive_message", wf.mine)
    assert _urls(wahooks, wf.their_connection) == [stale_url]
    return wf


async def test_a_delivery_from_another_whatsapp_is_acknowledged_without_a_run(real_database, wahooks, monkeypatch):  # noqa: F811
    db = real_database
    wf = await _owner_on_their_own(db, wahooks)
    response, runs = await _deliver(db, wf.workflow_id, _message(wf.their_connection, MEMBER_PHONE), monkeypatch)
    assert response["status"] == 200 and "ignored" in response["body"] and runs == []


async def test_a_delivery_from_the_credentials_whatsapp_runs(real_database, wahooks, monkeypatch):  # noqa: F811
    db = real_database
    wf = await _owner_on_their_own(db, wahooks)
    response, runs = await _deliver(db, wf.workflow_id, _message(wf.my_connection, OWNER_PHONE), monkeypatch)
    assert response["status"] == 200 and len(runs) == 1
    # The same phone through another of its links (a re-scan's old link) is still this account.
    _, runs = await _deliver(db, wf.workflow_id, _message("conn-replaced", OWNER_PHONE), monkeypatch)
    assert len(runs) == 1


@pytest.mark.parametrize("unjudgeable", ["unreadable credential", "unstamped envelope"])
async def test_a_delivery_that_cant_be_judged_runs(real_database, wahooks, monkeypatch, unjudgeable):  # noqa: F811
    """Losing a sender's message is worse than a run that shouldn't have happened."""
    db = real_database
    wf = await _owner_on_their_own(db, wahooks)
    envelope = _message(wf.their_connection, MEMBER_PHONE, stamped=unjudgeable != "unstamped envelope")
    if unjudgeable == "unreadable credential":
        await db.execute("UPDATE credentials SET credential = 'not-a-ciphertext' WHERE id = $1", wf.mine)
    _, runs = await _deliver(db, wf.workflow_id, envelope, monkeypatch)
    assert len(runs) == 1
