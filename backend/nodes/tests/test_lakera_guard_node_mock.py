"""Native factory/HTTP contract checks; no provider credentials or live calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import lakera_guard_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-lakera-test-key-42"
MESSAGES = [{"role": "user", "content": "Hello"}]
PUBLISHED = json.loads((Path(__file__).parent / "fixtures/lakera-guard/published_responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(
        node_id="lakera-fixture", node_type="automation-lakera-guard",
        node_data={"config": config, "credentials": {
            "credential_type": "lakera_guard_api_key", "api_key": TOKEN, **credential,
        }},
    )


def transport(monkeypatch, body, status=200):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,body", [
    ({"operation": "screen_content", "messages": MESSAGES, "payload": False, "breakdown": True},
     "/v2/guard", {"flagged": False, "action": "detect", "breakdown": [{"detected": True}]}),
    ({"operation": "get_detection_results", "messages": MESSAGES},
     "/v2/guard/results", {"results": [{"result": "l1_confident", "message_id": 0}]}),
    ({"operation": "check_policy_health", "project_id": "project-42"},
     "/v2/policies/health", {"status": "error", "is_default": False, "lint": {"passed": False}}),
    ({"operation": "validate_policy"}, "/v2/policies/lint", {"passed": False, "errors": []}),
])
async def test_lakera_guard_contract_routes_and_preserved_decisions(monkeypatch, config, path, body):
    requests = transport(monkeypatch, body)
    output = await node(config).execute({})
    assert output == {"status": "success", "operation": config["operation"], "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST" and str(request.url) == "https://api.lakera.ai" + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if config["operation"] == "validate_policy":
        assert request.content == b""
    else:
        assert json.loads(request.content) == {k: v for k, v in config.items() if k != "operation"}


@pytest.mark.asyncio
async def test_lakera_guard_tools_only_regional_request_and_optional_fields(monkeypatch):
    tools = [{"type": "function", "function": {"name": "get_weather", "strict": False,
              "parameters": {"type": "object", "properties": {"location": {"type": "string"}}}}}]
    requests = transport(monkeypatch, {"results": [], "tools": {"flagged": True, "results": []}})
    config = {"operation": "get_detection_results", "tools": tools, "conversation_id": "session:42",
              "metadata": {"user_id": "test", "count": 2}, "dev_info": False}
    await node(config, api_base_url="https://eu.api.lakera.ai").execute({})
    assert requests[0].url.host == "eu.api.lakera.ai"
    assert json.loads(requests[0].content) == {k: v for k, v in config.items() if k != "operation"}


@pytest.mark.asyncio
async def test_lakera_guard_assistant_tool_calls_and_text_parts(monkeypatch):
    requests = transport(monkeypatch, {"flagged": True})
    messages = [{"role": "assistant", "content": None, "tool_calls": [{"type": "function",
                 "id": "call-1", "function": {"name": "get_weather", "arguments": "{}"}}]},
                {"role": "tool", "content": [{"type": "text", "text": "18 C"}]}]
    await node({"operation": "screen_content", "messages": messages}).execute({})
    sent = json.loads(requests[0].content)
    assert "content" not in sent["messages"][0]
    assert sent["messages"][1] == messages[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 422, 429, 500, 503])
async def test_lakera_guard_failures_never_become_clean_decisions_or_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Rejected " + TOKEN}, status)
    output = await node({"operation": "screen_content", "messages": MESSAGES}).execute({})
    assert output["status"] == "error" and output["http_status"] == status
    assert TOKEN not in str(output) and "Rejected" in output["error"]
    assert len(requests) == 1 and "data" not in output


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [
    ("screen_content", {}), ("screen_content", {"flagged": "false"}),
    ("get_detection_results", {}), ("check_policy_health", {"status": "unknown"}),
    ("validate_policy", {}), ("validate_policy", {"passed": "true"}),
])
async def test_lakera_guard_missing_decisions_fail_closed(monkeypatch, operation, body):
    transport(monkeypatch, body)
    config = {"operation": operation}
    if operation in {"screen_content", "get_detection_results"}:
        config["messages"] = MESSAGES
    elif operation == "check_policy_health":
        config["project_id"] = "project-42"
    with pytest.raises(ValueError):
        await node(config).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", [
    ("screen_content", "/v2/guard"), ("get_detection_results", "/v2/guard/results"),
    ("check_policy_health", "/v2/policies/health"), ("validate_policy", "/v2/policies/lint"),
])
async def test_lakera_guard_provider_published_responses(monkeypatch, operation, route):
    """Keep the provider's examples verbatim, including optional tool results."""
    example = PUBLISHED["POST " + route]
    assert example["source"].startswith("https://docs.lakera.ai/")
    transport(monkeypatch, example["body"])
    config = {"operation": operation}
    if operation in {"screen_content", "get_detection_results"}:
        config["messages"] = MESSAGES
    elif operation == "check_policy_health":
        config["project_id"] = "string"
    result = await node(config).execute({})
    assert result["data"] == example["body"]


@pytest.mark.parametrize("config", [
    {"operation": "screen_content"}, {"operation": "get_detection_results", "messages": []},
    {"operation": "screen_content", "messages": [{"role": "user"}]},
    {"operation": "screen_content", "messages": MESSAGES, "conversation_id": "has spaces"},
    {"operation": "check_policy_health"}, {"operation": "validate_policy", "policy": {}},
])
def test_lakera_guard_rejects_invalid_inputs(config):
    assert not native.LakeraGuardNode.validate_config({"config": config})["valid"]


@pytest.mark.parametrize("key", ["Bearer abc", "bad\nkey", "https://example.test/key"])
def test_lakera_guard_rejects_bad_keys(key):
    with pytest.raises(ValidationError):
        native.LakeraGuardApiKeyCredential(api_key=key)


def test_lakera_guard_manual_credential_and_reachability_evidence():
    credential = native.LakeraGuardApiKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "lakera_guard_api_key"
    assert native.LakeraGuardNode.connection_evidence.proves == "reachability"
    assert native.LakeraGuardNode.connection_evidence.operation == "validate_policy"
    with pytest.raises(ValidationError):
        native.LakeraGuardApiKeyCredential(api_key=TOKEN, api_base_url="https://evil.test")
