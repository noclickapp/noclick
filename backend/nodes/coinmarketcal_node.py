"""CoinMarketCal v2: all nine operations in the published read-only contract.

Contract: https://coinmarketcal.com/developer/docs/openapi.json (2.0.0).
Plan-gated fields remain unchanged, including estimated event display dates.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.coinmarketcal.com"


class CoinMarketCalAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Coinmarketcal API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://coinmarketcal.com/developer/dashboard/keys",
            "x-credential-instructions": "Create an API key in your Coinmarketcal developer dashboard, copy its full secret, and paste it here. Your organization plan controls history, filters and exports. NoClick checks your monthly usage to verify access.",
        })
    credential_type: Literal["coinmarketcal_api_key"] = Field("coinmarketcal_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def text_bounds(cls, value):
        if isinstance(value, str) and (len(value) > 4096 or any(ord(c) < 32 for c in value)):
            raise ValueError("Use a bounded value without control characters")
        return value


class Page(Input):
    limit: int = Field(20, ge=1, le=100)
    cursor: Optional[str] = Field(None, description="Copy meta.cursor from the previous page; keep the filters unchanged. Null means the final page.")


class DateRange(Input):
    from_date: Optional[str] = Field(None, description="Inclusive ISO-8601 start with timezone. History depends on your plan.")
    to_date: Optional[str] = Field(None, description="Inclusive ISO-8601 end with timezone.")

    @field_validator("from_date", "to_date")
    @classmethod
    def date(cls, value):
        if value is not None:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if dt.tzinfo is None: raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO-8601 datetime with timezone") from None
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.from_date and self.to_date and datetime.fromisoformat(self.from_date.replace("Z", "+00:00")) > datetime.fromisoformat(self.to_date.replace("Z", "+00:00")):
            raise ValueError("End must be on or after start")
        return self


class ListEvents(Page, DateRange):
    """Find crypto events. Use displayedDate for estimated event dates."""
    operation: Literal["list_events"] = "list_events"
    coins: Optional[str] = Field(None, description="Comma-separated canonical coin slugs, e.g. bitcoin,ethereum.")
    categories: Optional[str] = Field(None, description="Comma-separated category IDs; requires Standard+.")
    keyword: Optional[str] = None
    impact_min: Optional[float] = Field(None, ge=0, le=10, description="Minimum precise impact; requires Elite+.")
    sort_by: Literal["date_asc", "date_desc", "created_desc", "created_desc_and_updated_desc", "impact_desc"] = Field("date_asc", description="impact_desc requires Elite+.")


class ListEventCancellations(Page):
    """Poll permanent removals at least every 90 days."""
    operation: Literal["list_event_cancellations"] = "list_event_cancellations"
    limit: int = Field(100, ge=1, le=100)
    since: Optional[str] = Field(None, description="Inclusive RFC3339 timestamp or YYYY-MM-DD; defaults to 90 days ago.")

    @field_validator("since")
    @classmethod
    def since_date(cls, value):
        if value is not None:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value): datetime.strptime(value, "%Y-%m-%d")
            else: DateRange.date(value)
        return value


class GetEvent(Input):
    operation: Literal["get_event"] = "get_event"
    event_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Event ID returned by list events.")


class ExportEventsCSV(DateRange):
    """Download an inclusive date range as a CSV file (Elite+)."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "elite", "x-tier-label": "Elite+"})
    operation: Literal["export_events_csv"] = "export_events_csv"
    from_date: str = Field(..., description="Inclusive ISO-8601 datetime with timezone.")
    to_date: str = Field(..., description="Inclusive ISO-8601 datetime with timezone.")


class GetEventsSnapshot(Input):
    """Get a private daily CSV.gz link, valid for 15 minutes (Elite+)."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "elite", "x-tier-label": "Elite+"})
    operation: Literal["get_events_snapshot"] = "get_events_snapshot"


class ListCategories(Input):
    """Read the unpaginated taxonomy and tier-windowed counts (Standard+)."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "standard", "x-tier-label": "Standard+"})
    operation: Literal["list_categories"] = "list_categories"


class ListCoins(Page):
    operation: Literal["list_coins"] = "list_coins"
    limit: int = Field(50, ge=1, le=200)
    q: Optional[str] = Field(None, description="Search coin name and symbol.")
    tracked: Optional[StrictBool] = Field(None, description="Omit for all coins; false includes only coins outside active editorial coverage.")


