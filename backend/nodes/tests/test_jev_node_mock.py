"""Exercise Jev through the native factory with the provider's published examples.

HTTP is intercepted; no real key or inference request is used by these tests.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import jev_node as jev
from nodes.core.registry import NodeFactory
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/jev/contract_examples.json").read_text())
AUTH = {"credential_type": "jev_api_key", "api_key": "jev-fixture-not-a-live-key"}
STATE = EXAMPLES["requests"]["noul"]["state"]


def config_for(operation):
    if operation == "list_models": return {"operation": operation}
    kind = "box" if operation == "locate_in_image" else "choice" if operation in {"choose_option", "analyze_sentiment"} else "score" if operation in {"rate_content", "score_urgency"} else "noul"
    request = EXAMPLES["requests"][kind]
    key, question = next(iter(request["questions"].items()))
    config = {"operation": operation, "state": request["state"], "model": request["model"]}
    if operation == "evaluate_questions": config["questions"] = request["questions"]
    else: config.update({"question_name": key, **{k: v for k, v in question.items() if k != "type"}})
    if "assets" in request: config["assets"] = request["assets"]
    return config, kind


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.typesafe.ai"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, body, headers = replies.pop(0)
        return httpx.Response(status, json=body, headers=headers)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(jev, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(config, auth=AUTH):
    node = NodeFactory.create_node(node_id="jev-test", node_type="automation-jev", node_data={"config": config, "credentials": deepcopy(auth)})
    return await node.execute({})


OPS = ["evaluate_questions", "ask_yes_no", "choose_option", "rate_content", "locate_in_image", "detect_spam", "detect_toxicity", "analyze_sentiment", "score_urgency"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPS)
async def test_published_requests_and_responses(transport, operation):
    requests, replies = transport
    config, kind = config_for(operation)
    replies.append((200, EXAMPLES["responses"][kind], {}))
    result = await run(config)
    assert result == {"status": "success", **EXAMPLES["responses"][kind]}
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == "POST" and request.url.path == "/v1/systemone"
    assert json.loads(request.content) == EXAMPLES["requests"][kind]
    assert request.headers.get("TypeSafe-Danger-Zone-Images") == ("true" if kind == "box" else None)
    assert "data_base64" not in json.dumps(result)


@pytest.mark.asyncio
async def test_models_are_read_only_reachability_evidence(transport):
    requests, replies = transport
    models = {"models": [{"name": "jev-latest", "description": "General-purpose system one model.", "release_date": "2026-09-15"}]}
    replies.append((200, models, {}))
    assert await run({"operation": "list_models"}) == {"status": "success", **models}
    assert requests[0].method == "GET" and requests[0].url.path == "/v1/models" and not requests[0].content
    assert jev.JevNode.connection_evidence.proves == "reachability"
    assert jev.JevAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == "jev_api_key"


@pytest.mark.asyncio
async def test_mixed_questions_structured_state_and_long_context(transport):
    requests, replies = transport
    questions, answers = {}, {}
    for kind in ("noul", "choice", "score"):
        questions.update(EXAMPLES["requests"][kind]["questions"])
        answers.update(EXAMPLES["responses"][kind]["answers"])
    replies.append((200, {"model": "jev-latest", "answers": answers, "usage": {"input_tokens": 120, "output_tokens": 12}}, {}))
    result = await run({"operation": "evaluate_questions", "state": {"messages": [STATE]}, "questions": questions, "long_context": True})
    assert result["status"] == "success" and result["answers"] == answers
    assert requests[0].headers["TypeSafe-Danger-Zone-Long-Context"] == "true"
    assert json.loads(requests[0].content)["state"] == {"messages": [STATE]}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,headers", [
    (401, {"detail": "Invalid API key"}, {}),
    (429, {"detail": "Rate limit exceeded"}, {"Retry-After": "5"}),
    (529, {"detail": "Overloaded"}, {}),
    (302, {}, {"Location": "https://evil.test"}),
    (200, {"models": "malformed"}, {}),
    (200, {"models": []}, {"Content-Type": "text/html"}),
])
async def test_failures_never_succeed_or_retry(transport, status, body, headers):
    requests, replies = transport
    replies.append((status, body, headers))
    result = await run({"operation": "list_models"})
    assert result["status"] == "error"
    assert len(requests) == 1
    if status == 401: assert result["error"] == "Invalid API key"


@pytest.mark.asyncio
async def test_answer_names_and_types_must_match(transport):
    _, replies = transport
    replies.append((200, EXAMPLES["responses"]["choice"], {}))
    config, _ = config_for("ask_yes_no")
    assert (await run(config))["status"] == "error"


@pytest.mark.asyncio
async def test_errors_redact_key(transport):
    _, replies = transport
    replies.append((401, {"detail": "Rejected " + AUTH["api_key"]}, {}))
    assert AUTH["api_key"] not in json.dumps(await run({"operation": "list_models"}))


@pytest.mark.parametrize("key", ["Bearer abc", "https://example.com/key", "<token>", "abc\r\nX: evil"])
def test_manual_credentials_reject_headers_urls_and_placeholders(key):
    with pytest.raises((ValueError, ValidationError)):
        jev.JevAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("config", [
    {"operation": "choose_option", "state": STATE, "criteria": {}},
    {"operation": "rate_content", "state": STATE, "criteria": []},
    {"operation": "evaluate_questions", "state": STATE, "questions": {}},
    {"operation": "ask_yes_no", "state": {"number": float("nan")}, "instructions": "Valid?"},
    {"operation": "ask_yes_no", "state": STATE, "instructions": "Valid?", "model": " "},
])
def test_invalid_inputs(config):
    with pytest.raises(ValueError):
        jev.JevNode.parse_config({"config": config, "credentials": AUTH})


@pytest.mark.parametrize("operation,kind", [("detect_spam", "noul"), ("detect_toxicity", "noul"), ("analyze_sentiment", "choice"), ("score_urgency", "score")])
def test_presets_supply_editable_typed_questions(operation, kind):
    parsed = jev.JevNode.parse_config({"config": {"operation": operation, "state": STATE, "model": ""}, "credentials": AUTH})
    body = jev.request_body(parsed.config)
    assert body["model"] == "jev-latest"
    assert body["questions"]["result"]["type"] == kind
    assert body["questions"]["result"]["instructions"]
