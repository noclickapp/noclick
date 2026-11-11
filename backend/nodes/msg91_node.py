"""MSG91 messaging and reporting against the provider's published v5 contract.

Each operation makes one request. Message acknowledgements mean queued, never
verified delivery. Actions return one provider page; no implicit pagination/retry. Email and Hello
polls baseline before firing and detect the latest state, not intermediate changes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class Msg91APIKeyCredential(BaseModel):
    model_config = ConfigDict(title="MSG91 API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://control.msg91.com/app/authkey",
            "x-credential-instructions": "Paste your MSG91 authkey from the Authkey page. Allow the messaging and report products you need and your NoClick server's IP if the key restricts IP addresses. NoClick checks your SMS templates on connect; this does not verify delivery or access to other products.",
        })
    credential_type: Literal["msg91_api_key"] = Field("msg91_api_key", json_schema_extra={"ui:hidden": True})
    authkey: str = Field(..., title="Authkey", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("authkey", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="Authkey")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the authkey, without whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class SMSRecipient(Input):
    mobiles: str = Field(..., min_length=1, description="Mobile number including country code")
    VAR1: str | None = None
    VAR2: str | None = None


class EmailAddress(Input):
    name: str | None = None
    email: str = Field(..., min_length=1)


class ReplyAddress(Input):
    email: str = Field(..., min_length=1)


class EmailRecipient(Input):
    to: list[EmailAddress] = Field(..., min_length=1)
    variables: dict[str, str] | None = None


class EmailAttachment(Input):
    filePath: str = Field(..., min_length=1, description="Public URL fetched by MSG91")
    fileName: str = Field(..., min_length=1)


class ContactRule(Input):
    field: str
    operator: str
    type: str
    value: str


class ContactRuleGroup(Input):
    condition: Literal["and", "or"]
    rules: list[ContactRule]


class ContactQuery(Input):
    condition: Literal["and", "or"]
    rules: list[ContactRuleGroup]


class SendSMS(Input):
    """Send sms; one provider request."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., min_length=1)
    recipients: list[SMSRecipient] = Field(..., min_length=1, max_length=100)
    short_url: Literal["0", "1"] | None = None
    short_url_expiry: str | None = None
    realTimeResponse: Literal["0", "1"] | None = None
    schtime: str | None = Field(None, description="Scheduled time YYYY-MM-DD HH:MM:SS")


class CreateSMSTemplate(Input):
    """Create sms template; one provider request."""
    operation: Literal["create_sms_template"] = Field("create_sms_template", json_schema_extra={"ui:hidden": True})
    template: str = Field(..., min_length=1)
    sender_id: str = Field(..., min_length=1)
    template_name: str = Field(..., min_length=1)
    dlt_template_id: str | None = None
    smsType: Literal["NORMAL", "UNICODE"] = "NORMAL"


class ListSMSTemplates(Input):
    """List sms templates; one provider request."""
    operation: Literal["list_sms_templates"] = Field("list_sms_templates", json_schema_extra={"ui:hidden": True})



class GetSMSTemplateVersions(Input):
    """Get sms template versions; one provider request."""
    operation: Literal["get_sms_template_versions"] = Field("get_sms_template_versions", json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., min_length=1)


class SendOTP(Input):
    """Send otp; one provider request."""
    operation: Literal["send_otp"] = Field("send_otp", json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., min_length=1)
    mobile: str = Field(..., min_length=1, description="Mobile number including country code")
    Param1: str | None = None
    Param2: str | None = None
    Param3: str | None = None


class VerifyOTP(Input):
    """Verify otp; one provider request."""
    operation: Literal["verify_otp"] = Field("verify_otp", json_schema_extra={"ui:hidden": True})
    mobile: str = Field(..., min_length=1)
    otp: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "password"})


class ResendOTP(Input):
    """Resend otp; one provider request."""
    operation: Literal["resend_otp"] = Field("resend_otp", json_schema_extra={"ui:hidden": True})
    mobile: str = Field(..., min_length=1)
    retrytype: Literal["text", "voice"] = "text"


