"""Google Sheets coverage phase 4 — saved views, grouping and slicers.

A filter view is a named, private filter: it doesn't change what collaborators
see, which is what makes it usable on a shared sheet where set_basic_filter
would be rude. Slicers are the interactive-control version of the same idea.

Both address columns by an index relative to their OWN range, so the shared
_relative_column helper does the conversion and rejects out-of-range letters
before anything is sent.
"""

import pytest

from nodes.google_sheets_node import (
    GoogleSheetsAddDimensionGroupConfig,
    GoogleSheetsAddFilterViewConfig,
    GoogleSheetsAddSlicerConfig,
    GoogleSheetsDeleteDimensionGroupConfig,
    GoogleSheetsDeleteFilterViewConfig,
    GoogleSheetsDuplicateFilterViewConfig,
    GoogleSheetsNode,
    GoogleSheetsNodeConfig,
    GoogleSheetsUpdateDimensionGroupConfig,
    GoogleSheetsUpdateFilterViewConfig,
    GoogleSheetsUpdateSlicerConfig,
    hex_to_color,
)

SHEET_ID = 31


class _Recorder:
    def __init__(self, node, sheet_entry=None, reply=None):
        self.requests = []
        self.sheet_entry = sheet_entry or {}
        self.reply = reply or {"replies": [{}]}
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


class TestFilterViews:
    @pytest.mark.asyncio
    async def test_sort_column_is_relative_to_the_view_range(self):
        """A view over A1:X13 makes Q index 16; over Q1:X13 it would be 0."""
        node = _node()
        rec = _Recorder(
            node, reply={"replies": [{"addFilterView": {"filter": {"filterViewId": 5}}}]}
        )
        out = await node._add_filter_view(
            GoogleSheetsAddFilterViewConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", view_title="Priority targets",
                range="A1:X13", sort_column="Q", sort_order="DESCENDING",
            ),
            "token",
        )
        view = rec.only["addFilterView"]["filter"]
        assert view["title"] == "Priority targets"
        assert view["sortSpecs"] == [{"dimensionIndex": 16, "sortOrder": "DESCENDING"}]
        assert out["filter_view_id"] == 5

    @pytest.mark.asyncio
    async def test_offset_range_shifts_the_sort_index(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_filter_view(
            GoogleSheetsAddFilterViewConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", view_title="V",
                range="Q1:X13", sort_column="Q",
            ),
            "token",
        )
        assert rec.only["addFilterView"]["filter"]["sortSpecs"][0]["dimensionIndex"] == 0

    @pytest.mark.asyncio
    async def test_hidden_values_are_keyed_by_relative_index(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_filter_view(
            GoogleSheetsAddFilterViewConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", view_title="Open only",
                range="A1:X13", hide_values='[{"column": "R", "hide": "Won, Passed"}]',
            ),
            "token",
        )
        criteria = rec.only["addFilterView"]["filter"]["criteria"]
        assert criteria == {"17": {"hiddenValues": ["Won", "Passed"]}}

    @pytest.mark.asyncio
    async def test_empty_range_covers_the_whole_sheet(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_filter_view(
            GoogleSheetsAddFilterViewConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", view_title="Everything"
            ),
            "token",
        )
        assert rec.only["addFilterView"]["filter"]["range"] == {"sheetId": SHEET_ID}

    @pytest.mark.asyncio
    async def test_sort_column_outside_the_range_is_rejected(self):
        node = _node()
        rec = _Recorder(node)
        with pytest.raises(ValueError, match="falls outside the view range"):
            await node._add_filter_view(
                GoogleSheetsAddFilterViewConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", view_title="V",
                    range="A1:D13", sort_column="Z",
                ),
                "token",
            )
        assert rec.requests == []

    @pytest.mark.asyncio
    async def test_hide_values_without_values_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="no values to hide"):
            await node._add_filter_view(
                GoogleSheetsAddFilterViewConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", view_title="V",
                    range="A1:X13", hide_values='[{"column": "R"}]',
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_update_resolves_by_title(self):
        node = _node()
        rec = _Recorder(
            node, {"filterViews": [{"title": "Priority targets", "filterViewId": 5,
                                    "range": {"sheetId": SHEET_ID, "startColumnIndex": 0}}]}
        )
        await node._update_filter_view(
            GoogleSheetsUpdateFilterViewConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", view_title="Priority targets",
                new_title="Tier 1 only",
            ),
            "token",
        )
        request = rec.only["updateFilterView"]
        assert request["filter"] == {"filterViewId": 5, "title": "Tier 1 only"}
        assert request["fields"] == "title"

    @pytest.mark.asyncio
    async def test_update_with_nothing_to_change_is_rejected(self):
        node = _node()
        _Recorder(node, {"filterViews": [{"title": "V", "filterViewId": 5}]})
        with pytest.raises(ValueError, match="Nothing to change"):
            await node._update_filter_view(
                GoogleSheetsUpdateFilterViewConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", view_title="V"
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_duplicate(self):
        node = _node()
        rec = _Recorder(
            node,
            {"filterViews": [{"title": "V", "filterViewId": 5}]},
            {"replies": [{"duplicateFilterView": {"filter": {"filterViewId": 6, "title": "Copy of V"}}}]},
        )
        out = await node._duplicate_filter_view(
            GoogleSheetsDuplicateFilterViewConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", view_title="V"
            ),
            "token",
        )
        assert rec.only["duplicateFilterView"] == {"filterId": 5}
        assert out["new_filter_view_id"] == 6

    @pytest.mark.asyncio
    async def test_delete(self):
        node = _node()
        rec = _Recorder(node, {"filterViews": [{"title": "V", "filterViewId": 5}]})
        await node._delete_filter_view(
            GoogleSheetsDeleteFilterViewConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", view_title="V"
            ),
            "token",
        )
        assert rec.only["deleteFilterView"] == {"filterId": 5}

    @pytest.mark.asyncio
    async def test_unknown_view_lists_what_is_there(self):
        node = _node()
        rec = _Recorder(node, {"filterViews": [{"title": "V", "filterViewId": 5}]})
        with pytest.raises(ValueError, match="Views here: V"):
            await node._delete_filter_view(
                GoogleSheetsDeleteFilterViewConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", view_title="Missing"
                ),
                "token",
            )
        assert rec.requests == []


