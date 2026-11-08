"""Fixer exchange rates, conversion and analysis using its published v1 contract.

Each action makes one GET to data.fixer.io. Fixer publishes no write endpoints.
Quote actions request spread=1; bid/ask availability and access depend on plan.
Reference: https://api.swaggerhub.com/apis/apilayer-863/FixerAPI/1.0.0/swagger.json
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
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://data.fixer.io/api"
CREDENTIAL_TYPE = "fixer_api_key"


class FixerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Fixer API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://fixer.io/dashboard",
            "x-credential-instructions": "Paste your Fixer API access key from your dashboard. NoClick sends it as access_key over HTTPS to data.fixer.io. Some operations, custom base currencies and bid/ask quotes require a paid plan. The connection read checks that the key is accepted; it does not identify an account.",
        },
    )
    credential_type: Literal["fixer_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the API access key without whitespace")
        return value


def _currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value.strip()):
        raise ValueError("Use a three-letter currency code, such as EUR")
    return value.strip().upper()


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use a date in YYYY-MM-DD format")
    date.fromisoformat(value)
    return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class ListCurrencies(_Input):
    """List supported currency codes and names; also checks key reachability."""
    operation: Literal["list_currencies"] = "list_currencies"


class _Rates(_Input):
    base: str | None = Field(None, description="Optional base currency; Fixer defaults to EUR. Changing it requires a supported plan.")
    symbols: str | None = Field(None, max_length=1000, description="Optional comma-separated currency codes, for example USD,GBP,JPY. Omit for all currencies.")

    @field_validator("base", mode="before")
    @classmethod
    def base_code(cls, value):
        return _currency(value) if value is not None else None

    @field_validator("symbols", mode="before")
    @classmethod
    def symbol_codes(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("Use comma-separated currency codes")
        return ",".join(_currency(code) for code in value.split(","))


class GetLatestRates(_Rates):
    """Get the latest exchange rates for all or selected currencies."""
    operation: Literal["get_latest_rates"] = "get_latest_rates"


class GetLatestQuotes(_Rates):
    """Get latest mid rates with available bid/ask quotes (Professional or higher)."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "professional", "x-tier-label": "Professional or higher"})
    operation: Literal["get_latest_quotes"] = "get_latest_quotes"


class _Historical(_Rates):
    date: str = Field(..., description="Historical rate date, YYYY-MM-DD.")
    _day = field_validator("date", mode="before")(_date)


class GetHistoricalRates(_Historical):
    """Get exchange rates for a historical date."""
    operation: Literal["get_historical_rates"] = "get_historical_rates"


class GetHistoricalQuotes(_Historical):
    """Get historical mid rates and available bid/ask quotes after September 24, 2026."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "professional", "x-tier-label": "Professional or higher"})
    operation: Literal["get_historical_quotes"] = "get_historical_quotes"


class _Conversion(_Input):
    from_currency: str = Field(..., title="From currency", description="Source currency code, for example EUR.")
    to_currency: str = Field(..., title="To currency", description="Target currency code, for example GBP.")
    amount: float = Field(..., allow_inf_nan=False, description="Amount to convert.")
    _codes = field_validator("from_currency", "to_currency", mode="before")(_currency)


class ConvertCurrency(_Conversion):
    """Convert an amount using the latest available exchange rate."""
    operation: Literal["convert_currency"] = "convert_currency"


class ConvertHistoricalCurrency(_Conversion):
    """Convert an amount using a specified historical date."""
    operation: Literal["convert_historical_currency"] = "convert_historical_currency"
    date: str = Field(..., description="Conversion date, YYYY-MM-DD.")
    _day = field_validator("date", mode="before")(_date)


class _Range(_Rates):
    start_date: str = Field(..., description="Start date, YYYY-MM-DD.")
    end_date: str = Field(..., description="End date, YYYY-MM-DD.")
    _days = field_validator("start_date", "end_date", mode="before")(_date)

    @model_validator(mode="after")
    def order(self):
        if self.start_date > self.end_date:
            raise ValueError("End date must be on or after start date")
        return self


class GetTimeSeries(_Range):
    """Get daily exchange rates between two dates."""
    operation: Literal["get_time_series"] = "get_time_series"


class GetTimeSeriesQuotes(_Range):
    """Get daily rates and available bid/ask quotes (Professional or higher)."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "professional", "x-tier-label": "Professional or higher"})
    operation: Literal["get_time_series_quotes"] = "get_time_series_quotes"


class GetFluctuations(_Range):
    """Get currency change and percentage change between two dates."""
    operation: Literal["get_fluctuations"] = "get_fluctuations"


FixerOperation = Annotated[Union[
    ListCurrencies, GetLatestRates, GetLatestQuotes, GetHistoricalRates,
    GetHistoricalQuotes, ConvertCurrency, ConvertHistoricalCurrency,
    GetTimeSeries, GetTimeSeriesQuotes, GetFluctuations,
], Field(discriminator="operation")]


