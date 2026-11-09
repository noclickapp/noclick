"""Twelve Data market data using a person's pasted API key.

Each operation targets one published endpoint; batch requests contain only fixed
time-series reads, and account usage supplies the connection evidence.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import urlencode, quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.twelvedata.com"
Interval = Literal["1min", "5min", "15min", "30min", "45min", "1h", "2h", "4h", "8h", "1day", "1week", "1month"]


class TwelveDataAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Twelve Data API Key",
        json_schema_extra={
            "x-credential-url": "https://twelvedata.com/account/api-keys",
            "x-credential-instructions": "Paste your API key from the Twelve Data dashboard. NoClick checks your account's API usage. Data availability and credits depend on your plan; premium financials may require an upgrade.",
        })
    credential_type: Literal["twelve_data_api_key"] = Field("twelve_data_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste a Twelve Data API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without an Authorization header or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Symbol(_Input):
    symbol: str = Field(..., min_length=1, max_length=100, description="One instrument, e.g. AAPL, BRK.B, EUR/USD or BTC/USD.")
    exchange: str | None = Field(None, max_length=100, description="Optional exchange name to disambiguate a ticker.")
    mic_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=100)

    @field_validator("symbol")
    @classmethod
    def one_symbol(cls, value):
        if "," in value or any(ord(c) < 32 for c in value):
            raise ValueError("Use one symbol; use batch time series for multiple instruments")
        return value


class _Series(_Symbol):
    interval: Interval = Field(..., description="Time between consecutive data points.")
    outputsize: int = Field(30, ge=1, le=5000, description="Maximum data points. This is a bounded window, not all historical data.")
    start_date: str | None = Field(None, max_length=40, description="YYYY-MM-DD or YYYY-MM-DD HH:MM:SS in the selected timezone.")
    end_date: str | None = Field(None, max_length=40)
    timezone: str | None = Field(None, max_length=100, description="Exchange, UTC or an IANA timezone such as America/New_York.")
    order: Literal["asc", "desc"] = "desc"


class _Financial(_Symbol):
    period: Literal["annual", "quarterly"] = "annual"
    outputsize: int = Field(6, ge=1, le=100, description="Maximum reporting periods to return.")
    start_date: str | None = Field(None, max_length=40)
    end_date: str | None = Field(None, max_length=40)


class _Directory(_Input):
    symbol: str | None = Field(None, max_length=100)
    page: int = Field(1, ge=1, description="Explicit provider page number; increase to read another page.")
    outputsize: int = Field(50, ge=1, le=500, description="Maximum records on this page; this does not fetch the full directory.")


class GetAPIUsage(_Input):
    """Read this API key's current usage and limits."""
    operation: Literal["get_api_usage"] = Field("get_api_usage", json_schema_extra={"ui:hidden": True})


class SearchSymbols(_Input):
    """Find instruments by ticker, name or identifier."""
    operation: Literal["search_symbols"] = Field("search_symbols", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, max_length=100, description="Search query, e.g. AAPL.")
    outputsize: int = Field(30, ge=1, le=120)


class ListStocks(_Directory):
    """Read one page of the stock directory."""
    operation: Literal["list_stocks"] = Field("list_stocks", json_schema_extra={"ui:hidden": True})
    exchange: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)


class ListForexPairs(_Directory):
    """Read one page of available foreign exchange pairs."""
    operation: Literal["list_forex_pairs"] = Field("list_forex_pairs", json_schema_extra={"ui:hidden": True})
    currency_base: str | None = Field(None, max_length=100)
    currency_quote: str | None = Field(None, max_length=100)


class ListCryptocurrencies(_Directory):
    """Read one page of cryptocurrency pairs."""
    operation: Literal["list_cryptocurrencies"] = Field("list_cryptocurrencies", json_schema_extra={"ui:hidden": True})
    exchange: str | None = Field(None, max_length=100)
    currency_base: str | None = Field(None, max_length=100)
    currency_quote: str | None = Field(None, max_length=100)


class GetPrice(_Symbol):
    """Read the latest available instrument price."""
    operation: Literal["get_price"] = Field("get_price", json_schema_extra={"ui:hidden": True})


class GetQuote(_Symbol):
    """Read the latest instrument quote and market metadata."""
    operation: Literal["get_quote"] = Field("get_quote", json_schema_extra={"ui:hidden": True})


