"""Bitly v4 contract tests for guided and advanced actions."""

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from nodes import bitly_node as module
from nodes.bitly_node import (
    BitlyNode, BitlyNodeConfig, BitlyTokenCredential, CreateBitlink,
    DeleteBitlink, ExpandLink, GetBitlink, GetCountries, GetEngagements,
    GetGroup, GetPlatformLimits, GetUser, ListBitlinks, ListGroups,
    ShortenLink, UpdateBitlink, GENERIC_CONFIGS,
)
from nodes.bitly_operations import OPERATIONS
from nodes.oauth import bitly_oauth
from nodes.core.oauth_provider import OAuthProviderSpec


def node(config):
    return BitlyNode(
        node_id="bitly-test", node_type="automation-bitly", node_data={},
        config=BitlyNodeConfig(config=config, credentials=BitlyTokenCredential(access_token="test-token")),
        sio=None, sid=None, workflow_id="test-workflow",
    )


@pytest.mark.parametrize("config,method,path,body", [
    (GetUser(), "GET", "/v4/user", None),
    (ListGroups(), "GET", "/v4/groups", None),
    (GetGroup(group_guid="G1"), "GET", "/v4/groups/G1", None),
    (ListBitlinks(group_guid="G1"), "GET", "/v4/groups/G1/bitlinks", None),
    (ShortenLink(long_url="https://example.com", group_guid="G1"), "POST", "/v4/shorten", {"long_url": "https://example.com", "group_guid": "G1", "domain": "bit.ly", "force_new_link": False}),
    (CreateBitlink(long_url="https://example.com", title="Example", tags_json='["qa"]'), "POST", "/v4/bitlinks", {"long_url": "https://example.com", "domain": "bit.ly", "title": "Example", "tags": ["qa"], "force_new_link": False}),
    (GetBitlink(bitlink="bit.ly/abc"), "GET", "/v4/bitlinks/bit.ly/abc", None),
    (UpdateBitlink(bitlink="bit.ly/abc", title="New"), "PATCH", "/v4/bitlinks/bit.ly/abc", {"title": "New"}),
    (DeleteBitlink(bitlink="bit.ly/abc"), "DELETE", "/v4/bitlinks/bit.ly/abc", None),
    (ExpandLink(bitlink_id="bit.ly/abc"), "POST", "/v4/expand", {"bitlink_id": "bit.ly/abc"}),
    (GetEngagements(bitlink="bit.ly/abc"), "GET", "/v4/bitlinks/bit.ly/abc/engagements", None),
    (GetCountries(bitlink="bit.ly/abc"), "GET", "/v4/bitlinks/bit.ly/abc/countries", None),
    (GetPlatformLimits(), "GET", "/v4/user/platform_limits", None),
])
@pytest.mark.asyncio
async def test_guided_actions_send_documented_requests(monkeypatch, config, method, path, body):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(204 if method == "DELETE" else 200,
                              json=None if method == "DELETE" else {"id": "bit.ly/abc"})
    client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler)))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["operation"] == config.operation
    assert result["timing_ms"]["api_request"] >= 0
    request, = requests
    assert request.method == method and request.url.path == path
    if "/bit.ly/abc" in path:
        assert b"bit.ly%2Fabc" in request.url.raw_path
    assert request.headers["Authorization"] == "Bearer test-token"
    if body is not None:
        assert json.loads(request.content) == body
    if isinstance(config, ListBitlinks):
        assert request.url.params["size"] == "50"
    if isinstance(config, GetEngagements):
        assert request.url.params["units"] == "30"


@pytest.mark.asyncio
async def test_advanced_action_path_query_and_body(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})
    client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler)))
    config = GENERIC_CONFIGS["api_update_bitlink"](
        bitlink="bit.ly/abc", query_json='{"foo":"bar"}', body_json='{"title":"Renamed"}')
    result = await node(config).execute({})
    assert result["data"] == {"ok": True}
    request, = requests
    assert request.method == "PATCH"
    assert request.url.path == "/v4/bitlinks/bit.ly/abc"
    assert b"bit.ly%2Fabc" in request.url.raw_path
    assert request.url.params["foo"] == "bar"
    assert json.loads(request.content) == {"title": "Renamed"}


def test_official_catalogue_is_exposed_in_schema():
    schema = BitlyNode.get_config_schema()
    text = json.dumps(schema)
    assert len(OPERATIONS) == 133
    assert all(f'"{name}"' in text for name in OPERATIONS)


@pytest.mark.asyncio
async def test_connection_options_and_api_error(monkeypatch):
    def handler(request):
        if request.url.path == "/v4/groups":
            return httpx.Response(200, json={"groups": [{"guid": "G1", "name": "NoClick"}]})
        return httpx.Response(403, json={"description": "Account plan does not allow this operation"})
    client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler)))
    options = await BitlyNode.load_field_options("group_guid", {"access_token": "test-token"})
    assert options == [{"value": "G1", "label": "NoClick"}]
    with pytest.raises(ValueError, match="Bitly API error 403: Account plan"):
        await node(GetUser()).execute({})


