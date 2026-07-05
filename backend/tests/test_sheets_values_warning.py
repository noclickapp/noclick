"""Google Sheets append/write single-cell warning (2026-07-05 incident).

A builder-generated pipe-joined `values` string silently appended entire "rows"
into single cells for a hundred runs. `_single_cell_warning` flags the
delimiter-in-single-cell shape on the node output without blocking the run.
"""

from nodes.google_sheets_node import GoogleSheetsNode


class TestSingleCellWarning:
    def test_pipe_joined_string_flagged(self):
        raw = "2026-07-05|Jane|jane@x.com|Dental"
        warning = GoogleSheetsNode._single_cell_warning(raw, [[raw]])
        assert warning is not None
        assert "SINGLE cell" in warning

    def test_tab_joined_string_flagged(self):
        raw = "a\tb\tc"
        assert GoogleSheetsNode._single_cell_warning(raw, [[raw]]) is not None

    def test_plain_scalar_not_flagged(self):
        assert GoogleSheetsNode._single_cell_warning("Jane Doe", [["Jane Doe"]]) is None

    def test_comma_text_not_flagged(self):
        # "Austin, TX" is a legitimate single value — commas are too noisy.
        assert GoogleSheetsNode._single_cell_warning("Austin, TX", [["Austin, TX"]]) is None

    def test_json_array_not_flagged(self):
        raw = '[["a", "b|c"]]'
        # Parsed to a real 1x2 row — pipe inside a cell value is fine.
        assert GoogleSheetsNode._single_cell_warning(raw, [["a", "b|c"]]) is None

    def test_non_string_input_not_flagged(self):
        assert GoogleSheetsNode._single_cell_warning([["a"]], [["a"]]) is None

    def test_parse_values_roundtrip_flags_incident_shape(self):
        """End-to-end through _parse_values: the incident config shape warns."""
        node = GoogleSheetsNode.__new__(GoogleSheetsNode)
        raw = "x|y|z"
        parsed = node._parse_values(raw, {})
        assert parsed == [["x|y|z"]]
        assert GoogleSheetsNode._single_cell_warning(raw, parsed) is not None
