"""Google Sheets coverage phase 2 — values, cells and data wrangling.

Notes, smart chips and pivot tables have no dedicated request; they ride on
updateCells/repeatCell, so the `fields` mask is what makes them safe. The rest
are the range operations the UI exposes under Data and Edit.

The recurring trap across this family is the index frame: users name columns by
sheet letter, but pivot offsets and dedupe comparison columns are relative to
their own source range, and dimension indexes are 1-based inclusive on the way
in and half-open zero-based on the way out.
"""

import pytest

from nodes.google_sheets_node import (
    GoogleSheetsAppendDimensionConfig,
    GoogleSheetsAutoFillConfig,
    GoogleSheetsCopyPasteConfig,
    GoogleSheetsCutPasteConfig,
    GoogleSheetsDeleteDuplicatesConfig,
    GoogleSheetsDeleteRangeConfig,
    GoogleSheetsInsertRangeConfig,
    GoogleSheetsMoveDimensionConfig,
    GoogleSheetsNode,
    GoogleSheetsNodeConfig,
    GoogleSheetsPasteDataConfig,
    GoogleSheetsPivotTableConfig,
    GoogleSheetsRandomizeRangeConfig,
    GoogleSheetsSetNotesConfig,
    GoogleSheetsSmartChipsConfig,
    GoogleSheetsTextToColumnsConfig,
    GoogleSheetsTrimWhitespaceConfig,
)

SHEET_ID = 11


class _Recorder:
    def __init__(self, node, reply=None):
        self.requests = []
        self.reply = reply or {"replies": [{}]}
        node._send_batch_update = self._send
        node._get_sheet_id = self._sheet_id

    async def _send(self, spreadsheet_id, requests, access_token):
        self.requests.append(requests)
        return self.reply

    async def _sheet_id(self, spreadsheet_id, sheet_name, access_token):
        return SHEET_ID

    @property
    def only(self):
        assert len(self.requests) == 1 and len(self.requests[0]) == 1
        return self.requests[0][0]


def _node():
    return GoogleSheetsNode.__new__(GoogleSheetsNode)


class TestCellNotes:
    @pytest.mark.asyncio
    async def test_note_is_written_with_a_note_only_field_mask(self):
        """A note must not disturb the cell's value or formatting."""
        node = _node()
        rec = _Recorder(node)
        await node._set_cell_notes(
            GoogleSheetsSetNotesConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A2:A10", note="Check this"
            ),
            "token",
        )
        request = rec.only["repeatCell"]
        assert request["fields"] == "note"
        assert request["cell"] == {"note": "Check this"}

    @pytest.mark.asyncio
    async def test_empty_note_clears_rather_than_being_treated_as_unset(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._set_cell_notes(
            GoogleSheetsSetNotesConfig(spreadsheet_id="ss", sheet_name="Sheet1", range="A2:A10"),
            "token",
        )
        assert rec.only["repeatCell"]["cell"] == {"note": ""}
        assert out["cleared"] is True


class TestSmartChips:
    @pytest.mark.asyncio
    async def test_person_chips(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._insert_smart_chips(
            GoogleSheetsSmartChipsConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="S2:S4",
                values="sam@example.com, alex@example.com",
            ),
            "token",
        )
        request = rec.only["updateCells"]
        assert request["fields"] == "userEnteredValue,chipRuns"
        first = request["rows"][0]["values"][0]
        assert first["chipRuns"][0]["chip"]["personProperties"]["email"] == "sam@example.com"
        assert first["chipRuns"][0]["startIndex"] == 0
        # the chip needs backing text to render over
        assert first["userEnteredValue"]["stringValue"] == "sam@example.com"
        assert out["chips_written"] == 2

    @pytest.mark.asyncio
    async def test_link_chips(self):
        node = _node()
        rec = _Recorder(node)
        await node._insert_smart_chips(
            GoogleSheetsSmartChipsConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="S2:S2",
                chip_type="link",
                values="https://example.com",
            ),
            "token",
        )
        chip = rec.only["updateCells"]["rows"][0]["values"][0]["chipRuns"][0]["chip"]
        assert chip["richLinkProperties"] == {"uri": "https://example.com"}

    @pytest.mark.asyncio
    async def test_display_format_is_passed_through(self):
        node = _node()
        rec = _Recorder(node)
        await node._insert_smart_chips(
            GoogleSheetsSmartChipsConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="S2:S2",
                values="sam@example.com",
                display_format="EMAIL",
            ),
            "token",
        )
        person = rec.only["updateCells"]["rows"][0]["values"][0]["chipRuns"][0]["chip"][
            "personProperties"
        ]
        assert person["displayFormat"] == "EMAIL"

    @pytest.mark.asyncio
    async def test_multi_column_range_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="single column"):
            await node._insert_smart_chips(
                GoogleSheetsSmartChipsConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", range="S2:T4", values="a@b.com"
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_more_values_than_cells_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="only covers 2 cell"):
            await node._insert_smart_chips(
                GoogleSheetsSmartChipsConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", range="S2:S3",
                    values="a@b.com, c@d.com, e@f.com",
                ),
                "token",
            )


