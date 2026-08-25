"""
GitHub REST API automation node.

This node provides GitHub operations in workflows via direct REST API calls.
Uses httpx for high-performance async HTTP requests.

API Reference: https://docs.github.com/en/rest
"""

import json
import logging
import re
import secrets
import time
from typing import ClassVar, Dict, Any, Optional, Tuple, Union, Literal, List, Annotated

import httpx
from pydantic import BaseModel, Field, Discriminator, ConfigDict

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import load_paginated_options, require_credential_token
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.github import GITHUB_REQUESTED_SCOPES, GITHUB_SCOPES
from utils.webhook_signatures import verify_hmac_sha256_hex

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"

_GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# ============================================================================
# Webhook trigger helpers
# ============================================================================


def _github_token_from_credential(credential: Dict[str, Any]) -> Optional[str]:
    """Extract a bearer token from a decrypted GitHub credential (OAuth or PAT)."""
    return (credential or {}).get("access_token") or (credential or {}).get(
        "personal_access_token"
    )


async def register_github_webhook(
    token: str,
    owner: str,
    repo: str,
    webhook_url: str,
    secret: str,
    events: List[str],
) -> int:
    """Create a repository webhook and return its numeric hook id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/hooks",
            headers={"Authorization": f"Bearer {token}", **_GITHUB_API_HEADERS},
            json={
                "name": "web",
                "active": True,
                "events": events or ["push"],
                "config": {
                    "url": webhook_url,
                    "content_type": "json",
                    "secret": secret,
                    "insecure_ssl": "0",
                },
            },
        )
        response.raise_for_status()
        return response.json().get("id")


async def unregister_github_webhook(
    token: str, owner: str, repo: str, hook_id: int
) -> None:
    """Delete a repository webhook. A missing hook (404) is treated as done."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/hooks/{hook_id}",
            headers={"Authorization": f"Bearer {token}", **_GITHUB_API_HEADERS},
        )
        if response.status_code not in (204, 404):
            response.raise_for_status()


async def list_github_webhooks(token: str, owner: str, repo: str) -> List[Dict[str, Any]]:
    """List the repository's webhooks (id + config.url is what we consume)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/hooks",
            headers={"Authorization": f"Bearer {token}", **_GITHUB_API_HEADERS},
            params={"per_page": 100},
        )
        response.raise_for_status()
        return response.json() or []


# ============================================================================
# GitHub Credential Schemas
# ============================================================================


class GithubOAuthCredential(BaseModel):
    """OAuth 2.0 credential for GitHub.
    Tokens are obtained via OAuth flow, not entered manually.

    Register OAuth app at: https://github.com/settings/developers
    """

    credential_type: Literal["github_oauth"] = Field(
        "github_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(
        None, title="Token Expiry"
    )  # ISO 8601 (only if expiring tokens enabled)
    login: Optional[str] = Field(None, title="GitHub Username")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "github",
            # Derived from nodes/scopes/github.py so the request cannot drift
            # from what the operations need — add a scope by declaring it on an
            # operation, not here.
            "x-oauth-scopes": GITHUB_REQUESTED_SCOPES,
        }
    )


class GithubPATCredential(BaseModel):
    """Personal Access Token authentication for GitHub REST API.

    Get your PAT at: https://github.com/settings/tokens
    """

    credential_type: Literal["github_pat"] = Field(
        "github_pat", json_schema_extra={"ui:hidden": True}
    )
    personal_access_token: str = Field(
        ...,
        title="Personal Access Token",
        description="GitHub Personal Access Token with appropriate scopes",
        json_schema_extra={
            "ui:widget": "password",
        },
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://github.com/settings/tokens"}
    )


# Union type - OAuth shown first in UI
GithubRestCredential = Union[GithubOAuthCredential, GithubPATCredential]


# ============================================================================
# GitHub Configuration Models (One per action)
# ============================================================================


class GithubGetRepositoryConfig(BaseModel):
    """Get information about a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_repository"] = Field(
        default="get_repository",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Get Repository",
            "x-keywords": ["repo details", "repo info", "repository metadata"],
        },
        title="Get Repository",
    )
    owner: str = Field(
        ..., title="Owner", description="Repository owner (username or organization)"
    )
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubListRepositoriesConfig(BaseModel):
    """List repositories for the authenticated user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_authenticated_user_repos"] = Field(
        default="list_authenticated_user_repos",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Authenticated User Repos",
            "x-keywords": ["my repos", "my repositories", "own repos", "repos i own"],
        },
        title="List Authenticated User Repos",
    )
    visibility: Optional[Literal["all", "public", "private"]] = Field(
        default="all", title="Visibility", description="Filter by repository visibility"
    )
    sort: Optional[Literal["created", "updated", "pushed", "full_name"]] = Field(
        default="updated", title="Sort By", description="Sort repositories by"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubListIssuesConfig(BaseModel):
    """List issues for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issues"] = Field(
        default="list_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issues",
            "x-keywords": [
                "repo issues",
                "all issues",
                "open issues",
                "browse issues",
                "issue list",
            ],
        },
        title="List Issues",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    state: Optional[Literal["open", "closed", "all"]] = Field(
        default="open", title="State", description="Filter by issue state"
    )
    labels: Optional[str] = Field(
        default=None, title="Labels", description="Comma-separated list of label names"
    )
    assignee: Optional[str] = Field(
        default=None,
        title="Assignee",
        description="Filter by assignee username, 'none', or '*'",
    )
    sort: Optional[Literal["created", "updated", "comments"]] = Field(
        default="created", title="Sort By", description="Sort issues by"
    )
    direction: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Direction", description="Sort direction"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubGetIssueConfig(BaseModel):
    """Get a specific issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue"] = Field(
        default="get_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue",
            "x-keywords": [
                "single issue",
                "one issue",
                "issue details",
                "fetch issue",
                "issue by number",
            ],
        },
        title="Get Issue",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="The issue number")


class GithubCreateIssueConfig(BaseModel):
    """Create a new issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_issue"] = Field(
        default="create_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Create Issue",
            "x-keywords": [
                "new issue",
                "file issue",
                "open issue",
                "report bug",
                "log issue",
                "raise ticket",
            ],
        },
        title="Create Issue",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    title: str = Field(..., title="Title", description="Issue title")
    body: Optional[str] = Field(
        default=None,
        title="Body",
        description="Issue body content (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    labels: Optional[List[str]] = Field(
        default=None, title="Labels", description="Array of label names"
    )
    assignees: Optional[List[str]] = Field(
        default=None, title="Assignees", description="Array of usernames to assign"
    )


class GithubUpdateIssueConfig(BaseModel):
    """Update an existing issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_issue"] = Field(
        default="update_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Update Issue",
            "x-keywords": [
                "edit issue",
                "change issue",
                "close issue",
                "reassign issue",
                "modify issue",
            ],
        },
        title="Update Issue",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="The issue number")
    title: Optional[str] = Field(
        default=None, title="Title", description="New issue title"
    )
    body: Optional[str] = Field(
        default=None,
        title="Body",
        description="New issue body content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    state: Optional[Literal["open", "closed"]] = Field(
        default=None, title="State", description="Issue state"
    )
    labels: Optional[List[str]] = Field(
        default=None, title="Labels", description="Array of label names"
    )
    assignees: Optional[List[str]] = Field(
        default=None, title="Assignees", description="Array of usernames to assign"
    )


class GithubListPullRequestsConfig(BaseModel):
    """List pull requests for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pull_requests"] = Field(
        default="list_pull_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "List Pull Requests",
            "x-keywords": [
                "repo prs",
                "open pull requests",
                "all prs",
                "browse pull requests",
                "pr list",
            ],
        },
        title="List Pull Requests",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    state: Optional[Literal["open", "closed", "all"]] = Field(
        default="open", title="State", description="Filter by PR state"
    )
    head: Optional[str] = Field(
        default=None,
        title="Head",
        description="Filter by head branch (format: user:branch)",
    )
    base: Optional[str] = Field(
        default=None, title="Base", description="Filter by base branch"
    )
    sort: Optional[Literal["created", "updated", "popularity", "long-running"]] = Field(
        default="created", title="Sort By", description="Sort PRs by"
    )
    direction: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Direction", description="Sort direction"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubGetPullRequestConfig(BaseModel):
    """Get a specific pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_pull_request"] = Field(
        default="get_pull_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Get Pull Request",
            "x-keywords": [
                "single pr",
                "one pull request",
                "pr details",
                "fetch pr",
                "pr by number",
            ],
        },
        title="Get Pull Request",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The pull request number"
    )


class GithubCreatePullRequestConfig(BaseModel):
    """Create a new pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_pull_request"] = Field(
        default="create_pull_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Create Pull Request",
            "x-keywords": [
                "open pr",
                "new pull request",
                "raise pr",
                "submit pr",
                "propose changes",
            ],
        },
        title="Create Pull Request",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    title: str = Field(..., title="Title", description="Pull request title")
    head: str = Field(
        ...,
        title="Head Branch",
        description="The branch containing changes (format: branch or user:branch)",
    )
    base: str = Field(..., title="Base Branch", description="The branch to merge into")
    body: Optional[str] = Field(
        default=None,
        title="Body",
        description="Pull request body content (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    draft: Optional[bool] = Field(
        default=False, title="Draft", description="Create as a draft PR"
    )


class GithubListCommitsConfig(BaseModel):
    """List commits in a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_commits"] = Field(
        default="list_commits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "List Commits",
            "x-keywords": [
                "repo commits",
                "commit history",
                "git log",
                "all commits",
                "browse commits",
            ],
        },
        title="List Commits",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    sha: Optional[str] = Field(
        default=None,
        title="SHA/Branch",
        description="SHA or branch to list commits from",
    )
    path: Optional[str] = Field(
        default=None, title="Path", description="Only commits containing this file path"
    )
    author: Optional[str] = Field(
        default=None, title="Author", description="Filter by author username or email"
    )
    since: Optional[str] = Field(
        default=None,
        title="Since",
        description="Only commits after this date (ISO 8601 format)",
    )
    until: Optional[str] = Field(
        default=None,
        title="Until",
        description="Only commits before this date (ISO 8601 format)",
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubGetCommitConfig(BaseModel):
    """Get a specific commit"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_commit"] = Field(
        default="get_commit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "Get Commit",
            "x-keywords": [
                "single commit",
                "one commit",
                "commit details",
                "commit by sha",
                "fetch commit",
            ],
        },
        title="Get Commit",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    ref: str = Field(
        ..., title="Ref", description="Commit SHA, branch name, or tag name"
    )


class GithubListBranchesConfig(BaseModel):
    """List branches in a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_branches"] = Field(
        default="list_branches",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Branch",
            "x-is-trigger": False,
            "x-display-name": "List Branches",
            "x-keywords": [
                "repo branches",
                "all branches",
                "branch list",
                "browse branches",
            ],
        },
        title="List Branches",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    protected: Optional[bool] = Field(
        default=None,
        title="Protected Only",
        description="Filter to only protected branches",
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubCreateBranchConfig(BaseModel):
    """Create a new branch"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_branch"] = Field(
        default="create_branch",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Branch",
            "x-is-trigger": False,
            "x-display-name": "Create Branch",
            "x-keywords": ["new branch", "make branch", "cut branch", "branch off"],
        },
        title="Create Branch",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    branch_name: str = Field(
        ..., title="Branch Name", description="Name for the new branch"
    )
    source_branch: Optional[str] = Field(
        default="main",
        title="Source Branch",
        description="Branch to create from (default: main)",
    )


class GithubGetFileContentsConfig(BaseModel):
    """Get the contents of a file"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_file_contents"] = Field(
        default="get_file_contents",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get File Contents",
            "x-keywords": [
                "read file",
                "file content",
                "fetch file",
                "view file",
                "download file content",
            ],
        },
        title="Get File Contents",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    path: str = Field(..., title="Path", description="Path to the file")
    ref: Optional[str] = Field(
        default=None,
        title="Ref",
        description="Branch, tag, or commit SHA (default: default branch)",
    )


class GithubCreateOrUpdateFileConfig(BaseModel):
    """Create or update a file in a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_or_update_file"] = Field(
        default="create_or_update_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Create or Update File",
            "x-keywords": [
                "write file",
                "commit file",
                "save file",
                "upsert file",
                "push file change",
            ],
        },
        title="Create or Update File",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    path: str = Field(..., title="Path", description="Path for the file")
    message: str = Field(..., title="Commit Message", description="Commit message")
    content: str = Field(
        ...,
        title="Content",
        description="File content (will be base64 encoded)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    branch: Optional[str] = Field(
        default=None,
        title="Branch",
        description="Branch to commit to (default: default branch)",
    )
    sha: Optional[str] = Field(
        default=None,
        title="SHA",
        description="SHA of existing file (required for updates)",
    )


class GithubCreateIssueCommentConfig(BaseModel):
    """Create a comment on an issue or pull request"""

    model_config = ConfigDict(populate_by_name=True)

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
                "add issue comment",
                "post issue comment",
            ],
        },
        title="Create Issue Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: Union[int, str] = Field(
        ..., title="Issue/PR Number", description="The issue or pull request number"
    )
    body: str = Field(
        ...,
        title="Comment Body",
        description="The comment content (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GithubListWorkflowRunsConfig(BaseModel):
    """List workflow runs for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workflow_runs"] = Field(
        default="list_workflow_runs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "List Workflow Runs",
            "x-keywords": [
                "actions runs",
                "ci runs",
                "pipeline runs",
                "build history",
                "workflow executions",
            ],
        },
        title="List Workflow Runs",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    branch: Optional[str] = Field(
        default=None, title="Branch", description="Filter by branch"
    )
    event: Optional[str] = Field(
        default=None,
        title="Event",
        description="Filter by event (e.g., push, pull_request)",
    )
    status: Optional[
        Literal["completed", "in_progress", "queued", "requested", "waiting", "pending"]
    ] = Field(default=None, title="Status", description="Filter by status")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubSearchIssuesConfig(BaseModel):
    """Search issues and pull requests"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_issues"] = Field(
        default="search_issues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Search Issues",
            "x-keywords": [
                "find issues",
                "search tickets",
                "query issues",
                "search pull requests",
                "issue search",
            ],
        },
        title="Search Issues",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Search query (e.g., 'repo:owner/repo is:issue is:open')",
    )
    sort: Optional[
        Literal[
            "comments",
            "reactions",
            "reactions-+1",
            "reactions--1",
            "reactions-smile",
            "reactions-thinking_face",
            "reactions-heart",
            "reactions-tada",
            "interactions",
            "created",
            "updated",
        ]
    ] = Field(default=None, title="Sort By", description="Sort results by")
    order: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Order", description="Sort order"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubSearchCodeConfig(BaseModel):
    """Search code across repositories"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_code"] = Field(
        default="search_code",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Code",
            "x-keywords": [
                "find code",
                "grep repos",
                "search source",
                "code search",
                "find in files",
            ],
        },
        title="Search Code",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Search query (e.g., 'repo:owner/repo extension:py class')",
    )
    sort: Optional[Literal["indexed"]] = Field(
        default=None, title="Sort By", description="Sort results by"
    )
    order: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Order", description="Sort order"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubSearchRepositoriesConfig(BaseModel):
    """Search repositories"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_repositories"] = Field(
        default="search_repositories",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Repositories",
            "x-keywords": [
                "find repos",
                "search projects",
                "repo search",
                "discover repositories",
                "query repos",
            ],
        },
        title="Search Repositories",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Search query (e.g., 'language:python stars:>1000')",
    )
    sort: Optional[Literal["stars", "forks", "help-wanted-issues", "updated"]] = Field(
        default=None, title="Sort By", description="Sort results by"
    )
    order: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Order", description="Sort order"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubMergePullRequestConfig(BaseModel):
    """Merge a pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["merge_pull_request"] = Field(
        default="merge_pull_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Merge Pull Request",
            "x-keywords": [
                "merge pr",
                "merge branch",
                "squash merge",
                "rebase merge",
                "land pr",
            ],
        },
        title="Merge Pull Request",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The pull request number"
    )
    commit_title: Optional[str] = Field(
        default=None, title="Commit Title", description="Title for the merge commit"
    )
    commit_message: Optional[str] = Field(
        default=None,
        title="Commit Message",
        description="Extra detail for the merge commit",
        json_schema_extra={"ui:widget": "textarea"},
    )
    merge_method: Optional[Literal["merge", "squash", "rebase"]] = Field(
        default="merge", title="Merge Method", description="Merge method to use"
    )


class GithubUpdatePullRequestConfig(BaseModel):
    """Update an existing pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_pull_request"] = Field(
        default="update_pull_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Update Pull Request",
            "x-keywords": [
                "edit pr",
                "change pr title",
                "close pr",
                "modify pull request",
                "retarget pr",
            ],
        },
        title="Update Pull Request",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The pull request number"
    )
    title: Optional[str] = Field(
        default=None, title="Title", description="New PR title"
    )
    body: Optional[str] = Field(
        default=None,
        title="Body",
        description="New PR body content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    state: Optional[Literal["open", "closed"]] = Field(
        default=None, title="State", description="PR state"
    )
    base: Optional[str] = Field(
        default=None, title="Base Branch", description="New base branch"
    )


class GithubListPullRequestFilesConfig(BaseModel):
    """List files changed in a pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pull_request_files"] = Field(
        default="list_pull_request_files",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "List Pull Request Files",
            "x-keywords": [
                "pr files",
                "changed files",
                "files in pr",
                "pr diff files",
                "what changed",
            ],
        },
        title="List Pull Request Files",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The pull request number"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubListReleasesConfig(BaseModel):
    """List releases for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_releases"] = Field(
        default="list_releases",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "List Releases",
            "x-keywords": [
                "repo releases",
                "all releases",
                "release list",
                "browse releases",
                "published versions",
            ],
        },
        title="List Releases",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubGetReleaseConfig(BaseModel):
    """Get a specific release"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_release"] = Field(
        default="get_release",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Get Release",
            "x-keywords": [
                "single release",
                "one release",
                "release details",
                "fetch release",
                "release by id",
            ],
        },
        title="Get Release",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    release_id: Optional[int] = Field(
        default=None,
        title="Release ID",
        description="Release ID (leave empty for latest release)",
    )


class GithubCreateReleaseConfig(BaseModel):
    """Create a new release"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_release"] = Field(
        default="create_release",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Create Release",
            "x-keywords": [
                "new release",
                "publish release",
                "cut release",
                "draft release",
                "tag release",
            ],
        },
        title="Create Release",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    tag_name: str = Field(
        ..., title="Tag Name", description="The name of the tag (e.g., v1.0.0)"
    )
    name: Optional[str] = Field(
        default=None, title="Release Name", description="The name of the release"
    )
    body: Optional[str] = Field(
        default=None,
        title="Body",
        description="Release notes content (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    draft: Optional[bool] = Field(
        default=False, title="Draft", description="Create as a draft release"
    )
    prerelease: Optional[bool] = Field(
        default=False, title="Prerelease", description="Mark as a prerelease"
    )
    target_commitish: Optional[str] = Field(
        default=None,
        title="Target",
        description="Target branch or commit SHA (default: default branch)",
    )


class GithubGetAuthenticatedUserConfig(BaseModel):
    """Get the authenticated user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_authenticated_user"] = Field(
        default="get_authenticated_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated User",
            "x-keywords": [
                "my profile",
                "current user",
                "whoami",
                "me",
                "my account",
                "logged in user",
            ],
        },
        title="Get Authenticated User",
    )


class GithubGetUserConfig(BaseModel):
    """Get a specific user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user"] = Field(
        default="get_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User",
            "x-keywords": [
                "someone profile",
                "user by username",
                "lookup user",
                "github user",
                "person profile",
            ],
        },
        title="Get User",
    )
    username: str = Field(..., title="Username", description="The GitHub username")


class GithubListIssueCommentsConfig(BaseModel):
    """List comments on an issue"""

    model_config = ConfigDict(populate_by_name=True)

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
                "read issue thread",
                "discussion comments",
            ],
        },
        title="List Issue Comments",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="The issue number")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubListLabelsConfig(BaseModel):
    """List labels for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_repo_labels"] = Field(
        default="list_repo_labels",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "List Repo Labels",
            "x-keywords": [
                "repo labels",
                "all labels",
                "available labels",
                "browse labels",
                "label list",
            ],
        },
        title="List Repo Labels",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubCreateLabelConfig(BaseModel):
    """Create a label"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_label"] = Field(
        default="create_label",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "Create Label",
            "x-keywords": [
                "new label",
                "make label",
                "add label",
                "define label",
                "color label",
            ],
        },
        title="Create Label",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    name: str = Field(..., title="Name", description="Label name")
    color: str = Field(
        ..., title="Color", description="Color hex code (without #, e.g., 'ff0000')"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Label description"
    )


class GithubAddLabelsToIssueConfig(BaseModel):
    """Add labels to an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_labels_to_issue"] = Field(
        default="add_labels_to_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Add Labels to Issue",
            "x-keywords": [
                "label issue",
                "tag issue",
                "add labels",
                "append labels",
                "attach label",
            ],
        },
        title="Add Labels to Issue",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="The issue number")
    labels: List[str] = Field(
        ..., title="Labels", description="Array of label names to add"
    )


class GithubForkRepositoryConfig(BaseModel):
    """Fork a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["fork_repository"] = Field(
        default="fork_repository",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Fork Repository",
            "x-keywords": [
                "fork repo",
                "fork this project",
                "make a fork",
                "fork into my account",
            ],
        },
        title="Fork Repository",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    organization: Optional[str] = Field(
        default=None,
        title="Organization",
        description="Organization to fork to (default: authenticated user)",
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New name for the forked repository"
    )


class GithubTriggerWorkflowDispatchConfig(BaseModel):
    """Trigger a workflow dispatch event"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["trigger_workflow_dispatch"] = Field(
        default="trigger_workflow_dispatch",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Trigger Workflow Dispatch",
            "x-keywords": [
                "run workflow",
                "start ci",
                "manually trigger",
                "kick off action",
                "dispatch event",
                "launch pipeline",
            ],
        },
        title="Trigger Workflow Dispatch",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    workflow_id: str = Field(
        ...,
        title="Workflow ID",
        description="Workflow file name (e.g., 'ci.yml') or workflow ID",
    )
    ref: str = Field(
        ..., title="Ref", description="Branch or tag to run the workflow on"
    )
    inputs: Optional[Dict[str, str]] = Field(
        default=None, title="Inputs", description="Workflow inputs (key-value pairs)"
    )


class GithubDeleteFileConfig(BaseModel):
    """Delete a file from a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_file"] = Field(
        default="delete_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Delete File",
            "x-keywords": [
                "remove file",
                "drop file",
                "delete from repo",
                "erase file",
            ],
        },
        title="Delete File",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    path: str = Field(..., title="Path", description="Path to the file")
    message: str = Field(
        ..., title="Commit Message", description="Commit message for the deletion"
    )
    sha: str = Field(..., title="SHA", description="SHA of the file being deleted")
    branch: Optional[str] = Field(
        default=None,
        title="Branch",
        description="Branch to delete from (default: default branch)",
    )


class GithubDeleteBranchConfig(BaseModel):
    """Delete a branch"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_branch"] = Field(
        default="delete_branch",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Branch",
            "x-is-trigger": False,
            "x-display-name": "Delete Branch",
            "x-keywords": [
                "remove branch",
                "drop branch",
                "prune branch",
                "delete head",
            ],
        },
        title="Delete Branch",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    branch_name: str = Field(
        ..., title="Branch Name", description="Name of the branch to delete"
    )


class GithubListTagsConfig(BaseModel):
    """List tags in a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_repo_tags"] = Field(
        default="list_repo_tags",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Repo Tags",
            "x-keywords": [
                "repo tags",
                "git tags",
                "version tags",
                "tag list",
                "release tags",
            ],
        },
        title="List Repo Tags",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubListOrganizationReposConfig(BaseModel):
    """List repositories for an organization"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_org_repos"] = Field(
        default="list_org_repos",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Org Repos",
            "x-keywords": [
                "organization repos",
                "repos in org",
                "company repositories",
                "org owned repos",
            ],
        },
        title="List Org Repos",
    )
    org: str = Field(..., title="Organization", description="Organization name")
    type: Optional[
        Literal["all", "public", "private", "forks", "sources", "member"]
    ] = Field(default="all", title="Type", description="Filter by repository type")
    sort: Optional[Literal["created", "updated", "pushed", "full_name"]] = Field(
        default="created", title="Sort By", description="Sort repositories by"
    )
    direction: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Direction", description="Sort direction"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubListCollaboratorsConfig(BaseModel):
    """List collaborators for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_repo_collaborators"] = Field(
        default="list_repo_collaborators",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Repo Collaborators",
            "x-keywords": [
                "repo collaborators",
                "people with access",
                "who can access repo",
                "repo team members",
            ],
        },
        title="List Repo Collaborators",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    affiliation: Optional[Literal["outside", "direct", "all"]] = Field(
        default="all",
        title="Affiliation",
        description="Filter by collaborator affiliation",
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Number of results per page (max 100)"
    )


