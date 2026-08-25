"""
BambooHR (HRIS) automation node.

Covers the core BambooHR REST API: employees, employee tables (job info,
compensation, employment status, …), time off, time tracking, reports, files,
metadata, and webhooks — plus a real push-based ``on_field_change`` trigger
backed by BambooHR's Permissioned Webhooks (HMAC-SHA256 signed).

Authentication (two methods):
- **API key** (primary, unrestricted): HTTP Basic auth with the API key as the
  username and any string as the password — ``Authorization: Basic b64(key:x)``.
- **OAuth 2.0**: subdomain-scoped authorization-code flow (Marketplace apps).

Every request needs the company subdomain (``{companyDomain}`` — the text before
``.bamboohr.com``) in the gateway URL, and ``Accept: application/json`` (BambooHR
defaults to XML otherwise). Employee id ``0`` resolves to the API-key owner.

Base URL: https://api.bamboohr.com/api/gateway.php/{companyDomain}/v1
Docs: https://documentation.bamboohr.com/docs
"""

import base64
import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.crm_records import BAMBOOHR_SCOPES

logger = logging.getLogger(__name__)

BAMBOOHR_GATEWAY = "https://api.bamboohr.com/api/gateway.php"

# Valid employee table names (row-level data tables).
EMPLOYEE_TABLES = [
    "jobInfo", "compensation", "employmentStatus", "bonus", "commission",
    "contacts", "dependents", "earnings", "emergencyContacts", "employeeAssets",
    "employeeCertifications", "employeeEducation", "employeeEquityGrants",
    "employeePassports", "employeeStockOptions", "employeeVisas",
]


# ============================================================================
# Credential Schemas
# ============================================================================


class BambooHROAuthCredential(BaseModel):
    """OAuth 2.0 credential for BambooHR (authorization-code flow).

    Restricted to approved Marketplace apps. Subdomain-scoped: the company
    subdomain forms the OAuth host, and the token response returns it back as
    the company context used for gateway API calls.
    """

    credential_type: Literal["bamboohr_oauth"] = Field(
        "bamboohr_oauth", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(
        ...,
        title="Company Subdomain",
        description="Your BambooHR subdomain. For acme.bamboohr.com enter 'acme'.",
    )
    access_token: str = Field(
        ..., title="Access Token", json_schema_extra={"ui:widget": "password"}
    )
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="Account Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "bamboohr",
            # Scopes covering the node's operations. offline_access is REQUIRED
            # to receive a refresh token; openid for OIDC identity.
            "x-oauth-scopes": [
                "openid", "offline_access",
                "employee", "employee.write", "employee_directory",
                "employee:file", "employee:file.write", "employee:photo",
                "time_off", "time_off.write",
                "time_tracking", "time_tracking.write",
                "report", "report.write",
                "company_file", "company_file.write",
                "company:info", "company:details",
                "webhooks", "webhooks.write",
                "meta", "user",
            ],
            "x-oauth-supports-custom-client": True,
            "x-oauth-custom-client-help": (
                "BambooHR OAuth is limited to approved Marketplace apps. Register one in "
                "the BambooHR Developer Portal, whitelist NoClick's BambooHR callback as a "
                "redirect URI (exact match), and paste its client ID + secret here — or use "
                "the API-key credential instead (no app approval needed)."
            ),
            "x-credential-url": "https://documentation.bamboohr.com/page/authenticate-integration",
        }
    )


class BambooHRApiKeyCredential(BaseModel):
    """API key credential for BambooHR (HTTP Basic auth).

    The API key is used as the Basic-auth username with any string as the
    password. The key inherits the creating user's UI permissions. Generate one
    from the BambooHR UI: click your name (lower-left) → API Keys.
    """

    credential_type: Literal["bamboohr_api_key"] = Field(
        "bamboohr_api_key", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(
        ...,
        title="Company Subdomain",
        description="Your BambooHR subdomain. For acme.bamboohr.com enter 'acme'.",
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="API key from BambooHR: click your name (lower-left) → API Keys.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://documentation.bamboohr.com/docs/getting-started",
            "x-credential-instructions": (
                "In BambooHR, click your name in the lower-left, choose 'API Keys', and "
                "generate a key. It inherits your UI permissions. Enter your subdomain "
                "(the text before .bamboohr.com) and the key."
            ),
        }
    )


# OAuth first (frontend auto-sorts OAuth above API key).
BambooHRCredential = Union[BambooHROAuthCredential, BambooHRApiKeyCredential]


# ============================================================================
# Operation Configs
# ============================================================================
#
# Shared field helpers ------------------------------------------------------

def _employee_id_field(desc: str = "Employee ID (use 0 for the API-key owner)", *, required: bool = True) -> Any:
    return Field(
        ... if required else None,
        title="Employee",
        description=desc,
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "employee_id",
                "placeholder": "Select an employee…",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste an employee ID (0 = me)",
            }
        },
    )


def _time_off_type_field(desc: str = "The type of time off", *, required: bool = True) -> Any:
    return Field(
        ... if required else None,
        title="Time Off Type",
        description=desc,
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "time_off_type_id",
                "placeholder": "Select a time off type…",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a time off type ID",
            }
        },
    )


def _webhook_id_field() -> Any:
    return Field(
        ...,
        title="Webhook",
        description="The BambooHR webhook to target",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "webhook_id",
                "placeholder": "Select a webhook…",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a webhook ID",
            }
        },
    )


def _date_field(title: str, description: str = "Calendar date", *, required: bool = True) -> Any:
    """A YYYY-MM-DD date field rendered with the date-picker widget."""
    return Field(
        ... if required else None,
        title=title,
        description=description,
        json_schema_extra={"ui:widget": "date"},
    )


def _since_field(desc: str = "Only changes at or after this time") -> Any:
    """An ISO 8601 timestamp field rendered with the date-time picker widget."""
    return Field(..., title="Since", description=desc, json_schema_extra={"ui:widget": "datetime"})


def _table_name_field() -> Any:
    return Field(
        ...,
        title="Table",
        description="Employee data table",
        json_schema_extra={
            "enum": EMPLOYEE_TABLES,
            "x-enum-searchable": True,
        },
    )


# --- Employees --------------------------------------------------------------

