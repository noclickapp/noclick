"""MoonClerk's read-only v1 API for payment forms, customers and payments.

Each operation makes one documented request; paging stays explicit so workflows
can resume without silently truncating data or fetching an unbounded account.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.moonclerk.com"
ACCEPT = "application/vnd.moonclerk+json;version=1"


class MoonclerkAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Moonclerk API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.moonclerk.com/settings/api-key",
            "x-credential-instructions": "In MoonClerk, open Settings → API Key and generate or copy your API key. Paste only the key below. It grants read access to your account's payment forms, customers and payments. MoonClerk's API does not support writes.",
        },
    )
    credential_type: Literal["moonclerk_api_key"] = Field("moonclerk_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
            raise ValueError("Paste only the API key, without the Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    count: int = Field(10, ge=1, le=100, description="Records per page (1–100).")
    offset: int = Field(0, ge=0, description="Starting row; use next_offset to request another page.")


class ListForms(_Page):
    """List payment forms in this account."""
    operation: Literal["list_forms"] = Field("list_forms", json_schema_extra={"ui:hidden": True})


class GetForm(_Input):
    """Read a payment form by MoonClerk ID."""
    operation: Literal["get_form"] = Field("get_form", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Form ID")


class _Dates(_Page):
    form_id: int | None = Field(None, ge=1, title="Form ID")

    @field_validator("checkout_from", "checkout_to", "next_payment_from", "next_payment_to", "date_from", "date_to", mode="before", check_fields=False)
    @classmethod
    def dates(cls, value, info):
        if value is not None and info.field_name.endswith(("_from", "_to")):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("Use a UTC calendar date in YYYY-MM-DD format")
            date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def date_order(self):
        for key, value in self.model_dump().items():
            if key.endswith("_from") and value is not None:
                end = getattr(self, key[:-5] + "_to", None)
                if end is not None and value > end:
                    raise ValueError("The end date must be on or after the start date")
        return self


class ListCustomers(_Dates):
    """List customers (called Plans in MoonClerk), optionally filtered by form, checkout, next payment or subscription status."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    checkout_from: str | None = Field(None, json_schema_extra={"format": "date"})
    checkout_to: str | None = Field(None, json_schema_extra={"format": "date"})
    next_payment_from: str | None = Field(None, json_schema_extra={"format": "date"})
    next_payment_to: str | None = Field(None, json_schema_extra={"format": "date"})
    status: Literal["active", "canceled", "expired", "past_due", "pending", "unpaid"] | None = None


class GetCustomer(_Input):
    """Read a customer and subscription by MoonClerk ID."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Customer ID")


class ListPayments(_Dates):
    """List payments, optionally filtered by form, customer, UTC date range or payment status. Amounts remain in cents."""
    operation: Literal["list_payments"] = Field("list_payments", json_schema_extra={"ui:hidden": True})
    customer_id: int | None = Field(None, ge=1, title="Customer ID")
    date_from: str | None = Field(None, json_schema_extra={"format": "date"})
    date_to: str | None = Field(None, json_schema_extra={"format": "date"})
    status: Literal["successful", "refunded", "failed"] | None = None


class GetPayment(_Input):
    """Read a payment by MoonClerk ID, preserving cents, custom fields and Stripe references."""
    operation: Literal["get_payment"] = Field("get_payment", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, title="Payment ID")


MoonclerkOperation = Annotated[Union[ListForms, GetForm, ListCustomers, GetCustomer, ListPayments, GetPayment], Field(discriminator="operation")]


class MoonclerkNodeConfig(NodeConfig[MoonclerkOperation, MoonclerkAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class MoonclerkNode(WorkflowNode):
    integration_type = "automation-moonclerk"
    connection_evidence = ConnectionEvidence(noun="payment forms", operation="list_forms", label_keys=("title", "id"))
    edit_examples = ["List failed payments from last month", "Find active customers for this payment form", "Get this customer's subscription"]

    @classmethod
    def get_config_model(cls):
        return MoonclerkNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a MoonClerk API key")
        op = self.config.config
        key = self.config.credentials.api_key
        listing = isinstance(op, _Page)
        kind = {"list_forms": "forms", "get_form": "forms", "list_customers": "customers", "get_customer": "customers", "list_payments": "payments", "get_payment": "payments"}[op.operation]
        path = "/" + kind + ("" if listing else "/" + str(op.id))
        params = op.model_dump(exclude={"operation", "id"}, exclude_none=True)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", BASE_URL + path, params=params,
                    headers={"Authorization": "Token token=" + key, "Accept": ACCEPT})
        except httpx.RequestError:
            return {"status": "error", "error": "MoonClerk could not be reached; retry later"}
        if response.status_code != 200:
            # Preserve definitive provider rejection text for the shared connect
            # seam, but never echo an authentication key or HTML error page.
            message = response.text[:2000] if response.headers.get("content-type", "").startswith("text/plain") else "MoonClerk request failed"
            return _redact({"status": "error", "error": message, "status_code": response.status_code}, key)
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime not in {"application/vnd.moonclerk+json", "application/json"} or len(response.content) > 10_000_000:
            raise ValueError("MoonClerk returned an unexpected or oversized JSON response")
        body = response.json()
        envelope = kind if listing else kind[:-1]
        data = body.get(envelope) if isinstance(body, dict) else None
        if listing:
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("MoonClerk list response is missing its resource array")
            result = {"status": "success", "data": data, "count": len(data), "offset": op.offset,
                "page_may_have_more": len(data) == op.count,
                "next_offset": op.offset + op.count if len(data) == op.count else None}
        else:
            if not isinstance(data, dict):
                raise ValueError("MoonClerk response is missing its resource object")
            result = {"status": "success", "data": data}
        return _redact(result, key)
