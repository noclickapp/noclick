"""ThriveCart account API, pinned to the provider's published Postman collection.

Only endpoints with saved successful examples are exposed. Each execution makes
one provider request; searches return one page and writes are never retried.
"""
from __future__ import annotations

import re
import time
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://thrivecart.com/api/external"


class ThriveCartAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="ThriveCart API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.thrivecart.com/documentation/intro/authentication-via-api-key/",
        "x-credential-instructions": "In ThriveCart, open Settings → API & webhooks → API tokens. Create an API key for your account and paste it here. NoClick verifies it by reading your account information.",
    })
    credential_type: Literal["thrivecart_api_key"] = Field("thrivecart_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, str_strip_whitespace=True)


def operation(name, title):
    return Field(name, title=title, json_schema_extra={"ui:hidden": True})


ID = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[0-9]+$")]
Email = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]


class GetAccount(_Input):
    operation: Literal["get_account"] = operation("get_account", "Get Account")


class ListProducts(_Input):
    operation: Literal["list_products"] = operation("list_products", "List Products")


class ListBumps(_Input):
    operation: Literal["list_bumps"] = operation("list_bumps", "List Bump Offers")


class ListUpsells(_Input):
    operation: Literal["list_upsells"] = operation("list_upsells", "List Upsells")


class ListDownsells(_Input):
    operation: Literal["list_downsells"] = operation("list_downsells", "List Downsells")


class GetProduct(_Input):
    operation: Literal["get_product"] = operation("get_product", "Get Product")
    product_id: ID


class GetBump(_Input):
    operation: Literal["get_bump"] = operation("get_bump", "Get Bump Offer")
    bump_id: ID


class GetUpsell(_Input):
    operation: Literal["get_upsell"] = operation("get_upsell", "Get Upsell")
    upsell_id: ID


class GetDownsell(_Input):
    operation: Literal["get_downsell"] = operation("get_downsell", "Get Downsell")
    downsell_id: ID


class _Mode(_Input):
    mode: Literal["live", "test"] = Field("live", description="Choose live or test-mode transactions; live writes affect real subscriptions and payments.")


class SearchTransactions(_Mode):
    operation: Literal["search_transactions"] = operation("search_transactions", "Search Transactions")
    page: int = Field(1, ge=1, le=1000000)
    per_page: int = Field(10, ge=1, le=100, description="Results per page; at most 100.")
    query: str | None = Field(None, max_length=1000)
    transaction_type: Literal["any", "charge", "rebill", "refund", "cancel"] = "any"
    currency: str | None = Field(None, pattern=r"^[a-z]{3}$", description="Lowercase three-letter currency, such as usd.")


class GetCustomer(_Mode):
    operation: Literal["get_customer"] = operation("get_customer", "Read Customer Information")
    email: Email


class _Subscription(_Mode):
    order_id: ID
    subscription_id: ID


class CancelSubscription(_Subscription):
    operation: Literal["cancel_subscription"] = operation("cancel_subscription", "Cancel Subscription")


class PauseSubscription(_Subscription):
    operation: Literal["pause_subscription"] = operation("pause_subscription", "Pause Subscription")
    auto_resume: int | None = Field(None, ge=1, description="Optional Unix timestamp at least 24 hours in the future. Omit to pause indefinitely.")

    @field_validator("auto_resume")
    @classmethod
    def future_resume(cls, value):
        if value is not None and value < time.time() + 86400:
            raise ValueError("Auto-resume must be at least 24 hours in the future")
        return value


class ResumeSubscription(_Subscription):
    operation: Literal["resume_subscription"] = operation("resume_subscription", "Resume Subscription")


class RefundTransaction(_Mode):
    operation: Literal["refund_transaction"] = operation("refund_transaction", "Refund Transaction")
    order_id: ID
    reference: str = Field(..., min_length=1, max_length=200, description="Exact purchase reference from a transaction or customer's history.")


class SearchAffiliates(_Input):
    operation: Literal["search_affiliates"] = operation("search_affiliates", "Search Affiliates")
    page: int = Field(1, ge=1, le=1000000)
    per_page: int = Field(5, ge=1, le=25)
    product_id: ID | None = None
    query: str | None = Field(None, max_length=1000)


class GetAffiliate(_Input):
    operation: Literal["get_affiliate"] = operation("get_affiliate", "Read Affiliate Information")
    affiliate_id: str = Field(..., min_length=1, max_length=254, description="Affiliate ID, numeric user ID, or email address.")