class TestPivotTable:
    @pytest.mark.asyncio
    async def test_offsets_are_relative_to_the_source_range(self):
        """Source A1:Z100 starts at column A, so E is offset 4."""
        node = _node()
        rec = _Recorder(node)
        await node._insert_pivot_table(
            GoogleSheetsPivotTableConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                anchor_cell="AB1",
                source_range="A1:Z100",
                pivot_rows="E",
                pivot_values='[{"column": "F", "function": "SUM"}]',
            ),
            "token",
        )
        pivot = rec.only["updateCells"]["rows"][0]["values"][0]["pivotTable"]
        assert pivot["rows"][0]["sourceColumnOffset"] == 4
        assert pivot["values"][0] == {"sourceColumnOffset": 5, "summarizeFunction": "SUM"}

    @pytest.mark.asyncio
    async def test_offsets_shift_when_the_source_does_not_start_at_a(self):
        node = _node()
        rec = _Recorder(node)
        await node._insert_pivot_table(
            GoogleSheetsPivotTableConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                anchor_cell="A1",
                source_range="D1:H100",
                pivot_rows="D",
                pivot_values='[{"column": "E", "function": "COUNTA"}]',
            ),
            "token",
        )
        pivot = rec.only["updateCells"]["rows"][0]["values"][0]["pivotTable"]
        assert pivot["rows"][0]["sourceColumnOffset"] == 0
        assert pivot["values"][0]["sourceColumnOffset"] == 1

    @pytest.mark.asyncio
    async def test_anchor_is_a_coordinate_not_a_range(self):
        node = _node()
        rec = _Recorder(node)
        await node._insert_pivot_table(
            GoogleSheetsPivotTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", anchor_cell="C5",
                source_range="A1:Z100", pivot_rows="A",
                pivot_values='[{"column": "B", "function": "SUM"}]',
            ),
            "token",
        )
        start = rec.only["updateCells"]["start"]
        assert start == {"sheetId": SHEET_ID, "rowIndex": 4, "columnIndex": 2}

    @pytest.mark.asyncio
    async def test_unsupported_function_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="Unsupported function 'TOTAL'"):
            await node._insert_pivot_table(
                GoogleSheetsPivotTableConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", anchor_cell="A1",
                    source_range="A1:Z100", pivot_rows="A",
                    pivot_values='[{"column": "B", "function": "TOTAL"}]',
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_no_grouping_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="at least one Group"):
            await node._insert_pivot_table(
                GoogleSheetsPivotTableConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", anchor_cell="A1",
                    source_range="A1:Z100",
                    pivot_values='[{"column": "B", "function": "SUM"}]',
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_column_outside_the_source_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="falls outside the source range"):
            await node._insert_pivot_table(
                GoogleSheetsPivotTableConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", anchor_cell="A1",
                    source_range="A1:D100", pivot_rows="Z",
                    pivot_values='[{"column": "B", "function": "SUM"}]',
                ),
                "token",
            )


