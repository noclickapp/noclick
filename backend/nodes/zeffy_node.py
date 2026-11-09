"""Zeffy public API v1: organization payments, contacts, campaigns and users.

Contract: https://api.zeffy.com/api/docs/openapi.json (version 1.0).
Each operation makes one API request; list operations return one cursor page.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.zeffy.com/api/v1"


class ZeffyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zeffy API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.zeffy.com/o/settings?openIntegrations=true",
            "x-credential-instructions": "As the organization owner, open Settings → Integrations in Zeffy and complete the API key setup. Paste the key here without the Bearer prefix. Writes require the organization to have completed Stripe verification. NoClick checks the key by reading your organization's campaigns.",
        })
    credential_type: Literal["zeffy_api_key"] = Field("zeffy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the Zeffy API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def resource_ids(cls, value, info):
        if value is not None and (info.field_name.endswith("_id") or info.field_name in {"starting_after", "ending_before", "contact", "campaign"}):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
                raise ValueError("Use a Zeffy resource ID")
        return value


class _Page(_Input):
    limit: int = Field(10, ge=1, le=100, strict=True, description="Page size, 1–100. Each run fetches one page.")
    starting_after: str | None = Field(None, description="Use next_cursor from the previous page.")
    ending_before: str | None = Field(None, description="Return resources before this ID; do not combine with starting_after.")
    created_gt: int | None = Field(None, ge=0, description="Created after this Unix timestamp (seconds).")
    created_gte: int | None = Field(None, ge=0, description="Created at or after this Unix timestamp (seconds).")
    created_lt: int | None = Field(None, ge=0, description="Created before this Unix timestamp (seconds).")
    created_lte: int | None = Field(None, ge=0, description="Created at or before this Unix timestamp (seconds).")

    @model_validator(mode="after")
    def cursors(self):
        if self.starting_after and self.ending_before:
            raise ValueError("Choose either starting_after or ending_before")
        return self


class ZeffyListPaymentsConfig(_Page):
    """List payments, with optional donor, campaign, status and date filters."""
    operation: Literal["list_payments"] = "list_payments"
    currency: Literal["cad", "usd"] | None = None
    contact: str | None = Field(None, description="Contact ID to filter by.")
    campaign: str | None = Field(None, description="Campaign ID to filter by.")
    type: Literal["online", "manual", "imported"] | None = None
    status: Literal["succeeded", "failed", "pending"] | None = None


class ZeffyListContactsConfig(_Page):
    """Find contacts by exact primary or secondary email, or by creation/update time."""
    operation: Literal["list_contacts"] = "list_contacts"
    email: str | None = None
    updated_gt: int | None = Field(None, ge=0)
    updated_gte: int | None = Field(None, ge=0)
    updated_lt: int | None = Field(None, ge=0)
    updated_lte: int | None = Field(None, ge=0)


class ZeffyListCampaignsConfig(_Page):
    """List the organization's donation forms and ticketing campaigns."""
    operation: Literal["list_campaigns"] = "list_campaigns"
    creator_user_id: str | None = None


class ZeffyListUsersConfig(_Page):
    """List organization team members, including removed users when requested."""
    operation: Literal["list_users"] = "list_users"
    status: Literal["active", "removed"] | None = None


class ZeffyGetPaymentConfig(_Input):
    """Read a single payment belonging to the organization."""
    operation: Literal["get_payment"] = "get_payment"
    payment_id: str = Field(..., min_length=1, description="Zeffy payment ID.")


class ZeffyGetContactConfig(_Input):
    """Read a single contact belonging to the organization."""
    operation: Literal["get_contact"] = "get_contact"
    contact_id: str = Field(..., min_length=1, description="Zeffy contact ID.")


class ZeffyGetCampaignConfig(_Input):
    """Read a single campaign belonging to the organization."""
    operation: Literal["get_campaign"] = "get_campaign"
    campaign_id: str = Field(..., min_length=1, description="Zeffy campaign ID.")


class ZeffyGetUserConfig(_Input):
    """Read a single user belonging to the organization."""
    operation: Literal["get_user"] = "get_user"
    user_id: str = Field(..., min_length=1, description="Zeffy user ID.")


class ZeffyAddress(_Input):
    line1: str
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None = Field(..., min_length=2, max_length=2)


