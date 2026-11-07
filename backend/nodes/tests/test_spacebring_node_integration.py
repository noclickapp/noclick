"""Native Spacebring factory, connect, parent, paging and write fixtures.

Only synthetic credentials reach httpx MockTransport; no live API calls are made.
"""
import base64
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import spacebring_node as wire
from nodes.spacebring_node import SpacebringNode, SpacebringBasicCredential, SpacebringFullConfig

CID, USER, NETWORK, LOCATION, RESOURCE, BOOKING, MEMBER = [f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 8)]
KEY = {"credential_type": "spacebring_basic", "client_id": "SYNTHETIC_SB_CLIENT", "client_secret": "SYNTHETIC_SB_SECRET", "network_id": NETWORK}
LOCATION_ROW = {"id": LOCATION, "networkRef": NETWORK, "title": "Owned Test Location"}
RESOURCE_ROW = {"id": RESOURCE, "networkRef": NETWORK, "locationRef": LOCATION, "title": "Owned Test Resource", "description": "Before", "type": "room"}
BOOKING_ROW = {"id": BOOKING, "resourceRef": RESOURCE, "startDate": "2026-10-01T10:00:00Z", "endDate": "2026-10-01T11:00:00Z",
    "createDate": "2026-09-30T10:00:00Z", "attendees": [], "memo": "Before", "userOwner": {"email": "PRIVATE_EMAIL"}, "payments": [{"private": "PRIVATE_PAYMENT"}]}


def fake_wire(monkeypatch, handler):
    real = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        return real(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(wire.httpx, "AsyncClient", client)


def assert_customer_request(request):
    assert str(request.url).startswith(wire.ORIGIN + "/")
    assert request.headers["spacebring-network-id"] == NETWORK
    assert request.headers["authorization"] == "Basic " + base64.b64encode((KEY["client_id"] + ":" + KEY["client_secret"]).encode()).decode()
    assert KEY["client_id"] not in str(request.url) and KEY["client_secret"] not in str(request.url)


async def native_operation(monkeypatch, operation, arguments=None):
    from nodes.core.run_op import run_node_operation
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", AsyncMock(return_value=dict(KEY)))
    # Admission belongs to staging's shared run seam, independent of this provider.
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))
    return await run_node_operation(node_type="automation-spacebring", operation=operation, arguments=arguments or {},
        user_id=USER, credential_id=CID, pool=object())


@pytest.mark.asyncio
async def test_actual_native_connect_identifies_returned_network_and_rejects_wrong_network(monkeypatch):
    from nodes.core.credential_connect import validate_for_connect
    from nodes.core.connection_evidence import collect_evidence
    match = True
    def response(request):
        assert_customer_request(request)
        assert request.method == "GET" and request.url.path == "/networks/v1"
        return httpx.Response(200, json={"networks": [{"id": NETWORK if match else LOCATION, "title": "Owned Test Network"}]})
    fake_wire(monkeypatch, response)
    evidence = await collect_evidence(node_type="automation-spacebring", credential_data=dict(KEY), user_id=USER)
    assert evidence.reachable is True and evidence.account_label == "Owned Test Network" and SpacebringNode.connection_evidence.proves == "account"
    monkeypatch.setattr("nodes.core.credential_connect._collect_evidence", collect_evidence)
    verdict = await validate_for_connect(credential_type="spacebring_basic", credential_data=dict(KEY), user_id=USER)
    assert verdict.ok and verdict.evidence.account_label == "Owned Test Network"
    match = False
    evidence = await collect_evidence(node_type="automation-spacebring", credential_data=dict(KEY), user_id=USER)
    assert evidence.reachable is not True and evidence.account_label is None


