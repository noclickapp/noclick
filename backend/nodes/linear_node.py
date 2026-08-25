"""
Linear automation node.

This node provides Linear operations in workflows via Linear's GraphQL API.
Uses direct API calls to https://api.linear.app/graphql.

Supports both OAuth 2.0 and Personal API Key (PAT) authentication.
"""

import logging
import time
from typing import ClassVar, Dict, Any, Optional, Union, Literal, List, Annotated, Tuple

import httpx
from pydantic import BaseModel, Field, Discriminator, ConfigDict

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import filter_options_by_search
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.linear import LINEAR_SCOPES
from utils.webhook_signatures import verify_hmac_sha256_hex

logger = logging.getLogger(__name__)

# GraphQL API endpoint
GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"


# ============================================================================
# Webhook trigger helpers
# ============================================================================


def _linear_auth_header(credential: Dict[str, Any]) -> Optional[str]:
    """Build the Linear Authorization header from a decrypted credential.

    Personal API keys are sent raw; OAuth access tokens use a Bearer prefix.
    """
    credential = credential or {}
    api_key = credential.get("api_key")
    if api_key:
        return api_key
    token = credential.get("access_token")
    return f"Bearer {token}" if token else None


async def _linear_graphql_call(
    auth_header: str, query: str, variables: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute a Linear GraphQL request, raising on GraphQL errors."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GRAPHQL_ENDPOINT,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            raise ValueError(f"Linear API error: {data['errors']}")
        return data.get("data", {})


async def register_linear_webhook(
    auth_header: str,
    url: str,
    resource_types: List[str],
    team_id: Optional[str],
    label: str,
) -> tuple:
    """Create a Linear webhook. Returns ``(webhook_id, signing_secret)``."""
    webhook_input: Dict[str, Any] = {
        "url": url,
        "resourceTypes": resource_types or ["Issue"],
        "label": label,
    }
    if team_id:
        webhook_input["teamId"] = team_id
    else:
        webhook_input["allPublicTeams"] = True
    query = (
        "mutation($input: WebhookCreateInput!){"
        " webhookCreate(input: $input){ success webhook { id secret } } }"
    )
    data = await _linear_graphql_call(auth_header, query, {"input": webhook_input})
    webhook = (data.get("webhookCreate") or {}).get("webhook") or {}
    return webhook.get("id"), webhook.get("secret")


async def unregister_linear_webhook(auth_header: str, webhook_id: str) -> None:
    """Delete a Linear webhook."""
    query = "mutation($id: String!){ webhookDelete(id: $id){ success } }"
    await _linear_graphql_call(auth_header, query, {"id": webhook_id})


def _linear_dynamic_field(
    *,
    field_name: str,
    title: str,
    description: str,
    placeholder: str,
    default: Any = ...,
    depends_on: Optional[str] = None,
    alias: Optional[str] = None,
    resource_type: Optional[str] = None,
) -> Any:
    dynamic_options: Dict[str, Any] = {
        "field_name": field_name,
        "placeholder": placeholder,
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste a Linear ID / reference",
    }
    if depends_on:
        dynamic_options["depends_on"] = depends_on
    extra: Dict[str, Any] = {"x-dynamic-options": dynamic_options}
    if resource_type:
        extra["x-resource-type"] = resource_type
    kwargs: Dict[str, Any] = {
        "title": title,
        "description": description,
        "json_schema_extra": extra,
    }
    if alias:
        kwargs["alias"] = alias
    return Field(default, **kwargs)


def _linear_team_field(
    description: str,
    *,
    title: str = "Team ID",
    default: Any = ...,
    field_name: str = "team_id",
    alias: Optional[str] = None,
) -> Any:
    return _linear_dynamic_field(
        field_name=field_name,
        title=title,
        description=description,
        placeholder="Select a team...",
        default=default,
        alias=alias,
        resource_type="linear_team",
    )


def _linear_user_field(
    description: str,
    *,
    title: str = "User ID",
    default: Any = ...,
    alias: Optional[str] = None,
) -> Any:
    return _linear_dynamic_field(
        field_name="user_id",
        title=title,
        description=description,
        placeholder="Select a user...",
        default=default,
        alias=alias,
    )


def _linear_project_field(
    description: str,
    *,
    title: str = "Project ID",
    default: Any = ...,
    alias: Optional[str] = None,
) -> Any:
    return _linear_dynamic_field(
        field_name="project_id",
        title=title,
        description=description,
        placeholder="Select a project...",
        default=default,
        alias=alias,
        resource_type="linear_project",
    )


def _linear_issue_field(
    description: str,
    *,
    title: str = "Issue ID",
    default: Any = ...,
    alias: Optional[str] = None,
) -> Any:
    return _linear_dynamic_field(
        field_name="issue_id",
        title=title,
        description=description,
        placeholder="Select an issue...",
        default=default,
        alias=alias,
        resource_type="linear_issue",
    )


def _linear_state_field(
    description: str,
    *,
    title: str = "State ID",
    default: Any = ...,
    depends_on: str = "teamId",
) -> Any:
    return _linear_dynamic_field(
        field_name="state_id",
        title=title,
        description=description,
        placeholder="Select a workflow state...",
        default=default,
        depends_on=depends_on,
        resource_type="linear_state",
    )


def _linear_cycle_field(
    description: str,
    *,
    title: str = "Cycle ID",
    default: Any = ...,
    depends_on: str = "teamId",
) -> Any:
    return _linear_dynamic_field(
        field_name="cycle_id",
        title=title,
        description=description,
        placeholder="Select a cycle...",
        default=default,
        depends_on=depends_on,
        resource_type="linear_cycle",
    )


# ============================================================================
# Linear Credential Schema
# ============================================================================


class LinearOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Linear.
    Tokens are obtained via OAuth flow, not entered manually.
    Linear tokens are long-lived (10 years).

    Register OAuth app at: https://linear.app/settings/api
    """

    credential_type: Literal["linear_oauth"] = Field(
        "linear_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "linear",
            "x-oauth-scopes": [
                "read",
                "write",
                "issues:create",
                "comments:create",
                # Required for webhookCreate / webhookDelete (Linear trigger nodes).
                # Backend's LINEAR_DEFAULT_SCOPES also includes this; the schema
                # field here is what the frontend authorize route reads to build
                # the OAuth URL, so both must agree. Users need to reconnect Linear
                # after this lands to upgrade their token's granted scope.
                "admin",
            ],
        }
    )


class LinearPATCredential(BaseModel):
    """Personal API Key authentication for Linear.

    Get your API key at: https://linear.app/settings/api
    """

    credential_type: Literal["linear_pat"] = Field(
        "linear_pat", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Linear Personal API Key (starts with lin_api_)",
        json_schema_extra={
            "ui:widget": "password",
        },
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://linear.app/settings/api"}
    )


# Union type - OAuth shown first in UI (best UX), PAT as alternative
LinearCredential = Union[LinearOAuthCredential, LinearPATCredential]


# ============================================================================
# Linear Configuration Models (One per action)
# ============================================================================


class LinearListCommentsConfig(BaseModel):
    """List comments for a specific Linear issue"""

    model_config = ConfigDict(populate_by_name=True, title="List Comments")

    operation: Literal["list_issue_comments"] = Field(
        default="list_issue_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Comments",
            "x-keywords": [
                "issue comments",
                "comments on issue",
                "ticket replies",
                "read discussion",
            ],
        },
        title="List Issue Comments",
    )
    issueId: str = _linear_issue_field("The issue ID")


class LinearCreateCommentConfig(BaseModel):
    """Create a comment on a specific Linear issue"""

    model_config = ConfigDict(populate_by_name=True, title="Create Comment")

    operation: Literal["create_issue_comment"] = Field(
        default="create_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Create Issue Comment",
            "x-keywords": [
                "comment on issue",
                "reply to issue",
                "post comment",
                "add note",
            ],
        },
        title="Create Issue Comment",
    )
    issueId: str = _linear_issue_field("The issue ID")
    body: str = Field(
        ..., title="Body", description="The content of the comment as Markdown"
    )


class LinearListCyclesConfig(BaseModel):
    """Retrieve cycles for a specific Linear team"""

    model_config = ConfigDict(populate_by_name=True, title="List Cycles")

    operation: Literal["list_team_cycles"] = Field(
        default="list_team_cycles",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Cycle",
            "x-is-trigger": False,
            "x-display-name": "List Team Cycles",
            "x-keywords": ["team cycles", "sprints", "iterations", "cycle list"],
        },
        title="List Team Cycles",
    )
    teamId: str = _linear_team_field("The team ID")
    first: Optional[int] = Field(
        default=50, title="Limit", description="Number of results to return (max 250)"
    )


class LinearGetDocumentConfig(BaseModel):
    """Retrieve a Linear document by ID"""

    model_config = ConfigDict(populate_by_name=True, title="Get Document")

    operation: Literal["get_document"] = Field(
        default="get_document",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Get Document",
            "x-keywords": ["read doc", "fetch document", "open doc", "view document"],
        },
        title="Get Document",
    )
    id_: str = Field(..., title="ID", description="The document ID", alias="id")


class LinearListDocumentsConfig(BaseModel):
    """List documents in the user's Linear workspace"""

    model_config = ConfigDict(populate_by_name=True, title="List Documents")

    operation: Literal["list_documents"] = Field(
        default="list_documents",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "List Documents",
            "x-keywords": [
                "all documents",
                "docs list",
                "workspace docs",
                "browse documents",
            ],
        },
        title="List Documents",
    )
    first: Optional[int] = Field(
        default=50, title="Limit", description="Number of results to return (max 250)"
    )


class LinearGetIssueConfig(BaseModel):
    """Retrieve detailed information about an issue by ID"""

    model_config = ConfigDict(populate_by_name=True, title="Get Issue")

    operation: Literal["get_issue"] = Field(
        default="get_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue",
            "x-keywords": ["read issue", "fetch ticket", "open issue", "issue details"],
        },
        title="Get Issue",
    )
    id_: str = _linear_issue_field("The issue ID", title="ID", alias="id")


