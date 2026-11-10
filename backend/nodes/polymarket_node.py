"""Polymarket CLOB account management and market data (published OpenAPI 1.0.0).

L2 signing follows Polymarket/py-clob-client signing/hmac.py. Existing CLOB
credentials suffice; no wallet private key, OAuth, or order signing is collected.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://clob.polymarket.com"


class PolymarketAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Polymarket CLOB API Key", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.polymarket.com/trading/wallets-auth",
            "x-credential-instructions": "Paste your existing CLOB API key, secret and passphrase, and the signer wallet address used to create them. These are CLOB L2 credentials, not Builder or Relayer keys. Use the official SDK to create or derive them with your wallet first. Never paste a wallet private key. NoClick signs account requests locally with HMAC-SHA256. Public market reads do not verify a credential."})
    credential_type: Literal["polymarket_api_key"] = Field("polymarket_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., title="API secret", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    api_passphrase: str = Field(..., title="API passphrase", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    wallet_address: str = Field(..., title="Signer wallet address", pattern=r"^0x[a-fA-F0-9]{40}$")

    @field_validator("api_key", "api_secret", "api_passphrase", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the credential without whitespace")
        if info.field_name == "api_secret":
            try:
                if not base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True):
                    raise ValueError()
            except (ValueError, binascii.Error):
                raise ValueError("Paste the base64 API secret issued by Polymarket") from None
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    id: str | None = None
    market: str | None = None
    asset_id: str | None = None
    next_cursor: str | None = Field(None, description="Continue with the provider's next_cursor. One page per run; LTE= marks the end.")


class ListOrders(_Page):
    """Read one page of this authenticated account's open orders."""
    operation: Literal["list_orders"] = "list_orders"


class GetOrder(_Input):
    operation: Literal["get_order"] = "get_order"
    order_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")


class ListTrades(_Page):
    operation: Literal["list_trades"] = "list_trades"
    maker_address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    market: str | None = Field(None, pattern=r"^0x[a-fA-F0-9]{64}$")
    before: str | None = Field(None, pattern=r"^\d+$")
    after: str | None = Field(None, pattern=r"^\d+$")


class OnNewTrade(PollTriggerConfigBase):
    """Watch new account trades; existing trades are baselined when enabled.

    GET /data/trades in the published CLOB OpenAPI supports the after filter.
    Narrow a busy account by market, token, or an earliest match timestamp.
    """
    operation: Literal["on_new_trade"] = Field("on_new_trade", title="On New Trade", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Trade", "ui:hidden": True,
    })
    maker_address: str = Field(..., title="Maker wallet address", pattern=r"^0x[a-fA-F0-9]{40}$")
    market: str | None = Field(None, title="Market condition ID", pattern=r"^0x[a-fA-F0-9]{64}$")
    asset_id: str | None = Field(None, title="Outcome token ID")
    after: str | None = Field(None, title="Trades after", pattern=r"^\d+$",
        description="Optional earliest match time as Unix seconds. Narrow this window for high-volume accounts.")


class GetBalanceAllowance(_Input):
    operation: Literal["get_balance_allowance"] = "get_balance_allowance"
    asset_type: Literal["COLLATERAL", "CONDITIONAL"] = "COLLATERAL"
    token_id: str | None = None
    signature_type: Literal[0, 1, 2, 3] = Field(0, description="0 EOA, 1 proxy, 2 Safe, 3 deposit wallet")

    @model_validator(mode="after")
    def conditional_token(self):
        if self.asset_type == "CONDITIONAL" and not self.token_id:
            raise ValueError("A conditional asset requires token_id")
        return self


class ListNotifications(_Input):
    operation: Literal["list_notifications"] = "list_notifications"
    signature_type: Literal[0, 1, 2, 3] = 0


class GetClosedOnlyMode(_Input):
    operation: Literal["get_closed_only_mode"] = "get_closed_only_mode"


class CancelOrder(_Input):
    operation: Literal["cancel_order"] = "cancel_order"
    order_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")


class CancelOrders(_Input):
    operation: Literal["cancel_orders"] = "cancel_orders"
    order_ids: list[str] = Field(..., min_length=1, max_length=1000, description="Order hashes to cancel; inspect not_canceled for failures.")


class CancelAllOrders(_Input):
    """Cancel every open order for this account; settled fills remain unchanged."""
    operation: Literal["cancel_all_orders"] = "cancel_all_orders"


