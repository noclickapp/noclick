"""Excel wire regressions using responses copied from the linked Microsoft docs."""

import json
from pathlib import Path

import httpx
import pytest

from nodes.excel_node import ExcelNode, ExcelNodeConfig


FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/microsoft_excel_conformance.json").read_text()
)
ROOT = "https://graph.microsoft.com/v1.0/me/drive/items/01CYZLFJDYBLIGAE7G5FE3I4VO2XP7BLU4/workbook"


async def execute(monkeypatch, config, responses):
    requests = []
    replies = iter(responses)
    original_client = httpx.AsyncClient

    def transport(request):
        requests.append(request)
        fixture = next(replies)
        if fixture is None:
            # tablerow-delete and tablesort-apply document HTTP 200 with no body.
            return httpx.Response(200)
        reply = FIXTURES[fixture]
        return httpx.Response(reply.get("status", 200), json=reply["body"])

    def client(*args, **kwargs):
        return original_client(
            *args, **kwargs, transport=httpx.MockTransport(transport), trust_env=False
        )

    monkeypatch.setattr(httpx, "AsyncClient", client)
    node = ExcelNode(
        node_id="excel-conformance",
        node_type="automation-excel",
        node_data={},
        sio=None,
        config=ExcelNodeConfig.model_validate(
            {
                "config": {"workbook_id": "01CYZLFJDYBLIGAE7G5FE3I4VO2XP7BLU4", **config},
                "credentials": {
                    "credential_type": "microsoft_excel_oauth",
                    "access_token": "fake-excel-token",
                    "refresh_token": "fake-refresh-token",
                    "expires_at": "2099-12-31T23:59:59Z",
                    "email": "conformance@example.com",
                },
            }
        ),
    )
    result = await node.execute({})
    assert all(
        r.headers["authorization"] == "Bearer fake-excel-token" for r in requests
    )
    return result, requests


@pytest.mark.asyncio
async def test_format_range_updates_font_fill_and_alignment(monkeypatch):
    # rangeformat-update documents three separate PATCH resources, not a deep update.
    result, requests = await execute(
        monkeypatch,
        {
            "operation": "format_range",
            "worksheet_name": "Sheet1",
            "range_address": "$A$1",
            "font_bold": True,
            "font_size": 26,
            "font_color": "#4B180E",
            "background_color": "#FF0000",
            "vertical_alignment": "Top",
        },
        ["font", "fill", "format"],
    )
    assert result["status"] == "success"
    url = ROOT + "/worksheets/Sheet1/range(address='$A$1')/format"
    assert [(r.method, str(r.url)) for r in requests] == [
        ("PATCH", url + "/font"),
        ("PATCH", url + "/fill"),
        ("PATCH", url),
    ]
    assert [json.loads(r.content) for r in requests] == [
        {"bold": True, "size": 26, "color": "#4B180E"},
        {"color": "#FF0000"},
        {"verticalAlignment": "Top"},
    ]


@pytest.mark.asyncio
async def test_horizontal_alignment_is_a_format_property(monkeypatch):
    result, requests = await execute(
        monkeypatch,
        {
            "operation": "format_range",
            "worksheet_name": "Sheet1",
            "range_address": "$B$1",
            "horizontal_alignment": "Center",
        },
        ["format"],
    )
    assert result["status"] == "success"
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"horizontalAlignment": "Center"}


@pytest.mark.asyncio
@pytest.mark.parametrize("table_name", [None, "name-value"])
async def test_create_table_names_the_created_resource(monkeypatch, table_name):
    result, requests = await execute(
        monkeypatch,
        {
            "operation": "create_table_from_range",
            "worksheet_name": "Sheet1",
            "range_address": "A1:D5",
            "has_headers": True,
            "table_name": table_name,
        },
        ["table_created", "table_updated"],
    )
    assert result["status"] == "success"
    assert result["data"]["id"] == "99"
    assert requests[0].method == "POST"
    assert str(requests[0].url) == ROOT + "/tables/add"
    assert json.loads(requests[0].content) == {
        "address": "Sheet1!A1:D5", "hasHeaders": True
    }
    if table_name:
        assert len(requests) == 2
        assert requests[1].method == "PATCH"
        assert str(requests[1].url) == ROOT + "/tables/99"
        assert json.loads(requests[1].content) == {"name": "name-value"}
    else:
        assert len(requests) == 1


