"""Evolution Go instance-token operations, pinned to the publisher's Swagger v1.0."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client, normalize_https_origin

DOCS = "https://github.com/evolution-foundation/evolution-go/blob/main/docs/wiki/"


class EvolutionGoInstanceTokenCredential(BaseModel):
    model_config = ConfigDict(title="Evolution Go Instance Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS + "conceitos-core/authentication.md",
            "x-credential-instructions": "Paste the token of an existing, paired Evolution Go WhatsApp instance and its public HTTPS server URL. Use the instance token, not the global admin key. NoClick sends it in the apikey header to that server."})
    credential_type: Literal["evolution_go_instance_token"] = Field("evolution_go_instance_token", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Server URL", description="The public HTTPS origin of your Evolution Go server, without a path.")
    api_token: str = Field(..., title="Instance token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url", mode="before")
    @classmethod
    def origin(cls, value):
        return normalize_https_origin(value, field_name="Evolution Go server URL")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Instance token", key=True)
        if any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the instance token without spaces or a header prefix")
        return value


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key.replace(token, "[redacted]"): _redact(item, token) for key, item in value.items()}
    return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


def text(title, *, required=True, description=None):
    return (str if required else Optional[str], Field(... if required else None, title=title,
        min_length=1, description=description))


def strings(title):
    return (list[str], Field(..., min_length=1, title=title))


# Each entry issues exactly one request to one published operation.
OPERATIONS = {
    "send_text": ("POST", "/send/text", "Send text", {"number": text("Recipient", description="Country-code phone number or WhatsApp JID."), "text": text("Message"), "id": text("Custom message ID", required=False)}),
    "send_media": ("POST", "/send/media", "Send media", {"number": text("Recipient"), "type": (Literal["image", "video", "audio", "document"], Field(..., title="Media type")), "url": text("Media URL"), "caption": text("Caption", required=False), "filename": text("Filename", required=False)}),
    "send_link": ("POST", "/send/link", "Send link preview", {"number": text("Recipient"), "text": text("Message"), "url": text("Link URL"), "title": text("Preview title", required=False), "description": text("Preview description", required=False), "imgUrl": text("Preview image URL", required=False)}),
    "send_location": ("POST", "/send/location", "Send location", {"number": text("Recipient"), "latitude": (float, Field(..., ge=-90, le=90, title="Latitude")), "longitude": (float, Field(..., ge=-180, le=180, title="Longitude")), "name": text("Place name", required=False), "address": text("Address", required=False)}),
    "send_poll": ("POST", "/send/poll", "Send poll", {"number": text("Recipient"), "question": text("Question"), "options": strings("Answer options"), "maxAnswer": (int, Field(1, ge=1, title="Maximum answers"))}),
    "react_to_message": ("POST", "/message/react", "React to message", {"number": text("Chat JID"), "id": text("Message ID"), "reaction": text("Reaction emoji"), "fromMe": (bool, Field(False, title="Sent by this account")), "participant": text("Participant JID", required=False)}),
    "mark_messages_read": ("POST", "/message/markread", "Mark messages read", {"number": text("Chat JID"), "id": strings("Message IDs")}),
    "edit_message": ("POST", "/message/edit", "Edit message", {"chat": text("Chat JID"), "messageId": text("Message ID"), "message": text("New message")}),
    "delete_message": ("POST", "/message/delete", "Delete message for everyone", {"chat": text("Chat JID"), "messageId": text("Message ID")}),
    "list_contacts": ("GET", "/user/contacts", "List contacts", {}),
    "check_users": ("POST", "/user/check", "Check WhatsApp numbers", {"number": strings("Phone numbers"), "formatJid": (bool, Field(True, title="Format phone numbers"))}),
    "get_users": ("POST", "/user/info", "Get users", {"number": strings("Phone numbers"), "formatJid": (bool, Field(True, title="Format phone numbers"))}),
    "get_avatar": ("POST", "/user/avatar", "Get avatar", {"number": text("Phone number or JID"), "preview": (bool, Field(False, title="Preview image"))}),
    "list_groups": ("GET", "/group/list", "List groups", {}),
    "get_group": ("POST", "/group/info", "Get group", {"groupJid": text("Group JID")}),
    "create_group": ("POST", "/group/create", "Create group", {"groupName": text("Group name"), "participants": strings("Participant phone numbers")}),
    "rename_group": ("POST", "/group/name", "Rename group", {"groupJid": text("Group JID"), "name": text("Group name")}),
    "set_group_description": ("POST", "/group/description", "Set group description", {"groupJid": text("Group JID"), "description": text("Group description")}),
    "get_group_invite_link": ("POST", "/group/invitelink", "Get group invite link", {"groupJid": text("Group JID"), "reset": (bool, Field(False, title="Reset invite link", description="Revokes the previous invite link when enabled."))}),
    "archive_chat": ("POST", "/chat/archive", "Archive chat", {"chat": text("Chat JID")}),
    "unarchive_chat": ("POST", "/chat/unarchive", "Unarchive chat", {"chat": text("Chat JID")}),
    "get_instance_status": ("GET", "/instance/status", "Get instance status", {}),
}


def _model(name, spec):
    return create_model("EvolutionGo" + "".join(s.title() for s in name.split("_")) + "Config",
        __module__=__name__, __base__=_Input,
        operation=(Literal[name], Field(name, title=spec[2], json_schema_extra={
            "ui:hidden": True, "x-display-name": spec[2], "x-is-trigger": False})), **spec[3])


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class EvolutionGoOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On WhatsApp event", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On WhatsApp event", "x-is-trigger": True, "x-category": "Triggers"})
    event_type: Literal["MESSAGE", "CALL"] = Field("MESSAGE", title="Event", description="Incoming message or call. Use a dedicated instance: Evolution Go has one webhook URL per instance; registration replaces its event and channel settings. Deliveries are unsigned.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


EvolutionGoOperation = Annotated[Union[tuple(CONFIG_MODELS.values()) + (EvolutionGoOnEventConfig,)], Field(discriminator="operation")]


class EvolutionGoNodeConfig(NodeConfig[EvolutionGoOperation, EvolutionGoInstanceTokenCredential]):
    model_config = ConfigDict(title="Evolution Go Node Configuration")


class EvolutionGoNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-evolution-go"
    webhook_signing_secret_not_issued = True
    connection_evidence = ConnectionEvidence(operation="list_contacts", noun="WhatsApp contacts",
        label_keys=("FullName", "PushName", "FirstName", "Jid"), identity_operation="get_instance_status")

    @classmethod
    def get_config_model(cls):
        return EvolutionGoNodeConfig

    @staticmethod
    async def _request(credential, method, path, body=None):
        credential = EvolutionGoInstanceTokenCredential.model_validate(credential)
        async with guarded_async_client(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, credential.server_url + path,
                headers={"apikey": credential.api_token, "Accept": "application/json"}, json=body)
        if response.status_code >= 300:
            try:
                detail = response.json().get("error", "Request failed")
            except (ValueError, AttributeError):
                detail = "Evolution Go returned a non-JSON response; check the server URL"
            raise ValueError(f"Evolution Go HTTP {response.status_code}: {str(detail).replace(credential.api_token, '[redacted]')}")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Evolution Go returned an unexpected response")
        if data.get("error"):
            raise ValueError(str(data["error"]).replace(credential.api_token, "[redacted]"))
        return _redact(data, credential.api_token)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Evolution Go instance token")
        op = self.config.config
        if isinstance(op, EvolutionGoOnEventConfig):
            payload = (self.node_data or {}).get("config", {}).get("_triggerPayload") or inputs
            return self.resolve_trigger_payload(payload, op.model_dump())
        method, path, _, _ = OPERATIONS[op.operation]
        body = op.model_dump(exclude={"operation"}, exclude_none=True) if method == "POST" else None
        data = await self._request(self.config.credentials.model_dump(), method, path, body)
        return {"status": "success", "operation": op.operation, "data": data.get("data", data)}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = EvolutionGoOnEventConfig.model_validate(config).event_type
        await cls._request(credential, "POST", "/instance/connect", {
            "webhookUrl": webhook_url, "subscribe": [event], "rabbitmqEnable": "disabled",
            "websocketEnable": "disabled", "natsEnable": "disabled"})
        return {"external_webhook_id": webhook_url}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if credential and config.get("external_webhook_id"):
            # Clearing the instance callback retains WhatsApp's paired session.
            await cls._request(credential, "POST", "/instance/connect", {
                "webhookUrl": "", "subscribe": ["MESSAGE"], "rabbitmqEnable": "disabled",
                "websocketEnable": "disabled", "natsEnable": "disabled"})

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "MESSAGE")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # The publisher's webhook sender sets Content-Type only, with no signature.
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = str(payload.get("event", "")).upper()
        return event in ({"MESSAGE"} if config.get("event_type", "MESSAGE") == "MESSAGE" else {"CALLOFFER"})

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        return {"status": "success", "operation": "on_event", "data": {key: value for key, value in payload.items() if key != "instanceToken" and not key.startswith("_")}}

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") != "on_event":
            return None
        payload = output.get("data", {})
        event = str(payload.get("event", "")).upper()
        data = payload.get("data", {})
        instance = payload.get("instanceId", "")
        if event == "MESSAGE":
            info = data.get("Info", {})
            if info.get("IsFromMe"):
                return None
            sender = info.get("Sender", "")
            chat = info.get("Chat", "")
            kind = info.get("Type")
            if kind == "text":
                content = data.get("Message", {}).get("conversation", "")
            elif kind == "media":
                content = f"[{info.get('MediaType', 'media')} message]"
            else:
                content = "[WhatsApp message]"
            return {"text": f"WhatsApp message from {info.get('PushName') or sender} ({sender}) in chat {chat} on Evolution Go instance {instance}: {content} (message ID: {info.get('ID', '')})",
                "conversation_key": f"evolution-go:{instance}:{chat}"}
        if event == "CALLOFFER":
            sender = data.get("CallCreator", "")
            return {"text": f"Incoming WhatsApp call from {sender} on Evolution Go instance {instance} (call ID: {data.get('CallID', '')})",
                "conversation_key": f"evolution-go:{instance}:{sender}"}
        return None
