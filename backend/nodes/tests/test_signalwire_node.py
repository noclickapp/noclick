"""Unrun SignalWire transport, paging, privacy and explicit-effect regressions.

Actual HTTPX MockTransport passes through the existing guarded client. Only
destination resolution is substituted; no provider, socket or database is used.
"""
from copy import deepcopy
import json

import httpx
import pytest

from nodes import signalwire_node as node
from utils import ssrf

CREDENTIAL = {"credential_type": node.TYPE, "space_url": "https://fixture.signalwire.com", "project_id": "11111111-1111-4111-8111-111111111111", "api_token": "fixture-api-token"}
RID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, state = [], {"handler": None}
    monkeypatch.setattr(ssrf, "assert_url_allowed", lambda *args, **kwargs: permitted())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    actual = ssrf.guarded_async_client
    async def provider(request):
        calls.append(request)
        assert request.headers["Authorization"] == node.auth_header(node.credential_value(CREDENTIAL))
        assert request.url.host == "fixture.signalwire.com"
        assert "api_token" not in request.url.params
        return state["handler"](request)
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(provider), **kwargs))
    return calls, state


async def permitted():
    return None


def response(data, status=200):
    return httpx.Response(status, json=data)


def message(**change):
    return {"id": RID, "project_id": CREDENTIAL["project_id"], "status": "delivered", "kind": "sms", "direction": "outbound", "number_of_segments": 1, "from": "+15550001111", "to": "+15550002222", "body": "private content", "charge": 0.1, "error_message": CREDENTIAL["api_token"], "status_callback_url": "https://private.example.test", **change}


@pytest.mark.parametrize("url", ["http://fixture.signalwire.com", "https://fixture.signalwire.com:443", "https://user:password@fixture.signalwire.com", "https://fixture.signalwire.com/api", "https://signalwire.com", "https://fixture.signalwire.com.evil.test", "https://127.0.0.1", "https://fixture.signalwire.com?api_token=secret", "https://fixture.signalwire.com/#fragment"])
def test_space_origin_is_strict(url):
    with pytest.raises(ValueError):
        node.credential_value({**CREDENTIAL, "space_url": url})


@pytest.mark.parametrize("token", ["", "Bearer supplied", "pat_personal-token", "https://example.test/token", "<your-token>", "bad\nheader", 123])
def test_project_token_rejects_other_family_or_malformed_secret(token):
    with pytest.raises(ValueError):
        node.credential_value({**CREDENTIAL, "api_token": token})


async def test_log_metadata_keeps_native_basic_wire_and_omits_private_content(transport):
    calls, state = transport
    state["handler"] = lambda request: response({"links": {"self": str(request.url)}, "data": [message()]})
    result = await node.request_operation(CREDENTIAL, node.ListMessages(created_on="2026-10-06"))
    item = result["data"]["items"][0]
    assert item == {"id": RID, "status": "delivered", "direction": "outbound", "kind": "sms", "number_of_segments": 1}
    assert calls[0].url.path == "/api/messaging/logs" and calls[0].url.params["include_deleted"] == "false"
    assert calls[0].url.params["created_on"] == "2026-10-06" and result["data"]["next_page_token"] is None


async def test_native_paging_reconstructs_same_collection_and_binds_current_credential(transport):
    calls, state = transport
    state["handler"] = lambda request: response({"links": {"next": "/api/messaging/logs?page_number=1&page_size=50&page_token=PA-native-token"} if len(calls) == 1 else {}, "data": [message()]})
    first = await node.request_operation(CREDENTIAL, node.ListMessages())
    continuation = first["data"]["next_page_token"]
    await node.request_operation(CREDENTIAL, node.ListMessages(page_token=continuation))
    assert len(calls) == 2 and calls[-1].url.params["page_number"] == "1" and calls[-1].url.params["page_token"] == "PA-native-token"
    with pytest.raises(ValueError, match="Continuation"):
        await node.request_operation({**CREDENTIAL, "api_token": "rotated-token"}, node.ListMessages(page_token=continuation))
    with pytest.raises(ValueError, match="Continuation"):
        await node.request_operation(CREDENTIAL, node.ListCalls(page_token=continuation))
    assert len(calls) == 2


