"""
Google Looker BI automation node.

Provides workflow integration with the Looker API (4.0) for operations including:
- Auth/Profile: logout, get current user
- Queries: run inline, create, get, run by id, async start/status/results
- SQL Runner: create SQL query, run SQL query
- LookML: get model, get explore fields
- Looks: search, get, run, create, update, delete
- Dashboards: search, get, create, update, delete, render to PDF/PNG, get render results
- Users: search, create, update, delete
- Content: search content/folders, list connections, alerts (search, get, delete)
- Scheduled plans: create, run once, list, get, delete
- Trigger: on_look_results (poll a saved Look on a schedule, emit new rows)

Authentication: API key (client_id + client_secret) exchanged at POST /login for a
short-lived access token, then sent on every request as `Authorization: token <token>`
(literal `token`, NOT `Bearer`). The Looker instance base URL is per-customer, so it is
captured on the credential.

API Base URL: https://<instance>...:19999/api/4.0 (original) or
https://<instance>.api.looker.app/api/4.0 (Google Cloud core) — supplied by the user.
Documentation: https://docs.cloud.google.com/looker/docs/api-overview

Note: Looker has no inbound webhook subscription API (push automation is via
ScheduledPlan / Alert), so the trigger is poll-based: a cron Durable Object POSTs
the node's internal webhook on a schedule and execute() runs the selected Look.
"""

import logging
import re
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.poll_trigger import (
    PollTriggerConfigBase, ScheduledPollTriggerMixin,
)
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

# Valid result formats for Looker run endpoints (result_format path segment).
RESULT_FORMATS = ["json", "json_detail", "csv", "txt", "html", "md", "xlsx", "sql"]
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PROXY_PATH = re.compile(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z")
_TEXT_FORMATS = {"csv", "txt", "html", "md", "sql"}
_BINARY_FORMATS = {"xlsx", "pdf", "png", "jpg"}
_BINARY_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg",
}


def _dynamic_options(
    field_name: str,
    placeholder: str,
    *,
    depends_on: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an ``x-dynamic-options`` spec for a Looker resource-reference field.

    All Looker dropdowns are searchable and allow pasting an ID (so values
    coming from an upstream step still work). ``depends_on`` names a sibling
    field whose value scopes the list (e.g. explores depend on the model).
    """
    spec: Dict[str, Any] = {
        "field_name": field_name,
        "placeholder": placeholder,
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste ID",
    }
    if depends_on:
        spec["depends_on"] = depends_on
    return spec


def _normalize_base_url(instance_url: str) -> str:
    """Normalize a user-supplied Looker instance URL to a `.../api/4.0` base.

    Accepts the bare host (`https://acme.cloud.looker.com:19999`) or a URL that
    already includes `/api/4.0`; returns a base with no trailing slash.
    """
    raw = str(instance_url or "").strip()
    if not raw:
        raise ValueError("A Looker instance URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        parsed = urlsplit(raw)
        port = parsed.port
        host = (parsed.hostname or "").lower()
    except ValueError as exc:
        raise ValueError("Looker instance URL is invalid") from exc
    if (parsed.scheme != "https" or not host or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or "?" in raw or "#" in raw or "\\" in raw):
        raise ValueError("Looker instance URL must be an HTTPS API host")
    # A tenant may configure a custom host and an explicit :443 or :19999.
    # Keep the explicit port while rejecting URL parser ambiguities before login.
    labels = host.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError("Looker instance URL has an invalid host")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Looker instance URL has an invalid port")
    path = parsed.path.rstrip("/")
    if path.endswith("/api/4.0"):
        proxy_path = path[:-len("/api/4.0")]
    else:
        proxy_path = path
        if "/api/" in path:
            raise ValueError("Looker instance URL must use API 4.0")
    if proxy_path and not _PROXY_PATH.fullmatch(proxy_path):
        raise ValueError("Looker instance URL has an invalid proxy path")
    authority = host + (f":{port}" if port is not None else "")
    return f"https://{authority}{proxy_path}/api/4.0"


# ============================================================================
# Credential Schema
# ============================================================================


class LookerApiKeyCredential(BaseModel):
    """API key credential for Looker (client_id + client_secret + instance URL)."""

    credential_type: Literal["looker_api_key"] = Field(
        "looker_api_key", json_schema_extra={"ui:hidden": True}
    )
    instance_url: str = Field(
        ...,
        title="Instance URL",
        description=(
            "Your Looker API base URL, e.g. https://acme.cloud.looker.com:19999 "
            "(original) or https://acme.api.looker.app (Google Cloud core)"
        ),
    )
    client_id: str = Field(
        ...,
        title="Client ID",
        description="API3 client_id from Looker Admin > Users > Edit > API Keys",
        json_schema_extra={"ui:widget": "password"},
    )
    client_secret: str = Field(
        ...,
        title="Client Secret",
        description="API3 client_secret paired with the client_id",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Looker API Key",
        json_schema_extra={
            "x-credential-url": "https://docs.cloud.google.com/looker/docs/api-auth"
        }
    )


LookerCredential = LookerApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class LookerLogoutConfig(BaseModel):
    """Invalidate the current Looker access token."""

    operation: Literal["logout"] = Field(
        "logout",
        json_schema_extra={
            "const": "logout",
            "ui:hidden": True,
            "x-category": "Auth",
            "x-is-trigger": False,
            "x-display-name": "Logout",
        },
        title="Logout",
    )


class LookerGetCurrentUserConfig(BaseModel):
    """Return the user account the API credentials act as."""

    operation: Literal["get_current_user"] = Field(
        "get_current_user",
        json_schema_extra={
            "const": "get_current_user",
            "ui:hidden": True,
            "x-category": "Auth",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


class LookerRunInlineQueryConfig(BaseModel):
    """Run an ad-hoc query (model/view/fields) and return results."""

    operation: Literal["run_inline_query"] = Field(
        "run_inline_query",
        json_schema_extra={
            "const": "run_inline_query",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Run Inline Query",
        },
        title="Run Inline Query",
    )
    model: str = Field(
        ...,
        title="Model",
        description="LookML model name",
        json_schema_extra={"x-dynamic-options": _dynamic_options("model", "Select a model…")},
    )
    view: str = Field(
        ...,
        title="View / Explore",
        description="Explore (view) name within the model",
        json_schema_extra={
            "x-dynamic-options": _dynamic_options("view", "Select an explore…", depends_on="model")
        },
    )
    fields: str = Field(
        ...,
        title="Fields",
        description="Comma-separated fully-qualified field names (e.g. orders.count, users.state)",
    )
    filters: Optional[str] = Field(
        None,
        title="Filters (JSON)",
        description='JSON object of field->filter expression, e.g. {"orders.created_date":"30 days"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    sorts: Optional[str] = Field(
        None, title="Sorts", description="Comma-separated sort fields (append ' desc' to reverse)"
    )
    limit: Optional[str] = Field(
        "500", title="Row Limit", description="Maximum number of rows to return"
    )
    result_format: str = Field(
        "json",
        title="Result Format",
        description="Output format for the query results",
        json_schema_extra={"enum": RESULT_FORMATS, "x-enum-searchable": True},
    )


class LookerCreateQueryConfig(BaseModel):
    """Define a query and get a query_id (without executing it)."""

    operation: Literal["create_query"] = Field(
        "create_query",
        json_schema_extra={
            "const": "create_query",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Create Query",
        },
        title="Create Query",
    )
    model: str = Field(
        ...,
        title="Model",
        description="LookML model name",
        json_schema_extra={"x-dynamic-options": _dynamic_options("model", "Select a model…")},
    )
    view: str = Field(
        ...,
        title="View / Explore",
        description="Explore (view) name within the model",
        json_schema_extra={
            "x-dynamic-options": _dynamic_options("view", "Select an explore…", depends_on="model")
        },
    )
    fields: str = Field(
        ..., title="Fields", description="Comma-separated fully-qualified field names"
    )
    filters: Optional[str] = Field(
        None,
        title="Filters (JSON)",
        description="JSON object of field->filter expression",
        json_schema_extra={"ui:widget": "textarea"},
    )
    sorts: Optional[str] = Field(None, title="Sorts", description="Comma-separated sort fields")
    limit: Optional[str] = Field("500", title="Row Limit", description="Maximum rows")


class LookerRunQueryConfig(BaseModel):
    """Execute a previously created query by id and return results."""

    operation: Literal["run_query"] = Field(
        "run_query",
        json_schema_extra={
            "const": "run_query",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Run Query By ID",
        },
        title="Run Query By ID",
    )
    query_id: str = Field(..., title="Query ID", description="The id of a created query")
    result_format: str = Field(
        "json",
        title="Result Format",
        description="Output format for the query results",
        json_schema_extra={"enum": RESULT_FORMATS, "x-enum-searchable": True},
    )


class LookerRunQueryAsyncConfig(BaseModel):
    """Start a long-running query as a background task (returns a query_task_id)."""

    operation: Literal["run_query_async"] = Field(
        "run_query_async",
        json_schema_extra={
            "const": "run_query_async",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Run Query Async (Start)",
        },
        title="Run Query Async (Start)",
    )
    query_id: str = Field(..., title="Query ID", description="The id of the query to run async")
    result_format: str = Field(
        "json",
        title="Result Format",
        description="Output format for the query results",
        json_schema_extra={"enum": RESULT_FORMATS, "x-enum-searchable": True},
    )


class LookerGetQueryTaskResultsConfig(BaseModel):
    """Fetch the results of a completed async query task."""

    operation: Literal["get_query_task_results"] = Field(
        "get_query_task_results",
        json_schema_extra={
            "const": "get_query_task_results",
            "ui:hidden": True,
            "x-category": "Queries",
            "x-is-trigger": False,
            "x-display-name": "Get Async Query Results",
        },
        title="Get Async Query Results",
    )
    query_task_id: str = Field(
        ..., title="Query Task ID", description="The query_task_id returned when starting the async query"
    )


class LookerSearchLooksConfig(BaseModel):
    """Find saved Looks by title, folder, or user."""

    operation: Literal["search_looks"] = Field(
        "search_looks",
        json_schema_extra={
            "const": "search_looks",
            "ui:hidden": True,
            "x-category": "Looks",
            "x-is-trigger": False,
            "x-display-name": "Search Looks",
        },
        title="Search Looks",
    )
    title: Optional[str] = Field(None, title="Title", description="Match Looks by title (supports % wildcard)")
    user_id: Optional[str] = Field(None, title="User ID", description="Filter to a Look owner")
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Filter to a folder",
        json_schema_extra={"x-dynamic-options": _dynamic_options("folder_id", "Select a folder…")},
    )
    limit: Optional[str] = Field("50", title="Limit", description="Max number of Looks to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of rows to skip")


class LookerGetLookConfig(BaseModel):
    """Retrieve a single saved Look's metadata."""

    operation: Literal["get_look"] = Field(
        "get_look",
        json_schema_extra={
            "const": "get_look",
            "ui:hidden": True,
            "x-category": "Looks",
            "x-is-trigger": False,
            "x-display-name": "Get Look",
        },
        title="Get Look",
    )
    look_id: str = Field(
        ...,
        title="Look ID",
        description="The id of the Look to retrieve",
        json_schema_extra={"x-dynamic-options": _dynamic_options("look_id", "Select a Look…")},
    )


class LookerRunLookConfig(BaseModel):
    """Execute a saved Look and return its data."""

    operation: Literal["run_look"] = Field(
        "run_look",
        json_schema_extra={
            "const": "run_look",
            "ui:hidden": True,
            "x-category": "Looks",
            "x-is-trigger": False,
            "x-display-name": "Run Look",
        },
        title="Run Look",
    )
    look_id: str = Field(
        ...,
        title="Look ID",
        description="The id of the Look to run",
        json_schema_extra={"x-dynamic-options": _dynamic_options("look_id", "Select a Look…")},
    )
    result_format: str = Field(
        "json",
        title="Result Format",
        description="Output format for the Look results",
        json_schema_extra={"enum": RESULT_FORMATS, "x-enum-searchable": True},
    )
    limit: Optional[str] = Field(None, title="Row Limit", description="Override the Look's row limit")


class LookerCreateLookConfig(BaseModel):
    """Save a new Look from a query."""

    operation: Literal["create_look"] = Field(
        "create_look",
        json_schema_extra={
            "const": "create_look",
            "ui:hidden": True,
            "x-category": "Looks",
            "x-is-trigger": False,
            "x-display-name": "Create Look",
        },
        title="Create Look",
    )
    title: str = Field(..., title="Title", description="Title of the new Look")
    query_id: str = Field(..., title="Query ID", description="The query the Look visualizes")
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="Folder to save the Look in",
        json_schema_extra={"x-dynamic-options": _dynamic_options("folder_id", "Select a folder…")},
    )
    description: Optional[str] = Field(None, title="Description", description="Optional description")


