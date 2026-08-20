"""Google Sheets coverage phase 3 — charts and embedded objects.

Two things make charts awkward. Stacking is a property of a basic chart rather
than a chart type, so the UI-facing names (STACKED_COLUMN) have to be flattened
back into (chartType, stackedType). And updateChartSpec REPLACES the whole spec,
so an edit that changes only the title must carry the existing series forward or
it silently blanks the chart.
"""

import pytest

from nodes.google_sheets_node import (
    GoogleSheetsAddChartConfig,
    GoogleSheetsAppendCellsConfig,
    GoogleSheetsChartBorderConfig,
    GoogleSheetsDeleteChartConfig,
    GoogleSheetsMoveChartConfig,
    GoogleSheetsNode,
    GoogleSheetsNodeConfig,
    GoogleSheetsUpdateChartConfig,
    hex_to_color,
)

SHEET_ID = 21


class _Recorder:
    def __init__(self, node, sheet_entry=None, reply=None):
        self.requests = []
        self.sheet_entry = sheet_entry or {}
        self.reply = reply or {"replies": [{"addChart": {"chart": {"chartId": 77}}}]}
        node._send_batch_update = self._send
        node._get_sheet_id = self._sheet_id
        node._fetch_sheet_entry = self._fetch

    async def _send(self, spreadsheet_id, requests, access_token):
        self.requests.append(requests)
        return self.reply

    async def _sheet_id(self, spreadsheet_id, sheet_name, access_token):
        return SHEET_ID

    async def _fetch(self, spreadsheet_id, sheet_name, fields, access_token):
        return {"properties": {"sheetId": SHEET_ID, "title": sheet_name}, **self.sheet_entry}

    @property
    def only(self):
        assert len(self.requests) == 1 and len(self.requests[0]) == 1
        return self.requests[0][0]


def _node():
    return GoogleSheetsNode.__new__(GoogleSheetsNode)


def _chart(**kw):
    kw.setdefault("series_ranges", "F2:F13")
    return GoogleSheetsAddChartConfig(spreadsheet_id="ss", sheet_name="Sheet1", **kw)


