"""Exercise Synthflow's native factory with intercepted HTTP requests.

These regressions pin required parameters, JSON writes, paging and credential
isolation without signing in or making calls to real recipients.
"""
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from nodes import synthflow_ai_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthflow-unit-test-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, region="global"):
    return NodeFactory.create_node(node_id="synthflow-test", node_type="automation-synthflow-ai",
        node_data={"config": config, "credentials": {"credential_type": "synthflow_ai_api_key", "api_key": TOKEN, "region": region}})


def transport(monkeypatch, body, status=200):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_agents_evidence_retains_pagination_and_region(monkeypatch):
    body = {"status": "ok", "response": {"assistants": [{"model_id": "agent-1", "name": "Sales"}], "pagination": {"offset": 40, "limit": 20}}}
    reqs = transport(monkeypatch, body)
    result = await node({"operation": "list_agents", "offset": 40}, "eu").execute({})
    assert result["data"] == body
    assert reqs[0].url.host == "api.eu.synthflow.ai"
    assert reqs[0].url.path == "/v2/assistants/"
    assert dict(reqs[0].url.params) == {"limit": "20", "offset": "40"}
    assert reqs[0].headers["Authorization"] == "Bearer " + TOKEN
    assert native.SynthflowAiNode.connection_evidence.operation == "list_agents"


@pytest.mark.asyncio
async def test_call_sends_required_recipient_and_custom_variables_once(monkeypatch):
    reqs = transport(monkeypatch, {"status": "ok", "response": {"call_id": "call-1"}, "eta": 3})
    cfg = {"operation": "make_call", "model_id": "agent-1", "phone": "+14155552671", "name": "Test Recipient", "custom_variables": [{"key": "company", "value": "Example"}]}
    result = await node(cfg).execute({})
    assert result["status"] == "success"
    assert len(reqs) == 1 and reqs[0].method == "POST"
    assert json.loads(reqs[0].content) == {k: v for k, v in cfg.items() if k != "operation"}


@pytest.mark.asyncio
async def test_call_filters_encode_plus_and_booleans(monkeypatch):
    reqs = transport(monkeypatch, {"status": "ok", "response": {"calls": []}})
    await node({"operation": "list_calls", "model_id": "agent-1", "lead_phone_number": "+14155552671", "include_all_actions": True}).execute({})
    assert reqs[0].url.params["model_id"] == "agent-1"
    assert reqs[0].url.params["include_all_actions"] == "true"
    assert b"%2B14155552671" in reqs[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg,method,path,body", [
    ({"operation": "create_contact", "name": "Ada", "phone_number": "+14155552671"}, "POST", "/contacts", {"name": "Ada", "phone_number": "+14155552671"}),
    ({"operation": "update_contact", "contact_id": "contact-1", "email": "ada@example.com"}, "PATCH", "/contacts/contact-1", {"email": "ada@example.com"}),
    ({"operation": "delete_contact", "contact_id": "contact-1"}, "DELETE", "/contacts/contact-1", None),
    ({"operation": "create_knowledge_base", "name": "Support"}, "POST", "/knowledge_base", {"name": "Support"}),
    ({"operation": "update_knowledge_base", "knowledge_base_id": "kb-1", "rag_use_condition": "Support questions"}, "PUT", "/knowledge_base/kb-1", {"rag_use_condition": "Support questions"}),
    ({"operation": "delete_knowledge_base", "knowledge_base_id": "kb-1"}, "DELETE", "/knowledge_base/kb-1", None),
    ({"operation": "delete_action", "action_id": "action-1"}, "DELETE", "/actions/action-1", None),
])
async def test_mutations_and_acknowledgement_only_responses(monkeypatch, cfg, method, path, body):
    reqs = transport(monkeypatch, {"status": "ok"})
    result = await node(cfg).execute({})
    assert result["status"] == "success"
    assert len(reqs) == 1
    assert (reqs[0].method, reqs[0].url.path) == (method, "/v2" + path)
    assert (json.loads(reqs[0].content) if reqs[0].content else None) == body


@pytest.mark.asyncio
async def test_phone_number_requires_workspace_and_preserves_slug(monkeypatch):
    body = {"slug": "14155552671", "phone_number": "+14155552671", "workspace_id": "workspace-1"}
    reqs = transport(monkeypatch, body)
    result = await node({"operation": "get_phone_number", "phone_number_slug": "14155552671", "workspace": "workspace-1"}).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert reqs[0].url.path == "/v2/numbers/14155552671"
    assert dict(reqs[0].url.params) == {"workspace": "workspace-1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [200, 401, 429])
async def test_provider_error_and_secret_redaction(monkeypatch, http_status):
    transport(monkeypatch, {"status": "error", "message": "Rejected " + TOKEN}, http_status)
    result = await node({"operation": "list_agents"}).execute({})
    assert result["status"] == "error"
    assert result["http_status"] == http_status
    assert result["error"] == "Rejected [redacted]"


@pytest.mark.parametrize("cfg", [
    {"operation": "list_calls"},
    {"operation": "make_call", "model_id": "agent-1", "phone": "+14155552671"},
    {"operation": "get_phone_number", "phone_number_slug": "14155552671"},
    {"operation": "get_contact", "contact_id": "../outside"},
    {"operation": "get_contact", "contact_id": "a?b"},
])
def test_invalid_config_never_reaches_transport(cfg):
    result = native.SynthflowAiNode.validate_config({"config": cfg, "credentials": {"api_key": TOKEN}})
    assert result["valid"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"response": {"assistants": []}}])
async def test_malformed_success_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "list_agents"}).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_secret_never_leaves_success_envelope(monkeypatch):
    transport(monkeypatch, {"status": "ok", "response": {"echo": TOKEN, "items": [TOKEN]}})
    result = await node({"operation": "list_agents"}).execute({})
    assert TOKEN not in str(result)


@pytest.mark.parametrize("key", ["", " \n", "Bearer abc", "nonascii—key", "https://example.com/key"])
def test_bad_api_keys_are_refused(key):
    with pytest.raises(ValueError):
        native.SynthflowAiAPIKeyCredential(api_key=key)