class _ContactFields(_Input):
    email: str | None = Field(None, description="Omit to leave unchanged; null clears on update.")
    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    phone_number: str | None = Field(None, max_length=50)
    address: ZeffyAddress | None = Field(None, description="Full mailing address object; null clears the whole address on update.")

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        if value is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Use an email address")
        return value


class ZeffyCreateContactConfig(_ContactFields):
    """Create a contact with email or both names. Existing emails return a conflict."""
    operation: Literal["create_contact"] = "create_contact"

    @model_validator(mode="after")
    def identity(self):
        if not self.email and not (self.first_name and self.last_name):
            raise ValueError("Provide an email or both first and last name")
        if any(getattr(self, key) is None for key in ("email", "first_name", "last_name") if key in self.model_fields_set):
            raise ValueError("Omit absent email and names when creating a contact")
        return self


class ZeffyUpsertContactConfig(_ContactFields):
    """Create or update by email (primary or secondary); the match email is not rewritten."""
    operation: Literal["upsert_contact"] = "upsert_contact"
    email: str = Field(..., min_length=3)


class ZeffyUpdateContactConfig(_ContactFields):
    """Update supplied fields on a contact. Explicit null clears a field."""
    operation: Literal["update_contact"] = "update_contact"
    contact_id: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def changes(self):
        if not (self.model_fields_set & set(_ContactFields.model_fields)):
            raise ValueError("Provide at least one contact field to update")
        return self


class ZeffyPaymentTicket(_Input):
    rate_id: str = Field(..., min_length=1, description="Rate ID from Get Campaign's rates.")
    quantity: int = Field(..., ge=1, strict=True)
    amount: int | None = Field(None, ge=0, strict=True, description="Per-unit cents, only for pay-what-you-can rates.")


class ZeffyCreatePaymentConfig(_Input):
    """Record an offline payment, without charging a card. Auctions are unsupported."""
    operation: Literal["create_payment"] = "create_payment"
    campaign_id: str = Field(..., min_length=1)
    amount: int | None = Field(None, ge=0, strict=True, description="Donation in cents. For donation forms only; use tickets for ticketing campaigns.")
    tickets: list[ZeffyPaymentTicket] | None = Field(None, min_length=1, max_length=1000)
    occurrence_id: str | None = Field(None, description="Required for ticketing campaigns with multiple occurrences.")
    extra_donation: int | None = Field(None, ge=0, strict=True, description="Extra cents, for ticketing only.")
    payment_method: Literal["cash", "cheque", "in_kind", "other"] = "cash"
    email: str | None = None
    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    generate_tax_receipt: StrictBool = Field(False, description="Generate and email a tax receipt.")
    send_confirmation_email: StrictBool = Field(False, description="Send the buyer a confirmation email.")
    payment_date: str | None = Field(None, description="ISO calendar date or datetime, e.g. 2026-01-15. Defaults to now.")

    @field_validator("payment_date")
    @classmethod
    def date_format(cls, value):
        if value is not None:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Use an ISO calendar date or datetime") from None
        return value

    @model_validator(mode="after")
    def campaign_payment(self):
        if (self.amount is None) == (self.tickets is None):
            raise ValueError("Provide either amount for a donation form or tickets for a ticketing campaign")
        if self.tickets is None and (self.extra_donation is not None or self.occurrence_id is not None):
            raise ValueError("Occurrence and extra donation apply only to ticketing campaigns")
        return self


class ZeffyDeletePaymentConfig(_Input):
    """Permanently delete a manual/imported payment; cancel its receipt and keep its contact. No email is sent. Online payments cannot be deleted."""
    operation: Literal["delete_payment"] = "delete_payment"
    payment_id: str = Field(..., min_length=1)


class ZeffyDeleteContactConfig(_Input):
    """Permanently delete a contact, with the dashboard's side effects. Active memberships prevent deletion."""
    operation: Literal["delete_contact"] = "delete_contact"
    contact_id: str = Field(..., min_length=1)


ZeffyConfig = Annotated[Union[
    ZeffyListPaymentsConfig, ZeffyGetPaymentConfig, ZeffyCreatePaymentConfig, ZeffyDeletePaymentConfig,
    ZeffyListContactsConfig, ZeffyGetContactConfig, ZeffyCreateContactConfig, ZeffyUpsertContactConfig,
    ZeffyUpdateContactConfig, ZeffyDeleteContactConfig, ZeffyListCampaignsConfig, ZeffyGetCampaignConfig,
    ZeffyListUsersConfig, ZeffyGetUserConfig,
], Field(discriminator="operation")]