class GetCoin(Input):
    operation: Literal["get_coin"] = "get_coin"
    slug: str = Field(..., min_length=1, max_length=200, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", description="Canonical coin slug, e.g. bitcoin.")


class GetUsage(Input):
    """Read the authenticated key's monthly quota and consumption."""
    operation: Literal["get_usage"] = "get_usage"


CoinMarketCalConfig = Annotated[Union[ListEvents, ListEventCancellations, GetEvent, ExportEventsCSV,
    GetEventsSnapshot, ListCategories, ListCoins, GetCoin, GetUsage], Field(discriminator="operation")]


class CoinMarketCalNodeConfig(NodeConfig[CoinMarketCalConfig, CoinMarketCalAPIKeyCredential]):
    pass


ROUTES = {
    "list_events": "/v2/events", "list_event_cancellations": "/v2/events/cancellations",
    "get_event": "/v2/events/{id}", "export_events_csv": "/v2/exports/events.csv",
    "get_events_snapshot": "/v2/exports/events/snapshot", "list_categories": "/v2/categories",
    "list_coins": "/v2/coins", "get_coin": "/v2/coins/{slug}", "get_usage": "/v2/usage",
}
WIRE = {"from_date": "from", "to_date": "to", "impact_min": "impactMin", "sort_by": "sortBy"}


class CoinMarketCalNode(WorkflowNode):
    integration_type = "automation-coinmarketcal"
    connection_evidence = ConnectionEvidence(noun="API key monthly usage", operation="get_usage", label_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return CoinMarketCalNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CoinMarketCal API key")
        config = self.config.config
        action = config.operation
        path = ROUTES[action]
        if isinstance(config, GetEvent): path = path.replace("{id}", quote(config.event_id, safe=""))
        if isinstance(config, GetCoin): path = path.replace("{slug}", quote(config.slug, safe=""))
        params = {WIRE.get(k, k): str(v).lower() if isinstance(v, bool) else v
                  for k, v in config.model_dump(exclude_none=True).items()
                  if k not in {"operation", "event_id", "slug"}}
        csv = action == "export_events_csv"
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request("GET", BASE + path, params=params, headers={
                "x-api-key": self.config.credentials.api_key, "Accept": "text/csv" if csv else "application/json"})
        # Preserve provider rejection text for the common credential-evidence seam.
        if response.status_code != 200:
            message = "CoinMarketCal request failed"
            try:
                body = response.json()
                if isinstance(body, dict): message = body.get("error") or body.get("message") or message
            except ValueError:
                pass
            message = str(message).replace(self.config.credentials.api_key, "[redacted]")[:1000]
            output = {"status": "error", "http_status": response.status_code, "error": message}
        else:
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if len(response.content) > 4 * 1024 * 1024:
                raise ValueError("CoinMarketCal response exceeds 4 MiB")
            if csv:
                if mime != "text/csv": raise ValueError("Expected a CoinMarketCal CSV response")
                output = {"status": "success", "file": BinaryOutput(response.content, "text/csv", "coinmarketcal-events.csv")}
            else:
                if mime != "application/json": raise ValueError("Expected CoinMarketCal JSON")
                body = response.json()
                if not isinstance(body, dict) or "error" in body or "message" in body:
                    raise ValueError("CoinMarketCal returned an unexpected response")
                if action.startswith("list_"):
                    if not isinstance(body.get("data"), list): raise ValueError("CoinMarketCal list data is missing")
                    if action != "list_categories":
                        meta = body.get("meta")
                        if not isinstance(meta, dict) or not isinstance(meta.get("total"), int) or not isinstance(meta.get("limit"), int) or (meta.get("cursor") is not None and not isinstance(meta["cursor"], str)):
                            raise ValueError("CoinMarketCal pagination metadata is invalid")
                elif action == "get_event" and body.get("id") != config.event_id:
                    raise ValueError("CoinMarketCal returned a different event")
                elif action == "get_coin" and body.get("slug") != config.slug:
                    raise ValueError("CoinMarketCal returned a different coin")
                elif action == "get_usage" and not (isinstance(body.get("tier"), str) and isinstance(body.get("periodYm"), str) and type(body.get("requestCount")) is int):
                    raise ValueError("CoinMarketCal usage counters are missing")
                elif action == "get_events_snapshot" and not (body.get("format") == "csv.gz" and isinstance(body.get("downloadUrl"), str)):
                    raise ValueError("CoinMarketCal snapshot metadata is missing")
                output = {"status": "success", "data": body}
                if action == "get_usage":
                    output["items"] = [{**body, "name": f"{body['tier']}: {body['requestCount']} requests in {body['periodYm']}"}]
        await self.emit(output)
        return output