class LinearListIssuesConfig(BaseModel):
    """List issues in the user's Linear workspace"""

    model_config = ConfigDict(populate_by_name=True, title="List Issues")

    operation: Literal["list_issues"] = Field(
        default="list_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issues",
            "x-keywords": [
                "all issues",
                "my issues",
                "ticket list",
                "browse issues",
                "open tickets",
            ],
        },
        title="List Issues",
    )
    first: Optional[int] = Field(
        default=50, title="Limit", description="Number of results to return (max 250)"
    )
    teamId: Optional[str] = _linear_team_field("Filter by team ID", default=None)
    assigneeId: Optional[str] = _linear_user_field(
        "Filter by assignee ID", title="Assignee ID", default=None
    )
    includeArchived: Optional[bool] = Field(
        default=False,
        title="Include Archived",
        description="Whether to include archived issues",
    )


class LinearCreateIssueConfig(BaseModel):
    """Create a new Linear issue"""

    model_config = ConfigDict(populate_by_name=True, title="Create Issue")

    operation: Literal["create_issue"] = Field(
        default="create_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Create Issue",
            "x-keywords": [
                "new issue",
                "file ticket",
                "open ticket",
                "log bug",
                "raise issue",
            ],
            "x-creates-resource": True,
            "x-resource-type": "linear_issue",
            "x-resource-id-path": "data.issueCreate.issue.id",
        },
        title="Create Issue",
    )
    title: str = Field(..., title="Title", description="The issue title")
    teamId: str = _linear_team_field("The team ID")
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="The issue description as Markdown",
    )
    priority: Optional[int] = Field(
        default=None,
        title="Priority",
        description="0=No priority, 1=Urgent, 2=High, 3=Normal, 4=Low",
    )
    stateId: Optional[str] = _linear_state_field("The workflow state ID", default=None)
    assigneeId: Optional[str] = _linear_user_field(
        "The assignee user ID", title="Assignee ID", default=None
    )
    projectId: Optional[str] = _linear_project_field("The project ID", default=None)
    cycleId: Optional[str] = _linear_cycle_field("The cycle ID", default=None)
    labelIds: Optional[List[str]] = Field(
        default=None, title="Label IDs", description="Array of label IDs"
    )
    dueDate: Optional[str] = Field(
        default=None,
        title="Due Date",
        description="Due date in ISO format (YYYY-MM-DD)",
    )
    parentId: Optional[str] = _linear_issue_field(
        "Parent issue ID for sub-issues", title="Parent ID", default=None
    )


class LinearUpdateIssueConfig(BaseModel):
    """Update an existing Linear issue"""

    model_config = ConfigDict(populate_by_name=True, title="Update Issue")

    operation: Literal["update_issue"] = Field(
        default="update_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Update Issue",
            "x-keywords": [
                "edit issue",
                "change ticket",
                "reassign issue",
                "move to status",
                "set priority",
            ],
        },
        title="Update Issue",
    )
    id_: str = _linear_issue_field("The issue ID", title="ID", alias="id")
    title: Optional[str] = Field(
        default=None, title="Title", description="The issue title"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="The issue description as Markdown",
    )
    priority: Optional[int] = Field(
        default=None,
        title="Priority",
        description="0=No priority, 1=Urgent, 2=High, 3=Normal, 4=Low",
    )
    stateId: Optional[str] = _linear_state_field("The workflow state ID", default=None)
    assigneeId: Optional[str] = _linear_user_field(
        "The assignee user ID", title="Assignee ID", default=None
    )
    projectId: Optional[str] = _linear_project_field("The project ID", default=None)
    cycleId: Optional[str] = _linear_cycle_field("The cycle ID", default=None)
    labelIds: Optional[List[str]] = Field(
        default=None, title="Label IDs", description="Array of label IDs"
    )
    dueDate: Optional[str] = Field(
        default=None,
        title="Due Date",
        description="Due date in ISO format (YYYY-MM-DD)",
    )


class LinearDeleteIssueConfig(BaseModel):
    """Delete a Linear issue"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Issue")

    operation: Literal["delete_issue"] = Field(
        default="delete_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue",
            "x-keywords": ["remove issue", "erase ticket", "trash issue"],
        },
        title="Delete Issue",
    )
    id_: str = Field(..., title="ID", description="The issue ID", alias="id")


class LinearListWorkflowStatesConfig(BaseModel):
    """List workflow states (statuses) for a team"""

    model_config = ConfigDict(populate_by_name=True, title="List Workflow States")

    operation: Literal["list_team_workflow_states"] = Field(
        default="list_team_workflow_states",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "List Team Workflow States",
            "x-keywords": [
                "workflow states",
                "statuses",
                "issue statuses",
                "team statuses",
                "status columns",
            ],
        },
        title="List Team Workflow States",
    )
    teamId: str = _linear_team_field("The team ID")


class LinearListIssueLabelsConfig(BaseModel):
    """List available issue labels in a Linear workspace"""

    model_config = ConfigDict(populate_by_name=True, title="List Issue Labels")

    operation: Literal["list_issue_labels"] = Field(
        default="list_issue_labels",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Labels",
            "x-keywords": [
                "available labels",
                "all tags",
                "workspace labels",
                "browse labels",
            ],
        },
        title="List Issue Labels",
    )
    first: Optional[int] = Field(
        default=50, title="Limit", description="Number of results to return (max 250)"
    )


class LinearCreateIssueLabelConfig(BaseModel):
    """Create a new Linear issue label"""

    model_config = ConfigDict(populate_by_name=True, title="Create Issue Label")

    operation: Literal["create_issue_label"] = Field(
        default="create_issue_label",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Create Issue Label",
            "x-keywords": ["new label", "add tag", "make label"],
        },
        title="Create Issue Label",
    )
    name: str = Field(..., title="Name", description="The name of the label")
    teamId: Optional[str] = _linear_team_field(
        "Team ID for team-specific label", default=None
    )
    color: Optional[str] = Field(
        default=None, title="Color", description="Hex color code (e.g., #ff0000)"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Label description"
    )


class LinearListProjectsConfig(BaseModel):
    """List projects in the user's Linear workspace"""

    model_config = ConfigDict(populate_by_name=True, title="List Projects")

    operation: Literal["list_projects"] = Field(
        default="list_projects",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Projects",
            "x-keywords": [
                "all projects",
                "project list",
                "browse projects",
                "my projects",
            ],
        },
        title="List Projects",
    )
    first: Optional[int] = Field(
        default=50, title="Limit", description="Number of results to return (max 250)"
    )


class LinearGetProjectConfig(BaseModel):
    """Retrieve details of a specific project"""

    model_config = ConfigDict(populate_by_name=True, title="Get Project")

    operation: Literal["get_project"] = Field(
        default="get_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Get Project",
            "x-keywords": [
                "read project",
                "open project",
                "project details",
                "fetch project",
            ],
        },
        title="Get Project",
    )
    id_: str = _linear_project_field("The project ID", title="ID", alias="id")


class LinearCreateProjectConfig(BaseModel):
    """Create a new project in Linear"""

    model_config = ConfigDict(populate_by_name=True, title="Create Project")

    operation: Literal["create_project"] = Field(
        default="create_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Create Project",
            "x-keywords": ["new project", "start project", "add project"],
            "x-creates-resource": True,
            "x-resource-type": "linear_project",
            "x-resource-id-path": "data.projectCreate.project.id",
        },
        title="Create Project",
    )
    name: str = Field(..., title="Name", description="The project name")
    teamIds: List[str] = Field(
        ..., title="Team IDs", description="Array of team IDs for this project"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Project description in Markdown"
    )
    state: Optional[str] = Field(
        default=None,
        title="State",
        description="Project state (planned, started, paused, completed, canceled)",
    )
    startDate: Optional[str] = Field(
        default=None,
        title="Start Date",
        description="Start date in ISO format (YYYY-MM-DD)",
    )
    targetDate: Optional[str] = Field(
        default=None,
        title="Target Date",
        description="Target date in ISO format (YYYY-MM-DD)",
    )
    leadId: Optional[str] = _linear_user_field(
        "Project lead user ID", title="Lead ID", default=None
    )


class LinearUpdateProjectConfig(BaseModel):
    """Update an existing Linear project"""

    model_config = ConfigDict(populate_by_name=True, title="Update Project")

    operation: Literal["update_project"] = Field(
        default="update_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Update Project",
            "x-keywords": [
                "edit project",
                "change project",
                "rename project",
                "set project status",
            ],
        },
        title="Update Project",
    )
    id_: str = _linear_project_field("The project ID", title="ID", alias="id")
    name: Optional[str] = Field(
        default=None, title="Name", description="The project name"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Project description in Markdown"
    )
    state: Optional[str] = Field(
        default=None,
        title="State",
        description="Project state (planned, started, paused, completed, canceled)",
    )
    startDate: Optional[str] = Field(
        default=None,
        title="Start Date",
        description="Start date in ISO format (YYYY-MM-DD)",
    )
    targetDate: Optional[str] = Field(
        default=None,
        title="Target Date",
        description="Target date in ISO format (YYYY-MM-DD)",
    )
    leadId: Optional[str] = _linear_user_field(
        "Project lead user ID", title="Lead ID", default=None
    )


class LinearListTeamsConfig(BaseModel):
    """List teams in the user's Linear workspace"""

    model_config = ConfigDict(populate_by_name=True, title="List Teams")

    operation: Literal["list_teams"] = Field(
        default="list_teams",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "List Teams",
            "x-keywords": ["all teams", "team list", "browse teams", "workspace teams"],
        },
        title="List Teams",
    )
    first: Optional[int] = Field(
        default=50, title="Limit", description="Number of results to return (max 250)"
    )


