"""Contract-shaped dispatch, account connection and documented webhook deliveries."""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.manifestly_node import ManifestlyAPIKeyCredential, ManifestlyNode, ManifestlyNodeConfig

FIXTURES = Path(__file__).parent / "fixtures" / "manifestly"
AUTH = {"credential_type": "manifestly_api_key", "api_key": "mf_fixture_key", "webhook_signing_secret": "fixture-hook-secret"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    original = httpx.AsyncClient

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.manifest.ly"
        assert request.headers["authorization"] == "Bearer mf_fixture_key"
        assert AUTH["api_key"] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


def node(config):
    return ManifestlyNode(node_id="fixture", node_type="automation-manifestly", node_data={"config": config},
        config=ManifestlyNodeConfig.model_validate({"config": config, "credentials": AUTH}), sio=Mock())


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", [
    ({"operation": "create_run", "checklist_id": 42, "title": "Q1 Onboarding"}, "POST", "/runs", {"run": {"checklist_id": 42, "title": "Q1 Onboarding"}}),
    ({"operation": "update_run", "run_id": 101, "title": "Updated Run Title", "state": "completed"}, "PUT", "/runs/101", {"run": {"title": "Updated Run Title", "state": "completed"}}),
    ({"operation": "change_run_step_state", "run_id": 101, "run_step_id": 555, "action": "complete"}, "POST", "/runs/101/run_steps/555", {"action": "complete"}),
    ({"operation": "assign_run_step", "run_id": 101, "run_step_id": 555, "assignee_membership_id": 42}, "POST", "/runs/101/run_steps/555/assign", {"assignee_membership_id": 42}),
    ({"operation": "assign_run_step", "run_id": 101, "run_step_id": 555}, "POST", "/runs/101/run_steps/555/assign", {}),
    ({"operation": "create_comment", "run_id": 101, "run_step_id": 555, "comment": "Verified with the vendor."}, "POST", "/runs/101/run_steps/555/comments", {"comment": "Verified with the vendor."}),
    ({"operation": "update_run_step_field", "run_id": 101, "run_step_id": 502, "field_id": 101, "value": "Jane Doe"}, "PUT", "/runs/101/run_steps/502/fields/101", {"value": "Jane Doe"}),
    ({"operation": "close_run", "run_id": 101}, "DELETE", "/runs/101", None),
])
async def test_manifestly_write_requests(transport, config, method, path, body):
    requests, replies = transport
    replies.append((204, None))
    instance = node(config)
    instance.emit = AsyncMock()
    assert await instance.execute({}) == {"acknowledged": True}
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/api/v2" + path
    assert (json.loads(request.content) if request.content else None) == body
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_manifestly_connection_and_pagination(transport):
    requests, replies = transport
    response = json.loads((FIXTURES / "responses.json").read_text())["responses"]["GET /workflows"]
    replies.append((200, response))
    instance = node({"operation": "list_workflows", "page": 2, "per_page": 20, "search": "Onboarding"})
    instance.emit = AsyncMock()
    result = await instance.execute({})
    assert result == response
    assert result["workflows"][0]["title"] == "Sample Workflow"
    assert dict(requests[0].url.params) == {"page": "2", "per_page": "20", "search": "Onboarding"}
    assert ManifestlyNode.connection_evidence.operation == "list_workflows"


@pytest.mark.asyncio
async def test_manifestly_errors_preserve_rejection_and_redact_secrets(transport):
    _, replies = transport
    replies.append((401, {"error": "Invalid API key mf_fixture_key"}))
    with pytest.raises(ValueError, match="Invalid API key") as err:
        await ManifestlyNode._request(AUTH, "GET", "/workflows")
    assert "mf_fixture_key" not in str(err.value)
    assert "401" in str(err.value)


