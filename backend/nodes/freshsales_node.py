"""
Freshsales (Freshworks CRM) automation node.

Provides workflow integration with the Freshsales CRM REST API for operations
including:
- Contacts: create, get, update, upsert, delete, list (via saved view)
- Sales Accounts: create, get, update, list (via saved view)
- Deals: create, get, update, list (via saved view)
- Tasks: create, list, update/complete
- Appointments: create, list
- Notes / Sales Activities / Phone Calls: create / log
- Search & Lookup: full-text search, field lookup
- Selectors / Settings: owners, deal stages, contact fields
- Marketing Lists: list, add contacts
- Webhook Trigger: receive outbound webhook events from a Freshsales Workflow

Authentication: API key (per-user) via `Authorization: Token token=<KEY>` header.
The account domain (bundle alias, e.g. `acme.myfreshworks.com`) is account-specific
and is supplied as a credential field; the base URL is built from it.

Documentation: https://developers.freshworks.com/crm/api/
"""

import json
import logging
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client, normalize_provider_subdomain

logger = logging.getLogger(__name__)


def _parse_json(value: Optional[str]) -> Any:
    """Parse a JSON string field. Raises ValueError on bad JSON."""
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")


def _split_ids(raw: str) -> list:
    """Parse a comma-separated ID string into ints where possible."""
    return [int(p.strip()) if p.strip().isdigit() else p.strip()
            for p in (raw or "").split(",") if p.strip()]


def _build_base_url(domain: str) -> str:
    """Build the Freshsales CRM API base URL from the account domain.

    Accepts `acme.myfreshworks.com`, `acme`, or a full URL and normalizes to
    `https://<domain>/crm/sales`. Endpoints are then appended as `/api/...`.
    """
    tenant = normalize_provider_subdomain(
        domain,
        "myfreshworks.com",
        field_name="Freshsales account domain",
    )
    return f"https://{tenant}.myfreshworks.com/crm/sales"


def _op(op: str, category: Optional[str], display: str) -> Dict[str, Any]:
    """Build the standard operation-field json_schema_extra for a config class."""
    return {
        "const": op, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": display,
    }


# Selector endpoints exposed by the generic "List Selector" operation.
FRESHSALES_SELECTORS = [
    "owners", "territories", "deal_stages", "deal_pipelines", "deal_reasons",
    "deal_types", "deal_payment_statuses", "deal_products", "currencies",
    "lead_sources", "industry_types", "business_types", "campaigns",
    "contact_statuses", "lifecycle_stages", "sales_activity_types",
    "sales_activity_outcomes", "designations",
]

# Entities whose field definitions are exposed by "Get Module Fields".
FRESHSALES_FIELD_ENTITIES = ["contacts", "sales_accounts", "deals", "sales_activities"]


# ============================================================================
# Credential Schema
# ============================================================================


class FreshsalesApiKeyCredential(BaseModel):
    """API key credential for Freshsales (Freshworks CRM)."""

    credential_type: Literal["freshsales_api_key"] = Field(
        "freshsales_api_key", json_schema_extra={"ui:hidden": True}
    )
    account_domain: str = Field(
        ...,
        title="Account Domain",
        description="Your Freshsales bundle alias, e.g. acme.myfreshworks.com (find it in your browser address bar)",
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Freshsales API key from Profile picture -> Settings -> API Settings -> Your API Key",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://support.freshsales.io/support/solutions/articles/220099-how-to-find-my-api-key-"
        }
    )


# API-key only. Freshworks' CRM REST API does not honor external OAuth 2.0 tokens
# (ext_oauth JWTs 401 with "Incorrect or expired API key"); the API key is the only
# working auth for the Freshsales REST API.
FreshsalesCredential = FreshsalesApiKeyCredential


# ============================================================================
# Operation Configs — Contacts
# ============================================================================


class FreshsalesCreateContactConfig(BaseModel):
    """Create a new contact."""

    operation: Literal["create_contact"] = Field(
        "create_contact",
        json_schema_extra={
            "const": "create_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Create Contact",
        },
        title="Create Contact",
    )
    first_name: Optional[str] = Field(None, title="First Name", description="Contact's first name")
    last_name: Optional[str] = Field(None, title="Last Name", description="Contact's last name")
    email: str = Field(..., title="Email", description="Contact's primary email address")
    mobile_number: Optional[str] = Field(
        None, title="Mobile Number", description="Contact's mobile phone number"
    )
    work_number: Optional[str] = Field(
        None, title="Work Number", description="Contact's work phone number"
    )
    job_title: Optional[str] = Field(None, title="Job Title", description="Contact's job title")
    owner_id: Optional[str] = Field(
        None,
        title="Owner",
        description="Owner (user) assigned to this contact",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "owner_id",
                "placeholder": "Select an owner...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste owner ID",
            }
        },
    )


class FreshsalesGetContactConfig(BaseModel):
    """Retrieve a single contact by ID."""

    operation: Literal["get_contact"] = Field(
        "get_contact",
        json_schema_extra={
            "const": "get_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Get Contact",
        },
        title="Get Contact",
    )
    contact_id: str = Field(..., title="Contact ID", description="The ID of the contact to retrieve")
    include: Optional[str] = Field(
        None,
        title="Include",
        description="Comma-separated associations to include (e.g. owner,sales_accounts)",
    )


class FreshsalesUpdateContactConfig(BaseModel):
    """Update fields on an existing contact."""

    operation: Literal["update_contact"] = Field(
        "update_contact",
        json_schema_extra={
            "const": "update_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Update Contact",
        },
        title="Update Contact",
    )
    contact_id: str = Field(..., title="Contact ID", description="The ID of the contact to update")
    first_name: Optional[str] = Field(None, title="First Name", description="Updated first name")
    last_name: Optional[str] = Field(None, title="Last Name", description="Updated last name")
    email: Optional[str] = Field(None, title="Email", description="Updated primary email")
    mobile_number: Optional[str] = Field(
        None, title="Mobile Number", description="Updated mobile phone number"
    )
    job_title: Optional[str] = Field(None, title="Job Title", description="Updated job title")
    owner_id: Optional[str] = Field(
        None,
        title="Owner",
        description="Reassign the contact owner",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "owner_id",
                "placeholder": "Select an owner...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste owner ID",
            }
        },
    )


class FreshsalesUpsertContactConfig(BaseModel):
    """Create or update a contact, matched on a unique field (e.g. email)."""

    operation: Literal["upsert_contact"] = Field(
        "upsert_contact",
        json_schema_extra={
            "const": "upsert_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Upsert Contact",
        },
        title="Upsert Contact",
    )
    unique_identifier_field: str = Field(
        "email",
        title="Match Field",
        description="Unique field used to match an existing contact",
        json_schema_extra={
            "enum": ["email", "mobile_number", "work_number"],
            "enumNames": ["Email", "Mobile Number", "Work Number"],
            "x-enum-searchable": True,
        },
    )
    email: str = Field(..., title="Email", description="Contact's email (the match value)")
    first_name: Optional[str] = Field(None, title="First Name", description="Contact's first name")
    last_name: Optional[str] = Field(None, title="Last Name", description="Contact's last name")
    mobile_number: Optional[str] = Field(
        None, title="Mobile Number", description="Contact's mobile phone number"
    )
    job_title: Optional[str] = Field(None, title="Job Title", description="Contact's job title")


class FreshsalesDeleteContactConfig(BaseModel):
    """Delete (move to recycle bin) a contact."""

    operation: Literal["delete_contact"] = Field(
        "delete_contact",
        json_schema_extra={
            "const": "delete_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact",
        },
        title="Delete Contact",
    )
    contact_id: str = Field(..., title="Contact ID", description="The ID of the contact to delete")