class TestChartSpec:
    @pytest.mark.asyncio
    async def test_column_chart_with_labels(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._add_chart(
            _chart(chart_title="Spend by tier", labels_range="A2:A13", anchor_cell="Z2"), "token"
        )
        chart = rec.only["addChart"]["chart"]
        basic = chart["spec"]["basicChart"]
        assert chart["spec"]["title"] == "Spend by tier"
        assert basic["chartType"] == "COLUMN"
        assert basic["stackedType"] == "NOT_STACKED"
        assert basic["domains"][0]["domain"]["sourceRange"]["sources"][0]["endRowIndex"] == 13
        assert len(basic["series"]) == 1
        assert out["chart_id"] == 77

    @pytest.mark.asyncio
    async def test_stacking_is_flattened_out_of_the_type_name(self):
        """STACKED_COLUMN is not an API chart type — it is COLUMN + STACKED."""
        node = _node()
        rec = _Recorder(node)
        await node._add_chart(_chart(chart_type="STACKED_BAR", anchor_cell="Z2"), "token")
        basic = rec.only["addChart"]["chart"]["spec"]["basicChart"]
        assert basic["chartType"] == "BAR"
        assert basic["stackedType"] == "STACKED"

    @pytest.mark.asyncio
    async def test_chart_data_is_wrapped_in_source_range(self):
        """ChartData nests ranges under sourceRange; a bare sources[] is invalid."""
        node = _node()
        rec = _Recorder(node)
        await node._add_chart(_chart(labels_range="A2:A13", anchor_cell="Z2"), "token")
        basic = rec.only["addChart"]["chart"]["spec"]["basicChart"]
        assert "sourceRange" in basic["series"][0]["series"]
        assert "sourceRange" in basic["domains"][0]["domain"]

    @pytest.mark.asyncio
    async def test_multiple_series(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_chart(
            _chart(series_ranges="F2:F13, G2:G13", labels_range="A2:A13", anchor_cell="Z2"),
            "token",
        )
        assert len(rec.only["addChart"]["chart"]["spec"]["basicChart"]["series"]) == 2

    @pytest.mark.asyncio
    async def test_pie_chart(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_chart(
            _chart(chart_type="PIE", labels_range="A2:A13", anchor_cell="Z2"), "token"
        )
        pie = rec.only["addChart"]["chart"]["spec"]["pieChart"]
        assert pie["pieHole"] == 0
        assert "domain" in pie and "series" in pie

    @pytest.mark.asyncio
    async def test_donut_is_a_pie_with_a_hole(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_chart(
            _chart(chart_type="DONUT", labels_range="A2:A13", anchor_cell="Z2"), "token"
        )
        assert rec.only["addChart"]["chart"]["spec"]["pieChart"]["pieHole"] == 0.5

    @pytest.mark.asyncio
    async def test_pie_without_labels_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="pie chart needs Labels"):
            await node._add_chart(_chart(chart_type="PIE", anchor_cell="Z2"), "token")

    @pytest.mark.asyncio
    async def test_pie_with_multiple_series_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="single range of values"):
            await node._add_chart(
                _chart(chart_type="PIE", labels_range="A2:A13", series_ranges="F2:F13, G2:G13"),
                "token",
            )

    @pytest.mark.asyncio
    async def test_histogram_and_scorecard(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_chart(_chart(chart_type="HISTOGRAM", anchor_cell="Z2"), "token")
        assert "histogramChart" in rec.only["addChart"]["chart"]["spec"]

        node2 = _node()
        rec2 = _Recorder(node2)
        await node2._add_chart(_chart(chart_type="SCORECARD", anchor_cell="Z2"), "token")
        assert "scorecardChart" in rec2.only["addChart"]["chart"]["spec"]

    @pytest.mark.asyncio
    async def test_no_series_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="Values is required"):
            await node._add_chart(_chart(series_ranges="  ", anchor_cell="Z2"), "token")

    @pytest.mark.asyncio
    async def test_no_anchor_puts_the_chart_on_a_new_sheet(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_chart(_chart(), "token")
        assert rec.only["addChart"]["chart"]["position"] == {"newSheet": True}

    @pytest.mark.asyncio
    async def test_anchor_becomes_an_overlay_coordinate(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_chart(_chart(anchor_cell="C5"), "token")
        overlay = rec.only["addChart"]["chart"]["position"]["overlayPosition"]
        assert overlay["anchorCell"] == {"sheetId": SHEET_ID, "rowIndex": 4, "columnIndex": 2}


class TestGridToA1:
    @pytest.mark.parametrize(
        "grid,expected",
        [
            ({"startRowIndex": 1, "endRowIndex": 13, "startColumnIndex": 5, "endColumnIndex": 6}, "F2:F13"),
            ({"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1}, "A1:A1"),
            ({"startRowIndex": 0, "endRowIndex": 2, "startColumnIndex": 26, "endColumnIndex": 27}, "AA1:AA2"),
        ],
    )
    def test_round_trips_back_to_a1(self, grid, expected):
        assert GoogleSheetsNode._grid_to_a1(grid) == expected


class TestUpdateChart:
    EXISTING = {
        "chartId": 77,
        "spec": {
            "title": "Spend by tier",
            "basicChart": {
                "chartType": "COLUMN",
                "stackedType": "NOT_STACKED",
                "domains": [
                    {"domain": {"sourceRange": {"sources": [
                        {"startRowIndex": 1, "endRowIndex": 13, "startColumnIndex": 0, "endColumnIndex": 1}
                    ]}}}
                ],
                "series": [
                    {"series": {"sourceRange": {"sources": [
                        {"startRowIndex": 1, "endRowIndex": 13, "startColumnIndex": 5, "endColumnIndex": 6}
                    ]}}}
                ],
            },
        },
    }

    @pytest.mark.asyncio
    async def test_retitling_carries_the_existing_series_forward(self):
        """updateChartSpec replaces the whole spec — dropping series would blank it."""
        node = _node()
        rec = _Recorder(node, {"charts": [self.EXISTING]})
        await node._update_chart(
            GoogleSheetsUpdateChartConfig(
                spreadsheet_id="ss", sheet_name="Sheet1",
                chart_title="Spend by tier", new_title="Spend by segment",
            ),
            "token",
        )
        spec = rec.only["updateChartSpec"]["spec"]
        assert spec["title"] == "Spend by segment"
        assert len(spec["basicChart"]["series"]) == 1
        assert spec["basicChart"]["series"][0]["series"]["sourceRange"]["sources"][0]["startColumnIndex"] == 5
        assert spec["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"][0]["startColumnIndex"] == 0

    @pytest.mark.asyncio
    async def test_changing_type_keeps_the_data(self):
        node = _node()
        rec = _Recorder(node, {"charts": [self.EXISTING]})
        await node._update_chart(
            GoogleSheetsUpdateChartConfig(
                spreadsheet_id="ss", sheet_name="Sheet1",
                chart_title="Spend by tier", chart_type="LINE",
            ),
            "token",
        )
        basic = rec.only["updateChartSpec"]["spec"]["basicChart"]
        assert basic["chartType"] == "LINE"
        assert len(basic["series"]) == 1

    @pytest.mark.asyncio
    async def test_unreadable_series_asks_for_values_rather_than_blanking(self):
        node = _node()
        rec = _Recorder(node, {"charts": [{"chartId": 77, "spec": {"title": "Odd", "waterfallChart": {}}}]})
        with pytest.raises(ValueError, match="Values must be supplied"):
            await node._update_chart(
                GoogleSheetsUpdateChartConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", chart_title="Odd", new_title="X"
                ),
                "token",
            )
        assert rec.requests == []

    @pytest.mark.parametrize(
        "spec,expected",
        [
            ({"pieChart": {"pieHole": 0}}, "PIE"),
            ({"pieChart": {"pieHole": 0.5}}, "DONUT"),
            ({"histogramChart": {}}, "HISTOGRAM"),
            ({"scorecardChart": {}}, "SCORECARD"),
            ({"basicChart": {"chartType": "BAR", "stackedType": "STACKED"}}, "STACKED_BAR"),
            ({"basicChart": {"chartType": "LINE", "stackedType": "NOT_STACKED"}}, "LINE"),
            ({"basicChart": {"chartType": "LINE", "stackedType": "STACKED"}}, "LINE"),
        ],
    )
    def test_type_inference_round_trips(self, spec, expected):
        assert GoogleSheetsNode._infer_chart_type(spec) == expected


class TestChartPlacementAndRemoval:
    CHART = {"chartId": 77, "spec": {"title": "Spend by tier"}}

    @pytest.mark.asyncio
    async def test_move_to_a_cell_with_a_size(self):
        node = _node()
        rec = _Recorder(node, {"charts": [self.CHART]})
        await node._move_chart(
            GoogleSheetsMoveChartConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", chart_title="Spend by tier",
                anchor_cell="B2", width_pixels=600, height_pixels=400,
            ),
            "token",
        )
        request = rec.only["updateEmbeddedObjectPosition"]
        overlay = request["newPosition"]["overlayPosition"]
        assert request["objectId"] == 77
        assert overlay["anchorCell"]["rowIndex"] == 1
        assert overlay["widthPixels"] == 600

    @pytest.mark.asyncio
    async def test_move_without_an_anchor_goes_to_its_own_sheet(self):
        node = _node()
        rec = _Recorder(node, {"charts": [self.CHART]})
        out = await node._move_chart(
            GoogleSheetsMoveChartConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", chart_title="Spend by tier"
            ),
            "token",
        )
        assert rec.only["updateEmbeddedObjectPosition"]["newPosition"] == {"newSheet": True}
        assert out["moved_to_new_sheet"] is True

    @pytest.mark.asyncio
    async def test_border(self):
        node = _node()
        rec = _Recorder(node, {"charts": [self.CHART]})
        await node._set_chart_border(
            GoogleSheetsChartBorderConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", chart_title="Spend by tier",
                border_color="#D9E0DE",
            ),
            "token",
        )
        request = rec.only["updateEmbeddedObjectBorder"]
        assert request["border"]["color"] == hex_to_color("#D9E0DE")
        assert request["fields"] == "color"

    @pytest.mark.asyncio
    async def test_delete(self):
        node = _node()
        rec = _Recorder(node, {"charts": [self.CHART]})
        await node._delete_chart(
            GoogleSheetsDeleteChartConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", chart_title="Spend by tier"
            ),
            "token",
        )
        assert rec.only["deleteEmbeddedObject"] == {"objectId": 77}

    @pytest.mark.asyncio
    async def test_unknown_chart_lists_what_is_there(self):
        node = _node()
        rec = _Recorder(node, {"charts": [self.CHART]})
        with pytest.raises(ValueError, match="Charts here: Spend by tier"):
            await node._delete_chart(
                GoogleSheetsDeleteChartConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", chart_title="Nope"
                ),
                "token",
            )
        assert rec.requests == []

    @pytest.mark.asyncio
    async def test_untitled_charts_are_described_not_crashed_on(self):
        node = _node()
        _Recorder(node, {"charts": [{"chartId": 1, "spec": {}}]})
        with pytest.raises(ValueError, match=r"Charts here: \(untitled\)"):
            await node._delete_chart(
                GoogleSheetsDeleteChartConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", chart_title="Nope"
                ),
                "token",
            )


