"""
GitLab DevOps automation node.

Provides workflow integration with the GitLab REST API (v4) for operations
including:
- Projects: list, get, create, list members
- Issues: list, get, create, update, comment
- Merge Requests: list, get, create, update, merge
- Repository: list/create/delete branches, list/create commits, get/upsert files,
  create tags
- CI/CD: list pipelines, create pipeline, list pipeline jobs
- Releases: create release
- Groups / Search / User
- Webhook Trigger: fire when a project hook event arrives (push, issues, MR, etc.)

Authentication: OAuth 2.0 authorization_code (gitlab.com, rotating refresh
tokens) OR a Personal/Project/Group Access Token. Every token type is sent via
the `Authorization: Bearer` header (the one header GitLab accepts for both OAuth
and access tokens). The access token is the only option for self-managed
instances.

API Base URL: https://gitlab.com/api/v4 (configurable host for self-managed).
Documentation: https://docs.gitlab.com/api/rest/
"""

import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from urllib.parse import quote
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.gitlab import GITLAB_SCOPES
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

DEFAULT_GITLAB_HOST = "https://gitlab.com"
API_PREFIX = "/api/v4"

# Selectable webhook event types. Each entry maps the user-facing value to the
# GitLab project-hook "*_events" flag (used when creating the hook) and the
# payload "object_kind" value (used to filter inbound deliveries at runtime,
# since GitLab posts ALL subscribed events to one URL with no per-subscription
# filter — the object_kind / X-Gitlab-Event header names the event).
GITLAB_EVENT_TYPES: Dict[str, Dict[str, str]] = {
    "push": {"flag": "push_events", "object_kind": "push", "label": "Push"},
    "tag_push": {"flag": "tag_push_events", "object_kind": "tag_push", "label": "Tag Push"},
    "issue": {"flag": "issues_events", "object_kind": "issue", "label": "Issue"},
    "merge_request": {
        "flag": "merge_requests_events",
        "object_kind": "merge_request",
        "label": "Merge Request",
    },
    "note": {"flag": "note_events", "object_kind": "note", "label": "Comment"},
    "pipeline": {"flag": "pipeline_events", "object_kind": "pipeline", "label": "Pipeline"},
    # GitLab job events post with object_kind "build".
    "job": {"flag": "job_events", "object_kind": "build", "label": "Job"},
    "deployment": {
        "flag": "deployment_events",
        "object_kind": "deployment",
        "label": "Deployment",
    },
    "release": {"flag": "releases_events", "object_kind": "release", "label": "Release"},
    "wiki_page": {"flag": "wiki_page_events", "object_kind": "wiki_page", "label": "Wiki Page"},
    "feature_flag": {"flag": "feature_flag_events", "object_kind": "feature_flag", "label": "Feature Flag"},
    "emoji": {"flag": "emoji_events", "object_kind": "emoji", "label": "Emoji"},
}

# Group-hook-ONLY events. Unlike the above, their payloads carry an `event_name`
# (e.g. "user_add_to_group", "subgroup_create", "project_create") rather than an
# `object_kind`, so they filter by event_name prefix.
GITLAB_GROUP_ONLY_EVENTS: Dict[str, Dict[str, str]] = {
    "member": {"flag": "member_events", "prefix": "user_", "label": "Member"},
    "subgroup": {"flag": "subgroup_events", "prefix": "subgroup_", "label": "Subgroup"},
    "project": {"flag": "project_events", "prefix": "project_", "label": "Project"},
}

# Confidential variants share the object_kind of their public counterpart, so
# they can't be filtered distinctly — instead, selecting the public event also
# subscribes to the confidential flag so those deliveries fire too.
_CONFIDENTIAL_FLAGS = {
    "issue": "confidential_issues_events",
    "note": "confidential_note_events",
}

# Sentinel value meaning "subscribe to every event type".
ALL_EVENTS = "*"

# object_kind -> selectable event value, for inbound delivery filtering.
_OBJECT_KIND_TO_EVENT = {
    spec["object_kind"]: key for key, spec in GITLAB_EVENT_TYPES.items()
}


def _selected_event_values(
    event_types: Optional[str], allowed: Optional[Dict[str, Dict[str, str]]] = None
) -> List[str]:
    """Parse the comma-separated event_types config into known event keys.

    Empty / unset / the "*" sentinel means all events. ``allowed`` is the event
    catalog to validate against (project events by default; pass the merged
    group catalog for group hooks).
    """
    catalog = allowed if allowed is not None else GITLAB_EVENT_TYPES
    if not event_types:
        return list(catalog.keys())
    parts = [p.strip() for p in str(event_types).split(",") if p.strip()]
    if not parts or ALL_EVENTS in parts:
        return list(catalog.keys())
    selected = [p for p in parts if p in catalog]
    return selected or list(catalog.keys())


def _hook_event_flags(event_types: Optional[str], *, group: bool = False) -> Dict[str, bool]:
    """Build the GitLab hook flag dict for the selected event types.

    Every known flag is sent explicitly (selected -> True, others -> False) so a
    re-registration with a narrower selection turns off previously-enabled flags.
    Selecting a public event whose confidential variant exists also enables that
    confidential flag. ``group=True`` includes the group-only event flags.
    """
    catalog: Dict[str, Dict[str, str]] = dict(GITLAB_EVENT_TYPES)
    if group:
        catalog.update(GITLAB_GROUP_ONLY_EVENTS)
    selected = set(_selected_event_values(event_types, allowed=catalog))
    flags = {spec["flag"]: (key in selected) for key, spec in catalog.items()}
    for key, conf_flag in _CONFIDENTIAL_FLAGS.items():
        flags[conf_flag] = key in selected
    return flags


def _group_event_for_payload(payload: Dict[str, Any]) -> Optional[str]:
    """Map an inbound group-hook payload to a selectable event key.

    Standard events carry object_kind; group-only events carry event_name.
    """
    object_kind = (payload or {}).get("object_kind")
    if object_kind:
        return _OBJECT_KIND_TO_EVENT.get(object_kind)
    event_name = str((payload or {}).get("event_name") or "")
    for key, spec in GITLAB_GROUP_ONLY_EVENTS.items():
        if event_name.startswith(spec["prefix"]):
            return key
    return None


# ============================================================================
# Credential Schemas
# ============================================================================


class GitLabAccessTokenCredential(BaseModel):
    """Personal / Project / Group Access Token credential for GitLab."""

    credential_type: Literal["gitlab_token"] = Field(
        "gitlab_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="GitLab Personal/Project/Group access token with the 'api' scope, from User Settings -> Access Tokens",
        json_schema_extra={"ui:widget": "password"},
    )
    host: str = Field(
        DEFAULT_GITLAB_HOST,
        title="GitLab Host",
        description="Base URL of your GitLab instance. Use https://gitlab.com for SaaS, or your self-managed host.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://gitlab.com/-/user_settings/personal_access_tokens"
        }
    )


class GitLabOAuthCredential(BaseModel):
    """OAuth 2.0 credential for GitLab (authorization_code grant).

    Tokens are obtained via the OAuth flow, not entered manually. GitLab access
    tokens expire after 2 hours and are auto-refreshed via the rotating refresh
    token.

    Register an OAuth app at: https://gitlab.com/-/user_settings/applications
    """

    credential_type: Literal["gitlab_oauth"] = Field(
        "gitlab_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="GitLab OAuth access token (Bearer).",
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")
    host: str = Field(
        DEFAULT_GITLAB_HOST,
        title="GitLab Host",
        description="Base URL of your GitLab instance.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "gitlab",
            "x-oauth-scopes": ["api", "read_user"],
            "x-credential-url": "https://gitlab.com/-/user_settings/applications",
        }
    )


# OAuth first so it is the default choice when a user adds a credential, with the
# Personal Access Token as the simplest always-working self-serve path (and the
# only option for self-managed instances without a pre-registered OAuth app).
GitLabCredential = Union[GitLabOAuthCredential, GitLabAccessTokenCredential]


# ============================================================================
# Operation Configs
# ============================================================================


