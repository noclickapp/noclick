from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from wss.handlers.oauth.slack_oauth_handler import SlackOAuthHandler


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
async def test_exchange_oauth_code_updates_existing_workspace_credential_for_same_owner(
    monkeypatch,
):
    sio = AsyncMock()
    sio.get_session = AsyncMock(
        return_value={
            "user_id": "user-1",
            "user_data": {"subscription_tier": "free"},
        }
    )
    handler = SlackOAuthHandler(sio)

    captured_events = []
    captured_updates = []

    class _FakeEncryption:
        def encrypt_credential(self, data):
            return "encrypted-credential"

        def decrypt_credential(self, _data):
            return {
                "team_id": "T1",
                "app_id": "A1",
                "client_id": None,
            }

    handler.encryption = _FakeEncryption()

    conn = SimpleNamespace(
        fetchrow=AsyncMock(
            return_value={
                "id": "cred-existing",
                "name": "Old Slack",
                "credential": "old-encrypted",
                "metadata": {},
            }
        ),
        execute=AsyncMock(return_value="UPDATE 1"),
    )
    handler.get_pool = AsyncMock(return_value=_FakePool(conn))

    async def _fake_send_event(_sio, _sid, response_event):
        captured_events.append(response_event)

    async def _fake_update_credential_data(**kwargs):
        captured_updates.append(kwargs)
        return True

    async def _fake_exchange_code_for_tokens(**_kwargs):
        tokens = SimpleNamespace(
            access_token="xoxe.xoxb-new",
            refresh_token="xoxe-refresh",
            expires_at="2026-06-03T00:00:00+00:00",
            token_type="bot",
            scope="channels:read,chat:write",
            app_id="A1",
            user_access_token="xoxe.xoxp-user",
            user_refresh_token="user-refresh",
            user_expires_at="2026-06-03T00:00:00+00:00",
            user_id_xoxp="U1",
        )
        workspace = SimpleNamespace(team_id="T1", team_name="Workspace", bot_user_id="B1")
        return tokens, workspace

    async def _unexpected_create(*_args, **_kwargs):
        raise AssertionError("should update existing Slack credential instead of creating a new one")

    monkeypatch.setattr(
        "wss.handlers.oauth.slack_oauth_handler.send_event",
        _fake_send_event,
    )
    monkeypatch.setattr(
        "wss.handlers.oauth.slack_oauth_handler.exchange_code_for_tokens",
        _fake_exchange_code_for_tokens,
    )
    monkeypatch.setattr(
        "wss.handlers.oauth.slack_oauth_handler.update_credential_data",
        _fake_update_credential_data,
    )
    monkeypatch.setattr(
        "wss.handlers.oauth.slack_oauth_handler.upsert_slack_installation_from_exchange",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "repositories.credentials.create_credential_with_limit_check",
        _unexpected_create,
    )

    request = SimpleNamespace(
        request_id="req-1",
        code="code-123",
        redirect_uri="https://example.com/callback",
        client_id=None,
        client_secret=None,
        credential_name="Slack Workspace",
        scopes=["channels:read", "chat:write"],
    )

    await handler.exchange_oauth_code("sid-1", request)

    assert len(captured_updates) == 1
    assert captured_updates[0]["credential_id"] == "cred-existing"
    assert captured_updates[0]["new_data"]["access_token"] == "xoxe.xoxb-new"
    assert captured_updates[0]["new_data"]["user_access_token"] == "xoxe.xoxp-user"
    conn.execute.assert_awaited_once()

    assert captured_events, "Expected success response event"
    data = captured_events[-1].data
    assert data["success"] is True
    assert data["credential_id"] == "cred-existing"