class SendEmail(Input):
    """Send email; one provider request."""
    operation: Literal["send_email"] = Field("send_email", json_schema_extra={"ui:hidden": True})
    recipients: list[EmailRecipient] = Field(..., min_length=1, max_length=100)
    from_address: EmailAddress = Field(..., alias="from")
    domain: str = Field(..., min_length=1)
    template_id: str = Field(..., min_length=1)
    reply_to: list[ReplyAddress] | None = None
    attachments: list[EmailAttachment] | None = None


class ListEmailTemplates(Input):
    """List email templates; one provider request."""
    operation: Literal["list_email_templates"] = Field("list_email_templates", json_schema_extra={"ui:hidden": True})
    include: Literal["versions"] | None = Field(None, alias="with")
    per_page: str = Field("25", pattern=r"^[1-9][0-9]{0,2}$")
    page: str = Field("1", pattern=r"^[1-9][0-9]*$")
    status_id: str | None = None
    keyword: str | None = None
    search_in: Literal["name"] | None = None


class GetEmailTemplate(Input):
    """Get email template; one provider request."""
    operation: Literal["get_email_template"] = Field("get_email_template", json_schema_extra={"ui:hidden": True})
    template_version_id: str = Field(..., min_length=1)
    include: Literal["template"] | None = Field(None, alias="with")


class CreateEmailTemplate(Input):
    """Create email template; one provider request."""
    operation: Literal["create_email_template"] = Field("create_email_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1, description="Template HTML, with provider template variables")
    slug: str | None = None


class GetSmsLogs(Input):
    """Get sms logs; one provider request."""
    operation: Literal["get_sms_logs"] = Field("get_sms_logs", json_schema_extra={"ui:hidden": True})
    startDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start date YYYY-MM-DD")
    endDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="End date YYYY-MM-DD; email logs allow at most three days")


class GetSmsAnalytics(Input):
    """Get sms analytics; one provider request."""
    operation: Literal["get_sms_analytics"] = Field("get_sms_analytics", json_schema_extra={"ui:hidden": True})
    startDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start date YYYY-MM-DD")
    endDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="End date YYYY-MM-DD; email logs allow at most three days")


class GetOtpLogs(Input):
    """Get otp logs; one provider request."""
    operation: Literal["get_otp_logs"] = Field("get_otp_logs", json_schema_extra={"ui:hidden": True})
    startDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start date YYYY-MM-DD")
    endDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="End date YYYY-MM-DD; email logs allow at most three days")


class GetOtpAnalytics(Input):
    """Get otp analytics; one provider request."""
    operation: Literal["get_otp_analytics"] = Field("get_otp_analytics", json_schema_extra={"ui:hidden": True})
    startDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start date YYYY-MM-DD")
    endDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="End date YYYY-MM-DD; email logs allow at most three days")


class GetEmailLogs(Input):
    """Get email logs; one provider request."""
    operation: Literal["get_email_logs"] = Field("get_email_logs", json_schema_extra={"ui:hidden": True})
    startDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start date YYYY-MM-DD")
    endDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="End date YYYY-MM-DD; email logs allow at most three days")


class GetEmailAnalytics(Input):
    """Get email analytics; one provider request."""
    operation: Literal["get_email_analytics"] = Field("get_email_analytics", json_schema_extra={"ui:hidden": True})
    startDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start date YYYY-MM-DD")
    endDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="End date YYYY-MM-DD; email logs allow at most three days")


class SearchContacts(Input):
    """Search contacts; one provider request."""
    operation: Literal["search_contacts"] = Field("search_contacts", json_schema_extra={"ui:hidden": True})
    phonebook_id: str = Field(..., min_length=1)
    pageNo: int = Field(1, ge=1)
    itemsPerPage: int = Field(100, ge=1, le=100)
    search: str | None = None
    columns: list[str] | None = None
    query: ContactQuery | None = None
    sortBy: str | None = None
    sortOrder: Literal["asc", "desc"] | None = None


