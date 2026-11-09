"""Virtuous CRM actions against the provider's pinned Postman collection.

One request per operation. Imports are queued for Virtuous review; an HTTP
acknowledgement does not mean the imported contact has been created.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.virtuoussoftware.com"
CREDENTIAL = "virtuous_crm_api_key"
DOCS = "https://www.postman.com/collections/19331481-aa0c66a4-0e87-428e-b56c-40e803949ed7"


class VirtuousCRMAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Virtuous CRM API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.virtuoussoftware.com/",
            "x-credential-instructions": "In Virtuous, open API Keys, create a key with a permission group for the actions you need, and paste the key here without the Bearer prefix. NoClick verifies it by reading your current organization. The key's permissions control which records you can read and change.",
        })
    credential_type: Literal["virtuous_crm_api_key"] = Field(CREDENTIAL, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    skip: int = Field(0, ge=0, le=10000000, description="Number of records to skip; each execution reads one page.")
    take: int = Field(10, ge=1, le=100, description="Number of records to request on this page.")


class _Contact(_Input):
    contact_id: int = Field(..., gt=0, description="Virtuous contact ID.")


class _Note(_Input):
    note_id: int = Field(..., gt=0, description="Virtuous contact note ID.")


class GetCurrentOrganization(_Input):
    operation: Literal["get_current_organization"] = Field("get_current_organization", json_schema_extra={"ui:hidden": True})


class GetContact(_Contact):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class FindContact(_Input):
    operation: Literal["find_contact"] = Field("find_contact", json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., min_length=3, max_length=320, description="Find a contact by email address.")


class SearchContacts(_Page):
    operation: Literal["search_contacts"] = Field("search_contacts", json_schema_extra={"ui:hidden": True})
    search: str = Field(..., min_length=1, max_length=1000)


class ImportContact(_Input):
    operation: Literal["import_contact"] = Field("import_contact", title="Submit Contact Import", description="Queues a contact transaction for matching, duplicate checks, and organization review. Does not immediately create a contact.", json_schema_extra={"ui:hidden": True})
    contact_type: str = Field(..., min_length=1, max_length=100, description="A configured contact type, such as Household, Organization or Foundation.")
    name: str = Field(..., min_length=1, max_length=500, description="Contact or household name.")
    first_name: str | None = Field(None, max_length=200)
    last_name: str | None = Field(None, max_length=200)
    email: EmailStr | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=100)
    reference_source: str | None = Field(None, max_length=200)
    reference_id: str | None = Field(None, max_length=200)
    address1: str | None = Field(None, max_length=500)
    address2: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=200)
    state: str | None = Field(None, max_length=200)
    postal: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=200)
    tags: str | None = Field(None, max_length=2000, description="Contact tags in the provider's string format.")


class ArchiveContact(_Contact):
    operation: Literal["archive_contact"] = Field("archive_contact", description="Archive the selected contact.", json_schema_extra={"ui:hidden": True})
    archive_reason: str | None = Field(None, max_length=2000)


class UnarchiveContact(_Contact):
    operation: Literal["unarchive_contact"] = Field("unarchive_contact", json_schema_extra={"ui:hidden": True})


class ListIndividuals(_Contact):
    operation: Literal["list_individuals"] = Field("list_individuals", json_schema_extra={"ui:hidden": True})


class GetIndividual(_Input):
    operation: Literal["get_individual"] = Field("get_individual", json_schema_extra={"ui:hidden": True})
    individual_id: int = Field(..., gt=0)


class ListNotes(_Contact, _Page):
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    sort_by: Literal["Id", "NoteDate", "CreatedDateTime"] | None = None
    descending: bool | None = None


class GetNote(_Note):
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})


class _NoteBody(_Input):
    note_type: str = Field(..., min_length=1, max_length=200, description="A contact note type configured in Virtuous.")
    note: str = Field(..., min_length=1, max_length=100000)
    note_date_time: datetime = Field(..., description="ISO 8601 date and time for this note.")
    important: bool = Field(..., description="Whether the note is important.")
    private: bool = Field(..., description="Whether the note is private.")
    time_spent: int = Field(..., ge=0, description="Time spent, in the units configured by Virtuous.")



class CreateNote(_Contact, _NoteBody):
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})


class UpdateNote(_Note, _NoteBody):
    operation: Literal["update_note"] = Field("update_note", title="Replace Contact Note", description="Sends the entire editable note model. Virtuous removes omitted properties on update, so every editable field is required.", json_schema_extra={"ui:hidden": True})


class DeleteNote(_Note):
    operation: Literal["delete_note"] = Field("delete_note", description="Delete the selected contact note.", json_schema_extra={"ui:hidden": True})


class ListTags(_Contact, _Page):
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})


class AddTag(_Contact):
    operation: Literal["add_tag"] = Field("add_tag", json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(..., gt=0, description="Existing Virtuous tag ID.")


class RemoveTag(_Input):
    operation: Literal["remove_tag"] = Field("remove_tag", json_schema_extra={"ui:hidden": True})
    contact_tag_id: int = Field(..., gt=0, description="Contact-tag association ID, not the tag ID.")


class GetGift(_Input):
    operation: Literal["get_gift"] = Field("get_gift", json_schema_extra={"ui:hidden": True})
    gift_id: int = Field(..., gt=0)


class ListGifts(_Contact, _Page):
    operation: Literal["list_gifts"] = Field("list_gifts", json_schema_extra={"ui:hidden": True})


class GetProject(_Input):
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., gt=0)


class SearchProjects(_Page):
    operation: Literal["search_projects"] = Field("search_projects", json_schema_extra={"ui:hidden": True})
    search: str = Field(..., min_length=1, max_length=1000)


class ListEvents(_Page):
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})


class GetEvent(_Input):
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    event_id: int = Field(..., gt=0)


Operation = Annotated[Union[GetCurrentOrganization, GetContact, FindContact, SearchContacts,
    ImportContact, ArchiveContact, UnarchiveContact, ListIndividuals, GetIndividual,
    ListNotes, GetNote, CreateNote, UpdateNote, DeleteNote, ListTags, AddTag, RemoveTag,
    GetGift, ListGifts, GetProject, SearchProjects, ListEvents, GetEvent], Field(discriminator="operation")]


class VirtuousCRMConfig(NodeConfig[Operation, VirtuousCRMAPIKeyCredential]):
    pass


# Each operation maps to exactly one published collection request.
ROUTES = {
    "get_current_organization": ("GET", "/api/Organization/Current"),
    "get_contact": ("GET", "/api/Contact/{contact_id}"),
    "find_contact": ("GET", "/api/Contact/Find"),
    "search_contacts": ("POST", "/api/Contact/Search"),
    "import_contact": ("POST", "/api/Contact/Transaction"),
    "archive_contact": ("PUT", "/api/Contact/Archive/{contact_id}"),
    "unarchive_contact": ("PUT", "/api/Contact/Unarchive/{contact_id}"),
    "list_individuals": ("GET", "/api/ContactIndividual/ByContact/{contact_id}"),
    "get_individual": ("GET", "/api/ContactIndividual/{individual_id}"),
    "list_notes": ("GET", "/api/ContactNote/ByContact/{contact_id}"),
    "get_note": ("GET", "/api/ContactNote/{note_id}"),
    "create_note": ("POST", "/api/ContactNote"),
    "update_note": ("PUT", "/api/ContactNote/{note_id}"),
    "delete_note": ("DELETE", "/api/ContactNote/{note_id}"),
    "list_tags": ("GET", "/api/ContactTag/ByContact/{contact_id}"),
    "add_tag": ("POST", "/api/ContactTag"),
    "remove_tag": ("DELETE", "/api/ContactTag/{contact_tag_id}"),
    "get_gift": ("GET", "/api/Gift/{gift_id}"),
    "list_gifts": ("GET", "/api/Gift/ByContact/{contact_id}"),
    "get_project": ("GET", "/api/Project/{project_id}"),
    "search_projects": ("POST", "/api/Project/Search"),
    "list_events": ("GET", "/api/Event"),
    "get_event": ("GET", "/api/Event/{event_id}"),
}
IMPORT_FIELDS = {"contact_type": "contactType", "first_name": "firstName", "last_name": "lastName",
    "reference_source": "referenceSource", "reference_id": "referenceId"}
NOTE_FIELDS = {"note_type": "type", "note": "note", "note_date_time": "noteDateTime",
    "important": "important", "private": "private", "time_spent": "timeSpent"}
EMPTY_SUCCESS = {"import_contact", "archive_contact", "delete_note", "remove_tag"}


class VirtuousCRMNode(WorkflowNode):
    integration_type = "automation-virtuous-crm"
    connection_evidence = ConnectionEvidence(noun="Virtuous organization", identity_operation="get_current_organization", identity_keys=("organizationName",))

    @classmethod
    def get_config_model(cls):
        return VirtuousCRMConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Virtuous CRM API key")
        op = self.config.config
        values = op.model_dump(mode="json", exclude_none=True)
        method, route = ROUTES[op.operation]
        route = route.format(**values)  # All path fields are validated positive integer IDs.
        params = {key: values[key] for key in ("skip", "take") if key in values}
        body = None
        if isinstance(op, FindContact):
            params["email"] = op.email
        if isinstance(op, (SearchContacts, SearchProjects)):
            body = {"search": op.search}
        elif isinstance(op, ImportContact):
            body = {IMPORT_FIELDS.get(k, k): v for k, v in values.items() if k != "operation"}
        elif isinstance(op, ArchiveContact):
            body = {"archiveReason": op.archive_reason} if op.archive_reason is not None else {}
        elif isinstance(op, (CreateNote, UpdateNote)):
            body = {wire: values[key] for key, wire in NOTE_FIELDS.items()}
            if isinstance(op, CreateNote):
                body["contactId"] = op.contact_id
        elif isinstance(op, AddTag):
            body = {"tagId": op.tag_id, "contactId": op.contact_id}
        if isinstance(op, ListNotes):
            if op.sort_by is not None:
                params["sortBy"] = op.sort_by
            if op.descending is not None:
                params["descending"] = str(op.descending).lower()
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + route, params=params,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        # Preserve the provider's rejection for the shared connection verifier.
        # Never retry writes: a timeout could have happened after acceptance.
        if not 200 <= response.status_code < 300:
            message = response.text.replace(key, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "status_code": response.status_code,
                "error": message or f"Virtuous CRM returned HTTP {response.status_code}"}
        if not response.content:
            if op.operation not in EMPTY_SUCCESS:
                raise ValueError("Virtuous CRM returned an unexpected empty response")
            data = None
        else:
            if len(response.content) > 10000000:
                raise ValueError("Virtuous CRM response exceeds 10 MB")
            media = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if media != "application/json" and not media.endswith("+json"):
                raise ValueError("Expected a Virtuous CRM JSON response")
            data = response.json()
            if isinstance(op, GetCurrentOrganization):
                if not isinstance(data, dict) or not isinstance(data.get("organizationName"), str) or not data["organizationName"]:
                    raise ValueError("Virtuous CRM did not return an organization name")
        result = {"status": "success", "http_status": response.status_code, "data": data}
        if isinstance(op, GetCurrentOrganization):
            result["name"] = data["organizationName"]
        if isinstance(op, ImportContact):
            result["import_submitted"] = True
            result["contact_created"] = False
        if isinstance(op, _Page):
            rows = data.get("list") if isinstance(data, dict) else None
            total = data.get("total") if isinstance(data, dict) else None
            known = isinstance(rows, list) and type(total) is int
            result["next_skip"] = op.skip + len(rows) if known and rows and op.skip + len(rows) < total else None
            result["has_more"] = op.skip + len(rows) < total if known else None
        return result