class TestDimensionGroups:
    @pytest.mark.asyncio
    async def test_group_converts_to_half_open_indices(self):
        node = _node()
        rec = _Recorder(node)
        await node._group_dimension(
            GoogleSheetsAddDimensionGroupConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", dimension="COLUMNS",
                start_index=6, end_index=17,
            ),
            "token",
        )
        assert rec.only["addDimensionGroup"]["range"] == {
            "sheetId": SHEET_ID,
            "dimension": "COLUMNS",
            "startIndex": 5,
            "endIndex": 17,
        }

    @pytest.mark.asyncio
    async def test_collapse(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._collapse_group(
            GoogleSheetsUpdateDimensionGroupConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", start_index=2, end_index=10
            ),
            "token",
        )
        request = rec.only["updateDimensionGroup"]
        assert request["dimensionGroup"]["collapsed"] is True
        assert request["fields"] == "collapsed"
        assert out["collapsed"] is True

    @pytest.mark.asyncio
    async def test_expand(self):
        node = _node()
        rec = _Recorder(node)
        await node._collapse_group(
            GoogleSheetsUpdateDimensionGroupConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", start_index=2, end_index=10,
                collapsed="false",
            ),
            "token",
        )
        assert rec.only["updateDimensionGroup"]["dimensionGroup"]["collapsed"] is False

    @pytest.mark.asyncio
    async def test_ungroup(self):
        node = _node()
        rec = _Recorder(node)
        await node._ungroup_dimension(
            GoogleSheetsDeleteDimensionGroupConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", start_index=2, end_index=10
            ),
            "token",
        )
        assert rec.only["deleteDimensionGroup"]["range"]["startIndex"] == 1

    @pytest.mark.asyncio
    async def test_reversed_group_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="comes before the start"):
            await node._group_dimension(
                GoogleSheetsAddDimensionGroupConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", start_index=10, end_index=2
                ),
                "token",
            )


