"""Claude reconnect must update the selected row without creating another one.

Exercise the actual handler, PKCE and SQL against test Postgres; only provider
HTTP and socket delivery are replaced.
"""
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
import respx

from tests.fixtures.real_db_fixture import real_database
from nodes.agent import harness_oauth_flows as flows
from nodes.agent.harness_oauth import CLAUDE_CODE_TOKEN_URL
from utils.encryption import get_encryption
from wss.handlers.oauth import claude_code_auth_handler as auth
from wss.receiver.client_events import (
    ClaudeCodeAuthStartRequest,
    ClaudeCodeAuthExchangeRequest,
)


@pytest_asyncio.fixture
async def account(real_database, monkeypatch):
    db = real_database
    user_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO auth.users (id, email) VALUES ($1, $2)",
        user_id,
        f"{user_id}@example.test",
    )
    encrypted = get_encryption().encrypt_credential(
        {"credentials": {"CLAUDE_CODE_ACCESS_TOKEN": "old"}}
    )
    credential_id = str(
        await db.fetchval(
            "INSERT INTO credentials (owner_id, organization_id, name, credential_type, credential, metadata) VALUES ($1, (SELECT organization_id FROM organization_members WHERE user_id=$1 AND is_primary=true LIMIT 1), 'My Claude', 'agent_claude_code_oauth', $2, '{}'::jsonb) RETURNING id",
            user_id,
            encrypted,
        )
    )
    sio = AsyncMock()
    sio.get_session.return_value = {
        "user_id": user_id,
        "user_data": {"subscription_tier": "free"},
    }
    handler = auth.ClaudeCodeAuthHandler(sio)
    monkeypatch.setattr(handler, "get_pool", AsyncMock(return_value=db.pool))
    monkeypatch.setattr(flows, "_get_redis", lambda: None)
    sent = AsyncMock()
    monkeypatch.setattr(auth, "send_event", sent)
    yield db, user_id, credential_id, handler, sent
    await db.execute("DELETE FROM credentials WHERE owner_id = $1", user_id)


@respx.mock
async def test_reconnect_keeps_id_name_and_count_and_replaces_tokens(account):
    db, user_id, credential_id, handler, sent = account
    await handler.start_oauth(
        "sid",
        ClaudeCodeAuthStartRequest(request_id="start", credential_id=credential_id),
    )
    start = sent.call_args.args[2].data
    assert start["success"] is True
    respx.post(CLAUDE_CODE_TOKEN_URL).respond(
        200,
        json={"access_token": "fresh", "refresh_token": "refresh", "expires_in": 3600},
    )
    await handler.exchange_code(
        "sid",
        ClaudeCodeAuthExchangeRequest(
            request_id="exchange",
            credential_id=credential_id,
            auth_session_id=start["auth_session_id"],
            authorization_code="new-code",
        ),
    )
    result = sent.call_args.args[2].data
    assert result["success"] is True, result
    assert result["credential_id"] == credential_id
    rows = await db.fetch(
        "SELECT id, name, credential FROM credentials WHERE owner_id=$1", user_id
    )
    assert len(rows) == 1
    assert rows[0]["name"] == "My Claude"
    assert (
        get_encryption().decrypt_credential(rows[0]["credential"])["credentials"][
            "CLAUDE_CODE_ACCESS_TOKEN"
        ]
        == "fresh"
    )


async def test_cannot_reconnect_another_owners_credential(account, monkeypatch):
    _, _, credential_id, handler, sent = account
    handler.sio.get_session.return_value = {"user_id": str(uuid.uuid4())}
    start = AsyncMock()
    monkeypatch.setattr(auth, "claude_code_start", start)
    await handler.start_oauth(
        "sid",
        ClaudeCodeAuthStartRequest(request_id="start", credential_id=credential_id),
    )
    start.assert_not_awaited()
    assert sent.call_args.args[2].data["error_code"] == "invalid_reconnect_target"
