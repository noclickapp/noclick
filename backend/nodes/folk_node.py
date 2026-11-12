"""Folk API 2025-06-09: one documented request per operation, one page per list.

Contract: https://developer.folk.app/schemas/2025-06-09.json
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.folk.app"
ID = Annotated[str, Field(min_length=40, max_length=40, pattern=r"^[a-z]{3}_[0-9a-fA-F-]{36}$")]
Short = Annotated[str, Field(max_length=500)]
Email = Annotated[str, Field(max_length=254)]
Phone = Annotated[str, Field(max_length=30)]
URL = Annotated[str, Field(max_length=2048)]


class FolkAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Folk API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.folk.app/apps/contacts/network/settings/api-keys",
            "x-credential-instructions": "In Folk workspace settings, open API and create an API key. Paste the key here without the Bearer prefix. NoClick checks the current user and sends requests only to api.folk.app. Access follows the workspace permissions of the key's user."
        })
    credential_type: Literal["folk_api_key"] = Field("folk_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(ch.isspace() for ch in value):
            raise ValueError("Paste only the API key, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, description="Number of records in this page.")
    cursor: Optional[str] = Field(None, min_length=1, max_length=512, description="Use next_cursor from a previous page, keeping the same filters.")


class _Write(_Input):
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=255, description="Optional Idempotency-Key. Reuse with the same body when retrying within 24 hours.")

    @field_validator("idempotency_key")
    @classmethod
    def header(cls, value):
        if value is not None and (not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            raise ValueError("Use an ASCII idempotency key without whitespace")
        return value


class _Contact(_Write):
    description: Optional[str] = Field(None, max_length=5000)
    emails: Optional[list[Email]] = Field(None, max_length=20)
    phones: Optional[list[Phone]] = Field(None, max_length=20)
    urls: Optional[list[URL]] = Field(None, max_length=20)
    addresses: Optional[list[Short]] = Field(None, max_length=20)
    group_ids: Optional[list[ID]] = Field(None, max_length=100, description="Groups to associate. On update this replaces group membership; an empty array clears it.")


class _Person(_Contact):
    firstName: Optional[str] = Field(None, max_length=500)
    lastName: Optional[str] = Field(None, max_length=500)
    fullName: Optional[str] = Field(None, max_length=1000)
    jobTitle: Optional[str] = Field(None, max_length=500)
    company_ids: Optional[list[ID]] = Field(None, max_length=20, description="Company associations; first is primary. Replaces associations on update.")


class _Company(_Contact):
    name: Optional[str] = Field(None, max_length=1000)
    industry: Optional[str] = Field(None, max_length=1000)


class _Group(_Write):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    visibility: Optional[Literal["public", "private"]] = None
    emoji: Optional[str] = Field(None, max_length=50)


class ListPeople(_Page):
    """Return one page of workspace people."""
    operation: Literal["list_people"] = Field("list_people", json_schema_extra={"ui:hidden": True})
    name_query: Optional[str] = Field(None, max_length=500, description="Filter by name containing this text.")


class GetPerson(_Input):
    """Get a person."""
    operation: Literal["get_person"] = Field("get_person", json_schema_extra={"ui:hidden": True})
    person_id: ID


class CreatePerson(_Person):
    """Create a person."""
    operation: Literal["create_person"] = Field("create_person", json_schema_extra={"ui:hidden": True})


class UpdatePerson(_Person):
    """Update a person."""
    operation: Literal["update_person"] = Field("update_person", json_schema_extra={"ui:hidden": True})
    person_id: ID


class DeletePerson(_Write):
    """Delete a person."""
    operation: Literal["delete_person"] = Field("delete_person", json_schema_extra={"ui:hidden": True})
    person_id: ID


class ListCompanies(_Page):
    """Return one page of workspace companies."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})
    name_query: Optional[str] = Field(None, max_length=500, description="Filter by name containing this text.")


class GetCompany(_Input):
    """Get a company."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: ID


class CreateCompany(_Company):
    """Create a company."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})


