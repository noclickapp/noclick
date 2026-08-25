"""Bearer tokens never follow provider-returned URLs outside provider origins."""

from unittest.mock import AsyncMock, Mock

import pytest

from nodes.oauth.pipedrive_oauth import (
    PipedriveTokens,
    exchange_code_for_tokens as exchange_pipedrive_code,
    refresh_access_token as refresh_pipedrive_token,
)
from nodes.oauth.salesforce_oauth import (
    SalesforceTokens,
    exchange_code_for_tokens as exchange_salesforce_code,
    refresh_access_token as refresh_salesforce_token,
)
from nodes.pipedrive_node import (
    PipedriveNode,
    PipedriveNodeConfig,
    PipedriveOAuthCredential,
)
from nodes.salesforce_node import (
    SalesforceNode,
    SalesforceNodeConfig,
    SalesforceGetBulkJobResultsConfig,
    SalesforceOAuthCredential,
    SalesforceQueryConfig,
)
from utils.ssrf import SSRFError


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


class _Client:
    def __init__(self, post_payload, get_payload=None):
        self.post = AsyncMock(return_value=_Response(post_payload))
        self.get = AsyncMock(return_value=_Response(get_payload or {}))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _salesforce_token_payload(**overrides):
    payload = {
        "access_token": "salesforce-access",
        "refresh_token": "salesforce-refresh",
        "instance_url": "https://team.my.salesforce.com",
        "issued_at": "1779710400000",
    }
    payload.update(overrides)
    return payload


