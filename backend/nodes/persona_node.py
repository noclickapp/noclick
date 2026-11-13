"""Persona identity workflows, pinned to the published 2026-09-29 API.

Each operation issues one request. Pagination links are returned, never fetched;
callers continue explicitly with page_after. Writes are never retried.
Contract: https://github.com/persona-id/persona-openapi/tree/main/2026-09-29
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import hashlib
import hmac
import json
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.withpersona.com/api/v1"
API_VERSION = "2026-09-29"


class PersonaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Persona API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.withpersona.com/dashboard/api-keys",
            "x-credential-instructions": "Create an API key in Persona's API Keys dashboard with permissions for the operations you need. Paste the key without the Bearer prefix. Sandbox and production keys access their respective environments. Connection reads your inquiries and needs inquiry read permission.",
        },
    )
    credential_type: Literal["persona_api_key"] = Field("persona_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page_size: int = Field(20, ge=1, le=100, title="Page Size")
    page_after: str | None = Field(None, max_length=256, title="After ID", description="Last resource ID from the preceding page; leave empty for the first page.")


class ListInquiries(_Page):
    operation: Literal["list_inquiries"] = Field("list_inquiries", title="List Inquiries")
    reference_id: str | None = Field(None, title="Reference ID")
    account_id: str | None = Field(None, title="Account ID")
    inquiry_status: str | None = Field(None, title="Inquiry Status", description="One status or comma-separated statuses, e.g. completed,approved.")


class _Inquiry(_Input):
    inquiry_id: str = Field(..., pattern=r"^inq_[A-Za-z0-9]+$", max_length=256, title="Inquiry ID")


class GetInquiry(_Inquiry):
    operation: Literal["get_inquiry"] = Field("get_inquiry", title="Get Inquiry")


class CreateInquiry(_Input):
    operation: Literal["create_inquiry"] = Field("create_inquiry", title="Create Inquiry")
    inquiry_template_id: str = Field(..., pattern=r"^itmpl_[A-Za-z0-9]+$", max_length=256, title="Inquiry Template ID")
    account_id: str | None = Field(None, title="Account ID")
    reference_id: str | None = Field(None, title="Account Reference ID", description="Reference used to automatically create or associate an account.")
    note: str | None = Field(None, title="Note")
    fields: dict | None = Field(None, title="Template Fields", description="Field name/value pairs defined by your inquiry template.")


class UpdateInquiry(_Inquiry):
    operation: Literal["update_inquiry"] = Field("update_inquiry", title="Update Inquiry")
    note: str = Field(..., title="Note", description="Replace the inquiry's unstructured note.")


class ApproveInquiry(_Inquiry):
    operation: Literal["approve_inquiry"] = Field("approve_inquiry", title="Approve Inquiry")
    comment: str | None = Field(None, title="Audit Comment")


class DeclineInquiry(_Inquiry):
    operation: Literal["decline_inquiry"] = Field("decline_inquiry", title="Decline Inquiry")
    comment: str | None = Field(None, title="Audit Comment")


class ReviewInquiry(_Inquiry):
    operation: Literal["mark_inquiry_for_review"] = Field("mark_inquiry_for_review", title="Mark Inquiry for Review")


class ExpireInquiry(_Inquiry):
    operation: Literal["expire_inquiry"] = Field("expire_inquiry", title="Expire Inquiry")


class SetInquiryTags(_Inquiry):
    operation: Literal["set_inquiry_tags"] = Field("set_inquiry_tags", title="Set Inquiry Tags")
    tags: list[str] = Field(..., title="Tag Names", description="Replace all tags. An empty list removes all tags.", json_schema_extra={"ui:widget": "list"})


class ListAccounts(_Page):
    operation: Literal["list_accounts"] = Field("list_accounts", title="List Accounts")
    reference_id: str | None = Field(None, title="Reference ID")


class _Account(_Input):
    account_id: str = Field(..., pattern=r"^act_[A-Za-z0-9]+$", max_length=256, title="Account ID")


class GetAccount(_Account):
    operation: Literal["get_account"] = Field("get_account", title="Get Account")


class CreateAccount(_Input):
    operation: Literal["create_account"] = Field("create_account", title="Create Account")
    reference_id: str = Field(..., min_length=1, title="Reference ID")
    account_type_id: str | None = Field(None, title="Account Type ID")
    name_first: str | None = Field(None, title="First Name")
    name_last: str | None = Field(None, title="Last Name")
    email_address: str | None = Field(None, title="Email Address")


class UpdateAccount(_Account):
    operation: Literal["update_account"] = Field("update_account", title="Update Account")
    reference_id: str = Field(..., min_length=1, title="Reference ID")


class ListCases(_Page):
    operation: Literal["list_cases"] = Field("list_cases", title="List Cases")
    case_status: str | None = Field(None, title="Case Status")
    account_id: str | None = Field(None, title="Account ID")


class _Case(_Input):
    case_id: str = Field(..., pattern=r"^case_[A-Za-z0-9]+$", max_length=256, title="Case ID")


class GetCase(_Case):
    operation: Literal["get_case"] = Field("get_case", title="Get Case")


class CreateCase(_Input):
    operation: Literal["create_case"] = Field("create_case", title="Create Case")
    case_template_id: str = Field(..., pattern=r"^ctmpl_[A-Za-z0-9]+$", max_length=256, title="Case Template ID")
    fields: dict | None = Field(None, title="Template Fields")


class SetCaseStatus(_Case):
    operation: Literal["set_case_status"] = Field("set_case_status", title="Set Case Status")
    case_status: str = Field(..., min_length=1, title="Case Status", description="A status configured on your case template.")


class ListReports(_Page):
    operation: Literal["list_reports"] = Field("list_reports", title="List Reports")
    account_id: str | None = Field(None, title="Account ID")
    reference_id: str | None = Field(None, title="Reference ID")


class GetReport(_Input):
    operation: Literal["get_report"] = Field("get_report", title="Get Report")
    report_id: str = Field(..., pattern=r"^rep_[A-Za-z0-9]+$", max_length=256, title="Report ID")


class ListInquiryTemplates(_Page):
    operation: Literal["list_inquiry_templates"] = Field("list_inquiry_templates", title="List Inquiry Templates")


class GetInquiryTemplate(_Input):
    operation: Literal["get_inquiry_template"] = Field("get_inquiry_template", title="Get Inquiry Template")
    inquiry_template_id: str = Field(..., pattern=r"^itmpl_[A-Za-z0-9]+$", max_length=256, title="Inquiry Template ID")


class _PersonaTrigger(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with Persona automatically; the API key needs webhook management permission.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class PersonaOnInquiryCreated(_PersonaTrigger):
    operation: Literal["on_inquiry_created"] = Field("on_inquiry_created", title="On Inquiry Created", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Inquiry Created",
    })


class PersonaOnInquiryCompleted(_PersonaTrigger):
    operation: Literal["on_inquiry_completed"] = Field("on_inquiry_completed", title="On Inquiry Completed", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Inquiry Completed",
    })


class PersonaOnInquiryFailed(_PersonaTrigger):
    operation: Literal["on_inquiry_failed"] = Field("on_inquiry_failed", title="On Inquiry Failed", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Inquiry Failed",
    })


class PersonaOnInquiryApproved(_PersonaTrigger):
    operation: Literal["on_inquiry_approved"] = Field("on_inquiry_approved", title="On Inquiry Approved", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Inquiry Approved",
    })


class PersonaOnInquiryDeclined(_PersonaTrigger):
    operation: Literal["on_inquiry_declined"] = Field("on_inquiry_declined", title="On Inquiry Declined", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Inquiry Declined",
    })


class PersonaOnInquiryMarkedForReview(_PersonaTrigger):
    operation: Literal["on_inquiry_marked_for_review"] = Field("on_inquiry_marked_for_review", title="On Inquiry Marked For Review", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Inquiry Marked For Review",
    })


class PersonaOnInquiryExpired(_PersonaTrigger):
    operation: Literal["on_inquiry_expired"] = Field("on_inquiry_expired", title="On Inquiry Expired", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Inquiry Expired",
    })


class PersonaOnAccountCreated(_PersonaTrigger):
    operation: Literal["on_account_created"] = Field("on_account_created", title="On Account Created", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Account Created",
    })


class PersonaOnCaseCreated(_PersonaTrigger):
    operation: Literal["on_case_created"] = Field("on_case_created", title="On Case Created", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Case Created",
    })


class PersonaOnCaseStatusUpdated(_PersonaTrigger):
    operation: Literal["on_case_status_updated"] = Field("on_case_status_updated", title="On Case Status Updated", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Case Status Updated",
    })


TRIGGER_EVENTS = {
    "on_inquiry_created": "inquiry.created",
    "on_inquiry_completed": "inquiry.completed",
    "on_inquiry_failed": "inquiry.failed",
    "on_inquiry_approved": "inquiry.approved",
    "on_inquiry_declined": "inquiry.declined",
    "on_inquiry_marked_for_review": "inquiry.marked-for-review",
    "on_inquiry_expired": "inquiry.expired",
    "on_account_created": "account.created",
    "on_case_created": "case.created",
    "on_case_status_updated": "case.status-updated",
}
# Persona's own MCP server: agents get its tools through a person's Persona sign-in.
PersonaMcpCredential = mcp_credential("persona", "https://withpersona.com/mcp", app="Persona")
PersonaCredential = Union[PersonaAPIKeyCredential, PersonaMcpCredential]


Operation = Annotated[Union[
    ListInquiries, GetInquiry, CreateInquiry, UpdateInquiry, ApproveInquiry,
    DeclineInquiry, ReviewInquiry, ExpireInquiry, SetInquiryTags,
    ListAccounts, GetAccount, CreateAccount, UpdateAccount,
    ListCases, GetCase, CreateCase, SetCaseStatus, ListReports, GetReport,
    ListInquiryTemplates, GetInquiryTemplate,
    PersonaOnInquiryCreated, PersonaOnInquiryCompleted, PersonaOnInquiryFailed,
    PersonaOnInquiryApproved, PersonaOnInquiryDeclined, PersonaOnInquiryMarkedForReview,
    PersonaOnInquiryExpired, PersonaOnAccountCreated, PersonaOnCaseCreated, PersonaOnCaseStatusUpdated,
], Field(discriminator="operation")]


class PersonaNodeConfig(NodeConfig[Operation, PersonaCredential]):
    pass


# One fixed provider route per user operation; no arbitrary URLs or methods.
ROUTES = {
    "list_inquiries": ("GET", "/inquiries"),
    "get_inquiry": ("GET", "/inquiries/{inquiry_id}"),
    "create_inquiry": ("POST", "/inquiries"),
    "update_inquiry": ("PATCH", "/inquiries/{inquiry_id}"),
    "approve_inquiry": ("POST", "/inquiries/{inquiry_id}/approve"),
    "decline_inquiry": ("POST", "/inquiries/{inquiry_id}/decline"),
    "mark_inquiry_for_review": ("POST", "/inquiries/{inquiry_id}/mark-for-review"),
    "expire_inquiry": ("POST", "/inquiries/{inquiry_id}/expire"),
    "set_inquiry_tags": ("POST", "/inquiries/{inquiry_id}/set-tags"),
    "list_accounts": ("GET", "/accounts"),
    "get_account": ("GET", "/accounts/{account_id}"),
    "create_account": ("POST", "/accounts"),
    "update_account": ("PATCH", "/accounts/{account_id}"),
    "list_cases": ("GET", "/cases"),
    "get_case": ("GET", "/cases/{case_id}"),
    "create_case": ("POST", "/cases"),
    "set_case_status": ("POST", "/cases/{case_id}/set-status"),
    "list_reports": ("GET", "/reports"),
    "get_report": ("GET", "/reports/{report_id}"),
    "list_inquiry_templates": ("GET", "/inquiry-templates"),
    "get_inquiry_template": ("GET", "/inquiry-templates/{inquiry_template_id}"),
}


def request_parts(config):
    """Translate the typed config to Persona's kebab-case JSON:API wire shape."""
    values = config.model_dump(exclude_none=True)
    operation = config.operation
    method, route = ROUTES[operation]
    route = route.format(**values)
    params, body = {}, None
    if operation.startswith("list_"):
        params["page[size]"] = config.page_size
        if config.page_after:
            params["page[after]"] = config.page_after
        for field in ("reference_id", "account_id", "inquiry_status", "case_status"):
            if values.get(field) is not None:
                name = "status" if field.endswith("_status") else field.replace("_", "-")
                params[f"filter[{name}]"] = values[field]
    elif operation == "create_inquiry":
        attributes = {k.replace("_", "-"): values[k] for k in ("inquiry_template_id", "account_id", "note", "fields") if k in values}
        # Do not request a session or verification link as a side effect.
        meta = {"auto-create-inquiry-session": False, "auto-create-one-time-link": False}
        if config.reference_id is not None:
            meta["auto-create-account-reference-id"] = config.reference_id
        body = {"data": {"attributes": attributes}, "meta": meta}
    elif operation in {"update_inquiry", "create_account", "update_account", "create_case"}:
        keys = {
            "update_inquiry": ("note",),
            "create_account": ("reference_id", "account_type_id", "name_first", "name_last", "email_address"),
            "update_account": ("reference_id",),
            "create_case": ("case_template_id", "fields"),
        }[operation]
        body = {"data": {"attributes": {k.replace("_", "-"): values[k] for k in keys if k in values}}}
    elif operation in {"approve_inquiry", "decline_inquiry"}:
        body = {"meta": {"comment": config.comment}} if config.comment is not None else {}
    elif operation == "set_inquiry_tags":
        body = {"meta": {"tag-name": config.tags}}
    elif operation == "set_case_status":
        body = {"meta": {"status": config.case_status}}
    return method, route, params, body


class PersonaNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-persona"
    credential_provider_labels = {"persona": "Persona Account"}
    connection_evidence = ConnectionEvidence(operation="list_inquiries", noun="Persona inquiries")

    @classmethod
    def get_config_model(cls):
        return PersonaNodeConfig

    @staticmethod
    async def _webhook_request(credential, method, route, body=None):
        token = PersonaAPIKeyCredential.model_validate(credential).api_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + route, headers={
                "Authorization": "Bearer " + token, "Persona-Version": API_VERSION,
                "Key-Inflection": "kebab", "Accept": "application/json",
            }, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Persona webhook request failed (HTTP {response.status_code})")
        return response.json()

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = TRIGGER_EVENTS[config["operation"]]
        payload = await cls._webhook_request(credential, "POST", "/webhooks", {
            "data": {"attributes": {"name": f"NoClick {node_id}", "url": webhook_url,
                "enabled-events": [event], "api-version": API_VERSION, "api-key-inflection": "kebab"}}})
        record = payload["data"]
        webhook_id = record["id"]
        secrets = record["attributes"]["secrets"]
        secret = next((s["value"] for s in secrets if s.get("expires-at") is None), None)
        if not webhook_id or not secret:
            raise ValueError("Persona did not return the webhook ID and active signing secret")
        # Creation returns a disabled webhook; activation requires the enable endpoint.
        try:
            await cls._webhook_request(credential, "POST", f"/webhooks/{quote(webhook_id, safe='')}/enable")
        except Exception:
            await cls._webhook_request(credential, "POST", f"/webhooks/{quote(webhook_id, safe='')}/archive")
            raise
        return {"external_webhook_id": webhook_id, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = (config or {}).get("external_webhook_id")
        if webhook_id and credential:
            await cls._webhook_request(credential, "POST", f"/webhooks/{quote(str(webhook_id), safe='')}/archive")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        header = next((v for k, v in headers.items() if k.lower() == "persona-signature"), "")
        # Persona sends space-separated signature sets during secret rotation.
        for signature_set in header.split():
            parts = dict(part.split("=", 1) for part in signature_set.split(",") if "=" in part)
            timestamp, signature = parts.get("t"), parts.get("v1")
            if timestamp and timestamp.isdigit() and signature and signature.isascii():
                digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
                if hmac.compare_digest(digest, signature):
                    return True
        return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        data = payload.get("data") or {}
        attributes = data.get("attributes") or {}
        return attributes.get("name") == TRIGGER_EVENTS.get(config.get("operation"))

    @classmethod
    def resolve_agent_event(cls, output):
        event = output.get("data") or {}
        attributes = event.get("attributes") or {}
        kind = attributes.get("name")
        if kind not in TRIGGER_EVENTS.values():
            return None
        record = (attributes.get("payload") or {}).get("data") or {}
        resource_id = record.get("id")
        if not resource_id:
            return None
        details = record.get("attributes") or {}
        lines = [f"Persona {kind.replace('.', ' ').replace('-', ' ')}: {resource_id}",
                 f"Event ID: {event.get('id')}", f"Occurred at: {attributes.get('created-at')}"]
        if kind.startswith("inquiry."):
            fields = details.get("fields") or {}
            subject = " ".join(str((fields.get(k) or {}).get("value") or "") for k in ("name-first", "name-last")).strip()
            if subject:
                lines.append(f"Person: {subject}")
        lines.append("Details: " + json.dumps(details, ensure_ascii=False, default=str)[:4000])
        lines.append("Resource relationships: " + json.dumps(record.get("relationships") or {}, default=str)[:2000])
        resource = kind.split(".")[0]
        lines.append(f"To act: get_{resource} {resource}_id={resource_id}.")
        return {"text": "\n".join(lines), "conversation_key": str(resource_id), "title": f"Persona {kind}: {resource_id}"}

    async def execute(self, inputs):
        if self.config.config.operation in TRIGGER_EVENTS:
            return inputs
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Persona API key")
        config = self.config.config
        method, route, params, body = request_parts(config)
        headers = {
            "Authorization": "Bearer " + credential.api_key,
            "Persona-Version": API_VERSION,
            "Key-Inflection": "kebab",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, params=params,
                                                **({"json": body} if body is not None else {}))
            if not 200 <= response.status_code < 300:
                try:
                    errors = response.json().get("errors", [])
                    message = "; ".join(str(e.get("detail") or e.get("title") or "Persona rejected the request") for e in errors if isinstance(e, dict))
                except (ValueError, AttributeError, TypeError):
                    message = ""
                return {"status": "error", "http_status": response.status_code,
                        "error": (message or "Persona rejected the request").replace(credential.api_key, "[redacted]")}
            payload = response.json()
            expected = list if config.operation.startswith("list_") else dict
            if not isinstance(payload, dict) or payload.get("errors") or not isinstance(payload.get("data"), expected):
                raise ValueError("Persona returned an unexpected response envelope")
            return {"status": "success", "operation": config.operation, **payload}
        except httpx.HTTPError:
            return {"status": "error", "error": "Persona request did not complete; check the provider before retrying a write"}
        except ValueError:
            return {"status": "error", "error": "Persona returned an unexpected response envelope"}
