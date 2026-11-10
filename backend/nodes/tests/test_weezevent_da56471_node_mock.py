"""Offline route, mutation, connection and poll lifecycle regressions."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import weezevent_da56471_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

HTTP_CLIENT = httpx.AsyncClient

F = Path(__file__).parent / "fixtures" / "weezevent-da56471"
CREDS = {"credential_type": native.CREDENTIAL_TYPE, "access_token": "synthetic.weezevent.token", "organization_id": 1}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, creds=None):
    return NodeFactory.create_node(node_id="fixture", node_type=native.WeezeventNode.integration_type,
        node_data={"config": config, "credentials": creds or CREDS})


def transport(monkeypatch, reply, status=200):
    requests = []
    original = HTTP_CLIENT
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        def respond(request):
            requests.append(request)
            return httpx.Response(status, json=copy.deepcopy(reply))
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("op", list(native.OPERATIONS), ids=lambda op: "weezevent-da56471-" + op)
async def test_all_operation_routes_and_auth(monkeypatch, op):
    method, path, query, fields, resource = native.OPERATIONS[op]
    cfg = {"operation": op}
    for key, field in native.CONFIG_MODELS[op].model_fields.items():
        if field.is_required():
            cfg[key] = {"event_id": 2, "attendee_id": 3, "order_id": 4, "name": "My event", "price": 15.06,
                "start_date": "2013-09-01T12:00:00Z", "barcode": "66880072260150", "first_name": "John", "last_name": "WeezDoe", "email": "john.weezdoe@weezevent.com"}[key]
    item = json.loads((F / ("order.json" if resource == "orders" else "attendee.json")).read_text())
    body = [item] if resource in {"events", "rates", "attendees", "orders"} else {"id": 1}
    requests = transport(monkeypatch, body)
    n = node(cfg)
    async def unseen(items, key):
        assert key(items[0])
        return items
    n._filter_unseen = unseen
    result = await n.execute({})
    assert result and len(requests) == 1
    expected = path.replace("{organization_id}", "1")
    for key, value in cfg.items(): expected = expected.replace("{" + key + "}", str(value))
    assert str(requests[0].url).split("?")[0] == native.BASE + expected
    assert requests[0].method == method
    assert requests[0].headers["Authorization"] == "Bearer " + CREDS["access_token"]
    if method == "POST":
        payload = json.loads(requests[0].content)
        if op == "swap_resale_ticket":
            assert payload == {"ticket": {"barcode": cfg["barcode"]}, "customer": {k: cfg[k] for k in ("first_name", "last_name", "email")}}
        else: assert payload == {k: cfg[k] for k in fields if k in cfg}


@pytest.mark.asyncio
async def test_filters_keep_false_and_connection_uses_owned_events(monkeypatch):
    requests = transport(monkeypatch, [{"id": 13718, "name": "My event"}])
    choices = await native.WeezeventNode.load_field_options("event_id", CREDS)
    assert choices == {"options": [{"value": "13718", "label": "My event"}]}
    assert requests[0].url.path == "/ticket/organizations/1/events"
    await node({"operation": "list_attendees", "event_id": 1, "scan_status": False, "modified__gt": "2021-04-26"}).execute({})
    assert dict(requests[-1].url.params) == {"scan_status": "false", "modified__gt": "2021-04-26"}
    assert native.WeezeventCredential.model_validate({k:v for k,v in CREDS.items() if k != "credential_type"}).credential_type == native.CREDENTIAL_TYPE


@pytest.mark.asyncio
@pytest.mark.parametrize("op,kind,id_field", [("on_new_or_updated_attendee", "attendee", "id"), ("on_new_or_updated_order", "order", "id_transaction")])
async def test_poll_baseline_changes_dedup_scope_and_agent(monkeypatch, op, kind, id_field):
    item = json.loads((F / (kind + ".json")).read_text())
    replies = [item]
    requests = transport(monkeypatch, replies)
    n = node({"operation": op, "event_id": 1})
    state = {}
    async def update(mutator, **kwargs):
        new, value = mutator(copy.deepcopy(state))
        if new is not None: state.clear(); state.update(new)
        return value
    n._update_node_state = update
    first = await n.execute({})
    assert first["changed_count"] == 0
    assert not n.should_propagate_output(first, {"operation": op})
    assert await n.execute({}) == first
    # Change a documented field on the same identity: updates fire once.
    item["first_name" if kind == "attendee" else "buyer_first_name"] = "Updated"
    transport(monkeypatch, [item])
    changed = await n.execute({})
    assert changed["changed_count"] == 1
    event = n.resolve_agent_event(changed)
    assert "Updated" in event["text"] and str(item[id_field]) in event["text"] and "event 1" in event["text"]
    assert (await n.execute({}))["changed_count"] == 0
    same = {"operation": op, "event_id": 1}
    assert poll_scope(native.WeezeventNode, same) == poll_scope(native.WeezeventNode, {**same, "goal": "cosmetic"})
    assert poll_scope(native.WeezeventNode, same) != poll_scope(native.WeezeventNode, {**same, "event_id": 2})
    n._config = native.WeezeventNode.parse_config({"config": {**same, "event_id": 2}, "credentials": CREDS})
    assert (await n.execute({}))["changed_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
async def test_errors_are_not_success(monkeypatch, status):
    transport(monkeypatch, {"detail": "Provider rejected request"}, status)
    with pytest.raises(ValueError, match="Provider rejected request"):
        await node({"operation": "list_events"}).execute({})


@pytest.mark.asyncio
async def test_bad_shapes_and_dates_fail(monkeypatch):
    requests = transport(monkeypatch, {"unexpected": True})
    with pytest.raises(ValueError, match="list"):
        await node({"operation": "list_events"}).execute({})
    with pytest.raises(ValueError, match="ISO 8601"):
        await node({"operation": "create_event", "name": "My event", "start_date": "not a date"}).execute({})
    assert len(requests) == 1
    with pytest.raises(ValidationError): native.WeezeventCredential.model_validate({**CREDS, "access_token": "Bearer token"})


@pytest.mark.asyncio
@pytest.mark.parametrize("barcode", [".", ".."])
async def test_barcode_dot_segments_cannot_change_the_route(monkeypatch, barcode):
    requests = transport(monkeypatch, {"id": 1})
    with pytest.raises(ValueError, match="resource identifier"):
        await node({"operation": "get_attendee_by_barcode", "event_id": 1, "barcode": barcode}).execute({})
    assert not requests
