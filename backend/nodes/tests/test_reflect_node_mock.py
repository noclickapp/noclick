"""Synthetic wire examples exercise all seven operations in Reflect's contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import reflect_node as native
from nodes.core.registry import NodeFactory

TOKEN = "reflect-synthetic-token-42"
CASES = json.loads((Path(__file__).parent / "fixtures/reflect/wire.json").read_text())


def node(config, **extra):
    return NodeFactory.create_node(node_id="reflect-fixture", node_type="automation-reflect", node_data={
        "config": config, "credentials": {"credential_type": "reflect_access_token", "access_token": TOKEN}, **extra,
    })


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Location": "https://example.test/"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_all_operations_wire_and_response(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, case["response"])
    output = await node({"operation": operation, **case["config"]}).execute({})
    request, = requests
    assert request.method == case["method"]
    assert str(request.url) == "https://reflect.app/api" + case["path"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert not request.url.query
    if case["method"] == "GET":
        assert not request.content
    else:
        assert json.loads(request.content) == case["body"]
    assert output == {"status": "success", "data": case["response"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 429, 500])
async def test_provider_rejection_and_no_redirect_or_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "rejected " + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_graphs"}).execute({})
    assert f"HTTP {status}" in str(error.value)
    assert TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("list_graphs", {}), ("create_note", []), ("create_note", {"error": "rejected"}), ("append_daily_note", {"success": False})])
async def test_invalid_envelopes_are_not_success(monkeypatch, operation, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": operation, **CASES[operation]["config"]}).execute({})


@pytest.mark.asyncio
async def test_empty_list_and_account_specific_connection_evidence(monkeypatch):
    transport(monkeypatch, [])
    assert (await node({"operation": "list_graphs"}).execute({}))["data"] == []
    assert native.ReflectNode.connection_evidence.operation == "list_graphs"


@pytest.mark.asyncio
async def test_secrets_are_redacted_in_nested_output(monkeypatch):
    transport(monkeypatch, [{"id": "g", "name": TOKEN}])
    output = await node({"operation": "list_graphs"}).execute({})
    assert TOKEN not in str(output)


def test_manual_credential_defaults_and_contract_limit():
    credential = native.ReflectAccessTokenCredential(access_token=TOKEN)
    assert credential.credential_type == "reflect_access_token"
    assert len(native.ROUTES) == 7
    with pytest.raises(ValidationError):
        native.ReflectAccessTokenCredential(access_token="Bearer " + TOKEN)
    for config in [{"operation": "list_books", "graph_id": "../other"}, {"operation": "create_note", "graph_id": "g"}, {"operation": "delete_note"}]:
        with pytest.raises(ValueError):
            node(config)
