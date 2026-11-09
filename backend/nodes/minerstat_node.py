"""Minerstat Data API v3 reads, pinned to the provider's published contract.

All operations make one request. Pagination remains explicit: the returned
provider envelope retains its offset, limit, count, freshness and plan notice.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MinerstatAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Minerstat API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://minerstat.com/developers",
            "x-credential-instructions": "Create an API key in Minerstat Developers and paste it here. Free keys support the catalog reads with up to 20 rows; profitability requires Enterprise. A successful catalog read proves API-key reachability, not account identity.",
        },
    )
    credential_type: Literal["minerstat_api_key"] = Field("minerstat_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class _Page(_Input):
    limit: int = Field(20, ge=1, le=1000, description="Rows per request, capped by your Minerstat plan (20 / 500 / 1000).")
    offset: int = Field(0, ge=0, description="Pagination offset. Increase explicitly to read another page.")


class _Slug(_Input):
    slug: str = Field(..., min_length=1, max_length=200, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
                      description="Stable resource slug from the matching list operation.")


class ListCoins(_Page):
    """List mineable coins with market prices, network metrics and freshness."""
    operation: Literal["list_coins"] = "list_coins"
    algorithm: str | None = Field(None, min_length=1, max_length=200, description="Algorithm slug, for example scrypt.")
    verified: StrictBool | None = Field(None, description="Only coins with confidence at least 70 when true.")


class GetCoin(_Slug):
    """Get one coin's identity, market, network and supply data."""
    operation: Literal["get_coin"] = "get_coin"


class GetCoinHistory(_Slug, _Page):
    """Read a page of historical network snapshots, newest first."""
    operation: Literal["get_coin_history"] = "get_coin_history"
    limit: int = Field(20, ge=1, le=100, description="Up to 100 points; Free plan capped at 20.")


class ListHardware(_Page):
    """List mining hardware with type, power and release date."""
    operation: Literal["list_hardware"] = "list_hardware"
    type: Literal["ASIC", "GPU", "CPU", "FPGA"] | None = None


class GetHardware(_Slug):
    """Get one device's identity and manufacturer specifications."""
    operation: Literal["get_hardware"] = "get_hardware"


class ListAlgorithms(_Page):
    """List mining algorithms with coin and benchmark counts."""
    operation: Literal["list_algorithms"] = "list_algorithms"


class GetAlgorithm(_Slug):
    """Get the coins and hardware supporting one algorithm."""
    operation: Literal["get_algorithm"] = "get_algorithm"


class ListPools(_Page):
    """List mining pools, fees and liveness information."""
    operation: Literal["list_pools"] = "list_pools"


class GetPool(_Slug):
    """Get a pool's per-coin fees, payout schemes and minimum payouts."""
    operation: Literal["get_pool"] = "get_pool"


class GetProfitability(_Input):
    """Rank mining opportunities using a hardware preset or manual hashrate."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False,
                            json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_profitability"] = "get_profitability"
    hardware: str | None = Field(None, min_length=1, max_length=200, description="Hardware slug for preset mode.")
    hashrate: float | None = Field(None, gt=0, description="Manual hashrate in H/s; supply algorithm as well.")
    algorithm: str | None = Field(None, min_length=1, max_length=200, description="Algorithm slug for manual mode.")
    power: float | None = Field(None, ge=0, description="Manual power draw in watts.")
    quantity: int = Field(1, ge=1)
    electricity: float = Field(0.10, ge=0, description="Electricity price in USD/kWh.")
    poolFee: float | None = Field(None, ge=0, le=0.2, title="Pool Fee", description="Fee fraction, for example 0.01 for 1%.")
    verifiedOnly: StrictBool | None = Field(None, title="Verified Only")
    limit: int = Field(25, ge=1, le=100)
    window: Literal["current", "6h", "24h", "3d"] = "current"

    @model_validator(mode="after")
    def mode(self):
        if self.hardware is None and (self.hashrate is None or self.algorithm is None):
            raise ValueError("Supply a hardware slug or both manual hashrate and algorithm")
        if self.hardware is not None and any(v is not None for v in (self.hashrate, self.algorithm, self.power)):
            raise ValueError("Choose either hardware preset or manual hashrate mode")
        return self


Operation = Annotated[Union[ListCoins, GetCoin, GetCoinHistory, ListHardware, GetHardware,
                            ListAlgorithms, GetAlgorithm, ListPools, GetPool, GetProfitability],
                      Field(discriminator="operation")]


class MinerstatConfig(NodeConfig[Operation, MinerstatAPIKeyCredential]):
    pass


ROUTES = {
    "list_coins": "/v3/coins", "get_coin": "/v3/coins/{slug}",
    "get_coin_history": "/v3/coins/{slug}/history",
    "list_hardware": "/v3/hardware", "get_hardware": "/v3/hardware/{slug}",
    "list_algorithms": "/v3/algorithms", "get_algorithm": "/v3/algorithms/{slug}",
    "list_pools": "/v3/pools", "get_pool": "/v3/pools/{slug}",
    "get_profitability": "/v3/profitability",
}
DETAILS = {"get_coin": "coin", "get_hardware": "hardware", "get_algorithm": "algorithm", "get_pool": "pool"}


class MinerstatNode(WorkflowNode):
    integration_type = "automation-minerstat"
    connection_evidence = ConnectionEvidence(operation="list_coins", noun="mining data", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return MinerstatConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Minerstat API key")
        config = self.config.config
        key = self.config.credentials.api_key
        route = ROUTES[config.operation]
        if "{slug}" in route:
            route = route.replace("{slug}", quote(config.slug, safe=""))
        params = config.model_dump(exclude={"operation", "slug"}, exclude_none=True)
        params = {name: str(value).lower() if isinstance(value, bool) else value for name, value in params.items()}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request("GET", "https://api.minerstat.com" + route,
                                                params=params, headers={"X-Api-Key": key, "Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Minerstat could not be reached") from None
        # Retain provider rejection text for connection evidence, but never echo a key.
        if response.status_code != 200:
            message = "Minerstat returned HTTP " + str(response.status_code)
            try:
                error = response.json().get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:1000].replace(key, "[redacted]")
            except (ValueError, AttributeError):
                pass
            return {"status": "error", "http_status": response.status_code, "error": message}
        if len(response.content) > 10_000_000 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected bounded Minerstat JSON")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Minerstat returned invalid JSON") from None
        if not isinstance(body, dict) or "error" in body:
            raise ValueError("Minerstat returned an unexpected response envelope")
        detail = DETAILS.get(config.operation)
        if detail:
            if not isinstance(body.get(detail), dict) or body[detail].get("slug") != config.slug:
                raise ValueError("Minerstat returned a different or missing resource")
        elif not isinstance(body.get("results"), list) or any(not isinstance(row, dict) for row in body["results"]):
            raise ValueError("Minerstat returned an invalid result list")
        if config.operation == "get_coin_history" and body.get("coin") != config.slug:
            raise ValueError("Minerstat returned history for a different coin")
        return {"status": "success", "operation": config.operation, "data": body}
