"""Two defects found by driving the Sheets node against real workbooks.

1. Typing a table column without naming it made the API rename it to
   "Column N", destroying the existing header. Converting a prospect sheet to
   a table wiped Status / Date contacted / Channel / Response in one call — a
   data-loss bug that succeeds silently.

2. fetch_spreadsheet_metadata returned a hand-picked subset that omitted
   tables, charts, banding and conditional formats entirely, so there was no
   way to see what a spreadsheet actually contained without opening it.
"""

import pytest

from nodes.google_sheets_node import (
    GoogleSheetsAddTableConfig,
    GoogleSheetsGetMetadataConfig,
    GoogleSheetsNode,
    GoogleSheetsUpdateTableConfig,
    column_index_to_letters,
    column_letters_to_index,
)

SHEET_ID = 51
HEADERS = [
    "Rank", "Tier", "Job title", "Country", "Company size", "Spend", "Rate",
    "Hire rate", "Active", "Budget", "Posted", "Age", "Fit", "Why", "Angle",
    "Watch", "URL", "Status", "Owner", "Date contacted", "Channel", "Response",
    "Next step", "Notes",
]


class _Recorder:
    def __init__(self, node, headers=None, sheet_entry=None):
        self.requests = []
        self.headers = HEADERS if headers is None else headers
        self.sheet_entry = sheet_entry or {}
        node._send_batch_update = self._send
        node._get_sheet_id = self._sheet_id
        node._fetch_sheet_entry = self._fetch
        node._read_header_row = self._read_headers

    async def _send(self, spreadsheet_id, requests, access_token):
        self.requests.append(requests)
        return {"replies": [{"addTable": {"table": {"tableId": "t1"}}}]}

    async def _sheet_id(self, spreadsheet_id, sheet_name, access_token):
        return SHEET_ID

    async def _fetch(self, spreadsheet_id, sheet_name, fields, access_token):
        return {"properties": {"sheetId": SHEET_ID, "title": sheet_name}, **self.sheet_entry}

    async def _read_headers(self, spreadsheet_id, sheet_name, grid_range, access_token):
        return self.headers

    @property
    def only(self):
        assert len(self.requests) == 1 and len(self.requests[0]) == 1
        return self.requests[0][0]


def _node():
    return GoogleSheetsNode.__new__(GoogleSheetsNode)


class TestColumnLetterRoundTrip:
    @pytest.mark.parametrize("index", [0, 1, 25, 26, 27, 51, 52, 701, 702])
    def test_index_to_letters_and_back(self, index):
        assert column_letters_to_index(column_index_to_letters(index)) == index

    @pytest.mark.parametrize(
        "index,letters", [(0, "A"), (25, "Z"), (26, "AA"), (27, "AB"), (51, "AZ"), (52, "BA")]
    )
    def test_known_values(self, index, letters):
        assert column_index_to_letters(index) == letters


