"""Domains-Index v1 reads and scheduled added/deleted-domain feeds.

Contract: https://api.domains-index.com/v1/swagger.json (version 1.0).
The published API is read-only. Pagination tokens are query values, never URLs.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.domains-index.com/v1"


class DomainsdbAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Domains-Index API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://domains-index.com/my-account/",
            "x-credential-instructions": "Paste your Domains-Index API key. NoClick checks the key's license information using the API key information endpoint.",
        })
    credential_type: Literal["domainsdb_api_key"] = Field("domainsdb_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API Key")


class _Input(BaseModel):
    pass


class SearchDomainsConfig(_Input):
    operation: Literal["search_domains"] = Field("search_domains", title="Search Domains", json_schema_extra={"ui:hidden": True})
    date: str | None = Field(None, title="Date", description="Request date")
    page: str | None = Field(None, title="Page", description="Search page to request")
    limit: int = Field(50, title="Limit", description="Results per page", ge=1)
    domain: str | None = Field(None, title="Domain", description="Domain includes")
    zone: str | None = Field(None, title="Zone", description="In Zone")
    country: str | None = Field(None, title="Country", description="Hosting Country")
    isDead: bool | None = Field(None, title="Isdead", description="Dead or Not, default not")
    A: str | None = Field(None, title="A", description="A record includes")
    NS: str | None = Field(None, title="NS", description="NS record includes")
    CNAME: str | None = Field(None, title="CNAME", description="CNAME record includes")
    MX: str | None = Field(None, title="MX", description="MX record includes")
    TXT: str | None = Field(None, title="TXT", description="TXT record includes")

class ListTldDomainsConfig(_Input):
    operation: Literal["list_tld_domains"] = Field("list_tld_domains", title="List TLD Domains", json_schema_extra={"ui:hidden": True})
    zone_id: str = Field(..., title="Zone Id", min_length=1)
    date: str | None = Field(None, title="Date", description="Request date")
    page: str | None = Field(None, title="Page", description="Search page to request")
    limit: int = Field(50, title="Limit", description="Results per page", ge=1)
    domain: str | None = Field(None, title="Domain", description="Domain includes")
    country: str | None = Field(None, title="Country", description="Hosting Country")
    isDead: bool | None = Field(None, title="Isdead", description="Dead or Not, default not")
    A: str | None = Field(None, title="A", description="A record includes")
    NS: str | None = Field(None, title="NS", description="NS record includes")
    CNAME: str | None = Field(None, title="CNAME", description="CNAME record includes")
    MX: str | None = Field(None, title="MX", description="MX record includes")
    TXT: str | None = Field(None, title="TXT", description="TXT record includes")

class SearchTldDomainsConfig(_Input):
    operation: Literal["search_tld_domains"] = Field("search_tld_domains", title="Search TLD Domains", json_schema_extra={"ui:hidden": True})
    zone_id: str = Field(..., title="Zone Id", min_length=1)
    date: str | None = Field(None, title="Date", description="Request date")
    page: str | None = Field(None, title="Page", description="Search page to request")
    limit: int = Field(50, title="Limit", description="Results per page", ge=1)
    domain: str | None = Field(None, title="Domain", description="Domain includes")
    country: str | None = Field(None, title="Country", description="Hosting Country")
    isDead: bool | None = Field(None, title="Isdead", description="Dead or Not, default not")
    A: str | None = Field(None, title="A", description="A record includes")
    NS: str | None = Field(None, title="NS", description="NS record includes")
    CNAME: str | None = Field(None, title="CNAME", description="CNAME record includes")
    MX: str | None = Field(None, title="MX", description="MX record includes")
    TXT: str | None = Field(None, title="TXT", description="TXT record includes")

class ListAddedDomainsConfig(_Input):
    operation: Literal["list_added_domains"] = Field("list_added_domains", title="List Added Domains", json_schema_extra={"ui:hidden": True})
    date: str | None = Field(None, title="Date", description="Request date")
    page: str | None = Field(None, title="Page", description="Search page to request")
    limit: int = Field(50, title="Limit", description="Results per page", ge=1)

class ListDeletedDomainsConfig(_Input):
    operation: Literal["list_deleted_domains"] = Field("list_deleted_domains", title="List Deleted Domains", json_schema_extra={"ui:hidden": True})
    date: str | None = Field(None, title="Date", description="Request date")
    page: str | None = Field(None, title="Page", description="Search page to request")
    limit: int = Field(50, title="Limit", description="Results per page", ge=1)

class ListUpdatesConfig(_Input):
    operation: Literal["list_updates"] = Field("list_updates", title="List Updates", json_schema_extra={"ui:hidden": True})

class GetApiInfoConfig(_Input):
    operation: Literal["get_api_info"] = Field("get_api_info", title="Get API Key Information", json_schema_extra={"ui:hidden": True})

class ListStatisticsConfig(_Input):
    operation: Literal["list_statistics"] = Field("list_statistics", title="List Zone Statistics", json_schema_extra={"ui:hidden": True})
    page: str | None = Field(None, title="Page", description="Search page to request")
    limit: int = Field(50, title="Limit", description="Results per page", ge=1)

class GetZoneStatisticsConfig(_Input):
    operation: Literal["get_zone_statistics"] = Field("get_zone_statistics", title="Get Zone Statistics", json_schema_extra={"ui:hidden": True})
    zone: str = Field(..., title="Zone", min_length=1)
    page: str | None = Field(None, title="Page", description="Search page to request")
    limit: int = Field(50, title="Limit", description="Results per page", ge=1)

class ListTldsConfig(_Input):
    operation: Literal["list_tlds"] = Field("list_tlds", title="List TLDs", json_schema_extra={"ui:hidden": True})

class GetTldConfig(_Input):
    operation: Literal["get_tld"] = Field("get_tld", title="Get TLD Information", json_schema_extra={"ui:hidden": True})
    zone: str = Field(..., title="Zone", min_length=1)
    page: str | None = Field(None, title="Page", description="Search page to request")
    limit: int = Field(50, title="Limit", description="Results per page", ge=1)

class OnAddedDomainConfig(PollTriggerConfigBase):
    operation: Literal["on_added_domain"] = Field("on_added_domain", title="On Added Domain", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    date: str | None = Field(None, title="Update Date", description="Provider request date. Omit to watch the latest update feed. First poll establishes a baseline; at most 1,000 domains per feed are supported.")

class OnDeletedDomainConfig(PollTriggerConfigBase):
    operation: Literal["on_deleted_domain"] = Field("on_deleted_domain", title="On Deleted Domain", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    date: str | None = Field(None, title="Update Date", description="Provider request date. Omit to watch the latest update feed. First poll establishes a baseline; at most 1,000 domains per feed are supported.")


ROUTES = {'search_domains': '/domains/search', 'list_tld_domains': '/domains/tld/{zone_id}', 'search_tld_domains': '/domains/tld/{zone_id}/search', 'list_added_domains': '/domains/updates/added', 'list_deleted_domains': '/domains/updates/deleted', 'list_updates': '/domains/updates/list', 'get_api_info': '/info/api', 'list_statistics': '/info/stat/', 'get_zone_statistics': '/info/stat/{zone}', 'list_tlds': '/info/tld/', 'get_tld': '/info/tld/{zone}', 'on_added_domain': '/domains/updates/added', 'on_deleted_domain': '/domains/updates/deleted'}

DomainsdbConfig = Annotated[Union[SearchDomainsConfig, ListTldDomainsConfig, SearchTldDomainsConfig, ListAddedDomainsConfig, ListDeletedDomainsConfig, ListUpdatesConfig, GetApiInfoConfig, ListStatisticsConfig, GetZoneStatisticsConfig, ListTldsConfig, GetTldConfig, OnAddedDomainConfig, OnDeletedDomainConfig], Field(discriminator="operation")]


class DomainsdbNodeConfig(NodeConfig[DomainsdbConfig, DomainsdbAPIKeyCredential]):
    model_config = ConfigDict(title="Domains Index Node Configuration")


class DomainsdbNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-domainsdb"
    connection_evidence = ConnectionEvidence(
        noun="API key license", identity_operation="get_api_info",
        identity_keys=("customer_name", "customer_email", "item_name"),
    )

    @classmethod
    def get_config_model(cls):
        return DomainsdbNodeConfig

    async def _request(self, path, params):
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request("GET", BASE_URL + path, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Domains-Index could not be reached") from None
        # Do not attach httpx's URL-bearing exception: api_key is a query secret.
        if response.status_code >= 300:
            raise ValueError(f"Domains-Index request failed (HTTP {response.status_code})")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Domains-Index returned an invalid JSON response") from None
        if not isinstance(body, (dict, list)):
            raise ValueError("Domains-Index returned an unexpected response")
        if isinstance(body, dict):
            if body.get("error") or body.get("errors") or str(body.get("success", "")).lower() in {"false", "0"}:
                raise ValueError("Domains-Index rejected the request")
        return body

    async def execute(self, inputs):
        if not isinstance(self.config, DomainsdbNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Domains-Index API key")
        config = self.config.config
        operation = config.operation
        path = ROUTES[operation]
        trigger = isinstance(config, PollTriggerConfigBase)
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if trigger:
            values = {"limit": 50, **({"date": config.date} if config.date else {})}
        for field in ("zone_id", "zone"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        # Only the domain APIs and API-info endpoint declare api_key.
        if path.startswith("/domains/") or path == "/info/api":
            values["api_key"] = self.config.credentials.api_key
        body = await self._request(path, values)
        if not trigger:
            return {"data": body}
        domains = []
        seen_pages = set()
        for page in range(20):
            if not isinstance(body, dict) or not isinstance(body.get("domains"), list):
                raise ValueError("Expected a Domains-Index domains page")
            for item in body["domains"]:
                if not isinstance(item, dict) or not isinstance(item.get("domain"), str) or not item["domain"]:
                    raise ValueError("Expected a domain name in every feed item")
                domains.append(item)
            cursor = body.get("next_page")
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in seen_pages or page == 19:
                raise ValueError("Domain feed exceeds the poll bound or repeats a page; choose an update date")
            seen_pages.add(cursor)
            values["page"] = cursor
            body = await self._request(path, values)
        fresh = await self._filter_unseen(domains, lambda item: item["domain"] + ":" + str(item.get("create_date") or "") + ":" + str(item.get("update_date") or ""))
        return {"domains": fresh, "domain_count": len(fresh), "change": "added" if operation == "on_added_domain" else "deleted"}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "change" not in output:
            return super().resolve_agent_event(output)
        domains = output.get("domains")
        if not domains:
            return None
        lines = [f"- {item['domain']} (created: {item.get('create_date', 'unknown')}; updated: {item.get('update_date', 'unknown')})" for item in domains[:20]]
        return {"text": f"Domains-Index: {len(domains)} {output['change']} domain(s) in the watched update feed.\n" + "\n".join(lines), "conversation_key": None}
