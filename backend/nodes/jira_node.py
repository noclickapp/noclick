"""
Jira REST API automation node.

This node provides Jira operations in workflows via direct REST API calls.
Uses httpx for high-performance async HTTP requests.

Jira Cloud REST API v3:
- Authorization URL: https://auth.atlassian.com/authorize
- Token URL: https://auth.atlassian.com/oauth/token
- API Base: https://api.atlassian.com/ex/jira/{cloudId}/rest/api/3

API Reference: https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/
OAuth 2.0 (3LO): https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/
"""

import logging
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Union, Literal, List, Annotated

import httpx
from pydantic import BaseModel, Field, ConfigDict, Discriminator

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.watch_channels import (
    WatchChannelTriggerMixin,
    get_watch_channel,
    save_watch_channel,
    update_channel_subscription,
)
from nodes.scopes.jira import JIRA_REQUESTED_SCOPES, JIRA_SCOPES, RECONNECT_HINT
from utils.ssrf import (
    SSRFError,
    assert_exact_url_origin,
    guarded_async_client,
    normalize_provider_subdomain,
)

logger = logging.getLogger(__name__)

# Jira dynamic webhooks expire after 30 days; the renewal cron refreshes them.
_JIRA_WEBHOOK_TTL = timedelta(days=30)


# ============================================================================
# Jira webhook trigger helpers
# ============================================================================


def _jira_api_base_from_dict(credential: Dict[str, Any]) -> str:
    """Build the Jira REST API base URL from a decrypted credential dict."""
    if credential.get("credential_type") == "jira_oauth" or credential.get("cloud_id"):
        return (
            f"https://api.atlassian.com/ex/jira/{credential['cloud_id']}/rest/api/3"
        )
    tenant = normalize_provider_subdomain(
        credential.get("domain") or "",
        "atlassian.net",
        field_name="Jira domain",
    )
    return f"https://{tenant}.atlassian.net/rest/api/3"


def _jira_auth_headers_from_dict(credential: Dict[str, Any]) -> Dict[str, str]:
    """Build Jira auth headers from a decrypted credential dict."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if credential.get("credential_type") == "jira_oauth" or credential.get(
        "access_token"
    ):
        headers["Authorization"] = f"Bearer {credential['access_token']}"
    else:
        auth = f"{credential.get('email')}:{credential.get('api_token')}"
        headers["Authorization"] = (
            f"Basic {base64.b64encode(auth.encode()).decode()}"
        )
    return headers


# Match-all JQL for triggers with no filter/project. Jira dynamic webhooks
# reject an empty jqlFilter and allow only =, !=, IN, NOT IN, so `!=` a
# sentinel key that can never exist matches every issue.
_MATCH_ALL_JQL = 'issuekey != "NONCLICK-0"'


async def jira_register_webhook(
    api_base: str,
    headers: Dict[str, str],
    webhook_url: str,
    events: List[str],
    jql_filter: str,
) -> str:
    """Register a Jira dynamic webhook. Returns the created webhook id."""
    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(
            f"{api_base}/webhook",
            headers=headers,
            json={
                "url": webhook_url,
                "webhooks": [{"events": events, "jqlFilter": jql_filter}],
            },
        )
        response.raise_for_status()
        results = response.json().get("webhookRegistrationResult", [])
        if not results or "createdWebhookId" not in results[0]:
            errors = results[0].get("errors") if results else "unknown error"
            raise ValueError(f"Jira rejected the webhook registration: {errors}")
        return str(results[0]["createdWebhookId"])


async def jira_delete_webhook(
    api_base: str, headers: Dict[str, str], webhook_id: str
) -> None:
    """Delete a Jira dynamic webhook."""
    async with guarded_async_client(timeout=30.0) as client:
        response = await client.request(
            "DELETE",
            f"{api_base}/webhook",
            headers=headers,
            json={"webhookIds": [int(webhook_id)]},
        )
        if response.status_code not in (200, 202, 204, 404):
            response.raise_for_status()


async def jira_refresh_webhook(
    api_base: str, headers: Dict[str, str], webhook_id: str
) -> None:
    """Extend a Jira dynamic webhook's 30-day expiry."""
    async with guarded_async_client(timeout=30.0) as client:
        response = await client.put(
            f"{api_base}/webhook/refresh",
            headers=headers,
            json={"webhookIds": [int(webhook_id)]},
        )
        response.raise_for_status()


# ============================================================================
# Jira Credential Schemas
# ============================================================================

#: Derived from nodes/scopes/jira.py so the request cannot drift from what the
#: operations need. Add a scope by declaring it on an operation, not here.
JIRA_OAUTH_SCOPES = JIRA_REQUESTED_SCOPES


class JiraOAuthCredential(BaseModel):
    """OAuth 2.0 (3LO) credential for Jira Cloud.
    Tokens are obtained via OAuth flow, not entered manually.

    Register OAuth app at: https://developer.atlassian.com/console/myapps/
    """

    credential_type: Literal["jira_oauth"] = Field(
        "jira_oauth", json_schema_extra={"ui:hidden": True}
    )
    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "atlassian",
            "x-oauth-scopes": JIRA_OAUTH_SCOPES,
        }
    )

    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")  # ISO 8601
    cloud_id: str = Field(
        ..., title="Cloud ID", description="Atlassian Cloud ID for API requests"
    )
    email: Optional[str] = Field(None, title="Account Email")
    site_name: Optional[str] = Field(
        None, title="Site Name", description="Jira site name for display"
    )
    site_url: Optional[str] = Field(
        None, title="Site URL", description="Jira site URL for display"
    )
    scope: Optional[str] = Field(
        None,
        title="Granted Scopes",
        description="OAuth scopes currently granted to this Jira credential",
    )


class JiraAPITokenCredential(BaseModel):
    """API Token authentication for Jira Cloud.

    Get your API token at: https://id.atlassian.com/manage-profile/security/api-tokens
    """

    credential_type: Literal["jira_api_token"] = Field(
        "jira_api_token", json_schema_extra={"ui:hidden": True}
    )
    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://id.atlassian.com/manage-profile/security/api-tokens"
        }
    )

    email: str = Field(
        ...,
        title="Email",
        description="Email address associated with your Atlassian account",
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description="Your Atlassian API token",
        json_schema_extra={"ui:widget": "password"},
    )
    domain: str = Field(
        ...,
        title="Jira Domain",
        description="Your Jira Cloud domain (e.g., yourcompany.atlassian.net)",
        json_schema_extra={"placeholder": "yourcompany.atlassian.net"},
    )


# Union type - OAuth shown first in UI (better UX)
JiraCredential = Union[JiraOAuthCredential, JiraAPITokenCredential]


# ============================================================================
# Jira Configuration Models (One per action)
# ============================================================================

# --- Issue Operations ---


class JiraGetIssueConfig(BaseModel):
    """Get a specific issue by key or ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue"] = Field(
        default="get_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue",
        },
        title="Get Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123) or ID"
    )
    expand: Optional[str] = Field(
        default=None,
        title="Expand",
        description="Comma-separated list of fields to expand (e.g., changelog, renderedFields)",
    )


class JiraSearchIssuesConfig(BaseModel):
    """Search for issues using JQL"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_issues_with_jql"] = Field(
        default="search_issues_with_jql",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Search Issues with Jql",
        },
        title="Search Issues with Jql",
    )
    jql: str = Field(
        ...,
        title="JQL Query",
        description="Jira Query Language query (e.g., project = PROJ AND status = Open)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "project = PROJ AND status = Open",
        },
    )
    max_results: Optional[int] = Field(
        default=50,
        title="Max Results",
        description="Maximum number of issues to return (max 100)",
    )
    start_at: Optional[int] = Field(
        default=0, title="Start At", description="Index of the first result to return"
    )
    fields: Optional[str] = Field(
        default=None,
        title="Fields",
        description="Comma-separated list of fields to return (e.g., summary,status,assignee)",
    )


class JiraCreateIssueConfig(BaseModel):
    """Create a new issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_issue"] = Field(
        default="create_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Create Issue",
        },
        title="Create Issue",
    )
    project_key: str = Field(
        ..., title="Project Key", description="The project key (e.g., PROJ)"
    )
    issue_type: str = Field(
        ...,
        title="Issue Type",
        description="The issue type name (e.g., Bug, Task, Story)",
    )
    summary: str = Field(..., title="Summary", description="Issue summary/title")
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Issue description (supports Atlassian Document Format or plain text)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    priority: Optional[str] = Field(
        default=None,
        title="Priority",
        description="Priority name (e.g., High, Medium, Low)",
    )
    assignee: Optional[str] = Field(
        default=None, title="Assignee", description="Account ID of the assignee"
    )
    labels: Optional[List[str]] = Field(
        default=None, title="Labels", description="List of labels to add"
    )
    parent_key: Optional[str] = Field(
        default=None,
        title="Parent Key",
        description="Parent issue key for subtasks (e.g., PROJ-100)",
    )
    custom_fields: Optional[Dict[str, Any]] = Field(
        default=None,
        title="Custom Fields",
        description='Custom field values as JSON object (e.g., {"customfield_10001": "value"})',
    )


class JiraUpdateIssueConfig(BaseModel):
    """Update an existing issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_issue"] = Field(
        default="update_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Update Issue",
        },
        title="Update Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    summary: Optional[str] = Field(
        default=None, title="Summary", description="New issue summary"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New issue description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    priority: Optional[str] = Field(
        default=None, title="Priority", description="New priority name"
    )
    assignee: Optional[str] = Field(
        default=None,
        title="Assignee",
        description="Account ID of the new assignee (use '-1' to unassign)",
    )
    labels: Optional[List[str]] = Field(
        default=None,
        title="Labels",
        description="New list of labels (replaces existing)",
    )
    custom_fields: Optional[Dict[str, Any]] = Field(
        default=None, title="Custom Fields", description="Custom field values to update"
    )


class JiraTransitionIssueConfig(BaseModel):
    """Transition an issue to a new status"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["transition_issue_status"] = Field(
        default="transition_issue_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Transition Issue Status",
        },
        title="Transition Issue Status",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    transition_id: str = Field(
        ...,
        title="Transition ID",
        description="The ID of the transition to perform (use 'list_issue_transitions' to get available IDs)",
    )
    comment: Optional[str] = Field(
        default=None,
        title="Comment",
        description="Optional comment to add with the transition",
        json_schema_extra={"ui:widget": "textarea"},
    )
    resolution: Optional[str] = Field(
        default=None,
        title="Resolution",
        description="Resolution name (required for some transitions, e.g., 'Done', 'Won't Fix')",
    )


class JiraListTransitionsConfig(BaseModel):
    """List available transitions for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_transitions"] = Field(
        default="list_issue_transitions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Transitions",
        },
        title="List Issue Transitions",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


class JiraAddCommentConfig(BaseModel):
    """Add a comment to an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_comment_to_issue"] = Field(
        default="add_comment_to_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Add Comment to Issue",
        },
        title="Add Comment to Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    body: str = Field(
        ...,
        title="Comment Body",
        description="The comment content",
        json_schema_extra={"ui:widget": "textarea"},
    )


class JiraDeleteIssueConfig(BaseModel):
    """Delete an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue"] = Field(
        default="delete_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue",
        },
        title="Delete Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    delete_subtasks: bool = Field(
        default=False, title="Delete Subtasks", description="Whether to delete subtasks"
    )


# --- Project Operations ---


class JiraListProjectsConfig(BaseModel):
    """List accessible projects"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_projects"] = Field(
        default="list_projects",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Projects",
        },
        title="List Projects",
    )
    max_results: Optional[int] = Field(
        default=50,
        title="Max Results",
        description="Maximum number of projects to return",
    )
    start_at: Optional[int] = Field(
        default=0, title="Start At", description="Index of the first result to return"
    )


class JiraGetProjectConfig(BaseModel):
    """Get project details"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_project"] = Field(
        default="get_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Get Project",
        },
        title="Get Project",
    )
    project_key: str = Field(
        ..., title="Project Key", description="The project key (e.g., PROJ)"
    )


# --- User Operations ---


class JiraSearchUsersConfig(BaseModel):
    """Search for users"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_users"] = Field(
        default="search_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Search Users",
        },
        title="Search Users",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Query string to search users (name, email, or username)",
    )
    max_results: Optional[int] = Field(
        default=50, title="Max Results", description="Maximum number of users to return"
    )


class JiraGetMyselfConfig(BaseModel):
    """Get current user details"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_current_user"] = Field(
        default="get_current_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


# --- Attachment Operations ---


class JiraGetAttachmentMetadataConfig(BaseModel):
    """Get metadata for an attachment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_attachment_metadata"] = Field(
        default="get_attachment_metadata",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Attachment",
            "x-is-trigger": False,
            "x-display-name": "Get Attachment Metadata",
        },
        title="Get Attachment Metadata",
    )
    attachment_id: str = Field(
        ..., title="Attachment ID", description="The ID of the attachment"
    )


class JiraDownloadAttachmentConfig(BaseModel):
    """Download an attachment (returns a stored file reference)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["download_attachment"] = Field(
        default="download_attachment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Download Attachment",
        },
        title="Download Attachment",
    )
    attachment_url: str = Field(
        ...,
        title="Attachment URL",
        description="The content URL of the attachment (from attachment metadata)",
    )


class JiraDeleteAttachmentConfig(BaseModel):
    """Delete an attachment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_attachment"] = Field(
        default="delete_attachment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Attachment",
            "x-is-trigger": False,
            "x-display-name": "Delete Attachment",
        },
        title="Delete Attachment",
    )
    attachment_id: str = Field(
        ..., title="Attachment ID", description="The ID of the attachment to delete"
    )


class JiraAddAttachmentConfig(BaseModel):
    """Add attachment to an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_attachment_to_issue"] = Field(
        default="add_attachment_to_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Add Attachment to Issue",
        },
        title="Add Attachment to Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    file_content: str = Field(
        ...,
        title="File Content",
        description="The file to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload"},
    )
    filename: str = Field(
        ..., title="Filename", description="Name of the file to attach"
    )


class JiraGetAttachmentsForIssueConfig(BaseModel):
    """Get all attachments for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_attachments"] = Field(
        default="list_issue_attachments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Attachments",
        },
        title="List Issue Attachments",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


class JiraExpandAttachmentForHumansConfig(BaseModel):
    """Get attachment with expanded human-readable data"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_attachment_human_readable"] = Field(
        default="get_attachment_human_readable",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Attachment Human Readable",
        },
        title="Get Attachment Human Readable",
    )
    attachment_id: str = Field(
        ..., title="Attachment ID", description="The ID of the attachment"
    )


# --- Worklog Operations ---


class JiraAddWorklogConfig(BaseModel):
    """Add worklog to an issue (time tracking)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_worklog_to_issue"] = Field(
        default="add_worklog_to_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Add Worklog to Issue",
        },
        title="Add Worklog to Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    time_spent: str = Field(
        ...,
        title="Time Spent",
        description="Time spent in Jira format (e.g., '3h 30m', '2d', '1w 2d 3h')",
    )
    comment: Optional[str] = Field(
        default=None,
        title="Comment",
        description="Comment describing the work",
        json_schema_extra={"ui:widget": "textarea"},
    )
    started: Optional[str] = Field(
        default=None,
        title="Started",
        description="ISO 8601 datetime when work started (defaults to now)",
    )


class JiraGetWorklogConfig(BaseModel):
    """Get a specific worklog by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_worklog"] = Field(
        default="get_worklog",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Worklog",
        },
        title="Get Worklog",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    worklog_id: str = Field(
        ..., title="Worklog ID", description="The ID of the worklog"
    )


class JiraUpdateWorklogConfig(BaseModel):
    """Update an existing worklog"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_worklog"] = Field(
        default="update_worklog",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Update Worklog",
        },
        title="Update Worklog",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    worklog_id: str = Field(
        ..., title="Worklog ID", description="The ID of the worklog to update"
    )
    time_spent: Optional[str] = Field(
        default=None,
        title="Time Spent",
        description="Updated time spent in Jira format",
    )
    comment: Optional[str] = Field(
        default=None,
        title="Comment",
        description="Updated comment",
        json_schema_extra={"ui:widget": "textarea"},
    )
    started: Optional[str] = Field(
        default=None, title="Started", description="Updated start time (ISO 8601)"
    )


class JiraDeleteWorklogConfig(BaseModel):
    """Delete a worklog"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_worklog"] = Field(
        default="delete_worklog",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Worklog",
        },
        title="Delete Worklog",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    worklog_id: str = Field(
        ..., title="Worklog ID", description="The ID of the worklog to delete"
    )


class JiraGetIssueWorklogsConfig(BaseModel):
    """Get all worklogs for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_worklogs"] = Field(
        default="list_issue_worklogs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Worklogs",
        },
        title="List Issue Worklogs",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    max_results: Optional[int] = Field(
        default=1000,
        title="Max Results",
        description="Maximum number of worklogs to return",
    )


class JiraGetDeletedWorklogsConfig(BaseModel):
    """Get list of IDs for deleted worklogs"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_deleted_worklog_ids"] = Field(
        default="list_deleted_worklog_ids",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Worklog",
            "x-is-trigger": False,
            "x-display-name": "List Deleted Worklog Ids",
        },
        title="List Deleted Worklog Ids",
    )
    since: Optional[int] = Field(
        default=0,
        title="Since",
        description="Unix timestamp (milliseconds) to get deletions since",
    )


class JiraGetUpdatedWorklogsConfig(BaseModel):
    """Get list of IDs for updated worklogs"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_updated_worklog_ids"] = Field(
        default="list_updated_worklog_ids",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Worklog",
            "x-is-trigger": False,
            "x-display-name": "List Updated Worklog Ids",
        },
        title="List Updated Worklog Ids",
    )
    since: Optional[int] = Field(
        default=0,
        title="Since",
        description="Unix timestamp (milliseconds) to get updates since",
    )
    expand: Optional[str] = Field(
        default=None,
        title="Expand",
        description="Comma-separated fields to expand (e.g., 'properties')",
    )


class JiraGetWorklogPropertyKeysConfig(BaseModel):
    """Get all worklog property keys for a worklog"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_worklog_property_keys"] = Field(
        default="list_worklog_property_keys",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Worklog Property Keys",
        },
        title="List Worklog Property Keys",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    worklog_id: str = Field(
        ..., title="Worklog ID", description="The ID of the worklog"
    )


# --- Component Operations ---


class JiraCreateComponentConfig(BaseModel):
    """Create a project component"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_project_component"] = Field(
        default="create_project_component",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Component",
            "x-is-trigger": False,
            "x-display-name": "Create Project Component",
        },
        title="Create Project Component",
    )
    project_key: str = Field(
        ..., title="Project Key", description="The project key (e.g., PROJ)"
    )
    name: str = Field(..., title="Component Name", description="Name of the component")
    description: Optional[str] = Field(
        default=None, title="Description", description="Component description"
    )
    lead_account_id: Optional[str] = Field(
        default=None,
        title="Lead Account ID",
        description="Account ID of the component lead",
    )


class JiraGetComponentConfig(BaseModel):
    """Get a component by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_component"] = Field(
        default="get_component",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Component",
            "x-is-trigger": False,
            "x-display-name": "Get Component",
        },
        title="Get Component",
    )
    component_id: str = Field(
        ..., title="Component ID", description="The ID of the component"
    )


class JiraUpdateComponentConfig(BaseModel):
    """Update a component"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_component"] = Field(
        default="update_component",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Component",
            "x-is-trigger": False,
            "x-display-name": "Update Component",
        },
        title="Update Component",
    )
    component_id: str = Field(
        ..., title="Component ID", description="The ID of the component"
    )
    name: Optional[str] = Field(
        default=None, title="Component Name", description="New name of the component"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description"
    )
    lead_account_id: Optional[str] = Field(
        default=None,
        title="Lead Account ID",
        description="New component lead account ID",
    )


class JiraDeleteComponentConfig(BaseModel):
    """Delete a component"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_component"] = Field(
        default="delete_component",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Component",
            "x-is-trigger": False,
            "x-display-name": "Delete Component",
        },
        title="Delete Component",
    )
    component_id: str = Field(
        ..., title="Component ID", description="The ID of the component to delete"
    )


class JiraGetProjectComponentsConfig(BaseModel):
    """Get all components for a project"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_project_components"] = Field(
        default="list_project_components",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Project Components",
        },
        title="List Project Components",
    )
    project_key: str = Field(
        ..., title="Project Key", description="The project key (e.g., PROJ)"
    )


class JiraGetComponentRelatedIssuesConfig(BaseModel):
    """Get issue count for a component"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_component_issue_count"] = Field(
        default="get_component_issue_count",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Component",
            "x-is-trigger": False,
            "x-display-name": "Get Component Issue Count",
        },
        title="Get Component Issue Count",
    )
    component_id: str = Field(
        ..., title="Component ID", description="The ID of the component"
    )


# --- Version Operations ---


class JiraCreateVersionConfig(BaseModel):
    """Create a project version/release"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_project_version"] = Field(
        default="create_project_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Version",
            "x-is-trigger": False,
            "x-display-name": "Create Project Version",
        },
        title="Create Project Version",
    )
    project_key: str = Field(
        ..., title="Project Key", description="The project key (e.g., PROJ)"
    )
    name: str = Field(
        ...,
        title="Version Name",
        description="Name of the version (e.g., '1.0.0', 'Sprint 1')",
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Version description"
    )
    release_date: Optional[str] = Field(
        default=None, title="Release Date", description="Release date (YYYY-MM-DD)"
    )
    released: Optional[bool] = Field(
        default=False, title="Released", description="Whether the version is released"
    )
    archived: Optional[bool] = Field(
        default=False, title="Archived", description="Whether the version is archived"
    )


class JiraGetVersionConfig(BaseModel):
    """Get a version by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_version"] = Field(
        default="get_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Version",
            "x-is-trigger": False,
            "x-display-name": "Get Version",
        },
        title="Get Version",
    )
    version_id: str = Field(
        ..., title="Version ID", description="The ID of the version"
    )


class JiraUpdateVersionConfig(BaseModel):
    """Update a version"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_version"] = Field(
        default="update_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Version",
            "x-is-trigger": False,
            "x-display-name": "Update Version",
        },
        title="Update Version",
    )
    version_id: str = Field(
        ..., title="Version ID", description="The ID of the version"
    )
    name: Optional[str] = Field(
        default=None, title="Version Name", description="New version name"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description"
    )
    release_date: Optional[str] = Field(
        default=None, title="Release Date", description="New release date (YYYY-MM-DD)"
    )
    released: Optional[bool] = Field(
        default=None, title="Released", description="Whether the version is released"
    )
    archived: Optional[bool] = Field(
        default=None, title="Archived", description="Whether the version is archived"
    )


class JiraDeleteVersionConfig(BaseModel):
    """Delete a version"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_version"] = Field(
        default="delete_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Version",
            "x-is-trigger": False,
            "x-display-name": "Delete Version",
        },
        title="Delete Version",
    )
    version_id: str = Field(
        ..., title="Version ID", description="The ID of the version to delete"
    )


class JiraGetProjectVersionsConfig(BaseModel):
    """Get all versions for a project"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_project_versions"] = Field(
        default="list_project_versions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Project Versions",
        },
        title="List Project Versions",
    )
    project_key: str = Field(
        ..., title="Project Key", description="The project key (e.g., PROJ)"
    )


class JiraMergeVersionsConfig(BaseModel):
    """Merge two versions"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["merge_project_versions"] = Field(
        default="merge_project_versions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Version",
            "x-is-trigger": False,
            "x-display-name": "Merge Project Versions",
        },
        title="Merge Project Versions",
    )
    version_id: str = Field(
        ..., title="Version ID", description="The ID of the version to merge from"
    )
    move_to_version_id: str = Field(
        ...,
        title="Move To Version ID",
        description="The ID of the version to merge into",
    )


class JiraMoveVersionConfig(BaseModel):
    """Move version position"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["move_version_position"] = Field(
        default="move_version_position",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Version",
            "x-is-trigger": False,
            "x-display-name": "Move Version Position",
        },
        title="Move Version Position",
    )
    version_id: str = Field(
        ..., title="Version ID", description="The ID of the version to move"
    )
    position: Literal["Earlier", "Later", "First", "Last"] = Field(
        ..., title="Position", description="Where to move the version"
    )


class JiraGetVersionRelatedIssuesConfig(BaseModel):
    """Get issue counts for a version"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_version_issue_counts"] = Field(
        default="get_version_issue_counts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Version",
            "x-is-trigger": False,
            "x-display-name": "Get Version Issue Counts",
        },
        title="Get Version Issue Counts",
    )
    version_id: str = Field(
        ..., title="Version ID", description="The ID of the version"
    )


class JiraGetVersionUnresolvedIssuesConfig(BaseModel):
    """Get count of unresolved issues for a version"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_version_unresolved_count"] = Field(
        default="get_version_unresolved_count",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Version",
            "x-is-trigger": False,
            "x-display-name": "Get Version Unresolved Count",
        },
        title="Get Version Unresolved Count",
    )
    version_id: str = Field(
        ..., title="Version ID", description="The ID of the version"
    )


# --- Issue Link Operations ---


class JiraGetIssueLinkConfig(BaseModel):
    """Get an issue link by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_link"] = Field(
        default="get_issue_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Link",
        },
        title="Get Issue Link",
    )
    link_id: str = Field(..., title="Link ID", description="The ID of the issue link")


class JiraCreateIssueLinkConfig(BaseModel):
    """Create a link between two issues"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["link_two_issues"] = Field(
        default="link_two_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Link Two Issues",
        },
        title="Link Two Issues",
    )
    inward_issue_key: str = Field(
        ...,
        title="Inward Issue Key",
        description="The issue key for the inward side (e.g., PROJ-123)",
    )
    outward_issue_key: str = Field(
        ...,
        title="Outward Issue Key",
        description="The issue key for the outward side (e.g., PROJ-456)",
    )
    link_type: str = Field(
        ...,
        title="Link Type",
        description="Type of link (e.g., 'Blocks', 'Relates', 'Duplicates')",
    )


class JiraDeleteIssueLinkConfig(BaseModel):
    """Delete an issue link"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue_link"] = Field(
        default="delete_issue_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Link",
        },
        title="Delete Issue Link",
    )
    link_id: str = Field(
        ..., title="Link ID", description="The ID of the link to delete"
    )


