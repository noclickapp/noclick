"""CompanyEnrich request/response regressions using synthetic fixtures, no account."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError
from nodes import companyenrich_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/companyenrich/cases.json").read_text())
TOKEN = "synthetic-companyenrich-token"
CREDENTIAL = {"credential_type": "companyenrich_api_token", "api_token": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="fixture", node_type="automation-companyenrich",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, response, status=200):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=response)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_contract_routes_payloads_and_provider_responses(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node({"operation": case["operation"], **case["config"]}).execute({})
    assert result == {"status": "success", "data": case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.companyenrich.com"
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert parse_qs(request.url.query.decode()) == case["params"]
    assert (json.loads(request.content) if request.content else None) == case["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 402, 404, 422, 429, 500])
async def test_rejected_request_is_not_success_and_secret_is_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {"title": "Rejected", "detail": "Rejected " + TOKEN}, status)
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation, config, response", [
    ("get_current_user", {}, {}),
    ("search_companies", {}, []),
    ("delete_company_list", {"list_id": "123e4567-e89b-42d3-a456-426614174000"}, {"ok": True}),
])
async def test_malformed_responses_fail(monkeypatch, operation, config, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": operation, **config}).execute({})


@pytest.mark.asyncio
async def test_provider_cursor_and_nested_secret_preserved_or_redacted(monkeypatch):
    transport(monkeypatch, {"items": [], "nextCursor": "provider+opaque", "debug": [TOKEN]})
    result = await node({"operation": "search_companies"}).execute({})
    assert result["data"]["nextCursor"] == "provider+opaque"
    assert result["data"]["debug"] == ["[redacted]"]


@pytest.mark.parametrize("config", [
    {"operation": "get_company", "company_id": "../me"},
    {"operation": "get_person", "person_id": "../me"},
    {"operation": "batch_enrich_companies", "domains": []},
    {"operation": "batch_enrich_companies", "domains": ["a.com"] * 51},
    {"operation": "search_companies", "page_size": 101},
    {"operation": "enrich_company_properties", "name": "Example", "linkedin_url": "invalid"},
    {"operation": "enrich_company_domain", "domain": "example.com", "url": "https://evil.test"},
])
def test_inputs_enforce_contract_bounds_and_fixed_routes(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_default_and_connection_evidence():
    credential = native.CompanyenrichAPITokenCredential(api_token="  " + TOKEN + "  ")
    assert credential.credential_type == "companyenrich_api_token" and credential.api_token == TOKEN
    assert native.CompanyenrichNode.connection_evidence.identity_operation == "get_current_user"
    assert len(CASES) == len(native.ROUTES) == 20
    for token in ["Bearer secret", "https://example.com/token", "<token>"]:
        with pytest.raises(ValueError):
            native.CompanyenrichAPITokenCredential(api_token=token)


@pytest.mark.asyncio
async def test_manual_connection_displays_provider_account_id(monkeypatch):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence
    user_id = "123e4567-e89b-42d3-a456-426614174000"
    transport(monkeypatch, {"userId": user_id, "credits": {}, "capabilities": {}})
    async def run_operation(**kwargs):
        assert kwargs["operation"] == "get_current_user" and kwargs["arguments"] == {}
        assert kwargs["credential_data"] == CREDENTIAL
        return await node({"operation": kwargs["operation"]}).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", run_operation)
    result = await collect_evidence(node_type="automation-companyenrich", user_id="fixture", credential_data=CREDENTIAL)
    assert result.reachable is True and result.account_label == user_id
