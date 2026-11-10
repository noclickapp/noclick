"""OpenWA 0.30.0: session, messaging, contact and group automation.

Contract: https://github.com/rmyndharis/OpenWA/blob/main/openapi.json
Webhook payload: docs/22-n8n-integration.md; signing: docs/examples/webhook-signature-verification.md.
This is the self-hosted rmyndharis/OpenWA gateway, not @open-wa/wa-automate.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

DOCS = "https://github.com/rmyndharis/OpenWA/blob/main/docs/06-api-specification.md"


class OpenWAAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="OpenWA API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": DOCS,
        "x-credential-instructions": "Enter your publicly reachable HTTPS OpenWA server origin and paste its API key. An operator key can send messages; a viewer key supports reads. NoClick lists the sessions visible to your key to check the connection. Use an already linked WhatsApp session."})
    credential_type: Literal["openwa_api_key"] = Field("openwa_api_key", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Server URL", description="Public HTTPS origin of your OpenWA gateway, for example https://openwa.example.com.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url", mode="before")
    @classmethod
    def origin(cls, value):
        origin = https_origin(value, field_name="Server URL")
        parts = urlsplit(origin)
        if parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443):
            raise ValueError("Use the public HTTPS origin of your OpenWA gateway")
        return origin

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    contract_id: str
    label: str
    fields: dict[str, tuple[Any, Any]]
    query: tuple[tuple[str, str], ...] = ()
    body: tuple[str, ...] = ()


def field(kind, *, required=False, description="", **constraints):
    return (kind if required else kind | None,
            Field(... if required else None, description=description, **constraints))


# Each entry maps to exactly one published operationId. No arbitrary routes.
OPERATIONS = {
    'list_sessions': Operation('GET', '/api/sessions', 'SessionController_findAll', 'List all sessions', {
        'limit': field(int, required=False, description='', ge=1, le=1000),
        'offset': field(int, required=False, description='', ge=0),
        'name': field(str, required=False, description=''),
    }, query=(('limit', 'limit'), ('offset', 'offset'), ('name', 'name')), body=()),
    'get_session': Operation('GET', '/api/sessions/{sessionId}', 'SessionController_findOne', 'Get session by ID', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
    }, query=(), body=()),
    'list_chats': Operation('GET', '/api/sessions/{sessionId}/chats', 'SessionController_getChats', 'Get active chats for a session', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'limit': field(int, required=False, description='', ge=1, le=1000),
        'offset': field(int, required=False, description='', ge=0),
    }, query=(('limit', 'limit'), ('offset', 'offset')), body=()),
    'list_messages': Operation('GET', '/api/sessions/{sessionId}/messages', 'MessageController_getMessages', 'Get message history for a session', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=False, description=''),
        'sender': field(str, required=False, description=''),
        'limit': field(int, required=False, description='', ge=1, le=1000),
        'offset': field(int, required=False, description='', ge=0),
        'after': field(str, required=False, description=''),
        'inlineMedia': field(bool, required=False, description=''),
        'since': field(float, required=False, description=''),
        'until': field(float, required=False, description=''),
        'direction': field(Literal['incoming', 'outgoing'], required=False, description=''),
        'orderBy': field(Literal['createdAt', 'timestamp'], required=False, description=''),
        'type': field(str, required=False, description=''),
        'messageId': field(str, required=False, description=''),
    }, query=(('chatId', 'chatId'), ('sender', 'from'), ('limit', 'limit'), ('offset', 'offset'), ('after', 'after'), ('inlineMedia', 'inlineMedia'), ('since', 'since'), ('until', 'until'), ('direction', 'direction'), ('orderBy', 'orderBy'), ('type', 'type'), ('messageId', 'messageId')), body=()),
    'send_text': Operation('POST', '/api/sessions/{sessionId}/messages/send-text', 'MessageController_sendText', 'Send a text message', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='WhatsApp chat ID (phone@c.us for individual, groupId@g.us for groups)', max_length=255),
        'text': field(str, required=True, description='Text message content', max_length=4096),
        'mentions': field(list[str], required=False, description='WIDs to @mention (e.g. ["62811@c.us"]). The text/caption must also contain the @<number> token.', max_length=1024),
        'linkPreview': field(bool, required=False, description='Controls the URL preview, and the engines differ. On whatsapp-web.js WhatsApp Web builds one by default and `false` suppresses it. On Baileys previews are OPT-IN: `true` asks the gateway to fetch the page and attach one, while unset or `false` sends none — generating a preview is a blocking outbound fetch per URL in the text, so it is never done unless asked for.'),
        'quotedMessageId': field(str, required=False, description='Quote an earlier message, turning this send into a reply. The id is engine-specific: whatsapp-web.js matches the serialized message id, Baileys matches the raw message key id and can only quote a message it has already stored. An id that cannot be resolved fails the send rather than delivering it unquoted.'),
    }, query=(), body=('chatId', 'text', 'mentions', 'linkPreview', 'quotedMessageId')),
    'reply': Operation('POST', '/api/sessions/{sessionId}/messages/reply', 'MessageController_reply', 'Reply to a message', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='', max_length=255),
        'quotedMessageId': field(str, required=True, description=''),
        'text': field(str, required=True, description='', max_length=4096),
        'mentions': field(list[str], required=False, description='WIDs to @mention (e.g. ["62811@c.us"]). The text/caption must also contain the @<number> token.', max_length=1024),
    }, query=(), body=('chatId', 'quotedMessageId', 'text', 'mentions')),
    'send_image': Operation('POST', '/api/sessions/{sessionId}/messages/send-image', 'MessageController_sendImage', 'Send an image message', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='WhatsApp chat ID', max_length=255),
        'url': field(str, required=True, description='Media URL (http/https)'),
        'mimetype': field(str, required=False, description='Media MIME type (required when using base64)'),
        'filename': field(str, required=False, description="Filename for the media. Only rendered on document sends — defaults to 'file' when omitted (a URL-based document send on whatsapp-web.js first derives the URL basename)", max_length=255),
        'caption': field(str, required=False, description='Caption for the media', max_length=1024),
        'mentions': field(list[str], required=False, description='WIDs to @mention (e.g. ["62811@c.us"]). The text/caption must also contain the @<number> token.', max_length=1024),
        'quotedMessageId': field(str, required=False, description='Quote an earlier message, turning this send into a reply. The id is engine-specific: whatsapp-web.js matches the serialized message id, Baileys matches the raw message key id and can only quote a message it has already stored. An id that cannot be resolved fails the send rather than delivering it unquoted.'),
    }, query=(), body=('chatId', 'url', 'mimetype', 'filename', 'caption', 'mentions', 'quotedMessageId')),
    'send_document': Operation('POST', '/api/sessions/{sessionId}/messages/send-document', 'MessageController_sendDocument', 'Send a document/file', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='WhatsApp chat ID', max_length=255),
        'url': field(str, required=True, description='Media URL (http/https)'),
        'mimetype': field(str, required=False, description='Media MIME type (required when using base64)'),
        'filename': field(str, required=False, description="Filename for the media. Only rendered on document sends — defaults to 'file' when omitted (a URL-based document send on whatsapp-web.js first derives the URL basename)", max_length=255),
        'caption': field(str, required=False, description='Caption for the media', max_length=1024),
        'mentions': field(list[str], required=False, description='WIDs to @mention (e.g. ["62811@c.us"]). The text/caption must also contain the @<number> token.', max_length=1024),
        'quotedMessageId': field(str, required=False, description='Quote an earlier message, turning this send into a reply. The id is engine-specific: whatsapp-web.js matches the serialized message id, Baileys matches the raw message key id and can only quote a message it has already stored. An id that cannot be resolved fails the send rather than delivering it unquoted.'),
    }, query=(), body=('chatId', 'url', 'mimetype', 'filename', 'caption', 'mentions', 'quotedMessageId')),
    'react': Operation('POST', '/api/sessions/{sessionId}/messages/react', 'MessageController_react', 'Add or remove a reaction to a message', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='', max_length=255),
        'messageId': field(str, required=True, description=''),
        'emoji': (str, Field('', description='Emoji to react with. Leave empty to remove the reaction.', max_length=32)),
    }, query=(), body=('chatId', 'messageId', 'emoji')),
    'forward_message': Operation('POST', '/api/sessions/{sessionId}/messages/forward', 'MessageController_forward', 'Forward a message to another chat', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'fromChatId': field(str, required=True, description='', max_length=255),
        'toChatId': field(str, required=True, description='', max_length=255),
        'messageId': field(str, required=True, description=''),
    }, query=(), body=('fromChatId', 'toChatId', 'messageId')),
    'edit_message': Operation('POST', '/api/sessions/{sessionId}/messages/edit', 'MessageController_edit', 'Edit the text of a message sent by this account', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='', max_length=255),
        'messageId': field(str, required=True, description=''),
        'body': field(str, required=True, description='New text body for the message', max_length=4096),
        'mentions': field(list[str], required=False, description='WIDs to @mention (e.g. ["62811@c.us"]). The text/caption must also contain the @<number> token.', max_length=1024),
    }, query=(), body=('chatId', 'messageId', 'body', 'mentions')),
    'delete_message': Operation('POST', '/api/sessions/{sessionId}/messages/delete', 'MessageController_deleteMessage', 'Delete a message', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='', max_length=255),
        'messageId': field(str, required=True, description=''),
        'forEveryone': field(bool, required=False, description='Delete for everyone (default true)'),
    }, query=(), body=('chatId', 'messageId', 'forEveryone')),
    'list_contacts': Operation('GET', '/api/sessions/{sessionId}/contacts', 'ContactController_findAll', 'Get all contacts for a session', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'limit': field(int, required=False, description='', ge=1, le=1000),
        'offset': field(int, required=False, description='', ge=0),
    }, query=(('limit', 'limit'), ('offset', 'offset')), body=()),
    'get_contact': Operation('GET', '/api/sessions/{sessionId}/contacts/{contactId}', 'ContactController_findOne', 'Get a specific contact by ID', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'contactId': field(str, required=True, description=''),
    }, query=(), body=()),
    'check_number': Operation('GET', '/api/sessions/{sessionId}/contacts/check/{number}', 'ContactController_checkNumber', 'Check if a phone number exists on WhatsApp', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'number': field(str, required=True, description=''),
    }, query=(), body=()),
    'list_groups': Operation('GET', '/api/sessions/{sessionId}/groups', 'SessionController_getGroups', 'Get all groups for a session', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'limit': field(int, required=False, description='', ge=1, le=1000),
        'offset': field(int, required=False, description='', ge=0),
    }, query=(('limit', 'limit'), ('offset', 'offset')), body=()),
    'get_group': Operation('GET', '/api/sessions/{sessionId}/groups/{groupId}', 'GroupController_findOne', 'Get detailed group info', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'groupId': field(str, required=True, description=''),
    }, query=(), body=()),
    'create_group': Operation('POST', '/api/sessions/{sessionId}/groups', 'GroupController_create', 'Create a new group', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'name': field(str, required=True, description='Group subject/name', max_length=100),
        'participants': field(list[str], required=True, description='Participant WhatsApp IDs (e.g. 12025550101@c.us)', max_length=256),
    }, query=(), body=('name', 'participants')),
    'list_templates': Operation('GET', '/api/sessions/{sessionId}/templates', 'TemplateController_findBySession', 'List all templates for a session', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
    }, query=(), body=()),
    'send_template': Operation('POST', '/api/sessions/{sessionId}/messages/send-template', 'MessageController_sendTemplate', 'Render a stored text template and send it as a text message', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='WhatsApp chat ID (phone@c.us for individual, groupId@g.us for groups)', max_length=255),
        'templateId': field(str, required=True, description='Template ID to render. Provide either templateId or templateName.'),
        'vars': field(dict[str, Any], required=False, description='Variables substituted into {{placeholder}} tokens in the template'),
        'mentions': field(list[str], required=False, description='WIDs to @mention (e.g. ["62811@c.us"]). The text/caption must also contain the @<number> token.', max_length=1024),
        'linkPreview': field(bool, required=False, description='Controls the URL preview on the rendered body, with the same engine split as send-text: whatsapp-web.js builds one by default and `false` suppresses it, while on Baileys previews are opt-in and only `true` attaches one.'),
    }, query=(), body=('chatId', 'templateId', 'vars', 'mentions', 'linkPreview')),
    'mark_read': Operation('POST', '/api/sessions/{sessionId}/chats/read', 'SessionController_markChatRead', 'Mark a chat as read/seen', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='Chat ID in the neutral form the gateway returns, on either engine (e.g. 12025550101@c.us)', max_length=255),
        'messageIds': field(list[str], required=False, description='Specific message IDs to mark read. Baileys acknowledges individual messages, so without this only the newest received message the engine still holds in memory gets a receipt — a burst leaves its earlier messages unread forever, and a restarted session has no message to acknowledge at all. Callers that persist inbound message IDs should send them here. Ignored by whatsapp-web.js, whose own sendSeen is chat-level.', max_length=100, min_length=1),
    }, query=(), body=('chatId', 'messageIds')),
    'archive_chat': Operation('POST', '/api/sessions/{sessionId}/chats/archive', 'SessionController_archiveChat', 'Archive or unarchive a chat', {
        'sessionId': field(str, required=True, description='', pattern='^[A-Za-z0-9-]{1,128}$', json_schema_extra={'x-dynamic-options': {'field_name': 'sessionId', 'allow_custom': True, 'searchable': True}}),
        'chatId': field(str, required=True, description='Chat ID in the neutral form the gateway returns, on either engine (e.g. 1234567890-123@g.us)', max_length=255),
        'archive': field(bool, required=True, description='true to archive, false to unarchive.'),
    }, query=(), body=('chatId', 'archive')),
}

CONFIG_MODELS = {}
for _name, _spec in OPERATIONS.items():
    _model = create_model("OpenWA" + "".join(part.title() for part in _name.split("_")) + "Config",
        __base__=_Input, operation=(Literal[_name], Field(_name, json_schema_extra={
            "ui:hidden": True, "x-display-name": _spec.label,
            "x-category": "Read" if _spec.method == "GET" else "Write"})), **_spec.fields)
    CONFIG_MODELS[_name] = _model


class OpenWAOnMessageConfig(WebhookTriggerConfigBase):
    operation: Literal["on_message"] = Field("on_message", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Incoming Message", "x-category": "Triggers"})
    sessionId: str = Field(..., pattern=r"^[A-Za-z0-9-]{1,128}$", title="Session",
        json_schema_extra={"x-dynamic-options": {"field_name": "sessionId", "allow_custom": True, "searchable": True}})
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered automatically with OpenWA.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


OpenWAConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (OpenWAOnMessageConfig,)], Field(discriminator="operation")]


class OpenWANodeConfig(NodeConfig[OpenWAConfig, OpenWAAPIKeyCredential]):
    pass


def _segment(value):
    if not isinstance(value, str) or not value or value in (".", ".."):
        raise ValueError("A resource ID is required")
    return quote(value, safe="")


class OpenWANode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-openwa"
    connection_evidence = ConnectionEvidence(operation="list_sessions", noun="sessions", label_keys=("name", "id"))
    webhook_replace_stale_endpoint = True

    @classmethod
    def get_config_model(cls):
        return OpenWANodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        cred = OpenWAAPIKeyCredential.model_validate(credential)
        async with guarded_async_client(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, cred.server_url + path,
                params=params, json=body, headers={"X-API-Key": cred.api_key, "Accept": "application/json"})
        if response.is_error or response.is_redirect:
            try:
                message = response.json().get("message") or "Request failed"
            except (ValueError, AttributeError):
                message = "Expected a JSON API response; check the server origin"
            raise ValueError(f"OpenWA API {response.status_code}: {str(message).replace(cred.api_key, '[redacted]')[:1000]}")
        return response.json() if response.content else {"ok": True}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an OpenWA API key")
        op = self.config.config
        if isinstance(op, OpenWAOnMessageConfig):
            return self.no_event_output(op.operation)
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", _segment(values.pop(key)))
        params = {wire: values[key] for key, wire in spec.query if key in values}
        body = {key: values[key] for key in spec.body if key in values}
        result = await self._request(self.config.credentials.model_dump(), spec.method, path,
            params=params or None, body=body if spec.body else None)
        output = {"status": "success", "operation": op.operation, "data": result}
        await self.emit(output)
        return output

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "sessionId":
            return {"options": []}
        offset = int(page_token or 0)
        rows = await cls._request(credential_data, "GET", "/api/sessions", params={"limit": 100, "offset": offset})
        if not isinstance(rows, list):
            raise ValueError("OpenWA did not return a session list")
        options = [{"value": str(row["id"]), "label": str(row.get("name") or row["id"])}
            for row in rows if isinstance(row, dict) and row.get("id")]
        if search:
            options = [row for row in options if search.lower() in row["label"].lower()]
        return {"options": options, "next_page_token": str(offset + 100) if len(rows) == 100 else None}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = OpenWAOnMessageConfig.model_validate(config)
        secret = secrets.token_hex(32)
        data = await cls._request(credential, "POST", f"/api/sessions/{_segment(op.sessionId)}/webhooks",
            body={"url": webhook_url, "events": ["message.received"], "secret": secret})
        if not isinstance(data, dict) or not data.get("id"):
            raise ValueError("OpenWA did not return a webhook ID")
        # The provider never returns the secret: retain the one sent at registration.
        # Retain the original session with the endpoint ID so a session change
        # tears down the old registration in its own session.
        return {"external_webhook_id": f"{op.sessionId}:{data['id']}", "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not credential or not config.get("external_webhook_id"):
            return
        session, endpoint = str(config["external_webhook_id"]).split(":", 1)
        await cls._request(credential, "DELETE",
            f"/api/sessions/{_segment(session)}/webhooks/{_segment(endpoint)}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"sessionId": (config or {}).get("sessionId")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        supplied = next((v for k, v in headers.items() if k.lower() == "x-openwa-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(supplied, str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", supplied):
            return False
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(supplied, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (isinstance(payload, dict) and payload.get("event") == "message.received"
            and payload.get("sessionId") == (config or {}).get("sessionId"))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event") != "message.received":
            return None
        data = output.get("data")
        if not isinstance(data, dict):
            return None
        session = output.get("sessionId")
        sender = data.get("from")
        chat = data.get("chatId")
        message = data.get("id")
        content = str(data.get("body") or "")[:3000]
        return {"text": f"OpenWA incoming message from {sender} in chat {chat}:\n{content}\n"
                f"Session ID: {session}; chat ID: {chat}; message ID: {message}. Use reply with quotedMessageId to respond.",
            "conversation_key": f"openwa:{session}:{chat}", "title": f"WhatsApp: {sender}"}
