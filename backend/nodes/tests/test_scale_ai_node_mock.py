"""Actual factory and operation runner with synthetic HTTP contract fixtures."""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import scale_ai_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": native.TYPE, "api_key": "synthetic-scale-key"}
USER = "11111111-1111-4111-8111-111111111111"
CASES = json.loads((Path(__file__).parent / "fixtures/scale-ai/operations.json").read_text())["cases"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def receive(request):
        calls.append(request)
        assert request.url.host == "api.scale.com" and request.url.scheme == "https"
        assert not request.url.userinfo and AUTH["api_key"] not in str(request.url)
        assert base64.b64decode(request.headers["Authorization"].split()[1]) == (AUTH["api_key"] + ":").encode()
        return responses.pop(0)

    client = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: client(**kw, transport=httpx.MockTransport(receive)))
    return calls, responses


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-scale-ai", operation=operation,
                                    arguments=arguments or {}, credential_data=AUTH, user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_scale_ai_operations_send_exact_published_request(transport, case):
    calls, replies = transport
    replies.append(httpx.Response(200, json=case["response"]))
    result = await run(case["operation"], case["arguments"])
    assert result["success"] is True and result["data"] == case["response"]
    assert len(calls) == 1 and not replies
    request = calls[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert dict(request.url.params) == case["params"]
    assert (json.loads(request.content) if request.content else None) == case["body"]


def test_scale_ai_manual_credential_has_default_tag_and_visible_required_field():
    shaped, errors, resolved = shape_credential(native.TYPE, {"api_key": "  synthetic-scale-key\n"})
    assert not errors and shaped == {"api_key": AUTH["api_key"]}
    assert resolved[1] is native.ScaleAiAPIKeyCredential
    assert resolved[1].model_validate(shaped).model_dump() == AUTH


@pytest.mark.parametrize("bad", ["https://dashboard.scale.com/apikeys", "<token>", "user:password", "key\nheader", "key with spaces", "key—unicode", 42])
def test_scale_ai_bad_keys_refused(bad):
    with pytest.raises(ValueError):
        native.ScaleAiAPIKeyCredential(api_key=bad)


@pytest.mark.parametrize("bad", ["..", "../files", "x/y", "x?y", "https://foreign.example", "x%2Fy", "x\n"])
def test_scale_ai_resource_paths_cannot_change_the_destination(bad):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="scale-ai-test", node_type="automation-scale-ai",
                                node_data={"config": {"operation": "get_file", "file_id": bad}, "credentials": AUTH})


def test_scale_ai_foreign_credential_cannot_be_retagged():
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="scale-ai-test", node_type="automation-scale-ai", node_data={
            "config": {"operation": "list_files"}, "credentials": {**AUTH, "credential_type": "foreign_key"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_scale_ai_error_no_retry_or_redirect_and_key_redacted(transport, status):
    calls, replies = transport
    replies.append(httpx.Response(status, text="Rejected " + AUTH["api_key"], headers={"Location": "https://foreign.example"}))
    result = await run("list_files")
    assert result["success"] is False and result["status_code"] == status
    assert "[redacted]" in result["error"] and AUTH["api_key"] not in json.dumps(result)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"model_endpoints": {}}, {"model_endpoints": ["bad"]}, {"model_endpoints": [{}]}])
async def test_scale_ai_malformed_success_cannot_prove_connection(transport, payload):
    transport[1].append(httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await run("list_model_endpoints")


@pytest.mark.asyncio
async def test_scale_ai_account_specific_endpoint_evidence(transport):
    row = {"id": "endpoint-1", "name": "my-classifier"}
    transport[1].append(httpx.Response(200, json={"model_endpoints": [row]}))
    evidence = await collect_evidence(node_type="automation-scale-ai", credential_data=AUTH, user_id=USER)
    assert evidence.reachable is True
    assert [s.label for s in evidence.samples] == ["my-classifier"]


@pytest.mark.asyncio
async def test_scale_ai_rejected_key_is_failed_evidence(transport):
    transport[1].append(httpx.Response(401, json={"detail": "Invalid API key"}))
    evidence = await collect_evidence(node_type="automation-scale-ai", credential_data=AUTH, user_id=USER)
    assert evidence.reachable is False and "Invalid API key" in evidence.error


@pytest.mark.parametrize("model,values", [
    (native.UpdateModelEndpoint, {"model_endpoint_id": "endpoint-1"}),
    (native.UpdateModelEndpoint, {"model_endpoint_id": "endpoint-1", "min_workers": 3, "max_workers": 1}),
    (native.CreateSyncTask, {"model_endpoint_id": "endpoint-1", "args": {}, "timeout_seconds": 0}),
    (native.CreateFineTune, {"model": "classifier"}),
])
def test_scale_ai_required_inputs_and_compute_bounds(model, values):
    with pytest.raises(ValueError):
        model.model_validate(values)


def test_scale_ai_sync_endpoint_requires_a_running_worker():
    values = next(c["arguments"] for c in CASES if c["operation"] == "create_model_endpoint")
    with pytest.raises(ValueError, match="at least one"):
        native.CreateModelEndpoint.model_validate({**values, "endpoint_type": "sync", "min_workers": 0})
    assert native.CreateModelEndpoint.model_validate({**values, "endpoint_type": "sync", "min_workers": 1}).min_workers == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,payload", [("delete_file", {"deleted": False}), ("cancel_fine_tune", {"success": False})])
async def test_scale_ai_negative_write_ack_is_not_success(transport, operation, payload):
    transport[1].append(httpx.Response(200, json=payload))
    args = {"file_id": "file-1"} if operation == "delete_file" else {"fine_tune_id": "tune-1"}
    if operation == "cancel_fine_tune":
        assert (await run(operation, args))["success"] is False
    else:
        with pytest.raises(ValueError):
            await run(operation, args)