class UpdateCompany(_Company):
    """Update a company."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    company_id: ID


class DeleteCompany(_Write):
    """Delete a company."""
    operation: Literal["delete_company"] = Field("delete_company", json_schema_extra={"ui:hidden": True})
    company_id: ID


class ListGroups(_Page):
    """List groups visible to the key user."""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})


class CreateGroup(_Group):
    """Create a workspace group."""
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    visibility: Literal["public", "private"]


class UpdateGroup(_Group):
    """Update group name, visibility or emoji."""
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"ui:hidden": True})
    group_id: ID


class ListUsers(_Page):
    """List workspace users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class GetCurrentUser(_Input):
    """Identify the user owning this API key."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class GetUser(_Input):
    """Get a workspace user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: ID


class ListNotes(_Page):
    """List notes, optionally filtered by linked entity and text."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    entity_id: Optional[ID] = None
    query: Optional[str] = Field(None, max_length=500)


class CreateNote(_Write):
    """Create a note on a person, company or object; optionally reply to a note."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    entity_id: ID
    content: str = Field(..., min_length=1, max_length=100000)
    visibility: Literal["public", "private"]
    parent_note_id: Optional[ID] = None


class GetNote(_Input):
    """Get a note."""
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})
    note_id: ID


class UpdateNote(_Write):
    """Update note content or visibility."""
    operation: Literal["update_note"] = Field("update_note", json_schema_extra={"ui:hidden": True})
    note_id: ID
    content: Optional[str] = Field(None, min_length=1, max_length=100000)
    visibility: Optional[Literal["public", "private"]] = None


class DeleteNote(_Write):
    """Delete a note."""
    operation: Literal["delete_note"] = Field("delete_note", json_schema_extra={"ui:hidden": True})
    note_id: ID


class ListReminders(_Page):
    """List reminders, optionally filtered by linked entity."""
    operation: Literal["list_reminders"] = Field("list_reminders", json_schema_extra={"ui:hidden": True})
    entity_id: Optional[ID] = None


class GetReminder(_Input):
    """Get a reminder."""
    operation: Literal["get_reminder"] = Field("get_reminder", json_schema_extra={"ui:hidden": True})
    reminder_id: ID


class GetCredits(_Input):
    """Read metered feature usage and limits; this endpoint is not paginated."""
    operation: Literal["get_credits"] = Field("get_credits", json_schema_extra={"ui:hidden": True})


# Folk's own MCP server: agents get its tools through a person's Folk sign-in.
FolkMcpCredential = mcp_credential("folk", "https://mcp.folk.app/mcp", app="Folk")
FolkCredential = Union[FolkAPIKeyCredential, FolkMcpCredential]


FolkConfig = Annotated[Union[ListPeople, GetPerson, CreatePerson, UpdatePerson, DeletePerson, ListCompanies, GetCompany, CreateCompany, UpdateCompany, DeleteCompany, ListGroups, CreateGroup, UpdateGroup, ListUsers, GetCurrentUser, GetUser, ListNotes, CreateNote, GetNote, UpdateNote, DeleteNote, ListReminders, GetReminder, GetCredits], Field(discriminator="operation")]


class FolkFullConfig(NodeConfig[FolkConfig, FolkCredential]):
    pass


ROUTES = {
    'list_people': ('GET', '/v1/people'),
    'get_person': ('GET', '/v1/people/{person_id}'),
    'create_person': ('POST', '/v1/people'),
    'update_person': ('PATCH', '/v1/people/{person_id}'),
    'delete_person': ('DELETE', '/v1/people/{person_id}'),
    'list_companies': ('GET', '/v1/companies'),
    'get_company': ('GET', '/v1/companies/{company_id}'),
    'create_company': ('POST', '/v1/companies'),
    'update_company': ('PATCH', '/v1/companies/{company_id}'),
    'delete_company': ('DELETE', '/v1/companies/{company_id}'),
    'list_groups': ('GET', '/v1/groups'),
    'create_group': ('POST', '/v1/groups'),
    'update_group': ('PATCH', '/v1/groups/{group_id}'),
    'list_users': ('GET', '/v1/users'),
    'get_current_user': ('GET', '/v1/users/me'),
    'get_user': ('GET', '/v1/users/{user_id}'),
    'list_notes': ('GET', '/v1/notes'),
    'create_note': ('POST', '/v1/notes'),
    'get_note': ('GET', '/v1/notes/{note_id}'),
    'update_note': ('PATCH', '/v1/notes/{note_id}'),
    'delete_note': ('DELETE', '/v1/notes/{note_id}'),
    'list_reminders': ('GET', '/v1/reminders'),
    'get_reminder': ('GET', '/v1/reminders/{reminder_id}'),
    'get_credits': ('GET', '/v1/credits'),
}


