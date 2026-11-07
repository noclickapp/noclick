"""Real BugHerd factory, dispatcher, connect, picker and response seams.

Provider I/O is synthetic and does not constitute provider or PostgreSQL proof.
"""
from base64 import b64encode
from contextlib import asynccontextmanager
from copy import deepcopy

import httpx
import pytest
from nodes import bugherd_node as api
from nodes.bugherd_node import BugHerdNode
from nodes.core import credential_connect as cc
from nodes.core import run_op
from nodes.core.registry import NodeFactory

USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
CID = "00000000-0000-4000-8000-000000000042"
KEY = "synthetic-bugherd-key-42A"
CREDENTIAL = {"credential_type": api.FAMILY, "api_key": KEY}
ORG = {
    "id": 81,
    "name": "Owned fixture organization",
    "api_key": KEY,
    "share_url": "https://capability.invalid/private",
}
PROJECT = {
    "id": 7,
    "name": "Owned fixture project",
    "api_key": KEY,
    "members": [
        {
            "id": 9,
            "display_name": "Fixture member",
            "avatar_url": "https://capability.invalid/avatar",
        }
    ],
}
TASK = {
    "id": 29,
    "project_id": 7,
    "local_task_id": 3,
    "title": "Fixture feedback",
    "status": "Custom Review",
    "status_id": 19,
    "secret_link": "https://capability.invalid/secret",
    "screenshot_url": "https://capability.invalid/screen",
    "attachments": ["https://capability.invalid/file"],
    "metadata": {"api_key": KEY},
    "logs": {"private": "unprojected"},
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, client_options = [], []

    def serve(request):
        calls.append(request)
        path = request.url.path
        if path.endswith("/organization.json"):
            return httpx.Response(200, json={"organization": ORG})
        if path.endswith("/projects/7.json"):
            return httpx.Response(200, json={"project": PROJECT})
        if path.endswith("/tasks/29.json"):
            return httpx.Response(200, json={"task": TASK})
        if path.endswith("/tasks/29/comments.json"):
            return httpx.Response(
                200,
                json={
                    "comments": [
                        {"id": 3, "text": "Owned comment", "is_private": True}
                    ],
                    "meta": {"count": 1},
                },
            )
        if path.endswith("/tasks.json"):
            return httpx.Response(200, json={"tasks": [TASK], "meta": {"count": 1}})
        if path.endswith("/projects.json"):
            return httpx.Response(
                200, json={"projects": [PROJECT], "meta": {"count": 1}}
            )
        if path.endswith("/users/members.json"):
            return httpx.Response(
                200, json={"users": [{"id": 9, "display_name": "Fixture member"}]}
            )
        raise AssertionError(f"Unplanned synthetic route {path}")

    @asynccontextmanager
    async def client(**kwargs):
        client_options.append(kwargs)
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as value:
            yield value

    monkeypatch.setattr(api, "guarded_async_client", client)
    return calls, client_options


def native(config, credentials=None, **data):
    return NodeFactory.create_node(
        node_id="fixture-node",
        node_type="automation-bugherd",
        node_data={
            "config": config,
            "credentials": deepcopy(CREDENTIAL if credentials is None else credentials),
            **data,
        },
        user_id=USER,
    )


def test_real_factory_schema_saved_canvas_shape_and_required_fields():
    node = native(
        {
            "operation": "list_tasks",
            "project_id": "7",
            "label": "Owned feedback",
            "_settings": {"retryOnFail": "false"},
        }
    )
    assert node.config.config.project_id == 7
    assert node.get_config_model() is type(node.config)
    schema = node.get_config_schema()
    operations = {
        model["properties"]["operation"]["const"]
        for model in schema["$defs"].values()
        if "operation" in model.get("properties", {})
    }
    assert operations == {
        "get_organization",
        "list_projects",
        "get_project",
        "list_users",
        "list_tasks",
        "get_task",
        "list_comments",
        "list_columns",
        "get_column",
    }
    assert schema["$defs"]["BugHerdApiKeyCredential"]["required"] == ["api_key"]
    assert (
        schema["$defs"]["GetTask"]["properties"]["task_id"]["x-dynamic-options"][
            "depends_on"
        ]
        == "project_id"
    )


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "create_task", "project_id": 7},
        {"operation": "get_task", "project_id": 7},
        {"operation": "list_tasks", "project_id": True},
        {"operation": "list_projects", "page": 0},
        {"operation": "list_projects", "page": 1000001},
        {
            "operation": "list_tasks",
            "project_id": 7,
            "view": "feedback",
            "tag": "ignored",
        },
        {"operation": "list_tasks", "project_id": 7, "updated_since": "2026-01-01"},
    ],
)
def test_closed_native_config_refuses_invalid_contracts(config):
    with pytest.raises(ValueError, match="configuration is invalid"):
        native(config)


