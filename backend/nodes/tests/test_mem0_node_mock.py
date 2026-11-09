"""Exercise Mem0 through the real node factory and an intercepted HTTP transport.

Fixtures are synthetic account data; tests verify requests, async semantics,
manual credential shape, and failure handling without using a live account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import mem0_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-mem0-api-key"
MEMORY = "550e8400-e29b-41d4-a716-446655440000"
EVENT = "2c4d1f44-4f7b-4b2f-9f6e-7b5b4f5a1234"
FIXTURE = Path(__file__).parent / "fixtures/mem0/responses.json"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="mem0-contract-test", node_type="automation-mem0", node_data={
        "config": config, "credentials": credentials or {"credential_type": "mem0_api_key", "api_key": TOKEN}})


def transport(monkeypatch, payload, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


CASES = [
    ({"operation": "add_memories", "user_id": "alice", "messages": '[{"role":"user","content":"I moved to Austin last month."}]', "metadata": '{"source":"onboarding_form"}', "expiration_date": "2027-12-31"}, "POST", "/v3/memories/add/", {"user_id": "alice", "messages": [{"role": "user", "content": "I moved to Austin last month."}], "metadata": {"source": "onboarding_form"}, "infer": True, "expiration_date": "2027-12-31"}),
    ({"operation": "list_memories", "filters": '{"user_id":"alice"}', "page": 2}, "POST", "/v3/memories/", {"filters": {"user_id": "alice"}, "page": 2, "page_size": 100, "show_expired": False}),
    ({"operation": "search_memories", "query": "where does the user live?", "filters": '{"user_id":"alice"}'}, "POST", "/v3/memories/search/", {"query": "where does the user live?", "filters": {"user_id": "alice"}, "top_k": 10, "threshold": 0.1, "rerank": False, "show_expired": False}),
    ({"operation": "get_memory", "memory_id": MEMORY}, "GET", f"/v1/memories/{MEMORY}/", None),
    ({"operation": "update_memory", "memory_id": MEMORY, "text": "Lives in Austin", "metadata": '{"source":"profile"}'}, "PUT", f"/v1/memories/{MEMORY}/", {"text": "Lives in Austin", "metadata": {"source": "profile"}}),
    ({"operation": "delete_memory", "memory_id": MEMORY, "delete_linked": True}, "DELETE", f"/v1/memories/{MEMORY}/", None),
    ({"operation": "get_memory_history", "memory_id": MEMORY}, "GET", f"/v1/memories/{MEMORY}/history/", None),
    ({"operation": "batch_update_memories", "memories": json.dumps([{"memory_id": MEMORY, "text": "Updated"}])}, "PUT", "/v1/batch/", {"memories": [{"memory_id": MEMORY, "text": "Updated"}]}),
    ({"operation": "batch_delete_memories", "memories": json.dumps([{"memory_id": MEMORY}])}, "DELETE", "/v1/batch/", {"memories": [{"memory_id": MEMORY}]}),
    ({"operation": "list_entities", "org_id": "org-1", "project_id": "proj-1"}, "GET", "/v1/entities/", None),
    ({"operation": "get_entity", "entity_type": "agent", "entity_id": "travel agent"}, "GET", "/v2/entities/agent/travel agent/", None),
    ({"operation": "delete_entity", "entity_id": "alice"}, "DELETE", "/v2/entities/user/alice/", None),
    ({"operation": "create_user", "user_id": "alice", "metadata": '{"plan":"premium"}'}, "POST", "/v1/users/", {"user_id": "alice", "metadata": {"plan": "premium"}}),
    ({"operation": "create_agent", "agent_id": "agent-1", "name": "Travel agent"}, "POST", "/v1/agents/", {"agent_id": "agent-1", "name": "Travel agent"}),
    ({"operation": "create_app", "app_id": "app-1", "name": "Travel app"}, "POST", "/v1/apps/", {"app_id": "app-1", "name": "Travel app"}),
    ({"operation": "create_run", "run_id": "run-1", "name": "Trip planning"}, "POST", "/v1/runs/", {"run_id": "run-1", "name": "Trip planning"}),
    ({"operation": "get_event", "event_id": EVENT}, "GET", f"/v1/event/{EVENT}/", None),
    ({"operation": "get_statistics"}, "GET", "/v1/stats/", None),
    ({"operation": "check_connection"}, "GET", "/v1/ping/", None),
    ({"operation": "submit_feedback", "memory_id": MEMORY, "feedback": "POSITIVE", "feedback_reason": "Accurate"}, "POST", "/v1/feedback/", {"memory_id": MEMORY, "feedback": "POSITIVE", "feedback_reason": "Accurate"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_factory_one_documented_request_and_response(monkeypatch, config, method, path, body):
    fixtures = json.loads(FIXTURE.read_text())
    payload = fixtures.get(config["operation"], {"message": "Accepted"})
    calls = transport(monkeypatch, payload)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": payload, "http_status": 200}
    assert len(calls) == 1
    req = calls[0]
    assert req.method == method and req.url.path == path
    assert req.url.host == "api.mem0.ai" and req.url.scheme == "https"
    assert req.headers["Authorization"] == "Token " + TOKEN
    assert (json.loads(req.content) if req.content else None) == body
    expected_query = {"delete_linked": "true"} if config["operation"] == "delete_memory" else {"org_id": "org-1", "project_id": "proj-1"} if config["operation"] == "list_entities" else {}
    assert dict(req.url.params) == expected_query
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_async_acknowledgement_and_pagination_remain_explicit(monkeypatch):
    payload = {"event_id": EVENT, "status": "PENDING"}
    transport(monkeypatch, payload)
    result = await node(CASES[0][0]).run({})
    assert result["data"] == payload
    assert "completed" not in result and "written" not in result
    payload = {"count": 101, "next": "https://api.mem0.ai/v3/memories/?page=2", "previous": None, "results": []}
    calls = transport(monkeypatch, payload)
    assert (await node({"operation": "list_memories", "filters": '{"user_id":"alice"}'}).run({}))["data"] == payload
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_provider_error_is_verbatim_except_echoed_key(monkeypatch, status):
    calls = transport(monkeypatch, {"detail": "Rejected key " + TOKEN}, status)
    result = await node({"operation": "list_entities"}).execute({})
    assert result == {"status": "error", "error": "Rejected key [redacted]", "http_status": status}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_error_envelope_scalar_and_non_json_fail(monkeypatch):
    for payload in [{"error": "Invalid API key"}, "html", None]:
        transport(monkeypatch, payload)
        assert (await node({"operation": "check_connection"}).execute({}))["status"] == "error"
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>Login</html>")), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    assert (await node({"operation": "check_connection"}).execute({}))["error"] == "Mem0 returned a non-JSON response"


def test_credential_default_manual_fields_and_foreign_family():
    shaped = native.Mem0APIKeyCredential(api_key="  " + TOKEN + "  ")
    assert shaped.credential_type == "mem0_api_key" and shaped.api_key == TOKEN
    for key in ["https://example.com/key", "Token abc", ""]:
        with pytest.raises(ValidationError):
            native.Mem0APIKeyCredential(api_key=key)
    with pytest.raises(ValidationError):
        native.Mem0APIKeyCredential(credential_type="other_api_key", api_key=TOKEN)


@pytest.mark.parametrize("config", [
    {"operation": "get_memory", "memory_id": "invalid"},
    {"operation": "get_entity", "entity_id": "../alice"},
    {"operation": "add_memories", "messages": "[]", "user_id": "alice"},
    {"operation": "add_memories", "messages": '[{"role":"user","content":"Hello"}]'},
    {"operation": "search_memories", "query": "tea", "filters": "[]"},
    {"operation": "batch_delete_memories", "memories": "[]"},
    {"operation": "batch_update_memories", "memories": json.dumps([{"memory_id": MEMORY}])},
    {"operation": "batch_delete_memories", "memories": json.dumps([{"memory_id": MEMORY, "text": "unrelated"}])},
])
def test_invalid_config_never_reaches_transport(config):
    with pytest.raises(ConfigValidationError, match="Invalid configuration"):
        node(config)


@pytest.mark.asyncio
async def test_failed_event_is_event_data_and_filters_require_entity(monkeypatch):
    payload = {"id": EVENT, "status": "FAILED", "error": "Extraction failed"}
    transport(monkeypatch, payload)
    assert (await node({"operation": "get_event", "event_id": EVENT}).execute({}))["data"] == payload
    with pytest.raises(ConfigValidationError, match="Filters must include"):
        node({"operation": "list_memories", "filters": "{}"})
    nested = {"OR": [{"user_id": "alice"}, {"agent_id": {"in": ["travel-agent"]}}]}
    assert node({"operation": "search_memories", "query": "travel", "filters": json.dumps(nested)}).config.config.query == "travel"