# --- Watcher Operations ---


class JiraGetIssueWatchersConfig(BaseModel):
    """Get watchers for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_watchers"] = Field(
        default="list_issue_watchers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Watchers",
        },
        title="List Issue Watchers",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


class JiraAddWatcherConfig(BaseModel):
    """Add watcher to an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_watcher_to_issue"] = Field(
        default="add_watcher_to_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Add Watcher to Issue",
        },
        title="Add Watcher to Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    account_id: str = Field(
        ...,
        title="Account ID",
        description="The account ID of the user to add as watcher",
    )


class JiraRemoveWatcherConfig(BaseModel):
    """Remove watcher from an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_watcher_from_issue"] = Field(
        default="remove_watcher_from_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Remove Watcher from Issue",
        },
        title="Remove Watcher from Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    account_id: str = Field(
        ...,
        title="Account ID",
        description="The account ID of the user to remove as watcher",
    )


# --- Priority Operations ---


class JiraGetPrioritiesConfig(BaseModel):
    """Get all priorities"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_priorities"] = Field(
        default="list_priorities",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Priority",
            "x-is-trigger": False,
            "x-display-name": "List Priorities",
        },
        title="List Priorities",
    )


class JiraGetPriorityConfig(BaseModel):
    """Get a priority by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_priority"] = Field(
        default="get_priority",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Priority",
            "x-is-trigger": False,
            "x-display-name": "Get Priority",
        },
        title="Get Priority",
    )
    priority_id: str = Field(
        ..., title="Priority ID", description="The ID of the priority"
    )


# --- Resolution Operations ---


class JiraGetResolutionsConfig(BaseModel):
    """Get all resolutions"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_resolutions"] = Field(
        default="list_resolutions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Resolution",
            "x-is-trigger": False,
            "x-display-name": "List Resolutions",
        },
        title="List Resolutions",
    )


class JiraGetResolutionConfig(BaseModel):
    """Get a resolution by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_resolution"] = Field(
        default="get_resolution",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Resolution",
            "x-is-trigger": False,
            "x-display-name": "Get Resolution",
        },
        title="Get Resolution",
    )
    resolution_id: str = Field(
        ..., title="Resolution ID", description="The ID of the resolution"
    )


# --- Status Operations ---


class JiraGetStatusesConfig(BaseModel):
    """Get all statuses"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_statuses"] = Field(
        default="list_statuses",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Status",
            "x-is-trigger": False,
            "x-display-name": "List Statuses",
        },
        title="List Statuses",
    )


class JiraGetStatusConfig(BaseModel):
    """Get a status by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_status"] = Field(
        default="get_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Status",
            "x-is-trigger": False,
            "x-display-name": "Get Status",
        },
        title="Get Status",
    )
    status_id: str = Field(..., title="Status ID", description="The ID of the status")


# --- Issue Type Operations ---


class JiraGetIssueTypesConfig(BaseModel):
    """Get all issue types"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_types"] = Field(
        default="list_issue_types",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "List Issue Types",
        },
        title="List Issue Types",
    )


class JiraGetIssueTypeConfig(BaseModel):
    """Get an issue type by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_type"] = Field(
        default="get_issue_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Type",
        },
        title="Get Issue Type",
    )
    issue_type_id: str = Field(
        ..., title="Issue Type ID", description="The ID of the issue type"
    )


class JiraGetProjectIssueTypesConfig(BaseModel):
    """Get issue types for a project"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_project_issue_types"] = Field(
        default="list_project_issue_types",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Project Issue Types",
        },
        title="List Project Issue Types",
    )
    project_key: str = Field(
        ..., title="Project Key", description="The project key (e.g., PROJ)"
    )


# --- Filter Operations ---


class JiraCreateFilterConfig(BaseModel):
    """Create a filter (saved JQL query)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_jql_filter"] = Field(
        default="create_jql_filter",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Filter",
            "x-is-trigger": False,
            "x-display-name": "Create Jql Filter",
        },
        title="Create Jql Filter",
    )
    name: str = Field(..., title="Filter Name", description="Name of the filter")
    jql: str = Field(
        ...,
        title="JQL Query",
        description="The JQL query to save",
        json_schema_extra={"ui:widget": "textarea"},
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Filter description"
    )
    favourite: Optional[bool] = Field(
        default=False, title="Favourite", description="Mark as favourite"
    )


class JiraGetFilterConfig(BaseModel):
    """Get a filter by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_filter"] = Field(
        default="get_filter",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Filter",
            "x-is-trigger": False,
            "x-display-name": "Get Filter",
        },
        title="Get Filter",
    )
    filter_id: str = Field(..., title="Filter ID", description="The ID of the filter")


class JiraUpdateFilterConfig(BaseModel):
    """Update a filter"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_filter"] = Field(
        default="update_filter",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Filter",
            "x-is-trigger": False,
            "x-display-name": "Update Filter",
        },
        title="Update Filter",
    )
    filter_id: str = Field(..., title="Filter ID", description="The ID of the filter")
    name: Optional[str] = Field(
        default=None, title="Filter Name", description="New filter name"
    )
    jql: Optional[str] = Field(
        default=None,
        title="JQL Query",
        description="New JQL query",
        json_schema_extra={"ui:widget": "textarea"},
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description"
    )


class JiraDeleteFilterConfig(BaseModel):
    """Delete a filter"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_filter"] = Field(
        default="delete_filter",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Filter",
            "x-is-trigger": False,
            "x-display-name": "Delete Filter",
        },
        title="Delete Filter",
    )
    filter_id: str = Field(
        ..., title="Filter ID", description="The ID of the filter to delete"
    )


class JiraSearchFiltersConfig(BaseModel):
    """Search for filters"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_filters"] = Field(
        default="search_filters",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Filter",
            "x-is-trigger": False,
            "x-display-name": "Search Filters",
        },
        title="Search Filters",
    )
    filter_name: Optional[str] = Field(
        default=None, title="Filter Name", description="Filter name to search for"
    )
    max_results: Optional[int] = Field(
        default=50,
        title="Max Results",
        description="Maximum number of filters to return",
    )


# --- Comment Operations (additional) ---


class JiraGetCommentConfig(BaseModel):
    """Get a comment by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_comment"] = Field(
        default="get_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Comment",
        },
        title="Get Issue Comment",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment"
    )


class JiraGetIssueCommentsConfig(BaseModel):
    """Get all comments for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_comments"] = Field(
        default="list_issue_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Comments",
        },
        title="List Issue Comments",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


class JiraUpdateCommentConfig(BaseModel):
    """Update a comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_issue_comment"] = Field(
        default="update_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Update Issue Comment",
        },
        title="Update Issue Comment",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment to update"
    )
    body: str = Field(
        ...,
        title="Comment Body",
        description="The updated comment content",
        json_schema_extra={"ui:widget": "textarea"},
    )


class JiraDeleteCommentConfig(BaseModel):
    """Delete a comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue_comment"] = Field(
        default="delete_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Comment",
        },
        title="Delete Issue Comment",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment to delete"
    )


# --- Field Operations ---


class JiraGetFieldsConfig(BaseModel):
    """Get all fields"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_fields"] = Field(
        default="list_fields",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Field",
            "x-is-trigger": False,
            "x-display-name": "List Fields",
        },
        title="List Fields",
    )


class JiraCreateCustomFieldConfig(BaseModel):
    """Create a custom field"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_custom_field"] = Field(
        default="create_custom_field",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Field",
            "x-is-trigger": False,
            "x-display-name": "Create Custom Field",
        },
        title="Create Custom Field",
    )
    name: str = Field(..., title="Field Name", description="Name of the custom field")
    description: Optional[str] = Field(
        default=None, title="Description", description="Field description"
    )
    field_type: str = Field(
        ...,
        title="Field Type",
        description="Type of field (e.g., 'com.atlassian.jira.plugin.system.customfieldtypes:textfield')",
    )
    searcher_key: str = Field(
        ..., title="Searcher Key", description="Searcher key for the field"
    )


# --- Board Operations (Jira Software) ---


class JiraGetAllBoardsConfig(BaseModel):
    """Get all boards"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_boards"] = Field(
        default="list_boards",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Board",
            "x-is-trigger": False,
            "x-display-name": "List Boards",
        },
        title="List Boards",
    )
    max_results: Optional[int] = Field(
        default=50,
        title="Max Results",
        description="Maximum number of boards to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetBoardConfig(BaseModel):
    """Get a board by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_board"] = Field(
        default="get_board",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Board",
            "x-is-trigger": False,
            "x-display-name": "Get Board",
        },
        title="Get Board",
    )
    board_id: str = Field(..., title="Board ID", description="The ID of the board")


class JiraGetBoardIssuesConfig(BaseModel):
    """Get issues for a board"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_board_issues"] = Field(
        default="list_board_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Board",
            "x-is-trigger": False,
            "x-display-name": "List Board Issues",
        },
        title="List Board Issues",
    )
    board_id: str = Field(..., title="Board ID", description="The ID of the board")
    max_results: Optional[int] = Field(
        default=50,
        title="Max Results",
        description="Maximum number of issues to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )
    jql: Optional[str] = Field(
        default=None,
        title="JQL",
        description="Optional JQL filter for board issues",
        json_schema_extra={"ui:widget": "textarea"},
    )


class JiraGetBoardBacklogConfig(BaseModel):
    """Get backlog issues for a board"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_board_backlog"] = Field(
        default="get_board_backlog",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Board",
            "x-is-trigger": False,
            "x-display-name": "Get Board Backlog",
        },
        title="Get Board Backlog",
    )
    board_id: str = Field(..., title="Board ID", description="The ID of the board")
    max_results: Optional[int] = Field(
        default=50,
        title="Max Results",
        description="Maximum number of backlog issues to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetBoardSprintsConfig(BaseModel):
    """Get sprints for a board"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_board_sprints"] = Field(
        default="list_board_sprints",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sprint",
            "x-is-trigger": False,
            "x-display-name": "List Board Sprints",
        },
        title="List Board Sprints",
    )
    board_id: str = Field(..., title="Board ID", description="The ID of the board")
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of sprints to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )
    state: Optional[str] = Field(
        default=None,
        title="State",
        description="Filter by sprint state (active, future, closed)",
    )


# --- Sprint Operations (Jira Software) ---


class JiraGetSprintConfig(BaseModel):
    """Get a sprint by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_sprint"] = Field(
        default="get_sprint",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sprint",
            "x-is-trigger": False,
            "x-display-name": "Get Sprint",
        },
        title="Get Sprint",
    )
    sprint_id: str = Field(..., title="Sprint ID", description="The ID of the sprint")


class JiraCreateSprintConfig(BaseModel):
    """Create a sprint"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_sprint"] = Field(
        default="create_sprint",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sprint",
            "x-is-trigger": False,
            "x-display-name": "Create Sprint",
        },
        title="Create Sprint",
    )
    name: str = Field(..., title="Sprint Name", description="Name of the sprint")
    origin_board_id: str = Field(
        ..., title="Board ID", description="ID of the board for this sprint"
    )
    goal: Optional[str] = Field(default=None, title="Goal", description="Sprint goal")
    start_date: Optional[str] = Field(
        default=None, title="Start Date", description="Sprint start date (ISO 8601)"
    )
    end_date: Optional[str] = Field(
        default=None, title="End Date", description="Sprint end date (ISO 8601)"
    )


class JiraUpdateSprintConfig(BaseModel):
    """Update a sprint"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_sprint"] = Field(
        default="update_sprint",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sprint",
            "x-is-trigger": False,
            "x-display-name": "Update Sprint",
        },
        title="Update Sprint",
    )
    sprint_id: str = Field(..., title="Sprint ID", description="The ID of the sprint")
    name: Optional[str] = Field(
        default=None, title="Sprint Name", description="New sprint name"
    )
    state: Optional[Literal["active", "closed", "future"]] = Field(
        default=None, title="State", description="Sprint state"
    )
    goal: Optional[str] = Field(default=None, title="Goal", description="New sprint goal")
    start_date: Optional[str] = Field(
        default=None, title="Start Date", description="New start date (ISO 8601)"
    )
    end_date: Optional[str] = Field(
        default=None, title="End Date", description="New end date (ISO 8601)"
    )


class JiraDeleteSprintConfig(BaseModel):
    """Delete a sprint"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_sprint"] = Field(
        default="delete_sprint",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sprint",
            "x-is-trigger": False,
            "x-display-name": "Delete Sprint",
        },
        title="Delete Sprint",
    )
    sprint_id: str = Field(
        ..., title="Sprint ID", description="The ID of the sprint to delete"
    )


class JiraGetSprintIssuesConfig(BaseModel):
    """Get issues in a sprint"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_sprint_issues"] = Field(
        default="list_sprint_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Sprint",
            "x-is-trigger": False,
            "x-display-name": "List Sprint Issues",
        },
        title="List Sprint Issues",
    )
    sprint_id: str = Field(..., title="Sprint ID", description="The ID of the sprint")
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of issues to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )
    jql: Optional[str] = Field(
        default=None,
        title="JQL",
        description="Optional JQL filter for sprint issues",
        json_schema_extra={"ui:widget": "textarea"},
    )


class JiraMoveIssuesToSprintConfig(BaseModel):
    """Move issues to a sprint"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["move_issues_to_sprint"] = Field(
        default="move_issues_to_sprint",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Move Issues to Sprint",
        },
        title="Move Issues to Sprint",
    )
    sprint_id: str = Field(..., title="Sprint ID", description="The ID of the sprint")
    issue_keys: List[str] = Field(
        ..., title="Issue Keys", description="List of issue keys to move"
    )


# --- Epic Operations (Jira Software) ---


class JiraGetEpicConfig(BaseModel):
    """Get an epic by ID or key"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_epic"] = Field(
        default="get_epic",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Epic",
            "x-is-trigger": False,
            "x-display-name": "Get Epic",
        },
        title="Get Epic",
    )
    epic_id_or_key: str = Field(
        ..., title="Epic ID or Key", description="The ID or key of the epic"
    )


class JiraGetEpicIssuesConfig(BaseModel):
    """Get issues in an epic"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_epic_issues"] = Field(
        default="list_epic_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Epic",
            "x-is-trigger": False,
            "x-display-name": "List Epic Issues",
        },
        title="List Epic Issues",
    )
    epic_id_or_key: str = Field(
        ..., title="Epic ID or Key", description="The ID or key of the epic"
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of issues to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraMoveIssuesToEpicConfig(BaseModel):
    """Move issues to an epic"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["move_issues_to_epic"] = Field(
        default="move_issues_to_epic",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Move Issues to Epic",
        },
        title="Move Issues to Epic",
    )
    epic_id_or_key: str = Field(
        ..., title="Epic ID or Key", description="The ID or key of the epic"
    )
    issue_keys: List[str] = Field(
        ..., title="Issue Keys", description="List of issue keys to move"
    )


# --- Remote Link Operations ---


class JiraGetRemoteLinksConfig(BaseModel):
    """Get remote links for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_remote_links"] = Field(
        default="list_issue_remote_links",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Remote Links",
        },
        title="List Issue Remote Links",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


class JiraCreateRemoteLinkConfig(BaseModel):
    """Create a remote link on an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_remote_link_on_issue"] = Field(
        default="create_remote_link_on_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Create Remote Link on Issue",
        },
        title="Create Remote Link on Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    url: str = Field(..., title="URL", description="URL of the remote link")
    title: str = Field(..., title="Title", description="Title of the remote link")
    summary: Optional[str] = Field(
        default=None, title="Summary", description="Optional summary for the remote link"
    )


class JiraDeleteRemoteLinkConfig(BaseModel):
    """Delete a remote link"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_remote_link"] = Field(
        default="delete_remote_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Remote Link",
        },
        title="Delete Remote Link",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    link_id: str = Field(
        ..., title="Link ID", description="The ID of the remote link to delete"
    )


# --- Label Operations ---


class JiraGetLabelsConfig(BaseModel):
    """Get all labels for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_labels"] = Field(
        default="get_issue_labels",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Labels",
        },
        title="Get Issue Labels",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


class JiraAddLabelsConfig(BaseModel):
    """Add labels to an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_labels_to_issue"] = Field(
        default="add_labels_to_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Add Labels to Issue",
        },
        title="Add Labels to Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    labels: List[str] = Field(..., title="Labels", description="List of labels to add")


class JiraSetLabelsConfig(BaseModel):
    """Set labels for an issue (replaces existing)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["replace_issue_labels"] = Field(
        default="replace_issue_labels",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Replace Issue Labels",
        },
        title="Replace Issue Labels",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    labels: List[str] = Field(
        ..., title="Labels", description="List of labels to set (replaces existing)"
    )


# --- Issue Property Operations ---


class JiraGetIssuePropertyConfig(BaseModel):
    """Get a property value for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_property"] = Field(
        default="get_issue_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Property",
        },
        title="Get Issue Property",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    property_key: str = Field(
        ..., title="Property Key", description="The key of the property to retrieve"
    )


class JiraSetIssuePropertyConfig(BaseModel):
    """Set a property value for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_issue_property"] = Field(
        default="set_issue_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Set Issue Property",
        },
        title="Set Issue Property",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    property_key: str = Field(
        ..., title="Property Key", description="The key of the property to set"
    )
    property_value: Dict[str, Any] = Field(
        ..., title="Property Value", description="The JSON value to store"
    )


class JiraDeleteIssuePropertyConfig(BaseModel):
    """Delete a property from an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue_property"] = Field(
        default="delete_issue_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Property",
        },
        title="Delete Issue Property",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    property_key: str = Field(
        ..., title="Property Key", description="The key of the property to delete"
    )


class JiraGetIssuePropertyKeysConfig(BaseModel):
    """Get all property keys for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_property_keys"] = Field(
        default="list_issue_property_keys",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Property Keys",
        },
        title="List Issue Property Keys",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


# --- Permission Operations ---


class JiraGetMyPermissionsConfig(BaseModel):
    """Get permissions for the current user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_current_user_permissions"] = Field(
        default="get_current_user_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Current User Permissions",
        },
        title="Get Current User Permissions",
    )
    permissions: str = Field(
        ...,
        title="Permissions",
        description="Comma-separated list of permission keys to check (e.g. BROWSE_PROJECTS,CREATE_ISSUES)",
    )
    project_key: Optional[str] = Field(
        default=None,
        title="Project Key",
        description="Project key to check permissions for (optional)",
    )
    issue_key: Optional[str] = Field(
        default=None,
        title="Issue Key",
        description="Issue key to check permissions for (optional)",
    )


class JiraGetAllPermissionsConfig(BaseModel):
    """Get all permissions in the system"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_all_permissions"] = Field(
        default="list_all_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Permission",
            "x-is-trigger": False,
            "x-display-name": "List All Permissions",
        },
        title="List All Permissions",
    )


class JiraCheckPermissionsConfig(BaseModel):
    """Check if user has specific permissions"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["check_user_permissions"] = Field(
        default="check_user_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Permission",
            "x-is-trigger": False,
            "x-display-name": "Check User Permissions",
        },
        title="Check User Permissions",
    )
    permissions: List[str] = Field(
        ..., title="Permissions", description="List of permission keys to check"
    )
    project_key: Optional[str] = Field(
        default=None,
        title="Project Key",
        description="Project key to check permissions for (optional)",
    )
    issue_key: Optional[str] = Field(
        default=None,
        title="Issue Key",
        description="Issue key to check permissions for (optional)",
    )


# --- Permission Scheme Operations ---


class JiraGetPermissionSchemesConfig(BaseModel):
    """Get all permission schemes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_permission_schemes"] = Field(
        default="list_permission_schemes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Permission Scheme",
            "x-is-trigger": False,
            "x-display-name": "List Permission Schemes",
        },
        title="List Permission Schemes",
    )


class JiraGetPermissionSchemeConfig(BaseModel):
    """Get a permission scheme by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_permission_scheme"] = Field(
        default="get_permission_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Permission Scheme",
            "x-is-trigger": False,
            "x-display-name": "Get Permission Scheme",
        },
        title="Get Permission Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the permission scheme"
    )


class JiraCreatePermissionSchemeConfig(BaseModel):
    """Create a new permission scheme"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_permission_scheme"] = Field(
        default="create_permission_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Permission Scheme",
            "x-is-trigger": False,
            "x-display-name": "Create Permission Scheme",
        },
        title="Create Permission Scheme",
    )
    name: str = Field(..., title="Name", description="Name of the permission scheme")
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Description of the permission scheme",
    )


class JiraDeletePermissionSchemeConfig(BaseModel):
    """Delete a permission scheme"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_permission_scheme"] = Field(
        default="delete_permission_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Permission Scheme",
            "x-is-trigger": False,
            "x-display-name": "Delete Permission Scheme",
        },
        title="Delete Permission Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the permission scheme to delete"
    )


# --- Group Operations ---


class JiraGetGroupsConfig(BaseModel):
    """Get all groups"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_groups"] = Field(
        default="list_groups",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Group",
            "x-is-trigger": False,
            "x-display-name": "List Groups",
        },
        title="List Groups",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of groups to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetGroupConfig(BaseModel):
    """Get a group by name"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_group"] = Field(
        default="get_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Group",
            "x-is-trigger": False,
            "x-display-name": "Get Group",
        },
        title="Get Group",
    )
    group_name: str = Field(..., title="Group Name", description="Name of the group")


class JiraCreateGroupConfig(BaseModel):
    """Create a new group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_group"] = Field(
        default="create_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Group",
            "x-is-trigger": False,
            "x-display-name": "Create Group",
        },
        title="Create Group",
    )
    name: str = Field(
        ..., title="Group Name", description="Name of the group to create"
    )


class JiraDeleteGroupConfig(BaseModel):
    """Delete a group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_group"] = Field(
        default="delete_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Group",
            "x-is-trigger": False,
            "x-display-name": "Delete Group",
        },
        title="Delete Group",
    )
    group_name: str = Field(
        ..., title="Group Name", description="Name of the group to delete"
    )


class JiraAddUserToGroupConfig(BaseModel):
    """Add a user to a group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_user_to_group"] = Field(
        default="add_user_to_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Group",
            "x-is-trigger": False,
            "x-display-name": "Add User to Group",
        },
        title="Add User to Group",
    )
    group_name: str = Field(..., title="Group Name", description="Name of the group")
    account_id: str = Field(
        ..., title="Account ID", description="Account ID of the user to add"
    )


class JiraRemoveUserFromGroupConfig(BaseModel):
    """Remove a user from a group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_user_from_group"] = Field(
        default="remove_user_from_group",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Group",
            "x-is-trigger": False,
            "x-display-name": "Remove User from Group",
        },
        title="Remove User from Group",
    )
    group_name: str = Field(..., title="Group Name", description="Name of the group")
    account_id: str = Field(
        ..., title="Account ID", description="Account ID of the user to remove"
    )


class JiraGetGroupMembersConfig(BaseModel):
    """Get members of a group"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_group_members"] = Field(
        default="list_group_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Group",
            "x-is-trigger": False,
            "x-display-name": "List Group Members",
        },
        title="List Group Members",
    )
    group_name: str = Field(..., title="Group Name", description="Name of the group")
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of members to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


# --- Project Role Operations ---


class JiraGetProjectRolesConfig(BaseModel):
    """Get all project roles for a project"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_project_roles"] = Field(
        default="list_project_roles",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Project Roles",
        },
        title="List Project Roles",
    )
    project_key: str = Field(..., title="Project Key", description="The project key")


class JiraGetProjectRoleConfig(BaseModel):
    """Get a specific project role"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_project_role"] = Field(
        default="get_project_role",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Get Project Role",
        },
        title="Get Project Role",
    )
    project_key: str = Field(..., title="Project Key", description="The project key")
    role_id: int = Field(..., title="Role ID", description="The ID of the role")


class JiraAddActorsToRoleConfig(BaseModel):
    """Add actors (users/groups) to a project role"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_actors_to_project_role"] = Field(
        default="add_actors_to_project_role",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Add Actors to Project Role",
        },
        title="Add Actors to Project Role",
    )
    project_key: str = Field(..., title="Project Key", description="The project key")
    role_id: int = Field(..., title="Role ID", description="The ID of the role")
    user_ids: Optional[List[str]] = Field(
        default=None, title="User IDs", description="List of user account IDs to add"
    )
    group_names: Optional[List[str]] = Field(
        default=None, title="Group Names", description="List of group names to add"
    )


class JiraRemoveActorsFromRoleConfig(BaseModel):
    """Remove actors from a project role"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_actors_from_project_role"] = Field(
        default="remove_actors_from_project_role",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Remove Actors from Project Role",
        },
        title="Remove Actors from Project Role",
    )
    project_key: str = Field(..., title="Project Key", description="The project key")
    role_id: int = Field(..., title="Role ID", description="The ID of the role")
    user_id: Optional[str] = Field(
        default=None, title="User ID", description="User account ID to remove"
    )
    group_name: Optional[str] = Field(
        default=None, title="Group Name", description="Group name to remove"
    )


# --- Screen Operations ---


class JiraGetScreensConfig(BaseModel):
    """Get all screens"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_screens"] = Field(
        default="list_screens",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Screen",
            "x-is-trigger": False,
            "x-display-name": "List Screens",
        },
        title="List Screens",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of screens to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetScreenConfig(BaseModel):
    """Get a screen by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_screen"] = Field(
        default="get_screen",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Screen",
            "x-is-trigger": False,
            "x-display-name": "Get Screen",
        },
        title="Get Screen",
    )
    screen_id: int = Field(..., title="Screen ID", description="The ID of the screen")


class JiraGetScreenTabsConfig(BaseModel):
    """Get all tabs for a screen"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_screen_tabs"] = Field(
        default="list_screen_tabs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Screen",
            "x-is-trigger": False,
            "x-display-name": "List Screen Tabs",
        },
        title="List Screen Tabs",
    )
    screen_id: int = Field(..., title="Screen ID", description="The ID of the screen")


