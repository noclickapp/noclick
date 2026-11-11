"""Signal8 Public API v1: market and SEC intelligence with a pasted API key.

Routes and parameters follow https://signal8.ai/developer/docs/openapi.json.
Responses retain provider caveats and nulls; batch quotes are a read-only POST.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.signal8.ai/api/v1/public"

class Signal8APIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Signal8 API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://signal8.ai/developer",
            "x-credential-instructions": "Paste an API key from the Signal8 developer portal. Requests consume Signal8 API credits. The connection read proves key acceptance, not account identity."})
    credential_type: Literal["signal8_api_key"] = Field("signal8_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _TickerInput(_Input):
    ticker: str = Field(..., min_length=1, max_length=5, pattern=r"^[A-Za-z]{1,5}$", description="Company ticker, for example AAPL.")

class Signal8SearchCompaniesConfig(_Input):
    """Search companies."""
    operation: Literal["search_companies"] = Field("search_companies", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, max_length=200, description='Search query (company name or ticker), 1-200 characters after trimming.')
    limit: int | None = Field(None, ge=1, le=100, description='Maximum number of results (1-100, default 20)')

class Signal8GetCompanyConfig(_TickerInput):
    """Get company profile."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})

class Signal8GetQuoteConfig(_TickerInput):
    """Get stock quote."""
    operation: Literal["get_quote"] = Field("get_quote", json_schema_extra={"ui:hidden": True})

class Signal8GetCandlesConfig(_TickerInput):
    """Get historical OHLCV candles."""
    operation: Literal["get_candles"] = Field("get_candles", json_schema_extra={"ui:hidden": True})
    resolution: Literal['1', '5', '15', '30', '60', '240', 'D', 'W', 'M'] | None = Field(None, description='Candle resolution: intraday minutes (1, 5, 15, 30, 60, 240), D (daily, default), W (weekly), or M (monthly).')
    period: Literal['1M', '3M', '6M', '1Y', '5Y', 'ALL'] | None = Field(None, description='Lookback period shorthand (default 1Y). Ignored when from/to are provided.')
    from_: int | None = Field(None, alias='from', ge=0, description='Start of an explicit range as a UNIX timestamp (takes precedence over period).')
    to: int | None = Field(None, ge=0, description='End of an explicit range as a UNIX timestamp (takes precedence over period).')

class Signal8ListCompanyNewsConfig(_TickerInput):
    """Get company news."""
    operation: Literal["list_company_news"] = Field("list_company_news", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=50, description='Maximum number of articles (1-50, default 20)')
    page: int | None = Field(None, ge=0, description='Page number for pagination (default 0)')

class Signal8GetFinancialsConfig(_TickerInput):
    """Get financial statements."""
    operation: Literal["get_financials"] = Field("get_financials", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=40, description='Maximum number of periods to return (1-40, default 10)')

class Signal8GetEarningsConfig(_TickerInput):
    """Get earnings reports."""
    operation: Literal["get_earnings"] = Field("get_earnings", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100, description='Maximum number of reports to return (1-100, default 20)')

class Signal8GetShortInterestConfig(_TickerInput):
    """Get short interest."""
    operation: Literal["get_short_interest"] = Field("get_short_interest", json_schema_extra={"ui:hidden": True})

class Signal8GetFloatConfig(_TickerInput):
    """Get float breakdown."""
    operation: Literal["get_float"] = Field("get_float", json_schema_extra={"ui:hidden": True})

class Signal8GetCashPositionConfig(_TickerInput):
    """Get cash position model & runway."""
    operation: Literal["get_cash_position"] = Field("get_cash_position", json_schema_extra={"ui:hidden": True})

class Signal8GetDilutionRiskConfig(_TickerInput):
    """Get dilution risk assessment."""
    operation: Literal["get_dilution_risk"] = Field("get_dilution_risk", json_schema_extra={"ui:hidden": True})

class Signal8GetDilutionSnapshotConfig(_TickerInput):
    """Get the dilution snapshot summary."""
    operation: Literal["get_dilution_snapshot"] = Field("get_dilution_snapshot", json_schema_extra={"ui:hidden": True})

