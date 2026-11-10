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


WEBHOOK_EVENT = json.loads((Path(__file__).parent / "fixtures/heygen/video_completed.json").read_text())["body"]
WEBHOOK_CREATED = json.loads((Path(__file__).parent / "fixtures/heygen/webhook_created.json").read_text())["body"]

@pytest.mark.asyncio
async def test_webhook_lifecycle_uses_documented_endpoint_and_secret(monkeypatch):
    calls = transport(monkeypatch, WEBHOOK_CREATED)
    config = {"operation": "on_video_completed"}
    credential = {"api_key": TOKEN}
    registration = await native.HeyGenNode._register_external_webhook(
        webhook_url="https://test.hooks.example.test/webhook", credential=credential, config=config, node_id="heygen-test")
    assert registration == {"external_webhook_id": "ep_abc123", "signing_secret": "whsec_k7x9m2..."}
    assert calls[0].method == "POST" and calls[0].url.path == "/v3/webhooks/endpoints"
    assert json.loads(calls[0].content) == {"url": "https://test.hooks.example.test/webhook", "events": ["avatar_video.success"]}
    assert calls[0].headers["x-api-key"] == TOKEN
    # Undo the client patch before installing the deletion transport.
    monkeypatch.undo()
    calls = transport(monkeypatch, {"data": {}})
    await native.HeyGenNode._unregister_external_webhook(
        credential=credential, config={**config, **registration}, node_id="heygen-test")
    assert calls[0].method == "DELETE" and calls[0].url.path == "/v3/webhooks/endpoints/ep_abc123"
    assert calls[0].content == b""

@pytest.mark.parametrize("data", [{}, {"endpoint_id": "ep_abc123"}, {"secret": "whsec_test"}])
@pytest.mark.asyncio
async def test_webhook_registration_requires_secret_and_id(monkeypatch, data):
    transport(monkeypatch, {"data": data})
    with pytest.raises(ValueError, match="endpoint ID and signing secret"):
        await native.HeyGenNode._register_external_webhook(webhook_url="https://test.hooks.example.test/webhook",
            credential={"api_key": TOKEN}, config={"operation": "on_video_completed"}, node_id="heygen-test")

@pytest.mark.asyncio
async def test_webhook_teardown_failure_is_not_silently_lost(monkeypatch):
    transport(monkeypatch, {"error": {"message": TOKEN}}, status=401)
    with pytest.raises(ValueError, match="HTTP 401") as error:
        await native.HeyGenNode._unregister_external_webhook(credential={"api_key": TOKEN},
            config={"external_webhook_id": "ep_abc123"}, node_id="heygen-test")
    assert TOKEN not in str(error.value)


def test_webhook_signature_is_raw_body_hmac_sha256_with_verbatim_secret():
    import hashlib
    import hmac
    raw = json.dumps(WEBHOOK_EVENT, indent=2).encode()
    secret = "whsec_k7x9m2..."
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    verify = native.HeyGenNode.verify_webhook_signature
    assert verify(raw, {"Signature": signature}, {"signing_secret": secret})
    assert not verify(raw + b" ", {"signature": signature}, {"signing_secret": secret})
    assert not verify(raw, {"signature": signature}, {"signing_secret": "wrong"})
    assert not verify(raw, {"signature": signature}, {})
    for value in ("", "bad", "sha256=" + signature, "☃"):
        assert not verify(raw, {"signature": value}, {"signing_secret": secret})

@pytest.mark.asyncio
async def test_documented_completion_reaches_workflow_and_human_shaped_agent_turn():
    config = {"operation": "on_video_completed"}
    cls = native.HeyGenNode
    assert cls.filter_trigger_payload(WEBHOOK_EVENT, config)
    output = cls.resolve_trigger_payload(WEBHOOK_EVENT, config)
    assert output == {"status": "success", "event_type": "avatar_video.success", "data": WEBHOOK_EVENT["event_data"]}
    assert await node(config).execute(WEBHOOK_EVENT) == output
    event = cls.resolve_agent_event(output)
    assert event["conversation_key"] == "vid_xyz789"
    assert "completed avatar video vid_xyz789" in event["text"]
    assert "https://files.heygen.com/video/vid_xyz789.mp4" in event["text"]
    assert "get_video video_id=vid_xyz789" in event["text"]
    assert "_webhook" not in event["text"] and "signing_secret" not in event["text"]
    assert not cls.filter_trigger_payload({**WEBHOOK_EVENT, "event_type": "avatar_video.fail"}, config)
    assert not cls.filter_trigger_payload(WEBHOOK_EVENT, {"operation": "list_videos"})
    with pytest.raises(ValueError, match="video ID"):
        cls.resolve_trigger_payload({"event_type": "avatar_video.success", "event_data": {}}, config)
    parsed = node({**config, "external_webhook_id": "ep_abc123", "signing_secret": "whsec_test"})
    assert parsed.config.config.model_dump()["signing_secret"] == "whsec_test"
