"""Webhook examples copied from https://developers.figma.com/docs/rest-api/webhooks-events/."""
import json
from pathlib import Path

import httpx
import pytest
import respx

from nodes.figma_node import FigmaNode, FigmaOnEventConfig, FigmaNodeConfig

EVENTS = json.loads((Path(__file__).parent / "fixtures/figma/events.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_type,header", [("figma_pat", "X-Figma-Token"), ("figma_oauth", "Authorization")])
async def test_register_unregister_and_verify(credential_type, header):
    config = {"operation": "on_event", "event_type": "FILE_COMMENT", "context": "file", "context_id": "zH44k2FUM629Fa4EMShiHL"}
    credential = {"credential_type": credential_type, "access_token": "token"}
    with respx.mock(assert_all_called=True) as router:
        create = router.post("https://api.figma.com/v2/webhooks").mock(return_value=httpx.Response(200, json={"id": "22"}))
        delete = router.delete("https://api.figma.com/v2/webhooks/22").mock(return_value=httpx.Response(200, json={"id": "22"}))
        state = await FigmaNode._register_external_webhook(webhook_url="https://example.com/hook", credential=credential, config=config, node_id="figma")
        body = json.loads(create.calls[0].request.content)
        assert body == {"event_type": "FILE_COMMENT", "context": "file", "context_id": config["context_id"], "endpoint": "https://example.com/hook", "passcode": state["signing_secret"]}
        assert len(state["signing_secret"]) >= 32
        assert create.calls[0].request.headers[header] == ("token" if credential_type == "figma_pat" else "Bearer token")
        event = {**EVENTS["FILE_COMMENT"]["body"], "passcode": state["signing_secret"]}
        assert FigmaNode.verify_webhook_signature(json.dumps(event).encode(), {}, state)
        assert not FigmaNode.verify_webhook_signature(json.dumps({**event, "passcode": "wrong"}).encode(), {}, state)
        await FigmaNode._unregister_external_webhook(credential=credential, config=state, node_id="figma")
        assert delete.called
    assert FigmaNodeConfig.model_validate({"config": {**config, **state}}).config.signing_secret == state["signing_secret"]


@pytest.mark.parametrize("body", [b"{}", b"[]", b"null", b"not json", b'{"passcode": 42}', b'\xff'])
def test_invalid_deliveries_fail_closed(body):
    assert not FigmaNode.verify_webhook_signature(body, {}, {"signing_secret": "secretpasscode"})
    assert not FigmaNode.verify_webhook_signature(body, {}, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", list(EVENTS))
async def test_documented_events(event_type):
    payload = EVENTS[event_type]["body"]
    assert FigmaNode.verify_webhook_signature(json.dumps(payload).encode(), {}, {"signing_secret": "secretpasscode"})
    control = await FigmaNode.handle_control_event(payload, {}, pool=None, workflow_id=None, node_id=None)
    if event_type == "PING":
        assert control
        assert FigmaNode.resolve_agent_event(payload) is None
        return
    assert control is None
    config = {"event_type": event_type}
    assert FigmaNode.filter_trigger_payload(payload, config)
    assert not FigmaNode.filter_trigger_payload(payload, {"event_type": "PING"})
    output = FigmaNode.resolve_trigger_payload({**payload, "_webhook": {"headers": {}}}, config)
    assert "passcode" not in output and "_webhook" not in output
    event = FigmaNode.resolve_agent_event(output)
    assert payload["file_key"] == event["conversation_key"]
    assert payload["file_name"] in event["text"]
    assert payload["file_key"] in event["text"]
    assert "secretpasscode" not in event["text"]
    if event_type == "FILE_COMMENT":
        assert "Change selection colors" in event["text"]
        assert "Dylan Field" in event["text"]
        assert "comment_id=32" in event["text"]
        assert "@811724164054158337" in event["text"]
    if event_type == "DEV_MODE_STATUS_UPDATE":
        assert payload["node_id"] in event["text"] and payload["status"] in event["text"]
    if event_type == "FILE_VERSION_UPDATE":
        assert payload["version_id"] in event["text"]
    if event_type == "LIBRARY_PUBLISH":
        assert "Matched colors to guidelines" in event["text"]


def test_registration_fingerprint_and_event_schema():
    config = {"event_type": "FILE_UPDATE", "context": "file", "context_id": "f"}
    assert FigmaNode.registration_fingerprint_fields(config) == config
    with pytest.raises(ValueError):
        FigmaOnEventConfig(context_id="f", event_type="PING")
    with pytest.raises(ValueError):
        FigmaOnEventConfig(context_id="")
