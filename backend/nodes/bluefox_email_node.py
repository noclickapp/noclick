"""Bluefox Email project, contact, audience and email automation operations.

Routes and payloads follow the provider's v1 OpenAPI contract. Project-scoped
API keys are supplied by a person; connection evidence reads project settings.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.bluefox.email/v1/projectId"


def _segment(value: str) -> str:
    if not value.strip() or value in {".", ".."} or any(ord(c) < 32 for c in value):
        raise ValueError("Supply a nonempty resource identifier without control characters")
    return value


def _picker(field: str, label: str, parent: str | None = None) -> dict:
    options = {"field_name": field, "placeholder": label, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return {"x-dynamic-options": options}


class BluefoxEmailAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Bluefox Email API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://bluefox.email/docs/api/",
            "x-credential-instructions": "In Bluefox Email, open Project Settings > API Keys and paste your project API key. Copy the project ID from Project Settings. NoClick checks the key by reading that project's settings.",
        },
    )
    credential_type: Literal["bluefox_email_api_key"] = Field("bluefox_email_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})
    project_id: str = Field(..., title="Project ID", min_length=1, max_length=256)

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value

    @field_validator("project_id")
    @classmethod
    def project(cls, value):
        return _segment(value.strip())


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(10, ge=1, le=30, description="Items per page (maximum 30).")
    skip: int = Field(0, ge=0, description="Items to skip; use next_skip from the preceding result.")


class GetProject(_Input):
    """Read this API key's project settings and connection evidence."""
    operation: Literal["get_project"] = "get_project"


class ListContacts(_Page):
    operation: Literal["list_contacts"] = "list_contacts"


class _ContactAddress(_Input):
    email: str = Field(..., min_length=1, max_length=320, description="Contact email address.", json_schema_extra={"format": "email"})

    @field_validator("email")
    @classmethod
    def address(cls, value):
        value = value.strip()
        if "@" not in value or any(c.isspace() for c in value):
            raise ValueError("Supply a contact email address")
        return _segment(value)


class GetContact(_ContactAddress):
    operation: Literal["get_contact"] = "get_contact"


class CreateContact(_ContactAddress):
    operation: Literal["create_contact"] = "create_contact"
    name: str | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = Field(None, description="Custom contact fields, sent as top-level properties. Discover field names in Bluefox Email.")

    @field_validator("custom_fields")
    @classmethod
    def custom(cls, value):
        if value is not None and set(value) & {"email", "name", "tags", "_id", "_lists"}:
            raise ValueError("Use the named inputs for standard contact fields")
        return value


class UpdateContact(CreateContact):
    operation: Literal["update_contact"] = "update_contact"

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.tags is None and not self.custom_fields:
            raise ValueError("Supply a name, tags, or custom contact fields to update")
        return self


class DeleteContact(_ContactAddress):
    """Delete a contact and remove it from all subscriber lists."""
    operation: Literal["delete_contact"] = "delete_contact"


class ListSubscriberLists(_Page):
    operation: Literal["list_subscriber_lists"] = "list_subscriber_lists"


class _ListID(_Input):
    list_id: str = Field(..., min_length=1, json_schema_extra=_picker("list_id", "Choose subscriber list"))


class GetSubscriberList(_ListID):
    operation: Literal["get_subscriber_list"] = "get_subscriber_list"


class CreateSubscriberList(_Input):
    operation: Literal["create_subscriber_list"] = "create_subscriber_list"
    name: str = Field(..., min_length=1)
    description: str = Field(..., description="Subscriber-facing list description.")
    private: bool = False


class UpdateSubscriberList(_ListID):
    operation: Literal["update_subscriber_list"] = "update_subscriber_list"
    name: str | None = None
    description: str | None = None
    private: bool | None = None

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, k) is None for k in ("name", "description", "private")):
            raise ValueError("Supply at least one list setting to update")
        return self


class DeleteSubscriberList(_ListID):
    operation: Literal["delete_subscriber_list"] = "delete_subscriber_list"


class ListSubscribers(_ListID, _Page):
    operation: Literal["list_subscribers"] = "list_subscribers"


class SubscribeContact(CreateContact, _ListID):
    """Subscribe a contact. The list's double opt-in may send a verification email."""
    operation: Literal["subscribe_contact"] = "subscribe_contact"
    status: Literal["unverified", "active"] | None = Field(None, description="Double opt-in still applies when active is requested; inspect the actual response.")


class GetSubscriber(_ContactAddress, _ListID):
    operation: Literal["get_subscriber"] = "get_subscriber"