class LookerUpdateLookConfig(BaseModel):
    """Update a Look's title, folder, or query."""

    operation: Literal["update_look"] = Field(
        "update_look",
        json_schema_extra={
            "const": "update_look",
            "ui:hidden": True,
            "x-category": "Looks",
            "x-is-trigger": False,
            "x-display-name": "Update Look",
        },
        title="Update Look",
    )
    look_id: str = Field(
        ...,
        title="Look ID",
        description="The id of the Look to update",
        json_schema_extra={"x-dynamic-options": _dynamic_options("look_id", "Select a Look…")},
    )
    title: Optional[str] = Field(None, title="Title", description="New title")
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Move to this folder",
        json_schema_extra={"x-dynamic-options": _dynamic_options("folder_id", "Select a folder…")},
    )
    description: Optional[str] = Field(None, title="Description", description="New description")
    deleted: Optional[str] = Field(
        None,
        title="Soft Delete",
        description="Set to true to soft-delete (or false to restore)",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class LookerDeleteLookConfig(BaseModel):
    """Delete a saved Look."""

    operation: Literal["delete_look"] = Field(
        "delete_look",
        json_schema_extra={
            "const": "delete_look",
            "ui:hidden": True,
            "x-category": "Looks",
            "x-is-trigger": False,
            "x-display-name": "Delete Look",
        },
        title="Delete Look",
    )
    look_id: str = Field(
        ...,
        title="Look ID",
        description="The id of the Look to delete",
        json_schema_extra={"x-dynamic-options": _dynamic_options("look_id", "Select a Look…")},
    )


class LookerSearchDashboardsConfig(BaseModel):
    """Find dashboards by title, folder, or user."""

    operation: Literal["search_dashboards"] = Field(
        "search_dashboards",
        json_schema_extra={
            "const": "search_dashboards",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Search Dashboards",
        },
        title="Search Dashboards",
    )
    title: Optional[str] = Field(None, title="Title", description="Match dashboards by title")
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Filter to a folder",
        json_schema_extra={"x-dynamic-options": _dynamic_options("folder_id", "Select a folder…")},
    )
    user_id: Optional[str] = Field(None, title="User ID", description="Filter to an owner")
    limit: Optional[str] = Field("50", title="Limit", description="Max number to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of rows to skip")


class LookerGetDashboardConfig(BaseModel):
    """Retrieve a dashboard's metadata and structure."""

    operation: Literal["get_dashboard"] = Field(
        "get_dashboard",
        json_schema_extra={
            "const": "get_dashboard",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Get Dashboard",
        },
        title="Get Dashboard",
    )
    dashboard_id: str = Field(
        ...,
        title="Dashboard ID",
        description="The id of the dashboard",
        json_schema_extra={"x-dynamic-options": _dynamic_options("dashboard_id", "Select a dashboard…")},
    )


