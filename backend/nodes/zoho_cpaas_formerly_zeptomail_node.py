"""Zoho CPaaS 1.1 channel APIs, from the provider's published OpenAPI 1.1.0.

Contract: https://www.zoho.com/sites/zweb/json/api/cpaas/oas.json

Management APIs require OAuth; this node uses pasted agent/channel API keys.
No webhook registration API is published, so activity uses scheduled polling.
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://cpaas.zoho.com/v1.1"
FAMILY = "zoho_cpaas_api_key"


class ZohoCPaaSAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zoho Agent API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.zoho.com/cpaas/help/api/api-authentication.html",
        "x-credential-instructions": "In your Agent, open SMTP/API > API Setup and copy the channel's API key. Each channel uses a separate key; attach the key for the action's channel. Paste only the key. SMS requires an India data-centre account. Email keys only allow sending, so their read-only connection verification is unavailable. Management APIs require OAuth and are not included."})
    credential_type: Literal["zoho_cpaas_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    channel: Literal["email", "sms", "whatsapp", "voice"] = Field("email", title="Key channel", description="Channel this key belongs to. Verification reads that channel's logs; email keys have no read probe.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without the Authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


def _json(value, kind, label):
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError(f"{label} must be valid JSON") from None
    if not isinstance(parsed, kind):
        raise ValueError(f"{label} must be a JSON {kind.__name__}")
    return parsed


class _Template(_Input):
    template_key: Optional[str] = Field(None, min_length=1, description="Template key; use this or the alias.")
    template_alias: Optional[str] = Field(None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def template(self):
        if sum(bool(v) for v in (self.template_key, self.template_alias, getattr(self, "message_content", None))) != 1:
            raise ValueError("Provide exactly one template key, template alias, or voice message content")
        return self


class _Email(_Input):
    from_address: str = Field(..., min_length=1, title="From email address")
    from_name: Optional[str] = Field(None, title="From display name")
    to_json: str = Field(..., title="Recipients JSON", description='Array of {"email_address":{"address":"user@example.com","name":"User"}}. Batch template recipients may also have merge_info.', json_schema_extra={"ui:widget": "code_editor"})
    cc_json: Optional[str] = Field(None, title="CC recipients JSON")
    bcc_json: Optional[str] = Field(None, title="BCC recipients JSON")
    reply_to_json: Optional[str] = Field(None, title="Reply-to JSON", description="Array of address/name objects.")
    bounce_address: Optional[str] = None
    track_opens: Optional[bool] = None
    track_clicks: Optional[bool] = None

    @field_validator("to_json", "cc_json", "bcc_json")
    @classmethod
    def recipients(cls, value):
        if value is not None:
            rows = _json(value, list, "Recipients")
            if not rows or not all(isinstance(r, dict) and isinstance(r.get("email_address"), dict) and isinstance(r["email_address"].get("address"), str) and r["email_address"]["address"].strip() for r in rows):
                raise ValueError("Each recipient needs email_address.address")
        return value

    @field_validator("reply_to_json")
    @classmethod
    def replies(cls, value):
        if value is not None and not all(isinstance(r, dict) and isinstance(r.get("address"), str) for r in _json(value, list, "Reply-to")):
            raise ValueError("Each reply-to needs an address")
        return value


class _EmailContent(_Email):
    subject: str = Field(..., min_length=1)
    htmlbody: Optional[str] = Field(None, title="HTML body")
    textbody: Optional[str] = Field(None, title="Text body")
    client_reference: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def content(self):
        if not self.htmlbody and not self.textbody:
            raise ValueError("Provide an HTML or text body")
        return self


class SendEmail(_EmailContent):
    operation: Literal["send_email"] = Field("send_email", title="Send Email")


class SendBatchEmails(_EmailContent):
    operation: Literal["send_batch_emails"] = Field("send_batch_emails", title="Send Batch Emails")


class _EmailTemplate(_Email, _Template):
    pass


class SendEmailUsingTemplate(_EmailTemplate):
    operation: Literal["send_email_using_template"] = Field("send_email_using_template", title="Send Email Using Template")
    merge_info_json: Optional[str] = Field(None, title="Merge variables JSON")
    client_reference: Optional[str] = Field(None, max_length=100)

    @field_validator("merge_info_json")
    @classmethod
    def merge(cls, value):
        if value is not None and not all(isinstance(v, str) for v in _json(value, dict, "Merge variables").values()):
            raise ValueError("Email merge values must be strings")
        return value


class SendBatchEmailsUsingTemplate(_EmailTemplate):
    operation: Literal["send_batch_emails_using_template"] = Field("send_batch_emails_using_template", title="Send Batch Emails Using Template")


class _Message(_Template):
    merge_info_json: Optional[str] = Field(None, title="Merge variables JSON", json_schema_extra={"ui:widget": "code_editor"})
    client_reference: Optional[str] = Field(None, max_length=100)

    @field_validator("merge_info_json")
    @classmethod
    def merge(cls, value):
        if value is not None:
            _json(value, dict, "Merge variables")
        return value

    @field_validator("template_key")
    @classmethod
    def template_uuid(cls, value):
        if value is not None:
            UUID(value)
        return value


class SendSMS(_Message):
    operation: Literal["send_sms"] = Field("send_sms", title="Send SMS")
    sender_key: str = Field(..., min_length=1, max_length=200)
    recipient: str = Field(..., min_length=8, max_length=20, description="One phone number including country code.")


class SendWhatsApp(_Message):
    operation: Literal["send_whatsapp_message"] = Field("send_whatsapp_message", title="Send WhatsApp Message")
    from_number: str = Field(..., min_length=8, max_length=20)
    to_number: str = Field(..., min_length=8, max_length=20)
    agent_id: Optional[str] = None


class SendVoice(_Message):
    operation: Literal["send_voice_call"] = Field("send_voice_call", title="Place Voice Call")
    from_number: str = Field(..., min_length=8, max_length=20)
    to_number: str = Field(..., min_length=8, max_length=20)
    message_content: Optional[str] = Field(None, min_length=1, max_length=5000, description="Ad-hoc text-to-speech instead of a template.")
    language: Optional[str] = Field(None, min_length=2, max_length=10, description="Provider default: en.")
    voice_gender: Literal["male", "female"] = "female"
    agent_key: Optional[str] = Field(None, max_length=300)


class _Dates(BaseModel):
    date_from: Optional[str] = Field(None, description="Start, ISO 8601 with UTC offset.")
    date_to: Optional[str] = Field(None, description="End, ISO 8601 with UTC offset.")

    @field_validator("date_from", "date_to")
    @classmethod
    def date(cls, value):
        if value is not None and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Include the UTC offset")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.date_from and self.date_to and datetime.fromisoformat(self.date_from.replace("Z", "+00:00")) > datetime.fromisoformat(self.date_to.replace("Z", "+00:00")):
            raise ValueError("date_to must be after date_from")
        return self


class _Logs(_Input, _Dates):
    offset: int = Field(0, ge=0)
    limit: int = Field(10, ge=1, le=100)
    status: Optional[str] = None
    client_reference: Optional[str] = Field(None, max_length=100)
    template_key: Optional[str] = Field(None, max_length=50)
    request_id: Optional[str] = Field(None, max_length=200)


class GetSMSLogs(_Logs):
    operation: Literal["get_sms_logs"] = Field("get_sms_logs", title="Get SMS Logs")
    recipient: Optional[str] = Field(None, max_length=30)
    sender_name: Optional[str] = Field(None, max_length=30)


class GetWhatsAppLogs(_Logs):
    operation: Literal["get_whatsapp_logs"] = Field("get_whatsapp_logs", title="Get WhatsApp Logs")
    recipient: Optional[str] = Field(None, max_length=30)


class GetVoiceLogs(_Logs):
    operation: Literal["get_voice_logs"] = Field("get_voice_logs", title="Get Voice Call Logs")
    status: Optional[Literal["INITIATED", "ANSWERED", "CALL_REJECTED", "CALL_UNANSWERED", "CALL_FAILED", "PROCESS_FAILED", "UNKNOWN"]] = None
    from_number: Optional[str] = Field(None, min_length=8, max_length=20)
    to_number: Optional[str] = Field(None, min_length=8, max_length=20)
    template_alias: Optional[str] = Field(None, max_length=50)
    message_id: Optional[UUID] = None


class _Detail(_Input):
    message_id: UUID = Field(..., title="Message or call ID", json_schema_extra={"x-dynamic-options": {
        "field_name": "activity_id", "allow_custom": True, "searchable": False,
        "placeholder": "Choose recent activity", "custom_placeholder": "Paste message ID"}})


class GetSMSDetails(_Detail):
    operation: Literal["get_sms_message_details"] = Field("get_sms_message_details", title="Get SMS Message Details")


class GetWhatsAppDetails(_Detail):
    operation: Literal["get_whatsapp_message_details"] = Field("get_whatsapp_message_details", title="Get WhatsApp Message Details")


class GetVoiceDetails(_Detail):
    operation: Literal["get_voice_call_details"] = Field("get_voice_call_details", title="Get Voice Call Details")


class _Poll(PollTriggerConfigBase, _Dates):
    client_reference: Optional[str] = Field(None, max_length=100, description="Watch only this reference. Narrow the date range or reference for scopes exceeding 2,000 entries.")


class OnSMSActivity(_Poll):
    operation: Literal["on_sms_activity"] = Field("on_sms_activity", title="On New or Changed SMS Activity", json_schema_extra={"x-is-trigger": True})


class OnWhatsAppActivity(_Poll):
    operation: Literal["on_whatsapp_activity"] = Field("on_whatsapp_activity", title="On New or Changed WhatsApp Activity", json_schema_extra={"x-is-trigger": True})


class OnVoiceActivity(_Poll):
    operation: Literal["on_voice_activity"] = Field("on_voice_activity", title="On New or Changed Voice Activity", json_schema_extra={"x-is-trigger": True})


Config = Annotated[Union[SendEmail, SendBatchEmails, SendEmailUsingTemplate, SendBatchEmailsUsingTemplate,
    SendSMS, SendWhatsApp, SendVoice, GetSMSLogs, GetWhatsAppLogs, GetVoiceLogs,
    GetSMSDetails, GetWhatsAppDetails, GetVoiceDetails, OnSMSActivity, OnWhatsAppActivity, OnVoiceActivity], Field(discriminator="operation")]


class ZohoCPaaSConfig(NodeConfig[Config, ZohoCPaaSAPIKeyCredential]):
    pass


ROUTES = {
    "send_email": ("POST", "/email"),
    "send_batch_emails": ("POST", "/email/batch"),
    "send_email_using_template": ("POST", "/email/template"),
    "send_batch_emails_using_template": ("POST", "/email/template/batch"),
    "send_sms": ("POST", "/sms"),
    "send_whatsapp_message": ("POST", "/whatsapp"),
    "send_voice_call": ("POST", "/voice"),
    "get_sms_logs": ("GET", "/sms/logs"),
    "get_whatsapp_logs": ("GET", "/whatsapp/logs"),
    "get_voice_logs": ("GET", "/voice/logs"),
    "get_sms_message_details": ("GET", "/sms/logs/{message_id}"),
    "get_whatsapp_message_details": ("GET", "/whatsapp/logs/{message_id}"),
    "get_voice_call_details": ("GET", "/voice/logs/{message_id}"),
    "on_sms_activity": ("GET", "/sms/logs"),
    "on_whatsapp_activity": ("GET", "/whatsapp/logs"),
    "on_voice_activity": ("GET", "/voice/logs"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class ZohoCPaaSNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-zoho-cpaas-formerly-zeptomail"
    credential_provider_labels = {"zoho_cpaas_formerly_zeptomail": "Zoho CPaaS"}
    connection_evidence = ConnectionEvidence(field="activity_id", noun="recent communications")

    @classmethod
    def get_config_model(cls):
        return ZohoCPaaSConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"Authorization": "Zoho-enczapikey " + credential.api_key, "Accept": "application/json"})
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Zoho CPaaS returned HTTP {response.status_code} with a non-JSON response") from None
        if response.is_error or (isinstance(payload, dict) and ("error" in payload or payload.get("status") in {"error", "failure", "failed"})):
            raise ValueError(f"Zoho CPaaS HTTP {response.status_code}: {json.dumps(_redact(payload, credential.api_key))}")
        if not isinstance(payload, dict):
            raise ValueError("Zoho CPaaS returned an unexpected response")
        return payload

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Zoho CPaaS API key")
        op = self.config.config
        method, path = ROUTES[op.operation]
        channel = path.split("/")[1]
        if isinstance(op, _Poll):
            params = op.model_dump(exclude_none=True, include={"date_from", "date_to", "client_reference"})
            rows = []
            for page in range(20):
                payload = await self._request(credential, method, path, params={**params, "offset": page * 100, "limit": 100})
                batch = payload.get("data")
                if not isinstance(batch, list) or not all(isinstance(row, dict) and row.get("message_id") and row.get("status") for row in batch):
                    raise ValueError("Zoho CPaaS activity needs a data array with message_id and status")
                rows.extend(batch)
                if len(batch) < 100:
                    break
            else:
                raise ValueError("More than 2,000 communications in this poll scope; narrow date_from or client_reference")
            fresh = await self._filter_unseen(rows, lambda row: str(row["message_id"]) + ":" + str(row["status"]))
            return {"operation": op.operation, "channel": channel, "events": fresh, "event_count": len(fresh)}
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{message_id}" in path:
            path = path.replace("{message_id}", quote(values.pop("message_id"), safe=""))
        for name in list(values):
            if name.endswith("_json"):
                values[name[:-5]] = json.loads(values.pop(name))
        if isinstance(op, _Email):
            values["from"] = {"address": values.pop("from_address")}
            if "from_name" in values:
                values["from"]["name"] = values.pop("from_name")
        if isinstance(op, SendSMS):
            values["to"] = [{"mobile_no": values.pop("recipient")}]
        for source, target in (("from_number", "from"), ("to_number", "to")):
            if source in values:
                values[target] = values.pop(source)
        payload = await self._request(credential, method, path, params=values if method == "GET" else None,
            body=values if method == "POST" else None)
        return {"operation": op.operation, **payload}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("event_count")) if config.get("operation", "").startswith("on_") else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or not isinstance(output.get("events"), list):
            return None
        rows = output["events"]
        if not rows:
            return None
        channel = output.get("channel", "communication")
        lines = []
        for row in rows[:20]:
            sender = row.get("sender_name", "") if channel == "sms" else row.get("from", "")
            lines.append(f"- {channel} from {sender} to {row.get('to', 'unknown recipient')}: {row.get('status', 'unknown')} (requested {row.get('request_time', '')}); message/call ID {row.get('message_id')}; request ID {row.get('request_id', '')}; client reference {row.get('client_reference', '')}")
        return {"text": f"Zoho CPaaS: {len(rows)} new or changed {channel} communication(s).\n" + "\n".join(lines), "conversation_key": None}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "activity_id":
            return {"options": []}
        credential = ZohoCPaaSAPIKeyCredential.model_validate(credential_data)
        context = context or {}
        config = context.get("config", context)
        path = ROUTES.get(config.get("operation", ""), (None, None))[1]
        channel = path.split("/")[1] if path else credential.channel
        if channel == "email":
            raise ValueError("Email API keys only allow sending; Zoho CPaaS provides no read-only verification endpoint for this key")
        offset = int(page_token or 0)
        if offset < 0:
            raise ValueError("Invalid page offset")
        payload = await cls._request(credential, "GET", f"/{channel}/logs", params={"offset": offset, "limit": 100})
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ValueError("Zoho CPaaS returned no activity data array")
        options = [{"value": row["message_id"], "label": f"{row.get('to', '')} — {row.get('status', '')} ({row['message_id']})"} for row in rows if isinstance(row, dict) and row.get("message_id")]
        if search:
            options = [row for row in options if search.casefold() in row["label"].casefold()]
        return {"options": options, "next_page_token": str(offset + 100) if len(rows) == 100 else None}
