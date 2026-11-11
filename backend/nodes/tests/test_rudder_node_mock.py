"""Rudder v12 wire semantics, typed-in credentials and inventory revisions."""
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes.rudder_node import RudderTokenCredential, RudderNode
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

TOKEN = "rudder-test-token-12345"
CREDENTIAL = {"credential_type": "rudder_api_token", "server_url": "https://rudder.example.com", "api_token": TOKEN}
ID = "9a1773c9-0889-40b6-be89-f6504443ac1b"
QUERY = {"select": "node", "composition": "and", "where": [{"objectType": "node", "attribute": "OS", "comparator": "eq", "value": "Linux"}]}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/rudder/node.json").read_text())


def node(config, credential=None):
    return NodeFactory.create_node(node_id="rudder-test", node_type="automation-rudder",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, responder):
    calls = []
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async def handle(request):
            calls.append(request)
            assert request.headers["X-API-Token"] == TOKEN
            assert TOKEN not in str(request.url)
            return responder(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as session:
            yield session
    monkeypatch.setattr("nodes.rudder_node.guarded_async_client", client)
    return calls


@pytest.mark.parametrize("operation,config,method,path,params,body", [
    ("list_nodes", {}, "GET", "/nodes", {"include": "default"}, None),
    ("get_node", {"node_id": ID}, "GET", f"/nodes/{ID}", {"include": "default"}, None),
    ("update_node", {"node_id": ID, "properties": [{"name": "datacenter", "value": {"site": "AMS2"}}], "policy_mode": "audit", "state": "enabled", "reason": "Reason used"}, "POST", f"/nodes/{ID}", {"reason": "Reason used"}, {"properties": [{"name": "datacenter", "value": {"site": "AMS2"}}], "policyMode": "audit", "state": "enabled"}),
    ("list_pending_nodes", {}, "GET", "/nodes/pending", {"include": "default"}, None),
    ("set_pending_node_status", {"node_id": ID, "status": "accepted"}, "POST", f"/nodes/pending/{ID}", {}, {"status": "accepted"}),
    ("list_rules", {}, "GET", "/rules", {}, None),
    ("get_rule", {"rule_id": ID}, "GET", f"/rules/{ID}", {}, None),
    ("create_rule", {"display_name": "Security policy", "category": ID, "directives": [ID], "targets": ["group:" + ID]}, "PUT", "/rules", {}, {"displayName": "Security policy", "category": ID, "directives": [ID], "targets": ["group:" + ID], "enabled": False}),
    ("update_rule", {"rule_id": ID, "enabled": False, "directives": [], "targets": [], "change_request_name": "Policy update", "change_request_description": "Review this"}, "POST", f"/rules/{ID}", {"changeRequestName": "Policy update", "changeRequestDescription": "Review this"}, {"enabled": False, "directives": [], "targets": []}),
    ("delete_rule", {"rule_id": ID}, "DELETE", f"/rules/{ID}", {}, None),
    ("list_directives", {}, "GET", "/directives", {}, None),
    ("get_directive", {"directive_id": ID}, "GET", f"/directives/{ID}", {}, None),
    ("update_directive", {"directive_id": ID, "priority": 0, "technique_version": "8.0", "policy_mode": "audit", "enabled": False, "parameters": {"section": {"name": "sections"}}}, "POST", f"/directives/{ID}", {}, {"priority": 0, "techniqueVersion": "8.0", "policyMode": "audit", "enabled": False, "parameters": {"section": {"name": "sections"}}}),
    ("list_groups", {}, "GET", "/groups", {}, None),
    ("get_group", {"group_id": ID}, "GET", f"/groups/{ID}", {}, None),
    ("create_group", {"display_name": "Linux nodes", "query": QUERY}, "PUT", "/groups", {}, {"displayName": "Linux nodes", "query": QUERY, "dynamic": True, "enabled": True}),
    ("update_group", {"group_id": ID, "query": QUERY, "enabled": False}, "POST", f"/groups/{ID}", {}, {"query": QUERY, "enabled": False}),
    ("delete_group", {"group_id": ID, "reason": "Reason used"}, "DELETE", f"/groups/{ID}", {"reason": "Reason used"}, None),
    ("reload_group", {"group_id": ID}, "POST", f"/groups/{ID}/reload", {}, None),
    ("list_parameters", {}, "GET", "/parameters", {}, None),
    ("get_parameter", {"parameter_id": "rudder_file_edit_header"}, "GET", "/parameters/rudder_file_edit_header", {}, None),
    ("create_parameter", {"parameter_id": "rudder_file_edit_footer", "value": json.dumps("### End of file managed by Rudder ###")}, "PUT", "/parameters", {}, {"id": "rudder_file_edit_footer", "value": "### End of file managed by Rudder ###", "overridable": False}),
    ("get_global_compliance", {}, "GET", "/compliance", {}, None),
    ("get_nodes_compliance", {"level": 6}, "GET", "/compliance/nodes", {"level": "6"}, None),
])
@pytest.mark.asyncio
async def test_request_contract(monkeypatch, operation, config, method, path, params, body):
    response = {"result": "success", "action": "test", "data": {key: [] for key in ["nodes", "rules", "directives", "groups", "parameters"]}}
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=response))
    assert await node({"operation": operation, **config}).execute({}) == {"status": "success", **response}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.raw_path.split(b"?")[0].decode() == "/rudder/api/latest" + path
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
async def test_search_is_one_json_query_parameter(monkeypatch):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"result": "success", "data": {"nodes": []}}))
    await node({"operation": "list_nodes", "query": QUERY, "include": "minimal"}).execute({})
    assert json.loads(calls[0].url.params["query"]) == QUERY
    assert set(calls[0].url.params) == {"query", "include"}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, False, 0, "", {"site": "AMS2"}])
