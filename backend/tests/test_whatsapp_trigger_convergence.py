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

Each WAHooks webhook signs its deliveries with a secret of its own, which the
row records by connection wherever a webhook is made (registering, a manual run
that re-registers, a rebind carrying webhooks to a new connection), and which
the nightly sweep reads off WAHooks for one the record lacks or misstates. One
URL can be registered on several connections: each delivery is checked against
its own connection's secret.

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

from repositories import trigger_resync
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.encryption import get_encryption
from utils.webhook_manager import WebhookManager

WAHOOKS_EVENTS = ("message", "session.status")

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
        hook = {"id": f"wh-{uuid.uuid4().hex[:6]}", "url": url, "events": list(events), "active": True,
                "signingSecret": uuid.uuid4().hex * 2}
        self.hooks.setdefault(connection_id, []).append(hook)
        return dict(hook)

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
    # Signed in today: the nightly resync acts only on workflows in use.
    await db.execute("INSERT INTO auth.users (id, email, last_sign_in_at) VALUES ($1, $2, now())",
                     owner, f"{owner}@example.test")
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

    # Never registered: a dry run says so without touching WAHooks, then the converger registers it through the
    # node's own loader, as the panel would.
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, plan_only=True))["state"] == "would_register"
    assert wahooks.hooks == {}
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

    # A trigger again, its row torn down before: the nightly resync finds it and, turned on, registers it.
    await _save(db, workflow_id, "receive_message", credentials["b"])
    await db.execute("DELETE FROM trigger_resync_state")
    await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
    assert not (await _row(db, workflow_id))["is_active"] and _urls(wahooks, connections["b"]) == []
    await trigger_resync.set_registers(db.pool, True)
    try:
        await WebhookManager.resync_trigger_registrations(db.pool, limit=10_000)
    finally:
        await db.execute("DELETE FROM trigger_resync_state")
    assert (await _row(db, workflow_id))["is_active"] and _urls(wahooks, connections["b"]) == [url]


@pytest.mark.parametrize("events,says,does", [
    (["message", "session.status"], "would_adopt", "live"),
    (["message"], "would_register", "registered"),
], ids=["live as asked", "missing an event"])
async def test_a_registration_the_row_never_recorded_is_recorded_not_added_again(  # noqa: F811
        real_database, wahooks, events, says, does):
    """Made before the row recorded registrations: read off the row alone, it looked like none, and a pass would
    have registered it again. WAHooks, read with NoClick's own key, says what's live: as asked, it's only recorded."""
    db = real_database
    owner, workflow_id, credentials, connections = await _seed(db, wahooks)
    webhook = await WebhookManager.get_or_create_webhook(db.pool, owner, uuid.UUID(workflow_id), NODE)
    url = webhook["webhook_url"]
    wahooks.hooks[connections["a"]] = [{"id": "wh-before", "url": url, "events": list(events)}]
    await db.execute("UPDATE webhooks SET is_active = true, registered_operation = NULL, registered_fingerprint = NULL "
                     "WHERE workflow_id = $1", workflow_id)

    # As the nightly sweep reads it, which asks WAHooks what's live.
    planned = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, plan_only=True, observe=True)
    assert planned["state"] == says
    assert wahooks.hooks[connections["a"]] == [{"id": "wh-before", "url": url, "events": list(events)}]

    done = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, observe=True)
    assert done["state"] == does and done["outcome"] == planned["outcome"]
    assert _urls(wahooks, connections["a"]) == [url], "one webhook, never a second"
    assert set(WAHOOKS_EVENTS) <= set(wahooks.hooks[connections["a"]][0]["events"])
    row = await db.fetchrow("SELECT is_active, registered_operation, registered_credential_id, external_webhook_id "
                            "FROM webhooks WHERE workflow_id = $1", workflow_id)
    assert row["is_active"] and row["registered_operation"] == "receive_message"
    assert str(row["registered_credential_id"]) == credentials["a"] and row["external_webhook_id"] == connections["a"]
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "live"


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


async def _secrets(db, workflow_id):
    """The row's signing secrets, by WAHooks connection."""
    from utils.webhook_manager import recorded_signing_secrets

    return recorded_signing_secrets(await db.fetchval(
        "SELECT signing_secrets FROM webhooks WHERE workflow_id = $1 AND node_id = $2", workflow_id, NODE))


