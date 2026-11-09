"""SalesRobot campaign and prospect automation using its published Postman API.

Each operation makes one request to api.boomtechinc.com. Saved examples are
contract evidence, not a schema or proof that a live account was exercised.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import date, time

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.boomtechinc.com/api"
DOCS = "https://documenter.getpostman.com/view/10815846/2sB3BKE8Fb"


class SalesrobotAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Salesrobot API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.salesrobot.co/admin/settings?tab=apiKey",
            "x-credential-instructions": "Generate an API key in SalesRobot Settings > API Key and paste it here. Copy the LinkedIn Account UUID from your SalesRobot account. NoClick sends X-API-KEY only to api.boomtechinc.com and lists this account's campaigns to check the connection."
        })
    credential_type: Literal["salesrobot_api_key"] = Field("salesrobot_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})
    linkedin_account_uuid: UUID = Field(..., title="LinkedIn Account UUID",
        description="The LinkedIn account to use for campaign, prospect and messaging operations.")

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Campaign(_Input):
    campaign_uuid: UUID = Field(..., title="Campaign UUID")


class _Prospect(_Input):
    prospect_uuid: UUID = Field(..., title="Prospect UUID")


class ListCampaigns(_Input):
    """List the connected LinkedIn account's campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})


class CreateCampaign(_Input):
    """Create an advanced LinkedIn campaign."""
    operation: Literal["create_campaign"] = Field("create_campaign", json_schema_extra={"ui:hidden": True})
    campaign_name: str = Field(..., min_length=1, max_length=1000)


class PauseCampaign(_Campaign):
    """Pause or resume one campaign."""
    operation: Literal["pause_campaign"] = Field("pause_campaign", json_schema_extra={"ui:hidden": True})
    pause: bool = True
    continue_started_campaign: bool = False


class StartCampaign(_Campaign):
    """Start a configured campaign."""
    operation: Literal["start_campaign"] = Field("start_campaign", json_schema_extra={"ui:hidden": True})
    has_invite_message: bool = False


class GetCampaignStats(_Campaign):
    """Read time-wise statistics for one campaign."""
    operation: Literal["get_campaign_stats"] = Field("get_campaign_stats", json_schema_extra={"ui:hidden": True})


class ListProspects(_Campaign):
    """Read one page of campaign prospects; increment page to continue."""
    operation: Literal["list_prospects"] = Field("list_prospects", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description="One-based page number, as in the published request.")
    size: int = Field(10, ge=1)
    sort: str = Field("createdTime,desc")


class GetProspectStatus(_Prospect):
    """Read campaign execution details for one prospect."""
    operation: Literal["get_prospect_status"] = Field("get_prospect_status", json_schema_extra={"ui:hidden": True})


class PauseProspect(_Prospect):
    """Pause or resume campaign execution for one prospect."""
    operation: Literal["pause_prospect"] = Field("pause_prospect", json_schema_extra={"ui:hidden": True})
    pause: bool = True


class ProspectFields(_Input):
    profileUrl: str | None = None
    salesNavUrl: str | None = None
    uniqueLinkedinId: str | None = None
    jobTitle: str | None = None
    companyName: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    fullName: str | None = None
    emailId: str | None = None
    phoneNo: str | None = None
    profilePhoto: str | None = None
    customMap: dict[str, str] | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Supply at least one prospect field")
        return self


class NewProspectFields(ProspectFields):
    profileUrl: str = Field(..., min_length=1, description="LinkedIn profile URL of the prospect to add.")


class AddProspect(_Campaign):
    """Add a single prospect to a campaign."""
    operation: Literal["add_prospect"] = Field("add_prospect", json_schema_extra={"ui:hidden": True})
    prospect: NewProspectFields


class UpdateProspect(_Prospect):
    """Update documented prospect fields; omitted fields are not sent."""
    operation: Literal["update_prospect"] = Field("update_prospect", json_schema_extra={"ui:hidden": True})
    prospect: ProspectFields


class DeleteProspect(_Prospect):
    """Delete a single prospect from the account."""
    operation: Literal["delete_prospect"] = Field("delete_prospect", json_schema_extra={"ui:hidden": True})


class DeleteProspects(_Input):
    """Delete an explicit selection of prospects; never select the whole account."""
    operation: Literal["delete_prospects"] = Field("delete_prospects", json_schema_extra={"ui:hidden": True})
    prospect_uuids: list[UUID] = Field(..., min_length=1)


class SearchImport(_Input):
    searchUrl: str = Field(..., min_length=1, description="LinkedIn or Sales Navigator search URL.")
    searchType: str = Field("normal")
    connectionLevels: list[Literal["1st", "2nd", "3rd"]] = Field(default_factory=lambda: ["2nd", "3rd"])
    openInmailDiscover: bool = False
    premiumOnly: bool = False
    dontAddIfInAnotherLinkedinAccountForMyUser: bool = True
    enableFastSync: bool = False
    collectContactInfo: bool = True
    enrichData: bool = True
    groupMessageUrl: str = ""
    eventMessageUrl: str = ""