class UpdateSubscriber(_ContactAddress, _ListID):
    """Pause, unsubscribe or reactivate; double opt-in may defer reactivation."""
    operation: Literal["update_subscriber"] = "update_subscriber"
    status: Literal["active", "paused", "unsubscribed"]
    paused_until: datetime | None = Field(None, description="Future ISO 8601 date-time with timezone; required when pausing.")

    @model_validator(mode="after")
    def pause(self):
        if self.paused_until is not None and self.paused_until.tzinfo is None:
            raise ValueError("Pause expiry needs a timezone")
        if self.status == "paused" and (self.paused_until is None or self.paused_until <= datetime.now(timezone.utc)):
            raise ValueError("Pausing requires a future pause expiry")
        return self


class ListCampaigns(_Page):
    operation: Literal["list_campaigns"] = "list_campaigns"


class _CampaignID(_Input):
    campaign_id: str = Field(..., min_length=1, json_schema_extra=_picker("campaign_id", "Choose campaign"))


class GetCampaign(_CampaignID):
    operation: Literal["get_campaign"] = "get_campaign"


class GetCampaignStats(_CampaignID):
    """Read aggregate campaign delivery and engagement totals."""
    operation: Literal["get_campaign_stats"] = "get_campaign_stats"


class ListTransactionalEmails(_Page):
    operation: Literal["list_transactional_emails"] = "list_transactional_emails"


class _TransactionalID(_Input):
    transactional_id: str = Field(..., min_length=1, json_schema_extra=_picker("transactional_id", "Choose transactional email"))


class GetTransactionalEmail(_TransactionalID):
    operation: Literal["get_transactional_email"] = "get_transactional_email"


class SendTransactionalEmail(_TransactionalID, _ContactAddress):
    """Queue one transactional email. Queue acceptance does not prove delivery."""
    operation: Literal["send_transactional_email"] = "send_transactional_email"
    data: dict[str, Any] | None = Field(None, description="Template variables merged at the top level of the template context.")


class ListTriggeredEmails(_Page):
    operation: Literal["list_triggered_emails"] = "list_triggered_emails"


class _TriggeredID(_Input):
    triggered_id: str = Field(..., min_length=1, json_schema_extra=_picker("triggered_id", "Choose triggered email"))


class GetTriggeredEmail(_TriggeredID):
    operation: Literal["get_triggered_email"] = "get_triggered_email"


class SendTriggeredEmail(_TriggeredID):
    """Queue a triggered email for explicit recipients, or all active list subscribers if emails is omitted."""
    operation: Literal["send_triggered_email"] = "send_triggered_email"
    emails: list[Annotated[str, Field(json_schema_extra={"format": "email"})]] | None = Field(None, min_length=1, description="Explicit recipients. Omit to send to every active subscriber on the email's list.")
    data: dict[str, Any] | None = None

    @field_validator("emails")
    @classmethod
    def addresses(cls, value):
        return [_ContactAddress(email=e).email for e in value] if value is not None else None


BluefoxEmailConfig = Annotated[Union[
    GetProject, ListContacts, GetContact, CreateContact, UpdateContact, DeleteContact,
    ListSubscriberLists, GetSubscriberList, CreateSubscriberList, UpdateSubscriberList, DeleteSubscriberList,
    ListSubscribers, SubscribeContact, GetSubscriber, UpdateSubscriber,
    ListCampaigns, GetCampaign, GetCampaignStats, ListTransactionalEmails, GetTransactionalEmail,
    SendTransactionalEmail, ListTriggeredEmails, GetTriggeredEmail, SendTriggeredEmail,
], Field(discriminator="operation")]


class BluefoxEmailFullConfig(NodeConfig[BluefoxEmailConfig, BluefoxEmailAPIKeyCredential]):
    pass


