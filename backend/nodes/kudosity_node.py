"""Kudosity Messaging API, pinned public contract version 20250101.

Each operation makes one request. Lists return one provider page, including its
pagination metadata; sends acknowledge API acceptance, not handset delivery.
"""
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.transmitmessage.com"


class KudosityAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Kudosity API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.kudosity.com/reference/authentication",
        "x-credential-instructions": "In your Kudosity account, open Settings and scroll to API Settings. Copy your Messaging API key and paste it here. NoClick sends it in x-api-key to api.transmitmessage.com. Legacy TransmitSMS API keys and secrets use a different API."})
    credential_type: Literal["kudosity_api_key"] = Field("kudosity_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessagePage(Input):
    limit: int = Field(25, ge=1, le=100, description="One page only. Use meta.pagination.next_cursor from the previous response.")
    cursor: Optional[str] = None
    direction: Literal["next", "prev"] = "next"
    date_range: Literal["last_week", "last_thirty", "last_month", "all"] = "all"


class ListWhatsappMessages(MessagePage):
    operation: Literal["list_whatsapp_messages"] = "list_whatsapp_messages"
    campaign_id: Optional[UUID] = None


class ListRcsMessages(MessagePage):
    operation: Literal["list_rcs_messages"] = "list_rcs_messages"


class ListWhatsappTemplates(Input):
    operation: Literal["list_whatsapp_templates"] = "list_whatsapp_templates"
    page: int = Field(1, ge=1)
    limit: int = Field(25, ge=1, le=100)
    status: Optional[Literal["PENDING", "APPROVED", "REJECTED", "PAUSED", "DISABLED", "FLAGGED", "LOCKED", "ARCHIVED", "IN_APPEAL", "LIMIT_EXCEEDED"]] = None
    category: Optional[Literal["MARKETING", "UTILITY", "AUTHENTICATION"]] = None
    language: Optional[str] = None
    name: Optional[str] = None


class Selected(Input):
    id: UUID = Field(..., title="Resource ID", description="Copy the message or webhook UUID from a previous operation.")


class GetWhatsappMessage(Selected):
    operation: Literal["get_whatsapp_message"] = "get_whatsapp_message"


class GetRcsMessage(Selected):
    operation: Literal["get_rcs_message"] = "get_rcs_message"


class GetSMS(Selected):
    operation: Literal["get_sms"] = "get_sms"


class GetMMS(Selected):
    operation: Literal["get_mms"] = "get_mms"


class GetWebhook(Selected):
    operation: Literal["get_webhook"] = "get_webhook"


class DeleteWebhook(Selected):
    operation: Literal["delete_webhook"] = "delete_webhook"


class ListWebhooks(Input):
    operation: Literal["list_webhooks"] = "list_webhooks"


class Outbound(Input):
    sender: str = Field(..., min_length=1, description="Sender registered on your account; RCS uses an agent ID.")
    recipient: str = Field(..., min_length=1, description="Opted-in recipient in international phone format.")
    message_ref: Optional[str] = Field(None, max_length=500)


class SendSMS(Outbound):
    operation: Literal["send_sms"] = "send_sms"
    message: str = Field(..., min_length=1, description="Sending may incur provider charges. API acceptance does not prove delivery.")
    track_links: Optional[bool] = None


class SendMMS(Outbound):
    operation: Literal["send_mms"] = "send_mms"
    content_urls: list[str] = Field(..., min_length=1, max_length=1, description="One public media URL up to 400 KB. MMS currently supports Australian recipients only.")
    subject: Optional[str] = Field(None, max_length=20, pattern=r"^[\x00-\x7F]*$")
    message: Optional[str] = Field(None, max_length=1000)
    track_links: Optional[bool] = None


class SendWhatsappMessage(Outbound):
    operation: Literal["send_whatsapp_message"] = "send_whatsapp_message"
    template_name: str = Field(..., min_length=1, description="An approved positional text template registered on this account.")
    parameters: list[str] = Field(default_factory=list, description="Ordered text values for the template's body variables.")


class SendRcsMessage(Outbound):
    operation: Literal["send_rcs_message"] = "send_rcs_message"
    message: str = Field(..., min_length=1, max_length=3072, description="RCS text message; sending may incur provider charges.")


class CheckRcsCapabilities(Input):
    operation: Literal["check_rcs_capabilities"] = "check_rcs_capabilities"
    sender: str = Field(..., min_length=1)
    phone_numbers: list[str] = Field(..., min_length=1, max_length=100, description="E.164 numbers without a leading plus.")


class WebhookFilter(Input):
    event_type: Optional[list[Literal["LINK_HIT", "OPT_OUT", "MMS_STATUS", "SMS_INBOUND", "SMS_STATUS", "MMS_INBOUND", "WHATSAPP_STATUS", "WHATSAPP_INBOUND", "RCS_STATUS", "RCS_INBOUND", "PAYMENT_SUCCEEDED", "PAYMENT_FAILED", "SENDER_REGISTRATION_STATUS", "SENDER_COMPLIANCE_STATUS"]]] = None
    sender: Optional[list[str]] = None
    status: Optional[list[str]] = None
    message_ref: Optional[list[str]] = None
    campaign_id: Optional[list[str]] = None


class WebhookBody(Input):
    name: str = Field(..., min_length=2, max_length=100)
    url: str = Field(..., pattern=r"^https://[^\s]+$", description="Public HTTPS destination accepting JSON POST events.")
    rate_limit: Optional[int] = Field(None, ge=0, le=10000)
    filter: Optional[WebhookFilter] = None


class CreateWebhook(WebhookBody):
    operation: Literal["create_webhook"] = "create_webhook"


class UpdateWebhook(WebhookBody, Selected):
    operation: Literal["update_webhook"] = "update_webhook"


KudosityConfig = Annotated[Union[ListWhatsappMessages, GetWhatsappMessage, SendWhatsappMessage,
    ListWhatsappTemplates, ListRcsMessages, GetRcsMessage, SendRcsMessage,
    CheckRcsCapabilities, GetSMS, SendSMS, GetMMS, SendMMS,
    ListWebhooks, GetWebhook, CreateWebhook, UpdateWebhook, DeleteWebhook], Field(discriminator="operation")]


class KudosityFullConfig(NodeConfig[KudosityConfig, KudosityAPIKeyCredential]):
    pass


ROUTES = {
    "list_whatsapp_messages": ("GET", "/v2/whatsapp/messages"),
    "get_whatsapp_message": ("GET", "/v2/whatsapp/messages/{id}"),
    "send_whatsapp_message": ("POST", "/v2/whatsapp/messages"),
    "list_whatsapp_templates": ("GET", "/v2/whatsapp/templates"),
    "list_rcs_messages": ("GET", "/v2/rcs/messages"),
    "get_rcs_message": ("GET", "/v2/rcs/messages/{id}"),
    "send_rcs_message": ("POST", "/v2/rcs/messages"),
    "check_rcs_capabilities": ("POST", "/v2/rcs/capabilities"),
    "get_sms": ("GET", "/v2/sms/{id}"),
    "send_sms": ("POST", "/v2/sms"),
    "get_mms": ("GET", "/v2/mms/{id}"),
    "send_mms": ("POST", "/v2/mms"),
    "list_webhooks": ("GET", "/v2/webhook"),
    "get_webhook": ("GET", "/v2/webhook/{id}"),
    "create_webhook": ("POST", "/v2/webhook"),
    "update_webhook": ("PUT", "/v2/webhook/{id}"),
    "delete_webhook": ("DELETE", "/v2/webhook/{id}"),
}


class KudosityNode(WorkflowNode):
    integration_type = "automation-kudosity"
    connection_evidence = ConnectionEvidence(noun="webhooks", operation="list_webhooks")

    @classmethod
    def get_config_model(cls):
        return KudosityFullConfig

    async def execute(self, inputs):
        cfg = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Kudosity API key")
        method, route = ROUTES[cfg.operation]
        values = cfg.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in route:
            route = route.replace("{id}", values.pop("id"))
        if cfg.operation == "send_whatsapp_message":
            values["content_type"] = "template"
            values["content"] = {"template": {"name": values.pop("template_name"), "parameters": values.pop("parameters")}}
        elif cfg.operation == "send_rcs_message":
            values["content_type"] = "text"
            values["content"] = {"text": {"message": values.pop("message")}}
        kwargs = {"params": values} if method == "GET" else ({"json": values} if method != "DELETE" else {})
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + route, headers={"x-api-key": credential.api_key, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve documented rejection details without reflecting the key.
            detail = ""
            try:
                body = response.json()
                error = body.get("error", {}) if isinstance(body, dict) else {}
                detail = error.get("detail", "") if isinstance(error, dict) else str(error)
                if not detail and isinstance(body, dict):
                    detail = body.get("status", "")
            except (ValueError, TypeError):
                pass
            detail = str(detail).replace(credential.api_key, "[redacted]")[:1000]
            raise ValueError(f"Kudosity HTTP {response.status_code}: {detail or 'request rejected'}")
        if len(response.content) > 5_000_000:
            raise ValueError("Kudosity response exceeds 5 MB; request a smaller page")
        if "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Expected JSON from Kudosity")
        body = response.json()
        if not isinstance(body, dict) or "error" in body:
            raise ValueError("Kudosity returned an unexpected response")
        result = {"status": "success", "data": body, "http_status": response.status_code}
        await self.emit(result)
        return result
