"""Crisp: the operations against Crisp's own documented requests and responses,
and the trigger end to end, from a signed plugin hook through the app-level
receiver to a queued run, with its loop guards and the agent's turn.

fixtures/crisp/documented.json holds the REST reference's examples (a source
URL per case); fixtures/crisp/events.json the Web Hooks reference's.
"""
import asyncio
import base64
import copy
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import fakeredis.aioredis
import httpx
import pytest
from pydantic import ValidationError

from nodes.core.webhook_subscriptions import RegistrationAdvisory
from nodes.crisp_node import CrispError, CrispNode, CrispNodeConfig
from utils.crisp_webhooks import crisp_parse, crisp_verify
from utils.registration_verdict import RegistrationUnverified

FIXTURES = Path(__file__).parent / "fixtures/crisp"
DOCS = json.loads((FIXTURES / "documented.json").read_text())
EVENTS = json.loads((FIXTURES / "events.json").read_text())
WEBSITE = "8c842203-7ed8-4e29-a608-7cf78a7d2fcc"
CREDENTIAL = {"credential_type": "crisp_website_token", "website_id": WEBSITE,
              "identifier": "d2fe9fd3-5c1b-46a8-9d2c-4a3c3b6e9f1a", "key": "crisp-test-key"}
SECRET = "plugin-hook-secret"
VISITOR_TEXT = EVENTS["message:send"]["Text Message"]
HOOK_WEBSITE = VISITOR_TEXT["website_id"]
SESSION = VISITOR_TEXT["data"]["session_id"]


def node(config):
    return CrispNode(node_id="crisp", node_type="automation-crisp", node_data={}, sio=Mock(),
                     config=CrispNodeConfig(config=config, credentials=CREDENTIAL))


