"""SecurityTrails DNS intelligence v1 and ASI project API v2.

Each operation makes one documented request. List results preserve the provider's
page/cursor metadata; tag changes preserve asynchronous completion and task IDs.
Contract sources: https://dash.readme.com/api/v1/api-registry/8jym43um90abqfc
and https://api.securitytrails.com/v2/openapi.json
"""
from __future__ import annotations

import re
from ipaddress import ip_address
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class SecurityTrailsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Securitytrails API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.securitytrails.com/docs/authentication",
            "x-credential-instructions": "Paste your API key from the SecurityTrails control panel. DNS intelligence uses the documented v1 apikey query parameter; ASI uses the apikey header. Requests go only to api.securitytrails.com. Account usage verifies the key. ASI operations additionally require an ASI subscription and project access.",
        },
    )
    credential_type: Literal["securitytrails_api_key"] = Field(
        "securitytrails_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API key",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("hostname", check_fields=False)
    @classmethod
    def hostname_value(cls, value):
        value = value.rstrip(".").lower()
        if len(value) > 253 or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
            for part in value.split(".")
        ):
            raise ValueError("Use a DNS hostname without a URL or path")
        return value

    @field_validator("ipaddress", check_fields=False)
    @classmethod
    def ip_value(cls, value):
        try:
            return str(ip_address(value))
        except ValueError:
            raise ValueError("Use an IPv4 or IPv6 address") from None

    @field_validator(
        "project_id", "task_id", "asset_id", "tag_name", check_fields=False
    )
    @classmethod
    def path_value(cls, value):
        # AssetFilter.asset_id is a typed equality expression, not a route segment.
        if not isinstance(value, str):
            return value
        if (
            value != value.strip()
            or value in {".", ".."}
            or any(c in value for c in "/\\?#")
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Use a single identifier or tag without path separators")
        return value


class DomainFilter(_Input):
    """Documented v1 domain filters; supplied filters are AND-combined."""

    ipv4: str | None = Field(None, min_length=1, max_length=1000)
    ipv6: str | None = Field(None, min_length=1, max_length=1000)
    apex_domain: str | None = Field(None, min_length=1, max_length=1000)
    keyword: str | None = Field(None, min_length=1, max_length=1000)
    mx: str | None = Field(None, min_length=1, max_length=1000)
    ns: str | None = Field(None, min_length=1, max_length=1000)
    cname: str | None = Field(None, min_length=1, max_length=1000)
    subdomain: str | None = Field(None, min_length=1, max_length=1000)
    soa_email: str | None = Field(None, min_length=1, max_length=1000)
    tld: str | None = Field(None, min_length=1, max_length=1000)
    whois_email: str | None = Field(None, min_length=1, max_length=1000)
    whois_street1: str | None = Field(None, min_length=1, max_length=1000)
    whois_street2: str | None = Field(None, min_length=1, max_length=1000)
    whois_street3: str | None = Field(None, min_length=1, max_length=1000)
    whois_street4: str | None = Field(None, min_length=1, max_length=1000)
    whois_telephone: str | None = Field(None, min_length=1, max_length=1000)
    whois_postalCode: str | None = Field(None, min_length=1, max_length=1000)
    whois_organization: str | None = Field(None, min_length=1, max_length=1000)
    whois_name: str | None = Field(None, min_length=1, max_length=1000)
    whois_fax: str | None = Field(None, min_length=1, max_length=1000)
    whois_city: str | None = Field(None, min_length=1, max_length=1000)


class EqualityFilter(_Input):
    eq: str = Field(..., min_length=1)


class AssetPropertiesFilter(_Input):
    asset_id: EqualityFilter | None = None
    asset_type: EqualityFilter | None = None
    custom_tags: EqualityFilter | None = None
    apex: EqualityFilter | None = None


class QuickSearchFilter(_Input):
    search: str = Field(..., min_length=1, max_length=100)


class AssetFilter(_Input):
    asset_properties: AssetPropertiesFilter | None = None
    quick_search: QuickSearchFilter | None = None


class Pagination(_Input):
    limit: int = Field(50, ge=1, le=1000)
    next_cursor: str | None = Field(
        None,
        description="meta.pagination.next_cursor from the previous response; retain the same sort and filters",
    )


class GetUsageConfig(_Input):
    "Usage"

    operation: Literal["get_usage"] = Field(
        "get_usage", json_schema_extra={"ui:hidden": True}
    )


class GetDomainConfig(_Input):
    "Get Domain"

    operation: Literal["get_domain"] = Field(
        "get_domain", json_schema_extra={"ui:hidden": True}
    )
    hostname: str = Field(..., min_length=1, max_length=1000)


class ExploreIpsConfig(_Input):
    "Explore IPs"

    operation: Literal["explore_ips"] = Field(
        "explore_ips", json_schema_extra={"ui:hidden": True}
    )
    ipaddress: str = Field(..., min_length=1, max_length=1000)


class GetDomainWhoisConfig(_Input):
    "Get WHOIS"

    operation: Literal["get_domain_whois"] = Field(
        "get_domain_whois", json_schema_extra={"ui:hidden": True}
    )
    hostname: str = Field(..., min_length=1, max_length=1000)


class GetIpUseragentsConfig(_Input):
    "Get Useragents"

    operation: Literal["get_ip_useragents"] = Field(
        "get_ip_useragents", json_schema_extra={"ui:hidden": True}
    )
    ipaddress: str = Field(..., min_length=1, max_length=1000)


class SearchDomainsConfig(_Input):
    "Search Domain (filter)"

    operation: Literal["search_domains"] = Field(
        "search_domains", json_schema_extra={"ui:hidden": True}
    )
    include_ips: bool = Field(False)
    page: int | None = Field(None, ge=1)
    filter: DomainFilter = Field(
        ...,
        description="AND-combined domain filters. An empty object searches all domains.",
    )


class GetSubdomainsConfig(_Input):
    "List Subdomains"

    operation: Literal["get_subdomains"] = Field(
        "get_subdomains", json_schema_extra={"ui:hidden": True}
    )
    hostname: str = Field(..., min_length=1, max_length=1000)


class GetDomainStatisticsConfig(_Input):
    "Search statistics"

    operation: Literal["get_domain_statistics"] = Field(
        "get_domain_statistics", json_schema_extra={"ui:hidden": True}
    )
    filter: DomainFilter = Field(
        ...,
        description="AND-combined domain filters. An empty object searches all domains.",
    )
    query: str | None = Field(
        None, min_length=1, description="Optional domain DSL expression"
    )


class GetDomainTagsConfig(_Input):
    "List Tags"

    operation: Literal["get_domain_tags"] = Field(
        "get_domain_tags", json_schema_extra={"ui:hidden": True}
    )
    hostname: str = Field(..., min_length=1, max_length=1000)


class GetDnsHistoryConfig(_Input):
    "DNS history by record type"

    operation: Literal["get_dns_history"] = Field(
        "get_dns_history", json_schema_extra={"ui:hidden": True}
    )
    hostname: str = Field(..., min_length=1, max_length=1000)
    type: Literal["a", "aaaa", "mx", "ns", "soa", "txt"] = Field(...)
    page: int | None = Field(None, ge=1)


class GetAssociatedDomainsConfig(_Input):
    "Find associated domains"

    operation: Literal["get_associated_domains"] = Field(
        "get_associated_domains", json_schema_extra={"ui:hidden": True}
    )
    hostname: str = Field(..., min_length=1, max_length=1000)
    page: int | None = Field(None, ge=1)


class SearchIpsConfig(_Input):
    "Search IPs (DSL)"

    operation: Literal["search_ips"] = Field(
        "search_ips", json_schema_extra={"ui:hidden": True}
    )
    page: int | None = Field(None, ge=1)
    query: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="SecurityTrails IP DSL expression",
    )


