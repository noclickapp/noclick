"""Offline request/response regressions against EMnify's published v1.3 API."""
import json
from pathlib import Path

import httpx
import pytest
from nodes import emnify_node as native
from nodes.core.registry import NodeFactory

TOKEN = "emnify-synthetic-application-token"
JWT = "emnify-synthetic-auth-token"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/emnify/published_responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="emnify-test", node_type="automation-emnify", node_data={
        "config": config, "credentials": {"credential_type": "emnify_application_token", "application_token": TOKEN}})


def transport(monkeypatch, response=None, status=200, headers=None, auth=None):
    requests = []
    def reply(request):
        requests.append(request)
        if request.url.path.endswith("/authenticate"):
            return auth or httpx.Response(200, json={"auth_token": JWT})
        return httpx.Response(status, json=response, headers=headers) if response is not None else httpx.Response(status, headers=headers)
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fixture,path", [
    ("get_organisation", "organisation", "/organisation/my"),
    ("get_endpoint", "endpoint", "/endpoint/42"),
    ("get_sim", "sim", "/sim/42"),
    ("get_sms", "sms", "/endpoint/42/sms/19"),
    ("get_connectivity", "connectivity", "/endpoint/42/connectivity"),
])
async def test_published_responses_auth_exchange_and_fixed_read_routes(monkeypatch, operation, fixture, path):
    body = FIXTURES[fixture]["body"]
    assert body is not None
    calls = transport(monkeypatch, body)
    cfg = {"operation": operation}
    if operation in {"get_endpoint", "get_sms", "get_connectivity"}:cfg["endpoint_id"] = 42
    if operation == "get_sim":cfg["sim_id"] = 42
    if operation == "get_sms":cfg["sms_id"] = 19
    result = await node(cfg).execute({})
    assert result["data"] == body and result["read_completed"]
    assert len(calls) == 2
    assert calls[0].method == "POST" and json.loads(calls[0].content) == {"application_token": TOKEN}
    assert "authorization" not in calls[0].headers
    assert calls[1].method == "GET" and calls[1].url.path == "/api/v1" + path
    assert calls[1].headers["authorization"] == "Bearer " + JWT
    assert all(c.url.host == "cdn.emnify.net" for c in calls)
    assert TOKEN not in str(result) and JWT not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("list_endpoints", "/endpoint"), ("list_sims", "/sim")])
