"""Member API request, response, connection and OAuth boundary regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import wild_apricot_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory
from nodes.oauth.wild_apricot_oauth import OAUTH_PROVIDER


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "wild_apricot_oauth", "access_token": "synthetic-access-token",
        "refresh_token": "synthetic-refresh-token", "expires_at": "2099-01-01T00:00:00Z",
        "organization": "example.wildapricot.org", **updates}


def make_node(config):
    return NodeFactory.create_node(node_id="fixture", node_type="automation-wild-apricot",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = json.loads((Path(__file__).parent / "fixtures/wild-apricot/requests.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_native_factory_member_contract_requests(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await make_node(case["config"]).execute({})
    assert result == {"operation": case["config"]["operation"], "data": case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url.copy_with(query=None)) == native.BASE + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert request.headers["authorization"] == "Bearer synthetic-access-token"
    assert request.headers["accept"] == "application/json"
    if "body" in case:
        assert json.loads(request.content) == case["body"]
    else:
        assert not request.content
    assert "synthetic-access-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_account_picker_and_connection_share_authenticated_read(monkeypatch):
    requests = transport(monkeypatch, [{"Id": 42, "Name": "Neighborhood Club"}])
    options = await native.WildApricotNode.load_field_options("account_id", credential())
    assert options == [{"value": "42", "label": "Neighborhood Club"}]
    assert requests[0].url.path == "/publicview/v1/accounts"
    assert native.WildApricotNode.connection_evidence.field == "account_id"


@pytest.mark.asyncio
async def test_saved_account_picker_metadata_is_not_an_api_argument(monkeypatch):
    requests = transport(monkeypatch, {"Id": 42, "Name": "Neighborhood Club"})
    config = {"operation": "get_account", "account_id": 42,
        "account_id__label": "Neighborhood Club", "credentialIds": {"wild_apricot_oauth": "fixture"}}
    assert native.WildApricotNode.validate_config({"config": config, "credentials": credential()})["valid"]
    result = await make_node(config).execute({})
    assert result["data"]["Id"] == 42
    assert requests[0].url.path == "/publicview/v1/accounts/42"
    assert not requests[0].url.query and not requests[0].content
    assert config["account_id__label"] == "Neighborhood Club"


def test_other_config_extras_remain_rejected():
    with pytest.raises(ConfigValidationError):
        make_node({"operation": "get_account", "account_id": 42, "base_url": "https://example.com"})


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"error": "rejected"}, [{"Id": 42}], "not an account list"])
async def test_invalid_account_response_cannot_prove_connection(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="invalid account list"):
        await native.WildApricotNode.load_field_options("account_id", credential())


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_provider_failure_never_becomes_success_or_retries_write(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Provider refusal"}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await make_node({"operation": "cancel_registration", "account_id": 42, "registration_id": 9}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("host", ["example.com", "example.wildapricot.org.evil.test", "https://example.wildapricot.org",
    "example.wildapricot.org/path", "127.0.0.1", "user@example.wildapricot.org"])
def test_oauth_context_rejects_non_provider_hosts(host):
    with pytest.raises(ValidationError):
        native.WildApricotOAuthCredential.model_validate(credential(organization=host))


@pytest.mark.parametrize("value", [-1, 0, "../contacts/me", "https://example.com/"])
def test_path_ids_cannot_change_routes(value):
    with pytest.raises(ConfigValidationError):
        make_node({"operation": "get_event", "account_id": 42, "event_id": value})


def test_provider_declared_endpoints_scopes_and_basic_token_exchange(monkeypatch):
    monkeypatch.setenv("WILD_APRICOT_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("WILD_APRICOT_CLIENT_SECRET", "synthetic-secret")
    request = OAUTH_PROVIDER.token_request({"grant_type": "authorization_code", "code": "synthetic-code",
        "redirect_uri": "https://example.test/callback"}, context={"organization": "example.wildapricot.org"})
    assert request["url"] == "https://oauth.wildapricot.org/auth/token"
    assert request["data"]["scope"] == "auto"
    assert request["data"]["grant_type"] == "authorization_code"
    assert request["data"]["client_id"] == "synthetic-client"
    assert isinstance(request["auth"], httpx.BasicAuth)
    refresh = OAUTH_PROVIDER.token_request({"grant_type": "refresh_token", "refresh_token": "synthetic-refresh"},
        context={"organization": "example.wildapricot.org"})
    assert "client_id" not in refresh["data"]
    assert isinstance(refresh["auth"], httpx.BasicAuth)
    assert OAUTH_PROVIDER.identity_url == native.BASE + "/accounts"
    assert OAUTH_PROVIDER.name_field == "0.Name"
    assert OAUTH_PROVIDER.scopes == ["auto"]


@pytest.mark.asyncio
async def test_expired_token_uses_shared_refresh_before_member_request(monkeypatch):
    from nodes.core import oauth_refresh
    seen = []
    async def fresh(**kwargs):
        seen.append(kwargs)
        kwargs["credential"]["access_token"] = "fresh-synthetic-token"
        return "fresh-synthetic-token"
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", fresh)
    requests = transport(monkeypatch, [])
    await make_node({"operation": "list_accounts"}).execute({})
    assert requests[0].headers["authorization"] == "Bearer fresh-synthetic-token"
    assert seen[0]["provider"] == "wild_apricot"
    assert callable(seen[0]["refresh"])
