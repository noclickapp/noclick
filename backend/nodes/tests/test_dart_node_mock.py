"""Dart contract transports with synthetic account data; no live writes."""
import json
import hashlib
import hmac
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import dart_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

ID = "Ab12Cd34Ef56"
TOKEN = "synthetic-dart-token-42"
CASES = json.loads((Path(__file__).parent / "fixtures/dart/transport.json").read_text())["cases"]
EVENTS = json.loads((Path(__file__).parent / "fixtures/dart/events.json").read_text())["events"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": "dart_api_token", "api_token": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="dart-fixture", node_type="automation-dart",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body(request) if callable(body) else body)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_dart_provider_method_route_body_and_parser(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert TOKEN not in str(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "app.dartai.com"
    assert request.url.path == case["path"]
    assert dict(request.url.params) == case["params"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN


@pytest.mark.asyncio
async def test_dart_pagination_and_picker_share_one_page(monkeypatch):
    requests = transport(monkeypatch, {"count": 200, "results": [{"id": ID, "title": "Launch"}],
        "next": native.BASE + "/tasks/list?offset=50&limit=50"})
    result = await node({"operation": "list_tasks", "no_defaults": True, "is_completed": False}).execute({})
    assert result["has_more"] is True and result["next_offset"] == 50
    assert len(requests) == 1
    assert requests[0].url.params["is_completed"] == "false"
    assert requests[0].url.params["no_defaults"] == "true"
    choices = await native.DartNode.load_field_options("task_id", credential(), page_token="0", search="Launch + café")
    assert choices == {"options": [{"value": ID, "label": "Launch"}], "next_page_token": "50"}
    assert len(requests) == 2 and requests[-1].url.params["title"] == "Launch + café"


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["https://evil.test/tasks?offset=50", native.BASE + "/docs/list?offset=50",
    native.BASE + "/tasks/list?offset=0", native.BASE + "/tasks/list?offset=x"])
async def test_dart_foreign_or_stalled_continuation_refused_without_following(monkeypatch, link):
    requests = transport(monkeypatch, {"count": 1, "results": [], "next": link})
    with pytest.raises(ValueError):
        await node({"operation": "list_tasks"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_dart_http_failures_keep_provider_message_and_redact_token(monkeypatch, status):
    requests = transport(monkeypatch, {"detail": "Not accepted " + TOKEN}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_me"}).execute({})
    assert str(status) in str(exc.value) and "Not accepted" in str(exc.value)
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"item": []}, {"item": {"id": "other"}}, {"error": "bad"}])
async def test_dart_invalid_resource_or_error_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_task", "task_id": ID}).execute({})


@pytest.mark.asyncio
async def test_dart_update_omission_and_move_without_anchor_refused_locally(monkeypatch):
    requests = transport(monkeypatch, {"item": {"id": ID}})
    for config in [{"operation": "update_task", "task_id": ID},
        {"operation": "update_doc", "doc_id": ID},
        {"operation": "move_task", "task_id": ID, "position": "before"}]:
        with pytest.raises(ValueError):
            await node(config).execute({})
    assert requests == []


def test_dart_manual_credential_default_masking_and_strict_resource_ids():
    shaped = native.DartAPITokenCredential(api_token="  " + TOKEN + "\n")
    assert shaped.credential_type == "dart_api_token" and shaped.api_token == TOKEN
    for token in ["Bearer " + TOKEN, "https://app.dartai.com", "<token>"]:
        with pytest.raises(ValidationError):
            native.DartAPITokenCredential(api_token=token)
    for config in [{"operation": "get_task", "task_id": "../bad"},
        {"operation": "list_comments"}, {"operation": "create_doc"},
        {"operation": "list_tasks", "limit": 0}]:
        with pytest.raises(ConfigValidationError):
            native.DartNode.parse_config({"config": config})


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", native.EVENTS)
async def test_dart_webhook_registration_lifecycle_and_event_subscription(monkeypatch, event_type):
    config = {"operation": "on_event", "event_type": event_type, "webhook_secret": "dsw_fixture_secret"}
    url = "https://fixture.hooks.example.test/webhook/dart"
    requests = transport(monkeypatch, {"item": {"id": ID, "title": "NoClick fixture", "url": url,
        "enabled": True, "eventKinds": [event_type]}})
    extra = await native.DartNode._register_external_webhook(
        webhook_url=url, credential=credential(), config=config, node_id="fixture")
    assert extra == {"external_webhook_id": ID, "signing_secret": "dsw_fixture_secret"}
    assert json.loads(requests[0].content) == {"item": {"title": "NoClick fixture", "url": url,
        "enabled": True, "eventKinds": [event_type]}}
    assert requests[0].method == "POST" and requests[0].url.path.endswith("/webhooks")
    await native.DartNode._unregister_external_webhook(credential=credential(), config={**config, **extra}, node_id="fixture")
    assert requests[1].method == "DELETE" and requests[1].url.path.endswith("/webhooks/" + ID)
    assert all(r.headers["Authorization"] == "Bearer " + TOKEN for r in requests)
    before = native.DartNode.registration_fingerprint_fields(config)
    assert before != native.DartNode.registration_fingerprint_fields({**config, "event_type": "doc.updated" if event_type != "doc.updated" else "task.created"})
    assert before != native.DartNode.registration_fingerprint_fields({**config, "webhook_secret": "rotated"})
    assert "dsw_fixture_secret" not in str(before)


def test_dart_signature_matches_official_sdk_and_fails_closed():
    secret = "dsw_fixture_secret"
    body = json.dumps(EVENTS["task.created"]).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    for config in ({"signing_secret": secret}, {"webhook_secret": secret}):
        assert native.DartNode.verify_webhook_signature(body, {"Dart-Signature": signature}, config)
        assert native.DartNode.verify_webhook_signature(body, {"dart-signature": signature}, config)
        assert not native.DartNode.verify_webhook_signature(body + b" ", {"Dart-Signature": signature}, config)
        assert not native.DartNode.verify_webhook_signature(body, {}, config)
        assert not native.DartNode.verify_webhook_signature(body, {"Dart-Signature": "☃"}, config)
    assert not native.DartNode.verify_webhook_signature(body, {"Dart-Signature": signature}, {})
    assert not native.DartNode.verify_webhook_signature(body, {"Dart-Signature": signature}, {"signing_secret": "wrong"})


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", native.EVENTS)
@pytest.mark.parametrize("sdk_envelope", [False, True])
async def test_dart_contract_events_deliver_content_and_ids_to_workflow_and_agent(event_type, sdk_envelope):
    # Values come from the OpenAPI schemas. The official server documents the
    # alternate data.model envelope: https://github.com/its-dart/dart-tools/blob/3bb2e3514d63c95157bfed8753cc48e183befaf3/dart/server.py
    payload = json.loads(json.dumps(EVENTS[event_type]))
    if sdk_envelope and "model" not in payload["data"]:
        payload["data"] = {"model": payload["data"]}
    config = {"operation": "on_event", "event_type": event_type, "webhook_secret": "dsw_fixture_secret"}
    assert native.DartNode.filter_trigger_payload(payload, config)
    assert not native.DartNode.filter_trigger_payload(payload, {**config, "event_type": "unsupported"})
    assert native.DartNode.resolve_trigger_payload(payload, config) is payload
    assert await node(config).execute(payload) == payload
    event = native.DartNode.resolve_agent_event(payload)
    record = payload["data"].get("model", payload["data"])
    assert record["id"] in event["text"] and record["htmlUrl"] in event["text"]
    assert event_type in event["text"]
    assert (record.get("text") or record.get("description") or record.get("title"))[:200] in event["text"]
    resource = event_type.split(".")[0]
    assert event["conversation_key"] == f"dart:{'task' if resource == 'comment' else resource}:{record['taskId'] if resource == 'comment' else record['id']}"
    assert "dsw_fixture_secret" not in str(event)
    if event_type == "task.status_updated":
        assert payload["data"]["oldStatus"] in event["text"] and payload["data"]["newStatus"] in event["text"]
    if event_type == "task.assignees_updated":
        assert "Previous assignees" in event["text"] and "New assignees" in event["text"]


@pytest.mark.asyncio
async def test_dart_malformed_webhook_registration_and_teardown_ids_are_refused(monkeypatch):
    requests = transport(monkeypatch, {"item": {}})
    config = {"operation": "on_event", "webhook_secret": "dsw_fixture_secret"}
    with pytest.raises(ValueError, match="webhook ID"):
        await native.DartNode._register_external_webhook(webhook_url="https://fixture.hooks.example.test/webhook/dart",
            credential=credential(), config=config, node_id="fixture")
    with pytest.raises(ValueError, match="webhook ID"):
        await native.DartNode._unregister_external_webhook(credential=credential(),
            config={"external_webhook_id": "../../me"}, node_id="fixture")
    assert len(requests) == 1
    assert not native.DartNode.filter_trigger_payload({"type": "task.created", "data": []}, config)
    assert native.DartNode.resolve_agent_event({"type": "task.created", "data": {}}) is None
