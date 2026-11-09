"""Encharge REST v1 operations for a person's own account using its API key.

Contract: https://encharge-app-resources.s3.amazonaws.com/merged.yaml
API-key alternative: https://app-encharge-resources.s3.amazonaws.com/merged.yaml
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.encharge.io/v1"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class EnchargeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Encharge API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.encharge.io/account/info",
        "x-credential-instructions": "Paste the API key from your Encharge Account page to automate your own account. NoClick sends it in the X-Encharge-Token header."})
    credential_type: Literal["encharge_api_key"] = Field("encharge_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PersonIdentifier(_Input):
    id: str | None = Field(None, min_length=1)
    userId: str | None = Field(None, min_length=1)
    email: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def identified(self):
        if not (self.id or self.userId or self.email):
            raise ValueError("Provide an Encharge id, userId or email")
        return self


class Person(PersonIdentifier):
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    name: str | None = None
    firstName: str | None = None
    lastName: str | None = None


class PersonField(_Input):
    name: str = Field(..., min_length=1)
    title: str | None = None
    type: Literal["string", "number", "boolean", "integer", "any"]
    format: Literal["date", "date-time"] | None = None
    readOnly: bool = False
    array: bool = False
    tooltip: str | None = None
    icon: str | None = None
    canMapFrom: bool | None = None
    firstClassField: bool | None = None
    createdBy: str | None = None


class _People(_Input):
    people: Json[Annotated[list[PersonIdentifier], Field(min_length=1, max_length=1000)]] = Field(
        ..., description='JSON array of people identified by id, userId or email, for example [{"email":"slav@encharge.io"}].', json_schema_extra=JSON_EDITOR)

    @field_validator("people", mode="before")
    @classmethod
    def json_people(cls, value):
        return json.dumps(value) if isinstance(value, list) else value


class GetPeople(_People):
    """Retrieve specific people by their identifiers."""
    operation: Literal["get_people"] = "get_people"


class UpsertPeople(_Input):
    """Create people or update those with matching identifiers and custom fields."""
    operation: Literal["upsert_people"] = "upsert_people"
    people: Json[Annotated[list[Person], Field(min_length=1, max_length=1000)]] = Field(..., description="JSON array of people, each with id, userId or email. Include names and custom person fields as needed.", json_schema_extra=JSON_EDITOR)
    _json = field_validator("people", mode="before")(_People.json_people.__func__)


class ArchivePeople(_People):
    """Archive people, or permanently delete their data when explicitly requested."""
    operation: Literal["archive_people"] = "archive_people"
    force: bool = Field(False, description="Permanently delete all person data for GDPR removal instead of archiving.")


class GetAccount(_Input):
    """Read account name, site, timezone and people count."""
    operation: Literal["get_account"] = "get_account"


class ListFields(_Input):
    """List the account's person fields."""
    operation: Literal["list_fields"] = "list_fields"


class CreateFields(_Input):
    """Create person field definitions."""
    operation: Literal["create_fields"] = "create_fields"
    fields: Json[Annotated[list[PersonField], Field(min_length=1, max_length=100)]] = Field(..., description="JSON array of person field definitions with name and type. readOnly and array default to false.", json_schema_extra=JSON_EDITOR)
    _json = field_validator("fields", mode="before")(_People.json_people.__func__)


