"""WhoisFreaks domain and IP intelligence API, pinned to the published v1 contract.

JSON lookups return one provider response, including provider paging metadata.
API-key rotation generates a secondary key and requires provider enablement.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE_URL = "https://api.whoisfreaks.com"


class WhoisfreaksAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Whoisfreaks API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "api_key",
            "x-credential-url": "https://billing.whoisfreaks.com",
            "x-credential-instructions": "Paste your API key from the WhoisFreaks billing dashboard. Account usage verifies the key without a domain lookup. Lookups consume provider credits; some APIs need a subscription.",
        },
    )
    credential_type: Literal["whoisfreaks_api_key"] = Field(
        "whoisfreaks_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetLiveWhoisConfig(_Input):
    operation: Literal["get_live_whois"] = Field(
        "get_live_whois",
        title="Live WHOIS Lookup",
        description="Live WHOIS Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domainName: str = Field(..., title="Domain Name", min_length=1)


class BulkWhoisConfig(_Input):
    operation: Literal["bulk_whois"] = Field(
        "bulk_whois",
        title="Bulk WHOIS Lookup",
        description="Bulk WHOIS Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domainNames: list[str] = Field(
        ..., title="Domain Names", min_length=1, max_length=100
    )


class GetLiveDnsConfig(_Input):
    operation: Literal["get_live_dns"] = Field(
        "get_live_dns",
        title="Live DNS Lookup",
        description="Live DNS Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domainName: str | None = Field(None, title="Domain Name")
    ipAddress: str | None = Field(
        None, title="Ip Address", description="Use for PTR lookups"
    )
    type: str = Field(
        "all",
        title="Type",
        description="all or comma-separated: A,MX,NS,TXT,SOA,SPF,AAAA,CNAME",
    )

    @model_validator(mode="after")
    def target(self):
        if not (self.domainName or self.ipAddress):
            raise ValueError("Provide at least one domain name or IP address")
        return self


class GetHistoricalDnsConfig(_Input):
    operation: Literal["get_historical_dns"] = Field(
        "get_historical_dns",
        title="Historical DNS Lookup",
        description="Historical DNS Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domainName: str = Field(..., title="Domain Name", min_length=1)
    type: str = Field("all", title="Type")
    page: int = Field(1, title="Page", strict=True, ge=1)


class GetReverseDnsConfig(_Input):
    operation: Literal["get_reverse_dns"] = Field(
        "get_reverse_dns",
        title="Reverse DNS Lookup",
        description="Reverse DNS Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    value: str = Field(
        ..., title="Value", min_length=1, description="IP, CIDR, or record value"
    )
    type: Literal["a", "mx", "cname", "ns", "aaaa", "txt", "soa"] = Field(
        ..., title="Type"
    )
    exact: bool = Field(True, title="Exact", strict=True)
    page: int = Field(1, title="Page", strict=True, ge=1)


class BulkDnsConfig(_Input):
    operation: Literal["bulk_dns"] = Field(
        "bulk_dns",
        title="Bulk DNS Lookup",
        description="Bulk DNS Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    type: str = Field("all", title="Type")
    domainNames: list[str] | None = Field(
        None, title="Domain Names", min_length=1, max_length=100
    )
    ipAddresses: list[str] | None = Field(
        None, title="Ip Addresses", min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def target(self):
        if not (self.domainNames or self.ipAddresses):
            raise ValueError("Provide at least one domain name or IP address")
        return self


class GetDomainAvailabilityConfig(_Input):
    operation: Literal["get_domain_availability"] = Field(
        "get_domain_availability",
        title="Domain Availability Check with Suggestions",
        description="Domain Availability Check with Suggestions. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domain: str = Field(
        ..., title="Domain", min_length=1, description="The domain name to check"
    )
    sug: bool = Field(
        False,
        title="Sug",
        strict=True,
        description="Whether to return TLD suggestions alongside the queried domain.",
    )
    count: int = Field(
        5,
        title="Count",
        strict=True,
        ge=1,
        le=100,
        description="Number of TLD suggestions to return when sug=true. Maximum is 100.",
    )


class BulkDomainAvailabilityConfig(_Input):
    operation: Literal["bulk_domain_availability"] = Field(
        "bulk_domain_availability",
        title="Bulk Domain Availability Check",
        description="Bulk Domain Availability Check. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domain: str | None = Field(
        None,
        title="Domain",
        description="Required for TLD-mode bulk check (base domain).",
    )
    domainNames: list[str] | None = Field(
        None,
        title="Domain Names",
        min_length=1,
        max_length=100,
        description="Mode 1: list of full domain names. Cannot be used with tld.",
    )
    tld: list[str] | None = Field(
        None,
        title="Tld",
        min_length=1,
        max_length=100,
        description="Mode 2: TLDs to check against the domain query param. Cannot be used with domainNames.",
    )

    @model_validator(mode="after")
    def target(self):
        if bool(self.domainNames) == bool(self.tld):
            raise ValueError("Provide either full domain names or TLDs")
        if self.tld and not self.domain:
            raise ValueError("A base domain is required with TLDs")
        if self.domainNames and self.domain:
            raise ValueError("A base domain is only used in TLD mode")
        return self


class GetDomainTyposConfig(_Input):
    operation: Literal["get_domain_typos"] = Field(
        "get_domain_typos",
        title="Typosquatting Lookup",
        description="Typosquatting Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    keyword: str | None = Field(None, title="Keyword")
    pattern: str | None = Field(None, title="Pattern")
    pageToken: str | None = Field(None, title="Page Token")

    @model_validator(mode="after")
    def target(self):
        if bool(self.keyword) == bool(self.pattern):
            raise ValueError("Provide either a keyword or a wildcard pattern")
        return self


class GetSslCertificateConfig(_Input):
    operation: Literal["get_ssl_certificate"] = Field(
        "get_ssl_certificate",
        title="SSL Certificate Lookup",
        description="SSL Certificate Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domainName: str = Field(..., title="Domain Name", min_length=1)
    chain: bool = Field(False, title="Chain", strict=True)
    sslRaw: bool = Field(False, title="Ssl Raw", strict=True)


class GetIpGeolocationConfig(_Input):
    operation: Literal["get_ip_geolocation"] = Field(
        "get_ip_geolocation",
        title="IP Geolocation Lookup",
        description="IP Geolocation Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    ip: str = Field(..., title="Ip", min_length=1)


class BulkIpGeolocationConfig(_Input):
    operation: Literal["bulk_ip_geolocation"] = Field(
        "bulk_ip_geolocation",
        title="Bulk IP Geolocation",
        description="Bulk IP Geolocation. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    ips: list[str] = Field(..., title="Ips", min_length=1, max_length=100)


class GetSubdomainsConfig(_Input):
    operation: Literal["get_subdomains"] = Field(
        "get_subdomains",
        title="Subdomains Lookup",
        description="Subdomains Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domain: str = Field(..., title="Domain", min_length=1)
    after: str | None = Field(
        None,
        title="After",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        json_schema_extra={"format": "date"},
    )
    before: str | None = Field(
        None,
        title="Before",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        json_schema_extra={"format": "date"},
    )
    status: Literal["active", "inactive"] | None = Field(None, title="Status")
    page: int = Field(1, title="Page", strict=True, ge=1)


class GetIpReputationConfig(_Input):
    operation: Literal["get_ip_reputation"] = Field(
        "get_ip_reputation",
        title="IP Reputation Lookup",
        description="IP Reputation Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    ip: str = Field(..., title="Ip", min_length=1)


class BulkIpReputationConfig(_Input):
    operation: Literal["bulk_ip_reputation"] = Field(
        "bulk_ip_reputation",
        title="Bulk IP Reputation",
        description="Bulk IP Reputation. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    ips: list[str] = Field(..., title="Ips", min_length=1, max_length=100)


class GetDomainReputationConfig(_Input):
    operation: Literal["get_domain_reputation"] = Field(
        "get_domain_reputation",
        title="Domain Reputation Lookup",
        description="Domain Reputation Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domainName: str = Field(
        ..., title="Domain Name", min_length=1, description="The domain name to assess"
    )


class GetAsnWhoisConfig(_Input):
    operation: Literal["get_asn_whois"] = Field(
        "get_asn_whois",
        title="ASN WHOIS Lookup",
        description="ASN WHOIS Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    asn: str = Field(..., title="Asn", min_length=1)


class GetIpWhoisConfig(_Input):
    operation: Literal["get_ip_whois"] = Field(
        "get_ip_whois",
        title="IP WHOIS Lookup",
        description="IP WHOIS Lookup. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    ip: str = Field(..., title="Ip", min_length=1)


class RotateApiKeyConfig(_Input):
    operation: Literal["rotate_api_key"] = Field(
        "rotate_api_key",
        title="Rotate API Key",
        description="Generate a secondary API key. WhoisFreaks must first enable rotation for your account. The result contains a secret; store it securely. Does not update your saved NoClick credential.",
        json_schema_extra={"ui:hidden": True},
    )


class GetAccountUsageConfig(_Input):
    operation: Literal["get_account_usage"] = Field(
        "get_account_usage",
        title="Account Usage",
        description="Account Usage. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )


class GetHistoricalWhoisConfig(_Input):
    operation: Literal["get_historical_whois"] = Field(
        "get_historical_whois",
        title="Historical WHOIS records for a domain",
        description="Historical WHOIS records for a domain. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    domainName: str = Field(
        ...,
        title="Domain Name",
        min_length=1,
        description="Domain to fetch historical WHOIS records for",
    )


class GetReverseWhoisConfig(_Input):
    operation: Literal["get_reverse_whois"] = Field(
        "get_reverse_whois",
        title="Reverse WHOIS lookup by keyword",
        description="Reverse WHOIS lookup by keyword. Returns one response; use provider pagination fields for subsequent pages.",
        json_schema_extra={"ui:hidden": True},
    )
    keyword: str = Field(
        ...,
        title="Keyword",
        min_length=1,
        description="Keyword to search across WHOIS records",
    )
    page: int | None = Field(
        None, title="Page", strict=True, ge=1, description="Page number"
    )


WhoisfreaksConfig = Annotated[
    Union[
        GetLiveWhoisConfig,
        BulkWhoisConfig,
        GetLiveDnsConfig,
        GetHistoricalDnsConfig,
        GetReverseDnsConfig,
        BulkDnsConfig,
        GetDomainAvailabilityConfig,
        BulkDomainAvailabilityConfig,
        GetDomainTyposConfig,
        GetSslCertificateConfig,
        GetIpGeolocationConfig,
        BulkIpGeolocationConfig,
        GetSubdomainsConfig,
        GetIpReputationConfig,
        BulkIpReputationConfig,
        GetDomainReputationConfig,
        GetAsnWhoisConfig,
        GetIpWhoisConfig,
        RotateApiKeyConfig,
        GetAccountUsageConfig,
        GetHistoricalWhoisConfig,
        GetReverseWhoisConfig,
    ],
    Field(discriminator="operation"),
]


class WhoisfreaksFullConfig(NodeConfig[WhoisfreaksConfig, WhoisfreaksAPIKeyCredential]):
    pass


ROUTES = {
    "get_live_whois": {
        "method": "GET",
        "path": "/v2.0/whois/live",
        "query": ["domainName"],
        "body": [],
        "format": True,
    },
    "bulk_whois": {
        "method": "POST",
        "path": "/v2.0/bulkwhois/live",
        "query": [],
        "body": ["domainNames"],
        "format": True,
    },
    "get_live_dns": {
        "method": "GET",
        "path": "/v2.0/dns/live",
        "query": ["domainName", "ipAddress", "type"],
        "body": [],
        "format": True,
    },
    "get_historical_dns": {
        "method": "GET",
        "path": "/v2.0/dns/historical",
        "query": ["domainName", "type", "page"],
        "body": [],
        "format": True,
    },
    "get_reverse_dns": {
        "method": "GET",
        "path": "/v2.1/dns/reverse",
        "query": ["value", "type", "exact", "page"],
        "body": [],
        "format": True,
    },
    "bulk_dns": {
        "method": "POST",
        "path": "/v2.0/dns/bulk/live",
        "query": ["type"],
        "body": ["domainNames", "ipAddresses"],
        "format": True,
    },
    "get_domain_availability": {
        "method": "GET",
        "path": "/v2.0/domain/availability",
        "query": ["domain", "sug", "count"],
        "body": [],
        "format": True,
    },
    "bulk_domain_availability": {
        "method": "POST",
        "path": "/v2.0/domain/availability",
        "query": ["domain"],
        "body": ["domainNames", "tld"],
        "format": True,
    },
    "get_domain_typos": {
        "method": "GET",
        "path": "/v3.0/domain/typos",
        "query": ["keyword", "pattern", "pageToken"],
        "body": [],
        "format": False,
    },
    "get_ssl_certificate": {
        "method": "GET",
        "path": "/v1.0/ssl/live",
        "query": ["domainName", "chain", "sslRaw"],
        "body": [],
        "format": True,
    },
    "get_ip_geolocation": {
        "method": "GET",
        "path": "/v1.0/geolocation",
        "query": ["ip"],
        "body": [],
        "format": False,
    },
    "bulk_ip_geolocation": {
        "method": "POST",
        "path": "/v1.0/geolocation",
        "query": [],
        "body": ["ips"],
        "format": False,
    },
    "get_subdomains": {
        "method": "GET",
        "path": "/v1.0/subdomains",
        "query": ["domain", "after", "before", "status", "page"],
        "body": [],
        "format": True,
    },
    "get_ip_reputation": {
        "method": "GET",
        "path": "/v1.0/security",
        "query": ["ip"],
        "body": [],
        "format": False,
    },
    "bulk_ip_reputation": {
        "method": "POST",
        "path": "/v1.0/security",
        "query": [],
        "body": ["ips"],
        "format": False,
    },
    "get_domain_reputation": {
        "method": "GET",
        "path": "/v1/domain/security",
        "query": ["domainName"],
        "body": [],
        "format": True,
    },
    "get_asn_whois": {
        "method": "GET",
        "path": "/v2.0/asn-whois",
        "query": ["asn"],
        "body": [],
        "format": True,
    },
    "get_ip_whois": {
        "method": "GET",
        "path": "/v1.0/ip-whois",
        "query": ["ip"],
        "body": [],
        "format": True,
    },
    "rotate_api_key": {
        "method": "GET",
        "path": "/v1.0/api-key/rotate",
        "query": [],
        "body": [],
        "format": False,
    },
    "get_account_usage": {
        "method": "GET",
        "path": "/v1.0/whoisapi/usage",
        "query": [],
        "body": [],
        "format": False,
    },
    "get_historical_whois": {
        "method": "GET",
        "path": "/v2.0/whois/history",
        "query": ["domainName"],
        "body": [],
        "format": True,
    },
    "get_reverse_whois": {
        "method": "GET",
        "path": "/v2.0/whois/reverse",
        "query": ["keyword", "page"],
        "body": [],
        "format": True,
    },
}


def _redact(value, key):
    if isinstance(value, dict):
        return {
            k: _redact(v, key)
            for k, v in value.items()
            if k.lower() not in {"apikey", "api_key"}
        }
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value.replace(key, "[redacted]") if isinstance(value, str) else value


class WhoisfreaksNode(WorkflowNode):
    integration_type = "automation-whoisfreaks"
    connection_evidence = ConnectionEvidence(
        operation="get_account_usage", noun="API credit balances", label_keys=("name",)
    )

    @classmethod
    def get_config_model(cls):
        return WhoisfreaksFullConfig

    async def execute(self, inputs):
        if (
            not isinstance(self.config, WhoisfreaksFullConfig)
            or not self.config.credentials
        ):
            raise ValueError("Connect a WhoisFreaks API key")
        config = self.config.config
        key = self.config.credentials.api_key
        route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        params = {name: values[name] for name in route["query"] if name in values}
        params = {
            k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()
        }
        params["apiKey"] = key
        if route["format"]:
            params["format"] = "json"
        kwargs = {
            "params": params,
            "headers": {
                "Accept": "text/plain"
                if config.operation == "rotate_api_key"
                else "application/json"
            },
        }
        if route["body"]:
            kwargs["json"] = {
                name: values[name] for name in route["body"] if name in values
            }
        try:
            async with guarded_async_client(
                timeout=60, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    route["method"], BASE_URL + route["path"], **kwargs
                )
            if response.status_code != 200:
                # HTTP errors can echo the key-bearing request URL. Never expose it.
                message = "WhoisFreaks request failed"
                try:
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get("message"), str):
                        message = body["message"].replace(key, "[redacted]")
                except ValueError:
                    pass
                return {
                    "status": "error",
                    "http_status": response.status_code,
                    "error": message,
                }
            if config.operation == "rotate_api_key":
                if not response.text.strip():
                    raise ValueError("Empty key rotation response")
                return {
                    "status": "success",
                    "result": response.text,
                    "credential_updated": False,
                }
            body = response.json()
            if not isinstance(body, (dict, list)) or not body:
                raise ValueError("Unexpected empty response")
            if isinstance(body, dict) and (
                body.get("status") is False or body.get("error")
            ):
                return {
                    "status": "error",
                    "error": _redact(
                        body.get("message")
                        or body.get("error")
                        or "WhoisFreaks rejected the request",
                        key,
                    ),
                }
            data = _redact(body, key)
            result = {"status": "success", "data": data}
            if config.operation == "get_account_usage":
                if not isinstance(body, dict) or not any(
                    isinstance(body.get(k), dict) and body[k]
                    for k in ("apiCredits", "apiSubscription")
                ):
                    raise ValueError("Missing account usage")
                result["items"] = [
                    {"name": f"{group}: {name} = {value}"}
                    for group in ("apiCredits", "apiSubscription")
                    for name, value in body.get(group, {}).items()
                    if isinstance(value, (str, int, float, bool))
                ]
            return result
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "WhoisFreaks could not be reached"}
        except ValueError:
            return {
                "status": "error",
                "error": "WhoisFreaks returned an unexpected response",
            }