class TestCopyCutPaste:
    @pytest.mark.asyncio
    async def test_copy_values_only(self):
        node = _node()
        rec = _Recorder(node)
        await node._copy_paste_range(
            GoogleSheetsCopyPasteConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", source_range="A1:D10",
                destination_range="F1:I10", paste_type="PASTE_VALUES",
            ),
            "token",
        )
        request = rec.only["copyPaste"]
        assert request["pasteType"] == "PASTE_VALUES"
        assert request["pasteOrientation"] == "NORMAL"
        assert request["source"]["endColumnIndex"] == 4

    @pytest.mark.asyncio
    async def test_transpose(self):
        node = _node()
        rec = _Recorder(node)
        await node._copy_paste_range(
            GoogleSheetsCopyPasteConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", source_range="A1:D1",
                destination_range="F1:F4", transpose="true",
            ),
            "token",
        )
        assert rec.only["copyPaste"]["pasteOrientation"] == "TRANSPOSE"

    @pytest.mark.asyncio
    async def test_cut_paste_destination_is_a_coordinate(self):
        node = _node()
        rec = _Recorder(node)
        await node._cut_paste_range(
            GoogleSheetsCutPasteConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", source_range="A1:D10",
                destination_cell="F5",
            ),
            "token",
        )
        assert rec.only["cutPaste"]["destination"] == {
            "sheetId": SHEET_ID,
            "rowIndex": 4,
            "columnIndex": 5,
        }


class TestPasteData:
    @pytest.mark.asyncio
    async def test_delimited_text(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._paste_data(
            GoogleSheetsPasteDataConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", anchor_cell="B3",
                data="a,b\nc,d\n", delimiter=",",
            ),
            "token",
        )
        request = rec.only["pasteData"]
        assert request["coordinate"] == {"sheetId": SHEET_ID, "rowIndex": 2, "columnIndex": 1}
        assert request["delimiter"] == ","
        assert out["rows_pasted"] == 2


class TestTextToColumns:
    @pytest.mark.asyncio
    async def test_autodetect(self):
        node = _node()
        rec = _Recorder(node)
        await node._split_text_to_columns(
            GoogleSheetsTextToColumnsConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A2:A100"
            ),
            "token",
        )
        request = rec.only["textToColumns"]
        assert request["delimiterType"] == "AUTODETECT"
        assert "delimiter" not in request

    @pytest.mark.asyncio
    async def test_custom_requires_a_delimiter(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="Custom Delimiter is required"):
            await node._split_text_to_columns(
                GoogleSheetsTextToColumnsConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", range="A2:A100",
                    delimiter_type="CUSTOM",
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_custom_delimiter_is_sent(self):
        node = _node()
        rec = _Recorder(node)
        await node._split_text_to_columns(
            GoogleSheetsTextToColumnsConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A2:A100",
                delimiter_type="CUSTOM", custom_delimiter="|",
            ),
            "token",
        )
        assert rec.only["textToColumns"]["delimiter"] == "|"


class TestCleanup:
    @pytest.mark.asyncio
    async def test_trim_whitespace_reports_cells_changed(self):
        node = _node()
        rec = _Recorder(node, {"replies": [{"trimWhitespace": {"cellsChangedCount": 12}}]})
        out = await node._trim_whitespace(
            GoogleSheetsTrimWhitespaceConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A2:Z100"
            ),
            "token",
        )
        assert rec.only["trimWhitespace"]["range"]["sheetId"] == SHEET_ID
        assert out["cells_changed"] == 12

    @pytest.mark.asyncio
    async def test_dedupe_whole_rows_sends_no_comparison_columns(self):
        node = _node()
        rec = _Recorder(node, {"replies": [{"deleteDuplicates": {"duplicatesRemovedCount": 3}}]})
        out = await node._remove_duplicate_rows(
            GoogleSheetsDeleteDuplicatesConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A2:Z100"
            ),
            "token",
        )
        assert "comparisonColumns" not in rec.only["deleteDuplicates"]
        assert out["duplicates_removed"] == 3

    @pytest.mark.asyncio
    async def test_dedupe_comparison_columns_are_range_relative(self):
        """Range starts at B, so comparing B and E gives offsets 0 and 3."""
        node = _node()
        rec = _Recorder(node)
        await node._remove_duplicate_rows(
            GoogleSheetsDeleteDuplicatesConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="B2:Z100", compare_columns="B, E"
            ),
            "token",
        )
        specs = rec.only["deleteDuplicates"]["comparisonColumns"]
        assert [s["startIndex"] for s in specs] == [0, 3]
        assert all(s["dimension"] == "COLUMNS" for s in specs)

    @pytest.mark.asyncio
    async def test_dedupe_column_outside_the_range_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="falls outside the range"):
            await node._remove_duplicate_rows(
                GoogleSheetsDeleteDuplicatesConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", range="A2:D100", compare_columns="Z"
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_randomize(self):
        node = _node()
        rec = _Recorder(node)
        await node._randomize_range(
            GoogleSheetsRandomizeRangeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A2:Z100"
            ),
            "token",
        )
        assert rec.only["randomizeRange"]["range"]["startRowIndex"] == 1


