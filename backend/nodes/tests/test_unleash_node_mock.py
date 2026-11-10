"""Execute the native factory against HTTP fixtures, with real SSRF validation."""
import asyncio
import json
import socket
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import unleash_node as unleash
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "unleash_token", "instance_url": "https://example.app.unleash-hosted.com", "api_token": "user:fixture-only-not-live"}
P = {"project_id": "default"}
F = {**P, "feature_name": "checkout"}
E = {**F, "environment": "production"}
S = {**E, "strategy_id": "strategy-1"}
PREFIX = "/api/admin/projects/default/features/checkout"
ENV = PREFIX + "/environments/production"
CASES = [
    ("list_projects", {}, "GET", "/api/admin/projects", None, 200),
    ("get_project", P, "GET", "/api/admin/projects/default/overview", None, 200),
    ("list_features", P, "GET", "/api/admin/projects/default/features", None, 200),
    ("get_feature", F, "GET", PREFIX, None, 200),
    ("create_feature", {**P, "name": "checkout", "type": "release", "impressionData": False}, "POST", "/api/admin/projects/default/features", {"name": "checkout", "type": "release", "impressionData": False}, 200),
    ("update_feature", {**F, "stale": False, "description": "Updated"}, "PUT", PREFIX, {"stale": False, "description": "Updated"}, 200),
    ("archive_feature", F, "DELETE", PREFIX, None, 202),
    ("get_feature_environment", E, "GET", ENV, None, 200),
    ("enable_feature", E, "POST", ENV + "/on", None, 200),
    ("disable_feature", E, "POST", ENV + "/off", None, 200),
    ("list_strategies", E, "GET", ENV + "/strategies", None, 200),
    ("get_strategy", S, "GET", ENV + "/strategies/strategy-1", None, 200),
    ("create_strategy", {**E, "name": "flexibleRollout", "parameters": {"rollout": "50", "stickiness": "default", "groupId": "checkout"}}, "POST", ENV + "/strategies", {"name": "flexibleRollout", "parameters": {"rollout": "50", "stickiness": "default", "groupId": "checkout"}}, 200),
    ("update_strategy", {**S, "disabled": True, "constraints": [{"contextName": "userId", "operator": "IN", "values": ["123"], "caseInsensitive": False}]}, "PUT", ENV + "/strategies/strategy-1", {"disabled": True, "constraints": [{"contextName": "userId", "operator": "IN", "values": ["123"], "caseInsensitive": False}]}, 200),
    ("delete_strategy", S, "DELETE", ENV + "/strategies/strategy-1", None, 200),
    ("list_variants", E, "GET", ENV + "/variants", None, 200),
    ("list_environments", {}, "GET", "/api/admin/environments", None, 200),
    ("get_environment", {"environment": "production"}, "GET", "/api/admin/environments/production", None, 200),
    ("list_segments", {}, "GET", "/api/admin/segments", None, 200),
    ("get_segment", {"segment_id": 1}, "GET", "/api/admin/segments/1", None, 200),
    ("create_segment", {"name": "Beta", "constraints": [], "project": "default"}, "POST", "/api/admin/segments", {"name": "Beta", "constraints": [], "project": "default"}, 201),
    ("update_segment", {"segment_id": 1, "name": "Beta", "constraints": []}, "PUT", "/api/admin/segments/1", {"name": "Beta", "constraints": []}, 204),
    ("delete_segment", {"segment_id": 1}, "DELETE", "/api/admin/segments/1", None, 204),
]


@pytest.fixture
async def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]))

    async def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body) if body is not None else httpx.Response(code)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(unleash, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, arguments=None, auth=None):
    return NodeFactory.create_node(node_id="unleash-test", node_type="automation-unleash",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": auth or AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body,code", CASES)
async def test_all_operations(transport, operation, arguments, method, path, body, code):
    requests, replies = transport
    empty = operation in {"enable_feature", "disable_feature", "archive_feature", "delete_strategy", "update_segment", "delete_segment"}
    payload = None if empty else {"name": "checkout", "enabled": False}
    if operation == "list_strategies":
        payload = [{"id": "strategy-1", "name": "flexibleRollout", "parameters": {"rollout": "50"}}]
    replies.append((code, payload))
    result = await node(operation, arguments).execute({})
    assert result == {"status": "success", "operation": operation, "http_status": code, "data": payload}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "example.app.unleash-hosted.com"
    assert request.headers["Authorization"] == AUTH["api_token"]
    assert AUTH["api_token"] not in str(request.url)
    assert dict(request.url.params) == {}
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
async def test_project_filter_and_self_hosted_prefix(transport):
    requests, replies = transport
    replies.append((200, {"version": 1, "projects": []}))
    await node("list_projects", {"archived": False}, {**AUTH, "instance_url": "https://flags.example.com/unleash/"}).execute({})
    assert str(requests[0].url) == "https://flags.example.com/unleash/api/admin/projects?archived=false"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 404, 429, 500, 302])
