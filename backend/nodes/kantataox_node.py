"""Kantata OX delivery operations using a pasted personal bearer token.

Routes, envelopes and filters follow the published Swagger 2.0 contract at
https://app.mavenlink.com/oas/specification (version 1.0.0). The contract
supports personal tokens and timestamp-filtered lists, without webhook APIs.
"""
from __future__ import annotations

import hashlib
import json

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://api.mavenlink.com/api/v1"


class KantataOXTokenCredential(BaseModel):
    model_config = ConfigDict(title="Kantata OX Personal Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.mavenlink.com/oauth/applications",
            "x-credential-instructions": "As a Kantata OX account administrator, register an application on the application management page and copy the personal OAuth bearer token from its page. Paste only the token. NoClick sends it only to api.mavenlink.com. The token inherits your Kantata permissions; a paid account is required to register applications.",
        })
    credential_type: Literal["kantataox_api_token"] = Field("kantataox_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="Personal bearer token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal bearer token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the bearer token, without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def dates(cls, value, info):
        if value is None:
            return value
        if info.field_name in {"start_date", "due_date", "date_performed"}:
            date.fromisoformat(value)
        if info.field_name == "updated_after":
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Use an ISO 8601 timestamp with a timezone")
        return value

    @model_validator(mode="after")
    def update_has_fields(self):
        if self.operation.startswith("update_") and not any(
            value is not None for name, value in self.model_dump().items() if name not in {"operation", "id"}
        ):
            raise ValueError("Supply at least one field to update")
        if self.operation == "create_project" and self.budgeted and self.price is None:
            raise ValueError("Supply a price for a budgeted project")
        return self


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    resource: str
    label: str
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    envelope: Optional[str] = None


PAGE = ("page", "per_page", "updated_after")
PROJECT = ("title", "description", "start_date", "due_date", "budgeted", "price", "access_level")
TASK = ("title", "description", "story_type", "start_date", "due_date", "status", "assignee_ids", "parent_id", "percentage_complete", "priority", "billable", "time_estimate_in_minutes")
TIME = ("workspace_id", "date_performed", "time_in_minutes", "story_id", "notes", "billable", "user_id")
OPERATIONS = {
    "get_me": Operation("GET", "/users/me", "users", "Get My Account"),
    "list_projects": Operation("GET", "/workspaces", "workspaces", "List Projects", query=(*PAGE, "search")),
    "get_project": Operation("GET", "/workspaces/{id}", "workspaces", "Get Project", required=("id",)),
    "create_project": Operation("POST", "/workspaces", "workspaces", "Create Project", body=PROJECT, required=("title",), envelope="workspace"),
    "update_project": Operation("PUT", "/workspaces/{id}", "workspaces", "Update Project", body=(*PROJECT, "archived"), required=("id",), envelope="workspace"),
    "list_tasks": Operation("GET", "/stories", "stories", "List Tasks", query=(*PAGE, "workspace_id", "search")),
    "get_task": Operation("GET", "/stories/{id}", "stories", "Get Task", required=("id",)),
    "create_task": Operation("POST", "/stories", "stories", "Create Task", body=("workspace_id", *TASK), required=("workspace_id", "title"), envelope="story"),
    "update_task": Operation("PUT", "/stories/{id}", "stories", "Update Task", body=(*TASK, "archived"), required=("id",), envelope="story"),
    "list_time_entries": Operation("GET", "/time_entries", "time_entries", "List Time Entries", query=(*PAGE, "workspace_id")),
    "get_time_entry": Operation("GET", "/time_entries/{id}", "time_entries", "Get Time Entry", required=("id",)),
    "create_time_entry": Operation("POST", "/time_entries", "time_entries", "Create Time Entry", body=TIME, required=("workspace_id", "date_performed", "time_in_minutes"), envelope="time_entry"),
    "update_time_entry": Operation("PUT", "/time_entries/{id}", "time_entries", "Update Time Entry", body=TIME, required=("id",), envelope="time_entry"),
    "delete_time_entry": Operation("DELETE", "/time_entries/{id}", "time_entries", "Delete Time Entry", required=("id",)),
    "list_posts": Operation("GET", "/posts", "posts", "List Activity Posts", query=(*PAGE, "workspace_id", "search")),
    "get_post": Operation("GET", "/posts/{id}", "posts", "Get Activity Post", required=("id",)),
    "create_post": Operation("POST", "/posts", "posts", "Create Activity Post", body=("workspace_id", "message", "story_id"), required=("workspace_id", "message"), envelope="post"),
    "list_users": Operation("GET", "/users", "users", "List Users", query=(*PAGE, "search")),
    "list_expenses": Operation("GET", "/expenses", "expenses", "List Expenses", query=(*PAGE, "workspace_id")),
}


def _field(name, required):
    kind: Any = str
    options: dict[str, Any] = {}
    default: Any = ... if required else None
    if name in {"id", "workspace_id", "story_id", "parent_id", "user_id"}:
        kind, options = int, {"ge": 1}
    elif name in {"time_in_minutes", "time_estimate_in_minutes", "price"}:
        kind, options = int, {"ge": 0}
    elif name == "percentage_complete":
        kind, options = int, {"ge": 0, "le": 100}
    elif name in {"billable", "budgeted", "archived"}:
        kind = bool
    elif name == "assignee_ids":
        kind = list[Annotated[int, Field(ge=1)]]
    elif name == "story_type":
        kind = Literal["task", "deliverable", "milestone", "issue"]
    elif name == "priority":
        kind = Literal["low", "normal", "high", "critical"]
    elif name == "access_level":
        kind = Literal["invitation", "open", "admins"]
    elif name == "page":
        kind, default, options = int, 1, {"ge": 1}
    elif name == "per_page":
        kind, default, options = int, 100, {"ge": 1, "le": 200}
    else:
        options = {"min_length": 1, "max_length": 999 if name == "description" else 20000}
    if name in {"start_date", "due_date", "date_performed", "updated_after"}:
        options["json_schema_extra"] = {"format": "date-time" if name == "updated_after" else "date"}
    return (kind if required or name in {"page", "per_page"} else Optional[kind],
            Field(default, title=name.replace("_", " ").title(), **options))


def _config(name, op):
    fields = {k: _field(k, k in op.required) for k in dict.fromkeys((*op.required, *op.query, *op.body))}
    if name == "create_project":
        fields["budgeted"] = (bool, Field(False, description="For a budgeted project, also supply its price in base currency units."))
    fields["operation"] = (Literal[name], Field(name, json_schema_extra={
        "ui:hidden": True, "x-display-name": op.label,
        "x-category": {"workspaces": "Projects", "stories": "Tasks", "time_entries": "Time Entries", "posts": "Activity", "users": "Account", "expenses": "Expenses"}[op.resource]}))
    return create_model("KantataOX" + ''.join(x.title() for x in name.split('_')) + "Config", __base__=_Input, **fields)


CONFIG_MODELS = {name: _config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
TRIGGERS = {
    "on_new_or_updated_project": ("workspaces", "/workspaces", "Project"),
    "on_new_or_updated_task": ("stories", "/stories", "Task"),
    "on_new_or_updated_time_entry": ("time_entries", "/time_entries", "Time Entry"),
    "on_new_or_updated_post": ("posts", "/posts", "Activity Post"),
}


def _trigger(name, resource, path, label):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New or Updated " + label, "x-category": "Triggers"}))}
    if resource != "workspaces":
        fields["workspace_id"] = _field("workspace_id", False)
    return create_model("KantataOX" + ''.join(x.title() for x in name.split('_')) + "Config", __base__=PollTriggerConfigBase, **fields)


TRIGGER_MODELS = {name: _trigger(name, *spec) for name, spec in TRIGGERS.items()}
globals().update({model.__name__: model for model in TRIGGER_MODELS.values()})
KantataOXConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + tuple(TRIGGER_MODELS.values())], Field(discriminator="operation")]


