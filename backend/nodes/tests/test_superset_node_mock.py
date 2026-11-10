"""Synthetic REST responses shaped by Apache's pinned v1 schemas, never live data."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import superset_node as db
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "superset_api_key", "server_url": "https://superset.example.com", "api_key": "synthetic-key"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/superset/list_responses.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        assert request.url.host == "superset.example.com"
        assert "synthetic-key" not in str(request.url)
        code, payload = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(code, content=payload)
        return httpx.Response(code, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(db, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type="automation-superset", operation=operation, arguments=arguments,
                                    credential_data=deepcopy(AUTH), user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body", [
    ("get_current_user", {}, "GET", "/api/v1/me/", None),
    ("get_dashboard", {"dashboard_id": 7}, "GET", "/api/v1/dashboard/7", None),
    ("create_dashboard", {"dashboard_title": "Revenue", "published": False}, "POST", "/api/v1/dashboard/", {"dashboard_title": "Revenue", "published": False}),
    ("update_dashboard", {"dashboard_id": 7, "dashboard_title": "Revenue", "position_json": "{}"}, "PUT", "/api/v1/dashboard/7", {"dashboard_title": "Revenue", "position_json": "{}"}),
    ("delete_dashboard", {"dashboard_id": 7}, "DELETE", "/api/v1/dashboard/7", None),
    ("list_dashboard_charts", {"dashboard_id": 7}, "GET", "/api/v1/dashboard/7/charts", None),
    ("get_chart", {"chart_id": 9}, "GET", "/api/v1/chart/9", None),
    ("create_chart", {"slice_name": "Sales", "datasource_id": 3, "datasource_type": "table", "params": "{}"}, "POST", "/api/v1/chart/", {"slice_name": "Sales", "datasource_id": 3, "datasource_type": "table", "params": "{}"}),
    ("update_chart", {"chart_id": 9, "slice_name": "Sales", "dashboards": [7]}, "PUT", "/api/v1/chart/9", {"slice_name": "Sales", "dashboards": [7]}),
    ("delete_chart", {"chart_id": 9}, "DELETE", "/api/v1/chart/9", None),
    ("get_chart_data", {"chart_id": 9}, "GET", "/api/v1/chart/9/data/", None),
    ("get_dataset", {"dataset_id": 3}, "GET", "/api/v1/dataset/3", None),
    ("create_dataset", {"database": 2, "table_name": "sales", "schema_name": "public"}, "POST", "/api/v1/dataset/", {"database": 2, "table_name": "sales", "schema": "public"}),
    ("update_dataset", {"dataset_id": 3, "table_name": "sales", "description": "Daily sales"}, "PUT", "/api/v1/dataset/3", {"table_name": "sales", "description": "Daily sales"}),
    ("delete_dataset", {"dataset_id": 3}, "DELETE", "/api/v1/dataset/3", None),
    ("refresh_dataset", {"dataset_id": 3}, "PUT", "/api/v1/dataset/3/refresh", None),
    ("get_database", {"database_id": 2}, "GET", "/api/v1/database/2", None),
])
async def test_fixed_routes_and_native_json(wire, operation, arguments, method, path, body):
    requests, replies = wire
    replies.append((201 if operation.startswith("create_") else 200, {"result": {"id": 7}}))
    result = await run(operation, **arguments)
    assert result["result"]["id"] == 7
    assert len(requests) == 1
    req = requests[0]
    assert (req.method, req.url.path) == (method, path)
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dashboard", "chart", "dataset", "database"])
async def test_list_pagination(wire, kind):
    requests, replies = wire
    replies.append((200, {"count": 201, "result": []}))
    result = await run("list_" + kind + "s", page=1, page_size=100)
    assert result["next_page"] == 2
    assert json.loads(requests[0].url.params["q"]) == {"page": 1, "page_size": 100}


def make_poll(kind, page_size=100):
    config = db.SupersetNode.parse_config({"config": {"operation": "on_new_or_updated_" + kind, "page_size": page_size}, "credentials": AUTH})
    return db.SupersetNode(node_id="poll", node_type="automation-superset", node_data={}, config=config)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dashboard", "chart"])
async def test_poll_baseline_new_update_and_scope_reset(wire, monkeypatch, kind):
    requests, replies = wire
    node = make_poll(kind)
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        new, result = mutator(deepcopy(state))
        if new is not None:
            state = new
        return result
    monkeypatch.setattr(node, "_update_node_state", update)
    original = deepcopy(FIXTURE[kind])
    replies.append((200, original))
    assert (await node.execute({}))["new_or_updated_count"] == 0
    assert node.trigger_produced_no_event({})
    changed = deepcopy(original)
    changed["result"][0]["changed_on_utc"] = "2026-11-10T10:01:00+0000"
    changed["result"].append({**changed["result"][0], "id": 12})
    replies.append((200, changed))
    output = await node.execute({})
    assert output["new_or_updated_count"] == 2
    event = node.resolve_agent_event(output)
    assert "ID 12" in event["text"] and "Superset" in event["text"]
    assert node.trigger_emitted_event(output)
    replies.append((200, changed))
    assert (await node.execute({}))["items"] == []
    assert node.resolve_agent_event({"items": []}) is None
    node._config.config.page_size = 50
    replies.append((200, changed))
    assert (await node.execute({}))["items"] == []
    query = json.loads(requests[0].url.params["q"])
    assert query["page"] == 0 and query["page_size"] == 100
    if kind == "dashboard":
        assert query["order_column"] == "changed_on"
    else:
        assert "order_column" not in query


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,match", [
    (401, {"message": "Invalid API key"}, "Invalid API key"),
    (403, {"message": "Denied"}, "Denied"),
    (500, {"message": "Failed"}, "Failed"),
    (302, b"", "HTTP 302"),
    (200, b"<html>login</html>", "invalid JSON"),
    (200, [], "unexpected response"),
])
async def test_failure_is_not_success_and_no_retry(wire, status, payload, match):
    requests, replies = wire
    replies.append((status, payload))
    with pytest.raises(ValueError, match=match):
        await run("create_dashboard", dashboard_title="Revenue")
    assert len(requests) == 1


@pytest.mark.parametrize("field,value", [("api_key", "Bearer secret"), ("api_key", "https://example.com/key"), ("server_url", "https://user:pass@example.com"), ("server_url", "http://example.com")])
def test_bad_manual_credentials(field, value):
    with pytest.raises(ValueError):
        db.SupersetAPIKeyCredential.model_validate({**AUTH, field: value})


def test_manual_credential_defaults_and_shape():
    cred = db.SupersetAPIKeyCredential(server_url=" https://superset.example.com/dashboard/1 ", api_key=" synthetic-key ")
    assert cred.credential_type == "superset_api_key"
    assert cred.server_url == "https://superset.example.com"
    assert cred.api_key == "synthetic-key"