class TestHeaderPreservation:
    @pytest.mark.asyncio
    async def test_unnamed_typed_column_keeps_its_existing_header(self):
        """The bug: this used to send no columnName, and the API wrote "Column 1"."""
        node = _node()
        rec = _Recorder(node)
        await node._add_table(
            GoogleSheetsAddTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1:X13",
                table_name="Prospects",
                columns='[{"column": "R", "type": "DROPDOWN", "values": "A, B"}]',
            ),
            "token",
        )
        prop = rec.only["addTable"]["table"]["columnProperties"][0]
        assert prop["columnIndex"] == 17
        assert prop["columnName"] == "Status"

    @pytest.mark.asyncio
    async def test_explicit_name_still_wins(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_table(
            GoogleSheetsAddTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1:X13",
                table_name="Prospects",
                columns='[{"column": "R", "type": "DROPDOWN", "name": "Stage", "values": "A"}]',
            ),
            "token",
        )
        assert rec.only["addTable"]["table"]["columnProperties"][0]["columnName"] == "Stage"

    @pytest.mark.asyncio
    async def test_several_columns_each_keep_their_own_header(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_table(
            GoogleSheetsAddTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1:X13",
                table_name="Prospects",
                columns='[{"column": "R", "type": "DROPDOWN", "values": "A"},'
                        ' {"column": "T", "type": "DATE"},'
                        ' {"column": "U", "type": "DROPDOWN", "values": "B"}]',
            ),
            "token",
        )
        names = [p["columnName"] for p in rec.only["addTable"]["table"]["columnProperties"]]
        assert names == ["Status", "Date contacted", "Channel"]

    @pytest.mark.asyncio
    async def test_headers_are_indexed_relative_to_the_table_range(self):
        """A table over R1:X13 gets a 7-wide header row, so R is headers[0]."""
        node = _node()
        rec = _Recorder(node, headers=["Status", "Owner", "Date contacted", "Channel"])
        await node._add_table(
            GoogleSheetsAddTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="R1:U13",
                table_name="Tracking",
                columns='[{"column": "U", "type": "DROPDOWN", "values": "A"}]',
            ),
            "token",
        )
        prop = rec.only["addTable"]["table"]["columnProperties"][0]
        assert prop["columnIndex"] == 3
        assert prop["columnName"] == "Channel"

    @pytest.mark.asyncio
    async def test_unreadable_header_row_degrades_rather_than_failing(self):
        """Losing name preservation is survivable; failing the operation is not."""
        node = _node()
        rec = _Recorder(node, headers=[])
        await node._add_table(
            GoogleSheetsAddTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1:X13",
                table_name="Prospects",
                columns='[{"column": "R", "type": "DROPDOWN", "values": "A"}]',
            ),
            "token",
        )
        prop = rec.only["addTable"]["table"]["columnProperties"][0]
        assert "columnName" not in prop

    @pytest.mark.asyncio
    async def test_update_table_preserves_headers_too(self):
        node = _node()
        rec = _Recorder(
            node,
            sheet_entry={"tables": [{"name": "Prospects", "tableId": "t1",
                                     "range": {"sheetId": SHEET_ID, "startColumnIndex": 0}}]},
        )
        await node._update_table(
            GoogleSheetsUpdateTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", table_name="Prospects",
                columns='[{"column": "R", "type": "DROPDOWN", "values": "A"}]',
            ),
            "token",
        )
        prop = rec.only["updateTable"]["table"]["columnProperties"][0]
        assert prop["columnName"] == "Status"

    @pytest.mark.asyncio
    async def test_no_columns_means_no_header_read(self):
        """A plain table must not pay for a values round-trip it cannot use."""
        node = _node()
        calls = []

        async def spy(*args, **kwargs):
            calls.append(args)
            return HEADERS

        rec = _Recorder(node)
        node._read_header_row = spy
        await node._add_table(
            GoogleSheetsAddTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1:X13", table_name="Plain"
            ),
            "token",
        )
        assert calls == []
        assert "columnProperties" not in rec.only["addTable"]["table"]


class TestStructureSummary:
    SHEET = {
        "tables": [{"name": "Prospects", "tableId": "t1"}],
        "charts": [{"chartId": 7, "spec": {"title": "Spend by tier"}}],
        "slicers": [{"slicerId": 3, "spec": {"title": "Status"}}],
        "filterViews": [{"title": "Priority", "filterViewId": 5}],
        "protectedRanges": [
            {"description": "Header row", "protectedRangeId": 9, "warningOnly": True}
        ],
        "bandedRanges": [{"bandedRangeId": 11}, {"bandedRangeId": 12}],
        "conditionalFormats": [{}, {}, {}],
    }

    def test_summarises_ids_and_names(self):
        out = GoogleSheetsNode._structure_summary(self.SHEET)
        assert out["tables"] == [{"name": "Prospects", "table_id": "t1"}]
        assert out["charts"] == [{"chart_id": 7, "title": "Spend by tier"}]
        assert out["slicers"] == [{"slicer_id": 3, "title": "Status"}]
        assert out["filter_views"] == [{"title": "Priority", "filter_view_id": 5}]
        assert out["protected_ranges"][0]["warning_only"] is True
        assert out["banded_range_ids"] == [11, 12]
        assert out["conditional_format_count"] == 3

    def test_empty_sheet_yields_empty_collections_not_nulls(self):
        out = GoogleSheetsNode._structure_summary({})
        assert out["tables"] == []
        assert out["charts"] == []
        assert out["banded_range_ids"] == []
        assert out["conditional_format_count"] == 0

    def test_counts_rather_than_dumping_conditional_formats(self):
        """A rule list is large and rarely actionable; the count is what callers use."""
        out = GoogleSheetsNode._structure_summary({"conditionalFormats": [{}] * 40})
        assert out["conditional_format_count"] == 40
        assert "conditionalFormats" not in out

    def test_untitled_chart_reports_none_rather_than_raising(self):
        out = GoogleSheetsNode._structure_summary({"charts": [{"chartId": 1, "spec": {}}]})
        assert out["charts"] == [{"chart_id": 1, "title": None}]


class TestMetadataConfig:
    def test_defaults_to_the_light_response(self):
        config = GoogleSheetsGetMetadataConfig(spreadsheet_id="ss")
        assert config.include_structure == "false"

    def test_opt_in_is_a_searchable_string_enum(self):
        schema = GoogleSheetsNode.get_config_schema()
        field = schema["$defs"]["GoogleSheetsGetMetadataConfig"]["properties"][
            "include_structure"
        ]
        assert field["enum"] == ["true", "false"]
        assert field["x-enum-searchable"] is True
