"""Exercise Composio's fixed routes, manual credential and response boundaries.

Mock HTTP responses keep all checks independent of accounts and provider effects.
"""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import composio_node as native
from nodes.core.registry import NodeFactory

KEY = "composio-test-key-41"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="composio-test", node_type="automation-composio",
        node_data={"config": config, "credentials": {"api_key": KEY}})


CASES = [
    ({"operation": "list_tools", "toolkit_slug": "github", "query": "issues"}, "GET", "/tools", {"limit": "50", "toolkit_slug": "github", "query": "issues", "include_deprecated": "false"}, None),
    ({"operation": "get_tool", "tool_slug": "GITHUB_GET_ISSUE"}, "GET", "/tools/GITHUB_GET_ISSUE", {}, None),
    ({"operation": "execute_tool", "tool_slug": "GITHUB_GET_ISSUE", "connected_account_id": "ca_test", "user_id": "user-123", "arguments": {"issue_number": 42}}, "POST", "/tools/execute/GITHUB_GET_ISSUE", {}, {"connected_account_id": "ca_test", "user_id": "user-123", "arguments": {"issue_number": 42}, "version": "latest"}),
    ({"operation": "list_toolkits", "search": "github"}, "GET", "/toolkits", {"limit": "50", "search": "github"}, None),
    ({"operation": "get_toolkit", "slug": "github"}, "GET", "/toolkits/github", {"version": "latest"}, None),
    ({"operation": "list_toolkit_categories"}, "GET", "/toolkits/categories", {}, None),
    ({"operation": "list_auth_configs", "cursor": "opaque+cursor="}, "GET", "/auth_configs", {"limit": "50", "cursor": "opaque+cursor=", "show_disabled": "false"}, None),
    ({"operation": "get_auth_config", "auth_config_id": "ac_test"}, "GET", "/auth_configs/ac_test", {}, None),
    ({"operation": "create_auth_config", "toolkit_slug": "github", "name": "Workflow", "scopes": ["repo"]}, "POST", "/auth_configs", {}, {"toolkit": {"slug": "github"}, "auth_config": {"type": "use_composio_managed_auth", "name": "Workflow", "credentials": {"scopes": ["repo"]}}}),
    ({"operation": "delete_auth_config", "auth_config_id": "ac_test"}, "DELETE", "/auth_configs/ac_test", {}, None),
    ({"operation": "list_connected_accounts", "user_ids": ["user-123", "user-456"]}, "GET", "/connected_accounts", {"limit": "50", "user_ids": ["user-123", "user-456"]}, None),
    ({"operation": "get_connected_account", "connected_account_id": "ca_test"}, "GET", "/connected_accounts/ca_test", {}, None),
    ({"operation": "delete_connected_account", "connected_account_id": "ca_test"}, "DELETE", "/connected_accounts/ca_test", {}, None),
    ({"operation": "list_trigger_types"}, "GET", "/triggers_types", {"limit": "50"}, None),
    ({"operation": "get_trigger_type", "slug": "GITHUB_COMMIT_EVENT"}, "GET", "/triggers_types/GITHUB_COMMIT_EVENT", {}, None),
    ({"operation": "list_active_triggers"}, "GET", "/trigger_instances/active", {"limit": "50", "show_disabled": "false"}, None),
    ({"operation": "upsert_trigger", "slug": "GITHUB_COMMIT_EVENT", "connected_account_id": "ca_test", "user_id": "user-123", "trigger_config": {"owner": "octocat"}, "type": "poll", "polling_interval": 5}, "POST", "/trigger_instances/GITHUB_COMMIT_EVENT/upsert", {}, {"connected_account_id": "ca_test", "user_id": "user-123", "trigger_config": {"owner": "octocat"}, "type": "poll", "polling_interval": 5}),
    ({"operation": "update_trigger", "trigger_id": "ti_test", "user_id": "user-123", "status": "disable"}, "PATCH", "/trigger_instances/manage/ti_test", {}, {"user_id": "user-123", "status": "disable"}),
    ({"operation": "delete_trigger", "trigger_id": "ti_test"}, "DELETE", "/trigger_instances/manage/ti_test", {}, None),
]


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body", CASES)
async def test_every_fixed_request(monkeypatch, config, method, path, params, body):
    reply = {"items": [], "next_cursor": "next+page=", "total_items": 1} if config["operation"].startswith("list_") else {"id": "ca_test", "status": "ACTIVE", "success": True}
    requests = transport(monkeypatch, reply)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split("?")[0] == native.BASE_URL + path
    assert request.headers["x-api-key"] == KEY
    assert set(request.url.params) == set(params)
    for name, value in params.items():
        assert request.url.params.get_list(name) == (value if isinstance(value, list) else [value])
    assert (json.loads(request.content) if request.content else None) == body
    if config["operation"].startswith("list_"):
        assert result["next_cursor"] == "next+page=" and result["has_more"]


