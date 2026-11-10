"""Farmbrite request mapping and polling against its published v1 examples.

Fixture source: https://developers.farmbrite.com/openapi.json, GET /<name>,
responses.200.content.application/json.example (version 1.0.0).
"""
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.farmbrite_node import BASE_URL, TRIGGERS, FarmbriteNode, FarmbriteTokenCredential

FIXTURES = Path(__file__).parent / "fixtures" / "farmbrite"
TOKEN = "test-farmbrite-secret"
CONTRACT_ACTIONS = [
    ("list_tasks", "GET", "/tasks", None),
    ("get_task", "GET", "/tasks/GUID", "task_id"),
    ("create_task", "POST", "/tasks", None),
    ("update_task", "PUT", "/tasks/GUID", "task_id"),
    ("delete_task", "DELETE", "/tasks/GUID", "task_id"),
    ("list_contacts", "GET", "/contacts", None),
    ("get_contact", "GET", "/contacts/GUID", "contact_id"),
    ("create_contact", "POST", "/contacts", None),
    ("update_contact", "PUT", "/contacts/GUID", "contact_id"),
    ("delete_contact", "DELETE", "/contacts/GUID", "contact_id"),
    ("list_animals", "GET", "/animals", None),
    ("get_animal", "GET", "/animals/GUID", "animal_id"),
    ("create_animal", "POST", "/animals", None),
    ("update_animal", "PUT", "/animals/GUID", "animal_id"),
    ("list_orders", "GET", "/orders", None),
    ("get_order", "GET", "/orders/GUID", "order_id"),
    ("create_order", "POST", "/orders", None),
    ("update_order", "PUT", "/orders/GUID", "order_id"),
    ("list_products", "GET", "/products", None),
    ("get_product", "GET", "/products/GUID", "product_id"),
    ("list_crops", "GET", "/crops", None),
    ("get_crop", "GET", "/crops/GUID", "crop_id"),
]


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


def node(config):
    instance = object.__new__(FarmbriteNode)
    instance.node_id = "farmbrite-test"
    instance._config = FarmbriteNode.parse_config({"config": config,
        "credentials": {"credential_type": "farmbrite_token", "api_token": TOKEN}})
    instance.emit = AsyncMock()
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("name,method,path,id_field", CONTRACT_ACTIONS)
async def test_all_action_routes_and_methods(name, method, path, id_field):
    config = {"operation": name}
    if id_field:
        config[id_field] = "GUID"
    config.update({
        "create_task": {"title": "The title of your task"},
        "update_task": {"title": "Updated Task Title"},
        "create_contact": {"first_name": "Bob"},
        "update_contact": {"first_name": "Robert"},
        "create_animal": {"type": "Cow", "status": "Active"},
        "update_animal": {"type": "Bull"},
        "create_order": {"status": "Ordered", "payment_status": "Paid"},
        "update_order": {"status": "Pending Approval"},
    }.get(name, {}))
    instance = node(config)
    instance._request = AsyncMock(return_value={"data": []} if name.startswith("list_") else {"id": "GUID"})
    await instance.execute({})
    args, kwargs = instance._request.call_args
    assert args == (TOKEN, method, path)
    expected_body = {key: value for key, value in config.items() if key not in {"operation", id_field}}
    assert kwargs["body"] == (expected_body if method in {"POST", "PUT"} else None)
    assert kwargs["params"] == ({"page": 1, "limit": 25} if name.startswith("list_") else None)


@pytest.mark.asyncio
async def test_bearer_request_and_provider_envelope(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=fixture("contacts"))

    @asynccontextmanager
    async def client(*args, **kwargs):
        assert not args
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            yield http

    monkeypatch.setattr("nodes.farmbrite_node.guarded_async_client", client)
    instance = node({"operation": "list_contacts", "page": 2, "limit": 100,
        "updated_since": "2022-01-01T00:00:00"})
    output = await instance.execute({})
    assert output["total_pages"] == 5
    assert output["data"][0]["first_name"] == "Bob"
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert str(requests[0].url).startswith(BASE_URL + "/contacts?")
    assert requests[0].url.params["updated_at"] == "gte:2022-01-01 00:00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,resource", TRIGGERS.items())
async def test_documented_events_baseline_new_update_and_agent(operation, resource):
    instance = node({"operation": operation})
    response = fixture(resource)
    instance._request = AsyncMock(side_effect=lambda *a, **kw: copy.deepcopy(response))
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        new_state, result = mutator(state)
        if new_state is not None:
            state = new_state
        return result

    instance._update_node_state = update
    assert (await instance.execute({}))["data"] == []
    assert instance.trigger_produced_no_event({})
    assert (await instance.execute({}))["data"] == []
    response["data"][0]["updated_at"] = "2026-11-10 10:00:00"
    output = await instance.execute({})
    assert output["change_count"] == 1
    assert instance.trigger_emitted_event(output)
    assert "GUID" in instance.resolve_agent_event(output)["text"]
    assert (await instance.execute({}))["data"] == []
    new_row = copy.deepcopy(response["data"][0])
    new_row["id"] = "new-GUID"
    response["data"].append(new_row)
    assert (await instance.execute({}))["change_count"] == 1
    assert instance._request.call_args.kwargs["params"]["sort_by"] == "updated_at"