class CancelMarketOrders(_Input):
    operation: Literal["cancel_market_orders"] = "cancel_market_orders"
    market: str = Field(..., min_length=1)
    asset_id: str = Field(..., min_length=1)


class MarkNotificationsRead(_Input):
    operation: Literal["mark_notifications_read"] = "mark_notifications_read"
    ids: str = Field(..., pattern=r"^\d+(,\d+)*$", description="Comma-separated notification IDs")


class _Token(_Input):
    token_id: str = Field(..., min_length=1, max_length=256, description="CLOB outcome token (asset) ID")


class GetOrderBook(_Token):
    operation: Literal["get_order_book"] = "get_order_book"


class GetPrice(_Token):
    operation: Literal["get_price"] = "get_price"
    side: Literal["BUY", "SELL"] = "BUY"


class GetMidpoint(_Token):
    operation: Literal["get_midpoint"] = "get_midpoint"


class GetSpread(_Token):
    operation: Literal["get_spread"] = "get_spread"


class GetLastTradePrice(_Token):
    operation: Literal["get_last_trade_price"] = "get_last_trade_price"


class GetFeeRate(_Token):
    operation: Literal["get_fee_rate"] = "get_fee_rate"


class GetTickSize(_Token):
    operation: Literal["get_tick_size"] = "get_tick_size"


class GetNegRisk(_Token):
    operation: Literal["get_neg_risk"] = "get_neg_risk"


class GetPriceHistory(_Input):
    operation: Literal["get_price_history"] = "get_price_history"
    market: str = Field(..., min_length=1, description="Outcome token (asset) ID, not condition ID")
    startTs: float | None = None
    endTs: float | None = None
    interval: Literal["max", "all", "1m", "1w", "1d", "6h", "1h"] = "1d"
    fidelity: int | None = Field(None, ge=1)


Operation = Annotated[Union[ListOrders, GetOrder, ListTrades, GetBalanceAllowance, ListNotifications, GetClosedOnlyMode, CancelOrder, CancelOrders, CancelAllOrders, CancelMarketOrders, MarkNotificationsRead, GetOrderBook, GetPrice, GetMidpoint, GetSpread, GetLastTradePrice, GetFeeRate, GetTickSize, GetNegRisk, GetPriceHistory, OnNewTrade], Field(discriminator="operation")]


class PolymarketConfig(NodeConfig[Operation, PolymarketAPIKeyCredential]):
    pass


# One provider operation per node operation. Public requests never carry credentials.
ROUTES = {
    "list_orders": ("GET", "/data/orders", True),
    "get_order": ("GET", "/data/order/{order_id}", True),
    "list_trades": ("GET", "/data/trades", True),
    "get_balance_allowance": ("GET", "/balance-allowance", True),
    "list_notifications": ("GET", "/notifications", True),
    "get_closed_only_mode": ("GET", "/auth/ban-status/closed-only", True),
    "cancel_order": ("DELETE", "/order", True),
    "cancel_orders": ("DELETE", "/orders", True),
    "cancel_all_orders": ("DELETE", "/cancel-all", True),
    "cancel_market_orders": ("DELETE", "/cancel-market-orders", True),
    "mark_notifications_read": ("DELETE", "/notifications", True),
    "get_price_history": ("GET", "/prices-history", False),
    "get_order_book": ("GET", "/book", False),
    "get_price": ("GET", "/price", False),
    "get_midpoint": ("GET", "/midpoint", False),
    "get_spread": ("GET", "/spread", False),
    "get_last_trade_price": ("GET", "/last-trade-price", False),
    "get_fee_rate": ("GET", "/fee-rate", False),
    "get_tick_size": ("GET", "/tick-size", False),
    "get_neg_risk": ("GET", "/neg-risk", False),
}


def sign_headers(credential, method, path, body, timestamp):
    # Sign only the path, excluding query parameters, as the official SDK does.
    secret = credential.api_secret
    key = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
    message = timestamp + method + path + (body or "")
    signature = base64.urlsafe_b64encode(hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()).decode("ascii")
    return {"POLY_ADDRESS": credential.wallet_address, "POLY_API_KEY": credential.api_key,
        "POLY_PASSPHRASE": credential.api_passphrase, "POLY_TIMESTAMP": timestamp, "POLY_SIGNATURE": signature}


def redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.api_key, credential.api_secret, credential.api_passphrase):
            value = value.replace(secret, "[redacted]")
    elif isinstance(value, dict):
        # Preserve unchanged provider structures; copy only when a secret was removed.
        cleaned = {k: redact(v, credential) for k, v in value.items()}
        return value if cleaned == value else cleaned
    elif isinstance(value, list):
        cleaned = [redact(v, credential) for v in value]
        return value if cleaned == value else cleaned
    return value


class PolymarketNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-polymarket"
    connection_evidence = ConnectionEvidence(noun="open orders", operation="list_orders", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return PolymarketConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_trade":
            return bool(output.get("new_trade_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        trades = output.get("trades") if isinstance(output, dict) else None
        if not isinstance(trades, list):
            return super().resolve_agent_event(output)
        if not trades:
            return None
        lines = [
            f"- Wallet {trade.get('maker_address')}: {trade.get('side')} {trade.get('size')} "
            f"{trade.get('outcome')} at {trade.get('price')}; market {trade.get('market')}, "
            f"token {trade.get('asset_id')}, trade {trade.get('id')}, "
            f"taker order {trade.get('taker_order_id')}, status {trade.get('status')}"
            for trade in trades[:10]
        ]
        if len(trades) > 10:
            lines.append(f"- … and {len(trades) - 10} more")
        return {"text": f"Polymarket: {len(trades)} new trade(s):\n" + "\n".join(lines),
            "conversation_key": None}

    async def execute(self, inputs):
        op = self.config.config
        if not isinstance(op, OnNewTrade):
            return await self._execute_operation(op)
        trades = []
        cursors = set()
        cursor = None
        for _ in range(20):
            page = await self._execute_operation(ListTrades(
                maker_address=op.maker_address, market=op.market, asset_id=op.asset_id,
                after=op.after, next_cursor=cursor,
            ))
            if page.get("status") == "error":
                return page
            trades.extend(page["data"])
            if len(trades) > 10000:
                raise ValueError("Too many Polymarket trades; narrow the market, token, or Trades after filter")
            # CLOB cursors encode offsets and may still name a next offset on
            # a short final page (as in the published trades example). A page
            # below the server's limit has exhausted the current result set.
            count, limit = page.get("count"), page.get("limit")
            short_page = (isinstance(count, int) and isinstance(limit, int)
                and limit > 0 and 0 <= count < limit)
            if not page["has_more"] or short_page:
                break
            cursor = page["next_cursor"]
            if cursor in cursors:
                raise ValueError("Polymarket repeated a trade page cursor")
            cursors.add(cursor)
        else:
            raise ValueError("Too many Polymarket trade pages; narrow the market, token, or Trades after filter")
        if any(not isinstance(trade, dict) or not trade.get("id") for trade in trades):
            raise ValueError("Polymarket returned a trade without an ID")
        # A page boundary can overlap while trades arrive; emit each trade once.
        trades = list({str(trade["id"]): trade for trade in trades}.values())
        fresh = await self._filter_unseen(trades, lambda trade: str(trade["id"]))
        return {"status": "success", "trades": fresh, "new_trade_count": len(fresh)}

    async def _execute_operation(self, op):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Polymarket CLOB API credentials")
        method, path, authenticated = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        body = None
        if op.operation == "get_order":
            path = path.replace("{order_id}", quote(values.pop("order_id"), safe=""))
        elif op.operation == "cancel_order":
            body, values = {"orderID": op.order_id}, {}
        elif op.operation == "cancel_orders":
            body, values = op.order_ids, {}
        elif op.operation == "cancel_market_orders":
            body, values = values, {}
        serialized = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body is not None else None
        headers = {"Accept": "application/json"}
        if serialized is not None:
            headers["Content-Type"] = "application/json"
        if authenticated:
            headers.update(sign_headers(credential, method, path, serialized, str(int(time.time()))))
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=values, headers=headers, content=serialized)
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "Polymarket returned a non-JSON response"}
        payload = redact(payload, credential)
        if not 200 <= response.status_code < 300 or (isinstance(payload, dict) and (("error" in payload and payload["error"]) or ("success" in payload and payload["success"] is False))):
            return {"status": "error", "http_status": response.status_code, "error": payload}
        if op.operation in {"list_orders", "list_trades"}:
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Polymarket returned an invalid page")
            cursor = payload.get("next_cursor")
            return {"status": "success", "data": payload["data"], "next_cursor": cursor,
                "has_more": cursor not in (None, "", "LTE="), "count": payload.get("count"), "limit": payload.get("limit")}
        # Keep cancellation's canceled/not_canceled map: an HTTP 200 can include refusals.
        return {"status": "success", "data": payload}