class TestStructuralCellOps:
    @pytest.mark.asyncio
    async def test_insert_cells_shifts_rows(self):
        node = _node()
        rec = _Recorder(node)
        await node._insert_cells(
            GoogleSheetsInsertRangeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="B2:B10"
            ),
            "token",
        )
        assert rec.only["insertRange"]["shiftDimension"] == "ROWS"

    @pytest.mark.asyncio
    async def test_delete_cells_shifts_columns(self):
        node = _node()
        rec = _Recorder(node)
        await node._delete_cells(
            GoogleSheetsDeleteRangeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="B2:B10",
                shift_direction="COLUMNS",
            ),
            "token",
        )
        assert rec.only["deleteRange"]["shiftDimension"] == "COLUMNS"

    @pytest.mark.asyncio
    async def test_move_converts_one_based_inclusive_to_half_open(self):
        """Moving columns 2-4 before column 8 is source [1,4) → destination 7."""
        node = _node()
        rec = _Recorder(node)
        await node._move_dimension(
            GoogleSheetsMoveDimensionConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", start_index=2, end_index=4,
                destination_index=8,
            ),
            "token",
        )
        request = rec.only["moveDimension"]
        assert request["source"] == {
            "sheetId": SHEET_ID,
            "dimension": "COLUMNS",
            "startIndex": 1,
            "endIndex": 4,
        }
        assert request["destinationIndex"] == 7

    @pytest.mark.asyncio
    async def test_reversed_move_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="comes before the start"):
            await node._move_dimension(
                GoogleSheetsMoveDimensionConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", start_index=9, end_index=2,
                    destination_index=1,
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_append_dimension(self):
        node = _node()
        rec = _Recorder(node)
        await node._append_dimension(
            GoogleSheetsAppendDimensionConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", dimension="ROWS", length=100
            ),
            "token",
        )
        assert rec.only["appendDimension"] == {
            "sheetId": SHEET_ID,
            "dimension": "ROWS",
            "length": 100,
        }

    @pytest.mark.asyncio
    async def test_auto_fill(self):
        node = _node()
        rec = _Recorder(node)
        await node._auto_fill(
            GoogleSheetsAutoFillConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1:A100"
            ),
            "token",
        )
        assert rec.only["autoFill"]["useAlternateSeries"] is False


class TestConfigParsing:
    NEW_OPERATIONS = [
        ("set_cell_notes", {"range": "A2:A10", "note": "x"}),
        ("insert_smart_chips", {"range": "S2:S3", "values": "a@b.com"}),
        ("insert_pivot_table", {"anchor_cell": "A1", "source_range": "A1:Z9",
                                "pivot_rows": "A", "pivot_values": '[{"column":"B"}]'}),
        ("copy_paste_range", {"source_range": "A1:D5", "destination_range": "F1:I5"}),
        ("cut_paste_range", {"source_range": "A1:D5", "destination_cell": "F1"}),
        ("paste_data", {"anchor_cell": "A1", "data": "a,b"}),
        ("auto_fill", {"range": "A1:A9"}),
        ("split_text_to_columns", {"range": "A2:A9"}),
        ("trim_whitespace", {"range": "A2:Z9"}),
        ("remove_duplicate_rows", {"range": "A2:Z9"}),
        ("randomize_range", {"range": "A2:Z9"}),
        ("insert_cells", {"range": "B2:B9"}),
        ("delete_cells", {"range": "B2:B9"}),
        ("move_rows_or_columns", {"start_index": 1, "end_index": 2, "destination_index": 5}),
        ("append_rows_or_columns", {"length": 10}),
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
            assert operation in found, f"{operation} missing from generated schema"
