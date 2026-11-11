"""Dart public API v0: tasks, documents, comments and signed workspace events.

Contract: https://app.dartai.com/api/v0/public/schema/ (version 1.0.0).
Token setup: https://www.dartai.com/features/api-libraries-and-cli
Webhook setup: https://help.dartai.com/en/articles/9024895-webhooks
Each operation makes one provider request. Lists return one page only.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

BASE = "https://app.dartai.com/api/v0/public"
NODE_TYPE = "automation-dart"
FAMILY = "dart_api_token"
DartID = Annotated[str, Field(pattern=r"^[a-zA-Z0-9]{12}$", description="12-character alphanumeric Dart ID, not a title or URL.")]


def picker(field):
    return {"x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True}}


class DartAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Dart API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.dartai.com/",
        "x-credential-instructions": "In Dart, open Settings > Account > API and copy your API token. Paste the token alone, without Bearer. API access requires a Premium or Business plan. NoClick sends it only to app.dartai.com.",
        "x-help-url": "https://www.dartai.com/features/api-libraries-and-cli",
    })
    credential_type: Literal["dart_api_token"] = Field("dart_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token alone, without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(50, ge=1, le=100, description="Results per page. This operation returns one page.")
    offset: int = Field(0, ge=0, description="Initial result index; use next_offset for another page.")


class GetMe(_Input):
    """Check the token and return the authenticated user."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class GetConfig(_Input):
    """Get workspace property names and available values."""
    operation: Literal["get_config"] = Field("get_config", json_schema_extra={"ui:hidden": True})


class ListTasks(_Page):
    """List one task page; implicit filters follow Dart workspace settings."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    title: str | None = None
    dartboard: str | None = Field(None, description="Dartboard title filter.")
    dartboard_id: DartID | None = None
    assignee: str | None = None
    status: str | None = None
    tag: str | None = None
    parent_id: DartID | None = None
    is_completed: bool | None = None
    in_trash: bool | None = None
    no_defaults: bool | None = Field(None, description="Disable Dart's implicit filters and ordering.")


class GetTask(_Input):
    """Get a task by its Dart ID."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task_id: DartID = Field(..., json_schema_extra=picker("task_id"))


class _TaskFields(_Input):
    dartboard: str | None = Field(None, description="Full dartboard title, from get_config.")
    type: str | None = Field(None, description="Task type title, from get_config.")
    status: str | None = Field(None, description="Task status title, from get_config.")
    description: str | None = Field(None, description="Markdown description. Omit to keep the existing description.")
    parentId: DartID | None = None
    assignee: str | None = Field(None, description="Single-assignee workspace: name or email.")
    assignees: list[str] | None = Field(None, description="Multiple-assignee workspace: replaces assignees; [] clears them.")
    reviewer: str | None = None
    reviewers: list[str] | None = None
    tags: list[str] | None = Field(None, description="Replaces all tags; [] clears them. Unknown titles create tags.")
    priority: Literal["Critical", "High", "Medium", "Low"] | None = None
    startAt: str | None = Field(None, description="ISO start date, YYYY-MM-DD.")
    dueAt: str | None = Field(None, description="ISO due date, YYYY-MM-DD.")
    size: str | int | None = None


class CreateTask(_TaskFields):
    """Create a task; omitted fields use Dart's defaults."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1)


class UpdateTask(_TaskFields):
    """Update supplied task properties. Omitted properties are unchanged."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    task_id: DartID = Field(..., json_schema_extra=picker("task_id"))
    title: str | None = None


class DeleteTask(GetTask):
    """Move a task to recoverable trash."""
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"ui:hidden": True})


class MoveTask(GetTask):
    """Reorder a task in its dartboard."""
    operation: Literal["move_task"] = Field("move_task", json_schema_extra={"ui:hidden": True})
    position: Literal["before", "after", "first", "last"] = "last"
    relative_task_id: DartID | None = Field(None, description="Required for before or after positions.", json_schema_extra=picker("task_id"))