async def test_one_page_with_explicit_continuation_and_unknown_total(monkeypatch, operation, path):
    calls = transport(monkeypatch, [{"id": 42}], headers={"X-Total-Pages": "3"})
    result = await node({"operation": operation, "page": 2, "per_page": 10}).execute({})
    assert result["next_page"] == 3 and result["pagination_known"]
    assert calls[-1].url.path == "/api/v1" + path and dict(calls[-1].url.params) == {"page": "2", "per_page": "10"}
    transport(monkeypatch, [])
    result = await node({"operation": operation}).execute({})
    assert result["pagination_known"] is False and result["total_pages"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reset,body", [("all", {"location": None, "pdp_context": None}), ("network", {"location": None}), ("data", {"pdp_context": None})])
async def test_connectivity_reset_sends_explicit_nulls_and_no_delivery_claim(monkeypatch, reset, body):
    calls = transport(monkeypatch, status=204)
    result = await node({"operation": "reset_connectivity", "endpoint_id": 42, "reset": reset}).execute({})
    assert calls[-1].method == "PATCH" and json.loads(calls[-1].content) == body
    assert result["acknowledged"] and result["effect_verified"] is False


@pytest.mark.asyncio
async def test_sms_payload_is_sent_once_and_empty_201_is_acknowledgement(monkeypatch):
    calls = transport(monkeypatch, status=201)
    result = await node({"operation": "send_sms", "endpoint_id": 42, "source_address": "12345689", "payload": "This is the message text"}).execute({})
    assert calls[-1].method == "POST" and calls[-1].url.path == "/api/v1/endpoint/42/sms"
    assert json.loads(calls[-1].content) == {"source_address": "12345689", "payload": "This is the message text"}
    assert result["acknowledged"] and not result["effect_verified"] and result["data"] is None
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,expiry,refill", [("set_data_quota", "2030-01-17 08:47:00", 1), ("set_sms_quota", "2030-01-17T08:47:00.000Z", True)])
async def test_quota_required_fields_nested_ids_and_distinct_refill_types(monkeypatch, operation, expiry, refill):
    calls = transport(monkeypatch, status=201)
    await node({"operation": operation, "endpoint_id": 42, "volume": 100, "expiry_date": expiry, "auto_refill": refill}).execute({})
    body = json.loads(calls[-1].content)
    assert body["status"] == {"id": 1} and body["action_on_exhaustion"] == {"id": 1}
    assert body["expiry_date"] == expiry and type(body["auto_refill"]) is type(refill)
    assert body["volume"] == 100 and "threshold_percentage" in body


@pytest.mark.asyncio
async def test_endpoint_and_sim_full_update_contract(monkeypatch):
    calls = transport(monkeypatch, status=204)
    await node({"operation": "update_endpoint", "endpoint_id": 42, "name": "test", "tags": "test1,test2", "imei": "1234567890", "imei_lock": False, "ip_address": "127.0.0.1", "ip_address_space_id": 1, "service_profile_id": 2, "tariff_profile_id": 3, "status_id": 0, "sim_id": 1234567, "sim_status_id": 1}).execute({})
    assert json.loads(calls[-1].content) == {"name": "test", "tags": "test1,test2", "imei": "1234567890", "imei_lock": False, "ip_address": "127.0.0.1", "ip_address_space": {"id": 1}, "service_profile": {"id": 2}, "tariff_profile": {"id": 3}, "status": {"id": 0}, "sim": {"id": 1234567, "status": {"id": 1}}}
    calls = transport(monkeypatch, status=204)
    await node({"operation": "update_sim", "sim_id": 42, "issuer_org_id": 3, "reseller_org_id": 5, "customer_org_id": 12, "status_id": 2}).execute({})
    assert json.loads(calls[-1].content) == {"issuer_org": {"id": 3}, "reseller_org": {"id": 5}, "customer_org": {"id": 12}, "status": {"id": 2}}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,status", [("delete_endpoint", "/endpoint/42", 204), ("remove_data_quota", "/endpoint/42/quota/data", 204), ("remove_sms_quota", "/endpoint/42/quota/sms", 204), ("cancel_sms", "/endpoint/42/sms/19", 200)])
async def test_deletions_only_acknowledge_provider(monkeypatch, operation, path, status):
    calls = transport(monkeypatch, status=status)
    result = await node({"operation": operation, "endpoint_id": 42, "sms_id": 19}).execute({})
    assert calls[-1].method == "DELETE" and calls[-1].url.path == "/api/v1" + path
    assert result["acknowledged"] and not result["effect_verified"]


@pytest.mark.asyncio
async def test_auth_rejection_stops_business_request_and_redacts_secret(monkeypatch):
    calls = transport(monkeypatch, auth=httpx.Response(401, json={"message": "Rejected " + TOKEN}))
    with pytest.raises(ValueError, match="Rejected \\[redacted\\]"):
        await node({"operation": "get_organisation"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_failures_and_redirects_are_not_success(monkeypatch, status):
    calls = transport(monkeypatch, {"message": "Provider rejected " + JWT}, status=status, headers={"Location": "https://elsewhere.test"})
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_organisation"}).execute({})
    assert str(status) in str(exc.value) and JWT not in str(exc.value) and len(calls) == 2


def test_manual_credential_default_and_invalid_paths():
    credential = native.EMnifyApplicationTokenCredential(application_token=TOKEN)
    assert credential.credential_type == "emnify_application_token"
    for config in [{"operation": "get_endpoint", "endpoint_id": "../other"}, {"operation": "get_endpoint", "endpoint_id": 0}, {"operation": "get_daily_usage", "endpoint_id": 1, "start_date": "2026-02-31"}]:
        with pytest.raises(ValueError):
            node(config)
