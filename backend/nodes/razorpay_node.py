"""Razorpay payment automation using merchant-supplied Basic API credentials.

This initial surface follows the pinned collection's saved requests and responses.
Lists return one provider page; writes are never retried or claimed as read back.
"""
from __future__ import annotations

import base64
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://api.razorpay.com/v1"
CREDENTIAL_TYPE = "razorpay_api_key"


class RazorpayAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Razorpay API Key", hide_input_in_errors=True, extra="ignore",
        json_schema_extra={
            "x-credential-url": "https://dashboard.razorpay.com/app/keys",
            "x-credential-instructions": "In Razorpay Dashboard, select Test or Live mode, then Account & Settings → API Keys. Paste the key ID and key secret from the same pair. Test keys operate on test data; live keys can create live orders, payment links and subscriptions. NoClick sends Basic authentication only to api.razorpay.com. Connecting reads your customers; it does not verify write permissions.",
        })
    credential_type: Literal["razorpay_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    key_id: str = Field(..., title="Key ID", min_length=1, max_length=512, repr=False, json_schema_extra={"ui:widget": "password"})
    key_secret: str = Field(..., title="Key Secret", min_length=1, max_length=512, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("key_id", "key_secret", mode="before")
    @classmethod
    def clean(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API credential value")
        value = clean_secret(value, field_name="API credential", key=True)
        if any(ord(c) < 33 or ord(c) > 126 for c in value) or ":" in value:
            raise ValueError("Paste the credential without whitespace, a colon or an authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Notes(_Input):
    notes: dict[str, str] | None = Field(None, description="Up to 15 notes; each value is at most 256 characters.")

    @field_validator("notes")
    @classmethod
    def bounded_notes(cls, value):
        if value is not None and (len(value) > 15 or any(not k or len(k) > 256 or len(v) > 256 for k, v in value.items())):
            raise ValueError("Use at most 15 bounded notes")
        return value


class _Amount(_Input):
    amount: int = Field(..., ge=100, strict=True, description="Amount in the smallest currency unit, for example 10000 paise for INR 100.")
    currency: str = Field("INR", pattern=r"^[A-Z]{3}$", description="Three-letter supported currency code. The amount uses that currency's subunit.")


class ListCustomers(_Input):
    """Fetch one page of customers belonging to the connected merchant."""
    operation: Literal["list_customers"] = "list_customers"
    count: int = Field(10, ge=1, le=100, strict=True, description="Maximum customers in this page; this operation does not fetch subsequent pages.")


class CreateCustomer(_Notes):
    """Create a customer record. This does not charge the customer."""
    operation: Literal["create_customer"] = "create_customer"
    name: str = Field(..., min_length=1, max_length=200)
    email: str | None = Field(None, max_length=254)
    contact: str | None = Field(None, max_length=32)
    gstin: str | None = Field(None, max_length=15)
    fail_existing: Literal["0", "1"] = Field("1", description="1 rejects an existing customer; 0 allows Razorpay to return the existing customer.")


class ListOrders(_Input):
    """Fetch one page of merchant orders, without expanded payments."""
    operation: Literal["list_orders"] = "list_orders"
    count: int = Field(10, ge=1, le=100, strict=True, description="Maximum orders in this page; this operation does not fetch subsequent pages.")


class CreateOrder(_Amount, _Notes):
    """Create an order for checkout; this does not itself capture a payment."""
    operation: Literal["create_order"] = "create_order"
    receipt: str | None = Field(None, max_length=40, description="Your unique receipt reference, up to 40 characters.")


class ListPayments(_Input):
    """Fetch the provider's default page of payments, not the whole history."""
    operation: Literal["list_payments"] = "list_payments"


class ListRefunds(_Input):
    """Fetch one page of refunds without initiating a refund."""
    operation: Literal["list_refunds"] = "list_refunds"
    count: int = Field(10, ge=1, le=100, strict=True, description="Maximum refunds in this page; this operation does not fetch subsequent pages.")


class ListInvoices(_Input):
    """Fetch the default page of invoices; no invoice is issued or emailed."""
    operation: Literal["list_invoices"] = "list_invoices"


class CreateItem(_Amount):
    """Create a reusable invoice item with an amount and description."""
    operation: Literal["create_item"] = "create_item"
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)


class ListItems(_Input):
    """Fetch the provider's default page of invoice items."""
    operation: Literal["list_items"] = "list_items"


class PlanItem(_Amount):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)


class CreatePlan(_Notes):
    """Create a recurring billing plan; no subscription or charge is created."""
    operation: Literal["create_plan"] = "create_plan"
    period: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] = "monthly"
    interval: int = Field(1, ge=1, strict=True)
    item: PlanItem

    @model_validator(mode="after")
    def daily_interval(self):
        if self.period == "daily" and self.interval < 7:
            raise ValueError("Daily plans require an interval of at least 7")
        return self


class ListPlans(_Input):
    """Fetch the provider's default page of subscription plans."""
    operation: Literal["list_plans"] = "list_plans"


class CreateSubscription(_Notes):
    """Create a subscription requiring customer authorization before charging."""
    operation: Literal["create_subscription"] = "create_subscription"
    plan_id: str = Field(..., pattern=r"^plan_[A-Za-z0-9]+$", description="Existing plan ID from list_plans or create_plan.")
    total_count: int = Field(..., ge=1, strict=True, description="Number of billing cycles.")
    quantity: int = Field(1, ge=1, strict=True)
    start_at: int | None = Field(None, ge=1, strict=True, description="Unix seconds; omit for the provider's immediate-start behavior.")
    expire_by: int | None = Field(None, ge=1, strict=True, description="Unix seconds by which customer authorization must complete.")
    customer_notify: bool = Field(False, strict=True, description="Ask Razorpay to notify the customer; false suppresses the notification request.")


class ListSubscriptions(_Input):
    """Fetch the provider's default page of subscriptions."""
    operation: Literal["list_subscriptions"] = "list_subscriptions"


class LinkCustomer(_Input):
    name: str | None = Field(None, max_length=200)
    contact: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=254)


