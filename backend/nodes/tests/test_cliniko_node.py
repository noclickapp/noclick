"""Unrun Cliniko native contracts using synthetic HTTP, never healthcare data."""
import base64
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import cliniko_node as node
from utils import ssrf

CREDENTIAL = {"credential_type": "cliniko_api_key", "api_key": "fixture-cliniko-key-uk2", "admin_contact_email": "admin@example.test", "shard": "uk2"}
BUSINESS = {"id": "12", "business_name": "Fixture Business", "time_zone_identifier": "Europe/London", "contact_information": "private-phone", "additional_information": "private-notes", "additional_invoice_information": "private-billing"}
PRACTITIONER = {"id": "34", "display_name": "Fixture Practitioner", "active": True, "description": "private-description", "user": {"links": {"self": "private-user"}}}
APPOINTMENT_TYPE = {"id": "56", "name": "Fixture Type", "duration_in_minutes": 30, "treatment_note_template": {"private": "medical"}, "deposit_price": "private-money"}
CONTACT = {"id": "78", "first_name": "Fixture", "last_name": "Contact", "company_name": "Fixture Company", "email": "contact@example.test", "archived_at": None, "notes": "private-medical-text", "phone_numbers": [{"number": "private-phone"}], "provider_number": "private-provider"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {
        ("GET", "/v1/businesses/12"): BUSINESS,
        ("GET", "/v1/practitioners/34"): PRACTITIONER,
        ("GET", "/v1/appointment_types/56"): APPOINTMENT_TYPE,
        ("GET", "/v1/contacts/78"): CONTACT,
    }
    async def handler(request):
        calls.append(request)
        assert request.url.host == "api.uk2.cliniko.com" and request.url.scheme == "https"
        assert request.headers["Authorization"] == "Basic " + base64.b64encode((CREDENTIAL["api_key"] + ":").encode()).decode()
        assert request.headers["User-Agent"] == "NoClick (admin@example.test)"
        assert CREDENTIAL["api_key"] not in str(request.url)
        reply = replies[(request.method, request.url.path)]
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    actual_client = ssrf.guarded_async_client
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual_client(transport=httpx.MockTransport(handler), **kwargs))
    return calls, replies


def test_issued_shard_and_legacy_shard_do_not_invent_a_url_or_bearer_flow():
    assert node.credential_value(CREDENTIAL).shard == "uk2"
    assert node.credential_value({key: value for key, value in CREDENTIAL.items() if key != "shard"}).shard == "uk2"
    assert node.credential_value({**CREDENTIAL, "api_key": "fixture-legacy-key", "shard": "au1"}).shard == "au1"
    for change in ({"shard": "au1"}, {"api_key": "fixture-key-zz9"}, {"api_key": "Basic private"}, {"api_key": "key:password"}, {"admin_contact_email": "admin@example.test\r\nHeader: bad"}, {"admin_contact_email": "admin@bad..test"}):
        with pytest.raises(ValueError):
            node.credential_value({**CREDENTIAL, **change})


async def test_business_page_validates_next_link_and_omits_free_and_billing_fields(transport):
    calls, replies = transport
    replies[("GET", "/v1/businesses")] = {"businesses": [BUSINESS], "total_entries": 2, "links": {"next": "https://api.uk2.cliniko.com/v1/businesses?page=2&per_page=1"}}
    result = await node.request_operation(CREDENTIAL, node.ListBusinesses(per_page=1))
    assert result["data"]["items"] == [{"id": "12", "business_name": "Fixture Business", "time_zone_identifier": "Europe/London", "name": "Fixture Business"}]
    assert result["data"]["next_page"] == 2 and len(calls) == 1
    assert dict(calls[0].url.params) == {"page": "1", "per_page": "1"}