class GetIpStatisticsConfig(_Input):
    "IP Search statistics"

    operation: Literal["get_ip_statistics"] = Field(
        "get_ip_statistics", json_schema_extra={"ui:hidden": True}
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="SecurityTrails IP DSL expression",
    )


class GetIpWhoisConfig(_Input):
    "Get IP Whois"

    operation: Literal["get_ip_whois"] = Field(
        "get_ip_whois", json_schema_extra={"ui:hidden": True}
    )
    ipaddress: str = Field(..., min_length=1, max_length=1000)


class ListProjectsConfig(_Input):
    "List Projects"

    operation: Literal["list_projects"] = Field(
        "list_projects", json_schema_extra={"ui:hidden": True}
    )
    sort_direction: Literal["asc", "desc"] = Field(
        "desc", description="The direction to sort by"
    )


class SearchAssetsConfig(_Input):
    "Search Assets"

    operation: Literal["search_assets"] = Field(
        "search_assets", json_schema_extra={"ui:hidden": True}
    )
    project_id: str = Field(
        ..., min_length=1, max_length=1000, description="The ID of the project"
    )
    filter: AssetFilter | None = None
    pagination: Pagination = Field(default_factory=Pagination)
    enrichments: list[
        Literal[
            "custom_tags",
            "dns_records",
            "whois",
            "ip_metadata",
            "open_tcp_ports",
            "open_udp_ports",
            "web_technologies",
            "certificates",
            "certificate_chain",
            "defenses",
            "exposures",
            "exposure_instance_details",
        ]
    ] | None = None


