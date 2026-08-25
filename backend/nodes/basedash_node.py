"""
Basedash automation node — AI-native BI / admin platform.

Covers the Basedash public REST API across organizations, dashboards, tabs,
charts (incl. PNG render), AI chats (text-to-SQL agent), automations + runs,
data sources (DB connections) + access policies, definitions (saved SQL),
insights, MCP servers, members, groups, and skills.

API shape:
- Base URL: https://charts.basedash.com/api/public
- Auth: API key as a Bearer token (`Authorization: Bearer bd_key_…`). No OAuth.
- Envelope: success `{"data": …}` (+ `{"pagination": {"nextCursor", "hasMore"}}`
  on lists); error `{"error": {"title", "detail"}}`.
- Pagination: cursor-based — `limit` (1-100, default 50) + `cursor`.
- Every resource except `/organizations` is nested under `/organizations/{orgId}/…`.
- Some AI endpoints are async (202); pass `wait=true` for a synchronous result.

Docs: https://www.basedash.com/docs/api-reference/overview
"""

import logging
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput

logger = logging.getLogger(__name__)

BASEDASH_API = "https://charts.basedash.com/api/public"


# ============================================================================
# Credential
# ============================================================================


class BasedashApiKeyCredential(BaseModel):
    """API key credential for Basedash (Bearer token).

    Create one in Basedash: avatar (top-right) → API keys → Create. Shown once —
    copy it immediately. Most endpoints require admin access to the organization.
    """

    api_key: str = Field(
        ...,
        title="API Key",
        description="Basedash API key (starts with bd_key_)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://www.basedash.com/docs/api-reference/overview",
            "x-credential-instructions": "Basedash → avatar → API keys → Create. Copy the bd_key_… value (shown once).",
        }
    )


# ============================================================================
# Shared field factories
# ============================================================================


def _org_field():
    return Field(
        ...,
        title="Organization",
        description="Basedash organization",
        json_schema_extra={"x-dynamic-options": {
            "field_name": "organization_id", "searchable": True, "allow_custom": True,
            "placeholder": "Select organization…"}},
    )


# Inline "Create new <resource>" builder affordances: picker field -> resource.
_FIELD_RESOURCE_TYPE = {
    "dashboard_id": "basedash_dashboard",
    "data_source_id": "basedash_data_source",
}


def _dyn_field(title: str, field_name: str, placeholder: str, required: bool = True):
    extra = {"x-dynamic-options": {
        "field_name": field_name, "searchable": True, "allow_custom": True, "placeholder": placeholder}}
    rt = _FIELD_RESOURCE_TYPE.get(field_name)
    if rt:
        extra["x-resource-type"] = rt
    kw = {"title": title, "json_schema_extra": extra}
    return Field(..., **kw) if required else Field(None, **kw)


def _json_field(title: str, hint: str, default: str = "{}"):
    return Field(default, title=title, description=hint,
                 json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


def _limit_field():
    return Field(None, title="Limit", description="Max results per page (1-100, default 50)")


def _cursor_field():
    return Field(None, title="Cursor", description="Pagination cursor from a previous response's nextCursor")


class _OrgOp(BaseModel):
    """Base for every org-scoped operation — carries the organization selector first."""
    organization_id: str = _org_field()


# ============================================================================
# Operation configs (discriminated on `operation`)
# ============================================================================

# --- Organizations ---------------------------------------------------------

class BDListOrganizationsConfig(BaseModel):
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"const": "list_organizations", "ui:hidden": True, "x-category": "Organizations", "x-display-name": "List Organizations"}, title="List Organizations")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetOrganizationConfig(_OrgOp):
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"const": "get_organization", "ui:hidden": True, "x-category": "Organizations", "x-display-name": "Get Organization"}, title="Get Organization")


class BDCreateOrganizationConfig(BaseModel):
    operation: Literal["create_organization"] = Field("create_organization", json_schema_extra={"const": "create_organization", "ui:hidden": True, "x-category": "Organizations", "x-display-name": "Create Organization"}, title="Create Organization")
    name: str = Field(..., title="Name", description="New organization name")


class BDUpdateOrganizationConfig(_OrgOp):
    operation: Literal["update_organization"] = Field("update_organization", json_schema_extra={"const": "update_organization", "ui:hidden": True, "x-category": "Organizations", "x-display-name": "Update Organization"}, title="Update Organization")
    body_json: str = _json_field("Fields (JSON)", 'Fields to update, e.g. {"name":"New name","insightsEnabled":true}')


class BDGetAiUsageConfig(_OrgOp):
    operation: Literal["get_ai_usage"] = Field("get_ai_usage", json_schema_extra={"const": "get_ai_usage", "ui:hidden": True, "x-category": "Organizations", "x-display-name": "Get AI Usage"}, title="Get AI Usage")


class BDGetAuditLogsConfig(_OrgOp):
    operation: Literal["get_audit_logs"] = Field("get_audit_logs", json_schema_extra={"const": "get_audit_logs", "ui:hidden": True, "x-category": "Organizations", "x-display-name": "Get Audit Logs (Enterprise)"}, title="Get Audit Logs")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


# --- Dashboards ------------------------------------------------------------

class BDListDashboardsConfig(_OrgOp):
    operation: Literal["list_dashboards"] = Field("list_dashboards", json_schema_extra={"const": "list_dashboards", "ui:hidden": True, "x-category": "Dashboards", "x-display-name": "List Dashboards"}, title="List Dashboards")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetDashboardConfig(_OrgOp):
    operation: Literal["get_dashboard"] = Field("get_dashboard", json_schema_extra={"const": "get_dashboard", "ui:hidden": True, "x-category": "Dashboards", "x-display-name": "Get Dashboard"}, title="Get Dashboard")
    dashboard_id: str = _dyn_field("Dashboard", "dashboard_id", "Select dashboard…")


class BDCreateDashboardConfig(_OrgOp):
    operation: Literal["create_dashboard"] = Field("create_dashboard", json_schema_extra={"const": "create_dashboard", "x-creates-resource": True, "x-resource-type": "basedash_dashboard", "x-resource-id-path": "data.id", "ui:hidden": True, "x-category": "Dashboards", "x-display-name": "Create Dashboard"}, title="Create Dashboard")
    name: str = Field(..., title="Name")
    body_json: str = _json_field("Extra Fields (JSON)", 'Optional, e.g. {"description":"…","icon":"📊","color":"blue"}')


class BDUpdateDashboardConfig(_OrgOp):
    operation: Literal["update_dashboard"] = Field("update_dashboard", json_schema_extra={"const": "update_dashboard", "ui:hidden": True, "x-category": "Dashboards", "x-display-name": "Update Dashboard"}, title="Update Dashboard")
    dashboard_id: str = _dyn_field("Dashboard", "dashboard_id", "Select dashboard…")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"name":"Renamed","color":"green"}')