# Each entry is exactly one operation in https://api.bluefox.email/v1/openapi.json.
ROUTES = {
    "get_project": ("GET", ""),
    "list_contacts": ("GET", "/contacts"), "create_contact": ("POST", "/contacts"),
    "get_contact": ("GET", "/contacts/{email}"), "update_contact": ("PATCH", "/contacts/{email}"),
    "delete_contact": ("DELETE", "/contacts/{email}"),
    "list_subscriber_lists": ("GET", "/subscriber-lists"), "create_subscriber_list": ("POST", "/subscriber-lists"),
    "get_subscriber_list": ("GET", "/subscriber-lists/{list_id}"), "update_subscriber_list": ("PATCH", "/subscriber-lists/{list_id}"),
    "delete_subscriber_list": ("DELETE", "/subscriber-lists/{list_id}"),
    "list_subscribers": ("GET", "/subscriber-lists/{list_id}/subscribers"),
    "subscribe_contact": ("POST", "/subscriber-lists/{list_id}/subscribers"),
    "get_subscriber": ("GET", "/subscriber-lists/{list_id}/subscribers/{email}"),
    "update_subscriber": ("PATCH", "/subscriber-lists/{list_id}/subscribers/{email}"),
    "list_campaigns": ("GET", "/campaigns"), "get_campaign": ("GET", "/campaigns/{campaign_id}"),
    "get_campaign_stats": ("GET", "/campaigns/{campaign_id}/stats"),
    "list_transactional_emails": ("GET", "/transactional-emails"), "get_transactional_email": ("GET", "/transactional-emails/{transactional_id}"),
    "send_transactional_email": ("POST", "/send-transactional"),
    "list_triggered_emails": ("GET", "/triggered-emails"), "get_triggered_email": ("GET", "/triggered-emails/{triggered_id}"),
    "send_triggered_email": ("POST", "/send-triggered"),
}
CHOICES = {"list_id": "list_subscriber_lists", "campaign_id": "list_campaigns", "transactional_id": "list_transactional_emails", "triggered_id": "list_triggered_emails"}


def _redact(value, secret):
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value.replace(secret, "[redacted]") if isinstance(value, str) else value


class BluefoxEmailNode(WorkflowNode):
    integration_type = "automation-bluefox-email"
    connection_evidence = ConnectionEvidence(noun="Bluefox Email project", identity_operation="get_project")

    @classmethod
    def get_config_model(cls):
        return BluefoxEmailFullConfig

    @staticmethod
    async def _request(credential, op):
        method, route = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path_values = {k: quote(_segment(v), safe="") for k, v in values.items() if k in {"email", "list_id", "campaign_id", "transactional_id", "triggered_id"}}
        url = BASE_URL + "/" + quote(credential.project_id, safe="") + route.format(**path_values)
        params, body = {}, None
        if isinstance(op, _Page):
            params = {"limit": op.limit, "skip": op.skip}
        if method in {"POST", "PATCH"}:
            body = {k: v for k, v in values.items() if k not in {"operation", "list_id", "campaign_id", "transactional_id", "triggered_id", "custom_fields", "paused_until"}}
            if op.operation in {"update_contact", "update_subscriber"}:
                body.pop("email", None)
            body.update(values.get("custom_fields", {}))
            if "paused_until" in values:
                body["pausedUntil"] = values["paused_until"]
            if op.operation == "send_transactional_email":
                body["transactionalId"] = op.transactional_id
            if op.operation == "send_triggered_email":
                body["triggeredId"] = op.triggered_id
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, params=params, headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}, **({"json": body} if body is not None else {}))
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Bluefox Email returned HTTP {response.status_code} without a JSON response") from None
        if not isinstance(payload, dict):
            raise ValueError("Bluefox Email returned an invalid response envelope")
        if not 200 <= response.status_code < 300 or payload.get("error") or (isinstance(payload.get("status"), int) and payload["status"] >= 400):
            error = payload.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            raise ValueError(_redact(message, credential.api_key) if isinstance(message, str) else f"Bluefox Email rejected the request (HTTP {response.status_code})")
        if "result" not in payload or not isinstance(payload["result"], dict):
            raise ValueError("Bluefox Email response is missing its result object")
        result = _redact(payload["result"], credential.api_key)
        output = {"status": "success", "operation": op.operation, "data": result, "http_status": response.status_code}
        if isinstance(op, _Page):
            if not isinstance(result.get("items"), list):
                raise ValueError("Bluefox Email response is missing its page items")
            more = isinstance(result.get("next"), str) and bool(result["next"])
            output.update(items=result["items"], count=result.get("count"), has_more=more,
                          next_skip=op.skip + len(result["items"]) if more and result["items"] else None)
        return output

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Bluefox Email project API key")
        return await self._request(self.config.credentials, self.config.config)

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name not in CHOICES:
            raise ValueError("Unknown Bluefox Email selector")
        credential = BluefoxEmailAPIKeyCredential.model_validate(credential_data)
        skip = int(page_token) if page_token is not None else 0
        op = BluefoxEmailFullConfig.model_validate({"config": {"operation": CHOICES[field_name], "limit": 30, "skip": skip}}).config
        result = await cls._request(credential, op)
        options = [{"value": row["_id"], "label": row.get("name") or row["_id"]} for row in result["items"] if isinstance(row, dict) and isinstance(row.get("_id"), str)]
        if search:
            options = [o for o in options if search.casefold() in o["label"].casefold()]
        return {"options": options, "next_page_token": str(result["next_skip"]) if result["next_skip"] is not None else None}
