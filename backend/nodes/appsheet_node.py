"""
Google AppSheet automation node.

Provides workflow integration with the AppSheet REST API (v2). The AppSheet API
is a single POST "Action" RPC surface — every call targets
``.../apps/{appId}/tables/{tableName}/Action`` and the operation is selected by
the ``Action`` field in the JSON body (``Add``, ``Edit``, ``Delete``, ``Find``,
or any custom action name defined in the app).

Operations:
- Rows: add, edit, delete
- Find: by keys, all rows, with a Selector expression (FILTER/SELECT/ORDERBY/TOP)
- Custom action: invoke an app-defined action by name
- Triggers: one passive webhook receiver per AppSheet bot event — On Rows Added /
  Updated / Deleted, On Any Data Change, On Schedule (point a bot's "Call a webhook"
  task at the matching trigger's URL)

Authentication: API Key — the per-app "Application Access Key" sent as the
``ApplicationAccessKey`` header. The App ID and data-residency region are part of
the credential since a single key is scoped to one app.

API Base URL: https://www.appsheet.com/api/v2 (region variants: eu, asia-southeast)
Documentation: https://support.google.com/appsheet/answer/10105768
"""

import json
import logging
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

# Data-residency host per region. The path suffix (/api/v2) is appended in the helper.
APPSHEET_REGION_HOSTS = {
    "global": "https://www.appsheet.com",
    "eu": "https://eu.appsheet.com",
    "asia-southeast": "https://asia-southeast.appsheet.com",
}


# ============================================================================
# Credential Schema
# ============================================================================


class AppSheetApiKeyCredential(BaseModel):
    """Application Access Key credential for a single AppSheet app."""

    credential_type: Literal["appsheet_api_key"] = Field(
        "appsheet_api_key", json_schema_extra={"ui:hidden": True}
    )
    app_id: str = Field(
        ...,
        title="App ID",
        description="The AppSheet app's unique identifier (shown in the editor URL). The access key is scoped to this app.",
    )
    application_access_key: str = Field(
        ...,
        title="Application Access Key",
        description="Per-app key from Settings -> Integrations -> 'IN: from cloud services to your app' -> Create Application Access Key (looks like V2-...). Enterprise plan required.",
        json_schema_extra={"ui:widget": "password"},
    )
    region: str = Field(
        "global",
        title="Region",
        description="Data-residency region of the app. EU/APAC apps must use their regional host.",
        json_schema_extra={
            "enum": ["global", "eu", "asia-southeast"],
            "enumNames": ["Global (www.appsheet.com)", "EU (eu.appsheet.com)", "Asia-Pacific (asia-southeast.appsheet.com)"],
            "x-enum-searchable": True,
        },
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://support.google.com/appsheet/answer/10105769"}
    )


AppSheetCredential = AppSheetApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class AppSheetAddRowsConfig(BaseModel):
    """Insert one or more new rows into a table."""

    operation: Literal["add_rows"] = Field(
        "add_rows",
        json_schema_extra={
            "const": "add_rows",
            "ui:hidden": True,
            "x-category": "Rows",
            "x-is-trigger": False,
            "x-display-name": "Add Rows",
        },
        title="Add Rows",
    )
    table_name: str = Field(
        ..., title="Table Name", description="Name of the table to add rows to (column names are case-sensitive)"
    )
    rows: str = Field(
        ...,
        title="Rows",
        description='JSON array of row objects keyed by column name, e.g. [{"FirstName": "Jane", "LastName": "Doe"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    run_as_user_email: Optional[str] = Field(
        None,
        title="Run As User Email",
        description="Execute as this app user so security filters / USEREMAIL() resolve correctly",
    )
    locale: Optional[str] = Field(
        None, title="Locale", description="Locale used to validate Date/Time/Decimal values, e.g. en-US"
    )
    timezone: Optional[str] = Field(
        None, title="Timezone", description="Timezone used to validate DateTime values, e.g. Pacific Standard Time"
    )