class BDDeleteDashboardConfig(_OrgOp):
    operation: Literal["delete_dashboard"] = Field("delete_dashboard", json_schema_extra={"const": "delete_dashboard", "ui:hidden": True, "x-category": "Dashboards", "x-display-name": "Delete Dashboard"}, title="Delete Dashboard")
    dashboard_id: str = _dyn_field("Dashboard", "dashboard_id", "Select dashboard…")


class BDListDashboardChartsConfig(_OrgOp):
    operation: Literal["list_dashboard_charts"] = Field("list_dashboard_charts", json_schema_extra={"const": "list_dashboard_charts", "ui:hidden": True, "x-category": "Dashboards", "x-display-name": "List Dashboard Charts"}, title="List Dashboard Charts")
    dashboard_id: str = _dyn_field("Dashboard", "dashboard_id", "Select dashboard…")


class BDCreateTabConfig(_OrgOp):
    operation: Literal["create_tab"] = Field("create_tab", json_schema_extra={"const": "create_tab", "ui:hidden": True, "x-category": "Dashboards", "x-display-name": "Create Tab"}, title="Create Tab")
    dashboard_id: str = _dyn_field("Dashboard", "dashboard_id", "Select dashboard…")
    name: str = Field(..., title="Tab Name")


class BDUpdateTabConfig(_OrgOp):
    operation: Literal["update_tab"] = Field("update_tab", json_schema_extra={"const": "update_tab", "ui:hidden": True, "x-category": "Dashboards", "x-display-name": "Update Tab"}, title="Update Tab")
    dashboard_id: str = _dyn_field("Dashboard", "dashboard_id", "Select dashboard…")
    tab_id: str = Field(..., title="Tab ID")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"name":"Overview","sortOrder":1}')


class BDDeleteTabConfig(_OrgOp):
    operation: Literal["delete_tab"] = Field("delete_tab", json_schema_extra={"const": "delete_tab", "ui:hidden": True, "x-category": "Dashboards", "x-display-name": "Delete Tab"}, title="Delete Tab")
    dashboard_id: str = _dyn_field("Dashboard", "dashboard_id", "Select dashboard…")
    tab_id: str = Field(..., title="Tab ID")


# --- Charts ----------------------------------------------------------------

_CHART_TYPES = ["TABLE", "LINE", "VERTICAL_BAR", "HORIZONTAL_BAR", "SCATTER", "FUNNEL", "NUMBER",
                "PROGRESS", "IMAGE", "RECORD", "TEXT", "PIE", "ACTIVITY", "MAP", "SANKEY",
                "DASHBOARD_HEADER", "DASHBOARD_TEXT"]


class BDCreateChartConfig(_OrgOp):
    operation: Literal["create_chart"] = Field("create_chart", json_schema_extra={"const": "create_chart", "ui:hidden": True, "x-category": "Charts", "x-display-name": "Create Chart"}, title="Create Chart")
    dashboard_id: str = _dyn_field("Dashboard", "dashboard_id", "Select dashboard…")
    name: str = Field(..., title="Name")
    chart_type: Optional[str] = Field("TABLE", title="Chart Type", json_schema_extra={"enum": _CHART_TYPES, "x-enum-searchable": True})
    sql_query: Optional[str] = Field(None, title="SQL Query", description="SQL powering the chart", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "sql"})
    database_connection_id: Optional[str] = _dyn_field("Data Source", "data_source_id", "Select data source…", required=False)
    body_json: str = _json_field("Extra Fields (JSON)", 'Optional, e.g. {"xAxisProperty":"day","yAxisProperty":"count","layout":{"x":0,"y":0,"width":6,"height":4}}')


class BDGetChartConfig(_OrgOp):
    operation: Literal["get_chart"] = Field("get_chart", json_schema_extra={"const": "get_chart", "ui:hidden": True, "x-category": "Charts", "x-display-name": "Get Chart"}, title="Get Chart")
    chart_id: str = Field(..., title="Chart ID")


class BDUpdateChartConfig(_OrgOp):
    operation: Literal["update_chart"] = Field("update_chart", json_schema_extra={"const": "update_chart", "ui:hidden": True, "x-category": "Charts", "x-display-name": "Update Chart"}, title="Update Chart")
    chart_id: str = Field(..., title="Chart ID")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"name":"Renamed","sqlQuery":"select 1"}')


class BDDeleteChartConfig(_OrgOp):
    operation: Literal["delete_chart"] = Field("delete_chart", json_schema_extra={"const": "delete_chart", "ui:hidden": True, "x-category": "Charts", "x-display-name": "Delete Chart"}, title="Delete Chart")
    chart_id: str = Field(..., title="Chart ID")


class BDGetChartImageConfig(_OrgOp):
    operation: Literal["get_chart_image"] = Field("get_chart_image", json_schema_extra={"const": "get_chart_image", "ui:hidden": True, "x-category": "Charts", "x-display-name": "Render Chart Image (PNG)"}, title="Render Chart Image")
    chart_id: str = Field(..., title="Chart ID")
    chart_version_id: Optional[str] = Field(None, title="Chart Version ID", description="Optional specific version to render")


# --- Chats (AI agent / text-to-SQL) ----------------------------------------