class GithubCreateRepoWebhookConfig(BaseModel):
    """Create a webhook for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_repo_webhook"] = Field(
        default="create_repo_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Create Repo Webhook",
            "x-keywords": [
                "repo webhook",
                "add repo hook",
                "repository webhook",
                "wire webhook",
                "incoming hook",
            ],
        },
        title="Create Repo Webhook",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    url: str = Field(
        ..., title="Payload URL", description="URL to receive webhook payloads"
    )
    content_type: Optional[Literal["json", "form"]] = Field(
        default="json", title="Content Type", description="Content type for payloads"
    )
    events: Optional[List[str]] = Field(
        default=["push"],
        title="Events",
        description="Events that trigger the webhook (e.g., ['push', 'pull_request'])",
    )
    active: Optional[bool] = Field(
        default=True, title="Active", description="Whether the webhook is active"
    )


# ============================================================================
# Additional Comprehensive GitHub API Operations
# ============================================================================


class GithubListMilestonesConfig(BaseModel):
    """List milestones for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_milestones"] = Field(
        default="list_milestones",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Milestone",
            "x-is-trigger": False,
            "x-display-name": "List Milestones",
            "x-keywords": [
                "repo milestones",
                "all milestones",
                "milestone list",
                "browse milestones",
            ],
        },
        title="List Milestones",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    state: Optional[Literal["open", "closed", "all"]] = Field(
        default="open", title="State", description="Filter by milestone state"
    )
    sort: Optional[Literal["due_on", "completeness"]] = Field(
        default="due_on", title="Sort By", description="Sort milestones by"
    )
    direction: Optional[Literal["asc", "desc"]] = Field(
        default="asc", title="Direction", description="Sort direction"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubCreateMilestoneConfig(BaseModel):
    """Create a milestone"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_milestone"] = Field(
        default="create_milestone",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Milestone",
            "x-is-trigger": False,
            "x-display-name": "Create Milestone",
            "x-keywords": ["new milestone", "add milestone", "make milestone"],
        },
        title="Create Milestone",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    title: str = Field(..., title="Title", description="Milestone title")
    state: Optional[Literal["open", "closed"]] = Field(
        default="open", title="State", description="Milestone state"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Milestone description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    due_on: Optional[str] = Field(
        default=None,
        title="Due Date",
        description="Due date (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)",
    )


class GithubListAssigneesConfig(BaseModel):
    """List available assignees for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_assignees"] = Field(
        default="list_issue_assignees",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Assignees",
            "x-keywords": [
                "available assignees",
                "who can be assigned",
                "assignable users",
                "possible assignees",
            ],
        },
        title="List Issue Assignees",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubRequestReviewersConfig(BaseModel):
    """Request reviewers for a pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["request_pull_request_reviewers"] = Field(
        default="request_pull_request_reviewers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Request Pull Request Reviewers",
            "x-keywords": [
                "request reviewers",
                "ask for review",
                "assign reviewers",
                "add reviewer",
                "ping reviewers",
            ],
        },
        title="Request Pull Request Reviewers",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    reviewers: Optional[List[str]] = Field(
        default=None, title="Reviewers", description="Array of usernames to request"
    )
    team_reviewers: Optional[List[str]] = Field(
        default=None,
        title="Team Reviewers",
        description="Array of team slugs to request",
    )


class GithubListPullRequestReviewsConfig(BaseModel):
    """List reviews on a pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pull_request_reviews"] = Field(
        default="list_pull_request_reviews",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "List Pull Request Reviews",
            "x-keywords": [
                "pr reviews",
                "reviews on pr",
                "approvals list",
                "who reviewed",
                "review status",
            ],
        },
        title="List Pull Request Reviews",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubCreatePullRequestReviewConfig(BaseModel):
    """Create a review on a pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_pull_request_review"] = Field(
        default="create_pull_request_review",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Create Pull Request Review",
            "x-keywords": [
                "review pr",
                "approve pr",
                "submit pr review",
                "request changes",
                "leave review",
            ],
        },
        title="Create Pull Request Review",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"] = Field(
        ..., title="Review Action", description="The review action to perform"
    )
    body: Optional[str] = Field(
        default=None,
        title="Body",
        description="Review comment",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GithubListGistsConfig(BaseModel):
    """List gists for the authenticated user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_authenticated_user_gists"] = Field(
        default="list_authenticated_user_gists",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "List Authenticated User Gists",
            "x-keywords": ["my gists", "own gists", "my snippets", "personal gists"],
        },
        title="List Authenticated User Gists",
    )
    since: Optional[str] = Field(
        default=None,
        title="Since",
        description="Only gists updated after this time (ISO 8601)",
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubGetGistConfig(BaseModel):
    """Get a specific gist"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_gist"] = Field(
        default="get_gist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "Get Gist",
            "x-keywords": [
                "single gist",
                "gist details",
                "snippet by id",
                "one gist",
                "view snippet",
            ],
        },
        title="Get Gist",
    )
    gist_id: str = Field(..., title="Gist ID", description="The gist ID")


class GithubCreateGistConfig(BaseModel):
    """Create a new gist"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_gist"] = Field(
        default="create_gist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "Create Gist",
            "x-keywords": [
                "new gist",
                "make snippet",
                "paste code",
                "share snippet",
                "save gist",
            ],
        },
        title="Create Gist",
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Gist description"
    )
    public: Optional[bool] = Field(
        default=False, title="Public", description="Whether the gist is public"
    )
    filename: str = Field(..., title="Filename", description="Name for the file")
    content: str = Field(
        ...,
        title="Content",
        description="File content",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GithubStarRepositoryConfig(BaseModel):
    """Star a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["star_repository"] = Field(
        default="star_repository",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Star Repository",
            "x-keywords": ["star repo", "star this repo", "favorite repo", "add star"],
        },
        title="Star Repository",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubUnstarRepositoryConfig(BaseModel):
    """Unstar a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unstar_repository"] = Field(
        default="unstar_repository",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Unstar Repository",
            "x-keywords": [
                "unstar repo",
                "remove star",
                "unfavorite repo",
                "destar repo",
            ],
        },
        title="Unstar Repository",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubListStargazersConfig(BaseModel):
    """List stargazers for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_repo_stargazers"] = Field(
        default="list_repo_stargazers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Repo Stargazers",
            "x-keywords": [
                "stargazers",
                "who starred",
                "starred by",
                "people who starred",
                "star list",
            ],
        },
        title="List Repo Stargazers",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListForksConfig(BaseModel):
    """List forks of a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_repo_forks"] = Field(
        default="list_repo_forks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Repo Forks",
            "x-keywords": [
                "repo forks",
                "who forked",
                "forks of repo",
                "list forks",
                "downstream forks",
            ],
        },
        title="List Repo Forks",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    sort: Optional[Literal["newest", "oldest", "stargazers", "watchers"]] = Field(
        default="newest", title="Sort By", description="Sort forks by"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListContributorsConfig(BaseModel):
    """List contributors to a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_repo_contributors"] = Field(
        default="list_repo_contributors",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "List Repo Contributors",
            "x-keywords": [
                "repo contributors",
                "who contributed",
                "contributor list",
                "top committers",
                "authors of repo",
            ],
        },
        title="List Repo Contributors",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    anon: Optional[bool] = Field(
        default=False,
        title="Include Anonymous",
        description="Include anonymous contributors",
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubGetRepoLanguagesConfig(BaseModel):
    """Get languages used in a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_repo_languages"] = Field(
        default="get_repo_languages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Get Repo Languages",
            "x-keywords": [
                "repo languages",
                "programming languages",
                "language breakdown",
                "languages used",
                "tech stack",
            ],
        },
        title="Get Repo Languages",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubGetRepoTopicsConfig(BaseModel):
    """Get topics for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_repo_topics"] = Field(
        default="get_repo_topics",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Get Repo Topics",
            "x-keywords": [
                "repo topics",
                "repository tags",
                "topic list",
                "read topics",
            ],
        },
        title="Get Repo Topics",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubSetRepoTopicsConfig(BaseModel):
    """Set topics for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_repo_topics"] = Field(
        default="set_repo_topics",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Set Repo Topics",
            "x-keywords": [
                "set topics",
                "assign topics",
                "tag repo",
                "replace topics",
                "edit repo topics",
            ],
        },
        title="Set Repo Topics",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    names: List[str] = Field(
        ..., title="Topics", description="Array of topic names (lowercase, no spaces)"
    )


class GithubCompareCommitsConfig(BaseModel):
    """Compare two commits"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["compare_commits"] = Field(
        default="compare_commits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "Compare Commits",
            "x-keywords": [
                "diff commits",
                "compare branches",
                "commit diff",
                "between commits",
                "compare refs",
            ],
        },
        title="Compare Commits",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    base: str = Field(..., title="Base", description="Base branch/tag/SHA")
    head: str = Field(..., title="Head", description="Head branch/tag/SHA to compare")


class GithubListCheckRunsConfig(BaseModel):
    """List check runs for a git reference"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_commit_check_runs"] = Field(
        default="list_commit_check_runs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "List Commit Check Runs",
            "x-keywords": [
                "commit checks",
                "ci checks",
                "check runs",
                "status checks",
                "build status",
            ],
        },
        title="List Commit Check Runs",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    ref: str = Field(..., title="Ref", description="Branch name, tag, or SHA")
    status: Optional[Literal["queued", "in_progress", "completed"]] = Field(
        default=None, title="Status", description="Filter by status"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListDeploymentsConfig(BaseModel):
    """List deployments for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_deployments"] = Field(
        default="list_deployments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deployment",
            "x-is-trigger": False,
            "x-display-name": "List Deployments",
            "x-keywords": [
                "deployment history",
                "past deploys",
                "all deployments",
                "deploys list",
            ],
        },
        title="List Deployments",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    environment: Optional[str] = Field(
        default=None, title="Environment", description="Filter by environment"
    )
    ref: Optional[str] = Field(
        default=None, title="Ref", description="Filter by ref (branch/tag/SHA)"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubCreateDeploymentConfig(BaseModel):
    """Create a deployment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_deployment"] = Field(
        default="create_deployment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deployment",
            "x-is-trigger": False,
            "x-display-name": "Create Deployment",
            "x-keywords": [
                "new deploy",
                "deploy",
                "start deployment",
                "ship release",
                "trigger deploy",
            ],
        },
        title="Create Deployment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    ref: str = Field(..., title="Ref", description="Branch, tag, or SHA to deploy")
    environment: Optional[str] = Field(
        default="production", title="Environment", description="Deployment environment"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Deployment description"
    )
    auto_merge: Optional[bool] = Field(
        default=True, title="Auto Merge", description="Auto-merge the default branch"
    )


class GithubListNotificationsConfig(BaseModel):
    """List notifications for the authenticated user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_notifications"] = Field(
        default="list_notifications",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Notification",
            "x-is-trigger": False,
            "x-display-name": "List Notifications",
            "x-keywords": [
                "my notifications",
                "inbox",
                "unread alerts",
                "github alerts",
                "activity feed",
            ],
        },
        title="List Notifications",
    )
    all: Optional[bool] = Field(
        default=False, title="All", description="Include read notifications"
    )
    participating: Optional[bool] = Field(
        default=False,
        title="Participating",
        description="Only participating notifications",
    )
    since: Optional[str] = Field(
        default=None,
        title="Since",
        description="Only notifications after this time (ISO 8601)",
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubMarkNotificationsReadConfig(BaseModel):
    """Mark notifications as read"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["mark_notifications_as_read"] = Field(
        default="mark_notifications_as_read",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Notification",
            "x-is-trigger": False,
            "x-display-name": "Mark Notifications As Read",
            "x-keywords": [
                "clear notifications",
                "mark read",
                "dismiss alerts",
                "read all",
                "clear inbox",
            ],
        },
        title="Mark Notifications As Read",
    )
    last_read_at: Optional[str] = Field(
        default=None,
        title="Last Read At",
        description="Mark notifications read before this time (ISO 8601, default: now)",
    )


class GithubListOrgTeamsConfig(BaseModel):
    """List teams in an organization"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_org_teams"] = Field(
        default="list_org_teams",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "List Org Teams",
            "x-keywords": [
                "organization teams",
                "teams in org",
                "all teams",
                "team list",
            ],
        },
        title="List Org Teams",
    )
    org: str = Field(..., title="Organization", description="Organization name")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListOrgMembersConfig(BaseModel):
    """List members of an organization"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_org_members"] = Field(
        default="list_org_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "List Org Members",
            "x-keywords": [
                "organization members",
                "people in org",
                "org users",
                "members list",
            ],
        },
        title="List Org Members",
    )
    org: str = Field(..., title="Organization", description="Organization name")
    role: Optional[Literal["all", "admin", "member"]] = Field(
        default="all", title="Role", description="Filter by role"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListRepoContentsConfig(BaseModel):
    """List contents of a directory in a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_repo_directory_contents"] = Field(
        default="list_repo_directory_contents",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List Repo Directory Contents",
            "x-keywords": [
                "directory contents",
                "list folder",
                "browse repo files",
                "tree contents",
                "files in folder",
            ],
        },
        title="List Repo Directory Contents",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    path: Optional[str] = Field(
        default="", title="Path", description="Directory path (empty for root)"
    )
    ref: Optional[str] = Field(
        default=None,
        title="Ref",
        description="Branch, tag, or SHA (default: default branch)",
    )


class GithubCreateRepoFromTemplateConfig(BaseModel):
    """Create a repository from a template"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_repo_from_template"] = Field(
        default="create_repo_from_template",
        json_schema_extra={
            "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "github_rest_repo",
            "x-resource-id-path": "data.full_name",
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Create Repo from Template",
            "x-keywords": [
                "from template",
                "template repo",
                "scaffold repo",
                "clone template",
                "use template",
            ],
        },
        title="Create Repo from Template",
    )
    template_owner: str = Field(
        ..., title="Template Owner", description="Template repo owner"
    )
    template_repo: str = Field(
        ..., title="Template Repo", description="Template repo name"
    )
    name: str = Field(..., title="Name", description="Name for the new repository")
    owner: Optional[str] = Field(
        default=None,
        title="Owner",
        description="Owner for new repo (org name or omit for authenticated user)",
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Repository description"
    )
    private: Optional[bool] = Field(
        default=False, title="Private", description="Create as private repository"
    )
    include_all_branches: Optional[bool] = Field(
        default=False,
        title="Include All Branches",
        description="Include all branches, not just default",
    )


class GithubCreateIssueReactionConfig(BaseModel):
    """Add a reaction to an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_reaction_on_issue"] = Field(
        default="create_reaction_on_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Create Reaction on Issue",
            "x-keywords": [
                "react to issue",
                "thumbs up issue",
                "emoji on issue",
                "like issue",
                "add reaction",
            ],
        },
        title="Create Reaction on Issue",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="The issue number")
    content: Literal[
        "+1", "-1", "laugh", "confused", "heart", "hooray", "rocket", "eyes"
    ] = Field(..., title="Reaction", description="The reaction type")


class GithubListUserReposConfig(BaseModel):
    """List repositories for a specific user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_repos"] = Field(
        default="list_user_repos",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List User Repos",
            "x-keywords": [
                "user repos",
                "someone elses repos",
                "repos by user",
                "another users repos",
                "public repos",
            ],
        },
        title="List User Repos",
    )
    username: str = Field(..., title="Username", description="The GitHub username")
    type: Optional[Literal["all", "owner", "member"]] = Field(
        default="owner", title="Type", description="Filter by repository type"
    )
    sort: Optional[Literal["created", "updated", "pushed", "full_name"]] = Field(
        default="updated", title="Sort By", description="Sort repositories by"
    )
    direction: Optional[Literal["asc", "desc"]] = Field(
        default="desc", title="Direction", description="Sort direction"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListUserFollowersConfig(BaseModel):
    """List followers of a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_followers"] = Field(
        default="list_user_followers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List User Followers",
            "x-keywords": [
                "who follows user",
                "followers list",
                "user followers",
                "people following",
            ],
        },
        title="List User Followers",
    )
    username: str = Field(..., title="Username", description="The GitHub username")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListUserFollowingConfig(BaseModel):
    """List users followed by a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_following"] = Field(
        default="list_user_following",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List User Following",
            "x-keywords": [
                "who user follows",
                "following list",
                "accounts followed",
                "people user follows",
            ],
        },
        title="List User Following",
    )
    username: str = Field(..., title="Username", description="The GitHub username")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubGetWorkflowRunConfig(BaseModel):
    """Get a specific workflow run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_workflow_run"] = Field(
        default="get_workflow_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Get Workflow Run",
            "x-keywords": [
                "single run",
                "run details",
                "ci run status",
                "one workflow run",
                "build status",
            ],
        },
        title="Get Workflow Run",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run ID", description="The workflow run ID")


class GithubCancelWorkflowRunConfig(BaseModel):
    """Cancel a workflow run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["cancel_workflow_run"] = Field(
        default="cancel_workflow_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Cancel Workflow Run",
            "x-keywords": [
                "stop run",
                "abort ci",
                "kill workflow",
                "cancel build",
                "halt pipeline",
            ],
        },
        title="Cancel Workflow Run",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run ID", description="The workflow run ID")


class GithubRerunWorkflowConfig(BaseModel):
    """Re-run a workflow"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["rerun_workflow"] = Field(
        default="rerun_workflow",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Rerun Workflow",
            "x-keywords": [
                "retry run",
                "rerun ci",
                "run again",
                "restart workflow",
                "re run build",
            ],
        },
        title="Rerun Workflow",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run ID", description="The workflow run ID")


class GithubListWorkflowsConfig(BaseModel):
    """List workflows in a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workflows"] = Field(
        default="list_workflows",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "List Workflows",
            "x-keywords": [
                "actions workflows",
                "ci pipelines",
                "available workflows",
                "yml workflows",
                "defined workflows",
            ],
        },
        title="List Workflows",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


# ==================== NEWLY ADDED CONFIG CLASSES ====================


class GithubListPullRequestReviewCommentsConfig(BaseModel):
    """List review comments on a pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pull_request_review_comments"] = Field(
        default="list_pull_request_review_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "List Pull Request Review Comments",
            "x-keywords": [
                "pr inline comments",
                "diff comments",
                "review thread comments",
                "code review comments",
            ],
        },
        title="List Pull Request Review Comments",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    sort: Literal["created", "updated"] = Field(
        default="created", title="Sort", description="Sort field"
    )
    direction: Literal["asc", "desc"] = Field(
        default="desc", title="Direction", description="Sort direction"
    )
    since: Optional[str] = Field(
        default=None,
        title="Since",
        description="Only show results updated after (ISO 8601)",
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubCreatePullRequestReviewCommentConfig(BaseModel):
    """Create a review comment on a pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_pull_request_review_comment"] = Field(
        default="create_pull_request_review_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Create Pull Request Review Comment",
            "x-keywords": [
                "comment on diff",
                "add inline comment",
                "comment on code line",
                "leave review comment",
            ],
        },
        title="Create Pull Request Review Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    body: str = Field(
        ...,
        title="Body",
        description="Comment body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    commit_id: str = Field(
        ..., title="Commit SHA", description="SHA of commit being commented on"
    )
    path: str = Field(
        ...,
        title="File Path",
        description="Relative path of the file being commented on",
    )
    line: Optional[int] = Field(
        default=None, title="Line", description="Line number in the diff"
    )
    side: Optional[Literal["LEFT", "RIGHT"]] = Field(
        default="RIGHT", title="Side", description="Side of the diff"
    )
    start_line: Optional[int] = Field(
        default=None, title="Start Line", description="First line of multi-line comment"
    )
    start_side: Optional[Literal["LEFT", "RIGHT"]] = Field(
        default=None, title="Start Side", description="Side of first line"
    )


class GithubGetPullRequestReviewCommentConfig(BaseModel):
    """Get a specific review comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_pull_request_review_comment"] = Field(
        default="get_pull_request_review_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Get Pull Request Review Comment",
            "x-keywords": [
                "single review comment",
                "one inline comment",
                "fetch diff comment",
                "review comment details",
            ],
        },
        title="Get Pull Request Review Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment ID", description="The comment ID")


class GithubUpdatePullRequestReviewCommentConfig(BaseModel):
    """Update a review comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_pull_request_review_comment"] = Field(
        default="update_pull_request_review_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Update Pull Request Review Comment",
            "x-keywords": [
                "edit review comment",
                "change pr comment",
                "modify diff comment",
                "edit code review note",
            ],
        },
        title="Update Pull Request Review Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment ID", description="The comment ID")
    body: str = Field(
        ...,
        title="Body",
        description="Comment body",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GithubDeletePullRequestReviewCommentConfig(BaseModel):
    """Delete a review comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_pull_request_review_comment"] = Field(
        default="delete_pull_request_review_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Delete Pull Request Review Comment",
            "x-keywords": [
                "remove review comment",
                "delete pr comment",
                "remove diff comment",
                "delete code review note",
            ],
        },
        title="Delete Pull Request Review Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment ID", description="The comment ID")


class GithubReplyToPullRequestReviewCommentConfig(BaseModel):
    """Reply to a review comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["reply_to_pull_request_review_comment"] = Field(
        default="reply_to_pull_request_review_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Reply to Pull Request Review Comment",
            "x-keywords": [
                "respond to review comment",
                "thread reply pr",
                "answer diff comment",
                "reply code review",
            ],
        },
        title="Reply to Pull Request Review Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    comment_id: int = Field(..., title="Comment ID", description="The comment ID")
    body: str = Field(
        ...,
        title="Body",
        description="Comment body",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GithubUpdatePullRequestReviewConfig(BaseModel):
    """Update a pending review"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_pull_request_review"] = Field(
        default="update_pull_request_review",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Update Pull Request Review",
            "x-keywords": [
                "edit pending review",
                "change review body",
                "modify pr review",
            ],
        },
        title="Update Pull Request Review",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    review_id: int = Field(..., title="Review ID", description="The review ID")
    body: str = Field(
        ...,
        title="Body",
        description="Comment body",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GithubDeletePendingPullRequestReviewConfig(BaseModel):
    """Delete a pending review"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_pending_pull_request_review"] = Field(
        default="delete_pending_pull_request_review",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Delete Pending Pull Request Review",
            "x-keywords": [
                "discard pending review",
                "cancel draft review",
                "remove unsubmitted review",
                "delete pr review",
            ],
        },
        title="Delete Pending Pull Request Review",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    review_id: int = Field(..., title="Review ID", description="The review ID")


class GithubGetPullRequestReviewCommentsConfig(BaseModel):
    """Get comments for a specific review"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_review_comments_for_review"] = Field(
        default="list_review_comments_for_review",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "List Review Comments for Review",
            "x-keywords": [
                "comments in review",
                "review thread comments",
                "show review feedback",
                "view review notes",
            ],
        },
        title="List Review Comments for Review",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    review_id: int = Field(..., title="Review ID", description="The review ID")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubSubmitPullRequestReviewConfig(BaseModel):
    """Submit a pending review"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["submit_pull_request_review"] = Field(
        default="submit_pull_request_review",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Submit Pull Request Review",
            "x-keywords": [
                "finish review",
                "approve request changes",
                "post pr review",
                "complete code review",
            ],
        },
        title="Submit Pull Request Review",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    review_id: int = Field(..., title="Review ID", description="The review ID")
    event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT", "SUBMIT"] = Field(
        ..., title="Event", description="Review event type"
    )
    body: Optional[str] = Field(
        default=None,
        title="Body",
        description="Review summary comment",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GithubDismissPullRequestReviewConfig(BaseModel):
    """Dismiss a review"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["dismiss_pull_request_review"] = Field(
        default="dismiss_pull_request_review",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Dismiss Pull Request Review",
            "x-keywords": [
                "override review",
                "dismiss approval",
                "discard pr review",
                "clear blocking review",
            ],
        },
        title="Dismiss Pull Request Review",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    review_id: int = Field(..., title="Review ID", description="The review ID")
    message: str = Field(..., title="Message", description="Dismissal message")
    event: Optional[Literal["DISMISS"]] = Field(
        default="DISMISS", title="Event", description=""
    )


class GithubListPullRequestCommitsConfig(BaseModel):
    """List commits on a pull request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pull_request_commits"] = Field(
        default="list_pull_request_commits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "List Pull Request Commits",
            "x-keywords": [
                "commits in pr",
                "pr commit history",
                "show pull request commits",
            ],
        },
        title="List Pull Request Commits",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubCheckIfPullRequestMergedConfig(BaseModel):
    """Check if a pull request has been merged"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["check_pull_request_merged"] = Field(
        default="check_pull_request_merged",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Check Pull Request Merged",
            "x-keywords": [
                "is pr merged",
                "merge status",
                "was pull request merged",
                "check merged",
            ],
        },
        title="Check Pull Request Merged",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )


class GithubUpdatePullRequestBranchConfig(BaseModel):
    """Update pull request branch with latest base branch"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_pull_request_branch"] = Field(
        default="update_pull_request_branch",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Update Pull Request Branch",
            "x-keywords": [
                "sync pr branch",
                "update with base",
                "pull latest into pr",
                "rebase pr branch",
            ],
        },
        title="Update Pull Request Branch",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    pull_number: int = Field(
        ..., title="Pull Request Number", description="The PR number"
    )
    expected_head_sha: Optional[str] = Field(
        default=None,
        title="Expected Head SHA",
        description="Expected SHA of PR's HEAD ref",
    )


# Generated Config Classes


class GithubUpdateRepositoryConfig(BaseModel):
    """Update repository settings"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_repository"] = Field(
        default="update_repository",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Update Repository",
            "x-keywords": [
                "edit repo settings",
                "rename repo",
                "change repository",
                "repo config",
            ],
        },
        title="Update Repository",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    name: Optional[str] = Field(
        default=None, title="Name", description="Repository name"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Repository description"
    )
    homepage: Optional[str] = Field(
        default=None, title="Homepage", description="Homepage URL"
    )
    private: Optional[bool] = Field(
        default=None, title="Private", description="Set repository visibility"
    )
    has_issues: Optional[bool] = Field(
        default=None, title="Has Issues", description="Enable issues"
    )
    has_projects: Optional[bool] = Field(
        default=None, title="Has Projects", description="Enable projects"
    )
    has_wiki: Optional[bool] = Field(
        default=None, title="Has Wiki", description="Enable wiki"
    )
    default_branch: Optional[str] = Field(
        default=None, title="Default Branch", description="Default branch name"
    )


class GithubDeleteRepositoryConfig(BaseModel):
    """Delete a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_repository"] = Field(
        default="delete_repository",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Delete Repository",
            "x-keywords": ["remove repo", "destroy repository", "delete project repo"],
        },
        title="Delete Repository",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubCreateRepositoryForAuthenticatedUserConfig(BaseModel):
    """Create a repository for the authenticated user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_repo_for_authenticated_user"] = Field(
        default="create_repo_for_authenticated_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "github_rest_repo",
            "x-resource-id-path": "data.full_name",
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Create Repo for Authenticated User",
            "x-keywords": [
                "new repo",
                "make my repository",
                "create personal repo",
                "start new project",
            ],
        },
        title="Create Repo for Authenticated User",
    )
    name: str = Field(..., title="Name", description="Name")
    description: Optional[str] = Field(
        default=None, title="Description", description="Repository description"
    )
    homepage: Optional[str] = Field(
        default=None, title="Homepage", description="Homepage URL"
    )
    private: Optional[bool] = Field(
        default=False, title="Private", description="Create private repository"
    )
    has_issues: Optional[bool] = Field(
        default=True, title="Has Issues", description="Enable issues"
    )
    has_projects: Optional[bool] = Field(
        default=True, title="Has Projects", description="Enable projects"
    )
    has_wiki: Optional[bool] = Field(
        default=True, title="Has Wiki", description="Enable wiki"
    )
    auto_init: Optional[bool] = Field(
        default=False, title="Auto Init", description="Initialize with README"
    )


class GithubTransferRepositoryConfig(BaseModel):
    """Transfer repository ownership"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["transfer_repository"] = Field(
        default="transfer_repository",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Transfer Repository",
            "x-keywords": [
                "change repo owner",
                "move repository",
                "hand off repo",
                "give repo ownership",
            ],
        },
        title="Transfer Repository",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    new_owner: str = Field(..., title="New Owner", description="New Owner")
    team_ids: Optional[List[int]] = Field(
        default=None, title="Team IDs", description="Team IDs for organization transfer"
    )


class GithubLockIssueConfig(BaseModel):
    """Lock an issue conversation"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["lock_issue"] = Field(
        default="lock_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Lock Issue",
            "x-keywords": [
                "freeze issue thread",
                "lock conversation",
                "disable issue comments",
                "lock issue thread",
            ],
        },
        title="Lock Issue",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="Issue Number")
    lock_reason: Optional[
        Literal["off-topic", "too heated", "resolved", "spam"]
    ] = Field(default=None, title="Lock Reason", description="Reason for locking")


class GithubUnlockIssueConfig(BaseModel):
    """Unlock an issue conversation"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unlock_issue"] = Field(
        default="unlock_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Unlock Issue",
            "x-keywords": [
                "unfreeze issue thread",
                "unlock conversation",
                "reenable issue comments",
                "unlock issue thread",
            ],
        },
        title="Unlock Issue",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="Issue Number")


class GithubGetIssueCommentConfig(BaseModel):
    """Get a specific issue comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_issue_comment"] = Field(
        default="get_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Get Issue Comment",
            "x-keywords": [
                "fetch issue comment",
                "view single comment",
                "read issue note",
            ],
        },
        title="Get Issue Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")


class GithubUpdateIssueCommentConfig(BaseModel):
    """Update an issue comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_issue_comment"] = Field(
        default="update_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Update Issue Comment",
            "x-keywords": [
                "edit issue comment",
                "change issue note",
                "modify issue reply",
            ],
        },
        title="Update Issue Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")
    body: str = Field(
        ...,
        title="Body",
        description="Body",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GithubDeleteIssueCommentConfig(BaseModel):
    """Delete an issue comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue_comment"] = Field(
        default="delete_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Comment",
            "x-keywords": [
                "remove issue comment",
                "delete issue note",
                "erase issue reply",
            ],
        },
        title="Delete Issue Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")


class GithubGetLabelConfig(BaseModel):
    """Get a label"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_label"] = Field(
        default="get_label",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "Get Label",
            "x-keywords": [
                "fetch single label",
                "view one label",
                "read label details",
            ],
        },
        title="Get Label",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    name: str = Field(..., title="Name", description="Name")


class GithubUpdateLabelConfig(BaseModel):
    """Update a label"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_label"] = Field(
        default="update_label",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "Update Label",
            "x-keywords": [
                "edit label",
                "rename label",
                "change label color",
                "modify tag",
            ],
        },
        title="Update Label",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    name: str = Field(..., title="Name", description="Name")
    new_name: Optional[str] = Field(
        default=None, title="New Name", description="New label name"
    )
    color: Optional[str] = Field(
        default=None, title="Color", description="6-character hex code without #"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Label description"
    )


class GithubDeleteLabelConfig(BaseModel):
    """Delete a label"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_label"] = Field(
        default="delete_label",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "Delete Label",
            "x-keywords": ["remove label", "delete tag", "erase label"],
        },
        title="Delete Label",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    name: str = Field(..., title="Name", description="Name")


