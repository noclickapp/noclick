"""Relay viewer tokens: who can mint a token for which room.

A user room token opens exactly one user's room and is minted only for the
signed-in browser session's own user; a workflow room token only for a
workflow the session can access. API-key and share-link sessions get neither.
"""

import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest

from tests.fixtures.cas_fixtures import cas_pool, make_workflow, TEST_USER_ID  # noqa: F401
from utils.relay_tokens import (
    USER_ROOM_AUDIENCE,
    USER_ROOM_TOKEN_TTL_S,
    mint_user_room_token,
    verify_user_room_token,
)
from utils.sdk_permissions import PUBLISHED_APP, check_sdk_permission
from wss.handlers.workflow_handler import WorkflowHandler
from wss.receiver import rate_limiter as rate_limiter_module
from wss.receiver.rate_limiter import RateLimiter
from wss.receiver.rate_limits import get_rate_limit_config
from wss.receiver.client_events import RelayUserTokenRequest, WorkflowCollabTokenRequest
from wss.receiver.receiver import SHARED_VISITOR_ALLOWED_EVENTS

SECRET = "relay-viewer-test-secret-0123456789abcdef"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("WORKFLOW_JWT_SECRET", SECRET)


def _handler(session, pool=None):
    h = WorkflowHandler(sio=AsyncMock())
    h.sio.get_session = AsyncMock(return_value=session)
    h.get_pool = AsyncMock(return_value=pool)
    return h


def _response(handler) -> dict:
    for call in reversed(handler.sio.emit.call_args_list):
        if call.args and call.args[0] == "response":
            return call.args[1]["data"]
    raise AssertionError("no response emitted")


async def _mint_user(session) -> dict:
    handler = _handler(session)
    await handler.get_relay_user_token("sid", RelayUserTokenRequest(request_id="r1"))
    return _response(handler)


# ── the token itself ─────────────────────────────────────────────────────


def test_user_room_token_opens_only_its_own_room():
    token, expires_at = mint_user_room_token("alice")
    claims = verify_user_room_token(token, "alice")
    assert claims["sub"] == "alice"
    assert claims["aud"] == USER_ROOM_AUDIENCE
    assert expires_at - int(time.time()) == pytest.approx(USER_ROOM_TOKEN_TTL_S, abs=2)
    with pytest.raises(jwt.InvalidTokenError):
        verify_user_room_token(token, "mallory")


@pytest.mark.parametrize("claims", [
    pytest.param({"sub": "alice", "workflowId": "wf1", "name": "A"}, id="workflow-collab"),
    pytest.param({"sub": "alice", "workflowId": "wf1", "role": "executor", "executionId": "e"}, id="executor"),
    pytest.param({"sub": "alice", "aud": "relay:workflow"}, id="other-audience"),
])
def test_other_tokens_on_the_same_secret_do_not_open_a_user_room(claims):
    now = int(time.time())
    token = jwt.encode({"iat": now, "exp": now + 300, **claims}, SECRET, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        verify_user_room_token(token, "alice")


def test_expired_or_forged_user_room_tokens_are_refused():
    now = int(time.time())
    expired = jwt.encode(
        {"sub": "alice", "aud": USER_ROOM_AUDIENCE, "iat": now - 600, "exp": now - 60}, SECRET, algorithm="HS256",
    )
    forged = jwt.encode(
        {"sub": "alice", "aud": USER_ROOM_AUDIENCE, "iat": now, "exp": now + 300}, "not-the-secret", algorithm="HS256",
    )
    no_expiry = jwt.encode({"sub": "alice", "aud": USER_ROOM_AUDIENCE}, SECRET, algorithm="HS256")
    for token in (expired, forged, no_expiry):
        with pytest.raises(jwt.InvalidTokenError):
            verify_user_room_token(token, "alice")


def test_no_signing_secret_mints_nothing(monkeypatch):
    monkeypatch.delenv("WORKFLOW_JWT_SECRET")
    with pytest.raises(RuntimeError):
        mint_user_room_token("alice")


# ── relay:user_token ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_browser_session_mints_for_its_own_user_only():
    data = await _mint_user({"user_id": "alice", "user_data": {}})
    assert data["success"] is True
    assert data["user_id"] == "alice"
    # The request names no user: the token is always for the session's own.
    assert verify_user_room_token(data["token"], "alice")["sub"] == "alice"
    with pytest.raises(jwt.InvalidTokenError):
        verify_user_room_token(data["token"], "bob")


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [
    pytest.param({}, id="signed-out"),
    pytest.param({"share_scope": {"link_id": "l", "owner_id": "alice"}}, id="share-link-visitor"),
    pytest.param(
        {"user_id": "alice", "sdk_key_id": "k", "sdk_workflow_id": "wf1", "sdk_permissions": ["read", "execute", "write"]},
        id="api-key",
    ),
])
async def test_sessions_that_are_not_the_signed_in_user_mint_nothing(session):
    data = await _mint_user(session)
    assert data["success"] is False
    assert data["token"] is None


def test_scoped_sessions_are_refused_before_any_relay_token_handler():
    for event in ("relay:user_token", "workflow:collab_token"):
        assert event not in SHARED_VISITOR_ALLOWED_EVENTS
        assert check_sdk_permission(event, ["read", "execute", "write"]) is not None
        assert check_sdk_permission(event, ["read", "execute", "write"], sdk_workflow_id="wf1",
                                    request_workflow_ids=frozenset({"wf1"})) is not None
        assert check_sdk_permission(event, [PUBLISHED_APP, "read", "execute", "write"]) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["relay:user_token", "workflow:collab_token"])
async def test_minting_relay_tokens_is_rate_limited(monkeypatch, event):
    clock = [1_000.0]
    monkeypatch.setattr(rate_limiter_module, "time", SimpleNamespace(time=lambda: clock[0]))
    limit = get_rate_limit_config().per_event_rate_limits[event]
    limiter = RateLimiter(get_rate_limit_config())

    async def mint() -> bool:
        return (await limiter.check_rate_limit("sid", event))[0]

    # A burst past the per-second limit is refused.
    assert [await mint() for _ in range(limit.second + 1)] == [True] * limit.second + [False]

    # Spread out under the per-second limit, the per-minute limit still holds.
    clock[0] += 120
    allowed = 0
    for _ in range(limit.minute + 5):
        clock[0] += 1.0 / limit.second + 0.01
        allowed += await mint()
    assert allowed == limit.minute

    # Another tab (sid) has its own budget.
    assert (await limiter.check_rate_limit("other-sid", event))[0] is True


# ── workflow:collab_token (the workflow room's token) ────────────────────


@pytest.mark.asyncio
async def test_collab_token_only_for_a_workflow_the_session_can_access(cas_pool):  # noqa: F811
    wid = await make_workflow(cas_pool)

    owner = _handler({"user_id": str(TEST_USER_ID), "user_data": {}}, pool=cas_pool)
    await owner.get_collab_token("sid", WorkflowCollabTokenRequest(request_id="r1", workflow_id=str(wid)))
    data = _response(owner)
    assert data["success"] is True
    claims = jwt.decode(data["token"], SECRET, algorithms=["HS256"])
    assert claims["workflowId"] == str(wid)
    assert claims["sub"] == str(TEST_USER_ID)

    stranger = _handler({"user_id": str(uuid.uuid4()), "user_data": {}}, pool=cas_pool)
    await stranger.get_collab_token("sid", WorkflowCollabTokenRequest(request_id="r2", workflow_id=str(wid)))
    data = _response(stranger)
    assert data["success"] is False
    assert data["token"] is None
