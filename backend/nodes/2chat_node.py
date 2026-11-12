"""2Chat API-key operations pinned to the provider's published Postman collection.

Each operation issues exactly one request. List results are a single provider
page; use the explicit page parameters to continue. Send success means queued
or accepted, not delivered. No account sign-in or OAuth app is required.
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.p.2chat.io"

class TwoChatAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="2Chat API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.2chat.io/developers?tab=api-access",
            "x-credential-instructions": "Paste your 2Chat API key from Developers → API access. NoClick sends it in the X-User-API-Key header to api.p.2chat.io. The account read verifies which account accepts the key.",
        })
    credential_type: Literal["2chat_api_key"] = Field("2chat_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a header")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class ContactDetail(_Input):
    type: Literal["E", "A", "PH", "WAPH"]
    value: str = Field(..., min_length=1, max_length=2000)

class TwoChatGetAccountConfig(_Input):
    """Get Account Information."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class TwoChatCreateContactConfig(_Input):
    """Create Contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=200)
    last_name: Optional[str] = Field(None, max_length=200)
    channel_uuid: Optional[str] = Field(None, min_length=1, max_length=128)
    contact_detail: list[ContactDetail] = Field(..., min_length=1, max_length=100, description='Published request-body spelling: contact_detail (singular).')


class TwoChatDeleteContactConfig(_Input):
    """Delete Contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    contact_uuid: str = Field(..., min_length=1, max_length=128)


class TwoChatGetContactConfig(_Input):
    """Get Contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_uuid: str = Field(..., min_length=1, max_length=128)


class TwoChatUpdateContactConfig(_Input):
    """Update Contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_uuid: str = Field(..., min_length=1, max_length=128)
    first_name: str = Field(..., min_length=1, max_length=200)
    last_name: Optional[str] = Field(None, max_length=200)


class TwoChatListContactsConfig(_Input):
    """List Contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    results_per_page: int = Field(30, ge=1, le=100)
    page_number: int = Field(0, ge=0, le=1000000, description="Zero-based result page; each call returns one page.")
    channel_uuid: Optional[str] = Field(None, min_length=1, max_length=128)


class TwoChatSearchContactsConfig(_Input):
    """Search Contacts."""
    operation: Literal["search_contacts"] = Field("search_contacts", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=500)
    results_per_page: int = Field(30, ge=1, le=100)
    page_number: int = Field(0, ge=0, le=1000000, description="Zero-based result page; each call returns one page.")
    channel_uuid: Optional[str] = Field(None, min_length=1, max_length=128)


class TwoChatListWebhooksConfig(_Input):
    """List All Webhooks."""
    operation: Literal["list_webhooks"] = Field("list_webhooks", json_schema_extra={"ui:hidden": True})


class TwoChatListNumbersConfig(_Input):
    """List Numbers."""
    operation: Literal["list_numbers"] = Field("list_numbers", json_schema_extra={"ui:hidden": True})
    page_number: Optional[int] = Field(None, ge=0, le=1000000, description="Zero-based result page; each call returns one page.")
    results_per_page: Optional[int] = Field(None, ge=1, le=100)
    status: Optional[Literal["connected", "disconnected", "all"]] = None


class TwoChatGetNumberConfig(_Input):
    """Get Number."""
    operation: Literal["get_number"] = Field("get_number", json_schema_extra={"ui:hidden": True})
    channel_uuid: str = Field(..., min_length=1, max_length=128)


class TwoChatSendMessageConfig(_Input):
    """Send Text / Media Message."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    from_number: str = Field(..., pattern=r'^\+[1-9][0-9]{6,14}$', description='Your connected sending number in E.164 format.')
    to_number: str = Field(..., pattern=r'^\+[1-9][0-9]{6,14}$', description='Recipient in E.164 format.')
    text: str = Field(..., min_length=1, max_length=65536)
    url: Optional[str] = Field(None, pattern=r'^https://[^\s]+$', description='Public media URL, maximum 16 MB; omit for text only.')


class TwoChatGetMessagesConfig(_Input):
    """Get Messages."""
    operation: Literal["get_messages"] = Field("get_messages", json_schema_extra={"ui:hidden": True})
    connected_number: str = Field(..., pattern=r'^\+[1-9][0-9]{6,14}$', description='Your connected WhatsApp number in E.164 format.')
    to_number: str = Field(..., pattern=r'^\+[1-9][0-9]{6,14}$', description='Recipient in E.164 format.')
    page_number: Optional[int] = Field(None, ge=0, le=1000000, description="Zero-based result page; each call returns one page.")


