"""Benzinga market data, news and calendar reads.

Contract: benzinga/benzinga-docs at 09544b018b38024e60b78b2f359c8feca171e735.
These published APIs expose reads only. Each operation fetches one page;
use its explicit page/date filters for subsequent requests. Product access
is determined by the subscriptions on the pasted Benzinga API token.
"""
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class BenzingaAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Benzinga API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.benzinga.com/"})
    credential_type: Literal["benzinga_api_token"] = Field("benzinga_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, repr=False,
        description="Paste your Benzinga API token. Your subscription must include the requested data product.",
        json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class BenzingaListNewsConfig(_Input):
    """Get the news items. Returns one response page."""
    operation: Literal["list_news"] = Field("list_news", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, page offsets are limited from 0 - 100000. Limit the query results by other parameters such as date.', ge=0)
    pageSize: int | None = Field(None, alias='pageSize', description='Number of results returned. Maximum 100.', ge=0, le=100)
    displayOutput: Literal['full', 'abstract', 'headline'] | None = Field(None, alias='displayOutput', description='Specify headline only (headline), headline + teaser (abstract), or headline + full body (full) text')
    date: str | None = Field(None, alias='date', description='The date to query for news. Shorthand for dateFrom and dateTo if they are the same. Format: yyyy-mm-dd')
    dateFrom: str | None = Field(None, alias='dateFrom', description='Date to query from point in time. Sorted by published date. Format: yyyy-mm-dd')
    dateTo: str | None = Field(None, alias='dateTo', description='Date to query to point in time. Sorted by published date. Format: yyyy-mm-dd')
    updatedSince: int | None = Field(None, alias='updatedSince', description='The last updated Unix timestamp (UTC) to pull and sort by', ge=0)
    publishedSince: int | None = Field(None, alias='publishedSince', description='The last published Unix timestamp (UTC) to pull and sort by', ge=0)
    sort: Literal['id:asc', 'id:desc', 'created:asc', 'created:desc', 'updated:asc', 'updated:desc'] | None = Field(None, alias='sort', description='Allows control of results sorting. Default is created, DESC. Format: field:direction. Sort Fields: id, created, updated. Sort Order: asc (ascending), desc (descending)')
    isin: str | None = Field(None, alias='isin', description='One or more ISINs separated by a comma. Maximum 50. Format: csv')
    cusips: str | None = Field(None, alias='cusips', description='One or more CUSIPs separated by a comma. Maximum 50. License agreement required. Format: csv')
    tickers: str | None = Field(None, alias='tickers', description='One or more ticker symbols separated by a comma. Maximum 50. Format: csv')
    primaryTickers: str | None = Field(None, alias='primaryTickers', description='One or more primary ticker symbols separated by a comma. Filters by primary ticker association only. Format: csv')
    channels: str | None = Field(None, alias='channels', description='One or more channel names or IDs separated by a comma. Format: csv')
    topics: str | None = Field(None, alias='topics', description='One or more words/phrases separated by a comma; searches Title, Tags, and Body in order of priority. Format: csv')
    topic_group_by: Literal['and', 'or'] | None = Field(None, alias='topic_group_by', description="Logical operator for topics query. Use 'and' to require all topics, 'or' to require any topic")
    authors: str | None = Field(None, alias='authors', description='One or more authors separated by a comma. Format: csv')
    content_types: str | None = Field(None, alias='content_types', description='One or more content types separated by a comma. Format: csv')
    format: Literal['text'] | None = Field(None, alias='format', description='Specify the desired format for the api response')
    importance: str | None = Field(None, alias='importance', description='Filter by importance level')
    importanceRank: int | None = Field(None, alias='importanceRank', description='Filter by importance rank (1-5)', ge=0)
    region: str | None = Field(None, alias='region', description="Filter by region (e.g., 'ca' or 'canada' for Canadian content)")


class BenzingaGetNewsConfig(_Input):
    """Returns a single news item by node ID. Returns one response page."""
    operation: Literal["get_news"] = Field("get_news", json_schema_extra={"ui:hidden": True})
    nodeID: int = Field(..., alias='nodeID', description='Node ID of the news item', ge=0)
    displayOutput: Literal['full', 'abstract', 'headline'] | None = Field(None, alias='displayOutput', description='Specify headline only (headline), headline + teaser (abstract), or headline + full body (full) text')
    format: Literal['text'] | None = Field(None, alias='format', description='Specify the desired format for the api response')


class BenzingaListRemovedNewsConfig(_Input):
    """Returns the removed news data. Returns one response page."""
    operation: Literal["list_removed_news"] = Field("list_removed_news", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, pageSize x page may not exceed 10000. Limit the query results by other parameters such as updatedSince.', ge=0)
    pageSize: int | None = Field(None, alias='pageSize', description='Number of results returned. Maximum 1000.', ge=0, le=1000)
    updatedSince: int | None = Field(None, alias='updatedSince', description='Filters the results to only include items that have been updated since the specified Unix timestamp (UTC)', ge=0)


class BenzingaListEarningsConfig(_Input):
    """Returns the earnings data. Returns one response page."""
    operation: Literal["list_earnings"] = Field("list_earnings", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, page offsets are limited from 0 - 100000. Limit the query results by other parameters such as date', ge=0)
    pagesize: int | None = Field(None, alias='pagesize', description='Number of results returned. Limit 1000', ge=0)
    parameters_date: str | None = Field(None, alias='parameters[date]', description='Date to query for calendar data. Shorthand for date_from and date_to if they are the same. Defaults for latest')
    parameters_date_from: str | None = Field(None, alias='parameters[date_from]', description='Date to query from point in time')
    parameters_date_to: str | None = Field(None, alias='parameters[date_to]', description='Date to query to point in time')
    parameters_date_sort: Literal['date'] | None = Field(None, alias='parameters[date_sort]', description='Field sort option for earnings calendar. Apply `:desc`, `:asc` for sort order')
    parameters_importance: Literal[0, 1, 2, 3, 4, 5] | None = Field(None, alias='parameters[importance]', description='The importance level to filter by. Uses Greater Than or Equal To the importance indicated', ge=0)
    parameters_tickers: str | None = Field(None, alias='parameters[tickers]', description='One or more ticker symbols separated by a comma. Maximum 50 tickers')
    parameters_updated: int | None = Field(None, alias='parameters[updated]', description='Records last Updated Unix timestamp (UTC). This will force the sort order to be Greater Than or Equal to the timestamp indicated', ge=0)


class BenzingaListDividendsConfig(_Input):
    """Dividends Events. Returns one response page."""
    operation: Literal["list_dividends"] = Field("list_dividends", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, page offsets are limited from 0 - 100000. Limit the query results by other parameters such as date', ge=0)
    pagesize: int | None = Field(None, alias='pagesize', description='Number of results returned. Limit 1000', ge=0)
    parameters_date: str | None = Field(None, alias='parameters[date]', description='Date to query for calendar data. Shorthand for date_from and date_to if they are the same. Defaults for latest')
    parameters_date_from: str | None = Field(None, alias='parameters[date_from]', description='Date to query from point in time')
    parameters_date_to: str | None = Field(None, alias='parameters[date_to]', description='Date to query to point in time')
    parameters_date_sort: Literal['announced', 'ex', 'payable', 'record'] | None = Field(None, alias='parameters[date_sort]', description='Dividend date field to sort on (newest to oldest)')
    parameters_dividend_yield_operation: Literal['gt', 'gte', 'eq', 'lte', 'lt'] | None = Field(None, alias='parameters[dividend_yield_operation]', description='Specifies how to filter using dividend yield. gt = Greater Than, gte = Greater Than Equal, eq = Equal, lt = Less Than, lte = Less Than Equal')
    parameters_dividend_yield: float | None = Field(None, alias='parameters[dividend_yield]', description='The dividend yield amount to filter by. Defaults to using Equal To the amount indicated. 1 = 100%')
    parameters_importance: Literal[0, 1, 2, 3, 4, 5] | None = Field(None, alias='parameters[importance]', description='The importance level to filter by. Uses Greater Than or Equal To the importance indicated', ge=0)
    parameters_tickers: str | None = Field(None, alias='parameters[tickers]', description='One or more ticker symbols separated by a comma. Maximum 50 tickers')
    parameters_updated: int | None = Field(None, alias='parameters[updated]', description='Records last Updated Unix timestamp (UTC). This will force the sort order to be Greater Than or Equal to the timestamp indicated', ge=0)


class BenzingaListRatingsConfig(_Input):
    """Returns analyst ratings data. Returns one response page."""
    operation: Literal["list_ratings"] = Field("list_ratings", json_schema_extra={"ui:hidden": True})
    fields: str | None = Field(None, alias='fields', description='Comma-separated list of fields to return. Available fields: id, date, time, ticker, exchange, name, currency, action_pt, action_company, rating_current, pt_current, rating_prior, pt_prior, pt_pct_change, url, url_calendar, url_news, analyst, analyst_id, analyst_name, firm_id, ratings_accuracy, importance, notes, updated. Use * for all fields including ratings_accuracy')
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, page offsets are limited from 0 - 100000. Limit the query results by other parameters such as date', ge=0)
    pagesize: int | None = Field(None, alias='pagesize', description='Number of results returned. Limit 1000', ge=0)
    parameters_date: str | None = Field(None, alias='parameters[date]', description='Date to query for calendar data. Shorthand for date_from and date_to if they are the same. Defaults for latest')
    parameters_date_from: str | None = Field(None, alias='parameters[date_from]', description='Date to query from point in time')
    parameters_date_to: str | None = Field(None, alias='parameters[date_to]', description='Date to query to point in time')
    parameters_importance: Literal[0, 1, 2, 3, 4, 5] | None = Field(None, alias='parameters[importance]', description='The importance level to filter by. Uses Greater Than or Equal To the importance indicated', ge=0)
    parameters_tickers: str | None = Field(None, alias='parameters[tickers]', description='One or more ticker symbols separated by a comma. Maximum 50 tickers')
    parameters_updated: int | None = Field(None, alias='parameters[updated]', description='Records last Updated Unix timestamp (UTC). This will force the sort order to be Greater Than or Equal to the timestamp indicated', ge=0)
    parameters_analyst_id: str | None = Field(None, alias='parameters[analyst_id]', description='One or more analyst ids (analyst_id) separated by a comma')
    parameters_firm_id: str | None = Field(None, alias='parameters[firm_id]', description='One or more firm ids (firm_id) separated by a comma')
    parameters_action: Literal['Downgrades', 'Maintains', 'Reinstates', 'Reiterates', 'Upgrades', 'Assumes', 'Initiates Coverage On', 'Terminates Coverage On', 'Removes', 'Suspends', 'Firm Dissolved'] | None = Field(None, alias='parameters[action]', description='Filter by a specific action_company (action for rating). Note that all of these terms are precisely defined')
    analyst: str | None = Field(None, alias='analyst', description="A comma separated list of analyst (person) ID's to bring back. Omitting will bring back all available analysts")
    firm: str | None = Field(None, alias='firm', description="A comma separated list of analyst firm ID's to bring back. Omitting will bring back all available firms")
    simplify: bool | None = Field(None, alias='simplify', description='Simplify the ratings to standardized categories')


class BenzingaListSplitsConfig(_Input):
    """Returns the splits calendar data. Returns one response page."""
    operation: Literal["list_splits"] = Field("list_splits", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, page offsets are limited from 0 - 100000. Limit the query results by other parameters such as date', ge=0)
    pagesize: int | None = Field(None, alias='pagesize', description='Number of results returned. Limit 1000', ge=0)
    parameters_date: str | None = Field(None, alias='parameters[date]', description='Date to query for calendar data. Shorthand for date_from and date_to if they are the same. Defaults for latest')
    parameters_date_from: str | None = Field(None, alias='parameters[date_from]', description='Date to query from point in time')
    parameters_date_to: str | None = Field(None, alias='parameters[date_to]', description='Date to query to point in time')
    parameters_date_search_field: Literal['announced', 'ex'] | None = Field(None, alias='parameters[date_search_field]', description='Date to filter and sort calendar by. Default is `announced`')
    parameters_importance: Literal[0, 1, 2, 3, 4, 5] | None = Field(None, alias='parameters[importance]', description='The importance level to filter by. Uses Greater Than or Equal To the importance indicated', ge=0)
    parameters_tickers: str | None = Field(None, alias='parameters[tickers]', description='One or more ticker symbols separated by a comma. Maximum 50 tickers')
    parameters_updated: int | None = Field(None, alias='parameters[updated]', description='Records last Updated Unix timestamp (UTC). This will force the sort order to be Greater Than or Equal to the timestamp indicated', ge=0)


class BenzingaListIposConfig(_Input):
    """IPOs V2.1. Returns one response page."""
    operation: Literal["list_ipos"] = Field("list_ipos", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page number', ge=0)
    pagesize: int | None = Field(None, alias='pagesize', description='Page size', ge=0)
    ipo_date: str | None = Field(None, alias='ipo_date', description='Date of IPO in YYYY-MM-DD format (new preferred parameter)')
    parameters_ipo_date: str | None = Field(None, alias='parameters[ipo_date]', description='Date of IPO in YYYY-MM-DD format (deprecated)')
    parameters_date_from: str | None = Field(None, alias='parameters[date_from]', description='Start date in YYYY-MM-DD format')
    parameters_date_to: str | None = Field(None, alias='parameters[date_to]', description='End date in YYYY-MM-DD format')
    parameters_tickers: str | None = Field(None, alias='parameters[tickers]', description='Tickers')
    parameters_ipo_type: str | None = Field(None, alias='parameters[ipo_type]', description='IPO type')
    parameters_updated: str | None = Field(None, alias='parameters[updated]', description='Updated time in Unix format')


class BenzingaListEconomicsConfig(_Input):
    """Returns the economic calendar data. Returns one response page."""
    operation: Literal["list_economics"] = Field("list_economics", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, page offsets are limited from 0 - 100000. Limit the query results by other parameters such as date', ge=0)
    pagesize: int | None = Field(None, alias='pagesize', description='Number of results returned. Limit 1000', ge=0, le=1000)
    parameters_date: str | None = Field(None, alias='parameters[date]', description='Date to query for calendar data. Shorthand for date_from and date_to if they are the same. Defaults for latest')
    parameters_date_from: str | None = Field(None, alias='parameters[date_from]', description='Date to query from point in time')
    parameters_date_to: str | None = Field(None, alias='parameters[date_to]', description='Date to query to point in time')
    parameters_importance: Literal[1, 2, 3] | None = Field(None, alias='parameters[importance]', description='The importance level to filter by. Uses Greater Than or Equal To the importance indicated', ge=0)
    parameters_updated: int | None = Field(None, alias='parameters[updated]', description='Records last Updated Unix timestamp (UTC). This will force the sort order to be Greater Than or Equal to the timestamp indicated', ge=0)
    country: str | None = Field(None, alias='country', description='3-Digit Country Code (e.g., USA, CAN, GBR)')
    event_name: str | None = Field(None, alias='event_name', description='One or more event name prefixes separated by a comma (e.g., CPI matches CPI, CPI (MoM), CPI (Mom) - Prelim)')
    event_category: str | None = Field(None, alias='event_category', description='One or more categories separated by a comma')


class BenzingaListGuidanceConfig(_Input):
    """Returns guidance data. Returns one response page."""
    operation: Literal["list_guidance"] = Field("list_guidance", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, page offsets are limited from 0 - 100000. Limit the query results by other parameters such as date', ge=0)
    pagesize: int | None = Field(None, alias='pagesize', description='Number of results returned. Limit 1000', ge=0)
    parameters_date: str | None = Field(None, alias='parameters[date]', description='Date to query for calendar data. Shorthand for date_from and date_to if they are the same. Defaults for latest')
    parameters_date_from: str | None = Field(None, alias='parameters[date_from]', description='Date to query from point in time')
    parameters_date_to: str | None = Field(None, alias='parameters[date_to]', description='Date to query to point in time')
    parameters_importance: Literal[0, 1, 2, 3, 4, 5] | None = Field(None, alias='parameters[importance]', description='The importance level to filter by. Uses Greater Than or Equal To the importance indicated', ge=0)
    parameters_is_primary: Literal['Y', 'N', 'All'] | None = Field(None, alias='parameters[is_primary]', description='Determines if guidance returned is primary, secondary or all. Default set to Y')
    parameters_tickers: str | None = Field(None, alias='parameters[tickers]', description='One or more ticker symbols separated by a comma. Maximum 50 tickers')
    parameters_updated: int | None = Field(None, alias='parameters[updated]', description='Records last Updated Unix timestamp (UTC). This will force the sort order to be Greater Than or Equal to the timestamp indicated', ge=0)


class BenzingaListOfferingsConfig(_Input):
    """Returns Secondary Offering data. Returns one response page."""
    operation: Literal["list_offerings"] = Field("list_offerings", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, page offsets are limited from 0 - 100000. Limit the query results by other parameters such as date', ge=0)
    pagesize: int | None = Field(None, alias='pagesize', description='Number of results returned. Limit 1000', ge=0)
    parameters_date: str | None = Field(None, alias='parameters[date]', description='Date to query for calendar data. Shorthand for date_from and date_to if they are the same. Defaults for latest')
    parameters_date_from: str | None = Field(None, alias='parameters[date_from]', description='Date to query from point in time')
    parameters_date_to: str | None = Field(None, alias='parameters[date_to]', description='Date to query to point in time')
    parameters_importance: Literal[0, 1, 2, 3, 4, 5] | None = Field(None, alias='parameters[importance]', description='The importance level to filter by. Uses Greater Than or Equal To the importance indicated', ge=0)
    parameters_tickers: str | None = Field(None, alias='parameters[tickers]', description='One or more ticker symbols separated by a comma. Maximum 50 tickers')
    parameters_updated: int | None = Field(None, alias='parameters[updated]', description='Records last Updated Unix timestamp (UTC). This will force the sort order to be Greater Than or Equal to the timestamp indicated', ge=0)


class BenzingaListConferenceCallsConfig(_Input):
    """Returns Conference call data. Returns one response page."""
    operation: Literal["list_conference_calls"] = Field("list_conference_calls", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, alias='page', description='Page offset. For optimization, performance and technical reasons, page offsets are limited from 0 - 100000. Limit the query results by other parameters such as date', ge=0)
    pagesize: int | None = Field(None, alias='pagesize', description='Number of results returned. Limit 1000', ge=0)
    parameters_date: str | None = Field(None, alias='parameters[date]', description='Date to query for calendar data. Shorthand for date_from and date_to if they are the same. Defaults for latest')
    parameters_date_from: str | None = Field(None, alias='parameters[date_from]', description='Date to query from point in time')
    parameters_date_to: str | None = Field(None, alias='parameters[date_to]', description='Date to query to point in time')
    parameters_tickers: str | None = Field(None, alias='parameters[tickers]', description='One or more ticker symbols separated by a comma. Maximum 50 tickers')
    parameters_updated: int | None = Field(None, alias='parameters[updated]', description='Records last Updated Unix timestamp (UTC). This will force the sort order to be Greater Than or Equal to the timestamp indicated', ge=0)


class BenzingaListMarketMoversConfig(_Input):
    """Market Movers. Returns one response page."""
    operation: Literal["list_market_movers"] = Field("list_market_movers", json_schema_extra={"ui:hidden": True})
    maxResults: int | None = Field(None, alias='maxResults', description='Maximum number of results to return. Controls the size of the response.', ge=0)
    from_date: str | None = Field(None, alias='from', description='Start of the movers window. Accepts an absolute YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS value, or an offset from now written as -{n}{unit}, where unit is m (minutes), d (days) or w (weeks), e.g. -5m, -5d, -9w')
    to: str | None = Field(None, alias='to', description='End of the movers window. Accepts an absolute YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS value, or an offset from now written as -{n}{unit}, where unit is m (minutes), d (days) or w (weeks), e.g. -5m, -5d, -9w')
    session: str | None = Field(None, alias='session', description='Trading session to filter movers. Examples: PRE_MARKET, REGULAR, AFTER_MARKET')
    screenerQuery: str | None = Field(None, alias='screenerQuery', description='Custom screener query string for filtering securities based on specific criteria')
    moversQuery: str | None = Field(None, alias='moversQuery', description='Custom movers query string for defining specific movement patterns or thresholds')


class BenzingaGetDelayedQuotesConfig(_Input):
    """Get delayed quotes V2. Returns one response page."""
    operation: Literal["get_delayed_quotes"] = Field("get_delayed_quotes", json_schema_extra={"ui:hidden": True})
    symbols: str | None = Field(None, alias='symbols', description='Comma-separated list of stock ticker symbols. At least one of symbols, isin, or cik is required.')
    isin: str | None = Field(None, alias='isin', description='Comma-separated list of ISIN identifiers. Maximum 50. At least one of symbols, isin, or cik is required.')
    cik: str | None = Field(None, alias='cik', description='Comma-separated list of CIK identifiers. At least one of symbols, isin, or cik is required.')


class BenzingaGetShortInterestConfig(_Input):
    """Short Interest Data. Returns one response page."""
    operation: Literal["get_short_interest"] = Field("get_short_interest", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., alias='symbols', description='Comma-separated list of stock ticker symbols (e.g., AAPL,MSFT,TSLA). Required.')
    finraReport: bool | None = Field(None, alias='finraReport', description='Include FINRA short interest report data. Default: false')
    page: int | None = Field(None, alias='page', description='Page number for pagination. Used with pageSize parameter.', ge=0)
    pageSize: int | None = Field(None, alias='pageSize', description='Number of results per page. Default varies by endpoint configuration.', ge=0)
    from_date: str | None = Field(None, alias='from', description='Start date for short interest data. Format: YYYY-MM-DD')
    to: str | None = Field(None, alias='to', description='End date for short interest data. Format: YYYY-MM-DD')


class BenzingaGetCompanyProfileConfig(_Input):
    """Company Profile Information V2.1. Returns one response page."""
    operation: Literal["get_company_profile"] = Field("get_company_profile", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., alias='symbols', description='Comma-separated list of stock ticker symbols (e.g., AAPL,MSFT,GOOGL). Required.')
    asOf: str | None = Field(None, alias='asOf', description='Filter results for dates on or after this date. Format: YYYY-MM-DD (e.g., 2024-01-01)')
    period: str | None = Field(None, alias='period', description='Time period filter for financial reporting periods. Supported values: Q1, Q2, Q3, Q4 (quarters), FY (fiscal year), TTM (trailing twelve months)')
    reportType: str | None = Field(None, alias='reportType', description='Type of financial report. Supported values: TTM (trailing twelve months), A (as originally reported), R (restated values), P (preliminary announcements)')


class BenzingaGetBarsConfig(_Input):
    """Historical Price Bars. Returns one response page."""
    operation: Literal["get_bars"] = Field("get_bars", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., alias='symbols', description='Comma-separated list of stock ticker symbols (e.g., AAPL,MSFT,TSLA). Required.')
    from_date: str = Field(..., alias='from', description='Start date/time for bars. Formats: YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, YTD (year-to-date), or relative values like 1MONTH/1m/1M, 1WEEK/1w/1W, 1DAY/1d/1D. Required.')
    to: str | None = Field(None, alias='to', description='End date/time for bars. Format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS. Defaults to current date/time if not specified.')
    interval: str | None = Field(None, alias='interval', description='Time bucket interval for aggregating price bars. Supported values: 1m (1 minute), 5m (5 minutes), 15m (15 minutes), 30m (30 minutes), 1h (1 hour), 1d (1 day), 1w (1 week), 1M (1 month). Default: 1d')
    session: str | None = Field(None, alias='session', description='Trading session filter. Supported values: ANY (all sessions), PRE_MARKET (pre-market trading), REGULAR (regular trading hours), AFTER_MARKET (after-hours trading). Default: ANY')


class BenzingaGetBalanceSheetConfig(_Input):
    """Get Balance Sheet V3. Returns one response page."""
    operation: Literal["get_balance_sheet"] = Field("get_balance_sheet", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., alias='symbols', description='Comma-separated list of stock ticker symbols (e.g., AAPL, MSFT)')
    from_date: str | None = Field(None, alias='from', description='Start date for query in YYYY-MM-DD format. Supports: YYYY-MM-DD, YTD (year-to-date), 1MONTH/1m/1M (1 month ago)')
    to: str | None = Field(None, alias='to', description='End date for query in YYYY-MM-DD format. Returns data up to and including this date.')
    date: str | None = Field(None, alias='date', description='Report type filter. Values: TTM (trailing twelve months), A (as reported), R (restated), P (preliminary)')


class BenzingaGetCashFlowConfig(_Input):
    """Get Cash Flow V3. Returns one response page."""
    operation: Literal["get_cash_flow"] = Field("get_cash_flow", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., alias='symbols', description='Comma separated list of symbols (e.g., AAPL, MSFT)')
    from_date: str | None = Field(None, alias='from', description='Start date for query in YYYY-MM-DD format. Supports: YYYY-MM-DD, YTD (year-to-date), 1MONTH/1m/1M (1 month ago)')
    to: str | None = Field(None, alias='to', description='End date for query in YYYY-MM-DD format. Returns data up to and including this date.')
    date: str | None = Field(None, alias='date', description='Report type filter. Values: TTM (trailing twelve months), A (as reported), R (restated), P (preliminary)')


class BenzingaGetIncomeStatementConfig(_Input):
    """Income Statement Data V3. Returns one response page."""
    operation: Literal["get_income_statement"] = Field("get_income_statement", json_schema_extra={"ui:hidden": True})
    symbols: str = Field(..., alias='symbols', description='Comma-separated list of stock ticker symbols (e.g., AAPL,MSFT,GOOGL). Required.')
    from_date: str | None = Field(None, alias='from', description='Start date for query. Supports multiple formats: YYYY-MM-DD (e.g., 2024-01-01), YTD (year-to-date from Jan 1), or relative dates like 1MONTH/1m/1M (1 month ago)')
    to: str | None = Field(None, alias='to', description='End date for query. Format: YYYY-MM-DD (e.g., 2024-12-31). Returns data up to and including this date.')
    date: str | None = Field(None, alias='date', description='Report type filter for financial statements. Supported values: TTM (trailing twelve months), A (as originally reported), R (restated values), P (preliminary announcements)')


BenzingaConfig = Annotated[Union[BenzingaListNewsConfig, BenzingaGetNewsConfig, BenzingaListRemovedNewsConfig, BenzingaListEarningsConfig, BenzingaListDividendsConfig, BenzingaListRatingsConfig, BenzingaListSplitsConfig, BenzingaListIposConfig, BenzingaListEconomicsConfig, BenzingaListGuidanceConfig, BenzingaListOfferingsConfig, BenzingaListConferenceCallsConfig, BenzingaListMarketMoversConfig, BenzingaGetDelayedQuotesConfig, BenzingaGetShortInterestConfig, BenzingaGetCompanyProfileConfig, BenzingaGetBarsConfig, BenzingaGetBalanceSheetConfig, BenzingaGetCashFlowConfig, BenzingaGetIncomeStatementConfig], Field(discriminator="operation")]


class BenzingaFullConfig(NodeConfig[BenzingaConfig, BenzingaAPITokenCredential]):
    pass


ROUTES = {'list_news': '/api/v2/news', 'get_news': '/api/v2/news/{nodeID}', 'list_removed_news': '/api/v2/news-removed', 'list_earnings': '/api/v2.1/calendar/earnings', 'list_dividends': '/api/v2.1/calendar/dividends', 'list_ratings': '/api/v2.1/calendar/ratings', 'list_splits': '/api/v2.1/calendar/splits', 'list_ipos': '/api/v2.1/calendar/ipos', 'list_economics': '/api/v2.1/calendar/economics', 'list_guidance': '/api/v2.1/calendar/guidance', 'list_offerings': '/api/v2.1/calendar/offerings', 'list_conference_calls': '/api/v2.1/calendar/conference-calls', 'list_market_movers': '/api/v1/market/movers', 'get_delayed_quotes': '/api/v2/quoteDelayed', 'get_short_interest': '/api/v1/shortinterest', 'get_company_profile': '/api/v2.1/fundamentals/companyProfile', 'get_bars': '/api/v2/bars', 'get_balance_sheet': '/api/v3/fundamentals/balance-sheet', 'get_cash_flow': '/api/v3/fundamentals/cash-flow', 'get_income_statement': '/api/v3/fundamentals/income-statement'}


class BenzingaNode(WorkflowNode):
    integration_type = "automation-benzinga"
    connection_evidence = ConnectionEvidence(operation="list_news", noun="Benzinga news", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BenzingaFullConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a Benzinga API token")
        config = self.config.config
        token = self.config.credentials.api_token
        params = config.model_dump(by_alias=True, exclude_none=True, exclude={"operation"})
        path = ROUTES[config.operation]
        if "{nodeID}" in path:
            path = path.replace("{nodeID}", str(params.pop("nodeID")))
        params["token"] = token
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.get("https://api.benzinga.com" + path,
                    params=params, headers={"Accept": "application/json"})
            if response.status_code != 200:
                return {"status": "error", "http_status": response.status_code,
                    "error": "Benzinga rejected the request" if response.status_code in (401, 403) else "Benzinga did not complete the request"}
            body = response.json()
            if not isinstance(body, (dict, list)) and not (config.operation == "get_delayed_quotes" and isinstance(body, str)):
                raise ValueError("Expected Benzinga JSON data")
            if isinstance(body, dict) and (body.get("error") or body.get("errors")):
                return {"status": "error", "error": "Benzinga returned an error response"}
            return {"status": "success", "operation": config.operation, "data": body}
        except (httpx.HTTPError, ValueError):
            # HTTP errors can include the secret-bearing query URL.
            raise ValueError("Benzinga request could not be completed or decoded") from None
