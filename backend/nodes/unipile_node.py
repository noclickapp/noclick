"""Unipile v1 messaging, email and network operations.

Contract: https://developer.unipile.com/openapi/.openapi.json (version 1.0).
Each operation makes one request; cursor pagination is explicit and writes are
never retried automatically. Connect existing accounts in Unipile's dashboard.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=100000)]


def api_origin(value):
    """Accept dashboard DSNs only under Unipile, including its documented port."""
    if not isinstance(value, str):
        raise ValueError("Paste the HTTPS DSN from the Unipile dashboard")
    raw = value.strip().rstrip("/")
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise ValueError("Use a valid Unipile HTTPS DSN") from None
    if (parts.scheme != "https" or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.unipile\.com", parts.hostname or "")
            or parts.username is not None or parts.password is not None
            or parts.path or parts.query or parts.fragment or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("Use your HTTPS DSN, such as https://api1.unipile.com:13111, without an API path")
    return "https://" + parts.hostname + (":" + str(port) if port is not None else "")


class UnipileAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Unipile API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.unipile.com/",
            "x-credential-instructions": "Paste your Unipile v1 dashboard DSN (including its port) and access token. Connect messaging or email accounts in Unipile first. The token is sent as X-API-KEY only to your Unipile DSN. Listing linked accounts verifies this connection; individual provider permissions may differ.",
        })
    credential_type: Literal["unipile_api_key"] = Field("unipile_api_key", json_schema_extra={"ui:hidden": True})
    api_url: str = Field(..., title="DSN", description="HTTPS origin from your Unipile dashboard, e.g. https://api1.unipile.com:13111")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_url", mode="before")
    @classmethod
    def origin(cls, value):
        return api_origin(value)

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the Unipile access token")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(100, ge=1, le=100, description="Page size. Use cursor from the previous response for another page.")
    cursor: Optional[Identifier] = None


class EmailRecipient(_Input):
    identifier: str = Field(..., min_length=3, max_length=320, description="Recipient email address")
    display_name: Optional[str] = Field(None, max_length=500)

    @field_validator("identifier")
    @classmethod
    def email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Use a recipient email address")
        return value


class UnipileListAccountsConfig(_Page):
    """List accounts."""
    operation: Literal["list_accounts"] = Field("list_accounts", json_schema_extra={"ui:hidden": True})


class UnipileGetAccountConfig(_Input):
    """Get account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})
    account_id: Identifier


class UnipileListChatsConfig(_Page):
    """List chats."""
    operation: Literal["list_chats"] = Field("list_chats", json_schema_extra={"ui:hidden": True})
    account_id: Optional[Identifier] = None
    unread: Optional[bool] = None


class UnipileGetChatConfig(_Input):
    """Get chat."""
    operation: Literal["get_chat"] = Field("get_chat", json_schema_extra={"ui:hidden": True})
    chat_id: Identifier
    account_id: Optional[Identifier] = Field(None, description="Required if chat_id is a provider ID")


class UnipileListChatMessagesConfig(_Page):
    """List chat messages."""
    operation: Literal["list_chat_messages"] = Field("list_chat_messages", json_schema_extra={"ui:hidden": True})
    chat_id: Identifier
    sender_id: Optional[Identifier] = None


class UnipileSendMessageConfig(_Input):
    """Send message."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    chat_id: Identifier
    text: Text
    account_id: Optional[Identifier] = None
    quote_id: Optional[Identifier] = None
    thread_id: Optional[Identifier] = None


class UnipileStartChatConfig(_Input):
    """Start chat."""
    operation: Literal["start_chat"] = Field("start_chat", json_schema_extra={"ui:hidden": True})
    account_id: Identifier
    attendees_ids: list[Identifier] = Field(..., min_length=1, max_length=100, description="Provider IDs of the recipients; LinkedIn classic relations only")
    text: Text
    subject: Optional[str] = Field(None, max_length=1000)


class UnipileSetChatReadStatusConfig(_Input):
    """Set chat read status."""
    operation: Literal["set_chat_read_status"] = Field("set_chat_read_status", json_schema_extra={"ui:hidden": True})
    chat_id: Identifier
    value: bool = Field(..., description="Read status for WhatsApp or LinkedIn")


class UnipileGetMessageConfig(_Input):
    """Get message."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})
    message_id: Identifier


class UnipileEditMessageConfig(_Input):
    """Edit message."""
    operation: Literal["edit_message"] = Field("edit_message", json_schema_extra={"ui:hidden": True})
    message_id: Identifier
    text: Text


