"""Contract and request tests for Render's public JSON API node."""

import json
from typing import get_args
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from nodes.render_node import (
    RENDER_OPERATIONS,
    RenderAPIKeyCredential,
    RenderConfig,
    RenderCreateDeployConfig,
    RenderGetUserConfig,
    RenderListLogsConfig,
    RenderListServicesConfig,
    RenderNode,
    RenderNodeConfig,
    RenderRetrieveServiceConfig,
    _render_request,
)


KEY = "rnd_test_secret"


def make_node(config):
    return RenderNode(
        node_id="render-test",
        node_type="automation-render",
        node_data={},
        config=RenderNodeConfig(
            config=config, credentials=RenderAPIKeyCredential(api_key=KEY)
        ),
        sio=Mock(),
        sid="sid",
        workflow_id="wf",
        user_id="user",
    )


def fake_http_response(status, data):
    response = httpx.Response(status, json=data)
    session = MagicMock()
    session.request = AsyncMock(return_value=response)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


def test_every_supported_operation_has_a_discriminated_config():
    members = get_args(get_args(RenderConfig)[0])
    names = [model.model_fields["operation"].default for model in members]
    assert len(names) == 216
    assert len(names) == len(set(names))
    assert set(names) == set(RENDER_OPERATIONS)
    assert all(
        model.model_fields["operation"].json_schema_extra["ui:hidden"]
        for model in members
    )
    assert {
        "list_services",
        "create_deploy",
        "update_env_var",
        "list_postgres",
        "list_logs",
        "list_workflows",
    } <= set(names)
    assert all(
        method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        for method, *_ in RENDER_OPERATIONS.values()
    )


def test_credential_and_connection_evidence():
    cred = RenderAPIKeyCredential(api_key=KEY)
    assert cred.credential_type == "render_api_key"
    assert RenderNode.connection_evidence.field == "service_id"
    assert RenderNode.connection_evidence.identity_operation == "get_user"
    assert RenderGetUserConfig().operation == "get_user"


@pytest.mark.asyncio
async def test_service_picker_flattens_render_list_envelopes():
    payload = {
        "status": "success",
        "data": {
            "items": [
                {"service": {"id": "srv-1", "name": "Web API"}, "cursor": "next"},
                {"service": {"id": "srv-2", "name": "Worker"}},
            ]
        },
    }
    with patch(
        "nodes.render_node._render_request",
        new_callable=AsyncMock,
        return_value=payload,
    ) as request:
        options = await RenderNode.load_field_options("service_id", {"api_key": KEY})
    assert options == [
        {"value": "srv-1", "label": "Web API"},
        {"value": "srv-2", "label": "Worker"},
    ]
    assert request.await_args.args[:3] == (KEY, "GET", "/services")


@pytest.mark.asyncio
async def test_list_services_query_parameters_and_authless_body():
    node = make_node(
        RenderListServicesConfig(
            name='["api","worker"]', limit=25, include_previews=True
        )
    )
    with patch("nodes.render_node._render_request", new_callable=AsyncMock) as request:
        await node.execute({})
    args, kwargs = request.await_args
    assert args[:3] == (KEY, "GET", "/services")
    assert ("name", "api") in kwargs["params"]
    assert ("name", "worker") in kwargs["params"]
    assert ("limit", 25) in kwargs["params"]
    assert ("includePreviews", "true") in kwargs["params"]
    assert kwargs["body"] is None


@pytest.mark.asyncio
async def test_encoded_path_and_required_parameters():
    node = make_node(RenderRetrieveServiceConfig(service_id="srv/unsafe"))
    with patch("nodes.render_node._render_request", new_callable=AsyncMock) as request:
        await node.execute({})
    assert request.await_args.args[2] == "/services/srv%2Funsafe"
    with pytest.raises(Exception):
        RenderListLogsConfig()
    assert (
        RenderListLogsConfig(owner_id="own-1", resource='["srv-1"]').operation
        == "list_logs"
    )


@pytest.mark.asyncio
async def test_deploy_write_passes_json_body():
    node = make_node(
        RenderCreateDeployConfig(service_id="srv-1", body='{"clearCache":"clear"}')
    )
    with patch("nodes.render_node._render_request", new_callable=AsyncMock) as request:
        await node.execute({})
    args, kwargs = request.await_args
    assert args[:3] == (KEY, "POST", "/services/srv-1/deploys")
    assert kwargs["body"] == {"clearCache": "clear"}
    assert kwargs["operation"] == "create_deploy"


@pytest.mark.asyncio
async def test_invalid_body_is_rejected_before_http():
    node = make_node(RenderCreateDeployConfig(service_id="srv-1", body="{"))
    with patch("nodes.render_node._render_request", new_callable=AsyncMock) as request:
        with pytest.raises(ValueError, match="valid JSON"):
            await node.execute({})
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_success_list_is_table_ready_and_uses_bearer_key():
    session = fake_http_response(200, [{"service": {"id": "srv-1"}}])
    with patch("nodes.render_node.httpx.AsyncClient", return_value=session) as client:
        result = await _render_request(
            KEY, "GET", "/services", params=[], body=None, operation="list_services"
        )
    assert result["status"] == "success"
    assert result["data"] == {"items": [{"service": {"id": "srv-1"}}], "count": 1}
    assert result["status_code"] == 200
    assert "api" in result["timing_ms"]
    assert (
        session.request.call_args.kwargs["headers"]["Authorization"] == f"Bearer {KEY}"
    )
    client.assert_called_once_with(timeout=120, follow_redirects=False)
    assert session.request.await_count == 1


@pytest.mark.asyncio
async def test_http_errors_preserve_status_without_request_secret():
    session = fake_http_response(401, {"message": "Unauthorized"})
    with patch("nodes.render_node.httpx.AsyncClient", return_value=session):
        result = await _render_request(
            KEY, "GET", "/users", params=[], body=None, operation="get_user"
        )
    assert result["status"] == "error"
    assert result["status_code"] == 401
    assert result["error"] == "Unauthorized"
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_http_error_redacts_key_echoed_by_provider():
    session = fake_http_response(400, {"message": f"Invalid token {KEY}"})
    with patch("nodes.render_node.httpx.AsyncClient", return_value=session):
        result = await _render_request(
            KEY, "GET", "/users", params=[], body=None, operation="get_user"
        )
    assert result["error"] == "Invalid token [redacted]"


@pytest.mark.asyncio
async def test_structured_workflow_request_body_preserves_json_types():
    node = make_node(RenderCreateDeployConfig(service_id="srv-1", body={"clearCache": "clear"}))
    with patch("nodes.render_node._render_request", new_callable=AsyncMock) as request:
        await node.execute({})
    assert request.await_args.kwargs["body"] == {"clearCache": "clear"}
    from nodes.render_node import RenderUpdateEnvVarsForServiceConfig
    config = RenderUpdateEnvVarsForServiceConfig(service_id="srv-1", body=[{"key": "FLAG", "generateValue": True}])
    node = make_node(config)
    with patch("nodes.render_node._render_request", new_callable=AsyncMock) as request:
        await node.execute({})
    assert request.await_args.kwargs["body"] == [{"key": "FLAG", "generateValue": True}]