class JiraGetScreenFieldsConfig(BaseModel):
    """Get all fields for a screen tab"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_screen_tab_fields"] = Field(
        default="list_screen_tab_fields",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Screen",
            "x-is-trigger": False,
            "x-display-name": "List Screen Tab Fields",
        },
        title="List Screen Tab Fields",
    )
    screen_id: int = Field(..., title="Screen ID", description="The ID of the screen")
    tab_id: int = Field(..., title="Tab ID", description="The ID of the screen tab")


# --- Issue Security Scheme Operations ---


class JiraGetIssueSecuritySchemesConfig(BaseModel):
    """Get all issue security schemes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_security_schemes"] = Field(
        default="list_issue_security_schemes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Security",
            "x-is-trigger": False,
            "x-display-name": "List Issue Security Schemes",
        },
        title="List Issue Security Schemes",
    )


class JiraGetIssueSecuritySchemeConfig(BaseModel):
    """Get an issue security scheme by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_security_scheme"] = Field(
        default="get_issue_security_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Security",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Security Scheme",
        },
        title="Get Issue Security Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the issue security scheme"
    )


# --- Notification Scheme Operations ---


class JiraGetNotificationSchemesConfig(BaseModel):
    """Get all notification schemes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_notification_schemes"] = Field(
        default="list_notification_schemes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Notification Scheme",
            "x-is-trigger": False,
            "x-display-name": "List Notification Schemes",
        },
        title="List Notification Schemes",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of schemes to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetNotificationSchemeConfig(BaseModel):
    """Get a notification scheme by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_notification_scheme"] = Field(
        default="get_notification_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Notification Scheme",
            "x-is-trigger": False,
            "x-display-name": "Get Notification Scheme",
        },
        title="Get Notification Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the notification scheme"
    )


# --- Workflow Operations ---


class JiraGetWorkflowsConfig(BaseModel):
    """Get all workflows"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workflows"] = Field(
        default="list_workflows",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "List Workflows",
        },
        title="List Workflows",
    )


class JiraGetWorkflowConfig(BaseModel):
    """Get a workflow by name"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_workflow"] = Field(
        default="get_workflow",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Get Workflow",
        },
        title="Get Workflow",
    )
    workflow_name: str = Field(
        ..., title="Workflow Name", description="Name of the workflow"
    )


class JiraGetWorkflowSchemesConfig(BaseModel):
    """Get all workflow schemes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workflow_schemes"] = Field(
        default="list_workflow_schemes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "List Workflow Schemes",
        },
        title="List Workflow Schemes",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of schemes to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetWorkflowSchemeConfig(BaseModel):
    """Get a workflow scheme by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_workflow_scheme"] = Field(
        default="get_workflow_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Get Workflow Scheme",
        },
        title="Get Workflow Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the workflow scheme"
    )


# --- Dashboard Operations ---


class JiraGetDashboardsConfig(BaseModel):
    """Get all dashboards"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_dashboards"] = Field(
        default="list_dashboards",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dashboard",
            "x-is-trigger": False,
            "x-display-name": "List Dashboards",
        },
        title="List Dashboards",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of dashboards to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetDashboardConfig(BaseModel):
    """Get a dashboard by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_dashboard"] = Field(
        default="get_dashboard",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dashboard",
            "x-is-trigger": False,
            "x-display-name": "Get Dashboard",
        },
        title="Get Dashboard",
    )
    dashboard_id: str = Field(
        ..., title="Dashboard ID", description="The ID of the dashboard"
    )


class JiraCreateDashboardConfig(BaseModel):
    """Create a new dashboard"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_dashboard"] = Field(
        default="create_dashboard",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dashboard",
            "x-is-trigger": False,
            "x-display-name": "Create Dashboard",
        },
        title="Create Dashboard",
    )
    name: str = Field(..., title="Name", description="Name of the dashboard")
    description: Optional[str] = Field(
        default=None, title="Description", description="Description of the dashboard"
    )


class JiraUpdateDashboardConfig(BaseModel):
    """Update a dashboard"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_dashboard"] = Field(
        default="update_dashboard",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dashboard",
            "x-is-trigger": False,
            "x-display-name": "Update Dashboard",
        },
        title="Update Dashboard",
    )
    dashboard_id: str = Field(
        ..., title="Dashboard ID", description="The ID of the dashboard"
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New name for the dashboard"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New description for the dashboard",
    )


class JiraDeleteDashboardConfig(BaseModel):
    """Delete a dashboard"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_dashboard"] = Field(
        default="delete_dashboard",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dashboard",
            "x-is-trigger": False,
            "x-display-name": "Delete Dashboard",
        },
        title="Delete Dashboard",
    )
    dashboard_id: str = Field(
        ..., title="Dashboard ID", description="The ID of the dashboard to delete"
    )


# --- Time Tracking Operations ---


class JiraGetWorklogConfig(BaseModel):
    """Get a worklog by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_worklog"] = Field(
        default="get_worklog",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Worklog",
        },
        title="Get Worklog",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    worklog_id: str = Field(
        ..., title="Worklog ID", description="The ID of the worklog"
    )


class JiraUpdateWorklogConfig(BaseModel):
    """Update a worklog"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_worklog"] = Field(
        default="update_worklog",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Update Worklog",
        },
        title="Update Worklog",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    worklog_id: str = Field(
        ..., title="Worklog ID", description="The ID of the worklog"
    )
    time_spent: Optional[str] = Field(
        default=None, title="Time Spent", description="Time spent (e.g., '3h 30m')"
    )
    comment: Optional[str] = Field(
        default=None, title="Comment", description="Comment for the worklog"
    )
    started: Optional[str] = Field(
        default=None, title="Started", description="Updated start time (ISO 8601)"
    )


# --- Audit Log Operations ---


class JiraGetAuditRecordsConfig(BaseModel):
    """Get audit log records"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_audit_log"] = Field(
        default="get_audit_log",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "System",
            "x-is-trigger": False,
            "x-display-name": "Get Audit Log",
        },
        title="Get Audit Log",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of records to return",
    )
    offset: Optional[int] = Field(
        default=None, title="Offset", description="Starting offset for pagination"
    )
    filter_text: Optional[str] = Field(
        default=None, title="Filter Text", description="Text to filter audit records"
    )


# --- Advanced Search Operations ---


class JiraSearchUsersConfig(BaseModel):
    """Search for users"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_users"] = Field(
        default="search_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Search Users",
        },
        title="Search Users",
    )
    query: str = Field(..., title="Query", description="Search query for users")
    max_results: int = Field(
        default=50, title="Max Results", description="Maximum number of users to return"
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraSearchProjectsConfig(BaseModel):
    """Search for projects"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_projects"] = Field(
        default="search_projects",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Search Projects",
        },
        title="Search Projects",
    )
    query: Optional[str] = Field(
        default=None, title="Query", description="Search query for projects"
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of projects to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetApplicationPropertyConfig(BaseModel):
    """Get an application property"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_application_property"] = Field(
        default="get_application_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "System",
            "x-is-trigger": False,
            "x-display-name": "Get Application Property",
        },
        title="Get Application Property",
    )
    key: str = Field(
        ..., title="Property Key", description="The key of the application property"
    )


class JiraGetServerInfoConfig(BaseModel):
    """Get Jira server information"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_jira_server_info"] = Field(
        default="get_jira_server_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "System",
            "x-is-trigger": False,
            "x-display-name": "Get Jira Server Info",
        },
        title="Get Jira Server Info",
    )


# --- Issue Link Type Operations ---


class JiraGetIssueLinkTypesConfig(BaseModel):
    """Get all issue link types"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_link_types"] = Field(
        default="list_issue_link_types",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Link Type",
            "x-is-trigger": False,
            "x-display-name": "List Issue Link Types",
        },
        title="List Issue Link Types",
    )


class JiraGetIssueLinkTypeConfig(BaseModel):
    """Get an issue link type by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_link_type"] = Field(
        default="get_issue_link_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Link Type",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Link Type",
        },
        title="Get Issue Link Type",
    )
    link_type_id: str = Field(
        ..., title="Link Type ID", description="The ID of the issue link type"
    )


class JiraCreateIssueLinkTypeConfig(BaseModel):
    """Create a new issue link type"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_issue_link_type"] = Field(
        default="create_issue_link_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Link Type",
            "x-is-trigger": False,
            "x-display-name": "Create Issue Link Type",
        },
        title="Create Issue Link Type",
    )
    name: str = Field(..., title="Name", description="Name of the link type")
    inward: str = Field(
        ..., title="Inward Description", description="Description of the inward link"
    )
    outward: str = Field(
        ..., title="Outward Description", description="Description of the outward link"
    )


class JiraUpdateIssueLinkTypeConfig(BaseModel):
    """Update an issue link type"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_issue_link_type"] = Field(
        default="update_issue_link_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Link Type",
            "x-is-trigger": False,
            "x-display-name": "Update Issue Link Type",
        },
        title="Update Issue Link Type",
    )
    link_type_id: str = Field(
        ..., title="Link Type ID", description="The ID of the issue link type"
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New name of the link type"
    )
    inward: Optional[str] = Field(
        default=None,
        title="Inward Description",
        description="New description of the inward link",
    )
    outward: Optional[str] = Field(
        default=None,
        title="Outward Description",
        description="New description of the outward link",
    )


class JiraDeleteIssueLinkTypeConfig(BaseModel):
    """Delete an issue link type"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue_link_type"] = Field(
        default="delete_issue_link_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Link Type",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Link Type",
        },
        title="Delete Issue Link Type",
    )
    link_type_id: str = Field(
        ..., title="Link Type ID", description="The ID of the issue link type to delete"
    )


# --- Field Configuration Operations ---


class JiraGetFieldConfigurationsConfig(BaseModel):
    """Get all field configurations"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_field_configurations"] = Field(
        default="list_field_configurations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Field",
            "x-is-trigger": False,
            "x-display-name": "List Field Configurations",
        },
        title="List Field Configurations",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of configurations to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetFieldConfigurationConfig(BaseModel):
    """Get a field configuration by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_field_configuration"] = Field(
        default="get_field_configuration",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Field",
            "x-is-trigger": False,
            "x-display-name": "Get Field Configuration",
        },
        title="Get Field Configuration",
    )
    configuration_id: int = Field(
        ..., title="Configuration ID", description="The ID of the field configuration"
    )


class JiraGetFieldConfigurationSchemesConfig(BaseModel):
    """Get all field configuration schemes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_field_configuration_schemes"] = Field(
        default="list_field_configuration_schemes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Field",
            "x-is-trigger": False,
            "x-display-name": "List Field Configuration Schemes",
        },
        title="List Field Configuration Schemes",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of schemes to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetFieldConfigurationSchemeConfig(BaseModel):
    """Get a field configuration scheme by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_field_configuration_scheme"] = Field(
        default="get_field_configuration_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Field",
            "x-is-trigger": False,
            "x-display-name": "Get Field Configuration Scheme",
        },
        title="Get Field Configuration Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the field configuration scheme"
    )


# --- Issue Type Scheme Operations ---


class JiraGetIssueTypeSchemesConfig(BaseModel):
    """Get all issue type schemes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_type_schemes"] = Field(
        default="list_issue_type_schemes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "List Issue Type Schemes",
        },
        title="List Issue Type Schemes",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of schemes to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetIssueTypeSchemeConfig(BaseModel):
    """Get an issue type scheme by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_type_scheme"] = Field(
        default="get_issue_type_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Type Scheme",
        },
        title="Get Issue Type Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the issue type scheme"
    )


class JiraCreateIssueTypeSchemeConfig(BaseModel):
    """Create an issue type scheme"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_issue_type_scheme"] = Field(
        default="create_issue_type_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Create Issue Type Scheme",
        },
        title="Create Issue Type Scheme",
    )
    name: str = Field(..., title="Name", description="Name of the issue type scheme")
    description: Optional[str] = Field(
        default=None, title="Description", description="Description of the scheme"
    )
    issue_type_ids: List[str] = Field(
        ...,
        title="Issue Type IDs",
        description="List of issue type IDs to include in the scheme",
    )


class JiraUpdateIssueTypeSchemeConfig(BaseModel):
    """Update an issue type scheme"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_issue_type_scheme"] = Field(
        default="update_issue_type_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Update Issue Type Scheme",
        },
        title="Update Issue Type Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the issue type scheme"
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New name of the scheme"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description of the scheme"
    )


class JiraDeleteIssueTypeSchemeConfig(BaseModel):
    """Delete an issue type scheme"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue_type_scheme"] = Field(
        default="delete_issue_type_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Type Scheme",
        },
        title="Delete Issue Type Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the issue type scheme to delete"
    )


# --- Issue Type Screen Scheme Operations ---


class JiraGetIssueTypeScreenSchemesConfig(BaseModel):
    """Get all issue type screen schemes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_type_screen_schemes"] = Field(
        default="list_issue_type_screen_schemes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "List Issue Type Screen Schemes",
        },
        title="List Issue Type Screen Schemes",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of schemes to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraGetIssueTypeScreenSchemeConfig(BaseModel):
    """Get an issue type screen scheme by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_type_screen_scheme"] = Field(
        default="get_issue_type_screen_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Type Screen Scheme",
        },
        title="Get Issue Type Screen Scheme",
    )
    scheme_id: str = Field(
        ..., title="Scheme ID", description="The ID of the issue type screen scheme"
    )


# --- Priority Scheme Operations ---


class JiraGetPrioritySchemeConfig(BaseModel):
    """Get a priority scheme by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_priority_scheme"] = Field(
        default="get_priority_scheme",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Priority",
            "x-is-trigger": False,
            "x-display-name": "Get Priority Scheme",
        },
        title="Get Priority Scheme",
    )
    scheme_id: int = Field(
        ..., title="Scheme ID", description="The ID of the priority scheme"
    )


class JiraGetPrioritySchemesConfig(BaseModel):
    """Get all priority schemes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_priority_schemes"] = Field(
        default="list_priority_schemes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Priority",
            "x-is-trigger": False,
            "x-display-name": "List Priority Schemes",
        },
        title="List Priority Schemes",
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of schemes to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


# --- Additional Project Operations ---


class JiraArchiveProjectConfig(BaseModel):
    """Archive a project"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["archive_project"] = Field(
        default="archive_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Archive Project",
        },
        title="Archive Project",
    )
    project_key: str = Field(
        ..., title="Project Key", description="The project key to archive"
    )


class JiraRestoreProjectConfig(BaseModel):
    """Restore an archived project"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["restore_archived_project"] = Field(
        default="restore_archived_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Restore Archived Project",
        },
        title="Restore Archived Project",
    )
    project_key: str = Field(
        ..., title="Project Key", description="The project key to restore"
    )


class JiraGetProjectCategoryConfig(BaseModel):
    """Get a project category by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_project_category"] = Field(
        default="get_project_category",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Get Project Category",
        },
        title="Get Project Category",
    )
    category_id: int = Field(
        ..., title="Category ID", description="The ID of the project category"
    )


class JiraGetAllProjectCategoriesConfig(BaseModel):
    """Get all project categories"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_project_categories"] = Field(
        default="list_project_categories",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Project Categories",
        },
        title="List Project Categories",
    )


class JiraCreateProjectCategoryConfig(BaseModel):
    """Create a project category"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_project_category"] = Field(
        default="create_project_category",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Create Project Category",
        },
        title="Create Project Category",
    )
    name: str = Field(..., title="Name", description="Name of the project category")
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Description of the project category",
    )


class JiraUpdateProjectCategoryConfig(BaseModel):
    """Update a project category"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_project_category"] = Field(
        default="update_project_category",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Update Project Category",
        },
        title="Update Project Category",
    )
    category_id: int = Field(
        ..., title="Category ID", description="The ID of the project category"
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New name of the project category"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New description of the project category",
    )


class JiraDeleteProjectCategoryConfig(BaseModel):
    """Delete a project category"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_project_category"] = Field(
        default="delete_project_category",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Delete Project Category",
        },
        title="Delete Project Category",
    )
    category_id: int = Field(
        ..., title="Category ID", description="The ID of the project category to delete"
    )


# --- Additional Issue Operations ---


class JiraAssignIssueConfig(BaseModel):
    """Assign an issue to a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["assign_issue_to_user"] = Field(
        default="assign_issue_to_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Assign Issue to User",
        },
        title="Assign Issue to User",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    account_id: Optional[str] = Field(
        default=None,
        title="Account ID",
        description="Account ID of the user to assign (null for automatic assignment)",
    )


class JiraGetIssueChangelogConfig(BaseModel):
    """Get changelog for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_changelog"] = Field(
        default="get_issue_changelog",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Changelog",
        },
        title="Get Issue Changelog",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    max_results: int = Field(
        default=50,
        title="Max Results",
        description="Maximum number of changelog entries to return",
    )
    start_at: Optional[int] = Field(
        default=None, title="Start At", description="Starting index for pagination"
    )


class JiraNotifyIssueConfig(BaseModel):
    """Send notification for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["send_issue_notification"] = Field(
        default="send_issue_notification",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Send Issue Notification",
        },
        title="Send Issue Notification",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )
    subject: str = Field(
        ..., title="Subject", description="Subject of the notification"
    )
    message: str = Field(..., title="Message", description="Body of the notification")
    recipients: Optional[Dict[str, Any]] = Field(
        default=None,
        title="Recipients",
        description="Recipients configuration (users, groups, etc.)",
    )


class JiraGetIssueVotesConfig(BaseModel):
    """Get votes for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_votes"] = Field(
        default="get_issue_votes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Votes",
        },
        title="Get Issue Votes",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


class JiraAddVoteConfig(BaseModel):
    """Add vote to an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_vote_to_issue"] = Field(
        default="add_vote_to_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Add Vote to Issue",
        },
        title="Add Vote to Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


class JiraRemoveVoteConfig(BaseModel):
    """Remove vote from an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_vote_from_issue"] = Field(
        default="remove_vote_from_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Remove Vote from Issue",
        },
        title="Remove Vote from Issue",
    )
    issue_key: str = Field(
        ..., title="Issue Key", description="The issue key (e.g., PROJ-123)"
    )


# --- Additional User Operations ---


class JiraGetUserConfig(BaseModel):
    """Get a user by account ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user"] = Field(
        default="get_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User",
        },
        title="Get User",
    )
    account_id: str = Field(
        ..., title="Account ID", description="The account ID of the user"
    )


class JiraGetUserGroupsConfig(BaseModel):
    """Get groups that a user belongs to"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_groups"] = Field(
        default="list_user_groups",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List User Groups",
        },
        title="List User Groups",
    )
    account_id: str = Field(
        ..., title="Account ID", description="The account ID of the user"
    )


class JiraGetUserPropertiesConfig(BaseModel):
    """Get all properties for a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_properties"] = Field(
        default="list_user_properties",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List User Properties",
        },
        title="List User Properties",
    )
    account_id: str = Field(
        ..., title="Account ID", description="The account ID of the user"
    )


class JiraGetUserPropertyConfig(BaseModel):
    """Get a property for a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_property"] = Field(
        default="get_user_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Property",
        },
        title="Get User Property",
    )
    account_id: str = Field(
        ..., title="Account ID", description="The account ID of the user"
    )
    property_key: str = Field(
        ..., title="Property Key", description="The key of the property to retrieve"
    )


class JiraSetUserPropertyConfig(BaseModel):
    """Set a property for a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_user_property"] = Field(
        default="set_user_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set User Property",
        },
        title="Set User Property",
    )
    account_id: str = Field(
        ..., title="Account ID", description="The account ID of the user"
    )
    property_key: str = Field(
        ..., title="Property Key", description="The key of the property to set"
    )
    property_value: Dict[str, Any] = Field(
        ..., title="Property Value", description="The JSON value to store"
    )


class JiraDeleteUserPropertyConfig(BaseModel):
    """Delete a property from a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_user_property"] = Field(
        default="delete_user_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Delete User Property",
        },
        title="Delete User Property",
    )
    account_id: str = Field(
        ..., title="Account ID", description="The account ID of the user"
    )
    property_key: str = Field(
        ..., title="Property Key", description="The key of the property to delete"
    )


# --- Bulk Operations ---


class JiraBulkCreateIssuesConfig(BaseModel):
    """Create multiple issues in bulk"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["bulk_create_issues"] = Field(
        default="bulk_create_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Bulk Create Issues",
        },
        title="Bulk Create Issues",
    )
    issues: List[Dict[str, Any]] = Field(
        ..., title="Issues", description="List of issue data to create"
    )


class JiraBulkUpdateIssuesConfig(BaseModel):
    """Update multiple issues in bulk"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["bulk_update_issues"] = Field(
        default="bulk_update_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Bulk Update Issues",
        },
        title="Bulk Update Issues",
    )
    issue_keys: List[str] = Field(
        ...,
        title="Issue Keys or IDs",
        description="Issue keys or IDs to edit (selectedIssueIdsOrKeys)",
    )
    edited_fields_input: Dict[str, Any] = Field(
        ...,
        title="Edited Fields Input",
        description=(
            "Jira bulk-edit editedFieldsInput object grouping fields by type, "
            "e.g. {\"labelsFields\": [{\"bulkEditMultiSelectFieldOption\": \"ADD\", "
            "\"fieldId\": \"labels\", \"labels\": [{\"name\": \"triage\"}]}]}"
        ),
    )
    selected_actions: List[str] = Field(
        ...,
        title="Selected Actions",
        description="Field IDs to edit (must match the fields in Edited Fields Input, e.g. [\"labels\"])",
    )
    send_bulk_notification: Optional[bool] = Field(
        default=None,
        title="Send Bulk Notification",
        description="Whether to send email notifications for the bulk edit",
    )


class JiraBulkDeleteIssuesConfig(BaseModel):
    """Delete multiple issues in bulk"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["bulk_delete_issues"] = Field(
        default="bulk_delete_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Bulk Delete Issues",
        },
        title="Bulk Delete Issues",
    )
    issue_keys: List[str] = Field(
        ..., title="Issue Keys", description="List of issue keys to delete"
    )


# --- Avatar Operations ---


class JiraGetProjectAvatarsConfig(BaseModel):
    """Get all avatars for a project"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_project_avatars"] = Field(
        default="list_project_avatars",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Project Avatars",
        },
        title="List Project Avatars",
    )
    project_key: str = Field(..., title="Project Key", description="The project key")


class JiraGetIssueTypeAvatarsConfig(BaseModel):
    """Get all avatars for an issue type"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_type_avatars"] = Field(
        default="list_issue_type_avatars",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "List Issue Type Avatars",
        },
        title="List Issue Type Avatars",
    )
    issue_type_id: str = Field(
        ..., title="Issue Type ID", description="The ID of the issue type"
    )


# --- Application Property Operations ---


class JiraGetApplicationPropertiesConfig(BaseModel):
    """Get all application properties"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_application_properties"] = Field(
        default="list_application_properties",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "System",
            "x-is-trigger": False,
            "x-display-name": "List Application Properties",
        },
        title="List Application Properties",
    )


class JiraSetApplicationPropertyConfig(BaseModel):
    """Set an application property"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_application_property"] = Field(
        default="set_application_property",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "System",
            "x-is-trigger": False,
            "x-display-name": "Set Application Property",
        },
        title="Set Application Property",
    )
    key: str = Field(
        ..., title="Property Key", description="The key of the application property"
    )
    value: str = Field(..., title="Value", description="The value to set")


# --- Configuration Operations ---


class JiraGetConfigurationConfig(BaseModel):
    """Get global configuration"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_global_configuration"] = Field(
        default="get_global_configuration",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "System",
            "x-is-trigger": False,
            "x-display-name": "Get Global Configuration",
        },
        title="Get Global Configuration",
    )


# --- Issue Security Level Operations ---


class JiraGetIssueSecurityLevelConfig(BaseModel):
    """Get issue security level by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_security_level"] = Field(
        default="get_issue_security_level",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Security Level",
        },
        title="Get Issue Security Level",
    )
    level_id: str = Field(
        ..., title="Level ID", description="The ID of the security level"
    )


# --- Additional Status Operations ---


class JiraGetStatusesConfig(BaseModel):
    """Get all statuses"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_statuses"] = Field(
        default="list_statuses",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Status",
            "x-is-trigger": False,
            "x-display-name": "List Statuses",
        },
        title="List Statuses",
    )


class JiraGetStatusConfig(BaseModel):
    """Get a status by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_status"] = Field(
        default="get_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Status",
            "x-is-trigger": False,
            "x-display-name": "Get Status",
        },
        title="Get Status",
    )
    status_id: str = Field(..., title="Status ID", description="The ID of the status")


class JiraCreateStatusConfig(BaseModel):
    """Create a new status"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_status"] = Field(
        default="create_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Status",
            "x-is-trigger": False,
            "x-display-name": "Create Status",
        },
        title="Create Status",
    )
    name: str = Field(..., title="Name", description="Name of the status")
    status_category: str = Field(
        ...,
        title="Status Category",
        description="Status category (TODO, IN_PROGRESS, or DONE)",
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Description of the status"
    )


class JiraUpdateStatusConfig(BaseModel):
    """Update a status"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_status"] = Field(
        default="update_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Status",
            "x-is-trigger": False,
            "x-display-name": "Update Status",
        },
        title="Update Status",
    )
    status_id: str = Field(..., title="Status ID", description="The ID of the status")
    name: Optional[str] = Field(
        default=None, title="Name", description="New name of the status"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description of the status"
    )


class JiraDeleteStatusConfig(BaseModel):
    """Delete a status"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_status"] = Field(
        default="delete_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Status",
            "x-is-trigger": False,
            "x-display-name": "Delete Status",
        },
        title="Delete Status",
    )
    status_id: str = Field(
        ..., title="Status ID", description="The ID of the status to delete"
    )


# --- Additional Resolution Operations ---


class JiraGetResolutionConfig(BaseModel):
    """Get a resolution by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_resolution"] = Field(
        default="get_resolution",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Resolution",
            "x-is-trigger": False,
            "x-display-name": "Get Resolution",
        },
        title="Get Resolution",
    )
    resolution_id: str = Field(
        ..., title="Resolution ID", description="The ID of the resolution"
    )


class JiraCreateResolutionConfig(BaseModel):
    """Create a new resolution"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_resolution"] = Field(
        default="create_resolution",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Resolution",
            "x-is-trigger": False,
            "x-display-name": "Create Resolution",
        },
        title="Create Resolution",
    )
    name: str = Field(..., title="Name", description="Name of the resolution")
    description: Optional[str] = Field(
        default=None, title="Description", description="Description of the resolution"
    )


