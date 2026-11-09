"""BONZO public API 3.0.0: one published endpoint per operation.

Contract: https://docs.getbonzo.com/api-docs.json
Production server: https://docs.getbonzo.com/api/public-api/new
Lists return one page; writes acknowledge the provider response without claiming delivery.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.getbonzo.com/api/v3"
ID = Annotated[int, Field(ge=1)]
Text = Annotated[str, Field(min_length=1, max_length=10000)]


class BonzoAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="BONZO API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://support.getbonzo.com/hc/en-us/articles/21542406821010-Admin-Integrations-Settings",
            "x-credential-instructions": "In BONZO, open Settings, Integrations, API and choose Add Token. Select the resource permissions needed by your workflow, then copy the token when it is shown. Paste only the API token here, without Bearer. Access follows the creating user's permissions; use a Team Lead or Admin token to manage multiple owners' prospects. NoClick checks the current user and sends the token only to app.getbonzo.com."
        })
    credential_type: Literal["bonzo_api_token"] = Field("bonzo_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetCurrentUser(_Input):
    """Get user details."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})

class ListProspects(_Input):
    """List prospects."""
    operation: Literal["list_prospects"] = Field("list_prospects", json_schema_extra={"ui:hidden": True})
    search: Optional[Text] = Field(None)
    pipeline_stage: Optional[int] = Field(None)
    group: Optional[int] = Field(None)
    status: Optional[Literal['active', 'non-active', 'responded']] = Field(None)
    sort: Optional[Literal['name', 'tags', 'last_conversation', 'last_contact', 'campaign', 'campaign_join', 'team', 'assigned_to', 'quialified_status', 'status', 'conversationalist_id', 'created_at']] = Field(None)
    order: Optional[Literal['desc', 'asc']] = Field(None)
    per_page: int = Field(15, ge=1, le=100, description="Maximum records in this page.")
    page: int = Field(1, ge=1, le=1000000, description="Page number; request subsequent pages explicitly.")

class GetProspect(_Input):
    """Show prospect."""
    operation: Literal["get_prospect"] = Field("get_prospect", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)

class CreateProspect(_Input):
    """Create prospect."""
    operation: Literal["create_prospect"] = Field("create_prospect", json_schema_extra={"ui:hidden": True})
    campaign: ID = Field(...)
    first_name: Annotated[str, Field(min_length=1, max_length=50)] = Field(...)
    last_name: Optional[Annotated[str, Field(max_length=50)]] = Field(None)
    email: Optional[Text] = Field(None)
    phone: Optional[Text] = Field(None)
    assigned_to: Optional[int] = Field(None)
    birthday: Optional[Text] = Field(None)
    address: Optional[Text] = Field(None)
    prospect_state: Optional[Text] = Field(None)
    city: Optional[Text] = Field(None)
    prospect_zip: Optional[Text] = Field(None)

class UpdateProspect(_Input):
    """Update prospect."""
    operation: Literal["update_prospect"] = Field("update_prospect", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)
    first_name: Annotated[str, Field(min_length=1, max_length=50)] = Field(...)
    last_name: Optional[Annotated[str, Field(max_length=50)]] = Field(None)
    email: Optional[Text] = Field(None)
    phone: Optional[Text] = Field(None)
    assigned_to: Optional[int] = Field(None)
    birthday: Optional[Text] = Field(None)
    address: Optional[Text] = Field(None)
    prospect_state: Optional[Text] = Field(None)
    city: Optional[Text] = Field(None)
    prospect_zip: Optional[Text] = Field(None)
    tags: Optional[Text] = Field(None, description="A prospect tag name.")

class DeleteProspect(_Input):
    """Delete prospect."""
    operation: Literal["delete_prospect"] = Field("delete_prospect", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)

