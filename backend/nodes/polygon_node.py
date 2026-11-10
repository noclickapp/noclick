"""Polygon market-data reads from the pinned provider Swagger 1.0.0 contract.

Each operation makes one request. Pagination is caller-controlled; offsets and
provider envelopes are preserved. This contract has no mutations or account API.
Contract: https://api.apis.guru/v2/specs/polygon.io/1.0.0/swagger.json
"""
from __future__ import annotations

import json
import re
from datetime import date as Date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class PolygonAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Polygon API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://polygon.io/dashboard/keys",
            "x-credential-instructions": "Paste your Polygon API key from the dashboard. NoClick sends it as apiKey to api.polygon.io. These legacy v1 market-data reads require the appropriate plan. Connection checks list available currencies and prove key acceptance, not account identity.",
        },
    )
    credential_type: Literal["polygon_api_key"] = Field("polygon_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Symbol(_Input):
    symbol: str = Field(..., min_length=1, max_length=128, description="Stock ticker, for example AAPL.")

    @field_validator("symbol")
    @classmethod
    def symbol_value(cls, value):
        if value in {".", ".."} or any(c in value for c in "/%?#\\") or any(ord(c) < 33 for c in value):
            raise ValueError("Use a stock ticker, not a path or URL")
        return value


class _Pair(_Input):
    from_currency: str = Field(..., min_length=1, max_length=32, description="From currency symbol, for example USD; sent as from in the path.")
    to_currency: str = Field(..., min_length=1, max_length=32, description="To currency symbol, for example JPY; sent as to in the path.")

    @field_validator("from_currency", "to_currency")
    @classmethod
    def currency_value(cls, value):
        return _Symbol.symbol_value(value)


class _History(_Input):
    date: str = Field(..., description="Trading day in YYYY-MM-DD format.", json_schema_extra={"format": "date"})
    offset: int | None = Field(None, ge=0, description="Timestamp offset for the next page; returned tick timestamps are preserved.")
    limit: int = Field(100, ge=1, le=10000, description="Maximum ticks in this request; manually request subsequent pages with offset.")

    @field_validator("date")
    @classmethod
    def day(cls, value):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("Use YYYY-MM-DD")
        Date.fromisoformat(value)
        return value


class PolygonListCompaniesConfig(_Input):
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"ui:hidden": True})
    sort: str | None = Field(None, max_length=128, description="Sort field; prefix with - for descending, for example -marketcap.")
    perpage: int | None = Field(None, ge=1, description="Companies per page.")
    page: int = Field(1, ge=1, description="Page number; request subsequent pages explicitly.")


class PolygonListCurrenciesConfig(_Input):
    operation: Literal["list_currencies"] = Field("list_currencies", json_schema_extra={"ui:hidden": True})


class PolygonHistoricAggregatesConfig(_Symbol, _History):
    operation: Literal["get_historic_aggregates"] = Field("get_historic_aggregates", json_schema_extra={"ui:hidden": True})
    size: Literal["second", "minute"] = Field("minute", description="Aggregation interval.")


class PolygonHistoricForexConfig(_Pair, _History):
    operation: Literal["get_historic_forex"] = Field("get_historic_forex", json_schema_extra={"ui:hidden": True})


class PolygonHistoricQuotesConfig(_Symbol, _History):
    operation: Literal["get_historic_quotes"] = Field("get_historic_quotes", json_schema_extra={"ui:hidden": True})


class PolygonHistoricTradesConfig(_Symbol, _History):
    operation: Literal["get_historic_trades"] = Field("get_historic_trades", json_schema_extra={"ui:hidden": True})


class PolygonLastForexTradeConfig(_Pair):
    operation: Literal["get_last_forex_trade"] = Field("get_last_forex_trade", json_schema_extra={"ui:hidden": True})


class PolygonLastStockTradeConfig(_Symbol):
    operation: Literal["get_last_stock_trade"] = Field("get_last_stock_trade", json_schema_extra={"ui:hidden": True})


class PolygonLastForexQuoteConfig(_Pair):
    operation: Literal["get_last_forex_quote"] = Field("get_last_forex_quote", json_schema_extra={"ui:hidden": True})


class PolygonLastStockQuoteConfig(_Symbol):
    operation: Literal["get_last_stock_quote"] = Field("get_last_stock_quote", json_schema_extra={"ui:hidden": True})


class PolygonOnNewOrUpdatedCompanyConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_company"] = Field(
        "on_new_or_updated_company", title="On New or Updated Company",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True,
                           "x-category": "Triggers", "x-display-name": "On New or Updated Company"},
    )
    perpage: int = Field(100, ge=1, le=1000, title="Recent company window",
        description="Watch this many most recently updated companies each poll. Increase the window or poll more frequently for busy markets. Existing records are baselined when armed.")


