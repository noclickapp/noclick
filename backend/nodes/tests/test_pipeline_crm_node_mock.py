"""Exercise every Pipeline CRM operation at the HTTP boundary."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import pipeline_crm_node as native
from nodes.core.registry import NodeFactory

TOKEN = "pcrm_live_fixture_123456789"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/pipeline-crm/requests.json").read_text())
CREDENTIAL = {"credential_type": "pipeline_crm_api_token", "api_token": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="pipeline-fixture", node_type="automation-pipeline-crm",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, handler):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.url.host == "api.pipelinecrm.com"
        return handler(request)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.ROUTES)
async def test_every_operation_uses_exact_contract_route_method_and_envelope(monkeypatch, operation):
    method, resource, root = native.ROUTES[operation]
    cfg = {"operation": operation}
    if operation.startswith("create_"):
        cfg.update(FIXTURES[operation])
    elif operation.startswith("update_"):
        cfg.update(FIXTURES[operation.replace("update_", "create_")])
    if operation.startswith(("get_", "update_", "delete_")) and resource != "profile":
        cfg[operation.split("_", 1)[1] + "_id"] = 4521
    payload = {"entries": [{"id": 4521, "name": "Acme"}], "pagination": {"page": 1, "per_page": 50, "total": 70}} if operation.startswith("list_") else {"id": 4521, "name": "Acme", "api_key": "legacy-secret"}
    requests = transport(monkeypatch, lambda req: httpx.Response(204) if method == "DELETE" else httpx.Response(200, json=payload))
    result = await node(cfg).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/api/v3/" + resource + ("/4521" if operation.startswith(("get_", "update_", "delete_")) and resource != "profile" else "")
    if root:
        assert json.loads(request.content) == {root: {k: v for k, v in cfg.items() if k not in {"operation", operation.split("_", 1)[1] + "_id"}}}
    else:
        assert not request.content
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"page": "1", "per_page": "50"}
        assert result["has_more"] is True and result["next_page"] == 2
    assert TOKEN not in str(result) and "legacy-secret" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,key", [("list_deals", "deal_name"), ("list_people", "person_full_name"), ("list_companies", "company_name")])
async def test_name_filters_and_final_page(monkeypatch, operation, key):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={"entries": [], "pagination": {"page": 2, "per_page": 20, "total": 20}}))
    result = await node({"operation": operation, "name": "Acme + café", "page": 2, "per_page": 20}).run({})
    assert result["status"] == "success" and result["next_page"] is None and result["has_more"] is False
    assert requests[0].url.params["conditions[" + key + "]"] == "Acme + café"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 301, 401, 403, 404, 422, 429, 500])
async def test_errors_preserve_rejection_and_redact_secret(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={"error": "Rejected " + TOKEN}))
    result = await node({"operation": "get_profile"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"error": "secret"}, [], {}, {"entries": [], "pagination": {"page": "1"}}])
async def test_invalid_list_never_claims_success(monkeypatch, payload):
    transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    assert (await node({"operation": "list_deals"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_empty_update_refused_before_http_and_wrong_record_refused(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={"id": 999}))
    with pytest.raises(ValueError, match="at least one field"):
        await node({"operation": "update_deal", "deal_id": 4521}).execute({})
    assert requests == []
    assert (await node({"operation": "get_deal", "deal_id": 4521}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_timeout_on_write_reports_uncertainty(monkeypatch):
    def fail(req):
        raise httpx.ReadTimeout("timeout", request=req)
    transport(monkeypatch, fail)
    result = await node({"operation": "create_deal", "name": "Acme"}).execute({})
    assert result["status"] == "error" and result["write_may_have_occurred"] is True


def test_config_rejects_bad_bounds_and_missing_required_fields():
    for cfg in [{"operation": "get_deal", "deal_id": "../profile"}, {"operation": "create_person"}, {"operation": "create_calendar_entry", "name": "Task"}, {"operation": "list_deals", "per_page": 201}]:
        with pytest.raises((ValidationError, ValueError)):
            node(cfg)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"id": None}, {"id": True}, {"id": -1}])
async def test_single_record_requires_a_provider_id(monkeypatch, payload):
    transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    assert (await node({"operation": "get_profile"}).execute({}))["status"] == "error"
