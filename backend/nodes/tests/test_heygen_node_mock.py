"""Native factory and HTTP contract tests; no live key or provider writes."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import heygen_node as native
from nodes.core.registry import NodeFactory

TOKEN = "heygen-synthetic-key-42"
CASES = json.loads((Path(__file__).parent / "fixtures/heygen/requests.json").read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="heygen-test", node_type="automation-heygen", node_data={
        "config": config, "credentials": {"credential_type": "heygen_api_key", "api_key": TOKEN}})

def transport(monkeypatch, body, status=200, fail=False):
    calls = []
    original = httpx.AsyncClient
    def respond(request):
        calls.append(request)
        if fail:
            raise httpx.ReadTimeout(TOKEN, request=request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return calls

@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_documented_requests_and_response_envelopes(monkeypatch, case):
    calls = transport(monkeypatch, case["response"], case.get("status", 200))
    output = await node(case["config"]).execute({})
    assert output == {**case["response"], "status": "success"}
    assert len(calls) == 1
    request = calls[0]
    assert (request.method, request.url.host, request.url.path) == (case["method"], "api.heygen.com", case["path"])
    assert request.headers["x-api-key"] == TOKEN and "authorization" not in request.headers
    assert dict(request.url.params) == case.get("query", {})
    if "body" in case:
        assert json.loads(request.content) == case["body"]
    else:
        assert request.content == b""
    assert request.headers.get("idempotency-key") == case.get("idempotency_key")

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 409, 429, 500])
async def test_error_envelope_preserves_provider_message_and_redacts_key(monkeypatch, status):
    calls = transport(monkeypatch, {"error": {"message": "Invalid key " + TOKEN}}, status)
    result = await node({"operation": "get_current_user"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Invalid key [redacted]"}
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_ambiguous_write_is_never_retried_or_leaks_transport_text(monkeypatch):
    calls = transport(monkeypatch, {}, fail=True)
    with pytest.raises(ValueError, match="inspect the provider") as error:
        await node({"operation": "create_folder", "name": "Demo"}).execute({})
    assert TOKEN not in str(error.value) and len(calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": None}, [], {"data": "not a record"}])
async def test_invalid_success_does_not_claim_connection(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="invalid data envelope"):
        await node({"operation": "get_current_user"}).execute({})

@pytest.mark.asyncio
async def test_nested_success_strings_are_redacted_without_flattening_job_status(monkeypatch):
    transport(monkeypatch, {"data": {"status": "waiting", "nested": [TOKEN]}})
    assert await node({"operation": "get_video", "video_id": "v_abc"}).execute({}) == {
        "status": "success", "data": {"status": "waiting", "nested": ["[redacted]"]}}

@pytest.mark.parametrize("identifier", ["../videos", "v?x=1", "v/other", "v#fragment", ".", "https://example.com"])
def test_resource_path_injection_fails_before_request(identifier):
    with pytest.raises(ValueError):
        node({"operation": "get_video", "video_id": identifier})

@pytest.mark.parametrize("key", ["https://app.heygen.com", "<api-key>", "Bearer token", "bad\nheader", "bad☃key"])
def test_secret_paste_errors(key):
    with pytest.raises(ValueError):
        native.HeyGenAPIKey(api_key=key)

@pytest.mark.parametrize("config", [
    {"operation": "list_avatar_groups", "limit": 51},
    {"operation": "list_videos", "limit": 101},
    {"operation": "create_folder", "name": "Demo", "idempotency_key": "bad header"},
    {"operation": "create_video", "avatar_id": "a1", "voice_id": "voice1", "script": ""},
    {"operation": "create_translation", "video": {"type": "asset_id", "asset_id": "a1"}, "output_languages": []},
])
def test_contract_constraints_fail_before_request(config):
    with pytest.raises(ValueError):
        node(config)

@pytest.mark.asyncio
@pytest.mark.parametrize("data", [{}, [], {"username": ""}, {"username": None}])
async def test_account_evidence_requires_a_named_identity(monkeypatch, data):
    transport(monkeypatch, {"data": data})
    with pytest.raises(ValueError, match="no current-user identity"):
        await node({"operation": "get_current_user"}).execute({})

@pytest.mark.asyncio
async def test_translation_accepts_existing_asset_without_downloading_it(monkeypatch):
    calls = transport(monkeypatch, {"data": {"video_translation_ids": ["tr_abc"]}})
    await node({"operation": "create_translation", "video": {"type": "asset_id", "asset_id": "asset_abc"}, "output_languages": ["English"]}).execute({})
    assert json.loads(calls[0].content)["video"] == {"type": "asset_id", "asset_id": "asset_abc"}
    assert len(calls) == 1
