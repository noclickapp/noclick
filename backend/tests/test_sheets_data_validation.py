"""Google Sheets data validation and rule teardown.

Dropdowns are the point of `set_data_validation`; the teardown operations exist
because every rule-adding operation was one-way. `add_alternating_colors` fails
outright on a range that is already banded, so a formatting script could not be
re-run, and conditional rules could only be added — never removed or reordered.
"""

import pytest

from nodes.google_sheets_node import (
    GoogleSheetsClearBandingConfig,
    GoogleSheetsClearDataValidationConfig,
    GoogleSheetsDeleteConditionalFormatConfig,
    GoogleSheetsNode,
    GoogleSheetsNodeConfig,
    GoogleSheetsSetDataValidationConfig,
)

SHEET_ID = 7


class _Recorder:
    """Stands in for the batchUpdate sender, sheet-id lookup and sheet fetch."""

    def __init__(self, node, sheet_entry=None):
        self.requests = []
        self.sheet_entry = sheet_entry or {}
        node._send_batch_update = self._send
        node._get_sheet_id = self._sheet_id
        node._fetch_sheet_entry = self._fetch

    async def _send(self, spreadsheet_id, requests, access_token):
        self.requests.append(requests)
        return {"replies": [{}]}

    async def _sheet_id(self, spreadsheet_id, sheet_name, access_token):
        return SHEET_ID

    async def _fetch(self, spreadsheet_id, sheet_name, fields, access_token):
        return {"properties": {"sheetId": SHEET_ID, "title": sheet_name}, **self.sheet_entry}

    @property
    def only(self):
        assert len(self.requests) == 1
        assert len(self.requests[0]) == 1
        return self.requests[0][0]

    @property
    def batch(self):
        assert len(self.requests) == 1
        return self.requests[0]


def _node():
    return GoogleSheetsNode.__new__(GoogleSheetsNode)


def _validation(**kw):
    return GoogleSheetsSetDataValidationConfig(
        spreadsheet_id="ss", sheet_name="Sheet1", range="R2:R100", **kw
    )


class TestOptionParsing:
    def test_comma_separated(self):
        assert GoogleSheetsNode._parse_option_values("Not started, Contacted, Won") == [
            "Not started",
            "Contacted",
            "Won",
        ]

    def test_json_array_allows_commas_inside_a_value(self):
        raw = '["Won", "Passed, no budget", "Contacted"]'
        assert GoogleSheetsNode._parse_option_values(raw) == [
            "Won",
            "Passed, no budget",
            "Contacted",
        ]

    def test_blank_entries_are_dropped(self):
        assert GoogleSheetsNode._parse_option_values("A, , B,") == ["A", "B"]

    def test_empty_input(self):
        assert GoogleSheetsNode._parse_option_values(None) == []
        assert GoogleSheetsNode._parse_option_values("   ") == []

    def test_malformed_json_is_reported_not_silently_split(self):
        with pytest.raises(ValueError, match="could not be parsed"):
            GoogleSheetsNode._parse_option_values('["Won", "Lost"')


class TestSetDataValidation:
    @pytest.mark.asyncio
    async def test_status_dropdown(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._set_data_validation(
            _validation(values="Not started, Contacted, Won"), "token"
        )
        rule = rec.only["setDataValidation"]["rule"]
        assert rule["condition"]["type"] == "ONE_OF_LIST"
        assert [v["userEnteredValue"] for v in rule["condition"]["values"]] == [
            "Not started",
            "Contacted",
            "Won",
        ]
        assert rule["showCustomUi"] is True
        assert rule["strict"] is True
        assert rec.only["setDataValidation"]["range"]["sheetId"] == SHEET_ID
        assert out["options"] == ["Not started", "Contacted", "Won"]

    @pytest.mark.asyncio
    async def test_non_strict_allows_free_text_with_a_warning(self):
        node = _node()
        rec = _Recorder(node)
        await node._set_data_validation(_validation(values="A, B", strict="false"), "token")
        assert rec.only["setDataValidation"]["rule"]["strict"] is False

    @pytest.mark.asyncio
    async def test_dropdown_chip_can_be_suppressed(self):
        node = _node()
        rec = _Recorder(node)
        await node._set_data_validation(
            _validation(values="A, B", show_dropdown="false"), "token"
        )
        assert rec.only["setDataValidation"]["rule"]["showCustomUi"] is False

    @pytest.mark.asyncio
    async def test_help_text_becomes_the_input_message(self):
        node = _node()
        rec = _Recorder(node)
        await node._set_data_validation(
            _validation(values="A, B", help_text="Pick the current stage"), "token"
        )
        assert rec.only["setDataValidation"]["rule"]["inputMessage"] == "Pick the current stage"

    @pytest.mark.asyncio
    async def test_range_backed_list_gets_a_leading_equals(self):
        node = _node()
        rec = _Recorder(node)
        await node._set_data_validation(
            _validation(rule_type="list_from_range", values="Config!A2:A10"), "token"
        )
        condition = rec.only["setDataValidation"]["rule"]["condition"]
        assert condition["type"] == "ONE_OF_RANGE"
        assert condition["values"][0]["userEnteredValue"] == "=Config!A2:A10"

    @pytest.mark.asyncio
    async def test_range_backed_list_does_not_double_the_equals(self):
        node = _node()
        rec = _Recorder(node)
        await node._set_data_validation(
            _validation(rule_type="list_from_range", values="=Config!A2:A10"), "token"
        )
        assert (
            rec.only["setDataValidation"]["rule"]["condition"]["values"][0]["userEnteredValue"]
            == "=Config!A2:A10"
        )

    @pytest.mark.asyncio
    async def test_checkbox_has_no_dropdown_chip(self):
        node = _node()
        rec = _Recorder(node)
        await node._set_data_validation(_validation(rule_type="checkbox"), "token")
        rule = rec.only["setDataValidation"]["rule"]
        assert rule["condition"] == {"type": "BOOLEAN"}
        assert "showCustomUi" not in rule

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "rule_type,expected",
        [("date", "DATE_IS_VALID"), ("email", "TEXT_IS_VALID_EMAIL"), ("url", "TEXT_IS_VALID_URL")],
    )
    async def test_simple_input_rules(self, rule_type, expected):
        node = _node()
        rec = _Recorder(node)
        await node._set_data_validation(_validation(rule_type=rule_type), "token")
        assert rec.only["setDataValidation"]["rule"]["condition"]["type"] == expected

    @pytest.mark.asyncio
    async def test_number_between(self):
        node = _node()
        rec = _Recorder(node)
        await node._set_data_validation(
            _validation(rule_type="number_between", min_value="0", max_value="10"), "token"
        )
        condition = rec.only["setDataValidation"]["rule"]["condition"]
        assert condition["type"] == "NUMBER_BETWEEN"
        assert [v["userEnteredValue"] for v in condition["values"]] == ["0", "10"]

    @pytest.mark.asyncio
    async def test_list_without_values_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="needs Values"):
            await node._set_data_validation(_validation(), "token")

    @pytest.mark.asyncio
    async def test_number_between_without_bounds_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="both Minimum and Maximum"):
            await node._set_data_validation(
                _validation(rule_type="number_between", min_value="1"), "token"
            )

    @pytest.mark.asyncio
    async def test_custom_formula_without_values_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="needs Values set to the formula"):
            await node._set_data_validation(_validation(rule_type="custom_formula"), "token")


