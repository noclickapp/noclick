"""Smartlead account analytics and master-inbox actions using a pasted API key.

Routes are fixed to the provider's server API. Each operation issues one request;
page offsets and limits are explicit, and mutations are never automatically retried.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://server.smartlead.ai/api"


class SmartleadAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Smartlead API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.smartlead.ai/app/settings/profile",
            "x-credential-instructions": "In Smartlead, open Settings > API Keys and copy your API key. Paste only the key. NoClick uses it to read your campaigns and run the actions you select. API access depends on your Smartlead plan.",
        })
    credential_type: Literal["smartlead_api_key"] = Field("smartlead_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(char.isspace() for char in value):
            raise ValueError("Paste only the API key without spaces or a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _ClientFilter(_Input):
    client_ids: str | None = Field(None, max_length=2000, pattern=r"^[0-9]+(?:,[0-9]+)*$", description="Comma-separated client IDs.")


class _DateFilter(_ClientFilter):
    start_date: str = Field(..., json_schema_extra={"format": "date"}, description="Inclusive start date, YYYY-MM-DD.")
    end_date: str = Field(..., json_schema_extra={"format": "date"}, description="End date, YYYY-MM-DD.")
    timezone: str = Field(..., min_length=1, max_length=100, description="IANA timezone, for example America/New_York or UTC.")
    campaign_ids: str | None = Field(None, max_length=2000, pattern=r"^[0-9]+(?:,[0-9]+){0,99}$", description="Comma-separated campaign IDs, at most 100.")

    @field_validator("start_date", "end_date")
    @classmethod
    def calendar_date(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Use YYYY-MM-DD")
        return value

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Use an IANA timezone") from None
        return value

    @model_validator(mode="after")
    def date_order(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class _Lead(_Input):
    email_lead_map_id: int = Field(..., gt=0, description="Lead-campaign mapping ID from the inbox; this is not the lead ID.")


class LeadCategories(_Input):
    unassigned: bool | None = None
    isAssigned: bool | None = None
    categoryIdsNotIn: list[int] | None = None
    categoryIdsIn: list[int] | None = None


class InboxFilters(_Input):
    search: str | None = Field(None, max_length=1000)
    leadCategories: LeadCategories | None = None
    emailStatus: list[Literal["Opened", "Clicked", "Replied", "Unsubscribed", "Bounced", "Accepted", "Not Replied"]] | None = None
    campaignId: list[int] | None = Field(None, max_length=5)
    emailAccountId: list[int] | None = None
    campaignTeamMemberId: list[int] | None = None
    campaignTagId: list[int] | None = None
    campaignClientId: list[int] | None = None
    replyTimeBetween: list[str] | None = Field(None, min_length=2, max_length=2)


class SmartleadListCampaignsConfig(_ClientFilter):
    """Get Campaign List."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})


