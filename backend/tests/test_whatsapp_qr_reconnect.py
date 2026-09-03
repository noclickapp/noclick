"""Reconnect-not-remint behavior for WhatsApp QR credentials.

A reconnect must reuse the existing binding instead of creating duplicate
credential rows and provider-side device links. Two repair layers are pinned
here:

1. start_qr_connection(reconnect_credential_id=…) re-scans into the SAME
   connection, so finalize resolves as the idempotent own-binding success.
2. finalize_qr_connection rebinds a fresh scan of an already-credentialed
   phone to that owner's EXISTING credential in place of an INSERT — the
   choke-point fix that covers every entry surface (panel, provide link,
   builder drawer) at once.
"""
import sys
import types
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_whatsapp_qr_bind_guard import (  # noqa: F401 (fixtures)
    FakeRedis,
    _PoolShim,
    fake_redis,
)

from utils.whatsapp_qr import finalize_qr_connection, start_qr_connection


class _StubEncryption:
    def encrypt_credential(self, data):
        return f"enc:{data['connection_id']}"


async def _seed_user(conn):
    owner = uuid.uuid4()
    await conn.execute(
        "INSERT INTO auth.users (id, email, role) VALUES ($1, $2, 'authenticated')",
        owner, f"test-{owner}@example.com",
    )
    return owner


async def _seed_credential(conn, owner, connection_id, phone=None):
    cred_id = uuid.uuid4()
    meta = {"provider": "wahooks", "connection_id": connection_id}
    if phone:
        meta["phone_number"] = phone
    await conn.execute(
        """INSERT INTO credentials (id, owner_id, credential_type, name, credential, metadata)
           VALUES ($1, $2, 'whatsapp_qr', 'WhatsApp (QR)', 'enc-old', $3)""",
        cred_id, owner, meta,
    )
    return cred_id


