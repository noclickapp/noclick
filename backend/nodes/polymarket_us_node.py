"""Polymarket US public data and signed trading/portfolio API.

Contract: https://docs.polymarket.us/api-reference/oapi-schemas/orders-schema.json
Authentication: https://docs.polymarket.us/api-reference/authentication
List operations return one provider page, preserving cursor/offset information.
"""
from __future__ import annotations

import base64
import binascii
import time
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Union
from urllib.parse import quote

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class PolymarketUSAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Polymarket US API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://polymarket.us/developer",
            "x-credential-instructions": "Create an API key in the Polymarket US developer portal after account identity verification. Paste its Key ID and Secret Key. The secret signs requests with Ed25519; it is never sent. This key can place and cancel trades. Account balances verify the connection.",
        })
    credential_type: Literal["polymarket_us_api_key"] = Field("polymarket_us_api_key", json_schema_extra={"ui:hidden": True})
    key_id: str = Field(..., min_length=1, max_length=256, title="Key ID", json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., min_length=1, max_length=256, title="Secret key", json_schema_extra={"ui:widget": "password"})

    @field_validator("key_id", "secret_key")
    @classmethod
    def trim(cls, value):
        value = value.strip()
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the key without whitespace")
        return value

    @field_validator("secret_key")
    @classmethod
    def signing_key(cls, value):
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Paste the base64 Secret Key from the developer portal") from None
        if len(raw) not in (32, 64):
            raise ValueError("Secret Key must encode a 32-byte seed or 64-byte Ed25519 private key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

class CreateOrderRequest(_Input):
    marketSlug: str = Field(..., min_length=1, description='Unique market slug into which the order should be entered')
    type: Literal['ORDER_TYPE_LIMIT', 'ORDER_TYPE_MARKET'] = Field(..., description='Type of order (limit or market)')
    price: Amount | None = Field(None, description='Order price and currency. Required for limit orders.')
    quantity: float | None = Field(None, gt=0, description='Order quantity in contracts. Supports decimal quantities on markets whose minimumTradeQty is less than 1.')
    tif: Literal['TIME_IN_FORCE_DAY', 'TIME_IN_FORCE_GOOD_TILL_CANCEL', 'TIME_IN_FORCE_GOOD_TILL_DATE', 'TIME_IN_FORCE_IMMEDIATE_OR_CANCEL', 'TIME_IN_FORCE_FILL_OR_KILL'] = Field(..., description='Order time in force policy')
    participateDontInitiate: bool | None = Field(None, description='If true, order must rest on the book prior to matching (maker only). Order will be rejected if it would immediately match.')
    goodTillTime: str | None = Field(None, description='Expiration time for orders with TIME_IN_FORCE_GOOD_TILL_DATE')
    intent: Literal['ORDER_INTENT_BUY_LONG', 'ORDER_INTENT_SELL_LONG', 'ORDER_INTENT_BUY_SHORT', 'ORDER_INTENT_SELL_SHORT'] | None = Field(None, description='Order intent. Either `intent` or (`outcomeSide` + `action`) must be set.')
    outcomeSide: Literal['OUTCOME_SIDE_YES', 'OUTCOME_SIDE_NO'] | None = Field(None, description='Outcome side. Set with `action` as an alternative to `intent`. Takes priority if both are set.')
    action: Literal['ORDER_ACTION_BUY', 'ORDER_ACTION_SELL'] | None = Field(None, description='Order action. Set with `outcomeSide` as an alternative to `intent`.')
    cashOrderQty: Amount | None = Field(None, description='Order quantity in cash and currency. Used for market orders instead of share quantity.')
    manualOrderIndicator: Literal['MANUAL_ORDER_INDICATOR_AUTOMATIC'] = Field('MANUAL_ORDER_INDICATOR_AUTOMATIC', description='Indicates whether the order was placed manually or automatically')
    synchronousExecution: bool | None = Field(None, description='If true, will block until the order is filled, rejected, canceled, or expired, up to maxBlockTime seconds')
    maxBlockTime: str | None = Field(None, description='Maximum block time in seconds if synchronous execution is requested')
    slippageTolerance: SlippageTolerance | None = Field(None, description='Slippage tolerance configuration for the order')

    @model_validator(mode="after")
    def order_requirements(self):
        if self.intent is None and (self.outcomeSide is None or self.action is None):
            raise ValueError("Set intent or both outcomeSide and action")
        if (self.outcomeSide is None) != (self.action is None):
            raise ValueError("outcomeSide and action must be supplied together")
        if (self.quantity is None) == (self.cashOrderQty is None):
            raise ValueError("Set quantity or cashOrderQty")
        if self.type == "ORDER_TYPE_LIMIT" and (self.price is None or self.quantity is None):
            raise ValueError("Limit orders require price and quantity")
        if self.tif == "TIME_IN_FORCE_GOOD_TILL_DATE" and not self.goodTillTime:
            raise ValueError("Good till date orders require goodTillTime")
        return self


class Amount(_Input):
    value: str = Field(..., description='The amount as a decimal string')
    currency: str = Field(..., description="The currency code (e.g., 'USD')")

    @field_validator("value")
    @classmethod
    def decimal_amount(cls, value):
        try:
            amount = Decimal(value)
        except InvalidOperation:
            raise ValueError("Use a decimal amount") from None
        if not amount.is_finite() or amount < 0:
            raise ValueError("Use a finite nonnegative decimal amount")
        return value


class SlippageTolerance(_Input):
    currentPrice: Amount | None = Field(None, description='Current price of the market used as reference for slippage calculation')
    bips: int | None = Field(None, description='Slippage tolerance in basis points (1 bip = 0.01%)')
    ticks: int | None = Field(None, description='Slippage tolerance in price ticks. Takes priority over bips if both are set.')


class CancelOrderRequest(_Input):
    marketSlug: str | None = Field(None, description='Unique market slug into which the order should be canceled')


class ModifyOrderRequest(_Input):
    marketSlug: str | None = Field(None, description='Unique market slug for the order being modified')
    price: Amount | None = Field(None, description='New order price and currency')
    quantity: float | None = Field(None, gt=0, description='Order quantity in contracts. Supports decimal quantities on markets whose minimumTradeQty is less than 1.')
    tif: Literal['TIME_IN_FORCE_DAY', 'TIME_IN_FORCE_GOOD_TILL_CANCEL', 'TIME_IN_FORCE_GOOD_TILL_DATE', 'TIME_IN_FORCE_IMMEDIATE_OR_CANCEL', 'TIME_IN_FORCE_FILL_OR_KILL'] | None = Field(None, description='New order time in force')
    participateDontInitiate: bool | None = Field(None, description='Order must rest on the book prior to matching (maker only)')
    goodTillTime: str | None = Field(None, description='Good till time for orders with TIME_IN_FORCE_GOOD_TILL_DATE')

    @model_validator(mode="after")
    def changed_fields(self):
        if not self.model_fields_set - {"marketSlug"}:
            raise ValueError("Provide at least one order field to modify")
        return self


class PreviewOrderRequest(_Input):
    request: CreateOrderRequest = Field(..., description='The order to preview')


class ClosePositionOrderRequest(_Input):
    marketSlug: str = Field(..., min_length=1, description='Market slug of the position to close')
    manualOrderIndicator: Literal['MANUAL_ORDER_INDICATOR_AUTOMATIC'] = Field('MANUAL_ORDER_INDICATOR_AUTOMATIC', description='Indicates whether the order was placed manually or automatically')
    synchronousExecution: bool | None = Field(None, description='If true, will block until the order is filled, rejected, canceled, or expired, up to maxBlockTime seconds')
    maxBlockTime: str | None = Field(None, description='Maximum block time in seconds if synchronous execution is requested')
    slippageTolerance: SlippageTolerance | None = Field(None, description='Slippage tolerance configuration for the close order')


class CancelOpenOrdersRequest(_Input):
    slugs: list[str] | None = Field(None, description='List of market slugs to filter by. If empty, cancels all open orders.')


class GetBalancesConfig(_Input):
    'Get Account Balances. '
    operation: Literal['get_balances'] = Field('get_balances', json_schema_extra={"ui:hidden": True})


class ListPositionsConfig(_Input):
    'Get User Positions. Returns one page; repeat with the next cursor or offset.'
    operation: Literal['list_positions'] = Field('list_positions', json_schema_extra={"ui:hidden": True})
    market: str | None = Field(None)
    limit: int | None = Field(None, ge=1, le=1000)
    cursor: str | None = Field(None)


class ListActivitiesConfig(_Input):
    'Get Activities. Returns one page; repeat with the next cursor or offset.'
    operation: Literal['list_activities'] = Field('list_activities', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=1000)
    cursor: str | None = Field(None)
    marketSlug: str | None = Field(None)
    types: list[Literal['ACTIVITY_TYPE_TRADE', 'ACTIVITY_TYPE_POSITION_RESOLUTION', 'ACTIVITY_TYPE_ACCOUNT_DEPOSIT', 'ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT', 'ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL', 'ACTIVITY_TYPE_REFERRAL_BONUS', 'ACTIVITY_TYPE_TRANSFER', 'ACTIVITY_TYPE_TAKER_FEE_REBATE', 'ACTIVITY_TYPE_LIQUIDITY_PROGRAM']] | None = Field(None)
    sortOrder: Literal['SORT_ORDER_DESCENDING', 'SORT_ORDER_ASCENDING'] | None = Field(None)


class ListOpenOrdersConfig(_Input):
    'Get Open Orders. Returns one page; repeat with the next cursor or offset.'
    operation: Literal['list_open_orders'] = Field('list_open_orders', json_schema_extra={"ui:hidden": True})
    slugs: list[str] | None = Field(None)


class GetOrderConfig(_Input):
    'Get Order. '
    operation: Literal['get_order'] = Field('get_order', json_schema_extra={"ui:hidden": True})
    orderId: str = Field(...)


class CreateOrderConfig(_Input):
    'Create Order. '
    operation: Literal['create_order'] = Field('create_order', json_schema_extra={"ui:hidden": True})
    body: CreateOrderRequest = Field(..., description="Create Order request fields as published by Polymarket US.")


class CancelOrderConfig(_Input):
    'Cancel Order. '
    operation: Literal['cancel_order'] = Field('cancel_order', json_schema_extra={"ui:hidden": True})
    orderId: str = Field(...)
    body: CancelOrderRequest = Field(..., description="Cancel Order request fields as published by Polymarket US.")


class ModifyOrderConfig(_Input):
    'Modify Order. '
    operation: Literal['modify_order'] = Field('modify_order', json_schema_extra={"ui:hidden": True})
    orderId: str = Field(...)
    body: ModifyOrderRequest = Field(..., description="Modify Order request fields as published by Polymarket US.")


class PreviewOrderConfig(_Input):
    'Preview Order. '
    operation: Literal['preview_order'] = Field('preview_order', json_schema_extra={"ui:hidden": True})
    body: PreviewOrderRequest = Field(..., description="Preview Order request fields as published by Polymarket US.")


class ClosePositionConfig(_Input):
    'Close Position Order. '
    operation: Literal['close_position'] = Field('close_position', json_schema_extra={"ui:hidden": True})
    body: ClosePositionOrderRequest = Field(..., description="Close Position Order request fields as published by Polymarket US.")


class CancelOpenOrdersConfig(_Input):
    'Cancel All Open Orders. '
    operation: Literal['cancel_open_orders'] = Field('cancel_open_orders', json_schema_extra={"ui:hidden": True})
    body: CancelOpenOrdersRequest = Field(..., description="Cancel All Open Orders request fields as published by Polymarket US.")


class ListMarketsConfig(_Input):
    'Get Markets. Returns one page; repeat with the next cursor or offset.'
    operation: Literal['list_markets'] = Field('list_markets', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=1000)
    offset: int | None = Field(None, ge=0)
    id: list[int] | None = Field(None)
    slug: list[str] | None = Field(None)
    archived: bool | None = Field(None)
    active: bool | None = Field(None)
    closed: bool | None = Field(None)


class GetMarketConfig(_Input):
    'Get Market By Slug. '
    operation: Literal['get_market'] = Field('get_market', json_schema_extra={"ui:hidden": True})
    slug: str = Field(...)


class GetMarketBboConfig(_Input):
    'Get Market BBO. '
    operation: Literal['get_market_bbo'] = Field('get_market_bbo', json_schema_extra={"ui:hidden": True})
    slug: str = Field(...)


class GetMarketBookConfig(_Input):
    'Get Market Book. '
    operation: Literal['get_market_book'] = Field('get_market_book', json_schema_extra={"ui:hidden": True})
    slug: str = Field(...)


class GetMarketSettlementConfig(_Input):
    'Get Market Settlement. '
    operation: Literal['get_market_settlement'] = Field('get_market_settlement', json_schema_extra={"ui:hidden": True})
    slug: str = Field(...)


class ListEventsConfig(_Input):
    'Get Events. Returns one page; repeat with the next cursor or offset.'
    operation: Literal['list_events'] = Field('list_events', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=1000)
    offset: int | None = Field(None, ge=0)
    id: list[int] | None = Field(None)
    slug: list[str] | None = Field(None)
    active: bool | None = Field(None)
    closed: bool | None = Field(None)
    tagSlug: str | None = Field(None)
    live: bool | None = Field(None)


class GetEventConfig(_Input):
    'Get Event By Slug. '
    operation: Literal['get_event'] = Field('get_event', json_schema_extra={"ui:hidden": True})
    slug: str = Field(...)
    groups: bool | None = Field(None)
    comboEnabledOnly: bool | None = Field(None)
    includePopularPlayerProps: bool | None = Field(None)


class SearchConfig(_Input):
    'Search. '
    operation: Literal['search'] = Field('search', json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None)
    limit: int | None = Field(None, ge=1, le=1000)
    status: str | None = Field(None)
    page: int | None = Field(None, ge=0)


PolymarketUSConfig = Annotated[Union[
    GetBalancesConfig,
    ListPositionsConfig,
    ListActivitiesConfig,
    ListOpenOrdersConfig,
    GetOrderConfig,
    CreateOrderConfig,
    CancelOrderConfig,
    ModifyOrderConfig,
    PreviewOrderConfig,
    ClosePositionConfig,
    CancelOpenOrdersConfig,
    ListMarketsConfig,
    GetMarketConfig,
    GetMarketBboConfig,
    GetMarketBookConfig,
    GetMarketSettlementConfig,
    ListEventsConfig,
    GetEventConfig,
    SearchConfig
], Field(discriminator="operation")]


class PolymarketUSFullConfig(NodeConfig[PolymarketUSConfig, PolymarketUSAPIKeyCredential]):
    pass


ROUTES = {'get_balances': {'method': 'GET',
                  'path': '/v1/account/balances',
                  'base': 'https://api.polymarket.us',
                  'path_fields': [],
                  'query_fields': [],
                  'body': False,
                  'operation_id': 'AccountService_GetAccountBalances'},
 'list_positions': {'method': 'GET',
                    'path': '/v1/portfolio/positions',
                    'base': 'https://api.polymarket.us',
                    'path_fields': [],
                    'query_fields': ['market', 'limit', 'cursor'],
                    'body': False,
                    'operation_id': 'PortfolioService_GetUserPositions'},
 'list_activities': {'method': 'GET',
                     'path': '/v1/portfolio/activities',
                     'base': 'https://api.polymarket.us',
                     'path_fields': [],
                     'query_fields': ['limit', 'cursor', 'marketSlug', 'types', 'sortOrder'],
                     'body': False,
                     'operation_id': 'PortfolioService_GetActivities'},
 'list_open_orders': {'method': 'GET',
                      'path': '/v1/orders/open',
                      'base': 'https://api.polymarket.us',
                      'path_fields': [],
                      'query_fields': ['slugs'],
                      'body': False,
                      'operation_id': 'OrdersService_GetOpenOrders'},
 'get_order': {'method': 'GET',
               'path': '/v1/order/{orderId}',
               'base': 'https://api.polymarket.us',
               'path_fields': ['orderId'],
               'query_fields': [],
               'body': False,
               'operation_id': 'OrdersService_GetOrder'},
 'create_order': {'method': 'POST',
                  'path': '/v1/orders',
                  'base': 'https://api.polymarket.us',
                  'path_fields': [],
                  'query_fields': [],
                  'body': True,
                  'operation_id': 'OrdersService_CreateOrder'},
 'cancel_order': {'method': 'POST',
                  'path': '/v1/order/{orderId}/cancel',
                  'base': 'https://api.polymarket.us',
                  'path_fields': ['orderId'],
                  'query_fields': [],
                  'body': True,
                  'operation_id': 'OrdersService_CancelOrder'},
 'modify_order': {'method': 'POST',
                  'path': '/v1/order/{orderId}/modify',
                  'base': 'https://api.polymarket.us',
                  'path_fields': ['orderId'],
                  'query_fields': [],
                  'body': True,
                  'operation_id': 'OrdersService_ModifyOrder'},
 'preview_order': {'method': 'POST',
                   'path': '/v1/order/preview',
                   'base': 'https://api.polymarket.us',
                   'path_fields': [],
                   'query_fields': [],
                   'body': True,
                   'operation_id': 'OrdersService_PreviewOrder'},
 'close_position': {'method': 'POST',
                    'path': '/v1/order/close-position',
                    'base': 'https://api.polymarket.us',
                    'path_fields': [],
                    'query_fields': [],
                    'body': True,
                    'operation_id': 'OrdersService_ClosePositionOrder'},
 'cancel_open_orders': {'method': 'POST',
                        'path': '/v1/orders/open/cancel',
                        'base': 'https://api.polymarket.us',
                        'path_fields': [],
                        'query_fields': [],
                        'body': True,
                        'operation_id': 'OrdersService_CancelOpenOrders'},
 'list_markets': {'method': 'GET',
                  'path': '/v1/markets',
                  'base': 'https://gateway.polymarket.us',
                  'path_fields': [],
                  'query_fields': ['limit', 'offset', 'id', 'slug', 'archived', 'active', 'closed'],
                  'body': False,
                  'operation_id': 'MarketService_GetMarkets'},
 'get_market': {'method': 'GET',
                'path': '/v1/market/slug/{slug}',
                'base': 'https://gateway.polymarket.us',
                'path_fields': ['slug'],
                'query_fields': [],
                'body': False,
                'operation_id': 'MarketService_GetMarketBySlug'},
 'get_market_bbo': {'method': 'GET',
                    'path': '/v1/markets/{slug}/bbo',
                    'base': 'https://gateway.polymarket.us',
                    'path_fields': ['slug'],
                    'query_fields': [],
                    'body': False,
                    'operation_id': 'MarketService_GetMarketBBO'},
 'get_market_book': {'method': 'GET',
                     'path': '/v1/markets/{slug}/book',
                     'base': 'https://gateway.polymarket.us',
                     'path_fields': ['slug'],
                     'query_fields': [],
                     'body': False,
                     'operation_id': 'MarketService_GetMarketBook'},
 'get_market_settlement': {'method': 'GET',
                           'path': '/v1/markets/{slug}/settlement',
                           'base': 'https://gateway.polymarket.us',
                           'path_fields': ['slug'],
                           'query_fields': [],
                           'body': False,
                           'operation_id': 'MarketService_GetMarketSettlement'},
 'list_events': {'method': 'GET',
                 'path': '/v1/events',
                 'base': 'https://gateway.polymarket.us',
                 'path_fields': [],
                 'query_fields': ['limit',
                                  'offset',
                                  'id',
                                  'slug',
                                  'active',
                                  'closed',
                                  'tagSlug',
                                  'live'],
                 'body': False,
                 'operation_id': 'EventsService_GetEvents'},
 'get_event': {'method': 'GET',
               'path': '/v1/events/slug/{slug}',
               'base': 'https://gateway.polymarket.us',
               'path_fields': ['slug'],
               'query_fields': ['groups', 'comboEnabledOnly', 'includePopularPlayerProps'],
               'body': False,
               'operation_id': 'EventsService_GetEventBySlug'},
 'search': {'method': 'GET',
            'path': '/v1/search',
            'base': 'https://gateway.polymarket.us',
            'path_fields': [],
            'query_fields': ['query', 'limit', 'status', 'page'],
            'body': False,
            'operation_id': 'SearchService_Search'}}


class PolymarketUSNode(WorkflowNode):
    integration_type = "automation-polymarket-us"
    connection_evidence = ConnectionEvidence(operation="get_balances", noun="account balances")

    @classmethod
    def get_config_model(cls):
        return PolymarketUSFullConfig

    async def execute(self, inputs):
        op = self.config.config
        route = ROUTES[op.operation]
        path = route["path"]
        for name in route["path_fields"]:
            value = getattr(op, name)
            if not value or value in {".", ".."} or any(c in value for c in "/\\?#"):
                raise ValueError("Use a single Polymarket US resource identifier")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        values = op.model_dump(exclude_none=True)
        params = {name: values[name] for name in route["query_fields"] if name in values}
        headers = {"Accept": "application/json"}
        if route["base"] == "https://api.polymarket.us":
            credential = self.config.credentials
            if credential is None:
                raise ValueError("Connect a Polymarket US API key")
            timestamp = str(int(time.time() * 1000))
            key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(credential.secret_key, validate=True)[:32])
            signature = key.sign((timestamp + route["method"] + path).encode())
            headers.update({"X-PM-Access-Key": credential.key_id, "X-PM-Timestamp": timestamp,
                "X-PM-Signature": base64.b64encode(signature).decode()})
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(route["method"], route["base"] + path,
                headers=headers, params=params, **({"json": values["body"]} if route["body"] else {}))
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text for connect verdicts, redacting pasted keys.
            text = response.text[:2000]
            if self.config.credentials:
                for value in (self.config.credentials.key_id, self.config.credentials.secret_key):
                    text = text.replace(value, "[redacted]")
            raise ValueError(f"Polymarket US HTTP {response.status_code}: {text}")
        data = response.json()
        if not isinstance(data, dict) or data.get("error") or data.get("errors"):
            raise ValueError("Polymarket US returned an invalid response or error envelope")
        result = {"status": "success", "data": data}
        if op.operation == "get_balances":
            result["items"] = [
                {"name": f"{balance['currency']}: {balance['currentBalance']}"}
                for balance in data.get("balances", [])
                if isinstance(balance, dict) and isinstance(balance.get("currency"), str)
                and isinstance(balance.get("currentBalance"), (int, float, str))
            ]
        return result