class LinearGetTeamConfig(BaseModel):
    """Retrieve details of a specific Linear team"""

    model_config = ConfigDict(populate_by_name=True, title="Get Team")

    operation: Literal["get_team"] = Field(
        default="get_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Get Team",
            "x-keywords": ["read team", "team details", "open team", "fetch team"],
        },
        title="Get Team",
    )
    id_: str = _linear_team_field(
        "The team ID", title="ID", field_name="team_id", alias="id"
    )


class LinearListUsersConfig(BaseModel):
    """Retrieve users in the Linear workspace"""

    model_config = ConfigDict(populate_by_name=True, title="List Users")

    operation: Literal["list_users"] = Field(
        default="list_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Users",
            "x-keywords": [
                "all users",
                "members",
                "people list",
                "workspace members",
                "teammates",
            ],
        },
        title="List Users",
    )
    first: Optional[int] = Field(
        default=50, title="Limit", description="Number of results to return (max 250)"
    )


class LinearGetUserConfig(BaseModel):
    """Retrieve details of a specific Linear user"""

    model_config = ConfigDict(populate_by_name=True, title="Get User")

    operation: Literal["get_user"] = Field(
        default="get_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User",
            "x-keywords": [
                "read user",
                "member details",
                "user profile",
                "fetch person",
            ],
        },
        title="Get User",
    )
    id_: str = _linear_user_field("The user ID", title="ID", alias="id")


class LinearGetViewerConfig(BaseModel):
    """Get the currently authenticated user"""

    model_config = ConfigDict(populate_by_name=True, title="Get Viewer")

    operation: Literal["get_authenticated_user"] = Field(
        default="get_authenticated_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated User",
            "x-keywords": [
                "current user",
                "who am i",
                "my account",
                "logged in user",
                "myself",
            ],
        },
        title="Get Authenticated User",
    )


class LinearSearchIssuesConfig(BaseModel):
    """Search issues by query string"""

    model_config = ConfigDict(populate_by_name=True, title="Search Issues")

    operation: Literal["search_issues"] = Field(
        default="search_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Search Issues",
            "x-keywords": [
                "find issue",
                "search tickets",
                "query issues",
                "look up issue",
            ],
        },
        title="Search Issues",
    )
    query: str = Field(..., title="Query", description="Search query string")
    first: Optional[int] = Field(
        default=50, title="Limit", description="Number of results to return (max 250)"
    )


class LinearCreateCycleConfig(BaseModel):
    """Create a new cycle (sprint) for a team"""

    model_config = ConfigDict(populate_by_name=True, title="Create Cycle")

    operation: Literal["create_cycle"] = Field(
        default="create_cycle",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Cycle",
            "x-is-trigger": False,
            "x-display-name": "Create Cycle",
            "x-keywords": ["new sprint", "start cycle", "new iteration", "add sprint"],
            "x-creates-resource": True,
            "x-resource-type": "linear_cycle",
            "x-resource-id-path": "data.cycleCreate.cycle.id",
        },
        title="Create Cycle",
    )
    teamId: str = _linear_team_field("The team ID")
    name: Optional[str] = Field(default=None, title="Name", description="Cycle name")
    startsAt: str = Field(
        ..., title="Starts At", description="Start date in ISO format"
    )
    endsAt: str = Field(..., title="Ends At", description="End date in ISO format")
    description: Optional[str] = Field(
        default=None, title="Description", description="Cycle description"
    )


class LinearCreateDocumentConfig(BaseModel):
    """Create a new document. Requires exactly one of: projectId, teamId, or issueId."""

    model_config = ConfigDict(populate_by_name=True, title="Create Document")

    operation: Literal["create_document"] = Field(
        default="create_document",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Create Document",
            "x-keywords": ["new doc", "write document", "add doc", "make document"],
        },
        title="Create Document",
    )
    title: str = Field(..., title="Title", description="Document title")
    content: Optional[str] = Field(
        default=None, title="Content", description="Document content in Markdown"
    )
    projectId: Optional[str] = _linear_project_field(
        "Associated project ID (mutually exclusive with teamId/issueId)",
        default=None,
    )
    teamId: Optional[str] = _linear_team_field(
        "Associated team ID (mutually exclusive with projectId/issueId)",
        default=None,
    )
    issueId: Optional[str] = _linear_issue_field(
        "Associated issue ID (mutually exclusive with projectId/teamId)",
        default=None,
    )


class LinearUpdateDocumentConfig(BaseModel):
    """Update an existing document"""

    model_config = ConfigDict(populate_by_name=True, title="Update Document")

    operation: Literal["update_document"] = Field(
        default="update_document",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Update Document",
            "x-keywords": ["edit document", "change doc", "modify document"],
        },
        title="Update Document",
    )
    id_: str = Field(..., title="ID", description="The document ID", alias="id")
    title: Optional[str] = Field(
        default=None, title="Title", description="New document title"
    )
    content: Optional[str] = Field(
        default=None, title="Content", description="New document content in Markdown"
    )


class LinearDeleteDocumentConfig(BaseModel):
    """Delete a document"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Document")

    operation: Literal["delete_document"] = Field(
        default="delete_document",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Delete Document",
            "x-keywords": ["remove document", "erase doc", "trash document"],
        },
        title="Delete Document",
    )
    id_: str = Field(
        ..., title="ID", description="The document ID to delete", alias="id"
    )


class LinearUpdateCommentConfig(BaseModel):
    """Update an existing comment"""

    model_config = ConfigDict(populate_by_name=True, title="Update Comment")

    operation: Literal["update_issue_comment"] = Field(
        default="update_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Update Issue Comment",
            "x-keywords": ["edit comment", "change comment", "fix comment text"],
        },
        title="Update Issue Comment",
    )
    id_: str = Field(..., title="ID", description="The comment ID", alias="id")
    body: str = Field(
        ..., title="Body", description="Updated comment content as Markdown"
    )


class LinearDeleteCommentConfig(BaseModel):
    """Delete a comment"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Comment")

    operation: Literal["delete_issue_comment"] = Field(
        default="delete_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Comment",
            "x-keywords": ["remove comment", "erase comment", "delete reply"],
        },
        title="Delete Issue Comment",
    )
    id_: str = Field(
        ..., title="ID", description="The comment ID to delete", alias="id"
    )


class LinearArchiveIssueConfig(BaseModel):
    """Archive an issue"""

    model_config = ConfigDict(populate_by_name=True, title="Archive Issue")

    operation: Literal["archive_issue"] = Field(
        default="archive_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Archive Issue",
            "x-keywords": ["close issue", "archive ticket", "shelve issue"],
        },
        title="Archive Issue",
    )
    id_: str = Field(..., title="ID", description="The issue ID to archive", alias="id")


class LinearUnarchiveIssueConfig(BaseModel):
    """Unarchive an issue"""

    model_config = ConfigDict(populate_by_name=True, title="Unarchive Issue")

    operation: Literal["unarchive_issue"] = Field(
        default="unarchive_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Unarchive Issue",
            "x-keywords": [
                "restore issue",
                "reopen archived issue",
                "unarchive ticket",
            ],
        },
        title="Unarchive Issue",
    )
    id_: str = Field(
        ..., title="ID", description="The issue ID to unarchive", alias="id"
    )


class LinearArchiveProjectConfig(BaseModel):
    """Archive a project (soft delete)"""

    model_config = ConfigDict(populate_by_name=True, title="Archive Project")

    operation: Literal["archive_project"] = Field(
        default="archive_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Archive Project",
            "x-keywords": ["close project", "shelve project", "soft delete project"],
        },
        title="Archive Project",
    )
    id_: str = Field(
        ..., title="ID", description="The project ID to archive", alias="id"
    )


class LinearDeleteProjectConfig(BaseModel):
    """Permanently delete a project"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Project")

    operation: Literal["delete_project"] = Field(
        default="delete_project",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Delete Project",
            "x-keywords": [
                "remove project",
                "permanently delete project",
                "trash project",
            ],
        },
        title="Delete Project",
    )
    id_: str = Field(
        ..., title="ID", description="The project ID to delete", alias="id"
    )


class LinearListAttachmentsConfig(BaseModel):
    """List attachments for an issue"""

    model_config = ConfigDict(populate_by_name=True, title="List Attachments")

    operation: Literal["list_issue_attachments"] = Field(
        default="list_issue_attachments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Attachment",
            "x-is-trigger": False,
            "x-display-name": "List Issue Attachments",
            "x-keywords": [
                "issue attachments",
                "attached links",
                "see attachments",
                "files on issue",
            ],
        },
        title="List Issue Attachments",
    )
    issueId: str = _linear_issue_field("The issue ID to get attachments for")
    first: Optional[int] = Field(
        default=50, title="Limit", description="Number of results to return"
    )


class LinearCreateAttachmentConfig(BaseModel):
    """Create an attachment (link URL to issue)"""

    model_config = ConfigDict(populate_by_name=True, title="Create Attachment")

    operation: Literal["create_issue_attachment"] = Field(
        default="create_issue_attachment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Attachment",
            "x-is-trigger": False,
            "x-display-name": "Create Issue Attachment",
            "x-keywords": [
                "attach link",
                "link url to issue",
                "add attachment",
                "attach file to issue",
            ],
        },
        title="Create Issue Attachment",
    )
    issueId: str = _linear_issue_field("The issue ID to attach to")
    url: str = Field(..., title="URL", description="The URL to attach")
    title: Optional[str] = Field(
        default=None, title="Title", description="Attachment title"
    )


class LinearDeleteAttachmentConfig(BaseModel):
    """Delete an attachment"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Attachment")

    operation: Literal["delete_attachment"] = Field(
        default="delete_attachment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Attachment",
            "x-is-trigger": False,
            "x-display-name": "Delete Attachment",
            "x-keywords": ["remove attachment", "detach file", "remove attached link"],
        },
        title="Delete Attachment",
    )
    id_: str = Field(
        ..., title="ID", description="The attachment ID to delete", alias="id"
    )


