"""Real node requests and provider-authored response examples; no live account."""
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from nodes import zulip_node as native
from nodes.core.registry import NodeFactory

TOKEN = "zulip-synthetic-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/zulip/responses.json").read_text())
CONFIGS = {
    "get_own_user": {}, "list_users": {}, "get_user": {"user_id": 5},
    "list_channels": {}, "list_subscriptions": {}, "list_topics": {"stream_id": 1},
    "get_messages": {"anchor": "newest", "num_before": 100, "num_after": 0,
        "narrow": [{"operator": "channel", "operand": "Denmark"}]},
    "get_message": {"message_id": 42},
    "send_message": {"type": "direct", "to": [9, 10], "content": "Hello"},
    "update_message": {"message_id": 42, "content": "Edited + café"},
    "delete_message": {"message_id": 42},
    "add_reaction": {"message_id": 42, "emoji_name": "octopus"},
    "remove_reaction": {"message_id": 42, "emoji_name": "octopus"},
    "subscribe": {"subscriptions": [{"name": "Verona", "description": "Italian city"}]},
    "unsubscribe": {"subscriptions": ["Verona", "Denmark"]},
    "render_message": {"content": "**foo**"},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credentials(**changes):
    return {"credential_type": "zulip_api_key", "server_url": "https://example.zulipchat.com",
        "email": "othello-bot@example.com", "api_key": TOKEN, **changes}


def node(operation, **changes):
    return NodeFactory.create_node(node_id="zulip-test", node_type="automation-zulip", node_data={
        "config": {"operation": operation, **CONFIGS[operation], **changes}, "credentials": credentials()})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_one_documented_operation_and_provider_example(monkeypatch, operation):
    requests = transport(monkeypatch, EXAMPLES[operation]["body"])
    result = await node(operation).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    method, route = native.ROUTES[operation]
    assert request.method == method
    assert request.url.path == "/api/v1" + route.format(**CONFIGS[operation])
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(("othello-bot@example.com:" + TOKEN).encode()).decode()
    assert TOKEN not in str(result)
    params = dict(request.url.params) if method == "GET" else {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    if operation == "send_message":
        assert json.loads(params["to"]) == [9, 10] and params["content"] == "Hello"
    if operation == "get_messages":
        assert json.loads(params["narrow"]) == [{"operator": "channel", "operand": "Denmark"}]
        assert params["anchor"] == "newest" and params["num_before"] == "100"
        assert result["response"]["found_newest"] is True
    if operation in {"subscribe", "unsubscribe"}:
        assert json.loads(params["subscriptions"]) == CONFIGS[operation]["subscriptions"]
    if operation == "update_message":
        assert params == {"content": "Edited + café"}


@pytest.mark.asyncio
async def test_channel_send_requires_topic_and_encodes_channel_name_as_string(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["send_message"]["body"])
    result = await node("send_message", type="channel", to="Denmark", topic="Castle").execute({})
    assert result["success"]
    assert json.loads(parse_qs(requests[0].content.decode())["to"][0]) == "Denmark"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list_subscriptions", "get_own_user", "send_message", "subscribe", "unsubscribe"])
async def test_missing_documented_response_fields_fail_closed(monkeypatch, operation):
    transport(monkeypatch, {"result": "success", "msg": ""})
    result = await node(operation).execute({})
    assert result["success"] is False and "data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 429, 500])
async def test_provider_error_is_preserved_and_secret_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {"result": "error", "msg": "Rejected " + TOKEN}, status)
    result = await node("list_subscriptions").execute({})
    assert result["status"] == "error" and result["message"] == "Rejected [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_writes_are_not_retried_and_ambiguous_outcomes_are_unknown(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("timed out"))
    result = await node("send_message").execute({})
    assert result["status"] == "unknown" and len(requests) == 1
    requests = transport(monkeypatch, {"result": "success", "msg": "", "id": 42,
        "ignored_parameters_unsupported": ["to"]})
    assert (await node("send_message").execute({}))["status"] == "unknown"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_redirects_and_wrong_envelopes_are_not_success(monkeypatch):
    for status, body in [(302, {}), (200, []), (200, {"result": "success"})]:
        requests = transport(monkeypatch, body, status)
        assert not (await node("list_subscriptions").execute({}))["success"]
        assert len(requests) == 1


@pytest.mark.parametrize("value", ["http://example.com", "https://example.com/api/v1", "https://user:password@example.com", "https://127.0.0.1", "https://example.com?x=1", "https://example.com:444", "https://localhost"])
def test_unsafe_or_non_origin_credential_rejected(value):
    with pytest.raises(ValueError):
        native.ZulipAPIKeyCredential.model_validate(credentials(server_url=value))


@pytest.mark.parametrize("operation, changes", [("get_user", {"user_id": "../me"}), ("get_message", {"message_id": True}),
    ("send_message", {"to": 9}), ("send_message", {"type": "channel", "to": 1}),
    ("subscribe", {"subscriptions": []}), ("get_messages", {"num_before": -1})])
def test_invalid_config_rejected_before_request(operation, changes):
    with pytest.raises(ValueError):
        node(operation, **changes)


def test_evidence_read_and_credential_shaping():
    assert native.ZulipNode.connection_evidence.operation == "list_subscriptions"
    assert native.ZulipNode.connection_evidence.identity_operation == "get_own_user"
    c = native.ZulipAPIKeyCredential.model_validate(credentials(server_url=" https://EXAMPLE.zulipchat.com/ ", api_key=" " + TOKEN + "\n"))
    assert c.server_url == "https://example.zulipchat.com" and c.api_key == TOKEN
