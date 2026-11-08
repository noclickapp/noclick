"""Fixer exchange rates using the provider's access_key query authentication.

Contract: https://api.swaggerhub.com/apis/apilayer-863/FixerAPI/1.0.0/swagger.json
All endpoints are reads. Features and base-currency switching depend on the plan.
"""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://data.fixer.io/api"


class FixerIoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Fixer Io API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://fixer.io/dashboard",
            "x-credential-instructions": "Copy your API access key from the Fixer dashboard. NoClick sends it to data.fixer.io over HTTPS. The connection check reads supported currencies and proves key acceptance, not account identity. Conversion, time series, fluctuation, spread data and base switching may require a paid plan.",
        })
    credential_type: Literal["fixer_io_api_key"] = Field("fixer_io_api_key", json_schema_extra={"ui:hidden": True})
    access_key: str = Field(..., title="API access key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API access key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API access key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListSymbols(_Input):
    operation: Literal["list_symbols"] = Field("list_symbols", title="List Supported Currencies", json_schema_extra={"ui:hidden": True})


class _Rates(_Input):
    base: str | None = Field(None, description="Three-letter base currency; provider defaults to EUR. Switching base requires a supported plan.")
    symbols: str | None = Field(None, max_length=1000, description="Comma-separated currency codes, for example USD,GBP,JPY. Omit for all currencies.")

    @field_validator("base", "symbols", mode="before")
    @classmethod
    def currencies(cls, value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}(?:,[A-Z]{3})*", value)):
            raise ValueError("Use uppercase three-letter currency codes")
        return value

    @field_validator("base")
    @classmethod
    def single_base(cls, value):
        if value is not None and len(value) != 3:
            raise ValueError("Choose one base currency")
        return value


class LatestRates(_Rates):
    operation: Literal["get_latest_rates"] = Field("get_latest_rates", title="Get Latest Rates", json_schema_extra={"ui:hidden": True})


class LatestSpread(_Rates):
    operation: Literal["get_latest_spread"] = Field("get_latest_spread", title="Get Latest Bid/Ask Rates", description="Request spread=1; bid/ask fields may be unavailable for some currencies or plans.", json_schema_extra={"ui:hidden": True})


class HistoricalRates(_Rates):
    operation: Literal["get_historical_rates"] = Field("get_historical_rates", title="Get Historical Rates", json_schema_extra={"ui:hidden": True})
    date: str = Field(..., description="Historical date in YYYY-MM-DD format.")

    @field_validator("date")
    @classmethod
    def day(cls, value):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use YYYY-MM-DD")
        date.fromisoformat(value)
        return value


class HistoricalSpread(HistoricalRates):
    operation: Literal["get_historical_spread"] = Field("get_historical_spread", title="Get Historical Bid/Ask Rates", description="Request spread=1 for a historical date; availability depends on the plan.", json_schema_extra={"ui:hidden": True})


class ConvertCurrency(_Input):
    operation: Literal["convert_currency"] = Field("convert_currency", title="Convert Currency", json_schema_extra={"ui:hidden": True})
    from_currency: str = Field(..., pattern=r"^[A-Z]{3}$", title="From currency", description="Source currency, for example GBP.")
    to_currency: str = Field(..., pattern=r"^[A-Z]{3}$", title="To currency", description="Target currency, for example JPY.")
    amount: float = Field(..., allow_inf_nan=False, description="Amount to convert.")


class ConvertHistoricalCurrency(ConvertCurrency):
    operation: Literal["convert_historical_currency"] = Field("convert_historical_currency", title="Convert at Historical Rate", json_schema_extra={"ui:hidden": True})
    date: str = Field(..., description="Conversion date in YYYY-MM-DD format.")
    _day = field_validator("date")(HistoricalRates.day.__func__)


class _Period(_Rates):
    start_date: str = Field(..., description="First date in YYYY-MM-DD format.")
    end_date: str = Field(..., description="Last date in YYYY-MM-DD format; maximum span is 365 days.")
    _days = field_validator("start_date", "end_date")(HistoricalRates.day.__func__)

    @model_validator(mode="after")
    def period(self):
        delta = (date.fromisoformat(self.end_date) - date.fromisoformat(self.start_date)).days
        if not 0 <= delta <= 365:
            raise ValueError("Use an ordered period of at most 365 days")
        return self


class TimeSeries(_Period):
    operation: Literal["get_time_series"] = Field("get_time_series", title="Get Daily Time Series", json_schema_extra={"ui:hidden": True})


class TimeSeriesSpread(_Period):
    operation: Literal["get_time_series_spread"] = Field("get_time_series_spread", title="Get Daily Bid/Ask Time Series", description="Request spread=1; bid/ask availability depends on the plan.", json_schema_extra={"ui:hidden": True})


class Fluctuation(_Period):
    operation: Literal["get_fluctuation"] = Field("get_fluctuation", title="Get Currency Fluctuation", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListSymbols, LatestRates, LatestSpread, HistoricalRates,
    HistoricalSpread, ConvertCurrency, ConvertHistoricalCurrency, TimeSeries,
    TimeSeriesSpread, Fluctuation], Field(discriminator="operation")]