class TestClearDataValidation:
    @pytest.mark.asyncio
    async def test_clear_sends_a_rule_less_request(self):
        """setDataValidation with no `rule` is how the API clears validation."""
        node = _node()
        rec = _Recorder(node)
        await node._clear_data_validation(
            GoogleSheetsClearDataValidationConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", range="R2:R100"
            ),
            "token",
        )
        request = rec.only["setDataValidation"]
        assert "rule" not in request
        assert request["range"]["sheetId"] == SHEET_ID


class TestDeleteConditionalFormatRules:
    @pytest.mark.asyncio
    async def test_deleting_all_rules_emits_one_request_per_rule_at_index_zero(self):
        """Each delete reindexes the rest, so repeatedly deleting 0 drains the list."""
        node = _node()
        rec = _Recorder(node, {"conditionalFormats": [{}, {}, {}]})
        out = await node._delete_conditional_format_rules(
            GoogleSheetsDeleteConditionalFormatConfig(spreadsheet_id="ss", sheet_name="Sheet1"),
            "token",
        )
        assert len(rec.batch) == 3
        assert all(
            r["deleteConditionalFormatRule"] == {"sheetId": SHEET_ID, "index": 0}
            for r in rec.batch
        )
        assert out["rules_deleted"] == 3

    @pytest.mark.asyncio
    async def test_deleting_one_rule_targets_that_index(self):
        node = _node()
        rec = _Recorder(node, {"conditionalFormats": [{}, {}, {}]})
        await node._delete_conditional_format_rules(
            GoogleSheetsDeleteConditionalFormatConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", rule_index=1
            ),
            "token",
        )
        assert len(rec.batch) == 1
        assert rec.batch[0]["deleteConditionalFormatRule"]["index"] == 1

    @pytest.mark.asyncio
    async def test_out_of_range_index_is_reported_not_sent(self):
        node = _node()
        rec = _Recorder(node, {"conditionalFormats": [{}]})
        with pytest.raises(ValueError, match="no rule at index 5"):
            await node._delete_conditional_format_rules(
                GoogleSheetsDeleteConditionalFormatConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", rule_index=5
                ),
                "token",
            )
        assert rec.requests == []

    @pytest.mark.asyncio
    async def test_no_rules_is_a_clean_no_op(self):
        node = _node()
        rec = _Recorder(node, {})
        out = await node._delete_conditional_format_rules(
            GoogleSheetsDeleteConditionalFormatConfig(spreadsheet_id="ss", sheet_name="Sheet1"),
            "token",
        )
        assert out["rules_deleted"] == 0
        assert rec.requests == []


class TestClearBanding:
    @pytest.mark.asyncio
    async def test_every_banded_range_is_deleted(self):
        node = _node()
        rec = _Recorder(
            node, {"bandedRanges": [{"bandedRangeId": 11}, {"bandedRangeId": 12}]}
        )
        out = await node._clear_banding(
            GoogleSheetsClearBandingConfig(spreadsheet_id="ss", sheet_name="Sheet1"), "token"
        )
        assert [r["deleteBanding"]["bandedRangeId"] for r in rec.batch] == [11, 12]
        assert out["bands_removed"] == 2

    @pytest.mark.asyncio
    async def test_unbanded_sheet_is_a_clean_no_op(self):
        """Makes clear-then-band safe to run on a sheet that was never banded."""
        node = _node()
        rec = _Recorder(node, {})
        out = await node._clear_banding(
            GoogleSheetsClearBandingConfig(spreadsheet_id="ss", sheet_name="Sheet1"), "token"
        )
        assert out["bands_removed"] == 0
        assert rec.requests == []


class TestConfigParsing:
    NEW_OPERATIONS = [
        ("set_data_validation", {"range": "R2:R100", "values": "A, B"}),
        ("clear_data_validation", {"range": "R2:R100"}),
        ("delete_conditional_format_rules", {}),
        ("clear_alternating_colors", {}),
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
