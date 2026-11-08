"""Codacy Cloud API v3 operations, using a pasted account API token.

Contract: https://api.codacy.com/api/api-docs/swagger.yaml (version 3.1.0).
Each operation makes exactly one request. Pagination is explicit; writes are
acknowledged by HTTP status, without claiming analysis completion or delivery.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.codacy.com/api/v3"


class CodacyAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Codacy API Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.codacy.com/codacy-api/api-tokens/#account-api-tokens",
            "x-credential-instructions": "In Codacy, open your account → Access management and click Create API token under Account API tokens. Paste it here. NoClick sends it in the api-token header to api.codacy.com. Repository tokens do not support all these operations. Access follows your Codacy account permissions.",
        },
    )
    credential_type: Literal["codacy_api_token"] = Field(
        "codacy_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API token",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def clean_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API token, without a header")
        return value


class CodacyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def reject_dot_segments(cls, value, info):
        if info.field_name in {
            "provider",
            "organization",
            "repository",
            "commit_uuid",
            "issue_id",
        } and value in {".", ".."}:
            raise ValueError("Use a resource name or identifier")
        return value


class CodacyGetUserConfig(CodacyInput):
    """Get the authenticated user"""

    operation: Literal["get_user"] = Field(
        "get_user", json_schema_extra={"ui:hidden": True}
    )


class CodacyListOrganizationsConfig(CodacyInput):
    """List organizations for the authenticated user"""

    operation: Literal["list_organizations"] = Field(
        "list_organizations", json_schema_extra={"ui:hidden": True}
    )
    cursor: str | None = Field(None, max_length=4096)
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="One page only; pass the returned pagination cursor to continue.",
    )


class CodacyListRepositoriesConfig(CodacyInput):
    """List organization repositories for the authenticated user"""

    operation: Literal["list_repositories"] = Field(
        "list_repositories", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    cursor: str | None = Field(None, max_length=4096)
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="One page only; pass the returned pagination cursor to continue.",
    )
    search: str | None = Field(None, max_length=4096)


class CodacyGetRepositoryConfig(CodacyInput):
    """Fetch the specified repository"""

    operation: Literal["get_repository"] = Field(
        "get_repository", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )


class CodacyListBranchesConfig(CodacyInput):
    """List repository branches"""

    operation: Literal["list_branches"] = Field(
        "list_branches", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    cursor: str | None = Field(None, max_length=4096)
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="One page only; pass the returned pagination cursor to continue.",
    )
    search: str | None = Field(None, max_length=4096)


class CodacyListRepositoryAnalysisConfig(CodacyInput):
    """List organization repositories with analysis information for the authenticated user"""

    operation: Literal["list_repository_analysis"] = Field(
        "list_repository_analysis", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    cursor: str | None = Field(None, max_length=4096)
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="One page only; pass the returned pagination cursor to continue.",
    )
    search: str | None = Field(None, max_length=4096)


class CodacyGetRepositoryAnalysisConfig(CodacyInput):
    """Get a repository with analysis information for the authenticated user"""

    operation: Literal["get_repository_analysis"] = Field(
        "get_repository_analysis", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    branch: str | None = Field(None, max_length=4096)


class CodacyListPullRequestsConfig(CodacyInput):
    """List pull requests from a repository that the user has access to"""

    operation: Literal["list_pull_requests"] = Field(
        "list_pull_requests", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="One page only; pass the returned pagination cursor to continue.",
    )
    cursor: str | None = Field(None, max_length=4096)
    search: str | None = Field(None, max_length=4096)


class CodacyGetPullRequestConfig(CodacyInput):
    """Get pull request from a repository"""

    operation: Literal["get_pull_request"] = Field(
        "get_pull_request", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    pull_request_number: int = Field(..., ge=1, le=2147483647)


class CodacyGetPullRequestCoverageConfig(CodacyInput):
    """Get pull request coverage information from a repository"""

    operation: Literal["get_pull_request_coverage"] = Field(
        "get_pull_request_coverage", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    pull_request_number: int = Field(..., ge=1, le=2147483647)


class CodacyListFilesConfig(CodacyInput):
    """List files in a repository"""

    operation: Literal["list_files"] = Field(
        "list_files", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    branch: str | None = Field(None, max_length=4096)
    path: str | None = Field(None, max_length=4096)
    search: str | None = Field(None, max_length=4096)
    cursor: str | None = Field(None, max_length=4096)
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="One page only; pass the returned pagination cursor to continue.",
    )


class CodacyListIgnoredFilesConfig(CodacyInput):
    """List ignored files in a repository"""

    operation: Literal["list_ignored_files"] = Field(
        "list_ignored_files", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    branch: str | None = Field(None, max_length=4096)
    search: str | None = Field(None, max_length=4096)
    cursor: str | None = Field(None, max_length=4096)
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="One page only; pass the returned pagination cursor to continue.",
    )


class CodacyFollowRepositoryConfig(CodacyInput):
    """Follow a repository that was already added to Codacy"""

    operation: Literal["follow_repository"] = Field(
        "follow_repository", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )


class CodacyUnfollowRepositoryConfig(CodacyInput):
    """Unfollow a repository"""

    operation: Literal["unfollow_repository"] = Field(
        "unfollow_repository", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )


class CodacyReanalyzeCommitConfig(CodacyInput):
    """Reanalyze a specific commit in a repository"""

    operation: Literal["reanalyze_commit"] = Field(
        "reanalyze_commit", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    commit_uuid: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Commit SHA or UUID to queue for analysis.",
    )
    clean_cache: bool = False


class CodacyUpdateFileStateConfig(CodacyInput):
    """Ignore or unignore a file"""

    operation: Literal["update_file_state"] = Field(
        "update_file_state", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    filepath: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Relative file path in the repository.",
    )
    ignored: bool


class CodacyListCommitsConfig(CodacyInput):
    """Return analysis results for the commits in a branch"""

    operation: Literal["list_commits"] = Field(
        "list_commits", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    branch: str | None = Field(None, max_length=4096)
    cursor: str | None = Field(None, max_length=4096)
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="One page only; pass the returned pagination cursor to continue.",
    )


class CodacyGetCommitConfig(CodacyInput):
    """Get analysis results for a commit"""

    operation: Literal["get_commit"] = Field(
        "get_commit", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    commit_uuid: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="UUID or SHA string that identifies the commit",
    )


class CodacyGetIssueConfig(CodacyInput):
    """Get information about an open issue in a repository"""

    operation: Literal["get_issue"] = Field(
        "get_issue", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    issue_id: int = Field(..., ge=1, le=2147483647)


class CodacyUpdateIssueStateConfig(CodacyInput):
    """Ignore or unignore an issue"""

    operation: Literal["update_issue_state"] = Field(
        "update_issue_state", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    issue_id: str = Field(
        ..., min_length=1, max_length=500, description="Issue identifier"
    )
    ignored: bool
    reason: Literal[
        "AcceptedUse", "FalsePositive", "NotExploitable", "TestCode", "ExternalCode"
    ] | None = None
    comment: str | None = Field(None, max_length=10000)


class CodacyListPullRequestIssuesConfig(CodacyInput):
    """List issues found in a pull request"""

    operation: Literal["list_pull_request_issues"] = Field(
        "list_pull_request_issues", json_schema_extra={"ui:hidden": True}
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Git provider identifier (e.g., gh for GitHub, gl for GitLab, bb for Bitbucket)",
    )
    organization: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Organization name on the Git provider",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Repository name on the Git provider organization",
    )
    pull_request_number: int = Field(..., ge=1, le=2147483647)
    issue_status: Literal["all", "new", "fixed"] | None = None
    only_potential: bool | None = None
    cursor: str | None = Field(None, max_length=4096)
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="One page only; pass the returned pagination cursor to continue.",
    )


CodacyConfig = Annotated[
    Union[
        CodacyGetUserConfig,
        CodacyListOrganizationsConfig,
        CodacyListRepositoriesConfig,
        CodacyGetRepositoryConfig,
        CodacyListBranchesConfig,
        CodacyListRepositoryAnalysisConfig,
        CodacyGetRepositoryAnalysisConfig,
        CodacyListPullRequestsConfig,
        CodacyGetPullRequestConfig,
        CodacyGetPullRequestCoverageConfig,
        CodacyListFilesConfig,
        CodacyListIgnoredFilesConfig,
        CodacyFollowRepositoryConfig,
        CodacyUnfollowRepositoryConfig,
        CodacyReanalyzeCommitConfig,
        CodacyUpdateFileStateConfig,
        CodacyListCommitsConfig,
        CodacyGetCommitConfig,
        CodacyGetIssueConfig,
        CodacyUpdateIssueStateConfig,
        CodacyListPullRequestIssuesConfig,
    ],
    Field(discriminator="operation"),
]


class CodacyFullConfig(NodeConfig[CodacyConfig, CodacyAPITokenCredential]):
    pass


OPERATIONS = {
    "get_user": {
        "method": "GET",
        "path": "/user",
        "path_fields": {},
        "query_fields": {},
        "body_fields": {},
        "success": 200,
        "contract_operation": "getUser",
    },
    "list_organizations": {
        "method": "GET",
        "path": "/user/organizations",
        "path_fields": {},
        "query_fields": {"cursor": "cursor", "limit": "limit"},
        "body_fields": {},
        "success": 200,
        "contract_operation": "listUserOrganizations",
    },
    "list_repositories": {
        "method": "GET",
        "path": "/organizations/{provider}/{remoteOrganizationName}/repositories",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
        },
        "query_fields": {"cursor": "cursor", "limit": "limit", "search": "search"},
        "body_fields": {},
        "success": 200,
        "contract_operation": "listOrganizationRepositories",
    },
    "get_repository": {
        "method": "GET",
        "path": "/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {},
        "body_fields": {},
        "success": 200,
        "contract_operation": "getRepository",
    },
    "list_branches": {
        "method": "GET",
        "path": "/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/branches",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {"cursor": "cursor", "limit": "limit", "search": "search"},
        "body_fields": {},
        "success": 200,
        "contract_operation": "listRepositoryBranches",
    },
    "list_repository_analysis": {
        "method": "GET",
        "path": "/analysis/organizations/{provider}/{remoteOrganizationName}/repositories",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
        },
        "query_fields": {"cursor": "cursor", "limit": "limit", "search": "search"},
        "body_fields": {},
        "success": 200,
        "contract_operation": "listOrganizationRepositoriesWithAnalysis",
    },
    "get_repository_analysis": {
        "method": "GET",
        "path": "/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {"branch": "branch"},
        "body_fields": {},
        "success": 200,
        "contract_operation": "getRepositoryWithAnalysis",
    },
    "list_pull_requests": {
        "method": "GET",
        "path": "/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/pull-requests",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {"limit": "limit", "cursor": "cursor", "search": "search"},
        "body_fields": {},
        "success": 200,
        "contract_operation": "listRepositoryPullRequests",
    },
    "get_pull_request": {
        "method": "GET",
        "path": "/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/pull-requests/{pullRequestNumber}",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
            "pullRequestNumber": "pull_request_number",
        },
        "query_fields": {},
        "body_fields": {},
        "success": 200,
        "contract_operation": "getRepositoryPullRequest",
    },
    "get_pull_request_coverage": {
        "method": "GET",
        "path": "/coverage/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/pull-requests/{pullRequestNumber}",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
            "pullRequestNumber": "pull_request_number",
        },
        "query_fields": {},
        "body_fields": {},
        "success": 200,
        "contract_operation": "getRepositoryPullRequestCoverage",
    },
    "list_files": {
        "method": "GET",
        "path": "/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/files",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {
            "branch": "branch",
            "path": "path",
            "search": "search",
            "cursor": "cursor",
            "limit": "limit",
        },
        "body_fields": {},
        "success": 200,
        "contract_operation": "listFiles",
    },
    "list_ignored_files": {
        "method": "GET",
        "path": "/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/ignored-files",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {
            "branch": "branch",
            "search": "search",
            "cursor": "cursor",
            "limit": "limit",
        },
        "body_fields": {},
        "success": 200,
        "contract_operation": "listIgnoredFiles",
    },
    "follow_repository": {
        "method": "POST",
        "path": "/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/follow",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {},
        "body_fields": {},
        "success": 200,
        "contract_operation": "followAddedRepository",
    },
    "unfollow_repository": {
        "method": "DELETE",
        "path": "/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/follow",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {},
        "body_fields": {},
        "success": 204,
        "contract_operation": "unfollowRepository",
    },
    "reanalyze_commit": {
        "method": "POST",
        "path": "/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/reanalyzeCommit",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {},
        "body_fields": {"commitUuid": "commit_uuid", "cleanCache": "clean_cache"},
        "success": 204,
        "contract_operation": "reanalyzeCommitById",
    },
    "update_file_state": {
        "method": "PATCH",
        "path": "/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/file",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {},
        "body_fields": {"filepath": "filepath", "ignored": "ignored"},
        "success": 204,
        "contract_operation": "updateFileState",
    },
    "list_commits": {
        "method": "GET",
        "path": "/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/commits",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
        },
        "query_fields": {"branch": "branch", "cursor": "cursor", "limit": "limit"},
        "body_fields": {},
        "success": 200,
        "contract_operation": "listRepositoryCommits",
    },
    "get_commit": {
        "method": "GET",
        "path": "/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/commits/{commitUuid}",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
            "commitUuid": "commit_uuid",
        },
        "query_fields": {},
        "body_fields": {},
        "success": 200,
        "contract_operation": "getCommit",
    },
    "get_issue": {
        "method": "GET",
        "path": "/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/issues/{issueId}",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
            "issueId": "issue_id",
        },
        "query_fields": {},
        "body_fields": {},
        "success": 200,
        "contract_operation": "getIssue",
    },
    "update_issue_state": {
        "method": "PATCH",
        "path": "/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/issues/{issueId}",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
            "issueId": "issue_id",
        },
        "query_fields": {},
        "body_fields": {"ignored": "ignored", "reason": "reason", "comment": "comment"},
        "success": 204,
        "contract_operation": "updateIssueState",
    },
    "list_pull_request_issues": {
        "method": "GET",
        "path": "/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/pull-requests/{pullRequestNumber}/issues",
        "path_fields": {
            "provider": "provider",
            "remoteOrganizationName": "organization",
            "repositoryName": "repository",
            "pullRequestNumber": "pull_request_number",
        },
        "query_fields": {
            "status": "issue_status",
            "onlyPotential": "only_potential",
            "cursor": "cursor",
            "limit": "limit",
        },
        "body_fields": {},
        "success": 200,
        "contract_operation": "listPullRequestIssues",
    },
}


class CodacyNode(WorkflowNode):
    integration_type = "automation-codacy"
    connection_evidence = ConnectionEvidence(
        noun="Codacy organizations",
        operation="list_organizations",
        identity_operation="get_user",
    )

    @classmethod
    def get_config_model(cls):
        return CodacyFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Codacy account API token")
        spec = OPERATIONS[config.operation]
        path = spec["path"]
        for parameter, field in spec["path_fields"].items():
            path = path.replace(
                "{" + parameter + "}", quote(str(getattr(config, field)), safe="")
            )
        params = {
            key: getattr(config, field)
            for key, field in spec["query_fields"].items()
            if getattr(config, field) is not None
        }
        body = {
            key: getattr(config, field)
            for key, field in spec["body_fields"].items()
            if getattr(config, field) is not None
        }
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    spec["method"],
                    BASE_URL + path,
                    headers={
                        "api-token": credential.api_token,
                        "Accept": "application/json",
                    },
                    params=params,
                    **({"json": body} if spec["body_fields"] else {}),
                )
        except httpx.RequestError:
            # Do not expose a request object (which holds the token), or retry a write.
            return {
                "status": "error",
                "error": "Codacy request could not be completed; inspect writes before retrying",
            }
        if response.status_code != spec["success"]:
            detail = response.text[:2000].replace(credential.api_token, "[redacted]")
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": detail or "Codacy request was not accepted",
            }
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "acknowledged": True}
        try:
            data = response.json()
        except ValueError:
            return {
                "status": "error",
                "error": "Codacy returned an unexpected JSON response",
            }
        if not isinstance(data, dict) or "error" in data or "errors" in data:
            return {
                "status": "error",
                "error": "Codacy returned an unexpected response shape",
            }
        required = {
            "get_pull_request": ("isAnalysing", "meta", "pullRequest"),
            "get_commit": ("commit", "meta"),
            "list_ignored_files": ("data", "hasCodacyConfigurationFile"),
            "list_pull_request_issues": ("data", "analyzed"),
        }.get(config.operation, ("data",))
        if any(key not in data for key in required):
            return {
                "status": "error",
                "error": "Codacy response is missing expected fields",
            }
        if "data" in data:
            expected = (
                str
                if config.operation == "follow_repository"
                else (list if config.operation.startswith("list_") else dict)
            )
            if not isinstance(data["data"], expected):
                return {
                    "status": "error",
                    "error": "Codacy returned an unexpected data shape",
                }
        # Preserve the provider's documented response, including pagination,
        # without following any response URL or manufacturing resource fields.
        return {**data, "status": "success", "http_status": response.status_code}
