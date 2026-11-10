"""Request and event behavior using the publisher's documented examples."""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from nodes import evolution_go_node as module
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "evolution_go"
CASES = json.loads((FIXTURES / "requests.json").read_text())
EVENTS = json.loads((FIXTURES / "events.json").read_text())
CREDENTIAL = {"credential_type": "evolution_go_instance_token", "server_url": "https://evolution.example.com", "api_token": "evolution-test-instance-739"}


def client_with(monkeypatch, handler):
    original = httpx.AsyncClient
    def factory(**kwargs):
        assert kwargs.get("follow_redirects") is False
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(module, "guarded_async_client", factory)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: "evolution-go-" + c["operation"])
async def test_evolution_go_documented_requests(monkeypatch, case):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.method == case["method"]
        assert request.url == CREDENTIAL["server_url"] + case["path"]
        assert request.headers["apikey"] == CREDENTIAL["api_token"]
        assert "authorization" not in request.headers
        if case["method"] == "POST":
            body = json.loads(request.content)
            for name, value in case["config"].items():
                if name != "operation":
                    assert body[name] == value
            assert "operation" not in body
        else:
            assert not request.content
        return httpx.Response(200, json=case["response"])
    client_with(monkeypatch, handle)
    node = NodeFactory.create_node(node_id="evolution-test", node_type="automation-evolution-go",
        node_data={"config": case["config"], "credentials": CREDENTIAL}, sio=Mock())
    result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"] == case["response"].get("data", case["response"])
    assert len(requests) == 1


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com/path", "https://user:password@example.com", "https://example.com?token=secret"])
def test_evolution_go_rejects_unsafe_credential_origins(url):
    with pytest.raises(ValueError):
        module.EvolutionGoInstanceTokenCredential(**{**CREDENTIAL, "server_url": url})


@pytest.mark.parametrize("token", ["https://example.com", "your-api-token", "abc\ndef", "token with spaces", "non-ascii-✓"])
def test_evolution_go_rejects_bad_tokens(token):
    with pytest.raises(ValueError):
        module.EvolutionGoInstanceTokenCredential(**{**CREDENTIAL, "api_token": token})


def test_evolution_go_manual_credential_defaults():
    data = module.EvolutionGoInstanceTokenCredential(server_url="https://EVOLUTION.example.com/", api_token="  evolution-test-instance-739  ")
    assert data.credential_type == "evolution_go_instance_token"
    assert data.server_url == "https://evolution.example.com"
    assert data.api_token == CREDENTIAL["api_token"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_evolution_go_rejects_http_errors_and_redacts_token(monkeypatch, status):
    def handle(request):
        return httpx.Response(status, json={"error": "Rejected " + CREDENTIAL["api_token"]}, headers={"location": "https://other.example.com"})
    client_with(monkeypatch, handle)
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await module.EvolutionGoNode._request(CREDENTIAL, "GET", "/user/contacts")
    assert CREDENTIAL["api_token"] not in str(exc.value)


@pytest.mark.asyncio
async def test_evolution_go_rejects_provider_error_envelope(monkeypatch):
    client_with(monkeypatch, lambda req: httpx.Response(200, json={"error": "not authorized"}))
    with pytest.raises(ValueError, match="not authorized"):
        await module.EvolutionGoNode._request(CREDENTIAL, "GET", "/user/contacts")


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["MESSAGE", "CALL"])
async def test_evolution_go_webhook_lifecycle_and_documented_delivery(monkeypatch, event_type):
    bodies = []
    def handle(request):
        assert request.url.path == "/instance/connect"
        assert request.method == "POST"
        assert request.headers["apikey"] == CREDENTIAL["api_token"]
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": "success"})
    client_with(monkeypatch, handle)
    config = {"operation": "on_event", "event_type": event_type}
    url = "https://test.hooks.example.test/webhook/evolution"
    extra = await module.EvolutionGoNode._register_external_webhook(webhook_url=url, credential=CREDENTIAL, config=config, node_id="test")
    assert extra["external_webhook_id"] == url
    assert bodies[0] == {"webhookUrl": url, "subscribe": [event_type], "rabbitmqEnable": "disabled", "websocketEnable": "disabled", "natsEnable": "disabled"}
    payload = EVENTS["Message.text" if event_type == "MESSAGE" else "CallOffer"]["body"]
    assert module.EvolutionGoNode.verify_webhook_signature(json.dumps(payload).encode(), {}, config)
    assert module.EvolutionGoNode.filter_trigger_payload(payload, config)
    other = EVENTS["CallOffer" if event_type == "MESSAGE" else "Message.text"]["body"]
    assert not module.EvolutionGoNode.filter_trigger_payload(other, config)
    output = module.EvolutionGoNode.resolve_trigger_payload(payload, config)
    event = module.EvolutionGoNode.resolve_agent_event(output)
    assert event["conversation_key"] == "evolution-go:249aad2e-68f9-464f-bc84-aca560c38f0e:12025550100@s.whatsapp.net"
    assert "instanceToken" not in output["data"]
    assert (payload["data"]["Info"]["ID"] if event_type == "MESSAGE" else payload["data"]["CallID"]) in event["text"]
    if event_type == "MESSAGE":
        assert payload["data"]["Message"]["conversation"] in event["text"]
        assert "Davidson Gomes" in event["text"]
    await module.EvolutionGoNode._unregister_external_webhook(credential=CREDENTIAL, config={**config, **extra}, node_id="test")
    assert bodies[1]["webhookUrl"] == ""
    assert len(bodies) == 2