async def test_parameter_preserves_json_values(monkeypatch, value):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"result": "success", "data": {"parameters": []}}))
    await node({"operation": "create_parameter", "parameter_id": "test", "value": json.dumps(value)}).execute({})
    assert json.loads(calls[0].content)["value"] == value


def test_manual_credential_default_and_normalization():
    credential = RudderTokenCredential(server_url=" https://RUDDER.example.com/ ", api_token=TOKEN)
    assert credential.credential_type == "rudder_api_token"
    assert credential.server_url == "https://rudder.example.com"
    assert TOKEN not in repr(credential)


@pytest.mark.parametrize("url", ["http://rudder.example.com", "https://user:pass@rudder.example.com", "https://rudder.example.com?x=1", "https://rudder.example.com/rudder/api/latest", "https://rudder.example.com#x", "https://rudder.example.com:123", "https://rudder.example.com/../", "https://rudder.example.com/%2f"])
def test_invalid_server(url):
    with pytest.raises(ValidationError):
        RudderTokenCredential(server_url=url, api_token=TOKEN)


@pytest.mark.parametrize("field,operation", [("node_id", "get_node"), ("rule_id", "get_rule"), ("directive_id", "get_directive"), ("group_id", "get_group"), ("parameter_id", "get_parameter")])
def test_rejects_path_escape(field, operation):
    for value in ["..", "../settings", "a/b", "a\\b", "x\n"]:
        with pytest.raises(ValueError):
            node({"operation": operation, field: value}).config


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 500])
async def test_error_envelope_and_redaction(monkeypatch, status):
    transport(monkeypatch, lambda request: httpx.Response(status, json={"result": "error", "errorDetails": "Rejected " + TOKEN}))
    result = await node({"operation": "list_nodes"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}


@pytest.mark.asyncio
async def test_redirect_not_followed(monkeypatch):
    calls = transport(monkeypatch, lambda request: httpx.Response(302, headers={"Location": "https://other.example.com"}))
    assert (await node({"operation": "list_nodes"}).execute({}))["status"] == "error"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>login</html>"), httpx.Response(200, json={"result": "success"}), httpx.Response(200, json={"result": "success", "data": {}}), httpx.Response(200, json={"data": {"nodes": []}})])
async def test_incomplete_success_does_not_prove_connection(monkeypatch, response):
    transport(monkeypatch, lambda request: response)
    with pytest.raises(ValueError, match="success envelope"):
        await node({"operation": "list_nodes"}).execute({})


@pytest.mark.asyncio
async def test_official_node_response_preserved(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json=FIXTURE))
    assert (await node({"operation": "get_node", "node_id": "node1"}).execute({}))["data"] == FIXTURE["data"]