class GitLabListProjectsConfig(BaseModel):
    """List projects accessible to the token."""

    operation: Literal["list_projects"] = Field(
        "list_projects",
        json_schema_extra={
            "const": "list_projects",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "List Projects",
        },
        title="List Projects",
    )
    search: Optional[str] = Field(
        None, title="Search", description="Filter projects by name"
    )
    membership: Optional[str] = Field(
        "true",
        title="Member Of",
        description="Only return projects the user is a member of",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    owned: Optional[str] = Field(
        "false",
        title="Owned Only",
        description="Only return projects the user owns",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    per_page: Optional[str] = Field(
        "20", title="Limit", description="Max projects to return (1-100)"
    )


class GitLabGetProjectConfig(BaseModel):
    """Retrieve a single project by ID or namespace/path."""

    operation: Literal["get_project"] = Field(
        "get_project",
        json_schema_extra={
            "const": "get_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Get Project",
        },
        title="Get Project",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path (e.g. mygroup/myrepo)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )


class GitLabCreateProjectConfig(BaseModel):
    """Create a new project (repository)."""

    operation: Literal["create_project"] = Field(
        "create_project",
        json_schema_extra={
            "const": "create_project",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "Create Project",
            "x-creates-resource": True,
            "x-resource-type": "gitlab_project",
            "x-resource-id-path": "data.id",
        },
        title="Create Project",
    )
    name: str = Field(..., title="Name", description="Name of the new project")
    namespace_id: Optional[str] = Field(
        None,
        title="Namespace ID",
        description="Namespace (group/user) ID to create the project in (defaults to current user)",
    )
    visibility: Optional[str] = Field(
        "private",
        title="Visibility",
        description="Project visibility",
        json_schema_extra={
            "enum": ["private", "internal", "public"],
            "enumNames": ["Private", "Internal", "Public"],
            "x-enum-searchable": True,
        },
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Project description",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GitLabListMembersConfig(BaseModel):
    """List members of a project."""

    operation: Literal["list_members"] = Field(
        "list_members",
        json_schema_extra={
            "const": "list_members",
            "ui:hidden": True,
            "x-category": "Projects",
            "x-is-trigger": False,
            "x-display-name": "List Project Members",
        },
        title="List Project Members",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )


class GitLabListIssuesConfig(BaseModel):
    """List issues in a project."""

    operation: Literal["list_issues"] = Field(
        "list_issues",
        json_schema_extra={
            "const": "list_issues",
            "ui:hidden": True,
            "x-category": "Issues",
            "x-is-trigger": False,
            "x-display-name": "List Issues",
        },
        title="List Issues",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    state: Optional[str] = Field(
        "opened",
        title="State",
        description="Filter issues by state",
        json_schema_extra={
            "enum": ["opened", "closed", "all"],
            "enumNames": ["Open", "Closed", "All"],
            "x-enum-searchable": True,
        },
    )
    labels: Optional[str] = Field(
        None, title="Labels", description="Comma-separated label names to filter by"
    )


class GitLabGetIssueConfig(BaseModel):
    """Get a single issue by its project-scoped IID."""

    operation: Literal["get_issue"] = Field(
        "get_issue",
        json_schema_extra={
            "const": "get_issue",
            "ui:hidden": True,
            "x-category": "Issues",
            "x-is-trigger": False,
            "x-display-name": "Get Issue",
        },
        title="Get Issue",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    issue_iid: str = Field(
        ..., title="Issue IID", description="Project-scoped issue IID"
    )


class GitLabCreateIssueConfig(BaseModel):
    """Create an issue in a project."""

    operation: Literal["create_issue"] = Field(
        "create_issue",
        json_schema_extra={
            "const": "create_issue",
            "ui:hidden": True,
            "x-category": "Issues",
            "x-is-trigger": False,
            "x-display-name": "Create Issue",
        },
        title="Create Issue",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    title: str = Field(..., title="Title", description="Issue title")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Issue description (Markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    labels: Optional[str] = Field(
        None, title="Labels", description="Comma-separated label names"
    )
    assignee_ids: Optional[str] = Field(
        None, title="Assignee IDs", description="Comma-separated user IDs to assign"
    )


class GitLabUpdateIssueConfig(BaseModel):
    """Edit issue fields or change its state."""

    operation: Literal["update_issue"] = Field(
        "update_issue",
        json_schema_extra={
            "const": "update_issue",
            "ui:hidden": True,
            "x-category": "Issues",
            "x-is-trigger": False,
            "x-display-name": "Update Issue",
        },
        title="Update Issue",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    issue_iid: str = Field(
        ..., title="Issue IID", description="Project-scoped issue IID"
    )
    title: Optional[str] = Field(None, title="Title", description="New issue title")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New issue description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    state_event: Optional[str] = Field(
        None,
        title="State Event",
        description="Change issue state",
        json_schema_extra={
            "enum": ["", "close", "reopen"],
            "enumNames": ["No change", "Close", "Reopen"],
            "x-enum-searchable": True,
        },
    )
    labels: Optional[str] = Field(
        None, title="Labels", description="Comma-separated label names (replaces existing)"
    )


class GitLabCreateNoteConfig(BaseModel):
    """Add a comment (note) to an issue or merge request."""

    operation: Literal["create_note"] = Field(
        "create_note",
        json_schema_extra={
            "const": "create_note",
            "ui:hidden": True,
            "x-category": "Issues",
            "x-is-trigger": False,
            "x-display-name": "Add Comment",
        },
        title="Add Comment",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    noteable_type: str = Field(
        "issues",
        title="Comment On",
        description="Whether to comment on an issue or a merge request",
        json_schema_extra={
            "enum": ["issues", "merge_requests"],
            "enumNames": ["Issue", "Merge Request"],
            "x-enum-searchable": True,
        },
    )
    noteable_iid: str = Field(
        ..., title="Issue/MR IID", description="Project-scoped IID of the issue or MR"
    )
    body: str = Field(
        ...,
        title="Comment Body",
        description="Comment text (Markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GitLabListMergeRequestsConfig(BaseModel):
    """List merge requests in a project."""

    operation: Literal["list_merge_requests"] = Field(
        "list_merge_requests",
        json_schema_extra={
            "const": "list_merge_requests",
            "ui:hidden": True,
            "x-category": "Merge Requests",
            "x-is-trigger": False,
            "x-display-name": "List Merge Requests",
        },
        title="List Merge Requests",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    state: Optional[str] = Field(
        "opened",
        title="State",
        description="Filter MRs by state",
        json_schema_extra={
            "enum": ["opened", "closed", "merged", "all"],
            "enumNames": ["Open", "Closed", "Merged", "All"],
            "x-enum-searchable": True,
        },
    )
    target_branch: Optional[str] = Field(
        None, title="Target Branch", description="Filter by target branch name"
    )


class GitLabGetMergeRequestConfig(BaseModel):
    """Get a single merge request by IID."""

    operation: Literal["get_merge_request"] = Field(
        "get_merge_request",
        json_schema_extra={
            "const": "get_merge_request",
            "ui:hidden": True,
            "x-category": "Merge Requests",
            "x-is-trigger": False,
            "x-display-name": "Get Merge Request",
        },
        title="Get Merge Request",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    merge_request_iid: str = Field(
        ..., title="Merge Request IID", description="Project-scoped MR IID"
    )


class GitLabCreateMergeRequestConfig(BaseModel):
    """Open a merge request."""

    operation: Literal["create_merge_request"] = Field(
        "create_merge_request",
        json_schema_extra={
            "const": "create_merge_request",
            "ui:hidden": True,
            "x-category": "Merge Requests",
            "x-is-trigger": False,
            "x-display-name": "Create Merge Request",
        },
        title="Create Merge Request",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    source_branch: str = Field(
        ..., title="Source Branch", description="Branch to merge from"
    )
    target_branch: str = Field(
        ..., title="Target Branch", description="Branch to merge into"
    )
    title: str = Field(..., title="Title", description="Merge request title")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Merge request description (Markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GitLabUpdateMergeRequestConfig(BaseModel):
    """Edit a merge request or change its state."""

    operation: Literal["update_merge_request"] = Field(
        "update_merge_request",
        json_schema_extra={
            "const": "update_merge_request",
            "ui:hidden": True,
            "x-category": "Merge Requests",
            "x-is-trigger": False,
            "x-display-name": "Update Merge Request",
        },
        title="Update Merge Request",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    merge_request_iid: str = Field(
        ..., title="Merge Request IID", description="Project-scoped MR IID"
    )
    title: Optional[str] = Field(None, title="Title", description="New MR title")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New MR description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    state_event: Optional[str] = Field(
        None,
        title="State Event",
        description="Change MR state",
        json_schema_extra={
            "enum": ["", "close", "reopen"],
            "enumNames": ["No change", "Close", "Reopen"],
            "x-enum-searchable": True,
        },
    )


class GitLabMergeMergeRequestConfig(BaseModel):
    """Accept/merge a merge request."""

    operation: Literal["merge_merge_request"] = Field(
        "merge_merge_request",
        json_schema_extra={
            "const": "merge_merge_request",
            "ui:hidden": True,
            "x-category": "Merge Requests",
            "x-is-trigger": False,
            "x-display-name": "Merge Merge Request",
        },
        title="Merge Merge Request",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    merge_request_iid: str = Field(
        ..., title="Merge Request IID", description="Project-scoped MR IID"
    )
    squash: Optional[str] = Field(
        "false",
        title="Squash Commits",
        description="Squash commits into a single commit on merge",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    merge_commit_message: Optional[str] = Field(
        None, title="Merge Commit Message", description="Custom merge commit message"
    )


class GitLabListBranchesConfig(BaseModel):
    """List repository branches."""

    operation: Literal["list_branches"] = Field(
        "list_branches",
        json_schema_extra={
            "const": "list_branches",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Branches",
        },
        title="List Branches",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    search: Optional[str] = Field(
        None, title="Search", description="Filter branches by name"
    )


class GitLabCreateBranchConfig(BaseModel):
    """Create a repository branch."""

    operation: Literal["create_branch"] = Field(
        "create_branch",
        json_schema_extra={
            "const": "create_branch",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Create Branch",
        },
        title="Create Branch",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    branch: str = Field(..., title="Branch Name", description="Name of the new branch")
    ref: str = Field(
        ..., title="Ref", description="Branch name or commit SHA to branch from"
    )


class GitLabDeleteBranchConfig(BaseModel):
    """Delete a repository branch."""

    operation: Literal["delete_branch"] = Field(
        "delete_branch",
        json_schema_extra={
            "const": "delete_branch",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Delete Branch",
        },
        title="Delete Branch",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    branch: str = Field(..., title="Branch Name", description="Name of the branch to delete")


class GitLabListCommitsConfig(BaseModel):
    """List repository commits."""

    operation: Literal["list_commits"] = Field(
        "list_commits",
        json_schema_extra={
            "const": "list_commits",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Commits",
        },
        title="List Commits",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    ref_name: Optional[str] = Field(
        None, title="Ref", description="Branch or tag name to list commits from"
    )
    since: Optional[str] = Field(
        None, title="Since", description="ISO 8601 lower bound for commit date"
    )
    until: Optional[str] = Field(
        None, title="Until", description="ISO 8601 upper bound for commit date"
    )


class GitLabCreateCommitConfig(BaseModel):
    """Create a commit with file actions in one call."""

    operation: Literal["create_commit"] = Field(
        "create_commit",
        json_schema_extra={
            "const": "create_commit",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Create Commit",
        },
        title="Create Commit",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    branch: str = Field(..., title="Branch", description="Branch to commit to")
    commit_message: str = Field(..., title="Commit Message", description="Commit message")
    file_path: str = Field(
        ..., title="File Path", description="Path of the file to create/update"
    )
    content: str = Field(
        ...,
        title="Content",
        description="New file content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    action: str = Field(
        "create",
        title="Action",
        description="File action to perform",
        json_schema_extra={
            "enum": ["create", "update", "delete"],
            "enumNames": ["Create", "Update", "Delete"],
            "x-enum-searchable": True,
        },
    )


class GitLabGetFileConfig(BaseModel):
    """Get a repository file's content and metadata."""

    operation: Literal["get_file"] = Field(
        "get_file",
        json_schema_extra={
            "const": "get_file",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Get File",
        },
        title="Get File",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    file_path: str = Field(..., title="File Path", description="Path of the file in the repo")
    ref: str = Field(
        "main", title="Ref", description="Branch, tag, or commit SHA to read from"
    )


class GitLabUpsertFileConfig(BaseModel):
    """Create or update a single repository file."""

    operation: Literal["upsert_file"] = Field(
        "upsert_file",
        json_schema_extra={
            "const": "upsert_file",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Create/Update File",
        },
        title="Create/Update File",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    file_path: str = Field(..., title="File Path", description="Path of the file in the repo")
    branch: str = Field(..., title="Branch", description="Branch to commit to")
    content: str = Field(
        ...,
        title="Content",
        description="File content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    commit_message: str = Field(..., title="Commit Message", description="Commit message")
    mode: str = Field(
        "create",
        title="Mode",
        description="Create a new file (POST) or update an existing one (PUT)",
        json_schema_extra={
            "enum": ["create", "update"],
            "enumNames": ["Create", "Update"],
            "x-enum-searchable": True,
        },
    )


class GitLabCreateTagConfig(BaseModel):
    """Create a git tag."""

    operation: Literal["create_tag"] = Field(
        "create_tag",
        json_schema_extra={
            "const": "create_tag",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Create Tag",
        },
        title="Create Tag",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    tag_name: str = Field(..., title="Tag Name", description="Name of the new tag")
    ref: str = Field(..., title="Ref", description="Branch name or commit SHA to tag")
    message: Optional[str] = Field(
        None, title="Message", description="Optional annotated tag message"
    )


class GitLabListPipelinesConfig(BaseModel):
    """List CI/CD pipelines."""

    operation: Literal["list_pipelines"] = Field(
        "list_pipelines",
        json_schema_extra={
            "const": "list_pipelines",
            "ui:hidden": True,
            "x-category": "CI/CD",
            "x-is-trigger": False,
            "x-display-name": "List Pipelines",
        },
        title="List Pipelines",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter pipelines by status",
        json_schema_extra={
            "enum": ["", "running", "pending", "success", "failed", "canceled", "skipped"],
            "enumNames": ["Any", "Running", "Pending", "Success", "Failed", "Canceled", "Skipped"],
            "x-enum-searchable": True,
        },
    )
    ref: Optional[str] = Field(
        None, title="Ref", description="Filter by branch or tag name"
    )


class GitLabCreatePipelineConfig(BaseModel):
    """Trigger a new pipeline on a ref."""

    operation: Literal["create_pipeline"] = Field(
        "create_pipeline",
        json_schema_extra={
            "const": "create_pipeline",
            "ui:hidden": True,
            "x-category": "CI/CD",
            "x-is-trigger": False,
            "x-display-name": "Create Pipeline",
        },
        title="Create Pipeline",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    ref: str = Field(..., title="Ref", description="Branch or tag to run the pipeline on")
    variables: Optional[str] = Field(
        None,
        title="Variables",
        description="CI/CD variables passed to the pipeline, one KEY=VALUE per line",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GitLabListPipelineJobsConfig(BaseModel):
    """List jobs for a pipeline."""

    operation: Literal["list_pipeline_jobs"] = Field(
        "list_pipeline_jobs",
        json_schema_extra={
            "const": "list_pipeline_jobs",
            "ui:hidden": True,
            "x-category": "CI/CD",
            "x-is-trigger": False,
            "x-display-name": "List Pipeline Jobs",
        },
        title="List Pipeline Jobs",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    pipeline_id: str = Field(
        ..., title="Pipeline ID", description="ID of the pipeline"
    )


class GitLabCreateReleaseConfig(BaseModel):
    """Create a release tied to a tag."""

    operation: Literal["create_release"] = Field(
        "create_release",
        json_schema_extra={
            "const": "create_release",
            "ui:hidden": True,
            "x-category": "Releases",
            "x-is-trigger": False,
            "x-display-name": "Create Release",
        },
        title="Create Release",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    tag_name: str = Field(..., title="Tag Name", description="Tag the release is tied to")
    name: Optional[str] = Field(None, title="Name", description="Release name")
    ref: Optional[str] = Field(
        None,
        title="Ref",
        description="Branch/commit to create the tag from if it does not exist",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Release notes (Markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GitLabListGroupsConfig(BaseModel):
    """List groups visible to the token."""

    operation: Literal["list_groups"] = Field(
        "list_groups",
        json_schema_extra={
            "const": "list_groups",
            "ui:hidden": True,
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": "List Groups",
        },
        title="List Groups",
    )
    search: Optional[str] = Field(
        None, title="Search", description="Filter groups by name"
    )


class GitLabSearchConfig(BaseModel):
    """Global search across GitLab."""

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Global Search",
        },
        title="Global Search",
    )
    scope: str = Field(
        "projects",
        title="Scope",
        description="What to search for",
        json_schema_extra={
            "enum": ["projects", "issues", "merge_requests", "milestones", "blobs", "users"],
            "enumNames": ["Projects", "Issues", "Merge Requests", "Milestones", "Code", "Users"],
            "x-enum-searchable": True,
        },
    )
    search_term: str = Field(..., title="Query", description="Search query string")


class GitLabGetUserConfig(BaseModel):
    """Return the authenticated user (token validity check)."""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class GitLabHookTriggerConfig(BaseModel):
    """Fire the workflow when a project hook event arrives."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_project_event"] = Field(
        "on_project_event",
        json_schema_extra={
            "const": "on_project_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Project Event",
        },
        title="On Project Event",
    )
    project_id: str = Field(
        ...,
        title="Project",
        description="Project whose events should trigger this workflow",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )
    event_types: str = Field(
        ALL_EVENTS,
        title="Trigger On",
        description=(
            "Which GitLab event fires this workflow. GitLab delivers every "
            "subscribed event to one URL; non-matching deliveries are skipped. "
            "Options: All Events (default), Push (commits pushed), Tag Push "
            "(tags pushed), Issue (issue created/updated/closed), Merge Request "
            "(MR opened/updated/merged), Comment (note on issue/MR/commit/code), "
            "Pipeline (CI/CD pipeline status change), Job (CI job status change), "
            "Deployment (environment deploy status), Release (release "
            "created/updated), Wiki Page (wiki page created/updated)."
        ),
        json_schema_extra={
            "enum": [ALL_EVENTS, *GITLAB_EVENT_TYPES.keys()],
            "enumNames": [
                "All Events",
                *[spec["label"] for spec in GITLAB_EVENT_TYPES.values()],
            ],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="GitLab posts project hook events here. Registered automatically when you connect credentials.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# Group trigger event catalog = project events + group-only events.
_GROUP_EVENT_LABELS = {
    **{k: v["label"] for k, v in GITLAB_EVENT_TYPES.items()},
    **{k: v["label"] for k, v in GITLAB_GROUP_ONLY_EVENTS.items()},
}


class GitLabGroupHookTriggerConfig(BaseModel):
    """Fire the workflow when a GROUP hook event arrives (across all the group's
    projects, plus group-level member/subgroup/project events).

    NOTE: Group webhooks are a GitLab Premium/Ultimate feature. On a free-tier
    group the hook can be created but GitLab never delivers events to it.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_group_event"] = Field(
        "on_group_event",
        json_schema_extra={
            "const": "on_group_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Group Event (Premium)",
        },
        title="On Group Event (Premium)",
    )
    group_id: str = Field(
        ...,
        title="Group",
        description="Group whose events (across all its projects) trigger this workflow. Numeric group ID or group path. Requires GitLab Premium/Ultimate — group webhooks do not fire on free-tier groups.",
    )
    event_types: str = Field(
        ALL_EVENTS,
        title="Trigger On",
        description=(
            "Which GitLab group event fires this workflow. Group hooks fire for "
            "events across every project in the group, plus group-level Member "
            "(user added/removed), Subgroup (created/removed), and Project "
            "(created/removed/transferred) events. GitLab delivers every "
            "subscribed event to one URL; non-matching deliveries are skipped."
        ),
        json_schema_extra={
            "enum": [ALL_EVENTS, *_GROUP_EVENT_LABELS.keys()],
            "enumNames": ["All Events", *_GROUP_EVENT_LABELS.values()],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="GitLab posts group hook events here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


def _project_field() -> Any:
    """The standard project picker field shared by every project-scoped op."""
    return Field(
        ...,
        title="Project",
        description="Numeric project ID or namespace/path",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste project ID / path",
            },
            "x-resource-type": "gitlab_project",
        },
    )


# ---- CI/CD: pipeline control -------------------------------------------------


class GitLabGetPipelineConfig(BaseModel):
    """Get a single pipeline."""

    operation: Literal["get_pipeline"] = Field(
        "get_pipeline",
        json_schema_extra={
            "const": "get_pipeline", "ui:hidden": True, "x-category": "CI/CD",
            "x-is-trigger": False, "x-display-name": "Get Pipeline",
        },
        title="Get Pipeline",
    )
    project_id: str = _project_field()
    pipeline_id: str = Field(..., title="Pipeline ID", description="ID of the pipeline")


class GitLabRetryPipelineConfig(BaseModel):
    """Retry the failed/canceled jobs of a pipeline."""

    operation: Literal["retry_pipeline"] = Field(
        "retry_pipeline",
        json_schema_extra={
            "const": "retry_pipeline", "ui:hidden": True, "x-category": "CI/CD",
            "x-is-trigger": False, "x-display-name": "Retry Pipeline",
        },
        title="Retry Pipeline",
    )
    project_id: str = _project_field()
    pipeline_id: str = Field(..., title="Pipeline ID", description="ID of the pipeline")


class GitLabCancelPipelineConfig(BaseModel):
    """Cancel a pipeline's running jobs."""

    operation: Literal["cancel_pipeline"] = Field(
        "cancel_pipeline",
        json_schema_extra={
            "const": "cancel_pipeline", "ui:hidden": True, "x-category": "CI/CD",
            "x-is-trigger": False, "x-display-name": "Cancel Pipeline",
        },
        title="Cancel Pipeline",
    )
    project_id: str = _project_field()
    pipeline_id: str = Field(..., title="Pipeline ID", description="ID of the pipeline")


# ---- CI/CD: job control ------------------------------------------------------


class GitLabGetJobConfig(BaseModel):
    """Get a single job."""

    operation: Literal["get_job"] = Field(
        "get_job",
        json_schema_extra={
            "const": "get_job", "ui:hidden": True, "x-category": "CI/CD",
            "x-is-trigger": False, "x-display-name": "Get Job",
        },
        title="Get Job",
    )
    project_id: str = _project_field()
    job_id: str = Field(..., title="Job ID", description="ID of the job")


class GitLabGetJobLogConfig(BaseModel):
    """Get a job's log/trace (plain text)."""

    operation: Literal["get_job_log"] = Field(
        "get_job_log",
        json_schema_extra={
            "const": "get_job_log", "ui:hidden": True, "x-category": "CI/CD",
            "x-is-trigger": False, "x-display-name": "Get Job Log",
        },
        title="Get Job Log",
    )
    project_id: str = _project_field()
    job_id: str = Field(..., title="Job ID", description="ID of the job")


class GitLabRetryJobConfig(BaseModel):
    """Retry a single job."""

    operation: Literal["retry_job"] = Field(
        "retry_job",
        json_schema_extra={
            "const": "retry_job", "ui:hidden": True, "x-category": "CI/CD",
            "x-is-trigger": False, "x-display-name": "Retry Job",
        },
        title="Retry Job",
    )
    project_id: str = _project_field()
    job_id: str = Field(..., title="Job ID", description="ID of the job")


class GitLabPlayJobConfig(BaseModel):
    """Run a manual job."""

    operation: Literal["play_job"] = Field(
        "play_job",
        json_schema_extra={
            "const": "play_job", "ui:hidden": True, "x-category": "CI/CD",
            "x-is-trigger": False, "x-display-name": "Play Job",
        },
        title="Play Job",
    )
    project_id: str = _project_field()
    job_id: str = Field(..., title="Job ID", description="ID of the manual job to run")


class GitLabCancelJobConfig(BaseModel):
    """Cancel a single job."""

    operation: Literal["cancel_job"] = Field(
        "cancel_job",
        json_schema_extra={
            "const": "cancel_job", "ui:hidden": True, "x-category": "CI/CD",
            "x-is-trigger": False, "x-display-name": "Cancel Job",
        },
        title="Cancel Job",
    )
    project_id: str = _project_field()
    job_id: str = Field(..., title="Job ID", description="ID of the job")


# ---- CI/CD: project variables ------------------------------------------------


class GitLabListVariablesConfig(BaseModel):
    """List a project's CI/CD variables."""

    operation: Literal["list_variables"] = Field(
        "list_variables",
        json_schema_extra={
            "const": "list_variables", "ui:hidden": True, "x-category": "CI/CD Variables",
            "x-is-trigger": False, "x-display-name": "List Variables",
        },
        title="List Variables",
    )
    project_id: str = _project_field()


class GitLabCreateVariableConfig(BaseModel):
    """Create a project CI/CD variable."""

    operation: Literal["create_variable"] = Field(
        "create_variable",
        json_schema_extra={
            "const": "create_variable", "ui:hidden": True, "x-category": "CI/CD Variables",
            "x-is-trigger": False, "x-display-name": "Create Variable",
        },
        title="Create Variable",
    )
    project_id: str = _project_field()
    key: str = Field(..., title="Key", description="Variable key (A-Z, 0-9, _)")
    value: str = Field(..., title="Value", description="Variable value")
    variable_type: str = Field(
        "env_var",
        title="Type",
        description="Variable type",
        json_schema_extra={
            "enum": ["env_var", "file"],
            "enumNames": ["Environment variable", "File"],
            "x-enum-searchable": True,
        },
    )
    protected: str = Field(
        "false", title="Protected", description="Only expose on protected branches/tags",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    masked: str = Field(
        "false", title="Masked", description="Mask the value in job logs",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GitLabUpdateVariableConfig(BaseModel):
    """Update a project CI/CD variable's value."""

    operation: Literal["update_variable"] = Field(
        "update_variable",
        json_schema_extra={
            "const": "update_variable", "ui:hidden": True, "x-category": "CI/CD Variables",
            "x-is-trigger": False, "x-display-name": "Update Variable",
        },
        title="Update Variable",
    )
    project_id: str = _project_field()
    key: str = Field(..., title="Key", description="Variable key to update")
    value: str = Field(..., title="Value", description="New value")


class GitLabDeleteVariableConfig(BaseModel):
    """Delete a project CI/CD variable."""

    operation: Literal["delete_variable"] = Field(
        "delete_variable",
        json_schema_extra={
            "const": "delete_variable", "ui:hidden": True, "x-category": "CI/CD Variables",
            "x-is-trigger": False, "x-display-name": "Delete Variable",
        },
        title="Delete Variable",
    )
    project_id: str = _project_field()
    key: str = Field(..., title="Key", description="Variable key to delete")


# ---- Merge Requests: review --------------------------------------------------


class GitLabApproveMergeRequestConfig(BaseModel):
    """Approve a merge request."""

    operation: Literal["approve_merge_request"] = Field(
        "approve_merge_request",
        json_schema_extra={
            "const": "approve_merge_request", "ui:hidden": True, "x-category": "Merge Requests",
            "x-is-trigger": False, "x-display-name": "Approve Merge Request",
        },
        title="Approve Merge Request",
    )
    project_id: str = _project_field()
    merge_request_iid: str = Field(..., title="MR IID", description="Internal ID of the merge request")


class GitLabUnapproveMergeRequestConfig(BaseModel):
    """Remove your approval from a merge request."""

    operation: Literal["unapprove_merge_request"] = Field(
        "unapprove_merge_request",
        json_schema_extra={
            "const": "unapprove_merge_request", "ui:hidden": True, "x-category": "Merge Requests",
            "x-is-trigger": False, "x-display-name": "Unapprove Merge Request",
        },
        title="Unapprove Merge Request",
    )
    project_id: str = _project_field()
    merge_request_iid: str = Field(..., title="MR IID", description="Internal ID of the merge request")


# ---- Notes (read) ------------------------------------------------------------


class GitLabListNotesConfig(BaseModel):
    """List comments (notes) on an issue or merge request."""

    operation: Literal["list_notes"] = Field(
        "list_notes",
        json_schema_extra={
            "const": "list_notes", "ui:hidden": True, "x-category": "Issues",
            "x-is-trigger": False, "x-display-name": "List Notes",
        },
        title="List Notes",
    )
    project_id: str = _project_field()
    noteable_type: str = Field(
        "issues",
        title="Noteable Type",
        description="Whether the notes belong to an issue or a merge request",
        json_schema_extra={
            "enum": ["issues", "merge_requests"],
            "enumNames": ["Issue", "Merge Request"],
            "x-enum-searchable": True,
        },
    )
    noteable_iid: str = Field(..., title="IID", description="Internal ID of the issue or merge request")


# ---- Issues: delete ----------------------------------------------------------


class GitLabDeleteIssueConfig(BaseModel):
    """Delete an issue."""

    operation: Literal["delete_issue"] = Field(
        "delete_issue",
        json_schema_extra={
            "const": "delete_issue", "ui:hidden": True, "x-category": "Issues",
            "x-is-trigger": False, "x-display-name": "Delete Issue",
        },
        title="Delete Issue",
    )
    project_id: str = _project_field()
    issue_iid: str = Field(..., title="Issue IID", description="Internal ID of the issue")


# ---- Labels ------------------------------------------------------------------


class GitLabListLabelsConfig(BaseModel):
    """List a project's labels."""

    operation: Literal["list_labels"] = Field(
        "list_labels",
        json_schema_extra={
            "const": "list_labels", "ui:hidden": True, "x-category": "Labels",
            "x-is-trigger": False, "x-display-name": "List Labels",
        },
        title="List Labels",
    )
    project_id: str = _project_field()


class GitLabCreateLabelConfig(BaseModel):
    """Create a project label."""

    operation: Literal["create_label"] = Field(
        "create_label",
        json_schema_extra={
            "const": "create_label", "ui:hidden": True, "x-category": "Labels",
            "x-is-trigger": False, "x-display-name": "Create Label",
        },
        title="Create Label",
    )
    project_id: str = _project_field()
    name: str = Field(..., title="Name", description="Label name")
    color: str = Field(
        "#428BCA", title="Color", description="Hex color (e.g. #FF0000) or a CSS color name"
    )
    description: Optional[str] = Field(None, title="Description", description="Label description")


class GitLabDeleteLabelConfig(BaseModel):
    """Delete a project label."""

    operation: Literal["delete_label"] = Field(
        "delete_label",
        json_schema_extra={
            "const": "delete_label", "ui:hidden": True, "x-category": "Labels",
            "x-is-trigger": False, "x-display-name": "Delete Label",
        },
        title="Delete Label",
    )
    project_id: str = _project_field()
    label_id: str = Field(..., title="Label ID or Name", description="Numeric label ID or label name")


# ---- Milestones --------------------------------------------------------------


class GitLabListMilestonesConfig(BaseModel):
    """List a project's milestones."""

    operation: Literal["list_milestones"] = Field(
        "list_milestones",
        json_schema_extra={
            "const": "list_milestones", "ui:hidden": True, "x-category": "Milestones",
            "x-is-trigger": False, "x-display-name": "List Milestones",
        },
        title="List Milestones",
    )
    project_id: str = _project_field()
    state: Optional[str] = Field(
        None, title="State", description="Filter by state",
        json_schema_extra={
            "enum": ["", "active", "closed"], "enumNames": ["Any", "Active", "Closed"],
            "x-enum-searchable": True,
        },
    )


class GitLabCreateMilestoneConfig(BaseModel):
    """Create a project milestone."""

    operation: Literal["create_milestone"] = Field(
        "create_milestone",
        json_schema_extra={
            "const": "create_milestone", "ui:hidden": True, "x-category": "Milestones",
            "x-is-trigger": False, "x-display-name": "Create Milestone",
        },
        title="Create Milestone",
    )
    project_id: str = _project_field()
    title: str = Field(..., title="Title", description="Milestone title")
    description: Optional[str] = Field(None, title="Description", description="Milestone description")
    due_date: Optional[str] = Field(None, title="Due Date", description="Due date (YYYY-MM-DD)")
    start_date: Optional[str] = Field(None, title="Start Date", description="Start date (YYYY-MM-DD)")


# ---- Members -----------------------------------------------------------------


class GitLabAddMemberConfig(BaseModel):
    """Add a user as a project member."""

    operation: Literal["add_member"] = Field(
        "add_member",
        json_schema_extra={
            "const": "add_member", "ui:hidden": True, "x-category": "Members",
            "x-is-trigger": False, "x-display-name": "Add Member",
        },
        title="Add Member",
    )
    project_id: str = _project_field()
    user_id: str = Field(..., title="User ID", description="Numeric ID of the user to add")
    access_level: str = Field(
        "30",
        title="Access Level",
        description="Member role",
        json_schema_extra={
            "enum": ["10", "20", "30", "40", "50"],
            "enumNames": ["Guest", "Reporter", "Developer", "Maintainer", "Owner"],
            "x-enum-searchable": True,
        },
    )


class GitLabRemoveMemberConfig(BaseModel):
    """Remove a project member."""

    operation: Literal["remove_member"] = Field(
        "remove_member",
        json_schema_extra={
            "const": "remove_member", "ui:hidden": True, "x-category": "Members",
            "x-is-trigger": False, "x-display-name": "Remove Member",
        },
        title="Remove Member",
    )
    project_id: str = _project_field()
    user_id: str = Field(..., title="User ID", description="Numeric ID of the user to remove")


# ---- Releases (read) ---------------------------------------------------------


class GitLabListReleasesConfig(BaseModel):
    """List a project's releases."""

    operation: Literal["list_releases"] = Field(
        "list_releases",
        json_schema_extra={
            "const": "list_releases", "ui:hidden": True, "x-category": "Releases",
            "x-is-trigger": False, "x-display-name": "List Releases",
        },
        title="List Releases",
    )
    project_id: str = _project_field()


class GitLabGetReleaseConfig(BaseModel):
    """Get a release by tag name."""

    operation: Literal["get_release"] = Field(
        "get_release",
        json_schema_extra={
            "const": "get_release", "ui:hidden": True, "x-category": "Releases",
            "x-is-trigger": False, "x-display-name": "Get Release",
        },
        title="Get Release",
    )
    project_id: str = _project_field()
    tag_name: str = Field(..., title="Tag Name", description="Tag the release is tied to")


# ---- Commit status -----------------------------------------------------------


class GitLabSetCommitStatusConfig(BaseModel):
    """Post a build/commit status onto a commit SHA."""

    operation: Literal["set_commit_status"] = Field(
        "set_commit_status",
        json_schema_extra={
            "const": "set_commit_status", "ui:hidden": True, "x-category": "Repository",
            "x-is-trigger": False, "x-display-name": "Set Commit Status",
        },
        title="Set Commit Status",
    )
    project_id: str = _project_field()
    sha: str = Field(..., title="Commit SHA", description="The commit SHA to attach the status to")
    state: str = Field(
        "success",
        title="State",
        description="Status state",
        json_schema_extra={
            "enum": ["pending", "running", "success", "failed", "canceled"],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(None, title="Context", description="Label/context for the status (e.g. ci/external)")
    target_url: Optional[str] = Field(None, title="Target URL", description="URL to link the status to")
    description: Optional[str] = Field(None, title="Description", description="Short status description")


# ---- Environments ------------------------------------------------------------


class GitLabListEnvironmentsConfig(BaseModel):
    """List a project's environments."""

    operation: Literal["list_environments"] = Field(
        "list_environments",
        json_schema_extra={
            "const": "list_environments", "ui:hidden": True, "x-category": "Environments",
            "x-is-trigger": False, "x-display-name": "List Environments",
        },
        title="List Environments",
    )
    project_id: str = _project_field()


class GitLabCreateEnvironmentConfig(BaseModel):
    """Create an environment."""

    operation: Literal["create_environment"] = Field(
        "create_environment",
        json_schema_extra={
            "const": "create_environment", "ui:hidden": True, "x-category": "Environments",
            "x-is-trigger": False, "x-display-name": "Create Environment",
        },
        title="Create Environment",
    )
    project_id: str = _project_field()
    name: str = Field(..., title="Name", description="Environment name (e.g. production)")
    external_url: Optional[str] = Field(None, title="External URL", description="Public URL of the environment")


class GitLabStopEnvironmentConfig(BaseModel):
    """Stop an environment."""

    operation: Literal["stop_environment"] = Field(
        "stop_environment",
        json_schema_extra={
            "const": "stop_environment", "ui:hidden": True, "x-category": "Environments",
            "x-is-trigger": False, "x-display-name": "Stop Environment",
        },
        title="Stop Environment",
    )
    project_id: str = _project_field()
    environment_id: str = Field(..., title="Environment ID", description="Numeric environment ID")


class GitLabDeleteEnvironmentConfig(BaseModel):
    """Delete a stopped environment."""

    operation: Literal["delete_environment"] = Field(
        "delete_environment",
        json_schema_extra={
            "const": "delete_environment", "ui:hidden": True, "x-category": "Environments",
            "x-is-trigger": False, "x-display-name": "Delete Environment",
        },
        title="Delete Environment",
    )
    project_id: str = _project_field()
    environment_id: str = Field(..., title="Environment ID", description="Numeric environment ID")


# ---- Deployments -------------------------------------------------------------


class GitLabListDeploymentsConfig(BaseModel):
    """List a project's deployments."""

    operation: Literal["list_deployments"] = Field(
        "list_deployments",
        json_schema_extra={
            "const": "list_deployments", "ui:hidden": True, "x-category": "Deployments",
            "x-is-trigger": False, "x-display-name": "List Deployments",
        },
        title="List Deployments",
    )
    project_id: str = _project_field()
    environment: Optional[str] = Field(None, title="Environment", description="Filter by environment name")


class GitLabGetDeploymentConfig(BaseModel):
    """Get a single deployment."""

    operation: Literal["get_deployment"] = Field(
        "get_deployment",
        json_schema_extra={
            "const": "get_deployment", "ui:hidden": True, "x-category": "Deployments",
            "x-is-trigger": False, "x-display-name": "Get Deployment",
        },
        title="Get Deployment",
    )
    project_id: str = _project_field()
    deployment_id: str = Field(..., title="Deployment ID", description="Numeric deployment ID")


class GitLabCreateDeploymentConfig(BaseModel):
    """Create a deployment record."""

    operation: Literal["create_deployment"] = Field(
        "create_deployment",
        json_schema_extra={
            "const": "create_deployment", "ui:hidden": True, "x-category": "Deployments",
            "x-is-trigger": False, "x-display-name": "Create Deployment",
        },
        title="Create Deployment",
    )
    project_id: str = _project_field()
    environment: str = Field(..., title="Environment", description="Target environment name")
    sha: str = Field(..., title="SHA", description="Commit SHA being deployed")
    ref: str = Field(..., title="Ref", description="Branch or tag deployed")
    status: str = Field(
        "success",
        title="Status",
        description="Deployment status",
        json_schema_extra={
            "enum": ["running", "success", "failed", "canceled"],
            "x-enum-searchable": True,
        },
    )


# ---- Wikis -------------------------------------------------------------------


class GitLabListWikisConfig(BaseModel):
    """List a project's wiki pages."""

    operation: Literal["list_wikis"] = Field(
        "list_wikis",
        json_schema_extra={
            "const": "list_wikis", "ui:hidden": True, "x-category": "Wikis",
            "x-is-trigger": False, "x-display-name": "List Wiki Pages",
        },
        title="List Wiki Pages",
    )
    project_id: str = _project_field()


class GitLabGetWikiConfig(BaseModel):
    """Get a wiki page by slug."""

    operation: Literal["get_wiki"] = Field(
        "get_wiki",
        json_schema_extra={
            "const": "get_wiki", "ui:hidden": True, "x-category": "Wikis",
            "x-is-trigger": False, "x-display-name": "Get Wiki Page",
        },
        title="Get Wiki Page",
    )
    project_id: str = _project_field()
    slug: str = Field(..., title="Slug", description="Wiki page slug (URL-encoded path)")


class GitLabCreateWikiConfig(BaseModel):
    """Create a wiki page."""

    operation: Literal["create_wiki"] = Field(
        "create_wiki",
        json_schema_extra={
            "const": "create_wiki", "ui:hidden": True, "x-category": "Wikis",
            "x-is-trigger": False, "x-display-name": "Create Wiki Page",
        },
        title="Create Wiki Page",
    )
    project_id: str = _project_field()
    title: str = Field(..., title="Title", description="Wiki page title")
    content: str = Field(..., title="Content", description="Page content", json_schema_extra={"ui:widget": "textarea"})


class GitLabUpdateWikiConfig(BaseModel):
    """Update a wiki page."""

    operation: Literal["update_wiki"] = Field(
        "update_wiki",
        json_schema_extra={
            "const": "update_wiki", "ui:hidden": True, "x-category": "Wikis",
            "x-is-trigger": False, "x-display-name": "Update Wiki Page",
        },
        title="Update Wiki Page",
    )
    project_id: str = _project_field()
    slug: str = Field(..., title="Slug", description="Slug of the page to update")
    title: Optional[str] = Field(None, title="Title", description="New title")
    content: Optional[str] = Field(None, title="Content", description="New content", json_schema_extra={"ui:widget": "textarea"})


class GitLabDeleteWikiConfig(BaseModel):
    """Delete a wiki page."""

    operation: Literal["delete_wiki"] = Field(
        "delete_wiki",
        json_schema_extra={
            "const": "delete_wiki", "ui:hidden": True, "x-category": "Wikis",
            "x-is-trigger": False, "x-display-name": "Delete Wiki Page",
        },
        title="Delete Wiki Page",
    )
    project_id: str = _project_field()
    slug: str = Field(..., title="Slug", description="Slug of the page to delete")


# ---- Protected branches ------------------------------------------------------


class GitLabListProtectedBranchesConfig(BaseModel):
    """List protected branches."""

    operation: Literal["list_protected_branches"] = Field(
        "list_protected_branches",
        json_schema_extra={
            "const": "list_protected_branches", "ui:hidden": True, "x-category": "Protected Branches",
            "x-is-trigger": False, "x-display-name": "List Protected Branches",
        },
        title="List Protected Branches",
    )
    project_id: str = _project_field()


class GitLabProtectBranchConfig(BaseModel):
    """Protect a branch (or wildcard)."""

    operation: Literal["protect_branch"] = Field(
        "protect_branch",
        json_schema_extra={
            "const": "protect_branch", "ui:hidden": True, "x-category": "Protected Branches",
            "x-is-trigger": False, "x-display-name": "Protect Branch",
        },
        title="Protect Branch",
    )
    project_id: str = _project_field()
    name: str = Field(..., title="Name", description="Branch name or wildcard (e.g. main, release/*)")


class GitLabUnprotectBranchConfig(BaseModel):
    """Unprotect a branch."""

    operation: Literal["unprotect_branch"] = Field(
        "unprotect_branch",
        json_schema_extra={
            "const": "unprotect_branch", "ui:hidden": True, "x-category": "Protected Branches",
            "x-is-trigger": False, "x-display-name": "Unprotect Branch",
        },
        title="Unprotect Branch",
    )
    project_id: str = _project_field()
    name: str = Field(..., title="Name", description="Protected branch name to remove")


# ---- Todos (user-scoped) -----------------------------------------------------


class GitLabListTodosConfig(BaseModel):
    """List the current user's todos."""

    operation: Literal["list_todos"] = Field(
        "list_todos",
        json_schema_extra={
            "const": "list_todos", "ui:hidden": True, "x-category": "Todos",
            "x-is-trigger": False, "x-display-name": "List Todos",
        },
        title="List Todos",
    )
    state: Optional[str] = Field(
        None, title="State", description="Filter by state",
        json_schema_extra={"enum": ["", "pending", "done"], "enumNames": ["Any", "Pending", "Done"], "x-enum-searchable": True},
    )


class GitLabMarkTodoDoneConfig(BaseModel):
    """Mark a single todo as done."""

    operation: Literal["mark_todo_done"] = Field(
        "mark_todo_done",
        json_schema_extra={
            "const": "mark_todo_done", "ui:hidden": True, "x-category": "Todos",
            "x-is-trigger": False, "x-display-name": "Mark Todo Done",
        },
        title="Mark Todo Done",
    )
    todo_id: str = Field(..., title="Todo ID", description="ID of the todo to mark done")


class GitLabMarkAllTodosDoneConfig(BaseModel):
    """Mark all of the current user's todos as done."""

    operation: Literal["mark_all_todos_done"] = Field(
        "mark_all_todos_done",
        json_schema_extra={
            "const": "mark_all_todos_done", "ui:hidden": True, "x-category": "Todos",
            "x-is-trigger": False, "x-display-name": "Mark All Todos Done",
        },
        title="Mark All Todos Done",
    )


# ---- Project hooks (management) ----------------------------------------------


class GitLabListHooksConfig(BaseModel):
    """List a project's webhooks."""

    operation: Literal["list_hooks"] = Field(
        "list_hooks",
        json_schema_extra={
            "const": "list_hooks", "ui:hidden": True, "x-category": "Webhooks",
            "x-is-trigger": False, "x-display-name": "List Webhooks",
        },
        title="List Webhooks",
    )
    project_id: str = _project_field()


class GitLabCreateHookConfig(BaseModel):
    """Create a project webhook."""

    operation: Literal["create_hook"] = Field(
        "create_hook",
        json_schema_extra={
            "const": "create_hook", "ui:hidden": True, "x-category": "Webhooks",
            "x-is-trigger": False, "x-display-name": "Create Webhook",
        },
        title="Create Webhook",
    )
    project_id: str = _project_field()
    url: str = Field(..., title="URL", description="Webhook target URL")
    token: Optional[str] = Field(None, title="Secret Token", description="Sent as X-Gitlab-Token on deliveries")
    push_events: str = Field(
        "true", title="Push Events", description="Trigger on push events",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GitLabDeleteHookConfig(BaseModel):
    """Delete a project webhook."""

    operation: Literal["delete_hook"] = Field(
        "delete_hook",
        json_schema_extra={
            "const": "delete_hook", "ui:hidden": True, "x-category": "Webhooks",
            "x-is-trigger": False, "x-display-name": "Delete Webhook",
        },
        title="Delete Webhook",
    )
    project_id: str = _project_field()
    hook_id: str = Field(..., title="Hook ID", description="Numeric webhook ID")


# ---- Releases (update / delete) ----------------------------------------------


class GitLabUpdateReleaseConfig(BaseModel):
    """Update a release's name/notes."""

    operation: Literal["update_release"] = Field(
        "update_release",
        json_schema_extra={
            "const": "update_release", "ui:hidden": True, "x-category": "Releases",
            "x-is-trigger": False, "x-display-name": "Update Release",
        },
        title="Update Release",
    )
    project_id: str = _project_field()
    tag_name: str = Field(..., title="Tag Name", description="Tag of the release to update")
    name: Optional[str] = Field(None, title="Name", description="New release name")
    description: Optional[str] = Field(None, title="Description", description="New notes (Markdown)", json_schema_extra={"ui:widget": "textarea"})


class GitLabDeleteReleaseConfig(BaseModel):
    """Delete a release (the tag is kept)."""

    operation: Literal["delete_release"] = Field(
        "delete_release",
        json_schema_extra={
            "const": "delete_release", "ui:hidden": True, "x-category": "Releases",
            "x-is-trigger": False, "x-display-name": "Delete Release",
        },
        title="Delete Release",
    )
    project_id: str = _project_field()
    tag_name: str = Field(..., title="Tag Name", description="Tag of the release to delete")


# ---- Epics (group-scoped, Premium) -------------------------------------------


class GitLabListEpicsConfig(BaseModel):
    """List a group's epics (Premium)."""

    operation: Literal["list_epics"] = Field(
        "list_epics",
        json_schema_extra={
            "const": "list_epics", "ui:hidden": True, "x-category": "Epics",
            "x-is-trigger": False, "x-display-name": "List Epics",
        },
        title="List Epics",
    )
    group_id: str = Field(..., title="Group", description="Numeric group ID or group path")
    state: Optional[str] = Field(
        None, title="State", description="Filter by state",
        json_schema_extra={"enum": ["", "opened", "closed"], "enumNames": ["Any", "Opened", "Closed"], "x-enum-searchable": True},
    )


class GitLabCreateEpicConfig(BaseModel):
    """Create an epic in a group (Premium)."""

    operation: Literal["create_epic"] = Field(
        "create_epic",
        json_schema_extra={
            "const": "create_epic", "ui:hidden": True, "x-category": "Epics",
            "x-is-trigger": False, "x-display-name": "Create Epic",
        },
        title="Create Epic",
    )
    group_id: str = Field(..., title="Group", description="Numeric group ID or group path")
    title: str = Field(..., title="Title", description="Epic title")
    description: Optional[str] = Field(None, title="Description", description="Epic description", json_schema_extra={"ui:widget": "textarea"})


class GitLabUpdateEpicConfig(BaseModel):
    """Update an epic (Premium)."""

    operation: Literal["update_epic"] = Field(
        "update_epic",
        json_schema_extra={
            "const": "update_epic", "ui:hidden": True, "x-category": "Epics",
            "x-is-trigger": False, "x-display-name": "Update Epic",
        },
        title="Update Epic",
    )
    group_id: str = Field(..., title="Group", description="Numeric group ID or group path")
    epic_iid: str = Field(..., title="Epic IID", description="Internal ID of the epic")
    title: Optional[str] = Field(None, title="Title", description="New title")
    state_event: Optional[str] = Field(
        None, title="State Event", description="Close or reopen",
        json_schema_extra={"enum": ["", "close", "reopen"], "enumNames": ["—", "Close", "Reopen"], "x-enum-searchable": True},
    )


GitLabConfig = Annotated[
    Union[
        GitLabListProjectsConfig,
        GitLabGetProjectConfig,
        GitLabCreateProjectConfig,
        GitLabListMembersConfig,
        GitLabListIssuesConfig,
        GitLabGetIssueConfig,
        GitLabCreateIssueConfig,
        GitLabUpdateIssueConfig,
        GitLabCreateNoteConfig,
        GitLabListMergeRequestsConfig,
        GitLabGetMergeRequestConfig,
        GitLabCreateMergeRequestConfig,
        GitLabUpdateMergeRequestConfig,
        GitLabMergeMergeRequestConfig,
        GitLabListBranchesConfig,
        GitLabCreateBranchConfig,
        GitLabDeleteBranchConfig,
        GitLabListCommitsConfig,
        GitLabCreateCommitConfig,
        GitLabGetFileConfig,
        GitLabUpsertFileConfig,
        GitLabCreateTagConfig,
        GitLabListPipelinesConfig,
        GitLabCreatePipelineConfig,
        GitLabListPipelineJobsConfig,
        GitLabCreateReleaseConfig,
        GitLabListGroupsConfig,
        GitLabSearchConfig,
        GitLabGetUserConfig,
        GitLabGetPipelineConfig,
        GitLabRetryPipelineConfig,
        GitLabCancelPipelineConfig,
        GitLabGetJobConfig,
        GitLabGetJobLogConfig,
        GitLabRetryJobConfig,
        GitLabPlayJobConfig,
        GitLabCancelJobConfig,
        GitLabListVariablesConfig,
        GitLabCreateVariableConfig,
        GitLabUpdateVariableConfig,
        GitLabDeleteVariableConfig,
        GitLabApproveMergeRequestConfig,
        GitLabUnapproveMergeRequestConfig,
        GitLabListNotesConfig,
        GitLabDeleteIssueConfig,
        GitLabListLabelsConfig,
        GitLabCreateLabelConfig,
        GitLabDeleteLabelConfig,
        GitLabListMilestonesConfig,
        GitLabCreateMilestoneConfig,
        GitLabAddMemberConfig,
        GitLabRemoveMemberConfig,
        GitLabListReleasesConfig,
        GitLabGetReleaseConfig,
        GitLabSetCommitStatusConfig,
        GitLabListEnvironmentsConfig,
        GitLabCreateEnvironmentConfig,
        GitLabStopEnvironmentConfig,
        GitLabDeleteEnvironmentConfig,
        GitLabListDeploymentsConfig,
        GitLabGetDeploymentConfig,
        GitLabCreateDeploymentConfig,
        GitLabListWikisConfig,
        GitLabGetWikiConfig,
        GitLabCreateWikiConfig,
        GitLabUpdateWikiConfig,
        GitLabDeleteWikiConfig,
        GitLabListProtectedBranchesConfig,
        GitLabProtectBranchConfig,
        GitLabUnprotectBranchConfig,
        GitLabListTodosConfig,
        GitLabMarkTodoDoneConfig,
        GitLabMarkAllTodosDoneConfig,
        GitLabListHooksConfig,
        GitLabCreateHookConfig,
        GitLabDeleteHookConfig,
        GitLabUpdateReleaseConfig,
        GitLabDeleteReleaseConfig,
        GitLabListEpicsConfig,
        GitLabCreateEpicConfig,
        GitLabUpdateEpicConfig,
        GitLabHookTriggerConfig,
        GitLabGroupHookTriggerConfig,
    ],
    Discriminator("operation"),
]


class GitLabNodeConfig(NodeConfig[GitLabConfig, GitLabCredential]):
    """Full configuration for the GitLab node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _kv_variables(value: Optional[str]) -> Optional[List[Dict[str, str]]]:
    """Parse newline-separated KEY=VALUE pairs into GitLab's variables array."""
    if not value:
        return None
    out: List[Dict[str, str]] = []
    for line in value.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key:
            out.append({"key": key, "value": val.strip()})
    return out or None


def _enc(project_id: str) -> str:
    """URL-encode a project id/path (namespace/project -> namespace%2Fproject)."""
    return quote(str(project_id), safe="")


async def _gitlab_request(
    host: str,
    token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated GitLab v4 request and return a structured result."""
    base = host.rstrip("/")
    url = f"{base}{API_PREFIX}{endpoint}"
    # Bearer works for BOTH OAuth access tokens and personal/project/group access
    # tokens; PRIVATE-TOKEN does NOT accept OAuth tokens (would 401). One header
    # covers every credential type this node supports.
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
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
                    message = err.get("message") or err.get("error") or str(err)
                except Exception:
                    message = response.text
                if isinstance(message, (dict, list)):
                    message = str(message)
                logger.error(f"[GitLabNode] API error ({action_name}): {message}")
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
            logger.error(f"[GitLabNode] Request failed ({action_name}): {msg}")
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


class GitLabNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """GitLab DevOps automation node."""

    edit_examples = [
        "List open issues in a project",
        "Create an issue when a customer reports a bug",
        "Open a merge request from a feature branch",
        "Merge an approved merge request",
        "Trigger a workflow whenever a merge request is opened",
    ]

    scope_registry = GITLAB_SCOPES
    connection_evidence = ConnectionEvidence(
        field="project_id",
        noun="projects",
    )

    @classmethod
    def get_config_model(cls):
        return GitLabNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring GitLab OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating Personal Access Tokens
        (which carry no refresh_token)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.gitlab_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="gitlab",
        )

    async def _ensure_fresh_token(self, credentials: "GitLabCredential") -> None:
        """Refresh an expired GitLab OAuth token in place before an API call.
        Personal Access Tokens carry no refresh_token and are left untouched."""
        if not isinstance(credentials, GitLabOAuthCredential):
            return

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.gitlab_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="gitlab",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    # ------------------------------------------------------------------
    # Dynamic options (projects)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]] = None,
        context=None,
        page_token=None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "project_id":
            return {"options": []}
        cred = credential_data or {}
        token = cred.get("access_token")
        host = cred.get("host") or DEFAULT_GITLAB_HOST
        if not token:
            return {"options": []}
        params = {"membership": "true", "per_page": "100", "order_by": "last_activity_at"}
        if search:
            params["search"] = search
        result = await _gitlab_request(
            host, token, "GET", "/projects", params=params, action_name="list_projects",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or []
        options = []
        for proj in data if isinstance(data, list) else []:
            if not isinstance(proj, dict):
                continue
            pid = proj.get("id")
            label = proj.get("path_with_namespace") or proj.get("name") or f"Project {pid}"
            if pid is not None:
                options.append({"label": label, "value": str(pid)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @staticmethod
    def _hook_scope(config: Dict[str, Any]):
        """Resolve (hooks_base_path, is_group) for the configured trigger.

        Group triggers register on /groups/:id/hooks; project triggers on
        /projects/:id/hooks.
        """
        cfg = config or {}
        if cfg.get("operation") == "on_group_event":
            group_id = cfg.get("group_id")
            if not group_id:
                raise ValueError("A group is required to register the trigger")
            return f"/groups/{_enc(group_id)}/hooks", True
        project_id = cfg.get("project_id")
        if not project_id:
            raise ValueError("A project is required to register the trigger")
        return f"/projects/{_enc(project_id)}/hooks", False

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "project_id": (config or {}).get("project_id"),
            "group_id": (config or {}).get("group_id"),
            "event_types": (config or {}).get("event_types"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        token = credential.get("access_token")
        host = credential.get("host") or DEFAULT_GITLAB_HOST
        if not token:
            raise ValueError("A GitLab access token is required to register the trigger")
        hooks_base, is_group = cls._hook_scope(config)
        secret = hashlib.sha256(f"{node_id}:{webhook_url}".encode()).hexdigest()[:32]

        # GitLab's POST /hooks is not idempotent — drop a stale hook from a prior
        # registration (e.g. after editing event_types/scope) before creating a
        # fresh one, else duplicate hooks accumulate and all fire.
        existing_id = (config or {}).get("external_webhook_id")
        if existing_id:
            try:
                await _gitlab_request(
                    host, token, "DELETE", f"{hooks_base}/{existing_id}",
                    action_name="register_webhook_cleanup",
                )
            except Exception as e:
                logger.warning(f"[GitLabNode] Could not remove stale hook: {e}")

        body = {
            "url": webhook_url,
            "token": secret,
            **_hook_event_flags((config or {}).get("event_types"), group=is_group),
        }
        result = await _gitlab_request(
            host, token, "POST", hooks_base, json_body=body, action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"GitLab webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = data.get("id") if isinstance(data, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id is not None else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        token = (credential or {}).get("access_token")
        host = (credential or {}).get("host") or DEFAULT_GITLAB_HOST
        cfg = config or {}
        is_group = cfg.get("operation") == "on_group_event"
        scope_id = cfg.get("group_id") if is_group else cfg.get("project_id")
        if not external_id or not token or not scope_id:
            return
        base = f"/groups/{_enc(scope_id)}/hooks" if is_group else f"/projects/{_enc(scope_id)}/hooks"
        await _gitlab_request(
            host,
            token,
            "DELETE",
            f"{base}/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("x-gitlab-token")
        if not sent:
            return False
        return hmac.compare_digest(secret, sent)

    @classmethod
    def filter_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        """Skip inbound deliveries whose event isn't in the selected event_types.

        GitLab posts every subscribed event to the same URL with no
        per-subscription filter, so we filter at runtime on the payload's
        ``object_kind`` (which mirrors the ``X-Gitlab-Event`` header). When the
        user selected "All Events" we accept everything.
        """
        is_group = (config or {}).get("operation") == "on_group_event"
        catalog = (
            {**GITLAB_EVENT_TYPES, **GITLAB_GROUP_ONLY_EVENTS} if is_group else GITLAB_EVENT_TYPES
        )
        selected = _selected_event_values((config or {}).get("event_types"), allowed=catalog)
        if set(selected) == set(catalog.keys()):
            return True  # all events — accept any delivery
        # Group hooks deliver member/subgroup/project via event_name, the rest
        # via object_kind; project hooks only via object_kind.
        event = _group_event_for_payload(payload) if is_group else _OBJECT_KIND_TO_EVENT.get(
            (payload or {}).get("object_kind")
        )
        if event is None:
            return True  # unrecognizable shape — don't silently drop
        return event in selected

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, GitLabNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, (GitLabHookTriggerConfig, GitLabGroupHookTriggerConfig)):
            return {
                "status": "success",
                "action": op.operation,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your GitLab access token.")
        await self._ensure_fresh_token(credentials)
        token = credentials.access_token
        host = getattr(credentials, "host", None) or DEFAULT_GITLAB_HOST

        handlers = {
            "list_projects": self._list_projects,
            "get_project": self._get_project,
            "create_project": self._create_project,
            "list_members": self._list_members,
            "list_issues": self._list_issues,
            "get_issue": self._get_issue,
            "create_issue": self._create_issue,
            "update_issue": self._update_issue,
            "create_note": self._create_note,
            "list_merge_requests": self._list_merge_requests,
            "get_merge_request": self._get_merge_request,
            "create_merge_request": self._create_merge_request,
            "update_merge_request": self._update_merge_request,
            "merge_merge_request": self._merge_merge_request,
            "list_branches": self._list_branches,
            "create_branch": self._create_branch,
            "delete_branch": self._delete_branch,
            "list_commits": self._list_commits,
            "create_commit": self._create_commit,
            "get_file": self._get_file,
            "upsert_file": self._upsert_file,
            "create_tag": self._create_tag,
            "list_pipelines": self._list_pipelines,
            "create_pipeline": self._create_pipeline,
            "list_pipeline_jobs": self._list_pipeline_jobs,
            "create_release": self._create_release,
            "list_groups": self._list_groups,
            "search": self._search,
            "get_user": self._get_user,
            "get_pipeline": self._get_pipeline,
            "retry_pipeline": self._retry_pipeline,
            "cancel_pipeline": self._cancel_pipeline,
            "get_job": self._get_job,
            "get_job_log": self._get_job_log,
            "retry_job": self._retry_job,
            "play_job": self._play_job,
            "cancel_job": self._cancel_job,
            "list_variables": self._list_variables,
            "create_variable": self._create_variable,
            "update_variable": self._update_variable,
            "delete_variable": self._delete_variable,
            "approve_merge_request": self._approve_merge_request,
            "unapprove_merge_request": self._unapprove_merge_request,
            "list_notes": self._list_notes,
            "delete_issue": self._delete_issue,
            "list_labels": self._list_labels,
            "create_label": self._create_label,
            "delete_label": self._delete_label,
            "list_milestones": self._list_milestones,
            "create_milestone": self._create_milestone,
            "add_member": self._add_member,
            "remove_member": self._remove_member,
            "list_releases": self._list_releases,
            "get_release": self._get_release,
            "set_commit_status": self._set_commit_status,
            "list_environments": self._list_environments,
            "create_environment": self._create_environment,
            "stop_environment": self._stop_environment,
            "delete_environment": self._delete_environment,
            "list_deployments": self._list_deployments,
            "get_deployment": self._get_deployment,
            "create_deployment": self._create_deployment,
            "list_wikis": self._list_wikis,
            "get_wiki": self._get_wiki,
            "create_wiki": self._create_wiki,
            "update_wiki": self._update_wiki,
            "delete_wiki": self._delete_wiki,
            "list_protected_branches": self._list_protected_branches,
            "protect_branch": self._protect_branch,
            "unprotect_branch": self._unprotect_branch,
            "list_todos": self._list_todos,
            "mark_todo_done": self._mark_todo_done,
            "mark_all_todos_done": self._mark_all_todos_done,
            "list_hooks": self._list_hooks,
            "create_hook": self._create_hook,
            "delete_hook": self._delete_hook,
            "update_release": self._update_release,
            "delete_release": self._delete_release,
            "list_epics": self._list_epics,
            "create_epic": self._create_epic,
            "update_epic": self._update_epic,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, token, host)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Projects
    # ------------------------------------------------------------------
    async def _list_projects(self, c: GitLabListProjectsConfig, token, host) -> Dict[str, Any]:
        params = {
            "search": c.search,
            "membership": c.membership,
            "owned": c.owned,
            "per_page": c.per_page,
        }
        return await _gitlab_request(
            host, token, "GET", "/projects", params=params, action_name="list_projects"
        )

    async def _get_project(self, c: GitLabGetProjectConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}", action_name="get_project"
        )

    async def _create_project(self, c: GitLabCreateProjectConfig, token, host) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "namespace_id": c.namespace_id,
            "visibility": c.visibility,
            "description": c.description,
        }
        return await _gitlab_request(
            host, token, "POST", "/projects", json_body=body, action_name="create_project"
        )

    async def _list_members(self, c: GitLabListMembersConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/members", action_name="list_members"
        )

    # ------------------------------------------------------------------
    # Handlers — Issues
    # ------------------------------------------------------------------
    async def _list_issues(self, c: GitLabListIssuesConfig, token, host) -> Dict[str, Any]:
        params = {"state": c.state, "labels": c.labels}
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/issues",
            params=params, action_name="list_issues",
        )

    async def _get_issue(self, c: GitLabGetIssueConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/issues/{c.issue_iid}",
            action_name="get_issue",
        )

    async def _create_issue(self, c: GitLabCreateIssueConfig, token, host) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "description": c.description,
            "labels": c.labels,
            "assignee_ids": _comma_list(c.assignee_ids),
        }
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/issues",
            json_body=body, action_name="create_issue",
        )

    async def _update_issue(self, c: GitLabUpdateIssueConfig, token, host) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "description": c.description,
            "state_event": c.state_event or None,
            "labels": c.labels,
        }
        return await _gitlab_request(
            host, token, "PUT", f"/projects/{_enc(c.project_id)}/issues/{c.issue_iid}",
            json_body=body, action_name="update_issue",
        )

    async def _create_note(self, c: GitLabCreateNoteConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST",
            f"/projects/{_enc(c.project_id)}/{c.noteable_type}/{c.noteable_iid}/notes",
            json_body={"body": c.body}, action_name="create_note",
        )

    # ------------------------------------------------------------------
    # Handlers — Merge Requests
    # ------------------------------------------------------------------
    async def _list_merge_requests(self, c: GitLabListMergeRequestsConfig, token, host) -> Dict[str, Any]:
        params = {"state": c.state, "target_branch": c.target_branch}
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/merge_requests",
            params=params, action_name="list_merge_requests",
        )

    async def _get_merge_request(self, c: GitLabGetMergeRequestConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET",
            f"/projects/{_enc(c.project_id)}/merge_requests/{c.merge_request_iid}",
            action_name="get_merge_request",
        )

    async def _create_merge_request(self, c: GitLabCreateMergeRequestConfig, token, host) -> Dict[str, Any]:
        body = {
            "source_branch": c.source_branch,
            "target_branch": c.target_branch,
            "title": c.title,
            "description": c.description,
        }
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/merge_requests",
            json_body=body, action_name="create_merge_request",
        )

    async def _update_merge_request(self, c: GitLabUpdateMergeRequestConfig, token, host) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "description": c.description,
            "state_event": c.state_event or None,
        }
        return await _gitlab_request(
            host, token, "PUT",
            f"/projects/{_enc(c.project_id)}/merge_requests/{c.merge_request_iid}",
            json_body=body, action_name="update_merge_request",
        )

    async def _merge_merge_request(self, c: GitLabMergeMergeRequestConfig, token, host) -> Dict[str, Any]:
        body = {
            "squash": c.squash == "true",
            "merge_commit_message": c.merge_commit_message,
        }
        return await _gitlab_request(
            host, token, "PUT",
            f"/projects/{_enc(c.project_id)}/merge_requests/{c.merge_request_iid}/merge",
            json_body=body, action_name="merge_merge_request",
        )

    # ------------------------------------------------------------------
    # Handlers — Repository
    # ------------------------------------------------------------------
    async def _list_branches(self, c: GitLabListBranchesConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/repository/branches",
            params={"search": c.search}, action_name="list_branches",
        )

    async def _create_branch(self, c: GitLabCreateBranchConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/repository/branches",
            params={"branch": c.branch, "ref": c.ref}, action_name="create_branch",
        )

    async def _delete_branch(self, c: GitLabDeleteBranchConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE",
            f"/projects/{_enc(c.project_id)}/repository/branches/{_enc(c.branch)}",
            action_name="delete_branch",
        )

    async def _list_commits(self, c: GitLabListCommitsConfig, token, host) -> Dict[str, Any]:
        params = {"ref_name": c.ref_name, "since": c.since, "until": c.until}
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/repository/commits",
            params=params, action_name="list_commits",
        )

    async def _create_commit(self, c: GitLabCreateCommitConfig, token, host) -> Dict[str, Any]:
        action: Dict[str, Any] = {"action": c.action, "file_path": c.file_path}
        if c.action != "delete":
            action["content"] = c.content
        body = {
            "branch": c.branch,
            "commit_message": c.commit_message,
            "actions": [action],
        }
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/repository/commits",
            json_body=body, action_name="create_commit",
        )

    async def _get_file(self, c: GitLabGetFileConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET",
            f"/projects/{_enc(c.project_id)}/repository/files/{_enc(c.file_path)}",
            params={"ref": c.ref}, action_name="get_file",
        )

    async def _upsert_file(self, c: GitLabUpsertFileConfig, token, host) -> Dict[str, Any]:
        method = "POST" if c.mode == "create" else "PUT"
        body = {
            "branch": c.branch,
            "content": c.content,
            "commit_message": c.commit_message,
        }
        return await _gitlab_request(
            host, token, method,
            f"/projects/{_enc(c.project_id)}/repository/files/{_enc(c.file_path)}",
            json_body=body, action_name="upsert_file",
        )

    async def _create_tag(self, c: GitLabCreateTagConfig, token, host) -> Dict[str, Any]:
        params = {"tag_name": c.tag_name, "ref": c.ref, "message": c.message}
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/repository/tags",
            params=params, action_name="create_tag",
        )

    # ------------------------------------------------------------------
    # Handlers — CI/CD
    # ------------------------------------------------------------------
    async def _list_pipelines(self, c: GitLabListPipelinesConfig, token, host) -> Dict[str, Any]:
        params = {"status": c.status or None, "ref": c.ref}
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/pipelines",
            params=params, action_name="list_pipelines",
        )

    async def _create_pipeline(self, c: GitLabCreatePipelineConfig, token, host) -> Dict[str, Any]:
        body: Dict[str, Any] = {"ref": c.ref, "variables": _kv_variables(c.variables)}
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/pipeline",
            json_body=body, action_name="create_pipeline",
        )

    async def _list_pipeline_jobs(self, c: GitLabListPipelineJobsConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET",
            f"/projects/{_enc(c.project_id)}/pipelines/{c.pipeline_id}/jobs",
            action_name="list_pipeline_jobs",
        )

    # ------------------------------------------------------------------
    # Handlers — Releases
    # ------------------------------------------------------------------
    async def _create_release(self, c: GitLabCreateReleaseConfig, token, host) -> Dict[str, Any]:
        body = {
            "tag_name": c.tag_name,
            "name": c.name,
            "ref": c.ref,
            "description": c.description,
        }
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/releases",
            json_body=body, action_name="create_release",
        )

    # ------------------------------------------------------------------
    # Handlers — Groups / Search / User
    # ------------------------------------------------------------------
    async def _list_groups(self, c: GitLabListGroupsConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", "/groups", params={"search": c.search}, action_name="list_groups"
        )

    async def _search(self, c: GitLabSearchConfig, token, host) -> Dict[str, Any]:
        params = {"scope": c.scope, "search": c.search_term}
        return await _gitlab_request(
            host, token, "GET", "/search", params=params, action_name="search"
        )

    async def _get_user(self, c: GitLabGetUserConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", "/user", action_name="get_user"
        )

    # ------------------------------------------------------------------
    # Handlers — CI/CD pipeline & job control
    # ------------------------------------------------------------------
    async def _get_pipeline(self, c: GitLabGetPipelineConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET",
            f"/projects/{_enc(c.project_id)}/pipelines/{c.pipeline_id}",
            action_name="get_pipeline",
        )

    async def _retry_pipeline(self, c: GitLabRetryPipelineConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST",
            f"/projects/{_enc(c.project_id)}/pipelines/{c.pipeline_id}/retry",
            action_name="retry_pipeline",
        )

    async def _cancel_pipeline(self, c: GitLabCancelPipelineConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST",
            f"/projects/{_enc(c.project_id)}/pipelines/{c.pipeline_id}/cancel",
            action_name="cancel_pipeline",
        )

    async def _get_job(self, c: GitLabGetJobConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/jobs/{c.job_id}",
            action_name="get_job",
        )

    async def _get_job_log(self, c: GitLabGetJobLogConfig, token, host) -> Dict[str, Any]:
        # The trace endpoint returns plain text; _gitlab_request wraps it as {"raw": ...}.
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/jobs/{c.job_id}/trace",
            action_name="get_job_log",
        )

    async def _retry_job(self, c: GitLabRetryJobConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/jobs/{c.job_id}/retry",
            action_name="retry_job",
        )

    async def _play_job(self, c: GitLabPlayJobConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/jobs/{c.job_id}/play",
            action_name="play_job",
        )

    async def _cancel_job(self, c: GitLabCancelJobConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/jobs/{c.job_id}/cancel",
            action_name="cancel_job",
        )

    # ------------------------------------------------------------------
    # Handlers — CI/CD variables
    # ------------------------------------------------------------------
    async def _list_variables(self, c: GitLabListVariablesConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/variables",
            action_name="list_variables",
        )

    async def _create_variable(self, c: GitLabCreateVariableConfig, token, host) -> Dict[str, Any]:
        body = {
            "key": c.key,
            "value": c.value,
            "variable_type": c.variable_type,
            "protected": c.protected == "true",
            "masked": c.masked == "true",
        }
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/variables",
            json_body=body, action_name="create_variable",
        )

    async def _update_variable(self, c: GitLabUpdateVariableConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "PUT", f"/projects/{_enc(c.project_id)}/variables/{_enc(c.key)}",
            json_body={"value": c.value}, action_name="update_variable",
        )

    async def _delete_variable(self, c: GitLabDeleteVariableConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE", f"/projects/{_enc(c.project_id)}/variables/{_enc(c.key)}",
            action_name="delete_variable",
        )

    # ------------------------------------------------------------------
    # Handlers — Merge Request review
    # ------------------------------------------------------------------
    async def _approve_merge_request(self, c: GitLabApproveMergeRequestConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST",
            f"/projects/{_enc(c.project_id)}/merge_requests/{c.merge_request_iid}/approve",
            action_name="approve_merge_request",
        )

    async def _unapprove_merge_request(self, c: GitLabUnapproveMergeRequestConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST",
            f"/projects/{_enc(c.project_id)}/merge_requests/{c.merge_request_iid}/unapprove",
            action_name="unapprove_merge_request",
        )

    async def _list_notes(self, c: GitLabListNotesConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET",
            f"/projects/{_enc(c.project_id)}/{c.noteable_type}/{c.noteable_iid}/notes",
            action_name="list_notes",
        )

    # ------------------------------------------------------------------
    # Handlers — Issues (delete)
    # ------------------------------------------------------------------
    async def _delete_issue(self, c: GitLabDeleteIssueConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE", f"/projects/{_enc(c.project_id)}/issues/{c.issue_iid}",
            action_name="delete_issue",
        )

    # ------------------------------------------------------------------
    # Handlers — Labels
    # ------------------------------------------------------------------
    async def _list_labels(self, c: GitLabListLabelsConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/labels",
            action_name="list_labels",
        )

    async def _create_label(self, c: GitLabCreateLabelConfig, token, host) -> Dict[str, Any]:
        body = {"name": c.name, "color": c.color, "description": c.description}
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/labels",
            json_body=body, action_name="create_label",
        )

    async def _delete_label(self, c: GitLabDeleteLabelConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE", f"/projects/{_enc(c.project_id)}/labels/{_enc(c.label_id)}",
            action_name="delete_label",
        )

    # ------------------------------------------------------------------
    # Handlers — Milestones
    # ------------------------------------------------------------------
    async def _list_milestones(self, c: GitLabListMilestonesConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/milestones",
            params={"state": c.state or None}, action_name="list_milestones",
        )

    async def _create_milestone(self, c: GitLabCreateMilestoneConfig, token, host) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "description": c.description,
            "due_date": c.due_date,
            "start_date": c.start_date,
        }
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/milestones",
            json_body=body, action_name="create_milestone",
        )

    # ------------------------------------------------------------------
    # Handlers — Members
    # ------------------------------------------------------------------
    async def _add_member(self, c: GitLabAddMemberConfig, token, host) -> Dict[str, Any]:
        body = {"user_id": int(c.user_id), "access_level": int(c.access_level)}
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/members",
            json_body=body, action_name="add_member",
        )

    async def _remove_member(self, c: GitLabRemoveMemberConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE", f"/projects/{_enc(c.project_id)}/members/{c.user_id}",
            action_name="remove_member",
        )

    # ------------------------------------------------------------------
    # Handlers — Releases (read)
    # ------------------------------------------------------------------
    async def _list_releases(self, c: GitLabListReleasesConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/releases",
            action_name="list_releases",
        )

    async def _get_release(self, c: GitLabGetReleaseConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/releases/{_enc(c.tag_name)}",
            action_name="get_release",
        )

    # ------------------------------------------------------------------
    # Handlers — Commit status
    # ------------------------------------------------------------------
    async def _set_commit_status(self, c: GitLabSetCommitStatusConfig, token, host) -> Dict[str, Any]:
        body = {
            "state": c.state,
            "name": c.name,
            "target_url": c.target_url,
            "description": c.description,
        }
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/statuses/{c.sha}",
            json_body=body, action_name="set_commit_status",
        )

    # ------------------------------------------------------------------
    # Handlers — Environments
    # ------------------------------------------------------------------
    async def _list_environments(self, c: GitLabListEnvironmentsConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/environments",
            action_name="list_environments",
        )

    async def _create_environment(self, c: GitLabCreateEnvironmentConfig, token, host) -> Dict[str, Any]:
        body = {"name": c.name, "external_url": c.external_url}
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/environments",
            json_body=body, action_name="create_environment",
        )

    async def _stop_environment(self, c: GitLabStopEnvironmentConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST",
            f"/projects/{_enc(c.project_id)}/environments/{c.environment_id}/stop",
            action_name="stop_environment",
        )

    async def _delete_environment(self, c: GitLabDeleteEnvironmentConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE",
            f"/projects/{_enc(c.project_id)}/environments/{c.environment_id}",
            action_name="delete_environment",
        )

    # ------------------------------------------------------------------
    # Handlers — Deployments
    # ------------------------------------------------------------------
    async def _list_deployments(self, c: GitLabListDeploymentsConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/deployments",
            params={"environment": c.environment}, action_name="list_deployments",
        )

    async def _get_deployment(self, c: GitLabGetDeploymentConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET",
            f"/projects/{_enc(c.project_id)}/deployments/{c.deployment_id}",
            action_name="get_deployment",
        )

    async def _create_deployment(self, c: GitLabCreateDeploymentConfig, token, host) -> Dict[str, Any]:
        body = {"environment": c.environment, "sha": c.sha, "ref": c.ref, "status": c.status}
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/deployments",
            json_body=body, action_name="create_deployment",
        )

    # ------------------------------------------------------------------
    # Handlers — Wikis
    # ------------------------------------------------------------------
    async def _list_wikis(self, c: GitLabListWikisConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/wikis",
            action_name="list_wikis",
        )

    async def _get_wiki(self, c: GitLabGetWikiConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/wikis/{_enc(c.slug)}",
            action_name="get_wiki",
        )

    async def _create_wiki(self, c: GitLabCreateWikiConfig, token, host) -> Dict[str, Any]:
        body = {"title": c.title, "content": c.content}
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/wikis",
            json_body=body, action_name="create_wiki",
        )

    async def _update_wiki(self, c: GitLabUpdateWikiConfig, token, host) -> Dict[str, Any]:
        body = {"title": c.title, "content": c.content}
        return await _gitlab_request(
            host, token, "PUT", f"/projects/{_enc(c.project_id)}/wikis/{_enc(c.slug)}",
            json_body=body, action_name="update_wiki",
        )

    async def _delete_wiki(self, c: GitLabDeleteWikiConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE", f"/projects/{_enc(c.project_id)}/wikis/{_enc(c.slug)}",
            action_name="delete_wiki",
        )

    # ------------------------------------------------------------------
    # Handlers — Protected branches
    # ------------------------------------------------------------------
    async def _list_protected_branches(self, c: GitLabListProtectedBranchesConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/protected_branches",
            action_name="list_protected_branches",
        )

    async def _protect_branch(self, c: GitLabProtectBranchConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/protected_branches",
            params={"name": c.name}, action_name="protect_branch",
        )

    async def _unprotect_branch(self, c: GitLabUnprotectBranchConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE",
            f"/projects/{_enc(c.project_id)}/protected_branches/{_enc(c.name)}",
            action_name="unprotect_branch",
        )

    # ------------------------------------------------------------------
    # Handlers — Todos (user-scoped)
    # ------------------------------------------------------------------
    async def _list_todos(self, c: GitLabListTodosConfig, token, host) -> Dict[str, Any]:
        # GitLab rejects an empty state ("state does not have a valid value");
        # only send a whitelisted value.
        state = c.state if c.state in ("pending", "done") else None
        return await _gitlab_request(
            host, token, "GET", "/todos", params={"state": state},
            action_name="list_todos",
        )

    async def _mark_todo_done(self, c: GitLabMarkTodoDoneConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST", f"/todos/{c.todo_id}/mark_as_done",
            action_name="mark_todo_done",
        )

    async def _mark_all_todos_done(self, c: GitLabMarkAllTodosDoneConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "POST", "/todos/mark_as_done", action_name="mark_all_todos_done",
        )

    # ------------------------------------------------------------------
    # Handlers — Project hooks (management)
    # ------------------------------------------------------------------
    async def _list_hooks(self, c: GitLabListHooksConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/projects/{_enc(c.project_id)}/hooks",
            action_name="list_hooks",
        )

    async def _create_hook(self, c: GitLabCreateHookConfig, token, host) -> Dict[str, Any]:
        body = {"url": c.url, "token": c.token, "push_events": c.push_events == "true"}
        return await _gitlab_request(
            host, token, "POST", f"/projects/{_enc(c.project_id)}/hooks",
            json_body=body, action_name="create_hook",
        )

    async def _delete_hook(self, c: GitLabDeleteHookConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE", f"/projects/{_enc(c.project_id)}/hooks/{c.hook_id}",
            action_name="delete_hook",
        )

    # ------------------------------------------------------------------
    # Handlers — Releases (update / delete)
    # ------------------------------------------------------------------
    async def _update_release(self, c: GitLabUpdateReleaseConfig, token, host) -> Dict[str, Any]:
        body = {"name": c.name, "description": c.description}
        return await _gitlab_request(
            host, token, "PUT", f"/projects/{_enc(c.project_id)}/releases/{_enc(c.tag_name)}",
            json_body=body, action_name="update_release",
        )

    async def _delete_release(self, c: GitLabDeleteReleaseConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "DELETE", f"/projects/{_enc(c.project_id)}/releases/{_enc(c.tag_name)}",
            action_name="delete_release",
        )

    # ------------------------------------------------------------------
    # Handlers — Epics (group-scoped, Premium)
    # ------------------------------------------------------------------
    async def _list_epics(self, c: GitLabListEpicsConfig, token, host) -> Dict[str, Any]:
        return await _gitlab_request(
            host, token, "GET", f"/groups/{_enc(c.group_id)}/epics",
            params={"state": c.state or None}, action_name="list_epics",
        )

    async def _create_epic(self, c: GitLabCreateEpicConfig, token, host) -> Dict[str, Any]:
        body = {"title": c.title, "description": c.description}
        return await _gitlab_request(
            host, token, "POST", f"/groups/{_enc(c.group_id)}/epics",
            json_body=body, action_name="create_epic",
        )

    async def _update_epic(self, c: GitLabUpdateEpicConfig, token, host) -> Dict[str, Any]:
        body = {"title": c.title, "state_event": c.state_event or None}
        return await _gitlab_request(
            host, token, "PUT", f"/groups/{_enc(c.group_id)}/epics/{c.epic_iid}",
            json_body=body, action_name="update_epic",
        )