class FreshsalesListContactsConfig(BaseModel):
    """List contacts belonging to a saved view."""

    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        json_schema_extra={
            "const": "list_contacts",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "List Contacts (View)",
        },
        title="List Contacts (View)",
    )
    view_id: str = Field(..., title="View ID", description="The ID of the saved contact view to list")
    page: Optional[str] = Field("1", title="Page", description="1-indexed page number")
    sort: Optional[str] = Field(None, title="Sort By", description="Field to sort by")
    sort_type: Optional[str] = Field(
        None,
        title="Sort Direction",
        description="Sort direction",
        json_schema_extra={
            "enum": ["", "asc", "desc"],
            "enumNames": ["Default", "Ascending", "Descending"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Operation Configs — Sales Accounts
# ============================================================================


class FreshsalesCreateAccountConfig(BaseModel):
    """Create a sales account (company/organization)."""

    operation: Literal["create_account"] = Field(
        "create_account",
        json_schema_extra={
            "const": "create_account",
            "ui:hidden": True,
            "x-category": "Accounts",
            "x-is-trigger": False,
            "x-display-name": "Create Account",
        },
        title="Create Account",
    )
    name: str = Field(..., title="Name", description="The account / company name")
    website: Optional[str] = Field(None, title="Website", description="Company website URL")
    phone: Optional[str] = Field(None, title="Phone", description="Company phone number")
    industry_type_id: Optional[str] = Field(
        None, title="Industry Type ID", description="Industry type ID"
    )
    owner_id: Optional[str] = Field(
        None,
        title="Owner",
        description="Owner (user) assigned to this account",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "owner_id",
                "placeholder": "Select an owner...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste owner ID",
            }
        },
    )


class FreshsalesGetAccountConfig(BaseModel):
    """Retrieve a single sales account by ID."""

    operation: Literal["get_account"] = Field(
        "get_account",
        json_schema_extra={
            "const": "get_account",
            "ui:hidden": True,
            "x-category": "Accounts",
            "x-is-trigger": False,
            "x-display-name": "Get Account",
        },
        title="Get Account",
    )
    account_id: str = Field(..., title="Account ID", description="The ID of the account to retrieve")
    include: Optional[str] = Field(
        None, title="Include", description="Comma-separated associations to include"
    )


class FreshsalesUpdateAccountConfig(BaseModel):
    """Update fields on a sales account."""

    operation: Literal["update_account"] = Field(
        "update_account",
        json_schema_extra={
            "const": "update_account",
            "ui:hidden": True,
            "x-category": "Accounts",
            "x-is-trigger": False,
            "x-display-name": "Update Account",
        },
        title="Update Account",
    )
    account_id: str = Field(..., title="Account ID", description="The ID of the account to update")
    name: Optional[str] = Field(None, title="Name", description="Updated account name")
    website: Optional[str] = Field(None, title="Website", description="Updated website URL")
    phone: Optional[str] = Field(None, title="Phone", description="Updated phone number")
    owner_id: Optional[str] = Field(
        None,
        title="Owner",
        description="Reassign the account owner",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "owner_id",
                "placeholder": "Select an owner...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste owner ID",
            }
        },
    )


class FreshsalesListAccountsConfig(BaseModel):
    """List accounts belonging to a saved view."""

    operation: Literal["list_accounts"] = Field(
        "list_accounts",
        json_schema_extra={
            "const": "list_accounts",
            "ui:hidden": True,
            "x-category": "Accounts",
            "x-is-trigger": False,
            "x-display-name": "List Accounts (View)",
        },
        title="List Accounts (View)",
    )
    view_id: str = Field(..., title="View ID", description="The ID of the saved account view to list")
    page: Optional[str] = Field("1", title="Page", description="1-indexed page number")


# ============================================================================
# Operation Configs — Deals
# ============================================================================


class FreshsalesCreateDealConfig(BaseModel):
    """Create a new deal (opportunity)."""

    operation: Literal["create_deal"] = Field(
        "create_deal",
        json_schema_extra={
            "const": "create_deal",
            "ui:hidden": True,
            "x-category": "Deals",
            "x-is-trigger": False,
            "x-display-name": "Create Deal",
        },
        title="Create Deal",
    )
    name: str = Field(..., title="Name", description="The deal name")
    amount: Optional[str] = Field(None, title="Amount", description="Deal value / amount")
    deal_stage_id: Optional[str] = Field(
        None,
        title="Deal Stage",
        description="The pipeline stage of the deal",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "deal_stage_id",
                "placeholder": "Select a deal stage...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste stage ID",
            }
        },
    )
    sales_account_id: Optional[str] = Field(
        None, title="Sales Account ID", description="The sales account this deal belongs to"
    )
    owner_id: Optional[str] = Field(
        None,
        title="Owner",
        description="Owner (user) assigned to this deal",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "owner_id",
                "placeholder": "Select an owner...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste owner ID",
            }
        },
    )
    expected_close: Optional[str] = Field(
        None, title="Expected Close Date", description="Expected close date (YYYY-MM-DD)"
    )


class FreshsalesGetDealConfig(BaseModel):
    """Retrieve a single deal by ID."""

    operation: Literal["get_deal"] = Field(
        "get_deal",
        json_schema_extra={
            "const": "get_deal",
            "ui:hidden": True,
            "x-category": "Deals",
            "x-is-trigger": False,
            "x-display-name": "Get Deal",
        },
        title="Get Deal",
    )
    deal_id: str = Field(..., title="Deal ID", description="The ID of the deal to retrieve")
    include: Optional[str] = Field(
        None, title="Include", description="Comma-separated associations to include"
    )


class FreshsalesUpdateDealConfig(BaseModel):
    """Update a deal (stage, amount, owner, etc.)."""

    operation: Literal["update_deal"] = Field(
        "update_deal",
        json_schema_extra={
            "const": "update_deal",
            "ui:hidden": True,
            "x-category": "Deals",
            "x-is-trigger": False,
            "x-display-name": "Update Deal",
        },
        title="Update Deal",
    )
    deal_id: str = Field(..., title="Deal ID", description="The ID of the deal to update")
    name: Optional[str] = Field(None, title="Name", description="Updated deal name")
    amount: Optional[str] = Field(None, title="Amount", description="Updated deal amount")
    deal_stage_id: Optional[str] = Field(
        None,
        title="Deal Stage",
        description="Move the deal to a different stage",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "deal_stage_id",
                "placeholder": "Select a deal stage...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste stage ID",
            }
        },
    )
    owner_id: Optional[str] = Field(
        None,
        title="Owner",
        description="Reassign the deal owner",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "owner_id",
                "placeholder": "Select an owner...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste owner ID",
            }
        },
    )


class FreshsalesListDealsConfig(BaseModel):
    """List deals belonging to a saved view."""

    operation: Literal["list_deals"] = Field(
        "list_deals",
        json_schema_extra={
            "const": "list_deals",
            "ui:hidden": True,
            "x-category": "Deals",
            "x-is-trigger": False,
            "x-display-name": "List Deals (View)",
        },
        title="List Deals (View)",
    )
    view_id: str = Field(..., title="View ID", description="The ID of the saved deal view to list")
    page: Optional[str] = Field("1", title="Page", description="1-indexed page number")


# ============================================================================
# Operation Configs — Tasks / Appointments
# ============================================================================


class FreshsalesCreateTaskConfig(BaseModel):
    """Create a task linked to a contact / account / deal."""

    operation: Literal["create_task"] = Field(
        "create_task",
        json_schema_extra={
            "const": "create_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Create Task",
        },
        title="Create Task",
    )
    title: str = Field(..., title="Title", description="The task title")
    due_date: str = Field(..., title="Due Date", description="Due date/time in ISO 8601")
    owner_id: Optional[str] = Field(
        None,
        title="Owner",
        description="Owner (user) assigned to this task",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "owner_id",
                "placeholder": "Select an owner...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste owner ID",
            }
        },
    )
    targetable_type: Optional[str] = Field(
        None,
        title="Linked Record Type",
        description="The type of record this task is linked to",
        json_schema_extra={
            "enum": ["", "Contact", "SalesAccount", "Deal"],
            "enumNames": ["None", "Contact", "Sales Account", "Deal"],
            "x-enum-searchable": True,
        },
    )
    targetable_id: Optional[str] = Field(
        None, title="Linked Record ID", description="The ID of the linked record"
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Task description",
        json_schema_extra={"ui:widget": "textarea"},
    )


class FreshsalesListTasksConfig(BaseModel):
    """List tasks filtered by status."""

    operation: Literal["list_tasks"] = Field(
        "list_tasks",
        json_schema_extra={
            "const": "list_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "List Tasks",
        },
        title="List Tasks",
    )
    task_filter: str = Field(
        "open",
        title="Filter",
        description="Which tasks to list",
        json_schema_extra={
            "enum": ["open", "due_today", "overdue", "completed"],
            "enumNames": ["Open", "Due Today", "Overdue", "Completed"],
            "x-enum-searchable": True,
        },
    )


