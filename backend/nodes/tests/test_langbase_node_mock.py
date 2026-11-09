"""Exercise native Langbase operations at the HTTP boundary; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import langbase_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/langbase/requests.json").read_text())
TOKEN = "synthetic-langbase-api-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="langbase-test", node_type="automation-langbase",
        node_data={"config": config, "credentials": {"credential_type": "langbase_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    client = httpx.AsyncClient
    def handler(req):
        requests.append(req)
        return response
    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        return client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", factory)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_each_operation_has_exactly_one_contract_request(monkeypatch, case):
    response = [] if case["operation"] == "list_pipes" else {"result": "preserved"}
    calls = transport(monkeypatch, httpx.Response(200, json=response))
    result = await node(case["config"]).execute({})
    assert result["data"] == response
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert str(request.url) == native.BASE_URL + case["path"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == case["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], [{"name": "summary-agent", "description": "My pipe", "api_key": "pipe-secret"}]])
async def test_account_evidence_and_pipe_key_redaction(monkeypatch, body):
    calls = transport(monkeypatch, httpx.Response(200, json=body))
    result = await node({"operation": native.LangbaseNode.connection_evidence.operation}).execute({})
    assert len(calls) == 1 and calls[0].method == "GET"
    assert "pipe-secret" not in str(result)
    assert result["data"] == ([] if not body else [{"name": "summary-agent", "description": "My pipe"}])


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": {"message": "Invalid API key"}}), (200, {"success": False, "error": "Request failed"}), (429, {"error": "Rate limit exceeded"})])
async def test_rejections_remain_errors(monkeypatch, status, body):
    transport(monkeypatch, httpx.Response(status, json=body))
    with pytest.raises(ValueError, match="Invalid API key|Request failed|Rate limit exceeded"):
        await node({"operation": "list_pipes"}).execute({})


@pytest.mark.asyncio
async def test_error_echo_redacted_and_redirect_never_followed(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(302, headers={"Location": "https://example.org"}, text=TOKEN))
    with pytest.raises(ValueError) as caught:
        await node({"operation": "list_pipes"}).execute({})
    assert TOKEN not in str(caught.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_escaped_document_name_and_nested_array_body(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(200, json={"success": True}))
    await node({"operation": "delete_document", "memory_name": "knowledge-base", "document_name": "a/b + c.pdf"}).execute({})
    assert calls[0].url.raw_path.endswith(b"/documents/a%2Fb%20%2B%20c.pdf")


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [["chunk one"], {"success": True, "chunks": ["chunk one"]}])
async def test_both_published_chunk_response_shapes_are_preserved(monkeypatch, response):
    transport(monkeypatch, httpx.Response(200, json=response))
    assert (await node({"operation": "chunk_text", "content": "Langbase"}).execute({}))["data"] == response


@pytest.mark.asyncio
async def test_run_nonstreaming_returns_thread_header(monkeypatch):
    body = {"completion": "Hello", "raw": {"choices": []}}
    calls = transport(monkeypatch, httpx.Response(200, json=body, headers={"lb-thread-id": "thread-123"}))
    result = await node({"operation": "run_pipe", "name": "summary-agent", "messages": [{"role": "user", "content": "Hello!"}]}).execute({})
    assert result == {"data": body, "thread_id": "thread-123"}
    assert json.loads(calls[0].content)["stream"] is False


@pytest.mark.parametrize("key", ["https://langbase.com", "Bearer some-key", "bad\nkey"])
def test_manual_credential_rejects_header_and_url(key):
    with pytest.raises(ValidationError):
        native.LangbaseAPIKeyCredential(api_key=key)


def test_manual_type_default_and_config_validation():
    assert native.LangbaseAPIKeyCredential(api_key=TOKEN).credential_type == "langbase_api_key"
    with pytest.raises(ValidationError):
        native.ChunkText(content="hello", chunk_max_length=1024, chunk_overlap=1024)
    with pytest.raises(ValidationError):
        native.CreateMemory(name="kb", chunk_size=1024, chunk_overlap=2048)
    with pytest.raises(ValidationError):
        native.GetThread(thread_id="not-a-uuid")


@pytest.mark.asyncio
async def test_malformed_evidence_is_not_a_working_connection(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"message": "unexpected"}))
    with pytest.raises(ValueError, match="unexpected pipe list"):
        await node({"operation": "list_pipes"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,selector", [
    ("run_pipe", "POST /v1/pipes/run"),
    ("chunk_text", "POST /v1/chunker"),
    ("retry_embeddings", "GET /v1/memory/{memoryName}/documents/{documentName}/embeddings/retry"),
])
async def test_published_responses_that_differ_from_pinned_spec(monkeypatch, operation, selector):
    examples = json.loads((Path(__file__).parent / "fixtures/langbase/documented_responses.json").read_text())
    example = examples[selector]
    assert example["source"].startswith("https://langbase.com/docs/api-reference/")
    transport(monkeypatch, httpx.Response(200, json=example["body"]))
    cfg = next(case["config"] for case in CASES if case["operation"] == operation)
    assert (await node(cfg).execute({}))["data"] == example["body"]


def test_optional_pipe_thread_can_be_unset():
    cfg = native.RunPipe(name="summary-agent", messages=[{"role": "user", "content": "Hello!"}], thread_id=None)
    assert cfg.thread_id is None
