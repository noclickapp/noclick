"""Procore's documented v2.0 delivery and webhook API lifecycle.

The fixture is copied from Procore's webhook guide; these tests also check the
caller-supplied bearer secret, scoping and cleanup after partial registration.
"""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import respx

from nodes.procore_node import OnResourceEvent, ProcoreNode, ProcoreNodeConfig

EVENT = json.loads((Path(__file__).parent / "fixtures/procore/events.json").read_text())["rfi.updated"]["body"]
CONFIG = {"operation": "on_resource_event", "company_id": EVENT["company_id"],
          "project_id": EVENT["project_id"], "resource_name": "RFIs", "event_type": "update"}
CREDENTIAL = {"credential_type": "procore_oauth", "access_token": "access"}


@pytest.mark.asyncio
@pytest.mark.parametrize("project", [True, False])
@pytest.mark.parametrize("event_type", ["create", "update", "delete"])
async def test_procore_webhook_registration_and_cleanup(project, event_type):
    config = {**CONFIG, "event_type": event_type}
    if not project:
        config.pop("project_id")
    path = f"/rest/v2.0/companies/{EVENT['company_id']}"
    if project:
        path += f"/projects/{EVENT['project_id']}"
    path += "/webhooks/hooks"
    with respx.mock as router:
        # Hook ID and response envelope from the published v2 OpenAPI.
        hook = router.post("https://api.procore.com" + path).respond(201, json={"data": {"id": "43593499"}})
        trigger = router.post("https://api.procore.com" + path + "/43593499/triggers").respond(201, json={"data": {"id": "231346546"}})
        delete = router.delete("https://api.procore.com" + path + "/43593499").respond(204)
        state = await ProcoreNode._register_external_webhook(webhook_url="https://test.hooks.example.test/webhook/test", credential=CREDENTIAL, config=config, node_id="test")
        expected_scope = f"{EVENT['company_id']}:{EVENT['project_id'] if project else ''}:43593499"
        assert state["external_webhook_id"] == expected_scope
        assert len(state["signing_secret"]) >= 32
        body = json.loads(hook.calls[0].request.content)
        assert body == {"payload_version": "v2.0", "namespace": "noclick",
                        "destination_url": "https://test.hooks.example.test/webhook/test",
                        "destination_headers": {"Authorization": "Bearer " + state["signing_secret"]}}
        assert json.loads(trigger.calls[0].request.content) == {"resource_name": "RFIs", "event_type": event_type}
        for request in (hook.calls[0].request, trigger.calls[0].request):
            assert request.headers["Authorization"] == "Bearer access"
            assert request.headers["Procore-Company-Id"] == str(EVENT["company_id"])
        # Teardown must retain its original scope after the user edits config.
        await ProcoreNode._unregister_external_webhook(credential=CREDENTIAL, config={**config, **state, "company_id": 1, "project_id": 2}, node_id="test")
        assert delete.called
        for key in ("company_id", "project_id", "resource_name", "event_type"):
            assert key in ProcoreNode.registration_fingerprint_fields(config)


@pytest.mark.asyncio
async def test_procore_trigger_failure_removes_created_hook():
    path = "https://api.procore.com" + ProcoreNode._hook_path(CONFIG)
    with respx.mock as router:
        router.post(path).respond(201, json={"data": {"id": "43593499"}})
        router.post(path + "/43593499/triggers").respond(403)
        delete = router.delete(path + "/43593499").respond(204)
        with pytest.raises(ValueError, match="403"):
            await ProcoreNode._register_external_webhook(webhook_url="https://test.hooks.example.test/webhook/test", credential=CREDENTIAL, config=CONFIG, node_id="test")
        assert delete.called


def test_procore_delivery_authentication():
    body = json.dumps(EVENT).encode()
    config = {**CONFIG, "signing_secret": "secret"}
    assert ProcoreNode.verify_webhook_signature(body, {"Authorization": "Bearer secret"}, config)
    for headers in ({}, {"authorization": "Bearer wrong"}, {"authorization": "secret"}, {"authorization": "Bearer sëcret"}):
        assert not ProcoreNode.verify_webhook_signature(body, headers, config)
    assert not ProcoreNode.verify_webhook_signature(body, {"authorization": "Bearer secret"}, CONFIG)


def test_procore_documented_event_to_agent():
    assert ProcoreNode.filter_trigger_payload(EVENT, CONFIG)
    assert ProcoreNode.filter_trigger_payload(EVENT, {**CONFIG, "resource_name": " RFIs "})
    assert ProcoreNode.filter_trigger_payload(EVENT, {**CONFIG, "project_id": None})
    for field, value in (("company_id", 1), ("project_id", 1), ("resource_name", "Other"), ("event_type", "delete"), ("api_version", "v4.0")):
        assert not ProcoreNode.filter_trigger_payload({**EVENT, field: value}, CONFIG)
    output = ProcoreNode.resolve_trigger_payload(EVENT, CONFIG)
    event = ProcoreNode.resolve_agent_event(output)
    assert "RFIs update" in event["text"]
    assert "user 987654321" in event["text"]
    assert "get_rfi company_id=1357908642 project_id=2468013579 rfi_id=54321" in event["text"]
    assert event["conversation_key"] == "1357908642:2468013579:RFIs:54321"
    # Malformed input must not cause the event formatter to fail.
    assert ProcoreNode.resolve_agent_event({}) is not None


@pytest.mark.asyncio
async def test_procore_trigger_is_not_an_action():
    model = ProcoreNodeConfig.model_validate({"config": {**CONFIG, "signing_secret": "saved"}, "credentials": CREDENTIAL})
    assert model.config.signing_secret == "saved"
    assert OnResourceEvent.model_json_schema()["properties"]["operation"]["x-is-trigger"] is True
    node = ProcoreNode(node_id="test", node_type="automation-procore", node_data={}, config=model, sio=Mock())
    assert (await node.execute({}))["status"] == "no_event"
