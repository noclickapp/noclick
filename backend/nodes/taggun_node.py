"""Taggun receipt OCR, validation and account training operations.

Each operation maps to one endpoint in the provider's published 1.16.220 contract.
API keys are pasted by the user; connection evidence reads their campaign IDs.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.taggun.io"
DOCS_URL = "https://api.taggun.io/docs/swagger.json"


class TaggunAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Taggun API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.taggun.io/",
            "x-credential-instructions": "Paste your Taggun API key. NoClick sends it in the apikey header to api.taggun.io. Connection verification reads your campaign setting IDs without scanning or changing receipts.",
        })
    credential_type: Literal["taggun_api_key"] = Field("taggun_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key",
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste your API key without a header prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _ReceiptContext(_Config):
    incognito: bool | None = Field(None, description="Avoid saving the receipt in Taggun storage.")
    ipAddress: str | None = Field(None, title="End user IP address")
    near: str | None = Field(None, description="Merchant location hint, e.g. Kalamazoo, MI, USA.")
    referenceId: str | None = Field(None, max_length=50, title="Reference ID")
    userId: str | None = Field(None, max_length=50, title="User ID")
    subAccountId: str | None = Field(None, max_length=100, title="Sub-account ID")
    language: Literal["en", "es", "fr", "jp", "he", "iw", "et", "lv", "lt", "fi", "el", "zh", "th", "ar", "kh"] | None = None


class _OCR(_ReceiptContext):
    refresh: bool | None = Field(None, description="Force reprocessing of an already stored receipt.")
    ignoreMerchantName: str | None = Field(None, title="Ignore merchant name")
    extractTime: bool | None = Field(None, title="Extract receipt time")
    containerId: str | None = Field(None, max_length=50, title="Container ID")


class _URL(_Config):
    url: str = Field(..., min_length=1, title="Receipt URL", description="HTTPS URL of a PDF, JPG, PNG, GIF or HEIC receipt. Taggun fetches this URL.")
    headers: dict[str, str] | None = Field(None, description="Optional HTTP headers Taggun forwards to the receipt URL.")

    @field_validator("url")
    @classmethod
    def https_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
            raise ValueError("Use an HTTPS receipt URL without embedded credentials")
        return value


class _Encoded(_Config):
    image: str = Field(..., min_length=1, title="Encoded receipt", description="Base64 image bytes without a data URL prefix.")
    filename: str = Field(..., min_length=1, title="File name")
    contentType: Literal["image/jpeg", "image/png", "image/gif", "image/heic", "application/pdf"] = Field(..., title="Content type")

    @field_validator("image")
    @classmethod
    def encoded_image(cls, value):
        try:
            if not base64.b64decode(value, validate=True):
                raise ValueError("Receipt is empty")
        except (binascii.Error, ValueError):
            raise ValueError("Use base64 image bytes without a data URL prefix") from None
        return value


class ScanSimpleURL(_URL, _OCR):
    """Extract receipt totals, date and merchant from a URL."""
    operation: Literal["scan_simple_url"] = "scan_simple_url"


class ScanVerboseURL(_URL, _OCR):
    """Extract detailed receipt entities and optional line items from a URL."""
    operation: Literal["scan_verbose_url"] = "scan_verbose_url"
    extractLineItems: bool | None = Field(None, title="Extract line items")


class ScanSimpleEncoded(_Encoded, _OCR):
    """Extract receipt totals, date and merchant from encoded image bytes."""
    operation: Literal["scan_simple_encoded"] = "scan_simple_encoded"


class ScanVerboseEncoded(_Encoded, _OCR):
    """Extract detailed receipt entities from encoded image bytes."""
    operation: Literal["scan_verbose_encoded"] = "scan_verbose_encoded"
    extractLineItems: bool | None = Field(None, title="Extract line items")


class ValidateReceiptURL(_URL, _ReceiptContext):
    """Validate a receipt against supplied validation rules."""
    operation: Literal["validate_receipt_url"] = "validate_receipt_url"
    validation: dict[str, Any] = Field(..., title="Validation rules", description="Taggun receiptValidationRules object: date, merchantName, merchantAddress, productCodes, serialNumber, balanceOwing, productLineItems, fraudDetection or smartValidate. See the provider contract.")
    additionalExtractionFields: list[Literal["modelNumber"]] | None = Field(None, title="Additional extraction fields")
    containerId: str | None = Field(None, max_length=50, title="Container ID")


class _Campaign(_Config):
    campaignId: str = Field(..., min_length=1, max_length=50, title="Campaign ID")

    @field_validator("campaignId")
    @classmethod
    def campaign_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a campaign ID without controls or dot path segments")
        return value


class ValidateCampaignURL(_URL, _ReceiptContext, _Campaign):
    """Validate a receipt against a saved campaign's rules."""
    operation: Literal["validate_campaign_url"] = "validate_campaign_url"


class ListCampaignSettings(_Config):
    """List campaign setting IDs belonging to this API key."""
    operation: Literal["list_campaign_settings"] = "list_campaign_settings"


class GetCampaignSettings(_Campaign):
    """Read the validation settings of one campaign."""
    operation: Literal["get_campaign_settings"] = "get_campaign_settings"


class _CampaignDateRange(_Config):
    start: str = Field(..., min_length=1, description="Start date, e.g. 2023-04-01T00:00:00.000Z.")
    end: str = Field(..., min_length=1, description="End date, e.g. 2023-04-01T00:00:00.000Z.")


