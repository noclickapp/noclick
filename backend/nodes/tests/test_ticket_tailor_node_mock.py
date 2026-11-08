"""Ticket Tailor validation, transport, pagination and draft-update contracts."""
import json
from pathlib import Path

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest

from nodes import ticket_tailor_node as native
from nodes.core.credential_connect import validate_for_connect
from nodes.core.registry import NodeFactory

TYPE = "automation-ticket-tailor"
USER = "00000000-0000-4000-8000-000000000001"
CID = "00000000-0000-4000-8000-000000000042"
CREDENTIAL = {"credential_type": "ticket_tailor", "api_key": "synthetic-key-private", "expected_box_office_name": "Fixture Box Office"}
OVERVIEW = {"box_office_name": "Fixture Box Office", "orders_received": 3, "credits": 900}
EVENT = {"object": "event", "id": "ev_1", "name": "Fixture Event", "status": "draft", "access_code": "omit-private"}
SERIES = {"object": "event_series", "id": "es_1", "name": "Fixture Series", "status": "draft", "timezone": "Europe/London"}
OCCURRENCE = {"object": "event", "id": "ev_1", "event_series_id": "es_1", "start": {"date": "2026-11-01", "time": "10:00:00", "timezone": "Europe/London"}}


def node(operation, credential=CREDENTIAL, **args):
    return NodeFactory.create_node(node_id="ticket-tailor-fixture", node_type=TYPE, node_data={"config": {"operation": operation, **args}, "credentials": credential}, sio=None, sid=None, user_id=USER)


def page(rows, next_link=None):
    return {"data": rows, "links": {"next": next_link, "previous": None}}


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        calls.append(request)
        value = responses.pop(0)
        if callable(value):
            value = value()
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as value:
            yield value
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("limit", [True, "10", "10x", 1.5, 0, 101])
def test_real_factory_strict_integer_refusal(limit, transport):
    with pytest.raises(ValueError):
        node("list_events", limit=limit)
    assert transport[0] == []


def test_original_foreign_discriminator_before_attachment_reconciliation(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=TYPE, node_data={"config": {"operation": "check_connection"}, "credentials": {**CREDENTIAL, "credential_type": "foreign"}, "credentialIds": {"ticket_tailor": CID}}, sio=None, sid=None)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_actual_visible_only_connect_named_box_office_not_ping(transport):
    transport[1].append(OVERVIEW)
    verdict = await validate_for_connect(credential_type="ticket_tailor", credential_data={key: value for key, value in CREDENTIAL.items() if key != "credential_type"}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == "ticket_tailor"
    assert verdict.evidence.account_label == "Fixture Box Office" and verdict.evidence.reachable is True
    assert transport[0][0].url.path == "/v1/overview"
    assert transport[0][0].headers["Authorization"] == "Basic c3ludGhldGljLWtleS1wcml2YXRlOg=="


@pytest.mark.asyncio
async def test_actual_events_page_typed_limit_projection_and_cursor(transport):
    transport[1].extend([OVERVIEW, page([EVENT], "/v1/events?starting_after=ev_1")])
    result = await node("list_events", limit=10).execute({})
    assert transport[0][-1].url.params["limit"] == "10" and len(transport[0]) == 2
    assert result["data"]["next_cursor"] == "ev_1" and "omit-private" not in repr(result)
    assert "credits" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["https://foreign.example/v1/events?starting_after=ev_1", "/v1/orders?starting_after=ev_1", "/v1/events?starting_after=ev_other", "/v1/events?starting_after=ev_1&starting_after=ev_2"])
async def test_cursor_links_cannot_be_followed_or_change_scope(transport, link):
    transport[1].extend([OVERVIEW, page([EVENT], link)])
    with pytest.raises(ValueError):
        await node("list_events").execute({})
    assert len(transport[0]) == 2


@pytest.mark.asyncio
async def test_exact_ticket_parent_and_sensitive_fields_omitted(transport):
    ticket = {"object": "issued_ticket", "id": "it_1", "event_id": "ev_1", "status": "valid", "email": "omit@example.test", "barcode": "omit-secret"}
    transport[1].extend([OVERVIEW, EVENT, ticket])
    result = await node("get_issued_ticket", event_id="ev_1", ticket_id="it_1").execute({})
    assert result["data"] == {"object": "issued_ticket", "id": "it_1", "event_id": "ev_1", "status": "valid"}
    transport[1].extend([OVERVIEW, EVENT, {**ticket, "event_id": "ev_other"}])
    with pytest.raises(ValueError, match="outside"):
        await node("get_issued_ticket", event_id="ev_1", ticket_id="it_1").execute({})


