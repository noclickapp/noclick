"""MailSlurp API 6.5.2. Fixed single-request operations; list results retain provider pagination.

Contract: https://api.mailslurp.com/v2/api-docs
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.mailslurp.com"

class MailslurpAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="MailSlurp API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.mailslurp.com/api/",
        "x-credential-instructions": "Copy your API key from the MailSlurp dashboard and paste it here. NoClick sends it as x-api-key to api.mailslurp.com. Connecting reads your account information. Your plan determines which operations are available.",
    })
    credential_type: Literal["mailslurp_api_key"] = Field("mailslurp_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class MailslurpGetAccountConfig(_Input):
    """get_account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class MailslurpListInboxesConfig(_Input):
    """List All Inboxes Paginated."""
    operation: Literal["list_inboxes"] = Field("list_inboxes", json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)
    sort: Literal['ASC', 'DESC'] = Field('ASC')
    search: str | None = Field(None)
    tag: str | None = Field(None)


class MailslurpCreateInboxConfig(_Input):
    """Create an inbox email address. An inbox has a real email address and can send and receive emails. Inboxes can be either `SMTP` or `HTTP` inboxes.."""
    operation: Literal["create_inbox"] = Field("create_inbox", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None)
    description: str | None = Field(None)
    expiresIn: int | None = Field(None, ge=1)
    inboxType: Literal['HTTP_INBOX', 'SMTP_INBOX'] | None = Field(None)


class MailslurpGetInboxConfig(_Input):
    """Get Inbox. Returns properties of an inbox.."""
    operation: Literal["get_inbox"] = Field("get_inbox", json_schema_extra={"ui:hidden": True})
    inboxId: UUID = Field(...)


class MailslurpUpdateInboxConfig(_Input):
    """Update Inbox. Change name and description. Email address is not editable.."""
    operation: Literal["update_inbox"] = Field("update_inbox", json_schema_extra={"ui:hidden": True})
    inboxId: UUID = Field(...)
    name: str | None = Field(None)
    description: str | None = Field(None)
    favourite: StrictBool | None = Field(None)


class MailslurpDeleteInboxConfig(_Input):
    """Delete inbox."""
    operation: Literal["delete_inbox"] = Field("delete_inbox", json_schema_extra={"ui:hidden": True})
    inboxId: UUID = Field(...)


class MailslurpListEmailsConfig(_Input):
    """Get emails in an Inbox. This method is not idempotent as it allows retries and waits if you want certain conditions to be met before returning. For simple listing and sorting of known emails use the email controller instead.."""
    operation: Literal["list_emails"] = Field("list_emails", json_schema_extra={"ui:hidden": True})
    inboxId: UUID = Field(...)
    size: int | None = Field(None, ge=1, le=100)
    sort: Literal['ASC', 'DESC'] | None = Field(None)
    unreadOnly: StrictBool | None = Field(None)


class MailslurpSendEmailConfig(_Input):
    """Send Email."""
    operation: Literal["send_email"] = Field("send_email", json_schema_extra={"ui:hidden": True})
    inboxId: UUID = Field(...)
    to: list[EmailStr] = Field(..., min_length=1, max_length=100)
    subject: str | None = Field(None)
    body: str | None = Field(None)
    isHTML: StrictBool | None = Field(None)


class MailslurpGetEmailConfig(_Input):
    """Get hydrated email (headers and body)."""
    operation: Literal["get_email"] = Field("get_email", json_schema_extra={"ui:hidden": True})
    emailId: UUID = Field(...)


class MailslurpReplyToEmailConfig(_Input):
    """Reply to an email."""
    operation: Literal["reply_to_email"] = Field("reply_to_email", json_schema_extra={"ui:hidden": True})
    emailId: UUID = Field(...)
    body: str = Field(...)
    isHTML: StrictBool = Field(...)


class MailslurpDeleteEmailConfig(_Input):
    """Delete an email."""
    operation: Literal["delete_email"] = Field("delete_email", json_schema_extra={"ui:hidden": True})
    emailId: UUID = Field(...)


class MailslurpMarkEmailReadConfig(_Input):
    """Mark an email as read or unread."""
    operation: Literal["mark_email_read"] = Field("mark_email_read", json_schema_extra={"ui:hidden": True})
    emailId: UUID = Field(...)
    read: StrictBool = Field(True)


class MailslurpListSentEmailsConfig(_Input):
    """Get all sent emails in paginated form."""
    operation: Literal["list_sent_emails"] = Field("list_sent_emails", json_schema_extra={"ui:hidden": True})
    inboxId: UUID | None = Field(None)
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)
    sort: Literal['ASC', 'DESC'] = Field('ASC')