class _CampaignBalanceOwing(_Config):
    max: float = Field(..., allow_inf_nan=False, title="Maximum balance owing")
    skip: bool | None = None


class _CampaignSettings(_Campaign):
    date: _CampaignDateRange | None = Field(None, description="Campaign date validation settings.")
    merchantNames: dict[str, Any] | None = Field(None, title="Merchant names")
    productCodes: dict[str, Any] | None = Field(None, title="Product codes")
    balanceOwing: _CampaignBalanceOwing | None = Field(None, title="Balance owing")
    productLineItems: dict[str, Any] | None = Field(None, title="Product line items")
    fraudDetection: dict[str, Any] | None = Field(None, title="Fraud detection")
    smartValidate: dict[str, Any] | None = Field(None, title="Smart validation")


class CreateCampaignSettings(_CampaignSettings):
    """Create validation settings for a campaign ID."""
    operation: Literal["create_campaign_settings"] = "create_campaign_settings"


class UpdateCampaignSettings(_CampaignSettings):
    """Update the validation settings for a campaign ID."""
    operation: Literal["update_campaign_settings"] = "update_campaign_settings"


class DeleteCampaignSettings(_Campaign):
    """Delete the saved validation settings for a campaign ID."""
    operation: Literal["delete_campaign_settings"] = "delete_campaign_settings"


class AddReceiptFeedback(_Config):
    """Submit manually verified receipt values for feedback and training."""
    operation: Literal["add_receipt_feedback"] = "add_receipt_feedback"
    referenceId: str = Field(..., min_length=1, title="Receipt reference ID")
    totalAmount: float | None = Field(None, title="Total amount", allow_inf_nan=False)
    taxAmount: float | None = Field(None, title="Tax amount", allow_inf_nan=False)
    merchantName: str | None = Field(None, title="Merchant name")
    currencyCode: str | None = Field(None, title="Currency code")
    date: str | None = Field(None, description="ISO 8601 date-time, e.g. 2016-12-22T12:00:00.000Z.", json_schema_extra={"format": "date-time"})
    masterCategory: str | None = Field(None, title="Master category")


    @field_validator("date")
    @classmethod
    def receipt_date(cls, value):
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO 8601 date-time including a timezone") from None
        return value


class AddMerchantName(_Config):
    """Add a merchant keyword to the account's model, updated daily by Taggun."""
    operation: Literal["add_merchant_name"] = "add_merchant_name"
    merchantName: str = Field(..., min_length=1, title="Merchant name")


TaggunConfig = Annotated[Union[
    ScanSimpleURL, ScanVerboseURL, ScanSimpleEncoded, ScanVerboseEncoded,
    ValidateReceiptURL, ValidateCampaignURL, ListCampaignSettings, GetCampaignSettings,
    CreateCampaignSettings, UpdateCampaignSettings, DeleteCampaignSettings,
    AddReceiptFeedback, AddMerchantName,
], Field(discriminator="operation")]


class TaggunNodeConfig(NodeConfig[TaggunConfig, TaggunAPIKeyCredential]):
    pass


# One request per operation; no hidden scans, mutations, pagination or readbacks.
ROUTES = {
    "scan_simple_url": ("POST", "/api/receipt/v1/simple/url"),
    "scan_verbose_url": ("POST", "/api/receipt/v1/verbose/url"),
    "scan_simple_encoded": ("POST", "/api/receipt/v1/simple/encoded"),
    "scan_verbose_encoded": ("POST", "/api/receipt/v1/verbose/encoded"),
    "validate_receipt_url": ("POST", "/api/validation/v1/receipt-validation/url"),
    "validate_campaign_url": ("POST", "/api/validation/v1/campaign/receipt-validation/url"),
    "list_campaign_settings": ("GET", "/api/validation/v1/campaign/settings/list"),
    "get_campaign_settings": ("GET", "/api/validation/v1/campaign/settings/{campaignId}"),
    "create_campaign_settings": ("POST", "/api/validation/v1/campaign/settings/create/{campaignId}"),
    "update_campaign_settings": ("PUT", "/api/validation/v1/campaign/settings/update/{campaignId}"),
    "delete_campaign_settings": ("DELETE", "/api/validation/v1/campaign/settings/delete/{campaignId}"),
    "add_receipt_feedback": ("POST", "/api/account/v1/feedback"),
    "add_merchant_name": ("POST", "/api/account/v1/merchantname/add"),
}


class TaggunNode(WorkflowNode):
    integration_type = "automation-taggun"
    connection_evidence = ConnectionEvidence(noun="Taggun campaign settings", operation="list_campaign_settings")

    @classmethod
    def get_config_model(cls):
        return TaggunNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your Taggun API key")
        credential = self.config.credentials
        config = self.config.config
        method, path = ROUTES[config.operation]
        body = config.model_dump(exclude={"operation"}, exclude_none=True)
        if "{campaignId}" in path:
            path = path.replace("{campaignId}", quote(body.pop("campaignId"), safe=""))
        async with guarded_async_client(timeout=90, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"apikey": credential.api_key, "Accept": "application/json"},
                **({"json": body} if method in {"POST", "PUT"} else {}))
        if not 200 <= response.status_code < 300:
            message = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(f"Taggun HTTP {response.status_code}: {message}")
        if not response.content:
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Taggun returned an unexpected non-JSON response") from None
        return {"status": "success", "data": data, "http_status": response.status_code}
