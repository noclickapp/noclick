"""Weatherbit weather, air quality, agriculture and energy reads, plus lightning polling."""
from datetime import date, datetime
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.weatherbit_operations import OPERATIONS, PARAMETERS
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.weatherbit.io/v2.0"


class WeatherbitAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Weatherbit API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.weatherbit.io/account/dashboard",
        "x-credential-instructions": "Paste your Weatherbit API key from your account dashboard. Product access depends on your subscription. NoClick checks the key's subscription usage; this does not identify a person.",
    })
    credential_type: Literal["weatherbit_api_key"] = Field("weatherbit_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the key without spaces or a header")
        return value


class WeatherbitInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def dates(self):
        values = self.model_dump()
        for name in ("start_date", "end_date", "date"):
            value = values.get(name)
            if value:
                try:
                    datetime.strptime(value, "%Y-%m-%d:%H") if len(value) == 13 else date.fromisoformat(value)
                except ValueError:
                    raise ValueError("Use YYYY-MM-DD or YYYY-MM-DD:HH for historical dates") from None
        for name in ("start_day", "end_day"):
            if values.get(name):
                try:
                    datetime.strptime("2000-" + values[name], "%Y-%m-%d")
                except ValueError:
                    raise ValueError("Use MM-DD for climate normal days") from None
        if values.get("start_date") and values.get("end_date") and values["start_date"] >= values["end_date"]:
            raise ValueError("End date must follow start date")
        return self


BOUNDS = {"lat": (-90, 90), "lon": (-180, 180), "days": (1, 16), "hours": (1, 240),
          "limit": (1, 1000), "skip": (0, 1000000), "search_distance_km": (1, 75), "search_mins": (1, 45)}


def _field(name, required, operation):
    spec = PARAMETERS[name]
    kind = {"number": float, "integer": int, "string": str, "array": list[str]}[spec["type"]]
    if spec.get("enum"):
        kind = Literal[tuple(spec["enum"])]
    if name == "tp" and operation in {"get_climate_normals", "get_historical_energy"}:
        kind = Literal["daily", "hourly", "monthly"]
    if spec["type"] == "array" and spec.get("items", {}).get("enum"):
        kind = list[Literal[tuple(spec["items"]["enum"])]]
    kwargs = {"title": name.replace("_", " ").title(), "description": spec.get("description", "")}
    if name in BOUNDS:
        kwargs.update(ge=BOUNDS[name][0], le=BOUNDS[name][1])
    if kind is str:
        kwargs.update(min_length=1, max_length=1000)
    if name in {"units", "tz"}:
        kind = Literal["M", "S", "I"] if name == "units" else Literal["local", "utc"]
    return (kind if required else Optional[kind], Field(... if required else None, **kwargs))


def _make_model(name, spec):
    path, fields, required = spec
    required = set(required)
    # A coordinate pair makes every weather read unambiguous, including (0, 0).
    if "lat" in fields:
        required.update(("lat", "lon"))
    if name == "geocode":
        required.add("city")
    return create_model("Weatherbit" + "".join(x.title() for x in name.split("_")) + "Config",
        __base__=WeatherbitInput, __module__=__name__,
        operation=(Literal[name], Field(name, json_schema_extra={"ui:hidden": True,
            "x-display-name": name.replace("_", " ").title(), "x-is-trigger": False,
            "x-category": "Account" if path == "/subscription/usage" else "Weather"})),
        **{field: _field(field, field in required, name) for field in fields})


CONFIG_MODELS = {name: _make_model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class WeatherbitOnNewLightningConfig(PollTriggerConfigBase):
    operation: Literal["on_new_lightning"] = Field("on_new_lightning", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Lightning", "x-category": "Triggers"})
    lat: float = Field(..., ge=-90, le=90, title="Latitude")
    lon: float = Field(..., ge=-180, le=180, title="Longitude")
    search_distance_km: int = Field(20, ge=1, le=75, title="Search Radius (km)")
    search_mins: int = Field(45, ge=1, le=45, title="Lookback (minutes)",
        description="Poll more often than this window. Outages beyond it can miss lightning events.")


WeatherbitConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (WeatherbitOnNewLightningConfig,)], Field(discriminator="operation")]


class WeatherbitNodeConfig(NodeConfig[WeatherbitConfig, WeatherbitAPIKeyCredential]):
    pass


class WeatherbitNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-weatherbit"
    connection_evidence = ConnectionEvidence(noun="Weatherbit subscription usage", operation="get_subscription_usage", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return WeatherbitNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_lightning_count")) if config.get("operation") == "on_new_lightning" else True

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("lightning")
        if not isinstance(rows, list):
            return super().resolve_agent_event(output)
        if not rows:
            return None
        lines = [f"Weatherbit detected {len(rows)} new lightning events:"]
        for row in rows[:50]:
            lines.append(f"Lightning {row['id']} at {row.get('timestamp_utc', 'unknown time')} UTC, "
                         f"coordinates {row.get('lat')}, {row.get('lon')}, "
                         f"{row.get('distance_km')} km from the watched point ({row.get('bearing_cardinal')}).")
        if len(rows) > 50:
            lines.append(f"{len(rows) - 50} more events are in the trigger output.")
        return {"text": "\n".join(lines), "title": "New lightning nearby", "conversation_key": None}

    async def _request(self, path, params):
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request("GET", BASE_URL + path, params={**params, "key": key}, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Weatherbit request could not be completed") from None
        if response.status_code == 204:
            return None
        if response.status_code != 200:
            try:
                message = response.json().get("error", "Request rejected")
            except (ValueError, AttributeError):
                message = "Request rejected"
            raise ValueError(f"Weatherbit HTTP {response.status_code}: {str(message).replace(key, '[redacted]')[:2000]}")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Weatherbit did not return JSON") from None
        if not isinstance(body, dict) or "error" in body:
            raise ValueError("Weatherbit returned an invalid response")
        return body

    async def _poll_lightning(self, config):
        params = config.model_dump(include={"lat", "lon", "search_distance_km", "search_mins"})
        params.update(sort="time", output_type="json", limit=1000)
        rows = []
        for offset in range(0, 10000, 1000):
            body = await self._request("/current/lightning", {**params, "skip": offset})
            if body is None:
                break
            page = body.get("lightning")
            if not isinstance(page, list) or any(not isinstance(row, dict) or type(row.get("id")) is not int for row in page):
                raise ValueError("Weatherbit lightning response is missing event identifiers")
            rows.extend(page)
            if len(page) < 1000:
                break
        else:
            raise ValueError("More than 10,000 lightning events in this window; reduce the radius or lookback")
        fresh = await self._filter_unseen(rows, lambda row: str(row["id"]))
        return {"status": "success", "lightning": fresh, "new_lightning_count": len(fresh)}

    async def execute(self, inputs):
        if not isinstance(self.config, WeatherbitNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Weatherbit API key")
        config = self.config.config
        if isinstance(config, WeatherbitOnNewLightningConfig):
            return await self._poll_lightning(config)
        path, fields, _ = OPERATIONS[config.operation]
        params = config.model_dump(include=set(fields), exclude_none=True)
        if isinstance(params.get("include"), list):
            params["include"] = ",".join(params["include"])
        body = await self._request(path, params)
        return {"status": "success", "operation": config.operation, "data": body, "no_data": body is None}