class ImportProspects(_Campaign):
    """Import prospects from a LinkedIn search URL."""
    operation: Literal["import_prospects"] = Field("import_prospects", json_schema_extra={"ui:hidden": True})
    search: SearchImport


class UpdateBlacklist(_Input):
    """Update company and profile blacklist entries."""
    operation: Literal["update_blacklist"] = Field("update_blacklist", json_schema_extra={"ui:hidden": True})
    company_names: list[str] = Field(..., description="Company domains, for example google.com.")
    profile_urls: list[str] = Field(..., description="LinkedIn profile URLs to blacklist.")


class CopyBlacklist(_Input):
    """Copy a blacklist from another LinkedIn account."""
    operation: Literal["copy_blacklist"] = Field("copy_blacklist", json_schema_extra={"ui:hidden": True})
    copy_from_account: UUID


class ScheduleFields(_Input):
    name: str = Field(..., min_length=1)
    maxProspectsToReach: int = Field(..., ge=0)
    startTime: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    endTime: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    timeZoneString: str
    safeModeEnabled: bool
    dayOfWeeks: list[Literal["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]]
    skipDates: list[date] = Field(default_factory=list)
    shouldSkipOneDayInWeek: bool = False

    @field_validator("startTime", "endTime")
    @classmethod
    def valid_time(cls, value):
        time.fromisoformat(value)
        return value

    @field_validator("timeZoneString")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use an IANA time zone such as Asia/Kolkata") from None
        return value


class UpdateSchedule(_Input):
    """Set the connected account's outreach schedule."""
    operation: Literal["update_schedule"] = Field("update_schedule", json_schema_extra={"ui:hidden": True})
    schedule: ScheduleFields


class QuotaFields(_Input):
    dailyViewQuota: int | None = Field(None, ge=0)
    dailyConnectQuota: int | None = Field(None, ge=0)
    dailyMessageQuota: int | None = Field(None, ge=0)
    dailyVoiceMessageQuota: int | None = Field(None, ge=0)
    dailyVideoMessageQuota: int | None = Field(None, ge=0)
    dailyFollowQuota: int | None = Field(None, ge=0)
    dailyInMailMessageQuota: int | None = Field(None, ge=0)
    dailyMailQuota: int | None = Field(None, ge=0)
    dailyMessageFromGroupsQuota: int | None = Field(None, ge=0)
    dailyMessageFromEventsQuota: int | None = Field(None, ge=0)
    dailyEndorsementQuota: int | None = Field(None, ge=0)
    dailyLikeCommentQuota: int | None = Field(None, ge=0)
    dailyEmailMessageQuota: int | None = Field(None, ge=0)
    automatedWarmUp: bool | None = None
    automatedWarmUpInMail: bool | None = None
    automatedWarmUpEndValue: int | None = Field(None, ge=0)
    automatedWarmUpStepValue: int | None = Field(None, ge=0)
    automatedWarmUpFrequency: int | None = Field(None, ge=0)
    automatedWarmUpEndValueInMail: int | None = Field(None, ge=0)
    automatedWarmUpStepValueInMail: int | None = Field(None, ge=0)
    automatedWarmUpFrequencyInMail: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Supply at least one quota setting")
        return self


class UpdateQuota(_Input):
    """Set daily quotas and warm-up settings."""
    operation: Literal["update_quota"] = Field("update_quota", json_schema_extra={"ui:hidden": True})
    quota: QuotaFields


class TagChat(_Prospect):
    """Set tags on a LinkedIn inbox conversation."""
    operation: Literal["tag_chat"] = Field("tag_chat", json_schema_extra={"ui:hidden": True})
    tags: list[str]


class SendMessage(_Prospect):
    """Send one LinkedIn message to a prospect."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    message: str = Field(..., min_length=1)


class TagAccount(_Input):
    """Add tags to the connected LinkedIn account."""
    operation: Literal["tag_account"] = Field("tag_account", json_schema_extra={"ui:hidden": True})
    tags: list[str] = Field(..., min_length=1)


SalesrobotConfig = Annotated[Union[ListCampaigns, CreateCampaign, PauseCampaign, StartCampaign,
    GetCampaignStats, ListProspects, GetProspectStatus, PauseProspect, AddProspect, UpdateProspect,
    DeleteProspect, DeleteProspects, ImportProspects, UpdateBlacklist, CopyBlacklist, UpdateSchedule,
    UpdateQuota, TagChat, SendMessage, TagAccount], Field(discriminator="operation")]


class SalesrobotFullConfig(NodeConfig[SalesrobotConfig, SalesrobotAPIKeyCredential]):
    pass


ROUTES = {
    "list_campaigns": ("GET", "/campaigns"),
    "create_campaign": ("POST", "/campaign"),
    "pause_campaign": ("POST", "/campaign/pause"),
    "start_campaign": ("POST", "/start"),
    "get_campaign_stats": ("GET", "/campaignTimeWiseStats"),
    "list_prospects": ("GET", "/campaign/prospects"),
    "get_prospect_status": ("GET", "/campaign/prospects/execution-details"),
    "pause_prospect": ("POST", "/campaign/pauseForProspect"),
    "add_prospect": ("POST", "/add-single-prospect"),
    "update_prospect": ("PUT", "/update-single-prospect"),
    "delete_prospect": ("DELETE", "/delete-single-prospect"),
    "delete_prospects": ("POST", "/campaign/deleteMultiple"),
    "import_prospects": ("POST", "/add-from-lisalesnav-search"),
    "update_blacklist": ("POST", "/blacklist/update"),
    "copy_blacklist": ("POST", "/blacklist/copy_from_account"),
    "update_schedule": ("POST", "/schedule"),
    "update_quota": ("POST", "/settings/quota"),
    "tag_chat": ("POST", "/messageTags"),
    "send_message": ("POST", "/sendAMessage"),
    "tag_account": ("POST", "/linkedinAccounts/tags/add"),
}


def _redact(value, key):
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value.replace(key, "[redacted]") if isinstance(value, str) else value


class SalesrobotNode(WorkflowNode):
    integration_type = "automation-salesrobot"
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns")

    @classmethod
    def get_config_model(cls):
        return SalesrobotFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SalesRobot API key and LinkedIn Account UUID")
        op = self.config.config
        credential = self.config.credentials
        account = str(credential.linkedin_account_uuid)
        action = op.operation
        method, route = ROUTES[action]
        values = op.model_dump(mode="json", exclude_none=True)
        params = {"linkedinAccountUuid": account}
        body = None
        if "campaign_uuid" in values:
            params["campaignUuid"] = values["campaign_uuid"]
        if "prospect_uuid" in values and action not in {"send_message", "tag_chat"}:
            params["prospectUuid"] = values["prospect_uuid"]
        if action == "create_campaign":
            body = {"campaignName": op.campaign_name, "campaignType": "ADVANCED",
                    "campaignFamily": "LINKEDIN", "linkedinAccountUuid": account}
        elif action == "pause_campaign":
            params.update(pause=str(op.pause).lower(), continueStartedCampaign=str(op.continue_started_campaign).lower())
        elif action == "start_campaign":
            params["hasInviteMessage"] = str(op.has_invite_message).lower()
        elif action == "list_prospects":
            params.update(page=op.page, size=op.size, sort=op.sort)
        elif action == "pause_prospect":
            params["pause"] = str(op.pause).lower()
        elif action in {"add_prospect", "update_prospect"}:
            body = values["prospect"]
        elif action == "delete_prospects":
            body = {"selectedProspectUuids": values["prospect_uuids"], "allSelected": False}
        elif action == "import_prospects":
            body = {"selectedAccountType": "LINKEDIN_ACCOUNT", **values["search"]}
        elif action == "update_blacklist":
            body = {"companyNames": op.company_names, "profileUrls": op.profile_urls}
        elif action == "copy_blacklist":
            params["copyFromAccount"] = str(op.copy_from_account)
            body = {}
        elif action == "update_schedule":
            body = values["schedule"]
        elif action == "update_quota":
            body = values["quota"]
        elif action == "tag_chat":
            body = {"tags": op.tags, "linkedinAccountUuid": account,
                    "linkedinProspectUuid": str(op.prospect_uuid), "inboxType": "linkedinInbox"}
        elif action == "send_message":
            params = {}
            body = {"prospectUuid": str(op.prospect_uuid), "messageToSend": op.message, "linkedinAccountUuid": account}
        elif action == "tag_account":
            body = {"tags": op.tags, "linkedinAccountUuid": account}
        headers = {"X-API-KEY": credential.api_key, "Accept": "application/json"}
        # The collection publishes this exact media type on these writes.
        if action in {"add_prospect", "update_blacklist", "copy_blacklist", "tag_chat", "tag_account"}:
            headers["Content-Type"] = "application/json;charset=UTF-8"
        else:
            headers["Content-Type"] = "application/json"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, params=params,
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("SalesRobot request did not complete; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            return {"status": "error", "operation": action, "http_status": response.status_code,
                    "error": _redact(response.text[:4000], credential.api_key)}
        if len(response.content) > 20_000_000:
            raise ValueError("SalesRobot response exceeds 20 MB")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("SalesRobot returned invalid JSON") from None
        if not isinstance(data, dict) or type(data.get("success")) is not bool:
            raise ValueError("SalesRobot returned an unexpected response envelope")
        if data["success"] is False:
            return {"status": "error", "operation": action, "http_status": response.status_code,
                    "error": _redact(data.get("message", "SalesRobot rejected the request"), credential.api_key)}
        if "data" not in data:
            raise ValueError("SalesRobot response is missing its documented data")
        if action in {"list_campaigns", "list_prospects"}:
            page = data["data"]
            if not isinstance(page, dict) or not isinstance(page.get("data"), list) or any(not isinstance(row, dict) for row in page["data"]):
                raise ValueError("SalesRobot returned an unexpected list response")
        return {"status": "success", "operation": action, **_redact(data, credential.api_key)}
