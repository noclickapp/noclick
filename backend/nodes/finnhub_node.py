"""Finnhub API v1: market data and non-streaming AI Copilot.

Contract: https://github.com/Finnhub-Stock-API/finnhub-go/blob/master/api/openapi.yaml
Each operation makes one request. Access depends on the key's subscription;
connection evidence proves market-data reachability, not account identity.
"""
from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://finnhub.io/api/v1"


class FinnhubAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Finnhub API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://finnhub.io/dashboard",
            "x-credential-instructions": "Paste your Finnhub API key from the dashboard. Your subscription determines available endpoints. NoClick sends it as the token query parameter to finnhub.io. Connecting checks public market news access, not account identity or premium permissions."})
    credential_type: Literal["finnhub_api_key"] = Field("finnhub_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def range_order(self):
        start, end = getattr(self, "from_date", None), getattr(self, "to_date", None)
        if start is not None and end is not None and start > end:
            raise ValueError("From must be on or before to")
        return self


class FinnhubChatMessage(_Input):
    role: Literal["system", "user"]
    content: str = Field(..., min_length=1, max_length=100000)


class FinnhubSymbolSearchConfig(_Input):
    """Symbol Lookup."""
    operation: Literal["symbol_search"] = Field("symbol_search", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, max_length=256)
    exchange: str | None = Field(None, min_length=1, max_length=256)


class FinnhubStockSymbolsConfig(_Input):
    """Stock Symbol."""
    operation: Literal["stock_symbols"] = Field("stock_symbols", json_schema_extra={"ui:hidden": True})
    exchange: str = Field(..., min_length=1, max_length=256)
    mic: str | None = Field(None, min_length=1, max_length=256)
    securityType: str | None = Field(None, min_length=1, max_length=256)
    currency: str | None = Field(None, min_length=1, max_length=256)


class FinnhubMarketStatusConfig(_Input):
    """Market Status."""
    operation: Literal["market_status"] = Field("market_status", json_schema_extra={"ui:hidden": True})
    exchange: str = Field(..., min_length=1, max_length=256)


class FinnhubCompanyProfile2Config(_Input):
    """Company Profile 2, selected by symbol."""
    operation: Literal["company_profile2"] = Field("company_profile2", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)


class FinnhubMarketNewsConfig(_Input):
    """Market News."""
    operation: Literal["get_market_news"] = Field("get_market_news", json_schema_extra={"ui:hidden": True})
    category: Literal["general", "forex", "crypto", "merger"] = Field("general")
    minId: int | None = Field(None, ge=0, strict=True)


class FinnhubCompanyNewsConfig(_Input):
    """Company News."""
    operation: Literal["company_news"] = Field("company_news", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)
    from_date: date = Field(..., alias="from")
    to_date: date = Field(..., alias="to")


class FinnhubCompanyPeersConfig(_Input):
    """Peers."""
    operation: Literal["company_peers"] = Field("company_peers", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)
    grouping: Literal["sector", "industry", "subIndustry"] | None = None


class FinnhubCompanyBasicFinancialsConfig(_Input):
    """Basic Financials."""
    operation: Literal["company_basic_financials"] = Field("company_basic_financials", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)
    metric: Literal["all"] = "all"


class FinnhubInsiderTransactionsConfig(_Input):
    """Insider Transactions."""
    operation: Literal["insider_transactions"] = Field("insider_transactions", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)
    from_date: date | None = Field(None, alias="from")
    to_date: date | None = Field(None, alias="to")


class FinnhubStockDividendsConfig(_Input):
    """Dividends."""
    operation: Literal["stock_dividends"] = Field("stock_dividends", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)
    from_date: date = Field(..., alias="from")
    to_date: date = Field(..., alias="to")


class FinnhubRecommendationTrendsConfig(_Input):
    """Recommendation Trends."""
    operation: Literal["recommendation_trends"] = Field("recommendation_trends", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)


class FinnhubPriceTargetConfig(_Input):
    """Price Target."""
    operation: Literal["price_target"] = Field("price_target", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)


class FinnhubCompanyEarningsConfig(_Input):
    """Earnings Surprises."""
    operation: Literal["company_earnings"] = Field("company_earnings", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)
    limit: int | None = Field(None, ge=0, strict=True)


class FinnhubEarningsCalendarConfig(_Input):
    """Earnings Calendar."""
    operation: Literal["earnings_calendar"] = Field("earnings_calendar", json_schema_extra={"ui:hidden": True})
    from_date: date | None = Field(None, alias="from")
    to_date: date | None = Field(None, alias="to")
    symbol: str | None = Field(None, min_length=1, max_length=256)
    international: bool | None = Field(None, strict=True)


class FinnhubQuoteConfig(_Input):
    """Quote."""
    operation: Literal["quote"] = Field("quote", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)


class FinnhubStockCandlesConfig(_Input):
    """Stock Candles."""
    operation: Literal["stock_candles"] = Field("stock_candles", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)
    resolution: Literal["1", "5", "15", "30", "60", "D", "W", "M"] = Field(...)
    from_date: int = Field(..., alias="from", ge=0, strict=True)
    to_date: int = Field(..., alias="to", ge=0, strict=True)


class FinnhubStockSplitsConfig(_Input):
    """Splits."""
    operation: Literal["stock_splits"] = Field("stock_splits", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)
    from_date: date = Field(..., alias="from")
    to_date: date = Field(..., alias="to")


class FinnhubForexRatesConfig(_Input):
    """Forex rates."""
    operation: Literal["forex_rates"] = Field("forex_rates", json_schema_extra={"ui:hidden": True})
    base: str | None = Field(None, min_length=1, max_length=256)
    date: str | None = Field(None, min_length=1, max_length=256)


class FinnhubCryptoCandlesConfig(_Input):
    """Crypto Candles."""
    operation: Literal["crypto_candles"] = Field("crypto_candles", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=256)
    resolution: Literal["1", "5", "15", "30", "60", "D", "W", "M"] = Field(...)
    from_date: int = Field(..., alias="from", ge=0, strict=True)
    to_date: int = Field(..., alias="to", ge=0, strict=True)


class FinnhubAiChatConfig(_Input):
    """AI Copilot."""
    operation: Literal["ai_chat"] = Field("ai_chat", json_schema_extra={"ui:hidden": True})
    messages: list[FinnhubChatMessage] = Field(..., min_length=1, max_length=100)


FinnhubOperation = Annotated[Union[
    FinnhubSymbolSearchConfig,
    FinnhubStockSymbolsConfig,
    FinnhubMarketStatusConfig,
    FinnhubCompanyProfile2Config,
    FinnhubMarketNewsConfig,
    FinnhubCompanyNewsConfig,
    FinnhubCompanyPeersConfig,
    FinnhubCompanyBasicFinancialsConfig,
    FinnhubInsiderTransactionsConfig,
    FinnhubStockDividendsConfig,
    FinnhubRecommendationTrendsConfig,
    FinnhubPriceTargetConfig,
    FinnhubCompanyEarningsConfig,
    FinnhubEarningsCalendarConfig,
    FinnhubQuoteConfig,
    FinnhubStockCandlesConfig,
    FinnhubStockSplitsConfig,
    FinnhubForexRatesConfig,
    FinnhubCryptoCandlesConfig,
    FinnhubAiChatConfig], Field(discriminator="operation")]


class FinnhubFullConfig(NodeConfig[FinnhubOperation, FinnhubAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    'symbol_search': ('GET', '/search', 'dict'),
    'stock_symbols': ('GET', '/stock/symbol', 'list'),
    'market_status': ('GET', '/stock/market-status', 'dict'),
    'company_profile2': ('GET', '/stock/profile2', 'dict'),
    'get_market_news': ('GET', '/news', 'list'),
    'company_news': ('GET', '/company-news', 'list'),
    'company_peers': ('GET', '/stock/peers', 'list'),
    'company_basic_financials': ('GET', '/stock/metric', 'dict'),
    'insider_transactions': ('GET', '/stock/insider-transactions', 'dict'),
    'stock_dividends': ('GET', '/stock/dividend', 'list'),
    'recommendation_trends': ('GET', '/stock/recommendation', 'list'),
    'price_target': ('GET', '/stock/price-target', 'dict'),
    'company_earnings': ('GET', '/stock/earnings', 'list'),
    'earnings_calendar': ('GET', '/calendar/earnings', 'dict'),
    'quote': ('GET', '/quote', 'dict'),
    'stock_candles': ('GET', '/stock/candle', 'dict'),
    'stock_splits': ('GET', '/stock/split', 'list'),
    'forex_rates': ('GET', '/forex/rates', 'dict'),
    'crypto_candles': ('GET', '/crypto/candle', 'dict'),
    'ai_chat': ('POST', '/ai-chat', 'dict'),
}


class FinnhubNode(WorkflowNode):
    integration_type = "automation-finnhub"
    connection_evidence = ConnectionEvidence(noun="market news", operation="get_market_news", label_keys=("headline", "id"), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return FinnhubFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Finnhub API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, path, shape = ROUTES[op.operation]
        values = op.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation"})
        params = {"token": token}
        body = None
        if method == "POST":
            body = {**values, "stream": False}
        else:
            params.update({k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()})
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Accept": "application/json"})
        except (httpx.HTTPError, OSError):
            raise ValueError("Finnhub request could not be confirmed; check connectivity before retrying") from None
        if response.status_code != 200:
            message = "Finnhub request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("error"), str):
                    message = error["error"].replace(token, "[redacted]")[:1000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "message": message}
        if len(response.content) > 20_000_000 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Finnhub returned an unexpected JSON response")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Finnhub returned invalid JSON") from None
        if isinstance(data, dict) and "error" in data:
            raise ValueError(str(data["error"]).replace(token, "[redacted]")[:1000])
        if (shape == "list" and not isinstance(data, list)) or (shape == "dict" and not isinstance(data, dict)):
            raise ValueError("Finnhub returned an unexpected response shape")
        # Preserve provider fields, including no_data candle responses and empty lists.
        def redact(value):
            if isinstance(value, str):
                return value.replace(token, "[redacted]")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {str(k).replace(token, "[redacted]"): redact(v) for k, v in value.items()}
            return value
        output = {"status": "success", "action": op.operation, "data": redact(data)}
        await self.emit(output)
        return output
