"""Microsoft Excel → OAuth scope requirements (Graph's shared notes are in microsoft.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry


# ===========================================================================
# Excel  (automation-excel)
# ===========================================================================
# Requests: Files.ReadWrite.All, User.Read.
#
# Every workbook endpoint (worksheets, ranges, tables, charts, names, sessions,
# functions) documents exactly ONE delegated permission — Files.ReadWrite — with
# "Not available" in the higher-privileged column, and the Excel resource page
# repeats it ("Files.Read for read actions, Files.ReadWrite for read and write
# actions"). The node never requests Files.ReadWrite, so nothing here can be
# mapped without inventing an undocumented equivalence between Files.ReadWrite
# and Files.ReadWrite.All. See the module docstring: recorded, not fixed.

EXCEL_SCOPES = ScopeRegistry(
    provider="excel",
    requirements={},
    unmapped=(
        # MISSING SCOPE: Files.ReadWrite — for every operation below.
        "add_table_column",
        "add_table_row",
        "add_worksheet",
        "apply_table_column_filter",
        "clear_range_contents",
        "clear_table_column_filter",
        "close_workbook_session",
        "convert_table_to_range",
        "create_chart",
        "create_named_item",
        "create_table_from_range",
        "create_workbook_session",
        "delete_chart",
        "delete_range_and_shift_cells",
        "delete_table",
        "delete_table_column",
        "delete_table_row",
        "delete_worksheet",
        "execute_excel_function",
        "format_range",
        "get_chart",
        "get_chart_image",
        "get_named_item",
        "get_range_values",
        "get_table",
        "get_worksheet",
        "get_worksheet_used_range",
        "insert_blank_cells_in_range",
        "list_named_items",
        "list_table_columns",
        "list_table_rows",
        "list_workbook_tables",
        "list_workbook_worksheets",
        "list_worksheet_charts",
        "merge_range_cells",
        "recalculate_workbook",
        "refresh_workbook_session",
        "sort_range_by_column",
        "sort_table_by_column",
        "unmerge_range_cells",
        "update_chart",
        "update_range_values",
        "update_worksheet",
    ),
)
