"""Offline HTTP-boundary coverage of every Weeztix operation and connect seam."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import weeztix_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.weeztix_oauth import OAUTH_PROVIDER

TOKEN = "weeztix-synthetic-token"
GUID = "6e26d618-354b-11eb-9322-acde48001122"
CASES = json.loads((Path(__file__).parent / "fixtures/weeztix/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="weeztix-test", node_type="automation-weeztix",
        node_data={"config": config, "credentials": {"credential_type": "weeztix_oauth", "access_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs == {"timeout": 30.0, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_weeztix_operation_request(monkeypatch, case):
    operation = case["config"]["operation"]
    if operation in {"resend_order_confirmation", "attach_shop_ticket", "detach_shop_ticket"}:
        response = httpx.Response(204)
    elif operation == "get_order_download_link":
        response = httpx.Response(200, text="https://api.weeztix.com/example.pdf", headers={"Content-Type": "text/plain; charset=utf-8"})
    else:
        payload = [{"guid": GUID, "name": "Festival", "deleted_at": None}] if operation.startswith("list_") or operation == "get_event_scanning_stats" else {"guid": GUID, "name": "Festival", "deleted_at": None}
        response = httpx.Response(200, json=payload)
    requests = transport(monkeypatch, response)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["http_status"] == response.status_code
    if response.status_code == 204:
        assert result["acknowledged"] is True
        assert "delivered" not in result
    elif operation == "get_order_download_link":
        assert result["download_link"] == response.text
    else:
        assert result["data"] == response.json()
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url) == "https://api.weeztix.com/3.0.0" + case["path"]
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert "company" not in request.headers
    assert (json.loads(request.content) if request.content else None) == case["body"]


@pytest.mark.asyncio
async def test_weeztix_company_and_collection_filter(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json=[]))
    result = await node({"operation": "list_events", "type": "upcoming", "company_id": GUID}).execute({})
    assert result["data"] == []
    assert requests[0].url.path.endswith("/event/upcoming")
    assert requests[0].headers["Company"] == GUID


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 406, 429, 500])
async def test_weeztix_errors_are_not_success_and_redact_secrets(monkeypatch, status):
    transport(monkeypatch, httpx.Response(status, json={"message": "Rejected " + TOKEN}))
    result = await node({"operation": "list_events"}).execute({})
    assert result["success"] is False
    assert result["http_status"] == status
    assert TOKEN not in str(result)
    assert "Rejected" in result["message"]


@pytest.mark.asyncio
async def test_weeztix_error_envelope_in_200(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"errors": {"auth": "Rejected"}}))
    assert (await node({"operation": "list_events"}).execute({}))["success"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>Sign in</html>"), httpx.Response(200, json={"unexpected": "envelope"})])
async def test_weeztix_malformed_collection_refuses_success(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError, match="Weeztix returned"):
        await node({"operation": "list_events"}).execute({})


@pytest.mark.asyncio
async def test_weeztix_unexpected_acknowledgement_refuses_success(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="acknowledgement"):
        await node({"operation": "attach_shop_ticket", "shop_id": GUID, "ticket_id": GUID}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_event", "event_id": "../order"},
    {"operation": "get_order", "order_id": "https://evil.example"},
    {"operation": "list_events", "company_id": "a\r\nHeader: injected"},
    {"operation": "list_events", "type": "all"},
    {"operation": "update_event", "event_id": GUID},
    {"operation": "update_ticket", "ticket_id": GUID, "min_orderable_amount_per_order": 20, "max_orderable_amount_per_order": 1},
    {"operation": "update_order_receiver", "order_id": GUID, "email": "invalid"},
])
def test_weeztix_rejects_invalid_input(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_weeztix_credential_default_and_declared_oauth():
    credential = native.WeeztixOAuthCredential(access_token=TOKEN)
    assert credential.credential_type == "weeztix_oauth"
    assert OAUTH_PROVIDER.authorize_url == "https://login.weeztix.com/login"
    assert OAUTH_PROVIDER.token_url == "https://auth.weeztix.com/tokens"
    assert OAUTH_PROVIDER.identity_url == "https://auth.weeztix.com/users/me"
    assert OAUTH_PROVIDER.rotates_refresh_tokens is True
    assert OAUTH_PROVIDER.pkce is False
    assert not native.WEEZTIX_SCOPES.declared_scopes()
    assert set(native.WEEZTIX_SCOPES) == {c["config"]["operation"] for c in CASES}
    assert native.WeeztixNode.connection_evidence.operation == "list_events"


@pytest.mark.asyncio
async def test_weeztix_refresh_uses_shared_choke_point(monkeypatch):
    from nodes.core import oauth_refresh
    from nodes.oauth.weeztix_oauth import refresh_access_token
    refreshed = {"credential_type": "weeztix_oauth", "access_token": "fresh-token", "refresh_token": "rotated-token"}
    helper = AsyncMock(return_value=refreshed)
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", helper)
    data = {"credential_type": "weeztix_oauth", "access_token": TOKEN, "refresh_token": "old-refresh-token"}
    result = await native.WeeztixNode.freshen_credential(data, user_id="user", credential_id="saved")
    assert result == refreshed
    helper.assert_awaited_once_with(data, pool=None, user_id="user", credential_id="saved", refresh=refresh_access_token, provider="weeztix")
