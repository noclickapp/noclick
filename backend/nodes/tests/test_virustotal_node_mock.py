"""Real factory execution against a local HTTP transport; no provider account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import virustotal_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-virustotal-key-12345"
HASH = "a" * 64
CREDENTIAL = {"credential_type": "virustotal_api_key", "api_key": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="vt-test", node_type="automation-virustotal",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body=None, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body if body is not None else {"data": {"id": "fixture-id", "type": "user" if "/users/" in request.url.path else "analysis"}})
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_account"}, "GET", "/users/" + TOKEN),
    ({"operation": "get_file", "file_id": HASH}, "GET", "/files/" + HASH),
    ({"operation": "get_url", "url_id": HASH}, "GET", "/urls/" + HASH),
    ({"operation": "get_domain", "domain": "example.com"}, "GET", "/domains/example.com"),
    ({"operation": "get_ip", "ip": "2001:db8::1"}, "GET", "/ip_addresses/2001:db8::1"),
    ({"operation": "get_analysis", "analysis_id": "analysis-id"}, "GET", "/analyses/analysis-id"),
    ({"operation": "scan_url", "url": "https://example.com/a?x=1&y=2"}, "POST", "/urls"),
    ({"operation": "rescan_file", "file_id": HASH}, "POST", "/files/" + HASH + "/analyse"),
    ({"operation": "rescan_url", "url_id": HASH}, "POST", "/urls/" + HASH + "/analyse"),
    ({"operation": "get_file_behavior_summary", "file_id": HASH}, "GET", "/files/" + HASH + "/behaviour_summary"),
]
for kind, resource, key, value in [("file", "files", "file_id", HASH), ("url", "urls", "url_id", HASH),
        ("domain", "domains", "domain", "example.com"), ("ip", "ip_addresses", "ip", "8.8.8.8")]:
    for part in ("comments", "votes"):
        CASES.append(({"operation": f"list_{kind}_{part}", key: value, "limit": 20, "cursor": "a+/="},
            "GET", f"/{resource}/{value}/{part}"))


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES)
async def test_each_operation_uses_one_published_endpoint(monkeypatch, config, method, path):
    requests = transport(monkeypatch)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "www.virustotal.com"
    assert request.url.path == "/api/v3" + path
    assert request.headers["x-apikey"] == TOKEN and request.headers["x-tool"] == "NoClick"
    assert dict(request.url.params) == ({"limit": "20", "cursor": "a+/="} if "limit" in config else {})
    if config["operation"] == "scan_url":
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert request.content == b"url=https%3A%2F%2Fexample.com%2Fa%3Fx%3D1%26y%3D2"
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_account_identity_redacts_key_and_preserves_quotas(monkeypatch):
    transport(monkeypatch, {"data": {"id": "alice", "type": "user", "attributes": {
        "first_name": "Alice", "apikey": TOKEN, "quotas": {"daily": {"used": 1}}}},
        "links": {"self": native.BASE_URL + "/users/" + TOKEN}})
    result = await node({"operation": "get_account"}).execute({})
    assert result["name"] == "Alice" and result["id"] == "alice"
    assert result["data"]["attributes"]["quotas"]["daily"]["used"] == 1
    assert "apikey" not in result["data"]["attributes"] and TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_page_preserves_continuation_without_following_links(monkeypatch):
    page = {"data": [{"id": "comment-1", "attributes": {"text": "a comment"}}],
        "meta": {"cursor": "next-token"}, "links": {"next": "https://www.virustotal.com/api/v3/domains/example.com/comments?cursor=next-token"}}
    requests = transport(monkeypatch, page)
    result = await node({"operation": "list_domain_comments", "domain": "example.com"}).execute({})
    assert result == {"status": "success", **page}
    assert len(requests) == 1 and dict(requests[0].url.params) == {"limit": "10"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_rejections_are_verbatim_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"code": "QuotaExceededError", "message": "Daily quota exceeded"}}, status)
    result = await node({"operation": "get_file", "file_id": HASH}).execute({})
    assert result == {"status": "error", "error": "Daily quota exceeded", "http_status": status}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_cannot_claim_success(monkeypatch):
    transport(monkeypatch, {"error": {"message": "Rejected " + TOKEN}})
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and TOKEN not in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["..", "x/y", "x?y", "x#y", "x\\y", "x\ny"])
async def test_path_injection_refused_before_request(monkeypatch, identifier):
    requests = transport(monkeypatch)
    with pytest.raises(ValueError):
        await node({"operation": "get_file", "file_id": identifier}).execute({})
    assert requests == []


@pytest.mark.asyncio
async def test_transport_error_does_not_disclose_account_url(monkeypatch):
    def client(**kwargs):
        def fail(request):
            raise httpx.ConnectError(str(request.url), request=request)
        return httpx.AsyncClient(transport=httpx.MockTransport(fail), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_account"}).execute({})
    assert TOKEN not in str(exc.value)


def test_manual_credential_default_and_operation_shape():
    parsed = native.VirusTotalAPIKeyCredential.model_validate({"api_key": "  " + TOKEN + "  "})
    assert parsed.credential_type == "virustotal_api_key" and parsed.api_key == TOKEN
    with pytest.raises(ValidationError):
        native.VirusTotalConfig.model_validate({"config": {"operation": "scan_url", "url": "not a URL"}, "credentials": CREDENTIAL})
    with pytest.raises(ValidationError):
        native.VirusTotalConfig.model_validate({"config": {"operation": "get_file", "file_id": HASH, "method": "DELETE"}, "credentials": CREDENTIAL})


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture,config", [
    ("file-report", {"operation": "get_file", "file_id": HASH}),
    ("domain-report", {"operation": "get_domain", "domain": "example.com"}),
])
async def test_provider_documented_reports(monkeypatch, fixture, config):
    documented = json.loads((Path(__file__).parent / "fixtures" / "virustotal" / (fixture + ".json")).read_text())
    transport(monkeypatch, documented["body"])
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["data"] == documented["body"]["data"]


@pytest.mark.asyncio
async def test_wrong_account_shape_cannot_prove_connection(monkeypatch):
    transport(monkeypatch, {"data": {"id": "analysis", "type": "analysis"}})
    with pytest.raises(ValueError, match="user object"):
        await node({"operation": "get_account"}).execute({})