def test_evolution_go_ignores_own_messages_and_unrelated_events():
    payload = json.loads(json.dumps(EVENTS["Message.text"]["body"]))
    payload["data"]["Info"]["IsFromMe"] = True
    assert module.EvolutionGoNode.resolve_agent_event({"operation": "on_event", "data": payload}) is None
    assert module.EvolutionGoNode.resolve_agent_event({"operation": "list_contacts", "data": []}) is None
    assert module.EvolutionGoNode.resolve_trigger_payload({"event": "Connected"}, {}) is None


def test_evolution_go_trigger_metadata_and_connection_evidence():
    schema = module.EvolutionGoNode.get_config_schema()
    assert schema["$defs"]["EvolutionGoOnEventConfig"]["properties"]["operation"]["x-is-trigger"] is True
    assert module.EvolutionGoNode.connection_evidence.operation == "list_contacts"
    assert module.EvolutionGoNode.connection_evidence.identity_operation == "get_instance_status"


@pytest.mark.asyncio
async def test_evolution_go_guards_private_server_at_request_time():
    from utils.ssrf import SSRFError
    with pytest.raises(SSRFError):
        await module.EvolutionGoNode._request({**CREDENTIAL, "server_url": "https://127.0.0.1"}, "GET", "/user/contacts")


@pytest.mark.asyncio
async def test_evolution_go_redacts_tokens_in_nested_success_responses(monkeypatch):
    token = 'issued-token-with-"quote'
    client_with(monkeypatch, lambda req: httpx.Response(200, json={"message": "success", "data": [{"token": token}]}))
    response = await module.EvolutionGoNode._request({**CREDENTIAL, "api_token": token}, "GET", "/instance/status")
    assert response["data"] == [{"token": "[redacted]"}]


@pytest.mark.parametrize("name", [name for name in EVENTS if name.startswith("Message.")])
def test_evolution_go_all_documented_message_types_reach_agent(name):
    payload = EVENTS[name]["body"]
    output = module.EvolutionGoNode.resolve_trigger_payload(payload, {"event_type": "MESSAGE"})
    event = module.EvolutionGoNode.resolve_agent_event(output)
    assert payload["data"]["Info"]["ID"] in event["text"]
    assert "12025550100@s.whatsapp.net" in event["conversation_key"]
    assert payload["instanceToken"] not in json.dumps(output)