class BDListChatsConfig(_OrgOp):
    operation: Literal["list_chats"] = Field("list_chats", json_schema_extra={"const": "list_chats", "ui:hidden": True, "x-category": "AI Chats", "x-display-name": "List Chats"}, title="List Chats")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDCreateChatConfig(_OrgOp):
    operation: Literal["create_chat"] = Field("create_chat", json_schema_extra={"const": "create_chat", "ui:hidden": True, "x-category": "AI Chats", "x-display-name": "Start Chat"}, title="Start Chat")
    message: str = Field(..., title="Message", description="Prompt for the Basedash AI agent", json_schema_extra={"ui:widget": "textarea"})
    wait: Optional[str] = Field("true", title="Wait for Result", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes (synchronous)", "No (async, returns 202)"], "x-enum-searchable": True})
    body_json: str = _json_field("Extra Fields (JSON)", 'Optional, e.g. {"databaseConnectionId":"…"}')


class BDGetChatConfig(_OrgOp):
    operation: Literal["get_chat"] = Field("get_chat", json_schema_extra={"const": "get_chat", "ui:hidden": True, "x-category": "AI Chats", "x-display-name": "Get Chat"}, title="Get Chat")
    chat_id: str = Field(..., title="Chat ID")


class BDDeleteChatConfig(_OrgOp):
    operation: Literal["delete_chat"] = Field("delete_chat", json_schema_extra={"const": "delete_chat", "ui:hidden": True, "x-category": "AI Chats", "x-display-name": "Delete Chat"}, title="Delete Chat")
    chat_id: str = Field(..., title="Chat ID")


class BDListChatMessagesConfig(_OrgOp):
    operation: Literal["list_chat_messages"] = Field("list_chat_messages", json_schema_extra={"const": "list_chat_messages", "ui:hidden": True, "x-category": "AI Chats", "x-display-name": "List Chat Messages"}, title="List Chat Messages")
    chat_id: str = Field(..., title="Chat ID")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDSendChatMessageConfig(_OrgOp):
    operation: Literal["send_chat_message"] = Field("send_chat_message", json_schema_extra={"const": "send_chat_message", "ui:hidden": True, "x-category": "AI Chats", "x-display-name": "Send Chat Message"}, title="Send Chat Message")
    chat_id: str = Field(..., title="Chat ID")
    message: str = Field(..., title="Message", json_schema_extra={"ui:widget": "textarea"})
    wait: Optional[str] = Field("true", title="Wait for Result", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes (synchronous)", "No (async)"], "x-enum-searchable": True})


class BDGetChatMessageConfig(_OrgOp):
    operation: Literal["get_chat_message"] = Field("get_chat_message", json_schema_extra={"const": "get_chat_message", "ui:hidden": True, "x-category": "AI Chats", "x-display-name": "Get Chat Message"}, title="Get Chat Message")
    chat_id: str = Field(..., title="Chat ID")
    message_id: str = Field(..., title="Message ID")


class BDCancelChatMessageConfig(_OrgOp):
    operation: Literal["cancel_chat_message"] = Field("cancel_chat_message", json_schema_extra={"const": "cancel_chat_message", "ui:hidden": True, "x-category": "AI Chats", "x-display-name": "Cancel Chat Message"}, title="Cancel Chat Message")
    chat_id: str = Field(..., title="Chat ID")
    message_id: str = Field(..., title="Message ID")


# --- Automations -----------------------------------------------------------

class BDListAutomationsConfig(_OrgOp):
    operation: Literal["list_automations"] = Field("list_automations", json_schema_extra={"const": "list_automations", "ui:hidden": True, "x-category": "Automations", "x-display-name": "List Automations"}, title="List Automations")
    include_archived: Optional[str] = Field("false", title="Include Archived", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetAutomationConfig(_OrgOp):
    operation: Literal["get_automation"] = Field("get_automation", json_schema_extra={"const": "get_automation", "ui:hidden": True, "x-category": "Automations", "x-display-name": "Get Automation"}, title="Get Automation")
    automation_id: str = Field(..., title="Automation ID")


class BDCreateAutomationConfig(_OrgOp):
    operation: Literal["create_automation"] = Field("create_automation", json_schema_extra={"const": "create_automation", "ui:hidden": True, "x-category": "Automations", "x-display-name": "Create Automation"}, title="Create Automation")
    name: str = Field(..., title="Name")
    instructions: Optional[str] = Field(None, title="Instructions", json_schema_extra={"ui:widget": "textarea"})
    body_json: str = _json_field("Extra Fields (JSON)", 'Optional, e.g. {"trigger":{"type":"SCHEDULE","frequency":"DAILY","preferredHour":9},"notifications":{"emailRecipients":["a@b.com"]}}')


class BDUpdateAutomationConfig(_OrgOp):
    operation: Literal["update_automation"] = Field("update_automation", json_schema_extra={"const": "update_automation", "ui:hidden": True, "x-category": "Automations", "x-display-name": "Update Automation"}, title="Update Automation")
    automation_id: str = Field(..., title="Automation ID")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"active":false}')


class BDDeleteAutomationConfig(_OrgOp):
    operation: Literal["delete_automation"] = Field("delete_automation", json_schema_extra={"const": "delete_automation", "ui:hidden": True, "x-category": "Automations", "x-display-name": "Delete Automation"}, title="Delete Automation")
    automation_id: str = Field(..., title="Automation ID")


class BDListAutomationRunsConfig(_OrgOp):
    operation: Literal["list_automation_runs"] = Field("list_automation_runs", json_schema_extra={"const": "list_automation_runs", "ui:hidden": True, "x-category": "Automations", "x-display-name": "List Automation Runs"}, title="List Automation Runs")
    automation_id: str = Field(..., title="Automation ID")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDStartAutomationRunConfig(_OrgOp):
    operation: Literal["start_automation_run"] = Field("start_automation_run", json_schema_extra={"const": "start_automation_run", "ui:hidden": True, "x-category": "Automations", "x-display-name": "Start Automation Run"}, title="Start Automation Run")
    automation_id: str = Field(..., title="Automation ID")
    wait: Optional[str] = Field("false", title="Wait for Result", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes (synchronous)", "No (async)"], "x-enum-searchable": True})


class BDGetAutomationRunConfig(_OrgOp):
    operation: Literal["get_automation_run"] = Field("get_automation_run", json_schema_extra={"const": "get_automation_run", "ui:hidden": True, "x-category": "Automations", "x-display-name": "Get Automation Run"}, title="Get Automation Run")
    automation_id: str = Field(..., title="Automation ID")
    run_id: str = Field(..., title="Run ID")


# --- Data sources ----------------------------------------------------------

class BDListDataSourcesConfig(_OrgOp):
    operation: Literal["list_data_sources"] = Field("list_data_sources", json_schema_extra={"const": "list_data_sources", "ui:hidden": True, "x-category": "Data Sources", "x-display-name": "List Data Sources"}, title="List Data Sources")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetDataSourceConfig(_OrgOp):
    operation: Literal["get_data_source"] = Field("get_data_source", json_schema_extra={"const": "get_data_source", "ui:hidden": True, "x-category": "Data Sources", "x-display-name": "Get Data Source"}, title="Get Data Source")
    data_source_id: str = _dyn_field("Data Source", "data_source_id", "Select data source…")


class BDCreateDataSourceConfig(_OrgOp):
    operation: Literal["create_data_source"] = Field("create_data_source", json_schema_extra={"const": "create_data_source", "x-creates-resource": True, "x-resource-type": "basedash_data_source", "x-resource-id-path": "data.id", "ui:hidden": True, "x-category": "Data Sources", "x-display-name": "Create Data Source"}, title="Create Data Source")
    body_json: str = _json_field("Connection (JSON)", 'e.g. {"displayName":"Prod","dialect":"POSTGRES","host":"…","port":5432,"databaseName":"…","username":"…","password":"…"}')


class BDUpdateDataSourceConfig(_OrgOp):
    operation: Literal["update_data_source"] = Field("update_data_source", json_schema_extra={"const": "update_data_source", "ui:hidden": True, "x-category": "Data Sources", "x-display-name": "Update Data Source"}, title="Update Data Source")
    data_source_id: str = _dyn_field("Data Source", "data_source_id", "Select data source…")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"displayName":"Renamed"}')


class BDDeleteDataSourceConfig(_OrgOp):
    operation: Literal["delete_data_source"] = Field("delete_data_source", json_schema_extra={"const": "delete_data_source", "ui:hidden": True, "x-category": "Data Sources", "x-display-name": "Delete Data Source"}, title="Delete Data Source")
    data_source_id: str = _dyn_field("Data Source", "data_source_id", "Select data source…")


class BDVerifyDataSourceConfig(_OrgOp):
    operation: Literal["verify_data_source"] = Field("verify_data_source", json_schema_extra={"const": "verify_data_source", "ui:hidden": True, "x-category": "Data Sources", "x-display-name": "Verify Data Source"}, title="Verify Data Source")
    body_json: str = _json_field("Connection (JSON)", 'Connection details to test (same shape as Create)')


class BDGetDataSourceAccessConfig(_OrgOp):
    operation: Literal["get_data_source_access"] = Field("get_data_source_access", json_schema_extra={"const": "get_data_source_access", "ui:hidden": True, "x-category": "Data Sources", "x-display-name": "Get Data Source Access"}, title="Get Data Source Access")
    data_source_id: str = _dyn_field("Data Source", "data_source_id", "Select data source…")


class BDSetDataSourceAccessConfig(_OrgOp):
    operation: Literal["set_data_source_access"] = Field("set_data_source_access", json_schema_extra={"const": "set_data_source_access", "ui:hidden": True, "x-category": "Data Sources", "x-display-name": "Set Data Source Access"}, title="Set Data Source Access")
    data_source_id: str = _dyn_field("Data Source", "data_source_id", "Select data source…")
    body_json: str = _json_field("Access Policy (JSON)", 'e.g. {"mode":"everyone"} or {"mode":"restricted","groupIds":["…"]}')


# --- Definitions (saved SQL) -----------------------------------------------

class BDListDefinitionsConfig(_OrgOp):
    operation: Literal["list_definitions"] = Field("list_definitions", json_schema_extra={"const": "list_definitions", "ui:hidden": True, "x-category": "Definitions", "x-display-name": "List Definitions"}, title="List Definitions")
    database_connection_id: Optional[str] = _dyn_field("Data Source", "data_source_id", "Filter by data source…", required=False)
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetDefinitionConfig(_OrgOp):
    operation: Literal["get_definition"] = Field("get_definition", json_schema_extra={"const": "get_definition", "ui:hidden": True, "x-category": "Definitions", "x-display-name": "Get Definition"}, title="Get Definition")
    definition_id: str = Field(..., title="Definition ID")


class BDCreateDefinitionConfig(_OrgOp):
    operation: Literal["create_definition"] = Field("create_definition", json_schema_extra={"const": "create_definition", "ui:hidden": True, "x-category": "Definitions", "x-display-name": "Create Definition"}, title="Create Definition")
    name: str = Field(..., title="Name")
    sql_query: str = Field(..., title="SQL Query", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "sql"})
    database_connection_id: str = _dyn_field("Data Source", "data_source_id", "Select data source…")
    body_json: str = _json_field("Extra Fields (JSON)", 'Optional, e.g. {"description":"…","referenceName":"active_users"}')


class BDUpdateDefinitionConfig(_OrgOp):
    operation: Literal["update_definition"] = Field("update_definition", json_schema_extra={"const": "update_definition", "ui:hidden": True, "x-category": "Definitions", "x-display-name": "Update Definition"}, title="Update Definition")
    definition_id: str = Field(..., title="Definition ID")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"sqlQuery":"select 1"}')