@pytest.mark.parametrize("operation,event,hookable", [
    ("on_run_event", "started", "checklist"), ("on_run_event", "completed", "run"),
    ("on_run_event", "late", "checklist"), ("on_step_event", "step_completed", "step"),
    ("on_step_event", "step_late", "run_step"), ("on_step_event", "step_skipped", "step"),
])
@pytest.mark.asyncio
async def test_manifestly_documented_webhook_lifecycle(transport, operation, event, hookable):
    requests, replies = transport
    # The contract publishes a Webhook response schema, not a saved example.
    response = {"webhook": {"id": 7, "target_url": "https://example.com/hook", "event": event,
        "created_at": "2026-11-10T00:00:00Z", "updated_at": "2026-11-10T00:00:00Z"}}
    replies.extend([(201, response), (204, None)])
    config = {"operation": operation, "event": event, "hookable": hookable, "hookable_id": 42}
    extra = await ManifestlyNode._register_external_webhook(webhook_url="https://example.com/hook", credential=AUTH, config=config, node_id="fixture")
    config.update(extra)
    assert extra["signing_secret"] == AUTH["webhook_signing_secret"]
    assert json.loads(requests[0].content) == {"webhook": {"url": "https://example.com/hook", "event": event, "signature_version": 2}, "hookable": hookable, "hookable_id": 42}
    payload = json.loads((FIXTURES / "webhook.json").read_text())["body"]
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(AUTH["webhook_signing_secret"].encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-Manifestly-Signature": signature, "X-Manifestly-Event": event}
    assert ManifestlyNode.verify_webhook_signature(body, headers, config)
    assert not ManifestlyNode.verify_webhook_signature(body + b" ", headers, config)
    assert not ManifestlyNode.verify_webhook_signature(body, {}, config)
    assert not ManifestlyNode.verify_webhook_signature(body, headers, {})
    payload["_webhook"] = {"headers": headers}
    assert ManifestlyNode.filter_trigger_payload(payload, config)
    assert not ManifestlyNode.filter_trigger_payload(payload, {**config, "event": "other"})
    result = ManifestlyNode.resolve_trigger_payload(payload, config)
    agent = ManifestlyNode.resolve_agent_event(result)
    assert agent["conversation_key"] == "43682"
    for expected in ("John Smith", "Philip Crawford", "30845220", "Enter in HRIS", "http://app.manifest.ly/runs/43682/edit"):
        assert expected in agent["text"]
    await ManifestlyNode._unregister_external_webhook(credential=AUTH, config=config, node_id="fixture")
    assert requests[1].method == "DELETE"
    assert requests[1].url.path == "/api/v2/webhooks/" + extra["external_webhook_id"]


@pytest.mark.asyncio
async def test_manifestly_trigger_requires_separate_secret(transport):
    with pytest.raises(ValueError, match="signing secret"):
        await ManifestlyNode._register_external_webhook(webhook_url="https://example.com/hook", credential={"api_key": AUTH["api_key"]},
            config={"operation": "on_run_event", "hookable_id": 42}, node_id="fixture")
    assert not transport[0]


@pytest.mark.parametrize("config", [
    {"operation": "get_run", "run_id": -1},
    {"operation": "list_runs", "per_page": 101},
    {"operation": "get_run_step", "run_id": 1, "run_step_id": 2, "per_page": 51},
    {"operation": "on_step_event", "event": "completed", "hookable_id": 42},
    {"operation": "on_run_event", "hookable": "run_step", "hookable_id": 42},
])
def test_manifestly_invalid_config(config):
    with pytest.raises(ValidationError):
        ManifestlyNodeConfig.model_validate({"config": config})


def test_manifestly_manual_credential():
    assert ManifestlyAPIKeyCredential(api_key=" mf_fixture_key ").credential_type == "manifestly_api_key"
    assert ManifestlyAPIKeyCredential(api_key=" mf_fixture_key ").api_key == "mf_fixture_key"
    for invalid in ("https://example.com/key", "<token>", "Bearer value"):
        with pytest.raises(ValidationError):
            ManifestlyAPIKeyCredential(api_key=invalid)
