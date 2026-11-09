"""Levitate Public API v1: one published endpoint per operation, one page per read.

Contract: https://api.levitate.ai/openapi/public-v1.json (1.0.0).
Personal key setup: https://help.levitate.ai/article/735-levitate-public-api.
"""
from __future__ import annotations

from datetime import date as calendar_date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.levitate import LEVITATE_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://api.levitate.ai"


class LevitateAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Levitate Personal API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.levitate.ai/article/735-levitate-public-api",
            "x-credential-instructions": "In Levitate, open your name menu, Integrations, Personal API Keys, Manage, then Create API Key. Select levitate:contacts and paste the key without the Bearer prefix. Public API access must be enabled on your account. Keys expire after 30, 90, 180 or 365 days; replace this credential before expiry. Zapier and MCP keys do not work here. NoClick reads a page of your contacts to check the key."
        })
    credential_type: Literal["levitate_api_key"] = Field("levitate_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="Personal API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Personal API key", key=True)
        if not value.isascii() or any(ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in value):
            raise ValueError("Paste only the personal API key without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ID = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^[^/\\?#\s]+$")]
Tag = Annotated[str, Field(min_length=1, max_length=100)]


class _Page(_Input):
    limit: int = Field(25, ge=1, le=100, description="Maximum rows in this page; use next_page_token to continue with the same filters.")
    pageToken: str | None = Field(None, min_length=1, max_length=8192, title="Page token")


class Address(_Input):
    address1: str | None = Field(None, max_length=200)
    address2: str | None = Field(None, max_length=200)
    city: str | None = Field(None, max_length=100)
    stateProvince: str | None = Field(None, max_length=100)
    postalCode: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=100)


class EmailAddress(_Input):
    label: str = Field("Work", max_length=50)
    value: str = Field(..., min_length=3, max_length=254)


class PhoneNumber(_Input):
    label: str | None = Field(None, max_length=50)
    value: str = Field(..., min_length=1, max_length=50)


class _CompanyFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    emailDomains: list[str] | None = Field(None, max_length=25, description="Company email domains; on update the entire array is replaced.")
    webSite: str | None = Field(None, max_length=2048)
    logoUrl: str | None = Field(None, max_length=2048)
    phoneNumbers: list[PhoneNumber] | None = Field(None, max_length=25, description="Replaces all phone numbers on update.")
    tags: list[Tag] | None = Field(None, max_length=50, description="Replaces all tags on update; [] clears tags. New tag names are created automatically.")
    address: Address | None = None


class _ContactFields(_Input):
    firstName: str | None = Field(None, max_length=100)
    lastName: str | None = Field(None, max_length=100)
    jobTitle: str | None = Field(None, max_length=200)
    emailAddresses: list[EmailAddress] | None = Field(None, max_length=25, description="First entry is primary. Replaces all email addresses on update.")
    phoneNumbers: list[PhoneNumber] | None = Field(None, max_length=25, description="First entry is primary. Replaces all phone numbers on update.")
    address: Address | None = None
    website: str | None = Field(None, max_length=2048)
    bio: str | None = Field(None, max_length=5000)
    tags: list[Tag] | None = Field(None, max_length=50, description="Replaces the entire tag list on update; [] clears tags. New tag names are created automatically.")
    customFields: dict[str, str] | None = Field(None, description="Account-defined name/value pairs. Replaces the entire object on update; {} clears it.")
    visibility: Literal["shared", "private"] | None = None


class KeyDate(_Input):
    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=31)
    year: int | None = Field(None, ge=1, le=9999)

    @model_validator(mode="after")
    def valid_date(self):
        calendar_date(self.year or 2000, self.month, self.day)
        return self