@pytest.mark.parametrize(
    "key",
    [
        "unsafe:password",
        "secret with spaces",
        "secret\r\nHeader:value",
        "secret\x00",
        "",
    ],
)
def test_credential_shape_errors_never_echo_submitted_secrets(key):
    with pytest.raises(ValueError) as failure:
        BugHerdNode.validate_credential({"api_key": key})
    assert key not in str(failure.value) if key else True
    assert "input_value" not in str(failure.value)


def test_real_manual_shape_preserves_default_discriminator_and_refuses_foreign_tag():
    shaped, errors, node_type = cc.shape_credential(api.FAMILY, {"api_key": KEY})
    assert not errors and node_type[0] == "automation-bugherd"
    assert shaped == CREDENTIAL
    with pytest.raises(ValueError, match="BugHerd API-key"):
        native(
            {"operation": "get_organization"},
            {"credential_type": "foreign_api_key", "api_key": KEY},
        )


@pytest.mark.asyncio
async def test_real_connect_collector_returns_protected_organization_not_keys(
    monkeypatch, transport
):
    from nodes.core.connection_evidence import collect_evidence

    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    verdict = await cc.validate_for_connect(
        credential_type=api.FAMILY, credential_data={"api_key": KEY}, user_id=USER
    )
    assert verdict.ok and verdict.evidence.reachable is True
    assert verdict.evidence.account_label == ORG["name"]
    assert verdict.verified_metadata()["verified_as"] == ORG["name"]
    assert len(transport[0]) == 1
    assert KEY not in repr(verdict.evidence)


@pytest.mark.asyncio
async def test_real_connect_empty_organization_is_unverified_without_invented_identity(
    monkeypatch, transport
):
    monkeypatch.setitem(ORG, "name", "")
    from nodes.core.connection_evidence import collect_evidence

    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    verdict = await cc.validate_for_connect(
        credential_type=api.FAMILY, credential_data={"api_key": KEY}, user_id=USER
    )
    assert verdict.ok and verdict.evidence.reachable is None
    assert verdict.evidence.account_label is None and verdict.verified_metadata() == {}
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_actual_dispatcher_fixed_basic_header_parent_checks_and_projection(
    transport,
):
    result = await run_op.run_node_operation(
        node_type="automation-bugherd",
        operation="list_comments",
        arguments={"operation": "create_comment", "project_id": 7, "task_id": 29},
        user_id=USER,
        credential_data=CREDENTIAL,
    )
    assert result["organization"] == {"id": 81, "name": ORG["name"]}
    assert result["project_id"] == 7 and result["task_id"] == 29
    assert result["data"][0]["text"] == "Owned comment"
    assert result["pagination_supported"] is False and result["page"] is None
    assert result["complete"] is True
    assert [r.url.path for r in transport[0]] == [
        "/api_v2/organization.json",
        "/api_v2/projects/7.json",
        "/api_v2/projects/7/tasks/29.json",
        "/api_v2/projects/7/tasks/29/comments.json",
    ]
    for request in transport[0]:
        assert request.method == "GET" and request.url.host == "www.bugherd.com"
        assert (
            request.headers["authorization"]
            == "Basic " + b64encode(f"{KEY}:x".encode()).decode()
        )
        assert KEY not in str(request.url)
    assert not transport[0][-1].url.query
    assert all(
        not opts["trust_env"] and not opts["follow_redirects"] for opts in transport[1]
    )


