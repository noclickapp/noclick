"""Offline Tave request and response regressions; no real credentials or writes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import tave_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/tave/requests.json").read_text())["cases"]
TOKEN = "synthetic-tave-api-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="tave-fixture", node_type="automation-tave", node_data={
        "config": config,
        "credentials": credentials or {"credential_type": "tave_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, status, response):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=response)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_tave_exact_native_request_and_collection_metadata(monkeypatch, case):
    requests = transport(monkeypatch, case["status"], case["response"])
    result = await node(case["config"]).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"]
    assert req.url.host == "workspace.vsco.co"
    assert req.url.path == case["path"]
    assert req.headers["X-API-KEY"] == TOKEN
    assert "authorization" not in req.headers
    assert dict(req.url.params) == case["query"]
    assert (json.loads(req.content) if req.content else None) == case["body"]
    assert result["status"] == "success"
    if case["config"]["operation"].startswith("list_"):
        assert result["items"] == case["response"]["items"]
        assert result["meta"] == case["response"]["meta"]
    else:
        assert result["data"] == case["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_tave_provider_error_preserved_and_secret_redacted(monkeypatch, status):
    requests = transport(monkeypatch, status, {"message": "Key " + TOKEN + " rejected"})
    result = await node({"operation": "get_studio"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Key [redacted] rejected"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_tave_studio_evidence_empty_page_and_error_envelope(monkeypatch):
    transport(monkeypatch, 200, {"id": "01h35ccwymj5ctckp8px1azhg6", "name": "Portrait Studio"})
    result = await node({"operation": "get_studio"}).execute({})
    assert result["data"]["name"] == "Portrait Studio"
    assert native.TaveNode.connection_evidence.identity_operation == "get_studio"
    transport(monkeypatch, 200, {"type": "job-collection", "items": [], "meta": {"currentPage": 1, "totalPages": 0}})
    result = await node({"operation": "list_jobs"}).execute({})
    assert result["items"] == [] and result["status"] == "success"
    transport(monkeypatch, 200, {"error": "denied"})
    assert (await node({"operation": "get_studio"}).execute({}))["status"] == "error"
    transport(monkeypatch, 200, {"items": "unexpected"})
    with pytest.raises(ValueError, match="collection"):
        await node({"operation": "list_jobs"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../studio/me"},
    {"operation": "get_job", "job_id": "https://example.test"},
    {"operation": "list_jobs", "page_size": 9},
    {"operation": "list_jobs", "page": 0},
    {"operation": "create_task", "name": "Missing list"},
    {"operation": "update_task", "task_id": "01h35ccwymj5ctckp8px1azhg6", "completed": True},
    {"operation": "create_note", "content_html": ""},
    {"operation": "create_event", "name": "Session", "start_date": "2020-02-31"},
    {"operation": "list_jobs", "stage": "unknown"},
    {"operation": "get_studio", "url": "https://example.test"},
])
def test_tave_invalid_config_fails_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        native.TaveNode.parse_config({"config": config})


def test_tave_manual_credential_default_and_secret_shape():
    credential = native.TaveAPIKeyCredential.model_validate({"api_key": "  " + TOKEN + "  "})
    assert credential.credential_type == "tave_api_key" and credential.api_key == TOKEN
    schema = native.TaveAPIKeyCredential.model_json_schema()
    assert schema["required"] == ["api_key"]
    assert schema["properties"]["credential_type"]["default"] == "tave_api_key"
    for key in ["https://example.test/key", "Bearer secret", "bad\r\nheader"]:
        with pytest.raises(ValueError):
            native.TaveAPIKeyCredential(api_key=key)