class LinkNotifications(_Input):
    sms: bool = Field(False, strict=True, description="Explicitly request an SMS containing the payment link.")
    email: bool = Field(False, strict=True, description="Explicitly request an email containing the payment link.")


class CreatePaymentLink(_Amount, _Notes):
    """Create a standard payment link with explicit notification choices."""
    operation: Literal["create_payment_link"] = "create_payment_link"
    description: str = Field(..., min_length=1, max_length=2048)
    reference_id: str | None = Field(None, max_length=40)
    customer: LinkCustomer | None = None
    notify: LinkNotifications = Field(default_factory=LinkNotifications)
    reminder_enable: bool = Field(False, strict=True, description="Enable provider payment reminders only when explicitly requested.")
    accept_partial: bool = Field(False, strict=True)
    first_min_partial_amount: int | None = Field(None, ge=100, strict=True)
    expire_by: int | None = Field(None, ge=1, strict=True, description="Link expiry in Unix seconds; must be a future timestamp accepted by Razorpay.")

    @model_validator(mode="after")
    def valid_partial(self):
        if self.first_min_partial_amount is not None and (not self.accept_partial or self.first_min_partial_amount > self.amount):
            raise ValueError("A partial minimum requires partial payments and cannot exceed the amount")
        if self.notify.sms and (self.customer is None or not self.customer.contact):
            raise ValueError("An SMS notification requires the customer's contact")
        if self.notify.email and (self.customer is None or not self.customer.email):
            raise ValueError("An email notification requires the customer's email")
        return self


class ListPaymentLinks(_Input):
    """Fetch the default page of standard payment links; no notifications are sent."""
    operation: Literal["list_payment_links"] = "list_payment_links"


RazorpayConfig = Annotated[Union[
    ListCustomers, CreateCustomer, ListOrders, CreateOrder, ListPayments, ListRefunds,
    ListInvoices, CreateItem, ListItems, CreatePlan, ListPlans, CreateSubscription,
    ListSubscriptions, CreatePaymentLink, ListPaymentLinks,
], Field(discriminator="operation")]


