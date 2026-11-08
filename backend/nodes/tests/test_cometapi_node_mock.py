"""CometAPI published-example and credential/error regressions; no live API calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import cometapi_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/cometapi/published_examples.json").read_text())
KEY = "synthetic-cometapi-api-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="cometapi-fixture", node_type="automation-cometapi",
        node_data={"config": config, "credentials": {"credential_type": "cometapi_api_key", "api_key": KEY}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_cometapi_published_example_exact_single_request(monkeypatch, operation):
    example = EXAMPLES[operation]
    requests = transport(monkeypatch, example["response"])
    result = await node(example["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == example["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example["method"]
    assert request.url.host == "api.cometapi.com"
    if operation == "create_message":
        assert request.headers["x-api-key"] == KEY and "authorization" not in request.headers
    else:
        assert request.headers["authorization"] == "Bearer " + KEY
    cfg = example["config"]
    path = example["path"].replace("{id}", cfg.get("task_id", "")).replace("{model}", cfg.get("model", ""))
    assert request.url.path == path
    if request.method == "GET":
        assert request.content == b""
        assert dict(request.url.params) == ({"id": cfg["task_id"]} if operation == "get_flux_result" else {})
    else:
        body = json.loads(request.content)
        expected = {k: v for k, v in cfg.items() if k != "operation"}
        if operation in {"create_chat_completion", "create_message", "create_response"}:
            expected["stream"] = False
        if operation == "create_embeddings":
            expected["encoding_format"] = "float"
        if operation == "create_flux_image":
            expected.pop("model")
            expected["async"] = True
        assert body == expected
        if operation == "create_message":
            assert request.headers["anthropic-version"] == "2023-06-01"
    if operation == "get_current_key":
        assert result["name"] == "production"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 503])
async def test_cometapi_http_errors_redact_without_retry_or_redirect(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text="Rejected " + KEY,
        headers={"location": "https://elsewhere.example/"}))
    result = await node({"operation": "get_current_key"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert KEY not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"code": False, "message": "bad key"}, {"success": False}, {"error": {"message": KEY}}])
async def test_cometapi_error_envelope_is_not_connection_proof(monkeypatch, payload):
    transport(monkeypatch, payload)
    result = await node({"operation": "get_current_key"}).execute({})
    assert result["status"] == "error" and KEY not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"code": True, "data": {}}, {}, [], {"code": True, "data": {"name": ""}}])
async def test_cometapi_incomplete_identity_is_not_connection_proof(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "get_current_key"}).execute({})


@pytest.mark.asyncio
async def test_cometapi_malformed_response_and_timeout_do_not_retry_paid_generation(monkeypatch):
    cfg = EXAMPLES["create_flux_image"]["config"]
    requests = transport(monkeypatch, lambda r: httpx.Response(200, text="<html>unavailable</html>"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await node(cfg).execute({})
    assert len(requests) == 1
    def timeout(request):
        raise httpx.ReadTimeout("secret " + KEY, request=request)
    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="check task history") as exc:
        await node(cfg).execute({})
    assert KEY not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_cometapi_pending_tasks_preserve_state_and_urls(monkeypatch):
    reply = {"id": "task-42", "status": "Pending", "result": None}
    transport(monkeypatch, reply)
    result = await node({"operation": "get_flux_result", "task_id": "task-42"}).execute({})
    assert result["data"] == reply and "completed" not in result
    reply = {"id": "task-42", "status": "Ready", "result": {"sample": "https://cdn.example/image.png"}}
    transport(monkeypatch, reply)
    assert (await node({"operation": "get_flux_result", "task_id": "task-42"}).execute({}))["data"] == reply


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [4, 21])
async def test_cometapi_midjourney_rejection_and_modal_not_generation_success(monkeypatch, code):
    transport(monkeypatch, {"code": code, "description": "Continue manually", "result": "task-42"})
    assert (await node(EXAMPLES["create_midjourney_image"]["config"]).execute({}))["status"] == "error"


@pytest.mark.parametrize("key", ["https://example.com/key", "Bearer secret", "bad\nkey", "bad\x7fkey", "<token>"])
def test_cometapi_invalid_secret(key):
    with pytest.raises(ValidationError):
        native.CometAPIKeyCredential(api_key=key)


def test_cometapi_manual_credential_defaults_and_schema():
    credential = native.CometAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == "cometapi_api_key"
    schema = native.CometAPINode.get_config_schema()
    props = schema["$defs"]["CometAPIKeyCredential"]["properties"]
    assert props["credential_type"]["default"] == "cometapi_api_key"
    assert native.CometAPINode.connection_evidence.identity_operation == "get_current_key"


@pytest.mark.parametrize("task", [".", "..", "bad\nvalue"])
def test_cometapi_task_id_validation(task):
    with pytest.raises(ValidationError):
        native.GetRunwayTask(task_id=task)


def test_cometapi_runway_utf16_limit_and_model_path_validation():
    with pytest.raises(ValidationError):
        native.CreateRunwayVideo(promptText="😀" * 501)
    with pytest.raises(ValidationError):
        native.CreateFluxImage(model="../../evil", prompt="test")


@pytest.mark.asyncio
async def test_cometapi_url_encoding_and_recursive_redaction(monkeypatch):
    requests = transport(monkeypatch, {"id": "task", "nested": [{KEY: KEY}]})
    result = await node({"operation": "get_runway_task", "task_id": "a/b?c#d"}).execute({})
    assert requests[0].url.raw_path == b"/runwayml/v1/tasks/a%2Fb%3Fc%23d"
    assert KEY not in str(result)
