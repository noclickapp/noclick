"""GSMTasks API 2.11.10: dispatch tasks and receive signed task events.

Contract: https://api.gsmtasks.com/docs/schema/?format=json
Authentication, versioning and webhook signing are documented in its tag descriptions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.gsmtasks.com"
VERSION = "2.11.10"
DOCS = "https://api.gsmtasks.com/docs/"


class GSMTasksAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="GSMTasks API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS + "#tag/authentication",
            "x-credential-instructions": "In GSMTasks, open Settings → API keys, create a key, and copy it when shown. Paste the key alone. NoClick sends it to api.gsmtasks.com with the Token prefix."})
    credential_type: Literal["gsmtasks_api_key"] = Field("gsmtasks_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def check_key(cls, value):
        value = value.strip()
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the API key alone, without the Token prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def text(title, required=False, **kwargs):
    return (str if required else str | None, Field(... if required else None, title=title, **kwargs))


def identifier(title):
    return (UUID, Field(..., title=title))


PAGE = {"cursor": text("Cursor", description="Opaque pagination cursor returned by GSMTasks."),
        "page_size": (int, Field(100, ge=1, le=1000, title="Page Size"))}
SEARCH = {**PAGE, "search": text("Search")}
TASK_ID = {"task_id": identifier("Task ID")}
ACCOUNT = {"account": text("Account URL", required=True, description="The account's full API resource URL.")}
TASK_FIELDS = {
    "reference": text("Reference", max_length=100),
    "external_id": text("External ID", max_length=100),
    "description": text("Description"),
    "category": (Literal["assignment", "pick_up", "drop_off", "warehouse"] | None, Field(None, title="Category")),
    "assignee": text("Assignee URL"),
    "complete_after": (datetime | None, Field(None, title="Complete After")),
    "complete_before": (datetime | None, Field(None, title="Complete Before")),
    "scheduled_time": (datetime | None, Field(None, title="Scheduled Time")),
    "address": (dict[str, Any] | None, Field(None, title="Address", description="GSMTasks nested address, for example {raw_address: ...}.")),
    "contact": (dict[str, Any] | None, Field(None, title="Contact", description="Nested name, company, phones and emails.")),
    "priority": (int | None, Field(None, ge=-2147483648, le=2147483647, title="Priority")),
}


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    fields: dict
    query: tuple = ()
    body: tuple = ()


OPERATIONS = {
    "list_accounts": Operation("List Accounts", "GET", "/accounts/", SEARCH, tuple(SEARCH)),
    "get_account": Operation("Get Account", "GET", "/accounts/{account_id}/", {"account_id": identifier("Account ID")}),
    "list_users": Operation("List Workers", "GET", "/users/", SEARCH, tuple(SEARCH)),
    "get_user": Operation("Get Worker", "GET", "/users/{user_id}/", {"user_id": identifier("Worker ID")}),
    "list_tasks": Operation("List Tasks", "GET", "/tasks/", {**SEARCH,
        "account": text("Account ID"), "assignee": text("Assignee ID"),
        "state": (Literal["draft", "scheduled", "unassigned", "assigned", "accepted", "transit", "active", "completed", "failed", "cancelled"] | None, Field(None, title="State")),
        "ordering": text("Order By", description="For example -updated_at."),
        "updated_at__gte": (datetime | None, Field(None, title="Updated Since"))},
        (*SEARCH, "account", "assignee", "state", "ordering", "updated_at__gte")),
    "get_task": Operation("Get Task", "GET", "/tasks/{task_id}/", TASK_ID),
    "create_task": Operation("Create Task", "POST", "/tasks/", {**ACCOUNT, **TASK_FIELDS}, body=("account", *TASK_FIELDS)),
    "update_task": Operation("Update Task", "PATCH", "/tasks/{task_id}/", {**TASK_ID, **TASK_FIELDS}, body=tuple(TASK_FIELDS)),
    "assign_task": Operation("Assign Task", "POST", "/tasks/{task_id}/assign/", {**TASK_ID,
        "assignee": text("Assignee URL", required=True), "notes": text("Notes")}, body=("assignee", "notes")),
    "list_task_events": Operation("List Task Events", "GET", "/tasks/{task_id}/events/", {**TASK_ID, **PAGE}, tuple(PAGE)),
    "list_task_documents": Operation("List Task Documents", "GET", "/tasks/{task_id}/documents/", {**TASK_ID, **PAGE}, tuple(PAGE)),
    "list_task_signatures": Operation("List Task Signatures", "GET", "/tasks/{task_id}/signatures/", {**TASK_ID, **PAGE}, tuple(PAGE)),
    "list_routes": Operation("List Routes", "GET", "/routes/", {**SEARCH, "account": text("Account ID")}, (*SEARCH, "account")),
    "get_route": Operation("Get Route", "GET", "/routes/{route_id}/", {"route_id": identifier("Route ID")}),
    "list_contact_addresses": Operation("List Contact Addresses", "GET", "/contact_addresses/", {**SEARCH, "account": text("Account ID")}, (*SEARCH, "account")),
}
for action, label in [("unassign", "Unassign"), ("accept", "Accept"), ("transit", "Start Travel for"),
                      ("activate", "Start Work on"), ("complete", "Complete"), ("fail", "Fail"), ("cancel", "Cancel")]:
    OPERATIONS[action + "_task"] = Operation(label + " Task", "POST", "/tasks/{task_id}/" + action + "/",
        {**TASK_ID, "notes": text("Notes")}, body=("notes",))

CONFIG_MODELS = {}
for name, spec in OPERATIONS.items():
    model = create_model("GSMTasks" + "".join(s.title() for s in name.split("_")) + "Config",
        __base__=Input, __module__=__name__,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={"ui:hidden": True,
            "x-display-name": spec.label, "x-is-trigger": False})), **spec.fields)
    CONFIG_MODELS[name] = model
    globals()[model.__name__] = model


class GSMTasksOnTaskEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_task_event"] = Field("on_task_event", title="On Task Event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Task Event"})
    account: str = Field(..., title="Account URL", description="Account's full API resource URL.")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


GSMTasksOperation = Annotated[Union[tuple(CONFIG_MODELS.values()) + (GSMTasksOnTaskEventConfig,)], Field(discriminator="operation")]


class GSMTasksNodeConfig(NodeConfig[GSMTasksOperation, GSMTasksAPIKeyCredential]):
    pass


class GSMTasksNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-gsmtasks"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="accounts", label_keys=("name", "id", "url"))

    @classmethod
    def get_config_model(cls):
        return GSMTasksNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        headers = {"Authorization": "Token " + credential["api_key"],
                   "Accept": "application/json; version=" + VERSION}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params, json=body)
        if response.is_error:
            # Do not expose a token if the server echoes headers in its error.
            detail = response.text.replace(credential["api_key"], "[redacted]")[:2000]
            raise ValueError(f"GSMTasks API error {response.status_code}: {detail}")
        data = response.json() if response.content else None
        return {"data": data, "pagination_link": response.headers.get("Link")}

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a GSMTasks API key")
        op = self.config.config
        if isinstance(op, GSMTasksOnTaskEventConfig):
            return {"status": "success", "operation": op.operation, "data": inputs}
        spec = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {k: values[k] for k in spec.query if k in values}
        body = {k: values[k] for k in spec.body if k in values} if spec.method != "GET" else None
        result = await self._request(self.config.credentials.model_dump(), spec.method, path, params=params, body=body)
        return {"status": "success", "operation": op.operation, **result}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        account = (config or {}).get("account")
        if not account:
            raise ValueError("Choose a GSMTasks account URL")
        result = await cls._request(credential, "POST", "/webhooks/", body={
            "account": account, "name": "NoClick " + str(node_id)[:80], "target": webhook_url,
            "version": VERSION, "task_events": True, "document_events": False,
            "signature_events": False, "review_events": False, "form_response_events": False})
        data = result["data"]
        if not isinstance(data, dict) or not data.get("id") or not data.get("shared_secret"):
            raise ValueError("GSMTasks did not return the webhook ID and shared secret; inspect webhooks before retrying")
        identifier = str(UUID(str(data["id"])))
        # Use the documented activation action instead of assuming that a new
        # webhook is already delivering.
        try:
            await cls._request(credential, "POST", "/webhooks/" + identifier + "/active/")
        except Exception:
            await cls._request(credential, "DELETE", "/webhooks/" + identifier + "/")
            raise
        return {"external_webhook_id": identifier, "signing_secret": data["shared_secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if identifier:
            identifier = str(UUID(str(identifier)))
            await cls._request(credential, "DELETE", "/webhooks/" + identifier + "/")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"account": (config or {}).get("account")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-gsmtasks-hmac-sha256"), "")
        if not secret or not isinstance(signature, str):
            return False
        expected = base64.b64encode(hmac.new(str(secret).encode(), body, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(expected.encode(), signature.encode())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        # Only task events have the documented event + inlined task shape.
        return isinstance(payload.get("task"), dict) and payload.get("event") in {
            "create", "assign", "unassign", "reject", "restart", "accept", "unaccept", "transit",
            "activate", "complete", "fail", "cancel", "assignee_near", "assignee_away", "updated"}

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output if "task" in output else output.get("data")
        if not isinstance(payload, dict) or not isinstance(payload.get("task"), dict):
            return super().resolve_agent_event(output)
        task = payload["task"]
        task_url = task.get("url")
        if not task_url:
            return super().resolve_agent_event(output)
        task_id = task_url.rstrip("/").rsplit("/", 1)[-1]
        label = task.get("reference") or task_id
        text = f"GSMTasks task {payload.get('event')}: {label} ({task.get('state')})."
        text += f"\nAccount: {payload.get('account')}\nWorker: {payload.get('user')}\nTask: {task_url}"
        address = task.get("address") or {}
        if address.get("formatted_address") or address.get("raw_address"):
            text += "\nAddress: " + str(address.get("formatted_address") or address.get("raw_address"))
        if task.get("description"):
            text += "\n" + str(task["description"])
        if payload.get("notes"):
            text += "\nNotes: " + str(payload["notes"])
        text += f"\nTo act, use get_task or update_task with task_id={task_id}."
        return {"text": text, "title": f"Task {label}", "conversation_key": task_id}
