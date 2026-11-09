"""Exercise Connect lifecycle and deliveries against Docusign's own examples.

The fixtures retain the provider's placeholders; the Connect example's blank
`event` is filled with the documented envelope-sent event when testing summaries.
"""

import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.docusign_node import (
    DOCUSIGN_EVENTS, DocusignNode, DocusignNodeConfig, DocusignOAuthCredential,
    OnDocusignEvent,
)

FIXTURES = Path(__file__).parent / "fixtures" / "docusign"
API = "https://demo.docusign.net/restapi/v2.1/accounts/acct-1"
AUTH = {"access_token": "access", "refresh_token": "refresh", "account_id": "acct-1",
        "base_uri": "https://demo.docusign.net", "expires_at": "2099-01-01T00:00:00Z"}


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("event", DOCUSIGN_EVENTS)
async def test_connect_registration_and_teardown(event):
    with respx.mock(assert_all_called=True) as router:
        create = router.post(API + "/connect").mock(
            return_value=httpx.Response(201, json={"connectId": "10242474"}))
        delete = router.delete(API + "/connect/10242474").mock(return_value=httpx.Response(204))
        result = await DocusignNode._register_external_webhook(
            webhook_url="https://example.com/webhook", credential=AUTH,
            config={"event_type": event, "connect_hmac_secret": '"account-key"'}, node_id="node")
        await DocusignNode._unregister_external_webhook(
            credential=AUTH, config=result, node_id="node")
    assert result == {"external_webhook_id": "10242474", "signing_secret": "account-key"}
    body = json.loads(create.calls[0].request.content)
    assert body["events"] == [event]
    assert body["includeHMAC"] == "true"
    assert body["deliveryMode"] == "SIM"
    assert body["eventData"] == {"version": "restv2.1", "includeData": ["recipients"]}
    assert body["urlToPublishTo"] == "https://example.com/webhook"
    assert create.calls[0].request.headers["Authorization"] == "Bearer access"
    assert delete.call_count == 1


@pytest.mark.asyncio
async def test_registration_validates_before_request_and_fails_loudly():
    with pytest.raises(ValidationError):
        await DocusignNode._register_external_webhook(
            webhook_url="https://example.com", credential=AUTH,
            config={"event_type": "invented", "connect_hmac_secret": "key"}, node_id="node")
    with respx.mock(assert_all_called=True) as router:
        router.post(API + "/connect").mock(return_value=httpx.Response(201, json={}))
        with pytest.raises(ValueError, match="configuration ID"):
            await DocusignNode._register_external_webhook(
                webhook_url="https://example.com", credential=AUTH,
                config={"connect_hmac_secret": "key"}, node_id="node")
    with respx.mock(assert_all_called=True) as router:
        router.delete(API + "/connect/123").mock(return_value=httpx.Response(403))
        with pytest.raises(ValueError, match="403"):
            await DocusignNode._unregister_external_webhook(
                credential=AUTH, config={"external_webhook_id": "123"}, node_id="node")
    with pytest.raises(ValueError, match="Connect Docusign"):
        await DocusignNode._unregister_external_webhook(
            credential=None, config={"external_webhook_id": "123"}, node_id="node")


def test_hmac_exact_body_numbered_headers_and_key_rotation():
    body = (FIXTURES / "envelope-sent.json").read_bytes()
    signature = base64.b64encode(hmac.new(b"account-key", body, hashlib.sha256).digest()).decode()
    headers = {"X-Docusign-Signature-1": "wrong", "x-DocuSign-Signature-2": signature}
    verify = DocusignNode.verify_webhook_signature
    assert verify(body, headers, {"signing_secret": "account-key"})
    assert verify(body, headers, {"signing_secret": '"account-key"'})
    assert not verify(body + b"\n", headers, {"signing_secret": "account-key"})
    assert not verify(body, headers, {"signing_secret": "other-key"})
    assert not verify(body, headers, {})
    assert not verify(body, {}, {"signing_secret": "account-key"})
    assert not verify(body, {"X-Docusign-Signature": signature}, {"signing_secret": "account-key"})
    assert not verify(body, {"X-Docusign-Signature-1": "non-ascii-λ"}, {"signing_secret": "account-key"})


@pytest.mark.parametrize("event", DOCUSIGN_EVENTS)
def test_documented_events_and_wrong_event_filter(event):
    payload = fixture(event)
    assert DocusignNode.resolve_trigger_payload(payload, {"event_type": event}) == payload
    assert DocusignNode.resolve_trigger_payload(payload, {"event_type": "different"})["status"] == "no_event"
    assert DocusignNode.resolve_trigger_payload(
        payload, {"event_type": event, "external_webhook_id": "different"})["status"] == "no_event"


@pytest.mark.asyncio
async def test_manual_trigger_does_not_refresh_or_call_docusign():
    node = DocusignNode(
        node_id="node", node_type="automation-docusign", node_data={},
        config=DocusignNodeConfig(config=OnDocusignEvent(connect_hmac_secret="key"),
                                  credentials=DocusignOAuthCredential(**AUTH)),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")
    with respx.mock(assert_all_called=True):
        result = await node.execute({})
    assert result["status"] == "no_event"
    assert DocusignNode.resolve_agent_event(result) is None


def test_agent_turn_has_documented_sender_content_and_action_ids():
    payload = fixture("connect-example")
    payload["event"] = "envelope-sent"
    data = payload["data"]
    summary = data["envelopeSummary"]
    for output in [payload, {"status": "success", "data": payload}]:
        result = DocusignNode.resolve_agent_event(output)
        assert result["conversation_key"] == f"{data['accountId']}:{data['envelopeId']}"
        for value in [summary["emailSubject"], summary["emailBlurb"], summary["sender"]["email"],
                      data["envelopeId"], data["accountId"], "get_envelope", "download_document"]:
            assert value in result["text"]
        assert result["title"] == summary["emailSubject"]
    # The docs' abbreviated summary is a string, not a dict; still actionable.
    sent = fixture("envelope-sent")
    result = DocusignNode.resolve_agent_event(sent)
    assert sent["data"]["envelopeId"] in result["text"]


def test_registration_fingerprint_tracks_subscription_and_key_only():
    config = {"event_type": "envelope-sent", "connect_hmac_secret": "key", "webhook_url": "mirror"}
    assert DocusignNode.registration_fingerprint_fields(config) == {
        "event_type": "envelope-sent", "connect_hmac_secret": "key"}
