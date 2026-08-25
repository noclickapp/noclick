"""Tests for WAHooks connection teardown + orphan reconciliation.

For months every teardown call site invoked a nonexistent
`encryption.decrypt`, swallowed the AttributeError, and deleted the DB row
anyway — every "deleted" WhatsApp connection stayed alive (and billed) at
WAHooks with the user's phone still linked. These tests pin the corrected
decrypt call, the keep-credential-on-teardown-failure semantics, and the
sweep that reconciles the ones already leaked.
"""
import pathlib
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


from utils.wahooks_connections import pick_orphan_connections, sweep_orphan_connections


BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_phantom_encryption_decrypt_calls():
    """CredentialEncryption has decrypt_credential, not decrypt. A phantom
    `.decrypt(` call raises AttributeError at runtime — inside best-effort
    try/excepts that made external teardown silently dead."""
    offenders = []
    for path in BACKEND_ROOT.rglob("*.py"):
        if "tests" in path.parts or ".venv" in path.parts:
            continue
        if re.search(r"encryption\.decrypt\(", path.read_text()):
            offenders.append(str(path.relative_to(BACKEND_ROOT)))
    assert not offenders, f"phantom encryption.decrypt() calls in: {offenders}"


# ── live_credential_connection_ids ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_ids_metadata_fast_path_handles_string_jsonb():
    """Pools without the jsonb codec (daily_maintenance's bare pool) return
    metadata as JSON text. The fast path must parse it — falling through to
    blob decryption crashes the sweep on any guard/placeholder row whose blob
    is deliberately not decryptable."""
    from utils.wahooks_connections import live_credential_connection_ids

    row = {
        "metadata": '{"connection_id": "conn-guard-1", "sweep_guard": true}',
        "credential": "not-a-decryptable-blob",
    }
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[row])
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    ids = await live_credential_connection_ids(pool)
    assert ids == {"conn-guard-1"}  # decrypt never attempted


# ── Orphan selection (pure) ────────────────────────────────────────────────────

def test_orphan_selection():
    connections = [
        {"id": "c-credentialed", "status": "connected"},
        {"id": "c-orphan-connected", "status": "connected"},
        {"id": "c-orphan-failed", "status": "failed"},
        {"id": "c-idle-pool", "status": "scan_qr"},  # reusable pool — never swept
        {"id": None, "status": "connected"},
    ]
    orphans = pick_orphan_connections(connections, {"c-credentialed"})
    assert orphans == ["c-orphan-connected", "c-orphan-failed"]


# ── Sweep ──────────────────────────────────────────────────────────────────────

class FakeWAHooksClient:
    def __init__(self, connections):
        self.connections = connections
        self.deleted = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def list_connections(self):
        return self.connections

    def delete_connection(self, cid):
        self.deleted.append(cid)


@pytest.mark.asyncio
async def test_sweep_deletes_orphans_and_keeps_credentialed(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "test-key")
    fake = FakeWAHooksClient([
        {"id": "c-live", "status": "connected"},
        {"id": "c-orphan", "status": "connected"},
        {"id": "c-idle", "status": "scan_qr"},
    ])

    pool = MagicMock()
    with patch("wahooks.WAHooks", return_value=fake), \
         patch("utils.wahooks_connections.live_credential_connection_ids",
               new=AsyncMock(return_value={"c-live"})), \
         patch("utils.wahooks_connections._has_active_reservation",
               new=AsyncMock(return_value=False)):
        summary = await sweep_orphan_connections(pool)

    assert fake.deleted == ["c-orphan"]
    assert summary["deleted"] == ["c-orphan"]
    assert summary["failed"] == []


@pytest.mark.asyncio
async def test_sweep_skips_reserved_connections(monkeypatch):
    """A connection mid-QR-flow (active reservation) is about to be bound —
    never sweep it."""
    monkeypatch.setenv("WAHOOKS_API_KEY", "test-key")
    fake = FakeWAHooksClient([{"id": "c-mid-scan", "status": "connected"}])

    with patch("wahooks.WAHooks", return_value=fake), \
         patch("utils.wahooks_connections.live_credential_connection_ids",
               new=AsyncMock(return_value=set())), \
         patch("utils.wahooks_connections._has_active_reservation",
               new=AsyncMock(return_value=True)):
        summary = await sweep_orphan_connections(MagicMock())

    assert fake.deleted == []
    assert summary["skipped_reserved"] == ["c-mid-scan"]


@pytest.mark.asyncio
async def test_sweep_without_api_key_is_a_noop(monkeypatch):
    monkeypatch.delenv("WAHOOKS_API_KEY", raising=False)
    assert await sweep_orphan_connections(MagicMock()) == {"skipped": "no_api_key"}


# ── Recurring cleanup teardown semantics ───────────────────────────────────────

async def _insert_credential_with_user(conn, encrypted="enc-blob"):
    user_id, cred_id = uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        "INSERT INTO auth.users (id, email, role) VALUES ($1, $2, 'authenticated') ON CONFLICT DO NOTHING",
        user_id, f"test-{user_id}@example.com",
    )
    await conn.execute(
        "INSERT INTO credentials (id, owner_id, credential_type, name, credential) VALUES ($1, $2, 'whatsapp_qr', 'test', $3)",
        cred_id, user_id, encrypted,
    )
    return user_id, cred_id