class JiraUpdateResolutionConfig(BaseModel):
    """Update a resolution"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_resolution"] = Field(
        default="update_resolution",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Resolution",
            "x-is-trigger": False,
            "x-display-name": "Update Resolution",
        },
        title="Update Resolution",
    )
    resolution_id: str = Field(
        ..., title="Resolution ID", description="The ID of the resolution"
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New name of the resolution"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New description of the resolution",
    )


class JiraDeleteResolutionConfig(BaseModel):
    """Delete a resolution"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_resolution"] = Field(
        default="delete_resolution",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Resolution",
            "x-is-trigger": False,
            "x-display-name": "Delete Resolution",
        },
        title="Delete Resolution",
    )
    resolution_id: str = Field(
        ..., title="Resolution ID", description="The ID of the resolution to delete"
    )
    replace_with: str = Field(
        ...,
        title="Replace With",
        description="ID of the resolution to reassign issues to before deletion",
    )


# --- Additional Priority Operations ---


class JiraGetPriorityConfig(BaseModel):
    """Get a priority by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_priority"] = Field(
        default="get_priority",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Priority",
            "x-is-trigger": False,
            "x-display-name": "Get Priority",
        },
        title="Get Priority",
    )
    priority_id: str = Field(
        ..., title="Priority ID", description="The ID of the priority"
    )


class JiraCreatePriorityConfig(BaseModel):
    """Create a new priority"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_priority"] = Field(
        default="create_priority",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Priority",
            "x-is-trigger": False,
            "x-display-name": "Create Priority",
        },
        title="Create Priority",
    )
    name: str = Field(..., title="Name", description="Name of the priority")
    description: Optional[str] = Field(
        default=None, title="Description", description="Description of the priority"
    )
    icon_url: Optional[str] = Field(
        default=None, title="Icon URL", description="URL of the priority icon"
    )
    status_color: Optional[str] = Field(
        default=None, title="Status Color", description="Color code for the priority"
    )


class JiraUpdatePriorityConfig(BaseModel):
    """Update a priority"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_priority"] = Field(
        default="update_priority",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Priority",
            "x-is-trigger": False,
            "x-display-name": "Update Priority",
        },
        title="Update Priority",
    )
    priority_id: str = Field(
        ..., title="Priority ID", description="The ID of the priority"
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New name of the priority"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New description of the priority"
    )


class JiraDeletePriorityConfig(BaseModel):
    """Delete a priority"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_priority"] = Field(
        default="delete_priority",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Priority",
            "x-is-trigger": False,
            "x-display-name": "Delete Priority",
        },
        title="Delete Priority",
    )
    priority_id: str = Field(
        ..., title="Priority ID", description="The ID of the priority to delete"
    )


# --- Additional Issue Type Operations ---


class JiraGetIssueTypeConfig(BaseModel):
    """Get an issue type by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_type"] = Field(
        default="get_issue_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Type",
        },
        title="Get Issue Type",
    )
    issue_type_id: str = Field(
        ..., title="Issue Type ID", description="The ID of the issue type"
    )


class JiraCreateIssueTypeConfig(BaseModel):
    """Create a new issue type"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_issue_type"] = Field(
        default="create_issue_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Create Issue Type",
        },
        title="Create Issue Type",
    )
    name: str = Field(..., title="Name", description="Name of the issue type")
    description: Optional[str] = Field(
        default=None, title="Description", description="Description of the issue type"
    )
    type: str = Field(
        default="standard",
        title="Type",
        description="Type of issue type (standard or subtask)",
    )


class JiraUpdateIssueTypeConfig(BaseModel):
    """Update an issue type"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_issue_type"] = Field(
        default="update_issue_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Update Issue Type",
        },
        title="Update Issue Type",
    )
    issue_type_id: str = Field(
        ..., title="Issue Type ID", description="The ID of the issue type"
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New name of the issue type"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New description of the issue type",
    )


class JiraDeleteIssueTypeConfig(BaseModel):
    """Delete an issue type"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue_type"] = Field(
        default="delete_issue_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue Type",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Type",
        },
        title="Delete Issue Type",
    )
    issue_type_id: str = Field(
        ..., title="Issue Type ID", description="The ID of the issue type to delete"
    )


# --- Advanced JQL Operations ---


class JiraValidateJQLConfig(BaseModel):
    """Validate a JQL query"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["validate_jql_query"] = Field(
        default="validate_jql_query",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "JQL",
            "x-is-trigger": False,
            "x-display-name": "Validate Jql Query",
        },
        title="Validate Jql Query",
    )
    jql: str = Field(..., title="JQL Query", description="The JQL query to validate")


class JiraGetJQLAutoCompleteConfig(BaseModel):
    """Get auto-complete suggestions for JQL"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_jql_autocomplete_suggestions"] = Field(
        default="get_jql_autocomplete_suggestions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "JQL",
            "x-is-trigger": False,
            "x-display-name": "Get Jql Autocomplete Suggestions",
        },
        title="Get Jql Autocomplete Suggestions",
    )
    field_name: Optional[str] = Field(
        default=None,
        title="Field Name",
        description="Field name for auto-complete suggestions",
    )


# --- Additional Operations ---


class JiraGetMyPreferencesConfig(BaseModel):
    """Get current user preferences"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_current_user_preferences"] = Field(
        default="get_current_user_preferences",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Current User Preferences",
        },
        title="Get Current User Preferences",
    )
    key: str = Field(
        ...,
        title="Preference Key",
        description="The key of the preference to retrieve",
    )


class JiraSetMyPreferenceConfig(BaseModel):
    """Set a user preference"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_current_user_preference"] = Field(
        default="set_current_user_preference",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set Current User Preference",
        },
        title="Set Current User Preference",
    )
    preference_key: str = Field(
        ..., title="Preference Key", description="The key of the preference to set"
    )
    value: str = Field(..., title="Value", description="The value to set")


