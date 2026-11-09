"""Jira Software Server/Data Center REST operations (11.2.1 contract).

Personal access tokens require Jira 8.14+. Instance context paths are retained;
requests use the shared SSRF guard and never follow redirects or retry writes.
Docs: https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


def _base_url(value):
    if not isinstance(value, str):
        raise ValueError("Paste your Jira instance URL, including its context path")
    value = value.strip().rstrip("/")
    if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("Use an instance URL without whitespace or control characters")
    try:
        p = urlsplit(value)
        if (
            p.scheme not in {"http", "https"}
            or not p.hostname
            or p.username is not None
            or p.password is not None
            or p.query
            or p.fragment
            or (p.port is not None and not 1 <= p.port <= 65535)
            or not re.fullmatch(r"[A-Za-z0-9.-]+", p.hostname)
            or "." not in p.hostname
            or p.hostname.endswith(".")
            or all(x.isdigit() for x in p.hostname.split("."))
            or any(
                not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", x)
                for x in p.hostname.split(".")
            )
            or not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", p.path)
            or p.path.endswith("/rest")
        ):
            raise ValueError()
    except ValueError:
        raise ValueError(
            "Use a public HTTP(S) Jira instance URL, optionally ending in /jira; omit /rest, credentials, query and fragment"
        ) from None
    return (
        p.scheme
        + "://"
        + p.hostname.lower()
        + (":" + str(p.port) if p.port else "")
        + p.path
    )


class JiraSoftwareServerTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Jira Software Server Personal Access Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html",
            "x-credential-instructions": "In Jira Server/Data Center 8.14 or later, open Profile > Personal access tokens and create a token. Paste it with your instance URL, including any context path such as /jira. The token uses your Jira permissions. Your instance must be publicly reachable; prefer HTTPS. Private network hosts and redirects are refused.",
        },
    )
    credential_type: Literal["jira_software_server_token"] = Field(
        "jira_software_server_token", json_schema_extra={"ui:hidden": True}
    )
    server_url: str = Field(
        ...,
        title="Jira Instance URL",
        description="Instance base URL, for example https://jira.example.com/jira. Omit /rest.",
    )
    api_token: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="Personal Access Token",
        description="Paste the token itself, without the Bearer prefix.",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    _base = field_validator("server_url", mode="before")(_base_url)

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token", key=True)
        if not value or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Issue(_Input):
    issue_key: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
        title="Issue Key or ID",
    )


class _Page(_Input):
    start_at: int = Field(
        0,
        ge=0,
        le=2147483647,
        title="Start At",
        description="Zero-based page offset. Read the returned startAt, maxResults, total or isLast before requesting another page.",
    )
    max_results: int = Field(
        50,
        ge=1,
        le=100,
        title="Page Size",
        description="Requested page size; Jira may cap it.",
    )


class _Board(_Input):
    board_id: int = Field(..., ge=1, le=9223372036854775807, title="Board ID")


class _Sprint(_Input):
    sprint_id: int = Field(..., ge=1, le=9223372036854775807, title="Sprint ID")


class _Dates(_Input):
    start_date: str | None = Field(
        None,
        title="Start Date",
        description="ISO 8601 timestamp with timezone, for example 2015-04-11T15:22:00.000+10:00.",
    )
    end_date: str | None = Field(
        None, title="End Date", description="ISO 8601 timestamp with timezone."
    )
    goal: str | None = Field(None, max_length=10000, title="Goal")

    @field_validator("start_date", "end_date")
    @classmethod
    def date(cls, value):
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError(
                    "Use an ISO 8601 timestamp including its timezone"
                ) from None
        return value


class JiraServerGetCurrentUserConfig(_Input):
    operation: Literal["get_current_user"] = Field(
        "get_current_user",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Current User"},
    )


class JiraServerGetIssueConfig(_Issue):
    operation: Literal["get_issue"] = Field(
        "get_issue",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Issue"},
    )
    fields: str | None = Field(
        None, title="Fields", description="Comma-separated field names."
    )
    expand: str | None = Field(None, title="Expand")


class JiraServerSearchIssuesConfig(_Page):
    operation: Literal["search_issues"] = Field(
        "search_issues",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Search Issues"},
    )
    jql: str = Field(
        ...,
        min_length=1,
        title="JQL",
        description="Jira Query Language, for example project = HSP.",
    )
    fields: list[str] | None = Field(
        None, title="Fields", json_schema_extra={"ui:widget": "json"}
    )


class JiraServerCreateIssueConfig(_Input):
    operation: Literal["create_issue"] = Field(
        "create_issue",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Create Issue"},
    )
    project_key: str = Field(..., min_length=1, title="Project Key")
    issue_type: str = Field(
        ...,
        min_length=1,
        title="Issue Type Name",
        description="For example Bug or Task; must be available on the project create screen.",
    )
    summary: str = Field(..., min_length=1, max_length=255, title="Summary")
    description: str | None = Field(
        None, title="Description", description="Server wiki markup text, not Cloud ADF."
    )
    assignee_name: str | None = Field(None, title="Assignee Username")
    labels: list[str] | None = Field(
        None, title="Labels", json_schema_extra={"ui:widget": "json"}
    )
    custom_fields: dict[str, Any] | None = Field(
        None,
        title="Custom Fields",
        description="Only customfield_ keys; values must match the project field metadata.",
        json_schema_extra={"ui:widget": "json"},
    )


class JiraServerUpdateIssueConfig(_Issue):
    operation: Literal["update_issue"] = Field(
        "update_issue",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Update Issue"},
    )
    fields: dict[str, Any] = Field(
        ...,
        min_length=1,
        title="Fields",
        description='Jira field values, for example {"summary": "Updated summary"}. Only fields on the edit screen can be set.',
        json_schema_extra={"ui:widget": "json"},
    )
    notify_users: bool = Field(
        True,
        title="Notify Users",
        description="Disabling notifications requires Jira administrator permission.",
    )


class JiraServerDeleteIssueConfig(_Issue):
    operation: Literal["delete_issue"] = Field(
        "delete_issue",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Issue"},
    )
    delete_subtasks: bool = Field(
        False,
        title="Delete Subtasks",
        description="If true, deletes child subtasks with the issue.",
    )


class JiraServerAssignIssueConfig(_Issue):
    operation: Literal["assign_issue"] = Field(
        "assign_issue",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Assign Issue"},
    )
    username: str | None = Field(
        ...,
        title="Assignee Username",
        description="Jira username; null unassigns, -1 uses the default assignee.",
    )


class JiraServerListCommentsConfig(_Issue, _Page):
    operation: Literal["list_comments"] = Field(
        "list_comments",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Comments"},
    )


class JiraServerAddCommentConfig(_Issue):
    operation: Literal["add_comment"] = Field(
        "add_comment",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Add Comment"},
    )
    body: str = Field(
        ..., min_length=1, title="Comment", description="Jira Server wiki markup text."
    )


class JiraServerListTransitionsConfig(_Issue):
    operation: Literal["list_transitions"] = Field(
        "list_transitions",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Transitions"},
    )


class JiraServerTransitionIssueConfig(_Issue):
    operation: Literal["transition_issue"] = Field(
        "transition_issue",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Transition Issue"},
    )
    transition_id: str = Field(
        ...,
        min_length=1,
        title="Transition ID",
        description="Choose an ID returned by List Transitions.",
    )
    fields: dict[str, Any] | None = Field(
        None,
        title="Transition Fields",
        description="Fields required by the transition screen, if any.",
        json_schema_extra={"ui:widget": "json"},
    )


class JiraServerListProjectsConfig(_Input):
    operation: Literal["list_projects"] = Field(
        "list_projects",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Projects"},
    )


class JiraServerGetProjectConfig(_Input):
    operation: Literal["get_project"] = Field(
        "get_project",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Project"},
    )
    project_key: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
        title="Project Key or ID",
    )


class JiraServerListIssueTypesConfig(_Input):
    operation: Literal["list_issue_types"] = Field(
        "list_issue_types",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Issue Types"},
    )


class JiraServerListPrioritiesConfig(_Input):
    operation: Literal["list_priorities"] = Field(
        "list_priorities",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Priorities"},
    )


class JiraServerListWorklogsConfig(_Issue):
    operation: Literal["list_worklogs"] = Field(
        "list_worklogs",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Worklogs"},
    )


class JiraServerAddWorklogConfig(_Issue):
    operation: Literal["add_worklog"] = Field(
        "add_worklog",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Add Worklog"},
    )
    time_spent_seconds: int = Field(
        ..., ge=1, le=9223372036854775807, title="Time Spent in Seconds"
    )
    started: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{4}$",
        title="Started",
        description="Jira timestamp, for example 2010-07-14T18:23:23.733+0000.",
    )
    comment: str | None = Field(None, title="Comment")

    @field_validator("started")
    @classmethod
    def started_date(cls, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            raise ValueError(
                "Use a valid Jira timestamp with milliseconds and timezone"
            ) from None
        return value


class JiraServerListBoardsConfig(_Page):
    operation: Literal["list_boards"] = Field(
        "list_boards",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Boards"},
    )
    name: str | None = Field(None, title="Board Name Filter")
    project_key: str | None = Field(None, title="Project Key or ID Filter")


class JiraServerGetBoardConfig(_Board):
    operation: Literal["get_board"] = Field(
        "get_board",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Board"},
    )


class JiraServerListSprintsConfig(_Board, _Page):
    operation: Literal["list_sprints"] = Field(
        "list_sprints",
        json_schema_extra={"ui:hidden": True, "x-display-name": "List Sprints"},
    )


class JiraServerGetSprintConfig(_Sprint):
    operation: Literal["get_sprint"] = Field(
        "get_sprint",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Get Sprint"},
    )


class JiraServerCreateSprintConfig(_Board, _Dates):
    operation: Literal["create_sprint"] = Field(
        "create_sprint",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Create Sprint"},
    )
    name: str = Field(..., min_length=1, max_length=255, title="Sprint Name")


class JiraServerUpdateSprintConfig(_Sprint, _Dates):
    operation: Literal["update_sprint"] = Field(
        "update_sprint",
        json_schema_extra={"ui:hidden": True, "x-display-name": "Update Sprint"},
    )
    name: str = Field(..., min_length=1, max_length=255, title="Sprint Name")
    state: Literal["future", "active", "closed"] | None = Field(
        None,
        title="State",
        description="Starting a sprint needs start/end dates. Closing moves incomplete issues according to Jira settings.",
    )


class JiraServerMoveIssuesToSprintConfig(_Sprint):
    operation: Literal["move_issues_to_sprint"] = Field(
        "move_issues_to_sprint",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Move Issues To Sprint",
        },
    )
    issues: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        title="Issue Keys or IDs",
        description="At most 50 issues; the sprint must be future or active.",
        json_schema_extra={"ui:widget": "json"},
    )

    @field_validator("issues")
    @classmethod
    def issue_keys(cls, values):
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", x) for x in values):
            raise ValueError("Use issue keys or IDs, without paths")
        return values


JiraSoftwareServerConfig = Annotated[
    Union[
        JiraServerGetCurrentUserConfig,
        JiraServerGetIssueConfig,
        JiraServerSearchIssuesConfig,
        JiraServerCreateIssueConfig,
        JiraServerUpdateIssueConfig,
        JiraServerDeleteIssueConfig,
        JiraServerAssignIssueConfig,
        JiraServerListCommentsConfig,
        JiraServerAddCommentConfig,
        JiraServerListTransitionsConfig,
        JiraServerTransitionIssueConfig,
        JiraServerListProjectsConfig,
        JiraServerGetProjectConfig,
        JiraServerListIssueTypesConfig,
        JiraServerListPrioritiesConfig,
        JiraServerListWorklogsConfig,
        JiraServerAddWorklogConfig,
        JiraServerListBoardsConfig,
        JiraServerGetBoardConfig,
        JiraServerListSprintsConfig,
        JiraServerGetSprintConfig,
        JiraServerCreateSprintConfig,
        JiraServerUpdateSprintConfig,
        JiraServerMoveIssuesToSprintConfig,
    ],
    Field(discriminator="operation"),
]


class JiraSoftwareServerFullConfig(
    NodeConfig[JiraSoftwareServerConfig, JiraSoftwareServerTokenCredential]
):
    pass


ROUTES = {
    "get_current_user": ("GET", "/api/2/myself", {}, None, 200),
    "get_issue": (
        "GET",
        "/api/2/issue/{issue_key}",
        {"fields": "fields", "expand": "expand"},
        None,
        200,
    ),
    "search_issues": ("POST", "/api/2/search", {}, "search", 200),
    "create_issue": ("POST", "/api/2/issue", {}, "create_issue", 201),
    "update_issue": (
        "PUT",
        "/api/2/issue/{issue_key}",
        {"notify_users": "notifyUsers"},
        "fields",
        204,
    ),
    "delete_issue": (
        "DELETE",
        "/api/2/issue/{issue_key}",
        {"delete_subtasks": "deleteSubtasks"},
        None,
        204,
    ),
    "assign_issue": ("PUT", "/api/2/issue/{issue_key}/assignee", {}, "assignee", 204),
    "list_comments": (
        "GET",
        "/api/2/issue/{issue_key}/comment",
        {"start_at": "startAt", "max_results": "maxResults"},
        None,
        200,
    ),
    "add_comment": ("POST", "/api/2/issue/{issue_key}/comment", {}, "comment", 201),
    "list_transitions": ("GET", "/api/2/issue/{issue_key}/transitions", {}, None, 200),
    "transition_issue": (
        "POST",
        "/api/2/issue/{issue_key}/transitions",
        {},
        "transition",
        204,
    ),
    "list_projects": ("GET", "/api/2/project", {}, None, 200),
    "get_project": ("GET", "/api/2/project/{project_key}", {}, None, 200),
    "list_issue_types": ("GET", "/api/2/issuetype", {}, None, 200),
    "list_priorities": ("GET", "/api/2/priority", {}, None, 200),
    "list_worklogs": ("GET", "/api/2/issue/{issue_key}/worklog", {}, None, 200),
    "add_worklog": ("POST", "/api/2/issue/{issue_key}/worklog", {}, "worklog", 201),
    "list_boards": (
        "GET",
        "/agile/1.0/board",
        {
            "start_at": "startAt",
            "max_results": "maxResults",
            "name": "name",
            "project_key": "projectKeyOrId",
        },
        None,
        200,
    ),
    "get_board": ("GET", "/agile/1.0/board/{board_id}", {}, None, 200),
    "list_sprints": (
        "GET",
        "/agile/1.0/board/{board_id}/sprint",
        {"start_at": "startAt", "max_results": "maxResults"},
        None,
        200,
    ),
    "get_sprint": ("GET", "/agile/1.0/sprint/{sprint_id}", {}, None, 200),
    "create_sprint": ("POST", "/agile/1.0/sprint", {}, "create_sprint", 201),
    "update_sprint": (
        "POST",
        "/agile/1.0/sprint/{sprint_id}",
        {},
        "update_sprint",
        200,
    ),
    "move_issues_to_sprint": (
        "POST",
        "/agile/1.0/sprint/{sprint_id}/issue",
        {},
        "issues",
        204,
    ),
}


def _body(config, kind):
    v = config.model_dump(exclude_none=True)
    if kind == "search":
        return {
            "jql": config.jql,
            "startAt": config.start_at,
            "maxResults": config.max_results,
            **({"fields": config.fields} if config.fields is not None else {}),
        }
    if kind == "create_issue":
        fields = {
            "project": {"key": config.project_key},
            "issuetype": {"name": config.issue_type},
            "summary": config.summary,
        }
        for key in ("description", "labels"):
            if key in v:
                fields[key] = v[key]
        if config.assignee_name is not None:
            fields["assignee"] = {"name": config.assignee_name}
        if config.custom_fields:
            if any(
                not re.fullmatch(r"customfield_[0-9]+", key)
                for key in config.custom_fields
            ):
                raise ValueError("Use customfield_ IDs in Custom Fields")
            fields.update(config.custom_fields)
        return {"fields": fields}
    if kind == "fields":
        return {"fields": config.fields}
    if kind == "assignee":
        return {"name": config.username}
    if kind == "comment":
        return {"body": config.body}
    if kind == "transition":
        return {
            "transition": {"id": config.transition_id},
            **({"fields": config.fields} if config.fields is not None else {}),
        }
    if kind == "worklog":
        return {
            "timeSpentSeconds": config.time_spent_seconds,
            "started": config.started,
            **({"comment": config.comment} if config.comment is not None else {}),
        }
    if kind in {"create_sprint", "update_sprint"}:
        body = {"name": config.name}
        for own, wire in (
            ("start_date", "startDate"),
            ("end_date", "endDate"),
            ("goal", "goal"),
            ("state", "state"),
        ):
            if own in v:
                body[wire] = v[own]
        if kind == "create_sprint":
            body["originBoardId"] = config.board_id
        return body
    if kind == "issues":
        return {"issues": config.issues}
    return None


class JiraSoftwareServerNode(WorkflowNode):
    integration_type = "automation-jira-software-server"
    connection_evidence = ConnectionEvidence(
        noun="Jira account",
        identity_operation="get_current_user",
        identity_keys=("displayName", "name", "key"),
    )

    @classmethod
    def get_config_model(cls):
        return JiraSoftwareServerFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Jira Software Server personal access token")
        credential = self.config.credentials
        config = self.config.config
        method, path, query, kind, expected = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for name in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {
            wire: str(values[own]).lower()
            if isinstance(values[own], bool)
            else values[own]
            for own, wire in query.items()
            if own in values
        }
        headers = {
            "Authorization": "Bearer " + credential.api_token,
            "Accept": "application/json",
        }
        body = _body(config, kind)
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    credential.server_url + "/rest" + path,
                    params=params,
                    headers=headers,
                    **({"json": body} if body is not None else {}),
                )
        except httpx.HTTPError:
            raise ValueError(
                "Jira request did not complete; inspect Jira before retrying a write"
            ) from None
        if response.status_code != expected:
            detail = response.text.replace(credential.api_token, "[redacted]")[:2000]
            raise ValueError(f"Jira API {response.status_code}: {detail}")
        if expected == 204:
            return {"status": "success", "success": True, "operation": config.operation}
        if "json" not in response.headers.get("content-type", "").lower():
            raise ValueError(
                "Jira returned a non-JSON response; check the instance URL"
            )
        data = response.json()
        if not isinstance(data, (dict, list)) or (
            isinstance(data, dict) and ("errorMessages" in data or "errors" in data)
        ):
            raise ValueError("Jira returned an unexpected response")
        if config.operation == "get_current_user" and (
            not isinstance(data, dict) or not (data.get("name") or data.get("key"))
        ):
            raise ValueError("Jira did not return an authenticated user")
        return {"status": "success", "data": data}