class GithubSetIssueLabelsConfig(BaseModel):
    """Set labels for an issue (replaces all)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["set_issue_labels"] = Field(
        default="set_issue_labels",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Set Issue Labels",
            "x-keywords": [
                "replace issue labels",
                "overwrite labels",
                "set all labels",
                "relabel issue",
            ],
        },
        title="Set Issue Labels",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="Issue Number")
    labels: List[Any] = Field(..., title="Labels", description="Labels")


class GithubRemoveAllIssueLabelsConfig(BaseModel):
    """Remove all labels from an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_all_labels_from_issue"] = Field(
        default="remove_all_labels_from_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Remove All Labels from Issue",
            "x-keywords": [
                "clear issue labels",
                "strip all labels",
                "unlabel issue",
                "remove every label",
            ],
        },
        title="Remove All Labels from Issue",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="Issue Number")


class GithubRemoveIssueLabelConfig(BaseModel):
    """Remove a label from an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_label_from_issue"] = Field(
        default="remove_label_from_issue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Remove Label from Issue",
            "x-keywords": [
                "unlabel one tag",
                "take off single label",
                "remove specific label",
                "detach label",
            ],
        },
        title="Remove Label from Issue",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="Issue Number")
    name: str = Field(..., title="Name", description="Name")


class GithubGetMilestoneConfig(BaseModel):
    """Get a milestone"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_milestone"] = Field(
        default="get_milestone",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Milestone",
            "x-is-trigger": False,
            "x-display-name": "Get Milestone",
            "x-keywords": [
                "fetch milestone",
                "view single milestone",
                "read milestone details",
            ],
        },
        title="Get Milestone",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    milestone_number: int = Field(
        ..., title="Milestone Number", description="Milestone Number"
    )


class GithubUpdateMilestoneConfig(BaseModel):
    """Update a milestone"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_milestone"] = Field(
        default="update_milestone",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Milestone",
            "x-is-trigger": False,
            "x-display-name": "Update Milestone",
            "x-keywords": [
                "edit milestone",
                "rename milestone",
                "change due date",
                "modify milestone",
            ],
        },
        title="Update Milestone",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    milestone_number: int = Field(
        ..., title="Milestone Number", description="Milestone Number"
    )
    title: Optional[str] = Field(
        default=None, title="Title", description="Milestone title"
    )
    state: Optional[Literal["open", "closed"]] = Field(
        default=None, title="State", description="Milestone state"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Milestone description"
    )
    due_on: Optional[str] = Field(
        default=None, title="Due On", description="Due date (ISO 8601)"
    )


class GithubDeleteMilestoneConfig(BaseModel):
    """Delete a milestone"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_milestone"] = Field(
        default="delete_milestone",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Milestone",
            "x-is-trigger": False,
            "x-display-name": "Delete Milestone",
            "x-keywords": ["remove milestone", "delete milestone target"],
        },
        title="Delete Milestone",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    milestone_number: int = Field(
        ..., title="Milestone Number", description="Milestone Number"
    )


class GithubUpdateReleaseConfig(BaseModel):
    """Update a release"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_release"] = Field(
        default="update_release",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Update Release",
            "x-keywords": [
                "edit release",
                "change release notes",
                "modify version",
                "rename release",
            ],
        },
        title="Update Release",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    release_id: int = Field(..., title="Release Id", description="Release Id")
    tag_name: Optional[str] = Field(
        default=None, title="Tag Name", description="Git tag name"
    )
    name: Optional[str] = Field(default=None, title="Name", description="Release name")
    body: Optional[str] = Field(
        default=None,
        title="Body",
        description="Release notes",
        json_schema_extra={"ui:widget": "textarea"},
    )
    draft: Optional[bool] = Field(
        default=None, title="Draft", description="Mark as draft"
    )
    prerelease: Optional[bool] = Field(
        default=None, title="Prerelease", description="Mark as prerelease"
    )


class GithubDeleteReleaseConfig(BaseModel):
    """Delete a release"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_release"] = Field(
        default="delete_release",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Delete Release",
            "x-keywords": ["remove release", "delete version", "erase release"],
        },
        title="Delete Release",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    release_id: int = Field(..., title="Release Id", description="Release Id")


class GithubGetLatestReleaseConfig(BaseModel):
    """Get the latest release"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_latest_release"] = Field(
        default="get_latest_release",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Get Latest Release",
            "x-keywords": ["newest release", "most recent version", "current release"],
        },
        title="Get Latest Release",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubGetReleaseByTagConfig(BaseModel):
    """Get a release by tag name"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_release_by_tag"] = Field(
        default="get_release_by_tag",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Get Release by Tag",
            "x-keywords": [
                "release for tag",
                "find release by version",
                "lookup release tag",
            ],
        },
        title="Get Release by Tag",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    tag: str = Field(..., title="Tag", description="Tag")


class GithubGenerateReleaseNotesConfig(BaseModel):
    """Generate release notes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["generate_release_notes"] = Field(
        default="generate_release_notes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Generate Release Notes",
            "x-keywords": [
                "auto changelog",
                "build release notes",
                "draft changelog",
                "compile release notes",
            ],
        },
        title="Generate Release Notes",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    tag_name: str = Field(..., title="Tag Name", description="Tag Name")
    target_commitish: Optional[str] = Field(
        default=None,
        title="Target Commitish",
        description="Commit/branch to base notes on",
    )
    previous_tag_name: Optional[str] = Field(
        default=None,
        title="Previous Tag Name",
        description="Previous tag to compare against",
    )
    configuration_file_path: Optional[str] = Field(
        default=None,
        title="Config File Path",
        description="Path to release notes config",
    )


class GithubListReleaseAssetsConfig(BaseModel):
    """List release assets"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_release_assets"] = Field(
        default="list_release_assets",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "List Release Assets",
            "x-keywords": [
                "release downloads",
                "release binaries",
                "show release files",
                "release attachments",
            ],
        },
        title="List Release Assets",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    release_id: int = Field(..., title="Release Id", description="Release Id")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubGetReleaseAssetConfig(BaseModel):
    """Get a release asset"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_release_asset"] = Field(
        default="get_release_asset",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Get Release Asset",
            "x-keywords": [
                "fetch release file",
                "single release asset",
                "download metadata",
                "view release binary",
            ],
        },
        title="Get Release Asset",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    asset_id: int = Field(..., title="Asset Id", description="Asset Id")


class GithubUpdateReleaseAssetConfig(BaseModel):
    """Update a release asset"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_release_asset"] = Field(
        default="update_release_asset",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Update Release Asset",
            "x-keywords": ["edit release file", "rename release asset", "change asset"],
        },
        title="Update Release Asset",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    asset_id: int = Field(..., title="Asset Id", description="Asset Id")
    name: Optional[str] = Field(
        default=None, title="Name", description="Asset filename"
    )
    label: Optional[str] = Field(
        default=None, title="Label", description="Display label"
    )


class GithubDeleteReleaseAssetConfig(BaseModel):
    """Delete a release asset"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_release_asset"] = Field(
        default="delete_release_asset",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Delete Release Asset",
            "x-keywords": [
                "remove release file",
                "delete release binary",
                "erase release asset",
            ],
        },
        title="Delete Release Asset",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    asset_id: int = Field(..., title="Asset Id", description="Asset Id")


class GithubUpdateGistConfig(BaseModel):
    """Update a gist"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_gist"] = Field(
        default="update_gist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "Update Gist",
            "x-keywords": ["edit gist", "change snippet", "modify gist files"],
        },
        title="Update Gist",
    )
    gist_id: int = Field(..., title="Gist Id", description="Gist Id")
    files: List[Any] = Field(..., title="Files", description="Files")
    description: Optional[str] = Field(
        default=None, title="Description", description="Gist description"
    )


class GithubDeleteGistConfig(BaseModel):
    """Delete a gist"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_gist"] = Field(
        default="delete_gist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "Delete Gist",
            "x-keywords": ["remove gist", "delete snippet", "erase gist"],
        },
        title="Delete Gist",
    )
    gist_id: int = Field(..., title="Gist Id", description="Gist Id")


class GithubListPublicGistsConfig(BaseModel):
    """List public gists"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_public_gists"] = Field(
        default="list_public_gists",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "List Public Gists",
            "x-keywords": [
                "browse public snippets",
                "all public gists",
                "discover gists",
            ],
        },
        title="List Public Gists",
    )
    since: Optional[str] = Field(
        default=None, title="Since", description="Only gists updated after (ISO 8601)"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListStarredGistsConfig(BaseModel):
    """List starred gists"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_starred_gists"] = Field(
        default="list_starred_gists",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "List Starred Gists",
            "x-keywords": ["my starred snippets", "favorited gists", "saved gists"],
        },
        title="List Starred Gists",
    )
    since: Optional[str] = Field(
        default=None, title="Since", description="Only gists updated after (ISO 8601)"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubStarGistConfig(BaseModel):
    """Star a gist"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["star_gist"] = Field(
        default="star_gist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "Star Gist",
            "x-keywords": ["favorite snippet", "save gist", "bookmark gist"],
        },
        title="Star Gist",
    )
    gist_id: int = Field(..., title="Gist Id", description="Gist Id")


class GithubUnstarGistConfig(BaseModel):
    """Unstar a gist"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unstar_gist"] = Field(
        default="unstar_gist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "Unstar Gist",
            "x-keywords": ["unfavorite snippet", "unsave gist", "remove gist bookmark"],
        },
        title="Unstar Gist",
    )
    gist_id: int = Field(..., title="Gist Id", description="Gist Id")


class GithubCheckIfGistIsStarredConfig(BaseModel):
    """Check if a gist is starred"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["check_gist_starred"] = Field(
        default="check_gist_starred",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "Check Gist Starred",
            "x-keywords": [
                "is gist starred",
                "gist favorite status",
                "did i star gist",
            ],
        },
        title="Check Gist Starred",
    )
    gist_id: int = Field(..., title="Gist Id", description="Gist Id")


class GithubForkGistConfig(BaseModel):
    """Fork a gist"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["fork_gist"] = Field(
        default="fork_gist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "Fork Gist",
            "x-keywords": ["copy snippet", "fork code snippet", "duplicate gist"],
        },
        title="Fork Gist",
    )
    gist_id: str = Field(..., title="Gist ID", description="The gist ID")


class GithubListGistForksConfig(BaseModel):
    """List gist forks"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_gist_forks"] = Field(
        default="list_gist_forks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "List Gist Forks",
            "x-keywords": ["gist copies", "who forked gist", "snippet forks"],
        },
        title="List Gist Forks",
    )
    gist_id: int = Field(..., title="Gist Id", description="Gist Id")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListGistCommitsConfig(BaseModel):
    """List gist commits"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_gist_commits"] = Field(
        default="list_gist_commits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "List Gist Commits",
            "x-keywords": ["gist history", "snippet revisions list", "gist change log"],
        },
        title="List Gist Commits",
    )
    gist_id: int = Field(..., title="Gist Id", description="Gist Id")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubGetGistRevisionConfig(BaseModel):
    """Get a specific gist revision"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_gist_revision"] = Field(
        default="get_gist_revision",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "Get Gist Revision",
            "x-keywords": ["gist version", "snippet revision", "historical gist"],
        },
        title="Get Gist Revision",
    )
    gist_id: int = Field(..., title="Gist Id", description="Gist Id")
    sha: str = Field(..., title="Sha", description="Sha")


class GithubListUserGistsConfig(BaseModel):
    """List gists for a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_user_gists"] = Field(
        default="list_user_gists",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Gist",
            "x-is-trigger": False,
            "x-display-name": "List User Gists",
            "x-keywords": ["someone snippets", "another user gists", "gists by user"],
        },
        title="List User Gists",
    )
    username: str = Field(..., title="Username", description="Username")
    since: Optional[str] = Field(
        default=None, title="Since", description="Only gists updated after (ISO 8601)"
    )
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListBranchesForHeadCommitConfig(BaseModel):
    """List branches where commit is the HEAD"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_branches_by_head_commit"] = Field(
        default="list_branches_by_head_commit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Branch",
            "x-is-trigger": False,
            "x-display-name": "List Branches by Head Commit",
            "x-keywords": [
                "branches at commit",
                "branches with this head",
                "branches containing commit",
                "which branch has commit",
            ],
        },
        title="List Branches by Head Commit",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    commit_sha: str = Field(..., title="Commit Sha", description="Commit Sha")


class GithubListPullRequestsForCommitConfig(BaseModel):
    """List pull requests associated with a commit"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pull_requests_by_commit"] = Field(
        default="list_pull_requests_by_commit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "List Pull Requests by Commit",
            "x-keywords": [
                "prs for commit",
                "pull requests with commit",
                "which pr has this commit",
                "prs containing commit",
            ],
        },
        title="List Pull Requests by Commit",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    commit_sha: str = Field(..., title="Commit Sha", description="Commit Sha")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubListCommitCommentsConfig(BaseModel):
    """List comments for a commit"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_commit_comments"] = Field(
        default="list_commit_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "List Commit Comments",
            "x-keywords": [
                "comments on commit",
                "commit discussion",
                "commit line comments",
            ],
        },
        title="List Commit Comments",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    commit_sha: str = Field(..., title="Commit Sha", description="Commit Sha")
    per_page: Optional[int] = Field(
        default=30, title="Per Page", description="Results per page"
    )


class GithubCreateCommitCommentConfig(BaseModel):
    """Create a comment on a commit"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_commit_comment"] = Field(
        default="create_commit_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "Create Commit Comment",
            "x-keywords": [
                "comment on commit",
                "add commit note",
                "leave commit feedback",
            ],
        },
        title="Create Commit Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    commit_sha: str = Field(..., title="Commit Sha", description="Commit Sha")
    body: str = Field(
        ...,
        title="Body",
        description="Body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    path: Optional[str] = Field(
        default=None, title="Path", description="File path for inline comment"
    )
    position: Optional[int] = Field(
        default=None, title="Position", description="Line index in diff"
    )
    line: Optional[int] = Field(
        default=None, title="Line", description="Line number (deprecated)"
    )


class GithubCreateCommitStatusConfig(BaseModel):
    """Create a commit status"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_commit_status"] = Field(
        default="create_commit_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "Create Commit Status",
            "x-keywords": [
                "set commit status",
                "mark commit state",
                "ci status check",
                "report build status",
                "set commit context",
            ],
        },
        title="Create Commit Status",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    sha: str = Field(..., title="Sha", description="Sha")
    state: str = Field(..., title="State", description="State")
    target_url: Optional[str] = Field(
        default=None, title="Target URL", description="URL for more details"
    )
    description: Optional[str] = Field(
        default=None, title="Description", description="Status description"
    )
    context: Optional[str] = Field(
        default=None, title="Context", description="Status context/label"
    )


class GithubGetRepositoryWebhookConfig(BaseModel):
    """Get a repository webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_repo_webhook"] = Field(
        default="get_repo_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Get Repo Webhook",
            "x-keywords": [
                "repo webhook config",
                "fetch hook settings",
                "webhook details",
            ],
        },
        title="Get Repo Webhook",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    hook_id: int = Field(..., title="Hook Id", description="Hook Id")


class GithubUpdateRepositoryWebhookConfig(BaseModel):
    """Update a repository webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_repo_webhook"] = Field(
        default="update_repo_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Update Repo Webhook",
            "x-keywords": [
                "change webhook url",
                "modify hook events",
                "edit repo hook",
            ],
        },
        title="Update Repo Webhook",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    hook_id: int = Field(..., title="Hook Id", description="Hook Id")
    config: Optional[Any] = Field(
        default=None, title="Config", description="Config parameter"
    )
    events: Optional[Any] = Field(
        default=None, title="Events", description="Events parameter"
    )
    active: Optional[Any] = Field(
        default=None, title="Active", description="Active parameter"
    )


class GithubDeleteRepositoryWebhookConfig(BaseModel):
    """Delete a repository webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_repo_webhook"] = Field(
        default="delete_repo_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Delete Repo Webhook",
            "x-keywords": ["remove repo webhook", "delete hook", "drop webhook"],
        },
        title="Delete Repo Webhook",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    hook_id: int = Field(..., title="Hook Id", description="Hook Id")


class GithubPingRepositoryWebhookConfig(BaseModel):
    """Ping a repository webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["ping_repo_webhook"] = Field(
        default="ping_repo_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Ping Repo Webhook",
            "x-keywords": ["ping webhook", "send hook ping", "trigger ping event"],
        },
        title="Ping Repo Webhook",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    hook_id: int = Field(..., title="Hook Id", description="Hook Id")


class GithubTestRepositoryWebhookConfig(BaseModel):
    """Test a repository webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["test_repo_webhook"] = Field(
        default="test_repo_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Test Repo Webhook",
            "x-keywords": ["test webhook", "fire push test event", "send test payload"],
        },
        title="Test Repo Webhook",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    hook_id: int = Field(..., title="Hook Id", description="Hook Id")


class GithubListWebhookDeliveriesConfig(BaseModel):
    """List webhook deliveries"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_webhook_deliveries"] = Field(
        default="list_webhook_deliveries",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Webhook Deliveries",
            "x-keywords": [
                "webhook delivery history",
                "hook delivery log",
                "past deliveries",
                "delivery attempts",
            ],
        },
        title="List Webhook Deliveries",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    hook_id: int = Field(..., title="Hook Id", description="Hook Id")


class GithubGetWebhookDeliveryConfig(BaseModel):
    """Get a webhook delivery"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_webhook_delivery"] = Field(
        default="get_webhook_delivery",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook Delivery",
            "x-keywords": [
                "single delivery details",
                "inspect delivery payload",
                "one delivery record",
            ],
        },
        title="Get Webhook Delivery",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    hook_id: int = Field(..., title="Hook Id", description="Hook Id")
    delivery_id: int = Field(..., title="Delivery Id", description="Delivery Id")


class GithubRedeliverWebhookConfig(BaseModel):
    """Redeliver a webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["redeliver_webhook"] = Field(
        default="redeliver_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Redeliver Webhook",
            "x-keywords": [
                "resend webhook",
                "redeliver hook",
                "retry delivery",
                "replay webhook",
            ],
        },
        title="Redeliver Webhook",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    hook_id: int = Field(..., title="Hook Id", description="Hook Id")
    delivery_id: int = Field(..., title="Delivery Id", description="Delivery Id")


class GithubAddRepositoryCollaboratorConfig(BaseModel):
    """Add a repository collaborator"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_repo_collaborator"] = Field(
        default="add_repo_collaborator",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Add Repo Collaborator",
            "x-keywords": [
                "invite collaborator",
                "grant repo access",
                "give someone access",
                "add contributor access",
            ],
        },
        title="Add Repo Collaborator",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    username: str = Field(..., title="Username", description="Username")
    permission: Optional[Any] = Field(
        default=None, title="Permission", description="Permission parameter"
    )


class GithubRemoveRepositoryCollaboratorConfig(BaseModel):
    """Remove a repository collaborator"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_repo_collaborator"] = Field(
        default="remove_repo_collaborator",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Remove Repo Collaborator",
            "x-keywords": ["revoke repo access", "kick collaborator", "remove access"],
        },
        title="Remove Repo Collaborator",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    username: str = Field(..., title="Username", description="Username")


class GithubGetRepositoryPermissionsConfig(BaseModel):
    """Get repository permissions for a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_repo_permissions"] = Field(
        default="get_user_repo_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Get User Repo Permissions",
            "x-keywords": [
                "user permission level",
                "what access does user have",
                "repo role for user",
                "access level",
            ],
        },
        title="Get User Repo Permissions",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    username: str = Field(..., title="Username", description="Username")


class GithubCheckIfUserIsCollaboratorConfig(BaseModel):
    """Check if a user is a collaborator"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["check_user_is_collaborator"] = Field(
        default="check_user_is_collaborator",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Check User Is Collaborator",
            "x-keywords": [
                "is user a collaborator",
                "verify repo access",
                "does user have access",
            ],
        },
        title="Check User Is Collaborator",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    username: str = Field(..., title="Username", description="Username")


class GithubListRepositoryInvitationsConfig(BaseModel):
    """List repository invitations"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_repo_invitations"] = Field(
        default="list_repo_invitations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Repo Invitations",
            "x-keywords": [
                "pending repo invites",
                "outstanding collaborator invitations",
                "unaccepted invites",
            ],
        },
        title="List Repo Invitations",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubUpdateRepositoryInvitationConfig(BaseModel):
    """Update a repository invitation"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_repo_invitation"] = Field(
        default="update_repo_invitation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Update Repo Invitation",
            "x-keywords": [
                "change invite permissions",
                "edit pending invite",
                "modify collaborator invitation",
            ],
        },
        title="Update Repo Invitation",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    invitation_id: int = Field(..., title="Invitation Id", description="Invitation Id")
    permissions: Optional[Any] = Field(
        default=None, title="Permissions", description="Permissions parameter"
    )


class GithubCreateTeamConfig(BaseModel):
    """Create a team"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_team"] = Field(
        default="create_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Create Team",
            "x-keywords": ["new team", "make org team", "set up team"],
        },
        title="Create Team",
    )
    org: str = Field(..., title="Org", description="Org")
    name: str = Field(..., title="Name", description="Name")
    description: Optional[Any] = Field(
        default=None, title="Description", description="Description parameter"
    )
    maintainers: Optional[Any] = Field(
        default=None, title="Maintainers", description="Maintainers parameter"
    )
    repo_names: Optional[Any] = Field(
        default=None, title="Repo Names", description="Repo Names parameter"
    )
    privacy: Optional[Any] = Field(
        default=None, title="Privacy", description="Privacy parameter"
    )


class GithubGetTeamConfig(BaseModel):
    """Get a team"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_team"] = Field(
        default="get_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Get Team",
            "x-keywords": ["team details", "fetch team info", "team by slug"],
        },
        title="Get Team",
    )
    org: str = Field(..., title="Org", description="Org")
    team_slug: str = Field(..., title="Team Slug", description="Team Slug")


class GithubUpdateTeamConfig(BaseModel):
    """Update a team"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_team"] = Field(
        default="update_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Update Team",
            "x-keywords": ["edit team", "rename team", "change team settings"],
        },
        title="Update Team",
    )
    org: str = Field(..., title="Org", description="Org")
    team_slug: str = Field(..., title="Team Slug", description="Team Slug")
    name: Optional[Any] = Field(
        default=None, title="Name", description="Name parameter"
    )
    description: Optional[Any] = Field(
        default=None, title="Description", description="Description parameter"
    )
    privacy: Optional[Any] = Field(
        default=None, title="Privacy", description="Privacy parameter"
    )


class GithubDeleteTeamConfig(BaseModel):
    """Delete a team"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_team"] = Field(
        default="delete_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Delete Team",
            "x-keywords": ["remove team", "disband team", "drop team"],
        },
        title="Delete Team",
    )
    org: str = Field(..., title="Org", description="Org")
    team_slug: str = Field(..., title="Team Slug", description="Team Slug")


class GithubListTeamRepositoriesConfig(BaseModel):
    """List team repositories"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_team_repos"] = Field(
        default="list_team_repos",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "List Team Repos",
            "x-keywords": [
                "team repositories",
                "repos for team",
                "what repos a team has",
                "team access repos",
            ],
        },
        title="List Team Repos",
    )
    org: str = Field(..., title="Org", description="Org")
    team_slug: str = Field(..., title="Team Slug", description="Team Slug")


class GithubCheckTeamPermissionsForRepositoryConfig(BaseModel):
    """Check team permissions for a repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["check_team_repo_permissions"] = Field(
        default="check_team_repo_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Check Team Repo Permissions",
            "x-keywords": [
                "team repo access",
                "does team have access",
                "team permission on repo",
                "verify team repo rights",
            ],
        },
        title="Check Team Repo Permissions",
    )
    org: str = Field(..., title="Org", description="Org")
    team_slug: str = Field(..., title="Team Slug", description="Team Slug")
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubAddOrUpdateTeamRepositoryPermissionsConfig(BaseModel):
    """Add or update team repository permissions"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_or_update_team_repo_permissions"] = Field(
        default="add_or_update_team_repo_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Add or Update Team Repo Permissions",
            "x-keywords": [
                "grant team repo access",
                "give team access to repo",
                "set team repo permission",
                "add repo to team",
            ],
        },
        title="Add or Update Team Repo Permissions",
    )
    org: str = Field(..., title="Org", description="Org")
    team_slug: str = Field(..., title="Team Slug", description="Team Slug")
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    permission: Optional[Any] = Field(
        default=None, title="Permission", description="Permission parameter"
    )


class GithubRemoveTeamRepositoryConfig(BaseModel):
    """Remove a repository from a team"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_repo_from_team"] = Field(
        default="remove_repo_from_team",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Remove Repo from Team",
            "x-keywords": [
                "revoke team repo access",
                "unassign repo from team",
                "take repo off team",
                "remove team access",
            ],
        },
        title="Remove Repo from Team",
    )
    org: str = Field(..., title="Org", description="Org")
    team_slug: str = Field(..., title="Team Slug", description="Team Slug")
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubListTeamMembersConfig(BaseModel):
    """List team members"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_team_members"] = Field(
        default="list_team_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "List Team Members",
            "x-keywords": [
                "who is on the team",
                "members of team",
                "team roster",
                "people in team",
            ],
        },
        title="List Team Members",
    )
    org: str = Field(..., title="Org", description="Org")
    team_slug: str = Field(..., title="Team Slug", description="Team Slug")


class GithubGetTeamMembershipConfig(BaseModel):
    """Get team membership for a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_team_membership"] = Field(
        default="get_team_membership",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Team",
            "x-is-trigger": False,
            "x-display-name": "Get Team Membership",
            "x-keywords": [
                "is user on team",
                "team membership status",
                "check team member",
                "user team role",
            ],
        },
        title="Get Team Membership",
    )
    org: str = Field(..., title="Org", description="Org")
    team_slug: str = Field(..., title="Team Slug", description="Team Slug")
    username: str = Field(..., title="Username", description="Username")


class GithubGetOrganizationConfig(BaseModel):
    """Get an organization"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_organization"] = Field(
        default="get_organization",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Get Organization",
            "x-keywords": [
                "org details",
                "company org info",
                "view organization",
                "org profile",
            ],
        },
        title="Get Organization",
    )
    org: str = Field(..., title="Org", description="Org")


class GithubUpdateOrganizationConfig(BaseModel):
    """Update an organization"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_organization"] = Field(
        default="update_organization",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Update Organization",
            "x-keywords": [
                "edit org settings",
                "change organization",
                "modify org profile",
                "org settings",
            ],
        },
        title="Update Organization",
    )
    org: str = Field(..., title="Org", description="Org")
    billing_email: Optional[Any] = Field(
        default=None, title="Billing Email", description="Billing Email parameter"
    )
    company: Optional[Any] = Field(
        default=None, title="Company", description="Company parameter"
    )
    email: Optional[Any] = Field(
        default=None, title="Email", description="Email parameter"
    )
    location: Optional[Any] = Field(
        default=None, title="Location", description="Location parameter"
    )
    name: Optional[Any] = Field(
        default=None, title="Name", description="Name parameter"
    )
    description: Optional[Any] = Field(
        default=None, title="Description", description="Description parameter"
    )


