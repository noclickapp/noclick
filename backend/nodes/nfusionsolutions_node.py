"""nFusion Solutions Market Data API v1, pinned to the provider's OpenAPI.

Token authentication stays on the fixed provider host. History poll triggers
monitor the configured date window for new or changed OHLC intervals.
Contract: https://api.nfusionsolutions.biz/swagger/1/swagger.json
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://api.nfusionsolutions.biz"


class NFusionTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Nfusion Solutions API Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.nfusionsolutions.com/",
            "x-credential-instructions": "In your nFusion Dashboard, open Connections and copy the Market Data API token from API Keys. A commercial market data license is required. Paste the token here; NoClick sends it to the nFusion API from the server.",
        },
    )
    credential_type: Literal["nfusionsolutions_token"] = Field(
        "nfusionsolutions_token", json_schema_extra={"ui:hidden": True}
    )
    token: str = Field(
        ...,
        title="API token",
        repr=False,
        min_length=1,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("token", mode="before")
    @classmethod
    def clean_token(cls, value):
        return clean_secret(value, field_name="API token")


class AdjustmentValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(..., min_length=1)
    ask: float | None = None
    bid: float | None = None
    askAdjustment: float | None = None
    bidAdjustment: float | None = None
    previousClose: float | None = None


class SymbolAdjustments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    expiresOn: datetime | None = None
    adjustments: list[AdjustmentValue] | None = None


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _WriteConfig(_Config):
    items_json: Json[list[SymbolAdjustments]] = Field(
        ...,
        title="Adjustment settings (JSON)",
        description="Array of settings. Each requires enabled and may include expiresOn and adjustments. Each adjustment requires symbol and may set ask, bid, askAdjustment, bidAdjustment or previousClose. This changes your tenant's price adjustments.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class ListRateCurrenciesConfig(_Config):
    """Get list of currencies supported by the rate endpoint."""

    operation: Literal["list_rate_currencies"] = Field(
        "list_rate_currencies",
        title="Get list of currencies supported by the rate endpoint",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class ListSummaryCurrencyPairsConfig(_Config):
    """Get list of currency pairs supported by the Summary endpoint."""

    operation: Literal["list_summary_currency_pairs"] = Field(
        "list_summary_currency_pairs",
        title="Get list of currency pairs supported by the Summary endpoint",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class ListHistoryCurrencyPairsConfig(_Config):
    """Get list of currency pairs supported by the history endpoint."""

    operation: Literal["list_history_currency_pairs"] = Field(
        "list_history_currency_pairs",
        title="Get list of currency pairs supported by the history endpoint",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class GetCurrencyRatesConfig(_Config):
    """Get latest mid rate for requested currency pairs."""

    operation: Literal["get_currency_rates"] = Field(
        "get_currency_rates",
        title="Get latest mid rate for requested currency pairs",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )
    pairs: str = Field(
        ...,
        title="Pairs",
        description="comma separated list of currency pairs. For example: USD/CAD,USD/EUR,USD/AUD",
    )
    applyTenantAdjustments: bool | None = Field(
        None, title="Apply tenant adjustments", description=""
    )


class GetCurrencySummaryConfig(_Config):
    """Get latest Summary for requested currency pairs."""

    operation: Literal["get_currency_summary"] = Field(
        "get_currency_summary",
        title="Get latest Summary for requested currency pairs",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )
    pairs: str = Field(
        ...,
        title="Pairs",
        description="comma separated list of currency pairs. For example: USD/CAD,USD/EUR,USD/AUD",
    )
    applyTenantAdjustments: bool | None = Field(
        None,
        title="Apply tenant adjustments",
        description="when false, tenant adjustments configured via Dashboard or the adjustments API are not applied. Defaults to true.",
    )


class GetCurrencyHistoryConfig(_Config):
    """Get historical prices for requested currency pairs."""

    operation: Literal["get_currency_history"] = Field(
        "get_currency_history",
        title="Get historical prices for requested currency pairs",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )
    pairs: str = Field(
        ...,
        title="Pairs",
        description="comma separated list of currency pairs. For example: USD/CAD,USD/EUR,USD/AUD",
    )
    start: datetime = Field(
        ...,
        title="Start date and time",
        description="start date of time period. format is yyyy-mm-dd Accepts ISO 8601 date or timestamp.",
    )
    end: datetime | None = Field(
        None,
        title="End date and time",
        description="end date of time period. format is yyyy-mm-dd. Default is current date. Accepts ISO 8601 date or timestamp.",
    )
    interval: str | None = Field(
        None,
        title="Aggregation interval",
        description='aggregation interval. Composed of an optional integer value (which defaults to 1 when not specified), \r\nfollowed by a type string which must be one of the following values:\r\ny=year,\r\nm=month,\r\nw=week,\r\nd=day,\r\nh=hour,\r\nmi=minute\r\n\r\nFor example, a yearly interval can be specified as "y" and 6 month interval as "6m". \r\n\r\nIf not specified the interval parameter default is 1 Day.',
    )


class GetCurrencyAdjustmentsConfig(_Config):
    """Read the currency adjustments."""

    operation: Literal["get_currency_adjustments"] = Field(
        "get_currency_adjustments",
        title="Read the currency adjustments",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class UpdateCurrencyAdjustmentsConfig(_WriteConfig):
    """Update the currency adjustments."""

    operation: Literal["update_currency_adjustments"] = Field(
        "update_currency_adjustments",
        title="Update the currency adjustments",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class ListMetalCurrenciesConfig(_Config):
    """Get list of currencies supported by metals endpoints for currency conversion."""

    operation: Literal["list_metal_currencies"] = Field(
        "list_metal_currencies",
        title="Get list of currencies supported by metals endpoints for currency conversion",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class ListSpotMetalsConfig(_Config):
    """Get list of symbols supported by the spot endpoints."""

    operation: Literal["list_spot_metals"] = Field(
        "list_spot_metals",
        title="Get list of symbols supported by the spot endpoints",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class GetSpotSummaryConfig(_Config):
    """Get latest Spot Summary for requested metals."""

    operation: Literal["get_spot_summary"] = Field(
        "get_spot_summary",
        title="Get latest Spot Summary for requested metals",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )
    metals: str = Field(
        ..., title="Metals", description="comma separated list of metals"
    )
    currency: str | None = Field(
        None,
        title="Conversion currencies",
        description="comma separated list of conversion currencies, defaults to USD",
    )
    unitofmeasure: Literal["mg", "g", "kg", "gr", "toz", "ct", "dwt"] | None = Field(
        None,
        title="Unit of measure",
        description="unit of meaure, defaults to troy ounces. allowed values are:\r\nmg=milligram\r\ng=gram\r\nkg=kilogram\r\ngr=grain\r\ntoz=troy ounce\r\nct=carat\r\ndwt=pennyweight",
    )
    applyTenantAdjustments: bool | None = Field(
        None,
        title="Apply tenant adjustments",
        description="when false, tenant adjustments configured via Dashboard or the adjustments API are not applied. Defaults to true.",
    )


class GetSpotHistoryConfig(_Config):
    """Get historical Spot prices for requested metals."""

    operation: Literal["get_spot_history"] = Field(
        "get_spot_history",
        title="Get historical Spot prices for requested metals",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )
    metals: str = Field(
        ..., title="Metals", description="comma separated list of metals"
    )
    start: datetime = Field(
        ...,
        title="Start date and time",
        description="start date of time period. format is yyyy-mm-dd Accepts ISO 8601 date or timestamp.",
    )
    end: datetime | None = Field(
        None,
        title="End date and time",
        description="end date of time period. format is yyyy-mm-dd. Default is current date. Accepts ISO 8601 date or timestamp.",
    )
    interval: str | None = Field(
        None,
        title="Aggregation interval",
        description='aggregation interval. Composed of an optional integer value (which defaults to 1 when not specified), \r\nfollowed by a type string which must be one of the following values:\r\ny=year,\r\nm=month,\r\nw=week,\r\nd=day,\r\nh=hour,\r\nmi=minute\r\n\r\nFor example, a yearly interval can be specified as "y" and 6 month interval as "6m". \r\n\r\nIf not specified the interval parameter default is 1 Day.',
    )
    historicalfx: bool | None = Field(
        None,
        title="Use historical exchange rates",
        description="if true use historical currency rates otherwise current currency rates. Defaults to true.",
    )
    currency: str | None = Field(
        None,
        title="Conversion currencies",
        description="comma separated list of conversion currencies, defaults to USD",
    )
    unitofmeasure: Literal["mg", "g", "kg", "gr", "toz", "ct", "dwt"] | None = Field(
        None,
        title="Unit of measure",
        description="unit of meaure, defaults to troy ounces. allowed values are:\r\nmg=milligram\r\ng=gram\r\nkg=kilogram\r\ngr=grain\r\ntoz=troy ounce\r\nct=carat\r\ndwt=pennyweight",
    )


class GetSpotRatioSummaryConfig(_Config):
    """Get latest Spot Summary for requested metal ratios."""

    operation: Literal["get_spot_ratio_summary"] = Field(
        "get_spot_ratio_summary",
        title="Get latest Spot Summary for requested metal ratios",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )
    pairs: str = Field(
        ...,
        title="Pairs",
        description="comma separated list of metal pairs. For example: gold/silver,gold/platinum,silver/palladium",
    )


class GetSpotRatioHistoryConfig(_Config):
    """Get historical Spot Ratio prices for requested metals."""

    operation: Literal["get_spot_ratio_history"] = Field(
        "get_spot_ratio_history",
        title="Get historical Spot Ratio prices for requested metals",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )
    pairs: str = Field(..., title="Pairs", description="comma separated list of metals")
    start: datetime = Field(
        ...,
        title="Start date and time",
        description="start date of time period. format is yyyy-mm-dd Accepts ISO 8601 date or timestamp.",
    )
    end: datetime | None = Field(
        None,
        title="End date and time",
        description="end date of time period. format is yyyy-mm-dd. Default is current date. Accepts ISO 8601 date or timestamp.",
    )
    interval: str | None = Field(
        None,
        title="Aggregation interval",
        description='aggregation interval. Composed of an optional integer value (which defaults to 1 when not specified), \r\nfollowed by a type string which must be one of the following values:\r\ny=year,\r\nm=month,\r\nw=week,\r\nd=day,\r\nh=hour,\r\nmi=minute\r\n\r\nFor example, a yearly interval can be specified as "y" and 6 month interval as "6m". \r\n\r\nIf not specified the interval parameter default is 1 Day.',
    )


class ListBenchmarkMetalsConfig(_Config):
    """Get list of symbols supported by the benchmark endpoints."""

    operation: Literal["list_benchmark_metals"] = Field(
        "list_benchmark_metals",
        title="Get list of symbols supported by the benchmark endpoints",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class GetBenchmarkSummaryConfig(_Config):
    """Get latest Benchmark prices for requested metals."""

    operation: Literal["get_benchmark_summary"] = Field(
        "get_benchmark_summary",
        title="Get latest Benchmark prices for requested metals",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )
    metals: str = Field(
        ..., title="Metals", description="comma separated list of metals"
    )
    currency: str | None = Field(
        None,
        title="Conversion currencies",
        description="comma separated list of conversion currencies, defaults to USD",
    )
    unitofmeasure: Literal["mg", "g", "kg", "gr", "toz", "ct", "dwt"] | None = Field(
        None,
        title="Unit of measure",
        description="unit of meaure, defaults to troy ounces. allowed values are:\r\nmg=milligram\r\ng=gram\r\nkg=kilogram\r\ngr=grain\r\ntoz=troy ounce\r\nct=carat\r\ndwt=pennyweight",
    )
    applyTenantAdjustments: bool | None = Field(
        None, title="Apply tenant adjustments", description=""
    )


class GetBenchmarkHistoryConfig(_Config):
    """Get historical benchmark prices for requested metals."""

    operation: Literal["get_benchmark_history"] = Field(
        "get_benchmark_history",
        title="Get historical benchmark prices for requested metals",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )
    metals: str = Field(
        ..., title="Metals", description="comma separated list of metals"
    )
    start: datetime = Field(
        ...,
        title="Start date and time",
        description="start date of time period. format is yyyy-mm-dd Accepts ISO 8601 date or timestamp.",
    )
    end: datetime | None = Field(
        None,
        title="End date and time",
        description="end date of time period. format is yyyy-mm-dd. Default is current date. Accepts ISO 8601 date or timestamp.",
    )
    interval: str | None = Field(
        None,
        title="Aggregation interval",
        description='aggregation interval. Composed of an optional integer value (which defaults to 1 when not specified), \r\nfollowed by a type string which must be one of the following values:\r\ny=year,\r\nm=month,\r\nw=week,\r\nd=day,\r\nh=hour,\r\nmi=minute\r\n\r\nFor example, a yearly interval can be specified as "y" and 6 month interval as "6m". \r\n\r\nIf not specified the interval parameter default is 1 Day.',
    )
    historicalfx: bool | None = Field(
        None,
        title="Use historical exchange rates",
        description="if true use historical currency rates otherwise current currency rates. Defaults to true.",
    )
    currency: str | None = Field(
        None,
        title="Conversion currencies",
        description="comma separated list of conversion currencies, defaults to USD",
    )
    unitofmeasure: Literal["mg", "g", "kg", "gr", "toz", "ct", "dwt"] | None = Field(
        None,
        title="Unit of measure",
        description="unit of meaure, defaults to troy ounces. allowed values are:\r\nmg=milligram\r\ng=gram\r\nkg=kilogram\r\ngr=grain\r\ntoz=troy ounce\r\nct=carat\r\ndwt=pennyweight",
    )


class GetMetalAdjustmentsConfig(_Config):
    """Read the spot adjustments."""

    operation: Literal["get_metal_adjustments"] = Field(
        "get_metal_adjustments",
        title="Read the spot adjustments",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class UpdateMetalAdjustmentsConfig(_WriteConfig):
    """Update the spot adjustments."""

    operation: Literal["update_metal_adjustments"] = Field(
        "update_metal_adjustments",
        title="Update the spot adjustments",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": False},
    )


class OnNewOrUpdatedSpotIntervalConfig(GetSpotHistoryConfig, PollTriggerConfigBase):
    """Poll the configured historical window for new or changed OHLC intervals.

    Set start to the beginning of the window to monitor. Provider result limits
    apply; choose an interval and window small enough to avoid truncation.
    """

    model_config = ConfigDict(
        extra="ignore", json_schema_extra={"x-requires-webhook": True}
    )

    operation: Literal["on_new_or_updated_spot_interval"] = Field(
        "on_new_or_updated_spot_interval",
        title="On New Or Updated Spot Interval",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True},
    )


class OnNewOrUpdatedCurrencyIntervalConfig(
    GetCurrencyHistoryConfig, PollTriggerConfigBase
):
    """Poll the configured historical window for new or changed OHLC intervals.

    Set start to the beginning of the window to monitor. Provider result limits
    apply; choose an interval and window small enough to avoid truncation.
    """

    model_config = ConfigDict(
        extra="ignore", json_schema_extra={"x-requires-webhook": True}
    )

    operation: Literal["on_new_or_updated_currency_interval"] = Field(
        "on_new_or_updated_currency_interval",
        title="On New Or Updated Currency Interval",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True},
    )


OPERATIONS = {
    "list_rate_currencies": {
        "method": "GET",
        "path": "/api/v1/Currencies/rate/supported",
        "parameters": [],
        "operation_id": "Currencies_SupportedCurrencies_Rate_GET",
    },
    "list_summary_currency_pairs": {
        "method": "GET",
        "path": "/api/v1/Currencies/summary/supported",
        "parameters": [],
        "operation_id": "Currencies_SupportedCurrencies_Summary_GET",
    },
    "list_history_currency_pairs": {
        "method": "GET",
        "path": "/api/v1/Currencies/history/supported",
        "parameters": [],
        "operation_id": "Currencies_SupportedCurrencies_History_GET",
    },
    "get_currency_rates": {
        "method": "GET",
        "path": "/api/v1/Currencies/rate",
        "parameters": ["pairs", "applyTenantAdjustments"],
        "operation_id": "Currencies_Rate_GET",
    },
    "get_currency_summary": {
        "method": "GET",
        "path": "/api/v1/Currencies/summary",
        "parameters": ["pairs", "applyTenantAdjustments"],
        "operation_id": "Currencies_Summary_GET",
    },
    "get_currency_history": {
        "method": "GET",
        "path": "/api/v1/Currencies/history",
        "parameters": ["pairs", "start", "end", "interval"],
        "operation_id": "Currencies_History_GET",
    },
    "get_currency_adjustments": {
        "method": "GET",
        "path": "/api/v1/Currencies/adjustments",
        "parameters": [],
        "operation_id": "Currencies_Adjustments_GET",
    },
    "update_currency_adjustments": {
        "method": "POST",
        "path": "/api/v1/Currencies/adjustments",
        "parameters": [],
        "operation_id": "Currencies_UpdateAdjustment_POST",
    },
    "list_metal_currencies": {
        "method": "GET",
        "path": "/api/v1/Metals/supported/currency",
        "parameters": [],
        "operation_id": "Metals_SupportedCurrencies_Metals_GET",
    },
    "list_spot_metals": {
        "method": "GET",
        "path": "/api/v1/Metals/spot/supported",
        "parameters": [],
        "operation_id": "Metals_SpotSupportedMetals_GET",
    },
    "get_spot_summary": {
        "method": "GET",
        "path": "/api/v1/Metals/spot/summary",
        "parameters": ["metals", "currency", "unitofmeasure", "applyTenantAdjustments"],
        "operation_id": "Metals_SpotSummary_GET",
    },
    "get_spot_history": {
        "method": "GET",
        "path": "/api/v1/Metals/spot/history",
        "parameters": [
            "metals",
            "start",
            "end",
            "interval",
            "historicalfx",
            "currency",
            "unitofmeasure",
        ],
        "operation_id": "Metals_SpotHistory_GET",
    },
    "get_spot_ratio_summary": {
        "method": "GET",
        "path": "/api/v1/Metals/spot/ratio/summary",
        "parameters": ["pairs"],
        "operation_id": "Metals_SpotRatioSummary_GET",
    },
    "get_spot_ratio_history": {
        "method": "GET",
        "path": "/api/v1/Metals/spot/ratio/history",
        "parameters": ["pairs", "start", "end", "interval"],
        "operation_id": "Metals_SpotRatioHistory_GET",
    },
    "list_benchmark_metals": {
        "method": "GET",
        "path": "/api/v1/Metals/benchmark/supported",
        "parameters": [],
        "operation_id": "Metals_BenchmarkSupportedMetals_GET",
    },
    "get_benchmark_summary": {
        "method": "GET",
        "path": "/api/v1/Metals/benchmark/summary",
        "parameters": ["metals", "currency", "unitofmeasure", "applyTenantAdjustments"],
        "operation_id": "Metals_BenchmarkSummary_GET",
    },
    "get_benchmark_history": {
        "method": "GET",
        "path": "/api/v1/Metals/benchmark/history",
        "parameters": [
            "metals",
            "start",
            "end",
            "interval",
            "historicalfx",
            "currency",
            "unitofmeasure",
        ],
        "operation_id": "Metals_BenchmarkHistory_GET",
    },
    "get_metal_adjustments": {
        "method": "GET",
        "path": "/api/v1/Metals/adjustments",
        "parameters": [],
        "operation_id": "Metals_MetalAdjustments_GET",
    },
    "update_metal_adjustments": {
        "method": "POST",
        "path": "/api/v1/Metals/adjustments",
        "parameters": [],
        "operation_id": "Metals_UpdateSpotAdjustments_POST",
    },
}

NFusionConfig = Annotated[
    Union[
        ListRateCurrenciesConfig,
        ListSummaryCurrencyPairsConfig,
        ListHistoryCurrencyPairsConfig,
        GetCurrencyRatesConfig,
        GetCurrencySummaryConfig,
        GetCurrencyHistoryConfig,
        GetCurrencyAdjustmentsConfig,
        UpdateCurrencyAdjustmentsConfig,
        ListMetalCurrenciesConfig,
        ListSpotMetalsConfig,
        GetSpotSummaryConfig,
        GetSpotHistoryConfig,
        GetSpotRatioSummaryConfig,
        GetSpotRatioHistoryConfig,
        ListBenchmarkMetalsConfig,
        GetBenchmarkSummaryConfig,
        GetBenchmarkHistoryConfig,
        GetMetalAdjustmentsConfig,
        UpdateMetalAdjustmentsConfig,
        OnNewOrUpdatedSpotIntervalConfig,
        OnNewOrUpdatedCurrencyIntervalConfig,
    ],
    Field(discriminator="operation"),
]


class NFusionNodeConfig(NodeConfig[NFusionConfig, NFusionTokenCredential]):
    pass


class NFusionSolutionsNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-nfusionsolutions"
    credential_provider_labels = {"nfusionsolutions": "nFusion Solutions"}
    connection_evidence = ConnectionEvidence(
        operation="get_metal_adjustments",
        noun="metal adjustment settings",
        proves="reachability",
    )
    edit_examples = [
        "Get gold and silver spot prices",
        "Read historical currency rates",
        "Update my metal price adjustments",
    ]

    @classmethod
    def get_config_model(cls):
        return NFusionNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation", "").startswith("on_"):
            return bool(output.get("interval_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "intervals" not in output:
            return super().resolve_agent_event(output)
        intervals = output["intervals"]
        if not intervals:
            return None
        lines = [
            f"- {item['symbol']} ({item['currency'] or 'base currency'}): {item['interval']}"
            for item in intervals[:10]
        ]
        return {
            "text": f"nFusion Solutions: {len(intervals)} new or updated market price interval(s).\n"
            + "\n".join(lines),
            "conversation_key": None,
        }

    async def _request(self, operation, config):
        spec = OPERATIONS[operation]
        token = self.config.credentials.token
        values = config.model_dump(mode="json", exclude_none=True)
        params = {key: values[key] for key in spec["parameters"] if key in values}
        params["token"] = token
        body = None
        if spec["method"] == "GET" and "adjustments" not in spec["path"]:
            params["format"] = "json"
        if spec["method"] == "POST":
            items = config.items_json
            body = {
                "token": token,
                "items": [
                    item.model_dump(mode="json", exclude_unset=True) for item in items
                ],
            }
        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    spec["method"],
                    BASE_URL + spec["path"],
                    params=params,
                    json=body,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError:
            raise ValueError(
                "nFusion Solutions request could not be completed"
            ) from None
        if not response.is_success:
            # Do not expose response URLs: this API authenticates in the query string.
            message = response.text.replace(token, "[redacted]")[:1000]
            raise ValueError(
                f"nFusion Solutions HTTP {response.status_code}: {message}"
            )
        try:
            data = response.json()
        except ValueError:
            raise ValueError("nFusion Solutions returned a non-JSON response") from None
        if not isinstance(data, (list, dict)):
            raise ValueError("nFusion Solutions returned an unexpected response shape")
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("success") is False:
                raise ValueError(
                    "nFusion Solutions: "
                    + str(item.get("error") or "Market data request failed").replace(
                        token, "[redacted]"
                    )
                )
        return data

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an nFusion Solutions API token")
        config = self.config.config
        poll = config.operation.startswith("on_")
        operation = {
            "on_new_or_updated_spot_interval": "get_spot_history",
            "on_new_or_updated_currency_interval": "get_currency_history",
        }.get(config.operation, config.operation)
        data = await self._request(operation, config)
        if not poll:
            return {"status": "success", "data": data}
        if not isinstance(data, list):
            raise ValueError("nFusion history must be an array")
        intervals = []
        for response in data:
            if not isinstance(response, dict):
                raise ValueError("nFusion returned an invalid history entry")
            collection = response.get("data")
            if collection is None:
                continue
            for interval in collection.get("intervals") or []:
                intervals.append(
                    {
                        "symbol": collection.get("symbol"),
                        "currency": collection.get("baseCurrency"),
                        "requested_symbol": response.get("requestedSymbol"),
                        "requested_currency": response.get("requestedCurrency"),
                        "unit_of_measure": response.get("requestedUnitOfMeasure"),
                        "interval": interval,
                    }
                )
        fresh = await self._filter_unseen(
            intervals,
            lambda item: hashlib.sha256(
                json.dumps(item, sort_keys=True).encode()
            ).hexdigest(),
        )
        return {"status": "success", "intervals": fresh, "interval_count": len(fresh)}
