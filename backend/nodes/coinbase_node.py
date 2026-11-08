"""Coinbase Exchange REST API v1.0 (not the retail Advanced Trade/CDP API).

Authentication contract: https://docs.cdp.coinbase.com/exchange/rest-api/authentication
Each operation makes one request; writes are never retried automatically.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.exchange.coinbase.com"
ID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Money = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[0-9]+(?:\.[0-9]+)?$")]


class CoinbaseExchangeCredential(BaseModel):
    model_config = ConfigDict(title="Coinbase Exchange API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://exchange.coinbase.com/profile/api",
        "x-credential-instructions": "Paste your Coinbase Exchange API key, base64 secret and passphrase. These are Exchange credentials, not a CDP private key or Advanced Trade key. Enable View for account reads and connection verification, and Trade for order creation/cancellation. No transfer permission is needed. Requests go only to api.exchange.coinbase.com. Account reads prove access to the key's profile, not write permissions or access to every portfolio.",
    })
    credential_type: Literal["coinbase_exchange_api_key"] = Field("coinbase_exchange_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=1024, title="API key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, title="API secret", json_schema_extra={"ui:widget": "password", "ui:help": "Paste the base64 secret exactly as Coinbase Exchange issued it."})
    passphrase: str = Field(..., min_length=1, max_length=1024, title="Passphrase", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret", "passphrase", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste a credential without control characters")
        if info.field_name == "api_secret":
            try:
                decoded = base64.b64decode(value, validate=True)
                if not decoded:
                    raise ValueError()
            except Exception:
                raise ValueError("Paste the base64 secret issued by Coinbase Exchange") from None
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Input):
    limit: int = Field(100, ge=1, le=100, description="One page only; pass next_after to after to continue.")
    after: str | None = Field(None, min_length=1, max_length=2048)


class ListAccounts(Input):
    operation: Literal["list_accounts"] = "list_accounts"


class GetAccount(Input):
    operation: Literal["get_account"] = "get_account"
    account_id: ID


class ListHolds(Page):
    operation: Literal["list_holds"] = "list_holds"
    account_id: ID


class ListLedger(Page):
    operation: Literal["list_ledger"] = "list_ledger"
    account_id: ID
    start_date: str | None = Field(None, description="Inclusive date or RFC3339 timestamp.")
    end_date: str | None = Field(None, description="Inclusive date or RFC3339 timestamp.")


class ListOrders(Page):
    operation: Literal["list_orders"] = "list_orders"
    product_id: ID | None = None
    status: Literal["open", "pending", "rejected", "done", "active", "received", "all"] = "open"


class GetOrder(Input):
    operation: Literal["get_order"] = "get_order"
    order_id: ID


class CreateOrder(Input):
    """Place a limit order. An accepted order does not mean it has filled."""
    operation: Literal["create_order"] = "create_order"
    product_id: ID
    side: Literal["buy", "sell"]
    price: Money
    size: Money
    client_oid: str = Field(..., pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", description="Your unique UUID for reconciling an uncertain order outcome before retrying.")
    post_only: bool = False

    @field_validator("price", "size")
    @classmethod
    def positive(cls, value):
        if Decimal(value) <= 0:
            raise ValueError("Price and size must be positive decimal strings")
        return value


class CancelOrder(Input):
    """Cancel one open order; fills may race with cancellation."""
    operation: Literal["cancel_order"] = "cancel_order"
    order_id: ID
    product_id: ID | None = None


class ListFills(Page):
    operation: Literal["list_fills"] = "list_fills"
    product_id: ID = Field(..., description="Product to reconcile, for example BTC-USD.")
    order_id: ID | None = None


class GetFees(Input):
    operation: Literal["get_fees"] = "get_fees"


class ListProducts(Input):
    operation: Literal["list_products"] = "list_products"


class Product(Input):
    product_id: ID


class GetProduct(Product):
    operation: Literal["get_product"] = "get_product"


class GetTicker(Product):
    operation: Literal["get_ticker"] = "get_ticker"


class GetStats(Product):
    operation: Literal["get_stats"] = "get_stats"


class GetOrderBook(Product):
    operation: Literal["get_order_book"] = "get_order_book"
    level: Literal[1, 2] = Field(1, description="Level 1 best bid/ask; level 2 aggregated book.")


class ListCurrencies(Input):
    operation: Literal["list_currencies"] = "list_currencies"


class GetCurrency(Input):
    operation: Literal["get_currency"] = "get_currency"
    currency_id: ID


class ListProfiles(Input):
    operation: Literal["list_profiles"] = "list_profiles"
    active: bool | None = None


class GetProfile(Input):
    operation: Literal["get_profile"] = "get_profile"
    profile_id: ID


class ListPaymentMethods(Input):
    operation: Literal["list_payment_methods"] = "list_payment_methods"


CoinbaseConfig = Annotated[Union[ListAccounts, GetAccount, ListHolds, ListLedger, ListOrders,
    GetOrder, CreateOrder, CancelOrder, ListFills, GetFees, ListProducts, GetProduct,
    GetTicker, GetStats, GetOrderBook, ListCurrencies, GetCurrency, ListProfiles,
    GetProfile, ListPaymentMethods], Field(discriminator="operation")]


class CoinbaseFullConfig(NodeConfig[CoinbaseConfig, CoinbaseExchangeCredential]):
    pass


# Fixed route table: every operation corresponds to one published Exchange operation.
ROUTES = {
    "list_accounts": ("GET", "/accounts"),
    "get_account": ("GET", "/accounts/{account_id}"),
    "list_holds": ("GET", "/accounts/{account_id}/holds"),
    "list_ledger": ("GET", "/accounts/{account_id}/ledger"),
    "list_orders": ("GET", "/orders"),
    "get_order": ("GET", "/orders/{order_id}"),
    "create_order": ("POST", "/orders"),
    "cancel_order": ("DELETE", "/orders/{order_id}"),
    "list_fills": ("GET", "/fills"),
    "get_fees": ("GET", "/fees"),
    "list_products": ("GET", "/products"),
    "get_product": ("GET", "/products/{product_id}"),
    "get_ticker": ("GET", "/products/{product_id}/ticker"),
    "get_stats": ("GET", "/products/{product_id}/stats"),
    "get_order_book": ("GET", "/products/{product_id}/book"),
    "list_currencies": ("GET", "/currencies"),
    "get_currency": ("GET", "/currencies/{currency_id}"),
    "list_profiles": ("GET", "/profiles"),
    "get_profile": ("GET", "/profiles/{profile_id}"),
    "list_payment_methods": ("GET", "/payment-methods"),
}
LISTS = {"list_accounts", "list_holds", "list_ledger", "list_orders", "list_fills",
         "list_products", "list_currencies", "list_profiles", "list_payment_methods"}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {_redact(k, secrets): _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    return value


class CoinbaseNode(WorkflowNode):
    integration_type = "automation-coinbase"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="Coinbase Exchange trading accounts")

    @classmethod
    def get_config_model(cls):
        return CoinbaseFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Coinbase Exchange API key")
        op, cred = self.config.config, self.config.credentials
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in list(values):
            marker = "{" + key + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(key)), safe=""))
        body = ""
        if method == "POST":
            if op.operation == "create_order":
                values["type"] = "limit"
            body = json.dumps(values, separators=(",", ":"), ensure_ascii=True)
        elif values:
            query = {k: "true" if v is True else "false" if v is False else v for k, v in values.items()}
            path += "?" + urlencode(query)
        timestamp = str(time.time())
        signature = base64.b64encode(hmac.new(base64.b64decode(cred.api_secret, validate=True),
            (timestamp + method + path + body).encode(), hashlib.sha256).digest()).decode()
        secrets = (cred.api_key, cred.api_secret, cred.passphrase, signature)
        headers = {"CB-ACCESS-KEY": cred.api_key, "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp, "CB-ACCESS-PASSPHRASE": cred.passphrase,
            "Accept": "application/json", "Content-Type": "application/json"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers, content=body.encode() if body else None)
        except httpx.RequestError:
            raise ValueError("Coinbase Exchange request did not complete; a write outcome is unknown. Reconcile orders using client_oid before retrying.") from None
        if not 200 <= response.status_code < 300:
            try:
                message = response.json().get("message", "Request rejected")
                message = message if isinstance(message, str) else "Request rejected"
            except Exception:
                message = "Request rejected"
            raise ValueError(_redact(f"Coinbase Exchange HTTP {response.status_code}: {message[:1000]}", secrets))
        if len(response.content) > 5_000_000 or response.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            raise ValueError("Coinbase Exchange returned an unexpected response; reconcile any write before retrying")
        data = response.json()
        expected = list if op.operation in LISTS else str if op.operation == "cancel_order" else dict
        if (not isinstance(data, expected) or isinstance(data, dict) and ("message" in data or "errors" in data)
                or isinstance(data, list) and any(not isinstance(row, dict) for row in data)):
            raise ValueError("Coinbase Exchange returned an unexpected JSON shape; reconcile any write before retrying")
        if op.operation == "list_accounts" and any(
            any(not isinstance(row.get(key), str) or not row[key] for key in ("id", "currency"))
            for row in data
        ):
            raise ValueError("Coinbase Exchange returned incomplete account identity data")
        result = {"status": "success", "data": data, "operation": op.operation}
        if isinstance(op, Page):
            following = response.headers.get("cb-after")
            if following and following == op.after:
                raise ValueError("Coinbase Exchange returned a nonadvancing cursor")
            result.update(next_after=following, next_before=response.headers.get("cb-before"), page_only=True)
        if method != "GET":
            result["acknowledged"] = True
            result["execution_verified"] = False
        result = _redact(result, secrets)
        await self.emit(result)
        return result
