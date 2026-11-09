"""Cloudbeds native factory request and response regressions; no live account."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import cloudbeds_node as cb
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/cloudbeds/operations.json').read_text())
AUTH = {"credential_type": "cloudbeds_api_key", "api_key": "synthetic-cloudbeds-key"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=AUTH):
    return NodeFactory.create_node(node_id="cloudbeds-test", node_type="automation-cloudbeds",
        node_data={"config": config, "credentials": credentials})


@pytest.fixture
def transport(monkeypatch):
    requests = []
    replies = []
    client_type = httpx.AsyncClient

    def send(request):
        requests.append(request)
        return replies.pop(0)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return client_type(transport=httpx.MockTransport(send), **kwargs)

    monkeypatch.setattr(cb.httpx, "AsyncClient", client)
    return requests, replies


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_cloudbeds_operations_use_exact_contract_endpoint(transport, operation):
    requests, replies = transport
    case = CASES[operation]
    body = {"success": True, "data": [{"propertyID": "123", "propertyName": "Test hotel"}], "count": 1, "total": 3}
    replies.append(httpx.Response(200, json=body))
    result = await node(case["config"]).execute({})
    assert result == {**body, "status": "success"}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == "/api/v1.3" + case["path"]
    assert request.url.host == "api.cloudbeds.com"
    assert request.headers["x-api-key"] == AUTH["api_key"]
    assert AUTH["api_key"] not in str(request.url)
    values = dict(request.url.params) if request.method == "GET" else {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    for name, value in case["config"].items():
        if name != "operation":
            assert values[name] == str(value)
    if request.method != "GET":
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"


@pytest.mark.asyncio
async def test_cloudbeds_notes_encode_text_once_and_preserve_creation_id(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"success": True, "reservationNoteID": "456"}))
    note = "Arrives at 20:00 + needs café & tea"
    result = await node({"operation": "create_reservation_note", "reservationID": "123", "reservationNote": note}).execute({})
    assert result["reservationNoteID"] == "456"
    assert parse_qs(requests[0].content.decode()) == {"reservationID": ["123"], "reservationNote": [note]}


@pytest.mark.asyncio
async def test_cloudbeds_explicit_housekeeping_and_email_flags(transport):
    requests, replies = transport
    replies.extend([httpx.Response(200, json={"success": True}) for _ in range(2)])
    await node({"operation": "update_housekeeping_status", "roomID": "101-0", "roomCondition": "clean", "doNotDisturb": False}).execute({})
    assert parse_qs(requests[0].content.decode())["doNotDisturb"] == ["false"]
    await node({"operation": "update_reservation_status", "reservationID": "123", "status": "confirmed"}).execute({})
    assert parse_qs(requests[1].content.decode())["sendStatusChangeEmail"] == ["false"]


@pytest.mark.asyncio
async def test_cloudbeds_page_selection_preserves_totals_without_extra_calls(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"success": True, "data": [], "count": 0, "total": 200}))
    result = await node({"operation": "list_properties", "pageNumber": 3, "pageSize": 10}).execute({})
    assert result["total"] == 200 and result["data"] == []
    assert dict(requests[0].url.params) == {"pageNumber": "3", "pageSize": "10"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_cloudbeds_provider_rejection_is_not_success(transport):
    _, replies = transport
    replies.append(httpx.Response(200, json={"success": False, "message": "Missing permission: read:hotel"}))
    result = await node({"operation": "list_properties"}).execute({})
    assert result["status"] == "error" and result["error"] == "Missing permission: read:hotel"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"success": "true"}])
async def test_cloudbeds_malformed_envelopes_fail(transport, body):
    _, replies = transport
    replies.append(httpx.Response(200, json=body))
    with pytest.raises(ValueError, match="invalid response envelope"):
        await node({"operation": "list_properties"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_cloudbeds_http_errors_are_not_success_or_retried(transport, status):
    requests, replies = transport
    replies.append(httpx.Response(status, json={"message": "Rejected"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "list_properties"}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_guest"},
    {"operation": "create_guest_note", "guestID": "1"},
    {"operation": "create_reservation_note", "reservationID": "1"},
    {"operation": "update_reservation_status", "reservationID": "1"},
    {"operation": "update_housekeeping_status", "roomID": "101-0"},
    {"operation": "list_properties", "pageNumber": 0},
    {"operation": "list_properties", "pageSize": 101},
    {"operation": "list_available_room_types", "startDate": "not-a-date"},
    {"operation": "list_properties", "base_url": "https://example.test"},
])
def test_cloudbeds_invalid_or_incomplete_requests_fail_before_network(config):
    with pytest.raises(ValueError):
        node(config)


def test_cloudbeds_api_key_can_be_entered_by_hand():
    credential = cb.CloudbedsAPIKeyCredential(api_key="  synthetic-cloudbeds-key  ")
    assert credential.credential_type == "cloudbeds_api_key"
    assert credential.api_key == "synthetic-cloudbeds-key"
    assert cb.CloudbedsNode.connection_evidence.operation == "list_properties"
    for key in ["https://example.test/key", "<token>", "key\nheader"]:
        with pytest.raises(ValidationError):
            cb.CloudbedsAPIKeyCredential(api_key=key)
