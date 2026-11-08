"""Exercise the real node through its factory with captured provider requests."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import docsbot_ai_node as provider
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError
from utils import ssrf

AUTH = {"credential_type": "docsbot_ai_api_key", "api_key": "fixture-docsbot-key"}
BASE = "/teams/team-1/bots/bot-1"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/docsbot-ai/responses.json").read_text())


def node(config, credentials=AUTH):
    return NodeFactory.create_node(node_id="docsbot-test", node_type="automation-docsbot-ai",
        node_data={"config": config, "credentials": credentials})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    def send(request):
        requests.append(request)
        status, data = replies.pop(0)
        return httpx.Response(status, json=data)
    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(provider, "guarded_async_client", lambda **kwargs: guarded(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


CASES = [
    ("chat", {"question": "What is WordPress?"}, "POST", "/chat", "chat"),
    ("chat_agent", {"question": "Help me", "conversationId": "conv-1"}, "POST", "/chat-agent", "agent"),
    ("search", {"query": "How do I reset my password?", "top_k": 6, "alpha": 0.6}, "POST", "/search", "search"),
    ("fetch_document", {"fileId": "abc123"}, "POST", "/fetch", "fetch"),
    ("rate_answer", {"answer_id": "answer-1", "rating": -1}, "PUT", "/rate/answer-1", "ack"),
    ("log_support", {"answer_id": "answer-1"}, "PUT", "/support/answer-1", "ack"),
    ("escalate_conversation", {"conv_id": "conv-1"}, "PUT", "/conversations/conv-1/escalate", "ack"),
    ("update_conversation", {"conv_id": "conv-1", "metadata": {"name": "John Doe"}}, "PUT", "/conversations/conv-1", "ack"),
    ("capture_lead", {"conv_id": "conv-1", "metadata": {"email": "john@example.com"}}, "POST", "/conversations/conv-1/lead", "ack"),
    ("summarize_conversation", {"conv_id": "conv-1"}, "GET", "/conversations/conv-1/summarize", "summary"),
    ("create_ticket", {"conv_id": "conv-1"}, "GET", "/conversations/conv-1/ticket", "ticket"),
    ("start_research", {"question": "What are the current trends in AI customer support?"}, "POST", "/research", "research"),
    ("continue_research", {"job_id": "job-1", "answers": "Focus on the SaaS industry, specifically for B2B customer support teams."}, "POST", "/research/job-1", "queued"),
    ("get_research", {"job_id": "job-1"}, "GET", "/research/job-1", "queued"),
    ("cancel_research", {"job_id": "job-1"}, "DELETE", "/research/job-1", "ack"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,example", CASES)
async def test_operation_request_and_provider_response(transport, operation, arguments, method, path, example):
    requests, replies = transport
    response = EXAMPLES[example]
    replies.append((200, response))
    result = await node({"operation": operation, "team_id": "team-1", "bot_id": "bot-1", **arguments}).execute({})
    assert result == {"data": response}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == BASE + path
    assert request.url.host == "api.docsbot.ai" and not request.url.query
    assert request.headers["Authorization"] == "Bearer fixture-docsbot-key"
    assert "fixture-docsbot-key" not in str(result)
    if request.content:
        body = json.loads(request.content)
        assert not {"operation", "team_id", "bot_id", "conv_id", "answer_id", "job_id"} & body.keys()
        for key, value in arguments.items():
            if key not in {"conv_id", "answer_id", "job_id"}:
                assert body[key] == value
        if operation == "chat_agent":
            assert body["stream"] is False
        if operation == "capture_lead":
            assert "fullChange" not in body
    else:
        assert method in {"GET", "DELETE"} or operation in {"log_support", "escalate_conversation"}


@pytest.mark.asyncio
async def test_libraries_are_account_evidence_and_preserve_labels(transport):
    requests, replies = transport
    data = {"libraries": [{"name": "Support knowledge", "description": "Help articles", "team_id": "team-1", "bot_id": "bot-1"}]}
    replies.append((200, data))
    result = await node({"operation": "list_libraries"}).execute({})
    assert result["data"] == data["libraries"]
    assert requests[0].url.path == "/libraries" and requests[0].method == "GET"
    assert not requests[0].content
    assert provider.DocsbotAiNode.connection_evidence.operation == "list_libraries"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_failures_do_not_report_success(transport, status):
    requests, replies = transport
    replies.append((status, {"error": "Rejected"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "list_libraries"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_and_invalid_evidence_shape(transport):
    _, replies = transport
    replies.extend([(200, {"error": "fixture-docsbot-key rejected"}), (200, {})])
    with pytest.raises(ValueError, match=r"\[redacted\] rejected"):
        await node({"operation": "list_libraries"}).execute({})
    with pytest.raises(ValueError, match="invalid libraries"):
        await node({"operation": "list_libraries"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "rate_answer", "team_id": "t", "bot_id": "b", "answer_id": "a", "rating": 2},
    {"operation": "chat", "team_id": "t", "bot_id": "b"},
    {"operation": "get_research", "team_id": "..", "bot_id": "b", "job_id": "j"},
    {"operation": "chat_agent", "team_id": "t", "bot_id": "b", "question": "hello", "conversationId": "c", "stream": True},
    {"operation": "unknown"},
])
def test_invalid_config_is_rejected(config):
    with pytest.raises(ConfigValidationError):
        provider.DocsbotAiNode.parse_config({"config": config, "credentials": AUTH})
