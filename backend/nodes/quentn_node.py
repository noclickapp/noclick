"""Quentn v1 contacts, tags, comments and account metadata.

Contract: https://quentn.com/assets/api/api-v1.yaml (1.0.0).
Authentication and tenant URL: https://help.quentn.com/hc/en-150/articles/4517495751953-Requests
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

CREDENTIAL_TYPE = "quentn_api_key"
DOCS = "https://help.quentn.com/hc/en-150/articles/4470019659793-Where-can-I-find-the-API"


class QuentnAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Quentn API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": DOCS,
        "x-credential-instructions": "In Quentn, open My account → API info. Copy the API URL and an API key into the fields below. API access requires a Basic account or higher. Use a separate key for NoClick."
    })
    credential_type: Literal["quentn_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., title="API URL", description="Your system URL, for example https://example.s1.quentn.com/public/api/v1.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_base_url", mode="before")
    @classmethod
    def base_url(cls, value):
        if not isinstance(value, str):
            raise ValueError("Copy the API URL from Quentn API info")
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port is not None
                or parsed.query or parsed.fragment or parsed.path != "/public/api/v1"
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.quentn\.com", parsed.netloc)):
            raise ValueError("Use the HTTPS system API URL ending in .quentn.com/public/api/v1")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _ContactID(_Input):
    contact_id: int = Field(..., ge=1, title="Contact ID")


class _TermID(_Input):
    term_id: int = Field(..., ge=1, title="Tag ID")


class _Fields(_Input):
    fields: list[str] | None = Field(None, description="Contact field names to return. Omit to use Quentn's defaults.")


class ContactData(BaseModel):
    """Built-in fields plus provider-defined field_ custom field names."""
    model_config = ConfigDict(extra="allow")
    mail: str | None = Field(None, title="Primary Email")
    first_name: str | None = None
    family_name: str | None = None
    company: str | None = None
    phone: str | None = None
    terms: list[int] | None = Field(None, description="Tag IDs; changing tags may start campaigns.")

    @model_validator(mode="after")
    def valid_contact(self):
        if self.mail is not None and not re.fullmatch(r"[^\s@/]+@[^\s@/]+\.[^\s@/]+", self.mail):
            raise ValueError("Use a valid primary email")
        return self


class GetContact(_ContactID, _Fields):
    """Read a contact by its numeric ID."""
    operation: Literal["get_contact"] = "get_contact"


class GetContactByEmail(_Fields):
    """Read a contact by primary email."""
    operation: Literal["get_contact_by_email"] = "get_contact_by_email"
    email: str = Field(..., title="Primary Email", pattern=r"^[^\s@/]+@[^\s@/]+\.[^\s@/]+$")


class CreateContact(_Input):
    """Create or merge a contact using the documented duplicate policy."""
    operation: Literal["create_contact"] = "create_contact"
    contact: ContactData
    duplicate_check_method: Literal["auto", "email", "none"] = "auto"
    duplicate_merge_method: Literal["update_add", "update", "add"] = "update_add"
    return_fields: list[str] | None = None

    @model_validator(mode="after")
    def contact_identity(self):
        data = self.contact.model_dump(exclude_none=True)
        if not data.get("mail") and not all(data.get(k) for k in ("first_name", "family_name", "ba_street", "ba_city", "ba_postal_code")):
            raise ValueError("Provide a primary email or the complete name and postal address")
        return self


class UpdateContact(_ContactID):
    """Update supplied contact fields; omitted fields are not sent."""
    operation: Literal["update_contact"] = "update_contact"
    contact: ContactData
    return_fields: list[str] | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.contact.model_dump(exclude_none=True):
            raise ValueError("Provide at least one contact field to update")
        return self


class DeleteContact(_ContactID):
    """Permanently delete the selected contact."""
    operation: Literal["delete_contact"] = "delete_contact"


class GetContactTags(_ContactID):
    """List the selected contact's tags."""
    operation: Literal["get_contact_tags"] = "get_contact_tags"


