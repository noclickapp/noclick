"""Exercise Base44's native node with provider-shaped HTTP responses.

Wire assertions cover every operation, custom fields and pagination. Rejection
cases ensure provider errors and malformed responses cannot appear successful.
"""
import json
from copy import deepcopy
from unittest.mock import AsyncMock, Mock
from pathlib import Path
from nodes.core.poll_trigger import poll_scope
import httpx
import pytest
from pydantic import ValidationError
from nodes import base44_node as base44
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "base44_token", "access_token": "synthetic-base44-personal-token"}
APP = "6820f3a4e7b91d003c45a1f2"
ID = "6886b8d390dc7e2f4a2c91b3"
ENTITY = {"app_id": APP, "entity_name": "Invoice"}
RECORD = {**ENTITY, "entity_id": ID}
USER = {"app_id": APP, "user_id": "6874b0c2e1a94d0031bb77de"}
DATA = {"amount": 4200, "status": "draft", "customer_email": "jane@acme.com"}
ROW = {"id": ID, **DATA}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def wire(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "app.base44.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        assert AUTH["access_token"] not in str(request.url)
        return responses.pop(0)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(base44, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, responses

async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-base44", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(AUTH),
        user_id="00000000-0000-4000-8000-000000000001")

CASES = [
    ("list_apps", {}, "GET", "/api/apps", None, [{"id": APP, "name": "CRM"}]),
    ("get_app", {"app_id": APP}, "GET", f"/api/apps/{APP}", None, {"id": APP}),
    ("create_app", {"name": "CRM"}, "POST", "/api/apps", {"name": "CRM"}, {"id": APP}),
    ("update_app", {"app_id": APP, "name": "CRM"}, "PUT", f"/api/apps/{APP}", {"name": "CRM"}, {"id": APP}),
    ("list_entity_schemas", {"app_id": APP}, "GET", f"/api/apps/{APP}/entity-schemas", None, {"schemas": [], "total": 0}),
    ("get_entity_schema", ENTITY, "GET", f"/api/apps/{APP}/entity-schemas/Invoice", None, {"name": "Invoice", "type": "object"}),
    ("list_records", ENTITY, "GET", f"/api/apps/{APP}/entities/Invoice/v2/list", None, {"items": [ROW], "has_more": True, "next_cursor": "opaque-cursor"}),
    ("count_records", ENTITY, "GET", f"/api/apps/{APP}/entities/Invoice/count", None, {"count": 1}),
    ("get_record", RECORD, "GET", f"/api/apps/{APP}/entities/Invoice/{ID}", None, ROW),
    ("create_record", {**ENTITY, "data": DATA}, "POST", f"/api/apps/{APP}/entities/Invoice", DATA, ROW),
    ("update_record", {**RECORD, "data": {"status": "paid"}}, "PUT", f"/api/apps/{APP}/entities/Invoice/{ID}", {"status": "paid"}, {**ROW, "status": "paid"}),
    ("delete_record", RECORD, "DELETE", f"/api/apps/{APP}/entities/Invoice/{ID}", None, {"success": True}),
    ("create_records", {**ENTITY, "records": [DATA]}, "POST", f"/api/apps/{APP}/entities/Invoice/bulk", [DATA], [ROW]),
    ("update_records", {**ENTITY, "records": [{"id": ID, "status": "paid"}]}, "PUT", f"/api/apps/{APP}/entities/Invoice/bulk", [{"id": ID, "status": "paid"}], [{**ROW, "status": "paid"}]),
    ("list_deleted_records", ENTITY, "GET", f"/api/apps/{APP}/entities/Invoice/trash", None, [ROW]),
    ("restore_record", RECORD, "PUT", f"/api/apps/{APP}/entities/Invoice/{ID}/restore", None, ROW),
    ("list_app_users", {"app_id": APP}, "GET", f"/api/apps/{APP}/entities/User", None, [{"id": USER["user_id"], "email": "jane@acme.com"}]),
    ("get_app_user", USER, "GET", f"/api/apps/{APP}/entities/User/{USER['user_id']}", None, {"id": USER["user_id"]}),
    ("update_app_user", {**USER, "data": {"department": "Sales"}}, "PUT", f"/api/apps/{APP}/entities/User/{USER['user_id']}", {"department": "Sales"}, {"id": USER["user_id"], "department": "Sales"}),
    ("delete_app_user", USER, "DELETE", f"/api/apps/{APP}/entities/User/{USER['user_id']}", None, {"success": True}),
]

@pytest.mark.parametrize("operation,arguments,method,path,body,payload", CASES)
async def test_native_operations(wire, operation, arguments, method, path, body, payload):
    requests, responses = wire
    responses.append(httpx.Response(200, json=deepcopy(payload)))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert result["items" if isinstance(payload, list) else "data"] == payload
    assert len(requests) == 1
    assert requests[0].method == method and requests[0].url.path == path
    assert (json.loads(requests[0].content) if requests[0].content else None) == body

async def test_cursor_filters_and_custom_fields_survive(wire):
    requests, responses = wire
    responses.append(httpx.Response(200, json={"items": [ROW], "next_cursor": None, "has_more": False}))
    result = await run("list_records", {**ENTITY, "q": {"status": "paid"}, "cursor": "opaque+cursor/==", "fields": "amount,status", "limit": 25})
    params = requests[0].url.params
    assert json.loads(params["q"]) == {"status": "paid"}
    assert params["cursor"] == "opaque+cursor/==" and params["limit"] == "25"
    assert result["data"]["items"][0]["customer_email"] == DATA["customer_email"]
    assert result["data"]["next_cursor"] is None

async def test_connection_evidence_lists_this_accounts_apps(wire):
    from nodes.core.connection_evidence import collect_evidence
    requests, responses = wire
    responses.append(httpx.Response(200, json=[{"id": APP, "name": "My CRM"}]))
    proof = await collect_evidence(node_type="automation-base44", credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert proof.reachable is True
    assert any(sample.label == "My CRM" for sample in proof.samples)
    assert requests[0].url.path == "/api/apps"

@pytest.mark.parametrize("code", [401, 403, 404, 429, 500])
async def test_provider_error_does_not_become_success(wire, code):
    requests, responses = wire
    responses.append(httpx.Response(code, json={"error": {"code": "denied", "message": "Token rejected"}}))
    result = await run("list_apps")
    assert result["status"] == "error" and result["http_status"] == code
    assert "Token rejected" in result["error"] and len(requests) == 1

async def test_redirects_are_not_followed(wire):
    requests, responses = wire
    responses.append(httpx.Response(302, headers={"Location": "https://other.example.test"}))
    result = await run("list_apps")
    assert result["status"] == "error" and len(requests) == 1

@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>Sign in</html>"), httpx.Response(200, json="bad")])
async def test_unexpected_response_refused(wire, response):
    wire[1].append(response)
    with pytest.raises(ValueError):
        await run("list_apps")

@pytest.mark.parametrize("config", [
    {"operation": "get_app", "app_id": "../../other"},
    {"operation": "list_records", "app_id": APP, "entity_name": "User"},
    {"operation": "get_record", **ENTITY, "entity_id": "a?b"},
    {"operation": "list_apps", "limit": 0},
    {"operation": "update_records", **ENTITY, "records": [{"status": "paid"}]},
])
def test_invalid_config_is_rejected(config):
    assert base44.Base44Node.validate_config({"config": config, "credentials": AUTH})["valid"] is False

def test_manual_credential_type_defaults():
    assert base44.Base44TokenCredential(access_token=AUTH["access_token"]).credential_type == "base44_token"
    with pytest.raises(ValidationError):
        base44.Base44TokenCredential(access_token="Bearer some-token")

# Record fields are copied from the published contract's EntityRecordPage
# items example; the completed page uses its documented pagination fields.
PAGE = json.loads((Path(__file__).parent / "fixtures/base44/record_page.json").read_text())


def poll_node(operation, state, **fields):
    raw = {"operation": operation, **ENTITY, **fields}
    node = base44.Base44Node(node_id="base44-poll", node_type="automation-base44",
        node_data={"config": raw}, config=base44.Base44Config.model_validate({"config": raw, "credentials": AUTH}), sio=Mock())
    node.emit = AsyncMock()

    async def update(mutator, **kwargs):
        updated, result = mutator(deepcopy(state))
        if updated is not None:
            state.clear()
            state.update(updated)
        return result

    node._update_node_state = update
    return node


@pytest.mark.parametrize("operation", ["on_new_record", "on_new_or_updated_record"])
async def test_record_poll_baseline_fresh_dedup_and_agent(wire, operation):
    state = {}
    node = poll_node(operation, state)
    wire[1].append(httpx.Response(200, json=deepcopy(PAGE)))
    baseline = await node.execute({})
    assert baseline["records"] == [] and node.trigger_produced_no_event(baseline)
    assert base44.Base44Node.resolve_agent_event(baseline) is None
    # An already-armed empty scope sees the provider's example record as new.
    state["seen_ids"] = []
    wire[1].append(httpx.Response(200, json=deepcopy(PAGE)))
    output = await node.execute({})
    assert output["records"] == PAGE["items"] and node.trigger_emitted_event(output)
    text = base44.Base44Node.resolve_agent_event(output)["text"]
    for value in (APP, "Invoice", ID, "jane@acme.com", "draft", "4200"):
        assert value in text
    wire[1].append(httpx.Response(200, json=deepcopy(PAGE)))
    assert (await node.execute({}))["records"] == []
    assert wire[0][0].url.params["sort"] == ("-updated_date" if "updated" in operation else "-created_date")
    assert base44.Base44Node.resolve_trigger_payload({"tick": True}, {"operation": operation}) is None


@pytest.mark.parametrize("operation,fires", [("on_new_record", False), ("on_new_or_updated_record", True)])
async def test_only_updated_trigger_fires_for_changed_timestamp(wire, operation, fires):
    state = {}
    node = poll_node(operation, state)
    before = deepcopy(PAGE)
    before["items"][0]["updated_date"] = before["items"][0]["created_date"]
    wire[1].extend([httpx.Response(200, json=before), httpx.Response(200, json=deepcopy(PAGE))])
    await node.execute({})
    result = await node.execute({})
    assert bool(result["records"]) is fires


async def test_poll_window_filter_and_scope_change(wire):
    state = {"seen_ids": []}
    node = poll_node("on_new_record", state, q={"status": "paid"})
    first = {**deepcopy(PAGE), "has_more": True, "next_cursor": "gAAAAABn7vJ..."}
    wire[1].append(httpx.Response(200, json=first))
    assert (await node.execute({}))["records"] == PAGE["items"]
    assert json.loads(wire[0][0].url.params["q"]) == {"status": "paid"}
    assert len(wire[0]) == 1 and wire[0][0].url.params["limit"] == "500"
    other = poll_node("on_new_record", state, q={"status": "draft"})
    wire[1].append(httpx.Response(200, json=deepcopy(PAGE)))
    assert (await other.execute({}))["records"] == []
    cfg = {"operation": "on_new_record", **ENTITY}
    assert poll_scope(base44.Base44Node, cfg) == poll_scope(base44.Base44Node, {**cfg, "label": "Renamed", "schedule": {"frequency": "minutes", "interval": 10}})


@pytest.mark.parametrize("response", [httpx.Response(403, json={"error": "denied"}),
    httpx.Response(200, json={"items": "bad"}),
    httpx.Response(200, json={"items": [{}], "has_more": False})])
async def test_failed_poll_preserves_state(wire, response):
    state = {"seen_ids": [ID]}
    node = poll_node("on_new_or_updated_record", state)
    wire[1].append(response)
    with pytest.raises(ValueError):
        await node.execute({})
    assert state == {"seen_ids": [ID]}
    node.emit.assert_not_awaited()
