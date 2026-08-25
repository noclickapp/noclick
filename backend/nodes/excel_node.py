"""
Excel node for Microsoft Graph API - Complete Excel workbook automation.

Supports all Excel operations via Microsoft Graph API including workbooks, worksheets,
ranges, tables, charts, and named items. Uses centralized Microsoft OAuth.

Research Source: Microsoft Graph Excel API v1.0 Documentation
Total Operations: 43 (across 6 categories)
"""

from typing import Dict, Any, Literal, Optional, Union, List, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft import EXCEL_SCOPES
from nodes.core.dynamic_options import require_credential_token
import httpx
import json
import logging
from nodes.oauth.microsoft_oauth import refresh_access_token, is_token_expired

logger = logging.getLogger(__name__)

# ============================================================================
# Credentials
# ============================================================================


class ExcelOAuthCredential(BaseModel):
    """
    Microsoft OAuth credential for Excel (via Graph API).

    Uses centralized Microsoft OAuth - credentials are automatically created
    when users connect their Microsoft account through the OAuth flow.

    Scopes required:
    - Files.ReadWrite.All: Read and write Excel files
    - User.Read: Get user profile info
    """

    credential_type: Literal["microsoft_excel_oauth"] = Field(
        "microsoft_excel_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str = Field(..., description="OAuth refresh token for token renewal")
    expires_at: str = Field(..., description="Token expiry timestamp (ISO 8601)")
    email: str = Field(..., description="Microsoft account email address")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "microsoft",  # Uses centralized Microsoft OAuth
            "x-oauth-scopes": [
                "https://graph.microsoft.com/Files.ReadWrite.All",  # Full Excel file access
                "https://graph.microsoft.com/User.Read",  # User profile
            ],
        }
    )


# ============================================================================
# Config Models - Workbook Operations (6 operations)
# ============================================================================


