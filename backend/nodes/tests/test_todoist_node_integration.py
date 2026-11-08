"""Todoist API v1 OAuth, operation, picker, and request contracts."""

import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx

from nodes.oauth.todoist_oauth import OAUTH_PROVIDER, refresh_access_token
from nodes.todoist_node import (
    CONFIG_MODELS, OPERATIONS, TODOIST_SCOPES, TodoistAPITokenCredential,
    TodoistNode, TodoistNodeConfig, TodoistOAuthCredential, TodoistOnNewTaskConfig,
)


def node(operation: str, *, oauth: bool = False, **values) -> TodoistNode:
    credential = (TodoistOAuthCredential(access_token="access", refresh_token="refresh",
                                        expires_at="2099-01-01T00:00:00Z") if oauth else
                  TodoistAPITokenCredential(api_token="personal"))
    return TodoistNode(
        node_id="todoist-test", node_type="automation-todoist", node_data={},
        config=TodoistNodeConfig(config=(TodoistOnNewTaskConfig(**values) if operation == "on_new_task"
                                         else CONFIG_MODELS[operation](**values)), credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
async def test_oauth_code_exchange_and_rotating_refresh(monkeypatch):
    monkeypatch.setenv("TODOIST_CLIENT_ID", "client")
    monkeypatch.setenv("TODOIST_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.todoist.com/oauth/access_token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "one", "refresh_token": "rotate-1",
                                      "expires_in": 3600, "scope": "data:read_write"}),
            httpx.Response(200, json={"access_token": "two", "refresh_token": "rotate-2",
                                      "expires_in": 3600, "scope": "data:read_write"}),
        ])
        router.get("https://api.todoist.com/api/v1/user").mock(
            return_value=httpx.Response(200, json={"full_name": "Example User"}))
        first, name = await OAUTH_PROVIDER.exchange("code", "https://noclick.com/api/auth/oauth/todoist/callback")
        assert name == "Example User"
        second = await refresh_access_token(first.refresh_token)
    assert first.refresh_token == "rotate-1"
    assert second.refresh_token == "rotate-2"
    assert route.call_count == 2
    assert "client_id=client" in route.calls[0].request.content.decode()
    assert "grant_type=authorization_code" in route.calls[0].request.content.decode()
    assert "grant_type=refresh_token" in route.calls[1].request.content.decode()
    assert "refresh_token=rotate-1" in route.calls[1].request.content.decode()