class _KeyFactFields(_Input):
    type: Literal["Unknown", "Birthday", "Renewal", "Anniversary", "Wedding", "FinancialReview", "Custom1", "Custom2", "Custom3", "Custom4", "Custom5", "Custom6", "Custom7", "Custom8", "Custom9", "Custom10"]
    value: str | None = Field(None, min_length=1, max_length=1000)
    date: KeyDate | None = None

    @model_validator(mode="after")
    def content(self):
        if not self.value and self.date is None:
            raise ValueError("Supply a key fact value or date")
        return self


class NoteReference(_Input):
    type: Literal["contact", "company"]
    id: ID


class ContactFilter(_Input):
    op: Literal["and", "or", "not"] | None = None
    filters: list[ContactFilter] | None = None
    field: str | None = None
    operator: str | None = None
    value: str | None = None

    @model_validator(mode="after")
    def tree(self):
        count = 0
        def visit(node, depth):
            nonlocal count
            if depth > 5:
                raise ValueError("Filters may nest at most five levels")
            if node.op:
                if node.field is not None or node.operator is not None or node.value is not None or not node.filters:
                    raise ValueError("A group needs only op and child filters")
                if node.op == "not" and len(node.filters) != 1:
                    raise ValueError("A not group requires exactly one child")
                for child in node.filters:
                    visit(child, depth + 1)
            else:
                allowed = {
                    "name": {"contains"}, "email": {"equals"}, "company": {"equals"},
                    "companyName": {"contains"}, "tags": {"contains", "notContains"},
                    "city": {"equals", "startsWith"}, "stateProvince": {"equals", "startsWith"},
                    "postalCode": {"startsWith"}, "source": {"equals"},
                    "createdAt": {"before", "after", "on"}, "updatedAt": {"before", "after", "on"},
                    "lastCommunicationDate": {"before", "after", "on", "isNull"},
                    **{k: {"equals"} for k in ("visibility", "emailSubscribed", "textSubscribed", "hasEmail", "hasPhone")},
                }
                operators = {"equals", "isEmpty", "isNotEmpty"} if node.field and node.field.startswith("customFields.") else allowed.get(node.field, set())
                if node.filters is not None or node.operator not in operators:
                    raise ValueError("Use a documented field and operator for a condition")
                if node.value is None and node.operator not in {"isNull", "isEmpty", "isNotEmpty"}:
                    raise ValueError("A condition requires a string value")
                count += 1
        visit(self, 1)
        if count > 50:
            raise ValueError("Use at most 50 filter conditions")
        return self


class GetCompany(_Input):
    """Get Company by Id."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})
    company_id: ID


class UpdateCompany(_CompanyFields):
    """Update a company."""
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"ui:hidden": True})
    company_id: ID


class DeleteCompany(_Input):
    """Delete a company. Permanently removes the company and detaches its contacts."""
    operation: Literal["delete_company"] = Field("delete_company", json_schema_extra={"ui:hidden": True})
    company_id: ID


class ListCompanies(_Page):
    """List companies."""
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, max_length=1000)
    tags: list[Tag] | None = Field(None, max_length=10, description="Repeatable tag filters combine with AND.")
    sort: Literal['name', '-name', 'creationDate', '-creationDate'] | None = None


class CreateCompany(_CompanyFields):
    """Create a company."""
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=200)


class GetContact(_Input):
    """Get Contact by Id."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: ID


class UpdateContact(_ContactFields):
    """Update a contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: ID


class ListContacts(_Page):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, max_length=1000)
    email: str | None = Field(None, max_length=1000)
    companyName: str | None = Field(None, max_length=1000)
    tags: list[Tag] | None = Field(None, max_length=10, description="Repeatable tag filters combine with AND.")
    location: str | None = Field(None, max_length=1000)
    createdAfter: str | None = Field(None, max_length=1000)
    createdBefore: str | None = Field(None, max_length=1000)
    updatedAfter: str | None = Field(None, max_length=1000)
    updatedBefore: str | None = Field(None, max_length=1000)
    lastCommunicatedAfter: str | None = Field(None, max_length=1000)
    lastCommunicatedBefore: str | None = Field(None, max_length=1000)
    sort: Literal['name', '-name', 'creationDate', '-creationDate'] | None = None


class CreateContact(_ContactFields):
    """Create a contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def identity(self):
        if not self.emailAddresses and not (self.firstName and self.lastName):
            raise ValueError("Supply an email address or both first and last name")
        return self


