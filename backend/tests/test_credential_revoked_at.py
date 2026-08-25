"""Tests that revoked credentials stay unreadable and reconnects clear the flag."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest


class _Conn:
    """Tiny mock asyncpg connection. Returns whatever fetchrow_value yields."""

    def __init__(self, fetchrow_value=None, execute_value="UPDATE 1"):
        self._fetchrow_value = fetchrow_value
        self._execute_value = execute_value
        self.execute = AsyncMock(return_value=execute_value)
        self.fetchrow = AsyncMock(return_value=fetchrow_value)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self._conn


class TestLoadCredentialRevokedGate:
    async def test_load_returns_none_when_revoked_at_set(self):
        from utils.credential_loader import load_credential

        conn = _Conn(fetchrow_value={
            "credential": b"<encrypted-blob>",
            "revoked_at": datetime(2026, 6, 8, tzinfo=timezone.utc),
        })
        pool = _Pool(conn)
        # Stub the org-context query that load_credential makes first.
        conn.fetchrow = AsyncMock(side_effect=[
            None,  # org context lookup
            {
                "credential": b"<encrypted-blob>",
                "revoked_at": datetime(2026, 6, 8, tzinfo=timezone.utc),
            },
        ])

        with patch("utils.encryption.get_encryption") as enc:
            enc.return_value.decrypt_credential.return_value = {"access_token": "should-not-decode"}
            result = await load_credential(pool, "u", "c-revoked")

        # Decryption must NOT happen on revoked rows.
        assert result is None
        enc.return_value.decrypt_credential.assert_not_called()

    async def test_load_returns_data_when_revoked_at_null(self):
        from utils.credential_loader import load_credential

        conn = _Conn()
        pool = _Pool(conn)
        conn.fetchrow = AsyncMock(side_effect=[
            None,
            {"credential": b"<enc>", "revoked_at": None, "token_version": 3, "updated_at": None},
        ])
        with patch("utils.encryption.get_encryption") as enc:
            enc.return_value.decrypt_credential.return_value = {"access_token": "ok"}
            result = await load_credential(pool, "u", "c-active")
        assert result == {"access_token": "ok", "token_version": 3}


class TestGetCredentialRevokedGate:
    async def test_get_returns_none_when_revoked(self):
        from utils.credentials import get_credential

        conn = _Conn(fetchrow_value={
            "credential": b"<enc>",
            "revoked_at": datetime(2026, 6, 8, tzinfo=timezone.utc),
        })
        pool = _Pool(conn)
        with patch("utils.encryption.get_encryption") as enc:
            enc.return_value.decrypt_credential.return_value = {"access_token": "x"}
            result = await get_credential("c-revoked", "u", pool=pool)
        assert result is None
        enc.return_value.decrypt_credential.assert_not_called()


class TestUpdateCredentialClearsRevokedAt:
    async def test_update_sql_clears_revoked_at(self):
        """Successful write of a credential clears revoked_at so reconnect /
        successful refresh auto-recover."""
        from utils.credentials import update_credential_data_detailed

        conn = _Conn(execute_value="UPDATE 1")
        pool = _Pool(conn)
        with patch("utils.encryption.get_encryption") as enc:
            enc.return_value.encrypt_credential.return_value = b"<enc>"
            rows, err = await update_credential_data_detailed(
                credential_id="c1",
                user_id="u1",
                new_data={"access_token": "new"},
                pool=pool,
            )
        assert rows == 1 and err is None

        # The execute SQL MUST contain `revoked_at = NULL` and `revoked_reason = NULL`.
        sql_called = conn.execute.await_args.args[0]
        assert "revoked_at = NULL" in sql_called, (
            f"Expected revoked_at clear in UPDATE; got: {sql_called!r}"
        )
        assert "revoked_reason = NULL" in sql_called

    async def test_update_with_metadata_also_clears_revoked_at(self):
        from utils.credentials import update_credential_data_detailed

        conn = _Conn(execute_value="UPDATE 1")
        pool = _Pool(conn)
        with patch("utils.encryption.get_encryption") as enc:
            enc.return_value.encrypt_credential.return_value = b"<enc>"
            rows, err = await update_credential_data_detailed(
                credential_id="c1",
                user_id="u1",
                new_data={"access_token": "new"},
                metadata_updates={"last_refreshed_at": "2026-06-08T00:00:00Z"},
                pool=pool,
            )
        assert rows == 1
        sql_called = conn.execute.await_args.args[0]
        assert "revoked_at = NULL" in sql_called