class LookerCreateDashboardConfig(BaseModel):
    """Create a new dashboard."""

    operation: Literal["create_dashboard"] = Field(
        "create_dashboard",
        json_schema_extra={
            "const": "create_dashboard",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Create Dashboard",
        },
        title="Create Dashboard",
    )
    title: str = Field(..., title="Title", description="Title of the new dashboard")
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="Folder to create the dashboard in",
        json_schema_extra={"x-dynamic-options": _dynamic_options("folder_id", "Select a folder…")},
    )
    description: Optional[str] = Field(None, title="Description", description="Optional description")


class LookerUpdateDashboardConfig(BaseModel):
    """Update dashboard properties."""

    operation: Literal["update_dashboard"] = Field(
        "update_dashboard",
        json_schema_extra={
            "const": "update_dashboard",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Update Dashboard",
        },
        title="Update Dashboard",
    )
    dashboard_id: str = Field(
        ...,
        title="Dashboard ID",
        description="The id of the dashboard to update",
        json_schema_extra={"x-dynamic-options": _dynamic_options("dashboard_id", "Select a dashboard…")},
    )
    title: Optional[str] = Field(None, title="Title", description="New title")
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Move to this folder",
        json_schema_extra={"x-dynamic-options": _dynamic_options("folder_id", "Select a folder…")},
    )
    description: Optional[str] = Field(None, title="Description", description="New description")


class LookerDeleteDashboardConfig(BaseModel):
    """Delete a dashboard."""

    operation: Literal["delete_dashboard"] = Field(
        "delete_dashboard",
        json_schema_extra={
            "const": "delete_dashboard",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Delete Dashboard",
        },
        title="Delete Dashboard",
    )
    dashboard_id: str = Field(
        ...,
        title="Dashboard ID",
        description="The id of the dashboard to delete",
        json_schema_extra={"x-dynamic-options": _dynamic_options("dashboard_id", "Select a dashboard…")},
    )


class LookerCreateRenderTaskConfig(BaseModel):
    """Start rendering a dashboard to PDF/PNG (returns a render_task_id)."""

    operation: Literal["create_render_task"] = Field(
        "create_render_task",
        json_schema_extra={
            "const": "create_render_task",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Render Dashboard",
        },
        title="Render Dashboard",
    )
    dashboard_id: str = Field(
        ...,
        title="Dashboard ID",
        description="The dashboard to render",
        json_schema_extra={"x-dynamic-options": _dynamic_options("dashboard_id", "Select a dashboard…")},
    )
    result_format: str = Field(
        "pdf",
        title="Format",
        description="Render output format",
        json_schema_extra={
            "enum": ["pdf", "png", "jpg"],
            "x-enum-searchable": True,
        },
    )
    width: Optional[str] = Field("1280", title="Width", description="Pixel width of the render")
    height: Optional[str] = Field("720", title="Height", description="Pixel height of the render")


class LookerGetRenderTaskConfig(BaseModel):
    """Check a render task and download the rendered file once complete."""

    operation: Literal["get_render_task"] = Field(
        "get_render_task",
        json_schema_extra={
            "const": "get_render_task",
            "ui:hidden": True,
            "x-category": "Dashboards",
            "x-is-trigger": False,
            "x-display-name": "Get Render Result",
        },
        title="Get Render Result",
    )
    render_task_id: str = Field(
        ..., title="Render Task ID", description="The render_task_id returned when starting the render"
    )


class LookerSearchUsersConfig(BaseModel):
    """Find Looker users by name or email."""

    operation: Literal["search_users"] = Field(
        "search_users",
        json_schema_extra={
            "const": "search_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Search Users",
        },
        title="Search Users",
    )
    email: Optional[str] = Field(None, title="Email", description="Match users by email")
    first_name: Optional[str] = Field(None, title="First Name", description="Match by first name")
    last_name: Optional[str] = Field(None, title="Last Name", description="Match by last name")
    limit: Optional[str] = Field("50", title="Limit", description="Max number to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of rows to skip")


class LookerCreateUserConfig(BaseModel):
    """Provision a new Looker user account."""

    operation: Literal["create_user"] = Field(
        "create_user",
        json_schema_extra={
            "const": "create_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Create User",
        },
        title="Create User",
    )
    first_name: str = Field(..., title="First Name", description="User's first name")
    last_name: str = Field(..., title="Last Name", description="User's last name")
    email: Optional[str] = Field(None, title="Email", description="Email for the new user's credentials")
    is_disabled: Optional[str] = Field(
        None,
        title="Disabled",
        description="Create the account in a disabled state",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class LookerUpdateUserConfig(BaseModel):
    """Update a user's profile or settings."""

    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={
            "const": "update_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Update User",
        },
        title="Update User",
    )
    user_id: str = Field(..., title="User ID", description="The id of the user to update")
    first_name: Optional[str] = Field(None, title="First Name", description="New first name")
    last_name: Optional[str] = Field(None, title="Last Name", description="New last name")
    is_disabled: Optional[str] = Field(
        None,
        title="Disabled",
        description="Enable or disable the user",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Disable", "Enable"],
            "x-enum-searchable": True,
        },
    )


class LookerDeleteUserConfig(BaseModel):
    """Delete a Looker user."""

    operation: Literal["delete_user"] = Field(
        "delete_user",
        json_schema_extra={
            "const": "delete_user",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Delete User",
        },
        title="Delete User",
    )
    user_id: str = Field(..., title="User ID", description="The id of the user to delete")


class LookerSearchFoldersConfig(BaseModel):
    """Find content folders (spaces) for organizing Looks/dashboards."""

    operation: Literal["search_folders"] = Field(
        "search_folders",
        json_schema_extra={
            "const": "search_folders",
            "ui:hidden": True,
            "x-category": "Content",
            "x-is-trigger": False,
            "x-display-name": "Search Folders",
        },
        title="Search Folders",
    )
    name: Optional[str] = Field(None, title="Name", description="Match folders by name")
    parent_id: Optional[str] = Field(
        None,
        title="Parent Folder ID",
        description="Filter to children of a folder",
        json_schema_extra={"x-dynamic-options": _dynamic_options("parent_id", "Select a parent folder…")},
    )
    limit: Optional[str] = Field("50", title="Limit", description="Max number to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of rows to skip")


class LookerListConnectionsConfig(BaseModel):
    """List database connections configured on the instance."""

    operation: Literal["list_connections"] = Field(
        "list_connections",
        json_schema_extra={
            "const": "list_connections",
            "ui:hidden": True,
            "x-category": "Content",
            "x-is-trigger": False,
            "x-display-name": "List Connections",
        },
        title="List Connections",
    )


class LookerSearchAlertsConfig(BaseModel):
    """Search data-driven alerts."""

    operation: Literal["search_alerts"] = Field(
        "search_alerts",
        json_schema_extra={
            "const": "search_alerts",
            "ui:hidden": True,
            "x-category": "Content",
            "x-is-trigger": False,
            "x-display-name": "Search Alerts",
        },
        title="Search Alerts",
    )
    limit: Optional[str] = Field("50", title="Limit", description="Max number to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of rows to skip")
    group_by: Optional[str] = Field(None, title="Group By", description="Group alerts by a field")


