"""Campaign Cleaner campaign analysis and inbox placement automation.

Each operation makes one request to the provider's published v1 contract.
API keys are pasted by the user; downloads use the platform's binary output seam.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.campaigncleaner.com"


class CampaignCleanerAPIKey(BaseModel):
    model_config = ConfigDict(title="Campaign Cleaner API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://campaigncleaner.com",
            "x-credential-instructions": "In Campaign Cleaner, open API Management → API Keys. Copy your API key and paste it here. Monitor writes require an active Inbox Placement Monitor plan and a role other than User.",
        })
    credential_type: Literal["campaign_cleaner_api_key"] = Field("campaign_cleaner_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Campaign(_Input):
    campaign_id: str = Field(..., min_length=1, title="Campaign ID", description="ID returned by Send Campaign or Get Campaign List.")


class GetCampaignStatus(_Campaign):
    operation: Literal["get_campaign_status"] = Field("get_campaign_status", title="Get Campaign Status", json_schema_extra={"ui:hidden": True})


class GetCampaignList(_Input):
    operation: Literal["get_campaign_list"] = Field("get_campaign_list", title="Get Campaign List", json_schema_extra={"ui:hidden": True})


class GetCampaign(_Campaign):
    operation: Literal["get_campaign"] = Field("get_campaign", title="Get Campaign", json_schema_extra={"ui:hidden": True})
    minimize_html: bool = Field(True, description="Remove whitespace from the cleaned HTML.")


class DeleteCampaign(_Campaign):
    operation: Literal["delete_campaign"] = Field("delete_campaign", title="Delete Campaign", description="Permanently delete the saved campaign and its analysis.", json_schema_extra={"ui:hidden": True})


class GetCredits(_Input):
    operation: Literal["get_credits"] = Field("get_credits", title="Get Credits", json_schema_extra={"ui:hidden": True})


class GetCampaignPDFAnalysis(_Campaign):
    operation: Literal["get_campaign_pdf_analysis"] = Field("get_campaign_pdf_analysis", title="Get Campaign PDF Analysis", json_schema_extra={"ui:hidden": True})


class SurroundingDiv(_Input):
    max_width: int | None = Field(None, ge=1)
    text_align: Literal["left", "center", "right"] | None = None
    font_size: int | None = Field(None, ge=1)
    center_to_parent: bool | None = None


class SendCampaign(_Input):
    operation: Literal["send_campaign"] = Field("send_campaign", title="Send Campaign for Cleaning", description="Submit HTML for analysis and sanitization; consumes one API credit. This does not send email to recipients.", json_schema_extra={"ui:hidden": True})
    campaign_html: str = Field(..., min_length=1, title="Campaign HTML", json_schema_extra={"ui:widget": "textarea"})
    campaign_name: str = Field(..., min_length=1, title="Campaign Name")
    adjust_font_colors: bool | None = None
    adjust_font_size: bool | None = None
    min_font_size_allowed: int | None = Field(None, ge=1, le=99)
    max_font_size_allowed: int | None = Field(None, ge=1, le=99)
    convert_h_to_p_tags: bool | None = None
    convert_tables_to_divs: bool | None = None
    custom_info: str | None = Field(None, max_length=500)
    host_extensionless_images: bool | None = None
    inline_css: bool | None = None
    inline_css_important: bool | None = None
    media_queries_important: bool | None = None
    preserve_media_queries: bool | None = None
    relative_links_base_url: str | None = None
    remove_classes_and_ids: bool | None = None
    remove_comments: bool | None = None
    remove_control_non_printable: bool | None = None
    remove_css_inheritance: bool | None = None
    remove_image_height: bool | None = None
    remove_large_widths_over: int | None = Field(None, ge=1)
    remove_successive_punctuation: bool | None = None
    replace_diacritics: bool | None = None
    replace_non_ascii_characters: bool | None = None
    resize_and_host: bool | None = None
    set_image_max_width: int | None = Field(None, ge=1)
    webhook_url: str | None = Field(None, description="Absolute HTTP(S) callback URL without a query string. The provider posts results here.")
    surrounding_div: SurroundingDiv | None = None

    @field_validator("relative_links_base_url", "webhook_url")
    @classmethod
    def absolute_url(cls, value, info):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Use an absolute HTTP(S) URL without credentials or a fragment")
        if info.field_name == "webhook_url" and parsed.query:
            raise ValueError("Webhook URLs must have no query string")
        return value

    @model_validator(mode="after")
    def font_range(self):
        if self.min_font_size_allowed is not None and self.max_font_size_allowed is not None and self.min_font_size_allowed > self.max_font_size_allowed:
            raise ValueError("Minimum font size must not exceed maximum font size")
        return self


class CreateInboxTest(_Input):
    operation: Literal["create_inbox_test"] = Field("create_inbox_test", title="Create Inbox Test", description="Create a seed test, consuming one credit. Send your email to the returned seed list separately.", json_schema_extra={"ui:hidden": True})
    test_name: str = Field(..., min_length=1, max_length=80, title="Test Name")


class GetInboxTestResults(_Input):
    operation: Literal["get_inbox_test_results"] = Field("get_inbox_test_results", title="Get Inbox Test Results", json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, title="Job ID")


class MonitorGetSeeds(_Input):
    operation: Literal["monitor_get_seeds"] = Field("monitor_get_seeds", title="Get Monitor Seeds", json_schema_extra={"ui:hidden": True})


class MonitorGetDomains(_Input):
    operation: Literal["monitor_get_domains"] = Field("monitor_get_domains", title="Get Monitor Domains", json_schema_extra={"ui:hidden": True})


class MonitorAddDomain(_Input):
    operation: Literal["monitor_add_domain"] = Field("monitor_add_domain", title="Add Monitor Domain", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=1, title="Sending Domain", description="Domain only, for example news.example.com. Publish the returned DNS TXT record before verification.")
    alerts_only: bool = False


class _Domain(_Input):
    domain_id: int = Field(..., ge=1, title="Domain ID")


class MonitorVerifyDomain(_Domain):
    operation: Literal["monitor_verify_domain"] = Field("monitor_verify_domain", title="Verify Monitor Domain", description="Check the pending domain's DNS TXT record.", json_schema_extra={"ui:hidden": True})


class MonitorRemoveDomain(_Domain):
    operation: Literal["monitor_remove_domain"] = Field("monitor_remove_domain", title="Remove Monitor Domain", description="Permanently deletes the domain, stored messages and alerts.", json_schema_extra={"ui:hidden": True})


class MonitorGetMessages(_Input):
    operation: Literal["monitor_get_messages"] = Field("monitor_get_messages", title="Get Monitor Messages", json_schema_extra={"ui:hidden": True})
    domain_id: int | None = Field(None, ge=1)
    provider_key: str | None = None
    placement: Literal["Inbox", "Spam", "Promotions", "Social", "Updates", "Newsletter", "Announcements", "Forums", "Other"] | None = None
    days: int = Field(30, ge=1, le=30)
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class MonitorGetMessage(_Input):
    operation: Literal["monitor_get_message"] = Field("monitor_get_message", title="Get Monitor Message", json_schema_extra={"ui:hidden": True})
    message_id: int = Field(..., ge=1, title="Message ID")
    include_eml: bool = Field(False, description="Also return the original email as an EML file; provider limit 10 requests per minute.")


class MonitorGetSummary(_Input):
    operation: Literal["monitor_get_summary"] = Field("monitor_get_summary", title="Get Monitor Placement Summary", json_schema_extra={"ui:hidden": True})
    days: int = Field(30, ge=1, le=365)
    domain_id: int | None = Field(None, ge=1)


class MonitorGetUsage(_Input):
    operation: Literal["monitor_get_usage"] = Field("monitor_get_usage", title="Get Monitor Usage", json_schema_extra={"ui:hidden": True})


class MonitorGetAlerts(_Input):
    operation: Literal["monitor_get_alerts"] = Field("monitor_get_alerts", title="Get Monitor Alerts", json_schema_extra={"ui:hidden": True})


class MonitorSaveAlert(_Input):
    operation: Literal["monitor_save_alert"] = Field("monitor_save_alert", title="Save Monitor Alert", description="Create an alert or replace the alert identified by Alert ID. Recipients must be the owner, team members or addresses at verified domains.", json_schema_extra={"ui:hidden": True})
    kind: Literal["spam", "notinbox", "rate", "auth"]
    alert_id: int | None = Field(None, ge=1)
    domain_id: int | None = Field(None, ge=0, description="Omit or use 0 for all domains.")
    provider_key: str | None = None
    threshold: int | None = Field(None, ge=1, le=100)
    min_messages: int | None = Field(None, ge=1, le=1000)
    delivery: Literal["instant", "digest"] = "instant"
    recipients: list[str] | None = Field(None, max_length=5, description="Up to five email addresses. Empty sends to the account owner.")
    enabled: bool = True


class MonitorDeleteAlert(_Input):
    operation: Literal["monitor_delete_alert"] = Field("monitor_delete_alert", title="Delete Monitor Alert", description="Delete the alert and its history.", json_schema_extra={"ui:hidden": True})
    alert_id: int = Field(..., ge=1)


CampaignCleanerConfig = Annotated[Union[
    GetCampaignStatus, GetCampaignList, GetCampaign, DeleteCampaign, GetCredits,
    GetCampaignPDFAnalysis, SendCampaign, CreateInboxTest, GetInboxTestResults,
    MonitorGetSeeds, MonitorGetDomains, MonitorAddDomain, MonitorVerifyDomain,
    MonitorRemoveDomain, MonitorGetMessages, MonitorGetMessage, MonitorGetSummary,
    MonitorGetUsage, MonitorGetAlerts, MonitorSaveAlert, MonitorDeleteAlert,
], Field(discriminator="operation")]


class CampaignCleanerFullConfig(NodeConfig[CampaignCleanerConfig, CampaignCleanerAPIKey]):
    pass


GET_OPERATIONS = frozenset({"get_campaign_list", "get_credits", "monitor_get_seeds",
    "monitor_get_domains", "monitor_get_messages", "monitor_get_message", "monitor_get_summary",
    "monitor_get_usage", "monitor_get_alerts"})


class CampaignCleanerNode(WorkflowNode):
    integration_type = "automation-campaign-cleaner"
    connection_evidence = ConnectionEvidence(operation="get_campaign_list", noun="saved campaigns",
        label_keys=("campaign_name", "id"))

    @classmethod
    def get_config_model(cls):
        return CampaignCleanerFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Campaign Cleaner API key")
        operation = config.operation
        payload = config.model_dump(exclude={"operation"}, exclude_none=True)
        if isinstance(config, _Campaign):
            payload = {"campaign": {"id": payload.pop("campaign_id"), **payload}}
        elif operation == "send_campaign":
            payload = {"send_campaign": payload}
        method = "GET" if operation in GET_OPERATIONS else "POST"
        kwargs = {"params": payload} if method == "GET" else {"json": payload}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + "/v1/" + operation,
                    headers={"X-CC-API-Key": credential.api_key,
                        "Accept": "application/pdf" if operation == "get_campaign_pdf_analysis" else "application/json"},
                    **kwargs)
        except httpx.HTTPError:
            raise ValueError("Campaign Cleaner request could not be completed") from None
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if response.is_success and operation == "get_campaign_pdf_analysis" and mime == "application/pdf":
            return {"file": BinaryOutput(response.content, "application/pdf", "campaign-analysis.pdf")}
        try:
            body = response.json()
        except ValueError:
            raise ValueError(f"Campaign Cleaner returned an unexpected response (HTTP {response.status_code})") from None
        if not isinstance(body, dict):
            raise ValueError("Campaign Cleaner returned an unexpected JSON response")
        # The API can reject a call with HTTP 200 and X-CC-Status: 4001.
        if not response.is_success or body.get("error") or response.headers.get("X-CC-Status") == "4001":
            detail = str(body.get("error") or body.get("message") or f"HTTP {response.status_code}")
            return {"status": "error", "error": detail.replace(credential.api_key, "[redacted]"), "http_status": response.status_code}
        if operation == "get_campaign_pdf_analysis":
            raise ValueError("Campaign Cleaner did not return a PDF report")
        if operation == "monitor_get_message" and "eml_base64" in body:
            encoded = body.pop("eml_base64")
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise ValueError("Campaign Cleaner returned an invalid original email") from None
            body["file"] = BinaryOutput(decoded, "message/rfc822", "original-message.eml")
        return body
