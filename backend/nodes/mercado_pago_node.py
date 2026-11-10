"""Mercado Pago account automation against the official OpenAPI 1.0.0 contract.

Application access tokens stay in Authorization; card tokens come from MercadoPago.js.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.mercadopago.com"
CONTRACT = "https://raw.githubusercontent.com/mercadopago/openapi/main/spec3.json"


class MercadoPagoAccessToken(BaseModel):
    model_config = ConfigDict(title="Mercado Pago Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.mercadopago.com/developers/panel/app",
            "x-credential-instructions": "Open your Mercado Pago application, choose production or test credentials, and paste its Access Token. Use the token for the account you want to automate. Do not paste a Public Key or the Bearer prefix."})
    credential_type: Literal["mercado_pago_access_token"] = Field("mercado_pago_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access Token")
        if not re.fullmatch(r"[A-Za-z0-9._~-]+", value):
            raise ValueError("Paste the Access Token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(30, ge=1, le=100, title="Page Size")
    offset: int = Field(0, ge=0, title="Offset", description="One page per action; increment offset by limit for the next page.")


class _Payment(_Input):
    payment_id: int = Field(..., ge=1, title="Payment ID")


class _Resource(_Input):
    id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", title="Resource ID")


class _Idempotency(_Input):
    idempotency_key: str = Field(..., title="Idempotency Key", description="A UUID unique to this payment/refund attempt. Reuse the same UUID when retrying the same attempt.", json_schema_extra={"format": "uuid"})

    @field_validator("idempotency_key")
    @classmethod
    def uuid(cls, value):
        UUID(value)
        return value


class SearchPayments(_Page):
    operation: Literal["search_payments"] = "search_payments"
    sort: Literal["date_created", "date_last_updated"] = "date_created"
    criteria: Literal["asc", "desc"] = "desc"
    range: Literal["date_created", "date_last_updated", "money_release_date"] | None = None
    begin_date: str | None = Field(None, description="ISO 8601 date and time with timezone.", json_schema_extra={"format": "date-time"})
    end_date: str | None = Field(None, description="ISO 8601 date and time with timezone.", json_schema_extra={"format": "date-time"})
    status: str | None = None
    external_reference: str | None = None

    @field_validator("begin_date", "end_date")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Include a timezone in the date and time")
        return value


class GetPayment(_Payment):
    operation: Literal["get_payment"] = "get_payment"


class CreatePayment(_Idempotency):
    operation: Literal["create_payment"] = "create_payment"
    transaction_amount: float = Field(..., gt=0, allow_inf_nan=False, description="Decimal amount, not cents.")
    payment_method_id: str = Field(..., min_length=1, description="For example pix, visa, or a supported local method.")
    payer_email: str = Field(..., min_length=1, json_schema_extra={"format": "email"})
    token: str | None = Field(None, description="Client-side card token, required for card payments.", json_schema_extra={"ui:widget": "password"})
    installments: int = Field(1, ge=1)
    description: str | None = None
    external_reference: str | None = None
    identification_type: str | None = None
    identification_number: str | None = None


class UpdatePayment(_Payment):
    operation: Literal["update_payment"] = "update_payment"
    capture: bool | None = None
    status: Literal["cancelled"] | None = None
    transaction_amount: float | None = Field(None, gt=0, allow_inf_nan=False)
    date_of_expiration: str | None = Field(None, json_schema_extra={"format": "date-time"})


class CreateRefund(_Payment, _Idempotency):
    operation: Literal["create_refund"] = "create_refund"
    amount: float | None = Field(None, gt=0, allow_inf_nan=False, description="Leave empty for a full refund.")


class ListRefunds(_Payment):
    operation: Literal["list_refunds"] = "list_refunds"


class GetRefund(_Payment):
    operation: Literal["get_refund"] = "get_refund"
    refund_id: int = Field(..., ge=1)


class _Preference(_Input):
    items_json: str = Field(..., title="Items (JSON)", description='Array of items, for example [{"title":"Premium Plan","quantity":1,"unit_price":99.9}].', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["title", "quantity", "unit_price"], "properties": {"title": {"type": "string"}, "quantity": {"type": "integer", "minimum": 1}, "unit_price": {"type": "number", "minimum": 1}}}}})
    payer_email: str | None = Field(None, json_schema_extra={"format": "email"})
    external_reference: str | None = None

    @field_validator("items_json")
    @classmethod
    def items(cls, value):
        items = json.loads(value)
        if not isinstance(items, list) or not items:
            raise ValueError("Provide a nonempty JSON array of checkout items")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
                raise ValueError("Each item needs a title")
            if type(item.get("quantity")) is not int or item["quantity"] < 1:
                raise ValueError("Each item needs a positive integer quantity")
            price = item.get("unit_price")
            if type(price) not in (int, float) or price <= 0 or not math.isfinite(price):
                raise ValueError("Each item needs a positive finite unit_price")
        return value


class CreatePreference(_Preference):
    operation: Literal["create_preference"] = "create_preference"


class GetPreference(_Resource):
    operation: Literal["get_preference"] = "get_preference"


class UpdatePreference(_Preference, _Resource):
    operation: Literal["update_preference"] = "update_preference"


class SearchPreferences(_Page):
    operation: Literal["search_preferences"] = "search_preferences"
    external_reference: str | None = None


class _Customer(_Input):
    email: str = Field(..., min_length=1, json_schema_extra={"format": "email"})
    first_name: str | None = None
    last_name: str | None = None
    description: str | None = None


class CreateCustomer(_Customer):
    operation: Literal["create_customer"] = "create_customer"


class UpdateCustomer(_Customer, _Resource):
    operation: Literal["update_customer"] = "update_customer"


class GetCustomer(_Resource):
    operation: Literal["get_customer"] = "get_customer"


class SearchCustomers(_Page):
    operation: Literal["search_customers"] = "search_customers"
    email: str | None = Field(None, json_schema_extra={"format": "email"})


class CreateSubscription(_Input):
    operation: Literal["create_subscription"] = "create_subscription"
    reason: str = Field(..., min_length=1)
    payer_email: str = Field(..., min_length=1, json_schema_extra={"format": "email"})
    frequency: int = Field(1, ge=1)
    frequency_type: Literal["months", "days"] = "months"
    transaction_amount: float = Field(..., gt=0, allow_inf_nan=False)
    currency_id: Literal["ARS", "BRL", "MXN", "CLP", "COP", "PEN", "UYU", "USD"]
    card_token_id: str | None = Field(None, json_schema_extra={"ui:widget": "password"})
    back_url: str | None = Field(None, json_schema_extra={"format": "uri"})
    external_reference: str | None = None
    preapproval_plan_id: str | None = None
    status: Literal["pending", "authorized"] = "pending"


class GetSubscription(_Resource):
    operation: Literal["get_subscription"] = "get_subscription"


class UpdateSubscription(_Resource):
    operation: Literal["update_subscription"] = "update_subscription"
    status: Literal["pending", "authorized", "paused", "cancelled"]
    reason: str | None = None
    external_reference: str | None = None


class SearchSubscriptions(_Page):
    operation: Literal["search_subscriptions"] = "search_subscriptions"
    payer_email: str | None = Field(None, json_schema_extra={"format": "email"})
    preapproval_plan_id: str | None = None
    status: Literal["pending", "authorized", "paused", "cancelled"] | None = None


class GetSubscriptionInvoice(_Input):
    operation: Literal["get_subscription_invoice"] = "get_subscription_invoice"
    id: int = Field(..., ge=1, title="Invoice ID")


class GetMerchantOrder(_Input):
    operation: Literal["get_merchant_order"] = "get_merchant_order"
    id: int = Field(..., ge=1, title="Merchant Order ID")


class GetChargeback(_Resource):
    operation: Literal["get_chargeback"] = "get_chargeback"


class OnNewOrUpdatedPayment(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_payment"] = Field("on_new_or_updated_payment", title="On New or Updated Payment", json_schema_extra={"x-is-trigger": True, "x-display-name": "On New or Updated Payment", "x-category": "Triggers", "ui:hidden": True})
    lookback_minutes: int = Field(1440, ge=5, le=10080, description="Poll payments updated in this rolling window. Set longer than your schedule interval and expected downtime. Baselines existing payments when armed; at most 2,000 updated payments per window.")
    external_reference: str | None = None


Operation = Annotated[Union[SearchPayments, GetPayment, CreatePayment, UpdatePayment, CreateRefund, ListRefunds, GetRefund, CreatePreference, GetPreference, UpdatePreference, SearchPreferences, CreateCustomer, UpdateCustomer, GetCustomer, SearchCustomers, CreateSubscription, GetSubscription, UpdateSubscription, SearchSubscriptions, GetSubscriptionInvoice, GetMerchantOrder, GetChargeback, OnNewOrUpdatedPayment], Field(discriminator="operation")]


class MercadoPagoNodeConfig(NodeConfig[Operation, MercadoPagoAccessToken]):
    pass


# Each action maps to exactly one operation in the pinned provider contract.
ROUTES = {
    "search_payments": ("GET", "/v1/payments/search"),
    "get_payment": ("GET", "/v1/payments/{payment_id}"),
    "create_payment": ("POST", "/v1/payments"),
    "update_payment": ("PUT", "/v1/payments/{payment_id}"),
    "create_refund": ("POST", "/v1/payments/{payment_id}/refunds"),
    "list_refunds": ("GET", "/v1/payments/{payment_id}/refunds"),
    "get_refund": ("GET", "/v1/payments/{payment_id}/refunds/{refund_id}"),
    "create_preference": ("POST", "/checkout/preferences"),
    "get_preference": ("GET", "/checkout/preferences/{id}"),
    "update_preference": ("PUT", "/checkout/preferences/{id}"),
    "search_preferences": ("GET", "/checkout/preferences/search"),
    "create_customer": ("POST", "/v1/customers"),
    "update_customer": ("PUT", "/v1/customers/{id}"),
    "get_customer": ("GET", "/v1/customers/{id}"),
    "search_customers": ("GET", "/v1/customers/search"),
    "create_subscription": ("POST", "/preapproval"),
    "get_subscription": ("GET", "/preapproval/{id}"),
    "update_subscription": ("PUT", "/preapproval/{id}"),
    "search_subscriptions": ("GET", "/preapproval/search"),
    "get_subscription_invoice": ("GET", "/authorized_payments/{id}"),
    "get_merchant_order": ("GET", "/merchant_orders/{id}"),
    "get_chargeback": ("GET", "/v1/chargebacks/{id}"),
}


class MercadoPagoNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-mercado-pago"
    connection_evidence = ConnectionEvidence(noun="payments", operation="search_payments")

    @classmethod
    def get_config_model(cls):
        return MercadoPagoNodeConfig

    async def _request(self, method, path, *, params=None, body=None, idempotency_key=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Mercado Pago account")
        headers = {"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            message = response.text.replace(credential.access_token, "[redacted]")[:2000]
            raise ValueError(f"Mercado Pago HTTP {response.status_code}: {message}")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Mercado Pago returned an unexpected JSON response")
        if isinstance(data, dict) and "error" in data and data["error"]:
            raise ValueError("Mercado Pago rejected the request: " + str(data.get("message") or data["error"]).replace(credential.access_token, "[redacted]")[:2000])
        return data

    async def _poll_payments(self, config):
        end = datetime.now(timezone.utc)
        params = {"sort": "date_last_updated", "criteria": "desc", "range": "date_last_updated",
            "begin_date": (end - timedelta(minutes=config.lookback_minutes)).isoformat(), "end_date": end.isoformat(), "limit": 100}
        if config.external_reference is not None:
            params["external_reference"] = config.external_reference
        payments = []
        for offset in range(0, 2000, 100):
            data = await self._request("GET", "/v1/payments/search", params={**params, "offset": offset})
            batch = data.get("results") if isinstance(data, dict) else None
            if not isinstance(batch, list):
                raise ValueError("Mercado Pago payment search omitted results")
            for payment in batch:
                if not isinstance(payment, dict) or not payment.get("id") or not (payment.get("date_last_updated") or payment.get("date_created")):
                    raise ValueError("A payment is missing its ID or update time; poll state was not advanced")
            payments.extend(batch)
            paging = data.get("paging") or {}
            total = paging.get("total")
            if len(batch) < 100 or (isinstance(total, int) and offset + len(batch) >= total):
                break
        else:
            raise ValueError("More than 2,000 payments in this poll window; narrow lookback or external reference")
        fresh = await self._filter_unseen(payments, lambda p: f"{p['id']}:{p.get('date_last_updated') or p.get('date_created')}:{p.get('status')}:{p.get('transaction_amount_refunded')}")
        return {"payments": fresh, "new_payment_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        payments = output.get("payments") if isinstance(output, dict) else None
        if not isinstance(payments, list):
            return super().resolve_agent_event(output)
        if not payments:
            return None
        lines = []
        for payment in payments[:20]:
            payer = payment.get("payer") or {}
            lines.append(f"- Payment {payment.get('id')} from {payer.get('email') or payer.get('id') or 'an unnamed payer'}: {payment.get('status')}; {payment.get('transaction_amount')} {payment.get('currency_id')}. {payment.get('description') or ''} Reference: {payment.get('external_reference') or 'none'}. Updated: {payment.get('date_last_updated')}.")
        return {"text": f"Mercado Pago: {len(payments)} new or updated payment(s) in your account.\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, OnNewOrUpdatedPayment):
            return await self._poll_payments(config)
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in tuple(values):
            marker = "{" + field + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(field)), safe=""))
        key = values.pop("idempotency_key", None)
        if config.operation == "create_payment":
            payer = {"email": values.pop("payer_email")}
            kind, number = values.pop("identification_type", None), values.pop("identification_number", None)
            if bool(kind) != bool(number):
                raise ValueError("Provide both identification type and number")
            if kind:
                payer["identification"] = {"type": kind, "number": number}
            values["payer"] = payer
        elif isinstance(config, _Preference):
            values["items"] = json.loads(values.pop("items_json"))
            if "payer_email" in values:
                values["payer"] = {"email": values.pop("payer_email")}
        elif config.operation == "create_subscription":
            values["auto_recurring"] = {field: values.pop(field) for field in ("frequency", "frequency_type", "transaction_amount", "currency_id")}
        if method != "GET" and not values and config.operation != "create_refund":
            raise ValueError("Provide at least one field to update")
        data = await self._request(method, path, params=values if method == "GET" else None, body=values if method != "GET" else None, idempotency_key=key)
        return {"status": "success", "data": data}