class ListAssetExposuresConfig(_Input):
    "List Asset Exposures"

    operation: Literal["list_asset_exposures"] = Field(
        "list_asset_exposures", json_schema_extra={"ui:hidden": True}
    )
    asset_id: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The asset identifier (domain or IP)",
    )
    project_id: str = Field(
        ..., min_length=1, max_length=1000, description="The ID of the project"
    )


class ListProjectTagsConfig(_Input):
    "Get Tags"

    operation: Literal["list_project_tags"] = Field(
        "list_project_tags", json_schema_extra={"ui:hidden": True}
    )
    project_id: str = Field(
        ..., min_length=1, max_length=1000, description="The ID of the project"
    )


class GetTagTaskConfig(_Input):
    "Get Custom Tag Task Status"

    operation: Literal["get_tag_task"] = Field(
        "get_tag_task", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Task id which was returned in a prior asset tagging request.",
    )
    project_id: str = Field(
        ..., min_length=1, max_length=1000, description="The ID of the project"
    )


class ApplyAssetTagConfig(_Input):
    "Apply Tag To Asset"

    operation: Literal["apply_asset_tag"] = Field(
        "apply_asset_tag", json_schema_extra={"ui:hidden": True}
    )
    asset_id: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The asset identifier (domain or IP)",
    )
    tag_name: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The tag name to apply to the asset. This tag will be created if it does not exist already.",
    )
    project_id: str = Field(
        ..., min_length=1, max_length=1000, description="The ID of the project"
    )


class RemoveAssetTagConfig(_Input):
    "Remove Tag From Asset"

    operation: Literal["remove_asset_tag"] = Field(
        "remove_asset_tag", json_schema_extra={"ui:hidden": True}
    )
    asset_id: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The asset identifier (domain or IP)",
    )
    tag_name: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Tag to be removed from the asset.",
    )
    project_id: str = Field(
        ..., min_length=1, max_length=1000, description="The ID of the project"
    )


class CreateProjectTagConfig(_Input):
    "Add Tag"

    operation: Literal["create_project_tag"] = Field(
        "create_project_tag", json_schema_extra={"ui:hidden": True}
    )
    tag_name: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The tag you wish to add. This will be added with the casing specified in your requestbut filtering and usage are case-insensitive.",
    )
    project_id: str = Field(
        ..., min_length=1, max_length=1000, description="The ID of the project"
    )