@pytest.mark.parametrize("config,error", [
    (UpdateBitlink(bitlink="bit.ly/abc"), "Provide a field to update"),
    (CreateBitlink(long_url="https://example.com", tags_json="{}"), "Tags JSON must be a JSON array"),
    (GENERIC_CONFIGS["api_update_bitlink"](bitlink="bit.ly/abc", body_json="invalid"), "Request Body JSON must be valid JSON"),
])
@pytest.mark.asyncio
async def test_local_input_validation(config, error):
    with pytest.raises(ValueError, match=error):
        await node(config).execute({})


@pytest.mark.asyncio
async def test_oauth_exchange_and_identity_use_documented_transport(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/oauth/access_token":
            return httpx.Response(200, json={"access_token": "new-token", "login": "noclick"})
        return httpx.Response(200, json={"login": "noclick", "default_group_guid": "G1"})

    client = httpx.AsyncClient
    monkeypatch.setattr(OAuthProviderSpec, "_client", lambda self, url: client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("BITLY_CLIENT_ID", "client-id")
    monkeypatch.setenv("BITLY_CLIENT_SECRET", "client-secret")

    tokens, name = await bitly_oauth.OAUTH_PROVIDER.exchange("auth-code", "https://noclick.com/callback")

    assert tokens.access_token == "new-token" and name == "noclick"
    assert tokens.refresh_token is None and tokens.expires_at is None
    assert requests[0].url.path == "/oauth/access_token"
    assert requests[0].headers["accept"] == "application/json"
    assert parse_qs(requests[0].content.decode()) == {
        "client_id": ["client-id"], "client_secret": ["client-secret"],
        "code": ["auth-code"], "redirect_uri": ["https://noclick.com/callback"],
        "grant_type": ["authorization_code"]}
    assert requests[1].url.path == "/v4/user"
    assert requests[1].headers["authorization"] == "Bearer new-token"


@pytest.fixture
def engagement():
    # Copied from https://dev.bitly.com/docs/tutorials/create-a-webhook/
    return json.loads((Path(__file__).parent / "fixtures/bitly/engagement.json").read_text())


@pytest.mark.asyncio
async def test_engagement_registration_teardown_and_scope(monkeypatch, engagement):
    calls = []
    async def request(token, method, path, **kwargs):
        calls.append((token, method, path, kwargs))
        return {"guid": engagement["webhook_guid"]}, 0
    monkeypatch.setattr(BitlyNode, "_request", request)
    config = {"operation": "on_engagement", "organization_guid": engagement["organization_guid"],
              "group_guid": engagement["group_guid"]}
    registration = await BitlyNode._register_external_webhook(
        webhook_url="https://noclick.com/webhook", credential={"access_token": "token"},
        config=config, node_id="test")
    assert calls[0][1:3] == ("POST", "/webhooks")
    assert calls[0][3]["body"] == {
        "organization_guid": engagement["organization_guid"], "group_guid": engagement["group_guid"],
        "name": "NoClick test", "event": "decodes", "url": "https://noclick.com/webhook", "is_active": True}
    assert registration == {"external_webhook_id": engagement["webhook_guid"]}
    await BitlyNode._unregister_external_webhook(
        credential={"access_token": "token"}, config=registration, node_id="test")
    assert calls[1][1:3] == ("DELETE", "/webhooks/" + engagement["webhook_guid"])
    assert BitlyNode.verify_webhook_signature(b"{}", {}, config)
    assert BitlyNode.resolve_trigger_payload(engagement, config)["data"] == engagement
    for change in ({"event_type": "ping"}, {"organization_guid": "other"}, {"group_guid": "other"}):
        assert BitlyNode.resolve_trigger_payload({**engagement, **change}, config) == {}
    result = await node(module.BitlyOnEngagementConfig(**config)).execute(engagement)
    assert BitlyNode.should_propagate_output(result, config)
    text = BitlyNode.resolve_agent_event(result)["text"]
    assert all(engagement[key] in text for key in ("event_id", "bitlink", "url", "group_guid", "country"))
    empty = await node(module.BitlyOnEngagementConfig(**config)).execute({})
    assert not BitlyNode.should_propagate_output(empty, config)


@pytest.mark.asyncio
async def test_list_bitlinks_uses_documented_cursor_and_query(monkeypatch):
    captured = []
    async def request(token, method, path, **kwargs):
        captured.append(kwargs)
        return {"links": []}, 0
    monkeypatch.setattr(BitlyNode, "_request", staticmethod(request))
    await node(ListBitlinks(group_guid="G1", search_after="cursor", query="docs")).execute({})
    assert captured[0]["params"] == {"size": 50, "search_after": "cursor", "query": "docs"}