async def test_rejections_are_errors_and_not_retried(transport, code):
    requests, replies = transport
    replies.append((code, {"message": "Not authorized"}))
    result = await node("list_projects").execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert "Not authorized" in result["error"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_rejection_redacts_token(transport):
    transport[1].append((401, {"message": AUTH["api_token"]}))
    assert AUTH["api_token"] not in str(await node("list_projects").execute({}))


@pytest.mark.asyncio
@pytest.mark.parametrize("field,context,body,expected", [
    ("project_id", {}, {"projects": [{"id": "default", "name": "Default"}]}, {"value": "default", "label": "Default"}),
    ("feature_name", P, {"features": [{"name": "checkout"}]}, {"value": "checkout", "label": "checkout"}),
    ("environment", {}, {"environments": [{"name": "production"}]}, {"value": "production", "label": "production"}),
    ("segment_id", {}, {"segments": [{"id": 1, "name": "Beta"}]}, {"value": "1", "label": "Beta"}),
])
async def test_resource_choices(transport, field, context, body, expected):
    transport[1].append((200, body))
    result = await unleash.UnleashNode.load_field_options(field, AUTH, context)
    assert result == {"options": [expected], "next_page_token": None}


@pytest.mark.asyncio
async def test_choice_errors_and_search(transport):
    transport[1].append((200, {"projects": [{"id": "default", "name": "Default"}]}))
    assert (await unleash.UnleashNode.load_field_options("project_id", AUTH, search="other"))["options"] == []
    transport[1].append((401, {"message": "Access denied"}))
    with pytest.raises(ValueError, match="Access denied"):
        await unleash.UnleashNode.load_field_options("project_id", AUTH)
    transport[1].append((200, {}))
    with pytest.raises(ValueError, match="invalid choice list"):
        await unleash.UnleashNode.load_field_options("project_id", AUTH)


@pytest.mark.parametrize("url", ["http://flags.example.com", "https://user:pass@flags.example.com", "https://flags.example.com/api", "https://flags.example.com?token=x", "https://flags.example.com/#/admin", "https://flags.example.com/../other"])
def test_unsafe_instance_urls_refused(url):
    with pytest.raises(ValidationError):
        unleash.UnleashTokenCredential.model_validate({**AUTH, "instance_url": url})


@pytest.mark.parametrize("token", ["Bearer secret", "https://example.com", "token\r\nInjected: yes", "<token>"])
def test_invalid_tokens_refused(token):
    with pytest.raises(ValidationError):
        unleash.UnleashTokenCredential.model_validate({**AUTH, "api_token": token})


def test_manual_credential_default_and_dot_traversal():
    credential = unleash.UnleashTokenCredential.model_validate({k: v for k, v in AUTH.items() if k != "credential_type"})
    assert credential.credential_type == "unleash_token"
    with pytest.raises(ValidationError):
        unleash.UnleashGetFeatureConfig(project_id="..", feature_name="checkout")


@pytest.mark.asyncio
async def test_private_hosts_blocked_before_token_is_sent(transport):
    with pytest.raises(ssrf.SSRFError):
        await node("list_projects", auth={**AUTH, "instance_url": "https://127.0.0.1"}).execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_empty_update_never_sends(transport):
    with pytest.raises(ValueError, match="at least one field"):
        await node("update_feature", F).execute({})
    assert transport[0] == []


# Provider examples retain their source URLs alongside each verbatim payload.
WEBHOOK_EVENTS = json.loads((Path(__file__).parent / "fixtures/unleash/webhook-events.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event_type", unleash.TRIGGER_EVENTS.items())
async def test_webhook_registration_delivery_and_teardown(transport, operation, event_type):
    requests, replies = transport
    config = {"operation": operation, "project_id": "test-project", "environment": None}
    replies.append((200, {"id": 7, "provider": "webhook", "description": None, "enabled": True,
        "parameters": {}, "events": [event_type]}))
    registered = await unleash.UnleashNode._register_external_webhook(
        webhook_url="https://fixture.hooks.example.test/webhook/secret", credential=AUTH, config=config, node_id="flag")
    assert registered == {"external_webhook_id": "7"}
    assert requests[0].method == "POST" and requests[0].url.path == "/api/admin/addons"
    assert json.loads(requests[0].content) == {"provider": "webhook", "enabled": True,
        "description": "NoClick flag", "events": [event_type],
        "parameters": {"url": "https://fixture.hooks.example.test/webhook/secret", "contentType": "application/json"},
        "projects": ["test-project"], "environments": []}
    payload = WEBHOOK_EVENTS[event_type]["body"]
    config["project_id"] = payload["project"]
    assert unleash.UnleashNode.verify_webhook_signature(json.dumps(payload).encode(), {}, config)
    assert unleash.UnleashNode.filter_trigger_payload(payload, config)
    output = unleash.UnleashNode.resolve_trigger_payload(payload, config)
    assert output == payload
    event = unleash.UnleashNode.resolve_agent_event(output)
    assert payload["createdBy"] in event["text"] and payload["featureName"] in event["text"]
    assert payload["project"] in event["text"] and str(payload["id"]) in event["text"]
    assert "get_feature project_id=" in event["text"]
    assert event["conversation_key"] == payload["project"] + "/" + payload["featureName"]
    assert json.dumps(payload["data"], ensure_ascii=False) in event["text"]
    replies.append((200, None))
    await unleash.UnleashNode._unregister_external_webhook(credential=AUTH,
        config={**config, **registered}, node_id="flag")
    assert requests[1].method == "DELETE" and requests[1].url.path == "/api/admin/addons/7"


@pytest.mark.parametrize("operation,event_type", unleash.TRIGGER_EVENTS.items())
def test_webhook_filters_and_batch_payloads(operation, event_type):
    payload = WEBHOOK_EVENTS[event_type]["body"]
    config = {"operation": operation}
    for changed in ({"project_id": "wrong-project"}, {"environment": "wrong-environment"}, {"operation": "list_projects"}):
        assert not unleash.UnleashNode.filter_trigger_payload(payload, {**config, **changed})
    assert not unleash.UnleashNode.filter_trigger_payload({}, config)
    assert not unleash.UnleashNode.filter_trigger_payload({"events": None}, config)
    other = {"type": "unrelated", "id": 999}
    batch = {"version": 1, "events": [payload, other, payload]}
    assert unleash.UnleashNode.resolve_trigger_payload(batch, config) == {"events": [payload, payload]}
    assert unleash.UnleashNode.resolve_agent_event({"events": [payload, payload]})["text"].count("To act:") == 2
    assert unleash.UnleashNode.resolve_trigger_payload(other, config)["status"] == "no_event"


def test_documented_webhook_batch_and_registration_scope():
    payload = WEBHOOK_EVENTS["feature-created-batch"]["body"]
    config = {"operation": "on_feature_created", "project_id": "default", "environment": "development"}
    assert unleash.UnleashNode.filter_trigger_payload(payload, config)
    assert unleash.UnleashNode.resolve_trigger_payload(payload, config) == payload["events"][0]
    assert unleash.UnleashNode.registration_fingerprint_fields(config) == {"project_id": "default", "environment": "development"}
    parsed = unleash.UnleashOnFeatureCreatedConfig(project_id=None, environment=None, external_webhook_id="7")
    assert parsed.external_webhook_id == "7"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", unleash.TRIGGER_EVENTS)
async def test_manual_trigger_run_has_no_event_and_no_http(transport, operation):
    output = await node(operation).execute({"other-step": {"id": "not-a-delivery"}})
    assert output["status"] == "no_event"
    assert transport[0] == []


@pytest.mark.asyncio
async def test_webhook_failures_are_visible_and_not_retried(transport):
    transport[1].append((403, {"message": AUTH["api_token"]}))
    with pytest.raises(ValueError, match="403") as error:
        await unleash.UnleashNode._register_external_webhook(webhook_url="https://fixture.hooks.example.test/webhook/x",
            credential=AUTH, config={"operation": "on_feature_created"}, node_id="flag")
    assert AUTH["api_token"] not in str(error.value)
    assert len(transport[0]) == 1
    transport[1].append((200, {}))
    with pytest.raises(ValueError, match="integration ID"):
        await unleash.UnleashNode._register_external_webhook(webhook_url="https://fixture.hooks.example.test/webhook/x",
            credential=AUTH, config={"operation": "on_feature_created"}, node_id="flag")
    transport[1].append((404, None))
    await unleash.UnleashNode._unregister_external_webhook(credential=AUTH, config={"external_webhook_id": "7"}, node_id="flag")
    with pytest.raises(ValueError, match="Connect Unleash"):
        await unleash.UnleashNode._unregister_external_webhook(credential=None, config={"external_webhook_id": "7"}, node_id="flag")