SecurityTrailsConfig = Annotated[
    Union[
        GetUsageConfig,
        GetDomainConfig,
        ExploreIpsConfig,
        GetDomainWhoisConfig,
        GetIpUseragentsConfig,
        SearchDomainsConfig,
        GetSubdomainsConfig,
        GetDomainStatisticsConfig,
        GetDomainTagsConfig,
        GetDnsHistoryConfig,
        GetAssociatedDomainsConfig,
        SearchIpsConfig,
        GetIpStatisticsConfig,
        GetIpWhoisConfig,
        ListProjectsConfig,
        SearchAssetsConfig,
        ListAssetExposuresConfig,
        ListProjectTagsConfig,
        GetTagTaskConfig,
        ApplyAssetTagConfig,
        RemoveAssetTagConfig,
        CreateProjectTagConfig,
    ],
    Field(discriminator="operation"),
]


class SecurityTrailsFullConfig(
    NodeConfig[SecurityTrailsConfig, SecurityTrailsAPIKeyCredential]
):
    pass


ROUTES = {
    "get_usage": {
        "version": 1,
        "method": "GET",
        "path": "/account/usage",
        "path_fields": [],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "usage-old",
    },
    "get_domain": {
        "version": 1,
        "method": "GET",
        "path": "/domain/{hostname}",
        "path_fields": ["hostname"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "get-domain-old",
    },
    "explore_ips": {
        "version": 1,
        "method": "GET",
        "path": "/ips/nearby/{ipaddress}",
        "path_fields": ["ipaddress"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "explore-ips-old",
    },
    "get_domain_whois": {
        "version": 1,
        "method": "GET",
        "path": "/domain/{hostname}/whois",
        "path_fields": ["hostname"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "get-whois-old",
    },
    "get_ip_useragents": {
        "version": 1,
        "method": "GET",
        "path": "/ips/{ipaddress}/useragents",
        "path_fields": ["ipaddress"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "get-useragents-for-ip-old",
    },
    "search_domains": {
        "version": 1,
        "method": "POST",
        "path": "/domains/list",
        "path_fields": [],
        "query_fields": ["include_ips", "page"],
        "body_fields": ["filter"],
        "operation_id": "search-old",
    },
    "get_subdomains": {
        "version": 1,
        "method": "GET",
        "path": "/domain/{hostname}/subdomains",
        "path_fields": ["hostname"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "list-subdomains-old",
    },
    "get_domain_statistics": {
        "version": 1,
        "method": "POST",
        "path": "/domains/stats",
        "path_fields": [],
        "query_fields": [],
        "body_fields": ["filter", "query"],
        "operation_id": "search-count-old",
    },
    "get_domain_tags": {
        "version": 1,
        "method": "GET",
        "path": "/domain/{hostname}/tags",
        "path_fields": ["hostname"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "list-tags-old",
    },
    "get_dns_history": {
        "version": 1,
        "method": "GET",
        "path": "/history/{hostname}/dns/{type}",
        "path_fields": ["hostname", "type"],
        "query_fields": ["page"],
        "body_fields": [],
        "operation_id": "dns-history-by-record-type-old",
    },
    "get_associated_domains": {
        "version": 1,
        "method": "GET",
        "path": "/domain/{hostname}/associated",
        "path_fields": ["hostname"],
        "query_fields": ["page"],
        "body_fields": [],
        "operation_id": "find-associated-domains-old",
    },
    "search_ips": {
        "version": 1,
        "method": "POST",
        "path": "/ips/list",
        "path_fields": [],
        "query_fields": ["page"],
        "body_fields": ["query"],
        "operation_id": "search-ips-dsl-old",
    },
    "get_ip_statistics": {
        "version": 1,
        "method": "POST",
        "path": "/ips/stats",
        "path_fields": [],
        "query_fields": [],
        "body_fields": ["query"],
        "operation_id": "ip-search-statistics-old",
    },
    "get_ip_whois": {
        "version": 1,
        "method": "GET",
        "path": "/ips/{ipaddress}/whois",
        "path_fields": ["ipaddress"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "get-ip-whois-old",
    },
    "list_projects": {
        "version": 2,
        "method": "GET",
        "path": "/projects",
        "path_fields": [],
        "query_fields": ["sort_direction"],
        "body_fields": [],
        "operation_id": "Project-list_projects",
    },
    "search_assets": {
        "version": 2,
        "method": "POST",
        "path": "/projects/{project_id}/assets/_search",
        "path_fields": ["project_id"],
        "query_fields": [],
        "body_fields": ["filter", "pagination", "enrichments"],
        "operation_id": "Assets-search_assets",
    },
    "list_asset_exposures": {
        "version": 2,
        "method": "GET",
        "path": "/projects/{project_id}/assets/{asset_id}/exposures",
        "path_fields": ["asset_id", "project_id"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "Assets-list_asset_exposures",
    },
    "list_project_tags": {
        "version": 2,
        "method": "GET",
        "path": "/projects/{project_id}/tags",
        "path_fields": ["project_id"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "Tagging-get_tags",
    },
    "get_tag_task": {
        "version": 2,
        "method": "GET",
        "path": "/projects/{project_id}/tags/_task_status/{task_id}",
        "path_fields": ["task_id", "project_id"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "Tagging-get_custom_tag_task_status",
    },
    "apply_asset_tag": {
        "version": 2,
        "method": "PUT",
        "path": "/projects/{project_id}/assets/{asset_id}/tags/{tag_name}",
        "path_fields": ["asset_id", "tag_name", "project_id"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "Assets-apply_tag_to_asset",
    },
    "remove_asset_tag": {
        "version": 2,
        "method": "DELETE",
        "path": "/projects/{project_id}/assets/{asset_id}/tags/{tag_name}",
        "path_fields": ["asset_id", "tag_name", "project_id"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "Assets-remove_tag_from_asset",
    },
    "create_project_tag": {
        "version": 2,
        "method": "POST",
        "path": "/projects/{project_id}/tags/{tag_name}",
        "path_fields": ["tag_name", "project_id"],
        "query_fields": [],
        "body_fields": [],
        "operation_id": "Tagging-add_tag",
    },
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]").replace(
            quote(secret, safe=""), "[redacted]"
        )
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


class SecurityTrailsNode(WorkflowNode):
    integration_type = "automation-securitytrails"
    connection_evidence = ConnectionEvidence(
        operation="get_usage", noun="account API usage"
    )

    @classmethod
    def get_config_model(cls):
        return SecurityTrailsFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a SecurityTrails API key")
        route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = route["path"]
        for name in route["path_fields"]:
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {
            name: values[name] for name in route["query_fields"] if name in values
        }
        headers = {"Accept": "application/json"}
        # v1 publishes an explicit query parameter; v2 declares APIKeyHeader.
        if route["version"] == 1:
            params["apikey"] = credential.api_key
        else:
            headers["apikey"] = credential.api_key
        body = {name: values[name] for name in route["body_fields"] if name in values}
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    route["method"],
                    f"https://api.securitytrails.com/v{route['version']}" + path,
                    params=params,
                    headers=headers,
                    **({"json": body} if route["body_fields"] else {}),
                )
        except httpx.HTTPError:
            # Transport exceptions may contain the v1 query key. Never echo URLs.
            raise ValueError(
                "SecurityTrails request did not complete; inspect tag task status before retrying a write"
            ) from None
        if not 200 <= response.status_code < 300:
            text = _redact(response.text[:2000], credential.api_key)
            raise ValueError(f"SecurityTrails HTTP {response.status_code}: {text}")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("SecurityTrails returned a non-JSON response") from None
        if not isinstance(data, dict) or data.get("error") or data.get("errors"):
            raise ValueError(
                "SecurityTrails returned an invalid response or error envelope"
            )
        if config.operation == "get_usage":
            if any(
                not isinstance(data.get(k), int)
                or isinstance(data.get(k), bool)
                or data[k] < 0
                for k in ("current_monthly_usage", "allowed_monthly_usage")
            ):
                raise ValueError("SecurityTrails returned incomplete account usage")
        result = {"status": "success", "data": _redact(data, credential.api_key)}
        if config.operation == "get_usage":
            result["items"] = [
                {
                    "name": f"Monthly API usage: {data['current_monthly_usage']} of {data['allowed_monthly_usage']} requests"
                }
            ]
        return result
