"""Exercise Bubbles requests through its real factory and HTTP boundary.

Webhook fixtures are copied from https://docs.usebubbles.com/webhooks/;
tokens and ordinary HTTP responses below are synthetic and make no live calls.
"""
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest

from nodes import bubbles_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures/bubbles"
TOKEN = "bbls_pat_synthetic_test_key"
CREDENTIAL = {"credential_type": "bubbles_token", "api_token": TOKEN}
HTTP_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="bubbles-test", node_type="automation-bubbles",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status not in (202, 204) else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return HTTP_CLIENT(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


CASES = [
    ({"operation": "get_me"}, "GET", "/v1/me", {}),
    ({"operation": "list_teams"}, "GET", "/v1/teams", {}),
    ({"operation": "list_bubbles", "limit": 10, "cursor": "opaque+/=", "team_id": "team1", "type": "meeting_recording", "created_after": "2026-07-03T15:45:50.193Z"}, "GET", "/v1/bubbles", {"limit": "10", "cursor": "opaque+/=", "team_id": "team1", "type": "meeting_recording", "created_after": "2026-07-03T15:45:50.193Z"}),
    ({"operation": "search_bubbles", "q": "Weekly sync"}, "GET", "/v1/bubbles/search", {"q": "Weekly sync", "limit": "25"}),
    ({"operation": "get_bubble", "bubble_id": "bubble1"}, "GET", "/v1/bubbles/bubble1", {}),
    ({"operation": "get_transcript", "bubble_id": "bubble1", "format": "text"}, "GET", "/v1/bubbles/bubble1/transcript", {"format": "text"}),
    ({"operation": "list_comments", "bubble_id": "bubble1"}, "GET", "/v1/bubbles/bubble1/comments", {"limit": "25"}),
    ({"operation": "join_meeting", "team_id": "team1", "meeting_url": "https://meet.google.com/abc-defg-hij"}, "POST", "/v1/meetings/join", {"team_id": "team1", "meeting_url": "https://meet.google.com/abc-defg-hij"}),
    ({"operation": "get_meeting_join", "join_id": "join1"}, "GET", "/v1/meetings/join/join1", {}),
    ({"operation": "list_webhooks"}, "GET", "/v1/webhooks", {}),
    ({"operation": "get_webhook", "webhook_id": "wh_1"}, "GET", "/v1/webhooks/wh_1", {}),
    ({"operation": "create_webhook", "url": "https://example.com/hooks/bubbles", "team_id": "team1"}, "POST", "/v1/webhooks", {"url": "https://example.com/hooks/bubbles", "events": ["meeting_recording.ready"], "team_id": "team1"}),
    ({"operation": "update_webhook", "webhook_id": "wh_1", "status": "active", "event_type": "screen_recording.ready"}, "PATCH", "/v1/webhooks/wh_1", {"status": "active", "events": ["screen_recording.ready"]}),
    ({"operation": "delete_webhook", "webhook_id": "wh_1"}, "DELETE", "/v1/webhooks/wh_1", {}),
    ({"operation": "test_webhook", "webhook_id": "wh_1"}, "POST", "/v1/webhooks/wh_1/test", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,values", CASES)
async def test_bubbles_operation_requests(monkeypatch, config, method, path, values):
    reply = {"id": "synthetic", "status": "recording", "has_more": True, "next_cursor": "next+/="}
    requests = transport(monkeypatch, reply, 204 if method == "DELETE" else 200)
    result = await node(config).execute({})
    request = requests[0]
    assert len(requests) == 1 and request.method == method and request.url.path == path
    assert request.url.host == "api.usebubbles.com" and request.headers["Authorization"] == "Bearer " + TOKEN
    assert (dict(request.url.params) if method == "GET" else json.loads(request.content) if request.content else {}) == values
    assert result["status"] == "success"
    assert result["data"] == ({"deleted": True} if method == "DELETE" else reply)
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 429, 500])
async def test_bubbles_rejections_remain_failures(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"type": "unauthorized", "message": "Rejected " + TOKEN}}, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_me"}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_bubbles_bodyless_test_delivery_acknowledgement(monkeypatch):
    transport(monkeypatch, None, 202)
    result = await node({"operation": "test_webhook", "webhook_id": "wh_1"}).execute({})
    assert result == {"status": "success", "operation": "test_webhook", "data": {"queued": True}}


@pytest.mark.asyncio
async def test_bubbles_webhook_lifecycle(monkeypatch):
    subscription = json.loads((FIXTURES / "webhook-created.json").read_text())
    requests = transport(monkeypatch, subscription, 201)
    state = await native.BubblesNode._register_external_webhook(webhook_url="https://example.com/hooks/bubbles",
        credential=CREDENTIAL, config={"team_id": "team1", "space_id": "space1"}, node_id="test")
    assert state == {"external_webhook_id": subscription["id"], "signing_secret": subscription["secret"]}
    assert json.loads(requests[0].content) == {"url": "https://example.com/hooks/bubbles", "events": ["meeting_recording.ready"], "team_id": "team1", "space_id": "space1"}
    requests = transport(monkeypatch, None, 204)
    await native.BubblesNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id="test")
    assert requests[0].method == "DELETE" and str(requests[0].url).endswith(native.quote(subscription["id"], safe=""))


def test_bubbles_documented_signature_and_agent_event():
    event = json.loads((FIXTURES / "meeting-ready.json").read_text())
    body = json.dumps(event).encode()
    secret = "whsec_demo_0123456789abcdef"
    def headers(timestamp):
        sig = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
        return {"X-Bubbles-Signature": f"t={timestamp},v1={sig}"}
    now = int(time.time())
    check = native.BubblesNode.verify_webhook_signature
    config = {"signing_secret": secret}
    assert check(body, headers(now), config)
    assert not check(body + b" ", headers(now), config)
    assert not check(body, headers(now - 400), config)
    assert not check(body, headers(now + 400), config)
    assert not check(body, {}, config)
    assert not check(body, headers(now), {})
    assert native.BubblesNode.filter_trigger_payload(event, {})
    assert not native.BubblesNode.filter_trigger_payload({**event, "type": "webhook.test"}, {})
    turn = native.BubblesNode.resolve_agent_event(event)
    assert turn["conversation_key"] == event["data"]["bubble"]["id"]
    assert all(value in turn["text"] for value in ["Weekly sync", event["data"]["bubble"]["url"], "get_transcript", "get_bubble"])


@pytest.mark.asyncio
async def test_bubbles_manual_trigger_and_connection_evidence(monkeypatch):
    assert (await node({"operation": "on_meeting_ready"}).execute({}))["status"] == "no_event"
    reply = {"data": [{"id": "team1", "name": "My workspace", "channels": []}]}
    transport(monkeypatch, reply)
    result = await node({"operation": native.BubblesNode.connection_evidence.operation}).execute({})
    from nodes.core.connection_evidence import _rows_from_operation
    assert _rows_from_operation(result)[0]["name"] == "My workspace"
    assert native.BubblesTokenCredential(api_token=TOKEN).credential_type == "bubbles_token"
