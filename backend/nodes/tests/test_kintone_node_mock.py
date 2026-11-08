"""Kintone wire-contract tests with synthetic credentials and HTTP responses."""
from copy import deepcopy
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import kintone_node as native
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "kintone_api_token", "api_token": "synthetic-kintone-token", "tenant_url": "https://example.cybozu.com", "app_id": 1}
RECORD = {"Text": {"value": "sample"}, "Date": {"value": None}}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(operation, config=None, auth=None):
    return NodeFactory.create_node(node_id="fixture", node_type="automation-kintone", node_data={"config": {"operation": operation, **(config or {})}, "credentials": AUTH if auth is None else auth})

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    def send(request):
        requests.append(request)
        return replies.pop(0)
    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: guarded(**kw, transport=httpx.MockTransport(send)))
    return requests, replies

CASES = [
    ("get_app", {}, "GET", "app", {"id": "1"}, {"appId": "1", "name": "Customer Database"}),
    ("get_fields", {}, "GET", "app/form/fields", {"app": "1", "lang": "default"}, {"properties": {}, "revision": "1"}),
    ("get_views", {}, "GET", "app/views", {"app": "1", "lang": "default"}, {"views": {}}),
    ("get_process", {}, "GET", "app/status", {"app": "1", "lang": "default"}, {"enable": False}),
    ("get_record", {"record_id": 2}, "GET", "record", {"app": "1", "id": "2"}, {"record": {}}),
    ("list_records", {"query": 'Text like "a+b & c" limit 10 offset 20', "total_count": True}, "GET", "records", {"app": "1", "query": 'Text like "a+b & c" limit 10 offset 20', "totalCount": "true"}, {"records": [], "totalCount": "0"}),
    ("create_record", {"record": RECORD}, "POST", "record", {"app": 1, "record": RECORD}, {"id": "2", "revision": "1"}),
    ("update_record", {"record_id": 2, "revision": 3, "record": RECORD}, "PUT", "record", {"app": 1, "id": 2, "revision": 3, "record": RECORD}, {"revision": "4"}),
    ("create_records", {"records": [RECORD]}, "POST", "records", {"app": 1, "records": [RECORD]}, {"ids": ["2"], "revisions": ["1"]}),
    ("update_records", {"records": [{"id": 2, "record": RECORD}]}, "PUT", "records", {"app": 1, "records": [{"id": 2, "record": RECORD}]}, {"records": [{"id": "2", "revision": "4"}]}),
    ("delete_records", {"ids": [2], "revisions": [3]}, "DELETE", "records", {"app": 1, "ids": [2], "revisions": [3]}, {}),
    ("get_comments", {"record_id": 2}, "GET", "record/comments", {"app": "1", "record": "2", "offset": "0", "limit": "10", "order": "DESC"}, {"comments": [], "newer": False, "older": False}),
    ("add_comment", {"record_id": 2, "text": "Hello", "mentions": [{"code": "sato", "type": "USER"}]}, "POST", "record/comment", {"app": 1, "record": 2, "comment": {"text": "Hello", "mentions": [{"code": "sato", "type": "USER"}]}}, {"id": "3"}),
    ("delete_comment", {"record_id": 2, "comment_id": 3}, "DELETE", "record/comment", {"app": 1, "record": 2, "comment": 3}, {}),
    ("create_cursor", {"query": 'Text like "sample"', "fields": ["Text"], "size": 500}, "POST", "records/cursor", {"app": 1, "query": 'Text like "sample"', "fields": ["Text"], "size": 500}, {"id": "cursor-123", "totalCount": "501"}),
    ("get_cursor", {"cursor_id": "cursor-123"}, "GET", "records/cursor", {"id": "cursor-123"}, {"records": [], "next": False}),
    ("delete_cursor", {"cursor_id": "cursor-123"}, "DELETE", "records/cursor", {"id": "cursor-123"}, {}),
    ("update_status", {"record_id": 2, "action": "Approve", "assignee": "sato"}, "PUT", "record/status", {"app": 1, "id": 2, "action": "Approve", "assignee": "sato"}, {"revision": "5"}),
    ("update_assignees", {"record_id": 2, "assignees": []}, "PUT", "record/assignees", {"app": 1, "id": 2, "assignees": []}, {"revision": "6"}),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,payload,body", CASES)
async def test_every_operation_exact_wire_request(transport, operation, config, method, path, payload, body):
    requests, replies = transport
    replies.append(httpx.Response(200, json=body))
    result = await node(operation, deepcopy(config)).execute({})
    assert result == {**body, "operation": operation, "status": "success"}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == f"/k/v1/{path}.json"
    assert request.url.host == "example.cybozu.com"
    assert request.headers["X-Cybozu-API-Token"] == AUTH["api_token"]
    assert AUTH["api_token"] not in str(request.url)
    assert (dict(request.url.params) if method == "GET" else json.loads(request.content)) == payload
    assert not replies

@pytest.mark.asyncio
async def test_explicit_app_and_cursor_continuation(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"record": {}}))
    await node("get_record", {"record_id": 2, "app_id": 42}).execute({})
    assert requests[0].url.params["app"] == "42"
    replies.append(httpx.Response(200, json={"records": [], "next": True}))
    assert (await node("get_cursor", {"cursor_id": "next-id"}).execute({}))["next"] is True

