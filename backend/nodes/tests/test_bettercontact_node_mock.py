"""Offline request/response regressions; no provider credentials or live writes."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import bettercontact_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-bettercontact-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="bettercontact-test", node_type="automation-bettercontact",
        node_data={"config": config, "credentials": {"credential_type": "bettercontact_api_key", "api_key": KEY}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,expected", [
    ({"operation": "create_enrichment", "data": [{"first_name": "Elon", "last_name": "Musk", "company_domain": "tesla.com", "custom_fields": {"crm_id": "a-42"}}], "enrich_email_address": False, "enrich_phone_number": True}, "/async", {"enrich_email_address": False, "enrich_phone_number": True}),
    ({"operation": "create_lead_finder_search", "filters": {"lead_job_title": {"include": ["Account Executive"], "exclude": ["Assistant"], "exact_match": True}, "is_b2b": False}, "limit": 25, "offset": 50}, "/lead_finder/async", {"limit": 25, "offset": 50}),
    ({"operation": "create_company_finder_search", "filters": {"company_industry": {"include": ["Software Development"]}}, "limit": 25, "offset": 25}, "/company_finder/async", {"limit": 25, "offset": 25}),
    ({"operation": "enrich_company", "company_domain": "microsoft.com"}, "/enrich_profile/company", {"company_domain": "microsoft.com"}),
    ({"operation": "enrich_lead_by_linkedin", "linkedin_url": "https://www.linkedin.com/in/veronick-martinuzzi-a4533373"}, "/enrich_profile/lead", {"linkedin_url": "https://www.linkedin.com/in/veronick-martinuzzi-a4533373"}),
    ({"operation": "enrich_lead_by_name", "first_name": "Veronick", "last_name": "Martinuzzi", "company_domain": "hondaresearch.com"}, "/enrich_profile/lead", {"first_name": "Veronick", "last_name": "Martinuzzi", "company_domain": "hondaresearch.com"}),
])
async def test_writes_preserve_identifiers_filters_false_and_pagination(monkeypatch, config, path, expected):
    requests = transport(monkeypatch, {"success": True, "request_id": "bc39ffbfc24cf043b748"}, 202)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == "POST" and str(request.url) == native.BASE + path
    assert request.headers["X-API-Key"] == KEY and not request.url.query
    body = json.loads(request.content)
    assert all(body[k] == v for k, v in expected.items())
    assert "api_key" not in body and "operation" not in body
    if config["operation"] == "create_enrichment":
        assert body["data"][0]["custom_fields"] == {"crm_id": "a-42"}
    if config["operation"] == "create_lead_finder_search":
        assert body["filters"] == config["filters"]


@pytest.mark.asyncio
async def test_account_evidence_uses_credential_only_and_preserves_identity(monkeypatch):
    body = {"success": True, "email": "your_email@mycompany.com", "credits_left": 32377}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "get_account"}).execute({})
    assert result["email"] == body["email"] and result["credits_left"] == 32377
    assert result["data"] == body
    assert requests[0].method == "GET" and requests[0].url.path == "/api/v2/account"
    assert not requests[0].content and not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,prefix,collection", [
    ("get_enrichment", "/async/", "data"),
    ("get_lead_finder_search", "/lead_finder/async/", "leads"),
    ("get_company_finder_search", "/company_finder/async/", "companies"),
])
@pytest.mark.parametrize("state,code", [("processing", 202), ("on_hold", 200), ("terminated", 200)])
async def test_async_status_is_independent_of_http_status(monkeypatch, operation, prefix, collection, state, code):
    body = {"id": "bc39ffbfc24cf043b748", "status": state, "credits_left": "999.0"}
    if state == "terminated":
        body[collection] = []
    requests = transport(monkeypatch, body, code)
    result = await node({"operation": operation, "request_id": body["id"]}).execute({})
    assert result["status"] == "success" and result["complete"] == (state == "terminated")
    assert result["data"] == body and result["request_status"] == state
    assert requests[0].method == "GET" and requests[0].url.path == "/api/v2" + prefix + body["id"]
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 402, 404, 406, 422, 429, 500])
async def test_provider_errors_no_retries_and_secret_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {"success": False, "error": "Rejected " + KEY}, status)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert KEY not in str(result) and "Rejected" in result["error"] and len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_on_200_does_not_prove_a_connection(monkeypatch):
    transport(monkeypatch, {"success": False, "error": "Your are not authorized. Please check your api_key."})
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["error"] == "Your are not authorized. Please check your api_key."


@pytest.mark.asyncio
async def test_incomplete_account_cannot_claim_identity(monkeypatch):
    transport(monkeypatch, {"success": True})
    with pytest.raises(ValueError, match="identity"):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_enrichment", "request_id": "../account"},
    {"operation": "get_enrichment", "request_id": "x?api_key=y"},
    {"operation": "create_enrichment", "data": []},
    {"operation": "create_enrichment", "data": [{"first_name": "Elon", "last_name": "Musk"}]},
    {"operation": "create_enrichment", "data": [{"first_name": "Elon", "last_name": "Musk", "company": "Tesla"}], "enrich_profile": True},
    {"operation": "create_company_finder_search", "filters": {"company": {"exclude": ["acme.com"]}}},
    {"operation": "create_company_finder_search", "filters": {}},
    {"operation": "create_lead_finder_search", "filters": {"company": {"include": []}}},
    {"operation": "create_company_finder_search", "filters": {"is_b2b": True}, "limit": 201},
    {"operation": "create_lead_finder_search", "filters": {"lead_job_title": {}}},
    {"operation": "create_lead_finder_search", "filters": {"limit_per_company": 3}},
    {"operation": "enrich_company"},
    {"operation": "enrich_lead_by_name", "first_name": "Veronick", "last_name": "Martinuzzi"},
])
def test_invalid_requests_fail_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_has_default_type_and_password_field():
    credential = native.BettercontactAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == "bettercontact_api_key"
    assert "API Key" in native.BettercontactAPIKeyCredential.model_json_schema()["title"]
    assert KEY not in repr(credential)
