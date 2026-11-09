"""TikTok API for Business v1.3: advertiser-scoped Smart+ ads and reporting.

Contract: https://github.com/tiktok/tiktok-business-api-sdk/tree/main/yml_files
Transport follows the publisher SDK: HTTPS v1.3 routes and Access-Token header.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://business-api.tiktok.com/open_api/v1.3"
ID = Annotated[str, Field(min_length=1, max_length=30, pattern=r"^[0-9]+$")]
Name = Annotated[str, Field(min_length=1, max_length=512)]
IDs = Annotated[list[ID], Field(min_length=1, max_length=100)]


class TikTokAdsAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="TikTok Ads Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://business-api.tiktok.com/portal/apps",
            "x-credential-instructions": "Paste an existing authorized TikTok API for Business access token from your developer app and the advertiser ID it can access. Your app needs permission for each API you use. NoClick sends the token in the Access-Token header to business-api.tiktok.com. This is separate from a TikTok video publishing token.",
        })
    credential_type: Literal["tiktok_ads_access_token"] = Field("tiktok_ads_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Access token", repr=False, json_schema_extra={"ui:widget": "password"})
    advertiser_id: ID = Field(..., title="Advertiser ID", description="The numeric TikTok Ads Manager account ID authorized for this token.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Advertiser(_Input):
    advertiser_id: ID | None = Field(None, title="Advertiser ID", description="Defaults to the connected advertiser. Override only with another account authorized for the same token.")


class _Page(_Advertiser):
    page: int = Field(1, ge=1, le=1000000)
    page_size: int = Field(100, ge=1, le=100)


class _Fields(_Page):
    fields: list[Name] | None = Field(None, max_length=100)


class CampaignFilter(_Input):
    campaign_ids: IDs | None = None
    campaign_name: Name | None = None
    primary_status: str | None = None


class AdgroupFilter(_Input):
    campaign_ids: IDs | None = None
    adgroup_ids: IDs | None = None
    adgroup_name: Name | None = None
    primary_status: str | None = None


class AdFilter(_Input):
    campaign_ids: IDs | None = None
    adgroup_ids: IDs | None = None
    smart_plus_ad_ids: IDs | None = None
    primary_status: str | None = None


class GetAdvertiserInfo(_Input):
    """Read the connected advertiser's account details."""
    operation: Literal["get_advertiser_info"] = Field("get_advertiser_info", json_schema_extra={"ui:hidden": True})
    fields: list[Name] | None = Field(None, max_length=100)


class ListCampaigns(_Fields):
    """Read one page of Smart+ campaigns; use page_info for continuation."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", title="List Smart+ Campaigns", json_schema_extra={"ui:hidden": True})
    filtering: CampaignFilter | None = None


class CreateCampaign(_Advertiser):
    """Create a Smart+ campaign. Enabling a campaign can spend the advertiser's budget."""
    operation: Literal["create_campaign"] = Field("create_campaign", title="Create Smart+ Campaign", json_schema_extra={"ui:hidden": True})
    campaign_name: Name
    objective_type: Literal["APP_PROMOTION", "LEAD_GENERATION", "WEB_CONVERSIONS"]
    request_id: Name = Field(..., description="Supply a stable unique request ID for this creation; reuse only for the same logical request.")
    operation_status: Literal["DISABLE", "ENABLE"] = Field("DISABLE", description="DISABLE creates a paused campaign. ENABLE may start spending.")
    budget: float | None = Field(None, gt=0, allow_inf_nan=False)
    budget_mode: Literal["BUDGET_MODE_DYNAMIC_DAILY_BUDGET", "BUDGET_MODE_TOTAL"] | None = None
    budget_optimize_on: bool | None = None
    app_id: ID | None = None
    app_promotion_type: Literal["APP_INSTALL"] | None = None
    sales_destination: Literal["WEBSITE"] | None = None
    po_number: Name | None = None
    special_industries: list[Name] | None = Field(None, max_length=100)


class UpdateCampaign(_Advertiser):
    """Update a Smart+ campaign's name, budget or purchase order."""
    operation: Literal["update_campaign"] = Field("update_campaign", json_schema_extra={"ui:hidden": True})
    campaign_id: ID
    campaign_name: Name | None = None
    budget: float | None = Field(None, gt=0, allow_inf_nan=False)
    po_number: Name | None = None

    @model_validator(mode="after")
    def change(self):
        if all(getattr(self, k) is None for k in ("campaign_name", "budget", "po_number")):
            raise ValueError("Supply a campaign name, budget or purchase order to update")
        return self


class UpdateCampaignStatus(_Advertiser):
    """Enable, pause or delete Smart+ campaigns. ENABLE may spend; DELETE is destructive."""
    operation: Literal["update_campaign_status"] = Field("update_campaign_status", json_schema_extra={"ui:hidden": True})
    campaign_ids: list[ID] = Field(..., min_length=1, max_length=20)
    operation_status: Literal["ENABLE", "DISABLE", "DELETE"]
    postback_window_mode: Literal["POSTBACK_WINDOW_MODE1", "POSTBACK_WINDOW_MODE2", "POSTBACK_WINDOW_MODE3", "UNSET"] | None = None