class FreshsalesUpdateTaskConfig(BaseModel):
    """Update a task or mark it complete."""

    operation: Literal["update_task"] = Field(
        "update_task",
        json_schema_extra={
            "const": "update_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Update / Complete Task",
        },
        title="Update / Complete Task",
    )
    task_id: str = Field(..., title="Task ID", description="The ID of the task to update")
    title: Optional[str] = Field(None, title="Title", description="Updated task title")
    due_date: Optional[str] = Field(None, title="Due Date", description="Updated due date (ISO 8601)")
    mark_complete: str = Field(
        "false",
        title="Mark Complete",
        description="Set the task to completed",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FreshsalesCreateAppointmentConfig(BaseModel):
    """Create a calendar appointment with attendees."""

    operation: Literal["create_appointment"] = Field(
        "create_appointment",
        json_schema_extra={
            "const": "create_appointment",
            "ui:hidden": True,
            "x-category": "Appointments",
            "x-is-trigger": False,
            "x-display-name": "Create Appointment",
        },
        title="Create Appointment",
    )
    title: str = Field(..., title="Title", description="The appointment title")
    from_date: str = Field(..., title="Start", description="Start time in ISO 8601")
    end_date: str = Field(..., title="End", description="End time in ISO 8601")
    location: Optional[str] = Field(None, title="Location", description="Appointment location")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Appointment description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    targetable_type: Optional[str] = Field(
        None,
        title="Linked Record Type",
        description="The type of record this appointment is linked to",
        json_schema_extra={
            "enum": ["", "Contact", "SalesAccount", "Deal"],
            "enumNames": ["None", "Contact", "Sales Account", "Deal"],
            "x-enum-searchable": True,
        },
    )
    targetable_id: Optional[str] = Field(
        None, title="Linked Record ID", description="The ID of the linked record"
    )


class FreshsalesListAppointmentsConfig(BaseModel):
    """List appointments filtered by time."""

    operation: Literal["list_appointments"] = Field(
        "list_appointments",
        json_schema_extra={
            "const": "list_appointments",
            "ui:hidden": True,
            "x-category": "Appointments",
            "x-is-trigger": False,
            "x-display-name": "List Appointments",
        },
        title="List Appointments",
    )
    appointment_filter: str = Field(
        "upcoming",
        title="Filter",
        description="Which appointments to list",
        json_schema_extra={
            "enum": ["upcoming", "past"],
            "enumNames": ["Upcoming", "Past"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Operation Configs — Notes / Activities / Calls
# ============================================================================


class FreshsalesCreateNoteConfig(BaseModel):
    """Attach a note to a contact, account, or deal."""

    operation: Literal["create_note"] = Field(
        "create_note",
        json_schema_extra={
            "const": "create_note",
            "ui:hidden": True,
            "x-category": "Activities",
            "x-is-trigger": False,
            "x-display-name": "Create Note",
        },
        title="Create Note",
    )
    description: str = Field(
        ...,
        title="Note",
        description="The note content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    targetable_type: str = Field(
        "Contact",
        title="Linked Record Type",
        description="The type of record this note is attached to",
        json_schema_extra={
            "enum": ["Contact", "SalesAccount", "Deal"],
            "enumNames": ["Contact", "Sales Account", "Deal"],
            "x-enum-searchable": True,
        },
    )
    targetable_id: str = Field(..., title="Linked Record ID", description="The ID of the linked record")


class FreshsalesCreateSalesActivityConfig(BaseModel):
    """Log a sales activity (call, email, custom activity type)."""

    operation: Literal["create_sales_activity"] = Field(
        "create_sales_activity",
        json_schema_extra={
            "const": "create_sales_activity",
            "ui:hidden": True,
            "x-category": "Activities",
            "x-is-trigger": False,
            "x-display-name": "Create Sales Activity",
        },
        title="Create Sales Activity",
    )
    title: str = Field(..., title="Title", description="The sales activity title")
    sales_activity_type_id: str = Field(
        ..., title="Activity Type ID",
        description="A CUSTOM sales-activity type ID (built-in Task/Meeting/etc. are not accepted here)",
    )
    targetable_type: str = Field(
        "Contact",
        title="Linked Record Type",
        description="The type of record this activity is linked to",
        json_schema_extra={
            "enum": ["Contact", "SalesAccount", "Deal"],
            "enumNames": ["Contact", "Sales Account", "Deal"],
            "x-enum-searchable": True,
        },
    )
    targetable_id: str = Field(..., title="Linked Record ID", description="The ID of the linked record")
    start_date: str = Field(..., title="Start Date", description="Activity start time (ISO 8601) — required")
    end_date: str = Field(..., title="End Date", description="Activity end time (ISO 8601) — required")
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="Activity notes",
        json_schema_extra={"ui:widget": "textarea"},
    )


class FreshsalesLogPhoneCallConfig(BaseModel):
    """Manually log a phone call against a record."""

    operation: Literal["log_phone_call"] = Field(
        "log_phone_call",
        json_schema_extra={
            "const": "log_phone_call",
            "ui:hidden": True,
            "x-category": "Activities",
            "x-is-trigger": False,
            "x-display-name": "Log Phone Call",
        },
        title="Log Phone Call",
    )
    call_direction: str = Field(
        "outgoing",
        title="Direction",
        description="The direction of the call",
        json_schema_extra={
            "enum": ["incoming", "outgoing"],
            "enumNames": ["Incoming", "Outgoing"],
            "x-enum-searchable": True,
        },
    )
    targetable_type: str = Field(
        "Contact",
        title="Linked Record Type",
        description="The type of record this call is logged against",
        json_schema_extra={
            "enum": ["Contact", "SalesAccount", "Deal"],
            "enumNames": ["Contact", "Sales Account", "Deal"],
            "x-enum-searchable": True,
        },
    )
    targetable_id: str = Field(..., title="Linked Record ID", description="The ID of the linked record")
    note: Optional[str] = Field(
        None,
        title="Call Note",
        description="Summary / outcome of the call",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Operation Configs — Search / Lookup / Selectors / Settings
# ============================================================================


class FreshsalesSearchConfig(BaseModel):
    """Full-text search across entities."""

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search",
        },
        title="Search",
    )
    query: str = Field(..., title="Query", description="The search query string")
    include: str = Field(
        "contact",
        title="Entities",
        description="Comma-separated entity types to search (contact,sales_account,deal,user)",
    )


class FreshsalesLookupConfig(BaseModel):
    """Look up a record by a specific field (e.g. email)."""

    operation: Literal["lookup"] = Field(
        "lookup",
        json_schema_extra={
            "const": "lookup",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Lookup by Field",
        },
        title="Lookup by Field",
    )
    value: str = Field(..., title="Value", description="The value to look up")
    field: str = Field(
        "email", title="Field", description="The field to match against (e.g. email)"
    )
    entities: str = Field(
        "contact", title="Entities", description="Comma-separated entity types to search"
    )


class FreshsalesListOwnersConfig(BaseModel):
    """List users / owners for assignment dropdowns."""

    operation: Literal["list_owners"] = Field(
        "list_owners",
        json_schema_extra={
            "const": "list_owners",
            "ui:hidden": True,
            "x-category": "Selectors",
            "x-is-trigger": False,
            "x-display-name": "List Owners",
        },
        title="List Owners",
    )


class FreshsalesListDealStagesConfig(BaseModel):
    """List configured deal stages."""

    operation: Literal["list_deal_stages"] = Field(
        "list_deal_stages",
        json_schema_extra={
            "const": "list_deal_stages",
            "ui:hidden": True,
            "x-category": "Selectors",
            "x-is-trigger": False,
            "x-display-name": "List Deal Stages",
        },
        title="List Deal Stages",
    )


class FreshsalesGetContactFieldsConfig(BaseModel):
    """List contact field definitions for dynamic field mapping."""

    operation: Literal["get_contact_fields"] = Field(
        "get_contact_fields",
        json_schema_extra={
            "const": "get_contact_fields",
            "ui:hidden": True,
            "x-category": "Selectors",
            "x-is-trigger": False,
            "x-display-name": "Get Contact Fields",
        },
        title="Get Contact Fields",
    )


# ============================================================================
# Operation Configs — Marketing Lists
# ============================================================================


class FreshsalesListMarketingListsConfig(BaseModel):
    """Fetch all marketing / contact lists."""

    operation: Literal["list_marketing_lists"] = Field(
        "list_marketing_lists",
        json_schema_extra={
            "const": "list_marketing_lists",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "List Marketing Lists",
        },
        title="List Marketing Lists",
    )


class FreshsalesAddContactsToListConfig(BaseModel):
    """Add contacts to a marketing list."""

    operation: Literal["add_contacts_to_list"] = Field(
        "add_contacts_to_list",
        json_schema_extra={
            "const": "add_contacts_to_list",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Add Contacts to List",
        },
        title="Add Contacts to List",
    )
    list_id: str = Field(..., title="List ID", description="The marketing list to add contacts to")
    contact_ids: str = Field(
        ..., title="Contact IDs", description="Comma-separated contact IDs to add"
    )


# ============================================================================
# Webhook Trigger Config (dashboard-configured outbound webhook)
# ============================================================================


class FreshsalesReceiveWebhookConfig(BaseModel):
    """Receive outbound webhook events fired by a Freshsales Workflow."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_webhook"] = Field(
        "receive_webhook",
        json_schema_extra={
            "const": "receive_webhook",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Webhook Events",
        },
        title="Receive Webhook Events",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL as a Webhook action in a Freshsales Workflow (Admin Settings -> Workflows)",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Additional Operation Configs — CRUD completeness, selectors, custom modules
# ============================================================================


class FreshsalesCloneContactConfig(BaseModel):
    """Clone an existing contact."""

    operation: Literal["clone_contact"] = Field("clone_contact", json_schema_extra=_op("clone_contact", "Contacts", "Clone Contact"), title="Clone Contact")
    contact_id: str = Field(..., title="Contact ID", description="The ID of the contact to clone", json_schema_extra={"ui:placeholder": "e.g. 401000012345"})


class FreshsalesForgetContactConfig(BaseModel):
    """Forget (GDPR hard-delete) a contact and its data."""

    operation: Literal["forget_contact"] = Field("forget_contact", json_schema_extra=_op("forget_contact", "Contacts", "Forget Contact (GDPR)"), title="Forget Contact (GDPR)")
    contact_id: str = Field(..., title="Contact ID", description="The ID of the contact to forget", json_schema_extra={"ui:placeholder": "e.g. 401000012345"})


class FreshsalesGetContactActivitiesConfig(BaseModel):
    """List a contact's activity history."""

    operation: Literal["get_contact_activities"] = Field("get_contact_activities", json_schema_extra=_op("get_contact_activities", "Contacts", "Get Contact Activities"), title="Get Contact Activities")
    contact_id: str = Field(..., title="Contact ID", description="The contact whose activities to fetch", json_schema_extra={"ui:placeholder": "e.g. 401000012345"})


class FreshsalesListContactViewsConfig(BaseModel):
    """List saved contact views/filters (returns their IDs for List Contacts)."""

    operation: Literal["list_contact_views"] = Field("list_contact_views", json_schema_extra=_op("list_contact_views", "Contacts", "List Contact Views"), title="List Contact Views")


class FreshsalesUpsertAccountConfig(BaseModel):
    """Create or update a sales account, matched on name."""

    operation: Literal["upsert_account"] = Field("upsert_account", json_schema_extra=_op("upsert_account", "Accounts", "Upsert Account"), title="Upsert Account")
    name: str = Field(..., title="Name", description="Account name (the match value)")
    website: Optional[str] = Field(None, title="Website")
    phone: Optional[str] = Field(None, title="Phone")


class FreshsalesDeleteAccountConfig(BaseModel):
    """Delete (move to recycle bin) a sales account."""

    operation: Literal["delete_account"] = Field("delete_account", json_schema_extra=_op("delete_account", "Accounts", "Delete Account"), title="Delete Account")
    account_id: str = Field(..., title="Account ID", description="The ID of the account to delete", json_schema_extra={"ui:placeholder": "e.g. 401000067890"})


class FreshsalesCloneAccountConfig(BaseModel):
    """Clone an existing sales account."""

    operation: Literal["clone_account"] = Field("clone_account", json_schema_extra=_op("clone_account", "Accounts", "Clone Account"), title="Clone Account")
    account_id: str = Field(..., title="Account ID", json_schema_extra={"ui:placeholder": "e.g. 401000067890"})


class FreshsalesForgetAccountConfig(BaseModel):
    """Forget (GDPR hard-delete) a sales account."""

    operation: Literal["forget_account"] = Field("forget_account", json_schema_extra=_op("forget_account", "Accounts", "Forget Account (GDPR)"), title="Forget Account (GDPR)")
    account_id: str = Field(..., title="Account ID", json_schema_extra={"ui:placeholder": "e.g. 401000067890"})


class FreshsalesListAccountViewsConfig(BaseModel):
    """List saved account views/filters."""

    operation: Literal["list_account_views"] = Field("list_account_views", json_schema_extra=_op("list_account_views", "Accounts", "List Account Views"), title="List Account Views")


class FreshsalesDeleteDealConfig(BaseModel):
    """Delete (move to recycle bin) a deal."""

    operation: Literal["delete_deal"] = Field("delete_deal", json_schema_extra=_op("delete_deal", "Deals", "Delete Deal"), title="Delete Deal")
    deal_id: str = Field(..., title="Deal ID", description="The ID of the deal to delete", json_schema_extra={"ui:placeholder": "e.g. 401000054321"})


class FreshsalesCloneDealConfig(BaseModel):
    """Clone an existing deal."""

    operation: Literal["clone_deal"] = Field("clone_deal", json_schema_extra=_op("clone_deal", "Deals", "Clone Deal"), title="Clone Deal")
    deal_id: str = Field(..., title="Deal ID", json_schema_extra={"ui:placeholder": "e.g. 401000054321"})


class FreshsalesForgetDealConfig(BaseModel):
    """Forget (GDPR hard-delete) a deal."""

    operation: Literal["forget_deal"] = Field("forget_deal", json_schema_extra=_op("forget_deal", "Deals", "Forget Deal (GDPR)"), title="Forget Deal (GDPR)")
    deal_id: str = Field(..., title="Deal ID", json_schema_extra={"ui:placeholder": "e.g. 401000054321"})


class FreshsalesListDealViewsConfig(BaseModel):
    """List saved deal views/filters."""

    operation: Literal["list_deal_views"] = Field("list_deal_views", json_schema_extra=_op("list_deal_views", "Deals", "List Deal Views"), title="List Deal Views")


class FreshsalesGetTaskConfig(BaseModel):
    """Retrieve a single task by ID."""

    operation: Literal["get_task"] = Field("get_task", json_schema_extra=_op("get_task", "Tasks", "Get Task"), title="Get Task")
    task_id: str = Field(..., title="Task ID", json_schema_extra={"ui:placeholder": "e.g. 401000011111"})


class FreshsalesDeleteTaskConfig(BaseModel):
    """Delete a task."""

    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra=_op("delete_task", "Tasks", "Delete Task"), title="Delete Task")
    task_id: str = Field(..., title="Task ID", json_schema_extra={"ui:placeholder": "e.g. 401000011111"})


class FreshsalesGetAppointmentConfig(BaseModel):
    """Retrieve a single appointment by ID."""

    operation: Literal["get_appointment"] = Field("get_appointment", json_schema_extra=_op("get_appointment", "Appointments", "Get Appointment"), title="Get Appointment")
    appointment_id: str = Field(..., title="Appointment ID", json_schema_extra={"ui:placeholder": "e.g. 401000022222"})


class FreshsalesUpdateAppointmentConfig(BaseModel):
    """Update an appointment."""

    operation: Literal["update_appointment"] = Field("update_appointment", json_schema_extra=_op("update_appointment", "Appointments", "Update Appointment"), title="Update Appointment")
    appointment_id: str = Field(..., title="Appointment ID", json_schema_extra={"ui:placeholder": "e.g. 401000022222"})
    title: Optional[str] = Field(None, title="Title")
    from_date: Optional[str] = Field(None, title="Start", description="Start time in ISO 8601")
    end_date: Optional[str] = Field(None, title="End", description="End time in ISO 8601")
    location: Optional[str] = Field(None, title="Location")
    description: Optional[str] = Field(None, title="Description", json_schema_extra={"ui:widget": "textarea"})


class FreshsalesDeleteAppointmentConfig(BaseModel):
    """Delete an appointment."""

    operation: Literal["delete_appointment"] = Field("delete_appointment", json_schema_extra=_op("delete_appointment", "Appointments", "Delete Appointment"), title="Delete Appointment")
    appointment_id: str = Field(..., title="Appointment ID", json_schema_extra={"ui:placeholder": "e.g. 401000022222"})


class FreshsalesUpdateNoteConfig(BaseModel):
    """Update a note's content."""

    operation: Literal["update_note"] = Field("update_note", json_schema_extra=_op("update_note", "Activities", "Update Note"), title="Update Note")
    note_id: str = Field(..., title="Note ID", json_schema_extra={"ui:placeholder": "e.g. 401000033333"})
    description: str = Field(..., title="Note", description="Updated note content", json_schema_extra={"ui:widget": "textarea"})


class FreshsalesDeleteNoteConfig(BaseModel):
    """Delete a note."""

    operation: Literal["delete_note"] = Field("delete_note", json_schema_extra=_op("delete_note", "Activities", "Delete Note"), title="Delete Note")
    note_id: str = Field(..., title="Note ID", json_schema_extra={"ui:placeholder": "e.g. 401000033333"})


class FreshsalesListSalesActivitiesConfig(BaseModel):
    """List sales activities (paginated)."""

    operation: Literal["list_sales_activities"] = Field("list_sales_activities", json_schema_extra=_op("list_sales_activities", "Activities", "List Sales Activities"), title="List Sales Activities")
    page: Optional[str] = Field("1", title="Page", json_schema_extra={"ui:placeholder": "e.g. 1"})


class FreshsalesGetSalesActivityConfig(BaseModel):
    """Retrieve a single sales activity by ID."""

    operation: Literal["get_sales_activity"] = Field("get_sales_activity", json_schema_extra=_op("get_sales_activity", "Activities", "Get Sales Activity"), title="Get Sales Activity")
    sales_activity_id: str = Field(..., title="Sales Activity ID", json_schema_extra={"ui:placeholder": "e.g. 401000044444"})


class FreshsalesUpdateSalesActivityConfig(BaseModel):
    """Update a sales activity."""

    operation: Literal["update_sales_activity"] = Field("update_sales_activity", json_schema_extra=_op("update_sales_activity", "Activities", "Update Sales Activity"), title="Update Sales Activity")
    sales_activity_id: str = Field(..., title="Sales Activity ID", json_schema_extra={"ui:placeholder": "e.g. 401000044444"})
    title: Optional[str] = Field(None, title="Title")
    notes: Optional[str] = Field(None, title="Notes", json_schema_extra={"ui:widget": "textarea"})


class FreshsalesDeleteSalesActivityConfig(BaseModel):
    """Delete a sales activity."""

    operation: Literal["delete_sales_activity"] = Field("delete_sales_activity", json_schema_extra=_op("delete_sales_activity", "Activities", "Delete Sales Activity"), title="Delete Sales Activity")
    sales_activity_id: str = Field(..., title="Sales Activity ID", json_schema_extra={"ui:placeholder": "e.g. 401000044444"})


class FreshsalesListSelectorConfig(BaseModel):
    """List values from any Freshsales selector (pipelines, types, currencies, etc.)."""

    operation: Literal["list_selector"] = Field("list_selector", json_schema_extra=_op("list_selector", "Selectors", "List Selector"), title="List Selector")
    selector: str = Field(
        "deal_pipelines", title="Selector",
        description="Which selector list to fetch",
        json_schema_extra={"enum": FRESHSALES_SELECTORS, "x-enum-searchable": True},
    )


class FreshsalesGetModuleFieldsConfig(BaseModel):
    """List field definitions for a module (contacts / accounts / deals / activities)."""

    operation: Literal["get_module_fields"] = Field("get_module_fields", json_schema_extra=_op("get_module_fields", "Selectors", "Get Module Fields"), title="Get Module Fields")
    entity: str = Field(
        "contacts", title="Module",
        description="Which module's field definitions to fetch",
        json_schema_extra={"enum": FRESHSALES_FIELD_ENTITIES, "enumNames": ["Contacts", "Sales Accounts", "Deals", "Sales Activities"], "x-enum-searchable": True},
    )


class FreshsalesFilteredSearchConfig(BaseModel):
    """Query records of an entity by arbitrary field conditions (filter rules)."""

    operation: Literal["filtered_search"] = Field("filtered_search", json_schema_extra=_op("filtered_search", "Search", "Filtered Search"), title="Filtered Search")
    entity: str = Field(
        "contact", title="Entity",
        description="Entity to query",
        json_schema_extra={"enum": ["contact", "sales_account", "deal"], "enumNames": ["Contact", "Sales Account", "Deal"], "x-enum-searchable": True},
    )
    filter_rule_json: str = Field(
        ..., title="Filter Rule (JSON)",
        description='Array of field conditions, e.g. [{"attribute":"first_name","operator":"is_in","value":["Sam"]}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    page: Optional[str] = Field("1", title="Page", json_schema_extra={"ui:placeholder": "e.g. 1"})


class FreshsalesCreateCustomRecordConfig(BaseModel):
    """Create a record in a custom module."""

    operation: Literal["cm_create_record"] = Field("cm_create_record", json_schema_extra=_op("cm_create_record", "Custom Modules", "Create Custom Module Record"), title="Create Custom Module Record")
    module_name: str = Field(..., title="Module Name", description="Custom module API name (e.g. cm_projects)", json_schema_extra={"ui:placeholder": "e.g. cm_projects"})
    data_json: str = Field(..., title="Fields (JSON)", description="Map of field name -> value for the record", json_schema_extra={"ui:widget": "textarea"})


class FreshsalesGetCustomRecordConfig(BaseModel):
    """Retrieve a custom-module record by ID."""

    operation: Literal["cm_get_record"] = Field("cm_get_record", json_schema_extra=_op("cm_get_record", "Custom Modules", "Get Custom Module Record"), title="Get Custom Module Record")
    module_name: str = Field(..., title="Module Name", json_schema_extra={"ui:placeholder": "e.g. cm_projects"})
    record_id: str = Field(..., title="Record ID", json_schema_extra={"ui:placeholder": "e.g. 401000099999"})


class FreshsalesUpdateCustomRecordConfig(BaseModel):
    """Update a custom-module record."""

    operation: Literal["cm_update_record"] = Field("cm_update_record", json_schema_extra=_op("cm_update_record", "Custom Modules", "Update Custom Module Record"), title="Update Custom Module Record")
    module_name: str = Field(..., title="Module Name", json_schema_extra={"ui:placeholder": "e.g. cm_projects"})
    record_id: str = Field(..., title="Record ID", json_schema_extra={"ui:placeholder": "e.g. 401000099999"})
    data_json: str = Field(..., title="Fields (JSON)", description="Fields to update", json_schema_extra={"ui:widget": "textarea"})


class FreshsalesDeleteCustomRecordConfig(BaseModel):
    """Delete a custom-module record."""

    operation: Literal["cm_delete_record"] = Field("cm_delete_record", json_schema_extra=_op("cm_delete_record", "Custom Modules", "Delete Custom Module Record"), title="Delete Custom Module Record")
    module_name: str = Field(..., title="Module Name", json_schema_extra={"ui:placeholder": "e.g. cm_projects"})
    record_id: str = Field(..., title="Record ID", json_schema_extra={"ui:placeholder": "e.g. 401000099999"})


class FreshsalesGetListContactsConfig(BaseModel):
    """Fetch all contacts belonging to a marketing list."""

    operation: Literal["get_list_contacts"] = Field("get_list_contacts", json_schema_extra=_op("get_list_contacts", "Lists", "Get List Contacts"), title="Get List Contacts")
    list_id: str = Field(..., title="List ID", json_schema_extra={"ui:placeholder": "e.g. 401000055555"})


class FreshsalesRemoveContactsFromListConfig(BaseModel):
    """Remove contacts from a marketing list."""

    operation: Literal["remove_contacts_from_list"] = Field("remove_contacts_from_list", json_schema_extra=_op("remove_contacts_from_list", "Lists", "Remove Contacts from List"), title="Remove Contacts from List")
    list_id: str = Field(..., title="List ID", json_schema_extra={"ui:placeholder": "e.g. 401000055555"})
    contact_ids: str = Field(..., title="Contact IDs", description="Comma-separated contact IDs to remove")


class FreshsalesCreateDocumentLinkConfig(BaseModel):
    """Attach an external link (document) to a record."""

    operation: Literal["create_document_link"] = Field("create_document_link", json_schema_extra=_op("create_document_link", "Documents", "Attach Link to Record"), title="Attach Link to Record")
    url: str = Field(..., title="URL", description="The link URL to attach", json_schema_extra={"ui:placeholder": "https://..."})
    name: Optional[str] = Field(None, title="Name", description="Display name for the link")
    targetable_type: str = Field(
        "Contact", title="Linked Record Type",
        json_schema_extra={"enum": ["Contact", "SalesAccount", "Deal"], "enumNames": ["Contact", "Sales Account", "Deal"], "x-enum-searchable": True},
    )
    targetable_id: str = Field(..., title="Linked Record ID")


class FreshsalesListDocumentAssociationsConfig(BaseModel):
    """List files and links attached to a record."""

    operation: Literal["list_document_associations"] = Field("list_document_associations", json_schema_extra=_op("list_document_associations", "Documents", "List Record Documents"), title="List Record Documents")
    targetable_type: str = Field(
        "contacts", title="Record Type",
        json_schema_extra={"enum": ["contacts", "sales_accounts", "deals"], "enumNames": ["Contact", "Sales Account", "Deal"], "x-enum-searchable": True},
    )
    record_id: str = Field(..., title="Record ID")


# ============================================================================
# Discriminated Union
# ============================================================================


FreshsalesConfig = Annotated[
    Union[
        FreshsalesCreateContactConfig,
        FreshsalesGetContactConfig,
        FreshsalesUpdateContactConfig,
        FreshsalesUpsertContactConfig,
        FreshsalesDeleteContactConfig,
        FreshsalesListContactsConfig,
        FreshsalesCloneContactConfig,
        FreshsalesForgetContactConfig,
        FreshsalesGetContactActivitiesConfig,
        FreshsalesListContactViewsConfig,
        FreshsalesCreateAccountConfig,
        FreshsalesGetAccountConfig,
        FreshsalesUpdateAccountConfig,
        FreshsalesListAccountsConfig,
        FreshsalesUpsertAccountConfig,
        FreshsalesDeleteAccountConfig,
        FreshsalesCloneAccountConfig,
        FreshsalesForgetAccountConfig,
        FreshsalesListAccountViewsConfig,
        FreshsalesCreateDealConfig,
        FreshsalesGetDealConfig,
        FreshsalesUpdateDealConfig,
        FreshsalesListDealsConfig,
        FreshsalesDeleteDealConfig,
        FreshsalesCloneDealConfig,
        FreshsalesForgetDealConfig,
        FreshsalesListDealViewsConfig,
        FreshsalesCreateTaskConfig,
        FreshsalesListTasksConfig,
        FreshsalesUpdateTaskConfig,
        FreshsalesGetTaskConfig,
        FreshsalesDeleteTaskConfig,
        FreshsalesCreateAppointmentConfig,
        FreshsalesListAppointmentsConfig,
        FreshsalesGetAppointmentConfig,
        FreshsalesUpdateAppointmentConfig,
        FreshsalesDeleteAppointmentConfig,
        FreshsalesCreateNoteConfig,
        FreshsalesUpdateNoteConfig,
        FreshsalesDeleteNoteConfig,
        FreshsalesCreateSalesActivityConfig,
        FreshsalesListSalesActivitiesConfig,
        FreshsalesGetSalesActivityConfig,
        FreshsalesUpdateSalesActivityConfig,
        FreshsalesDeleteSalesActivityConfig,
        FreshsalesLogPhoneCallConfig,
        FreshsalesSearchConfig,
        FreshsalesLookupConfig,
        FreshsalesFilteredSearchConfig,
        FreshsalesListOwnersConfig,
        FreshsalesListDealStagesConfig,
        FreshsalesListSelectorConfig,
        FreshsalesGetContactFieldsConfig,
        FreshsalesGetModuleFieldsConfig,
        FreshsalesListMarketingListsConfig,
        FreshsalesAddContactsToListConfig,
        FreshsalesGetListContactsConfig,
        FreshsalesRemoveContactsFromListConfig,
        FreshsalesCreateCustomRecordConfig,
        FreshsalesGetCustomRecordConfig,
        FreshsalesUpdateCustomRecordConfig,
        FreshsalesDeleteCustomRecordConfig,
        FreshsalesCreateDocumentLinkConfig,
        FreshsalesListDocumentAssociationsConfig,
        FreshsalesReceiveWebhookConfig,
    ],
    Discriminator("operation"),
]


class FreshsalesNodeConfig(NodeConfig[FreshsalesConfig, FreshsalesCredential]):
    """Full configuration for the Freshsales node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


async def _freshsales_request(
    base_url: str,
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Freshsales CRM request and return a structured result."""
    url = f"{base_url}{endpoint}"
    headers = {
        "Authorization": f"Token token={api_key}",
        "Content-Type": "application/json",
    }
    if json_body is not None:
        # Strip None recursively: Freshsales bodies wrap fields in a resource
        # object ({"contact": {...}}), and a nested null is read as "clear the
        # field" — failing required-field validation on partial updates.
        def _drop_none(v):
            if isinstance(v, dict):
                return {k: _drop_none(x) for k, x in v.items() if x is not None}
            return v
        json_body = _drop_none(json_body)
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with guarded_async_client(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    errors = err.get("errors") if isinstance(err, dict) else None
                    if isinstance(errors, dict):
                        message = errors.get("message") or str(errors)
                    else:
                        message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[FreshsalesNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
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
            logger.error(f"[FreshsalesNode] Request failed ({action_name}): {msg}")
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


class FreshsalesNode(WorkflowNode):
    """Freshsales (Freshworks CRM) automation node."""

    edit_examples = [
        "Create a contact in Freshsales when a form is submitted",
        "Create a deal and assign it to an owner",
        "Look up a contact by email and update their job title",
        "Log a phone call against a contact after a sales call",
        "Trigger a workflow when a Freshsales Workflow fires a webhook",
    ]

    @classmethod
    def get_config_model(cls):
        return FreshsalesNodeConfig

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the internal webhook URL for the receive_webhook trigger.

        Freshsales outbound webhooks are configured in the Freshsales dashboard
        (Workflows), so this only provisions our inbound URL for the user to paste.
        """
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        return {
            "values": {
                "webhook_id": webhook_data.get("webhook_id"),
                "webhook_url": webhook_data.get("webhook_url"),
                "relay_connected": webhook_data.get("relay_connected"),
                "is_production": webhook_data.get("is_production"),
            }
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
        """Load owner and deal-stage dropdown options from the Freshsales selector API."""
        if field_name not in ("owner_id", "deal_stage_id"):
            return {"options": []}
        if not credential_data:
            return {"options": []}
        api_key = credential_data.get("api_key")
        base_url = _build_base_url(credential_data.get("account_domain", ""))

        if field_name == "owner_id":
            result = await _freshsales_request(
                base_url, api_key, "GET", "/api/selector/owners", action_name="list_owners"
            )
            key = "users"
            label_fields = ("display_name", "email", "name")
        else:
            result = await _freshsales_request(
                base_url, api_key, "GET", "/api/selector/deal_stages", action_name="list_deal_stages"
            )
            key = "deal_stages"
            label_fields = ("name",)

        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        items = data.get(key) if isinstance(data, dict) else None
        if not isinstance(items, list):
            return {"options": []}
        options = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            label = next((item.get(f) for f in label_fields if item.get(f)), None) or str(item_id)
            if item_id is not None:
                options.append({"label": str(label), "value": str(item_id)})
        return {"options": options}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, FreshsalesNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        # Webhook trigger mode — pass through the inbound event payload
        if isinstance(op, FreshsalesReceiveWebhookConfig):
            return {
                "status": "success",
                "action": "receive_webhook",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Freshsales API key and account domain.")
        api_key = credentials.api_key
        base_url = _build_base_url(credentials.account_domain)

        handlers = {
            "create_contact": self._create_contact,
            "get_contact": self._get_contact,
            "update_contact": self._update_contact,
            "upsert_contact": self._upsert_contact,
            "delete_contact": self._delete_contact,
            "list_contacts": self._list_contacts,
            "create_account": self._create_account,
            "get_account": self._get_account,
            "update_account": self._update_account,
            "list_accounts": self._list_accounts,
            "create_deal": self._create_deal,
            "get_deal": self._get_deal,
            "update_deal": self._update_deal,
            "list_deals": self._list_deals,
            "create_task": self._create_task,
            "list_tasks": self._list_tasks,
            "update_task": self._update_task,
            "create_appointment": self._create_appointment,
            "list_appointments": self._list_appointments,
            "create_note": self._create_note,
            "create_sales_activity": self._create_sales_activity,
            "log_phone_call": self._log_phone_call,
            "search": self._search,
            "lookup": self._lookup,
            "list_owners": self._list_owners,
            "list_deal_stages": self._list_deal_stages,
            "get_contact_fields": self._get_contact_fields,
            "list_marketing_lists": self._list_marketing_lists,
            "add_contacts_to_list": self._add_contacts_to_list,
            "clone_contact": self._clone_contact,
            "forget_contact": self._forget_contact,
            "get_contact_activities": self._get_contact_activities,
            "list_contact_views": self._list_contact_views,
            "upsert_account": self._upsert_account,
            "delete_account": self._delete_account,
            "clone_account": self._clone_account,
            "forget_account": self._forget_account,
            "list_account_views": self._list_account_views,
            "delete_deal": self._delete_deal,
            "clone_deal": self._clone_deal,
            "forget_deal": self._forget_deal,
            "list_deal_views": self._list_deal_views,
            "get_task": self._get_task,
            "delete_task": self._delete_task,
            "get_appointment": self._get_appointment,
            "update_appointment": self._update_appointment,
            "delete_appointment": self._delete_appointment,
            "update_note": self._update_note,
            "delete_note": self._delete_note,
            "list_sales_activities": self._list_sales_activities,
            "get_sales_activity": self._get_sales_activity,
            "update_sales_activity": self._update_sales_activity,
            "delete_sales_activity": self._delete_sales_activity,
            "filtered_search": self._filtered_search,
            "list_selector": self._list_selector,
            "get_module_fields": self._get_module_fields,
            "get_list_contacts": self._get_list_contacts,
            "remove_contacts_from_list": self._remove_contacts_from_list,
            "cm_create_record": self._cm_create_record,
            "cm_get_record": self._cm_get_record,
            "cm_update_record": self._cm_update_record,
            "cm_delete_record": self._cm_delete_record,
            "create_document_link": self._create_document_link,
            "list_document_associations": self._list_document_associations,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, base_url, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------
    async def _create_contact(self, c: FreshsalesCreateContactConfig, base_url, api_key):
        body = {
            "contact": {
                "first_name": c.first_name,
                "last_name": c.last_name,
                "email": c.email,
                "mobile_number": c.mobile_number,
                "work_number": c.work_number,
                "job_title": c.job_title,
                "owner_id": c.owner_id,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "POST", "/api/contacts", json_body=body, action_name="create_contact"
        )

    async def _get_contact(self, c: FreshsalesGetContactConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", f"/api/contacts/{c.contact_id}",
            params={"include": c.include}, action_name="get_contact"
        )

    async def _update_contact(self, c: FreshsalesUpdateContactConfig, base_url, api_key):
        body = {
            "contact": {
                "first_name": c.first_name,
                "last_name": c.last_name,
                "email": c.email,
                "mobile_number": c.mobile_number,
                "job_title": c.job_title,
                "owner_id": c.owner_id,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "PUT", f"/api/contacts/{c.contact_id}",
            json_body=body, action_name="update_contact"
        )

    async def _upsert_contact(self, c: FreshsalesUpsertContactConfig, base_url, api_key):
        # Freshsales' unique email field is `emails` (plural) in the upsert
        # identifier — `email` is rejected with "provide a unique field".
        identifier_field = "emails" if c.unique_identifier_field == "email" else c.unique_identifier_field
        body = {
            "unique_identifier": {identifier_field: c.email},
            "contact": {
                "email": c.email,
                "first_name": c.first_name,
                "last_name": c.last_name,
                "mobile_number": c.mobile_number,
                "job_title": c.job_title,
            },
        }
        return await _freshsales_request(
            base_url, api_key, "POST", "/api/contacts/upsert",
            json_body=body, action_name="upsert_contact"
        )

    async def _delete_contact(self, c: FreshsalesDeleteContactConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "DELETE", f"/api/contacts/{c.contact_id}", action_name="delete_contact"
        )

    async def _list_contacts(self, c: FreshsalesListContactsConfig, base_url, api_key):
        params = {"page": c.page, "sort": c.sort, "sort_type": c.sort_type or None}
        return await _freshsales_request(
            base_url, api_key, "GET", f"/api/contacts/view/{c.view_id}",
            params=params, action_name="list_contacts"
        )

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    async def _create_account(self, c: FreshsalesCreateAccountConfig, base_url, api_key):
        body = {
            "sales_account": {
                "name": c.name,
                "website": c.website,
                "phone": c.phone,
                "industry_type_id": c.industry_type_id,
                "owner_id": c.owner_id,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "POST", "/api/sales_accounts",
            json_body=body, action_name="create_account"
        )

    async def _get_account(self, c: FreshsalesGetAccountConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", f"/api/sales_accounts/{c.account_id}",
            params={"include": c.include}, action_name="get_account"
        )

    async def _update_account(self, c: FreshsalesUpdateAccountConfig, base_url, api_key):
        body = {
            "sales_account": {
                "name": c.name,
                "website": c.website,
                "phone": c.phone,
                "owner_id": c.owner_id,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "PUT", f"/api/sales_accounts/{c.account_id}",
            json_body=body, action_name="update_account"
        )

    async def _list_accounts(self, c: FreshsalesListAccountsConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", f"/api/sales_accounts/view/{c.view_id}",
            params={"page": c.page}, action_name="list_accounts"
        )

    # ------------------------------------------------------------------
    # Deals
    # ------------------------------------------------------------------
    async def _create_deal(self, c: FreshsalesCreateDealConfig, base_url, api_key):
        body = {
            "deal": {
                "name": c.name,
                "amount": c.amount,
                "deal_stage_id": c.deal_stage_id,
                "sales_account_id": c.sales_account_id,
                "owner_id": c.owner_id,
                "expected_close": c.expected_close,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "POST", "/api/deals", json_body=body, action_name="create_deal"
        )

    async def _get_deal(self, c: FreshsalesGetDealConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", f"/api/deals/{c.deal_id}",
            params={"include": c.include}, action_name="get_deal"
        )

    async def _update_deal(self, c: FreshsalesUpdateDealConfig, base_url, api_key):
        body = {
            "deal": {
                "name": c.name,
                "amount": c.amount,
                "deal_stage_id": c.deal_stage_id,
                "owner_id": c.owner_id,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "PUT", f"/api/deals/{c.deal_id}",
            json_body=body, action_name="update_deal"
        )

    async def _list_deals(self, c: FreshsalesListDealsConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", f"/api/deals/view/{c.view_id}",
            params={"page": c.page}, action_name="list_deals"
        )

    # ------------------------------------------------------------------
    # Tasks / Appointments
    # ------------------------------------------------------------------
    async def _create_task(self, c: FreshsalesCreateTaskConfig, base_url, api_key):
        body = {
            "task": {
                "title": c.title,
                "due_date": c.due_date,
                "owner_id": c.owner_id,
                "targetable_type": c.targetable_type or None,
                "targetable_id": c.targetable_id,
                "description": c.description,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "POST", "/api/tasks", json_body=body, action_name="create_task"
        )

    async def _list_tasks(self, c: FreshsalesListTasksConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", "/api/tasks",
            params={"filter": c.task_filter}, action_name="list_tasks"
        )

    async def _update_task(self, c: FreshsalesUpdateTaskConfig, base_url, api_key):
        task: Dict[str, Any] = {"title": c.title, "due_date": c.due_date}
        if c.mark_complete == "true":
            task["status"] = 1
        return await _freshsales_request(
            base_url, api_key, "PUT", f"/api/tasks/{c.task_id}",
            json_body={"task": task}, action_name="update_task"
        )

    async def _create_appointment(self, c: FreshsalesCreateAppointmentConfig, base_url, api_key):
        body = {
            "appointment": {
                "title": c.title,
                "from_date": c.from_date,
                "end_date": c.end_date,
                "location": c.location,
                "description": c.description,
                "targetable_type": c.targetable_type or None,
                "targetable_id": c.targetable_id,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "POST", "/api/appointments",
            json_body=body, action_name="create_appointment"
        )

    async def _list_appointments(self, c: FreshsalesListAppointmentsConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", "/api/appointments",
            params={"filter": c.appointment_filter}, action_name="list_appointments"
        )

    # ------------------------------------------------------------------
    # Notes / Activities / Calls
    # ------------------------------------------------------------------
    async def _create_note(self, c: FreshsalesCreateNoteConfig, base_url, api_key):
        body = {
            "note": {
                "description": c.description,
                "targetable_type": c.targetable_type,
                "targetable_id": c.targetable_id,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "POST", "/api/notes", json_body=body, action_name="create_note"
        )

    async def _create_sales_activity(self, c: FreshsalesCreateSalesActivityConfig, base_url, api_key):
        body = {
            "sales_activity": {
                "title": c.title,
                "sales_activity_type_id": c.sales_activity_type_id,
                "targetable_type": c.targetable_type,
                "targetable_id": c.targetable_id,
                "start_date": c.start_date,
                "end_date": c.end_date,
                "notes": c.notes,
            }
        }
        return await _freshsales_request(
            base_url, api_key, "POST", "/api/sales_activities",
            json_body=body, action_name="create_sales_activity"
        )

    async def _log_phone_call(self, c: FreshsalesLogPhoneCallConfig, base_url, api_key):
        # Freshsales' /phone_calls expects fields at the top level (a
        # {"phone_call": {...}} wrapper OR a "note" key both trigger a Ruby
        # "Symbol into String" error); the note field is `call_notes`.
        body = {
            "call_direction": c.call_direction,
            "targetable_type": c.targetable_type,
            "targetable_id": c.targetable_id,
            "call_notes": c.note,
        }
        return await _freshsales_request(
            base_url, api_key, "POST", "/api/phone_calls",
            json_body=body, action_name="log_phone_call"
        )

    # ------------------------------------------------------------------
    # Search / Lookup / Selectors / Settings
    # ------------------------------------------------------------------
    async def _search(self, c: FreshsalesSearchConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", "/api/search",
            params={"q": c.query, "include": c.include}, action_name="search"
        )

    async def _lookup(self, c: FreshsalesLookupConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", "/api/lookup",
            params={"q": c.value, "f": c.field, "entities": c.entities}, action_name="lookup"
        )

    async def _list_owners(self, c: FreshsalesListOwnersConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", "/api/selector/owners", action_name="list_owners"
        )

    async def _list_deal_stages(self, c: FreshsalesListDealStagesConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", "/api/selector/deal_stages", action_name="list_deal_stages"
        )

    async def _get_contact_fields(self, c: FreshsalesGetContactFieldsConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", "/api/settings/contacts/fields", action_name="get_contact_fields"
        )

    # ------------------------------------------------------------------
    # Marketing Lists
    # ------------------------------------------------------------------
    async def _list_marketing_lists(self, c: FreshsalesListMarketingListsConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "GET", "/api/lists", action_name="list_marketing_lists"
        )

    async def _add_contacts_to_list(self, c: FreshsalesAddContactsToListConfig, base_url, api_key):
        return await _freshsales_request(
            base_url, api_key, "PUT", f"/api/lists/{c.list_id}/add_contacts",
            json_body={"ids": _split_ids(c.contact_ids)}, action_name="add_contacts_to_list"
        )

    # ------------------------------------------------------------------
    # Contacts — clone / forget / activities / views
    # ------------------------------------------------------------------
    async def _clone_contact(self, c: FreshsalesCloneContactConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "POST", f"/api/contacts/{c.contact_id}/clone", action_name="clone_contact")

    async def _forget_contact(self, c: FreshsalesForgetContactConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/contacts/{c.contact_id}/forget", action_name="forget_contact")

    async def _get_contact_activities(self, c: FreshsalesGetContactActivitiesConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", f"/api/contacts/{c.contact_id}/activities.json", action_name="get_contact_activities")

    async def _list_contact_views(self, c: FreshsalesListContactViewsConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", "/api/contacts/filters", action_name="list_contact_views")

    # ------------------------------------------------------------------
    # Accounts — upsert / delete / clone / forget / views
    # ------------------------------------------------------------------
    async def _upsert_account(self, c: FreshsalesUpsertAccountConfig, base_url, api_key):
        body = {
            "unique_identifier": {"name": c.name},
            "sales_account": {"name": c.name, "website": c.website, "phone": c.phone},
        }
        return await _freshsales_request(base_url, api_key, "POST", "/api/sales_accounts/upsert", json_body=body, action_name="upsert_account")

    async def _delete_account(self, c: FreshsalesDeleteAccountConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/sales_accounts/{c.account_id}", action_name="delete_account")

    async def _clone_account(self, c: FreshsalesCloneAccountConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "POST", f"/api/sales_accounts/{c.account_id}/clone", action_name="clone_account")

    async def _forget_account(self, c: FreshsalesForgetAccountConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/sales_accounts/{c.account_id}/forget", action_name="forget_account")

    async def _list_account_views(self, c: FreshsalesListAccountViewsConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", "/api/sales_accounts/filters", action_name="list_account_views")

    # ------------------------------------------------------------------
    # Deals — delete / clone / forget / views
    # ------------------------------------------------------------------
    async def _delete_deal(self, c: FreshsalesDeleteDealConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/deals/{c.deal_id}", action_name="delete_deal")

    async def _clone_deal(self, c: FreshsalesCloneDealConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "POST", f"/api/deals/{c.deal_id}/clone", action_name="clone_deal")

    async def _forget_deal(self, c: FreshsalesForgetDealConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/deals/{c.deal_id}/forget", action_name="forget_deal")

    async def _list_deal_views(self, c: FreshsalesListDealViewsConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", "/api/deals/filters", action_name="list_deal_views")

    # ------------------------------------------------------------------
    # Tasks — get / delete
    # ------------------------------------------------------------------
    async def _get_task(self, c: FreshsalesGetTaskConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", f"/api/tasks/{c.task_id}", action_name="get_task")

    async def _delete_task(self, c: FreshsalesDeleteTaskConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/tasks/{c.task_id}", action_name="delete_task")

    # ------------------------------------------------------------------
    # Appointments — get / update / delete
    # ------------------------------------------------------------------
    async def _get_appointment(self, c: FreshsalesGetAppointmentConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", f"/api/appointments/{c.appointment_id}", action_name="get_appointment")

    async def _update_appointment(self, c: FreshsalesUpdateAppointmentConfig, base_url, api_key):
        body = {"appointment": {"title": c.title, "from_date": c.from_date, "end_date": c.end_date, "location": c.location, "description": c.description}}
        return await _freshsales_request(base_url, api_key, "PUT", f"/api/appointments/{c.appointment_id}", json_body=body, action_name="update_appointment")

    async def _delete_appointment(self, c: FreshsalesDeleteAppointmentConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/appointments/{c.appointment_id}", action_name="delete_appointment")

    # ------------------------------------------------------------------
    # Notes — update / delete
    # ------------------------------------------------------------------
    async def _update_note(self, c: FreshsalesUpdateNoteConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "PUT", f"/api/notes/{c.note_id}", json_body={"note": {"description": c.description}}, action_name="update_note")

    async def _delete_note(self, c: FreshsalesDeleteNoteConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/notes/{c.note_id}", action_name="delete_note")

    # ------------------------------------------------------------------
    # Sales activities — list / get / update / delete
    # ------------------------------------------------------------------
    async def _list_sales_activities(self, c: FreshsalesListSalesActivitiesConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", "/api/sales_activities", params={"page": c.page}, action_name="list_sales_activities")

    async def _get_sales_activity(self, c: FreshsalesGetSalesActivityConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", f"/api/sales_activities/{c.sales_activity_id}", action_name="get_sales_activity")

    async def _update_sales_activity(self, c: FreshsalesUpdateSalesActivityConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "PUT", f"/api/sales_activities/{c.sales_activity_id}", json_body={"sales_activity": {"title": c.title, "notes": c.notes}}, action_name="update_sales_activity")

    async def _delete_sales_activity(self, c: FreshsalesDeleteSalesActivityConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/sales_activities/{c.sales_activity_id}", action_name="delete_sales_activity")

    # ------------------------------------------------------------------
    # Filtered search / selectors / fields
    # ------------------------------------------------------------------
    async def _filtered_search(self, c: FreshsalesFilteredSearchConfig, base_url, api_key):
        body = {"filter_rule": _parse_json(c.filter_rule_json)}
        return await _freshsales_request(base_url, api_key, "POST", f"/api/filtered_search/{c.entity}", params={"page": c.page}, json_body=body, action_name="filtered_search")

    async def _list_selector(self, c: FreshsalesListSelectorConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", f"/api/selector/{c.selector}", action_name="list_selector")

    async def _get_module_fields(self, c: FreshsalesGetModuleFieldsConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", f"/api/settings/{c.entity}/fields", action_name="get_module_fields")

    # ------------------------------------------------------------------
    # Lists — get contacts / remove contacts
    # ------------------------------------------------------------------
    async def _get_list_contacts(self, c: FreshsalesGetListContactsConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", f"/api/contacts/lists/{c.list_id}", action_name="get_list_contacts")

    async def _remove_contacts_from_list(self, c: FreshsalesRemoveContactsFromListConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "PUT", f"/api/lists/{c.list_id}/remove_contacts", json_body={"ids": _split_ids(c.contact_ids)}, action_name="remove_contacts_from_list")

    # ------------------------------------------------------------------
    # Custom modules
    # ------------------------------------------------------------------
    async def _cm_create_record(self, c: FreshsalesCreateCustomRecordConfig, base_url, api_key):
        body = {c.module_name: _parse_json(c.data_json)}
        return await _freshsales_request(base_url, api_key, "POST", f"/api/custom_module/{c.module_name}", json_body=body, action_name="cm_create_record")

    async def _cm_get_record(self, c: FreshsalesGetCustomRecordConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", f"/api/custom_module/{c.module_name}/{c.record_id}", action_name="cm_get_record")

    async def _cm_update_record(self, c: FreshsalesUpdateCustomRecordConfig, base_url, api_key):
        body = {c.module_name: _parse_json(c.data_json)}
        return await _freshsales_request(base_url, api_key, "PUT", f"/api/custom_module/{c.module_name}/{c.record_id}", json_body=body, action_name="cm_update_record")

    async def _cm_delete_record(self, c: FreshsalesDeleteCustomRecordConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "DELETE", f"/api/custom_module/{c.module_name}/{c.record_id}", action_name="cm_delete_record")

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    async def _create_document_link(self, c: FreshsalesCreateDocumentLinkConfig, base_url, api_key):
        # Fields go at the top level — a {"document_link": {...}} wrapper 400s.
        body = {"url": c.url, "name": c.name, "targetable_type": c.targetable_type, "targetable_id": c.targetable_id}
        return await _freshsales_request(base_url, api_key, "POST", "/api/document_links", json_body=body, action_name="create_document_link")

    async def _list_document_associations(self, c: FreshsalesListDocumentAssociationsConfig, base_url, api_key):
        return await _freshsales_request(base_url, api_key, "GET", f"/api/{c.targetable_type}/{c.record_id}/document_associations", action_name="list_document_associations")