class AddContactTags(_ContactID):
    """Add tags to a contact; tag changes can start campaigns."""
    operation: Literal["add_contact_tags"] = "add_contact_tags"
    tag_ids: list[Annotated[int, Field(ge=1)]] = Field(..., min_length=1, description="Tag IDs to send to Quentn's PUT contact terms endpoint.")


class RemoveContactTags(_ContactID):
    """Remove only the specified tags from a contact."""
    operation: Literal["remove_contact_tags"] = "remove_contact_tags"
    tag_ids: list[Annotated[int, Field(ge=1)]] = Field(..., min_length=1)


class ListContactComments(_ContactID):
    """Read one range of contact comments."""
    operation: Literal["list_contact_comments"] = "list_contact_comments"
    range: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=50)
    sort: Literal["asc", "desc"] = "asc"


class AddContactComment(_ContactID):
    """Add a comment to the selected contact."""
    operation: Literal["add_contact_comment"] = "add_contact_comment"
    comment: str = Field(..., min_length=1)


class UpdateContactComment(_ContactID):
    """Update one comment on the selected contact."""
    operation: Literal["update_contact_comment"] = "update_contact_comment"
    comment_id: int = Field(..., ge=1)
    comment: str = Field(..., min_length=1)


class DeleteContactComments(_ContactID):
    """Delete only the specified contact comments."""
    operation: Literal["delete_contact_comments"] = "delete_contact_comments"
    comment_ids: list[Annotated[int, Field(ge=1)]] = Field(..., min_length=1)


class ListTags(_Input):
    """Read one page of account tags, with an explicit offset."""
    operation: Literal["list_tags"] = "list_tags"
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=500)


class CreateTag(_Input):
    """Create a tag for contact segmentation and campaigns."""
    operation: Literal["create_tag"] = "create_tag"
    name: str = Field(..., min_length=1)
    description: str | None = None


class GetTag(_TermID):
    """Read one tag by ID."""
    operation: Literal["get_tag"] = "get_tag"


class UpdateTag(_TermID):
    """Update a tag's name or description."""
    operation: Literal["update_tag"] = "update_tag"
    name: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if self.name is None and self.description is None:
            raise ValueError("Provide a tag name or description")
        return self


class DeleteTag(_TermID):
    """Delete the selected tag; Quentn may block tags used by campaigns."""
    operation: Literal["delete_tag"] = "delete_tag"


class ListUsers(_Input):
    """Read one range of users in this Quentn system."""
    operation: Literal["list_users"] = "list_users"
    range: int = Field(0, ge=0)
    limit: int = Field(20, ge=1, le=20)
    sort: Literal["asc", "desc"] = "asc"


class GetUser(_Input):
    """Read a user by ID."""
    operation: Literal["get_user"] = "get_user"
    user_id: int = Field(..., ge=1)


class ListCustomFields(_Input):
    """Read custom field definitions and their machine names."""
    operation: Literal["list_custom_fields"] = "list_custom_fields"


class GetCustomField(_Input):
    """Read a custom field definition by numeric ID."""
    operation: Literal["get_custom_field"] = "get_custom_field"
    field_id: int = Field(..., ge=1)


# Quentn's own MCP server: agents get its tools through a person's Quentn sign-in.
QuentnMcpCredential = mcp_credential("quentn", "https://mcp.quentn.com/mcp", app="Quentn")
QuentnCredential = Union[QuentnAPIKeyCredential, QuentnMcpCredential]


QuentnOperation = Annotated[Union[
    GetContact, GetContactByEmail, CreateContact, UpdateContact, DeleteContact,
    GetContactTags, AddContactTags, RemoveContactTags, ListContactComments,
    AddContactComment, UpdateContactComment, DeleteContactComments,
    ListTags, CreateTag, GetTag, UpdateTag, DeleteTag, ListUsers, GetUser,
    ListCustomFields, GetCustomField,
], Field(discriminator="operation")]


class QuentnFullConfig(NodeConfig[QuentnOperation, QuentnCredential]):
    pass


