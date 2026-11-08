"""EODHD Financial Data API v2: fixed read operations and pasted API tokens.

Contract: https://github.com/EodHistoricalData/EODHD-openapi (2.0.0).
The published contract offers GET operations only. Pages are explicit; no hidden
pagination or retry multiplies the provider's per-request API charges.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://eodhd.com/api"
CREDENTIAL_TYPE = "eodhd_apis_api_token"


class EodhdApisAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="EODHD API Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://eodhd.com/cp/settings",
            "x-credential-instructions": "Paste your EODHD API token from your account settings. Your subscription determines which datasets you can read. NoClick verifies it with the User API.",
        },
    )
    credential_type: Literal["eodhd_apis_api_token"] = Field(
        CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API token",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the token without a prefix or whitespace")
        return value


class _ReadConfig(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="after")
    def date_order(self):
        start, end = getattr(self, "from_date", None), getattr(self, "to_date", None)
        if start is not None and end is not None and start > end:
            raise ValueError("The end must be on or after the start")
        return self


class EodhdGetUserConfig(_ReadConfig):
    """Get current user details."""

    operation: Literal["get_user"] = Field(
        "get_user", title="Get User", json_schema_extra={"ui:hidden": True}
    )


class EodhdGetEodPricesConfig(_ReadConfig):
    """Retrieve end-of-day historical price data."""

    operation: Literal["get_eod_prices"] = Field(
        "get_eod_prices", title="Get EOD Prices", json_schema_extra={"ui:hidden": True}
    )
    ticker: str = Field(
        ..., min_length=1, max_length=1000, description="Ticker symbol of the company"
    )
    from_date: date | None = Field(
        None, description="Start date for historical data (YYYY-MM-DD)"
    )
    to_date: date | None = Field(
        None, description="End date for historical data (YYYY-MM-DD)"
    )
    period: Literal["d", "w", "m"] | None = Field(
        None,
        description="Data period (e.g., 'd' for daily, 'w' for weekly, 'm' for monthly)",
    )
    filter: Literal[
        "last_date", "last_open", "last_high", "last_low", "last_close", "last_volume"
    ] | None = Field(None, description="Filter for specific last known data points")


class EodhdGetLivePricesConfig(_ReadConfig):
    """Retrieve delayed real-time stock prices."""

    operation: Literal["get_live_prices"] = Field(
        "get_live_prices",
        title="Get Live Prices",
        json_schema_extra={"ui:hidden": True},
    )
    ticker: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Ticker symbol with exchange code (e.g., 'AAPL.US').",
    )
    symbols: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Comma-separated list of additional ticker symbols for multiple requests in a single call (e.g., 'VTI,EUR.FOREX').",
    )
    ex: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Exchange code filter (e.g., 'US').",
    )


class EodhdGetIntradayPricesConfig(_ReadConfig):
    """Retrieve intraday historical price data."""

    operation: Literal["get_intraday_prices"] = Field(
        "get_intraday_prices",
        title="Get Intraday Prices",
        json_schema_extra={"ui:hidden": True},
    )
    ticker: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Ticker symbol with exchange code (e.g., 'AAPL.US').",
    )
    interval: Literal["1m", "5m", "15m", "30m", "1h"] = Field(
        ...,
        description="Interval for data points. Options are '1m' (1 minute), '5m' (5 minutes), '15m' (15 minutes), '30m' (30 minutes), and '1h' (1 hour).",
    )
    from_timestamp: int | None = Field(
        None,
        description="Start datetime in Unix timestamp (UTC). For example, 1627896900 for '2021-08-02 09:35:00'.",
    )
    to_timestamp: int | None = Field(
        None,
        description="End datetime in Unix timestamp (UTC). For example, 1630575300 for '2021-09-02 09:35:00'.",
    )


class EodhdGetFundamentalsConfig(_ReadConfig):
    """Retrieve filtered fundamental data for a specific symbol."""

    operation: Literal["get_fundamentals"] = Field(
        "get_fundamentals",
        title="Get Fundamentals",
        json_schema_extra={"ui:hidden": True},
    )
    ticker: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The ticker symbol in the format SYMBOL.EXCHANGE, e.g., 'AAPL.US' for Apple Inc. on NASDAQ.",
    )
    filter: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Filter parameter to specify data section and optional sub-sections, e.g., `Financials::Balance_Sheet::quarterly::2024-06-30`. Supported sections include General, Highlights, Valuation, SharesStats, Technicals, SplitsDividends, AnalystRatings, Holders, InsiderTransactions, ESGScores, outstandingShares, Earnings, and Financials. When omitted, returns all sections.",
    )
    historical: Literal[0, 1] | None = Field(
        None,
        description="Set to 1 to return historical data for certain sections (e.g., outstandingShares).",
    )
    from_date: date | None = Field(
        None, description="Start date for historical data in 'YYYY-MM-DD' format."
    )
    to_date: date | None = Field(
        None, description="End date for historical data in 'YYYY-MM-DD' format."
    )
    version: int | None = Field(None, description="API version for response format.")
    no_cache: Literal[0, 1] | None = Field(
        None, description="Set to 1 to bypass cache and get fresh data."
    )


class EodhdSearchSymbolsConfig(_ReadConfig):
    """Search stocks, companies, and ISINs."""

    operation: Literal["search_symbols"] = Field(
        "search_symbols", title="Search Symbols", json_schema_extra={"ui:hidden": True}
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The search query (e.g., 'AAPL', 'Amazon', or ISIN 'US3453708600')",
    )
    limit: int | None = Field(None, description="Limit the number of results returned")
    security_type: Literal[
        "all", "stock", "etf", "fund", "bond", "index", "crypto"
    ] | None = Field(None, description="Filter by security type.")
    exchange: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Filter by exchange code (e.g., 'US', 'LSE').",
    )
    bonds_only: Literal[0, 1] | None = Field(
        None, description="Set to 1 to return bonds only."
    )


class EodhdListExchangesConfig(_ReadConfig):
    """List supported exchanges."""

    operation: Literal["list_exchanges"] = Field(
        "list_exchanges", title="List Exchanges", json_schema_extra={"ui:hidden": True}
    )


class EodhdListExchangeSymbolsConfig(_ReadConfig):
    """Retrieve the list of tickers for a specific exchange.."""

    operation: Literal["list_exchange_symbols"] = Field(
        "list_exchange_symbols",
        title="List Exchange Symbols",
        json_schema_extra={"ui:hidden": True},
    )
    exchange: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Exchange code, e.g., 'PSE' for the Philippines Stock Exchange or 'US' for combined US exchanges.",
    )
    delisted: Literal[0, 1] | None = Field(
        None, description="Include delisted (inactive) tickers. Set to '1' to include."
    )
    security_type: Literal[
        "common_stock", "preferred_stock", "stock", "etf", "fund"
    ] | None = Field(
        None,
        description="Filter by ticker type. Options: 'common_stock', 'preferred_stock', 'stock', 'etf', 'fund'.",
    )


class EodhdGetExchangeDetailsConfig(_ReadConfig):
    """Retrieve details for a specific exchange."""

    operation: Literal["get_exchange_details"] = Field(
        "get_exchange_details",
        title="Get Exchange Details",
        json_schema_extra={"ui:hidden": True},
    )
    exchange: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Exchange code for which details are to be retrieved (e.g., 'US' for the USA exchange).",
    )
    from_date: date | None = Field(
        None,
        description="Start date for holiday data (YYYY-MM-DD). Defaults to 6 months before the current date.",
    )
    to_date: date | None = Field(
        None,
        description="End date for holiday data (YYYY-MM-DD). Defaults to 6 months after the current date.",
    )
    format_version: int | None = Field(None, description="Response format version.")


class EodhdGetNewsConfig(_ReadConfig):
    """Retrieve financial news articles."""

    operation: Literal["get_news"] = Field(
        "get_news", title="Get News", json_schema_extra={"ui:hidden": True}
    )
    symbols: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Ticker code to get news for (e.g., 'AAPL.US'). Required if 't' is not provided.",
    )
    tag: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Tag to get news on a given topic. Required if 's' is not provided.",
    )
    from_date: date | None = Field(
        None, description="Start date for news data (YYYY-MM-DD)"
    )
    to_date: date | None = Field(
        None, description="End date for news data (YYYY-MM-DD)"
    )
    limit: int | None = Field(
        None, ge=1, le=1000, description="The number of results to return"
    )
    offset: int | None = Field(
        None,
        ge=0,
        le=9000,
        description="The offset of the data. Maximum 9000; to reach older articles, narrow the period with from and to",
    )


class EodhdGetSentimentConfig(_ReadConfig):
    """Retrieve market news sentiment data."""

    operation: Literal["get_sentiment"] = Field(
        "get_sentiment", title="Get Sentiment", json_schema_extra={"ui:hidden": True}
    )
    symbols: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Comma-separated list of ticker codes to retrieve sentiment data for (e.g., 'btc-usd.cc,aapl.us').",
    )
    from_date: date | None = Field(
        None, description="Start date for sentiment data (YYYY-MM-DD)."
    )
    to_date: date | None = Field(
        None, description="End date for sentiment data (YYYY-MM-DD)."
    )


class EodhdGetDividendsConfig(_ReadConfig):
    """Retrieve historical dividend data."""

    operation: Literal["get_dividends"] = Field(
        "get_dividends", title="Get Dividends", json_schema_extra={"ui:hidden": True}
    )
    ticker: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Ticker symbol of the stock in the format {SYMBOL_NAME}.{EXCHANGE_ID} (e.g., 'AAPL.US' for NASDAQ or 'AAPL.MX' for the Mexican Stock Exchange).",
    )
    from_date: date | None = Field(
        None,
        description="Start date for data retrieval in 'YYYY-MM-DD' format. Defaults to earliest available data if not provided.",
    )
    to_date: date | None = Field(
        None,
        description="End date for data retrieval in 'YYYY-MM-DD' format. Defaults to latest available data if not provided.",
    )


class EodhdGetSplitsConfig(_ReadConfig):
    """Retrieve historical split data."""

    operation: Literal["get_splits"] = Field(
        "get_splits", title="Get Splits", json_schema_extra={"ui:hidden": True}
    )
    ticker: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Ticker symbol of the stock in the format {SYMBOL_NAME}.{EXCHANGE_ID} (e.g., 'AAPL.US' for NASDAQ or 'AAPL.MX' for the Mexican Stock Exchange).",
    )
    from_date: date | None = Field(
        None,
        description="Start date for data retrieval in 'YYYY-MM-DD' format. Defaults to earliest available data if not provided.",
    )
    to_date: date | None = Field(
        None,
        description="End date for data retrieval in 'YYYY-MM-DD' format. Defaults to latest available data if not provided.",
    )


class EodhdGetEarningsCalendarConfig(_ReadConfig):
    """Retrieve upcoming earnings data."""

    operation: Literal["get_earnings_calendar"] = Field(
        "get_earnings_calendar",
        title="Get Earnings Calendar",
        json_schema_extra={"ui:hidden": True},
    )
    from_date: date | None = Field(
        None,
        description="Start date for earnings data, in 'YYYY-MM-DD' format. Defaults to today if not provided.",
    )
    to_date: date | None = Field(
        None,
        description="End date for earnings data, in 'YYYY-MM-DD' format. Defaults to 7 days from today if not provided.",
    )
    symbols: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Specific symbols to retrieve earnings data for, separated by commas (e.g., 'AAPL.US,MSFT.US'). Overrides the 'from' and 'to' parameters if used.",
    )


class EodhdGetIpoCalendarConfig(_ReadConfig):
    """Retrieve upcoming IPO data."""

    operation: Literal["get_ipo_calendar"] = Field(
        "get_ipo_calendar",
        title="Get IPO Calendar",
        json_schema_extra={"ui:hidden": True},
    )
    from_date: date | None = Field(
        None,
        description="Start date for IPO data in 'YYYY-MM-DD' format. Defaults to today if not provided.",
    )
    to_date: date | None = Field(
        None,
        description="End date for IPO data in 'YYYY-MM-DD' format. Defaults to 7 days from today if not provided.",
    )


class EodhdGetSplitsCalendarConfig(_ReadConfig):
    """Retrieve upcoming and historical stock splits."""

    operation: Literal["get_splits_calendar"] = Field(
        "get_splits_calendar",
        title="Get Splits Calendar",
        json_schema_extra={"ui:hidden": True},
    )
    from_date: date | None = Field(
        None,
        description="Start date for split data in 'YYYY-MM-DD' format. Defaults to today if not provided.",
    )
    to_date: date | None = Field(
        None,
        description="End date for split data in 'YYYY-MM-DD' format. Defaults to 7 days from today if not provided.",
    )


class EodhdGetDividendsCalendarConfig(_ReadConfig):
    """Retrieve upcoming dividends calendar."""

    operation: Literal["get_dividends_calendar"] = Field(
        "get_dividends_calendar",
        title="Get Dividends Calendar",
        json_schema_extra={"ui:hidden": True},
    )
    date_eq: date | None = Field(
        None,
        description="Exact date in 'YYYY-MM-DD' format. Required if `filter[symbol]` is not present.\n",
    )
    date_from: date | None = Field(
        None, description="Start date in 'YYYY-MM-DD' format."
    )
    date_to: date | None = Field(None, description="End date in 'YYYY-MM-DD' format.")
    symbol: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Ticker symbol (e.g., 'AAPL.US'). When provided, `filter[date_eq]` may be omitted.\n",
    )
    limit: int | None = Field(
        None, ge=1, le=10000, description="Number of records per page (1-10000)."
    )
    offset: int | None = Field(
        None, ge=0, le=1000000, description="Pagination offset (0-1000000)."
    )


class EodhdGetTechnicalIndicatorConfig(_ReadConfig):
    """Retrieve technical indicator data for a specified symbol.."""

    operation: Literal["get_technical_indicator"] = Field(
        "get_technical_indicator",
        title="Get Technical Indicator",
        json_schema_extra={"ui:hidden": True},
    )
    ticker: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Symbol in the format {SYMBOL_NAME}.{EXCHANGE_ID}, e.g., AAPL.US for Apple Inc.",
    )
    function_name: Literal[
        "sma",
        "ema",
        "wma",
        "volatility",
        "stochastic",
        "rsi",
        "stddev",
        "stochrsi",
        "slope",
        "dmi",
        "adx",
        "macd",
        "atr",
        "cci",
        "sar",
        "beta",
        "bbands",
        "splitadjusted",
        "avgvol",
        "avgvolccy",
    ] = Field(
        ...,
        description="The function to calculate the technical indicator (e.g., 'sma' for Simple Moving Average).",
    )
    period: int | None = Field(
        None,
        ge=2,
        le=100000,
        description="Number of data points used to calculate the indicator. Default is 50.",
    )
    from_date: date | None = Field(
        None, description="Start date for data retrieval in 'YYYY-MM-DD' format."
    )
    to_date: date | None = Field(
        None, description="End date for data retrieval in 'YYYY-MM-DD' format."
    )
    order: Literal["a", "d"] | None = Field(
        None,
        description="Sort order of dates: 'a' for ascending, 'd' for descending. Default is ascending.",
    )
    splitadjusted_only: Literal[0, 1] | None = Field(
        None,
        description="For select functions, adjust data only for splits by setting to '1'. Default is '0'.",
    )
    filter: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Retrieve only the last value by specifying 'last_ema' or 'last_volume' as the filter.",
    )


EodhdApisOperation = Annotated[
    Union[
        EodhdGetUserConfig,
        EodhdGetEodPricesConfig,
        EodhdGetLivePricesConfig,
        EodhdGetIntradayPricesConfig,
        EodhdGetFundamentalsConfig,
        EodhdSearchSymbolsConfig,
        EodhdListExchangesConfig,
        EodhdListExchangeSymbolsConfig,
        EodhdGetExchangeDetailsConfig,
        EodhdGetNewsConfig,
        EodhdGetSentimentConfig,
        EodhdGetDividendsConfig,
        EodhdGetSplitsConfig,
        EodhdGetEarningsCalendarConfig,
        EodhdGetIpoCalendarConfig,
        EodhdGetSplitsCalendarConfig,
        EodhdGetDividendsCalendarConfig,
        EodhdGetTechnicalIndicatorConfig,
    ],
    Field(discriminator="operation"),
]


class EodhdApisNodeConfig(NodeConfig[EodhdApisOperation, EodhdApisAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Each entry maps to one provider operation; query names are never caller supplied.
# (path, path field mapping, query field mapping, supports fmt=json)
ROUTES = {
    "get_user": ("/user", {}, {}, True),
    "get_eod_prices": (
        "/eod/{ticker}",
        {"ticker": "ticker"},
        {"from_date": "from", "to_date": "to", "period": "period", "filter": "filter"},
        True,
    ),
    "get_live_prices": (
        "/real-time/{ticker}",
        {"ticker": "ticker"},
        {"symbols": "s", "ex": "ex"},
        True,
    ),
    "get_intraday_prices": (
        "/intraday/{ticker}",
        {"ticker": "ticker"},
        {"interval": "interval", "from_timestamp": "from", "to_timestamp": "to"},
        True,
    ),
    "get_fundamentals": (
        "/fundamentals/{ticker}",
        {"ticker": "ticker"},
        {
            "filter": "filter",
            "historical": "historical",
            "from_date": "from",
            "to_date": "to",
            "version": "version",
            "no_cache": "no_cache",
        },
        False,
    ),
    "search_symbols": (
        "/search/{query}",
        {"query": "query"},
        {
            "limit": "limit",
            "security_type": "type",
            "exchange": "exchange",
            "bonds_only": "bonds_only",
        },
        True,
    ),
    "list_exchanges": ("/exchanges-list", {}, {}, True),
    "list_exchange_symbols": (
        "/exchange-symbol-list/{exchangeCode}",
        {"exchangeCode": "exchange"},
        {"delisted": "delisted", "security_type": "type"},
        True,
    ),
    "get_exchange_details": (
        "/exchange-details/{EXCHANGE_CODE}",
        {"EXCHANGE_CODE": "exchange"},
        {"from_date": "from", "to_date": "to", "format_version": "format_version"},
        True,
    ),
    "get_news": (
        "/news",
        {},
        {
            "symbols": "s",
            "tag": "t",
            "from_date": "from",
            "to_date": "to",
            "limit": "limit",
            "offset": "offset",
        },
        True,
    ),
    "get_sentiment": (
        "/sentiments",
        {},
        {"symbols": "s", "from_date": "from", "to_date": "to"},
        True,
    ),
    "get_dividends": (
        "/div/{ticker}",
        {"ticker": "ticker"},
        {"from_date": "from", "to_date": "to"},
        True,
    ),
    "get_splits": (
        "/splits/{ticker}",
        {"ticker": "ticker"},
        {"from_date": "from", "to_date": "to"},
        True,
    ),
    "get_earnings_calendar": (
        "/calendar/earnings",
        {},
        {"from_date": "from", "to_date": "to", "symbols": "symbols"},
        True,
    ),
    "get_ipo_calendar": (
        "/calendar/ipos",
        {},
        {"from_date": "from", "to_date": "to"},
        True,
    ),
    "get_splits_calendar": (
        "/calendar/splits",
        {},
        {"from_date": "from", "to_date": "to"},
        True,
    ),
    "get_dividends_calendar": (
        "/calendar/dividends",
        {},
        {
            "date_eq": "filter[date_eq]",
            "date_from": "filter[date_from]",
            "date_to": "filter[date_to]",
            "symbol": "filter[symbol]",
            "limit": "page[limit]",
            "offset": "page[offset]",
        },
        True,
    ),
    "get_technical_indicator": (
        "/technical/{ticker}",
        {"ticker": "ticker"},
        {
            "function_name": "function",
            "period": "period",
            "from_date": "from",
            "to_date": "to",
            "order": "order",
            "splitadjusted_only": "splitadjusted_only",
            "filter": "filter",
        },
        True,
    ),
}


class EodhdApisNode(WorkflowNode):
    integration_type = "automation-eodhd-apis"
    connection_evidence = ConnectionEvidence(
        noun="EODHD account", identity_operation="get_user"
    )

    @classmethod
    def get_config_model(cls):
        return EodhdApisNodeConfig

    @classmethod
    def declared_output_keys(cls, config):
        return ["status", "operation", "data"]

    async def execute(self, input_data):
        full = self.config
        if not full or not full.credentials:
            raise ValueError("Connect an EODHD API token")
        config, credential = full.config, full.credentials
        path, path_fields, query_fields, fmt = ROUTES[config.operation]
        for placeholder, field in path_fields.items():
            value = str(getattr(config, field))
            if (
                value in {".", ".."}
                or "/" in value
                or "\\" in value
                or any(ord(c) < 32 for c in value)
            ):
                raise ValueError(
                    "Use a single EODHD symbol, exchange code or search term"
                )
            path = path.replace("{" + placeholder + "}", quote(value, safe=""))
        params = {"api_token": credential.api_token}
        if fmt:
            params["fmt"] = "json"
        for field, query in query_fields.items():
            value = getattr(config, field)
            if value is not None:
                params[query] = value.isoformat() if isinstance(value, date) else value
        output = {"operation": config.operation}
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    "GET",
                    BASE_URL + path,
                    params=params,
                    headers={"Accept": "application/json"},
                )
            if not 200 <= response.status_code < 300:
                # Preserve provider rejection text for connection evidence, without
                # disclosing query credentials echoed by an upstream error page.
                message = response.text[:1000].replace(
                    credential.api_token, "[redacted]"
                )
                return {
                    **output,
                    "status": "error",
                    "http_status": response.status_code,
                    "error": message or "EODHD rejected the request",
                }
            media = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if media != "application/json" and not media.endswith("+json"):
                raise ValueError("EODHD returned a non-JSON response")
            data = response.json()
            if isinstance(data, dict) and (
                data.get("error") or data.get("errors") or data.get("success") is False
            ):
                return {
                    **output,
                    "status": "error",
                    "error": str(
                        data.get("error")
                        or data.get("errors")
                        or "EODHD rejected the request"
                    ).replace(credential.api_token, "[redacted]")[:1000],
                }
            if config.operation == "get_user":
                if not isinstance(data, dict) or not any(
                    isinstance(data.get(key), str) and data[key].strip()
                    for key in ("name", "email")
                ):
                    raise ValueError("EODHD user response must identify the subscriber")
                # Return documented account fields only, excluding token-like extras.
                data = {
                    key: data[key]
                    for key in (
                        "name",
                        "email",
                        "subscriptionType",
                        "paymentMethod",
                        "apiRequests",
                        "apiRequestsDate",
                        "dailyRateLimit",
                    )
                    if key in data
                }
            return {**output, "status": "success", "data": data}
        except (httpx.HTTPError, SSRFError):
            return {
                **output,
                "status": "error",
                "error": "EODHD request could not be completed",
            }
        except ValueError:
            return {
                **output,
                "status": "error",
                "error": "EODHD returned an invalid JSON response",
            }
