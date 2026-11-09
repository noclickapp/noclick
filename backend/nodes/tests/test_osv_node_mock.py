"""OSV route/body regressions; no credentials or live provider calls."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import osv_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / "fixtures/osv/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="osv-fixture", node_type="automation-osv", node_data={"config": config})


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXTURES, ids=lambda c: c["config"]["operation"])
async def test_osv_exact_operation_wire_and_response(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url) == native.BASE + case["path"]
    assert "authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    for key, value in case["response"].items():
        assert result[key] == value


@pytest.mark.asyncio
async def test_osv_empty_protobuf_page_and_cursor_only_are_valid(monkeypatch):
    transport(monkeypatch, {})
    assert (await node({"operation": "query_commit", "commit": "a" * 40}).execute({}))["vulns"] == []
    requests = transport(monkeypatch, {"next_page_token": "next-token"})
    out = await node({"operation": "query_commit", "commit": "a" * 40, "page_token": "previous-token"}).execute({})
    assert out["vulns"] == [] and out["next_page_token"] == "next-token"
    assert json.loads(requests[0].content)["page_token"] == "previous-token"


@pytest.mark.asyncio
async def test_osv_batch_preserves_independent_cursors_and_empty_results(monkeypatch):
    case = next(c for c in FIXTURES if c["config"]["operation"] == "query_batch")
    body = {"results": [{"next_page_token": "first-only"}, {}, {"vulns": []}]}
    transport(monkeypatch, body)
    assert (await node(case["config"]).execute({}))["results"] == body["results"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_osv_http_failures_raise(monkeypatch, status):
    transport(monkeypatch, {"message": "Provider error"}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "get_vulnerability"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"error": "failure"}, {"code": 3, "message": "bad query"}, {"vulns": "wrong"}, {"vulns": ["wrong"]}, {"next_page_token": 123}])
async def test_osv_malformed_or_error_response_is_rejected(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "query_commit", "commit": "a" * 40}).execute({})


@pytest.mark.asyncio
async def test_osv_wrong_vulnerability_and_batch_count_rejected(monkeypatch):
    transport(monkeypatch, {"id": "OTHER-123"})
    with pytest.raises(ValueError, match="different vulnerability"):
        await node({"operation": "get_vulnerability"}).execute({})
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match="input count"):
        await node({"operation": "query_batch", "queries": [{"commit": "a" * 40}]}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "query_commit", "commit": "../bad"},
    {"operation": "get_vulnerability", "vulnerability_id": "../query"},
    {"operation": "list_import_findings", "source": "../../x"},
    {"operation": "query_purl", "purl": "pkg:pypi/jinja2@3.1.4", "version": "3.1.4"},
    {"operation": "query_batch", "queries": [{"commit": "a" * 40, "version": "1.0"}]},
    {"operation": "query_batch", "queries": [{"package": {"name": "jinja2"}}]},
    {"operation": "query_batch", "queries": [{"package": {"purl": "pkg:pypi/jinja2", "name": "jinja2", "ecosystem": "PyPI"}}]},
    {"operation": "determine_version", "file_hashes": [{"file_path": "x.c", "hash": "not-md5"}]},
    {"operation": "map_ubuntu_packages", "ecosystem": "Ubuntu:24.04", "binary_names": []},
    {"operation": "create_vulnerability"},
])
def test_osv_invalid_inputs_rejected(config):
    with pytest.raises(ValueError):
        native.OsvNode.parse_config({"config": config})


def test_osv_schema_public_reachability_and_category_contract():
    assert native.OsvNode.connection_evidence.proves == "reachability"
    assert native.OsvNode.validate_config({"config": {"operation": "get_vulnerability"}, "credentials": {}})["valid"]
    schema = native.OsvFullConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 10
    assert "credential_type" not in str(schema)
