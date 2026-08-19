"""Google Sheets presentation operations.

The values API speaks A1; every formatting request speaks GridRange. These
tests pin that translation, and pin the property that makes `format_cells`
safe to call repeatedly: the `fields` mask must name only what the caller
actually set, so applying a background never wipes an existing font.
"""

import pytest

from nodes.google_sheets_node import (
    GoogleSheetsAddBandingConfig,
    GoogleSheetsAutoResizeConfig,
    GoogleSheetsConditionalFormatConfig,
    GoogleSheetsFormatCellsConfig,
    GoogleSheetsNode,
    GoogleSheetsNodeConfig,
    GoogleSheetsSortRangeConfig,
    GoogleSheetsUpdateBordersConfig,
    GoogleSheetsUpdateSheetPropertiesConfig,
    a1_range_to_grid_range,
    column_letters_to_index,
    hex_to_color,
)

SHEET_ID = 42


class _Recorder:
    """Stands in for the batchUpdate sender and the sheet-id lookup."""

    def __init__(self, node):
        self.requests = []
        node._send_batch_update = self._send
        node._get_sheet_id = self._sheet_id

    async def _send(self, spreadsheet_id, requests, access_token):
        self.requests.append(requests)
        return {"replies": [{}]}

    async def _sheet_id(self, spreadsheet_id, sheet_name, access_token):
        return SHEET_ID

    @property
    def only(self):
        assert len(self.requests) == 1
        assert len(self.requests[0]) == 1
        return self.requests[0][0]


def _node():
    return GoogleSheetsNode.__new__(GoogleSheetsNode)


class TestColumnLetters:
    @pytest.mark.parametrize(
        "letters,index", [("A", 0), ("B", 1), ("Z", 25), ("AA", 26), ("AB", 27), ("BA", 52)]
    )
    def test_letters_map_to_zero_based_index(self, letters, index):
        assert column_letters_to_index(letters) == index


class TestA1ToGridRange:
    def test_bounded_range(self):
        assert a1_range_to_grid_range("A1:D10", SHEET_ID) == {
            "sheetId": SHEET_ID,
            "startColumnIndex": 0,
            "endColumnIndex": 4,
            "startRowIndex": 0,
            "endRowIndex": 10,
        }

    def test_single_cell_is_a_one_by_one_range(self):
        assert a1_range_to_grid_range("B7", SHEET_ID) == {
            "sheetId": SHEET_ID,
            "startColumnIndex": 1,
            "endColumnIndex": 2,
            "startRowIndex": 6,
            "endRowIndex": 7,
        }

    def test_whole_columns_leave_rows_unbounded(self):
        grid = a1_range_to_grid_range("A:D", SHEET_ID)
        assert grid == {"sheetId": SHEET_ID, "startColumnIndex": 0, "endColumnIndex": 4}
        assert "startRowIndex" not in grid

    def test_whole_rows_leave_columns_unbounded(self):
        grid = a1_range_to_grid_range("2:10", SHEET_ID)
        assert grid == {"sheetId": SHEET_ID, "startRowIndex": 1, "endRowIndex": 10}
        assert "startColumnIndex" not in grid

    def test_empty_range_is_the_whole_sheet(self):
        assert a1_range_to_grid_range("", SHEET_ID) == {"sheetId": SHEET_ID}

    def test_sheet_qualified_range_drops_the_sheet_prefix(self):
        # The sheet is already identified by sheetId; a stale prefix must not leak in.
        assert a1_range_to_grid_range("Priority 12!A1:B2", SHEET_ID) == {
            "sheetId": SHEET_ID,
            "startColumnIndex": 0,
            "endColumnIndex": 2,
            "startRowIndex": 0,
            "endRowIndex": 2,
        }

    def test_absolute_references_are_accepted(self):
        assert a1_range_to_grid_range("$A$1:$B$2", SHEET_ID)["endColumnIndex"] == 2

    def test_lowercase_is_accepted(self):
        assert a1_range_to_grid_range("a1:d10", SHEET_ID)["endColumnIndex"] == 4

    def test_multi_letter_columns(self):
        assert a1_range_to_grid_range("Z1:AA2", SHEET_ID)["endColumnIndex"] == 27

    def test_reversed_range_is_rejected(self):
        with pytest.raises(ValueError, match="comes before the start"):
            a1_range_to_grid_range("D10:A1", SHEET_ID)

    def test_garbage_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid A1 range"):
            a1_range_to_grid_range("not a range", SHEET_ID)


