"""Unrun Oracle HCM transport, opaque-key, date-mode and privacy regressions.

The real request helper uses HTTPX MockTransport; no Oracle account is contacted.
"""
import base64
from copy import deepcopy

import httpx
import pytest

from nodes import oracle_hcm_node as node
from utils import ssrf

CREDENTIAL = {"credential_type": node.BASIC, "username": "fixture-service", "password": "fixture-password", "tenant_url": "https://fixture.fa.us2.oraclecloud.com", "api_version": node.VERSION}
KEY = "00020000ABCDEF"


@pytest.fixture
def ensure_native_db_pool():
    yield


def location(key=KEY, **fields):
    return {"LocationId": 12, "LocationCode": "QA_ONLY", "LocationName": "Fixture Location", "SetId": 0, "SetCode": "COMMON", "EffectiveStartDate": "2026-10-06", "EffectiveEndDate": "4712-12-31", "ActiveStatus": "A", "links": [{"rel": "canonical", "href": node.base_url(node.credential_value(CREDENTIAL)) + "/locationsV2/" + key}], **fields}


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    monkeypatch.setattr(ssrf, "assert_url_allowed", lambda *args, **kwargs: _allowed())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def provider(request):
        calls.append(request)
        assert responses, "Unexpected request or retry"
        return responses.pop(0)
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(provider), **kwargs))
    return calls, responses


async def _allowed():
    return None


@pytest.mark.parametrize("value", ["http://fixture.fa.us2.oraclecloud.com", "https://fixture.fa.us2.oraclecloud.com:443", "https://fixture.fa.us2.oraclecloud.com/path", "https://user@fixture.fa.us2.oraclecloud.com", "https://127.0.0.1", "https://fixture.fa.us2.oraclecloud.com.evil.test", "https://fixture.fa.us2.oraclecloud.com?token=x"])
def test_tenant_is_a_documented_https_origin(value):
    with pytest.raises(ValueError):
        node.credential_value({**CREDENTIAL, "tenant_url": value})


def test_explicit_version_family_and_v1_oauth_boundary():
    with pytest.raises(ValueError):
        node.credential_value({**CREDENTIAL, "api_version": "v1"})
    with pytest.raises(ValueError):
        node.credential_value({key: value for key, value in CREDENTIAL.items() if key != "credential_type"})
    with pytest.raises(ValueError):
        node.credential_value({**CREDENTIAL, "access_token": "fixture-token"})
    token = node.credential_value({"credential_type": node.OAUTH, "access_token": "fixture-issued-token", "tenant_url": CREDENTIAL["tenant_url"], "api_version": node.VERSION})
    assert node.auth_header(token) == "Bearer fixture-issued-token"


async def test_actual_basic_wire_minimal_worker_projection_and_clamped_paging(transport):
    calls, responses = transport
    raw = {"PersonId": 44, "PersonNumber": "D44", "DisplayName": "private-name", "phones": [{"PhoneNumber": "private-phone"}], "assignments": [{"Salary": 123}], "links": [{"rel": "self", "href": node.base_url(node.credential_value(CREDENTIAL)) + "/publicWorkers/44"}]}
    responses.append(httpx.Response(200, json={"items": [raw], "count": 1, "offset": 0, "limit": 20, "hasMore": True}))
    result = await node.request_operation(CREDENTIAL, node.ListWorkers(limit=50))
    assert result["data"]["next_offset"] == 20
    assert result["data"]["items"] == [{"id": "44", "PersonId": "44", "PersonNumber": "D44", "resource_key": "44", "name": "D44"}]
    assert calls[0].headers["Authorization"] == "Basic " + base64.b64encode(b"fixture-service:fixture-password").decode()
    assert calls[0].url.params["fields"] == "PersonId,PersonNumber"
    assert "expand" not in calls[0].url.params and "dependency" not in calls[0].url.params
    assert calls[0].url.path == "/hcmRestApi/resources/11.13.18.05/publicWorkers"
    assert "fixture-password" not in str(calls[0].url)