class ExcelCreateSessionConfig(BaseModel):
    """Create a workbook session for persistent or non-persistent changes"""

    operation: Literal["create_workbook_session"] = Field(
        "create_workbook_session",
        json_schema_extra={
            "const": "create_workbook_session",
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "Create Workbook Session",
            "x-keywords": [
                "start session",
                "open workbook session",
                "begin editing session",
                "persistent session",
            ],
        },
        title="Create Workbook Session",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    persist_changes: bool = Field(
        True,
        title="Persist Changes",
        description="If true, changes are saved to the file (persistent session). If false, changes are temporary.",
    )


class ExcelCloseSessionConfig(BaseModel):
    """Close a workbook session"""

    operation: Literal["close_workbook_session"] = Field(
        "close_workbook_session",
        json_schema_extra={
            "const": "close_workbook_session",
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "Close Workbook Session",
            "x-keywords": [
                "end session",
                "close editing session",
                "finish session",
                "discard session",
            ],
        },
        title="Close Workbook Session",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    session_id: str = Field(
        ...,
        title="Session ID",
        description="Session ID to close (returned from create_session)",
    )


class ExcelRefreshSessionConfig(BaseModel):
    """Refresh a workbook session to keep it alive"""

    operation: Literal["refresh_workbook_session"] = Field(
        "refresh_workbook_session",
        json_schema_extra={
            "const": "refresh_workbook_session",
            "ui:hidden": True,
            "x-category": "Session",
            "x-is-trigger": False,
            "x-display-name": "Refresh Workbook Session",
            "x-keywords": [
                "keep session alive",
                "renew session",
                "extend session",
                "ping session",
            ],
        },
        title="Refresh Workbook Session",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    session_id: str = Field(
        ..., title="Session ID", description="Session ID to refresh"
    )


class ExcelCalculateConfig(BaseModel):
    """Recalculate all formulas in the workbook"""

    operation: Literal["recalculate_workbook"] = Field(
        "recalculate_workbook",
        json_schema_extra={
            "const": "recalculate_workbook",
            "ui:hidden": True,
            "x-category": "Workbook",
            "x-is-trigger": False,
            "x-display-name": "Recalculate Workbook",
            "x-keywords": [
                "recalc formulas",
                "recompute workbook",
                "refresh formulas",
                "force calculation",
                "recalculate cells",
            ],
        },
        title="Recalculate Workbook",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    calculation_type: str = Field(
        "Recalculate",
        title="Calculation Type",
        description="Recalculate (default), Full, or FullRebuild",
        json_schema_extra={
            "enum": ["Recalculate", "Full", "FullRebuild"],
            "x-enum-searchable": True,
        },
    )


class ExcelExecuteFunctionConfig(BaseModel):
    """Execute built-in Excel function (300+ functions available)"""

    operation: Literal["execute_excel_function"] = Field(
        "execute_excel_function",
        json_schema_extra={
            "const": "execute_excel_function",
            "ui:hidden": True,
            "x-category": "Workbook",
            "x-is-trigger": False,
            "x-display-name": "Execute Excel Function",
            "x-keywords": [
                "run excel formula",
                "call function",
                "vlookup",
                "sum function",
                "apply formula",
                "built in function",
            ],
        },
        title="Execute Excel Function",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    function_name: str = Field(
        ...,
        title="Function Name",
        description="Excel function name (e.g., 'vlookup', 'sum', 'pmt')",
        json_schema_extra={"ui:placeholder": "sum"},
    )
    parameters: str = Field(
        ...,
        title="Function Parameters (JSON Array)",
        description="Function arguments as JSON array (e.g., [[1,2,3]] for SUM)",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


# ============================================================================
# Config Models - Worksheet Operations (6 operations)
# ============================================================================


class ExcelListWorksheetsConfig(BaseModel):
    """List all worksheets in a workbook"""

    operation: Literal["list_workbook_worksheets"] = Field(
        "list_workbook_worksheets",
        json_schema_extra={
            "const": "list_workbook_worksheets",
            "ui:hidden": True,
            "x-category": "Worksheet",
            "x-is-trigger": False,
            "x-display-name": "List Workbook Worksheets",
            "x-keywords": [
                "all worksheets",
                "list sheets",
                "show tabs",
                "worksheet names",
            ],
        },
        title="List Workbook Worksheets",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )


class ExcelGetWorksheetConfig(BaseModel):
    """Get worksheet details by name"""

    operation: Literal["get_worksheet"] = Field(
        "get_worksheet",
        json_schema_extra={
            "const": "get_worksheet",
            "ui:hidden": True,
            "x-category": "Worksheet",
            "x-is-trigger": False,
            "x-display-name": "Get Worksheet",
            "x-keywords": [
                "worksheet details",
                "sheet by name",
                "open sheet",
                "single worksheet",
            ],
        },
        title="Get Worksheet",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )


class ExcelAddWorksheetConfig(BaseModel):
    """Add a new worksheet to the workbook"""

    operation: Literal["add_worksheet"] = Field(
        "add_worksheet",
        json_schema_extra={
            "const": "add_worksheet",
            "ui:hidden": True,
            "x-category": "Worksheet",
            "x-is-trigger": False,
            "x-display-name": "Add Worksheet",
            "x-keywords": [
                "new worksheet",
                "create sheet",
                "new tab",
                "insert worksheet",
            ],
            "x-creates-resource": True,
            "x-resource-type": "excel_worksheet",
            "x-resource-id-path": "data.name",
        },
        title="Add Worksheet",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet Name",
        description="Name for the new worksheet",
        json_schema_extra={"ui:placeholder": "NewSheet"},
    )


class ExcelUpdateWorksheetConfig(BaseModel):
    """Update worksheet properties (name, visibility, position)"""

    operation: Literal["update_worksheet"] = Field(
        "update_worksheet",
        json_schema_extra={
            "const": "update_worksheet",
            "ui:hidden": True,
            "x-category": "Worksheet",
            "x-is-trigger": False,
            "x-display-name": "Update Worksheet",
            "x-keywords": [
                "rename sheet",
                "hide worksheet",
                "move tab",
                "reorder sheet",
                "worksheet properties",
            ],
        },
        title="Update Worksheet",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Current Worksheet",
        description="Select the worksheet to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    new_name: Optional[str] = Field(
        None,
        title="New Name (Optional)",
        description="New name for the worksheet (leave empty to keep current name)",
    )
    visible: Optional[bool] = Field(
        None,
        title="Visible (Optional)",
        description="Set worksheet visibility (true/false)",
    )
    position: Optional[int] = Field(
        None,
        title="Position (Optional)",
        description="Zero-based position of the worksheet",
    )


class ExcelDeleteWorksheetConfig(BaseModel):
    """Delete a worksheet from the workbook"""

    operation: Literal["delete_worksheet"] = Field(
        "delete_worksheet",
        json_schema_extra={
            "const": "delete_worksheet",
            "ui:hidden": True,
            "x-category": "Worksheet",
            "x-is-trigger": False,
            "x-display-name": "Delete Worksheet",
            "x-keywords": [
                "remove worksheet",
                "delete sheet",
                "drop tab",
                "trash worksheet",
            ],
        },
        title="Delete Worksheet",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select the worksheet to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )


class ExcelGetUsedRangeConfig(BaseModel):
    """Get the used range of a worksheet (all cells with data)"""

    operation: Literal["get_worksheet_used_range"] = Field(
        "get_worksheet_used_range",
        json_schema_extra={
            "const": "get_worksheet_used_range",
            "ui:hidden": True,
            "x-category": "Worksheet",
            "x-is-trigger": False,
            "x-display-name": "Get Worksheet Used Range",
            "x-keywords": [
                "used range",
                "data extent",
                "occupied cells",
                "filled area",
                "bounds of data",
            ],
        },
        title="Get Worksheet Used Range",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    values_only: bool = Field(
        False,
        title="Values Only",
        description="If true, return only values. If false, include formulas and formatting.",
    )


# ============================================================================
# Config Models - Range Operations (9 operations)
# ============================================================================


class ExcelGetRangeConfig(BaseModel):
    """Get data from a specific cell range"""

    operation: Literal["get_range_values"] = Field(
        "get_range_values",
        json_schema_extra={
            "const": "get_range_values",
            "ui:hidden": True,
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Get Range Values",
            "x-keywords": [
                "read cells",
                "read range",
                "fetch cell data",
                "get cell values",
                "pull range",
            ],
        },
        title="Get Range Values",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Cell range (e.g., 'A1:D10', 'A1', 'A:A')",
        json_schema_extra={"ui:placeholder": "A1:D10"},
    )
    values_only: bool = Field(
        False,
        title="Values Only",
        description="If true, return only values. If false, include formulas.",
    )


class ExcelUpdateRangeConfig(BaseModel):
    """Update cell values, formulas, or formatting in a range"""

    operation: Literal["update_range_values"] = Field(
        "update_range_values",
        json_schema_extra={
            "const": "update_range_values",
            "ui:hidden": True,
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Update Range Values",
            "x-keywords": [
                "write cells",
                "set cell values",
                "put data",
                "fill range",
                "enter formulas",
                "write range",
            ],
        },
        title="Update Range Values",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Cell range to update (e.g., 'A1:D10')",
        json_schema_extra={"ui:placeholder": "A1"},
    )
    values: Optional[str] = Field(
        None,
        title="Values (JSON Array)",
        description='2D array of values as JSON (e.g., [["Name", "Age"], ["John", 30]])',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    formulas: Optional[str] = Field(
        None,
        title="Formulas (JSON Array)",
        description='2D array of formulas as JSON (e.g., [["=SUM(A1:A10)"]])',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    number_format: Optional[str] = Field(
        None,
        title="Number Format",
        description="Excel number format code (e.g., '$#,##0.00', '0.00%', 'mm/dd/yyyy')",
    )


class ExcelClearRangeConfig(BaseModel):
    """Clear content, format, or both from a range"""

    operation: Literal["clear_range_contents"] = Field(
        "clear_range_contents",
        json_schema_extra={
            "const": "clear_range_contents",
            "ui:hidden": True,
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Clear Range Contents",
            "x-keywords": [
                "clear cells",
                "empty range",
                "wipe cells",
                "erase contents",
                "clear formatting",
            ],
        },
        title="Clear Range Contents",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Cell range to clear",
        json_schema_extra={"ui:placeholder": "A1:D10"},
    )
    apply_to: str = Field(
        "All",
        title="Clear Type",
        description="What to clear: All, Contents, or Formats",
        json_schema_extra={
            "enum": ["All", "Contents", "Formats"],
            "x-enum-searchable": True,
        },
    )


class ExcelInsertRangeConfig(BaseModel):
    """Insert blank cells and shift existing cells down or right"""

    operation: Literal["insert_blank_cells_in_range"] = Field(
        "insert_blank_cells_in_range",
        json_schema_extra={
            "const": "insert_blank_cells_in_range",
            "ui:hidden": True,
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Insert Blank Cells in Range",
            "x-keywords": [
                "insert cells",
                "shift cells down",
                "shift cells right",
                "add empty cells",
            ],
        },
        title="Insert Blank Cells in Range",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Where to insert cells",
        json_schema_extra={"ui:placeholder": "A1:A10"},
    )
    shift: str = Field(
        "Down",
        title="Shift Direction",
        description="Direction to shift existing cells: Down or Right",
        json_schema_extra={"enum": ["Down", "Right"], "x-enum-searchable": True},
    )


class ExcelDeleteRangeConfig(BaseModel):
    """Delete cells and shift remaining cells up or left"""

    operation: Literal["delete_range_and_shift_cells"] = Field(
        "delete_range_and_shift_cells",
        json_schema_extra={
            "const": "delete_range_and_shift_cells",
            "ui:hidden": True,
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Delete Range and Shift Cells",
            "x-keywords": [
                "delete cells shift",
                "shift cells up",
                "shift cells left",
                "remove cells",
            ],
        },
        title="Delete Range and Shift Cells",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Cells to delete",
        json_schema_extra={"ui:placeholder": "A1:A10"},
    )
    shift: str = Field(
        "Up",
        title="Shift Direction",
        description="Direction to shift remaining cells: Up or Left",
        json_schema_extra={"enum": ["Up", "Left"], "x-enum-searchable": True},
    )


class ExcelMergeRangeConfig(BaseModel):
    """Merge cells into a single region"""

    operation: Literal["merge_range_cells"] = Field(
        "merge_range_cells",
        json_schema_extra={
            "const": "merge_range_cells",
            "ui:hidden": True,
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Merge Range Cells",
            "x-keywords": [
                "merge cells",
                "combine cells",
                "join cells",
                "merge region",
            ],
        },
        title="Merge Range Cells",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Cells to merge (e.g., 'A1:B2')",
        json_schema_extra={"ui:placeholder": "A1:B2"},
    )
    across: bool = Field(
        False,
        title="Merge Across",
        description="If true, merge each row separately. If false, merge all cells.",
    )


class ExcelUnmergeRangeConfig(BaseModel):
    """Unmerge merged cells"""

    operation: Literal["unmerge_range_cells"] = Field(
        "unmerge_range_cells",
        json_schema_extra={
            "const": "unmerge_range_cells",
            "ui:hidden": True,
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Unmerge Range Cells",
            "x-keywords": [
                "unmerge cells",
                "split merged cells",
                "separate cells",
                "undo merge",
            ],
        },
        title="Unmerge Range Cells",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Merged cells to unmerge",
        json_schema_extra={"ui:placeholder": "A1:B2"},
    )


class ExcelSortRangeConfig(BaseModel):
    """Sort a range by column"""

    operation: Literal["sort_range_by_column"] = Field(
        "sort_range_by_column",
        json_schema_extra={
            "const": "sort_range_by_column",
            "ui:hidden": True,
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Sort Range by Column",
            "x-keywords": [
                "sort cells",
                "sort range",
                "order range",
                "arrange cells",
                "sort by column",
            ],
        },
        title="Sort Range by Column",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Range to sort",
        json_schema_extra={"ui:placeholder": "A1:D10"},
    )
    has_headers: bool = Field(
        True,
        title="Has Headers",
        description="If true, first row is treated as headers",
    )
    sort_column_index: int = Field(
        0,
        title="Sort Column Index",
        description="Zero-based column index to sort by (0 = first column)",
    )
    ascending: bool = Field(
        True,
        title="Ascending",
        description="If true, sort A-Z/1-9. If false, sort Z-A/9-1.",
    )


class ExcelFormatRangeConfig(BaseModel):
    """Apply formatting to a range (font, fill, borders, alignment)"""

    operation: Literal["format_range"] = Field(
        "format_range",
        json_schema_extra={
            "const": "format_range",
            "ui:hidden": True,
            "x-category": "Range",
            "x-is-trigger": False,
            "x-display-name": "Format Range",
            "x-keywords": [
                "style cells",
                "font color",
                "fill color",
                "cell borders",
                "bold cells",
                "align cells",
                "background color",
            ],
        },
        title="Format Range",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Cells to format",
        json_schema_extra={"ui:placeholder": "A1:D10"},
    )
    font_bold: Optional[bool] = Field(
        None, title="Font Bold (Optional)", description="Make text bold"
    )
    font_italic: Optional[bool] = Field(
        None, title="Font Italic (Optional)", description="Make text italic"
    )
    font_size: Optional[float] = Field(
        None, title="Font Size (Optional)", description="Font size in points (e.g., 12)"
    )
    font_color: Optional[str] = Field(
        None,
        title="Font Color (Optional)",
        description="Font color in hex format (e.g., '#FF0000' for red)",
        json_schema_extra={"ui:placeholder": "#000000"},
    )
    background_color: Optional[str] = Field(
        None,
        title="Background Color (Optional)",
        description="Cell background color in hex (e.g., '#FFFF00' for yellow)",
        json_schema_extra={"ui:placeholder": "#FFFFFF"},
    )
    horizontal_alignment: Optional[str] = Field(
        None,
        title="Horizontal Alignment (Optional)",
        description="Text horizontal alignment",
        json_schema_extra={
            "enum": [
                "General",
                "Left",
                "Center",
                "Right",
                "Fill",
                "Justify",
                "CenterContinuous",
                "Distributed",
            ],
            "x-enum-searchable": True,
        },
    )
    vertical_alignment: Optional[str] = Field(
        None,
        title="Vertical Alignment (Optional)",
        description="Text vertical alignment",
        json_schema_extra={
            "enum": ["Top", "Center", "Bottom", "Justify", "Distributed"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Config Models - Table Operations (13 operations)
# ============================================================================


class ExcelListTablesConfig(BaseModel):
    """List all tables in the workbook"""

    operation: Literal["list_workbook_tables"] = Field(
        "list_workbook_tables",
        json_schema_extra={
            "const": "list_workbook_tables",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "List Workbook Tables",
            "x-keywords": ["all tables", "list tables", "show tables", "table names"],
        },
        title="List Workbook Tables",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )


class ExcelGetTableConfig(BaseModel):
    """Get table details by name"""

    operation: Literal["get_table"] = Field(
        "get_table",
        json_schema_extra={
            "const": "get_table",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Get Table",
            "x-keywords": [
                "table details",
                "table by name",
                "open table",
                "single table",
            ],
        },
        title="Get Table",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(
        ...,
        title="Table Name",
        description="Name of the table",
        json_schema_extra={"ui:placeholder": "Table1"},
    )


class ExcelAddTableConfig(BaseModel):
    """Create a new table from a range"""

    operation: Literal["create_table_from_range"] = Field(
        "create_table_from_range",
        json_schema_extra={
            "const": "create_table_from_range",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Create Table from Range",
            "x-keywords": [
                "new table",
                "make table",
                "range to table",
                "convert range to table",
                "format as table",
            ],
        },
        title="Create Table from Range",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select worksheet containing the data",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    range_address: str = Field(
        ...,
        title="Range Address",
        description="Range to convert to table (e.g., 'A1:D10')",
        json_schema_extra={"ui:placeholder": "A1:D10"},
    )
    has_headers: bool = Field(
        True,
        title="Has Headers",
        description="If true, first row becomes table headers",
    )
    table_name: Optional[str] = Field(
        None,
        title="Table Name (Optional)",
        description="Name for the table (auto-generated if not provided)",
    )


class ExcelDeleteTableConfig(BaseModel):
    """Delete a table (converts back to range)"""

    operation: Literal["delete_table"] = Field(
        "delete_table",
        json_schema_extra={
            "const": "delete_table",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Delete Table",
            "x-keywords": ["remove table", "drop table", "trash table"],
        },
        title="Delete Table",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to delete"
    )


class ExcelConvertTableToRangeConfig(BaseModel):
    """Convert table to normal range (keeps data, removes table structure)"""

    operation: Literal["convert_table_to_range"] = Field(
        "convert_table_to_range",
        json_schema_extra={
            "const": "convert_table_to_range",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Convert Table to Range",
            "x-keywords": [
                "table to range",
                "unformat table",
                "remove table structure",
                "ungroup table",
            ],
        },
        title="Convert Table to Range",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to convert"
    )


class ExcelListTableRowsConfig(BaseModel):
    """List all rows in a table"""

    operation: Literal["list_table_rows"] = Field(
        "list_table_rows",
        json_schema_extra={
            "const": "list_table_rows",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "List Table Rows",
            "x-keywords": [
                "all table rows",
                "show table rows",
                "table records",
                "read table rows",
            ],
        },
        title="List Table Rows",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table")


class ExcelAddTableRowConfig(BaseModel):
    """Add a row to a table"""

    operation: Literal["add_table_row"] = Field(
        "add_table_row",
        json_schema_extra={
            "const": "add_table_row",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Add Table Row",
            "x-keywords": [
                "new table row",
                "append row",
                "insert table row",
                "add record",
            ],
        },
        title="Add Table Row",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table")
    values: str = Field(
        ...,
        title="Row Values (JSON Array)",
        description='Row data as JSON array (e.g., ["John", 30, "Developer"])',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    index: Optional[int] = Field(
        None,
        title="Insert at Index (Optional)",
        description="Zero-based index to insert row (null = append to end)",
    )


class ExcelDeleteTableRowConfig(BaseModel):
    """Delete a row from a table by index"""

    operation: Literal["delete_table_row"] = Field(
        "delete_table_row",
        json_schema_extra={
            "const": "delete_table_row",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Delete Table Row",
            "x-keywords": [
                "remove table row",
                "drop row by index",
                "delete record",
                "trash table row",
            ],
        },
        title="Delete Table Row",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table")
    index: int = Field(
        ...,
        title="Row Index",
        description="Zero-based index of the row to delete (0 = first data row)",
    )


class ExcelListTableColumnsConfig(BaseModel):
    """List all columns in a table"""

    operation: Literal["list_table_columns"] = Field(
        "list_table_columns",
        json_schema_extra={
            "const": "list_table_columns",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "List Table Columns",
            "x-keywords": [
                "all table columns",
                "show table columns",
                "table fields",
                "read table columns",
            ],
        },
        title="List Table Columns",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table")


class ExcelAddTableColumnConfig(BaseModel):
    """Add a column to a table"""

    operation: Literal["add_table_column"] = Field(
        "add_table_column",
        json_schema_extra={
            "const": "add_table_column",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Add Table Column",
            "x-keywords": [
                "new table column",
                "append column",
                "insert table column",
                "add field",
            ],
        },
        title="Add Table Column",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table")
    column_name: str = Field(
        ...,
        title="Column Name",
        description="Name for the new column",
        json_schema_extra={"ui:placeholder": "New Column"},
    )
    values: Optional[str] = Field(
        None,
        title="Column Values (JSON Array)",
        description="Optional initial values as JSON array (e.g., [100, 200, 300])",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    index: Optional[int] = Field(
        None,
        title="Insert at Index (Optional)",
        description="Zero-based index to insert column (null = append to end)",
    )


class ExcelDeleteTableColumnConfig(BaseModel):
    """Delete a column from a table"""

    operation: Literal["delete_table_column"] = Field(
        "delete_table_column",
        json_schema_extra={
            "const": "delete_table_column",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Delete Table Column",
            "x-keywords": [
                "remove table column",
                "drop column",
                "delete field",
                "trash table column",
            ],
        },
        title="Delete Table Column",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table")
    column_name: str = Field(
        ..., title="Column Name", description="Name of the column to delete"
    )


class ExcelSortTableConfig(BaseModel):
    """Sort a table by column"""

    operation: Literal["sort_table_by_column"] = Field(
        "sort_table_by_column",
        json_schema_extra={
            "const": "sort_table_by_column",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Sort Table by Column",
            "x-keywords": [
                "sort table",
                "order table rows",
                "arrange table",
                "sort table by column",
            ],
        },
        title="Sort Table by Column",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to sort"
    )
    column_name: str = Field(..., title="Column Name", description="Column to sort by")
    ascending: bool = Field(
        True, title="Ascending", description="If true, sort A-Z. If false, sort Z-A."
    )


class ExcelApplyFilterConfig(BaseModel):
    """Apply auto-filter to a table column"""

    operation: Literal["apply_table_column_filter"] = Field(
        "apply_table_column_filter",
        json_schema_extra={
            "const": "apply_table_column_filter",
            "ui:hidden": True,
            "x-category": "Filter",
            "x-is-trigger": False,
            "x-display-name": "Apply Table Column Filter",
            "x-keywords": [
                "filter table column",
                "auto filter",
                "add column filter",
                "set table filter",
            ],
        },
        title="Apply Table Column Filter",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table")
    column_name: str = Field(..., title="Column Name", description="Column to filter")
    filter_values: str = Field(
        ...,
        title="Filter Values (JSON Array)",
        description='Values to show (e.g., ["Active", "Pending"])',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class ExcelClearFilterConfig(BaseModel):
    """Clear filter from a table column"""

    operation: Literal["clear_table_column_filter"] = Field(
        "clear_table_column_filter",
        json_schema_extra={
            "const": "clear_table_column_filter",
            "ui:hidden": True,
            "x-category": "Filter",
            "x-is-trigger": False,
            "x-display-name": "Clear Table Column Filter",
            "x-keywords": [
                "remove table filter",
                "clear column filter",
                "reset filter",
                "unfilter table",
            ],
        },
        title="Clear Table Column Filter",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table")
    column_name: str = Field(
        ..., title="Column Name", description="Column to clear filter from"
    )


# ============================================================================
# Config Models - Chart Operations (6 operations)
# ============================================================================


class ExcelListChartsConfig(BaseModel):
    """List all charts in a worksheet"""

    operation: Literal["list_worksheet_charts"] = Field(
        "list_worksheet_charts",
        json_schema_extra={
            "const": "list_worksheet_charts",
            "ui:hidden": True,
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "List Worksheet Charts",
            "x-keywords": ["all charts", "list charts", "show charts", "chart names"],
        },
        title="List Worksheet Charts",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )


class ExcelGetChartConfig(BaseModel):
    """Get chart details by name"""

    operation: Literal["get_chart"] = Field(
        "get_chart",
        json_schema_extra={
            "const": "get_chart",
            "ui:hidden": True,
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Get Chart",
            "x-keywords": [
                "chart details",
                "chart by name",
                "open chart",
                "single chart",
            ],
        },
        title="Get Chart",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    chart_name: str = Field(
        ...,
        title="Chart Name",
        description="Name of the chart",
        json_schema_extra={"ui:placeholder": "Chart1"},
    )


class ExcelAddChartConfig(BaseModel):
    """Create a new chart from data range"""

    operation: Literal["create_chart"] = Field(
        "create_chart",
        json_schema_extra={
            "const": "create_chart",
            "ui:hidden": True,
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Create Chart",
            "x-keywords": [
                "new chart",
                "make chart",
                "add graph",
                "plot data",
                "insert chart",
            ],
        },
        title="Create Chart",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select worksheet to create chart in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    chart_type: str = Field(
        ...,
        title="Chart Type",
        description="Type of chart to create",
        json_schema_extra={
            "enum": [
                "ColumnClustered",
                "ColumnStacked",
                "Line",
                "Pie",
                "XYScatter",
                "Area",
                "Bar",
                "Doughnut",
            ],
            "enumNames": [
                "Column (Clustered)",
                "Column (Stacked)",
                "Line",
                "Pie",
                "Scatter",
                "Area",
                "Bar",
                "Doughnut",
            ],
            "x-enum-searchable": True,
        },
    )
    source_data_range: str = Field(
        ...,
        title="Source Data Range",
        description="Range containing chart data (e.g., 'A1:B10')",
        json_schema_extra={"ui:placeholder": "A1:B10"},
    )
    series_by: str = Field(
        "Auto",
        title="Series By",
        description="Organize series by rows or columns",
        json_schema_extra={
            "enum": ["Auto", "Columns", "Rows"],
            "x-enum-searchable": True,
        },
    )


class ExcelUpdateChartConfig(BaseModel):
    """Update chart properties (title, size, position)"""

    operation: Literal["update_chart"] = Field(
        "update_chart",
        json_schema_extra={
            "const": "update_chart",
            "ui:hidden": True,
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Update Chart",
            "x-keywords": [
                "edit chart",
                "chart title",
                "resize chart",
                "move chart",
                "chart properties",
            ],
        },
        title="Update Chart",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    chart_name: str = Field(
        ..., title="Chart Name", description="Name of the chart to update"
    )
    new_name: Optional[str] = Field(
        None, title="New Name (Optional)", description="New name for the chart"
    )
    title: Optional[str] = Field(
        None,
        title="Chart Title (Optional)",
        description="Title to display on the chart",
    )
    height: Optional[float] = Field(
        None, title="Height (Optional)", description="Chart height in points"
    )
    width: Optional[float] = Field(
        None, title="Width (Optional)", description="Chart width in points"
    )


class ExcelDeleteChartConfig(BaseModel):
    """Delete a chart from worksheet"""

    operation: Literal["delete_chart"] = Field(
        "delete_chart",
        json_schema_extra={
            "const": "delete_chart",
            "ui:hidden": True,
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Delete Chart",
            "x-keywords": ["remove chart", "drop chart", "trash chart", "delete graph"],
        },
        title="Delete Chart",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    chart_name: str = Field(
        ..., title="Chart Name", description="Name of the chart to delete"
    )


class ExcelGetChartImageConfig(BaseModel):
    """Get chart as base64-encoded PNG image"""

    operation: Literal["get_chart_image"] = Field(
        "get_chart_image",
        json_schema_extra={
            "const": "get_chart_image",
            "ui:hidden": True,
            "x-category": "Chart",
            "x-is-trigger": False,
            "x-display-name": "Get Chart Image",
            "x-keywords": [
                "chart as image",
                "export chart png",
                "chart screenshot",
                "render chart",
                "chart picture",
            ],
        },
        title="Get Chart Image",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    worksheet_name: str = Field(
        ...,
        title="Worksheet",
        description="Select a worksheet/tab within the workbook",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "worksheet_name",
                "depends_on": "workbook_id",
                "placeholder": "Select a worksheet...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter worksheet name",
            },
            "x-resource-type": "excel_worksheet",
        },
    )
    chart_name: str = Field(..., title="Chart Name", description="Name of the chart")
    width: Optional[int] = Field(
        None,
        title="Width (Optional)",
        description="Image width in pixels (maintains aspect ratio if height not set)",
    )
    height: Optional[int] = Field(
        None, title="Height (Optional)", description="Image height in pixels"
    )


# ============================================================================
# Config Models - Named Items Operations (3 operations)
# ============================================================================


class ExcelListNamedItemsConfig(BaseModel):
    """List all named ranges and items in the workbook"""

    operation: Literal["list_named_items"] = Field(
        "list_named_items",
        json_schema_extra={
            "const": "list_named_items",
            "ui:hidden": True,
            "x-category": "Named Item",
            "x-is-trigger": False,
            "x-display-name": "List Named Items",
            "x-keywords": [
                "all named ranges",
                "list named items",
                "show defined names",
                "named range names",
            ],
        },
        title="List Named Items",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )


class ExcelGetNamedItemConfig(BaseModel):
    """Get value of a named range or item"""

    operation: Literal["get_named_item"] = Field(
        "get_named_item",
        json_schema_extra={
            "const": "get_named_item",
            "ui:hidden": True,
            "x-category": "Named Item",
            "x-is-trigger": False,
            "x-display-name": "Get Named Item",
            "x-keywords": [
                "named range value",
                "read defined name",
                "get named item",
                "single named range",
            ],
        },
        title="Get Named Item",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    name: str = Field(
        ...,
        title="Name",
        description="Name of the named range or item",
        json_schema_extra={"ui:placeholder": "SalesTotal"},
    )


class ExcelAddNamedItemConfig(BaseModel):
    """Create a named range or constant"""

    operation: Literal["create_named_item"] = Field(
        "create_named_item",
        json_schema_extra={
            "const": "create_named_item",
            "ui:hidden": True,
            "x-category": "Named Item",
            "x-is-trigger": False,
            "x-display-name": "Create Named Item",
            "x-keywords": [
                "new named range",
                "define name",
                "name a range",
                "add named constant",
            ],
        },
        title="Create Named Item",
    )
    workbook_id: str = Field(
        ...,
        title="Workbook",
        description="Select an Excel workbook from your OneDrive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workbook_id",
                "placeholder": "Select a workbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste workbook/file ID",
            },
            "x-resource-type": "excel_workbook",
        },
    )
    name: str = Field(
        ...,
        title="Name",
        description="Name for the item (e.g., 'SalesTotal')",
        json_schema_extra={"ui:placeholder": "MyRange"},
    )
    reference: str = Field(
        ...,
        title="Reference",
        description="Cell reference or formula (e.g., 'Sheet1!$A$1:$A$10' or '=100')",
        json_schema_extra={"ui:placeholder": "Sheet1!$A$1:$A$10"},
    )
    comment: Optional[str] = Field(
        None,
        title="Comment (Optional)",
        description="Optional description of the named item",
    )


# ============================================================================
# Discriminated Union of All Excel Operations (43 total)
# ============================================================================

ExcelConfig = Annotated[
    Union[
        # Workbook operations (5)
        ExcelCreateSessionConfig,
        ExcelCloseSessionConfig,
        ExcelRefreshSessionConfig,
        ExcelCalculateConfig,
        ExcelExecuteFunctionConfig,
        # Worksheet operations (6)
        ExcelListWorksheetsConfig,
        ExcelGetWorksheetConfig,
        ExcelAddWorksheetConfig,
        ExcelUpdateWorksheetConfig,
        ExcelDeleteWorksheetConfig,
        ExcelGetUsedRangeConfig,
        # Range operations (9)
        ExcelGetRangeConfig,
        ExcelUpdateRangeConfig,
        ExcelClearRangeConfig,
        ExcelInsertRangeConfig,
        ExcelDeleteRangeConfig,
        ExcelMergeRangeConfig,
        ExcelUnmergeRangeConfig,
        ExcelSortRangeConfig,
        ExcelFormatRangeConfig,
        # Table operations (13)
        ExcelListTablesConfig,
        ExcelGetTableConfig,
        ExcelAddTableConfig,
        ExcelDeleteTableConfig,
        ExcelConvertTableToRangeConfig,
        ExcelListTableRowsConfig,
        ExcelAddTableRowConfig,
        ExcelDeleteTableRowConfig,
        ExcelListTableColumnsConfig,
        ExcelAddTableColumnConfig,
        ExcelDeleteTableColumnConfig,
        ExcelSortTableConfig,
        ExcelApplyFilterConfig,
        ExcelClearFilterConfig,
        # Chart operations (6)
        ExcelListChartsConfig,
        ExcelGetChartConfig,
        ExcelAddChartConfig,
        ExcelUpdateChartConfig,
        ExcelDeleteChartConfig,
        ExcelGetChartImageConfig,
        # Named items operations (3)
        ExcelListNamedItemsConfig,
        ExcelGetNamedItemConfig,
        ExcelAddNamedItemConfig,
    ],
    Discriminator("operation"),
]


class ExcelNodeConfig(NodeConfig[ExcelConfig, ExcelOAuthCredential]):
    """Full configuration for Excel node including credentials."""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class ExcelNode(WorkflowNode):
    """
    Excel automation node using Microsoft Graph API.

    Provides complete Excel workbook automation with 43 operations across 6 categories:
    - Workbook: Sessions, calculations, functions
    - Worksheets: List, add, update, delete, ranges
    - Ranges: Read, write, clear, insert, delete, merge, format, sort
    - Tables: Full table management, rows, columns, sorting, filtering
    - Charts: Create, update, delete, export as image
    - Named Items: Named ranges and constants

    Authentication: Uses centralized Microsoft OAuth (Files.ReadWrite.All scope)
    API Endpoint: https://graph.microsoft.com/v1.0
    """

    edit_examples = [
        "Calculate all formulas in the Budget sheet and return results",
        "List all worksheets in the Q4_Financials.xlsx workbook",
        "Update range A1:C10 with new sales data and recalculate totals",
        'Create a new worksheet named "Dashboard" in the active workbook',
        "Add a pivot table summarizing revenue by region and product",
        "Clear all values in range B2:D100 but preserve formatting",
        "Insert 5 rows after row 15 for new employee records",
    ]

    #: OAuth scope requirements per operation (nodes/scopes/microsoft.py).
    scope_registry = EXCEL_SCOPES
    connection_evidence = ConnectionEvidence(
        field="workbook_id",
        noun="workbooks",
    )

    @classmethod
    def get_config_model(cls):
        return ExcelNodeConfig

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
        to populate dropdowns (e.g., list of workbooks from OneDrive).

        Args:
            field_name: Name of the field needing options (e.g., "workbook_id")
            credential_data: Decrypted OAuth credential data
            context: Additional context (e.g., currently selected workbook_id for worksheet_name)
            page_token: Optional token for pagination
            search: Optional search term to filter results

        Returns:
            Dict with 'options' (list of option dicts) and 'next_page_token' (optional)
        """
        logger.info(
            f"[ExcelNode] load_field_options called: field={field_name}, page_token={page_token}"
        )

        if field_name == "workbook_id":
            return await cls._list_workbooks(credential_data, page_token, search=search)
        elif field_name == "worksheet_name":
            workbook_id = (context or {}).get("workbook_id")
            logger.info(
                f"[ExcelNode] load_field_options for worksheet_name, context={context}, workbook_id={workbook_id}"
            )
            if workbook_id:
                options = await cls._list_worksheets(
                    credential_data, workbook_id, search=search
                )
                return {"options": options, "next_page_token": None}
            else:
                logger.warning(
                    f"[ExcelNode] No workbook_id in context for worksheet_name field"
                )

        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_workbooks(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all Excel workbooks accessible to the user from OneDrive with pagination.

        Uses Microsoft Graph Drive API to find Excel files (.xlsx, .xlsm, .xlsb).

        Returns:
            Dict with 'options' (list of workbook options) and 'next_page_token'
        """
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Microsoft account to load Excel workbooks",
        )

        # Search for Excel files in OneDrive
        # Using Drive search API to find .xlsx files; if a search term is
        # provided, pass it to the upstream `q` parameter so the API narrows
        # results server-side. Pagination still works within filtered results.
        query = search if search else ".xlsx"
        escaped_query = query.replace("'", "''")
        url = f"https://graph.microsoft.com/v1.0/me/drive/search(q='{escaped_query}')"

        params = {
            "$top": 100,
            "$orderby": "lastModifiedDateTime desc",
            "$select": "id,name,lastModifiedDateTime,createdBy",
        }

        if page_token:
            params["$skiptoken"] = page_token

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.text else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                files = data.get("value", [])
                next_link = data.get("@odata.nextLink")

                # Extract skiptoken from nextLink if present
                next_page_token = None
                if next_link and "$skiptoken=" in next_link:
                    next_page_token = next_link.split("$skiptoken=")[1].split("&")[0]

                options = []
                for file in files:
                    # Only include actual Excel files (filter out folders)
                    if file.get("name", "").endswith((".xlsx", ".xlsm", ".xlsb")):
                        options.append(
                            {
                                "value": file["id"],
                                "label": file["name"],
                                "metadata": {
                                    "lastModifiedDateTime": file.get(
                                        "lastModifiedDateTime"
                                    ),
                                    "createdBy": file.get("createdBy", {})
                                    .get("user", {})
                                    .get("displayName", ""),
                                },
                            }
                        )

                logger.info(
                    f"[ExcelNode] Found {len(options)} Excel workbooks, next_page_token={next_page_token is not None}"
                )
                return {"options": options, "next_page_token": next_page_token}

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to load Excel workbooks: {e}") from e

    @classmethod
    async def _list_worksheets(
        cls,
        credential_data: Dict[str, Any],
        workbook_id: str,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List all worksheets/tabs within a specific Excel workbook.

        Args:
            credential_data: OAuth credentials
            workbook_id: The OneDrive file ID of the workbook
            search: Accepted for uniform dispatch but unused — worksheet
                lists are small enough to render unfiltered.

        Returns:
            List of option dicts with 'value' and 'label' keys
        """
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Microsoft account to load worksheets",
        )

        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{workbook_id}/workbook/worksheets"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.text else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                worksheets = data.get("value", [])

                options = []
                for sheet in worksheets:
                    options.append(
                        {
                            "value": sheet.get("name", ""),
                            "label": sheet.get("name", ""),
                            "metadata": {
                                "id": sheet.get("id", ""),
                                "position": sheet.get("position", 0),
                                "visibility": sheet.get("visibility", "visible"),
                            },
                        }
                    )

                logger.info(
                    f"[ExcelNode] Found {len(options)} worksheets in workbook {workbook_id}"
                )
                return options

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to load Excel worksheets: {e}") from e

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="microsoft",
        )

    async def _ensure_fresh_token(self, credentials: ExcelOAuthCredential) -> str:
        """Return a valid Excel access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="microsoft",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Route to the appropriate operation handler based on action"""
        config = self.config
        if not config or not isinstance(config, ExcelNodeConfig):
            raise ValueError("Excel configuration required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Excel credentials required. Connect your Microsoft account in the credentials tab."
            )

        # Auto-refresh token if expired
        access_token = await self._ensure_fresh_token(credentials)

        op_config = config.config
        action = op_config.operation

        # Route to operation handler
        handlers = {
            # Workbook operations
            "create_workbook_session": self._create_session,
            "close_workbook_session": self._close_session,
            "refresh_workbook_session": self._refresh_session,
            "recalculate_workbook": self._calculate,
            "execute_excel_function": self._execute_function,
            # Worksheet operations
            "list_workbook_worksheets": self._execute_list_worksheets,
            "get_worksheet": self._get_worksheet,
            "add_worksheet": self._add_worksheet,
            "update_worksheet": self._update_worksheet,
            "delete_worksheet": self._delete_worksheet,
            "get_worksheet_used_range": self._get_used_range,
            # Range operations
            "get_range_values": self._get_range,
            "update_range_values": self._update_range,
            "clear_range_contents": self._clear_range,
            "insert_blank_cells_in_range": self._insert_range,
            "delete_range_and_shift_cells": self._delete_range,
            "merge_range_cells": self._merge_range,
            "unmerge_range_cells": self._unmerge_range,
            "sort_range_by_column": self._sort_range,
            "format_range": self._format_range,
            # Table operations
            "list_workbook_tables": self._list_tables,
            "get_table": self._get_table,
            "create_table_from_range": self._add_table,
            "delete_table": self._delete_table,
            "convert_table_to_range": self._convert_table_to_range,
            "list_table_rows": self._list_table_rows,
            "add_table_row": self._add_table_row,
            "delete_table_row": self._delete_table_row,
            "list_table_columns": self._list_table_columns,
            "add_table_column": self._add_table_column,
            "delete_table_column": self._delete_table_column,
            "sort_table_by_column": self._sort_table,
            "apply_table_column_filter": self._apply_filter,
            "clear_table_column_filter": self._clear_filter,
            # Chart operations
            "list_worksheet_charts": self._list_charts,
            "get_chart": self._get_chart,
            "create_chart": self._add_chart,
            "update_chart": self._update_chart,
            "delete_chart": self._delete_chart,
            "get_chart_image": self._get_chart_image,
            # Named items operations
            "list_named_items": self._list_named_items,
            "get_named_item": self._get_named_item,
            "create_named_item": self._add_named_item,
        }

        handler = handlers.get(action)
        if not handler:
            return {
                "status": "error",
                "action": action,
                "message": f"Unknown action: {action}",
            }

        return await handler(op_config, access_token)

    # ========================================================================
    # Workbook Operations
    # ========================================================================

    async def _create_session(
        self, config: ExcelCreateSessionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a persistent or non-persistent workbook session"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/createSession"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"persistChanges": config.persist_changes},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "create_workbook_session",
                    "message": f"Failed to create session: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "create_workbook_session",
                "data": {
                    "session_id": data.get("id"),
                    "persist_changes": data.get("persistChanges"),
                    "message": "Session created successfully. Use session_id in subsequent requests.",
                },
            }

    async def _close_session(
        self, config: ExcelCloseSessionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Close a workbook session"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/closeSession"
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "workbook-session-id": config.session_id,
                },
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "close_workbook_session",
                    "message": f"Failed to close session: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "close_workbook_session",
                "message": "Session closed successfully",
            }

    async def _refresh_session(
        self, config: ExcelRefreshSessionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Refresh a workbook session"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/refreshSession"
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "workbook-session-id": config.session_id,
                },
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "refresh_workbook_session",
                    "message": f"Failed to refresh session: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "refresh_workbook_session",
                "message": "Session refreshed successfully",
            }

    async def _calculate(
        self, config: ExcelCalculateConfig, access_token: str
    ) -> Dict[str, Any]:
        """Recalculate all formulas in the workbook"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/application/calculate"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"calculationType": config.calculation_type},
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "recalculate_workbook",
                    "message": f"Failed to calculate: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "recalculate_workbook",
                "message": f"Workbook recalculated ({config.calculation_type})",
            }

    async def _execute_function(
        self, config: ExcelExecuteFunctionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Execute a built-in Excel function"""
        try:
            parameters = json.loads(config.parameters)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "execute_excel_function",
                "message": f"Invalid JSON in parameters: {str(e)}",
            }

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/functions/{config.function_name}"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=parameters,
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "execute_excel_function",
                    "message": f"Failed to execute function: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "execute_excel_function",
                "data": {"function": config.function_name, "result": data.get("value")},
            }

    # ========================================================================
    # Worksheet Operations
    # ========================================================================

    async def _execute_list_worksheets(
        self, config: ExcelListWorksheetsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all worksheets in the workbook"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_workbook_worksheets",
                    "message": f"Failed to list worksheets: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            worksheets = data.get("value", [])
            return {
                "status": "success",
                "action": "list_workbook_worksheets",
                "data": {
                    "count": len(worksheets),
                    "worksheets": [
                        {
                            "id": ws.get("id"),
                            "name": ws.get("name"),
                            "position": ws.get("position"),
                            "visibility": ws.get("visibility"),
                        }
                        for ws in worksheets
                    ],
                },
            }

    async def _get_worksheet(
        self, config: ExcelGetWorksheetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get worksheet details"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_worksheet",
                    "message": f"Failed to get worksheet: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_worksheet",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "position": data.get("position"),
                    "visibility": data.get("visibility"),
                },
            }

    async def _add_worksheet(
        self, config: ExcelAddWorksheetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Add a new worksheet"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/add"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"name": config.worksheet_name},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "add_worksheet",
                    "message": f"Failed to add worksheet: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "add_worksheet",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "position": data.get("position"),
                },
            }

    async def _update_worksheet(
        self, config: ExcelUpdateWorksheetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update worksheet properties"""
        update_data = {}
        if config.new_name:
            update_data["name"] = config.new_name
        if config.visible is not None:
            update_data["visibility"] = "Visible" if config.visible else "Hidden"
        if config.position is not None:
            update_data["position"] = config.position

        if not update_data:
            return {
                "status": "error",
                "action": "update_worksheet",
                "message": "No updates provided",
            }

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}"
            response = await client.patch(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=update_data,
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "update_worksheet",
                    "message": f"Failed to update worksheet: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "update_worksheet",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "position": data.get("position"),
                    "visibility": data.get("visibility"),
                },
            }

    async def _delete_worksheet(
        self, config: ExcelDeleteWorksheetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a worksheet"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}"
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "delete_worksheet",
                    "message": f"Failed to delete worksheet: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "delete_worksheet",
                "message": f"Worksheet '{config.worksheet_name}' deleted successfully",
            }

    async def _get_used_range(
        self, config: ExcelGetUsedRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get the used range of a worksheet"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/usedRange"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_worksheet_used_range",
                    "message": f"Failed to get used range: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            result = {
                "status": "success",
                "action": "get_worksheet_used_range",
                "data": {
                    "address": data.get("address"),
                    "row_count": data.get("rowCount"),
                    "column_count": data.get("columnCount"),
                },
            }

            if config.values_only:
                result["data"]["values"] = data.get("values", [])
            else:
                result["data"]["values"] = data.get("values", [])
                result["data"]["formulas"] = data.get("formulas", [])
                result["data"]["number_format"] = data.get("numberFormat", [])

            return result

    # ========================================================================
    # Range Operations
    # ========================================================================

    async def _get_range(
        self, config: ExcelGetRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get data from a specific range"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/range(address='{config.range_address}')"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_range_values",
                    "message": f"Failed to get range: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            result = {
                "status": "success",
                "action": "get_range_values",
                "data": {
                    "address": data.get("address"),
                    "row_count": data.get("rowCount"),
                    "column_count": data.get("columnCount"),
                    "values": data.get("values", []),
                },
            }

            if not config.values_only:
                result["data"]["formulas"] = data.get("formulas", [])
                result["data"]["number_format"] = data.get("numberFormat", [])

            return result

    async def _update_range(
        self, config: ExcelUpdateRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update range values, formulas, or formatting"""
        update_data = {}

        if config.values:
            try:
                update_data["values"] = json.loads(config.values)
            except json.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "update_range_values",
                    "message": f"Invalid JSON in values: {str(e)}",
                }

        if config.formulas:
            try:
                update_data["formulas"] = json.loads(config.formulas)
            except json.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "update_range_values",
                    "message": f"Invalid JSON in formulas: {str(e)}",
                }

        if config.number_format:
            update_data["numberFormat"] = config.number_format

        if not update_data:
            return {
                "status": "error",
                "action": "update_range_values",
                "message": "No updates provided",
            }

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/range(address='{config.range_address}')"
            response = await client.patch(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=update_data,
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "update_range_values",
                    "message": f"Failed to update range: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "update_range_values",
                "data": {
                    "address": data.get("address"),
                    "row_count": data.get("rowCount"),
                    "column_count": data.get("columnCount"),
                },
            }

    async def _clear_range(
        self, config: ExcelClearRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Clear content, format, or both from a range"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/range(address='{config.range_address}')/clear"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"applyTo": config.apply_to},
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "clear_range_contents",
                    "message": f"Failed to clear range: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "clear_range_contents",
                "message": f"Range cleared ({config.apply_to})",
            }

    async def _insert_range(
        self, config: ExcelInsertRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Insert blank cells and shift existing cells"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/range(address='{config.range_address}')/insert"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"shift": config.shift},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "insert_blank_cells_in_range",
                    "message": f"Failed to insert range: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "insert_blank_cells_in_range",
                "data": {"new_address": data.get("address"), "shift": config.shift},
            }

    async def _delete_range(
        self, config: ExcelDeleteRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete cells and shift remaining cells"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/range(address='{config.range_address}')/delete"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"shift": config.shift},
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "delete_range_and_shift_cells",
                    "message": f"Failed to delete range: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "delete_range_and_shift_cells",
                "message": f"Range deleted (shift {config.shift})",
            }

    async def _merge_range(
        self, config: ExcelMergeRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Merge cells into a single region"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/range(address='{config.range_address}')/merge"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"across": config.across},
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "merge_range_cells",
                    "message": f"Failed to merge range: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "merge_range_cells",
                "message": "Cells merged successfully",
            }

    async def _unmerge_range(
        self, config: ExcelUnmergeRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Unmerge merged cells"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/range(address='{config.range_address}')/unmerge"
            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "unmerge_range_cells",
                    "message": f"Failed to unmerge range: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "unmerge_range_cells",
                "message": "Cells unmerged successfully",
            }

    async def _sort_range(
        self, config: ExcelSortRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Sort a range by column"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/range(address='{config.range_address}')/sort/apply"

            sort_fields = [
                {"key": config.sort_column_index, "ascending": config.ascending}
            ]

            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"fields": sort_fields, "hasHeaders": config.has_headers},
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "sort_range_by_column",
                    "message": f"Failed to sort range: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "sort_range_by_column",
                "message": f"Range sorted by column {config.sort_column_index} ({'ascending' if config.ascending else 'descending'})",
            }

    async def _format_range(
        self, config: ExcelFormatRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Apply formatting to a range"""
        # Build format update object
        format_updates = {}

        # Font formatting
        if any(
            [
                config.font_bold is not None,
                config.font_italic is not None,
                config.font_size is not None,
                config.font_color is not None,
            ]
        ):
            font_format = {}
            if config.font_bold is not None:
                font_format["bold"] = config.font_bold
            if config.font_italic is not None:
                font_format["italic"] = config.font_italic
            if config.font_size is not None:
                font_format["size"] = config.font_size
            if config.font_color is not None:
                font_format["color"] = config.font_color
            format_updates["font"] = font_format

        # Fill (background) formatting
        if config.background_color is not None:
            format_updates["fill"] = {"color": config.background_color}

        # Alignment formatting
        if (
            config.horizontal_alignment is not None
            or config.vertical_alignment is not None
        ):
            alignment = {}
            if config.horizontal_alignment is not None:
                alignment["horizontal"] = config.horizontal_alignment
            if config.vertical_alignment is not None:
                alignment["vertical"] = config.vertical_alignment
            format_updates["alignment"] = alignment

        if not format_updates:
            return {
                "status": "error",
                "action": "format_range",
                "message": "No formatting options provided",
            }

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/range(address='{config.range_address}')/format"
            response = await client.patch(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=format_updates,
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "format_range",
                    "message": f"Failed to format range: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "format_range",
                "message": "Range formatted successfully",
            }

    # ========================================================================
    # Table Operations (13 operations - implementation continues...)
    # ========================================================================

    async def _list_tables(
        self, config: ExcelListTablesConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all tables in the workbook"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_workbook_tables",
                    "message": f"Failed to list tables: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            tables = data.get("value", [])
            return {
                "status": "success",
                "action": "list_workbook_tables",
                "data": {
                    "count": len(tables),
                    "tables": [
                        {
                            "id": t.get("id"),
                            "name": t.get("name"),
                            "show_headers": t.get("showHeaders"),
                            "show_totals": t.get("showTotals"),
                            "style": t.get("style"),
                        }
                        for t in tables
                    ],
                },
            }

    async def _get_table(
        self, config: ExcelGetTableConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get table details"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_table",
                    "message": f"Failed to get table: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_table",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "show_headers": data.get("showHeaders"),
                    "show_totals": data.get("showTotals"),
                    "style": data.get("style"),
                },
            }

    async def _add_table(
        self, config: ExcelAddTableConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new table from a range"""
        table_data = {
            "address": f"{config.worksheet_name}!{config.range_address}",
            "hasHeaders": config.has_headers,
        }

        if config.table_name:
            table_data["name"] = config.table_name

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/add"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=table_data,
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "create_table_from_range",
                    "message": f"Failed to create table: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "create_table_from_range",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "show_headers": data.get("showHeaders"),
                },
            }

    async def _delete_table(
        self, config: ExcelDeleteTableConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a table"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}"
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "delete_table",
                    "message": f"Failed to delete table: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "delete_table",
                "message": f"Table '{config.table_name}' deleted successfully",
            }

    async def _convert_table_to_range(
        self, config: ExcelConvertTableToRangeConfig, access_token: str
    ) -> Dict[str, Any]:
        """Convert table to normal range"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/convertToRange"
            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "convert_table_to_range",
                    "message": f"Failed to convert table: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "convert_table_to_range",
                "data": {
                    "address": data.get("address"),
                    "message": "Table converted to range successfully",
                },
            }

    async def _list_table_rows(
        self, config: ExcelListTableRowsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all rows in a table"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/rows"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_table_rows",
                    "message": f"Failed to list rows: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            rows = data.get("value", [])
            return {
                "status": "success",
                "action": "list_table_rows",
                "data": {
                    "count": len(rows),
                    "rows": [
                        {
                            "index": row.get("index"),
                            "values": row.get("values", [[]])[0]
                            if row.get("values")
                            else [],
                        }
                        for row in rows
                    ],
                },
            }

    async def _add_table_row(
        self, config: ExcelAddTableRowConfig, access_token: str
    ) -> Dict[str, Any]:
        """Add a row to a table"""
        try:
            values = json.loads(config.values)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "add_table_row",
                "message": f"Invalid JSON in values: {str(e)}",
            }

        row_data = {"values": [values]}  # API expects 2D array
        if config.index is not None:
            row_data["index"] = config.index

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/rows"
            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}, json=row_data
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "add_table_row",
                    "message": f"Failed to add row: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "add_table_row",
                "data": {
                    "index": data.get("index"),
                    "values": data.get("values", [[]])[0] if data.get("values") else [],
                },
            }

    async def _delete_table_row(
        self, config: ExcelDeleteTableRowConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a row from a table"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/rows/itemAt(index={config.index})"
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "delete_table_row",
                    "message": f"Failed to delete row: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "delete_table_row",
                "message": f"Row {config.index} deleted successfully",
            }

    async def _list_table_columns(
        self, config: ExcelListTableColumnsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all columns in a table"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/columns"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_table_columns",
                    "message": f"Failed to list columns: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            columns = data.get("value", [])
            return {
                "status": "success",
                "action": "list_table_columns",
                "data": {
                    "count": len(columns),
                    "columns": [
                        {
                            "id": col.get("id"),
                            "name": col.get("name"),
                            "index": col.get("index"),
                        }
                        for col in columns
                    ],
                },
            }

    async def _add_table_column(
        self, config: ExcelAddTableColumnConfig, access_token: str
    ) -> Dict[str, Any]:
        """Add a column to a table"""
        column_data = {"name": config.column_name}

        if config.values:
            try:
                values = json.loads(config.values)
                column_data["values"] = [[v] for v in values]  # API expects 2D array
            except json.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "add_table_column",
                    "message": f"Invalid JSON in values: {str(e)}",
                }

        if config.index is not None:
            column_data["index"] = config.index

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/columns"
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=column_data,
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "add_table_column",
                    "message": f"Failed to add column: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "add_table_column",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "index": data.get("index"),
                },
            }

    async def _delete_table_column(
        self, config: ExcelDeleteTableColumnConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a column from a table"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/columns/{config.column_name}"
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "delete_table_column",
                    "message": f"Failed to delete column: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "delete_table_column",
                "message": f"Column '{config.column_name}' deleted successfully",
            }

    async def _sort_table(
        self, config: ExcelSortTableConfig, access_token: str
    ) -> Dict[str, Any]:
        """Sort a table by column"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/sort/apply"

            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "fields": [
                        {"key": config.column_name, "ascending": config.ascending}
                    ]
                },
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "sort_table_by_column",
                    "message": f"Failed to sort table: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "sort_table_by_column",
                "message": f"Table sorted by '{config.column_name}' ({'ascending' if config.ascending else 'descending'})",
            }

    async def _apply_filter(
        self, config: ExcelApplyFilterConfig, access_token: str
    ) -> Dict[str, Any]:
        """Apply filter to a table column"""
        try:
            filter_values = json.loads(config.filter_values)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "apply_table_column_filter",
                "message": f"Invalid JSON in filter_values: {str(e)}",
            }

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/columns/{config.column_name}/filter/apply"

            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"criteria": {"filterOn": "Values", "values": filter_values}},
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "apply_table_column_filter",
                    "message": f"Failed to apply filter: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "apply_table_column_filter",
                "message": f"Filter applied to column '{config.column_name}'",
            }

    async def _clear_filter(
        self, config: ExcelClearFilterConfig, access_token: str
    ) -> Dict[str, Any]:
        """Clear filter from a table column"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/tables/{config.table_name}/columns/{config.column_name}/filter/clear"

            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "clear_table_column_filter",
                    "message": f"Failed to clear filter: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "clear_table_column_filter",
                "message": f"Filter cleared from column '{config.column_name}'",
            }

    # ========================================================================
    # Chart Operations
    # ========================================================================

    async def _list_charts(
        self, config: ExcelListChartsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all charts in a worksheet"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/charts"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_worksheet_charts",
                    "message": f"Failed to list charts: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            charts = data.get("value", [])
            return {
                "status": "success",
                "action": "list_worksheet_charts",
                "data": {
                    "count": len(charts),
                    "charts": [
                        {
                            "id": c.get("id"),
                            "name": c.get("name"),
                            "height": c.get("height"),
                            "width": c.get("width"),
                        }
                        for c in charts
                    ],
                },
            }

    async def _get_chart(
        self, config: ExcelGetChartConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get chart details"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/charts/{config.chart_name}"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_chart",
                    "message": f"Failed to get chart: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_chart",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "height": data.get("height"),
                    "width": data.get("width"),
                    "left": data.get("left"),
                    "top": data.get("top"),
                },
            }

    async def _add_chart(
        self, config: ExcelAddChartConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new chart"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/charts/add"

            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "type": config.chart_type,
                    "sourceData": f"{config.worksheet_name}!{config.source_data_range}",
                    "seriesBy": config.series_by,
                },
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "create_chart",
                    "message": f"Failed to create chart: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "create_chart",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "type": config.chart_type,
                },
            }

    async def _update_chart(
        self, config: ExcelUpdateChartConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update chart properties"""
        update_data = {}
        if config.new_name:
            update_data["name"] = config.new_name
        if config.title:
            update_data["title"] = {"text": config.title}
        if config.height is not None:
            update_data["height"] = config.height
        if config.width is not None:
            update_data["width"] = config.width

        if not update_data:
            return {
                "status": "error",
                "action": "update_chart",
                "message": "No updates provided",
            }

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/charts/{config.chart_name}"
            response = await client.patch(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=update_data,
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "update_chart",
                    "message": f"Failed to update chart: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "update_chart",
                "data": {"id": data.get("id"), "name": data.get("name")},
            }

    async def _delete_chart(
        self, config: ExcelDeleteChartConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a chart"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/charts/{config.chart_name}"
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                return {
                    "status": "error",
                    "action": "delete_chart",
                    "message": f"Failed to delete chart: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "delete_chart",
                "message": f"Chart '{config.chart_name}' deleted successfully",
            }

    async def _get_chart_image(
        self, config: ExcelGetChartImageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get chart as base64-encoded PNG image"""
        params = {}
        if config.width is not None:
            params["width"] = config.width
        if config.height is not None:
            params["height"] = config.height

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/worksheets/{config.worksheet_name}/charts/{config.chart_name}/image"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_chart_image",
                    "message": f"Failed to get chart image: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_chart_image",
                "data": {
                    "image_base64": data.get("value"),
                    "format": "png",
                    "message": "Use image_base64 value in <img src='data:image/png;base64,...'>",
                },
            }

    # ========================================================================
    # Named Items Operations
    # ========================================================================

    async def _list_named_items(
        self, config: ExcelListNamedItemsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all named ranges and items"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/names"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_named_items",
                    "message": f"Failed to list named items: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            items = data.get("value", [])
            return {
                "status": "success",
                "action": "list_named_items",
                "data": {
                    "count": len(items),
                    "named_items": [
                        {
                            "name": item.get("name"),
                            "type": item.get("type"),
                            "value": item.get("value"),
                            "comment": item.get("comment"),
                        }
                        for item in items
                    ],
                },
            }

    async def _get_named_item(
        self, config: ExcelGetNamedItemConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get value of a named range or item"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/names/{config.name}"
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_named_item",
                    "message": f"Failed to get named item: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_named_item",
                "data": {
                    "name": data.get("name"),
                    "type": data.get("type"),
                    "value": data.get("value"),
                    "comment": data.get("comment"),
                },
            }

    async def _add_named_item(
        self, config: ExcelAddNamedItemConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a named range or constant"""
        item_data = {"name": config.name, "reference": config.reference}

        if config.comment:
            item_data["comment"] = config.comment

        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.workbook_id}/workbook/names/add"
            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}, json=item_data
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "create_named_item",
                    "message": f"Failed to create named item: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "create_named_item",
                "data": {
                    "name": data.get("name"),
                    "type": data.get("type"),
                    "value": data.get("value"),
                },
            }