class FixerFullConfig(NodeConfig[FixerOperation, FixerAPIKeyCredential]):
    pass


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Fixer returned an invalid number")
    return value


def _quote(value):
    if type(value) in (int, float):
        return _number(value)
    if not isinstance(value, dict) or "rate" not in value:
        raise ValueError("Fixer returned an invalid quote")
    return {key: _number(value[key]) for key in ("rate", "bid", "ask", "spread") if key in value}


def _mapping(value, project):
    if not isinstance(value, dict):
        raise ValueError("Fixer returned an invalid rates map")
    return {key: project(item) for key, item in value.items()}


def _project(body, path):
    """Preserve documented JSON, including optional bid/ask fields and nested dates."""
    if not isinstance(body, dict) or body.get("success") is not True or "error" in body:
        raise ValueError("Fixer did not confirm this request")
    result = {"success": True}
    for key in ("timestamp", "base", "date", "historical", "timeseries", "fluctuation", "start_date", "end_date"):
        if key in body:
            value = body[key]
            if key == "timestamp":
                if type(value) is not int:
                    raise ValueError("Fixer returned an invalid timestamp")
            elif key in {"historical", "timeseries", "fluctuation"}:
                if type(value) is not bool:
                    raise ValueError("Fixer returned an invalid flag")
            elif not isinstance(value, str):
                raise ValueError("Fixer returned invalid metadata")
            result[key] = value
    if path == "/symbols":
        def name(value):
            if not isinstance(value, str):
                raise ValueError("Fixer returned an invalid currency name")
            return value
        result["symbols"] = _mapping(body.get("symbols"), name)
    elif path == "/convert":
        result["result"] = _number(body.get("result"))
        query, info = body.get("query"), body.get("info")
        if not isinstance(query, dict) or not isinstance(info, dict):
            raise ValueError("Fixer returned incomplete conversion metadata")
        result["query"] = {"from": _currency(query.get("from")), "to": _currency(query.get("to")), "amount": _number(query.get("amount"))}
        result["info"] = {"rate": _number(info.get("rate"))}
        if "timestamp" in info:
            result["info"]["timestamp"] = _number(info["timestamp"])
    elif path == "/timeseries":
        result["rates"] = _mapping(body.get("rates"), lambda daily: _mapping(daily, _quote))
    elif path == "/fluctuation":
        def fluctuation(value):
            if not isinstance(value, dict):
                raise ValueError("Fixer returned invalid fluctuation metrics")
            return {key: _number(value[key]) for key in ("start_rate", "end_rate", "change", "change_pct")}
        result["rates"] = _mapping(body.get("rates"), fluctuation)
    else:
        result["rates"] = _mapping(body.get("rates"), _quote)
    return result


class FixerNode(WorkflowNode):
    integration_type = "automation-fixer"
    connection_evidence = ConnectionEvidence(
        noun="supported currencies", operation="list_currencies", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return FixerFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Fixer API key")
        credential, op = self.config.credentials, self.config.config
        params = {"access_key": credential.api_key}
        for key in ("base", "symbols", "start_date", "end_date"):
            value = getattr(op, key, None)
            if value is not None:
                params[key] = value
        if isinstance(op, ListCurrencies):
            path = "/symbols"
        elif isinstance(op, (GetLatestRates, GetLatestQuotes)):
            path = "/latest"
        elif isinstance(op, _Historical):
            path = "/" + op.date
        elif isinstance(op, _Conversion):
            path = "/convert"
            params.update({"from": op.from_currency, "to": op.to_currency, "amount": op.amount})
            if isinstance(op, ConvertHistoricalCurrency):
                params["date"] = op.date
        elif isinstance(op, (GetTimeSeries, GetTimeSeriesQuotes)):
            path = "/timeseries"
        else:
            path = "/fluctuation"
        if isinstance(op, (GetLatestQuotes, GetHistoricalQuotes, GetTimeSeriesQuotes)):
            params["spread"] = 1
        output = {"operation": op.operation}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request("GET", BASE + path, params=params, headers={"Accept": "application/json"})
            output["http_status"] = response.status_code
            if len(response.content) > 8_000_000:
                raise ValueError("Fixer response exceeded the supported size")
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Fixer returned an invalid JSON response") from None
            if isinstance(body, dict) and (body.get("success") is False or "error" in body):
                error = body.get("error")
                message = (error.get("info") or error.get("type")) if isinstance(error, dict) else None
                if not isinstance(message, str):
                    message = "Fixer rejected the request"
                return {**output, "status": "error", "error": message.replace(credential.api_key, "[redacted]")[:2000]}
            if response.status_code != 200:
                return {**output, "status": "error", "error": "Fixer did not confirm this read"}
            return {**output, "status": "success", "data": _project(body, path)}
        except (ValueError, KeyError, SSRFError, httpx.HTTPError):
            return {**output, "status": "error", "error": "Fixer returned an invalid response or the request could not be completed"}