class Signal8GetDilutionInstrumentsConfig(_TickerInput):
    """Get dilution instrument rows by family."""
    operation: Literal["get_dilution_instruments"] = Field("get_dilution_instruments", json_schema_extra={"ui:hidden": True})
    family: Literal['warrants', 'convertibles', 'preferred', 'shelfs', 'atms', 'elocs', 's1_offerings', 'equity_plans', 'exchangeables', 'recent_offerings'] = Field(..., description='Which instrument family to return.')

class Signal8GetOwnershipConfig(_TickerInput):
    """Get comprehensive ownership breakdown."""
    operation: Literal["get_ownership"] = Field("get_ownership", json_schema_extra={"ui:hidden": True})

class Signal8ListInsiderTransactionsConfig(_TickerInput):
    """Get insider transaction history."""
    operation: Literal["list_insider_transactions"] = Field("list_insider_transactions", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=500, description='Maximum number of results (1-500, default 100)')
    offset: int | None = Field(None, ge=0, description='Number of results to skip (default 0)')
    year: int | None = Field(None, ge=2000, le=2100, description='Only transactions in this calendar year (2000-2100).')
    month: int | None = Field(None, ge=1, le=12, description='Only transactions in this month (1-12). Combine with `year`.')
    transactionCode: Literal['P', 'S', 'A', 'M', 'F', 'G', 'C', 'W', 'J', 'K', 'L', 'U', 'H', 'D', 'I', 'O', 'Z'] | None = Field(None, description='Only transactions with this SEC Form 4 transaction code\n(case-insensitive). Common codes: `P` purchase, `S` sale, `A` award,\n`M` option exercise, `F` tax withholding, `G` gift. Any other value\nreturns 400 `INVALID_INPUT`.')

class Signal8GetComplianceConfig(_TickerInput):
    """Get full compliance evaluation."""
    operation: Literal["get_compliance"] = Field("get_compliance", json_schema_extra={"ui:hidden": True})

class Signal8ListGainersConfig(_Input):
    """Top gainers (close-to-close or extended-hours)."""
    operation: Literal["list_gainers"] = Field("list_gainers", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=20, description='Max results (1-20, default 10)')
    marketCapMin: float | None = Field(None, description='marketCapMin')
    marketCapMax: float | None = Field(None, description='marketCapMax')
    session: Literal['premarket', 'regular', 'afterhours'] | None = Field(None, description='Session window. `regular` (default) ranks by close-to-close.\n`premarket` uses `pre_market_change_percent`; `afterhours` uses\n`after_hours_change_percent`. Extended-hours sessions only\nreturn rows whose corresponding extended-hours columns are\npopulated by the most recent ingest.')

class Signal8ListLosersConfig(_Input):
    """Top losers (close-to-close or extended-hours)."""
    operation: Literal["list_losers"] = Field("list_losers", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100, description='limit')
    marketCapMin: float | None = Field(None, description='marketCapMin')
    marketCapMax: float | None = Field(None, description='marketCapMax')
    session: Literal['premarket', 'regular', 'afterhours'] | None = Field(None, description='Session window. `regular` (default) ranks by close-to-close.\n`premarket` uses `pre_market_change_percent`; `afterhours` uses\n`after_hours_change_percent`.')

class Signal8ListActiveStocksConfig(_Input):
    """Most active stocks by volume."""
    operation: Literal["list_active_stocks"] = Field("list_active_stocks", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100, description='limit')
    marketCapMin: float | None = Field(None, description='marketCapMin')
    marketCapMax: float | None = Field(None, description='marketCapMax')
    session: Literal['regular'] | None = Field(None, description='Only `regular` is accepted on this route. `premarket` /\n`afterhours` produce `400 INVALID_INPUT`.')

class Signal8GetBatchQuotesConfig(_Input):
    """Batch quote fetch by explicit ticker list."""
    operation: Literal["get_batch_quotes"] = Field("get_batch_quotes", json_schema_extra={"ui:hidden": True})
    tickers: str = Field(..., min_length=1, max_length=2999, pattern=r"^[A-Za-z]{1,5}(?:,[A-Za-z]{1,5}){0,499}$", description="Up to 500 comma-separated ticker symbols, for example AAPL,MSFT.")

