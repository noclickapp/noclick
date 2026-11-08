"""Beach Day API v1: all nine published read endpoints.

Contract: https://beachdayapi.com/openapi.json (1.0.0).
The API has no published mutation or account-identity endpoint.
"""
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://beachdayapi.com/v1"

class BeachDayApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Beach Day API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://beachdayapi.com/dashboard/api-keys/",
        "x-credential-instructions": "Paste your API key from the Beach Day API dashboard. Requests use Bearer authentication. Connection testing reads the shared country catalogue and proves key acceptance, not account identity. API calls may consume prepaid credits.",
    })
    credential_type: Literal["beach_day_api_key"] = Field("beach_day_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GetHealthConfig(_Input):
    """Health check."""
    operation: Literal["get_health"] = Field("get_health", json_schema_extra={"ui:hidden": True})

class ListBeachesConfig(_Input):
    """List beaches."""
    operation: Literal["list_beaches"] = Field("list_beaches", json_schema_extra={"ui:hidden": True})
    state: str | None = Field(None, description='Filter by state code, for example CA, FL, HI, or AU-NSW.')
    country: str | None = Field(None, description="Filter by country name (e.g., 'Croatia', 'Greece', 'Thailand', 'French Polynesia', 'New Caledonia', 'Fiji', 'Samoa', 'Tonga', 'New Zealand'). Case-insensitive.")
    search: str | None = Field(None, description="Search beaches by name (case-insensitive, e.g. 'Malibu').")
    offset: int = Field(0, ge=0, description='Number of results to skip (default: 0).')
    limit: int = Field(100, ge=1, le=500, description='Max results per page (default: 100, max: 500).')

class GetBeachDetailConfig(_Input):
    """Get beach detail."""
    operation: Literal["get_beach_detail"] = Field("get_beach_detail", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='Beach ID.')

class ListBeachConditionsConfig(_Input):
    """List beach conditions."""
    operation: Literal["list_beach_conditions"] = Field("list_beach_conditions", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='Beach ID.')
    offset: int = Field(0, ge=0, description='Number of results to skip (default: 0).')
    limit: int = Field(30, ge=1, le=200, description='Max results per page (default: 30, max: 200).')

class GetScoredBeachesConfig(_Input):
    """Get scored beaches."""
    operation: Literal["get_scored_beaches"] = Field("get_scored_beaches", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0, description='Number of results to skip (default: 0).')
    limit: int = Field(50, ge=1, le=200, description='Max results per page (default: 50, max: 200).')

class GetBeachRulesConfig(_Input):
    """Get beach rules."""
    operation: Literal["get_beach_rules"] = Field("get_beach_rules", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='id')

class GetBeachAmenitiesConfig(_Input):
    """Get beach amenities."""
    operation: Literal["get_beach_amenities"] = Field("get_beach_amenities", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='id')

class GetTidePredictionsConfig(_Input):
    """Get tide predictions."""
    operation: Literal["get_tide_predictions"] = Field("get_tide_predictions", json_schema_extra={"ui:hidden": True})
    beach_id: int = Field(..., ge=1, description='beach_id')

class ListCountriesConfig(_Input):
    """List available countries."""
    operation: Literal["list_countries"] = Field("list_countries", json_schema_extra={"ui:hidden": True})

BeachDayOperation = Annotated[Union[GetHealthConfig, ListBeachesConfig, GetBeachDetailConfig, ListBeachConditionsConfig, GetScoredBeachesConfig, GetBeachRulesConfig, GetBeachAmenitiesConfig, GetTidePredictionsConfig, ListCountriesConfig], Field(discriminator="operation")]

class BeachDayFullConfig(NodeConfig[BeachDayOperation, BeachDayApiKeyCredential]):
    pass

ROUTES = {'get_health': '/health/', 'list_beaches': '/beaches/', 'get_beach_detail': '/beaches/{id}/', 'list_beach_conditions': '/beaches/{id}/conditions/', 'get_scored_beaches': '/beaches/scored/', 'get_beach_rules': '/beaches/{id}/rules/', 'get_beach_amenities': '/beaches/{id}/amenities/', 'get_tide_predictions': '/tides/{beach_id}/', 'list_countries': '/countries/'}

class BeachDayApiNode(WorkflowNode):
    integration_type = "automation-beach-day-api"
    connection_evidence = ConnectionEvidence(operation="list_countries", noun="countries", proves="reachability", label_keys=("country",))

    @classmethod
    def get_config_model(cls):
        return BeachDayFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Beach Day API key")
        config = self.config.config
        path = ROUTES[config.operation]
        params = config.model_dump(exclude_none=True, exclude={"operation"})
        for name in ("id", "beach_id"):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", str(params.pop(name)))
        headers = {"Accept": "application/json"}
        # Health is explicitly unauthenticated in the provider's contract.
        if config.operation != "get_health":
            headers["Authorization"] = "Bearer " + credential.api_key
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", BASE_URL + path, params=params, headers=headers)
        except httpx.HTTPError:
            raise ValueError("Beach Day API request failed; retry later") from None
        if response.status_code != 200:
            message = "Beach Day API rejected the request"
            try:
                body = response.json()
                if isinstance(body, dict):
                    message = str(body.get("detail") or body.get("message") or body.get("error") or message)
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code,
                    "error": message.replace(credential.api_key, "[redacted]")[:1000]}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Beach Day API returned invalid JSON") from None
        if not isinstance(body, dict) or any(k in body for k in ("error", "detail")):
            raise ValueError("Beach Day API returned an unexpected response")
        # Preserve documented nullable fields and nested weather/ocean JSON.
        return {"status": "success", "data": body}
