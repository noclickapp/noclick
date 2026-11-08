"""Corrently v2 energy data and secret-protected meter updates.

Contract: https://api.apis.guru/v2/specs/corrently.io/2.0.0/openapi.json
Public reads do not authenticate the meter update secret.
"""
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://api.corrently.io/v2.0"

class CorrentlyMeterCredential(BaseModel):
    model_config = ConfigDict(title="Corrently Meter Secret", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://corrently.io/",
        "x-credential-instructions": "Enter your existing Stromkonto meter account and the secret chosen on its first reading update. Public reads only establish reachability; they cannot verify the secret or account ownership. The secret is sent only in the JSON body of meter updates."})
    credential_type: Literal["corrently_meter_secret"] = Field("corrently_meter_secret", json_schema_extra={"ui:hidden": True})
    account: str = Field(..., min_length=1, title="Meter account", description="Existing Stromkonto meter address.")
    secret: str = Field(..., min_length=1, title="Meter secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("secret", mode="before")
    @classmethod
    def secret_value(cls, value):
        return clean_secret(value, field_name="Meter secret")

    @field_validator("account")
    @classmethod
    def account_value(cls, value):
        value = value.strip()
        if not value or any(ord(ch) < 32 for ch in value):
            raise ValueError("Enter a Stromkonto meter account")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GetBalances(_Input):
    """Balances"""
    operation: Literal["get_balances"] = Field("get_balances", json_schema_extra={"ui:hidden": True})

class GetMeterReading(_Input):
    """Meter Reading"""
    operation: Literal["get_meter_reading"] = Field("get_meter_reading", json_schema_extra={"ui:hidden": True})

class PostMeterReading(_Input):
    """Meter Reading"""
    operation: Literal["post_meter_reading"] = Field("post_meter_reading", json_schema_extra={"ui:hidden": True})
    energy: int = Field(..., ge=0, description="Cumulative meter reading in Wh (documented energy alias for 1.8.0).")
    zip: str = Field(..., min_length=1, description="German postcode of the metered location.")

class GetPrediction(_Input):
    """Prediction"""
    operation: Literal["get_prediction"] = Field("get_prediction", json_schema_extra={"ui:hidden": True})
    zip: str | None = Field(None, description='Zipcode (Postleitzahl) of a city in Germany.')
    key: str | None = Field(None, description='Any valid Stromkonto account (address).')

class GetDispatch(_Input):
    """Dispatch (Green Energy Distribution Schedule)"""
    operation: Literal["get_dispatch"] = Field("get_dispatch", json_schema_extra={"ui:hidden": True})
    zip: str | None = Field(None, description='Zipcode (Postleitzahl) of a city in Germany.')
    key: str | None = Field(None, description='Any valid Stromkonto account (address).')

class GetMarketData(_Input):
    """Marketdata"""
    operation: Literal["get_market_data"] = Field("get_market_data", json_schema_extra={"ui:hidden": True})
    zip: str | None = Field(None, description='Zipcode (Postleitzahl) of a city in Germany.')

class GetBestHour(_Input):
    """Get best hour (with most regional green energy) in a given timeframe."""
    operation: Literal["get_best_hour"] = Field("get_best_hour", json_schema_extra={"ui:hidden": True})
    zip: str | None = Field(None, description='Zipcode (Postleitzahl) of a city in Germany.')
    key: str | None = Field(None, description='Any valid Stromkonto account (address).')
    timeframe: int | None = Field(None, description='Number of hours to check (default 24 hours from now).')
    hours: int | None = Field(None, description='How many hours in row do you need the device turned on?')

class GetTariff(_Input):
    """Energy Tariff information"""
    operation: Literal["get_tariff"] = Field("get_tariff", json_schema_extra={"ui:hidden": True})
    zipcode: str | None = Field(None, description='Zipcode (Postzleitzahl) of a city in Germany.')

class GetTariffComponents(_Input):
    """Energy Tariff price components"""
    operation: Literal["get_tariff_components"] = Field("get_tariff_components", json_schema_extra={"ui:hidden": True})
    zipcode: str | None = Field(None, description='Zipcode (Postzleitzahl) of a city in Germany.')
    email: str | None = Field(None, description='Valid email address to assign request to (pre offer generation). Ensure GDPR (DSGVO) at any time')
    kwha: int | None = Field(None, description='Total amount of energy in kilo-watt-hours per year. (sample 2100)')
    milliseconds: int | None = Field(None, description='If provided all results will be scaled to this timeframe')
    wh: int | None = Field(None, description='If provided together with milliseconds, a cost component stament for a particular event (like charging a car) will be created.')

class ListOpenMeters(_Input):
    """Public shared smart meters installed in Germany and available for subservices and exploration."""
    operation: Literal["list_open_meters"] = Field("list_open_meters", json_schema_extra={"ui:hidden": True})

class ListOpenMeterReadings(_Input):
    """Public shared smart meters installed in Germany and available for subservices and exploration."""
    operation: Literal["list_open_meter_readings"] = Field("list_open_meter_readings", json_schema_extra={"ui:hidden": True})

class ListOpenMeterActivities(_Input):
    """Public shared smart meters installed in Germany and available for subservices and exploration."""
    operation: Literal["list_open_meter_activities"] = Field("list_open_meter_activities", json_schema_extra={"ui:hidden": True})

CorrentlyConfig = Annotated[Union[GetBalances, GetMeterReading, PostMeterReading, GetPrediction, GetDispatch, GetMarketData, GetBestHour, GetTariff, GetTariffComponents, ListOpenMeters, ListOpenMeterReadings, ListOpenMeterActivities], Field(discriminator="operation")]

class CorrentlyNodeConfig(NodeConfig[CorrentlyConfig, CorrentlyMeterCredential]):
    pass

ROUTES = {'get_balances': ('GET', '/stromkonto/balances'), 'get_meter_reading': ('GET', '/metering/reading'), 'post_meter_reading': ('POST', '/metering/reading'), 'get_prediction': ('GET', '/gsi/prediction'), 'get_dispatch': ('GET', '/gsi/dispatch'), 'get_market_data': ('GET', '/gsi/marketdata'), 'get_best_hour': ('GET', '/gsi/bestHour'), 'get_tariff': ('GET', '/tariff/slph0'), 'get_tariff_components': ('GET', '/tariff/components'), 'list_open_meters': ('GET', '/alternative/openmeter/meters'), 'list_open_meter_readings': ('GET', '/alternative/openmeter/readings'), 'list_open_meter_activities': ('GET', '/alternative/openmeter/activities')}

class CorrentlyNode(WorkflowNode):
    integration_type = "automation-corrently"
    connection_evidence = ConnectionEvidence(operation="get_balances", noun="public Stromkonto balances", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return CorrentlyNodeConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Corrently meter account and secret")
        method, path = ROUTES[config.operation]
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        body = None
        if config.operation == "post_meter_reading":
            body = {**params, "account": credential.account, "secret": credential.secret}
            params = {}
        elif config.operation in {"get_balances", "get_meter_reading"}:
            params["account"] = credential.account
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body, headers={"Accept": "application/json"})
            if not 200 <= response.status_code < 300:
                return {"status": "error", "http_status": response.status_code, "error": "Corrently request failed"}
            data = response.json()
            if isinstance(data, dict) and (data.get("error") or data.get("success") is False):
                return {"status": "error", "error": "Corrently did not confirm the request"}
            # A provider response must never expose the update secret.
            def redact(value):
                if isinstance(value, dict):
                    return {k: redact(v) for k, v in value.items() if k != "secret"}
                if isinstance(value, list):
                    return [redact(v) for v in value]
                if isinstance(value, str):
                    return value.replace(credential.secret, "[redacted]")
                return value
            result = {"status": "success", "data": redact(data)}
            await self.emit(result)
            return result
        except (httpx.HTTPError, ValueError, SSRFError):
            return {"status": "error", "error": "Corrently response could not be confirmed"}
