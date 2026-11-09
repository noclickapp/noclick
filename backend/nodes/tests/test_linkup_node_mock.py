"""Exercise native discovery, request serialization and HTTP failures offline."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import linkup_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/linkup/examples.json").read_text())
CREDENTIAL = {"credential_type": "linkup_api_key", "api_key": "synthetic-linkup-key"}
CONFIGS = {
    "get_credit_balance": {},
    "search": EXAMPLES["search"],
    "fetch": EXAMPLES["fetch"],
    "create_extract": EXAMPLES["extract"],
    "list_extract": {},
    "get_extract": {"id": "01234-abcd-56789"},
    "create_tasks": {"tasks": [{"type": "search", "input": EXAMPLES["search"]}, {"type": "fetch", "input": EXAMPLES["fetch"]}]},
    "list_tasks": {"type": ["fetch", "search"], "status": ["pending", "completed"]},
    "get_task": {"id": "01234-abcd-56789"},
    "create_response": {"input": "What is Microsoft's 2024 revenue?"},
    "create_research": {"q": "What is Microsoft's 2024 revenue?"},
    "list_research": {},
    "get_research": {"id": "01234-abcd-56789"},
    "rewind_search": {"q": "Donald Trump", "asOf": "2026-03-12"},
    "rewind_fetch": {"url": "https://example.com/a", "asOf": "2026-03-12"},
}


def node(operation, **changes):
    return NodeFactory.create_node(node_id="linkup-test", node_type="automation-linkup", node_data={
        "config": {"operation": operation, **CONFIGS[operation], **changes}, "credentials": CREDENTIAL,
    })


def transport(monkeypatch, *, code=200, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(code, json=EXAMPLES["balance"] if body is None else body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_every_operation_has_exactly_one_contract_request(monkeypatch, operation):
    requests = transport(monkeypatch)
    result = await node(operation).execute({})
    method, path = native.ROUTES[operation]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.linkup.so"
    assert request.url.path == path.replace("{id}", "01234-abcd-56789")
    assert request.headers["Authorization"] == "Bearer synthetic-linkup-key"
    assert result == {"status": "success", "data": EXAMPLES["balance"]}
    if method == "GET":
        assert not request.content
    else:
        body = json.loads(request.content)
        assert "operation" not in body
        if operation == "create_tasks":
            assert isinstance(body, list) and len(body) == 2
            assert body[0]["input"]["q"] == EXAMPLES["search"]["q"]
        if operation == "create_extract":
            assert body["schema"] == EXAMPLES["extract"]["schema"]
            assert "extraction_schema" not in body
        if operation == "fetch":
            assert body["includeRawContent"] is False
        if operation.startswith("rewind_"):
            assert body["asOf"] == "2026-03-12"


@pytest.mark.asyncio
async def test_task_filters_repeat_query_keys_and_paginate(monkeypatch):
    requests = transport(monkeypatch)
    await node("list_tasks", page=2, pageSize=25, sortBy="updatedAt", sortDirection="desc").execute({})
    params = requests[0].url.params
    assert params.get_list("type") == ["fetch", "search"]
    assert params.get_list("status") == ["pending", "completed"]
    assert params["page"] == "2" and params["pageSize"] == "25"
    assert params["sortDirection"] == "desc" and params["sortBy"] == "updatedAt"


@pytest.mark.asyncio
async def test_ids_are_encoded_as_one_path_segment(monkeypatch):
    requests = transport(monkeypatch)
    await node("get_task", id="task/a?x=1").execute({})
    assert requests[0].url.raw_path == b"/v1/tasks/task%2Fa%3Fx%3D1"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 429, 500, 302])
async def test_provider_http_errors_are_not_success(monkeypatch, code):
    requests = transport(monkeypatch, code=code, body={"message": "Request rejected"})
    with pytest.raises(httpx.HTTPStatusError):
        await node("get_credit_balance").execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_response_shapes_pass_through_including_pending_and_structured(monkeypatch):
    for body in [EXAMPLES["sourced_answer"], {"id": "task-1", "status": "pending", "output": None}, {"custom": [1, "text"]}, []]:
        transport(monkeypatch, body=body)
        assert (await node("search").execute({}))["data"] == body
    transport(monkeypatch, body="not a response object")
    with pytest.raises(ValueError, match="unexpected JSON"):
        await node("fetch").execute({})


def test_registry_and_credential_support_manual_connect():
    assert NODE_REGISTRY["automation-linkup"] is native.LinkupNode
    credential = native.LinkupAPIKeyCredential(api_key="synthetic-linkup-key")
    assert credential.credential_type == "linkup_api_key"
    assert set(native.LinkupAPIKeyCredential.model_json_schema()["required"]) == {"api_key"}
    evidence = native.LinkupNode.connection_evidence
    assert evidence.operation == "get_credit_balance" and evidence.proves == "reachability"


@pytest.mark.parametrize("operation, changes", [
    ("search", {"outputType": "structured", "structuredOutputSchema": None}),
    ("search", {"depth": "unknown"}),
    ("search", {"fromDate": "2026-04-01", "toDate": "2026-03-01"}),
    ("fetch", {"instructions": "Use USD", "schema": None}),
    ("list_tasks", {"pageSize": 101}),
    ("create_tasks", {"tasks": []}),
    ("create_tasks", {"tasks": [{"type": "fetch", "input": {}}]}),
    ("rewind_fetch", {"asOf": "2026-02-30"}),
])
def test_invalid_config_refused(operation, changes):
    with pytest.raises((ValueError, ValidationError)):
        node(operation, **changes)
