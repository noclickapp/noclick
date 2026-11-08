"""Zoho Projects V3 workflow actions.

The paths, methods, request fields and scopes below are from
https://projects.zoho.com/api-docs (V3, accessed 2026-10-04). IDs are kept
as strings because Zoho IDs exceed JavaScript's safe integer range.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.zoho_projects import ZOHO_PROJECTS_SCOPES
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.oauth.zoho_projects_oauth import hosts_for, OAUTH_PROVIDER


class ZohoProjectsOAuthCredential(BaseModel):
    credential_type: Literal["zoho_projects_oauth"] = Field("zoho_projects_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., json_schema_extra={"ui:widget": "password"})
    expires_at: str
    location: str
    accounts: str
    accounts_server: str
    portal_id: str | None = None
    portal_name: str | None = None

    model_config = ConfigDict(title="Zoho Projects OAuth", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "zoho_projects",
        "x-oauth-scopes": sorted(ZOHO_PROJECTS_SCOPES.declared_scopes()),
        "x-credential-url": "https://api-console.zoho.com/",
    })


def _id_field(title: str, field_name: str) -> tuple[type, Any]:
    options = {
        "field_name": field_name, "placeholder": f"Select {title.lower()}...",
        "searchable": True, "allow_custom": True,
        "custom_placeholder": f"Or paste {title.lower()} ID",
    }
    if field_name != "portal_id":
        options["depends_on"] = "portal_id" if field_name == "project_id" else "project_id"
    return (str, Field(..., title=title, json_schema_extra={
        "x-dynamic-options": options, "x-resource-type": f"zoho_projects_{field_name}",
    }))


PORTAL = _id_field("Portal", "portal_id")
PROJECT = _id_field("Project", "project_id")
TASKLIST = _id_field("Task List", "tasklist_id")
TASK = _id_field("Task", "task_id")


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    scope: str
    category: str
    label: str
    fields: dict[str, tuple[type, Any]]
    collection: str | None = None


PAGE = {
    "page": (int, Field(1, ge=1, title="Page")),
    "per_page": (int, Field(100, ge=1, le=200, title="Per Page")),
}
NAME = (str, Field(..., min_length=1, title="Name"))
DESC = (Optional[str], Field(None, title="Description", json_schema_extra={"ui:widget": "textarea"}))

# Every operation is a fixed documented endpoint. No caller-controlled URL,
# method, arbitrary JSON body, attachment upload, or invite/assignment action.
OPS: dict[str, Operation] = {
    "list_portals": Operation("GET", "/portals", "portals.READ", "Portals", "List Portals", {}, "portals"),
    "get_portal": Operation("GET", "/portal/{portal_id}", "portals.READ", "Portals", "Get Portal", {"portal_id": PORTAL}),
    "list_projects": Operation("GET", "/portal/{portal_id}/projects", "projects.READ", "Projects", "List Projects", {"portal_id": PORTAL, **PAGE}, "projects"),
    "get_project": Operation("GET", "/portal/{portal_id}/projects/{project_id}", "projects.READ", "Projects", "Get Project", {"portal_id": PORTAL, "project_id": PROJECT}),
    "create_project": Operation("POST", "/portal/{portal_id}/projects", "projects.CREATE", "Projects", "Create Project", {
        "portal_id": PORTAL, "name": NAME,
        "owner_zpuid": (str, Field(..., title="Project Owner", description="V3 requires owner.zpuid. The picker shows the portal owner; paste another user's ZPUID if needed.", json_schema_extra={
            "x-dynamic-options": {"field_name": "owner_zpuid", "placeholder": "Select portal owner...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste user ZPUID", "depends_on": "portal_id"},
            "x-resource-type": "zoho_projects_owner_zpuid",
        })),
        "description": DESC,
        "project_type": (Optional[Literal["active", "template"]], Field(None, title="Project Type")),
        "is_public_project": (Optional[bool], Field(None, title="Public Project")),
        "start_date": (Optional[str], Field(None, title="Start Date", description="YYYY-MM-DD")),
        "end_date": (Optional[str], Field(None, title="End Date", description="YYYY-MM-DD")),
    }),
    "update_project": Operation("PATCH", "/portal/{portal_id}/projects/{project_id}", "projects.UPDATE", "Projects", "Update Project", {
        "portal_id": PORTAL, "project_id": PROJECT,
        "name": (Optional[str], Field(None, title="Name")), "description": DESC,
        "start_date": (Optional[str], Field(None, title="Start Date", description="YYYY-MM-DD")),
        "end_date": (Optional[str], Field(None, title="End Date", description="YYYY-MM-DD")),
    }),
    "trash_project": Operation("POST", "/portal/{portal_id}/projects/{project_id}/trash", "projects.UPDATE", "Projects", "Trash Project", {"portal_id": PORTAL, "project_id": PROJECT}),
    "restore_project": Operation("POST", "/portal/{portal_id}/projects/{project_id}/restore", "projects.UPDATE", "Projects", "Restore Project", {"portal_id": PORTAL, "project_id": PROJECT}),
    "delete_project": Operation("DELETE", "/portal/{portal_id}/projects/{project_id}", "projects.DELETE", "Projects", "Permanently Delete Project", {"portal_id": PORTAL, "project_id": PROJECT}),
    "list_tasklists": Operation("GET", "/portal/{portal_id}/projects/{project_id}/tasklists", "tasklists.READ", "Task Lists", "List Task Lists", {"portal_id": PORTAL, "project_id": PROJECT, **PAGE}, "tasklists"),
    "list_all_tasklists": Operation("GET", "/portal/{portal_id}/all-tasklists", "tasklists.READ", "Task Lists", "List All Task Lists", {"portal_id": PORTAL, **PAGE}, "tasklists"),
    "get_tasklist": Operation("GET", "/portal/{portal_id}/projects/{project_id}/tasklists/{tasklist_id}", "tasklists.READ", "Task Lists", "Get Task List", {"portal_id": PORTAL, "project_id": PROJECT, "tasklist_id": TASKLIST}),
    "create_tasklist": Operation("POST", "/portal/{portal_id}/projects/{project_id}/tasklists", "tasklists.CREATE", "Task Lists", "Create Task List", {
        "portal_id": PORTAL, "project_id": PROJECT, "name": NAME,
        "flag": (Optional[Literal["internal", "external"]], Field(None, title="Visibility")),
    }),
    # Zoho's V3 docs publish CREATE for the PATCH operation too.
    "update_tasklist": Operation("PATCH", "/portal/{portal_id}/projects/{project_id}/tasklists/{tasklist_id}", "tasklists.CREATE", "Task Lists", "Update Task List", {
        "portal_id": PORTAL, "project_id": PROJECT, "tasklist_id": TASKLIST,
        "name": (Optional[str], Field(None, title="Name")),
        "flag": (Optional[Literal["internal", "external"]], Field(None, title="Visibility")),
        "status": (Optional[Literal["active", "completed"]], Field(None, title="Status")),
    }),
    "delete_tasklist": Operation("DELETE", "/portal/{portal_id}/projects/{project_id}/tasklists/{tasklist_id}", "tasklists.DELETE", "Task Lists", "Delete Task List", {"portal_id": PORTAL, "project_id": PROJECT, "tasklist_id": TASKLIST}),
    "list_tasks": Operation("GET", "/portal/{portal_id}/projects/{project_id}/tasks", "tasks.READ", "Tasks", "List Tasks", {"portal_id": PORTAL, "project_id": PROJECT, **PAGE}, "tasks"),
    "list_all_tasks": Operation("GET", "/portal/{portal_id}/tasks", "tasks.READ", "Tasks", "List All Tasks", {"portal_id": PORTAL, **PAGE}, "tasks"),
    "get_task": Operation("GET", "/portal/{portal_id}/projects/{project_id}/tasks/{task_id}", "tasks.READ", "Tasks", "Get Task", {"portal_id": PORTAL, "project_id": PROJECT, "task_id": TASK}),
    "create_task": Operation("POST", "/portal/{portal_id}/projects/{project_id}/tasks", "tasks.CREATE", "Tasks", "Create Task", {
        "portal_id": PORTAL, "project_id": PROJECT, "name": NAME,
        "description": DESC,
        "tasklist_id": (Optional[str], Field(None, title="Task List ID", description="Optional; uses the general task list when omitted.")),
        "priority": (Optional[Literal["none", "low", "medium", "high"]], Field(None, title="Priority")),
        "start_date": (Optional[str], Field(None, title="Start Date", description="ISO 8601 timestamp")),
        "end_date": (Optional[str], Field(None, title="End Date", description="ISO 8601 timestamp")),
    }),
    "update_task": Operation("PATCH", "/portal/{portal_id}/projects/{project_id}/tasks/{task_id}", "tasks.UPDATE", "Tasks", "Update Task", {
        "portal_id": PORTAL, "project_id": PROJECT, "task_id": TASK,
        "name": (Optional[str], Field(None, title="Name")), "description": DESC,
        "priority": (Optional[Literal["none", "low", "medium", "high"]], Field(None, title="Priority")),
        "status_id": (Optional[str], Field(None, title="Status ID")),
        "completion_percentage": (Optional[int], Field(None, ge=0, le=100, title="Completion Percentage")),
        "start_date": (Optional[str], Field(None, title="Start Date", description="ISO 8601 timestamp")),
        "end_date": (Optional[str], Field(None, title="End Date", description="ISO 8601 timestamp")),
    }),
    "delete_task": Operation("DELETE", "/portal/{portal_id}/projects/{project_id}/tasks/{task_id}", "tasks.DELETE", "Tasks", "Delete Task", {"portal_id": PORTAL, "project_id": PROJECT, "task_id": TASK}),
    "on_new_task": Operation("GET", "/portal/{portal_id}/projects/{project_id}/tasks", "tasks.READ", "Triggers", "On New Task", {"portal_id": PORTAL, "project_id": PROJECT}),
}


def _model_for(name: str, spec: Operation) -> type[BaseModel]:
    title = "ZohoProjects" + "".join(p.title() for p in name.split("_")) + "Config"
    is_trigger = spec.category == "Triggers"
    operation_field = (Literal[name], Field(name, title=spec.label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": spec.category,
        "x-is-trigger": is_trigger, "x-display-name": spec.label,
    }))
    return create_model(title, __base__=PollTriggerConfigBase if is_trigger else BaseModel, operation=operation_field, **spec.fields)


OP_MODELS = {name: _model_for(name, spec) for name, spec in OPS.items()}
ZohoProjectsOperation = Annotated[Union[tuple(OP_MODELS.values())], Discriminator("operation")]


class ZohoProjectsNodeConfig(NodeConfig[ZohoProjectsOperation, ZohoProjectsOAuthCredential]):
    pass




def _safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or not value.isascii() or not value.isdigit():
        raise ValueError(f"{label} must be a numeric Zoho ID")
    return quote(value, safe="")


def _has_next_page(info: Any) -> bool:
    if not isinstance(info, dict) or "has_next_page" not in info:
        raise ValueError("Zoho Projects pagination metadata is missing")
    value = info.get("has_next_page")
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError("Zoho Projects pagination metadata is malformed")


def _identified_rows(rows: Any, *, label_key: str = "name") -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("Zoho Projects list response is malformed")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].isascii() or not row["id"].isdigit():
            raise ValueError("Zoho Projects list contains an unidentifiable item")
        if not isinstance(row.get(label_key), str) or not row[label_key].strip():
            raise ValueError("Zoho Projects list contains an unnamed item")
    return rows


async def zoho_request(credential: dict[str, Any], method: str, path: str, *, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
    _, host = hosts_for(credential["location"], credential.get("accounts_server"))
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method, f"{host}/api/v3{path}",
                headers={"Authorization": f"Bearer {credential['access_token']}", "Accept": "application/json"},
                params=params, json=body,
            )
    except httpx.TimeoutException as exc:
        raise ValueError("Zoho Projects request timed out") from exc
    except httpx.RequestError as exc:
        raise ValueError("Zoho Projects could not be reached") from exc
    if not 200 <= response.status_code < 300:
        # Provider bodies can contain request echoes or bearer material.
        raise ValueError(f"Zoho Projects API returned HTTP {response.status_code}")
    if response.status_code == 204 or (response.status_code == 202 and not response.content):
        return {"status": "accepted" if response.status_code == 202 else "success", "http_status": response.status_code}
    if not response.content:
        raise ValueError("Zoho Projects returned an empty response")
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        raise ValueError("Zoho Projects returned an unexpected non-JSON response")
    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError("Zoho Projects returned malformed JSON") from exc
    if not isinstance(data, (dict, list)):
        raise ValueError("Zoho Projects returned an unexpected JSON response")
    return {"status": "accepted" if response.status_code == 202 else "success", "http_status": response.status_code, "data": data}


class ZohoProjectsNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-zoho-projects"
    edit_examples = [
        "Create a Zoho Projects task when a form is submitted",
        "List tasks in a Zoho project",
        "Update a Zoho Projects task's priority",
    ]
    scope_registry = ZOHO_PROJECTS_SCOPES
    connection_evidence = ConnectionEvidence(field="portal_id", noun="portals")

    @classmethod
    def get_config_model(cls):
        return ZohoProjectsNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="zoho_projects",
        )

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: dict[str, Any], context: Optional[dict[str, Any]] = None, page_token: Optional[str] = None, search: Optional[str] = None) -> dict[str, Any]:
        context = context or {}
        config = context.get("config") if isinstance(context.get("config"), dict) else context
        if field_name in ("portal_id", "owner_zpuid"):
            result = await zoho_request(credential_data, "GET", "/portals")
            rows = _identified_rows(result.get("data"), label_key="portal_name")
            if not rows:
                raise ValueError("No Zoho Projects portal is accessible")
            if field_name == "portal_id":
                options = [{"value": p["id"], "label": p["portal_name"]} for p in rows]
            else:
                portal_id = _safe_id(config.get("portal_id") or credential_data.get("portal_id"), "Portal")
                options = []
                for portal in rows:
                    owner = portal.get("owner")
                    if portal["id"] != portal_id or not isinstance(owner, dict):
                        continue
                    zpuid, name = owner.get("zpuid"), owner.get("full_name")
                    if isinstance(zpuid, str) and zpuid.isascii() and zpuid.isdigit() and isinstance(name, str) and name.strip():
                        options.append({"value": zpuid, "label": name})
        elif field_name in ("project_id", "tasklist_id", "task_id"):
            portal = _safe_id(config.get("portal_id") or credential_data.get("portal_id"), "Portal")
            if field_name != "project_id" and not config.get("project_id"):
                return {"options": [], "next_page_token": None}
            project = _safe_id(config["project_id"], "Project") if field_name != "project_id" else None
            resource = {"project_id": "projects", "tasklist_id": "tasklists", "task_id": "tasks"}[field_name]
            path = f"/portal/{portal}/projects" + (f"/{project}/{resource}" if project else "")
            token = page_token if page_token is not None else "1"
            if not isinstance(token, str) or not token.isascii() or not token.isdigit() or int(token) < 1:
                raise ValueError("Zoho Projects picker page must be a positive numeric page")
            page = int(token)
            query = (search or "").strip().lower()
            options = []
            seen_ids = set()
            # V3 uses page/per_page and page_info.has_next_page. Search needs
            # enough matches to scroll: an empty filtered page cannot advance
            # the shared picker. Consume full pages so continuation skips no rows.
            for _ in range(10 if query else 1):
                result = await zoho_request(credential_data, "GET", path, params={"page": page, "per_page": 100})
                data = result.get("data")
                # Retain the documented bare-array project response as well as
                # the V3 collection envelope. Envelopes must carry pagination.
                rows = _identified_rows(data if isinstance(data, list) else data.get(resource) if isinstance(data, dict) else None)
                if query:
                    for row in rows:
                        if row["id"] in seen_ids:
                            raise ValueError("Zoho Projects picker returned repeated items")
                        seen_ids.add(row["id"])
                info = data.get("page_info") if isinstance(data, dict) else None
                if isinstance(data, dict):
                    has_more = _has_next_page(info)
                    if "page" in info and (type(info["page"]) is not int or info["page"] != page):
                        raise ValueError("Zoho Projects picker pagination page did not advance")
                else:
                    if query and len(rows) >= 100:
                        raise ValueError("Zoho Projects picker search pagination metadata is missing")
                    has_more = False
                options.extend({"value": row["id"], "label": row["name"]} for row in rows
                               if not query or query in row["name"].lower())
                next_page = str(page + 1) if has_more else None
                if not query or not has_more or len(options) >= 25:
                    return {"options": options, "next_page_token": next_page}
                page += 1
            raise ValueError("Zoho Projects picker search exceeded 10 pages; browse without search or paste a numeric ID")
        else:
            return {"options": [], "next_page_token": None}
        if search:
            options = [o for o in options if search.lower() in o["label"].lower()]
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ZohoProjectsNodeConfig) or not self.config.credentials:
            raise ValueError("A Zoho Projects credential and operation are required")
        op = self.config.config
        name = op.operation
        spec = OPS[name]
        creds = self.config.credentials.model_dump()
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=creds,
            refresh=OAUTH_PROVIDER.bind_refresh(creds),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="zoho_projects", caller_path="execute",
        )
        values = op.model_dump(exclude_none=True)
        path = spec.path
        for key in ("portal_id", "project_id", "tasklist_id", "task_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", _safe_id(values[key], key))
        params = {key: values[key] for key in ("page", "per_page") if key in values}
        body = {key: value for key, value in values.items() if key not in {"operation", "portal_id", "project_id", "tasklist_id", "task_id", "page", "per_page"}}
        if "owner_zpuid" in body:
            body["owner"] = {"zpuid": _safe_id(body.pop("owner_zpuid"), "Owner ZPUID")}
        if "tasklist_id" in values and name == "create_task":
            body["tasklist"] = {"id": _safe_id(values["tasklist_id"], "Task List")}
        if "status_id" in body:
            body["status"] = {"id": _safe_id(body.pop("status_id"), "Status")}
        if name == "on_new_task":
            # V3 documents sort_by=DESC(created_time), page/per_page and
            # has_next_page. Read a bounded, complete result set before
            # updating durable seen state; fail on overflow instead of losing
            # tasks silently. A single project is the poll scope.
            tasks: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for page in range(1, 6):
                page_result = await zoho_request(creds, "GET", path, params={
                    "page": page, "per_page": 200, "sort_by": "DESC(created_time)",
                })
                data = page_result.get("data")
                if not isinstance(data, dict):
                    raise ValueError("Zoho Projects task list response is malformed")
                page_tasks = _identified_rows(data.get("tasks"))
                for task in page_tasks:
                    if task["id"] in seen_ids:
                        raise ValueError("Zoho Projects returned duplicate task IDs across pages")
                    seen_ids.add(task["id"])
                tasks.extend(page_tasks)
                if not _has_next_page(data.get("page_info")):
                    break
            else:
                raise ValueError("This project has more than 1,000 tasks; the new-task trigger cannot safely baseline it")
            fresh = await self._filter_unseen(tasks, lambda task: str(task["id"]) if task.get("id") else None)
            return {"status": "success", "action": name, "project_id": values["project_id"], "new_count": len(fresh), "items": fresh}
        if spec.method == "PATCH" and not body:
            raise ValueError("At least one update field is required")
        result = await zoho_request(creds, spec.method, path, params=params or None, body=body if spec.method in ("POST", "PATCH") and body else None)
        if name == "list_portals":
            if not _identified_rows(result.get("data"), label_key="portal_name"):
                raise ValueError("No Zoho Projects portal is accessible")
        return {"action": name, **result}
