"""Exercise W&B requests through the native node factory with a mock transport.

Synthetic fixtures verify route, body, pagination, credential and failure behavior
without signing in or sending data to a real W&B project.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import weights_and_biases_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-wandb-key-12345"
CREDENTIAL = {"credential_type": "weights_and_biases_api_key", "api_key": TOKEN, "project_id": "entity/project"}
CASES = json.loads((Path(__file__).parent / "fixtures/weights-and-biases/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="wandb-fixture", node_type="automation-weights-and-biases",
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def transport(monkeypatch, reply):
    calls = []
    def respond(request):
        calls.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.parametrize("case", CASES, ids=lambda c: "weights-and-biases:" + c["config"]["operation"])
async def test_weights_and_biases_one_exact_request_per_operation(monkeypatch, case):
    calls = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == case["response"]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST"
    assert str(request.url) == "https://trace.wandb.ai" + case["path"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert json.loads(request.content) == case["body"]
    if case["config"]["operation"] in native.WRITES:
        assert result["write_acknowledged"] is True


async def test_weights_and_biases_jsonl_and_offset(monkeypatch):
    rows = [{"id": "call-one"}, {"id": "call-two"}]
    calls = transport(monkeypatch, lambda _: httpx.Response(200,
        content="\n".join(json.dumps(r) for r in rows) + "\n", headers={"content-type": "application/jsonl"}))
    result = await node({"operation": "list_calls", "limit": 2, "offset": 10}).execute({})
    assert result["items"] == rows and result["next_offset"] == 12
    assert result["has_more_possible"] is True and len(calls) == 1
    assert calls[0].headers["accept"] == "application/jsonl"
    transport(monkeypatch, {"objs": []})
    result = await node({"operation": "list_objects"}).execute({})
    assert result["items"] == [] and result["next_offset"] is None


async def test_weights_and_biases_json_null_object_value_is_sent(monkeypatch):
    calls = transport(monkeypatch, {"digest": "version"})
    await node({"operation": "create_object", "object_id": "null-value", "val": None}).execute({})
    assert json.loads(calls[0].content)["obj"]["val"] is None


async def test_weights_and_biases_filters_keep_native_contract_names(monkeypatch):
    calls = transport(monkeypatch, {"objs": []})
    await node({"operation": "list_objects", "filter": {"latest_only": True, "base_object_classes": ["Dataset"]}, "offset": 20}).execute({})
    body = json.loads(calls[0].content)
    assert body["filter"] == {"latest_only": True, "base_object_classes": ["Dataset"]}
    assert body["offset"] == 20
    calls = transport(monkeypatch, {"count": 3})
    await node({"operation": "get_call_stats", "filter": {"trace_roots_only": True}}).execute({})
    assert json.loads(calls[0].content)["filter"] == {"trace_roots_only": True}


async def test_weights_and_biases_default_evidence_lists_selected_project(monkeypatch):
    calls = transport(monkeypatch, {"objs": [{"object_id": "my-model", "digest": "version"}]})
    from nodes.core.connection_evidence import collect_evidence
    result = await collect_evidence(node_type="automation-weights-and-biases", user_id="fixture-user", credential_data=CREDENTIAL)
    assert result.reachable is True
    assert any("my-model" in sample.label for sample in result.samples)
    assert len(calls) == 1 and json.loads(calls[0].content)["project_id"] == "entity/project"


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_weights_and_biases_provider_rejections_and_no_retry(monkeypatch, status):
    calls = transport(monkeypatch, lambda _: httpx.Response(status, json={"detail": "Denied " + TOKEN}))
    result = await node({"operation": "list_objects"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Denied" in result["message"] and TOKEN not in str(result)
    assert len(calls) == 1


@pytest.mark.parametrize("reply", [{}, {"objs": "wrong"}, {"error": "denied"}])
async def test_weights_and_biases_bad_envelopes_are_not_account_proof(monkeypatch, reply):
    transport(monkeypatch, reply)
    with pytest.raises(ValueError, match="could not be parsed"):
        await node({"operation": "list_objects"}).execute({})


async def test_weights_and_biases_transport_failure_does_not_repeat_write(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("unconfirmed", request=request)
    calls = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="inspect the project"):
        await node({"operation": "create_object", "object_id": "model", "val": {}}).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize("key", ["https://wandb.ai/authorize", "<your-key>", "Bearer key", "é", None])
def test_weights_and_biases_bad_keys_fail_before_request(key):
    with pytest.raises(ValidationError):
        native.WeightsAndBiasesAPIKeyCredential.model_validate({**CREDENTIAL, "api_key": key})


@pytest.mark.parametrize("project", ["https://wandb.ai/entity/project", "project", "entity/project/other", "entity/..", "entity/pro ject"])
def test_weights_and_biases_project_is_a_person_supplied_identifier(project):
    with pytest.raises(ValidationError):
        native.WeightsAndBiasesAPIKeyCredential.model_validate({**CREDENTIAL, "project_id": project})


def test_weights_and_biases_manual_credential_default_and_operation_boundaries():
    credential = native.WeightsAndBiasesAPIKeyCredential.model_validate({"api_key": " " + TOKEN + "\n", "project_id": " entity/project "})
    assert credential.model_dump() == CREDENTIAL
    assert native.WeightsAndBiasesNode.connection_evidence.operation == "list_objects"
    for config in [{"operation": "delete_object", "object_id": "x"},
                   {"operation": "delete_calls", "call_ids": []},
                   {"operation": "list_objects", "limit": 1001},
                   {"operation": "list_objects", "url": "https://evil.test"}]:
        with pytest.raises(ValidationError):
            native.WeightsAndBiasesConfig.model_validate({"config": config, "credentials": CREDENTIAL})
