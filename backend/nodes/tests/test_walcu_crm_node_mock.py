"""Exercise Walcu's native factory with schema-shaped synthetic records.

These fixtures check requests, response preservation and real poll deduplication;
provider contract conformance is run separately against the pinned OpenAPI file.
"""
import base64
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import walcu_crm_node as walcu
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": walcu.TYPE, "username": "fixture-user", "password": "fixture-password", "dealer_id": "dealer-1"}
CLIENT = "0123456789abcdef01234567"
LEAD = "abcdef0123456789abcdef01"
RECORD = json.loads((Path(__file__).parent / "fixtures/walcu-crm/records.json").read_text())["record"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.crm.walcu.com"
        assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"fixture-user:fixture-password").decode()
        assert "fixture-password" not in str(request.url)
        code, payload, headers = replies.pop(0)
        return httpx.Response(code, json=payload, headers=headers)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(walcu, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, args=None, auth=None):
    return await run_node_operation(node_type="automation-walcu-crm", operation=operation, arguments=args or {},
        credential_data=AUTH if auth is None else auth, user_id="00000000-0000-4000-8000-000000000001", pool=None)


CREATE = {
    "client": {"first_name": "Alex", "last_name": "Smith", "email": "alex@example.test", "phone": "+15550123456"},
    "salelead": {"client_id": CLIENT, "inquiry": "Test drive", "location": "Madrid"},
    "task": {"client_id": CLIENT, "description": "Call the client"},
    "note": {"client_id": CLIENT, "content": "Requested financing"},
    "car": {"make": "Example", "model": "Demo", "published": False, "mileage": 0},
    "date": {"title": "Test drive", "start_date": "2026-11-10", "event_type": "test-drive"},
}
CASES = []
for resource, plural in (("client", "clients"), ("salelead", "saleleads"), ("task", "tasks"), ("note", "notes"), ("car", "cars"), ("date", "dates")):
    CASES.extend([
        ("list_" + plural, {"skip": 100, "limit": 50, "search": "Alex", "sort": "updated_at"}, "GET", "/" + plural, None),
        ("create_" + resource, CREATE[resource], "POST", "/" + plural, {"dealer_id": "dealer-1", **CREATE[resource]} if resource != "client" else {
            "dealer_id": "dealer-1", "primary_contact": {"name": {"first_name": "Alex", "last_name": "Smith"}, "emails": ["alex@example.test"], "phones": ["+15550123456"]}}),
    ])
    if resource != "date":
        CASES.extend([
            ("get_" + resource, {resource + "_id": CLIENT}, "GET", "/" + plural + "/" + CLIENT, None),
            ("update_" + resource, {resource + "_id": CLIENT, "patch": [{"op": "replace", "path": "/custom", "value": "reviewed"}]},
             "PATCH", "/" + plural + "/" + CLIENT, [{"op": "replace", "path": "/custom", "value": "reviewed"}]),
        ])


@pytest.mark.parametrize("operation,args,method,path,body", CASES)
async def test_walcu_crm_operation_routes_and_bodies(transport, operation, args, method, path, body):
    requests, replies = transport
    # The pinned getone schemas explicitly return arrays, unlike create/patch.
    data = [RECORD] if method == "GET" else RECORD
    replies.append((200, data, {"mapp-has-more": "true"} if operation.startswith("list_") else {}))
    output = await run(operation, args)
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/dealers/dealer-1" + path
    assert output["status"] == "success"
    assert (output.get("items") if operation.startswith("list_") else output["data"]) == data
    if body is not None:
        assert json.loads(request.content) == body
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"skip": "100", "limit": "50", "search": "Alex", "sort": "updated_at"}
        assert output["has_more"] and output["next_skip"] == 101


@pytest.mark.parametrize("operation", walcu.TRIGGERS)
async def test_walcu_crm_poll_baseline_repeat_update_new_and_repoint(transport, operation):
    requests, replies = transport
    node = NodeFactory.create_node(node_id="walcu-poll", node_type="automation-walcu-crm",
        node_data={"config": {"operation": operation}, "credentials": AUTH})
    state = {}

    async def update(mutator, **kwargs):
        new, value = mutator(deepcopy(state))
        if new is not None:
            state.clear()
            state.update(new)
        return value

    node._update_node_state = update
    replies.append((200, [RECORD], {}))
    assert (await node.execute({}))["items"] == []
    replies.append((200, [RECORD], {}))
    assert (await node.execute({}))["items"] == []
    # The published schema uses date precision, so content changes on the same
    # date must also wake the agent.
    updated = {**RECORD, "inquiry": "Requested financing"}
    new = {**RECORD, "_id": LEAD}
    replies.extend([(200, [updated], {"mapp-has-more": "true"}), (200, [new], {})])
    output = await node.execute({})
    assert output["items"] == [updated, new]
    assert requests[-1].url.params["skip"] == "100"
    assert requests[-1].url.params["sort"] == "updated_at"
    assert walcu.WalcuCRMNode.should_propagate_output(output, {"operation": operation})
    event = node.resolve_agent_event(output)
    assert "Walcu CRM" in event["text"] and CLIENT in event["text"] and "dealer-1" in event["text"]
    replies.append((200, [updated, new], {}))
    assert (await node.execute({}))["items"] == []
    node._config.config.search = "Madrid"
    replies.append((200, [updated, new], {}))
    assert (await node.execute({}))["items"] == []
    assert requests[-1].url.params["search"] == "Madrid"


