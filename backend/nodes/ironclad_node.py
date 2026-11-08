"""Ironclad public API v1 operations using a person-supplied bearer token."""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client
from nodes.scopes.ironclad import IRONCLAD_SCOPES


class IroncladAPITokenCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Ironclad API Token",
        json_schema_extra={
            "x-credential-url": "https://developer.ironcladapp.com/reference/authenticate-a-request",
            "x-credential-instructions": "Paste an existing Ironclad access token without the Bearer prefix. Replace it when it expires; NoClick does not refresh pasted tokens. Legacy access tokens are deprecated by Ironclad. For client-credentials or legacy tokens, enter the Ironclad user email whose permissions apply. For a personal user token, leave the email blank to use its own identity. Select the same region where the token was issued. A successful read verifies access to records, not all write permissions.",
        })
    credential_type: Literal["ironclad_api_token"] = Field("ironclad_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=8192, repr=False, title="Access token", json_schema_extra={"ui:widget": "password"})
    user_email: str | None = Field(None, min_length=3, max_length=254, title="Act as user email", description="An existing Ironclad user email, required for client-credentials tokens. Omit for a personal user token.")
    api_host: Literal["ironcladapp.com", "eu1.ironcladapp.com", "demo.ironcladapp.com"] = Field("ironcladapp.com", title="API region", description="Production, EU production, or demo.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, key=True)
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste an access token without whitespace or the Bearer prefix")
        return value

    @field_validator("user_email", mode="before")
    @classmethod
    def email(cls, value):
        if value is None or isinstance(value, str) and not value.strip():
            return None
        if not isinstance(value, str):
            raise ValueError("Enter an Ironclad user email")
        value = value.strip()
        if not value.isascii() or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter an Ironclad user email")
        return value


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowId(Operation):
    workflow_id: str = Field(..., min_length=1, max_length=256, title="Workflow ID", description="The workflow ID or Ironclad ID.")


class RecordId(Operation):
    record_id: str = Field(..., min_length=1, max_length=256, title="Record ID", description="The record ID or Ironclad ID.")


class EntityId(Operation):
    entity_id: str = Field(..., min_length=1, max_length=256, title="Entity ID", description="The entity ID or Ironclad ID.")


class Page(Operation):
    page: int = Field(0, ge=0, le=100000000, description="Zero-based page; one page is returned per execution.")
    page_size: int = Field(20, ge=1, le=100, title="Page size")


class ListWorkflows(Page):
    operation: Literal["list_workflows"] = "list_workflows"
    status: Literal["active", "paused", "completed", "cancelled"] = "active"
    template: str | None = None
    search: str | None = Field(None, max_length=1000)
    filter: str | None = Field(None, description="Ironclad filter formula.")
    last_updated: str | None = Field(None, description="Retrieve workflows updated since this UTC date.")


class GetWorkflow(WorkflowId):
    operation: Literal["get_workflow"] = "get_workflow"


class CreateWorkflow(Operation):
    operation: Literal["create_workflow"] = "create_workflow"
    template: str = Field(..., min_length=1, title="Template ID")
    attributes: dict[str, Any] = Field(..., description="Launch-form attributes using IDs and values from the workflow schema.")
    use_default_values: bool = False


class ListWorkflowApprovals(WorkflowId):
    operation: Literal["list_workflow_approvals"] = "list_workflow_approvals"


class ListWorkflowSigners(WorkflowId):
    operation: Literal["list_workflow_signers"] = "list_workflow_signers"


class ListWorkflowParticipants(WorkflowId, Page):
    operation: Literal["list_workflow_participants"] = "list_workflow_participants"


class ListWorkflowComments(WorkflowId, Page):
    operation: Literal["list_workflow_comments"] = "list_workflow_comments"


class CreateWorkflowComment(WorkflowId):
    operation: Literal["create_workflow_comment"] = "create_workflow_comment"
    comment: str = Field(..., min_length=1, description="Comment text; mentions use <@user@example.com>.")
    replied_to_comment_id: str | None = None


class AttributeUpdate(Operation):
    action: Literal["set", "remove"] = "set"
    path: str = Field(..., min_length=1, description="Workflow attribute ID.")
    value: Any = None

    @model_validator(mode="after")
    def set_value(self):
        if self.action == "set" and "value" not in self.model_fields_set:
            raise ValueError("Set requires an attribute value")
        return self


class UpdateWorkflowAttributes(WorkflowId):
    operation: Literal["update_workflow_attributes"] = "update_workflow_attributes"
    updates: list[AttributeUpdate] = Field(..., min_length=1)
    comment: str | None = None


class PauseWorkflow(WorkflowId):
    operation: Literal["pause_workflow"] = "pause_workflow"
    comment: str = Field(..., min_length=1)


class ResumeWorkflow(WorkflowId):
    operation: Literal["resume_workflow"] = "resume_workflow"
    comment: str = Field(..., min_length=1)


class CancelWorkflow(WorkflowId):
    operation: Literal["cancel_workflow"] = "cancel_workflow"
    comment: str = Field(..., min_length=1)


class ListWorkflowSchemas(Operation):
    operation: Literal["list_workflow_schemas"] = "list_workflow_schemas"
    form: Literal["launch"] = "launch"


class GetWorkflowSchema(Operation):
    operation: Literal["get_workflow_schema"] = "get_workflow_schema"
    schema_id: str = Field(..., min_length=1, title="Workflow schema ID")
    form: Literal["launch"] = "launch"


class ListRecords(Page):
    operation: Literal["list_records"] = "list_records"
    search: str | None = Field(None, max_length=1000)
    filter: str | None = None
    types: str | None = Field(None, description="Comma-separated record type IDs.")
    last_updated: str | None = None


class GetRecord(RecordId):
    operation: Literal["get_record"] = "get_record"


class CreateRecord(Operation):
    operation: Literal["create_record"] = "create_record"
    record_type: str = Field(..., min_length=1, description="Record type ID from the records schema.")
    name: str = Field(..., min_length=1)
    properties: dict[str, Any] = Field(..., description='Typed properties, e.g. {"counterpartyName":{"type":"string","value":"Jane Doe"}}.')


class UpdateRecord(RecordId):
    operation: Literal["update_record"] = "update_record"
    name: str | None = Field(None, min_length=1)
    record_type: str | None = None
    add_properties: dict[str, Any] | None = None
    remove_properties: list[str] | None = None

    @model_validator(mode="after")
    def change(self):
        if all(getattr(self, k) is None for k in ("name", "record_type", "add_properties", "remove_properties")):
            raise ValueError("Provide a record change")
        return self


class DeleteRecord(RecordId):
    operation: Literal["delete_record"] = "delete_record"


class GetRecordSchema(Operation):
    operation: Literal["get_record_schema"] = "get_record_schema"


class ListEntities(Page):
    operation: Literal["list_entities"] = "list_entities"
    search: str | None = Field(None, max_length=1000)
    filter: str | None = None


class GetEntity(EntityId):
    operation: Literal["get_entity"] = "get_entity"


class CreateEntity(Operation):
    operation: Literal["create_entity"] = "create_entity"
    name: str = Field(..., min_length=1)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"
    properties: dict[str, Any] | None = None


class UpdateEntity(EntityId):
    operation: Literal["update_entity"] = "update_entity"
    name: str | None = Field(None, min_length=1)
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    add_properties: dict[str, Any] | None = None
    remove_properties: list[str] | None = None

    @model_validator(mode="after")
    def change(self):
        if all(getattr(self, k) is None for k in ("name", "status", "add_properties", "remove_properties")):
            raise ValueError("Provide an entity change")
        return self


IroncladOperation = Annotated[Union[
    ListWorkflows, GetWorkflow, CreateWorkflow, ListWorkflowApprovals, ListWorkflowSigners,
    ListWorkflowParticipants, ListWorkflowComments, CreateWorkflowComment, UpdateWorkflowAttributes,
    PauseWorkflow, ResumeWorkflow, CancelWorkflow, ListWorkflowSchemas, GetWorkflowSchema,
    ListRecords, GetRecord, CreateRecord, UpdateRecord, DeleteRecord, GetRecordSchema,
    ListEntities, GetEntity, CreateEntity, UpdateEntity,
], Field(discriminator="operation")]


class IroncladNodeConfig(NodeConfig[IroncladOperation, IroncladAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "list_workflows": ("GET", "/workflows"),
    "get_workflow": ("GET", "/workflows/{workflow_id}"),
    "create_workflow": ("POST", "/workflows"),
    "list_workflow_approvals": ("GET", "/workflows/{workflow_id}/approvals"),
    "list_workflow_signers": ("GET", "/workflows/{workflow_id}/signatures"),
    "list_workflow_participants": ("GET", "/workflows/{workflow_id}/participants"),
    "list_workflow_comments": ("GET", "/workflows/{workflow_id}/comments"),
    "create_workflow_comment": ("POST", "/workflows/{workflow_id}/comments"),
    "update_workflow_attributes": ("PATCH", "/workflows/{workflow_id}/attributes"),
    "pause_workflow": ("POST", "/workflows/{workflow_id}/pause"),
    "resume_workflow": ("POST", "/workflows/{workflow_id}/resume"),
    "cancel_workflow": ("POST", "/workflows/{workflow_id}/cancel"),
    "list_workflow_schemas": ("GET", "/workflow-schemas"),
    "get_workflow_schema": ("GET", "/workflow-schemas/{schema_id}"),
    "list_records": ("GET", "/records"),
    "get_record": ("GET", "/records/{record_id}"),
    "create_record": ("POST", "/records"),
    "update_record": ("PATCH", "/records/{record_id}"),
    "delete_record": ("DELETE", "/records/{record_id}"),
    "get_record_schema": ("GET", "/records/metadata"),
    "list_entities": ("GET", "/entities"),
    "get_entity": ("GET", "/entities/{entity_id}"),
    "create_entity": ("POST", "/entities"),
    "update_entity": ("PATCH", "/entities/{entity_id}"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(x, secret) for x in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


def _request_parts(op):
    values = op.model_dump(exclude_none=True)
    method, route = ROUTES[op.operation]
    for key in ("workflow_id", "record_id", "entity_id", "schema_id"):
        if key in values:
            identifier = values[key]
            if identifier in {".", ".."} or any(ord(c) < 32 for c in identifier):
                raise ValueError("Use a single Ironclad resource ID")
            route = route.replace("{" + key + "}", quote(identifier, safe=""))
    params, body = {}, None
    if isinstance(op, Page):
        params.update(page=op.page, pageSize=op.page_size)
    if isinstance(op, (ListWorkflows, ListRecords, ListEntities)):
        for key in ("status", "template", "search", "filter", "types", "last_updated", "name"):
            if key in values:
                params["lastUpdated" if key == "last_updated" else key] = values[key]
    if isinstance(op, (ListWorkflowSchemas, GetWorkflowSchema)):
        params["form"] = op.form
    if isinstance(op, CreateWorkflow):
        params["useDefaultValues"] = str(op.use_default_values).lower()
        body = {"template": op.template, "attributes": op.attributes}
    elif isinstance(op, CreateWorkflowComment):
        body = {"comment": op.comment}
        if op.replied_to_comment_id is not None:
            body["repliedToActivityFeedMessageId"] = op.replied_to_comment_id
    elif isinstance(op, UpdateWorkflowAttributes):
        body = {"updates": [x.model_dump() if x.action == "set" else {"action": "remove", "path": x.path} for x in op.updates]}
        if op.comment is not None:
            body["comment"] = op.comment
    elif isinstance(op, (PauseWorkflow, ResumeWorkflow, CancelWorkflow)):
        body = {"comment": {"message": op.comment}}
    elif isinstance(op, CreateRecord):
        body = {"type": op.record_type, "name": op.name, "properties": op.properties}
    elif isinstance(op, (UpdateRecord, UpdateEntity, CreateEntity)):
        aliases = {"record_type": "type", "add_properties": "addProperties", "remove_properties": "removeProperties"}
        body = {aliases.get(k, k): v for k, v in values.items() if k not in {"operation", "record_id", "entity_id"}}
    return method, route, params, body


class IroncladNode(WorkflowNode):
    integration_type = "automation-ironclad"
    scope_registry = IRONCLAD_SCOPES
    connection_evidence = ConnectionEvidence(noun="records", operation="list_records", label_keys=("name", "ironcladId", "id"))

    @classmethod
    def get_config_model(cls):
        return IroncladNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Ironclad access token")
        credential = self.config.credentials
        op = self.config.config
        method, route, params, body = _request_parts(op)
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}
        if credential.user_email:
            headers["x-as-user-email"] = credential.user_email
        try:
            async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=30) as client:
                response = await client.request(method, "https://" + credential.api_host + "/public/api/v1" + route,
                    headers=headers, params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            detail = "Read failed" if method == "GET" else "Write outcome unknown; inspect Ironclad before retrying"
            raise ValueError("Ironclad: " + detail) from None
        if not 200 <= response.status_code < 300:
            message = "Ironclad rejected the request"
            try:
                payload = response.json()
                if isinstance(payload, dict) and isinstance(payload.get("message"), str):
                    message = payload["message"][:2000]
            except ValueError:
                pass
            message = _redact(message, credential.api_token)
            raise ValueError(f"Ironclad HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            output = {"acknowledged": True}
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Ironclad returned an invalid JSON response") from None
            if not isinstance(payload, (dict, list)):
                raise ValueError("Ironclad returned an unexpected response shape")
            output = {"data": payload}
            if isinstance(op, Page):
                if not isinstance(payload, dict) or not isinstance(payload.get("list"), list):
                    raise ValueError("Ironclad returned an invalid list envelope")
                output.update(items=payload["list"], page=payload.get("page"), page_size=payload.get("pageSize"), count=payload.get("count"))
                count = payload.get("count")
                next_page = op.page + 1 if type(count) is int and (op.page + 1) * op.page_size < count else None
                output.update(next_page=next_page, complete=next_page is None if type(count) is int else False)
        output.update(status="success", operation=op.operation, http_status=response.status_code)
        output = _redact(output, credential.api_token)
        await self.emit(output)
        return output
