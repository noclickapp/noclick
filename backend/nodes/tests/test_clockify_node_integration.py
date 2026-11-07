"""Contract tests for the Clockify node's user, project, and time-entry operations."""

import pytest
from pydantic import ValidationError

from nodes.clockify_node import (
    ClockifyApiKeyCredential,
    ClockifyNode,
    ClockifyNodeConfig,
)


CREDENTIAL = {"api_key": "test-secret", "api_domain": "euc1.clockify.me"}


def make_node(operation: str, **fields):
    config = ClockifyNodeConfig.model_validate(
        {
            "config": {"operation": operation, **fields},
            "credentials": CREDENTIAL,
        }
    )
    return ClockifyNode("test", "automation-clockify", {}, config=config)


@pytest.mark.asyncio
async def test_account_and_workspace_evidence(monkeypatch):
    calls = []

    async def request(credential, method, path, **kwargs):
        calls.append((credential.api_domain, method, path))
        return (
            [{"id": "w1", "name": "Design"}]
            if path == "/workspaces"
            else {"id": "u1", "name": "Ada"}
        )

    monkeypatch.setattr(ClockifyNode, "_request", staticmethod(request))
    options = await ClockifyNode.load_field_options("workspace_id", CREDENTIAL)
    assert options == {"options": [{"value": "w1", "label": "Design"}]}
    assert (await make_node("get_current_user").execute({}))["data"]["result"][
        "name"
    ] == "Ada"
    assert (await make_node("list_workspaces").execute({}))["data"]["workspaces"][0][
        "name"
    ] == "Design"
    assert calls == [
        ("euc1.clockify.me", "GET", "/workspaces"),
        ("euc1.clockify.me", "GET", "/user"),
        ("euc1.clockify.me", "GET", "/workspaces"),
    ]


@pytest.mark.asyncio
async def test_project_and_time_entry_requests(monkeypatch):
    calls = []

    async def request(credential, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"id": "u1"} if path == "/user" else {"id": "created"}

    monkeypatch.setattr(ClockifyNode, "_request", staticmethod(request))
    await make_node(
        "create_project", workspace_id="w1", name="Launch", billable=False
    ).execute({})
    await make_node(
        "create_time_entry",
        workspace_id="w1",
        start="2026-09-29T09:00:00Z",
        project_id="p1",
        description="Build",
        custom_fields_json='[{"customFieldId":"cf","value":"x"}]',
    ).execute({})
    await make_node("list_time_entries", workspace_id="w1", project_id="p1").execute({})
    await make_node(
        "stop_timer", workspace_id="w1", end="2026-09-29T10:00:00Z"
    ).execute({})
    assert calls[0] == (
        "POST",
        "/workspaces/w1/projects",
        {"body": {"name": "Launch", "billable": False}},
    )
    assert calls[1][0:2] == ("POST", "/workspaces/w1/time-entries")
    assert calls[1][2]["body"]["customFields"] == [
        {"customFieldId": "cf", "value": "x"}
    ]
    assert calls[3] == (
        "GET",
        "/workspaces/w1/user/u1/time-entries",
        {"params": {"page": 1, "page-size": 50, "project": "p1"}},
    )
    assert calls[5] == (
        "PATCH",
        "/workspaces/w1/user/u1/time-entries",
        {"body": {"end": "2026-09-29T10:00:00Z"}},
    )


def test_domain_and_id_are_constrained():
    assert (
        ClockifyApiKeyCredential(
            api_key="x", api_domain="  EUC1.Clockify.Me "
        ).api_domain
        == "euc1.clockify.me"
    )
    for domain in (
        "localhost",
        "api.clockify.me.attacker.test",
        "evil.com",
        "foo/bar.clockify.me",
    ):
        with pytest.raises(ValidationError):
            ClockifyApiKeyCredential(api_key="x", api_domain=domain)
    with pytest.raises(ValueError):
        from nodes.clockify_node import _id

        _id("foo/bar")


@pytest.mark.asyncio
async def test_http_contract_uses_key_header_and_regional_host(respx_mock):
    import httpx

    route = respx_mock.get("https://euc1.clockify.me/api/v1/workspaces").mock(
        return_value=httpx.Response(200, json=[{"id": "w1", "name": "Design"}])
    )
    result = await make_node("list_workspaces").execute({})
    assert result["status"] == "success"
    assert result["data"]["workspaces"] == [{"id": "w1", "name": "Design"}]
    assert route.called
    assert route.calls[0].request.headers["X-Api-Key"] == "test-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation, fields, method, path, payload",
    [
        (
            "list_clients",
            {"workspace_id": "w1", "name": "Acme"},
            "GET",
            "/workspaces/w1/clients",
            {"params": {"page": 1, "page-size": 50, "name": "Acme"}},
        ),
        (
            "create_client",
            {"workspace_id": "w1", "name": "Acme", "email": "a@example.com"},
            "POST",
            "/workspaces/w1/clients",
            {"body": {"name": "Acme", "email": "a@example.com"}},
        ),
        (
            "list_tags",
            {"workspace_id": "w1"},
            "GET",
            "/workspaces/w1/tags",
            {"params": {"page": 1, "page-size": 50}},
        ),
        (
            "create_tag",
            {"workspace_id": "w1", "name": "Sprint"},
            "POST",
            "/workspaces/w1/tags",
            {"body": {"name": "Sprint"}},
        ),
        (
            "list_tasks",
            {"workspace_id": "w1", "project_id": "p1"},
            "GET",
            "/workspaces/w1/projects/p1/tasks",
            {"params": {"page": 1, "page-size": 50}},
        ),
        (
            "create_task",
            {"workspace_id": "w1", "project_id": "p1", "name": "Build"},
            "POST",
            "/workspaces/w1/projects/p1/tasks",
            {"body": {"name": "Build"}},
        ),
    ],
)
async def test_client_tag_and_task_routes(
    monkeypatch, operation, fields, method, path, payload
):
    calls = []

    async def request(credential, actual_method, actual_path, **kwargs):
        calls.append((actual_method, actual_path, kwargs))
        return {"id": "created"}

    monkeypatch.setattr(ClockifyNode, "_request", staticmethod(request))
    result = await make_node(operation, **fields).execute({})
    assert result["status"] == "success"
    assert calls == [(method, path, payload)]
