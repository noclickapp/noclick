"""Alpaca Trading API v2, pinned to the provider's 2.0.1 OpenAPI contract.

Each operation issues one request. Writes acknowledge API acceptance only;
order fills, replacements and cancellation completion must be checked later.
https://docs.alpaca.markets/us/openapi/trading-api.json
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, AfterValidator, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


def _positive(value: str) -> str:
    if not re.fullmatch(r"\d+(?:\.\d{1,9})?", value) or Decimal(value) <= 0:
        raise ValueError("Use a positive decimal with at most nine decimal places")
    return value


Positive = Annotated[str, Field(min_length=1, max_length=32), AfterValidator(_positive)]
Symbol = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9./_-]*$")]
TimeInForce = Literal["day", "gtc", "opg", "cls", "ioc", "fok"]


class AlpacaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Alpaca API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.alpaca.markets/",
        "x-credential-instructions": "In the Alpaca Trading Dashboard, generate an API key and paste its key ID and secret key. Choose the environment matching those keys: paper and live keys are different. Paper is the default. Live writes can place real trades. NoClick verifies the connection by reading your account; this does not prove permission to trade."})
    credential_type: Literal["alpaca_api_key"] = Field("alpaca_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key ID", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, title="API secret key", json_schema_extra={"ui:widget": "password"})
    environment: Literal["paper", "live"] = Field("paper", description="Use the environment where these keys were generated.")

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Alpaca key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the key without spaces or an HTTP header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetAccount(_Input):
    operation: Literal["get_account"] = "get_account"


class GetAccountConfig(_Input):
    operation: Literal["get_account_config"] = "get_account_config"


class UpdateAccountConfig(_Input):
    operation: Literal["update_account_config"] = "update_account_config"
    trade_confirm_email: Literal["all", "none"] | None = None
    suspend_trade: StrictBool | None = None
    no_shorting: StrictBool | None = None
    fractional_trading: StrictBool | None = None
    max_margin_multiplier: Literal["1", "2", "4"] | None = None
    disable_overnight_trading: StrictBool | None = None

    @model_validator(mode="after")
    def changed(self):
        if not self.model_dump(exclude_none=True, exclude={"operation"}):
            raise ValueError("Choose at least one account setting to change")
        return self


class GetPortfolioHistory(_Input):
    operation: Literal["get_portfolio_history"] = "get_portfolio_history"
    period: str = Field("1M", pattern=r"^[1-9][0-9]*[DWMA]$")
    timeframe: Literal["1D", "1H", "15Min", "5Min", "1Min"] = "1D"
    intraday_reporting: Literal["market_hours", "extended_hours", "continuous"] | None = None
    pnl_reset: Literal["no_reset", "per_day"] | None = None


class ListActivities(_Input):
    """One activity page; pass the last activity ID as page_token for the next."""
    operation: Literal["list_activities"] = "list_activities"
    activity_types: str | None = Field(None, max_length=1000, description="Comma-separated activity types, for example FILL,DIV.")
    direction: Literal["asc", "desc"] = "desc"
    page_size: int = Field(100, ge=1, le=100)
    page_token: str | None = Field(None, min_length=1, max_length=256)
    after: str | None = None
    until: str | None = None


class ListAssets(_Input):
    operation: Literal["list_assets"] = "list_assets"
    status: Literal["active", "inactive"] | None = None
    asset_class: Literal["us_equity", "crypto", "us_option", "us_index"] | None = None
    exchange: str | None = Field(None, max_length=200)


class GetAsset(_Input):
    operation: Literal["get_asset"] = "get_asset"
    symbol_or_asset_id: Symbol


class GetCalendar(_Input):
    operation: Literal["get_calendar"] = "get_calendar"
    start: str | None = Field(None, description="First date, inclusive; Alpaca accepts YYYY-MM-DD.")
    end: str | None = Field(None, description="Last date, inclusive; Alpaca accepts YYYY-MM-DD.")
    date_type: Literal["TRADING", "SETTLEMENT"] | None = None


class GetClock(_Input):
    operation: Literal["get_clock"] = "get_clock"


class ListOrders(_Input):
    """One page, bounded by limit; use after/until or the order ID cursors to continue."""
    operation: Literal["list_orders"] = "list_orders"
    status: Literal["open", "closed", "all"] = "open"
    limit: int = Field(50, ge=1, le=500)
    after: str | None = None
    until: str | None = None
    direction: Literal["asc", "desc"] = "desc"
    nested: StrictBool = False
    symbols: str | None = Field(None, max_length=2000, description="Comma-separated symbols.")
    side: Literal["buy", "sell"] | None = None
    before_order_id: UUID | None = None
    after_order_id: UUID | None = None

    @model_validator(mode="after")
    def cursors(self):
        if (self.before_order_id and self.after_order_id) or ((self.before_order_id or self.after_order_id) and (self.after or self.until)):
            raise ValueError("Choose one order ID cursor, or timestamp bounds")
        return self


class CreateOrder(_Input):
    """Submit a single-leg order. Acceptance does not mean a fill; do not blindly retry."""
    operation: Literal["create_order"] = "create_order"
    symbol: Symbol
    side: Literal["buy", "sell"]
    type: Literal["market", "limit", "stop", "stop_limit", "trailing_stop"] = "market"
    time_in_force: TimeInForce = "day"
    qty: Positive | None = None
    notional: Positive | None = None
    limit_price: Positive | None = None
    stop_price: Positive | None = None
    trail_price: Positive | None = None
    trail_percent: Positive | None = None
    extended_hours: StrictBool = False
    client_order_id: str | None = Field(None, min_length=1, max_length=128, description="Unique client ID to find the order after an ambiguous timeout; reuse must be reconciled before retrying.")

    @model_validator(mode="after")
    def order_rules(self):
        if (self.qty is None) == (self.notional is None):
            raise ValueError("Provide exactly one of quantity or notional")
        if self.notional and (self.type != "market" or self.time_in_force != "day"):
            raise ValueError("Notional orders require market type and day time in force")
        if self.qty and Decimal(self.qty) % 1 and (self.type != "market" or self.time_in_force != "day"):
            raise ValueError("Fractional quantities require market type and day time in force")
        if (self.type in {"limit", "stop_limit"}) != (self.limit_price is not None):
            raise ValueError("Limit price is required only for limit and stop-limit orders")
        if (self.type in {"stop", "stop_limit"}) != (self.stop_price is not None):
            raise ValueError("Stop price is required only for stop and stop-limit orders")
        if self.type == "trailing_stop":
            if (self.trail_price is None) == (self.trail_percent is None):
                raise ValueError("Provide exactly one trailing price or percent")
        elif self.trail_price is not None or self.trail_percent is not None:
            raise ValueError("Trailing values require a trailing-stop order")
        if self.extended_hours and (self.type != "limit" or self.time_in_force not in {"day", "gtc"}):
            raise ValueError("Extended hours require a limit order with day or gtc")
        return self


class GetOrder(_Input):
    operation: Literal["get_order"] = "get_order"
    order_id: UUID
    nested: StrictBool = False


class ReplaceOrder(_Input):
    """Replacement request; inspect the returned order status for completion."""
    operation: Literal["replace_order"] = "replace_order"
    order_id: UUID
    qty: Positive | None = None
    limit_price: Positive | None = None
    stop_price: Positive | None = None
    trail: Positive | None = None
    time_in_force: TimeInForce | None = None
    client_order_id: str | None = Field(None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def patch_rules(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "order_id"}):
            raise ValueError("Choose at least one order field to replace")
        if self.qty and Decimal(self.qty) % 1:
            raise ValueError("Replacement quantity must be whole shares")
        return self


class CancelOrder(_Input):
    """Request cancellation; a 204 acknowledges the request, not final cancellation."""
    operation: Literal["cancel_order"] = "cancel_order"
    order_id: UUID


class GetOrderByClientID(_Input):
    operation: Literal["get_order_by_client_id"] = "get_order_by_client_id"
    client_order_id: str = Field(..., min_length=1, max_length=128)


class ListPositions(_Input):
    operation: Literal["list_positions"] = "list_positions"


class GetPosition(_Input):
    operation: Literal["get_position"] = "get_position"
    symbol_or_asset_id: Symbol


class ClosePosition(_Input):
    """Submit an order to close all or part of one position; filling is asynchronous."""
    operation: Literal["close_position"] = "close_position"
    symbol_or_asset_id: Symbol
    qty: Positive | None = None
    percentage: float | None = Field(None, gt=0, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def close_rules(self):
        if self.qty is not None and self.percentage is not None:
            raise ValueError("Choose quantity or percentage, not both; omit both to close the whole position")
        return self


class ListWatchlists(_Input):
    operation: Literal["list_watchlists"] = "list_watchlists"


class CreateWatchlist(_Input):
    operation: Literal["create_watchlist"] = "create_watchlist"
    name: str = Field(..., min_length=1, max_length=255)
    symbols: list[Symbol] | None = Field(None, max_length=1000)


class GetWatchlist(_Input):
    operation: Literal["get_watchlist"] = "get_watchlist"
    watchlist_id: UUID


class UpdateWatchlist(_Input):
    operation: Literal["update_watchlist"] = "update_watchlist"
    watchlist_id: UUID
    name: str | None = Field(None, min_length=1, max_length=255)
    symbols: list[Symbol] | None = Field(None, max_length=1000, description="Replaces the existing symbols; an empty list clears them.")

    @model_validator(mode="after")
    def patch_rules(self):
        if self.name is None and self.symbols is None:
            raise ValueError("Provide a name or a replacement symbol list")
        return self


class AddWatchlistAsset(_Input):
    operation: Literal["add_watchlist_asset"] = "add_watchlist_asset"
    watchlist_id: UUID
    symbol: Symbol


class RemoveWatchlistAsset(_Input):
    operation: Literal["remove_watchlist_asset"] = "remove_watchlist_asset"
    watchlist_id: UUID
    symbol: Symbol


class DeleteWatchlist(_Input):
    operation: Literal["delete_watchlist"] = "delete_watchlist"
    watchlist_id: UUID


class OnNewOrder(PollTriggerConfigBase):
    """New submissions, including orders already closed between polls; not status updates."""
    operation: Literal["on_new_order"] = Field("on_new_order", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Order",
    })
    symbols: str | None = Field(None, max_length=2000, description="Comma-separated symbols. Polls up to 10,000 orders; narrow this scope for larger histories.")
    side: Literal["buy", "sell"] | None = None


class OnNewActivity(PollTriggerConfigBase):
    """New fills, dividends, transfers and other account activities, deduplicated by ID."""
    operation: Literal["on_new_activity"] = Field("on_new_activity", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Account Activity",
    })
    activity_types: str | None = Field(None, max_length=1000, description="Comma-separated activity types, for example FILL,DIV. Use FILL to watch trade executions.")
    after: datetime | None = Field(None, description="Only activities created after this timestamp. Polls up to 2,000 activities; narrow this scope for larger histories.")


AlpacaConfig = Annotated[Union[
    GetAccount, GetAccountConfig, UpdateAccountConfig, GetPortfolioHistory,
    ListActivities, ListAssets, GetAsset, GetCalendar, GetClock, ListOrders,
    CreateOrder, GetOrder, ReplaceOrder, CancelOrder, GetOrderByClientID,
    ListPositions, GetPosition, ClosePosition, ListWatchlists, CreateWatchlist,
    GetWatchlist, UpdateWatchlist, AddWatchlistAsset, RemoveWatchlistAsset, DeleteWatchlist, OnNewOrder, OnNewActivity,
], Field(discriminator="operation")]


class AlpacaNodeConfig(NodeConfig[AlpacaConfig, AlpacaAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Exactly one published operation per workflow operation. No user-selected URLs.
REQUESTS = {
    "get_account": ("GET", "/v2/account"),
    "get_account_config": ("GET", "/v2/account/configurations"),
    "update_account_config": ("PATCH", "/v2/account/configurations"),
    "get_portfolio_history": ("GET", "/v2/account/portfolio/history"),
    "list_activities": ("GET", "/v2/account/activities"),
    "list_assets": ("GET", "/v2/assets"),
    "get_asset": ("GET", "/v2/assets/{symbol_or_asset_id}"),
    "get_calendar": ("GET", "/v2/calendar"),
    "get_clock": ("GET", "/v2/clock"),
    "list_orders": ("GET", "/v2/orders"),
    "create_order": ("POST", "/v2/orders"),
    "get_order": ("GET", "/v2/orders/{order_id}"),
    "replace_order": ("PATCH", "/v2/orders/{order_id}"),
    "cancel_order": ("DELETE", "/v2/orders/{order_id}"),
    "get_order_by_client_id": ("GET", "/v2/orders:by_client_order_id"),
    "list_positions": ("GET", "/v2/positions"),
    "get_position": ("GET", "/v2/positions/{symbol_or_asset_id}"),
    "close_position": ("DELETE", "/v2/positions/{symbol_or_asset_id}"),
    "list_watchlists": ("GET", "/v2/watchlists"),
    "create_watchlist": ("POST", "/v2/watchlists"),
    "get_watchlist": ("GET", "/v2/watchlists/{watchlist_id}"),
    "update_watchlist": ("PUT", "/v2/watchlists/{watchlist_id}"),
    "add_watchlist_asset": ("POST", "/v2/watchlists/{watchlist_id}"),
    "remove_watchlist_asset": ("DELETE", "/v2/watchlists/{watchlist_id}/{symbol}"),
    "delete_watchlist": ("DELETE", "/v2/watchlists/{watchlist_id}"),
}
LISTS = {"list_activities", "list_assets", "get_calendar", "list_orders", "list_positions", "list_watchlists"}


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.api_key, credential.api_secret):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    if isinstance(value, dict):
        return {_redact(k, credential): _redact(v, credential) for k, v in value.items()}
    return value


class AlpacaNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-alpaca"
    connection_evidence = ConnectionEvidence(noun="Alpaca account", identity_operation="get_account", identity_keys=("account_number", "id"))

    @classmethod
    def get_config_model(cls):
        return AlpacaNodeConfig

    async def _request(self, action, values):
        credential = self.config.credentials
        method, route = REQUESTS[action]
        for name in re.findall(r"\{([^}]+)\}", route):
            route = route.replace("{" + name + "}", quote(str(values.pop(name)), safe=""))
        base = "https://paper-api.alpaca.markets" if credential.environment == "paper" else "https://api.alpaca.markets"
        headers = {"APCA-API-KEY-ID": credential.api_key, "APCA-API-SECRET-KEY": credential.api_secret, "Accept": "application/json"}
        body = values if method in {"POST", "PUT", "PATCH"} else None
        params = None if body is not None else {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, base + route, headers=headers, params=params, **({"json": body} if body is not None else {}))
        except httpx.TransportError:
            # Never retry a possibly accepted trading request.
            raise ValueError("Alpaca transport failed; write outcome is unknown. Inspect the account or client order ID before retrying." if method != "GET" else "Alpaca could not be reached") from None
        if response.status_code not in ({204} if action in {"cancel_order", "delete_watchlist"} else {200}):
            try:
                message = response.json().get("message", "Alpaca request failed")
            except (ValueError, AttributeError):
                message = "Alpaca request failed"
            raise ValueError(_redact(f"Alpaca HTTP {response.status_code}: {str(message)[:1000]}", credential))
        data = None
        if response.status_code != 204:
            if response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                raise ValueError("Alpaca returned an unexpected content type; inspect write outcome before retrying")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Alpaca returned invalid JSON; inspect write outcome before retrying") from None
            if action in LISTS:
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError("Alpaca returned an unexpected list response")
            elif not isinstance(data, dict) or not data:
                raise ValueError("Alpaca returned an unexpected object response; inspect write outcome before retrying")
        return data, response.status_code, method

    async def _poll(self, op):
        orders = isinstance(op, OnNewOrder)
        action = "list_orders" if orders else "list_activities"
        size = 500 if orders else 100
        params = {"direction": "desc", "limit" if orders else "page_size": size}
        if orders:
            params.update(status="all", nested=False)
            for name in ("symbols", "side"):
                if getattr(op, name) is not None:
                    params[name] = getattr(op, name)
        else:
            if op.activity_types is not None:
                params["activity_types"] = op.activity_types
            if op.after is not None:
                params["after"] = op.after.isoformat()
        items = []
        ids = set()
        for _ in range(20):
            page, _, _ = await self._request(action, dict(params))
            for item in page:
                identifier = item.get("id")
                if not isinstance(identifier, str) or not identifier or identifier in ids:
                    raise ValueError("Alpaca poll returned a missing or repeated ID; baseline was not changed")
                ids.add(identifier)
                items.append(item)
            if len(page) < size:
                break
            params["before_order_id" if orders else "page_token"] = page[-1]["id"]
        else:
            raise ValueError("Alpaca poll history exceeds its page bound; narrow the trigger scope before arming")
        # Baseline only after every page succeeds. Oldest first for agent/workflow consumption.
        fresh = await self._filter_unseen(list(reversed(items)), lambda item: item["id"])
        output = {"status": "success", "operation": op.operation, "data": _redact(fresh, self.config.credentials), "new_item_count": len(fresh)}
        await self.emit(output)
        return output

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in {"on_new_order", "on_new_activity"}:
            return super().resolve_agent_event(output)
        items = output.get("data") or []
        if not items:
            return None
        orders = output["operation"] == "on_new_order"
        title = "New Alpaca orders" if orders else "New Alpaca account activities"
        lines = [f"{title} in the connected trading account: {len(items)}"]
        for item in items:
            facts = [f"{name}={item[name]}" for name in (
                ("id", "client_order_id", "symbol", "side", "qty", "notional", "status", "submitted_at") if orders else
                ("id", "activity_type", "symbol", "side", "qty", "price", "net_amount", "currency", "transaction_time", "created_at", "date", "order_id")
            ) if item.get(name) is not None]
            lines.append("; ".join(facts))
        if orders:
            lines.append("Use get_order with order_id=id to check the current order; a submission is not a confirmed fill.")
        else:
            lines.append("Use get_order with order_id when present to inspect the related order.")
        return {"text": "\n".join(lines), "title": title}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Alpaca API key ID and secret")
        credential = self.config.credentials
        op = self.config.config
        if isinstance(op, (OnNewOrder, OnNewActivity)):
            return await self._poll(op)
        action = op.operation
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        data, http_status, method = await self._request(action, values)
        output = {"status": "success", "operation": action, "data": _redact(data, credential), "http_status": http_status}
        if method != "GET":
            output["request_accepted"] = True
            if action in {"create_order", "replace_order", "close_position", "cancel_order"}:
                output["execution_verified"] = False
        if action == "list_orders":
            output.update(page_limit=op.limit, limit_reached=len(data) >= op.limit)
        elif action == "list_activities":
            output.update(page_limit=op.page_size, limit_reached=len(data) >= op.page_size,
                          next_page_token=data[-1].get("id") if len(data) >= op.page_size and data else None)
        await self.emit(output)
        return output