def _hook_secret(wahooks, connection_id):
    [hook] = wahooks.hooks[connection_id]
    return hook["signingSecret"]


async def _deliver(db, workflow_id, envelope, monkeypatch, *, secret=None):
    """Post ``envelope`` to the trigger's webhook as WAHooks does, signed with ``secret`` (by default the one its row
    records for the envelope's connection, else one it never recorded); the response and the payloads it ran."""
    import json

    from tests.test_whatsapp_self_echo import wahooks_headers
    from utils import webhook_routes

    runs = []

    def run(**kwargs):
        runs.append(kwargs["nodes"][0]["config"]["_triggerPayload"])

        async def ran():
            return {}
        return ran()

    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", run)
    webhook_id = str(await db.fetchval(
        "SELECT id FROM webhooks WHERE workflow_id = $1 AND node_id = $2", workflow_id, NODE))
    recorded = (await _secrets(db, workflow_id)).get(envelope.get("connectionId"))
    headers = wahooks_headers(envelope, secret or recorded or "a secret no row records")
    response = await webhook_routes.handle_webhook_payload(
        webhook_id, json.dumps(envelope), headers, {}, return_response=True)
    return response, runs


async def _owner_on_their_own(db, wahooks):
    """The shared workflow after the owner moved the trigger onto their own WhatsApp, with the
    member's webhook still on the member's connection (left by a registration nothing recorded)."""
    wf = await _shared(db, wahooks)
    stale_url = await _url(db, wf.workflow_id)
    await db.execute("UPDATE webhooks SET external_webhook_id = NULL, registered_credential_id = NULL, "
                     "signing_secrets = '{}'::jsonb WHERE workflow_id = $1", wf.workflow_id)
    await _open_panel(db, wf.owner, wf.workflow_id, wf.mine)
    await _save(db, wf.workflow_id, "receive_message", wf.mine)
    assert _urls(wahooks, wf.their_connection) == [stale_url]
    return wf


async def test_a_delivery_from_another_whatsapp_is_acknowledged_without_a_run(real_database, wahooks, monkeypatch):  # noqa: F811
    db = real_database
    wf = await _owner_on_their_own(db, wahooks)
    # The row records no secret for the left-behind webhook's connection: nothing to check it by, and it isn't the
    # credential's WhatsApp, however it's signed.
    for secret in (None, _hook_secret(wahooks, wf.their_connection)):
        response, runs = await _deliver(db, wf.workflow_id, _message(wf.their_connection, MEMBER_PHONE), monkeypatch,
                                        secret=secret)
        assert response["status"] == 200 and "ignored" in response["body"] and runs == []
    # Naming the credential's connection takes that connection's secret: the left-behind webhook's is refused.
    response, runs = await _deliver(db, wf.workflow_id, _message(wf.my_connection, MEMBER_PHONE), monkeypatch,
                                    secret=_hook_secret(wahooks, wf.their_connection))
    assert response["status"] == 401 and runs == []


async def test_a_delivery_from_the_credentials_whatsapp_runs(real_database, wahooks, monkeypatch):  # noqa: F811
    db = real_database
    wf = await _owner_on_their_own(db, wahooks)
    response, runs = await _deliver(db, wf.workflow_id, _message(wf.my_connection, OWNER_PHONE), monkeypatch)
    assert response["status"] == 200 and len(runs) == 1
    assert runs[0]["_webhook"]["signature_verified"] is True
    # The same phone through another of its links (a re-scan's old link) is still this account: it runs unverified.
    _, runs = await _deliver(db, wf.workflow_id, _message("conn-replaced", OWNER_PHONE), monkeypatch)
    assert len(runs) == 1 and runs[0]["_webhook"]["signature_verified"] is False


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


async def _torn_down(db, wahooks, *, attached):
    """A trigger whose registration was torn down with the account it ran on (deleted since), while its
    config still mirrors a live one. ``attached`` names the account the saved trigger holds now, if any."""
    owner, workflow_id, credentials, connections = await _seed(db, wahooks)
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "registered"
    [url] = _urls(wahooks, connections["a"])
    await WebhookManager.deregister_node_webhooks(db.pool, workflow_id, [NODE], requesting_user_id=owner)
    await db.execute("DELETE FROM credentials WHERE id = $1", credentials["a"])
    graph = await db.fetchval("SELECT workflow FROM workflows WHERE id = $1", workflow_id)
    config = graph["nodes"][0]["config"]
    config["credentialIds"] = {"whatsapp_qr": credentials[attached]} if attached else {}
    await db.execute("UPDATE workflows SET workflow = $2::jsonb WHERE id = $1", workflow_id, graph)
    row = await _row(db, workflow_id)
    assert not row["is_active"] and row["registered_operation"] == "receive_message"
    assert config["webhook_url"] and config["trigger_registered"] is True and not config.get("trigger_error")
    return owner, workflow_id, credentials, connections, url, graph


