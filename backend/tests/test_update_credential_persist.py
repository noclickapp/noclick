"""Tests for update_credential_data — the system token-refresh persist.

This write is keyed by credential_id ONLY (not owner-filtered): access is
verified when the credential is loaded, and a refreshed single-use rotating
token MUST be saved regardless of which user ran the workflow, or a shared/org
credential refreshed by a non-owner is bricked. These tests pin that contract
(it previously filtered WHERE owner_id=$, which silently dropped non-owner
refreshes and, combined with the new persist-raise, would fail their runs).

Run: pytest tests/test_update_credential_persist.py -v
"""

from unittest.mock import patch

from utils.credentials import update_credential_data


class _FakeConn:
    def __init__(self, result="UPDATE 1"):
        self.result = result
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return self.result


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


async def test_persist_is_keyed_by_credential_id_not_owner():
    conn = _FakeConn()
    pool = _FakePool(conn)
    with patch("utils.credentials.get_encryption") as enc:
        enc.return_value.encrypt_credential.return_value = b"ENC"
        ok = await update_credential_data(
            credential_id="cid-123",
            user_id="not-the-owner",
            new_data={"access_token": "fresh"},
            metadata_updates={"expires_at": "2026-01-01T00:00:00+00:00"},
            pool=pool,
        )
    assert ok is True
    query, args = conn.executed[0]
    assert "WHERE id =" in query
    assert "owner_id" not in query  # system write — not owner-gated
    assert "cid-123" in args
    assert "not-the-owner" not in args  # runner is never used to filter the write


async def test_persist_returns_false_on_missing_row():
    conn = _FakeConn(result="UPDATE 0")
    pool = _FakePool(conn)
    with patch("utils.credentials.get_encryption") as enc:
        enc.return_value.encrypt_credential.return_value = b"ENC"
        ok = await update_credential_data(
            credential_id="cid-404",
            user_id="u",
            new_data={"access_token": "x"},
            pool=pool,
        )
    assert ok is False  # genuinely-missing row -> caller (ensure_fresh_oauth_token) raises
