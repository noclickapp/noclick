"""Native operation dispatch and provider-documented webhook examples, without live credentials."""
import base64
import hashlib
import hmac
import json
import time
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import openlayer_node as ol
from nodes.core.run_op import run_node_operation

FIXTURES = Path(__file__).parent / "fixtures/openlayer"
EVENTS = json.loads((FIXTURES / "events.json").read_text())
REGISTRATION = json.loads((FIXTURES / "webhook_registration.json").read_text())["body"]
ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
AUTH = {"credential_type": "openlayer_api_key", "api_key": "fixture-openlayer-key"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    async def send(request):
        calls.append(request)
        assert request.url.host == "api.openlayer.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, data = replies.pop(0)
        return httpx.Response(status, json=data) if data is not None else httpx.Response(status)
    original = httpx.AsyncClient
    monkeypatch.setattr(ol.httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(send)))
    return calls, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-openlayer", operation=operation, arguments=arguments or {},
        credential_data=deepcopy(AUTH), user_id="00000000-0000-4000-8000-000000000001")


# Fixed expected routes catch path/method mistakes independently of the node's operation table.
CASES = [
    ("list_projects", {"page": 2, "per_page": 10, "task_type": "llm-base"}, "GET", "/projects", {"page": "2", "perPage": "10", "taskType": "llm-base"}, None),
    ("create_project", {"name": "My Project", "task_type": "llm-base"}, "POST", "/projects", {}, {"name": "My Project", "taskType": "llm-base"}),
    ("update_project", {"project_id": ID, "description": "Changed"}, "PATCH", f"/projects/{ID}", {}, {"description": "Changed"}),
    ("delete_project", {"project_id": ID}, "DELETE", f"/projects/{ID}", {}, None),
    ("list_commits", {"project_id": ID}, "GET", f"/projects/{ID}/versions", {"page": "1", "perPage": "25"}, None),
    ("create_commit", {"project_id": ID, "storage_uri": "s3://...", "commit_message": "Updated the prompt."}, "POST", f"/projects/{ID}/versions", {}, {"storageUri": "s3://...", "commit": {"message": "Updated the prompt."}}),
    ("get_commit", {"project_version_id": ID}, "GET", f"/versions/{ID}", {}, None),
    ("list_commit_test_results", {"project_version_id": ID, "result_status": "failing"}, "GET", f"/versions/{ID}/results", {"page": "1", "perPage": "25", "status": "failing"}, None),
    ("list_inference_pipelines", {"project_id": ID, "name": "production"}, "GET", f"/projects/{ID}/inference-pipelines", {"page": "1", "perPage": "25", "name": "production"}, None),
    ("create_inference_pipeline", {"project_id": ID, "name": "production"}, "POST", f"/projects/{ID}/inference-pipelines", {}, {"name": "production", "description": ""}),
    ("get_inference_pipeline", {"inference_pipeline_id": ID}, "GET", f"/inference-pipelines/{ID}", {}, None),
    ("update_inference_pipeline", {"inference_pipeline_id": ID, "name": "production"}, "PUT", f"/inference-pipelines/{ID}", {}, {"name": "production"}),
    ("delete_inference_pipeline", {"inference_pipeline_id": ID}, "DELETE", f"/inference-pipelines/{ID}", {}, None),
    ("publish_inferences", {"inference_pipeline_id": ID, "rows_json": '[{"user_query":"what is the meaning of life?","output":"42"}]', "stream_config_json": '{"inputVariableNames":["user_query"],"outputColumnName":"output"}'}, "POST", f"/inference-pipelines/{ID}/data-stream", {}, {"rows": [{"user_query": "what is the meaning of life?", "output": "42"}], "config": {"inputVariableNames": ["user_query"], "outputColumnName": "output"}}),
    ("list_rows", {"inference_pipeline_id": ID, "filter_json": '{}', "sort_column": "timestamp", "ascending": False}, "POST", f"/inference-pipelines/{ID}/rows", {"page": "1", "perPage": "25", "sortColumn": "timestamp", "asc": "false"}, {}),
    ("get_row", {"inference_pipeline_id": ID, "inference_id": "my-row"}, "GET", f"/inference-pipelines/{ID}/rows/my-row", {}, None),
    ("update_row", {"inference_pipeline_id": ID, "inference_id": "my-row", "row_json": '{"output":"42"}'}, "PUT", f"/inference-pipelines/{ID}/rows", {"inferenceId": "my-row"}, {"row": {"output": "42"}}),
    ("delete_row", {"inference_pipeline_id": ID, "inference_id": "my-row"}, "DELETE", f"/inference-pipelines/{ID}/rows/my-row", {}, None),
    ("list_tests", {"project_id": ID, "include_archived": False}, "GET", f"/projects/{ID}/tests", {"page": "1", "perPage": "25", "includeArchived": "false"}, None),
    ("evaluate_test", {"test_id": ID, "start_timestamp": 1699920000, "end_timestamp": 1700006400}, "POST", f"/tests/{ID}/evaluate", {}, {"startTimestamp": 1699920000, "endTimestamp": 1700006400, "overwriteResults": False}),
    ("list_test_results", {"test_id": ID, "start_timestamp": 1699920000}, "GET", f"/tests/{ID}/results", {"page": "1", "perPage": "25", "startTimestamp": "1699920000"}, None),
    ("list_pipeline_test_results", {"inference_pipeline_id": ID}, "GET", f"/inference-pipelines/{ID}/results", {"page": "1", "perPage": "25"}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,params,body", CASES)
async def test_openlayer_native_actions(transport, operation, arguments, method, path, params, body):
    calls, replies = transport
    expected = {"items": [{"id": ID, "name": "My Project"}], "provider_field": {"preserved": True}}
    replies.append((200, expected))
    result = await run(operation, arguments)
    assert result == expected
    assert len(calls) == 1 and not replies
    request = calls[0]
    assert request.method == method
    assert request.url.path == "/v1" + path
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
async def test_openlayer_empty_delete_and_async_result(transport):
    _, replies = transport
    replies.append((204, None))
    assert (await run("delete_project", {"project_id": ID}))["success"] is True
    replies.append((202, {"message": "Resource is not ready yet."}))
    assert await run("list_test_results", {"test_id": ID}) == {"message": "Resource is not ready yet."}


@pytest.mark.asyncio
async def test_openlayer_key_rejection_keeps_provider_reason(transport):
    _, replies = transport
    replies.append((401, {"message": "Expired API key"}))
    with pytest.raises(ValueError, match="401: Expired API key"):
        await run("list_projects")


@pytest.mark.parametrize("operation,arguments", [
    ("get_commit", {"project_version_id": "../../other"}),
    ("get_row", {"inference_pipeline_id": ID, "inference_id": ".."}),
    ("list_projects", {"per_page": 101}),
    ("create_project", {"name": "x", "task_type": "invented"}),
    ("publish_inferences", {"inference_pipeline_id": ID, "rows_json": "{}", "stream_config_json": "{}"}),
    ("update_row", {"inference_pipeline_id": ID, "inference_id": "row", "row_json": "{}"}),
    ("evaluate_test", {"test_id": ID, "start_timestamp": 2, "end_timestamp": 1}),
])
def test_openlayer_rejects_invalid_inputs(operation, arguments):
    with pytest.raises(ValidationError):
        ol.OpenlayerNodeConfig.model_validate({"config": {"operation": operation, **arguments}, "credentials": AUTH})


@pytest.mark.parametrize("value", ["Bearer abc", "https://api.openlayer.com", "abc\nheader", "abc\x7f", 123, ""])
def test_openlayer_key_shape(value):
    with pytest.raises(ValueError):
        ol.OpenlayerAPIKeyCredential(api_key=value)


def signature(body, *, secret=REGISTRATION["secret"], timestamp=None):
    timestamp = str(timestamp if timestamp is not None else int(time.time()))
    headers = {"webhook-id": "fixture-message", "webhook-timestamp": timestamp}
    message = b"fixture-message." + timestamp.encode() + b"." + body
    digest = hmac.new(base64.b64decode(secret.removeprefix("whsec_")), message, hashlib.sha256).digest()
    headers["webhook-signature"] = "v1," + base64.b64encode(digest).decode()
    return headers


@pytest.mark.asyncio
@pytest.mark.parametrize("event", list(EVENTS))
async def test_openlayer_docs_webhook_lifecycle_and_agent_event(transport, event):
    calls, replies = transport
    replies.extend([(201, REGISTRATION), (204, None)])
    config = {"operation": "on_event", "workspace_id": ID, "event_type": event}
    registered = await ol.OpenlayerNode._register_external_webhook(webhook_url="https://example.com/webhooks/openlayer",
        credential=AUTH, config=config, node_id="fixture")
    assert registered == {"external_webhook_id": REGISTRATION["id"], "signing_secret": REGISTRATION["secret"]}
    config.update(registered)
    assert calls[0].url.path == f"/v1/workspaces/{ID}/webhooks"
    assert json.loads(calls[0].content) == {"url": "https://example.com/webhooks/openlayer", "description": "NoClick fixture", "eventTypes": [event]}
    payload = deepcopy(EVENTS[event]["body"])
    raw = json.dumps(payload).encode()
    headers = signature(raw)
    assert ol.OpenlayerNode.verify_webhook_signature(raw, headers, config)
    assert not ol.OpenlayerNode.verify_webhook_signature(raw + b" ", headers, config)
    assert ol.OpenlayerNode.filter_trigger_payload(payload, config)
    output = ol.OpenlayerNode.resolve_trigger_payload(payload, config)
    agent = ol.OpenlayerNode.resolve_agent_event(output)
    assert event in agent["text"] and ID in agent["text"]
    assert agent["conversation_key"] == ID
    assert "fixture-openlayer-key" not in str(agent)
    if event == "tests.result.updated":
        assert "1 failing" in agent["text"] and "list_commit_test_results" in agent["text"]
    await ol.OpenlayerNode._unregister_external_webhook(credential=AUTH, config=config, node_id="fixture")
    assert calls[1].method == "DELETE"
    assert calls[1].url.path == f"/v1/workspaces/{ID}/webhooks/{REGISTRATION['id']}"
    assert not replies


def test_openlayer_signature_rotation_staleness_and_missing_secret():
    raw = b'{"type":"test.created"}'
    config = {"signing_secret": REGISTRATION["secret"]}
    headers = signature(raw)
    headers["webhook-signature"] = "v1,bad v2,ignored " + headers["webhook-signature"]
    assert ol.OpenlayerNode.verify_webhook_signature(raw, {k.upper(): v for k,v in headers.items()}, config)
    assert not ol.OpenlayerNode.verify_webhook_signature(raw, signature(raw, timestamp=int(time.time()) - 301), config)
    assert not ol.OpenlayerNode.verify_webhook_signature(raw, signature(raw, timestamp=int(time.time()) + 301), config)
    assert not ol.OpenlayerNode.verify_webhook_signature(raw, headers, {})
    assert not ol.OpenlayerNode.verify_webhook_signature(raw, headers, {"signing_secret": "invalid!"})
    assert not ol.OpenlayerNode.verify_webhook_signature(raw, {}, config)
    assert not ol.OpenlayerNode.verify_webhook_signature(raw, {**headers, "webhook-signature": "v1,\u00e9"}, config)
    assert not ol.OpenlayerNode.filter_trigger_payload(EVENTS["test.created"]["body"], {"event_type": "test.deleted"})


@pytest.mark.asyncio
async def test_openlayer_registration_requires_id_and_secret(transport):
    _, replies = transport
    replies.append((201, {"id": ID}))
    with pytest.raises(ValueError, match="signing secret"):
        await ol.OpenlayerNode._register_external_webhook(webhook_url="https://example.com/webhooks/openlayer",
            credential=AUTH, config={"workspace_id": ID}, node_id="fixture")


def test_openlayer_manual_key_default_and_schema_contract():
    assert ol.OpenlayerAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == "openlayer_api_key"
    schema = ol.OpenlayerNode.get_config_schema()
    assert schema and len(ol.OPERATIONS) == 22
    assert ol.OpenlayerNode.connection_evidence.operation == "list_projects"
    assert ol.OpenlayerNode.registration_fingerprint_fields({"workspace_id": ID, "event_type": "test.created"}) == {"workspace_id": ID, "event_type": "test.created"}
