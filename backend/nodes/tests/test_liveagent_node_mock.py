"""LiveAgent v4 route, auth and poll behavior using schema-shaped synthetic fixtures."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import liveagent_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

RESPONSES = json.loads((Path(__file__).parent / "fixtures/liveagent/responses.json").read_text())
CREDENTIAL = {"credential_type": "liveagent_api_key", "account_url": "https://your.ladesk.com", "api_key": "test-liveagent-key"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="liveagent-test", node_type="automation-liveagent",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, reply):
    requests = []
    client_type = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return client_type(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def config_for(name):
    if "agent_activity" in name or "agent_worktime" in name:
        return {"operation": name, "agentId": "abc12345"}
    if "ticket_activity" in name:
        return {"operation": name, "ticketId": "ticket01"}
    if name in {"get_department", "rename_department"}:
        return {"operation": name, "departmentId": "dep67890", **({"newName": "Customer Support"} if name.startswith("rename") else {})}
    if name == "get_ticket_field_definition":
        return {"operation": name, "id": 1}
    return {"operation": name}


def response_for(name):
    if name == "rename_department":
        return {}
    if name == "get_ticket_field_definition":
        return {"data": RESPONSES["ticket_field_definitions"]["data"][0]}
    key = name.removeprefix("list_").removeprefix("get_").removeprefix("on_new_or_updated_")
    return copy.deepcopy(RESPONSES[key])


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [name for name in native.OPERATIONS if not name.startswith("on_")])
async def test_action_wire_contract(monkeypatch, operation):
    config = config_for(operation)
    requests = transport(monkeypatch, response_for(operation))
    result = await node(config).execute({})
    request = requests[0]
    spec = native.OPERATIONS[operation]
    expected_path = spec["path"]
    for key in spec["path_fields"]:
        expected_path = expected_path.replace("{" + key + "}", str(config[key]))
    assert request.method == spec["method"]
    assert request.url.path == "/api/v4" + expected_path
    assert request.url.host == "your.ladesk.com"
    assert request.headers["apikey"] == CREDENTIAL["api_key"]
    assert CREDENTIAL["api_key"] not in str(request.url)
    assert result == {"status": "success", "operation": operation, "data": response_for(operation)}
    if operation == "rename_department":
        assert json.loads(request.content) == {"newName": "Customer Support"}


@pytest.mark.asyncio
async def test_filter_serialization_preserves_arrays_and_false(monkeypatch):
    requests = transport(monkeypatch, RESPONSES["agent_activity"])
    await node({"operation": "list_agent_activity", "agentId": "abc12345", "ticketId": ["ticket01", "ticket02"],
        "activityType": ["solve", "view"], "activityFromStart": "2025-01-01T00:00:00Z", "sortOrder": "asc"}).execute({})
    assert requests[0].url.params.get_list("ticketId") == ["ticket01", "ticket02"]
    assert requests[0].url.params.get_list("activityType") == ["solve", "view"]
    assert requests[0].url.params["activityFromStart"] == "2025-01-01T00:00:00Z"
    requests = transport(monkeypatch, RESPONSES["ticket_field_definitions"])
    await node({"operation": "list_ticket_field_definitions", "includeArchived": False}).execute({})
    assert requests[0].url.params["includeArchived"] == "false"


@pytest.mark.parametrize("url", ["http://your.ladesk.com", "https://ladesk.com.evil.test", "https://evil.test", "https://your.ladesk.com@evil.test", "https://your.ladesk.com/api/v4", "https://127.0.0.1", "https://your.ladesk.com?key=foo"])
def test_credential_refuses_wrong_origins(url):
    with pytest.raises((ValidationError, ValueError)):
        native.LiveAgentAPIKeyCredential.model_validate({**CREDENTIAL, "account_url": url})


def test_manual_credential_default_and_normalized_host():
    value = native.LiveAgentAPIKeyCredential(account_url="https://YOUR.ladesk.com/", api_key="secret")
    assert value.credential_type == "liveagent_api_key"
    assert value.account_url == "https://your.ladesk.com"


@pytest.mark.parametrize("config", [
    {"operation":"list_agent_activity","agentId":"bad"},
    {"operation":"get_ticket_field_definition","id":0},
    {"operation":"rename_department","departmentId":"dep67890","newName":""},
    {"operation":"list_agent_availability","limit":1001},
])
def test_contract_input_constraints(config):
    with pytest.raises(ValueError):
        node(config).config


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [name for name in native.OPERATIONS if name.startswith("on_")])
async def test_poll_baseline_new_updated_and_duplicate_suppression(monkeypatch, operation):
    reply = response_for(operation)
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=reply))
    instance = node(config_for(operation))
    state = {}
    async def update(mutator, skip_result=None):
        nonlocal state
        replacement, output = mutator(state)
        if replacement is not None:
            state = replacement
        return output
    monkeypatch.setattr(instance, "_update_node_state", update)
    assert (await instance.execute({}))["event_count"] == 0
    row_key = native.OPERATIONS[operation]["rows"]
    new_row = copy.deepcopy(reply[row_key][0])
    time_key = "activityFrom" if operation.endswith("activity") else "statusFrom" if operation.endswith("worktime") else "availableFrom"
    new_row[time_key] = "2025-01-02T00:00:00Z"
    reply[row_key].append(new_row)
    output = await instance.execute({})
    assert output["records"] == [new_row] and output["event_count"] == 1
    event = native.LiveAgentNode.resolve_agent_event(output)
    assert "LiveAgent" in event["text"] and "2025-01-02" in event["text"]
    assert instance.trigger_emitted_event(output)
    assert (await instance.execute({}))["event_count"] == 0
    end_key = "activityTo" if operation.endswith("activity") else "statusTo" if operation.endswith("worktime") else "availableTo"
    new_row[end_key] = "2025-01-02T01:00:00Z"
    assert (await instance.execute({}))["records"] == [new_row]
    assert "schedule" not in requests[-1].url.params
    config = config_for(operation)
    assert poll_scope(native.LiveAgentNode, config) == poll_scope(native.LiveAgentNode, {**config, "label": "Changed label"})




@pytest.mark.asyncio
async def test_truncated_poll_never_consumes_seen_state(monkeypatch):
    transport(monkeypatch, {**RESPONSES["agent_activity"], "truncated": True})
    instance = node(config_for("on_new_or_updated_agent_activity"))
    async def unseen(*args):
        pytest.fail("Must not update state after an incomplete read")
    monkeypatch.setattr(instance, "_filter_unseen", unseen)
    with pytest.raises(ValueError, match="truncated"):
        await instance.execute({})




@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error":"Wrong API key"}), (403, {"detail":"Permission denied"}), (200, {"error":"Bad request"}), (302, {})])
async def test_provider_errors_and_redirects_fail(monkeypatch, status, body):
    transport(monkeypatch, lambda _: httpx.Response(status, json=body))
    with pytest.raises(ValueError, match="LiveAgent API error"):
        await node({"operation":"list_ticket_field_definitions"}).execute({})