class LinearListIssueRelationsConfig(BaseModel):
    """List issue relations (blocks, related, duplicate)"""

    model_config = ConfigDict(populate_by_name=True, title="List Issue Relations")

    operation: Literal["list_issue_relations"] = Field(
        default="list_issue_relations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Relations",
            "x-keywords": [
                "issue relations",
                "blocking issues",
                "related issues",
                "linked issues",
                "duplicate issues",
            ],
        },
        title="List Issue Relations",
    )
    issueId: str = _linear_issue_field("The issue ID to get relations for")


class LinearCreateIssueRelationConfig(BaseModel):
    """Create a relation between issues"""

    model_config = ConfigDict(populate_by_name=True, title="Create Issue Relation")

    operation: Literal["create_issue_relation"] = Field(
        default="create_issue_relation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Create Issue Relation",
            "x-keywords": [
                "link issues",
                "mark as blocking",
                "relate issues",
                "mark duplicate",
                "add dependency",
            ],
        },
        title="Create Issue Relation",
    )
    issueId: str = _linear_issue_field("The source issue ID")
    relatedIssueId: str = _linear_issue_field(
        "The target issue ID", title="Related Issue ID"
    )
    type: str = Field(
        ...,
        title="Relation Type",
        description="Type of relation: blocks, duplicate, related",
    )


class LinearDeleteIssueRelationConfig(BaseModel):
    """Delete an issue relation"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Issue Relation")

    operation: Literal["delete_issue_relation"] = Field(
        default="delete_issue_relation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Relation",
            "x-keywords": [
                "unlink issues",
                "remove relation",
                "remove dependency",
                "remove blocking",
            ],
        },
        title="Delete Issue Relation",
    )
    id_: str = Field(
        ..., title="ID", description="The issue relation ID to delete", alias="id"
    )


class LinearListProjectMilestonesConfig(BaseModel):
    """List milestones for a project"""

    model_config = ConfigDict(populate_by_name=True, title="List Project Milestones")

    operation: Literal["list_project_milestones"] = Field(
        default="list_project_milestones",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "List Project Milestones",
            "x-keywords": [
                "project milestones",
                "all milestones",
                "milestone list",
                "browse milestones",
            ],
        },
        title="List Project Milestones",
    )
    projectId: str = _linear_project_field("The project ID")


class LinearCreateProjectMilestoneConfig(BaseModel):
    """Create a project milestone"""

    model_config = ConfigDict(populate_by_name=True, title="Create Project Milestone")

    operation: Literal["create_project_milestone"] = Field(
        default="create_project_milestone",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Create Project Milestone",
            "x-keywords": ["new milestone", "add milestone", "set milestone"],
        },
        title="Create Project Milestone",
    )
    projectId: str = _linear_project_field("The project ID")
    name: str = Field(..., title="Name", description="Milestone name")
    description: Optional[str] = Field(
        default=None, title="Description", description="Milestone description"
    )
    targetDate: Optional[str] = Field(
        default=None, title="Target Date", description="Target date in ISO format"
    )


class LinearUpdateProjectMilestoneConfig(BaseModel):
    """Update a project milestone"""

    model_config = ConfigDict(populate_by_name=True, title="Update Project Milestone")

    operation: Literal["update_project_milestone"] = Field(
        default="update_project_milestone",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Update Project Milestone",
            "x-keywords": ["edit milestone", "change milestone", "rename milestone"],
        },
        title="Update Project Milestone",
    )
    id_: str = Field(..., title="ID", description="The milestone ID", alias="id")
    name: Optional[str] = Field(
        default=None, title="Name", description="New milestone name"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New milestone description"
    )
    targetDate: Optional[str] = Field(
        default=None, title="Target Date", description="New target date in ISO format"
    )


class LinearDeleteProjectMilestoneConfig(BaseModel):
    """Delete a project milestone"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Project Milestone")

    operation: Literal["delete_project_milestone"] = Field(
        default="delete_project_milestone",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Project",
            "x-is-trigger": False,
            "x-display-name": "Delete Project Milestone",
            "x-keywords": ["remove milestone", "erase milestone", "trash milestone"],
        },
        title="Delete Project Milestone",
    )
    id_: str = Field(
        ..., title="ID", description="The milestone ID to delete", alias="id"
    )


class LinearListWebhooksConfig(BaseModel):
    """List webhooks for the organization"""

    model_config = ConfigDict(populate_by_name=True, title="List Webhooks")

    operation: Literal["list_webhooks"] = Field(
        default="list_webhooks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Webhooks",
            "x-keywords": ["webhooks", "show webhooks", "configured callbacks"],
        },
        title="List Webhooks",
    )


class LinearCreateWebhookConfig(BaseModel):
    """Create a webhook"""

    model_config = ConfigDict(populate_by_name=True, title="Create Webhook")

    operation: Literal["create_webhook"] = Field(
        default="create_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
            "x-keywords": ["new webhook", "register callback", "setup webhook"],
        },
        title="Create Webhook",
    )
    url: str = Field(..., title="URL", description="Webhook URL to receive events")
    label: Optional[str] = Field(
        default=None, title="Label", description="Webhook label"
    )
    teamId: Optional[str] = _linear_team_field(
        "Team to filter events for", default=None
    )
    resourceTypes: Optional[List[str]] = Field(
        default=None,
        title="Resource Types",
        description="Types of resources to receive: Issue, Comment, Project, etc.",
    )


class LinearDeleteWebhookConfig(BaseModel):
    """Delete a webhook"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Webhook")

    operation: Literal["delete_webhook"] = Field(
        default="delete_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
            "x-keywords": ["remove webhook", "delete callback", "unregister webhook"],
        },
        title="Delete Webhook",
    )
    id_: str = Field(
        ..., title="ID", description="The webhook ID to delete", alias="id"
    )


class LinearUpdateCycleConfig(BaseModel):
    """Update an existing cycle"""

    model_config = ConfigDict(populate_by_name=True, title="Update Cycle")

    operation: Literal["update_cycle"] = Field(
        default="update_cycle",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Cycle",
            "x-is-trigger": False,
            "x-display-name": "Update Cycle",
            "x-keywords": ["edit sprint", "change cycle", "modify iteration"],
        },
        title="Update Cycle",
    )
    id_: str = Field(..., title="ID", description="The cycle ID", alias="id")
    name: Optional[str] = Field(
        default=None, title="Name", description="New cycle name"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New cycle description"
    )
    startsAt: Optional[str] = Field(
        default=None, title="Starts At", description="New start date in ISO format"
    )
    endsAt: Optional[str] = Field(
        default=None, title="Ends At", description="New end date in ISO format"
    )


class LinearArchiveCycleConfig(BaseModel):
    """Archive a cycle"""

    model_config = ConfigDict(populate_by_name=True, title="Archive Cycle")

    operation: Literal["archive_cycle"] = Field(
        default="archive_cycle",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Cycle",
            "x-is-trigger": False,
            "x-display-name": "Archive Cycle",
            "x-keywords": ["close sprint", "archive iteration", "finish cycle"],
        },
        title="Archive Cycle",
    )
    id_: str = Field(..., title="ID", description="The cycle ID to archive", alias="id")


class LinearDeleteIssueLabelConfig(BaseModel):
    """Delete an issue label"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Issue Label")

    operation: Literal["delete_issue_label"] = Field(
        default="delete_issue_label",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Label",
            "x-keywords": ["remove label", "erase tag", "delete label"],
        },
        title="Delete Issue Label",
    )
    id_: str = Field(..., title="ID", description="The label ID to delete", alias="id")


class LinearUpdateIssueLabelConfig(BaseModel):
    """Update an issue label"""

    model_config = ConfigDict(populate_by_name=True, title="Update Issue Label")

    operation: Literal["update_issue_label"] = Field(
        default="update_issue_label",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Update Issue Label",
            "x-keywords": ["edit label", "rename label", "change tag color"],
        },
        title="Update Issue Label",
    )
    id_: str = Field(..., title="ID", description="The label ID", alias="id")
    name: Optional[str] = Field(
        default=None, title="Name", description="New label name"
    )
    color: Optional[str] = Field(
        default=None, title="Color", description="New label color (hex)"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="New label description"
    )


# Discriminated union uses 'operation' field to determine which config type to parse
def _linear_trigger_field(value: str, display: str, keywords: Optional[list] = None):
    """Build the hidden `operation` discriminator Field for a Linear trigger."""
    extra = {
        "ui:hidden": True,
        "x-category": None,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(default=value, json_schema_extra=extra, title=display)


class _LinearEventTriggerBase(WebhookTriggerConfigBase):
    """Shared fields for Linear per-resource triggers.

    Each per-resource trigger op is a separate operation (On Issue Change, etc.)
    so the user picks the specific trigger rather than a generic resource-types
    field; the Linear ``resourceTypes`` are resolved from the operation via
    ``LinearNode._trigger_event_map``. Webhook lifecycle fields are inherited from
    WebhookTriggerConfigBase (x-requires-webhook included).
    """

    model_config = ConfigDict(populate_by_name=True)

    team_id: Optional[str] = Field(
        default=None,
        title="Team ID",
        description="Limit events to a single team (leave blank for all public teams)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team_id",
                "placeholder": "Select a team...",
                "searchable": True,
                "allow_custom": True,
            },
            "x-resource-type": "linear_team",
        },
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


class LinearOnIssueCreatedConfig(_LinearEventTriggerBase):
    """Trigger: fires when a Linear issue is created."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="On Issue Created",
        json_schema_extra={"x-requires-webhook": True},
    )

    operation: Literal["on_issue_created"] = _linear_trigger_field(
        "on_issue_created",
        "On Issue Created",
        keywords=[
            "when new issue",
            "on issue opened",
            "new ticket filed",
            "issue created event",
        ],
    )


class LinearOnIssueUpdatedConfig(_LinearEventTriggerBase):
    """Trigger: fires when a Linear issue is updated."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="On Issue Updated",
        json_schema_extra={"x-requires-webhook": True},
    )

    operation: Literal["on_issue_updated"] = _linear_trigger_field(
        "on_issue_updated",
        "On Issue Updated",
        keywords=[
            "when issue changed",
            "on issue edited",
            "issue status changed",
            "ticket updated event",
        ],
    )


