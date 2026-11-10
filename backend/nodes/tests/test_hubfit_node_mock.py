"""Exercise HubFit's real operation runner against isolated HTTP fixtures.

Provider examples pin response parsing; boundary cases protect task clearing,
request placement, connection setup and Standard Webhooks verification.
"""
import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import hubfit_node as hubfit
from nodes.core.run_op import run_node_operation

FIXTURES = json.loads((Path(__file__).parent / "fixtures/hubfit/documented.json").read_text())
AUTH = {"credential_type": "hubfit_api_key", "api_key": "hubfit_sk_fixture_local_only"}
CLIENT = "6ad6af41d3199442d31b2743"
TASK = FIXTURES["task_created"]["body"]["data"]["id"]
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    native = httpx.AsyncClient

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.hubfit.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body) if body is not None else httpx.Response(code)

    monkeypatch.setattr(hubfit.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-hubfit", operation=operation,
        arguments=arguments or {}, credential_data=AUTH.copy(), user_id=USER)


@pytest.mark.asyncio
async def test_hubfit_message_uses_documented_body_and_idempotency(transport):
    requests, replies = transport
    body = FIXTURES["message_sent"]["body"]
    replies.append((201, body))
    result = await run("send_client_message", {"client_id": CLIENT, "text": body["data"]["text"], "idempotency_key": "message-123"})
    assert result["data"] == body["data"]
    request = requests[0]
    assert request.method == "POST" and request.url.path == f"/v1/clients/{CLIENT}/messages"
    assert json.loads(request.content) == {"text": body["data"]["text"]}
    assert request.headers["Idempotency-Key"] == "message-123"


@pytest.mark.asyncio
async def test_hubfit_patch_preserves_explicit_null_and_omits_untouched_fields(transport):
    requests, replies = transport
    replies.extend([(200, FIXTURES["task_updated"]["body"])] * 2)
    await run("update_task", {"task_id": TASK, "due_date": None, "client_id": None, "assignee_id": None})
    assert requests[0].method == "PATCH"
    assert requests[0].url.path == f"/v1/tasks/{TASK}"
    assert json.loads(requests[0].content) == {"dueDate": None, "clientId": None, "assigneeId": None}
    await run("update_task", {"task_id": TASK, "status": "completed", "title": None})
    assert json.loads(requests[1].content) == {"status": "completed"}


@pytest.mark.asyncio
async def test_hubfit_create_client_makes_login_email_a_visible_choice(transport):
    requests, replies = transport
    replies.extend([(201, {"data": {"id": CLIENT}}), (201, {"data": {"id": CLIENT}})])
    await run("create_client", {"name": "Client Example", "email": "client@example.com"})
    await run("create_client", {"name": "Client Example", "email": "client@example.com", "send_login_instructions": True})
    assert json.loads(requests[0].content)["sendLoginInstructions"] is False
    assert json.loads(requests[1].content)["sendLoginInstructions"] is True


@pytest.mark.asyncio
async def test_hubfit_query_cursor_and_account_evidence(transport):
    requests, replies = transport
    page = {"data": [{"id": CLIENT, "name": "Example Client", "email": "client@example.com"}],
            "nextCursor": "opaque+cursor/=", "totalCount": 1}
    replies.append((200, page))
    result = await run("list_clients", {"email": "client+tag@example.com", "cursor": "opaque+/=", "limit": 5})
    assert result["nextCursor"] == page["nextCursor"]
    assert dict(requests[0].url.params) == {"email": "client+tag@example.com", "cursor": "opaque+/=", "limit": "5", "status": "active"}
    assert hubfit.HubFitNode.connection_evidence.operation == "list_clients"
    assert hubfit.HubFitAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == "hubfit_api_key"


@pytest.mark.asyncio
async def test_hubfit_private_note_and_read_only_connection_picker(transport):
    requests, replies = transport
    body = FIXTURES["note_created"]["body"]
    replies.append((201, body))
    await run("create_client_note", {"client_id": CLIENT, "text": body["data"]["text"], "visibility": "private"})
    assert json.loads(requests[0].content)["visibility"] == "private"
    replies.append((200, {"data": [{"id": CLIENT, "name": "Example Client"}], "nextCursor": None, "totalCount": 1}))
    options = await hubfit.HubFitNode.load_field_options("client_id", AUTH)
    assert options == {"options": [{"value": CLIENT, "label": "Example Client"}], "next_page_token": None}
    assert requests[1].method == "GET"


