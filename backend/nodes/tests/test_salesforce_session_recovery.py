"""Exercise early Salesforce session revocation without live provider activity.

The real node and shared refresher run against deterministic HTTP responses;
no customer credentials, database or Salesforce requests are used.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.oauth.salesforce_oauth import SalesforceTokens
from nodes.salesforce_node import (
    SalesforceGetLimitsConfig,
    SalesforceNode,
    SalesforceNodeConfig,
    SalesforceOAuthCredential,
)


def make_node():
    credential = SalesforceOAuthCredential(
        access_token="old-access",
        refresh_token="old-refresh",
        instance_url="https://controlled.my.salesforce.com",
        expires_at="2099-12-31T23:59:59Z",
    )
    node = SalesforceNode(
        node_id="isolated-test-node",
        node_type="automation-salesforce",
        node_data={},
        config=SalesforceNodeConfig(
            config=SalesforceGetLimitsConfig(), credentials=credential
        ),
        sio=None,
        sid=None,
        workflow_id="isolated-test-workflow",
        user_id="isolated-test-user",
    )
    return node, credential


@pytest.fixture
def provider(monkeypatch):
    client = type("Client", (), {})()
    client.request = AsyncMock()

    @asynccontextmanager
    async def guarded_client(**kwargs):
        yield client

    refresh = AsyncMock(
        return_value=SalesforceTokens(
            access_token="new-access",
            refresh_token="new-refresh",
            instance_url="https://controlled.my.salesforce.com",
            expires_at="2099-12-31T23:59:59Z",
        )
    )
    monkeypatch.setattr("nodes.salesforce_node.guarded_async_client", guarded_client)
    monkeypatch.setattr("nodes.salesforce_node.refresh_access_token", refresh)
    return client, refresh


def revoked_response():
    return httpx.Response(
        401,
        json=[
            {"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}
        ],
    )


@pytest.mark.asyncio
async def test_revoked_but_unexpired_read_recovers_once(provider):
    client, refresh = provider
    node, credential = make_node()
    client.request.side_effect = [
        revoked_response(),
        httpx.Response(200, json={"DailyApiRequests": {"Remaining": 100}}),
    ]

    result = await node._make_request("GET", "/limits", credential)

    assert result["status"] == "success"
    assert result["data"]["DailyApiRequests"]["Remaining"] == 100
    assert credential.access_token == "new-access"
    assert credential.refresh_token == "new-refresh"
    refresh.assert_awaited_once_with(
        "old-refresh", "https://controlled.my.salesforce.com", False
    )
    assert client.request.await_count == 2
    assert (
        client.request.await_args_list[0].kwargs["headers"]["Authorization"]
        == "Bearer old-access"
    )
    assert (
        client.request.await_args_list[1].kwargs["headers"]["Authorization"]
        == "Bearer new-access"
    )


@pytest.mark.asyncio
async def test_second_invalid_session_is_not_retried(provider):
    client, refresh = provider
    node, credential = make_node()
    client.request.side_effect = [revoked_response(), revoked_response()]

    result = await node._make_request("GET", "/limits", credential)

    assert result["status"] == "error"
    assert result["status_code"] == 401
    assert result["error_code"] == "INVALID_SESSION_ID"
    assert client.request.await_count == 2
    refresh.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
async def test_mutating_requests_never_replay_or_refresh(provider, method):
    client, refresh = provider
    node, credential = make_node()
    client.request.return_value = revoked_response()

    result = await node._make_request(
        method, "/sobjects/Account", credential, json_body={"Name": "isolated"}
    )

    assert result["status"] == "error"
    assert result["status_code"] == 401
    client.request.assert_awaited_once()
    refresh.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json=[{"errorCode": "OTHER_ERROR"}]),
        httpx.Response(401, text="not JSON"),
        httpx.Response(401, json=[None, "INVALID_SESSION_ID"]),
        httpx.Response(403, json=[{"errorCode": "INVALID_SESSION_ID"}]),
        httpx.Response(429, json=[{"errorCode": "INVALID_SESSION_ID"}]),
        httpx.Response(500, json=[{"errorCode": "INVALID_SESSION_ID"}]),
    ],
)
async def test_only_explicit_invalid_session_401_recovers(provider, response):
    client, refresh = provider
    node, credential = make_node()
    client.request.return_value = response

    result = await node._make_request("GET", "/limits", credential)

    assert result["status"] == "error"
    assert result["status_code"] == response.status_code
    client.request.assert_awaited_once()
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_head_and_object_shaped_invalid_session_recover(provider):
    client, refresh = provider
    node, credential = make_node()
    client.request.side_effect = [
        httpx.Response(401, json={"errorCode": "INVALID_SESSION_ID"}),
        httpx.Response(204),
    ]

    result = await node._make_request("HEAD", "/limits", credential)

    assert result["status"] == "success"
    assert result["data"] == {"success": True}
    assert client.request.await_count == 2
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_refresh_fails_without_replaying_read(provider):
    client, refresh = provider
    node, credential = make_node()
    client.request.return_value = revoked_response()
    refresh.side_effect = ValueError("Refresh token expired; reconnect Salesforce")

    result = await node._make_request("GET", "/limits", credential)

    assert result["status"] == "error"
    assert "reconnect" in result["error"].lower()
    assert "old-access" not in str(result)
    assert "old-refresh" not in str(result)
    assert credential.access_token == "old-access"
    client.request.assert_awaited_once()
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_normal_read_uses_refreshed_instance_origin(provider):
    client, refresh = provider
    node, credential = make_node()
    refresh.return_value.instance_url = "https://rotated.my.salesforce.com"
    client.request.side_effect = [revoked_response(), httpx.Response(200, json={})]

    result = await node._make_request("GET", "/limits", credential)

    assert result["status"] == "success"
    assert credential.instance_url == "https://rotated.my.salesforce.com"
    assert client.request.await_args_list[1].kwargs["url"] == (
        "https://rotated.my.salesforce.com/services/data/v63.0/limits"
    )


@pytest.mark.asyncio
async def test_opaque_url_cannot_receive_token_for_changed_instance(provider):
    client, refresh = provider
    node, credential = make_node()
    refresh.return_value.instance_url = "https://rotated.my.salesforce.com"
    client.request.return_value = revoked_response()

    result = await node._make_request(
        "GET",
        "https://controlled.my.salesforce.com/services/data/v63.0/query/next",
        credential,
        use_full_url=True,
    )

    assert result["status"] == "error"
    client.request.assert_awaited_once()
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_in_lock_reread_reuses_concurrent_repair(provider, monkeypatch):
    client, refresh = provider
    node, credential = make_node()
    node.node_data = {"credential_id": "isolated-credential"}
    fresh = {
        **credential.model_dump(),
        "access_token": "concurrent-access",
        "refresh_token": "concurrent-refresh",
        "token_version": 2,
    }
    store = type("Store", (), {})()
    store.lock_key = "isolated-salesforce-session"
    store.load = AsyncMock(return_value=fresh)
    store.persist = AsyncMock()
    monkeypatch.setattr(
        "nodes.core.oauth_refresh.CredentialsTableStore", lambda *a, **kw: store
    )
    monkeypatch.setattr("nodes.core.oauth_refresh.record_refresh_event", AsyncMock())
    client.request.side_effect = [revoked_response(), httpx.Response(200, json={})]

    result = await node._make_request("GET", "/limits", credential)

    assert result["status"] == "success"
    assert credential.access_token == "concurrent-access"
    assert credential.refresh_token == "concurrent-refresh"
    refresh.assert_not_awaited()
    store.persist.assert_not_awaited()
    assert client.request.await_args_list[1].kwargs["headers"]["Authorization"] == (
        "Bearer concurrent-access"
    )