class GithubListOrganizationRepositoriesConfig(BaseModel):
    """List organization repositories (alias)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_org_repos_alias"] = Field(
        default="list_org_repos_alias",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "List Org Repos Alias",
            "x-keywords": [
                "org repositories",
                "all repos in org",
                "repos under organization",
                "company repos",
            ],
        },
        title="List Org Repos Alias",
    )
    org: str = Field(..., title="Org", description="Org")


class GithubCreateOrganizationRepositoryConfig(BaseModel):
    """Create an organization repository"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_org_repository"] = Field(
        default="create_org_repository",
        json_schema_extra={
            "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "github_rest_repo",
            "x-resource-id-path": "data.full_name",
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Create Org Repository",
            "x-keywords": [
                "new repo in org",
                "make org repo",
                "org repository",
                "add repo to organization",
            ],
        },
        title="Create Org Repository",
    )
    org: str = Field(..., title="Org", description="Org")
    name: str = Field(..., title="Name", description="Name")
    description: Optional[Any] = Field(
        default=None, title="Description", description="Description parameter"
    )
    homepage: Optional[Any] = Field(
        default=None, title="Homepage", description="Homepage parameter"
    )
    private: Optional[Any] = Field(
        default=None, title="Private", description="Private parameter"
    )
    has_issues: Optional[Any] = Field(
        default=None, title="Has Issues", description="Has Issues parameter"
    )
    has_projects: Optional[Any] = Field(
        default=None, title="Has Projects", description="Has Projects parameter"
    )
    has_wiki: Optional[Any] = Field(
        default=None, title="Has Wiki", description="Has Wiki parameter"
    )


class GithubListOrganizationInvitationsConfig(BaseModel):
    """List organization invitations"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_org_invitations"] = Field(
        default="list_org_invitations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "List Org Invitations",
            "x-keywords": [
                "pending org invites",
                "who was invited to org",
                "organization invites",
                "outstanding org invitations",
            ],
        },
        title="List Org Invitations",
    )
    org: str = Field(..., title="Org", description="Org")


class GithubCancelOrganizationInvitationConfig(BaseModel):
    """Cancel an organization invitation"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["cancel_org_invitation"] = Field(
        default="cancel_org_invitation",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Cancel Org Invitation",
            "x-keywords": [
                "revoke org invite",
                "rescind organization invitation",
                "withdraw org invite",
                "delete org invitation",
            ],
        },
        title="Cancel Org Invitation",
    )
    org: str = Field(..., title="Org", description="Org")
    invitation_id: int = Field(..., title="Invitation Id", description="Invitation Id")


class GithubListOrganizationMembersConfig(BaseModel):
    """List organization members (alias)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_org_members_alias"] = Field(
        default="list_org_members_alias",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "List Org Members Alias",
            "x-keywords": [
                "org members",
                "who is in the org",
                "people in organization",
                "company members",
            ],
        },
        title="List Org Members Alias",
    )
    org: str = Field(..., title="Org", description="Org")


class GithubCheckOrganizationMembershipConfig(BaseModel):
    """Check organization membership"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["check_org_membership"] = Field(
        default="check_org_membership",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Check Org Membership",
            "x-keywords": [
                "is user in org",
                "org membership check",
                "verify org member",
                "belongs to organization",
            ],
        },
        title="Check Org Membership",
    )
    org: str = Field(..., title="Org", description="Org")
    username: str = Field(..., title="Username", description="Username")


class GithubRemoveOrganizationMemberConfig(BaseModel):
    """Remove an organization member"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_org_member"] = Field(
        default="remove_org_member",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Remove Org Member",
            "x-keywords": [
                "kick from org",
                "remove person from organization",
                "drop org member",
                "boot org user",
            ],
        },
        title="Remove Org Member",
    )
    org: str = Field(..., title="Org", description="Org")
    username: str = Field(..., title="Username", description="Username")


class GithubGetOrganizationMembershipConfig(BaseModel):
    """Get organization membership for a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_org_membership"] = Field(
        default="get_org_membership",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Get Org Membership",
            "x-keywords": [
                "org membership role",
                "user org status",
                "membership in organization",
                "org member details",
            ],
        },
        title="Get Org Membership",
    )
    org: str = Field(..., title="Org", description="Org")
    username: str = Field(..., title="Username", description="Username")


class GithubAddOrUpdateOrganizationMembershipConfig(BaseModel):
    """Add or update organization membership"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_or_update_org_membership"] = Field(
        default="add_or_update_org_membership",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Add or Update Org Membership",
            "x-keywords": [
                "invite to org",
                "set org role",
                "add person to organization",
                "change org membership",
            ],
        },
        title="Add or Update Org Membership",
    )
    org: str = Field(..., title="Org", description="Org")
    username: str = Field(..., title="Username", description="Username")
    role: Optional[Any] = Field(
        default=None, title="Role", description="Role parameter"
    )


class GithubRemoveOrganizationMembershipConfig(BaseModel):
    """Remove organization membership"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_org_membership"] = Field(
        default="remove_org_membership",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Remove Org Membership",
            "x-keywords": [
                "leave organization",
                "delete org membership",
                "end org membership",
                "revoke org membership",
            ],
        },
        title="Remove Org Membership",
    )
    org: str = Field(..., title="Org", description="Org")
    username: str = Field(..., title="Username", description="Username")


class GithubListPendingOrganizationInvitationsConfig(BaseModel):
    """List pending organization invitations (alias)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pending_org_invitations"] = Field(
        default="list_pending_org_invitations",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "List Pending Org Invitations",
            "x-keywords": [
                "unaccepted org invites",
                "pending invitations org",
                "awaiting org members",
                "not yet accepted invites",
            ],
        },
        title="List Pending Org Invitations",
    )
    org: str = Field(..., title="Org", description="Org")


class GithubListOrganizationWebhooksConfig(BaseModel):
    """List organization webhooks"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_org_webhooks"] = Field(
        default="list_org_webhooks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "List Org Webhooks",
            "x-keywords": [
                "org webhooks",
                "organization hooks",
                "webhooks for org",
                "company webhooks",
            ],
        },
        title="List Org Webhooks",
    )
    org: str = Field(..., title="Org", description="Org")


class GithubCreateOrganizationWebhookConfig(BaseModel):
    """Create an organization webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_org_webhook"] = Field(
        default="create_org_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Create Org Webhook",
            "x-keywords": [
                "new org webhook",
                "add organization hook",
                "set up org webhook",
                "register org webhook",
            ],
        },
        title="Create Org Webhook",
    )
    org: str = Field(..., title="Org", description="Org")
    name: str = Field(..., title="Name", description="Name")
    config: Any = Field(..., title="Config", description="Config")
    events: Optional[Any] = Field(
        default=None, title="Events", description="Events parameter"
    )
    active: Optional[Any] = Field(
        default=None, title="Active", description="Active parameter"
    )


class GithubListDeploymentStatusesConfig(BaseModel):
    """List deployment statuses"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_deployment_statuses"] = Field(
        default="list_deployment_statuses",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deployment",
            "x-is-trigger": False,
            "x-display-name": "List Deployment Statuses",
            "x-keywords": [
                "deployment status history",
                "deploy states",
                "statuses for deployment",
                "deployment progress list",
            ],
        },
        title="List Deployment Statuses",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    deployment_id: int = Field(..., title="Deployment Id", description="Deployment Id")


class GithubCreateDeploymentStatusConfig(BaseModel):
    """Create a deployment status"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_deployment_status"] = Field(
        default="create_deployment_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deployment",
            "x-is-trigger": False,
            "x-display-name": "Create Deployment Status",
            "x-keywords": [
                "set deploy status",
                "mark deployment state",
                "post deployment status",
                "report deploy result",
            ],
        },
        title="Create Deployment Status",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    deployment_id: int = Field(..., title="Deployment Id", description="Deployment Id")
    state: str = Field(..., title="State", description="State")
    target_url: Optional[Any] = Field(
        default=None, title="Target Url", description="Target Url parameter"
    )
    log_url: Optional[Any] = Field(
        default=None, title="Log Url", description="Log Url parameter"
    )
    description: Optional[Any] = Field(
        default=None, title="Description", description="Description parameter"
    )
    environment: Optional[Any] = Field(
        default=None, title="Environment", description="Environment parameter"
    )


class GithubGetDeploymentStatusConfig(BaseModel):
    """Get a deployment status"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_deployment_status"] = Field(
        default="get_deployment_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deployment",
            "x-is-trigger": False,
            "x-display-name": "Get Deployment Status",
            "x-keywords": [
                "one deployment status",
                "deploy state details",
                "fetch deployment status",
                "single deploy status",
            ],
        },
        title="Get Deployment Status",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    deployment_id: int = Field(..., title="Deployment Id", description="Deployment Id")
    status_id: int = Field(..., title="Status Id", description="Status Id")


class GithubGetDeploymentConfig(BaseModel):
    """Get a deployment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_deployment"] = Field(
        default="get_deployment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deployment",
            "x-is-trigger": False,
            "x-display-name": "Get Deployment",
            "x-keywords": [
                "deployment details",
                "one deploy",
                "fetch deployment",
                "deploy info",
            ],
        },
        title="Get Deployment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    deployment_id: int = Field(..., title="Deployment Id", description="Deployment Id")


class GithubDeleteDeploymentConfig(BaseModel):
    """Delete a deployment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_deployment"] = Field(
        default="delete_deployment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Deployment",
            "x-is-trigger": False,
            "x-display-name": "Delete Deployment",
            "x-keywords": [
                "remove deployment",
                "drop a deploy",
                "delete deploy record",
                "purge deployment",
            ],
        },
        title="Delete Deployment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    deployment_id: int = Field(..., title="Deployment Id", description="Deployment Id")


class GithubListIssueReactionsConfig(BaseModel):
    """List reactions for an issue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_reactions"] = Field(
        default="list_issue_reactions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Reactions",
            "x-keywords": [
                "reactions on issue",
                "emoji on issue",
                "who reacted to issue",
                "issue thumbs up",
            ],
        },
        title="List Issue Reactions",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="Issue Number")


class GithubDeleteIssueReactionConfig(BaseModel):
    """Delete an issue reaction"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue_reaction"] = Field(
        default="delete_issue_reaction",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Reaction",
            "x-keywords": [
                "remove issue reaction",
                "unreact to issue",
                "take off issue emoji",
                "delete issue thumbs up",
            ],
        },
        title="Delete Issue Reaction",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    issue_number: int = Field(..., title="Issue Number", description="Issue Number")
    reaction_id: int = Field(..., title="Reaction Id", description="Reaction Id")


class GithubListIssueCommentReactionsConfig(BaseModel):
    """List reactions for an issue comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_issue_comment_reactions"] = Field(
        default="list_issue_comment_reactions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "List Issue Comment Reactions",
            "x-keywords": [
                "reactions on issue comment",
                "emoji on issue comment",
                "who reacted to comment",
                "issue comment reactions",
            ],
        },
        title="List Issue Comment Reactions",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")


class GithubCreateIssueCommentReactionConfig(BaseModel):
    """Create a reaction for an issue comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_reaction_on_issue_comment"] = Field(
        default="create_reaction_on_issue_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Create Reaction on Issue Comment",
            "x-keywords": [
                "react to issue comment",
                "add emoji to issue comment",
                "thumbs up issue comment",
                "like issue comment",
            ],
        },
        title="Create Reaction on Issue Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")
    content: str = Field(..., title="Content", description="Content")


class GithubDeleteIssueCommentReactionConfig(BaseModel):
    """Delete an issue comment reaction"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_issue_comment_reaction"] = Field(
        default="delete_issue_comment_reaction",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Issue",
            "x-is-trigger": False,
            "x-display-name": "Delete Issue Comment Reaction",
            "x-keywords": [
                "remove issue comment reaction",
                "unreact issue comment",
                "take off comment emoji",
                "delete reaction on comment",
            ],
        },
        title="Delete Issue Comment Reaction",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")
    reaction_id: int = Field(..., title="Reaction Id", description="Reaction Id")


class GithubListCommitCommentReactionsConfig(BaseModel):
    """List reactions for a commit comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_commit_comment_reactions"] = Field(
        default="list_commit_comment_reactions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "List Commit Comment Reactions",
            "x-keywords": [
                "reactions on commit comment",
                "emoji on commit comment",
                "who reacted commit comment",
                "commit comment reactions",
            ],
        },
        title="List Commit Comment Reactions",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")


class GithubCreateCommitCommentReactionConfig(BaseModel):
    """Create a reaction for a commit comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_reaction_on_commit_comment"] = Field(
        default="create_reaction_on_commit_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "Create Reaction on Commit Comment",
            "x-keywords": [
                "react to commit comment",
                "add emoji commit comment",
                "thumbs up commit comment",
                "like commit comment",
            ],
        },
        title="Create Reaction on Commit Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")
    content: str = Field(..., title="Content", description="Content")


class GithubDeleteCommitCommentReactionConfig(BaseModel):
    """Delete a commit comment reaction"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_commit_comment_reaction"] = Field(
        default="delete_commit_comment_reaction",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Commit",
            "x-is-trigger": False,
            "x-display-name": "Delete Commit Comment Reaction",
            "x-keywords": [
                "remove commit comment reaction",
                "unreact commit comment",
                "delete commit comment emoji",
            ],
        },
        title="Delete Commit Comment Reaction",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")
    reaction_id: int = Field(..., title="Reaction Id", description="Reaction Id")


class GithubListPullRequestReviewCommentReactionsConfig(BaseModel):
    """List reactions for a PR review comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_pr_review_comment_reactions"] = Field(
        default="list_pr_review_comment_reactions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "List Pr Review Comment Reactions",
            "x-keywords": [
                "reactions on review comment",
                "emoji on pr comment",
                "who reacted review comment",
                "pull request comment reactions",
            ],
        },
        title="List Pr Review Comment Reactions",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")


class GithubCreatePullRequestReviewCommentReactionConfig(BaseModel):
    """Create a reaction for a PR review comment"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_reaction_on_pr_review_comment"] = Field(
        default="create_reaction_on_pr_review_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Create Reaction on Pr Review Comment",
            "x-keywords": [
                "react to review comment",
                "add emoji pr comment",
                "thumbs up review comment",
                "like pr review comment",
            ],
        },
        title="Create Reaction on Pr Review Comment",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")
    content: str = Field(..., title="Content", description="Content")


class GithubDeletePullRequestReviewCommentReactionConfig(BaseModel):
    """Delete a PR review comment reaction"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_pr_review_comment_reaction"] = Field(
        default="delete_pr_review_comment_reaction",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Pull Request",
            "x-is-trigger": False,
            "x-display-name": "Delete Pr Review Comment Reaction",
            "x-keywords": [
                "remove review comment reaction",
                "unreact pr comment",
                "delete review comment emoji",
            ],
        },
        title="Delete Pr Review Comment Reaction",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    comment_id: int = Field(..., title="Comment Id", description="Comment Id")
    reaction_id: int = Field(..., title="Reaction Id", description="Reaction Id")


class GithubListReleaseReactionsConfig(BaseModel):
    """List reactions for a release"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_release_reactions"] = Field(
        default="list_release_reactions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "List Release Reactions",
            "x-keywords": [
                "reactions on release",
                "emoji on release",
                "who reacted to release",
                "release reactions",
            ],
        },
        title="List Release Reactions",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    release_id: int = Field(..., title="Release Id", description="Release Id")


class GithubCreateReleaseReactionConfig(BaseModel):
    """Create a reaction for a release"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_reaction_on_release"] = Field(
        default="create_reaction_on_release",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Create Reaction on Release",
            "x-keywords": [
                "react to release",
                "add emoji to release",
                "thumbs up release",
                "like release",
            ],
        },
        title="Create Reaction on Release",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    release_id: int = Field(..., title="Release Id", description="Release Id")
    content: str = Field(..., title="Content", description="Content")


class GithubDeleteReleaseReactionConfig(BaseModel):
    """Delete a release reaction"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_release_reaction"] = Field(
        default="delete_release_reaction",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Release",
            "x-is-trigger": False,
            "x-display-name": "Delete Release Reaction",
            "x-keywords": [
                "remove release reaction",
                "unreact release",
                "delete release emoji",
            ],
        },
        title="Delete Release Reaction",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    release_id: int = Field(..., title="Release Id", description="Release Id")
    reaction_id: int = Field(..., title="Reaction Id", description="Reaction Id")


class GithubListWorkflowRunArtifactsConfig(BaseModel):
    """List workflow run artifacts"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workflow_run_artifacts"] = Field(
        default="list_workflow_run_artifacts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "List Workflow Run Artifacts",
            "x-keywords": [
                "artifacts for a run",
                "build outputs of run",
                "run artifacts",
                "files from workflow run",
            ],
        },
        title="List Workflow Run Artifacts",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")


class GithubListRepositoryArtifactsConfig(BaseModel):
    """List repository artifacts"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_repo_artifacts"] = Field(
        default="list_repo_artifacts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Artifact",
            "x-is-trigger": False,
            "x-display-name": "List Repo Artifacts",
            "x-keywords": [
                "all repo artifacts",
                "build artifacts in repo",
                "repository artifacts",
                "stored ci outputs",
            ],
        },
        title="List Repo Artifacts",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")


class GithubGetArtifactConfig(BaseModel):
    """Get an artifact"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_artifact"] = Field(
        default="get_artifact",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Artifact",
            "x-is-trigger": False,
            "x-display-name": "Get Artifact",
            "x-keywords": [
                "one artifact",
                "artifact details",
                "fetch artifact metadata",
                "single build output",
            ],
        },
        title="Get Artifact",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    artifact_id: int = Field(..., title="Artifact Id", description="Artifact Id")


class GithubDeleteArtifactConfig(BaseModel):
    """Delete an artifact"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_artifact"] = Field(
        default="delete_artifact",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Artifact",
            "x-is-trigger": False,
            "x-display-name": "Delete Artifact",
            "x-keywords": [
                "remove artifact",
                "drop build output",
                "purge artifact",
                "clean up artifact",
            ],
        },
        title="Delete Artifact",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    artifact_id: int = Field(..., title="Artifact Id", description="Artifact Id")


class GithubDownloadArtifactConfig(BaseModel):
    """Download an artifact"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["download_artifact"] = Field(
        default="download_artifact",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Artifact",
            "x-is-trigger": False,
            "x-display-name": "Download Artifact",
            "x-keywords": [
                "get artifact zip",
                "pull build output",
                "fetch artifact file",
                "save artifact",
            ],
        },
        title="Download Artifact",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    artifact_id: int = Field(..., title="Artifact Id", description="Artifact Id")
    archive_format: Any = Field(
        ..., title="Archive Format", description="Archive Format"
    )


class GithubDeleteWorkflowRunConfig(BaseModel):
    """Delete a workflow run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_workflow_run"] = Field(
        default="delete_workflow_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Delete Workflow Run",
            "x-keywords": [
                "remove workflow run",
                "drop a run",
                "delete ci run",
                "purge action run",
            ],
        },
        title="Delete Workflow Run",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")


class GithubGetWorkflowRunUsageConfig(BaseModel):
    """Get workflow run usage"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_workflow_run_usage"] = Field(
        default="get_workflow_run_usage",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Get Workflow Run Usage",
            "x-keywords": [
                "run billing time",
                "workflow minutes used",
                "run compute usage",
                "action run cost",
            ],
        },
        title="Get Workflow Run Usage",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")


class GithubDownloadWorkflowRunLogsConfig(BaseModel):
    """Download workflow run logs"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["download_workflow_run_logs"] = Field(
        default="download_workflow_run_logs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Download Workflow Run Logs",
            "x-keywords": [
                "get run logs",
                "pull workflow logs",
                "fetch ci logs",
                "save action logs",
            ],
        },
        title="Download Workflow Run Logs",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")


class GithubDeleteWorkflowRunLogsConfig(BaseModel):
    """Delete workflow run logs"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_workflow_run_logs"] = Field(
        default="delete_workflow_run_logs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Delete Workflow Run Logs",
            "x-keywords": [
                "remove run logs",
                "clear workflow logs",
                "purge ci logs",
                "drop action logs",
            ],
        },
        title="Delete Workflow Run Logs",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")


class GithubListWorkflowRunJobsConfig(BaseModel):
    """List jobs for a workflow run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workflow_run_jobs"] = Field(
        default="list_workflow_run_jobs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "List Workflow Run Jobs",
            "x-keywords": [
                "jobs in a run",
                "run job list",
                "steps of workflow run",
                "ci jobs for run",
            ],
        },
        title="List Workflow Run Jobs",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")


class GithubGetWorkflowRunAttemptConfig(BaseModel):
    """Get a workflow run attempt"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_workflow_run_attempt"] = Field(
        default="get_workflow_run_attempt",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Get Workflow Run Attempt",
            "x-keywords": [
                "workflow run attempt",
                "ci run attempt",
                "retry attempt",
                "rerun attempt details",
                "github actions attempt",
            ],
        },
        title="Get Workflow Run Attempt",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")
    attempt_number: int = Field(
        ..., title="Attempt Number", description="Attempt Number"
    )


class GithubListJobsForWorkflowRunAttemptConfig(BaseModel):
    """List jobs for a workflow run attempt"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workflow_run_attempt_jobs"] = Field(
        default="list_workflow_run_attempt_jobs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "List Workflow Run Attempt Jobs",
            "x-keywords": [
                "jobs for attempt",
                "attempt jobs",
                "run attempt jobs",
                "ci jobs per attempt",
                "github actions attempt jobs",
            ],
        },
        title="List Workflow Run Attempt Jobs",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")
    attempt_number: int = Field(
        ..., title="Attempt Number", description="Attempt Number"
    )


class GithubDownloadWorkflowRunAttemptLogsConfig(BaseModel):
    """Download logs for a workflow run attempt"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["download_workflow_run_attempt_logs"] = Field(
        default="download_workflow_run_attempt_logs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Download Workflow Run Attempt Logs",
            "x-keywords": [
                "attempt logs",
                "logs for attempt",
                "ci attempt logs",
                "download retry logs",
                "github actions attempt logs",
            ],
        },
        title="Download Workflow Run Attempt Logs",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")
    attempt_number: int = Field(
        ..., title="Attempt Number", description="Attempt Number"
    )


class GithubApproveWorkflowRunConfig(BaseModel):
    """Approve a workflow run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["approve_workflow_run"] = Field(
        default="approve_workflow_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "Approve Workflow Run",
            "x-keywords": [
                "approve ci run",
                "approve actions run",
                "allow workflow",
                "approve pending run",
                "authorize workflow run",
            ],
        },
        title="Approve Workflow Run",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")


class GithubListWorkflowRunPendingDeploymentsConfig(BaseModel):
    """List pending deployments for a workflow run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_workflow_run_pending_deployments"] = Field(
        default="list_workflow_run_pending_deployments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Workflow",
            "x-is-trigger": False,
            "x-display-name": "List Workflow Run Pending Deployments",
            "x-keywords": [
                "pending deployments",
                "awaiting approval deployments",
                "environments awaiting review",
                "deployments needing approval",
                "blocked deployments",
            ],
        },
        title="List Workflow Run Pending Deployments",
    )
    owner: str = Field(..., title="Owner", description="Repository owner")
    repo: str = Field(..., title="Repository", description="Repository name")
    run_id: int = Field(..., title="Run Id", description="Run Id")


# ============================================================================
# Trigger operation config
# ============================================================================


def _github_trigger_field(value: str, display: str, keywords: Optional[list] = None):
    """Build the hidden `operation` discriminator Field for a GitHub trigger."""
    extra = {
        "ui:hidden": True,
        "x-category": None,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(default=value, json_schema_extra=extra, title=display)


class _GithubRepoEventTriggerBase(BaseModel):
    """Shared fields for GitHub per-event repository triggers.

    Each per-event trigger op is a separate operation (On Push, etc.); the
    GitHub event is resolved from the operation via ``_trigger_event_map``.
    """

    model_config = ConfigDict(
        populate_by_name=True, json_schema_extra={"x-requires-webhook": True}
    )

    repository: str = Field(
        ...,
        title="Repository",
        description="The repository to watch (owner/name)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "repository",
                "placeholder": "Select a repository...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste owner/repo",
            },
            "x-resource-type": "github_rest_repo",
        },
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
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    external_webhook_id: Optional[int] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
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


class GithubOnPushConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires on a push to the repository."""

    operation: Literal["on_push"] = _github_trigger_field(
        "on_push",
        "On Push",
        keywords=[
            "when code pushed",
            "on commit pushed",
            "on git push",
            "new push event",
            "code pushed to repo",
        ],
    )


class GithubOnIssueOpenedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is opened."""

    operation: Literal["on_issue_opened"] = _github_trigger_field(
        "on_issue_opened",
        "On Issue Opened",
        keywords=[
            "when issue opened",
            "new issue created",
            "on issue raised",
            "issue filed",
        ],
    )


class GithubOnIssueEditedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is edited."""

    operation: Literal["on_issue_edited"] = _github_trigger_field(
        "on_issue_edited",
        "On Issue Edited",
        keywords=["when issue edited", "issue body changed", "issue title updated"],
    )


class GithubOnIssueDeletedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is deleted."""

    operation: Literal["on_issue_deleted"] = _github_trigger_field(
        "on_issue_deleted",
        "On Issue Deleted",
        keywords=["when issue deleted", "issue removed"],
    )


class GithubOnIssuePinnedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is pinned."""

    operation: Literal["on_issue_pinned"] = _github_trigger_field(
        "on_issue_pinned",
        "On Issue Pinned",
        keywords=["when issue pinned", "issue stuck to top"],
    )


class GithubOnIssueUnpinnedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is unpinned."""

    operation: Literal["on_issue_unpinned"] = _github_trigger_field(
        "on_issue_unpinned",
        "On Issue Unpinned",
        keywords=["when issue unpinned", "issue unstuck"],
    )


class GithubOnIssueClosedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is closed."""

    operation: Literal["on_issue_closed"] = _github_trigger_field(
        "on_issue_closed",
        "On Issue Closed",
        keywords=["when issue closed", "issue resolved", "issue marked done"],
    )


class GithubOnIssueReopenedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is reopened."""

    operation: Literal["on_issue_reopened"] = _github_trigger_field(
        "on_issue_reopened",
        "On Issue Reopened",
        keywords=["when issue reopened", "closed issue reopened"],
    )


class GithubOnIssueAssignedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is assigned."""

    operation: Literal["on_issue_assigned"] = _github_trigger_field(
        "on_issue_assigned",
        "On Issue Assigned",
        keywords=[
            "when issue assigned",
            "issue assigned to someone",
            "issue gets assignee",
        ],
    )


class GithubOnIssueUnassignedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is unassigned."""

    operation: Literal["on_issue_unassigned"] = _github_trigger_field(
        "on_issue_unassigned",
        "On Issue Unassigned",
        keywords=["when issue unassigned", "assignee removed from issue"],
    )


class GithubOnIssueLabeledConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a label is added to a GitHub issue."""

    operation: Literal["on_issue_labeled"] = _github_trigger_field(
        "on_issue_labeled",
        "On Issue Labeled",
        keywords=["when issue labeled", "label added to issue", "tag added to issue"],
    )


class GithubOnIssueUnlabeledConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a label is removed from a GitHub issue."""

    operation: Literal["on_issue_unlabeled"] = _github_trigger_field(
        "on_issue_unlabeled",
        "On Issue Unlabeled",
        keywords=[
            "when issue unlabeled",
            "label removed from issue",
            "tag removed from issue",
        ],
    )


class GithubOnIssueLockedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is locked."""

    operation: Literal["on_issue_locked"] = _github_trigger_field(
        "on_issue_locked",
        "On Issue Locked",
        keywords=["when issue locked", "issue conversation locked"],
    )


class GithubOnIssueUnlockedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is unlocked."""

    operation: Literal["on_issue_unlocked"] = _github_trigger_field(
        "on_issue_unlocked",
        "On Issue Unlocked",
        keywords=["when issue unlocked", "issue conversation unlocked"],
    )


class GithubOnIssueTransferredConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a GitHub issue is transferred to another repository."""

    operation: Literal["on_issue_transferred"] = _github_trigger_field(
        "on_issue_transferred",
        "On Issue Transferred",
        keywords=["when issue transferred", "issue moved to repo", "issue migrated"],
    )


class GithubOnIssueMilestonedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a milestone is added to a GitHub issue."""

    operation: Literal["on_issue_milestoned"] = _github_trigger_field(
        "on_issue_milestoned",
        "On Issue Milestoned",
        keywords=["when issue milestoned", "milestone added to issue"],
    )


class GithubOnIssueDemilestonedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a milestone is removed from a GitHub issue."""

    operation: Literal["on_issue_demilestoned"] = _github_trigger_field(
        "on_issue_demilestoned",
        "On Issue Demilestoned",
        keywords=["when issue demilestoned", "milestone removed from issue"],
    )


class GithubOnIssueCommentConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a comment is made on an issue or pull request."""

    operation: Literal["on_issue_comment"] = _github_trigger_field(
        "on_issue_comment",
        "On Issue Comment",
        keywords=[
            "when issue commented",
            "new comment on issue",
            "comment posted on issue",
            "someone comments",
        ],
    )


class GithubOnPullRequestAssignedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is assigned."""

    operation: Literal["on_pull_request_assigned"] = _github_trigger_field(
        "on_pull_request_assigned",
        "On Pull Request Assigned",
        keywords=["when pr assigned", "pull request assigned", "pr gets assignee"],
    )


class GithubOnPullRequestAutoMergeDisabledConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when auto-merge is disabled on a pull request."""

    operation: Literal["on_pull_request_auto_merge_disabled"] = _github_trigger_field(
        "on_pull_request_auto_merge_disabled",
        "On Pull Request Auto Merge Disabled",
        keywords=["when auto merge disabled", "pr auto merge turned off"],
    )


class GithubOnPullRequestAutoMergeEnabledConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when auto-merge is enabled on a pull request."""

    operation: Literal["on_pull_request_auto_merge_enabled"] = _github_trigger_field(
        "on_pull_request_auto_merge_enabled",
        "On Pull Request Auto Merge Enabled",
        keywords=["when auto merge enabled", "pr auto merge turned on"],
    )


class GithubOnPullRequestClosedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is closed without being merged."""

    operation: Literal["on_pull_request_closed"] = _github_trigger_field(
        "on_pull_request_closed",
        "On Pull Request Closed",
        keywords=[
            "when pr closed",
            "pull request closed unmerged",
            "pr closed without merge",
        ],
    )


class GithubOnPullRequestConvertedToDraftConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is converted to draft."""

    operation: Literal["on_pull_request_converted_to_draft"] = _github_trigger_field(
        "on_pull_request_converted_to_draft",
        "On Pull Request Converted To Draft",
        keywords=["when pr converted to draft", "pull request back to draft"],
    )


class GithubOnPullRequestDemilestonedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a milestone is removed from a pull request."""

    operation: Literal["on_pull_request_demilestoned"] = _github_trigger_field(
        "on_pull_request_demilestoned",
        "On Pull Request Demilestoned",
        keywords=["when pr demilestoned", "milestone removed from pr"],
    )


class GithubOnPullRequestDequeuedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is removed from the merge queue."""

    operation: Literal["on_pull_request_dequeued"] = _github_trigger_field(
        "on_pull_request_dequeued",
        "On Pull Request Dequeued",
        keywords=["when pr dequeued", "pr removed from merge queue"],
    )


class GithubOnPullRequestEditedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request's title or body is edited."""

    operation: Literal["on_pull_request_edited"] = _github_trigger_field(
        "on_pull_request_edited",
        "On Pull Request Edited",
        keywords=[
            "when pr edited",
            "pull request title changed",
            "pr description updated",
        ],
    )


class GithubOnPullRequestEnqueuedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is added to the merge queue."""

    operation: Literal["on_pull_request_enqueued"] = _github_trigger_field(
        "on_pull_request_enqueued",
        "On Pull Request Enqueued",
        keywords=["when pr enqueued", "pr added to merge queue"],
    )


class GithubOnPullRequestLabeledConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a label is added to a pull request."""

    operation: Literal["on_pull_request_labeled"] = _github_trigger_field(
        "on_pull_request_labeled",
        "On Pull Request Labeled",
        keywords=["when pr labeled", "label added to pr", "tag added to pull request"],
    )


class GithubOnPullRequestLockedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is locked."""

    operation: Literal["on_pull_request_locked"] = _github_trigger_field(
        "on_pull_request_locked",
        "On Pull Request Locked",
        keywords=["when pr locked", "pull request conversation locked"],
    )


class GithubOnPullRequestMilestonedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a milestone is added to a pull request."""

    operation: Literal["on_pull_request_milestoned"] = _github_trigger_field(
        "on_pull_request_milestoned",
        "On Pull Request Milestoned",
        keywords=["when pr milestoned", "milestone added to pr"],
    )


class GithubOnPullRequestMergedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is merged (action=closed with merged=true)."""

    operation: Literal["on_pull_request_merged"] = _github_trigger_field(
        "on_pull_request_merged",
        "On Pull Request Merged",
        keywords=["when pr merged", "pull request merged", "pr gets merged"],
    )


class GithubOnPullRequestOpenedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is opened."""

    operation: Literal["on_pull_request_opened"] = _github_trigger_field(
        "on_pull_request_opened",
        "On Pull Request Opened",
        keywords=[
            "when pr opened",
            "new pull request",
            "pr created",
            "pull request raised",
        ],
    )


class GithubOnPullRequestReadyForReviewConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a draft pull request is marked as ready for review."""

    operation: Literal["on_pull_request_ready_for_review"] = _github_trigger_field(
        "on_pull_request_ready_for_review",
        "On Pull Request Ready For Review",
        keywords=[
            "when pr ready for review",
            "draft pr marked ready",
            "pull request ready",
        ],
    )


class GithubOnPullRequestReopenedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a closed pull request is reopened."""

    operation: Literal["on_pull_request_reopened"] = _github_trigger_field(
        "on_pull_request_reopened",
        "On Pull Request Reopened",
        keywords=["when pr reopened", "closed pull request reopened"],
    )


class GithubOnPullRequestReviewRequestRemovedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a review request is removed from a pull request."""

    operation: Literal[
        "on_pull_request_review_request_removed"
    ] = _github_trigger_field(
        "on_pull_request_review_request_removed",
        "On Pull Request Review Request Removed",
        keywords=["when review request removed", "reviewer request removed from pr"],
    )


class GithubOnPullRequestReviewRequestedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a review is requested on a pull request."""

    operation: Literal["on_pull_request_review_requested"] = _github_trigger_field(
        "on_pull_request_review_requested",
        "On Pull Request Review Requested",
        keywords=[
            "when review requested",
            "reviewer requested on pr",
            "asked for review",
        ],
    )


class GithubOnPullRequestSynchronizeConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when new commits are pushed to a pull request's branch."""

    operation: Literal["on_pull_request_synchronize"] = _github_trigger_field(
        "on_pull_request_synchronize",
        "On Pull Request Synchronize",
        keywords=[
            "when pr updated with commits",
            "new commits pushed to pr",
            "pr branch synced",
        ],
    )


class GithubOnPullRequestUnassignedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is unassigned."""

    operation: Literal["on_pull_request_unassigned"] = _github_trigger_field(
        "on_pull_request_unassigned",
        "On Pull Request Unassigned",
        keywords=["when pr unassigned", "assignee removed from pull request"],
    )


class GithubOnPullRequestUnlabeledConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a label is removed from a pull request."""

    operation: Literal["on_pull_request_unlabeled"] = _github_trigger_field(
        "on_pull_request_unlabeled",
        "On Pull Request Unlabeled",
        keywords=["when pr unlabeled", "label removed from pull request"],
    )


class GithubOnPullRequestUnlockedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pull request is unlocked."""

    operation: Literal["on_pull_request_unlocked"] = _github_trigger_field(
        "on_pull_request_unlocked",
        "On Pull Request Unlocked",
        keywords=["when pr unlocked", "pull request conversation unlocked"],
    )


class GithubOnReleasePublishedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a release is published."""

    operation: Literal["on_release_published"] = _github_trigger_field(
        "on_release_published",
        "On Release Published",
        keywords=[
            "when release published",
            "new release published",
            "release goes live",
        ],
    )


class GithubOnReleaseUnpublishedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a release is unpublished."""

    operation: Literal["on_release_unpublished"] = _github_trigger_field(
        "on_release_unpublished",
        "On Release Unpublished",
        keywords=["when release unpublished", "release taken down"],
    )


class GithubOnReleaseCreatedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a draft release is created."""

    operation: Literal["on_release_created"] = _github_trigger_field(
        "on_release_created",
        "On Release Created",
        keywords=["when draft release created", "new draft release"],
    )


class GithubOnReleaseEditedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a release is edited."""

    operation: Literal["on_release_edited"] = _github_trigger_field(
        "on_release_edited",
        "On Release Edited",
        keywords=["when release edited", "release notes changed"],
    )


class GithubOnReleaseDeletedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a release is deleted."""

    operation: Literal["on_release_deleted"] = _github_trigger_field(
        "on_release_deleted",
        "On Release Deleted",
        keywords=["when release deleted", "release removed"],
    )


class GithubOnReleasePrereleasedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a release is marked as a pre-release."""

    operation: Literal["on_release_prereleased"] = _github_trigger_field(
        "on_release_prereleased",
        "On Release Prereleased",
        keywords=["when prerelease", "release marked prerelease", "beta release"],
    )


class GithubOnReleaseReleasedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when a pre-release is promoted to a full release."""

    operation: Literal["on_release_released"] = _github_trigger_field(
        "on_release_released",
        "On Release Released",
        keywords=[
            "when prerelease promoted",
            "prerelease becomes full release",
            "release promoted",
        ],
    )


class GithubOnStarCreatedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when someone stars the repository."""

    operation: Literal["on_star_created"] = _github_trigger_field(
        "on_star_created",
        "On Star Created",
        keywords=[
            "when repo starred",
            "someone stars repo",
            "new star",
            "gained a star",
        ],
    )


class GithubOnStarDeletedConfig(_GithubRepoEventTriggerBase):
    """Trigger: fires when someone unstars the repository."""

    operation: Literal["on_star_deleted"] = _github_trigger_field(
        "on_star_deleted",
        "On Star Deleted",
        keywords=["when repo unstarred", "someone unstars repo", "lost a star"],
    )


# Discriminated union uses 'operation' field to determine which config type to parse
GithubRestConfig = Annotated[
    Union[
        # Trigger operations — Push
        GithubOnPushConfig,
        # Trigger operations — Issues
        GithubOnIssueOpenedConfig,
        GithubOnIssueEditedConfig,
        GithubOnIssueDeletedConfig,
        GithubOnIssuePinnedConfig,
        GithubOnIssueUnpinnedConfig,
        GithubOnIssueClosedConfig,
        GithubOnIssueReopenedConfig,
        GithubOnIssueAssignedConfig,
        GithubOnIssueUnassignedConfig,
        GithubOnIssueLabeledConfig,
        GithubOnIssueUnlabeledConfig,
        GithubOnIssueLockedConfig,
        GithubOnIssueUnlockedConfig,
        GithubOnIssueTransferredConfig,
        GithubOnIssueMilestonedConfig,
        GithubOnIssueDemilestonedConfig,
        # Trigger operations — Issue Comments
        GithubOnIssueCommentConfig,
        # Trigger operations — Pull Requests
        GithubOnPullRequestAssignedConfig,
        GithubOnPullRequestAutoMergeDisabledConfig,
        GithubOnPullRequestAutoMergeEnabledConfig,
        GithubOnPullRequestClosedConfig,
        GithubOnPullRequestConvertedToDraftConfig,
        GithubOnPullRequestDemilestonedConfig,
        GithubOnPullRequestDequeuedConfig,
        GithubOnPullRequestEditedConfig,
        GithubOnPullRequestEnqueuedConfig,
        GithubOnPullRequestLabeledConfig,
        GithubOnPullRequestLockedConfig,
        GithubOnPullRequestMilestonedConfig,
        GithubOnPullRequestMergedConfig,
        GithubOnPullRequestOpenedConfig,
        GithubOnPullRequestReadyForReviewConfig,
        GithubOnPullRequestReopenedConfig,
        GithubOnPullRequestReviewRequestRemovedConfig,
        GithubOnPullRequestReviewRequestedConfig,
        GithubOnPullRequestSynchronizeConfig,
        GithubOnPullRequestUnassignedConfig,
        GithubOnPullRequestUnlabeledConfig,
        GithubOnPullRequestUnlockedConfig,
        # Trigger operations — Releases
        GithubOnReleasePublishedConfig,
        GithubOnReleaseUnpublishedConfig,
        GithubOnReleaseCreatedConfig,
        GithubOnReleaseEditedConfig,
        GithubOnReleaseDeletedConfig,
        GithubOnReleasePrereleasedConfig,
        GithubOnReleaseReleasedConfig,
        # Trigger operations — Stars
        GithubOnStarCreatedConfig,
        GithubOnStarDeletedConfig,
        # Repository operations
        GithubGetRepositoryConfig,
        GithubListRepositoriesConfig,
        GithubListOrganizationReposConfig,
        GithubForkRepositoryConfig,
        GithubListCollaboratorsConfig,
        GithubCreateRepoWebhookConfig,
        GithubListForksConfig,
        GithubListContributorsConfig,
        GithubGetRepoLanguagesConfig,
        GithubGetRepoTopicsConfig,
        GithubSetRepoTopicsConfig,
        GithubListStargazersConfig,
        GithubStarRepositoryConfig,
        GithubUnstarRepositoryConfig,
        GithubListRepoContentsConfig,
        GithubCreateRepoFromTemplateConfig,
        GithubListUserReposConfig,
        # Issue operations
        GithubListIssuesConfig,
        GithubGetIssueConfig,
        GithubCreateIssueConfig,
        GithubUpdateIssueConfig,
        GithubListIssueCommentsConfig,
        GithubCreateIssueCommentConfig,
        GithubAddLabelsToIssueConfig,
        GithubCreateIssueReactionConfig,
        GithubListMilestonesConfig,
        GithubCreateMilestoneConfig,
        GithubListAssigneesConfig,
        # Pull request operations
        GithubListPullRequestsConfig,
        GithubGetPullRequestConfig,
        GithubCreatePullRequestConfig,
        GithubUpdatePullRequestConfig,
        GithubMergePullRequestConfig,
        GithubListPullRequestFilesConfig,
        GithubRequestReviewersConfig,
        GithubListPullRequestReviewsConfig,
        GithubCreatePullRequestReviewConfig,
        # Commit operations
        GithubListCommitsConfig,
        GithubGetCommitConfig,
        GithubCompareCommitsConfig,
        GithubListCheckRunsConfig,
        # Branch operations
        GithubListBranchesConfig,
        GithubCreateBranchConfig,
        GithubDeleteBranchConfig,
        GithubListTagsConfig,
        # File operations
        GithubGetFileContentsConfig,
        GithubCreateOrUpdateFileConfig,
        GithubDeleteFileConfig,
        # Release operations
        GithubListReleasesConfig,
        GithubGetReleaseConfig,
        GithubCreateReleaseConfig,
        # Label operations
        GithubListLabelsConfig,
        GithubCreateLabelConfig,
        # User operations
        GithubGetAuthenticatedUserConfig,
        GithubGetUserConfig,
        GithubListUserFollowersConfig,
        GithubListUserFollowingConfig,
        # Workflow operations
        GithubListWorkflowRunsConfig,
        GithubListWorkflowsConfig,
        GithubGetWorkflowRunConfig,
        GithubTriggerWorkflowDispatchConfig,
        GithubCancelWorkflowRunConfig,
        GithubRerunWorkflowConfig,
        # Deployment operations
        GithubListDeploymentsConfig,
        GithubCreateDeploymentConfig,
        # Notification operations
        GithubListNotificationsConfig,
        GithubMarkNotificationsReadConfig,
        # Organization operations
        GithubListOrgTeamsConfig,
        GithubListOrgMembersConfig,
        # Gist operations
        GithubListGistsConfig,
        GithubGetGistConfig,
        GithubCreateGistConfig,
        # Search operations
        GithubSearchIssuesConfig,
        GithubSearchCodeConfig,
        GithubSearchRepositoriesConfig,
        # Newly added configs
        GithubListPullRequestReviewCommentsConfig,
        GithubCreatePullRequestReviewCommentConfig,
        GithubGetPullRequestReviewCommentConfig,
        GithubUpdatePullRequestReviewCommentConfig,
        GithubDeletePullRequestReviewCommentConfig,
        GithubReplyToPullRequestReviewCommentConfig,
        GithubUpdatePullRequestReviewConfig,
        GithubDeletePendingPullRequestReviewConfig,
        GithubGetPullRequestReviewCommentsConfig,
        GithubSubmitPullRequestReviewConfig,
        GithubDismissPullRequestReviewConfig,
        GithubListPullRequestCommitsConfig,
        GithubCheckIfPullRequestMergedConfig,
        GithubUpdatePullRequestBranchConfig,
        GithubUpdateRepositoryConfig,
        GithubDeleteRepositoryConfig,
        GithubCreateRepositoryForAuthenticatedUserConfig,
        GithubTransferRepositoryConfig,
        GithubLockIssueConfig,
        GithubUnlockIssueConfig,
        GithubGetIssueCommentConfig,
        GithubUpdateIssueCommentConfig,
        GithubDeleteIssueCommentConfig,
        GithubGetLabelConfig,
        GithubUpdateLabelConfig,
        GithubDeleteLabelConfig,
        GithubSetIssueLabelsConfig,
        GithubRemoveAllIssueLabelsConfig,
        GithubRemoveIssueLabelConfig,
        GithubGetMilestoneConfig,
        GithubUpdateMilestoneConfig,
        GithubDeleteMilestoneConfig,
        GithubUpdateReleaseConfig,
        GithubDeleteReleaseConfig,
        GithubGetLatestReleaseConfig,
        GithubGetReleaseByTagConfig,
        GithubGenerateReleaseNotesConfig,
        GithubListReleaseAssetsConfig,
        GithubGetReleaseAssetConfig,
        GithubUpdateReleaseAssetConfig,
        GithubDeleteReleaseAssetConfig,
        GithubUpdateGistConfig,
        GithubDeleteGistConfig,
        GithubListPublicGistsConfig,
        GithubListStarredGistsConfig,
        GithubStarGistConfig,
        GithubUnstarGistConfig,
        GithubCheckIfGistIsStarredConfig,
        GithubForkGistConfig,
        GithubListGistForksConfig,
        GithubListGistCommitsConfig,
        GithubGetGistRevisionConfig,
        GithubListUserGistsConfig,
        GithubListBranchesForHeadCommitConfig,
        GithubListPullRequestsForCommitConfig,
        GithubListCommitCommentsConfig,
        GithubCreateCommitCommentConfig,
        GithubCreateCommitStatusConfig,
        GithubGetRepositoryWebhookConfig,
        GithubUpdateRepositoryWebhookConfig,
        GithubDeleteRepositoryWebhookConfig,
        GithubPingRepositoryWebhookConfig,
        GithubTestRepositoryWebhookConfig,
        GithubListWebhookDeliveriesConfig,
        GithubGetWebhookDeliveryConfig,
        GithubRedeliverWebhookConfig,
        GithubAddRepositoryCollaboratorConfig,
        GithubRemoveRepositoryCollaboratorConfig,
        GithubGetRepositoryPermissionsConfig,
        GithubCheckIfUserIsCollaboratorConfig,
        GithubListRepositoryInvitationsConfig,
        GithubUpdateRepositoryInvitationConfig,
        GithubCreateTeamConfig,
        GithubGetTeamConfig,
        GithubUpdateTeamConfig,
        GithubDeleteTeamConfig,
        GithubListTeamRepositoriesConfig,
        GithubCheckTeamPermissionsForRepositoryConfig,
        GithubAddOrUpdateTeamRepositoryPermissionsConfig,
        GithubRemoveTeamRepositoryConfig,
        GithubListTeamMembersConfig,
        GithubGetTeamMembershipConfig,
        GithubGetOrganizationConfig,
        GithubUpdateOrganizationConfig,
        GithubListOrganizationRepositoriesConfig,
        GithubCreateOrganizationRepositoryConfig,
        GithubListOrganizationInvitationsConfig,
        GithubCancelOrganizationInvitationConfig,
        GithubListOrganizationMembersConfig,
        GithubCheckOrganizationMembershipConfig,
        GithubRemoveOrganizationMemberConfig,
        GithubGetOrganizationMembershipConfig,
        GithubAddOrUpdateOrganizationMembershipConfig,
        GithubRemoveOrganizationMembershipConfig,
        GithubListPendingOrganizationInvitationsConfig,
        GithubListOrganizationWebhooksConfig,
        GithubCreateOrganizationWebhookConfig,
        GithubListDeploymentStatusesConfig,
        GithubCreateDeploymentStatusConfig,
        GithubGetDeploymentStatusConfig,
        GithubGetDeploymentConfig,
        GithubDeleteDeploymentConfig,
        GithubListIssueReactionsConfig,
        GithubDeleteIssueReactionConfig,
        GithubListIssueCommentReactionsConfig,
        GithubCreateIssueCommentReactionConfig,
        GithubDeleteIssueCommentReactionConfig,
        GithubListCommitCommentReactionsConfig,
        GithubCreateCommitCommentReactionConfig,
        GithubDeleteCommitCommentReactionConfig,
        GithubListPullRequestReviewCommentReactionsConfig,
        GithubCreatePullRequestReviewCommentReactionConfig,
        GithubDeletePullRequestReviewCommentReactionConfig,
        GithubListReleaseReactionsConfig,
        GithubCreateReleaseReactionConfig,
        GithubDeleteReleaseReactionConfig,
        GithubListWorkflowRunArtifactsConfig,
        GithubListRepositoryArtifactsConfig,
        GithubGetArtifactConfig,
        GithubDeleteArtifactConfig,
        GithubDownloadArtifactConfig,
        GithubDeleteWorkflowRunConfig,
        GithubGetWorkflowRunUsageConfig,
        GithubDownloadWorkflowRunLogsConfig,
        GithubDeleteWorkflowRunLogsConfig,
        GithubListWorkflowRunJobsConfig,
        GithubGetWorkflowRunAttemptConfig,
        GithubListJobsForWorkflowRunAttemptConfig,
        GithubDownloadWorkflowRunAttemptLogsConfig,
        GithubApproveWorkflowRunConfig,
        GithubListWorkflowRunPendingDeploymentsConfig,
    ],
    Discriminator("operation"),
]


class GithubRestNodeConfig(NodeConfig[GithubRestConfig, GithubRestCredential]):
    """Full configuration for GitHub REST node including credentials"""

    pass


# ============================================================================
# GitHub REST Node Implementation
# ============================================================================


class GithubRestNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """
    GitHub REST API automation node.

    Executes GitHub operations via direct REST API calls for optimal performance.
    Supports multiple actions - user selects one in the config.
    """

    edit_examples = [
        'Create a pull request from "fix/auth" to "main" branch',
        'List all open issues with label "bug" in the noclick repo',
        "Merge a pull request and delete the source branch automatically",
        'Get all commits in the "develop" branch since last week',
        "Create a release v1.2.0 with release notes and binary assets",
        "Fork the repository and add a webhook for push events",
        'Search for issues mentioning "performance" in the org',
    ]

    scope_registry = GITHUB_SCOPES
    connection_evidence = ConnectionEvidence(
        field="repository",
        noun="repositories",
    )

    @classmethod
    def get_config_model(cls):
        return GithubRestNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute GitHub action via REST API."""
        logger.info(f"[GithubRestNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, GithubRestNodeConfig):
            raise ValueError("GithubRestNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                "[GithubRestNode] Credentials are required. "
                "Please add your Personal Access Token in the node's credentials tab."
            )

        # All trigger ops share the same handler — dispatch without listing all classes.
        if config.operation in self._trigger_event_map:
            return await self._trigger_on_repository_event(config, credentials)

        # Route to appropriate handler based on config type
        action_handlers = {
            # Repository operations
            GithubGetRepositoryConfig: self._get_repository,
            GithubListRepositoriesConfig: self._list_repositories,
            GithubListOrganizationReposConfig: self._list_organization_repos,
            GithubForkRepositoryConfig: self._fork_repository,
            GithubListCollaboratorsConfig: self._list_collaborators,
            GithubCreateRepoWebhookConfig: self._create_repo_webhook,
            GithubListForksConfig: self._list_forks,
            GithubListContributorsConfig: self._list_contributors,
            GithubGetRepoLanguagesConfig: self._get_repo_languages,
            GithubGetRepoTopicsConfig: self._get_repo_topics,
            GithubSetRepoTopicsConfig: self._set_repo_topics,
            GithubListStargazersConfig: self._list_stargazers,
            GithubStarRepositoryConfig: self._star_repository,
            GithubUnstarRepositoryConfig: self._unstar_repository,
            GithubListRepoContentsConfig: self._list_repo_contents,
            GithubCreateRepoFromTemplateConfig: self._create_repo_from_template,
            GithubListUserReposConfig: self._list_user_repos,
            # Issue operations
            GithubListIssuesConfig: self._list_issues,
            GithubGetIssueConfig: self._get_issue,
            GithubCreateIssueConfig: self._create_issue,
            GithubUpdateIssueConfig: self._update_issue,
            GithubListIssueCommentsConfig: self._list_issue_comments,
            GithubCreateIssueCommentConfig: self._create_issue_comment,
            GithubAddLabelsToIssueConfig: self._add_labels_to_issue,
            GithubCreateIssueReactionConfig: self._create_issue_reaction,
            GithubListMilestonesConfig: self._list_milestones,
            GithubCreateMilestoneConfig: self._create_milestone,
            GithubListAssigneesConfig: self._list_assignees,
            # Pull request operations
            GithubListPullRequestsConfig: self._list_pull_requests,
            GithubGetPullRequestConfig: self._get_pull_request,
            GithubCreatePullRequestConfig: self._create_pull_request,
            GithubUpdatePullRequestConfig: self._update_pull_request,
            GithubMergePullRequestConfig: self._merge_pull_request,
            GithubListPullRequestFilesConfig: self._list_pull_request_files,
            GithubRequestReviewersConfig: self._request_reviewers,
            GithubListPullRequestReviewsConfig: self._list_pull_request_reviews,
            GithubCreatePullRequestReviewConfig: self._create_pull_request_review,
            # Commit operations
            GithubListCommitsConfig: self._list_commits,
            GithubGetCommitConfig: self._get_commit,
            GithubCompareCommitsConfig: self._compare_commits,
            GithubListCheckRunsConfig: self._list_check_runs,
            # Branch operations
            GithubListBranchesConfig: self._list_branches,
            GithubCreateBranchConfig: self._create_branch,
            GithubDeleteBranchConfig: self._delete_branch,
            GithubListTagsConfig: self._list_tags,
            # File operations
            GithubGetFileContentsConfig: self._get_file_contents,
            GithubCreateOrUpdateFileConfig: self._create_or_update_file,
            GithubDeleteFileConfig: self._delete_file,
            # Release operations
            GithubListReleasesConfig: self._list_releases,
            GithubGetReleaseConfig: self._get_release,
            GithubCreateReleaseConfig: self._create_release,
            # Label operations
            GithubListLabelsConfig: self._list_labels,
            GithubCreateLabelConfig: self._create_label,
            # User operations
            GithubGetAuthenticatedUserConfig: self._get_authenticated_user,
            GithubGetUserConfig: self._get_user,
            GithubListUserFollowersConfig: self._list_user_followers,
            GithubListUserFollowingConfig: self._list_user_following,
            # Workflow operations
            GithubListWorkflowRunsConfig: self._list_workflow_runs,
            GithubListWorkflowsConfig: self._list_workflows,
            GithubGetWorkflowRunConfig: self._get_workflow_run,
            GithubTriggerWorkflowDispatchConfig: self._trigger_workflow_dispatch,
            GithubCancelWorkflowRunConfig: self._cancel_workflow_run,
            GithubRerunWorkflowConfig: self._rerun_workflow,
            # Deployment operations
            GithubListDeploymentsConfig: self._list_deployments,
            GithubCreateDeploymentConfig: self._create_deployment,
            # Notification operations
            GithubListNotificationsConfig: self._list_notifications,
            GithubMarkNotificationsReadConfig: self._mark_notifications_read,
            # Organization operations
            GithubListOrgTeamsConfig: self._list_org_teams,
            GithubListOrgMembersConfig: self._list_org_members,
            # Gist operations
            GithubListGistsConfig: self._list_gists,
            GithubGetGistConfig: self._get_gist,
            GithubCreateGistConfig: self._create_gist,
            # Search operations
            GithubSearchIssuesConfig: self._search_issues,
            GithubSearchCodeConfig: self._search_code,
            GithubSearchRepositoriesConfig: self._search_repositories,
            # Newly added action handlers
            GithubListPullRequestReviewCommentsConfig: self._list_pull_request_review_comments,
            GithubCreatePullRequestReviewCommentConfig: self._create_pull_request_review_comment,
            GithubGetPullRequestReviewCommentConfig: self._get_pull_request_review_comment,
            GithubUpdatePullRequestReviewCommentConfig: self._update_pull_request_review_comment,
            GithubDeletePullRequestReviewCommentConfig: self._delete_pull_request_review_comment,
            GithubReplyToPullRequestReviewCommentConfig: self._reply_to_pull_request_review_comment,
            GithubUpdatePullRequestReviewConfig: self._update_pull_request_review,
            GithubDeletePendingPullRequestReviewConfig: self._delete_pending_pull_request_review,
            GithubGetPullRequestReviewCommentsConfig: self._get_pull_request_review_comments,
            GithubSubmitPullRequestReviewConfig: self._submit_pull_request_review,
            GithubDismissPullRequestReviewConfig: self._dismiss_pull_request_review,
            GithubListPullRequestCommitsConfig: self._list_pull_request_commits,
            GithubCheckIfPullRequestMergedConfig: self._check_if_pull_request_merged,
            GithubUpdatePullRequestBranchConfig: self._update_pull_request_branch,
            GithubUpdateRepositoryConfig: self._update_repository,
            GithubDeleteRepositoryConfig: self._delete_repository,
            GithubCreateRepositoryForAuthenticatedUserConfig: self._create_repository_for_authenticated_user,
            GithubTransferRepositoryConfig: self._transfer_repository,
            GithubLockIssueConfig: self._lock_issue,
            GithubUnlockIssueConfig: self._unlock_issue,
            GithubGetIssueCommentConfig: self._get_issue_comment,
            GithubUpdateIssueCommentConfig: self._update_issue_comment,
            GithubDeleteIssueCommentConfig: self._delete_issue_comment,
            GithubGetLabelConfig: self._get_label,
            GithubUpdateLabelConfig: self._update_label,
            GithubDeleteLabelConfig: self._delete_label,
            GithubSetIssueLabelsConfig: self._set_issue_labels,
            GithubRemoveAllIssueLabelsConfig: self._remove_all_issue_labels,
            GithubRemoveIssueLabelConfig: self._remove_issue_label,
            GithubGetMilestoneConfig: self._get_milestone,
            GithubUpdateMilestoneConfig: self._update_milestone,
            GithubDeleteMilestoneConfig: self._delete_milestone,
            GithubUpdateReleaseConfig: self._update_release,
            GithubDeleteReleaseConfig: self._delete_release,
            GithubGetLatestReleaseConfig: self._get_latest_release,
            GithubGetReleaseByTagConfig: self._get_release_by_tag,
            GithubGenerateReleaseNotesConfig: self._generate_release_notes,
            GithubListReleaseAssetsConfig: self._list_release_assets,
            GithubGetReleaseAssetConfig: self._get_release_asset,
            GithubUpdateReleaseAssetConfig: self._update_release_asset,
            GithubDeleteReleaseAssetConfig: self._delete_release_asset,
            GithubUpdateGistConfig: self._update_gist,
            GithubDeleteGistConfig: self._delete_gist,
            GithubListPublicGistsConfig: self._list_public_gists,
            GithubListStarredGistsConfig: self._list_starred_gists,
            GithubStarGistConfig: self._star_gist,
            GithubUnstarGistConfig: self._unstar_gist,
            GithubCheckIfGistIsStarredConfig: self._check_if_gist_is_starred,
            GithubForkGistConfig: self._fork_gist,
            GithubListGistForksConfig: self._list_gist_forks,
            GithubListGistCommitsConfig: self._list_gist_commits,
            GithubGetGistRevisionConfig: self._get_gist_revision,
            GithubListUserGistsConfig: self._list_user_gists,
            GithubListBranchesForHeadCommitConfig: self._list_branches_for_head_commit,
            GithubListPullRequestsForCommitConfig: self._list_pull_requests_for_commit,
            GithubListCommitCommentsConfig: self._list_commit_comments,
            GithubCreateCommitCommentConfig: self._create_commit_comment,
            GithubCreateCommitStatusConfig: self._create_commit_status,
            GithubGetRepositoryWebhookConfig: self._get_repository_webhook,
            GithubUpdateRepositoryWebhookConfig: self._update_repository_webhook,
            GithubDeleteRepositoryWebhookConfig: self._delete_repository_webhook,
            GithubPingRepositoryWebhookConfig: self._ping_repository_webhook,
            GithubTestRepositoryWebhookConfig: self._test_repository_webhook,
            GithubListWebhookDeliveriesConfig: self._list_webhook_deliveries,
            GithubGetWebhookDeliveryConfig: self._get_webhook_delivery,
            GithubRedeliverWebhookConfig: self._redeliver_webhook,
            GithubAddRepositoryCollaboratorConfig: self._add_repository_collaborator,
            GithubRemoveRepositoryCollaboratorConfig: self._remove_repository_collaborator,
            GithubGetRepositoryPermissionsConfig: self._get_repository_permissions,
            GithubCheckIfUserIsCollaboratorConfig: self._check_if_user_is_collaborator,
            GithubListRepositoryInvitationsConfig: self._list_repository_invitations,
            GithubUpdateRepositoryInvitationConfig: self._update_repository_invitation,
            GithubCreateTeamConfig: self._create_team,
            GithubGetTeamConfig: self._get_team,
            GithubUpdateTeamConfig: self._update_team,
            GithubDeleteTeamConfig: self._delete_team,
            GithubListTeamRepositoriesConfig: self._list_team_repositories,
            GithubCheckTeamPermissionsForRepositoryConfig: self._check_team_permissions_for_repository,
            GithubAddOrUpdateTeamRepositoryPermissionsConfig: self._add_or_update_team_repository_permissions,
            GithubRemoveTeamRepositoryConfig: self._remove_team_repository,
            GithubListTeamMembersConfig: self._list_team_members,
            GithubGetTeamMembershipConfig: self._get_team_membership,
            GithubGetOrganizationConfig: self._get_organization,
            GithubUpdateOrganizationConfig: self._update_organization,
            GithubListOrganizationRepositoriesConfig: self._list_organization_repositories,
            GithubCreateOrganizationRepositoryConfig: self._create_organization_repository,
            GithubListOrganizationInvitationsConfig: self._list_organization_invitations,
            GithubCancelOrganizationInvitationConfig: self._cancel_organization_invitation,
            GithubListOrganizationMembersConfig: self._list_organization_members,
            GithubCheckOrganizationMembershipConfig: self._check_organization_membership,
            GithubRemoveOrganizationMemberConfig: self._remove_organization_member,
            GithubGetOrganizationMembershipConfig: self._get_organization_membership,
            GithubAddOrUpdateOrganizationMembershipConfig: self._add_or_update_organization_membership,
            GithubRemoveOrganizationMembershipConfig: self._remove_organization_membership,
            GithubListPendingOrganizationInvitationsConfig: self._list_pending_organization_invitations,
            GithubListOrganizationWebhooksConfig: self._list_organization_webhooks,
            GithubCreateOrganizationWebhookConfig: self._create_organization_webhook,
            GithubListDeploymentStatusesConfig: self._list_deployment_statuses,
            GithubCreateDeploymentStatusConfig: self._create_deployment_status,
            GithubGetDeploymentStatusConfig: self._get_deployment_status,
            GithubGetDeploymentConfig: self._get_deployment,
            GithubDeleteDeploymentConfig: self._delete_deployment,
            GithubListIssueReactionsConfig: self._list_issue_reactions,
            GithubDeleteIssueReactionConfig: self._delete_issue_reaction,
            GithubListIssueCommentReactionsConfig: self._list_issue_comment_reactions,
            GithubCreateIssueCommentReactionConfig: self._create_issue_comment_reaction,
            GithubDeleteIssueCommentReactionConfig: self._delete_issue_comment_reaction,
            GithubListCommitCommentReactionsConfig: self._list_commit_comment_reactions,
            GithubCreateCommitCommentReactionConfig: self._create_commit_comment_reaction,
            GithubDeleteCommitCommentReactionConfig: self._delete_commit_comment_reaction,
            GithubListPullRequestReviewCommentReactionsConfig: self._list_pull_request_review_comment_reactions,
            GithubCreatePullRequestReviewCommentReactionConfig: self._create_pull_request_review_comment_reaction,
            GithubDeletePullRequestReviewCommentReactionConfig: self._delete_pull_request_review_comment_reaction,
            GithubListReleaseReactionsConfig: self._list_release_reactions,
            GithubCreateReleaseReactionConfig: self._create_release_reaction,
            GithubDeleteReleaseReactionConfig: self._delete_release_reaction,
            GithubListWorkflowRunArtifactsConfig: self._list_workflow_run_artifacts,
            GithubListRepositoryArtifactsConfig: self._list_repository_artifacts,
            GithubGetArtifactConfig: self._get_artifact,
            GithubDeleteArtifactConfig: self._delete_artifact,
            GithubDownloadArtifactConfig: self._download_artifact,
            GithubDeleteWorkflowRunConfig: self._delete_workflow_run,
            GithubGetWorkflowRunUsageConfig: self._get_workflow_run_usage,
            GithubDownloadWorkflowRunLogsConfig: self._download_workflow_run_logs,
            GithubDeleteWorkflowRunLogsConfig: self._delete_workflow_run_logs,
            GithubListWorkflowRunJobsConfig: self._list_workflow_run_jobs,
            GithubGetWorkflowRunAttemptConfig: self._get_workflow_run_attempt,
            GithubListJobsForWorkflowRunAttemptConfig: self._list_jobs_for_workflow_run_attempt,
            GithubDownloadWorkflowRunAttemptLogsConfig: self._download_workflow_run_attempt_logs,
            GithubApproveWorkflowRunConfig: self._approve_workflow_run,
            GithubListWorkflowRunPendingDeploymentsConfig: self._list_workflow_run_pending_deployments,
        }

        handler = action_handlers.get(type(config))
        if not handler:
            raise ValueError(f"Unknown config type: {type(config)}")

        return await handler(config, credentials)

    # ========================================================================
    # Webhook Trigger (on_repository_event)
    # ========================================================================

    # operation literal -> the GitHub webhook event(s) it subscribes to
    _trigger_event_map: ClassVar[Dict[str, List[str]]] = {
        # Push
        "on_push": ["push"],
        # Issues
        "on_issue_opened": ["issues"],
        "on_issue_edited": ["issues"],
        "on_issue_deleted": ["issues"],
        "on_issue_pinned": ["issues"],
        "on_issue_unpinned": ["issues"],
        "on_issue_closed": ["issues"],
        "on_issue_reopened": ["issues"],
        "on_issue_assigned": ["issues"],
        "on_issue_unassigned": ["issues"],
        "on_issue_labeled": ["issues"],
        "on_issue_unlabeled": ["issues"],
        "on_issue_locked": ["issues"],
        "on_issue_unlocked": ["issues"],
        "on_issue_transferred": ["issues"],
        "on_issue_milestoned": ["issues"],
        "on_issue_demilestoned": ["issues"],
        # Issue comments
        "on_issue_comment": ["issue_comment"],
        # Pull requests
        "on_pull_request_assigned": ["pull_request"],
        "on_pull_request_auto_merge_disabled": ["pull_request"],
        "on_pull_request_auto_merge_enabled": ["pull_request"],
        "on_pull_request_closed": ["pull_request"],
        "on_pull_request_converted_to_draft": ["pull_request"],
        "on_pull_request_demilestoned": ["pull_request"],
        "on_pull_request_dequeued": ["pull_request"],
        "on_pull_request_edited": ["pull_request"],
        "on_pull_request_enqueued": ["pull_request"],
        "on_pull_request_labeled": ["pull_request"],
        "on_pull_request_locked": ["pull_request"],
        "on_pull_request_milestoned": ["pull_request"],
        "on_pull_request_merged": ["pull_request"],
        "on_pull_request_opened": ["pull_request"],
        "on_pull_request_ready_for_review": ["pull_request"],
        "on_pull_request_reopened": ["pull_request"],
        "on_pull_request_review_request_removed": ["pull_request"],
        "on_pull_request_review_requested": ["pull_request"],
        "on_pull_request_synchronize": ["pull_request"],
        "on_pull_request_unassigned": ["pull_request"],
        "on_pull_request_unlabeled": ["pull_request"],
        "on_pull_request_unlocked": ["pull_request"],
        # Releases
        "on_release_published": ["release"],
        "on_release_unpublished": ["release"],
        "on_release_created": ["release"],
        "on_release_edited": ["release"],
        "on_release_deleted": ["release"],
        "on_release_prereleased": ["release"],
        "on_release_released": ["release"],
        # Stars
        "on_star_created": ["star"],
        "on_star_deleted": ["star"],
    }

    # Maps operation → expected payload action string.
    # on_push: no action field in push payloads — filter passes always.
    # on_issue_comment: no filtering — fires on all comment actions (created/edited/deleted).
    # on_pull_request_merged: special case — action="closed" with pull_request.merged=True.
    _TRIGGER_ACTION_MAP: ClassVar[Dict[str, Optional[str]]] = {
        # Issues
        "on_issue_opened": "opened",
        "on_issue_edited": "edited",
        "on_issue_deleted": "deleted",
        "on_issue_pinned": "pinned",
        "on_issue_unpinned": "unpinned",
        "on_issue_closed": "closed",
        "on_issue_reopened": "reopened",
        "on_issue_assigned": "assigned",
        "on_issue_unassigned": "unassigned",
        "on_issue_labeled": "labeled",
        "on_issue_unlabeled": "unlabeled",
        "on_issue_locked": "locked",
        "on_issue_unlocked": "unlocked",
        "on_issue_transferred": "transferred",
        "on_issue_milestoned": "milestoned",
        "on_issue_demilestoned": "demilestoned",
        # Pull requests (all except merged use the action string directly)
        "on_pull_request_assigned": "assigned",
        "on_pull_request_auto_merge_disabled": "auto_merge_disabled",
        "on_pull_request_auto_merge_enabled": "auto_merge_enabled",
        "on_pull_request_closed": "closed",
        "on_pull_request_converted_to_draft": "converted_to_draft",
        "on_pull_request_demilestoned": "demilestoned",
        "on_pull_request_dequeued": "dequeued",
        "on_pull_request_edited": "edited",
        "on_pull_request_enqueued": "enqueued",
        "on_pull_request_labeled": "labeled",
        "on_pull_request_locked": "locked",
        "on_pull_request_milestoned": "milestoned",
        # on_pull_request_merged handled specially in filter_trigger_payload
        "on_pull_request_opened": "opened",
        "on_pull_request_ready_for_review": "ready_for_review",
        "on_pull_request_reopened": "reopened",
        "on_pull_request_review_request_removed": "review_request_removed",
        "on_pull_request_review_requested": "review_requested",
        "on_pull_request_synchronize": "synchronize",
        "on_pull_request_unassigned": "unassigned",
        "on_pull_request_unlabeled": "unlabeled",
        "on_pull_request_unlocked": "unlocked",
        # Releases
        "on_release_published": "published",
        "on_release_unpublished": "unpublished",
        "on_release_created": "created",
        "on_release_edited": "edited",
        "on_release_deleted": "deleted",
        "on_release_prereleased": "prereleased",
        "on_release_released": "released",
        # Stars
        "on_star_created": "created",
        "on_star_deleted": "deleted",
    }

    @classmethod
    def filter_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        """Filter GitHub webhook deliveries by action so granular trigger ops only fire on matching events."""
        op = (config or {}).get("operation")
        if op not in cls._trigger_event_map:
            return True
        # on_push has no action field — always passes.
        # on_issue_comment fires on all comment actions — always passes.
        if op in ("on_push", "on_issue_comment"):
            return True
        # Merged PR: GitHub sends action="closed" with pull_request.merged=True.
        if op == "on_pull_request_merged":
            return payload.get("action") == "closed" and bool(
                (payload.get("pull_request") or {}).get("merged")
            )
        # on_pull_request_closed must NOT fire for merges (which also use action="closed")
        if op == "on_pull_request_closed":
            return payload.get("action") == "closed" and not bool(
                (payload.get("pull_request") or {}).get("merged")
            )
        expected = cls._TRIGGER_ACTION_MAP.get(op)
        return expected is None or payload.get("action") == expected

    @staticmethod
    def _split_repository(config: Dict[str, Any]):
        """Split the trigger's `owner/name` repository field into a pair."""
        repository = (config or {}).get("repository") or ""
        if "/" not in repository:
            return None, None
        owner, repo = repository.split("/", 1)
        return owner.strip(), repo.strip()

    async def _trigger_on_repository_event(self, config, credentials) -> Dict[str, Any]:
        """Output when the trigger node is run manually from the editor.

        In a live workflow the node fires from a webhook delivery and outputs
        GitHub's event payload directly.
        """
        return {
            "message": (
                "This trigger fires when the subscribed event occurs in the "
                "repository. It outputs the GitHub event payload."
            ),
            "repository": getattr(config, "repository", None),
            "events": self._trigger_event_map.get(
                getattr(config, "operation", None), []
            ),
        }

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # The hook lives ON the repository — switching repos must re-register.
        return {"repository": (config or {}).get("repository")}

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ) -> Dict[str, Any]:
        owner, repo = cls._split_repository(config)
        if not owner or not repo:
            raise ValueError("Select a repository to activate this trigger")
        token = _github_token_from_credential(credential)
        if not token:
            raise ValueError("GitHub credential is missing an access token")
        secret = (config or {}).get("signing_secret") or secrets.token_hex(32)
        events = cls._trigger_event_map.get((config or {}).get("operation")) or ["push"]

        # GitHub's POST /hooks is not idempotent, and knowing "the" stale hook
        # id is unreliable: the config mirror is debounced and the row write
        # races rapid operation flips, so cleanup keyed on a remembered id
        # orphaned one live hook PER operation change (3 hooks → same URL,
        # 2026-07-19). The webhook URL is the identity WE own — sweep every
        # hook pointing at it, so registration converges to exactly one hook
        # regardless of how the races interleaved (and self-heals orphans
        # from before this fix).
        try:
            for hook in await list_github_webhooks(token, owner, repo):
                if ((hook.get("config") or {}).get("url") or "").rstrip("/") == webhook_url.rstrip("/"):
                    await unregister_github_webhook(token, owner, repo, hook.get("id"))
                    logger.info(
                        f"[GithubRestNode] Swept stale hook {hook.get('id')} for {webhook_url}"
                    )
        except Exception as e:
            logger.warning(f"[GithubRestNode] Stale-hook sweep failed: {e}")
            # Fall back to the remembered id so a sweep-permission failure
            # still cleans what it can.
            existing = (config or {}).get("external_webhook_id")
            if existing:
                try:
                    await unregister_github_webhook(token, owner, repo, existing)
                except Exception as e2:
                    logger.warning(f"[GithubRestNode] Could not remove stale hook: {e2}")

        hook_id = await register_github_webhook(
            token, owner, repo, webhook_url, secret, events
        )
        return {"signing_secret": secret, "external_webhook_id": hook_id}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id) -> None:
        owner, repo = cls._split_repository(config)
        hook_id = (config or {}).get("external_webhook_id")
        token = _github_token_from_credential(credential or {})
        if not (owner and repo and hook_id and token):
            return
        await unregister_github_webhook(token, owner, repo, hook_id)

    @classmethod
    async def load_field_options(
        cls,
        field_name,
        credential_data,
        context=None,
        page_token=None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dynamic dropdown options — lists repositories the token can access.

        GitHub's ``GET /user/repos`` has no native search parameter, so search
        mode delegates to :func:`load_paginated_options` which paginates with
        ``page`` numbers and applies the shared substring filter.
        """
        if field_name != "repository":
            return {"options": [], "next_page_token": None}
        token = require_credential_token(
            _github_token_from_credential(credential_data or {}),
            "Connect a GitHub account to load repositories",
        )

        per_page = 100

        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            page = int(cursor) if cursor else 1
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{GITHUB_API_BASE}/user/repos",
                    headers={
                        "Authorization": f"Bearer {token}",
                        **_GITHUB_API_HEADERS,
                    },
                    params={"per_page": per_page, "sort": "updated", "page": page},
                )
                response.raise_for_status()
                batch = response.json() or []
            options = [
                {"value": r["full_name"], "label": r["full_name"]}
                for r in batch
                if r.get("full_name")
            ]
            # GitHub doesn't return a total count; infer "more pages" from a
            # full-page response (a short page is the last one).
            next_cursor = str(page + 1) if len(batch) == per_page else None
            return options, next_cursor

        return await load_paginated_options(
            fetch_page,
            page_token=page_token,
            search=search,
            log_label="GithubRestNode.load_field_options(repository)",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify GitHub's ``X-Hub-Signature-256: sha256=<hex>`` header."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        return verify_hmac_sha256_hex(
            body,
            secret,
            headers.get("x-hub-signature-256", ""),
            prefix="sha256=",
        )

    @classmethod
    def handle_webhook_handshake(cls, body: bytes, headers: Dict[str, str], config=None):
        """Acknowledge GitHub's one-off ``ping`` event without firing a run."""
        if headers.get("x-github-event") == "ping":
            return {"msg": "pong"}
        return None

    def _get_access_token(self, credentials: GithubRestCredential) -> str:
        """Extract access token from either OAuth or PAT credentials."""
        if isinstance(credentials, GithubOAuthCredential):
            return credentials.access_token
        elif isinstance(credentials, GithubPATCredential):
            return credentials.personal_access_token
        else:
            # Fallback for dict-like access (when loaded from DB)
            if hasattr(credentials, "access_token"):
                return credentials.access_token
            elif hasattr(credentials, "personal_access_token"):
                return credentials.personal_access_token
            raise ValueError("Invalid credential type - no access token found")

    @classmethod
    def get_sandbox_setup(cls, *, repo, branch, credential_data):
        """Authenticated-clone spec for an agent sandbox mount (provider mode).

        The token lands in the sandbox's git credential store, so the agent
        can push branches; PR creation stays mediated via the
        ``github__create_pull_request`` node_op tool.
        """
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+", repo or ""):
            raise ValueError(f"agent_sandbox_repo must be 'owner/name', got {repo!r}")
        token = _github_token_from_credential(credential_data)
        if not token:
            raise ValueError("GitHub credential has no usable token for repo mount")
        login = (credential_data or {}).get("login")
        email = (credential_data or {}).get("email")
        return {
            "kind": "git_clone",
            "host": "github.com",
            "repo": repo,
            "branch": branch or None,
            "clone_url": f"https://github.com/{repo}.git",
            "token": token,
            "git_user": login or "NoClick Agent",
            "git_email": email
            or (f"{login}@users.noreply.github.com" if login else "agent@noclick.app"),
        }

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.github_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="github",
        )

    async def _ensure_fresh_token(self, credentials: GithubRestCredential) -> str:
        """Return a valid GitHub token, refreshing expiring OAuth tokens when needed."""
        if not isinstance(credentials, GithubOAuthCredential):
            return self._get_access_token(credentials)

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.github_oauth import (
            is_token_expired,
            refresh_access_token,
        )
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            is_expired=is_token_expired,
            provider="github",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    @classmethod
    async def _resolve_trigger_credential(cls, pool, user_id: str, credential_ids):
        """Load and refresh the trigger credential before webhook registration."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.github_oauth import (
            is_token_expired,
            refresh_access_token,
        )
        from utils.credential_loader import load_credential

        if not credential_ids:
            return None
        credential_id = next((cid for cid in credential_ids.values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id)
        if credential and credential.get("access_token"):
            await ensure_fresh_oauth_token(
                pool=pool,
                credential_id=credential_id,
                user_id=user_id,
                credential=credential,
                refresh=refresh_access_token,
                is_expired=is_token_expired,
                provider="github",
            )
        return credential

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: GithubRestCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """Make an authenticated GitHub API request with timing."""
        total_start = time.time()

        access_token = await self._ensure_fresh_token(credentials)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        url = f"{GITHUB_API_BASE}{endpoint}"

        # Filter out None params
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient() as client:
            # API request timing
            api_start = time.time()
            logger.info(f"[GithubRestNode] 🔌 {method} {endpoint}")

            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=30.0,
            )
            api_time = (time.time() - api_start) * 1000
            logger.info(
                f"[GithubRestNode] ⏱️ API request: {api_time:.1f}ms (status: {response.status_code})"
            )

            # Response parsing timing
            parse_start = time.time()

            if response.status_code >= 400:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("message", response.text)
                logger.error(f"[GithubRestNode] API error: {error_msg}")

                total_time = (time.time() - total_start) * 1000
                output = {
                    "type": "github_rest",
                    "action": action_name,
                    "status": "error",
                    "error": error_msg,
                    "status_code": response.status_code,
                    "data": None,
                    "timestamp": time.time(),
                    "timing_ms": {
                        "api_request": round(api_time, 1),
                        "total": round(total_time, 1),
                    },
                }
                await self.emit(output)
                return output

            # Parse successful response
            data = response.json() if response.content else None
            parse_time = (time.time() - parse_start) * 1000
            logger.info(f"[GithubRestNode] ⏱️ Response parsing: {parse_time:.1f}ms")

            total_time = (time.time() - total_start) * 1000
            logger.info(f"[GithubRestNode] ⏱️ TOTAL time: {total_time:.1f}ms")

            output = {
                "type": "github_rest",
                "action": action_name,
                "status": "success",
                "data": data,
                "timestamp": time.time(),
                "timing_ms": {
                    "api_request": round(api_time, 1),
                    "response_parsing": round(parse_time, 1),
                    "total": round(total_time, 1),
                },
            }

            await self.emit(output)
            return output

    # ============================================================================
    # Repository Actions
    # ============================================================================

    async def _get_repository(
        self, config: GithubGetRepositoryConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get repository information."""
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}",
            credentials,
            action_name="get_repository",
        )

    async def _list_repositories(
        self, config: GithubListRepositoriesConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List repositories for authenticated user."""
        params = {
            "visibility": config.visibility,
            "sort": config.sort,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            "/user/repos",
            credentials,
            params=params,
            action_name="list_authenticated_user_repos",
        )

    # ============================================================================
    # Issues Actions
    # ============================================================================

    async def _list_issues(
        self, config: GithubListIssuesConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List issues in a repository."""
        params = {
            "state": config.state,
            "labels": config.labels,
            "assignee": config.assignee,
            "sort": config.sort,
            "direction": config.direction,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/issues",
            credentials,
            params=params,
            action_name="list_issues",
        )

    async def _get_issue(
        self, config: GithubGetIssueConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a specific issue."""
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}",
            credentials,
            action_name="get_issue",
        )

    async def _create_issue(
        self, config: GithubCreateIssueConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a new issue."""
        body = {
            "title": config.title,
        }
        if config.body:
            body["body"] = config.body
        if config.labels:
            body["labels"] = config.labels
        if config.assignees:
            body["assignees"] = config.assignees

        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/issues",
            credentials,
            json_body=body,
            action_name="create_issue",
        )

    async def _update_issue(
        self, config: GithubUpdateIssueConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update an existing issue."""
        body = {}
        if config.title:
            body["title"] = config.title
        if config.body:
            body["body"] = config.body
        if config.state:
            body["state"] = config.state
        if config.labels is not None:
            body["labels"] = config.labels
        if config.assignees is not None:
            body["assignees"] = config.assignees

        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}",
            credentials,
            json_body=body,
            action_name="update_issue",
        )

    # ============================================================================
    # Pull Request Actions
    # ============================================================================

    async def _list_pull_requests(
        self, config: GithubListPullRequestsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List pull requests."""
        params = {
            "state": config.state,
            "head": config.head,
            "base": config.base,
            "sort": config.sort,
            "direction": config.direction,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls",
            credentials,
            params=params,
            action_name="list_pull_requests",
        )

    async def _get_pull_request(
        self, config: GithubGetPullRequestConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a specific pull request."""
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}",
            credentials,
            action_name="get_pull_request",
        )

    async def _create_pull_request(
        self, config: GithubCreatePullRequestConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a new pull request."""
        body = {
            "title": config.title,
            "head": config.head,
            "base": config.base,
        }
        if config.body:
            body["body"] = config.body
        if config.draft is not None:
            body["draft"] = config.draft

        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/pulls",
            credentials,
            json_body=body,
            action_name="create_pull_request",
        )

    # ============================================================================
    # Commit Actions
    # ============================================================================

    async def _list_commits(
        self, config: GithubListCommitsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List commits in a repository."""
        params = {
            "sha": config.sha,
            "path": config.path,
            "author": config.author,
            "since": config.since,
            "until": config.until,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/commits",
            credentials,
            params=params,
            action_name="list_commits",
        )

    async def _get_commit(
        self, config: GithubGetCommitConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a specific commit."""
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/commits/{config.ref}",
            credentials,
            action_name="get_commit",
        )

    # ============================================================================
    # Branch Actions
    # ============================================================================

    async def _list_branches(
        self, config: GithubListBranchesConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List branches in a repository."""
        params = {"protected": config.protected, "per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/branches",
            credentials,
            params=params,
            action_name="list_branches",
        )

    async def _create_branch(
        self, config: GithubCreateBranchConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a new branch."""
        # First, get the SHA of the source branch
        source_ref = await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/git/refs/heads/{config.source_branch}",
            credentials,
            action_name="get_source_branch",
        )

        if source_ref["status"] == "error":
            return source_ref

        sha = source_ref["data"]["object"]["sha"]

        # Create the new branch
        body = {"ref": f"refs/heads/{config.branch_name}", "sha": sha}
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/git/refs",
            credentials,
            json_body=body,
            action_name="create_branch",
        )

    # ============================================================================
    # File Content Actions
    # ============================================================================

    async def _get_file_contents(
        self, config: GithubGetFileContentsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get file contents."""
        params = {"ref": config.ref} if config.ref else None
        result = await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/contents/{config.path}",
            credentials,
            params=params,
            action_name="get_file_contents",
        )

        # Decode base64 content if present
        if result["status"] == "success" and result["data"]:
            import base64

            if result["data"].get("content"):
                try:
                    content = base64.b64decode(result["data"]["content"]).decode(
                        "utf-8"
                    )
                    result["data"]["decoded_content"] = content
                except Exception as e:
                    logger.warning(f"[GithubRestNode] Could not decode content: {e}")

        return result

    async def _create_or_update_file(
        self, config: GithubCreateOrUpdateFileConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create or update a file."""
        import base64

        encoded_content = base64.b64encode(config.content.encode("utf-8")).decode(
            "utf-8"
        )

        body = {
            "message": config.message,
            "content": encoded_content,
        }
        if config.branch:
            body["branch"] = config.branch
        if config.sha:
            body["sha"] = config.sha

        return await self._make_request(
            "PUT",
            f"/repos/{config.owner}/{config.repo}/contents/{config.path}",
            credentials,
            json_body=body,
            action_name="create_or_update_file",
        )

    # ============================================================================
    # Comment Actions
    # ============================================================================

    async def _create_issue_comment(
        self, config: GithubCreateIssueCommentConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a comment on an issue or PR."""
        body = {"body": config.body}
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/comments",
            credentials,
            json_body=body,
            action_name="create_issue_comment",
        )

    # ============================================================================
    # Workflow Actions
    # ============================================================================

    async def _list_workflow_runs(
        self, config: GithubListWorkflowRunsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List workflow runs."""
        params = {
            "branch": config.branch,
            "event": config.event,
            "status": config.status,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs",
            credentials,
            params=params,
            action_name="list_workflow_runs",
        )

    # ============================================================================
    # Search Actions
    # ============================================================================

    async def _search_issues(
        self, config: GithubSearchIssuesConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Search issues and pull requests."""
        params = {
            "q": config.query,
            "sort": config.sort,
            "order": config.order,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            "/search/issues",
            credentials,
            params=params,
            action_name="search_issues",
        )

    async def _search_code(
        self, config: GithubSearchCodeConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Search code across repositories."""
        params = {
            "q": config.query,
            "sort": config.sort,
            "order": config.order,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET", "/search/code", credentials, params=params, action_name="search_code"
        )

    async def _search_repositories(
        self, config: GithubSearchRepositoriesConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Search repositories."""
        params = {
            "q": config.query,
            "sort": config.sort,
            "order": config.order,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            "/search/repositories",
            credentials,
            params=params,
            action_name="search_repositories",
        )

    # ============================================================================
    # Additional Pull Request Actions
    # ============================================================================

    async def _update_pull_request(
        self, config: GithubUpdatePullRequestConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update an existing pull request."""
        body = {}
        if config.title:
            body["title"] = config.title
        if config.body:
            body["body"] = config.body
        if config.state:
            body["state"] = config.state
        if config.base:
            body["base"] = config.base

        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}",
            credentials,
            json_body=body,
            action_name="update_pull_request",
        )

    async def _merge_pull_request(
        self, config: GithubMergePullRequestConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Merge a pull request."""
        body = {}
        if config.commit_title:
            body["commit_title"] = config.commit_title
        if config.commit_message:
            body["commit_message"] = config.commit_message
        if config.merge_method:
            body["merge_method"] = config.merge_method

        return await self._make_request(
            "PUT",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/merge",
            credentials,
            json_body=body,
            action_name="merge_pull_request",
        )

    async def _list_pull_request_files(
        self,
        config: GithubListPullRequestFilesConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List files changed in a pull request."""
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/files",
            credentials,
            params=params,
            action_name="list_pull_request_files",
        )

    # ============================================================================
    # Release Actions
    # ============================================================================

    async def _list_releases(
        self, config: GithubListReleasesConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List releases for a repository."""
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/releases",
            credentials,
            params=params,
            action_name="list_releases",
        )

    async def _get_release(
        self, config: GithubGetReleaseConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a specific release or latest release."""
        if config.release_id:
            endpoint = (
                f"/repos/{config.owner}/{config.repo}/releases/{config.release_id}"
            )
        else:
            endpoint = f"/repos/{config.owner}/{config.repo}/releases/latest"

        return await self._make_request(
            "GET", endpoint, credentials, action_name="get_release"
        )

    async def _create_release(
        self, config: GithubCreateReleaseConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a new release."""
        body = {
            "tag_name": config.tag_name,
        }
        if config.name:
            body["name"] = config.name
        if config.body:
            body["body"] = config.body
        if config.draft is not None:
            body["draft"] = config.draft
        if config.prerelease is not None:
            body["prerelease"] = config.prerelease
        if config.target_commitish:
            body["target_commitish"] = config.target_commitish

        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/releases",
            credentials,
            json_body=body,
            action_name="create_release",
        )

    # ============================================================================
    # User Actions
    # ============================================================================

    async def _get_authenticated_user(
        self,
        config: GithubGetAuthenticatedUserConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Get the authenticated user."""
        return await self._make_request(
            "GET", "/user", credentials, action_name="get_authenticated_user"
        )

    async def _get_user(
        self, config: GithubGetUserConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a specific user."""
        return await self._make_request(
            "GET", f"/users/{config.username}", credentials, action_name="get_user"
        )

    # ============================================================================
    # Additional Issue Actions
    # ============================================================================

    async def _list_issue_comments(
        self, config: GithubListIssueCommentsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List comments on an issue."""
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/comments",
            credentials,
            params=params,
            action_name="list_issue_comments",
        )

    async def _add_labels_to_issue(
        self, config: GithubAddLabelsToIssueConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Add labels to an issue."""
        body = {"labels": config.labels}
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/labels",
            credentials,
            json_body=body,
            action_name="add_labels_to_issue",
        )

    # ============================================================================
    # Label Actions
    # ============================================================================

    async def _list_labels(
        self, config: GithubListLabelsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List labels for a repository."""
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/labels",
            credentials,
            params=params,
            action_name="list_repo_labels",
        )

    async def _create_label(
        self, config: GithubCreateLabelConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a label."""
        body = {
            "name": config.name,
            "color": config.color,
        }
        if config.description:
            body["description"] = config.description

        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/labels",
            credentials,
            json_body=body,
            action_name="create_label",
        )

    # ============================================================================
    # Additional Branch Actions
    # ============================================================================

    async def _delete_branch(
        self, config: GithubDeleteBranchConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a branch."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/git/refs/heads/{config.branch_name}",
            credentials,
            action_name="delete_branch",
        )

    async def _list_tags(
        self, config: GithubListTagsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List tags in a repository."""
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/tags",
            credentials,
            params=params,
            action_name="list_repo_tags",
        )

    # ============================================================================
    # Additional File Actions
    # ============================================================================

    async def _delete_file(
        self, config: GithubDeleteFileConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a file from a repository."""
        body = {
            "message": config.message,
            "sha": config.sha,
        }
        if config.branch:
            body["branch"] = config.branch

        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/contents/{config.path}",
            credentials,
            json_body=body,
            action_name="delete_file",
        )

    # ============================================================================
    # Additional Repository Actions
    # ============================================================================

    async def _list_organization_repos(
        self,
        config: GithubListOrganizationReposConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List repositories for an organization."""
        params = {
            "type": config.type,
            "sort": config.sort,
            "direction": config.direction,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/repos",
            credentials,
            params=params,
            action_name="list_org_repos",
        )

    async def _fork_repository(
        self, config: GithubForkRepositoryConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Fork a repository."""
        body = {}
        if config.organization:
            body["organization"] = config.organization
        if config.name:
            body["name"] = config.name

        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/forks",
            credentials,
            json_body=body if body else None,
            action_name="fork_repository",
        )

    async def _list_collaborators(
        self, config: GithubListCollaboratorsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List collaborators for a repository."""
        params = {"affiliation": config.affiliation, "per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/collaborators",
            credentials,
            params=params,
            action_name="list_repo_collaborators",
        )

    async def _create_repo_webhook(
        self, config: GithubCreateRepoWebhookConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a webhook for a repository."""
        body = {
            "name": "web",
            "active": config.active,
            "events": config.events,
            "config": {
                "url": config.url,
                "content_type": config.content_type,
            },
        }

        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/hooks",
            credentials,
            json_body=body,
            action_name="create_repo_webhook",
        )

    # ============================================================================
    # Additional Workflow Actions
    # ============================================================================

    async def _trigger_workflow_dispatch(
        self,
        config: GithubTriggerWorkflowDispatchConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Trigger a workflow dispatch event."""
        body = {
            "ref": config.ref,
        }
        if config.inputs:
            body["inputs"] = config.inputs

        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/actions/workflows/{config.workflow_id}/dispatches",
            credentials,
            json_body=body,
            action_name="trigger_workflow_dispatch",
        )

    # ============================================================================
    # Comprehensive Additional Handler Methods
    # ============================================================================

    async def _list_milestones(
        self, config: GithubListMilestonesConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {
            "state": config.state,
            "sort": config.sort,
            "direction": config.direction,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/milestones",
            credentials,
            params=params,
            action_name="list_milestones",
        )

    async def _create_milestone(
        self, config: GithubCreateMilestoneConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        body = {"title": config.title}
        if config.state:
            body["state"] = config.state
        if config.description:
            body["description"] = config.description
        if config.due_on:
            body["due_on"] = config.due_on
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/milestones",
            credentials,
            json_body=body,
            action_name="create_milestone",
        )

    async def _list_assignees(
        self, config: GithubListAssigneesConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/assignees",
            credentials,
            params=params,
            action_name="list_issue_assignees",
        )

    async def _request_reviewers(
        self, config: GithubRequestReviewersConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        body = {}
        if config.reviewers:
            body["reviewers"] = config.reviewers
        if config.team_reviewers:
            body["team_reviewers"] = config.team_reviewers
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/requested_reviewers",
            credentials,
            json_body=body,
            action_name="request_pull_request_reviewers",
        )

    async def _list_pull_request_reviews(
        self,
        config: GithubListPullRequestReviewsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/reviews",
            credentials,
            params=params,
            action_name="list_pull_request_reviews",
        )

    async def _create_pull_request_review(
        self,
        config: GithubCreatePullRequestReviewConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        body = {"event": config.event}
        if config.body:
            body["body"] = config.body
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/reviews",
            credentials,
            json_body=body,
            action_name="create_pull_request_review",
        )

    async def _list_gists(
        self, config: GithubListGistsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"per_page": config.per_page}
        if config.since:
            params["since"] = config.since
        return await self._make_request(
            "GET",
            "/gists",
            credentials,
            params=params,
            action_name="list_authenticated_user_gists",
        )

    async def _get_gist(
        self, config: GithubGetGistConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"/gists/{config.gist_id}", credentials, action_name="get_gist"
        )

    async def _create_gist(
        self, config: GithubCreateGistConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        body = {
            "files": {config.filename: {"content": config.content}},
            "public": config.public,
        }
        if config.description:
            body["description"] = config.description
        return await self._make_request(
            "POST", "/gists", credentials, json_body=body, action_name="create_gist"
        )

    async def _star_repository(
        self, config: GithubStarRepositoryConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        return await self._make_request(
            "PUT",
            f"/user/starred/{config.owner}/{config.repo}",
            credentials,
            action_name="star_repository",
        )

    async def _unstar_repository(
        self, config: GithubUnstarRepositoryConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        return await self._make_request(
            "DELETE",
            f"/user/starred/{config.owner}/{config.repo}",
            credentials,
            action_name="unstar_repository",
        )

    async def _list_stargazers(
        self, config: GithubListStargazersConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/stargazers",
            credentials,
            params=params,
            action_name="list_repo_stargazers",
        )

    async def _list_forks(
        self, config: GithubListForksConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"sort": config.sort, "per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/forks",
            credentials,
            params=params,
            action_name="list_repo_forks",
        )

    async def _list_contributors(
        self, config: GithubListContributorsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {
            "anon": str(config.anon).lower() if config.anon else None,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/contributors",
            credentials,
            params=params,
            action_name="list_repo_contributors",
        )

    async def _get_repo_languages(
        self, config: GithubGetRepoLanguagesConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/languages",
            credentials,
            action_name="get_repo_languages",
        )

    async def _get_repo_topics(
        self, config: GithubGetRepoTopicsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/topics",
            credentials,
            action_name="get_repo_topics",
        )

    async def _set_repo_topics(
        self, config: GithubSetRepoTopicsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        body = {"names": config.names}
        return await self._make_request(
            "PUT",
            f"/repos/{config.owner}/{config.repo}/topics",
            credentials,
            json_body=body,
            action_name="set_repo_topics",
        )

    async def _compare_commits(
        self, config: GithubCompareCommitsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/compare/{config.base}...{config.head}",
            credentials,
            action_name="compare_commits",
        )

    async def _list_check_runs(
        self, config: GithubListCheckRunsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"status": config.status, "per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/commits/{config.ref}/check-runs",
            credentials,
            params=params,
            action_name="list_commit_check_runs",
        )

    async def _list_deployments(
        self, config: GithubListDeploymentsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {
            "environment": config.environment,
            "ref": config.ref,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/deployments",
            credentials,
            params=params,
            action_name="list_deployments",
        )

    async def _create_deployment(
        self, config: GithubCreateDeploymentConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        body = {
            "ref": config.ref,
            "environment": config.environment,
            "auto_merge": config.auto_merge,
        }
        if config.description:
            body["description"] = config.description
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/deployments",
            credentials,
            json_body=body,
            action_name="create_deployment",
        )

    async def _list_notifications(
        self, config: GithubListNotificationsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {
            "all": config.all,
            "participating": config.participating,
            "since": config.since,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            "/notifications",
            credentials,
            params=params,
            action_name="list_notifications",
        )

    async def _mark_notifications_read(
        self,
        config: GithubMarkNotificationsReadConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        body = {}
        if config.last_read_at:
            body["last_read_at"] = config.last_read_at
        return await self._make_request(
            "PUT",
            "/notifications",
            credentials,
            json_body=body,
            action_name="mark_notifications_as_read",
        )

    async def _list_org_teams(
        self, config: GithubListOrgTeamsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/teams",
            credentials,
            params=params,
            action_name="list_org_teams",
        )

    async def _list_org_members(
        self, config: GithubListOrgMembersConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"role": config.role, "per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/members",
            credentials,
            params=params,
            action_name="list_org_members",
        )

    async def _list_repo_contents(
        self, config: GithubListRepoContentsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"ref": config.ref} if config.ref else None
        path = config.path or ""
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/contents/{path}",
            credentials,
            params=params,
            action_name="list_repo_directory_contents",
        )

    async def _create_repo_from_template(
        self,
        config: GithubCreateRepoFromTemplateConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        body = {
            "name": config.name,
            "private": config.private,
            "include_all_branches": config.include_all_branches,
        }
        if config.owner:
            body["owner"] = config.owner
        if config.description:
            body["description"] = config.description
        return await self._make_request(
            "POST",
            f"/repos/{config.template_owner}/{config.template_repo}/generate",
            credentials,
            json_body=body,
            action_name="create_repo_from_template",
        )

    async def _create_issue_reaction(
        self, config: GithubCreateIssueReactionConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        body = {"content": config.content}
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/reactions",
            credentials,
            json_body=body,
            action_name="create_reaction_on_issue",
        )

    async def _list_user_repos(
        self, config: GithubListUserReposConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {
            "type": config.type,
            "sort": config.sort,
            "direction": config.direction,
            "per_page": config.per_page,
        }
        return await self._make_request(
            "GET",
            f"/users/{config.username}/repos",
            credentials,
            params=params,
            action_name="list_user_repos",
        )

    async def _list_user_followers(
        self, config: GithubListUserFollowersConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/users/{config.username}/followers",
            credentials,
            params=params,
            action_name="list_user_followers",
        )

    async def _list_user_following(
        self, config: GithubListUserFollowingConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/users/{config.username}/following",
            credentials,
            params=params,
            action_name="list_user_following",
        )

    async def _list_workflows(
        self, config: GithubListWorkflowsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        params = {"per_page": config.per_page}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/workflows",
            credentials,
            params=params,
            action_name="list_workflows",
        )

    async def _get_workflow_run(
        self, config: GithubGetWorkflowRunConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}",
            credentials,
            action_name="get_workflow_run",
        )

    async def _cancel_workflow_run(
        self, config: GithubCancelWorkflowRunConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/cancel",
            credentials,
            action_name="cancel_workflow_run",
        )

    async def _rerun_workflow(
        self, config: GithubRerunWorkflowConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/rerun",
            credentials,
            action_name="rerun_workflow",
        )

    # ==================== NEWLY ADDED HANDLER METHODS ====================

    async def _list_pull_request_review_comments(
        self,
        config: GithubListPullRequestReviewCommentsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List review comments on a pull request."""
        params = {}
        if config.sort is not None:
            params["sort"] = config.sort
        if config.direction is not None:
            params["direction"] = config.direction
        if config.since is not None:
            params["since"] = config.since
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/comments",
            credentials,
            params=params,
            action_name="list_pull_request_review_comments",
        )

    async def _create_pull_request_review_comment(
        self,
        config: GithubCreatePullRequestReviewCommentConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Create a review comment on a pull request."""
        params = {}
        params["commit_id"] = config.commit_id
        params["path"] = config.path
        if config.line is not None:
            params["line"] = config.line
        body = {}
        body["body"] = config.body
        if config.side is not None:
            body["side"] = config.side
        if config.start_line is not None:
            body["start_line"] = config.start_line
        if config.start_side is not None:
            body["start_side"] = config.start_side
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/comments",
            credentials,
            json_body=body,
            params=params,
            action_name="create_pull_request_review_comment",
        )

    async def _get_pull_request_review_comment(
        self,
        config: GithubGetPullRequestReviewCommentConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Get a specific review comment."""
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls/comments/{config.comment_id}",
            credentials,
            action_name="get_pull_request_review_comment",
        )

    async def _update_pull_request_review_comment(
        self,
        config: GithubUpdatePullRequestReviewCommentConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Update a review comment."""
        body = {}
        body["body"] = config.body
        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/pulls/comments/{config.comment_id}",
            credentials,
            json_body=body,
            action_name="update_pull_request_review_comment",
        )

    async def _delete_pull_request_review_comment(
        self,
        config: GithubDeletePullRequestReviewCommentConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Delete a review comment."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/pulls/comments/{config.comment_id}",
            credentials,
            action_name="delete_pull_request_review_comment",
        )

    async def _reply_to_pull_request_review_comment(
        self,
        config: GithubReplyToPullRequestReviewCommentConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Reply to a review comment."""
        body = {}
        body["body"] = config.body
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/comments/{config.comment_id}/replies",
            credentials,
            json_body=body,
            action_name="reply_to_pull_request_review_comment",
        )

    async def _update_pull_request_review(
        self,
        config: GithubUpdatePullRequestReviewConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Update a pending review."""
        body = {}
        body["body"] = config.body
        return await self._make_request(
            "PUT",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/reviews/{config.review_id}",
            credentials,
            json_body=body,
            action_name="update_pull_request_review",
        )

    async def _delete_pending_pull_request_review(
        self,
        config: GithubDeletePendingPullRequestReviewConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Delete a pending review."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/reviews/{config.review_id}",
            credentials,
            action_name="delete_pending_pull_request_review",
        )

    async def _get_pull_request_review_comments(
        self,
        config: GithubGetPullRequestReviewCommentsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Get comments for a specific review."""
        params = {}
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/reviews/{config.review_id}/comments",
            credentials,
            params=params,
            action_name="list_review_comments_for_review",
        )

    async def _submit_pull_request_review(
        self,
        config: GithubSubmitPullRequestReviewConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Submit a pending review."""
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/reviews/{config.review_id}/events",
            credentials,
            json_body=body,
            action_name="submit_pull_request_review",
        )

    async def _dismiss_pull_request_review(
        self,
        config: GithubDismissPullRequestReviewConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Dismiss a review."""
        params = {}
        params["message"] = config.message
        body = {}
        body["message"] = config.message
        if config.event is not None:
            body["event"] = config.event
        return await self._make_request(
            "PUT",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/reviews/{config.review_id}/dismissals",
            credentials,
            json_body=body,
            params=params,
            action_name="dismiss_pull_request_review",
        )

    async def _list_pull_request_commits(
        self,
        config: GithubListPullRequestCommitsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List commits on a pull request."""
        params = {}
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/commits",
            credentials,
            params=params,
            action_name="list_pull_request_commits",
        )

    async def _check_if_pull_request_merged(
        self,
        config: GithubCheckIfPullRequestMergedConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Check if a pull request has been merged."""
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/merge",
            credentials,
            action_name="check_pull_request_merged",
        )

    async def _update_pull_request_branch(
        self,
        config: GithubUpdatePullRequestBranchConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Update pull request branch with latest base branch."""
        params = {}
        if config.expected_head_sha is not None:
            params["expected_head_sha"] = config.expected_head_sha
        return await self._make_request(
            "PUT",
            f"/repos/{config.owner}/{config.repo}/pulls/{config.pull_number}/update-branch",
            credentials,
            json_body=body,
            params=params,
            action_name="update_pull_request_branch",
        )

    # Generated Handler Methods

    async def _update_repository(
        self, config: GithubUpdateRepositoryConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update repository settings."""
        params = {}
        if config.name is not None:
            params["name"] = config.name
        if config.description is not None:
            params["description"] = config.description
        if config.homepage is not None:
            params["homepage"] = config.homepage
        if config.private is not None:
            params["private"] = config.private
        if config.has_issues is not None:
            params["has_issues"] = config.has_issues
        if config.has_projects is not None:
            params["has_projects"] = config.has_projects
        if config.has_wiki is not None:
            params["has_wiki"] = config.has_wiki
        if config.default_branch is not None:
            params["default_branch"] = config.default_branch
        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}",
            credentials,
            action_name="update_repository",
        )

    async def _delete_repository(
        self, config: GithubDeleteRepositoryConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a repository."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}",
            credentials,
            action_name="delete_repository",
        )

    async def _create_repository_for_authenticated_user(
        self,
        config: GithubCreateRepositoryForAuthenticatedUserConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Create a repository for the authenticated user."""
        params = {}
        if config.description is not None:
            params["description"] = config.description
        if config.homepage is not None:
            params["homepage"] = config.homepage
        if config.private is not None:
            params["private"] = config.private
        if config.has_issues is not None:
            params["has_issues"] = config.has_issues
        if config.has_projects is not None:
            params["has_projects"] = config.has_projects
        if config.has_wiki is not None:
            params["has_wiki"] = config.has_wiki
        if config.auto_init is not None:
            params["auto_init"] = config.auto_init
        body = {}
        body["name"] = config.name
        return await self._make_request(
            "POST",
            f"/user/repos",
            credentials,
            json_body=body,
            action_name="create_repo_for_authenticated_user",
        )

    async def _transfer_repository(
        self, config: GithubTransferRepositoryConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Transfer repository ownership."""
        params = {}
        if config.team_ids is not None:
            params["team_ids"] = config.team_ids
        body = {}
        body["new_owner"] = config.new_owner
        body["new_owner"] = config.new_owner
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/transfer",
            credentials,
            json_body=body,
            action_name="transfer_repository",
        )

    async def _lock_issue(
        self, config: GithubLockIssueConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Lock an issue conversation."""
        params = {}
        if config.lock_reason is not None:
            params["lock_reason"] = config.lock_reason
        return await self._make_request(
            "PUT",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/lock",
            credentials,
            action_name="lock_issue",
        )

    async def _unlock_issue(
        self, config: GithubUnlockIssueConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Unlock an issue conversation."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/lock",
            credentials,
            action_name="unlock_issue",
        )

    async def _get_issue_comment(
        self, config: GithubGetIssueCommentConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a specific issue comment."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/issues/comments/{config.comment_id}",
            credentials,
            action_name="get_issue_comment",
        )

    async def _update_issue_comment(
        self, config: GithubUpdateIssueCommentConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update an issue comment."""
        body = {}
        body["body"] = config.body
        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/issues/comments/{config.comment_id}",
            credentials,
            json_body=body,
            action_name="update_issue_comment",
        )

    async def _delete_issue_comment(
        self, config: GithubDeleteIssueCommentConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete an issue comment."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/issues/comments/{config.comment_id}",
            credentials,
            action_name="delete_issue_comment",
        )

    async def _get_label(
        self, config: GithubGetLabelConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a label."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/labels/{config.name}",
            credentials,
            action_name="get_label",
        )

    async def _update_label(
        self, config: GithubUpdateLabelConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update a label."""
        params = {}
        if config.new_name is not None:
            params["new_name"] = config.new_name
        if config.color is not None:
            params["color"] = config.color
        if config.description is not None:
            params["description"] = config.description
        body = {}
        body["name"] = config.name
        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/labels/{config.name}",
            credentials,
            json_body=body,
            action_name="update_label",
        )

    async def _delete_label(
        self, config: GithubDeleteLabelConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a label."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/labels/{config.name}",
            credentials,
            action_name="delete_label",
        )

    async def _set_issue_labels(
        self, config: GithubSetIssueLabelsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Set labels for an issue (replaces all)."""
        body = {}
        body["labels"] = config.labels
        return await self._make_request(
            "PUT",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/labels",
            credentials,
            json_body=body,
            action_name="set_issue_labels",
        )

    async def _remove_all_issue_labels(
        self,
        config: GithubRemoveAllIssueLabelsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Remove all labels from an issue."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/labels",
            credentials,
            action_name="remove_all_labels_from_issue",
        )

    async def _remove_issue_label(
        self, config: GithubRemoveIssueLabelConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Remove a label from an issue."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/labels/{config.name}",
            credentials,
            action_name="remove_label_from_issue",
        )

    async def _get_milestone(
        self, config: GithubGetMilestoneConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a milestone."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/milestones/{config.milestone_number}",
            credentials,
            action_name="get_milestone",
        )

    async def _update_milestone(
        self, config: GithubUpdateMilestoneConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update a milestone."""
        params = {}
        if config.title is not None:
            params["title"] = config.title
        if config.state is not None:
            params["state"] = config.state
        if config.description is not None:
            params["description"] = config.description
        if config.due_on is not None:
            params["due_on"] = config.due_on
        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/milestones/{config.milestone_number}",
            credentials,
            action_name="update_milestone",
        )

    async def _delete_milestone(
        self, config: GithubDeleteMilestoneConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a milestone."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/milestones/{config.milestone_number}",
            credentials,
            action_name="delete_milestone",
        )

    async def _update_release(
        self, config: GithubUpdateReleaseConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update a release."""
        params = {}
        if config.tag_name is not None:
            params["tag_name"] = config.tag_name
        if config.name is not None:
            params["name"] = config.name
        if config.body is not None:
            params["body"] = config.body
        if config.draft is not None:
            params["draft"] = config.draft
        if config.prerelease is not None:
            params["prerelease"] = config.prerelease
        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/releases/{config.release_id}",
            credentials,
            action_name="update_release",
        )

    async def _delete_release(
        self, config: GithubDeleteReleaseConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a release."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/releases/{config.release_id}",
            credentials,
            action_name="delete_release",
        )

    async def _get_latest_release(
        self, config: GithubGetLatestReleaseConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get the latest release."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/releases/latest",
            credentials,
            action_name="get_latest_release",
        )

    async def _get_release_by_tag(
        self, config: GithubGetReleaseByTagConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a release by tag name."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/releases/tags/{config.tag}",
            credentials,
            action_name="get_release_by_tag",
        )

    async def _generate_release_notes(
        self,
        config: GithubGenerateReleaseNotesConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Generate release notes."""
        params = {}
        if config.target_commitish is not None:
            params["target_commitish"] = config.target_commitish
        if config.previous_tag_name is not None:
            params["previous_tag_name"] = config.previous_tag_name
        if config.configuration_file_path is not None:
            params["configuration_file_path"] = config.configuration_file_path
        body = {}
        body["tag_name"] = config.tag_name
        body["tag_name"] = config.tag_name
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/releases/generate-notes",
            credentials,
            json_body=body,
            action_name="generate_release_notes",
        )

    async def _list_release_assets(
        self, config: GithubListReleaseAssetsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List release assets."""
        params = {}
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/releases/{config.release_id}/assets",
            credentials,
            params=params,
            action_name="list_release_assets",
        )

    async def _get_release_asset(
        self, config: GithubGetReleaseAssetConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a release asset."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/releases/assets/{config.asset_id}",
            credentials,
            action_name="get_release_asset",
        )

    async def _update_release_asset(
        self, config: GithubUpdateReleaseAssetConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update a release asset."""
        params = {}
        if config.name is not None:
            params["name"] = config.name
        if config.label is not None:
            params["label"] = config.label
        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/releases/assets/{config.asset_id}",
            credentials,
            action_name="update_release_asset",
        )

    async def _delete_release_asset(
        self, config: GithubDeleteReleaseAssetConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a release asset."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/releases/assets/{config.asset_id}",
            credentials,
            action_name="delete_release_asset",
        )

    async def _update_gist(
        self, config: GithubUpdateGistConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update a gist."""
        params = {}
        if config.description is not None:
            params["description"] = config.description
        body = {}
        body["files"] = config.files
        return await self._make_request(
            "PATCH",
            f"/gists/{config.gist_id}",
            credentials,
            json_body=body,
            action_name="update_gist",
        )

    async def _delete_gist(
        self, config: GithubDeleteGistConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a gist."""
        return await self._make_request(
            "DELETE", f"/gists/{config.gist_id}", credentials, action_name="delete_gist"
        )

    async def _list_public_gists(
        self, config: GithubListPublicGistsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List public gists."""
        params = {}
        if config.since is not None:
            params["since"] = config.since
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/gists/public",
            credentials,
            params=params,
            action_name="list_public_gists",
        )

    async def _list_starred_gists(
        self, config: GithubListStarredGistsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List starred gists."""
        params = {}
        if config.since is not None:
            params["since"] = config.since
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/gists/starred",
            credentials,
            params=params,
            action_name="list_starred_gists",
        )

    async def _star_gist(
        self, config: GithubStarGistConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Star a gist."""
        return await self._make_request(
            "PUT", f"/gists/{config.gist_id}/star", credentials, action_name="star_gist"
        )

    async def _unstar_gist(
        self, config: GithubUnstarGistConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Unstar a gist."""
        return await self._make_request(
            "DELETE",
            f"/gists/{config.gist_id}/star",
            credentials,
            action_name="unstar_gist",
        )

    async def _check_if_gist_is_starred(
        self,
        config: GithubCheckIfGistIsStarredConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Check if a gist is starred."""
        params = {}
        return await self._make_request(
            "GET",
            f"/gists/{config.gist_id}/star",
            credentials,
            action_name="check_gist_starred",
        )

    async def _fork_gist(
        self, config: GithubForkGistConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Fork a gist."""
        return await self._make_request(
            "POST",
            f"/gists/{config.gist_id}/forks",
            credentials,
            action_name="fork_gist",
        )

    async def _list_gist_forks(
        self, config: GithubListGistForksConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List gist forks."""
        params = {}
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/gists/{config.gist_id}/forks",
            credentials,
            params=params,
            action_name="list_gist_forks",
        )

    async def _list_gist_commits(
        self, config: GithubListGistCommitsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List gist commits."""
        params = {}
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/gists/{config.gist_id}/commits",
            credentials,
            params=params,
            action_name="list_gist_commits",
        )

    async def _get_gist_revision(
        self, config: GithubGetGistRevisionConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a specific gist revision."""
        params = {}
        return await self._make_request(
            "GET",
            f"/gists/{config.gist_id}/{config.sha}",
            credentials,
            action_name="get_gist_revision",
        )

    async def _list_user_gists(
        self, config: GithubListUserGistsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List gists for a user."""
        params = {}
        if config.since is not None:
            params["since"] = config.since
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/users/{config.username}/gists",
            credentials,
            params=params,
            action_name="list_user_gists",
        )

    async def _list_branches_for_head_commit(
        self,
        config: GithubListBranchesForHeadCommitConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List branches where commit is the HEAD."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/commits/{config.commit_sha}/branches-where-head",
            credentials,
            action_name="list_branches_by_head_commit",
        )

    async def _list_pull_requests_for_commit(
        self,
        config: GithubListPullRequestsForCommitConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List pull requests associated with a commit."""
        params = {}
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/commits/{config.commit_sha}/pulls",
            credentials,
            params=params,
            action_name="list_pull_requests_by_commit",
        )

    async def _list_commit_comments(
        self, config: GithubListCommitCommentsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List comments for a commit."""
        params = {}
        if config.per_page is not None:
            params["per_page"] = config.per_page
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/commits/{config.commit_sha}/comments",
            credentials,
            params=params,
            action_name="list_commit_comments",
        )

    async def _create_commit_comment(
        self, config: GithubCreateCommitCommentConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a comment on a commit."""
        params = {}
        if config.path is not None:
            params["path"] = config.path
        if config.position is not None:
            params["position"] = config.position
        if config.line is not None:
            params["line"] = config.line
        body = {}
        body["body"] = config.body
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/commits/{config.commit_sha}/comments",
            credentials,
            json_body=body,
            action_name="create_commit_comment",
        )

    async def _create_commit_status(
        self, config: GithubCreateCommitStatusConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a commit status."""
        params = {}
        if config.target_url is not None:
            params["target_url"] = config.target_url
        if config.description is not None:
            params["description"] = config.description
        if config.context is not None:
            params["context"] = config.context
        body = {}
        body["state"] = config.state
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/statuses/{config.sha}",
            credentials,
            json_body=body,
            action_name="create_commit_status",
        )

    async def _get_repository_webhook(
        self,
        config: GithubGetRepositoryWebhookConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Get a repository webhook."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/hooks/{config.hook_id}",
            credentials,
            action_name="get_repo_webhook",
        )

    async def _update_repository_webhook(
        self,
        config: GithubUpdateRepositoryWebhookConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Update a repository webhook."""
        params = {}
        if config.config is not None:
            params["config"] = config.config
        if config.events is not None:
            params["events"] = config.events
        if config.active is not None:
            params["active"] = config.active
        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/hooks/{config.hook_id}",
            credentials,
            action_name="update_repo_webhook",
        )

    async def _delete_repository_webhook(
        self,
        config: GithubDeleteRepositoryWebhookConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Delete a repository webhook."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/hooks/{config.hook_id}",
            credentials,
            action_name="delete_repo_webhook",
        )

    async def _ping_repository_webhook(
        self,
        config: GithubPingRepositoryWebhookConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Ping a repository webhook."""
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/hooks/{config.hook_id}/pings",
            credentials,
            action_name="ping_repo_webhook",
        )

    async def _test_repository_webhook(
        self,
        config: GithubTestRepositoryWebhookConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Test a repository webhook."""
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/hooks/{config.hook_id}/tests",
            credentials,
            action_name="test_repo_webhook",
        )

    async def _list_webhook_deliveries(
        self,
        config: GithubListWebhookDeliveriesConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List webhook deliveries."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/hooks/{config.hook_id}/deliveries",
            credentials,
            action_name="list_webhook_deliveries",
        )

    async def _get_webhook_delivery(
        self, config: GithubGetWebhookDeliveryConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a webhook delivery."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/hooks/{config.hook_id}/deliveries/{config.delivery_id}",
            credentials,
            action_name="get_webhook_delivery",
        )

    async def _redeliver_webhook(
        self, config: GithubRedeliverWebhookConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Redeliver a webhook."""
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/hooks/{config.hook_id}/deliveries/{config.delivery_id}/attempts",
            credentials,
            action_name="redeliver_webhook",
        )

    async def _add_repository_collaborator(
        self,
        config: GithubAddRepositoryCollaboratorConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Add a repository collaborator."""
        params = {}
        if config.permission is not None:
            params["permission"] = config.permission
        return await self._make_request(
            "PUT",
            f"/repos/{config.owner}/{config.repo}/collaborators/{config.username}",
            credentials,
            action_name="add_repo_collaborator",
        )

    async def _remove_repository_collaborator(
        self,
        config: GithubRemoveRepositoryCollaboratorConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Remove a repository collaborator."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/collaborators/{config.username}",
            credentials,
            action_name="remove_repo_collaborator",
        )

    async def _get_repository_permissions(
        self,
        config: GithubGetRepositoryPermissionsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Get repository permissions for a user."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/collaborators/{config.username}/permission",
            credentials,
            action_name="get_user_repo_permissions",
        )

    async def _check_if_user_is_collaborator(
        self,
        config: GithubCheckIfUserIsCollaboratorConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Check if a user is a collaborator."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/collaborators/{config.username}",
            credentials,
            action_name="check_user_is_collaborator",
        )

    async def _list_repository_invitations(
        self,
        config: GithubListRepositoryInvitationsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List repository invitations."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/invitations",
            credentials,
            action_name="list_repo_invitations",
        )

    async def _update_repository_invitation(
        self,
        config: GithubUpdateRepositoryInvitationConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Update a repository invitation."""
        params = {}
        if config.permissions is not None:
            params["permissions"] = config.permissions
        return await self._make_request(
            "PATCH",
            f"/repos/{config.owner}/{config.repo}/invitations/{config.invitation_id}",
            credentials,
            action_name="update_repo_invitation",
        )

    async def _create_team(
        self, config: GithubCreateTeamConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Create a team."""
        params = {}
        if config.description is not None:
            params["description"] = config.description
        if config.maintainers is not None:
            params["maintainers"] = config.maintainers
        if config.repo_names is not None:
            params["repo_names"] = config.repo_names
        if config.privacy is not None:
            params["privacy"] = config.privacy
        body = {}
        body["name"] = config.name
        return await self._make_request(
            "POST",
            f"/orgs/{config.org}/teams",
            credentials,
            json_body=body,
            action_name="create_team",
        )

    async def _get_team(
        self, config: GithubGetTeamConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a team."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/teams/{config.team_slug}",
            credentials,
            action_name="get_team",
        )

    async def _update_team(
        self, config: GithubUpdateTeamConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update a team."""
        params = {}
        if config.name is not None:
            params["name"] = config.name
        if config.description is not None:
            params["description"] = config.description
        if config.privacy is not None:
            params["privacy"] = config.privacy
        return await self._make_request(
            "PATCH",
            f"/orgs/{config.org}/teams/{config.team_slug}",
            credentials,
            action_name="update_team",
        )

    async def _delete_team(
        self, config: GithubDeleteTeamConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a team."""
        return await self._make_request(
            "DELETE",
            f"/orgs/{config.org}/teams/{config.team_slug}",
            credentials,
            action_name="delete_team",
        )

    async def _list_team_repositories(
        self,
        config: GithubListTeamRepositoriesConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List team repositories."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/teams/{config.team_slug}/repos",
            credentials,
            action_name="list_team_repos",
        )

    async def _check_team_permissions_for_repository(
        self,
        config: GithubCheckTeamPermissionsForRepositoryConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Check team permissions for a repository."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/teams/{config.team_slug}/repos/{config.owner}/{config.repo}",
            credentials,
            action_name="check_team_repo_permissions",
        )

    async def _add_or_update_team_repository_permissions(
        self,
        config: GithubAddOrUpdateTeamRepositoryPermissionsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Add or update team repository permissions."""
        params = {}
        if config.permission is not None:
            params["permission"] = config.permission
        return await self._make_request(
            "PUT",
            f"/orgs/{config.org}/teams/{config.team_slug}/repos/{config.owner}/{config.repo}",
            credentials,
            action_name="add_or_update_team_repo_permissions",
        )

    async def _remove_team_repository(
        self,
        config: GithubRemoveTeamRepositoryConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Remove a repository from a team."""
        return await self._make_request(
            "DELETE",
            f"/orgs/{config.org}/teams/{config.team_slug}/repos/{config.owner}/{config.repo}",
            credentials,
            action_name="remove_repo_from_team",
        )

    async def _list_team_members(
        self, config: GithubListTeamMembersConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List team members."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/teams/{config.team_slug}/members",
            credentials,
            action_name="list_team_members",
        )

    async def _get_team_membership(
        self, config: GithubGetTeamMembershipConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get team membership for a user."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/teams/{config.team_slug}/memberships/{config.username}",
            credentials,
            action_name="get_team_membership",
        )

    async def _get_organization(
        self, config: GithubGetOrganizationConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get an organization."""
        params = {}
        return await self._make_request(
            "GET", f"/orgs/{config.org}", credentials, action_name="get_organization"
        )

    async def _update_organization(
        self, config: GithubUpdateOrganizationConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Update an organization."""
        params = {}
        if config.billing_email is not None:
            params["billing_email"] = config.billing_email
        if config.company is not None:
            params["company"] = config.company
        if config.email is not None:
            params["email"] = config.email
        if config.location is not None:
            params["location"] = config.location
        if config.name is not None:
            params["name"] = config.name
        if config.description is not None:
            params["description"] = config.description
        return await self._make_request(
            "PATCH",
            f"/orgs/{config.org}",
            credentials,
            action_name="update_organization",
        )

    async def _list_organization_repositories(
        self,
        config: GithubListOrganizationRepositoriesConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List organization repositories (alias)."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/repos",
            credentials,
            action_name="list_org_repos_alias",
        )

    async def _create_organization_repository(
        self,
        config: GithubCreateOrganizationRepositoryConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Create an organization repository."""
        params = {}
        if config.description is not None:
            params["description"] = config.description
        if config.homepage is not None:
            params["homepage"] = config.homepage
        if config.private is not None:
            params["private"] = config.private
        if config.has_issues is not None:
            params["has_issues"] = config.has_issues
        if config.has_projects is not None:
            params["has_projects"] = config.has_projects
        if config.has_wiki is not None:
            params["has_wiki"] = config.has_wiki
        body = {}
        body["name"] = config.name
        return await self._make_request(
            "POST",
            f"/orgs/{config.org}/repos",
            credentials,
            json_body=body,
            action_name="create_org_repository",
        )

    async def _list_organization_invitations(
        self,
        config: GithubListOrganizationInvitationsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List organization invitations."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/invitations",
            credentials,
            action_name="list_org_invitations",
        )

    async def _cancel_organization_invitation(
        self,
        config: GithubCancelOrganizationInvitationConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Cancel an organization invitation."""
        return await self._make_request(
            "DELETE",
            f"/orgs/{config.org}/invitations/{config.invitation_id}",
            credentials,
            action_name="cancel_org_invitation",
        )

    async def _list_organization_members(
        self,
        config: GithubListOrganizationMembersConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List organization members (alias)."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/members",
            credentials,
            action_name="list_org_members_alias",
        )

    async def _check_organization_membership(
        self,
        config: GithubCheckOrganizationMembershipConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Check organization membership."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/members/{config.username}",
            credentials,
            action_name="check_org_membership",
        )

    async def _remove_organization_member(
        self,
        config: GithubRemoveOrganizationMemberConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Remove an organization member."""
        return await self._make_request(
            "DELETE",
            f"/orgs/{config.org}/members/{config.username}",
            credentials,
            action_name="remove_org_member",
        )

    async def _get_organization_membership(
        self,
        config: GithubGetOrganizationMembershipConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Get organization membership for a user."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/memberships/{config.username}",
            credentials,
            action_name="get_org_membership",
        )

    async def _add_or_update_organization_membership(
        self,
        config: GithubAddOrUpdateOrganizationMembershipConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Add or update organization membership."""
        params = {}
        if config.role is not None:
            params["role"] = config.role
        return await self._make_request(
            "PUT",
            f"/orgs/{config.org}/memberships/{config.username}",
            credentials,
            action_name="add_or_update_org_membership",
        )

    async def _remove_organization_membership(
        self,
        config: GithubRemoveOrganizationMembershipConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Remove organization membership."""
        return await self._make_request(
            "DELETE",
            f"/orgs/{config.org}/memberships/{config.username}",
            credentials,
            action_name="remove_org_membership",
        )

    async def _list_pending_organization_invitations(
        self,
        config: GithubListPendingOrganizationInvitationsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List pending organization invitations (alias)."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/invitations",
            credentials,
            action_name="list_pending_org_invitations",
        )

    async def _list_organization_webhooks(
        self,
        config: GithubListOrganizationWebhooksConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List organization webhooks."""
        params = {}
        return await self._make_request(
            "GET",
            f"/orgs/{config.org}/hooks",
            credentials,
            action_name="list_org_webhooks",
        )

    async def _create_organization_webhook(
        self,
        config: GithubCreateOrganizationWebhookConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Create an organization webhook."""
        params = {}
        if config.events is not None:
            params["events"] = config.events
        if config.active is not None:
            params["active"] = config.active
        body = {}
        body["name"] = config.name
        return await self._make_request(
            "POST",
            f"/orgs/{config.org}/hooks",
            credentials,
            json_body=body,
            action_name="create_org_webhook",
        )

    async def _list_deployment_statuses(
        self,
        config: GithubListDeploymentStatusesConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List deployment statuses."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/deployments/{config.deployment_id}/statuses",
            credentials,
            action_name="list_deployment_statuses",
        )

    async def _create_deployment_status(
        self,
        config: GithubCreateDeploymentStatusConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Create a deployment status."""
        params = {}
        if config.target_url is not None:
            params["target_url"] = config.target_url
        if config.log_url is not None:
            params["log_url"] = config.log_url
        if config.description is not None:
            params["description"] = config.description
        if config.environment is not None:
            params["environment"] = config.environment
        body = {}
        body["state"] = config.state
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/deployments/{config.deployment_id}/statuses",
            credentials,
            json_body=body,
            action_name="create_deployment_status",
        )

    async def _get_deployment_status(
        self, config: GithubGetDeploymentStatusConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a deployment status."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/deployments/{config.deployment_id}/statuses/{config.status_id}",
            credentials,
            action_name="get_deployment_status",
        )

    async def _get_deployment(
        self, config: GithubGetDeploymentConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get a deployment."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/deployments/{config.deployment_id}",
            credentials,
            action_name="get_deployment",
        )

    async def _delete_deployment(
        self, config: GithubDeleteDeploymentConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a deployment."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/deployments/{config.deployment_id}",
            credentials,
            action_name="delete_deployment",
        )

    async def _list_issue_reactions(
        self, config: GithubListIssueReactionsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List reactions for an issue."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/reactions",
            credentials,
            action_name="list_issue_reactions",
        )

    async def _delete_issue_reaction(
        self, config: GithubDeleteIssueReactionConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete an issue reaction."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/issues/{config.issue_number}/reactions/{config.reaction_id}",
            credentials,
            action_name="delete_issue_reaction",
        )

    async def _list_issue_comment_reactions(
        self,
        config: GithubListIssueCommentReactionsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List reactions for an issue comment."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/issues/comments/{config.comment_id}/reactions",
            credentials,
            action_name="list_issue_comment_reactions",
        )

    async def _create_issue_comment_reaction(
        self,
        config: GithubCreateIssueCommentReactionConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Create a reaction for an issue comment."""
        body = {}
        body["content"] = config.content
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/issues/comments/{config.comment_id}/reactions",
            credentials,
            json_body=body,
            action_name="create_reaction_on_issue_comment",
        )

    async def _delete_issue_comment_reaction(
        self,
        config: GithubDeleteIssueCommentReactionConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Delete an issue comment reaction."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/issues/comments/{config.comment_id}/reactions/{config.reaction_id}",
            credentials,
            action_name="delete_issue_comment_reaction",
        )

    async def _list_commit_comment_reactions(
        self,
        config: GithubListCommitCommentReactionsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List reactions for a commit comment."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/comments/{config.comment_id}/reactions",
            credentials,
            action_name="list_commit_comment_reactions",
        )

    async def _create_commit_comment_reaction(
        self,
        config: GithubCreateCommitCommentReactionConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Create a reaction for a commit comment."""
        body = {}
        body["content"] = config.content
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/comments/{config.comment_id}/reactions",
            credentials,
            json_body=body,
            action_name="create_reaction_on_commit_comment",
        )

    async def _delete_commit_comment_reaction(
        self,
        config: GithubDeleteCommitCommentReactionConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Delete a commit comment reaction."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/comments/{config.comment_id}/reactions/{config.reaction_id}",
            credentials,
            action_name="delete_commit_comment_reaction",
        )

    async def _list_pull_request_review_comment_reactions(
        self,
        config: GithubListPullRequestReviewCommentReactionsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List reactions for a PR review comment."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/pulls/comments/{config.comment_id}/reactions",
            credentials,
            action_name="list_pr_review_comment_reactions",
        )

    async def _create_pull_request_review_comment_reaction(
        self,
        config: GithubCreatePullRequestReviewCommentReactionConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Create a reaction for a PR review comment."""
        body = {}
        body["content"] = config.content
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/pulls/comments/{config.comment_id}/reactions",
            credentials,
            json_body=body,
            action_name="create_reaction_on_pr_review_comment",
        )

    async def _delete_pull_request_review_comment_reaction(
        self,
        config: GithubDeletePullRequestReviewCommentReactionConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Delete a PR review comment reaction."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/pulls/comments/{config.comment_id}/reactions/{config.reaction_id}",
            credentials,
            action_name="delete_pr_review_comment_reaction",
        )

    async def _list_release_reactions(
        self,
        config: GithubListReleaseReactionsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List reactions for a release."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/releases/{config.release_id}/reactions",
            credentials,
            action_name="list_release_reactions",
        )

    async def _create_release_reaction(
        self,
        config: GithubCreateReleaseReactionConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Create a reaction for a release."""
        body = {}
        body["content"] = config.content
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/releases/{config.release_id}/reactions",
            credentials,
            json_body=body,
            action_name="create_reaction_on_release",
        )

    async def _delete_release_reaction(
        self,
        config: GithubDeleteReleaseReactionConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Delete a release reaction."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/releases/{config.release_id}/reactions/{config.reaction_id}",
            credentials,
            action_name="delete_release_reaction",
        )

    async def _list_workflow_run_artifacts(
        self,
        config: GithubListWorkflowRunArtifactsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List workflow run artifacts."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/artifacts",
            credentials,
            action_name="list_workflow_run_artifacts",
        )

    async def _list_repository_artifacts(
        self,
        config: GithubListRepositoryArtifactsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List repository artifacts."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/artifacts",
            credentials,
            action_name="list_repo_artifacts",
        )

    async def _get_artifact(
        self, config: GithubGetArtifactConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get an artifact."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/artifacts/{config.artifact_id}",
            credentials,
            action_name="get_artifact",
        )

    async def _delete_artifact(
        self, config: GithubDeleteArtifactConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete an artifact."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/actions/artifacts/{config.artifact_id}",
            credentials,
            action_name="delete_artifact",
        )

    async def _download_artifact(
        self, config: GithubDownloadArtifactConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Download an artifact."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/artifacts/{config.artifact_id}/{config.archive_format}",
            credentials,
            action_name="download_artifact",
        )

    async def _delete_workflow_run(
        self, config: GithubDeleteWorkflowRunConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Delete a workflow run."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}",
            credentials,
            action_name="delete_workflow_run",
        )

    async def _get_workflow_run_usage(
        self, config: GithubGetWorkflowRunUsageConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Get workflow run usage."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/usage",
            credentials,
            action_name="get_workflow_run_usage",
        )

    async def _download_workflow_run_logs(
        self,
        config: GithubDownloadWorkflowRunLogsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Download workflow run logs."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/logs",
            credentials,
            action_name="download_workflow_run_logs",
        )

    async def _delete_workflow_run_logs(
        self,
        config: GithubDeleteWorkflowRunLogsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Delete workflow run logs."""
        return await self._make_request(
            "DELETE",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/logs",
            credentials,
            action_name="delete_workflow_run_logs",
        )

    async def _list_workflow_run_jobs(
        self, config: GithubListWorkflowRunJobsConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """List jobs for a workflow run."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/jobs",
            credentials,
            action_name="list_workflow_run_jobs",
        )

    async def _get_workflow_run_attempt(
        self,
        config: GithubGetWorkflowRunAttemptConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Get a workflow run attempt."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/attempts/{config.attempt_number}",
            credentials,
            action_name="get_workflow_run_attempt",
        )

    async def _list_jobs_for_workflow_run_attempt(
        self,
        config: GithubListJobsForWorkflowRunAttemptConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List jobs for a workflow run attempt."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/attempts/{config.attempt_number}/jobs",
            credentials,
            action_name="list_workflow_run_attempt_jobs",
        )

    async def _download_workflow_run_attempt_logs(
        self,
        config: GithubDownloadWorkflowRunAttemptLogsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """Download logs for a workflow run attempt."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/attempts/{config.attempt_number}/logs",
            credentials,
            action_name="download_workflow_run_attempt_logs",
        )

    async def _approve_workflow_run(
        self, config: GithubApproveWorkflowRunConfig, credentials: GithubRestCredential
    ) -> Dict[str, Any]:
        """Approve a workflow run."""
        return await self._make_request(
            "POST",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/approve",
            credentials,
            action_name="approve_workflow_run",
        )

    async def _list_workflow_run_pending_deployments(
        self,
        config: GithubListWorkflowRunPendingDeploymentsConfig,
        credentials: GithubRestCredential,
    ) -> Dict[str, Any]:
        """List pending deployments for a workflow run."""
        params = {}
        return await self._make_request(
            "GET",
            f"/repos/{config.owner}/{config.repo}/actions/runs/{config.run_id}/pending_deployments",
            credentials,
            action_name="list_workflow_run_pending_deployments",
        )
