"""IPinfo intelligence and report operations pinned to the official v1 OpenAPI contract.

Product access depends on the supplied token's plan. No IPinfo account mutations
are published in this contract; POST operations enrich IPs or generate reports.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class IpinfoIoTokenCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="Ipinfo API Token",
        json_schema_extra={
            "x-credential-url": "https://ipinfo.io/account/token",
            "x-credential-instructions": "Paste your IPinfo API token from your account dashboard. NoClick sends it as a bearer token to IPinfo only. The token information read verifies acceptance and shows plan limits; it does not verify a person's identity. Specialized products require the corresponding IPinfo subscription.",
        })
    credential_type: Literal["ipinfo_io_api_token"] = Field("ipinfo_io_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without an authorization header")
        return value


# IPinfo's own MCP server: agents get its tools through a person's IPinfo sign-in.
IpinfoIoMcpCredential = mcp_credential("ipinfo_io", "https://mcp.ipinfo.io/", app="IPinfo")
IpinfoIoCredential = Union[IpinfoIoTokenCredential, IpinfoIoMcpCredential]


def ip_value(value):
    if not isinstance(value, str) or "%" in value:
        raise ValueError("Use a single IPv4 or IPv6 address")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise ValueError("Use a single IPv4 or IPv6 address") from None


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class IpInput(Input):
    ip: str = Field(..., description="A single IPv4 or IPv6 address, for example 8.8.8.8.")
    _ip = field_validator("ip", mode="before")(ip_value)


class AsnInput(Input):
    asn: int = Field(..., ge=1, le=4294967295, description="ASN number without the AS prefix, for example 15169.")


class DomainInput(Input):
    domain: str = Field(..., description="Domain name only, for example google.com.")

    @field_validator("domain")
    @classmethod
    def domain_name(cls, value):
        if len(value) > 253 or not re.fullmatch(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", value):
            raise ValueError("Use a domain name without a URL or path")
        return value.lower()


class DomainsInput(IpInput):
    page: int = Field(0, ge=0, description="Zero-based page; one page is returned per execution.")
    limit: int = Field(100, ge=1, le=1000)


class BatchInput(Input):
    ips: list[str] = Field(..., min_length=1, max_length=1000,
        description="IPv4 or IPv6 addresses to enrich. One legacy full lookup per address, at most 1000.")

    @field_validator("ips")
    @classmethod
    def addresses(cls, values):
        return [ip_value(value) for value in values]


class ReportInput(Input):
    ips: list[str] = Field(..., min_length=1, max_length=500000,
        description="IP addresses to include in the report. Sent as newline-separated text to IPinfo.")

    @field_validator("ips")
    @classmethod
    def addresses(cls, values):
        return [ip_value(value) for value in values]


class GetTokenInfo(Input):
    """Get token info. Product access depends on the token plan."""
    operation: Literal["get_token_info"] = Field("get_token_info", json_schema_extra={"ui:hidden": True})


class GetCurrentIpInfo(Input):
    """Get current ip info. Product access depends on the token plan."""
    operation: Literal["get_current_ip_info"] = Field("get_current_ip_info", json_schema_extra={"ui:hidden": True})


class GetIpInfo(IpInput):
    """Get ip info. Product access depends on the token plan."""
    operation: Literal["get_ip_info"] = Field("get_ip_info", json_schema_extra={"ui:hidden": True})


class GetLiteIpInfo(IpInput):
    """Get lite ip info. Product access depends on the token plan."""
    operation: Literal["get_lite_ip_info"] = Field("get_lite_ip_info", json_schema_extra={"ui:hidden": True})


class GetCurrentLiteInfo(Input):
    """Get current lite info. Product access depends on the token plan."""
    operation: Literal["get_current_lite_info"] = Field("get_current_lite_info", json_schema_extra={"ui:hidden": True})


class GetLookupIpInfo(IpInput):
    """Get lookup ip info. Product access depends on the token plan."""
    operation: Literal["get_lookup_ip_info"] = Field("get_lookup_ip_info", json_schema_extra={"ui:hidden": True})


class GetCurrentLookupInfo(Input):
    """Get current lookup info. Product access depends on the token plan."""
    operation: Literal["get_current_lookup_info"] = Field("get_current_lookup_info", json_schema_extra={"ui:hidden": True})


class GetAsn(AsnInput):
    """Get asn. Product access depends on the token plan."""
    operation: Literal["get_asn"] = Field("get_asn", json_schema_extra={"ui:hidden": True})


class GetCompany(IpInput):
    """Get company. Product access depends on the token plan."""
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"ui:hidden": True})


class GetCarrier(IpInput):
    """Get carrier. Product access depends on the token plan."""
    operation: Literal["get_carrier"] = Field("get_carrier", json_schema_extra={"ui:hidden": True})


class GetRanges(DomainInput):
    """Get ranges. Product access depends on the token plan."""
    operation: Literal["get_ranges"] = Field("get_ranges", json_schema_extra={"ui:hidden": True})


class GetHostedDomains(DomainsInput):
    """Get hosted domains. Product access depends on the token plan."""
    operation: Literal["get_hosted_domains"] = Field("get_hosted_domains", json_schema_extra={"ui:hidden": True})


class GetAbuseContact(IpInput):
    """Get abuse contact. Product access depends on the token plan."""
    operation: Literal["get_abuse_contact"] = Field("get_abuse_contact", json_schema_extra={"ui:hidden": True})


class GetPrivacy(IpInput):
    """Get privacy. Product access depends on the token plan."""
    operation: Literal["get_privacy"] = Field("get_privacy", json_schema_extra={"ui:hidden": True})


class GetResidentialProxy(IpInput):
    """Get residential proxy. Product access depends on the token plan."""
    operation: Literal["get_residential_proxy"] = Field("get_residential_proxy", json_schema_extra={"ui:hidden": True})


class GetPrivacyExtended(IpInput):
    """Get privacy extended. Product access depends on the token plan."""
    operation: Literal["get_privacy_extended"] = Field("get_privacy_extended", json_schema_extra={"ui:hidden": True})


class GetPlace(IpInput):
    """Get place. Product access depends on the token plan."""
    operation: Literal["get_place"] = Field("get_place", json_schema_extra={"ui:hidden": True})


class BatchEnrich(BatchInput):
    """Batch enrich. Product access depends on the token plan."""
    operation: Literal["batch_enrich"] = Field("batch_enrich", json_schema_extra={"ui:hidden": True})


class SummarizeIps(ReportInput):
    """Summarize ips. Product access depends on the token plan."""
    operation: Literal["summarize_ips"] = Field("summarize_ips", json_schema_extra={"ui:hidden": True})


class MapIps(ReportInput):
    """Map ips. Product access depends on the token plan."""
    operation: Literal["map_ips"] = Field("map_ips", json_schema_extra={"ui:hidden": True})


IpinfoIoOperation = Annotated[Union[
    GetTokenInfo, GetCurrentIpInfo, GetIpInfo, GetLiteIpInfo, GetCurrentLiteInfo, GetLookupIpInfo, GetCurrentLookupInfo, GetAsn, GetCompany, GetCarrier, GetRanges, GetHostedDomains, GetAbuseContact, GetPrivacy, GetResidentialProxy, GetPrivacyExtended, GetPlace, BatchEnrich, SummarizeIps, MapIps
], Field(discriminator="operation")]


class IpinfoIoConfig(NodeConfig[IpinfoIoOperation, IpinfoIoCredential]):
    pass


ROUTES = {'get_token_info': ('GET', '/me', 'https://ipinfo.io'), 'get_current_ip_info': ('GET', '/', 'https://ipinfo.io'), 'get_ip_info': ('GET', '/{ip}', 'https://ipinfo.io'), 'get_lite_ip_info': ('GET', '/lite/{ip}', 'https://api.ipinfo.io'), 'get_current_lite_info': ('GET', '/lite/me', 'https://api.ipinfo.io'), 'get_lookup_ip_info': ('GET', '/lookup/{ip}', 'https://api.ipinfo.io'), 'get_current_lookup_info': ('GET', '/lookup/me', 'https://api.ipinfo.io'), 'get_asn': ('GET', '/AS{asn}', 'https://ipinfo.io'), 'get_company': ('GET', '/{ip}/company', 'https://ipinfo.io'), 'get_carrier': ('GET', '/{ip}/carrier', 'https://ipinfo.io'), 'get_ranges': ('GET', '/ranges/{domain}', 'https://ipinfo.io'), 'get_hosted_domains': ('GET', '/domains/{ip}', 'https://ipinfo.io'), 'get_abuse_contact': ('GET', '/{ip}/abuse', 'https://ipinfo.io'), 'get_privacy': ('GET', '/{ip}/privacy', 'https://ipinfo.io'), 'get_residential_proxy': ('GET', '/resproxy/{ip}', 'https://ipinfo.io'), 'get_privacy_extended': ('GET', '/{ip}/privacy_extended', 'https://ipinfo.io'), 'get_place': ('GET', '/places/{ip}', 'https://api.ipinfo.io'), 'batch_enrich': ('POST', '/batch', 'https://ipinfo.io'), 'summarize_ips': ('POST', '/tools/summarize-ips', 'https://ipinfo.io'), 'map_ips': ('POST', '/tools/map', 'https://ipinfo.io')}


def redact(value, token):
    if isinstance(value, dict):
        return {key: redact(item, token) for key, item in value.items() if key.lower() not in {"token", "api_token", "access_token"}}
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class IpinfoIoNode(WorkflowNode):
    integration_type = "automation-ipinfo-io"
    credential_provider_labels = {"ipinfo_io": "IPinfo Account"}
    connection_evidence = ConnectionEvidence(operation="get_token_info", noun="token limits", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return IpinfoIoConfig

    @classmethod
    def parse_config(cls, config_data):
        # Refuse explicit foreign tags before the shared credential reconciliation.
        raw = config_data.get("credentials")
        if raw is not None and (not isinstance(raw, dict) or raw.get("credential_type") != "ipinfo_io_api_token"):
            raise ValueError("Attach an IPinfo API token credential")
        return super().parse_config(runtime_config_view(config_data, IpinfoIoConfig))

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an IPinfo API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, route, origin = ROUTES[config.operation]
        for key in ("ip", "asn", "domain"):
            if hasattr(config, key):
                route = route.replace("{" + key + "}", quote(str(getattr(config, key)), safe=""))
        kwargs = {}
        if isinstance(config, DomainsInput):
            kwargs["params"] = {"page": config.page, "limit": config.limit}
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if isinstance(config, BatchInput):
            kwargs["json"] = config.ips
        elif isinstance(config, ReportInput):
            kwargs["content"] = "\n".join(config.ips) + "\n"
            kwargs["params"] = {"cli": 1}
            headers["Content-Type"] = "text/plain"
        try:
            async with guarded_async_client(timeout=60.0, follow_redirects=False) as client:
                response = await client.request(method, origin + route, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise ValueError("IPinfo request could not be completed; check report history before retrying a report") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("IPinfo returned an unexpected non-JSON response") from None
        data = redact(data, token)
        if not 200 <= response.status_code < 300:
            return {"status": "error", "success": False, "http_status": response.status_code, "error": data}
        if not isinstance(data, dict):
            raise ValueError("IPinfo returned an unexpected response shape")
        if data.get("error"):
            return {"status": "error", "success": False, "http_status": response.status_code, "error": data["error"]}
        if isinstance(config, GetTokenInfo) and not (isinstance(data.get("requests"), dict) and isinstance(data.get("features"), dict)):
            raise ValueError("IPinfo token limits response is incomplete")
        output = {"status": "success", "success": True, "operation": config.operation,
            "http_status": response.status_code, "data": data}
        await self.emit(output)
        return output