class SearchContacts(_Page):
    """Search contacts with a boolean filter."""
    operation: Literal["search_contacts"] = Field("search_contacts", json_schema_extra={"ui:hidden": True})
    sort: Literal['name', '-name', 'creationDate', '-creationDate'] | None = None
    filter: ContactFilter


class ListContactKeyFacts(_Input):
    """List a contact's key facts."""
    operation: Literal["list_contact_key_facts"] = Field("list_contact_key_facts", json_schema_extra={"ui:hidden": True})
    contact_id: ID


class AddContactKeyFact(_KeyFactFields):
    """Add a key fact to a contact."""
    operation: Literal["add_contact_key_fact"] = Field("add_contact_key_fact", json_schema_extra={"ui:hidden": True})
    contact_id: ID


class GetContactKeyFact(_Input):
    """Get one of a contact's key facts by Id."""
    operation: Literal["get_contact_key_fact"] = Field("get_contact_key_fact", json_schema_extra={"ui:hidden": True})
    contact_id: ID
    key_fact_id: ID


class ReplaceContactKeyFact(_KeyFactFields):
    """Replace one of a contact's key facts. Full replacement: omitted fields are cleared; integration-owned facts cannot be changed."""
    operation: Literal["replace_contact_key_fact"] = Field("replace_contact_key_fact", json_schema_extra={"ui:hidden": True})
    contact_id: ID
    key_fact_id: ID


class DeleteContactKeyFact(_Input):
    """Delete one of a contact's key facts."""
    operation: Literal["delete_contact_key_fact"] = Field("delete_contact_key_fact", json_schema_extra={"ui:hidden": True})
    contact_id: ID
    key_fact_id: ID


class GetNote(_Input):
    """Get Note by Id."""
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})
    note_id: ID


class DeleteNote(_Input):
    """Delete a note."""
    operation: Literal["delete_note"] = Field("delete_note", json_schema_extra={"ui:hidden": True})
    note_id: ID


class ListNotes(_Page):
    """List and filter notes."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})
    contactId: str | None = Field(None, max_length=1000)
    companyId: str | None = Field(None, max_length=1000)
    createdAfter: str | None = Field(None, max_length=1000)
    createdBefore: str | None = Field(None, max_length=1000)
    updatedAfter: str | None = Field(None, max_length=1000)
    updatedBefore: str | None = Field(None, max_length=1000)
    sort: Literal['creationDate', '-creationDate'] | None = None


class CreateNote(_Input):
    """Log a note."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, max_length=100000, description="HTML fragment. Levitate sanitizes markup and adds the lev-content wrapper; omit that wrapper.")
    references: list[NoteReference] = Field(..., min_length=1, max_length=25)
    visibility: Literal["shared", "private"] | None = None


LevitateConfig = Annotated[Union[GetCompany, UpdateCompany, DeleteCompany, ListCompanies, CreateCompany, GetContact, UpdateContact, ListContacts, CreateContact, SearchContacts, ListContactKeyFacts, AddContactKeyFact, GetContactKeyFact, ReplaceContactKeyFact, DeleteContactKeyFact, GetNote, DeleteNote, ListNotes, CreateNote], Field(discriminator="operation")]


class LevitateFullConfig(NodeConfig[LevitateConfig, LevitateAPIKeyCredential]):
    pass