class LinearOnIssueDeletedConfig(_LinearEventTriggerBase):
    """Trigger: fires when a Linear issue is deleted."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="On Issue Deleted",
        json_schema_extra={"x-requires-webhook": True},
    )

    operation: Literal["on_issue_deleted"] = _linear_trigger_field(
        "on_issue_deleted",
        "On Issue Deleted",
        keywords=["when issue removed", "on issue deleted", "ticket deleted event"],
    )


class LinearOnCommentCreatedConfig(_LinearEventTriggerBase):
    """Trigger: fires when a Linear comment is created."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="On Comment Created",
        json_schema_extra={"x-requires-webhook": True},
    )

    operation: Literal["on_comment_created"] = _linear_trigger_field(
        "on_comment_created",
        "On Comment Created",
        keywords=[
            "when new comment",
            "on comment added",
            "someone commented",
            "issue reply posted",
        ],
    )


class LinearOnCommentUpdatedConfig(_LinearEventTriggerBase):
    """Trigger: fires when a Linear comment is updated."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="On Comment Updated",
        json_schema_extra={"x-requires-webhook": True},
    )

    operation: Literal["on_comment_updated"] = _linear_trigger_field(
        "on_comment_updated",
        "On Comment Updated",
        keywords=["when comment edited", "on comment changed", "comment updated event"],
    )


class LinearOnCommentDeletedConfig(_LinearEventTriggerBase):
    """Trigger: fires when a Linear comment is deleted."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="On Comment Deleted",
        json_schema_extra={"x-requires-webhook": True},
    )

    operation: Literal["on_comment_deleted"] = _linear_trigger_field(
        "on_comment_deleted",
        "On Comment Deleted",
        keywords=[
            "when comment removed",
            "on comment deleted",
            "comment deleted event",
        ],
    )


class LinearOnProjectCreatedConfig(_LinearEventTriggerBase):
    """Trigger: fires when a Linear project is created."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="On Project Created",
        json_schema_extra={"x-requires-webhook": True},
    )

    operation: Literal["on_project_created"] = _linear_trigger_field(
        "on_project_created",
        "On Project Created",
        keywords=["when new project", "on project started", "project created event"],
    )


class LinearOnProjectUpdatedConfig(_LinearEventTriggerBase):
    """Trigger: fires when a Linear project is updated."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="On Project Updated",
        json_schema_extra={"x-requires-webhook": True},
    )

    operation: Literal["on_project_updated"] = _linear_trigger_field(
        "on_project_updated",
        "On Project Updated",
        keywords=["when project changed", "on project edited", "project updated event"],
    )