@pytest.mark.parametrize("link", ["https://api.au1.cliniko.com/v1/businesses?page=2", "https://attacker.example.test/v1/businesses?page=2", "https://api.uk2.cliniko.com/v1/patients?page=2", "https://api.uk2.cliniko.com/v1/businesses?page=2&page=3", "https://api.uk2.cliniko.com/v1/businesses?page=1", "https://api.uk2.cliniko.com/v1/businesses?page=2&per_page=100", "https://api.uk2.cliniko.com/v1/businesses?page=2&api_key=private"])
async def test_foreign_duplicate_nonprogressing_or_changed_page_link_is_never_followed(transport, link):
    calls, replies = transport
    replies[("GET", "/v1/businesses")] = {"businesses": [BUSINESS], "total_entries": 2, "links": {"next": link}}
    with pytest.raises(ValueError, match="pagination"):
        await node.request_operation(CREDENTIAL, node.ListBusinesses(per_page=1))
    assert len(calls) == 1


async def test_missing_next_for_incomplete_page_fails_loudly(transport):
    _, replies = transport
    replies[("GET", "/v1/businesses")] = {"businesses": [BUSINESS], "total_entries": 2, "links": {}}
    with pytest.raises(ValueError, match="incomplete"):
        await node.request_operation(CREDENTIAL, node.ListBusinesses(per_page=1))


async def test_availability_reads_exact_parents_and_fixed_date_window_only(transport):
    calls, replies = transport
    route = "/v1/businesses/12/practitioners/34/appointment_types/56/available_times"
    replies[("GET", route)] = {"available_times": [{"appointment_start": "2099-01-01T10:00:00Z", "patient_id": "private", "notes": "private"}], "total_entries": 1, "links": {}}
    config = node.ListAvailableTimes(business_id="12", practitioner_id="34", appointment_type_id="56", from_date="2099-01-01", to_date="2099-01-07")
    result = await node.request_operation(CREDENTIAL, config)
    assert result["data"]["items"] == [{"appointment_start": "2099-01-01T10:00:00Z"}]
    assert result["data"]["business_id"] == "12" and result["data"]["practitioner_id"] == "34"
    assert dict(calls[-1].url.params) == {"from": "2099-01-01", "to": "2099-01-07", "page": "1", "per_page": "50"}
    assert [call.url.path for call in calls] == ["/v1/businesses/12", "/v1/practitioners/34", "/v1/appointment_types/56", route]


@pytest.mark.parametrize("dates", [("2099-01-01", "2099-01-09"), ("2099-01-07", "2099-01-01"), ("2099-02-30", "2099-03-01")])
def test_availability_date_window_is_bounded_before_any_request(dates):
    with pytest.raises(ValueError):
        node.GetNextAvailableTime(business_id="12", practitioner_id="34", appointment_type_id="56", from_date=dates[0], to_date=dates[1])


async def test_foreign_parent_id_stops_before_availability(transport):
    calls, replies = transport
    replies[("GET", "/v1/practitioners/34")] = {**PRACTITIONER, "id": "35"}
    with pytest.raises(ValueError, match="different resource"):
        await node.request_operation(CREDENTIAL, node.GetNextAvailableTime(business_id="12", practitioner_id="34", appointment_type_id="56", from_date="2099-01-01", to_date="2099-01-07"))
    assert len(calls) == 2


@pytest.mark.parametrize("cls,method,status", [(node.CreateContact, "POST", 201), (node.UpdateContact, "PATCH", 200)])
async def test_external_contact_write_is_closed_and_confirmed_by_get_readback(transport, cls, method, status):
    calls, replies = transport
    state = {"contact": dict(CONTACT)}
    replies[("GET", "/v1/contacts/78")] = lambda _: httpx.Response(200, json=state["contact"])
    def change(request):
        expected = {"company_name": "New Company"} if method == "POST" else {"company_name": "New Company", "email": None}
        assert json.loads(request.content) == expected
        state["contact"].update(expected)
        return httpx.Response(status, json=state["contact"])
    replies[(method, "/v1/contacts" if method == "POST" else "/v1/contacts/78")] = change
    config = cls(company_name="New Company") if method == "POST" else cls(contact_id="78", company_name="New Company", email=None)
    result = await node.request_operation(CREDENTIAL, config)
    assert result["data"]["company_name"] == "New Company" and "private" not in repr(result)
    assert [call.method for call in calls] == (["POST", "GET"] if method == "POST" else ["GET", "PATCH", "GET"])
    assert state["contact"]["last_name"] == "Contact"


