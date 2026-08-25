from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from wss.handlers.oauth.atlassian_oauth_handler import AtlassianOAuthHandler


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


@pytest.mark.asyncio
async def test_refresh_oauth_token_persists_granted_scopes(monkeypatch):
    """Manual refresh routes through the choke point (which persists the
    rotated tokens + expanded scope into the blob) and then syncs the granted
    scopes into metadata with a metadata-only UPDATE — never a blob write."""
    sio = AsyncMock()
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})

    handler = AtlassianOAuthHandler(sio)
    captured_events = []
    decrypted_credential = {
        "access_token": "old-token",
        "refresh_token": "refresh-1",
        "expires_at": "2026-05-27T00:00:00+00:00",  # expired — freshen refreshes
        "scope": "read:jira-work",
        "token_version": 3,
    }

    class _FakeConn:
        def __init__(self):
            self.execute = AsyncMock()

    conn = _FakeConn()
    handler.get_pool = AsyncMock(return_value=_FakePool(conn))

    async def _fake_send_event(_sio, _sid, response_event):
        captured_events.append(response_event)

    async def _fake_refresh_access_token(_refresh_token):
        return SimpleNamespace(
            access_token="new-token",
            refresh_token="refresh-2",
            expires_at="2099-05-28T00:00:00+00:00",
            scope="read:jira-work read:board-scope:jira-software",
            token_type="Bearer",
        )

    monkeypatch.setattr(
        "wss.handlers.oauth.atlassian_oauth_handler.send_event",
        _fake_send_event,
    )
    monkeypatch.setattr(
        "wss.handlers.oauth.atlassian_oauth_handler.refresh_access_token",
        _fake_refresh_access_token,
    )

    persist = AsyncMock(return_value=(1, None))
    with patch(
        "utils.credential_loader.load_credential",
        new=AsyncMock(return_value=dict(decrypted_credential)),
    ), patch(
        "utils.credentials.update_credential_data_detailed", new=persist
    ):
        request = SimpleNamespace(request_id="req-1", credential_id="cred-1")
        await handler.refresh_oauth_token("sid-1", request)

    # The choke point persisted the rotated tokens + expanded scope.
    persist.assert_awaited_once()
    persisted = persist.await_args.kwargs["new_data"]
    assert persisted["access_token"] == "new-token"
    assert persisted["refresh_token"] == "refresh-2"
    assert persisted["scope"] == "read:jira-work read:board-scope:jira-software"
    assert persist.await_args.kwargs["expected_token_version"] == 3

    # The handler synced granted scopes via a metadata-ONLY update.
    conn.execute.assert_awaited_once()
    sql, credential_id, metadata_updates = conn.execute.await_args.args
    assert "metadata = metadata ||" in sql
    assert "credential =" not in sql and "encrypted_data" not in sql
    assert credential_id == "cred-1"
    assert metadata_updates["scopes"] == [
        "read:jira-work",
        "read:board-scope:jira-software",
    ]

    assert captured_events
    assert captured_events[-1].data["success"] is True
