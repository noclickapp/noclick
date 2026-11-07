"""Baserow database-token actions against a simulated HTTP server."""

import json

import httpx
import pytest

from nodes import baserow_node as module
from nodes.baserow_node import (
    BaserowBatchCreateRowsConfig,
    BaserowBatchDeleteRowsConfig,
    BaserowBatchUpdateRowsConfig,
    BaserowCreateRowConfig,
    BaserowDatabaseTokenCredential,
    BaserowDeleteRowConfig,
    BaserowGetRowConfig,
    BaserowListFieldsConfig,
    BaserowListRowsConfig,
    BaserowListTablesConfig,
    BaserowMoveRowConfig,
    BaserowNode,
    BaserowNodeConfig,
    BaserowUpdateRowConfig,
)


def make_node(config):
    credentials = BaserowDatabaseTokenCredential(database_token="test-secret")
    return BaserowNode(
        node_id="baserow-test",
        node_type="automation-baserow",
        node_data={},
        config=BaserowNodeConfig(config=config, credentials=credentials),
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


@pytest.mark.parametrize(
    "config,method,path,expected_body",
    [
        (BaserowListTablesConfig(), "GET", "/api/database/tables/all-tables/", None),
        (
            BaserowListFieldsConfig(table_id=11),
            "GET",
            "/api/database/fields/table/11/",
            None,
        ),
        (
            BaserowListRowsConfig(table_id=11, search="Ada", page=2),
            "GET",
            "/api/database/rows/table/11/",
            None,
        ),
        (
            BaserowGetRowConfig(table_id=11, row_id=2),
            "GET",
            "/api/database/rows/table/11/2/",
            None,
        ),
        (
            BaserowCreateRowConfig(table_id=11, fields={"Name": "Ada"}),
            "POST",
            "/api/database/rows/table/11/",
            {"Name": "Ada"},
        ),
        (
            BaserowUpdateRowConfig(table_id=11, row_id=2, fields={"Name": "Grace"}),
            "PATCH",
            "/api/database/rows/table/11/2/",
            {"Name": "Grace"},
        ),
        (
            BaserowMoveRowConfig(table_id=11, row_id=2, before_row_id=3),
            "PATCH",
            "/api/database/rows/table/11/2/move/",
            None,
        ),
        (
            BaserowDeleteRowConfig(table_id=11, row_id=2),
            "DELETE",
            "/api/database/rows/table/11/2/",
            None,
        ),
        (
            BaserowBatchCreateRowsConfig(table_id=11, rows=[{"Name": "Ada"}]),
            "POST",
            "/api/database/rows/table/11/batch/",
            {"items": [{"Name": "Ada"}]},
        ),
        (
            BaserowBatchUpdateRowsConfig(
                table_id=11, rows=[{"id": 2, "Name": "Grace"}]
            ),
            "PATCH",
            "/api/database/rows/table/11/batch/",
            {"items": [{"id": 2, "Name": "Grace"}]},
        ),
        (
            BaserowBatchDeleteRowsConfig(table_id=11, row_ids=[2, 3]),
            "POST",
            "/api/database/rows/table/11/batch-delete/",
            {"items": [2, 3]},
        ),
    ],
)
@pytest.mark.asyncio
async def test_all_database_token_operations(
    monkeypatch, config, method, path, expected_body
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            204 if method == "DELETE" else 200,
            json=None if method == "DELETE" else {"id": 2},
        )

    monkeypatch.setattr(
        module,
        "guarded_async_client",
        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await make_node(config).execute({})

    assert result["status"] == "success"
    assert result["action"] == config.operation
    assert result["timing_ms"]["total"] >= 0
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == path
    assert request.headers["Authorization"] == "Token test-secret"
    if expected_body is not None:
        assert json.loads(request.content) == expected_body
    if config.operation == "list_rows":
        assert request.url.params["search"] == "Ada"
        assert request.url.params["page"] == "2"
    if config.operation == "move_row":
        assert request.url.params["before_id"] == "3"


@pytest.mark.asyncio
async def test_dynamic_table_options_and_api_error(monkeypatch):
    def handler(request):
        if request.url.path.endswith("all-tables/"):
            return httpx.Response(
                200, json=[{"id": 11, "name": "Customers", "database_id": 4}]
            )
        return httpx.Response(403, json={"error": "ERROR_NO_PERMISSION"})

    monkeypatch.setattr(
        module,
        "guarded_async_client",
        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    credential = {"database_token": "test-secret"}
    options = await BaserowNode.load_field_options(
        "table_id", credential, page_token=None, search="customer"
    )
    assert options == {
        "options": [
            {"value": "11", "label": "Customers", "metadata": {"database_id": 4}}
        ]
    }
    assert await BaserowNode.load_field_options(
        "table_id", credential, search="missing"
    ) == {"options": []}
    result = await make_node(BaserowGetRowConfig(table_id=11, row_id=2)).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 403
    assert result["error"] == "ERROR_NO_PERMISSION"


def test_json_text_from_flow_canvas_is_parsed_for_row_fields():
    create = BaserowCreateRowConfig.model_validate(
        {"table_id": 11, "fields": '{"Name":"Ada"}'}
    )
    update = BaserowUpdateRowConfig.model_validate(
        {"table_id": 11, "row_id": 2, "fields": '{"Name":"Grace"}'}
    )
    assert create.fields == {"Name": "Ada"}
    assert update.fields == {"Name": "Grace"}


@pytest.mark.asyncio
async def test_rejects_non_https_instance(monkeypatch):
    node = make_node(BaserowListTablesConfig())
    node.config.credentials.base_url = "http://localhost:8000"
    with pytest.raises(ValueError, match="public HTTPS origin"):
        await node.execute({})
