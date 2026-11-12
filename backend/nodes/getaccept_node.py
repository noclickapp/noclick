"""GetAccept v1 operations using an existing bearer access token.

Contract: https://raw.githubusercontent.com/getaccept/openapi/master/openapi.json (1.6).
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

BASE = "https://api.getaccept.com/v1"
FAMILY = "getaccept_access_token"


class GetAcceptAccessToken(BaseModel):
    model_config = ConfigDict(title="GetAccept Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.getaccept.com/api",
            "x-credential-instructions": "Paste an existing GetAccept bearer access token obtained through GetAccept's documented authentication API. NoClick does not collect your password or refresh this token; replace it when it expires. Omit the Bearer prefix."})
    credential_type: Literal["getaccept_access_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def nonempty(cls, value, info):
        if isinstance(value, str) and (not value.strip() or any(ord(c) < 32 and c not in "\n\r\t" for c in value)):
            raise ValueError("Use a nonempty value without control characters")
        if info.field_name.endswith("_id") and isinstance(value, str) and (value in {".", ".."} or any(c in value for c in "/\\?#")):
            raise ValueError("Use a single GetAccept resource ID")
        return value


class _Page(_Input):
    offset: int = Field(0, ge=0, description="Zero-based offset; request the next page by increasing by limit.")
    limit: int = Field(100, ge=1, le=100, description="Records per request. Each run fetches one page.")


class _Document(_Input):
    document_id: str = Field(..., title="Document ID", min_length=1, max_length=512)


class ListDocuments(_Page):
    """List one page of documents, optionally filtering status or external ID."""
    operation: Literal["list_documents"] = "list_documents"
    filter: Literal["draft", "sent", "viewed", "reviewed", "signed", "rejected", "recalled"] | None = None
    sort_by: Literal["name", "value", "created", "recipient", "status", "owner"] | None = None
    sort_order: Literal["asc", "desc"] | None = None
    external_id: str | None = None
    showteam: bool | None = None
    showall: bool | None = None


class GetDocument(_Document):
    """Read document details."""
    operation: Literal["get_document"] = "get_document"
    with_attachments: bool | None = None
    with_pages: bool | None = None
    with_stats: bool | None = None


class GetDocumentByExternalId(_Input):
    """Read a document by its external system identifier."""
    operation: Literal["get_document_by_external_id"] = "get_document_by_external_id"
    external_id: str = Field(..., min_length=1, max_length=512)


class Recipient(_Input):
    email: str = Field(..., min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    mobile: str | None = None
    role: Literal["signer", "internalApprover", "externalApprover", "cc"] = "signer"
    role_name: str | None = None


class CreateDocument(_Input):
    """Create a document from an existing template; automatic sending is explicit."""
    operation: Literal["create_document"] = "create_document"
    name: str = Field(..., min_length=1)
    template_id: str = Field(..., min_length=1, title="Template ID")
    recipients: list[Recipient] = Field(..., min_length=1, max_length=100)
    external_id: str | None = None
    value: float | None = Field(None, allow_inf_nan=False)
    is_automatic_sending: bool = Field(False, description="Send to recipients immediately after creation.")
    is_signing: bool = True
    email_send_message: str | None = None


class UpdateDocument(_Document):
    """Update document metadata without replacing the document content."""
    operation: Literal["update_document"] = "update_document"
    tags: str | None = Field(None, description="Comma-separated tags, as required by the API.")
    external_id: str | None = None
    external_client_id: str | None = None
    value: float | None = Field(None, allow_inf_nan=False)
    contract_start_date: str | None = None
    contract_end_date: str | None = None

    @model_validator(mode="after")
    def change(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "document_id"}):
            raise ValueError("Provide at least one metadata field to update")
        return self


class SendDocument(_Document):
    """Send an existing document to its recipients."""
    operation: Literal["send_document"] = "send_document"
    sender_email: str | None = None
    sender_id: str | None = None


class SendReminder(_Document):
    """Send an email or SMS reminder to document recipients."""
    operation: Literal["send_reminder"] = "send_reminder"
    type: Literal["email", "sms"] = "email"
    text: str = Field(..., min_length=1)
    not_opened: bool | None = None
    not_signed: bool | None = None


class CreateComment(_Document):
    """Post a document comment."""
    operation: Literal["create_comment"] = "create_comment"
    text: str = Field(..., min_length=1)
    position: str | None = None


class ListContacts(_Page):
    """List one page of contacts with optional search and status filters."""
    operation: Literal["list_contacts"] = "list_contacts"
    search: str | None = None
    filter: Literal["active", "inactive", "signed"] | None = None
    sort_by: Literal["name", "email", "company_name", "document_count", "created"] | None = None
    sort_order: Literal["asc", "desc"] | None = None
    showteam: bool | None = None
    showall: bool | None = None


class CreateContact(_Input):
    """Create a sales contact."""
    operation: Literal["create_contact"] = "create_contact"
    email: str = Field(..., min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    fullname: str | None = None
    company_name: str | None = None
    company_number: str | None = None
    mobile: str | None = None
    phone: str | None = None
    title: str | None = None
    note: str | None = None


class DeleteContact(_Input):
    """Permanently delete a contact."""
    operation: Literal["delete_contact"] = "delete_contact"
    contact_id: str = Field(..., min_length=1, max_length=512)


class ListTemplates(_Input):
    """List document templates, optionally within a folder."""
    operation: Literal["list_templates"] = "list_templates"
    showall: Literal["true", "false"] | None = None
    folder_id: str | None = None


class ListFolders(_Input):
    """List archive or template folders."""
    operation: Literal["list_folders"] = "list_folders"
    type: Literal["archive", "template"] | None = None


class GetUser(_Input):
    """Read a user's profile."""
    operation: Literal["get_user"] = "get_user"
    user_id: str = Field(..., min_length=1, max_length=512)


