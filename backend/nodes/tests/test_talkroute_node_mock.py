"""Talkroute requests and events, using the provider's published 2.0.2 contract."""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.talkroute_node import TalkrouteNode, TalkrouteNodeConfig, TalkrouteAPIKeyCredential, CONFIG_MODELS

KEY = "tr_live_" + "a" * 64
CREDENTIAL = {"credential_type": "talkroute_api_key", "api_key": KEY}
CONVERSATION = "17086010517-16308910180"
FIXTURES = Path(__file__).parent / "fixtures" / "talkroute"


def node(operation, **config):
    return TalkrouteNode(node_id="talkroute-test", node_type="automation-talkroute", node_data={},
        config=TalkrouteNodeConfig(config=CONFIG_MODELS[operation](**config), credentials=CREDENTIAL), sio=Mock())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", [
    ("get_account", {}, "GET", "/v2/account", None),
    ("list_virtual_numbers", {}, "GET", "/v2/virtual-numbers", None),
    ("get_virtual_number", {"id":"42"}, "GET", "/v2/virtual-numbers/42", None),
    ("list_voice_mailboxes", {}, "GET", "/v2/voice-mailboxes", None),
    ("list_voicemails", {}, "GET", "/v2/voice-messages", None),
    ("get_voicemail", {"id":"42"}, "GET", "/v2/voice-messages/42", None),
    ("get_voicemail_audio", {"id":"42"}, "GET", "/v2/voice-messages/42/audio-url", None),
    ("mark_voicemails_read", {"read":"unread", "ids":[1,2,42]}, "PATCH", "/v2/voice-messages/read/unread", {"ids":[1,2,42]}),
    ("list_conversations", {"since":"2026-06-01T12:00:00Z", "unread":False}, "GET", "/v2/text-conversations", None),
    ("list_messages", {"conversationId":CONVERSATION}, "GET", f"/v2/text-conversations/{CONVERSATION}/messages", None),
    ("send_text", {"conversationId":CONVERSATION, "body":"Hello, this is a sample message."}, "POST", f"/v2/text-conversations/{CONVERSATION}", {"body":"Hello, this is a sample message."}),
    ("mark_conversation_messages_read", {"conversationId":CONVERSATION, "id":["d6bee442-ec60-4380-aa3f-bf28e578a4e7"]}, "PATCH", f"/v2/text-conversations/{CONVERSATION}/messages/read", {"id":["d6bee442-ec60-4380-aa3f-bf28e578a4e7"]}),
    ("get_message", {"conversationId":CONVERSATION,"id":"42"}, "GET", f"/v2/text-conversations/{CONVERSATION}/messages/42", None),
    ("delete_message", {"conversationId":CONVERSATION,"id":"42"}, "DELETE", f"/v2/text-conversations/{CONVERSATION}/messages/42", None),
    ("list_contacts", {"favorite":False}, "GET", "/v2/contacts", None),
    ("get_contact", {"id":"uuid"}, "GET", "/v2/contacts/uuid", None),
    ("create_contact", {"name":"John Smith", "isFavorite":False}, "POST", "/v2/contacts", {"name":"John Smith", "isFavorite":False}),
    ("update_contact", {"id":"uuid", "emails":[], "isFavorite":False}, "PATCH", "/v2/contacts/uuid", {"emails":[], "isFavorite":False}),
    ("delete_contact", {"id":"uuid"}, "DELETE", "/v2/contacts/uuid", None),
    ("add_contact_phone", {"id":"uuid", "phoneNumber":"+18005550199", "type":"Mobile"}, "POST", "/v2/contacts/uuid/phone-numbers", {"phoneNumber":"+18005550199", "type":"Mobile"}),
    ("list_call_history", {"callerNumber":"+17023234800", "direction":"inbound"}, "GET", "/v2/call-history", None),
    ("list_forwarding_numbers", {}, "GET", "/v2/forwarding-numbers", None),
])
async def test_talkroute_requests(operation, config, method, path, body):
    response = {"data": {"id":"42"}, "pagination":{"page":1}}
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, "https://api.talkroute.com/api" + path).mock(
            return_value=httpx.Response(204) if method in {"PATCH","DELETE"} else httpx.Response(200,json=response))
        result = await node(operation, **config).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert json.loads(request.content) == body if body is not None else not request.content
    assert result["status"] == "success"
    if method in {"PATCH","DELETE"}:
        assert result["ok"] is True
    else:
        assert result["pagination"] == {"page":1}
    if operation.startswith("list_") and operation != "list_contacts":
        assert request.url.params["page"] == "1"
        assert request.url.params["pageSize"] == "50"
    if "unread" in config:
        assert request.url.params["unread"] == "false"
    if "favorite" in config:
        assert request.url.params["favorite"] == "false"


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["new_text_message","new_call_record","new_voicemail"])
async def test_talkroute_subscription_and_documented_payload(event):
    operation = "on_" + event
    config = {"operation":operation}
    payload = json.loads((FIXTURES / (event + ".json")).read_text())
    with respx.mock(assert_all_called=True) as router:
        register = router.post("https://api.talkroute.com/api/v2/subscriptions").mock(return_value=httpx.Response(201,json={"data":{"id":"subscription-id"}}))
        router.delete("https://api.talkroute.com/api/v2/subscriptions/subscription-id").mock(return_value=httpx.Response(204))
        state = await TalkrouteNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/test", credential=CREDENTIAL, config=config, node_id="test")
        assert json.loads(register.calls[0].request.content) == {"type":event,"hookUrl":"https://hooks.hooks.example.test/test"}
        await TalkrouteNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id="test")
    assert TalkrouteNode.verify_webhook_signature(json.dumps(payload).encode(), {}, config)
    assert TalkrouteNode.filter_trigger_payload(payload, config)
    for other in {"new_text_message","new_call_record","new_voicemail"} - {event}:
        assert not TalkrouteNode.filter_trigger_payload(payload, {"operation":"on_" + other})
    output = TalkrouteNode.resolve_trigger_payload({**payload,"_webhook":{"id":"private"}},config)
    assert output["data"] == payload
    agent = TalkrouteNode.resolve_agent_event(output)
    assert (payload.get("body") or payload.get("caller_number")) in agent["text"]
    assert agent["text"] and agent["conversation_key"]
    if event == "new_text_message":
        assert CONVERSATION in agent["text"]
    elif event == "new_voicemail":
        assert payload["transcription"] in agent["text"]
    assert (await node(operation).execute({}))["status"] == "no_event"