@pytest.mark.asyncio
async def test_hubfit_problem_detail_is_preserved_without_credential(transport):
    requests, replies = transport
    replies.append((403, {"detail": "Key lacks clients:read", "code": "insufficient_scope"}))
    with pytest.raises(ValueError, match="Key lacks clients:read"):
        await hubfit.HubFitNode._request(AUTH, "GET", "/clients")
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_client", "client_id": "../tasks"},
    {"operation": "create_task", "title": "   "},
    {"operation": "send_client_message", "client_id": CLIENT, "text": " "},
    {"operation": "update_task", "task_id": TASK},
    {"operation": "update_task", "task_id": TASK, "status": None},
    {"operation": "create_task", "title": "Call client", "due_date": "2026-02-31"},
    {"operation": "list_clients", "limit": 101},
])
def test_hubfit_rejects_invalid_requests_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        hubfit.HubFitNodeConfig.model_validate({"config": config, "credentials": AUTH})


def signature(body, secret, *, timestamp=None):
    timestamp = str(timestamp if timestamp is not None else int(time.time()))
    headers = {"webhook-id": "fixture-event", "webhook-timestamp": timestamp}
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = base64.b64encode(hmac.new(key, f"fixture-event.{timestamp}.".encode() + body, hashlib.sha256).digest()).decode()
    headers["webhook-signature"] = "v1," + digest
    return headers


def test_hubfit_standard_webhooks_rejects_tamper_replays_and_wrong_secret():
    secret = FIXTURES["endpoint_created"]["body"]["secret"]
    config = {"signing_secret": secret}
    body = json.dumps(FIXTURES["check_in_event"]["body"]).encode()
    headers = signature(body, secret)
    assert hubfit.HubFitNode.verify_webhook_signature(body, headers, config)
    headers["webhook-signature"] = "v1,incorrect " + headers["webhook-signature"]
    assert hubfit.HubFitNode.verify_webhook_signature(body, headers, config)
    assert not hubfit.HubFitNode.verify_webhook_signature(body + b" ", headers, config)
    assert not hubfit.HubFitNode.verify_webhook_signature(body, signature(body, secret, timestamp=int(time.time()) - 301), config)
    assert not hubfit.HubFitNode.verify_webhook_signature(body, signature(body, secret, timestamp=int(time.time()) + 301), config)
    assert not hubfit.HubFitNode.verify_webhook_signature(body, headers, {"signing_secret": "whsec_invalid"})
    assert not hubfit.HubFitNode.verify_webhook_signature(body, {}, config)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event", list(hubfit.EVENTS.items()))
async def test_hubfit_register_deliver_and_remove_each_documented_event(transport, operation, event):
    requests, replies = transport
    replies.extend([(201, FIXTURES["endpoint_created"]["body"]), (204, None)])
    config = {"operation": operation}
    state = await hubfit.HubFitNode._register_external_webhook(webhook_url="https://example.com/hubfit-webhooks",
        credential=AUTH, config=config, node_id="fixture")
    assert json.loads(requests[0].content) == {"name": "NoClick fixture", "url": "https://example.com/hubfit-webhooks", "events": [event]}
    # All five event schemas in the pinned contract share the same documented record-ref shape.
    payload = {**FIXTURES["check_in_event"]["body"], "type": event}
    assert hubfit.HubFitNode.filter_trigger_payload(payload, config)
    assert not hubfit.HubFitNode.filter_trigger_payload({**payload, "type": "future.event"}, config)
    output = hubfit.HubFitNode.resolve_trigger_payload(payload, config)
    turn = hubfit.HubFitNode.resolve_agent_event(output)
    assert payload["data"]["clientId"] in turn["text"] and payload["data"]["id"] in turn["text"]
    assert turn["conversation_key"] == payload["data"]["clientId"]
    await hubfit.HubFitNode._unregister_external_webhook(credential=AUTH, config={**config, **state}, node_id="fixture")
    assert requests[-1].method == "DELETE" and requests[-1].url.path.endswith(state["external_webhook_id"])


@pytest.mark.asyncio
async def test_hubfit_manual_trigger_run_does_not_invent_an_event():
    result = await run("on_check_in_submitted")
    assert result["status"] == "no_event"