PolygonConfig = Annotated[Union[
    PolygonListCompaniesConfig, PolygonListCurrenciesConfig,
    PolygonHistoricAggregatesConfig, PolygonHistoricForexConfig,
    PolygonHistoricQuotesConfig, PolygonHistoricTradesConfig,
    PolygonLastForexTradeConfig, PolygonLastStockTradeConfig,
    PolygonLastForexQuoteConfig, PolygonLastStockQuoteConfig,
    PolygonOnNewOrUpdatedCompanyConfig,
], Field(discriminator="operation")]


class PolygonFullConfig(NodeConfig[PolygonConfig, PolygonAPIKeyCredential]):
    pass


ROUTES = {
    "list_companies": "/v1/companies",
    "list_currencies": "/v1/currencies",
    "get_historic_aggregates": "/v1/historic/agg/{size}/{symbol}/{date}",
    "get_historic_forex": "/v1/historic/forex/{from_currency}/{to_currency}/{date}",
    "get_historic_quotes": "/v1/historic/quotes/{symbol}/{date}",
    "get_historic_trades": "/v1/historic/trades/{symbol}/{date}",
    "get_last_forex_trade": "/v1/last/currencies/{from_currency}/{to_currency}",
    "get_last_stock_trade": "/v1/last/stocks/{symbol}",
    "get_last_forex_quote": "/v1/last_quote/currencies/{from_currency}/{to_currency}",
    "get_last_stock_quote": "/v1/last_quote/stocks/{symbol}",
}


class PolygonNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-polygon"
    connection_evidence = ConnectionEvidence(
        operation="list_currencies", noun="available currencies", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return PolygonFullConfig

    @classmethod
    def resolve_agent_event(cls, output):
        data = output.get("data") if isinstance(output, dict) else None
        if not isinstance(data, dict) or "companies" not in data:
            return super().resolve_agent_event(output)
        companies = data["companies"]
        if not companies:
            return None
        lines = ["Polygon: new or updated company information"]
        for company in companies:
            lines.append(f"{company.get('name') or company['symbol']} ({company['symbol']}) "
                         f"updated {company['updated']}")
            lines.append("Company details: " + json.dumps(company, ensure_ascii=False))
            lines.append(f"Use symbol={company['symbol']} with Polygon stock trade, quote or aggregate operations.")
        return {"text": "\n".join(lines), "title": "Polygon company updates"}

    async def _poll_companies(self, cfg):
        # The pinned contract documents generic sort-by-field, the updated
        # timestamp and symbol. Poll only the declared bounded recent window;
        # versioned identities emit both newly listed and changed records.
        result = await self._read(PolygonListCompaniesConfig(
            sort="-updated", perpage=cfg.perpage, page=1), self.config.credentials.api_key)
        companies = result["data"]
        if any(not isinstance(item, dict) or not item.get("symbol") or not item.get("updated")
               for item in companies):
            raise ValueError("Polygon company polling requires symbol and updated on every record")
        fresh = await self._filter_unseen(companies, lambda item: json.dumps([item["symbol"], item["updated"]]))
        return {"status": "success", "data": {"companies": fresh, "new_or_updated_company_count": len(fresh)}}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Polygon API key")
        cfg = self.config.config
        if isinstance(cfg, PolygonOnNewOrUpdatedCompanyConfig):
            return await self._poll_companies(cfg)
        return await self._read(cfg, self.config.credentials.api_key)

    async def _read(self, cfg, key):
        values = cfg.model_dump(exclude_none=True)
        route = ROUTES[cfg.operation]
        path = route.format(**{name: quote(str(value), safe="") for name, value in values.items()})
        query_names = ("sort", "perpage", "page") if cfg.operation == "list_companies" else ("offset", "limit") if isinstance(cfg, _History) else ()
        params = {name: values[name] for name in query_names if name in values}
        params["apiKey"] = key
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", "https://api.polygon.io" + path,
                    params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            # Transport exceptions can carry the query string containing the key.
            raise ValueError("Polygon request could not be completed") from None
        if response.status_code != 200:
            try:
                body = response.json()
                message = body.get("message") or body.get("error") if isinstance(body, dict) else None
            except ValueError:
                message = None
            detail = str(message).replace(key, "[redacted]")[:500] if message else "Request rejected"
            raise ValueError(f"Polygon (HTTP {response.status_code}): {detail}")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Polygon returned an invalid JSON response") from None
        if isinstance(body, dict) and (body.get("error") or str(body.get("status", "")).upper() in {"ERROR", "NOT_AUTHORIZED", "UNAUTHORIZED"} or ("code" in body and "message" in body)):
            detail = str(body.get("message") or body.get("error") or body.get("status")).replace(key, "[redacted]")[:500]
            raise ValueError("Polygon: " + detail)
        if cfg.operation in {"list_companies", "list_currencies"}:
            if not isinstance(body, list):
                raise ValueError("Polygon returned an unexpected list response")
        elif not isinstance(body, dict):
            raise ValueError("Polygon returned an unexpected object response")
        return {"status": "success", "data": body}
