"""Marketstack v2 market data reads, pinned to the provider's published 2.0.0 API.

Marketstack publishes GET operations only. Each operation makes one request;
limit/offset pagination is explicit and prices retain the provider's units.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.marketstack.com"


class MarketstackAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Marketstack API Key",
        json_schema_extra={
            "x-credential-url": "https://marketstack.com/dashboard",
            "x-credential-instructions": "Paste the API access key from your Marketstack dashboard. Data availability and intraday intervals depend on your plan. The connection read checks key acceptance, not account identity or access to every dataset.",
        })
    credential_type: Literal["marketstack_api_key"] = Field("marketstack_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def ordered_dates(self):
        start, end = getattr(self, "date_from", None), getattr(self, "date_to", None)
        if start and end and start > end:
            raise ValueError("Start date must not follow end date")
        return self


class MarketstackListExchangesConfig(_Input):
    """Stock Exchanges."""
    operation: Literal["list_exchanges"] = Field("list_exchanges", json_schema_extra={"ui:hidden": True})
    search: Optional[str] = Field(None, description='Use this parameter to get autocomplete suggestions by specifying a search term.', min_length=1, max_length=1000)
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetExchangeConfig(_Input):
    """Stock Exchange by MIC."""
    operation: Literal["get_exchange"] = Field("get_exchange", json_schema_extra={"ui:hidden": True})
    mic: str = Field(..., description='Market Identifier Code (MIC) of the stock exchange.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")

class MarketstackListExchangeTickersConfig(_Input):
    """Tickers for an Exchange."""
    operation: Literal["list_exchange_tickers"] = Field("list_exchange_tickers", json_schema_extra={"ui:hidden": True})
    mic: str = Field(..., description='Market Identifier Code (MIC) of the stock exchange.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")
    search: Optional[str] = Field(None, description='Use this parameter to get autocomplete suggestions by specifying a search term.', min_length=1, max_length=1000)
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetTickerConfig(_Input):
    """Ticker by Symbol."""
    operation: Literal["get_ticker"] = Field("get_ticker", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., description='Stock ticker symbol.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")

class MarketstackListEodConfig(_Input):
    """End-of-Day Data."""
    operation: Literal["list_eod"] = Field("list_eod", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., description='Comma-separated list of one or more stock ticker symbols (required for this endpoint). Example: AAPL,MSFT', min_length=1, max_length=1000)
    exchange: Optional[str] = Field(None, description='Filter results by stock exchange, identified by its MIC. Example: XNAS', min_length=1, max_length=1000)
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    date_from: Optional[Date] = Field(None, description='Filter results from a specific start date. [Format: YYYY-MM-DD]')
    date_to: Optional[Date] = Field(None, description='Filter results up to a specific end date. [Format: YYYY-MM-DD]')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetLatestEodConfig(_Input):
    """Latest End-of-Day Data."""
    operation: Literal["get_latest_eod"] = Field("get_latest_eod", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., description='Comma-separated list of one or more stock ticker symbols (required for this endpoint). Example: AAPL,MSFT', min_length=1, max_length=1000)
    exchange: Optional[str] = Field(None, description='Filter results by stock exchange, identified by its MIC. Example: XNAS', min_length=1, max_length=1000)
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetEodOnDateConfig(_Input):
    """End-of-Day Data for a Specific Date."""
    operation: Literal["get_eod_on_date"] = Field("get_eod_on_date", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., description='Comma-separated list of one or more stock ticker symbols (required for this endpoint). Example: AAPL,MSFT', min_length=1, max_length=1000)
    exchange: Optional[str] = Field(None, description='Filter results by stock exchange, identified by its MIC. Example: XNAS', min_length=1, max_length=1000)
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)
    date: Date = Field(..., description='Date in YYYY-MM-DD format.')

class MarketstackListIntradayConfig(_Input):
    """Intraday Data."""
    operation: Literal["list_intraday"] = Field("list_intraday", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., description='Comma-separated list of one or more stock ticker symbols (required for this endpoint). Example: AAPL,MSFT', min_length=1, max_length=1000)
    exchange: Optional[str] = Field(None, description='Filter results by stock exchange, identified by its MIC. Example: XNAS', min_length=1, max_length=1000)
    interval: Literal['1min', '5min', '10min', '15min', '30min', '1hour', '3hour', '6hour', '12hour', '24hour'] = Field('1hour', description='Intraday data interval. Available values: 1min, 5min, 10min, 15min, 30min, 1hour, 3hour, 6hour, 12hour, 24hour. Default: 1hour')
    after_hours: Optional[StrictBool] = Field(None, description='Include after-hours data in intraday results.')
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    date_from: Optional[Date] = Field(None, description='Filter results from a specific start date. [Format: YYYY-MM-DD]')
    date_to: Optional[Date] = Field(None, description='Filter results up to a specific end date. [Format: YYYY-MM-DD]')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetLatestIntradayConfig(_Input):
    """Latest Intraday Data."""
    operation: Literal["get_latest_intraday"] = Field("get_latest_intraday", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., description='Comma-separated list of one or more stock ticker symbols (required for this endpoint). Example: AAPL,MSFT', min_length=1, max_length=1000)
    exchange: Optional[str] = Field(None, description='Filter results by stock exchange, identified by its MIC. Example: XNAS', min_length=1, max_length=1000)
    interval: Literal['1min', '5min', '10min', '15min', '30min', '1hour', '3hour', '6hour', '12hour', '24hour'] = Field('1hour', description='Intraday data interval. Available values: 1min, 5min, 10min, 15min, 30min, 1hour, 3hour, 6hour, 12hour, 24hour. Default: 1hour')
    after_hours: Optional[StrictBool] = Field(None, description='Include after-hours data in intraday results.')
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetIntradayOnDateConfig(_Input):
    """Intraday Data for a Specific Date."""
    operation: Literal["get_intraday_on_date"] = Field("get_intraday_on_date", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., description='Comma-separated list of one or more stock ticker symbols (required for this endpoint). Example: AAPL,MSFT', min_length=1, max_length=1000)
    exchange: Optional[str] = Field(None, description='Filter results by stock exchange, identified by its MIC. Example: XNAS', min_length=1, max_length=1000)
    interval: Literal['1min', '5min', '10min', '15min', '30min', '1hour', '3hour', '6hour', '12hour', '24hour'] = Field('1hour', description='Intraday data interval. Available values: 1min, 5min, 10min, 15min, 30min, 1hour, 3hour, 6hour, 12hour, 24hour. Default: 1hour')
    after_hours: Optional[StrictBool] = Field(None, description='Include after-hours data in intraday results.')
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)
    date: Date = Field(..., description='Date in YYYY-MM-DD format.')

class MarketstackListTickerEodConfig(_Input):
    """Ticker End-of-Day Data."""
    operation: Literal["list_ticker_eod"] = Field("list_ticker_eod", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., description='Stock ticker symbol.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    date_from: Optional[Date] = Field(None, description='Filter results from a specific start date. [Format: YYYY-MM-DD]')
    date_to: Optional[Date] = Field(None, description='Filter results up to a specific end date. [Format: YYYY-MM-DD]')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetLatestTickerEodConfig(_Input):
    """Ticker Latest End-of-Day Data."""
    operation: Literal["get_latest_ticker_eod"] = Field("get_latest_ticker_eod", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., description='Stock ticker symbol.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetTickerEodOnDateConfig(_Input):
    """Ticker End-of-Day Data for a Date."""
    operation: Literal["get_ticker_eod_on_date"] = Field("get_ticker_eod_on_date", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., description='Stock ticker symbol.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")
    date: Date = Field(..., description='Date in YYYY-MM-DD format.')
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackListTickerIntradayConfig(_Input):
    """Ticker Intraday Data."""
    operation: Literal["list_ticker_intraday"] = Field("list_ticker_intraday", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., description='Stock ticker symbol.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")
    interval: Literal['1min', '5min', '10min', '15min', '30min', '1hour', '3hour', '6hour', '12hour', '24hour'] = Field('1hour', description='Intraday data interval. Available values: 1min, 5min, 10min, 15min, 30min, 1hour, 3hour, 6hour, 12hour, 24hour. Default: 1hour')
    after_hours: Optional[StrictBool] = Field(None, description='Include after-hours data in intraday results.')
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    date_from: Optional[Date] = Field(None, description='Filter results from a specific start date. [Format: YYYY-MM-DD]')
    date_to: Optional[Date] = Field(None, description='Filter results up to a specific end date. [Format: YYYY-MM-DD]')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetLatestTickerIntradayConfig(_Input):
    """Ticker Latest Intraday Data."""
    operation: Literal["get_latest_ticker_intraday"] = Field("get_latest_ticker_intraday", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., description='Stock ticker symbol.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")
    interval: Literal['1min', '5min', '10min', '15min', '30min', '1hour', '3hour', '6hour', '12hour', '24hour'] = Field('1hour', description='Intraday data interval. Available values: 1min, 5min, 10min, 15min, 30min, 1hour, 3hour, 6hour, 12hour, 24hour. Default: 1hour')
    after_hours: Optional[StrictBool] = Field(None, description='Include after-hours data in intraday results.')
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetTickerIntradayOnDateConfig(_Input):
    """Ticker Intraday Data for a Date."""
    operation: Literal["get_ticker_intraday_on_date"] = Field("get_ticker_intraday_on_date", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., description='Stock ticker symbol.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")
    date: Date = Field(..., description='Date in YYYY-MM-DD format.')
    interval: Literal['1min', '5min', '10min', '15min', '30min', '1hour', '3hour', '6hour', '12hour', '24hour'] = Field('1hour', description='Intraday data interval. Available values: 1min, 5min, 10min, 15min, 30min, 1hour, 3hour, 6hour, 12hour, 24hour. Default: 1hour')
    after_hours: Optional[StrictBool] = Field(None, description='Include after-hours data in intraday results.')
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackListSplitsConfig(_Input):
    """Stock Splits."""
    operation: Literal["list_splits"] = Field("list_splits", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., description='Comma-separated list of one or more stock ticker symbols. Example: AAPL,MSFT', min_length=1, max_length=1000)
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    date_from: Optional[Date] = Field(None, description='Filter results from a specific start date. [Format: YYYY-MM-DD]')
    date_to: Optional[Date] = Field(None, description='Filter results up to a specific end date. [Format: YYYY-MM-DD]')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackListDividendsConfig(_Input):
    """Stock Dividends."""
    operation: Literal["list_dividends"] = Field("list_dividends", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., description='Comma-separated list of one or more stock ticker symbols. Example: AAPL,MSFT', min_length=1, max_length=1000)
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    date_from: Optional[Date] = Field(None, description='Filter results from a specific start date. [Format: YYYY-MM-DD]')
    date_to: Optional[Date] = Field(None, description='Filter results up to a specific end date. [Format: YYYY-MM-DD]')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackListTickerSplitsConfig(_Input):
    """Ticker Stock Splits."""
    operation: Literal["list_ticker_splits"] = Field("list_ticker_splits", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., description='Stock ticker symbol.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    date_from: Optional[Date] = Field(None, description='Filter results from a specific start date. [Format: YYYY-MM-DD]')
    date_to: Optional[Date] = Field(None, description='Filter results up to a specific end date. [Format: YYYY-MM-DD]')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackListTickerDividendsConfig(_Input):
    """Ticker Stock Dividends."""
    operation: Literal["list_ticker_dividends"] = Field("list_ticker_dividends", json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., description='Stock ticker symbol.', min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9^][A-Za-z0-9_.^:-]{0,99}$")
    sort: Literal['DESC', 'ASC', 'desc', 'asc'] = Field('DESC', description='Sort order of the results by date.')
    date_from: Optional[Date] = Field(None, description='Filter results from a specific start date. [Format: YYYY-MM-DD]')
    date_to: Optional[Date] = Field(None, description='Filter results up to a specific end date. [Format: YYYY-MM-DD]')
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackListTimezonesConfig(_Input):
    """Supported Timezones."""
    operation: Literal["list_timezones"] = Field("list_timezones", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackListCurrenciesConfig(_Input):
    """Supported Currencies."""
    operation: Literal["list_currencies"] = Field("list_currencies", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackListTickersConfig(_Input):
    """List Tickers."""
    operation: Literal["list_tickers"] = Field("list_tickers", json_schema_extra={"ui:hidden": True})
    search: Optional[str] = Field(None, description='Use this parameter to get autocomplete suggestions by specifying a search term.', min_length=1, max_length=1000)
    exchange: Optional[str] = Field(None, description='Filter results by stock exchange, identified by its MIC. Example: XNAS', min_length=1, max_length=1000)
    limit: int = Field(100, description='Specify a limit of results to return. Default value is 100.', ge=1, le=1000)
    offset: int = Field(0, description='Specify an offset for pagination. Default offset value is 0.', ge=0)

class MarketstackGetTickerInfoConfig(_Input):
    """Ticker Information."""
    operation: Literal["get_ticker_info"] = Field("get_ticker_info", json_schema_extra={"ui:hidden": True})
    ticker: str = Field(..., description='Stock ticker symbol. Example: AAPL', min_length=1, max_length=1000)

class MarketstackGetStockPriceConfig(_Input):
    """Real-Time Stock Price."""
    operation: Literal["get_stock_price"] = Field("get_stock_price", json_schema_extra={"ui:hidden": True})
    ticker: str = Field(..., description='Stock ticker symbol, e.g. AAPL.', min_length=1, max_length=1000)
    exchange: Optional[str] = Field(None, description='Exchange MIC code, e.g. XNAS, XLON. Use it when a ticker is listed on more than one exchange.', min_length=1, max_length=1000)

MarketstackOperation = Annotated[Union[
    MarketstackListExchangesConfig,
    MarketstackGetExchangeConfig,
    MarketstackListExchangeTickersConfig,
    MarketstackGetTickerConfig,
    MarketstackListEodConfig,
    MarketstackGetLatestEodConfig,
    MarketstackGetEodOnDateConfig,
    MarketstackListIntradayConfig,
    MarketstackGetLatestIntradayConfig,
    MarketstackGetIntradayOnDateConfig,
    MarketstackListTickerEodConfig,
    MarketstackGetLatestTickerEodConfig,
    MarketstackGetTickerEodOnDateConfig,
    MarketstackListTickerIntradayConfig,
    MarketstackGetLatestTickerIntradayConfig,
    MarketstackGetTickerIntradayOnDateConfig,
    MarketstackListSplitsConfig,
    MarketstackListDividendsConfig,
    MarketstackListTickerSplitsConfig,
    MarketstackListTickerDividendsConfig,
    MarketstackListTimezonesConfig,
    MarketstackListCurrenciesConfig,
    MarketstackListTickersConfig,
    MarketstackGetTickerInfoConfig,
    MarketstackGetStockPriceConfig
], Field(discriminator="operation")]


class MarketstackFullConfig(NodeConfig[MarketstackOperation, MarketstackAPIKeyCredential]):
    pass


ROUTES = {'list_exchanges': '/v2/exchanges', 'get_exchange': '/v2/exchanges/{mic}', 'list_exchange_tickers': '/v2/exchanges/{mic}/tickers', 'get_ticker': '/v2/tickers/{symbol}', 'list_eod': '/v2/eod', 'get_latest_eod': '/v2/eod/latest', 'get_eod_on_date': '/v2/eod/{date}', 'list_intraday': '/v2/intraday', 'get_latest_intraday': '/v2/intraday/latest', 'get_intraday_on_date': '/v2/intraday/{date}', 'list_ticker_eod': '/v2/tickers/{symbol}/eod', 'get_latest_ticker_eod': '/v2/tickers/{symbol}/eod/latest', 'get_ticker_eod_on_date': '/v2/tickers/{symbol}/eod/{date}', 'list_ticker_intraday': '/v2/tickers/{symbol}/intraday', 'get_latest_ticker_intraday': '/v2/tickers/{symbol}/intraday/latest', 'get_ticker_intraday_on_date': '/v2/tickers/{symbol}/intraday/{date}', 'list_splits': '/v2/splits', 'list_dividends': '/v2/dividends', 'list_ticker_splits': '/v2/tickers/{symbol}/splits', 'list_ticker_dividends': '/v2/tickers/{symbol}/dividends', 'list_timezones': '/v2/timezones', 'list_currencies': '/v2/currencies', 'list_tickers': '/v2/tickerslist', 'get_ticker_info': '/v2/tickerinfo', 'get_stock_price': '/v2/stockprice'}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items() if key.lower() not in {"access_key", "api_key"}}
    return value


class MarketstackNode(WorkflowNode):
    integration_type = "automation-marketstack"
    connection_evidence = ConnectionEvidence(
        noun="stock exchanges", operation="list_exchanges", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return MarketstackFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Marketstack API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        route = ROUTES[config.operation]
        params = {"access_key": secret}
        for name, value in config.model_dump(mode="json", exclude_none=True).items():
            if name == "operation":
                continue
            marker = "{" + name + "}"
            if marker in route:
                route = route.replace(marker, quote(str(value), safe=""))
            else:
                params[name] = str(value).lower() if isinstance(value, bool) else value
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request("GET", BASE + route, params=params, headers={"Accept": "application/json"})
            if response.status_code != 200:
                # Never echo request URLs: Marketstack authenticates in the query.
                message = "Marketstack request failed"
                try:
                    error = response.json().get("error", {})
                    if isinstance(error, dict) and isinstance(error.get("info"), str):
                        message = error["info"][:2000]
                except (ValueError, AttributeError):
                    pass
                result = {"status": "error", "http_status": response.status_code, "message": message}
            else:
                if len(response.content) > 10_000_000:
                    raise ValueError("Marketstack response exceeds the size limit")
                body = response.json()
                if not isinstance(body, dict) or body.get("success") is False or "error" in body:
                    raise ValueError("Marketstack returned an error or unexpected response")
                if not body:
                    raise ValueError("Marketstack returned an empty response object")
                result = {"status": "success", "data": body.get("data", body)}
                pagination = body.get("pagination")
                if pagination is not None:
                    if not isinstance(pagination, dict):
                        raise ValueError("Marketstack pagination is invalid")
                    result["pagination"] = pagination
                    keys = ("offset", "count", "total")
                    if all(type(pagination.get(k)) is int and pagination[k] >= 0 for k in keys):
                        next_offset = pagination["offset"] + pagination["count"]
                        has_more = next_offset < pagination["total"]
                        if has_more and pagination["count"] == 0:
                            raise ValueError("Marketstack pagination did not advance")
                        result.update(has_more=has_more, next_offset=next_offset if has_more else None)
        except (httpx.HTTPError, ValueError, TypeError):
            result = {"status": "error", "message": "Marketstack request could not be completed; check the key, plan and parameters"}
        result = _redact(result, secret)
        await self.emit(result)
        return result
