"""Offline transport regressions; provider examples are pinned in the fixtures."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import urlscanio_node as native
from nodes.core.registry import NodeFactory

TOKEN = "urlscanio-test-key"
SCAN = "68e26c59-2eae-437b-aeb1-cf750fafe7d7"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/urlscanio/documented_responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="urlscanio-test", node_type="automation-urlscanio",
        node_data={"config": config, "credentials": credential or {"credential_type": "urlscanio_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def handler(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_user"}, "GET", "/user/username", None),
    ({"operation": "submit_scan", "url": "https://urlscan.io", "visibility": "public", "tags": ["testing"]}, "POST", "/api/v1/scan", {"url": "https://urlscan.io", "visibility": "public", "tags": ["testing"]}),
    ({"operation": "search", "q": "page.domain:example.com"}, "GET", "/api/v1/search", None),
    ({"operation": "get_result", "scan_id": SCAN}, "GET", f"/api/v1/result/{SCAN}/", None),
    ({"operation": "update_visibility", "scan_id": SCAN, "visibility": "unlisted"}, "PUT", f"/api/v1/result/{SCAN}/visibility/", {"visibility": "unlisted"}),
    ({"operation": "reset_visibility", "scan_id": SCAN}, "DELETE", f"/api/v1/result/{SCAN}/visibility/", None),
    ({"operation": "get_countries"}, "GET", "/api/v1/availableCountries", None),
    ({"operation": "get_quotas"}, "GET", "/api/v1/quotas", None),
    ({"operation": "get_available_brands"}, "GET", "/api/v1/pro/availableBrands", None),
    ({"operation": "get_brand_summary"}, "GET", "/api/v1/pro/brands", None),
    ({"operation": "get_hostname_history", "hostname": "urlscan.io"}, "GET", "/api/v1/hostname/urlscan.io", None),
    ({"operation": "get_similar_results", "scan_id": SCAN}, "GET", f"/api/v1/pro/result/{SCAN}/similar/", None),
    ({"operation": "list_saved_searches"}, "GET", "/api/v1/user/searches/", None),
    ({"operation": "create_saved_search", "datasource": "scans", "name": "Testsearch", "query": "page.domain:urlscan.io"}, "POST", "/api/v1/user/searches/", {"search": {"datasource": "scans", "name": "Testsearch", "query": "page.domain:urlscan.io"}}),
    ({"operation": "update_saved_search", "search_id": "saved-1", "datasource": "scans", "name": "Testsearch", "query": "page.domain:urlscan.io"}, "PUT", "/api/v1/user/searches/saved-1/", {"search": {"datasource": "scans", "name": "Testsearch", "query": "page.domain:urlscan.io"}}),
    ({"operation": "delete_saved_search", "search_id": "saved-1"}, "DELETE", "/api/v1/user/searches/saved-1/", None),
    ({"operation": "list_subscriptions"}, "GET", "/api/v1/user/subscriptions/", None),
    ({"operation": "list_channels"}, "GET", "/api/v1/user/channels/", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES)
async def test_each_operation_is_one_contract_request(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, {"fixture": ["provider data"]})
    result = await node(config).execute({})
    assert result["data"] == {"fixture": ["provider data"]}
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.host, request.url.path) == (method, "urlscan.io", path)
    assert request.headers["api-key"] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example,extra", [
    ("submit_scan", "submitScan", {"url": "https://urlscan.io"}),
    ("search", "searchDatasource", {"q": "page.domain:example.com"}),
    ("get_countries", "getAvailableCountries", {}),
    ("get_quotas", "getQuotas", {}),
    ("get_similar_results", "getSimilarResults", {"scan_id": SCAN}),
])
async def test_documented_responses_are_preserved(monkeypatch, operation, example, extra):
    body = EXAMPLES[example]["body"]
    transport(monkeypatch, body)
    result = await node({"operation": operation, **extra}).execute({})
    assert result["data"] == body


@pytest.mark.asyncio
async def test_search_and_hostname_pagination_are_explicit(monkeypatch):
    requests = transport(monkeypatch, {"results": [], "has_more": True})
    await node({"operation": "search", "q": "page.domain:example.com", "search_after": "1234,scan-id", "size": 25, "collapse": "page.domain.keyword"}).execute({})
    assert dict(requests[0].url.params) == {"q": "page.domain:example.com", "search_after": "1234,scan-id", "size": "25", "datasource": "scans", "collapse": "page.domain.keyword"}
    requests = transport(monkeypatch, {"pageState": "opaque+token"})
    result = await node({"operation": "get_hostname_history", "hostname": "urlscan.io", "limit": 10, "pageState": "opaque+token"}).execute({})
    assert dict(requests[0].url.params) == {"limit": "10", "pageState": "opaque+token"}
    assert result["data"]["pageState"] == "opaque+token"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_saved_search_writable_fields_exact(monkeypatch):
    requests = transport(monkeypatch, {"search": {"name": "Testsearch"}})
    cfg = {"operation": "create_saved_search", "datasource": "scans", "name": "Testsearch", "query": "page.domain:urlscan.io", "longDescription": "Example", "permissions": ["team:read"], "tlp": "red", "usertags": ["private.test"]}
    await node(cfg).execute({})
    assert json.loads(requests[0].content) == {"search": {k: v for k, v in cfg.items() if k != "operation"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [302, 400, 401, 403, 404, 429, 500])
async def test_errors_and_redirects_do_not_retry_or_echo_secrets(monkeypatch, code):
    requests = transport(monkeypatch, lambda r: httpx.Response(code, text=TOKEN, headers={"Location": "https://other.example/"}))
    with pytest.raises(ValueError, match=f"HTTP {code}") as exc:
        await node({"operation": "submit_scan", "url": "https://urlscan.io"}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "denied"}, {"status": "error"}, "unexpected", None])
async def test_error_envelope_and_invalid_shape(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "get_user"}).execute({})


@pytest.mark.asyncio
async def test_invalid_json_and_transport_failure_are_sanitized(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, text="not json " + TOKEN))
    with pytest.raises(ValueError, match="JSON"):
        await node({"operation": "get_user"}).execute({})
    def fail(request):
        raise httpx.ConnectError(TOKEN, request=request)
    requests = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="did not complete") as exc:
        await node({"operation": "get_user"}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_secret_echo_redaction_and_account_evidence(monkeypatch):
    transport(monkeypatch, {"username": "example-user", "nested": [{"echo": TOKEN}]})
    result = await node({"operation": "get_user"}).execute({})
    assert result["data"]["username"] == "example-user" and TOKEN not in str(result)
    assert native.UrlscanioNode.connection_evidence.identity_operation == "get_user"


def test_credential_is_manual_and_defaulted():
    assert native.UrlscanioAPIKeyCredential(api_key=TOKEN).credential_type == "urlscanio_api_key"
    assert native.UrlscanioAPIKeyCredential(api_key="  " + TOKEN + "  ").api_key == TOKEN
    for key in ["https://urlscan.io/user/profile/", "<token>", "bad\nheader"]:
        with pytest.raises(ValidationError):
            native.UrlscanioAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("config", [
    {"operation": "get_result", "scan_id": "../bad"},
    {"operation": "submit_scan", "url": "file:///etc/passwd"},
    {"operation": "submit_scan", "url": "https://example.com", "tags": ["x" * 31]},
    {"operation": "search", "q": "*", "size": 10001},
    {"operation": "create_saved_search", "datasource": "scans", "name": "x", "query": "*", "createdAt": "2026-01-01"},
])
def test_invalid_input_is_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)