class JiraGetLicenseConfig(BaseModel):
    """Get Jira license information"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_jira_license_info"] = Field(
        default="get_jira_license_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "System",
            "x-is-trigger": False,
            "x-display-name": "Get Jira License Info",
        },
        title="Get Jira License Info",
    )


def _jira_trigger_field(value: str, display: str):
    """Build the hidden `operation` discriminator Field for a Jira trigger."""
    return Field(
        value,
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": display,
        },
        title=display,
    )


class _JiraEventTriggerBase(BaseModel):
    """Shared fields for Jira per-event triggers.

    Each per-event trigger op is a separate operation (On Issue Created, etc.)
    so the user picks the specific trigger rather than a generic events field;
    the event type is resolved from the operation via ``_trigger_event_map``.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    jql_filter: str = Field(
        "",
        title="JQL Filter",
        description=(
            "JQL restricting which issues' events fire the trigger. Jira dynamic "
            "webhooks only support =, !=, IN, and NOT IN operators; leave blank "
            "to match all issues."
        ),
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class JiraOnIssueCreatedConfig(_JiraEventTriggerBase):
    """Trigger: fires when a Jira issue is created."""

    operation: Literal["on_issue_created"] = _jira_trigger_field(
        "on_issue_created", "On Issue Created"
    )


class JiraOnIssueUpdatedConfig(_JiraEventTriggerBase):
    """Trigger: fires when a Jira issue is updated."""

    operation: Literal["on_issue_updated"] = _jira_trigger_field(
        "on_issue_updated", "On Issue Updated"
    )


class JiraOnIssueDeletedConfig(_JiraEventTriggerBase):
    """Trigger: fires when a Jira issue is deleted."""

    operation: Literal["on_issue_deleted"] = _jira_trigger_field(
        "on_issue_deleted", "On Issue Deleted"
    )


class JiraOnCommentAddedConfig(_JiraEventTriggerBase):
    """Trigger: fires when a comment is added to a Jira issue."""

    operation: Literal["on_comment_added"] = _jira_trigger_field(
        "on_comment_added", "On Comment Added"
    )


# Union of all config types
JiraConfig = Annotated[
    Union[
        # Trigger operations
        JiraOnIssueCreatedConfig,
        JiraOnIssueUpdatedConfig,
        JiraOnIssueDeletedConfig,
        JiraOnCommentAddedConfig,
        # Issue operations
        JiraGetIssueConfig,
        JiraSearchIssuesConfig,
        JiraCreateIssueConfig,
        JiraUpdateIssueConfig,
        JiraTransitionIssueConfig,
        JiraListTransitionsConfig,
        JiraAddCommentConfig,
        JiraDeleteIssueConfig,
        # Project operations
        JiraListProjectsConfig,
        JiraGetProjectConfig,
        # User operations
        JiraSearchUsersConfig,
        JiraGetMyselfConfig,
        # Attachment operations
        JiraGetAttachmentMetadataConfig,
        JiraDownloadAttachmentConfig,
        JiraDeleteAttachmentConfig,
        JiraAddAttachmentConfig,
        JiraGetAttachmentsForIssueConfig,
        JiraExpandAttachmentForHumansConfig,
        # Worklog operations
        JiraAddWorklogConfig,
        JiraGetWorklogConfig,
        JiraUpdateWorklogConfig,
        JiraDeleteWorklogConfig,
        JiraGetIssueWorklogsConfig,
        JiraGetDeletedWorklogsConfig,
        JiraGetUpdatedWorklogsConfig,
        JiraGetWorklogPropertyKeysConfig,
        # Component operations
        JiraCreateComponentConfig,
        JiraGetComponentConfig,
        JiraUpdateComponentConfig,
        JiraDeleteComponentConfig,
        JiraGetProjectComponentsConfig,
        JiraGetComponentRelatedIssuesConfig,
        # Version operations
        JiraCreateVersionConfig,
        JiraGetVersionConfig,
        JiraUpdateVersionConfig,
        JiraDeleteVersionConfig,
        JiraGetProjectVersionsConfig,
        JiraMergeVersionsConfig,
        JiraMoveVersionConfig,
        JiraGetVersionRelatedIssuesConfig,
        JiraGetVersionUnresolvedIssuesConfig,
        # Issue Link operations
        JiraGetIssueLinkConfig,
        JiraCreateIssueLinkConfig,
        JiraDeleteIssueLinkConfig,
        # Watcher operations
        JiraGetIssueWatchersConfig,
        JiraAddWatcherConfig,
        JiraRemoveWatcherConfig,
        # Priority operations
        JiraGetPrioritiesConfig,
        JiraGetPriorityConfig,
        # Resolution operations
        JiraGetResolutionsConfig,
        JiraGetResolutionConfig,
        # Status operations
        JiraGetStatusesConfig,
        JiraGetStatusConfig,
        # Issue Type operations
        JiraGetIssueTypesConfig,
        JiraGetIssueTypeConfig,
        JiraGetProjectIssueTypesConfig,
        # Filter operations
        JiraCreateFilterConfig,
        JiraGetFilterConfig,
        JiraUpdateFilterConfig,
        JiraDeleteFilterConfig,
        JiraSearchFiltersConfig,
        # Comment operations (additional)
        JiraGetCommentConfig,
        JiraGetIssueCommentsConfig,
        JiraUpdateCommentConfig,
        JiraDeleteCommentConfig,
        # Field operations
        JiraGetFieldsConfig,
        JiraCreateCustomFieldConfig,
        # Board operations (Jira Software)
        JiraGetAllBoardsConfig,
        JiraGetBoardConfig,
        JiraGetBoardIssuesConfig,
        JiraGetBoardBacklogConfig,
        JiraGetBoardSprintsConfig,
        # Sprint operations (Jira Software)
        JiraGetSprintConfig,
        JiraCreateSprintConfig,
        JiraUpdateSprintConfig,
        JiraDeleteSprintConfig,
        JiraGetSprintIssuesConfig,
        JiraMoveIssuesToSprintConfig,
        # Epic operations (Jira Software)
        JiraGetEpicConfig,
        JiraGetEpicIssuesConfig,
        JiraMoveIssuesToEpicConfig,
        # Remote Link operations
        JiraGetRemoteLinksConfig,
        JiraCreateRemoteLinkConfig,
        JiraDeleteRemoteLinkConfig,
        # Label operations
        JiraGetLabelsConfig,
        JiraAddLabelsConfig,
        JiraSetLabelsConfig,
        # Issue Property operations
        JiraGetIssuePropertyConfig,
        JiraSetIssuePropertyConfig,
        JiraDeleteIssuePropertyConfig,
        JiraGetIssuePropertyKeysConfig,
        # Permission operations
        JiraGetMyPermissionsConfig,
        JiraGetAllPermissionsConfig,
        JiraCheckPermissionsConfig,
        # Permission Scheme operations
        JiraGetPermissionSchemesConfig,
        JiraGetPermissionSchemeConfig,
        JiraCreatePermissionSchemeConfig,
        JiraDeletePermissionSchemeConfig,
        # Group operations
        JiraGetGroupsConfig,
        JiraGetGroupConfig,
        JiraCreateGroupConfig,
        JiraDeleteGroupConfig,
        JiraAddUserToGroupConfig,
        JiraRemoveUserFromGroupConfig,
        JiraGetGroupMembersConfig,
        # Project Role operations
        JiraGetProjectRolesConfig,
        JiraGetProjectRoleConfig,
        JiraAddActorsToRoleConfig,
        JiraRemoveActorsFromRoleConfig,
        # Screen operations
        JiraGetScreensConfig,
        JiraGetScreenConfig,
        JiraGetScreenTabsConfig,
        JiraGetScreenFieldsConfig,
        # Issue Security Scheme operations
        JiraGetIssueSecuritySchemesConfig,
        JiraGetIssueSecuritySchemeConfig,
        # Notification Scheme operations
        JiraGetNotificationSchemesConfig,
        JiraGetNotificationSchemeConfig,
        # Workflow operations
        JiraGetWorkflowsConfig,
        JiraGetWorkflowConfig,
        JiraGetWorkflowSchemesConfig,
        JiraGetWorkflowSchemeConfig,
        # Dashboard operations
        JiraGetDashboardsConfig,
        JiraGetDashboardConfig,
        JiraCreateDashboardConfig,
        JiraUpdateDashboardConfig,
        JiraDeleteDashboardConfig,
        # Time Tracking operations
        JiraGetWorklogConfig,
        JiraUpdateWorklogConfig,
        # Audit operations
        JiraGetAuditRecordsConfig,
        # Advanced Search operations
        JiraSearchUsersConfig,
        JiraSearchProjectsConfig,
        JiraGetApplicationPropertyConfig,
        JiraGetServerInfoConfig,
        # Issue Link Type operations
        JiraGetIssueLinkTypesConfig,
        JiraGetIssueLinkTypeConfig,
        JiraCreateIssueLinkTypeConfig,
        JiraUpdateIssueLinkTypeConfig,
        JiraDeleteIssueLinkTypeConfig,
        # Field Configuration operations
        JiraGetFieldConfigurationsConfig,
        JiraGetFieldConfigurationConfig,
        JiraGetFieldConfigurationSchemesConfig,
        JiraGetFieldConfigurationSchemeConfig,
        # Issue Type Scheme operations
        JiraGetIssueTypeSchemesConfig,
        JiraGetIssueTypeSchemeConfig,
        JiraCreateIssueTypeSchemeConfig,
        JiraUpdateIssueTypeSchemeConfig,
        JiraDeleteIssueTypeSchemeConfig,
        # Issue Type Screen Scheme operations
        JiraGetIssueTypeScreenSchemesConfig,
        JiraGetIssueTypeScreenSchemeConfig,
        # Priority Scheme operations
        JiraGetPrioritySchemeConfig,
        JiraGetPrioritySchemesConfig,
        # Additional Project operations
        JiraArchiveProjectConfig,
        JiraRestoreProjectConfig,
        JiraGetProjectCategoryConfig,
        JiraGetAllProjectCategoriesConfig,
        JiraCreateProjectCategoryConfig,
        JiraUpdateProjectCategoryConfig,
        JiraDeleteProjectCategoryConfig,
        # Additional Issue operations
        JiraAssignIssueConfig,
        JiraGetIssueChangelogConfig,
        JiraNotifyIssueConfig,
        JiraGetIssueVotesConfig,
        JiraAddVoteConfig,
        JiraRemoveVoteConfig,
        # Additional User operations
        JiraGetUserConfig,
        JiraGetUserGroupsConfig,
        JiraGetUserPropertiesConfig,
        JiraGetUserPropertyConfig,
        JiraSetUserPropertyConfig,
        JiraDeleteUserPropertyConfig,
        # Bulk operations
        JiraBulkCreateIssuesConfig,
        JiraBulkUpdateIssuesConfig,
        JiraBulkDeleteIssuesConfig,
        # Avatar operations
        JiraGetProjectAvatarsConfig,
        JiraGetIssueTypeAvatarsConfig,
        # Application Property operations
        JiraGetApplicationPropertiesConfig,
        JiraSetApplicationPropertyConfig,
        # Configuration operations
        JiraGetConfigurationConfig,
        # Issue Security Level operations
        JiraGetIssueSecurityLevelConfig,
        # Status operations
        JiraGetStatusesConfig,
        JiraGetStatusConfig,
        JiraCreateStatusConfig,
        JiraUpdateStatusConfig,
        JiraDeleteStatusConfig,
        # Resolution operations
        JiraGetResolutionConfig,
        JiraCreateResolutionConfig,
        JiraUpdateResolutionConfig,
        JiraDeleteResolutionConfig,
        # Priority operations
        JiraGetPriorityConfig,
        JiraCreatePriorityConfig,
        JiraUpdatePriorityConfig,
        JiraDeletePriorityConfig,
        # Issue Type operations
        JiraGetIssueTypeConfig,
        JiraCreateIssueTypeConfig,
        JiraUpdateIssueTypeConfig,
        JiraDeleteIssueTypeConfig,
        # JQL operations
        JiraValidateJQLConfig,
        JiraGetJQLAutoCompleteConfig,
        # User preference operations
        JiraGetMyPreferencesConfig,
        JiraSetMyPreferenceConfig,
        # License operations
        JiraGetLicenseConfig,
    ],
    Discriminator("operation"),
]


# Full node config
class JiraNodeFullConfig(NodeConfig[JiraConfig, JiraCredential]):
    """Complete node configuration for Jira"""

    pass


# ============================================================================
# Jira Node Implementation
# ============================================================================


class JiraNode(WatchChannelTriggerMixin, WorkflowNode):
    """
    Jira workflow node for issue and project management.

    Supports both OAuth 2.0 (3LO) and API token authentication.

    Note: Jira dynamic webhooks carry no HMAC signature, so the trigger relies
    on the unguessable webhook URL for authenticity (the same model as the
    generic webhook trigger). ``verify_webhook_signature`` is intentionally not
    overridden — it inherits the permissive base default.
    """

    edit_examples = [
        "Create bug ticket in PROJ project with high priority and assign",
        "Search all open issues in PROJ and update status to in progress",
        "Get issue PROJ-123 details and add comment about progress",
        "Create subtask under parent issue PROJ-456 for code review",
        "Transition issue to resolved and add custom field value",
        "Link two issues as duplicate and update description/labels",
        "Get all issues with label 'bug' and change assignee to qa-team",
    ]

    _trigger_event_map = {
        "on_issue_created": ["jira:issue_created"],
        "on_issue_updated": ["jira:issue_updated"],
        "on_issue_deleted": ["jira:issue_deleted"],
        "on_comment_added": ["comment_created"],
    }

    scope_registry = JIRA_SCOPES

    connection_evidence = ConnectionEvidence(
        operation="list_projects",
        noun="projects",
        label_keys=("name", "key", "id"),
        identity_operation="get_current_user",
    )

    @classmethod
    def get_config_model(cls):
        return JiraNodeFullConfig

    # ========================================================================
    # Webhook trigger (on_jira_event) — dynamic webhook with 30-day expiry
    # ========================================================================

    @classmethod
    async def _register_watch_channel(
        cls, *, pool, user_id, workflow_id, node_id, webhook_id,
        webhook_url, credential, credential_id, config,
    ) -> Dict[str, Any]:
        api_base = _jira_api_base_from_dict(credential)
        headers = _jira_auth_headers_from_dict(credential)

        # Delete a stale webhook from a previous registration so re-saving the
        # workflow doesn't leak webhooks or cause duplicate deliveries.
        existing = await get_watch_channel(pool, workflow_id, node_id)
        if existing and existing.get("channel_id"):
            try:
                await jira_delete_webhook(api_base, headers, existing["channel_id"])
            except Exception as e:
                logger.warning(
                    f"[JiraNode] Could not delete stale webhook: {e}"
                )

        events = cls._trigger_event_map.get((config or {}).get("operation"), [])
        jql = (config or {}).get("jql_filter")
        if not jql and (config or {}).get("project_key"):
            jql = f"project = {(config or {})['project_key']}"
        if not jql:
            # Jira rejects an empty jqlFilter ("Empty JQL search not supported"),
            # so "leave blank to match all issues" needs a real match-all clause.
            # Dynamic webhooks allow only =, !=, IN, NOT IN operators, so use a
            # `!=` against a sentinel that can never exist — matches every issue.
            jql = _MATCH_ALL_JQL
        jira_webhook_id = await jira_register_webhook(
            api_base, headers, webhook_url, events, jql
        )
        await save_watch_channel(
            pool,
            webhook_id=webhook_id,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
            provider="jira",
            credential_id=credential_id,
            channel_id=jira_webhook_id,
            resource_id=None,
            channel_token="",
            expires_at=datetime.now(timezone.utc) + _JIRA_WEBHOOK_TTL,
        )
        return {}

    @classmethod
    async def _stop_watch_channel(
        cls, *, pool, workflow_id, node_id, credential, config, channel_row
    ) -> None:
        if not credential or not channel_row.get("channel_id"):
            return
        api_base = _jira_api_base_from_dict(credential)
        headers = _jira_auth_headers_from_dict(credential)
        await jira_delete_webhook(api_base, headers, channel_row["channel_id"])

    @classmethod
    async def renew_watch_channel(cls, pool, channel_row: Dict[str, Any]) -> None:
        """Extend an expiring Jira dynamic webhook (called by the cron).

        Works for both API-token and OAuth credentials: the stored OAuth access
        token is ~1h-lived but this cron fires ~15 days out, so it is refreshed
        via the shared freshen choke point before the PUT (a no-op for API-token
        credentials, which carry no refresh token).
        """
        from utils.credential_loader import load_credential

        user_id = str(channel_row["user_id"])
        cred_id = channel_row.get("credential_id")
        credential = await load_credential(
            pool, user_id, str(cred_id) if cred_id else None
        )
        if not credential or not channel_row.get("channel_id"):
            logger.warning(
                f"[JiraNode] Cannot renew channel {channel_row.get('id')}: "
                f"credential or webhook id unavailable"
            )
            return
        credential = await cls.freshen_credential(
            credential, pool=pool, user_id=user_id,
            credential_id=str(cred_id) if cred_id else None,
        )
        api_base = _jira_api_base_from_dict(credential)
        headers = _jira_auth_headers_from_dict(credential)
        await jira_refresh_webhook(api_base, headers, channel_row["channel_id"])
        await update_channel_subscription(
            pool,
            channel_row["id"],
            channel_id=channel_row["channel_id"],
            resource_id=None,
            expires_at=datetime.now(timezone.utc) + _JIRA_WEBHOOK_TTL,
        )

    def _get_api_base(self, credentials: JiraCredential) -> str:
        """Get the API base URL based on credential type"""
        if isinstance(credentials, JiraOAuthCredential):
            return (
                f"https://api.atlassian.com/ex/jira/{credentials.cloud_id}/rest/api/3"
            )
        else:
            # API token auth uses direct domain
            tenant = normalize_provider_subdomain(
                credentials.domain,
                "atlassian.net",
                field_name="Jira domain",
            )
            return f"https://{tenant}.atlassian.net/rest/api/3"

    def _get_auth_headers(self, credentials: JiraCredential) -> Dict[str, str]:
        """Get authentication headers based on credential type"""
        if isinstance(credentials, JiraOAuthCredential):
            return {
                "Authorization": f"Bearer {credentials.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        else:
            # Basic auth with email:api_token
            auth_string = f"{credentials.email}:{credentials.api_token}"
            auth_bytes = base64.b64encode(auth_string.encode()).decode()
            return {
                "Authorization": f"Basic {auth_bytes}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

    def _parse_scope_string(self, scope: Optional[str]) -> set[str]:
        if not scope:
            return set()
        return {part.strip() for part in scope.split() if part.strip()}

    def _raise_missing_scope_error(self, missing_scopes: set[str]) -> None:
        missing = ", ".join(sorted(missing_scopes))
        raise ValueError(
            "This Jira OAuth credential is missing scopes required for this operation. "
            f"Missing scopes: {missing}. {RECONNECT_HINT}"
        )

    def _ensure_operation_scopes(
        self, credentials: JiraOAuthCredential, op_config: BaseModel
    ) -> None:
        """Pre-flight the credential's granted scopes against JIRA_SCOPES.

        Operations without a requirement entry (see the registry's ``unmapped``)
        are let through so Jira's own 403 is what the user sees, rather than a
        guess from an incomplete table.
        """
        requirement = JIRA_SCOPES.get(getattr(op_config, "operation", ""))
        if requirement is None or not requirement.scopes:
            return
        required = set(requirement.scopes)
        granted = self._parse_scope_string(credentials.scope)
        if granted and not required.issubset(granted):
            self._raise_missing_scope_error(required - granted)

    @classmethod
    async def _hydrate_oauth_metadata(
        cls,
        cred_dict: Dict[str, Any],
        credential_id: Optional[str],
        *,
        user_id: Optional[str],
        organization_id: Optional[str] = None,
        pool=None,
    ) -> Dict[str, Any]:
        """Backfill Jira OAuth fields that older refreshes dropped from encrypted data."""
        credential_type = cred_dict.get("credential_type")
        if credential_type and credential_type != "jira_oauth":
            return cred_dict
        if not any(
            cred_dict.get(key) for key in ("access_token", "refresh_token", "cloud_id")
        ):
            return cred_dict
        if not credential_id:
            return cred_dict
        if (
            cred_dict.get("cloud_id")
            and cred_dict.get("scope")
            and cred_dict.get("site_url")
        ):
            return cred_dict

        if pool is None:
            from utils.database_pool import get_native_pool

            pool = get_native_pool()
        async with pool.acquire() as conn:
            org_id = organization_id
            if org_id is None and user_id:
                from wss.handlers.workflow_handler import get_user_org_context

                org_id = await get_user_org_context(conn, user_id)
            from repositories.credentials import credential_access_predicate

            row = await conn.fetchrow(
                f"""
                SELECT c.metadata
                FROM credentials c
                WHERE c.id = $1
                  AND {credential_access_predicate()}
                """,
                credential_id,
                user_id,
                org_id,
            )

        metadata = row["metadata"] if row else None
        if isinstance(metadata, str):
            try:
                import json
                metadata = json.loads(metadata)
            except Exception:
                metadata = None
        if not isinstance(metadata, dict):
            return cred_dict

        if not cred_dict.get("cloud_id") and metadata.get("cloud_id"):
            cred_dict["cloud_id"] = metadata["cloud_id"]
        if not cred_dict.get("scope") and metadata.get("scopes"):
            scopes = metadata["scopes"]
            if isinstance(scopes, list):
                cred_dict["scope"] = " ".join(str(scope) for scope in scopes if scope)
            elif isinstance(scopes, str):
                cred_dict["scope"] = scopes
        if not cred_dict.get("site_url") and metadata.get("site_url"):
            cred_dict["site_url"] = metadata["site_url"]
        if not cred_dict.get("site_name") and metadata.get("site_name"):
            cred_dict["site_name"] = metadata["site_name"]
        return cred_dict

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the Jira node"""
        config = self.config
        if not config or not isinstance(config, JiraNodeFullConfig):
            raise ValueError("Configuration required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials required. Connect a Jira account in the credentials tab."
            )

        # Ensure fresh token for OAuth
        if isinstance(credentials, JiraOAuthCredential):
            credentials = await self._ensure_fresh_token(credentials)

        # Get API base and headers
        api_base = self._get_api_base(credentials)
        headers = self._get_auth_headers(credentials)

        # Execute based on action type
        op_config = config.config
        if isinstance(credentials, JiraOAuthCredential):
            self._ensure_operation_scopes(credentials, op_config)

        # Trigger operation — manual editor run only (webhook deliveries skip
        # execute() because the event payload is the node output directly)
        if isinstance(
            op_config,
            (
                JiraOnIssueCreatedConfig,
                JiraOnIssueUpdatedConfig,
                JiraOnIssueDeletedConfig,
                JiraOnCommentAddedConfig,
            ),
        ):
            return {
                "message": (
                    "This trigger fires when a subscribed Jira event occurs. "
                    "It outputs the Jira event payload."
                ),
                "events": self._trigger_event_map.get(op_config.operation, []),
            }

        # Issue operations
        if isinstance(op_config, JiraGetIssueConfig):
            return await self._get_issue(api_base, headers, op_config)
        elif isinstance(op_config, JiraSearchIssuesConfig):
            return await self._search_issues(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateIssueConfig):
            return await self._create_issue(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateIssueConfig):
            return await self._update_issue(api_base, headers, op_config)
        elif isinstance(op_config, JiraTransitionIssueConfig):
            return await self._transition_issue(api_base, headers, op_config)
        elif isinstance(op_config, JiraListTransitionsConfig):
            return await self._list_transitions(api_base, headers, op_config)
        elif isinstance(op_config, JiraAddCommentConfig):
            return await self._add_comment(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteIssueConfig):
            return await self._delete_issue(api_base, headers, op_config)
        # Project operations
        elif isinstance(op_config, JiraListProjectsConfig):
            return await self._list_projects(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetProjectConfig):
            return await self._get_project(api_base, headers, op_config)
        # User operations
        elif isinstance(op_config, JiraSearchUsersConfig):
            return await self._search_users(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetMyselfConfig):
            return await self._get_myself(api_base, headers)
        # Attachment operations
        elif isinstance(op_config, JiraGetAttachmentMetadataConfig):
            return await self._get_attachment_metadata(api_base, headers, op_config)
        elif isinstance(op_config, JiraDownloadAttachmentConfig):
            return await self._download_attachment(
                api_base,
                headers,
                op_config,
                credentials,
            )
        elif isinstance(op_config, JiraDeleteAttachmentConfig):
            return await self._delete_attachment(api_base, headers, op_config)
        elif isinstance(op_config, JiraAddAttachmentConfig):
            return await self._add_attachment(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetAttachmentsForIssueConfig):
            return await self._get_attachments_for_issue(api_base, headers, op_config)
        elif isinstance(op_config, JiraExpandAttachmentForHumansConfig):
            return await self._expand_attachment_for_humans(
                api_base, headers, op_config
            )
        # Worklog operations
        elif isinstance(op_config, JiraAddWorklogConfig):
            return await self._add_worklog(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetWorklogConfig):
            return await self._get_worklog(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateWorklogConfig):
            return await self._update_worklog(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteWorklogConfig):
            return await self._delete_worklog(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetIssueWorklogsConfig):
            return await self._get_issue_worklogs(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetDeletedWorklogsConfig):
            return await self._get_deleted_worklogs(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetUpdatedWorklogsConfig):
            return await self._get_updated_worklogs(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetWorklogPropertyKeysConfig):
            return await self._get_worklog_property_keys(api_base, headers, op_config)
        # Component operations
        elif isinstance(op_config, JiraCreateComponentConfig):
            return await self._create_component(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetComponentConfig):
            return await self._get_component(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateComponentConfig):
            return await self._update_component(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteComponentConfig):
            return await self._delete_component(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetProjectComponentsConfig):
            return await self._get_project_components(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetComponentRelatedIssuesConfig):
            return await self._get_component_related_issues(
                api_base, headers, op_config
            )
        # Version operations
        elif isinstance(op_config, JiraCreateVersionConfig):
            return await self._create_version(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetVersionConfig):
            return await self._get_version(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateVersionConfig):
            return await self._update_version(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteVersionConfig):
            return await self._delete_version(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetProjectVersionsConfig):
            return await self._get_project_versions(api_base, headers, op_config)
        elif isinstance(op_config, JiraMergeVersionsConfig):
            return await self._merge_versions(api_base, headers, op_config)
        elif isinstance(op_config, JiraMoveVersionConfig):
            return await self._move_version(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetVersionRelatedIssuesConfig):
            return await self._get_version_related_issues(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetVersionUnresolvedIssuesConfig):
            return await self._get_version_unresolved_issues(
                api_base, headers, op_config
            )
        # Issue Link operations
        elif isinstance(op_config, JiraGetIssueLinkConfig):
            return await self._get_issue_link(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateIssueLinkConfig):
            return await self._create_issue_link(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteIssueLinkConfig):
            return await self._delete_issue_link(api_base, headers, op_config)
        # Watcher operations
        elif isinstance(op_config, JiraGetIssueWatchersConfig):
            return await self._get_issue_watchers(api_base, headers, op_config)
        elif isinstance(op_config, JiraAddWatcherConfig):
            return await self._add_watcher(api_base, headers, op_config)
        elif isinstance(op_config, JiraRemoveWatcherConfig):
            return await self._remove_watcher(api_base, headers, op_config)
        # Priority operations
        elif isinstance(op_config, JiraGetPrioritiesConfig):
            return await self._get_priorities(api_base, headers)
        elif isinstance(op_config, JiraGetPriorityConfig):
            return await self._get_priority(api_base, headers, op_config)
        # Resolution operations
        elif isinstance(op_config, JiraGetResolutionsConfig):
            return await self._get_resolutions(api_base, headers)
        elif isinstance(op_config, JiraGetResolutionConfig):
            return await self._get_resolution(api_base, headers, op_config)
        # Status operations
        elif isinstance(op_config, JiraGetStatusesConfig):
            return await self._get_statuses(api_base, headers)
        elif isinstance(op_config, JiraGetStatusConfig):
            return await self._get_status(api_base, headers, op_config)
        # Issue Type operations
        elif isinstance(op_config, JiraGetIssueTypesConfig):
            return await self._get_issue_types(api_base, headers)
        elif isinstance(op_config, JiraGetIssueTypeConfig):
            return await self._get_issue_type(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetProjectIssueTypesConfig):
            return await self._get_project_issue_types(api_base, headers, op_config)
        # Filter operations
        elif isinstance(op_config, JiraCreateFilterConfig):
            return await self._create_filter(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetFilterConfig):
            return await self._get_filter(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateFilterConfig):
            return await self._update_filter(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteFilterConfig):
            return await self._delete_filter(api_base, headers, op_config)
        elif isinstance(op_config, JiraSearchFiltersConfig):
            return await self._search_filters(api_base, headers, op_config)
        # Comment operations (additional)
        elif isinstance(op_config, JiraGetCommentConfig):
            return await self._get_comment(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetIssueCommentsConfig):
            return await self._get_issue_comments(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateCommentConfig):
            return await self._update_comment(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteCommentConfig):
            return await self._delete_comment(api_base, headers, op_config)
        # Field operations
        elif isinstance(op_config, JiraGetFieldsConfig):
            return await self._get_fields(api_base, headers)
        elif isinstance(op_config, JiraCreateCustomFieldConfig):
            return await self._create_custom_field(api_base, headers, op_config)
        # Board operations (Jira Software)
        elif isinstance(op_config, JiraGetAllBoardsConfig):
            return await self._get_all_boards(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetBoardConfig):
            return await self._get_board(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetBoardIssuesConfig):
            return await self._get_board_issues(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetBoardBacklogConfig):
            return await self._get_board_backlog(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetBoardSprintsConfig):
            return await self._get_board_sprints(api_base, headers, op_config)
        # Sprint operations (Jira Software)
        elif isinstance(op_config, JiraGetSprintConfig):
            return await self._get_sprint(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateSprintConfig):
            return await self._create_sprint(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateSprintConfig):
            return await self._update_sprint(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteSprintConfig):
            return await self._delete_sprint(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetSprintIssuesConfig):
            return await self._get_sprint_issues(api_base, headers, op_config)
        elif isinstance(op_config, JiraMoveIssuesToSprintConfig):
            return await self._move_issues_to_sprint(api_base, headers, op_config)
        # Epic operations (Jira Software)
        elif isinstance(op_config, JiraGetEpicConfig):
            return await self._get_epic(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetEpicIssuesConfig):
            return await self._get_epic_issues(api_base, headers, op_config)
        elif isinstance(op_config, JiraMoveIssuesToEpicConfig):
            return await self._move_issues_to_epic(api_base, headers, op_config)
        # Remote Link operations
        elif isinstance(op_config, JiraGetRemoteLinksConfig):
            return await self._get_remote_links(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateRemoteLinkConfig):
            return await self._create_remote_link(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteRemoteLinkConfig):
            return await self._delete_remote_link(api_base, headers, op_config)
        # Label operations
        elif isinstance(op_config, JiraGetLabelsConfig):
            return await self._get_labels(api_base, headers, op_config)
        elif isinstance(op_config, JiraAddLabelsConfig):
            return await self._add_labels(api_base, headers, op_config)
        elif isinstance(op_config, JiraSetLabelsConfig):
            return await self._set_labels(api_base, headers, op_config)
        # Issue Property operations
        elif isinstance(op_config, JiraGetIssuePropertyConfig):
            return await self._get_issue_property(api_base, headers, op_config)
        elif isinstance(op_config, JiraSetIssuePropertyConfig):
            return await self._set_issue_property(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteIssuePropertyConfig):
            return await self._delete_issue_property(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetIssuePropertyKeysConfig):
            return await self._get_issue_property_keys(api_base, headers, op_config)
        # Permission operations
        elif isinstance(op_config, JiraGetMyPermissionsConfig):
            return await self._get_my_permissions(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetAllPermissionsConfig):
            return await self._get_all_permissions(api_base, headers)
        elif isinstance(op_config, JiraCheckPermissionsConfig):
            return await self._check_permissions(api_base, headers, op_config)
        # Permission Scheme operations
        elif isinstance(op_config, JiraGetPermissionSchemesConfig):
            return await self._get_permission_schemes(api_base, headers)
        elif isinstance(op_config, JiraGetPermissionSchemeConfig):
            return await self._get_permission_scheme(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreatePermissionSchemeConfig):
            return await self._create_permission_scheme(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeletePermissionSchemeConfig):
            return await self._delete_permission_scheme(api_base, headers, op_config)
        # Group operations
        elif isinstance(op_config, JiraGetGroupsConfig):
            return await self._get_groups(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetGroupConfig):
            return await self._get_group(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateGroupConfig):
            return await self._create_group(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteGroupConfig):
            return await self._delete_group(api_base, headers, op_config)
        elif isinstance(op_config, JiraAddUserToGroupConfig):
            return await self._add_user_to_group(api_base, headers, op_config)
        elif isinstance(op_config, JiraRemoveUserFromGroupConfig):
            return await self._remove_user_from_group(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetGroupMembersConfig):
            return await self._get_group_members(api_base, headers, op_config)
        # Project Role operations
        elif isinstance(op_config, JiraGetProjectRolesConfig):
            return await self._get_project_roles(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetProjectRoleConfig):
            return await self._get_project_role(api_base, headers, op_config)
        elif isinstance(op_config, JiraAddActorsToRoleConfig):
            return await self._add_actors_to_role(api_base, headers, op_config)
        elif isinstance(op_config, JiraRemoveActorsFromRoleConfig):
            return await self._remove_actors_from_role(api_base, headers, op_config)
        # Screen operations
        elif isinstance(op_config, JiraGetScreensConfig):
            return await self._get_screens(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetScreenConfig):
            return await self._get_screen(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetScreenTabsConfig):
            return await self._get_screen_tabs(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetScreenFieldsConfig):
            return await self._get_screen_fields(api_base, headers, op_config)
        # Issue Security Scheme operations
        elif isinstance(op_config, JiraGetIssueSecuritySchemesConfig):
            return await self._get_issue_security_schemes(api_base, headers)
        elif isinstance(op_config, JiraGetIssueSecuritySchemeConfig):
            return await self._get_issue_security_scheme(api_base, headers, op_config)
        # Notification Scheme operations
        elif isinstance(op_config, JiraGetNotificationSchemesConfig):
            return await self._get_notification_schemes(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetNotificationSchemeConfig):
            return await self._get_notification_scheme(api_base, headers, op_config)
        # Workflow operations
        elif isinstance(op_config, JiraGetWorkflowsConfig):
            return await self._get_workflows(api_base, headers)
        elif isinstance(op_config, JiraGetWorkflowConfig):
            return await self._get_workflow(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetWorkflowSchemesConfig):
            return await self._get_workflow_schemes(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetWorkflowSchemeConfig):
            return await self._get_workflow_scheme(api_base, headers, op_config)
        # Dashboard operations
        elif isinstance(op_config, JiraGetDashboardsConfig):
            return await self._get_dashboards(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetDashboardConfig):
            return await self._get_dashboard(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateDashboardConfig):
            return await self._create_dashboard(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateDashboardConfig):
            return await self._update_dashboard(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteDashboardConfig):
            return await self._delete_dashboard(api_base, headers, op_config)
        # Time Tracking operations
        elif isinstance(op_config, JiraGetWorklogConfig):
            return await self._get_worklog(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateWorklogConfig):
            return await self._update_worklog(api_base, headers, op_config)
        # Audit operations
        elif isinstance(op_config, JiraGetAuditRecordsConfig):
            return await self._get_audit_records(api_base, headers, op_config)
        # Advanced Search operations
        elif isinstance(op_config, JiraSearchUsersConfig):
            return await self._search_users(api_base, headers, op_config)
        elif isinstance(op_config, JiraSearchProjectsConfig):
            return await self._search_projects(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetApplicationPropertyConfig):
            return await self._get_application_property(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetServerInfoConfig):
            return await self._get_server_info(api_base, headers)
        # Issue Link Type operations
        elif isinstance(op_config, JiraGetIssueLinkTypesConfig):
            return await self._get_issue_link_types(api_base, headers)
        elif isinstance(op_config, JiraGetIssueLinkTypeConfig):
            return await self._get_issue_link_type(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateIssueLinkTypeConfig):
            return await self._create_issue_link_type(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateIssueLinkTypeConfig):
            return await self._update_issue_link_type(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteIssueLinkTypeConfig):
            return await self._delete_issue_link_type(api_base, headers, op_config)
        # Field Configuration operations
        elif isinstance(op_config, JiraGetFieldConfigurationsConfig):
            return await self._get_field_configurations(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetFieldConfigurationConfig):
            return await self._get_field_configuration(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetFieldConfigurationSchemesConfig):
            return await self._get_field_configuration_schemes(
                api_base, headers, op_config
            )
        elif isinstance(op_config, JiraGetFieldConfigurationSchemeConfig):
            return await self._get_field_configuration_scheme(
                api_base, headers, op_config
            )
        # Issue Type Scheme operations
        elif isinstance(op_config, JiraGetIssueTypeSchemesConfig):
            return await self._get_issue_type_schemes(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetIssueTypeSchemeConfig):
            return await self._get_issue_type_scheme(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateIssueTypeSchemeConfig):
            return await self._create_issue_type_scheme(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateIssueTypeSchemeConfig):
            return await self._update_issue_type_scheme(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteIssueTypeSchemeConfig):
            return await self._delete_issue_type_scheme(api_base, headers, op_config)
        # Issue Type Screen Scheme operations
        elif isinstance(op_config, JiraGetIssueTypeScreenSchemesConfig):
            return await self._get_issue_type_screen_schemes(
                api_base, headers, op_config
            )
        elif isinstance(op_config, JiraGetIssueTypeScreenSchemeConfig):
            return await self._get_issue_type_screen_scheme(
                api_base, headers, op_config
            )
        # Priority Scheme operations
        elif isinstance(op_config, JiraGetPrioritySchemeConfig):
            return await self._get_priority_scheme(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetPrioritySchemesConfig):
            return await self._get_priority_schemes(api_base, headers, op_config)
        # Additional Project operations
        elif isinstance(op_config, JiraArchiveProjectConfig):
            return await self._archive_project(api_base, headers, op_config)
        elif isinstance(op_config, JiraRestoreProjectConfig):
            return await self._restore_project(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetProjectCategoryConfig):
            return await self._get_project_category(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetAllProjectCategoriesConfig):
            return await self._get_all_project_categories(api_base, headers)
        elif isinstance(op_config, JiraCreateProjectCategoryConfig):
            return await self._create_project_category(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateProjectCategoryConfig):
            return await self._update_project_category(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteProjectCategoryConfig):
            return await self._delete_project_category(api_base, headers, op_config)
        # Additional Issue operations
        elif isinstance(op_config, JiraAssignIssueConfig):
            return await self._assign_issue(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetIssueChangelogConfig):
            return await self._get_issue_changelog(api_base, headers, op_config)
        elif isinstance(op_config, JiraNotifyIssueConfig):
            return await self._notify_issue(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetIssueVotesConfig):
            return await self._get_issue_votes(api_base, headers, op_config)
        elif isinstance(op_config, JiraAddVoteConfig):
            return await self._add_vote(api_base, headers, op_config)
        elif isinstance(op_config, JiraRemoveVoteConfig):
            return await self._remove_vote(api_base, headers, op_config)
        # Additional User operations
        elif isinstance(op_config, JiraGetUserConfig):
            return await self._get_user(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetUserGroupsConfig):
            return await self._get_user_groups(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetUserPropertiesConfig):
            return await self._get_user_properties(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetUserPropertyConfig):
            return await self._get_user_property(api_base, headers, op_config)
        elif isinstance(op_config, JiraSetUserPropertyConfig):
            return await self._set_user_property(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteUserPropertyConfig):
            return await self._delete_user_property(api_base, headers, op_config)
        # Bulk operations
        elif isinstance(op_config, JiraBulkCreateIssuesConfig):
            return await self._bulk_create_issues(api_base, headers, op_config)
        elif isinstance(op_config, JiraBulkUpdateIssuesConfig):
            return await self._bulk_update_issues(api_base, headers, op_config)
        elif isinstance(op_config, JiraBulkDeleteIssuesConfig):
            return await self._bulk_delete_issues(api_base, headers, op_config)
        # Avatar operations
        elif isinstance(op_config, JiraGetProjectAvatarsConfig):
            return await self._get_project_avatars(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetIssueTypeAvatarsConfig):
            return await self._get_issue_type_avatars(api_base, headers, op_config)
        # Application Property operations
        elif isinstance(op_config, JiraGetApplicationPropertiesConfig):
            return await self._get_application_properties(api_base, headers)
        elif isinstance(op_config, JiraSetApplicationPropertyConfig):
            return await self._set_application_property(api_base, headers, op_config)
        # Configuration operations
        elif isinstance(op_config, JiraGetConfigurationConfig):
            return await self._get_configuration(api_base, headers)
        # Issue Security Level operations
        elif isinstance(op_config, JiraGetIssueSecurityLevelConfig):
            return await self._get_issue_security_level(api_base, headers, op_config)
        # Status operations
        elif isinstance(op_config, JiraGetStatusesConfig):
            return await self._get_statuses(api_base, headers)
        elif isinstance(op_config, JiraGetStatusConfig):
            return await self._get_status(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateStatusConfig):
            return await self._create_status(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateStatusConfig):
            return await self._update_status(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteStatusConfig):
            return await self._delete_status(api_base, headers, op_config)
        # Resolution operations
        elif isinstance(op_config, JiraGetResolutionConfig):
            return await self._get_resolution(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateResolutionConfig):
            return await self._create_resolution(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateResolutionConfig):
            return await self._update_resolution(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteResolutionConfig):
            return await self._delete_resolution(api_base, headers, op_config)
        # Priority operations
        elif isinstance(op_config, JiraGetPriorityConfig):
            return await self._get_priority(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreatePriorityConfig):
            return await self._create_priority(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdatePriorityConfig):
            return await self._update_priority(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeletePriorityConfig):
            return await self._delete_priority(api_base, headers, op_config)
        # Issue Type operations
        elif isinstance(op_config, JiraGetIssueTypeConfig):
            return await self._get_issue_type(api_base, headers, op_config)
        elif isinstance(op_config, JiraCreateIssueTypeConfig):
            return await self._create_issue_type(api_base, headers, op_config)
        elif isinstance(op_config, JiraUpdateIssueTypeConfig):
            return await self._update_issue_type(api_base, headers, op_config)
        elif isinstance(op_config, JiraDeleteIssueTypeConfig):
            return await self._delete_issue_type(api_base, headers, op_config)
        # JQL operations
        elif isinstance(op_config, JiraValidateJQLConfig):
            return await self._validate_jql(api_base, headers, op_config)
        elif isinstance(op_config, JiraGetJQLAutoCompleteConfig):
            return await self._get_jql_autocomplete(api_base, headers, op_config)
        # User preference operations
        elif isinstance(op_config, JiraGetMyPreferencesConfig):
            return await self._get_my_preferences(api_base, headers, op_config)
        elif isinstance(op_config, JiraSetMyPreferenceConfig):
            return await self._set_my_preference(api_base, headers, op_config)
        # License operations
        elif isinstance(op_config, JiraGetLicenseConfig):
            return await self._get_license(api_base, headers)

        raise ValueError(f"Unknown action: {type(op_config)}")

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.atlassian_oauth import refresh_access_token

        credential_data = await cls._hydrate_oauth_metadata(
            credential_data or {},
            credential_id,
            user_id=user_id,
            pool=pool,
        )
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="atlassian",
        )

    async def _ensure_fresh_token(
        self, credentials: JiraOAuthCredential
    ) -> JiraOAuthCredential:
        """Refresh OAuth token if expired, persisting via the shared helper."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.atlassian_oauth import refresh_access_token
        from utils.database_pool import get_native_pool

        credential_id = (self.node_data or {}).get("credential_id")
        cred_dict = await self._hydrate_oauth_metadata(
            credentials.model_dump(),
            credential_id,
            user_id=self.user_id,
            organization_id=self.organization_id,
        )
        await ensure_fresh_oauth_token(
            credential_id=credential_id,
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="atlassian",
        )

        # Return updated credentials (keeping cloud_id and metadata)
        return JiraOAuthCredential(
            access_token=cred_dict["access_token"],
            refresh_token=cred_dict.get("refresh_token") or credentials.refresh_token,
            expires_at=cred_dict.get("expires_at"),
            cloud_id=credentials.cloud_id,
            email=credentials.email,
            site_name=credentials.site_name,
            site_url=cred_dict.get("site_url") or credentials.site_url,
            scope=cred_dict.get("scope") or credentials.scope,
        )

    # --- Issue Operations ---

    async def _get_issue(
        self, api_base: str, headers: Dict, config: JiraGetIssueConfig
    ) -> Dict[str, Any]:
        """Get issue by key"""
        params = {}
        if config.expand:
            params["expand"] = config.expand

        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}",
                headers=headers,
                params=params if params else None,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_issue", "issue": result})
            return result

    async def _search_issues(
        self, api_base: str, headers: Dict, config: JiraSearchIssuesConfig
    ) -> Dict[str, Any]:
        """Search issues using JQL"""
        payload = {"jql": config.jql}
        if config.fields:
            payload["fields"] = [f.strip() for f in config.fields.split(",")]
        else:
            # Jira Cloud's newer /search/jql endpoint returns only issue IDs
            # unless fields are requested explicitly. Keep the old usable search
            # contract by defaulting to navigable issue fields.
            payload["fields"] = ["*navigable"]

        # maxResults and startAt go in query params, not payload
        params = {
            "maxResults": min(config.max_results or 50, 100),
            "startAt": config.start_at or 0,
        }

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/search/jql",  # Updated to use new endpoint
                headers=headers,
                json=payload,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            # New endpoint returns different format: {"issues": [], "isLast": true}
            # Convert to old format for backward compatibility
            issues = result.get("issues", [])
            await self.emit({"action": "search_issues_with_jql", "total": len(issues)})
            return {
                "issues": issues,
                "total": len(issues),
                "startAt": config.start_at or 0,
                "maxResults": config.max_results or 50,
                "isLast": result.get("isLast", True),
            }

    async def _create_issue(
        self, api_base: str, headers: Dict, config: JiraCreateIssueConfig
    ) -> Dict[str, Any]:
        """Create a new issue"""
        fields: Dict[str, Any] = {
            "project": {"key": config.project_key},
            "issuetype": {"name": config.issue_type},
            "summary": config.summary,
        }

        if config.description:
            # Try to parse as ADF, fallback to plain text
            fields["description"] = self._format_description(config.description)

        if config.priority:
            fields["priority"] = {"name": config.priority}
        if config.assignee:
            fields["assignee"] = {"accountId": config.assignee}
        if config.labels:
            fields["labels"] = config.labels
        if config.parent_key:
            fields["parent"] = {"key": config.parent_key}
        if config.custom_fields:
            fields.update(config.custom_fields)

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue",
                headers=headers,
                json={"fields": fields},
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_issue", "key": result.get("key")})
            return result

    async def _update_issue(
        self, api_base: str, headers: Dict, config: JiraUpdateIssueConfig
    ) -> Dict[str, Any]:
        """Update an existing issue"""
        fields: Dict[str, Any] = {}

        if config.summary:
            fields["summary"] = config.summary
        if config.description:
            fields["description"] = self._format_description(config.description)
        if config.priority:
            fields["priority"] = {"name": config.priority}
        if config.assignee:
            if config.assignee == "-1":
                fields["assignee"] = None
            else:
                fields["assignee"] = {"accountId": config.assignee}
        if config.labels is not None:
            fields["labels"] = config.labels
        if config.custom_fields:
            fields.update(config.custom_fields)

        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issue/{config.issue_key}",
                headers=headers,
                json={"fields": fields},
            )
            response.raise_for_status()
            await self.emit({"action": "update_issue", "key": config.issue_key})
            return {"success": True, "key": config.issue_key}

    async def _transition_issue(
        self, api_base: str, headers: Dict, config: JiraTransitionIssueConfig
    ) -> Dict[str, Any]:
        """Transition an issue to a new status"""
        payload: Dict[str, Any] = {"transition": {"id": config.transition_id}}

        if config.comment:
            payload["update"] = {
                "comment": [{"add": {"body": self._format_description(config.comment)}}]
            }

        if config.resolution:
            payload.setdefault("fields", {})["resolution"] = {"name": config.resolution}

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue/{config.issue_key}/transitions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {"action": "transition_issue_status", "key": config.issue_key}
            )
            return {
                "success": True,
                "key": config.issue_key,
                "transition_id": config.transition_id,
            }

    async def _list_transitions(
        self, api_base: str, headers: Dict, config: JiraListTransitionsConfig
    ) -> Dict[str, Any]:
        """List available transitions for an issue"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/transitions",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_issue_transitions",
                    "count": len(result.get("transitions", [])),
                }
            )
            return result

    async def _add_comment(
        self, api_base: str, headers: Dict, config: JiraAddCommentConfig
    ) -> Dict[str, Any]:
        """Add a comment to an issue"""
        payload = {"body": self._format_description(config.body)}

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue/{config.issue_key}/comment",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "add_comment_to_issue", "key": config.issue_key})
            return result

    async def _delete_issue(
        self, api_base: str, headers: Dict, config: JiraDeleteIssueConfig
    ) -> Dict[str, Any]:
        """Delete an issue"""
        params = {"deleteSubtasks": str(config.delete_subtasks).lower()}

        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issue/{config.issue_key}",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            await self.emit({"action": "delete_issue", "key": config.issue_key})
            return {"success": True, "key": config.issue_key, "deleted": True}

    # --- Project Operations ---

    async def _list_projects(
        self, api_base: str, headers: Dict, config: JiraListProjectsConfig
    ) -> Dict[str, Any]:
        """List accessible projects"""
        params = {
            "maxResults": config.max_results or 50,
            "startAt": config.start_at or 0,
        }

        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/project/search",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "list_projects", "total": result.get("total", 0)}
            )
            return result

    async def _get_project(
        self, api_base: str, headers: Dict, config: JiraGetProjectConfig
    ) -> Dict[str, Any]:
        """Get project details"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/project/{config.project_key}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_project", "key": result.get("key")})
            return result

    # --- User Operations ---

    async def _get_myself(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get the authenticated user"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/myself",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_current_user", "accountId": result.get("accountId")}
            )
            return result

    # --- Attachment Operations ---

    async def _get_attachment_metadata(
        self, api_base: str, headers: Dict, config: JiraGetAttachmentMetadataConfig
    ) -> Dict[str, Any]:
        """Get metadata for an attachment"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/attachment/{config.attachment_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_attachment_metadata", "id": result.get("id")}
            )
            return result

    async def _download_attachment(
        self,
        api_base: str,
        headers: Dict,
        config: JiraDownloadAttachmentConfig,
        credentials: JiraCredential,
    ) -> Dict[str, Any]:
        """Download an attachment and return a stored file reference"""
        import mimetypes
        from urllib.parse import unquote, urlparse

        from nodes.core.binary_output import BinaryOutput

        parsed_base = httpx.URL(api_base)
        port = parsed_base.port
        origin = f"{parsed_base.scheme}://{parsed_base.host}"
        if port and not (parsed_base.scheme == "https" and port == 443):
            origin = f"{origin}:{port}"
        allowed_origins = [origin]
        if isinstance(credentials, JiraOAuthCredential) and credentials.site_url:
            tenant = normalize_provider_subdomain(
                credentials.site_url,
                "atlassian.net",
                field_name="Jira site URL",
            )
            allowed_origins.append(f"https://{tenant}.atlassian.net")

        # Metadata URLs may contain arbitrary paths/query signatures, but the
        # credentialed hop must stay on the OAuth API origin or the exact Jira
        # tenant attached to this credential.
        for allowed_origin in allowed_origins:
            try:
                assert_exact_url_origin(config.attachment_url, allowed_origin)
            except SSRFError:
                continue
            break
        else:
            raise SSRFError("Refusing Jira credentials outside the credential origins")

        async with guarded_async_client() as client:
            response = await client.get(
                config.attachment_url,
                headers=headers,
                follow_redirects=False,
            )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise ValueError("Jira attachment redirect did not include a location")
            storage_url = str(response.url.join(location))
            # Signed object-storage URLs authenticate themselves. A fresh
            # client follows the complete storage redirect chain without ever
            # carrying the Jira Authorization header.
            async with guarded_async_client(follow_redirects=True) as storage_client:
                response = await storage_client.get(storage_url)
        response.raise_for_status()

        content_type = response.headers.get("content-type") or "application/octet-stream"
        filename = unquote(urlparse(config.attachment_url).path.rsplit("/", 1)[-1])
        if not filename:
            ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
            filename = f"attachment{ext}"

        await self.emit(
            {"action": "download_attachment", "size": len(response.content)}
        )
        return {
            "content": BinaryOutput(
                data=response.content,
                content_type=content_type,
                filename=filename,
            )
        }

    async def _delete_attachment(
        self, api_base: str, headers: Dict, config: JiraDeleteAttachmentConfig
    ) -> Dict[str, Any]:
        """Delete an attachment"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/attachment/{config.attachment_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit({"action": "delete_attachment", "id": config.attachment_id})
            return {
                "success": True,
                "attachment_id": config.attachment_id,
                "deleted": True,
            }

    async def _add_attachment(
        self, api_base: str, headers: Dict, config: JiraAddAttachmentConfig
    ) -> Dict[str, Any]:
        """Add attachment to an issue"""
        from nodes.core.media_resolver import resolve_media_input

        resolved = await resolve_media_input(config.file_content)
        file_bytes = resolved.data
        filename = config.filename or resolved.filename

        # Prepare multipart upload - note we need to remove Content-Type from headers
        # as httpx will set it automatically for multipart
        upload_headers = {
            k: v for k, v in headers.items() if k.lower() != "content-type"
        }
        upload_headers["X-Atlassian-Token"] = "no-check"  # Required for file uploads

        files = {"file": (filename, file_bytes)}

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue/{config.issue_key}/attachments",
                headers=upload_headers,
                files=files,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "add_attachment_to_issue", "issue_key": config.issue_key}
            )
            return {"attachments": result}

    async def _get_attachments_for_issue(
        self, api_base: str, headers: Dict, config: JiraGetAttachmentsForIssueConfig
    ) -> Dict[str, Any]:
        """Get all attachments for an issue"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}",
                headers=headers,
                params={"fields": "attachment"},
            )
            response.raise_for_status()
            result = response.json()
            attachments = result.get("fields", {}).get("attachment", [])
            await self.emit(
                {"action": "list_issue_attachments", "count": len(attachments)}
            )
            return {"attachments": attachments}

    async def _expand_attachment_for_humans(
        self, api_base: str, headers: Dict, config: JiraExpandAttachmentForHumansConfig
    ) -> Dict[str, Any]:
        """Get attachment with expanded human-readable data"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/attachment/{config.attachment_id}/expand/human",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_attachment_human_readable", "id": result.get("id")}
            )
            return result

    # --- Worklog Operations ---

    async def _add_worklog(
        self, api_base: str, headers: Dict, config: JiraAddWorklogConfig
    ) -> Dict[str, Any]:
        """Add worklog to an issue"""
        payload: Dict[str, Any] = {"timeSpent": config.time_spent}

        if config.comment:
            payload["comment"] = self._format_description(config.comment)

        if config.started:
            payload["started"] = config.started

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue/{config.issue_key}/worklog",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "add_worklog_to_issue", "issue_key": config.issue_key}
            )
            return result

    async def _get_worklog(
        self, api_base: str, headers: Dict, config: JiraGetWorklogConfig
    ) -> Dict[str, Any]:
        """Get a specific worklog"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/worklog/{config.worklog_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_worklog", "id": result.get("id")})
            return result

    async def _update_worklog(
        self, api_base: str, headers: Dict, config: JiraUpdateWorklogConfig
    ) -> Dict[str, Any]:
        """Update an existing worklog"""
        payload: Dict[str, Any] = {}

        if config.time_spent:
            payload["timeSpent"] = config.time_spent
        if config.comment:
            payload["comment"] = self._format_description(config.comment)
        if config.started:
            payload["started"] = config.started

        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issue/{config.issue_key}/worklog/{config.worklog_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "update_worklog", "id": result.get("id")})
            return result

    async def _delete_worklog(
        self, api_base: str, headers: Dict, config: JiraDeleteWorklogConfig
    ) -> Dict[str, Any]:
        """Delete a worklog"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issue/{config.issue_key}/worklog/{config.worklog_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit({"action": "delete_worklog", "id": config.worklog_id})
            return {"success": True, "worklog_id": config.worklog_id, "deleted": True}

    async def _get_issue_worklogs(
        self, api_base: str, headers: Dict, config: JiraGetIssueWorklogsConfig
    ) -> Dict[str, Any]:
        """Get all worklogs for an issue"""
        params = {"maxResults": config.max_results or 1000}

        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/worklog",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            worklogs = result.get("worklogs", [])
            await self.emit({"action": "list_issue_worklogs", "count": len(worklogs)})
            return result

    async def _get_deleted_worklogs(
        self, api_base: str, headers: Dict, config: JiraGetDeletedWorklogsConfig
    ) -> Dict[str, Any]:
        """Get list of IDs for deleted worklogs since a timestamp"""
        params = {}
        if config.since:
            params["since"] = config.since

        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/worklog/deleted",
                headers=headers,
                params=params if params else None,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_deleted_worklog_ids",
                    "count": len(result.get("values", [])),
                }
            )
            return result

    async def _get_updated_worklogs(
        self, api_base: str, headers: Dict, config: JiraGetUpdatedWorklogsConfig
    ) -> Dict[str, Any]:
        """Get list of IDs for updated worklogs since a timestamp"""
        params = {}
        if config.since:
            params["since"] = config.since
        if config.expand:
            params["expand"] = config.expand

        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/worklog/updated",
                headers=headers,
                params=params if params else None,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_updated_worklog_ids",
                    "count": len(result.get("values", [])),
                }
            )
            return result

    async def _get_worklog_property_keys(
        self, api_base: str, headers: Dict, config: JiraGetWorklogPropertyKeysConfig
    ) -> Dict[str, Any]:
        """Get all worklog property keys for a worklog"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/worklog/{config.worklog_id}/properties",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_worklog_property_keys",
                    "count": len(result.get("keys", [])),
                }
            )
            return result

    # --- Component Operations ---

    async def _create_component(
        self, api_base: str, headers: Dict, config: JiraCreateComponentConfig
    ) -> Dict[str, Any]:
        """Create a project component"""
        payload: Dict[str, Any] = {"name": config.name, "project": config.project_key}

        if config.description:
            payload["description"] = config.description
        if config.lead_account_id:
            payload["leadAccountId"] = config.lead_account_id

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/component",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "create_project_component", "id": result.get("id")}
            )
            return result

    async def _get_component(
        self, api_base: str, headers: Dict, config: JiraGetComponentConfig
    ) -> Dict[str, Any]:
        """Get a component by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/component/{config.component_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_component", "id": result.get("id")})
            return result

    async def _update_component(
        self, api_base: str, headers: Dict, config: JiraUpdateComponentConfig
    ) -> Dict[str, Any]:
        """Update a component"""
        payload: Dict[str, Any] = {}

        if config.name:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        if config.lead_account_id:
            payload["leadAccountId"] = config.lead_account_id

        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/component/{config.component_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "update_component", "id": result.get("id")})
            return result

    async def _delete_component(
        self, api_base: str, headers: Dict, config: JiraDeleteComponentConfig
    ) -> Dict[str, Any]:
        """Delete a component"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/component/{config.component_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit({"action": "delete_component", "id": config.component_id})
            return {
                "success": True,
                "component_id": config.component_id,
                "deleted": True,
            }

    async def _get_project_components(
        self, api_base: str, headers: Dict, config: JiraGetProjectComponentsConfig
    ) -> Dict[str, Any]:
        """Get all components for a project"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/project/{config.project_key}/components",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "list_project_components", "count": len(result)})
            return {"components": result}

    async def _get_component_related_issues(
        self, api_base: str, headers: Dict, config: JiraGetComponentRelatedIssuesConfig
    ) -> Dict[str, Any]:
        """Get issue count for a component"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/component/{config.component_id}/relatedIssueCounts",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_component_issue_count", "id": config.component_id}
            )
            return result

    # --- Version Operations ---

    async def _create_version(
        self, api_base: str, headers: Dict, config: JiraCreateVersionConfig
    ) -> Dict[str, Any]:
        """Create a project version"""
        payload: Dict[str, Any] = {
            "name": config.name,
            "project": config.project_key,
            "released": config.released,
            "archived": config.archived,
        }
        if config.description:
            payload["description"] = config.description
        if config.release_date:
            payload["releaseDate"] = config.release_date

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/version",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "create_project_version", "id": result.get("id")}
            )
            return result

    async def _get_version(
        self, api_base: str, headers: Dict, config: JiraGetVersionConfig
    ) -> Dict[str, Any]:
        """Get a version by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/version/{config.version_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_version", "id": result.get("id")})
            return result

    async def _update_version(
        self, api_base: str, headers: Dict, config: JiraUpdateVersionConfig
    ) -> Dict[str, Any]:
        """Update a version"""
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        if config.release_date:
            payload["releaseDate"] = config.release_date
        if config.released is not None:
            payload["released"] = config.released
        if config.archived is not None:
            payload["archived"] = config.archived

        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/version/{config.version_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "update_version", "id": result.get("id")})
            return result

    async def _delete_version(
        self, api_base: str, headers: Dict, config: JiraDeleteVersionConfig
    ) -> Dict[str, Any]:
        """Delete a version"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/version/{config.version_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit({"action": "delete_version", "id": config.version_id})
            return {"success": True, "version_id": config.version_id, "deleted": True}

    async def _get_project_versions(
        self, api_base: str, headers: Dict, config: JiraGetProjectVersionsConfig
    ) -> Dict[str, Any]:
        """Get all versions for a project"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/project/{config.project_key}/versions",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "list_project_versions", "count": len(result)})
            return {"versions": result}

    async def _merge_versions(
        self, api_base: str, headers: Dict, config: JiraMergeVersionsConfig
    ) -> Dict[str, Any]:
        """Merge two versions"""
        payload = {"moveIssuesTo": config.move_to_version_id}
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/version/{config.version_id}/mergeto/{config.move_to_version_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "merge_project_versions",
                    "from": config.version_id,
                    "to": config.move_to_version_id,
                }
            )
            if response.status_code == 204 or not response.content:
                return {
                    "success": True,
                    "from_version_id": config.version_id,
                    "to_version_id": config.move_to_version_id,
                    "merged": True,
                }
            return response.json()

    async def _move_version(
        self, api_base: str, headers: Dict, config: JiraMoveVersionConfig
    ) -> Dict[str, Any]:
        """Move version position"""
        payload = {"position": config.position}
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/version/{config.version_id}/move",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "move_version_position",
                    "id": config.version_id,
                    "position": config.position,
                }
            )
            return result

    async def _get_version_related_issues(
        self, api_base: str, headers: Dict, config: JiraGetVersionRelatedIssuesConfig
    ) -> Dict[str, Any]:
        """Get issue counts for a version"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/version/{config.version_id}/relatedIssueCounts",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_version_issue_counts", "id": config.version_id}
            )
            return result

    async def _get_version_unresolved_issues(
        self, api_base: str, headers: Dict, config: JiraGetVersionUnresolvedIssuesConfig
    ) -> Dict[str, Any]:
        """Get count of unresolved issues for a version"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/version/{config.version_id}/unresolvedIssueCount",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "get_version_unresolved_count",
                    "id": config.version_id,
                    "count": result.get("issuesUnresolvedCount", 0),
                }
            )
            return result

    # --- Issue Link Operations ---

    async def _get_issue_link(
        self, api_base: str, headers: Dict, config: JiraGetIssueLinkConfig
    ) -> Dict[str, Any]:
        """Get an issue link by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issueLink/{config.link_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_issue_link", "id": result.get("id")})
            return result

    async def _create_issue_link(
        self, api_base: str, headers: Dict, config: JiraCreateIssueLinkConfig
    ) -> Dict[str, Any]:
        """Create a link between two issues"""
        payload = {
            "type": {"name": config.link_type},
            "inwardIssue": {"key": config.inward_issue_key},
            "outwardIssue": {"key": config.outward_issue_key},
        }
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issueLink",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit({"action": "link_two_issues", "type": config.link_type})
            return {
                "success": True,
                "inward": config.inward_issue_key,
                "outward": config.outward_issue_key,
            }

    async def _delete_issue_link(
        self, api_base: str, headers: Dict, config: JiraDeleteIssueLinkConfig
    ) -> Dict[str, Any]:
        """Delete an issue link"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issueLink/{config.link_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit({"action": "delete_issue_link", "id": config.link_id})
            return {"success": True, "link_id": config.link_id, "deleted": True}

    # --- Watcher Operations ---

    async def _get_issue_watchers(
        self, api_base: str, headers: Dict, config: JiraGetIssueWatchersConfig
    ) -> Dict[str, Any]:
        """Get watchers for an issue"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/watchers",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "list_issue_watchers", "count": result.get("watchCount", 0)}
            )
            return result

    async def _add_watcher(
        self, api_base: str, headers: Dict, config: JiraAddWatcherConfig
    ) -> Dict[str, Any]:
        """Add watcher to an issue"""
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue/{config.issue_key}/watchers",
                headers=headers,
                json=config.account_id,  # Send as JSON string
            )
            response.raise_for_status()
            await self.emit(
                {"action": "add_watcher_to_issue", "issue_key": config.issue_key}
            )
            return {
                "success": True,
                "issue_key": config.issue_key,
                "account_id": config.account_id,
            }

    async def _remove_watcher(
        self, api_base: str, headers: Dict, config: JiraRemoveWatcherConfig
    ) -> Dict[str, Any]:
        """Remove watcher from an issue"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issue/{config.issue_key}/watchers",
                headers=headers,
                params={"accountId": config.account_id},
            )
            response.raise_for_status()
            await self.emit(
                {"action": "remove_watcher_from_issue", "issue_key": config.issue_key}
            )
            return {
                "success": True,
                "issue_key": config.issue_key,
                "account_id": config.account_id,
            }

    # --- Priority Operations ---

    async def _get_priorities(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get all priorities"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/priority",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "list_priorities", "count": len(result)})
            return {"priorities": result}

    async def _get_priority(
        self, api_base: str, headers: Dict, config: JiraGetPriorityConfig
    ) -> Dict[str, Any]:
        """Get a priority by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/priority/{config.priority_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_priority", "id": result.get("id")})
            return result

    # --- Resolution Operations ---

    async def _get_resolutions(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get all resolutions"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/resolution",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "list_resolutions", "count": len(result)})
            return {"resolutions": result}

    async def _get_resolution(
        self, api_base: str, headers: Dict, config: JiraGetResolutionConfig
    ) -> Dict[str, Any]:
        """Get a resolution by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/resolution/{config.resolution_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_resolution", "id": result.get("id")})
            return result

    # --- Status Operations ---

    # --- Issue Type Operations ---

    async def _get_issue_types(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get all issue types"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issuetype",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "list_issue_types", "count": len(result)})
            return {"issue_types": result}

    async def _get_issue_type(
        self, api_base: str, headers: Dict, config: JiraGetIssueTypeConfig
    ) -> Dict[str, Any]:
        """Get an issue type by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issuetype/{config.issue_type_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_issue_type", "id": result.get("id")})
            return result

    async def _get_project_issue_types(
        self, api_base: str, headers: Dict, config: JiraGetProjectIssueTypesConfig
    ) -> Dict[str, Any]:
        """Get issue types for a project"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/project/{config.project_key}",
                headers=headers,
                params={"expand": "issueTypes"},
            )
            response.raise_for_status()
            result = response.json()
            issue_types = result.get("issueTypes", [])
            await self.emit(
                {"action": "list_project_issue_types", "count": len(issue_types)}
            )
            return {"issue_types": issue_types}

    # --- Filter Operations ---

    async def _create_filter(
        self, api_base: str, headers: Dict, config: JiraCreateFilterConfig
    ) -> Dict[str, Any]:
        """Create a filter"""
        payload: Dict[str, Any] = {
            "name": config.name,
            "jql": config.jql,
            "favourite": config.favourite,
        }
        if config.description:
            payload["description"] = config.description

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/filter",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_jql_filter", "id": result.get("id")})
            return result

    async def _get_filter(
        self, api_base: str, headers: Dict, config: JiraGetFilterConfig
    ) -> Dict[str, Any]:
        """Get a filter by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/filter/{config.filter_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_filter", "id": result.get("id")})
            return result

    async def _update_filter(
        self, api_base: str, headers: Dict, config: JiraUpdateFilterConfig
    ) -> Dict[str, Any]:
        """Update a filter"""
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.jql:
            payload["jql"] = config.jql
        if config.description is not None:
            payload["description"] = config.description

        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/filter/{config.filter_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "update_filter", "id": result.get("id")})
            return result

    async def _delete_filter(
        self, api_base: str, headers: Dict, config: JiraDeleteFilterConfig
    ) -> Dict[str, Any]:
        """Delete a filter"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/filter/{config.filter_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit({"action": "delete_filter", "id": config.filter_id})
            return {"success": True, "filter_id": config.filter_id, "deleted": True}

    async def _search_filters(
        self, api_base: str, headers: Dict, config: JiraSearchFiltersConfig
    ) -> Dict[str, Any]:
        """Search for filters"""
        params = {"maxResults": config.max_results or 50}
        if config.filter_name:
            params["filterName"] = config.filter_name

        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/filter/search",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "search_filters", "count": len(result.get("values", []))}
            )
            return result

    # --- Comment Operations (additional) ---

    async def _get_comment(
        self, api_base: str, headers: Dict, config: JiraGetCommentConfig
    ) -> Dict[str, Any]:
        """Get a comment by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/comment/{config.comment_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_issue_comment", "id": result.get("id")})
            return result

    async def _get_issue_comments(
        self, api_base: str, headers: Dict, config: JiraGetIssueCommentsConfig
    ) -> Dict[str, Any]:
        """Get all comments for an issue"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/comment",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            comments = result.get("comments", [])
            await self.emit({"action": "list_issue_comments", "count": len(comments)})
            return result

    async def _update_comment(
        self, api_base: str, headers: Dict, config: JiraUpdateCommentConfig
    ) -> Dict[str, Any]:
        """Update a comment"""
        payload = {"body": self._format_description(config.body)}
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issue/{config.issue_key}/comment/{config.comment_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "update_issue_comment", "id": result.get("id")})
            return result

    async def _delete_comment(
        self, api_base: str, headers: Dict, config: JiraDeleteCommentConfig
    ) -> Dict[str, Any]:
        """Delete a comment"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issue/{config.issue_key}/comment/{config.comment_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit({"action": "delete_issue_comment", "id": config.comment_id})
            return {"success": True, "comment_id": config.comment_id, "deleted": True}

    # --- Field Operations ---

    async def _get_fields(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get all fields"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/field",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "list_fields", "count": len(result)})
            return {"fields": result}

    async def _create_custom_field(
        self, api_base: str, headers: Dict, config: JiraCreateCustomFieldConfig
    ) -> Dict[str, Any]:
        """Create a custom field"""
        payload: Dict[str, Any] = {
            "name": config.name,
            "type": config.field_type,
            "searcherKey": config.searcher_key,
        }
        if config.description:
            payload["description"] = config.description

        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/field",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_custom_field", "id": result.get("id")})
            return result

    # --- Board Operations (Jira Software) ---

    async def _get_all_boards(
        self, api_base: str, headers: Dict, config: JiraGetAllBoardsConfig
    ) -> Dict[str, Any]:
        """Get all boards"""
        # Use Jira Software API endpoint
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{agile_base}/board",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "list_boards", "count": len(result.get("values", []))}
            )
            return result

    async def _get_board(
        self, api_base: str, headers: Dict, config: JiraGetBoardConfig
    ) -> Dict[str, Any]:
        """Get board by ID"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        async with guarded_async_client() as client:
            response = await client.get(
                f"{agile_base}/board/{config.board_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_board", "board_id": config.board_id})
            return result

    async def _get_board_issues(
        self, api_base: str, headers: Dict, config: JiraGetBoardIssuesConfig
    ) -> Dict[str, Any]:
        """Get issues for a board"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        if config.jql:
            params["jql"] = config.jql
        async with guarded_async_client() as client:
            response = await client.get(
                f"{agile_base}/board/{config.board_id}/issue",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_board_issues",
                    "board_id": config.board_id,
                    "count": len(result.get("issues", [])),
                }
            )
            return result

    async def _get_board_backlog(
        self, api_base: str, headers: Dict, config: JiraGetBoardBacklogConfig
    ) -> Dict[str, Any]:
        """Get backlog issues for a board"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{agile_base}/board/{config.board_id}/backlog",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "get_board_backlog",
                    "board_id": config.board_id,
                    "count": len(result.get("issues", [])),
                }
            )
            return result

    async def _get_board_sprints(
        self, api_base: str, headers: Dict, config: JiraGetBoardSprintsConfig
    ) -> Dict[str, Any]:
        """Get sprints for a board"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        if config.state:
            params["state"] = config.state
        async with guarded_async_client() as client:
            response = await client.get(
                f"{agile_base}/board/{config.board_id}/sprint",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_board_sprints",
                    "board_id": config.board_id,
                    "count": len(result.get("values", [])),
                }
            )
            return result

    # --- Sprint Operations (Jira Software) ---

    async def _get_sprint(
        self, api_base: str, headers: Dict, config: JiraGetSprintConfig
    ) -> Dict[str, Any]:
        """Get sprint by ID"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        async with guarded_async_client() as client:
            response = await client.get(
                f"{agile_base}/sprint/{config.sprint_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_sprint", "sprint_id": config.sprint_id})
            return result

    async def _create_sprint(
        self, api_base: str, headers: Dict, config: JiraCreateSprintConfig
    ) -> Dict[str, Any]:
        """Create a new sprint"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        payload: Dict[str, Any] = {
            "name": config.name,
            "originBoardId": config.origin_board_id,
        }
        if config.goal:
            payload["goal"] = config.goal
        if config.start_date:
            payload["startDate"] = config.start_date
        if config.end_date:
            payload["endDate"] = config.end_date
        async with guarded_async_client() as client:
            response = await client.post(
                f"{agile_base}/sprint",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_sprint", "sprint_id": result.get("id")})
            return result

    async def _update_sprint(
        self, api_base: str, headers: Dict, config: JiraUpdateSprintConfig
    ) -> Dict[str, Any]:
        """Update a sprint"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.goal is not None:
            payload["goal"] = config.goal
        if config.state:
            payload["state"] = config.state
        if config.start_date:
            payload["startDate"] = config.start_date
        if config.end_date:
            payload["endDate"] = config.end_date
        async with guarded_async_client() as client:
            response = await client.put(
                f"{agile_base}/sprint/{config.sprint_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "update_sprint", "sprint_id": config.sprint_id})
            return result

    async def _delete_sprint(
        self, api_base: str, headers: Dict, config: JiraDeleteSprintConfig
    ) -> Dict[str, Any]:
        """Delete a sprint"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{agile_base}/sprint/{config.sprint_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit({"action": "delete_sprint", "sprint_id": config.sprint_id})
            return {"success": True, "sprint_id": config.sprint_id, "deleted": True}

    async def _get_sprint_issues(
        self, api_base: str, headers: Dict, config: JiraGetSprintIssuesConfig
    ) -> Dict[str, Any]:
        """Get issues for a sprint"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        if config.jql:
            params["jql"] = config.jql
        async with guarded_async_client() as client:
            response = await client.get(
                f"{agile_base}/sprint/{config.sprint_id}/issue",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_sprint_issues",
                    "sprint_id": config.sprint_id,
                    "count": len(result.get("issues", [])),
                }
            )
            return result

    async def _move_issues_to_sprint(
        self, api_base: str, headers: Dict, config: JiraMoveIssuesToSprintConfig
    ) -> Dict[str, Any]:
        """Move issues to a sprint"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        payload = {"issues": config.issue_keys}
        async with guarded_async_client() as client:
            response = await client.post(
                f"{agile_base}/sprint/{config.sprint_id}/issue",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "move_issues_to_sprint",
                    "sprint_id": config.sprint_id,
                    "count": len(config.issue_keys),
                }
            )
            return {
                "success": True,
                "sprint_id": config.sprint_id,
                "moved_count": len(config.issue_keys),
            }

    # --- Epic Operations (Jira Software) ---

    async def _get_epic(
        self, api_base: str, headers: Dict, config: JiraGetEpicConfig
    ) -> Dict[str, Any]:
        """Get epic by ID"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        async with guarded_async_client() as client:
            response = await client.get(
                f"{agile_base}/epic/{config.epic_id_or_key}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_epic", "epic_id": config.epic_id_or_key})
            return result

    async def _get_epic_issues(
        self, api_base: str, headers: Dict, config: JiraGetEpicIssuesConfig
    ) -> Dict[str, Any]:
        """Get issues for an epic"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{agile_base}/epic/{config.epic_id_or_key}/issue",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_epic_issues",
                    "epic_id": config.epic_id_or_key,
                    "count": len(result.get("issues", [])),
                }
            )
            return result

    async def _move_issues_to_epic(
        self, api_base: str, headers: Dict, config: JiraMoveIssuesToEpicConfig
    ) -> Dict[str, Any]:
        """Move issues to an epic"""
        agile_base = api_base.replace("/rest/api/3", "/rest/agile/1.0")
        payload = {"issues": config.issue_keys}
        async with guarded_async_client() as client:
            response = await client.post(
                f"{agile_base}/epic/{config.epic_id_or_key}/issue",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "move_issues_to_epic",
                    "epic_id": config.epic_id_or_key,
                    "count": len(config.issue_keys),
                }
            )
            return {
                "success": True,
                "epic_id": config.epic_id_or_key,
                "moved_count": len(config.issue_keys),
            }

    # --- Remote Link Operations ---

    async def _get_remote_links(
        self, api_base: str, headers: Dict, config: JiraGetRemoteLinksConfig
    ) -> Dict[str, Any]:
        """Get remote links for an issue"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/remotelink",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_issue_remote_links",
                    "issue_key": config.issue_key,
                    "count": len(result),
                }
            )
            return {"remote_links": result}

    async def _create_remote_link(
        self, api_base: str, headers: Dict, config: JiraCreateRemoteLinkConfig
    ) -> Dict[str, Any]:
        """Create a remote link for an issue"""
        payload: Dict[str, Any] = {"object": {"url": config.url, "title": config.title}}
        if config.summary:
            payload["object"]["summary"] = config.summary
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue/{config.issue_key}/remotelink",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "create_remote_link_on_issue",
                    "issue_key": config.issue_key,
                    "link_id": result.get("id"),
                }
            )
            return result

    async def _delete_remote_link(
        self, api_base: str, headers: Dict, config: JiraDeleteRemoteLinkConfig
    ) -> Dict[str, Any]:
        """Delete a remote link"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issue/{config.issue_key}/remotelink/{config.link_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "delete_remote_link",
                    "issue_key": config.issue_key,
                    "link_id": config.link_id,
                }
            )
            return {"success": True, "link_id": config.link_id, "deleted": True}

    # --- Label Operations ---

    async def _get_labels(
        self, api_base: str, headers: Dict, config: JiraGetLabelsConfig
    ) -> Dict[str, Any]:
        """Get all labels for an issue"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}",
                headers=headers,
                params={"fields": "labels"},
            )
            response.raise_for_status()
            result = response.json()
            labels = result.get("fields", {}).get("labels", [])
            await self.emit(
                {
                    "action": "get_issue_labels",
                    "issue_key": config.issue_key,
                    "count": len(labels),
                }
            )
            return {"labels": labels}

    async def _add_labels(
        self, api_base: str, headers: Dict, config: JiraAddLabelsConfig
    ) -> Dict[str, Any]:
        """Add labels to an issue"""
        # Get existing labels
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}",
                headers=headers,
                params={"fields": "labels"},
            )
            response.raise_for_status()
            issue_data = response.json()
            existing_labels = issue_data.get("fields", {}).get("labels", [])

            # Combine with new labels (remove duplicates)
            combined_labels = list(set(existing_labels + config.labels))

            # Update issue with combined labels
            payload = {"fields": {"labels": combined_labels}}
            response = await client.put(
                f"{api_base}/issue/{config.issue_key}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "add_labels_to_issue",
                    "issue_key": config.issue_key,
                    "added": len(config.labels),
                }
            )
            return {"success": True, "labels": combined_labels}

    async def _set_labels(
        self, api_base: str, headers: Dict, config: JiraSetLabelsConfig
    ) -> Dict[str, Any]:
        """Set labels for an issue (replaces existing)"""
        payload = {"fields": {"labels": config.labels}}
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issue/{config.issue_key}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "replace_issue_labels",
                    "issue_key": config.issue_key,
                    "count": len(config.labels),
                }
            )
            return {"success": True, "labels": config.labels}

    # --- Issue Property Operations ---

    async def _get_issue_property(
        self, api_base: str, headers: Dict, config: JiraGetIssuePropertyConfig
    ) -> Dict[str, Any]:
        """Get a property value for an issue"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/properties/{config.property_key}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "get_issue_property",
                    "issue_key": config.issue_key,
                    "property_key": config.property_key,
                }
            )
            return result

    async def _set_issue_property(
        self, api_base: str, headers: Dict, config: JiraSetIssuePropertyConfig
    ) -> Dict[str, Any]:
        """Set a property value for an issue"""
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issue/{config.issue_key}/properties/{config.property_key}",
                headers=headers,
                json=config.property_value,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "set_issue_property",
                    "issue_key": config.issue_key,
                    "property_key": config.property_key,
                }
            )
            return {"success": True, "property_key": config.property_key}

    async def _delete_issue_property(
        self, api_base: str, headers: Dict, config: JiraDeleteIssuePropertyConfig
    ) -> Dict[str, Any]:
        """Delete a property from an issue"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issue/{config.issue_key}/properties/{config.property_key}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "delete_issue_property",
                    "issue_key": config.issue_key,
                    "property_key": config.property_key,
                }
            )
            return {
                "success": True,
                "property_key": config.property_key,
                "deleted": True,
            }

    async def _get_issue_property_keys(
        self, api_base: str, headers: Dict, config: JiraGetIssuePropertyKeysConfig
    ) -> Dict[str, Any]:
        """Get all property keys for an issue"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/properties",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            keys = result.get("keys", [])
            await self.emit(
                {
                    "action": "list_issue_property_keys",
                    "issue_key": config.issue_key,
                    "count": len(keys),
                }
            )
            return result

    # --- Permission Operations ---

    async def _get_my_permissions(
        self, api_base: str, headers: Dict, config: JiraGetMyPermissionsConfig
    ) -> Dict[str, Any]:
        """Get permissions for the current user"""
        params = {"permissions": config.permissions}
        if config.project_key:
            params["projectKey"] = config.project_key
        if config.issue_key:
            params["issueKey"] = config.issue_key
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/mypermissions",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_current_user_permissions"})
            return result

    async def _get_all_permissions(
        self, api_base: str, headers: Dict
    ) -> Dict[str, Any]:
        """Get all permissions in the system"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/permissions",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            permissions = result.get("permissions", {})
            await self.emit(
                {"action": "list_all_permissions", "count": len(permissions)}
            )
            return result

    async def _check_permissions(
        self, api_base: str, headers: Dict, config: JiraCheckPermissionsConfig
    ) -> Dict[str, Any]:
        """Check if user has specific permissions"""
        params = {"permissions": ",".join(config.permissions)}
        if config.project_key:
            params["projectKey"] = config.project_key
        if config.issue_key:
            params["issueKey"] = config.issue_key
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/mypermissions",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "check_user_permissions", "checked": len(config.permissions)}
            )
            return result

    # --- Permission Scheme Operations ---

    async def _get_permission_schemes(
        self, api_base: str, headers: Dict
    ) -> Dict[str, Any]:
        """Get all permission schemes"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/permissionscheme",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            schemes = result.get("permissionSchemes", [])
            await self.emit(
                {"action": "list_permission_schemes", "count": len(schemes)}
            )
            return result

    async def _get_permission_scheme(
        self, api_base: str, headers: Dict, config: JiraGetPermissionSchemeConfig
    ) -> Dict[str, Any]:
        """Get a permission scheme by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/permissionscheme/{config.scheme_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_permission_scheme", "scheme_id": config.scheme_id}
            )
            return result

    async def _create_permission_scheme(
        self, api_base: str, headers: Dict, config: JiraCreatePermissionSchemeConfig
    ) -> Dict[str, Any]:
        """Create a new permission scheme"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.description:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/permissionscheme",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "create_permission_scheme", "scheme_id": result.get("id")}
            )
            return result

    async def _delete_permission_scheme(
        self, api_base: str, headers: Dict, config: JiraDeletePermissionSchemeConfig
    ) -> Dict[str, Any]:
        """Delete a permission scheme"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/permissionscheme/{config.scheme_id}",
                headers=headers,
            )
            response.raise_for_status()
            await self.emit(
                {"action": "delete_permission_scheme", "scheme_id": config.scheme_id}
            )
            return {"success": True, "scheme_id": config.scheme_id, "deleted": True}

    # --- Group Operations ---

    async def _get_groups(
        self, api_base: str, headers: Dict, config: JiraGetGroupsConfig
    ) -> Dict[str, Any]:
        """Get all groups"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/groups/picker",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            groups = result.get("groups", [])
            await self.emit({"action": "list_groups", "count": len(groups)})
            return result

    async def _get_group(
        self, api_base: str, headers: Dict, config: JiraGetGroupConfig
    ) -> Dict[str, Any]:
        """Get a group by name"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/group",
                headers=headers,
                params={"groupname": config.group_name},
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_group", "group_name": config.group_name})
            return result

    async def _create_group(
        self, api_base: str, headers: Dict, config: JiraCreateGroupConfig
    ) -> Dict[str, Any]:
        """Create a new group"""
        payload = {"name": config.name}
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/group",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_group", "name": config.name})
            return result

    async def _delete_group(
        self, api_base: str, headers: Dict, config: JiraDeleteGroupConfig
    ) -> Dict[str, Any]:
        """Delete a group"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/group",
                headers=headers,
                params={"groupname": config.group_name},
            )
            response.raise_for_status()
            await self.emit({"action": "delete_group", "group_name": config.group_name})
            return {"success": True, "group_name": config.group_name, "deleted": True}

    async def _add_user_to_group(
        self, api_base: str, headers: Dict, config: JiraAddUserToGroupConfig
    ) -> Dict[str, Any]:
        """Add a user to a group"""
        payload = {"accountId": config.account_id}
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/group/user",
                headers=headers,
                params={"groupname": config.group_name},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "add_user_to_group",
                    "group_name": config.group_name,
                    "account_id": config.account_id,
                }
            )
            return result

    async def _remove_user_from_group(
        self, api_base: str, headers: Dict, config: JiraRemoveUserFromGroupConfig
    ) -> Dict[str, Any]:
        """Remove a user from a group"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/group/user",
                headers=headers,
                params={"groupname": config.group_name, "accountId": config.account_id},
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "remove_user_from_group",
                    "group_name": config.group_name,
                    "account_id": config.account_id,
                }
            )
            return {
                "success": True,
                "group_name": config.group_name,
                "account_id": config.account_id,
            }

    async def _get_group_members(
        self, api_base: str, headers: Dict, config: JiraGetGroupMembersConfig
    ) -> Dict[str, Any]:
        """Get members of a group"""
        params = {"groupname": config.group_name, "maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/group/member",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            members = result.get("values", [])
            await self.emit(
                {
                    "action": "list_group_members",
                    "group_name": config.group_name,
                    "count": len(members),
                }
            )
            return result

    # --- Project Role Operations ---

    async def _get_project_roles(
        self, api_base: str, headers: Dict, config: JiraGetProjectRolesConfig
    ) -> Dict[str, Any]:
        """Get all project roles for a project"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/project/{config.project_key}/role", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "list_project_roles", "project_key": config.project_key}
            )
            return result

    async def _get_project_role(
        self, api_base: str, headers: Dict, config: JiraGetProjectRoleConfig
    ) -> Dict[str, Any]:
        """Get a specific project role"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/project/{config.project_key}/role/{config.role_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "get_project_role",
                    "project_key": config.project_key,
                    "role_id": config.role_id,
                }
            )
            return result

    async def _add_actors_to_role(
        self, api_base: str, headers: Dict, config: JiraAddActorsToRoleConfig
    ) -> Dict[str, Any]:
        """Add actors to a project role"""
        payload: Dict[str, Any] = {}
        if config.user_ids:
            payload["user"] = config.user_ids
        if config.group_names:
            payload["group"] = config.group_names
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/project/{config.project_key}/role/{config.role_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "add_actors_to_project_role",
                    "project_key": config.project_key,
                    "role_id": config.role_id,
                }
            )
            return result

    async def _remove_actors_from_role(
        self, api_base: str, headers: Dict, config: JiraRemoveActorsFromRoleConfig
    ) -> Dict[str, Any]:
        """Remove actors from a project role"""
        params = {}
        if config.user_id:
            params["user"] = config.user_id
        if config.group_name:
            params["group"] = config.group_name
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/project/{config.project_key}/role/{config.role_id}",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "remove_actors_from_project_role",
                    "project_key": config.project_key,
                    "role_id": config.role_id,
                }
            )
            return {"success": True}

    # --- Screen Operations ---

    async def _get_screens(
        self, api_base: str, headers: Dict, config: JiraGetScreensConfig
    ) -> Dict[str, Any]:
        """Get all screens"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/screens", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "list_screens", "count": len(result.get("values", []))}
            )
            return result

    async def _get_screen(
        self, api_base: str, headers: Dict, config: JiraGetScreenConfig
    ) -> Dict[str, Any]:
        """Get a screen by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/screens",
                headers=headers,
                params={"id": config.screen_id},
            )
            response.raise_for_status()
            result = response.json()
            screens = result.get("values", [])
            screen = screens[0] if screens else None
            await self.emit({"action": "get_screen", "screen_id": config.screen_id})
            return screen if screen is not None else result

    async def _get_screen_tabs(
        self, api_base: str, headers: Dict, config: JiraGetScreenTabsConfig
    ) -> Dict[str, Any]:
        """Get all tabs for a screen"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/screens/{config.screen_id}/tabs", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_screen_tabs",
                    "screen_id": config.screen_id,
                    "count": len(result),
                }
            )
            return {"tabs": result}

    async def _get_screen_fields(
        self, api_base: str, headers: Dict, config: JiraGetScreenFieldsConfig
    ) -> Dict[str, Any]:
        """Get all fields for a screen tab"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/screens/{config.screen_id}/tabs/{config.tab_id}/fields",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_screen_tab_fields",
                    "screen_id": config.screen_id,
                    "tab_id": config.tab_id,
                    "count": len(result),
                }
            )
            return {"fields": result}

    # --- Issue Security Scheme Operations ---

    async def _get_issue_security_schemes(
        self, api_base: str, headers: Dict
    ) -> Dict[str, Any]:
        """Get all issue security schemes"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issuesecurityschemes", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            schemes = result.get("issueSecuritySchemes", [])
            await self.emit(
                {"action": "list_issue_security_schemes", "count": len(schemes)}
            )
            return result

    async def _get_issue_security_scheme(
        self, api_base: str, headers: Dict, config: JiraGetIssueSecuritySchemeConfig
    ) -> Dict[str, Any]:
        """Get an issue security scheme by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issuesecurityschemes/{config.scheme_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_issue_security_scheme", "scheme_id": config.scheme_id}
            )
            return result

    # --- Notification Scheme Operations ---

    async def _get_notification_schemes(
        self, api_base: str, headers: Dict, config: JiraGetNotificationSchemesConfig
    ) -> Dict[str, Any]:
        """Get all notification schemes"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/notificationscheme", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_notification_schemes",
                    "count": len(result.get("values", [])),
                }
            )
            return result

    async def _get_notification_scheme(
        self, api_base: str, headers: Dict, config: JiraGetNotificationSchemeConfig
    ) -> Dict[str, Any]:
        """Get a notification scheme by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/notificationscheme/{config.scheme_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_notification_scheme", "scheme_id": config.scheme_id}
            )
            return result

    # --- Workflow Operations ---

    async def _get_workflows(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get all workflows"""
        async with guarded_async_client() as client:
            response = await client.get(f"{api_base}/workflow/search", headers=headers)
            response.raise_for_status()
            result = response.json()
            workflows = result.get("values", [])
            await self.emit({"action": "list_workflows", "count": len(workflows)})
            return result

    async def _get_workflow(
        self, api_base: str, headers: Dict, config: JiraGetWorkflowConfig
    ) -> Dict[str, Any]:
        """Get a workflow by name"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/workflow",
                headers=headers,
                params={"workflowName": config.workflow_name},
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_workflow", "workflow_name": config.workflow_name}
            )
            return result

    async def _get_workflow_schemes(
        self, api_base: str, headers: Dict, config: JiraGetWorkflowSchemesConfig
    ) -> Dict[str, Any]:
        """Get all workflow schemes"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/workflowscheme", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_workflow_schemes",
                    "count": len(result.get("values", [])),
                }
            )
            return result

    async def _get_workflow_scheme(
        self, api_base: str, headers: Dict, config: JiraGetWorkflowSchemeConfig
    ) -> Dict[str, Any]:
        """Get a workflow scheme by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/workflowscheme/{config.scheme_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_workflow_scheme", "scheme_id": config.scheme_id}
            )
            return result

    # --- Dashboard Operations ---

    async def _get_dashboards(
        self, api_base: str, headers: Dict, config: JiraGetDashboardsConfig
    ) -> Dict[str, Any]:
        """Get all dashboards"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/dashboard", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_dashboards",
                    "count": len(result.get("dashboards", [])),
                }
            )
            return result

    async def _get_dashboard(
        self, api_base: str, headers: Dict, config: JiraGetDashboardConfig
    ) -> Dict[str, Any]:
        """Get a dashboard by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/dashboard/{config.dashboard_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_dashboard", "dashboard_id": config.dashboard_id}
            )
            return result

    async def _create_dashboard(
        self, api_base: str, headers: Dict, config: JiraCreateDashboardConfig
    ) -> Dict[str, Any]:
        """Create a new dashboard"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.description:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/dashboard", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "create_dashboard", "dashboard_id": result.get("id")}
            )
            return result

    async def _update_dashboard(
        self, api_base: str, headers: Dict, config: JiraUpdateDashboardConfig
    ) -> Dict[str, Any]:
        """Update a dashboard"""
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/dashboard/{config.dashboard_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "update_dashboard", "dashboard_id": config.dashboard_id}
            )
            return result

    async def _delete_dashboard(
        self, api_base: str, headers: Dict, config: JiraDeleteDashboardConfig
    ) -> Dict[str, Any]:
        """Delete a dashboard"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/dashboard/{config.dashboard_id}", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {"action": "delete_dashboard", "dashboard_id": config.dashboard_id}
            )
            return {
                "success": True,
                "dashboard_id": config.dashboard_id,
                "deleted": True,
            }

    # --- Time Tracking Operations ---

    async def _get_worklog(
        self, api_base: str, headers: Dict, config: JiraGetWorklogConfig
    ) -> Dict[str, Any]:
        """Get a worklog by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/worklog/{config.worklog_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "get_worklog",
                    "issue_key": config.issue_key,
                    "worklog_id": config.worklog_id,
                }
            )
            return result

    async def _update_worklog(
        self, api_base: str, headers: Dict, config: JiraUpdateWorklogConfig
    ) -> Dict[str, Any]:
        """Update a worklog"""
        payload: Dict[str, Any] = {}
        if config.time_spent:
            payload["timeSpent"] = config.time_spent
        if config.comment:
            payload["comment"] = self._format_description(config.comment)
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issue/{config.issue_key}/worklog/{config.worklog_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "update_worklog",
                    "issue_key": config.issue_key,
                    "worklog_id": config.worklog_id,
                }
            )
            return result

    # --- Audit Log Operations ---

    async def _get_audit_records(
        self, api_base: str, headers: Dict, config: JiraGetAuditRecordsConfig
    ) -> Dict[str, Any]:
        """Get audit log records"""
        params = {"maxResults": config.max_results}
        if config.offset is not None:
            params["offset"] = config.offset
        if config.filter_text:
            params["filter"] = config.filter_text
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/auditing/record", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_audit_log", "count": len(result.get("records", []))}
            )
            return result

    # --- Advanced Search Operations ---

    async def _search_users(
        self, api_base: str, headers: Dict, config: JiraSearchUsersConfig
    ) -> Dict[str, Any]:
        """Search for users"""
        params = {"query": config.query, "maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/user/search", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "search_users", "query": config.query, "count": len(result)}
            )
            return result  # Return list directly

    async def _search_projects(
        self, api_base: str, headers: Dict, config: JiraSearchProjectsConfig
    ) -> Dict[str, Any]:
        """Search for projects"""
        params = {"maxResults": config.max_results}
        if config.query:
            params["query"] = config.query
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/project/search", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "search_projects", "count": len(result.get("values", []))}
            )
            return result

    async def _get_application_property(
        self, api_base: str, headers: Dict, config: JiraGetApplicationPropertyConfig
    ) -> Dict[str, Any]:
        """Get an application property"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/application-properties",
                headers=headers,
                params={"key": config.key},
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_application_property", "key": config.key})
            return result

    async def _get_server_info(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get Jira server information"""
        async with guarded_async_client() as client:
            response = await client.get(f"{api_base}/serverInfo", headers=headers)
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_jira_server_info"})
            return result

    # --- Issue Link Type Operations ---

    async def _get_issue_link_types(
        self, api_base: str, headers: Dict
    ) -> Dict[str, Any]:
        """Get all issue link types"""
        async with guarded_async_client() as client:
            response = await client.get(f"{api_base}/issueLinkType", headers=headers)
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_issue_link_types",
                    "count": len(result.get("issueLinkTypes", [])),
                }
            )
            return result

    async def _get_issue_link_type(
        self, api_base: str, headers: Dict, config: JiraGetIssueLinkTypeConfig
    ) -> Dict[str, Any]:
        """Get an issue link type by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issueLinkType/{config.link_type_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_issue_link_type", "link_type_id": config.link_type_id}
            )
            return result

    async def _create_issue_link_type(
        self, api_base: str, headers: Dict, config: JiraCreateIssueLinkTypeConfig
    ) -> Dict[str, Any]:
        """Create a new issue link type"""
        payload = {
            "name": config.name,
            "inward": config.inward,
            "outward": config.outward,
        }
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issueLinkType", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_issue_link_type", "name": config.name})
            return result

    async def _update_issue_link_type(
        self, api_base: str, headers: Dict, config: JiraUpdateIssueLinkTypeConfig
    ) -> Dict[str, Any]:
        """Update an issue link type"""
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.inward:
            payload["inward"] = config.inward
        if config.outward:
            payload["outward"] = config.outward
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issueLinkType/{config.link_type_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "update_issue_link_type",
                    "link_type_id": config.link_type_id,
                }
            )
            return result

    async def _delete_issue_link_type(
        self, api_base: str, headers: Dict, config: JiraDeleteIssueLinkTypeConfig
    ) -> Dict[str, Any]:
        """Delete an issue link type"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issueLinkType/{config.link_type_id}", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "delete_issue_link_type",
                    "link_type_id": config.link_type_id,
                }
            )
            return {
                "success": True,
                "link_type_id": config.link_type_id,
                "deleted": True,
            }

    # --- Field Configuration Operations ---

    async def _get_field_configurations(
        self, api_base: str, headers: Dict, config: JiraGetFieldConfigurationsConfig
    ) -> Dict[str, Any]:
        """Get all field configurations"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/fieldconfiguration", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_field_configurations",
                    "count": len(result.get("values", [])),
                }
            )
            return result

    async def _get_field_configuration(
        self, api_base: str, headers: Dict, config: JiraGetFieldConfigurationConfig
    ) -> Dict[str, Any]:
        """Get a field configuration by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/fieldconfiguration",
                headers=headers,
                params={"id": config.configuration_id},
            )
            response.raise_for_status()
            result = response.json()
            values = result.get("values", [])
            configuration = values[0] if values else None
            await self.emit(
                {
                    "action": "get_field_configuration",
                    "configuration_id": config.configuration_id,
                }
            )
            return configuration if configuration is not None else result

    async def _get_field_configuration_schemes(
        self,
        api_base: str,
        headers: Dict,
        config: JiraGetFieldConfigurationSchemesConfig,
    ) -> Dict[str, Any]:
        """Get all field configuration schemes"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/fieldconfigurationscheme", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_field_configuration_schemes",
                    "count": len(result.get("values", [])),
                }
            )
            return result

    async def _get_field_configuration_scheme(
        self,
        api_base: str,
        headers: Dict,
        config: JiraGetFieldConfigurationSchemeConfig,
    ) -> Dict[str, Any]:
        """Get a field configuration scheme by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/fieldconfigurationscheme",
                headers=headers,
                params={"id": config.scheme_id},
            )
            response.raise_for_status()
            result = response.json()
            values = result.get("values", [])
            scheme = values[0] if values else None
            await self.emit(
                {
                    "action": "get_field_configuration_scheme",
                    "scheme_id": config.scheme_id,
                }
            )
            return scheme if scheme is not None else result

    # --- Issue Type Scheme Operations ---

    async def _get_issue_type_schemes(
        self, api_base: str, headers: Dict, config: JiraGetIssueTypeSchemesConfig
    ) -> Dict[str, Any]:
        """Get all issue type schemes"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issuetypescheme", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_issue_type_schemes",
                    "count": len(result.get("values", [])),
                }
            )
            return result

    async def _get_issue_type_scheme(
        self, api_base: str, headers: Dict, config: JiraGetIssueTypeSchemeConfig
    ) -> Dict[str, Any]:
        """Get an issue type scheme by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issuetypescheme/{config.scheme_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_issue_type_scheme", "scheme_id": config.scheme_id}
            )
            return result

    async def _create_issue_type_scheme(
        self, api_base: str, headers: Dict, config: JiraCreateIssueTypeSchemeConfig
    ) -> Dict[str, Any]:
        """Create an issue type scheme"""
        payload: Dict[str, Any] = {
            "name": config.name,
            "issueTypeIds": config.issue_type_ids,
        }
        if config.description:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issuetypescheme", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_issue_type_scheme", "name": config.name})
            return result

    async def _update_issue_type_scheme(
        self, api_base: str, headers: Dict, config: JiraUpdateIssueTypeSchemeConfig
    ) -> Dict[str, Any]:
        """Update an issue type scheme"""
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issuetypescheme/{config.scheme_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {"action": "update_issue_type_scheme", "scheme_id": config.scheme_id}
            )
            if response.status_code == 204 or not response.content:
                return {
                    "success": True,
                    "scheme_id": config.scheme_id,
                    "updated": True,
                }
            return response.json()

    async def _delete_issue_type_scheme(
        self, api_base: str, headers: Dict, config: JiraDeleteIssueTypeSchemeConfig
    ) -> Dict[str, Any]:
        """Delete an issue type scheme"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issuetypescheme/{config.scheme_id}", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {"action": "delete_issue_type_scheme", "scheme_id": config.scheme_id}
            )
            return {"success": True, "scheme_id": config.scheme_id, "deleted": True}

    # --- Issue Type Screen Scheme Operations ---

    async def _get_issue_type_screen_schemes(
        self, api_base: str, headers: Dict, config: JiraGetIssueTypeScreenSchemesConfig
    ) -> Dict[str, Any]:
        """Get all issue type screen schemes"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issuetypescreenscheme", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_issue_type_screen_schemes",
                    "count": len(result.get("values", [])),
                }
            )
            return result

    async def _get_issue_type_screen_scheme(
        self, api_base: str, headers: Dict, config: JiraGetIssueTypeScreenSchemeConfig
    ) -> Dict[str, Any]:
        """Get an issue type screen scheme by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issuetypescreenscheme",
                headers=headers,
                params={"id": config.scheme_id},
            )
            response.raise_for_status()
            result = response.json()
            values = result.get("values", [])
            scheme = values[0] if values else None
            await self.emit(
                {
                    "action": "get_issue_type_screen_scheme",
                    "scheme_id": config.scheme_id,
                }
            )
            return scheme if scheme is not None else result

    # --- Priority Scheme Operations ---

    async def _get_priority_scheme(
        self, api_base: str, headers: Dict, config: JiraGetPrioritySchemeConfig
    ) -> Dict[str, Any]:
        """Get a priority scheme by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/priorityscheme",
                headers=headers,
                params={"schemeId": config.scheme_id},
            )
            response.raise_for_status()
            result = response.json()
            values = result.get("values", [])
            scheme = values[0] if values else None
            await self.emit(
                {"action": "get_priority_scheme", "scheme_id": config.scheme_id}
            )
            return scheme if scheme is not None else result

    async def _get_priority_schemes(
        self, api_base: str, headers: Dict, config: JiraGetPrioritySchemesConfig
    ) -> Dict[str, Any]:
        """Get all priority schemes"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/priorityscheme", headers=headers, params=params
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_priority_schemes",
                    "count": len(result.get("values", [])),
                }
            )
            return result

    # --- Additional Project Operations ---

    async def _archive_project(
        self, api_base: str, headers: Dict, config: JiraArchiveProjectConfig
    ) -> Dict[str, Any]:
        """Archive a project"""
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/project/{config.project_key}/archive", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {"action": "archive_project", "project_key": config.project_key}
            )
            return {
                "success": True,
                "project_key": config.project_key,
                "archived": True,
            }

    async def _restore_project(
        self, api_base: str, headers: Dict, config: JiraRestoreProjectConfig
    ) -> Dict[str, Any]:
        """Restore an archived project"""
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/project/{config.project_key}/restore", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "restore_archived_project",
                    "project_key": config.project_key,
                }
            )
            return {
                "success": True,
                "project_key": config.project_key,
                "restored": True,
            }

    async def _get_project_category(
        self, api_base: str, headers: Dict, config: JiraGetProjectCategoryConfig
    ) -> Dict[str, Any]:
        """Get a project category by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/projectCategory/{config.category_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_project_category", "category_id": config.category_id}
            )
            return result

    async def _get_all_project_categories(
        self, api_base: str, headers: Dict
    ) -> Dict[str, Any]:
        """Get all project categories"""
        async with guarded_async_client() as client:
            response = await client.get(f"{api_base}/projectCategory", headers=headers)
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "list_project_categories", "count": len(result)})
            return {"categories": result}

    async def _create_project_category(
        self, api_base: str, headers: Dict, config: JiraCreateProjectCategoryConfig
    ) -> Dict[str, Any]:
        """Create a project category"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.description:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/projectCategory", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_project_category", "name": config.name})
            return result

    async def _update_project_category(
        self, api_base: str, headers: Dict, config: JiraUpdateProjectCategoryConfig
    ) -> Dict[str, Any]:
        """Update a project category"""
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/projectCategory/{config.category_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "update_project_category", "category_id": config.category_id}
            )
            return result

    async def _delete_project_category(
        self, api_base: str, headers: Dict, config: JiraDeleteProjectCategoryConfig
    ) -> Dict[str, Any]:
        """Delete a project category"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/projectCategory/{config.category_id}", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {"action": "delete_project_category", "category_id": config.category_id}
            )
            return {"success": True, "category_id": config.category_id, "deleted": True}

    # --- Additional Issue Operations ---

    async def _assign_issue(
        self, api_base: str, headers: Dict, config: JiraAssignIssueConfig
    ) -> Dict[str, Any]:
        """Assign an issue to a user"""
        payload = (
            {"accountId": config.account_id}
            if config.account_id
            else {"accountId": None}
        )
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issue/{config.issue_key}/assignee",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {"action": "assign_issue_to_user", "issue_key": config.issue_key}
            )
            return {"success": True, "issue_key": config.issue_key}

    async def _get_issue_changelog(
        self, api_base: str, headers: Dict, config: JiraGetIssueChangelogConfig
    ) -> Dict[str, Any]:
        """Get changelog for an issue"""
        params = {"maxResults": config.max_results}
        if config.start_at is not None:
            params["startAt"] = config.start_at
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/changelog",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_issue_changelog", "issue_key": config.issue_key}
            )
            return result

    async def _notify_issue(
        self, api_base: str, headers: Dict, config: JiraNotifyIssueConfig
    ) -> Dict[str, Any]:
        """Send notification for an issue"""
        payload: Dict[str, Any] = {
            "subject": config.subject,
            "textBody": config.message,
        }
        if config.recipients:
            payload.update(config.recipients)
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue/{config.issue_key}/notify",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {"action": "send_issue_notification", "issue_key": config.issue_key}
            )
            return {"success": True}

    async def _get_issue_votes(
        self, api_base: str, headers: Dict, config: JiraGetIssueVotesConfig
    ) -> Dict[str, Any]:
        """Get votes for an issue"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issue/{config.issue_key}/votes", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_issue_votes", "issue_key": config.issue_key}
            )
            return result

    async def _add_vote(
        self, api_base: str, headers: Dict, config: JiraAddVoteConfig
    ) -> Dict[str, Any]:
        """Add vote to an issue"""
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue/{config.issue_key}/votes", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {"action": "add_vote_to_issue", "issue_key": config.issue_key}
            )
            return {"success": True}

    async def _remove_vote(
        self, api_base: str, headers: Dict, config: JiraRemoveVoteConfig
    ) -> Dict[str, Any]:
        """Remove vote from an issue"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issue/{config.issue_key}/votes", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {"action": "remove_vote_from_issue", "issue_key": config.issue_key}
            )
            return {"success": True}

    # --- Additional User Operations ---

    async def _get_user(
        self, api_base: str, headers: Dict, config: JiraGetUserConfig
    ) -> Dict[str, Any]:
        """Get a user by account ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/user",
                headers=headers,
                params={"accountId": config.account_id},
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_user", "account_id": config.account_id})
            return result

    async def _get_user_groups(
        self, api_base: str, headers: Dict, config: JiraGetUserGroupsConfig
    ) -> Dict[str, Any]:
        """Get groups that a user belongs to"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/user/groups",
                headers=headers,
                params={"accountId": config.account_id},
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "list_user_groups", "account_id": config.account_id}
            )
            return result

    async def _get_user_properties(
        self, api_base: str, headers: Dict, config: JiraGetUserPropertiesConfig
    ) -> Dict[str, Any]:
        """Get all properties for a user"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/user/properties",
                headers=headers,
                params={"accountId": config.account_id},
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "list_user_properties", "account_id": config.account_id}
            )
            return result

    async def _get_user_property(
        self, api_base: str, headers: Dict, config: JiraGetUserPropertyConfig
    ) -> Dict[str, Any]:
        """Get a property for a user"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/user/properties/{config.property_key}",
                headers=headers,
                params={"accountId": config.account_id},
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "get_user_property",
                    "account_id": config.account_id,
                    "property_key": config.property_key,
                }
            )
            return result

    async def _set_user_property(
        self, api_base: str, headers: Dict, config: JiraSetUserPropertyConfig
    ) -> Dict[str, Any]:
        """Set a property for a user"""
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/user/properties/{config.property_key}",
                headers=headers,
                params={"accountId": config.account_id},
                json=config.property_value,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "set_user_property",
                    "account_id": config.account_id,
                    "property_key": config.property_key,
                }
            )
            return {"success": True}

    async def _delete_user_property(
        self, api_base: str, headers: Dict, config: JiraDeleteUserPropertyConfig
    ) -> Dict[str, Any]:
        """Delete a property from a user"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/user/properties/{config.property_key}",
                headers=headers,
                params={"accountId": config.account_id},
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "delete_user_property",
                    "account_id": config.account_id,
                    "property_key": config.property_key,
                }
            )
            return {"success": True}

    # --- Bulk Operations ---

    async def _bulk_create_issues(
        self, api_base: str, headers: Dict, config: JiraBulkCreateIssuesConfig
    ) -> Dict[str, Any]:
        """Create multiple issues in bulk"""
        payload = {"issueUpdates": config.issues}
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issue/bulk", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "bulk_create_issues", "count": len(config.issues)}
            )
            return result

    async def _bulk_update_issues(
        self, api_base: str, headers: Dict, config: JiraBulkUpdateIssuesConfig
    ) -> Dict[str, Any]:
        """Bulk-edit fields across multiple issues (async task)"""
        payload: Dict[str, Any] = {
            "selectedIssueIdsOrKeys": config.issue_keys,
            "editedFieldsInput": config.edited_fields_input,
            "selectedActions": config.selected_actions,
        }
        if config.send_bulk_notification is not None:
            payload["sendBulkNotification"] = config.send_bulk_notification
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/bulk/issues/fields", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "bulk_update_issues", "count": len(config.issue_keys)}
            )
            return result

    async def _bulk_delete_issues(
        self, api_base: str, headers: Dict, config: JiraBulkDeleteIssuesConfig
    ) -> Dict[str, Any]:
        """Delete multiple issues in bulk (async task)"""
        payload = {"selectedIssueIdsOrKeys": config.issue_keys}
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/bulk/issues/delete", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "bulk_delete_issues", "count": len(config.issue_keys)}
            )
            return result

    # --- Avatar Operations ---

    async def _get_project_avatars(
        self, api_base: str, headers: Dict, config: JiraGetProjectAvatarsConfig
    ) -> Dict[str, Any]:
        """Get all avatars for a project"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/project/{config.project_key}/avatars", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "list_project_avatars", "project_key": config.project_key}
            )
            return result

    async def _get_issue_type_avatars(
        self, api_base: str, headers: Dict, config: JiraGetIssueTypeAvatarsConfig
    ) -> Dict[str, Any]:
        """Get all avatars for an issue type"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/universal_avatar/type/issuetype/owner/{config.issue_type_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {
                    "action": "list_issue_type_avatars",
                    "issue_type_id": config.issue_type_id,
                }
            )
            return result

    # --- Application Property Operations ---

    async def _get_application_properties(
        self, api_base: str, headers: Dict
    ) -> Dict[str, Any]:
        """Get all application properties"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/application-properties", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "list_application_properties"})
            return {"properties": result}

    async def _set_application_property(
        self, api_base: str, headers: Dict, config: JiraSetApplicationPropertyConfig
    ) -> Dict[str, Any]:
        """Set an application property"""
        payload = {"id": config.key, "value": config.value}
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/application-properties/{config.key}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit({"action": "set_application_property", "key": config.key})
            return {"success": True}

    # --- Configuration Operations ---

    async def _get_configuration(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get global configuration"""
        async with guarded_async_client() as client:
            response = await client.get(f"{api_base}/configuration", headers=headers)
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_global_configuration"})
            return result

    # --- Issue Security Level Operations ---

    async def _get_issue_security_level(
        self, api_base: str, headers: Dict, config: JiraGetIssueSecurityLevelConfig
    ) -> Dict[str, Any]:
        """Get issue security level by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/securitylevel/{config.level_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_issue_security_level", "level_id": config.level_id}
            )
            return result

    # --- Status Operations ---

    async def _get_statuses(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get all statuses"""
        async with guarded_async_client() as client:
            response = await client.get(f"{api_base}/status", headers=headers)
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "list_statuses", "count": len(result)})
            return {"statuses": result}

    async def _get_status(
        self, api_base: str, headers: Dict, config: JiraGetStatusConfig
    ) -> Dict[str, Any]:
        """Get a status by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/status/{config.status_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_status", "status_id": config.status_id})
            return result

    # Status create/update/delete only exist as bulk endpoints on /statuses
    # (there is no POST /status or PUT/DELETE /status/{id}); each takes a
    # one-element batch here.

    async def _create_status(
        self, api_base: str, headers: Dict, config: JiraCreateStatusConfig
    ) -> Dict[str, Any]:
        """Create a new status"""
        status: Dict[str, Any] = {
            "name": config.name,
            "statusCategory": config.status_category.strip().upper(),
        }
        if config.description:
            status["description"] = config.description
        payload = {"scope": {"type": "GLOBAL"}, "statuses": [status]}
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/statuses", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_status", "name": config.name})
            return result[0] if isinstance(result, list) and result else result

    async def _update_status(
        self, api_base: str, headers: Dict, config: JiraUpdateStatusConfig
    ) -> Dict[str, Any]:
        """Update a status"""
        async with guarded_async_client() as client:
            # PUT /statuses requires id, name AND statusCategory; fetch the
            # current status to fill whatever the config leaves unchanged.
            current_resp = await client.get(
                f"{api_base}/statuses",
                headers=headers,
                params={"id": config.status_id},
            )
            current_resp.raise_for_status()
            current_list = current_resp.json()
            if not current_list:
                raise ValueError(f"Status '{config.status_id}' not found")
            current = current_list[0]
            status: Dict[str, Any] = {
                "id": config.status_id,
                "name": config.name or current.get("name"),
                "statusCategory": current.get("statusCategory"),
            }
            if config.description is not None:
                status["description"] = config.description
            response = await client.put(
                f"{api_base}/statuses", headers=headers, json={"statuses": [status]}
            )
            response.raise_for_status()
            await self.emit({"action": "update_status", "status_id": config.status_id})
            return {"success": True, "status": status}

    async def _delete_status(
        self, api_base: str, headers: Dict, config: JiraDeleteStatusConfig
    ) -> Dict[str, Any]:
        """Delete a status"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/statuses",
                headers=headers,
                params={"id": config.status_id},
            )
            response.raise_for_status()
            await self.emit({"action": "delete_status", "status_id": config.status_id})
            return {"success": True, "status_id": config.status_id, "deleted": True}

    # --- Resolution Operations ---

    async def _get_resolution(
        self, api_base: str, headers: Dict, config: JiraGetResolutionConfig
    ) -> Dict[str, Any]:
        """Get a resolution by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/resolution/{config.resolution_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_resolution", "resolution_id": config.resolution_id}
            )
            return result

    async def _create_resolution(
        self, api_base: str, headers: Dict, config: JiraCreateResolutionConfig
    ) -> Dict[str, Any]:
        """Create a new resolution"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.description:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/resolution", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_resolution", "name": config.name})
            return result

    async def _update_resolution(
        self, api_base: str, headers: Dict, config: JiraUpdateResolutionConfig
    ) -> Dict[str, Any]:
        """Update a resolution"""
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/resolution/{config.resolution_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            await self.emit(
                {"action": "update_resolution", "resolution_id": config.resolution_id}
            )
            if response.status_code == 204 or not response.content:
                return {
                    "success": True,
                    "resolution_id": config.resolution_id,
                    "updated": True,
                }
            return response.json()

    async def _delete_resolution(
        self, api_base: str, headers: Dict, config: JiraDeleteResolutionConfig
    ) -> Dict[str, Any]:
        """Delete a resolution (async — Jira returns 303 to a task)"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/resolution/{config.resolution_id}",
                headers=headers,
                params={"replaceWith": config.replace_with},
            )
            # Jira runs resolution deletion asynchronously: 303 See Other with a
            # Location header pointing at the tracking task (not a real failure).
            if response.status_code not in (200, 202, 204, 303):
                response.raise_for_status()
            task_url = response.headers.get("Location")
            await self.emit(
                {"action": "delete_resolution", "resolution_id": config.resolution_id}
            )
            return {
                "success": True,
                "resolution_id": config.resolution_id,
                "deleted": True,
                "task_url": task_url,
            }

    # --- Priority Operations ---

    async def _get_priority(
        self, api_base: str, headers: Dict, config: JiraGetPriorityConfig
    ) -> Dict[str, Any]:
        """Get a priority by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/priority/{config.priority_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_priority", "priority_id": config.priority_id}
            )
            return result

    async def _create_priority(
        self, api_base: str, headers: Dict, config: JiraCreatePriorityConfig
    ) -> Dict[str, Any]:
        """Create a new priority"""
        payload: Dict[str, Any] = {"name": config.name}
        if config.description:
            payload["description"] = config.description
        if config.icon_url:
            payload["iconUrl"] = config.icon_url
        if config.status_color:
            payload["statusColor"] = config.status_color
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/priority", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_priority", "name": config.name})
            return result

    async def _update_priority(
        self, api_base: str, headers: Dict, config: JiraUpdatePriorityConfig
    ) -> Dict[str, Any]:
        """Update a priority"""
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/priority/{config.priority_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "update_priority", "priority_id": config.priority_id}
            )
            return result

    async def _delete_priority(
        self, api_base: str, headers: Dict, config: JiraDeletePriorityConfig
    ) -> Dict[str, Any]:
        """Delete a priority"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/priority/{config.priority_id}", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {"action": "delete_priority", "priority_id": config.priority_id}
            )
            return {"success": True, "priority_id": config.priority_id, "deleted": True}

    # --- Issue Type Operations ---

    async def _get_issue_type(
        self, api_base: str, headers: Dict, config: JiraGetIssueTypeConfig
    ) -> Dict[str, Any]:
        """Get an issue type by ID"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/issuetype/{config.issue_type_id}", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "get_issue_type", "issue_type_id": config.issue_type_id}
            )
            return result

    async def _create_issue_type(
        self, api_base: str, headers: Dict, config: JiraCreateIssueTypeConfig
    ) -> Dict[str, Any]:
        """Create a new issue type"""
        payload: Dict[str, Any] = {"name": config.name, "type": config.type}
        if config.description:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/issuetype", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "create_issue_type", "name": config.name})
            return result

    async def _update_issue_type(
        self, api_base: str, headers: Dict, config: JiraUpdateIssueTypeConfig
    ) -> Dict[str, Any]:
        """Update an issue type"""
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.description is not None:
            payload["description"] = config.description
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/issuetype/{config.issue_type_id}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit(
                {"action": "update_issue_type", "issue_type_id": config.issue_type_id}
            )
            return result

    async def _delete_issue_type(
        self, api_base: str, headers: Dict, config: JiraDeleteIssueTypeConfig
    ) -> Dict[str, Any]:
        """Delete an issue type"""
        async with guarded_async_client() as client:
            response = await client.delete(
                f"{api_base}/issuetype/{config.issue_type_id}", headers=headers
            )
            response.raise_for_status()
            await self.emit(
                {"action": "delete_issue_type", "issue_type_id": config.issue_type_id}
            )
            return {
                "success": True,
                "issue_type_id": config.issue_type_id,
                "deleted": True,
            }

    # --- JQL Operations ---

    async def _validate_jql(
        self, api_base: str, headers: Dict, config: JiraValidateJQLConfig
    ) -> Dict[str, Any]:
        """Validate a JQL query"""
        payload = {"queries": [config.jql]}
        async with guarded_async_client() as client:
            response = await client.post(
                f"{api_base}/jql/parse", headers=headers, json=payload
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "validate_jql_query"})
            return result

    async def _get_jql_autocomplete(
        self, api_base: str, headers: Dict, config: JiraGetJQLAutoCompleteConfig
    ) -> Dict[str, Any]:
        """Get auto-complete suggestions for JQL"""
        params = {}
        if config.field_name:
            params["fieldName"] = config.field_name
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/jql/autocompletedata",
                headers=headers,
                params=params if params else None,
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_jql_autocomplete_suggestions"})
            return result

    # --- User Preference Operations ---

    async def _get_my_preferences(
        self, api_base: str, headers: Dict, config: JiraGetMyPreferencesConfig
    ) -> Dict[str, Any]:
        """Get current user preferences"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/mypreferences",
                headers=headers,
                params={"key": config.key},
            )
            response.raise_for_status()
            await self.emit(
                {"action": "get_current_user_preferences", "key": config.key}
            )
            if response.status_code == 204 or not response.content:
                return {"key": config.key, "value": None}
            try:
                return response.json()
            except ValueError:
                return {"key": config.key, "value": response.text}

    async def _set_my_preference(
        self, api_base: str, headers: Dict, config: JiraSetMyPreferenceConfig
    ) -> Dict[str, Any]:
        """Set a user preference"""
        async with guarded_async_client() as client:
            response = await client.put(
                f"{api_base}/mypreferences?key={config.preference_key}",
                headers=headers,
                data=config.value,
            )
            response.raise_for_status()
            await self.emit(
                {
                    "action": "set_current_user_preference",
                    "preference_key": config.preference_key,
                }
            )
            return {"success": True}

    # --- License Operations ---

    async def _get_license(self, api_base: str, headers: Dict) -> Dict[str, Any]:
        """Get Jira license information"""
        async with guarded_async_client() as client:
            response = await client.get(
                f"{api_base}/application-properties", headers=headers
            )
            response.raise_for_status()
            result = response.json()
            await self.emit({"action": "get_jira_license_info"})
            return {"license": result}

    # --- Helpers ---

    def _format_description(self, text: str) -> Dict[str, Any]:
        """Format text as Atlassian Document Format (ADF)"""
        # If it looks like it's already ADF JSON, parse and return it
        if text.strip().startswith("{"):
            import json

            try:
                parsed = json.loads(text)
                if parsed.get("type") == "doc":
                    return parsed
            except json.JSONDecodeError:
                pass

        # Convert plain text to ADF
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]}
            ],
        }