class OnEmailDeliveryUpdate(PollTriggerConfigBase):
    """Watch new email logs and delivery changes in a rolling three-calendar-day window.

    The first poll records a baseline. Intermediate states between polls are not replayed.
    """
    operation: Literal["on_email_delivery_update"] = Field("on_email_delivery_update", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "On Email Delivery Update",
    })
    limit: int = Field(1000, ge=1, le=10000, title="Maximum Emails",
        description="Maximum email logs per poll (up to 10,000). Increase this if your three-day window exceeds the limit; an incomplete response stops the poll.")


class OnNewOrUpdatedTicket(PollTriggerConfigBase):
    """Watch the latest 100 Hello tickets in an inbox for new tickets or latest-message changes.

    The first poll records a baseline; changes outside this recent window are not replayed.
    """
    operation: Literal["on_new_or_updated_ticket"] = Field("on_new_or_updated_ticket", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "On New or Updated Hello Ticket",
    })
    inbox_id: str = Field(..., min_length=1, title="Inbox ID")
    ticket_state: Literal["Open", "close", "snooze", "spam"] = Field("Open", title="Ticket State")


Msg91Config = Annotated[Union[SendSMS, CreateSMSTemplate, ListSMSTemplates, GetSMSTemplateVersions, SendOTP, VerifyOTP, ResendOTP, SendEmail, ListEmailTemplates, GetEmailTemplate, CreateEmailTemplate, GetSmsLogs, GetSmsAnalytics, GetOtpLogs, GetOtpAnalytics, GetEmailLogs, GetEmailAnalytics, SearchContacts, OnEmailDeliveryUpdate, OnNewOrUpdatedTicket], Field(discriminator="operation")]


class Msg91NodeConfig(NodeConfig[Msg91Config, Msg91APIKeyCredential]):
    pass


# Docs URLs identify the exact operation contract; no user-controlled routes.
OPERATIONS = {
    "send_sms": ('POST', '/api/v5/flow', ()),  # https://docs.msg91.com/sms/send-sms
    "create_sms_template": ('POST', '/api/v5/sms/addTemplate', ()),  # https://docs.msg91.com/sms/add-flow
    "list_sms_templates": ('GET', '/api/v5/flows', ()),  # https://docs.msg91.com/sms/list-sms-templates
    "get_sms_template_versions": ('POST', '/api/v5/sms/getTemplateVersions', ()),  # https://docs.msg91.com/sms/get-template-versions
    "send_otp": ('POST', '/api/v5/otp', ('template_id', 'mobile')),  # https://docs.msg91.com/otp/sendotp
    "verify_otp": ('GET', '/api/v5/otp/verify', ('mobile', 'otp')),  # https://docs.msg91.com/otp/verify-otp
    "resend_otp": ('GET', '/api/v5/otp/retry', ('mobile', 'retrytype')),  # https://docs.msg91.com/otp/resend-otp
    "send_email": ('POST', '/api/v5/email/send', ()),  # https://docs.msg91.com/email/send-email
    "list_email_templates": ('GET', '/api/v5/email/templates', ('with', 'per_page', 'page', 'status_id', 'keyword', 'search_in')),  # https://docs.msg91.com/email/list-of-all-email-templates
    "get_email_template": ('GET', '/api/v5/email/template-versions/{template_version_id}', ('with',)),  # https://docs.msg91.com/email/email-template-details
    "create_email_template": ('POST', '/api/v5/email/templates', ()),  # https://docs.msg91.com/email/create-new-template
    "get_sms_logs": ('POST', '/api/v5/report/logs/p/sms', ('startDate', 'endDate')),  # https://docs.msg91.com/sms/sms-logs
    "get_sms_analytics": ('GET', '/api/v5/report/analytics/p/sms', ('startDate', 'endDate')),  # https://docs.msg91.com/sms/sms-analytics
    "get_otp_logs": ('GET', '/api/v5/report/logs/p/otp', ('startDate', 'endDate')),  # https://docs.msg91.com/otp/otp-logs
    "get_otp_analytics": ('GET', '/api/v5/report/analytics/p/otp', ('startDate', 'endDate')),  # https://docs.msg91.com/otp/otp-analytics
    "get_email_logs": ('GET', '/api/v5/report/logs/mail', ('startDate', 'endDate')),  # https://docs.msg91.com/email/email-logs
    "get_email_analytics": ('GET', '/api/v5/report/analytics/p/mail', ('startDate', 'endDate')),  # https://docs.msg91.com/email/email-analytics
    "search_contacts": ('POST', '/api/v5/segmento/api/v1/phonebooks/{phonebook_id}/contacts/filters', ()),  # https://docs.msg91.com/segmento/filtersearch-contact
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items() if k.lower() not in {"authkey", "authorization"}}
    return value