class TestAppendCells:
    @pytest.mark.asyncio
    async def test_types_are_preserved(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._append_cells(
            GoogleSheetsAppendCellsConfig(
                spreadsheet_id="ss", sheet_name="Sheet1",
                values='[["Jane", 42, true, "=SUM(A1:A2)", ""]]',
            ),
            "token",
        )
        values = rec.only["appendCells"]["rows"][0]["values"]
        assert values[0]["userEnteredValue"] == {"stringValue": "Jane"}
        assert values[1]["userEnteredValue"] == {"numberValue": 42}
        assert values[2]["userEnteredValue"] == {"boolValue": True}
        assert values[3]["userEnteredValue"] == {"formulaValue": "=SUM(A1:A2)"}
        assert values[4] == {}
        assert out["rows_appended"] == 1

    @pytest.mark.asyncio
    async def test_non_list_rows_are_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="Each row must itself be a list"):
            await node._append_cells(
                GoogleSheetsAppendCellsConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", values='["Jane", "Sam"]'
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_malformed_json_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="not valid JSON"):
            await node._append_cells(
                GoogleSheetsAppendCellsConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", values='[["a"'
                ),
                "token",
            )


class TestConfigParsing:
    NEW_OPERATIONS = [
        ("add_chart", {"series_ranges": "F2:F13"}),
        ("update_chart", {"chart_title": "X", "new_title": "Y"}),
        ("move_chart", {"chart_title": "X", "anchor_cell": "B2"}),
        ("set_chart_border", {"chart_title": "X", "border_color": "#000000"}),
        ("delete_chart", {"chart_title": "X"}),
        ("append_cells", {"values": '[["a"]]'}),
    ]

    @pytest.mark.parametrize("operation,extra", NEW_OPERATIONS)
    def test_operation_parses_and_dispatches(self, operation, extra):
        import inspect

        parsed = GoogleSheetsNodeConfig(
            config={
                "operation": operation,
                "spreadsheet_id": "ss",
                "sheet_name": "Sheet1",
                **extra,
            }
        ).config
        assert parsed.operation == operation
        source = inspect.getsource(GoogleSheetsNode.execute)
        assert f"isinstance(config, {type(parsed).__name__})" in source

    def test_all_new_operations_are_in_the_schema(self):
        schema = GoogleSheetsNode.get_config_schema()
        defs = schema.get("$defs", schema.get("definitions", {}))
        found = set()
        for entry in defs.values():
            operation = entry.get("properties", {}).get("operation", {})
            for value in operation.get("enum", []) or [operation.get("const")]:
                if value:
                    found.add(value)
        for operation, _ in self.NEW_OPERATIONS:
            assert operation in found