@pytest.mark.parametrize("host", ["http://example.cybozu.com", "https://example.cybozu.com.evil.test", "https://127.0.0.1", "https://user:pass@example.cybozu.com", "https://example.cybozu.com:443", "https://example.cybozu.com/k/v1", "https://example.cybozu.com?token=x"])
def test_bad_tenant_rejected(host):
    with pytest.raises(ValueError):
        node("get_app", auth={**AUTH, "tenant_url": host})

@pytest.mark.parametrize("family", [None, "", "other_api_token", [], {}])
def test_foreign_credential_refused(family):
    with pytest.raises(ValueError):
        node("get_app", auth={**AUTH, "credential_type": family})

@pytest.mark.parametrize("operation,config", [
    ("delete_records", {"ids": [1, 2], "revisions": [1]}),
    ("create_records", {"records": [{}] * 101}),
    ("get_record", {"record_id": 0}),
    ("get_comments", {"record_id": 1, "limit": 11}),
    ("create_cursor", {"size": 501}),
    ("get_app", {"arbitrary_path": "/evil"}),
])
def test_invalid_inputs_rejected(operation, config):
    with pytest.raises(ValueError):
        node(operation, config)

@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "https://evil.test"}), httpx.Response(200, text="login", headers={"Content-Type": "text/html"}), httpx.Response(200, json=[]), httpx.Response(200, json={"unexpected": True})])
async def test_redirect_html_and_invalid_shapes_fail(transport, response):
    transport[1].append(response)
    result = await node("get_app").execute({})
    assert result["status"] == "error" and len(transport[0]) == 1

@pytest.mark.asyncio
async def test_provider_rejection_redacts_token(transport):
    transport[1].append(httpx.Response(403, json={"code": "CB_NO02", "message": "No permission to access " + AUTH["api_token"]}))
    result = await node("get_app").execute({})
    assert result["http_status"] == 403 and "No permission" in result["error"]
    assert AUTH["api_token"] not in json.dumps(result)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,payload,body", CASES)
async def test_provider_documented_responses_through_factory(transport, operation, config, method, path, payload, body):
    from pathlib import Path
    examples = json.loads((Path(__file__).parent / "fixtures/kintone/responses.json").read_text())
    example = examples[f"{method} /k/v1/{path}.json"]
    transport[1].append(httpx.Response(200, json=example["body"]))
    result = await node(operation, config).execute({})
    assert result == {**example["body"], "operation": operation, "status": "success"}
