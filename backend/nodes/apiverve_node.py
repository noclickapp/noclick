"""Apiverve validation, lookup and generation APIs.

Each operation calls one documented endpoint using a manually supplied API key.
Current provider docs correct missing parameters and methods in the pinned spec.
"""
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class ApiverveAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Apiverve API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dashboard.apiverve.com",
            "x-credential-instructions": "Paste your Apiverve API key from the dashboard. The connection check reads the USD currency symbol and confirms key acceptance, not account identity. Calls consume provider credits."})
    credential_type: Literal["apiverve_api_key"] = Field("apiverve_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value)

class ApiverveValidateEmailConfig(BaseModel):
    """Validate email. Provider reference: https://docs.apiverve.com/ref/emailvalidator."""
    operation: Literal["validate_email"] = Field("validate_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)


class ApiverveCheckDisposableEmailConfig(BaseModel):
    """Check disposable email. Provider reference: https://docs.apiverve.com/ref/emaildisposablechecker."""
    operation: Literal["check_disposable_email"] = Field("check_disposable_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)


class ApiverveValidatePhoneConfig(BaseModel):
    """Validate phone. Provider reference: https://docs.apiverve.com/ref/phonenumbervalidator."""
    operation: Literal["validate_phone"] = Field("validate_phone", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., min_length=1)
    country: str = Field(..., min_length=1)


class ApiverveLookupIpConfig(BaseModel):
    """Lookup ip. Provider reference: https://docs.apiverve.com/ref/iplookup."""
    operation: Literal["lookup_ip"] = Field("lookup_ip", json_schema_extra={"ui:hidden": True})
    ip: str = Field(..., min_length=1)


class ApiverveCheckDomainAvailabilityConfig(BaseModel):
    """Check domain availability. Provider reference: https://docs.apiverve.com/ref/domainavailability."""
    operation: Literal["check_domain_availability"] = Field("check_domain_availability", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=1)


class ApiverveGetDomainExpirationConfig(BaseModel):
    """Get domain expiration. Provider reference: https://docs.apiverve.com/ref/domainexpiration."""
    operation: Literal["get_domain_expiration"] = Field("get_domain_expiration", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=1)


class ApiverveConvertCurrencyConfig(BaseModel):
    """Convert currency. Provider reference: https://docs.apiverve.com/ref/currencyconverter."""
    operation: Literal["convert_currency"] = Field("convert_currency", json_schema_extra={"ui:hidden": True})
    value: float = Field(..., ge=0)
    from_currency: str = Field(..., min_length=1)
    to: str = Field(..., min_length=1)


class ApiverveGetWeatherConfig(BaseModel):
    """Get weather. Provider reference: https://docs.apiverve.com/ref/weatherforecast."""
    operation: Literal["get_weather"] = Field("get_weather", json_schema_extra={"ui:hidden": True})
    city: str = Field(..., min_length=1)


class ApiverveGenerateQrCodeConfig(BaseModel):
    """Generate qr code. Provider reference: https://docs.apiverve.com/ref/qrcodegenerator."""
    operation: Literal["generate_qr_code"] = Field("generate_qr_code", json_schema_extra={"ui:hidden": True})
    value: str = Field(..., min_length=1)


class ApiverveGeneratePdfConfig(BaseModel):
    """Generate pdf. Provider reference: https://docs.apiverve.com/ref/htmltopdf."""
    operation: Literal["generate_pdf"] = Field("generate_pdf", json_schema_extra={"ui:hidden": True})
    html: str = Field(..., min_length=1)


class ApiverveGenerateImageConfig(BaseModel):
    """Generate image. Provider reference: https://docs.apiverve.com/ref/htmltoimage."""
    operation: Literal["generate_image"] = Field("generate_image", json_schema_extra={"ui:hidden": True})
    html: str = Field(..., min_length=1)


class ApiverveCaptureScreenshotConfig(BaseModel):
    """Capture screenshot. Provider reference: https://docs.apiverve.com/ref/webscreenshots."""
    operation: Literal["capture_screenshot"] = Field("capture_screenshot", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1)


class ApiverveUnshortenUrlConfig(BaseModel):
    """Unshorten url. Provider reference: https://docs.apiverve.com/ref/urlunshortener."""
    operation: Literal["unshorten_url"] = Field("unshorten_url", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1)


class ApiverveConvertMarkdownConfig(BaseModel):
    """Convert markdown. Provider reference: https://docs.apiverve.com/ref/markdowntohtml."""
    operation: Literal["convert_markdown"] = Field("convert_markdown", json_schema_extra={"ui:hidden": True})
    markdown: str = Field(..., min_length=1)


class ApiverveListCurrencySymbolsConfig(BaseModel):
    """List currency symbols. Provider reference: https://docs.apiverve.com/ref/currencysymbols."""
    operation: Literal["list_currency_symbols"] = Field("list_currency_symbols", json_schema_extra={"ui:hidden": True})
    currency: str = Field("USD")


ApiverveConfig = Annotated[Union[ApiverveValidateEmailConfig, ApiverveCheckDisposableEmailConfig, ApiverveValidatePhoneConfig, ApiverveLookupIpConfig, ApiverveCheckDomainAvailabilityConfig, ApiverveGetDomainExpirationConfig, ApiverveConvertCurrencyConfig, ApiverveGetWeatherConfig, ApiverveGenerateQrCodeConfig, ApiverveGeneratePdfConfig, ApiverveGenerateImageConfig, ApiverveCaptureScreenshotConfig, ApiverveUnshortenUrlConfig, ApiverveConvertMarkdownConfig, ApiverveListCurrencySymbolsConfig], Field(discriminator="operation")]

class ApiverveFullConfig(NodeConfig[ApiverveConfig, ApiverveAPIKeyCredential]):
    pass

ROUTES = {'validate_email': ('GET', 'emailvalidator'), 'check_disposable_email': ('GET', 'emaildisposablechecker'), 'validate_phone': ('GET', 'phonenumbervalidator'), 'lookup_ip': ('GET', 'iplookup'), 'check_domain_availability': ('GET', 'domainavailability'), 'get_domain_expiration': ('GET', 'domainexpiration'), 'convert_currency': ('GET', 'currencyconverter'), 'get_weather': ('GET', 'weatherforecast'), 'generate_qr_code': ('POST', 'qrcodegenerator'), 'generate_pdf': ('POST', 'htmltopdf'), 'generate_image': ('POST', 'htmltoimage'), 'capture_screenshot': ('POST', 'webscreenshots'), 'unshorten_url': ('POST', 'urlunshortener'), 'convert_markdown': ('POST', 'markdowntohtml'), 'list_currency_symbols': ('GET', 'currencysymbols')}

class ApiverveNode(WorkflowNode):
    integration_type = "automation-apiverve"
    connection_evidence = ConnectionEvidence(operation="list_currency_symbols", noun="Apiverve key acceptance", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return ApiverveFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Apiverve API key")
        config = self.config.config
        method, endpoint = ROUTES[config.operation]
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        if "from_currency" in params:
            params["from"] = params.pop("from_currency")
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.apiverve.com/v1/" + endpoint,
                headers={"x-api-key": self.config.credentials.api_key, "Accept": "application/json"},
                **({"json": params} if method == "POST" else {"params": params}))
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("status") != "ok" or body.get("error"):
            message = body.get("error") if isinstance(body, dict) else None
            return {"status": "error", "error": message or "Apiverve did not confirm the request"}
        if "data" not in body:
            raise ValueError("Apiverve response is missing data")
        return {"status": "success", "data": body["data"]}