class UnipileAddMessageReactionConfig(_Input):
    """Add message reaction."""
    operation: Literal["add_message_reaction"] = Field("add_message_reaction", json_schema_extra={"ui:hidden": True})
    message_id: Identifier
    reaction: str = Field(..., min_length=1, max_length=32, description="Native emoji, e.g. 👍")


class UnipileListEmailsConfig(_Page):
    """List emails."""
    operation: Literal["list_emails"] = Field("list_emails", json_schema_extra={"ui:hidden": True})
    account_id: Identifier
    search: Optional[str] = Field(None, max_length=1000)
    folder: Optional[Identifier] = None
    meta_only: Optional[bool] = None


class UnipileGetEmailConfig(_Input):
    """Get email."""
    operation: Literal["get_email"] = Field("get_email", json_schema_extra={"ui:hidden": True})
    email_id: Identifier
    account_id: Optional[Identifier] = Field(None, description="Required if email_id is a provider UID")
    include_headers: Optional[bool] = None


class UnipileSetEmailUnreadConfig(_Input):
    """Set email unread."""
    operation: Literal["set_email_unread"] = Field("set_email_unread", json_schema_extra={"ui:hidden": True})
    email_id: Identifier
    account_id: Optional[Identifier] = Field(None, description="Required if email_id is a provider UID")
    unread: bool


class UnipileListEmailContactsConfig(_Page):
    """List email contacts."""
    operation: Literal["list_email_contacts"] = Field("list_email_contacts", json_schema_extra={"ui:hidden": True})
    account_id: Identifier


class UnipileSendEmailConfig(_Input):
    """Send email."""
    operation: Literal["send_email"] = Field("send_email", json_schema_extra={"ui:hidden": True})
    account_id: Identifier
    to: list[EmailRecipient] = Field(..., min_length=1, max_length=100)
    subject: Optional[str] = Field(None, max_length=1000)
    body: Text
    reply_to: Optional[Identifier] = None


class UnipileGetOwnProfileConfig(_Input):
    """Get own profile."""
    operation: Literal["get_own_profile"] = Field("get_own_profile", json_schema_extra={"ui:hidden": True})
    account_id: Identifier


