"""Globalping v1 measurements with a user-supplied dashboard bearer token.

Contract: https://api.globalping.io/v1/spec.yaml (1.0.0).
Creation is asynchronous: retrieve the returned ID in a later workflow step.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.globalping.io/v1"


class GlobalpingTokenCredential(BaseModel):
    model_config = ConfigDict(title="Globalping API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dash.globalping.io/tokens",
            "x-credential-instructions": "Create a token in the Globalping Dashboard and paste it here. NoClick sends it as a bearer token to api.globalping.io. Measurements can spend your credits after the free hourly allowance. Connection testing reads your authenticated rate limits; Globalping does not expose an account identity endpoint.",
        })
    credential_type: Literal["globalping_api_token"] = Field("globalping_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Measurement(_Input):
    target: str = Field(..., min_length=1, max_length=253,
        description="Public hostname, IPv4 or IPv6 address, without a URL scheme or path.")
    location: Optional[str] = Field(None, min_length=1, max_length=500,
        description="Globalping magic location filter, for example Berlin+Germany or AS13335.")
    reuse_measurement_id: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9_-]{1,128}$",
        description="Reuse the probes of an earlier measurement instead of a location filter.")
    limit: int = Field(1, ge=1, le=500, description="Maximum probes; each probe consumes a rate-limit point or credit.")
    timeout: Optional[int] = Field(None, ge=5, le=30, description="Probe-side timeout in seconds.")
    ip_version: Literal[4, 6] = Field(4, title="IP version")

    @field_validator("target")
    @classmethod
    def target_value(cls, value):
        if any(c.isspace() for c in value) or any(c in value for c in "/?#@"):
            raise ValueError("Use a public hostname or IP address without a URL scheme or path")
        return value

    @model_validator(mode="after")
    def locations_exclusive(self):
        if self.location and self.reuse_measurement_id:
            raise ValueError("Choose either a location filter or previous measurement probes")
        return self


class Ping(_Measurement):
    """Create an ICMP ping measurement."""
    operation: Literal["create_ping"] = "create_ping"
    packets: int = Field(3, ge=1, le=16)


class TcpPing(_Measurement):
    """Create a TCP ping measurement to test a service port."""
    operation: Literal["create_tcp_ping"] = "create_tcp_ping"
    packets: int = Field(3, ge=1, le=16)
    port: int = Field(80, ge=0, le=65535)


class Traceroute(_Measurement):
    """Create a traceroute measurement."""
    operation: Literal["create_traceroute"] = "create_traceroute"
    protocol: Literal["ICMP", "TCP", "UDP"] = "ICMP"
    port: Optional[int] = Field(None, ge=0, le=65535, description="Destination port for TCP.")


class Mtr(_Measurement):
    """Create an MTR measurement with per-hop packet statistics."""
    operation: Literal["create_mtr"] = "create_mtr"
    protocol: Literal["ICMP", "TCP", "UDP"] = "ICMP"
    packets: int = Field(3, ge=1, le=16)
    port: Optional[int] = Field(None, ge=0, le=65535, description="Destination port for TCP or UDP.")


class _Dns(_Measurement):
    query_type: Literal["A", "AAAA", "ANY", "CNAME", "DNSKEY", "DS", "HTTPS", "MX", "NS", "NSEC", "PTR", "RRSIG", "SOA", "TXT", "SRV", "SVCB"] = "A"
    protocol: Literal["TCP", "UDP"] = "UDP"
    resolver: Optional[str] = Field(None, max_length=253, description="Custom DNS resolver IP address.")
    port: int = Field(53, ge=0, le=65535)


class Dns(_Dns):
    """Create a DNS lookup measurement."""
    operation: Literal["create_dns"] = "create_dns"


class DnsTrace(_Dns):
    """Trace DNS delegation from root servers to the target."""
    operation: Literal["create_dns_trace"] = "create_dns_trace"


class Http(_Measurement):
    """Create an HTTP measurement for response headers, status and timings."""
    operation: Literal["create_http"] = "create_http"
    protocol: Literal["HTTP", "HTTPS", "HTTP2"] = "HTTPS"
    request_method: Literal["HEAD", "GET", "OPTIONS"] = "HEAD"
    path: str = Field("/", max_length=2000)
    query: Optional[str] = Field(None, max_length=2000, description="Query string without a leading question mark.")
    port: Optional[int] = Field(None, ge=0, le=65535)


class GetMeasurement(_Input):
    """Read current status and results once; leave at least 500ms between reads."""
    operation: Literal["get_measurement"] = "get_measurement"
    measurement_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,128}$")


class ListProbes(_Input):
    """List all currently online public probes and their locations."""
    operation: Literal["list_probes"] = "list_probes"


class GetLimits(_Input):
    """Read authenticated rate limits and available credits."""
    operation: Literal["get_limits"] = "get_limits"


# Globalping's own MCP server: agents get its tools through a person's Globalping sign-in.
GlobalpingMcpCredential = mcp_credential("globalping", "https://mcp.globalping.dev/mcp", app="Globalping")
GlobalpingCredential = Union[GlobalpingTokenCredential, GlobalpingMcpCredential]


GlobalpingConfig = Annotated[Union[Ping, TcpPing, Traceroute, Mtr, Dns, DnsTrace, Http,
    GetMeasurement, ListProbes, GetLimits], Field(discriminator="operation")]


class GlobalpingFullConfig(NodeConfig[GlobalpingConfig, GlobalpingCredential]):
    pass


class GlobalpingNode(WorkflowNode):
    integration_type = "automation-globalping"
    credential_provider_labels = {"globalping": "Globalping Account"}
    connection_evidence = ConnectionEvidence(operation="get_limits", noun="Globalping authenticated rate limits", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return GlobalpingFullConfig

    @staticmethod
    def measurement_body(config):
        kind = {"create_ping": "ping", "create_tcp_ping": "ping", "create_traceroute": "traceroute",
            "create_mtr": "mtr", "create_dns": "dns", "create_dns_trace": "dns", "create_http": "http"}[config.operation]
        body = {"type": kind, "target": config.target, "limit": config.limit}
        if config.timeout is not None:
            body["timeout"] = config.timeout
        if config.reuse_measurement_id:
            body["locations"] = config.reuse_measurement_id
        elif config.location:
            body["locations"] = [{"magic": config.location}]
        options = {"ipVersion": config.ip_version}
        for name in ("packets", "protocol", "port", "resolver"):
            value = getattr(config, name, None)
            if value is not None:
                options[name] = value
        if isinstance(config, (Ping, TcpPing)):
            options["protocol"] = "TCP" if isinstance(config, TcpPing) else "ICMP"
        if isinstance(config, _Dns):
            options.update(query={"type": config.query_type}, trace=isinstance(config, DnsTrace))
        if isinstance(config, Http):
            options["request"] = {"method": config.request_method, "path": config.path}
            if config.query is not None:
                options["request"]["query"] = config.query
        body["measurementOptions"] = options
        return body

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Globalping API token")
        if isinstance(config, _Measurement):
            method, path, expected = "POST", "/measurements", 202
            kwargs = {"json": self.measurement_body(config)}
        else:
            method, expected, kwargs = "GET", 200, {}
            path = "/measurements/" + quote(config.measurement_id, safe="") if isinstance(config, GetMeasurement) else "/probes" if isinstance(config, ListProbes) else "/limits"
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json",
            "User-Agent": "NoClick/1.0 (+https://noclick.com)", "Accept-Encoding": "gzip"}
        try:
            async with guarded_async_client(timeout=40, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers, **kwargs)
            if response.status_code != expected:
                message = "Globalping returned HTTP " + str(response.status_code)
                try:
                    error = response.json().get("error", {})
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"]
                except (ValueError, AttributeError):
                    pass
                return {"status": "error", "http_status": response.status_code,
                    "error": message.replace(credential.api_token, "[redacted]"),
                    "retry_after": response.headers.get("Retry-After")}
            body = response.json()
            if isinstance(config, ListProbes):
                if not isinstance(body, list) or any(not isinstance(item, dict) or not isinstance(item.get("location"), dict) for item in body):
                    raise ValueError("Expected a Globalping probes array")
            elif not isinstance(body, dict) or "error" in body:
                raise ValueError("Expected a Globalping response object")
            elif isinstance(config, _Measurement):
                if not isinstance(body.get("id"), str) or not body["id"] or type(body.get("probesCount")) is not int:
                    raise ValueError("Expected a measurement ID and probe count")
            elif isinstance(config, GetMeasurement):
                if body.get("id") != config.measurement_id or body.get("status") not in {"in-progress", "finished"} or not isinstance(body.get("results"), list):
                    raise ValueError("Expected the requested measurement status and results")
            elif isinstance(config, GetLimits):
                rate = body.get("rateLimit", {}).get("measurements", {}).get("create", {})
                if rate.get("type") != "user":
                    return {"status": "error", "error": "Globalping did not confirm authenticated user limits"}
                if any(type(rate.get(key)) is not int for key in ("limit", "remaining", "reset")):
                    raise ValueError("Expected Globalping user rate limits")
            return {"status": "success", "data": body, "http_status": response.status_code}
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return {"status": "error", "error": "Globalping response could not be verified"}
