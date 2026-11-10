"""Exercise ChatGPT actions through the native factory with a synthetic key.

Pin request serialization, pagination and provider failures without using an
OpenAI account or consuming API credits.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import chatgpt_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-openai-project-key-42"
EVENTS = json.loads((Path(__file__).parent / "fixtures/chatgpt/webhook_events.json").read_text())
ROUTES = json.loads((Path(__file__).parent / "fixtures/chatgpt/routes.json").read_text())
BODIES = {
    "search_vector_store": {"query": "What is the return policy?", "max_num_results": 10},
    "create_response": {"model": "gpt-4.1", "input": "Write a greeting.", "max_output_tokens": 64, "background": True},
    "create_chat_completion": {"model": "gpt-4.1", "messages": [{"role": "user", "content": "Hello!"}], "store": True},
    "create_embedding": {"model": "text-embedding-3-small", "input": ["Hello", "World"], "dimensions": 3},
    "create_moderation": {"input": "Hello!"},
    "create_batch": {"input_file_id": "file-abc123", "endpoint": "/v1/responses", "metadata": {"job": "nightly"}},
    "create_vector_store": {"name": "Support FAQ", "file_ids": ["file-abc123"]},
}
IDS = {"response_id": "resp_123", "completion_id": "chatcmpl-123", "model": "gpt-4.1", "file_id": "file-abc123", "batch_id": "batch_123", "vector_store_id": "vs_123"}


def signed_event(body, *, timestamp=None, event_id="wh_123"):
    import base64
    import hashlib
    import hmac
    import time
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = base64.b64encode(hmac.new(b"secret",
        event_id.encode() + b"." + timestamp.encode() + b"." + body, hashlib.sha256).digest()).decode()
    return {"webhook-id": event_id, "webhook-timestamp": timestamp, "webhook-signature": "v1," + signature}


@pytest.mark.parametrize("kind", native.CHATGPT_WEBHOOK_EVENTS)
def test_chatgpt_documented_event_reaches_agent(kind):
    event = EVENTS[kind]["body"]
    body = json.dumps(event).encode()
    config = {"operation": "on_event", "event_type": kind, "signing_secret": "whsec_c2VjcmV0"}
    headers = signed_event(body)
    assert native.ChatGPTNode.verify_webhook_signature(body, headers, config)
    assert not native.ChatGPTNode.verify_webhook_signature(body + b" ", headers, config)
    assert native.ChatGPTNode.filter_trigger_payload(event, config)
    output = native.ChatGPTNode.resolve_trigger_payload({**event, "_webhook": {"headers": headers}}, config)
    assert output["data"] == event
    agent = native.ChatGPTNode.resolve_agent_event(output)
    assert kind in agent["text"] and event["id"] in agent["text"] and event["data"]["id"] in agent["text"]
    assert agent["conversation_key"] == event["data"]["id"]
    assert "_webhook" not in str(output)
    other = dict(config, event_type="response.failed" if kind != "response.failed" else "response.completed")
    assert not native.ChatGPTNode.filter_trigger_payload(event, other)


def test_chatgpt_signature_matches_official_sdk_and_rejects_replays():
    import time
    from openai import OpenAI
    body = json.dumps(EVENTS["response.completed"]["body"]).encode()
    config = {"signing_secret": "whsec_c2VjcmV0"}
    headers = signed_event(body)
    headers["webhook-signature"] = "v1,bad " + headers["webhook-signature"]
    with OpenAI(api_key=TOKEN) as client:
        client.webhooks.verify_signature(body, headers, secret=config["signing_secret"])
    assert native.ChatGPTNode.verify_webhook_signature(body, {k.upper(): v for k, v in headers.items()}, config)
    for offset in (-301, 301):
        assert not native.ChatGPTNode.verify_webhook_signature(body, signed_event(body, timestamp=int(time.time()) + offset), config)
    for missing in headers:
        assert not native.ChatGPTNode.verify_webhook_signature(body, {k: v for k, v in headers.items() if k != missing}, config)
    assert not native.ChatGPTNode.verify_webhook_signature(body, headers, {"signing_secret": "whsec_!bad!"})
    assert not native.ChatGPTNode.verify_webhook_signature(body, headers, {})
    assert not native.ChatGPTNode.verify_webhook_signature(body, dict(headers, **{"webhook-id": "other"}), config)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", native.CHATGPT_WEBHOOK_EVENTS)
async def test_chatgpt_register_and_unregister_event(monkeypatch, kind):
    reply = {"id": "whe_123", "signing_secret": "whsec_c2VjcmV0"}
    requests = transport(monkeypatch, body=reply)
    config = {"operation": "on_event", "event_type": kind}
    credential = {"api_key": TOKEN}
    extra = await native.ChatGPTNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/test",
        credential=credential, config=config, node_id="chatgpt-fixture")
    assert extra == {"external_webhook_id": "whe_123", "signing_secret": reply["signing_secret"]}
    assert requests[0].method == "POST" and str(requests[0].url) == native.BASE + "/webhook_endpoints"
    assert json.loads(requests[0].content) == {"url": "https://hooks.hooks.example.test/test", "name": "NoClick chatgpt-fixture", "event_types": [kind]}
    assert requests[0].headers["authorization"] == "Bearer " + TOKEN
    await native.ChatGPTNode._unregister_external_webhook(credential=credential, config={**config, **extra}, node_id="chatgpt-fixture")
    assert requests[1].method == "DELETE" and str(requests[1].url) == native.BASE + "/webhook_endpoints/whe_123"
    assert native.ChatGPTNode.registration_fingerprint_fields(config) == {"event_type": kind}
    model = native.ChatGPTConfig.model_validate({"config": {**config, **extra}, "credentials": {"credential_type": "chatgpt_api_key", **credential}})
    assert model.config.signing_secret == reply["signing_secret"]


@pytest.mark.asyncio
async def test_chatgpt_trigger_manual_run_and_registration_errors(monkeypatch):
    assert (await node({"operation": "on_event"}).execute({}))["status"] == "no_event"
    transport(monkeypatch, body={"id": "whe_123"})
    with pytest.raises(ValueError, match="signing secret"):
        await native.ChatGPTNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/test",
            credential={"api_key": TOKEN}, config={}, node_id="test")
    transport(monkeypatch, status=403, body={"error": {"message": TOKEN}})
    with pytest.raises(ValueError, match="HTTP 403") as error:
        await native.ChatGPTNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/test",
            credential={"api_key": TOKEN}, config={}, node_id="test")
    assert TOKEN not in str(error.value)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="chatgpt-fixture", node_type="automation-chatgpt",
        node_data={"config": config, "credentials": {"credential_type": "chatgpt_api_key", "api_key": TOKEN}})


def transport(monkeypatch, status=200, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body if body is not None else {"id": "owned-result", "object": "fixture"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ROUTES)
async def test_chatgpt_factory_one_request_per_operation(monkeypatch, operation):
    method, route, has_body = ROUTES[operation]
    cfg = {"operation": operation, **BODIES.get(operation, {})}
    for field in native.re.findall(r"\{([^}]+)\}", route):
        cfg[field] = IDS[field]
        route = route.replace("{" + field + "}", IDS[field])
    reply = {"object": "list", "data": []} if operation == "list_models" else {"id": "owned-result", "object": "fixture"}
    requests = transport(monkeypatch, body=reply)
    assert await node(cfg).execute({}) == reply
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/v1" + route
    assert request.url.host == "api.openai.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if has_body:
        body = json.loads(request.content)
        assert all(body[k] == v for k, v in BODIES[operation].items())
        assert "operation" not in body
        if operation in {"create_response", "create_chat_completion"}:
            assert body["stream"] is False
        if operation == "create_embedding":
            assert body["encoding_format"] == "float"
        if operation == "create_batch":
            assert body["completion_window"] == "24h"
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_chatgpt_preserves_output_items_usage_and_pagination(monkeypatch):
    body = {"object": "list", "data": [{"id": "file-1"}], "has_more": True, "last_id": "file-1"}
    requests = transport(monkeypatch, body=body)
    assert await node({"operation": "list_files", "limit": 10, "after": "file-0", "purpose": "batch", "order": "asc"}).execute({}) == body
    assert dict(requests[0].url.params) == {"limit": "10", "after": "file-0", "purpose": "batch", "order": "asc"}
    assert len(requests) == 1
    response = {"id": "resp_123", "status": "completed", "error": None,
        "output": [{"type": "reasoning", "summary": []}, {"type": "message", "content": [{"type": "output_text", "text": "Hello"}]}], "usage": {"total_tokens": 12}}
    transport(monkeypatch, body=response)
    assert await node({"operation": "get_response", "response_id": "resp_123"}).execute({}) == response


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_chatgpt_provider_rejections_are_not_success_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={"error": {"message": "Rejected " + TOKEN}})
    result = await node({"operation": "list_models"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["../files", "a/b", "a\\b", "https://evil.test", ".", ".."])
async def test_chatgpt_rejects_path_injection_before_request(monkeypatch, value):
    requests = transport(monkeypatch)
    with pytest.raises(ValueError):
        await node({"operation": "get_model", "model": value}).execute({})
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {}, {"object": "list", "data": "wrong"}, {"error": {"message": "failure"}}])
async def test_chatgpt_malformed_success_is_not_a_verified_response(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node({"operation": "list_models"}).execute({})


def test_chatgpt_schema_connect_defaults_and_required_inputs():
    credential = native.ChatGPTAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "chatgpt_api_key"
    assert set(native.ChatGPTAPIKeyCredential.model_json_schema()["required"]) == {"api_key"}
    assert native.ChatGPTNode.connection_evidence.proves == "reachability"
    for cls, cfg in [(native.ChatGPTCreateResponse, {"input": "Hello"}),
                     (native.ChatGPTCreateChatCompletion, {"model": "gpt-4.1", "messages": []}),
                     (native.ChatGPTCreateBatch, {"input_file_id": "file-1", "endpoint": "/evil"})]:
        with pytest.raises(ValidationError):
            cls.model_validate(cfg)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_response", "get_response", "cancel_response"])
async def test_chatgpt_parses_unmodified_provider_documented_responses(monkeypatch, operation):
    fixtures = json.loads((Path(__file__).parent / "fixtures/chatgpt/documented_responses.json").read_text())
    body = fixtures[operation]["body"]
    transport(monkeypatch, body=body)
    cfg = {"operation": operation, **(BODIES[operation] if operation == "create_response" else {"response_id": "resp_123"})}
    assert await node(cfg).execute({}) == body


def test_chatgpt_rejects_response_output_limit_below_provider_minimum():
    with pytest.raises(ValidationError):
        native.ChatGPTCreateResponse(model="gpt-4.1", input="Hello", max_output_tokens=15)
