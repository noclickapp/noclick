"""Owler Enterprise v3.0 company intelligence and latest-news polling."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://apiv2.owler.com"
DOCS_URL = "https://developers-v3.owler.com/"
Category = Literal["NEWS", "PRESS", "FUNDING", "ACQUISITION", "PEOPLE", "BLOG", "VIDEOS"]


class OwlerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Owler API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS_URL,
            "x-credential-instructions": "Paste your Owler Enterprise API key. NoClick sends it in the x-api-key header. Connecting reads the documented sample company (100486) to verify key acceptance; shared company data does not prove your account identity. Your API plan must include the selected endpoints."})
    credential_type: Literal["owler_api_key"] = Field("owler_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False,
        json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CompanyID(_Input):
    company_id: str = Field(..., min_length=1, title="Company ID", description="Owler company ID, for example 100486.")


class _Website(_Input):
    website: str = Field(..., min_length=1, title="Company Domain", description="Company domain, without a URL scheme or path.")


class GetCompanyByID(_CompanyID):
    operation: Literal["get_company_by_id"] = Field("get_company_by_id", title="Get Company by ID", json_schema_extra={"ui:hidden": True})


class GetCompanyByWebsite(_Website):
    operation: Literal["get_company_by_website"] = Field("get_company_by_website", title="Get Company by Domain", json_schema_extra={"ui:hidden": True})


class _CompetitorPage(_Input):
    pagination_id: str = Field("*", title="Pagination ID", description="Use * for the first page, then the returned pagination_id. A blank returned ID means the end. At most 50 competitors per page.")


class GetCompetitorsByID(_CompanyID, _CompetitorPage):
    operation: Literal["get_competitors_by_id"] = Field("get_competitors_by_id", title="Get Competitors by ID", json_schema_extra={"ui:hidden": True})


class GetCompetitorsByWebsite(_Website, _CompetitorPage):
    operation: Literal["get_competitors_by_website"] = Field("get_competitors_by_website", title="Get Competitors by Domain", json_schema_extra={"ui:hidden": True})


class _FeedFilter(_Input):
    category: Category | None = Field(None, title="News Category", description="Leave empty for all categories.")


class _FeedPage(_FeedFilter):
    limit: int = Field(10, ge=10, le=100, title="Result Limit")
    pagination_id: str | None = Field(None, title="Pagination ID", description="Leave blank for the latest feeds; use the returned ID for the next page.")


def _company_list(value: str) -> str:
    items = [item.strip() for item in value.split(",")]
    if not 1 <= len(items) <= 10 or any(not item for item in items):
        raise ValueError("Provide one to ten comma-separated companies")
    return ",".join(items)


class _FeedIDs(_Input):
    company_id: str = Field(..., min_length=1, title="Company IDs", description="One to ten comma-separated Owler company IDs.")
    _ids = field_validator("company_id")(_company_list)


class _FeedDomains(_Input):
    domain: str = Field(..., min_length=1, title="Company Domains", description="One to ten comma-separated company domains.")
    _domains = field_validator("domain")(_company_list)


class GetFeedsByID(_FeedIDs, _FeedPage):
    operation: Literal["get_feeds_by_id"] = Field("get_feeds_by_id", title="Get Company News by IDs", json_schema_extra={"ui:hidden": True})


class GetFundingNews(GetFeedsByID):
    operation: Literal["get_funding_news"] = Field("get_funding_news", title="Get Funding News", json_schema_extra={"ui:hidden": True})
    category: Literal["FUNDING"] = Field("FUNDING", json_schema_extra={"ui:hidden": True})


class GetAcquisitionNews(GetFeedsByID):
    operation: Literal["get_acquisition_news"] = Field("get_acquisition_news", title="Get Acquisition News", json_schema_extra={"ui:hidden": True})
    category: Literal["ACQUISITION"] = Field("ACQUISITION", json_schema_extra={"ui:hidden": True})


class GetPeopleNews(GetFeedsByID):
    operation: Literal["get_people_news"] = Field("get_people_news", title="Get Leadership and People News", json_schema_extra={"ui:hidden": True})
    category: Literal["PEOPLE"] = Field("PEOPLE", json_schema_extra={"ui:hidden": True})


class GetPressReleases(GetFeedsByID):
    operation: Literal["get_press_releases"] = Field("get_press_releases", title="Get Press Releases", json_schema_extra={"ui:hidden": True})
    category: Literal["PRESS"] = Field("PRESS", json_schema_extra={"ui:hidden": True})


class GetFeedsByWebsite(_FeedDomains, _FeedPage):
    operation: Literal["get_feeds_by_website"] = Field("get_feeds_by_website", title="Get Company News by Domains", json_schema_extra={"ui:hidden": True})


class OnNewFeedByID(_FeedIDs, _FeedFilter, PollTriggerConfigBase):
    """Watch the latest 100 feeds in this scope; poll often enough to keep up."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_new_feed_by_id"] = Field("on_new_feed_by_id", title="On New Company News by IDs", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


class OnNewFeedByWebsite(_FeedDomains, _FeedFilter, PollTriggerConfigBase):
    """Watch the latest 100 feeds in this scope; poll often enough to keep up."""
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_new_feed_by_website"] = Field("on_new_feed_by_website", title="On New Company News by Domains", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


OwlerConfig = Annotated[Union[GetCompanyByID, GetCompanyByWebsite, GetCompetitorsByID,
    GetCompetitorsByWebsite, GetFeedsByID, GetFeedsByWebsite, GetFundingNews,
    GetAcquisitionNews, GetPeopleNews, GetPressReleases, OnNewFeedByID,
    OnNewFeedByWebsite], Field(discriminator="operation")]


class OwlerNodeConfig(NodeConfig[OwlerConfig, OwlerAPIKeyCredential]):
    pass


class OwlerNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-owler"
    connection_evidence = ConnectionEvidence(operation="get_company_by_id",
        operation_arguments={"company_id": "100486"}, noun="company records", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return OwlerNodeConfig

    @staticmethod
    async def _request(api_key: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request("GET", BASE_URL + path,
                params={"format": "json", **params},
                headers={"x-api-key": api_key, "Accept": "application/json"})
        if response.is_error:
            detail = response.text.replace(api_key, "[redacted]")
            raise ValueError(f"Owler API error {response.status_code}: {detail[:2000]}")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object from Owler")
        return body

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Owler Enterprise API key")
        config = self.config.config
        params: dict[str, Any] = {}
        if isinstance(config, (GetCompanyByID, GetCompanyByWebsite, GetCompetitorsByID, GetCompetitorsByWebsite)):
            competitors = isinstance(config, (GetCompetitorsByID, GetCompetitorsByWebsite))
            prefix = "/v1/company/competitorpremium" if competitors else "/v1/companypremium"
            if isinstance(config, _CompanyID):
                path = prefix + "/id/" + quote(config.company_id, safe="")
            else:
                path = prefix + "/url/" + quote(config.website, safe="")
            if competitors:
                params["pagination_id"] = config.pagination_id
        else:
            by_id = isinstance(config, _FeedIDs)
            path = "/v1/feed" if by_id else "/v1/feed/url"
            params["company_id" if by_id else "domain"] = config.company_id if by_id else config.domain
            if config.category is not None:
                params["category"] = config.category
            params["limit"] = str(config.limit if isinstance(config, _FeedPage) else 100)
            if isinstance(config, _FeedPage) and config.pagination_id:
                params["pagination_id"] = config.pagination_id
        body = await self._request(credential.api_key, path, params)
        if isinstance(config, (OnNewFeedByID, OnNewFeedByWebsite)):
            feeds = body.get("feed", [])
            if not isinstance(feeds, list) or any(not isinstance(item, dict) for item in feeds):
                raise ValueError("Expected Owler's feed array")
            fresh = await self._filter_unseen(feeds, lambda item: item.get("id") or None)
            return {"feed": fresh, "new_feed_count": len(fresh)}
        return body

    @classmethod
    def resolve_agent_event(cls, output):
        feeds = output.get("feed") if isinstance(output, dict) else None
        if not isinstance(feeds, list):
            return super().resolve_agent_event(output)
        if not feeds:
            return None
        lines = []
        for feed in feeds[:20]:
            company = feed.get("company") or {}
            lines.append(f"- {company.get('name') or 'Company'} (company ID {company.get('company_id', '')}): "
                f"{feed.get('title') or 'New company news'} [{feed.get('category', '')}]\n"
                f"  {feed.get('description', '')}\n"
                f"  {feed.get('source_url') or feed.get('owler_feed_url') or ''} "
                f"(feed ID {feed.get('id', '')}, {feed.get('feed_date', '')})")
        return {"text": f"Owler: {len(feeds)} new company news item(s)\n" + "\n".join(lines), "conversation_key": None}
