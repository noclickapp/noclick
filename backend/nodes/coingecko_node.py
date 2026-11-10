"""CoinGecko Demo API v3 market data, one documented GET per operation.

This API has no writes or account-owned resources. Evidence proves reachability,
not identity. Page parameters fetch exactly one page; no completeness is implied.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.coingecko.com/api/v3"
FAMILY = "coingecko_api_key"


class CoinGeckoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="CoinGecko API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.coingecko.com/en/developers/dashboard",
            "x-credential-instructions": "Paste a CoinGecko Demo API key from your Developer Dashboard. Use a Demo key, not a paid Pro key. NoClick sends it in the x-cg-demo-api-key header to api.coingecko.com. The connection check reads public API status and proves reachability, not account identity.",
        })
    credential_type: Literal["coingecko_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the Demo API key without a header or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Coin(_Input):
    id: str = Field(..., min_length=1, max_length=200, description="CoinGecko coin ID, for example bitcoin; use List coins or Search to find it.")

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value) or value in {".", ".."}:
            raise ValueError("Use one CoinGecko resource ID")
        return value


class _Page(_Input):
    page: int = Field(1, ge=1, le=100000, description="Fetch one page; increment explicitly to read another page.")
    per_page: int = Field(100, ge=1, le=250)


class CheckConnection(_Input):
    """Check connection: GET /ping."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})

class GetPrices(_Input):
    """Get prices: GET /simple/price."""
    operation: Literal["get_prices"] = Field("get_prices", json_schema_extra={"ui:hidden": True})
    ids: str = Field(..., min_length=1, max_length=2000, description="Comma-separated CoinGecko IDs, for example bitcoin,ethereum.")
    vs_currencies: str = Field("usd", max_length=500)
    include_market_cap: bool = False
    include_24hr_vol: bool = False
    include_24hr_change: bool = False
    include_last_updated_at: bool = False

class GetTokenPrices(_Coin):
    """Get token prices: GET /simple/token_price/{id}."""
    id: str = Field(..., min_length=1, max_length=200, description="Asset platform ID, for example ethereum; use List asset platforms to find it.")
    operation: Literal["get_token_prices"] = Field("get_token_prices", json_schema_extra={"ui:hidden": True})
    contract_addresses: str = Field(..., min_length=1, max_length=4000, description="Comma-separated token contract addresses.")
    vs_currencies: str = Field("usd", max_length=500)
    include_market_cap: bool = False
    include_24hr_vol: bool = False
    include_24hr_change: bool = False
    include_last_updated_at: bool = False

class ListSupportedCurrencies(_Input):
    """List supported currencies: GET /simple/supported_vs_currencies."""
    operation: Literal["list_supported_currencies"] = Field("list_supported_currencies", json_schema_extra={"ui:hidden": True})

class ListCoins(_Input):
    """List coins: GET /coins/list."""
    operation: Literal["list_coins"] = Field("list_coins", json_schema_extra={"ui:hidden": True})
    include_platform: bool = False

class ListCoinMarkets(_Page):
    """List coin markets: GET /coins/markets."""
    operation: Literal["list_coin_markets"] = Field("list_coin_markets", json_schema_extra={"ui:hidden": True})
    vs_currency: str = Field("usd", max_length=50)
    ids: str | None = Field(None, min_length=1, max_length=2000)
    category: str | None = Field(None, min_length=1, max_length=200)
    order: Literal["market_cap_asc", "market_cap_desc", "volume_asc", "volume_desc", "id_asc", "id_desc"] = "market_cap_desc"
    sparkline: bool = False
    price_change_percentage: str | None = Field(None, max_length=100)

class GetCoin(_Coin):
    """Get coin: GET /coins/{id}."""
    operation: Literal["get_coin"] = Field("get_coin", json_schema_extra={"ui:hidden": True})
    localization: bool = False
    tickers: bool = False
    market_data: bool = True
    community_data: bool = False
    developer_data: bool = False
    sparkline: bool = False

class GetCoinHistory(_Coin):
    """Get coin history: GET /coins/{id}/history."""
    operation: Literal["get_coin_history"] = Field("get_coin_history", json_schema_extra={"ui:hidden": True})
    date: str = Field(..., description="Historical date as dd-mm-yyyy; Demo history is limited to the past 365 days.")
    localization: bool = False

    @field_validator("date")
    @classmethod
    def calendar_date(cls, value):
        if not re.fullmatch(r"[0-9]{2}-[0-9]{2}-[0-9]{4}", value):
            raise ValueError("Use dd-mm-yyyy")
        datetime.strptime(value, "%d-%m-%Y")
        return value

class GetMarketChart(_Coin):
    """Get market chart: GET /coins/{id}/market_chart."""
    operation: Literal["get_market_chart"] = Field("get_market_chart", json_schema_extra={"ui:hidden": True})
    vs_currency: str = Field("usd", max_length=50)
    days: str = Field("1", pattern=r"^(?:[1-9]|[1-9][0-9]|[12][0-9]{2}|3[0-5][0-9]|36[0-5])$", description="Days of history, 1–365 on the Demo plan.")
    interval: Literal["hourly", "daily"] | None = None