class ZeffyFullConfig(NodeConfig[ZeffyConfig, ZeffyAPIKeyCredential]):
    pass


# Fixed operations, never a caller-supplied method, host or URL.
ROUTES = {
    "list_payments": ("GET", "payments", None),
    "get_payment": ("GET", "payments", "payment_id"),
    "create_payment": ("POST", "payments", None),
    "delete_payment": ("DELETE", "payments", "payment_id"),
    "list_contacts": ("GET", "contacts", None),
    "get_contact": ("GET", "contacts", "contact_id"),
    "create_contact": ("POST", "contacts", None),
    "upsert_contact": ("PUT", "contacts", None),
    "update_contact": ("PATCH", "contacts", "contact_id"),
    "delete_contact": ("DELETE", "contacts", "contact_id"),
    "list_campaigns": ("GET", "campaigns", None),
    "get_campaign": ("GET", "campaigns", "campaign_id"),
    "list_users": ("GET", "users", None),
    "get_user": ("GET", "users", "user_id"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    return value


class ZeffyNode(WorkflowNode):
    integration_type = "automation-zeffy"
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return ZeffyFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Zeffy API key")
        credential = self.config.credentials
        config = self.config.config
        operation = config.operation
        method, resource, id_field = ROUTES[operation]
        path = "/" + resource
        if id_field:
            path += "/" + getattr(config, id_field)
        listing = operation.startswith("list_")
        params, body = {}, None
        if listing:
            for key, value in config.model_dump(exclude_none=True).items():
                if key == "operation":
                    continue
                if key.startswith(("created_", "updated_")):
                    prefix, suffix = key.rsplit("_", 1)
                    key = prefix + "[" + suffix + "]"
                params[key] = value
        elif method in {"POST", "PUT", "PATCH"}:
            body = config.model_dump(exclude_unset=True, exclude={"operation", id_field} if id_field else {"operation"})
            if isinstance(config, ZeffyCreatePaymentConfig):
                body = config.model_dump(exclude_none=True, exclude={"operation"})
        response = None
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    json=body, headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"})
            expected = {201} if operation in {"create_payment", "create_contact"} else {200, 201} if operation == "upsert_contact" else {204} if operation == "delete_contact" else {200}
            if response.status_code not in expected:
                message = "Zeffy request failed (HTTP " + str(response.status_code) + ")"
                if len(response.content) <= 2_000_000:
                    try:
                        error = response.json().get("error", {})
                        if isinstance(error, dict) and isinstance(error.get("message"), str):
                            message = error["message"][:2000]
                    except (ValueError, AttributeError):
                        pass
                return {"status": "error", "error": _redact(message, credential.api_key), "http_status": response.status_code}
            if operation == "delete_contact":
                return {"status": "success", "deleted_id": config.contact_id, "deletion_acknowledged": True, "http_status": 204}
            if len(response.content) > 2_000_000 or "json" not in response.headers.get("Content-Type", ""):
                raise ValueError("Expected bounded JSON")
            result = response.json()
            if not isinstance(result, dict) or "error" in result:
                raise ValueError("Invalid Zeffy response")
            if listing:
                if result.get("object") != "list" or not isinstance(result.get("data"), list) or type(result.get("has_more")) is not bool or "next_cursor" not in result:
                    raise ValueError("Invalid Zeffy list page")
                if result["next_cursor"] is not None and not isinstance(result["next_cursor"], str):
                    raise ValueError("Invalid Zeffy cursor")
                for row in result["data"]:
                    self._record(row, resource)
                output = {"data": result["data"], "has_more": result["has_more"], "next_cursor": result["next_cursor"]}
            else:
                self._record(result, resource)
                if id_field and result["id"] != getattr(config, id_field):
                    raise ValueError("Zeffy returned a different resource ID")
                output = {"data": result}
            return _redact({"status": "success", "http_status": response.status_code, **output}, credential.api_key)
        except (ValueError, SSRFError, httpx.HTTPError):
            return {"status": "error", "error": "Zeffy returned an incomplete response or the request could not be confirmed.",
                **({"http_status": response.status_code} if response is not None else {})}

    @staticmethod
    def _record(row, resource):
        if not isinstance(row, dict) or row.get("object") != resource[:-1] or not isinstance(row.get("id"), str) or not row["id"]:
            raise ValueError("Invalid Zeffy resource")
