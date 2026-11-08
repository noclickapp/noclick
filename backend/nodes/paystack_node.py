"""Paystack's published API: one provider request for each workflow operation.

Contract: https://raw.githubusercontent.com/PaystackOSS/openapi/main/dist/paystack.yaml
Authentication: https://paystack.com/docs/api/authentication/
Amounts are integer minor units; API acknowledgements do not prove payment settlement.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.paystack.co"
Code = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.=-]+$")]
Positive = Annotated[int, Field(gt=0)]
Currency = Literal["GHS", "KES", "NGN", "USD", "ZAR"]
Interval = Literal["daily", "weekly", "monthly", "biannually", "annually"]


class PaystackAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Paystack API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.paystack.com/#/settings/developers",
            "x-credential-instructions": "Paste your Paystack secret key from Settings → API Keys & Webhooks. Use a test secret key for test data or a live secret key for real payments. Public keys cannot authorize these operations. NoClick sends the key only to api.paystack.co. Connecting reads your customer list; it does not test write permissions.",
        },
    )
    credential_type: Literal["paystack_api_key"] = Field("paystack_api_key", json_schema_extra={"ui:hidden": True})
    secret_key: str = Field(..., min_length=1, max_length=4096, title="Secret key", json_schema_extra={"ui:widget": "password"})

    @field_validator("secret_key", mode="before")
    @classmethod
    def shape_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Paystack secret key")
        value = clean_secret(value, field_name="Secret key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value) or value.startswith(("pk_", "Bearer")):
            raise ValueError("Paste a secret key without the Bearer prefix; public keys cannot authorize these operations")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("amount", "page", "per_page", "invoice_limit", "id", "plan_id", mode="before", check_fields=False)
    @classmethod
    def reject_boolean_numbers(cls, value, info):
        if isinstance(value, bool) and info.field_name in {"amount", "page", "per_page", "invoice_limit", "id", "plan_id"}:
            raise ValueError("Use an integer, not a boolean")
        return value


class _List(_Input):
    page: int = Field(1, ge=1, le=1000000, description="Page number. Each run fetches exactly one page.")
    per_page: int = Field(50, ge=1, le=100, description="Records per page (1–100).")
    from_date: Optional[datetime] = Field(None, description="Inclusive start timestamp in ISO 8601 format.")
    to_date: Optional[datetime] = Field(None, description="End timestamp in ISO 8601 format.")

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.from_date and self.to_date:
            try:
                if self.from_date > self.to_date:
                    raise ValueError("End date must be after start date")
            except TypeError:
                raise ValueError("Use the same timezone format for both dates") from None
        return self


class InitializeTransaction(_Input):
    """Initialize checkout; the customer must still complete payment."""
    operation: Literal["initialize_transaction"] = "initialize_transaction"
    email: str = Field(..., min_length=3, max_length=254, description="Customer email address.")
    amount: Positive = Field(..., description="Amount in the currency's smallest denomination.")
    currency: Optional[Currency] = None
    reference: Optional[Code] = Field(None, description="Unique reference; letters, numbers, -, . and = only.")
    callback_url: Optional[str] = Field(None, description="Fully qualified customer redirect URL.")
    plan: Optional[Code] = Field(None, description="Plan code; Paystack overrides amount when supplied.")
    invoice_limit: Optional[Positive] = None
    metadata: Optional[dict[str, Any]] = None


class VerifyTransaction(_Input):
    """Verify a transaction reference; inspect data.status to determine payment state."""
    operation: Literal["verify_transaction"] = "verify_transaction"
    reference: Code


class ListTransactions(_List):
    """List one page of transactions with optional filters."""
    operation: Literal["list_transactions"] = "list_transactions"
    status: Optional[Literal["success", "failed", "abandoned", "reversed"]] = None
    customer_code: Optional[Code] = None
    amount: Optional[Positive] = None
    channel: Optional[Literal["card", "pos", "bank", "dedicated_nuban", "ussd", "bank_transfer"]] = None


class GetTransaction(_Input):
    """Fetch a transaction by numeric ID."""
    operation: Literal["get_transaction"] = "get_transaction"
    id: Positive


class CreateCustomer(_Input):
    """Create a customer record."""
    operation: Literal["create_customer"] = "create_customer"
    email: str = Field(..., min_length=3, max_length=254)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    metadata: Optional[str] = Field(None, description="Stringified JSON object of custom data.")


class ListCustomers(_List):
    """List one page of this account's customers."""
    operation: Literal["list_customers"] = "list_customers"