def _pipedrive_token_payload(**overrides):
    payload = {
        "access_token": "pipedrive-access",
        "refresh_token": "pipedrive-refresh",
        "api_domain": "https://acme.pipedrive.com",
        "expires_in": 3600,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def salesforce_env(monkeypatch):
    monkeypatch.setenv("SALESFORCE_CLIENT_ID", "client-id")
    monkeypatch.setenv("SALESFORCE_CLIENT_SECRET", "client-secret")


@pytest.fixture
def pipedrive_env(monkeypatch):
    monkeypatch.setenv("PIPEDRIVE_CLIENT_ID", "client-id")
    monkeypatch.setenv("PIPEDRIVE_CLIENT_SECRET", "client-secret")


@pytest.mark.asyncio
async def test_salesforce_rejects_provider_instance_suffix_escape(
    monkeypatch, salesforce_env
):
    client = _Client(
        _salesforce_token_payload(instance_url="https://team.salesforce.com.evil.example")
    )
    monkeypatch.setattr(
        "nodes.oauth.salesforce_oauth.httpx.AsyncClient", lambda **_kwargs: client
    )

    with pytest.raises(ValueError, match="Salesforce instance URL"):
        await exchange_salesforce_code("code", "https://app.example/callback")
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_salesforce_identity_bearer_stays_on_login_origin(
    monkeypatch, salesforce_env
):
    client = _Client(
        _salesforce_token_payload(
            id="https://login.salesforce.com.evil.example/id/org/user"
        )
    )
    monkeypatch.setattr(
        "nodes.oauth.salesforce_oauth.httpx.AsyncClient", lambda **_kwargs: client
    )

    with pytest.raises(SSRFError, match="outside"):
        await exchange_salesforce_code("code", "https://app.example/callback")
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_salesforce_exchange_canonicalizes_provider_origins(
    monkeypatch, salesforce_env
):
    client = _Client(
        _salesforce_token_payload(
            instance_url="TEAM.My.Salesforce.Com/",
            id="https://login.salesforce.com/id/org/user",
        ),
        {"user_id": "user", "organization_id": "org"},
    )
    monkeypatch.setattr(
        "nodes.oauth.salesforce_oauth.httpx.AsyncClient", lambda **_kwargs: client
    )

    tokens, user = await exchange_salesforce_code(
        "code", "https://app.example/callback"
    )

    assert tokens.instance_url == "https://team.my.salesforce.com"
    assert user.user_id == "user"
    assert client.get.await_args.args[0] == "https://login.salesforce.com/id/org/user"


@pytest.mark.asyncio
async def test_salesforce_refresh_revalidates_rotated_instance(
    monkeypatch, salesforce_env
):
    client = _Client(
        _salesforce_token_payload(instance_url="https://127.0.0.1.example")
    )
    monkeypatch.setattr(
        "nodes.oauth.salesforce_oauth.httpx.AsyncClient", lambda **_kwargs: client
    )

    with pytest.raises(ValueError, match="Salesforce instance URL"):
        await refresh_salesforce_token(
            "refresh", "https://old.my.salesforce.com"
        )


@pytest.mark.parametrize(
    "model",
    [
        lambda: SalesforceTokens(
            access_token="a",
            instance_url="https://attacker.example",
            expires_at="2026-01-01T00:00:00+00:00",
        ),
        lambda: SalesforceOAuthCredential(
            access_token="a",
            refresh_token="r",
            instance_url="https://attacker.example",
            expires_at="2026-01-01T00:00:00+00:00",
        ),
    ],
)
def test_salesforce_models_reject_untrusted_runtime_origin(model):
    with pytest.raises(ValueError, match="Salesforce instance URL"):
        model()


@pytest.mark.asyncio
async def test_pipedrive_rejects_api_domain_before_userinfo_bearer(
    monkeypatch, pipedrive_env
):
    client = _Client(
        _pipedrive_token_payload(api_domain="https://acme.pipedrive.com@evil.example")
    )
    monkeypatch.setattr(
        "nodes.oauth.pipedrive_oauth.httpx.AsyncClient", lambda **_kwargs: client
    )

    with pytest.raises(ValueError, match="Pipedrive API domain"):
        await exchange_pipedrive_code("code", "https://app.example/callback")
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipedrive_exchange_uses_canonical_provider_origin(
    monkeypatch, pipedrive_env
):
    client = _Client(
        _pipedrive_token_payload(api_domain="ACME.Pipedrive.Com/"),
        {"data": {"id": 7, "name": "Ada"}},
    )
    monkeypatch.setattr(
        "nodes.oauth.pipedrive_oauth.httpx.AsyncClient", lambda **_kwargs: client
    )

    tokens, user = await exchange_pipedrive_code(
        "code", "https://app.example/callback"
    )

    assert tokens.api_domain == "https://acme.pipedrive.com"
    assert user.api_domain == "https://acme.pipedrive.com"
    assert client.get.await_args.args[0] == "https://acme.pipedrive.com/api/v1/users/me"


@pytest.mark.asyncio
async def test_pipedrive_refresh_revalidates_rotated_api_domain(
    monkeypatch, pipedrive_env
):
    client = _Client(
        _pipedrive_token_payload(api_domain="https://acme.pipedrive.com/path")
    )
    monkeypatch.setattr(
        "nodes.oauth.pipedrive_oauth.httpx.AsyncClient", lambda **_kwargs: client
    )

    with pytest.raises(ValueError, match="Pipedrive API domain"):
        await refresh_pipedrive_token("refresh")


@pytest.mark.parametrize(
    "model",
    [
        lambda: PipedriveTokens(
            access_token="a", api_domain="https://attacker.example"
        ),
        lambda: PipedriveOAuthCredential(
            access_token="a", api_domain="https://attacker.example"
        ),
    ],
)
def test_pipedrive_models_reject_untrusted_runtime_origin(model):
    with pytest.raises(ValueError, match="Pipedrive API domain"):
        model()


@pytest.mark.asyncio
async def test_salesforce_rotated_instance_reaches_next_request(monkeypatch):
    credential = SalesforceOAuthCredential(
        access_token="old-access",
        refresh_token="refresh",
        instance_url="https://old.my.salesforce.com",
        expires_at="2020-01-01T00:00:00+00:00",
    )
    node = SalesforceNode(
        node_id="salesforce",
        node_type="automation-salesforce",
        node_data={},
        config=SalesforceNodeConfig(
            config=SalesforceQueryConfig(query="SELECT Id FROM Account"),
            credentials=credential,
        ),
        user_id="user",
    )

    async def fake_ensure(**kwargs):
        kwargs["credential"].update(
            access_token="new-access",
            instance_url="https://rotated.my.salesforce.com",
        )
        return "new-access"

    response = _Response({"records": []})
    request = AsyncMock(return_value=response)
    client = Mock(request=request)
    context = _ClientContext(client)
    monkeypatch.setattr(
        "nodes.core.oauth_refresh.ensure_fresh_oauth_token", fake_ensure
    )
    monkeypatch.setattr(
        "nodes.salesforce_node.guarded_async_client", lambda **_kwargs: context
    )

    result = await node.execute({})

    assert result["status"] == "success"
    assert credential.instance_url == "https://rotated.my.salesforce.com"
    assert request.await_args.kwargs["url"].startswith(
        "https://rotated.my.salesforce.com/services/data/"
    )


@pytest.mark.asyncio
async def test_salesforce_rotated_instance_reaches_direct_bulk_csv_request(monkeypatch):
    credential = SalesforceOAuthCredential(
        access_token="old-access",
        refresh_token="refresh",
        instance_url="https://old.my.salesforce.com",
        expires_at="2020-01-01T00:00:00+00:00",
    )
    node = SalesforceNode(
        node_id="salesforce",
        node_type="automation-salesforce",
        node_data={},
        config=SalesforceNodeConfig(
            config=SalesforceGetBulkJobResultsConfig(
                job_id="job-1",
                result_type="failed",
            ),
            credentials=credential,
        ),
        user_id="user",
    )

    async def fake_ensure(**kwargs):
        kwargs["credential"].update(
            access_token="new-access",
            instance_url="https://rotated.my.salesforce.com",
        )
        return "new-access"

    response = _Response({})
    response.text = "Id,Error\n001,bad"
    get = AsyncMock(return_value=response)
    client = Mock(get=get)
    monkeypatch.setattr(
        "nodes.core.oauth_refresh.ensure_fresh_oauth_token",
        fake_ensure,
    )
    monkeypatch.setattr(
        "nodes.salesforce_node.guarded_async_client",
        lambda **_kwargs: _ClientContext(client),
    )

    result = await node.execute({})

    assert result["status"] == "success"
    assert result["data"] == {
        "csv_data": "Id,Error\n001,bad",
        "result_type": "failed",
    }
    assert get.await_args.args[0].startswith(
        "https://rotated.my.salesforce.com/services/data/"
    )
    assert get.await_args.kwargs["headers"]["Authorization"] == "Bearer new-access"


@pytest.mark.asyncio
async def test_pipedrive_rotated_api_domain_reaches_next_request(monkeypatch):
    credential = PipedriveOAuthCredential(
        access_token="old-access",
        refresh_token="refresh",
        expires_at="2020-01-01T00:00:00+00:00",
        api_domain="https://old.pipedrive.com",
    )
    node = PipedriveNode(
        node_id="pipedrive",
        node_type="automation-pipedrive",
        node_data={},
        config=PipedriveNodeConfig(
            config={"operation": "get_deal", "deal_id": "7"},
            credentials=credential,
        ),
        user_id="user",
    )

    async def fake_ensure(**kwargs):
        kwargs["credential"].update(
            access_token="new-access",
            api_domain="https://rotated.pipedrive.com",
        )
        return "new-access"

    request = AsyncMock(
        return_value={"status": "success", "action": "get_deal", "data": {}}
    )
    monkeypatch.setattr(
        "nodes.core.oauth_refresh.ensure_fresh_oauth_token", fake_ensure
    )
    monkeypatch.setattr("nodes.pipedrive_node._pipedrive_request", request)

    result = await node.execute({})

    assert result["status"] == "success"
    assert credential.api_domain == "https://rotated.pipedrive.com"
    assert request.await_args.args[:2] == (
        "https://rotated.pipedrive.com",
        "new-access",
    )


class _ClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, exc_type, exc, tb):
        return False
