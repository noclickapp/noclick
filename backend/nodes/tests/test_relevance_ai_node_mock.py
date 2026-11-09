"""Exercise Relevance AI's actual factory and HTTP boundary without an account.

Synthetic fixtures cover the published methods, paths and body shapes; the
external conformance harness independently judges them against the pinned spec.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import relevance_ai_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

KEY = "synthetic-relevance-key"
CREDENTIAL = {"credential_type": "relevance_ai_api_key", "project_id": "project-1", "api_key": KEY, "region": "au"}
CASES = json.loads((Path(__file__).parent / "fixtures/relevance-ai/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=CREDENTIAL):
    return NodeFactory.create_node(node_id="relevance-ai-test", node_type="automation-relevance-ai",
        node_data={"config": config, "credentials": credential})


def mock_client(monkeypatch, body, status=200, content=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if content is None else httpx.Response(status, content=content)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body,response", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_relevance_ai_contract_requests(monkeypatch, config, method, path, query, body, response):
    requests = mock_client(monkeypatch, response)
    output = await node(config).execute({})
    assert output == {"status": "success", "data": response}
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path
    assert req.url.host == "api-f1db6c.stack.tryrelevance.com"
    assert req.headers["Authorization"] == "project-1:" + KEY
    assert dict(req.url.params) == query
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("region,host", [("au", "api-f1db6c.stack.tryrelevance.com"), ("us", "api-bcbe5a.stack.tryrelevance.com"), ("eu", "api-d7b62b.stack.tryrelevance.com")])
async def test_relevance_ai_region_is_fixed_to_provider(monkeypatch, region, host):
    requests = mock_client(monkeypatch, {"results": []})
    await node({"operation": "list_agents"}, {**CREDENTIAL, "region": region}).execute({})
    assert requests[0].url.host == host


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 404, 422, 429, 500])
async def test_relevance_ai_rejections_are_verbatim_redacted_and_not_retried(monkeypatch, status):
    requests = mock_client(monkeypatch, {"message": "Rejected " + KEY}, status)
    result = await node({"operation": "list_agents"}).execute({})
    assert result == {"status": "error", "status_code": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"status": "failed", "errors": [{"message": "Tool failed " + KEY}], "output": {}},
    {"type": "failed", "updates": [], "last_message_id": 1},
    {"error": "Invalid API key " + KEY},
])
async def test_relevance_ai_execution_failures_are_not_success(monkeypatch, payload):
    mock_client(monkeypatch, payload)
    result = await node({"operation": "run_tool", "studio_id": "tool"}).execute({})
    assert result["status"] == "error" and KEY not in str(result)


@pytest.mark.asyncio
async def test_relevance_ai_jobs_keep_progress_and_are_not_polled_implicitly(monkeypatch):
    reply = {"type": "timeout", "updates": [{"output": {"value": 1}}], "last_message_id": 12}
    requests = mock_client(monkeypatch, reply)
    result = await node({"operation": "get_tool_job", "studio_id": "tool", "job_id": "job"}).execute({})
    assert result["data"] == reply and len(requests) == 1


@pytest.mark.asyncio
async def test_relevance_ai_refuses_non_json_and_unexpected_response(monkeypatch):
    mock_client(monkeypatch, None, content=b"<html>Sign in</html>")
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "list_agents"}).execute({})
    for payload in ([], {}):
        mock_client(monkeypatch, payload)
        with pytest.raises(ValueError, match="response shape"):
            await node({"operation": "list_agents"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_agent", "agent_id": "../keys"},
    {"operation": "get_tool", "studio_id": "https://example.com"},
    {"operation": "get_tool_job", "studio_id": "tool"},
    {"operation": "list_agents", "page": 0},
    {"operation": "list_tools", "page_size": 101},
    {"operation": "trigger_agent", "agent_id": "agent", "message": ""},
    {"operation": "run_tool", "studio_id": "tool", "params": "[]"},
    {"operation": "add_knowledge", "knowledge_set": "policies", "data": "[]"},
    {"operation": "add_knowledge", "knowledge_set": "policies", "data": '[{"type":"text","value":{},"extra":true}]'},
    {"operation": "delete_knowledge", "knowledge_set": "policies"},
])
def test_relevance_ai_bad_config_fails_before_network(config):
    with pytest.raises(ConfigValidationError):
        native.RelevanceAINode.parse_config({"config": config})


@pytest.mark.parametrize("patch", [{"api_key": "project:secret"}, {"api_key": "Bearer secret"}, {"api_key": "secret\nheader"}, {"api_key": "https://example.com"}, {"api_key": "sécret"}, {"project_id": "../project"}, {"region": "https://example.com"}])
def test_relevance_ai_manual_credential_validation(patch):
    with pytest.raises(ValidationError):
        native.RelevanceAIAPIKeyCredential.model_validate({**CREDENTIAL, **patch})


def test_relevance_ai_credential_defaults_type():
    assert native.RelevanceAIAPIKeyCredential(project_id="project", api_key=KEY).credential_type == "relevance_ai_api_key"


@pytest.mark.asyncio
async def test_relevance_ai_evidence_is_account_specific_and_preserves_denial(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    import nodes.core.run_op as runner
    async def run_operation(**kwargs):
        return await node({"operation": kwargs["operation"]}, kwargs["credential_data"]).execute({})
    monkeypatch.setattr(runner, "run_node_operation", run_operation)
    mock_client(monkeypatch, {"results": [{"name": "Sales Assistant", "agent_id": "sales-agent"}]})
    kwargs = dict(node_type="automation-relevance-ai", user_id="test-user", pool=None, credential_data=CREDENTIAL)
    evidence = await collect_evidence(**kwargs)
    assert evidence.reachable is True and evidence.samples[0].label == "Sales Assistant"
    mock_client(monkeypatch, {"message": "This key has been revoked."}, 401)
    evidence = await collect_evidence(**kwargs)
    assert evidence.reachable is False and "This key has been revoked." in evidence.error
