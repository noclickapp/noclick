"""Exercise Cloro through the real node factory with a recording HTTP transport.

These synthetic responses verify wire shapes, error handling and credit-safe
request behavior without using a Cloro account or consuming provider credits.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import cloro_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-cloro-api-key-123"
TASK_ID = "2ca6a28e-bf47-43cf-9ef5-6d67b74be234"
TASK = {"taskType": "CHATGPT", "payload": {"prompt": "What do you know about Acme Corp?", "country": "US"}}
CASES = [
    ("monitor_chatgpt", "POST", "/v1/monitor/chatgpt", {"prompt": ["Best shoes?", "Which cost less than $100?"], "country": "US"}),
    ("monitor_gemini", "POST", "/v1/monitor/gemini", {"prompt": "Explain quantum computing", "country": "US"}),
    ("monitor_google", "POST", "/v1/monitor/google", {"query": "best laptops for programming", "country": "US"}),
    ("get_google_product", "POST", "/v1/monitor/google/product", {"productResultToken": "nuzK-QgAV8BqrZdwQJYZopzdoFhpvKr-N2_YDZevwzg"}),
    ("resolve_google_goto", "POST", "/v1/monitor/google/goto", {"url": "https://www.google.com/goto?url=sample-token"}),
    ("monitor_google_news", "POST", "/v1/monitor/google/news", {"query": "climate change", "gl": "us"}),
    ("monitor_perplexity", "POST", "/v1/monitor/perplexity", {"prompt": "What are the best laptops for programming?", "country": "US"}),
    ("monitor_ai_mode", "POST", "/v1/monitor/aimode", {"prompt": "What are the best laptops for programming?", "gl": "us"}),
    ("monitor_bing_ai_mode", "POST", "/v1/monitor/bing/aimode", {"prompt": "What are the best running shoes for beginners?", "country": "US"}),
    ("get_countries", "GET", "/v1/countries", {"model": "chatgpt"}),
    ("create_async_task", "POST", "/v1/async/task", TASK),
    ("create_batch_async_tasks", "POST", "/v1/async/task/batch", {"tasks": [TASK]}),
    ("get_task_status", "GET", "/v1/async/task/" + TASK_ID, {"taskId": TASK_ID}),
    ("get_async_status", "GET", "/v1/async/status", {}),
    ("clear_async_queue", "DELETE", "/v1/async/queue", {}),
    ("get_credits", "GET", "/v1/credits", {}),
    ("get_states", "GET", "/v1/states", {"country": "US"}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, config=None, credentials=None):
    return NodeFactory.create_node(node_id="cloro-test", node_type="automation-cloro", node_data={
        "config": {"operation": operation, **(config or {})},
        "credentials": credentials or {"credential_type": "cloro_api_key", "api_key": TOKEN},
    })


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
@pytest.mark.parametrize("operation,method,path,config", CASES)
async def test_cloro_wire_contract_and_unchanged_results(monkeypatch, operation, method, path, config):
    body = {"remaining": 48210, "perCycle": 1562500, "cycleResetsAt": "2026-08-10T17:35:27.000Z"} if operation == "get_credits" else {"result": {"sources": [{"url": "https://example.com", "title": "Research"}]}, "futureField": True}
    requests = transport(monkeypatch, body)
    result = await node(operation, config).execute({})
    assert result == {"status": "success", "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.cloro.dev"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if method == "POST":
        assert json.loads(request.content) == (config["tasks"] if operation == "create_batch_async_tasks" else config)
    else:
        assert not request.content
        assert dict(request.url.params) == ({k: v for k, v in config.items() if k != "taskId"})


@pytest.mark.asyncio
async def test_cloro_google_url_and_optional_formats(monkeypatch):
    requests = transport(monkeypatch, {"result": {}})
    config = {"url": "https://www.google.com/search?q=best+laptops+for+programming&hl=en&gl=us&num=30", "include": {"aioverview": {"markdown": True}, "paaAioverview": True}}
    await node("monitor_google", config).execute({})
    assert json.loads(requests[0].content) == config


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 429, 503])
async def test_cloro_errors_are_verbatim_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"success": False, "error": {"code": "REJECTED", "message": "Provider rejected " + TOKEN}}, status)
    result = await node("get_credits").execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert result["error"] == "Provider rejected [redacted]"
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_cloro_success_envelope_cannot_hide_provider_failure(monkeypatch):
    transport(monkeypatch, {"success": False, "error": {"message": "Invalid API key"}})
    assert (await node("get_credits").execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_cloro_batch_partial_failures_are_preserved(monkeypatch):
    body = {"summary": {"total": 2, "successful": 1, "failed": 1}, "results": [{"success": True, "taskId": TASK_ID}, {"success": False, "error": "Queue full"}]}
    transport(monkeypatch, body)
    assert (await node("create_batch_async_tasks", {"tasks": [TASK, TASK]}).execute({}))["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, "html", {}, {"remaining": True, "perCycle": None, "cycleResetsAt": None}])
async def test_cloro_incomplete_evidence_does_not_verify(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node("get_credits").execute({})


@pytest.mark.parametrize("operation,config", [
    ("monitor_google", {"query": "test"}),
    ("monitor_google", {"query": "test", "country": "US", "url": "https://www.google.com/search?q=x"}),
    ("monitor_google", {"query": "test", "country": "US", "pages": 11}),
    ("monitor_google", {"url": "https://google.com.evil.test/search?q=x"}),
    ("monitor_google", {"query": "test", "country": "US", "gl": "de"}),
    ("monitor_google_news", {"query": "test"}),
    ("monitor_ai_mode", {"prompt": "test", "country": "US", "uule": "test", "location": "New York"}),
    ("monitor_chatgpt", {"prompt": "test", "country": "DE", "state": "CA"}),
    ("monitor_bing_ai_mode", {"prompt": "字" * 389, "country": "US"}),
    ("monitor_bing_ai_mode", {"prompt": "test", "country": "CN"}),
    ("create_async_task", {"taskType": "CHATGPT", "payload": {"prompt": "test"}}),
    ("create_async_task", {"taskType": "GOOGLE_PRODUCT", "payload": {"prompt": "test", "country": "US"}}),
    ("create_batch_async_tasks", {"tasks": []}),
    ("get_task_status", {"taskId": "../../other"}),
])
def test_cloro_invalid_inputs_rejected_before_request(operation, config):
    with pytest.raises(ValueError):
        node(operation, config)


def test_cloro_manual_credential_defaults_and_secret_shape():
    assert native.CloroAPIKeyCredential(api_key=TOKEN).credential_type == "cloro_api_key"
    for value in ["https://example.com/token", "Bearer some-token"]:
        with pytest.raises(ValidationError):
            native.CloroAPIKeyCredential(api_key=value)