@pytest.mark.parametrize("next_link", ["https://evil.test/api/messaging/logs?page_number=1&page_size=50&page_token=a", "//evil.test/api/messaging/logs?page_number=1&page_size=50&page_token=a", "/api/voice/logs?page_number=1&page_size=50&page_token=a", "/api/messaging/logs?page_number=1&page_size=50&page_token=a&api_token=secret", "/api/messaging/logs?page_number=1&page_number=2&page_size=50&page_token=a", "/api/messaging/logs?page_number=1&page_size=51&page_token=a", "/api/messaging/logs?page_number=1&page_size=50", "/api/messaging/logs?page_number=0&page_size=50&page_token=a", "/api/messaging/logs?page_number=1&page_size=50&page_token=a&created_on=2026-10-05"])
async def test_invalid_continuation_fails_without_following_link(transport, next_link):
    calls, state = transport
    state["handler"] = lambda _: response({"links": {"next": next_link}, "data": [message()]})
    with pytest.raises(ValueError, match="continuation"):
        await node.request_operation(CREDENTIAL, node.ListMessages(created_on="2026-10-06"))
    assert len(calls) == 1


async def test_fabric_projection_rejects_foreign_project_and_discards_nested_configuration(transport):
    calls, state = transport
    resource = {"id": RID, "project_id": CREDENTIAL["project_id"], "display_name": "Fixture", "type": "ai_agent", "ai_agent": {"prompt": "private prompt", "api_key": "private nested secret"}}
    state["handler"] = lambda _: response(resource)
    result = await node.request_operation(CREDENTIAL, node.GetResource(resource_id=RID))
    assert result["data"] == {"id": RID, "display_name": "Fixture", "type": "ai_agent"}
    resource["project_id"] = RID
    with pytest.raises(ValueError, match="project"):
        await node.request_operation(CREDENTIAL, node.GetResource(resource_id=RID))
    assert len(calls) == 2


async def test_sms_201_is_queue_acceptance_and_does_not_retry_or_return_content(transport):
    calls, state = transport
    def send(request):
        assert request.method == "POST" and request.url.path == "/api/messaging/messages"
        assert json.loads(request.content) == {"from": "+15550001111", "to": "+15550002222", "body": "fixture SMS"}
        return response(message(body="fixture SMS", status="queued"), 201)
    state["handler"] = send
    result = await node.request_operation(CREDENTIAL, node.SendSMS(from_number="+15550001111", to_number="+15550002222", message="fixture SMS", confirm_send=True))
    assert result["data"]["queued_request_accepted"] is True and result["data"]["delivery_verified"] is False
    assert "body" not in result["data"] and len(calls) == 1


async def test_redaction_requires_terminal_pre_read_and_exact_empty_body(transport):
    calls, state = transport
    def redact(request):
        if request.method == "GET":
            return response(message())
        assert request.method == "PATCH" and json.loads(request.content) == {"body": ""}
        return response(message(body=""))
    state["handler"] = redact
    result = await node.request_operation(CREDENTIAL, node.RedactMessage(message_id=RID, confirm_redact=True))
    assert result["data"]["body_redaction_confirmed"] is True and len(calls) == 2
    state["handler"] = lambda _: response(message(status="queued"))
    with pytest.raises(ValueError, match="terminal"):
        await node.request_operation(CREDENTIAL, node.RedactMessage(message_id=RID, confirm_redact=True))
    assert len(calls) == 3


async def test_number_rename_preserves_routing_and_verifies_one_readback(transport):
    calls, state = transport
    number = {"id": RID, "number": "+15550001111", "name": "Old", "call_request_url": "https://private.test", "capabilities": ["sms"]}
    def rename(request):
        if request.method == "PUT":
            assert json.loads(request.content) == {"name": "New"}
            number["name"] = "New"
        return response(deepcopy(number))
    state["handler"] = rename
    result = await node.request_operation(CREDENTIAL, node.RenameNumber(phone_number_id=RID, name="New"))
    assert [request.method for request in calls] == ["GET", "PUT", "GET"] and result["readback_verified"] is True
    assert "call_request_url" not in result["data"]


