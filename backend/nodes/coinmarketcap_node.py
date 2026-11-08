"""CoinMarketCap Pro API market data, pinned to its published OpenAPI 3.0.3.

Each operation issues one GET. List reads return one explicit start/limit page;
plan-dependent historical/exchange endpoints require a suitable subscription.
The provider contract exposes data reads, not trading or account mutations.
"""
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://pro-api.coinmarketcap.com"


class CoinMarketCapAPIKey(BaseModel):
    model_config = ConfigDict(title="CoinMarketCap API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://pro.coinmarketcap.com/account",
            "x-credential-instructions": "Paste your CoinMarketCap Pro API key. NoClick sends it in the X-CMC_PRO_API_KEY header. Connecting reads your key's plan and usage; it does not identify a person. Endpoint access and usage credits depend on your subscription.",
        })
    credential_type: Literal["coinmarketcap_api_key"] = Field("coinmarketcap_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    start: int = Field(1, ge=1, title="Start", description="One-based result offset. Each run reads only this page.")
    limit: int = Field(100, ge=1, le=5000, title="Limit", description="Maximum results on this page. Advance start by limit to read another page.")


class _SentimentPage(_Page):
    limit: int = Field(50, ge=1, le=500, title="Limit")


class _Convert(_Input):
    convert: str = Field("USD", max_length=2000,
        pattern=r"^[0-9A-Za-z$@-]+(?:,[0-9A-Za-z$@-]+)*$",
        title="Quote currencies", description="Comma-separated fiat or cryptocurrency symbols. Additional conversions may use more credits.")


class _Listings(_Convert):
    start: int = Field(1, ge=1, title="Start", description="One-based result offset; one page per run.")
    limit: int = Field(100, ge=1, le=5000, title="Limit")
    sort: Literal["market_cap", "name", "symbol", "date_added", "price", "volume_24h", "percent_change_24h"] = Field("market_cap", title="Sort by")
    sort_dir: Literal["asc", "desc"] = Field("desc", title="Sort direction")


class _Assets(_Input):
    id: str = Field(..., min_length=1, max_length=2000, pattern=r"^\d+(?:,\d+)*$", title="CoinMarketCap IDs",
        description="Comma-separated stable CoinMarketCap IDs. For example 1,1027 for Bitcoin/Ethereum; use exchange IDs for exchange operations.")


class _AssetQuote(_Assets, _Convert):
    pass


class _History(_AssetQuote):
    time_start: str = Field(..., min_length=1, max_length=64, title="Start time", description="Unix or ISO 8601 timestamp, e.g. 2024-01-01. Historical access requires an eligible plan.")
    time_end: str | None = Field(None, max_length=64, title="End time", description="Unix or ISO 8601 timestamp, inclusive. Defaults to current time at the provider.")
    time_period: Literal["daily", "hourly"] = Field("daily", title="Time period")
    count: int = Field(10, ge=1, le=10000, title="Count")


class _Conversion(_Convert):
    id: str = Field(..., min_length=1, max_length=30, pattern=r"^\d+$", title="Source currency ID", description="One fiat or cryptocurrency ID, e.g. 1 for Bitcoin.")
    amount: float = Field(..., ge=0.00000001, le=1000000000000, allow_inf_nan=False, title="Amount")


class CoinMarketCapGetKeyInfoConfig(_Input):
    """API key plan and usage."""
    operation: Literal["get_key_info"] = Field("get_key_info", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapListCryptocurrenciesConfig(_Page):
    """Cryptocurrency ID map."""
    operation: Literal["list_cryptocurrencies"] = Field("list_cryptocurrencies", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapListLatestListingsConfig(_Listings):
    """Latest ranked cryptocurrencies."""
    operation: Literal["list_latest_listings"] = Field("list_latest_listings", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapGetLatestQuotesConfig(_AssetQuote):
    """Latest cryptocurrency prices."""
    operation: Literal["get_latest_quotes"] = Field("get_latest_quotes", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapGetCryptocurrencyInfoConfig(_Assets):
    """Cryptocurrency metadata."""
    operation: Literal["get_cryptocurrency_info"] = Field("get_cryptocurrency_info", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapGetLatestOhlcvConfig(_AssetQuote):
    """Latest cryptocurrency OHLCV."""
    operation: Literal["get_latest_ohlcv"] = Field("get_latest_ohlcv", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapGetHistoricalOhlcvConfig(_History):
    """Historical cryptocurrency OHLCV."""
    operation: Literal["get_historical_ohlcv"] = Field("get_historical_ohlcv", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapGetGlobalMetricsConfig(_Convert):
    """Global market metrics."""
    operation: Literal["get_global_metrics"] = Field("get_global_metrics", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapListFiatCurrenciesConfig(_Page):
    """Fiat currency ID map."""
    operation: Literal["list_fiat_currencies"] = Field("list_fiat_currencies", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapConvertPriceConfig(_Conversion):
    """Convert a currency amount."""
    operation: Literal["convert_price"] = Field("convert_price", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapListExchangesConfig(_Page):
    """Exchange ID map."""
    operation: Literal["list_exchanges"] = Field("list_exchanges", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapGetExchangeInfoConfig(_Assets):
    """Exchange metadata."""
    operation: Literal["get_exchange_info"] = Field("get_exchange_info", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapGetExchangeQuotesConfig(_AssetQuote):
    """Latest exchange volumes."""
    operation: Literal["get_exchange_quotes"] = Field("get_exchange_quotes", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapListCategoriesConfig(_Page):
    """Cryptocurrency categories."""
    operation: Literal["list_categories"] = Field("list_categories", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapGetFearAndGreedConfig(_Input):
    """Latest Fear and Greed Index."""
    operation: Literal["get_fear_and_greed"] = Field("get_fear_and_greed", title="Operation", json_schema_extra={"x-operation-kind": "read"})


class CoinMarketCapGetFearAndGreedHistoryConfig(_SentimentPage):
    """Historical Fear and Greed Index."""
    operation: Literal["get_fear_and_greed_history"] = Field("get_fear_and_greed_history", title="Operation", json_schema_extra={"x-operation-kind": "read"})


CoinMarketCapConfig = Annotated[Union[
    CoinMarketCapGetKeyInfoConfig,
    CoinMarketCapListCryptocurrenciesConfig,
    CoinMarketCapListLatestListingsConfig,
    CoinMarketCapGetLatestQuotesConfig,
    CoinMarketCapGetCryptocurrencyInfoConfig,
    CoinMarketCapGetLatestOhlcvConfig,
    CoinMarketCapGetHistoricalOhlcvConfig,
    CoinMarketCapGetGlobalMetricsConfig,
    CoinMarketCapListFiatCurrenciesConfig,
    CoinMarketCapConvertPriceConfig,
    CoinMarketCapListExchangesConfig,
    CoinMarketCapGetExchangeInfoConfig,
    CoinMarketCapGetExchangeQuotesConfig,
    CoinMarketCapListCategoriesConfig,
    CoinMarketCapGetFearAndGreedConfig,
    CoinMarketCapGetFearAndGreedHistoryConfig
], Field(discriminator="operation")]


class CoinMarketCapFullConfig(NodeConfig[CoinMarketCapConfig, CoinMarketCapAPIKey]):
    pass


ROUTES = {'get_key_info': '/v1/key/info', 'list_cryptocurrencies': '/v1/cryptocurrency/map', 'list_latest_listings': '/v3/cryptocurrency/listings/latest', 'get_latest_quotes': '/v3/cryptocurrency/quotes/latest', 'get_cryptocurrency_info': '/v2/cryptocurrency/info', 'get_latest_ohlcv': '/v2/cryptocurrency/ohlcv/latest', 'get_historical_ohlcv': '/v2/cryptocurrency/ohlcv/historical', 'get_global_metrics': '/v1/global-metrics/quotes/latest', 'list_fiat_currencies': '/v1/fiat/map', 'convert_price': '/v2/tools/price-conversion', 'list_exchanges': '/v1/exchange/map', 'get_exchange_info': '/v1/exchange/info', 'get_exchange_quotes': '/v1/exchange/quotes/latest', 'list_categories': '/v1/cryptocurrency/categories', 'get_fear_and_greed': '/v3/fear-and-greed/latest', 'get_fear_and_greed_history': '/v3/fear-and-greed/historical'}


class CoinMarketCapNode(WorkflowNode):
    integration_type = "automation-coinmarketcap"
    connection_evidence = ConnectionEvidence(noun="API key plan and usage", operation="get_key_info", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return CoinMarketCapFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a CoinMarketCap API key")
        config = self.config.config
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get(BASE + ROUTES[config.operation], params=params,
                    headers={"X-CMC_PRO_API_KEY": credential.api_key, "Accept": "application/json"})
            if response.status_code != 200:
                # Preserve provider rejection text when present, without leaking keys or URLs.
                message = "CoinMarketCap request failed"
                try:
                    error = response.json().get("status", {}).get("error_message")
                    if isinstance(error, str) and error:
                        message = error.replace(credential.api_key, "[redacted]")
                except (ValueError, AttributeError):
                    pass
                return {"status": "error", "http_status": response.status_code, "error": message}
            body = response.json()
        except httpx.HTTPError:
            return {"status": "error", "error": "CoinMarketCap request could not be completed"}
        except ValueError:
            return {"status": "error", "error": "CoinMarketCap returned invalid JSON"}
        if not isinstance(body, dict) or not isinstance(body.get("status"), dict):
            return {"status": "error", "error": "CoinMarketCap returned an unexpected response"}
        status = body["status"]
        if status.get("error_code") not in (0, "0"):
            message = status.get("error_message") or "CoinMarketCap did not confirm this request"
            return {"status": "error", "error_code": status.get("error_code"),
                "error": str(message).replace(credential.api_key, "[redacted]")}
        if not isinstance(body.get("data"), (dict, list)):
            return {"status": "error", "error": "CoinMarketCap response has no data object or list"}
        if config.operation == "get_key_info" and (
            not isinstance(body["data"], dict) or not all(isinstance(body["data"].get(k), dict) for k in ("plan", "usage"))
        ):
            return {"status": "error", "error": "CoinMarketCap response has no key plan and usage"}
        return {"status": "success", "data": body["data"], "api_status": status}
