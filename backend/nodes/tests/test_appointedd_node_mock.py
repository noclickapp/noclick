"""Appointedd request contracts and schema-backed poll deliveries; no live account."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import appointedd_node as api

ID = "0123456789abcdef01234567"
AUTH = {"credential_type": "appointedd_access_token", "access_token": "fixture-appointedd-bearer"}
FIXTURES = Path(__file__).parent / "fixtures" / "appointedd"


def node(operation, **fields):
    config = api.AppointeddNodeConfig.model_validate({"config": {"operation": operation, **fields}, "credentials": AUTH})
    return api.AppointeddNode(node_id="appointedd-test", node_type="automation-appointedd", node_data={}, config=config)


def payload(kind):
    return json.loads((FIXTURES / (kind + ".json")).read_text())


@pytest.fixture
def wire(monkeypatch):
    requests, responses = [], []
    async def send(request):
        requests.append(request)
        assert request.url.host == "json-api.appointedd.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        status, body = responses.pop(0)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    monkeypatch.setattr(api, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(send), **kw))
    return requests, responses


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path", [
    ("get_account", {"account_id": ID}, "GET", f"/v2/accounts/{ID}"),
    ("get_booking", {"booking_id": ID}, "GET", f"/v2/bookings/{ID}"),
    ("get_customer", {"customer_id": ID}, "GET", f"/v2/customers/{ID}"),
    ("get_event", {"event_id": ID}, "GET", f"/v2/events/{ID}"),
    ("get_service", {"service_id": ID}, "GET", f"/v2/services/{ID}"),
    ("get_resource", {"resource_id": ID}, "GET", f"/v2/resources/{ID}"),
    ("cancel_booking", {"booking_id": ID}, "POST", f"/v2/bookings/{ID}/cancel"),
    ("cancel_event", {"event_id": ID}, "POST", f"/v2/events/{ID}/cancel"),
    ("delete_customer", {"customer_id": ID}, "DELETE", f"/v2/customers/{ID}"),
])
async def test_routes(wire, operation, fields, method, path):
    requests, responses = wire
    responses.append((204 if method != "GET" else 200, {"data": {"id": ID}}))
    await node(operation, **fields).execute({})
    assert (requests[0].method, requests[0].url.path) == (method, path)
    assert not requests[0].content


@pytest.mark.asyncio
async def test_customer_create_and_patch_do_not_wrap_data(wire):
    requests, responses = wire
    responses.extend([(200, {"data": {}}), (200, {"data": {}})])
    await node("create_customer", account_id=ID, attributes={"firstname": "Ada", "lastname": "Lovelace"}).execute({})
    await node("update_customer", customer_id=ID, attributes={"email": None, "tags": []}).execute({})
    assert json.loads(requests[0].content) == {"attributes": {"firstname": "Ada", "lastname": "Lovelace"}, "relationships": {"account": {"data": {"type": "Account", "id": ID}}}}
    assert json.loads(requests[1].content) == {"attributes": {"email": None, "tags": []}}


@pytest.mark.asyncio
async def test_booking_flow_bodies(wire):
    requests, responses = wire
    responses.extend([(200, {"data": {}})] * 3)
    await node("search_availability", accounts=[{"accountId": ID, "serviceId": ID}], ranges=[{"start": "2026-05-01T10:00:00Z", "end": "2026-05-01T11:00:00Z"}]).execute({})
    await node("create_reservation", account_id=ID, service_id=ID, start="2026-05-01T10:00:00Z").execute({})
    await node("create_event", account_id=ID, reservation_id=ID, participants=[{"id": ID}]).execute({})
    assert [r.url.path for r in requests] == ["/v2/availability/intervals/search", "/v2/reservations", "/v2/events"]
    assert json.loads(requests[0].content)["accounts"] == [{"accountId": ID, "serviceId": ID}]
    assert json.loads(requests[1].content)["type"] == "Reservation"
    event = json.loads(requests[2].content)
    assert event["attributes"]["participants"] == [{"type": "ExistingCustomer", "id": ID, "spaces": 1}]
    assert event["attributes"]["sendPaymentRequest"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,operation", [("bookings", "on_booking_changed"), ("customers", "on_customer_changed")])
async def test_poll_all_pages_revision_and_agent_event(wire, monkeypatch, kind, operation):
    requests, responses = wire
    first = payload(kind)
    second = deepcopy(first)
    second["data"][0]["id"] = "abcdef0123456789abcdef01"
    first["meta"]["total"] = second["meta"]["total"] = 2
    first["links"]["next"] = f"https://json-api.appointedd.com/v2/{kind}?page[after]={ID}"
    responses.extend([(200, first), (200, second)])
    watcher = node(operation, account_id=ID, updated_since="2026-05-01T00:00:00Z")
    revisions = []
    async def unseen(rows, key):
        revisions.extend(key(row) for row in rows)
        return rows
    monkeypatch.setattr(watcher, "_filter_unseen", unseen)
    result = await watcher.execute({})
    data = result.get("data", result)
    assert data["changed_count"] == 2
    assert len(set(revisions)) == 2
    assert requests[1].url.params["page[after]"] == ID
    assert requests[0].url.params["filter[accountIds]"] == ID
    assert ("filter[updatedSince]" if kind == "customers" else "filter[updated][after]") in requests[0].url.params
    event = api.AppointeddNode.resolve_agent_event(data)
    assert ID in event["text"] and ("Ada Lovelace" if kind == "customers" else "booking") in event["text"]
    assert api.AppointeddNode.should_propagate_output({"changed_count": 0}, {"operation": operation}) is False


def test_inputs_and_manual_credential():
    assert api.AppointeddTokenCredential(access_token="fixture-bearer").credential_type == "appointedd_access_token"
    for bad in ["https://example.test", "Bearer credential-value"]:
        with pytest.raises(ValidationError): api.AppointeddTokenCredential(access_token=bad)
    with pytest.raises(ValidationError): node("get_booking", booking_id="../accounts")
    with pytest.raises(ValidationError): node("update_customer", customer_id=ID, attributes={"firstname": None})


@pytest.mark.asyncio
async def test_error_is_not_evidence(wire):
    requests, responses = wire
    responses.append((401, {"message": "You are not allowed to perform this action"}))
    with pytest.raises(ValueError, match="You are not allowed"):
        await node("list_accounts").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,operation", [("bookings", "on_booking_changed"), ("customers", "on_customer_changed")])
async def test_actual_poll_baseline_new_and_updated_revision(wire, monkeypatch, kind, operation):
    _, responses = wire
    watcher = node(operation)
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    monkeypatch.setattr(watcher, "_update_node_state", update)
    original = payload(kind)
    original["meta"]["total"] = 1
    responses.append((200, original))
    first = await watcher.execute({})
    assert first["changed_count"] == 0
    added = deepcopy(original)
    added["data"].append(deepcopy(added["data"][0]))
    added["data"][1]["id"] = "abcdef0123456789abcdef01"
    added["meta"]["total"] = 2
    responses.append((200, added))
    second = await watcher.execute({})
    assert [row["id"] for row in second["changed_items"]] == ["abcdef0123456789abcdef01"]
    revised = deepcopy(added)
    revised["data"][0]["attributes"]["updated"] = "2026-05-02T10:00:00Z"
    responses.append((200, revised))
    third = await watcher.execute({})
    assert [row["id"] for row in third["changed_items"]] == [ID]
    responses.append((200, revised))
    assert (await watcher.execute({}))["changed_count"] == 0


@pytest.mark.asyncio
async def test_connection_evidence_exposes_account_names(wire):
    _, responses = wire
    responses.append((200, {"data": [{"id": ID, "type": "Account", "attributes": {"name": "Edinburgh", "slug": "edinburgh"}}], "links": {"next": None}}))
    result = await node("list_accounts").execute({})
    assert result["items"] == [{"id": ID, "name": "Edinburgh"}]
