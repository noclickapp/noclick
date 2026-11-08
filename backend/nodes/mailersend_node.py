"""MailerSend v1 email automation using a pasted, permission-limited API token.

Each operation performs one documented API call. Lists return the provider's
first-page envelope (including pagination metadata); no links are followed.
Email acceptance is asynchronous and never claims delivery.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.mailersend.com/v1"


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Paste a single MailerSend resource ID")
    return value


ResourceID = Annotated[str, BeforeValidator(resource_id)]


class MailerSendAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="MailerSend API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.mailersend.com/api-tokens",
            "x-credential-instructions": "Paste a MailerSend API token. Grant domains read access to verify the connection, plus read or write access for the operations you use. Tokens are scoped to sending domains; sending requires a verified sender. NoClick sends your token only to api.mailersend.com.",
        })
    credential_type: Literal["mailersend_api_token"] = Field("mailersend_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=8192, repr=False, title="API Token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or re.search(r"[\s\x00-\x1f\x7f:]", value):
            raise ValueError("Paste only the token without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EmailAddress(Input):
    email: str = Field(..., min_length=3, max_length=254)
    name: str | None = Field(None, max_length=256)

    @field_validator("email")
    @classmethod
    def email_value(cls, value):
        if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
            raise ValueError("Enter an email address")
        return value


class EmailMessage(Input):
    sender: EmailAddress = Field(..., alias="from", title="From", description="Address on your verified sending domain.")
    to: list[EmailAddress] = Field(..., min_length=1, max_length=50)
    subject: str = Field(..., min_length=1, max_length=998)
    text: str = Field(..., min_length=1, max_length=1000000)
    html: str | None = Field(None, max_length=1000000)


class Empty(Input):
    pass


class DomainID(Input):
    domain_id: ResourceID


class MessageID(Input):
    message_id: ResourceID


class RecipientID(Input):
    recipient_id: ResourceID


class BulkID(Input):
    bulk_email_id: ResourceID


class SendEmail(Input):
    message: EmailMessage = Field(..., description="Sender, recipients, subject, text and optional HTML. A successful submission means queued, not delivered.")


class BulkEmail(Input):
    messages: list[EmailMessage] = Field(..., min_length=1, max_length=500, description="Up to 500 separate email requests, submitted asynchronously.")


class Suppress(DomainID):
    recipients: list[str] = Field(..., min_length=1, max_length=100, description="Email addresses to suppress for this sending domain.")

    @field_validator("recipients")
    @classmethod
    def emails(cls, values):
        return [EmailAddress(email=v).email for v in values]


class MailerSendSendEmailConfig(SendEmail):
    operation: Literal["send_email"] = Field("send_email", json_schema_extra={"ui:hidden": True})


class MailerSendSendBulkEmailConfig(BulkEmail):
    operation: Literal["send_bulk_email"] = Field("send_bulk_email", json_schema_extra={"ui:hidden": True})


class MailerSendGetBulkEmailStatusConfig(BulkID):
    operation: Literal["get_bulk_email_status"] = Field("get_bulk_email_status", json_schema_extra={"ui:hidden": True})


class MailerSendListDomainsConfig(Empty):
    operation: Literal["list_domains"] = Field("list_domains", json_schema_extra={"ui:hidden": True})


class MailerSendGetDomainConfig(DomainID):
    operation: Literal["get_domain"] = Field("get_domain", json_schema_extra={"ui:hidden": True})


class MailerSendGetDomainDnsRecordsConfig(DomainID):
    operation: Literal["get_domain_dns_records"] = Field("get_domain_dns_records", json_schema_extra={"ui:hidden": True})


class MailerSendListTemplatesConfig(Empty):
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})


class MailerSendListMessagesConfig(Empty):
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})


class MailerSendGetMessageConfig(MessageID):
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})


class MailerSendListScheduledMessagesConfig(Empty):
    operation: Literal["list_scheduled_messages"] = Field("list_scheduled_messages", json_schema_extra={"ui:hidden": True})


class MailerSendGetScheduledMessageConfig(MessageID):
    operation: Literal["get_scheduled_message"] = Field("get_scheduled_message", json_schema_extra={"ui:hidden": True})


class MailerSendDeleteScheduledMessageConfig(MessageID):
    operation: Literal["delete_scheduled_message"] = Field("delete_scheduled_message", json_schema_extra={"ui:hidden": True})


class MailerSendListRecipientsConfig(Empty):
    operation: Literal["list_recipients"] = Field("list_recipients", json_schema_extra={"ui:hidden": True})


class MailerSendGetRecipientConfig(RecipientID):
    operation: Literal["get_recipient"] = Field("get_recipient", json_schema_extra={"ui:hidden": True})


class MailerSendDeleteRecipientConfig(RecipientID):
    operation: Literal["delete_recipient"] = Field("delete_recipient", json_schema_extra={"ui:hidden": True})


class MailerSendListBlocklistConfig(Empty):
    operation: Literal["list_blocklist"] = Field("list_blocklist", json_schema_extra={"ui:hidden": True})


class MailerSendAddBlocklistRecipientsConfig(Suppress):
    operation: Literal["add_blocklist_recipients"] = Field("add_blocklist_recipients", json_schema_extra={"ui:hidden": True})


class MailerSendListHardBouncesConfig(Empty):
    operation: Literal["list_hard_bounces"] = Field("list_hard_bounces", json_schema_extra={"ui:hidden": True})


class MailerSendListUnsubscribesConfig(Empty):
    operation: Literal["list_unsubscribes"] = Field("list_unsubscribes", json_schema_extra={"ui:hidden": True})


class MailerSendAddUnsubscribeRecipientsConfig(Suppress):
    operation: Literal["add_unsubscribe_recipients"] = Field("add_unsubscribe_recipients", json_schema_extra={"ui:hidden": True})


MailerSendConfig = Annotated[Union[
    MailerSendSendEmailConfig,
    MailerSendSendBulkEmailConfig,
    MailerSendGetBulkEmailStatusConfig,
    MailerSendListDomainsConfig,
    MailerSendGetDomainConfig,
    MailerSendGetDomainDnsRecordsConfig,
    MailerSendListTemplatesConfig,
    MailerSendListMessagesConfig,
    MailerSendGetMessageConfig,
    MailerSendListScheduledMessagesConfig,
    MailerSendGetScheduledMessageConfig,
    MailerSendDeleteScheduledMessageConfig,
    MailerSendListRecipientsConfig,
    MailerSendGetRecipientConfig,
    MailerSendDeleteRecipientConfig,
    MailerSendListBlocklistConfig,
    MailerSendAddBlocklistRecipientsConfig,
    MailerSendListHardBouncesConfig,
    MailerSendListUnsubscribesConfig,
    MailerSendAddUnsubscribeRecipientsConfig
], Field(discriminator="operation")]


class MailerSendFullConfig(NodeConfig[MailerSendConfig, MailerSendAPITokenCredential]):
    pass


ROUTES = {'send_email': ('POST', '/email'), 'send_bulk_email': ('POST', '/bulk-email'), 'get_bulk_email_status': ('GET', '/bulk-email/{bulk_email_id}'), 'list_domains': ('GET', '/domains'), 'get_domain': ('GET', '/domains/{domain_id}'), 'get_domain_dns_records': ('GET', '/domains/{domain_id}/dns-records'), 'list_templates': ('GET', '/templates'), 'list_messages': ('GET', '/messages'), 'get_message': ('GET', '/messages/{message_id}'), 'list_scheduled_messages': ('GET', '/message-schedules'), 'get_scheduled_message': ('GET', '/message-schedules/{message_id}'), 'delete_scheduled_message': ('DELETE', '/message-schedules/{message_id}'), 'list_recipients': ('GET', '/recipients'), 'get_recipient': ('GET', '/recipients/{recipient_id}'), 'delete_recipient': ('DELETE', '/recipients/{recipient_id}'), 'list_blocklist': ('GET', '/suppressions/blocklist'), 'add_blocklist_recipients': ('POST', '/suppressions/blocklist'), 'list_hard_bounces': ('GET', '/suppressions/hard-bounces'), 'list_unsubscribes': ('GET', '/suppressions/unsubscribes'), 'add_unsubscribe_recipients': ('POST', '/suppressions/unsubscribes')}


class MailerSendNode(WorkflowNode):
    integration_type = "automation-mailersend"
    connection_evidence = ConnectionEvidence(operation="list_domains", noun="sending domains", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return MailerSendFullConfig

    @classmethod
    def parse_config(cls, config_data):
        cls._check_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    @staticmethod
    def _check_family(config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and "credential_type" in raw and raw["credential_type"] != "mailersend_api_token":
            raise ValueError("Attach a MailerSend API token credential")

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a MailerSend API token")
        operation = config.operation
        method, path = ROUTES[operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True, by_alias=True)
        for key, value in values.items():
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(resource_id(value), safe=""))
        body = None
        if operation == "send_email":
            body = values["message"]
        elif operation == "send_bulk_email":
            body = values["messages"]
        elif isinstance(config, Suppress):
            body = {"domain_id": values["domain_id"], "recipients": values["recipients"]}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers={
                    "Authorization": "Bearer " + credential.api_token, "Accept": "application/json",
                }, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("MailerSend could not be reached; request outcome is unknown") from None
        if not 200 <= response.status_code < 300:
            message = "MailerSend request failed"
            try:
                detail = response.json().get("message")
                if isinstance(detail, str):
                    message = detail.replace(credential.api_token, "[redacted]")[:500]
            except (ValueError, AttributeError):
                pass
            raise ValueError(f"MailerSend HTTP {response.status_code}: {message}")
        if len(response.content) > 5_000_000:
            raise ValueError("MailerSend response exceeds the supported size")
        payload = None
        if response.content:
            if "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("MailerSend returned an unexpected content type")
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("MailerSend returned invalid JSON") from None
            if not isinstance(payload, (dict, list)):
                raise ValueError("MailerSend returned an unexpected response shape")
            if isinstance(payload, dict) and ("errors" in payload or "error" in payload):
                raise ValueError("MailerSend returned an error envelope")
        if method == "GET":
            if not isinstance(payload, dict) or "data" not in payload:
                raise ValueError("MailerSend response is missing its data envelope")
            if operation.startswith("list_") and not isinstance(payload["data"], list):
                raise ValueError("MailerSend returned an invalid list envelope")
        result = {"status": "accepted" if operation in {"send_email", "send_bulk_email"} else "success",
            "operation": operation, "http_status": response.status_code, "data": payload.get("data", payload) if isinstance(payload, dict) else payload}
        if isinstance(payload, dict):
            for key in ("links", "meta"):
                if key in payload:
                    result[key] = payload[key]
        if operation in {"send_email", "send_bulk_email"}:
            result["delivery_verified"] = False
            result["message_id"] = response.headers.get("x-message-id")
        return result