def _failed(data):
    return isinstance(data, dict) and (
        data.get("hasError") is True or data.get("success") is False
        or (isinstance(data.get("type"), str) and data["type"].lower() in {"error", "fail", "failed"})
        or (isinstance(data.get("msg_type"), str) and data["msg_type"].lower() in {"error", "fail", "failed"})
        or (isinstance(data.get("status"), str) and data["status"].lower() in {"error", "fail", "failed"})
        or bool(data.get("error"))
    )


class Msg91Node(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-msg91"
    connection_evidence = ConnectionEvidence(noun="SMS templates", operation="list_sms_templates", label_keys=("flow_name", "flow_id"))

    @classmethod
    def get_config_model(cls):
        return Msg91NodeConfig

    @classmethod
    def resolve_agent_event(cls, output):
        emails = output.get("emails") if isinstance(output, dict) else None
        tickets = output.get("tickets") if isinstance(output, dict) else None
        if isinstance(emails, list):
            if not emails:
                return None
            lines = [f"- {str(row.get('status') or 'Status updated')[:100]}: "
                     f"{str(row.get('senderEmail') or '')[:200]} to {str(row.get('recipientEmail') or '')[:200]}; "
                     f"subject: {str(row.get('subject') or '')[:300]}; "
                     f"request ID: {row.get('requestId')}; updated: {row.get('statusUpdatedAt')}; "
                     f"reason: {str(row.get('failureReason') or row.get('description') or '')[:300]}"
                     for row in emails[:10]]
            return {"text": f"MSG91: {len(emails)} email delivery update(s).\n" + "\n".join(lines),
                    "title": "MSG91 email delivery updates", "conversation_key": None}
        if isinstance(tickets, list):
            if not tickets:
                return None
            lines = []
            for row in tickets[:10]:
                message = (row.get("last_message") or {}).get("message") or {}
                text = (message.get("content") or {}).get("text") or ""
                lines.append(f"- {str(row.get('customer_name') or '')[:200]} "
                             f"({str(row.get('customer_mail') or row.get('customer_number') or '')[:200]}): "
                             f"{str(row.get('subject') or '')[:300]}; {str(text)[:800]} "
                             f"[ticket ID {row.get('ticket_id')}, chat ID {row.get('id')}, inbox ID {row.get('inbox_id')}; "
                             f"message ID {message.get('_id')}; by {row.get('last_message_by')}]")
            return {"text": f"MSG91 Hello: {len(tickets)} new or updated ticket(s).\n" + "\n".join(lines),
                    "title": "MSG91 Hello ticket updates", "conversation_key": None}
        return super().resolve_agent_event(output)

    async def _poll(self, op, key):
        # Official contracts: https://docs.msg91.com/email/email-logs.md and
        # https://docs.msg91.com/hello/mail-ticket-list.openapi.yml
        if isinstance(op, OnEmailDeliveryUpdate):
            today = datetime.now(timezone.utc).date()
            path = "/api/v5/report/logs/mail"
            params = {"startDate": (today - timedelta(days=2)).isoformat(),
                      "endDate": today.isoformat(), "limit": op.limit}
            collection = "data"
        else:
            path = "/api/v5/hello/v2/mail-channel/"
            params = {"inbox_id": op.inbox_id, "type": op.ticket_state,
                      "start_from": 0, "page_size": 100}
            collection = "chat_channels"
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get("https://control.msg91.com" + path,
                    params=params, headers={"authkey": key, "accept": "application/json"})
            if response.status_code >= 300:
                raise ValueError("MSG91 polling request was rejected; check the API key and product permissions")
            data = response.json()
        except (httpx.RequestError, ValueError):
            raise ValueError("MSG91 polling request did not return a readable successful response") from None
        rows = data.get(collection) if isinstance(data, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("MSG91 polling response has an unexpected list shape")
        if isinstance(op, OnEmailDeliveryUpdate):
            total = (data.get("metadata") or {}).get("total")
            if len(rows) > 10000 or (isinstance(total, (int, float)) and total > len(rows)):
                raise ValueError("MSG91 email logs are incomplete; increase Maximum Emails before polling again")
            def identity(row):
                if not row.get("requestId") or not row.get("recipientEmail") or not row.get("statusUpdatedAt"):
                    raise ValueError("MSG91 email log is missing its request, recipient or update time")
                return json.dumps([row["requestId"], row["recipientEmail"], row["statusUpdatedAt"], row.get("status")])
            fresh = await self._filter_unseen(rows, identity)
            result = {"emails": _redact(fresh, key), "new_email_count": len(fresh)}
        else:
            def identity(row):
                last = row.get("last_message") or {}
                if row.get("id") is None or last.get("timetoken") is None:
                    raise ValueError("MSG91 Hello ticket is missing its chat ID or latest-message time")
                return json.dumps([row["id"], last["timetoken"]])
            fresh = await self._filter_unseen(rows, identity)
            result = {"tickets": _redact(fresh, key), "new_ticket_count": len(fresh)}
        await self.emit(result)
        return result

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a MSG91 API key")
        op = self.config.config
        key = self.config.credentials.authkey
        if isinstance(op, (OnEmailDeliveryUpdate, OnNewOrUpdatedTicket)):
            return await self._poll(op, key)
        method, path, query_names = OPERATIONS[op.operation]
        values = op.model_dump(by_alias=True, exclude_none=True, exclude={"operation"})
        for field in ("template_version_id", "phonebook_id"):
            if field in values:
                identifier = values.pop(field)
                if identifier in {".", ".."} or any(c in identifier for c in "/\\?#%"):
                    raise ValueError("Use a single MSG91 resource ID")
                path = path.replace("{" + field + "}", quote(identifier, safe=""))
        params = {name: values.pop(name) for name in query_names if name in values}
        headers = {"authkey": key, "accept": "application/json"}
        if op.operation == "resend_otp":
            headers.pop("authkey")
            params["authkey"] = key
        request = {"params": params, "headers": headers}
        if op.operation == "create_sms_template":
            request["files"] = {name: (None, value) for name, value in values.items()}
        elif values:
            request["json"] = values
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://control.msg91.com" + path, **request)
            if response.status_code >= 300:
                result = {"status": "error", "http_status": response.status_code,
                          "message": response.text[:2000]}
            else:
                # Some report/template contracts specify an empty response or text/plain JSON.
                data = response.json() if response.content else None
                if _failed(data):
                    result = {"status": "error", "http_status": response.status_code, "data": data,
                              "message": data.get("message") or data.get("errors") or data.get("error") or "MSG91 rejected the request"}
                elif op.operation in {"send_sms", "send_otp", "verify_otp", "resend_otp"} and not (isinstance(data, dict) and data.get("type") == "success"):
                    raise ValueError("MSG91 did not confirm the message request")
                elif op.operation == "list_sms_templates" and not (isinstance(data, dict) and isinstance(data.get("data"), list)):
                    raise ValueError("MSG91 SMS template list has an unexpected shape")
                else:
                    result = {"status": "success", "http_status": response.status_code, "data": data,
                              "delivery_verified": False}
                    if op.operation == "list_sms_templates":
                        result["items"] = data["data"]
        except httpx.RequestError:
            # Never retry a possibly accepted send or leak an authkey-bearing retry URL.
            raise ValueError("MSG91 request did not complete; inspect the provider before retrying a send") from None
        except (ValueError, TypeError):
            raise ValueError("MSG91 response could not be read; inspect the provider before retrying a send") from None
        result = _redact(result, key)
        await self.emit(result)
        return result