@pytest.mark.asyncio
async def test_sort_resolves_column_name_to_numeric_key(monkeypatch):
    result, requests = await execute(
        monkeypatch,
        {
            "operation": "sort_table_by_column",
            "table_name": "Table1",
            "column_name": "name-value",
        },
        ["column", None],
    )
    assert result["status"] == "success"
    assert [(r.method, str(r.url)) for r in requests] == [
        ("GET", ROOT + "/tables/Table1/columns/name-value"),
        ("POST", ROOT + "/tables/Table1/sort/apply"),
    ]
    assert json.loads(requests[1].content) == {
        "fields": [{"key": 99, "ascending": True}]
    }


@pytest.mark.asyncio
async def test_delete_row_uses_row_resource(monkeypatch):
    # https://learn.microsoft.com/en-us/graph/api/tablerow-delete?view=graph-rest-1.0
    result, requests = await execute(
        monkeypatch,
        {"operation": "delete_table_row", "table_name": "Table1", "index": 0},
        [None],
    )
    assert result["status"] == "success"
    assert [(r.method, str(r.url)) for r in requests] == [
        ("DELETE", ROOT + "/tables/Table1/rows/0")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dimensions", "suffix"),
    [
        ({}, "image"),
        ({"width": 640}, "image(width=640)"),
        ({"width": 640, "height": 480}, "image(width=640,height=480)"),
        # https://learn.microsoft.com/en-us/graph/excel-display-chart-image: width 0 is default.
        ({"height": 480}, "image(width=0,height=480)"),
    ],
)
async def test_image_dimensions_are_function_arguments(monkeypatch, dimensions, suffix):
    result, requests = await execute(
        monkeypatch,
        {
            "operation": "get_chart_image",
            "worksheet_name": "Sheet1",
            "chart_name": "Chart1",
            **dimensions,
        },
        ["image"],
    )
    assert result["data"]["image_base64"] == "base-64 chart image string"
    assert [(r.method, str(r.url)) for r in requests] == [
        ("GET", ROOT + "/worksheets/Sheet1/charts/Chart1/" + suffix)
    ]
    assert not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("height", [None, 99])
async def test_chart_title_uses_title_resource(monkeypatch, height):
    result, requests = await execute(
        monkeypatch,
        {
            "operation": "update_chart",
            "worksheet_name": "Sheet1",
            "chart_name": "Chart1",
            "title": "text-value",
            "height": height,
        },
        ["chart_title", "chart_updated" if height else "chart"],
    )
    assert result["status"] == "success"
    assert result["data"]["id"] == "id-value"
    url = ROOT + "/worksheets/Sheet1/charts/Chart1"
    assert [(r.method, str(r.url)) for r in requests] == [
        ("PATCH", url + "/title"),
        ("PATCH" if height else "GET", url),
    ]
    assert json.loads(requests[0].content) == {"text": "text-value"}
    if height:
        assert json.loads(requests[1].content) == {"height": 99}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "replies"),
    [
        (
            {"operation": "format_range", "worksheet_name": "Sheet1",
             "range_address": "$A$1", "font_bold": True, "background_color": "#FF0000"},
            ["error"],
        ),
        (
            {"operation": "create_table_from_range", "worksheet_name": "Sheet1",
             "range_address": "A1:D5", "table_name": "name-value"},
            ["table_created", "error"],
        ),
        (
            {"operation": "sort_table_by_column", "table_name": "Table1",
             "column_name": "name-value"},
            ["error"],
        ),
        (
            {"operation": "update_chart", "worksheet_name": "Sheet1",
             "chart_name": "Chart1", "title": "text-value", "height": 99},
            ["error"],
        ),
    ],
)
async def test_multistep_updates_stop_on_provider_error(monkeypatch, config, replies):
    result, requests = await execute(monkeypatch, config, replies)
    assert result["status"] == "error"
    assert result["status_code"] == 400
    assert "Uploaded fragment overlaps with existing data." in result["message"]
    assert len(requests) == len(replies)