class KantataOXNodeConfig(NodeConfig[KantataOXConfig, KantataOXTokenCredential]):
    pass


def records(data, resource):
    """Use canonical result references, never associated objects in the same index."""
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("Kantata OX response is missing its results array")
    rows = []
    for ref in data["results"]:
        if not isinstance(ref, dict) or ref.get("key") != resource or not isinstance(ref.get("id"), str):
            raise ValueError("Kantata OX returned an invalid result reference")
        index = data.get(resource)
        if not isinstance(index, dict) or not isinstance(index.get(ref["id"]), dict):
            raise ValueError("Kantata OX result reference is absent from its resource index")
        rows.append({**index[ref["id"]], "id": ref["id"]})
    return rows


class KantataOXNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-kantataox"
    connection_evidence = ConnectionEvidence(noun="Kantata OX user", identity_operation="get_me", identity_keys=("full_name", "email_address", "id"))

    @classmethod
    def get_config_model(cls):
        return KantataOXNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Kantata OX personal token")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        expected_status = 204 if method == "DELETE" else 200
        if response.status_code != expected_status:
            message = "Kantata OX request failed"
            try:
                errors = response.json().get("errors", [])
                details = [e["message"] for e in errors if isinstance(e, dict) and isinstance(e.get("message"), str)]
                if details:
                    message = "; ".join(details).replace(credential.api_token, "[redacted]")[:1000]
            except (ValueError, AttributeError, TypeError):
                pass
            message = message.replace(credential.api_token, "[redacted]")
            raise ValueError(f"Kantata OX HTTP {response.status_code}: {message}")
        if response.status_code == 204 or not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict) or ("errors" in data and data["errors"]):
            raise ValueError("Kantata OX did not confirm the request")
        return data

    async def _poll(self, config):
        resource, path, _ = TRIGGERS[config.operation]
        items = []
        for page in range(1, 21):
            params = {"page": page, "per_page": 200, "order": "newest_reply_at:desc" if resource == "posts" else "updated_at:desc"}
            if getattr(config, "workspace_id", None) is not None:
                params["workspace_id"] = config.workspace_id
            data = await self._request("GET", path, params=params)
            rows = records(data, resource)
            items.extend(rows)
            count = data.get("count")
            if type(count) is not int or count < 0:
                raise ValueError("Kantata OX list response is missing its total count")
            if page * 200 >= count:
                break
            if not rows:
                raise ValueError("Kantata OX pagination stopped before the reported count")
        else:
            raise ValueError("More than 4,000 records in this trigger scope; narrow the watched project")
        fresh = await self._filter_unseen(items, lambda row: row["id"] + ":" + hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest())
        return {"items": fresh, "new_item_count": len(fresh), "resource": resource}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_item_count")) if config.get("operation") in TRIGGERS else True

    @classmethod
    def resolve_agent_event(cls, output):
        items = output.get("items")
        resource = output.get("resource")
        if resource not in {"workspaces", "stories", "time_entries", "posts"} or not isinstance(items, list):
            return super().resolve_agent_event(output)
        if not items:
            return None
        lines = []
        for item in items[:10]:
            identifier = item["id"]
            if resource in {"workspaces", "stories"}:
                content = item.get("title") or "Untitled"
                who = item.get("creator_id")
            elif resource == "posts":
                content = item.get("message") or "Activity post"
                who = item.get("user_id")
            else:
                content = 'Time entry'
                if item.get('time_in_minutes') is not None:
                    content += f": {item['time_in_minutes']} minutes"
                if item.get('date_performed'):
                    content += f" on {item['date_performed']}"
                if item.get('notes'):
                    content += ' — ' + str(item['notes'])
                who = item.get("user_id")
            project = item.get("workspace_id") if resource != "workspaces" else identifier
            details = [f"id {identifier}"]
            if project is not None:
                details.append(f"project {project}")
            if who is not None:
                details.append(f"user {who}")
            if resource in {"posts", "time_entries"} and item.get("story_id"):
                details.append(f"task {item['story_id']}")
            if item.get("updated_at"):
                details.append(f"updated {item['updated_at']}")
            lines.append(f"- {str(content)[:500]} ({'; '.join(details)})")
        return {"text": (f"Kantata OX: {len(items)} new or updated {resource}:\n" + "\n".join(lines))[:4000],
                "conversation_key": None, "title": "Kantata OX updates"}

    async def execute(self, inputs):
        config = self.config.config
        if config.operation in TRIGGERS:
            return await self._poll(config)
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path.replace("{id}", str(values.get("id", "")))
        params = {key: values[key] for key in op.query if key in values}
        body = {op.envelope: {key: values[key] for key in op.body if key in values}} if op.envelope else None
        data = await self._request(op.method, path, params=params or None, body=body)
        if op.method == "DELETE":
            return {"deleted_id": str(config.id), "acknowledged": True}
        items = records(data, op.resource)
        if config.operation.startswith(("get_", "create_", "update_")):
            if len(items) != 1:
                raise ValueError("Kantata OX did not return exactly one canonical record")
            if "id" in values and items[0]["id"] != str(values["id"]):
                raise ValueError("Kantata OX returned a different record")
            return {"data": items[0]}
        count = data.get("count")
        if type(count) is not int or count < 0:
            raise ValueError("Kantata OX list response is missing its total count")
        return {"items": items, "count": count, "next_page": config.page + 1 if config.page * config.per_page < count else None}