class MailslurpGetSentEmailConfig(_Input):
    """Get sent email receipt."""
    operation: Literal["get_sent_email"] = Field("get_sent_email", json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class MailslurpListContactsConfig(_Input):
    """Get all contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class MailslurpCreateContactConfig(_Input):
    """Create a contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    firstName: str | None = Field(None)
    lastName: str | None = Field(None)
    emailAddresses: list[EmailStr] = Field(..., min_length=1, max_length=1)


class MailslurpGetContactConfig(_Input):
    """Get contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contactId: UUID = Field(...)


class MailslurpDeleteContactConfig(_Input):
    """Delete contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    contactId: UUID = Field(...)


# MailSlurp's own MCP server: agents get its tools through a person's MailSlurp sign-in.
MailslurpMcpCredential = mcp_credential("mailslurp", "https://api.mailslurp.com/mcp", app="MailSlurp")
MailslurpCredential = Union[MailslurpAPIKeyCredential, MailslurpMcpCredential]


MailslurpConfig = Annotated[Union[MailslurpGetAccountConfig, MailslurpListInboxesConfig, MailslurpCreateInboxConfig, MailslurpGetInboxConfig, MailslurpUpdateInboxConfig, MailslurpDeleteInboxConfig, MailslurpListEmailsConfig, MailslurpSendEmailConfig, MailslurpGetEmailConfig, MailslurpReplyToEmailConfig, MailslurpDeleteEmailConfig, MailslurpMarkEmailReadConfig, MailslurpListSentEmailsConfig, MailslurpGetSentEmailConfig, MailslurpListContactsConfig, MailslurpCreateContactConfig, MailslurpGetContactConfig, MailslurpDeleteContactConfig], Field(discriminator="operation")]

class MailslurpFullConfig(NodeConfig[MailslurpConfig, MailslurpCredential]):
    pass

ROUTES = {'get_account': ('GET', '/user/info', [], []), 'list_inboxes': ('GET', '/inboxes/paginated', ['page', 'size', 'sort', 'search', 'tag'], []), 'create_inbox': ('POST', '/inboxes', ['name', 'description', 'inboxType', 'expiresIn'], []), 'get_inbox': ('GET', '/inboxes/{inboxId}', [], []), 'update_inbox': ('PATCH', '/inboxes/{inboxId}', [], ['name', 'description', 'favourite']), 'delete_inbox': ('DELETE', '/inboxes/{inboxId}', [], []), 'list_emails': ('GET', '/inboxes/{inboxId}/emails', ['size', 'sort', 'unreadOnly'], []), 'send_email': ('POST', '/inboxes/{inboxId}', [], ['to', 'subject', 'body', 'isHTML']), 'get_email': ('GET', '/emails/{emailId}', [], []), 'reply_to_email': ('PUT', '/emails/{emailId}', [], ['body', 'isHTML']), 'delete_email': ('DELETE', '/emails/{emailId}', [], []), 'mark_email_read': ('PATCH', '/emails/{emailId}/read', ['read'], []), 'list_sent_emails': ('GET', '/sent', ['page', 'size', 'sort', 'inboxId'], []), 'get_sent_email': ('GET', '/sent/{id}', [], []), 'list_contacts': ('GET', '/contacts', [], []), 'create_contact': ('POST', '/contacts', [], ['firstName', 'lastName', 'emailAddresses']), 'get_contact': ('GET', '/contacts/{contactId}', [], []), 'delete_contact': ('DELETE', '/contacts/{contactId}', [], [])}

class MailslurpNode(WorkflowNode):
    integration_type = "automation-mailslurp"
    credential_provider_labels = {"mailslurp": "MailSlurp Account"}
    connection_evidence = ConnectionEvidence(noun="MailSlurp account", identity_operation="get_account", identity_keys=("emailAddress", "id"))

    @classmethod
    def get_config_model(cls):
        return MailslurpFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a MailSlurp API key")
        op = self.config.config
        method, path, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        for name, value in values.items():
            path = path.replace("{" + name + "}", str(value))
        params = {k: str(values[k]).lower() if isinstance(values[k], bool) else values[k]
                  for k in query_fields if k in values}
        body = {k: values[k] for k in body_fields if k in values}
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"x-api-key": key, "Accept": "application/json"},
                    **({"json": body} if body_fields else {}))
        except httpx.HTTPError:
            raise ValueError("MailSlurp request could not be confirmed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            # Preserve provider rejections for the connection seam, with the key removed.
            message = response.text[:2000].replace(key, "[redacted]")
            raise ValueError(f"MailSlurp HTTP {response.status_code}: {message}")
        if len(response.content) > 10_000_000:
            raise ValueError("MailSlurp response exceeds the supported size")
        data = None
        if response.content:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Expected a MailSlurp JSON response") from None
        output = {"status": "success", "operation": op.operation, "data": data,
                  "http_status": response.status_code}
        await self.emit(output)
        return output