@pytest.mark.parametrize("edit", [{"offset": 1}, {"count": 9}, {"limit": 101}, {"hasMore": "true"}, {"items": [], "count": 0, "hasMore": True}])
async def test_incoherent_page_is_not_partial_success(transport, edit):
    calls, responses = transport
    responses.append(httpx.Response(200, json={"items": [location()], "count": 1, "offset": 0, "limit": 50, "hasMore": False, **edit}))
    with pytest.raises(ValueError, match="paging"):
        await node.request_operation(CREDENTIAL, node.ListLocations())
    assert len(calls) == 1


@pytest.mark.parametrize("href", ["https://evil.test/hcmRestApi/resources/11.13.18.05/locationsV2/123", "https://fixture.fa.us2.oraclecloud.com/hcmRestApi/resources/v1/locationsV2/123", "https://fixture.fa.us2.oraclecloud.com/hcmRestApi/resources/11.13.18.05/workers/123", "https://fixture.fa.us2.oraclecloud.com/hcmRestApi/resources/11.13.18.05/locationsV2/123?access_token=x"])
def test_opaque_link_is_bound_to_current_tenant_version_resource(href):
    with pytest.raises(ValueError):
        node.project(location(links=[{"rel": "canonical", "href": href}]), node.credential_value(CREDENTIAL), "locationsV2")
    with pytest.raises(ValueError):
        node.project(location(links=[]), node.credential_value(CREDENTIAL), "locationsV2")


async def test_create_uses_all_documented_required_fields_and_readback(transport):
    calls, responses = transport
    responses.extend([httpx.Response(201, json=location()), httpx.Response(200, json=location())])
    config = node.CreateLocation(location_code="QA_ONLY", location_name="Fixture Location", set_id=0, set_code="COMMON", effective_start_date="2026-10-06", effective_end_date="4712-12-31")
    result = await node.request_operation(CREDENTIAL, config)
    assert result["data"]["resource_key"] == KEY and len(calls) == 2
    body = node.finite_json(calls[0].content)
    assert body == {"LocationCode": "QA_ONLY", "LocationName": "Fixture Location", "SetId": 0, "SetCode": "COMMON", "EffectiveStartDate": "2026-10-06", "EffectiveEndDate": "4712-12-31"}
    assert calls[0].headers["Content-Type"] == "application/vnd.oracle.adf.resourceitem+json"
    assert "Upsert-Mode" not in calls[0].headers


async def test_date_effective_update_allows_new_hash_but_preserves_surrogate_identity(transport):
    calls, responses = transport
    after = location("00020000NEWKEY", LocationName="Changed", Description=None)
    responses.extend([httpx.Response(200, json=location()), httpx.Response(200, json=after), httpx.Response(200, json=after)])
    config = node.UpdateLocation(location_key=KEY, range_mode="UPDATE", effective_start_date="2026-11-01", location_name="Changed", description=None)
    result = await node.request_operation(CREDENTIAL, config)
    assert calls[1].headers["Effective-Of"] == "RangeStartDate=2026-11-01;RangeMode=UPDATE"
    assert node.finite_json(calls[1].content) == {"LocationName": "Changed", "Description": None}
    assert result["data"]["id"] == "12" and result["data"]["resource_key"] == "00020000NEWKEY"
    assert calls[2].url.path.endswith("/00020000NEWKEY")


async def test_delete_changes_keeps_bodyless_204_and_qualified_history_semantics(transport):
    calls, responses = transport
    responses.extend([httpx.Response(200, json=location()), httpx.Response(204, headers={"Content-Type": "text/plain"})])
    result = await node.request_operation(CREDENTIAL, node.DeleteLocation(location_key=KEY, confirm_delete_changes=True))
    assert result["data"]["delete_changes_accepted"] is True and result["data"]["logical_location_absence_verified"] is False
    assert len(calls) == 2 and calls[1].headers["Effective-Of"] == "RangeMode=DELETE_CHANGES"
    with pytest.raises(ValueError):
        node.DeleteLocation(location_key=KEY, confirm_delete_changes="true")


