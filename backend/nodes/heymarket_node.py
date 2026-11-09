"""Heymarket SMS operations using manually supplied API Secret credentials.

Each action makes one documented REST call; paginated reads return one page and
writes report the provider acknowledgement without claiming SMS delivery.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.heymarket.com"
PositiveID = Annotated[int, Field(gt=0)]
Phone = Annotated[str, Field(pattern=r"^[1-9][0-9]{6,14}$", description="E.164 digits without the leading plus sign.")]


class HeymarketAPISecretCredential(BaseModel):
    model_config = ConfigDict(
        title="Heymarket API Secret", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.heymarket.com",
            "x-credential-instructions": "In Heymarket, open Settings > Integrations > API and generate an API Secret. Paste its Secret ID and Secret Key here. The key is shown only once. NoClick signs a fresh short-lived JWT on the server for each request. Connection checks read your inboxes.",
        },
    )
    credential_type: Literal["heymarket_api_secret"] = Field("heymarket_api_secret", json_schema_extra={"ui:hidden": True})
    secret_id: str = Field(..., min_length=1, max_length=4096, title="Secret ID", json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., min_length=1, max_length=4096, title="Secret Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("secret_id", "secret_key", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value) or "||" in value:
            raise ValueError("Paste the credential value without spaces or the signing separator")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListInboxes(_Input):
    operation: Literal["list_inboxes"] = Field("list_inboxes", json_schema_extra={"ui:hidden": True})


class GetTeam(_Input):
    operation: Literal["get_team"] = Field("get_team", json_schema_extra={"ui:hidden": True})


class ContactTag(_Input):
    tag_id: PositiveID


class _ContactFields(_Input):
    phone: Phone
    first: str | None = None
    last: str | None = None
    display_name: str | None = None
    email: str | None = None
    custom: dict[str, Any] | None = Field(None, description="Custom field IDs as string keys, with their values.")
    assignee_id: int | None = Field(None, ge=-1, description="Team member ID; -1 unassigns the contact.")
    tags: list[ContactTag] | None = Field(None, max_length=5)
    is_opted_out: bool | None = None
    timezone: str | None = None


class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})


class GetContact(_Input):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: PositiveID


class UpdateContact(_ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: PositiveID
    overwrite: bool = Field(False, description="Replace custom fields if true; otherwise merge. Names are always overwritten: supply current first, last and display_name to preserve them.")


class DeleteContact(_Input):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    contact_id: PositiveID


class _Page(_Input):
    limit: int = Field(30, ge=1, le=100, description="Results per page. This action returns a single page.")
    page: int = Field(0, ge=0, description="Zero-based page number; increment to request another page.")
    date: str | None = Field(None, description="RFC 3339 timestamp used by the provider to filter or paginate results.")
    ascending: bool = False


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class SearchChannel(_Input):
    channel_type: Literal["phone", "email"]
    channel_ids: list[str] = Field(..., min_length=1, max_length=100)


class SearchContacts(_Input):
    operation: Literal["search_contacts"] = Field("search_contacts", json_schema_extra={"ui:hidden": True})
    contact_channels: list[SearchChannel] = Field(..., min_length=1, max_length=100, description="Find contacts by phone numbers or email addresses.")


class ListConversations(_Page):
    operation: Literal["list_conversations"] = Field("list_conversations", json_schema_extra={"ui:hidden": True})
    filters: dict[str, Any] | None = Field(None, description="Heymarket filters such as inboxes, closed, unread, ids and unanswered.")


class GetConversation(_Input):
    operation: Literal["get_conversation"] = Field("get_conversation", json_schema_extra={"ui:hidden": True})
    conversation_id: PositiveID


class _ConversationAction(_Input):
    inbox_id: PositiveID
    user_id: PositiveID
    target: Phone


class CloseConversation(_ConversationAction):
    operation: Literal["close_conversation"] = Field("close_conversation", json_schema_extra={"ui:hidden": True})


class OpenConversation(_ConversationAction):
    operation: Literal["open_conversation"] = Field("open_conversation", json_schema_extra={"ui:hidden": True})


class MarkConversationRead(_ConversationAction):
    operation: Literal["mark_conversation_read"] = Field("mark_conversation_read", json_schema_extra={"ui:hidden": True})


class MarkConversationUnread(_ConversationAction):
    operation: Literal["mark_conversation_unread"] = Field("mark_conversation_unread", json_schema_extra={"ui:hidden": True})


class ReassignConversation(_ConversationAction):
    operation: Literal["reassign_conversation"] = Field("reassign_conversation", json_schema_extra={"ui:hidden": True})
    reassign_id: PositiveID


class GetMessages(_Input):
    operation: Literal["get_messages"] = Field("get_messages", json_schema_extra={"ui:hidden": True})
    phone_number: Phone
    inbox_id: PositiveID
    timestamp: int | None = Field(None, ge=0, description="Latest time to search, as a Unix timestamp. Returns one history page.")


class SendMessage(_Input):
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    inbox_id: PositiveID
    creator_id: PositiveID
    phone_number: Phone
    text: str = Field(..., min_length=1, description="SMS message text.")
    media_url: str | None = Field(None, description="Optional publicly accessible MMS media URL. Heymarket retrieves this URL.")
    local_id: str | None = Field(None, description="Optional client message identifier; no automatic retry is performed.")


class ListLists(_Page):
    operation: Literal["list_lists"] = Field("list_lists", json_schema_extra={"ui:hidden": True})


class CreateList(_Input):
    operation: Literal["create_list"] = Field("create_list", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1)
    contacts: list[PositiveID] | None = None
    phones: list[Phone] | None = None
    emails: list[str] | None = None
    local_id: str | None = None


class UpdateList(_Input):
    operation: Literal["update_list"] = Field("update_list", json_schema_extra={"ui:hidden": True})
    list_id: PositiveID
    title: str | None = None
    contacts: list[PositiveID] | None = Field(None, description="Replace the entire list membership. Prefer add_contacts/remove_contacts for incremental changes.")
    add_contacts: list[PositiveID] | None = None
    remove_contacts: list[PositiveID] | None = None
    add_phones: list[Phone] | None = None
    remove_phones: list[Phone] | None = None
    add_emails: list[str] | None = None
    remove_emails: list[str] | None = None


class ListTemplates(_Page):
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})


class GetTemplate(_Input):
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: PositiveID


HeymarketOperation = Annotated[Union[
    ListInboxes, GetTeam, CreateContact, GetContact, UpdateContact, DeleteContact,
    ListContacts, SearchContacts, ListConversations, GetConversation,
    CloseConversation, OpenConversation, MarkConversationRead, MarkConversationUnread,
    ReassignConversation, GetMessages, SendMessage, ListLists, CreateList,
    UpdateList, ListTemplates, GetTemplate,
], Field(discriminator="operation")]


class HeymarketFullConfig(NodeConfig[HeymarketOperation, HeymarketAPISecretCredential]):
    pass


# One entry per published operation; POST pagination endpoints are reads.
ROUTES = {
    "list_inboxes": ("GET", "/v1/inboxes", None, "array"),
    "get_team": ("GET", "/v1/team", None, "object"),
    "create_contact": ("POST", "/v1/contact", None, "object"),
    "get_contact": ("GET", "/v1/contact/{id}", "contact_id", "object"),
    "update_contact": ("PUT", "/v1/contact/{id}", "contact_id", "object"),
    "delete_contact": ("DELETE", "/v1/contact/{id}", "contact_id", "string"),
    "list_contacts": ("POST", "/v2/contacts/list", None, "array"),
    "search_contacts": ("POST", "/v2/contacts/search", None, "array"),
    "list_conversations": ("POST", "/v1/conversations", None, "array"),
    "get_conversation": ("GET", "/v1/conversations/{id}", "conversation_id", "object"),
    "close_conversation": ("POST", "/v1/conversations/close", None, "string"),
    "open_conversation": ("POST", "/v1/conversations/open", None, "string"),
    "mark_conversation_read": ("POST", "/v1/conversations/read", None, "string"),
    "mark_conversation_unread": ("POST", "/v1/conversations/unread", None, "string"),
    "reassign_conversation": ("POST", "/v1/conversations/reassign", None, "string"),
    "get_messages": ("GET", "/v1/messages", None, "array"),
    "send_message": ("POST", "/v1/message/send", None, "object"),
    "list_lists": ("POST", "/v2/lists/paginate", None, "array"),
    "create_list": ("POST", "/v2/lists", None, "object"),
    "update_list": ("PUT", "/v2/lists/{id}", "list_id", "object"),
    "list_templates": ("POST", "/v1/templates", None, "array"),
    "get_template": ("GET", "/v1/template/{id}", "template_id", "object"),
}
READS = frozenset({name for name in ROUTES if name.startswith(("list_", "get_", "search_"))})


def _jwt(credential):
    # Heymarket's published authentication contract uses ID||Key, not Key alone.
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")
    header = encode(b'{"alg":"HS256","typ":"JWT"}')
    payload = encode(json.dumps({"iss": credential.secret_id, "iat": int(time.time())}, separators=(",", ":")).encode())
    signed = header + b"." + payload
    signature = encode(hmac.new(f"{credential.secret_id}||{credential.secret_key}".encode(), signed, hashlib.sha256).digest())
    return (signed + b"." + signature).decode()


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
    return value


class HeymarketNode(WorkflowNode):
    integration_type = "automation-heymarket"
    connection_evidence = ConnectionEvidence(noun="inboxes", operation="list_inboxes")

    @classmethod
    def get_config_model(cls):
        return HeymarketFullConfig

    async def execute(self, input_data):
        if not self.config.credentials:
            raise ValueError("Connect a Heymarket API Secret")
        credential = self.config.credentials
        op = self.config.config
        method, path, path_field, shape = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        if path_field:
            path = path.replace("{id}", str(values.pop(path_field)))
        params = None
        if isinstance(op, UpdateContact):
            params = {"overwrite": str(values.pop("overwrite")).lower()}
        elif isinstance(op, GetMessages):
            params = {"phoneNumber": values["phone_number"], "inboxID": values["inbox_id"]}
            if op.timestamp is not None:
                params["timestamp"] = op.timestamp
        token = _jwt(credential)
        secrets = (token, credential.secret_id, credential.secret_key)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(
                    method, BASE_URL + path, params=params,
                    json=values if method in {"POST", "PUT"} else None,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json, text/plain"},
                )
            if not 200 <= response.status_code < 300:
                output = {"status": "error", "http_status": response.status_code, "message": response.text[:4000] or "Heymarket rejected the request"}
            else:
                if len(response.content) > 10_000_000:
                    raise ValueError("Heymarket response exceeds the supported size")
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                body = response.json() if mime == "application/json" or mime.endswith("+json") else response.text
                if isinstance(body, dict) and (body.get("error") or body.get("errors") or body.get("success") is False):
                    output = {"status": "error", "http_status": response.status_code, "message": body}
                elif not isinstance(body, {"array": list, "object": dict, "string": str}[shape]):
                    raise ValueError("Heymarket returned an unexpected response shape")
                else:
                    output = {"status": "success", "data": body, "http_status": response.status_code}
                    if isinstance(op, _Page):
                        output["pagination"] = {"page": op.page, "limit": op.limit, "single_page": True, "date": op.date}
                    if op.operation not in READS:
                        output["acknowledged"] = True
                        if isinstance(op, SendMessage):
                            output["delivery_verified"] = False
        except httpx.RequestError:
            output = {"status": "error", "message": "Heymarket request did not complete; inspect the account before retrying a write.", "write_outcome": "unknown" if op.operation not in READS else None}
        except (ValueError, TypeError):
            output = {"status": "error", "message": "Heymarket returned an unexpected response; inspect the account before retrying a write.", "write_outcome": "unknown" if op.operation not in READS else None}
        output = _redact(output, secrets)
        await self.emit(output)
        return output
