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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
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


class CoinbasePollConfig(PollTriggerConfigBase):
    lookback_hours: int = Field(24, ge=1, le=168, description=(
        "Poll this many recent hours. First poll records existing items without firing. "
        "Up to 2,000 items per poll; choose a smaller window for busy accounts. "
        "Events older than this window after a pause cannot be recovered."))


class OnNewOrder(CoinbasePollConfig):
    operation: Literal["on_new_order"] = Field("on_new_order", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Order"})
    product_id: ID | None = Field(None, description="Watch one product, or all products when empty.")


class OnNewFill(CoinbasePollConfig):
    operation: Literal["on_new_fill"] = Field("on_new_fill", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Fill"})
    product_id: ID = Field(..., description="Product to watch, for example BTC-USD.")


class OnNewLedgerEntry(CoinbasePollConfig):
    operation: Literal["on_new_ledger_entry"] = Field("on_new_ledger_entry", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Account Activity"})
    account_id: ID = Field(..., description="Trading account whose trades, transfers and fees to watch.")


CoinbaseConfig = Annotated[Union[ListAccounts, GetAccount, ListHolds, ListLedger, ListOrders,
    GetOrder, CreateOrder, CancelOrder, ListFills, GetFees, ListProducts, GetProduct,
    GetTicker, GetStats, GetOrderBook, ListCurrencies, GetCurrency, ListProfiles,
    GetProfile, ListPaymentMethods, OnNewOrder, OnNewFill, OnNewLedgerEntry], Field(discriminator="operation")]


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
        for key in list(value):
            cleaned_key = _redact(key, secrets)
            cleaned_value = _redact(value[key], secrets)
            if cleaned_key != key:
                del value[key]
            value[cleaned_key] = cleaned_value
        return value
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    return value


class CoinbaseNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-coinbase"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="Coinbase Exchange trading accounts")

    @classmethod
    def get_config_model(cls):
        return CoinbaseFullConfig

    async def _request(self, method, path, values, expected):
        cred = self.config.credentials
        body = ""
        if method == "POST":
            if path == "/orders":
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
        if (not isinstance(data, expected) or isinstance(data, dict) and ("message" in data or "errors" in data)
                or isinstance(data, list) and any(not isinstance(row, dict) for row in data)):
            raise ValueError("Coinbase Exchange returned an unexpected JSON shape; reconcile any write before retrying")
        return _redact(data, secrets), _redact(dict(response.headers), secrets)

    async def _poll(self, op):
        # All three routes support start_date in the pinned Exchange OpenAPI 1.0.
        since = (datetime.now(timezone.utc) - timedelta(hours=op.lookback_hours)).isoformat()
        values = {"limit": 100, "start_date": since}
        if isinstance(op, OnNewOrder):
            path = "/orders"
            values.update(status="all", sortedBy="created_at", sorting="desc")
            if op.product_id:
                values["product_id"] = op.product_id
        elif isinstance(op, OnNewFill):
            path = "/fills"
            values["product_id"] = op.product_id
        else:
            path = "/accounts/" + quote(op.account_id, safe="") + "/ledger"
        items, cursors = [], set()
        for _ in range(20):
            data, headers = await self._request("GET", path, values, list)
            for row in data:
                key = "trade_id" if isinstance(op, OnNewFill) else "id"
                if (row.get(key) is None or not str(row[key]) or not row.get("created_at")
                        or isinstance(op, OnNewFill) and not row.get("order_id")):
                    raise ValueError("Coinbase Exchange returned incomplete activity identity data")
            items.extend(data)
            following = headers.get("cb-after")
            if not following or not data:
                break
            if following in cursors:
                raise ValueError("Coinbase Exchange returned a nonadvancing activity cursor")
            cursors.add(following)
            values["after"] = following
        else:
            raise ValueError("More than 2,000 Coinbase activity items; reduce the lookback window or narrow the product")

        def identity(row):
            if isinstance(op, OnNewFill):
                return str(row["order_id"]) + ":" + str(row["trade_id"])
            return str(row["id"])

        # API pages can overlap while trading continues. Dedup within this poll too.
        unique = {identity(row): row for row in items}
        fresh = await self._filter_unseen(list(unique.values()), identity)
        result = {"status": "success", "operation": op.operation, "data": fresh,
                  "new_item_count": len(fresh)}
        if isinstance(op, OnNewLedgerEntry):
            result["account_id"] = op.account_id
        await self.emit(result)
        return result

    @classmethod
    def resolve_agent_event(cls, output):
        operation = output.get("operation")
        labels = {"on_new_order": "new order", "on_new_fill": "new fill",
                  "on_new_ledger_entry": "new account activity"}
        if operation not in labels:
            return super().resolve_agent_event(output)
        rows = output.get("data", [])
        if not rows:
            return None
        lines = []
        for row in rows[:20]:
            if operation == "on_new_ledger_entry":
                lines.append(f"- Account {output.get('account_id')}: {row.get('type')} "
                             f"{row.get('amount')}; balance {row.get('balance')}; "
                             f"entry {row.get('id')}, at {row.get('created_at')}; "
                             f"details {json.dumps(row.get('details', {}))}")
            else:
                identifier = (f"fill {row.get('trade_id')}, order {row.get('order_id')}"
                              if operation == "on_new_fill" else f"order {row.get('id')}, status {row.get('status')}")
                lines.append(f"- Profile {row.get('profile_id')}: {row.get('side')} "
                             f"{row.get('size', 'unspecified size')} {row.get('product_id')} "
                             f"at {row.get('price', 'market price')}; {identifier}; at {row.get('created_at')}")
        if len(rows) > 20:
            lines.append(f"- {len(rows) - 20} more items are in the trigger output.")
        return {"text": f"Coinbase Exchange: {len(rows)} {labels[operation]} item(s):\n" + "\n".join(lines),
                "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Coinbase Exchange API key")
        op = self.config.config
        if isinstance(op, CoinbasePollConfig):
            return await self._poll(op)
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in list(values):
            marker = "{" + key + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(key)), safe=""))
        expected = list if op.operation in LISTS else str if op.operation == "cancel_order" else dict
        data, headers = await self._request(method, path, values, expected)
        if op.operation == "list_accounts" and any(
            any(not isinstance(row.get(key), str) or not row[key] for key in ("id", "currency"))
            for row in data
        ):
            raise ValueError("Coinbase Exchange returned incomplete account identity data")
        result = {"status": "success", "data": data, "operation": op.operation}
        if isinstance(op, Page):
            following = headers.get("cb-after")
            if following and following == op.after:
                raise ValueError("Coinbase Exchange returned a nonadvancing cursor")
            result.update(next_after=following, next_before=headers.get("cb-before"), page_only=True)
        if method != "GET":
            result["acknowledged"] = True
            result["execution_verified"] = False
        await self.emit(result)
        return result