class TestSlicers:
    @pytest.mark.asyncio
    async def test_column_index_is_relative_to_the_data_range(self):
        node = _node()
        rec = _Recorder(node, reply={"replies": [{"addSlicer": {"slicer": {"slicerId": 8}}}]})
        out = await node._add_slicer(
            GoogleSheetsAddSlicerConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1:X13",
                filter_column="R", anchor_cell="Z2", slicer_title="Status",
                background_color="#E3F0EB",
            ),
            "token",
        )
        spec = rec.only["addSlicer"]["slicer"]["spec"]
        assert spec["columnIndex"] == 17
        assert spec["title"] == "Status"
        assert spec["backgroundColor"] == hex_to_color("#E3F0EB")
        anchor = rec.only["addSlicer"]["slicer"]["position"]["overlayPosition"]["anchorCell"]
        assert anchor == {"sheetId": SHEET_ID, "rowIndex": 1, "columnIndex": 25}
        assert out["slicer_id"] == 8

    @pytest.mark.asyncio
    async def test_filter_column_outside_the_data_range_is_rejected(self):
        node = _node()
        rec = _Recorder(node)
        with pytest.raises(ValueError, match="falls outside the data range"):
            await node._add_slicer(
                GoogleSheetsAddSlicerConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", range="A1:D13",
                    filter_column="Z", anchor_cell="F2",
                ),
                "token",
            )
        assert rec.requests == []

    @pytest.mark.asyncio
    async def test_update_resolves_by_title_and_masks_fields(self):
        node = _node()
        rec = _Recorder(
            node,
            {"slicers": [{"slicerId": 8, "spec": {"title": "Status",
                                                  "dataRange": {"sheetId": SHEET_ID, "startColumnIndex": 0}}}]},
        )
        await node._update_slicer(
            GoogleSheetsUpdateSlicerConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", slicer_title="Status",
                new_title="Outreach stage", filter_column="R",
            ),
            "token",
        )
        request = rec.only["updateSlicerSpec"]
        assert request["slicerId"] == 8
        assert request["spec"] == {"title": "Outreach stage", "columnIndex": 17}
        assert set(request["fields"].split(",")) == {"title", "columnIndex"}

    @pytest.mark.asyncio
    async def test_update_with_nothing_to_change_is_rejected(self):
        node = _node()
        _Recorder(node, {"slicers": [{"slicerId": 8, "spec": {"title": "Status"}}]})
        with pytest.raises(ValueError, match="Nothing to change"):
            await node._update_slicer(
                GoogleSheetsUpdateSlicerConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", slicer_title="Status"
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_unknown_slicer_lists_what_is_there(self):
        node = _node()
        _Recorder(node, {"slicers": [{"slicerId": 8, "spec": {"title": "Status"}}]})
        with pytest.raises(ValueError, match="Slicers here: Status"):
            await node._update_slicer(
                GoogleSheetsUpdateSlicerConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", slicer_title="Nope", new_title="X"
                ),
                "token",
            )


class TestConfigParsing:
    NEW_OPERATIONS = [
        ("save_filter_view", {"view_title": "V"}),
        ("update_filter_view", {"view_title": "V", "new_title": "W"}),
        ("duplicate_filter_view", {"view_title": "V"}),
        ("delete_filter_view", {"view_title": "V"}),
        ("group_rows_or_columns", {"start_index": 1, "end_index": 5}),
        ("collapse_group", {"start_index": 1, "end_index": 5}),
        ("ungroup_rows_or_columns", {"start_index": 1, "end_index": 5}),
        ("add_slicer", {"range": "A1:D9", "filter_column": "B", "anchor_cell": "F2"}),
        ("update_slicer", {"slicer_title": "S", "new_title": "T"}),
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