class ListAdgroups(_Fields):
    """Read one page of Smart+ ad groups."""
    operation: Literal["list_adgroups"] = Field("list_adgroups", title="List Smart+ Ad Groups", json_schema_extra={"ui:hidden": True})
    filtering: AdgroupFilter | None = None


class UpdateAdgroup(_Advertiser):
    """Change a Smart+ ad group's name, budget or bids."""
    operation: Literal["update_adgroup"] = Field("update_adgroup", title="Update Smart+ Ad Group", json_schema_extra={"ui:hidden": True})
    adgroup_id: ID
    adgroup_name: Name | None = None
    budget: float | None = Field(None, gt=0, allow_inf_nan=False)
    bid_price: float | None = Field(None, ge=0, allow_inf_nan=False)
    conversion_bid_price: float | None = Field(None, ge=0, allow_inf_nan=False)
    roas_bid: float | None = Field(None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def change(self):
        if all(getattr(self, k) is None for k in ("adgroup_name", "budget", "bid_price", "conversion_bid_price", "roas_bid")):
            raise ValueError("Supply an ad group name, budget or bid to update")
        return self


class UpdateAdgroupStatus(_Advertiser):
    """Enable, pause or delete Smart+ ad groups."""
    operation: Literal["update_adgroup_status"] = Field("update_adgroup_status", json_schema_extra={"ui:hidden": True})
    adgroup_ids: list[ID] = Field(..., min_length=1, max_length=20)
    operation_status: Literal["ENABLE", "DISABLE", "DELETE"]


class ListAds(_Fields):
    """Read one page of Smart+ ads."""
    operation: Literal["list_ads"] = Field("list_ads", title="List Smart+ Ads", json_schema_extra={"ui:hidden": True})
    filtering: AdFilter | None = None


class UpdateAd(_Advertiser):
    """Rename an existing Smart+ ad."""
    operation: Literal["update_ad"] = Field("update_ad", title="Rename Smart+ Ad", json_schema_extra={"ui:hidden": True})
    smart_plus_ad_id: ID
    ad_name: Name


class UpdateAdStatus(_Advertiser):
    """Enable, pause or delete Smart+ ads."""
    operation: Literal["update_ad_status"] = Field("update_ad_status", json_schema_extra={"ui:hidden": True})
    smart_plus_ad_ids: list[ID] = Field(..., min_length=1, max_length=20)
    operation_status: Literal["ENABLE", "DISABLE", "DELETE"]


class GetAdReviewInfo(_Advertiser):
    """Read review results for selected Smart+ ads."""
    operation: Literal["get_ad_review_info"] = Field("get_ad_review_info", json_schema_extra={"ui:hidden": True})
    smart_plus_ad_ids: IDs


class GetReport(_Page):
    """Read one page of basic advertising performance metrics for a date range."""
    operation: Literal["get_report"] = Field("get_report", json_schema_extra={"ui:hidden": True})
    report_type: Literal["BASIC"] = "BASIC"
    data_level: Literal["AUCTION_ADVERTISER", "AUCTION_CAMPAIGN", "AUCTION_ADGROUP", "AUCTION_AD"] = "AUCTION_CAMPAIGN"
    dimensions: list[Name] = Field(default_factory=lambda: ["campaign_id", "stat_time_day"], min_length=1, max_length=10)
    metrics: list[Name] = Field(default_factory=lambda: ["spend", "impressions", "clicks"], min_length=1, max_length=100)
    start_date: date
    end_date: date
    enable_total_metrics: bool = False

    @model_validator(mode="after")
    def dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class ListAudiences(_Page):
    """Read one page of the advertiser's custom audiences."""
    operation: Literal["list_audiences"] = Field("list_audiences", json_schema_extra={"ui:hidden": True})
    custom_audience_ids: IDs | None = None


class GetAudiences(_Advertiser):
    """Read selected custom audience details."""
    operation: Literal["get_audiences"] = Field("get_audiences", json_schema_extra={"ui:hidden": True})
    custom_audience_ids: IDs
    history_size: int | None = Field(None, ge=1, le=100)


class UpdateAudience(_Advertiser):
    """Rename a custom audience without replacing its members."""
    operation: Literal["update_audience"] = Field("update_audience", title="Rename Custom Audience", json_schema_extra={"ui:hidden": True})
    custom_audience_id: ID
    custom_audience_name: Name


class DeleteAudiences(_Advertiser):
    """Delete selected custom audiences permanently."""
    operation: Literal["delete_audiences"] = Field("delete_audiences", json_schema_extra={"ui:hidden": True})
    custom_audience_ids: IDs


class ListPixels(_Page):
    """Read one page of tracking pixels."""
    operation: Literal["list_pixels"] = Field("list_pixels", json_schema_extra={"ui:hidden": True})
    page_size: int = Field(20, ge=1, le=20)
    pixel_id: ID | None = None
    name: Name | None = None


class UpdatePixel(_Advertiser):
    """Rename an advertiser's tracking pixel."""
    operation: Literal["update_pixel"] = Field("update_pixel", title="Rename Pixel", json_schema_extra={"ui:hidden": True})
    pixel_id: ID
    pixel_name: Name


class GetAdgroupQuota(_Advertiser):
    """Read the advertiser's ad group quota."""
    operation: Literal["get_adgroup_quota"] = Field("get_adgroup_quota", json_schema_extra={"ui:hidden": True})


TikTokAdsConfig = Annotated[Union[
    GetAdvertiserInfo, ListCampaigns, CreateCampaign, UpdateCampaign, UpdateCampaignStatus,
    ListAdgroups, UpdateAdgroup, UpdateAdgroupStatus, ListAds, UpdateAd, UpdateAdStatus,
    GetAdReviewInfo, GetReport, ListAudiences, GetAudiences, UpdateAudience,
    DeleteAudiences, ListPixels, UpdatePixel, GetAdgroupQuota,
], Field(discriminator="operation")]


class TikTokAdsFullConfig(NodeConfig[TikTokAdsConfig, TikTokAdsAccessTokenCredential]):
    pass


OPERATIONS = {
    "get_advertiser_info": ("GET", "/advertiser/info/"),
    "list_campaigns": ("GET", "/smart_plus/campaign/get/"),
    "create_campaign": ("POST", "/smart_plus/campaign/create/"),
    "update_campaign": ("POST", "/smart_plus/campaign/update/"),
    "update_campaign_status": ("POST", "/smart_plus/campaign/status/update/"),
    "list_adgroups": ("GET", "/smart_plus/adgroup/get/"),
    "update_adgroup": ("POST", "/smart_plus/adgroup/update/"),
    "update_adgroup_status": ("POST", "/smart_plus/adgroup/status/update/"),
    "list_ads": ("GET", "/smart_plus/ad/get/"),
    "update_ad": ("POST", "/smart_plus/ad/update/"),
    "update_ad_status": ("POST", "/smart_plus/ad/status/update/"),
    "get_ad_review_info": ("GET", "/smart_plus/ad/review_info/"),
    "get_report": ("GET", "/report/integrated/get/"),
    "list_audiences": ("GET", "/dmp/custom_audience/list/"),
    "get_audiences": ("GET", "/dmp/custom_audience/get/"),
    "update_audience": ("POST", "/dmp/custom_audience/update/"),
    "delete_audiences": ("POST", "/dmp/custom_audience/delete/"),
    "list_pixels": ("GET", "/pixel/list/"),
    "update_pixel": ("POST", "/pixel/update/"),
    "get_adgroup_quota": ("GET", "/adgroup/quota/"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class TikTokAdsNode(WorkflowNode):
    integration_type = "automation-tiktok-ads"
    connection_evidence = ConnectionEvidence(
        noun="advertiser accounts", operation="get_advertiser_info",
        label_keys=("advertiser_name", "name", "advertiser_id"),
    )

    @classmethod
    def get_config_model(cls):
        return TikTokAdsFullConfig

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a TikTok Ads access token and advertiser ID")
        method, path = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        if config.operation == "get_advertiser_info":
            values["advertiser_ids"] = [credential.advertiser_id]
        else:
            values.setdefault("advertiser_id", credential.advertiser_id)
        params = {k: json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list, bool)) else v
                  for k, v in values.items()} if method == "GET" else None
        response = None
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Access-Token": credential.access_token, "Accept": "application/json"},
                    params=params, **({"json": values} if method == "POST" else {}))
            if len(response.content) > 5000000:
                raise ValueError("Response too large")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Expected an API envelope")
            code = body.get("code")
            if response.status_code != 200 or type(code) is not int or code != 0:
                message = body.get("message")
                return {"status": "error", "http_status": response.status_code, "status_code": response.status_code,
                    "provider_code": code if type(code) is int else None,
                    "error": _redact(message, credential.access_token)[:2000] if isinstance(message, str) else "TikTok Ads did not confirm this request"}
            data = body.get("data")
            if not isinstance(data, dict):
                raise ValueError("Expected response data")
            # Batch status endpoints can acknowledge only some of the requested IDs.
            partial = bool(data.get("error_list"))
            return _redact({"status": "error" if partial else "success", "data": data,
                "request_id": body.get("request_id"), "http_status": response.status_code,
                **({"error": "TikTok Ads reported per-item failures; inspect error_list before retrying"} if partial else {})}, credential.access_token)
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "TikTok Ads request could not be completed; inspect write outcomes before retrying"}
        except (ValueError, UnicodeError):
            return {"status": "error", "http_status": response.status_code if response is not None else None, "error": "TikTok Ads returned an invalid JSON response; inspect write outcomes before retrying"}
