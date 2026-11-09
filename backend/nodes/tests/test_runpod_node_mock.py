"""Wire-level tests use synthetic resources and never contact a Runpod account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import runpod_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-runpod-key-42"
CASES = json.loads((Path(__file__).parent / "fixtures/runpod/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation="list_pods", **config):
    return NodeFactory.create_node(node_id="runpod-test", node_type="automation-runpod",
        node_data={"config": {"operation": operation, **config},
            "credentials": {"credential_type": "runpod_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests, policies = [], []
    original = httpx.AsyncClient
    def send(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        policies.append(kwargs)
        return original(**kwargs, transport=httpx.MockTransport(send))
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests, policies


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_each_operation_has_one_exact_contract_request(monkeypatch, case):
    response = httpx.Response(case["status"], json=case["response"]) if "response" in case else httpx.Response(case["status"])
    requests, policies = transport(monkeypatch, response)
    result = await node(case["operation"], **case["config"]).run({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url) == native.BASE_URL + case["path"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url)
    if "body" in case:
        assert json.loads(request.content) == case["body"]
    else:
        assert request.content == b""
    assert policies[0]["follow_redirects"] is False
    assert policies[0]["trust_env"] is False
    if "response" in case:
        assert result["items" if isinstance(case["response"], list) else "item"] == case["response"]
    else:
        assert result["accepted"] is True


@pytest.mark.asyncio
async def test_filters_preserve_explicit_false(monkeypatch):
    requests, _ = transport(monkeypatch, httpx.Response(200, json=[]))
    await node(compute_type="CPU", desired_status="EXITED", name="Training + test", include_workers=False).run({})
    assert dict(requests[0].url.params) == {"computeType": "CPU", "desiredStatus": "EXITED", "name": "Training + test", "includeWorkers": "false"}


@pytest.mark.asyncio
async def test_update_sends_only_supplied_settings(monkeypatch):
    requests, _ = transport(monkeypatch, httpx.Response(200, json={"id": "pod1"}))
    await node("update_pod", pod_id="pod1", locked=False, volume_in_gb=0, env={}).run({})
    assert json.loads(requests[0].content) == {"locked": False, "volumeInGb": 0, "env": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 422, 429, 500])
async def test_errors_and_redirects_do_not_retry_or_leak_token(monkeypatch, status):
    requests, _ = transport(monkeypatch, httpx.Response(status, json={"error": "Rejected " + TOKEN}, headers={"Location": "https://example.test"}))
    result = await node().run({})
    assert len(requests) == 1 and result["status"] == "error"
    assert result["http_status"] == status and TOKEN not in json.dumps(result)
    assert result["message"] == "Rejected [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, None, "not a list", [1], {"error": "bad"}])
async def test_bad_list_response_does_not_claim_success(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    assert (await node().run({}))["status"] == "error"


@pytest.mark.asyncio
async def test_empty_account_is_valid(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json=[]))
    assert (await node().run({}))["items"] == []


@pytest.mark.asyncio
async def test_write_timeout_is_not_retried(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("secret " + TOKEN, request=request)
    requests, _ = transport(monkeypatch, fail)
    result = await node("stop_pod", pod_id="pod1").run({})
    assert len(requests) == 1 and result["status"] == "error"
    assert "inspect" in result["message"] and TOKEN not in str(result)


@pytest.mark.parametrize("bad", ["../escape", "a/b", "a?foo=bar", "a%2fb", "a#fragment", "https://other.test"])
def test_path_segments_are_validated_before_network(bad):
    with pytest.raises(ValueError):
        native.RunpodNode.parse_config({"config": {"operation": "get_pod", "pod_id": bad}})


def test_manual_key_default_hidden_and_credential_family():
    value = native.RunpodAPIKeyCredential(api_key=TOKEN)
    assert value.credential_type == "runpod_api_key"
    schema = value.model_json_schema()
    assert schema["properties"]["api_key"]["ui:widget"] == "password"
    assert "credential_type" not in schema.get("required", [])
    assert len(native.ROUTES) == 23
    with pytest.raises(ValueError):
        native.RunpodNode.parse_config({"config": {"operation": "list_pods"}, "credentials": {"credential_type": "other_api_key", "api_key": TOKEN}})
    with pytest.raises(ValidationError):
        native.RunpodAPIKeyCredential(api_key="Bearer secret")


@pytest.mark.asyncio
async def test_empty_patch_rejected_before_request(monkeypatch):
    requests, _ = transport(monkeypatch, httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="at least one"):
        await node("update_endpoint", endpoint_id="endpoint1").run({})
    assert requests == []