class GetDocumentStatus(_Document):
    """Read a document signing status."""
    operation: Literal["get_document_status"] = "get_document_status"


class ListRecipients(_Document):
    """List document recipients."""
    operation: Literal["list_recipients"] = "list_recipients"


class ListComments(_Document):
    """List document comments."""
    operation: Literal["list_comments"] = "list_comments"


class ListEvents(_Document):
    """List document activity events."""
    operation: Literal["list_events"] = "list_events"


class ListUsers(_Input):
    """List users in the current entity."""
    operation: Literal["list_users"] = "list_users"


class ListAttachments(_Input):
    """List available attachments."""
    operation: Literal["list_attachments"] = "list_attachments"


class TestAuthentication(_Input):
    """Read the current entity and user IDs to verify authentication."""
    operation: Literal["test_authentication"] = "test_authentication"


# GetAccept's own MCP server: agents get its tools through a person's GetAccept sign-in.
GetacceptMcpCredential = mcp_credential("getaccept", "https://mcp.getaccept.com/mcp", app="GetAccept")
GetAcceptCredential = Union[GetAcceptAccessToken, GetacceptMcpCredential]


GetAcceptOperation = Annotated[Union[ListDocuments, GetDocument, GetDocumentByExternalId, CreateDocument, UpdateDocument, SendDocument, SendReminder, CreateComment, ListContacts, CreateContact, DeleteContact, ListTemplates, ListFolders, GetUser, GetDocumentStatus, ListRecipients, ListComments, ListEvents, ListUsers, ListAttachments, TestAuthentication], Field(discriminator="operation")]


class GetAcceptConfig(NodeConfig[GetAcceptOperation, GetAcceptCredential]):
    pass


# Every operation corresponds to one published v1 API operation.
ROUTES = {
    "list_documents": ("GET", "/documents"),
    "get_document": ("GET", "/documents/{document_id}"),
    "get_document_by_external_id": ("GET", "/documents/external/{external_id}"),
    "create_document": ("POST", "/documents"),
    "update_document": ("PUT", "/documents/{document_id}"),
    "send_document": ("POST", "/documents/{document_id}/send"),
    "send_reminder": ("POST", "/documents/{document_id}/reminders"),
    "create_comment": ("POST", "/documents/{document_id}/comments"),
    "list_contacts": ("GET", "/contacts"),
    "create_contact": ("POST", "/contacts"),
    "delete_contact": ("DELETE", "/contacts/{contact_id}"),
    "list_templates": ("GET", "/templates"),
    "list_folders": ("GET", "/folders"),
    "get_user": ("GET", "/users/{user_id}"),
    "get_document_status": ("GET", "/documents/{document_id}/status"),
    "list_recipients": ("GET", "/documents/{document_id}/recipients"),
    "list_comments": ("GET", "/documents/{document_id}/comments"),
    "list_events": ("GET", "/documents/{document_id}/events"),
    "list_users": ("GET", "/users"),
    "list_attachments": ("GET", "/attachments"),
    "test_authentication": ("GET", "/test"),
}
LIST_KEYS = {"list_recipients": "recipients", "list_contacts": "contacts", "list_templates": "templates", "list_folders": "folders", "list_users": "users", "list_attachments": "attachments"}


async def request(credential, op):
    method, path = ROUTES[op.operation]
    values = op.model_dump(exclude_none=True, exclude={"operation"})
    for key in tuple(values):
        if "{" + key + "}" in path:
            path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
    kwargs = {"params": values} if method == "GET" else {"json": values} if method in {"POST", "PUT"} else {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
        response = await client.request(method, BASE + path,
            headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}, **kwargs)
    if response.status_code >= 300:
        message = response.text.replace(credential.access_token, "[redacted]")[:2000]
        raise ValueError(f"GetAccept HTTP {response.status_code}: {message}")
    # Update and reminder endpoints document a status without a response schema.
    if response.status_code == 204 or not response.content:
        return {"http_status": response.status_code, "acknowledged": True}
    body = response.json()
    if isinstance(body, dict) and (body.get("error") or body.get("errors")):
        raise ValueError("GetAccept rejected the request: " + str(body).replace(credential.access_token, "[redacted]")[:2000])
    if op.operation.startswith("list_"):
        rows = body.get(LIST_KEYS[op.operation]) if op.operation in LIST_KEYS and isinstance(body, dict) else body
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("GetAccept returned an unexpected list response")
        return {"records": rows, "http_status": response.status_code,
            **({"offset": op.offset, "limit": op.limit} if isinstance(op, _Page) else {})}
    if not isinstance(body, dict):
        raise ValueError("GetAccept returned an unexpected object response")
    return {"data": body, "http_status": response.status_code}


class GetAcceptNode(WorkflowNode):
    integration_type = "automation-getaccept"
    credential_provider_labels = {"getaccept": "GetAccept Account"}
    scope_registry = ScopeRegistry(provider="getaccept", enforcement=Enforcement.STRICT,
        requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in ROUTES})
    connection_evidence = ConnectionEvidence(noun="GetAccept documents", operation="list_documents",
        identity_operation="test_authentication", label_keys=("name", "id"))
    edit_examples = ["Create a proposal from a template", "Find signed documents", "Send a document reminder", "Create a sales contact"]

    @classmethod
    def get_config_model(cls):
        return GetAcceptConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a GetAccept access token")
        return await request(self.config.credentials, self.config.config)