class Signal8ListFilingsConfig(_Input):
    """Search and list filings."""
    operation: Literal["list_filings"] = Field("list_filings", json_schema_extra={"ui:hidden": True})
    ciks: str | None = Field(None, description='Comma-separated CIK numbers (e.g. "0000320193,0001018724").')
    pageSize: int | None = Field(None, ge=1, le=100, description='Results per page (default: 25, max: 100).')
    formTypes: str | None = Field(None, description='Comma-separated form types (e.g. "10-K,10-Q,8-K,S-1").')
    dateFrom: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description='Start date filter (YYYY-MM-DD).')
    dateTo: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description='End date filter (YYYY-MM-DD).')
    q: str | None = Field(None, min_length=1, max_length=200, description='Full-text query over filing bodies. Syntax: unquoted words must ALL appear; "quoted phrase" = exact wording; OR between alternatives; -word / -"phrase" to exclude; `w1 NEAR/10 w2` (also `NEAR(10)`, bare `NEAR` = 10) = words close together; `word*` = prefix of 4+ letters; `$AAPL` or a capitalised ticker scopes to that company; a form code (`8-K`), `item 5.02` / `8-K 1.05` and a bare year (`2024`) scope to that form / 8-K item / year. The archive\'s reading of the query is reported in `meta.understanding` (disable with understand=false). Ranked when sort=relevance. Rows then carry `rank` and `snippet`.')
    sort: Literal['newest', 'relevance'] | None = Field(None, description='newest (acceptance time, default) or relevance (requires q; best match first). Any other value is a 400.')
    cursor: str | None = Field(None, description="Opaque keyset cursor from a previous response's pagination.nextCursor. Use instead of page for deep, stable paging.")
    acceptedFrom: str | None = Field(None, description='Acceptance-time lower bound (ISO-8601). Rows without an acceptance time compare on filing date.')
    acceptedTo: str | None = Field(None, description='Acceptance-time upper bound (ISO-8601).')

