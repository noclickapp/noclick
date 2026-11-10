"""Verify hashlookup requests and preserve the provider's published JSON examples.

The transport is mocked; neither accounts nor live hash searches are required.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import circl_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures/circl"
CASES = json.loads((FIXTURES / "documented.json").read_text())
README = json.loads((FIXTURES / "readme-examples.json").read_text())["examples"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="circl-test", node_type="automation-circl", node_data={"config": config})


def transport(monkeypatch, body, status=200, media="application/json"):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"content-type": media})

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_circl_documented_queries(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == case["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url) == native.BASE + case["path"]
    assert "authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    if request.method == "POST":
        assert request.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_circl_parent_pagination_uses_documented_opaque_cursor(monkeypatch):
    config = {"operation": "get_parents", "sha1": "732458574c63c3790cad093a36eadfb990d11ee6", "count": 10}
    requests = transport(monkeypatch, README[5])
    first = await node(config).execute({})
    assert first["data"] == README[5]
    assert requests[0].url.path.endswith("/10/0")
    config["cursor"] = first["data"]["cursor"]
    requests = transport(monkeypatch, README[6])
    second = await node(config).execute({})
    assert requests[0].url.path.endswith("/10/" + README[5]["cursor"])
    assert second["data"] == README[6]
    assert second["data"]["total"] == 42


def test_circl_numeric_cursor_is_accepted_by_runtime_config_lens():
    parsed = native.CirclNode.parse_config({"config": {"operation": "get_children", "sha1": "a" * 40, "cursor": 42}})
    assert parsed.config.cursor == "42"


@pytest.mark.asyncio
async def test_circl_optional_sessions_and_lookup_header(monkeypatch):
    for operation, action, body in [("create_session", "create", README[7]), ("get_session", "get", README[8])]:
        requests = transport(monkeypatch, body)
        out = await node({"operation": operation, "name": "test", "server_url": "https://hashes.example.org/"}).execute({})
        assert out["data"] == body
        assert str(requests[0].url) == f"https://hashes.example.org/session/{action}/test"
        assert requests[0].method == "GET"
    case = CASES[1]
    requests = transport(monkeypatch, case["response"])
    await node({**case["config"], "session_name": "test"}).execute({})
    assert requests[0].headers["hashlookup_session"] == "test"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path", [
    ({"operation": "get_children", "sha1": "a" * 40}, "/children/" + "a" * 40 + "/100/0"),
    ({"operation": "get_top"}, "/stats/top"),
])
async def test_circl_remaining_contract_routes(monkeypatch, config, path):
    # No published JSON example for these routes: this checks the wire only.
    requests = transport(monkeypatch, {})
    await node(config).execute({})
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == path


@pytest.mark.asyncio
async def test_circl_missing_hash_is_an_explicit_nonmatch(monkeypatch):
    transport(monkeypatch, {"message": "Non existing MD5"}, 404)
    out = await node(CASES[1]["config"]).execute({})
    assert out["status"] == "success" and out["found"] is False
    assert out["data"] == {"message": "Non existing MD5"}


@pytest.mark.asyncio
async def test_circl_wrong_hash_and_non_api_404_are_rejected(monkeypatch):
    transport(monkeypatch, {"MD5": "0" * 32})
    with pytest.raises(ValueError, match="requested file hash"):
        await node(CASES[1]["config"]).execute({})
    transport(monkeypatch, {}, 404, "text/html")
    with pytest.raises(ValueError, match="JSON"):
        await node(CASES[1]["config"]).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_circl_provider_failures_are_not_success(monkeypatch, status):
    transport(monkeypatch, {"message": "Feature is not enabled"}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "create_session", "name": "test"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body,media", [("not JSON object", "application/json"), ({"error": "bad"}, "application/json"), ({}, "text/html")])
async def test_circl_malformed_responses_are_rejected(monkeypatch, body, media):
    transport(monkeypatch, body, media=media)
    with pytest.raises(ValueError):
        await node({"operation": "get_info"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "lookup_md5", "md5": "not-a-hash"},
    {"operation": "lookup_sha1", "sha1": "../stats/top"},
    {"operation": "lookup_sha256", "sha256": "a" * 63},
    {"operation": "bulk_md5", "hashes": []},
    {"operation": "bulk_sha1", "hashes": ["a" * 32]},
    {"operation": "get_parents", "sha1": "a" * 40, "count": 0},
    {"operation": "get_children", "sha1": "a" * 40, "cursor": "../info"},
    {"operation": "create_session", "name": "x\r\nInjected: header"},
    {"operation": "get_info", "server_url": "http://hashes.example.org"},
    {"operation": "get_info", "server_url": "https://user:pass@hashes.example.org"},
    {"operation": "get_info", "server_url": "https://hashes.example.org/path"},
    {"operation": "get_info", "server_url": "https://hashes.example.org?secret=x"},
])
def test_circl_invalid_inputs_fail_before_request(config):
    with pytest.raises(ValueError):
        native.CirclNode.parse_config({"config": config})


def test_circl_public_schema_and_reachability_evidence():
    assert native.CirclNode.connection_evidence.proves == "reachability"
    assert native.CirclNode.validate_config({"config": {"operation": "get_info"}, "credentials": {}})["valid"]
    schema = native.CirclFullConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 11
    assert "credential_type" not in str(schema)
