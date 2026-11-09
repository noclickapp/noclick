"""Wire-contract regressions with synthetic tenant credentials; no live API calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import manyrequests_node as native
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": native.TYPE, "portal_url": "https://agency.manyrequests.com", "api_token": "synthetic-manyrequests-token"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, auth=None):
    return NodeFactory.create_node(node_id="manyrequests-test", node_type="automation-manyrequests",
        node_data={"config": config, "credentials": AUTH if auth is None else auth})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    def respond(request):
        requests.append(request)
        status, body, headers = replies.pop(0)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers=headers)
        return httpx.Response(status, json=body, headers={"content-type": "application/vnd.api+json", **headers})

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, replies


CASES = json.loads((Path(__file__).parent / "fixtures/manyrequests/operations.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
@pytest.mark.asyncio
async def test_every_operation_has_exact_contract_method_path_and_body(transport, case):
    requests, replies = transport
    replies.append((case["status"], case["response"], {}))
    result = await node(case["config"]).execute({})
    assert result["success"] is True and result["http_status"] == case["status"]
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"]
    assert req.url.path == "/api/v1" + case["path"]
    assert req.url.host == "agency.manyrequests.com"
    assert req.headers["Authorization"] == "Bearer " + AUTH["api_token"]
    assert req.headers["Accept"] == "application/vnd.api+json"
    assert dict(req.url.params) == case["query"]
    assert (json.loads(req.content) if req.content else None) == case["body"]
    if "data" in case["response"]:
        assert result["data"] == case["response"]["data"]
    assert replies == []


@pytest.mark.asyncio
async def test_query_filters_serialize_exact_names_and_false_values(transport):
    transport[1].append((200, {"data": [], "links": {}, "meta": {}}, {}))
    await node({"operation": "list_services", "search": "Design + support", "is_for_sale": False}).execute({})
    assert dict(transport[0][0].url.params) == {"per_page": "25", "filter[search]": "Design + support", "filter[is_for_sale]": "false"}
    transport[1].append((200, {"data": [], "links": {}, "meta": {}}, {}))
    await node({"operation": "list_clients", "organization_id": "4"}).execute({})
    assert transport[0][-1].url.params["filter[organization_id]"] == "4"


@pytest.mark.asyncio
async def test_evidence_returns_recognizable_names_and_keeps_pagination(transport):
    payload = {"data": [{"id": "2", "type": "clients", "attributes": {"name": "Acme", "email": "a@example.test"}}],
               "links": {"next": "https://agency.manyrequests.com/api/v1/clients?page=2"}, "meta": {"total": 200}}
    transport[1].append((200, payload, {}))
    result = await node({"operation": "list_clients"}).execute({})
    assert result["items"][0]["name"] == "Acme" and result["page_only"] is True
    assert result["links"] == payload["links"] and result["meta"] == payload["meta"]
    assert len(transport[0]) == 1


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 422, 429, 500])
@pytest.mark.asyncio
async def test_error_or_redirect_never_succeeds_or_follows(transport, status):
    transport[1].append((status, {"message": "rejected " + AUTH["api_token"]}, {"location": "https://evil.example.test/"}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_clients"}).execute({})
    assert AUTH["api_token"] not in str(exc.value) and len(transport[0]) == 1
    if status >= 400:
        assert str(status) in str(exc.value) and "rejected" in str(exc.value)


@pytest.mark.parametrize("body", [{}, {"data": [], "errors": []}, {"error": "refused", "data": []}, {"data": {}}])
@pytest.mark.asyncio
async def test_bad_list_envelopes_refused(transport, body):
    transport[1].append((200, body, {}))
    with pytest.raises(ValueError):
        await node({"operation": "list_clients"}).execute({})


@pytest.mark.asyncio
async def test_empty_page_and_provider_echo_redaction(transport):
    transport[1].append((200, {"data": [], "links": {}, "meta": {}}, {}))
    assert (await node({"operation": "list_clients"}).execute({}))["items"] == []
    transport[1].append((200, {"data": {"id": "1", "type": "clients", "attributes": {"name": AUTH["api_token"]}}}, {}))
    assert AUTH["api_token"] not in json.dumps(await node({"operation": "get_client", "client_id": 1}).execute({}))


@pytest.mark.parametrize("host", ["http://agency.manyrequests.com", "https://user:pass@agency.manyrequests.com", "https://agency.manyrequests.com/x", "https://agency.manyrequests.com?x=1", "https://127.0.0.1", "https://[::1]", "https://agency.manyrequests.com:8080", "https://agency.manyrequests.com#x", "https://agency.manyrequests.com/../"])
def test_invalid_portal_refused_before_transport(host):
    with pytest.raises(ValueError):
        node({"operation": "list_clients"}, {**AUTH, "portal_url": host})


def test_manual_credentials_have_default_type_and_canonical_portal():
    credential = native.ManyRequestsAPITokenCredential(portal_url="custom.example.com", api_token=AUTH["api_token"])
    assert credential.credential_type == native.TYPE and credential.portal_url == "https://custom.example.com"


@pytest.mark.parametrize("token", ["https://example.com/token", "<token>", "Bearer token", "test\ntoken", ""])
def test_invalid_tokens_refused(token):
    with pytest.raises(ValidationError):
        native.ManyRequestsAPITokenCredential(portal_url=AUTH["portal_url"], api_token=token)


@pytest.mark.parametrize("key", ["../clients", "https://example.test", "a/b", "a%2Fb", "x?include=secret"])
def test_request_slug_does_not_change_route(key):
    with pytest.raises(ValueError):
        node({"operation": "get_request", "request_key": key})


def test_time_order_and_foreign_operation_fields_refused():
    with pytest.raises(ValueError):
        node({"operation": "create_time_entry", "request_id": 1, "user_id": 1, "started_at": "2026-01-01T12:00:00Z", "ended_at": "2026-01-01T11:00:00Z"})
    with pytest.raises(ValueError):
        node({"operation": "get_client", "client_id": 1, "url": "https://evil.example.test"})
    with pytest.raises(ValueError):
        node({"operation": "update_request_status", "status_id": 1})


@pytest.mark.parametrize("status", [200, 202, 204])
@pytest.mark.asyncio
async def test_create_request_does_not_claim_unexpected_status_completed(transport, status):
    transport[1].append((status, {"data": {"id": "1", "type": "requests"}}, {}))
    with pytest.raises(ValueError):
        await node({"operation": "create_request", "client_id": 1, "service_id": 2, "title": "Design"}).execute({})


@pytest.mark.asyncio
async def test_html_is_not_account_evidence(transport):
    transport[1].append((200, b"<html>Sign in</html>", {"content-type": "text/html"}))
    with pytest.raises(ValueError, match="JSON"):
        await node({"operation": "list_clients"}).execute({})
