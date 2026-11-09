"""Exercise all Prisma routes through the real node factory without network access."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import prisma_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-prisma-service-token"
ROUTES = json.loads((Path(__file__).parent / "fixtures/prisma/routes.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="prisma-fixture",
        node_type="automation-prisma",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "prisma_service_token",
                "service_token": TOKEN,
            },
        },
    )


def transport(monkeypatch, status, body=None):
    requests = []

    def respond(request):
        requests.append(request)
        return (
            httpx.Response(status, json=body)
            if body is not None
            else httpx.Response(status)
        )

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ROUTES)
async def test_each_operation_single_contract_request(monkeypatch, operation):
    spec = ROUTES[operation]
    config = {"operation": operation}
    values = {
        "project_id": "proj_abc123",
        "database_id": "db_abc123",
        "connection_id": "con_abc123",
        "workspace_id": "wksp_abc123",
        "name": "Workflow database",
    }
    model = next(
        m
        for m in native.Operation.__args__[0].__args__
        if m.model_fields["operation"].default == operation
    )
    for key, field in model.model_fields.items():
        if field.is_required():
            config[key] = values[key]
    status = (
        204
        if spec["method"] == "DELETE"
        else 201
        if operation in {"create_project", "create_database", "create_connection"}
        else 200
    )
    response = {
        "data": [{"id": "proj_abc123", "name": "Automation"}],
        "pagination": {"hasMore": True, "nextCursor": "cursor+next"},
    }
    if operation == "get_database_usage":
        response = {
            "period": {"start": "2026-10-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"},
            "metrics": {
                "operations": {"used": 12, "unit": "ops"},
                "storage": {"used": 1, "unit": "GiB"},
            },
            "generatedAt": "2026-11-01T00:00:00Z",
        }
    requests = transport(monkeypatch, status, response if status != 204 else None)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == spec["method"] and req.url.path == spec["path"].format(
        **values
    )
    assert (
        req.url.host == "api.prisma.io"
        and req.headers["Authorization"] == "Bearer " + TOKEN
    )
    if status == 204:
        assert result["deleted"] is True
    else:
        assert result == {**response, "status": "success"}
    if spec["body_fields"]:
        body = json.loads(req.content)
        assert set(body) == {native.WIRE_NAMES.get(k, k) for k in spec["body_fields"]}
        for key in spec["body_fields"]:
            assert body[native.WIRE_NAMES.get(key, key)] == getattr(
                node(config).config.config, key
            )
    else:
        assert req.content == b""


@pytest.mark.asyncio
async def test_pagination_filter_dates_and_wire_names(monkeypatch):
    requests = transport(
        monkeypatch,
        200,
        {"data": [], "pagination": {"hasMore": False, "nextCursor": None}},
    )
    await node(
        {
            "operation": "list_project_databases",
            "project_id": "proj_abc123",
            "cursor": "page+two &x",
            "limit": 3,
        }
    ).execute({})
    assert dict(requests[0].url.params) == {"cursor": "page+two &x", "limit": "3"}
    requests = transport(
        monkeypatch,
        200,
        {"period": {}, "metrics": {}, "generatedAt": "2026-11-01T00:00:00Z"},
    )
    await node(
        {
            "operation": "get_database_usage",
            "database_id": "db_abc123",
            "start_date": "2026-10-01T00:00:00Z",
            "end_date": "2026-11-01T00:00:00Z",
        }
    ).execute({})
    assert dict(requests[0].url.params) == {
        "startDate": "2026-10-01T00:00:00Z",
        "endDate": "2026-11-01T00:00:00Z",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 301, 401, 403, 404, 429, 500])
async def test_failures_preserve_provider_rejection_and_redact_token(
    monkeypatch, status
):
    requests = transport(monkeypatch, status, {"message": "Access denied " + TOKEN})
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_projects"}).execute({})
    assert f"HTTP {status}" in str(error.value) and "Access denied" in str(error.value)
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"data": [], "error": "rejected"}])
async def test_unexpected_envelope_refused(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_projects"}).execute({})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_database"},
        {"operation": "get_project", "project_id": "../../me"},
        {"operation": "create_connection", "database_id": "db_abc123", "name": "x"},
        {"operation": "list_projects", "limit": 0},
        {
            "operation": "create_database",
            "project_id": "proj_abc123",
            "name": "x",
            "region": "invalid",
        },
        {
            "operation": "get_database_usage",
            "database_id": "db_abc123",
            "start_date": "yesterday",
        },
    ],
)
def test_invalid_inputs_fail_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        native.PrismaNode.parse_config({"config": config})


def test_credential_can_be_entered_manually():
    credential = native.PrismaServiceTokenCredential(service_token=TOKEN)
    assert credential.credential_type == "prisma_service_token"
    assert native.PrismaNode.connection_evidence.operation == "list_projects"
