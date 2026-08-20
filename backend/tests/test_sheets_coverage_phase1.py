"""Google Sheets coverage phase 1 — update counterparts and range protection.

Two themes. First, several families could only ever ADD: banding, conditional
rules and tables had no in-place edit, which is what made a formatting script
one-way. Second, named and protected ranges were missing entirely.

Both named and protected ranges are addressed by a human-readable label rather
than an opaque id, so each handler resolves the id first and reports what does
exist when the lookup fails.
"""

import pytest

from nodes.google_sheets_node import (
    GoogleSheetsAddNamedRangeConfig,
    GoogleSheetsAddProtectedRangeConfig,
    GoogleSheetsDeleteNamedRangeConfig,
    GoogleSheetsDeleteProtectedRangeConfig,
    GoogleSheetsNode,
    GoogleSheetsNodeConfig,
    GoogleSheetsUpdateBandingConfig,
    GoogleSheetsUpdateConditionalFormatConfig,
    GoogleSheetsUpdateNamedRangeConfig,
    GoogleSheetsUpdateProtectedRangeConfig,
    GoogleSheetsUpdateSpreadsheetPropertiesConfig,
    GoogleSheetsUpdateTableConfig,
    hex_to_color,
)

SHEET_ID = 5


class _Recorder:
    def __init__(self, node, sheet_entry=None, named=None, reply=None):
        self.requests = []
        self.sheet_entry = sheet_entry or {}
        self.named = named or []
        self.reply = reply or {"replies": [{}]}
        node._send_batch_update = self._send
        node._get_sheet_id = self._sheet_id
        node._fetch_sheet_entry = self._fetch
        node._resolve_named_range = self._named

    async def _send(self, spreadsheet_id, requests, access_token):
        self.requests.append(requests)
        return self.reply

    async def _sheet_id(self, spreadsheet_id, sheet_name, access_token):
        return SHEET_ID

    async def _fetch(self, spreadsheet_id, sheet_name, fields, access_token):
        return {"properties": {"sheetId": SHEET_ID, "title": sheet_name}, **self.sheet_entry}

    async def _named(self, spreadsheet_id, range_name, access_token):
        for entry in self.named:
            if entry["name"] == range_name:
                return entry
        raise ValueError(f"No named range '{range_name}'. Named ranges here: none.")

    @property
    def only(self):
        assert len(self.requests) == 1 and len(self.requests[0]) == 1
        return self.requests[0][0]

    @property
    def batch(self):
        assert len(self.requests) == 1
        return self.requests[0]


def _node():
    return GoogleSheetsNode.__new__(GoogleSheetsNode)


class TestUpdateConditionalFormatRule:
    @pytest.mark.asyncio
    async def test_reordering_sends_new_index_and_no_rule(self):
        """Priority order is the whole point: first matching rule wins per cell."""
        node = _node()
        rec = _Recorder(node)
        out = await node._update_conditional_format_rule(
            GoogleSheetsUpdateConditionalFormatConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", rule_index=3, new_index=0
            ),
            "token",
        )
        request = rec.only["updateConditionalFormatRule"]
        assert request == {"sheetId": SHEET_ID, "index": 3, "newIndex": 0}
        assert "rule" not in request
        assert out["action"] == "moved"

    @pytest.mark.asyncio
    async def test_editing_replaces_the_rule_at_that_index(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._update_conditional_format_rule(
            GoogleSheetsUpdateConditionalFormatConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                rule_index=1,
                range="A2:A50",
                condition_type="NUMBER_GREATER",
                value="40",
                background_color="#E3F0EB",
            ),
            "token",
        )
        request = rec.only["updateConditionalFormatRule"]
        assert request["index"] == 1
        rule = request["rule"]
        assert rule["ranges"][0]["endRowIndex"] == 50
        assert rule["booleanRule"]["condition"]["type"] == "NUMBER_GREATER"
        assert out["action"] == "edited"

    @pytest.mark.asyncio
    async def test_editing_without_a_condition_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="needs a Condition"):
            await node._update_conditional_format_rule(
                GoogleSheetsUpdateConditionalFormatConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", rule_index=0
                ),
                "token",
            )