class ListCampaigns(_Input):
    """List campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})
    search: Optional[Text] = Field(None)
    type: Optional[Literal['consequtive', 'date_based']] = Field(None)
    sort: Optional[Literal['name', 'messages', 'prospects', 'status']] = Field(None)
    order: Optional[Literal['desc', 'asc']] = Field(None)
    per_page: int = Field(15, ge=1, le=100, description="Maximum records in this page.")
    page: int = Field(1, ge=1, le=1000000, description="Page number; request subsequent pages explicitly.")

class ChangeCampaign(_Input):
    """Change campaign."""
    operation: Literal["change_campaign"] = Field("change_campaign", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)
    campaign: ID = Field(...)

class ListPipelines(_Input):
    """List pipeliens."""
    operation: Literal["list_pipelines"] = Field("list_pipelines", json_schema_extra={"ui:hidden": True})
    per_page: int = Field(15, ge=1, le=100, description="Maximum records in this page.")
    page: int = Field(1, ge=1, le=1000000, description="Page number; request subsequent pages explicitly.")

class GetPipeline(_Input):
    """Show pipeline."""
    operation: Literal["get_pipeline"] = Field("get_pipeline", json_schema_extra={"ui:hidden": True})
    pipeline: ID = Field(...)

class MoveProspect(_Input):
    """Move prospect to pipeline."""
    operation: Literal["move_prospect"] = Field("move_prospect", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)
    pipeline_stage: ID = Field(...)

class ListNotes(_Input):
    """List notes."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)

class CreateNote(_Input):
    """Create note."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)
    content: Text = Field(...)
    is_pinned: Optional[bool] = Field(None)
    include_in_conversation: Optional[bool] = Field(None)

class UpdateNote(_Input):
    """Update note."""
    operation: Literal["update_note"] = Field("update_note", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)
    note: ID = Field(...)
    content: Text = Field(...)
    is_pinned: Optional[bool] = Field(None)
    include_in_conversation: Optional[bool] = Field(None)

class DeleteNote(_Input):
    """Delete note."""
    operation: Literal["delete_note"] = Field("delete_note", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)
    note: ID = Field(...)

class ListTags(_Input):
    """List tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})

class ListTasks(_Input):
    """List tasks."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    prospect_id: Optional[int] = Field(None)
    search: Optional[Text] = Field(None)
    type: Optional[Literal['none', 'call', 'voicemail', 'follow_up', 'meeting', 'birthday']] = Field(None)
    status: Optional[Literal['today', 'active', 'upcoming', 'overdue', 'completed', 'birthday', 'current']] = Field(None)
    conversationalist: Optional[bool] = Field(None)
    sort: Optional[Literal['title', 'details', 'type', 'assignee_id', 'business_id', 'prospect_id', 'date']] = Field(None)
    order: Optional[Literal['desc', 'asc']] = Field(None)
    per_page: int = Field(15, ge=1, le=100, description="Maximum records in this page.")
    page: int = Field(1, ge=1, le=1000000, description="Page number; request subsequent pages explicitly.")

class GetTask(_Input):
    """Task details."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    task: ID = Field(...)

class ListTeamMembers(_Input):
    """List team members."""
    operation: Literal["list_team_members"] = Field("list_team_members", json_schema_extra={"ui:hidden": True})
    search: Optional[Text] = Field(None)
    per_page: int = Field(15, ge=1, le=100, description="Maximum records in this page.")
    page: int = Field(1, ge=1, le=1000000, description="Page number; request subsequent pages explicitly.")

