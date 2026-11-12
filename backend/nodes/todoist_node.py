"""Todoist API v1 tasks, projects, sections, labels, and comments.

The operation table follows https://developer.todoist.com/api/v1/.
"""

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.todoist import TODOIST_SCOPES
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    creates: Optional[str] = None


PAGE = ("cursor", "limit")
TASK_FIELDS = ("content", "description", "project_id", "section_id", "parent_id",
               "labels_json", "priority", "assignee_id", "due_string", "due_date",
               "due_datetime", "due_lang", "duration", "duration_unit", "deadline_date")

OPERATIONS: dict[str, Operation] = {
    "get_user": Operation("Get Current User", "Account", "GET", "/user"),
    "list_projects": Operation("List Projects", "Projects", "GET", "/projects",
                               query=("folder_id", "workspace_id", *PAGE)),
    "search_projects": Operation("Search Projects", "Projects", "GET", "/projects/search",
                                 required=("query",), query=("query", *PAGE)),
    "list_archived_projects": Operation("List Archived Projects", "Projects", "GET", "/projects/archived",
                                        query=PAGE),
    "get_project": Operation("Get Project", "Projects", "GET", "/projects/{project_id}",
                             required=("project_id",)),
    "create_project": Operation("Create Project", "Projects", "POST", "/projects",
                                required=("name",), body=("name", "description", "parent_id", "color",
                                                         "is_favorite", "view_style", "workspace_id"),
                                creates="project"),
    "update_project": Operation("Update Project", "Projects", "POST", "/projects/{project_id}",
                                required=("project_id",), body=("name", "description", "color",
                                     "is_favorite", "view_style", "child_order", "is_collapsed", "folder_id")),
    "archive_project": Operation("Archive Project", "Projects", "POST", "/projects/{project_id}/archive",
                                 required=("project_id",)),
    "unarchive_project": Operation("Unarchive Project", "Projects", "POST", "/projects/{project_id}/unarchive",
                                   required=("project_id",)),
    "delete_project": Operation("Delete Project", "Projects", "DELETE", "/projects/{project_id}",
                                required=("project_id",)),
    "list_sections": Operation("List Sections", "Sections", "GET", "/sections",
                               query=("project_id", "workspace_id", *PAGE)),
    "search_sections": Operation("Search Sections", "Sections", "GET", "/sections/search",
                                 required=("query",), query=("query", *PAGE)),
    "get_section": Operation("Get Section", "Sections", "GET", "/sections/{section_id}",
                             required=("section_id",)),
    "create_section": Operation("Create Section", "Sections", "POST", "/sections",
                                required=("name", "project_id"),
                                body=("name", "project_id", "order", "description"), creates="section"),
    "update_section": Operation("Update Section", "Sections", "POST", "/sections/{section_id}",
                                required=("section_id",),
                                body=("name", "section_order", "is_collapsed", "description")),
    "archive_section": Operation("Archive Section", "Sections", "POST", "/sections/{section_id}/archive",
                                 required=("section_id",)),
    "unarchive_section": Operation("Unarchive Section", "Sections", "POST", "/sections/{section_id}/unarchive",
                                   required=("section_id",)),
    "delete_section": Operation("Delete Section", "Sections", "DELETE", "/sections/{section_id}",
                                required=("section_id",)),
    "list_tasks": Operation("List Tasks", "Tasks", "GET", "/tasks",
                            query=("project_id", "section_id", "parent_id", "label", *PAGE)),
    "filter_tasks": Operation("Filter Tasks", "Tasks", "GET", "/tasks/filter",
                              required=("query",), query=("query", "lang", *PAGE)),
    "get_task": Operation("Get Task", "Tasks", "GET", "/tasks/{task_id}", required=("task_id",)),
    "create_task": Operation("Create Task", "Tasks", "POST", "/tasks",
                             required=("content",), body=TASK_FIELDS, creates="task"),
    "quick_add_task": Operation("Quick Add Task", "Tasks", "POST", "/tasks/quick",
                                required=("text",), body=("text", "note"), creates="task"),
    "update_task": Operation("Update Task", "Tasks", "POST", "/tasks/{task_id}",
                             required=("task_id",), body=("content", "description", "labels_json",
                                 "priority", "due_string", "due_date", "due_datetime", "due_lang",
                                 "assignee_id", "duration", "duration_unit", "deadline_date",
                                 "child_order", "is_collapsed", "day_order")),
    "move_task": Operation("Move Task", "Tasks", "POST", "/tasks/{task_id}/move",
                           required=("task_id",), body=("project_id", "section_id", "parent_id")),
    "close_task": Operation("Complete Task", "Tasks", "POST", "/tasks/{task_id}/close",
                            required=("task_id",)),
    "reopen_task": Operation("Reopen Task", "Tasks", "POST", "/tasks/{task_id}/reopen",
                             required=("task_id",)),
    "delete_task": Operation("Delete Task", "Tasks", "DELETE", "/tasks/{task_id}",
                             required=("task_id",)),
    "list_labels": Operation("List Labels", "Labels", "GET", "/labels", query=PAGE),
    "search_labels": Operation("Search Labels", "Labels", "GET", "/labels/search",
                               required=("query",), query=("query", *PAGE)),
    "get_label": Operation("Get Label", "Labels", "GET", "/labels/{label_id}",
                           required=("label_id",)),
    "create_label": Operation("Create Label", "Labels", "POST", "/labels",
                              required=("name",), body=("name", "order", "color", "is_favorite"),
                              creates="label"),
    "update_label": Operation("Update Label", "Labels", "POST", "/labels/{label_id}",
                              required=("label_id",), body=("name", "order", "color", "is_favorite")),
    "delete_label": Operation("Delete Label", "Labels", "DELETE", "/labels/{label_id}",
                              required=("label_id",)),
    "list_comments": Operation("List Comments", "Comments", "GET", "/comments",
                               query=("project_id", "task_id", *PAGE)),
    "get_comment": Operation("Get Comment", "Comments", "GET", "/comments/{comment_id}",
                             required=("comment_id",)),
    "create_comment": Operation("Create Comment", "Comments", "POST", "/comments",
                                required=("content",), body=("content", "project_id", "task_id"),
                                creates="comment"),
    "update_comment": Operation("Update Comment", "Comments", "POST", "/comments/{comment_id}",
                                required=("comment_id", "content"), body=("content",)),
    "delete_comment": Operation("Delete Comment", "Comments", "DELETE", "/comments/{comment_id}",
                                required=("comment_id",)),
}