async def _canvas_save(db, owner, workflow_id, graph):
    """Save ``graph`` as the canvas does, then run the reconcile job the save queues and wakes."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from wss.handlers.workflow_handler import WorkflowHandler
    from wss.receiver.client_events import WorkflowUpdateRequest

    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={"user_id": owner})
    sio.emit = AsyncMock()
    handler = WorkflowHandler(sio=sio)
    handler.get_pool = AsyncMock(return_value=db.pool)
    spawned = {}
    with patch("utils.async_helpers.spawn", side_effect=lambda coro, name=None: spawned.setdefault(name, coro)):
        await handler.update_workflow("sid", WorkflowUpdateRequest(
            request_id="r", workflow_id=workflow_id, workflow_data=graph))
    assert not sio.emit.await_args.args[1].get("error")
    hooks = spawned.pop(f"workflow-reconcile:{workflow_id}")
    for other in spawned.values():
        other.close()
    await hooks


async def test_attaching_an_account_to_a_torn_down_trigger_registers_it(real_database, wahooks):  # noqa: F811
    """The trigger lost its account; a new one is linked and saved onto it. The save brings the
    registration back under the new account, whatever the config mirror still claims."""
    db = real_database
    owner, workflow_id, credentials, connections, url, graph = await _torn_down(db, wahooks, attached=None)

    graph["nodes"][0]["config"]["credentialIds"] = {"whatsapp_qr": credentials["b"]}
    await _canvas_save(db, owner, workflow_id, graph)

    row = await _row(db, workflow_id)
    assert row["is_active"] and str(row["registered_credential_id"]) == credentials["b"]
    assert _urls(wahooks, connections["b"]) == [url]


async def test_a_save_reactivates_a_trigger_whose_row_is_down(real_database, wahooks):  # noqa: F811
    """No account change this time: a setup save activates a ready trigger the row says is down,
    not only one whose config mirror says so."""
    db = real_database
    owner, workflow_id, _, connections, url, graph = await _torn_down(db, wahooks, attached="b")

    graph["nodes"][0]["config"]["label"] = "Inbox messages"
    await _canvas_save(db, owner, workflow_id, graph)

    assert (await _row(db, workflow_id))["is_active"] and _urls(wahooks, connections["b"]) == [url]


async def test_the_re_registration_choke_point_restores_a_loader_registered_trigger(real_database, wahooks):  # noqa: F811
    """Restore, undo and repair route through ``register_node_webhooks``; a trigger its own loader
    registers comes back like any other."""
    db = real_database
    owner, workflow_id, credentials, connections, url, _ = await _torn_down(db, wahooks, attached="b")

    assert await WebhookManager.register_node_webhooks(db.pool, workflow_id, owner, node_ids=[NODE]) == 1
    row = await _row(db, workflow_id)
    assert row["is_active"] and str(row["registered_credential_id"]) == credentials["b"]
    assert _urls(wahooks, connections["b"]) == [url]


# ── The secret each webhook signs with ─────────────────────────────────────

async def test_registering_records_the_secret_its_deliveries_are_signed_with(real_database, wahooks, monkeypatch):  # noqa: F811
    db = real_database
    owner, workflow_id, credentials, connections = await _seed(db, wahooks)
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "registered"
    assert await _secrets(db, workflow_id) == {connections["a"]: _hook_secret(wahooks, connections["a"])}
    graph = await db.fetchval("SELECT workflow FROM workflows WHERE id = $1", workflow_id)
    assert "signing_secret" not in graph["nodes"][0]["config"], "the row keeps it, never the graph"

    response, runs = await _deliver(db, workflow_id, _message(connections["a"], OWNER_PHONE), monkeypatch)
    assert response["status"] == 200 and len(runs) == 1
    response, runs = await _deliver(db, workflow_id, _message(connections["a"], OWNER_PHONE), monkeypatch,
                                    secret="not this webhook's")
    assert response["status"] == 401 and runs == []

    # Another WhatsApp: the first's webhook is torn down with its secret, and the new one has a secret of its own.
    await _save(db, workflow_id, "receive_message", credentials["b"])
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "registered"
    assert await _secrets(db, workflow_id) == {connections["b"]: _hook_secret(wahooks, connections["b"])}


async def _unsigned_registration(db, wahooks):
    """A live registration from before NoClick kept its webhook's signing secret."""
    owner, workflow_id, credentials, connections = await _seed(db, wahooks)
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "registered"
    await db.execute("UPDATE webhooks SET signing_secrets = '{}'::jsonb WHERE workflow_id = $1", workflow_id)
    [hook] = wahooks.hooks[connections["a"]]
    return workflow_id, connections["a"], dict(hook)