# Each operation makes exactly one request to the pinned published contract.
ROUTES = {
    "get_contact": ("GET", "/contact/{contact_id}"),
    "get_contact_by_email": ("GET", "/contact/{email}"),
    "create_contact": ("POST", "/contact"),
    "update_contact": ("PUT", "/contact/{contact_id}"),
    "delete_contact": ("DELETE", "/contact/{contact_id}"),
    "get_contact_tags": ("GET", "/contact/{contact_id}/terms"),
    "add_contact_tags": ("PUT", "/contact/{contact_id}/terms"),
    "remove_contact_tags": ("DELETE", "/contact/{contact_id}/terms"),
    "list_contact_comments": ("GET", "/contact/{contact_id}/comments"),
    "add_contact_comment": ("POST", "/contact/{contact_id}/comments"),
    "update_contact_comment": ("PUT", "/contact/{contact_id}/comments"),
    "delete_contact_comments": ("DELETE", "/contact/{contact_id}/comments"),
    "list_tags": ("GET", "/terms"), "create_tag": ("POST", "/terms"),
    "get_tag": ("GET", "/terms/{term_id}"), "update_tag": ("PUT", "/terms/{term_id}"),
    "delete_tag": ("DELETE", "/terms/{term_id}"),
    "list_users": ("GET", "/users"), "get_user": ("GET", "/user/{user_id}"),
    "list_custom_fields": ("GET", "/custom-fields"),
    "get_custom_field": ("GET", "/custom-fields/{field_id}"),
}


def request_parts(op):
    data = op.model_dump(exclude_none=True)
    data.pop("operation")
    method, template = ROUTES[op.operation]
    path = template
    for field in re.findall(r"{(\w+)}", template):
        path = path.replace("{" + field + "}", quote(str(data.pop(field)), safe=""))
    params, body = {}, None
    if method == "GET":
        if "fields" in data:
            data["fields"] = ",".join(data["fields"])
        params = data
    elif isinstance(op, (AddContactTags, RemoveContactTags)):
        body = data["tag_ids"]
    elif isinstance(op, DeleteContactComments):
        body = data["comment_ids"]
    elif isinstance(op, UpdateContact):
        body = {**data.pop("contact"), **data}
    elif isinstance(op, UpdateContactComment):
        body = {"id": data["comment_id"], "comment": data["comment"]}
    elif method in {"PUT", "POST"}:
        body = data
    return method, path, params, body


class QuentnNode(WorkflowNode):
    integration_type = "automation-quentn"
    credential_provider_labels = {"quentn": "Quentn Account"}
    connection_evidence = ConnectionEvidence(operation="list_tags", noun="tags")

    @classmethod
    def get_config_model(cls):
        return QuentnFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Quentn API key and API URL")
        credential = self.config.credentials
        op = self.config.config
        method, path, params, body = request_parts(op)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.api_base_url + path,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        try:
            result = response.json()
        except ValueError:
            raise ValueError("Quentn returned an unreadable response; check the API URL") from None
        if response.status_code != 200 or (isinstance(result, dict) and (result.get("error") in (True, "true") or result.get("success") in (False, "false"))):
            message = result.get("message", "Quentn rejected the request") if isinstance(result, dict) else "Quentn rejected the request"
            message = str(message).replace(credential.api_key, "[redacted]")
            output = {"status": "error", "http_status": response.status_code, "message": message}
        else:
            if not isinstance(result, (dict, list)):
                raise ValueError("Expected a JSON object or array from Quentn")
            output = {"status": "success", "data": result}
            if isinstance(op, ListTags):
                if not isinstance(result, list):
                    raise ValueError("Expected Quentn's array of tags")
                output.update(has_more=len(result) == op.limit,
                    next_offset=op.offset + len(result) if len(result) == op.limit else None)
            elif isinstance(op, (ListUsers, ListContactComments)):
                if not isinstance(result, dict):
                    raise ValueError("Expected Quentn's range response")
                ranges = result.get("number_ranges")
                output["next_range"] = op.range + 1 if isinstance(ranges, int) and op.range + 1 < ranges else None
        await self.emit(output)
        return output
