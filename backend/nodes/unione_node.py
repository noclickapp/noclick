"""UniOne Web API v1.87: explicit transactional email and account operations.

Contract: https://docs.unione.io/openapi/unione-web-api-latest.json
Each operation makes one JSON POST. Lists retain provider pagination fields.
Mutations are never automatically retried.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.unione.io/en/transactional/api/v1"
CREDENTIAL_TYPE = "unione_api_key"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class UnioneAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="UniOne API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://cp.unione.io/en/user/info/api",
            "x-credential-instructions": "In UniOne account settings, copy your user API key, or use a project API key from Projects. Paste the key here. NoClick sends it in the X-API-KEY header. A project key limits operations to that project."})
    credential_type: Literal["unione_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("tags", "global_substitutions", "global_metadata", "events", mode="before", check_fields=False)
    @classmethod
    def json_editor(cls, value):
        # The editor sends JSON text; workflow tools can send native JSON.
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                raise ValueError("Enter valid JSON") from None
            if not isinstance(value, (dict, list)):
                raise ValueError("Enter a JSON object or array")
        return value


Email = Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
Text = Annotated[str, Field(min_length=1, max_length=100000)]
Domain = Annotated[str, Field(min_length=3, max_length=253, pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$")]
Cause = Literal["unsubscribed", "temporary_unavailable", "permanent_unavailable", "complained"]


class _Page(_Input):
    limit: int = Field(50, ge=1, le=1000, description="Records in this page; increase offset to request another page.")
    offset: int = Field(0, ge=0)


class _TemplateId(_Input):
    id: UUID = Field(..., title="Template ID")


class _WebhookUrl(_Input):
    url: str = Field(..., min_length=1, max_length=4096, pattern=r"^https?://[^\s]+$", title="Webhook URL",
        description="The exact URL identifies the webhook; NoClick does not fetch this URL.")


class _Email(_Input):
    email: Email


class _Domain(_Input):
    domain: Domain


class _Dump(_Input):
    dump_id: str = Field(..., min_length=1, max_length=512)


class SendEmail(_Email):
    """Send a transactional email to one recipient; returns accepted and failed recipients."""
    operation: Literal["send_email"] = Field("send_email", json_schema_extra={"ui:hidden": True})
    from_email: Email
    subject: Text
    plaintext: Text = Field(..., title="Plain text body")
    html: str | None = Field(None, max_length=2000000, title="HTML body")
    from_name: str | None = Field(None, max_length=1000)
    reply_to: Email | None = None
    template_id: UUID | None = None
    tags: Annotated[list[str], Field(max_length=10)] | str | None = Field(None, json_schema_extra=JSON_EDITOR)
    global_substitutions: dict[str, str] | str | None = Field(None, json_schema_extra=JSON_EDITOR)
    global_metadata: dict[str, str] | str | None = Field(None, json_schema_extra=JSON_EDITOR)
    idempotence_key: str | None = Field(None, max_length=256, description="Provider idempotence key; use a stable value when retrying a send yourself.")


class SetTemplate(_Input):
    """Create a template, or update it when an existing template ID is supplied."""
    operation: Literal["set_template"] = Field("set_template", json_schema_extra={"ui:hidden": True})
    name: Text
    from_email: Email
    id: UUID | None = Field(None, title="Existing template ID")
    subject: str | None = Field(None, max_length=100000)
    plaintext: str | None = Field(None, max_length=2000000)
    html: str | None = Field(None, max_length=2000000)
    from_name: str | None = Field(None, max_length=1000)
    reply_to: Email | None = None
    global_substitutions: dict[str, str] | str | None = Field(None, json_schema_extra=JSON_EDITOR)
    global_metadata: dict[str, str] | str | None = Field(None, json_schema_extra=JSON_EDITOR)


class GetTemplate(_TemplateId):
    """Get an email template by ID."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})


class ListTemplates(_Page):
    """List one page of account or project templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})


class DeleteTemplate(_TemplateId):
    """Delete an email template by ID."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})


class WebhookEvents(_Input):
    spam_block: list[Literal["*"]] | None = None
    email_status: list[Literal["sent", "delivered", "opened", "clicked", "unsubscribed", "subscribed", "soft_bounced", "hard_bounced", "spam"]] | None = None


class SetWebhook(_WebhookUrl):
    """Create or update the event handler identified by this URL."""
    operation: Literal["set_webhook"] = Field("set_webhook", json_schema_extra={"ui:hidden": True})
    status: Literal["active", "disabled", "stopped"] | None = None
    event_format: Literal["json_post", "json_post_gzip"] | None = None
    delivery_info: Literal[0, 1] | None = None
    single_event: Literal[0, 1] | None = None
    max_parallel: int | None = Field(None, ge=5, le=100)
    events: WebhookEvents | str | None = Field(None, json_schema_extra=JSON_EDITOR)