class TodoistOAuthCredential(BaseModel):
    credential_type: Literal["todoist_oauth"] = Field("todoist_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    model_config = ConfigDict(json_schema_extra={
        "title": "Todoist OAuth", "x-credential-type": "oauth", "x-oauth-provider": "todoist",
        "x-oauth-scopes": TODOIST_SCOPES.declared_scopes(),
        "x-credential-url": "https://app.todoist.com/app/settings/integrations/developer",
    })


class TodoistAPITokenCredential(BaseModel):
    credential_type: Literal["todoist_api_token"] = Field("todoist_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal API Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(json_schema_extra={
        "title": "Todoist API Token",
        "x-credential-url": "https://app.todoist.com/app/settings/integrations/developer",
    })


# Todoist's own MCP server: agents get its tools through a person's Todoist sign-in.
TodoistMcpCredential = mcp_credential("todoist", "https://ai.todoist.net/mcp", app="Todoist")
TodoistCredential = Union[TodoistOAuthCredential, TodoistAPITokenCredential, TodoistMcpCredential]

TITLES = {
    "content": "Content", "description": "Description", "name": "Name", "text": "Quick Add Text",
    "query": "Search or Filter Query", "project_id": "Project", "section_id": "Section",
    "task_id": "Task ID", "label_id": "Label ID", "comment_id": "Comment ID",
    "labels_json": "Labels JSON", "due_string": "Natural Language Due Date",
    "due_date": "Due Date", "due_datetime": "Due Date and Time",
    "deadline_date": "Deadline Date", "is_favorite": "Favorite",
}
INTEGERS = {"limit", "priority", "order", "section_order", "child_order", "day_order", "duration",
            "assignee_id", "workspace_id", "folder_id"}