@pytest.mark.asyncio
async def test_draft_series_metadata_post_is_form_encoded_and_not_readback(transport):
    transport[1].extend([OVERVIEW, SERIES, {**SERIES, "name": "Updated"}, {**SERIES, "name": "Updated"}])
    result = await node("update_draft_series", event_series_id="es_1", name="Updated").execute({})
    write = transport[0][2]
    assert write.method == "POST" and write.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert parse_qs(write.content.decode()) == {"name": ["Updated"]}
    assert result["data"]["readback_verified"] is False


@pytest.mark.asyncio
async def test_published_series_never_receives_write(transport):
    transport[1].extend([OVERVIEW, {**SERIES, "status": "published"}])
    with pytest.raises(ValueError, match="draft"):
        await node("update_draft_series", event_series_id="es_1", name="Updated").execute({})
    assert all(request.method == "GET" for request in transport[0])


@pytest.mark.asyncio
async def test_publication_during_metadata_write_is_not_success(transport):
    transport[1].extend([OVERVIEW, SERIES, {**SERIES, "name": "Updated"}, {**SERIES, "status": "published"}])
    with pytest.raises(ValueError, match="reconcile"):
        await node("update_draft_series", event_series_id="es_1", name="Updated").execute({})


@pytest.mark.asyncio
async def test_malformed_or_missing_page_boundary_is_not_completion(transport):
    transport[1].extend([OVERVIEW, {"data": [EVENT], "links": {}}])
    with pytest.raises(ValueError):
        await node("list_events").execute({})


@pytest.mark.asyncio
async def test_occurrence_update_requires_exact_parent_and_uses_documented_local_dates(transport):
    transport[1].extend([OVERVIEW, SERIES, OCCURRENCE, OCCURRENCE, SERIES])
    await node("update_draft_occurrence", event_series_id="es_1", occurrence_id="ev_1", start_date="2026-11-01", start_time="10:00:00", end_date="2026-11-01", end_time="11:00:00").execute({})
    write = next(request for request in transport[0] if request.method == "POST")
    assert write.url.path == "/v1/event_series/es_1/events/ev_1"
    assert set(parse_qs(write.content.decode())) == {"start_date", "start_time", "end_date", "end_time"}


@pytest.mark.asyncio
async def test_actual_native_picker_requires_parent_before_request(transport):
    with pytest.raises(ValueError):
        await native.TicketTailorNode.load_field_options("ticket_id", CREDENTIAL, context={})
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_safe_error_no_secret_or_provider_body(transport, status):
    transport[1].append(httpx.Response(status, json={"message": CREDENTIAL["api_key"]}))
    with pytest.raises(ValueError) as error:
        await node("check_connection").execute({})
    assert CREDENTIAL["api_key"] not in str(error.value)




# Verbatim examples from the provider's published OpenAPI description:
# https://app.tickettailor-stitching.com/openapi.yml?97074ff8cbe67793
@pytest.mark.parametrize("filename,kind,parents", [
    ("Event", "event", {}),
    ("EventSeries", "event_series", {}),
    ("EventOccurrence", "event", {"series_id": "es_1"}),
    ("Order", "order", {"event_id": "ev_40980"}),
])
def test_documented_resource_examples(filename, kind, parents):
    raw = json.loads((Path(__file__).parent / "fixtures" / "ticket-tailor" / (filename + ".json")).read_text())
    result = native._record(raw, kind, resource_id=raw["id"], **parents)
    if filename in {"Event", "EventSeries"}:
        assert result["venue"] == {"name": "Flower festival gardens", "country": "GB", "postal_code": "SW1 3BR"}
    if kind == "order":
        assert result["currency"] == {"code": "gbp", "base_multiplier": 100}
        assert "total_paid" not in result
        assert "buyer_details" not in result and "issued_tickets" not in result
        assert native._record({**raw, "total_paid": 100}, kind, **parents)["total_paid"] == 100
        with pytest.raises(ValueError):
            native._record({**raw, "currency": "gbp"}, kind, **parents)
        with pytest.raises(ValueError):
            native._record({**raw, "total_paid": "100"}, kind, **parents)
