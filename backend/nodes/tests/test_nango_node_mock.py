"""Verify Nango requests through the workflow factory, without provider traffic."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

import nodes.nango_node as nango
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "nango_api_key", "api_key": "synthetic-environment-key"}
USER = UUID("00000000-0000-0000-0000-000000000001")
INTEGRATION = json.loads((Path(__file__).parent / "fixtures/nango/integration.json").read_text())
CONNECTION = {"provider_config_key": "github-nango", "connection_id": "connection-123"}


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.nango.dev"
        assert request.headers["authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, body = replies.pop(0)
        if isinstance(body, bytes):
            return httpx.Response(code, content=body, headers={"Content-Type": "text/html"})
        return httpx.Response(code, json=body)
    monkeypatch.setattr(nango, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-nango", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(AUTH), user_id=USER)


CASES = [
    ("list_integrations", {}, "GET", "/integrations", {"data": []}),
    ("get_integration", {"unique_key": "github-nango"}, "GET", "/integrations/github-nango", INTEGRATION),
    ("create_integration", {"unique_key": "github-nango", "provider": "github"}, "POST", "/integrations", INTEGRATION),
    ("update_integration", {"unique_key": "github-nango", "display_name": "GitHub"}, "PATCH", "/integrations/github-nango", INTEGRATION),
    ("delete_integration", {"unique_key": "github-nango"}, "DELETE", "/integrations/github-nango", {"success": True}),
    ("list_functions", {"unique_key": "github-nango", "page": 2, "limit": 10, "type": "sync"}, "GET", "/integrations/github-nango/functions", {"data": [], "pagination": {"page": 2, "limit": 10, "total": 20}}),
    ("list_connections", {"connection_id": "connection-123", "page": 2}, "GET", "/connections", {"connections": []}),
    ("get_connection", CONNECTION, "GET", "/connections/connection-123", {**CONNECTION, "credentials": {"apiKey": "never-escape", "type": "API_KEY"}, "metadata": {}}),
    ("update_connection", {**CONNECTION, "tags": {"team": "sales"}}, "PATCH", "/connections/connection-123", {"success": True}),
    ("delete_connection", CONNECTION, "DELETE", "/connections/connection-123", {"success": True}),
    ("set_connection_metadata", {**CONNECTION, "metadata": {"team": "sales"}}, "POST", "/connections/metadata", {**CONNECTION, "metadata": {"team": "sales"}}),
    ("update_connection_metadata", {**CONNECTION, "metadata": {"team": "sales"}}, "PATCH", "/connections/metadata", {**CONNECTION, "metadata": {"team": "sales"}}),
    ("get_records", {**CONNECTION, "model": "Issue", "cursor": "next-page"}, "GET", "/records", {"records": [{"id": "issue-1"}], "next_cursor": "another-page"}),
    ("trigger_sync", {**CONNECTION, "syncs": ["github-issues"]}, "POST", "/sync/trigger", {"success": True}),
    ("start_sync", {**CONNECTION, "syncs": ["github-issues"]}, "POST", "/sync/start", {"success": True}),
    ("pause_sync", {**CONNECTION, "syncs": ["github-issues"]}, "POST", "/sync/pause", {"success": True}),
    ("get_sync_status", CONNECTION, "GET", "/sync/status", {"syncs": []}),
    ("trigger_action", {**CONNECTION, "action_name": "create-issue", "input": {"title": "New issue"}, "asynchronous": True}, "POST", "/action/trigger", {"id": "action-123", "statusUrl": "/action/action-123"}),
    ("get_action_result", {"action_id": "action-123"}, "GET", "/action/action-123", {"id": "issue-1"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path,response", CASES)
async def test_all_operations_use_one_contract_request(transport, operation, args, method, path, response):
    requests, replies = transport
    replies.append((200, response))
    result = await run(operation, args)
    assert len(requests) == 1
    req = requests[0]
    assert (req.method, req.url.path) == (method, path)
    assert "never-escape" not in json.dumps(result)
    if operation in {"get_connection", "delete_connection", "update_connection"}:
        assert req.url.params["provider_config_key"] == "github-nango"
    if operation in {"get_records", "trigger_action"}:
        assert req.headers["Connection-Id"] == "connection-123"
        assert req.headers["Provider-Config-Key"] == "github-nango"
    if operation in {"trigger_sync", "start_sync", "pause_sync"}:
        assert json.loads(req.content) == {**CONNECTION, "syncs": ["github-issues"]}
    if operation == "trigger_action":
        assert req.headers["X-Async"] == "true"
        assert json.loads(req.content) == {"action_name": "create-issue", "input": {"title": "New issue"}}
        assert result == response  # scheduling is not completion
    if operation == "list_connections":
        assert req.url.params["connectionId"] == "connection-123"
        assert req.url.params["page"] == "2"
    if operation == "get_records":
        assert req.url.params["cursor"] == "next-page"
        assert result["next_cursor"] == "another-page"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,payload", [(401, {"error": "invalid key"}), (403, {"error": "scope denied"}), (429, {"error": "rate limited"}), (302, b"redirect"), (200, b"login"), (200, {"error": "rejected"}), (200, {}), (200, [])])
async def test_errors_and_malformed_evidence_fail(transport, code, payload):
    transport[1].append((code, payload))
    with pytest.raises(ValueError):
        await run("list_integrations")
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_false_write_acknowledgement_is_not_success(transport):
    transport[1].append((200, {"success": False}))
    with pytest.raises(ValueError, match="rejected"):
        await run("pause_sync", {**CONNECTION, "syncs": ["github-issues"]})


@pytest.mark.asyncio
async def test_secrets_are_redacted_in_errors_and_responses(transport):
    transport[1].append((401, {"message": AUTH["api_key"]}))
    with pytest.raises(ValueError) as error:
        await run("list_integrations")
    assert AUTH["api_key"] not in str(error.value)
    transport[1].append((200, {"data": [{"display_name": AUTH["api_key"], "credentials": {"private_key": "hidden"}}]}))
    result = await run("list_integrations")
    assert AUTH["api_key"] not in json.dumps(result) and "hidden" not in json.dumps(result)


@pytest.mark.asyncio
async def test_dates_serialized_as_rfc3339(transport):
    transport[1].append((200, {"records": [], "next_cursor": None}))
    await run("get_records", {**CONNECTION, "model": "Issue", "modified_after": "2023-05-31T11:46:13.390Z"})
    assert transport[0][0].url.params["modified_after"].startswith("2023-05-31T11:46:13.390")
    with pytest.raises(ValidationError):
        nango.GetRecordsConfig(**CONNECTION, model="Issue", modified_after="tomorrow")


@pytest.mark.asyncio
async def test_ids_cannot_change_request_authority(transport):
    transport[1].append((200, INTEGRATION))
    await run("get_integration", {"unique_key": "https://elsewhere.test/a?b"})
    assert str(transport[0][0].url).startswith("https://api.nango.dev/integrations/https%3A%2F%2Felsewhere.test%2Fa%3Fb")
    with pytest.raises(ValueError):
        await run("get_integration", {"unique_key": ".."})
    assert len(transport[0]) == 1


def test_manual_credential_has_a_default_type_and_only_one_input():
    credential = nango.NangoAPIKeyCredential(api_key=AUTH["api_key"])
    assert credential.credential_type == "nango_api_key"
    assert nango.NangoAPIKeyCredential.model_json_schema()["required"] == ["api_key"]
    with pytest.raises(ValidationError):
        nango.NangoAPIKeyCredential(api_key="Bearer value")