class ListDocs(_Page):
    """List one page of documents with optional title, folder and text filters."""
    operation: Literal["list_docs"] = Field("list_docs", json_schema_extra={"ui:hidden": True})
    title: str | None = None
    folder: str | None = None
    folder_id: DartID | None = None
    text: str | None = None
    in_trash: bool | None = None
    no_defaults: bool | None = None


class GetDoc(_Input):
    """Get a document by its Dart ID."""
    operation: Literal["get_doc"] = Field("get_doc", json_schema_extra={"ui:hidden": True})
    doc_id: DartID = Field(..., json_schema_extra=picker("doc_id"))


class CreateDoc(_Input):
    """Create a document with a title and optional markdown content."""
    operation: Literal["create_doc"] = Field("create_doc", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1)
    folder: str | None = Field(None, description="Full folder title, from get_config.")
    text: str | None = None


class UpdateDoc(GetDoc):
    """Update supplied document properties. Omitted properties are unchanged."""
    operation: Literal["update_doc"] = Field("update_doc", json_schema_extra={"ui:hidden": True})
    title: str | None = None
    folder: str | None = None
    text: str | None = Field(None, description="Full markdown content. Omit to keep the existing content.")


class DeleteDoc(GetDoc):
    """Move a document to recoverable trash."""
    operation: Literal["delete_doc"] = Field("delete_doc", json_schema_extra={"ui:hidden": True})


class ListComments(_Page):
    """List one page of comments for a required task ID."""
    operation: Literal["list_comments"] = Field("list_comments", json_schema_extra={"ui:hidden": True})
    task_id: DartID = Field(..., json_schema_extra=picker("task_id"))
    author: str | None = None
    text: str | None = None
    parent_id: DartID | None = None


class AddComment(GetTask):
    """Add a markdown comment or reply to a task."""
    operation: Literal["add_comment"] = Field("add_comment", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1)
    parent_id: DartID | None = None


class GetDartboard(_Input):
    """Get a dartboard and its tasks by ID."""
    operation: Literal["get_dartboard"] = Field("get_dartboard", json_schema_extra={"ui:hidden": True})
    dartboard_id: DartID


class GetFolder(_Input):
    """Get a folder and its documents by ID."""
    operation: Literal["get_folder"] = Field("get_folder", json_schema_extra={"ui:hidden": True})
    folder_id: DartID


class GetView(_Input):
    """Get a saved view by ID."""
    operation: Literal["get_view"] = Field("get_view", json_schema_extra={"ui:hidden": True})
    view_id: DartID


# Dart's own MCP server: agents get its tools through a person's Dart sign-in.
DartMcpCredential = mcp_credential("dart", "https://mcp.dartai.com/mcp", app="Dart")
DartCredential = Union[DartAPITokenCredential, DartMcpCredential]


DartConfig = Annotated[Union[GetMe, GetConfig, ListTasks, GetTask, CreateTask, UpdateTask,
    DeleteTask, MoveTask, ListDocs, GetDoc, CreateDoc, UpdateDoc, DeleteDoc,
    ListComments, AddComment, GetDartboard, GetFolder, GetView, OnEvent], Field(discriminator="operation")]


class DartFullConfig(NodeConfig[DartConfig, DartCredential]):
    pass


# Each entry is one operation in the pinned provider contract.
ROUTES = {
    "get_me": ("GET", "/me"), "get_config": ("GET", "/config"),
    "list_tasks": ("GET", "/tasks/list"), "get_task": ("GET", "/tasks/{id}"),
    "create_task": ("POST", "/tasks"), "update_task": ("PUT", "/tasks/{id}"),
    "delete_task": ("DELETE", "/tasks/{id}"), "move_task": ("POST", "/tasks/{id}/move"),
    "list_docs": ("GET", "/docs/list"), "get_doc": ("GET", "/docs/{id}"),
    "create_doc": ("POST", "/docs"), "update_doc": ("PUT", "/docs/{id}"),
    "delete_doc": ("DELETE", "/docs/{id}"), "list_comments": ("GET", "/comments/list"),
    "add_comment": ("POST", "/comments"), "get_dartboard": ("GET", "/dartboards/{id}"),
    "get_folder": ("GET", "/folders/{id}"), "get_view": ("GET", "/views/{id}"),
}


class DartNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-dart"
    credential_provider_labels = {"dart": "Dart Account"}
    connection_evidence = ConnectionEvidence(noun="tasks", operation="list_tasks", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return DartFullConfig

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        trigger = OnEvent.model_validate(config)
        data = await cls._request(DartAPITokenCredential.model_validate(credential), "POST", "/webhooks",
            body={"item": {"enabled": True, "title": f"NoClick {node_id}", "url": webhook_url,
                "eventKinds": [trigger.event_type]}})
        item = data.get("item")
        if not isinstance(item, dict) or not re.fullmatch(r"[a-zA-Z0-9]{12}", str(item.get("id", ""))):
            raise ValueError("Dart did not return a webhook ID")
        return {"external_webhook_id": item["id"], "signing_secret": trigger.webhook_secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = (config or {}).get("external_webhook_id")
        if not webhook_id:
            return
        if not re.fullmatch(r"[a-zA-Z0-9]{12}", str(webhook_id)):
            raise ValueError("Invalid Dart webhook ID")
        await cls._request(DartAPITokenCredential.model_validate(credential), "DELETE", f"/webhooks/{webhook_id}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        config = config or {}
        return {"event_type": config.get("event_type", "task.created"),
            "secret_hash": hashlib.sha256(str(config.get("webhook_secret", "")).encode()).hexdigest()}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Dart's official SDK: dart/webhook.py and dart/server.py.
        secret = (config or {}).get("signing_secret") or (config or {}).get("webhook_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "dart-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return bool(re.fullmatch(r"[a-fA-F0-9]{64}", signature)) and hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (isinstance(payload, dict) and payload.get("type") in EVENTS
            and payload.get("type") == (config or {}).get("event_type", "task.created")
            and isinstance(payload.get("data"), dict))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("type") not in EVENTS:
            return super().resolve_agent_event(output)
        kind = output["type"]
        data = output.get("data")
        if not isinstance(data, dict):
            return None
        # OpenAPI uses direct data on create/delete; the official SDK server
        # documents data.model on those deliveries too. Accept both contracts.
        record = data["model"] if "model" in data else data
        if not isinstance(record, dict) or not record.get("id"):
            return None
        resource_id = record["id"]
        resource = kind.split(".")[0]
        title = record.get("text") if resource == "comment" else record.get("title")
        title = str(title or resource_id)[:200]
        lines = [f"Dart {kind}: {title}", f"{resource}_id: {resource_id}"]
        if resource == "task":
            actor = record.get("createdBy") if kind == "task.created" else record.get("updatedBy")
            facts = [("By", actor), ("Dartboard", record.get("dartboard")), ("Status", record.get("status")),
                ("Description", record.get("description"))]
            if kind == "task.status_updated":
                facts += [("Previous status", data.get("oldStatus")), ("New status", data.get("newStatus"))]
            elif kind == "task.assignees_updated":
                facts += [("Previous assignees", data.get("oldAssignees")), ("New assignees", data.get("newAssignees"))]
            conversation = resource_id
        elif resource == "doc":
            facts = [("Folder", record.get("folder")), ("Content", record.get("text"))]
            conversation = resource_id
        else:
            facts = [("By", record.get("author")), ("Task ID", record.get("taskId")), ("Comment", record.get("text"))]
            conversation = record.get("taskId") or resource_id
        facts.append(("URL", record.get("htmlUrl")))
        lines += [f"{label}: {str(value)[:2000]}" for label, value in facts if value is not None and value != ""]
        return {"text": "\n".join(lines), "conversation_key": f"dart:{resource if resource != 'comment' else 'task'}:{conversation}",
            "title": title}

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.status_code != 200:
            detail = ""
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("detail") or error.get("message") or error.get("errors") or ""
            except ValueError:
                pass
            detail = str(detail).replace(credential.api_token, "[redacted]")[:1000]
            raise ValueError(f"Dart returned HTTP {response.status_code}" + (": " + detail if detail else ""))
        data = response.json()
        if not isinstance(data, dict) or "errors" in data or "error" in data:
            raise ValueError("Dart returned an invalid or error response")
        return data

    @staticmethod
    def _next_offset(data, path, offset):
        link = data.get("next")
        if link is None:
            return None
        if not isinstance(link, str):
            raise ValueError("Dart returned an invalid next page")
        parsed = urlsplit(link)
        expected = urlsplit(BASE + path)
        if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path):
            raise ValueError("Dart returned a next page outside the selected list")
        values = parse_qs(parsed.query).get("offset", [])
        if len(values) != 1 or not re.fullmatch(r"[0-9]+", values[0]) or int(values[0]) <= offset:
            raise ValueError("Dart returned a non-advancing page")
        return int(values[0])

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Dart API token")
        if isinstance(config, OnEvent):
            if not self.filter_trigger_payload(inputs, config.model_dump()):
                raise ValueError("Expected the selected Dart event")
            return inputs
        method, template = ROUTES[config.operation]
        args = config.model_dump(exclude_none=True, exclude={"operation"})
        path, body, params = template, None, None
        selected_id = None
        if "{id}" in path:
            resource = next(key for key in ("task_id", "doc_id", "dartboard_id", "folder_id", "view_id") if key in args)
            selected_id = args.pop(resource)
            path = path.replace("{id}", selected_id)
        if method == "GET":
            params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in args.items()}
        elif config.operation == "move_task":
            if config.position in {"before", "after"} and not config.relative_task_id:
                raise ValueError("Choose a relative task for before or after")
            key = "beforeTaskId" if config.position in {"before", "first"} else "afterTaskId"
            body = {key: config.relative_task_id if config.position in {"before", "after"} else None}
        elif config.operation == "add_comment":
            body = {"item": {"taskId": args.pop("task_id"), "text": args.pop("text"),
                **({"parentId": args["parent_id"]} if "parent_id" in args else {})}}
        elif method in {"POST", "PUT"}:
            if method == "PUT":
                if not args:
                    raise ValueError("Supply at least one property to update")
                args["id"] = selected_id
            body = {"item": args}
        data = await self._request(credential, method, path, params=params, body=body)
        if config.operation.startswith("list_"):
            if not isinstance(data.get("results"), list) or type(data.get("count")) is not int:
                raise ValueError("Dart returned an invalid list page")
            if any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in data["results"]):
                raise ValueError("Dart returned an invalid list item")
            next_offset = self._next_offset(data, path, config.offset)
            return {"status": "success", **data, "next_offset": next_offset, "has_more": next_offset is not None}
        if config.operation == "get_me":
            if data.get("isLoggedIn") is not True or not isinstance(data.get("user"), dict):
                raise ValueError("Dart did not confirm an authenticated user")
            return {"status": "success", "user": data["user"], **data["user"]}
        if config.operation == "get_config":
            if not isinstance(data.get("user"), dict) or not isinstance(data.get("dartboards"), list):
                raise ValueError("Dart returned an invalid workspace configuration")
            return {"status": "success", "data": data}
        item = data.get("item")
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Dart returned an invalid resource")
        if selected_id is not None and item["id"] != selected_id:
            raise ValueError("Dart returned a different resource ID")
        return {"status": "success", "item": item}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, *, page_token=None, search=None):
        listing = {"task_id": "list_tasks", "doc_id": "list_docs"}.get(field_name)
        if listing is None:
            raise ValueError("Unknown Dart choice field")
        if page_token is not None and not re.fullmatch(r"[0-9]+", str(page_token)):
            raise ValueError("Use the returned Dart page token")
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node(node_id="dart-options", node_type=NODE_TYPE,
            node_data={"config": {"operation": listing, "offset": int(page_token or 0), **({"title": search} if search else {})},
                "credentials": credential_data})
        result = await node.execute({})
        return {"options": [{"value": row["id"], "label": row.get("title") or row["id"]} for row in result["results"]],
            "next_page_token": str(result["next_offset"]) if result["has_more"] else None}
