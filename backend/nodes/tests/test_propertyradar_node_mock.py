"""PropertyRadar native dispatch regressions using synthetic HTTP fixtures."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import propertyradar_node as native
from nodes.core.registry import NodeFactory

TOKEN = "propertyradar-fixture-token"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="propertyradar-fixture", node_type="automation-propertyradar",
        node_data={"config": config, "credentials": {"credential_type": "propertyradar_api_token", "api_token": TOKEN}})


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

CASES = json.loads((Path(__file__).parent / "fixtures/propertyradar/operations.json").read_text())

@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_every_native_operation_exact_contract_request(monkeypatch, case):
    count = native.MUTATION_OUTPUT.get(case["config"]["operation"])
    body = {count: 1} if count else {"results": []}
    requests = transport(monkeypatch, body)
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "operation": case["config"]["operation"], **body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url.copy_with(query=None)) == native.BASE + case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    assert TOKEN not in str(result)

@pytest.mark.asyncio
async def test_purchase_is_explicit_and_pagination_is_forwarded(monkeypatch):
    body = {"results": [{"RadarID": "P8A0E18D"}], "resultCount": 1, "nextPageToken": "opaque-next"}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "search_properties", "criteria": [{"name": "State", "value": ["OR"]}],
                         "purchase": 1, "start": 100, "limit": 50, "page_token": "opaque-previous"}).execute({})
    assert result["nextPageToken"] == "opaque-next"
    assert dict(requests[0].url.params) == {"Purchase": "1", "Start": "100", "Limit": "50", "PageToken": "opaque-previous"}
    assert json.loads(requests[0].content) == {"Criteria": [{"name": "State", "value": ["OR"]}]}

@pytest.mark.asyncio
async def test_empty_account_lists_are_valid_evidence_and_webhook_secrets_redacted(monkeypatch):
    transport(monkeypatch, {"results": []})
    assert (await node({"operation": "list_lists"}).execute({}))["results"] == []
    requests = transport(monkeypatch, {"results": [{"WebhookID": 123, "Secret": "hidden", "WebhookName": TOKEN}]})
    result = await node({"operation": "list_webhooks"}).execute({})
    assert result["results"] == [{"WebhookID": 123, "WebhookName": "[redacted]"}]
    assert "Secret" not in requests[0].url.params["Fields"]

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_failures_do_not_claim_success_and_keep_redacted_provider_text(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "list_lists"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Rejected" in result["error"] and TOKEN not in str(result) and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": "refused"}, {"results": {}}, {"results": None}])
async def test_unexpected_response_is_not_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_lists"}).execute({})

@pytest.mark.parametrize("config", [
    {"operation": "get_list", "list_id": 0},
    {"operation": "get_property", "radar_id": "../elsewhere"},
    {"operation": "get_property", "radar_id": "P123", "purchase": 2},
    {"operation": "create_list", "list_name": "Dynamic", "list_type": "dynamic"},
    {"operation": "create_list", "list_name": "Static", "criteria": [{"name": "State", "value": ["OR"]}]},
    {"operation": "update_list", "list_id": 123},
    {"operation": "add_items", "list_id": 123, "criteria": []},
    {"operation": "list_webhooks", "limit": 1001},
])
def test_invalid_inputs_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_credential_type_default_and_operation_coverage():
    assert native.PropertyRadarTokenCredential(api_token=TOKEN).credential_type == "propertyradar_api_token"
    assert {case["config"]["operation"] for case in CASES} == set(native.ROUTES)
    assert len(CASES) == 20


@pytest.mark.asyncio
async def test_documented_preview_omits_records_and_purchased_read_requires_records(monkeypatch):
    # The official contract explicitly documents omitted records in transaction previews.
    # Preserve estimated cost and counts without inventing purchased rows.
    body = {"totalCost": 1.5, "quantityFreeRemaining": 250, "resultCount": 20, "totalResultCount": 20}
    transport(monkeypatch, body)
    assert (await node({"operation": "get_transactions", "radar_id": "P8A0E18D"}).execute({}))["resultCount"] == 20
    with pytest.raises(ValueError):
        await node({"operation": "get_transactions", "radar_id": "P8A0E18D", "purchase": 1}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [-1, True, "1", None])
async def test_invalid_mutation_counts_refused(monkeypatch, count):
    transport(monkeypatch, {"updateCount": count})
    with pytest.raises(ValueError):
        await node({"operation": "update_list", "list_id": 123, "is_monitored": 1}).execute({})