class CreateStudent(_Input):
    operation: Literal["create_student"] = operation("create_student", "Create Learn Student")
    email: Email
    course_id: ID
    name: str | None = Field(None, min_length=1, max_length=150)
    tags: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=100)
    order_id: ID | None = None
    purchase_type: Literal["product", "bump", "upsell", "downsell"] | None = None
    purchase_id: ID | None = None
    trigger_emails: StrictBool = Field(True, description="Send the provider's student email; defaults to true as in ThriveCart.")

    @model_validator(mode="after")
    def order_relationship(self):
        fields = (self.order_id, self.purchase_type, self.purchase_id)
        if any(v is not None for v in fields) and not all(v is not None for v in fields):
            raise ValueError("Supply order ID, purchase type and purchase ID together")
        return self


Operation = Annotated[Union[GetAccount, ListProducts, ListBumps, ListUpsells, ListDownsells,
    GetProduct, GetBump, GetUpsell, GetDownsell, SearchTransactions, GetCustomer,
    CancelSubscription, PauseSubscription, ResumeSubscription, RefundTransaction,
    SearchAffiliates, GetAffiliate, CreateStudent], Field(discriminator="operation")]


class ThriveCartNodeConfig(NodeConfig[Operation, ThriveCartAPIKeyCredential]):
    pass


# One config operation maps to one published collection request.
ROUTES = {
    "get_account": ("GET", "/ping"),
    "list_products": ("GET", "/products"),
    "list_bumps": ("GET", "/bumps"),
    "list_upsells": ("GET", "/upsells"),
    "list_downsells": ("GET", "/downsells"),
    "get_product": ("GET", "/products/{product_id}"),
    "get_bump": ("GET", "/bumps/{bump_id}"),
    "get_upsell": ("GET", "/upsells/{upsell_id}"),
    "get_downsell": ("GET", "/downsells/{downsell_id}"),
    "search_transactions": ("GET", "/transactions"),
    "get_customer": ("POST", "/customer"),
    "cancel_subscription": ("POST", "/cancelSubscription"),
    "pause_subscription": ("POST", "/pauseSubscription"),
    "resume_subscription": ("POST", "/resumeSubscription"),
    "refund_transaction": ("POST", "/refund"),
    "search_affiliates": ("GET", "/affiliates"),
    "get_affiliate": ("POST", "/affiliate"),
    "create_student": ("POST", "/students"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    return value


class ThriveCartNode(WorkflowNode):
    integration_type = "automation-thrivecart"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account", identity_keys=("account_name", "user_name", "account_url"))

    @classmethod
    def get_config_model(cls):
        return ThriveCartNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a ThriveCart API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation", "mode"}, exclude_none=True)
        for field in re.findall(r"\{([^}]+)\}", route):
            route = route.replace("{" + field + "}", values.pop(field))
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        if isinstance(op, _Mode):
            headers["X-TC-Mode"] = op.mode
        params, data, files = None, None, None
        if isinstance(op, (SearchTransactions, SearchAffiliates)):
            values["perPage"] = values.pop("per_page")
            if isinstance(op, SearchTransactions):
                values["transactionType"] = values.pop("transaction_type")
            params = values
        elif isinstance(op, CreateStudent):
            tags = values.pop("tags")
            order = {field: values.pop(field) for field in ("order_id", "purchase_type", "purchase_id") if field in values}
            values["trigger_emails"] = "true" if op.trigger_emails else "false"
            pairs = list(values.items()) + [("tags[]", tag) for tag in tags]
            pairs += [("order_info[" + field + "]", value) for field, value in order.items()]
            files = [(name, (None, str(value))) for name, value in pairs]
        elif method == "POST":
            data = values
        try:
            async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=30.0) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, params=params, data=data, files=files)
        except httpx.RequestError:
            raise ValueError("ThriveCart request did not complete; inspect the account before retrying a write") from None
        try:
            body = response.json()
        except ValueError:
            raise ValueError(f"ThriveCart returned HTTP {response.status_code} without JSON") from None
        if not response.is_success or isinstance(body, dict) and ("error" in body or body.get("success") is False):
            detail = body.get("error", body.get("message", body)) if isinstance(body, dict) else body
            result = {"status": "error", "success": False, "http_status": response.status_code, "message": _redact(str(detail), key)}
        else:
            if not isinstance(body, (dict, list)):
                raise ValueError("ThriveCart returned an unexpected JSON response")
            if op.operation == "get_account" and not all(body.get(f) for f in ("account_id", "account_name")):
                raise ValueError("ThriveCart account information is missing")
            result = {"status": "success", "success": True, "data": _redact(body, key)}
            if isinstance(op, (SearchTransactions, SearchAffiliates)):
                # Preserve provider meta verbatim; do not infer completion from example counts.
                result["page"] = op.page
                result["per_page"] = op.per_page
        await self.emit(result)
        return result
