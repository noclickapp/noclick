"""WhatsApp session-death detection and alerting regressions.

Pins the push path (session.status control events → owner alert), the manual-
run truth check (dead session = loud failure, healthy = honest no-event
envelope), the webhook subscription upgrade, and the daily sweep backstop.
"""

import os
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from nodes.whatsapp_node import (
    WAHOOKS_WEBHOOK_EVENTS,
    WhatsAppNode,
    WhatsAppNodeConfig,
    WhatsAppQRCredential,
    WhatsAppReceiveMessageConfig,
    _wahooks_ensure_webhook,
)

RECEIVE_CFG = {"operation": "receive_message", "credentialIds": {"whatsapp_qr": "cred-1"}}


def _qr_node():
    node_config = WhatsAppNodeConfig(
        config=WhatsAppReceiveMessageConfig(webhook_url="https://wh-1.hooks.example.test"),
        credentials=WhatsAppQRCredential(connection_id="conn-1"),
    )
    return WhatsAppNode(
        node_id="wa-1", node_type="automation-whatsapp", node_data={},
        config=node_config, sio=None, sid=None, workflow_id="wf-1",
    )


def _pool(metadata=None, workflow_name="My Bot"):
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={
        "metadata": metadata or {"connection_id": "conn-1"},
        "workflow_name": workflow_name,
    })
    return pool


class _StatusClient:
    def __init__(self, status):
        self._status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_connection(self, connection_id):
        return {"id": connection_id, "status": self._status}


# ── handle_control_event ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_data_events_are_not_control_events():
    assert await WhatsAppNode.handle_control_event(
        {"event": "message", "session": "s", "payload": {}}, RECEIVE_CFG,
        pool=MagicMock(), workflow_id="wf-1", node_id="wa-1",
    ) is None
    # Meta Cloud API shapes aren't control events either.
    assert await WhatsAppNode.handle_control_event(
        {"object": "whatsapp_business_account"}, RECEIVE_CFG,
        pool=MagicMock(), workflow_id="wf-1", node_id="wa-1",
    ) is None


@pytest.mark.asyncio
async def test_healthy_status_event_consumed_without_alert():
    alert = AsyncMock()
    with patch("utils.notifications.send_channel_disconnected_alert", alert):
        msg = await WhatsAppNode.handle_control_event(
            {"event": "session.status", "session": "s", "payload": {"status": "WORKING"}},
            RECEIVE_CFG, pool=MagicMock(), workflow_id="wf-1", node_id="wa-1",
        )
    assert msg and "consumed" in msg
    alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_status_event_alerts_after_live_verification():
    alert = AsyncMock()
    with patch.dict(os.environ, {"WAHOOKS_API_KEY": "k"}), \
         patch("wahooks.WAHooks", lambda api_key: _StatusClient("failed")), \
         patch("utils.notifications.send_channel_disconnected_alert", alert):
        msg = await WhatsAppNode.handle_control_event(
            {"event": "session.status", "session": "s", "payload": {"status": "FAILED"}},
            RECEIVE_CFG, pool=_pool(), workflow_id="wf-1", node_id="wa-1",
        )
    assert "owner alerted" in msg
    alert.assert_awaited_once_with(
        "cred-1", provider_label="WhatsApp", session_status="failed",
        workflow_id="wf-1", workflow_name="My Bot", pool=ANY,
    )


@pytest.mark.asyncio
async def test_failed_status_event_skips_alert_when_own_connection_healthy():
    """The event names a WAHA session we can't map — a stale registration
    delivering another session's death must not flag a healthy credential."""
    alert = AsyncMock()
    with patch.dict(os.environ, {"WAHOOKS_API_KEY": "k"}), \
         patch("wahooks.WAHooks", lambda api_key: _StatusClient("connected")), \
         patch("utils.notifications.send_channel_disconnected_alert", alert):
        msg = await WhatsAppNode.handle_control_event(
            {"event": "session.status", "session": "s", "payload": {"status": "FAILED"}},
            RECEIVE_CFG, pool=_pool(), workflow_id="wf-1", node_id="wa-1",
        )
    assert "healthy" in msg
    alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_control_event_never_raises():
    pool = MagicMock()
    pool.fetchrow = AsyncMock(side_effect=RuntimeError("db down"))
    msg = await WhatsAppNode.handle_control_event(
        {"event": "session.status", "session": "s", "payload": {"status": "FAILED"}},
        RECEIVE_CFG, pool=pool, workflow_id="wf-1", node_id="wa-1",
    )
    assert "consumed" in msg  # still consumed — a broken handler must not fire the workflow


# ── manual-run truth check ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manual_run_on_dead_session_fails_loudly():
    node = _qr_node()
    with patch(
        "utils.whatsapp_qr.get_connection_statuses",
        AsyncMock(return_value={"conn-1": "failed"}),
    ):
        with pytest.raises(ValueError) as exc:
            await node.execute({})
    assert "Re-scan the QR" in str(exc.value)
    assert "do NOT create a new credential" in str(exc.value)


