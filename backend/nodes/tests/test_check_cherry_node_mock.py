"""Exercise Check Cherry requests with a local HTTP transport and synthetic credentials.

These tests pin request placement, account evidence, pagination, and provider failures
without accessing a live Check Cherry account.
"""
from contextlib import asynccontextmanager
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import check_cherry_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-check-cherry-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="check-cherry-test", node_type="automation-check-cherry",
        node_data={"config": config, "credentials": {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}})


def transport(monkeypatch, payload, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=payload)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
async def test_check_cherry_lead_evidence_and_pagination(monkeypatch):
    payload = {"data": [{"id": "42", "type": "lead", "attributes": {"first_name": "Jane", "new_field": "preserved"}}],
        "included": [], "meta": {"status": "ok", "page": 1, "total_pages": 2}}
    calls = transport(monkeypatch, payload)
    result = await node({"operation": "list_leads", "email": "jane@example.com"}).execute({})
    assert result["data"] == payload["data"] and result["included"] == []
    assert result["items"][0]["name"] == "Jane"
    assert result["next_page"] == 2
    assert native.CheckCherryNode.connection_evidence.operation == "list_leads"
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].url.host == "api.checkcherry.com"
    assert calls[0].url.path == "/api/v1/leads"
    assert calls[0].headers["Api-Key"] == TOKEN
    assert dict(calls[0].url.params) == {"page": "1", "per": "25", "email": "jane@example.com"}


@pytest.mark.asyncio
async def test_check_cherry_write_flat_body_and_ack_only_response(monkeypatch):
    calls = transport(monkeypatch, {"meta": {"status": "ok"}})
    result = await node({"operation": "add_lead_note", "lead_id": 42, "note": "Follow up", "next_follow_up_on": "2027-03-04"}).execute({})
    assert result["status"] == "success"
    assert calls[0].method == "POST" and calls[0].url.path == "/api/v1/leads/42/notes"
    assert json.loads(calls[0].content) == {"note": "Follow up", "next_follow_up_on": "2027-03-04"}
    assert not calls[0].url.query


@pytest.mark.asyncio
async def test_check_cherry_booking_nested_packages_and_default_contact(monkeypatch):
    calls = transport(monkeypatch, {"data": {"id": "10", "type": "event"}, "meta": {"status": "ok"}})
    await node({"operation": "create_booking", "contact_name": "Jane Smith", "packages": [
        {"event_type_id": "3", "starts_at_date": "2027-03-04", "starts_at_time": "14:30", "length_in_minutes": 120}]}).execute({})
    body = json.loads(calls[0].content)
    assert calls[0].method == "POST" and calls[0].url.path == "/api/v1/bookings"
    assert body["packages"][0]["starts_at_date"] == "2027-03-04"
    assert body["contact_type"] == "New Customer"
    assert "send_booking_confirmation_emails" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [200, 401, 403, 429, 500])
async def test_check_cherry_errors_are_not_success_and_redact_secrets(monkeypatch, http_status):
    calls = transport(monkeypatch, {"meta": {"status": "error"}, "message": "Permission denied " + TOKEN}, http_status)
    with pytest.raises(ValueError, match="Permission denied") as exc:
        await node({"operation": "list_leads"}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_check_cherry_response_redacts_token_and_terminal_page(monkeypatch):
    transport(monkeypatch, {"data": [], "meta": {"status": "ok", "page": 2, "total_pages": 2}, "echo": TOKEN})
    result = await node({"operation": "list_leads", "page": 2}).execute({})
    assert result["next_page"] is None and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_check_cherry_malformed_success_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, {"meta": {"status": "ok"}})
    with pytest.raises(ValueError, match="resource list"):
        await node({"operation": "list_leads"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_lead", "lead_id": -1},
    {"operation": "get_lead", "lead_id": "../events"},
    {"operation": "update_event", "event_id": 1},
    {"operation": "list_leads", "page": 0},
    {"operation": "create_appointment", "guest_name": "Jane"},
    {"operation": "create_lead"},
])
def test_check_cherry_invalid_input_fails_before_http(config):
    with pytest.raises((ValidationError, ValueError)):
        native.CheckCherryNode.parse_config({"config": config})


@pytest.mark.parametrize("key", ["https://example.com/key", "<token>", "a\nb", "Bearer secret"])
def test_check_cherry_bad_pasted_key(key):
    with pytest.raises((ValidationError, ValueError)):
        native.CheckCherryCredential(api_key=key)
