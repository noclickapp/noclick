"""Chmeetings contract requests at the HTTP boundary, plus failure handling."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import chmeetings_node as chmeetings
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-chmeetings-api-key"
CASES = json.loads((Path(__file__).parent / "fixtures/chmeetings/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="chmeetings-fixture", node_type="automation-chmeetings", node_data={
        "config": config, "credentials": credentials or {"credential_type": "chmeetings_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, status=200, body=None, raw=None):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"Retry-After": "5"},
                              **({"content": raw} if raw is not None else {"json": body} if body is not None else {}))

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(chmeetings, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_chmeetings_contract_requests(monkeypatch, case):
    requests = transport(monkeypatch, case["status"], case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["http_status"] == case["status"]
    assert result["data"] == (case["response"].get("data", case["response"]) if case["response"] is not None else None)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"] and req.url.path == case["path"]
    assert str(req.url.copy_with(query=None)) == "https://api.chmeetings.com" + case["path"]
    assert req.headers["apikey"] == TOKEN and "Authorization" not in req.headers
    assert dict(req.url.params) == case.get("query", {})
    assert (json.loads(req.content) if req.content else None) == case.get("body")
    if case["method"] != "GET":
        assert result["write_acknowledged"] is True
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_chmeetings_paging_and_encoding(monkeypatch):
    requests = transport(monkeypatch, body={"data": [{"id": 12}], "paging": {"page": 2, "page_size": 1, "total_count": 3}, "errors": None})
    result = await node({"operation": "list_people", "page": 2, "page_size": 1, "name": "R&D + café"}).execute({})
    assert result["items"] == [{"id": 12}] and result["next_page"] == 3 and result["has_more"] is True
    assert requests[0].url.params["name"] == "R&D + café"
    assert requests[0].url.params["include_organizations"] == "false"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"errors": ["Invalid API key"]}), (403, {"errors": ["Access denied"]}),
    (429, {"errors": ["Rate limit exceeded"]}), (500, None), (302, None),
    (200, {"status_code": 400, "errors": ["Invalid request"]}), (200, {"status_code": "403"})])
async def test_chmeetings_errors_and_no_retries(monkeypatch, status, body):
    requests = transport(monkeypatch, status, body)
    result = await node({"operation": "list_groups"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["retry_after"] == "5" and len(requests) == 1
    if body and body.get("errors"):
        assert result["error"] == body["errors"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": {}}, {"data": []}, {"data": [], "paging": {"page": 2, "page_size": 100, "total_count": 1}}])
async def test_chmeetings_invalid_paged_response(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node({"operation": "list_families"}).execute({})


@pytest.mark.asyncio
async def test_chmeetings_secret_redaction(monkeypatch):
    transport(monkeypatch, status=401, body={"errors": ["Rejected " + TOKEN]})
    result = await node({"operation": "list_groups"}).execute({})
    assert TOKEN not in json.dumps(result) and "[redacted]" in json.dumps(result)


@pytest.mark.asyncio
async def test_chmeetings_invalid_json_and_missing_body(monkeypatch):
    transport(monkeypatch, raw=b"<html>Proxy unavailable</html>")
    with pytest.raises(ValueError, match="unexpected response"):
        await node({"operation": "list_groups"}).execute({})
    transport(monkeypatch)
    with pytest.raises(ValueError, match="omitted"):
        await node({"operation": "get_group", "group_id": 12}).execute({})


@pytest.mark.parametrize("config", [{"operation": "get_person", "id": "../people"},
    {"operation": "get_group", "group_id": 0}, {"operation": "list_people", "page_size": 101},
    {"operation": "create_person", "first_name": "Emily"}, {"operation": "create_group", "name": "x" * 101},
    {"operation": "create_note", "person_id": 12, "note": ""}, {"operation": "list_groups", "url": "https://evil.example"}])
def test_chmeetings_invalid_inputs(config):
    with pytest.raises(ValueError):
        node(config)


def test_chmeetings_key_and_unset_defaults():
    with pytest.raises(ValidationError):
        chmeetings.ChmeetingsAPIKeyCredential(api_key="https://api.chmeetings.com")
    assert chmeetings.ChmeetingsAPIKeyCredential(api_key="  " + TOKEN + "  ").api_key == TOKEN
    parsed = chmeetings.ChmeetingsNode.parse_config({"config": {"operation": "list_people", "page": "", "include_groups": None}})
    assert parsed.config.page == 1 and parsed.config.include_groups is False
