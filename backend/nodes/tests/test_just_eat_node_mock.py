"""Exercise Just Eat requests with the provider's published example payloads.

The tests also cover shared-token webhook authentication, notification destination
ownership during cleanup, and readable delivery events for agent workflows.
"""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from jsonschema import Draft4Validator, FormatChecker, RefResolver
from pydantic import ValidationError

from nodes.just_eat_node import (
    BASE, OPERATIONS, JustEatNode, JustEatNodeConfig,
    JustEatOnDeliveryEventConfig, JustEatTokenCredential,
)

FIXTURES = Path(__file__).parent / "fixtures" / "just-eat"
EXAMPLES = json.loads((FIXTURES / "provider_examples.json").read_text())
CONFIGS = json.loads((FIXTURES / "configs.json").read_text())
SCHEMAS = json.loads((FIXTURES / "request_schemas.json").read_text())
CREDENTIAL = {"credential_type": "just_eat_token", "access_token": "a-realistic-partner-token"}
PROVIDER_OPERATIONS = {
    "estimate_delivery": "v1DeliveryEstimatePost", "create_delivery": "v1DeliveryPost",
    "get_delivery_status": "v1DeliveryStatusRequestIdGet", "cancel_delivery": "v1DeliveryCancellationRequestPut",
    "list_collect_points": "v1DeliveryCollectPointsGet", "request_assistance": "v1DeliveryRequestAssistancePost",
    "get_notification_config": "v1DeliveryNotificationConfigGet", "create_notification_config": "v1DeliveryNotificationConfigPost",
    "update_notification_config": "v1DeliveryNotificationConfigPatch", "delete_notification_config": "v1DeliveryNotificationConfigDelete",
    "simulate_delivery": "v1DeliverySimulatePost",
}


def node(operation, config=None):
    raw = {"operation": operation, **(config if config is not None else CONFIGS.get(operation, {}).get("config", {}))}
    return JustEatNode(node_id="test", node_type="automation-just-eat", node_data={"config": raw},
        config=JustEatNodeConfig.model_validate({"config": raw, "credentials": CREDENTIAL}), sio=Mock())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(OPERATIONS))
async def test_operations_send_the_published_method_and_body(monkeypatch, operation):
    requests = []
    response_schema = {
        "estimate_delivery": "DaasDaaSEstimateResponse", "create_delivery": "DaasDaaSDeliveryResponse",
        "get_delivery_status": "DaasDaaSDeliveryStatusResponse", "cancel_delivery": "DaasDaaSCancelDeliveryResponse",
        "list_collect_points": "DaasDaaSCollectPointResponse", "request_assistance": "DaasDaaSAssistanceRequestResponse",
        "get_notification_config": "DaasDaaSNotificationConfigResponse", "simulate_delivery": "DaasDaaSSimulateDeliveryResponse",
    }.get(operation)
    provider_response = EXAMPLES[response_schema] if response_schema else None
    async def request(self, method, url, **kwargs):
        requests.append((method, url, kwargs))
        if provider_response is None:
            return httpx.Response(204, request=httpx.Request(method, url))
        return httpx.Response(200, json=provider_response, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    result = await node(operation).execute({})
    method, url, kwargs = requests[0]
    assert result["status"] == "success"
    assert result["data"] == (provider_response if provider_response is not None else {"ok": True})
    assert len(requests) == 1
    contract = SCHEMAS["endpoints"][PROVIDER_OPERATIONS[operation]]
    assert method == contract["method"]
    path = contract["path"]
    if "{requestId}" in path:
        path = path.replace("{requestId}", CONFIGS[operation]["config"]["request_id"])
    assert url == BASE + path
    assert kwargs["headers"]["Authorization"] == "Bearer " + CREDENTIAL["access_token"]
    assert kwargs["headers"]["User-Agent"] == "NoClick/1.0"
    if kwargs["json"] is not None:
        key = method + " " + OPERATIONS[operation][2]
        # Validate the body independently of the contract's malformed server URL.
        # These schemas are copied unchanged from the pinned provider document.
        Draft4Validator(SCHEMAS["operations"][key], resolver=RefResolver.from_schema(SCHEMAS),
            format_checker=FormatChecker()).validate(kwargs["json"])
    if operation == "estimate_delivery":
        expected = dict(EXAMPLES["DaasDaaSEstimateRequest"])
        actual = dict(kwargs["json"])
        assert datetime.fromisoformat(actual.pop("targetDeliverTime")) == datetime.fromisoformat(expected.pop("targetDeliverTime"))
        assert actual == expected
    elif operation == "create_delivery":
        # Datetime serialization normalizes UTC to Z, preserving the same instant.
        expected = dict(EXAMPLES["DaasDaaSDeliveryRequest"])
        actual = dict(kwargs["json"])
        assert datetime.fromisoformat(actual.pop("targetCollectTime")) == datetime.fromisoformat(expected.pop("targetCollectTime"))
        assert actual == expected
    elif operation == "request_assistance":
        assert kwargs["json"] == EXAMPLES["DaasDaaSAssistanceRequest"]
    elif operation in {"cancel_delivery", "simulate_delivery"}:
        schema = "DaasDaaSCancelDeliveryRequest" if operation == "cancel_delivery" else "DaasDaasSimulateDeliveryRequest"
        assert kwargs["json"] == EXAMPLES[schema]
    elif operation == "list_collect_points":
        assert kwargs["params"] == {"limit": 100, "offset": 0}
    elif operation == "create_notification_config":
        assert kwargs["json"]["type"] == "TOKEN"
        assert "username" not in kwargs["json"]


@pytest.mark.asyncio
async def test_provider_collection_points_are_preserved(monkeypatch):
    async def request(*args, **kwargs):
        return EXAMPLES["DaasDaaSCollectPointResponse"]
    monkeypatch.setattr(JustEatNode, "_request", request)
    assert (await node("list_collect_points").execute({}))["data"] == EXAMPLES["DaasDaaSCollectPointResponse"]


@pytest.mark.asyncio
async def test_registration_token_verification_and_owned_cleanup(monkeypatch):
    calls = []
    endpoint = "https://test.hooks.example.test/webhook/just-eat"
    async def request(credential, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"endpoint": endpoint} if method == "GET" else {"ok": True}
    monkeypatch.setattr(JustEatNode, "_request", request)
    config = {"operation": "on_delivery_event", **CONFIGS["on_delivery_event"]["config"]}
    state = await JustEatNode._register_external_webhook(webhook_url=endpoint, credential=CREDENTIAL, config=config, node_id="test")
    body = calls[0][2]["body"]
    assert body == {"email": "email@partner.com", "endpoint": endpoint, "secret": state["signing_secret"], "type": "TOKEN"}
    assert JustEatNode.verify_webhook_signature(b"{}", {"X-API-Key": state["signing_secret"]}, state)
    assert not JustEatNode.verify_webhook_signature(b"{}", {"x-api-key": "wrong"}, state)
    assert not JustEatNode.verify_webhook_signature(b"{}", {}, state)
    assert not JustEatNode.verify_webhook_signature(b"{}", {"x-api-key": "wrong"}, {})
    await JustEatNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id="test")
    assert [c[0] for c in calls] == ["POST", "GET", "DELETE"]


