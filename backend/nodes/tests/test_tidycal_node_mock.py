"""Contract-derived request and credential regressions; no account or live network."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import tidycal_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-tidycal-personal-token"
CASES = json.loads((Path(__file__).parent / "fixtures/tidycal/requests.json").read_text())["cases"]


def node(config):
    return NodeFactory.create_node(node_id="tidycal-fixture", node_type="automation-tidycal",
        node_data={"config": config, "credentials": {"credential_type": "tidycal_personal_token", "api_token": TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, content=json.dumps(reply), headers={"Content-Type": "application/json"})
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_each_request_matches_provider_contract(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", **case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.scheme == "https" and request.url.host == "tidycal.com"
    assert request.url.path == "/api" + case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == case["body"]


@pytest.mark.asyncio
async def test_payment_date_filters_use_provider_wire_names(monkeypatch):
    requests = transport(monkeypatch, {"data": []})
    await node({"operation": "list_payments", "from": "2026-10-20", "to": "2026-10-21", "status": "completed"}).execute({})
    assert dict(requests[0].url.params) == {"from": "2026-10-20", "to": "2026-10-21", "status": "completed", "page": "1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 429, 500])
async def test_provider_errors_preserve_message_without_echoing_token(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status,
        json={"message": "Rejected: " + TOKEN}, headers={"Retry-After": "60"}))
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert result["message"] == "Rejected: [redacted]" and result["retry_after"] == "60"
    assert len(requests) == 1
    from nodes.core.connection_evidence import _ProviderRefused, _raise_if_error_envelope
    with pytest.raises(_ProviderRefused, match="HTTP " + str(status)):
        _raise_if_error_envelope(result)


@pytest.mark.asyncio
async def test_uncertain_write_never_retries(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("no response", request=request)
    requests = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="before retrying a write"):
        await node({"operation": "cancel_booking", "booking_id": 7}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, "not an object", 7])
async def test_unexpected_json_does_not_prove_connection(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="JSON object or list"):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
async def test_both_documented_pagination_envelopes_preserved(monkeypatch):
    for payload in [
        {"data": [{"id": 7}], "current_page": 1, "next_page_url": "https://tidycal.com/api/bookings?page=2"},
        {"data": [], "links": {"next": None}, "meta": {"last_page": 1}},
    ]:
        requests = transport(monkeypatch, payload)
        result = await node({"operation": "list_bookings"}).execute({})
        assert result == {"status": "success", **payload}
        assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"name": "John"}, {"name": "", "email": "john@example.com"}])
async def test_unknown_account_shape_cannot_prove_connection(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="recognizable account"):
        await node({"operation": "get_account"}).execute({})


def test_manual_credential_default_and_identity_evidence():
    credential = native.TidyCalPersonalToken(api_token=TOKEN)
    assert credential.credential_type == "tidycal_personal_token"
    assert native.TidyCalNode.connection_evidence.identity_operation == "get_account"
    assert native.TidyCalPersonalToken.model_fields["credential_type"].is_required() is False
    for bad in ["Bearer token", "https://tidycal.com", "<token>", "line\nbreak"]:
        with pytest.raises(ValidationError):
            native.TidyCalPersonalToken(api_token=bad)


@pytest.mark.parametrize("config", [
    {"operation": "get_booking", "booking_id": "../me"},
    {"operation": "get_booking", "booking_id": True},
    {"operation": "get_booking", "booking_id": 0},
    {"operation": "list_contacts", "page": 0},
    {"operation": "list_payments", "from": "not-a-date"},
    {"operation": "reschedule_booking", "booking_id": 7, "starts_at": "tomorrow"},
    {"operation": "create_contact", "name": "John", "email": "invalid"},
    {"operation": "create_contact", "name": "John", "email": "john@example.com", "timezone": "not/a/zone"},
    {"operation": "list_booking_type_timeslots", "booking_type_id": 7, "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-05-01T00:00:00Z"},
    {"operation": "list_booking_type_timeslots", "booking_type_id": 7, "starts_at": "2026-05-01T00:00:00Z", "ends_at": "2026-01-01T00:00:00Z"},
])
def test_invalid_inputs_rejected_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)