class GetOHLC(_Coin):
    """Get ohlc: GET /coins/{id}/ohlc."""
    operation: Literal["get_ohlc"] = Field("get_ohlc", json_schema_extra={"ui:hidden": True})
    vs_currency: str = Field("usd", max_length=50)
    days: Literal["1", "7", "14", "30", "90", "180", "365"] = "1"

class ListCategories(_Input):
    """List categories: GET /coins/categories/list."""
    operation: Literal["list_categories"] = Field("list_categories", json_schema_extra={"ui:hidden": True})

class ListCategoryMarkets(_Input):
    """List category markets: GET /coins/categories."""
    operation: Literal["list_category_markets"] = Field("list_category_markets", json_schema_extra={"ui:hidden": True})
    order: Literal["market_cap_desc", "market_cap_asc", "name_desc", "name_asc", "market_cap_change_24h_desc", "market_cap_change_24h_asc"] = "market_cap_desc"

class ListExchanges(_Page):
    """List exchanges: GET /exchanges."""
    operation: Literal["list_exchanges"] = Field("list_exchanges", json_schema_extra={"ui:hidden": True})

class GetExchange(_Coin):
    """Get exchange: GET /exchanges/{id}."""
    id: str = Field(..., min_length=1, max_length=200, description="Exchange ID, for example binance; use List exchanges to find it.")
    operation: Literal["get_exchange"] = Field("get_exchange", json_schema_extra={"ui:hidden": True})

class Search(_Input):
    """Search: GET /search."""
    operation: Literal["search"] = Field("search", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=200, description="Search coins, categories, exchanges and NFTs by name or symbol.")

class GetTrending(_Input):
    """Get trending: GET /search/trending."""
    operation: Literal["get_trending"] = Field("get_trending", json_schema_extra={"ui:hidden": True})

class GetGlobal(_Input):
    """Get global: GET /global."""
    operation: Literal["get_global"] = Field("get_global", json_schema_extra={"ui:hidden": True})

class GetDefiGlobal(_Input):
    """Get defi global: GET /global/decentralized_finance_defi."""
    operation: Literal["get_defi_global"] = Field("get_defi_global", json_schema_extra={"ui:hidden": True})

class GetExchangeRates(_Input):
    """Get exchange rates: GET /exchange_rates."""
    operation: Literal["get_exchange_rates"] = Field("get_exchange_rates", json_schema_extra={"ui:hidden": True})

class ListAssetPlatforms(_Input):
    """List asset platforms: GET /asset_platforms."""
    operation: Literal["list_asset_platforms"] = Field("list_asset_platforms", json_schema_extra={"ui:hidden": True})
    filter: Literal["nft"] | None = None

class _OnchainPoll(PollTriggerConfigBase):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-webhook": True})
    network: str | None = Field(None, min_length=1, max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Network ID",
        description="GeckoTerminal network ID, for example eth or solana. Leave empty for all networks.")


