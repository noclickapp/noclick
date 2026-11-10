import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import merge_dev_node as mod
from nodes.core.registry import NodeFactory

CREDS = {"credential_type": "merge_dev_api_key", "api_key": "merge-test-key", "account_token": "merge-test-account"}
FIXTURES = Path(__file__).parent / "fixtures" / "merge-dev"

def node(config):
    return NodeFactory.create_node(node_id="merge-test", node_type="automation-merge-dev", node_data={"config": config, "credentials": CREDS})

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,spec", mod.OPERATIONS.items())
async def test_merge_dev_contract_requests(monkeypatch, operation, spec):
    category, method, path = spec
    config = {"operation": operation}
    if "{id}" in path:
        config["id"] = "0958cbc6-6040-430a-848e-aafacbadf4ae"
    if method in {"POST", "PATCH"}:
        config["model"] = {"first_name": "Gil"} if category == "ats" else {"name": "Please add more integrations"}
        if category == "ats": config["remote_user_id"] = "19202938"
    fixture_cat = category if category in {"ats", "hris", "ticketing"} else "ats"
    row = json.loads((FIXTURES / (fixture_cat + ".json")).read_text())
    listing = method == "GET" and "{id}" not in path and path != "/account-details"
    payload = {"results": [row], "next": None, "previous": None} if listing else {"model": row} if method != "GET" else row
    def respond(request):
        assert request.method == method
        assert request.url.path == "/api/" + category + "/v1" + path.replace("{id}", config.get("id", ""))
        assert request.headers["Authorization"] == "Bearer merge-test-key"
        assert request.headers["X-Account-Token"] == "merge-test-account"
        if method in {"POST", "PATCH"}:
            assert json.loads(request.content) == {k:v for k,v in config.items() if k in {"model", "remote_user_id"}}
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(mod, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    n = node(config)
    n._filter_unseen = AsyncMock(side_effect=lambda rows, key: rows)
    result = await n.execute({})
    if operation.startswith("on_"):
        assert result["items"] == [row]
        assert n.resolve_agent_event(result)["text"]
        key = n._filter_unseen.call_args.args[1]
        assert key(row) == row["id"] + ":" + row["modified_at"]
    else: assert result

@pytest.mark.asyncio
async def test_merge_dev_rejects_provider_failure(monkeypatch):
    monkeypatch.setattr(mod, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"detail": "Invalid token"}))))
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "list_employees"}).execute({})

def test_merge_dev_pagination_boundary():
    with pytest.raises(ValueError):
        mod.MergeDevNode._cursor({"next": 123}, "hris", "/employees")


def test_merge_dev_opaque_cursor():
    cursor = "cD0yMDIxLTAxLTA2KzAzJTNBMjQlM0E1My40MzQzMjYlMkIwMCUzQTAw"
    assert mod.MergeDevNode._cursor({"next": cursor}, "hris", "/employees") == cursor
