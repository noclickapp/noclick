"""Requests checked against the pinned contract; body examples copied from it.

Other values are synthetic account data, not claimed live recordings.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError
from nodes import trackvia_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

DOC = json.loads((Path(__file__).parent / "fixtures/trackvia/documented.json").read_text())
AUTH = {"credential_type": "trackvia_api_token", "access_token": "synthetic-auth-token", "user_key": "synthetic-account-key"}
CASES = [
    ("list_users", {"start": 20, "max": 10}, "GET", "/users", {"start": "20", "max": "10"}),
    ("create_user", {"email": "person@example.com", "first_name": "Alex", "last_name": "Chen", "time_zone": "America/Denver"}, "POST", "/users", {}),
    ("list_apps", {"name": "Operations"}, "GET", "/apps", {"name": "Operations"}),
    ("list_views", {"name": "Open Orders"}, "GET", "/views", {"name": "Open Orders"}),
    ("list_records", {"view_id": 123, "start": 100, "max": 100}, "GET", "/views/123", {"start": "100", "max": "100"}),
    ("search_records", {"view_id": 123, "q": "Some Text"}, "GET", "/views/123/find", {"q": "Some Text", "start": "0", "max": "100"}),
    ("list_microservices", {}, "GET", "/integrations", {}),
    ("invoke_microservice_query", {"microservice_id": 12, "param": "abc"}, "GET", "/integrations/12/invoke", {"param": "abc"}),
    ("invoke_microservice", {"microservice_id": 12, "body": {"work": "value"}}, "POST", "/integrations/12/invoke", {}),
    ("create_record", {"view_id": 123, **DOC["create_record"]}, "POST", "/views/123/records", {}),
    ("get_record", {"view_id": 123, "record_id": 42}, "GET", "/views/123/records/42", {}),
    ("update_record", {"view_id": 123, "record_id": 42, **DOC["update_record"]}, "PUT", "/views/123/records/42", {}),
    ("delete_record", {"view_id": 123, "record_id": 42}, "DELETE", "/views/123/records/42", {}),
    ("delete_file", {"view_id": 123, "record_id": 42, "field_name": "Document"}, "DELETE", "/views/123/records/42/files/Document", {}),
    ("delete_attachments", {"view_id": 123, "record_id": 42, "field_name": "Documents", "attachment_ids": [10, 11]}, "DELETE", "/views/123/records/42/attachments/Documents", {"attachmentIds": ["10", "11"]}),
    ("delete_all_attachments", {"view_id": 123, "record_id": 42, "field_name": "Documents"}, "DELETE", "/views/123/records/42/attachments/Documents/all", {}),
]

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies

async def run(operation, args=None, credential=None):
    return await run_node_operation(node_type="automation-trackvia", operation=operation,
        arguments=args or {}, credential_data=credential or AUTH,
        user_id="00000000-0000-4000-8000-000000000001")

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query", CASES)
async def test_trackvia_contract_requests(transport, operation, config, method, path, query):
    requests, replies = transport
    body = [{"id": 1, "name": "Operations"}] if operation in {"list_apps", "list_views", "list_microservices"} else {"data": [], "totalCount": 0}
    code = 201 if operation in {"create_user", "create_record", "update_record"} else 204 if operation == "delete_record" else 200
    replies.append((code, None if code == 204 or operation in {"delete_file", "delete_attachments", "delete_all_attachments"} else body))
    result = await run(operation, config)
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/openapi" + path
    assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
    assert request.url.params["user_key"] == AUTH["user_key"]
    actual = dict(request.url.params)
    actual.pop("user_key")
    if operation == "delete_attachments":
        actual["attachmentIds"] = request.url.params.get_list("attachmentIds")
    assert actual == query
    if operation in {"create_record", "update_record"}:
        assert json.loads(request.content) == {"data": config["data"]}
    elif operation == "invoke_microservice":
        assert json.loads(request.content) == config["body"]
    elif operation == "create_user":
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert parse_qs(request.content.decode()) == {"email": ["person@example.com"], "firstName": ["Alex"], "lastName": ["Chen"], "timeZone": ["America/Denver"]}
    else:
        assert request.content == b""

@pytest.mark.asyncio
async def test_trackvia_evidence_and_tenant(transport):
    requests, replies = transport
    replies.append((200, [{"id": 5, "name": "Warehouse"}]))
    result = await run("list_apps", credential={**AUTH, "api_base_url": "https://acme.trackvia.com/", "account_id": "123"})
    assert result["data"] == [{"id": 5, "name": "Warehouse"}]
    assert requests[0].url.host == "acme.trackvia.com"
    assert requests[0].headers["account-id"] == "123"
    assert node.TrackViaNode.connection_evidence.operation == "list_apps"

@pytest.mark.asyncio
async def test_trackvia_provider_error_is_not_success(transport):
    requests, replies = transport
    replies.append((401, {"message": "Token has expired"}))
    assert await run("list_apps") == {"status": "error", "error": "Token has expired", "http_status": 401}
    replies.append((400, {"message": AUTH["user_key"] + " is invalid"}))
    result = await run("list_apps")
    assert AUTH["user_key"] not in result["error"]

@pytest.mark.parametrize("url", ["http://go.trackvia.com", "https://trackvia.com.evil.test", "https://go.trackvia.com@evil.test", "https://127.0.0.1", "https://go.trackvia.com/openapi", "https://go.trackvia.com:444"])
def test_trackvia_rejects_foreign_or_malformed_tenants(url):
    with pytest.raises(ValidationError):
        node.TrackViaTokenCredential.model_validate({**AUTH, "api_base_url": url})

def test_trackvia_credentials_can_be_pasted_without_type():
    raw = {k: v for k, v in AUTH.items() if k != "credential_type"}
    assert node.TrackViaTokenCredential.model_validate(raw).credential_type == "trackvia_api_token"
    assert not node.TrackViaTokenCredential.model_fields["credential_type"].is_required()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,json_field", [
    ("create_record", {"view_id": 123, **DOC["create_record"]}, "data"),
    ("invoke_microservice", {"microservice_id": 12, "body": {"work": "value"}}, "body"),
    ("delete_attachments", {"view_id": 123, "record_id": 42, "field_name": "Documents", "attachment_ids": [10, 11]}, "attachment_ids"),
])
async def test_trackvia_accepts_pasted_json(transport, operation, args, json_field):
    requests, replies = transport
    replies.extend([(200, {"data": []}), (200, {"data": []})])
    await run(operation, args)
    await run(operation, {**args, json_field: json.dumps(args[json_field])})
    assert requests[0].content == requests[1].content
    assert requests[0].url == requests[1].url

@pytest.mark.parametrize("value", [".", ".."])
def test_trackvia_field_name_cannot_change_route(value):
    with pytest.raises(ValidationError):
        node.TrackViaDeleteFileConfig(view_id=123, record_id=42, field_name=value)
