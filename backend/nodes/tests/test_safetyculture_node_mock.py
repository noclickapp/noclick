"""Native-factory tests against captured requests and synthetic contract fixtures."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import safetyculture_node as sc
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": sc.CREDENTIAL_TYPE, "api_token": "synthetic-safetyculture-test-token"}
IDENTIFIER = "80e42a67-01d2-40f5-9e65-011bd09ee0f0"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.mitti.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_token"]
        assert AUTH["api_token"] not in str(request.url)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(sc, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type=sc.SafetyCultureNode.integration_type,
        operation=operation, arguments=arguments or {}, credential_data=deepcopy(AUTH),
        user_id="00000000-0000-4000-8000-000000000001")


CASES = json.loads((Path(__file__).parent / "fixtures/safetyculture/wire_cases.json").read_text())["cases"]


@pytest.mark.parametrize("operation,arguments,method,path,body,payload", CASES)
@pytest.mark.asyncio
async def test_safetyculture_wire_contract(transport, operation, arguments, method, path, body, payload):
    requests, replies = transport
    replies.append((200, payload))
    result = await run(operation, arguments)
    assert result["status"] == "success" and result["data"] == payload
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == path
    if body is not None:
        assert json.loads(request.content) == body
    else:
        assert request.content == b""
    if operation == "search_inspections":
        assert request.url.params.get_list("field") == ["audit_id", "modified_at", "template_id"]
    if operation == "search_templates":
        assert request.url.params.get_list("field") == ["template_id", "name", "modified_at", "created_at"]


@pytest.mark.asyncio
async def test_safetyculture_search_parameters(transport):
    requests, replies = transport
    replies.append((200, {"audits": []}))
    await run("search_inspections", {"template": [IDENTIFIER, "another-template"], "modified_after": "2026-11-01T00:00:00Z", "completed": "true", "owner": "me"})
    assert requests[0].url.params.get_list("template") == [IDENTIFIER, "another-template"]
    assert requests[0].url.params["modified_after"] == "2026-11-01T00:00:00Z"
    assert requests[0].url.params["completed"] == "true"


@pytest.mark.parametrize("code", [301, 401, 403, 429, 500])
@pytest.mark.asyncio
async def test_safetyculture_refusals_and_no_retry(transport, code):
    requests, replies = transport
    replies.append((code, {"message": "Provider rejected " + AUTH["api_token"]}))
    result = await run("create_action", {"title": "Check"})
    assert result["success"] is False and result["http_status"] == code
    assert result["write_outcome"] == "unverified" and len(requests) == 1
    assert AUTH["api_token"] not in json.dumps(result)


@pytest.mark.asyncio
async def test_safetyculture_rejects_error_envelope(transport):
    _, replies = transport
    replies.append((200, {"code": 7, "message": "Denied"}))
    with pytest.raises(ValueError, match="invalid or error"):
        await run("list_groups")


@pytest.mark.parametrize("value", ["https://app.mitti.com", "<token>", "Bearer token", "a\r\nb", "unicode–token", ""])
def test_safetyculture_manual_credential_validation(value):
    with pytest.raises(ValidationError):
        sc.SafetyCultureAPITokenCredential(api_token=value)


def test_safetyculture_default_credential_type():
    assert sc.SafetyCultureAPITokenCredential(api_token="  synthetic-token\n").model_dump() == {"credential_type": sc.CREDENTIAL_TYPE, "api_token": "synthetic-token"}


@pytest.mark.parametrize("value", ["../other", "a/b", "a?x=y", "%2f", ".."])
def test_safetyculture_resource_path_validation(value):
    with pytest.raises(ValidationError):
        sc.GetAction(action_id=value)


def test_safetyculture_dates_and_write_body_limits():
    with pytest.raises(ValidationError):
        sc.CreateAction(title="x" * 256)
    with pytest.raises(ValidationError):
        sc.UpdateActionDueDate(action_id=IDENTIFIER, due_at="2026-11-10T09:00:00")


WEBHOOK_EVENTS = json.loads((Path(__file__).parent / "fixtures/safetyculture/webhook_events.json").read_text())["events"]


@pytest.mark.parametrize("operation,event_type", sc.TRIGGER_EVENTS.items())
@pytest.mark.asyncio
async def test_safetyculture_trigger_lifecycle(transport, operation, event_type):
    requests, replies = transport
    replies.extend([(200, {"token": "org-signing-secret"}),
                    (200, {"webhook": {"webhook_id": IDENTIFIER}}), (200, {})])
    config = {"operation": operation}
    registration = await sc.SafetyCultureNode._register_external_webhook(
        webhook_url="https://example.com", credential=AUTH, config=config, node_id="test")
    assert registration == {"external_webhook_id": IDENTIFIER, "signing_secret": "org-signing-secret"}
    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", "/webhooks/v1/token"), ("POST", "/webhooks/v1/webhooks")]
    assert json.loads(requests[1].content) == {"url": "https://example.com", "trigger_events": [event_type]}
    await sc.SafetyCultureNode._unregister_external_webhook(
        credential=AUTH, config={**config, **registration}, node_id="test")
    assert requests[-1].method == "DELETE"
    assert requests[-1].url.path == "/webhooks/v1/webhooks/" + IDENTIFIER
    assert not replies


@pytest.mark.parametrize("operation,event_type", sc.TRIGGER_EVENTS.items())
@pytest.mark.asyncio
async def test_safetyculture_documented_signed_event(operation, event_type):
    import hashlib
    import hmac
    payload = deepcopy(WEBHOOK_EVENTS[event_type]["body"])
    body = json.dumps(payload).encode()
    config = {"operation": operation, "signing_secret": "org-secret"}
    headers = {"X-SafetyCulture-Signature": hmac.new(b"org-secret", body, hashlib.sha256).hexdigest()}
    node = sc.SafetyCultureNode
    assert node.verify_webhook_signature(body, headers, config)
    assert not node.verify_webhook_signature(body + b" ", headers, config)
    assert not node.verify_webhook_signature(body, {}, config)
    assert not node.verify_webhook_signature(body, headers, {"operation": operation})
    assert node.filter_trigger_payload(payload, config)
    output = node.resolve_trigger_payload(payload, config)
    event = node.resolve_agent_event(output)
    inspection_id = payload["resource"]["id"]
    assert event["conversation_key"] == inspection_id
    assert inspection_id in event["text"] and payload["event"]["triggered_by"]["user"] in event["text"]
    assert payload["data"]["details"]["template_id"] in event["text"]
    node_instance = node(node_id="test", node_type=node.integration_type,
        node_data={}, config=sc.SafetyCultureFullConfig.model_validate({"config": {"operation": operation}, "credentials": AUTH}), sio=Mock())
    assert await node_instance.execute(payload) == output
    result = await run(operation, {})
    assert result["status"] == "no_event" and node.resolve_agent_event(result) is None
    schema = node.get_config_schema()
    assert schema["$defs"]["OnInspectionStarted"]["properties"]["operation"]["x-is-trigger"]
    assert schema["$defs"]["OnInspectionCompleted"]["properties"]["operation"]["x-is-trigger"]


def test_safetyculture_filters_other_events_and_incomplete_inspections():
    node = sc.SafetyCultureNode
    started = deepcopy(WEBHOOK_EVENTS[sc.TRIGGER_EVENTS["on_inspection_started"]]["body"])
    assert not node.filter_trigger_payload(started, {"operation": "on_inspection_completed"})
    completed = deepcopy(WEBHOOK_EVENTS[sc.TRIGGER_EVENTS["on_inspection_completed"]]["body"])
    assert not node.filter_trigger_payload(completed, {"operation": "on_inspection_started"})
    completed["data"].pop("inspection_completed_set")
    assert not node.filter_trigger_payload(completed, {"operation": "on_inspection_completed"})
    assert not node.filter_trigger_payload({}, {"operation": "on_inspection_started"})


@pytest.mark.asyncio
async def test_safetyculture_does_not_register_without_signing_secret(transport):
    requests, replies = transport
    replies.append((200, {}))
    with pytest.raises(ValueError, match="signing secret"):
        await sc.SafetyCultureNode._register_external_webhook(webhook_url="https://example.com",
            credential=AUTH, config={"operation": "on_inspection_started"}, node_id="test")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_safetyculture_cleanup_already_deleted(transport):
    requests, replies = transport
    replies.append((404, {}))
    await sc.SafetyCultureNode._unregister_external_webhook(credential=AUTH,
        config={"external_webhook_id": IDENTIFIER}, node_id="test")
    assert len(requests) == 1