@pytest.mark.parametrize("status", [202, 204, 301, 401, 403, 429, 500])
async def test_unexpected_status_is_safe_and_never_retried(transport, status):
    calls, state = transport
    state["handler"] = lambda _: httpx.Response(status, text=CREDENTIAL["api_token"], headers={"retry-after": "20", "location": "https://private.test"})
    with pytest.raises(node.SignalWireAPIError) as failure:
        await node.request_operation(CREDENTIAL, node.GetProject())
    assert failure.value.http_status == status and failure.value.retry_after == 20 and CREDENTIAL["api_token"] not in str(failure.value)
    assert len(calls) == 1


@pytest.mark.parametrize("content", [b'{"id":"one","id":"two"}', b'{"value":NaN}', b'{"value":1e999}', b'<html>login</html>'])
async def test_malformed_duplicate_or_nonfinite_json_is_loud(transport, content):
    calls, state = transport
    state["handler"] = lambda _: httpx.Response(200, content=content, headers={"content-type": "application/json"})
    with pytest.raises(ValueError, match="JSON"):
        await node.request_operation(CREDENTIAL, node.GetProject())
    assert len(calls) == 1


async def test_response_bound_and_private_override_fail_closed(transport, monkeypatch):
    calls, state = transport
    state["handler"] = lambda _: httpx.Response(200, content=b" " * (node.MAX_BYTES + 1), headers={"content-type": "application/json"})
    with pytest.raises(ValueError, match="2 MiB"):
        await node.request_operation(CREDENTIAL, node.GetProject())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: True)
    with pytest.raises(ValueError, match="private overrides"):
        await node.request_operation(CREDENTIAL, node.GetProject())
    assert len(calls) == 1


@pytest.mark.parametrize("context", [{"project_id": RID}, {"_space_url": "https://foreign.signalwire.com"}, {"api_token": "forged"}, "not context"])
async def test_picker_rejects_forged_scope_before_provider(transport, context):
    calls, _ = transport
    with pytest.raises(ValueError):
        await node.SignalWireNode.load_field_options("phone_number_id", CREDENTIAL, context=context)
    assert calls == []


@pytest.mark.parametrize("confirmation", [False, 1, "true"])
def test_effect_confirmations_are_literal_true(confirmation):
    with pytest.raises(ValueError):
        node.SendSMS(from_number="+15550001111", to_number="+15550002222", message="fixture SMS", confirm_send=confirmation)
    with pytest.raises(ValueError):
        node.RedactMessage(message_id=RID, confirm_redact=confirmation)


def test_raw_family_closed_controls_and_dates():
    for raw in [{"config": {"operation": "get_project"}, "credentials": {key: value for key, value in CREDENTIAL.items() if key != "credential_type"}}, {"config": {"operation": "send_sms", "body": "raw"}, "credentials": CREDENTIAL}]:
        assert node.SignalWireNode.validate_config(raw)["valid"] is False
        with pytest.raises(ValueError):
            node.SignalWireNode.parse_config(raw)
    with pytest.raises(ValueError):
        node.ListCalls(created_on="2026-02-30")
    with pytest.raises(ValueError):
        node.ListCalls(created_on="2026-10-06", created_after="2026-10-05")


async def test_execute_accepts_preparsed_config_without_raw_node_data(transport):
    calls, state = transport
    state["handler"] = lambda _: response({"id": CREDENTIAL["project_id"], "name": "Project"})
    instance = node.SignalWireNode(
        node_id="preparsed", node_type="automation-signalwire", node_data={},
        config=node.SignalWireNodeConfig.model_validate({
            "config": {"operation": "get_project"}, "credentials": CREDENTIAL,
        }),
    )
    result = await instance.execute({})
    assert result["data"] == {"id": CREDENTIAL["project_id"], "name": "Project"}
    assert len(calls) == 1