class TwoChatGetMessageConfig(_Input):
    """Get Single Message."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})
    session_key: str = Field(..., min_length=1, max_length=512)
    message_uuid: str = Field(..., min_length=1, max_length=128)


class TwoChatListConversationsConfig(_Input):
    """List Conversations."""
    operation: Literal["list_conversations"] = Field("list_conversations", json_schema_extra={"ui:hidden": True})
    channel_uuid: str = Field(..., min_length=1, max_length=128)
    page_number: Optional[int] = Field(None, ge=0, le=1000000, description="Zero-based result page; each call returns one page.")
    phone_number: Optional[str] = Field(None, pattern=r"^[0-9]{3,20}$")


class TwoChatListGroupsConfig(_Input):
    """List WhatsApp Groups."""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})
    connected_number: str = Field(..., pattern=r'^\+[1-9][0-9]{6,14}$', description='Your connected WhatsApp number in E.164 format.')


class TwoChatGetGroupConfig(_Input):
    """List WhatsApp Group Participants."""
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})
    whatsapp_group_uuid: str = Field(..., min_length=1, max_length=128)


class TwoChatSendSmsConfig(_Input):
    """Send An SMS Message."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:hidden": True})
    from_number: str = Field(..., pattern=r'^\+[1-9][0-9]{6,14}$', description='Your connected sending number in E.164 format.')
    to_number: str = Field(..., pattern=r'^\+[1-9][0-9]{6,14}$', description='Recipient in E.164 format.')
    text: str = Field(..., min_length=1, max_length=65536)


class TwoChatListUsersConfig(_Input):
    """List Users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class TwoChatListTagsConfig(_Input):
    """List Tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0, le=1000000, description="Zero-based result page; each call returns one page.")
    page_size: int = Field(20, ge=1, le=50)


class TwoChatCreateTagConfig(_Input):
    """Create Tag."""
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100)
    session_key: Optional[str] = Field(None, min_length=1, max_length=512)


class TwoChatUpdateTagConfig(_Input):
    """Update Tag."""
    operation: Literal["update_tag"] = Field("update_tag", json_schema_extra={"ui:hidden": True})
    tag_uuid: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=100)
    color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')


class TwoChatDeleteTagConfig(_Input):
    """Delete Tag."""
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra={"ui:hidden": True})
    tag_uuid: str = Field(..., min_length=1, max_length=128)


class TwoChatGetConversationTagsConfig(_Input):
    """Get Conversation Tags."""
    operation: Literal["get_conversation_tags"] = Field("get_conversation_tags", json_schema_extra={"ui:hidden": True})
    session_key: str = Field(..., min_length=1, max_length=512)


class TwoChatAddConversationTagConfig(_Input):
    """Add Tag To Conversation."""
    operation: Literal["add_conversation_tag"] = Field("add_conversation_tag", json_schema_extra={"ui:hidden": True})
    tag_uuid: str = Field(..., min_length=1, max_length=128)
    session_key: str = Field(..., min_length=1, max_length=512)


class TwoChatRemoveConversationTagConfig(_Input):
    """Remove Tag From Conversation."""
    operation: Literal["remove_conversation_tag"] = Field("remove_conversation_tag", json_schema_extra={"ui:hidden": True})
    tag_uuid: str = Field(..., min_length=1, max_length=128)
    session_key: str = Field(..., min_length=1, max_length=512)


TwoChatConfig = Annotated[Union[
    TwoChatGetAccountConfig,
    TwoChatCreateContactConfig,
    TwoChatDeleteContactConfig,
    TwoChatGetContactConfig,
    TwoChatUpdateContactConfig,
    TwoChatListContactsConfig,
    TwoChatSearchContactsConfig,
    TwoChatListWebhooksConfig,
    TwoChatListNumbersConfig,
    TwoChatGetNumberConfig,
    TwoChatSendMessageConfig,
    TwoChatGetMessagesConfig,
    TwoChatGetMessageConfig,
    TwoChatListConversationsConfig,
    TwoChatListGroupsConfig,
    TwoChatGetGroupConfig,
    TwoChatSendSmsConfig,
    TwoChatListUsersConfig,
    TwoChatListTagsConfig,
    TwoChatCreateTagConfig,
    TwoChatUpdateTagConfig,
    TwoChatDeleteTagConfig,
    TwoChatGetConversationTagsConfig,
    TwoChatAddConversationTagConfig,
    TwoChatRemoveConversationTagConfig
], Field(discriminator="operation")]