@pytest.mark.asyncio
async def test_manual_run_on_healthy_session_returns_no_event(monkeypatch):
    monkeypatch.delenv("WAHOOKS_API_KEY", raising=False)
    node = _qr_node()
    with patch(
        "utils.whatsapp_qr.get_connection_statuses",
        AsyncMock(return_value={"conn-1": "connected"}),
    ):
        result = await node.execute({})
    assert result["status"] == "no_event"
    assert "No live event" in result["message"]


@pytest.mark.asyncio
async def test_manual_run_with_unknown_status_never_fails(monkeypatch):
    """WAHooks unreachable = unknown, never dead (non-definitive-signal)."""
    monkeypatch.delenv("WAHOOKS_API_KEY", raising=False)
    node = _qr_node()
    with patch(
        "utils.whatsapp_qr.get_connection_statuses", AsyncMock(return_value=None)
    ):
        result = await node.execute({})
    assert result["status"] == "no_event"


# ── webhook subscription create-or-upgrade ──────────────────────────────────


class _WebhookClient:
    def __init__(self, existing):
        self.existing = existing
        self.created = []
        self.updated = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def list_webhooks(self, connection_id):
        return self.existing

    def create_webhook(self, connection_id, url, events):
        self.created.append((connection_id, url, events))

    def update_webhook(self, webhook_id, **kw):
        self.updated.append((webhook_id, kw))


def test_ensure_webhook_creates_with_status_subscription():
    client = _WebhookClient(existing=[])
    with patch("wahooks.WAHooks", lambda api_key: client):
        assert _wahooks_ensure_webhook("k", "conn-1", "https://wh.hooks.example.test") is True
    assert client.created == [("conn-1", "https://wh.hooks.example.test", WAHOOKS_WEBHOOK_EVENTS)]
    assert "session.status" in WAHOOKS_WEBHOOK_EVENTS


def test_ensure_webhook_upgrades_legacy_message_only_config():
    client = _WebhookClient(
        existing=[{"id": "wh-9", "url": "https://wh.hooks.example.test", "events": ["message"]}]
    )
    with patch("wahooks.WAHooks", lambda api_key: client):
        assert _wahooks_ensure_webhook("k", "conn-1", "https://wh.hooks.example.test") is True
    assert client.created == []
    assert client.updated == [("wh-9", {"events": ["message", "session.status"]})]


def test_ensure_webhook_noop_when_current():
    client = _WebhookClient(
        existing=[{"id": "wh-9", "url": "https://wh.hooks.example.test",
                   "events": ["message", "session.status"]}]
    )
    with patch("wahooks.WAHooks", lambda api_key: client):
        assert _wahooks_ensure_webhook("k", "conn-1", "https://wh.hooks.example.test") is False
    assert client.created == [] and client.updated == []


# ── status cache: an id the cache has never seen is a MISS, not "gone" ──────


class _ListClient:
    def __init__(self, connections, fetches):
        self._connections = connections
        self._fetches = fetches

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def list_connections(self):
        self._fetches.append(1)
        return self._connections


@pytest.fixture
def status_cache(monkeypatch):
    """A warm 60s cache that predates conn-new — exactly the state every
    picker list hits in the minute after a scan."""
    import time

    from utils import whatsapp_qr

    monkeypatch.setenv("WAHOOKS_API_KEY", "k")
    monkeypatch.setattr(whatsapp_qr, "_status_cache", (time.monotonic(), {"conn-1": "connected"}))
    fetches: list = []
    live = [{"id": "conn-1", "status": "connected"}, {"id": "conn-new", "status": "connected"}]
    monkeypatch.setattr("wahooks.WAHooks", lambda api_key: _ListClient(live, fetches))
    return fetches


@pytest.mark.asyncio
async def test_cached_statuses_serve_known_connections(status_cache):
    from utils.whatsapp_qr import get_connection_statuses

    assert await get_connection_statuses(require=["conn-1"]) == {"conn-1": "connected"}
    assert status_cache == []  # cache hit


@pytest.mark.asyncio
async def test_unseen_connection_forces_a_refetch_instead_of_missing(status_cache):
    """2026-08-29: a just-scanned connection was absent from the 60s cache, so
    the picker said "(disconnected)" and the loader refused to register — a
    healthy credential judged dead by a stale list."""
    from utils.whatsapp_qr import dead_session_status, get_connection_statuses

    statuses = await get_connection_statuses(require=["conn-new"])
    assert statuses["conn-new"] == "connected" and len(status_cache) == 1
    # The refreshed map is cached in turn.
    assert await dead_session_status("conn-new") is None
    assert len(status_cache) == 1


@pytest.mark.asyncio
async def test_absent_from_a_fresh_list_is_still_definitively_gone(status_cache):
    from utils.whatsapp_qr import dead_session_status

    assert await dead_session_status("conn-deleted") == "missing"


def test_remember_connection_status_stamps_the_live_cache(status_cache):
    from utils import whatsapp_qr

    whatsapp_qr.remember_connection_status("conn-new", "connected")
    assert whatsapp_qr._status_cache[1]["conn-new"] == "connected"


