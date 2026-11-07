"""
Cursor automation node.

Provides workflow integration with the Cursor REST API (api.cursor.com) covering:
- Cloud Agents: create / list / get / archive / unarchive / delete agents;
  add follow-up runs; list / get / cancel runs; usage; artifacts; download
- Discovery: list models, list repositories, get API key info
- Admin (Team): members, audit logs, daily usage, spend, usage events,
  set spend limit, remove member
- Analytics: team agent-edits, tabs, DAU, models; per-user metric; AI-code
  commit + change metrics
- Webhook Trigger: fire when a cloud agent reaches FINISHED / ERROR

Authentication: API key (no OAuth). Cloud Agents endpoints accept a Bearer
token; Admin / Analytics / AI-Code endpoints use HTTP Basic with the key as the
username and an empty password. Both forms are accepted on api.cursor.com, so
this node sends a Bearer token for Cloud Agents (/v1) and HTTP Basic for the
unversioned Admin / Analytics endpoints.

API Base URL: https://api.cursor.com
Documentation: https://cursor.com/docs/api
"""

import base64
import hashlib
import hmac
import logging
import re
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from urllib.parse import urlsplit
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence

logger = logging.getLogger(__name__)

CURSOR_API_BASE = "https://api.cursor.com"

AGENT_TERMINAL_STATUSES = frozenset({"FINISHED", "ERROR"})


# ============================================================================
# Credential Schema
# ============================================================================


class CursorApiKeyCredential(BaseModel):
    """API Key credential for Cursor (Cloud Agents + Admin/Analytics)."""

    credential_type: Literal["cursor_api_key"] = Field(
        "cursor_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description=(
            "Use a user or service-account API key for Cloud Agents, or a team "
            "Admin API key for Admin, Analytics, and AI Code operations. "
            "Create the appropriate key in the Cursor Dashboard."
        ),
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Cursor API Key",
        json_schema_extra={"x-credential-url": "https://cursor.com/dashboard"}
    )


CursorCredential = CursorApiKeyCredential


# ============================================================================
# Cloud Agent Operation Configs
# ============================================================================


class CursorCreateAgentConfig(BaseModel):
    """Launch a Cursor cloud agent with an initial prompt and target repo."""

    operation: Literal["create_agent"] = Field(
        "create_agent",
        json_schema_extra={
            "const": "create_agent",
            "ui:hidden": True,
            "x-category": "Cloud Agents",
            "x-is-trigger": False,
            "x-display-name": "Create Cloud Agent",
        },
        title="Create Cloud Agent",
    )
    prompt_text: str = Field(
        ...,
        title="Prompt",
        description="Initial instruction for the cloud agent",
        json_schema_extra={"ui:widget": "textarea"},
    )
    repository: str = Field(
        ...,
        title="Repository URL",
        description="Connected repository URL (GitHub, GitLab, Bitbucket, or Azure DevOps)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "repository",
                "placeholder": "Select a repository...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a GitHub repo URL",
            }
        },
    )
    model: Optional[str] = Field(
        None,
        title="Model",
        description="Model to run the agent with (optional)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "model",
                "placeholder": "Select a model...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a model id",
            }
        },
    )
    branch: Optional[str] = Field(
        None, title="Branch", description="Starting branch/ref the agent bases its work on (optional)"
    )


class CursorListAgentsConfig(BaseModel):
    """List the authenticated user's cloud agents, newest first."""

    operation: Literal["list_agents"] = Field(
        "list_agents",
        json_schema_extra={
            "const": "list_agents",
            "ui:hidden": True,
            "x-category": "Cloud Agents",
            "x-is-trigger": False,
            "x-display-name": "List Cloud Agents",
        },
        title="List Cloud Agents",
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="nextCursor from the previous response")
    limit: int = Field(20, ge=1, le=100, title="Limit", description="Number of agents to return")


class CursorGetAgentConfig(BaseModel):
    """Fetch durable metadata / status for a specific cloud agent."""

    operation: Literal["get_agent"] = Field(
        "get_agent",
        json_schema_extra={
            "const": "get_agent",
            "ui:hidden": True,
            "x-category": "Cloud Agents",
            "x-is-trigger": False,
            "x-display-name": "Get Cloud Agent",
        },
        title="Get Cloud Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The ID of the cloud agent")