@pytest.mark.asyncio
async def test_new_oauth_connection_requires_rotating_refresh_token(monkeypatch):
    monkeypatch.setenv("TODOIST_CLIENT_ID", "client")
    monkeypatch.setenv("TODOIST_CLIENT_SECRET", "secret")
    with respx.mock:
        respx.post("https://api.todoist.com/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "long-lived", "expires_in": 315360000}))
        respx.get("https://api.todoist.com/api/v1/user").mock(
            return_value=httpx.Response(200, json={"full_name": "Example User"}))
        with pytest.raises(ValueError, match="single-use"):
            await OAUTH_PROVIDER.exchange("code", "https://noclick.com/callback")


@pytest.mark.asyncio
async def test_missing_rotated_refresh_token_is_rejected(monkeypatch):
    monkeypatch.setenv("TODOIST_CLIENT_ID", "client")
    monkeypatch.setenv("TODOIST_CLIENT_SECRET", "secret")
    with respx.mock:
        respx.post("https://api.todoist.com/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 3600}))
        with pytest.raises(ValueError, match="single-use"):
            await refresh_access_token("consumed")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,method,path,body", [
    ("get_user", {}, "GET", "/user", None),
    ("list_projects", {"limit": 20}, "GET", "/projects", None),
    ("search_projects", {"query": "Roadmap"}, "GET", "/projects/search", None),
    ("create_project", {"name": "Roadmap", "is_favorite": True}, "POST", "/projects",
     {"name": "Roadmap", "is_favorite": True}),
    ("create_section", {"project_id": "6Xabc", "name": "Planning"}, "POST", "/sections",
     {"name": "Planning", "project_id": "6Xabc"}),
    ("list_tasks", {"project_id": "6Xabc"}, "GET", "/tasks", None),
    ("filter_tasks", {"query": "today | overdue"}, "GET", "/tasks/filter", None),
    ("create_task", {"content": "Ship launch", "project_id": "6Xabc",
                     "due_string": "tomorrow", "labels_json": '["work","urgent"]', "priority": 4},
     "POST", "/tasks", {"content": "Ship launch", "project_id": "6Xabc",
                          "due_string": "tomorrow", "labels": ["work", "urgent"], "priority": 4}),
    ("update_task", {"task_id": "6Xtask", "content": "Ship next week"},
     "POST", "/tasks/6Xtask", {"content": "Ship next week"}),
    ("move_task", {"task_id": "6Xtask", "section_id": "6Xsection"},
     "POST", "/tasks/6Xtask/move", {"section_id": "6Xsection"}),
    ("close_task", {"task_id": "6Xtask"}, "POST", "/tasks/6Xtask/close", {}),
    ("delete_task", {"task_id": "6Xtask"}, "DELETE", "/tasks/6Xtask", None),
    ("create_label", {"name": "urgent"}, "POST", "/labels", {"name": "urgent"}),
    ("create_comment", {"content": "Looks good", "task_id": "6Xtask"},
     "POST", "/comments", {"content": "Looks good", "task_id": "6Xtask"}),
])
async def test_api_request(operation, values, method, path, body):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, "https://api.todoist.com/api/v1" + path).mock(
            return_value=httpx.Response(204) if operation in {"close_task", "delete_task"} else
            httpx.Response(200, json={"id": "6Xresult"}))
        result = await node(operation, **values).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer personal"
    if body is not None:
        assert json.loads(request.content) == body
    if operation == "list_projects":
        assert request.url.params["limit"] == "20"
    if operation == "filter_tasks":
        assert request.url.params["query"] == "today | overdue"
    assert result["status"] == "success"
    assert result["data"] == ({"ok": True} if operation in {"close_task", "delete_task"}
                              else {"id": "6Xresult"})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,path,field,expected", [
    ("create_project", {"name": "Vacation Planning", "workspace_id": "123456"},
     "/projects", "workspace_id", 123456),
    ("update_project", {"project_id": "6XGgm6PHrGgMpCFX", "folder_id": "123456"},
     "/projects/6XGgm6PHrGgMpCFX", "folder_id", 123456),
    ("create_task", {"content": "Buy milk", "assignee_id": "123456789"},
     "/tasks", "assignee_id", 123456789),
    ("update_task", {"task_id": "6XGgmFVcrG5RRjVr", "assignee_id": "123456789"},
     "/tasks/6XGgmFVcrG5RRjVr", "assignee_id", 123456789),
])
async def test_numeric_ids_are_sent_as_json_integers(monkeypatch, operation, values, path, field, expected):
    # The pinned Todoist OpenAPI contract requires these body IDs to be integers.
    # String values from workflow configuration must be normalized before sending.
    request = AsyncMock()
    monkeypatch.setattr(TodoistNode, "_request", request)
    await node(operation, **values).execute({})
    assert request.await_args.args == ("personal", "POST", path)
    value = request.await_args.kwargs["body"][field]
    assert type(value) is int
    assert value == expected


@pytest.mark.asyncio
async def test_dynamic_project_and_section_pickers():
    with respx.mock(assert_all_called=True) as router:
        projects = router.get("https://api.todoist.com/api/v1/projects/search").mock(
            return_value=httpx.Response(200, json={"results": [{"id": "6Xabc", "name": "Roadmap"}],
                                                     "next_cursor": "next"}))
        sections = router.get("https://api.todoist.com/api/v1/sections").mock(
            return_value=httpx.Response(200, json={"results": [{"id": "6Xsec", "name": "Planning"}]}))
        found = await TodoistNode.load_field_options("project_id", {"api_token": "personal"}, search="Roadmap")
        child = await TodoistNode.load_field_options(
            "section_id", {"api_token": "personal"}, context={"config": {"project_id": "6Xabc"}})
    assert projects.calls[0].request.url.params["query"] == "Roadmap"
    assert found == {"options": [{"value": "6Xabc", "label": "Roadmap"}], "next_page_token": "next"}
    assert sections.calls[0].request.url.params["project_id"] == "6Xabc"
    assert child["options"] == [{"value": "6Xsec", "label": "Planning"}]