class GetWebhook(_WebhookUrl):
    """Get event handler settings for an exact URL."""
    operation: Literal["get_webhook"] = Field("get_webhook", json_schema_extra={"ui:hidden": True})


class ListWebhooks(_Page):
    """List one page of event notification handlers."""
    operation: Literal["list_webhooks"] = Field("list_webhooks", json_schema_extra={"ui:hidden": True})


class DeleteWebhook(_WebhookUrl):
    """Delete the event notification handler identified by its URL."""
    operation: Literal["delete_webhook"] = Field("delete_webhook", json_schema_extra={"ui:hidden": True})


class SetSuppression(_Email):
    """Suppress an email address with a specified cause."""
    operation: Literal["set_suppression"] = Field("set_suppression", json_schema_extra={"ui:hidden": True})
    cause: Cause
    created: str | None = Field(None, description="UTC YYYY-MM-DD hh:mm:ss; omit to use the current time.")


class GetSuppression(_Email):
    """Get suppression reasons for an address."""
    operation: Literal["get_suppression"] = Field("get_suppression", json_schema_extra={"ui:hidden": True})
    all_projects: bool | None = None


class ListSuppressions(_Input):
    """List one suppression page, passing the returned cursor for the next page."""
    operation: Literal["list_suppressions"] = Field("list_suppressions", json_schema_extra={"ui:hidden": True})
    cause: Literal["unsubscribed", "temporary_unavailable", "permanent_unavailable", "complained", "blocked"] | None = None
    source: Literal["user", "system", "subscriber"] | None = None
    start_time: str | None = Field(None, description="UTC YYYY-MM-DD hh:mm:ss, ignored when cursor is supplied.")
    cursor: str | None = Field(None, max_length=8192)
    limit: int = Field(50, ge=1, le=1000)


class DeleteSuppression(_Email):
    """Remove deletable suppressions for an address; provider limits still apply."""
    operation: Literal["delete_suppression"] = Field("delete_suppression", json_schema_extra={"ui:hidden": True})


class GetDomainDNSRecords(_Domain):
    """Get DNS setup records for a sending domain."""
    operation: Literal["get_domain_dns_records"] = Field("get_domain_dns_records", json_schema_extra={"ui:hidden": True})


class ListDomains(_Page):
    """List a page of sending domains and their verification and DKIM states."""
    operation: Literal["list_domains"] = Field("list_domains", json_schema_extra={"ui:hidden": True})
    domain: Domain | None = None


class ValidateDomainVerification(_Domain):
    """Trigger validation of the domain ownership record."""
    operation: Literal["validate_domain_verification"] = Field("validate_domain_verification", json_schema_extra={"ui:hidden": True})


class ValidateDomainDKIM(_Domain):
    """Trigger validation of the domain DKIM record."""
    operation: Literal["validate_domain_dkim"] = Field("validate_domain_dkim", json_schema_extra={"ui:hidden": True})


class CreateEventDump(_Input):
    """Queue an asynchronous CSV export; get its status and file URLs separately."""
    operation: Literal["create_event_dump"] = Field("create_event_dump", json_schema_extra={"ui:hidden": True})
    start_time: str = Field(..., description="UTC YYYY-MM-DD hh:mm:ss, within the account's retention window.")
    end_time: str | None = Field(None, description="Exclusive end time, UTC YYYY-MM-DD hh:mm:ss.")
    limit: int | None = Field(None, ge=1)
    all_projects: bool | None = None
    aggregate: Literal["", "day_status"] | None = None
    delimiter: Literal[",", ";"] | None = None
    format: Literal["csv", "csv_gzip"] | None = None


class GetEventDump(_Dump):
    """Get export preparation status and download URLs without downloading files."""
    operation: Literal["get_event_dump"] = Field("get_event_dump", json_schema_extra={"ui:hidden": True})


class ListEventDumps(_Input):
    """List existing asynchronous exports."""
    operation: Literal["list_event_dumps"] = Field("list_event_dumps", json_schema_extra={"ui:hidden": True})


class DeleteEventDump(_Dump):
    """Remove an export from the queue or storage."""
    operation: Literal["delete_event_dump"] = Field("delete_event_dump", json_schema_extra={"ui:hidden": True})


