"""DNSFilter account, network and filtering-policy automation.

Each operation makes one documented request to the fixed DNSFilter API origin.
List operations return one provider-default page and preserve continuation metadata.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.dnsfilter.com"


class DNSFilterAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="DNSFilter API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.dnsfilter.com",
            "x-credential-instructions": "Get an API token from Account Settings in the DNSFilter dashboard. Paste the token itself, without an Authorization or Bearer prefix. NoClick sends it only to api.dnsfilter.com. The token needs permission for the operations you use.",
            "x-help-url": "https://help.dnsfilter.com/hc/en-us/articles/21169189058323-API-Tokens",
        })
    credential_type: Literal["dnsfilter_api_token"] = Field("dnsfilter_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=8192, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your DNSFilter API token")
        value = clean_secret(value, field_name="API Token", key=True)
        if not value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _NetworkFields(_Input):
    name: str = Field(..., min_length=1, max_length=500, description="Network name.")
    organization_id: int = Field(..., ge=1, description="Organization resource ID.")
    policy_ids: list[int] | None = Field(None, max_length=100, description="Policy IDs to assign. An empty list removes policy assignments.")
    physical_address: str | None = Field(None, max_length=2000)
    external_id: str | None = Field(None, max_length=500)
    ip_addresses: list[str] | None = Field(None, max_length=100, description="Public IP addresses to add to this network.")


class _PolicyFields(_Input):
    name: str = Field(..., min_length=1, max_length=500, description="Policy name.")
    organization_id: int = Field(..., ge=1, description="Organization resource ID.")
    allow_unknown_domains: bool | None = None
    google_safesearch: bool | None = None
    bing_safe_search: bool | None = None
    youtube_restricted_level: Literal["strict", "none"] | None = None
    whitelist_domains: list[str] | None = Field(None, max_length=1000, title="Allowlisted Domains")
    blacklist_domains: list[str] | None = Field(None, max_length=1000, title="Blocklisted Domains")
    blacklist_categories: list[int] | None = Field(None, max_length=1000, title="Blocked Category IDs")


class _DomainFields(_Input):
    policy_id: int = Field(..., ge=1)
    domain: str = Field(..., min_length=1, max_length=253, description="DNS domain to add or remove, without a scheme or URL path.")
    note: str = Field(..., max_length=2000, description="Required by DNSFilter, including on removal. May be empty.")


class GetCurrentUser(_Input):
    """Get current user."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class ListOrganizations(_Input):
    """Read one provider-default page; output includes provider links."""
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})
    name: str | None = None


