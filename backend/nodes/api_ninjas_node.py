"""API Ninjas enrichment and computation APIs, one request per operation.

Contract: https://api-ninjas.com/openapi.json (1.0.0).
The provider exposes shared data; a successful probe proves key acceptance only.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.api-ninjas.com"


class ApiNinjasApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="API Ninjas API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://api-ninjas.com/profile",
        "x-credential-instructions": "Copy your API key from your API Ninjas account. NoClick sends it in X-Api-Key to api.api-ninjas.com. Plan limits apply; commercial use requires a premium subscription. Connection testing proves the key is accepted, not account identity.",
    })
    credential_type: Literal["api_ninjas_api_key"] = Field("api_ninjas_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste an API key without whitespace or control characters")
        return value


class OperationBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True, allow_inf_nan=False)


class ValidateEmail(OperationBase):
    operation: Literal["validate_email"] = Field("validate_email", title="Validate Email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, max_length=320, title="Email Address")


class ValidatePhone(OperationBase):
    operation: Literal["validate_phone"] = Field("validate_phone", title="Validate Phone", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., min_length=1, max_length=100, title="Phone Number", description="Include the country calling code if no country is supplied.")
    country: str | None = Field(None, min_length=2, max_length=2, title="Country Code", description="Two-letter ISO country code.")


class Geocode(OperationBase):
    operation: Literal["geocode"] = Field("geocode", title="Geocode City", json_schema_extra={"ui:hidden": True})
    city: str = Field(..., min_length=1, max_length=250, title="City")
    state: str | None = Field(None, max_length=250, title="US State")
    country: str | None = Field(None, max_length=250, title="Country")
    zipcode: str | None = Field(None, pattern=r"^[0-9]{5}$", title="US ZIP Code")


class Coordinates(OperationBase):
    lat: float = Field(..., ge=-90, le=90, title="Latitude")
    lon: float = Field(..., ge=-180, le=180, title="Longitude")


class ReverseGeocode(Coordinates):
    operation: Literal["reverse_geocode"] = Field("reverse_geocode", title="Reverse Geocode Coordinates", json_schema_extra={"ui:hidden": True})


class GetWeather(Coordinates):
    operation: Literal["get_weather"] = Field("get_weather", title="Get Current Weather", json_schema_extra={"ui:hidden": True})


class ConvertCurrency(OperationBase):
    operation: Literal["convert_currency"] = Field("convert_currency", title="Convert Currency", json_schema_extra={"ui:hidden": True})
    have: str = Field(..., pattern=r"^[A-Z]{3}$", title="From Currency", description="ISO currency code, such as GBP.")
    want: str = Field(..., pattern=r"^[A-Z]{3}$", title="To Currency", description="ISO currency code, such as AUD.")
    amount: float = Field(..., title="Amount")


class GetExchangeRate(OperationBase):
    operation: Literal["get_exchange_rate"] = Field("get_exchange_rate", title="Get Exchange Rate", json_schema_extra={"ui:hidden": True})
    pair: str = Field(..., pattern=r"^[A-Z]{3}_[A-Z]{3}$", title="Currency Pair", description="For example GBP_AUD. Free plans receive daily rates.")


class GetStockPrice(OperationBase):
    operation: Literal["get_stock_price"] = Field("get_stock_price", title="Get Stock Price", json_schema_extra={"ui:hidden": True})
    ticker: str = Field(..., min_length=1, max_length=100, title="Ticker", description="For example AAPL or ^DJI. Free plans receive the latest session closing price.")


class GetNutrition(OperationBase):
    operation: Literal["get_nutrition"] = Field("get_nutrition", title="Get Nutrition from Text", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=10000, title="Food Description", description="For example 1lb brisket and fries. Some nutrients require a premium plan.")


class AnalyzeSentiment(OperationBase):
    operation: Literal["analyze_sentiment"] = Field("analyze_sentiment", title="Analyze Sentiment", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1, max_length=2000, title="Text")


class DetectLanguage(OperationBase):
    operation: Literal["detect_language"] = Field("detect_language", title="Detect Text Language", json_schema_extra={"ui:hidden": True})
    text: str = Field(..., min_length=1, max_length=1000, title="Text", description="At least ten words recommended.")


class CompareText(OperationBase):
    operation: Literal["compare_text"] = Field("compare_text", title="Compare Text Similarity", description="Posts two texts for a similarity calculation; creates no stored resource.", json_schema_extra={"ui:hidden": True})
    text_1: str = Field(..., min_length=1, max_length=5000, title="First Text")
    text_2: str = Field(..., min_length=1, max_length=5000, title="Second Text")


class GeneratePassword(OperationBase):
    operation: Literal["generate_password"] = Field("generate_password", title="Generate Random Password", json_schema_extra={"ui:hidden": True})
    length: int = Field(16, ge=1, le=1024, title="Length")
    exclude_numbers: bool | None = Field(None, title="Exclude Numbers", description="Premium plan only.")
    exclude_special_chars: bool | None = Field(None, title="Exclude Special Characters", description="Premium plan only.")


class LookupIP(OperationBase):
    operation: Literal["lookup_ip"] = Field("lookup_ip", title="Look Up IP Address", json_schema_extra={"ui:hidden": True})
    address: str = Field(..., min_length=1, max_length=100, title="IP Address", description="IPv4 or IPv6 address to look up.")


class GetWorldTime(OperationBase):
    operation: Literal["get_world_time"] = Field("get_world_time", title="Get World Time", json_schema_extra={"ui:hidden": True})
    timezone: str = Field("Europe/London", max_length=100, title="Timezone", description="IANA timezone name. Defaults to Europe/London; change for another location.")


Operation = Annotated[Union[ValidateEmail, ValidatePhone, Geocode, ReverseGeocode, GetWeather, ConvertCurrency, GetExchangeRate, GetStockPrice, GetNutrition, AnalyzeSentiment, DetectLanguage, CompareText, GeneratePassword, LookupIP, GetWorldTime], Field(discriminator="operation")]


class ApiNinjasNodeConfig(NodeConfig[Operation, ApiNinjasApiKeyCredential]):
    pass


ROUTES = {
    "validate_email": ("GET", "/v1/validateemail"),
    "validate_phone": ("GET", "/v1/validatephone"),
    "geocode": ("GET", "/v1/geocoding"),
    "reverse_geocode": ("GET", "/v1/reversegeocoding"),
    "get_weather": ("GET", "/v1/weather"),
    "convert_currency": ("GET", "/v1/convertcurrency"),
    "get_exchange_rate": ("GET", "/v1/exchangerate"),
    "get_stock_price": ("GET", "/v1/stockprice"),
    "get_nutrition": ("GET", "/v1/nutrition"),
    "analyze_sentiment": ("GET", "/v1/sentiment"),
    "detect_language": ("GET", "/v1/textlanguage"),
    "compare_text": ("POST", "/v1/textsimilarity"),
    "generate_password": ("GET", "/v1/passwordgenerator"),
    "lookup_ip": ("GET", "/v1/iplookup"),
    "get_world_time": ("GET", "/v1/worldtime"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class ApiNinjasNode(WorkflowNode):
    integration_type = "automation-api-ninjas"
    connection_evidence = ConnectionEvidence(noun="API key", operation="get_world_time", label_keys=("timezone",), proves="reachability")
    edit_examples = ["Validate this email address", "Convert GBP to AUD", "Compare these two texts"]

    @classmethod
    def get_config_model(cls):
        return ApiNinjasNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an API Ninjas API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        fields = op.model_dump(exclude={"operation"}, exclude_none=True)
        if isinstance(op, GetWeather):
            fields = {k: str(v) for k, v in fields.items()}
        kwargs = {"json": fields} if method == "POST" else {"params": fields}
        try:
            async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(30)) as client:
                async with client.stream(method, BASE + path, headers={"X-Api-Key": secret, "Accept": "application/json"}, **kwargs) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2 * 1024 * 1024:
                            raise ValueError("API Ninjas response exceeds 2 MiB")
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ValueError("API Ninjas returned an invalid JSON response") from None
                    if not 200 <= response.status_code < 300 or isinstance(payload, dict) and "error" in payload:
                        message = payload.get("error") if isinstance(payload, dict) else None
                        output = {"status": "error", "success": False, "http_status": response.status_code,
                                  "error": message if isinstance(message, str) else "API Ninjas rejected the request"}
                    else:
                        array = isinstance(op, (Geocode, ReverseGeocode, GetNutrition))
                        if not isinstance(payload, list if array else dict) or array and any(not isinstance(row, dict) for row in payload):
                            raise ValueError("API Ninjas returned an unexpected response shape")
                        output = {"status": "success", "success": True, "data": payload}
        except httpx.HTTPError:
            raise ValueError("API Ninjas request could not be completed") from None
        output = _redact(output, secret)
        await self.emit(output)
        return output