class TestUpdateBanding:
    @pytest.mark.asyncio
    async def test_recolours_every_band_on_the_sheet(self):
        node = _node()
        rec = _Recorder(node, {"bandedRanges": [{"bandedRangeId": 1}, {"bandedRangeId": 2}]})
        out = await node._update_banding(
            GoogleSheetsUpdateBandingConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", second_band_color="#EEEEEE"
            ),
            "token",
        )
        assert len(rec.batch) == 2
        request = rec.batch[0]["updateBanding"]
        assert request["fields"] == "rowProperties.secondBandColor"
        assert request["bandedRange"]["rowProperties"]["secondBandColor"] == hex_to_color("#EEEEEE")
        assert out["bands_updated"] == 2

    @pytest.mark.asyncio
    async def test_fields_mask_names_only_the_colours_given(self):
        node = _node()
        rec = _Recorder(node, {"bandedRanges": [{"bandedRangeId": 1}]})
        await node._update_banding(
            GoogleSheetsUpdateBandingConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                header_color="#1B6E5A",
                first_band_color="#FFFFFF",
            ),
            "token",
        )
        fields = rec.only["updateBanding"]["fields"]
        assert "rowProperties.headerColor" in fields
        assert "rowProperties.firstBandColor" in fields
        assert "secondBandColor" not in fields

    @pytest.mark.asyncio
    async def test_unbanded_sheet_points_at_the_add_operation(self):
        node = _node()
        _Recorder(node, {})
        with pytest.raises(ValueError, match="Use Add Alternating Colours first"):
            await node._update_banding(
                GoogleSheetsUpdateBandingConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", header_color="#000000"
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_no_colours_is_rejected(self):
        node = _node()
        _Recorder(node, {"bandedRanges": [{"bandedRangeId": 1}]})
        with pytest.raises(ValueError, match="No colours"):
            await node._update_banding(
                GoogleSheetsUpdateBandingConfig(spreadsheet_id="ss", sheet_name="Sheet1"), "token"
            )


class TestUpdateTable:
    @pytest.mark.asyncio
    async def test_rename_only_sends_a_name_field(self):
        node = _node()
        rec = _Recorder(node, {"tables": [{"name": "Prospects", "tableId": "t1"}]})
        await node._update_table(
            GoogleSheetsUpdateTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", table_name="Prospects", new_name="Leads"
            ),
            "token",
        )
        request = rec.only["updateTable"]
        assert request["fields"] == "name"
        assert request["table"] == {"tableId": "t1", "name": "Leads"}

    @pytest.mark.asyncio
    async def test_retyping_columns_without_resizing_uses_the_current_range(self):
        """Column letters are table-relative, so the existing range must be read."""
        node = _node()
        rec = _Recorder(
            node,
            {
                "tables": [
                    {
                        "name": "Prospects",
                        "tableId": "t1",
                        "range": {"sheetId": SHEET_ID, "startColumnIndex": 17},
                    }
                ]
            },
        )
        await node._update_table(
            GoogleSheetsUpdateTableConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                table_name="Prospects",
                columns='[{"column": "R", "type": "DROPDOWN", "values": "A, B"}]',
            ),
            "token",
        )
        prop = rec.only["updateTable"]["table"]["columnProperties"][0]
        assert prop["columnIndex"] == 0

    @pytest.mark.asyncio
    async def test_nothing_to_change_is_rejected(self):
        node = _node()
        _Recorder(node, {"tables": [{"name": "Prospects", "tableId": "t1"}]})
        with pytest.raises(ValueError, match="Nothing to change"):
            await node._update_table(
                GoogleSheetsUpdateTableConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", table_name="Prospects"
                ),
                "token",
            )


