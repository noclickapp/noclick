"""Exercise the real factory and HTTP transport using synthetic contract fixtures."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import gleap_node as native
from nodes.core.registry import NodeFactory

TOKEN = "gleap-synthetic-token-for-tests"
CASES = json.loads((Path(__file__).parent / "fixtures/gleap/contract-cases.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=True):
    return NodeFactory.create_node(node_id="gleap-test", node_type="automation-gleap", node_data={
        "config": config,
        "credentials": {"credential_type": "gleap_service_account", "api_token": TOKEN} if credential else None})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,status,response", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_contract_routes_bodies_and_responses(monkeypatch, config, method, path, body, status, response):
    calls = transport(monkeypatch, lambda r: httpx.Response(status, json=response) if response is not None else httpx.Response(status))
    result = await node(config).execute({})
    assert result["status"] == "success", result
    assert result["http_status"] == status
    assert len(calls) == 1
    r = calls[0]
    assert r.method == method and r.url.path == path and r.url.host == "api.gleap.io"
    assert r.headers["Authorization"] == "Bearer " + TOKEN
    assert r.headers["Gleap-Version"] == "2026-08-01"
    assert (json.loads(r.content) if r.content else None) == body
    if response is not None:
        assert result["data"] == response
    if status == 202 and response is None:
        assert result["accepted"] and result["completed"] is False
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,parent,cursor", [("list_conversations", "user_id", "cursor"), ("list_messages", "conversation_id", "after")])
async def test_explicit_pagination_is_preserved_without_following(monkeypatch, operation, parent, cursor):
    next_key = "next_cursor" if cursor == "cursor" else "next_after"
    reply = {"items": [], "has_more": True, next_key: "opaque+next/="}
    calls = transport(monkeypatch, lambda r: httpx.Response(200, json=reply))
    result = await node({"operation": operation, parent: "123", cursor: "opaque+previous/=", "limit": 25}).execute({})
    assert result[next_key] == reply[next_key] and result["has_more"]
    assert dict(calls[0].url.params) == {cursor: "opaque+previous/=", "limit": "25"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_path_identifiers_are_single_encoded_segments_and_idempotency_is_explicit(monkeypatch):
    calls = transport(monkeypatch, lambda r: httpx.Response(200, json={"userId": "customer/email@example.com"}))
    assert (await node({"operation": "get_contact", "user_id": "customer/email@example.com"}).execute({}))["status"] == "success"
    assert b"customer%2Femail%40example.com" in calls[0].url.raw_path
    calls = transport(monkeypatch, lambda r: httpx.Response(204))
    await node({"operation": "rate_message", "message_id": "msg_1", "rating": "negative", "idempotency_key": "rating-123"}).execute({})
    assert calls[0].headers["Idempotency-Key"] == "rating-123"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 422, 429, 500])
async def test_problem_details_redaction_rate_limit_and_no_retry(monkeypatch, status):
    calls = transport(monkeypatch, lambda r: httpx.Response(status, json={"title": "Rejected", "detail": "Token " + TOKEN + " rejected", "code": "invalid_token"}, headers={"Location": "https://example.com", "Retry-After": "60"}))
    result = await node({"operation": "list_workflows"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["message"] == "Token [redacted] rejected"
    assert result["retry_after"] == "60" and len(calls) == 1
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": "failure"}, [1], {"id": 3}])
async def test_malformed_success_is_not_evidence(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    assert (await node({"operation": "list_workflows"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_timeout_has_uncertain_write_outcome_and_missing_credential_sends_nothing(monkeypatch):
    def timeout(r):
        raise httpx.ReadTimeout("timed out", request=r)
    calls = transport(monkeypatch, timeout)
    result = await node({"operation": "send_message", "conversation_id": "c", "text": "Hello"}).execute({})
    assert result["status"] == "error" and "may have been accepted" in result["message"]
    assert len(calls) == 1
    with pytest.raises(ValueError, match="Connect a Gleap"):
        await node({"operation": "list_workflows"}, credential=False).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "create_conversation", "user_id": "u", "message": "Hi", "workflowId": "w", "agentId": "a"},
    {"operation": "create_conversation", "user_id": "u", "message": "Hi", "type": "CRASH"},
    {"operation": "update_conversation", "conversation_id": "c"},
    {"operation": "answer_workflow_step", "conversation_id": "c"},
    {"operation": "rate_conversation", "conversation_id": "c", "rating": 11},
    {"operation": "rate_message", "message_id": "m", "rating": "excellent"},
    {"operation": "get_contact", "user_id": ".."},
    {"operation": "send_message", "conversation_id": "c", "text": "Hi", "idempotency_key": "injected\r\nHeader: value"},
    {"operation": "create_webhook", "url": "http://example.com"},
])
def test_provider_constraints(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize("token", ["https://example.com", "Bearer token", "a\r\nb", "<token>"])
def test_token_shape(token):
    with pytest.raises((ValueError, ValidationError)):
        native.GleapServiceAccountCredential(api_token=token)