class GetCustomer(_Input):
    """Fetch a customer by customer code."""
    operation: Literal["get_customer"] = "get_customer"
    code: Code


class UpdateCustomer(_Input):
    """Update selected customer fields; omitted fields are not sent."""
    operation: Literal["update_customer"] = "update_customer"
    code: Code
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    metadata: Optional[str] = Field(None, description="Stringified JSON object of custom data.")


class CreatePlan(_Input):
    """Create a recurring billing plan."""
    operation: Literal["create_plan"] = "create_plan"
    name: str = Field(..., min_length=1, max_length=500)
    amount: Positive = Field(..., description="Amount in minor currency units.")
    interval: Interval
    description: Optional[str] = None
    currency: Optional[Literal["NGN", "GHS", "ZAR", "USD"]] = None
    send_invoices: Optional[bool] = None
    send_sms: Optional[bool] = None
    invoice_limit: Optional[Positive] = None


class ListPlans(_List):
    """List one page of billing plans."""
    operation: Literal["list_plans"] = "list_plans"
    interval: Optional[Interval] = None
    amount: Optional[Positive] = None


class GetPlan(_Input):
    """Fetch a billing plan by code."""
    operation: Literal["get_plan"] = "get_plan"
    code: Code


class UpdatePlan(_Input):
    """Update a billing plan's name, price, cadence or notification settings."""
    operation: Literal["update_plan"] = "update_plan"
    code: Code
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    amount: Optional[Positive] = None
    interval: Optional[Interval] = None
    currency: Optional[Literal["NGN", "GHS", "ZAR", "USD"]] = None
    send_invoices: Optional[bool] = None
    send_sms: Optional[bool] = None
    invoice_limit: Optional[Positive] = None


class CreateSubscription(_Input):
    """Subscribe an existing customer to a plan using their saved authorization."""
    operation: Literal["create_subscription"] = "create_subscription"
    customer: str = Field(..., min_length=1, description="Customer code or email address.")
    plan: Code
    authorization: Optional[Code] = Field(None, description="Saved authorization code; defaults to the customer's most recent authorization.")
    start_date: Optional[datetime] = None


class ListSubscriptions(_List):
    """List one page of subscriptions."""
    operation: Literal["list_subscriptions"] = "list_subscriptions"
    plan_id: Optional[Positive] = Field(None, description="Numeric plan ID, not plan code.")
    customer: Optional[str] = Field(None, description="Customer ID.")


class GetSubscription(_Input):
    """Fetch a subscription by code."""
    operation: Literal["get_subscription"] = "get_subscription"
    code: Code


class EnableSubscription(_Input):
    """Enable a subscription with its email token."""
    operation: Literal["enable_subscription"] = "enable_subscription"
    code: Code
    token: str = Field(..., min_length=1, max_length=200, description="Subscription email_token returned by Paystack.", json_schema_extra={"ui:widget": "password"})


class DisableSubscription(_Input):
    """Disable a subscription with its email token."""
    operation: Literal["disable_subscription"] = "disable_subscription"
    code: Code
    token: str = Field(..., min_length=1, max_length=200, description="Subscription email_token returned by Paystack.", json_schema_extra={"ui:widget": "password"})


class CreateRefund(_Input):
    """Request a full or partial refund; processing may be asynchronous."""
    operation: Literal["create_refund"] = "create_refund"
    transaction: Code = Field(..., description="Reference of a previously completed transaction.")
    amount: Optional[Positive] = Field(None, description="Minor units; omit for a full refund. Cannot exceed the original amount.")
    currency: Optional[Currency] = None
    customer_note: Optional[str] = None
    merchant_note: Optional[str] = None


class ListRefunds(_List):
    """List one page of refunds."""
    operation: Literal["list_refunds"] = "list_refunds"


class GetRefund(_Input):
    """Fetch a refund by numeric ID."""
    operation: Literal["get_refund"] = "get_refund"
    id: Positive


class GetBalance(_Input):
    """Read the account's balances by currency."""
    operation: Literal["get_balance"] = "get_balance"


PaystackOperation = Annotated[Union[
    InitializeTransaction, VerifyTransaction, ListTransactions, GetTransaction,
    CreateCustomer, ListCustomers, GetCustomer, UpdateCustomer,
    CreatePlan, ListPlans, GetPlan, UpdatePlan,
    CreateSubscription, ListSubscriptions, GetSubscription, EnableSubscription, DisableSubscription,
    CreateRefund, ListRefunds, GetRefund, GetBalance,
], Field(discriminator="operation")]