class LookerCreateScheduledPlanConfig(BaseModel):
    """Schedule recurring delivery of a Look or dashboard."""

    operation: Literal["create_scheduled_plan"] = Field(
        "create_scheduled_plan",
        json_schema_extra={
            "const": "create_scheduled_plan",
            "ui:hidden": True,
            "x-category": "Scheduled Plans",
            "x-is-trigger": False,
            "x-display-name": "Create Scheduled Plan",
        },
        title="Create Scheduled Plan",
    )
    name: str = Field(..., title="Name", description="Name of the scheduled plan")
    look_id: Optional[str] = Field(
        None,
        title="Look ID",
        description="Look to deliver (Look or dashboard required)",
        json_schema_extra={"x-dynamic-options": _dynamic_options("look_id", "Select a Look…")},
    )
    dashboard_id: Optional[str] = Field(
        None,
        title="Dashboard ID",
        description="Dashboard to deliver",
        json_schema_extra={"x-dynamic-options": _dynamic_options("dashboard_id", "Select a dashboard…")},
    )
    crontab: str = Field(
        ..., title="Crontab", description="Cron schedule, e.g. '0 9 * * *' for daily at 9am"
    )
    destination_address: str = Field(
        ..., title="Destination Email", description="Email address to deliver the content to"
    )
    result_format: str = Field(
        "csv",
        title="Format",
        description="Delivery format",
        json_schema_extra={
            "enum": ["csv", "xlsx", "json", "pdf", "png", "wysiwyg_pdf", "assembled_pdf"],
            "x-enum-searchable": True,
        },
    )


class LookerRunScheduledPlanOnceConfig(BaseModel):
    """Immediately deliver a Look/dashboard without saving a schedule."""

    operation: Literal["run_scheduled_plan_once"] = Field(
        "run_scheduled_plan_once",
        json_schema_extra={
            "const": "run_scheduled_plan_once",
            "ui:hidden": True,
            "x-category": "Scheduled Plans",
            "x-is-trigger": False,
            "x-display-name": "Run Scheduled Plan Once",
        },
        title="Run Scheduled Plan Once",
    )
    name: str = Field(..., title="Name", description="Name for this one-time delivery")
    look_id: Optional[str] = Field(
        None,
        title="Look ID",
        description="Look to deliver (Look or dashboard required)",
        json_schema_extra={"x-dynamic-options": _dynamic_options("look_id", "Select a Look…")},
    )
    dashboard_id: Optional[str] = Field(
        None,
        title="Dashboard ID",
        description="Dashboard to deliver",
        json_schema_extra={"x-dynamic-options": _dynamic_options("dashboard_id", "Select a dashboard…")},
    )
    destination_address: str = Field(
        ..., title="Destination Email", description="Email address to deliver the content to"
    )
    result_format: str = Field(
        "csv",
        title="Format",
        description="Delivery format",
        json_schema_extra={
            "enum": ["csv", "xlsx", "json", "pdf", "png", "wysiwyg_pdf", "assembled_pdf"],
            "x-enum-searchable": True,
        },
    )


class LookerGetQueryConfig(BaseModel):
    """Fetch a saved query's definition by id."""

    operation: Literal["get_query"] = Field(
        "get_query",
        json_schema_extra={
            "const": "get_query", "ui:hidden": True, "x-category": "Queries",
            "x-is-trigger": False, "x-display-name": "Get Query",
        },
        title="Get Query",
    )
    query_id: str = Field(..., title="Query ID", description="The id of the query to fetch")


class LookerGetQueryTaskConfig(BaseModel):
    """Check the status of a running async query task."""

    operation: Literal["get_query_task"] = Field(
        "get_query_task",
        json_schema_extra={
            "const": "get_query_task", "ui:hidden": True, "x-category": "Queries",
            "x-is-trigger": False, "x-display-name": "Get Async Query Status",
        },
        title="Get Async Query Status",
    )
    query_task_id: str = Field(
        ..., title="Query Task ID", description="The query_task_id returned when starting the async query"
    )


class LookerCreateSqlQueryConfig(BaseModel):
    """Create a raw SQL Runner query (returns a slug to run)."""

    operation: Literal["create_sql_query"] = Field(
        "create_sql_query",
        json_schema_extra={
            "const": "create_sql_query", "ui:hidden": True, "x-category": "SQL Runner",
            "x-is-trigger": False, "x-display-name": "Create SQL Query",
        },
        title="Create SQL Query",
    )
    connection_name: Optional[str] = Field(
        None,
        title="Connection",
        description="Database connection to run against (connection or model required)",
        json_schema_extra={"x-dynamic-options": _dynamic_options("connection_name", "Select a connection…")},
    )
    model_name: Optional[str] = Field(
        None,
        title="Model",
        description="LookML model to run against (uses its connection)",
        json_schema_extra={"x-dynamic-options": _dynamic_options("model_name", "Select a model…")},
    )
    sql: str = Field(
        ..., title="SQL", description="The raw SQL to execute",
        json_schema_extra={"ui:widget": "textarea"},
    )


class LookerRunSqlQueryConfig(BaseModel):
    """Run a previously created SQL Runner query by slug."""

    operation: Literal["run_sql_query"] = Field(
        "run_sql_query",
        json_schema_extra={
            "const": "run_sql_query", "ui:hidden": True, "x-category": "SQL Runner",
            "x-is-trigger": False, "x-display-name": "Run SQL Query",
        },
        title="Run SQL Query",
    )
    slug: str = Field(..., title="Query Slug", description="The slug returned by Create SQL Query")
    result_format: str = Field(
        "json",
        title="Result Format",
        description="Output format for the SQL results",
        json_schema_extra={"enum": RESULT_FORMATS, "x-enum-searchable": True},
    )


class LookerGetLookmlModelConfig(BaseModel):
    """Get a LookML model's metadata (its explores, label, project)."""

    operation: Literal["get_lookml_model"] = Field(
        "get_lookml_model",
        json_schema_extra={
            "const": "get_lookml_model", "ui:hidden": True, "x-category": "LookML",
            "x-is-trigger": False, "x-display-name": "Get LookML Model",
        },
        title="Get LookML Model",
    )
    model: str = Field(
        ..., title="Model", description="LookML model name",
        json_schema_extra={"x-dynamic-options": _dynamic_options("model", "Select a model…")},
    )


class LookerGetExploreConfig(BaseModel):
    """Get an explore's field metadata (dimensions, measures, filters)."""

    operation: Literal["get_explore"] = Field(
        "get_explore",
        json_schema_extra={
            "const": "get_explore", "ui:hidden": True, "x-category": "LookML",
            "x-is-trigger": False, "x-display-name": "Get Explore Fields",
        },
        title="Get Explore Fields",
    )
    model: str = Field(
        ..., title="Model", description="LookML model name",
        json_schema_extra={"x-dynamic-options": _dynamic_options("model", "Select a model…")},
    )
    explore: str = Field(
        ..., title="Explore", description="Explore (view) name within the model",
        json_schema_extra={"x-dynamic-options": _dynamic_options("explore", "Select an explore…", depends_on="model")},
    )


class LookerSearchContentConfig(BaseModel):
    """Search across Looks and dashboards by free-text terms."""

    operation: Literal["search_content"] = Field(
        "search_content",
        json_schema_extra={
            "const": "search_content", "ui:hidden": True, "x-category": "Content",
            "x-is-trigger": False, "x-display-name": "Search Content",
        },
        title="Search Content",
    )
    terms: str = Field(..., title="Search Terms", description="Free-text terms to search content titles/descriptions")


