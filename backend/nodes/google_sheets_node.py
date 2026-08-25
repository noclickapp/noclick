"""
Google Sheets workflow node implementation.
Enables reading from and writing to Google Sheets via OAuth credentials.

Supports 35 operations across three families:

- values: read, write, append, clear, batch_get, batch_update, batch_clear
- structure: create, get_metadata, add_sheet, delete_sheet, copy_sheet,
  rename_sheet, duplicate_sheet, find_replace, insert/delete rows and columns
- presentation: format_cells, update_sheet_properties, auto_resize_dimensions,
  set_dimension_size, merge/unmerge cells, format_borders,
  add_alternating_colors, set/clear_basic_filter, add_conditional_format_rule,
  sort_range, set/clear_data_validation, delete_conditional_format_rules,
  clear_alternating_colors

plus the on_new_row trigger.
"""

import time
import asyncio
import os
import json
import logging
import re
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.oauth.google_token import ensure_fresh_google_token
from nodes.core.dynamic_options import require_credential_token
from nodes.scopes.google import GOOGLE_SHEETS_SCOPES
from utils.encryption import get_encryption

logger = logging.getLogger(__name__)

GOOGLE_SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


async def sheets_read_values(
    access_token: str, spreadsheet_id: str, sheet_name: Optional[str] = None
) -> List[List[Any]]:
    """Read every cell value from a sheet (defaults to the first sheet)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        if not sheet_name:
            meta = await client.get(
                f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}",
                headers=headers,
                params={"fields": "sheets.properties.title"},
            )
            meta.raise_for_status()
            sheets = meta.json().get("sheets", [])
            if not sheets:
                return []
            sheet_name = sheets[0]["properties"]["title"]
        response = await client.get(
            f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}/values/{sheet_name}",
            headers=headers,
        )
        response.raise_for_status()
        return response.json().get("values", [])


# ============================================================================
# Formatting helpers
#
# The values API speaks A1 ("Sheet1!A1:D10") but every formatting request in
# spreadsheets.batchUpdate speaks GridRange (sheetId + half-open 0-based
# indices). These two helpers are the whole translation layer.
# ============================================================================

_A1_CELL_RE = re.compile(r"^([A-Za-z]+)?(\d+)?$")


def column_letters_to_index(letters: str) -> int:
    """'A' -> 0, 'Z' -> 25, 'AA' -> 26. Zero-based, as GridRange wants."""
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def column_index_to_letters(index: int) -> str:
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA'. The inverse of column_letters_to_index."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def a1_range_to_grid_range(a1_range: str, sheet_id: int) -> Dict[str, Any]:
    """
    Convert an A1 range into a GridRange.

    Accepts 'A1:D10', bare columns 'A:D', bare rows '2:10', a single cell 'B7',
    a sheet-qualified range 'Sheet1!A1:D10', or an empty string for the whole
    sheet. Omitted bounds stay absent, which the API reads as unbounded.
    """
    grid: Dict[str, Any] = {"sheetId": sheet_id}
    spec = (a1_range or "").strip()
    if "!" in spec:
        spec = spec.rsplit("!", 1)[1].strip()
    spec = spec.replace("$", "")
    if not spec:
        return grid

    start_spec, _, end_spec = spec.partition(":")
    if not end_spec:
        end_spec = start_spec

    start_match = _A1_CELL_RE.match(start_spec)
    end_match = _A1_CELL_RE.match(end_spec)
    if not start_match or not end_match:
        raise ValueError(
            f"Invalid A1 range '{a1_range}'. Use forms like 'A1:D10', 'A:D', '2:10' or 'B7'."
        )

    start_col, start_row = start_match.groups()
    end_col, end_row = end_match.groups()

    if start_col:
        grid["startColumnIndex"] = column_letters_to_index(start_col)
    if end_col:
        grid["endColumnIndex"] = column_letters_to_index(end_col) + 1
    if start_row:
        grid["startRowIndex"] = int(start_row) - 1
    if end_row:
        grid["endRowIndex"] = int(end_row)

    for low, high in (("startRowIndex", "endRowIndex"), ("startColumnIndex", "endColumnIndex")):
        if low in grid and high in grid and grid[low] >= grid[high]:
            raise ValueError(
                f"Invalid A1 range '{a1_range}': the end of the range comes before the start."
            )
    return grid


def hex_to_color(value: Optional[str]) -> Optional[Dict[str, float]]:
    """'#1B6E5A' or '1b6e5a' -> the 0..1 RGB dict the Sheets API expects."""
    if value is None:
        return None
    raw = value.strip().lstrip("#")
    if not raw:
        return None
    if len(raw) == 3:
        raw = "".join(char * 2 for char in raw)
    if len(raw) != 6 or any(char not in "0123456789abcdefABCDEF" for char in raw):
        raise ValueError(
            f"Invalid colour '{value}'. Use a hex colour such as '#1B6E5A'."
        )
    return {
        "red": int(raw[0:2], 16) / 255.0,
        "green": int(raw[2:4], 16) / 255.0,
        "blue": int(raw[4:6], 16) / 255.0,
    }


def _is_true(value: Optional[str]) -> bool:
    """Config booleans travel as the strings 'true'/'false' (see CLAUDE.md)."""
    return str(value).strip().lower() == "true"


# ============================================================================
# Google Sheets Node Credential Schema
# ============================================================================


class GoogleSheetsOAuthCredential(BaseModel):
    """
    OAuth credential for Google Sheets access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_sheets_oauth"] = Field(
        "google_sheets_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "google",
            "x-oauth-scopes": [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.metadata.readonly",  # For listing spreadsheets
            ],
        }
    )


# ============================================================================
# Google Sheets Node Configuration Models
# ============================================================================


