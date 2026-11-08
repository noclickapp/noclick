"""Gitea v1 API with a supplied personal access token and public HTTPS instance.

Each operation sends exactly one published API request. Writes return the API's
acknowledgement, with no automatic retry or implicit follow-up mutation.
Contract: https://docs.gitea.com/api/1.20/
Authentication: https://docs.gitea.com/development/api-usage/
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client, normalize_https_origin


def _segment(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}", value):
        raise ValueError("Enter one Gitea owner or repository name without slashes")
    return value


class GiteaTokenCredential(BaseModel):
    model_config = ConfigDict(title="Gitea Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.gitea.com/development/api-usage/",
            "x-credential-instructions": "In your Gitea instance, open Settings → Applications → Manage Access Tokens. Paste an existing token and the public HTTPS instance origin. Use read:user for connection verification, read:repository and read:issue for reads, and write:repository and write:issue for writes you use. Tokens are sent as Authorization: token, never in URLs. Instances hosted under a URL subpath are not supported."})
    credential_type: Literal["gitea_token"] = Field("gitea_token", json_schema_extra={"ui:hidden": True})
    instance_url: str = Field(..., title="Gitea Instance URL", description="Public HTTPS origin, for example https://gitea.example.com. No API path, query or fragment.")
    access_token: str = Field(..., repr=False, title="Personal Access Token", json_schema_extra={"ui:widget": "password"})

    @field_validator("instance_url", mode="before")
    @classmethod
    def origin(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter your Gitea HTTPS instance origin")
        try:
            return normalize_https_origin(value, field_name="Gitea instance")
        except SSRFError:
            raise ValueError("Enter an HTTPS origin without a path, userinfo, query or fragment") from None

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if len(value) > 4096 or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the personal access token without a header prefix")
        return value


def _operation(name, title, category):
    return Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": title,
        "x-category": category, "x-is-trigger": False})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, le=2147483647, title="Page", description="One API page per execution; use next_page to continue.")
    limit: int = Field(50, ge=1, le=100, title="Items per Page", description="The instance may apply a lower server-side maximum.")


class _Repository(_Input):
    owner: str = Field(..., title="Repository Owner")
    repo: str = Field(..., title="Repository Name")
    _names = field_validator("owner", "repo", mode="before")(_segment)


class _RepositoryPage(_Repository, _Page):
    pass


class _Issue(_Repository):
    index: int = Field(..., ge=1, le=9223372036854775807, title="Issue or Pull Request Number")


class _IssueFields(_Input):
    body: str | None = Field(None, max_length=100000, title="Markdown Body")
    assignees: list[str] | None = Field(None, max_length=100, title="Assignee Usernames", description="Use an empty list to clear assignees when updating.")
    milestone: int | None = Field(None, ge=0, le=9223372036854775807, title="Milestone ID")


class _ReleaseFields(_Input):
    name: str | None = Field(None, max_length=1000, title="Release Title")
    body: str | None = Field(None, max_length=100000, title="Release Notes")
    target_commitish: str | None = Field(None, min_length=1, max_length=255, title="Target Branch or Commit")
    draft: bool | None = Field(None, title="Draft")
    prerelease: bool | None = Field(None, title="Prerelease")


class _Release(_Repository):
    release_id: int = Field(..., ge=1, le=9223372036854775807, title="Release ID")


class GiteaCurrentUserConfig(_Input):
    operation: Literal["get_current_user"] = _operation("get_current_user", "Get Current User", "Account")


class GiteaListRepositoriesConfig(_Page):
    operation: Literal["list_repositories"] = _operation("list_repositories", "List My Repositories", "Repositories")


class GiteaGetRepositoryConfig(_Repository):
    operation: Literal["get_repository"] = _operation("get_repository", "Get Repository", "Repositories")


class GiteaCreateRepositoryConfig(_Input):
    operation: Literal["create_repository"] = _operation("create_repository", "Create Repository", "Repositories")
    name: str = Field(..., min_length=1, max_length=255, title="Repository Name")
    description: str | None = Field(None, max_length=10000)
    private: bool = Field(True, title="Private Repository")
    auto_init: bool = Field(False, title="Initialize Repository")
    default_branch: str | None = Field(None, min_length=1, max_length=255)
    _name = field_validator("name", mode="before")(_segment)


class GiteaListIssuesConfig(_RepositoryPage):
    operation: Literal["list_issues"] = _operation("list_issues", "List Issues", "Issues")
    state: Literal["open", "closed", "all"] = "open"
    q: str | None = Field(None, max_length=1000, title="Search Text")
    labels: str | None = Field(None, max_length=1000, title="Label Names", description="Comma-separated label names.")


class GiteaGetIssueConfig(_Issue):
    operation: Literal["get_issue"] = _operation("get_issue", "Get Issue", "Issues")


class GiteaCreateIssueConfig(_Repository, _IssueFields):
    operation: Literal["create_issue"] = _operation("create_issue", "Create Issue", "Issues")
    title: str = Field(..., min_length=1, max_length=1000)
    labels: list[int] | None = Field(None, max_length=100, title="Label IDs")


class GiteaUpdateIssueConfig(_Issue, _IssueFields):
    operation: Literal["update_issue"] = _operation("update_issue", "Update Issue", "Issues")
    title: str | None = Field(None, min_length=1, max_length=1000)
    state: Literal["open", "closed"] | None = None


class GiteaListIssueCommentsConfig(_Issue):
    operation: Literal["list_issue_comments"] = _operation("list_issue_comments", "List Issue Comments", "Issues")


class GiteaCreateIssueCommentConfig(_Issue):
    operation: Literal["create_issue_comment"] = _operation("create_issue_comment", "Create Issue Comment", "Issues")
    body: str = Field(..., min_length=1, max_length=100000, title="Markdown Comment")


class GiteaListPullRequestsConfig(_RepositoryPage):
    operation: Literal["list_pull_requests"] = _operation("list_pull_requests", "List Pull Requests", "Pull Requests")
    state: Literal["open", "closed", "all"] = "open"


class GiteaGetPullRequestConfig(_Issue):
    operation: Literal["get_pull_request"] = _operation("get_pull_request", "Get Pull Request", "Pull Requests")


class GiteaCreatePullRequestConfig(_Repository, _IssueFields):
    operation: Literal["create_pull_request"] = _operation("create_pull_request", "Create Pull Request", "Pull Requests")
    title: str = Field(..., min_length=1, max_length=1000)
    head: str = Field(..., min_length=1, max_length=255, title="Source Branch", description="Branch or username:branch for a fork.")
    base: str = Field(..., min_length=1, max_length=255, title="Target Branch")
    labels: list[int] | None = Field(None, max_length=100, title="Label IDs")


class GiteaUpdatePullRequestConfig(_Issue, _IssueFields):
    operation: Literal["update_pull_request"] = _operation("update_pull_request", "Update Pull Request", "Pull Requests")
    title: str | None = Field(None, min_length=1, max_length=1000)
    state: Literal["open", "closed"] | None = None
    base: str | None = Field(None, min_length=1, max_length=255, title="Target Branch")


class GiteaListBranchesConfig(_RepositoryPage):
    operation: Literal["list_branches"] = _operation("list_branches", "List Branches", "Branches")


class GiteaCreateBranchConfig(_Repository):
    operation: Literal["create_branch"] = _operation("create_branch", "Create Branch", "Branches")
    new_branch_name: str = Field(..., min_length=1, max_length=255, title="New Branch Name")
    old_branch_name: str | None = Field(None, min_length=1, max_length=255, title="Source Branch", description="Omit to use the repository default branch.")


class GiteaListReleasesConfig(_RepositoryPage):
    operation: Literal["list_releases"] = _operation("list_releases", "List Releases", "Releases")


class GiteaGetReleaseConfig(_Release):
    operation: Literal["get_release"] = _operation("get_release", "Get Release", "Releases")


class GiteaCreateReleaseConfig(_Repository, _ReleaseFields):
    operation: Literal["create_release"] = _operation("create_release", "Create Release", "Releases")
    tag_name: str = Field(..., min_length=1, max_length=255)
    draft: bool = Field(True, title="Draft", description="Set to false to publish this release.")
    prerelease: bool = False


class GiteaUpdateReleaseConfig(_Release, _ReleaseFields):
    operation: Literal["update_release"] = _operation("update_release", "Update Release", "Releases")
    tag_name: str | None = Field(None, min_length=1, max_length=255)


class GiteaListLabelsConfig(_RepositoryPage):
    operation: Literal["list_labels"] = _operation("list_labels", "List Repository Labels", "Issues")


GiteaOperation = Annotated[Union[
    GiteaCurrentUserConfig,
    GiteaListRepositoriesConfig,
    GiteaGetRepositoryConfig,
    GiteaCreateRepositoryConfig,
    GiteaListIssuesConfig,
    GiteaGetIssueConfig,
    GiteaCreateIssueConfig,
    GiteaUpdateIssueConfig,
    GiteaListIssueCommentsConfig,
    GiteaCreateIssueCommentConfig,
    GiteaListPullRequestsConfig,
    GiteaGetPullRequestConfig,
    GiteaCreatePullRequestConfig,
    GiteaUpdatePullRequestConfig,
    GiteaListBranchesConfig,
    GiteaCreateBranchConfig,
    GiteaListReleasesConfig,
    GiteaGetReleaseConfig,
    GiteaCreateReleaseConfig,
    GiteaUpdateReleaseConfig,
    GiteaListLabelsConfig], Field(discriminator="operation")]


class GiteaNodeConfig(NodeConfig[GiteaOperation, GiteaTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# One published operation per config; no arbitrary URL or method escape hatch.
ROUTES = {
    'get_current_user': ('GET', '/user', (), (), False),
    'list_repositories': ('GET', '/user/repos', ('page', 'limit'), (), True),
    'get_repository': ('GET', '/repos/{owner}/{repo}', (), (), False),
    'create_repository': ('POST', '/user/repos', (), ('name', 'description', 'private', 'auto_init', 'default_branch'), False),
    'list_issues': ('GET', '/repos/{owner}/{repo}/issues', ('page', 'limit', 'state', 'q', 'labels'), (), True),
    'get_issue': ('GET', '/repos/{owner}/{repo}/issues/{index}', (), (), False),
    'create_issue': ('POST', '/repos/{owner}/{repo}/issues', (), ('title', 'body', 'assignees', 'milestone', 'labels'), False),
    'update_issue': ('PATCH', '/repos/{owner}/{repo}/issues/{index}', (), ('title', 'body', 'assignees', 'milestone', 'state'), False),
    'list_issue_comments': ('GET', '/repos/{owner}/{repo}/issues/{index}/comments', (), (), True),
    'create_issue_comment': ('POST', '/repos/{owner}/{repo}/issues/{index}/comments', (), ('body',), False),
    'list_pull_requests': ('GET', '/repos/{owner}/{repo}/pulls', ('page', 'limit', 'state'), (), True),
    'get_pull_request': ('GET', '/repos/{owner}/{repo}/pulls/{index}', (), (), False),
    'create_pull_request': ('POST', '/repos/{owner}/{repo}/pulls', (), ('title', 'head', 'base', 'body', 'assignees', 'milestone', 'labels'), False),
    'update_pull_request': ('PATCH', '/repos/{owner}/{repo}/pulls/{index}', (), ('title', 'body', 'assignees', 'milestone', 'state', 'base'), False),
    'list_branches': ('GET', '/repos/{owner}/{repo}/branches', ('page', 'limit'), (), True),
    'create_branch': ('POST', '/repos/{owner}/{repo}/branches', (), ('new_branch_name', 'old_branch_name'), False),
    'list_releases': ('GET', '/repos/{owner}/{repo}/releases', ('page', 'limit'), (), True),
    'get_release': ('GET', '/repos/{owner}/{repo}/releases/{release_id}', (), (), False),
    'create_release': ('POST', '/repos/{owner}/{repo}/releases', (), ('tag_name', 'name', 'body', 'draft', 'prerelease', 'target_commitish'), False),
    'update_release': ('PATCH', '/repos/{owner}/{repo}/releases/{release_id}', (), ('tag_name', 'name', 'body', 'draft', 'prerelease', 'target_commitish'), False),
    'list_labels': ('GET', '/repos/{owner}/{repo}/labels', ('page', 'limit'), (), True),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class GiteaNode(WorkflowNode):
    integration_type = "automation-gitea"
    connection_evidence = ConnectionEvidence(operation="get_current_user", identity_operation="get_current_user",
        noun="Gitea account", label_keys=("login", "full_name"), identity_keys=("login", "full_name", "id"), proves="account")
    edit_examples = ["Create a Gitea issue and comment on it", "List open Gitea pull requests", "Create a draft Gitea release"]

    @classmethod
    def get_config_model(cls):
        return GiteaNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", "gitea_token") != "gitea_token":
            raise ValueError("Select a Gitea personal access token credential")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a Gitea personal access token")
        method, route, query_fields, body_fields, is_list = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = route.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params = {key: values[key] for key in query_fields if key in values}
        if config.operation == "list_issues":
            params["type"] = "issues"
        body = {key: values[key] for key in body_fields if key in values}
        if method == "PATCH" and not body:
            raise ValueError("Supply at least one field to update")
        result = {"action": config.operation}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, credential.instance_url + "/api/v1" + path,
                    headers={"Authorization": "token " + credential.access_token, "Accept": "application/json"},
                    params=params, **({"json": body} if body_fields else {}))
            result["http_status"] = response.status_code
            expected_status = 201 if method == "POST" or config.operation in {"update_issue", "update_pull_request"} else 200
            if response.status_code != expected_status:
                message = "Gitea rejected the request"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = _redact(error["message"], credential.access_token)[:1000]
                except ValueError:
                    pass
                return {**result, "status": "error", "error": message}
            if len(response.content) > 8 * 1024 * 1024 or "application/json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected a bounded JSON response from Gitea")
            data = response.json()
            if not isinstance(data, list if is_list else dict) or (isinstance(data, dict) and ("error" in data or "errors" in data)):
                raise ValueError("Unexpected Gitea response shape")
            if is_list and any(not isinstance(row, dict) for row in data):
                raise ValueError("Expected Gitea resource objects")
            result.update(status="success", data=_redact(data, credential.access_token))
            if "page" in query_fields:
                # Never follow an arbitrary provider-supplied next URL.
                has_more = bool(re.search(r';\s*rel=["\']?next(?:["\']|[,;]|$)', response.headers.get("link", "")))
                result.update(page=config.page, has_more=has_more, next_page=config.page + 1 if has_more else None)
            return result
        except (httpx.HTTPError, SSRFError):
            return {**result, "status": "error", "error": "Gitea transport failed; outcome may be unknown. No automatic retry was made."}
        except (ValueError, TypeError):
            return {**result, "status": "error", "error": "Gitea returned an invalid JSON response; outcome may be unknown."}
