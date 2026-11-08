"""ZoomInfo operation wire contracts, error handling and OAuth lifecycle."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import zoominfo_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.zoominfo_oauth import OAUTH_PROVIDER

CASES = json.loads((Path(__file__).parent / "fixtures/zoominfo/cases.json").read_text())
CREDENTIAL = {"credential_type": "zoominfo_oauth", "access_token": "zoominfo-test-secret", "refresh_token": "zoominfo-test-refresh", "expires_at": "2099-01-01T00:00:00Z"}


def node(config):
    return NodeFactory.create_node(node_id="zoominfo-test", node_type="automation-zoominfo", node_data={"config": config, "credentials": CREDENTIAL.copy()})


def transport(monkeypatch, payload, status=200, mime=native.MEDIA):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=payload, headers={"content-type": mime}) if status != 204 else httpx.Response(204)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs) as result:
            yield result
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_zoominfo_operation_wire_contract(monkeypatch, operation):
    case = CASES[operation]
    calls = transport(monkeypatch, case["response"], case["status"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.host == "api.zoominfo.com" and request.url.path == "/gtm" + case["path"]
    assert request.headers["authorization"] == "Bearer " + CREDENTIAL["access_token"]
    assert request.headers["accept"] == native.MEDIA
    if case["request"] is None:
        assert not request.content
    else:
        assert request.headers["content-type"] == native.MEDIA
        assert json.loads(request.content) == case["request"]
    if operation.startswith("search_"):
        assert request.url.params["page[number]"] == "1" and request.url.params["page[size]"] == "25"
    if operation.startswith("lookup_"):
        assert dict(request.url.params) == {"filter[entity]": "contact", "filter[fieldType]": "output"}
    if case["response"] is not None:
        assert result["data"] == case["response"]["data"]


@pytest.mark.asyncio
async def test_zoominfo_pagination_and_sort_preserve_metadata(monkeypatch):
    payload = {"data": [], "links": {"last": "/data/v1/companies/search?page[number]=2"}, "meta": {"page": {"number": 2, "total": 2}}}
    calls = transport(monkeypatch, payload)
    result = await node({"operation": "search_companies", "filters": '{"companyName":"ZoomInfo"}', "page_number": 2, "page_size": 10, "sort": "-companyName"}).execute({})
    assert dict(calls[0].url.params) == {"page[number]": "2", "page[size]": "10", "sort": "-companyName"}
    assert result["meta"] == payload["meta"] and result["links"] == payload["links"]
    calls = transport(monkeypatch, {"data": []})
    await node({"operation": "list_audiences", "page_token": "opaque+cursor=", "page_size": 50}).execute({})
    assert dict(calls[0].url.params) == {"pageToken": "opaque+cursor=", "pageSize": "50"}


@pytest.mark.parametrize("config", [
    {"operation": "search_contacts", "filters": "[]"},
    {"operation": "search_contacts", "filters": "{}"},
    {"operation": "search_contacts", "filters": '{"personId":NaN}'},
    {"operation": "search_intent", "filters": '{"companyName":"ZoomInfo"}'},
    {"operation": "search_contacts", "filters": '{"companyName":"ZoomInfo"}', "page_size": 101},
    {"operation": "get_audience", "audience_id": "../other"},
    {"operation": "enrich_contacts", "record_ids": [0], "output_fields": ["email"]},
    {"operation": "enrich_contacts", "record_ids": list(range(1, 27)), "output_fields": ["email"]},
    {"operation": "enrich_contacts", "record_ids": [1], "output_fields": ["unsupported"]},
    {"operation": "upload_audience_members", "audience_id": "123", "upload_operation": "ADD", "fields": ["ziCompanyId"], "records": [["123", "extra"]]},
    {"operation": "create_audience", "name": "Sales", "audience_type": "unknown"},
])
def test_zoominfo_invalid_inputs_rejected(config):
    with pytest.raises(ValueError):
        native.ZoomInfoNode.parse_config({"config": config, "credentials": CREDENTIAL})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_zoominfo_failures_never_succeed_or_leak_secrets(monkeypatch, status):
    calls = transport(monkeypatch, {"errors": [{"detail": "Token rejected: " + CREDENTIAL["access_token"]}]}, status)
    result = await node({"operation": "get_usage"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert CREDENTIAL["access_token"] not in str(result) and len(calls) == 1
    if status in {401, 403}:
        assert "Token rejected:" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"errors": []}, {"data": "wrong"}, {"data": []}, {"data": [{"id": "user", "type": "UserUsage", "attributes": None}]}])
async def test_zoominfo_malformed_account_proof_is_not_success(monkeypatch, payload):
    transport(monkeypatch, payload)
    assert (await node({"operation": "get_usage"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_zoominfo_html_not_accepted(monkeypatch):
    transport(monkeypatch, {"data": []}, mime="text/html")
    assert (await node({"operation": "list_audiences"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_zoominfo_execute_adopts_rotated_credential(monkeypatch):
    from nodes.core import oauth_refresh
    async def refresh(**kwargs):
        assert kwargs["provider"] == "zoominfo" and kwargs["refresh"] == OAUTH_PROVIDER.refresh
        kwargs["credential"].update(access_token="rotated-access", refresh_token="rotated-refresh", expires_at="2099-02-01T00:00:00Z")
        return "rotated-access"
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", refresh)
    calls = transport(monkeypatch, {"data": []})
    n = node({"operation": "list_audiences"})
    await n.execute({})
    assert calls[0].headers["authorization"] == "Bearer rotated-access"
    assert n.config.credentials.refresh_token == "rotated-refresh"


@pytest.mark.asyncio
async def test_zoominfo_freshen_hook_uses_shared_choke_point(monkeypatch):
    from nodes.core import oauth_refresh
    freshen = AsyncMock(return_value=CREDENTIAL)
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", freshen)
    assert await native.ZoomInfoNode.freshen_credential(CREDENTIAL, user_id="user", credential_id="cred") == CREDENTIAL
    assert freshen.call_args.kwargs["refresh"] == OAUTH_PROVIDER.refresh
    assert freshen.call_args.kwargs["provider"] == "zoominfo"


@pytest.mark.asyncio
async def test_zoominfo_oauth_identity_and_declaration(monkeypatch):
    assert OAUTH_PROVIDER.pkce and OAUTH_PROVIDER.rotates_refresh_tokens
    assert OAUTH_PROVIDER.token_auth == "basic"
    assert OAUTH_PROVIDER.authorize_url == native.BASE + "/oauth/v1/authorize"
    assert OAUTH_PROVIDER.token_url == native.BASE + "/oauth/v1/token"
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=CASES["get_usage"]["response"])
    @asynccontextmanager
    async def client(*args, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:
            yield c
    monkeypatch.setattr(type(OAUTH_PROVIDER), "_client", client)
    assert await OAUTH_PROVIDER.account_name("access-test") == "user-1"
    assert calls[0].url == OAUTH_PROVIDER.identity_url
    assert calls[0].headers["authorization"] == "Bearer access-test"
    schema = native.ZoomInfoNode.get_config_schema()
    assert schema["$defs"]["ZoomInfoOAuthCredential"]["x-oauth-scopes"] == native.ZOOMINFO_SCOPES.declared_scopes()
    assert native.ZoomInfoNode.connection_evidence.operation == "get_usage"