class GoogleSheetsReadConfig(BaseModel):
    """Configuration for reading data from a Google Sheet"""

    operation: Literal["read_sheet_data"] = Field(
        "read_sheet_data",
        title="Read Sheet Data",
        description="Read data from spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "read_sheet_data",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Read Sheet Data",
            "x-keywords": [
                "get rows",
                "fetch rows",
                "list rows",
                "read rows",
                "get values",
                "get data",
                "get cells",
                "retrieve rows",
                "pull data",
                "load rows",
                "get records",
                "view rows",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet to read from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: Optional[str] = Field(
        None,
        title="Sheet",
        description="Select a sheet/tab within the spreadsheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
                "auto_select_first": True,
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    range: Optional[str] = Field(
        None,
        title="Range",
        description="Cell range to read (e.g., A1:D10). Leave empty to read all data.",
        json_schema_extra={"placeholder": "A1:D10 (optional)"},
    )


class GoogleSheetsWriteConfig(BaseModel):
    """Configuration for writing data to a Google Sheet"""

    operation: Literal["write_sheet_data"] = Field(
        "write_sheet_data",
        title="Write Sheet Data",
        description="Write data to spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "write_sheet_data",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Write Sheet Data",
            "x-keywords": [
                "update cells",
                "set values",
                "set data",
                "put values",
                "overwrite range",
                "update range",
                "edit cells",
                "modify cells",
                "set cells",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet to write to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: Optional[str] = Field(
        None,
        title="Sheet",
        description="Select a sheet/tab within the spreadsheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
                "auto_select_first": True,
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Cell range to write to (e.g., A1:D10)",
        json_schema_extra={"placeholder": "A1"},
    )
    values: Union[str, List[Any]] = Field(
        ...,
        title="Values",
        description='JSON array of rows to write (e.g., [["A1", "B1"], ["A2", "B2"]])',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[["Name", "Email"], ["John", "john@example.com"]]',
        },
    )


class GoogleSheetsAppendConfig(BaseModel):
    """Configuration for appending rows to a Google Sheet"""

    operation: Literal["append_rows_to_sheet"] = Field(
        "append_rows_to_sheet",
        title="Append Rows to Sheet",
        description="Append rows to spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "append_rows_to_sheet",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Append Rows to Sheet",
            "x-keywords": [
                "add row",
                "add rows",
                "insert row",
                "new row",
                "add record",
                "add data",
                "append data",
                "create row",
                "push row",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet to append to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: Optional[str] = Field(
        None,
        title="Sheet",
        description="Select a sheet/tab within the spreadsheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
                "auto_select_first": True,
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Column range to append after (e.g., A:D)",
        json_schema_extra={"placeholder": "A:D"},
    )
    values: Union[str, List[Any]] = Field(
        ...,
        title="Values",
        description="JSON array of rows to append",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[["John", "john@example.com"]]',
        },
    )


class GoogleSheetsClearConfig(BaseModel):
    """Configuration for clearing values from a range"""

    operation: Literal["clear_sheet_range"] = Field(
        "clear_sheet_range",
        title="Clear Sheet Range",
        description="Clear values from a range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "clear_sheet_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Clear Sheet Range",
            "x-keywords": [
                "empty range",
                "delete values",
                "remove data",
                "wipe cells",
                "reset range",
                "erase cells",
                "clear cells",
                "blank cells",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: Optional[str] = Field(
        None,
        title="Sheet",
        description="Select a sheet/tab",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
                "auto_select_first": True,
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Cell range to clear (e.g., A1:D10)",
        json_schema_extra={"placeholder": "A1:D10"},
    )


class GoogleSheetsCreateConfig(BaseModel):
    """Configuration for creating a new spreadsheet"""

    operation: Literal["create_new_spreadsheet"] = Field(
        "create_new_spreadsheet",
        title="Create New Spreadsheet",
        description="Create a new spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_new_spreadsheet",
            "x-category": "Spreadsheet",
            "x-is-trigger": False,
            "x-display-name": "Create New Spreadsheet",
            "x-keywords": [
                "new spreadsheet",
                "make spreadsheet",
                "create file",
                "new workbook",
                "create spreadsheet",
                "start spreadsheet",
            ],
            "x-creates-resource": True,
            "x-resource-type": "google_spreadsheet",
            "x-resource-id-path": "spreadsheet_id",
        },
    )
    title: str = Field(
        ..., title="Spreadsheet Title", description="Name for the new spreadsheet"
    )
    sheet_titles: Optional[str] = Field(
        None,
        title="Sheet Names",
        description="Comma-separated list of sheet names (default: 'Sheet1')",
        json_schema_extra={"placeholder": "Sheet1, Sheet2, Data"},
    )


class GoogleSheetsGetMetadataConfig(BaseModel):
    """Configuration for getting spreadsheet metadata"""

    operation: Literal["fetch_spreadsheet_metadata"] = Field(
        "fetch_spreadsheet_metadata",
        title="Fetch Spreadsheet Metadata",
        description="Get spreadsheet info, properties, and optionally its tables, charts and rules",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_spreadsheet_metadata",
            "x-category": "Spreadsheet",
            "x-is-trigger": False,
            "x-display-name": "Fetch Spreadsheet Metadata",
            "x-keywords": [
                "get info",
                "list sheets",
                "list tabs",
                "sheet names",
                "tab names",
                "get properties",
                "spreadsheet info",
                "get metadata",
                "list worksheets",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )


    include_structure: Optional[Literal["true", "false"]] = Field(
        "false",
        title="Include Structure",
        description=(
            "Also return each sheet's tables, charts, slicers, filter views, protected and "
            "banded ranges and conditional formatting rules, plus the spreadsheet's named ranges. "
            "Off by default because it is a much larger response."
        ),
    )


class GoogleSheetsBatchGetConfig(BaseModel):
    """Configuration for reading multiple ranges at once"""

    operation: Literal["read_multiple_sheet_ranges"] = Field(
        "read_multiple_sheet_ranges",
        title="Read Multiple Sheet Ranges",
        description="Read multiple ranges at once",
        json_schema_extra={
            "ui:hidden": True,
            "const": "read_multiple_sheet_ranges",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Read Multiple Sheet Ranges",
            "x-keywords": [
                "batch read",
                "read ranges",
                "get multiple ranges",
                "read several ranges",
                "batch get",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    ranges: str = Field(
        ...,
        title="Ranges",
        description="Comma-separated list of ranges (e.g., Sheet1!A1:B10, Sheet2!C1:D5)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Sheet1!A1:B10, Sheet2!C1:D5",
        },
    )


class GoogleSheetsBatchUpdateConfig(BaseModel):
    """Configuration for writing to multiple ranges at once"""

    operation: Literal["write_to_multiple_sheet_ranges"] = Field(
        "write_to_multiple_sheet_ranges",
        title="Write to Multiple Sheet Ranges",
        description="Write to multiple ranges at once",
        json_schema_extra={
            "ui:hidden": True,
            "const": "write_to_multiple_sheet_ranges",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Write to Multiple Sheet Ranges",
            "x-keywords": [
                "batch write",
                "update multiple ranges",
                "write several ranges",
                "batch update",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    data: str = Field(
        ...,
        title="Data",
        description="JSON array of {range, values} objects",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"range": "Sheet1!A1", "values": [["Value1"]]}, {"range": "Sheet1!B1", "values": [["Value2"]]}]',
        },
    )


class GoogleSheetsAddSheetConfig(BaseModel):
    """Configuration for adding a new sheet/tab"""

    operation: Literal["add_spreadsheet_sheet"] = Field(
        "add_spreadsheet_sheet",
        title="Add Spreadsheet Sheet",
        description="Add a new sheet/tab to spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_spreadsheet_sheet",
            "x-category": "Sheet",
            "x-is-trigger": False,
            "x-display-name": "Add Spreadsheet Sheet",
            "x-keywords": [
                "new tab",
                "add tab",
                "create tab",
                "new worksheet",
                "add worksheet",
                "create sheet tab",
                "new sheet tab",
            ],
            "x-creates-resource": True,
            "x-resource-type": "google_sheet_tab",
            "x-resource-id-path": "sheet_title",
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_title: str = Field(
        ..., title="Sheet Name", description="Name for the new sheet"
    )
    index: Optional[int] = Field(
        None,
        title="Position",
        description="Position for the new sheet (0 = first, leave empty for last)",
    )


class GoogleSheetsDeleteSheetConfig(BaseModel):
    """Configuration for deleting a sheet/tab"""

    operation: Literal["delete_spreadsheet_sheet"] = Field(
        "delete_spreadsheet_sheet",
        title="Delete Spreadsheet Sheet",
        description="Delete a sheet/tab from spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_spreadsheet_sheet",
            "x-category": "Sheet",
            "x-is-trigger": False,
            "x-display-name": "Delete Spreadsheet Sheet",
            "x-keywords": [
                "remove sheet",
                "delete tab",
                "remove tab",
                "remove worksheet",
                "drop sheet",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: str = Field(
        ...,
        title="Sheet",
        description="Select the sheet to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )


class GoogleSheetsCopySheetConfig(BaseModel):
    """Configuration for copying a sheet to another spreadsheet"""

    operation: Literal["copy_sheet_to_spreadsheet"] = Field(
        "copy_sheet_to_spreadsheet",
        title="Copy Sheet to Spreadsheet",
        description="Copy a sheet to another spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "copy_sheet_to_spreadsheet",
            "x-category": "Sheet",
            "x-is-trigger": False,
            "x-display-name": "Copy Sheet to Spreadsheet",
            "x-keywords": [
                "copy tab",
                "copy worksheet",
                "move sheet to spreadsheet",
                "duplicate tab to spreadsheet",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Source Spreadsheet",
        description="Select the source spreadsheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select source spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: str = Field(
        ...,
        title="Sheet to Copy",
        description="Select the sheet to copy",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    destination_spreadsheet_id: str = Field(
        ...,
        title="Destination Spreadsheet",
        description="Select the destination spreadsheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select destination spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )


class GoogleSheetsRenameSheetConfig(BaseModel):
    """Configuration for renaming a sheet/tab"""

    operation: Literal["rename_spreadsheet_sheet"] = Field(
        "rename_spreadsheet_sheet",
        title="Rename Spreadsheet Sheet",
        description="Rename a sheet/tab",
        json_schema_extra={
            "ui:hidden": True,
            "const": "rename_spreadsheet_sheet",
            "x-category": "Sheet",
            "x-is-trigger": False,
            "x-display-name": "Rename Spreadsheet Sheet",
            "x-keywords": [
                "rename tab",
                "rename worksheet",
                "change sheet name",
                "change tab name",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: str = Field(
        ...,
        title="Sheet",
        description="Select the sheet to rename",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    new_name: str = Field(..., title="New Name", description="New name for the sheet")


class GoogleSheetsDuplicateSheetConfig(BaseModel):
    """Configuration for duplicating a sheet within the same spreadsheet"""

    operation: Literal["duplicate_sheet_in_spreadsheet"] = Field(
        "duplicate_sheet_in_spreadsheet",
        title="Duplicate Sheet in Spreadsheet",
        description="Duplicate a sheet within the spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "duplicate_sheet_in_spreadsheet",
            "x-category": "Sheet",
            "x-is-trigger": False,
            "x-display-name": "Duplicate Sheet in Spreadsheet",
            "x-keywords": [
                "copy sheet",
                "clone sheet",
                "duplicate tab",
                "clone tab",
                "copy worksheet within",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: str = Field(
        ...,
        title="Sheet",
        description="Select the sheet to duplicate",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    new_name: Optional[str] = Field(
        None, title="New Name", description="Name for the duplicated sheet (optional)"
    )


class GoogleSheetsFindReplaceConfig(BaseModel):
    """Configuration for find and replace in a spreadsheet"""

    operation: Literal["find_and_replace_in_spreadsheet"] = Field(
        "find_and_replace_in_spreadsheet",
        title="Find and Replace in Spreadsheet",
        description="Find and replace text in spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "find_and_replace_in_spreadsheet",
            "x-category": "Spreadsheet",
            "x-is-trigger": False,
            "x-display-name": "Find and Replace in Spreadsheet",
            "x-keywords": [
                "search and replace",
                "replace text",
                "substitute text",
                "swap text",
                "search replace",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    find: str = Field(..., title="Find", description="Text to find")
    replacement: str = Field(..., title="Replace With", description="Replacement text")
    sheet_name: Optional[str] = Field(
        None,
        title="Sheet",
        description="Limit to specific sheet (leave empty for all sheets)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "All sheets (or select one)...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    match_case: bool = Field(
        False, title="Match Case", description="Case-sensitive search"
    )
    match_entire_cell: bool = Field(
        False,
        title="Match Entire Cell",
        description="Only match if entire cell matches",
    )


class GoogleSheetsInsertRowsConfig(BaseModel):
    """Configuration for inserting rows"""

    operation: Literal["insert_sheet_rows"] = Field(
        "insert_sheet_rows",
        title="Insert Sheet Rows",
        description="Insert rows at a position",
        json_schema_extra={
            "ui:hidden": True,
            "const": "insert_sheet_rows",
            "x-category": "Row",
            "x-is-trigger": False,
            "x-display-name": "Insert Sheet Rows",
            "x-keywords": [
                "insert blank rows",
                "add empty rows",
                "insert rows at position",
                "make space rows",
                "add blank rows",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: str = Field(
        ...,
        title="Sheet",
        description="Select the sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    start_row: int = Field(
        ..., title="Start Row", description="Row number to insert at (1-indexed)", ge=1
    )
    num_rows: int = Field(
        1, title="Number of Rows", description="Number of rows to insert", ge=1
    )


class GoogleSheetsDeleteRowsConfig(BaseModel):
    """Configuration for deleting rows"""

    operation: Literal["delete_sheet_rows"] = Field(
        "delete_sheet_rows",
        title="Delete Sheet Rows",
        description="Delete rows from a sheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_sheet_rows",
            "x-category": "Row",
            "x-is-trigger": False,
            "x-display-name": "Delete Sheet Rows",
            "x-keywords": ["remove rows", "drop rows", "delete records", "erase rows"],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: str = Field(
        ...,
        title="Sheet",
        description="Select the sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    start_row: int = Field(
        ..., title="Start Row", description="First row to delete (1-indexed)", ge=1
    )
    end_row: int = Field(
        ...,
        title="End Row",
        description="Last row to delete (inclusive, 1-indexed)",
        ge=1,
    )


class GoogleSheetsBatchClearConfig(BaseModel):
    """Configuration for clearing multiple ranges at once"""

    operation: Literal["clear_multiple_sheet_ranges"] = Field(
        "clear_multiple_sheet_ranges",
        title="Clear Multiple Sheet Ranges",
        description="Clear multiple ranges at once",
        json_schema_extra={
            "ui:hidden": True,
            "const": "clear_multiple_sheet_ranges",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Clear Multiple Sheet Ranges",
            "x-keywords": [
                "batch clear",
                "empty multiple ranges",
                "clear several ranges",
                "wipe multiple ranges",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    ranges: List[str] = Field(
        ...,
        title="Ranges",
        description="List of A1 notation ranges to clear (e.g., ['Sheet1!A1:B10', 'Sheet1!D1:E10'])",
        json_schema_extra={"placeholder": "['Sheet1!A1:B10', 'Sheet1!D1:E10']"},
    )


class GoogleSheetsInsertColumnsConfig(BaseModel):
    """Configuration for inserting columns"""

    operation: Literal["insert_sheet_columns"] = Field(
        "insert_sheet_columns",
        title="Insert Sheet Columns",
        description="Insert columns at a position",
        json_schema_extra={
            "ui:hidden": True,
            "const": "insert_sheet_columns",
            "x-category": "Column",
            "x-is-trigger": False,
            "x-display-name": "Insert Sheet Columns",
            "x-keywords": [
                "insert blank columns",
                "add columns",
                "insert columns at position",
                "add empty columns",
                "add cols",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: str = Field(
        ...,
        title="Sheet",
        description="Select the sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    start_column: int = Field(
        ...,
        title="Start Column",
        description="Column number to insert at (1 = A, 2 = B, etc.)",
        ge=1,
    )
    num_columns: int = Field(
        1, title="Number of Columns", description="Number of columns to insert", ge=1
    )
    inherit_from_before: bool = Field(
        False,
        title="Inherit From Before",
        description="Inherit formatting from column before the insert position",
    )


class GoogleSheetsDeleteColumnsConfig(BaseModel):
    """Configuration for deleting columns"""

    operation: Literal["delete_sheet_columns"] = Field(
        "delete_sheet_columns",
        title="Delete Sheet Columns",
        description="Delete columns from a sheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_sheet_columns",
            "x-category": "Column",
            "x-is-trigger": False,
            "x-display-name": "Delete Sheet Columns",
            "x-keywords": [
                "remove columns",
                "drop columns",
                "delete cols",
                "erase columns",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: str = Field(
        ...,
        title="Sheet",
        description="Select the sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    start_column: int = Field(
        ...,
        title="Start Column",
        description="First column to delete (1 = A, 2 = B, etc.)",
        ge=1,
    )
    end_column: int = Field(
        ...,
        title="End Column",
        description="Last column to delete (inclusive, 1 = A, 2 = B, etc.)",
        ge=1,
    )


# ============================================================================
# Formatting / presentation operations
#
# Every operation below targets one sheet, so the spreadsheet + sheet pickers
# live on a shared base rather than being restated twelve times. Optional
# fields mean "leave this alone": each handler builds the API `fields` mask
# from what was actually supplied, so setting a background never clears a font.
# ============================================================================

_BOOL_ENUM = {"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True}


class GoogleSheetsSheetTargetBase(BaseModel):
    """Spreadsheet + sheet pickers shared by the formatting operations."""

    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: str = Field(
        ...,
        title="Sheet",
        description="Select the sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )


class GoogleSheetsFormatCellsConfig(GoogleSheetsSheetTargetBase):
    """Configuration for formatting a range of cells"""

    operation: Literal["format_cells"] = Field(
        "format_cells",
        title="Format Cells",
        description="Set font, colour, alignment and number format on a range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "format_cells",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Format Cells",
            "x-keywords": [
                "bold header row",
                "make text bold",
                "change cell background colour",
                "highlight cells",
                "set font size",
                "align text",
                "format as currency",
                "format as date",
                "format as percentage",
                "style a range",
                "wrap text",
            ],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range to format in A1 notation, e.g. A1:D1 for a header row",
        json_schema_extra={"ui:placeholder": "A1:D1"},
    )
    bold: Optional[Literal["true", "false"]] = Field(
        None, title="Bold", description="Make the text bold"
    )
    italic: Optional[Literal["true", "false"]] = Field(
        None, title="Italic", description="Make the text italic"
    )
    underline: Optional[Literal["true", "false"]] = Field(
        None, title="Underline", description="Underline the text"
    )
    strikethrough: Optional[Literal["true", "false"]] = Field(
        None, title="Strikethrough", description="Strike through the text"
    )
    font_size: Optional[int] = Field(
        None, title="Font Size", description="Font size in points", ge=1, le=400
    )
    font_family: Optional[str] = Field(
        None,
        title="Font Family",
        description="Font name, e.g. Arial or Roboto Mono",
        json_schema_extra={"ui:placeholder": "Arial"},
    )
    text_color: Optional[str] = Field(
        None,
        title="Text Colour",
        description="Hex colour for the text, e.g. #12191B",
        json_schema_extra={"ui:placeholder": "#12191B"},
    )
    background_color: Optional[str] = Field(
        None,
        title="Background Colour",
        description="Hex fill colour for the cells, e.g. #E3F0EB",
        json_schema_extra={"ui:placeholder": "#E3F0EB"},
    )
    horizontal_alignment: Optional[Literal["LEFT", "CENTER", "RIGHT"]] = Field(
        None, title="Horizontal Alignment", description="Horizontal text alignment"
    )
    vertical_alignment: Optional[Literal["TOP", "MIDDLE", "BOTTOM"]] = Field(
        None, title="Vertical Alignment", description="Vertical text alignment"
    )
    wrap_strategy: Optional[Literal["OVERFLOW_CELL", "LEGACY_WRAP", "CLIP", "WRAP"]] = Field(
        None, title="Text Wrapping", description="How text behaves when it exceeds the cell"
    )
    number_format_type: Optional[
        Literal["TEXT", "NUMBER", "PERCENT", "CURRENCY", "DATE", "TIME", "DATE_TIME", "SCIENTIFIC"]
    ] = Field(
        None,
        title="Number Format",
        description="Value type for the cells",
    )
    number_format_pattern: Optional[str] = Field(
        None,
        title="Number Format Pattern",
        description='Optional pattern, e.g. "$#,##0.00" or "yyyy-mm-dd". Requires Number Format.',
        json_schema_extra={"ui:placeholder": "$#,##0.00"},
    )


class GoogleSheetsUpdateSheetPropertiesConfig(GoogleSheetsSheetTargetBase):
    """Configuration for sheet-level display properties"""

    operation: Literal["update_sheet_properties"] = Field(
        "update_sheet_properties",
        title="Update Sheet Properties",
        description="Freeze header rows or columns, set the tab colour, toggle gridlines",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_sheet_properties",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Update Sheet Properties",
            "x-keywords": [
                "freeze header row",
                "freeze panes",
                "freeze first column",
                "lock top row",
                "set tab colour",
                "hide gridlines",
                "hide sheet",
            ],
        },
    )
    frozen_row_count: Optional[int] = Field(
        None,
        title="Frozen Rows",
        description="Number of rows to freeze at the top (1 keeps a header visible)",
        ge=0,
    )
    frozen_column_count: Optional[int] = Field(
        None, title="Frozen Columns", description="Number of columns to freeze at the left", ge=0
    )
    tab_color: Optional[str] = Field(
        None,
        title="Tab Colour",
        description="Hex colour for the sheet tab, e.g. #1B6E5A",
        json_schema_extra={"ui:placeholder": "#1B6E5A"},
    )
    hide_gridlines: Optional[Literal["true", "false"]] = Field(
        None, title="Hide Gridlines", description="Hide the default cell gridlines"
    )
    hidden: Optional[Literal["true", "false"]] = Field(
        None, title="Hide Sheet", description="Hide this sheet from the tab bar"
    )


class GoogleSheetsAutoResizeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for auto-sizing columns or rows to fit their contents"""

    operation: Literal["auto_resize_dimensions"] = Field(
        "auto_resize_dimensions",
        title="Auto-Resize Columns Or Rows",
        description="Resize columns or rows to fit their contents",
        json_schema_extra={
            "ui:hidden": True,
            "const": "auto_resize_dimensions",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Auto-Resize Columns Or Rows",
            "x-keywords": [
                "autofit columns",
                "fit column width to content",
                "resize columns automatically",
                "auto size rows",
            ],
        },
    )
    dimension: Literal["COLUMNS", "ROWS"] = Field(
        "COLUMNS", title="Resize", description="Whether to resize columns or rows"
    )
    start_index: int = Field(
        1, title="Start", description="First column/row to resize (1 = A / row 1)", ge=1
    )
    end_index: Optional[int] = Field(
        None,
        title="End",
        description="Last column/row to resize, inclusive. Leave empty to resize to the end.",
        ge=1,
    )


class GoogleSheetsSetDimensionSizeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for setting an explicit column width or row height"""

    operation: Literal["set_dimension_size"] = Field(
        "set_dimension_size",
        title="Set Column Width Or Row Height",
        description="Set an exact pixel width for columns or height for rows",
        json_schema_extra={
            "ui:hidden": True,
            "const": "set_dimension_size",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Set Column Width Or Row Height",
            "x-keywords": [
                "set column width",
                "make column wider",
                "set row height",
                "widen columns",
            ],
        },
    )
    dimension: Literal["COLUMNS", "ROWS"] = Field(
        "COLUMNS", title="Resize", description="Whether to size columns or rows"
    )
    start_index: int = Field(
        ..., title="Start", description="First column/row to size (1 = A / row 1)", ge=1
    )
    end_index: Optional[int] = Field(
        None, title="End", description="Last column/row to size, inclusive", ge=1
    )
    pixel_size: int = Field(
        ..., title="Size (pixels)", description="Width or height in pixels", ge=2, le=2000
    )


class GoogleSheetsMergeCellsConfig(GoogleSheetsSheetTargetBase):
    """Configuration for merging cells"""

    operation: Literal["merge_cells"] = Field(
        "merge_cells",
        title="Merge Cells",
        description="Merge a range into a single cell",
        json_schema_extra={
            "ui:hidden": True,
            "const": "merge_cells",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Merge Cells",
            "x-keywords": ["merge cells", "combine cells", "merge across", "join cells"],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range to merge in A1 notation",
        json_schema_extra={"ui:placeholder": "A1:D1"},
    )
    merge_type: Literal["MERGE_ALL", "MERGE_COLUMNS", "MERGE_ROWS"] = Field(
        "MERGE_ALL",
        title="Merge Type",
        description="Merge everything, merge each column, or merge each row",
    )


class GoogleSheetsUnmergeCellsConfig(GoogleSheetsSheetTargetBase):
    """Configuration for unmerging cells"""

    operation: Literal["unmerge_cells"] = Field(
        "unmerge_cells",
        title="Unmerge Cells",
        description="Split merged cells back apart",
        json_schema_extra={
            "ui:hidden": True,
            "const": "unmerge_cells",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Unmerge Cells",
            "x-keywords": ["unmerge cells", "split merged cells", "undo merge"],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range to unmerge in A1 notation",
        json_schema_extra={"ui:placeholder": "A1:D1"},
    )


class GoogleSheetsUpdateBordersConfig(GoogleSheetsSheetTargetBase):
    """Configuration for drawing borders on a range"""

    operation: Literal["format_borders"] = Field(
        "format_borders",
        title="Add Or Remove Borders",
        description="Draw or clear borders around and inside a range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "format_borders",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Add Or Remove Borders",
            "x-keywords": [
                "add borders",
                "draw table borders",
                "outline a range",
                "add gridlines to a range",
                "underline header",
            ],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range to apply borders to in A1 notation",
        json_schema_extra={"ui:placeholder": "A1:D10"},
    )
    border_style: Literal[
        "SOLID", "SOLID_MEDIUM", "SOLID_THICK", "DASHED", "DOTTED", "DOUBLE", "NONE"
    ] = Field("SOLID", title="Border Style", description="Line style. NONE removes borders.")
    border_color: Optional[str] = Field(
        None,
        title="Border Colour",
        description="Hex colour for the borders, e.g. #D9E0DE",
        json_schema_extra={"ui:placeholder": "#D9E0DE"},
    )
    apply_to: Literal["ALL", "OUTER", "INNER", "BOTTOM", "TOP"] = Field(
        "ALL",
        title="Apply To",
        description="Which edges to draw: every edge, the outside only, the inside only, or a single side",
    )


class GoogleSheetsAddBandingConfig(GoogleSheetsSheetTargetBase):
    """Configuration for alternating row colours"""

    operation: Literal["add_alternating_colors"] = Field(
        "add_alternating_colors",
        title="Add Alternating Colours",
        description="Apply banded row colours to a range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_alternating_colors",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Add Alternating Colours",
            "x-keywords": [
                "alternating row colours",
                "banded rows",
                "zebra striping",
                "stripe rows",
                "make it readable",
            ],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range to band in A1 notation",
        json_schema_extra={"ui:placeholder": "A1:Z100"},
    )
    header_color: Optional[str] = Field(
        None,
        title="Header Colour",
        description="Hex colour for the header band, e.g. #1B6E5A",
        json_schema_extra={"ui:placeholder": "#1B6E5A"},
    )
    first_band_color: str = Field(
        "#FFFFFF",
        title="First Band Colour",
        description="Hex colour for odd rows",
        json_schema_extra={"ui:placeholder": "#FFFFFF"},
    )
    second_band_color: str = Field(
        "#F1F3F2",
        title="Second Band Colour",
        description="Hex colour for even rows",
        json_schema_extra={"ui:placeholder": "#F1F3F2"},
    )


class GoogleSheetsSetBasicFilterConfig(GoogleSheetsSheetTargetBase):
    """Configuration for adding a filter to a range"""

    operation: Literal["set_basic_filter"] = Field(
        "set_basic_filter",
        title="Set Filter",
        description="Add sort and filter controls to a header range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "set_basic_filter",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Set Filter",
            "x-keywords": [
                "add filter",
                "filter headers",
                "make columns sortable",
                "add autofilter",
                "enable sorting",
            ],
        },
    )
    range: Optional[str] = Field(
        None,
        title="Range",
        description="Range to cover in A1 notation. Leave empty to filter the whole sheet.",
        json_schema_extra={"ui:placeholder": "A1:Z100"},
    )


class GoogleSheetsClearBasicFilterConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing a filter"""

    operation: Literal["clear_basic_filter"] = Field(
        "clear_basic_filter",
        title="Clear Filter",
        description="Remove the sort and filter controls from a sheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "clear_basic_filter",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Clear Filter",
            "x-keywords": ["remove filter", "clear autofilter", "turn off filtering"],
        },
    )


class GoogleSheetsConditionalFormatConfig(GoogleSheetsSheetTargetBase):
    """Configuration for a conditional formatting rule"""

    operation: Literal["add_conditional_format_rule"] = Field(
        "add_conditional_format_rule",
        title="Add Conditional Formatting",
        description="Colour cells automatically based on their value",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_conditional_format_rule",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Add Conditional Formatting",
            "x-keywords": [
                "conditional formatting",
                "highlight cells over a value",
                "colour code status",
                "red if overdue",
                "highlight duplicates by formula",
                "colour scale",
            ],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range the rule applies to in A1 notation",
        json_schema_extra={"ui:placeholder": "A2:A100"},
    )
    condition_type: Literal[
        "NUMBER_GREATER",
        "NUMBER_LESS",
        "NUMBER_EQ",
        "NUMBER_BETWEEN",
        "TEXT_CONTAINS",
        "TEXT_EQ",
        "TEXT_STARTS_WITH",
        "BLANK",
        "NOT_BLANK",
        "CUSTOM_FORMULA",
    ] = Field(..., title="Condition", description="What has to be true for the format to apply")
    value: Optional[str] = Field(
        None,
        title="Value",
        description="Value to compare against, or the formula for a custom rule",
        json_schema_extra={"ui:placeholder": "100"},
    )
    value_max: Optional[str] = Field(
        None,
        title="Second Value",
        description="Upper bound, used only by the between condition",
    )
    background_color: Optional[str] = Field(
        None,
        title="Background Colour",
        description="Hex fill applied when the condition is met",
        json_schema_extra={"ui:placeholder": "#E3F0EB"},
    )
    text_color: Optional[str] = Field(
        None,
        title="Text Colour",
        description="Hex text colour applied when the condition is met",
        json_schema_extra={"ui:placeholder": "#97473A"},
    )
    bold: Optional[Literal["true", "false"]] = Field(
        None, title="Bold", description="Bold the text when the condition is met"
    )


class GoogleSheetsSortRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for sorting a range"""

    operation: Literal["sort_range"] = Field(
        "sort_range",
        title="Sort Range",
        description="Sort rows in a range by a column",
        json_schema_extra={
            "ui:hidden": True,
            "const": "sort_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Sort Range",
            "x-keywords": [
                "sort rows",
                "order by column",
                "sort descending",
                "rank rows",
                "sort a to z",
            ],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range to sort in A1 notation. Exclude the header row.",
        json_schema_extra={"ui:placeholder": "A2:Z100"},
    )
    sort_column: int = Field(
        ...,
        title="Sort By Column",
        description="Column to sort on (1 = A, 2 = B, etc.)",
        ge=1,
    )
    sort_order: Literal["ASCENDING", "DESCENDING"] = Field(
        "ASCENDING", title="Order", description="Sort direction"
    )


class GoogleSheetsSetDataValidationConfig(GoogleSheetsSheetTargetBase):
    """Configuration for adding a dropdown or input rule to a range"""

    operation: Literal["set_data_validation"] = Field(
        "set_data_validation",
        title="Add Dropdown Or Input Rule",
        description="Restrict a range to a set of values, a checkbox, or a validated input",
        json_schema_extra={
            "ui:hidden": True,
            "const": "set_data_validation",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Add Dropdown Or Input Rule",
            "x-keywords": [
                "add a dropdown",
                "dropdown list",
                "restrict values",
                "data validation",
                "pick from a list",
                "status column options",
                "add checkbox",
                "validate input",
                "limit what can be entered",
            ],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range to apply the rule to in A1 notation, e.g. R2:R100 for a status column",
        json_schema_extra={"ui:placeholder": "R2:R100"},
    )
    rule_type: Literal[
        "list", "list_from_range", "checkbox", "number_between", "date", "email", "url", "custom_formula"
    ] = Field(
        "list",
        title="Rule Type",
        description="What the cells are allowed to contain. 'list' is the usual dropdown.",
    )
    values: Optional[str] = Field(
        None,
        title="Values",
        description=(
            'Dropdown options as a comma-separated list or a JSON array — '
            'e.g. Not started, Contacted, Won. For "from range" use an A1 range like '
            "Config!A2:A10; for a custom formula use the formula itself."
        ),
        json_schema_extra={"ui:placeholder": "Not started, Contacted, Won"},
    )
    min_value: Optional[str] = Field(
        None, title="Minimum", description="Lower bound, used only by the number range rule"
    )
    max_value: Optional[str] = Field(
        None, title="Maximum", description="Upper bound, used only by the number range rule"
    )
    strict: Optional[Literal["true", "false"]] = Field(
        "true",
        title="Reject Invalid Entries",
        description="Yes rejects anything outside the rule; No allows it with a warning",
    )
    show_dropdown: Optional[Literal["true", "false"]] = Field(
        "true",
        title="Show Dropdown Chip",
        description="Show the in-cell dropdown arrow (list rules only)",
    )
    help_text: Optional[str] = Field(
        None,
        title="Help Text",
        description="Message shown when someone selects a cell in the range",
        json_schema_extra={"ui:placeholder": "Pick the current outreach stage"},
    )


class GoogleSheetsClearDataValidationConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing dropdowns / input rules from a range"""

    operation: Literal["clear_data_validation"] = Field(
        "clear_data_validation",
        title="Remove Dropdown Or Input Rule",
        description="Strip data validation from a range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "clear_data_validation",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Remove Dropdown Or Input Rule",
            "x-keywords": [
                "remove dropdown",
                "clear data validation",
                "delete input rule",
                "unrestrict values",
            ],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range to clear in A1 notation",
        json_schema_extra={"ui:placeholder": "R2:R100"},
    )


class GoogleSheetsDeleteConditionalFormatConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing conditional formatting rules"""

    operation: Literal["delete_conditional_format_rules"] = Field(
        "delete_conditional_format_rules",
        title="Remove Conditional Formatting",
        description="Delete one conditional formatting rule, or every rule on the sheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_conditional_format_rules",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Remove Conditional Formatting",
            "x-keywords": [
                "remove conditional formatting",
                "delete colour rule",
                "clear highlighting rules",
                "reset conditional format",
            ],
        },
    )
    rule_index: Optional[int] = Field(
        None,
        title="Rule Number",
        description="Which rule to remove, counting from 0 as the highest priority. Leave empty to remove all rules on the sheet.",
        ge=0,
    )


class GoogleSheetsClearBandingConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing alternating row colours"""

    operation: Literal["clear_alternating_colors"] = Field(
        "clear_alternating_colors",
        title="Remove Alternating Colours",
        description="Strip banded row colours from a sheet so they can be reapplied",
        json_schema_extra={
            "ui:hidden": True,
            "const": "clear_alternating_colors",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Remove Alternating Colours",
            "x-keywords": [
                "remove banding",
                "clear alternating colours",
                "remove zebra striping",
                "reset row colours",
            ],
        },
    )


class GoogleSheetsAddTableConfig(GoogleSheetsSheetTargetBase):
    """Configuration for turning a range into a Sheets table"""

    operation: Literal["add_table"] = Field(
        "add_table",
        title="Convert Range To Table",
        description="Turn a range into a table, with chip dropdowns and typed columns",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_table",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Convert Range To Table",
            "x-keywords": [
                "convert range to table",
                "turn a range into a table",
                "chip dropdown",
                "coloured dropdown pills",
                "typed columns",
                "make it a table",
            ],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range to convert, including the header row, e.g. A1:X13",
        json_schema_extra={"ui:placeholder": "A1:X13"},
    )
    table_name: str = Field(
        ...,
        title="Table Name",
        description="Name for the table, used to reference it later",
        json_schema_extra={"ui:placeholder": "Prospects"},
    )
    columns: Optional[str] = Field(
        None,
        title="Column Types",
        description=(
            'JSON list of typed columns, e.g. [{"column": "R", "type": "DROPDOWN", '
            '"values": "Not started, Contacted, Won"}]. Columns you leave out stay plain text. '
            "A DROPDOWN column renders as colour chips and requires values."
        ),
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "ui:placeholder": '[{"column": "R", "type": "DROPDOWN", "values": "Not started, Won"}]',
        },
    )


class GoogleSheetsDeleteTableConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing a table"""

    operation: Literal["delete_table"] = Field(
        "delete_table",
        title="Delete Table",
        description="Remove a table, leaving its values in place",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_table",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Delete Table",
            "x-keywords": [
                "delete table",
                "remove table",
                "convert table back to a range",
                "undo table",
            ],
        },
    )
    table_name: str = Field(
        ...,
        title="Table Name",
        description="Name of the table to remove",
        json_schema_extra={"ui:placeholder": "Prospects"},
    )


# ============================================================================
# Coverage phase 1 — completing families we already ship, plus named and
# protected ranges. Every one of these is an update/delete counterpart to an
# operation that could previously only add, which is what made formatting
# scripts one-way.
# ============================================================================


class GoogleSheetsUpdateConditionalFormatConfig(GoogleSheetsSheetTargetBase):
    """Configuration for editing or reordering a conditional formatting rule"""

    operation: Literal["update_conditional_format_rule"] = Field(
        "update_conditional_format_rule",
        title="Edit Conditional Formatting",
        description="Change a conditional formatting rule, or move it up or down the priority order",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_conditional_format_rule",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Edit Conditional Formatting",
            "x-keywords": [
                "edit conditional formatting",
                "reorder colour rules",
                "change rule priority",
                "move rule up",
                "which rule wins",
            ],
        },
    )
    rule_index: int = Field(
        ...,
        title="Rule Number",
        description="Which rule to change, counting from 0 as the highest priority",
        ge=0,
    )
    new_index: Optional[int] = Field(
        None,
        title="Move To Position",
        description=(
            "Move the rule to this position instead of editing it. Rules are applied in order "
            "and the first match wins per cell, so position decides which rule shows."
        ),
        ge=0,
    )
    range: Optional[str] = Field(
        None,
        title="Range",
        description="New range for the rule in A1 notation. Leave empty to keep the current one.",
        json_schema_extra={"ui:placeholder": "A2:A100"},
    )
    condition_type: Optional[
        Literal[
            "NUMBER_GREATER", "NUMBER_LESS", "NUMBER_EQ", "NUMBER_BETWEEN",
            "TEXT_CONTAINS", "TEXT_EQ", "TEXT_STARTS_WITH", "BLANK", "NOT_BLANK", "CUSTOM_FORMULA",
        ]
    ] = Field(None, title="Condition", description="New condition. Required when editing the rule.")
    value: Optional[str] = Field(None, title="Value", description="Value to compare against, or the formula")
    value_max: Optional[str] = Field(None, title="Second Value", description="Upper bound for the between condition")
    background_color: Optional[str] = Field(
        None, title="Background Colour", description="Hex fill applied when the condition is met",
        json_schema_extra={"ui:placeholder": "#E3F0EB"},
    )
    text_color: Optional[str] = Field(
        None, title="Text Colour", description="Hex text colour applied when the condition is met",
        json_schema_extra={"ui:placeholder": "#97473A"},
    )
    bold: Optional[Literal["true", "false"]] = Field(
        None, title="Bold", description="Bold the text when the condition is met"
    )


class GoogleSheetsUpdateBandingConfig(GoogleSheetsSheetTargetBase):
    """Configuration for recolouring existing banding in place"""

    operation: Literal["update_alternating_colors"] = Field(
        "update_alternating_colors",
        title="Recolour Alternating Colours",
        description="Change the colours of banding that is already applied, without removing it first",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_alternating_colors",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Recolour Alternating Colours",
            "x-keywords": [
                "change banding colours",
                "recolour banded rows",
                "edit alternating colours",
                "restyle zebra striping",
            ],
        },
    )
    header_color: Optional[str] = Field(
        None, title="Header Colour", description="Hex colour for the header band",
        json_schema_extra={"ui:placeholder": "#1B6E5A"},
    )
    first_band_color: Optional[str] = Field(
        None, title="First Band Colour", description="Hex colour for odd rows",
        json_schema_extra={"ui:placeholder": "#FFFFFF"},
    )
    second_band_color: Optional[str] = Field(
        None, title="Second Band Colour", description="Hex colour for even rows",
        json_schema_extra={"ui:placeholder": "#F1F3F2"},
    )


class GoogleSheetsUpdateTableConfig(GoogleSheetsSheetTargetBase):
    """Configuration for changing a table's name, range or column types"""

    operation: Literal["update_table"] = Field(
        "update_table",
        title="Edit Table",
        description="Rename a table, resize it, or retype its columns",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_table",
            "x-category": "Format",
            "x-is-trigger": False,
            "x-display-name": "Edit Table",
            "x-keywords": [
                "rename table",
                "resize table",
                "change table columns",
                "edit table dropdown values",
            ],
        },
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to change",
        json_schema_extra={"ui:placeholder": "Prospects"},
    )
    new_name: Optional[str] = Field(
        None, title="New Name", description="Rename the table to this"
    )
    range: Optional[str] = Field(
        None, title="New Range", description="Resize the table to this A1 range",
        json_schema_extra={"ui:placeholder": "A1:X40"},
    )
    columns: Optional[str] = Field(
        None,
        title="Column Types",
        description='JSON list of typed columns, same shape as Create Table, e.g. [{"column": "R", "type": "DROPDOWN", "values": "A, B"}]',
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
        },
    )


class GoogleSheetsUpdateSpreadsheetPropertiesConfig(BaseModel):
    """Configuration for spreadsheet-level properties"""

    operation: Literal["update_spreadsheet_properties"] = Field(
        "update_spreadsheet_properties",
        title="Update Spreadsheet Properties",
        description="Rename the spreadsheet or change its locale, timezone or recalculation setting",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_spreadsheet_properties",
            "x-category": "Spreadsheet",
            "x-is-trigger": False,
            "x-display-name": "Update Spreadsheet Properties",
            "x-keywords": [
                "rename spreadsheet",
                "change spreadsheet title",
                "set timezone",
                "set locale",
                "recalculation interval",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    title: Optional[str] = Field(None, title="Title", description="New name for the spreadsheet")
    locale: Optional[str] = Field(
        None, title="Locale", description="Locale code, e.g. en_US",
        json_schema_extra={"ui:placeholder": "en_US"},
    )
    time_zone: Optional[str] = Field(
        None, title="Timezone", description="Timezone in CLDR format, e.g. Europe/London",
        json_schema_extra={"ui:placeholder": "Europe/London"},
    )
    auto_recalc: Optional[Literal["ON_CHANGE", "MINUTE", "HOUR"]] = Field(
        None, title="Recalculate", description="How often volatile functions recalculate"
    )


class GoogleSheetsAddNamedRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for naming a range"""

    operation: Literal["add_named_range"] = Field(
        "add_named_range",
        title="Add Named Range",
        description="Give a range a name so formulas can refer to it",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_named_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Add Named Range",
            "x-keywords": [
                "name a range",
                "named range",
                "create a range alias",
                "label a range for formulas",
            ],
        },
    )
    range_name: str = Field(
        ..., title="Name", description="Name for the range, letters, digits and underscores",
        json_schema_extra={"ui:placeholder": "StatusOptions"},
    )
    range: str = Field(
        ..., title="Range", description="Range to name in A1 notation",
        json_schema_extra={"ui:placeholder": "A2:A10"},
    )


class GoogleSheetsUpdateNamedRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for changing a named range"""

    operation: Literal["update_named_range"] = Field(
        "update_named_range",
        title="Update Named Range",
        description="Rename a named range or point it at a different range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_named_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Update Named Range",
            "x-keywords": ["rename named range", "repoint named range", "edit named range"],
        },
    )
    range_name: str = Field(..., title="Current Name", description="Name of the range to change")
    new_name: Optional[str] = Field(None, title="New Name", description="Rename it to this")
    range: Optional[str] = Field(
        None, title="New Range", description="Point it at this A1 range instead",
        json_schema_extra={"ui:placeholder": "A2:A20"},
    )


class GoogleSheetsDeleteNamedRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing a named range"""

    operation: Literal["delete_named_range"] = Field(
        "delete_named_range",
        title="Delete Named Range",
        description="Remove a named range. The cells and their values stay.",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_named_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Delete Named Range",
            "x-keywords": ["remove named range", "delete range name", "unname a range"],
        },
    )
    range_name: str = Field(..., title="Name", description="Name of the range to remove")


class GoogleSheetsAddProtectedRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for protecting a range from edits"""

    operation: Literal["add_protected_range"] = Field(
        "add_protected_range",
        title="Protect Range",
        description="Stop a range being edited, or warn when someone tries",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_protected_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Protect Range",
            "x-keywords": [
                "protect a range",
                "lock cells",
                "prevent editing",
                "make cells read only",
                "warn before editing",
            ],
        },
    )
    range: Optional[str] = Field(
        None,
        title="Range",
        description="Range to protect in A1 notation. Leave empty to protect the whole sheet.",
        json_schema_extra={"ui:placeholder": "A1:X1"},
    )
    description: Optional[str] = Field(
        None, title="Description", description="Why this range is protected",
        json_schema_extra={"ui:placeholder": "Header row — do not edit"},
    )
    warning_only: Optional[Literal["true", "false"]] = Field(
        "false",
        title="Warning Only",
        description="Yes shows a warning but still allows the edit; No blocks it outright",
    )
    editors: Optional[str] = Field(
        None,
        title="Allowed Editors",
        description="Comma-separated email addresses that may still edit. Ignored when Warning Only is Yes.",
        json_schema_extra={"ui:placeholder": "me@example.com, ops@example.com"},
    )


class GoogleSheetsUpdateProtectedRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for changing a protected range"""

    operation: Literal["update_protected_range"] = Field(
        "update_protected_range",
        title="Update Protected Range",
        description="Change a protected range's extent, description or editors",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_protected_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Update Protected Range",
            "x-keywords": ["change protection", "edit protected range", "change who can edit"],
        },
    )
    description: str = Field(
        ...,
        title="Description",
        description="Description of the protected range to change — this is how it is identified",
    )
    range: Optional[str] = Field(
        None, title="New Range", description="Move the protection to this A1 range"
    )
    new_description: Optional[str] = Field(
        None, title="New Description", description="Change the description to this"
    )
    warning_only: Optional[Literal["true", "false"]] = Field(
        None, title="Warning Only", description="Switch between warning and hard block"
    )
    editors: Optional[str] = Field(
        None, title="Allowed Editors", description="Comma-separated email addresses that may edit"
    )


class GoogleSheetsDeleteProtectedRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing range protection"""

    operation: Literal["delete_protected_range"] = Field(
        "delete_protected_range",
        title="Unprotect Range",
        description="Remove protection from a range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_protected_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Unprotect Range",
            "x-keywords": ["remove protection", "unlock cells", "unprotect range", "allow editing"],
        },
    )
    description: str = Field(
        ..., title="Description", description="Description of the protected range to remove"
    )


# ============================================================================
# Coverage phase 2 — values, cells and data wrangling.
#
# Three of these ride on updateCells (notes, smart chips, pivot tables), which
# has no dedicated request of its own. The rest are the range-level operations
# the Sheets UI exposes under Data and Edit.
# ============================================================================

_PASTE_TYPES = Literal[
    "PASTE_NORMAL", "PASTE_VALUES", "PASTE_FORMAT", "PASTE_NO_BORDERS",
    "PASTE_FORMULA", "PASTE_DATA_VALIDATION", "PASTE_CONDITIONAL_FORMATTING",
]


class GoogleSheetsSetNotesConfig(GoogleSheetsSheetTargetBase):
    """Configuration for putting a hover note on cells"""

    operation: Literal["set_cell_notes"] = Field(
        "set_cell_notes",
        title="Cell Notes",
        description="Attach a hover note to every cell in a range, or clear them",
        json_schema_extra={
            "ui:hidden": True,
            "const": "set_cell_notes",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Cell Notes",
            "x-keywords": [
                "add a note to a cell",
                "cell note",
                "hover note",
                "annotate cells",
                "clear notes",
            ],
        },
    )
    range: str = Field(
        ..., title="Range", description="Range to annotate in A1 notation",
        json_schema_extra={"ui:placeholder": "A2:A100"},
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="Text of the note. Leave empty to remove existing notes from the range.",
        json_schema_extra={"ui:rows": 3},
    )


class GoogleSheetsSmartChipsConfig(GoogleSheetsSheetTargetBase):
    """Configuration for inserting people or link smart chips"""

    operation: Literal["insert_smart_chips"] = Field(
        "insert_smart_chips",
        title="Insert Smart Chips",
        description="Turn cells into people chips or rich link chips",
        json_schema_extra={
            "ui:hidden": True,
            "const": "insert_smart_chips",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Insert Smart Chips",
            "x-keywords": [
                "smart chip",
                "people chip",
                "person chip",
                "link chip",
                "insert a chip",
                "mention someone in a cell",
            ],
        },
    )
    range: str = Field(
        ..., title="Range", description="Range to fill with chips, one chip per cell",
        json_schema_extra={"ui:placeholder": "S2:S13"},
    )
    chip_type: Literal["person", "link"] = Field(
        "person", title="Chip Type", description="A person chip or a rich link chip"
    )
    values: str = Field(
        ...,
        title="Values",
        description=(
            "Comma-separated list or JSON array, one per cell down the range — "
            "email addresses for person chips, URLs for link chips."
        ),
        json_schema_extra={"ui:placeholder": "sam@example.com, alex@example.com"},
    )
    display_format: Optional[Literal["DEFAULT", "LAST_NAME_COMMA_FIRST_NAME", "EMAIL"]] = Field(
        None, title="Display Format", description="How a person chip renders"
    )


class GoogleSheetsPivotTableConfig(GoogleSheetsSheetTargetBase):
    """Configuration for anchoring a pivot table"""

    operation: Literal["insert_pivot_table"] = Field(
        "insert_pivot_table",
        title="Pivot Table",
        description="Summarise a source range into a pivot table anchored at a cell",
        json_schema_extra={
            "ui:hidden": True,
            "const": "insert_pivot_table",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Pivot Table",
            "x-keywords": [
                "pivot table",
                "summarise by category",
                "group and total",
                "cross tabulate",
                "breakdown by column",
            ],
        },
    )
    anchor_cell: str = Field(
        ...,
        title="Anchor Cell",
        description="Top-left cell where the pivot table is placed, e.g. A1",
        json_schema_extra={"ui:placeholder": "A1"},
    )
    source_range: str = Field(
        ...,
        title="Source Range",
        description="Range to summarise, including its header row",
        json_schema_extra={"ui:placeholder": "A1:Z100"},
    )
    source_sheet_name: Optional[str] = Field(
        None,
        title="Source Sheet",
        description="Sheet the source range lives on. Defaults to the sheet selected above.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Same sheet",
                "depends_on": "spreadsheet_id",
            },
            "x-resource-type": "google_sheet_tab",
        },
    )
    pivot_rows: Optional[str] = Field(
        None,
        title="Group Rows By",
        description="Comma-separated source column letters to group down the side, e.g. E, R",
        json_schema_extra={"ui:placeholder": "E, R"},
    )
    pivot_columns: Optional[str] = Field(
        None,
        title="Group Columns By",
        description="Comma-separated source column letters to group across the top",
        json_schema_extra={"ui:placeholder": "D"},
    )
    pivot_values: str = Field(
        ...,
        title="Summarise",
        description=(
            'JSON list of what to total, e.g. [{"column": "F", "function": "SUM"}]. '
            "Functions: SUM, COUNTA, COUNT, COUNTUNIQUE, AVERAGE, MAX, MIN, MEDIAN, "
            "PRODUCT, STDEV, STDEVP, VAR, VARP."
        ),
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "ui:placeholder": '[{"column": "F", "function": "SUM"}]',
        },
    )


class GoogleSheetsCopyPasteConfig(GoogleSheetsSheetTargetBase):
    """Configuration for copying a range onto another"""

    operation: Literal["copy_paste_range"] = Field(
        "copy_paste_range",
        title="Copy And Paste Range",
        description="Copy a range over another, optionally values-only or format-only",
        json_schema_extra={
            "ui:hidden": True,
            "const": "copy_paste_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Copy And Paste Range",
            "x-keywords": [
                "copy a range",
                "paste values only",
                "copy formatting",
                "duplicate a range",
                "paste special",
            ],
        },
    )
    source_range: str = Field(
        ..., title="Copy From", description="Source range in A1 notation",
        json_schema_extra={"ui:placeholder": "A1:D10"},
    )
    destination_range: str = Field(
        ..., title="Paste To", description="Destination range in A1 notation",
        json_schema_extra={"ui:placeholder": "F1:I10"},
    )
    paste_type: _PASTE_TYPES = Field(
        "PASTE_NORMAL", title="Paste", description="What to carry over"
    )
    transpose: Optional[Literal["true", "false"]] = Field(
        "false", title="Transpose", description="Swap rows and columns while pasting"
    )


class GoogleSheetsCutPasteConfig(GoogleSheetsSheetTargetBase):
    """Configuration for moving a range"""

    operation: Literal["cut_paste_range"] = Field(
        "cut_paste_range",
        title="Cut And Paste Range",
        description="Move a range somewhere else, leaving the source empty",
        json_schema_extra={
            "ui:hidden": True,
            "const": "cut_paste_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Cut And Paste Range",
            "x-keywords": ["move a range", "cut and paste", "relocate cells"],
        },
    )
    source_range: str = Field(
        ..., title="Cut From", description="Source range in A1 notation",
        json_schema_extra={"ui:placeholder": "A1:D10"},
    )
    destination_cell: str = Field(
        ...,
        title="Paste To",
        description="Top-left cell of the destination, e.g. F1",
        json_schema_extra={"ui:placeholder": "F1"},
    )
    paste_type: _PASTE_TYPES = Field(
        "PASTE_NORMAL", title="Paste", description="What to carry over"
    )


class GoogleSheetsPasteDataConfig(GoogleSheetsSheetTargetBase):
    """Configuration for pasting delimited text"""

    operation: Literal["paste_data"] = Field(
        "paste_data",
        title="Paste Delimited Text",
        description="Paste CSV or tab-separated text into a range, splitting it into cells",
        json_schema_extra={
            "ui:hidden": True,
            "const": "paste_data",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Paste Delimited Text",
            "x-keywords": [
                "paste csv",
                "import csv text",
                "paste tab separated",
                "paste delimited data",
            ],
        },
    )
    anchor_cell: str = Field(
        ..., title="Anchor Cell", description="Top-left cell to paste into",
        json_schema_extra={"ui:placeholder": "A1"},
    )
    data: str = Field(
        ...,
        title="Data",
        description="The delimited text to paste",
        json_schema_extra={"ui:widget": "code_editor", "ui:rows": 6},
    )
    delimiter: str = Field(
        ",", title="Delimiter", description="Character separating the values",
        json_schema_extra={"ui:placeholder": ","},
    )


class GoogleSheetsAutoFillConfig(GoogleSheetsSheetTargetBase):
    """Configuration for extending a series"""

    operation: Literal["auto_fill"] = Field(
        "auto_fill",
        title="Auto-Fill Range",
        description="Continue a pattern or series across a range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "auto_fill",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Auto-Fill Range",
            "x-keywords": [
                "autofill",
                "fill down",
                "continue a series",
                "extend a pattern",
                "drag fill",
            ],
        },
    )
    range: str = Field(
        ...,
        title="Range",
        description="Range containing the existing values plus the cells to fill",
        json_schema_extra={"ui:placeholder": "A1:A100"},
    )
    use_alternate_series: Optional[Literal["true", "false"]] = Field(
        "false",
        title="Alternate Series",
        description="Use the alternate interpretation of the pattern",
    )


class GoogleSheetsTextToColumnsConfig(GoogleSheetsSheetTargetBase):
    """Configuration for splitting a column of text"""

    operation: Literal["split_text_to_columns"] = Field(
        "split_text_to_columns",
        title="Split Text To Columns",
        description="Split one column of delimited text across several columns",
        json_schema_extra={
            "ui:hidden": True,
            "const": "split_text_to_columns",
            "x-category": "Column",
            "x-is-trigger": False,
            "x-display-name": "Split Text To Columns",
            "x-keywords": [
                "split text to columns",
                "separate by comma",
                "split a column",
                "text to columns",
            ],
        },
    )
    range: str = Field(
        ..., title="Range", description="Single column of text to split",
        json_schema_extra={"ui:placeholder": "A2:A100"},
    )
    delimiter_type: Literal["COMMA", "SEMICOLON", "PERIOD", "SPACE", "CUSTOM", "AUTODETECT"] = Field(
        "AUTODETECT", title="Split On", description="What separates the values"
    )
    custom_delimiter: Optional[str] = Field(
        None, title="Custom Delimiter", description="Character to split on, when Split On is CUSTOM"
    )


class GoogleSheetsTrimWhitespaceConfig(GoogleSheetsSheetTargetBase):
    """Configuration for trimming whitespace"""

    operation: Literal["trim_whitespace"] = Field(
        "trim_whitespace",
        title="Trim Whitespace",
        description="Strip leading, trailing and repeated spaces from a range",
        json_schema_extra={
            "ui:hidden": True,
            "const": "trim_whitespace",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Trim Whitespace",
            "x-keywords": ["trim whitespace", "strip spaces", "clean up spacing", "remove extra spaces"],
        },
    )
    range: str = Field(
        ..., title="Range", description="Range to clean in A1 notation",
        json_schema_extra={"ui:placeholder": "A2:Z100"},
    )


class GoogleSheetsDeleteDuplicatesConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing duplicate rows"""

    operation: Literal["remove_duplicate_rows"] = Field(
        "remove_duplicate_rows",
        title="Remove Duplicate Rows",
        description="Delete rows that repeat, optionally comparing only some columns",
        json_schema_extra={
            "ui:hidden": True,
            "const": "remove_duplicate_rows",
            "x-category": "Row",
            "x-is-trigger": False,
            "x-display-name": "Remove Duplicate Rows",
            "x-keywords": [
                "remove duplicates",
                "dedupe rows",
                "delete duplicate rows",
                "unique rows only",
            ],
        },
    )
    range: str = Field(
        ..., title="Range", description="Range to deduplicate, excluding the header row",
        json_schema_extra={"ui:placeholder": "A2:Z100"},
    )
    compare_columns: Optional[str] = Field(
        None,
        title="Compare Columns",
        description="Comma-separated column letters to compare. Leave empty to compare whole rows.",
        json_schema_extra={"ui:placeholder": "B, E"},
    )


class GoogleSheetsRandomizeRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for shuffling rows"""

    operation: Literal["randomize_range"] = Field(
        "randomize_range",
        title="Randomise Range",
        description="Shuffle the rows of a range into random order",
        json_schema_extra={
            "ui:hidden": True,
            "const": "randomize_range",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Randomise Range",
            "x-keywords": ["shuffle rows", "randomise order", "random sort", "mix up rows"],
        },
    )
    range: str = Field(
        ..., title="Range", description="Range to shuffle, excluding the header row",
        json_schema_extra={"ui:placeholder": "A2:Z100"},
    )


class GoogleSheetsInsertRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for inserting cells and shifting the rest"""

    operation: Literal["insert_cells"] = Field(
        "insert_cells",
        title="Insert Cells",
        description="Insert blank cells, shifting existing cells down or right",
        json_schema_extra={
            "ui:hidden": True,
            "const": "insert_cells",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Insert Cells",
            "x-keywords": ["insert cells", "shift cells down", "shift cells right", "add blank cells"],
        },
    )
    range: str = Field(
        ..., title="Range", description="Where to insert, in A1 notation",
        json_schema_extra={"ui:placeholder": "B2:B10"},
    )
    shift_direction: Literal["ROWS", "COLUMNS"] = Field(
        "ROWS",
        title="Shift",
        description="ROWS shifts existing cells down; COLUMNS shifts them right",
    )


class GoogleSheetsDeleteRangeConfig(GoogleSheetsSheetTargetBase):
    """Configuration for deleting cells and shifting the rest"""

    operation: Literal["delete_cells"] = Field(
        "delete_cells",
        title="Delete Cells",
        description="Delete cells, shifting the remaining cells up or left",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_cells",
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Delete Cells",
            "x-keywords": ["delete cells", "shift cells up", "shift cells left", "remove cells"],
        },
    )
    range: str = Field(
        ..., title="Range", description="Cells to delete, in A1 notation",
        json_schema_extra={"ui:placeholder": "B2:B10"},
    )
    shift_direction: Literal["ROWS", "COLUMNS"] = Field(
        "ROWS", title="Shift", description="ROWS shifts remaining cells up; COLUMNS shifts them left"
    )


class GoogleSheetsMoveDimensionConfig(GoogleSheetsSheetTargetBase):
    """Configuration for moving rows or columns"""

    operation: Literal["move_rows_or_columns"] = Field(
        "move_rows_or_columns",
        title="Move Rows Or Columns",
        description="Move a block of rows or columns to a different position",
        json_schema_extra={
            "ui:hidden": True,
            "const": "move_rows_or_columns",
            "x-category": "Row",
            "x-is-trigger": False,
            "x-display-name": "Move Rows Or Columns",
            "x-keywords": [
                "move rows",
                "move columns",
                "reorder columns",
                "reposition rows",
                "drag a column",
            ],
        },
    )
    dimension: Literal["ROWS", "COLUMNS"] = Field(
        "COLUMNS", title="Move", description="Whether to move rows or columns"
    )
    start_index: int = Field(
        ..., title="From", description="First row/column to move (1 = A / row 1)", ge=1
    )
    end_index: int = Field(
        ..., title="To", description="Last row/column to move, inclusive", ge=1
    )
    destination_index: int = Field(
        ...,
        title="Move Before",
        description="Move the block so it sits before this row/column number",
        ge=1,
    )


class GoogleSheetsAppendDimensionConfig(GoogleSheetsSheetTargetBase):
    """Configuration for appending blank rows or columns"""

    operation: Literal["append_rows_or_columns"] = Field(
        "append_rows_or_columns",
        title="Append Rows Or Columns",
        description="Add blank rows or columns to the end of a sheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "append_rows_or_columns",
            "x-category": "Row",
            "x-is-trigger": False,
            "x-display-name": "Append Rows Or Columns",
            "x-keywords": [
                "add rows at the end",
                "append blank rows",
                "extend the sheet",
                "add more columns",
            ],
        },
    )
    dimension: Literal["ROWS", "COLUMNS"] = Field(
        "ROWS", title="Append", description="Whether to append rows or columns"
    )
    length: int = Field(..., title="How Many", description="Number to append", ge=1)


# ============================================================================
# Coverage phase 3 — charts and embedded objects.
#
# ChartSpec has a dozen variants. The basic types plus pie, histogram and
# scorecard cover the overwhelming majority of real charts; the specialised
# ones (candlestick, org, treemap, waterfall) are deliberately not exposed.
# ============================================================================

_CHART_TYPES = Literal[
    "COLUMN", "STACKED_COLUMN", "BAR", "STACKED_BAR", "LINE", "AREA",
    "STACKED_AREA", "SCATTER", "COMBO", "PIE", "DONUT", "HISTOGRAM", "SCORECARD",
]
_LEGEND = Literal["BOTTOM_LEGEND", "LEFT_LEGEND", "RIGHT_LEGEND", "TOP_LEGEND", "NO_LEGEND"]


class GoogleSheetsAddChartConfig(GoogleSheetsSheetTargetBase):
    """Configuration for adding a chart"""

    operation: Literal["add_chart"] = Field(
        "add_chart",
        title="Add Chart",
        description="Build a chart from a range and place it on a sheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_chart",
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Add Chart",
            "x-keywords": [
                "create a chart", "bar chart", "line graph", "pie chart",
                "plot the data", "visualise a range", "graph these numbers",
            ],
        },
    )
    chart_type: _CHART_TYPES = Field(
        "COLUMN", title="Chart Type", description="Which kind of chart to build"
    )
    chart_title: Optional[str] = Field(
        None, title="Title", description="Title shown above the chart",
        json_schema_extra={"ui:placeholder": "Spend by tier"},
    )
    subtitle: Optional[str] = Field(None, title="Subtitle", description="Smaller text under the title")
    labels_range: Optional[str] = Field(
        None, title="Labels",
        description="Range holding the category labels — the x-axis, or the pie slices",
        json_schema_extra={"ui:placeholder": "A2:A13"},
    )
    series_ranges: str = Field(
        ..., title="Values",
        description="One or more ranges to plot, comma-separated or a JSON array",
        json_schema_extra={"ui:placeholder": "F2:F13, G2:G13"},
    )
    anchor_cell: Optional[str] = Field(
        None, title="Place At",
        description="Top-left cell to anchor the chart. Leave empty to put it on a new sheet.",
        json_schema_extra={"ui:placeholder": "Z2"},
    )
    legend_position: Optional[_LEGEND] = Field(
        None, title="Legend", description="Where the legend sits"
    )
    axis_title: Optional[str] = Field(
        None, title="Value Axis Title", description="Label for the value axis"
    )


class GoogleSheetsUpdateChartConfig(GoogleSheetsSheetTargetBase):
    """Configuration for changing an existing chart"""

    operation: Literal["update_chart"] = Field(
        "update_chart",
        title="Edit Chart",
        description="Change a chart's type, title or the data it plots",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_chart",
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Edit Chart",
            "x-keywords": [
                "change chart type", "edit a chart", "retitle a chart",
                "change what a chart plots",
            ],
        },
    )
    chart_title: str = Field(
        ..., title="Chart",
        description="Title of the chart to change — this is how it is identified",
    )
    chart_type: Optional[_CHART_TYPES] = Field(
        None, title="New Chart Type", description="Change the chart to this type"
    )
    new_title: Optional[str] = Field(None, title="New Title", description="Retitle the chart")
    subtitle: Optional[str] = Field(None, title="Subtitle", description="Smaller text under the title")
    labels_range: Optional[str] = Field(
        None, title="Labels", description="New range for the category labels"
    )
    series_ranges: Optional[str] = Field(
        None, title="Values", description="New ranges to plot, comma-separated or a JSON array"
    )
    legend_position: Optional[_LEGEND] = Field(
        None, title="Legend", description="Where the legend sits"
    )
    axis_title: Optional[str] = Field(
        None, title="Value Axis Title", description="Label for the value axis"
    )


class GoogleSheetsMoveChartConfig(GoogleSheetsSheetTargetBase):
    """Configuration for moving or resizing a chart"""

    operation: Literal["move_chart"] = Field(
        "move_chart",
        title="Move Or Resize Chart",
        description="Reposition a chart, resize it, or move it onto its own sheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "move_chart",
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Move Or Resize Chart",
            "x-keywords": [
                "move a chart", "resize a chart", "reposition a graph",
                "put chart on its own sheet",
            ],
        },
    )
    chart_title: str = Field(..., title="Chart", description="Title of the chart to move")
    anchor_cell: Optional[str] = Field(
        None, title="Place At",
        description="Top-left cell to move it to. Leave empty to move it onto its own sheet.",
        json_schema_extra={"ui:placeholder": "Z2"},
    )
    width_pixels: Optional[int] = Field(
        None, title="Width (pixels)", description="Resize the chart's width", ge=20, le=4000
    )
    height_pixels: Optional[int] = Field(
        None, title="Height (pixels)", description="Resize the chart's height", ge=20, le=4000
    )


class GoogleSheetsChartBorderConfig(GoogleSheetsSheetTargetBase):
    """Configuration for a chart's border colour"""

    operation: Literal["set_chart_border"] = Field(
        "set_chart_border",
        title="Set Chart Border",
        description="Colour the border around a chart",
        json_schema_extra={
            "ui:hidden": True,
            "const": "set_chart_border",
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Set Chart Border",
            "x-keywords": ["chart border", "outline a chart", "border colour around a graph"],
        },
    )
    chart_title: str = Field(..., title="Chart", description="Title of the chart")
    border_color: str = Field(
        ..., title="Border Colour", description="Hex colour for the border",
        json_schema_extra={"ui:placeholder": "#D9E0DE"},
    )


class GoogleSheetsDeleteChartConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing a chart"""

    operation: Literal["delete_chart"] = Field(
        "delete_chart",
        title="Delete Chart",
        description="Remove a chart from the spreadsheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_chart",
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Delete Chart",
            "x-keywords": ["delete a chart", "remove a graph", "get rid of a chart"],
        },
    )
    chart_title: str = Field(..., title="Chart", description="Title of the chart to remove")


class GoogleSheetsAppendCellsConfig(GoogleSheetsSheetTargetBase):
    """Configuration for appending rows of cells after the last row of data"""

    operation: Literal["append_cells"] = Field(
        "append_cells",
        title="Append Rows After Data",
        description="Add rows directly after the last row that has data",
        json_schema_extra={
            "ui:hidden": True,
            "const": "append_cells",
            "x-category": "Row",
            "x-is-trigger": False,
            "x-display-name": "Append Rows After Data",
            "x-keywords": [
                "append after last row", "add rows to the bottom",
                "append raw cells", "add to the end of the data",
            ],
        },
    )
    values: str = Field(
        ..., title="Values",
        description='JSON array of rows, e.g. [["Jane", "jane@x.com"], ["Sam", "sam@x.com"]]',
        json_schema_extra={
            "ui:widget": "code_editor",
            "x-code-language": "json",
            "ui:placeholder": '[["Jane", "jane@x.com"]]',
        },
    )


# ============================================================================
# Coverage phase 4 — saved views, grouping and slicers.
#
# A filter view is a named, private filter: it does not change what anyone
# else sees, which is what makes it the right tool on a shared sheet. Slicers
# are the interactive control version of the same idea.
# ============================================================================


class GoogleSheetsAddFilterViewConfig(GoogleSheetsSheetTargetBase):
    """Configuration for creating a saved filter view"""

    operation: Literal["save_filter_view"] = Field(
        "save_filter_view",
        title="Filter View",
        description="Save a named filter that only you see, leaving everyone else's view alone",
        json_schema_extra={
            "ui:hidden": True,
            "const": "save_filter_view",
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Filter View",
            "x-keywords": [
                "filter view", "saved filter", "private filter",
                "filter without affecting others", "named view",
            ],
        },
    )
    view_title: str = Field(
        ..., title="View Name", description="Name for the filter view",
        json_schema_extra={"ui:placeholder": "Priority targets"},
    )
    range: Optional[str] = Field(
        None, title="Range",
        description="Range the view covers. Leave empty for the whole sheet.",
        json_schema_extra={"ui:placeholder": "A1:X13"},
    )
    sort_column: Optional[str] = Field(
        None, title="Sort By Column", description="Column letter to sort on",
        json_schema_extra={"ui:placeholder": "Q"},
    )
    sort_order: Optional[Literal["ASCENDING", "DESCENDING"]] = Field(
        None, title="Sort Order", description="Sort direction"
    )
    hide_values: Optional[str] = Field(
        None,
        title="Hide Values",
        description=(
            'JSON list of per-column hidden values, e.g. '
            '[{"column": "R", "hide": "Passed, Won"}]'
        ),
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class GoogleSheetsUpdateFilterViewConfig(GoogleSheetsSheetTargetBase):
    """Configuration for changing a filter view"""

    operation: Literal["update_filter_view"] = Field(
        "update_filter_view",
        title="Update Filter View",
        description="Rename a filter view, move it, or change how it sorts",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_filter_view",
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Update Filter View",
            "x-keywords": ["rename filter view", "edit a saved filter", "change filter view sort"],
        },
    )
    view_title: str = Field(..., title="View Name", description="Name of the view to change")
    new_title: Optional[str] = Field(None, title="New Name", description="Rename the view")
    range: Optional[str] = Field(None, title="New Range", description="Move the view to this range")
    sort_column: Optional[str] = Field(None, title="Sort By Column", description="Column letter to sort on")
    sort_order: Optional[Literal["ASCENDING", "DESCENDING"]] = Field(
        None, title="Sort Order", description="Sort direction"
    )


class GoogleSheetsDuplicateFilterViewConfig(GoogleSheetsSheetTargetBase):
    """Configuration for copying a filter view"""

    operation: Literal["duplicate_filter_view"] = Field(
        "duplicate_filter_view",
        title="Duplicate Filter View",
        description="Copy a filter view so it can be tweaked without touching the original",
        json_schema_extra={
            "ui:hidden": True,
            "const": "duplicate_filter_view",
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Duplicate Filter View",
            "x-keywords": ["copy filter view", "clone a saved filter", "duplicate a view"],
        },
    )
    view_title: str = Field(..., title="View Name", description="Name of the view to copy")


class GoogleSheetsDeleteFilterViewConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing a filter view"""

    operation: Literal["delete_filter_view"] = Field(
        "delete_filter_view",
        title="Delete Filter View",
        description="Remove a saved filter view",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_filter_view",
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Delete Filter View",
            "x-keywords": ["remove filter view", "delete a saved filter", "get rid of a view"],
        },
    )
    view_title: str = Field(..., title="View Name", description="Name of the view to remove")


class GoogleSheetsAddDimensionGroupConfig(GoogleSheetsSheetTargetBase):
    """Configuration for grouping rows or columns"""

    operation: Literal["group_rows_or_columns"] = Field(
        "group_rows_or_columns",
        title="Group Rows Or Columns",
        description="Make a block of rows or columns collapsible",
        json_schema_extra={
            "ui:hidden": True,
            "const": "group_rows_or_columns",
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Group Rows Or Columns",
            "x-keywords": [
                "group rows", "group columns", "collapsible rows",
                "outline rows", "fold away columns",
            ],
        },
    )
    dimension: Literal["ROWS", "COLUMNS"] = Field(
        "ROWS", title="Group", description="Whether to group rows or columns"
    )
    start_index: int = Field(
        ..., title="From", description="First row/column in the group (1 = A / row 1)", ge=1
    )
    end_index: int = Field(..., title="To", description="Last row/column, inclusive", ge=1)


class GoogleSheetsUpdateDimensionGroupConfig(GoogleSheetsSheetTargetBase):
    """Configuration for collapsing or expanding a group"""

    operation: Literal["collapse_group"] = Field(
        "collapse_group",
        title="Collapse Or Expand Group",
        description="Fold a group of rows or columns away, or open it back up",
        json_schema_extra={
            "ui:hidden": True,
            "const": "collapse_group",
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Collapse Or Expand Group",
            "x-keywords": ["collapse a group", "expand a group", "fold rows away", "unfold columns"],
        },
    )
    dimension: Literal["ROWS", "COLUMNS"] = Field(
        "ROWS", title="Group", description="Whether the group covers rows or columns"
    )
    start_index: int = Field(..., title="From", description="First row/column in the group", ge=1)
    end_index: int = Field(..., title="To", description="Last row/column, inclusive", ge=1)
    depth: int = Field(1, title="Depth", description="Nesting depth of the group", ge=0)
    collapsed: Literal["true", "false"] = Field(
        "true", title="Collapsed", description="Yes folds the group away; No opens it"
    )


class GoogleSheetsDeleteDimensionGroupConfig(GoogleSheetsSheetTargetBase):
    """Configuration for ungrouping rows or columns"""

    operation: Literal["ungroup_rows_or_columns"] = Field(
        "ungroup_rows_or_columns",
        title="Ungroup Rows Or Columns",
        description="Remove a collapsible group, leaving the rows or columns in place",
        json_schema_extra={
            "ui:hidden": True,
            "const": "ungroup_rows_or_columns",
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Ungroup Rows Or Columns",
            "x-keywords": ["ungroup rows", "remove grouping", "delete an outline group"],
        },
    )
    dimension: Literal["ROWS", "COLUMNS"] = Field(
        "ROWS", title="Group", description="Whether the group covers rows or columns"
    )
    start_index: int = Field(..., title="From", description="First row/column in the group", ge=1)
    end_index: int = Field(..., title="To", description="Last row/column, inclusive", ge=1)


class GoogleSheetsAddSlicerConfig(GoogleSheetsSheetTargetBase):
    """Configuration for adding a slicer control"""

    operation: Literal["add_slicer"] = Field(
        "add_slicer",
        title="Add Slicer",
        description="Place an interactive filter control on the sheet",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_slicer",
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Add Slicer",
            "x-keywords": [
                "add a slicer", "interactive filter", "filter control",
                "dashboard filter", "clickable filter",
            ],
        },
    )
    range: str = Field(
        ..., title="Data Range", description="Range the slicer filters, including headers",
        json_schema_extra={"ui:placeholder": "A1:X13"},
    )
    filter_column: str = Field(
        ..., title="Filter On Column", description="Column letter the slicer filters by",
        json_schema_extra={"ui:placeholder": "R"},
    )
    anchor_cell: str = Field(
        ..., title="Place At", description="Top-left cell to anchor the slicer",
        json_schema_extra={"ui:placeholder": "Z2"},
    )
    slicer_title: Optional[str] = Field(None, title="Title", description="Label shown on the slicer")
    background_color: Optional[str] = Field(
        None, title="Background Colour", description="Hex fill for the slicer",
        json_schema_extra={"ui:placeholder": "#E3F0EB"},
    )


class GoogleSheetsUpdateSlicerConfig(GoogleSheetsSheetTargetBase):
    """Configuration for changing a slicer"""

    operation: Literal["update_slicer"] = Field(
        "update_slicer",
        title="Update Slicer",
        description="Retitle a slicer or point it at a different column",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_slicer",
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Update Slicer",
            "x-keywords": ["edit a slicer", "retitle a slicer", "change slicer column"],
        },
    )
    slicer_title: str = Field(
        ..., title="Slicer", description="Title of the slicer to change — this is how it is identified"
    )
    new_title: Optional[str] = Field(None, title="New Title", description="Retitle the slicer")
    filter_column: Optional[str] = Field(
        None, title="Filter On Column", description="Point it at this column letter instead"
    )
    background_color: Optional[str] = Field(
        None, title="Background Colour", description="Hex fill for the slicer"
    )


# ============================================================================
# Coverage phase 5 — developer metadata and connected data sources.
#
# Developer metadata is the API's way to tag a sheet, row or column with a
# key/value that survives edits and reordering — the durable alternative to
# "the status column is column R", which stops being true the moment someone
# inserts a column.
#
# The comment requests (insertComment, addCommentReply, updateCommentPost,
# deleteComment, deleteCommentReply) are deliberately NOT implemented: they
# are gated behind the Google Workspace Developer Preview Program and their
# CommentThread/Post payloads are not publicly documented, so any shape here
# would be a guess at an operation nobody outside the preview can call.
# ============================================================================


class GoogleSheetsCreateMetadataConfig(GoogleSheetsSheetTargetBase):
    """Configuration for tagging a sheet, row or column with durable metadata"""

    operation: Literal["create_developer_metadata"] = Field(
        "create_developer_metadata",
        title="Add Developer Metadata",
        description="Tag a sheet, row or column with a key/value that survives edits and reordering",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_developer_metadata",
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Add Developer Metadata",
            "x-keywords": [
                "developer metadata", "tag a column", "label a row durably",
                "attach metadata", "stable column reference",
            ],
        },
    )
    metadata_key: str = Field(
        ..., title="Key", description="Name of the tag",
        json_schema_extra={"ui:placeholder": "status_column"},
    )
    metadata_value: Optional[str] = Field(
        None, title="Value", description="Value stored against the key"
    )
    attach_to: Literal["SPREADSHEET", "SHEET", "ROW", "COLUMN"] = Field(
        "SHEET", title="Attach To", description="What the metadata is anchored to"
    )
    start_index: Optional[int] = Field(
        None,
        title="From",
        description="First row/column to tag (1 = A / row 1). Required for ROW or COLUMN.",
        ge=1,
    )
    end_index: Optional[int] = Field(
        None, title="To", description="Last row/column, inclusive. Defaults to the same as From.", ge=1
    )
    visibility: Literal["DOCUMENT", "PROJECT"] = Field(
        "DOCUMENT",
        title="Visibility",
        description="DOCUMENT is readable by anyone with the file; PROJECT only by this app",
    )


class GoogleSheetsUpdateMetadataConfig(GoogleSheetsSheetTargetBase):
    """Configuration for changing developer metadata"""

    operation: Literal["update_developer_metadata"] = Field(
        "update_developer_metadata",
        title="Update Developer Metadata",
        description="Change the value stored against a metadata key",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_developer_metadata",
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Update Developer Metadata",
            "x-keywords": ["change developer metadata", "edit a metadata tag", "update metadata value"],
        },
    )
    metadata_key: str = Field(..., title="Key", description="Key of the metadata to change")
    metadata_value: str = Field(..., title="New Value", description="New value to store")


class GoogleSheetsDeleteMetadataConfig(GoogleSheetsSheetTargetBase):
    """Configuration for removing developer metadata"""

    operation: Literal["delete_developer_metadata"] = Field(
        "delete_developer_metadata",
        title="Delete Developer Metadata",
        description="Remove every metadata entry stored under a key",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_developer_metadata",
            "x-category": "Metadata",
            "x-is-trigger": False,
            "x-display-name": "Delete Developer Metadata",
            "x-keywords": ["remove developer metadata", "delete a metadata tag", "untag a column"],
        },
    )
    metadata_key: str = Field(..., title="Key", description="Key of the metadata to remove")


class GoogleSheetsAddDataSourceConfig(BaseModel):
    """Configuration for connecting a BigQuery data source"""

    operation: Literal["add_data_source"] = Field(
        "add_data_source",
        title="Connect BigQuery Data Source",
        description="Attach a BigQuery table or query to the spreadsheet as a connected data source",
        json_schema_extra={
            "ui:hidden": True,
            "const": "add_data_source",
            "x-category": "Data Source",
            "x-is-trigger": False,
            "x-display-name": "Connect BigQuery Data Source",
            "x-keywords": [
                "connected sheets", "bigquery", "connect a data source",
                "attach a warehouse table", "query bigquery from sheets",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    project_id: str = Field(
        ..., title="BigQuery Project", description="Google Cloud project billed for the query",
        json_schema_extra={"ui:placeholder": "my-gcp-project"},
    )
    source_type: Literal["table", "query"] = Field(
        "table", title="Source", description="Attach a whole table, or the result of a query"
    )
    dataset_id: Optional[str] = Field(
        None, title="Dataset", description="BigQuery dataset. Required when attaching a table.",
        json_schema_extra={"ui:placeholder": "analytics"},
    )
    table_id: Optional[str] = Field(
        None, title="Table", description="BigQuery table. Required when attaching a table.",
        json_schema_extra={"ui:placeholder": "events"},
    )
    table_project_id: Optional[str] = Field(
        None,
        title="Table Project",
        description="Project the table lives in, if different from the billing project",
    )
    query: Optional[str] = Field(
        None,
        title="Query",
        description="SQL to run. Required when attaching a query.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "sql", "ui:rows": 6},
    )


class GoogleSheetsUpdateDataSourceConfig(BaseModel):
    """Configuration for repointing a data source"""

    operation: Literal["repoint_data_source"] = Field(
        "repoint_data_source",
        title="Repoint Data Source",
        description="Repoint a connected data source at a different table or query",
        json_schema_extra={
            "ui:hidden": True,
            "const": "repoint_data_source",
            "x-category": "Data Source",
            "x-is-trigger": False,
            "x-display-name": "Repoint Data Source",
            "x-keywords": ["change data source", "repoint bigquery", "edit connected sheet query"],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    data_source_id: str = Field(
        ..., title="Data Source ID", description="ID of the data source to change"
    )
    project_id: str = Field(..., title="BigQuery Project", description="Google Cloud project")
    source_type: Literal["table", "query"] = Field(
        "table", title="Source", description="Attach a whole table, or the result of a query"
    )
    dataset_id: Optional[str] = Field(None, title="Dataset", description="BigQuery dataset")
    table_id: Optional[str] = Field(None, title="Table", description="BigQuery table")
    table_project_id: Optional[str] = Field(None, title="Table Project", description="Project the table lives in")
    query: Optional[str] = Field(
        None, title="Query", description="SQL to run",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "sql", "ui:rows": 6},
    )


class GoogleSheetsDeleteDataSourceConfig(BaseModel):
    """Configuration for disconnecting a data source"""

    operation: Literal["delete_data_source"] = Field(
        "delete_data_source",
        title="Delete Data Source",
        description="Disconnect a data source and remove the sheets it backs",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_data_source",
            "x-category": "Data Source",
            "x-is-trigger": False,
            "x-display-name": "Delete Data Source",
            "x-keywords": ["disconnect data source", "remove bigquery connection", "delete connected sheet"],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    data_source_id: str = Field(
        ..., title="Data Source ID", description="ID of the data source to disconnect"
    )


class GoogleSheetsRefreshDataSourceConfig(BaseModel):
    """Configuration for refreshing connected data"""

    operation: Literal["refresh_data_source"] = Field(
        "refresh_data_source",
        title="Refresh Data Source",
        description="Re-run a connected data source so its sheets pick up new rows",
        json_schema_extra={
            "ui:hidden": True,
            "const": "refresh_data_source",
            "x-category": "Data Source",
            "x-is-trigger": False,
            "x-display-name": "Refresh Data Source",
            "x-keywords": [
                "refresh connected data", "re-run bigquery", "update connected sheet",
                "pull latest warehouse data",
            ],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    data_source_id: Optional[str] = Field(
        None,
        title="Data Source ID",
        description="Which data source to refresh. Leave empty to refresh all of them.",
    )
    force: Optional[Literal["true", "false"]] = Field(
        "false",
        title="Force",
        description="Refresh even if the data source is already running a refresh",
    )


class GoogleSheetsCancelRefreshConfig(BaseModel):
    """Configuration for cancelling a running refresh"""

    operation: Literal["cancel_data_source_refresh"] = Field(
        "cancel_data_source_refresh",
        title="Cancel Data Source Refresh",
        description="Stop a refresh that is currently running",
        json_schema_extra={
            "ui:hidden": True,
            "const": "cancel_data_source_refresh",
            "x-category": "Data Source",
            "x-is-trigger": False,
            "x-display-name": "Cancel Data Source Refresh",
            "x-keywords": ["cancel a refresh", "stop bigquery refresh", "abort connected data refresh"],
        },
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="Select a Google Sheet",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    data_source_id: Optional[str] = Field(
        None,
        title="Data Source ID",
        description="Which refresh to cancel. Leave empty to cancel all of them.",
    )


class GoogleSheetsOnNewRowConfig(PollTriggerConfigBase):
    """Trigger: polls a sheet on a schedule and fires for newly added rows."""

    operation: Literal["on_new_row"] = Field(
        "on_new_row",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Row",
            "x-keywords": [
                "row added",
                "when row added",
                "watch rows",
                "new row added",
                "monitor rows",
                "on row created",
                "row created trigger",
            ],
        },
        title="On New Row",
    )
    spreadsheet_id: str = Field(
        ...,
        title="Spreadsheet",
        description="The spreadsheet to watch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "spreadsheet_id",
                "placeholder": "Select a spreadsheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a spreadsheet ID",
            },
            "x-resource-type": "google_spreadsheet",
        },
    )
    sheet_name: Optional[str] = Field(
        None,
        title="Sheet",
        description="Tab to watch (leave blank for the first sheet)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "sheet_name",
                "placeholder": "Select a sheet...",
                "depends_on": "spreadsheet_id",
                "auto_select_first": True,
            },
            "x-resource-type": "google_sheet_tab",
        },
    )


# Discriminated union uses 'operation' field to determine which config type to parse
GoogleSheetsConfig = Annotated[
    Union[
        GoogleSheetsOnNewRowConfig,
        GoogleSheetsReadConfig,
        GoogleSheetsWriteConfig,
        GoogleSheetsAppendConfig,
        GoogleSheetsClearConfig,
        GoogleSheetsCreateConfig,
        GoogleSheetsGetMetadataConfig,
        GoogleSheetsBatchGetConfig,
        GoogleSheetsBatchUpdateConfig,
        GoogleSheetsAddSheetConfig,
        GoogleSheetsDeleteSheetConfig,
        GoogleSheetsCopySheetConfig,
        GoogleSheetsRenameSheetConfig,
        GoogleSheetsDuplicateSheetConfig,
        GoogleSheetsFindReplaceConfig,
        GoogleSheetsInsertRowsConfig,
        GoogleSheetsDeleteRowsConfig,
        GoogleSheetsBatchClearConfig,
        GoogleSheetsInsertColumnsConfig,
        GoogleSheetsDeleteColumnsConfig,
        GoogleSheetsFormatCellsConfig,
        GoogleSheetsUpdateSheetPropertiesConfig,
        GoogleSheetsAutoResizeConfig,
        GoogleSheetsSetDimensionSizeConfig,
        GoogleSheetsMergeCellsConfig,
        GoogleSheetsUnmergeCellsConfig,
        GoogleSheetsUpdateBordersConfig,
        GoogleSheetsAddBandingConfig,
        GoogleSheetsSetBasicFilterConfig,
        GoogleSheetsClearBasicFilterConfig,
        GoogleSheetsConditionalFormatConfig,
        GoogleSheetsSortRangeConfig,
        GoogleSheetsSetDataValidationConfig,
        GoogleSheetsClearDataValidationConfig,
        GoogleSheetsDeleteConditionalFormatConfig,
        GoogleSheetsClearBandingConfig,
        GoogleSheetsAddTableConfig,
        GoogleSheetsDeleteTableConfig,
        GoogleSheetsUpdateConditionalFormatConfig,
        GoogleSheetsUpdateBandingConfig,
        GoogleSheetsUpdateTableConfig,
        GoogleSheetsUpdateSpreadsheetPropertiesConfig,
        GoogleSheetsAddNamedRangeConfig,
        GoogleSheetsUpdateNamedRangeConfig,
        GoogleSheetsDeleteNamedRangeConfig,
        GoogleSheetsAddProtectedRangeConfig,
        GoogleSheetsUpdateProtectedRangeConfig,
        GoogleSheetsDeleteProtectedRangeConfig,
        GoogleSheetsSetNotesConfig,
        GoogleSheetsSmartChipsConfig,
        GoogleSheetsPivotTableConfig,
        GoogleSheetsCopyPasteConfig,
        GoogleSheetsCutPasteConfig,
        GoogleSheetsPasteDataConfig,
        GoogleSheetsAutoFillConfig,
        GoogleSheetsTextToColumnsConfig,
        GoogleSheetsTrimWhitespaceConfig,
        GoogleSheetsDeleteDuplicatesConfig,
        GoogleSheetsRandomizeRangeConfig,
        GoogleSheetsInsertRangeConfig,
        GoogleSheetsDeleteRangeConfig,
        GoogleSheetsMoveDimensionConfig,
        GoogleSheetsAppendDimensionConfig,
        GoogleSheetsAddChartConfig,
        GoogleSheetsUpdateChartConfig,
        GoogleSheetsMoveChartConfig,
        GoogleSheetsChartBorderConfig,
        GoogleSheetsDeleteChartConfig,
        GoogleSheetsAppendCellsConfig,
        GoogleSheetsAddFilterViewConfig,
        GoogleSheetsUpdateFilterViewConfig,
        GoogleSheetsDuplicateFilterViewConfig,
        GoogleSheetsDeleteFilterViewConfig,
        GoogleSheetsAddDimensionGroupConfig,
        GoogleSheetsUpdateDimensionGroupConfig,
        GoogleSheetsDeleteDimensionGroupConfig,
        GoogleSheetsAddSlicerConfig,
        GoogleSheetsUpdateSlicerConfig,
        GoogleSheetsCreateMetadataConfig,
        GoogleSheetsUpdateMetadataConfig,
        GoogleSheetsDeleteMetadataConfig,
        GoogleSheetsAddDataSourceConfig,
        GoogleSheetsUpdateDataSourceConfig,
        GoogleSheetsDeleteDataSourceConfig,
        GoogleSheetsRefreshDataSourceConfig,
        GoogleSheetsCancelRefreshConfig,
    ],
    Discriminator("operation"),
]


class GoogleSheetsNodeConfig(
    NodeConfig[GoogleSheetsConfig, GoogleSheetsOAuthCredential]
):
    """Full configuration for Google Sheets node including credentials"""

    pass


# ============================================================================
# Google Sheets Node Implementation
# ============================================================================

GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


class GoogleSheetsNode(ScheduledPollTriggerMixin, WorkflowNode):
    """
    Google Sheets workflow node for reading and writing spreadsheet data.
    """

    edit_examples = [
        "Read data from the Q2 Sales sheet and filter for values over 1000",
        "Append a new row with timestamp and status to the transactions sheet",
        "Update the Reports sheet with pivot data from analytics",
        "Clear completed tasks from the checklist and archive to backup sheet",
        "Batch update pricing data across 5 different product sheets",
        'Find and replace all instances of "pending" with "active" in Orders',
        "Insert 10 new rows in the inventory sheet with auto-incrementing IDs",
    ]

    scope_registry = GOOGLE_SHEETS_SCOPES
    connection_evidence = ConnectionEvidence(
        field="spreadsheet_id",
        noun="spreadsheets",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Google Sheets node"""
        return GoogleSheetsNodeConfig

    async def _trigger_on_new_row(self, config, credentials) -> Dict[str, Any]:
        """Poll the sheet and emit rows added since the last poll."""

        cred_dict = credentials.model_dump()
        credential_id = (self.node_data or {}).get("credential_id")
        access_token = await ensure_fresh_google_token(
            None, credential_id, self.user_id, cred_dict
        )
        values = await sheets_read_values(
            access_token, config.spreadsheet_id, config.sheet_name
        )
        header = values[0] if values else []
        rows = [
            {
                "row_number": i + 1,
                "values": row,
                "row": dict(zip(header, row)),
            }
            for i, row in enumerate(values)
            if i > 0
        ]
        new_rows = await self._filter_unseen(rows, lambda r: str(r["row_number"]))
        return {
            "rows": new_rows,
            "new_row_count": len(new_rows),
            "headers": header,
        }

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Load dynamic options for a field with pagination support.

        This is called by the workflow handler when the frontend needs
        to populate dropdowns (e.g., list of spreadsheets).

        Args:
            field_name: Name of the field needing options (e.g., "spreadsheet_id")
            credential_data: Decrypted OAuth credential data
            context: Additional context (e.g., currently selected spreadsheet)
            page_token: Optional token for pagination (for spreadsheet_id field)
            search: Optional search term to filter options

        Returns:
            Dict with 'options' (list of option dicts) and 'next_page_token' (optional)
        """
        logger.info(
            f"[GoogleSheetsNode] load_field_options called: field={field_name}, page_token={page_token}, search={search}"
        )
        if field_name == "spreadsheet_id":
            return await cls._list_spreadsheets(
                credential_data, page_token, search=search
            )
        elif field_name == "sheet_name":
            spreadsheet_id = (context or {}).get("spreadsheet_id")
            logger.info(
                f"[GoogleSheetsNode] load_field_options for sheet_name, context={context}, spreadsheet_id={spreadsheet_id}"
            )
            if spreadsheet_id:
                options = await cls._list_worksheets(
                    credential_data, spreadsheet_id, search=search
                )
                return {"options": options, "next_page_token": None}
            else:
                logger.warning(
                    f"[GoogleSheetsNode] No spreadsheet_id in context for sheet_name field"
                )
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_spreadsheets(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all Google Sheets accessible to the user with pagination support.

        Uses Drive API with mime type filter to find spreadsheets.

        Returns:
            Dict with 'options' (list of spreadsheet options) and 'next_page_token'
        """
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google account to load spreadsheets",
        )

        q = "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
        if search:
            # Escape single quotes for Drive API q syntax
            escaped = search.replace("\\", "\\\\").replace("'", "\\'")
            q += f" and name contains '{escaped}'"

        url = f"{GOOGLE_DRIVE_API_BASE}/files"
        params = {
            "q": q,
            "fields": "nextPageToken,files(id,name,modifiedTime,owners)",
            "orderBy": "modifiedTime desc",
            "pageSize": 100,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code != 200:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Google Drive API error: {error_msg}")

                data = response.json()
                files = data.get("files", [])
                next_page_token = data.get("nextPageToken")

                options = []
                for file in files:
                    options.append(
                        {
                            "value": file["id"],
                            "label": file["name"],
                            "metadata": {
                                "modifiedTime": file.get("modifiedTime"),
                                "owners": [
                                    o.get("displayName", o.get("emailAddress", ""))
                                    for o in file.get("owners", [])
                                ],
                            },
                        }
                    )

                logger.info(
                    f"[GoogleSheetsNode] Found {len(options)} spreadsheets, next_page_token={next_page_token is not None}"
                )
                return {"options": options, "next_page_token": next_page_token}

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[GoogleSheetsNode] Error listing spreadsheets: {e}")
            raise ValueError(f"Failed to load Google Sheets options: {e}") from e

    @classmethod
    async def _list_worksheets(
        cls,
        credential_data: Dict[str, Any],
        spreadsheet_id: str,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List all worksheets (tabs) in a specific spreadsheet.
        """
        logger.info(
            f"[GoogleSheetsNode] _list_worksheets called for spreadsheet_id={spreadsheet_id}"
        )

        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google account to load sheets",
        )

        # Check and refresh token if needed
        url = f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}"
        params = {"fields": "sheets.properties"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code != 200:
                    raise ValueError(
                        f"Google Sheets API error: status={response.status_code}, body={response.text[:500]}"
                    )

                data = response.json()
                sheets = data.get("sheets", [])
                logger.info(f"[GoogleSheetsNode] Got {len(sheets)} sheets from API")

                options = []
                for sheet in sheets:
                    props = sheet.get("properties", {})
                    options.append(
                        {
                            "value": props.get("title", ""),
                            "label": props.get("title", ""),
                            "metadata": {
                                "sheetId": props.get("sheetId"),
                                "index": props.get("index"),
                            },
                        }
                    )

                logger.info(
                    f"[GoogleSheetsNode] Returning {len(options)} worksheet options"
                )
                return options

        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"[GoogleSheetsNode] Error listing worksheets: {e}", exc_info=True
            )
            raise ValueError(
                f"Failed to load Google Sheets worksheet options: {e}"
            ) from e

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Google Sheets operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict containing Google Sheets operation results
        """
        logger.info(f"[GoogleSheetsNode] Executing node {self.node_id}")

        # Get config - required for this node
        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[GoogleSheetsNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, GoogleSheetsNodeConfig):
            raise ValueError(
                f"[GoogleSheetsNode] Invalid config type: {type(node_config)}, expected GoogleSheetsNodeConfig"
            )

        # Extract the actual config and credentials
        config = node_config.config
        credentials = node_config.credentials

        # Validate credentials are provided
        if not credentials:
            raise ValueError(
                f"[GoogleSheetsNode] Google Sheets credentials are required but not provided. "
                f"Please connect a Google account in the node's credentials tab."
            )

        # Trigger operation — poll the sheet for newly added rows
        if isinstance(config, GoogleSheetsOnNewRowConfig):
            return await self._trigger_on_new_row(config, credentials)

        # Ensure token is fresh before making API calls
        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        if isinstance(config, GoogleSheetsReadConfig):
            output = await self._read_sheet(config, access_token)
        elif isinstance(config, GoogleSheetsWriteConfig):
            output = await self._write_sheet(config, access_token, inputs)
        elif isinstance(config, GoogleSheetsAppendConfig):
            output = await self._append_sheet(config, access_token, inputs)
        elif isinstance(config, GoogleSheetsClearConfig):
            output = await self._clear_range(config, access_token)
        elif isinstance(config, GoogleSheetsCreateConfig):
            output = await self._create_spreadsheet(config, access_token)
        elif isinstance(config, GoogleSheetsGetMetadataConfig):
            output = await self._get_metadata(config, access_token)
        elif isinstance(config, GoogleSheetsBatchGetConfig):
            output = await self._batch_get(config, access_token)
        elif isinstance(config, GoogleSheetsBatchUpdateConfig):
            output = await self._batch_update(config, access_token, inputs)
        elif isinstance(config, GoogleSheetsAddSheetConfig):
            output = await self._add_sheet(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteSheetConfig):
            output = await self._delete_sheet(config, access_token)
        elif isinstance(config, GoogleSheetsCopySheetConfig):
            output = await self._copy_sheet(config, access_token)
        elif isinstance(config, GoogleSheetsRenameSheetConfig):
            output = await self._rename_sheet(config, access_token)
        elif isinstance(config, GoogleSheetsDuplicateSheetConfig):
            output = await self._duplicate_sheet(config, access_token)
        elif isinstance(config, GoogleSheetsFindReplaceConfig):
            output = await self._find_replace(config, access_token)
        elif isinstance(config, GoogleSheetsInsertRowsConfig):
            output = await self._insert_rows(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteRowsConfig):
            output = await self._delete_rows(config, access_token)
        elif isinstance(config, GoogleSheetsBatchClearConfig):
            output = await self._batch_clear(config, access_token)
        elif isinstance(config, GoogleSheetsInsertColumnsConfig):
            output = await self._insert_columns(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteColumnsConfig):
            output = await self._delete_columns(config, access_token)
        elif isinstance(config, GoogleSheetsFormatCellsConfig):
            output = await self._format_cells(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateSheetPropertiesConfig):
            output = await self._update_sheet_properties(config, access_token)
        elif isinstance(config, GoogleSheetsAutoResizeConfig):
            output = await self._auto_resize_dimensions(config, access_token)
        elif isinstance(config, GoogleSheetsSetDimensionSizeConfig):
            output = await self._set_dimension_size(config, access_token)
        elif isinstance(config, GoogleSheetsMergeCellsConfig):
            output = await self._merge_cells(config, access_token)
        elif isinstance(config, GoogleSheetsUnmergeCellsConfig):
            output = await self._unmerge_cells(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateBordersConfig):
            output = await self._update_borders(config, access_token)
        elif isinstance(config, GoogleSheetsAddBandingConfig):
            output = await self._add_banding(config, access_token)
        elif isinstance(config, GoogleSheetsSetBasicFilterConfig):
            output = await self._set_basic_filter(config, access_token)
        elif isinstance(config, GoogleSheetsClearBasicFilterConfig):
            output = await self._clear_basic_filter(config, access_token)
        elif isinstance(config, GoogleSheetsConditionalFormatConfig):
            output = await self._add_conditional_format_rule(config, access_token)
        elif isinstance(config, GoogleSheetsSortRangeConfig):
            output = await self._sort_range(config, access_token)
        elif isinstance(config, GoogleSheetsSetDataValidationConfig):
            output = await self._set_data_validation(config, access_token)
        elif isinstance(config, GoogleSheetsClearDataValidationConfig):
            output = await self._clear_data_validation(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteConditionalFormatConfig):
            output = await self._delete_conditional_format_rules(config, access_token)
        elif isinstance(config, GoogleSheetsClearBandingConfig):
            output = await self._clear_banding(config, access_token)
        elif isinstance(config, GoogleSheetsAddTableConfig):
            output = await self._add_table(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteTableConfig):
            output = await self._delete_table(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateConditionalFormatConfig):
            output = await self._update_conditional_format_rule(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateBandingConfig):
            output = await self._update_banding(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateTableConfig):
            output = await self._update_table(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateSpreadsheetPropertiesConfig):
            output = await self._update_spreadsheet_properties(config, access_token)
        elif isinstance(config, GoogleSheetsAddNamedRangeConfig):
            output = await self._add_named_range(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateNamedRangeConfig):
            output = await self._update_named_range(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteNamedRangeConfig):
            output = await self._delete_named_range(config, access_token)
        elif isinstance(config, GoogleSheetsAddProtectedRangeConfig):
            output = await self._add_protected_range(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateProtectedRangeConfig):
            output = await self._update_protected_range(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteProtectedRangeConfig):
            output = await self._delete_protected_range(config, access_token)
        elif isinstance(config, GoogleSheetsSetNotesConfig):
            output = await self._set_cell_notes(config, access_token)
        elif isinstance(config, GoogleSheetsSmartChipsConfig):
            output = await self._insert_smart_chips(config, access_token)
        elif isinstance(config, GoogleSheetsPivotTableConfig):
            output = await self._insert_pivot_table(config, access_token)
        elif isinstance(config, GoogleSheetsCopyPasteConfig):
            output = await self._copy_paste_range(config, access_token)
        elif isinstance(config, GoogleSheetsCutPasteConfig):
            output = await self._cut_paste_range(config, access_token)
        elif isinstance(config, GoogleSheetsPasteDataConfig):
            output = await self._paste_data(config, access_token)
        elif isinstance(config, GoogleSheetsAutoFillConfig):
            output = await self._auto_fill(config, access_token)
        elif isinstance(config, GoogleSheetsTextToColumnsConfig):
            output = await self._split_text_to_columns(config, access_token)
        elif isinstance(config, GoogleSheetsTrimWhitespaceConfig):
            output = await self._trim_whitespace(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteDuplicatesConfig):
            output = await self._remove_duplicate_rows(config, access_token)
        elif isinstance(config, GoogleSheetsRandomizeRangeConfig):
            output = await self._randomize_range(config, access_token)
        elif isinstance(config, GoogleSheetsInsertRangeConfig):
            output = await self._insert_cells(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteRangeConfig):
            output = await self._delete_cells(config, access_token)
        elif isinstance(config, GoogleSheetsMoveDimensionConfig):
            output = await self._move_dimension(config, access_token)
        elif isinstance(config, GoogleSheetsAppendDimensionConfig):
            output = await self._append_dimension(config, access_token)
        elif isinstance(config, GoogleSheetsAddChartConfig):
            output = await self._add_chart(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateChartConfig):
            output = await self._update_chart(config, access_token)
        elif isinstance(config, GoogleSheetsMoveChartConfig):
            output = await self._move_chart(config, access_token)
        elif isinstance(config, GoogleSheetsChartBorderConfig):
            output = await self._set_chart_border(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteChartConfig):
            output = await self._delete_chart(config, access_token)
        elif isinstance(config, GoogleSheetsAppendCellsConfig):
            output = await self._append_cells(config, access_token)
        elif isinstance(config, GoogleSheetsAddFilterViewConfig):
            output = await self._add_filter_view(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateFilterViewConfig):
            output = await self._update_filter_view(config, access_token)
        elif isinstance(config, GoogleSheetsDuplicateFilterViewConfig):
            output = await self._duplicate_filter_view(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteFilterViewConfig):
            output = await self._delete_filter_view(config, access_token)
        elif isinstance(config, GoogleSheetsAddDimensionGroupConfig):
            output = await self._group_dimension(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateDimensionGroupConfig):
            output = await self._collapse_group(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteDimensionGroupConfig):
            output = await self._ungroup_dimension(config, access_token)
        elif isinstance(config, GoogleSheetsAddSlicerConfig):
            output = await self._add_slicer(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateSlicerConfig):
            output = await self._update_slicer(config, access_token)
        elif isinstance(config, GoogleSheetsCreateMetadataConfig):
            output = await self._create_developer_metadata(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateMetadataConfig):
            output = await self._update_developer_metadata(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteMetadataConfig):
            output = await self._delete_developer_metadata(config, access_token)
        elif isinstance(config, GoogleSheetsAddDataSourceConfig):
            output = await self._add_data_source(config, access_token)
        elif isinstance(config, GoogleSheetsUpdateDataSourceConfig):
            output = await self._update_data_source(config, access_token)
        elif isinstance(config, GoogleSheetsDeleteDataSourceConfig):
            output = await self._delete_data_source(config, access_token)
        elif isinstance(config, GoogleSheetsRefreshDataSourceConfig):
            output = await self._refresh_data_source(config, access_token)
        elif isinstance(config, GoogleSheetsCancelRefreshConfig):
            output = await self._cancel_data_source_refresh(config, access_token)
        else:
            raise ValueError(f"Unexpected config type: {type(config)}")

        # Emit output to frontend
        await self.emit(output)

        return output

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="google",
        )

    async def _ensure_fresh_token(
        self, credentials: GoogleSheetsOAuthCredential
    ) -> str:
        """
        Return a valid Google Sheets access token, refreshing + persisting if expired.

        Args:
            credentials: Current credential data

        Returns:
            Valid access token (refreshed if necessary)
        """
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token

        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="google",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    def _build_range(self, sheet_name: Optional[str], range_spec: Optional[str]) -> str:
        """
        Build A1 notation range from sheet_name and range components.

        Google Sheets API expects ranges in A1 notation:
        - "Sheet1!A1:D10" - specific range on specific sheet
        - "Sheet1" - entire sheet
        - "A1:D10" - range on first/active sheet

        Args:
            sheet_name: Name of the sheet/tab (e.g., "Sheet2")
            range_spec: Cell range specification (e.g., "A1:D10")

        Returns:
            Properly formatted A1 notation range string

        Examples:
            _build_range("Sheet2", "A1:D10") -> "Sheet2!A1:D10"
            _build_range("Sheet2", None) -> "Sheet2"
            _build_range(None, "A1:D10") -> "A1:D10"
            _build_range(None, None) -> "" (empty, will trigger fallback to first sheet)
        """
        # If range_spec already contains sheet name (e.g., "Sheet1!A1:D10"), use as-is
        if range_spec and "!" in range_spec:
            logger.info(
                f"[GoogleSheetsNode] Range already includes sheet name: {range_spec}"
            )
            return range_spec

        # Build range from components
        if sheet_name and range_spec:
            # Both sheet and range: "Sheet2!A1:D10"
            result = f"{sheet_name}!{range_spec}"
            logger.info(
                f"[GoogleSheetsNode] Built range from sheet_name + range: {result}"
            )
            return result
        elif sheet_name:
            # Only sheet: "Sheet2" (reads entire sheet)
            logger.info(f"[GoogleSheetsNode] Using entire sheet: {sheet_name}")
            return sheet_name
        elif range_spec:
            # Only range: "A1:D10" (uses first/active sheet)
            logger.info(
                f"[GoogleSheetsNode] Using range on default sheet: {range_spec}"
            )
            return range_spec
        else:
            # Neither provided: empty string (triggers fallback logic)
            logger.info(
                f"[GoogleSheetsNode] No sheet_name or range provided, will use fallback"
            )
            return ""

    async def _read_sheet(
        self, config: GoogleSheetsReadConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Read data from Google Sheet.

        Args:
            config: Read configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing read results
        """
        # Build the range from sheet_name and range components
        read_range = self._build_range(config.sheet_name, config.range)

        if not read_range:
            # No sheet_name or range specified - get the first sheet name and read all data
            logger.info(
                f"[GoogleSheetsNode] No sheet_name or range specified, fetching first sheet name"
            )
            async with httpx.AsyncClient() as client:
                metadata_url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}?fields=sheets.properties.title"
                metadata_response = await client.get(
                    metadata_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if metadata_response.status_code != 200:
                    error_data = metadata_response.json()
                    error_msg = error_data.get("error", {}).get(
                        "message", metadata_response.text
                    )
                    logger.error(
                        f"[GoogleSheetsNode] Failed to get sheet metadata: {error_msg}"
                    )
                    raise ValueError(f"Google Sheets API error: {error_msg}")

                metadata = metadata_response.json()
                sheets = metadata.get("sheets", [])
                if not sheets:
                    raise ValueError("Spreadsheet has no sheets")

                # Use the first sheet's name as the range (reads all data)
                first_sheet_name = (
                    sheets[0].get("properties", {}).get("title", "Sheet1")
                )
                read_range = first_sheet_name
                logger.info(f"[GoogleSheetsNode] Fallback to first sheet: {read_range}")

        logger.info(
            f"[GoogleSheetsNode] Reading from spreadsheet {config.spreadsheet_id}, range {read_range}"
        )

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}/values/{read_range}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleSheetsNode] Read failed: {error_msg}")
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            values = data.get("values", [])

            output = {
                "type": "google_sheets",
                "operation": "read_sheet_data",
                "spreadsheet_id": config.spreadsheet_id,
                "range": read_range,
                "row_count": len(values),
                "values": values,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleSheetsNode] Read {len(values)} rows from sheet")
            return output

    async def _write_sheet(
        self, config: GoogleSheetsWriteConfig, access_token: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Write data to Google Sheet.

        Args:
            config: Write configuration
            access_token: Valid OAuth access token
            inputs: Input data from upstream nodes

        Returns:
            Dict containing write results
        """
        # Build the range from sheet_name and range components
        write_range = self._build_range(config.sheet_name, config.range)

        logger.info(
            f"[GoogleSheetsNode] Writing to spreadsheet {config.spreadsheet_id}, range {write_range}"
        )

        # Parse values - could be JSON string or reference to input data
        values = self._parse_values(config.values, inputs)

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}/values/{write_range}"

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params={"valueInputOption": "USER_ENTERED"},
                json={"values": values},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleSheetsNode] Write failed: {error_msg}")
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()

            output = {
                "type": "google_sheets",
                "operation": "write_sheet_data",
                "spreadsheet_id": config.spreadsheet_id,
                "range": write_range,
                "updated_cells": data.get("updatedCells", 0),
                "updated_rows": data.get("updatedRows", 0),
                "timestamp": time.time(),
                "status": "success",
            }
            cell_warning = self._single_cell_warning(config.values, values)
            if cell_warning:
                logger.warning(f"[GoogleSheetsNode] {self.node_id}: {cell_warning}")
                output["warning"] = cell_warning

            logger.info(
                f"[GoogleSheetsNode] Wrote {data.get('updatedCells', 0)} cells to sheet"
            )
            return output

    async def _append_sheet(
        self,
        config: GoogleSheetsAppendConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Append rows to Google Sheet.

        Args:
            config: Append configuration
            access_token: Valid OAuth access token
            inputs: Input data from upstream nodes

        Returns:
            Dict containing append results
        """
        # Build the range from sheet_name and range components
        append_range = self._build_range(config.sheet_name, config.range)

        logger.info(
            f"[GoogleSheetsNode] Appending to spreadsheet {config.spreadsheet_id}, range {append_range}"
        )

        # Parse values
        values = self._parse_values(config.values, inputs)

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}/values/{append_range}:append"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params={
                    "valueInputOption": "USER_ENTERED",
                    "insertDataOption": "INSERT_ROWS",
                },
                json={"values": values},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleSheetsNode] Append failed: {error_msg}")
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            updates = data.get("updates", {})

            output = {
                "type": "google_sheets",
                "operation": "append_rows_to_sheet",
                "spreadsheet_id": config.spreadsheet_id,
                "range": append_range,
                "updated_range": updates.get("updatedRange", ""),
                "updated_rows": updates.get("updatedRows", 0),
                "updated_cells": updates.get("updatedCells", 0),
                "timestamp": time.time(),
                "status": "success",
            }
            cell_warning = self._single_cell_warning(config.values, values)
            if cell_warning:
                logger.warning(f"[GoogleSheetsNode] {self.node_id}: {cell_warning}")
                output["warning"] = cell_warning

            logger.info(
                f"[GoogleSheetsNode] Appended {updates.get('updatedRows', 0)} rows to sheet"
            )
            return output

    def _serialize_cell_value(self, value: Any) -> Any:
        """
        Serialize a value for Google Sheets cell.

        Google Sheets cells only accept primitive values (string, number, boolean, null).
        Nested objects and arrays must be converted to JSON strings.

        Args:
            value: Any value to serialize

        Returns:
            Primitive value suitable for Google Sheets cell
        """
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (dict, list)):
            # Convert complex types to JSON string
            try:
                return json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                return str(value)
        # Fallback for other types
        return str(value)

    def _convert_objects_to_2d(
        self, objects: List[Dict[str, Any]], include_header: bool = True
    ) -> List[List[Any]]:
        """
        Convert an array of objects (dicts) to a 2D array suitable for Google Sheets.

        Extracts keys from the first object as headers, then converts each object
        to a row of values in the same order. Nested objects/arrays are serialized
        to JSON strings since Google Sheets cells only accept primitives.

        Args:
            objects: List of dictionaries with consistent keys
            include_header: Whether to include header row (default True)

        Returns:
            2D array: [[header1, header2, ...], [val1, val2, ...], ...]
        """
        if not objects:
            return [[]]

        # Get headers from the first object's keys
        # Use the first object to determine column order
        first_obj = objects[0]
        if not isinstance(first_obj, dict):
            # Not actually objects, return as-is wrapped
            return [[self._serialize_cell_value(obj)] for obj in objects]

        headers = list(first_obj.keys())
        logger.info(
            f"[GoogleSheetsNode][_convert_objects_to_2d] Extracted headers: {headers}"
        )

        rows = []
        if include_header:
            rows.append(headers)

        # Convert each object to a row, serializing complex values to JSON
        for obj in objects:
            if isinstance(obj, dict):
                row = [self._serialize_cell_value(obj.get(h, "")) for h in headers]
            else:
                # If somehow not a dict, wrap as single value
                row = [self._serialize_cell_value(obj)]
            rows.append(row)

        logger.info(
            f"[GoogleSheetsNode][_convert_objects_to_2d] Converted {len(objects)} objects to {len(rows)} rows"
        )
        return rows

    def _parse_values(
        self, values_input: Any, inputs: Dict[str, Any]
    ) -> List[List[Any]]:
        """
        Parse values from configuration.

        The workflow handler resolves {{...}} references BEFORE this method is called,
        so values_input could be:
        - A resolved value (string, number, etc.) from a reference like {{iteration.item.field}}
        - A JSON string: [[\"A1\", \"B1\"], [\"A2\", \"B2\"]]
        - Already a list from input data
        - An array of objects: [{\"name\": \"Alice\"}, {\"name\": \"Bob\"}]

        For single values, auto-wraps into 2D array format required by Google Sheets API.
        For array of objects, auto-converts to 2D with headers from object keys.

        Args:
            values_input: Values from config (may be already resolved)
            inputs: Input data from upstream nodes

        Returns:
            Parsed list of rows (each row is a list of cell values)
        """
        # DIAGNOSTIC LOGGING FOR DEBUGGING
        logger.info(
            f"[GoogleSheetsNode][_parse_values] Received values_input type: {type(values_input)}"
        )
        if isinstance(values_input, str):
            logger.info(
                f"[GoogleSheetsNode][_parse_values] String length: {len(values_input)}"
            )
            logger.info(
                f"[GoogleSheetsNode][_parse_values] First 200 chars: {values_input[:200]}"
            )
        elif isinstance(values_input, list) and len(values_input) > 0:
            logger.info(
                f"[GoogleSheetsNode][_parse_values] List with {len(values_input)} items, first item type: {type(values_input[0])}"
            )

        # If already a list, check what kind
        if isinstance(values_input, list):
            if len(values_input) == 0:
                return [[]]

            first_item = values_input[0]

            # Already 2D list - use as-is
            if isinstance(first_item, list):
                return values_input

            # Array of objects (dicts) - convert to 2D with headers
            if isinstance(first_item, dict):
                logger.info(
                    f"[GoogleSheetsNode][_parse_values] Detected array of objects, auto-converting to 2D"
                )
                return self._convert_objects_to_2d(values_input)

            # 1D list of primitives - wrap each item as a row
            return [[item] for item in values_input]

        # If it's a string, try to parse as JSON
        if isinstance(values_input, str):
            values_str = values_input.strip()

            # Try to parse as JSON first
            try:
                values = json.loads(values_str)
                if isinstance(values, list):
                    if len(values) == 0:
                        return [[]]

                    first_item = values[0]

                    # Already 2D list
                    if isinstance(first_item, list):
                        return values

                    # Array of objects - convert to 2D with headers
                    if isinstance(first_item, dict):
                        logger.info(
                            f"[GoogleSheetsNode][_parse_values] Detected JSON array of objects, auto-converting to 2D"
                        )
                        return self._convert_objects_to_2d(values)

                    # 1D list of primitives
                    return [[item] for item in values]

                # Single value parsed from JSON - wrap it
                return [[values]]
            except json.JSONDecodeError:
                pass

            # Check for legacy input reference pattern (for backwards compatibility)
            if values_str.startswith("{{") and values_str.endswith("}}"):
                ref_path = values_str[2:-2].strip()
                parts = ref_path.split(".")

                if len(parts) >= 2 and parts[0] == "input":
                    node_id = parts[1]
                    field_path = parts[2:] if len(parts) > 2 else ["values"]

                    if node_id in inputs:
                        data = inputs[node_id]
                        for field in field_path:
                            if isinstance(data, dict) and field in data:
                                data = data[field]
                            else:
                                raise ValueError(f"Invalid reference path: {ref_path}")
                        return data if isinstance(data, list) else [[data]]

            # Plain string value (e.g., resolved from {{iteration.item.field}})
            # Wrap it in 2D array for Google Sheets API
            return [[values_str]]

        # Any other type (number, bool, etc.) - wrap it
        return [[values_input]]

    @staticmethod
    def _single_cell_warning(raw: Any, parsed: List[List[Any]]) -> Optional[str]:
        """A plain (non-JSON) string appends as ONE cell. When it carries an
        obvious column delimiter, that's almost always a malformed config.
        Non-blocking: surfaced as a
        `warning` on the node output."""
        if not isinstance(raw, str) or len(parsed) != 1 or len(parsed[0]) != 1:
            return None
        if "|" not in raw and "\t" not in raw:
            return None
        return (
            "values was a plain string containing a column delimiter — it was "
            "appended as a SINGLE cell. To write multiple columns/rows, pass a "
            'JSON array of rows, e.g. [["col1", "col2"]].'
        )

    async def _clear_range(
        self, config: GoogleSheetsClearConfig, access_token: str
    ) -> Dict[str, Any]:
        """Clear values from a range."""
        # Build the range from sheet_name and range components
        clear_range = self._build_range(config.sheet_name, config.range)

        logger.info(f"[GoogleSheetsNode] Clearing range {clear_range}")

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}/values/{clear_range}:clear"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            return {
                "type": "google_sheets",
                "operation": "clear_sheet_range",
                "spreadsheet_id": config.spreadsheet_id,
                "cleared_range": data.get("clearedRange", clear_range),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _create_spreadsheet(
        self, config: GoogleSheetsCreateConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new spreadsheet."""
        logger.info(f"[GoogleSheetsNode] Creating spreadsheet: {config.title}")

        sheets = []
        if config.sheet_titles:
            for title in config.sheet_titles.split(","):
                sheets.append({"properties": {"title": title.strip()}})
        else:
            sheets.append({"properties": {"title": "Sheet1"}})

        body = {"properties": {"title": config.title}, "sheets": sheets}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_SHEETS_API_BASE,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            sheet_names = [s["properties"]["title"] for s in data.get("sheets", [])]

            return {
                "type": "google_sheets",
                "operation": "create_new_spreadsheet",
                "spreadsheet_id": data.get("spreadsheetId"),
                "title": data.get("properties", {}).get("title"),
                "url": data.get("spreadsheetUrl"),
                "sheets": sheet_names,
                "timestamp": time.time(),
                "status": "success",
            }

    @staticmethod
    def _structure_summary(sheet: Dict[str, Any]) -> Dict[str, Any]:
        """Name-and-id view of a sheet's tables, charts and rules.

        Deliberately a summary, not the raw payload: a chart spec alone can run
        to hundreds of lines, and what a caller needs to act is which things
        exist and what to address them by.
        """
        return {
            "tables": [
                {"name": t.get("name"), "table_id": t.get("tableId")}
                for t in sheet.get("tables", []) or []
            ],
            "charts": [
                {
                    "chart_id": c.get("chartId"),
                    "title": c.get("spec", {}).get("title"),
                }
                for c in sheet.get("charts", []) or []
            ],
            "slicers": [
                {
                    "slicer_id": sl.get("slicerId"),
                    "title": sl.get("spec", {}).get("title"),
                }
                for sl in sheet.get("slicers", []) or []
            ],
            "filter_views": [
                {"title": f.get("title"), "filter_view_id": f.get("filterViewId")}
                for f in sheet.get("filterViews", []) or []
            ],
            "protected_ranges": [
                {
                    "description": pr.get("description"),
                    "protected_range_id": pr.get("protectedRangeId"),
                    "warning_only": pr.get("warningOnly", False),
                }
                for pr in sheet.get("protectedRanges", []) or []
            ],
            "banded_range_ids": [
                b.get("bandedRangeId") for b in sheet.get("bandedRanges", []) or []
            ],
            "conditional_format_count": len(sheet.get("conditionalFormats", []) or []),
        }

    async def _get_metadata(
        self, config: GoogleSheetsGetMetadataConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get spreadsheet metadata."""
        logger.info(f"[GoogleSheetsNode] Getting metadata for {config.spreadsheet_id}")

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}"
        deep = _is_true(config.include_structure)
        fields = "spreadsheetId,properties,sheets.properties,spreadsheetUrl"
        if deep:
            fields += (
                ",namedRanges,sheets(tables,charts,slicers,filterViews,"
                "protectedRanges,bandedRanges,conditionalFormats)"
            )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": fields},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            sheets_info = []
            for sheet in data.get("sheets", []):
                props = sheet.get("properties", {})
                entry = {
                    "sheetId": props.get("sheetId"),
                    "title": props.get("title"),
                    "index": props.get("index"),
                    "rowCount": props.get("gridProperties", {}).get("rowCount"),
                    "columnCount": props.get("gridProperties", {}).get("columnCount"),
                }
                if deep:
                    entry.update(self._structure_summary(sheet))
                sheets_info.append(entry)

            return {
                "type": "google_sheets",
                "operation": "fetch_spreadsheet_metadata",
                "spreadsheet_id": data.get("spreadsheetId"),
                "title": data.get("properties", {}).get("title"),
                "locale": data.get("properties", {}).get("locale"),
                "url": data.get("spreadsheetUrl"),
                "named_ranges": (
                    [
                        {"name": n.get("name"), "named_range_id": n.get("namedRangeId")}
                        for n in data.get("namedRanges", []) or []
                    ]
                    if deep
                    else None
                ),
                "sheets": sheets_info,
                "sheet_count": len(sheets_info),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _batch_get(
        self, config: GoogleSheetsBatchGetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Read multiple ranges at once."""
        logger.info(f"[GoogleSheetsNode] Batch getting ranges")

        ranges = [r.strip() for r in config.ranges.split(",")]
        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}/values:batchGet"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"ranges": ranges},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            value_ranges = []
            for vr in data.get("valueRanges", []):
                value_ranges.append(
                    {"range": vr.get("range"), "values": vr.get("values", [])}
                )

            return {
                "type": "google_sheets",
                "operation": "read_multiple_sheet_ranges",
                "spreadsheet_id": config.spreadsheet_id,
                "value_ranges": value_ranges,
                "range_count": len(value_ranges),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _batch_update(
        self,
        config: GoogleSheetsBatchUpdateConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Write to multiple ranges at once."""
        logger.info(f"[GoogleSheetsNode] Batch updating ranges")

        try:
            data_list = json.loads(config.data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON data: {e}")

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}/values:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"valueInputOption": "USER_ENTERED", "data": data_list},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            return {
                "type": "google_sheets",
                "operation": "write_to_multiple_sheet_ranges",
                "spreadsheet_id": config.spreadsheet_id,
                "total_updated_rows": data.get("totalUpdatedRows", 0),
                "total_updated_columns": data.get("totalUpdatedColumns", 0),
                "total_updated_cells": data.get("totalUpdatedCells", 0),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_sheet_id(
        self, spreadsheet_id: str, sheet_name: str, access_token: str
    ) -> int:
        """Helper to get sheet ID from sheet name."""
        url = f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "sheets.properties"},
            )
            if response.status_code != 200:
                raise ValueError(f"Failed to get sheet info")

            data = response.json()
            for sheet in data.get("sheets", []):
                if sheet.get("properties", {}).get("title") == sheet_name:
                    return sheet["properties"]["sheetId"]

            raise ValueError(f"Sheet '{sheet_name}' not found")

    async def _add_sheet(
        self, config: GoogleSheetsAddSheetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Add a new sheet/tab to spreadsheet."""
        logger.info(f"[GoogleSheetsNode] Adding sheet: {config.sheet_title}")

        request = {"addSheet": {"properties": {"title": config.sheet_title}}}
        if config.index is not None:
            request["addSheet"]["properties"]["index"] = config.index

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"requests": [request]},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            replies = data.get("replies", [{}])
            props = replies[0].get("addSheet", {}).get("properties", {})

            return {
                "type": "google_sheets",
                "operation": "add_spreadsheet_sheet",
                "spreadsheet_id": config.spreadsheet_id,
                "sheet_id": props.get("sheetId"),
                "sheet_title": props.get("title"),
                "index": props.get("index"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_sheet(
        self, config: GoogleSheetsDeleteSheetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a sheet/tab from spreadsheet."""
        logger.info(f"[GoogleSheetsNode] Deleting sheet: {config.sheet_name}")

        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            return {
                "type": "google_sheets",
                "operation": "delete_spreadsheet_sheet",
                "spreadsheet_id": config.spreadsheet_id,
                "deleted_sheet_name": config.sheet_name,
                "deleted_sheet_id": sheet_id,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _copy_sheet(
        self, config: GoogleSheetsCopySheetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Copy a sheet to another spreadsheet."""
        logger.info(f"[GoogleSheetsNode] Copying sheet to another spreadsheet")

        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )

        url = (
            f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}/sheets/{sheet_id}:copyTo"
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"destinationSpreadsheetId": config.destination_spreadsheet_id},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            return {
                "type": "google_sheets",
                "operation": "copy_sheet_to_spreadsheet",
                "source_spreadsheet_id": config.spreadsheet_id,
                "source_sheet_name": config.sheet_name,
                "destination_spreadsheet_id": config.destination_spreadsheet_id,
                "new_sheet_id": data.get("sheetId"),
                "new_sheet_title": data.get("title"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _rename_sheet(
        self, config: GoogleSheetsRenameSheetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Rename a sheet/tab."""
        logger.info(f"[GoogleSheetsNode] Renaming sheet to: {config.new_name}")

        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": sheet_id,
                                    "title": config.new_name,
                                },
                                "fields": "title",
                            }
                        }
                    ]
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            return {
                "type": "google_sheets",
                "operation": "rename_spreadsheet_sheet",
                "spreadsheet_id": config.spreadsheet_id,
                "old_name": config.sheet_name,
                "new_name": config.new_name,
                "sheet_id": sheet_id,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _duplicate_sheet(
        self, config: GoogleSheetsDuplicateSheetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Duplicate a sheet within the same spreadsheet."""
        logger.info(f"[GoogleSheetsNode] Duplicating sheet: {config.sheet_name}")

        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )

        request = {"duplicateSheet": {"sourceSheetId": sheet_id}}
        if config.new_name:
            request["duplicateSheet"]["newSheetName"] = config.new_name

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"requests": [request]},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            replies = data.get("replies", [{}])
            props = replies[0].get("duplicateSheet", {}).get("properties", {})

            return {
                "type": "google_sheets",
                "operation": "duplicate_sheet_in_spreadsheet",
                "spreadsheet_id": config.spreadsheet_id,
                "source_sheet_name": config.sheet_name,
                "new_sheet_id": props.get("sheetId"),
                "new_sheet_title": props.get("title"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _find_replace(
        self, config: GoogleSheetsFindReplaceConfig, access_token: str
    ) -> Dict[str, Any]:
        """Find and replace text in spreadsheet."""
        logger.info(
            f"[GoogleSheetsNode] Find/replace: '{config.find}' -> '{config.replacement}'"
        )

        request = {
            "findReplace": {
                "find": config.find,
                "replacement": config.replacement,
                "matchCase": config.match_case,
                "matchEntireCell": config.match_entire_cell,
                "allSheets": config.sheet_name is None,
            }
        }

        if config.sheet_name:
            sheet_id = await self._get_sheet_id(
                config.spreadsheet_id, config.sheet_name, access_token
            )
            request["findReplace"]["sheetId"] = sheet_id
            request["findReplace"]["allSheets"] = False

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"requests": [request]},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            replies = data.get("replies", [{}])
            result = replies[0].get("findReplace", {})

            return {
                "type": "google_sheets",
                "operation": "find_and_replace_in_spreadsheet",
                "spreadsheet_id": config.spreadsheet_id,
                "find": config.find,
                "replacement": config.replacement,
                "occurrences_changed": result.get("occurrencesChanged", 0),
                "values_changed": result.get("valuesChanged", 0),
                "rows_changed": result.get("rowsChanged", 0),
                "sheets_changed": result.get("sheetsChanged", 0),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _insert_rows(
        self, config: GoogleSheetsInsertRowsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Insert rows at a position."""
        logger.info(
            f"[GoogleSheetsNode] Inserting {config.num_rows} rows at row {config.start_row}"
        )

        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )

        # Convert 1-indexed to 0-indexed
        start_index = config.start_row - 1
        end_index = start_index + config.num_rows

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "ROWS",
                                    "startIndex": start_index,
                                    "endIndex": end_index,
                                },
                                "inheritFromBefore": start_index > 0,
                            }
                        }
                    ]
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            return {
                "type": "google_sheets",
                "operation": "insert_sheet_rows",
                "spreadsheet_id": config.spreadsheet_id,
                "sheet_name": config.sheet_name,
                "start_row": config.start_row,
                "num_rows": config.num_rows,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_rows(
        self, config: GoogleSheetsDeleteRowsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete rows from a sheet."""
        logger.info(
            f"[GoogleSheetsNode] Deleting rows {config.start_row} to {config.end_row}"
        )

        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )

        # Convert 1-indexed to 0-indexed
        start_index = config.start_row - 1
        end_index = config.end_row  # end is exclusive in API

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "requests": [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "ROWS",
                                    "startIndex": start_index,
                                    "endIndex": end_index,
                                }
                            }
                        }
                    ]
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            return {
                "type": "google_sheets",
                "operation": "delete_sheet_rows",
                "spreadsheet_id": config.spreadsheet_id,
                "sheet_name": config.sheet_name,
                "start_row": config.start_row,
                "end_row": config.end_row,
                "rows_deleted": config.end_row - config.start_row + 1,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _batch_clear(
        self, config: GoogleSheetsBatchClearConfig, access_token: str
    ) -> Dict[str, Any]:
        """Clear multiple ranges at once."""
        logger.info(f"[GoogleSheetsNode] Batch clearing {len(config.ranges)} ranges")

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}/values:batchClear"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"ranges": config.ranges},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            data = response.json()
            return {
                "type": "google_sheets",
                "operation": "clear_multiple_sheet_ranges",
                "spreadsheet_id": config.spreadsheet_id,
                "cleared_ranges": data.get("clearedRanges", []),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _insert_columns(
        self, config: GoogleSheetsInsertColumnsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Insert columns at a position."""
        logger.info(
            f"[GoogleSheetsNode] Inserting {config.num_columns} columns at column {config.start_column}"
        )

        # Get sheet ID from sheet name
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )

        # Convert 1-indexed to 0-indexed
        start_index = config.start_column - 1

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "COLUMNS",
                                    "startIndex": start_index,
                                    "endIndex": start_index + config.num_columns,
                                },
                                "inheritFromBefore": config.inherit_from_before,
                            }
                        }
                    ]
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            return {
                "type": "google_sheets",
                "operation": "insert_sheet_columns",
                "spreadsheet_id": config.spreadsheet_id,
                "sheet_name": config.sheet_name,
                "start_column": config.start_column,
                "num_columns": config.num_columns,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_columns(
        self, config: GoogleSheetsDeleteColumnsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete columns from a sheet."""
        logger.info(
            f"[GoogleSheetsNode] Deleting columns {config.start_column} to {config.end_column}"
        )

        # Get sheet ID from sheet name
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )

        # Convert 1-indexed to 0-indexed
        start_index = config.start_column - 1
        end_index = config.end_column  # end is exclusive in API

        url = f"{GOOGLE_SHEETS_API_BASE}/{config.spreadsheet_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "requests": [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "COLUMNS",
                                    "startIndex": start_index,
                                    "endIndex": end_index,
                                }
                            }
                        }
                    ]
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")

            return {
                "type": "google_sheets",
                "operation": "delete_sheet_columns",
                "spreadsheet_id": config.spreadsheet_id,
                "sheet_name": config.sheet_name,
                "start_column": config.start_column,
                "end_column": config.end_column,
                "columns_deleted": config.end_column - config.start_column + 1,
                "timestamp": time.time(),
                "status": "success",
            }

    # ------------------------------------------------------------------
    # Formatting operations
    #
    # All of these are spreadsheets.batchUpdate requests, so they share one
    # sender. Handlers only build the request list.
    # ------------------------------------------------------------------

    async def _send_batch_update(
        self, spreadsheet_id: str, requests: List[Dict[str, Any]], access_token: str
    ) -> Dict[str, Any]:
        """POST a batchUpdate request list and return the parsed response."""
        url = f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}:batchUpdate"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"requests": requests},
            )
            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")
            return response.json()

    async def _resolve_grid_range(
        self, spreadsheet_id: str, sheet_name: str, a1_range: Optional[str], access_token: str
    ) -> Dict[str, Any]:
        """Resolve a sheet name + A1 range into a GridRange."""
        sheet_id = await self._get_sheet_id(spreadsheet_id, sheet_name, access_token)
        return a1_range_to_grid_range(a1_range or "", sheet_id)

    async def _format_cells(
        self, config: GoogleSheetsFormatCellsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Apply font, colour, alignment and number formatting to a range."""
        logger.info(
            f"[GoogleSheetsNode] Formatting {config.sheet_name}!{config.range}"
        )
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )

        text_format: Dict[str, Any] = {}
        fields: List[str] = []
        for attr, api_key in (
            ("bold", "bold"),
            ("italic", "italic"),
            ("underline", "underline"),
            ("strikethrough", "strikethrough"),
        ):
            value = getattr(config, attr)
            if value is not None:
                text_format[api_key] = _is_true(value)
                fields.append(f"userEnteredFormat.textFormat.{api_key}")
        if config.font_size is not None:
            text_format["fontSize"] = config.font_size
            fields.append("userEnteredFormat.textFormat.fontSize")
        if config.font_family:
            text_format["fontFamily"] = config.font_family
            fields.append("userEnteredFormat.textFormat.fontFamily")
        text_color = hex_to_color(config.text_color)
        if text_color:
            text_format["foregroundColor"] = text_color
            fields.append("userEnteredFormat.textFormat.foregroundColor")

        cell_format: Dict[str, Any] = {}
        if text_format:
            cell_format["textFormat"] = text_format
        background = hex_to_color(config.background_color)
        if background:
            cell_format["backgroundColor"] = background
            fields.append("userEnteredFormat.backgroundColor")
        if config.horizontal_alignment:
            cell_format["horizontalAlignment"] = config.horizontal_alignment
            fields.append("userEnteredFormat.horizontalAlignment")
        if config.vertical_alignment:
            cell_format["verticalAlignment"] = config.vertical_alignment
            fields.append("userEnteredFormat.verticalAlignment")
        if config.wrap_strategy:
            cell_format["wrapStrategy"] = config.wrap_strategy
            fields.append("userEnteredFormat.wrapStrategy")
        if config.number_format_type:
            number_format: Dict[str, Any] = {"type": config.number_format_type}
            if config.number_format_pattern:
                number_format["pattern"] = config.number_format_pattern
            cell_format["numberFormat"] = number_format
            fields.append("userEnteredFormat.numberFormat")
        elif config.number_format_pattern:
            raise ValueError(
                "A number format pattern needs a number format type as well "
                "(for example type CURRENCY with pattern \"$#,##0.00\")."
            )

        if not fields:
            raise ValueError(
                "No formatting was specified. Set at least one option, such as Bold or Background Colour."
            )

        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "repeatCell": {
                        "range": grid_range,
                        "cell": {"userEnteredFormat": cell_format},
                        "fields": ",".join(fields),
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "format_cells",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "applied": fields,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _update_sheet_properties(
        self, config: GoogleSheetsUpdateSheetPropertiesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Freeze panes, colour the tab, toggle gridlines or hide the sheet."""
        logger.info(
            f"[GoogleSheetsNode] Updating sheet properties on {config.sheet_name}"
        )
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )

        properties: Dict[str, Any] = {"sheetId": sheet_id}
        fields: List[str] = []
        grid_properties: Dict[str, Any] = {}
        if config.frozen_row_count is not None:
            grid_properties["frozenRowCount"] = config.frozen_row_count
            fields.append("gridProperties.frozenRowCount")
        if config.frozen_column_count is not None:
            grid_properties["frozenColumnCount"] = config.frozen_column_count
            fields.append("gridProperties.frozenColumnCount")
        if config.hide_gridlines is not None:
            grid_properties["hideGridlines"] = _is_true(config.hide_gridlines)
            fields.append("gridProperties.hideGridlines")
        if grid_properties:
            properties["gridProperties"] = grid_properties
        tab_color = hex_to_color(config.tab_color)
        if tab_color:
            properties["tabColor"] = tab_color
            fields.append("tabColor")
        if config.hidden is not None:
            properties["hidden"] = _is_true(config.hidden)
            fields.append("hidden")

        if not fields:
            raise ValueError(
                "No sheet properties were specified. Set at least one option, such as Frozen Rows."
            )

        await self._send_batch_update(
            config.spreadsheet_id,
            [{"updateSheetProperties": {"properties": properties, "fields": ",".join(fields)}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "update_sheet_properties",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "sheet_id": sheet_id,
            "applied": fields,
            "timestamp": time.time(),
            "status": "success",
        }

    def _dimension_range(
        self, sheet_id: int, dimension: str, start_index: int, end_index: Optional[int]
    ) -> Dict[str, Any]:
        """Build a DimensionRange from 1-based, inclusive user input."""
        if end_index is not None and end_index < start_index:
            raise ValueError("The end column/row comes before the start.")
        dimension_range: Dict[str, Any] = {
            "sheetId": sheet_id,
            "dimension": dimension,
            "startIndex": start_index - 1,
        }
        if end_index is not None:
            dimension_range["endIndex"] = end_index
        return dimension_range

    async def _auto_resize_dimensions(
        self, config: GoogleSheetsAutoResizeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Resize columns or rows to fit their contents."""
        logger.info(
            f"[GoogleSheetsNode] Auto-resizing {config.dimension} on {config.sheet_name}"
        )
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "autoResizeDimensions": {
                        "dimensions": self._dimension_range(
                            sheet_id, config.dimension, config.start_index, config.end_index
                        )
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "auto_resize_dimensions",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "dimension": config.dimension,
            "start_index": config.start_index,
            "end_index": config.end_index,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _set_dimension_size(
        self, config: GoogleSheetsSetDimensionSizeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Set an exact column width or row height."""
        logger.info(
            f"[GoogleSheetsNode] Sizing {config.dimension} to {config.pixel_size}px"
        )
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "updateDimensionProperties": {
                        "range": self._dimension_range(
                            sheet_id, config.dimension, config.start_index, config.end_index
                        ),
                        "properties": {"pixelSize": config.pixel_size},
                        "fields": "pixelSize",
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "set_dimension_size",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "dimension": config.dimension,
            "pixel_size": config.pixel_size,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _merge_cells(
        self, config: GoogleSheetsMergeCellsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Merge a range into one cell."""
        logger.info(f"[GoogleSheetsNode] Merging {config.sheet_name}!{config.range}")
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"mergeCells": {"range": grid_range, "mergeType": config.merge_type}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "merge_cells",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "merge_type": config.merge_type,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _unmerge_cells(
        self, config: GoogleSheetsUnmergeCellsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Split merged cells in a range back apart."""
        logger.info(f"[GoogleSheetsNode] Unmerging {config.sheet_name}!{config.range}")
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"unmergeCells": {"range": grid_range}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "unmerge_cells",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _update_borders(
        self, config: GoogleSheetsUpdateBordersConfig, access_token: str
    ) -> Dict[str, Any]:
        """Draw or clear borders on a range."""
        logger.info(f"[GoogleSheetsNode] Bordering {config.sheet_name}!{config.range}")
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        border = {"style": config.border_style}
        border_color = hex_to_color(config.border_color)
        if border_color:
            border["color"] = border_color

        edges = {
            "ALL": ("top", "bottom", "left", "right", "innerHorizontal", "innerVertical"),
            "OUTER": ("top", "bottom", "left", "right"),
            "INNER": ("innerHorizontal", "innerVertical"),
            "BOTTOM": ("bottom",),
            "TOP": ("top",),
        }[config.apply_to]

        request: Dict[str, Any] = {"range": grid_range}
        for edge in edges:
            request[edge] = border

        await self._send_batch_update(
            config.spreadsheet_id, [{"updateBorders": request}], access_token
        )
        return {
            "type": "google_sheets",
            "operation": "format_borders",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "border_style": config.border_style,
            "apply_to": config.apply_to,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _add_banding(
        self, config: GoogleSheetsAddBandingConfig, access_token: str
    ) -> Dict[str, Any]:
        """Apply alternating row colours to a range."""
        logger.info(f"[GoogleSheetsNode] Banding {config.sheet_name}!{config.range}")
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        row_properties: Dict[str, Any] = {
            "firstBandColor": hex_to_color(config.first_band_color),
            "secondBandColor": hex_to_color(config.second_band_color),
        }
        header_color = hex_to_color(config.header_color)
        if header_color:
            row_properties["headerColor"] = header_color

        response = await self._send_batch_update(
            config.spreadsheet_id,
            [{"addBanding": {"bandedRange": {"range": grid_range, "rowProperties": row_properties}}}],
            access_token,
        )
        banded_range_id = (
            response.get("replies", [{}])[0]
            .get("addBanding", {})
            .get("bandedRange", {})
            .get("bandedRangeId")
        )
        return {
            "type": "google_sheets",
            "operation": "add_alternating_colors",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "banded_range_id": banded_range_id,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _set_basic_filter(
        self, config: GoogleSheetsSetBasicFilterConfig, access_token: str
    ) -> Dict[str, Any]:
        """Add sort/filter controls over a range."""
        logger.info(f"[GoogleSheetsNode] Setting filter on {config.sheet_name}")
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"setBasicFilter": {"filter": {"range": grid_range}}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "set_basic_filter",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _clear_basic_filter(
        self, config: GoogleSheetsClearBasicFilterConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove the sort/filter controls from a sheet."""
        logger.info(f"[GoogleSheetsNode] Clearing filter on {config.sheet_name}")
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"clearBasicFilter": {"sheetId": sheet_id}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "clear_basic_filter",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "sheet_id": sheet_id,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _add_conditional_format_rule(
        self, config: GoogleSheetsConditionalFormatConfig, access_token: str
    ) -> Dict[str, Any]:
        """Add a conditional formatting rule to a range."""
        logger.info(
            f"[GoogleSheetsNode] Adding conditional format to {config.sheet_name}!{config.range}"
        )
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )

        boolean_rule = self._boolean_rule(
            config.condition_type,
            config.value,
            config.value_max,
            config.background_color,
            config.text_color,
            config.bold,
        )
        response = await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "addConditionalFormatRule": {
                        "rule": {"ranges": [grid_range], "booleanRule": boolean_rule},
                        "index": 0,
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "add_conditional_format_rule",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "condition_type": config.condition_type,
            "replies": response.get("replies", []),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _sort_range(
        self, config: GoogleSheetsSortRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Sort the rows of a range by one column."""
        logger.info(f"[GoogleSheetsNode] Sorting {config.sheet_name}!{config.range}")
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        # sortRange indexes the column relative to the range, not the sheet.
        range_start_column = grid_range.get("startColumnIndex", 0)
        dimension_index = (config.sort_column - 1) - range_start_column
        if dimension_index < 0:
            raise ValueError(
                f"Sort column {config.sort_column} falls outside the range {config.range}."
            )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "sortRange": {
                        "range": grid_range,
                        "sortSpecs": [
                            {
                                "dimensionIndex": dimension_index,
                                "sortOrder": config.sort_order,
                            }
                        ],
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "sort_range",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "sort_column": config.sort_column,
            "sort_order": config.sort_order,
            "timestamp": time.time(),
            "status": "success",
        }

    # ------------------------------------------------------------------
    # Data validation and rule teardown
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_option_values(raw: Optional[str]) -> List[str]:
        """Dropdown options arrive as a JSON array or a comma-separated list."""
        if raw is None or not str(raw).strip():
            return []
        text = str(raw).strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError(
                    f"Values looks like a JSON array but could not be parsed: {text[:80]}"
                )
            if not isinstance(parsed, list):
                raise ValueError("Values must be a JSON array or a comma-separated list.")
            return [str(v).strip() for v in parsed if str(v).strip()]
        return [part.strip() for part in text.split(",") if part.strip()]

    async def _set_data_validation(
        self, config: GoogleSheetsSetDataValidationConfig, access_token: str
    ) -> Dict[str, Any]:
        """Apply a dropdown or input rule to a range."""
        logger.info(
            f"[GoogleSheetsNode] Data validation ({config.rule_type}) on "
            f"{config.sheet_name}!{config.range}"
        )
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )

        options: List[str] = []
        if config.rule_type == "list":
            options = self._parse_option_values(config.values)
            if not options:
                raise ValueError(
                    "A dropdown needs Values — a comma-separated list such as "
                    "'Not started, Contacted, Won'."
                )
            condition = {
                "type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": v} for v in options],
            }
        elif config.rule_type == "list_from_range":
            if not config.values or not config.values.strip():
                raise ValueError(
                    "A range-backed dropdown needs Values set to an A1 range, e.g. Config!A2:A10."
                )
            source = config.values.strip()
            condition = {
                "type": "ONE_OF_RANGE",
                "values": [{"userEnteredValue": source if source.startswith("=") else f"={source}"}],
            }
        elif config.rule_type == "checkbox":
            condition = {"type": "BOOLEAN"}
        elif config.rule_type == "number_between":
            if config.min_value is None or config.max_value is None:
                raise ValueError("The number range rule needs both Minimum and Maximum.")
            condition = {
                "type": "NUMBER_BETWEEN",
                "values": [
                    {"userEnteredValue": config.min_value},
                    {"userEnteredValue": config.max_value},
                ],
            }
        elif config.rule_type == "date":
            condition = {"type": "DATE_IS_VALID"}
        elif config.rule_type == "email":
            condition = {"type": "TEXT_IS_VALID_EMAIL"}
        elif config.rule_type == "url":
            condition = {"type": "TEXT_IS_VALID_URL"}
        else:  # custom_formula
            if not config.values or not config.values.strip():
                raise ValueError("The custom formula rule needs Values set to the formula.")
            formula = config.values.strip()
            condition = {
                "type": "CUSTOM_FORMULA",
                "values": [{"userEnteredValue": formula if formula.startswith("=") else f"={formula}"}],
            }

        rule: Dict[str, Any] = {"condition": condition, "strict": _is_true(config.strict)}
        # showCustomUi renders the in-cell dropdown chip; it only means anything
        # for the two list rules.
        if config.rule_type in ("list", "list_from_range"):
            rule["showCustomUi"] = _is_true(config.show_dropdown)
        if config.help_text:
            rule["inputMessage"] = config.help_text

        await self._send_batch_update(
            config.spreadsheet_id,
            [{"setDataValidation": {"range": grid_range, "rule": rule}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "set_data_validation",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "rule_type": config.rule_type,
            "options": options,
            "strict": _is_true(config.strict),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _clear_data_validation(
        self, config: GoogleSheetsClearDataValidationConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove data validation from a range."""
        logger.info(
            f"[GoogleSheetsNode] Clearing data validation on {config.sheet_name}!{config.range}"
        )
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        # setDataValidation with no rule is the documented way to clear it.
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"setDataValidation": {"range": grid_range}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "clear_data_validation",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _fetch_sheet_entry(
        self, spreadsheet_id: str, sheet_name: str, fields: str, access_token: str
    ) -> Dict[str, Any]:
        """Read one sheet's entry from the spreadsheet, limited to `fields`."""
        url = f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": fields},
            )
            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Sheets API error: {error_msg}")
            for sheet in response.json().get("sheets", []):
                if sheet.get("properties", {}).get("title") == sheet_name:
                    return sheet
        raise ValueError(f"Sheet '{sheet_name}' not found")

    async def _delete_conditional_format_rules(
        self, config: GoogleSheetsDeleteConditionalFormatConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete one conditional formatting rule, or all of them on a sheet."""
        sheet = await self._fetch_sheet_entry(
            config.spreadsheet_id,
            config.sheet_name,
            "sheets(properties(sheetId,title),conditionalFormats)",
            access_token,
        )
        sheet_id = sheet["properties"]["sheetId"]
        rule_count = len(sheet.get("conditionalFormats", []) or [])

        if config.rule_index is not None:
            if config.rule_index >= rule_count:
                raise ValueError(
                    f"Sheet '{config.sheet_name}' has {rule_count} conditional formatting "
                    f"rule(s); there is no rule at index {config.rule_index}."
                )
            indexes = [config.rule_index]
        else:
            indexes = list(range(rule_count))

        if not indexes:
            return {
                "type": "google_sheets",
                "operation": "delete_conditional_format_rules",
                "spreadsheet_id": config.spreadsheet_id,
                "sheet_name": config.sheet_name,
                "sheet_id": sheet_id,
                "rules_deleted": 0,
                "timestamp": time.time(),
                "status": "success",
            }

        # Each delete reindexes the rest, so deleting index 0 repeatedly drains
        # the whole list; a single target needs exactly one delete at its index.
        target = config.rule_index if config.rule_index is not None else 0
        requests = [
            {"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": target}}
            for _ in indexes
        ]
        await self._send_batch_update(config.spreadsheet_id, requests, access_token)
        return {
            "type": "google_sheets",
            "operation": "delete_conditional_format_rules",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "sheet_id": sheet_id,
            "rules_deleted": len(indexes),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _clear_banding(
        self, config: GoogleSheetsClearBandingConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove every banded range on a sheet so banding can be reapplied."""
        sheet = await self._fetch_sheet_entry(
            config.spreadsheet_id,
            config.sheet_name,
            "sheets(properties(sheetId,title),bandedRanges)",
            access_token,
        )
        banded = sheet.get("bandedRanges", []) or []
        if not banded:
            return {
                "type": "google_sheets",
                "operation": "clear_alternating_colors",
                "spreadsheet_id": config.spreadsheet_id,
                "sheet_name": config.sheet_name,
                "bands_removed": 0,
                "timestamp": time.time(),
                "status": "success",
            }

        requests = [
            {"deleteBanding": {"bandedRangeId": band["bandedRangeId"]}} for band in banded
        ]
        await self._send_batch_update(config.spreadsheet_id, requests, access_token)
        return {
            "type": "google_sheets",
            "operation": "clear_alternating_colors",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "bands_removed": len(requests),
            "timestamp": time.time(),
            "status": "success",
        }

    # ------------------------------------------------------------------
    # Tables
    #
    # A table is what gives a column CHIP dropdowns; plain data validation
    # only ever renders the arrow style. Column types live on the table, so
    # the dropdown values ride along in columnProperties rather than in a
    # separate setDataValidation call.
    # ------------------------------------------------------------------

    # Verified against the Tables guide; the rest of the enum is accepted by
    # the API but not useful enough to surface until someone asks.
    _TABLE_COLUMN_TYPES = {
        "TEXT",
        "DOUBLE",
        "CURRENCY",
        "PERCENT",
        "DATE",
        "TIME",
        "DATE_TIME",
        "DROPDOWN",
    }

    def _parse_table_columns(
        self,
        raw: Optional[str],
        grid_range: Dict[str, Any],
        headers: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Turn the `columns` JSON into columnProperties.

        `column` is given as a sheet letter because that is what a person reads
        off the top of the screen; the API wants an index relative to the
        table's own range, so the range's start column is subtracted here.

        `headers` is the table's existing header row. Typing a column without
        naming it makes the API rename it to "Column N", silently destroying
        whatever the header said, so the current text is carried forward
        whenever the caller does not supply a name.
        """
        if raw is None or not str(raw).strip():
            return []
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Column Types is not valid JSON: {exc}")
        if not isinstance(spec, list):
            raise ValueError('Column Types must be a JSON list, e.g. [{"column": "R", ...}].')

        range_start = grid_range.get("startColumnIndex", 0)
        properties: List[Dict[str, Any]] = []
        for entry in spec:
            if not isinstance(entry, dict):
                raise ValueError("Each entry in Column Types must be an object.")
            letter = str(entry.get("column", "")).strip()
            if not letter:
                raise ValueError('Each entry in Column Types needs a "column", e.g. "R".')
            column_type = str(entry.get("type", "TEXT")).strip().upper()
            if column_type not in self._TABLE_COLUMN_TYPES:
                raise ValueError(
                    f"Unsupported column type '{column_type}'. "
                    f"Use one of: {', '.join(sorted(self._TABLE_COLUMN_TYPES))}."
                )
            absolute = column_letters_to_index(letter)
            relative = absolute - range_start
            if relative < 0 or (
                "endColumnIndex" in grid_range and absolute >= grid_range["endColumnIndex"]
            ):
                raise ValueError(
                    f"Column {letter} falls outside the table range."
                )

            prop: Dict[str, Any] = {"columnIndex": relative, "columnType": column_type}
            name = entry.get("name")
            if not name and headers and relative < len(headers):
                name = headers[relative]
            if name:
                prop["columnName"] = str(name)
            if column_type == "DROPDOWN":
                options = self._parse_option_values(entry.get("values"))
                if not options:
                    raise ValueError(
                        f"Column {letter} is a DROPDOWN, so it needs \"values\" — "
                        'e.g. "Not started, Contacted, Won".'
                    )
                prop["dataValidationRule"] = {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": v} for v in options],
                    }
                }
            properties.append(prop)
        return properties

    async def _read_header_row(
        self, spreadsheet_id: str, sheet_name: str, grid_range: Dict[str, Any], access_token: str
    ) -> List[str]:
        """The first row of a range, used to keep table column names intact."""
        start_row = grid_range.get("startRowIndex", 0) + 1
        start_col = column_index_to_letters(grid_range.get("startColumnIndex", 0))
        end_col = (
            column_index_to_letters(grid_range["endColumnIndex"] - 1)
            if "endColumnIndex" in grid_range
            else ""
        )
        a1 = f"{sheet_name}!{start_col}{start_row}:{end_col}{start_row}"
        url = f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}/values/{a1}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
            if response.status_code != 200:
                # A missing header is not worth failing the whole operation over;
                # the caller just loses name preservation for unnamed columns.
                logger.warning(
                    "[GoogleSheetsNode] Could not read header row for %s: %s",
                    a1,
                    response.text[:200],
                )
                return []
            rows = response.json().get("values", [])
        return [str(v) for v in (rows[0] if rows else [])]

    async def _add_table(
        self, config: GoogleSheetsAddTableConfig, access_token: str
    ) -> Dict[str, Any]:
        """Convert a range into a table so its columns can carry chip dropdowns."""
        logger.info(
            f"[GoogleSheetsNode] Creating table '{config.table_name}' over "
            f"{config.sheet_name}!{config.range}"
        )
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        headers = (
            await self._read_header_row(
                config.spreadsheet_id, config.sheet_name, grid_range, access_token
            )
            if config.columns
            else []
        )
        column_properties = self._parse_table_columns(config.columns, grid_range, headers)

        table: Dict[str, Any] = {"name": config.table_name, "range": grid_range}
        if column_properties:
            table["columnProperties"] = column_properties

        response = await self._send_batch_update(
            config.spreadsheet_id, [{"addTable": {"table": table}}], access_token
        )
        created = (
            response.get("replies", [{}])[0].get("addTable", {}).get("table", {})
        )
        return {
            "type": "google_sheets",
            "operation": "add_table",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "table_name": config.table_name,
            "table_id": created.get("tableId"),
            "typed_columns": len(column_properties),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _resolve_table_id(
        self, spreadsheet_id: str, sheet_name: str, table_name: str, access_token: str
    ) -> str:
        """Find a table's id by its name, scoped to one sheet."""
        sheet = await self._fetch_sheet_entry(
            spreadsheet_id, sheet_name, "sheets(properties(sheetId,title),tables)", access_token
        )
        tables = sheet.get("tables", []) or []
        for table in tables:
            if table.get("name") == table_name:
                return table["tableId"]
        known = ", ".join(t.get("name", "?") for t in tables) or "none"
        raise ValueError(
            f"No table named '{table_name}' on sheet '{sheet_name}'. Tables here: {known}."
        )

    async def _delete_table(
        self, config: GoogleSheetsDeleteTableConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove a table. Values stay; only the table wrapper goes."""
        logger.info(f"[GoogleSheetsNode] Deleting table '{config.table_name}'")
        table_id = await self._resolve_table_id(
            config.spreadsheet_id, config.sheet_name, config.table_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id, [{"deleteTable": {"tableId": table_id}}], access_token
        )
        return {
            "type": "google_sheets",
            "operation": "delete_table",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "table_name": config.table_name,
            "table_id": table_id,
            "timestamp": time.time(),
            "status": "success",
        }

    # ------------------------------------------------------------------
    # Coverage phase 1 — update/delete counterparts and range protection
    # ------------------------------------------------------------------

    def _boolean_rule(
        self, condition_type: str, value: Optional[str], value_max: Optional[str],
        background_color: Optional[str], text_color: Optional[str], bold: Optional[str],
    ) -> Dict[str, Any]:
        """Build a BooleanRule — shared by the add and update conditional-format ops."""
        needs_one = {
            "NUMBER_GREATER", "NUMBER_LESS", "NUMBER_EQ", "TEXT_CONTAINS",
            "TEXT_EQ", "TEXT_STARTS_WITH", "CUSTOM_FORMULA",
        }
        condition: Dict[str, Any] = {"type": condition_type}
        if condition_type == "NUMBER_BETWEEN":
            if value is None or value_max is None:
                raise ValueError("The between condition needs both Value and Second Value.")
            condition["values"] = [
                {"userEnteredValue": value},
                {"userEnteredValue": value_max},
            ]
        elif condition_type in needs_one:
            if not value:
                raise ValueError(f"Condition {condition_type} needs a Value.")
            condition["values"] = [{"userEnteredValue": value}]

        cell_format: Dict[str, Any] = {}
        background = hex_to_color(background_color)
        if background:
            cell_format["backgroundColor"] = background
        text_format: Dict[str, Any] = {}
        foreground = hex_to_color(text_color)
        if foreground:
            text_format["foregroundColor"] = foreground
        if bold is not None:
            text_format["bold"] = _is_true(bold)
        if text_format:
            cell_format["textFormat"] = text_format
        if not cell_format:
            raise ValueError(
                "The rule has no formatting to apply. Set a Background Colour, Text Colour or Bold."
            )
        return {"condition": condition, "format": cell_format}

    async def _update_conditional_format_rule(
        self, config: GoogleSheetsUpdateConditionalFormatConfig, access_token: str
    ) -> Dict[str, Any]:
        """Edit a conditional formatting rule, or move it in the priority order."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        if config.new_index is not None:
            request = {
                "updateConditionalFormatRule": {
                    "sheetId": sheet_id,
                    "index": config.rule_index,
                    "newIndex": config.new_index,
                }
            }
            action = "moved"
        else:
            if not config.condition_type:
                raise ValueError(
                    "Editing a rule needs a Condition. To only change priority, set Move To Position."
                )
            grid_range = a1_range_to_grid_range(config.range or "", sheet_id)
            request = {
                "updateConditionalFormatRule": {
                    "sheetId": sheet_id,
                    "index": config.rule_index,
                    "rule": {
                        "ranges": [grid_range],
                        "booleanRule": self._boolean_rule(
                            config.condition_type, config.value, config.value_max,
                            config.background_color, config.text_color, config.bold,
                        ),
                    },
                }
            }
            action = "edited"

        await self._send_batch_update(config.spreadsheet_id, [request], access_token)
        return {
            "type": "google_sheets",
            "operation": "update_conditional_format_rule",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "rule_index": config.rule_index,
            "action": action,
            "new_index": config.new_index,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _update_banding(
        self, config: GoogleSheetsUpdateBandingConfig, access_token: str
    ) -> Dict[str, Any]:
        """Recolour banding in place, so re-running a format script does not fail."""
        sheet = await self._fetch_sheet_entry(
            config.spreadsheet_id, config.sheet_name,
            "sheets(properties(sheetId,title),bandedRanges)", access_token,
        )
        banded = sheet.get("bandedRanges", []) or []
        if not banded:
            raise ValueError(
                f"Sheet '{config.sheet_name}' has no alternating colours to recolour. "
                "Use Add Alternating Colours first."
            )

        row_properties: Dict[str, Any] = {}
        fields: List[str] = []
        for attr, api_key in (
            ("header_color", "headerColor"),
            ("first_band_color", "firstBandColor"),
            ("second_band_color", "secondBandColor"),
        ):
            colour = hex_to_color(getattr(config, attr))
            if colour:
                row_properties[api_key] = colour
                fields.append(f"rowProperties.{api_key}")
        if not fields:
            raise ValueError("No colours were specified.")

        requests = [
            {
                "updateBanding": {
                    "bandedRange": {
                        "bandedRangeId": band["bandedRangeId"],
                        "rowProperties": row_properties,
                    },
                    "fields": ",".join(fields),
                }
            }
            for band in banded
        ]
        await self._send_batch_update(config.spreadsheet_id, requests, access_token)
        return {
            "type": "google_sheets",
            "operation": "update_alternating_colors",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "bands_updated": len(requests),
            "applied": fields,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _update_table(
        self, config: GoogleSheetsUpdateTableConfig, access_token: str
    ) -> Dict[str, Any]:
        """Rename, resize or retype an existing table."""
        table_id = await self._resolve_table_id(
            config.spreadsheet_id, config.sheet_name, config.table_name, access_token
        )
        table: Dict[str, Any] = {"tableId": table_id}
        fields: List[str] = []
        if config.new_name:
            table["name"] = config.new_name
            fields.append("name")

        grid_range = None
        if config.range:
            grid_range = await self._resolve_grid_range(
                config.spreadsheet_id, config.sheet_name, config.range, access_token
            )
            table["range"] = grid_range
            fields.append("range")
        if config.columns:
            if grid_range is None:
                # Column letters resolve against the table's own range, so an edit
                # that retypes columns without resizing still needs to know it.
                grid_range = await self._table_grid_range(
                    config.spreadsheet_id, config.sheet_name, config.table_name, access_token
                )
            headers = await self._read_header_row(
                config.spreadsheet_id, config.sheet_name, grid_range, access_token
            )
            table["columnProperties"] = self._parse_table_columns(
                config.columns, grid_range, headers
            )
            fields.append("columnProperties")

        if not fields:
            raise ValueError("Nothing to change. Set a New Name, New Range or Column Types.")

        await self._send_batch_update(
            config.spreadsheet_id,
            [{"updateTable": {"table": table, "fields": ",".join(fields)}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "update_table",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "table_name": config.table_name,
            "table_id": table_id,
            "applied": fields,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _table_grid_range(
        self, spreadsheet_id: str, sheet_name: str, table_name: str, access_token: str
    ) -> Dict[str, Any]:
        """The GridRange a table currently covers."""
        sheet = await self._fetch_sheet_entry(
            spreadsheet_id, sheet_name, "sheets(properties(sheetId,title),tables)", access_token
        )
        for table in sheet.get("tables", []) or []:
            if table.get("name") == table_name:
                return table.get("range", {"sheetId": sheet["properties"]["sheetId"]})
        raise ValueError(f"No table named '{table_name}' on sheet '{sheet_name}'.")

    async def _update_spreadsheet_properties(
        self, config: GoogleSheetsUpdateSpreadsheetPropertiesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Rename the spreadsheet or change locale, timezone or recalculation."""
        properties: Dict[str, Any] = {}
        fields: List[str] = []
        for attr, api_key in (
            ("title", "title"),
            ("locale", "locale"),
            ("time_zone", "timeZone"),
            ("auto_recalc", "autoRecalc"),
        ):
            value = getattr(config, attr)
            if value:
                properties[api_key] = value
                fields.append(api_key)
        if not fields:
            raise ValueError("No properties were specified.")

        await self._send_batch_update(
            config.spreadsheet_id,
            [{"updateSpreadsheetProperties": {"properties": properties, "fields": ",".join(fields)}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "update_spreadsheet_properties",
            "spreadsheet_id": config.spreadsheet_id,
            "applied": fields,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _add_named_range(
        self, config: GoogleSheetsAddNamedRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Name a range so formulas can refer to it."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        response = await self._send_batch_update(
            config.spreadsheet_id,
            [{"addNamedRange": {"namedRange": {"name": config.range_name, "range": grid_range}}}],
            access_token,
        )
        created = response.get("replies", [{}])[0].get("addNamedRange", {}).get("namedRange", {})
        return {
            "type": "google_sheets",
            "operation": "add_named_range",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range_name": config.range_name,
            "range": config.range,
            "named_range_id": created.get("namedRangeId"),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _resolve_named_range(
        self, spreadsheet_id: str, range_name: str, access_token: str
    ) -> Dict[str, Any]:
        """Find a named range by name. Named ranges are spreadsheet-scoped."""
        url = f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "namedRanges"},
            )
            if response.status_code != 200:
                error_data = response.json()
                raise ValueError(
                    f"Google Sheets API error: {error_data.get('error', {}).get('message', response.text)}"
                )
            named = response.json().get("namedRanges", []) or []
        for entry in named:
            if entry.get("name") == range_name:
                return entry
        known = ", ".join(e.get("name", "?") for e in named) or "none"
        raise ValueError(f"No named range '{range_name}'. Named ranges here: {known}.")

    async def _update_named_range(
        self, config: GoogleSheetsUpdateNamedRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Rename a named range or point it somewhere else."""
        existing = await self._resolve_named_range(
            config.spreadsheet_id, config.range_name, access_token
        )
        named_range: Dict[str, Any] = {"namedRangeId": existing["namedRangeId"]}
        fields: List[str] = []
        if config.new_name:
            named_range["name"] = config.new_name
            fields.append("name")
        if config.range:
            named_range["range"] = await self._resolve_grid_range(
                config.spreadsheet_id, config.sheet_name, config.range, access_token
            )
            fields.append("range")
        if not fields:
            raise ValueError("Nothing to change. Set a New Name or a New Range.")

        await self._send_batch_update(
            config.spreadsheet_id,
            [{"updateNamedRange": {"namedRange": named_range, "fields": ",".join(fields)}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "update_named_range",
            "spreadsheet_id": config.spreadsheet_id,
            "range_name": config.range_name,
            "named_range_id": existing["namedRangeId"],
            "applied": fields,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _delete_named_range(
        self, config: GoogleSheetsDeleteNamedRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove a named range, leaving the cells alone."""
        existing = await self._resolve_named_range(
            config.spreadsheet_id, config.range_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"deleteNamedRange": {"namedRangeId": existing["namedRangeId"]}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "delete_named_range",
            "spreadsheet_id": config.spreadsheet_id,
            "range_name": config.range_name,
            "named_range_id": existing["namedRangeId"],
            "timestamp": time.time(),
            "status": "success",
        }

    @staticmethod
    def _editor_emails(raw: Optional[str]) -> List[str]:
        return [part.strip() for part in str(raw or "").split(",") if part.strip()]

    async def _add_protected_range(
        self, config: GoogleSheetsAddProtectedRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Protect a range from edits."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        protected: Dict[str, Any] = {"range": grid_range, "warningOnly": _is_true(config.warning_only)}
        if config.description:
            protected["description"] = config.description
        editors = self._editor_emails(config.editors)
        if editors:
            if _is_true(config.warning_only):
                # A warning-only range is advisory, so the API rejects an editor list.
                raise ValueError(
                    "Allowed Editors cannot be combined with Warning Only. "
                    "Set Warning Only to No to restrict who can edit."
                )
            protected["editors"] = {"users": editors}

        response = await self._send_batch_update(
            config.spreadsheet_id,
            [{"addProtectedRange": {"protectedRange": protected}}],
            access_token,
        )
        created = (
            response.get("replies", [{}])[0].get("addProtectedRange", {}).get("protectedRange", {})
        )
        return {
            "type": "google_sheets",
            "operation": "add_protected_range",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "description": config.description,
            "warning_only": _is_true(config.warning_only),
            "editors": editors,
            "protected_range_id": created.get("protectedRangeId"),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _resolve_protected_range(
        self, spreadsheet_id: str, sheet_name: str, description: str, access_token: str
    ) -> Dict[str, Any]:
        """Find a protected range by its description, scoped to one sheet."""
        sheet = await self._fetch_sheet_entry(
            spreadsheet_id, sheet_name,
            "sheets(properties(sheetId,title),protectedRanges)", access_token,
        )
        ranges = sheet.get("protectedRanges", []) or []
        for entry in ranges:
            if entry.get("description") == description:
                return entry
        known = ", ".join(e.get("description", "(no description)") for e in ranges) or "none"
        raise ValueError(
            f"No protected range described '{description}' on sheet '{sheet_name}'. "
            f"Protected ranges here: {known}."
        )

    async def _update_protected_range(
        self, config: GoogleSheetsUpdateProtectedRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Change a protected range's extent, description or editors."""
        existing = await self._resolve_protected_range(
            config.spreadsheet_id, config.sheet_name, config.description, access_token
        )
        protected: Dict[str, Any] = {"protectedRangeId": existing["protectedRangeId"]}
        fields: List[str] = []
        if config.range:
            protected["range"] = await self._resolve_grid_range(
                config.spreadsheet_id, config.sheet_name, config.range, access_token
            )
            fields.append("range")
        if config.new_description:
            protected["description"] = config.new_description
            fields.append("description")
        if config.warning_only is not None:
            protected["warningOnly"] = _is_true(config.warning_only)
            fields.append("warningOnly")
        editors = self._editor_emails(config.editors)
        if editors:
            protected["editors"] = {"users": editors}
            fields.append("editors")
        if not fields:
            raise ValueError("Nothing to change.")

        await self._send_batch_update(
            config.spreadsheet_id,
            [{"updateProtectedRange": {"protectedRange": protected, "fields": ",".join(fields)}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "update_protected_range",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "protected_range_id": existing["protectedRangeId"],
            "applied": fields,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _delete_protected_range(
        self, config: GoogleSheetsDeleteProtectedRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove protection from a range."""
        existing = await self._resolve_protected_range(
            config.spreadsheet_id, config.sheet_name, config.description, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"deleteProtectedRange": {"protectedRangeId": existing["protectedRangeId"]}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "delete_protected_range",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "description": config.description,
            "protected_range_id": existing["protectedRangeId"],
            "timestamp": time.time(),
            "status": "success",
        }

    # ------------------------------------------------------------------
    # Coverage phase 2 — values, cells and data wrangling
    # ------------------------------------------------------------------

    @staticmethod
    def _grid_span(grid_range: Dict[str, Any]) -> tuple:
        """Rows and columns a bounded GridRange covers."""
        rows = grid_range.get("endRowIndex", 0) - grid_range.get("startRowIndex", 0)
        cols = grid_range.get("endColumnIndex", 0) - grid_range.get("startColumnIndex", 0)
        return rows, cols

    async def _set_cell_notes(
        self, config: GoogleSheetsSetNotesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Put the same note on every cell in a range, or clear them."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        # An empty note is how the API clears one, so "" is meaningful here and
        # must not be treated as "unset".
        note = config.note or ""
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"repeatCell": {"range": grid_range, "cell": {"note": note}, "fields": "note"}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "set_cell_notes",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "cleared": not note,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _insert_smart_chips(
        self, config: GoogleSheetsSmartChipsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Fill a range with people or rich link chips, one per cell."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        values = self._parse_option_values(config.values)
        if not values:
            raise ValueError("Values is empty — supply one email or URL per cell.")

        rows, cols = self._grid_span(grid_range)
        if cols != 1:
            raise ValueError("Smart chips are written one per cell down a single column.")
        if rows and len(values) > rows:
            raise ValueError(
                f"{len(values)} values given but the range only covers {rows} cell(s)."
            )

        def chip_cell(value: str) -> Dict[str, Any]:
            if config.chip_type == "person":
                person: Dict[str, Any] = {"email": value}
                if config.display_format:
                    person["displayFormat"] = config.display_format
                chip = {"personProperties": person}
            else:
                chip = {"richLinkProperties": {"uri": value}}
            # A chip run needs backing text; the API renders the chip over it.
            return {
                "userEnteredValue": {"stringValue": value},
                "chipRuns": [{"startIndex": 0, "chip": chip}],
            }

        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "updateCells": {
                        "range": {**grid_range, "endRowIndex": grid_range.get("startRowIndex", 0) + len(values)},
                        "rows": [{"values": [chip_cell(v)]} for v in values],
                        "fields": "userEnteredValue,chipRuns",
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "insert_smart_chips",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "chip_type": config.chip_type,
            "chips_written": len(values),
            "timestamp": time.time(),
            "status": "success",
        }

    _PIVOT_FUNCTIONS = {
        "SUM", "COUNTA", "COUNT", "COUNTUNIQUE", "AVERAGE", "MAX", "MIN",
        "MEDIAN", "PRODUCT", "STDEV", "STDEVP", "VAR", "VARP",
    }

    async def _insert_pivot_table(
        self, config: GoogleSheetsPivotTableConfig, access_token: str
    ) -> Dict[str, Any]:
        """Anchor a pivot table summarising a source range."""
        source_sheet = config.source_sheet_name or config.sheet_name
        source = await self._resolve_grid_range(
            config.spreadsheet_id, source_sheet, config.source_range, access_token
        )
        anchor = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.anchor_cell, access_token
        )
        source_start = source.get("startColumnIndex", 0)

        def offsets(raw: Optional[str]) -> List[int]:
            out = []
            for letter in [p.strip() for p in str(raw or "").split(",") if p.strip()]:
                absolute = column_letters_to_index(letter)
                relative = absolute - source_start
                if relative < 0 or (
                    "endColumnIndex" in source and absolute >= source["endColumnIndex"]
                ):
                    raise ValueError(f"Column {letter} falls outside the source range.")
                out.append(relative)
            return out

        try:
            spec = json.loads(config.pivot_values)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Summarise is not valid JSON: {exc}")
        if not isinstance(spec, list) or not spec:
            raise ValueError(
                'Summarise must be a non-empty JSON list, e.g. [{"column": "F", "function": "SUM"}].'
            )

        values = []
        for entry in spec:
            if not isinstance(entry, dict) or not entry.get("column"):
                raise ValueError('Each Summarise entry needs a "column".')
            function = str(entry.get("function", "SUM")).strip().upper()
            if function not in self._PIVOT_FUNCTIONS:
                raise ValueError(
                    f"Unsupported function '{function}'. "
                    f"Use one of: {', '.join(sorted(self._PIVOT_FUNCTIONS))}."
                )
            value: Dict[str, Any] = {
                "sourceColumnOffset": offsets(entry["column"])[0],
                "summarizeFunction": function,
            }
            if entry.get("name"):
                value["name"] = str(entry["name"])
            values.append(value)

        pivot: Dict[str, Any] = {"source": source, "valueLayout": "HORIZONTAL", "values": values}
        rows = [{"sourceColumnOffset": o, "showTotals": True, "sortOrder": "ASCENDING"}
                for o in offsets(config.pivot_rows)]
        cols = [{"sourceColumnOffset": o, "showTotals": True, "sortOrder": "ASCENDING"}
                for o in offsets(config.pivot_columns)]
        if rows:
            pivot["rows"] = rows
        if cols:
            pivot["columns"] = cols
        if not rows and not cols:
            raise ValueError("A pivot table needs at least one Group Rows By or Group Columns By column.")

        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "updateCells": {
                        "start": {
                            "sheetId": anchor["sheetId"],
                            "rowIndex": anchor.get("startRowIndex", 0),
                            "columnIndex": anchor.get("startColumnIndex", 0),
                        },
                        "rows": [{"values": [{"pivotTable": pivot}]}],
                        "fields": "pivotTable",
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "insert_pivot_table",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "anchor_cell": config.anchor_cell,
            "source_range": config.source_range,
            "group_rows": len(rows),
            "group_columns": len(cols),
            "values": len(values),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _copy_paste_range(
        self, config: GoogleSheetsCopyPasteConfig, access_token: str
    ) -> Dict[str, Any]:
        """Copy one range over another."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "copyPaste": {
                        "source": a1_range_to_grid_range(config.source_range, sheet_id),
                        "destination": a1_range_to_grid_range(config.destination_range, sheet_id),
                        "pasteType": config.paste_type,
                        "pasteOrientation": "TRANSPOSE" if _is_true(config.transpose) else "NORMAL",
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "copy_paste_range",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "source_range": config.source_range,
            "destination_range": config.destination_range,
            "paste_type": config.paste_type,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _cut_paste_range(
        self, config: GoogleSheetsCutPasteConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a range, leaving the source empty."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        destination = a1_range_to_grid_range(config.destination_cell, sheet_id)
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "cutPaste": {
                        "source": a1_range_to_grid_range(config.source_range, sheet_id),
                        # cutPaste anchors on a single coordinate, not a range.
                        "destination": {
                            "sheetId": sheet_id,
                            "rowIndex": destination.get("startRowIndex", 0),
                            "columnIndex": destination.get("startColumnIndex", 0),
                        },
                        "pasteType": config.paste_type,
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "cut_paste_range",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "source_range": config.source_range,
            "destination_cell": config.destination_cell,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _paste_data(
        self, config: GoogleSheetsPasteDataConfig, access_token: str
    ) -> Dict[str, Any]:
        """Paste delimited text into a sheet, splitting it into cells."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        anchor = a1_range_to_grid_range(config.anchor_cell, sheet_id)
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "pasteData": {
                        "coordinate": {
                            "sheetId": sheet_id,
                            "rowIndex": anchor.get("startRowIndex", 0),
                            "columnIndex": anchor.get("startColumnIndex", 0),
                        },
                        "data": config.data,
                        "type": "PASTE_NORMAL",
                        "delimiter": config.delimiter,
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "paste_data",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "anchor_cell": config.anchor_cell,
            "rows_pasted": len([line for line in config.data.splitlines() if line.strip()]),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _auto_fill(
        self, config: GoogleSheetsAutoFillConfig, access_token: str
    ) -> Dict[str, Any]:
        """Continue a pattern across a range."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "autoFill": {
                        "range": grid_range,
                        "useAlternateSeries": _is_true(config.use_alternate_series),
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "auto_fill",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _split_text_to_columns(
        self, config: GoogleSheetsTextToColumnsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Split a column of delimited text across several columns."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        request: Dict[str, Any] = {
            "source": grid_range,
            "delimiterType": config.delimiter_type,
        }
        if config.delimiter_type == "CUSTOM":
            if not config.custom_delimiter:
                raise ValueError("Split On is CUSTOM, so Custom Delimiter is required.")
            request["delimiter"] = config.custom_delimiter

        await self._send_batch_update(
            config.spreadsheet_id, [{"textToColumns": request}], access_token
        )
        return {
            "type": "google_sheets",
            "operation": "split_text_to_columns",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "delimiter_type": config.delimiter_type,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _trim_whitespace(
        self, config: GoogleSheetsTrimWhitespaceConfig, access_token: str
    ) -> Dict[str, Any]:
        """Strip leading, trailing and repeated spaces."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        response = await self._send_batch_update(
            config.spreadsheet_id, [{"trimWhitespace": {"range": grid_range}}], access_token
        )
        trimmed = (
            response.get("replies", [{}])[0].get("trimWhitespace", {}).get("cellsChangedCount")
        )
        return {
            "type": "google_sheets",
            "operation": "trim_whitespace",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "cells_changed": trimmed,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _remove_duplicate_rows(
        self, config: GoogleSheetsDeleteDuplicatesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete repeated rows, comparing whole rows or named columns."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        request: Dict[str, Any] = {"range": grid_range}
        letters = [p.strip() for p in str(config.compare_columns or "").split(",") if p.strip()]
        if letters:
            range_start = grid_range.get("startColumnIndex", 0)
            specs = []
            for letter in letters:
                absolute = column_letters_to_index(letter)
                relative = absolute - range_start
                if relative < 0 or (
                    "endColumnIndex" in grid_range and absolute >= grid_range["endColumnIndex"]
                ):
                    raise ValueError(f"Column {letter} falls outside the range.")
                specs.append({"dimension": "COLUMNS", "startIndex": relative, "endIndex": relative + 1})
            request["comparisonColumns"] = specs

        response = await self._send_batch_update(
            config.spreadsheet_id, [{"deleteDuplicates": request}], access_token
        )
        removed = (
            response.get("replies", [{}])[0].get("deleteDuplicates", {}).get("duplicatesRemovedCount")
        )
        return {
            "type": "google_sheets",
            "operation": "remove_duplicate_rows",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "compare_columns": letters,
            "duplicates_removed": removed,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _randomize_range(
        self, config: GoogleSheetsRandomizeRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Shuffle the rows of a range."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id, [{"randomizeRange": {"range": grid_range}}], access_token
        )
        return {
            "type": "google_sheets",
            "operation": "randomize_range",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _insert_cells(
        self, config: GoogleSheetsInsertRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Insert blank cells, shifting the rest out of the way."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"insertRange": {"range": grid_range, "shiftDimension": config.shift_direction}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "insert_cells",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "shift_direction": config.shift_direction,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _delete_cells(
        self, config: GoogleSheetsDeleteRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete cells, closing the gap."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"deleteRange": {"range": grid_range, "shiftDimension": config.shift_direction}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "delete_cells",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "shift_direction": config.shift_direction,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _move_dimension(
        self, config: GoogleSheetsMoveDimensionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a block of rows or columns elsewhere."""
        if config.end_index < config.start_index:
            raise ValueError("The end row/column comes before the start.")
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "moveDimension": {
                        "source": {
                            "sheetId": sheet_id,
                            "dimension": config.dimension,
                            "startIndex": config.start_index - 1,
                            "endIndex": config.end_index,
                        },
                        "destinationIndex": config.destination_index - 1,
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "move_rows_or_columns",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "dimension": config.dimension,
            "start_index": config.start_index,
            "end_index": config.end_index,
            "destination_index": config.destination_index,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _append_dimension(
        self, config: GoogleSheetsAppendDimensionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Add blank rows or columns to the end of a sheet."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "appendDimension": {
                        "sheetId": sheet_id,
                        "dimension": config.dimension,
                        "length": config.length,
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "append_rows_or_columns",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "dimension": config.dimension,
            "length": config.length,
            "timestamp": time.time(),
            "status": "success",
        }

    # ------------------------------------------------------------------
    # Coverage phase 3 — charts and embedded objects
    # ------------------------------------------------------------------

    # Sheets models stacking as a property of a basic chart, not a type, so the
    # UI-facing names are flattened back out here.
    _BASIC_CHART_TYPES = {
        "COLUMN": ("COLUMN", "NOT_STACKED"),
        "STACKED_COLUMN": ("COLUMN", "STACKED"),
        "BAR": ("BAR", "NOT_STACKED"),
        "STACKED_BAR": ("BAR", "STACKED"),
        "LINE": ("LINE", "NOT_STACKED"),
        "AREA": ("AREA", "NOT_STACKED"),
        "STACKED_AREA": ("AREA", "STACKED"),
        "SCATTER": ("SCATTER", "NOT_STACKED"),
        "COMBO": ("COMBO", "NOT_STACKED"),
    }

    def _chart_spec(
        self, chart_type: str, sheet_id: int, labels_range: Optional[str],
        series_ranges: Optional[str], title: Optional[str], subtitle: Optional[str],
        legend_position: Optional[str], axis_title: Optional[str],
    ) -> Dict[str, Any]:
        """Build a ChartSpec from ranges named in A1."""
        series = self._parse_option_values(series_ranges)
        if not series:
            raise ValueError("Values is required — give at least one range to plot.")

        def source(a1: str) -> Dict[str, Any]:
            # ChartData wraps its ranges in sourceRange; writing a bare
            # {"sources": ...} is accepted by no endpoint.
            return {"sourceRange": {"sources": [a1_range_to_grid_range(a1, sheet_id)]}}

        spec: Dict[str, Any] = {}
        if title:
            spec["title"] = title
        if subtitle:
            spec["subtitle"] = subtitle

        if chart_type in ("PIE", "DONUT"):
            if not labels_range:
                raise ValueError("A pie chart needs Labels — the range naming each slice.")
            if len(series) > 1:
                raise ValueError("A pie chart plots a single range of values.")
            spec["pieChart"] = {
                "domain": source(labels_range),
                "series": source(series[0]),
                "legendPosition": legend_position or "RIGHT_LEGEND",
                "pieHole": 0.5 if chart_type == "DONUT" else 0,
            }
        elif chart_type == "HISTOGRAM":
            spec["histogramChart"] = {
                "series": [{"data": source(r)} for r in series],
                "legendPosition": legend_position or "BOTTOM_LEGEND",
            }
        elif chart_type == "SCORECARD":
            if len(series) > 1:
                raise ValueError("A scorecard shows a single value range.")
            spec["scorecardChart"] = {
                "keyValueData": source(series[0]),
                "aggregateType": "SUM",
            }
        else:
            basic_type, stacked = self._BASIC_CHART_TYPES[chart_type]
            axis = []
            if axis_title:
                axis.append({"position": "LEFT_AXIS", "title": axis_title})
            basic: Dict[str, Any] = {
                "chartType": basic_type,
                "stackedType": stacked,
                "series": [{"series": source(r), "targetAxis": "LEFT_AXIS"} for r in series],
                "headerCount": 0,
            }
            if labels_range:
                basic["domains"] = [{"domain": source(labels_range)}]
            if axis:
                basic["axis"] = axis
            if legend_position:
                basic["legendPosition"] = legend_position
            spec["basicChart"] = basic
        return spec

    @staticmethod
    def _chart_position(
        sheet_id: int, anchor: Optional[Dict[str, Any]],
        width: Optional[int] = None, height: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Where a chart sits — overlaid on a sheet, or on its own new sheet."""
        if anchor is None:
            return {"newSheet": True}
        overlay: Dict[str, Any] = {
            "anchorCell": {
                "sheetId": sheet_id,
                "rowIndex": anchor.get("startRowIndex", 0),
                "columnIndex": anchor.get("startColumnIndex", 0),
            }
        }
        if width:
            overlay["widthPixels"] = width
        if height:
            overlay["heightPixels"] = height
        return {"overlayPosition": overlay}

    async def _resolve_chart(
        self, spreadsheet_id: str, sheet_name: str, chart_title: str, access_token: str
    ) -> Dict[str, Any]:
        """Find a chart by its title, scoped to one sheet."""
        sheet = await self._fetch_sheet_entry(
            spreadsheet_id, sheet_name, "sheets(properties(sheetId,title),charts)", access_token
        )
        charts = sheet.get("charts", []) or []
        for chart in charts:
            if chart.get("spec", {}).get("title") == chart_title:
                return chart
        known = ", ".join(
            c.get("spec", {}).get("title") or "(untitled)" for c in charts
        ) or "none"
        raise ValueError(
            f"No chart titled '{chart_title}' on sheet '{sheet_name}'. Charts here: {known}."
        )

    async def _add_chart(
        self, config: GoogleSheetsAddChartConfig, access_token: str
    ) -> Dict[str, Any]:
        """Build a chart from a range and place it."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        spec = self._chart_spec(
            config.chart_type, sheet_id, config.labels_range, config.series_ranges,
            config.chart_title, config.subtitle, config.legend_position, config.axis_title,
        )
        anchor = (
            a1_range_to_grid_range(config.anchor_cell, sheet_id) if config.anchor_cell else None
        )
        response = await self._send_batch_update(
            config.spreadsheet_id,
            [{"addChart": {"chart": {"spec": spec, "position": self._chart_position(sheet_id, anchor)}}}],
            access_token,
        )
        created = response.get("replies", [{}])[0].get("addChart", {}).get("chart", {})
        return {
            "type": "google_sheets",
            "operation": "add_chart",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "chart_type": config.chart_type,
            "chart_title": config.chart_title,
            "chart_id": created.get("chartId"),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _update_chart(
        self, config: GoogleSheetsUpdateChartConfig, access_token: str
    ) -> Dict[str, Any]:
        """Change an existing chart's spec."""
        chart = await self._resolve_chart(
            config.spreadsheet_id, config.sheet_name, config.chart_title, access_token
        )
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        existing = chart.get("spec", {})
        # updateChartSpec replaces the whole spec, so anything not supplied has
        # to be carried over from the chart as it stands.
        chart_type = config.chart_type or self._infer_chart_type(existing)
        series = config.series_ranges or self._existing_series(existing)
        if not series:
            raise ValueError(
                "This chart's series could not be read back, so Values must be supplied."
            )
        spec = self._chart_spec(
            chart_type, sheet_id,
            config.labels_range or self._existing_domain(existing),
            series,
            config.new_title if config.new_title is not None else existing.get("title"),
            config.subtitle if config.subtitle is not None else existing.get("subtitle"),
            config.legend_position, config.axis_title,
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"updateChartSpec": {"chartId": chart["chartId"], "spec": spec}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "update_chart",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "chart_id": chart["chartId"],
            "chart_type": chart_type,
            "timestamp": time.time(),
            "status": "success",
        }

    @staticmethod
    def _infer_chart_type(spec: Dict[str, Any]) -> str:
        """Map a spec that came back from the API onto our flattened type names."""
        if "pieChart" in spec:
            return "DONUT" if spec["pieChart"].get("pieHole") else "PIE"
        if "histogramChart" in spec:
            return "HISTOGRAM"
        if "scorecardChart" in spec:
            return "SCORECARD"
        basic = spec.get("basicChart", {})
        base = basic.get("chartType", "COLUMN")
        if basic.get("stackedType") == "STACKED" and base in ("COLUMN", "BAR", "AREA"):
            return f"STACKED_{base}"
        return base

    @staticmethod
    def _grid_to_a1(grid: Dict[str, Any]) -> str:
        """GridRange back to A1, for carrying a chart's own ranges forward."""
        start = (
            f"{column_index_to_letters(grid.get('startColumnIndex', 0))}"
            f"{grid.get('startRowIndex', 0) + 1}"
        )
        if "endRowIndex" not in grid and "endColumnIndex" not in grid:
            return start
        end = (
            f"{column_index_to_letters(grid.get('endColumnIndex', 1) - 1)}"
            f"{grid.get('endRowIndex', 1)}"
        )
        return f"{start}:{end}"

    @classmethod
    def _existing_series(cls, spec: Dict[str, Any]) -> Optional[str]:
        sources: List[str] = []
        if "basicChart" in spec:
            for entry in spec["basicChart"].get("series", []):
                for source in entry.get("series", {}).get("sourceRange", {}).get("sources", []):
                    sources.append(cls._grid_to_a1(source))
        elif "pieChart" in spec:
            for source in spec["pieChart"].get("series", {}).get("sourceRange", {}).get("sources", []):
                sources.append(cls._grid_to_a1(source))
        return ", ".join(sources) or None

    @classmethod
    def _existing_domain(cls, spec: Dict[str, Any]) -> Optional[str]:
        if "basicChart" in spec:
            for entry in spec["basicChart"].get("domains", []):
                for source in entry.get("domain", {}).get("sourceRange", {}).get("sources", []):
                    return cls._grid_to_a1(source)
        elif "pieChart" in spec:
            for source in spec["pieChart"].get("domain", {}).get("sourceRange", {}).get("sources", []):
                return cls._grid_to_a1(source)
        return None

    async def _move_chart(
        self, config: GoogleSheetsMoveChartConfig, access_token: str
    ) -> Dict[str, Any]:
        """Reposition or resize a chart."""
        chart = await self._resolve_chart(
            config.spreadsheet_id, config.sheet_name, config.chart_title, access_token
        )
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        anchor = (
            a1_range_to_grid_range(config.anchor_cell, sheet_id) if config.anchor_cell else None
        )
        position = self._chart_position(
            sheet_id, anchor, config.width_pixels, config.height_pixels
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "updateEmbeddedObjectPosition": {
                        "objectId": chart["chartId"],
                        "newPosition": position,
                        "fields": "*",
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "move_chart",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "chart_id": chart["chartId"],
            "moved_to_new_sheet": anchor is None,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _set_chart_border(
        self, config: GoogleSheetsChartBorderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Colour the border around a chart."""
        chart = await self._resolve_chart(
            config.spreadsheet_id, config.sheet_name, config.chart_title, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "updateEmbeddedObjectBorder": {
                        "objectId": chart["chartId"],
                        "border": {"color": hex_to_color(config.border_color)},
                        "fields": "color",
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "set_chart_border",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "chart_id": chart["chartId"],
            "border_color": config.border_color,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _delete_chart(
        self, config: GoogleSheetsDeleteChartConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove a chart."""
        chart = await self._resolve_chart(
            config.spreadsheet_id, config.sheet_name, config.chart_title, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"deleteEmbeddedObject": {"objectId": chart["chartId"]}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "delete_chart",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "chart_title": config.chart_title,
            "chart_id": chart["chartId"],
            "timestamp": time.time(),
            "status": "success",
        }

    async def _append_cells(
        self, config: GoogleSheetsAppendCellsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Append rows straight after the last row of data."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        try:
            rows = json.loads(config.values)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Values is not valid JSON: {exc}")
        if not isinstance(rows, list) or not rows:
            raise ValueError('Values must be a non-empty JSON array of rows, e.g. [["a", "b"]].')
        if not all(isinstance(row, list) for row in rows):
            raise ValueError('Each row must itself be a list, e.g. [["a", "b"], ["c", "d"]].')

        def cell(value: Any) -> Dict[str, Any]:
            if value is None or value == "":
                return {}
            if isinstance(value, bool):
                return {"userEnteredValue": {"boolValue": value}}
            if isinstance(value, (int, float)):
                return {"userEnteredValue": {"numberValue": value}}
            text = str(value)
            key = "formulaValue" if text.startswith("=") else "stringValue"
            return {"userEnteredValue": {key: text}}

        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "appendCells": {
                        "sheetId": sheet_id,
                        "rows": [{"values": [cell(v) for v in row]} for row in rows],
                        "fields": "userEnteredValue",
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "append_cells",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "rows_appended": len(rows),
            "timestamp": time.time(),
            "status": "success",
        }

    # ------------------------------------------------------------------
    # Coverage phase 4 — saved views, grouping and slicers
    # ------------------------------------------------------------------

    def _relative_column(self, letter: str, grid_range: Dict[str, Any], what: str) -> int:
        """A sheet column letter as an index relative to a range's own start."""
        absolute = column_letters_to_index(letter.strip())
        relative = absolute - grid_range.get("startColumnIndex", 0)
        if relative < 0 or (
            "endColumnIndex" in grid_range and absolute >= grid_range["endColumnIndex"]
        ):
            raise ValueError(f"Column {letter.strip()} falls outside the {what}.")
        return relative

    def _filter_specs(self, raw: Optional[str], grid_range: Dict[str, Any]) -> Dict[str, Any]:
        """Per-column hidden values, keyed by index relative to the view's range."""
        if not raw or not str(raw).strip():
            return {}
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Hide Values is not valid JSON: {exc}")
        if not isinstance(spec, list):
            raise ValueError('Hide Values must be a JSON list, e.g. [{"column": "R", "hide": "Won"}].')
        criteria: Dict[str, Any] = {}
        for entry in spec:
            if not isinstance(entry, dict) or not entry.get("column"):
                raise ValueError('Each Hide Values entry needs a "column".')
            hidden = self._parse_option_values(entry.get("hide"))
            if not hidden:
                raise ValueError(f'Column {entry["column"]} has no values to hide.')
            index = self._relative_column(str(entry["column"]), grid_range, "view range")
            criteria[str(index)] = {"hiddenValues": hidden}
        return criteria

    async def _resolve_filter_view(
        self, spreadsheet_id: str, sheet_name: str, view_title: str, access_token: str
    ) -> Dict[str, Any]:
        """Find a filter view by title, scoped to one sheet."""
        sheet = await self._fetch_sheet_entry(
            spreadsheet_id, sheet_name, "sheets(properties(sheetId,title),filterViews)", access_token
        )
        views = sheet.get("filterViews", []) or []
        for view in views:
            if view.get("title") == view_title:
                return view
        known = ", ".join(v.get("title", "(untitled)") for v in views) or "none"
        raise ValueError(
            f"No filter view called '{view_title}' on sheet '{sheet_name}'. Views here: {known}."
        )

    async def _add_filter_view(
        self, config: GoogleSheetsAddFilterViewConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a named, private filter."""
        grid_range = await self._resolve_grid_range(
            config.spreadsheet_id, config.sheet_name, config.range, access_token
        )
        view: Dict[str, Any] = {"title": config.view_title, "range": grid_range}
        if config.sort_column:
            view["sortSpecs"] = [
                {
                    "dimensionIndex": self._relative_column(
                        config.sort_column, grid_range, "view range"
                    ),
                    "sortOrder": config.sort_order or "ASCENDING",
                }
            ]
        criteria = self._filter_specs(config.hide_values, grid_range)
        if criteria:
            view["criteria"] = criteria

        response = await self._send_batch_update(
            config.spreadsheet_id, [{"addFilterView": {"filter": view}}], access_token
        )
        created = response.get("replies", [{}])[0].get("addFilterView", {}).get("filter", {})
        return {
            "type": "google_sheets",
            "operation": "save_filter_view",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "view_title": config.view_title,
            "filter_view_id": created.get("filterViewId"),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _update_filter_view(
        self, config: GoogleSheetsUpdateFilterViewConfig, access_token: str
    ) -> Dict[str, Any]:
        """Rename, move or re-sort a filter view."""
        existing = await self._resolve_filter_view(
            config.spreadsheet_id, config.sheet_name, config.view_title, access_token
        )
        view: Dict[str, Any] = {"filterViewId": existing["filterViewId"]}
        fields: List[str] = []
        grid_range = existing.get("range", {})
        if config.new_title:
            view["title"] = config.new_title
            fields.append("title")
        if config.range:
            grid_range = await self._resolve_grid_range(
                config.spreadsheet_id, config.sheet_name, config.range, access_token
            )
            view["range"] = grid_range
            fields.append("range")
        if config.sort_column:
            view["sortSpecs"] = [
                {
                    "dimensionIndex": self._relative_column(
                        config.sort_column, grid_range, "view range"
                    ),
                    "sortOrder": config.sort_order or "ASCENDING",
                }
            ]
            fields.append("sortSpecs")
        if not fields:
            raise ValueError("Nothing to change. Set a New Name, New Range or Sort By Column.")

        await self._send_batch_update(
            config.spreadsheet_id,
            [{"updateFilterView": {"filter": view, "fields": ",".join(fields)}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "update_filter_view",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "filter_view_id": existing["filterViewId"],
            "applied": fields,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _duplicate_filter_view(
        self, config: GoogleSheetsDuplicateFilterViewConfig, access_token: str
    ) -> Dict[str, Any]:
        """Copy a filter view."""
        existing = await self._resolve_filter_view(
            config.spreadsheet_id, config.sheet_name, config.view_title, access_token
        )
        response = await self._send_batch_update(
            config.spreadsheet_id,
            [{"duplicateFilterView": {"filterId": existing["filterViewId"]}}],
            access_token,
        )
        created = response.get("replies", [{}])[0].get("duplicateFilterView", {}).get("filter", {})
        return {
            "type": "google_sheets",
            "operation": "duplicate_filter_view",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "source_view_title": config.view_title,
            "new_filter_view_id": created.get("filterViewId"),
            "new_view_title": created.get("title"),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _delete_filter_view(
        self, config: GoogleSheetsDeleteFilterViewConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove a filter view."""
        existing = await self._resolve_filter_view(
            config.spreadsheet_id, config.sheet_name, config.view_title, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"deleteFilterView": {"filterId": existing["filterViewId"]}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "delete_filter_view",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "view_title": config.view_title,
            "filter_view_id": existing["filterViewId"],
            "timestamp": time.time(),
            "status": "success",
        }

    def _group_range(
        self, sheet_id: int, dimension: str, start_index: int, end_index: int
    ) -> Dict[str, Any]:
        if end_index < start_index:
            raise ValueError("The end row/column comes before the start.")
        return {
            "sheetId": sheet_id,
            "dimension": dimension,
            "startIndex": start_index - 1,
            "endIndex": end_index,
        }

    async def _group_dimension(
        self, config: GoogleSheetsAddDimensionGroupConfig, access_token: str
    ) -> Dict[str, Any]:
        """Make a block of rows or columns collapsible."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "addDimensionGroup": {
                        "range": self._group_range(
                            sheet_id, config.dimension, config.start_index, config.end_index
                        )
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "group_rows_or_columns",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "dimension": config.dimension,
            "start_index": config.start_index,
            "end_index": config.end_index,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _collapse_group(
        self, config: GoogleSheetsUpdateDimensionGroupConfig, access_token: str
    ) -> Dict[str, Any]:
        """Fold a group away or open it back up."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "updateDimensionGroup": {
                        "dimensionGroup": {
                            "range": self._group_range(
                                sheet_id, config.dimension, config.start_index, config.end_index
                            ),
                            "depth": config.depth,
                            "collapsed": _is_true(config.collapsed),
                        },
                        "fields": "collapsed",
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "collapse_group",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "dimension": config.dimension,
            "collapsed": _is_true(config.collapsed),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _ungroup_dimension(
        self, config: GoogleSheetsDeleteDimensionGroupConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove a collapsible group."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "deleteDimensionGroup": {
                        "range": self._group_range(
                            sheet_id, config.dimension, config.start_index, config.end_index
                        )
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "ungroup_rows_or_columns",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "dimension": config.dimension,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _resolve_slicer(
        self, spreadsheet_id: str, sheet_name: str, slicer_title: str, access_token: str
    ) -> Dict[str, Any]:
        """Find a slicer by title, scoped to one sheet."""
        sheet = await self._fetch_sheet_entry(
            spreadsheet_id, sheet_name, "sheets(properties(sheetId,title),slicers)", access_token
        )
        slicers = sheet.get("slicers", []) or []
        for slicer in slicers:
            if slicer.get("spec", {}).get("title") == slicer_title:
                return slicer
        known = ", ".join(
            s.get("spec", {}).get("title") or "(untitled)" for s in slicers
        ) or "none"
        raise ValueError(
            f"No slicer titled '{slicer_title}' on sheet '{sheet_name}'. Slicers here: {known}."
        )

    async def _add_slicer(
        self, config: GoogleSheetsAddSlicerConfig, access_token: str
    ) -> Dict[str, Any]:
        """Place an interactive filter control on the sheet."""
        sheet_id = await self._get_sheet_id(
            config.spreadsheet_id, config.sheet_name, access_token
        )
        data_range = a1_range_to_grid_range(config.range, sheet_id)
        anchor = a1_range_to_grid_range(config.anchor_cell, sheet_id)
        spec: Dict[str, Any] = {
            "dataRange": data_range,
            "columnIndex": self._relative_column(config.filter_column, data_range, "data range"),
            "applyToPivotTables": True,
        }
        if config.slicer_title:
            spec["title"] = config.slicer_title
        background = hex_to_color(config.background_color)
        if background:
            spec["backgroundColor"] = background

        response = await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "addSlicer": {
                        "slicer": {
                            "spec": spec,
                            "position": {
                                "overlayPosition": {
                                    "anchorCell": {
                                        "sheetId": sheet_id,
                                        "rowIndex": anchor.get("startRowIndex", 0),
                                        "columnIndex": anchor.get("startColumnIndex", 0),
                                    }
                                }
                            },
                        }
                    }
                }
            ],
            access_token,
        )
        created = response.get("replies", [{}])[0].get("addSlicer", {}).get("slicer", {})
        return {
            "type": "google_sheets",
            "operation": "add_slicer",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "range": config.range,
            "filter_column": config.filter_column,
            "slicer_id": created.get("slicerId"),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _update_slicer(
        self, config: GoogleSheetsUpdateSlicerConfig, access_token: str
    ) -> Dict[str, Any]:
        """Retitle a slicer, recolour it, or point it at another column."""
        slicer = await self._resolve_slicer(
            config.spreadsheet_id, config.sheet_name, config.slicer_title, access_token
        )
        spec: Dict[str, Any] = {}
        fields: List[str] = []
        if config.new_title:
            spec["title"] = config.new_title
            fields.append("title")
        if config.filter_column:
            spec["columnIndex"] = self._relative_column(
                config.filter_column, slicer.get("spec", {}).get("dataRange", {}), "data range"
            )
            fields.append("columnIndex")
        background = hex_to_color(config.background_color)
        if background:
            spec["backgroundColor"] = background
            fields.append("backgroundColor")
        if not fields:
            raise ValueError("Nothing to change. Set a New Title, Filter On Column or Background Colour.")

        await self._send_batch_update(
            config.spreadsheet_id,
            [{"updateSlicerSpec": {"slicerId": slicer["slicerId"], "spec": spec, "fields": ",".join(fields)}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "update_slicer",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "slicer_id": slicer["slicerId"],
            "applied": fields,
            "timestamp": time.time(),
            "status": "success",
        }

    # ------------------------------------------------------------------
    # Coverage phase 5 — developer metadata and connected data sources
    # ------------------------------------------------------------------

    async def _create_developer_metadata(
        self, config: GoogleSheetsCreateMetadataConfig, access_token: str
    ) -> Dict[str, Any]:
        """Tag a spreadsheet, sheet, row or column durably."""
        metadata: Dict[str, Any] = {
            "metadataKey": config.metadata_key,
            "visibility": config.visibility,
        }
        if config.metadata_value is not None:
            metadata["metadataValue"] = config.metadata_value

        if config.attach_to == "SPREADSHEET":
            metadata["location"] = {"spreadsheet": True}
        elif config.attach_to == "SHEET":
            metadata["location"] = {
                "sheetId": await self._get_sheet_id(
                    config.spreadsheet_id, config.sheet_name, access_token
                )
            }
        else:
            if config.start_index is None:
                raise ValueError(
                    f"Attaching to a {config.attach_to.lower()} needs From — the row or column number."
                )
            end = config.end_index if config.end_index is not None else config.start_index
            if end < config.start_index:
                raise ValueError("The end row/column comes before the start.")
            metadata["location"] = {
                "dimensionRange": {
                    "sheetId": await self._get_sheet_id(
                        config.spreadsheet_id, config.sheet_name, access_token
                    ),
                    "dimension": "ROWS" if config.attach_to == "ROW" else "COLUMNS",
                    "startIndex": config.start_index - 1,
                    "endIndex": end,
                }
            }

        response = await self._send_batch_update(
            config.spreadsheet_id,
            [{"createDeveloperMetadata": {"developerMetadata": metadata}}],
            access_token,
        )
        created = (
            response.get("replies", [{}])[0]
            .get("createDeveloperMetadata", {})
            .get("developerMetadata", {})
        )
        return {
            "type": "google_sheets",
            "operation": "create_developer_metadata",
            "spreadsheet_id": config.spreadsheet_id,
            "metadata_key": config.metadata_key,
            "attach_to": config.attach_to,
            "metadata_id": created.get("metadataId"),
            "timestamp": time.time(),
            "status": "success",
        }

    @staticmethod
    def _metadata_filter(metadata_key: str) -> Dict[str, Any]:
        """A DataFilter that selects every entry stored under one key."""
        return {"developerMetadataLookup": {"metadataKey": metadata_key}}

    async def _update_developer_metadata(
        self, config: GoogleSheetsUpdateMetadataConfig, access_token: str
    ) -> Dict[str, Any]:
        """Change the value stored under a metadata key."""
        response = await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "updateDeveloperMetadata": {
                        "dataFilters": [self._metadata_filter(config.metadata_key)],
                        "developerMetadata": {"metadataValue": config.metadata_value},
                        "fields": "metadataValue",
                    }
                }
            ],
            access_token,
        )
        updated = (
            response.get("replies", [{}])[0]
            .get("updateDeveloperMetadata", {})
            .get("developerMetadata", [])
        )
        return {
            "type": "google_sheets",
            "operation": "update_developer_metadata",
            "spreadsheet_id": config.spreadsheet_id,
            "metadata_key": config.metadata_key,
            "entries_updated": len(updated),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _delete_developer_metadata(
        self, config: GoogleSheetsDeleteMetadataConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove every entry stored under a metadata key."""
        response = await self._send_batch_update(
            config.spreadsheet_id,
            [{"deleteDeveloperMetadata": {"dataFilter": self._metadata_filter(config.metadata_key)}}],
            access_token,
        )
        deleted = (
            response.get("replies", [{}])[0]
            .get("deleteDeveloperMetadata", {})
            .get("deletedDeveloperMetadata", [])
        )
        return {
            "type": "google_sheets",
            "operation": "delete_developer_metadata",
            "spreadsheet_id": config.spreadsheet_id,
            "metadata_key": config.metadata_key,
            "entries_deleted": len(deleted),
            "timestamp": time.time(),
            "status": "success",
        }

    @staticmethod
    def _bigquery_spec(
        project_id: str, source_type: str, dataset_id: Optional[str], table_id: Optional[str],
        table_project_id: Optional[str], query: Optional[str],
    ) -> Dict[str, Any]:
        """A BigQuery DataSourceSpec, either a whole table or a query."""
        bigquery: Dict[str, Any] = {"projectId": project_id}
        if source_type == "query":
            if not query or not query.strip():
                raise ValueError("Source is 'query', so Query is required.")
            bigquery["querySpec"] = {"rawQuery": query}
        else:
            if not dataset_id or not table_id:
                raise ValueError("Source is 'table', so Dataset and Table are both required.")
            bigquery["tableSpec"] = {
                "datasetId": dataset_id,
                "tableId": table_id,
                "tableProjectId": table_project_id or project_id,
            }
        return {"bigQuery": bigquery}

    async def _add_data_source(
        self, config: GoogleSheetsAddDataSourceConfig, access_token: str
    ) -> Dict[str, Any]:
        """Connect a BigQuery table or query to the spreadsheet."""
        spec = self._bigquery_spec(
            config.project_id, config.source_type, config.dataset_id, config.table_id,
            config.table_project_id, config.query,
        )
        response = await self._send_batch_update(
            config.spreadsheet_id,
            [{"addDataSource": {"dataSource": {"spec": spec}}}],
            access_token,
        )
        created = response.get("replies", [{}])[0].get("addDataSource", {}).get("dataSource", {})
        return {
            "type": "google_sheets",
            "operation": "add_data_source",
            "spreadsheet_id": config.spreadsheet_id,
            "project_id": config.project_id,
            "source_type": config.source_type,
            "data_source_id": created.get("dataSourceId"),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _update_data_source(
        self, config: GoogleSheetsUpdateDataSourceConfig, access_token: str
    ) -> Dict[str, Any]:
        """Repoint a data source at a different table or query."""
        spec = self._bigquery_spec(
            config.project_id, config.source_type, config.dataset_id, config.table_id,
            config.table_project_id, config.query,
        )
        await self._send_batch_update(
            config.spreadsheet_id,
            [
                {
                    "updateDataSource": {
                        "dataSource": {"dataSourceId": config.data_source_id, "spec": spec},
                        "fields": "spec",
                    }
                }
            ],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "repoint_data_source",
            "spreadsheet_id": config.spreadsheet_id,
            "data_source_id": config.data_source_id,
            "source_type": config.source_type,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _delete_data_source(
        self, config: GoogleSheetsDeleteDataSourceConfig, access_token: str
    ) -> Dict[str, Any]:
        """Disconnect a data source."""
        await self._send_batch_update(
            config.spreadsheet_id,
            [{"deleteDataSource": {"dataSourceId": config.data_source_id}}],
            access_token,
        )
        return {
            "type": "google_sheets",
            "operation": "delete_data_source",
            "spreadsheet_id": config.spreadsheet_id,
            "data_source_id": config.data_source_id,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _refresh_data_source(
        self, config: GoogleSheetsRefreshDataSourceConfig, access_token: str
    ) -> Dict[str, Any]:
        """Re-run a connected data source, or all of them."""
        # The request is a union — exactly one of dataSourceId / isAll.
        request: Dict[str, Any] = {"force": _is_true(config.force)}
        if config.data_source_id:
            request["dataSourceId"] = config.data_source_id
        else:
            request["isAll"] = True

        await self._send_batch_update(
            config.spreadsheet_id, [{"refreshDataSource": request}], access_token
        )
        return {
            "type": "google_sheets",
            "operation": "refresh_data_source",
            "spreadsheet_id": config.spreadsheet_id,
            "data_source_id": config.data_source_id,
            "refreshed_all": not config.data_source_id,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _cancel_data_source_refresh(
        self, config: GoogleSheetsCancelRefreshConfig, access_token: str
    ) -> Dict[str, Any]:
        """Stop a running refresh."""
        request: Dict[str, Any] = {}
        if config.data_source_id:
            request["dataSourceId"] = config.data_source_id
        else:
            request["isAll"] = True

        await self._send_batch_update(
            config.spreadsheet_id, [{"cancelDataSourceRefresh": request}], access_token
        )
        return {
            "type": "google_sheets",
            "operation": "cancel_data_source_refresh",
            "spreadsheet_id": config.spreadsheet_id,
            "data_source_id": config.data_source_id,
            "cancelled_all": not config.data_source_id,
            "timestamp": time.time(),
            "status": "success",
        }
