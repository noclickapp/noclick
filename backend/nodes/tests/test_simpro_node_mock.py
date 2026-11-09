"""Simpro request, connection and response regressions through the actual factory.

All credentials and responses are synthetic; tests never contact a Simpro build.
The request fixture pins each operation's method, path and provider field names.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import simpro_node as native
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "simpro_api_key", "build_url": "https://example.simprosuite.com", "api_key": "synthetic-simpro-key"}
CASES = json.loads((Path(__file__).parent / "fixtures/simpro/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="simpro-test", node_type="automation-simpro",
        node_data={"config": config, "credentials": AUTH if credentials is None else credentials})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_simpro_all_requests_and_success_responses(monkeypatch, case):
    response = httpx.Response(case["status"], json=case["response"]) if case["status"] != 204 else httpx.Response(204)
    requests = transport(monkeypatch, response)
    result = await node(case["config"]).execute({})
    assert result["success"] is True
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "example.simprosuite.com"
    assert request.headers["Authorization"] == "Bearer synthetic-simpro-key"
    assert request.headers["Content-Type"] == "application/json"
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert dict(request.url.params) == ({"page": "1", "pageSize": "30"} if case["config"]["operation"].startswith("list_") and case["config"]["operation"] != "list_companies" else {})


@pytest.mark.asyncio
async def test_simpro_provider_pagination_and_terminal_page(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json=[{"ID": 123}], headers={"Result-Pages": "3", "Result-Total": "65"}))
    result = await node({"operation": "list_jobs", "company_id": 0, "page": 2}).execute({})
    assert result["next_page"] == 3 and result["total"] == 65
    result = await node({"operation": "list_jobs", "company_id": 0, "page": 3}).execute({})
    assert result["next_page"] is None


@pytest.mark.asyncio
async def test_simpro_company_evidence_uses_recognizable_names(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, httpx.Response(200, json=[{"ID": 0, "Name": "Example Services"}]))
    evidence = await collect_evidence(node_type="automation-simpro", user_id="simpro-fixture", credential_data=AUTH)
    assert evidence.reachable is True
    assert evidence.samples[0].label == "Example Services"
    assert len(requests) == 1 and requests[0].url.path == "/api/v1.0/companies/"


@pytest.mark.parametrize("url", ["http://example.simprosuite.com", "https://127.0.0.1", "https://example.simprosuite.com.evil.com", "https://example.simprosuite.com/api/", "https://user:secret@example.simprosuite.com", "https://example.simprosuite.com:443", "https://example.simprosuite.com?x=1", "https://example.simprosuite.com\n"])
def test_simpro_build_url_refuses_unsafe_destinations(url):
    # Whitespace around a pasted URL is normalized by the manual connect seam.
    if url.endswith("\n"):
        assert native.SimproAPIKeyCredential(**{**AUTH, "build_url": url}).build_url == AUTH["build_url"]
    else:
        with pytest.raises(ValidationError):
            native.SimproAPIKeyCredential(**{**AUTH, "build_url": url})


def test_simpro_manual_connect_fields_and_normalization():
    credential = native.SimproAPIKeyCredential(build_url=" https://Example.simprocloud.com/ ", api_key="synthetic-simpro-key")
    assert credential.credential_type == "simpro_api_key"
    assert credential.build_url == "https://example.simprocloud.com"


@pytest.mark.parametrize("config", [
    {"operation": "get_job", "company_id": 0, "job_id": "../123"},
    {"operation": "get_job", "company_id": -1, "job_id": 123},
    {"operation": "list_jobs", "company_id": 0, "page_size": 251},
    {"operation": "create_job", "company_id": 0, "job_type": "Invalid", "site": 123},
    {"operation": "create_quote", "company_id": 0, "quote_type": "Project", "site": 123},
    {"operation": "update_contact", "company_id": 0, "contact_id": 123},
    {"operation": "create_site", "company_id": 0, "name": "Fixture", "unsupported": True},
])
def test_simpro_invalid_config_refused_before_transport(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "https://evil.example"}), httpx.Response(401, text="Rejected synthetic-simpro-key"), httpx.Response(429, text="Too many requests"), httpx.Response(200, text="Login", headers={"Content-Type": "text/html"}), httpx.Response(200, json={"error": "Rejected"}), httpx.Response(200, json=[{}]), httpx.Response(204)])
async def test_simpro_redirects_errors_and_invalid_lists_fail(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_companies"}).execute({})
    assert AUTH["api_key"] not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_simpro_creation_requires_documented_created_status(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"ID": 123}))
    with pytest.raises(ValueError, match="Simpro HTTP 200"):
        await node({"operation": "create_site", "company_id": 0, "name": "Fixture"}).execute({})
