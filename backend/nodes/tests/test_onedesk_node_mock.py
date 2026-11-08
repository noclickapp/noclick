"""Exercise every OneDesk operation through native discovery and mocked HTTP."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import onedesk_node as od
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from utils import ssrf

AUTH = {"credential_type": "onedesk_api_key", "api_key": "fixture-onedesk-key"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/onedesk/operations.json").read_text())
CASES = FIXTURE["cases"]


def node(operation, arguments=None, credential=AUTH):
    return NodeFactory.create_node(node_id="onedesk-test", node_type="automation-onedesk",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": credential})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "app.onedesk.com"
        assert request.headers["OD-Public-API-Key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(od, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_onedesk_operation_request_and_result(case, transport):
    requests, replies = transport
    replies.append((200, case["response"]))
    result = await node(case["operation"], case["arguments"]).execute({})
    assert result["status"] == "success"
    assert result["code"] == "SUCCESS"
    if isinstance(case["response"], dict):
        assert result["data"] == case["response"]["data"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.raw_path.decode() == case["path"]
    assert (json.loads(request.content) if request.content else None) == case["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {}), (429, {}), (302, {}), (500, {}),
    (200, {"code": "ERROR_SECURITY_ACCESS"}), (200, "ERROR_CANNOT_FIND_ITEM"), (200, {"data": {}})])
async def test_onedesk_rejects_errors_without_retry(status, payload, transport):
    requests, replies = transport
    replies.append((status, payload))
    result = await node("get_organization").execute({})
    assert result["status"] == "error"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_onedesk_pagination_preserves_false_and_filters(transport):
    requests, replies = transport
    replies.append((200, {"code": "SUCCESS", "data": [{"name": "Task"}], "totalNum": 1}))
    result = await node("list_items", {"itemType": ["task"], "limit": 1, "offset": 10,
        "properties": [{"property": "isArchived", "operation": "EQ", "value": False}]}).execute({})
    assert result["next_offset"] == 11  # totalNum is not a reliable global count.
    assert json.loads(requests[0].content)["properties"][0]["value"] is False
    replies.append((200, {"code": "SUCCESS", "data": []}))
    result = await node("list_items", {"itemType": ["task"], "offset": 11}).execute({})
    assert result["next_offset"] is None


@pytest.mark.asyncio
async def test_onedesk_ignored_filter_is_not_a_success(transport):
    _, replies = transport
    replies.append((200, {"code": "SUCCESS", "data": [], "notAppliedPropertyFilters": ["name1:property name not found"]}))
    assert (await node("list_customers").execute({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"code": "SUCCESS"}, {"code": "SUCCESS", "data": {}}, {"code": "SUCCESS", "data": [1, 2]}])
async def test_onedesk_malformed_or_oversized_page(body, transport):
    _, replies = transport
    replies.append((200, body))
    with pytest.raises(ValueError):
        await node("list_users", {"limit": 1}).execute({})


@pytest.mark.asyncio
async def test_onedesk_redacts_echoed_key(transport):
    _, replies = transport
    replies.append((200, {"code": "SUCCESS", "data": {"name": AUTH["api_key"]}}))
    assert AUTH["api_key"] not in json.dumps(await node("get_organization").execute({}))


@pytest.mark.parametrize("operation,arguments", [
    ("get_item", {"external_id": "../users"}),
    ("get_message", {"external_id": "x?token=secret"}),
    ("update_customer", {"external_id": "616c7f21-0000-0000-0000-e1c087ebe9ea"}),
    ("list_items", {}), ("list_users", {"limit": 51}),
    ("create_timesheet", {"works": 2}), ("create_customer", {}),
])
def test_onedesk_invalid_config(operation, arguments):
    with pytest.raises(ValueError):
        node(operation, arguments)


def test_onedesk_discovery_and_connection_evidence():
    assert NODE_REGISTRY["automation-onedesk"] is od.OnedeskNode
    spec = od.OnedeskNode.connection_evidence
    assert spec.identity_operation == "get_organization"
    assert "organizationName" in spec.identity_keys
    assert node(spec.identity_operation).config.credentials.api_key == AUTH["api_key"]


@pytest.mark.parametrize("key", ["", "https://example.com/key", "paste_your_api_key_here", "a\nb"])
def test_onedesk_secret_validation(key):
    with pytest.raises((ValueError, ValidationError)):
        od.OnedeskAPIKeyCredential(api_key=key)
