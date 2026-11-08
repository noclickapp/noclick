"""Financial Datasets API v1.0.0: fixed, single-request data queries.

Contract: https://www.financialdatasets.ai/openapi.json
Authentication: https://docs.financialdatasets.ai/quickstart
Pagination is explicit: copy next_cursor into the same operation for another page.
POST operations search data; account signup and billing mutations are not exposed.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.financialdatasets.ai"


class FinancialDatasetsAIAPIKey(BaseModel):
    model_config = ConfigDict(title="Financial Datasets AI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.financialdatasets.ai/",
            "x-credential-instructions": "Generate an API key in your Financial Datasets dashboard and paste it here. Paid datasets require sufficient account credits. The news probe checks key acceptance, not account identity.",
        })
    credential_type: Literal["financial_datasets_ai_api_key"] = Field("financial_datasets_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_dates(self):
        values = self.model_dump()
        for name, value in values.items():
            if value is not None and (name.startswith("filing_date") or name.startswith("report_period") or name in {"start_date", "end_date", "as_of"}):
                date.fromisoformat(value)
        if values.get("start_date") and values.get("end_date") and self.start_date > self.end_date:
            raise ValueError("Start date must be on or before end date")
        return self


class _CompanyInput(_Input):
    @model_validator(mode="after")
    def require_company(self):
        if not any(getattr(self, name, None) for name in ("ticker", "cik", "isin")):
            raise ValueError("Supply a ticker, CIK or ISIN")
        return self


class FinancialFilter(BaseModel):
    field: str = Field(..., min_length=1)
    operator: Literal["gt", "lt", "gte", "lte", "eq", "in"]
    value: Union[float, str, list[Union[float, str]]]

    @model_validator(mode="after")
    def operator_value(self):
        if self.operator == "in" and (not isinstance(self.value, list) or not self.value):
            raise ValueError("The in operator requires a nonempty list")
        if self.operator != "in" and isinstance(self.value, list):
            raise ValueError("Only the in operator accepts a list")
        return self


class FinancialSort(BaseModel):
    field: str = Field(..., min_length=1)
    direction: Literal["asc", "desc"] = "desc"


class GetCompanyFactsConfig(_CompanyInput):
    """Get company facts."""
    operation: Literal['get_company_facts'] = Field('get_company_facts', title='Get company facts')
    ticker: Optional[str] = Field(None, description='The ticker symbol.')
    cik: Optional[str] = Field(None, description='The CIK of the company.')


class GetIncomeStatementsConfig(_CompanyInput):
    """Get income statements."""
    operation: Literal['get_income_statements'] = Field('get_income_statements', title='Get income statements')
    ticker: Optional[str] = Field(None, description='The ticker symbol. Required if cik or isin is not provided.')
    period: Literal['annual', 'quarterly', 'ttm'] = Field(..., description='The time period of the income statements.')
    limit: Optional[int] = Field(None, ge=1, description='The maximum number of income statements to return. This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cik: Optional[str] = Field(None, description='The Central Index Key (CIK) of the company.')
    market: Optional[Literal['US', 'UK', 'FR']] = Field(None, description="The market the company is listed in: `US` (the default), `UK` or `FR`. Any ticker of the company, including a second share class, returns the company's statements.")
    exchange: Optional[str] = Field(None, description='Deprecated alias of `market`: `LSE` means `market=UK`. Existing requests keep working. France has no alias: name it with `market=FR`.')
    isin: Optional[str] = Field(None, description='The ISIN (International Securities Identification Number) of a non-US listing. An alternative to `ticker` and `market`.')
    report_period: Optional[str] = Field(None, description='Filter by exact report period date in YYYY-MM-DD format.')
    report_period_gte: Optional[str] = Field(None, description='Filter by report period greater than or equal to date in YYYY-MM-DD format.')
    report_period_lte: Optional[str] = Field(None, description='Filter by report period less than or equal to date in YYYY-MM-DD format.')
    report_period_gt: Optional[str] = Field(None, description='Filter by report period greater than date in YYYY-MM-DD format.')
    report_period_lt: Optional[str] = Field(None, description='Filter by report period less than date in YYYY-MM-DD format.')
    filing_date: Optional[str] = Field(None, description='Filter by exact SEC filing date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by SEC filing date greater than or equal to date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lte: Optional[str] = Field(None, description='Filter by SEC filing date less than or equal to date in YYYY-MM-DD format. Useful for point-in-time queries: returns only data that was publicly filed by the given date. Rows without a known filing date are excluded.')
    filing_date_gt: Optional[str] = Field(None, description='Filter by SEC filing date greater than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lt: Optional[str] = Field(None, description='Filter by SEC filing date less than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class GetBalanceSheetsConfig(_CompanyInput):
    """Get balance sheets."""
    operation: Literal['get_balance_sheets'] = Field('get_balance_sheets', title='Get balance sheets')
    ticker: Optional[str] = Field(None, description='The ticker symbol. Required if cik or isin is not provided.')
    period: Literal['annual', 'quarterly', 'ttm'] = Field(..., description='The time period of the balance sheets.')
    limit: Optional[int] = Field(None, ge=1, description='The maximum number of balance sheets to return This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cik: Optional[str] = Field(None, description='The Central Index Key (CIK) of the company.')
    market: Optional[Literal['US', 'UK', 'FR']] = Field(None, description="The market the company is listed in: `US` (the default), `UK` or `FR`. Any ticker of the company, including a second share class, returns the company's statements.")
    exchange: Optional[str] = Field(None, description='Deprecated alias of `market`: `LSE` means `market=UK`. Existing requests keep working. France has no alias: name it with `market=FR`.')
    isin: Optional[str] = Field(None, description='The ISIN (International Securities Identification Number) of a non-US listing. An alternative to `ticker` and `market`.')
    report_period: Optional[str] = Field(None, description='Filter by exact report period date in YYYY-MM-DD format.')
    report_period_gte: Optional[str] = Field(None, description='Filter by report period greater than or equal to date in YYYY-MM-DD format.')
    report_period_lte: Optional[str] = Field(None, description='Filter by report period less than or equal to date in YYYY-MM-DD format.')
    report_period_gt: Optional[str] = Field(None, description='Filter by report period greater than date in YYYY-MM-DD format.')
    report_period_lt: Optional[str] = Field(None, description='Filter by report period less than date in YYYY-MM-DD format.')
    filing_date: Optional[str] = Field(None, description='Filter by exact SEC filing date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by SEC filing date greater than or equal to date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lte: Optional[str] = Field(None, description='Filter by SEC filing date less than or equal to date in YYYY-MM-DD format. Useful for point-in-time queries: returns only data that was publicly filed by the given date. Rows without a known filing date are excluded.')
    filing_date_gt: Optional[str] = Field(None, description='Filter by SEC filing date greater than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lt: Optional[str] = Field(None, description='Filter by SEC filing date less than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class GetCashFlowStatementsConfig(_CompanyInput):
    """Get cash flow statements."""
    operation: Literal['get_cash_flow_statements'] = Field('get_cash_flow_statements', title='Get cash flow statements')
    ticker: Optional[str] = Field(None, description='The ticker symbol. Required if cik or isin is not provided.')
    period: Literal['annual', 'quarterly', 'ttm'] = Field(..., description='The time period of the cash flow statements.')
    limit: Optional[int] = Field(None, ge=1, description='The maximum number of cash flow statements to return. This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cik: Optional[str] = Field(None, description='The Central Index Key (CIK) of the company.')
    market: Optional[Literal['US', 'UK', 'FR']] = Field(None, description="The market the company is listed in: `US` (the default), `UK` or `FR`. Any ticker of the company, including a second share class, returns the company's statements.")
    exchange: Optional[str] = Field(None, description='Deprecated alias of `market`: `LSE` means `market=UK`. Existing requests keep working. France has no alias: name it with `market=FR`.')
    isin: Optional[str] = Field(None, description='The ISIN (International Securities Identification Number) of a non-US listing. An alternative to `ticker` and `market`.')
    report_period: Optional[str] = Field(None, description='Filter by exact report period date in YYYY-MM-DD format.')
    report_period_gte: Optional[str] = Field(None, description='Filter by report period greater than or equal to date in YYYY-MM-DD format.')
    report_period_lte: Optional[str] = Field(None, description='Filter by report period less than or equal to date in YYYY-MM-DD format.')
    report_period_gt: Optional[str] = Field(None, description='Filter by report period greater than date in YYYY-MM-DD format.')
    report_period_lt: Optional[str] = Field(None, description='Filter by report period less than date in YYYY-MM-DD format.')
    filing_date: Optional[str] = Field(None, description='Filter by exact SEC filing date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by SEC filing date greater than or equal to date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lte: Optional[str] = Field(None, description='Filter by SEC filing date less than or equal to date in YYYY-MM-DD format. Useful for point-in-time queries: returns only data that was publicly filed by the given date. Rows without a known filing date are excluded.')
    filing_date_gt: Optional[str] = Field(None, description='Filter by SEC filing date greater than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lt: Optional[str] = Field(None, description='Filter by SEC filing date less than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class GetAllFinancialsConfig(_CompanyInput):
    """Get all financial statements."""
    operation: Literal['get_all_financials'] = Field('get_all_financials', title='Get all financial statements')
    ticker: Optional[str] = Field(None, description='The ticker symbol. Required if cik or isin is not provided.')
    period: Literal['annual', 'quarterly', 'ttm'] = Field(..., description='The time period of the financial statements.')
    limit: Optional[int] = Field(None, ge=1, description='The maximum number of financial statements to return. This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cik: Optional[str] = Field(None, description='The Central Index Key (CIK) of the company.')
    market: Optional[Literal['US', 'UK', 'FR']] = Field(None, description="The market the company is listed in: `US` (the default), `UK` or `FR`. Any ticker of the company, including a second share class, returns the company's statements.")
    exchange: Optional[str] = Field(None, description='Deprecated alias of `market`: `LSE` means `market=UK`. Existing requests keep working. France has no alias: name it with `market=FR`.')
    isin: Optional[str] = Field(None, description='The ISIN (International Securities Identification Number) of a non-US listing. An alternative to `ticker` and `market`.')
    report_period: Optional[str] = Field(None, description='Filter by exact report period date in YYYY-MM-DD format.')
    report_period_gte: Optional[str] = Field(None, description='Filter by report period greater than or equal to date in YYYY-MM-DD format.')
    report_period_lte: Optional[str] = Field(None, description='Filter by report period less than or equal to date in YYYY-MM-DD format.')
    report_period_gt: Optional[str] = Field(None, description='Filter by report period greater than date in YYYY-MM-DD format.')
    report_period_lt: Optional[str] = Field(None, description='Filter by report period less than date in YYYY-MM-DD format.')
    filing_date: Optional[str] = Field(None, description='Filter by exact SEC filing date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by SEC filing date greater than or equal to date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lte: Optional[str] = Field(None, description='Filter by SEC filing date less than or equal to date in YYYY-MM-DD format. Useful for point-in-time queries: returns only data that was publicly filed by the given date. Rows without a known filing date are excluded.')
    filing_date_gt: Optional[str] = Field(None, description='Filter by SEC filing date greater than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lt: Optional[str] = Field(None, description='Filter by SEC filing date less than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class GetFinancialMetricsConfig(_CompanyInput):
    """Get financial metrics."""
    operation: Literal['get_financial_metrics'] = Field('get_financial_metrics', title='Get financial metrics')
    ticker: Optional[str] = Field(None, description='The ticker symbol of the company. Required if cik is not provided.')
    cik: Optional[str] = Field(None, description='The Central Index Key (CIK) of the company. Can be used instead of ticker.')
    market: Optional[Literal['US', 'UK', 'FR']] = Field(None, description="The market the company is listed in: `US` (the default), `UK` or `FR`. Any ticker of the company, including a second share class, returns the company's metrics. Price-based values (market cap, enterprise value, valuation ratios, dividend yield) are not yet available for UK tickers.")
    exchange: Optional[str] = Field(None, description='Deprecated alias of `market`: `LSE` means `market=UK`. Existing requests keep working. France has no alias: name it with `market=FR`.')
    isin: Optional[str] = Field(None, description='The ISIN (International Securities Identification Number) of a non-US listing. An alternative to `ticker` and `market`.')
    period: Literal['annual', 'quarterly', 'ttm'] = Field(..., description='The time period for the financial data.')
    limit: Optional[int] = Field(None, ge=1, description='The maximum number of results to return. This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    report_period: Optional[str] = Field(None, description='Filter by exact report period date in YYYY-MM-DD format.')
    report_period_gte: Optional[str] = Field(None, description='Filter by report period greater than or equal to date in YYYY-MM-DD format.')
    report_period_lte: Optional[str] = Field(None, description='Filter by report period less than or equal to date in YYYY-MM-DD format.')
    report_period_gt: Optional[str] = Field(None, description='Filter by report period greater than date in YYYY-MM-DD format.')
    report_period_lt: Optional[str] = Field(None, description='Filter by report period less than date in YYYY-MM-DD format.')
    filing_date: Optional[str] = Field(None, description='Filter by exact SEC filing date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by SEC filing date greater than or equal to date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lte: Optional[str] = Field(None, description='Filter by SEC filing date less than or equal to date in YYYY-MM-DD format. Useful for point-in-time queries: returns only data that was publicly filed by the given date. Rows without a known filing date are excluded.')
    filing_date_gt: Optional[str] = Field(None, description='Filter by SEC filing date greater than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lt: Optional[str] = Field(None, description='Filter by SEC filing date less than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class GetMetricsSnapshotConfig(_CompanyInput):
    """Financial Metrics Snapshot (Real-Time)."""
    operation: Literal['get_metrics_snapshot'] = Field('get_metrics_snapshot', title='Financial Metrics Snapshot (Real-Time)')
    ticker: Optional[str] = Field(None, description='The ticker symbol of the company.')
    cik: Optional[str] = Field(None, description='The Central Index Key (CIK) of the company. Can be used instead of ticker.')
    market: Optional[Literal['US', 'UK', 'FR']] = Field(None, description="The market the company is listed in: `US` (the default), `UK` or `FR`. Any ticker of the company, including a second share class, returns the company's metrics. Price-based values (market cap, enterprise value, valuation ratios, dividend yield) are not yet available for UK tickers.")
    exchange: Optional[str] = Field(None, description='Deprecated alias of `market`: `LSE` means `market=UK`. Existing requests keep working. France has no alias: name it with `market=FR`.')
    isin: Optional[str] = Field(None, description='The ISIN (International Securities Identification Number) of a non-US listing. An alternative to `ticker` and `market`.')


class GetPricesConfig(_Input):
    """Get historical stock price data."""
    operation: Literal['get_prices'] = Field('get_prices', title='Get historical stock price data')
    ticker: str = Field(..., description='The stock ticker symbol (e.g. AAPL, MSFT).')
    interval: Literal['day', 'week', 'month', 'year'] = Field(..., description='The time interval for the price data.')
    start_date: str = Field(..., description='The start date for the price data (format: YYYY-MM-DD).')
    end_date: str = Field(..., description='The end date for the price data (format: YYYY-MM-DD).')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class GetPriceSnapshotConfig(_Input):
    """Price Snapshot (Real-Time)."""
    operation: Literal['get_price_snapshot'] = Field('get_price_snapshot', title='Price Snapshot (Real-Time)')
    ticker: str = Field(..., description='The stock ticker symbol (e.g. AAPL, MSFT).')


class GetEarningsConfig(_Input):
    """Get earnings snapshot."""
    operation: Literal['get_earnings'] = Field('get_earnings', title='Get earnings snapshot')
    ticker: str = Field(..., description='The ticker symbol (e.g. `AAPL`).')
    limit: int = Field(1, ge=1, le=40, description='Number of most-recent **report periods** worth of filings to return, sorted by `(report_period DESC, filing_date ASC)`. The number of entries returned may exceed `limit` when a recent period has both an 8-K and a 10-Q / 10-K. Values above 40 are clamped to 40. Non-positive or non-integer values return 400. This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class ListFilingsConfig(_Input):
    """Get SEC filings."""
    operation: Literal['list_filings'] = Field('list_filings', title='Get SEC filings')
    cik: Optional[str] = Field(None, description='The Central Index Key (CIK) of the company.')
    ticker: Optional[str] = Field(None, description='The ticker symbol.')
    filing_type: Optional[list[Literal["10-K", "10-Q", "8-K", "20-F", "6-K"]]] = Field(None, description='Filter by one or more filing types. Repeat the query parameter to pass multiple values (e.g. filing_type=10-Q&filing_type=10-K).')
    limit: int = Field(10, ge=1, description='The maximum number of filings to return (default: 10). This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class ListNewsConfig(_Input):
    """Get news articles."""
    operation: Literal['list_news'] = Field('list_news', title='Get news articles')
    ticker: Optional[str] = Field(None, description='The ticker symbol of the company. Omit for broad market news.')
    limit: int = Field(5, ge=1, le=10, description='The maximum number of news articles to return (default: 5, max: 10). This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class ListInsiderTradesConfig(_Input):
    """Get insider trades."""
    operation: Literal['list_insider_trades'] = Field('list_insider_trades', title='Get insider trades')
    ticker: str = Field(..., description='The ticker symbol of the company.')
    limit: int = Field(10, ge=1, description='The maximum number of transactions to return (default: 10). This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    name: Optional[str] = Field(None, description="Filter by insider name (e.g., 'Jen Hsun Huang'). Use the /insider-trades/names endpoint to get available names for a ticker.")
    transaction_type: Optional[str] = Field(None, description="Filter by transaction type (e.g., 'Open market sale', 'Gift'). Use the /insider-trades/transaction-types endpoint to get available types.")
    form_type: Optional[Literal['4', '4/A', '5', '5/A']] = Field(None, description='Filter by SEC form type: 4 for trades, 5 for annual statements (or their amendments 4/A, 5/A).')
    filing_date: Optional[str] = Field(None, description='Filter by exact filing date in YYYY-MM-DD format.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by filing date greater than or equal to this date (YYYY-MM-DD).')
    filing_date_lte: Optional[str] = Field(None, description='Filter by filing date less than or equal to this date (YYYY-MM-DD).')
    filing_date_gt: Optional[str] = Field(None, description='Filter by filing date greater than this date (YYYY-MM-DD).')
    filing_date_lt: Optional[str] = Field(None, description='Filter by filing date less than this date (YYYY-MM-DD).')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class ListInsiderOwnershipConfig(_Input):
    """Get insider ownership."""
    operation: Literal['list_insider_ownership'] = Field('list_insider_ownership', title='Get insider ownership')
    ticker: str = Field(..., description='The ticker symbol of the company.')
    name: Optional[str] = Field(None, description='Filter by insider name (case-insensitive contains). Use the /insider-ownership/names endpoint to get available names for a ticker.')
    form_type: Optional[Literal['3', '3/A', '5', '5/A']] = Field(None, description='Filter by SEC form type: 3 for initial ownership statements, 5 for annual statements (or their amendments 3/A, 5/A).')
    filing_date: Optional[str] = Field(None, description='Filter by exact filing date in YYYY-MM-DD format.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by filing date greater than or equal to this date (YYYY-MM-DD).')
    filing_date_lte: Optional[str] = Field(None, description='Filter by filing date less than or equal to this date (YYYY-MM-DD).')
    filing_date_gt: Optional[str] = Field(None, description='Filter by filing date greater than this date (YYYY-MM-DD).')
    filing_date_lt: Optional[str] = Field(None, description='Filter by filing date less than this date (YYYY-MM-DD).')
    limit: int = Field(10, ge=1, description='The total number of rows to return (default: 10; no maximum). This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class ListInstitutionalHoldingsConfig(_Input):
    """Get 13F institutional holdings."""
    operation: Literal['list_institutional_holdings'] = Field('list_institutional_holdings', title='Get 13F institutional holdings')
    filer_cik: Optional[str] = Field(None, description='The 10-digit zero-padded SEC CIK of the institutional filer. Mutually exclusive with `ticker`.')
    ticker: Optional[str] = Field(None, description="The held security's ticker symbol. Mutually exclusive with `filer_cik`. Without a `report_period` filter, returns one position per institutional filer whose most recent 13F currently includes this ticker.")
    limit: int = Field(10, ge=1, description='The total number of rows to return (default: 10; no maximum). This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    report_period: Optional[str] = Field(None, description='Filter by exact report period date in YYYY-MM-DD format.')
    report_period_gte: Optional[str] = Field(None, description='Filter by report period greater than or equal to date in YYYY-MM-DD format.')
    report_period_lte: Optional[str] = Field(None, description='Filter by report period less than or equal to date in YYYY-MM-DD format.')
    report_period_gt: Optional[str] = Field(None, description='Filter by report period greater than date in YYYY-MM-DD format.')
    report_period_lt: Optional[str] = Field(None, description='Filter by report period less than date in YYYY-MM-DD format.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class ListBeneficialOwnershipConfig(_Input):
    """Get beneficial ownership."""
    operation: Literal['list_beneficial_ownership'] = Field('list_beneficial_ownership', title='Get beneficial ownership')
    ticker: Optional[str] = Field(None, description='The ticker symbol of the subject company. Provide ticker or filer_cik, not both.')
    filer_cik: Optional[str] = Field(None, description='The SEC CIK of the filer (the beneficial owner). Provide ticker or filer_cik, not both. Use the /beneficial-ownership/filers endpoint to look up CIKs by owner name.')
    type: Optional[Literal['activist', 'passive']] = Field(None, description='Filter by stake type: activist (Schedule 13D) or passive (Schedule 13G).')
    history: StrictBool = Field(False, description='When true, returns the full amendment history of each stake instead of only its current state.')
    filing_date: Optional[str] = Field(None, description='Filter by exact filing date in YYYY-MM-DD format.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by filing date greater than or equal to this date (YYYY-MM-DD).')
    filing_date_lte: Optional[str] = Field(None, description='Filter by filing date less than or equal to this date (YYYY-MM-DD).')
    filing_date_gt: Optional[str] = Field(None, description='Filter by filing date greater than this date (YYYY-MM-DD).')
    filing_date_lt: Optional[str] = Field(None, description='Filter by filing date less than this date (YYYY-MM-DD).')
    limit: int = Field(10, ge=1, description='The total number of rows to return (default: 10; no maximum). This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class ListActivistOwnershipConfig(_Input):
    """Get activist stakes."""
    operation: Literal['list_activist_ownership'] = Field('list_activist_ownership', title='Get activist stakes')
    ticker: Optional[str] = Field(None, description='The ticker symbol of the subject company. Provide ticker or filer_cik, not both.')
    filer_cik: Optional[str] = Field(None, description='The SEC CIK of the filer (the beneficial owner). Provide ticker or filer_cik, not both. Use the /activist-ownership/filers endpoint to look up CIKs by owner name.')
    history: StrictBool = Field(False, description='When true, returns the full amendment history of each stake instead of only its current state.')
    filing_date: Optional[str] = Field(None, description='Filter by exact filing date in YYYY-MM-DD format.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by filing date greater than or equal to this date (YYYY-MM-DD).')
    filing_date_lte: Optional[str] = Field(None, description='Filter by filing date less than or equal to this date (YYYY-MM-DD).')
    filing_date_gt: Optional[str] = Field(None, description='Filter by filing date greater than this date (YYYY-MM-DD).')
    filing_date_lt: Optional[str] = Field(None, description='Filter by filing date less than this date (YYYY-MM-DD).')
    limit: int = Field(10, ge=1, description='The total number of rows to return (default: 10; no maximum). This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class ListIndexFundsConfig(_Input):
    """Get ETF / index-fund holdings."""
    operation: Literal['list_index_funds'] = Field('list_index_funds', title='Get ETF / index-fund holdings')
    ticker: Optional[str] = Field(None, description="The fund's ticker symbol (e.g., `SPY`). Returns that fund's holdings. Mutually exclusive with `holding`.")
    holding: Optional[str] = Field(None, description="A held security's ticker symbol (e.g., `AAPL`). Returns the funds whose latest filing holds it. Mutually exclusive with `ticker`.")
    as_of: Optional[str] = Field(None, description="Only valid with `ticker`. Returns the fund composition in effect on or before this date (YYYY-MM-DD). Without it, the fund's latest filing is returned.")
    asset_class: Optional[Literal['equity', 'bond']] = Field(None, description='Only valid with `ticker`. Filter constituents by instrument type: `equity` or `bond`. Omit for all holdings.')
    limit: int = Field(50, ge=1, description='The total number of rows to return (default: 50; no maximum). This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    offset: int = Field(0, ge=0, description='The number of rows to skip, for pagination (default: 0).')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")

    @model_validator(mode="after")
    def one_direction(self):
        if bool(self.ticker) == bool(self.holding):
            raise ValueError("Supply exactly one fund ticker or held-security ticker")
        return self


class ListIposConfig(_Input):
    """Get IPO filings."""
    operation: Literal['list_ipos'] = Field('list_ipos', title='Get IPO filings')
    ticker: Optional[str] = Field(None, description="Filter by the proposed ticker symbol from the filing's cover page.")
    cik: Optional[str] = Field(None, description='Filter by the SEC Central Index Key of the filer, with or without leading zeros.')
    classification: Optional[Literal['ipo', 'shell_company', 'spac', 'resale', 'other']] = Field(None, description='Filter by filing classification: ipo (a real operating company registering to list on an exchange), shell_company, spac, resale, or other.')
    filing_date: Optional[str] = Field(None, description='Filter by exact SEC filing date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_gte: Optional[str] = Field(None, description='Filter by SEC filing date greater than or equal to date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lte: Optional[str] = Field(None, description='Filter by SEC filing date less than or equal to date in YYYY-MM-DD format. Useful for point-in-time queries: returns only data that was publicly filed by the given date. Rows without a known filing date are excluded.')
    filing_date_gt: Optional[str] = Field(None, description='Filter by SEC filing date greater than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    filing_date_lt: Optional[str] = Field(None, description='Filter by SEC filing date less than date in YYYY-MM-DD format. Rows without a known filing date are excluded.')
    limit: int = Field(10, ge=1, description='The total number of rows to return (default: 10; no maximum). This is the total across all pages, not a page size: each page holds up to 10 records, linked by `next_page_url`.')
    cursor: Optional[str] = Field(None, description="Opaque pagination cursor from a previous response's next_page_url. When provided, all other query parameters are ignored: the cursor carries the original request's filters. Treat it as opaque; do not construct or modify it.")


class GetInterestRatesSnapshotConfig(_Input):
    """Interest Rates (Snapshot)."""
    operation: Literal['get_interest_rates_snapshot'] = Field('get_interest_rates_snapshot', title='Interest Rates (Snapshot)')
    bank: Optional[str] = Field(None, description='Optional central bank code (e.g., FED, ECB, BOJ) to return one bank only. Use the /macro/interest-rates/banks endpoint to get a list of available banks.')


class GetYieldCurveSnapshotConfig(_Input):
    """Treasury Yields (Snapshot)."""
    operation: Literal['get_yield_curve_snapshot'] = Field('get_yield_curve_snapshot', title='Treasury Yields (Snapshot)')


class GetInflationSnapshotConfig(_Input):
    """Inflation (Snapshot)."""
    operation: Literal['get_inflation_snapshot'] = Field('get_inflation_snapshot', title='Inflation (Snapshot)')
    series: Optional[str] = Field(None, description='Optional series id to return one row instead of all fourteen, e.g. cpi_core_sa or pce_core_sa.')


class GetLaborSnapshotConfig(_Input):
    """Labor Market (Snapshot)."""
    operation: Literal['get_labor_snapshot'] = Field('get_labor_snapshot', title='Labor Market (Snapshot)')
    series: Optional[str] = Field(None, description='Optional series id to return one row instead of all 24, e.g. unemployment_rate_sa.')


class SearchFinancialsConfig(_Input):
    """Search financial statements."""
    operation: Literal['search_financials'] = Field('search_financials', title='Search financial statements')
    filters: list[FinancialFilter] = Field(..., min_length=1)
    limit: int = Field(10, ge=1)
    currency: str = "USD"
    order_by: Optional[FinancialSort] = None
    as_of: Optional[str] = Field(None, description="Point-in-time screen date, YYYY-MM-DD")


class SearchLineItemsConfig(_Input):
    """Search specific financial metrics."""
    operation: Literal['search_line_items'] = Field('search_line_items', title='Search specific financial metrics')
    line_items: list[str] = Field(..., min_length=1)
    tickers: list[str] = Field(..., min_length=1)
    period: Literal["annual", "quarterly", "ttm"] = "ttm"
    limit: int = Field(1, ge=1)


FinancialDatasetsAIConfig = Annotated[Union[
    GetCompanyFactsConfig,
    GetIncomeStatementsConfig,
    GetBalanceSheetsConfig,
    GetCashFlowStatementsConfig,
    GetAllFinancialsConfig,
    GetFinancialMetricsConfig,
    GetMetricsSnapshotConfig,
    GetPricesConfig,
    GetPriceSnapshotConfig,
    GetEarningsConfig,
    ListFilingsConfig,
    ListNewsConfig,
    ListInsiderTradesConfig,
    ListInsiderOwnershipConfig,
    ListInstitutionalHoldingsConfig,
    ListBeneficialOwnershipConfig,
    ListActivistOwnershipConfig,
    ListIndexFundsConfig,
    ListIposConfig,
    GetInterestRatesSnapshotConfig,
    GetYieldCurveSnapshotConfig,
    GetInflationSnapshotConfig,
    GetLaborSnapshotConfig,
    SearchFinancialsConfig,
    SearchLineItemsConfig
], Field(discriminator="operation")]


class FinancialDatasetsAIFullConfig(NodeConfig[FinancialDatasetsAIConfig, FinancialDatasetsAIAPIKey]):
    pass


ROUTES = {
    'get_company_facts': ('GET', '/company/facts'),
    'get_income_statements': ('GET', '/financials/income-statements'),
    'get_balance_sheets': ('GET', '/financials/balance-sheets'),
    'get_cash_flow_statements': ('GET', '/financials/cash-flow-statements'),
    'get_all_financials': ('GET', '/financials'),
    'get_financial_metrics': ('GET', '/financial-metrics'),
    'get_metrics_snapshot': ('GET', '/financial-metrics/snapshot'),
    'get_prices': ('GET', '/prices'),
    'get_price_snapshot': ('GET', '/prices/snapshot'),
    'get_earnings': ('GET', '/earnings'),
    'list_filings': ('GET', '/filings'),
    'list_news': ('GET', '/news'),
    'list_insider_trades': ('GET', '/insider-trades'),
    'list_insider_ownership': ('GET', '/insider-ownership'),
    'list_institutional_holdings': ('GET', '/institutional-holdings'),
    'list_beneficial_ownership': ('GET', '/beneficial-ownership'),
    'list_activist_ownership': ('GET', '/activist-ownership'),
    'list_index_funds': ('GET', '/index-funds'),
    'list_ipos': ('GET', '/ipos'),
    'get_interest_rates_snapshot': ('GET', '/macro/interest-rates/snapshot'),
    'get_yield_curve_snapshot': ('GET', '/macro/yield-curve/snapshot'),
    'get_inflation_snapshot': ('GET', '/macro/inflation/snapshot'),
    'get_labor_snapshot': ('GET', '/macro/labor/snapshot'),
    'search_financials': ('POST', '/financials/search/screener'),
    'search_line_items': ('POST', '/financials/search/line-items'),
}


class FinancialDatasetsAINode(WorkflowNode):
    integration_type = "automation-financial-datasets-ai"
    connection_evidence = ConnectionEvidence(
        operation="list_news", noun="market news", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return FinancialDatasetsAIFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Financial Datasets API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        # A cursor carries the original filters; the server ignores other query
        # values. Keep required parameters for contract validation. Each run
        # makes one request and never follows a response-provided URL.
        secret = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"X-API-KEY": secret, "Accept": "application/json"},
                **({"json": values} if method == "POST" else {"params": values}))
        if not response.is_success:
            try:
                error = response.json()
            except ValueError:
                error = response.text[:2000]
            message = json.dumps(error, ensure_ascii=False).replace(secret, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message}
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a Financial Datasets JSON object")
        if body.get("error") or body.get("errors"):
            return {"status": "error", "error": json.dumps(body).replace(secret, "[redacted]")}
        # Keep documented response envelopes, metadata, attribution and nulls.
        # Return an extracted cursor for convenience; never forward the API key
        # to a provider-supplied next_page_url.
        next_cursor = None
        following = body.get("next_page_url")
        if following:
            parts = urlsplit(following)
            query = parse_qs(parts.query)
            if parts.scheme != "https" or parts.netloc != "api.financialdatasets.ai" or parts.path.rstrip("/") != path or parts.fragment:
                raise ValueError("Pagination URL changed the API origin or operation")
            if len(query.get("cursor", [])) != 1:
                raise ValueError("Pagination URL lacks an opaque cursor")
            next_cursor = query["cursor"][0]
            if next_cursor == getattr(config, "cursor", None):
                raise ValueError("Pagination cursor did not advance")
        return {**body, "status": "success", "next_cursor": next_cursor}
