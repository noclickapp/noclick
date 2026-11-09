"""Offline factory and HTTP-boundary regressions for POMA Grill v3."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import poma_grill_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-poma-api-key-42"
CASES = json.loads((Path(__file__).parent / "fixtures/poma-grill/contract_cases.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="poma-test", node_type="automation-poma-grill",
        node_data={"config": config, "credentials": {"credential_type": "poma_grill_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_poma_grill_exact_contract_request_and_response(monkeypatch, case):
    requests = transport(monkeypatch, lambda req: httpx.Response(204) if case["body"] is None else
        httpx.Response(201 if case["operation"] == "ingest_document" else 200, json=case["body"]))
    result = await node({"operation": case["operation"], **case["config"]}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"] and req.url.path == "/v3" + case["path"]
    assert req.url.host == "api.poma-ai.com" and req.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result) and "provider-returned-secret" not in str(result)
    action = case["operation"]
    if action == "get_account":
        assert "api_key" not in result["data"] and result["data"]["username"] == "john_doe"
    elif action == "delete_job":
        assert result["accepted"] and result["best_effort"] and not result["deletion_verified"]
    else:
        assert result["data"] == case["body"]
    body = json.loads(req.content) if req.content else None
    if action in {"search", "search_document"}:
        assert body["query"] == case["config"]["query"] and body["return_assets"] is False
        assert "project_id" not in body and "operation" not in body
        if action == "search_document": assert body["doc_filter"] == "doc-1"
    elif action == "update_document_attributes":
        assert body == {"attributes": {"region": "apac", "obsolete_key": None}}
    elif action == "rename_project": assert body == {"name": "Renamed"}
    elif action == "ingest_document":
        assert body is None
        assert req.headers["X-Remote-URL"] == "https://example.com/documents/report.pdf"
        assert req.headers["Content-Type"] == "application/octet-stream"
    else: assert body is None
    if action in {"get_usage", "get_project_usage"}:
        assert dict(req.url.params) == {"chart": "false", "chartResolution": "week", "chartProduct": "all"}
    elif action == "list_documents": assert dict(req.url.params) == {"limit": "1", "cursor": "opaque+token"}
    elif action == "list_active_jobs": assert dict(req.url.params) == {"limit": "2"}
    else: assert not req.url.params
    if case["path"].startswith("/grill/") and "project_id" in case["config"]:
        assert req.headers["X-Project-ID"] == case["config"]["project_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 429, 500])
async def test_poma_grill_provider_error_is_not_success_and_never_retries(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={"error": "Rejected " + TOKEN, "code": status}))
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Rejected" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"error": "no access"},
    {"account_id": None, "username": None, "email": None, "plan": None}])
async def test_poma_grill_unexpected_identity_never_proves_connection(monkeypatch, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
async def test_poma_grill_encodes_document_path_and_preserves_attribute_schema(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={"doc_id": "a/b?c", "attributes": {}, "attribute_schema": {}}))
    await node({"operation": "update_document_attributes", "doc_id": "a/b?c",
        "attributes": {"reviewed_at": "2026-09-21T07:30:00Z"},
        "attribute_schema": {"reviewed_at": {"type": "datetime"}}}).execute({})
    assert requests[0].url.raw_path == b"/v3/grill/docs/a%2Fb%3Fc"
    assert json.loads(requests[0].content)["attribute_schema"] == {"reviewed_at": {"type": "datetime"}}


@pytest.mark.parametrize("config", [
    {"operation": "list_documents", "limit": 501},
    {"operation": "get_document", "doc_id": ".."},
    {"operation": "rename_project", "project_id": "not-a-uuid", "name": "Test"},
    {"operation": "search_document", "query": "What?"},
    {"operation": "update_document_attributes", "doc_id": "doc-1"},
    {"operation": "search", "query": "What?", "target_tokens": 99},
    {"operation": "search", "query": "What?", "attribute_filters": [{}]},
])
def test_poma_grill_invalid_inputs_fail_before_network(config):
    with pytest.raises(ValueError): node(config)


def test_poma_grill_manual_credential_has_default_tag_and_secret_validation():
    credential = native.PomaGrillAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "poma_grill_api_key" and credential.api_key == TOKEN
    for bad in ["https://example.com/key", "Bearer key", "<token>"]:
        with pytest.raises(ValidationError): native.PomaGrillAPIKeyCredential(api_key=bad)