class SendSms(_Input):
    """Send SMS."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)
    message: Text = Field(...)
    attachment_url: Optional[Text] = Field(None)

class SendEmail(_Input):
    """Send email."""
    operation: Literal["send_email"] = Field("send_email", json_schema_extra={"ui:hidden": True})
    prospect: ID = Field(...)
    subject: Text = Field(...)
    message: Text = Field(...)


BonzoConfig = Annotated[Union[GetCurrentUser, ListProspects, GetProspect, CreateProspect, UpdateProspect, DeleteProspect, ListCampaigns, ChangeCampaign, ListPipelines, GetPipeline, MoveProspect, ListNotes, CreateNote, UpdateNote, DeleteNote, ListTags, ListTasks, GetTask, ListTeamMembers, SendSms, SendEmail], Field(discriminator="operation")]


class BonzoFullConfig(NodeConfig[BonzoConfig, BonzoAPITokenCredential]):
    pass


ROUTES = {'get_current_user': ('GET', '/me', 200), 'list_prospects': ('GET', '/prospects', 200), 'get_prospect': ('GET', '/prospects/{prospect}', 200), 'create_prospect': ('POST', '/prospects/campaign/{campaign}', 200), 'update_prospect': ('PUT', '/prospects/{prospect}', 200), 'delete_prospect': ('DELETE', '/prospects/{prospect}', 200), 'list_campaigns': ('GET', '/campaigns', 200), 'change_campaign': ('POST', '/prospects/{prospect}/campaign/{campaign}', 200), 'list_pipelines': ('GET', '/pipelines', 200), 'get_pipeline': ('GET', '/pipelines/fetch/{pipeline}', 200), 'move_prospect': ('POST', '/prospects/{prospect}/pipeline-stage/{pipelineStage}', 200), 'list_notes': ('GET', '/prospects/{prospect}/notes', 200), 'create_note': ('POST', '/prospects/{prospect}/notes', 201), 'update_note': ('PUT', '/prospects/{prospect}/notes/{note}', 200), 'delete_note': ('DELETE', '/prospects/{prospect}/notes/{note}', 200), 'list_tags': ('GET', '/tags', 200), 'list_tasks': ('GET', '/tasks', 200), 'get_task': ('GET', '/tasks/{task}', 200), 'list_team_members': ('GET', '/team/members', 200), 'send_sms': ('POST', '/prospects/{prospect}/sms', 200), 'send_email': ('POST', '/prospects/{prospect}/email', 200)}


class BonzoNode(WorkflowNode):
    integration_type = "automation-bonzo"
    connection_evidence = ConnectionEvidence(
        noun="BONZO account", identity_operation="get_current_user",
        identity_keys=("name", "email", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return BonzoFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a BONZO API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, template, expected_status = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = template
        for name in list(values):
            wire_name = "pipelineStage" if name == "pipeline_stage" and op.operation == "move_prospect" else name
            if "{" + wire_name + "}" in path:
                path = path.replace("{" + wire_name + "}", str(values.pop(name)))
        # Current provider docs use JSON rather than the old pinned form encoding.
        if "assigned_to" in values:
            values["assigned_to"] = str(values["assigned_to"])
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers,
                    **({"params": values} if method == "GET" else {"json": values} if values else {}))
        except httpx.RequestError:
            raise ValueError("BONZO request could not be confirmed; inspect writes before retrying") from None
        if response.status_code not in ({200, 201} if op.operation == "create_note" else {expected_status}):
            try:
                error = response.json()
                message = error.get("message") if isinstance(error, dict) else None
            except ValueError:
                message = None
            safe = message.replace(token, "[redacted]")[:1000] if isinstance(message, str) else "Request was not confirmed"
            raise ValueError(f"BONZO HTTP {response.status_code}: {safe}")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("BONZO returned invalid JSON; inspect writes before retrying") from None
        if not isinstance(payload, dict) or "error" in payload or payload.get("success") is False:
            raise ValueError("BONZO returned an error or invalid response; inspect writes before retrying")
        output = {"status": "success", "http_status": response.status_code}
        if op.operation in {"delete_prospect", "delete_note", "move_prospect"}:
            if not isinstance(payload.get("message"), str) or not payload["message"]:
                raise ValueError("BONZO acknowledgement is missing its message")
            output["message"] = payload["message"]
        else:
            data = payload.get("data")
            listing = op.operation.startswith("list_")
            if not isinstance(data, list if listing else dict):
                raise ValueError("BONZO response is missing its data " + ("array" if listing else "object"))
            output["data"] = data
            if listing:
                if not all(isinstance(row, dict) for row in data):
                    raise ValueError("BONZO returned an invalid list item")
                output["items"] = data
                if hasattr(op, "page"):
                    meta = payload.get("meta")
                    if not isinstance(meta, dict):
                        raise ValueError("BONZO response is missing pagination metadata")
                    current, last = meta.get("current_page"), meta.get("last_page")
                    if type(current) is not int or type(last) is not int or current < 1 or last < current:
                        raise ValueError("BONZO returned invalid pagination metadata")
                    output.update(meta=meta, next_page=current + 1 if current < last else None, has_more=current < last)
            else:
                identifier = data.get("id")
                if not isinstance(identifier, (str, int)) or isinstance(identifier, bool):
                    raise ValueError("BONZO response is missing its resource ID")
                expected = {
                    "get_prospect": "prospect", "update_prospect": "prospect", "change_campaign": "prospect",
                    "get_pipeline": "pipeline", "get_task": "task", "update_note": "note",
                }.get(op.operation)
                if expected and str(identifier) != str(getattr(op, expected)):
                    raise ValueError("BONZO returned a different resource ID")
        if method != "GET":
            output["write_acknowledged"] = True

        def redact(value):
            if isinstance(value, str):
                return value.replace(token, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items()}
            return value

        output = redact(output)
        await self.emit(output)
        return output