# ── phone-number backfill ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_phone_backfill_stamps_only_missing(monkeypatch):
    """Finalize often binds before WAHooks resolves the phone (16/17 prod rows
    were missing it) — without the backfill the same-phone rebind never fires
    for existing credentials."""
    from utils.wahooks_connections import backfill_credential_phone_numbers

    rows = [
        {"id": "cred-nophone", "metadata": {"connection_id": "conn-a"}},
        {"id": "cred-hasphone", "metadata": {"connection_id": "conn-b", "phone_number": "111"}},
        {"id": "cred-unknown-conn", "metadata": {"connection_id": "conn-zzz"}},
    ]
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    conn.execute = AsyncMock()
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire)

    class _Client:
        def __init__(self, api_key):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def list_connections(self):
            return [
                {"id": "conn-a", "status": "connected", "phoneNumber": "263771970778"},
                {"id": "conn-b", "status": "connected", "phoneNumber": "111"},
            ]

    monkeypatch.setenv("WAHOOKS_API_KEY", "k")
    monkeypatch.setattr("wahooks.WAHooks", _Client)

    summary = await backfill_credential_phone_numbers(pool)

    assert summary["stamped"] == ["cred-nophone"]
    conn.execute.assert_awaited_once()
    args = conn.execute.await_args.args
    assert args[1] == "cred-nophone" and args[2] == "263771970778"
    # The merge re-checks emptiness so a concurrent finalize-stamp wins.
    assert "COALESCE(metadata->>'phone_number', '') = ''" in args[0]


# ── daily sweep backstop ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sweep_alerts_only_referenced_dead_credentials(monkeypatch):
    """The daily backstop is provider-agnostic: every health-checked type is
    judged by the same registry the pickers read, and only in-use dead
    credentials produce an email — with that type's own fix-it hint."""
    from utils.credential_health import alert_dead_credentials

    rows = [
        {"id": "cred-dead", "owner_id": "u1", "organization_id": None, "credential_type": "whatsapp_qr",
         "metadata": {"connection_id": "conn-dead"}},
        {"id": "cred-live", "owner_id": "u1", "organization_id": None, "credential_type": "whatsapp_qr",
         "metadata": {"connection_id": "conn-live"}},
        {"id": "cred-unused", "owner_id": "u1", "organization_id": None, "credential_type": "whatsapp_qr",
         "metadata": {"connection_id": "conn-unused"}},
        {"id": "cred-rescanning", "owner_id": "u1", "organization_id": None, "credential_type": "whatsapp_qr",
         "metadata": {"connection_id": "conn-rescan"}},
        {"id": "cred-discord-gone", "owner_id": "u2", "organization_id": None, "credential_type": "discord_bot_install",
         "metadata": {"guild_id": "g-gone", "guild_name": "Old Server"}},
        {"id": "cred-discord-ok", "owner_id": "u2", "organization_id": None, "credential_type": "discord_bot_install",
         "metadata": {"guild_id": "g-ok"}},
    ]
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire)

    async def fake_refs(self, credential_id, owner_id, org_id):
        if credential_id == "cred-unused":
            return []
        return [{"workflow_id": "wf-1", "workflow_name": "Bot"}]

    async def probe(client, guild_id):
        return {"g-gone": 404, "g-ok": 200}[guild_id]

    alert = AsyncMock()
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "platform-token")
    monkeypatch.setattr("utils.credential_health._probe_discord_guild", probe)
    # The sweep reads the SAME cached status seam as every other health
    # consumer — one dead/alive rule everywhere. conn-unused absent → 'missing';
    # a bound connection mid-rescan holds a reservation and is not dead.
    monkeypatch.setattr(
        "utils.whatsapp_qr.get_connection_statuses",
        AsyncMock(return_value={"conn-dead": "failed", "conn-live": "connected", "conn-rescan": "scan_qr"}),
    )
    monkeypatch.setattr(
        "utils.wahooks_connections._has_active_reservation",
        AsyncMock(side_effect=lambda cid: cid == "conn-rescan"),
    )
    monkeypatch.setattr(
        "repositories.credentials.CredentialsRepo.list_workflows_referencing_credential",
        fake_refs,
    )
    monkeypatch.setattr("utils.notifications.send_channel_disconnected_alert", alert)

    summary = await alert_dead_credentials(pool)

    assert summary["alerted"] == ["cred-dead", "cred-discord-gone"]
    assert summary["dead_unreferenced"] == ["cred-unused"]
    whatsapp_call, discord_call = alert.await_args_list
    assert whatsapp_call.args == ("cred-dead",)
    assert whatsapp_call.kwargs["provider_label"] == "WhatsApp"
    assert whatsapp_call.kwargs["session_status"] == "failed"
    assert "re-scan" in whatsapp_call.kwargs["hint"].lower()
    assert whatsapp_call.kwargs["workflow_id"] == "wf-1"
    assert discord_call.args == ("cred-discord-gone",)
    assert discord_call.kwargs["provider_label"] == "Discord"
    assert discord_call.kwargs["session_status"] == "removed"
    assert "Old Server" in discord_call.kwargs["hint"] and "Install bot" in discord_call.kwargs["hint"]
