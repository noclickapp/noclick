"""SafetyCulture (now Mitti) API v1.369.11.

Contract: https://developer.mitti.com/openapi/safetyculture-api.json
Host/rebrand: https://developer.mitti.com/docs/mitti-apps-guide
Each operation makes one API request. Lists return one page and provider paging
metadata unchanged; writes report the API acknowledgement, not a readback.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
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


SafetyCultureConfig = Annotated[Union[ListGroups, SearchInspections, SearchTemplates, GetTemplate,
    GetInspection, CreateInspection, CompleteInspection, ListActions, GetAction, CreateAction,
    UpdateActionTitle, UpdateActionDescription, UpdateActionStatus, UpdateActionPriority,
    UpdateActionDueDate], Field(discriminator="operation")]


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


class SafetyCultureNode(WorkflowNode):
    integration_type = "automation-safetyculture"
    connection_evidence = ConnectionEvidence(operation="list_groups", noun="groups and organizations")

    @classmethod
    def get_config_model(cls):
        return SafetyCultureFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SafetyCulture API token")
        op = self.config.config
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