class TestHexToColor:
    def test_six_digit_hex(self):
        assert hex_to_color("#FFFFFF") == {"red": 1.0, "green": 1.0, "blue": 1.0}

    def test_hash_is_optional_and_case_insensitive(self):
        assert hex_to_color("000000") == hex_to_color("#000000")
        assert hex_to_color("#1b6e5a") == hex_to_color("#1B6E5A")

    def test_shorthand_expands(self):
        assert hex_to_color("#FFF") == hex_to_color("#FFFFFF")

    def test_channel_values_are_normalised(self):
        colour = hex_to_color("#FF8000")
        assert colour["red"] == 1.0
        assert colour["blue"] == 0.0
        assert 0.5 < colour["green"] < 0.51

    def test_none_and_empty_pass_through(self):
        assert hex_to_color(None) is None
        assert hex_to_color("   ") is None

    def test_invalid_hex_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid colour"):
            hex_to_color("#GGGGGG")


class TestFormatCells:
    @pytest.mark.asyncio
    async def test_fields_mask_names_only_what_was_set(self):
        """The invariant: formatting one property must not clear the others."""
        node = _node()
        rec = _Recorder(node)
        await node._format_cells(
            GoogleSheetsFormatCellsConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1:D1", bold="true"
            ),
            "token",
        )
        repeat = rec.only["repeatCell"]
        assert repeat["fields"] == "userEnteredFormat.textFormat.bold"
        assert repeat["cell"]["userEnteredFormat"] == {"textFormat": {"bold": True}}
        assert "backgroundColor" not in repeat["cell"]["userEnteredFormat"]

    @pytest.mark.asyncio
    async def test_header_styling_builds_expected_request(self):
        node = _node()
        rec = _Recorder(node)
        await node._format_cells(
            GoogleSheetsFormatCellsConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="A1:D1",
                bold="true",
                background_color="#1B6E5A",
                text_color="#FFFFFF",
                horizontal_alignment="CENTER",
            ),
            "token",
        )
        repeat = rec.only["repeatCell"]
        fmt = repeat["cell"]["userEnteredFormat"]
        assert fmt["textFormat"]["bold"] is True
        assert fmt["textFormat"]["foregroundColor"] == {"red": 1.0, "green": 1.0, "blue": 1.0}
        assert fmt["horizontalAlignment"] == "CENTER"
        assert repeat["range"]["sheetId"] == SHEET_ID
        for field in (
            "userEnteredFormat.textFormat.bold",
            "userEnteredFormat.backgroundColor",
            "userEnteredFormat.horizontalAlignment",
        ):
            assert field in repeat["fields"]

    @pytest.mark.asyncio
    async def test_bold_false_is_sent_not_skipped(self):
        """Explicitly un-bolding must reach the API, not be treated as 'unset'."""
        node = _node()
        rec = _Recorder(node)
        await node._format_cells(
            GoogleSheetsFormatCellsConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1", bold="false"
            ),
            "token",
        )
        repeat = rec.only["repeatCell"]
        assert repeat["cell"]["userEnteredFormat"]["textFormat"]["bold"] is False
        assert repeat["fields"] == "userEnteredFormat.textFormat.bold"

    @pytest.mark.asyncio
    async def test_currency_pattern(self):
        node = _node()
        rec = _Recorder(node)
        await node._format_cells(
            GoogleSheetsFormatCellsConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="F2:F100",
                number_format_type="CURRENCY",
                number_format_pattern="$#,##0.00",
            ),
            "token",
        )
        fmt = rec.only["repeatCell"]["cell"]["userEnteredFormat"]
        assert fmt["numberFormat"] == {"type": "CURRENCY", "pattern": "$#,##0.00"}

    @pytest.mark.asyncio
    async def test_empty_format_is_rejected_rather_than_sent(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="No formatting was specified"):
            await node._format_cells(
                GoogleSheetsFormatCellsConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", range="A1:D1"
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_pattern_without_type_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="needs a number format type"):
            await node._format_cells(
                GoogleSheetsFormatCellsConfig(
                    spreadsheet_id="ss",
                    sheet_name="Sheet1",
                    range="A1",
                    number_format_pattern="$#,##0.00",
                ),
                "token",
            )


