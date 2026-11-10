"""Exercise Hubflo's real factory and HTTP seam with provider examples.

Every action is checked for its route, body and parsing; webhook tests cover
registration, teardown, signatures and the documented delivery-to-agent path.
"""
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import hubflo_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "hubflo"
OPERATIONS = json.loads((FIXTURES / "operations.json").read_text())
EVENTS = json.loads((FIXTURES / "events.json").read_text())
CREDENTIAL = {"credential_type": "hubflo_api_key", "api_key": "synthetic-hubflo-key"}
CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=CREDENTIAL):
    return NodeFactory.create_node(node_id="hubflo-test", node_type="automation-hubflo",
        node_data={"config": config, "credentials": credential})


def transport(monkeypatch, respond):
    requests = []
    def handler(request):
        requests.append(request)
        return respond(request)
    monkeypatch.setattr(native.httpx, "AsyncClient", lambda **kw: CLIENT(transport=httpx.MockTransport(handler), **kw))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("name", OPERATIONS)
async def test_each_action_documented_method_route_body_and_response(monkeypatch, name):
    example = OPERATIONS[name]
    config = {**example["config"], **example["request_examples"]}
    requests = transport(monkeypatch, lambda req: httpx.Response(example["status"], json=example["response"],
                                                               headers={"X-Next-Page": "2"}))
    result = await node(config).execute({})
    assert result["data"] == example["response"]
    req = requests[0]
    assert len(requests) == 1 and req.method == example["method"]
    assert req.url.host == "app.hubflo.com"
    assert req.url.path == example["path"].replace("{id}", config.get("id", ""))
    assert req.headers["Authorization"] == "Bearer " + CREDENTIAL["api_key"]
    if example["method"] in {"POST", "PATCH"}:
        sent = json.loads(req.content)
        assert set(sent) <= set(example["body"])
        assert all(sent[k] == v for k, v in example["request_examples"].items() if k in example["body"])
        assert "id" not in sent
    else:
        assert not req.content
        assert set(req.url.params) <= set(example["query"])
    if name.startswith("list_"):
        assert dict(req.url.params)["page"] == "1" and result["next_page"] == 2


@pytest.mark.asyncio
async def test_filter_page_and_false_values_preserved(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=[]))
    result = await node({"operation": "list_tasks", "page": 3, "per_page": 100, "completed": False}).execute({})
    assert dict(requests[0].url.params) == {"page": "3", "per_page": "100", "completed": "false"}
    assert result["next_page"] is None
    requests.clear()
    await node({"operation": "update_task", "id": "task-one", "name": "Task name", "completed": False, "tags": []}).execute({})
    assert json.loads(requests[0].content) == {"name": "Task name", "completed": False, "tags": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_provider_error_and_redirect_are_not_success(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={"message": "Invalid API token"},
                                                              headers={"Location": "https://other.example/"}))
    with pytest.raises(ValueError, match=f"Hubflo API {status}: Invalid API token"):
        await node({"operation": "get_organization"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event", native.EVENT_OPERATIONS.items())
async def test_trigger_registration_teardown_signature_and_documented_agent_turn(monkeypatch, operation, event):
    def respond(req):
        if req.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(201, json={"id": "hook-one", "secret": "synthetic-signing-secret"})
    requests = transport(monkeypatch, respond)
    config = {"operation": operation}
    registered = await native.HubfloNode._register_external_webhook(
        webhook_url="https://test.hooks.example.test", credential=CREDENTIAL, config=config, node_id="test")
    assert json.loads(requests[0].content) == {"url": "https://test.hooks.example.test", "event_names": [event]}
    config.update(registered)
    payload = EVENTS[event]["body"]
    body = json.dumps(payload).encode()
    signature = hmac.new(registered["signing_secret"].encode(), body, hashlib.sha256).hexdigest()
    assert native.HubfloNode.verify_webhook_signature(body, {"X-Hubflo-Signature": signature}, config)
    assert native.HubfloNode.verify_webhook_signature(body, {"x-hubflo-signature": signature}, config)
    for invalid in [body + b" ", b"{}"]:
        assert not native.HubfloNode.verify_webhook_signature(invalid, {"X-Hubflo-Signature": signature}, config)
    for headers in [{}, {"X-Hubflo-Signature": "a" * 64}, {"X-Hubflo-Signature": "é" * 64}]:
        assert not native.HubfloNode.verify_webhook_signature(body, headers, config)
    assert not native.HubfloNode.verify_webhook_signature(body, {"X-Hubflo-Signature": signature}, {})
    turn = native.HubfloNode.resolve_agent_event(native.HubfloNode.resolve_trigger_payload(payload, config))
    assert payload["webhook_delivery_id"] in turn["text"]
    assert payload["data"] in turn["text"] and turn["conversation_key"] == payload["webhook_delivery_id"]
    assert (await node({"operation": operation}).execute({}))["status"] == "no_event"
    await native.HubfloNode._unregister_external_webhook(credential=CREDENTIAL, config=config, node_id="test")
    assert requests[-1].method == "DELETE" and requests[-1].url.path == "/api/v2/webhooks/hook-one"


@pytest.mark.asyncio
async def test_registration_fails_without_provider_signing_secret(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(201, json={"id": "hook-one"}))
    with pytest.raises(ValueError, match="signing secret"):
        await native.HubfloNode._register_external_webhook(webhook_url="https://test.hooks.example.test",
            credential=CREDENTIAL, config={"operation": "on_contact_created"}, node_id="test")


@pytest.mark.asyncio
async def test_path_escape_is_rejected_before_request(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={}))
    for identifier in ["..", "a/b", "foo?token=bad", "a\\b"]:
        with pytest.raises(ValueError, match="resource ID"):
            await node({"operation": "get_contact", "id": identifier}).execute({})
    assert not requests


def test_manual_credential_defaults_and_schema():
    key = native.HubfloAPIKeyCredential.model_validate({"api_key": "  synthetic-key  "})
    assert key.credential_type == "hubflo_api_key" and key.api_key == "synthetic-key"
    for value in ["", "Bearer key", "https://app.hubflo.com", "<token>"]:
        with pytest.raises((ValueError, ValidationError)):
            native.HubfloAPIKeyCredential(api_key=value)
    with pytest.raises((ValueError, ValidationError)):
        node({"operation": "list_contacts", "per_page": 101})
    assert native.HubfloNode.connection_evidence.operation == "get_organization"


@pytest.mark.asyncio
async def test_explicit_null_removes_recurrence_but_omission_does_not(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={}))
    await node({"operation": "update_task", "id": "task-one", "name": "Task", "recurrence_type": None}).execute({})
    assert json.loads(requests[-1].content)["recurrence_type"] is None
    await node({"operation": "update_task", "id": "task-one", "name": "Task"}).execute({})
    assert "recurrence_type" not in json.loads(requests[-1].content)
