"""Exercise the actual Vagaro factory and guarded native transport with synthetic HTTP.

These fixtures preserve regional headers, real config normalization and paging.
Provider profile effects and cleanup are never inferred from an acknowledgment.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from nodes import vagaro_node as s
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import verify_operation_scopes
from utils import ssrf

NODE = "automation-vagaro"
BID, CUSTOMER, EMPLOYEE, APPT = "owned~business==", "owned-customer==", "owned-employee==", "owned-appointment=="
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
KEY = {"credential_type": "vagaro_issued_client_token", "access_token": "fixture.private.token", "region": "us04", "expires_at": "2026-10-06T01:00:00Z", "granted_scopes": ["read access", "write access", "write employee"]}
LOCATION = {"businessId": BID, "businessName": "Owned Location", "businessPhone": "private-phone", "businessEmail": "private-email"}


@pytest.fixture
def ensure_native_db_pool():
    yield


def envelope(data, **extra):
    return {"status": 200, "responseCode": 1000, "message": "Success", "data": data, **extra}


@pytest.fixture
def provider(monkeypatch):
    state = SimpleNamespace(calls=[], responses=[], factories=0, dns=[])
    async def dns(host, port):
        state.dns.append((host, port))
        assert host == "api.vagaro.com"
        return ["8.8.8.8"]
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", dns)
    monkeypatch.setattr(s, "_now", lambda: NOW)
    def answer(request):
        state.calls.append(request)
        assert request.url.host == "api.vagaro.com" and request.url.path.startswith("/us04/api/v2/")
        assert request.headers["accessToken"] == KEY["access_token"] and "authorization" not in request.headers
        assert state.responses, "Unexpected provider request"
        result = state.responses.pop(0)
        return result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)
    factory = ssrf.guarded_async_client
    def client(**kwargs):
        state.factories += 1
        assert "require_public" not in kwargs and not kwargs["trust_env"] and not kwargs["follow_redirects"]
        return factory(**kwargs, transport=httpx.MockTransport(answer))
    monkeypatch.setattr(s, "guarded_async_client", client)
    return state


async def run(config, credential=None):
    node = NodeFactory.create_node(node_id="fixture-vagaro", node_type=NODE, node_data={"config": config, "credentials": credential or KEY}, user_id="fixture-owner")
    return await node.execute({})


def parent(provider):
    provider.responses.append(envelope({"locations": [LOCATION]}))


@pytest.mark.asyncio
async def test_real_post_read_header_and_verified_numeric_continuation_without_url_output(provider):
    provider.responses.append(envelope({"locations": [LOCATION], "nextPage": "https://api.vagaro.com/us04/api/v2/locations?pageNumber=2&pageSize=1"}))
    result = await run({"operation": "list_locations", "page_size": 1})
    request = provider.calls[0]
    assert request.method == "POST" and json.loads(request.content) == {}
    assert dict(request.url.params) == {"pageNumber": "1", "pageSize": "1"}
    assert result["next_page_number"] == 2 and not result["snapshot_verified"]
    assert "nextPage" not in result and "private" not in json.dumps(result)
    assert s.VagaroNode.connection_evidence.identity_operation is None


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://outside.invalid/us04/api/v2/locations?pageNumber=2&pageSize=1", "https://api.vagaro.com/us02/api/v2/locations?pageNumber=2&pageSize=1", "https://api.vagaro.com/us04/api/v2/locations?pageNumber=1&pageSize=1", "https://api.vagaro.com/us04/api/v2/locations?pageNumber=2&pageNumber=3&pageSize=1", "https://api.vagaro.com/us04/api/v2/locations?pageNumber=2&pageSize=100"])
async def test_continuation_cannot_change_host_region_route_size_or_replay(provider, url):
    provider.responses.append(envelope({"locations": [LOCATION], "nextPage": url}))
    result = await run({"operation": "list_locations", "page_size": 1})
    assert result["status"] == "error" and result["status_code"] == 200 and len(provider.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [envelope({"locations": []}, executed=False), envelope({"locations": []}, errors={"field": "private"}), {"status": 401, "responseCode": 1034, "data": ""}, {"status": 200, "responseCode": 1003, "data": {}}, {"status": 200, "responseCode": 1000}, {"status": "200", "responseCode": 1000, "data": {}}])
async def test_actual_semantic_error_envelope_is_not_a_successful_http_probe(provider, payload):
    provider.responses.append(payload)
    result = await run({"operation": "list_locations"})
    assert result["status"] == "error" and result["status_code"] == 200 and "private" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b'{"status":200,"responseCode":1000,"data":{},"opaque":NaN}', b'{"status":200,"responseCode":1000,"data":{},"opaque":1e309}', b'{"status":200,"status":200,"responseCode":1000,"data":{}}', b" " * (s.MAX_BYTES + 1)])
async def test_strict_finite_duplicate_free_json_and_real_stream_limit(provider, body):
    provider.responses.append(httpx.Response(200, content=body, headers={"content-type": "application/json"}))
    result = await run({"operation": "list_locations"})
    assert result["status"] == "error" and result["status_code"] == 200 and len(provider.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("include_contacts", [False, True])
async def test_customer_parent_and_id_are_real_contact_output_is_explicit(provider, include_contacts):
    parent(provider)
    provider.responses.append(envelope({"customerId": CUSTOMER, "customerFirstName": "Owned", "email": "owned@example.test", "mobilePhone": "5555555555", "birthday": "private-date", "pointsBalance": 500, "generalTags": ["owned"]}))
    result = await run({"operation": "get_customer", "business_id": BID, "customer_id": CUSTOMER, "include_contact_details": include_contacts})
    assert json.loads(provider.calls[0].content) == {"businessId": BID}
    assert json.loads(provider.calls[1].content) == {"businessId": BID, "customerId": CUSTOMER}
    assert ("email" in result) is include_contacts and "birthday" not in result and "pointsBalance" not in result
    assert result["generalTags"] == ["owned"]


@pytest.mark.asyncio
async def test_different_location_prevents_record_request(provider):
    provider.responses.append(envelope({"locations": [{**LOCATION, "businessId": "other-location"}]}))
    result = await run({"operation": "get_customer", "business_id": BID, "customer_id": CUSTOMER})
    assert result["status"] == "error" and not result["uncertain_outcome"] and len(provider.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("customer", [CUSTOMER, "other-customer"])
async def test_appointment_documented_page_query_does_not_invent_verified_continuation(provider, customer):
    parent(provider)
    provider.responses.append(envelope([{"appointmentId": APPT, "customerId": customer, "amount": 100, "formResponseIds": ["private"]}]))
    result = await run({"operation": "list_customer_appointments", "business_id": BID, "customer_id": CUSTOMER, "page_size": 1})
    assert json.loads(provider.calls[-1].content) == {"businessId": BID, "customerId": CUSTOMER}
    assert dict(provider.calls[-1].url.params) == {"pageNumber": "1", "pageSize": "1", "orderBy": "asc"}
    if customer != CUSTOMER:
        assert result["status"] == "error"
    else:
        assert result["next_page_number"] == 2 and not result["continuation_verified"]
        assert "amount" not in result["appointments"][0] and "formResponseIds" not in result["appointments"][0]


@pytest.mark.asyncio
async def test_personal_task_read_checks_actual_employee_parent_and_explicit_local_dates(provider):
    parent(provider)
    provider.responses.append(envelope({"serviceProviderId": EMPLOYEE, "employeeFirstName": "Owned"}))
    provider.responses.append(envelope({"personalTasks": [{"personalTaskId": "owned-task", "businessId": BID, "serviceProviderId": EMPLOYEE, "personalTaskName": "Owned task", "personalTaskComment": "private"}]}))
    result = await run({"operation": "list_personal_tasks", "business_id": BID, "service_provider_id": EMPLOYEE, "start_date": "2026-10-06", "end_date": "2026-10-07"})
    assert result["personalTasks"][0]["personalTaskId"] == "owned-task" and "private" not in json.dumps(result)
    assert json.loads(provider.calls[-1].content) == {"businessId": BID, "serviceProviderId": EMPLOYEE, "startTime": "2026-10-06", "endTime": "2026-10-07"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,wire", [("update_customer_profile", {"customer_id": CUSTOMER, "general_tags": []}, {"businessId": BID, "generalTags": []}), ("update_employee_name", {"service_provider_id": EMPLOYEE, "employee_first_name": "Changed"}, {"businessId": BID, "employeeFirstName": "Changed"}), ("update_location_name", {"business_name": "Changed"}, {"businessName": "Changed"})])
async def test_closed_profile_update_preflights_record_and_accepts_documented_empty_string(provider, operation, arguments, wire):
    parent(provider)
    if operation == "update_customer_profile":
        provider.responses.append(envelope({"customerId": CUSTOMER}))
    elif operation == "update_employee_name":
        provider.responses.append(envelope({"serviceProviderId": EMPLOYEE}))
    provider.responses.append(envelope(""))
    result = await run({"operation": operation, "business_id": BID, "acknowledge_profile_effects": True, **arguments})
    assert provider.calls[-1].method == "PUT" and json.loads(provider.calls[-1].content) == wire
    assert result["provider_acknowledged"] and not result["readback_verified"] and result["status_code"] == 200
    assert len(provider.calls) == (2 if operation == "update_location_name" else 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(500, json={"message": "private"}), httpx.Response(302, headers={"location": "https://outside.invalid"}), httpx.Response(200, json=envelope({}))])
async def test_failed_or_malformed_mutation_preserves_status_and_one_attempt_uncertainty(provider, response):
    parent(provider)
    provider.responses.append(response)
    result = await run({"operation": "update_location_name", "business_id": BID, "business_name": "Changed", "acknowledge_profile_effects": True})
    assert result["status"] == "error" and result["status_code"] == response.status_code and result["uncertain_outcome"] and len(provider.calls) == 2
    assert "private" not in json.dumps(result)


@pytest.mark.asyncio
async def test_scope_expiry_family_effects_and_invalid_parent_precede_every_client(provider):
    result = await run({"operation": "update_location_name", "business_id": BID, "business_name": "Changed", "acknowledge_profile_effects": True}, {**KEY, "granted_scopes": ["read access"]})
    assert result["status"] == "error"
    assert (await run({"operation": "list_locations"}, {**KEY, "expires_at": "2026-10-05T00:00:00Z"}))["status"] == "error"
    for config, credential in [({"operation": "list_locations"}, {**KEY, "credential_type": "foreign"}), ({"operation": "update_location_name", "business_id": BID, "business_name": "Changed", "acknowledge_profile_effects": False}, KEY), ({"operation": "get_location", "business_id": "../other"}, KEY)]:
        with pytest.raises(ValueError):
            await run(config, credential)
    assert provider.factories == 0 and not provider.calls and not provider.dns


@pytest.mark.asyncio
async def test_native_picker_uses_real_page_number_and_never_follows_next_url(provider):
    provider.responses.append(envelope({"locations": [LOCATION]}))
    result = await s.VagaroNode.load_field_options("business_id", KEY, page_token="2", search="owned")
    assert result["options"] == [{"label": "Owned Location", "value": BID}] and result["next_page_token"] is None
    assert provider.calls[0].url.params["pageNumber"] == "2" and len(provider.calls) == 1


def test_credentials_hide_secrets_and_do_not_advertise_fake_oauth():
    model = s.VagaroIssuedClientTokenCredential.model_validate(KEY)
    assert KEY["access_token"] not in repr(model)
    for invalid in [{**KEY, "access_token": "private\r\nheader"}, {**KEY, "region": "../private"}, {**KEY, "expires_at": "private-valueZ"}]:
        with pytest.raises(ValidationError) as error:
            s.VagaroIssuedClientTokenCredential.model_validate(invalid)
        assert "private" not in str(error.value)
    assert "x-oauth-provider" not in s.VagaroIssuedClientTokenCredential.model_json_schema()
    assert verify_operation_scopes(s.VagaroNode, ["update_location_name", "update_customer_profile"], ["read access"]) == {"update_location_name": ["write employee"], "update_customer_profile": ["write access"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("slug,path,fields,id_key", [
    ("retrieve-customer", "customers", s.CUSTOMER, "customerId"),
    ("retrieve-employee", "employees", s.EMPLOYEE, "serviceProviderId"),
    ("retrieve-appointment", "appointments", s.APPOINTMENT, "appointmentId"),
])
async def test_documented_record_examples_parse_without_exposing_private_fields(provider, slug, path, fields, id_key):
    example = json.loads((Path(__file__).parent / "fixtures" / "vagaro" / f"{slug}.json").read_text())
    provider.responses.append(example["body"])
    session = s.BusinessSession(s.VagaroIssuedClientTokenCredential.model_validate(KEY))
    data, status = await session.request("POST", path, body={})
    records = data if isinstance(data, list) else [data]
    projected = [s._project(record, fields, id_key) for record in records]
    assert status == 200 and len(projected) == len(records)
    assert all(row[id_key] == record[id_key] for row, record in zip(projected, records))
    assert all(set(row) <= set(fields) for row in projected)


@pytest.mark.asyncio
@pytest.mark.parametrize("slug,path,field,fields,id_key", [
    ("retrieve-locations", "locations", "locations", s.LOCATION, "businessId"),
    ("retrieve-personal-tasks", "personal-tasks/retrieve", "personalTasks", s.TASK, "personalTaskId"),
])
async def test_documented_pages_preserve_verified_continuation(provider, slug, path, field, fields, id_key):
    example = json.loads((Path(__file__).parent / "fixtures" / "vagaro" / f"{slug}.json").read_text())
    provider.responses.append(example["body"])
    session = s.BusinessSession(s.VagaroIssuedClientTokenCredential.model_validate(KEY))
    data, _ = await session.request("POST", path, body={})
    page = s._page(data, field, s.Page(page_size=50), session, path, fields, id_key)
    assert page["next_page_number"] == 2 and len(page[field]) == len(data[field])
    assert all(set(row) <= set(fields) for row in page[field])