class TestSheetProperties:
    @pytest.mark.asyncio
    async def test_freeze_header_row(self):
        node = _node()
        rec = _Recorder(node)
        await node._update_sheet_properties(
            GoogleSheetsUpdateSheetPropertiesConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", frozen_row_count=1
            ),
            "token",
        )
        update = rec.only["updateSheetProperties"]
        assert update["properties"]["gridProperties"]["frozenRowCount"] == 1
        assert update["properties"]["sheetId"] == SHEET_ID
        assert update["fields"] == "gridProperties.frozenRowCount"

    @pytest.mark.asyncio
    async def test_unfreezing_to_zero_is_sent(self):
        node = _node()
        rec = _Recorder(node)
        await node._update_sheet_properties(
            GoogleSheetsUpdateSheetPropertiesConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", frozen_row_count=0
            ),
            "token",
        )
        assert (
            rec.only["updateSheetProperties"]["properties"]["gridProperties"]["frozenRowCount"] == 0
        )

    @pytest.mark.asyncio
    async def test_no_properties_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="No sheet properties"):
            await node._update_sheet_properties(
                GoogleSheetsUpdateSheetPropertiesConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1"
                ),
                "token",
            )


class TestDimensions:
    @pytest.mark.asyncio
    async def test_auto_resize_converts_to_half_open_indices(self):
        node = _node()
        rec = _Recorder(node)
        await node._auto_resize_dimensions(
            GoogleSheetsAutoResizeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", start_index=1, end_index=26
            ),
            "token",
        )
        dims = rec.only["autoResizeDimensions"]["dimensions"]
        assert dims == {
            "sheetId": SHEET_ID,
            "dimension": "COLUMNS",
            "startIndex": 0,
            "endIndex": 26,
        }

    @pytest.mark.asyncio
    async def test_open_ended_resize_omits_end_index(self):
        node = _node()
        rec = _Recorder(node)
        await node._auto_resize_dimensions(
            GoogleSheetsAutoResizeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", start_index=3
            ),
            "token",
        )
        assert "endIndex" not in rec.only["autoResizeDimensions"]["dimensions"]


class TestBorders:
    @pytest.mark.asyncio
    async def test_outer_only_sets_four_edges(self):
        node = _node()
        rec = _Recorder(node)
        await node._update_borders(
            GoogleSheetsUpdateBordersConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="A1:D10", apply_to="OUTER"
            ),
            "token",
        )
        request = rec.only["updateBorders"]
        assert set(request) == {"range", "top", "bottom", "left", "right"}

    @pytest.mark.asyncio
    async def test_bottom_only_underlines_a_header(self):
        node = _node()
        rec = _Recorder(node)
        await node._update_borders(
            GoogleSheetsUpdateBordersConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="A1:D1",
                apply_to="BOTTOM",
                border_style="SOLID_MEDIUM",
            ),
            "token",
        )
        request = rec.only["updateBorders"]
        assert set(request) == {"range", "bottom"}
        assert request["bottom"]["style"] == "SOLID_MEDIUM"


class TestBanding:
    @pytest.mark.asyncio
    async def test_band_colours_are_converted(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_banding(
            GoogleSheetsAddBandingConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="A1:Z100",
                header_color="#1B6E5A",
            ),
            "token",
        )
        row_properties = rec.only["addBanding"]["bandedRange"]["rowProperties"]
        assert row_properties["headerColor"] == hex_to_color("#1B6E5A")
        assert row_properties["firstBandColor"] == hex_to_color("#FFFFFF")
        assert row_properties["secondBandColor"] == hex_to_color("#F1F3F2")