class GetOrganization(_Input):
    """Get organization."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})
    organization_id: int = Field(..., ge=1)


class ListNetworks(_Input):
    """Read one provider-default page; output includes provider links."""
    operation: Literal["list_networks"] = Field("list_networks", json_schema_extra={"ui:hidden": True})
    search: str | None = None


class GetNetwork(_Input):
    """Get network."""
    operation: Literal["get_network"] = Field("get_network", json_schema_extra={"ui:hidden": True})
    network_id: int = Field(..., ge=1)


class CreateNetwork(_NetworkFields):
    """Create network."""
    operation: Literal["create_network"] = Field("create_network", json_schema_extra={"ui:hidden": True})


class UpdateNetwork(_NetworkFields):
    """Update network."""
    operation: Literal["update_network"] = Field("update_network", json_schema_extra={"ui:hidden": True})
    network_id: int = Field(..., ge=1)


class DeleteNetwork(_Input):
    """Delete network."""
    operation: Literal["delete_network"] = Field("delete_network", json_schema_extra={"ui:hidden": True})
    network_id: int = Field(..., ge=1)


class ListPolicies(_Input):
    """Read one provider-default page; output includes provider links."""
    operation: Literal["list_policies"] = Field("list_policies", json_schema_extra={"ui:hidden": True})
    organization_id: int | None = Field(None, ge=1)


class GetPolicy(_Input):
    """Get policy."""
    operation: Literal["get_policy"] = Field("get_policy", json_schema_extra={"ui:hidden": True})
    policy_id: int = Field(..., ge=1)


class CreatePolicy(_PolicyFields):
    """Create policy."""
    operation: Literal["create_policy"] = Field("create_policy", json_schema_extra={"ui:hidden": True})


class UpdatePolicy(_PolicyFields):
    """Update policy."""
    operation: Literal["update_policy"] = Field("update_policy", json_schema_extra={"ui:hidden": True})
    policy_id: int = Field(..., ge=1)


class DeletePolicy(_Input):
    """Delete policy."""
    operation: Literal["delete_policy"] = Field("delete_policy", json_schema_extra={"ui:hidden": True})
    policy_id: int = Field(..., ge=1)


class AddBlocklistDomain(_DomainFields):
    """Add blocklist domain."""
    operation: Literal["add_blocklist_domain"] = Field("add_blocklist_domain", json_schema_extra={"ui:hidden": True})


class RemoveBlocklistDomain(_DomainFields):
    """Remove blocklist domain."""
    operation: Literal["remove_blocklist_domain"] = Field("remove_blocklist_domain", json_schema_extra={"ui:hidden": True})


class AddAllowlistDomain(_DomainFields):
    """Add allowlist domain."""
    operation: Literal["add_allowlist_domain"] = Field("add_allowlist_domain", json_schema_extra={"ui:hidden": True})


class RemoveAllowlistDomain(_DomainFields):
    """Remove allowlist domain."""
    operation: Literal["remove_allowlist_domain"] = Field("remove_allowlist_domain", json_schema_extra={"ui:hidden": True})


class ListUserAgents(_Input):
    """Read one provider-default page; output includes provider links."""
    operation: Literal["list_user_agents"] = Field("list_user_agents", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    state: Literal["online", "offline"] | None = None
    policy_id: int | None = Field(None, ge=1)


class GetUserAgent(_Input):
    """Get user agent."""
    operation: Literal["get_user_agent"] = Field("get_user_agent", json_schema_extra={"ui:hidden": True})
    user_agent_id: UUID


DNSFilterConfig = Annotated[Union[
    GetCurrentUser,
    ListOrganizations,
    GetOrganization,
    ListNetworks,
    GetNetwork,
    CreateNetwork,
    UpdateNetwork,
    DeleteNetwork,
    ListPolicies,
    GetPolicy,
    CreatePolicy,
    UpdatePolicy,
    DeletePolicy,
    AddBlocklistDomain,
    RemoveBlocklistDomain,
    AddAllowlistDomain,
    RemoveAllowlistDomain,
    ListUserAgents,
    GetUserAgent
], Field(discriminator="operation")]


class DNSFilterNodeConfig(NodeConfig[DNSFilterConfig, DNSFilterAPITokenCredential]):
    pass


OPERATIONS = {
    "get_current_user": ('GET', '/v1/current_user', None),
    "list_organizations": ('GET', '/v1/organizations', None),
    "get_organization": ('GET', '/v1/organizations/{organization_id}', None),
    "list_networks": ('GET', '/v1/networks', None),
    "get_network": ('GET', '/v1/networks/{network_id}', None),
    "create_network": ('POST', '/v1/networks', 'network'),
    "update_network": ('PATCH', '/v1/networks/{network_id}', 'network'),
    "delete_network": ('DELETE', '/v1/networks/{network_id}', None),
    "list_policies": ('GET', '/v1/policies', None),
    "get_policy": ('GET', '/v1/policies/{policy_id}', None),
    "create_policy": ('POST', '/v1/policies', 'policy'),
    "update_policy": ('PATCH', '/v1/policies/{policy_id}', 'policy'),
    "delete_policy": ('DELETE', '/v1/policies/{policy_id}', None),
    "add_blocklist_domain": ('POST', '/v1/policies/{policy_id}/add_blacklist_domain', 'domain'),
    "remove_blocklist_domain": ('POST', '/v1/policies/{policy_id}/remove_blacklist_domain', 'domain'),
    "add_allowlist_domain": ('POST', '/v1/policies/{policy_id}/add_whitelist_domain', 'domain'),
    "remove_allowlist_domain": ('POST', '/v1/policies/{policy_id}/remove_whitelist_domain', 'domain'),
    "list_user_agents": ('GET', '/v1/user_agents', None),
    "get_user_agent": ('GET', '/v1/user_agents/{user_agent_id}', None),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


class DNSFilterNode(WorkflowNode):
    integration_type = "automation-dnsfilter"
    connection_evidence = ConnectionEvidence(noun="organizations", operation="list_organizations",
        identity_operation="get_current_user", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return DNSFilterNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a DNSFilter API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, template, wrapper = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, mode="json")
        path = template.format(**values)
        fields = {k: v for k, v in values.items() if k != "operation" and "{" + k + "}" not in template}
        body, params = None, None
        if method == "GET":
            params = fields
        elif wrapper:
            if "ip_addresses" in fields:
                fields["ip_addresses_attributes"] = [{"address": ip} for ip in fields.pop("ip_addresses")]
            body = fields if wrapper == "domain" else {wrapper: fields}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            # Do not retry a write whose delivery is uncertain.
            return {"status": "error", "error": "DNSFilter request did not complete", "write_outcome": "unknown" if method != "GET" else None}
        if not 200 <= response.status_code < 300:
            message = response.text.replace(token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code,
                "error": message or "DNSFilter rejected the request"}
        if method == "DELETE" and response.status_code == 204:
            return {"status": "success", "http_status": 204, "deletion_acknowledged": True}
        try:
            if len(response.content) > 10_000_000:
                raise ValueError("Response is too large")
            body = response.json()
            if not isinstance(body, dict) or "data" not in body or "errors" in body:
                raise ValueError("Missing data envelope")
            data = body["data"]
            listing = config.operation.startswith("list_")
            if not isinstance(data, list if listing else dict):
                raise ValueError("Unexpected data shape")
            rows = data if listing else [data]
            if any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in rows):
                raise ValueError("Unexpected record shape")
        except (ValueError, TypeError):
            return {"status": "error", "error": "DNSFilter returned an unexpected JSON response",
                "http_status": response.status_code, "write_outcome": "unknown" if method != "GET" else None}
        result = {"status": "success", "http_status": response.status_code, "data": data}
        for key in ("links", "meta", "included"):
            if key in body:
                result[key] = body[key]
        if listing:
            result["page_scope"] = "provider_default_page"
            result["items"] = [{**row, **({"name": row["attributes"]["name"]}
                if isinstance(row.get("attributes"), dict) and "name" in row["attributes"] else {})} for row in data]
        return _redact(result, token)
