"""Manifestly Checklists v2. Contract: https://api.manifest.ly/api/v2/openapi.json.

API keys act as an integration identity, not as the person connecting it.
Webhook payloads/signing: https://help.manifest.ly/article/55-using-checklist-webhooks-for-automations
Header format: https://www.manifest.ly/api
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.manifest.ly/api/v2"
HOOK_DOCS = "https://help.manifest.ly/article/55-using-checklist-webhooks-for-automations"


class ManifestlyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Manifestly API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.manifest.ly/api",
        "x-credential-instructions": "An account admin creates an API key in Account Settings → Integrations and selects its department. Paste that key here. Calls act as the integration identity. For webhook triggers, also paste the separate signing secret from Workflow Hooks → Generate signing secret. Rotating that secret requires updating this connection.",
    })
    credential_type: Literal["manifestly_api_key"] = Field("manifestly_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})
    webhook_signing_secret: Optional[str] = Field(None, title="Webhook Signing Secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "webhook_signing_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        if value is None and info.field_name == "webhook_signing_secret":
            return None
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the secret without whitespace or a Bearer header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def number(title, required=True):
    return (int if required else Optional[int], Field(... if required else None, title=title, gt=0))


def text(title, required=False):
    return (str if required else Optional[str], Field(... if required else None, title=title, min_length=1))


PAGE = {"page": (int, Field(1, ge=1, title="Page")), "per_page": (int, Field(20, ge=1, le=100, title="Results Per Page"))}
RUN = {"run_id": number("Run ID")}
STEP = {**RUN, "run_step_id": number("Run Step ID")}
WORKFLOW = {"workflow_id": number("Workflow ID")}


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    fields: dict
    query: tuple = ()
    body: tuple = ()
    wrapper: Optional[str] = None


OPERATIONS = {
    "list_workflows": Operation("List Workflows", "GET", "/workflows", {**PAGE, "search": text("Search"), "department_id": number("Department ID", False)}, ("page", "per_page", "search", "department_id")),
    "get_workflow": Operation("Get Workflow", "GET", "/workflows/{workflow_id}", WORKFLOW),
    "list_workflow_steps": Operation("List Workflow Steps", "GET", "/workflows/{workflow_id}/steps", {**WORKFLOW, **PAGE}, ("page", "per_page")),
    "list_workflow_fields": Operation("List Workflow Fields", "GET", "/workflows/{workflow_id}/fields", WORKFLOW),
    "list_runs": Operation("List Runs", "GET", "/runs", {**PAGE, "search": text("Search"), "workflow_id": number("Workflow ID", False), "status": (Optional[Literal["closed", "late", "in-progress", "upcoming"]], None)}, ("page", "per_page", "search", "workflow_id", "status")),
    "get_run": Operation("Get Run", "GET", "/runs/{run_id}", RUN),
    "create_run": Operation("Start Run", "POST", "/runs", {"checklist_id": number("Workflow ID"), "title": text("Run Title", True), "external_id": text("External ID"), "notes": text("Notes"), "due_at": text("Due At (ISO 8601)")}, body=("checklist_id", "title", "external_id", "notes", "due_at"), wrapper="run"),
    "update_run": Operation("Update Run", "PUT", "/runs/{run_id}", {**RUN, "title": text("Run Title", True), "due_at": text("Due At (ISO 8601)"), "state": (Optional[Literal["completed", "started"]], None)}, body=("title", "due_at", "state"), wrapper="run"),
    "close_run": Operation("Close Run", "DELETE", "/runs/{run_id}", RUN),
    "get_run_summary": Operation("Get Run Progress", "GET", "/runs/{run_id}/summary", RUN),
    "list_run_steps": Operation("List Run Steps", "GET", "/runs/{run_id}/run_steps", {**RUN, **PAGE, "status": (Optional[Literal["completed", "not_completed"]], None)}, ("page", "per_page", "status")),
    "get_run_step": Operation("Get Run Step", "GET", "/runs/{run_id}/run_steps/{run_step_id}", {**STEP, "page": (int, Field(1, ge=1)), "per_page": (int, Field(20, ge=1, le=50))}, ("page", "per_page")),
    "change_run_step_state": Operation("Change Run Step State", "POST", "/runs/{run_id}/run_steps/{run_step_id}", {**STEP, "action": (Literal["complete", "uncomplete", "skip", "unskip", "start", "stop"], Field(..., title="Action"))}, body=("action",)),
    "assign_run_step": Operation("Assign Run Step", "POST", "/runs/{run_id}/run_steps/{run_step_id}/assign", {**STEP, "assignee_membership_id": number("Assignee Membership ID", False)}, body=("assignee_membership_id",)),
    "create_run_step": Operation("Create Run Step", "POST", "/runs/{run_id}/run_steps", {**RUN, "title": text("Step Title", True), "parent_run_step_id": number("Parent Section ID", False), "due_at": text("Due At (ISO 8601)")}, body=("title", "parent_run_step_id", "due_at")),
    "list_run_step_fields": Operation("List Run Step Fields", "GET", "/runs/{run_id}/run_steps/{run_step_id}/fields", STEP),
    "update_run_step_field": Operation("Set Run Step Field Value", "PUT", "/runs/{run_id}/run_steps/{run_step_id}/fields/{field_id}", {**STEP, "field_id": number("Field ID"), "value": (str, Field(..., title="Value", description="Text value. File, image and signature uploads require the provider's upload endpoint."))}, body=("value",)),
    "list_comments": Operation("List Run Step Comments", "GET", "/runs/{run_id}/run_steps/{run_step_id}/comments", STEP),
    "create_comment": Operation("Add Run Step Comment", "POST", "/runs/{run_id}/run_steps/{run_step_id}/comments", {**STEP, "comment": text("Comment", True)}, body=("comment",)),
    "list_users": Operation("List Users", "GET", "/users", {**PAGE, "search": text("Search"), "email": text("Email")}, ("page", "per_page", "search", "email")),
    "list_departments": Operation("List Departments", "GET", "/departments", {**PAGE, "search": text("Search")}, ("page", "per_page", "search")),
}


def _make_model(name, spec):
    return create_model("Manifestly" + "".join(x.title() for x in name.split("_")) + "Config", __base__=_Input, __module__=__name__,
        operation=(Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": spec.label})),
        **spec.fields)


CONFIG_MODELS = {name: _make_model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class ManifestlyOnRunEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_run_event"] = Field("on_run_event", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Run Started, Completed or Late"})
    event: Literal["started", "completed", "late"] = Field("completed", title="Run Event")
    hookable: Literal["checklist", "run"] = Field("checklist", title="Watch Workflow or Run")
    hookable_id: int = Field(..., gt=0, title="Workflow or Run ID")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True, "ui:copyable": True})


class ManifestlyOnStepEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_step_event"] = Field("on_step_event", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Step Completed, Skipped or Late"})
    event: Literal["step_completed", "step_skipped", "step_late"] = Field("step_completed", title="Step Event")
    hookable: Literal["step", "run_step"] = Field("step", title="Watch Workflow Step or Run Step")
    hookable_id: int = Field(..., gt=0, title="Step or Run Step ID")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True, "ui:copyable": True})


ManifestlyConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (ManifestlyOnRunEventConfig, ManifestlyOnStepEventConfig)], Field(discriminator="operation")]


class ManifestlyNodeConfig(NodeConfig[ManifestlyConfig, ManifestlyAPIKeyCredential]):
    pass


def _redact(value, credential):
    secrets = [v for k, v in credential.items() if k in {"api_key", "webhook_signing_secret"} and isinstance(v, str) and v]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    return value


class ManifestlyNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-manifestly"
    connection_evidence = ConnectionEvidence(operation="list_workflows", noun="workflows", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return ManifestlyNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = ManifestlyAPIKeyCredential.model_validate(credential).model_dump()
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + credential["api_key"], "Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("Manifestly request could not be completed; inspect writes before retrying") from None
        if response.is_error:
            raise ValueError(_redact(f"Manifestly API {response.status_code}: {response.text}", credential))
        if not response.content:
            return {"acknowledged": True}
        try:
            result = response.json()
        except ValueError:
            raise ValueError("Manifestly returned a non-JSON response") from None
        if not isinstance(result, dict):
            raise ValueError("Manifestly returned an unexpected response envelope")
        return _redact(result, credential)

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Manifestly API key")
        op = self.config.config
        if op.operation in {"on_run_event", "on_step_event"}:
            payload = self.node_data.get("config", {}).get("_triggerPayload") or inputs
            return self.resolve_trigger_payload(payload, op.model_dump())
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        path = spec.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", str(value))
        params = {k: values[k] for k in spec.query if k in values}
        body = {k: values[k] for k in spec.body if k in values}
        if spec.wrapper:
            body = {spec.wrapper: body}
        result = await self._request(self.config.credentials.model_dump(), spec.method, path, params=params or None,
            body=body if spec.method in {"POST", "PUT", "PATCH"} else None)
        await self.emit(result)
        return result

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        parsed = ManifestlyNodeConfig.model_validate({"config": config, "credentials": credential})
        op = parsed.config
        if not isinstance(op, (ManifestlyOnRunEventConfig, ManifestlyOnStepEventConfig)):
            raise ValueError("Choose a Manifestly trigger")
        secret = parsed.credentials.webhook_signing_secret
        if not secret:
            raise ValueError("Paste the account webhook signing secret into the Manifestly connection")
        data = await cls._request(credential, "POST", "/webhooks", body={
            "webhook": {"url": webhook_url, "event": op.event, "signature_version": 2},
            "hookable": op.hookable, "hookable_id": op.hookable_id})
        identifier = data.get("webhook", {}).get("id")
        if type(identifier) is not int or identifier <= 0:
            raise ValueError("Manifestly did not return a webhook ID")
        return {"external_webhook_id": str(identifier), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = config.get("external_webhook_id")
        if not identifier:
            return
        if not str(identifier).isdigit():
            raise ValueError("Invalid Manifestly webhook ID")
        await cls._request(credential, "DELETE", f"/webhooks/{identifier}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {k: config.get(k) for k in ("event", "hookable", "hookable_id")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        if not isinstance(secret, str) or not secret:
            return False
        signature = next((v for k, v in headers.items() if k.lower() == "x-manifestly-signature"), "")
        if not isinstance(signature, str) or not signature.isascii():
            return False
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        headers = payload.get("_webhook", {}).get("headers", {})
        event = next((v for k, v in headers.items() if k.lower() == "x-manifestly-event"), None)
        return event == config.get("event")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"event": config.get("event"), "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output.get("data") if isinstance(output, dict) else None
        if not isinstance(payload, dict) or not payload.get("run_id"):
            return None
        title = payload.get("checklist_run_detailed_name") or payload.get("checklist_run_name") or "Manifestly run"
        step = payload.get("step") or {}
        actor = step.get("completed_by_name") or payload.get("completed_by_name") or payload.get("participants")
        text = f"Manifestly {output.get('event')}: {title}\nWorkflow: {payload.get('workflow_name')}\nPeople: {actor}\nRun ID: {payload['run_id']}\nURL: {payload.get('run_url')}"
        if step:
            text += f"\nStep: {step.get('title')}\nRun step ID: {step.get('run_step_id')}\nData: {step.get('data')}"
        return {"text": text, "title": str(title), "conversation_key": str(payload["run_id"])}
