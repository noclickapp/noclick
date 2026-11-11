"""Pidgeon email API, pinned to the provider's OpenAPI 1.67.4.

Webhook deliveries use the example and signature protocol in
https://pidgeon.ai/docs/webhooks and /docs/webhooks/verifying.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://pidgeon.ai/api/v1"

class PidgeonCredential(BaseModel):
    model_config = ConfigDict(title="Pidgeon API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://pidgeon.ai/docs/authentication",
        "x-credential-instructions": "Paste an existing Pidgeon API key. Read access proves the connection; sending requires send access and address administration requires admin access. The key is sent only to pidgeon.ai."})
    credential_type: Literal["pidgeon_api_key"] = Field("pidgeon_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _EventsInput(_Input):
    @model_validator(mode="after")
    def one_direction(self):
        if self.cursor and self.after:
            raise ValueError("Use either Cursor for history or After for forward recovery")
        return self

# Each table entry is (HTTP method, path, query wire names, body wire names,
# config-to-wire aliases, fields). No generic arbitrary HTTP operation is exposed.
OPERATIONS = {
    'get_account': ('GET', '/me', [], [], {}, {
    }),
    'list_identities': ('GET', '/identities', ['limit', 'cursor', 'tenant_id', 'pod_id'], [], {}, {
        'limit': (int | None, Field(None, title='Limit', ge=1, le=200)),
        'cursor': (str | None, Field(None, title='Cursor', description='From a previous page’s `next_cursor`. Opaque — do not parse it.')),
        'tenant_id': (str | None, Field(None, title='Tenant Id', max_length=200)),
        'pod_id': (str | None, Field(None, title='Pod Id', json_schema_extra={'format': 'uuid'})),
    }),
    'create_identity': ('POST', '/identities', [], ['address', 'display_name', 'inbox', 'type', 'mode'], {}, {
        'address': (str, Field(..., min_length=3, title='Address', description='A whole address — the local part and the domain in one. An alternative to the other two.', max_length=320)),
        'display_name': (str | None, Field(None, title='Display Name', description='The name a recipient sees beside the address.', max_length=120)),
        'inbox': (bool | None, Field(None, title='Inbox', description='Whether it keeps mail. With an inbox what arrives is stored and a person can open it; without one it becomes an event and your webhook fires. Defaults from `type`.')),
        'type': (Literal['human', 'team', 'application', 'workflow', 'agent'] | None, Field(None, title='Type', description='A label for what this address is for. It does not change what the address can do — that is `inbox`.')),
        'mode': (Literal['human', 'automated', 'hybrid'] | None, Field(None, title='Mode', description='Who answers: a person, software, or both.')),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'get_identity': ('GET', '/identities/{id}', [], [], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
    }),
    'update_identity': ('PATCH', '/identities/{id}', [], ['display_name', 'mode', 'status'], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        'display_name': (str | None, Field(None, title='Display Name', description='The name a recipient sees beside the address.', max_length=120)),
        'mode': (Literal['human', 'automated', 'hybrid'] | None, Field(None, title='Mode', description='Who answers: a person, software, or both.')),
        'status': (Literal['active', 'suspended', 'archived'] | None, Field(None, title='Status')),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'delete_identity': ('DELETE', '/identities/{id}', [], [], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'list_messages': ('GET', '/messages', ['limit', 'cursor', 'thread_id', 'body'], [], {'body_format': 'body'}, {
        'limit': (int | None, Field(None, title='Limit', ge=1, le=200)),
        'cursor': (str | None, Field(None, title='Cursor', description='From a previous page’s `next_cursor`. Opaque — do not parse it.', max_length=200)),
        'thread_id': (str, Field(..., title='Thread Id', json_schema_extra={'format': 'uuid'})),
        'body_format': (Literal['original', 'clean'] | None, Field(None, title='Body Format')),
    }),
    'search_messages': ('GET', '/messages/search', ['identity_id', 'q', 'in', 'from', 'to', 'limit', 'cursor'], [], {'folder': 'in', 'from_address': 'from'}, {
        'identity_id': (str | None, Field(None, title='Identity Id', json_schema_extra={'format': 'uuid'})),
        'q': (str | None, Field(None, title='Search Query', max_length=200)),
        'folder': (Literal['inbox', 'starred', 'sent', 'drafts', 'scheduled', 'snoozed', 'archive', 'spam', 'trash', 'unauthenticated'] | None, Field(None, title='Folder')),
        'from_address': (str | None, Field(None, title='From Address', max_length=200)),
        'to': (str | None, Field(None, title='To', max_length=200)),
        'limit': (int | None, Field(None, title='Limit', ge=1, le=100)),
        'cursor': (str | None, Field(None, title='Cursor', description='From a previous page’s `next_cursor`. Opaque — do not parse it.', max_length=500)),
    }),
    'get_message': ('GET', '/messages/{id}', ['body'], [], {'body_format': 'body'}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        'body_format': (Literal['original', 'clean'] | None, Field(None, title='Body Format')),
    }),
    'send_message': ('POST', '/messages', [], ['from', 'to', 'cc', 'bcc', 'subject', 'text', 'html', 'reply_to', 'send_at'], {'from_address': 'from'}, {
        'from_address': (str, Field(..., title='From Address', description='An address on a domain you own, and one this key may send from.', json_schema_extra={'format': 'email'})),
        'to': (str, Field(..., title='To', description='One recipient email address.', json_schema_extra={'format': 'email'})),
        'cc': (str | None, Field(None, title='Cc', description='Copied, and visible to everybody who receives the message.', json_schema_extra={'format': 'email'})),
        'bcc': (str | None, Field(None, title='Bcc', description='Copied, and visible to nobody else.', json_schema_extra={'format': 'email'})),
        'subject': (str | None, Field(None, title='Subject', description='Left off a reply, where the thread already has one.', max_length=500)),
        'text': (str | None, Field(None, title='Text', description='The plain-text body. Send this even when you send `html` — some clients only read it.', max_length=500000, json_schema_extra={'ui:widget': 'textarea'})),
        'html': (str | None, Field(None, title='HTML', description='The rich body. Sanitised on the way in; scripts and remote content are removed.', max_length=1000000, json_schema_extra={'ui:widget': 'textarea'})),
        'reply_to': (str | None, Field(None, title='Reply To', description='Where replies go, when not to `from`: one of your own addresses, or an address on a domain you have verified.', json_schema_extra={'format': 'email'})),
        'send_at': (str | None, Field(None, title='Send At', json_schema_extra={'format': 'date-time'})),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'reply_to_message': ('POST', '/messages/{id}/reply', [], ['text', 'html', 'to', 'cc', 'bcc'], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        'text': (str | None, Field(None, title='Text', description='The plain-text body. Send this even when you send `html` — some clients only read it.', max_length=500000, json_schema_extra={'ui:widget': 'textarea'})),
        'html': (str | None, Field(None, title='HTML', description='The rich body. Sanitised on the way in; scripts and remote content are removed.', max_length=1000000, json_schema_extra={'ui:widget': 'textarea'})),
        'to': (str | None, Field(None, title='To', description='One recipient email address.', json_schema_extra={'format': 'email'})),
        'cc': (str | None, Field(None, title='Cc', description='Copied, and visible to everybody who receives the message.', json_schema_extra={'format': 'email'})),
        'bcc': (str | None, Field(None, title='Bcc', description='Copied, and visible to nobody else.', json_schema_extra={'format': 'email'})),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'reply_all': ('POST', '/messages/{id}/reply-all', [], ['text', 'html'], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        'text': (str | None, Field(None, title='Text', description='The plain-text body. Send this even when you send `html` — some clients only read it.', max_length=500000, json_schema_extra={'ui:widget': 'textarea'})),
        'html': (str | None, Field(None, title='HTML', description='The rich body. Sanitised on the way in; scripts and remote content are removed.', max_length=1000000, json_schema_extra={'ui:widget': 'textarea'})),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'forward_message': ('POST', '/messages/{id}/forward', [], ['text', 'html', 'to'], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        'text': (str | None, Field(None, title='Text', description='The plain-text body. Send this even when you send `html` — some clients only read it.', max_length=500000, json_schema_extra={'ui:widget': 'textarea'})),
        'html': (str | None, Field(None, title='HTML', description='The rich body. Sanitised on the way in; scripts and remote content are removed.', max_length=1000000, json_schema_extra={'ui:widget': 'textarea'})),
        'to': (str | None, Field(None, title='To', description='One recipient email address.', json_schema_extra={'format': 'email'})),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'update_message': ('PATCH', '/messages/{id}', [], ['is_starred', 'folder'], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        'is_starred': (bool | None, Field(None, title='Is Starred')),
        'folder': (Literal['inbox', 'archive', 'spam', 'trash'] | None, Field(None, title='Folder')),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'list_events': ('GET', '/events', ['limit', 'cursor', 'type', 'identity_id', 'after'], [], {}, {
        'limit': (int | None, Field(None, title='Page Size', ge=1, le=200)),
        'cursor': (str | None, Field(None, title='Page Cursor', description='Pages backward through history. Do not combine with After.')),
        'type': (str | None, Field(None, title='Event Type')),
        'identity_id': (str | None, Field(None, title='Address ID', json_schema_extra={'format': 'uuid'})),
        'after': (str | None, Field(None, title='After', description='ISO timestamp for forward recovery; start at 1970-01-01T00:00:00Z. Do not combine with Cursor.', json_schema_extra={'format': 'date-time'})),
    }),
    'get_thread': ('GET', '/threads/{id}', [], [], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
    }),
    'update_thread': ('PATCH', '/threads/{id}', [], ['status', 'owner_type', 'assignee_id', 'reason'], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        'status': (Literal['open', 'waiting', 'resolved', 'human_review'] | None, Field(None, title='Status')),
        'owner_type': (Literal['human', 'automation', 'agent'] | None, Field(None, title='Owner Type')),
        'assignee_id': (str | None, Field(None, title='Assignee Id', json_schema_extra={'format': 'uuid'})),
        'reason': (str | None, Field(None, title='Reason', max_length=500)),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'list_drafts': ('GET', '/drafts', ['identity_id', 'limit', 'cursor'], [], {}, {
        'identity_id': (str, Field(..., title='Identity Id', json_schema_extra={'format': 'uuid'})),
        'limit': (int | None, Field(None, title='Limit', ge=1, le=200)),
        'cursor': (str | None, Field(None, title='Cursor', description='From a previous page’s `next_cursor`. Opaque — do not parse it.', max_length=500)),
    }),
    'create_draft': ('POST', '/drafts', [], ['identity_id', 'from', 'to', 'cc', 'bcc', 'subject', 'text'], {'from_address': 'from'}, {
        'identity_id': (str, Field(..., title='Identity Id', description='The address this belongs to.', json_schema_extra={'format': 'uuid'})),
        'from_address': (str | None, Field(None, title='From Address', description='An address on a domain you own, and one this key may send from.')),
        'to': (str | None, Field(None, title='To', description='One recipient email address.', json_schema_extra={'format': 'email'})),
        'cc': (str | None, Field(None, title='Cc', description='Copied, and visible to everybody who receives the message.', json_schema_extra={'format': 'email'})),
        'bcc': (str | None, Field(None, title='Bcc', description='Copied, and visible to nobody else.', json_schema_extra={'format': 'email'})),
        'subject': (str | None, Field(None, title='Subject', description='Left off a reply, where the thread already has one.', max_length=2000)),
        'text': (str | None, Field(None, title='Text', description='The plain-text body. Send this even when you send `html` — some clients only read it.', max_length=500000, json_schema_extra={'ui:widget': 'textarea'})),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'get_draft': ('GET', '/drafts/{id}', [], [], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
    }),
    'update_draft': ('PATCH', '/drafts/{id}', [], ['to', 'cc', 'bcc', 'subject', 'text'], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        'to': (str | None, Field(None, title='To', description='One recipient email address.', json_schema_extra={'format': 'email'})),
        'cc': (str | None, Field(None, title='Cc', description='Copied, and visible to everybody who receives the message.', json_schema_extra={'format': 'email'})),
        'bcc': (str | None, Field(None, title='Bcc', description='Copied, and visible to nobody else.', json_schema_extra={'format': 'email'})),
        'subject': (str | None, Field(None, title='Subject', description='Left off a reply, where the thread already has one.', max_length=2000)),
        'text': (str | None, Field(None, title='Text', description='The plain-text body. Send this even when you send `html` — some clients only read it.', max_length=500000, json_schema_extra={'ui:widget': 'textarea'})),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'delete_draft': ('DELETE', '/drafts/{id}', [], [], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'send_draft': ('POST', '/drafts/{id}/send', [], [], {}, {
        'id': (str, Field(..., title='Resource ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')),
        "idempotency_key": (str | None, Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse this value when retrying the same write within 24 hours.")),
    }),
    'list_contacts': ('GET', '/contacts', ['identity_id', 'search', 'limit', 'cursor'], [], {}, {
        'identity_id': (str | None, Field(None, title='Identity Id', description='Only the contacts of this address.', json_schema_extra={'format': 'uuid'})),
        'search': (str | None, Field(None, title='Search', description='Part of a name or an address: `priya`, `@acme.com`.', max_length=200)),
        'limit': (int | None, Field(None, title='Limit', ge=1, le=200)),
        'cursor': (str | None, Field(None, title='Cursor', description='From a previous page’s `next_cursor`. Opaque — do not parse it.', max_length=500)),
    }),
}

CONFIG_MODELS = {}
for name, (_, _, _, _, _, fields) in OPERATIONS.items():
    CONFIG_MODELS[name] = create_model(
        "Pidgeon" + "".join(part.title() for part in name.split("_")) + "Config",
        __base__=_EventsInput if name == "list_events" else _Input,
        operation=(Literal[name], Field(name, json_schema_extra={
            "ui:hidden": True, "x-display-name": name.replace("_", " ").title()})), **fields)

class PidgeonMessageReceivedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_message_received"] = Field("on_message_received", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Message Received"})
    identity_id: str | None = Field(None, title="Address ID", description="Optional: receive mail only for this address.", json_schema_extra={"format": "uuid"})
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

PidgeonConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (PidgeonMessageReceivedConfig,)], Field(discriminator="operation")]

class PidgeonNodeConfig(NodeConfig[PidgeonConfig, PidgeonCredential]):
    pass

class PidgeonNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-pidgeon"
    connection_evidence = ConnectionEvidence(operation="get_account", identity_operation="get_account", noun="Pidgeon account")

    @classmethod
    def get_config_model(cls):
        return PidgeonNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None, idempotency_key=None):
        key = PidgeonCredential.model_validate(credential).api_key
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body, headers=headers)
        if response.is_error:
            try:
                detail = response.json().get("error", {}).get("message")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Pidgeon API error {response.status_code}: {detail or 'request failed'}")
        result = response.json()
        if not isinstance(result, dict) or "error" in result or "data" not in result:
            raise ValueError("Pidgeon returned an unexpected response")
        return result

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        body = {"url": webhook_url, "event_types": ["message.received"]}
        if (config or {}).get("identity_id"):
            body["identity_id"] = config["identity_id"]
        result = await cls._request(credential, "POST", "/webhooks", body=body)
        endpoint = result["data"]
        if not endpoint.get("id") or not endpoint.get("secret"):
            raise ValueError("Pidgeon did not return the webhook ID and one-time signing secret")
        return {"external_webhook_id": endpoint["id"], "signing_secret": endpoint["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if endpoint_id and credential:
            await cls._request(credential, "DELETE", "/webhooks/" + quote(str(endpoint_id), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"identity_id": (config or {}).get("identity_id")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        headers = {k.lower(): v for k, v in headers.items()}
        stamp = headers.get("x-pidgeon-timestamp", "")
        signature = headers.get("x-pidgeon-signature", "")
        secret = (config or {}).get("signing_secret")
        if not isinstance(signature, str) or not signature.isascii():
            return False
        if not secret or not stamp.isascii() or not stamp.isdigit() or len(stamp) > 12:
            return False
        if abs(time.time() - int(stamp)) > 300:
            return False
        expected = "v1=" + hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        if payload.get("type") != "message.received":
            return False
        data = payload.get("data") or {}
        if data.get("from_self"):
            return False
        if data.get("owner_type") == "human":
            return False
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("type") != "message.received":
            return None
        data = output.get("data") or {}
        mid, tid = data.get("message_id"), data.get("thread_id")
        sender = data.get("from_name") or data.get("from") or "A sender"
        subject = data.get("subject") or "New email"
        text = (f"Pidgeon: {sender} <{data.get('from', '')}> sent {subject} to {data.get('identity', '')}.\n"
                f"Received at {output.get('created_at', '')}. Message ID: {mid}; thread ID: {tid}.\n"
                f"The event contains metadata only. Use get_message id={mid} body_format=clean to read it, "
                f"then reply_to_message id={mid} to answer. Read the message's Firewall verdict before acting.")
        return {"text": text, "conversation_key": tid or mid or output.get("id"), "title": subject}

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, PidgeonMessageReceivedConfig):
            return self.no_event_output(op.operation)
        if not self.config.credentials:
            raise ValueError("Connect a Pidgeon API key")
        method, path, query, body_keys, aliases, _ = OPERATIONS[op.operation]
        values = {aliases.get(k, k): v for k, v in op.model_dump(exclude_none=True, exclude={"operation"}).items()}
        if "{id}" in path:
            path = path.replace("{id}", quote(str(values.pop("id")), safe=""))
        params = {k: values[k] for k in query if k in values}
        body = {k: values[k] for k in body_keys if k in values}
        result = await self._request(self.config.credentials.model_dump(), method, path,
            params=params or None, body=body if method in {"POST", "PATCH", "PUT"} else None,
            idempotency_key=values.get("idempotency_key"))
        return {"status": "success", "operation": op.operation, **result}