class GetTimeSeries(_Series):
    """Read a bounded window of OHLCV history."""
    operation: Literal["get_time_series"] = Field("get_time_series", json_schema_extra={"ui:hidden": True})


class GetExchangeRate(_Input):
    """Read the latest or historical forex or cryptocurrency rate."""
    operation: Literal["get_exchange_rate"] = Field("get_exchange_rate", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=3, max_length=100, pattern=r"^[^,\s/]+/[^,\s/]+$", description="Currency pair, e.g. EUR/USD.")
    date: str | None = Field(None, max_length=40)


class ConvertCurrency(GetExchangeRate):
    """Calculate a currency conversion; does not move funds."""
    operation: Literal["convert_currency"] = Field("convert_currency", json_schema_extra={"ui:hidden": True})
    amount: float = Field(..., ge=0, allow_inf_nan=False, description="Amount of base currency to convert.")


class GetProfile(_Symbol):
    """Read the company profile."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})


class GetStatistics(_Symbol):
    """Read valuation, financial and market statistics."""
    operation: Literal["get_statistics"] = Field("get_statistics", json_schema_extra={"ui:hidden": True})


class GetIncomeStatement(_Financial):
    """Read annual or quarterly income statements."""
    operation: Literal["get_income_statement"] = Field("get_income_statement", json_schema_extra={"ui:hidden": True})


class GetBalanceSheet(_Financial):
    """Read annual or quarterly balance sheets."""
    operation: Literal["get_balance_sheet"] = Field("get_balance_sheet", json_schema_extra={"ui:hidden": True})


class GetCashFlow(_Financial):
    """Read annual or quarterly cash flow statements."""
    operation: Literal["get_cash_flow"] = Field("get_cash_flow", json_schema_extra={"ui:hidden": True})


class ListDividends(_Symbol):
    """Read dividends within an optional date window."""
    operation: Literal["list_dividends"] = Field("list_dividends", json_schema_extra={"ui:hidden": True})
    start_date: str | None = Field(None, max_length=40)
    end_date: str | None = Field(None, max_length=40)


class ListSplits(_Symbol):
    """Read stock splits within an optional date window."""
    operation: Literal["list_splits"] = Field("list_splits", json_schema_extra={"ui:hidden": True})
    start_date: str | None = Field(None, max_length=40)
    end_date: str | None = Field(None, max_length=40)


class ListEarnings(_Symbol):
    """Read a bounded earnings history."""
    operation: Literal["list_earnings"] = Field("list_earnings", json_schema_extra={"ui:hidden": True})
    outputsize: int = Field(12, ge=1, le=100)
    start_date: str | None = Field(None, max_length=40)
    end_date: str | None = Field(None, max_length=40)


class GetRSI(_Series):
    """Read relative strength index values."""
    operation: Literal["get_rsi"] = Field("get_rsi", json_schema_extra={"ui:hidden": True})
    time_period: int = Field(14, ge=1, le=800)


class GetSMA(_Series):
    """Read simple moving average values."""
    operation: Literal["get_sma"] = Field("get_sma", json_schema_extra={"ui:hidden": True})
    time_period: int = Field(9, ge=1, le=800)


class GetMACD(_Series):
    """Read moving average convergence divergence values."""
    operation: Literal["get_macd"] = Field("get_macd", json_schema_extra={"ui:hidden": True})
    fast_period: int = Field(12, ge=1, le=800)
    slow_period: int = Field(26, ge=1, le=800)
    signal_period: int = Field(9, ge=1, le=800)


class BatchTimeSeries(_Input):
    """POST a batch of time-series reads, with individual outcomes preserved."""
    operation: Literal["batch_time_series"] = Field("batch_time_series", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., min_length=1, max_length=1000, description="Comma-separated symbols, e.g. AAPL,MSFT. Maximum 20 unique instruments; each consumes API credits.")
    interval: Interval = Field(...)
    outputsize: int = Field(30, ge=1, le=5000)

    @field_validator("symbols")
    @classmethod
    def batch_symbols(cls, value):
        parts = [p.strip() for p in value.split(",")]
        if not 1 <= len(parts) <= 20 or len(set(parts)) != len(parts) or any(not p or len(p) > 100 or any(ord(c) < 32 for c in p) for p in parts):
            raise ValueError("Provide 1 to 20 distinct comma-separated symbols")
        return ",".join(parts)


TwelveDataConfig = Annotated[Union[GetAPIUsage, SearchSymbols, ListStocks, ListForexPairs,
    ListCryptocurrencies, GetPrice, GetQuote, GetTimeSeries, GetExchangeRate, ConvertCurrency,
    GetProfile, GetStatistics, GetIncomeStatement, GetBalanceSheet, GetCashFlow, ListDividends,
    ListSplits, ListEarnings, GetRSI, GetSMA, GetMACD, BatchTimeSeries], Field(discriminator="operation")]


class TwelveDataFullConfig(NodeConfig[TwelveDataConfig, TwelveDataAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "get_api_usage": "/api_usage", "search_symbols": "/symbol_search", "list_stocks": "/stocks",
    "list_forex_pairs": "/forex_pairs", "list_cryptocurrencies": "/cryptocurrencies",
    "get_price": "/price", "get_quote": "/quote", "get_time_series": "/time_series",
    "get_exchange_rate": "/exchange_rate", "convert_currency": "/currency_conversion",
    "get_profile": "/profile", "get_statistics": "/statistics", "get_income_statement": "/income_statement",
    "get_balance_sheet": "/balance_sheet", "get_cash_flow": "/cash_flow", "list_dividends": "/dividends",
    "list_splits": "/splits", "list_earnings": "/earnings", "get_rsi": "/rsi", "get_sma": "/sma",
    "get_macd": "/macd", "batch_time_series": "/batch",
}


def _redact(value, key):
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items() if k.lower() not in {"apikey", "api_key", "authorization"}}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, str):
        for secret in (key, quote(key, safe="")):
            value = value.replace(secret, "[redacted]")
    return value


class TwelveDataNode(WorkflowNode):
    integration_type = "automation-twelve-data"
    connection_evidence = ConnectionEvidence(operation="get_api_usage", noun="account API usage", label_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return TwelveDataFullConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a Twelve Data API key")
        config, key = self.config.config, self.config.credentials.api_key
        params = config.model_dump(exclude_none=True, exclude={"operation"})
        body = None
        if config.operation == "batch_time_series":
            # URLs are assembled locally, never accepted from workflow input.
            body = {f"req_{i}": {"url": "/time_series?" + urlencode({"symbol": symbol,
                "interval": config.interval, "outputsize": config.outputsize, "apikey": key})}
                for i, symbol in enumerate(config.symbols.split(","), 1)}
            params = {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request("POST" if body is not None else "GET", BASE + ROUTES[config.operation],
                    params=params, **({"json": body} if body is not None else {}),
                    headers={"Accept": "application/json", "Authorization": "apikey " + key})
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise ValueError("Twelve Data request could not be completed or decoded") from None
        if not isinstance(payload, dict):
            raise ValueError("Twelve Data returned an unexpected JSON response")
        if response.status_code != 200 or payload.get("status") == "error" or (isinstance(payload.get("code"), int) and payload["code"] >= 400):
            output = {"status": "error", "success": False, "http_status": response.status_code,
                "status_code": payload.get("code") if type(payload.get("code")) is int and payload["code"] >= 400 else response.status_code,
                "code": payload.get("code"), "error": payload.get("message") or "Twelve Data did not complete this request"}
        else:
            output = {"status": "success", "success": True, "operation": config.operation, "data": payload}
            if config.operation == "get_api_usage":
                if not isinstance(payload.get("timestamp"), str) or any(type(payload.get(k)) is not int or payload[k] < 0 for k in ("current_usage", "plan_limit")):
                    raise ValueError("Twelve Data account usage could not be verified")
                output["items"] = [{"name": f"{payload['current_usage']} requests used of {payload['plan_limit']}/minute", "id": payload["timestamp"]}]
            if body is not None:
                data = payload.get("data")
                if not isinstance(data, dict):
                    raise ValueError("Twelve Data batch results are missing")
                output["complete"] = set(data) == set(body)
                output["success"] = output["complete"] and all(isinstance(v, dict) and v.get("status") == "success" and isinstance(v.get("response"), dict) and v["response"].get("status") != "error" for v in data.values())
                if not output["success"]:
                    output["status"] = "partial"
        output = _redact(output, key)
        await self.emit(output)
        return output