class _Field(_Input):
    field_name: str = Field(..., min_length=1, max_length=256, description="Unique person field name, not its display title.")

    @field_validator("field_name")
    @classmethod
    def safe_name(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a valid person field name")
        return value


class UpdateField(_Field):
    """Modify a person field using its complete definition."""
    operation: Literal["update_field"] = "update_field"
    field: Json[PersonField] = Field(..., description="JSON field definition; name must match the selected field name.", json_schema_extra=JSON_EDITOR)

    @field_validator("field", mode="before")
    @classmethod
    def json_field(cls, value):
        return json.dumps(value) if isinstance(value, dict) else value

    @model_validator(mode="after")
    def same_name(self):
        if self.field.name != self.field_name:
            raise ValueError("Field definition name must match field_name")
        return self


class DeleteField(_Field):
    """Delete a person field definition."""
    operation: Literal["delete_field"] = "delete_field"


class ListSegments(_Input):
    """List dynamic segments in the account."""
    operation: Literal["list_segments"] = "list_segments"


class ListSegmentPeople(_Input):
    """Read one page of people in a dynamic segment."""
    operation: Literal["list_segment_people"] = "list_segment_people"
    segment_id: int = Field(..., ge=1)
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    attributes: str | None = Field(None, description="Comma-separated person field names to retrieve.")
    sort: str | None = None
    order: Literal["asc", "desc"] | None = None


class AddTags(PersonIdentifier):
    """Add one or more comma-separated tags to an existing person."""
    operation: Literal["add_tags"] = "add_tags"
    tag: str = Field(..., min_length=1, description="Tag name, or comma-separated tag names.")


class RemoveTags(PersonIdentifier):
    """Remove one or more comma-separated tags from an existing person."""
    operation: Literal["remove_tags"] = "remove_tags"
    tag: str = Field(..., min_length=1, description="Tag name, or comma-separated tag names.")


class UnsubscribePerson(PersonIdentifier):
    """Unsubscribe a person from receiving further emails."""
    operation: Literal["unsubscribe_person"] = "unsubscribe_person"



EnchargeOperation = Annotated[Union[GetPeople, UpsertPeople, ArchivePeople, GetAccount,
    ListFields, CreateFields, UpdateField, DeleteField, ListSegments, ListSegmentPeople,
    AddTags, RemoveTags, UnsubscribePerson], Field(discriminator="operation")]


class EnchargeConfig(NodeConfig[EnchargeOperation, EnchargeAPIKeyCredential]):
    pass


# One native operation, one published API operation; no arbitrary request surface.
ROUTES = {
    "get_people": ("GET", "/people", 200, "users"),
    "upsert_people": ("POST", "/people", 200, "users"),
    "archive_people": ("DELETE", "/people", 204, None),
    "get_account": ("GET", "/accounts/info", 200, None),
    "list_fields": ("GET", "/fields", 200, "items"),
    "create_fields": ("POST", "/fields", 200, "items"),
    "update_field": ("PATCH", "/fields/{fieldName}", 200, "field"),
    "delete_field": ("DELETE", "/fields/{fieldName}", 204, None),
    "list_segments": ("GET", "/segments", 200, "segments"),
    "list_segment_people": ("GET", "/segments/{segmentId}/people", 200, "people"),
    "add_tags": ("POST", "/tags", 201, None),
    "remove_tags": ("DELETE", "/tags", 204, None),
    "unsubscribe_person": ("POST", "/people/unsubscribe", 204, None),
}


def _dump(value):
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value.model_dump(exclude_none=True)


def _redact(value: Any, secret: str):
    if isinstance(value, dict):
        return {k.replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value.replace(secret, "[redacted]") if isinstance(value, str) else value


class EnchargeNode(WorkflowNode):
    integration_type = "automation-encharge"
    connection_evidence = ConnectionEvidence(noun="segments", operation="list_segments", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return EnchargeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Encharge API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, expected, envelope = ROUTES[op.operation]
        params, body = {}, None
        if isinstance(op, (GetPeople, ArchivePeople)):
            for index, person in enumerate(op.people):
                for field, value in _dump(person).items():
                    params[f"people[{index}][{field}]"] = value
            if isinstance(op, ArchivePeople):
                params["force"] = str(op.force).lower()
        elif isinstance(op, UpsertPeople):
            body = _dump(op.people)
        elif isinstance(op, CreateFields):
            body = _dump(op.fields)
        elif isinstance(op, (UpdateField, DeleteField)):
            path = path.replace("{fieldName}", quote(op.field_name, safe=""))
            if isinstance(op, UpdateField):
                body = _dump(op.field)
        elif isinstance(op, ListSegmentPeople):
            path = path.replace("{segmentId}", str(op.segment_id))
            params = {"limit": op.limit, "offset": op.offset}
            if op.attributes:
                params["attributes"] = [s.strip() for s in op.attributes.split(",") if s.strip()]
            for field in ("sort", "order"):
                if getattr(op, field) is not None:
                    params[field] = getattr(op, field)
        elif isinstance(op, (AddTags, RemoveTags)):
            body = op.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(op, UnsubscribePerson):
            params = op.model_dump(exclude={"operation"}, exclude_none=True)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"X-Encharge-Token": key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            status = response.status_code
            if status != expected:
                # Keep provider rejection text for connection evidence, with the secret removed.
                message = f"Encharge returned HTTP {status}"
                if len(response.content) < 20000:
                    try:
                        error = response.json()
                        error = error.get("error", error.get("message")) if isinstance(error, dict) else None
                        if isinstance(error, dict):
                            error = error.get("message")
                        if isinstance(error, str):
                            message = error[:2000]
                    except ValueError:
                        pass
                return {"status": "error", "http_status": status, "error": _redact(message, key)}
            out = {"status": "success", "operation": op.operation, "http_status": status}
            if status == 204 or (op.operation == "add_tags" and not response.content):
                return {**out, "acknowledged": True}
            if op.operation == "add_tags":
                return {**out, "acknowledged": True}
            if len(response.content) > 10_000_000:
                raise ValueError("Encharge response exceeds the size bound")
            payload = response.json()
            if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
                raise ValueError("Invalid Encharge response envelope")
            if envelope is not None:
                if envelope not in payload or not isinstance(payload[envelope], dict if envelope == "field" else list):
                    raise ValueError("Missing Encharge response data")
            if op.operation == "get_account" and "accountId" not in payload:
                raise ValueError("Missing account identity")
            out["data"] = _redact(payload, key)
            if envelope is not None:
                out[envelope] = out["data"][envelope]
            if isinstance(op, ListSegmentPeople):
                out.update(offset=op.offset, limit=op.limit, next_offset=op.offset + len(payload["people"]) if len(payload["people"]) == op.limit else None)
            return out
        except (httpx.HTTPError, SSRFError, ValueError) as exc:
            message = "Encharge request timed out" if isinstance(exc, httpx.TimeoutException) else "Encharge request failed or returned an invalid response"
            return {"status": "error", "error": message}
