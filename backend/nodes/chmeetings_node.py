"""Chmeetings API 1.0 people, groups, notes and directory operations.

Contract: https://api.chmeetings.com/openapi/v1.json. Each operation sends
one request; paged reads expose the next page without silently fetching more.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.chmeetings.com"
ResourceID = Annotated[int, Field(ge=1, le=9223372036854775807)]


class ChmeetingsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Chmeetings API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://help.chmeetings.com/hc/en-us/articles/4407466673937-Developer-API-Guide",
        "x-credential-instructions": "Copy your Chmeetings API key from Settings → Integrations → API Integration (Get API). Paste only the key. NoClick sends it in the apikey header to api.chmeetings.com. Connection testing reads your groups; it does not verify permission for every operation.",
    })
    credential_type: Literal["chmeetings_api_key"] = Field("chmeetings_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Chmeetings API key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, le=2147483647, description="Page number, starting at 1.")
    page_size: int = Field(100, ge=1, le=100)


class ListPeople(_Page):
    """Read one page of people, optionally filtered by name, email or mobile."""
    operation: Literal["list_people"] = "list_people"
    include_family_members: bool = True
    include_additional_fields: bool = True
    include_organizations: bool = False
    include_groups: bool = False
    name: str | None = None
    email: str | None = None
    mobile: str | None = None
    has_email: bool | None = None
    has_mobile: bool | None = None
    do_not_email: bool | None = None
    do_not_text: bool | None = None


class GetPerson(_Input):
    operation: Literal["get_person"] = "get_person"
    id: ResourceID = Field(..., title="Person ID")


class _PersonFields(_Input):
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    middle_name: str | None = None
    nick_name: str | None = None
    email: str | None = None
    mobile: str | None = None
    telephone: str | None = None
    birth_date: date | None = None
    gender: Literal["male", "female", "unknown"] | None = None
    social_status: str | None = None
    job_title: str | None = None
    work_place: str | None = None
    do_not_text: bool | None = None
    do_not_email: bool | None = None


class CreatePerson(_PersonFields):
    """Create a person with contact and profile fields."""
    operation: Literal["create_person"] = "create_person"


class UpdatePerson(_PersonFields):
    """Update a person using PUT. Supply the desired name and profile fields."""
    operation: Literal["update_person"] = "update_person"
    id: ResourceID = Field(..., title="Person ID")


class DeletePerson(GetPerson):
    """Delete the selected person."""
    operation: Literal["delete_person"] = "delete_person"


class ListGroups(_Input):
    operation: Literal["list_groups"] = "list_groups"
    search_text: str | None = Field(None, description="Group name contains this text.")


class GetGroup(_Input):
    operation: Literal["get_group"] = "get_group"
    group_id: ResourceID


class _GroupFields(_Input):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, description="Rich text; HTML is accepted by Chmeetings.")
    privacy: Literal["internal", "members", "public"] | None = None
    join_request_option: Literal["open", "closed", "approval_required"] | None = None
    is_visible_to_non_members: bool | None = None
    is_members_visible: bool | None = None
    is_group_leaders_visible: bool | None = None
    is_chat_enabled: bool | None = Field(None, description="Enabling requires a group chat add-on or branded app subscription.")


class CreateGroup(_GroupFields):
    operation: Literal["create_group"] = "create_group"


class UpdateGroup(_GroupFields):
    """Update a group using PUT; supply the desired settings."""
    operation: Literal["update_group"] = "update_group"
    group_id: ResourceID


class DeleteGroup(GetGroup):
    operation: Literal["delete_group"] = "delete_group"


class AddGroupMember(_Input):
    operation: Literal["add_group_member"] = "add_group_member"
    group_id: ResourceID
    person_id: ResourceID


class RemoveGroupMember(AddGroupMember):
    operation: Literal["remove_group_member"] = "remove_group_member"


class ListNotes(_Page):
    operation: Literal["list_notes"] = "list_notes"
    person_id: ResourceID


class GetNote(_Page):
    operation: Literal["get_note"] = "get_note"
    person_id: ResourceID
    note_id: ResourceID


class CreateNote(_Input):
    operation: Literal["create_note"] = "create_note"
    person_id: ResourceID
    note: str = Field(..., min_length=1)


class UpdateNote(CreateNote):
    operation: Literal["update_note"] = "update_note"
    note_id: ResourceID


class DeleteNote(_Input):
    operation: Literal["delete_note"] = "delete_note"
    person_id: ResourceID
    note_id: ResourceID


class ListFamilies(_Page):
    operation: Literal["list_families"] = "list_families"
    search_text: str | None = None


class GetFamily(_Input):
    operation: Literal["get_family"] = "get_family"
    id: ResourceID = Field(..., title="Family ID")


class ListOrganizations(_Page):
    operation: Literal["list_organizations"] = "list_organizations"
    search_text: str | None = None


class GetOrganization(_Input):
    operation: Literal["get_organization"] = "get_organization"
    organization_id: ResourceID


ChmeetingsOperation = Annotated[Union[
    ListPeople, GetPerson, CreatePerson, UpdatePerson, DeletePerson,
    ListGroups, GetGroup, CreateGroup, UpdateGroup, DeleteGroup,
    AddGroupMember, RemoveGroupMember, ListNotes, GetNote, CreateNote, UpdateNote,
    DeleteNote, ListFamilies, GetFamily, ListOrganizations, GetOrganization,
], Field(discriminator="operation")]


class ChmeetingsNodeConfig(NodeConfig):
    config: ChmeetingsOperation
    credentials: ChmeetingsAPIKeyCredential | None = None


ROUTES = {
    "list_people": ("GET", "/api/v1/people"),
    "get_person": ("GET", "/api/v1/people/{id}"),
    "create_person": ("POST", "/api/v1/people"),
    "update_person": ("PUT", "/api/v1/people/{id}"),
    "delete_person": ("DELETE", "/api/v1/people/{id}"),
    "list_groups": ("GET", "/api/v1/groups"),
    "get_group": ("GET", "/api/v1/groups/{group_id}"),
    "create_group": ("POST", "/api/v1/groups"),
    "update_group": ("PUT", "/api/v1/groups/{group_id}"),
    "delete_group": ("DELETE", "/api/v1/groups/{group_id}"),
    "add_group_member": ("POST", "/api/v1/groups/{group_id}/memberships"),
    "remove_group_member": ("DELETE", "/api/v1/groups/{group_id}/memberships/{person_id}"),
    "list_notes": ("GET", "/api/v1/people/{person_id}/notes"),
    "get_note": ("GET", "/api/v1/people/{person_id}/notes/{note_id}"),
    "create_note": ("POST", "/api/v1/people/{person_id}/notes"),
    "update_note": ("PUT", "/api/v1/people/{person_id}/notes/{note_id}"),
    "delete_note": ("DELETE", "/api/v1/people/{person_id}/notes/{note_id}"),
    "list_families": ("GET", "/api/v1/families"),
    "get_family": ("GET", "/api/v1/families/{id}"),
    "list_organizations": ("GET", "/api/v1/organizations"),
    "get_organization": ("GET", "/api/v1/organizations/{organization_id}"),
}
EMPTY_SUCCESS = {"create_person", "update_person", "delete_person", "delete_group", "remove_group_member", "delete_note"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class ChmeetingsNode(WorkflowNode):
    integration_type = "automation-chmeetings"
    connection_evidence = ConnectionEvidence(noun="groups", operation="list_groups", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return ChmeetingsNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Chmeetings API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, route = ROUTES[op.operation]
        payload = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        for field in ("id", "group_id", "person_id", "note_id", "organization_id"):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", str(payload.pop(field)))
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in payload.items()} if method == "GET" else None
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"apikey": token, "Accept": "application/json"},
                    **({"params": params} if method == "GET" else {"json": payload} if method in {"POST", "PUT"} else {}))
        except httpx.RequestError:
            raise ValueError("Chmeetings request could not be completed; inspect any write before retrying") from None
        body = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Chmeetings returned an unexpected response; inspect any write before retrying") from None
            if not isinstance(body, dict):
                raise ValueError("Chmeetings returned an unexpected JSON envelope")
        errors = body.get("errors") if body else None
        api_status = body.get("status_code") if body else None
        if not 200 <= response.status_code < 300 or errors or (api_status is not None and str(api_status).isdigit() and int(api_status) >= 400):
            result = {"status": "error", "http_status": response.status_code,
                      "error": errors or "Chmeetings rejected the request", "retry_after": response.headers.get("Retry-After")}
        elif body is None and op.operation not in EMPTY_SUCCESS:
            raise ValueError("Chmeetings omitted the documented response")
        else:
            result = {"status": "success", "http_status": response.status_code, "data": body.get("data", body) if body is not None else None}
            if op.operation.startswith("list_"):
                if body is None or not isinstance(body.get("data"), list):
                    raise ValueError("Chmeetings omitted the documented result list")
                result["items"] = body["data"]
                if isinstance(op, _Page):
                    paging = body.get("paging")
                    if not isinstance(paging, dict):
                        raise ValueError("Chmeetings omitted pagination metadata")
                    try:
                        total = int(paging["total_count"])
                        page, size = int(paging["page"]), int(paging["page_size"])
                    except (KeyError, TypeError, ValueError):
                        raise ValueError("Chmeetings returned invalid pagination metadata") from None
                    if total < 0 or page != op.page or size != op.page_size or len(body["data"]) > size:
                        raise ValueError("Chmeetings pagination does not match the request")
                    has_more = page * size < total
                    result.update(paging=paging, has_more=has_more, next_page=page + 1 if has_more else None)
            if method != "GET":
                result["write_acknowledged"] = True
        result = _redact(result, token)
        await self.emit(result)
        return result