async def test_the_nightly_sweep_reads_the_secret_a_registration_from_before_lacks(real_database, wahooks):  # noqa: F811
    db = real_database
    workflow_id, connection, hook = await _unsigned_registration(db, wahooks)

    # A lifecycle surface takes it as it is: live, nothing asked of WAHooks.
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "live"
    assert await _secrets(db, workflow_id) == {}

    # The sweep reads it off the webhook WAHooks holds: recorded, the webhook itself untouched.
    planned = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, plan_only=True, observe=True)
    assert planned["state"] == "would_adopt" and "secret" in planned["reason"]
    assert "signingSecret" not in str(planned) and hook["signingSecret"] not in str(planned)
    assert await _secrets(db, workflow_id) == {}
    done = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, observe=True)
    assert done["state"] == "live" and done.get("adopted") is True
    assert await _secrets(db, workflow_id) == {connection: hook["signingSecret"]}
    assert wahooks.hooks[connection] == [hook], "the same webhook, never re-made"

    # Recorded: the next sweep finds nothing to change, and one that can't read WAHooks leaves it be.
    again = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, observe=True)
    assert again["state"] == "live" and not again.get("adopted")
    wahooks.down = True
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, observe=True))["state"] == "live"


async def test_the_nightly_sweep_corrects_a_secret_recorded_from_another_webhook(
        real_database, wahooks, monkeypatch):  # noqa: F811
    """A record holding another webhook's secret for the connection refuses every delivery from it; the sweep reads
    the one WAHooks signs with and records it, and the connection's deliveries run again."""
    db = real_database
    workflow_id, connection, hook = await _unsigned_registration(db, wahooks)
    await db.execute("UPDATE webhooks SET signing_secrets = $2::jsonb WHERE workflow_id = $1", workflow_id,
                     {connection: "a stale webhook's secret"})
    response, runs = await _deliver(db, workflow_id, _message(connection, OWNER_PHONE), monkeypatch,
                                    secret=hook["signingSecret"])
    assert response["status"] == 401 and runs == []

    planned = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, plan_only=True, observe=True)
    assert planned["state"] == "would_adopt"
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, observe=True)).get("adopted") is True
    assert await _secrets(db, workflow_id) == {connection: hook["signingSecret"]}
    response, runs = await _deliver(db, workflow_id, _message(connection, OWNER_PHONE), monkeypatch)
    assert response["status"] == 200 and runs[0]["_webhook"]["signature_verified"] is True


async def test_a_sweep_that_cant_read_wahooks_leaves_an_unsigned_registration_be(real_database, wahooks):  # noqa: F811
    """Not knowing the secret is no reason to tear down a live registration: it's read on a later sweep."""
    db = real_database
    workflow_id, connection, hook = await _unsigned_registration(db, wahooks)
    wahooks.down = True
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, observe=True))["state"] == "live"
    assert await _secrets(db, workflow_id) == {} and (await _row(db, workflow_id))["is_active"]
    wahooks.down = False
    assert wahooks.hooks[connection] == [hook]


async def test_a_sweep_re_registers_an_unsigned_registration_wahooks_no_longer_holds(real_database, wahooks):  # noqa: F811
    """Looking for its secret finds no webhook at all: the trigger was deaf, and registering it again records the new
    webhook's secret."""
    db = real_database
    workflow_id, connection, hook = await _unsigned_registration(db, wahooks)
    wahooks.hooks[connection] = []

    done = await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, observe=True)
    assert done["state"] == "registered"
    assert _urls(wahooks, connection) == [hook["url"]]
    assert await _secrets(db, workflow_id) == {connection: _hook_secret(wahooks, connection)}
    assert _hook_secret(wahooks, connection) != hook["signingSecret"]