class PaystackNodeConfig(NodeConfig[PaystackOperation, PaystackAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Each entry names exactly one operation in the pinned Paystack OpenAPI contract.
ROUTES = {
    "initialize_transaction": ("POST", "/transaction/initialize", None),
    "verify_transaction": ("GET", "/transaction/verify/{reference}", "reference"),
    "list_transactions": ("GET", "/transaction", None),
    "get_transaction": ("GET", "/transaction/{id}", "id"),
    "create_customer": ("POST", "/customer", None),
    "list_customers": ("GET", "/customer", None),
    "get_customer": ("GET", "/customer/{code}", "code"),
    "update_customer": ("PUT", "/customer/{code}", "code"),
    "create_plan": ("POST", "/plan", None),
    "list_plans": ("GET", "/plan", None),
    "get_plan": ("GET", "/plan/{code}", "code"),
    "update_plan": ("PUT", "/plan/{code}", "code"),
    "create_subscription": ("POST", "/subscription", None),
    "list_subscriptions": ("GET", "/subscription", None),
    "get_subscription": ("GET", "/subscription/{code}", "code"),
    "enable_subscription": ("POST", "/subscription/enable", None),
    "disable_subscription": ("POST", "/subscription/disable", None),
    "create_refund": ("POST", "/refund", None),
    "list_refunds": ("GET", "/refund", None),
    "get_refund": ("GET", "/refund/{id}", "id"),
    "get_balance": ("GET", "/balance", None),
}
_NO_DATA = {"update_plan", "enable_subscription", "disable_subscription"}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secrets): _redact(v, secrets) for k, v in value.items()}
    return value


class PaystackNode(WorkflowNode):
    integration_type = "automation-paystack"
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers", label_keys=("email", "customer_code", "id"))

    @classmethod
    def get_config_model(cls):
        return PaystackNodeConfig

    @staticmethod
    def _guard_credential(config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", "paystack_api_key") != "paystack_api_key":
            raise ValueError("Attach a Paystack API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._guard_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._guard_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Paystack secret key")
        op = self.config.config
        method, route, path_field = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if path_field:
            route = route.replace("{" + path_field + "}", str(values.pop(path_field)))
        if isinstance(op, _List):
            size = values.pop("per_page")
            values["per_page" if op.operation == "list_transactions" else "perPage"] = size
            for field, target in (("from_date", "from"), ("to_date", "to"), ("plan_id", "plan")):
                if field in values:
                    values[target] = values.pop(field)
        if op.operation in {"update_customer", "update_plan"} and not values:
            raise ValueError("Provide at least one field to update")
        if "metadata" in values and isinstance(values["metadata"], str):
            import json
            try:
                if not isinstance(json.loads(values["metadata"]), dict):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError("Metadata must be a stringified JSON object") from None
        key = self.config.credentials.secret_key
        secrets = (key, getattr(op, "token", None))
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    params=values if method == "GET" else None,
                    json=values if method != "GET" else None)
        except httpx.HTTPError:
            return {"status": "error", "error": "Paystack request could not be confirmed" + ("; inspect the provider before retrying this write" if method != "GET" else ""), "write_outcome": "unknown" if method != "GET" else None}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "Paystack returned a non-JSON response"}
        if not isinstance(payload, dict):
            return {"status": "error", "http_status": response.status_code, "error": "Paystack returned an invalid response envelope"}
        if not 200 <= response.status_code < 300 or payload.get("status") is not True:
            message = payload.get("message")
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(message, secrets) if isinstance(message, str) else "Paystack did not accept the request"}
        data = payload.get("data")
        if op.operation not in _NO_DATA:
            expected = list if isinstance(op, _List) or op.operation == "get_balance" else dict
            if not isinstance(data, expected):
                return {"status": "error", "error": "Paystack returned an unexpected data shape", "http_status": response.status_code}
        result = {"status": "success", "operation": op.operation, "http_status": response.status_code,
            "data": data, "provider_message": payload.get("message")}
        if isinstance(op, _List):
            result.update({"meta": payload.get("meta"), "page": op.page, "per_page": op.per_page})
        if method != "GET":
            result["write_acknowledged"] = True
        return _redact(result, secrets)
