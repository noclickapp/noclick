"""Contract routes through the real factory; failures must never claim success."""
import json
from pathlib import Path

import httpx
import pytest
from nodes import gotowebinar_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.gotowebinar_oauth import OAUTH_PROVIDER

CREDS = {"credential_type": "gotowebinar_oauth", "access_token": "synthetic-access-token", "refresh_token": "synthetic-refresh-token"}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/gotowebinar/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="webinar-test", node_type="automation-gotowebinar",
        node_data={"config": config, "credentials": credentials or CREDS})


def transport(monkeypatch, handler):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.getgo.com"
        assert request.headers["Authorization"] == "Bearer " + CREDS["access_token"]
        return handler(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("name", FIXTURES)
async def test_gotowebinar_contract_request(monkeypatch, name):
    fixture = FIXTURES[name]
    def reply(request):
        assert request.method == fixture["method"]
        assert request.url.path == fixture["path"]
        assert dict(request.url.params) == fixture["query"]
        if "body" in fixture["config"]:
            assert json.loads(request.content) == fixture["config"]["body"]
            assert request.headers["Content-Type"] == "application/json"
        else:
            assert request.content == b""
        assert request.headers["Accept"] == ("application/vnd.citrix.g2wapi-v1.1+json" if name == "register_participant" else "application/json")
        return httpx.Response(fixture["status"], json=fixture["response"]) if fixture["response"] is not None else httpx.Response(fixture["status"])
    requests = transport(monkeypatch, reply)
    result = await node(fixture["config"]).execute({})
    assert len(requests) == 1
    assert result["data"] == fixture["response"]
    assert result["status"] == "success"
    if fixture["method"] != "GET":
        assert result["accepted"] is True and result["completion_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 409, 429, 500])
async def test_gotowebinar_rejection_is_not_success(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={"error": "rejected"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node(FIXTURES["register_participant"]["config"]).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "unexpected"}, None, "wrong"])
async def test_gotowebinar_bad_list(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node(FIXTURES["list_webinars"]["config"]).execute({})


@pytest.mark.asyncio
async def test_gotowebinar_identity_picker(monkeypatch):
    async def fresh(data, **kwargs):
        return data
    monkeypatch.setattr(native.GoToWebinarNode, "freshen_credential", fresh)
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"id": "123456789", "displayName": "Webinar Organizer"}))
    result = await native.GoToWebinarNode.load_field_options("organizer_key", CREDS)
    assert requests[0].url.path == "/identity/v1/Users/me"
    assert result == {"options": [{"value": "123456789", "label": "Webinar Organizer"}], "next_page_token": None}


@pytest.mark.parametrize("name,field,value", [("get_webinar", "webinar_key", "../123"), ("list_historical_webinars", "toTime", "2014-01-01T00:00:00Z"), ("cancel_webinar", "sendCancellationEmails", "true")])
def test_gotowebinar_invalid_configs(name, field, value):
    config = {**FIXTURES[name]["config"], field: value}
    result = native.GoToWebinarNode.validate_config({"config": config, "credentials": CREDS})
    assert result["valid"] is False


def test_gotowebinar_oauth_and_manual_shape():
    shaped = native.GoToWebinarOAuthCredential(access_token=CREDS["access_token"], refresh_token=CREDS["refresh_token"])
    assert shaped.credential_type == "gotowebinar_oauth"
    assert OAUTH_PROVIDER.identity_url == native.IDENTITY
    assert OAUTH_PROVIDER.token_auth == "basic"
    assert OAUTH_PROVIDER.scope_registry is native.GOTOWEBINAR_SCOPES
    assert set(native.GOTOWEBINAR_SCOPES) == set(FIXTURES)
