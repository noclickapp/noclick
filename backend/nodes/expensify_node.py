"""
Expensify expense-management automation node.

Provides workflow integration with the Expensify Integration Server API. Every
operation hits the single POST endpoint and is selected by the top-level `type`
field (and, for create/get/update jobs, an `inputSettings.type` discriminator).

Operations:
- Exports: export reports to file, download generated file, reconciliation export
- Create: report, expenses, policy (workspace), expense rules
- Get: policy details, policy list, domain card list
- Update: policy, report status (reimburse), expense rules, tag approvers,
  advanced employee updater

Authentication: Partner credentials (partnerUserID + partnerUserSecret) passed
inside the JSON `requestJobDescription` payload (not HTTP headers). No OAuth.
API Base URL: https://integrations.expensify.com/Integration-Server/ExpensifyIntegrations
Documentation: https://integrations.expensify.com/Integration-Server/doc/

Webhooks: not supported by the Expensify API. The `on_new_report` trigger is
therefore poll-based (via ScheduledPollTriggerMixin): each scheduled poll runs
the two-step export (generate a JSON report-metadata file, then download it) and
emits only reports not seen before.
The payload is form-encoded (application/x-www-form-urlencoded), with the JSON
job description in a `requestJobDescription` form field and an optional separate
`template` field for export jobs.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

logger = logging.getLogger(__name__)

EXPENSIFY_API_BASE = "https://integrations.expensify.com/Integration-Server/ExpensifyIntegrations"

# The combinedReportData exporter requires at least one of startDate/reportIDList/
# approvedAfter; this early date means "everything" when the user gives no filter.
_ALL_TIME_START = "2000-01-01"
# get/policy requires a non-empty `fields` list — default to the full set.
_ALL_POLICY_FIELDS = ["categories", "reportFields", "tags", "tax", "employees"]

# A minimal Freemarker template that emits a CSV row per transaction. Exports
# require a template; this is a sensible default the user can override.
DEFAULT_EXPORT_TEMPLATE = (
    "<#list reports as report>${report.reportName},${report.total}\n"
    "<#list report.transactionList as expense>"
    "${expense.created},${expense.merchant},${expense.amount},${expense.currency}\n"
    "</#list></#list>"
)

# Freemarker template emitting one JSON object per report (id, name, created,
# submitted, status) as a JSON array. Used by the poll trigger to read report
# metadata so it can cursor on report id / created date.
POLL_REPORT_TEMPLATE = (
    "[<#list reports as report>"
    '{"reportID":"${report.reportID}",'
    '"reportName":"${report.reportName}",'
    '"created":"${report.created}",'
    '"submitted":"${report.submitted!\'\'}",'
    '"status":"${report.status!\'\'}"}'
    "<#if report_has_next>,</#if>"
    "</#list>]"
)


# ============================================================================
# Credential Schema
# ============================================================================


class ExpensifyPartnerCredential(BaseModel):
    """Partner credential (partnerUserID + partnerUserSecret) for Expensify."""

    credential_type: Literal["expensify_partner"] = Field(
        "expensify_partner", json_schema_extra={"ui:hidden": True}
    )
    partner_user_id: str = Field(
        ...,
        title="Partner User ID",
        description="partnerUserID generated at expensify.com/tools/integrations",
        json_schema_extra={"ui:widget": "password"},
    )
    partner_user_secret: str = Field(
        ...,
        title="Partner User Secret",
        description="partnerUserSecret generated alongside the ID (shown only once)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://www.expensify.com/tools/integrations/",
            "x-credential-instructions": (
                "Generate partner credentials at expensify.com/tools/integrations. "
                "Both values are shown only once — store them securely."
            ),
        }
    )


ExpensifyCredential = ExpensifyPartnerCredential


# ============================================================================
# Operation Configs
# ============================================================================


class ExpensifyExportReportsConfig(BaseModel):
    """Generate an export of report/expense data via a Freemarker template."""

    operation: Literal["export_reports"] = Field(
        "export_reports",
        json_schema_extra={
            "const": "export_reports",
            "ui:hidden": True,
            "x-category": "Exports",
            "x-is-trigger": False,
            "x-display-name": "Export Reports to File",
        },
        title="Export Reports to File",
    )
    template: Optional[str] = Field(
        None,
        title="Freemarker Template",
        description="Freemarker template controlling the export output. Defaults to a per-transaction CSV.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    file_extension: str = Field(
        "csv",
        title="File Extension",
        description="Output file extension",
        json_schema_extra={
            "enum": ["csv", "xls", "xlsx", "pdf", "json", "xml", "txt"],
            "enumNames": ["CSV", "XLS", "XLSX", "PDF", "JSON", "XML", "TXT"],
            "x-enum-searchable": True,
        },
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Filter reports starting on/after this date (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Filter reports up to this date (YYYY-MM-DD)"
    )
    report_state: Optional[str] = Field(
        None,
        title="Report State",
        description="Filter by report approval state",
        json_schema_extra={
            "enum": ["", "OPEN", "SUBMITTED", "APPROVED", "REIMBURSED", "ARCHIVED"],
            "enumNames": ["Any", "Open", "Submitted", "Approved", "Reimbursed", "Archived"],
            "x-enum-searchable": True,
        },
    )
    report_id_list: Optional[str] = Field(
        None, title="Report IDs", description="Comma-separated report IDs to export (optional)"
    )
    mark_as_exported: Optional[str] = Field(
        None,
        title="Mark As Exported Label",
        description="If set, marks exported reports with this label to avoid re-pulling them",
    )


class ExpensifyDownloadFileConfig(BaseModel):
    """Download a previously generated export file by name."""

    operation: Literal["download_file"] = Field(
        "download_file",
        json_schema_extra={
            "const": "download_file",
            "ui:hidden": True,
            "x-category": "Exports",
            "x-is-trigger": False,
            "x-display-name": "Download Generated File",
        },
        title="Download Generated File",
    )
    file_name: str = Field(
        ...,
        title="File Name",
        description="The generated filename returned by an export or reconciliation job",
    )
    file_system: str = Field(
        "integrationServer",
        title="File System",
        description="Where the file lives — 'integrationServer' for report exports, 'reconciliation' for reconciliation exports",
        json_schema_extra={
            "enum": ["integrationServer", "reconciliation"],
            "enumNames": ["Report export", "Reconciliation export"],
            "x-enum-searchable": True,
        },
    )


class ExpensifyReconciliationConfig(BaseModel):
    """Export card-transaction data for given card feeds and date range."""

    operation: Literal["reconciliation_export"] = Field(
        "reconciliation_export",
        json_schema_extra={
            "const": "reconciliation_export",
            "ui:hidden": True,
            "x-category": "Exports",
            "x-is-trigger": False,
            "x-display-name": "Reconciliation Export",
        },
        title="Reconciliation Export",
    )
    domain_name: str = Field(
        ..., title="Domain Name", description="The Expensify domain the card feeds belong to"
    )
    start_date: str = Field(
        ..., title="Start Date", description="Start of the transaction date range (YYYY-MM-DD)"
    )
    end_date: str = Field(
        ..., title="End Date", description="End of the transaction date range (YYYY-MM-DD)"
    )
    feed_name: Optional[str] = Field(
        None, title="Card Feed Name", description="Restrict to a specific card feed (optional)"
    )
    reportable_status: str = Field(
        "all",
        title="Transaction Status",
        description="Which transactions to include",
        json_schema_extra={
            "enum": ["all", "unreported"],
            "enumNames": ["All transactions", "Unreported only"],
            "x-enum-searchable": True,
        },
    )
    template: Optional[str] = Field(
        None,
        title="Freemarker Template",
        description="Freemarker template controlling the export output (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ExpensifyCreateReportConfig(BaseModel):
    """Create a new expense report with transactions."""

    operation: Literal["create_report"] = Field(
        "create_report",
        json_schema_extra={
            "const": "create_report",
            "ui:hidden": True,
            "x-category": "Create",
            "x-is-trigger": False,
            "x-display-name": "Create Report",
        },
        title="Create Report",
    )
    policy_id: str = Field(
        ...,
        title="Policy (Workspace)",
        description="The policy/workspace ID the report belongs to",
        json_schema_extra={
            "x-resource-type": "expensify_policy",
            "x-dynamic-options": {
                "field_name": "policy_id",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a policy ID",
            }
        },
    )
    employee_email: str = Field(
        ..., title="Employee Email", description="Email of the user the report is created for"
    )
    report_title: str = Field(..., title="Report Title", description="Title of the new report")
    expenses_json: Optional[str] = Field(
        None,
        title="Expenses (JSON)",
        description='JSON array of expense objects, e.g. [{"created":"2026-01-01","merchant":"Cab","amount":1500,"currency":"USD"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ExpensifyCreateExpensesConfig(BaseModel):
    """Create individual expenses in a user's account."""

    operation: Literal["create_expenses"] = Field(
        "create_expenses",
        json_schema_extra={
            "const": "create_expenses",
            "ui:hidden": True,
            "x-category": "Create",
            "x-is-trigger": False,
            "x-display-name": "Create Expenses",
        },
        title="Create Expenses",
    )
    employee_email: str = Field(
        ..., title="Employee Email", description="Email of the user the expenses are created for"
    )
    expenses_json: str = Field(
        ...,
        title="Expenses (JSON)",
        description='JSON array of expense objects, e.g. [{"created":"2026-01-01","merchant":"Cab","amount":1500,"currency":"USD","category":"Travel"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    policy_id: Optional[str] = Field(
        None,
        title="Policy (Workspace)",
        description="Optional policy/workspace to assign the expenses to",
        json_schema_extra={
            "x-resource-type": "expensify_policy",
            "x-dynamic-options": {
                "field_name": "policy_id",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a policy ID",
            }
        },
    )


