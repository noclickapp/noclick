"""Octen wire-contract tests with published examples; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import octen_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/octen/contract_cases.json").read_text())
TOKEN = "octen-test-secret-unique"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="octen-contract", node_type="automation-octen", node_data={
        "config": config, "credentials": {"credential_type": "octen_api_key", "api_key": TOKEN},
    })


def mock_client(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    real_client = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        assert kwargs["timeout"] == 180.0
        return real_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_octen_documented_inputs_response_and_exact_route(monkeypatch, case):
    requests = mock_client(monkeypatch, case["response"])
    result = await node({"operation": case["operation"], **case["config"]}).execute({})
    assert result == {"status": "success", "operation": case["operation"], "data": case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.octen.ai"
    assert request.headers["x-api-key"] == TOKEN and "authorization" not in request.headers
    assert not request.url.query
    if case["method"] == "GET":
        assert request.url.path == case["path"].replace("{task_id}", case["config"]["task_id"])
        assert not request.content
    else:
        assert request.url.path == case["path"]
        body = json.loads(request.content)
        assert "operation" not in body and "api_key" not in body
        for field, value in case["wire"].items():
            assert body[field] == value
        if case["operation"] in {"chat_completion", "answer", "create_search_agent"}:
            assert body["stream"] is False
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [
    (401, {"code": 401, "msg": "Invalid API Key"}),
    (403, {"code": 403, "msg": "Insufficient balance"}),
    (429, {"code": 429, "msg": "Rate limited"}),
    (500, {"code": 500, "msg": "Internal error"}),
    (200, {"code": 401, "msg": "Invalid API Key"}),
    (200, {"error": {"message": "Invalid API Key"}}),
    (302, {"msg": "Redirect refused"}),
])
async def test_octen_errors_are_not_success_or_retried(monkeypatch, status, body):
    requests = mock_client(monkeypatch, lambda r: httpx.Response(status, json=body))
    with pytest.raises(ValueError, match="Octen:"):
        await node({"operation": "search_web", "query": "Octen"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"unrelated": True}])
async def test_octen_unexpected_response_is_not_accepted(monkeypatch, body):
    mock_client(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "search_web", "query": "Octen"}).execute({})


@pytest.mark.asyncio
async def test_octen_html_and_secret_error_redaction(monkeypatch):
    mock_client(monkeypatch, lambda r: httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "search_web", "query": "Octen"}).execute({})
    mock_client(monkeypatch, lambda r: httpx.Response(401, json={"msg": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "search_web", "query": "Octen"}).execute({})
    assert TOKEN not in str(exc.value) and "[redacted]" in str(exc.value)


@pytest.mark.parametrize("task_id", ["..", ".", "a/b", "a?b", "a#b", "a\\b", "a b"])
def test_octen_task_ids_cannot_change_the_route(task_id):
    with pytest.raises(ValidationError):
        native.GetSearchAgent(task_id=task_id)


def test_octen_credentials_hand_connect_and_evidence():
    assert NODE_REGISTRY["automation-octen"] is native.OctenNode
    credential = native.OctenAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "octen_api_key" and credential.api_key == TOKEN
    for key in ["https://octen.ai/platform", "Bearer abc def", "<token>"]:
        with pytest.raises((ValueError, ValidationError)):
            native.OctenAPIKeyCredential(api_key=key)
    evidence = native.OctenNode.connection_evidence
    assert evidence.proves == "reachability" and evidence.operation == "search_web"
    native.WebSearch(**evidence.operation_arguments)


def test_octen_json_fields_bounds_and_embedding_dimension():
    with pytest.raises(ValidationError):
        native.VideoSearch(inputs='[{"type":"image","url":"https://example.com/a.png"}]')
    with pytest.raises(ValidationError):
        native.Extract(urls="[]")
    with pytest.raises(ValidationError):
        native.CreateEmbeddings(input='["text"]', model="octen-embedding-0.6b", dimension=4096)
    with pytest.raises(ValidationError):
        native.ChatCompletion(messages="[]")
    with pytest.raises(ValidationError):
        native.WebSearch(query="x", count=101)
    assert native.WebSearch(query="x", language='["en"]').model_dump()["language"] == ["en"]


@pytest.mark.asyncio
async def test_octen_async_submission_keeps_queued_state_and_does_not_poll(monkeypatch):
    reply = {"request_id": "req-test", "task_id": "agent-test", "status": "queued"}
    requests = mock_client(monkeypatch, reply)
    result = await node({"operation": "create_search_agent", "messages": '[{"role":"user","content":"Research search APIs"}]'}).execute({})
    assert result["data"]["status"] == "queued" and len(requests) == 1


@pytest.mark.asyncio
async def test_octen_multimodal_fusion_uses_only_documented_fields(monkeypatch):
    requests = mock_client(monkeypatch, {"request_id": "req-fusion", "code": 0})
    await node({"operation": "create_vl_embeddings", "input": '{"contents":[{"text":"A tent"},{"image":"https://example.com/tent.jpg"}]}', "enable_fusion": True, "fps": 0.5, "instruct": "Represent this tent", "dimension": 1024}).execute({})
    body = json.loads(requests[0].content)
    assert body["enable_fusion"] is True and body["fps"] == 0.5
    assert body["dimension"] == 1024 and body["instruct"] == "Represent this tent"
    assert "input_type" not in body