@pytest.mark.asyncio
async def test_cleanup_preserves_a_replacement_destination(monkeypatch):
    calls = []
    async def request(credential, method, path, **kwargs):
        calls.append(method)
        return {"endpoint": "https://another-workflow.hooks.example.test/webhook/another"}
    monkeypatch.setattr(JustEatNode, "_request", request)
    await JustEatNode._unregister_external_webhook(credential=CREDENTIAL,
        config={"external_webhook_id": "https://original.hooks.example.test/webhook/original"}, node_id="test")
    assert calls == ["GET"]


def test_documented_delivery_event_reaches_an_agent_with_actionable_context():
    event = EXAMPLES["event"]
    assert JustEatNode.filter_trigger_payload(event, {})
    output = JustEatNode.resolve_trigger_payload(event, {})
    message = JustEatNode.resolve_agent_event(output)
    for value in ["COURIERJOBSTATUS", "DELIVERED", "Example Courier", event["data"]["requestId"],
                  event["data"]["orderId"], event["data"]["orderTrackerURL"]]:
        assert value in message["text"]
    assert not JustEatNode.filter_trigger_payload({"type": "unrecognized"}, {})
    assert JustEatNode.resolve_agent_event({"status": "waiting"}) is None


def test_manual_credential_and_trigger_confirmation():
    assert JustEatTokenCredential(access_token="partner-token").credential_type == "just_eat_token"
    with pytest.raises(ValidationError):
        JustEatTokenCredential(access_token="Bearer partner-token")
    with pytest.raises(ValidationError):
        JustEatOnDeliveryEventConfig(email="email@partner.com")
    with pytest.raises(ValidationError):
        JustEatOnDeliveryEventConfig(email="email@partner.com", replace_existing_configuration=False)


@pytest.mark.asyncio
async def test_empty_success_and_provider_error_are_handled(monkeypatch):
    async def empty(self, method, url, **kwargs):
        return httpx.Response(204, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", empty)
    assert (await node("delete_notification_config").execute({}))["data"] == {"ok": True}
    async def rejected(self, method, url, **kwargs):
        return httpx.Response(401, text="Token was rejected: " + CREDENTIAL["access_token"], request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", rejected)
    with pytest.raises(ValueError, match="Token was rejected: \\[redacted\\]"):
        await node("list_collect_points").execute({})


@pytest.mark.asyncio
async def test_invalid_json_fails_before_sending(monkeypatch):
    async def unexpected(*args, **kwargs):
        pytest.fail("Invalid JSON reached the provider")
    monkeypatch.setattr(JustEatNode, "_request", unexpected)
    for value in ["not JSON", "[]"]:
        with pytest.raises(ValueError):
            await node("estimate_delivery", {"collect_point_id": "point", "delivery_json": value}).execute({})