@pytest.mark.asyncio
async def test_poll_paginates_and_does_not_advance_state_on_repeat():
    instance = node({"operation": "on_task_changed"})
    response = fixture("tasks")
    response["total_pages"] = 2
    second = copy.deepcopy(response)
    second["data"][0]["id"] = "page2-GUID"
    instance._request = AsyncMock(side_effect=[response, second])
    instance._filter_unseen = AsyncMock(side_effect=lambda rows, id_fn: rows)
    output = await instance.execute({})
    assert output["change_count"] == 2
    assert instance._request.call_args.kwargs["params"]["page"] == 2
    instance._filter_unseen.reset_mock()
    instance._request = AsyncMock(return_value=response)
    with pytest.raises(ValueError, match="repeated"):
        await instance.execute({})
    instance._filter_unseen.assert_not_called()


@pytest.mark.asyncio
async def test_poll_refuses_incomplete_or_unversioned_records():
    instance = node({"operation": "on_task_changed"})
    instance._filter_unseen = AsyncMock()
    instance._request = AsyncMock(return_value={"data": [{"id": "GUID"}]})
    with pytest.raises(ValueError, match="updated_at"):
        await instance.execute({})
    instance._filter_unseen.assert_not_called()


@pytest.mark.parametrize("config", [
    {"operation": "get_animal", "animal_id": "../tasks"},
    {"operation": "get_animal", "animal_id": "x?admin=true"},
    {"operation": "update_task", "task_id": "GUID"},
    {"operation": "create_animal", "type": "Cow", "status": "Deceased"},
    {"operation": "create_task", "title": "x", "reference_type": "animal"},
    {"operation": "create_order", "status": "Ordered"},
    {"operation": "list_tasks", "limit": 101},
    {"operation": "create_task", "title": "x", "complete": "false"},
    {"operation": "create_task", "title": "x", "end_time": "2022-02-30 12:00"},
])
def test_invalid_configuration(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_hand_connected_token_default():
    assert FarmbriteTokenCredential(api_token=TOKEN).credential_type == "farmbrite_token"
    for invalid in ("Bearer secret", "secret\nheader", "https://farmbrite.com", "<token>"):
        with pytest.raises(ValueError):
            FarmbriteTokenCredential(api_token=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": TOKEN}), (200, {"success": False, "message": TOKEN})])
async def test_failures_redact_secret(monkeypatch, status, body):
    @asynccontextmanager
    async def client(*args, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))) as http:
            yield http

    monkeypatch.setattr("nodes.farmbrite_node.guarded_async_client", client)
    with pytest.raises(ValueError) as error:
        await FarmbriteNode._request(TOKEN, "GET", "/tasks")
    assert TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_empty_write_acknowledgement(monkeypatch):
    @asynccontextmanager
    async def client(*args, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as http:
            yield http

    monkeypatch.setattr("nodes.farmbrite_node.guarded_async_client", client)
    assert await FarmbriteNode._request(TOKEN, "DELETE", "/tasks/GUID") == {"http_status": 200}


@pytest.mark.asyncio
async def test_documented_order_line_update_keeps_existing_item_id():
    config = {"operation": "update_order", "order_id": "GUID", "status": "Pending Approval",
        "payment_status": "Due", "order_items": [{"id": "Farmbrite Order Item ID",
            "description": "Item Description", "price": 25, "product_id": "Farmbrite Product ID", "qty": 3}]}
    instance = node(config)
    instance._request = AsyncMock(return_value={})
    await instance.execute({})
    assert instance._request.call_args.kwargs["body"]["order_items"][0]["id"] == "Farmbrite Order Item ID"
    del config["order_items"][0]["id"]
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_animal_status_is_a_declared_poll_scope_and_query():
    instance = node({"operation": "on_animal_changed", "status": "Sold"})
    instance._request = AsyncMock(return_value=fixture("animals"))
    instance._filter_unseen = AsyncMock(return_value=[])
    await instance.execute({})
    assert instance._request.call_args.kwargs["params"]["status"] == "Sold"
    active = FarmbriteNode.schedule_poll_scope({"operation": "on_animal_changed", "status": "Active"})
    sold = FarmbriteNode.schedule_poll_scope({"operation": "on_animal_changed", "status": "Sold"})
    assert active != sold
    assert sold == FarmbriteNode.schedule_poll_scope({"operation": "on_animal_changed", "status": "Sold", "label": "New label"})