class CursorArchiveAgentConfig(BaseModel):
    """Archive a cloud agent (reversible; blocks new runs)."""

    operation: Literal["archive_agent"] = Field(
        "archive_agent",
        json_schema_extra={
            "const": "archive_agent",
            "ui:hidden": True,
            "x-category": "Cloud Agents",
            "x-is-trigger": False,
            "x-display-name": "Archive Cloud Agent",
        },
        title="Archive Cloud Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The ID of the cloud agent to archive")


class CursorUnarchiveAgentConfig(BaseModel):
    """Reactivate an archived cloud agent."""

    operation: Literal["unarchive_agent"] = Field(
        "unarchive_agent",
        json_schema_extra={
            "const": "unarchive_agent",
            "ui:hidden": True,
            "x-category": "Cloud Agents",
            "x-is-trigger": False,
            "x-display-name": "Unarchive Cloud Agent",
        },
        title="Unarchive Cloud Agent",
    )
    agent_id: str = Field(
        ..., title="Agent ID", description="The ID of the cloud agent to unarchive"
    )


class CursorDeleteAgentConfig(BaseModel):
    """Permanently delete a cloud agent (irreversible)."""

    operation: Literal["delete_agent"] = Field(
        "delete_agent",
        json_schema_extra={
            "const": "delete_agent",
            "ui:hidden": True,
            "x-category": "Cloud Agents",
            "x-is-trigger": False,
            "x-display-name": "Delete Cloud Agent",
        },
        title="Delete Cloud Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The ID of the cloud agent to delete")