class ListTags(_Input):
    """List user-defined email tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})


class DeleteTag(_Input):
    """Remove a user-defined tag."""
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(..., ge=1)


class Ping(_Input):
    """Check API key validity and return the user ID."""
    operation: Literal["ping"] = Field("ping", json_schema_extra={"ui:hidden": True})


class GetAccountInfo(_Input):
    """Read the user or project identity and accounting information."""
    operation: Literal["get_account_info"] = Field("get_account_info", json_schema_extra={"ui:hidden": True})


UnioneConfig = Annotated[Union[SendEmail, SetTemplate, GetTemplate, ListTemplates,
    DeleteTemplate, SetWebhook, GetWebhook, ListWebhooks, DeleteWebhook,
    SetSuppression, GetSuppression, ListSuppressions, DeleteSuppression,
    GetDomainDNSRecords, ListDomains, ValidateDomainVerification, ValidateDomainDKIM,
    CreateEventDump, GetEventDump, ListEventDumps, DeleteEventDump, ListTags,
    DeleteTag, Ping, GetAccountInfo], Field(discriminator="operation")]


class UnioneFullConfig(NodeConfig[UnioneConfig, UnioneAPIKeyCredential]):
    pass


ROUTES = {
    "send_email": "/email/send.json", "set_template": "/template/set.json",
    "get_template": "/template/get.json", "list_templates": "/template/list.json",
    "delete_template": "/template/delete.json", "set_webhook": "/webhook/set.json",
    "get_webhook": "/webhook/get.json", "list_webhooks": "/webhook/list.json",
    "delete_webhook": "/webhook/delete.json", "set_suppression": "/suppression/set.json",
    "get_suppression": "/suppression/get.json", "list_suppressions": "/suppression/list.json",
    "delete_suppression": "/suppression/delete.json", "get_domain_dns_records": "/domain/get-dns-records.json",
    "list_domains": "/domain/list.json", "validate_domain_verification": "/domain/validate-verification-record.json",
    "validate_domain_dkim": "/domain/validate-dkim.json", "create_event_dump": "/event-dump/create.json",
    "get_event_dump": "/event-dump/get.json", "list_event_dumps": "/event-dump/list.json",
    "delete_event_dump": "/event-dump/delete.json", "list_tags": "/tag/list.json",
    "delete_tag": "/tag/delete.json", "ping": "/system/ping.json", "get_account_info": "/system/info.json",
}


def _body(config):
    data = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
    for field in ("start_time", "end_time", "created"):
        if field in data:
            try:
                if datetime.strptime(data[field], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S") != data[field]:
                    raise ValueError()
            except ValueError:
                raise ValueError(f"{field} must use UTC YYYY-MM-DD hh:mm:ss") from None
    if config.operation == "create_event_dump" and data.get("end_time") and data["end_time"] <= data["start_time"]:
        raise ValueError("End time must be after start time")
    if config.operation in {"send_email", "set_template"}:
        body = {k: data.pop(k) for k in ("html", "plaintext") if k in data}
        if body:
            data["body"] = body
        if config.operation == "send_email":
            data["recipients"] = [{"email": data.pop("email")}]
            return {"message": data}
        return {"template": data}
    return data


def _redact(value, key):
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items() if k.lower() not in {"api_key", "project_api_key", "x-api-key"}}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value.replace(key, "[redacted]") if isinstance(value, str) else value


class UnioneNode(WorkflowNode):
    integration_type = "automation-unione"
    connection_evidence = ConnectionEvidence(noun="UniOne account", identity_operation="get_account_info",
        identity_keys=("email", "project_name", "user_id"))

    @classmethod
    def get_config_model(cls):
        return UnioneFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a UniOne API key")
        cfg = self.config.config
        key = self.config.credentials.api_key
        body = _body(cfg)
        if len(json.dumps(body).encode("utf-8")) > 10_000_000:
            raise ValueError("UniOne requests must be no larger than 10 MB")
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request("POST", BASE_URL + ROUTES[cfg.operation], json=body,
                    headers={"X-API-KEY": key, "Accept": "application/json"})
            if len(response.content) > 10_000_000:
                raise ValueError("UniOne response exceeded 10 MB")
            try:
                result = response.json()
            except ValueError:
                raise ValueError("UniOne returned an unexpected non-JSON response") from None
            if not isinstance(result, dict):
                raise ValueError("UniOne returned an unexpected response shape")
            if response.status_code != 200 or result.get("status") != "success":
                output = {"status": "error", "http_status": response.status_code,
                    "message": result.get("message") or "UniOne did not confirm this request", "code": result.get("code")}
            else:
                output = result
        except httpx.RequestError:
            output = {"status": "error", "message": "UniOne request did not complete; check the provider before retrying a write", "outcome": "unknown"}
        output = _redact(output, key)
        await self.emit(output)
        return output
