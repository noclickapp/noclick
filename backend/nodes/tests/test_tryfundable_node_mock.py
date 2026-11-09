"""Offline request and failure regressions for the native Tryfundable node.

Fixtures pin provider routes and documented examples independently of the
runtime routing table. No live API key, account or credit spend is involved.
"""
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import tryfundable_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/tryfundable/contract.json").read_text())
TOKEN = "vg_123456abcdef_abcdefghijklmnopqrstuvwxyz012345"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="tryfundable-test", node_type="automation-tryfundable",
        node_data={"config": config, "credentials": {"credential_type": "tryfundable_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body=None, status=200, mime="application/json"):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body if body is not None else {
            "success": True, "data": {"configurations": []}, "meta": {"credits_used": 0}},
            headers={"Content-Type": mime, "Location": "https://example.test/redirect"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,case", FIXTURE["operations"].items())
async def test_every_operation_uses_its_single_documented_endpoint(monkeypatch, operation, case):
    requests = transport(monkeypatch)
    result = await node({"operation": operation, **case["config"]}).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url).startswith(native.BASE_URL + "/")
    assert request.url.path == "/api/v1" + case["path"].replace("{id}", case["config"].get("id", ""))
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if case["method"] == "POST":
        assert not request.url.query
        body = json.loads(request.content)
        assert body["page_size"] == 10 and body["page"] == 0
        assert "operation" not in body and "api_key" not in body
    else:
        assert not request.content
        for key, value in case["config"].items():
            if key != "id" or "{id}" not in case["path"]:
                if key in {"start_date", "end_date"}:
                    assert datetime.fromisoformat(request.url.params[key]) == datetime.fromisoformat(value)
                else:
                    assert request.url.params[key] == value
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXTURE["published_responses"].values())
async def test_provider_published_response_envelopes(monkeypatch, case):
    operation = case["operation"]
    requests = transport(monkeypatch, case["body"])
    result = await node({"operation": operation, **FIXTURE["operations"][operation]["config"]}).run({})
    assert result["status"] == "success" and result["data"] == case["body"]["data"]
    assert result["meta"] == case["body"]["meta"] and len(requests) == 1
    if operation == "list_alert_configurations":
        assert result["items"] == case["body"]["data"]["configurations"]


@pytest.mark.asyncio
async def test_nested_discovery_filters_and_pagination_keep_their_boundaries(monkeypatch):
    requests = transport(monkeypatch, {"success": True, "data": {"companies": []},
        "meta": {"total_count": 80, "page": 2, "page_size": 10, "credits_used": 10}})
    result = await node({"operation": "search_companies", "company": {
        "industries": ["artificial-intelligence"], "locations": ["san-francisco-california"]},
        "latest_deal": {"date_start": "2024-01-01", "financing_types": [{"type": "SERIES_A"}]},
        "page": 2, "page_size": 10}).execute({})
    body = json.loads(requests[0].content)
    assert body["company"]["locations"] == ["san-francisco-california"]
    assert body["latest_deal"]["date_start"] == "2024-01-01"
    assert body["latest_deal"]["financing_types"][0]["type"] == "SERIES_A"
    assert result["meta"]["page"] == 2 and result["meta"]["total_count"] == 80
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_identifier_urls_are_query_values_and_not_destinations(monkeypatch):
    requests = transport(monkeypatch)
    value = "https://www.linkedin.com/in/eladgil/?a=1&b=2"
    await node({"operation": "get_person", "linkedin": value}).execute({})
    assert requests[0].url.host == "www.tryfundable.ai"
    assert dict(requests[0].url.params) == {"linkedin": value}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field,value", [
    ("unlock_person_email", "email", "jane@example.com"),
    ("unlock_person_phone", "phone", "+14155550123"),
])
async def test_unlocks_preserve_credit_and_prior_ownership_metadata(monkeypatch, operation, field, value):
    body = {"success": True, "data": {"person_id": "550e8400-e29b-41d4-a716-446655440000",
        field: value, "already_unlocked": False}, "meta": {"credits_used": 5, "page": 0, "page_size": 1}}
    requests = transport(monkeypatch, body)
    result = await node({"operation": operation, "id": body["data"]["person_id"]}).execute({})
    assert result["data"][field] == value and result["meta"]["credits_used"] == 5
    assert result["data"]["already_unlocked"] is False and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 204, 301, 302, 400, 401, 402, 403, 404, 429, 500])
async def test_http_failures_do_not_redirect_or_retry_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, {"success": False, "error": {"message": "Rejected " + TOKEN}}, status)
    result = await node({"operation": "unlock_person_email", "id": "550e8400-e29b-41d4-a716-446655440000"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,mime", [({}, "application/json"),
    ({"success": False, "error": {"message": "not available"}}, "application/json"),
    ({"success": True, "data": [], "meta": {}}, "application/json"),
    ({"success": True, "data": {}, "meta": {}}, "text/html"),
    ({"success": True, "data": {}, "meta": {}}, "application/json"),
])
async def test_malformed_or_error_envelopes_never_prove_connection(monkeypatch, body, mime):
    transport(monkeypatch, body, mime=mime)
    with pytest.raises(ValueError, match="Tryfundable|Expected bounded JSON"):
        await node({"operation": "list_alert_configurations"}).run({})


@pytest.mark.parametrize("config", [
    {"operation": "get_person"}, {"operation": "get_company", "id": "../other"},
    {"operation": "search_company", "name": "Acme", "domain": "acme.com"},
    {"operation": "search_people", "page_size": 501},
    {"operation": "search_deals", "page": True},
    {"operation": "search_companies", "company": {"unknown": "filter"}},
    {"operation": "get_alerts", "alert_ids": "not-a-uuid", "start_date": "2024-01-01T00:00:00Z", "end_date": "2024-12-31T23:59:59Z"},
    {"operation": "get_alerts", "alert_ids": "550e8400-e29b-41d4-a716-446655440000", "start_date": "2025-01-01T00:00:00Z", "end_date": "2024-12-31T23:59:59Z"},
])
def test_invalid_inputs_fail_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_api_key_default_normalization_and_plan_disclosure():
    value = native.TryfundableAPIKeyCredential(api_key=" " + TOKEN + " ")
    assert value.credential_type == "tryfundable_api_key" and value.api_key == TOKEN
    for key in ["Bearer " + TOKEN, "https://example.test/key", "<token>", "abc\nxyz"]:
        with pytest.raises((ValueError, ValidationError)):
            native.TryfundableAPIKeyCredential(api_key=key)
    assert native.TryfundableNode.connection_evidence.proves == "account"
    assert native.TryfundableNode.connection_evidence.operation == "list_alert_configurations"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,message,reachable", [
    (401, "API key not provided", False),
    (403, "This endpoint requires a Pro+ or Enterprise plan.", None),
])
async def test_account_evidence_distinguishes_dead_keys_from_plan_restrictions(monkeypatch, status, message, reachable):
    from nodes.core.connection_evidence import collect_evidence
    import nodes.core.run_op as run_op

    requests = transport(monkeypatch, {"success": False, "error": {"message": message}}, status)
    async def perform(**kwargs):
        assert kwargs["operation"] == "list_alert_configurations"
        return await node({"operation": kwargs["operation"]}).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", perform)
    result = await collect_evidence(node_type="automation-tryfundable", user_id="test-user",
        credential_data={"credential_type": "tryfundable_api_key", "api_key": TOKEN})
    assert result.reachable is reachable and len(requests) == 1
    if reachable is False:
        assert result.error == message + " (HTTP 401)"