class LookerListScheduledPlansConfig(BaseModel):
    """List scheduled plans owned by the API user (or all users, admin only)."""

    operation: Literal["list_scheduled_plans"] = Field(
        "list_scheduled_plans",
        json_schema_extra={
            "const": "list_scheduled_plans", "ui:hidden": True, "x-category": "Scheduled Plans",
            "x-is-trigger": False, "x-display-name": "List Scheduled Plans",
        },
        title="List Scheduled Plans",
    )
    user_id: Optional[str] = Field(None, title="User ID", description="Filter to a plan owner")
    all_users: Optional[str] = Field(
        None,
        title="All Users",
        description="Include plans owned by all users (requires admin)",
        json_schema_extra={
            "enum": ["", "true", "false"], "enumNames": ["No", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class LookerGetScheduledPlanConfig(BaseModel):
    """Get a scheduled plan by id."""

    operation: Literal["get_scheduled_plan"] = Field(
        "get_scheduled_plan",
        json_schema_extra={
            "const": "get_scheduled_plan", "ui:hidden": True, "x-category": "Scheduled Plans",
            "x-is-trigger": False, "x-display-name": "Get Scheduled Plan",
        },
        title="Get Scheduled Plan",
    )
    scheduled_plan_id: str = Field(..., title="Scheduled Plan ID", description="The id of the scheduled plan")


class LookerDeleteScheduledPlanConfig(BaseModel):
    """Delete a scheduled plan."""

    operation: Literal["delete_scheduled_plan"] = Field(
        "delete_scheduled_plan",
        json_schema_extra={
            "const": "delete_scheduled_plan", "ui:hidden": True, "x-category": "Scheduled Plans",
            "x-is-trigger": False, "x-display-name": "Delete Scheduled Plan",
        },
        title="Delete Scheduled Plan",
    )
    scheduled_plan_id: str = Field(..., title="Scheduled Plan ID", description="The id of the scheduled plan to delete")


class LookerGetAlertConfig(BaseModel):
    """Get a data-driven alert by id."""

    operation: Literal["get_alert"] = Field(
        "get_alert",
        json_schema_extra={
            "const": "get_alert", "ui:hidden": True, "x-category": "Content",
            "x-is-trigger": False, "x-display-name": "Get Alert",
        },
        title="Get Alert",
    )
    alert_id: str = Field(..., title="Alert ID", description="The id of the alert")


class LookerDeleteAlertConfig(BaseModel):
    """Delete a data-driven alert."""

    operation: Literal["delete_alert"] = Field(
        "delete_alert",
        json_schema_extra={
            "const": "delete_alert", "ui:hidden": True, "x-category": "Content",
            "x-is-trigger": False, "x-display-name": "Delete Alert",
        },
        title="Delete Alert",
    )
    alert_id: str = Field(..., title="Alert ID", description="The id of the alert to delete")


class LookerOnLookResultsConfig(PollTriggerConfigBase):
    """Poll-based trigger: run a saved Look on a schedule and emit its result rows.

    Looker has no inbound webhook subscription API, so this trigger polls: a
    Cloudflare cron Durable Object fires on the configured interval and POSTs the
    node's internal webhook URL, then ``execute()`` runs the selected Look (JSON).
    The first poll baselines (emits nothing); afterwards only rows not seen on a
    previous poll are emitted, deduplicating on ``cursor_field`` when set (a
    stable id/timestamp column) or on the whole row otherwise. Webhook + schedule
    provisioning, seen-set persistence, and teardown come from
    ``ScheduledPollTriggerMixin``.
    """

    operation: Literal["on_look_results"] = Field(
        "on_look_results",
        json_schema_extra={
            "const": "on_look_results",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Scheduled Look Results",
        },
        title="On Scheduled Look Results",
    )
    look_id: str = Field(
        ...,
        title="Look",
        description="The saved Look to run on each poll",
        json_schema_extra={"x-dynamic-options": _dynamic_options("look_id", "Select a Look…")},
    )
    cursor_field: Optional[str] = Field(
        None,
        title="Cursor Field",
        description=(
            "Optional column in the Look's results (e.g. a created/updated timestamp "
            "or row id) used as the de-dup key. Leave empty to de-dup on the whole "
            "row. Either way, only rows not seen on a previous poll are emitted."
        ),
        json_schema_extra={"placeholder": "orders.created_time"},
    )
    limit: Optional[str] = Field(
        None, title="Row Limit", description="Override the Look's row limit"
    )


# ============================================================================
# Discriminated Union
# ============================================================================


LookerConfig = Annotated[
    Union[
        LookerLogoutConfig,
        LookerGetCurrentUserConfig,
        LookerRunInlineQueryConfig,
        LookerCreateQueryConfig,
        LookerRunQueryConfig,
        LookerRunQueryAsyncConfig,
        LookerGetQueryTaskResultsConfig,
        LookerGetQueryConfig,
        LookerGetQueryTaskConfig,
        LookerCreateSqlQueryConfig,
        LookerRunSqlQueryConfig,
        LookerGetLookmlModelConfig,
        LookerGetExploreConfig,
        LookerSearchContentConfig,
        LookerSearchLooksConfig,
        LookerGetLookConfig,
        LookerRunLookConfig,
        LookerCreateLookConfig,
        LookerUpdateLookConfig,
        LookerDeleteLookConfig,
        LookerSearchDashboardsConfig,
        LookerGetDashboardConfig,
        LookerCreateDashboardConfig,
        LookerUpdateDashboardConfig,
        LookerDeleteDashboardConfig,
        LookerCreateRenderTaskConfig,
        LookerGetRenderTaskConfig,
        LookerSearchUsersConfig,
        LookerCreateUserConfig,
        LookerUpdateUserConfig,
        LookerDeleteUserConfig,
        LookerSearchFoldersConfig,
        LookerListConnectionsConfig,
        LookerSearchAlertsConfig,
        LookerGetAlertConfig,
        LookerDeleteAlertConfig,
        LookerCreateScheduledPlanConfig,
        LookerRunScheduledPlanOnceConfig,
        LookerListScheduledPlansConfig,
        LookerGetScheduledPlanConfig,
        LookerDeleteScheduledPlanConfig,
        # Trigger
        LookerOnLookResultsConfig,
    ],
    Discriminator("operation"),
]


class LookerNodeConfig(NodeConfig[LookerConfig, LookerCredential]):
    """Full configuration for the Looker node including credentials."""

    pass


# ============================================================================
# Auth + HTTP helpers
# ============================================================================


def _parse_json_obj(value: Optional[str], field: str) -> Optional[Dict[str, Any]]:
    """Parse a JSON-object config string, raising a clear error on bad input."""
    if not value:
        return None
    import json

    try:
        parsed = json.loads(value)
    except Exception:
        raise ValueError(f"{field} must be valid JSON")
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must be a JSON object")
    return parsed


def _to_bool(value: Optional[str]) -> Optional[bool]:
    if value is None or value == "":
        return None
    return value == "true"


class _LookerRequestError(ValueError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


async def _looker_login(client: httpx.AsyncClient, base_url: str, credential: Dict[str, Any]) -> str:
    """Exchange client_id + client_secret for a short-lived access token."""
    client_id = credential.get("client_id")
    client_secret = credential.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError("Looker client_id and client_secret are required")
    response = await client.post(
        f"{base_url}/login",
        data={"client_id": client_id, "client_secret": client_secret},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if not 200 <= response.status_code < 300:
        raise _LookerRequestError(
            f"Looker login failed ({response.status_code})", response.status_code
        )
    try:
        payload = response.json()
    except ValueError:
        raise _LookerRequestError("Looker login returned invalid JSON") from None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip() or len(token) > 8192:
        raise _LookerRequestError("Looker login response did not include a valid access_token")
    return token


async def _looker_request(
    credential: Dict[str, Any],
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
    result_format: Optional[str] = None,
) -> Dict[str, Any]:
    """Login then make an authenticated Looker API 4.0 request.

    Uses the non-standard `Authorization: token <token>` header (literal `token`).
    """
    base_url = _normalize_base_url(credential.get("instance_url", ""))
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}

    start = time.time()
    def _error(message: str, status_code: int) -> Dict[str, Any]:
        return {
            "status": "error", "action": action_name, "error": message,
            "status_code": status_code,
            "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
        }

    try:
        # The instance is user-configured. Guard the DNS answer and every request,
        # and never forward a login form or token across a redirect.
        async with guarded_async_client(timeout=60.0, verify=True, follow_redirects=False) as client:
            token = await _looker_login(client, base_url, credential)
            response = await client.request(
                method=method,
                url=f"{base_url}{endpoint}",
                headers={
                    "Authorization": f"token {token}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=json_body,
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if not 200 <= response.status_code < 300:
                logger.info("[LookerNode] %s returned HTTP %s", action_name, response.status_code)
                return _error(f"Looker request failed ({response.status_code})", response.status_code)
            if response.status_code == 202 and action_name in (
                "get_query_task_results", "get_render_task"
            ):
                pending = {
                    "status": "pending", "action": action_name,
                    "status_code": 202, "timing_ms": {"api_request": api_ms},
                }
                retry_after = response.headers.get("retry-after", "")
                if retry_after.isdecimal() and int(retry_after) <= 3600:
                    pending["retry_after_seconds"] = int(retry_after)
                return pending
            if action_name == "get_current_user" and (
                response.status_code != 200 or not response.content
            ):
                return _error("Looker returned an invalid user identity", response.status_code)
            if response.status_code == 204 or not response.content:
                data: Any = {"success": True}
            else:
                content_type = str(response.headers.get("content-type", "")).split(";", 1)[0].lower()
                fmt = result_format or ""
                if action_name == "get_render_task" and content_type not in (
                    "application/pdf", "image/png", "image/jpeg",
                    "application/octet-stream",
                ):
                    return _error("Looker returned an invalid render result", response.status_code)
                if fmt in _BINARY_FORMATS and (
                    content_type.startswith("text/") or content_type.endswith("json")
                ):
                    return _error("Looker returned an invalid binary result", response.status_code)
                if fmt in _TEXT_FORMATS and content_type.endswith("json"):
                    return _error("Looker returned an invalid text result", response.status_code)
                if action_name == "get_render_task" or fmt in _BINARY_FORMATS or (
                    action_name == "get_query_task_results" and content_type in (
                        "application/pdf", "image/png", "image/jpeg", _BINARY_MIME["xlsx"],
                        "application/octet-stream",
                    )
                ):
                    extension = fmt if fmt in _BINARY_FORMATS else {
                        "application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg",
                        _BINARY_MIME["xlsx"]: "xlsx",
                    }.get(content_type, "bin")
                    data = BinaryOutput(
                        data=response.content,
                        content_type=content_type or _BINARY_MIME.get(extension, "application/octet-stream"),
                        filename=f"looker_{action_name}.{extension}",
                    )
                elif fmt in _TEXT_FORMATS or (
                    action_name == "get_query_task_results" and content_type.startswith("text/")
                ):
                    data = {"raw": response.text}
                else:
                    try:
                        data = response.json()
                    except ValueError:
                        return _error("Looker returned invalid JSON", response.status_code)
                    if (action_name == "get_query_task_results" or fmt == "json_detail") and (
                        isinstance(data, dict) and data.get("errors")
                    ):
                        # json_detail reports SQL failures inside HTTP 200.
                        # Error details may contain SQL or tenant data.
                        return _error("Looker query returned SQL errors", response.status_code)
                    if action_name == "get_current_user":
                        user_id = data.get("id") if isinstance(data, dict) else None
                        if (isinstance(user_id, bool) or not isinstance(user_id, (str, int))
                                or not str(user_id).strip() or len(str(user_id)) > 100):
                            return _error("Looker returned an invalid user identity", response.status_code)
                        # A proxy may ignore fields=. Keep only documented,
                        # nonsecret identity scalars; User also contains
                        # credential subobjects with one-use URLs.
                        data = {
                            key: value for key in (
                                "id", "first_name", "last_name", "email", "display_name"
                            ) if isinstance((value := data.get(key)), (str, int))
                            and not isinstance(value, bool) and len(str(value)) <= 300
                        }
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
    except _LookerRequestError as exc:
        return _error(str(exc), exc.status_code)
    except httpx.TimeoutException:
        return _error("Looker request timed out", 408)
    except Exception:
        logger.warning("[LookerNode] %s transport failed", action_name)
        return _error("Looker request could not be completed", 502)


def _config_value(config_data: Optional[Dict[str, Any]], field: str) -> Optional[str]:
    """Read a sibling field value for ``depends_on`` from the loader's config_data.

    Config fields may arrive flat or nested under a ``config`` key, so check both.
    """
    if not isinstance(config_data, dict):
        return None
    value = config_data.get(field)
    if value in (None, "") and isinstance(config_data.get("config"), dict):
        value = config_data["config"].get(field)
    return value or None


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _int_or_none(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ============================================================================
# Node Implementation
# ============================================================================


class LookerNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Google Looker BI automation node."""

    integration_type = "automation-looker"

    edit_examples = [
        "Run an inline query against the orders model and return the results as JSON",
        "Run a saved Look and pull its data into the workflow",
        "Search dashboards by title in a specific folder",
        "Render a dashboard to PDF and download it",
        "Email a dashboard on a daily schedule via a scheduled plan",
    ]

    connection_evidence = ConnectionEvidence(
        identity_operation="get_current_user",
        noun="Looker user",
        identity_keys=("email", "display_name", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return LookerNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (models, explores, folders, Looks, dashboards)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Load dropdown options for Looker resource-reference fields.

        ``folder_id``/``parent_id``, ``look_id``, ``dashboard_id`` and ``model``
        are top-level listable resources. ``view`` lists the explores of the
        model selected in the same operation (``depends_on": "model"``), read
        from ``config_data``.
        """
        loaders = {
            "model", "model_name", "view", "explore", "folder_id", "parent_id",
            "look_id", "dashboard_id", "connection_name",
        }
        if field_name not in loaders:
            return []
        if not credential_data:
            raise ValueError("Connect a Looker account to load options")
        credential = credential_data

        if field_name in ("model", "model_name"):
            options = await cls._list_options(
                credential, "/lookml_models", "list_lookml_models",
                params={"fields": "name,label"}, value_key="name", label_keys=("label", "name"),
            )
        elif field_name == "connection_name":
            options = await cls._list_options(
                credential, "/connections", "list_connections",
                params={"fields": "name,dialect_name"}, value_key="name", label_keys=("name",),
            )
        elif field_name in ("view", "explore"):
            model = _config_value(context, "model")
            if not model:
                return []
            result = await _looker_request(
                credential, "GET", f"/lookml_models/{model}",
                params={"fields": "explores"}, action_name="get_lookml_model",
            )
            if result.get("status") != "success":
                raise ValueError(result.get("error", "Looker model options could not be loaded"))
            data = result.get("data")
            explores = (data or {}).get("explores") if isinstance(data, dict) else None
            options = cls._map_options(explores, "name", ("label", "name"))
        elif field_name in ("folder_id", "parent_id"):
            options = await cls._list_options(
                credential, "/folders", "list_folders",
                params={"fields": "id,name"}, value_key="id", label_keys=("name", "id"),
            )
        elif field_name == "look_id":
            options = await cls._list_options(
                credential, "/looks", "list_looks",
                params={"fields": "id,title"}, value_key="id", label_keys=("title", "id"),
            )
        else:
            options = await cls._list_options(
                credential, "/dashboards", "list_dashboards",
                params={"fields": "id,title"}, value_key="id", label_keys=("title", "id"),
            )
        query = (search or "").strip().casefold()
        return [opt for opt in options if query in opt["label"].casefold()
                or query in opt["value"].casefold()] if query else options

    @classmethod
    async def _list_options(
        cls,
        credential: Dict[str, Any],
        endpoint: str,
        action_name: str,
        *,
        params: Optional[Dict[str, Any]],
        value_key: str,
        label_keys: tuple,
    ) -> List[Dict[str, str]]:
        """GET a Looker list endpoint and map rows to dropdown options."""
        result = await _looker_request(
            credential, "GET", endpoint, params=params, action_name=action_name
        )
        if result.get("status") != "success":
            raise ValueError(result.get("error", "Looker options could not be loaded"))
        return cls._map_options(result.get("data"), value_key, label_keys)

    @staticmethod
    def _map_options(rows: Any, value_key: str, label_keys: tuple) -> List[Dict[str, str]]:
        """Map API rows to ``[{label, value}]``, using the first present label key."""
        if not isinstance(rows, list):
            raise ValueError("Looker returned invalid options")
        options: List[Dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Looker returned invalid options")
            value = row.get(value_key)
            if value is None or value == "":
                raise ValueError("Looker returned invalid options")
            label = next((row[k] for k in label_keys if row.get(k)), value)
            options.append({"label": str(label), "value": str(value)})
        return options

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, LookerNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Looker API credentials.")
        cred = {
            "instance_url": credentials.instance_url,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
        }

        handlers = {
            "logout": self._logout,
            "get_current_user": self._get_current_user,
            "run_inline_query": self._run_inline_query,
            "create_query": self._create_query,
            "run_query": self._run_query,
            "run_query_async": self._run_query_async,
            "get_query_task_results": self._get_query_task_results,
            "get_query": self._get_query,
            "get_query_task": self._get_query_task,
            "create_sql_query": self._create_sql_query,
            "run_sql_query": self._run_sql_query,
            "get_lookml_model": self._get_lookml_model,
            "get_explore": self._get_explore,
            "search_content": self._search_content,
            "search_looks": self._search_looks,
            "get_look": self._get_look,
            "run_look": self._run_look,
            "create_look": self._create_look,
            "update_look": self._update_look,
            "delete_look": self._delete_look,
            "search_dashboards": self._search_dashboards,
            "get_dashboard": self._get_dashboard,
            "create_dashboard": self._create_dashboard,
            "update_dashboard": self._update_dashboard,
            "delete_dashboard": self._delete_dashboard,
            "create_render_task": self._create_render_task,
            "get_render_task": self._get_render_task,
            "search_users": self._search_users,
            "create_user": self._create_user,
            "update_user": self._update_user,
            "delete_user": self._delete_user,
            "search_folders": self._search_folders,
            "list_connections": self._list_connections,
            "search_alerts": self._search_alerts,
            "get_alert": self._get_alert,
            "delete_alert": self._delete_alert,
            "create_scheduled_plan": self._create_scheduled_plan,
            "run_scheduled_plan_once": self._run_scheduled_plan_once,
            "list_scheduled_plans": self._list_scheduled_plans,
            "get_scheduled_plan": self._get_scheduled_plan,
            "delete_scheduled_plan": self._delete_scheduled_plan,
            "on_look_results": self._on_look_results,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, cred)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Auth / Profile handlers
    # ------------------------------------------------------------------
    async def _logout(self, c: LookerLogoutConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "DELETE", "/logout", action_name="logout")

    async def _get_current_user(self, c: LookerGetCurrentUserConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(
            cred, "GET", "/user", params={"fields": "id,first_name,last_name,email,display_name"},
            action_name="get_current_user",
        )

    # ------------------------------------------------------------------
    # Query handlers
    # ------------------------------------------------------------------
    async def _run_inline_query(self, c: LookerRunInlineQueryConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "model": c.model,
            "view": c.view,
            "fields": _comma_list(c.fields),
            "filters": _parse_json_obj(c.filters, "Filters"),
            "sorts": _comma_list(c.sorts),
            "limit": c.limit,
        }
        return await _looker_request(
            cred, "POST", f"/queries/run/{c.result_format}", json_body=body,
            action_name="run_inline_query", result_format=c.result_format,
        )

    async def _create_query(self, c: LookerCreateQueryConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "model": c.model,
            "view": c.view,
            "fields": _comma_list(c.fields),
            "filters": _parse_json_obj(c.filters, "Filters"),
            "sorts": _comma_list(c.sorts),
            "limit": c.limit,
        }
        return await _looker_request(cred, "POST", "/queries", json_body=body, action_name="create_query")

    async def _run_query(self, c: LookerRunQueryConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(
            cred, "GET", f"/queries/{c.query_id}/run/{c.result_format}",
            action_name="run_query", result_format=c.result_format,
        )

    async def _run_query_async(self, c: LookerRunQueryAsyncConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {"query_id": _int_or_none(c.query_id) or c.query_id, "result_format": c.result_format}
        return await _looker_request(cred, "POST", "/query_tasks", json_body=body, action_name="run_query_async")

    async def _get_query_task_results(self, c: LookerGetQueryTaskResultsConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(
            cred, "GET", f"/query_tasks/{c.query_task_id}/results", action_name="get_query_task_results"
        )

    async def _get_query(self, c: LookerGetQueryConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "GET", f"/queries/{c.query_id}", action_name="get_query")

    async def _get_query_task(self, c: LookerGetQueryTaskConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(
            cred, "GET", f"/query_tasks/{c.query_task_id}", action_name="get_query_task"
        )

    # ------------------------------------------------------------------
    # SQL Runner handlers
    # ------------------------------------------------------------------
    async def _create_sql_query(self, c: LookerCreateSqlQueryConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        if not c.connection_name and not c.model_name:
            raise ValueError("A connection or a model is required to create a SQL query")
        body = {"connection_name": c.connection_name, "model_name": c.model_name, "sql": c.sql}
        return await _looker_request(cred, "POST", "/sql_queries", json_body=body, action_name="create_sql_query")

    async def _run_sql_query(self, c: LookerRunSqlQueryConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(
            cred, "POST", f"/sql_queries/{c.slug}/run/{c.result_format}",
            action_name="run_sql_query", result_format=c.result_format,
        )

    # ------------------------------------------------------------------
    # LookML metadata handlers
    # ------------------------------------------------------------------
    async def _get_lookml_model(self, c: LookerGetLookmlModelConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "GET", f"/lookml_models/{c.model}", action_name="get_lookml_model")

    async def _get_explore(self, c: LookerGetExploreConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(
            cred, "GET", f"/lookml_models/{c.model}/explores/{c.explore}", action_name="get_explore"
        )

    async def _search_content(self, c: LookerSearchContentConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "GET", f"/content/{c.terms}", action_name="search_content")

    # ------------------------------------------------------------------
    # Look handlers
    # ------------------------------------------------------------------
    async def _search_looks(self, c: LookerSearchLooksConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        params = {
            "title": c.title,
            "user_id": c.user_id,
            "folder_id": c.folder_id,
            "limit": c.limit,
            "offset": c.offset,
        }
        return await _looker_request(cred, "GET", "/looks/search", params=params, action_name="search_looks")

    async def _get_look(self, c: LookerGetLookConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "GET", f"/looks/{c.look_id}", action_name="get_look")

    async def _run_look(self, c: LookerRunLookConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        params = {"limit": c.limit}
        return await _looker_request(
            cred, "GET", f"/looks/{c.look_id}/run/{c.result_format}", params=params,
            action_name="run_look", result_format=c.result_format,
        )

    async def _create_look(self, c: LookerCreateLookConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "query_id": _int_or_none(c.query_id) or c.query_id,
            "folder_id": c.folder_id,
            "description": c.description,
        }
        return await _looker_request(cred, "POST", "/looks", json_body=body, action_name="create_look")

    async def _update_look(self, c: LookerUpdateLookConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "folder_id": c.folder_id,
            "description": c.description,
            "deleted": _to_bool(c.deleted),
        }
        return await _looker_request(cred, "PATCH", f"/looks/{c.look_id}", json_body=body, action_name="update_look")

    async def _delete_look(self, c: LookerDeleteLookConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "DELETE", f"/looks/{c.look_id}", action_name="delete_look")

    # ------------------------------------------------------------------
    # Dashboard handlers
    # ------------------------------------------------------------------
    async def _search_dashboards(self, c: LookerSearchDashboardsConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        params = {
            "title": c.title,
            "folder_id": c.folder_id,
            "user_id": c.user_id,
            "limit": c.limit,
            "offset": c.offset,
        }
        return await _looker_request(cred, "GET", "/dashboards/search", params=params, action_name="search_dashboards")

    async def _get_dashboard(self, c: LookerGetDashboardConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "GET", f"/dashboards/{c.dashboard_id}", action_name="get_dashboard")

    async def _create_dashboard(self, c: LookerCreateDashboardConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {"title": c.title, "folder_id": c.folder_id, "description": c.description}
        return await _looker_request(cred, "POST", "/dashboards", json_body=body, action_name="create_dashboard")

    async def _update_dashboard(self, c: LookerUpdateDashboardConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {"title": c.title, "folder_id": c.folder_id, "description": c.description}
        return await _looker_request(
            cred, "PATCH", f"/dashboards/{c.dashboard_id}", json_body=body, action_name="update_dashboard"
        )

    async def _delete_dashboard(self, c: LookerDeleteDashboardConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "DELETE", f"/dashboards/{c.dashboard_id}", action_name="delete_dashboard")

    async def _create_render_task(self, c: LookerCreateRenderTaskConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        params = {"width": c.width, "height": c.height}
        return await _looker_request(
            cred,
            "POST",
            f"/render_tasks/dashboards/{c.dashboard_id}/{c.result_format}",
            params=params,
            json_body={},
            action_name="create_render_task",
        )

    async def _get_render_task(self, c: LookerGetRenderTaskConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(
            cred, "GET", f"/render_tasks/{c.render_task_id}/results", action_name="get_render_task"
        )

    # ------------------------------------------------------------------
    # User handlers
    # ------------------------------------------------------------------
    async def _search_users(self, c: LookerSearchUsersConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        params = {
            "email": c.email,
            "first_name": c.first_name,
            "last_name": c.last_name,
            "limit": c.limit,
            "offset": c.offset,
        }
        return await _looker_request(cred, "GET", "/users/search", params=params, action_name="search_users")

    async def _create_user(self, c: LookerCreateUserConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "first_name": c.first_name,
            "last_name": c.last_name,
            "email": c.email,
            "is_disabled": _to_bool(c.is_disabled),
        }
        return await _looker_request(cred, "POST", "/users", json_body=body, action_name="create_user")

    async def _update_user(self, c: LookerUpdateUserConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "first_name": c.first_name,
            "last_name": c.last_name,
            "is_disabled": _to_bool(c.is_disabled),
        }
        return await _looker_request(cred, "PATCH", f"/users/{c.user_id}", json_body=body, action_name="update_user")

    async def _delete_user(self, c: LookerDeleteUserConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "DELETE", f"/users/{c.user_id}", action_name="delete_user")

    # ------------------------------------------------------------------
    # Content handlers
    # ------------------------------------------------------------------
    async def _search_folders(self, c: LookerSearchFoldersConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        params = {
            "name": c.name,
            "parent_id": c.parent_id,
            "limit": c.limit,
            "offset": c.offset,
        }
        return await _looker_request(cred, "GET", "/folders/search", params=params, action_name="search_folders")

    async def _list_connections(self, c: LookerListConnectionsConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "GET", "/connections", action_name="list_connections")

    async def _search_alerts(self, c: LookerSearchAlertsConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        params = {"limit": c.limit, "offset": c.offset, "group_by": c.group_by}
        return await _looker_request(cred, "GET", "/alerts/search", params=params, action_name="search_alerts")

    async def _get_alert(self, c: LookerGetAlertConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "GET", f"/alerts/{c.alert_id}", action_name="get_alert")

    async def _delete_alert(self, c: LookerDeleteAlertConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(cred, "DELETE", f"/alerts/{c.alert_id}", action_name="delete_alert")

    # ------------------------------------------------------------------
    # Scheduled plan handlers
    # ------------------------------------------------------------------
    def _scheduled_plan_destination(self, c, fmt: str) -> List[Dict[str, Any]]:
        return [
            {
                "type": "email",
                "format": fmt,
                "address": c.destination_address,
            }
        ]

    async def _create_scheduled_plan(self, c: LookerCreateScheduledPlanConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "look_id": _int_or_none(c.look_id),
            "dashboard_id": _int_or_none(c.dashboard_id),
            "crontab": c.crontab,
            "scheduled_plan_destination": self._scheduled_plan_destination(c, c.result_format),
        }
        return await _looker_request(
            cred, "POST", "/scheduled_plans", json_body=body, action_name="create_scheduled_plan"
        )

    async def _run_scheduled_plan_once(self, c: LookerRunScheduledPlanOnceConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "look_id": _int_or_none(c.look_id),
            "dashboard_id": _int_or_none(c.dashboard_id),
            "scheduled_plan_destination": self._scheduled_plan_destination(c, c.result_format),
        }
        return await _looker_request(
            cred, "POST", "/scheduled_plans/run_once", json_body=body, action_name="run_scheduled_plan_once"
        )

    async def _list_scheduled_plans(self, c: LookerListScheduledPlansConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        params = {"user_id": c.user_id, "all_users": _to_bool(c.all_users)}
        return await _looker_request(cred, "GET", "/scheduled_plans", params=params, action_name="list_scheduled_plans")

    async def _get_scheduled_plan(self, c: LookerGetScheduledPlanConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(
            cred, "GET", f"/scheduled_plans/{c.scheduled_plan_id}", action_name="get_scheduled_plan"
        )

    async def _delete_scheduled_plan(self, c: LookerDeleteScheduledPlanConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        return await _looker_request(
            cred, "DELETE", f"/scheduled_plans/{c.scheduled_plan_id}", action_name="delete_scheduled_plan"
        )

    # ------------------------------------------------------------------
    # Trigger handler (scheduled-query poll)
    # ------------------------------------------------------------------
    async def _on_look_results(self, c: LookerOnLookResultsConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        """Run the selected Look on each poll and emit only rows not seen before.

        Dedup + persistence come from ``ScheduledPollTriggerMixin._filter_unseen``:
        the first poll baselines (emits nothing), then each row is keyed by
        ``cursor_field`` (when set) or its full JSON otherwise, and only unseen
        keys are emitted. The seen-set is persisted in node state, so dedup holds
        across polls and container restarts.
        """
        import json as _json

        params = {"limit": c.limit} if c.limit else None
        result = await _looker_request(
            cred, "GET", f"/looks/{c.look_id}/run/json", params=params, action_name="on_look_results"
        )
        if result.get("status") != "success":
            return result

        rows = result.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return {
                "status": "error", "operation": "on_look_results",
                "error": "Looker returned invalid Look results",
                "status_code": result.get("status_code", 200),
                "timing_ms": result.get("timing_ms", {}),
            }

        cursor_field = c.cursor_field

        def _row_id(row: Dict[str, Any]) -> Optional[str]:
            if cursor_field:
                value = row.get(cursor_field)
                return str(value) if value is not None else None
            return _json.dumps(row, sort_keys=True, default=str)

        new_rows = await self._filter_unseen(rows, _row_id)

        return {
            "status": "success",
            "operation": "on_look_results",
            "look_id": c.look_id,
            "cursor_field": cursor_field,
            "new_count": len(new_rows),
            "items": new_rows,
            "timestamp": time.time(),
            "timing_ms": result.get("timing_ms", {}),
        }
