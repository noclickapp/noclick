"""Buildkite REST contract tests. These do not claim a live account connection."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from nodes.buildkite_node import (
    BuildkiteNode,
    BuildkiteNodeConfig,
    BuildkiteTokenCredential,
    _request,
    _segment,
)
from wss.handlers.workflow_handler import WorkflowHandler
from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest


def node(operation: str, **fields):
    return BuildkiteNode(
        node_id="buildkite-test",
        node_type="automation-buildkite",
        node_data={},
        config=BuildkiteNodeConfig(
            config={"operation": operation, **fields},
            credentials=BuildkiteTokenCredential(api_token="sample-token"),
        ),
        sio=Mock(),
        sid="test",
        workflow_id="workflow",
        user_id="user",
    )


async def captured_request(operation: str, **fields):
    calls = []

    async def fake(token, method, path, *, params=None, body=None):
        calls.append((token, method, path, params, body))
        return {"status": "success", "data": {"ok": True}}

    with patch("nodes.buildkite_node._request", side_effect=fake):
        result = await node(operation, **fields).execute({})
    assert result["operation"] == operation
    assert result["status"] == "success"
    assert len(calls) == 1
    return calls[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,fields,method,path",
    [
        ("get_user", {}, "GET", "/user"),
        ("list_organizations", {}, "GET", "/organizations"),
        (
            "get_organization",
            {"organization": "my-org"},
            "GET",
            "/organizations/my-org",
        ),
        (
            "list_pipelines",
            {"organization": "my-org"},
            "GET",
            "/organizations/my-org/pipelines",
        ),
        (
            "get_pipeline",
            {"organization": "my-org", "pipeline": "app"},
            "GET",
            "/organizations/my-org/pipelines/app",
        ),
        (
            "archive_pipeline",
            {"organization": "my-org", "pipeline": "app"},
            "POST",
            "/organizations/my-org/pipelines/app/archive",
        ),
        (
            "unarchive_pipeline",
            {"organization": "my-org", "pipeline": "app"},
            "POST",
            "/organizations/my-org/pipelines/app/unarchive",
        ),
        (
            "list_builds",
            {"organization": "my-org", "pipeline": "app"},
            "GET",
            "/organizations/my-org/pipelines/app/builds",
        ),
        (
            "get_build",
            {"organization": "my-org", "pipeline": "app", "build_number": 12},
            "GET",
            "/organizations/my-org/pipelines/app/builds/12",
        ),
        (
            "cancel_build",
            {"organization": "my-org", "pipeline": "app", "build_number": 12},
            "PUT",
            "/organizations/my-org/pipelines/app/builds/12/cancel",
        ),
        (
            "rebuild_build",
            {"organization": "my-org", "pipeline": "app", "build_number": 12},
            "PUT",
            "/organizations/my-org/pipelines/app/builds/12/rebuild",
        ),
        (
            "list_artifacts",
            {"organization": "my-org", "pipeline": "app", "build_number": 12},
            "GET",
            "/organizations/my-org/pipelines/app/builds/12/artifacts",
        ),
        (
            "list_annotations",
            {"organization": "my-org", "pipeline": "app", "build_number": 12},
            "GET",
            "/organizations/my-org/pipelines/app/builds/12/annotations",
        ),
    ],
)
async def test_read_and_action_routes(operation, fields, method, path):
    token, actual_method, actual_path, _, _ = await captured_request(
        operation, **fields
    )
    assert (token, actual_method, actual_path) == ("sample-token", method, path)


@pytest.mark.asyncio
async def test_create_pipeline_and_build_payloads():
    _, method, path, _, body = await captured_request(
        "create_pipeline",
        organization="acme",
        name="Test",
        repository="git@github.com:a/b.git",
        configuration="steps:\n - command: echo ok",
        cluster_id="cluster-1",
        provider_settings_json=(
            '{"trigger_mode":"none","build_branches":false,'
            '"build_pull_requests":false,"build_tags":false}'
        ),
    )
    assert (method, path) == ("POST", "/organizations/acme/pipelines")
    assert body == {
        "name": "Test",
        "repository": "git@github.com:a/b.git",
        "configuration": "steps:\n - command: echo ok",
        "cluster_id": "cluster-1",
        "provider_settings": {
            "trigger_mode": "none",
            "build_branches": False,
            "build_pull_requests": False,
            "build_tags": False,
        },
    }

    _, method, path, _, body = await captured_request(
        "create_build",
        organization="acme",
        pipeline="ci",
        commit="abc123",
        branch="main",
        environment_json='{"TEST": "yes"}',
        metadata_json='{"release": 42}',
    )
    assert (method, path) == ("POST", "/organizations/acme/pipelines/ci/builds")
    assert body == {
        "commit": "abc123",
        "branch": "main",
        "env": {"TEST": "yes"},
        "meta_data": {"release": 42},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["{invalid", "[]"])
async def test_create_pipeline_rejects_invalid_provider_settings_before_request(value):
    with patch("nodes.buildkite_node._request", new_callable=AsyncMock) as request:
        with pytest.raises(ValueError, match="Provider settings must be"):
            await node(
                "create_pipeline",
                organization="acme",
                name="Test",
                repository="https://github.com/buildkite/hello-world.git",
                configuration="steps: []",
                provider_settings_json=value,
            ).execute({})
        request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_requires_actual_fields_and_build_number_is_integer():
    with pytest.raises(ValueError, match="at least one"):
        await captured_request("update_pipeline", organization="acme", pipeline="ci")
    with pytest.raises(ValueError):
        node("get_build", organization="acme", pipeline="ci", build_number="build-uuid")
    _, method, _, _, body = await captured_request(
        "update_pipeline", organization="acme", pipeline="ci", description="new"
    )
    assert method == "PATCH"
    assert body == {"description": "new"}


@pytest.mark.asyncio
async def test_annotation_and_filtered_listing():
    _, _, _, params, _ = await captured_request(
        "list_artifacts",
        organization="acme",
        pipeline="ci",
        build_number=4,
        path="coverage/*",
        state="finished",
    )
    assert params == {"path": "coverage/*", "state": "finished"}
    _, method, path, _, body = await captured_request(
        "create_annotation",
        organization="acme",
        pipeline="ci",
        build_number=4,
        body="## Deployment",
        style="success",
        context="release",
    )
    assert (method, path) == (
        "POST",
        "/organizations/acme/pipelines/ci/builds/4/annotations",
    )
    assert body == {"body": "## Deployment", "style": "success", "context": "release"}


@pytest.mark.asyncio
async def test_org_and_pipeline_picker_use_user_data():
    async def fake(token, method, path, *, params=None, body=None):
        if path == "/organizations":
            return {"status": "success", "data": [{"slug": "acme", "name": "Acme"}]}
        return {"status": "success", "data": [{"slug": "deploy", "name": "Deploy"}]}

    with patch("nodes.buildkite_node._request", side_effect=fake):
        assert await BuildkiteNode.load_field_options(
            "organization", {"api_token": "token"}
        ) == [{"value": "acme", "label": "Acme"}]
        assert await BuildkiteNode.load_field_options(
            "pipeline", {"api_token": "token"}, {"organization": "acme"}
        ) == [{"value": "deploy", "label": "Deploy"}]
        assert (
            await BuildkiteNode.load_field_options("pipeline", {"api_token": "token"})
            == []
        )


@pytest.mark.asyncio
async def test_flowcanvas_dispatcher_loads_buildkite_options_with_current_keywords():
    class Acquire:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *_exc):
            return False

    sio = Mock()
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})
    sio.emit = AsyncMock()
    conn = Mock()
    conn.fetchrow = AsyncMock(return_value={"credential": "sealed"})
    pool = Mock()
    pool.acquire.return_value = Acquire()
    handler = WorkflowHandler(sio)
    handler.get_pool = AsyncMock(return_value=pool)
    encryption = Mock()
    encryption.decrypt_credential.return_value = {"api_token": "sample-token"}
    calls = []

    async def fake_request(token, method, path, *, params=None, body=None):
        calls.append((token, method, path, params, body))
        if path == "/organizations":
            rows = [
                {"slug": "acme", "name": "Acme"},
                {"slug": "example", "name": "Example"},
            ]
        else:
            rows = [
                {"slug": "release", "name": "Release"},
                {"slug": "deploy", "name": "Deploy"},
            ]
        return {"status": "success", "data": rows}

    with (
        patch(
            "wss.handlers.workflow_handler.get_user_org_context",
            new=AsyncMock(return_value="org-1"),
        ),
        patch("wss.handlers.workflow_handler.get_encryption", return_value=encryption),
        patch("nodes.buildkite_node._request", side_effect=fake_request),
    ):
        await handler.load_node_options(
            "sid-1",
            WorkflowNodeLoadOptionsRequest(
                request_id="org-options",
                node_type="automation-buildkite",
                field_name="organization",
                credential_id="credential-1",
                search=" AcM ",
            ),
        )
        org_response = sio.emit.await_args.args[1]["data"]
        assert org_response["success"] is True
        assert org_response["options"] == [
            {"value": "acme", "label": "Acme", "metadata": None}
        ]

        await handler.load_node_options(
            "sid-1",
            WorkflowNodeLoadOptionsRequest(
                request_id="pipeline-options",
                node_type="automation-buildkite",
                field_name="pipeline",
                credential_id="credential-1",
                context={"organization": "acme"},
                search=" release ",
            ),
        )
        pipeline_response = sio.emit.await_args.args[1]["data"]
        assert pipeline_response["success"] is True
        assert pipeline_response["options"] == [
            {"value": "release", "label": "Release", "metadata": None}
        ]

    assert calls == [
        ("sample-token", "GET", "/organizations", None, None),
        (
            "sample-token",
            "GET",
            "/organizations/acme/pipelines",
            {"per_page": 100},
            None,
        ),
    ]


@pytest.mark.asyncio
async def test_http_transport_auth_error_and_204(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/cancel"):
            return httpx.Response(204)
        return httpx.Response(403, json={"message": "Missing write_builds scope"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.buildkite_node.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    error = await _request("secret-token", "GET", "/organizations")
    success = await _request("secret-token", "PUT", "/cancel")
    assert error == {
        "status": "error",
        "status_code": 403,
        "error": "Missing write_builds scope",
    }
    assert success == {
        "status": "success",
        "status_code": 204,
        "data": {"success": True},
    }
    assert seen[0].headers["Authorization"] == "Bearer secret-token"
    assert seen[0].url.host == "api.buildkite.com"


@pytest.mark.asyncio
async def test_http_validation_errors_expose_only_bounded_safe_field_codes(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/plain-error"):
            return httpx.Response(500, text="secret-token and private-repository")
        return httpx.Response(
            422,
            json={
                "message": "Validation Failed for secret-token",
                "errors": [
                    {
                        "field": "cluster_id",
                        "code": "can't be blank",
                        "value": "private",
                    },
                    {
                        "field": "repository",
                        "code": "private-repository is invalid",
                        "submitted_value": "private-repository",
                    },
                    {"field": "bad field", "code": "ignore this"},
                    *[
                        {
                            "field": f"field_{index}",
                            "code": "x" * 300 if index == 0 else "is invalid",
                        }
                        for index in range(10)
                    ],
                ],
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.buildkite_node.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    body = {"repository": "private-repository"}
    error = await _request("secret-token", "POST", "/pipelines", body=body)
    assert error == {
        "status": "error",
        "status_code": 422,
        "error": "Validation Failed for [redacted]",
        "validation_errors": [
            {"field": "cluster_id", "code": "can't be blank"},
            {"field": "repository", "code": "[redacted] is invalid"},
            *[
                {
                    "field": f"field_{index}",
                    "code": "x" * 240 if index == 0 else "is invalid",
                }
                for index in range(3)
            ],
        ],
    }
    assert len(error["validation_errors"][2]["code"]) == 240
    assert "private" not in str(error)
    assert "secret-token" not in str(error)
    assert await _request("secret-token", "POST", "/plain-error", body=body) == {
        "status": "error",
        "status_code": 500,
        "error": "Buildkite returned HTTP 500",
    }


def test_path_segment_escapes_slashes_and_full_urls():
    assert _segment("team/ci") == "team%2Fci"
    assert _segment("https://evil.test") == "https%3A%2F%2Fevil.test"
