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


Operation = Annotated[Union[ListOrders, GetOrder, ListTrades, GetBalanceAllowance, ListNotifications, GetClosedOnlyMode, CancelOrder, CancelOrders, CancelAllOrders, CancelMarketOrders, MarkNotificationsRead, GetOrderBook, GetPrice, GetMidpoint, GetSpread, GetLastTradePrice, GetFeeRate, GetTickSize, GetNegRisk, GetPriceHistory], Field(discriminator="operation")]


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
        return {k: redact(v, credential) for k, v in value.items()}
    elif isinstance(value, list):
        return [redact(v, credential) for v in value]
    return value


class PolymarketNode(WorkflowNode):
    integration_type = "automation-polymarket"
    connection_evidence = ConnectionEvidence(noun="open orders", operation="list_orders", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return PolymarketConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Polymarket CLOB API credentials")
        op = self.config.config
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
        if not 200 <= response.status_code < 300 or (isinstance(payload, dict) and (payload.get("error") or payload.get("success") is False)):
            return {"status": "error", "http_status": response.status_code, "error": payload}
        if op.operation in {"list_orders", "list_trades"}:
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Polymarket returned an invalid page")
            cursor = payload.get("next_cursor")
            return {"status": "success", "data": payload["data"], "next_cursor": cursor,
                "has_more": cursor not in (None, "", "LTE="), "count": payload.get("count"), "limit": payload.get("limit")}
        # Keep cancellation's canceled/not_canceled map: an HTTP 200 can include refusals.
        return {"status": "success", "data": payload}
