"""Native factory and HTTP regressions against published API 1.0 fields."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import leadsforge_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/leadsforge/requests.json").read_text())["cases"]
TOKEN = "synthetic-leadsforge-key-12345"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="leadsforge-fixture", node_type="automation-leadsforge",
        node_data={"config": config, "credentials": {"credential_type": "leadsforge_api_key", "api_key": TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_published_request_boundaries(monkeypatch, case):
    response = {"jobs": [{"id": "job_abc123", "status": "completed"}], "nextCursor": "opaque-next", "total": 1}
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=response))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.leadsforge.ai" and request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers.get("Idempotency-Key") == case["config"].get("idempotency_key")
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["config"]["operation"] == "list_enrichment_jobs":
        assert result["items"] == response["jobs"]


@pytest.mark.asyncio
async def test_connection_defaults_and_empty_account(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"jobs": [], "total": 0}))
    result = await node({"operation": "list_enrichment_jobs"}).execute({})
    assert result["items"] == [] and dict(requests[0].url.params) == {"limit": "50"}
    assert native.LeadsforgeAPIKeyCredential(api_key=TOKEN).credential_type == "leadsforge_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 402, 403, 410, 429, 500])
async def test_rejection_redacts_key_and_never_retries(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"message": "Rejected " + TOKEN}, headers={"Location": "https://example.org"}))
    result = await node({"operation": "get_balance"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert result["message"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
async def test_nested_response_redaction(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={"value": [TOKEN, {TOKEN: TOKEN}]}))
    assert TOKEN not in str(await node({"operation": "get_balance"}).execute({}))


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], "not-json", {"jobs": None}])
async def test_bad_response_is_not_connection_evidence(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, text=body) if isinstance(body, str) else httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "list_enrichment_jobs"}).execute({})


@pytest.mark.asyncio
async def test_transport_failure_does_not_repeat_write(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout(TOKEN, request=request)
    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="check job status") as exc:
        await node({"operation": "find_emails", "request": {"personIDs": ["p_abc123"]}}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_enrichment_job", "jobID": "../balance"},
    {"operation": "list_enrichment_jobs", "limit": 0},
    {"operation": "list_enrichment_jobs", "limit": 101},
    {"operation": "list_enrichment_jobs", "offset": -1},
    {"operation": "list_enrichment_jobs", "status": "invented"},
    {"operation": "find_emails", "request": {"personIDs": []}},
    {"operation": "find_emails", "request": {"personIDs": ["p_abc123"] * 501}},
    {"operation": "search_maps", "request": {"categories": ["Dentist"], "radiusKm": 5}},
    {"operation": "search_maps", "request": {"categories": ["Dentist"], "radiusKm": 5, "limit": 200, "lat": 91}},
    {"operation": "search_company_followers", "request": {"linkedinUrl": "https://www.linkedin.com/company/salesforgeai", "limit": 50001}},
    {"operation": "search_lookalikes", "request": {"domains": [], "pageSize": 101}},
    {"operation": "start_salesnav_job", "request": {}},
    {"operation": "search_people", "request": {"limit": 2001}},
])
def test_invalid_request_is_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize("token", ["https://example.org/key", "Bearer abc", "abc\nxyz", ""])
def test_manual_credentials_refuse_headers_urls_and_empty_secrets(token):
    with pytest.raises(ValidationError):
        native.LeadsforgeAPIKeyCredential(api_key=token)
