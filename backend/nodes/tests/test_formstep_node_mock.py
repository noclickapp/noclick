"""Provider-authored examples and exact Formstep RPC/signature regressions."""
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import formstep_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "formstep"
EXAMPLES = json.loads((FIXTURES / "operations.json").read_text())
EVENTS = json.loads((FIXTURES / "events.json").read_text())
TOKEN = "fs_unit_test_formstep_token"
CREDENTIAL = {"credential_type": "formstep_api_token", "api_token": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="formstep-test", node_type="automation-formstep",
        node_data={"config": config, "credentials": CREDENTIAL})


def mock_http(monkeypatch, respond):
    original = httpx.AsyncClient
    requests = []
    def handler(request):
        requests.append(request)
        return respond(request) if callable(respond) else httpx.Response(200, json=respond)
    monkeypatch.setattr(native.httpx, "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return requests


def config_params(params):
    return {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in params.items()}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.METHODS)
async def test_exact_rpc_contract_and_documented_response(monkeypatch, operation):
    example = EXAMPLES[operation]
    params, response = example["params"], example["response"]
    requests = mock_http(monkeypatch, response)
    result = await node({"operation": operation, **config_params(params)}).execute({})
    request, = requests
    assert request.method == "POST"
    assert str(request.url) == "https://api.formstep.io/api/v1"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {"method": example["method"], "params": params}
    assert result["data"] == response["data"]
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_explicit_nulls_false_and_cursor_are_preserved(monkeypatch):
    requests = mock_http(monkeypatch, {"ok": True, "data": {}})
    await node({"operation": "update_form", "formId": "frm_test", "folderId": None, "emoji": None}).execute({})
    assert json.loads(requests[-1].content)["params"] == {"formId": "frm_test", "folderId": None, "emoji": None}
    await node({"operation": "list_submissions", "formId": "frm_test", "cursor": "next_123", "includeDrafts": False, "limit": 100}).execute({})
    assert json.loads(requests[-1].content)["params"] == {"formId": "frm_test", "cursor": "next_123", "includeDrafts": False, "limit": 100}
    await node({"operation": "list_submissions", "formId": "frm_test", "limit": None, "cursor": None}).execute({})
    assert json.loads(requests[-1].content)["params"] == {"formId": "frm_test"}


@pytest.mark.parametrize("config", [
    {"operation": "update_form", "formId": "frm_test"},
    {"operation": "update_form", "formId": "frm_test", "name": None},
    {"operation": "list_requests"},
    {"operation": "create_request", "formId": "frm_test", "delivery": "email"},
    {"operation": "create_request", "formId": "frm_test", "readonly": '["missing"]'},
    {"operation": "create_request", "formId": "frm_test", "documents": '[{}]'},
    {"operation": "list_forms", "workspaceId": "ws_test", "limit": 101},
])
def test_invalid_parameters_refused(config):
    with pytest.raises((ValidationError, ValueError)):
        native.FormstepNodeConfig.model_validate({"config": config, "credentials": CREDENTIAL})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid token format"}}), (200, {"ok": False, "error": {"code": "CONFLICT", "message": "Request is completed"}}), (200, []), (200, {"ok": True})])
async def test_errors_never_report_success(monkeypatch, status, body):
    mock_http(monkeypatch, lambda request: httpx.Response(status, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["submission_created", "request_completed"])
async def test_webhook_lifecycle_signature_and_agent_turn(monkeypatch, event_type):
    def respond(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "data": {"subscriptionId": "sub_test", "deleted": True}})
    requests = mock_http(monkeypatch, respond)
    config = {"operation": "on_event", "formId": "frm_test", "event_type": event_type}
    registered = await native.FormstepNode._register_external_webhook(
        webhook_url="https://test.hooks.example.test/webhook/test", credential=CREDENTIAL, config=config, node_id="test")
    params = json.loads(requests[0].content)["params"]
    assert params == {"formId": "frm_test", "targetUrl": "https://test.hooks.example.test/webhook/test", "provider": "n8n", "eventType": event_type, "signingSecret": registered["signing_secret"]}
    assert len(registered["signing_secret"]) >= 32
    config.update(registered)
    event = EVENTS[native.EVENT_TYPES[event_type]]["body"]
    body = json.dumps(event).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(registered["signing_secret"].encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"X-Formstep-Signature": f"t={timestamp},sha256={digest}"}
    assert native.FormstepNode.verify_webhook_signature(body, headers, config)
    assert not native.FormstepNode.verify_webhook_signature(body + b" ", headers, config)
    assert not native.FormstepNode.verify_webhook_signature(body, {}, config)
    assert not native.FormstepNode.verify_webhook_signature(body, {"X-Formstep-Signature": "t=bad,sha256=bad"}, config)
    assert not native.FormstepNode.verify_webhook_signature(body, {"X-Formstep-Signature": f"t={timestamp},sha256=é"}, config)
    stale = str(int(time.time()) - 600)
    signature = hmac.new(registered["signing_secret"].encode(), stale.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert not native.FormstepNode.verify_webhook_signature(body, {"X-Formstep-Signature": f"t={stale},sha256={signature}"}, config)
    assert native.FormstepNode.filter_trigger_payload(event, config)
    other_type = "request_completed" if event_type == "submission_created" else "submission_created"
    assert not native.FormstepNode.filter_trigger_payload(EVENTS[native.EVENT_TYPES[other_type]]["body"], config)
    output = native.FormstepNode.resolve_trigger_payload(event, config)
    turn = native.FormstepNode.resolve_agent_event(output)
    assert event["data"]["form"]["id"] in turn["text"]
    assert "alice@example.com" in turn["text"] if event_type == "submission_created" else "ada@acme.com" in turn["text"]
    assert "Answers:" in turn["text"] and turn["conversation_key"]
    await native.FormstepNode._unregister_external_webhook(credential=CREDENTIAL, config=config, node_id="test")
    assert json.loads(requests[-1].content) == {"method": "webhooks.delete", "params": {"subscriptionId": "sub_test"}}
    assert native.FormstepNode.registration_fingerprint_fields(config) == {"formId": "frm_test", "event_type": event_type}


@pytest.mark.asyncio
async def test_manual_trigger_has_no_event(monkeypatch):
    requests = mock_http(monkeypatch, {"ok": True, "data": {}})
    output = await node({"operation": "on_event", "formId": "frm_test"}).execute({})
    assert output["status"] == "no_event" and not requests


def test_manual_credential_default():
    credential = native.FormstepAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == "formstep_api_token"
    assert native.FormstepNode.connection_evidence.operation == "list_workspaces"