@pytest.mark.asyncio
async def test_inventory_baseline_revisions_and_dedup(monkeypatch):
    # Same documented node schema in the /nodes list envelope.
    response = {"result": "success", "action": "listAcceptedNodes", "data": copy.deepcopy(FIXTURE["data"])}
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=response))
    instance = node({"operation": "on_inventory_updated"})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        next_state, result = mutator(copy.deepcopy(state))
        if next_state is not None:
            state = next_state
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)
    assert (await instance.execute({}))["new_inventory_count"] == 0
    assert instance.trigger_produced_no_event({})
    response["data"]["nodes"][0]["lastInventoryDate"] = "2021-01-31T00:20:00Z"
    result = await instance.execute({})
    assert result["new_inventory_count"] == 1
    assert instance.trigger_emitted_event(result)
    assert result["nodes"][0]["hostname"] == "node1.localhost"
    assert (await instance.execute({}))["new_inventory_count"] == 0
    second = copy.deepcopy(response["data"]["nodes"][0]); second["id"] = "node2"
    response["data"]["nodes"].append(second)
    assert (await instance.execute({}))["new_inventory_count"] == 1
    assert all(dict(call.url.params) == {"include": "minimal,lastInventoryDate"} for call in calls)
    assert poll_scope(RudderNode, {"operation": "on_inventory_updated"}) == poll_scope(RudderNode, {"operation": "on_inventory_updated", "label": "Changed label"})


@pytest.mark.asyncio
async def test_missing_inventory_timestamp_and_failed_poll_preserve_state(monkeypatch):
    response = {"result": "success", "data": {"nodes": [{"id": "node1", "hostname": "node1.localhost", "status": "accepted"}]}}
    transport(monkeypatch, lambda request: httpx.Response(200, json=response))
    instance = node({"operation": "on_inventory_updated"})
    seen = []
    async def unseen(items, key):
        seen.extend(items)
        return items
    monkeypatch.setattr(instance, "_filter_unseen", unseen)
    assert (await instance.execute({}))["new_inventory_count"] == 0
    assert seen == []
    transport(monkeypatch, lambda request: httpx.Response(403, json={"result": "error", "errorDetails": "Forbidden"}))
    assert (await instance.execute({}))["status"] == "error"
    assert seen == []


@pytest.mark.asyncio
async def test_inventory_fleet_bound_does_not_advance_state(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"result": "success", "data": {"nodes": [{key: FIXTURE["data"]["nodes"][0][key] for key in ["id", "hostname", "status", "lastInventoryDate"]}] * 10001}}))
    instance = node({"operation": "on_inventory_updated"})
    async def unseen(*args):
        pytest.fail("An oversized fleet must not change the baseline")
    monkeypatch.setattr(instance, "_filter_unseen", unseen)
    with pytest.raises(ValueError, match="10000 nodes"):
        await instance.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "", False, {"nested": None}])
async def test_node_property_preserves_explicit_values(monkeypatch, value):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"result": "success", "data": {"nodes": []}}))
    await node({"operation": "update_node", "node_id": ID, "properties": [{"name": "test", "value": value}]}).execute({})
    assert json.loads(calls[0].content) == {"properties": [{"name": "test", "value": value}]}
