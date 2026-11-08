"""Offline request/response regressions; fixtures are synthetic, not live evidence."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import wistia_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "wistia-synthetic-test-token"
CASES = json.loads((Path(__file__).parent / "fixtures/wistia/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="wistia-test", node_type="automation-wistia", node_data={
        "config": config, "credentials": {"credential_type": "wistia_api_token", "api_token": TOKEN}})


def transport(monkeypatch, reply):
    calls = []
    def handler(request):
        calls.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_contract_request_and_documented_envelope(monkeypatch, case):
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json=case["response"]) if case["response"] is not None else httpx.Response(200))
    result = await node(case["config"]).execute({})
    assert NODE_REGISTRY["automation-wistia"] is native.WistiaNode
    assert result["status"] == "success" and result["data"] == case["response"]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.host == "api.wistia.com"
    assert request.url.raw_path.split(b"?")[0].decode() == "/modern" + case["path"]
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["x-wistia-api-version"] == "2026-09"
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["config"]["operation"] == "list_media":
        assert dict(request.url.params) == {"page": "1", "per_page": "25", "name": "Launch + café", "archived": "false"}
    if case["config"]["operation"] == "list_folders":
        assert dict(request.url.params) == {"page": "2", "per_page": "1"}
        assert result["has_more"] and result["next_page"] == 3
    if case["config"]["operation"] == "import_media":
        assert result["import_completed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
async def test_errors_redact_secret_and_do_not_retry_or_follow(monkeypatch, status):
    calls = transport(monkeypatch, lambda _: httpx.Response(status, text="Denied " + TOKEN, headers={"Location": "https://example.com"}))
    result = await node({"operation": "get_account"}).execute({})
    assert len(calls) == 1 and result["status"] == "error"
    assert result["http_status"] == status and TOKEN not in str(result)
    assert result["message"] == "Denied [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>oops</html>"), httpx.Response(200, json=[]), httpx.Response(200, json={"error": "denied"}), httpx.Response(200, content=b"{", headers={"content-type": "application/json"})])
async def test_malformed_success_is_not_connection_proof(monkeypatch, response):
    transport(monkeypatch, lambda _: response)
    with pytest.raises(ValueError):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
async def test_empty_page_and_nested_secret_redaction(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json=[]))
    result = await node({"operation": "list_media"}).execute({})
    assert result["data"] == [] and result["next_page"] is None
    transport(monkeypatch, lambda _: httpx.Response(200, json={"id": 123, "name": "Acme", "nested": [TOKEN]}))
    assert TOKEN not in str(await node({"operation": "get_account"}).execute({}))


@pytest.mark.asyncio
async def test_write_timeout_does_not_retry(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("private " + TOKEN, request=request)
    calls = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="inspect write outcomes") as exc:
        await node({"operation": "create_tag", "name": "launch"}).execute({})
    assert TOKEN not in str(exc.value) and len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_media", "media_id": "../other"},
    {"operation": "get_folder", "folder_id": "x/y"},
    {"operation": "update_media", "media_id": "abc"},
    {"operation": "update_folder", "folder_id": "abc"},
    {"operation": "list_media", "per_page": 101},
    {"operation": "list_media", "page": 0},
    {"operation": "import_media", "url": "https://user:secret@example.com/a"},
    {"operation": "import_media", "url": "file:///etc/passwd"},
    {"operation": "create_captions", "media_id": "abc", "caption_file": "captions", "language": "english"},
])
def test_invalid_inputs_rejected_before_network(config):
    assert not native.WistiaNode.validate_config({"config": config})["valid"]


def test_token_cleaning_and_account_specific_connection_evidence():
    credential = native.WistiaAPITokenCredential(api_token=" " + TOKEN + " ")
    assert credential.api_token == TOKEN
    for value in ["https://example.com/token", "Bearer " + TOKEN, "<token>"]:
        with pytest.raises(ValidationError):
            native.WistiaAPITokenCredential(api_token=value)
    evidence = native.WistiaNode.connection_evidence
    assert evidence.operation == "list_media" and evidence.identity_operation == "get_account"
    assert evidence.proves == "account"