@pytest.mark.parametrize("status", [202, 301, 401, 403, 429, 500])
async def test_unexpected_or_error_status_is_safe_and_never_retried(transport, status):
    calls, responses = transport
    responses.append(httpx.Response(status, text="private-payroll fixture-password", headers={"Retry-After": "5"}))
    with pytest.raises(node.OracleHCMAPIError) as error:
        await node.request_operation(CREDENTIAL, node.ListDepartments())
    assert error.value.http_status == status and "private-payroll" not in str(error.value) and "fixture-password" not in str(error.value)
    assert len(calls) == 1


async def test_cursor_binds_current_credential_tenant_and_search_before_io(transport):
    calls, responses = transport
    responses.append(httpx.Response(200, json={"items": [location()], "count": 1, "offset": 0, "limit": 100, "hasMore": True}))
    page = await node.OracleHCMNode.load_field_options("location_key", CREDENTIAL, search="Fixture")
    with pytest.raises(ValueError, match="continuation"):
        await node.OracleHCMNode.load_field_options("location_key", {**CREDENTIAL, "password": "rotated-password"}, page_token=page["next_page_token"], search="Fixture")
    assert len(calls) == 1 and page["options"][0]["value"] == KEY


@pytest.mark.parametrize("content", [b'{"count":1,"count":2}', b'{"value":NaN}', b'{"value":1e999}', b'{broken'])
def test_strict_json(content):
    with pytest.raises(ValueError):
        node.finite_json(content)


def test_date_modes_and_closed_fields():
    for data in ({"range_mode": "UPDATE"}, {"range_mode": "CORRECTION", "effective_start_date": "2026-11-01"}, {"range_mode": "CORRECTION", "location_name": None}, {"range_mode": "CORRECTION", "bank_account": "forbidden"}):
        with pytest.raises(ValueError):
            node.UpdateLocation(location_key=KEY, description="Fixture", **data)
    encoded = base64.b64encode(b"fixture-service:fixture-password").decode()
    assert "fixture-password" not in node.safe_text("fixture-password " + encoded, node.credential_value(CREDENTIAL))
    assert encoded not in node.safe_text(encoded, node.credential_value(CREDENTIAL))


async def test_response_bound_private_override_and_failed_write_readback_never_retry(transport, monkeypatch):
    calls, responses = transport
    responses.append(httpx.Response(200, content=b"x" * (node.MAX_BYTES + 1), headers={"Content-Type": "application/json"}))
    with pytest.raises(ValueError, match="2 MiB"):
        await node.request_operation(CREDENTIAL, node.ListDepartments())
    assert len(calls) == 1
    monkeypatch.setattr(node, "allow_private_hosts", lambda: True)
    with pytest.raises(ValueError, match="private overrides"):
        await node.request_operation(CREDENTIAL, node.ListDepartments())
    assert len(calls) == 1
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    responses.extend([httpx.Response(200, json=location()), httpx.Response(200, json=location(LocationName="Changed")), httpx.Response(200, json=location())])
    with pytest.raises(ValueError, match="readback"):
        await node.request_operation(CREDENTIAL, node.UpdateLocation(location_key=KEY, range_mode="CORRECTION", location_name="Changed"))
    assert len(calls) == 4 and [request.method for request in calls[1:]] == ["GET", "PATCH", "GET"]


async def test_execute_with_typed_config_and_no_frontend_data(transport):
    calls, responses = transport
    responses.append(httpx.Response(200, json={"items": [], "count": 0, "offset": 0, "limit": 50, "hasMore": False}))
    config = node.OracleHCMNodeConfig.model_validate({"config": {"operation": "list_departments"}, "credentials": CREDENTIAL})
    instance = node.OracleHCMNode(node_id="typed", node_type="automation-oracle-hcm", node_data={}, config=config)
    result = await instance.execute({})
    assert result["data"]["items"] == [] and len(calls) == 1
    instance.node_data = {"config": {"operation": "list_departments", "url": "https://evil.test"}, "credentials": CREDENTIAL}
    with pytest.raises(ValueError, match="typed HCM fields"):
        await instance.execute({})
    assert len(calls) == 1
