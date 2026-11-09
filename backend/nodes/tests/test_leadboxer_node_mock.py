"""Exercise the native node against isolated HTTP contract fixtures."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import leadboxer_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/leadboxer/requests.json").read_text())
TOKEN = "synthetic-leadboxer-key"
CREDENTIAL = {"credential_type": "leadboxer_api_key", "api_key": TOKEN, "email": "jane.doe@leadboxer.com"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="leadboxer-test", node_type="automation-leadboxer",
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_contract_routes_parameters_bodies_and_response(monkeypatch, operation):
    case = CASES[operation]
    config = case["config"]
    payload = {"data": [{"datasetId": "owned", "humanName": "Sales"}], "metaData": {"nextToken": "provider-token"}} if operation.startswith("list_") else {"id": 42, "organizationName": "Example"}
    response = httpx.Response(204) if case["status"] == 204 else httpx.Response(200, json=payload)
    requests = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["http_status"] == case["status"]
    assert len(requests) == 1
    request = requests[0]
    path = case["path"].replace("{leadId}", str(config.get("leadId", ""))).replace("{segmentId}", str(config.get("segmentId", "")))
    assert request.url.host == "api.leadboxer.com" and request.url.path == path
    assert request.method == case["method"] and request.headers["x-api-key"] == TOKEN
    values = {**node(config).config.config.model_dump(exclude_none=True), "email": CREDENTIAL["email"]}
    assert dict(request.url.params) == {k: str(values[k]) for k in case["query"] if k in values}
    if case["body_fields"]:
        assert json.loads(request.content) == {k: values[k] for k in case["body_fields"] if k in values}
    else:
        assert not request.content
    if operation.startswith("list_"):
        assert result["data"] == payload["data"] and result["metaData"] == payload["metaData"]
    elif case["status"] == 204:
        assert result["acknowledged"] is True
    else:
        assert result["data"] == payload


@pytest.mark.asyncio
async def test_datasets_evidence_redacts_provider_secrets(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"data": [{"datasetId": "owned", "humanName": "Sales", "apiKey": "other-key", "accessToken": "other-token", "nested": {"message": TOKEN}}]}))
    result = await node({"operation": "list_datasets"}).execute({})
    assert result["data"][0]["humanName"] == "Sales"
    assert all(secret not in str(result) for secret in (TOKEN, "other-key", "other-token"))
    assert native.LeadboxerNode.connection_evidence.operation == "list_datasets"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_failures_never_claim_success_or_echo_key(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"message": TOKEN}))
    result = await node({"operation": "delete_segment", "segmentId": 42}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_connection_rejection_preserves_provider_detail(monkeypatch):
    transport(monkeypatch, httpx.Response(403, json={"detail": "API license does not permit this dataset"}))
    result = await node({"operation": "list_datasets"}).execute({})
    assert result["message"] == "API license does not permit this dataset"
    assert result["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": {}}, [], "invalid"])
async def test_malformed_list_is_not_connection_proof(monkeypatch, payload):
    transport(monkeypatch, httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node({"operation": "list_datasets"}).execute({})


@pytest.mark.asyncio
async def test_provider_next_token_and_filters_are_preserved(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={"data": [], "metaData": {"nextToken": "next-page"}}))
    config = {"operation": "list_leads", "site": "owned", "criteriaTimeFilter": "eventEsTimestamp|lessthan|6", "nextToken": "previous+/=", "criteriaTextFilter": "organizationName.raw|contains|Acme & Co"}
    result = await node(config).execute({})
    assert requests[0].url.params["nextToken"] == "previous+/="
    assert requests[0].url.params["criteriaTextFilter"] == config["criteriaTextFilter"]
    assert result["metaData"]["nextToken"] == "next-page"


@pytest.mark.parametrize("key", ["https://example.com/key", "<token>", "bad\nkey", "", "é"])
def test_pasted_key_validation(key):
    with pytest.raises(ValidationError):
        native.LeadboxerAPIKeyCredential(api_key=key, email=CREDENTIAL["email"])


def test_manual_credential_default_and_config_boundaries():
    assert native.LeadboxerAPIKeyCredential(api_key=TOKEN, email=CREDENTIAL["email"]).credential_type == "leadboxer_api_key"
    for config in [
        {"operation": "get_lead", "leadId": "../escape", "site": "owned"},
        {"operation": "list_events", "site": "owned", "sessionId": "s", "limit": 101},
        {"operation": "delete_segment", "segmentId": 0},
        {"operation": "create_segment", "name": "x"},
    ]:
        with pytest.raises(ValueError):
            node(config)