BOOLEANS = {"is_favorite", "is_collapsed"}
DYNAMIC = {
    "project_id": {"field_name": "project_id", "placeholder": "Select a project...",
                   "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste a project ID"},
    "section_id": {"field_name": "section_id", "placeholder": "Select a section...",
                   "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste a section ID",
                   "depends_on": "project_id"},
}


def _field(name: str, required: bool) -> tuple[Any, Any]:
    kind = bool if name in BOOLEANS else int if name in INTEGERS else str
    extra: dict[str, Any] = {}
    if name.endswith("_json"):
        extra["ui:widget"] = "textarea"
    if name in DYNAMIC:
        extra["x-dynamic-options"] = DYNAMIC[name]
    return (kind if required else Optional[kind],
            Field(... if required else None, title=TITLES.get(name, name.replace("_", " ").title()),
                  json_schema_extra=extra or None))


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    model_name = "Todoist" + "".join(part.title() for part in name.split("_")) + "Config"
    extra: dict[str, Any] = {"const": name, "ui:hidden": True, "x-category": op.category,
                             "x-is-trigger": False, "x-display-name": op.label}
    if op.creates:
        extra.update({"x-creates-resource": True, "x-resource-type": f"todoist_{op.creates}",
                      "x-resource-id-path": "data.id"})
    names = set(op.required + op.query + op.body)
    for marker in op.path.split("{")[1:]:
        names.add(marker.split("}")[0])
    fields = {field: _field(field, field in op.required) for field in sorted(names)}
    return create_model(model_name, __module__=__name__,
                        operation=(Literal[name], Field(name, title=op.label, json_schema_extra=extra)),
                        **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class TodoistOnNewTaskConfig(PollTriggerConfigBase):
    operation: Literal["on_new_task"] = Field("on_new_task", title="On New Task", json_schema_extra={
        "const": "on_new_task", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Task",
    })
    project_id: Optional[str] = Field(None, title="Project", json_schema_extra={
        "x-dynamic-options": DYNAMIC["project_id"],
    })


TodoistConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (TodoistOnNewTaskConfig,)],
                         Discriminator("operation")]


class TodoistNodeConfig(NodeConfig[TodoistConfig, TodoistCredential]):
    pass


class TodoistNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-todoist"
    credential_provider_labels = {"todoist": "Todoist Account"}
    connection_evidence = ConnectionEvidence(
        field="project_id", noun="projects", identity_operation="get_user",
        identity_keys=("full_name", "email"),
    )
    scope_registry = TODOIST_SCOPES
    edit_examples = [
        "Create a Todoist task due tomorrow", "List overdue Todoist tasks",
        "Complete a Todoist task", "Create a Todoist project", "Add a task comment",
    ]

    @classmethod
    def get_config_model(cls):
        return TodoistNodeConfig

    @classmethod
    def should_propagate_output(cls, output: dict[str, Any], config: dict[str, Any]) -> bool:
        if config.get("operation") == "on_new_task":
            return bool(output.get("new_task_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output: dict[str, Any]) -> Optional[dict[str, Any]]:
        tasks = output.get("tasks") if isinstance(output, dict) else None
        if not isinstance(tasks, list):
            return super().resolve_agent_event(output)
        if not tasks:
            return None
        lines = [f"- {task.get('content') or 'Untitled task'} (id {task.get('id')})"
                 for task in tasks[:10] if isinstance(task, dict)]
        if len(tasks) > 10:
            lines.append(f"- … and {len(tasks) - 10} more")
        return {"text": f"Todoist: {len(tasks)} new task(s):\n" + "\n".join(lines),
                "conversation_key": None}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.todoist_oauth import refresh_access_token
        if not credential_data.get("refresh_token"):
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="todoist")

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: dict[str, Any],
                                 context: Optional[dict[str, Any]] = None,
                                 page_token: Optional[str] = None,
                                 search: Optional[str] = None) -> dict[str, Any]:
        if field_name not in DYNAMIC:
            return {"options": []}
        token = (credential_data or {}).get("access_token") or (credential_data or {}).get("api_token")
        if not token:
            raise ValueError("Connect Todoist to list projects and sections")
        context = context or {}
        config = context.get("config") if isinstance(context.get("config"), dict) else context
        if field_name == "project_id":
            path = "/projects/search" if search else "/projects"
            params = {"limit": 100, "cursor": page_token, "query": search}
        else:
            path = "/sections"
            params = {"limit": 100, "cursor": page_token, "project_id": config.get("project_id")}
        data = await cls._request(token, "GET", path,
                                  params={key: value for key, value in params.items() if value is not None})
        return {"options": [{"value": str(item["id"]), "label": item.get("name") or str(item["id"])}
                            for item in data.get("results", []) if isinstance(item, dict) and item.get("id")],
                "next_page_token": data.get("next_cursor")}

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method, f"https://api.todoist.com/api/v1{path}", params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("error") or payload.get("error_tag") or payload.get("message")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Todoist API error {response.status_code}: {detail or 'request failed'}")
        return response.json() if response.content else {"ok": True}

    async def _access_token(self, credential: TodoistCredential) -> str:
        if isinstance(credential, TodoistOAuthCredential):
            if credential.refresh_token:
                from nodes.core.oauth_refresh import ensure_fresh_oauth_token
                from nodes.oauth.todoist_oauth import refresh_access_token
                credential_data = credential.model_dump()
                token = await ensure_fresh_oauth_token(
                    credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                    credential=credential_data, refresh=refresh_access_token,
                    provider="todoist", caller_path="execute")
                for key in ("access_token", "refresh_token", "expires_at"):
                    setattr(credential, key, credential_data.get(key))
                return token
            return credential.access_token
        return credential.api_token

    async def _poll_new_tasks(self, token: str, project_id: Optional[str]) -> dict[str, Any]:
        tasks: list[dict[str, Any]] = []
        cursor = None
        for _ in range(20):
            params = {"limit": 100}
            if project_id:
                params["project_id"] = project_id
            if cursor:
                params["cursor"] = cursor
            data = await self._request(token, "GET", "/tasks", params=params)
            tasks.extend(item for item in data.get("results", []) if isinstance(item, dict))
            cursor = data.get("next_cursor")
            if not cursor:
                break
        else:
            raise ValueError("Todoist has more than 2,000 tasks in this scope; choose a project to monitor")
        fresh = await self._filter_unseen(tasks, lambda task: str(task["id"]) if task.get("id") else None)
        return {"tasks": fresh, "new_task_count": len(fresh)}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, TodoistNodeConfig):
            raise ValueError("Todoist configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Todoist account")
        config = self.config.config
        name = config.operation
        self.scope_registry.require(name)
        token = await self._access_token(credential)
        if isinstance(config, TodoistOnNewTaskConfig):
            return await self._poll_new_tasks(token, config.project_id)
        spec = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for field in tuple(values):
            marker = "{" + field + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(field)), safe=""))
        params = {field: values[field] for field in spec.query if field in values}
        body = {}
        for field in spec.body:
            if field not in values:
                continue
            value = values[field]
            if field.endswith("_json"):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{field} must contain valid JSON") from exc
                if field == "labels_json" and (not isinstance(value, list) or
                                               not all(isinstance(label, str) for label in value)):
                    raise ValueError("Labels JSON must be an array of names")
            body[field.removesuffix("_json")] = value
        data = await self._request(token, spec.method, path, params=params or None,
                                   body=body if spec.method == "POST" else None)
        return {"status": "success", "operation": name, "data": data}
