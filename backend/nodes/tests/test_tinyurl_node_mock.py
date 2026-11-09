"""TinyURL request and response regressions; all credentials are synthetic."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import tinyurl_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-tinyurl-token"
CREDENTIAL = {"credential_type": "tinyurl_api_token", "api_token": TOKEN}
LINK = json.loads((Path(__file__).parent / "fixtures/tinyurl/link.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="test-tinyurl", node_type="automation-tinyurl",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body=LINK, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "create_link", "url": "https://example.com/a", "tags": ["tag1"]}, "POST", "/create", {"url": "https://example.com/a", "domain": "tinyurl.com", "tags": ["tag1"]}),
    ({"operation": "update_link", "alias": "example-alias", "new_tags": [], "new_stats": False, "new_expires_at": None}, "PATCH", "/update", {"domain": "tinyurl.com", "alias": "example-alias", "new_tags": [], "new_stats": False, "new_expires_at": None}),
    ({"operation": "change_destination", "alias": "example-alias", "url": "https://example.com/new"}, "PATCH", "/change", {"domain": "tinyurl.com", "alias": "example-alias", "url": "https://example.com/new"}),
    ({"operation": "get_link", "alias": "example-alias"}, "GET", "/alias/tinyurl.com/example-alias", {}),
    ({"operation": "delete_link", "alias": "example-alias"}, "DELETE", "/alias/tinyurl.com/example-alias", {}),
    ({"operation": "list_links", "type": "archived", "search": "tag:hello world"}, "GET", "/urls/archived", {"search": "tag:hello world"}),
    ({"operation": "count_links"}, "GET", "/urls/available/count", {}),
    ({"operation": "toggle_archive", "alias": "example-alias"}, "PATCH", "/archive", {"domain": "tinyurl.com", "alias": "example-alias"}),
    ({"operation": "set_analytics_status", "alias": "example-alias", "enabled": False}, "PATCH", "/analytics/status", {"domain": "tinyurl.com", "alias": "example-alias", "enabled": False}),
    ({"operation": "set_analytics_sharing", "alias": "example-alias", "public": False}, "PATCH", "/analytics/sharing", {"domain": "tinyurl.com", "alias": "example-alias", "public": False}),
]
for op, path in [(o, p) for o, (m, p) in native.ROUTES.items() if o.endswith("_analytics")]:
    extra = {"interval": "day"} if op == "timeline_analytics" else {}
    CASES.append(({"operation": op, "from_date": "2021-08-10T10:00:00-0800", "alias": "tinyurl.com/myalias", **extra}, "GET", path.replace("{region}", "world"), {"from": "2021-08-10T10:00:00-0800", "alias": "tinyurl.com/myalias", **extra}))


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,values", CASES)
async def test_each_operation_sends_exact_method_path_and_payload(monkeypatch, config, method, path, values):
    requests = transport(monkeypatch)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == LINK["data"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "api.tinyurl.com" and request.url.path == path
    assert request.headers["Authorization"] == "Bearer " + TOKEN and TOKEN not in str(request.url)
    if method == "GET":
        assert dict(request.url.params) == values
    elif method == "DELETE":
        assert request.content == b""
    else:
        assert json.loads(request.content) == values


@pytest.mark.asyncio
async def test_connection_read_preserves_empty_list_and_paging_metadata(monkeypatch):
    body = {"data": [], "code": 0, "errors": [], "meta": {"current_page": 1, "last_page": 1}}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_links"}).execute({})
    assert result["data"] == [] and result["meta"] == body["meta"]
    assert requests[0].url.path == "/urls/available"
    assert native.TinyURLNode.connection_evidence.operation == "list_links"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_http_failure_redacts_token_and_never_claims_success(monkeypatch, status):
    requests = transport(monkeypatch, {"errors": ["rejected " + TOKEN]}, status)
    result = await node({"operation": "list_links"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_and_malformed_success(monkeypatch):
    transport(monkeypatch, {"data": [], "code": 5, "errors": ["Invalid alias"]})
    assert (await node({"operation": "list_links"}).execute({}))["status"] == "error"
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match="envelope"):
        await node({"operation": "list_links"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_link", "alias": "../bad"},
    {"operation": "get_link", "alias": "ok", "domain": "https://tinyurl.com"},
    {"operation": "create_link", "url": "file:///tmp/secret"},
    {"operation": "create_link", "url": "https://example.com", "alias": "four"},
    {"operation": "list_links", "search": "unqualified"},
    {"operation": "timeline_analytics", "from_date": "2021-08-10", "interval": "year"},
    {"operation": "general_analytics"},
    {"operation": "set_analytics_status", "alias": "example-alias"},
])
def test_invalid_configs(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_default_and_secret_widget():
    credential = native.TinyURLAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == "tinyurl_api_token"
    schema = credential.model_json_schema()
    assert schema["properties"]["api_token"]["ui:widget"] == "password"
    assert "credential_type" not in schema["required"]
    for token in ["Bearer abcd", "https://example.com/token"]:
        with pytest.raises(ValueError):
            native.TinyURLAPITokenCredential(api_token=token)