def test_walcu_crm_poll_scope_ignores_canvas_and_schedule_metadata():
    base = {"operation": "on_client_changed", "search": "Alex"}
    assert poll_scope(walcu.WalcuCRMNode, base) == poll_scope(walcu.WalcuCRMNode, {**base, "label": "Cosmetic", "schedule_id": "new-schedule"})
    assert poll_scope(walcu.WalcuCRMNode, base) != poll_scope(walcu.WalcuCRMNode, {**base, "search": "Madrid"})


@pytest.mark.parametrize("field,value", [("dealer_id", "../bad"), ("dealer_id", "x/y"), ("username", "a:b"), ("password", "secret\n")])
async def test_walcu_crm_invalid_credential_refused_before_http(transport, field, value):
    with pytest.raises(ValueError):
        await run("list_clients", auth={**AUTH, field: value})
    assert transport[0] == []


@pytest.mark.parametrize("bad", ["../bad", "x/y", "x?foo=bar", "https://elsewhere.test", "x%2Fy"])
async def test_walcu_crm_invalid_path_id_refused_before_http(transport, bad):
    with pytest.raises(ValueError):
        await run("get_client", {"client_id": bad})
    assert transport[0] == []


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_walcu_crm_preserves_provider_error(transport, status):
    transport[1].append((status, {"error": "provider rejected request"}, {}))
    with pytest.raises(ValueError, match=f"HTTP {status}.*provider rejected request"):
        await run("list_clients")
    assert len(transport[0]) == 1


async def test_walcu_crm_manual_credential_defaults_and_connection_evidence(transport):
    assert walcu.WalcuCRMBasicCredential.model_validate({k: v for k, v in AUTH.items() if k != "credential_type"}).credential_type == walcu.TYPE
    transport[1].append((200, [RECORD], {}))
    result = await collect_evidence(node_type="automation-walcu-crm", credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001", pool=None)
    assert result.reachable is True and result.samples
    assert result.samples[0].label == "Alex Smith"


async def test_walcu_crm_client_picker_paginates_and_searches(transport):
    transport[1].append((200, [RECORD], {"mapp-has-more": "true"}))
    output = await walcu.WalcuCRMNode.load_field_options("client_id", AUTH, page_token="100", search="Alex")
    assert output == {"options": [{"value": CLIENT, "label": "Alex Smith"}], "next_page_token": "101"}
    assert dict(transport[0][-1].url.params) == {"skip": "100", "limit": "100", "search": "Alex"}


async def test_walcu_crm_picker_labels_are_not_provider_inputs(transport):
    transport[1].append((200, RECORD, {}))
    await run("create_task", {"client_id": CLIENT, "description": "Call Alex",
        "client_id__label": "Alex Smith", "credentialIds": {"walcu_crm_basic": "saved-credential"}})
    assert json.loads(transport[0][-1].content) == {
        "dealer_id": "dealer-1", "client_id": CLIENT, "description": "Call Alex"}


async def test_walcu_crm_patch_preserves_null_and_from(transport):
    patch = [{"op": "replace", "path": "/custom", "value": None},
             {"op": "copy", "path": "/description", "from_path": "/custom", "value": None},
             {"op": "remove", "path": "/inquiry", "value": None}]
    transport[1].append((200, RECORD, {}))
    await run("update_salelead", {"salelead_id": LEAD, "patch": patch})
    assert json.loads(transport[0][-1].content) == [
        {"op": "replace", "path": "/custom", "value": None},
        {"op": "copy", "path": "/description", "from": "/custom"}, {"op": "remove", "path": "/inquiry"}]


async def test_walcu_crm_incomplete_poll_does_not_advance_state(transport):
    node = NodeFactory.create_node(node_id="walcu-poll", node_type="automation-walcu-crm",
        node_data={"config": {"operation": "on_client_changed"}, "credentials": AUTH})
    node._update_node_state = AsyncMock()
    transport[1].extend([(200, [RECORD], {"mapp-has-more": "true"}), (200, [], {"mapp-has-more": "true"})])
    with pytest.raises(ValueError, match="empty page"):
        await node.execute({})
    node._update_node_state.assert_not_called()