@pytest.fixture
def stub_wahooks_reconnect(monkeypatch):
    """wahooks SDK stub covering the reconnect + finalize surfaces."""
    calls = {
        "get_qr": [], "created": 0, "get_or_create": 0, "connections": {},
        "webhooks": {}, "seq": [],
    }

    class StubClient:
        def __init__(self, api_key):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_qr(self, connection_id):
            calls["get_qr"].append(connection_id)
            if connection_id == "conn-gone":
                raise mod.WAHooksError("404 connection not found")
            return {"qr": f"QR-{connection_id}"}

        def get_or_create_scannable_connection(self, virgin_only=False):
            calls["get_or_create"] += 1
            return {"id": "conn-virgin", "qr": "QR-virgin"}

        def create_connection(self):
            calls["created"] += 1
            return {"id": "conn-fresh", "qr": "QR-fresh"}

        def get_connection(self, connection_id):
            return calls["connections"].get(
                connection_id, {"status": "connected", "phoneNumber": ""}
            )

        def list_webhooks(self, connection_id):
            if connection_id == "conn-broken":
                raise mod.WAHooksError("500 webhooks unavailable")
            return list(calls["webhooks"].get(connection_id, []))

        def create_webhook(self, connection_id, url, events):
            calls["seq"].append(("create_webhook", connection_id))
            calls["webhooks"].setdefault(connection_id, []).append(
                {"id": f"wh-{len(calls['seq'])}", "url": url, "events": events}
            )

    mod = types.ModuleType("wahooks")
    mod.WAHooks = StubClient
    mod.WAHooksError = type("WAHooksError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "wahooks", mod)
    monkeypatch.setenv("WAHOOKS_API_KEY", "test-key")
    return calls


@pytest.mark.asyncio
class TestStartReconnect:
    async def test_reconnect_reuses_own_connection(
        self, postgres_db, fake_redis, stub_wahooks_reconnect  # noqa: F811
    ):
        owner = await _seed_user(postgres_db)
        cred_id = await _seed_credential(postgres_db, owner, "conn-own")

        result = await start_qr_connection(
            _PoolShim(postgres_db), owner_id=str(owner),
            reconnect_credential_id=str(cred_id),
        )
        assert result["success"] is True
        assert result["connection_id"] == "conn-own"
        assert result["reconnect"] is True
        assert stub_wahooks_reconnect["get_qr"] == ["conn-own"]
        # No new connection minted — the whole point.
        assert stub_wahooks_reconnect["get_or_create"] == 0
        assert stub_wahooks_reconnect["created"] == 0
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")

    async def test_reconnect_falls_back_when_connection_gone(
        self, postgres_db, fake_redis, stub_wahooks_reconnect  # noqa: F811
    ):
        owner = await _seed_user(postgres_db)
        cred_id = await _seed_credential(postgres_db, owner, "conn-gone")

        result = await start_qr_connection(
            _PoolShim(postgres_db), owner_id=str(owner),
            reconnect_credential_id=str(cred_id),
        )
        # Falls through to a normal scan; finalize's phone rebind repairs later.
        assert result["success"] is True
        assert result["connection_id"] == "conn-virgin"
        assert "reconnect" not in result
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")

    async def test_reconnect_ignores_foreign_credential(
        self, postgres_db, fake_redis, stub_wahooks_reconnect  # noqa: F811
    ):
        other_owner = await _seed_user(postgres_db)
        foreign_cred = await _seed_credential(postgres_db, other_owner, "conn-foreign")
        caller = await _seed_user(postgres_db)

        result = await start_qr_connection(
            _PoolShim(postgres_db), owner_id=str(caller),
            reconnect_credential_id=str(foreign_cred),
        )
        # Owner-scoped lookup misses → normal flow; the foreign connection's QR
        # is never fetched.
        assert result["connection_id"] == "conn-virgin"
        assert stub_wahooks_reconnect["get_qr"] == []
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")


@pytest.mark.asyncio
class TestFinalizeSamePhoneRebind:
    async def test_fresh_scan_rebinds_existing_credential(
        self, monkeypatch, postgres_db, fake_redis, stub_wahooks_reconnect  # noqa: F811
    ):
        start_charge = AsyncMock()
        monkeypatch.setattr("billing.recurring.start_connection_charge", start_charge)
        owner = await _seed_user(postgres_db)
        cred_id = await _seed_credential(postgres_db, owner, "conn-old", phone="12025550105")
        stub_wahooks_reconnect["connections"]["conn-new"] = {
            "status": "connected", "phoneNumber": "12025550105",
        }
        await fake_redis.set("whatsapp:qr:reserved:conn-new", str(owner))
        # A trigger registered on the replaced connection (WAHooks webhooks
        # are per-connection — it dies with the delete unless carried over).
        stub_wahooks_reconnect["webhooks"]["conn-old"] = [
            {"id": "wh-old", "url": "https://wh-1.hooks.example.test",
             "events": ["message", "session.status"]},
        ]

        async def _delete(connection_id):
            stub_wahooks_reconnect["seq"].append(("delete", connection_id))

        deleted = AsyncMock(side_effect=_delete)
        with patch("utils.wahooks_connections.delete_wahooks_connection", deleted), \
             patch("utils.credentials.get_encryption", return_value=_StubEncryption()):
            result = await finalize_qr_connection(
                _PoolShim(postgres_db), owner_id=str(owner), connection_id="conn-new",
                user_tier="plus", encryption=_StubEncryption(),
            )

        assert result["success"] is True
        assert result["credential_id"] == str(cred_id)  # SAME credential, repaired
        assert result["created"] is False
        # The trigger's webhook rides along to the new connection, BEFORE the
        # old one is torn down (2026-08-29: a re-scan left a trigger deaf).
        assert stub_wahooks_reconnect["webhooks"]["conn-new"] == [
            {"id": "wh-1", "url": "https://wh-1.hooks.example.test",
             "events": ["message", "session.status"]},
        ]
        assert stub_wahooks_reconnect["seq"] == [
            ("create_webhook", "conn-new"), ("delete", "conn-old"),
        ]
        row = await postgres_db.fetchrow(
            "SELECT credential, metadata FROM credentials WHERE id = $1", cred_id
        )
        assert row["credential"] == "enc:conn-new"
        assert row["metadata"]["connection_id"] == "conn-new"
        deleted.assert_awaited_once_with("conn-old")
        # No duplicate row, no duplicate recurring charge.
        count = await postgres_db.fetchval(
            "SELECT count(*) FROM credentials WHERE credential_type = 'whatsapp_qr'"
        )
        assert count == 1
        # A rebind never starts a second billing clock: the platform's charge
        # seam is not touched (the engine's default is nothing to bill).
        start_charge.assert_not_awaited()
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")

    async def test_rebind_keeps_old_connection_when_webhooks_cannot_move(
        self, postgres_db, fake_redis, stub_wahooks_reconnect  # noqa: F811
    ):
        """Deleting the replaced connection without its webhooks would silently
        unregister every trigger on it, so a failed carry-over leaves the old
        link alive (still delivering) for the orphan sweep."""
        owner = await _seed_user(postgres_db)
        cred_id = await _seed_credential(postgres_db, owner, "conn-broken", phone="12025550105")
        stub_wahooks_reconnect["connections"]["conn-new"] = {
            "status": "connected", "phoneNumber": "12025550105",
        }
        await fake_redis.set("whatsapp:qr:reserved:conn-new", str(owner))

        deleted = AsyncMock()
        with patch("utils.wahooks_connections.delete_wahooks_connection", deleted), \
             patch("utils.credentials.get_encryption", return_value=_StubEncryption()):
            result = await finalize_qr_connection(
                _PoolShim(postgres_db), owner_id=str(owner), connection_id="conn-new",
                user_tier="plus", encryption=_StubEncryption(),
            )

        assert result["success"] is True and result["credential_id"] == str(cred_id)
        deleted.assert_not_awaited()
        row = await postgres_db.fetchrow("SELECT metadata FROM credentials WHERE id = $1", cred_id)
        assert row["metadata"]["connection_id"] == "conn-new"  # rebind itself still lands
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")

    async def test_rebind_never_crosses_owners(
        self, postgres_db, fake_redis, stub_wahooks_reconnect  # noqa: F811
    ):
        other_owner = await _seed_user(postgres_db)
        foreign_cred = await _seed_credential(
            postgres_db, other_owner, "conn-theirs", phone="12025550105"
        )
        caller = await _seed_user(postgres_db)
        stub_wahooks_reconnect["connections"]["conn-new"] = {
            "status": "connected", "phoneNumber": "12025550105",
        }
        await fake_redis.set("whatsapp:qr:reserved:conn-new", str(caller))

        result = await finalize_qr_connection(
            _PoolShim(postgres_db), owner_id=str(caller), connection_id="conn-new",
            user_tier="plus", encryption=_StubEncryption(),
        )
        # The other owner's credential is untouched; the caller gets their own.
        row = await postgres_db.fetchrow(
            "SELECT metadata FROM credentials WHERE id = $1", foreign_cred
        )
        assert row["metadata"]["connection_id"] == "conn-theirs"
        if result["success"]:
            assert result["credential_id"] != str(foreign_cred)
            assert result["created"] is True
        await postgres_db.execute("DELETE FROM credentials WHERE credential_type = 'whatsapp_qr'")