@pytest.mark.asyncio
async def test_new_task_trigger_paginates_and_emits_only_unseen():
    trigger = node("on_new_task", project_id="6Xproject")
    trigger._filter_unseen = AsyncMock(return_value=[{"id": "6Xnew", "content": "Review"}])
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://api.todoist.com/api/v1/tasks").mock(side_effect=[
            httpx.Response(200, json={"results": [{"id": "6Xold", "content": "Old"}],
                                      "next_cursor": "next"}),
            httpx.Response(200, json={"results": [{"id": "6Xnew", "content": "Review"}],
                                      "next_cursor": None}),
        ])
        result = await trigger.execute({})
    assert route.call_count == 2
    assert route.calls[0].request.url.params["project_id"] == "6Xproject"
    assert route.calls[1].request.url.params["cursor"] == "next"
    assert result == {"tasks": [{"id": "6Xnew", "content": "Review"}], "new_task_count": 1}
    assert TodoistNode.should_propagate_output(result, {"operation": "on_new_task"})
    assert not TodoistNode.should_propagate_output(
        {"tasks": [], "new_task_count": 0}, {"operation": "on_new_task"})
    assert "Review" in TodoistNode.resolve_agent_event(result)["text"]
    assert TodoistNode.resolve_agent_event({"tasks": []}) is None


@pytest.mark.asyncio
async def test_api_error_and_invalid_labels_are_visible():
    with respx.mock:
        respx.get("https://api.todoist.com/api/v1/user").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"}))
        with pytest.raises(ValueError, match="Todoist API error 401: Unauthorized"):
            await node("get_user").execute({})
    with pytest.raises(ValueError, match="Labels JSON must be an array of names"):
        await node("create_task", content="Task", labels_json='{"bad":true}').execute({})


def test_all_operations_in_schema_and_scoped():
    assert len(OPERATIONS) == 39
    schema = TodoistNode.get_config_schema()
    for name, model in CONFIG_MODELS.items():
        assert model.__name__ in schema["$defs"]
        assert TODOIST_SCOPES.require(name) is not None
    assert "TodoistOnNewTaskConfig" in schema["$defs"]
    assert TODOIST_SCOPES.require("on_new_task") is not None
    assert set(schema["$defs"]["TodoistOAuthCredential"]["x-oauth-scopes"]) == {
        "data:read_write", "data:delete", "project:delete"}
    assert schema["$defs"]["TodoistAPITokenCredential"]["properties"]["api_token"]["ui:widget"] == "password"


@pytest.mark.asyncio
async def test_execute_adopts_refreshed_tokens(monkeypatch):
    instance = node("get_user", oauth=True)

    async def fresh_token(**kwargs):
        assert kwargs["provider"] == "todoist"
        assert kwargs["caller_path"] == "execute"
        kwargs["credential"].update(
            access_token="next-access", refresh_token="next-refresh",
            expires_at="2099-02-01T00:00:00Z",
        )
        return "next-access"

    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", fresh_token)
    request = AsyncMock(return_value={"full_name": "Example User"})
    monkeypatch.setattr(TodoistNode, "_request", request)
    await instance.execute({})
    assert request.await_args.args[0] == "next-access"
    assert instance.config.credentials.refresh_token == "next-refresh"
    assert instance.config.credentials.access_token == "next-access"


def test_oauth_declaration_matches_scope_wire_format():
    assert OAUTH_PROVIDER.scope_separator == ","
    assert OAUTH_PROVIDER.rotates_refresh_tokens
    assert OAUTH_PROVIDER.scopes == TODOIST_SCOPES.declared_scopes()
    tokens, _ = OAUTH_PROVIDER.parse_tokens(httpx.Response(200, json={
        "access_token": "access", "refresh_token": "refresh",
        "scope": "data:read_write,data:delete,project:delete",
    }))
    assert set(tokens.scope.split()) == set(TODOIST_SCOPES.declared_scopes())