class UnipileGetProfileConfig(_Input):
    """Get profile."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})
    account_id: Identifier
    identifier: Identifier
    notify: bool = Field(False, description="Whether to notify the profile owner of the visit")


class UnipileSendInvitationConfig(_Input):
    """Send invitation."""
    operation: Literal["send_invitation"] = Field("send_invitation", json_schema_extra={"ui:hidden": True})
    account_id: Identifier
    provider_id: Identifier
    message: Optional[str] = Field(None, max_length=300)
    user_email: Optional[str] = Field(None, max_length=320)


class UnipileListRelationsConfig(_Page):
    """List relations."""
    operation: Literal["list_relations"] = Field("list_relations", json_schema_extra={"ui:hidden": True})
    account_id: Identifier
    filter: Optional[str] = Field(None, max_length=1000)


class UnipileListSentInvitationsConfig(_Page):
    """List sent invitations."""
    operation: Literal["list_sent_invitations"] = Field("list_sent_invitations", json_schema_extra={"ui:hidden": True})
    account_id: Identifier


class UnipileListUserPostsConfig(_Page):
    """List user posts."""
    operation: Literal["list_user_posts"] = Field("list_user_posts", json_schema_extra={"ui:hidden": True})
    account_id: Identifier
    identifier: Identifier
    is_company: Optional[bool] = None


UnipileConfig = Annotated[Union[
    UnipileListAccountsConfig,
    UnipileGetAccountConfig,
    UnipileListChatsConfig,
    UnipileGetChatConfig,
    UnipileListChatMessagesConfig,
    UnipileSendMessageConfig,
    UnipileStartChatConfig,
    UnipileSetChatReadStatusConfig,
    UnipileGetMessageConfig,
    UnipileEditMessageConfig,
    UnipileAddMessageReactionConfig,
    UnipileListEmailsConfig,
    UnipileGetEmailConfig,
    UnipileSetEmailUnreadConfig,
    UnipileListEmailContactsConfig,
    UnipileSendEmailConfig,
    UnipileGetOwnProfileConfig,
    UnipileGetProfileConfig,
    UnipileSendInvitationConfig,
    UnipileListRelationsConfig,
    UnipileListSentInvitationsConfig,
    UnipileListUserPostsConfig
], Field(discriminator="operation")]


class UnipileFullConfig(NodeConfig[UnipileConfig, UnipileAPIKeyCredential]):
    pass


OPERATIONS = {
    'list_accounts': ('GET', '/accounts', (), False),
    'get_account': ('GET', '/accounts/{account_id}', (), False),
    'list_chats': ('GET', '/chats', (), False),
    'get_chat': ('GET', '/chats/{chat_id}', (), False),
    'list_chat_messages': ('GET', '/chats/{chat_id}/messages', (), False),
    'send_message': ('POST', '/chats/{chat_id}/messages', ('text', 'account_id', 'quote_id', 'thread_id'), True),
    'start_chat': ('POST', '/chats', ('account_id', 'attendees_ids', 'text', 'subject'), True),
    'set_chat_read_status': ('PATCH', '/chats/{chat_id}', ('value',), False),
    'get_message': ('GET', '/messages/{message_id}', (), False),
    'edit_message': ('PATCH', '/messages/{message_id}', ('text',), False),
    'add_message_reaction': ('POST', '/messages/{message_id}/reaction', ('reaction',), False),
    'list_emails': ('GET', '/emails', (), False),
    'get_email': ('GET', '/emails/{email_id}', (), False),
    'set_email_unread': ('PUT', '/emails/{email_id}', ('unread',), False),
    'list_email_contacts': ('GET', '/emails/contacts', (), False),
    'send_email': ('POST', '/emails', ('account_id', 'to', 'subject', 'body', 'reply_to'), True),
    'get_own_profile': ('GET', '/users/me', (), False),
    'get_profile': ('GET', '/users/{identifier}', (), False),
    'send_invitation': ('POST', '/users/invite', ('account_id', 'provider_id', 'message', 'user_email'), False),
    'list_relations': ('GET', '/users/relations', (), False),
    'list_sent_invitations': ('GET', '/users/invite/sent', (), False),
    'list_user_posts': ('GET', '/users/{identifier}/posts', (), False),
}


def _redact(value, secret):
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items() if k.lower() not in {"password", "access_token", "refresh_token", "api_key", "x-api-key"}}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    return value


def _form_fields(body):
    """Docs send recipient objects as JSON and attendee IDs as repeated fields."""
    fields = []
    for name, value in body.items():
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                fields.append((name, (None, json.dumps(value))))
            else:
                fields.extend((name, (None, str(item))) for item in value)
        else:
            fields.append((name, (None, str(value))))
    return fields


class UnipileNode(WorkflowNode):
    integration_type = "automation-unipile"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="linked Unipile accounts")

    @classmethod
    def get_config_model(cls):
        return UnipileFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Unipile API key and DSN")
        credential = self.config.credentials
        config = self.config.config
        method, route, body_fields, multipart = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path_fields = re.findall(r"{(\w+)}", route)
        for field in path_fields:
            value = values.pop(field)
            if value in {".", ".."} or any(ord(c) < 32 for c in value):
                raise ValueError("Use a single valid resource identifier")
            route = route.replace("{" + field + "}", quote(value, safe=""))
        body = {field: values.pop(field) for field in body_fields if field in values}
        if config.operation == "set_chat_read_status":
            body["action"] = "setReadStatus"
        params = {k: ("true" if v else "false") if isinstance(v, bool) else v for k, v in values.items()}
        kwargs = {"files": _form_fields(body)} if multipart else {"json": body} if body else {}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, credential.api_url + "/api/v1" + route,
                headers={"X-API-KEY": credential.api_key, "Accept": "application/json"}, params=params, **kwargs)
        if response.status_code not in {200, 201}:
            # Preserve provider rejection text for the shared connect verdict.
            try:
                error = response.json()
                message = error.get("detail") or error.get("message") or error.get("title") or "Unipile request failed"
            except (ValueError, AttributeError):
                message = "Unipile returned an unexpected HTTP response"
            return {"status": "error", "http_status": response.status_code,
                    "error": _redact(str(message)[:2000], credential.api_key)}
        if (len(response.content) > 10000000 or
                response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
            raise ValueError("Expected a bounded Unipile JSON response")
        payload = response.json()
        if not isinstance(payload, dict) or str(payload.get("type", "")).startswith("errors/") or "errors" in payload:
            raise ValueError("Unipile returned an invalid response")
        if config.operation.startswith("list_"):
            if not isinstance(payload.get("items"), list):
                raise ValueError("Unipile list response must contain items")
            if payload.get("cursor") is not None and not isinstance(payload["cursor"], str):
                raise ValueError("Unipile returned an invalid cursor")
        output = {"status": "success", "data": _redact(payload, credential.api_key)}
        await self.emit(output)
        return output