class CursorAddRunConfig(BaseModel):
    """Send a follow-up prompt to an existing cloud agent."""

    operation: Literal["add_run"] = Field(
        "add_run",
        json_schema_extra={
            "const": "add_run",
            "ui:hidden": True,
            "x-category": "Runs",
            "x-is-trigger": False,
            "x-display-name": "Add Follow-up Run",
        },
        title="Add Follow-up Run",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to add a run to")
    prompt_text: str = Field(
        ...,
        title="Prompt",
        description="Follow-up instruction for the agent",
        json_schema_extra={"ui:widget": "textarea"},
    )


class CursorListRunsConfig(BaseModel):
    """List an agent's runs, newest first."""

    operation: Literal["list_runs"] = Field(
        "list_runs",
        json_schema_extra={
            "const": "list_runs",
            "ui:hidden": True,
            "x-category": "Runs",
            "x-is-trigger": False,
            "x-display-name": "List Runs",
        },
        title="List Runs",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent whose runs to list")
    cursor: Optional[str] = Field(None, title="Cursor", description="nextCursor from the previous response")
    limit: int = Field(20, ge=1, le=100, title="Limit", description="Number of runs to return")


class CursorGetRunConfig(BaseModel):
    """Get a run's status, timestamps, result, and git object."""

    operation: Literal["get_run"] = Field(
        "get_run",
        json_schema_extra={
            "const": "get_run",
            "ui:hidden": True,
            "x-category": "Runs",
            "x-is-trigger": False,
            "x-display-name": "Get Run",
        },
        title="Get Run",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent the run belongs to")
    run_id: str = Field(..., title="Run ID", description="The ID of the run")


class CursorCancelRunConfig(BaseModel):
    """Cancel an active run (terminal action)."""

    operation: Literal["cancel_run"] = Field(
        "cancel_run",
        json_schema_extra={
            "const": "cancel_run",
            "ui:hidden": True,
            "x-category": "Runs",
            "x-is-trigger": False,
            "x-display-name": "Cancel Run",
        },
        title="Cancel Run",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent the run belongs to")
    run_id: str = Field(..., title="Run ID", description="The ID of the run to cancel")


class CursorGetAgentUsageConfig(BaseModel):
    """Token usage breakdown for an agent (totalled and per run)."""

    operation: Literal["get_agent_usage"] = Field(
        "get_agent_usage",
        json_schema_extra={
            "const": "get_agent_usage",
            "ui:hidden": True,
            "x-category": "Cloud Agents",
            "x-is-trigger": False,
            "x-display-name": "Get Agent Usage",
        },
        title="Get Agent Usage",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to get usage for")


class CursorListArtifactsConfig(BaseModel):
    """List files / artifacts produced by an agent."""

    operation: Literal["list_artifacts"] = Field(
        "list_artifacts",
        json_schema_extra={
            "const": "list_artifacts",
            "ui:hidden": True,
            "x-category": "Cloud Agents",
            "x-is-trigger": False,
            "x-display-name": "List Artifacts",
        },
        title="List Artifacts",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent whose artifacts to list")


class CursorDownloadArtifactConfig(BaseModel):
    """Get a presigned download URL for an agent artifact (15-min expiry)."""

    operation: Literal["download_artifact"] = Field(
        "download_artifact",
        json_schema_extra={
            "const": "download_artifact",
            "ui:hidden": True,
            "x-category": "Cloud Agents",
            "x-is-trigger": False,
            "x-display-name": "Download Artifact",
        },
        title="Download Artifact",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent the artifact belongs to")
    path: str = Field(..., title="Artifact Path", description="Relative path from List Artifacts, under artifacts/")


class CursorListModelsConfig(BaseModel):
    """List models available to the API key with parameter definitions."""

    operation: Literal["list_models"] = Field(
        "list_models",
        json_schema_extra={
            "const": "list_models",
            "ui:hidden": True,
            "x-category": "Discovery",
            "x-is-trigger": False,
            "x-display-name": "List Models",
        },
        title="List Models",
    )


class CursorListRepositoriesConfig(BaseModel):
    """List GitHub repos accessible via Cursor's GitHub app."""

    operation: Literal["list_repositories"] = Field(
        "list_repositories",
        json_schema_extra={
            "const": "list_repositories",
            "ui:hidden": True,
            "x-category": "Discovery",
            "x-is-trigger": False,
            "x-display-name": "List Repositories",
        },
        title="List Repositories",
    )


class CursorGetMeConfig(BaseModel):
    """Info about the current API key (identity / scope)."""

    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={
            "const": "get_me",
            "ui:hidden": True,
            "x-category": "Discovery",
            "x-is-trigger": False,
            "x-display-name": "Get API Key Info",
        },
        title="Get API Key Info",
    )


# ============================================================================
# Admin (Team) Operation Configs — Basic auth, unversioned /teams endpoints
# ============================================================================


class CursorListTeamMembersConfig(BaseModel):
    """Retrieve all team members (Admin API key required)."""

    operation: Literal["list_team_members"] = Field(
        "list_team_members",
        json_schema_extra={
            "const": "list_team_members",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "List Team Members",
        },
        title="List Team Members",
    )


class CursorGetAuditLogsConfig(BaseModel):
    """Retrieve audit-log events with optional filters (Admin API key required)."""

    operation: Literal["get_audit_logs"] = Field(
        "get_audit_logs",
        json_schema_extra={
            "const": "get_audit_logs",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "Get Audit Logs",
        },
        title="Get Audit Logs",
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Filter events on or after this date (epoch ms or ISO)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Filter events on or before this date (epoch ms or ISO)"
    )
    search: Optional[str] = Field(
        None, title="Search", description="Free-text search across audit events"
    )


class CursorGetDailyUsageConfig(BaseModel):
    """Daily usage metrics for the team (Admin API key required)."""

    operation: Literal["get_daily_usage"] = Field(
        "get_daily_usage",
        json_schema_extra={
            "const": "get_daily_usage",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "Get Daily Usage",
        },
        title="Get Daily Usage",
    )
    start_date: str = Field(
        ..., title="Start Date", description="Start of the window (epoch milliseconds)"
    )
    end_date: str = Field(
        ..., title="End Date", description="End of the window (epoch milliseconds)"
    )


class CursorGetTeamSpendConfig(BaseModel):
    """Spending data for the current billing cycle (Admin API key required)."""

    operation: Literal["get_team_spend"] = Field(
        "get_team_spend",
        json_schema_extra={
            "const": "get_team_spend",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "Get Team Spend",
        },
        title="Get Team Spend",
    )
    search: Optional[str] = Field(
        None, title="Search", description="Filter spend rows by member name / email"
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field("50", title="Page Size", description="Rows per page")


class CursorGetUsageEventsConfig(BaseModel):
    """Detailed usage events with token counts and costs (Admin API key required)."""

    operation: Literal["get_usage_events"] = Field(
        "get_usage_events",
        json_schema_extra={
            "const": "get_usage_events",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "Get Usage Events",
        },
        title="Get Usage Events",
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Window start (epoch milliseconds)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Window end (epoch milliseconds)"
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field("50", title="Page Size", description="Events per page")


class CursorSetUserSpendLimitConfig(BaseModel):
    """Set a monthly spend limit for an individual member (Admin API key required)."""

    operation: Literal["set_user_spend_limit"] = Field(
        "set_user_spend_limit",
        json_schema_extra={
            "const": "set_user_spend_limit",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "Set User Spend Limit",
        },
        title="Set User Spend Limit",
    )
    user_email: str = Field(
        ..., title="Member Email", description="Email of the team member to limit"
    )
    spend_limit_dollars: str = Field(
        ..., title="Spend Limit (USD)", description="Monthly spend limit in US dollars"
    )


class CursorRemoveTeamMemberConfig(BaseModel):
    """Remove a member from the team (Admin API key required)."""

    operation: Literal["remove_team_member"] = Field(
        "remove_team_member",
        json_schema_extra={
            "const": "remove_team_member",
            "ui:hidden": True,
            "x-category": "Admin",
            "x-is-trigger": False,
            "x-display-name": "Remove Team Member",
        },
        title="Remove Team Member",
    )
    user_email: str = Field(
        ..., title="Member Email", description="Email of the team member to remove"
    )


# ============================================================================
# Analytics Operation Configs — Basic auth, unversioned /analytics endpoints
# ============================================================================


class CursorTeamAgentEditsConfig(BaseModel):
    """Team metrics on AI-suggested code edits accepted (Admin API key required)."""

    operation: Literal["team_agent_edits"] = Field(
        "team_agent_edits",
        json_schema_extra={
            "const": "team_agent_edits",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Team Agent-Edit Metrics",
        },
        title="Team Agent-Edit Metrics",
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Window start (epoch milliseconds)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Window end (epoch milliseconds)"
    )


class CursorTeamTabsConfig(BaseModel):
    """Autocomplete (Tab) suggestion acceptance metrics (Admin API key required)."""

    operation: Literal["team_tabs"] = Field(
        "team_tabs",
        json_schema_extra={
            "const": "team_tabs",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Team Tab Metrics",
        },
        title="Team Tab Metrics",
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Window start (epoch milliseconds)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Window end (epoch milliseconds)"
    )


class CursorTeamDauConfig(BaseModel):
    """Daily active user counts for the team (Admin API key required)."""

    operation: Literal["team_dau"] = Field(
        "team_dau",
        json_schema_extra={
            "const": "team_dau",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Team Daily Active Users",
        },
        title="Team Daily Active Users",
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Window start (epoch milliseconds)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Window end (epoch milliseconds)"
    )


class CursorTeamModelsConfig(BaseModel):
    """AI model usage metrics across the team (Admin API key required)."""

    operation: Literal["team_models"] = Field(
        "team_models",
        json_schema_extra={
            "const": "team_models",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Team Model Usage",
        },
        title="Team Model Usage",
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Window start (epoch milliseconds)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Window end (epoch milliseconds)"
    )


class CursorPerUserAnalyticsConfig(BaseModel):
    """Per-user analytics for a chosen metric (Admin API key required)."""

    operation: Literal["per_user_analytics"] = Field(
        "per_user_analytics",
        json_schema_extra={
            "const": "per_user_analytics",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Per-User Analytics",
        },
        title="Per-User Analytics",
    )
    metric: str = Field(
        "agent-edits",
        title="Metric",
        description="Which per-user metric to fetch",
        json_schema_extra={
            "enum": [
                "agent-edits",
                "tabs",
                "models",
                "mcp",
                "commands",
                "skills",
                "ask-mode",
            ],
            "x-enum-searchable": True,
        },
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field("50", title="Page Size", description="Rows per page")


class CursorAiCommitsConfig(BaseModel):
    """Per-commit attribution of lines to Tab / Composer / non-AI (Admin API key required)."""

    operation: Literal["ai_commits"] = Field(
        "ai_commits",
        json_schema_extra={
            "const": "ai_commits",
            "ui:hidden": True,
            "x-category": "AI Code",
            "x-is-trigger": False,
            "x-display-name": "AI Commit Metrics",
        },
        title="AI Commit Metrics",
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Window start (epoch milliseconds)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Window end (epoch milliseconds)"
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field("50", title="Page Size", description="Rows per page")


class CursorAiChangesConfig(BaseModel):
    """Accepted AI changes grouped by changeId with per-file metadata (Admin API key required)."""

    operation: Literal["ai_changes"] = Field(
        "ai_changes",
        json_schema_extra={
            "const": "ai_changes",
            "ui:hidden": True,
            "x-category": "AI Code",
            "x-is-trigger": False,
            "x-display-name": "AI Change Metrics",
        },
        title="AI Change Metrics",
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Window start (epoch milliseconds)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="Window end (epoch milliseconds)"
    )
    page: Optional[str] = Field("1", title="Page", description="Page number (1-based)")
    page_size: Optional[str] = Field("50", title="Page Size", description="Rows per page")


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class CursorAgentStatusTriggerConfig(BaseModel):
    """Receive legacy v0 statusChange webhooks for FINISHED or ERROR agents."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_agent_status_change"] = Field(
        "on_agent_status_change",
        json_schema_extra={
            "const": "on_agent_status_change",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Agent Status Change",
        },
        title="On Agent Status Change",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Use this URL when creating an agent with Cursor's legacy v0 webhook API. The v1 Cloud Agents API does not yet support webhooks.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: str = Field(
        ...,
        min_length=32,
        title="Signing Secret",
        description="Set this same secret in the legacy v0 create-agent webhook.secret field (at least 32 characters). Unsigned deliveries are rejected.",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


CursorConfig = Annotated[
    Union[
        CursorCreateAgentConfig,
        CursorListAgentsConfig,
        CursorGetAgentConfig,
        CursorArchiveAgentConfig,
        CursorUnarchiveAgentConfig,
        CursorDeleteAgentConfig,
        CursorAddRunConfig,
        CursorListRunsConfig,
        CursorGetRunConfig,
        CursorCancelRunConfig,
        CursorGetAgentUsageConfig,
        CursorListArtifactsConfig,
        CursorDownloadArtifactConfig,
        CursorListModelsConfig,
        CursorListRepositoriesConfig,
        CursorGetMeConfig,
        CursorListTeamMembersConfig,
        CursorGetAuditLogsConfig,
        CursorGetDailyUsageConfig,
        CursorGetTeamSpendConfig,
        CursorGetUsageEventsConfig,
        CursorSetUserSpendLimitConfig,
        CursorRemoveTeamMemberConfig,
        CursorTeamAgentEditsConfig,
        CursorTeamTabsConfig,
        CursorTeamDauConfig,
        CursorTeamModelsConfig,
        CursorPerUserAnalyticsConfig,
        CursorAiCommitsConfig,
        CursorAiChangesConfig,
        CursorAgentStatusTriggerConfig,
    ],
    Discriminator("operation"),
]


class CursorNodeConfig(NodeConfig[CursorConfig, CursorCredential]):
    """Full configuration for the Cursor node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


def _basic_auth_header(api_key: str) -> str:
    """HTTP Basic with the key as username and an empty password (Cursor form)."""
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    return f"Basic {token}"


async def _cursor_request(
    api_key: str,
    method: str,
    endpoint: str,
    *,
    auth: str = "bearer",
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Cursor request and return a structured result.

    ``auth="bearer"`` for Cloud Agent operations; ``auth="basic"`` for the
    unversioned Admin / Analytics / AI-Code endpoints and API key info.
    """
    url = f"{CURSOR_API_BASE}{endpoint}"
    authorization = (
        f"Bearer {api_key}" if auth == "bearer" else _basic_auth_header(api_key)
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                # Provider bodies and transport exceptions can echo credentials,
                # request URLs, and prompt text. Keep user-visible errors stable.
                if response.status_code == 401:
                    message = "Cursor rejected the API key (HTTP 401)"
                elif response.status_code == 403:
                    message = "Cursor refused this operation for the API key (HTTP 403)"
                elif response.status_code == 429:
                    message = "Cursor rate limit reached (HTTP 429)"
                else:
                    message = f"Cursor API request failed (HTTP {response.status_code})"
                logger.warning("[CursorNode] %s failed with HTTP %s", action_name, response.status_code)
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
                except ValueError:
                    logger.warning("[CursorNode] %s returned non-JSON HTTP %s", action_name, response.status_code)
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": "Cursor returned a non-JSON response",
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": api_ms},
                    }
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
        except httpx.RequestError:
            logger.warning("[CursorNode] %s failed in transport", action_name)
            return {
                "status": "error",
                "action": action_name,
                "error": "Cursor network request failed",
                "status_code": 503,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class CursorNode(WorkflowNode):
    """Cursor automation node (Cloud Agents, Admin, Analytics)."""

    integration_type = "automation-cursor"

    edit_examples = [
        "Launch a Cursor cloud agent to fix a bug in my GitHub repo",
        "Send a follow-up prompt to an existing cloud agent",
        "List my cloud agents and check their run status",
        "Get the team's daily usage and spend for this billing cycle",
        "Trigger a workflow when a cloud agent finishes or errors",
    ]

    connection_evidence = ConnectionEvidence(
        # /v1/me identifies user, service-account, and team API keys. Listing
        # Cloud Agents here would reject a valid Admin-only key at save time.
        noun="API keys",
        identity_operation="get_me",
        identity_keys=("userEmail", "apiKeyName"),
    )

    @classmethod
    def get_config_model(cls):
        return CursorNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (repositories + models)
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
        if field_name not in ("repository", "model"):
            return {"options": []}
        api_key = (credential_data or {}).get("api_key")
        if not api_key:
            raise ValueError("Connect a Cursor API key to load options")

        if field_name == "repository":
            result = await _cursor_request(
                api_key, "GET", "/v1/repositories", action_name="list_repositories"
            )
            if result.get("status") != "success":
                raise ValueError(result.get("error") or "Cursor repositories could not be loaded")
            data = result.get("data") or {}
            repos = data.get("items") if isinstance(data, dict) else data
            if not isinstance(repos, list):
                raise ValueError("Cursor returned an unexpected repository list")
            options = []
            for repo in repos:
                if not isinstance(repo, dict):
                    continue
                url = repo.get("url") or repo.get("htmlUrl") or repo.get("cloneUrl")
                name = repo.get("fullName") or repo.get("name") or (urlsplit(url).path.strip("/") if url else None)
                if url:
                    options.append({"label": str(name), "value": str(url)})
            return {"options": options}

        # field_name == "model"
        result = await _cursor_request(
            api_key, "GET", "/v1/models", action_name="list_models"
        )
        if result.get("status") != "success":
            raise ValueError(result.get("error") or "Cursor models could not be loaded")
        data = result.get("data") or {}
        models = data.get("items") if isinstance(data, dict) else data
        if not isinstance(models, list):
            raise ValueError("Cursor returned an unexpected model list")
        options = []
        for model in models:
            if isinstance(model, dict):
                mid = model.get("id") or model.get("name")
                label = model.get("displayName") or model.get("name") or mid
            else:
                mid = model
                label = model
            if mid:
                options.append({"label": str(label), "value": str(mid)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook receiver provisioning + signature verification
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the inbound webhook URL for the trigger operation.

        Legacy v0 agent creation accepts a webhook URL. This mints the NoClick
        URL to pass to that API; v1 has no webhook delivery yet.
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
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Cursor's HMAC-SHA256 X-Webhook-Signature header.

        Cursor sends ``X-Webhook-Signature: sha256=<hex>``. An unconfigured
        secret cannot authenticate a delivery.
        """
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        sent = headers.get("x-webhook-signature")
        if not isinstance(sent, str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", sent):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", sent)

    @classmethod
    def filter_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        return (
            isinstance(payload, dict)
            and payload.get("event") == "statusChange"
            and payload.get("status") in AGENT_TERMINAL_STATUSES
        )

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        return output.get("action") == "on_agent_status_change" and output.get("new_count") == 0

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, CursorNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, CursorAgentStatusTriggerConfig):
            valid_event = self.filter_trigger_payload(inputs, {})
            return {
                "status": "success",
                "action": "on_agent_status_change",
                "data": {**inputs, "webhook_url": op.webhook_url} if valid_event else {},
                "new_count": int(valid_event),
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Cursor API key.")
        api_key = credentials.api_key

        handlers = {
            "create_agent": self._create_agent,
            "list_agents": self._list_agents,
            "get_agent": self._get_agent,
            "archive_agent": self._archive_agent,
            "unarchive_agent": self._unarchive_agent,
            "delete_agent": self._delete_agent,
            "add_run": self._add_run,
            "list_runs": self._list_runs,
            "get_run": self._get_run,
            "cancel_run": self._cancel_run,
            "get_agent_usage": self._get_agent_usage,
            "list_artifacts": self._list_artifacts,
            "download_artifact": self._download_artifact,
            "list_models": self._list_models,
            "list_repositories": self._list_repositories,
            "get_me": self._get_me,
            "list_team_members": self._list_team_members,
            "get_audit_logs": self._get_audit_logs,
            "get_daily_usage": self._get_daily_usage,
            "get_team_spend": self._get_team_spend,
            "get_usage_events": self._get_usage_events,
            "set_user_spend_limit": self._set_user_spend_limit,
            "remove_team_member": self._remove_team_member,
            "team_agent_edits": self._team_agent_edits,
            "team_tabs": self._team_tabs,
            "team_dau": self._team_dau,
            "team_models": self._team_models,
            "per_user_analytics": self._per_user_analytics,
            "ai_commits": self._ai_commits,
            "ai_changes": self._ai_changes,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Cloud Agent handlers (Bearer auth except API key info)
    # ------------------------------------------------------------------
    async def _create_agent(self, c: CursorCreateAgentConfig, api_key: str) -> Dict[str, Any]:
        repo: Dict[str, Any] = {"url": c.repository}
        if c.branch:
            repo["startingRef"] = c.branch
        body: Dict[str, Any] = {
            "prompt": {"text": c.prompt_text},
            "repos": [repo],
            "model": {"id": c.model} if c.model else None,
        }
        return await _cursor_request(
            api_key, "POST", "/v1/agents", json_body=body, action_name="create_agent"
        )

    async def _list_agents(self, c: CursorListAgentsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/v1/agents",
            params={"cursor": c.cursor, "limit": c.limit},
            action_name="list_agents",
        )

    async def _get_agent(self, c: CursorGetAgentConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", f"/v1/agents/{c.agent_id}", action_name="get_agent"
        )

    async def _archive_agent(self, c: CursorArchiveAgentConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "POST", f"/v1/agents/{c.agent_id}/archive", action_name="archive_agent"
        )

    async def _unarchive_agent(self, c: CursorUnarchiveAgentConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "POST", f"/v1/agents/{c.agent_id}/unarchive", action_name="unarchive_agent"
        )

    async def _delete_agent(self, c: CursorDeleteAgentConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "DELETE", f"/v1/agents/{c.agent_id}", action_name="delete_agent"
        )

    async def _add_run(self, c: CursorAddRunConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "POST", f"/v1/agents/{c.agent_id}/runs",
            json_body={"prompt": {"text": c.prompt_text}},
            action_name="add_run",
        )

    async def _list_runs(self, c: CursorListRunsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", f"/v1/agents/{c.agent_id}/runs",
            params={"cursor": c.cursor, "limit": c.limit},
            action_name="list_runs",
        )

    async def _get_run(self, c: CursorGetRunConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", f"/v1/agents/{c.agent_id}/runs/{c.run_id}", action_name="get_run"
        )

    async def _cancel_run(self, c: CursorCancelRunConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "POST", f"/v1/agents/{c.agent_id}/runs/{c.run_id}/cancel",
            action_name="cancel_run",
        )

    async def _get_agent_usage(self, c: CursorGetAgentUsageConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", f"/v1/agents/{c.agent_id}/usage", action_name="get_agent_usage"
        )

    async def _list_artifacts(self, c: CursorListArtifactsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", f"/v1/agents/{c.agent_id}/artifacts", action_name="list_artifacts"
        )

    async def _download_artifact(self, c: CursorDownloadArtifactConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", f"/v1/agents/{c.agent_id}/artifacts/download",
            params={"path": c.path}, action_name="download_artifact",
        )

    async def _list_models(self, c: CursorListModelsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(api_key, "GET", "/v1/models", action_name="list_models")

    async def _list_repositories(self, c: CursorListRepositoriesConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/v1/repositories", action_name="list_repositories"
        )

    async def _get_me(self, c: CursorGetMeConfig, api_key: str) -> Dict[str, Any]:
        # Basic is documented for v1 and for team Admin keys alike. The key
        # name is required to make the connect-time identity proof meaningful.
        result = await _cursor_request(
            api_key, "GET", "/v1/me", auth="basic", action_name="get_me"
        )
        if result.get("status") == "success":
            data = result.get("data")
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("apiKeyName"), str)
                or not data["apiKeyName"].strip()
            ):
                return {
                    "status": "error",
                    "action": "get_me",
                    "error": "Cursor returned an unexpected API key record",
                    "status_code": result.get("status_code"),
                }
        return result

    # ------------------------------------------------------------------
    # Admin (Team) handlers (Basic auth)
    # ------------------------------------------------------------------
    async def _list_team_members(self, c: CursorListTeamMembersConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/teams/members", auth="basic", action_name="list_team_members"
        )

    async def _get_audit_logs(self, c: CursorGetAuditLogsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/teams/audit-logs", auth="basic",
            params={"startTime": c.start_date, "endTime": c.end_date, "search": c.search},
            action_name="get_audit_logs",
        )

    async def _get_daily_usage(self, c: CursorGetDailyUsageConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "POST", "/teams/daily-usage-data", auth="basic",
            json_body={"startDate": int(c.start_date), "endDate": int(c.end_date)},
            action_name="get_daily_usage",
        )

    async def _get_team_spend(self, c: CursorGetTeamSpendConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "POST", "/teams/spend", auth="basic",
            json_body={
                "searchTerm": c.search,
                **{key: int(value) for key, value in {
                    "page": c.page, "pageSize": c.page_size,
                }.items() if value not in (None, "")},
            },
            action_name="get_team_spend",
        )

    async def _get_usage_events(self, c: CursorGetUsageEventsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "POST", "/teams/filtered-usage-events", auth="basic",
            json_body={key: int(value) for key, value in {
                "startDate": c.start_date,
                "endDate": c.end_date,
                "page": c.page,
                "pageSize": c.page_size,
            }.items() if value not in (None, "")},
            action_name="get_usage_events",
        )

    async def _set_user_spend_limit(self, c: CursorSetUserSpendLimitConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "POST", "/teams/user-spend-limit", auth="basic",
            json_body={"userEmail": c.user_email, "spendLimitDollars": int(c.spend_limit_dollars)},
            action_name="set_user_spend_limit",
        )

    async def _remove_team_member(self, c: CursorRemoveTeamMemberConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "POST", "/teams/remove-member", auth="basic",
            json_body={"email": c.user_email},
            action_name="remove_team_member",
        )

    # ------------------------------------------------------------------
    # Analytics handlers (Basic auth)
    # ------------------------------------------------------------------
    async def _team_agent_edits(self, c: CursorTeamAgentEditsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/analytics/team/agent-edits", auth="basic",
            params={"startDate": c.start_date, "endDate": c.end_date},
            action_name="team_agent_edits",
        )

    async def _team_tabs(self, c: CursorTeamTabsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/analytics/team/tabs", auth="basic",
            params={"startDate": c.start_date, "endDate": c.end_date},
            action_name="team_tabs",
        )

    async def _team_dau(self, c: CursorTeamDauConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/analytics/team/dau", auth="basic",
            params={"startDate": c.start_date, "endDate": c.end_date},
            action_name="team_dau",
        )

    async def _team_models(self, c: CursorTeamModelsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/analytics/team/models", auth="basic",
            params={"startDate": c.start_date, "endDate": c.end_date},
            action_name="team_models",
        )

    async def _per_user_analytics(self, c: CursorPerUserAnalyticsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", f"/analytics/by-user/{c.metric}", auth="basic",
            params={"page": c.page, "pageSize": c.page_size},
            action_name="per_user_analytics",
        )

    async def _ai_commits(self, c: CursorAiCommitsConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/analytics/ai-code/commits", auth="basic",
            params={
                "startDate": c.start_date,
                "endDate": c.end_date,
                "page": c.page,
                "pageSize": c.page_size,
            },
            action_name="ai_commits",
        )

    async def _ai_changes(self, c: CursorAiChangesConfig, api_key: str) -> Dict[str, Any]:
        return await _cursor_request(
            api_key, "GET", "/analytics/ai-code/changes", auth="basic",
            params={
                "startDate": c.start_date,
                "endDate": c.end_date,
                "page": c.page,
                "pageSize": c.page_size,
            },
            action_name="ai_changes",
        )