async def test_creation_confirmation_failure_does_not_repeat_post(transport):
    calls, replies = transport
    replies[("POST", "/v1/contacts")] = lambda _: httpx.Response(201, json=CONTACT)
    with pytest.raises(ValueError, match="not confirmed"):
        await node.request_operation(CREDENTIAL, node.CreateContact(company_name="New Company"))
    assert len(calls) == 1 and calls[0].method == "POST"


async def test_archive_204_has_no_json_and_checks_documented_status(transport):
    calls, replies = transport
    state = {"contact": dict(CONTACT)}
    replies[("GET", "/v1/contacts/78")] = lambda _: httpx.Response(200, json=state["contact"])
    def archive(_):
        state["contact"]["archived_at"] = "2099-01-01T10:00:00Z"
        return httpx.Response(204, content=b"")
    replies[("POST", "/v1/contacts/78/archive")] = archive
    result = await node.request_operation(CREDENTIAL, node.ArchiveContact(contact_id="78", confirm_archive=True))
    assert result["changed"] is True and result["data"]["archived_at"] == "2099-01-01T10:00:00Z"
    assert [call.method for call in calls] == ["GET", "POST", "GET"]


@pytest.mark.parametrize("confirmation", [False, 1, "true"])
def test_archive_requires_explicit_boolean_not_coercion(confirmation):
    with pytest.raises(ValueError):
        node.ArchiveContact(contact_id="78", confirm_archive=confirmation)


@pytest.mark.parametrize("status", [201, 202, 204, 301, 401, 403, 429, 500])
async def test_safe_http_error_exposes_reset_timestamp_not_key_body_or_url(transport, status):
    calls, replies = transport
    replies[("GET", "/v1/businesses/12")] = lambda _: httpx.Response(status, text=CREDENTIAL["api_key"], headers={"Location": "https://private.example.test", "X-RateLimit-Reset": "1791288000"})
    with pytest.raises(node.ClinikoAPIError) as failure:
        await node.request_operation(CREDENTIAL, node.GetBusiness(business_id="12"))
    assert failure.value.http_status == status and failure.value.rate_limit_reset_at == 1791288000
    assert "private" not in str(failure.value) and CREDENTIAL["api_key"] not in str(failure.value)
    assert len(calls) == 1


async def test_response_limit_and_private_override_prevent_partial_or_private_result(transport, monkeypatch):
    calls, replies = transport
    replies[("GET", "/v1/businesses/12")] = lambda _: httpx.Response(200, content=b"x" * (node.MAX_BYTES + 1), headers={"Content-Type": "application/json"})
    with pytest.raises(ValueError, match="2 MiB"):
        await node.request_operation(CREDENTIAL, node.GetBusiness(business_id="12"))
    monkeypatch.setattr(node, "allow_private_hosts", lambda: True)
    with pytest.raises(ValueError, match="overrides"):
        await node.request_operation(CREDENTIAL, node.GetBusiness(business_id="12"))
    with pytest.raises(ValueError, match="different current"):
        await node.ClinikoNode.load_field_options("business_id", CREDENTIAL, page_token="forged:2")
    assert len(calls) == 1


@pytest.mark.parametrize("content", [b'{"id":"12","id":"12"}', b'{"id":NaN}', b'{"id":1e999}', b'not-json'])
def test_json_is_finite_and_has_unique_keys(content):
    with pytest.raises(ValueError):
        node.finite_json(content)


def test_metadata_redacts_raw_and_encoded_authentication_and_admin_contact():
    credential = node.credential_value(CREDENTIAL)
    encoded = base64.b64encode((credential.api_key + ":").encode()).decode()
    result = node.safe_text(credential.api_key + " " + encoded + " " + credential.admin_contact_email, credential)
    assert result == "[redacted] [redacted] [redacted]"
    assert credential.api_key not in repr(credential)