@pytest.mark.asyncio
async def test_task_page_preserves_custom_status_and_explicit_short_page_continuation(
    transport,
):
    result = await native(
        {"operation": "list_tasks", "project_id": 7, "page": 2, "tag": "ui"}
    ).execute({})
    row = result["data"][0]
    assert row["status_id"] == 19 and row["local_task_id"] == 3
    assert (
        result["next_page"] == 3
        and result["complete"] is False
        and result["total_count"] == 1
    )
    assert (
        not {"secret_link", "screenshot_url", "attachments", "metadata", "logs"}
        & row.keys()
    )
    assert KEY not in repr(result) and "capability.invalid" not in repr(result)
    assert dict(transport[0][-1].url.params) == {"page": "2", "tag": "ui"}


@pytest.mark.asyncio
async def test_native_project_and_dependent_task_pickering(transport):
    projects = await BugHerdNode.load_field_options(
        "project_id", CREDENTIAL, {"_user_id": USER}, search="Owned"
    )
    assert projects["options"][0]["value"] == "7" and projects["next_page_token"] == "2"
    tasks = await BugHerdNode.load_field_options(
        "task_id", CREDENTIAL, {"_user_id": USER, "project_id": "7"}, page_token="2"
    )
    assert (
        tasks["options"][0]["value"] == "29"
        and tasks["options"][0]["metadata"]["project_id"] == 7
    )
    before = len(transport[0])
    for context in (
        {"_user_id": USER},
        {"_user_id": USER, "project_id": True},
        {"_user_id": USER, "project_id": "../../7"},
    ):
        with pytest.raises(ValueError, match="explicit project parent"):
            await BugHerdNode.load_field_options("task_id", CREDENTIAL, context)
    assert len(transport[0]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,media,body",
    [
        (401, "application/json", KEY),
        (429, "application/json", KEY),
        (503, "application/json", KEY),
        (302, "application/json", KEY),
        (200, "text/html", KEY),
        (200, "application/json", KEY),
        (200, "application/json", '{"organization":{}}'),
    ],
)
async def test_http_error_media_and_malformed_evidence_are_safe_single_attempt(
    monkeypatch, status, media, body
):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={
                "content-type": media,
                "Retry-After": "Wed, 01 Jan 2030 00:00:00 GMT",
            },
            text=body,
        )

    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as value:
            yield value

    monkeypatch.setattr(api, "guarded_async_client", client)
    with pytest.raises(ValueError) as failure:
        await native({"operation": "get_organization"}).execute({})
    assert KEY not in str(failure.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_strict_parent_projection_missing_counts_nulls_and_negative_known_column_count():
    scope = api.prepare(CREDENTIAL, BugHerdNode.validate_credential)
    with pytest.raises(ValueError, match="outside the requested project"):
        api.page(
            {"tasks": [{**TASK, "project_id": 8}]},
            "tasks",
            api.Task,
            scope,
            project_id=7,
            page_number=1,
        )
    output = api.page(
        {"columns": [{"id": 5, "project_id": 7, "tasks_count": -3}]},
        "columns",
        api.Column,
        scope,
        project_id=7,
    )
    assert (
        output["data"][0]["tasks_count"] == -3
        and output["total_count"] is None
        and output["complete"] is None
    )
    row = api.projected(api.Task, {**TASK, "deleted_at": None}, scope, project_id=7)
    assert row["deleted_at"] is None and "closed_at" not in row
    assert (
        api.page({"tasks": []}, "tasks", api.Task, scope, page_number=8)["next_page"]
        is None
    )
    with pytest.raises(ValueError, match="100-record"):
        api.page(
            {"users": [{"id": value} for value in range(1, 102)]},
            "users",
            api.User,
            scope,
            page_number=1,
        )


@pytest.mark.asyncio
async def test_execute_uses_parsed_credentials_without_trusted_context(transport):
    config = BugHerdNode.parse_config(
        {"config": {"operation": "get_organization"}, "credentials": CREDENTIAL}
    )
    node = BugHerdNode(
        node_id="offline", node_type="automation-bugherd", node_data={}, config=config
    )
    assert (await node.execute({}))["data"]["id"] == ORG["id"]
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_missing_credentials_fail_before_transport(transport):
    config = BugHerdNode.parse_config({"config": {"operation": "get_organization"}})
    node = BugHerdNode(
        node_id="offline", node_type="automation-bugherd", node_data={}, config=config
    )
    with pytest.raises(ValueError, match="Connect a BugHerd API key"):
        await node.execute({})
    assert not transport[0]
