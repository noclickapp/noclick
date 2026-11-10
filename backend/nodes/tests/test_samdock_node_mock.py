"""Offline native execution with the provider's documented DTO examples."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import samdock_node as sd
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import shape_credential
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/samdock/documented.json").read_text())
AUTH = {"credential_type": "samdock_api_token", "api_token": "fixture-samdock-access-token"}


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "samdock.app"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_token"]
        assert AUTH["api_token"] not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, content=body) if isinstance(body, bytes) else httpx.Response(code, json=body)
    original = ssrf.guarded_async_client
    monkeypatch.setattr(sd, "guarded_async_client", lambda **kw: original(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-samdock", operation=operation,
        arguments=arguments or {}, credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(sd.ROUTES))
async def test_every_native_operation(transport, operation):
    requests, replies = transport
    action, resource = operation.split("_", 1)
    args = {"id": "record-123"} if action in {"get", "update", "delete"} else {}
    if action in {"create", "update"}:
        args.update(EXAMPLES["deal" if resource == "lead" else resource])
    if operation == "change_deal_stage":
        args = {"id": "record-123", "pipeline_id": "1", "stage_id": "23-1-2021"}
    if operation == "list_tasks":
        args.update(limit=50, offset=100)
    payload = [{"_id": "1", "name": "john Doe"}] if action == "list" else {"_id": "1"}
    replies.append((200, payload))
    result = await run(operation, args)
    assert result["status"] == "success" and result["data"] == payload
    assert len(requests) == 1 and not replies
    request = requests[0]
    method, route = sd.ROUTES[operation]
    assert request.method == method
    assert request.url.path == route.replace("{id}", "record-123")
    if action in {"create", "update", "change"}:
        body = json.loads(request.content)
        assert body == {sd.BODY_FIELDS.get(k, k): v for k, v in args.items() if k != "id"}
        assert "operation" not in body and "record_id" not in body
    if operation == "list_tasks":
        assert dict(request.url.params) == {"limit": "50", "offset": "100"}
    else:
        assert not request.url.query


@pytest.mark.asyncio
async def test_empty_write_acknowledgement_and_provider_rejection(transport):
    requests, replies = transport
    replies.extend([(200, b""), (401, {"message": "Token rejected"})])
    assert (await run("create_deal", {"name": "John"}))["data"] is None
    rejected = await run("list_organizations")
    assert rejected["status"] == "error" and rejected["http_status"] == 401
    assert rejected["error"] == "Token rejected"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_provider_error_redacts_token_and_writes_are_not_retried(transport):
    requests, replies = transport
    replies.append((500, {"message": "Rejected " + AUTH["api_token"]}))
    result = await run("create_deal", {"name": "John"})
    assert AUTH["api_token"] not in json.dumps(result)
    assert result["status"] == "error" and len(requests) == 1


@pytest.mark.asyncio
async def test_malformed_and_empty_read_do_not_prove_connection(transport):
    _, replies = transport
    replies.extend([(200, b"<html>Sign in</html>"), (200, b"")])
    with pytest.raises(ValueError, match="invalid JSON"):
        await run("list_organizations")
    with pytest.raises(ValueError, match="empty read"):
        await run("list_organizations")


@pytest.mark.parametrize("identifier", ["../deals", ".", "..", "https://example.org", "x?y", "x#z"])
def test_id_rejects_route_injection(identifier):
    with pytest.raises(ValueError):
        sd.SamdockNode.parse_config({"config": {"operation": "get_deal", "id": identifier}})


def test_manual_credential_default_and_required_dto_fields():
    shaped, errors, resolved = shape_credential("samdock_api_token", {"api_token": AUTH["api_token"]})
    assert not errors and shaped["api_token"] == AUTH["api_token"]
    assert resolved[1](api_token=AUTH["api_token"]).credential_type == "samdock_api_token"
    with pytest.raises(ValueError):
        sd.SamdockNode.parse_config({"config": {"operation": "create_person", "last_name": "Doe"}})
    assert sd.SamdockNode.connection_evidence.operation == "list_organizations"
