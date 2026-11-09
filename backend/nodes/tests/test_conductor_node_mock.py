"""Exercise Conductor's real factory with a synthetic API transport.

These regressions cover authentication evidence, pagination, message delivery
acknowledgments and uncertain writes without using a provider account.
"""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import conductor_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-conductor-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="conductor-fixture", node_type="automation-conductor",
        node_data={"config": config, "credentials": {"credential_type": "conductor_api_key", "api_key": KEY}})


def mock_api(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.conductor.build"
        assert request.headers["Authorization"] == "Bearer " + KEY
        assert request.headers["User-Agent"] == "NoClick-Conductor/1.0"
        return reply(request)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_conductor_account_identity_evidence(monkeypatch):
    requests = mock_api(monkeypatch, lambda _: httpx.Response(200, json={"userId": "user-1", "email": "owner@example.test", "authMethod": "api-key"}))
    result = await node({"operation": "get_identity"}).execute({})
    assert result["status"] == "success" and result["data"]["userId"] == "user-1"
    assert requests[0].url.path == "/me" and len(requests) == 1
    assert native.ConductorNode.connection_evidence.identity_operation == "get_identity"


@pytest.mark.asyncio
async def test_conductor_workspace_filters_and_page_continuation(monkeypatch):
    requests = mock_api(monkeypatch, lambda _: httpx.Response(200, json={"data": [{"id": "workspace-1", "name": "Repair checkout"}], "offset": 50, "hasMore": True}))
    result = await node({"operation": "list_workspaces", "limit": 1, "offset": 50, "include_archived": True, "name": "Repair checkout"}).execute({})
    assert dict(requests[0].url.params) == {"limit": "1", "offset": "50", "includeArchived": "true", "name": "Repair checkout"}
    assert result["has_more"] is True and result["next_offset"] == 51
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_conductor_transcript_polling_omits_offset(monkeypatch):
    requests = mock_api(monkeypatch, lambda _: httpx.Response(200, json={"data": [], "offset": 0, "hasMore": False}))
    result = await node({"operation": "list_messages", "session_id": "session-1", "after": "message-1"}).execute({})
    assert requests[0].url.path == "/v0/sessions/session-1/messages"
    assert dict(requests[0].url.params) == {"limit": "50", "after": "message-1"}
    assert result["next_offset"] is None
    with pytest.raises(ValidationError):
        native.ConductorListMessagesConfig(session_id="session-1", after="message-1", offset=1)


@pytest.mark.asyncio
async def test_conductor_create_workspace_and_initial_message_are_not_retried(monkeypatch):
    reply = {"id": "workspace-1", "sessionId": "session-1", "deepLink": "conductor://workspace-1", "initialMessage": {"id": "message-1", "status": "queued"}}
    requests = mock_api(monkeypatch, lambda _: httpx.Response(201, json=reply))
    result = await node({"operation": "create_workspace", "project_id": "project-1", "name": "Repair checkout", "message": "Fix the checkout failure"}).execute({})
    assert requests[0].method == "POST" and requests[0].url.path == "/v0/workspaces"
    assert json.loads(requests[0].content) == {"projectId": "project-1", "name": "Repair checkout", "message": "Fix the checkout failure"}
    assert result["data"] == reply and len(requests) == 1


@pytest.mark.asyncio
async def test_conductor_message_deduplication_id_and_queued_ack_preserved(monkeypatch):
    uid = "a529ba41-057f-4093-8e50-d95c0a8091cd"
    reply = {"id": uid, "status": "queued"}
    requests = mock_api(monkeypatch, lambda _: httpx.Response(200, json=reply))
    result = await node({"operation": "send_message", "session_id": "session-1", "message": "Inspect the failing test", "message_id": uid}).execute({})
    assert json.loads(requests[0].content) == {"message": "Inspect the failing test", "messageId": uid}
    assert result["data"] == reply and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", [("archive_workspace", "/v0/workspaces/workspace-1/archive"), ("cancel_session", "/v0/sessions/session-1/cancel")])
async def test_conductor_bodyless_lifecycle_actions_preserve_ack(monkeypatch, operation, route):
    requests = mock_api(monkeypatch, lambda _: httpx.Response(200, json={"success": True}))
    result = await node({"operation": operation, "workspace_id" if "workspace" in operation else "session_id": "workspace-1" if "workspace" in operation else "session-1"}).execute({})
    assert requests[0].url.path == route and requests[0].method == "POST" and requests[0].content == b""
    assert result["data"] == {"success": True} and "completed" not in result


@pytest.mark.asyncio
async def test_conductor_rejection_preserves_provider_words_redacts_key(monkeypatch):
    requests = mock_api(monkeypatch, lambda _: httpx.Response(403, json={"userMessage": "Project access denied for " + KEY}))
    result = await node({"operation": "get_project", "project_id": "project-1"}).execute({})
    assert result["status_code"] == 403 and result["error"] == "Project access denied for [redacted]"
    assert KEY not in str(result) and len(requests) == 1
    from nodes.core.connection_evidence import _ProviderRefused, _raise_if_error_envelope
    with pytest.raises(_ProviderRefused, match="HTTP 403"):
        _raise_if_error_envelope(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "server", "html", "malformed"])
async def test_conductor_uncertain_writes_never_retry_or_claim_success(monkeypatch, failure):
    def reply(request):
        if failure == "timeout":
            raise httpx.ReadTimeout(KEY, request=request)
        if failure == "server":
            return httpx.Response(503, json={"userMessage": "Unavailable"})
        if failure == "html":
            return httpx.Response(200, text="<html>Proxy</html>")
        return httpx.Response(200, json=[])
    requests = mock_api(monkeypatch, reply)
    result = await node({"operation": "rename_workspace", "workspace_id": "workspace-1", "name": "New name"}).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown" and KEY not in str(result)
    assert len(requests) == 1


@pytest.mark.parametrize("identifier", ["..", "other/path", "a?query", "a#fragment", "a%2fb"])
def test_conductor_ids_cannot_change_route(identifier):
    with pytest.raises(ValidationError):
        native.ConductorGetWorkspaceConfig(workspace_id=identifier)


@pytest.mark.parametrize("key", ["Bearer abc", "https://example.test/key", "abc\nsecret"])
def test_conductor_credentials_accept_only_pasted_key(key):
    with pytest.raises(ValidationError):
        native.ConductorAPIKeyCredential(api_key=key)
