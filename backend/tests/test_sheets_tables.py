"""Google Sheets tables.

A table is the only way to get CHIP dropdowns — plain data validation renders
the arrow style, and the display style is not settable on a standalone rule.
Column types live on the table, so dropdown values ride in columnProperties.

The sharp edge is the index frame: users name a column by its sheet letter,
but the API wants an index relative to the table's own range.
"""

import pytest

from nodes.google_sheets_node import (
    GoogleSheetsAddTableConfig,
    GoogleSheetsDeleteTableConfig,
    GoogleSheetsNode,
    GoogleSheetsNodeConfig,
)

SHEET_ID = 3


class _Recorder:
    def __init__(self, node, sheet_entry=None, reply=None):
        self.requests = []
        self.sheet_entry = sheet_entry or {}
        self.reply = reply or {"replies": [{"addTable": {"table": {"tableId": "t1"}}}]}
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


def _cfg(**kw):
    kw.setdefault("range", "A1:X13")
    kw.setdefault("table_name", "Prospects")
    return GoogleSheetsAddTableConfig(spreadsheet_id="ss", sheet_name="Sheet1", **kw)


class TestAddTable:
    @pytest.mark.asyncio
    async def test_plain_table_carries_no_column_properties(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._add_table(_cfg(), "token")
        table = rec.only["addTable"]["table"]
        assert table["name"] == "Prospects"
        assert table["range"]["sheetId"] == SHEET_ID
        assert "columnProperties" not in table
        assert out["table_id"] == "t1"
        assert out["typed_columns"] == 0

    @pytest.mark.asyncio
    async def test_dropdown_column_index_is_relative_to_the_table_range(self):
        """Column R is sheet index 17; in a table starting at A that is 17."""
        node = _node()
        rec = _Recorder(node)
        await node._add_table(
            _cfg(columns='[{"column": "R", "type": "DROPDOWN", "values": "Not started, Won"}]'),
            "token",
        )
        prop = rec.only["addTable"]["table"]["columnProperties"][0]
        assert prop["columnIndex"] == 17
        assert prop["columnType"] == "DROPDOWN"
        assert [
            v["userEnteredValue"] for v in prop["dataValidationRule"]["condition"]["values"]
        ] == ["Not started", "Won"]

    @pytest.mark.asyncio
    async def test_index_is_offset_when_the_table_does_not_start_at_column_a(self):
        """A table over R1:X13 makes R its own column 0, not column 17."""
        node = _node()
        rec = _Recorder(node)
        await node._add_table(
            _cfg(
                range="R1:X13",
                columns='[{"column": "R", "type": "DROPDOWN", "values": "A, B"},'
                ' {"column": "T", "type": "DATE"}]',
            ),
            "token",
        )
        props = rec.only["addTable"]["table"]["columnProperties"]
        assert [p["columnIndex"] for p in props] == [0, 2]

    @pytest.mark.asyncio
    async def test_column_name_is_optional_and_passed_through(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_table(
            _cfg(columns='[{"column": "R", "type": "DROPDOWN", "values": "A", "name": "Status"}]'),
            "token",
        )
        assert rec.only["addTable"]["table"]["columnProperties"][0]["columnName"] == "Status"

    @pytest.mark.asyncio
    async def test_non_dropdown_columns_carry_no_validation_rule(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_table(_cfg(columns='[{"column": "L", "type": "PERCENT"}]'), "token")
        prop = rec.only["addTable"]["table"]["columnProperties"][0]
        assert prop["columnType"] == "PERCENT"
        assert "dataValidationRule" not in prop

    @pytest.mark.asyncio
    async def test_dropdown_without_values_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match='needs "values"'):
            await node._add_table(_cfg(columns='[{"column": "R", "type": "DROPDOWN"}]'), "token")

    @pytest.mark.asyncio
    async def test_unknown_column_type_is_rejected_with_the_valid_set(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="Unsupported column type 'RATING'"):
            await node._add_table(_cfg(columns='[{"column": "R", "type": "rating"}]'), "token")

    @pytest.mark.asyncio
    async def test_column_outside_the_range_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="falls outside the table range"):
            await node._add_table(
                _cfg(range="A1:D13", columns='[{"column": "R", "type": "DATE"}]'), "token"
            )

    @pytest.mark.asyncio
    async def test_column_before_the_range_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="falls outside the table range"):
            await node._add_table(
                _cfg(range="R1:X13", columns='[{"column": "B", "type": "DATE"}]'), "token"
            )

    @pytest.mark.asyncio
    async def test_malformed_json_is_reported(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="not valid JSON"):
            await node._add_table(_cfg(columns='[{"column": "R"'), "token")

    @pytest.mark.asyncio
    async def test_non_list_json_is_reported(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="must be a JSON list"):
            await node._add_table(_cfg(columns='{"column": "R"}'), "token")

    @pytest.mark.asyncio
    async def test_type_is_case_insensitive(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_table(
            _cfg(columns='[{"column": "R", "type": "dropdown", "values": "A"}]'), "token"
        )
        assert rec.only["addTable"]["table"]["columnProperties"][0]["columnType"] == "DROPDOWN"


class TestDeleteTable:
    @pytest.mark.asyncio
    async def test_resolves_the_table_by_name(self):
        node = _node()
        rec = _Recorder(
            node,
            {"tables": [{"name": "Other", "tableId": "t9"}, {"name": "Prospects", "tableId": "t4"}]},
        )
        out = await node._delete_table(
            GoogleSheetsDeleteTableConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", table_name="Prospects"
            ),
            "token",
        )
        assert rec.only["deleteTable"] == {"tableId": "t4"}
        assert out["table_id"] == "t4"

    @pytest.mark.asyncio
    async def test_unknown_table_lists_what_is_there(self):
        node = _node()
        rec = _Recorder(node, {"tables": [{"name": "Other", "tableId": "t9"}]})
        with pytest.raises(ValueError, match="Tables here: Other"):
            await node._delete_table(
                GoogleSheetsDeleteTableConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", table_name="Missing"
                ),
                "token",
            )
        assert rec.requests == []

    @pytest.mark.asyncio
    async def test_sheet_with_no_tables_says_none(self):
        node = _node()
        _Recorder(node, {})
        with pytest.raises(ValueError, match="Tables here: none"):
            await node._delete_table(
                GoogleSheetsDeleteTableConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", table_name="Missing"
                ),
                "token",
            )


class TestConfigParsing:
    NEW_OPERATIONS = [
        ("add_table", {"range": "A1:X13", "table_name": "Prospects"}),
        ("delete_table", {"table_name": "Prospects"}),
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

    def test_operations_are_in_the_schema(self):
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