class BDDeleteDefinitionConfig(_OrgOp):
    operation: Literal["delete_definition"] = Field("delete_definition", json_schema_extra={"const": "delete_definition", "ui:hidden": True, "x-category": "Definitions", "x-display-name": "Delete Definition"}, title="Delete Definition")
    definition_id: str = Field(..., title="Definition ID")


# --- Insights --------------------------------------------------------------

class BDListInsightsConfig(_OrgOp):
    operation: Literal["list_insights"] = Field("list_insights", json_schema_extra={"const": "list_insights", "ui:hidden": True, "x-category": "Insights", "x-display-name": "List Insights"}, title="List Insights")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetInsightConfig(_OrgOp):
    operation: Literal["get_insight"] = Field("get_insight", json_schema_extra={"const": "get_insight", "ui:hidden": True, "x-category": "Insights", "x-display-name": "Get Insight"}, title="Get Insight")
    insight_id: str = Field(..., title="Insight ID")


class BDCreateInsightConfig(_OrgOp):
    operation: Literal["create_insight"] = Field("create_insight", json_schema_extra={"const": "create_insight", "ui:hidden": True, "x-category": "Insights", "x-display-name": "Generate Insight"}, title="Generate Insight")
    body_json: str = _json_field("Body (JSON)", 'e.g. {"chartId":"…"} or {"title":"…","sqlQuery":"…","databaseConnectionId":"…"}')
    wait: Optional[str] = Field("false", title="Wait for Result", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes (synchronous)", "No (async)"], "x-enum-searchable": True})


class BDDeleteInsightConfig(_OrgOp):
    operation: Literal["delete_insight"] = Field("delete_insight", json_schema_extra={"const": "delete_insight", "ui:hidden": True, "x-category": "Insights", "x-display-name": "Delete Insight"}, title="Delete Insight")
    insight_id: str = Field(..., title="Insight ID")


# --- MCP servers -----------------------------------------------------------

class BDListMcpServersConfig(_OrgOp):
    operation: Literal["list_mcp_servers"] = Field("list_mcp_servers", json_schema_extra={"const": "list_mcp_servers", "ui:hidden": True, "x-category": "MCP Servers", "x-display-name": "List MCP Servers"}, title="List MCP Servers")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetMcpServerConfig(_OrgOp):
    operation: Literal["get_mcp_server"] = Field("get_mcp_server", json_schema_extra={"const": "get_mcp_server", "ui:hidden": True, "x-category": "MCP Servers", "x-display-name": "Get MCP Server"}, title="Get MCP Server")
    mcp_server_id: str = Field(..., title="MCP Server ID")


class BDCreateMcpServerConfig(_OrgOp):
    operation: Literal["create_mcp_server"] = Field("create_mcp_server", json_schema_extra={"const": "create_mcp_server", "ui:hidden": True, "x-category": "MCP Servers", "x-display-name": "Create MCP Server"}, title="Create MCP Server")
    body_json: str = _json_field("Body (JSON)", 'e.g. {"displayName":"My MCP","serverUrl":"https://…","transportType":"STREAMABLE_HTTP"}')


class BDUpdateMcpServerConfig(_OrgOp):
    operation: Literal["update_mcp_server"] = Field("update_mcp_server", json_schema_extra={"const": "update_mcp_server", "ui:hidden": True, "x-category": "MCP Servers", "x-display-name": "Update MCP Server"}, title="Update MCP Server")
    mcp_server_id: str = Field(..., title="MCP Server ID")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"displayName":"Renamed"}')


class BDDeleteMcpServerConfig(_OrgOp):
    operation: Literal["delete_mcp_server"] = Field("delete_mcp_server", json_schema_extra={"const": "delete_mcp_server", "ui:hidden": True, "x-category": "MCP Servers", "x-display-name": "Delete MCP Server"}, title="Delete MCP Server")
    mcp_server_id: str = Field(..., title="MCP Server ID")