class TestConditionalFormat:
    @pytest.mark.asyncio
    async def test_single_value_condition(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_conditional_format_rule(
            GoogleSheetsConditionalFormatConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="G2:G100",
                condition_type="NUMBER_GREATER",
                value="40",
                background_color="#E3F0EB",
            ),
            "token",
        )
        rule = rec.only["addConditionalFormatRule"]["rule"]
        assert rule["booleanRule"]["condition"] == {
            "type": "NUMBER_GREATER",
            "values": [{"userEnteredValue": "40"}],
        }
        assert rule["ranges"][0]["sheetId"] == SHEET_ID

    @pytest.mark.asyncio
    async def test_blank_condition_carries_no_values(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_conditional_format_rule(
            GoogleSheetsConditionalFormatConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="A2:A100",
                condition_type="NOT_BLANK",
                bold="true",
            ),
            "token",
        )
        condition = rec.only["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]
        assert condition == {"type": "NOT_BLANK"}

    @pytest.mark.asyncio
    async def test_between_requires_both_bounds(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="both Value and Second Value"):
            await node._add_conditional_format_rule(
                GoogleSheetsConditionalFormatConfig(
                    spreadsheet_id="ss",
                    sheet_name="Sheet1",
                    range="A2:A100",
                    condition_type="NUMBER_BETWEEN",
                    value="1",
                    background_color="#FFFFFF",
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_rule_without_formatting_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="no formatting to apply"):
            await node._add_conditional_format_rule(
                GoogleSheetsConditionalFormatConfig(
                    spreadsheet_id="ss",
                    sheet_name="Sheet1",
                    range="A2:A100",
                    condition_type="NOT_BLANK",
                ),
                "token",
            )


class TestSortRange:
    @pytest.mark.asyncio
    async def test_sort_column_is_relative_to_the_range(self):
        """sortRange indexes within the range, so column C of C2:F100 is index 0."""
        node = _node()
        rec = _Recorder(node)
        await node._sort_range(
            GoogleSheetsSortRangeConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="C2:F100",
                sort_column=3,
                sort_order="DESCENDING",
            ),
            "token",
        )
        spec = rec.only["sortRange"]["sortSpecs"][0]
        assert spec == {"dimensionIndex": 0, "sortOrder": "DESCENDING"}

    @pytest.mark.asyncio
    async def test_sort_column_outside_the_range_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="falls outside the range"):
            await node._sort_range(
                GoogleSheetsSortRangeConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", range="C2:F100", sort_column=1
                ),
                "token",
            )


class TestConfigParsing:
    """Every new operation must resolve through the discriminated union."""

    NEW_OPERATIONS = [
        ("format_cells", {"range": "A1", "bold": "true"}),
        ("update_sheet_properties", {"frozen_row_count": 1}),
        ("auto_resize_dimensions", {}),
        ("set_dimension_size", {"start_index": 1, "pixel_size": 200}),
        ("merge_cells", {"range": "A1:D1"}),
        ("unmerge_cells", {"range": "A1:D1"}),
        ("format_borders", {"range": "A1:D1"}),
        ("add_alternating_colors", {"range": "A1:Z100"}),
        ("set_basic_filter", {}),
        ("clear_basic_filter", {}),
        (
            "add_conditional_format_rule",
            {"range": "A1:A9", "condition_type": "NOT_BLANK", "bold": "true"},
        ),
        ("sort_range", {"range": "A2:D9", "sort_column": 1}),
    ]

    @pytest.mark.parametrize("operation,extra", NEW_OPERATIONS)
    def test_operation_parses(self, operation, extra):
        config = GoogleSheetsNodeConfig(
            config={
                "operation": operation,
                "spreadsheet_id": "ss",
                "sheet_name": "Sheet1",
                **extra,
            }
        )
        assert config.config.operation == operation

    @pytest.mark.parametrize("operation,extra", NEW_OPERATIONS)
    def test_operation_is_dispatchable(self, operation, extra):
        """A config in the union with no isinstance branch raises 'Unexpected config type'.

        Checked against the parsed config's own class, not its handler name —
        several handlers are deliberately named differently from the operation.
        """
        import inspect

        parsed = GoogleSheetsNodeConfig(
            config={
                "operation": operation,
                "spreadsheet_id": "ss",
                "sheet_name": "Sheet1",
                **extra,
            }
        ).config
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