class ExpensifyCreatePolicyConfig(BaseModel):
    """Create a new workspace policy."""

    operation: Literal["create_policy"] = Field(
        "create_policy",
        json_schema_extra={
            "const": "create_policy",
            "x-creates-resource": True,
            "x-resource-type": "expensify_policy",
            "x-resource-id-path": "data.policyID",
            "ui:hidden": True,
            "x-category": "Create",
            "x-is-trigger": False,
            "x-display-name": "Create Policy",
        },
        title="Create Policy",
    )
    policy_name: str = Field(..., title="Policy Name", description="Name of the new workspace policy")
    policy_plan: str = Field(
        "team",
        title="Plan",
        description="The plan type for the new policy",
        json_schema_extra={
            "enum": ["team", "corporate"],
            "enumNames": ["Team (Collect)", "Corporate (Control)"],
            "x-enum-searchable": True,
        },
    )


class ExpensifyCreateExpenseRulesConfig(BaseModel):
    """Create automatic expense-tagging rules for an employee."""

    operation: Literal["create_expense_rules"] = Field(
        "create_expense_rules",
        json_schema_extra={
            "const": "create_expense_rules",
            "ui:hidden": True,
            "x-category": "Create",
            "x-is-trigger": False,
            "x-display-name": "Create Expense Rules",
        },
        title="Create Expense Rules",
    )
    policy_id: str = Field(
        ...,
        title="Policy (Workspace)",
        description="The policy the rules apply to",
        json_schema_extra={
            "x-resource-type": "expensify_policy",
            "x-dynamic-options": {
                "field_name": "policy_id",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a policy ID",
            }
        },
    )
    employee_email: str = Field(
        ..., title="Employee Email", description="Email of the employee the rules apply to"
    )
    rules_json: str = Field(
        ...,
        title="Rule Actions (JSON)",
        description='JSON "actions" object for the rule, e.g. {"tag":"Travel","defaultBillable":true}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ExpensifyGetPolicyConfig(BaseModel):
    """Retrieve full policy config (categories, tags, tax rates, employees)."""

    operation: Literal["get_policy"] = Field(
        "get_policy",
        json_schema_extra={
            "const": "get_policy",
            "ui:hidden": True,
            "x-category": "Get",
            "x-is-trigger": False,
            "x-display-name": "Get Policy Details",
        },
        title="Get Policy Details",
    )
    policy_id_list: str = Field(
        ...,
        title="Policy IDs",
        description="Comma-separated policy/workspace IDs to retrieve",
    )
    fields: Optional[str] = Field(
        None,
        title="Fields Filter",
        description="Comma-separated fields to include (e.g. categories,tags,reportFields). Empty returns all.",
    )


class ExpensifyGetPolicyListConfig(BaseModel):
    """List all policies accessible to the credential's user."""

    operation: Literal["get_policy_list"] = Field(
        "get_policy_list",
        json_schema_extra={
            "const": "get_policy_list",
            "ui:hidden": True,
            "x-category": "Get",
            "x-is-trigger": False,
            "x-display-name": "Get Policy List",
        },
        title="Get Policy List",
    )
    admin_only: str = Field(
        "false",
        title="Admin Policies Only",
        description="Only return policies where the user is an admin",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class ExpensifyGetDomainCardListConfig(BaseModel):
    """Retrieve corporate (domain-level) card info."""

    operation: Literal["get_domain_card_list"] = Field(
        "get_domain_card_list",
        json_schema_extra={
            "const": "get_domain_card_list",
            "ui:hidden": True,
            "x-category": "Get",
            "x-is-trigger": False,
            "x-display-name": "Get Domain Card List",
        },
        title="Get Domain Card List",
    )
    domain_name: str = Field(
        ..., title="Domain Name", description="The Expensify domain to list cards for"
    )


class ExpensifyUpdatePolicyConfig(BaseModel):
    """Manage categories, tags, and report fields on a policy."""

    operation: Literal["update_policy"] = Field(
        "update_policy",
        json_schema_extra={
            "const": "update_policy",
            "ui:hidden": True,
            "x-category": "Update",
            "x-is-trigger": False,
            "x-display-name": "Update Policy",
        },
        title="Update Policy",
    )
    policy_id: str = Field(
        ...,
        title="Policy (Workspace)",
        description="The policy/workspace to update",
        json_schema_extra={
            "x-resource-type": "expensify_policy",
            "x-dynamic-options": {
                "field_name": "policy_id",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a policy ID",
            }
        },
    )
    update_type: str = Field(
        "categories",
        title="Update Type",
        description="What to manage on the policy",
        json_schema_extra={
            "enum": ["categories", "tags", "reportFields"],
            "enumNames": ["Categories", "Tags", "Report Fields"],
            "x-enum-searchable": True,
        },
    )
    data_json: str = Field(
        ...,
        title="Data (JSON)",
        description="JSON payload describing the categories/tags/report fields to merge or replace",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ExpensifyUpdateReportStatusConfig(BaseModel):
    """Mark reports as reimbursed."""

    operation: Literal["update_report_status"] = Field(
        "update_report_status",
        json_schema_extra={
            "const": "update_report_status",
            "ui:hidden": True,
            "x-category": "Update",
            "x-is-trigger": False,
            "x-display-name": "Mark Reports Reimbursed",
        },
        title="Mark Reports Reimbursed",
    )
    report_id_list: Optional[str] = Field(
        None, title="Report IDs", description="Comma-separated report IDs to reimburse"
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Reimburse reports starting on/after this date (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Reimburse reports up to this date (YYYY-MM-DD)"
    )


class ExpensifyUpdateExpenseRulesConfig(BaseModel):
    """Modify existing expense rules for an employee."""

    operation: Literal["update_expense_rules"] = Field(
        "update_expense_rules",
        json_schema_extra={
            "const": "update_expense_rules",
            "ui:hidden": True,
            "x-category": "Update",
            "x-is-trigger": False,
            "x-display-name": "Update Expense Rules",
        },
        title="Update Expense Rules",
    )
    policy_id: str = Field(
        ...,
        title="Policy (Workspace)",
        description="The policy the rules belong to",
        json_schema_extra={
            "x-resource-type": "expensify_policy",
            "x-dynamic-options": {
                "field_name": "policy_id",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a policy ID",
            }
        },
    )
    employee_email: str = Field(
        ..., title="Employee Email", description="Email of the employee whose rule to update"
    )
    rule_id: str = Field(
        ..., title="Rule ID", description="The numeric ID of the existing rule to modify"
    )
    rules_json: str = Field(
        ...,
        title="Rule Actions (JSON)",
        description='JSON "actions" object for the rule, e.g. {"tag":"Travel"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ExpensifyUpdateTagApproversConfig(BaseModel):
    """Assign approvers to specific single-level tags."""

    operation: Literal["update_tag_approvers"] = Field(
        "update_tag_approvers",
        json_schema_extra={
            "const": "update_tag_approvers",
            "ui:hidden": True,
            "x-category": "Update",
            "x-is-trigger": False,
            "x-display-name": "Update Tag Approvers",
        },
        title="Update Tag Approvers",
    )
    policy_id: str = Field(
        ...,
        title="Policy (Workspace)",
        description="The policy the tags belong to",
        json_schema_extra={
            "x-resource-type": "expensify_policy",
            "x-dynamic-options": {
                "field_name": "policy_id",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a policy ID",
            }
        },
    )
    approvers_json: str = Field(
        ...,
        title="Tag Approvers (JSON)",
        description='JSON array mapping tags to approver emails, e.g. [{"tag":"Marketing","approver":"lead@co.com"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class ExpensifyAdvancedEmployeeUpdaterConfig(BaseModel):
    """Modern employee provisioning (emails, managers, admin status, payroll)."""

    operation: Literal["advanced_employee_updater"] = Field(
        "advanced_employee_updater",
        json_schema_extra={
            "const": "advanced_employee_updater",
            "ui:hidden": True,
            "x-category": "Update",
            "x-is-trigger": False,
            "x-display-name": "Advanced Employee Updater",
        },
        title="Advanced Employee Updater",
    )
    policy_id: str = Field(
        ...,
        title="Policy (Workspace)",
        description="The policy to provision employees in",
        json_schema_extra={
            "x-resource-type": "expensify_policy",
            "x-dynamic-options": {
                "field_name": "policy_id",
                "placeholder": "Select a workspace...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a policy ID",
            }
        },
    )
    employees_json: str = Field(
        ...,
        title="Employees (JSON)",
        description="JSON array of employee objects (email, manager, admin, payroll data)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Trigger Config (poll-based)
# ============================================================================


class ExpensifyOnNewReportConfig(PollTriggerConfigBase):
    """Poll the report exporter for newly submitted/created reports.

    Expensify has no outbound webhooks, so the trigger polls the Integration
    Server on a schedule. Each poll runs the two-step export (generate a JSON
    report-metadata file, then download it) and emits only reports not seen on a
    previous poll. Webhook + schedule provisioning, seen-set persistence, and
    teardown come from ``ScheduledPollTriggerMixin``.
    """

    operation: Literal["on_new_report"] = Field(
        "on_new_report",
        title="On New Report",
        description="Trigger the workflow when a new report is submitted/created",
        json_schema_extra={
            "ui:hidden": True,
            "const": "on_new_report",
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On New Report",
        },
    )
    report_state: str = Field(
        "SUBMITTED",
        title="Report State",
        description="Only trigger on reports in this approval state",
        json_schema_extra={
            "enum": ["", "OPEN", "SUBMITTED", "APPROVED", "REIMBURSED", "ARCHIVED"],
            "enumNames": ["Any", "Open", "Submitted", "Approved", "Reimbursed", "Archived"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Discriminated Union
# ============================================================================


ExpensifyConfig = Annotated[
    Union[
        ExpensifyExportReportsConfig,
        ExpensifyDownloadFileConfig,
        ExpensifyReconciliationConfig,
        ExpensifyCreateReportConfig,
        ExpensifyCreateExpensesConfig,
        ExpensifyCreatePolicyConfig,
        ExpensifyCreateExpenseRulesConfig,
        ExpensifyGetPolicyConfig,
        ExpensifyGetPolicyListConfig,
        ExpensifyGetDomainCardListConfig,
        ExpensifyUpdatePolicyConfig,
        ExpensifyUpdateReportStatusConfig,
        ExpensifyUpdateExpenseRulesConfig,
        ExpensifyUpdateTagApproversConfig,
        ExpensifyAdvancedEmployeeUpdaterConfig,
        ExpensifyOnNewReportConfig,
    ],
    Discriminator("operation"),
]


class ExpensifyNodeConfig(NodeConfig[ExpensifyConfig, ExpensifyCredential]):
    """Full configuration for the Expensify node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _parse_json(value: Optional[str], field_label: str) -> Any:
    """Parse a JSON string field, raising a clear error on bad input."""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field_label} is not valid JSON: {e}")


async def _expensify_request(
    credential: ExpensifyCredential,
    job_description: Dict[str, Any],
    action_name: str,
    template: Optional[str] = None,
    data_field: Optional[str] = None,
    expect_file: bool = False,
) -> Dict[str, Any]:
    """POST a job description to the Expensify Integration Server.

    The Expensify API takes a form-encoded body: the JSON job description in a
    `requestJobDescription` field, an optional `template` field (export jobs), and
    an optional `data` field (employee-updater records, sent separately from the
    job description). Partner credentials are embedded inside the JSON payload.
    """
    payload = {
        "credentials": {
            "partnerUserID": credential.partner_user_id,
            "partnerUserSecret": credential.partner_user_secret,
        },
        **job_description,
    }
    form: Dict[str, str] = {"requestJobDescription": json.dumps(payload)}
    if template is not None:
        form["template"] = template
    if data_field is not None:
        form["data"] = data_field

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(EXPENSIFY_API_BASE, data=form)
            api_ms = round((time.time() - start) * 1000, 2)

            if response.status_code >= 400:
                logger.error(f"[ExpensifyNode] API error ({action_name}): {response.text}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": response.text,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            text = response.text
            # The Integration Server returns JSON for control/get jobs and raw
            # file bytes for downloads. Try JSON first, fall back to raw text.
            data: Any
            try:
                data = response.json()
            except Exception:
                data = {"raw": text}

            # Expensify signals failures with a non-zero responseCode in a 200 body.
            if isinstance(data, dict) and data.get("responseCode") not in (None, 200):
                message = data.get("responseMessage") or data.get("message") or str(data)
                logger.error(f"[ExpensifyNode] Job error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": data.get("responseCode"),
                    "timing_ms": {"api_request": api_ms},
                }

            if expect_file and isinstance(data, dict) and "raw" in data:
                data = {"file_contents": text}

            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[ExpensifyNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class ExpensifyNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Expensify expense-management automation node."""

    edit_examples = [
        "Export all approved reports from last month to a CSV file",
        "Create an expense report for an employee with a list of transactions",
        "Mark a batch of reports as reimbursed",
        "List all the workspaces I can access",
        "Create a new corporate workspace policy",
    ]

    @classmethod
    def get_config_model(cls):
        return ExpensifyNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (policies / workspaces)
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
        """Load the workspace (policy) dropdown. ``credential_data`` arrives
        already decrypted from the handler — build the partner credential off it."""
        if field_name != "policy_id":
            return {"options": []}
        cred_data = credential_data or {}
        if not cred_data.get("partner_user_id"):
            return {"options": []}

        credential = ExpensifyPartnerCredential(
            partner_user_id=cred_data.get("partner_user_id", ""),
            partner_user_secret=cred_data.get("partner_user_secret", ""),
        )
        result = await _expensify_request(
            credential,
            {"type": "get", "inputSettings": {"type": "policyList"}},
            action_name="get_policy_list",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        policies = data.get("policyList") if isinstance(data, dict) else None
        if not isinstance(policies, list):
            return {"options": []}
        options = []
        for p in policies:
            if not isinstance(p, dict):
                continue
            pid = p.get("id") or p.get("policyID")
            name = p.get("name") or p.get("policyName") or f"Policy {pid}"
            if pid is not None:
                options.append({"label": str(name), "value": str(pid)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ExpensifyNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Expensify partner credentials.")

        handlers = {
            "export_reports": self._export_reports,
            "download_file": self._download_file,
            "reconciliation_export": self._reconciliation_export,
            "create_report": self._create_report,
            "create_expenses": self._create_expenses,
            "create_policy": self._create_policy,
            "create_expense_rules": self._create_expense_rules,
            "get_policy": self._get_policy,
            "get_policy_list": self._get_policy_list,
            "get_domain_card_list": self._get_domain_card_list,
            "update_policy": self._update_policy,
            "update_report_status": self._update_report_status,
            "update_expense_rules": self._update_expense_rules,
            "update_tag_approvers": self._update_tag_approvers,
            "advanced_employee_updater": self._advanced_employee_updater,
            "on_new_report": self._on_new_report,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, credentials)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _export_reports(
        self, c: ExpensifyExportReportsConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        filters: Dict[str, Any] = {}
        if c.start_date:
            filters["startDate"] = c.start_date
        if c.end_date:
            filters["endDate"] = c.end_date
        if c.report_state:
            filters["reportState"] = c.report_state
        report_ids = _comma_list(c.report_id_list)
        if report_ids:
            filters["reportIDList"] = ",".join(report_ids)
        if c.mark_as_exported:
            filters["markedAsExported"] = c.mark_as_exported
        # The exporter rejects a filter set without startDate/reportIDList; default
        # to all-time so "export everything" works without a date.
        if "startDate" not in filters and "reportIDList" not in filters:
            filters["startDate"] = _ALL_TIME_START

        job = {
            "type": "file",
            # Required: return the generated file name so it can be downloaded.
            "onReceive": {"immediateResponse": ["returnRandomFileName"]},
            "inputSettings": {"type": "combinedReportData", "filters": filters},
            "outputSettings": {"fileExtension": c.file_extension},
        }
        return await _expensify_request(
            cred, job, action_name="export_reports", template=c.template or DEFAULT_EXPORT_TEMPLATE
        )

    async def _download_file(
        self, c: ExpensifyDownloadFileConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        job = {"type": "download", "fileName": c.file_name, "fileSystem": c.file_system}
        return await _expensify_request(
            cred, job, action_name="download_file", expect_file=True
        )

    async def _reconciliation_export(
        self, c: ExpensifyReconciliationConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        input_settings: Dict[str, Any] = {
            "type": "transactionList",
            "domain": c.domain_name,
            "startDate": c.start_date,
            "endDate": c.end_date,
            "reportableStatus": c.reportable_status,
        }
        if c.feed_name:
            input_settings["feedName"] = c.feed_name
        job = {
            "type": "reconciliation",
            "inputSettings": input_settings,
            "outputSettings": {"fileExtension": "csv"},
        }
        return await _expensify_request(
            cred,
            job,
            action_name="reconciliation_export",
            template=c.template or DEFAULT_EXPORT_TEMPLATE,
        )

    async def _create_report(
        self, c: ExpensifyCreateReportConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        input_settings: Dict[str, Any] = {
            "type": "report",
            "policyID": c.policy_id,
            "employeeEmail": c.employee_email,
            "report": {"title": c.report_title},
        }
        expenses = _parse_json(c.expenses_json, "Expenses (JSON)")
        if expenses is not None:
            # `expenses` is a sibling of `report` in inputSettings, not nested.
            input_settings["expenses"] = expenses
        job = {"type": "create", "inputSettings": input_settings}
        return await _expensify_request(cred, job, action_name="create_report")

    async def _create_expenses(
        self, c: ExpensifyCreateExpensesConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        input_settings: Dict[str, Any] = {
            "type": "expenses",
            "employeeEmail": c.employee_email,
            "transactionList": _parse_json(c.expenses_json, "Expenses (JSON)"),
        }
        if c.policy_id:
            input_settings["policyID"] = c.policy_id
        job = {"type": "create", "inputSettings": input_settings}
        return await _expensify_request(cred, job, action_name="create_expenses")

    async def _create_policy(
        self, c: ExpensifyCreatePolicyConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        job = {
            "type": "create",
            "inputSettings": {
                "type": "policy",
                "policyName": c.policy_name,
                "policyType": c.policy_plan,
            },
        }
        return await _expensify_request(cred, job, action_name="create_policy")

    async def _create_expense_rules(
        self, c: ExpensifyCreateExpenseRulesConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        job = {
            "type": "create",
            "inputSettings": {
                "type": "expenseRules",
                "policyID": c.policy_id,
                "employeeEmail": c.employee_email,
                "actions": _parse_json(c.rules_json, "Rule Actions (JSON)"),
            },
        }
        return await _expensify_request(cred, job, action_name="create_expense_rules")

    async def _get_policy(
        self, c: ExpensifyGetPolicyConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        # `fields` is required by the API — default to the full set when unset.
        input_settings: Dict[str, Any] = {
            "type": "policy",
            "policyIDList": _comma_list(c.policy_id_list) or [],
            "fields": _comma_list(c.fields) or _ALL_POLICY_FIELDS,
        }
        job = {"type": "get", "inputSettings": input_settings}
        return await _expensify_request(cred, job, action_name="get_policy")

    async def _get_policy_list(
        self, c: ExpensifyGetPolicyListConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        input_settings: Dict[str, Any] = {"type": "policyList"}
        if c.admin_only == "true":
            input_settings["adminOnly"] = True
        job = {"type": "get", "inputSettings": input_settings}
        return await _expensify_request(cred, job, action_name="get_policy_list")

    async def _get_domain_card_list(
        self, c: ExpensifyGetDomainCardListConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        job = {
            "type": "get",
            "inputSettings": {"type": "domainCardList", "domain": c.domain_name},
        }
        return await _expensify_request(cred, job, action_name="get_domain_card_list")

    async def _update_policy(
        self, c: ExpensifyUpdatePolicyConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        job = {
            "type": "update",
            "inputSettings": {
                "type": "policy",
                "policyID": c.policy_id,
                c.update_type: _parse_json(c.data_json, "Data (JSON)"),
            },
        }
        return await _expensify_request(cred, job, action_name="update_policy")

    async def _update_report_status(
        self, c: ExpensifyUpdateReportStatusConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        # reportIDList / date range go under a `filters` object, not directly in
        # inputSettings, and the field is `status` (only value: REIMBURSED).
        filters: Dict[str, Any] = {}
        report_ids = _comma_list(c.report_id_list)
        if report_ids:
            filters["reportIDList"] = ",".join(report_ids)
        if c.start_date:
            filters["startDate"] = c.start_date
        if c.end_date:
            filters["endDate"] = c.end_date
        input_settings: Dict[str, Any] = {"type": "reportStatus", "status": "REIMBURSED"}
        if filters:
            input_settings["filters"] = filters
        job = {"type": "update", "inputSettings": input_settings}
        return await _expensify_request(cred, job, action_name="update_report_status")

    async def _update_expense_rules(
        self, c: ExpensifyUpdateExpenseRulesConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        input_settings: Dict[str, Any] = {
            "type": "expenseRules",
            "policyID": c.policy_id,
            "employeeEmail": c.employee_email,
            "ruleID": int(c.rule_id),
            "actions": _parse_json(c.rules_json, "Rule Actions (JSON)"),
        }
        job = {"type": "update", "inputSettings": input_settings}
        return await _expensify_request(cred, job, action_name="update_expense_rules")

    async def _update_tag_approvers(
        self, c: ExpensifyUpdateTagApproversConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        job = {
            "type": "update",
            "inputSettings": {
                "type": "tagApprovers",
                "policyID": c.policy_id,
                "tagApprovers": _parse_json(c.approvers_json, "Tag Approvers (JSON)"),
            },
        }
        return await _expensify_request(cred, job, action_name="update_tag_approvers")

    async def _advanced_employee_updater(
        self, c: ExpensifyAdvancedEmployeeUpdaterConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        # Advanced Employee Updater: update/employees with entity=generic; the
        # employee records are sent inline in a SEPARATE `data` form field (not
        # inside requestJobDescription), per the Integration Server docs.
        _parse_json(c.employees_json, "Employees (JSON)")  # validate JSON up-front
        job = {
            "type": "update",
            "dataSource": "request",
            "inputSettings": {"type": "employees", "entity": "generic"},
        }
        return await _expensify_request(
            cred, job, action_name="advanced_employee_updater", data_field=c.employees_json
        )


    # ------------------------------------------------------------------
    # Trigger handler (poll)
    # ------------------------------------------------------------------
    async def _on_new_report(
        self, c: ExpensifyOnNewReportConfig, cred: ExpensifyCredential
    ) -> Dict[str, Any]:
        """Poll for newly submitted/created reports and emit only unseen ones.

        Expensify exports are two-step: a ``file`` job generates a JSON
        report-metadata file and returns its NAME, then a ``download`` job fetches
        the contents. Dedup + persistence come from
        ``ScheduledPollTriggerMixin._filter_unseen`` (baselines on the first poll,
        then emits only reportIDs not seen before; seen-set persisted in node
        state so dedup holds across polls)."""
        # startDate is required by the exporter; pull all-time and let the seen-set
        # dedup — the mixin baselines on the first poll then emits only new reports.
        filters: Dict[str, Any] = {"startDate": _ALL_TIME_START}
        if c.report_state:
            filters["reportState"] = c.report_state
        gen_job = {
            "type": "file",
            "onReceive": {"immediateResponse": ["returnRandomFileName"]},
            "inputSettings": {"type": "combinedReportData", "filters": filters},
            "outputSettings": {"fileExtension": "json"},
        }
        gen = await _expensify_request(
            cred, gen_job, action_name="on_new_report", template=POLL_REPORT_TEMPLATE
        )
        if gen.get("status") != "success":
            return gen

        file_name = self._extract_filename(gen.get("data"))
        if not file_name:
            return {
                "status": "error",
                "operation": "on_new_report",
                "error": "Export did not return a file name to download",
            }

        dl = await _expensify_request(
            cred,
            {"type": "download", "fileName": file_name, "fileSystem": "integrationServer"},
            action_name="on_new_report_download",
            expect_file=True,
        )
        if dl.get("status") != "success":
            return dl

        reports = self._parse_poll_reports(dl.get("data"))
        new_reports = await self._filter_unseen(reports, lambda r: str(r.get("reportID")) if r.get("reportID") else None)

        return {
            "status": "success",
            "operation": "on_new_report",
            "items": new_reports,
            "new_count": len(new_reports),
        }

    @staticmethod
    def _extract_filename(data: Any) -> Optional[str]:
        """Pull the generated file name out of a `file`-job response (JSON
        {"filename": ...} or a bare filename surfaced as {"raw": ...})."""
        if isinstance(data, str):
            return data.strip() or None
        if isinstance(data, dict):
            name = data.get("filename") or data.get("fileName") or data.get("raw")
            return str(name).strip() if name else None
        return None

    @staticmethod
    def _parse_poll_reports(data: Any) -> List[Dict[str, Any]]:
        """Extract the report list from a downloaded JSON export.

        The download surfaces file bytes (a JSON array) as {"file_contents": "..."}
        or {"raw": "..."}; a JSON body parses to a list directly."""
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            text = data.get("file_contents") or data.get("raw")
            if text is None:
                return []
            try:
                raw = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return []
        else:
            return []
        return [r for r in raw if isinstance(r, dict) and r.get("reportID")]