class LinearOnProjectDeletedConfig(_LinearEventTriggerBase):
    """Trigger: fires when a Linear project is deleted."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="On Project Deleted",
        json_schema_extra={"x-requires-webhook": True},
    )

    operation: Literal["on_project_deleted"] = _linear_trigger_field(
        "on_project_deleted",
        "On Project Deleted",
        keywords=[
            "when project removed",
            "on project deleted",
            "project deleted event",
        ],
    )


LinearConfig = Annotated[
    Union[
        # Trigger operations — Issues
        LinearOnIssueCreatedConfig,
        LinearOnIssueUpdatedConfig,
        LinearOnIssueDeletedConfig,
        # Trigger operations — Comments
        LinearOnCommentCreatedConfig,
        LinearOnCommentUpdatedConfig,
        LinearOnCommentDeletedConfig,
        # Trigger operations — Projects
        LinearOnProjectCreatedConfig,
        LinearOnProjectUpdatedConfig,
        LinearOnProjectDeletedConfig,
        # Comments
        LinearListCommentsConfig,
        LinearCreateCommentConfig,
        LinearUpdateCommentConfig,
        LinearDeleteCommentConfig,
        # Cycles
        LinearListCyclesConfig,
        LinearCreateCycleConfig,
        LinearUpdateCycleConfig,
        LinearArchiveCycleConfig,
        # Documents
        LinearGetDocumentConfig,
        LinearListDocumentsConfig,
        LinearCreateDocumentConfig,
        LinearUpdateDocumentConfig,
        LinearDeleteDocumentConfig,
        # Issues
        LinearGetIssueConfig,
        LinearListIssuesConfig,
        LinearCreateIssueConfig,
        LinearUpdateIssueConfig,
        LinearDeleteIssueConfig,
        LinearSearchIssuesConfig,
        LinearArchiveIssueConfig,
        LinearUnarchiveIssueConfig,
        # Workflow States
        LinearListWorkflowStatesConfig,
        # Issue Labels
        LinearListIssueLabelsConfig,
        LinearCreateIssueLabelConfig,
        LinearUpdateIssueLabelConfig,
        LinearDeleteIssueLabelConfig,
        # Projects
        LinearListProjectsConfig,
        LinearGetProjectConfig,
        LinearCreateProjectConfig,
        LinearUpdateProjectConfig,
        LinearArchiveProjectConfig,
        LinearDeleteProjectConfig,
        # Project Milestones
        LinearListProjectMilestonesConfig,
        LinearCreateProjectMilestoneConfig,
        LinearUpdateProjectMilestoneConfig,
        LinearDeleteProjectMilestoneConfig,
        # Teams
        LinearListTeamsConfig,
        LinearGetTeamConfig,
        # Users
        LinearListUsersConfig,
        LinearGetUserConfig,
        LinearGetViewerConfig,
        # Attachments
        LinearListAttachmentsConfig,
        LinearCreateAttachmentConfig,
        LinearDeleteAttachmentConfig,
        # Issue Relations
        LinearListIssueRelationsConfig,
        LinearCreateIssueRelationConfig,
        LinearDeleteIssueRelationConfig,
        # Webhooks
        LinearListWebhooksConfig,
        LinearCreateWebhookConfig,
        LinearDeleteWebhookConfig,
    ],
    Discriminator("operation"),
]


class LinearNodeConfig(NodeConfig[LinearConfig, LinearCredential]):
    """Full configuration for Linear node including credentials"""

    pass


# ============================================================================
# GraphQL Queries and Mutations
# ============================================================================

GRAPHQL_QUERIES = {
    "list_teams": """
        query ListTeams($first: Int) {
            teams(first: $first) {
                nodes {
                    id
                    name
                    key
                    description
                    createdAt
                    updatedAt
                }
            }
        }
    """,
    "get_team": """
        query GetTeam($id: String!) {
            team(id: $id) {
                id
                name
                key
                description
                createdAt
                updatedAt
            }
        }
    """,
    "list_users": """
        query ListUsers($first: Int) {
            users(first: $first) {
                nodes {
                    id
                    name
                    displayName
                    email
                    active
                    admin
                    createdAt
                }
            }
        }
    """,
    "get_user": """
        query GetUser($id: String!) {
            user(id: $id) {
                id
                name
                displayName
                email
                active
                admin
                createdAt
            }
        }
    """,
    "get_authenticated_user": """
        query GetViewer {
            viewer {
                id
                name
                displayName
                email
                active
                admin
            }
        }
    """,
    "list_issues": """
        query ListIssues($first: Int, $filter: IssueFilter) {
            issues(first: $first, filter: $filter) {
                nodes {
                    id
                    identifier
                    title
                    description
                    priority
                    priorityLabel
                    state { id name color type }
                    assignee { id name email }
                    team { id name key }
                    project { id name }
                    labels { nodes { id name color } }
                    createdAt
                    updatedAt
                    dueDate
                }
            }
        }
    """,
    "get_issue": """
        query GetIssue($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                description
                priority
                priorityLabel
                state { id name color type }
                assignee { id name email }
                team { id name key }
                project { id name }
                labels { nodes { id name color } }
                comments { nodes { id body createdAt user { id name } } }
                createdAt
                updatedAt
                dueDate
                branchName
            }
        }
    """,
    "search_issues": """
        query SearchIssues($term: String!, $first: Int) {
            searchIssues(term: $term, first: $first) {
                nodes {
                    id
                    identifier
                    title
                    description
                    state { id name }
                    team { id name }
                }
            }
        }
    """,
    "list_team_workflow_states": """
        query ListWorkflowStates($teamId: String!) {
            team(id: $teamId) {
                states {
                    nodes {
                        id
                        name
                        color
                        type
                        position
                    }
                }
            }
        }
    """,
    "list_issue_labels": """
        query ListIssueLabels($first: Int) {
            issueLabels(first: $first) {
                nodes {
                    id
                    name
                    color
                    description
                    team { id name }
                }
            }
        }
    """,
    "list_projects": """
        query ListProjects($first: Int) {
            projects(first: $first) {
                nodes {
                    id
                    name
                    description
                    state
                    progress
                    startDate
                    targetDate
                    lead { id name }
                    teams { nodes { id name } }
                    createdAt
                    updatedAt
                }
            }
        }
    """,
    "dynamic_list_projects": """
        query DynamicListProjects {
            projects {
                nodes {
                    id
                    name
                }
            }
        }
    """,
    "get_project": """
        query GetProject($id: String!) {
            project(id: $id) {
                id
                name
                description
                state
                progress
                startDate
                targetDate
                lead { id name }
                teams { nodes { id name } }
                issues { nodes { id identifier title } }
                createdAt
                updatedAt
            }
        }
    """,
    "list_documents": """
        query ListDocuments($first: Int) {
            documents(first: $first) {
                nodes {
                    id
                    title
                    content
                    project { id name }
                    creator { id name }
                    createdAt
                    updatedAt
                }
            }
        }
    """,
    "get_document": """
        query GetDocument($id: String!) {
            document(id: $id) {
                id
                title
                content
                project { id name }
                creator { id name }
                createdAt
                updatedAt
            }
        }
    """,
    "list_team_cycles": """
        query ListCycles($teamId: String!, $first: Int) {
            team(id: $teamId) {
                cycles(first: $first) {
                    nodes {
                        id
                        name
                        number
                        startsAt
                        endsAt
                        progress
                        completedAt
                    }
                }
            }
        }
    """,
    "list_issue_comments": """
        query ListComments($issueId: String!) {
            issue(id: $issueId) {
                comments {
                    nodes {
                        id
                        body
                        createdAt
                        updatedAt
                        user { id name email }
                    }
                }
            }
        }
    """,
    "list_issue_attachments": """
        query ListAttachments($issueId: String!, $first: Int) {
            issue(id: $issueId) {
                attachments(first: $first) {
                    nodes {
                        id
                        title
                        url
                        createdAt
                        creator { id name email }
                    }
                }
            }
        }
    """,
    "list_issue_relations": """
        query ListIssueRelations($issueId: String!) {
            issue(id: $issueId) {
                relations {
                    nodes {
                        id
                        type
                        relatedIssue { id identifier title }
                    }
                }
            }
        }
    """,
    "list_project_milestones": """
        query ListProjectMilestones($projectId: String!) {
            project(id: $projectId) {
                projectMilestones {
                    nodes {
                        id
                        name
                        description
                        targetDate
                        createdAt
                    }
                }
            }
        }
    """,
    "list_webhooks": """
        query ListWebhooks {
            webhooks {
                nodes {
                    id
                    label
                    url
                    enabled
                    resourceTypes
                    createdAt
                }
            }
        }
    """,
}

GRAPHQL_MUTATIONS = {
    "create_issue": """
        mutation CreateIssue($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    url
                }
            }
        }
    """,
    "update_issue": """
        mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    url
                }
            }
        }
    """,
    "delete_issue": """
        mutation DeleteIssue($id: String!) {
            issueDelete(id: $id) {
                success
            }
        }
    """,
    "create_issue_comment": """
        mutation CreateComment($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
                comment {
                    id
                    body
                    createdAt
                }
            }
        }
    """,
    "create_issue_label": """
        mutation CreateIssueLabel($input: IssueLabelCreateInput!) {
            issueLabelCreate(input: $input) {
                success
                issueLabel {
                    id
                    name
                    color
                }
            }
        }
    """,
    "create_project": """
        mutation CreateProject($input: ProjectCreateInput!) {
            projectCreate(input: $input) {
                success
                project {
                    id
                    name
                    url
                }
            }
        }
    """,
    "update_project": """
        mutation UpdateProject($id: String!, $input: ProjectUpdateInput!) {
            projectUpdate(id: $id, input: $input) {
                success
                project {
                    id
                    name
                    url
                }
            }
        }
    """,
    "create_cycle": """
        mutation CreateCycle($input: CycleCreateInput!) {
            cycleCreate(input: $input) {
                success
                cycle {
                    id
                    name
                    number
                    startsAt
                    endsAt
                }
            }
        }
    """,
    "create_document": """
        mutation CreateDocument($input: DocumentCreateInput!) {
            documentCreate(input: $input) {
                success
                document {
                    id
                    title
                }
            }
        }
    """,
    "update_document": """
        mutation UpdateDocument($id: String!, $input: DocumentUpdateInput!) {
            documentUpdate(id: $id, input: $input) {
                success
                document { id title }
            }
        }
    """,
    "delete_document": """
        mutation DeleteDocument($id: String!) {
            documentDelete(id: $id) {
                success
            }
        }
    """,
    "update_issue_comment": """
        mutation UpdateComment($id: String!, $input: CommentUpdateInput!) {
            commentUpdate(id: $id, input: $input) {
                success
                comment { id body }
            }
        }
    """,
    "delete_issue_comment": """
        mutation DeleteComment($id: String!) {
            commentDelete(id: $id) {
                success
            }
        }
    """,
    "archive_issue": """
        mutation ArchiveIssue($id: String!) {
            issueArchive(id: $id) {
                success
            }
        }
    """,
    "unarchive_issue": """
        mutation UnarchiveIssue($id: String!) {
            issueUnarchive(id: $id) {
                success
            }
        }
    """,
    "archive_project": """
        mutation ArchiveProject($id: String!) {
            projectArchive(id: $id) {
                success
            }
        }
    """,
    "delete_project": """
        mutation DeleteProject($id: String!) {
            projectDelete(id: $id) {
                success
            }
        }
    """,
    "create_issue_attachment": """
        mutation CreateAttachment($input: AttachmentCreateInput!) {
            attachmentCreate(input: $input) {
                success
                attachment { id title url }
            }
        }
    """,
    "delete_attachment": """
        mutation DeleteAttachment($id: String!) {
            attachmentDelete(id: $id) {
                success
            }
        }
    """,
    "create_issue_relation": """
        mutation CreateIssueRelation($input: IssueRelationCreateInput!) {
            issueRelationCreate(input: $input) {
                success
                issueRelation { id type }
            }
        }
    """,
    "delete_issue_relation": """
        mutation DeleteIssueRelation($id: String!) {
            issueRelationDelete(id: $id) {
                success
            }
        }
    """,
    "create_project_milestone": """
        mutation CreateProjectMilestone($input: ProjectMilestoneCreateInput!) {
            projectMilestoneCreate(input: $input) {
                success
                projectMilestone { id name targetDate }
            }
        }
    """,
    "update_project_milestone": """
        mutation UpdateProjectMilestone($id: String!, $input: ProjectMilestoneUpdateInput!) {
            projectMilestoneUpdate(id: $id, input: $input) {
                success
                projectMilestone { id name targetDate }
            }
        }
    """,
    "delete_project_milestone": """
        mutation DeleteProjectMilestone($id: String!) {
            projectMilestoneDelete(id: $id) {
                success
            }
        }
    """,
    "create_webhook": """
        mutation CreateWebhook($input: WebhookCreateInput!) {
            webhookCreate(input: $input) {
                success
                webhook { id label url enabled }
            }
        }
    """,
    "delete_webhook": """
        mutation DeleteWebhook($id: String!) {
            webhookDelete(id: $id) {
                success
            }
        }
    """,
    "update_cycle": """
        mutation UpdateCycle($id: String!, $input: CycleUpdateInput!) {
            cycleUpdate(id: $id, input: $input) {
                success
                cycle { id name startsAt endsAt }
            }
        }
    """,
    "archive_cycle": """
        mutation ArchiveCycle($id: String!) {
            cycleArchive(id: $id) {
                success
            }
        }
    """,
    "update_issue_label": """
        mutation UpdateIssueLabel($id: String!, $input: IssueLabelUpdateInput!) {
            issueLabelUpdate(id: $id, input: $input) {
                success
                issueLabel { id name color }
            }
        }
    """,
    "delete_issue_label": """
        mutation DeleteIssueLabel($id: String!) {
            issueLabelDelete(id: $id) {
                success
            }
        }
    """,
}


# ============================================================================
# Linear Node Implementation
# ============================================================================


class LinearNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """
    Linear automation node.

    Executes Linear operations via direct GraphQL API calls.
    Supports multiple actions - user selects one in the config.
    """

    edit_examples = [
        'Create a new issue in PROJ-123 titled "Fix login bug" with high priority',
        "Add a comment to issue ENG-456 summarizing the deployment results",
        'Update issue FEAT-789 status to "In Progress" and assign to Alice',
        "List all comments on issue BUG-101 and extract the latest feedback",
        'Create a new cycle named "Sprint 12" with a 2-week duration',
        'Search for all issues with label "critical" in the Infra team',
    ]

    # Maps each trigger operation to the Linear webhook ``resourceTypes`` list.
    _trigger_event_map: ClassVar[Dict[str, List[str]]] = {
        "on_issue_created": ["Issue"],
        "on_issue_updated": ["Issue"],
        "on_issue_deleted": ["Issue"],
        "on_comment_created": ["Comment"],
        "on_comment_updated": ["Comment"],
        "on_comment_deleted": ["Comment"],
        "on_project_created": ["Project"],
        "on_project_updated": ["Project"],
        "on_project_deleted": ["Project"],
    }

    # Maps operation → (Linear resource type, payload action) for webhook filtering
    _TRIGGER_FILTER_MAP: ClassVar[Dict[str, Tuple[str, str]]] = {
        "on_issue_created": ("Issue", "create"),
        "on_issue_updated": ("Issue", "update"),
        "on_issue_deleted": ("Issue", "remove"),
        "on_comment_created": ("Comment", "create"),
        "on_comment_updated": ("Comment", "update"),
        "on_comment_deleted": ("Comment", "remove"),
        "on_project_created": ("Project", "create"),
        "on_project_updated": ("Project", "update"),
        "on_project_deleted": ("Project", "remove"),
    }

    @classmethod
    def filter_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        """Filter Linear webhook by resource type + action so granular trigger ops only fire on matching events."""
        op = (config or {}).get("operation")
        match = cls._TRIGGER_FILTER_MAP.get(op)
        if match is None:
            return True
        expected_type, expected_action = match
        return (
            payload.get("type") == expected_type
            and payload.get("action") == expected_action
        )

    scope_registry = LINEAR_SCOPES
    connection_evidence = ConnectionEvidence(
        field="team_id",
        noun="teams",
    )

    @classmethod
    def get_config_model(cls):
        return LinearNodeConfig

    @classmethod
    async def _resolve_dynamic_team_id(
        cls, auth_header: str, context: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        context = context or {}
        team_id = context.get("teamId") or context.get("team_id")
        if team_id:
            return team_id

        issue_id = (
            context.get("issueId") or context.get("issue_id") or context.get("id")
        )
        if not issue_id:
            return None

        data = await _linear_graphql_call(
            auth_header, GRAPHQL_QUERIES["get_issue"], {"id": issue_id}
        )
        return (((data.get("issue") or {}).get("team")) or {}).get("id")

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic dropdown options for Linear ID-backed config fields."""
        logger.info(f"[LinearNode] load_field_options called: field={field_name}")
        auth = _linear_auth_header(credential_data or {})
        if not auth:
            raise ValueError("Connect a Linear account to load options")

        context = context or {}

        if field_name == "team_id":
            data = await _linear_graphql_call(
                auth, GRAPHQL_QUERIES["list_teams"], {"first": 250}
            )
            teams = ((data.get("teams") or {}).get("nodes")) or []
            options = [
                {
                    "value": team.get("id"),
                    "label": f"{team.get('name')} ({team.get('key')})"
                    if team.get("key")
                    else (team.get("name") or team.get("id")),
                    "metadata": {"key": team.get("key")},
                }
                for team in teams
                if team.get("id")
            ]
        elif field_name == "user_id":
            data = await _linear_graphql_call(
                auth, GRAPHQL_QUERIES["list_users"], {"first": 250}
            )
            users = ((data.get("users") or {}).get("nodes")) or []
            options = [
                {
                    "value": user.get("id"),
                    "label": user.get("displayName")
                    or user.get("name")
                    or user.get("email")
                    or user.get("id"),
                    "metadata": {"email": user.get("email")},
                }
                for user in users
                if user.get("id")
            ]
        elif field_name == "project_id":
            data = await _linear_graphql_call(
                auth, GRAPHQL_QUERIES["dynamic_list_projects"], {}
            )
            projects = ((data.get("projects") or {}).get("nodes")) or []
            options = [
                {
                    "value": project.get("id"),
                    "label": project.get("name") or project.get("id"),
                }
                for project in projects
                if project.get("id")
            ]
        elif field_name == "issue_id":
            variables: Dict[str, Any] = {"first": 250}
            team_id = context.get("teamId") or context.get("team_id")
            if team_id:
                variables["filter"] = {"team": {"id": {"eq": team_id}}}
            data = await _linear_graphql_call(
                auth, GRAPHQL_QUERIES["list_issues"], variables
            )
            issues = ((data.get("issues") or {}).get("nodes")) or []
            options = [
                {
                    "value": issue.get("id"),
                    "label": f"{issue.get('identifier')}: {issue.get('title')}"
                    if issue.get("identifier")
                    else (issue.get("title") or issue.get("id")),
                }
                for issue in issues
                if issue.get("id")
            ]
        elif field_name == "state_id":
            team_id = await cls._resolve_dynamic_team_id(auth, context)
            if not team_id:
                raise ValueError("Select a team or issue first to load workflow states")
            data = await _linear_graphql_call(
                auth,
                GRAPHQL_QUERIES["list_team_workflow_states"],
                {"teamId": team_id},
            )
            states = (
                (((data.get("team") or {}).get("states")) or {}).get("nodes")
            ) or []
            options = [
                {
                    "value": state.get("id"),
                    "label": state.get("name") or state.get("id"),
                    "metadata": {"type": state.get("type")},
                }
                for state in states
                if state.get("id")
            ]
        elif field_name == "cycle_id":
            team_id = await cls._resolve_dynamic_team_id(auth, context)
            if not team_id:
                raise ValueError("Select a team or issue first to load cycles")
            data = await _linear_graphql_call(
                auth,
                GRAPHQL_QUERIES["list_team_cycles"],
                {"teamId": team_id, "first": 250},
            )
            cycles = (
                (((data.get("team") or {}).get("cycles")) or {}).get("nodes")
            ) or []
            options = [
                {
                    "value": cycle.get("id"),
                    "label": cycle.get("name")
                    or (
                        f"Cycle {cycle.get('number')}"
                        if cycle.get("number")
                        else cycle.get("id")
                    ),
                }
                for cycle in cycles
                if cycle.get("id")
            ]
        else:
            return {"options": [], "next_page_token": None}

        return {
            "options": filter_options_by_search(
                options, search, fields=("label", "value")
            ),
            "next_page_token": None,
        }

    # ========================================================================
    # Webhook Trigger (granular issue/comment/project triggers)
    # ========================================================================

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "team_id": (config or {}).get("team_id"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ) -> Dict[str, Any]:
        auth = _linear_auth_header(credential)
        if not auth:
            raise ValueError("Linear credential is missing an API key or access token")
        resource_types = cls._trigger_event_map.get((config or {}).get("operation"), [])
        team_id = (config or {}).get("team_id")

        # webhookCreate is not idempotent — drop a stale webhook from a
        # previous registration before creating a fresh one.
        existing = (config or {}).get("external_webhook_id")
        if existing:
            try:
                await unregister_linear_webhook(auth, existing)
            except Exception as e:
                logger.warning(f"[LinearNode] Could not remove stale webhook: {e}")

        webhook_id, secret = await register_linear_webhook(
            auth, webhook_url, resource_types, team_id, "NoClick trigger"
        )
        if not secret:
            raise ValueError("Linear did not return a webhook signing secret")
        return {"signing_secret": secret, "external_webhook_id": webhook_id}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id) -> None:
        auth = _linear_auth_header(credential or {})
        webhook_id = (config or {}).get("external_webhook_id")
        if not auth or not webhook_id:
            return
        await unregister_linear_webhook(auth, webhook_id)

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Linear's ``Linear-Signature`` hex HMAC-SHA256 header."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        return verify_hmac_sha256_hex(body, secret, headers.get("linear-signature", ""))

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Linear action via GraphQL API."""
        logger.info(f"[LinearNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, LinearNodeConfig):
            raise ValueError("LinearNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                "[LinearNode] Credentials are required. "
                "Please add your credentials in the node's credentials tab."
            )

        # Get action name from config
        action = config.operation

        # Route to appropriate handler
        if action in self._trigger_event_map:
            return {
                "message": (
                    "This trigger fires when a subscribed Linear event occurs. "
                    "It outputs the Linear webhook payload."
                ),
                "resource_types": self._trigger_event_map.get(action, []),
                "team_id": config.team_id,
            }
        elif action == "list_teams":
            return await self._execute_query(
                "list_teams", {"first": config.first}, credentials
            )
        elif action == "get_team":
            return await self._execute_query(
                "get_team", {"id": config.id_}, credentials
            )
        elif action == "list_users":
            return await self._execute_query(
                "list_users", {"first": config.first}, credentials
            )
        elif action == "get_user":
            return await self._execute_query(
                "get_user", {"id": config.id_}, credentials
            )
        elif action == "get_authenticated_user":
            return await self._execute_query("get_authenticated_user", {}, credentials)
        elif action == "list_issues":
            variables = {"first": config.first}
            filter_obj = {}
            if config.teamId:
                filter_obj["team"] = {"id": {"eq": config.teamId}}
            if config.assigneeId:
                filter_obj["assignee"] = {"id": {"eq": config.assigneeId}}
            if filter_obj:
                variables["filter"] = filter_obj
            return await self._execute_query("list_issues", variables, credentials)
        elif action == "get_issue":
            return await self._execute_query(
                "get_issue", {"id": config.id_}, credentials
            )
        elif action == "search_issues":
            return await self._execute_query(
                "search_issues",
                {"term": config.query, "first": config.first},
                credentials,
            )
        elif action == "create_issue":
            input_data = {"title": config.title, "teamId": config.teamId}
            if config.description:
                input_data["description"] = config.description
            if config.priority is not None:
                input_data["priority"] = config.priority
            if config.stateId:
                input_data["stateId"] = config.stateId
            if config.assigneeId:
                input_data["assigneeId"] = config.assigneeId
            if config.projectId:
                input_data["projectId"] = config.projectId
            if config.cycleId:
                input_data["cycleId"] = config.cycleId
            if config.labelIds:
                input_data["labelIds"] = config.labelIds
            if config.dueDate:
                input_data["dueDate"] = config.dueDate
            if config.parentId:
                input_data["parentId"] = config.parentId
            return await self._execute_mutation(
                "create_issue", {"input": input_data}, credentials
            )
        elif action == "update_issue":
            input_data = {}
            if config.title:
                input_data["title"] = config.title
            if config.description is not None:
                input_data["description"] = config.description
            if config.priority is not None:
                input_data["priority"] = config.priority
            if config.stateId:
                input_data["stateId"] = config.stateId
            if config.assigneeId:
                input_data["assigneeId"] = config.assigneeId
            if config.projectId:
                input_data["projectId"] = config.projectId
            if config.cycleId:
                input_data["cycleId"] = config.cycleId
            if config.labelIds:
                input_data["labelIds"] = config.labelIds
            if config.dueDate:
                input_data["dueDate"] = config.dueDate
            return await self._execute_mutation(
                "update_issue", {"id": config.id_, "input": input_data}, credentials
            )
        elif action == "delete_issue":
            return await self._execute_mutation(
                "delete_issue", {"id": config.id_}, credentials
            )
        elif action == "list_team_workflow_states":
            return await self._execute_query(
                "list_team_workflow_states", {"teamId": config.teamId}, credentials
            )
        elif action == "list_issue_labels":
            return await self._execute_query(
                "list_issue_labels", {"first": config.first}, credentials
            )
        elif action == "create_issue_label":
            input_data = {"name": config.name}
            if config.teamId:
                input_data["teamId"] = config.teamId
            if config.color:
                input_data["color"] = config.color
            if config.description:
                input_data["description"] = config.description
            return await self._execute_mutation(
                "create_issue_label", {"input": input_data}, credentials
            )
        elif action == "list_projects":
            return await self._execute_query(
                "list_projects", {"first": config.first}, credentials
            )
        elif action == "get_project":
            return await self._execute_query(
                "get_project", {"id": config.id_}, credentials
            )
        elif action == "create_project":
            input_data = {"name": config.name, "teamIds": config.teamIds}
            if config.description:
                input_data["description"] = config.description
            if config.state:
                input_data["state"] = config.state
            if config.startDate:
                input_data["startDate"] = config.startDate
            if config.targetDate:
                input_data["targetDate"] = config.targetDate
            if config.leadId:
                input_data["leadId"] = config.leadId
            return await self._execute_mutation(
                "create_project", {"input": input_data}, credentials
            )
        elif action == "update_project":
            input_data = {}
            if config.name:
                input_data["name"] = config.name
            if config.description is not None:
                input_data["description"] = config.description
            if config.state:
                input_data["state"] = config.state
            if config.startDate:
                input_data["startDate"] = config.startDate
            if config.targetDate:
                input_data["targetDate"] = config.targetDate
            if config.leadId:
                input_data["leadId"] = config.leadId
            return await self._execute_mutation(
                "update_project", {"id": config.id_, "input": input_data}, credentials
            )
        elif action == "list_documents":
            return await self._execute_query(
                "list_documents", {"first": config.first}, credentials
            )
        elif action == "get_document":
            return await self._execute_query(
                "get_document", {"id": config.id_}, credentials
            )
        elif action == "create_document":
            input_data = {"title": config.title}
            if config.content:
                input_data["content"] = config.content
            if config.projectId:
                input_data["projectId"] = config.projectId
            if config.teamId:
                input_data["teamId"] = config.teamId
            if config.issueId:
                input_data["issueId"] = config.issueId
            return await self._execute_mutation(
                "create_document", {"input": input_data}, credentials
            )
        elif action == "list_team_cycles":
            return await self._execute_query(
                "list_team_cycles",
                {"teamId": config.teamId, "first": config.first},
                credentials,
            )
        elif action == "create_cycle":
            input_data = {
                "teamId": config.teamId,
                "startsAt": config.startsAt,
                "endsAt": config.endsAt,
            }
            if config.name:
                input_data["name"] = config.name
            if config.description:
                input_data["description"] = config.description
            return await self._execute_mutation(
                "create_cycle", {"input": input_data}, credentials
            )
        elif action == "list_issue_comments":
            return await self._execute_query(
                "list_issue_comments", {"issueId": config.issueId}, credentials
            )
        elif action == "create_issue_comment":
            input_data = {"issueId": config.issueId, "body": config.body}
            return await self._execute_mutation(
                "create_issue_comment", {"input": input_data}, credentials
            )
        elif action == "update_issue_comment":
            return await self._execute_mutation(
                "update_issue_comment",
                {"id": config.id_, "input": {"body": config.body}},
                credentials,
            )
        elif action == "delete_issue_comment":
            return await self._execute_mutation(
                "delete_issue_comment", {"id": config.id_}, credentials
            )
        # Document operations
        elif action == "update_document":
            input_data = {}
            if config.title:
                input_data["title"] = config.title
            if config.content:
                input_data["content"] = config.content
            return await self._execute_mutation(
                "update_document", {"id": config.id_, "input": input_data}, credentials
            )
        elif action == "delete_document":
            return await self._execute_mutation(
                "delete_document", {"id": config.id_}, credentials
            )
        # Issue archive/unarchive
        elif action == "archive_issue":
            return await self._execute_mutation(
                "archive_issue", {"id": config.id_}, credentials
            )
        elif action == "unarchive_issue":
            return await self._execute_mutation(
                "unarchive_issue", {"id": config.id_}, credentials
            )
        # Project archive/delete
        elif action == "archive_project":
            return await self._execute_mutation(
                "archive_project", {"id": config.id_}, credentials
            )
        elif action == "delete_project":
            return await self._execute_mutation(
                "delete_project", {"id": config.id_}, credentials
            )
        # Attachments
        elif action == "list_issue_attachments":
            return await self._execute_query(
                "list_issue_attachments",
                {"issueId": config.issueId, "first": config.first},
                credentials,
            )
        elif action == "create_issue_attachment":
            input_data = {"issueId": config.issueId, "url": config.url}
            if config.title:
                input_data["title"] = config.title
            return await self._execute_mutation(
                "create_issue_attachment", {"input": input_data}, credentials
            )
        elif action == "delete_attachment":
            return await self._execute_mutation(
                "delete_attachment", {"id": config.id_}, credentials
            )
        # Issue relations
        elif action == "list_issue_relations":
            return await self._execute_query(
                "list_issue_relations", {"issueId": config.issueId}, credentials
            )
        elif action == "create_issue_relation":
            input_data = {
                "issueId": config.issueId,
                "relatedIssueId": config.relatedIssueId,
                "type": config.type,
            }
            return await self._execute_mutation(
                "create_issue_relation", {"input": input_data}, credentials
            )
        elif action == "delete_issue_relation":
            return await self._execute_mutation(
                "delete_issue_relation", {"id": config.id_}, credentials
            )
        # Project milestones
        elif action == "list_project_milestones":
            return await self._execute_query(
                "list_project_milestones", {"projectId": config.projectId}, credentials
            )
        elif action == "create_project_milestone":
            input_data = {"projectId": config.projectId, "name": config.name}
            if config.description:
                input_data["description"] = config.description
            if config.targetDate:
                input_data["targetDate"] = config.targetDate
            return await self._execute_mutation(
                "create_project_milestone", {"input": input_data}, credentials
            )
        elif action == "update_project_milestone":
            input_data = {}
            if config.name:
                input_data["name"] = config.name
            if config.description:
                input_data["description"] = config.description
            if config.targetDate:
                input_data["targetDate"] = config.targetDate
            return await self._execute_mutation(
                "update_project_milestone",
                {"id": config.id_, "input": input_data},
                credentials,
            )
        elif action == "delete_project_milestone":
            return await self._execute_mutation(
                "delete_project_milestone", {"id": config.id_}, credentials
            )
        # Webhooks
        elif action == "list_webhooks":
            return await self._execute_query("list_webhooks", {}, credentials)
        elif action == "create_webhook":
            input_data = {"url": config.url}
            if config.label:
                input_data["label"] = config.label
            if config.teamId:
                input_data["teamId"] = config.teamId
            if config.resourceTypes:
                input_data["resourceTypes"] = config.resourceTypes
            return await self._execute_mutation(
                "create_webhook", {"input": input_data}, credentials
            )
        elif action == "delete_webhook":
            return await self._execute_mutation(
                "delete_webhook", {"id": config.id_}, credentials
            )
        # Cycle operations
        elif action == "update_cycle":
            input_data = {}
            if config.name:
                input_data["name"] = config.name
            if config.description:
                input_data["description"] = config.description
            if config.startsAt:
                input_data["startsAt"] = config.startsAt
            if config.endsAt:
                input_data["endsAt"] = config.endsAt
            return await self._execute_mutation(
                "update_cycle", {"id": config.id_, "input": input_data}, credentials
            )
        elif action == "archive_cycle":
            return await self._execute_mutation(
                "archive_cycle", {"id": config.id_}, credentials
            )
        # Issue label operations
        elif action == "update_issue_label":
            input_data = {}
            if config.name:
                input_data["name"] = config.name
            if config.color:
                input_data["color"] = config.color
            if config.description:
                input_data["description"] = config.description
            return await self._execute_mutation(
                "update_issue_label",
                {"id": config.id_, "input": input_data},
                credentials,
            )
        elif action == "delete_issue_label":
            return await self._execute_mutation(
                "delete_issue_label", {"id": config.id_}, credentials
            )
        else:
            raise ValueError(f"Unknown action: {action}")

    async def _execute_query(
        self, query_name: str, variables: Dict[str, Any], credentials: LinearCredential
    ) -> Dict[str, Any]:
        """Execute a GraphQL query."""
        query = GRAPHQL_QUERIES.get(query_name)
        if not query:
            raise ValueError(f"Unknown query: {query_name}")
        return await self._call_graphql(query_name, query, variables, credentials)

    async def _execute_mutation(
        self,
        mutation_name: str,
        variables: Dict[str, Any],
        credentials: LinearCredential,
    ) -> Dict[str, Any]:
        """Execute a GraphQL mutation."""
        mutation = GRAPHQL_MUTATIONS.get(mutation_name)
        if not mutation:
            raise ValueError(f"Unknown mutation: {mutation_name}")
        return await self._call_graphql(mutation_name, mutation, variables, credentials)

    async def _call_graphql(
        self,
        operation_name: str,
        query: str,
        variables: Dict[str, Any],
        credentials: LinearCredential,
    ) -> Dict[str, Any]:
        """Execute GraphQL request and return standardized output."""
        await self._ensure_fresh_token(credentials)
        auth_header = self._get_auth_header(credentials)

        # Remove None values from variables
        clean_variables = {k: v for k, v in variables.items() if v is not None}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GRAPHQL_ENDPOINT,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": auth_header,
                },
                json={"query": query, "variables": clean_variables},
            )

            result = response.json()

            # Check for GraphQL errors
            if "errors" in result:
                error_msg = result["errors"][0].get("message", "Unknown GraphQL error")
                output = {
                    "type": "linear",
                    "action": operation_name,
                    "status": "error",
                    "error": error_msg,
                    "data": None,
                    "timestamp": time.time(),
                }
                logger.error(f"[LinearNode] GraphQL error: {error_msg}")
            else:
                # Extract data from response
                data = result.get("data", {})
                output = {
                    "type": "linear",
                    "action": operation_name,
                    "status": "success",
                    "data": data,
                    "timestamp": time.time(),
                }
                logger.info(
                    f"[LinearNode] GraphQL operation completed: {operation_name}"
                )

            await self.emit(output)
            return output

    def _get_auth_header(self, credentials: LinearCredential) -> str:
        """Build authorization header from credentials.

        For API keys: Use key directly (no Bearer prefix)
        For OAuth tokens: Use Bearer prefix
        """
        if isinstance(credentials, LinearPATCredential):
            # API keys don't use Bearer prefix
            return credentials.api_key
        else:
            # OAuth tokens use Bearer prefix
            return f"Bearer {credentials.access_token}"

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring Linear OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating personal API keys."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.linear_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="linear",
        )

    async def _ensure_fresh_token(self, credentials: LinearCredential) -> None:
        """Refresh an expired Linear OAuth token in place. Personal API keys are
        long-lived and left untouched."""
        if not isinstance(credentials, LinearOAuthCredential):
            return

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.linear_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="linear",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
