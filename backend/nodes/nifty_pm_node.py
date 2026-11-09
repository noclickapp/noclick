"""Nifty v3 project management using a workspace-scoped personal access token.

Contract: https://developers.niftypm.com/docs/api/v3/0.154.0/nifty-v3-openapi.json
One published endpoint per operation; list operations return one cursor page.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://openapi.niftypm.com/api/v3"


class NiftyPMTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Nifty Personal Access Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.niftypm.com/docs/getting-started",
            "x-credential-instructions": "In Nifty, open Settings → API Tokens → New token. Choose the scopes for your actions and paste the token here. Tokens reach one workspace. Include members:read for the connection check; reads need the corresponding resource:read scope, creates and updates resource:write, assignments tasks:link, and deleting tasks tasks:delete. A successful connection check does not prove write permissions.",
        },
    )
    credential_type: Literal["nifty_pm_personal_access_token"] = Field(
        "nifty_pm_personal_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        min_length=1,
        title="Personal access token",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(char.isspace() for char in value):
            raise ValueError("Paste the token without a Bearer prefix or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def wire_values(cls, value, info):
        if value is None:
            return value
        if info.field_name == "id" or info.field_name.endswith("Id"):
            if (
                not value.strip()
                or any(char in value for char in "/?#\\")
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError("Paste one Nifty resource ID")
        if info.field_name in {"start", "end", "startAt", "dueAt", "expectedUpdatedAt"}:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Use an ISO 8601 timestamp with a timezone")
        return value


class _Page(_Input):
    limit: int = Field(
        50,
        ge=1,
        le=200,
        description="Maximum rows in this page; follow nextCursor until hasMore is false.",
    )
    cursor: Optional[str] = Field(
        None,
        description="Opaque nextCursor from the previous response with the same filters.",
    )
    includeTotal: bool = Field(
        False,
        description="Request the total count at the cost of an extra provider query.",
    )


class _Write(_Input):
    idempotency_key: Optional[str] = Field(
        None,
        max_length=250,
        description="Optional Idempotency-Key. Reuse only for retries of the same write within 10 minutes.",
    )


class NiftyListDocumentsConfig(_Page):
    """List Documents."""

    operation: Literal["list_documents"] = Field(
        "list_documents", json_schema_extra={"ui:hidden": True}
    )
    projectId: Optional[str] = Field(
        None,
        description="Restrict the list to one project. Omit to list documents across every project you can access.",
    )


class NiftyCreateDocumentConfig(_Write):
    """Create Document."""

    operation: Literal["create_document"] = Field(
        "create_document", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(
        ...,
        min_length=1,
        description="Document display name. Required on create; editable.",
    )
    projectId: str = Field(
        ...,
        min_length=1,
        description="The project this document belongs to. Required on create — a document always lives in a project — and immutable afterwards.",
    )
    description: Optional[str] = Field(
        None,
        max_length=2000,
        description="1–3 sentence summary of what this document is for (max 2,000 chars; null = none). Surfaced in list results so agents can discover a project's knowledge without fetching bodies. Set it when creating a document; keep it short — it is metadata, not a second body.",
    )
    content: Optional[str] = Field(
        None,
        description="Initial document body, as Markdown. Supports headings, lists, tables, code blocks and Nifty mention syntax. Create-only: the body of an existing document is EXTENDED with the `append` operation and read back with the `content` operation — it can never be replaced or deleted, and it is not returned by list or get.",
    )


class NiftyListLabelsConfig(_Page):
    """List Labels."""

    operation: Literal["list_labels"] = Field(
        "list_labels", json_schema_extra={"ui:hidden": True}
    )


class NiftyListListsConfig(_Page):
    """List Lists."""

    operation: Literal["list_lists"] = Field(
        "list_lists", json_schema_extra={"ui:hidden": True}
    )
    projectId: Optional[str] = Field(
        None,
        description="Restrict the list to one project. Omit to list lists across every project you can access.",
    )


class NiftyCreateListConfig(_Write):
    """Create List."""

    operation: Literal["create_list"] = Field(
        "create_list", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="List name. Trimmed; obvious spam is rejected with 400.",
    )
    projectId: str = Field(
        ...,
        min_length=1,
        description="Project this list belongs to (scope). Immutable after creation.",
    )
    description: Optional[str] = Field(None, description="List description")


class NiftyListMembersConfig(_Page):
    """List Team Members."""

    operation: Literal["list_members"] = Field(
        "list_members", json_schema_extra={"ui:hidden": True}
    )


class NiftyGetCurrentMemberConfig(_Input):
    """Me (Team Member)."""

    operation: Literal["get_current_member"] = Field(
        "get_current_member", json_schema_extra={"ui:hidden": True}
    )


class NiftyListMessagesConfig(_Page):
    """List Messages."""

    operation: Literal["list_messages"] = Field(
        "list_messages", json_schema_extra={"ui:hidden": True}
    )


class NiftyCreateMessageConfig(_Write):
    """Create Message."""

    operation: Literal["create_message"] = Field(
        "create_message", json_schema_extra={"ui:hidden": True}
    )
    text: str = Field(
        ...,
        max_length=655350,
        description="Message body. Supports Markdown formatting, plus embedded mention tags (`<@memberId>` person, `<?taskId>` task, `<#projectId>` project, `<??statusId>` status, `<^listId>` list, `<~labelId>` label, `<$portfolioId>` portfolio, `<!discussionId>` discussion). Nullable for non-text messages (gif, audio).",
    )
    taskId: str = Field(
        ...,
        description="The task this message comments on. Exactly one parent context per message.",
    )


class NiftyListProjectsConfig(_Page):
    """List Projects."""

    operation: Literal["list_projects"] = Field(
        "list_projects", json_schema_extra={"ui:hidden": True}
    )


class NiftyCreateProjectConfig(_Write):
    """Create Project."""

    operation: Literal["create_project"] = Field(
        "create_project", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name. Must be unique among the projects in the same portfolio. Maximum 100 characters.",
    )
    description: Optional[str] = Field(
        None, description="Optional project description. Supports Markdown formatting."
    )
    portfolioId: Optional[str] = Field(
        None,
        description="The portfolio this project is grouped under. Defaults to the team's General portfolio when omitted on create. Immutable after create.",
    )
    accessType: Optional[Literal["public", "limited", "workspace"]] = Field(
        None,
        description="Visibility: limited (default — only invited members), public (all team members auto-added) or workspace (every non-guest team member can find and open it). Omit for limited.",
    )


class NiftyGetProjectConfig(_Input):
    """Get Project."""

    operation: Literal["get_project"] = Field(
        "get_project", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., min_length=1, pattern="^[0-9A-Za-z_!]+$", description="Id of the Project."
    )


class NiftyUpdateProjectConfig(_Write):
    """Update Project."""

    operation: Literal["update_project"] = Field(
        "update_project", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., min_length=1, pattern="^[0-9A-Za-z_!]+$", description="Id of the Project."
    )
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Display name. Must be unique among the projects in the same portfolio. Maximum 100 characters.",
    )
    description: Optional[str] = Field(
        None, description="Optional project description. Supports Markdown formatting."
    )
    archived: Optional[bool] = Field(
        None,
        description="Archived projects are hidden from default project lists. Archiving does NOT cascade — tasks and lists inside the project stay active. Set it with PATCH; a project cannot be created already archived.",
    )
    accessType: Optional[Literal["public", "limited", "workspace"]] = Field(
        None,
        description="Visibility: limited (default — only invited members), public (all team members auto-added) or workspace (every non-guest team member can find and open it). Omit for limited.",
    )
    expectedUpdatedAt: Optional[str] = Field(
        None,
        description="Optional concurrency guard: the `updatedAt` you last read. If the resource has changed since, the update is rejected with 409 instead of overwriting the other writer. Re-read, re-derive your change from the current values, and retry with the fresh `updatedAt`.",
    )

    @model_validator(mode="after")
    def changed_fields(self):
        if not any(
            value is not None
            for key, value in self.model_dump().items()
            if key not in {"operation", "id", "idempotency_key", "expectedUpdatedAt"}
        ):
            raise ValueError("Provide at least one field to update")
        return self


class NiftyListTasksConfig(_Page):
    """List Tasks."""

    operation: Literal["list_tasks"] = Field(
        "list_tasks", json_schema_extra={"ui:hidden": True}
    )
    projectId: Optional[str] = Field(
        None,
        description="Restrict the list to one project. Omit to list tasks across every project you can access.",
    )
    scope: Optional[Literal["both", "project", "personal"]] = Field(
        None,
        description="Which tasks a workspace-wide list returns: `project` (rows that belong to a project you can access), `personal` (your own rows, which belong to no project), or `both`. Ignored when you pass `projectId`. Default: `both`.",
    )


class NiftyCreateTaskConfig(_Write):
    """Create Task."""

    operation: Literal["create_task"] = Field(
        "create_task", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Task name. 1–1024 characters after trimming. Content that reads as promotional (link-farm text, bulk marketing copy) is rejected with a 400.",
    )
    description: Optional[str] = Field(
        None, description="Task description. Supports Markdown formatting."
    )
    projectId: Optional[str] = Field(
        None,
        min_length=1,
        description="Project this task belongs to; `null` on a personal task. Omit it on create to make a personal task (visible only to you). PATCH-ing it moves the task — and its subtasks — into another project; a personal task cannot be moved into a project, nor a project task made personal.",
    )
    listId: Optional[str] = Field(
        None,
        description="The list this task belongs to. Null when the task is not on a list. Legal ids come from `GET /lists`.",
    )
    statusId: Optional[str] = Field(
        None,
        description="The status column this task sits in. Null when the task has no status (e.g. a backlog item). Legal ids come from `GET /statuses`.",
    )
    parentTaskId: Optional[str] = Field(
        None,
        description="The parent task, when this task is a subtask. Null on top-level tasks. Subtask siblings are ranked by `order`.",
    )
    startAt: Optional[str] = Field(
        None, description="When work on this task is scheduled to start."
    )
    dueAt: Optional[str] = Field(None, description="When this task is due.")
    estimate: Optional[int] = Field(
        None,
        ge=0,
        le=2147483647,
        description="Effort estimate in minutes, used when the project's `estimationUnit` is `hours` (enter `20m` / `1h 30m` as 20 / 90); `points` projects keep `storyPoints` and convert through the team's points-per-day at read. `null` means unestimated. Not a rank and not time already spent.",
    )
    assignees: Optional[list[str]] = Field(
        None,
        max_length=50,
        description="Team member ids of the people assigned to this task. On create, seeds the set. **On update, REPLACES the whole set — members you leave out are unassigned.** For additive changes use `POST`/`DELETE /tasks/{id}/assignees`. Read the current set with `?expand=assignees`.",
    )
    labels: Optional[list[str]] = Field(
        None,
        max_length=50,
        description="Label ids attached to this task. On create, seeds the set. **On update, REPLACES the whole set — labels you leave out are detached.** For additive changes use `POST`/`DELETE /tasks/{id}/labels`. Read the current set with `?expand=labels`.",
    )


class NiftyGetTaskConfig(_Input):
    """Get Task."""

    operation: Literal["get_task"] = Field(
        "get_task", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., min_length=1, pattern="^[0-9A-Za-z_!]+$", description="Id of the Task."
    )


class NiftyUpdateTaskConfig(_Write):
    """Update Task."""

    operation: Literal["update_task"] = Field(
        "update_task", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., min_length=1, pattern="^[0-9A-Za-z_!]+$", description="Id of the Task."
    )
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=1024,
        description="Task name. 1–1024 characters after trimming. Content that reads as promotional (link-farm text, bulk marketing copy) is rejected with a 400.",
    )
    description: Optional[str] = Field(
        None, description="Task description. Supports Markdown formatting."
    )
    completed: Optional[bool] = Field(
        None,
        description='Whether this task is marked complete. Set `true` to mark a task done — Nifty renders completed tasks in a virtual "Completed" column, so prefer this over creating a separate "Done" status. Pairs with `completedAt` (timestamp) and `completedById` (who completed it).',
    )
    archived: Optional[bool] = Field(
        None, description="Whether this resource is archived."
    )
    listId: Optional[str] = Field(
        None,
        description="The list this task belongs to. Null when the task is not on a list. Legal ids come from `GET /lists`.",
    )
    statusId: Optional[str] = Field(
        None,
        description="The status column this task sits in. Null when the task has no status (e.g. a backlog item). Legal ids come from `GET /statuses`.",
    )
    dueAt: Optional[str] = Field(None, description="When this task is due.")
    estimate: Optional[int] = Field(
        None,
        ge=0,
        le=2147483647,
        description="Effort estimate in minutes, used when the project's `estimationUnit` is `hours` (enter `20m` / `1h 30m` as 20 / 90); `points` projects keep `storyPoints` and convert through the team's points-per-day at read. `null` means unestimated. Not a rank and not time already spent.",
    )
    expectedUpdatedAt: Optional[str] = Field(
        None,
        description="Optional concurrency guard: the `updatedAt` you last read. If the resource has changed since, the update is rejected with 409 instead of overwriting the other writer. Re-read, re-derive your change from the current values, and retry with the fresh `updatedAt`.",
    )

    @model_validator(mode="after")
    def changed_fields(self):
        if not any(
            value is not None
            for key, value in self.model_dump().items()
            if key not in {"operation", "id", "idempotency_key", "expectedUpdatedAt"}
        ):
            raise ValueError("Provide at least one field to update")
        return self


class NiftyDeleteTaskConfig(_Write):
    """Delete Task."""

    operation: Literal["delete_task"] = Field(
        "delete_task", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., min_length=1, pattern="^[0-9A-Za-z_!]+$", description="Id of the Task."
    )


class NiftySearchTasksConfig(_Page):
    """Search Tasks."""

    operation: Literal["search_tasks"] = Field(
        "search_tasks", json_schema_extra={"ui:hidden": True}
    )
    q: str = Field(
        ...,
        min_length=3,
        max_length=200,
        description="Full-text search query. Trimmed before matching; URLs, e-mail addresses and HTML markup are rejected.",
    )
    projectId: str = Field(
        ...,
        description="The project to search within. Required — tasks are project-scoped and search has no workspace-wide mode.",
    )


class NiftyAddTaskAssigneesConfig(_Write):
    """Add assignees to a Task."""

    operation: Literal["add_task_assignees"] = Field(
        "add_task_assignees", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., min_length=1, pattern="^[0-9A-Za-z_!]+$", description="Id of the Task."
    )
    ids: list[str] = Field(..., description="Team Members to add or remove, by id.")


class NiftyAddTaskLabelsConfig(_Write):
    """Add labels to a Task."""

    operation: Literal["add_task_labels"] = Field(
        "add_task_labels", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(
        ..., min_length=1, pattern="^[0-9A-Za-z_!]+$", description="Id of the Task."
    )
    ids: list[str] = Field(..., description="Labels to add or remove, by id.")


class NiftyListTimeEntriesConfig(_Page):
    """List Time Entries."""

    operation: Literal["list_time_entries"] = Field(
        "list_time_entries", json_schema_extra={"ui:hidden": True}
    )


class NiftyCreateTimeEntryConfig(_Write):
    """Create Time Entry."""

    operation: Literal["create_time_entry"] = Field(
        "create_time_entry", json_schema_extra={"ui:hidden": True}
    )
    start: str = Field(..., description="When the tracked interval began (ISO 8601).")
    end: str = Field(
        ...,
        description="When the tracked interval ended (ISO 8601); null while the entry is running. Start a timer with `POST /time-entries/start`. Creating an entry without `end` (or with null) makes a running entry *without* stopping your current one. PATCH `end` to stop a running entry; a stopped entry cannot be reopened, so PATCH with `end: null` is refused.",
    )
    taskId: str = Field(
        ...,
        min_length=1,
        description="The task this time is tracked against. Set once when the entry is created: an entry cannot be moved to another task afterwards. Null if that task has since been deleted — the entry is kept, and `taskNiceId` and `taskName` then say which task it was.",
    )
    projectId: Optional[str] = Field(
        None,
        description="The project this time is booked against. Set once when the entry is created: an entry cannot be moved to another project afterwards.",
    )
    description: Optional[str] = Field(
        None,
        description="Free-text note about what the time was spent on. This is the field `GET /time-entries/search` matches against.",
    )

    @model_validator(mode="after")
    def interval(self):
        if datetime.fromisoformat(
            self.end.replace("Z", "+00:00")
        ) <= datetime.fromisoformat(self.start.replace("Z", "+00:00")):
            raise ValueError("End must be after start for a completed time entry")
        return self


NiftyPMOperation = Annotated[
    Union[
        NiftyListDocumentsConfig,
        NiftyCreateDocumentConfig,
        NiftyListLabelsConfig,
        NiftyListListsConfig,
        NiftyCreateListConfig,
        NiftyListMembersConfig,
        NiftyGetCurrentMemberConfig,
        NiftyListMessagesConfig,
        NiftyCreateMessageConfig,
        NiftyListProjectsConfig,
        NiftyCreateProjectConfig,
        NiftyGetProjectConfig,
        NiftyUpdateProjectConfig,
        NiftyListTasksConfig,
        NiftyCreateTaskConfig,
        NiftyGetTaskConfig,
        NiftyUpdateTaskConfig,
        NiftyDeleteTaskConfig,
        NiftySearchTasksConfig,
        NiftyAddTaskAssigneesConfig,
        NiftyAddTaskLabelsConfig,
        NiftyListTimeEntriesConfig,
        NiftyCreateTimeEntryConfig,
    ],
    Field(discriminator="operation"),
]


class NiftyPMNodeConfig(NodeConfig[NiftyPMOperation, NiftyPMTokenCredential]):
    pass


OPERATIONS = {
    "list_documents": (
        "GET",
        "/documents",
        ["projectId", "cursor", "limit", "includeTotal"],
        [],
    ),
    "create_document": (
        "POST",
        "/documents",
        [],
        ["name", "projectId", "description", "content"],
    ),
    "list_labels": ("GET", "/labels", ["cursor", "limit", "includeTotal"], []),
    "list_lists": (
        "GET",
        "/lists",
        ["projectId", "cursor", "limit", "includeTotal"],
        [],
    ),
    "create_list": ("POST", "/lists", [], ["name", "projectId", "description"]),
    "list_members": ("GET", "/members", ["cursor", "limit", "includeTotal"], []),
    "get_current_member": ("GET", "/members/me", [], []),
    "list_messages": ("GET", "/messages", ["cursor", "limit", "includeTotal"], []),
    "create_message": ("POST", "/messages", [], ["text", "taskId"]),
    "list_projects": ("GET", "/projects", ["cursor", "limit", "includeTotal"], []),
    "create_project": (
        "POST",
        "/projects",
        [],
        ["name", "description", "portfolioId", "accessType"],
    ),
    "get_project": ("GET", "/projects/{id}", [], []),
    "update_project": (
        "PATCH",
        "/projects/{id}",
        [],
        ["name", "description", "archived", "accessType", "expectedUpdatedAt"],
    ),
    "list_tasks": (
        "GET",
        "/tasks",
        ["projectId", "scope", "cursor", "limit", "includeTotal"],
        [],
    ),
    "create_task": (
        "POST",
        "/tasks",
        [],
        [
            "name",
            "description",
            "projectId",
            "listId",
            "statusId",
            "parentTaskId",
            "startAt",
            "dueAt",
            "estimate",
            "assignees",
            "labels",
        ],
    ),
    "get_task": ("GET", "/tasks/{id}", [], []),
    "update_task": (
        "PATCH",
        "/tasks/{id}",
        [],
        [
            "name",
            "description",
            "completed",
            "archived",
            "listId",
            "statusId",
            "dueAt",
            "estimate",
            "expectedUpdatedAt",
        ],
    ),
    "delete_task": ("DELETE", "/tasks/{id}", [], []),
    "search_tasks": (
        "GET",
        "/tasks/search",
        ["q", "projectId", "cursor", "limit", "includeTotal"],
        [],
    ),
    "add_task_assignees": ("POST", "/tasks/{id}/assignees", [], ["ids"]),
    "add_task_labels": ("POST", "/tasks/{id}/labels", [], ["ids"]),
    "list_time_entries": (
        "GET",
        "/time-entries",
        ["cursor", "limit", "includeTotal"],
        [],
    ),
    "create_time_entry": (
        "POST",
        "/time-entries",
        [],
        ["start", "end", "taskId", "projectId", "description"],
    ),
}


class NiftyPMNode(WorkflowNode):
    integration_type = "automation-nifty-pm"
    connection_evidence = ConnectionEvidence(
        noun="Nifty account", identity_operation="get_current_member"
    )

    @classmethod
    def get_config_model(cls):
        return NiftyPMNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Nifty personal access token")
        config = self.config.config
        token = self.config.credentials.access_token
        method, path, query_fields, body_fields = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        if "id" in values:
            path = path.replace("{id}", quote(values["id"], safe=""))
        params = {
            key: str(values[key]).lower()
            if isinstance(values[key], bool)
            else values[key]
            for key in query_fields
            if key in values
        }
        body = {key: values[key] for key in body_fields if key in values}
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if values.get("idempotency_key"):
            headers["Idempotency-Key"] = values["idempotency_key"]
        # No automatic write retries: a timeout can follow a committed mutation.
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + path,
                    params=params,
                    headers=headers,
                    **({"json": body} if body_fields else {}),
                )
        except httpx.HTTPError:
            return {
                "status": "error",
                "error": "Nifty request could not be completed; inspect the resource before retrying a write",
            }
        if response.status_code >= 300:
            try:
                problem = response.json()
            except ValueError:
                problem = {}
            message = (
                problem.get("detail") or problem.get("title")
                if isinstance(problem, dict)
                else None
            )
            message = str(message or "Nifty rejected the request").replace(
                token, "[redacted]"
            )
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": message,
                "code": problem.get("code") if isinstance(problem, dict) else None,
            }
        if response.status_code == 204:
            return {
                "status": "success",
                "operation": config.operation,
                "http_status": 204,
                "deleted_id": values.get("id"),
            }
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Nifty returned an unreadable JSON response") from None
        if not isinstance(payload, dict):
            raise ValueError("Expected a Nifty response object")
        if config.operation.startswith(("list_", "search_")):
            if not isinstance(payload.get("data"), list):
                raise ValueError("Expected a Nifty collection envelope")
            # Preserve the documented cursor envelope, including null totals.
            output = {**payload, "status": "success", "operation": config.operation}
        else:
            output = {
                "status": "success",
                "operation": config.operation,
                "data": payload,
            }
        return output
