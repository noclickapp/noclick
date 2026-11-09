"""Local regressions for the Bookings Graph contract and Microsoft family OAuth.

These tests use the real factory and mocked HTTP, without logging in or creating
appointments. They pin provider field names and failure behavior at the wire.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import microsoft_bookings_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-bookings-token"
BUSINESS = "Contosolunchdelivery@contoso.com"
DOCUMENTED = json.loads((Path(__file__).parent / "fixtures/microsoft-bookings/documented_responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="bookings-test", node_type="automation-microsoft-bookings",
        node_data={"config": config, "credentials": {"access_token": TOKEN, **credential}})


def transport(monkeypatch, status=200, body=None):
    requests = []
    real_client = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
async def test_account_evidence_lists_tenant_businesses_without_extra_arguments(monkeypatch):
    requests = transport(monkeypatch, body={"value": [{"id": BUSINESS, "displayName": "Contoso lunch delivery"}]})
    result = await node({"operation": "list_businesses"}).execute({})
    assert result["items"][0]["displayName"] == "Contoso lunch delivery"
    assert result["count"] == 1 and len(requests) == 1
    assert str(requests[0].url) == "https://graph.microsoft.com/v1.0/solutions/bookingBusinesses"
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert requests[0].content == b""


@pytest.mark.asyncio
async def test_create_appointment_uses_documented_start_end_and_customer_reference(monkeypatch):
    requests = transport(monkeypatch, status=201, body={"id": "AAMkADKnAAA="})
    result = await node({"operation": "create_appointment", "business_id": BUSINESS,
        "service_id": "57da6774-a087-4d69-b0e6-6fb82c339976", "start": "2018-05-01T12:00:00+00:00",
        "end": "2018-05-01T12:30:00+00:00", "customer_name": "Jordan Miller", "customer_email": "jordanm@contoso.com",
        "customer_id": "7ed53fa5-9ef2-4f2f-975b-27447440bc09", "staff_member_ids": ["8ee1c803-a1fa-406d-8259-7ab53233f148"],
        "opt_out_of_customer_email": True}).execute({})
    body = json.loads(requests[0].content)
    assert body == {"@odata.type": "#microsoft.graph.bookingAppointment",
        "serviceId": "57da6774-a087-4d69-b0e6-6fb82c339976",
        "start": {"@odata.type": "#microsoft.graph.dateTimeTimeZone", "dateTime": "2018-05-01T12:00:00+00:00", "timeZone": "UTC"},
        "end": {"@odata.type": "#microsoft.graph.dateTimeTimeZone", "dateTime": "2018-05-01T12:30:00+00:00", "timeZone": "UTC"},
        "customerName": "Jordan Miller", "customerEmailAddress": "jordanm@contoso.com",
        "customers": [{"@odata.type": "#microsoft.graph.bookingCustomerInformation", "customerId": "7ed53fa5-9ef2-4f2f-975b-27447440bc09", "name": "Jordan Miller", "emailAddress": "jordanm@contoso.com"}],
        "staffMemberIds": ["8ee1c803-a1fa-406d-8259-7ab53233f148"], "optOutOfCustomerEmail": True}
    assert len(requests) == 1 and requests[0].method == "POST"
    assert result["data"]["id"] == "AAMkADKnAAA=" and result["write_acknowledged"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,suffix,method,expected", [
    ("create_customer", {"display_name": "Joni Sherman", "email_address": "jonis@relecloud.com"}, "/customers", "POST",
        {"@odata.type": "#microsoft.graph.bookingCustomer", "displayName": "Joni Sherman", "emailAddress": "jonis@relecloud.com"}),
    ("update_service", {"service_id": "service-1", "default_price": 0, "is_hidden_from_customers": False}, "/services/service-1", "PATCH",
        {"@odata.type": "#microsoft.graph.bookingService", "defaultPrice": 0, "isHiddenFromCustomers": False}),
    ("update_business", {"phone": "123-456-7890"}, "", "PATCH",
        {"@odata.type": "#microsoft.graph.bookingBusiness", "phone": "123-456-7890"}),
    ("delete_appointment", {"appointment_id": "AAMkADKnAAA="}, "/appointments/AAMkADKnAAA%3D", "DELETE", None),
])
async def test_mutations_send_only_documented_body_fields(monkeypatch, operation, config, suffix, method, expected):
    requests = transport(monkeypatch, status=201 if method == "POST" else 204,
        body={"id": "created"} if method == "POST" else None)
    result = await node({"operation": operation, "business_id": BUSINESS, **config}).execute({})
    assert len(requests) == 1 and requests[0].method == method
    assert requests[0].url.raw_path.decode() == "/v1.0/solutions/bookingBusinesses/Contosolunchdelivery%40contoso.com" + suffix
    assert (json.loads(requests[0].content) if requests[0].content else None) == expected
    assert result["write_acknowledged"] is True


@pytest.mark.asyncio
async def test_pagination_is_exposed_without_following_provider_url(monkeypatch):
    link = "https://graph.microsoft.com/v1.0/solutions/bookingBusinesses/x/appointments?$skip=20"
    requests = transport(monkeypatch, body={"value": [], "@odata.nextLink": link})
    result = await node({"operation": "list_appointments", "business_id": BUSINESS}).execute({})
    assert result["items"] == [] and result["next_link"] == link and len(requests) == 1


@pytest.mark.asyncio
async def test_opaque_appointment_id_encodes_base64_characters_as_one_segment(monkeypatch):
    requests = transport(monkeypatch, body={"id": "AAMk+abc/def=="})
    await node({"operation": "get_appointment", "business_id": BUSINESS,
        "appointment_id": "AAMk+abc/def=="}).execute({})
    assert requests[0].url.raw_path.decode() == "/v1.0/solutions/bookingBusinesses/Contosolunchdelivery%40contoso.com/appointments/AAMk%2Babc%2Fdef%3D%3D"


@pytest.mark.asyncio
async def test_error_preserves_provider_message_and_redacts_secrets(monkeypatch):
    transport(monkeypatch, status=403, body={"error": {"message": "Access denied " + TOKEN}})
    with pytest.raises(ValueError, match=r"403.*Access denied \[redacted\]") as exc:
        await node({"operation": "list_businesses"}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"value": "bad"}, {"value": [42]}])
async def test_malformed_collection_is_not_success(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError, match="value collection"):
        await node({"operation": "list_businesses"}).execute({})


@pytest.mark.asyncio
async def test_refresh_uses_shared_microsoft_choke_point(monkeypatch):
    from nodes.core import oauth_refresh
    async def refresh(**kwargs):
        assert kwargs["provider"] == "microsoft" and kwargs["caller_path"] == "execute"
        kwargs["credential"]["access_token"] = "fresh-token"
        return "fresh-token"
    mock = AsyncMock(side_effect=refresh)
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", mock)
    requests = transport(monkeypatch, body={"value": []})
    await node({"operation": "list_businesses"}, refresh_token="refresh-token", expires_at="2000-01-01T00:00:00Z").execute({})
    assert mock.await_count == 1 and requests[0].headers["Authorization"] == "Bearer fresh-token"


@pytest.mark.parametrize("config", [
    {"operation": "get_business", "business_id": ".."},
    {"operation": "get_business", "business_id": "https://other.test"},
    {"operation": "update_customer", "business_id": BUSINESS, "customer_id": "c"},
    {"operation": "update_service", "business_id": BUSINESS, "service_id": "s"},
    {"operation": "create_service", "business_id": BUSINESS, "display_name": "Bento", "default_duration": "PT"},
])
def test_invalid_routes_empty_updates_and_durations_are_rejected(config):
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS[config["operation"]].model_validate(config)


def test_credential_default_and_optional_refresh_allow_manual_connect():
    credential = native.MicrosoftBookingsOAuthCredential(access_token="  " + TOKEN + "\n")
    assert credential.credential_type == "microsoft_oauth" and credential.access_token == TOKEN
    assert not credential.refresh_token and not credential.expires_at
    assert set(native.OPERATIONS) == set(native.BOOKINGS_SCOPES)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(DOCUMENTED))
async def test_parser_accepts_unaltered_microsoft_published_responses(monkeypatch, operation):
    fixture = DOCUMENTED[operation]
    config = {"operation": operation}
    for key in native.OPERATIONS[operation].fields:
        if key.endswith("_id"):
            config[key] = BUSINESS if key == "business_id" else "resource-1"
    if operation == "create_appointment":
        config.update(start="2018-05-01T12:00:00+00:00", end="2018-05-01T12:30:00+00:00",
            customer_name="Jordan Miller", customer_email="jordanm@contoso.com")
    if operation == "create_service":
        config.update(display_name="Bento", default_duration="PT1H30M")
    if operation in {"create_customer", "update_customer"}:
        config.update(display_name="Joni Sherman", email_address="jonis@relecloud.com")
    transport(monkeypatch, status=fixture["status"], body=fixture["body"])
    result = await node(config).execute({})
    assert result["status"] == "success"
    if operation.startswith("list_"):
        assert result["items"] == fixture["body"]["value"]
    else:
        assert result["data"] == fixture["body"]