ROUTES = {
    "get_company": ('GET', '/public/v1/Companies/{company_id}'),
    "update_company": ('PATCH', '/public/v1/Companies/{company_id}'),
    "delete_company": ('DELETE', '/public/v1/Companies/{company_id}'),
    "list_companies": ('GET', '/public/v1/Companies'),
    "create_company": ('POST', '/public/v1/Companies'),
    "get_contact": ('GET', '/public/v1/Contacts/{contact_id}'),
    "update_contact": ('PATCH', '/public/v1/Contacts/{contact_id}'),
    "list_contacts": ('GET', '/public/v1/Contacts'),
    "create_contact": ('POST', '/public/v1/Contacts'),
    "search_contacts": ('POST', '/public/v1/Contacts/search'),
    "list_contact_key_facts": ('GET', '/public/v1/Contacts/{contact_id}/keyfacts'),
    "add_contact_key_fact": ('POST', '/public/v1/Contacts/{contact_id}/keyfacts'),
    "get_contact_key_fact": ('GET', '/public/v1/Contacts/{contact_id}/keyfacts/{key_fact_id}'),
    "replace_contact_key_fact": ('PUT', '/public/v1/Contacts/{contact_id}/keyfacts/{key_fact_id}'),
    "delete_contact_key_fact": ('DELETE', '/public/v1/Contacts/{contact_id}/keyfacts/{key_fact_id}'),
    "get_note": ('GET', '/public/v1/Notes/{note_id}'),
    "delete_note": ('DELETE', '/public/v1/Notes/{note_id}'),
    "list_notes": ('GET', '/public/v1/Notes'),
    "create_note": ('POST', '/public/v1/Notes'),
}


class LevitateNode(WorkflowNode):
    integration_type = "automation-levitate"
    scope_registry = LEVITATE_SCOPES
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts")

    @classmethod
    def get_config_model(cls):
        return LevitateFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Levitate personal API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, template = ROUTES[op.operation]
        path = template
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for name in list(values):
            if "{" + name + "}" in path:
                identifier = values.pop(name)
                if identifier in {".", ".."}:
                    raise ValueError("Use a Levitate resource ID")
                path = path.replace("{" + name + "}", quote(identifier, safe=""))
        params, body = {}, None
        if method == "GET":
            params = values
        elif method != "DELETE":
            body = values
            if op.operation == "search_contacts":
                params = {name: body.pop(name) for name in ("limit", "pageToken", "sort") if name in body}
            if not body:
                raise ValueError("Supply at least one field to write")
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("Levitate request could not be confirmed; inspect writes before retrying") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Levitate HTTP {response.status_code}: invalid JSON; inspect writes before retrying") from None
        expected_status = 201 if op.operation in {"create_contact", "create_company", "create_note", "add_contact_key_fact"} else 200
        if response.status_code != expected_status or not isinstance(payload, dict) or payload.get("success") is not True:
            message = payload.get("systemMessage") if isinstance(payload, dict) else None
            safe = str(message).replace(key, "[redacted]")[:1000] if message else "Request was not confirmed"
            raise ValueError(f"Levitate HTTP {response.status_code}: {safe}")
        output = {"status": "success", "http_status": response.status_code}
        if method == "DELETE":
            output.update(deleted_id=getattr(op, "key_fact_id", getattr(op, "company_id", getattr(op, "note_id", None))), write_acknowledged=True)
        else:
            value = payload.get("value")
            if not isinstance(value, dict):
                raise ValueError("Levitate returned no value object; inspect writes before retrying")
            output["data"] = value
            if op.operation.startswith("list_") or op.operation == "search_contacts":
                items = value.get("values")
                token = value.get("pageToken")
                if items is not None and not isinstance(items, list):
                    raise ValueError("Levitate returned invalid rows")
                if token is not None and (not isinstance(token, str) or not token or token == getattr(op, "pageToken", None)):
                    raise ValueError("Levitate returned an invalid or nonadvancing cursor")
                output.update(items=items or [], next_page_token=token, has_more=token is not None)
            if method not in {"GET"} and op.operation != "search_contacts":
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