async def test_a_sweep_reading_secrets_leaves_a_recorded_registration_be(real_database, wahooks):  # noqa: F811
    """The read is for secrets: a registration whose secrets are recorded stays as it is whatever WAHooks lists."""
    db = real_database
    owner, workflow_id, credentials, connections = await _seed(db, wahooks)
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "registered"
    recorded = await _secrets(db, workflow_id)
    wahooks.hooks[connections["a"]] = []

    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE, observe=True))["state"] == "live"
    assert await _secrets(db, workflow_id) == recorded and _urls(wahooks, connections["a"]) == []


async def test_a_rebind_records_the_secret_the_new_connection_signs_with(real_database, wahooks, monkeypatch):  # noqa: F811
    """A re-scan carries each webhook to the phone's new connection, where WAHooks makes it anew with a new secret.
    The row records it beside the old link's, so each verifies its own; only the credential's connection is the
    owner's, so the old link's deliveries run unverified."""
    from utils.wahooks_connections import migrate_wahooks_webhooks

    db = real_database
    owner, workflow_id, credentials, connections = await _seed(db, wahooks)
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "registered"
    before = _hook_secret(wahooks, connections["a"])
    rescanned = f"conn-rescan-{uuid.uuid4().hex[:8]}"
    wahooks.live.add(rescanned)
    # The rebind moves the credential first (utils.whatsapp_qr.finalize_qr_connection), then its webhooks.
    await db.execute(
        "UPDATE credentials SET credential = $2, metadata = $3::jsonb WHERE id = $1", credentials["a"],
        get_encryption().encrypt_credential({"credential_type": "whatsapp_qr", "connection_id": rescanned}),
        {"connection_id": rescanned, "phone_number": OWNER_PHONE})

    assert await migrate_wahooks_webhooks(db.pool, connections["a"], rescanned) == 1
    assert await _secrets(db, workflow_id) == {connections["a"]: before, rescanned: _hook_secret(wahooks, rescanned)}
    assert _hook_secret(wahooks, rescanned) != before
    response, runs = await _deliver(db, workflow_id, _message(rescanned, OWNER_PHONE), monkeypatch)
    assert response["status"] == 200 and runs[0]["_webhook"]["signature_verified"] is True

    # The old link, until it goes: its own secret verifies it, and it isn't the credential's connection.
    response, runs = await _deliver(db, workflow_id, _message(connections["a"], OWNER_PHONE), monkeypatch)
    assert response["status"] == 200 and runs[0]["_webhook"]["signature_verified"] is False
    response, runs = await _deliver(db, workflow_id, _message(connections["a"], OWNER_PHONE), monkeypatch,
                                    secret=_hook_secret(wahooks, rescanned))
    assert response["status"] == 401 and runs == []


async def test_a_manual_run_that_re_registers_records_the_new_secret(real_database, wahooks):  # noqa: F811
    """A test run of the trigger puts back a webhook WAHooks lost; the row records the one it made."""
    from nodes.whatsapp_node import WhatsAppNode, WhatsAppNodeConfig, WhatsAppQRCredential
    from nodes.whatsapp_trigger_config import WhatsAppReceiveMessageConfig

    db = real_database
    owner, workflow_id, credentials, connections = await _seed(db, wahooks)
    assert (await WebhookManager.reconcile_node(db.pool, workflow_id, NODE))["state"] == "registered"
    url = await _url(db, workflow_id)
    wahooks.hooks[connections["a"]] = []

    node = WhatsAppNode(
        node_id=NODE, node_type="automation-whatsapp", node_data={}, sio=None, sid=None, workflow_id=workflow_id,
        config=WhatsAppNodeConfig(config=WhatsAppReceiveMessageConfig(webhook_url=url),
                                  credentials=WhatsAppQRCredential(connection_id=connections["a"])))
    assert (await node.execute({}))["status"] == "no_event"
    assert _urls(wahooks, connections["a"]) == [url]
    assert await _secrets(db, workflow_id) == {connections["a"]: _hook_secret(wahooks, connections["a"])}