@pytest.mark.asyncio
async def test_actual_native_resource204_and_booking200_metadata_readbacks(monkeypatch):
    resource, booking, writes = dict(RESOURCE_ROW), dict(BOOKING_ROW), []
    def response(request):
        assert_customer_request(request)
        if request.method == "PATCH":
            body = json.loads(request.content)
            writes.append((request.url.path, body))
            if request.url.path == "/resources/v1/" + RESOURCE:
                assert body == {"resource": {"description": "Changed"}}
                resource.update(body["resource"])
                return httpx.Response(204)
            assert body == {"booking": {"memo": "Changed", "sendUpdates": "none"}, "updateRepeatingScope": "singleOccurrence"}
            booking.update(memo=body["booking"]["memo"])
        if request.url.path == "/locations/v1/" + LOCATION:
            return httpx.Response(200, json={"location": LOCATION_ROW})
        if request.url.path == "/resources/v1/" + RESOURCE:
            return httpx.Response(200, json={"resource": resource})
        return httpx.Response(200, json={"booking": booking})
    fake_wire(monkeypatch, response)
    target = {"location_id": LOCATION, "resource_id": RESOURCE}
    result = await native_operation(monkeypatch, "update_resource_metadata", {**target, "description": "Changed"})
    assert result["data"]["resource"]["description"] == "Changed" and result["data"]["readback_verified"] is True
    result = await native_operation(monkeypatch, "update_booking_metadata", {**target, "booking_id": BOOKING, "memo": "Changed"})
    assert result["data"]["booking"]["memo"] == "Changed" and result["data"]["readback_verified"] is True
    assert len(writes) == 2 and "PRIVATE_" not in str(result)


@pytest.mark.asyncio
async def test_parent_refusal_precedes_metadata_write(monkeypatch):
    calls = []
    def response(request):
        calls.append((request.method, request.url.path))
        body = {"location": LOCATION_ROW} if request.url.path.startswith("/locations/") else {"resource": {**RESOURCE_ROW, "locationRef": MEMBER}}
        return httpx.Response(200, json=body)
    fake_wire(monkeypatch, response)
    result = await native_operation(monkeypatch, "update_resource_metadata", {"location_id": LOCATION, "resource_id": RESOURCE, "title": "Changed"})
    assert result["status"] == "error" and all(method == "GET" for method, _ in calls)


@pytest.mark.asyncio
async def test_native_paging_uses_same_filters_and_refuses_scope_or_repeat(monkeypatch):
    calls = []
    native_cursor = "opaque+/=="
    def response(request):
        if request.url.path.startswith("/locations/"):
            return httpx.Response(200, json={"location": LOCATION_ROW})
        calls.append(request)
        assert request.url.params["locationRef"] == LOCATION and request.url.params["limit"] == "1"
        if "nextPageToken" in request.url.params:
            assert request.url.params["nextPageToken"] == native_cursor
            return httpx.Response(200, json={"resources": [RESOURCE_ROW]})
        return httpx.Response(200, json={"resources": [RESOURCE_ROW], "nextPageToken": native_cursor, "searchQueryNext": "https://foreign.invalid"})
    fake_wire(monkeypatch, response)
    arguments = {"location_id": LOCATION, "limit": 1}
    first = await native_operation(monkeypatch, "list_resources", arguments)
    token = first["data"]["next_page_token"]
    assert token and first["data"]["has_more"] is True
    second = await native_operation(monkeypatch, "list_resources", {**arguments, "page_token": token})
    assert second["data"]["has_more"] is False and len(calls) == 2
    wrong = await native_operation(monkeypatch, "list_resources", {**arguments, "limit": 2, "page_token": token})
    assert wrong["status"] == "error" and len(calls) == 2
    key = dict(KEY)
    with pytest.raises(ValueError):
        await SpacebringNode.load_field_options("resource_id", key, {"location_id": LOCATION, "page_token": token})
    binding = wire.scope(key, "list_resources", {"locationRef": LOCATION, "limit": 1})
    for bad in ("https://foreign.invalid", True, "not-json"):
        with pytest.raises(ValueError):
            wire.decode_page(bad, binding)
    replacement = {**KEY, "client_secret": "ROTATED_SECRET"}
    with pytest.raises(ValueError):
        wire.decode_page(token, wire.scope(replacement, "list_resources", {"locationRef": LOCATION, "limit": 1}))
    repeated = 0
    def repeat_response(request):
        nonlocal repeated
        if request.url.path.startswith("/locations/"):
            return httpx.Response(200, json={"location": LOCATION_ROW})
        repeated += 1
        return httpx.Response(200, json={"resources": [RESOURCE_ROW], "nextPageToken": native_cursor})
    # Install another transport from the actual original client, not the previous wrapper.
    monkeypatch.undo()
    fake_wire(monkeypatch, repeat_response)
    repeated_result = await native_operation(monkeypatch, "list_resources", {**arguments, "page_token": token})
    assert repeated_result["status"] == "error" and repeated == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,uncertain", [(202, True), (200, True), (403, False), (429, True), (503, True)])
