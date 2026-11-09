"""VaultRE v1.3: manual integrator API key plus account access token.

Contract: https://docs.api.vaultre.com.au/swagger/vaultre.yaml
Auth: https://docs.api.vaultre.com.au/guide.html
Every operation performs one documented request. Lists return one page only;
provider pagination links are never followed with credentials.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://ap-southeast-2.api.vaultre.com.au/api/v1.3"


class VaultREAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="VaultRE API Key and Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.api.vaultre.com.au/basics.html",
            "x-credential-instructions": "Register as an approved integrator before connecting. Paste your integrator API key and an account access token from Office Integrations > Third-Party Access. The account owner chooses the token's permissions. Both values are required.",
        },
    )
    credential_type: Literal["vaultre_api_key"] = Field("vaultre_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Integrator API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    access_token: str = Field(..., title="Account Access Token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "access_token", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="VaultRE secret")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the secret without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page Number")
    page_size: int = Field(50, ge=1, le=100, title="Page Size", description="Returns one page. Use next_page for the following request.")


def _datetime(value):
    if value is None:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Use an ISO 8601 datetime with a timezone") from None
    return value


class _Modified(_Page):
    modified_since: str | None = Field(None, title="Modified Since", json_schema_extra={"format": "date-time"})
    modified_before: str | None = Field(None, title="Modified Before", json_schema_extra={"format": "date-time"})
    _dates = field_validator("modified_since", "modified_before")(_datetime)


class _Contact(_Input):
    contact_id: int = Field(..., ge=1, title="Contact ID")


class _Task(_Input):
    task_id: int = Field(..., ge=1, title="Task ID")


class _Property(_Input):
    property_id: int = Field(..., ge=1, title="Property ID")


class _ContactFields(_Input):
    first_name: str | None = Field(None, max_length=500, title="First Name")
    last_name: str | None = Field(None, max_length=500, title="Last Name")
    company: str | None = Field(None, max_length=500)
    position: str | None = Field(None, max_length=500)
    emails: list[Annotated[str, Field(json_schema_extra={"format": "email"})]] | None = Field(None, title="Email Addresses", description="Replaces the email array when supplied. Omit to leave unchanged.")
    archived: bool | None = None
    on_do_not_call_list: bool | None = Field(None, title="Do Not Call")

    @field_validator("emails")
    @classmethod
    def email_addresses(cls, values):
        if values is not None and any(not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", v) for v in values):
            raise ValueError("Provide valid email addresses")
        return values

    @model_validator(mode="after")
    def nonempty(self):
        names = ("first_name", "last_name", "company", "position", "emails", "archived", "on_do_not_call_list")
        if not any(getattr(self, name) is not None for name in names):
            raise ValueError("Provide at least one contact field")
        return self


class _TaskFields(_Input):
    subject: str | None = Field(None, min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=100000, json_schema_extra={"ui:widget": "textarea"})
    start: str | None = Field(None, json_schema_extra={"format": "date-time"})
    _start = field_validator("start")(_datetime)

    @model_validator(mode="after")
    def nonempty(self):
        if all(getattr(self, name) is None for name in ("subject", "description", "start")):
            raise ValueError("Provide at least one task field")
        return self


class GetAccount(_Input):
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"ui:hidden": True})


class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Current User", json_schema_extra={"ui:hidden": True})


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, title="Email Filter")
    team_id: int | None = Field(None, ge=1)


class ListContactCategories(_Page):
    operation: Literal["list_contact_categories"] = Field("list_contact_categories", title="List Contact Categories", json_schema_extra={"ui:hidden": True})


class ListContacts(_Modified):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    archived: bool | None = None


class SearchContacts(_Page):
    operation: Literal["search_contacts"] = Field("search_contacts", title="Search Contacts", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=4, max_length=500)
    email: str | None = Field(None, min_length=4, max_length=500)
    phone: str | None = Field(None, min_length=4, max_length=100)
    fuzzy: bool = True
    archived: bool | None = None

    @model_validator(mode="after")
    def search_term(self):
        if not any((self.name, self.email, self.phone)):
            raise ValueError("Provide a name, email or phone with at least four characters")
        return self


class GetContact(_Contact):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})


class UpdateContact(_Contact, _ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})


class DeleteContact(_Contact):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True})


class ListContactNotes(_Contact, _Page):
    operation: Literal["list_contact_notes"] = Field("list_contact_notes", title="List Contact Notes", json_schema_extra={"ui:hidden": True})


class CreateContactNote(_Contact):
    operation: Literal["create_contact_note"] = Field("create_contact_note", title="Create Contact Note", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, max_length=100000, title="Note Text", json_schema_extra={"ui:widget": "textarea"})
    note_type_id: int | None = Field(None, ge=1, title="Note Type ID")
    read_only: bool | None = None


class ListTasks(_Page):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True})
    user_id: int | None = Field(None, ge=1, title="Assigned User ID")
    completed: bool | None = None
    starting_after: str | None = Field(None, json_schema_extra={"format": "date-time"})
    starting_before: str | None = Field(None, json_schema_extra={"format": "date-time"})
    _dates = field_validator("starting_after", "starting_before")(_datetime)


class GetTask(_Task):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True})


class CreateTask(_TaskFields):
    operation: Literal["create_task"] = Field("create_task", title="Create Task", json_schema_extra={"ui:hidden": True})
    subject: str = Field(..., min_length=1, max_length=1000)
    start: str = Field(..., json_schema_extra={"format": "date-time"})
    user_id: int = Field(..., ge=1, title="Assigned User ID")


class UpdateTask(_Task, _TaskFields):
    operation: Literal["update_task"] = Field("update_task", title="Update Task", json_schema_extra={"ui:hidden": True})


class DeleteTask(_Task):
    operation: Literal["delete_task"] = Field("delete_task", title="Delete Task", json_schema_extra={"ui:hidden": True})


class CompleteTask(_Task):
    operation: Literal["complete_task"] = Field("complete_task", title="Complete Task", json_schema_extra={"ui:hidden": True})


class UncompleteTask(_Task):
    operation: Literal["uncomplete_task"] = Field("uncomplete_task", title="Uncomplete Task", json_schema_extra={"ui:hidden": True})


class ListSaleProperties(_Modified):
    operation: Literal["list_sale_properties"] = Field("list_sale_properties", title="List Sale Properties", json_schema_extra={"ui:hidden": True})
    status: Literal["prospect", "appraisal", "listing", "conditional", "listingOrConditional", "unconditional"] | None = None


class GetSaleProperty(_Property):
    operation: Literal["get_sale_property"] = Field("get_sale_property", title="Get Sale Property", json_schema_extra={"ui:hidden": True})


class ListLeaseProperties(_Modified):
    operation: Literal["list_lease_properties"] = Field("list_lease_properties", title="List Lease Properties", json_schema_extra={"ui:hidden": True})
    status: Literal["prospect", "appraisal", "management"] | None = None
    available_only: bool | None = None


class GetLeaseProperty(_Property):
    operation: Literal["get_lease_property"] = Field("get_lease_property", title="Get Lease Property", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetAccount, GetCurrentUser, ListUsers, ListContactCategories, ListContacts, SearchContacts, GetContact, CreateContact, UpdateContact, DeleteContact, ListContactNotes, CreateContactNote, ListTasks, GetTask, CreateTask, UpdateTask, DeleteTask, CompleteTask, UncompleteTask, ListSaleProperties, GetSaleProperty, ListLeaseProperties, GetLeaseProperty], Field(discriminator="operation")]


class VaultREConfig(NodeConfig[Operation, VaultREAPIKeyCredential]):
    pass


# One operation -> one published method/path; no arbitrary request escape hatch.
ROUTES = {
    "get_account": ("GET", "/account"),
    "get_current_user": ("GET", "/user"),
    "list_users": ("GET", "/account/users"),
    "list_contact_categories": ("GET", "/categories/contact"),
    "list_contacts": ("GET", "/contacts"),
    "search_contacts": ("GET", "/search/contacts"),
    "get_contact": ("GET", "/contacts/{contact_id}"),
    "create_contact": ("POST", "/contacts"),
    "update_contact": ("PUT", "/contacts/{contact_id}"),
    "delete_contact": ("DELETE", "/contacts/{contact_id}"),
    "list_contact_notes": ("GET", "/contacts/{contact_id}/notes"),
    "create_contact_note": ("POST", "/contacts/{contact_id}/notes"),
    "list_tasks": ("GET", "/tasks"),
    "get_task": ("GET", "/tasks/{task_id}"),
    "create_task": ("POST", "/tasks"),
    "update_task": ("PUT", "/tasks/{task_id}"),
    "delete_task": ("DELETE", "/tasks/{task_id}"),
    "complete_task": ("PUT", "/tasks/{task_id}/complete"),
    "uncomplete_task": ("PUT", "/tasks/{task_id}/uncomplete"),
    "list_sale_properties": ("GET", "/properties/residential/sale"),
    "get_sale_property": ("GET", "/properties/residential/sale/{property_id}"),
    "list_lease_properties": ("GET", "/properties/residential/lease"),
    "get_lease_property": ("GET", "/properties/residential/lease/{property_id}"),
}
CONTACT_FIELDS = {"first_name": "firstName", "last_name": "lastName", "company": "company", "position": "position", "emails": "emails", "archived": "archived", "on_do_not_call_list": "onDoNotCallList"}
QUERY_FIELDS = {"page": "page", "page_size": "pagesize", "modified_since": "modifiedSince", "modified_before": "modifiedBefore", "archived": "archived", "email": "email", "team_id": "team", "name": "name", "phone": "phone", "fuzzy": "fuzzy", "user_id": "userid", "completed": "completed", "starting_after": "startingAfter", "starting_before": "startingBefore", "status": "status", "available_only": "availableOnly"}


def _redact(value, credentials):
    if isinstance(value, str):
        for secret in (credentials.api_key, credentials.access_token):
            value = value.replace(secret, "[redacted]")
    elif isinstance(value, list):
        value = [_redact(item, credentials) for item in value]
    elif isinstance(value, dict):
        value = {key: _redact(item, credentials) for key, item in value.items()}
    return value


class VaultRENode(WorkflowNode):
    integration_type = "automation-vaultre"
    connection_evidence = ConnectionEvidence(
        noun="contacts", operation="list_contacts", identity_operation="get_account",
        label_keys=("displayName", "name", "firstName", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return VaultREConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a VaultRE API key and account access token")
        op = self.config.config
        method, route = ROUTES[op.operation]
        route = route.format(**op.model_dump())
        params, body = {}, None
        if method == "GET":
            for local, remote in QUERY_FIELDS.items():
                value = getattr(op, local, None)
                if value is not None:
                    params[remote] = str(value).lower() if isinstance(value, bool) else value
        elif isinstance(op, _ContactFields):
            body = {remote: getattr(op, local) for local, remote in CONTACT_FIELDS.items() if getattr(op, local) is not None}
        elif isinstance(op, CreateContactNote):
            body = {"body": op.body}
            if op.note_type_id is not None:
                body["type"] = {"id": op.note_type_id}
            if op.read_only is not None:
                body["readOnly"] = op.read_only
        elif isinstance(op, _TaskFields):
            body = {key: getattr(op, key) for key in ("subject", "description", "start") if getattr(op, key) is not None}
            if isinstance(op, CreateTask):
                body["user"] = {"id": op.user_id}
        expected = 204 if method == "DELETE" else 201 if method == "POST" else 200
        try:
            async with guarded_async_client(timeout=30, http2=False, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, params=params,
                    headers={"X-Api-Key": credential.api_key, "Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except (httpx.HTTPError, SSRFError, OSError):
            return {"status": "error", "error": "VaultRE request did not complete; inspect the account before retrying a write."}
        if response.status_code != expected:
            message = "VaultRE returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("msg"), str):
                    message = error["msg"][:2000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, credential)}
        if expected == 204:
            return {"status": "success", "deleted": True}
        if len(response.content) > 10_000_000:
            return {"status": "error", "error": "VaultRE response exceeds the supported size"}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "error": "VaultRE did not return JSON"}
        if not isinstance(data, dict):
            return {"status": "error", "error": "VaultRE did not return an object"}
        if data.get("success") is False:
            return {"status": "error", "error": _redact(str(data.get("msg", "VaultRE rejected the request")), credential)}
        data = _redact(data, credential)
        if isinstance(op, _Page):
            items = data.get("items")
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                return {"status": "error", "error": "VaultRE did not return a list of items"}
            total_pages = data.get("totalPages")
            has_more = op.page < total_pages if type(total_pages) is int and total_pages >= 0 else None
            return {"status": "success", "items": items, "total_items": data.get("totalItems"),
                "total_pages": total_pages, "page": op.page, "has_more": has_more,
                "next_page": op.page + 1 if has_more else None}
        return {"status": "success", "data": data}