class TestSpreadsheetProperties:
    @pytest.mark.asyncio
    async def test_rename_spreadsheet(self):
        node = _node()
        rec = _Recorder(node)
        await node._update_spreadsheet_properties(
            GoogleSheetsUpdateSpreadsheetPropertiesConfig(spreadsheet_id="ss", title="Q3 Pipeline"),
            "token",
        )
        request = rec.only["updateSpreadsheetProperties"]
        assert request["properties"] == {"title": "Q3 Pipeline"}
        assert request["fields"] == "title"

    @pytest.mark.asyncio
    async def test_timezone_uses_the_camel_case_api_key(self):
        node = _node()
        rec = _Recorder(node)
        await node._update_spreadsheet_properties(
            GoogleSheetsUpdateSpreadsheetPropertiesConfig(
                spreadsheet_id="ss", time_zone="Europe/London"
            ),
            "token",
        )
        assert rec.only["updateSpreadsheetProperties"]["properties"] == {"timeZone": "Europe/London"}

    @pytest.mark.asyncio
    async def test_nothing_specified_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="No properties"):
            await node._update_spreadsheet_properties(
                GoogleSheetsUpdateSpreadsheetPropertiesConfig(spreadsheet_id="ss"), "token"
            )


class TestNamedRanges:
    @pytest.mark.asyncio
    async def test_add(self):
        node = _node()
        rec = _Recorder(
            node, reply={"replies": [{"addNamedRange": {"namedRange": {"namedRangeId": "n1"}}}]}
        )
        out = await node._add_named_range(
            GoogleSheetsAddNamedRangeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range_name="StatusOptions", range="A2:A10"
            ),
            "token",
        )
        named = rec.only["addNamedRange"]["namedRange"]
        assert named["name"] == "StatusOptions"
        assert named["range"]["startRowIndex"] == 1
        assert out["named_range_id"] == "n1"

    @pytest.mark.asyncio
    async def test_update_resolves_the_id_from_the_name(self):
        node = _node()
        rec = _Recorder(node, named=[{"name": "StatusOptions", "namedRangeId": "n1"}])
        await node._update_named_range(
            GoogleSheetsUpdateNamedRangeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range_name="StatusOptions", new_name="Stages"
            ),
            "token",
        )
        request = rec.only["updateNamedRange"]
        assert request["namedRange"] == {"namedRangeId": "n1", "name": "Stages"}
        assert request["fields"] == "name"

    @pytest.mark.asyncio
    async def test_update_with_nothing_to_change_is_rejected(self):
        node = _node()
        _Recorder(node, named=[{"name": "StatusOptions", "namedRangeId": "n1"}])
        with pytest.raises(ValueError, match="Nothing to change"):
            await node._update_named_range(
                GoogleSheetsUpdateNamedRangeConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", range_name="StatusOptions"
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_delete(self):
        node = _node()
        rec = _Recorder(node, named=[{"name": "StatusOptions", "namedRangeId": "n1"}])
        await node._delete_named_range(
            GoogleSheetsDeleteNamedRangeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range_name="StatusOptions"
            ),
            "token",
        )
        assert rec.only["deleteNamedRange"] == {"namedRangeId": "n1"}

    @pytest.mark.asyncio
    async def test_unknown_name_is_reported_before_any_request(self):
        node = _node()
        rec = _Recorder(node, named=[])
        with pytest.raises(ValueError, match="No named range"):
            await node._delete_named_range(
                GoogleSheetsDeleteNamedRangeConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", range_name="Missing"
                ),
                "token",
            )
        assert rec.requests == []