class AppSheetEditRowsConfig(BaseModel):
    """Update existing rows; each row must include the key column(s) plus changed columns."""

    operation: Literal["edit_rows"] = Field(
        "edit_rows",
        json_schema_extra={
            "const": "edit_rows",
            "ui:hidden": True,
            "x-category": "Rows",
            "x-is-trigger": False,
            "x-display-name": "Edit Rows",
        },
        title="Edit Rows",
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table to edit rows in")
    rows: str = Field(
        ...,
        title="Rows",
        description='JSON array of row objects; each must include the key column value(s) and the columns to change',
        json_schema_extra={"ui:widget": "textarea"},
    )
    run_as_user_email: Optional[str] = Field(
        None, title="Run As User Email", description="Execute as this app user for security filters"
    )
    locale: Optional[str] = Field(None, title="Locale", description="Locale used to validate values, e.g. en-US")
    timezone: Optional[str] = Field(None, title="Timezone", description="Timezone used to validate DateTime values")


class AppSheetDeleteRowsConfig(BaseModel):
    """Delete existing rows; each row must include the key column value(s)."""

    operation: Literal["delete_rows"] = Field(
        "delete_rows",
        json_schema_extra={
            "const": "delete_rows",
            "ui:hidden": True,
            "x-category": "Rows",
            "x-is-trigger": False,
            "x-display-name": "Delete Rows",
        },
        title="Delete Rows",
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table to delete rows from")
    rows: str = Field(
        ...,
        title="Rows",
        description='JSON array of row objects; each must include the key column value(s), e.g. [{"Id": "123"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    run_as_user_email: Optional[str] = Field(
        None, title="Run As User Email", description="Execute as this app user for security filters"
    )


class AppSheetFindRowsConfig(BaseModel):
    """Read specific rows by key; provide key values in Rows."""

    operation: Literal["find_rows"] = Field(
        "find_rows",
        json_schema_extra={
            "const": "find_rows",
            "ui:hidden": True,
            "x-category": "Find",
            "x-is-trigger": False,
            "x-display-name": "Find Rows by Key",
        },
        title="Find Rows by Key",
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table to read from")
    rows: str = Field(
        ...,
        title="Rows",
        description='JSON array of row objects holding the key column value(s) to fetch, e.g. [{"Id": "123"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    run_as_user_email: Optional[str] = Field(
        None, title="Run As User Email", description="Execute as this app user for security filters"
    )


class AppSheetFindAllRowsConfig(BaseModel):
    """Return every row in the table (empty Rows, no Selector)."""

    operation: Literal["find_all_rows"] = Field(
        "find_all_rows",
        json_schema_extra={
            "const": "find_all_rows",
            "ui:hidden": True,
            "x-category": "Find",
            "x-is-trigger": False,
            "x-display-name": "Find All Rows",
        },
        title="Find All Rows",
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table to read all rows from")
    run_as_user_email: Optional[str] = Field(
        None, title="Run As User Email", description="Execute as this app user for security filters"
    )


class AppSheetFindWithSelectorConfig(BaseModel):
    """Read rows matching an AppSheet Selector expression (FILTER/SELECT/ORDERBY/TOP)."""

    operation: Literal["find_with_selector"] = Field(
        "find_with_selector",
        json_schema_extra={
            "const": "find_with_selector",
            "ui:hidden": True,
            "x-category": "Find",
            "x-is-trigger": False,
            "x-display-name": "Find with Selector",
        },
        title="Find with Selector",
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table to read from")
    selector: str = Field(
        ...,
        title="Selector",
        description='AppSheet expression, e.g. Filter(People, [Age] >= 21), OrderBy(People, [LastName], TRUE), or Top(Filter(People,[Age]>=21),10)',
    )
    run_as_user_email: Optional[str] = Field(
        None, title="Run As User Email", description="Execute as this app user for security filters"
    )


class AppSheetInvokeActionConfig(BaseModel):
    """Run a data-change action predefined in the app against the supplied rows."""

    operation: Literal["invoke_action"] = Field(
        "invoke_action",
        json_schema_extra={
            "const": "invoke_action",
            "ui:hidden": True,
            "x-category": "Actions",
            "x-is-trigger": False,
            "x-display-name": "Invoke Custom Action",
        },
        title="Invoke Custom Action",
    )
    table_name: str = Field(..., title="Table Name", description="Name of the table the action operates on")
    action_name: str = Field(
        ..., title="Action Name", description="Name of the custom action defined in the app"
    )
    rows: str = Field(
        ...,
        title="Rows",
        description='JSON array of row objects the action runs against, e.g. [{"Id": "123"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    run_as_user_email: Optional[str] = Field(
        None, title="Run As User Email", description="Execute as this app user for security filters"
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


# AppSheet Automation bots fire on distinct event types (Adds / Updates /
# Deletes / any data change / scheduled). Each maps to its own passive webhook
# trigger below: the user configures a bot for that event and points its
# "Call a webhook" task at the trigger's URL. All triggers behave identically at
# runtime (pass the inbound payload through) — they differ only in the bot event
# the user should wire, which the AI builder and canvas can then express clearly.


def _webhook_url_field(bot_event: str) -> Any:
    return Field(
        default=None,
        title="Webhook URL",
        description=(
            f"Point a 'Call a webhook' task at this URL from an AppSheet Automation "
            f"bot whose event is set to {bot_event}."
        ),
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class _AppSheetWebhookTrigger(BaseModel):
    """Base for AppSheet Automation webhook triggers — passive receivers that fire
    when a bot's 'Call a webhook' task posts its event payload."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


class AppSheetOnRowsAddedConfig(_AppSheetWebhookTrigger):
    """Fires when rows are added (AppSheet bot event: 'Adds only')."""

    operation: Literal["on_rows_added"] = Field(
        "on_rows_added",
        json_schema_extra={
            "const": "on_rows_added",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Rows Added",
        },
        title="On Rows Added",
    )
    webhook_url: Optional[str] = _webhook_url_field('"Adds only" (data change)')


class AppSheetOnRowsUpdatedConfig(_AppSheetWebhookTrigger):
    """Fires when rows are updated (AppSheet bot event: 'Updates only')."""

    operation: Literal["on_rows_updated"] = Field(
        "on_rows_updated",
        json_schema_extra={
            "const": "on_rows_updated",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Rows Updated",
        },
        title="On Rows Updated",
    )
    webhook_url: Optional[str] = _webhook_url_field('"Updates only" (data change)')


class AppSheetOnRowsDeletedConfig(_AppSheetWebhookTrigger):
    """Fires when rows are deleted (AppSheet bot event: 'Deletes only')."""

    operation: Literal["on_rows_deleted"] = Field(
        "on_rows_deleted",
        json_schema_extra={
            "const": "on_rows_deleted",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Rows Deleted",
        },
        title="On Rows Deleted",
    )
    webhook_url: Optional[str] = _webhook_url_field('"Deletes only" (data change)')


class AppSheetOnDataChangeConfig(_AppSheetWebhookTrigger):
    """Fires on any data change (AppSheet bot event: 'Adds and updates' / 'All changes')."""

    operation: Literal["on_data_change"] = Field(
        "on_data_change",
        json_schema_extra={
            "const": "on_data_change",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Any Data Change",
        },
        title="On Any Data Change",
    )
    webhook_url: Optional[str] = _webhook_url_field('any data change ("Adds and updates" / "All changes")')


class AppSheetOnScheduleConfig(_AppSheetWebhookTrigger):
    """Fires on a schedule (AppSheet bot event: 'Scheduled')."""

    operation: Literal["on_schedule"] = Field(
        "on_schedule",
        json_schema_extra={
            "const": "on_schedule",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Schedule",
        },
        title="On Schedule",
    )
    webhook_url: Optional[str] = _webhook_url_field("a Scheduled event")


# ============================================================================
# Discriminated Union
# ============================================================================


AppSheetConfig = Annotated[
    Union[
        AppSheetAddRowsConfig,
        AppSheetEditRowsConfig,
        AppSheetDeleteRowsConfig,
        AppSheetFindRowsConfig,
        AppSheetFindAllRowsConfig,
        AppSheetFindWithSelectorConfig,
        AppSheetInvokeActionConfig,
        AppSheetOnRowsAddedConfig,
        AppSheetOnRowsUpdatedConfig,
        AppSheetOnRowsDeletedConfig,
        AppSheetOnDataChangeConfig,
        AppSheetOnScheduleConfig,
    ],
    Discriminator("operation"),
]


class AppSheetNodeConfig(NodeConfig[AppSheetConfig, AppSheetCredential]):
    """Full configuration for the AppSheet node including credentials."""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


def _parse_rows(value: Optional[str], field: str = "Rows") -> list:
    """Parse a JSON array of row objects from a config string.

    Raises a clear ValueError on malformed JSON rather than failing silently.
    """
    if value is None or str(value).strip() == "":
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field} must be a valid JSON array of objects: {e}")
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError(f"{field} must be a JSON array of objects")
    return parsed


def _build_properties(
    selector: Optional[str] = None,
    run_as_user_email: Optional[str] = None,
    locale: Optional[str] = None,
    timezone: Optional[str] = None,
) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    if selector:
        props["Selector"] = selector
    if run_as_user_email:
        props["RunAsUserEmail"] = run_as_user_email
    if locale:
        props["Locale"] = locale
    if timezone:
        props["Timezone"] = timezone
    return props


async def _appsheet_request(
    credential: "AppSheetCredential",
    table_name: str,
    action: str,
    rows: list,
    properties: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """POST an AppSheet Action and return a structured result.

    All operations target the same endpoint shape; the operation is selected by
    the ``Action`` field in the JSON body.
    """
    host = APPSHEET_REGION_HOSTS.get(credential.region)
    if not host:
        raise ValueError(f"Unknown AppSheet region: {credential.region}")
    url = f"{host}/api/v2/apps/{credential.app_id}/tables/{table_name}/Action"
    headers = {
        "ApplicationAccessKey": credential.application_access_key,
        "Content-Type": "application/json",
    }
    body: Dict[str, Any] = {"Action": action, "Rows": rows}
    if properties:
        body["Properties"] = properties

    start = time.time()
    # 60s: AppSheet writes append to the backing datasource (Sheets/AppSheet DB)
    # and can occasionally take >30s.
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method="POST", url=url, headers=headers, json=body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("message") if isinstance(err, dict) else str(err)
                    if not message:
                        message = response.text or str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[AppSheetNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            # AppSheet returns the affected/found rows. Find returns a bare JSON
            # array; Add/Edit/Delete wrap them as {"Rows": [...]}. Normalize both
            # to a plain list of row objects so downstream consumers see one shape.
            if response.status_code == 204 or not response.text:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
                if isinstance(data, dict) and "Rows" in data:
                    data = data["Rows"]
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
            logger.error(f"[AppSheetNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


class AppSheetNode(WorkflowNode):
    """Google AppSheet automation node."""

    edit_examples = [
        "Add a new row to the Orders table in AppSheet",
        "Edit a customer record by its key column",
        "Delete rows from a table when a deal is lost",
        "Find all rows where Age is at least 21 using a FILTER selector",
        "Trigger a workflow when an AppSheet bot posts a row-change webhook",
    ]

    @classmethod
    def get_config_model(cls):
        return AppSheetNodeConfig

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
        """Provision the internal webhook URL for the AppSheet webhook triggers.

        AppSheet outbound webhooks are configured inside an Automation bot, so we
        only mint our inbound URL — the user pastes it into the bot's webhook task.
        Shared by all trigger operations (they each expose a ``webhook_url`` field).
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

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, AppSheetNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        # Webhook trigger mode — every AppSheet trigger is a passive receiver that
        # passes the inbound bot payload through (the push path uses the base
        # resolve_trigger_payload; this handles manual runs).
        if isinstance(op, _AppSheetWebhookTrigger):
            return {
                "status": "success",
                "action": op.operation,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your AppSheet Application Access Key, App ID, and region.")

        handlers = {
            "add_rows": self._add_rows,
            "edit_rows": self._edit_rows,
            "delete_rows": self._delete_rows,
            "find_rows": self._find_rows,
            "find_all_rows": self._find_all_rows,
            "find_with_selector": self._find_with_selector,
            "invoke_action": self._invoke_action,
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
    async def _add_rows(self, c: AppSheetAddRowsConfig, cred) -> Dict[str, Any]:
        rows = _parse_rows(c.rows)
        props = _build_properties(
            run_as_user_email=c.run_as_user_email, locale=c.locale, timezone=c.timezone
        )
        return await _appsheet_request(
            cred, c.table_name, "Add", rows, properties=props, action_name="add_rows"
        )

    async def _edit_rows(self, c: AppSheetEditRowsConfig, cred) -> Dict[str, Any]:
        rows = _parse_rows(c.rows)
        props = _build_properties(
            run_as_user_email=c.run_as_user_email, locale=c.locale, timezone=c.timezone
        )
        return await _appsheet_request(
            cred, c.table_name, "Edit", rows, properties=props, action_name="edit_rows"
        )

    async def _delete_rows(self, c: AppSheetDeleteRowsConfig, cred) -> Dict[str, Any]:
        rows = _parse_rows(c.rows)
        props = _build_properties(run_as_user_email=c.run_as_user_email)
        return await _appsheet_request(
            cred, c.table_name, "Delete", rows, properties=props, action_name="delete_rows"
        )

    async def _find_rows(self, c: AppSheetFindRowsConfig, cred) -> Dict[str, Any]:
        rows = _parse_rows(c.rows)
        props = _build_properties(run_as_user_email=c.run_as_user_email)
        return await _appsheet_request(
            cred, c.table_name, "Find", rows, properties=props, action_name="find_rows"
        )

    async def _find_all_rows(self, c: AppSheetFindAllRowsConfig, cred) -> Dict[str, Any]:
        props = _build_properties(run_as_user_email=c.run_as_user_email)
        return await _appsheet_request(
            cred, c.table_name, "Find", [], properties=props, action_name="find_all_rows"
        )

    async def _find_with_selector(self, c: AppSheetFindWithSelectorConfig, cred) -> Dict[str, Any]:
        props = _build_properties(selector=c.selector, run_as_user_email=c.run_as_user_email)
        return await _appsheet_request(
            cred, c.table_name, "Find", [], properties=props, action_name="find_with_selector"
        )

    async def _invoke_action(self, c: AppSheetInvokeActionConfig, cred) -> Dict[str, Any]:
        rows = _parse_rows(c.rows)
        props = _build_properties(run_as_user_email=c.run_as_user_email)
        return await _appsheet_request(
            cred, c.table_name, c.action_name, rows, properties=props, action_name="invoke_action"
        )