class FixerIoNodeConfig(NodeConfig[Operation, FixerIoAPIKeyCredential]):
    pass


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _rates(value, *, nested=False, fluctuation=False):
    if not isinstance(value, dict):
        raise ValueError("Fixer returned invalid rates")
    for code, rate in value.items():
        if nested:
            date.fromisoformat(code)
            _rates(rate)
        elif not re.fullmatch(r"[A-Z]{3}", code):
            raise ValueError("Fixer returned an invalid currency code")
        elif fluctuation:
            if not isinstance(rate, dict) or not all(_number(rate.get(k)) for k in ("start_rate", "end_rate", "change", "change_pct")):
                raise ValueError("Fixer returned invalid fluctuation metrics")
        elif not _number(rate):
            if not isinstance(rate, dict) or not _number(rate.get("rate")) or any(not _number(rate[k]) for k in ("bid", "ask", "spread") if k in rate):
                raise ValueError("Fixer returned an invalid exchange rate")


class FixerIoNode(WorkflowNode):
    integration_type = "automation-fixer-io"
    connection_evidence = ConnectionEvidence(operation="list_symbols", noun="supported currencies", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return FixerIoNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Fixer Io API access key")
        op = self.config.config
        key = self.config.credentials.access_key
        params = {"access_key": key}
        if isinstance(op, ListSymbols):
            path = "/symbols"
        elif isinstance(op, ConvertCurrency):
            path = "/convert"
            params.update({"from": op.from_currency, "to": op.to_currency, "amount": op.amount})
            if isinstance(op, ConvertHistoricalCurrency):
                params["date"] = op.date
        else:
            params.update({k: v for k, v in op.model_dump().items() if k in {"base", "symbols", "start_date", "end_date"} and v is not None})
            if isinstance(op, HistoricalRates):
                path = "/" + op.date
            elif isinstance(op, (TimeSeries, TimeSeriesSpread)):
                path = "/timeseries"
            elif isinstance(op, Fluctuation):
                path = "/fluctuation"
            else:
                path = "/latest"
            if isinstance(op, (LatestSpread, HistoricalSpread, TimeSeriesSpread)):
                params["spread"] = 1
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.get(BASE_URL + path, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Fixer request could not be completed") from None
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Fixer returned a non-JSON response") from None
        if isinstance(body, dict) and body.get("success") is False:
            error = body.get("error")
            message = (error.get("info") or error.get("type")) if isinstance(error, dict) else None
            raise ValueError(_redact(message or "Fixer rejected the request", key))
        if response.status_code != 200:
            raise ValueError(f"Fixer request failed (HTTP {response.status_code})")
        if not isinstance(body, dict) or body.get("success") is not True:
            raise ValueError("Fixer did not confirm a successful response")
        if isinstance(op, ListSymbols):
            symbols = body.get("symbols")
            if not isinstance(symbols, dict) or any(not isinstance(v, str) for v in symbols.values()):
                raise ValueError("Fixer returned invalid currency symbols")
        elif isinstance(op, ConvertCurrency):
            if not _number(body.get("result")):
                raise ValueError("Fixer returned an invalid conversion result")
        else:
            _rates(body.get("rates"), nested=isinstance(op, (TimeSeries, TimeSeriesSpread)), fluctuation=isinstance(op, Fluctuation))
        output = _redact({**body, "operation": op.operation, "status": "success"}, key)
        await self.emit(output)
        return output
