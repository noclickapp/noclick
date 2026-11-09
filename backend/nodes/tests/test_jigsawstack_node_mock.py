"""Offline native node execution against exact provider-published response examples."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import jigsawstack_node as js
from nodes.core.registry import NodeFactory
from utils import ssrf

KEY = "jigsawstack-fixture-secret"
AUTH = {"credential_type": "jigsawstack_api_key", "api_key": KEY}
ID = "0073d008-da9b-4c27-90a8-0240f3ecd4f5"
CASES = [
    ({"operation": "analyze_sentiment", "text": "I love this product!"}, "POST", "/ai/sentiment"),
    ({"operation": "generate_sql", "prompt": "Find all transactions with amounts exceeding $10,000, sorted by transaction date", "database": "postgresql"}, "POST", "/ai/sql"),
    ({"operation": "check_profanity", "text": "This is a sample text that might contain inappropriate language."}, "POST", "/validate/profanity"),
    ({"operation": "check_spam", "text": "Congratulations! You've won a free iPhone! Click here to claim now!"}, "POST", "/validate/spam_check"),
    ({"operation": "check_spelling", "text": "This sentense has a speling mistake."}, "POST", "/validate/spell_check"),
    ({"operation": "translate_text", "text": "Hello", "target_language": "zh"}, "POST", "/ai/translate"),
    ({"operation": "create_embedding", "text": "Caption: Secluded Tiki Bar on a serene lake, perfect for a refreshing drink and a relaxing getaway"}, "POST", "/embedding"),
    ({"operation": "scrape_page", "url": "https://news.ycombinator.com/news", "element_prompts": ["titles", "points"]}, "POST", "/ai/scrape"),
    ({"operation": "extract_document", "url": "https://jigsawstack.com/preview/vocr-example.jpg", "prompt": "total_price"}, "POST", "/vocr"),
    ({"operation": "detect_objects", "url": "https://jigsawstack.com/preview/object-detection-example-input.jpg"}, "POST", "/object_detection"),
    ({"operation": "transcribe_audio", "url": "https://jigsawstack.com/preview/stt-example.wav"}, "POST", "/ai/transcribe"),
    ({"operation": "search_web", "query": "What is the capital of France?"}, "POST", "/web/search"),
    ({"operation": "suggest_search", "query": "What is the capital"}, "GET", "/web/search/suggest"),
    ({"operation": "list_prompts", "limit": 10}, "GET", "/prompt_engine"),
    ({"operation": "create_prompt", "prompt": "Tell me a story about {about}", "inputs": [{"key": "about", "optional": False, "initial_value": "Leaning Tower of Pisa"}]}, "POST", "/prompt_engine"),
    ({"operation": "run_prompt", "id": ID, "input_values": {"text": "How to get started with JigsawStack?"}}, "POST", "/prompt_engine/{id}"),
    ({"operation": "delete_prompt", "id": ID}, "DELETE", "/prompt_engine/{id}"),
]
FIXTURES = json.loads((Path(__file__).parent / "fixtures/jigsawstack/responses.json").read_text())


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        code, payload = responses.pop(0)
        return httpx.Response(code, json=payload)

    original = httpx.AsyncClient.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(send)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    return requests, responses


def node(config):
    n = NodeFactory.create_node(node_id="jigsawstack-test", node_type="automation-jigsawstack", node_data={"config": config, "credentials": AUTH})
    n.emit = AsyncMock()
    return n


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_jigsawstack_documented_response(config, method, path, transport):
    requests, responses = transport
    # Delete docs describe a boolean acknowledgement, without a JSON example.
    payload = FIXTURES.get(method + " " + path, {"body": {"success": True}})["body"]
    responses.append((200, payload))
    result = await node(config).execute({})
    assert result["success"] is True
    assert result["data"] == payload
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method
    assert str(req.url).startswith(js.BASE + path.replace("{id}", ID))
    assert req.headers["x-api-key"] == KEY
    assert KEY not in str(req.url) and KEY not in req.content.decode()
    if method == "POST":
        body = json.loads(req.content)
        assert "operation" not in body
        for field, value in config.items():
            if field != "operation":
                assert body[field] == value
        if config["operation"] in {"transcribe_audio", "run_prompt"}:
            assert body["stream"] is False
        if config["operation"] == "detect_objects":
            assert body["return_type"] == "url"
    elif method == "DELETE":
        assert req.content == b""
    if config["operation"] == "suggest_search":
        assert req.url.params["query"] == config["query"]
    if config["operation"] == "list_prompts":
        assert req.url.params["limit"] == "10" and req.url.params["page"] == "1"
        assert result["items"] == payload["prompt_engines"]
        assert result["has_more"] == payload["has_more"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 429, 500])
async def test_jigsawstack_failure_is_not_success(code, transport):
    _, responses = transport
    responses.append((code, {"success": False, "error": {"message": "Rejected " + KEY, "code": "rejected"}}))
    result = await node({"operation": "list_prompts"}).execute({})
    assert result["success"] is False and result["status"] == "error"
    assert result["http_status"] == code
    assert KEY not in json.dumps(result)
    assert "Rejected [redacted]" == result["error"]["message"]


@pytest.mark.asyncio
async def test_jigsawstack_http_success_error_envelope(transport):
    _, responses = transport
    responses.append((200, {"success": False, "error": {"message": "Invalid input"}}))
    result = await node({"operation": "check_spam", "text": "Hello world"}).execute({})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_jigsawstack_missing_prompt_list_is_unverified(transport):
    _, responses = transport
    responses.append((200, {"success": True}))
    with pytest.raises(ValueError, match="prompt list is missing"):
        await node({"operation": "list_prompts"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "run_prompt", "id": "../escape"},
    {"operation": "delete_prompt", "id": "https://example.com"},
    {"operation": "translate_text", "text": "Hi", "target_language": "invalid"},
    {"operation": "analyze_sentiment", "text": "a" * 2001},
    {"operation": "list_prompts", "page": 0},
])
def test_jigsawstack_invalid_config(config):
    assert not js.JigsawstackNode.validate_config({"config": config, "credentials": AUTH})["valid"]


def test_jigsawstack_manual_credential_default():
    credential = js.JigsawstackAPIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == "jigsawstack_api_key"
    assert credential.api_key == KEY
    with pytest.raises(ValidationError):
        js.JigsawstackAPIKeyCredential(api_key="https://example.com/key")