class FolkNode(WorkflowNode):
    integration_type = "automation-folk"
    credential_provider_labels = {"folk": "Folk Account"}
    connection_evidence = ConnectionEvidence(noun="Folk user", identity_operation="get_current_user", identity_keys=("fullName", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return FolkFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Folk API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, template = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation", "idempotency_key"})
        path = template
        for name in list(values):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", values.pop(name))
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json", "X-API-Version": "2025-06-09"}
        if getattr(op, "idempotency_key", None):
            headers["Idempotency-Key"] = op.idempotency_key
        params, body = {}, None
        if method == "GET":
            params = values
            if "entity_id" in params:
                params["entity.id"] = params.pop("entity_id")
            if "name_query" in params:
                attribute = "fullName" if op.operation == "list_people" else "name"
                params["filter[" + attribute + "][like]"] = params.pop("name_query")
        else:
            body = values if method != "DELETE" else None
            if body is not None:
                for source, target in (("group_ids", "groups"), ("company_ids", "companies")):
                    if source in body:
                        body[target] = [{"id": value} for value in body.pop(source)]
                for source, target in (("entity_id", "entity"), ("parent_note_id", "parentNote")):
                    if source in body:
                        body[target] = {"id": body.pop(source)}
                if not body:
                    raise ValueError("Supply at least one field to write")
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("Folk request could not be confirmed; inspect writes before retrying") from None
        if response.status_code != 200:
            try:
                error = response.json()
                message = error.get("error", {}).get("message") if isinstance(error.get("error"), dict) else error.get("message")
            except (ValueError, AttributeError):
                message = None
            safe = str(message).replace(key, "[redacted]")[:1000] if message else "Request was not confirmed"
            raise ValueError(f"Folk HTTP {response.status_code}: {safe}")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Folk returned invalid JSON; inspect writes before retrying") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict) or "error" in payload:
            raise ValueError("Folk response is missing its data object; inspect writes before retrying")
        data = payload["data"]
        output = {"status": "success", "data": data, "http_status": response.status_code}
        if op.operation.startswith("list_"):
            if not isinstance(data.get("items"), list) or not isinstance(data.get("pagination"), dict):
                raise ValueError("Folk returned an invalid page")
            link = data["pagination"].get("nextLink")
            cursor = None
            if link is not None:
                if not isinstance(link, str):
                    raise ValueError("Folk returned an invalid next page")
                parts = urlsplit(link)
                if parts.scheme != "https" or parts.netloc != "api.folk.app" or parts.path != path or parts.fragment:
                    raise ValueError("Folk returned a next page outside the requested resource")
                cursors = parse_qs(parts.query).get("cursor", [])
                if len(cursors) != 1 or not 1 <= len(cursors[0]) <= 512 or cursors[0] == getattr(op, "cursor", None):
                    raise ValueError("Folk returned an invalid or nonadvancing cursor")
                cursor = cursors[0]
            output.update(items=data["items"], next_cursor=cursor, has_more=cursor is not None)
        elif op.operation != "get_credits" and not isinstance(data.get("id"), str):
            raise ValueError("Folk response is missing its resource ID")
        for name, value in op.model_dump().items():
            if "{" + name + "}" in template and data.get("id") != value:
                raise ValueError("Folk returned a different resource ID")
        # A provider acknowledgement is not a read-back proof.
        if method != "GET":
            output["write_acknowledged"] = True
        def redact(value):
            if isinstance(value, str):
                return value.replace(key, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {name: redact(item) for name, item in value.items()}
            return value
        output = redact(output)
        await self.emit(output)
        return output