class SmartleadListClientsConfig(_ClientFilter):
    """Get Client List."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})


class SmartleadCampaignStatusStatsConfig(_Input):
    """Get Campaign Status Stats."""
    operation: Literal["get_campaign_status_stats"] = Field("get_campaign_status_stats", json_schema_extra={"ui:hidden": True})


class SmartleadOverallStatsConfig(_DateFilter):
    """Get Overall Stats V2."""
    operation: Literal["get_overall_stats"] = Field("get_overall_stats", json_schema_extra={"ui:hidden": True})
    is_agency: Literal["true", "false"] | None = None
    full_data: Literal["true", "false"] | None = None


class SmartleadDailyStatsConfig(_DateFilter):
    """Get Day-wise Overall Stats."""
    operation: Literal["get_daily_stats"] = Field("get_daily_stats", json_schema_extra={"ui:hidden": True})


class SmartleadCampaignPerformanceConfig(_DateFilter):
    """Get Campaign Overall Stats."""
    operation: Literal["get_campaign_performance"] = Field("get_campaign_performance", json_schema_extra={"ui:hidden": True})
    full_data: Literal["true", "false"] | None = None
    limit: int | None = Field(None, ge=1, description="Page size; use offset for further pages.")
    offset: int | None = Field(None, ge=0)


class SmartleadCampaignResponseStatsConfig(_DateFilter):
    """Get Campaign Response Stats."""
    operation: Literal["get_campaign_response_stats"] = Field("get_campaign_response_stats", json_schema_extra={"ui:hidden": True})
    full_data: Literal["true", "false"] | None = None


class SmartleadFollowupReplyRateConfig(_DateFilter):
    """Get Follow-up Reply Rate."""
    operation: Literal["get_followup_reply_rate"] = Field("get_followup_reply_rate", json_schema_extra={"ui:hidden": True})


class SmartleadLeadStatsConfig(_DateFilter):
    """Get Lead Overall Stats."""
    operation: Literal["get_lead_stats"] = Field("get_lead_stats", json_schema_extra={"ui:hidden": True})


class SmartleadGetInboxLeadConfig(_Input):
    """Fetch Master Inbox Lead by ID."""
    operation: Literal["get_inbox_lead"] = Field("get_inbox_lead", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, title="Inbox mapping ID")


class SmartleadListInboxRepliesConfig(_Input):
    """Fetch Inbox Replies."""
    operation: Literal["list_inbox_replies"] = Field("list_inbox_replies", json_schema_extra={"ui:hidden": True})
    fetch_message_history: bool = False
    offset: int = Field(0, ge=0, description="Number of replies to skip; advance explicitly to read further pages.")
    limit: int = Field(10, ge=1, le=20)
    filters: InboxFilters | None = None
    sortBy: Literal["REPLY_TIME_DESC", "SENT_TIME_DESC"] | None = None


class SmartleadUpdateCategoryConfig(_Lead):
    """Update Lead Category."""
    operation: Literal["update_lead_category"] = Field("update_lead_category", json_schema_extra={"ui:hidden": True})
    category_id: int = Field(..., gt=0, description="Category to assign.")


class SmartleadUpdateRevenueConfig(_Lead):
    """Update Lead Revenue."""
    operation: Literal["update_lead_revenue"] = Field("update_lead_revenue", json_schema_extra={"ui:hidden": True})
    revenue: float = Field(..., ge=0, allow_inf_nan=False)


class SmartleadCreateTaskConfig(_Lead):
    """Create Lead Task."""
    operation: Literal["create_lead_task"] = Field("create_lead_task", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=20000)
    priority: Literal["LOW", "MEDIUM", "HIGH"]
    due_date: str = Field(..., json_schema_extra={"format": "date-time"}, description="ISO 8601 due date with timezone.")

    @field_validator("due_date")
    @classmethod
    def due(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Due date must include a timezone")
        return value


class SmartleadCreateNoteConfig(_Lead):
    """Create Lead Note."""
    operation: Literal["create_lead_note"] = Field("create_lead_note", json_schema_extra={"ui:hidden": True})
    note_message: str = Field(..., min_length=1, max_length=20000)


class SmartleadResumeLeadConfig(_Lead):
    """Resume Lead."""
    operation: Literal["resume_lead"] = Field("resume_lead", json_schema_extra={"ui:hidden": True})
    campaign_id: int = Field(..., gt=0)
    resume_delay_days: int | None = Field(None, ge=0)


class SmartleadBlockDomainsConfig(_Input):
    """Block Domains."""
    operation: Literal["block_domains"] = Field("block_domains", json_schema_extra={"ui:hidden": True})
    domains: list[str] = Field(..., min_length=1, description="Domains to block across all campaigns.")
    source: str = Field("manual", max_length=100)


class SmartleadMarkUnreadConfig(_Lead):
    """Mark Lead as Unread."""
    operation: Literal["mark_lead_unread"] = Field("mark_lead_unread", json_schema_extra={"ui:hidden": True})


class SmartleadAddTagsConfig(_Input):
    """Add Tags to Email Accounts."""
    operation: Literal["add_email_account_tags"] = Field("add_email_account_tags", json_schema_extra={"ui:hidden": True})
    email_account_ids: list[int] = Field(..., min_length=1, max_length=25)
    tag_ids: list[int] = Field(..., min_length=1)


class SmartleadRemoveTagsConfig(_Input):
    """Remove Tags from Email Accounts."""
    operation: Literal["remove_email_account_tags"] = Field("remove_email_account_tags", json_schema_extra={"ui:hidden": True})
    email_account_ids: list[int] = Field(..., min_length=1)
    tag_ids: list[int] = Field(..., min_length=1)


SmartleadOperation = Annotated[Union[
    SmartleadListCampaignsConfig,
    SmartleadListClientsConfig,
    SmartleadCampaignStatusStatsConfig,
    SmartleadOverallStatsConfig,
    SmartleadDailyStatsConfig,
    SmartleadCampaignPerformanceConfig,
    SmartleadCampaignResponseStatsConfig,
    SmartleadFollowupReplyRateConfig,
    SmartleadLeadStatsConfig,
    SmartleadGetInboxLeadConfig,
    SmartleadListInboxRepliesConfig,
    SmartleadUpdateCategoryConfig,
    SmartleadUpdateRevenueConfig,
    SmartleadCreateTaskConfig,
    SmartleadCreateNoteConfig,
    SmartleadResumeLeadConfig,
    SmartleadBlockDomainsConfig,
    SmartleadMarkUnreadConfig,
    SmartleadAddTagsConfig,
    SmartleadRemoveTagsConfig
], Field(discriminator="operation")]


class SmartleadFullConfig(NodeConfig[SmartleadOperation, SmartleadAPIKeyCredential]):
    pass


# One fixed provider route per operation: method, path, query field names.
ROUTES = {'list_campaigns': ('GET', '/v1/analytics/campaign/list', ('client_ids',)),
 'list_clients': ('GET', '/v1/analytics/client/list', ('client_ids',)),
 'get_campaign_status_stats': ('GET', '/v1/analytics/campaign/status-stats', ()),
 'get_overall_stats': ('GET',
                       '/v1/analytics/overall-stats-v2',
                       ('start_date',
                        'end_date',
                        'timezone',
                        'client_ids',
                        'campaign_ids',
                        'is_agency',
                        'full_data')),
 'get_daily_stats': ('GET',
                     '/v1/analytics/day-wise-overall-stats',
                     ('start_date', 'end_date', 'timezone', 'client_ids', 'campaign_ids')),
 'get_campaign_performance': ('GET',
                              '/v1/analytics/campaign/overall-stats',
                              ('start_date',
                               'end_date',
                               'timezone',
                               'client_ids',
                               'campaign_ids',
                               'full_data',
                               'limit',
                               'offset')),
 'get_campaign_response_stats': ('GET',
                                 '/v1/analytics/campaign/response-stats',
                                 ('start_date',
                                  'end_date',
                                  'timezone',
                                  'client_ids',
                                  'campaign_ids',
                                  'full_data')),
 'get_followup_reply_rate': ('GET',
                             '/v1/analytics/campaign/follow-up-reply-rate',
                             ('start_date', 'end_date', 'timezone', 'client_ids', 'campaign_ids')),
 'get_lead_stats': ('GET',
                    '/v1/analytics/lead/overall-stats',
                    ('start_date', 'end_date', 'timezone', 'client_ids', 'campaign_ids')),
 'get_inbox_lead': ('GET', '/v1/master-inbox/{id}', ()),
 'list_inbox_replies': ('POST', '/v1/master-inbox/inbox-replies', ('fetch_message_history',)),
 'update_lead_category': ('PATCH', '/v1/master-inbox/update-category', ()),
 'update_lead_revenue': ('PATCH', '/v1/master-inbox/update-revenue', ()),
 'create_lead_task': ('POST', '/v1/master-inbox/create-task', ()),
 'create_lead_note': ('POST', '/v1/master-inbox/create-note', ()),
 'resume_lead': ('PATCH', '/v1/master-inbox/resume-lead', ()),
 'block_domains': ('POST', '/v1/master-inbox/block-domains', ()),
 'mark_lead_unread': ('PATCH', '/v1/master-inbox/mark-unread', ()),
 'add_email_account_tags': ('POST', '/v1/email-accounts/tag-mapping', ()),
 'remove_email_account_tags': ('DELETE', '/v1/email-accounts/tag-mapping', ())}


class SmartleadNode(WorkflowNode):
    integration_type = "automation-smartlead"
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns")

    @classmethod
    def get_config_model(cls):
        return SmartleadFullConfig

    async def execute(self, inputs):
        full = self.config
        if not full.credentials:
            return {"status": "error", "error": "Connect a Smartlead API key"}
        op = full.config
        method, path, query_fields = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        values.pop("operation")
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        query = {"api_key": full.credentials.api_key}
        for field in query_fields:
            if field in values:
                value = values.pop(field)
                query[field] = str(value).lower() if isinstance(value, bool) else str(value)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=query,
                    headers={"Accept": "application/json"},
                    **({"json": values} if method != "GET" else {}))
            if len(response.content) > 10_000_000:
                return {"status": "error", "error": "Smartlead response exceeds the supported size"}
            try:
                body = response.json()
            except ValueError:
                return {"status": "error", "status_code": response.status_code,
                    "error": "Smartlead returned a non-JSON response"}
            # Never return the query key, including when a provider echoes it.
            body = _redact(body, full.credentials.api_key)
            failed = isinstance(body, dict) and (body.get("success") is False or body.get("ok") is False or bool(body.get("error")))
            if not response.is_success or failed:
                message = (body.get("message") or body.get("error")) if isinstance(body, dict) else None
                return {"status": "error", "status_code": response.status_code,
                    "error": message if isinstance(message, str) else "Smartlead request failed"}
            if not isinstance(body, dict):
                return {"status": "error", "error": "Expected a Smartlead JSON object"}
            result = {"status": "success", "data": body}
            if op.operation in {"list_campaigns", "list_clients"}:
                data = body.get("data")
                if not isinstance(data, dict):
                    return {"status": "error", "error": "Smartlead list response is missing data"}
                keys = ("campaigns", "campaign_list") if op.operation == "list_campaigns" else ("clients", "client_list")
                items = next((data[key] for key in keys if key in data), None)
                if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                    return {"status": "error", "error": "Smartlead list response has an unexpected shape"}
                result["items"] = items
            return result
        except (httpx.HTTPError, OSError):
            # httpx exceptions contain the request URL, which contains the key.
            return {"status": "error", "error": "Smartlead request could not be completed"}


def _redact(value, secret):
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()
            if key.lower() not in {"api_key", "authorization"}}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    return value