@pytest.mark.asyncio
async def test_account_evidence_preserves_identity_and_omits_secrets(monkeypatch):
    account = {"id": "ca_test", "alias": "Work GitHub", "status": "ACTIVE", "user_id": "user-123",
        "data": {"access_token": "private-token"}, "state": {"val": {"api_key": "private-key"}}, "params": {"password": "private-password"}}
    transport(monkeypatch, {"items": [account]})
    result = await node({"operation": "list_connected_accounts"}).execute({})
    assert result["items"] == [{k: account[k] for k in ("id", "alias", "status", "user_id")}]
    assert not result["has_more"]
    transport(monkeypatch, account)
    result = await node({"operation": "get_connected_account", "connected_account_id": "ca_test"}).execute({})
    assert result["data"]["status"] == "ACTIVE" and "private-" not in str(result)


@pytest.mark.asyncio
async def test_auth_secret_payload_is_omitted(monkeypatch):
    transport(monkeypatch, {"id": "ac_test", "name": "GitHub", "credentials": {"client_secret": KEY}, "shared_connection_fields": {"private": "value"}})
    result = await node({"operation": "get_auth_config", "auth_config_id": "ac_test"}).execute({})
    assert result["data"] == {"id": "ac_test", "name": "GitHub"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reply", [(401, {"message": "Invalid API key"}), (429, {"message": "Rate limit exceeded"}), (200, {"successful": False, "error": "Tool failed"}), (200, {"success": False, "message": "Delete failed"})])
async def test_provider_failure_is_not_success_or_retried(monkeypatch, status, reply):
    requests = transport(monkeypatch, reply, status)
    with pytest.raises(ValueError, match=reply.get("message") or reply["error"]) as failure:
        await node({"operation": "execute_tool", "tool_slug": "GITHUB_GET_ISSUE", "connected_account_id": "ca_test", "user_id": "user-123"}).execute({})
    assert len(requests) == 1
    if status >= 400:
        assert f"(HTTP {status})" in str(failure.value)


@pytest.mark.asyncio
async def test_no_content_trigger_success_and_invalid_list(monkeypatch):
    transport(monkeypatch, None, 204)
    result = await node({"operation": "upsert_trigger", "slug": "GITHUB_COMMIT_EVENT", "connected_account_id": "ca_test", "user_id": "user-123"}).execute({})
    assert result == {"status": "success", "http_status": 204, "data": None}
    transport(monkeypatch, {"items": "invalid"})
    with pytest.raises(ValueError, match="invalid list envelope"):
        await node({"operation": "list_connected_accounts"}).execute({})


@pytest.mark.parametrize("identifier", ["../tools", "foo/bar", "foo?query=1", "https://example.com", "foo#bar"])
def test_path_inputs_cannot_change_route(identifier):
    with pytest.raises(ValidationError):
        native.GetTool(tool_slug=identifier)


def test_manual_credential_defaults_type_and_trims_key():
    credential = native.ComposioAPIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.model_dump() == {"credential_type": "composio_api_key", "api_key": KEY}
    assert native.ComposioNode.connection_evidence.operation == "list_connected_accounts"
