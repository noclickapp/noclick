"""Bitsnap merchant API v1: JSON Connect calls and signed shop events.

Contract: https://bitsnap.pl/api/v1/openapi.json (1.0.0).
Events: https://docs.bitsnap.pl/reference/webhook-events/.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.bitsnap import BITSNAP_SCOPES

BASE_URL = "https://bitsnap.pl/api/v1"


class BitsnapAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bitsnap API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.bitsnap.pl/reference/api/",
        "x-credential-instructions": "In Bitsnap, open Settings → Developer and create a project API key. Paste the bs_test_ or bs_live_ key. Choose the scopes your actions need and enable its write switch for writes. Payment links require a live key. NoClick checks GetAccount to show the shop and environment.",
    })
    credential_type: Literal["bitsnap_api_key"] = Field("bitsnap_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def validate_fields(cls, value, info):
        if info.field_name == "idempotency_key" and value is not None:
            if not re.fullmatch(r"[\x20-\x7e]{1,255}", value):
                raise ValueError("Idempotency key must be 1–255 printable ASCII characters")
        if info.field_name in {"from_time", "to_time", "created_from", "created_to", "created_after", "expires_at"} and value is not None:
            if not isinstance(value, str) or not re.search(r"T.*(?:Z|[+-]\d\d:\d\d)$", value):
                raise ValueError("Use an RFC 3339 timestamp with a time zone")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @model_validator(mode="after")
    def date_order(self):
        for start, end in [("from_time", "to_time"), ("created_from", "created_to")]:
            a, b = getattr(self, start, None), getattr(self, end, None)
            if a and b and datetime.fromisoformat(a.replace("Z", "+00:00")) >= datetime.fromisoformat(b.replace("Z", "+00:00")):
                raise ValueError("The end must be after the start")
        if getattr(self, "operation", None) == "create_payment_link" and self.price.amount <= 0:
            raise ValueError("Payment link price must be greater than zero")
        return self


class Money(_Input):
    amount: int = Field(..., ge=0, le=2147483647, description="Integer in minor units: 4900 = 49.00 PLN.")
    currency: str = Field(..., pattern=r"^[A-Z]{3}$", description="Uppercase ISO 4217 currency code.")


class Discount(_Input):
    percent_off: float = Field(..., gt=0, le=100, description="Percent off. Must stay within the key's maximum discount (default 30%). Fixed-amount coupons are created in the Bitsnap dashboard.")


class Variant(_Input):
    id: Optional[str] = Field(None, min_length=1, description="Existing variant ID when updating; omit to create a variant.")
    name: str = Field(..., min_length=1)
    price: Money
    available_quantity: Optional[int] = Field(None, ge=0, le=2147483647)


class CheckoutItem(_Input):
    product_id: str = Field(..., min_length=1, description="Product or variant ID.")
    quantity: int = Field(1, ge=1, le=2147483647)


ProductStatus = Literal["PRODUCT_STATUS_DRAFT", "PRODUCT_STATUS_UNPUBLISHED", "PRODUCT_STATUS_PUBLISHED"]
OrderStatus = Literal["ORDER_STATUS_CREATED", "ORDER_STATUS_PAID", "ORDER_STATUS_UNPAID", "ORDER_STATUS_CANCELED", "ORDER_STATUS_SENT", "ORDER_STATUS_COMPLETED", "ORDER_STATUS_ISSUE", "ORDER_STATUS_RETURNED", "ORDER_STATUS_IN_PROGRESS"]
LinkStatus = Literal["PAYMENT_LINK_STATUS_ACTIVE", "PAYMENT_LINK_STATUS_PAID", "PAYMENT_LINK_STATUS_ARCHIVED"]

ID = (str, Field(..., min_length=1, title="Resource ID", description="Opaque Bitsnap resource ID."))
OPTIONAL_TEXT = (Optional[str], Field(None))
TIME = (Optional[str], Field(None, description="RFC 3339 timestamp, e.g. 2026-01-01T00:00:00Z.", json_schema_extra={"format": "date-time"}))
WRITE = {"idempotency_key": (Optional[str], Field(None, min_length=1, max_length=255, description="Reuse this key only for a retry of the same write and body (kept for 24 hours)."))}
PAGE = {"limit": (int, Field(50, ge=1, le=100)), "cursor": (Optional[str], Field(None, description="Opaque nextCursor from the previous response. One page per run."))}
COUPON = {"name": (str, Field(..., min_length=1)), "discount": (Discount, Field(...)), "includes_delivery": (StrictBool, Field(False)), "product_ids": (list[str], Field(default_factory=list)), "expires_at": TIME}

# Each public action maps to exactly one method of the pinned contract.
# tuple: service, RPC, human label, config fields.
OPERATIONS = {
    "get_account": ("AccountService", "GetAccount", "Get Account", {}),
    "list_products": ("ProductsService", "ListProducts", "List Products", {**PAGE, "search": OPTIONAL_TEXT, "include_drafts": (StrictBool, Field(False))}),
    "get_product": ("ProductsService", "GetProduct", "Get Product", {"id": ID}),
    "create_product": ("ProductsService", "CreateProduct", "Create Product", {**WRITE, "name": (str, Field(..., min_length=1)), "price": (Money, Field(...)), "status": (ProductStatus, Field("PRODUCT_STATUS_DRAFT")), "available_quantity": (Optional[int], Field(None, ge=0, le=2147483647)), "images": (list[str], Field(default_factory=list)), "variants": (list[Variant], Field(default_factory=list))}),
    "update_product": ("ProductsService", "UpdateProduct", "Update Product", {**WRITE, "id": ID, "revision": (Optional[int], Field(None, ge=0, le=2147483647, description="Revision last read; rejects concurrent edits. Omit to overwrite.")), "name": (Optional[str], Field(None, min_length=1)), "price": (Optional[Money], Field(None)), "status": (Optional[ProductStatus], Field(None)), "available_quantity": (Optional[int], Field(None, ge=0, le=2147483647)), "images": (list[str], Field(default_factory=list)), "variants": (list[Variant], Field(default_factory=list, description="Nonempty replaces all variants; include existing IDs to retain them. Empty keeps them."))}),
    "list_orders": ("OrdersService", "ListOrders", "List Orders", {**PAGE, "created_from": TIME, "created_to": TIME, "statuses": (list[OrderStatus], Field(default_factory=list)), "product_ids": (list[str], Field(default_factory=list))}),
    "get_order": ("OrdersService", "GetOrder", "Get Order", {"id": ID}),
    "list_coupons": ("CouponsService", "ListCoupons", "List Coupons", {}),
    "create_coupon": ("CouponsService", "CreateCoupon", "Create Coupon", {**WRITE, **COUPON}),
    "update_coupon": ("CouponsService", "UpdateCoupon", "Replace Coupon", {**WRITE, "id": ID, **COUPON}),
    "delete_coupon": ("CouponsService", "DeleteCoupon", "Delete Coupon and Its Codes", {**WRITE, "id": ID}),
    "create_coupon_code": ("CouponsService", "CreateCouponCode", "Create Coupon Code", {**WRITE, "coupon_id": (str, Field(..., min_length=1)), "code": (str, Field(..., min_length=1)), "max_redemptions": (Optional[int], Field(None, ge=1, le=2147483647)), "minimum_order_amount": (Optional[int], Field(None, ge=0, le=2147483647)), "expires_at": TIME}),
    "delete_coupon_code": ("CouponsService", "DeleteCouponCode", "Delete Coupon Code", {**WRITE, "id": ID}),
    "create_checkout_link": ("CheckoutService", "CreateCheckoutLink", "Create Product Checkout Link", {**WRITE, "items": (list[CheckoutItem], Field(..., min_length=1)), "customer_email": OPTIONAL_TEXT, "success_url": (Optional[str], Field(None, pattern=r"^https://[^\s]+$")), "cancel_url": (Optional[str], Field(None, pattern=r"^https://[^\s]+$")), "client_reference_id": (Optional[str], Field(None, max_length=200))}),
    "list_payment_links": ("PaymentLinkService", "ListPaymentLinks", "List Payment Links", {**PAGE, "statuses": (list[LinkStatus], Field(default_factory=list))}),
    "get_payment_link": ("PaymentLinkService", "GetPaymentLink", "Get Payment Link", {"id": ID}),
    "create_payment_link": ("PaymentLinkService", "CreatePaymentLink", "Create Payment Link", {**WRITE, "name": (str, Field(..., min_length=1, max_length=120)), "price": (Money, Field(..., description="Gross price, greater than zero. Live key required.")), "vat_rate": (Optional[int], Field(None, ge=0, le=100)), "usage": (Literal["PAYMENT_LINK_USAGE_SINGLE", "PAYMENT_LINK_USAGE_REUSABLE"], Field("PAYMENT_LINK_USAGE_SINGLE"))}),
    "archive_payment_link": ("PaymentLinkService", "ArchivePaymentLink", "Archive Payment Link", {**WRITE, "id": ID}),
    "send_payment_link": ("PaymentLinkService", "SendPaymentLink", "Email Payment Link", {**WRITE, "id": ID, "email": (str, Field(..., min_length=3)), "note": (Optional[str], Field(None, max_length=500))}),
    "get_sales_summary": ("StatsService", "GetSalesSummary", "Get Sales Summary", {"from_time": TIME, "to_time": TIME, "product_ids": (list[str], Field(default_factory=list))}),
    "list_forms": ("LeadsService", "ListForms", "List Lead Forms", {"status": OPTIONAL_TEXT}),
    "list_leads": ("LeadsService", "ListLeads", "List Leads", {"form_id": OPTIONAL_TEXT, "status": OPTIONAL_TEXT, "created_after": TIME, "page_size": (int, Field(50, ge=1, le=100)), "page_token": (Optional[str], Field(None, description="nextPageToken from the previous response.")), "min_score": (Optional[float], Field(None, ge=1, le=5)), "band": (Optional[Literal["hot", "warm", "cold"]], Field(None)), "spam_suspected": (Optional[StrictBool], Field(None)), "sort": (Literal["created_desc", "score_desc"], Field("created_desc"))}),
    "get_lead": ("LeadsService", "GetLead", "Get Lead", {"lead_id": (str, Field(..., min_length=1))}),
    "update_lead": ("LeadsService", "UpdateLead", "Update Lead", {**WRITE, "lead_id": (str, Field(..., min_length=1)), "status": OPTIONAL_TEXT, "tags": (list[str], Field(default_factory=list)), "notes": OPTIONAL_TEXT, "assignee_id": OPTIONAL_TEXT, "department_id": OPTIONAL_TEXT, "replace_tags": (StrictBool, Field(False))}),
}


def _make_config(name, spec):
    return create_model("Bitsnap" + "".join(w.title() for w in name.split("_")) + "Config", __module__=__name__, __base__=_Input,
        operation=(Literal[name], Field(name, title=spec[2], json_schema_extra={"ui:hidden": True, "x-display-name": spec[2], "x-category": spec[0].removesuffix("Service"), "x-is-trigger": False})), **spec[3])


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})

WEBHOOK_EVENTS = (
    "TRANSACTION_CREATED", "TRANSACTION_SUCCESS", "TRANSACTION_FAILURE", "TRANSACTION_EXPIRED", "TRANSACTION_CHARGE",
    "SUBSCRIPTION_CREATED", "SUBSCRIPTION_PAUSED", "SUBSCRIPTION_RESUMED", "SUBSCRIPTION_UPDATED", "SUBSCRIPTION_DELETED",
    "SUBSCRIPTION_CHARGE_PAID", "SUBSCRIPTION_CHARGE_FAILED", "SUBSCRIPTION_PAST_DUE", "SUBSCRIPTION_CANCELED",
    "ACCESS_EXPIRES_IN_3_DAYS", "ACCESS_EXPIRED", "CART_RECOVERY", "TESTIMONIAL_FULFILLED", "PARTNER_COMMISSION_EARNED",
    "REFUND_SUCCEEDED", "REFUND_FAILED", "CONFIGURATOR_SUBMISSION_CREATED", "CONFIGURATOR_SUBMISSION_UPDATED",
    "CONFIGURATOR_SUBMISSION_STATUS_CHANGED", "CONFIGURATOR_FORM_PUBLISHED", "CONFIGURATOR_FORM_ARCHIVED",
    "CONFIGURATOR_CHECKOUT_STARTED", "CONFIGURATOR_CHECKOUT_PAID", "CONFIGURATOR_CHECKOUT_FAILED", "INVOICE_ISSUED",
)


class BitsnapOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Shop Event", json_schema_extra={"ui:hidden": True, "x-display-name": "On Shop Event", "x-category": "Triggers", "x-is-trigger": True})
    event_type: Literal["ALL", *WEBHOOK_EVENTS] = Field("ALL", title="Event", description="Receive all documented shop events or select one. Requires webhooks:write and the key's write switch.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered automatically with Bitsnap.", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


BitsnapConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (BitsnapOnEventConfig,)], Field(discriminator="operation")]


class BitsnapNodeConfig(NodeConfig[BitsnapConfig, BitsnapAPIKeyCredential]):
    pass


def _wire(value):
    """Connect JSON uses the documented camelCase protobuf field names."""
    if isinstance(value, list):
        return [_wire(item) for item in value]
    if isinstance(value, dict):
        return {({"from_time": "from", "to_time": "to"}.get(k) or re.sub(r"_([a-z])", lambda m: m[1].upper(), k)): _wire(v) for k, v in value.items()}
    return value


class BitsnapNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-bitsnap"
    connection_evidence = ConnectionEvidence(operation="get_account", identity_operation="get_account", noun="shop")
    scope_registry = BITSNAP_SCOPES

    @classmethod
    def get_config_model(cls):
        return BitsnapNodeConfig

    @classmethod
    async def _request(cls, credential, service, rpc, body, *, idempotency_key=None):
        key = BitsnapAPIKeyCredential.model_validate(credential).api_key
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.post(f"{BASE_URL}/bitsnap.v1.{service}/{rpc}", headers=headers, json=body)
        if not response.is_success:
            try:
                data = response.json()
                message = data.get("message") if isinstance(data, dict) else None
            except ValueError:
                message = None
            raise ValueError(f"Bitsnap API error {response.status_code}: {str(message or 'request failed').replace(key, '[redacted]')}")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Bitsnap returned an unexpected JSON response")
        if "code" in data and "message" in data:
            raise ValueError(f"Bitsnap API error: {str(data['message']).replace(key, '[redacted]')}")
        return data

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, BitsnapNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Bitsnap API key")
        config = self.config.config
        if isinstance(config, BitsnapOnEventConfig):
            return self.no_event_output("on_event", "Waiting for a signed Bitsnap event")
        name = config.operation
        self.scope_registry.require(name)
        service, rpc, _, _ = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        key = values.pop("idempotency_key", None)
        data = await self._request(self.config.credentials.model_dump(), service, rpc, _wire(values), idempotency_key=key)
        return {"status": "success", "operation": name, "data": data}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "ALL")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = BitsnapOnEventConfig.model_validate(config or {}).event_type
        data = await cls._request(credential, "WebhooksService", "CreateWebhook", {"name": f"NoClick {node_id}", "url": webhook_url, "events": [event]})
        webhook = data.get("webhook") or {}
        if not webhook.get("id") or not data.get("signingSecret"):
            raise ValueError("Bitsnap did not return the webhook ID and signing secret")
        return {"external_webhook_id": str(webhook["id"]), "signing_secret": data["signingSecret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint = (config or {}).get("external_webhook_id")
        if endpoint and credential:
            await cls._request(credential, "WebhooksService", "DeleteWebhook", {"id": str(endpoint)})

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-content-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        data = payload.get("eventData")
        if not isinstance(data, dict):
            return False
        event = data.get("event")
        return event in WEBHOOK_EVENTS and (config.get("event_type", "ALL") in ("ALL", event))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or not isinstance(output.get("eventData"), dict):
            return super().resolve_agent_event(output)
        data = output["eventData"]
        event, identifier = data.get("event"), data.get("id")
        if event not in WEBHOOK_EVENTS or not identifier:
            return super().resolve_agent_event(output)
        title = "Bitsnap " + event.replace("_", " ").lower()
        lines = [title, f"Shop: {output.get('projectId')}", f"Resource ID: {identifier}", f"Event ID: {data.get('eventId')}"]
        if "environment" in output:
            lines.append(f"Environment: {output['environment']}")
        if event.startswith("CONFIGURATOR_"):
            configurator = data["configurator"]
            form = configurator["form"]
            lines.append(f"Form: {form['name']} (form_id={form['id']})")
            if "contact" in configurator:
                lines.append("Contact: " + json.dumps(configurator["contact"], ensure_ascii=False))
            if "submission" in configurator:
                lines.append(f"To act: get_lead or update_lead with lead_id={identifier}.")
        else:
            if "customer" in data:
                lines.append("Customer: " + json.dumps(data["customer"], ensure_ascii=False))
            lines.append(f"To act: get_order with id={identifier}.")
        lines.append("Content: " + json.dumps(data, ensure_ascii=False)[:6000])
        return {"text": "\n".join(lines), "conversation_key": str(output.get("projectId")) + ":" + str(identifier), "title": title}