class Signal8OnNewFilingConfig(PollTriggerConfigBase):
    """Watch the newest 100 SEC filings in this scope each interval.

    High-volume scopes can exceed this rolling window: use a company filter
    and a short schedule. Signal8 archive coverage is not proof of SEC absence.
    """
    operation: Literal["on_new_filing"] = Field("on_new_filing", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New SEC Filing"})
    ciks: str | None = Field(None, description="Comma-separated company CIKs. Narrow busy feeds to avoid exceeding the 100-filing polling window.")
    formTypes: str | None = Field(None, description="Comma-separated SEC forms, for example 10-K,10-Q,8-K.")

Signal8Config = Annotated[Union[Signal8SearchCompaniesConfig, Signal8GetCompanyConfig, Signal8GetQuoteConfig, Signal8GetCandlesConfig, Signal8ListCompanyNewsConfig, Signal8GetFinancialsConfig, Signal8GetEarningsConfig, Signal8GetShortInterestConfig, Signal8GetFloatConfig, Signal8GetCashPositionConfig, Signal8GetDilutionRiskConfig, Signal8GetDilutionSnapshotConfig, Signal8GetDilutionInstrumentsConfig, Signal8GetOwnershipConfig, Signal8ListInsiderTransactionsConfig, Signal8GetComplianceConfig, Signal8ListGainersConfig, Signal8ListLosersConfig, Signal8ListActiveStocksConfig, Signal8GetBatchQuotesConfig, Signal8ListFilingsConfig, Signal8OnNewFilingConfig], Field(discriminator="operation")]

class Signal8NodeConfig(NodeConfig[Signal8Config, Signal8APIKeyCredential]):
    pass

ROUTES = {'search_companies': ('GET', '/companies/search'), 'get_company': ('GET', '/companies/{ticker}'), 'get_quote': ('GET', '/companies/{ticker}/quote'), 'get_candles': ('GET', '/companies/{ticker}/candles'), 'list_company_news': ('GET', '/companies/{ticker}/news'), 'get_financials': ('GET', '/companies/{ticker}/financials'), 'get_earnings': ('GET', '/companies/{ticker}/earnings'), 'get_short_interest': ('GET', '/companies/{ticker}/short-interest'), 'get_float': ('GET', '/companies/{ticker}/float'), 'get_cash_position': ('GET', '/cash-position/{ticker}'), 'get_dilution_risk': ('GET', '/dilution/{ticker}/risk'), 'get_dilution_snapshot': ('GET', '/dilution/{ticker}/snapshot'), 'get_dilution_instruments': ('GET', '/dilution/{ticker}/instruments'), 'get_ownership': ('GET', '/intelligence/{ticker}/ownership'), 'list_insider_transactions': ('GET', '/intelligence/{ticker}/insider-transactions'), 'get_compliance': ('GET', '/compliance/{ticker}/evaluation'), 'list_gainers': ('GET', '/market/movers/gainers'), 'list_losers': ('GET', '/market/movers/losers'), 'list_active_stocks': ('GET', '/market/movers/active'), 'get_batch_quotes': ('POST', '/market/quotes'), 'list_filings': ('GET', '/edgar/filings')}

class Signal8Node(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-signal8"
    connection_evidence = ConnectionEvidence(operation="list_filings", noun="SEC filings",
        label_keys=("company_name", "accession_number", "id"), proves="reachability")
    edit_examples = ["Get the latest AAPL quote", "Watch new SEC filings for these companies", "Assess dilution risk for VNRX"]

    @classmethod
    def get_config_model(cls):
        return Signal8NodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None):
        async with guarded_async_client() as client:
            response = await client.request(method, BASE_URL + path,
                headers={"X-Api-Key": api_key, "Accept": "application/json"},
                params=params, json=body, timeout=30, follow_redirects=False)
        if not 200 <= response.status_code < 300:
            # Do not include request headers or a provider echo of the secret.
            try:
                error = response.json().get("error", {})
                message = error.get("message") if isinstance(error, dict) else str(error)
            except (ValueError, AttributeError):
                message = None
            raise ValueError((message or f"Signal8 HTTP {response.status_code}").replace(api_key, "[redacted]"))
        result = response.json()
        if not isinstance(result, dict) or result.get("error") or result.get("success") is False:
            raise ValueError("Signal8 returned an invalid or error response")
        return result

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Signal8 API key")
        op = self.config.config
        if isinstance(op, Signal8OnNewFilingConfig):
            params = {"sort": "newest", "pageSize": 100}
            for key in ("ciks", "formTypes"):
                if getattr(op, key) is not None:
                    params[key] = getattr(op, key)
            result = await self._request(self.config.credentials.api_key, "GET", "/edgar/filings", params=params)
            rows = result.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("id") for row in rows):
                raise ValueError("Signal8 filing list is missing documented filing IDs")
            fresh = await self._filter_unseen(rows, lambda row: str(row["id"]))
            return {"filings": fresh, "new_filing_count": len(fresh), "poll_window": 100,
                    "window_full": len(rows) >= 100}
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, by_alias=True, exclude={"operation"})
        if "{ticker}" in path:
            path = path.replace("{ticker}", quote(values.pop("ticker"), safe=""))
        return await self._request(self.config.credentials.api_key, method, path,
                                   params=values if method == "GET" else None,
                                   body=values if method == "POST" else None)

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_filing_count")) if config.get("operation") == "on_new_filing" else True

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("filings") if isinstance(output, dict) else None
        if not isinstance(rows, list):
            return super().resolve_agent_event(output)
        if not rows:
            return None
        lines = [f"{r.get('company_name', 'Company')} (CIK {r.get('cik')}): {r.get('form_type')} filed {r.get('filing_date')}; accession {r.get('accession_number')}, Signal8 filing ID {r['id']}" for r in rows[:20]]
        return {"text": f"Signal8: {len(rows)} new SEC filing(s).\n" + "\n".join(lines), "conversation_key": None}