@pytest.mark.parametrize("bad", ["Bearer abc", "https://example.com/key", "<token>"])
def test_talkroute_manual_credential_rejects_invalid_input(bad):
    with pytest.raises(ValidationError):
        TalkrouteAPIKeyCredential(api_key=bad)


def test_talkroute_manual_credential_defaults_type():
    assert TalkrouteAPIKeyCredential(api_key=KEY).credential_type == "talkroute_api_key"


@pytest.mark.asyncio
async def test_talkroute_errors_and_redirects_do_not_look_successful():
    with respx.mock as router:
        router.get("https://api.talkroute.com/api/v2/account").mock(return_value=httpx.Response(401,json={"message":"Key rejected"}))
        with pytest.raises(ValueError,match="Key rejected"):
            await node("get_account").execute({})
        router.get("https://api.talkroute.com/api/v2/account").mock(return_value=httpx.Response(302,headers={"Location":"https://evil.example"}))
        with pytest.raises(ValueError,match="302"):
            await node("get_account").execute({})


def test_talkroute_path_input_is_bounded_and_empty_lists_rejected():
    with pytest.raises(ValidationError):
        node("get_contact",id="../account")
    with pytest.raises(ValidationError):
        node("send_text",conversationId="invalid",body="hello")
    with pytest.raises(ValidationError):
        node("mark_voicemails_read",ids=[])
