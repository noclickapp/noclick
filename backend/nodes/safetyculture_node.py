"""SafetyCulture (now Mitti) API v1.371.1.

Contract: https://developer.mitti.com/openapi/safetyculture-api.json
Host/rebrand: https://developer.mitti.com/docs/mitti-apps-guide
Each operation makes one API request. Lists return one page and provider paging
metadata unchanged; writes report the API acknowledgement, not a readback.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.mitti.com"
CREDENTIAL_TYPE = "safetyculture_api_token"


class SafetyCultureAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="SafetyCulture API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.mitti.com/reference/authentication",
            "x-credential-instructions": "SafetyCulture is now Mitti. In your web app, open My Profile, Settings, API tokens and generate a user API token, or use an existing service user API token. Paste the token alone. Requests run with the token owner's permissions and access. Connection verification requires Platform management: Groups permission. User tokens expire after 30 days of inactivity. NoClick sends your token only to api.mitti.com.",
        })
    credential_type: Literal["safetyculture_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API token")
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token alone without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("template_id", "inspection_id", "action_id", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if value is None:
            return None
        if not value or value.strip() != value or len(value) > 256 or any(c in value for c in "/\\?#%") or any(ord(c) < 33 for c in value) or value in {".", ".."}:
            raise ValueError("Use a single provider resource ID")
        return value


def _op(name):
    return Field(name, json_schema_extra={"ui:hidden": True})


class ListGroups(_Input):
    """Read groups and organizations belonging to the token owner."""
    operation: Literal["list_groups"] = _op("list_groups")


class _Search(_Input):
    limit: int = Field(100, ge=1, le=1000, description="One page only. Compare count and total; advance modified_after to continue. Equal timestamps may overlap: deduplicate IDs.")
    order: Literal["asc", "desc"] = "asc"
    modified_after: AwareDatetime | None = None
    modified_before: AwareDatetime | None = None
    archived: Literal["false", "true", "both"] = "false"
    owner: Literal["all", "me", "other"] = "all"


class SearchInspections(_Search):
    operation: Literal["search_inspections"] = _op("search_inspections")
    completed: Literal["both", "false", "true"] = "both"
    template: list[str] | None = Field(None, max_length=100, description="Template IDs. Sent as repeated query parameters.")


class SearchTemplates(_Search):
    operation: Literal["search_templates"] = _op("search_templates")


class GetTemplate(_Input):
    operation: Literal["get_template"] = _op("get_template")
    template_id: str
    locale: str | None = Field(None, max_length=40)


class GetInspection(_Input):
    operation: Literal["get_inspection"] = _op("get_inspection")
    inspection_id: str


class CreateInspection(_Input):
    """Create an inspection from a template without pre-filled answers."""
    operation: Literal["create_inspection"] = _op("create_inspection")
    template_id: str


class CompleteInspection(_Input):
    operation: Literal["complete_inspection"] = _op("complete_inspection")
    inspection_id: str


class ListActions(_Input):
    operation: Literal["list_actions"] = _op("list_actions")
    page_size: int = Field(100, ge=1, le=100)
    page_token: str | None = Field(None, max_length=4096, description="Use next_page_token from the previous response with the same page size.")


class GetAction(_Input):
    operation: Literal["get_action"] = _op("get_action")
    action_id: str


class CreateAction(_Input):
    operation: Literal["create_action"] = _op("create_action")
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=30000)
    due_at: AwareDatetime | None = None
    site_id: str | None = Field(None, max_length=256)
    inspection_id: str | None = None
    priority_id: str | None = Field(None, max_length=256)
    status_id: str | None = Field(None, max_length=256)

    @field_validator("inspection_id")
    @classmethod
    def optional_inspection(cls, value):
        return None if value is None else _Input.identifier(value)


class _ActionUpdate(_Input):
    action_id: str
    modified_at: AwareDatetime | None = None


class UpdateActionTitle(_ActionUpdate):
    operation: Literal["update_action_title"] = _op("update_action_title")
    title: str = Field(..., min_length=1, max_length=255)


class UpdateActionDescription(_ActionUpdate):
    operation: Literal["update_action_description"] = _op("update_action_description")
    description: str = Field(..., min_length=1, max_length=30000)


class UpdateActionStatus(_ActionUpdate):
    operation: Literal["update_action_status"] = _op("update_action_status")
    status_id: str = Field(..., min_length=1, max_length=256, description="Action status UUID: To do 17e793a1-26a3-4ecd-99ca-f38ecc6eaa2e; In progress 20ce0cb1-387a-47d4-8c34-bc6fd3be0e27; Complete 7223d809-553e-4714-a038-62dc98f3fbf3; Can't do 06308884-41c2-4ee0-9da7-5676647d3d75.")


class UpdateActionPriority(_ActionUpdate):
    operation: Literal["update_action_priority"] = _op("update_action_priority")
    priority_id: str = Field(..., min_length=1, max_length=256, description="Provider priority UUID.")


class UpdateActionDueDate(_ActionUpdate):
    operation: Literal["update_action_due_date"] = _op("update_action_due_date")
    due_at: AwareDatetime | None = Field(None, description="UTC or offset date/time. Leave unset to clear the due date.")


# Official payloads: /reference/webhooks and /reference/remove-owners-access-to-a-completed-inspection.
TRIGGER_EVENTS = {
    "on_inspection_started": "TRIGGER_EVENT_INSPECTION_HAS_STARTED",
    "on_inspection_completed": "TRIGGER_EVENT_INSPECTION_COMPLETED_STATUS",
}


class _InspectionTrigger(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(None, title="Webhook URL",
        description="Registered automatically for your organization. Requires Administrator permission for users, or Override permissions: Manage all data for service users.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class OnInspectionStarted(_InspectionTrigger):
    operation: Literal["on_inspection_started"] = Field("on_inspection_started", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "On Inspection Started"})


class OnInspectionCompleted(_InspectionTrigger):
    operation: Literal["on_inspection_completed"] = Field("on_inspection_completed", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "On Inspection Completed"})


SafetyCultureConfig = Annotated[Union[ListGroups, SearchInspections, SearchTemplates, GetTemplate,
    GetInspection, CreateInspection, CompleteInspection, ListActions, GetAction, CreateAction,
    UpdateActionTitle, UpdateActionDescription, UpdateActionStatus, UpdateActionPriority,
    UpdateActionDueDate, OnInspectionStarted, OnInspectionCompleted], Field(discriminator="operation")]


class SafetyCultureFullConfig(NodeConfig[SafetyCultureConfig, SafetyCultureAPITokenCredential]):
    pass


# One operation maps to exactly one published contract operation.
ROUTES = {
    "list_groups": ("GET", "/share/connections"),
    "search_inspections": ("GET", "/audits/search"),
    "search_templates": ("GET", "/templates/search"),
    "get_template": ("GET", "/templates/v1/templates/{template_id}"),
    "get_inspection": ("GET", "/inspections/v1/inspections/{inspection_id}"),
    "create_inspection": ("POST", "/inspections/integration/v1/inspections"),
    "complete_inspection": ("POST", "/inspections/integration/v1/inspections/{inspection_id}/complete"),
    "list_actions": ("POST", "/tasks/v1/actions/list"),
    "get_action": ("GET", "/tasks/v1/actions/{action_id}"),
    "create_action": ("POST", "/tasks/v1/actions"),
    "update_action_title": ("PUT", "/tasks/v1/actions/{action_id}/title"),
    "update_action_description": ("PUT", "/tasks/v1/actions/{action_id}/description"),
    "update_action_status": ("PUT", "/tasks/v1/actions/{action_id}/status"),
    "update_action_priority": ("PUT", "/tasks/v1/actions/{action_id}/priority"),
    "update_action_due_date": ("PUT", "/tasks/v1/actions/{action_id}/due_at"),
}


class SafetyCultureNode(ExternalWebhookTriggerMixin, WorkflowNode):
    webhook_replace_stale_endpoint = True
    integration_type = "automation-safetyculture"
    connection_evidence = ConnectionEvidence(operation="list_groups", noun="groups and organizations")

    @classmethod
    def get_config_model(cls):
        return SafetyCultureFullConfig

    @classmethod
    async def _webhook_request(cls, token, method, path, *, body=None):
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, json=body)
            if method == "DELETE" and response.status_code == 404:
                return {}
            if response.status_code != 200:
                raise ValueError(f"SafetyCulture webhook request failed (HTTP {response.status_code})")
            data = response.json()
            if not isinstance(data, dict) or data.get("error") or data.get("errors") or (isinstance(data.get("code"), int) and data["code"] != 0):
                raise ValueError("SafetyCulture returned an invalid webhook response")
            return data
        except httpx.RequestError:
            raise ValueError("SafetyCulture webhook request could not be confirmed") from None

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = TRIGGER_EVENTS.get((config or {}).get("operation"))
        if event is None:
            raise ValueError("Choose a supported SafetyCulture trigger")
        token = credential.get("api_token")
        if not token:
            raise ValueError("Connect a SafetyCulture API token")
        # Read the organization's secret; never rotate it and break other consumers.
        secret = (await cls._webhook_request(token, "GET", "/webhooks/v1/token")).get("token")
        if not isinstance(secret, str) or not secret:
            raise ValueError("SafetyCulture did not return its webhook signing secret")
        data = await cls._webhook_request(token, "POST", "/webhooks/v1/webhooks",
            body={"url": webhook_url, "trigger_events": [event]})
        endpoint = data.get("webhook") or {}
        endpoint_id = endpoint.get("webhook_id")
        if not isinstance(endpoint_id, str) or not endpoint_id:
            raise ValueError("SafetyCulture did not return a webhook ID")
        return {"external_webhook_id": endpoint_id, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if not endpoint_id:
            return
        if not credential or not credential.get("api_token"):
            raise ValueError("Connect SafetyCulture to remove its webhook")
        await cls._webhook_request(credential["api_token"], "DELETE",
            "/webhooks/v1/webhooks/" + quote(str(endpoint_id), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # https://developer.mitti.com/reference/webhooksservice_gettoken
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-safetyculture-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.encode(), expected.encode())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event_type = TRIGGER_EVENTS.get((config or {}).get("operation"))
        if not event_type or event_type not in (payload.get("event") or {}).get("event_types", []):
            return False
        if config["operation"] == "on_inspection_completed":
            return "inspection_completed_set" in (payload.get("data") or {})
        return True

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if (config or {}).get("operation") in TRIGGER_EVENTS:
            if not cls.filter_trigger_payload(payload, config):
                return {"status": "no_event", "operation": config["operation"]}
            return {"status": "success", "operation": config["operation"], "data": payload}
        return None

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") not in TRIGGER_EVENTS:
            return super().resolve_agent_event(output)
        if output.get("status") == "no_event":
            return None
        payload = output["data"]
        event = payload["event"]
        actor = event["triggered_by"]
        inspection_id = payload["resource"]["id"]
        details = payload["data"]["details"]
        action = "started" if output["operation"] == "on_inspection_started" else "completed"
        lines = [f"SafetyCulture inspection {action}: {inspection_id}",
            f"By {actor['user']} in organization {actor['organization']} at {event['date_triggered']}.",
            f"Template: {details['template_id']}."]
        if action == "completed":
            completion = payload["data"]["inspection_completed_set"]
            lines.append(f"Completed at {completion.get('complete_time', 'unknown time')}.")
            site = completion.get("site") or {}
            if site.get("folder_id"):
                lines.append(f"Site: {site['folder_id']}.")
        lines.append(f"Use get_inspection with inspection_id={inspection_id} to read the inspection and its answers.")
        return {"text": "\n".join(lines), "conversation_key": str(inspection_id),
            "title": f"Inspection {action}"}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SafetyCulture API token")
        op = self.config.config
        if op.operation in TRIGGER_EVENTS:
            payload = (self.node_data or {}).get("config", {}).get("_triggerPayload", inputs)
            return self.resolve_trigger_payload(payload, op.model_dump())
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        for field in ("template_id", "inspection_id", "action_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        if isinstance(op, SearchInspections):
            values["field"] = ["audit_id", "modified_at", "template_id"]
        elif isinstance(op, SearchTemplates):
            values["field"] = ["template_id", "name", "modified_at", "created_at"]
        token = self.config.credentials.api_token
        kwargs = {"params": values} if method == "GET" else {"json": values}
        # Fixed official host, redirects disabled, SSRF DNS/IP guard at dispatch.
        # Do not retry writes: a timeout or a 5xx may have committed the mutation.
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, BASE_URL + path,
                        headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 8 * 1024 * 1024:
                            raise ValueError("SafetyCulture response exceeds 8 MB; narrow the request")
                    if response.status_code != 200:
                        message = "SafetyCulture request failed"
                        try:
                            payload = json.loads(raw)
                            if isinstance(payload, dict) and isinstance(payload.get("message"), str):
                                message = payload["message"][:2000].replace(token, "[redacted]")
                        except (ValueError, UnicodeError):
                            pass
                        output = {"status": "error", "success": False, "http_status": response.status_code,
                            "message": message, "write_outcome": "unverified" if method != "GET" and op.operation != "list_actions" else None}
                    else:
                        media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if media != "application/json" and not media.endswith("+json"):
                            raise ValueError("SafetyCulture returned an unexpected representation")
                        payload = json.loads(raw)
                        if not isinstance(payload, dict) or payload.get("error") or payload.get("errors") or (isinstance(payload.get("code"), int) and payload["code"] != 0):
                            raise ValueError("SafetyCulture returned an invalid or error response")
                        # Retain provider envelopes, IDs and next_page_token unchanged.
                        output = {"status": "success", "success": True, "http_status": 200,
                            "data": payload, "operation": op.operation}
        except httpx.RequestError:
            raise ValueError("SafetyCulture request could not be confirmed; inspect the account before retrying a write") from None
        await self.emit(output)
        return output
