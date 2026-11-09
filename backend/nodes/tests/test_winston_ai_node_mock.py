"""Winston's published request bodies, non-billable MCP evidence and failures.

https://docs.gowinston.ai/api-reference/openapi.json
https://docs.gowinston.ai/api-reference/mcp-server
All calls are mocked: no real key, account or credits.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import winston_ai_node as native
from nodes.core.registry import NodeFactory

TOKEN = "winston-synthetic-secret-123456"
TEXT = "A useful article about science and technology. " * 15
CREDENTIAL = {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}
MCP = json.loads((Path(__file__).parent / "fixtures/winston-ai/mcp_tools.json").read_text())["body"]
CASES = [
    ("detect_ai_text", {"text": TEXT, "sentences": False}, "/v2/ai-content-detection", {"language": "auto", "version": "latest"}),
    ("detect_ai_file", {"file_url": "https://example.com/document.pdf"}, "/v2/ai-content-detection", {"language": "auto", "version": "latest", "sentences": True}),
    ("detect_ai_website", {"website": "https://example.com"}, "/v2/ai-content-detection", {"language": "auto", "version": "latest", "sentences": True}),
    ("check_plagiarism_text", {"text": TEXT, "excluded_sources": ["example.com"]}, "/v2/plagiarism", {"language": "auto", "country": "us"}),
    ("check_plagiarism_file", {"file_url": "https://example.com/document.pdf"}, "/v2/plagiarism", {"language": "auto", "country": "us", "excluded_sources": []}),
    ("check_plagiarism_website", {"website": "https://example.com"}, "/v2/plagiarism", {"language": "auto", "country": "us", "excluded_sources": []}),
    ("fact_check_text", {"text": TEXT}, "/v2/fact-checker", {"language": "auto"}),
    ("detect_ai_image_url", {"url": "https://example.com/image.jpg"}, "/v2/image-detection", {"version": "latest"}),
    ("detect_ai_image_data", {"image": "data:image/png;base64,aGVsbG8="}, "/v2/image-detection", {"version": "latest"}),
    ("analyze_image_forensics", {"image_url": "https://example.com/image.png"}, "/v2/advanced-image-detection", {}),
    ("compare_texts", {"first_text": "Hello world", "second_text": "Hello earth"}, "/v2/text-compare", {}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="winston-test", node_type="automation-winston-ai", node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, *, status=200, sse=False):
    requests = []
    def reply(request):
        requests.append(request)
        if sse:
            return httpx.Response(status, text="event: message\ndata: " + json.dumps(body) + "\n\n", headers={"Content-Type": "text/event-stream"})
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,path,defaults", CASES, ids=[c[0] for c in CASES])
async def test_winston_ai_exact_single_request_and_lossless_response(monkeypatch, operation, fields, path, defaults):
    response = {"status": 200, "score": 73.25, "credits_remaining": 500, "sentences": [{"text": "A sentence", "score": 42}], "new_field": {"value": True}}
    requests = transport(monkeypatch, response)
    assert await node({"operation": operation, **fields}).execute({}) == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST" and request.url == native.BASE + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    expected = {**defaults, **fields}
    if "file_url" in expected:
        expected["file"] = expected.pop("file_url")
    assert json.loads(request.content) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("sse", [False, True])
async def test_winston_ai_connection_check_only_lists_tools(monkeypatch, sse):
    requests = transport(monkeypatch, MCP, sse=sse)
    result = await node({"operation": "check_connection"}).execute({})
    assert result == {"key_accepted": True, "tools": [{"name": "ai-text-detection"}], "account_identity_verified": False}
    assert len(requests) == 1 and requests[0].url == native.BASE + "/mcp/v1"
    assert json.loads(requests[0].content) == {"jsonrpc": "2.0", "method": "tools/list", "id": 1}


@pytest.mark.asyncio
async def test_winston_ai_connection_evidence_seam(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, MCP)
    result = await collect_evidence(node_type="automation-winston-ai", user_id="winston-test", credential_data=CREDENTIAL)
    assert result.reachable is True and native.WinstonAINode.connection_evidence.proves == "reachability"
    assert len(requests) == 1 and json.loads(requests[0].content)["method"] == "tools/list"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 403, 429, 500, 302])
async def test_winston_ai_error_status_no_retry_and_no_secret(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Unauthorized", "description": "Rejected key " + TOKEN}, status=status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "compare_texts", "first_text": "one", "second_text": "two"}).execute({})
    assert TOKEN not in str(exc.value) and str(status) in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}, {"jsonrpc": "2.0", "id": 9, "result": {"tools": [{"name": "ai-text-detection"}]}}, {"error": {"code": -32603, "message": "failed"}}])
async def test_winston_ai_malformed_probe_never_proves_key(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "check_connection"}).execute({})


@pytest.mark.asyncio
async def test_winston_ai_error_envelope_200_is_failure(monkeypatch):
    transport(monkeypatch, {"error": "failed", "description": TOKEN})
    with pytest.raises(ValueError) as exc:
        await node({"operation": "compare_texts", "first_text": "one", "second_text": "two"}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize("value", ["https://example.com/token", "Bearer abc def", "has\nnewline", "", "<token>"])
def test_winston_ai_bad_manual_keys(value):
    with pytest.raises((ValidationError, ValueError)):
        native.WinstonAIApiKeyCredential(api_key=value)


def test_winston_ai_manual_key_default_and_trim():
    credential = native.WinstonAIApiKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == native.CREDENTIAL_TYPE and credential.api_key == TOKEN


@pytest.mark.parametrize("url", ["http://localhost/a", "http://127.0.0.1/a", "https://user:pass@example.com/a", "file:///tmp/x", "https://example.com/#fragment"])
def test_winston_ai_public_input_urls(url):
    with pytest.raises(ValidationError):
        native.ImageURLConfig(url=url)


@pytest.mark.parametrize("config", [
    {"operation": "detect_ai_text", "text": "short"},
    {"operation": "check_plagiarism_text", "text": "short"},
    {"operation": "fact_check_text", "text": "x" * 10001},
    {"operation": "compare_texts", "first_text": "x" * 120001, "second_text": "other"},
])
def test_winston_ai_provider_text_bounds(config):
    assert native.WinstonAINode.validate_config({"config": config, "credentials": CREDENTIAL})["valid"] is False


@pytest.mark.asyncio
async def test_winston_ai_connection_rejection_blocks_manual_save(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, {"error": "Unauthorized", "description": "Missing or invalid authentication token"}, status=401)
    result = await collect_evidence(node_type="automation-winston-ai", user_id="winston-test", credential_data=CREDENTIAL)
    assert result.reachable is False
    assert "Missing or invalid authentication token" in result.error
    assert len(requests) == 1