@pytest.fixture
def crisp_api(monkeypatch):
    """Answer the node's requests with ``responses[i]`` (status, envelope); record them."""
    state = {"requests": [], "responses": []}
    original = httpx.AsyncClient

    def transport(request):
        state["requests"].append(request)
        status, body = state["responses"].pop(0)
        return httpx.Response(status, json=body)

    def client(*args, **kwargs):
        assert kwargs.get("follow_redirects") is False
        return original(*args, **kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr("nodes.crisp_node.httpx.AsyncClient", client)
    return state


@pytest.fixture
def redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis()
    for target in ("utils.self_echo.get_shared_redis", "utils.fire_budget.get_shared_redis",
                   "utils.redis_client.get_shared_redis"):
        monkeypatch.setattr(target, lambda: client)
    return client


def sign(body: bytes, timestamp: str = "1632396148750", secret: str = SECRET) -> dict:
    signature = hmac.new(secret.encode(), b"[" + timestamp.encode() + b";" + body + b"]", hashlib.sha256).hexdigest()
    return {"X-Crisp-Request-Timestamp": timestamp, "X-Crisp-Signature": signature}


# ── operations ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("op", sorted(DOCS["operations"]))
async def test_documented_operation(op, crisp_api, redis):
    case = DOCS["operations"][op]
    crisp_api["responses"].append((case["response_status"], case["response"]))
    result = await node({"operation": op, **case["config"]}).execute({})
    request, = crisp_api["requests"]
    assert request.method == case["method"]
    assert request.url.host == "api.crisp.chat"
    assert request.url.path == case["path"]
    assert dict(request.url.params) == {k: str(v) for k, v in case["params"].items()}
    assert request.headers["X-Crisp-Tier"] == "website"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(
        f"{CREDENTIAL['identifier']}:{CREDENTIAL['key']}".encode()).decode()
    assert (json.loads(request.content) if request.content else None) == case["body"]
    data = case["response"]["data"]
    wrapped = {"get_messages": "messages", "list_conversations": "conversations", "list_operators": "operators"}
    if op in wrapped:
        assert result["data"][wrapped[op]] == data
    else:
        assert result["data"] == data
    assert result["status"] == "success" and result["operation"] == op


@pytest.mark.asyncio
async def test_list_filters_search_and_paging(crisp_api):
    crisp_api["responses"].append((200, {"error": False, "reason": "listed", "data": []}))
    await node({"operation": "list_conversations", "page": 3, "per_page": 50, "search": "refund",
                "status": "unresolved", "unread_only": "true", "unassigned_only": "true"}).execute({})
    request, = crisp_api["requests"]
    assert request.url.path == f"/v1/website/{WEBSITE}/conversations/3"
    assert dict(request.url.params) == {"per_page": "50", "search_query": "refund", "search_type": "text",
                                        "filter_not_resolved": "1", "filter_unread": "1", "filter_unassigned": "1"}
    crisp_api["responses"].append((200, {"error": False, "reason": "listed", "data": []}))
    await node({"operation": "get_messages", "session_id": SESSION, "before_timestamp": 1632396148646}).execute({})
    assert dict(crisp_api["requests"][1].url.params) == {"timestamp_before": "1632396148646"}


@pytest.mark.asyncio
async def test_sender_name_rides_the_message(crisp_api, redis):
    crisp_api["responses"].append((202, DOCS["operations"]["send_message"]["response"]))
    await node({"operation": "send_message", "session_id": SESSION, "message": "Hi!", "sender_name": "Ada"}).execute({})
    assert json.loads(crisp_api["requests"][0].content) == {
        "type": "text", "from": "operator", "origin": "chat", "content": "Hi!",
        "user": {"type": "participant", "nickname": "Ada"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["402", "403", "404"])
async def test_crisp_errors_carry_status_and_reason(status, crisp_api, redis):
    crisp_api["responses"].append((int(status), DOCS["errors"][status]))
    with pytest.raises(CrispError) as raised:
        await node({"operation": "send_message", "session_id": SESSION, "message": "Hi"}).execute({})
    assert raised.value.status == int(status)
    assert DOCS["errors"][status]["reason"] in str(raised.value)
    assert CREDENTIAL["key"] not in str(raised.value)


@pytest.mark.parametrize("config", [
    {"operation": "send_message", "session_id": "../operators/list", "message": "x"},
    {"operation": "get_contact", "people_id": "a/b"},
    {"operation": "send_file", "session_id": SESSION, "file_url": "http://x.test/a.pdf", "file_name": "a", "mime_type": "a/b"},
    {"operation": "list_conversations", "per_page": 10},
    {"operation": "assign_conversation", "session_id": SESSION, "operator_id": "someone"},
])
def test_invalid_config_never_reaches_a_url(config):
    with pytest.raises(ValidationError):
        CrispNodeConfig(config=config, credentials=CREDENTIAL)


@pytest.mark.asyncio
async def test_update_visitor_needs_a_change(crisp_api):
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_visitor", "session_id": SESSION}).execute({})
    assert crisp_api["requests"] == []


@pytest.mark.asyncio
async def test_operator_picker_is_the_connection_evidence(crisp_api):
    crisp_api["responses"].append((200, DOCS["operations"]["list_operators"]["response"]))
    options = await CrispNode.load_field_options("operator_id", CREDENTIAL)
    assert options == [{"value": "a53c456f-286a-490c-8793-d2a651838137", "label": "Baptiste Jamin"},
                       {"value": "aa0b64dd-9fb4-4db9-80d6-5a49eb84087b", "label": "Valerian Saliou"}]
    assert CrispNode.connection_evidence.field == "operator_id"


# ── the trigger: signature, parse, loop guards ─────────────────────────────


def test_signature_is_hmac_of_timestamp_and_raw_body(monkeypatch):
    monkeypatch.setenv("CRISP_PLUGIN_HOOK_SECRET", SECRET)
    body = json.dumps(VISITOR_TEXT).encode()
    headers = {k.lower(): v for k, v in sign(body).items()}
    assert crisp_verify(None, body, headers, "")
    assert not crisp_verify(None, body + b" ", headers, "")
    assert not crisp_verify(None, body, {**headers, "x-crisp-request-timestamp": "1632396148751"}, "")
    assert not crisp_verify(None, body, {k: v for k, v in sign(body, secret="other").items()}, "")
    assert not crisp_verify(None, body, {"x-crisp-request-timestamp": "1632396148750"}, "")
    monkeypatch.delenv("CRISP_PLUGIN_HOOK_SECRET")
    assert not crisp_verify(None, body, headers, "")


def test_only_visitor_messages_are_events():
    for name, example in EVENTS["message:send"].items():
        events = crisp_parse(json.dumps(example).encode())
        assert events == [(HOOK_WEBSITE, "message:send", example, SESSION)], name
    for name, example in EVENTS["message:received"].items():
        assert crisp_parse(json.dumps(example).encode()) == [], name
    # The agent's own reply (sent as the operator) and an operator's note.
    reply = copy.deepcopy(VISITOR_TEXT)
    reply["data"]["from"] = "operator"
    assert crisp_parse(json.dumps(reply).encode()) == []
    assert crisp_parse(b"not json") == [] and crisp_parse(b"{}") == []


@pytest.mark.asyncio
async def test_signed_visitor_message_fans_out_to_a_run(monkeypatch, redis):
    from utils.webhook_routes import handle_app_webhook_payload

    monkeypatch.setenv("CRISP_PLUGIN_HOOK_SECRET", SECRET)
    queued = []
    workflow = {"nodes": [{"id": "crisp-trigger", "type": "automation-crisp", "config": {"operation": "on_visitor_message"}},
                          {"id": "agent", "type": "agent", "config": {}}],
                "edges": [{"source": "crisp-trigger", "target": "agent"}]}

    class Pool:
        async def fetchrow(self, query, workflow_id):
            return {"workflow": copy.deepcopy(workflow)}

    async def execute(**kwargs):
        queued.append(kwargs)

    find = AsyncMock(return_value=[{"workflow_id": "wf-1", "node_id": "crisp-trigger", "user_id": "owner-1",
                                    "provider": "crisp"}])
    body = json.dumps(VISITOR_TEXT).encode()
    # _delivered_elsewhere is the hosted platform's own trigger seam (not this workflow's concern).
    with patch("nodes.core.webhook_subscriptions.find_subscriptions", new=find), \
            patch("utils.webhook_routes.get_native_pool", return_value=Pool()), \
            patch("utils.webhook_routes._delivered_elsewhere", new=AsyncMock(return_value=None)), \
            patch("utils.webhook_routes._execute_workflow_with_relay", new=execute):
        response = await handle_app_webhook_payload("crisp", body, sign(body), "https://w.test/webhook/app/crisp")
        await asyncio.sleep(0)
        assert response.success is True
        assert find.await_args.args[1:] == ("crisp", HOOK_WEBSITE, "message:send")
        assert len(queued) == 1 and queued[0]["start_node_id"] == "crisp-trigger"
        assert queued[0]["nodes"][0]["config"]["_triggerPayload"] == VISITOR_TEXT

        # Crisp retries a hook: the same message never runs twice.
        await handle_app_webhook_payload("crisp", body, sign(body), "https://w.test/webhook/app/crisp")
        await asyncio.sleep(0)
        assert len(queued) == 1

        # An unsigned delivery (a workspace's own web hook) is refused.
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as refused:
            await handle_app_webhook_payload("crisp", body, {}, "https://w.test/webhook/app/crisp")
        assert refused.value.status_code == 401


@pytest.mark.asyncio
async def test_noclick_sent_message_never_wakes_a_trigger(crisp_api, redis):
    """The send records its fingerprint, and a visitor-message event carrying it
    is dropped before fan-out (a reply sent as a visitor by another NoClick
    node, or echoed back by an integration)."""
    from utils.crisp_webhooks import crisp_drop_event

    crisp_api["responses"].append((202, {"error": False, "reason": "dispatched", "data": {"fingerprint": 163239614854320}}))
    await node({"operation": "send_message", "session_id": SESSION, "message": "On it!"}).execute({})
    echo = copy.deepcopy(VISITOR_TEXT)
    assert await crisp_drop_event(echo) == f"message {SESSION}:163239614854320 was sent by a NoClick Crisp node"
    echo["data"]["fingerprint"] = 1
    assert await crisp_drop_event(echo) is None


@pytest.mark.asyncio
async def test_fire_budget_is_per_conversation(monkeypatch, redis):
    """A two-party loop (an autoresponder answering the agent by email) is
    bounded per Crisp conversation: other conversations keep firing."""
    from utils.app_webhooks import APP_PROVIDERS
    from utils.fire_budget import FIRE_BUDGET_MAX, over_fire_budget

    assert APP_PROVIDERS["crisp"]["fire_budget"] is True
    _, _, _, channel = crisp_parse(json.dumps(VISITOR_TEXT).encode())[0]
    assert channel == SESSION
    for _ in range(FIRE_BUDGET_MAX):
        assert not await over_fire_budget("wf-1", "crisp-trigger", channel)
    assert await over_fire_budget("wf-1", "crisp-trigger", channel)
    assert not await over_fire_budget("wf-1", "crisp-trigger", "session_other")


# ── the agent's turn ──────────────────────────────────────────────────────


def test_visitor_message_is_the_agents_turn_in_its_conversation():
    event = CrispNode.resolve_agent_event(VISITOR_TEXT)
    assert event["conversation_key"] == SESSION
    assert event["title"] == "Crisp: visitor607"
    assert "Hello Crisp, this is a message from a visitor!" in event["text"]
    assert f"send_message with session_id={SESSION}" in event["text"]
    assert event["media"] == []


@pytest.mark.parametrize("name,said,file", [
    ("Text Message With Attachments", "Hello Crisp, here is my invoice!", "invoice.pdf"),
    ("File Message", "[image]", "screenshot.png"),
    ("Audio Message", "[voice message]", None),
])
def test_files_reach_the_agent(name, said, file):
    payload = EVENTS["message:send"][name]
    event = CrispNode.resolve_agent_event(payload)
    assert said in event["text"]
    assert len(event["media"]) == 1
    entry = event["media"][0]
    assert entry["url"].startswith("https://") and entry["url"] in event["text"]
    if file:
        assert entry["filename"] == file
    if name == "Text Message With Attachments":
        assert " via email " in event["text"]
    assert entry["voice"] is (name == "Audio Message")


def test_picker_and_field_answers_read_as_text():
    picker = CrispNode.resolve_agent_event(EVENTS["message:send"]["Picker Message (user selection response)"])
    field = CrispNode.resolve_agent_event(EVENTS["message:send"]["Field Message (user input response)"])
    content = EVENTS["message:send"]["Field Message (user input response)"]["data"]["content"]
    assert content["value"] in field["text"]
    chosen = [c["label"] for c in EVENTS["message:send"]["Picker Message (user selection response)"]["data"]["content"]["choices"]
              if c.get("selected")]
    assert chosen and all(label in picker["text"] for label in chosen)


def test_other_outputs_fall_back_to_the_default_event():
    assert CrispNode.resolve_agent_event({"status": "no_event", "data": {}})["conversation_key"] is None


@pytest.mark.asyncio
async def test_manual_run_of_the_trigger_says_no_event(crisp_api):
    result = await node({"operation": "on_visitor_message"}).execute({})
    assert result["status"] == "no_event" and crisp_api["requests"] == []


# ── registration: the workspace the token reaches, and whether Crisp delivers ──


@pytest.mark.asyncio
async def test_tenant_is_the_workspace_the_token_reaches(crisp_api):
    crisp_api["responses"].append((200, DOCS["operations"]["get_website"]["response"]))
    assert await CrispNode._resolve_tenant_id(CREDENTIAL) == WEBSITE
    assert crisp_api["requests"][0].url.path == f"/v1/website/{WEBSITE}"


@pytest.mark.asyncio
async def test_a_refused_token_registers_nothing_and_a_blip_is_no_verdict(crisp_api):
    crisp_api["responses"].append((403, {"error": True, "reason": "not_allowed", "data": {}}))
    with pytest.raises(ValueError, match="refused this API token") as refused:
        await CrispNode._resolve_tenant_id(CREDENTIAL)
    assert not isinstance(refused.value, RegistrationUnverified)
    crisp_api["responses"].append((503, {"error": True, "reason": "unavailable", "data": {}}))
    with pytest.raises(RegistrationUnverified):
        await CrispNode._resolve_tenant_id(CREDENTIAL)


@pytest.mark.asyncio
async def test_delivery_health_follows_noclicks_plugin(crisp_api, monkeypatch):
    for env in ("CRISP_PLUGIN_HOOK_SECRET", "CRISP_PLUGIN_ID", "CRISP_PLUGIN_TOKEN_IDENTIFIER",
                "CRISP_PLUGIN_TOKEN_KEY", "CRISP_PLUGIN_INSTALL_URL"):
        monkeypatch.delenv(env, raising=False)
    advisory = await CrispNode.check_registration_health(CREDENTIAL, "on_visitor_message", {})
    assert isinstance(advisory, RegistrationAdvisory) and "plugin isn't set up" in advisory.message

    monkeypatch.setenv("CRISP_PLUGIN_HOOK_SECRET", SECRET)
    assert await CrispNode.check_registration_health(CREDENTIAL, "on_visitor_message", {}) is None  # cannot judge

    plugin = "3c2d4f0e-6a0b-4c5e-9d6f-1a2b3c4d5e6f"
    monkeypatch.setenv("CRISP_PLUGIN_ID", plugin)
    monkeypatch.setenv("CRISP_PLUGIN_TOKEN_IDENTIFIER", "plugin-id")
    monkeypatch.setenv("CRISP_PLUGIN_TOKEN_KEY", "plugin-key")
    monkeypatch.setenv("CRISP_PLUGIN_INSTALL_URL", "https://install.test/noclick")
    crisp_api["responses"].append((200, DOCS["subscription"]["ok"]))
    assert await CrispNode.check_registration_health(CREDENTIAL, "on_visitor_message", {}) is None
    request = crisp_api["requests"][-1]
    assert request.url.path == f"/v1/plugins/subscription/{WEBSITE}/{plugin}"
    assert request.headers["X-Crisp-Tier"] == "plugin"

    crisp_api["responses"].append((404, DOCS["subscription"]["missing"]))
    advisory = await CrispNode.check_registration_health(CREDENTIAL, "on_visitor_message", {})
    assert advisory.message.endswith("https://install.test/noclick")

    crisp_api["responses"].append((500, {"error": True, "reason": "error", "data": {}}))
    with pytest.raises(CrispError):
        await CrispNode.check_registration_health(CREDENTIAL, "on_visitor_message", {})


@pytest.mark.asyncio
async def test_registration_writes_the_workspace_subscription(crisp_api, monkeypatch):
    saved = {}

    async def save(pool, **kwargs):
        saved.update(kwargs)

    monkeypatch.setattr("nodes.core.webhook_subscriptions.get_node_subscriptions", AsyncMock(return_value=[]))
    monkeypatch.setattr("nodes.core.webhook_subscriptions.save_subscriptions", save)
    monkeypatch.setenv("CRISP_PLUGIN_HOOK_SECRET", SECRET)
    for env in ("CRISP_PLUGIN_ID", "CRISP_PLUGIN_TOKEN_IDENTIFIER", "CRISP_PLUGIN_TOKEN_KEY"):
        monkeypatch.delenv(env, raising=False)
    crisp_api["responses"].append((200, DOCS["operations"]["get_website"]["response"]))
    mirrors = await CrispNode.register_and_describe(
        None, user_id="owner-1", workflow_id="wf-1", node_id="crisp-trigger", operation="on_visitor_message",
        credential_id="cred-1", credential=CREDENTIAL, config={})
    assert saved == {"provider": "crisp", "tenant_id": WEBSITE, "user_id": "owner-1", "workflow_id": "wf-1",
                     "node_id": "crisp-trigger", "credential_id": "cred-1", "event_types": ["message:send"]}
    assert mirrors["trigger_registered"] is True and mirrors["trigger_error"] is None