# 2Chat's own MCP server: agents get its tools through a person's 2Chat sign-in.
TwoChatMcpCredential = mcp_credential("two_chat", "https://mcp.2chat.io/mcp", app="2Chat")
TwoChatCredential = Union[TwoChatAPIKeyCredential, TwoChatMcpCredential]


class TwoChatNodeConfig(NodeConfig[TwoChatConfig, TwoChatCredential]):
    model_config = ConfigDict(title="2Chat Node Configuration")

ROUTES = {'get_account': ('GET', '/open/info', []), 'create_contact': ('POST', '/open/contacts', []), 'delete_contact': ('DELETE', '/open/contacts/{contact_uuid}', []), 'get_contact': ('GET', '/open/contacts/{contact_uuid}', []), 'update_contact': ('PUT', '/open/contacts/{contact_uuid}', []), 'list_contacts': ('GET', '/open/contacts', ['results_per_page', 'page_number', 'channel_uuid']), 'search_contacts': ('GET', '/open/contacts/search', ['query', 'results_per_page', 'page_number', 'channel_uuid']), 'list_webhooks': ('GET', '/open/webhooks', []), 'list_numbers': ('GET', '/open/whatsapp/get-numbers', ['page_number', 'results_per_page', 'status']), 'get_number': ('GET', '/open/whatsapp/channel/{channel_uuid}', []), 'send_message': ('POST', '/open/whatsapp/send-message', []), 'get_messages': ('GET', '/open/whatsapp/messages/{connected_number}/{to_number}', ['page_number']), 'get_message': ('GET', '/open/whatsapp/message/{session_key}/{message_uuid}', []), 'list_conversations': ('GET', '/open/whatsapp/conversations/{channel_uuid}', ['page_number', 'phone_number']), 'list_groups': ('GET', '/open/whatsapp/groups/{connected_number}', []), 'get_group': ('GET', '/open/whatsapp/group/{whatsapp_group_uuid}', []), 'send_sms': ('POST', '/open/sms/send', []), 'list_users': ('GET', '/open/users', []), 'list_tags': ('GET', '/open/tags', ['page', 'page_size']), 'create_tag': ('POST', '/open/tags', []), 'update_tag': ('PUT', '/open/tags/{tag_uuid}', []), 'delete_tag': ('DELETE', '/open/tags/{tag_uuid}', []), 'get_conversation_tags': ('GET', '/open/tags/sessions/{session_key}', []), 'add_conversation_tag': ('POST', '/open/tags/{tag_uuid}/sessions', []), 'remove_conversation_tag': ('DELETE', '/open/tags/{tag_uuid}/sessions/{session_key}', [])}

def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class TwoChatNode(WorkflowNode):
    integration_type = "automation-2chat"
    credential_provider_labels = {"2chat": "2Chat Account"}
    connection_evidence = ConnectionEvidence(noun="2Chat account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return TwoChatNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a 2Chat API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route, query_fields = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        for name in tuple(values):
            marker = "{" + name + "}"
            if marker in route:
                route = route.replace(marker, quote(str(values.pop(name)), safe=""))
        params = {name: values.pop(name) for name in query_fields if name in values}
        kwargs = {"params": params} if params else {}
        if method in {"POST", "PUT"}:
            kwargs["json"] = values
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"X-User-API-Key": key, "Accept": "application/json", "Content-Type": "application/json"}, **kwargs)
        except httpx.TransportError:
            raise ValueError("2Chat request did not complete" +
                ("; the write outcome is unknown, inspect before retrying" if method != "GET" else "")) from None
        if not 200 <= response.status_code < 300:
            raise ValueError(f"2Chat HTTP {response.status_code}: " + response.text.replace(key, "[redacted]")[:1000])
        if len(response.content) > 10000000:
            raise ValueError("2Chat response exceeds the supported JSON size")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("2Chat returned invalid JSON") from None
        if not isinstance(body, dict):
            raise ValueError("2Chat returned an unexpected JSON shape")
        if body.get("success") is not True or body.get("error") or body.get("errors"):
            raise ValueError("2Chat: " + str(_redact(body, key))[:1000])
        if config.operation == "get_account" and not (
            isinstance(body.get("account"), dict) and body["account"].get("name") and body["account"].get("uuid")
        ):
            raise ValueError("2Chat account identity is missing")
        output = _redact({"status": "success", "data": body, "http_status": response.status_code}, key)
        await self.emit(output)
        return output