class OnNewPool(_OnchainPoll):
    """Watch the latest 20 liquidity pools. The first poll records a baseline.

    Pools outside this window between polls can be missed; choose a network
    and a shorter schedule for busy feeds. This is not a complete history.
    """
    operation: Literal["on_new_pool"] = Field("on_new_pool", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Pool"})


class OnUpdatedToken(_OnchainPoll):
    """Watch the 100 most recently updated token metadata records.

    The first poll records a baseline. Updates outside this window between
    polls can be missed. Each token's metadata timestamp identifies an update.
    """
    operation: Literal["on_updated_token"] = Field("on_updated_token", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On Token Metadata Updated"})


CoinGeckoConfig = Annotated[Union[CheckConnection, GetPrices, GetTokenPrices, ListSupportedCurrencies, ListCoins, ListCoinMarkets, GetCoin, GetCoinHistory, GetMarketChart, GetOHLC, ListCategories, ListCategoryMarkets, ListExchanges, GetExchange, Search, GetTrending, GetGlobal, GetDefiGlobal, GetExchangeRates, ListAssetPlatforms, OnNewPool, OnUpdatedToken], Field(discriminator="operation")]


class CoinGeckoFullConfig(NodeConfig[CoinGeckoConfig, CoinGeckoAPIKeyCredential]):
    pass


ROUTES = {
    "check_connection": ("/ping", dict),
    "get_prices": ("/simple/price", dict),
    "get_token_prices": ("/simple/token_price/{id}", dict),
    "list_supported_currencies": ("/simple/supported_vs_currencies", list),
    "list_coins": ("/coins/list", list),
    "list_coin_markets": ("/coins/markets", list),
    "get_coin": ("/coins/{id}", dict),
    "get_coin_history": ("/coins/{id}/history", dict),
    "get_market_chart": ("/coins/{id}/market_chart", dict),
    "get_ohlc": ("/coins/{id}/ohlc", list),
    "list_categories": ("/coins/categories/list", list),
    "list_category_markets": ("/coins/categories", list),
    "list_exchanges": ("/exchanges", list),
    "get_exchange": ("/exchanges/{id}", dict),
    "search": ("/search", dict),
    "get_trending": ("/search/trending", dict),
    "get_global": ("/global", dict),
    "get_defi_global": ("/global/decentralized_finance_defi", dict),
    "get_exchange_rates": ("/exchange_rates", dict),
    "list_asset_platforms": ("/asset_platforms", list),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class CoinGeckoNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-coingecko"
    connection_evidence = ConnectionEvidence(
        noun="CoinGecko API status", operation="check_connection", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return CoinGeckoFullConfig

    @classmethod
    def resolve_agent_event(cls, output):
        operation = output.get("operation")
        if operation not in {"on_new_pool", "on_updated_token"}:
            return super().resolve_agent_event(output)
        items = output.get("data") or []
        if not items:
            return None
        label = "New liquidity pools" if operation == "on_new_pool" else "Token metadata updated"
        timestamp = "pool_created_at" if operation == "on_new_pool" else "metadata_updated_at"
        records = []
        for item in items:
            attributes = item["attributes"]
            records.append(f"{attributes.get('name') or item['id']} — "
                f"ID: {item['id']}; address: {attributes.get('address')}; "
                f"{timestamp}: {attributes[timestamp]}\n" + json.dumps(item, ensure_ascii=False))
        return {
            "title": f"CoinGecko: {label}",
            "conversation_key": f"coingecko:{operation}:{output.get('network') or 'all'}",
            "text": f"CoinGecko — {label} on {output.get('network') or 'all networks'}. "
                + "\n" + "\n".join(records),
        }

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CoinGecko Demo API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        is_poll = isinstance(config, _OnchainPoll)
        if is_poll:
            if isinstance(config, OnNewPool):
                route = (f"/onchain/networks/{quote(config.network, safe='')}/new_pools"
                         if config.network else "/onchain/networks/new_pools")
                params = {"page": 1}
            else:
                route = "/onchain/tokens/info_recently_updated"
                params = {"network": config.network} if config.network else {}
            expected = dict
        else:
            route, expected = ROUTES[config.operation]
            params = config.model_dump(exclude={"operation"}, exclude_none=True)
        if "{id}" in route:
            route = route.replace("{id}", quote(params.pop("id"), safe=""))
        params = {k: "true" if v is True else "false" if v is False else str(v) for k, v in params.items()}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get(BASE + route, params=params,
                    headers={"x-cg-demo-api-key": secret, "Accept": "application/json"})
        except httpx.RequestError:
            return {"status": "error", "message": "CoinGecko could not be reached", "identity_verified": False}
        if response.status_code != 200:
            # Preserve provider rejection wording for the connect verdict, but redact secrets.
            try:
                payload = response.json()
                message = payload.get("error") or payload.get("status", {}).get("error_message")
            except (ValueError, AttributeError, TypeError):
                message = None
            return {"status": "error", "http_status": response.status_code,
                "message": _redact(message, secret) if isinstance(message, str) else "CoinGecko rejected the request",
                "identity_verified": False}
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" or len(response.content) > 20_000_000:
            return {"status": "error", "message": "CoinGecko returned an unexpected response"}
        try:
            body = response.json()
        except ValueError:
            return {"status": "error", "message": "CoinGecko returned invalid JSON"}
        if not isinstance(body, expected) or isinstance(body, dict) and ("error" in body or "status" in body):
            return {"status": "error", "message": "CoinGecko returned an unexpected response"}
        if config.operation == "check_connection" and not isinstance(body.get("gecko_says"), str):
            return {"status": "error", "message": "CoinGecko API status was not confirmed"}
        if is_poll:
            items = body.get("data")
            timestamp = "pool_created_at" if isinstance(config, OnNewPool) else "metadata_updated_at"
            if not isinstance(items, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
                or not isinstance(item.get("attributes"), dict)
                or not isinstance(item["attributes"].get(timestamp), str)
                or not item["attributes"][timestamp]
                for item in items
            ):
                raise ValueError("CoinGecko returned an invalid onchain feed; poll state was preserved")
            items = _redact(items, secret)
            fresh = await self._filter_unseen(items, lambda item:
                item["id"] if isinstance(config, OnNewPool)
                else f"{item['id']}:{item['attributes']['metadata_updated_at']}")
            output = {"status": "success", "operation": config.operation, "data": fresh,
                "network": config.network, "count": len(fresh),
                "window": "latest 20 pools" if isinstance(config, OnNewPool) else "100 most recently updated tokens"}
            await self.emit(output)
            return output
        output = {"status": "success", "operation": config.operation, "data": _redact(body, secret), "identity_verified": False}
        if isinstance(config, _Page):
            output.update(page=config.page, per_page=config.per_page, pagination="single_page")
        await self.emit(output)
        return output