async def test_write_uncertainty_native_type_privacy_and_no_replay(monkeypatch, status, uncertain):
    writes = []
    def response(request):
        if request.method == "PATCH":
            writes.append(request)
            return httpx.Response(status, json={"type": "syntheticRejection", "message": KEY["client_secret"] + " PRIVATE_MEMBER"})
        return httpx.Response(200, json={"location": LOCATION_ROW} if request.url.path.startswith("/locations/") else {"resource": RESOURCE_ROW})
    fake_wire(monkeypatch, response)
    result = await native_operation(monkeypatch, "update_resource_metadata", {"location_id": LOCATION, "resource_id": RESOURCE, "title": "Changed"})
    assert result["status"] == "error" and result["write_outcome_uncertain"] is uncertain and len(writes) == 1
    assert result["provider_type"] == "syntheticRejection" and "PRIVATE_MEMBER" not in str(result) and KEY["client_secret"] not in str(result)


@pytest.mark.asyncio
async def test_availability_post_is_read_only_and_requires_boolean(monkeypatch):
    calls = []
    def response(request):
        calls.append(request)
        if request.method == "POST":
            assert request.url.path.endswith("/availability")
            assert json.loads(request.content) == {"startDate": "2026-10-01T10:00:00Z", "endDate": "2026-10-01T11:00:00Z", "quantity": 1}
            return httpx.Response(200, json={"available": False, "reason": {"code": "capacityExceeded", "message": "PRIVATE_TEXT"}})
        return httpx.Response(200, json={"location": LOCATION_ROW} if request.url.path.startswith("/locations/") else {"resource": RESOURCE_ROW})
    fake_wire(monkeypatch, response)
    result = await native_operation(monkeypatch, "check_resource_availability", {"location_id": LOCATION, "resource_id": RESOURCE,
        "start_time": "2026-10-01T10:00:00Z", "end_time": "2026-10-01T11:00:00Z"})
    assert result["data"]["available"] is False and result["data"]["reason_code"] == "capacityExceeded"
    assert "PRIVATE_TEXT" not in str(result) and sum(request.method == "POST" for request in calls) == 1


def test_actual_models_selected_output_and_bounded_json():
    for key, value in (("client_secret", "SECRET_SENTINEL\n"), ("client_id", "secret:id"), ("network_id", "https://foreign.invalid")):
        with pytest.raises(ValueError) as error:
            SpacebringBasicCredential.model_validate({**KEY, key: value})
        assert "SECRET_SENTINEL" not in str(error.value) and KEY["client_secret"] not in str(error.value)
    with pytest.raises(ValueError):
        SpacebringFullConfig.model_validate({"config": {"operation": "list_locations", "limit": True}})
    with pytest.raises(ValueError):
        SpacebringFullConfig.model_validate({"config": {"operation": "update_booking_metadata", "location_id": LOCATION,
            "resource_id": RESOURCE, "booking_id": BOOKING, "memo": "Changed", "sendUpdates": "all"}})
    for payload in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b' ' * (wire.MAX_BODY + 1)):
        with pytest.raises(ValueError):
            wire.parse_json(payload)
    with pytest.raises(ValueError):
        wire.safe_selected({"title": KEY["client_secret"]}, KEY)
    member = wire.selected({"id": MEMBER, "locationRef": LOCATION, "type": "member", "status": "approved", "user": {"email": "PRIVATE_EMAIL"}}, "membership", data=KEY, location=LOCATION)
    assert "PRIVATE_EMAIL" not in str(member) and "user" not in member