# --- Members ---------------------------------------------------------------

class BDListMembersConfig(_OrgOp):
    operation: Literal["list_members"] = Field("list_members", json_schema_extra={"const": "list_members", "ui:hidden": True, "x-category": "Members", "x-display-name": "List Members"}, title="List Members")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetMemberConfig(_OrgOp):
    operation: Literal["get_member"] = Field("get_member", json_schema_extra={"const": "get_member", "ui:hidden": True, "x-category": "Members", "x-display-name": "Get Member"}, title="Get Member")
    member_id: str = Field(..., title="Member ID")


class BDInviteMemberConfig(_OrgOp):
    operation: Literal["invite_member"] = Field("invite_member", json_schema_extra={"const": "invite_member", "ui:hidden": True, "x-category": "Members", "x-display-name": "Invite Member"}, title="Invite Member")
    email: str = Field(..., title="Email")
    role: Optional[str] = Field("MEMBER", title="Role", json_schema_extra={"enum": ["ADMIN", "MEMBER"], "x-enum-searchable": True})


class BDUpdateMemberConfig(_OrgOp):
    operation: Literal["update_member"] = Field("update_member", json_schema_extra={"const": "update_member", "ui:hidden": True, "x-category": "Members", "x-display-name": "Update Member"}, title="Update Member")
    member_id: str = Field(..., title="Member ID")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"role":"ADMIN"}')


class BDDeactivateMemberConfig(_OrgOp):
    operation: Literal["deactivate_member"] = Field("deactivate_member", json_schema_extra={"const": "deactivate_member", "ui:hidden": True, "x-category": "Members", "x-display-name": "Deactivate Member"}, title="Deactivate Member")
    member_id: str = Field(..., title="Member ID")


# --- Groups ----------------------------------------------------------------

class BDListGroupsConfig(_OrgOp):
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"const": "list_groups", "ui:hidden": True, "x-category": "Groups", "x-display-name": "List Groups"}, title="List Groups")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetGroupConfig(_OrgOp):
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"const": "get_group", "ui:hidden": True, "x-category": "Groups", "x-display-name": "Get Group"}, title="Get Group")
    group_id: str = Field(..., title="Group ID")


class BDCreateGroupConfig(_OrgOp):
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"const": "create_group", "ui:hidden": True, "x-category": "Groups", "x-display-name": "Create Group"}, title="Create Group")
    name: str = Field(..., title="Name")


class BDUpdateGroupConfig(_OrgOp):
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"const": "update_group", "ui:hidden": True, "x-category": "Groups", "x-display-name": "Update Group"}, title="Update Group")
    group_id: str = Field(..., title="Group ID")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"name":"Renamed"}')


class BDDeleteGroupConfig(_OrgOp):
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"const": "delete_group", "ui:hidden": True, "x-category": "Groups", "x-display-name": "Delete Group"}, title="Delete Group")
    group_id: str = Field(..., title="Group ID")


class BDAddGroupMemberConfig(_OrgOp):
    operation: Literal["add_group_member"] = Field("add_group_member", json_schema_extra={"const": "add_group_member", "ui:hidden": True, "x-category": "Groups", "x-display-name": "Add Group Member"}, title="Add Group Member")
    group_id: str = Field(..., title="Group ID")
    body_json: str = _json_field("Body (JSON)", 'e.g. {"memberId":"…"} or {"email":"…"} (pending invite)')


# --- Skills ----------------------------------------------------------------

class BDListSkillsConfig(_OrgOp):
    operation: Literal["list_skills"] = Field("list_skills", json_schema_extra={"const": "list_skills", "ui:hidden": True, "x-category": "Skills", "x-display-name": "List Skills"}, title="List Skills")
    limit: Optional[str] = _limit_field()
    cursor: Optional[str] = _cursor_field()


class BDGetSkillConfig(_OrgOp):
    operation: Literal["get_skill"] = Field("get_skill", json_schema_extra={"const": "get_skill", "ui:hidden": True, "x-category": "Skills", "x-display-name": "Get Skill"}, title="Get Skill")
    skill_id: str = Field(..., title="Skill ID")


class BDCreateSkillConfig(_OrgOp):
    operation: Literal["create_skill"] = Field("create_skill", json_schema_extra={"const": "create_skill", "ui:hidden": True, "x-category": "Skills", "x-display-name": "Create Skill"}, title="Create Skill")
    body_json: str = _json_field("Body (JSON)", 'e.g. {"name":"…","instructions":"…"}')


class BDUpdateSkillConfig(_OrgOp):
    operation: Literal["update_skill"] = Field("update_skill", json_schema_extra={"const": "update_skill", "ui:hidden": True, "x-category": "Skills", "x-display-name": "Update Skill"}, title="Update Skill")
    skill_id: str = Field(..., title="Skill ID")
    body_json: str = _json_field("Fields (JSON)", 'e.g. {"name":"Renamed"}')


class BDDeleteSkillConfig(_OrgOp):
    operation: Literal["delete_skill"] = Field("delete_skill", json_schema_extra={"const": "delete_skill", "ui:hidden": True, "x-category": "Skills", "x-display-name": "Delete Skill"}, title="Delete Skill")
    skill_id: str = Field(..., title="Skill ID")


BasedashConfig = Annotated[
    Union[
        BDListOrganizationsConfig, BDGetOrganizationConfig, BDCreateOrganizationConfig,
        BDUpdateOrganizationConfig, BDGetAiUsageConfig, BDGetAuditLogsConfig,
        BDListDashboardsConfig, BDGetDashboardConfig, BDCreateDashboardConfig,
        BDUpdateDashboardConfig, BDDeleteDashboardConfig, BDListDashboardChartsConfig,
        BDCreateTabConfig, BDUpdateTabConfig, BDDeleteTabConfig,
        BDCreateChartConfig, BDGetChartConfig, BDUpdateChartConfig, BDDeleteChartConfig, BDGetChartImageConfig,
        BDListChatsConfig, BDCreateChatConfig, BDGetChatConfig, BDDeleteChatConfig,
        BDListChatMessagesConfig, BDSendChatMessageConfig, BDGetChatMessageConfig, BDCancelChatMessageConfig,
        BDListAutomationsConfig, BDGetAutomationConfig, BDCreateAutomationConfig,
        BDUpdateAutomationConfig, BDDeleteAutomationConfig, BDListAutomationRunsConfig,
        BDStartAutomationRunConfig, BDGetAutomationRunConfig,
        BDListDataSourcesConfig, BDGetDataSourceConfig, BDCreateDataSourceConfig,
        BDUpdateDataSourceConfig, BDDeleteDataSourceConfig, BDVerifyDataSourceConfig,
        BDGetDataSourceAccessConfig, BDSetDataSourceAccessConfig,
        BDListDefinitionsConfig, BDGetDefinitionConfig, BDCreateDefinitionConfig,
        BDUpdateDefinitionConfig, BDDeleteDefinitionConfig,
        BDListInsightsConfig, BDGetInsightConfig, BDCreateInsightConfig, BDDeleteInsightConfig,
        BDListMcpServersConfig, BDGetMcpServerConfig, BDCreateMcpServerConfig,
        BDUpdateMcpServerConfig, BDDeleteMcpServerConfig,
        BDListMembersConfig, BDGetMemberConfig, BDInviteMemberConfig, BDUpdateMemberConfig, BDDeactivateMemberConfig,
        BDListGroupsConfig, BDGetGroupConfig, BDCreateGroupConfig, BDUpdateGroupConfig,
        BDDeleteGroupConfig, BDAddGroupMemberConfig,
        BDListSkillsConfig, BDGetSkillConfig, BDCreateSkillConfig, BDUpdateSkillConfig, BDDeleteSkillConfig,
    ],
    Discriminator("operation"),
]