class TestProtectedRanges:
    @pytest.mark.asyncio
    async def test_protect_a_header_row_with_named_editors(self):
        node = _node()
        rec = _Recorder(
            node,
            reply={"replies": [{"addProtectedRange": {"protectedRange": {"protectedRangeId": 9}}}]},
        )
        out = await node._add_protected_range(
            GoogleSheetsAddProtectedRangeConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                range="A1:X1",
                description="Header row",
                editors="me@example.com, ops@example.com",
            ),
            "token",
        )
        protected = rec.only["addProtectedRange"]["protectedRange"]
        assert protected["description"] == "Header row"
        assert protected["warningOnly"] is False
        assert protected["editors"] == {"users": ["me@example.com", "ops@example.com"]}
        assert out["protected_range_id"] == 9

    @pytest.mark.asyncio
    async def test_empty_range_protects_the_whole_sheet(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_protected_range(
            GoogleSheetsAddProtectedRangeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", description="Everything"
            ),
            "token",
        )
        assert rec.only["addProtectedRange"]["protectedRange"]["range"] == {"sheetId": SHEET_ID}

    @pytest.mark.asyncio
    async def test_warning_only_with_editors_is_rejected(self):
        """The API rejects the combination; catching it here explains why."""
        node = _node()
        rec = _Recorder(node)
        with pytest.raises(ValueError, match="cannot be combined with Warning Only"):
            await node._add_protected_range(
                GoogleSheetsAddProtectedRangeConfig(
                    spreadsheet_id="ss",
                    sheet_name="Sheet1",
                    description="Header",
                    warning_only="true",
                    editors="me@example.com",
                ),
                "token",
            )
        assert rec.requests == []

    @pytest.mark.asyncio
    async def test_update_resolves_by_description(self):
        node = _node()
        rec = _Recorder(
            node, {"protectedRanges": [{"description": "Header row", "protectedRangeId": 9}]}
        )
        await node._update_protected_range(
            GoogleSheetsUpdateProtectedRangeConfig(
                spreadsheet_id="ss",
                sheet_name="Sheet1",
                description="Header row",
                warning_only="true",
            ),
            "token",
        )
        request = rec.only["updateProtectedRange"]
        assert request["protectedRange"]["protectedRangeId"] == 9
        assert request["protectedRange"]["warningOnly"] is True
        assert request["fields"] == "warningOnly"

    @pytest.mark.asyncio
    async def test_delete_resolves_by_description(self):
        node = _node()
        rec = _Recorder(
            node, {"protectedRanges": [{"description": "Header row", "protectedRangeId": 9}]}
        )
        await node._delete_protected_range(
            GoogleSheetsDeleteProtectedRangeConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", description="Header row"
            ),
            "token",
        )
        assert rec.only["deleteProtectedRange"] == {"protectedRangeId": 9}

    @pytest.mark.asyncio
    async def test_unknown_description_lists_what_is_there(self):
        node = _node()
        rec = _Recorder(
            node, {"protectedRanges": [{"description": "Header row", "protectedRangeId": 9}]}
        )
        with pytest.raises(ValueError, match="Protected ranges here: Header row"):
            await node._delete_protected_range(
                GoogleSheetsDeleteProtectedRangeConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", description="Nope"
                ),
                "token",
            )
        assert rec.requests == []


class TestConfigParsing:
    NEW_OPERATIONS = [
        ("update_conditional_format_rule", {"rule_index": 0, "new_index": 1}),
        ("update_alternating_colors", {"header_color": "#000000"}),
        ("update_table", {"table_name": "Prospects", "new_name": "Leads"}),
        ("add_named_range", {"range_name": "Stages", "range": "A2:A10"}),
        ("update_named_range", {"range_name": "Stages", "new_name": "Steps"}),
        ("delete_named_range", {"range_name": "Stages"}),
        ("add_protected_range", {"description": "Header"}),
        ("update_protected_range", {"description": "Header", "warning_only": "true"}),
        ("delete_protected_range", {"description": "Header"}),
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

    def test_spreadsheet_scoped_operation_needs_no_sheet(self):
        """update_spreadsheet_properties is the one op with no sheet picker."""
        import inspect

        parsed = GoogleSheetsNodeConfig(
            config={"operation": "update_spreadsheet_properties", "spreadsheet_id": "ss", "title": "X"}
        ).config
        assert parsed.operation == "update_spreadsheet_properties"
        assert not hasattr(parsed, "sheet_name")
        source = inspect.getsource(GoogleSheetsNode.execute)
        assert f"isinstance(config, {type(parsed).__name__})" in source