class BambooGetEmployeeConfig(BaseModel):
    operation: Literal["get_employee"] = Field(
        "get_employee",
        json_schema_extra={"const": "get_employee", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Get Employee"},
        title="Get Employee",
    )
    employee_id: str = _employee_id_field()
    fields: str = Field(
        "firstName,lastName,jobTitle,workEmail,department,division,location,supervisor,status",
        title="Fields",
        description="Comma-separated field aliases/ids to return, or 'all'",
    )


class BambooGetDirectoryConfig(BaseModel):
    operation: Literal["get_employee_directory"] = Field(
        "get_employee_directory",
        json_schema_extra={"const": "get_employee_directory", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Get Employee Directory"},
        title="Get Employee Directory",
    )


class BambooAddEmployeeConfig(BaseModel):
    operation: Literal["add_employee"] = Field(
        "add_employee",
        json_schema_extra={"const": "add_employee", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Add Employee"},
        title="Add Employee",
    )
    first_name: str = Field(..., title="First Name", description="The employee's first name")
    last_name: str = Field(..., title="Last Name", description="The employee's last name")
    fields_json: Optional[str] = Field(
        None,
        title="Additional Fields (JSON)",
        description='Extra employee fields as a JSON object, e.g. {"jobTitle":"Engineer","workEmail":"a@b.com"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BambooUpdateEmployeeConfig(BaseModel):
    operation: Literal["update_employee"] = Field(
        "update_employee",
        json_schema_extra={"const": "update_employee", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Update Employee"},
        title="Update Employee",
    )
    employee_id: str = _employee_id_field()
    fields_json: str = Field(
        ...,
        title="Fields (JSON)",
        description='Fields to update as a JSON object, e.g. {"jobTitle":"Senior Engineer"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BambooGetChangedEmployeesConfig(BaseModel):
    operation: Literal["get_changed_employees"] = Field(
        "get_changed_employees",
        json_schema_extra={"const": "get_changed_employees", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Get Changed Employees"},
        title="Get Changed Employees",
    )
    since: str = _since_field("Only employees changed at or after this time")
    type: Optional[str] = Field(
        None, title="Change Type", description="Filter by change kind (optional)",
        json_schema_extra={"enum": ["", "inserted", "updated", "deleted"], "x-enum-searchable": True},
    )


class BambooGetEmployeePhotoConfig(BaseModel):
    operation: Literal["get_employee_photo"] = Field(
        "get_employee_photo",
        json_schema_extra={"const": "get_employee_photo", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Get Employee Photo"},
        title="Get Employee Photo",
    )
    employee_id: str = _employee_id_field()
    size: str = Field(
        "small", title="Size",
        json_schema_extra={"enum": ["original", "large", "medium", "small", "xs", "tiny"], "x-enum-searchable": True},
    )


# --- Employee tables --------------------------------------------------------

class BambooGetTableRowsConfig(BaseModel):
    operation: Literal["get_table_rows"] = Field(
        "get_table_rows",
        json_schema_extra={"const": "get_table_rows", "ui:hidden": True, "x-category": "Tables", "x-display-name": "Get Table Rows"},
        title="Get Table Rows",
    )
    employee_id: str = _employee_id_field()
    table_name: str = _table_name_field()


class BambooAddTableRowConfig(BaseModel):
    operation: Literal["add_table_row"] = Field(
        "add_table_row",
        json_schema_extra={"const": "add_table_row", "ui:hidden": True, "x-category": "Tables", "x-display-name": "Add Table Row"},
        title="Add Table Row",
    )
    employee_id: str = _employee_id_field()
    table_name: str = _table_name_field()
    fields_json: str = Field(..., title="Row Fields (JSON)", description='Row column values, e.g. {"jobTitle":"Engineer"}', json_schema_extra={"ui:widget": "textarea"})


class BambooUpdateTableRowConfig(BaseModel):
    operation: Literal["update_table_row"] = Field(
        "update_table_row",
        json_schema_extra={"const": "update_table_row", "ui:hidden": True, "x-category": "Tables", "x-display-name": "Update Table Row"},
        title="Update Table Row",
    )
    employee_id: str = _employee_id_field()
    table_name: str = _table_name_field()
    row_id: str = Field(..., title="Row ID", description="The table row's id")
    fields_json: str = Field(..., title="Row Fields (JSON)", description='Row column values, e.g. {"jobTitle":"Engineer"}', json_schema_extra={"ui:widget": "textarea"})


class BambooDeleteTableRowConfig(BaseModel):
    operation: Literal["delete_table_row"] = Field(
        "delete_table_row",
        json_schema_extra={"const": "delete_table_row", "ui:hidden": True, "x-category": "Tables", "x-display-name": "Delete Table Row"},
        title="Delete Table Row",
    )
    employee_id: str = _employee_id_field()
    table_name: str = _table_name_field()
    row_id: str = Field(..., title="Row ID", description="The table row's id")


class BambooGetChangedTableConfig(BaseModel):
    operation: Literal["get_changed_table_rows"] = Field(
        "get_changed_table_rows",
        json_schema_extra={"const": "get_changed_table_rows", "ui:hidden": True, "x-category": "Tables", "x-display-name": "Get Changed Table Rows"},
        title="Get Changed Table Rows",
    )
    table_name: str = _table_name_field()
    since: str = _since_field("Only rows changed at or after this time")


# --- Time off ---------------------------------------------------------------

class BambooListTimeOffRequestsConfig(BaseModel):
    operation: Literal["list_time_off_requests"] = Field(
        "list_time_off_requests",
        json_schema_extra={"const": "list_time_off_requests", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "List Time Off Requests"},
        title="List Time Off Requests",
    )
    start: str = _date_field("Start Date", "Range start")
    end: str = _date_field("End Date", "Range end")
    employee_id: Optional[str] = _employee_id_field("Filter to one employee (optional)", required=False)
    status: Optional[str] = Field(
        None, title="Status", description="Filter by request status (optional)",
        json_schema_extra={"enum": ["", "approved", "denied", "superseded", "requested", "canceled"], "x-enum-searchable": True},
    )
    type: Optional[str] = _time_off_type_field("Filter to one time off type (optional)", required=False)


class BambooAddTimeOffRequestConfig(BaseModel):
    operation: Literal["add_time_off_request"] = Field(
        "add_time_off_request",
        json_schema_extra={"const": "add_time_off_request", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "Add Time Off Request"},
        title="Add Time Off Request",
    )
    employee_id: str = _employee_id_field()
    start: str = _date_field("Start Date", "Range start")
    end: str = _date_field("End Date", "Range end")
    time_off_type_id: str = _time_off_type_field()
    amount: str = Field(..., title="Amount", description="Hours or days depending on the type's unit")
    status: str = Field(
        "requested", title="Status", description="Initial request status",
        json_schema_extra={"enum": ["requested", "approved", "denied"], "x-enum-searchable": True},
    )
    notes: Optional[str] = Field(None, title="Notes", description="Optional note shown on the request")


class BambooChangeRequestStatusConfig(BaseModel):
    operation: Literal["change_time_off_request_status"] = Field(
        "change_time_off_request_status",
        json_schema_extra={"const": "change_time_off_request_status", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "Change Request Status"},
        title="Change Request Status",
    )
    request_id: str = Field(..., title="Request ID", description="The time-off request id")
    status: str = Field(
        ..., title="Status", description="New status for the request",
        json_schema_extra={"enum": ["approved", "denied", "canceled"], "x-enum-searchable": True},
    )
    note: Optional[str] = Field(None, title="Note", description="Optional note")


class BambooAddTimeOffHistoryConfig(BaseModel):
    operation: Literal["add_time_off_history"] = Field(
        "add_time_off_history",
        json_schema_extra={"const": "add_time_off_history", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "Add Time Off History"},
        title="Add Time Off History",
    )
    employee_id: str = _employee_id_field()
    fields_json: str = Field(..., title="History Entry (JSON)", description='e.g. {"date":"2026-01-01","note":"Manual entry","amount":8}', json_schema_extra={"ui:widget": "textarea"})


class BambooAdjustBalanceConfig(BaseModel):
    operation: Literal["adjust_time_off_balance"] = Field(
        "adjust_time_off_balance",
        json_schema_extra={"const": "adjust_time_off_balance", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "Adjust Time Off Balance"},
        title="Adjust Time Off Balance",
    )
    employee_id: str = _employee_id_field()
    date: str = _date_field("Date", "Effective date of the adjustment")
    time_off_type_id: str = _time_off_type_field()
    amount: str = Field(..., title="Amount", description="Positive or negative adjustment")
    note: Optional[str] = Field(None, title="Note", description="Optional note")


class BambooEstimateBalanceConfig(BaseModel):
    operation: Literal["estimate_future_balance"] = Field(
        "estimate_future_balance",
        json_schema_extra={"const": "estimate_future_balance", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "Estimate Future Balance"},
        title="Estimate Future Balance",
    )
    employee_id: str = _employee_id_field()
    end: str = _date_field("As-of Date", "Project the balance to this date")


class BambooListTimeOffTypesConfig(BaseModel):
    operation: Literal["list_time_off_types"] = Field(
        "list_time_off_types",
        json_schema_extra={"const": "list_time_off_types", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "List Time Off Types"},
        title="List Time Off Types",
    )


class BambooListTimeOffPoliciesConfig(BaseModel):
    operation: Literal["list_time_off_policies"] = Field(
        "list_time_off_policies",
        json_schema_extra={"const": "list_time_off_policies", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "List Time Off Policies"},
        title="List Time Off Policies",
    )


class BambooWhosOutConfig(BaseModel):
    operation: Literal["get_whos_out"] = Field(
        "get_whos_out",
        json_schema_extra={"const": "get_whos_out", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "Get Who's Out"},
        title="Get Who's Out",
    )
    start: Optional[str] = _date_field("Start Date", "Defaults to today", required=False)
    end: Optional[str] = _date_field("End Date", "Range end (optional)", required=False)


# --- Time tracking ----------------------------------------------------------

class BambooTimesheetSummaryConfig(BaseModel):
    operation: Literal["get_timesheet_summary"] = Field(
        "get_timesheet_summary",
        json_schema_extra={"const": "get_timesheet_summary", "ui:hidden": True, "x-category": "Time Tracking", "x-display-name": "Get Timesheet Summary"},
        title="Get Timesheet Summary",
    )
    employee_ids: str = Field(..., title="Employee IDs", description="Comma-separated employee IDs")
    start: str = _date_field("Start Date", "Range start")
    end: str = _date_field("End Date", "Range end")


class BambooClockInConfig(BaseModel):
    operation: Literal["clock_in"] = Field(
        "clock_in",
        json_schema_extra={"const": "clock_in", "ui:hidden": True, "x-category": "Time Tracking", "x-display-name": "Clock In"},
        title="Clock In",
    )
    employee_id: str = _employee_id_field()
    fields_json: Optional[str] = Field(
        None, title="Options (JSON)", description='Optional {"timezone":"…","note":"…","projectId":…}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BambooClockOutConfig(BaseModel):
    operation: Literal["clock_out"] = Field(
        "clock_out",
        json_schema_extra={"const": "clock_out", "ui:hidden": True, "x-category": "Time Tracking", "x-display-name": "Clock Out"},
        title="Clock Out",
    )
    employee_id: str = _employee_id_field()


class BambooAddTimeTrackingConfig(BaseModel):
    operation: Literal["add_time_tracking"] = Field(
        "add_time_tracking",
        json_schema_extra={"const": "add_time_tracking", "ui:hidden": True, "x-category": "Time Tracking", "x-display-name": "Add Hour Entry"},
        title="Add Hour Entry",
    )
    fields_json: str = Field(..., title="Hour Entry (JSON)", description='e.g. {"employeeId":123,"date":"2026-01-01","hours":8}', json_schema_extra={"ui:widget": "textarea"})


class BambooUpdateTimeTrackingConfig(BaseModel):
    operation: Literal["update_time_tracking"] = Field(
        "update_time_tracking",
        json_schema_extra={"const": "update_time_tracking", "ui:hidden": True, "x-category": "Time Tracking", "x-display-name": "Update Hour Entry"},
        title="Update Hour Entry",
    )
    time_tracking_id: str = Field(..., title="Time Tracking ID", description="The time-tracking entry id")
    fields_json: str = Field(..., title="Fields (JSON)", description='Fields to change, e.g. {"hours":6.5}', json_schema_extra={"ui:widget": "textarea"})


class BambooDeleteTimeTrackingConfig(BaseModel):
    operation: Literal["delete_time_tracking"] = Field(
        "delete_time_tracking",
        json_schema_extra={"const": "delete_time_tracking", "ui:hidden": True, "x-category": "Time Tracking", "x-display-name": "Delete Hour Entry"},
        title="Delete Hour Entry",
    )
    time_tracking_id: str = Field(..., title="Time Tracking ID", description="The time-tracking entry id")


# --- Reports ----------------------------------------------------------------

class BambooListDatasetsConfig(BaseModel):
    operation: Literal["list_datasets"] = Field(
        "list_datasets",
        json_schema_extra={"const": "list_datasets", "ui:hidden": True, "x-category": "Reports", "x-display-name": "List Datasets"},
        title="List Datasets",
    )


class BambooGetReportConfig(BaseModel):
    operation: Literal["get_report"] = Field(
        "get_report",
        json_schema_extra={"const": "get_report", "ui:hidden": True, "x-category": "Reports", "x-display-name": "Get Report"},
        title="Get Report",
    )
    report_id: str = Field(
        ...,
        title="Report ID",
        description="Numeric ID of a saved company report (from the report's URL in BambooHR)",
    )
    report_format: str = Field(
        "JSON", title="Format",
        json_schema_extra={"enum": ["JSON", "CSV", "XLS", "PDF"], "x-enum-searchable": True},
    )


class BambooCustomReportConfig(BaseModel):
    operation: Literal["request_custom_report"] = Field(
        "request_custom_report",
        json_schema_extra={"const": "request_custom_report", "ui:hidden": True, "x-category": "Reports", "x-display-name": "Request Custom Report"},
        title="Request Custom Report",
    )
    fields: str = Field(..., title="Fields", description="Comma-separated field aliases/ids (max 400)")
    title: Optional[str] = Field(None, title="Title", description="Report title (optional)")
    filters_json: Optional[str] = Field(
        None, title="Filters (JSON)",
        description='Optional, e.g. {"lastChanged":{"includeNull":"no","value":"2026-01-01T00:00:00Z"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


# --- Files ------------------------------------------------------------------

class BambooListEmployeeFilesConfig(BaseModel):
    operation: Literal["list_employee_files"] = Field(
        "list_employee_files",
        json_schema_extra={"const": "list_employee_files", "ui:hidden": True, "x-category": "Files", "x-display-name": "List Employee Files"},
        title="List Employee Files",
    )
    employee_id: str = _employee_id_field()


class BambooUploadEmployeeFileConfig(BaseModel):
    operation: Literal["upload_employee_file"] = Field(
        "upload_employee_file",
        json_schema_extra={"const": "upload_employee_file", "ui:hidden": True, "x-category": "Files", "x-display-name": "Upload Employee File"},
        title="Upload Employee File",
    )
    employee_id: str = _employee_id_field()
    file_name: str = Field(..., title="File Name", description="Name to save the file as, e.g. contract.pdf")
    category_id: str = Field(
        ..., title="Category", description="Employee file category",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "category_id", "placeholder": "Select a category…",
                "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste a category id",
            }
        },
    )
    content_base64: str = Field(..., title="File Content (base64)", description="The file bytes, base64-encoded", json_schema_extra={"ui:widget": "textarea"})
    share: str = Field(
        "yes", title="Share with Employee",
        json_schema_extra={"enum": ["yes", "no"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class BambooGetEmployeeFileConfig(BaseModel):
    operation: Literal["get_employee_file"] = Field(
        "get_employee_file",
        json_schema_extra={"const": "get_employee_file", "ui:hidden": True, "x-category": "Files", "x-display-name": "Get Employee File"},
        title="Get Employee File",
    )
    employee_id: str = _employee_id_field()
    file_id: str = Field(..., title="File ID", description="The file's numeric id")


class BambooDeleteEmployeeFileConfig(BaseModel):
    operation: Literal["delete_employee_file"] = Field(
        "delete_employee_file",
        json_schema_extra={"const": "delete_employee_file", "ui:hidden": True, "x-category": "Files", "x-display-name": "Delete Employee File"},
        title="Delete Employee File",
    )
    employee_id: str = _employee_id_field()
    file_id: str = Field(..., title="File ID", description="The file's numeric id")


class BambooListCompanyFilesConfig(BaseModel):
    operation: Literal["list_company_files"] = Field(
        "list_company_files",
        json_schema_extra={"const": "list_company_files", "ui:hidden": True, "x-category": "Files", "x-display-name": "List Company Files"},
        title="List Company Files",
    )


class BambooGetCompanyFileConfig(BaseModel):
    operation: Literal["get_company_file"] = Field(
        "get_company_file",
        json_schema_extra={"const": "get_company_file", "ui:hidden": True, "x-category": "Files", "x-display-name": "Get Company File"},
        title="Get Company File",
    )
    file_id: str = Field(..., title="File ID", description="The file's numeric id")


# --- Metadata ---------------------------------------------------------------

class BambooListFieldsConfig(BaseModel):
    operation: Literal["list_fields"] = Field(
        "list_fields",
        json_schema_extra={"const": "list_fields", "ui:hidden": True, "x-category": "Metadata", "x-display-name": "List Fields"},
        title="List Fields",
    )


class BambooListTabularFieldsConfig(BaseModel):
    operation: Literal["list_tabular_fields"] = Field(
        "list_tabular_fields",
        json_schema_extra={"const": "list_tabular_fields", "ui:hidden": True, "x-category": "Metadata", "x-display-name": "List Tabular Fields"},
        title="List Tabular Fields",
    )


class BambooGetListsConfig(BaseModel):
    operation: Literal["get_lists"] = Field(
        "get_lists",
        json_schema_extra={"const": "get_lists", "ui:hidden": True, "x-category": "Metadata", "x-display-name": "Get Lists"},
        title="Get Lists",
    )


class BambooListUsersConfig(BaseModel):
    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={"const": "list_users", "ui:hidden": True, "x-category": "Metadata", "x-display-name": "List Users"},
        title="List Users",
    )


class BambooGetAccountConfig(BaseModel):
    operation: Literal["get_account"] = Field(
        "get_account",
        json_schema_extra={"const": "get_account", "ui:hidden": True, "x-category": "Metadata", "x-display-name": "Get Account Info"},
        title="Get Account Info",
    )


# --- Webhooks (management) --------------------------------------------------

class BambooListWebhooksConfig(BaseModel):
    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={"const": "list_webhooks", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "List Webhooks"},
        title="List Webhooks",
    )


class BambooCreateWebhookConfig(BaseModel):
    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={"const": "create_webhook", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Create Webhook"},
        title="Create Webhook",
    )
    definition_json: str = Field(
        ..., title="Webhook Definition (JSON)",
        description='e.g. {"name":"…","monitorFields":["jobTitle"],"postFields":{"jobTitle":"jobTitle"},"url":"https://…","format":"json"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class BambooGetWebhookConfig(BaseModel):
    operation: Literal["get_webhook"] = Field(
        "get_webhook",
        json_schema_extra={"const": "get_webhook", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Get Webhook"},
        title="Get Webhook",
    )
    webhook_id: str = _webhook_id_field()


class BambooUpdateWebhookConfig(BaseModel):
    operation: Literal["update_webhook"] = Field(
        "update_webhook",
        json_schema_extra={"const": "update_webhook", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Update Webhook"},
        title="Update Webhook",
    )
    webhook_id: str = _webhook_id_field()
    definition_json: str = Field(..., title="Webhook Definition (JSON)", description='Full updated definition, e.g. {"name":"…","monitorFields":["jobTitle"],"url":"https://…"}', json_schema_extra={"ui:widget": "textarea"})


class BambooDeleteWebhookConfig(BaseModel):
    operation: Literal["delete_webhook"] = Field(
        "delete_webhook",
        json_schema_extra={"const": "delete_webhook", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Delete Webhook"},
        title="Delete Webhook",
    )
    webhook_id: str = _webhook_id_field()


class BambooListMonitorFieldsConfig(BaseModel):
    operation: Literal["list_monitor_fields"] = Field(
        "list_monitor_fields",
        json_schema_extra={"const": "list_monitor_fields", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "List Monitor Fields"},
        title="List Monitor Fields",
    )


# --- Triggers: field-change push webhooks (decomposed by event type) --------
#
# All BambooHR triggers are Permissioned Webhooks that fire when monitored
# employee fields change. Rather than one generic trigger, we ship a trigger per
# semantic event with a preset, verified, non-permission-gated field bundle —
# plus a generic "Any Field Change" for full control. Compensation/termination
# fields are sensitive (permission-gated) so they're intentionally NOT preset;
# watch them via the generic trigger if your credential has permission.
TRIGGER_MONITOR_FIELDS = {
    "on_employment_status_change": ["status", "hireDate"],
    "on_job_change": ["jobTitle", "department", "division", "location", "reportsTo"],
    "on_contact_info_change": ["workEmail", "mobilePhone", "homePhone", "workPhone"],
    "on_personal_info_change": ["firstName", "lastName", "preferredName", "homeEmail"],
}


class _BambooTriggerBase(WebhookTriggerConfigBase):
    """Shared plumbing for BambooHR field-change triggers.

    Each registers a Permissioned Webhook pointing at the NoClick webhook URL and
    verifies every delivery's ``X-BambooHR-Signature`` (HMAC-SHA256 over the raw
    body + ``X-BambooHR-Timestamp``, keyed by the webhook's private key).
    """

    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="NoClick auto-generates this and registers it with BambooHR",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class BambooOnEmploymentStatusChangeConfig(_BambooTriggerBase):
    operation: Literal["on_employment_status_change"] = Field(
        "on_employment_status_change",
        json_schema_extra={"const": "on_employment_status_change", "ui:hidden": True, "x-category": None, "x-is-trigger": True, "x-display-name": "On Employment Status Change"},
        title="On Employment Status Change",
    )


class BambooOnJobChangeConfig(_BambooTriggerBase):
    operation: Literal["on_job_change"] = Field(
        "on_job_change",
        json_schema_extra={"const": "on_job_change", "ui:hidden": True, "x-category": None, "x-is-trigger": True, "x-display-name": "On Job Change"},
        title="On Job Change",
    )


class BambooOnContactInfoChangeConfig(_BambooTriggerBase):
    operation: Literal["on_contact_info_change"] = Field(
        "on_contact_info_change",
        json_schema_extra={"const": "on_contact_info_change", "ui:hidden": True, "x-category": None, "x-is-trigger": True, "x-display-name": "On Contact Info Change"},
        title="On Contact Info Change",
    )


class BambooOnPersonalInfoChangeConfig(_BambooTriggerBase):
    operation: Literal["on_personal_info_change"] = Field(
        "on_personal_info_change",
        json_schema_extra={"const": "on_personal_info_change", "ui:hidden": True, "x-category": None, "x-is-trigger": True, "x-display-name": "On Personal Info Change"},
        title="On Personal Info Change",
    )


class BambooOnFieldChangeConfig(_BambooTriggerBase):
    """Generic trigger: fire when any user-chosen fields change."""

    operation: Literal["on_field_change"] = Field(
        "on_field_change",
        json_schema_extra={"const": "on_field_change", "ui:hidden": True, "x-category": None, "x-is-trigger": True, "x-display-name": "On Field Change (Any)"},
        title="On Field Change (Any)",
    )
    monitor_fields: str = Field(
        "jobTitle,department,status",
        title="Monitored Fields",
        description="Comma-separated field aliases/names to watch for changes",
    )


BambooHRConfig = Annotated[
    Union[
        BambooGetEmployeeConfig,
        BambooGetDirectoryConfig,
        BambooAddEmployeeConfig,
        BambooUpdateEmployeeConfig,
        BambooGetChangedEmployeesConfig,
        BambooGetEmployeePhotoConfig,
        BambooGetTableRowsConfig,
        BambooAddTableRowConfig,
        BambooUpdateTableRowConfig,
        BambooDeleteTableRowConfig,
        BambooGetChangedTableConfig,
        BambooListTimeOffRequestsConfig,
        BambooAddTimeOffRequestConfig,
        BambooChangeRequestStatusConfig,
        BambooAddTimeOffHistoryConfig,
        BambooAdjustBalanceConfig,
        BambooEstimateBalanceConfig,
        BambooListTimeOffTypesConfig,
        BambooListTimeOffPoliciesConfig,
        BambooWhosOutConfig,
        BambooTimesheetSummaryConfig,
        BambooClockInConfig,
        BambooClockOutConfig,
        BambooAddTimeTrackingConfig,
        BambooUpdateTimeTrackingConfig,
        BambooDeleteTimeTrackingConfig,
        BambooListDatasetsConfig,
        BambooGetReportConfig,
        BambooCustomReportConfig,
        BambooListEmployeeFilesConfig,
        BambooUploadEmployeeFileConfig,
        BambooGetEmployeeFileConfig,
        BambooDeleteEmployeeFileConfig,
        BambooListCompanyFilesConfig,
        BambooGetCompanyFileConfig,
        BambooListFieldsConfig,
        BambooListTabularFieldsConfig,
        BambooGetListsConfig,
        BambooListUsersConfig,
        BambooGetAccountConfig,
        BambooListWebhooksConfig,
        BambooCreateWebhookConfig,
        BambooGetWebhookConfig,
        BambooUpdateWebhookConfig,
        BambooDeleteWebhookConfig,
        BambooListMonitorFieldsConfig,
        # Triggers (decomposed by event type)
        BambooOnEmploymentStatusChangeConfig,
        BambooOnJobChangeConfig,
        BambooOnContactInfoChangeConfig,
        BambooOnPersonalInfoChangeConfig,
        BambooOnFieldChangeConfig,
    ],
    Discriminator("operation"),
]


class BambooHRNodeConfig(NodeConfig[BambooHRConfig, BambooHRCredential]):
    """Full BambooHR node configuration including credentials."""

    pass


# ============================================================================
# HTTP request helper
# ============================================================================


def _auth_header(*, api_key: Optional[str] = None, access_token: Optional[str] = None) -> str:
    if access_token:
        return f"Bearer {access_token}"
    raw = f"{api_key}:x".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _resolve_auth(credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract ``{subdomain, api_key|access_token}`` from a decrypted credential."""
    if not credential:
        return None
    subdomain = credential.get("subdomain")
    if not subdomain:
        return None
    if credential.get("access_token"):
        return {"subdomain": subdomain, "access_token": credential["access_token"]}
    if credential.get("api_key"):
        return {"subdomain": subdomain, "api_key": credential["api_key"]}
    return None


def _download_filename(response: "httpx.Response", action_name: str, content_type: str) -> str:
    """Best-effort filename for a downloaded body: Content-Disposition if present,
    else the operation name + an extension guessed from the content type."""
    cd = response.headers.get("content-disposition") or response.headers.get("Content-Disposition") or ""
    if "filename" in cd.lower():
        part = cd.split("filename")[-1].lstrip("*=").strip()
        part = part.split(";")[0].replace("UTF-8''", "").strip().strip('"').strip("'")
        if part:
            return part
    ext = {
        "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif",
        "application/pdf": "pdf", "text/csv": "csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.ms-excel": "xls",
    }.get(content_type.split(";")[0].strip(), "bin")
    return f"{action_name}.{ext}"


async def _bamboo_request(
    auth: Dict[str, Any],
    method: str,
    endpoint: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    files: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    version: str = "v1",
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated BambooHR request and return a structured result.

    Non-JSON responses (photo / file bytes) are surfaced as base64 under
    a BinaryOutput marker (resolved to a file reference by the executor).
    """
    subdomain = auth["subdomain"]
    url = f"{BAMBOOHR_GATEWAY}/{subdomain}/{version}{endpoint}"
    headers = {
        "Authorization": _auth_header(
            api_key=auth.get("api_key"), access_token=auth.get("access_token")
        ),
        "Accept": "application/json",
    }
    # BambooHR treats any Content-Type variant other than exactly
    # "application/json" as XML — only set it for JSON bodies.
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers,
                params=params, json=json_body, files=files, data=data,
            )
            api_ms = round((time.time() - start) * 1000, 2)

            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("message") or err.get("error") or err if isinstance(err, dict) else err
                except Exception:
                    message = response.text or f"HTTP {response.status_code}"
                # BambooHR often returns the error reason in a header.
                bamboo_err = response.headers.get("X-BambooHR-Error-Message")
                if bamboo_err:
                    message = bamboo_err
                if not isinstance(message, str):
                    message = str(message)
                logger.error(f"[BambooHRNode] API error ({action_name}): {message}")
                return {
                    "status": "error", "action": action_name, "error": message,
                    "status_code": response.status_code, "timing_ms": {"api_request": api_ms},
                }

            content_type = response.headers.get("content-type", "")
            if response.status_code == 204 or not response.content:
                # Create ops (POST/PUT) return the new resource id in the
                # Location header with an empty body — surface it.
                data_out: Any = {"success": True}
                loc = response.headers.get("Location") or response.headers.get("location")
                if loc:
                    data_out["location"] = loc
                    tail = loc.rstrip("/").rsplit("/", 1)[-1]
                    if tail.isdigit():
                        data_out["id"] = tail
            elif "application/json" in content_type:
                try:
                    data_out = response.json()
                except Exception:
                    data_out = {"raw": response.text}
            elif content_type.startswith(("image/", "application/pdf", "application/octet-stream")) or "spreadsheet" in content_type or "csv" in content_type:
                # Binary bodies (employee photo, file downloads, PDF/XLS reports)
                # are handed back as a BinaryOutput marker; the executor stores it
                # and resolves it to a {url, mime_type, name, size_bytes} reference
                # (never a base64 wall-of-characters in the output).
                from nodes.core.binary_output import BinaryOutput
                data_out = {
                    "file": BinaryOutput(
                        data=response.content,
                        content_type=content_type.split(";")[0].strip() or "application/octet-stream",
                        filename=_download_filename(response, action_name, content_type),
                    )
                }
            else:
                data_out = {"raw": response.text, "content_type": content_type}

            return {
                "status": "success", "action": action_name, "data": data_out,
                "status_code": response.status_code, "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timed out", "status_code": 408}
        except Exception as e:  # noqa: BLE001
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[BambooHRNode] Request failed ({action_name}): {msg}")
            return {"status": "error", "action": action_name, "error": msg, "status_code": 500}


def _parse_json_field(raw: Optional[str], field: str) -> Any:
    import json as _json
    if not raw:
        return {}
    try:
        return _json.loads(raw)
    except Exception as e:
        raise ValueError(f"{field} must be valid JSON: {e}")


# ============================================================================
# Node Implementation
# ============================================================================


class BambooHRNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """BambooHR HRIS automation node (employees, time off, reports, webhooks)."""

    edit_examples = [
        "Get an employee's job title and department from BambooHR",
        "List all time-off requests approved this month",
        "Create a BambooHR employee when a new hire form is submitted",
        "Trigger a workflow when an employee's department changes",
        "Pull a BambooHR company report and email it",
    ]

    scope_registry = BAMBOOHR_SCOPES
    connection_evidence = ConnectionEvidence(
        field="employee_id",
        noun="employees",
    )
    @classmethod
    def get_config_model(cls):
        return BambooHRNodeConfig

    # ------------------------------------------------------------------
    # OAuth token refresh (OAuth credential only; API key needs none)
    # ------------------------------------------------------------------
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not (credential_data or {}).get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.bamboohr_oauth import refresh_access_token

        subdomain = credential_data.get("subdomain")
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=lambda rt: refresh_access_token(rt, subdomain=subdomain),
            provider="bamboohr",
        )

    async def _resolve_fresh_auth(self, credentials) -> Dict[str, Any]:
        """Return the auth dict, refreshing an expiring OAuth token first."""
        cred_dict = credentials.model_dump()
        if cred_dict.get("refresh_token"):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.bamboohr_oauth import refresh_access_token

            subdomain = cred_dict.get("subdomain")
            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=lambda rt: refresh_access_token(rt, subdomain=subdomain),
                provider="bamboohr",
                caller_path="execute",
            )
        auth = _resolve_auth(cred_dict)
        if not auth:
            raise ValueError("BambooHR credential is missing a subdomain and API key / access token.")
        return auth

    # ------------------------------------------------------------------
    # Dynamic dropdowns
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        auth = _resolve_auth(credential_data or {})
        if not auth:
            return {"options": []}

        if field_name == "employee_id":
            result = await _bamboo_request(auth, "GET", "/employees/directory", action_name="load_employees")
            employees = (result.get("data") or {}).get("employees", []) if result.get("status") == "success" else []
            options = [
                {"value": str(e.get("id")), "label": e.get("displayName") or f"{e.get('firstName','')} {e.get('lastName','')}".strip() or str(e.get("id"))}
                for e in employees if e.get("id") is not None
            ]
            return {"options": [{"value": "0", "label": "Me (API key owner)"}] + options}

        if field_name == "time_off_type_id":
            result = await _bamboo_request(auth, "GET", "/meta/time_off/types", action_name="load_time_off_types")
            types = (result.get("data") or {}).get("timeOffTypes", []) if result.get("status") == "success" else []
            return {"options": [{"value": str(t.get("id")), "label": t.get("name") or str(t.get("id"))} for t in types if t.get("id") is not None]}

        if field_name == "webhook_id":
            result = await _bamboo_request(auth, "GET", "/webhooks/", action_name="load_webhooks")
            data = result.get("data") if result.get("status") == "success" else None
            hooks = (data.get("webhooks") if isinstance(data, dict) else data) or []
            return {"options": [
                {"value": str(w.get("id")), "label": w.get("name") or f"Webhook {w.get('id')}"}
                for w in hooks if isinstance(w, dict) and w.get("id") is not None
            ]}

        if field_name == "category_id":
            # Employee-file categories are company-wide, but the endpoint is keyed
            # by an employee (/employees/{id}/files/view). Employee 0 ("the API-key
            # owner") does NOT resolve under an OAuth token, so prefer the
            # already-selected employee, then fall back to the first real employee
            # in the directory rather than 0.
            emp = None
            if context:
                emp = context.get("employee_id") or (context.get("config") or {}).get("employee_id")
            if not emp or str(emp) == "0":
                d = await _bamboo_request(auth, "GET", "/employees/directory", action_name="load_file_categories_dir")
                emps = (d.get("data") or {}).get("employees", []) if d.get("status") == "success" else []
                emp = str(emps[0]["id"]) if emps else "0"
            result = await _bamboo_request(auth, "GET", f"/employees/{emp}/files/view/", action_name="load_file_categories")
            data = result.get("data") if result.get("status") == "success" else None
            cats = (data.get("categories") if isinstance(data, dict) else data) or []
            return {"options": [
                {"value": str(cat.get("id")), "label": cat.get("name") or f"Category {cat.get('id')}"}
                for cat in cats if isinstance(cat, dict) and cat.get("id") is not None
            ]}

        return {"options": []}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, BambooHRNodeConfig):
            raise ValueError("Valid configuration is required")

        op = config.config
        # The trigger op is fired by the webhook route — a manual run just echoes.
        if isinstance(op, _BambooTriggerBase):
            return {"type": "bamboohr", "operation": op.operation, "status": "success",
                    "data": {**inputs, "webhook_url": op.webhook_url}}

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect a BambooHR API key or OAuth account.")
        auth = await self._resolve_fresh_auth(credentials)

        handler = self._HANDLERS.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")
        result = await handler(self, op, auth)
        if isinstance(result, dict):
            result.setdefault("timing_ms", {})
            result["timing_ms"]["total"] = round((time.time() - start_time) * 1000, 2)
        return result

    # -- Employee handlers ------------------------------------------------
    async def _get_employee(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/employees/{c.employee_id}", params={"fields": c.fields}, action_name="get_employee")

    async def _get_directory(self, c, auth):
        return await _bamboo_request(auth, "GET", "/employees/directory", action_name="get_employee_directory")

    async def _add_employee(self, c, auth):
        body = {"firstName": c.first_name, "lastName": c.last_name, **_parse_json_field(c.fields_json, "Additional Fields")}
        return await _bamboo_request(auth, "POST", "/employees/", json_body=body, action_name="add_employee")

    async def _update_employee(self, c, auth):
        body = _parse_json_field(c.fields_json, "Fields")
        return await _bamboo_request(auth, "POST", f"/employees/{c.employee_id}", json_body=body, action_name="update_employee")

    async def _get_changed_employees(self, c, auth):
        return await _bamboo_request(auth, "GET", "/employees/changed", params={"since": c.since, "type": c.type}, action_name="get_changed_employees")

    async def _get_employee_photo(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/employees/{c.employee_id}/photo/{c.size}", action_name="get_employee_photo")

    # -- Table handlers ---------------------------------------------------
    async def _get_table_rows(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/employees/{c.employee_id}/tables/{c.table_name}", action_name="get_table_rows")

    async def _add_table_row(self, c, auth):
        body = _parse_json_field(c.fields_json, "Row Fields")
        return await _bamboo_request(auth, "POST", f"/employees/{c.employee_id}/tables/{c.table_name}", json_body=body, action_name="add_table_row")

    async def _update_table_row(self, c, auth):
        body = _parse_json_field(c.fields_json, "Row Fields")
        return await _bamboo_request(auth, "PUT", f"/employees/{c.employee_id}/tables/{c.table_name}/{c.row_id}", json_body=body, action_name="update_table_row")

    async def _delete_table_row(self, c, auth):
        return await _bamboo_request(auth, "DELETE", f"/employees/{c.employee_id}/tables/{c.table_name}/{c.row_id}", action_name="delete_table_row")

    async def _get_changed_table(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/employees/changed/tables/{c.table_name}", params={"since": c.since}, action_name="get_changed_table_rows")

    # -- Time off handlers ------------------------------------------------
    async def _list_time_off_requests(self, c, auth):
        params = {"start": c.start, "end": c.end, "employeeId": c.employee_id, "status": c.status, "type": c.type}
        return await _bamboo_request(auth, "GET", "/time_off/requests/", params=params, action_name="list_time_off_requests")

    async def _add_time_off_request(self, c, auth):
        body = {"status": c.status, "start": c.start, "end": c.end, "timeOffTypeId": c.time_off_type_id, "amount": c.amount}
        if c.notes:
            # BambooHR wants each note tagged with its author ("from").
            body["notes"] = [{"from": "employee", "note": c.notes}]
        # Note: BambooHR uses PUT to add a time-off request.
        return await _bamboo_request(auth, "PUT", f"/employees/{c.employee_id}/time_off/request/", json_body=body, action_name="add_time_off_request")

    async def _change_request_status(self, c, auth):
        body = {"status": c.status}
        if c.note:
            body["note"] = c.note
        return await _bamboo_request(auth, "PUT", f"/time_off/requests/{c.request_id}/status/", json_body=body, action_name="change_time_off_request_status")

    async def _add_time_off_history(self, c, auth):
        body = _parse_json_field(c.fields_json, "History Entry")
        return await _bamboo_request(auth, "PUT", f"/employees/{c.employee_id}/time_off/history/", json_body=body, action_name="add_time_off_history")

    async def _adjust_balance(self, c, auth):
        body = {"date": c.date, "timeOffTypeId": c.time_off_type_id, "amount": c.amount}
        if c.note:
            body["note"] = c.note
        return await _bamboo_request(auth, "PUT", f"/employees/{c.employee_id}/time_off/balance_adjustment/", json_body=body, action_name="adjust_time_off_balance")

    async def _estimate_balance(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/employees/{c.employee_id}/time_off/calculator/", params={"end": c.end}, action_name="estimate_future_balance")

    async def _list_time_off_types(self, c, auth):
        return await _bamboo_request(auth, "GET", "/meta/time_off/types/", action_name="list_time_off_types")

    async def _list_time_off_policies(self, c, auth):
        return await _bamboo_request(auth, "GET", "/meta/time_off/policies/", action_name="list_time_off_policies")

    async def _whos_out(self, c, auth):
        return await _bamboo_request(auth, "GET", "/time_off/whos_out/", params={"start": c.start, "end": c.end}, action_name="get_whos_out")

    # -- Time tracking handlers ------------------------------------------
    async def _timesheet_summary(self, c, auth):
        params = {"employeeIds": c.employee_ids, "start": c.start, "end": c.end}
        return await _bamboo_request(auth, "GET", "/timesheet/summary", params=params, action_name="get_timesheet_summary")

    async def _clock_in(self, c, auth):
        body = {"employeeId": c.employee_id, **_parse_json_field(c.fields_json, "Options")}
        return await _bamboo_request(auth, "POST", "/timesheet/clock_in", json_body=body, action_name="clock_in")

    async def _clock_out(self, c, auth):
        return await _bamboo_request(auth, "POST", "/timesheet/clock_out", json_body={"employeeId": c.employee_id}, action_name="clock_out")

    async def _add_time_tracking(self, c, auth):
        body = _parse_json_field(c.fields_json, "Hour Entry")
        return await _bamboo_request(auth, "POST", "/time_tracking", json_body=body, action_name="add_time_tracking")

    async def _update_time_tracking(self, c, auth):
        body = _parse_json_field(c.fields_json, "Fields")
        return await _bamboo_request(auth, "PUT", f"/time_tracking/{c.time_tracking_id}", json_body=body, action_name="update_time_tracking")

    async def _delete_time_tracking(self, c, auth):
        return await _bamboo_request(auth, "DELETE", f"/time_tracking/{c.time_tracking_id}", action_name="delete_time_tracking")

    # -- Report handlers --------------------------------------------------
    async def _list_datasets(self, c, auth):
        # BambooHR has no "list reports" endpoint (reports are fetched by ID);
        # the Datasets API is the modern discovery surface.
        return await _bamboo_request(auth, "GET", "/datasets", action_name="list_datasets")

    async def _get_report(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/reports/{c.report_id}", params={"format": c.report_format}, action_name="get_report")

    async def _custom_report(self, c, auth):
        body: Dict[str, Any] = {"fields": [f.strip() for f in c.fields.split(",") if f.strip()]}
        if c.title:
            body["title"] = c.title
        if c.filters_json:
            body["filters"] = _parse_json_field(c.filters_json, "Filters")
        return await _bamboo_request(auth, "POST", "/reports/custom", params={"format": "JSON"}, json_body=body, action_name="request_custom_report")

    # -- File handlers ----------------------------------------------------
    async def _list_employee_files(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/employees/{c.employee_id}/files/view/", action_name="list_employee_files")

    async def _upload_employee_file(self, c, auth):
        try:
            content = base64.b64decode(c.content_base64)
        except Exception as e:
            return {"status": "error", "action": "upload_employee_file", "error": f"content_base64 is not valid base64: {e}", "status_code": 400}
        files = {"file": (c.file_name, content)}
        data = {"category": c.category_id, "fileName": c.file_name, "share": c.share}
        return await _bamboo_request(auth, "POST", f"/employees/{c.employee_id}/files/", files=files, data=data, action_name="upload_employee_file")

    async def _get_employee_file(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/employees/{c.employee_id}/files/{c.file_id}/", action_name="get_employee_file")

    async def _delete_employee_file(self, c, auth):
        return await _bamboo_request(auth, "DELETE", f"/employees/{c.employee_id}/files/{c.file_id}", action_name="delete_employee_file")

    async def _list_company_files(self, c, auth):
        return await _bamboo_request(auth, "GET", "/files/view/", action_name="list_company_files")

    async def _get_company_file(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/files/company/{c.file_id}/", action_name="get_company_file")

    # -- Metadata handlers ------------------------------------------------
    async def _list_fields(self, c, auth):
        return await _bamboo_request(auth, "GET", "/meta/fields/", action_name="list_fields")

    async def _list_tabular_fields(self, c, auth):
        return await _bamboo_request(auth, "GET", "/meta/tables/", action_name="list_tabular_fields")

    async def _get_lists(self, c, auth):
        return await _bamboo_request(auth, "GET", "/meta/lists/", action_name="get_lists")

    async def _list_users(self, c, auth):
        return await _bamboo_request(auth, "GET", "/meta/users/", action_name="list_users")

    async def _get_account(self, c, auth):
        return await _bamboo_request(auth, "GET", "/meta/company", action_name="get_account")

    # -- Webhook management handlers -------------------------------------
    async def _list_webhooks(self, c, auth):
        return await _bamboo_request(auth, "GET", "/webhooks/", action_name="list_webhooks")

    async def _create_webhook(self, c, auth):
        body = _parse_json_field(c.definition_json, "Webhook Definition")
        return await _bamboo_request(auth, "POST", "/webhooks/", json_body=body, action_name="create_webhook")

    async def _get_webhook(self, c, auth):
        return await _bamboo_request(auth, "GET", f"/webhooks/{c.webhook_id}/", action_name="get_webhook")

    async def _update_webhook(self, c, auth):
        body = _parse_json_field(c.definition_json, "Webhook Definition")
        return await _bamboo_request(auth, "PUT", f"/webhooks/{c.webhook_id}/", json_body=body, action_name="update_webhook")

    async def _delete_webhook(self, c, auth):
        return await _bamboo_request(auth, "DELETE", f"/webhooks/{c.webhook_id}/", action_name="delete_webhook")

    async def _list_monitor_fields(self, c, auth):
        return await _bamboo_request(auth, "GET", "/webhooks/monitor_fields/", action_name="list_monitor_fields")

    # ------------------------------------------------------------------
    # Push trigger — BambooHR Permissioned Webhook (HMAC-signed)
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "monitor_fields": (config or {}).get("monitor_fields"),
        }

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        auth = _resolve_auth(credential or {})
        if not auth:
            raise ValueError("A connected BambooHR account is required to register the trigger")
        cfg = config or {}
        # Decomposed triggers use their preset field bundle; the generic
        # "on_field_change" uses the user's comma-separated monitor_fields.
        op = cfg.get("operation")
        if op in TRIGGER_MONITOR_FIELDS:
            fields = TRIGGER_MONITOR_FIELDS[op]
        else:
            fields = [f.strip() for f in (cfg.get("monitor_fields") or "").split(",") if f.strip()] or ["jobTitle"]
        body = {
            "name": f"NoClick trigger {node_id}",
            "monitorFields": fields,
            "postFields": {f: f for f in fields},
            "url": webhook_url,
            "format": "json",
        }
        result = await _bamboo_request(auth, "POST", "/webhooks/", json_body=body, action_name="register_webhook")
        if result.get("status") != "success":
            raise ValueError(f"Failed to register BambooHR webhook: {result.get('error')}")
        data = result.get("data") or {}
        return {
            "external_webhook_id": str(data.get("id")) if data.get("id") is not None else None,
            "signing_secret": data.get("privateKey"),
        }

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        auth = _resolve_auth(credential or {})
        external_id = (config or {}).get("external_webhook_id")
        if not auth or not external_id:
            return
        try:
            await _bamboo_request(auth, "DELETE", f"/webhooks/{external_id}/", action_name="unregister_webhook")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[BambooHRNode] Failed to delete BambooHR webhook: {e}")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        """Verify ``X-BambooHR-Signature`` = HMAC-SHA256(rawBody + timestamp, privateKey)."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no private key stored (pre-registration) — don't hard-block
        sig = headers.get("x-bamboohr-signature") or headers.get("X-BambooHR-Signature")
        timestamp = headers.get("x-bamboohr-timestamp") or headers.get("X-BambooHR-Timestamp")
        if not sig or not timestamp:
            return False
        expected = hmac.new(
            secret.encode("utf-8"),
            body + timestamp.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, sig)

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Dict[str, Any]:
        """Deliver a fired webhook event to a wired agent as text."""
        import json as _json
        data = output.get("data", output) if isinstance(output, dict) else output
        return {"text": _json.dumps(data, default=str), "conversation_key": None}

    _HANDLERS = {
        "get_employee": _get_employee,
        "get_employee_directory": _get_directory,
        "add_employee": _add_employee,
        "update_employee": _update_employee,
        "get_changed_employees": _get_changed_employees,
        "get_employee_photo": _get_employee_photo,
        "get_table_rows": _get_table_rows,
        "add_table_row": _add_table_row,
        "update_table_row": _update_table_row,
        "delete_table_row": _delete_table_row,
        "get_changed_table_rows": _get_changed_table,
        "list_time_off_requests": _list_time_off_requests,
        "add_time_off_request": _add_time_off_request,
        "change_time_off_request_status": _change_request_status,
        "add_time_off_history": _add_time_off_history,
        "adjust_time_off_balance": _adjust_balance,
        "estimate_future_balance": _estimate_balance,
        "list_time_off_types": _list_time_off_types,
        "list_time_off_policies": _list_time_off_policies,
        "get_whos_out": _whos_out,
        "get_timesheet_summary": _timesheet_summary,
        "clock_in": _clock_in,
        "clock_out": _clock_out,
        "add_time_tracking": _add_time_tracking,
        "update_time_tracking": _update_time_tracking,
        "delete_time_tracking": _delete_time_tracking,
        "list_datasets": _list_datasets,
        "get_report": _get_report,
        "request_custom_report": _custom_report,
        "list_employee_files": _list_employee_files,
        "upload_employee_file": _upload_employee_file,
        "get_employee_file": _get_employee_file,
        "delete_employee_file": _delete_employee_file,
        "list_company_files": _list_company_files,
        "get_company_file": _get_company_file,
        "list_fields": _list_fields,
        "list_tabular_fields": _list_tabular_fields,
        "get_lists": _get_lists,
        "list_users": _list_users,
        "get_account": _get_account,
        "list_webhooks": _list_webhooks,
        "create_webhook": _create_webhook,
        "get_webhook": _get_webhook,
        "update_webhook": _update_webhook,
        "delete_webhook": _delete_webhook,
        "list_monitor_fields": _list_monitor_fields,
    }
