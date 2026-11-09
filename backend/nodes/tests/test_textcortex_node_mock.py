"""Offline factory tests against TextCortex's published response examples."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import textcortex_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-textcortex-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/textcortex/published_examples.json").read_text())["responses"]
CASES = [
    ({"operation": "list_files", "q": "policy", "page": 2, "limit": 10}, "GET /api-platform/files", {"q": "policy", "page": "2", "limit": "10"}),
    ({"operation": "get_file", "file_id": "file-example"}, "GET /api-platform/files/{file_id}", {}),
    ({"operation": "delete_file", "file_id": "file-example"}, "DELETE /api-platform/files/{file_id}", None),
    ({"operation": "list_knowledge_bases"}, "GET /api-platform/knowledge-bases", {"page": "0", "limit": "20"}),
    ({"operation": "search_knowledge_base_files", "q": "cancellation"}, "GET /api-platform/knowledge-bases/files/search", {"page": "0", "limit": "20", "q": "cancellation"}),
    ({"operation": "list_knowledge_base_files", "kb_id": "kb-example"}, "GET /api-platform/knowledge-bases/{kb_id}/files", {"page": "0", "limit": "20"}),
    ({"operation": "insert_knowledge_base_file", "kb_id": "kb-example", "file_id": "file-example"}, "POST /api-platform/knowledge-bases/{kb_id}/files", {"file_id": "file-example"}),
    ({"operation": "query_knowledge_base", "kb_id": "kb-example", "query": "What are the cancellation terms?", "top_k": 3}, "POST /api-platform/knowledge-bases/{kb_id}/query", {"query": "What are the cancellation terms?", "top_k": 3, "verbatim": False}),
    ({"operation": "get_balance"}, "GET /balance", {}),
    ({"operation": "get_capabilities"}, "GET /capabilities", {}),
    ({"operation": "list_models"}, "GET /models", {}),
    ({"operation": "get_model", "model_id": "gpt-6-luna"}, "GET /models/{model_id}", {}),
    ({"operation": "create_chat_completion", "model": "gpt-6-luna", "prompt": "Write a short product tagline.", "max_tokens": 128}, "POST /chat/completions", {"model": "gpt-6-luna", "messages": [{"role": "user", "content": "Write a short product tagline."}], "max_tokens": 128, "stream": False}),
    ({"operation": "create_response", "model": "gpt-6-luna", "input": "Write a short product tagline."}, "POST /responses", {"model": "gpt-6-luna", "input": "Write a short product tagline.", "store": False, "stream": False}),
    ({"operation": "generate_image", "model": "gpt-image-2.5", "prompt": "A watercolor mountain lake", "size": "1024x1024"}, "POST /images/generations", {"model": "gpt-image-2.5", "prompt": "A watercolor mountain lake", "size": "1024x1024", "n": 1, "response_format": "url"}),
    ({"operation": "search_web", "query": "TextCortex API documentation", "website": "textcortex.com"}, "POST /web/search", {"query": "TextCortex API documentation", "website": "textcortex.com", "limit": 5}),
]

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config, credential=None):
    return NodeFactory.create_node(node_id="fixture", node_type="automation-textcortex", node_data={
        "config": config, "credentials": credential or {"credential_type": "textcortex_api_key", "api_key": TOKEN}})

def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize("config,route,expected", CASES, ids=[x[0]["operation"] for x in CASES])
async def test_textcortex_each_action_one_request_published_response(monkeypatch, config, route, expected):
    example = EXAMPLES[route]
    requests = transport(monkeypatch, example["body"], example["status"])
    result = await node(config).execute({})
    assert result["success"] is True and result["data"] == example["body"]
    assert len(requests) == 1
    req = requests[0]
    method, path = route.split(" ")
    for name in ("file_id", "kb_id", "model_id"):
        if name in config: path = path.replace("{" + name + "}", config[name])
    assert req.method == method and str(req.url.copy_with(query=None)) == native.BASE + path
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    if method == "GET": assert dict(req.url.params) == expected
    elif method == "POST": assert json.loads(req.content) == expected
    else: assert not req.content

@pytest.mark.asyncio
async def test_textcortex_pages_use_has_more_even_if_total_estimated(monkeypatch):
    body = json.loads(json.dumps(EXAMPLES["GET /api-platform/files"]["body"]))
    body["pagination"].update(has_more=True, total=0, total_is_exact=False)
    transport(monkeypatch, body)
    result = await node({"operation": "list_files", "page": 4}).execute({})
    assert result["next_page"] == 5 and result["has_more"] is True
    body["pagination"]["has_more"] = False
    transport(monkeypatch, body)
    result = await node({"operation": "list_files", "page": 5}).execute({})
    assert result["next_page"] is None

@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": {"message": "Invalid " + TOKEN}}), (403, {"detail": "Forbidden"}), (429, {"message": "Slow down"}), (502, {"error": "Upstream failed"})])
async def test_textcortex_errors_redacted_and_never_retried(monkeypatch, status, body):
    requests = transport(monkeypatch, body, status)
    result = await node({"operation": "get_balance"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert TOKEN not in str(result) and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"error": {"message": "Rejected"}}, {"status": "fail"}])
async def test_textcortex_malformed_success_not_claimed(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError): await node({"operation": "get_balance"}).execute({})

@pytest.mark.parametrize("config", [
    {"operation": "get_file", "file_id": "../balance"},
    {"operation": "get_model", "model_id": "a?admin=true"},
    {"operation": "query_knowledge_base", "kb_id": "kb-example", "query": "x", "top_k": 21},
    {"operation": "search_knowledge_base_files", "q": "x", "limit": 26},
    {"operation": "search_web", "query": "x", "limit": 11},
])
def test_textcortex_invalid_inputs_fail_before_request(config):
    with pytest.raises(ValueError): node(config)

@pytest.mark.parametrize("key", ["Bearer abc", "https://example.com/key", "<token>"])
def test_textcortex_manual_key_rejects_headers_urls_placeholders(key):
    with pytest.raises(ValidationError): native.TextcortexAPIKeyCredential(api_key=key)

def test_textcortex_manual_credential_default_and_connection_read():
    assert native.TextcortexAPIKeyCredential(api_key=TOKEN).credential_type == "textcortex_api_key"
    assert native.TextcortexNode.connection_evidence.operation == "list_files"
    assert len(native.ROUTES) == 16