class BasedashNodeConfig(NodeConfig[BasedashConfig, BasedashApiKeyCredential]):
    """Full Basedash node configuration including credentials."""

    pass


# ============================================================================
# HTTP helper
# ============================================================================


def _extract_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            return err.get("detail") or err.get("title") or f"HTTP {resp.status_code}"
        if isinstance(err, str):
            return err
    except Exception:
        pass
    return f"HTTP {resp.status_code}: {resp.text[:300]}"


async def _bd_request(api_key: str, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                      json_body: Optional[Any] = None, action_name: str = "request",
                      raw: bool = False) -> Dict[str, Any]:
    """Call the Basedash public API and return a structured result.

    Unwraps the ``{data}`` / ``{error}`` envelope and surfaces ``pagination``.
    With ``raw=True`` returns the response bytes (for the PNG chart render).
    """
    url = f"{BASEDASH_API}{path}"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.request(method=method, url=url, headers=headers, params=params, json=json_body)
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timed out", "status_code": 408}
        except Exception as e:  # noqa: BLE001
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[BasedashNode] Request failed ({action_name}): {msg}")
            return {"status": "error", "action": action_name, "error": msg, "status_code": 500}

    api_ms = round((time.time() - start) * 1000, 2)
    if resp.status_code >= 400:
        message = _extract_error(resp)
        logger.error(f"[BasedashNode] API error ({action_name}): {message}")
        return {"status": "error", "action": action_name, "error": message,
                "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}

    if raw:
        return {"status": "success", "action": action_name, "content": resp.content,
                "content_type": resp.headers.get("content-type", "application/octet-stream"),
                "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}

    if resp.status_code == 204 or not resp.content:
        return {"status": "success", "action": action_name, "data": {"success": True},
                "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}

    try:
        body = resp.json()
    except Exception:
        return {"status": "success", "action": action_name, "data": {"raw": resp.text},
                "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}

    out: Dict[str, Any] = {"status": "success", "action": action_name,
                           "data": body.get("data") if isinstance(body, dict) and "data" in body else body,
                           "status_code": resp.status_code, "timing_ms": {"api_request": api_ms}}
    if isinstance(body, dict) and body.get("pagination") is not None:
        out["pagination"] = body["pagination"]
    return out


def _parse_json(raw: Optional[str], label: str) -> Dict[str, Any]:
    import json as _json
    if not raw or not raw.strip():
        return {}
    try:
        parsed = _json.loads(raw)
    except Exception as e:
        raise ValueError(f"{label} must be valid JSON: {e}")
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def _page_params(c) -> Dict[str, Any]:
    p: Dict[str, Any] = {}
    if getattr(c, "limit", None):
        p["limit"] = c.limit
    if getattr(c, "cursor", None):
        p["cursor"] = c.cursor
    return p


# ============================================================================
# Node
# ============================================================================


class BasedashNode(WorkflowNode):
    """Basedash BI/admin automation node (API key auth)."""

    @classmethod
    def get_config_model(cls):
        return BasedashNodeConfig

    # ---- Dynamic dropdowns -------------------------------------------------
    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None, page_token: Optional[str] = None, search: Optional[str] = None,
    ) -> Dict[str, Any]:
        api_key = (credential_data or {}).get("api_key")
        if not api_key:
            return {"options": []}
        ctx = context or {}
        org_id = ctx.get("organization_id")

        if field_name == "organization_id":
            items = await cls._list_all(api_key, "/organizations")
            return {"options": [{"value": it["id"], "label": it.get("name") or it["id"]} for it in items if it.get("id")]}

        if not org_id:
            return {"options": []}
        endpoints = {
            "dashboard_id": (f"/organizations/{org_id}/dashboards", "name"),
            "data_source_id": (f"/organizations/{org_id}/data-sources", "displayName"),
        }
        if field_name in endpoints:
            path, label_attr = endpoints[field_name]
            items = await cls._list_all(api_key, path)
            return {"options": [{"value": it["id"], "label": it.get(label_attr) or it["id"]} for it in items if it.get("id")]}
        return {"options": []}

    @classmethod
    async def _list_all(cls, api_key: str, path: str, max_items: int = 200) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        cursor = None
        for _ in range(10):
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            res = await _bd_request(api_key, "GET", path, params=params, action_name="load_options")
            if res.get("status") != "success":
                break
            data = res.get("data")
            if isinstance(data, list):
                items.extend([x for x in data if isinstance(x, dict)])
            pg = res.get("pagination") or {}
            cursor = pg.get("nextCursor")
            if not cursor or len(items) >= max_items:
                break
        return items

    # ---- Execute -----------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, BasedashNodeConfig):
            raise ValueError("Valid configuration is required")
        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add a Basedash API key.")
        api_key = credentials.api_key
        op = config.config

        handler = self._HANDLERS.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")
        result = await handler(self, op, api_key)
        if isinstance(result, dict):
            result.setdefault("timing_ms", {})
            result["timing_ms"]["total"] = round((time.time() - start_time) * 1000, 2)
        return result

    def _org_base(self, c) -> str:
        return f"/organizations/{c.organization_id}"

    # ---- Organizations -----------------------------------------------------
    async def _list_organizations(self, c, k):
        return await _bd_request(k, "GET", "/organizations", params=_page_params(c), action_name="list_organizations")

    async def _get_organization(self, c, k):
        return await _bd_request(k, "GET", self._org_base(c), action_name="get_organization")

    async def _create_organization(self, c, k):
        return await _bd_request(k, "POST", "/organizations", json_body={"name": c.name}, action_name="create_organization")

    async def _update_organization(self, c, k):
        return await _bd_request(k, "PATCH", self._org_base(c), json_body=_parse_json(c.body_json, "Fields"), action_name="update_organization")

    async def _get_ai_usage(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/ai-usage", action_name="get_ai_usage")

    async def _get_audit_logs(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/audit-logs", params=_page_params(c), action_name="get_audit_logs")

    # ---- Dashboards --------------------------------------------------------
    async def _list_dashboards(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/dashboards", params=_page_params(c), action_name="list_dashboards")

    async def _get_dashboard(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/dashboards/{c.dashboard_id}", action_name="get_dashboard")

    async def _create_dashboard(self, c, k):
        body = {"name": c.name, **_parse_json(c.body_json, "Extra Fields")}
        return await _bd_request(k, "POST", f"{self._org_base(c)}/dashboards", json_body=body, action_name="create_dashboard")

    async def _update_dashboard(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/dashboards/{c.dashboard_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_dashboard")

    async def _delete_dashboard(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/dashboards/{c.dashboard_id}", action_name="delete_dashboard")

    async def _list_dashboard_charts(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/dashboards/{c.dashboard_id}/charts", action_name="list_dashboard_charts")

    async def _create_tab(self, c, k):
        return await _bd_request(k, "POST", f"{self._org_base(c)}/dashboards/{c.dashboard_id}/tabs", json_body={"name": c.name}, action_name="create_tab")

    async def _update_tab(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/dashboards/{c.dashboard_id}/tabs/{c.tab_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_tab")

    async def _delete_tab(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/dashboards/{c.dashboard_id}/tabs/{c.tab_id}", action_name="delete_tab")

    # ---- Charts ------------------------------------------------------------
    async def _create_chart(self, c, k):
        body: Dict[str, Any] = {"dashboardId": c.dashboard_id, "name": c.name}
        if c.chart_type:
            body["chartType"] = c.chart_type
        if c.sql_query:
            body["sqlQuery"] = c.sql_query
        if c.database_connection_id:
            body["databaseConnectionId"] = c.database_connection_id
        body.update(_parse_json(c.body_json, "Extra Fields"))
        return await _bd_request(k, "POST", f"{self._org_base(c)}/charts", json_body=body, action_name="create_chart")

    async def _get_chart(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/charts/{c.chart_id}", action_name="get_chart")

    async def _update_chart(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/charts/{c.chart_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_chart")

    async def _delete_chart(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/charts/{c.chart_id}", action_name="delete_chart")

    async def _get_chart_image(self, c, k):
        params = {"chartVersionId": c.chart_version_id} if c.chart_version_id else None
        res = await _bd_request(k, "GET", f"{self._org_base(c)}/charts/{c.chart_id}/image", params=params, action_name="get_chart_image", raw=True)
        if res.get("status") != "success":
            return res
        return {"status": "success", "action": "get_chart_image",
                "data": BinaryOutput(data=res["content"], content_type=res.get("content_type", "image/png"), filename=f"chart-{c.chart_id}.png"),
                "timing_ms": res.get("timing_ms", {})}

    # ---- Chats -------------------------------------------------------------
    async def _list_chats(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/chats", params=_page_params(c), action_name="list_chats")

    async def _create_chat(self, c, k):
        body = {"message": c.message, **_parse_json(c.body_json, "Extra Fields")}
        params = {"wait": "true"} if c.wait == "true" else None
        return await _bd_request(k, "POST", f"{self._org_base(c)}/chats", params=params, json_body=body, action_name="create_chat")

    async def _get_chat(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/chats/{c.chat_id}", action_name="get_chat")

    async def _delete_chat(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/chats/{c.chat_id}", action_name="delete_chat")

    async def _list_chat_messages(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/chats/{c.chat_id}/messages", params=_page_params(c), action_name="list_chat_messages")

    async def _send_chat_message(self, c, k):
        params = {"wait": "true"} if c.wait == "true" else None
        return await _bd_request(k, "POST", f"{self._org_base(c)}/chats/{c.chat_id}/messages", params=params, json_body={"message": c.message}, action_name="send_chat_message")

    async def _get_chat_message(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/chats/{c.chat_id}/messages/{c.message_id}", action_name="get_chat_message")

    async def _cancel_chat_message(self, c, k):
        return await _bd_request(k, "POST", f"{self._org_base(c)}/chats/{c.chat_id}/messages/{c.message_id}/cancel", action_name="cancel_chat_message")

    # ---- Automations -------------------------------------------------------
    async def _list_automations(self, c, k):
        params = _page_params(c)
        if c.include_archived == "true":
            params["includeArchived"] = "true"
        return await _bd_request(k, "GET", f"{self._org_base(c)}/automations", params=params, action_name="list_automations")

    async def _get_automation(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/automations/{c.automation_id}", action_name="get_automation")

    async def _create_automation(self, c, k):
        body: Dict[str, Any] = {"name": c.name}
        if c.instructions:
            body["instructions"] = c.instructions
        body.update(_parse_json(c.body_json, "Extra Fields"))
        return await _bd_request(k, "POST", f"{self._org_base(c)}/automations", json_body=body, action_name="create_automation")

    async def _update_automation(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/automations/{c.automation_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_automation")

    async def _delete_automation(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/automations/{c.automation_id}", action_name="delete_automation")

    async def _list_automation_runs(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/automations/{c.automation_id}/runs", params=_page_params(c), action_name="list_automation_runs")

    async def _start_automation_run(self, c, k):
        params = {"wait": "true"} if c.wait == "true" else None
        return await _bd_request(k, "POST", f"{self._org_base(c)}/automations/{c.automation_id}/runs", params=params, json_body={}, action_name="start_automation_run")

    async def _get_automation_run(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/automations/{c.automation_id}/runs/{c.run_id}", action_name="get_automation_run")

    # ---- Data sources ------------------------------------------------------
    async def _list_data_sources(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/data-sources", params=_page_params(c), action_name="list_data_sources")

    async def _get_data_source(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/data-sources/{c.data_source_id}", action_name="get_data_source")

    async def _create_data_source(self, c, k):
        return await _bd_request(k, "POST", f"{self._org_base(c)}/data-sources", json_body=_parse_json(c.body_json, "Connection"), action_name="create_data_source")

    async def _update_data_source(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/data-sources/{c.data_source_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_data_source")

    async def _delete_data_source(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/data-sources/{c.data_source_id}", action_name="delete_data_source")

    async def _verify_data_source(self, c, k):
        return await _bd_request(k, "POST", f"{self._org_base(c)}/data-sources/verify", json_body=_parse_json(c.body_json, "Connection"), action_name="verify_data_source")

    async def _get_data_source_access(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/data-sources/{c.data_source_id}/access", action_name="get_data_source_access")

    async def _set_data_source_access(self, c, k):
        return await _bd_request(k, "PUT", f"{self._org_base(c)}/data-sources/{c.data_source_id}/access", json_body=_parse_json(c.body_json, "Access Policy"), action_name="set_data_source_access")

    # ---- Definitions -------------------------------------------------------
    async def _list_definitions(self, c, k):
        params = _page_params(c)
        if c.database_connection_id:
            params["databaseConnectionId"] = c.database_connection_id
        return await _bd_request(k, "GET", f"{self._org_base(c)}/definitions", params=params, action_name="list_definitions")

    async def _get_definition(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/definitions/{c.definition_id}", action_name="get_definition")

    async def _create_definition(self, c, k):
        body = {"name": c.name, "sqlQuery": c.sql_query, "databaseConnectionId": c.database_connection_id, **_parse_json(c.body_json, "Extra Fields")}
        return await _bd_request(k, "POST", f"{self._org_base(c)}/definitions", json_body=body, action_name="create_definition")

    async def _update_definition(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/definitions/{c.definition_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_definition")

    async def _delete_definition(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/definitions/{c.definition_id}", action_name="delete_definition")

    # ---- Insights ----------------------------------------------------------
    async def _list_insights(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/insights", params=_page_params(c), action_name="list_insights")

    async def _get_insight(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/insights/{c.insight_id}", action_name="get_insight")

    async def _create_insight(self, c, k):
        params = {"wait": "true"} if c.wait == "true" else None
        return await _bd_request(k, "POST", f"{self._org_base(c)}/insights", params=params, json_body=_parse_json(c.body_json, "Body"), action_name="create_insight")

    async def _delete_insight(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/insights/{c.insight_id}", action_name="delete_insight")

    # ---- MCP servers -------------------------------------------------------
    async def _list_mcp_servers(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/mcp-servers", params=_page_params(c), action_name="list_mcp_servers")

    async def _get_mcp_server(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/mcp-servers/{c.mcp_server_id}", action_name="get_mcp_server")

    async def _create_mcp_server(self, c, k):
        return await _bd_request(k, "POST", f"{self._org_base(c)}/mcp-servers", json_body=_parse_json(c.body_json, "Body"), action_name="create_mcp_server")

    async def _update_mcp_server(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/mcp-servers/{c.mcp_server_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_mcp_server")

    async def _delete_mcp_server(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/mcp-servers/{c.mcp_server_id}", action_name="delete_mcp_server")

    # ---- Members -----------------------------------------------------------
    async def _list_members(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/members", params=_page_params(c), action_name="list_members")

    async def _get_member(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/members/{c.member_id}", action_name="get_member")

    async def _invite_member(self, c, k):
        return await _bd_request(k, "POST", f"{self._org_base(c)}/members", json_body={"email": c.email, "role": c.role or "MEMBER"}, action_name="invite_member")

    async def _update_member(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/members/{c.member_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_member")

    async def _deactivate_member(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/members/{c.member_id}", action_name="deactivate_member")

    # ---- Groups ------------------------------------------------------------
    async def _list_groups(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/groups", params=_page_params(c), action_name="list_groups")

    async def _get_group(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/groups/{c.group_id}", action_name="get_group")

    async def _create_group(self, c, k):
        return await _bd_request(k, "POST", f"{self._org_base(c)}/groups", json_body={"name": c.name}, action_name="create_group")

    async def _update_group(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/groups/{c.group_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_group")

    async def _delete_group(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/groups/{c.group_id}", action_name="delete_group")

    async def _add_group_member(self, c, k):
        return await _bd_request(k, "POST", f"{self._org_base(c)}/groups/{c.group_id}/members", json_body=_parse_json(c.body_json, "Body"), action_name="add_group_member")

    # ---- Skills ------------------------------------------------------------
    async def _list_skills(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/skills", params=_page_params(c), action_name="list_skills")

    async def _get_skill(self, c, k):
        return await _bd_request(k, "GET", f"{self._org_base(c)}/skills/{c.skill_id}", action_name="get_skill")

    async def _create_skill(self, c, k):
        return await _bd_request(k, "POST", f"{self._org_base(c)}/skills", json_body=_parse_json(c.body_json, "Body"), action_name="create_skill")

    async def _update_skill(self, c, k):
        return await _bd_request(k, "PATCH", f"{self._org_base(c)}/skills/{c.skill_id}", json_body=_parse_json(c.body_json, "Fields"), action_name="update_skill")

    async def _delete_skill(self, c, k):
        return await _bd_request(k, "DELETE", f"{self._org_base(c)}/skills/{c.skill_id}", action_name="delete_skill")

    _HANDLERS = {
        "list_organizations": _list_organizations, "get_organization": _get_organization,
        "create_organization": _create_organization, "update_organization": _update_organization,
        "get_ai_usage": _get_ai_usage, "get_audit_logs": _get_audit_logs,
        "list_dashboards": _list_dashboards, "get_dashboard": _get_dashboard,
        "create_dashboard": _create_dashboard, "update_dashboard": _update_dashboard,
        "delete_dashboard": _delete_dashboard, "list_dashboard_charts": _list_dashboard_charts,
        "create_tab": _create_tab, "update_tab": _update_tab, "delete_tab": _delete_tab,
        "create_chart": _create_chart, "get_chart": _get_chart, "update_chart": _update_chart,
        "delete_chart": _delete_chart, "get_chart_image": _get_chart_image,
        "list_chats": _list_chats, "create_chat": _create_chat, "get_chat": _get_chat,
        "delete_chat": _delete_chat, "list_chat_messages": _list_chat_messages,
        "send_chat_message": _send_chat_message, "get_chat_message": _get_chat_message,
        "cancel_chat_message": _cancel_chat_message,
        "list_automations": _list_automations, "get_automation": _get_automation,
        "create_automation": _create_automation, "update_automation": _update_automation,
        "delete_automation": _delete_automation, "list_automation_runs": _list_automation_runs,
        "start_automation_run": _start_automation_run, "get_automation_run": _get_automation_run,
        "list_data_sources": _list_data_sources, "get_data_source": _get_data_source,
        "create_data_source": _create_data_source, "update_data_source": _update_data_source,
        "delete_data_source": _delete_data_source, "verify_data_source": _verify_data_source,
        "get_data_source_access": _get_data_source_access, "set_data_source_access": _set_data_source_access,
        "list_definitions": _list_definitions, "get_definition": _get_definition,
        "create_definition": _create_definition, "update_definition": _update_definition,
        "delete_definition": _delete_definition,
        "list_insights": _list_insights, "get_insight": _get_insight,
        "create_insight": _create_insight, "delete_insight": _delete_insight,
        "list_mcp_servers": _list_mcp_servers, "get_mcp_server": _get_mcp_server,
        "create_mcp_server": _create_mcp_server, "update_mcp_server": _update_mcp_server,
        "delete_mcp_server": _delete_mcp_server,
        "list_members": _list_members, "get_member": _get_member, "invite_member": _invite_member,
        "update_member": _update_member, "deactivate_member": _deactivate_member,
        "list_groups": _list_groups, "get_group": _get_group, "create_group": _create_group,
        "update_group": _update_group, "delete_group": _delete_group, "add_group_member": _add_group_member,
        "list_skills": _list_skills, "get_skill": _get_skill, "create_skill": _create_skill,
        "update_skill": _update_skill, "delete_skill": _delete_skill,
    }
