"""Requests and call deliveries exercised with the provider's unmodified examples."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from nodes.net2phone_node import (
    ACCEPT, BASE, MODELS, OPERATIONS, Net2PhoneAccessToken, Net2PhoneNode,
    Net2PhoneNodeConfig,
)

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/net2phone/examples.json").read_text())["examples"]
CREDENTIAL = {"credential_type": "net2phone_access_token", "access_token": "test-token-123"}
CLIENT = httpx.AsyncClient


def node(operation, **values):
    return Net2PhoneNode(node_id="test", node_type="automation-net2phone", node_data={}, sio=Mock(),
        config=Net2PhoneNodeConfig.model_validate({"config": {"operation": operation, **values}, "credentials": CREDENTIAL}))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_net2phone_documented_requests(monkeypatch, operation):
    values = {}
    for field in MODELS[operation].model_fields:
        if field == "start_date": values[field] = "2021-05-01T00:00:00Z"
        if field == "userId": values[field] = 100
        if field == "subscriptionId": values[field] = 12345
        if field == "post_uri": values[field] = "https://mydomain.com/webhooks"
        if field == "to": values[field] = EXAMPLES["call"]["to"]
    label, method, route, _, location = OPERATIONS[operation]
    seen = []

    def respond(request):
        seen.append(request)
        assert request.method == method
        assert str(request.url).startswith(BASE + route.replace("{userId}", "100").replace("{subscriptionId}", "12345"))
        assert request.headers["authorization"] == "Bearer test-token-123"
        assert request.headers["accept"] == ACCEPT
        if "cdrs" in operation:
            assert request.url.params["start_date"] == values["start_date"]
            return httpx.Response(200, json=EXAMPLES["cdrs-3"])
        if operation == "place_call":
            assert json.loads(request.content) == EXAMPLES["call"]
            return httpx.Response(201)
        if operation == "delete_subscription": return httpx.Response(204)
        if operation == "create_subscription":
            assert json.loads(request.content)["post_uri"] == values["post_uri"]
            return httpx.Response(202, json=EXAMPLES["http-webhook-subscription"])
        key = {"get_current_user": "user", "get_user": "user", "get_account": "account",
               "list_users": "users", "list_available_endpoints": "endpoints", "get_subscription": "http-webhook-subscription"}[operation]
        return httpx.Response(200, json=EXAMPLES[key])

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: CLIENT(transport=httpx.MockTransport(respond), **kw))
    result = await node(operation, **values).execute({})
    assert result["status"] == "success"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_net2phone_registration_cleanup(monkeypatch):
    seen = []
    def respond(request):
        seen.append(request)
        if request.method == "POST":
            assert json.loads(request.content) == {"post_uri": "https://mydomain.com/webhooks", "calls": True,
                "cdrs": False, "recordings": False, "expires_in": 604800, "user": "201"}
            return httpx.Response(202, json=EXAMPLES["http-webhook-subscription"])
        assert request.method == "DELETE" and request.url.path == "/v1/subscriptions/12345/"
        return httpx.Response(204)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: CLIENT(transport=httpx.MockTransport(respond), **kw))
    config = {"user": "201"}
    config.update(await Net2PhoneNode._register_external_webhook(webhook_url="https://mydomain.com/webhooks", credential=CREDENTIAL, config=config, node_id="test"))
    assert not Net2PhoneNode.webhook_registration_stale(config, {})
    config["subscription_expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert Net2PhoneNode.webhook_registration_stale(config, {})
    await Net2PhoneNode._unregister_external_webhook(credential=CREDENTIAL, config=config, node_id="test")
    assert len(seen) == 2


@pytest.mark.parametrize("example", ["webhook-call-answered", "webhook-call-ringing", "webhook-call-completed", "webhook-call-auto-attendant"])
def test_net2phone_documented_events(example):
    payload = EXAMPLES[example]
    assert Net2PhoneNode.verify_webhook_signature(json.dumps(payload).encode(), {}, {})
    for body in [payload, {"calls": payload}]:
        output = Net2PhoneNode.resolve_trigger_payload(body, {})
        event = Net2PhoneNode.resolve_agent_event(output)
        assert payload["from"]["call_id"] == event["conversation_key"]
        assert payload["to"]["id"] in event["text"]
        assert payload["from"]["call_id"] in event["text"]


@pytest.mark.asyncio
async def test_net2phone_provider_errors_redact_token(monkeypatch):
    def respond(request):
        return httpx.Response(401, json={"message": "Rejected test-token-123"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: CLIENT(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ValueError, match=r"401: Rejected \[redacted\]"):
        await node("get_current_user").execute({})


def test_net2phone_manual_credential_defaults():
    assert Net2PhoneAccessToken(access_token="test-token-123").credential_type == "net2phone_access_token"
    with pytest.raises(ValueError): Net2PhoneAccessToken(access_token="Bearer bad-token")


def test_net2phone_oauth_requests_match_authentication_docs(monkeypatch):
    import base64
    from nodes.oauth.net2phone_oauth import OAUTH_PROVIDER
    monkeypatch.setenv("NET2PHONE_CLIENT_ID", "test-client")
    monkeypatch.setenv("NET2PHONE_CLIENT_SECRET", "test-secret")
    request = OAUTH_PROVIDER.token_request({"grant_type": "authorization_code", "code": "test-code", "redirect_uri": "https://example.com/callback/"})
    assert request["url"] == "https://api.n2p.io/v1/oauth/token/"
    assert request["json"] == {"grant_type": "authorization_code", "code": "test-code", "client_id": "test-client", "redirect_uri": "https://example.com/callback/"}
    request = OAUTH_PROVIDER.token_request({"grant_type": "refresh_token", "refresh_token": "test-refresh"})
    assert request["headers"]["Authorization"] == "Bearer " + base64.b64encode(b"test-client:test-secret").decode()
    assert request["json"] == {"grant_type": "refresh_token", "refresh_token": "test-refresh"}
    assert request["auth"] is None


@pytest.mark.asyncio
async def test_net2phone_oauth_identity_uses_version_header(monkeypatch):
    from nodes.oauth.net2phone_oauth import OAUTH_PROVIDER
    def respond(request):
        assert request.url.path == "/v1/users/current/"
        assert request.headers["Accept"] == ACCEPT
        assert request.headers["Authorization"] == "Bearer test-identity"
        return httpx.Response(200, json=EXAMPLES["user"])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: CLIENT(transport=httpx.MockTransport(respond), **kw))
    assert await OAUTH_PROVIDER.account_name("test-identity") == EXAMPLES["user"]["email"]