class RazorpayFullConfig(NodeConfig[RazorpayConfig, RazorpayAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# One operation per published collection item. Trailing slashes are intentional.
ROUTES = {
    "list_customers": ("GET", "/customers", "customer"),
    "create_customer": ("POST", "/customers", "customer"),
    "list_orders": ("GET", "/orders", "order"),
    "create_order": ("POST", "/orders", "order"),
    "list_payments": ("GET", "/payments/", "payment"),
    "list_refunds": ("GET", "/refunds", "refund"),
    "list_invoices": ("GET", "/invoices", "invoice"),
    "create_item": ("POST", "/items", "item"),
    "list_items": ("GET", "/items", "item"),
    "create_plan": ("POST", "/plans", "plan"),
    "list_plans": ("GET", "/plans", "plan"),
    "create_subscription": ("POST", "/subscriptions", "subscription"),
    "list_subscriptions": ("GET", "/subscriptions", "subscription"),
    "create_payment_link": ("POST", "/payment_links", "payment_link"),
    "list_payment_links": ("GET", "/payment_links/", "payment_link"),
}
PREFIXES = {"customer": "cust", "order": "order", "payment": "pay", "refund": "rfnd",
    "invoice": "inv", "item": "item", "plan": "plan", "subscription": "sub", "payment_link": "plink"}


def _resource(value, kind):
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not re.fullmatch(PREFIXES[kind] + r"_[A-Za-z0-9]+", value["id"]):
        raise ValueError("Razorpay returned an unexpected resource")
    if "entity" in value and value["entity"] != kind:
        raise ValueError("Razorpay returned a different resource kind")
    return value


def _redact(value, secrets):
    if isinstance(value, dict):
        return {_redact(k, secrets): _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
    return value


def _guard_credential(config_data):
    raw = config_data.get("credentials")
    if isinstance(raw, dict) and "credential_type" in raw and raw["credential_type"] != CREDENTIAL_TYPE:
        raise ValueError("Attach a Razorpay API key credential")


class RazorpayNode(WorkflowNode):
    integration_type = "automation-razorpay"
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers", label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return RazorpayFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _guard_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _guard_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not isinstance(self.config, RazorpayFullConfig) or self.config.credentials is None:
            raise ValueError("Connect a Razorpay API key pair")
        credential, config = self.config.credentials, self.config.config
        method, path, kind = ROUTES[config.operation]
        basic = base64.b64encode((credential.key_id + ":" + credential.key_secret).encode("ascii")).decode("ascii")
        secrets = (credential.key_id, credential.key_secret, basic)
        headers = {"Authorization": "Basic " + basic, "Accept": "application/json", "Content-Type": "application/json"}
        body = config.model_dump(exclude={"operation"}, exclude_none=True) if method == "POST" else None
        params = {"count": config.count} if hasattr(config, "count") else None
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        except (httpx.HTTPError, OSError, SSRFError):
            result = {"status": "error", "message": "Razorpay request did not complete; inspect the Dashboard before retrying a write", "write_outcome": "unknown" if method == "POST" else None}
        else:
            try:
                if len(response.content) > 5_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Razorpay returned an unexpected response")
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Razorpay returned an unexpected response")
                if response.status_code != 200 or "error" in payload:
                    error = payload.get("error")
                    message = error.get("description") if isinstance(error, dict) else None
                    result = {"status": "error", "http_status": response.status_code, "message": message if isinstance(message, str) else "Razorpay request was not confirmed", "write_outcome": "unknown" if method == "POST" and response.status_code >= 500 else None}
                elif method == "GET":
                    rows = payload.get("payment_links" if kind == "payment_link" else "items")
                    if not isinstance(rows, list):
                        raise ValueError("Razorpay returned an unexpected page")
                    if kind != "payment_link" and (payload.get("entity") != "collection" or type(payload.get("count")) is not int or payload["count"] != len(rows)):
                        raise ValueError("Razorpay returned an inconsistent page")
                    result = {"status": "success", "items": [_resource(row, kind) for row in rows], "count": len(rows), "page_only": True, "complete": False,
                        "pagination": "One provider page; no automatic pagination or completeness claim"}
                else:
                    result = {"status": "success", "item": _resource(payload, kind), "write_acknowledged": True, "readback_verified": False}
            except (ValueError, TypeError):
                result = {"status": "error", "http_status": response.status_code, "message": "Razorpay response could not be verified; inspect the Dashboard before retrying a write", "write_outcome": "unknown" if method == "POST" else None}
        result = _redact(result, secrets)
        await self.emit(result)
        return result
