"""IP2Proxy package queries, pinned to its published GET / contract.

Each package is a cumulative lookup with a documented credit cost. There are no
write endpoints in this contract. Existing IP2Proxy keys only (not IP2Location.io).
"""
from ipaddress import ip_address
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

DOCS = "https://www.ip2location.com/web-service/ip2proxy"


class Ip2ProxyAPIKey(BaseModel):
    model_config = ConfigDict(
        title="IP2Proxy API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS,
            "x-credential-instructions": "Paste your existing IP2Proxy web-service API key. New registrations for this legacy service are closed; IP2Location.io keys belong to a different service. Connecting looks up 201.42.237.89 with PX1 and consumes one credit. This proves key acceptance, not account identity. Package queries cost 1 to 11 credits each.",
        },
    )
    credential_type: Literal["ip2proxy_api_key"] = Field("ip2proxy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key")


class _Lookup(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    ip: str = Field(..., title="IP address", description="IPv4 or IPv6 address, for example 201.42.237.89. Each package includes the data from lower packages.")

    @field_validator("ip")
    @classmethod
    def valid_ip(cls, value):
        value = value.strip()
        ip_address(value)
        if "%" in value:
            raise ValueError("Use an IP address without a zone identifier")
        return value


class Ip2ProxyPX1Config(_Lookup):
    """Proxy status and country, including lower-package data; 1 credit(s)."""
    operation: Literal["get_proxy_status"] = Field("get_proxy_status", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX2Config(_Lookup):
    """Proxy type, including lower-package data; 2 credit(s)."""
    operation: Literal["get_proxy_type"] = Field("get_proxy_type", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX3Config(_Lookup):
    """Region and city, including lower-package data; 3 credit(s)."""
    operation: Literal["get_proxy_location"] = Field("get_proxy_location", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX4Config(_Lookup):
    """Internet service provider, including lower-package data; 4 credit(s)."""
    operation: Literal["get_proxy_isp"] = Field("get_proxy_isp", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX5Config(_Lookup):
    """Domain, including lower-package data; 5 credit(s)."""
    operation: Literal["get_proxy_domain"] = Field("get_proxy_domain", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX6Config(_Lookup):
    """Usage classification, including lower-package data; 6 credit(s)."""
    operation: Literal["get_proxy_usage"] = Field("get_proxy_usage", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX7Config(_Lookup):
    """Autonomous system, including lower-package data; 7 credit(s)."""
    operation: Literal["get_proxy_asn"] = Field("get_proxy_asn", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX8Config(_Lookup):
    """Last seen, including lower-package data; 8 credit(s)."""
    operation: Literal["get_proxy_last_seen"] = Field("get_proxy_last_seen", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX9Config(_Lookup):
    """Threat, including lower-package data; 9 credit(s)."""
    operation: Literal["get_proxy_threat"] = Field("get_proxy_threat", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX10Config(_Lookup):
    """Residential proxy detection, including lower-package data; 10 credit(s)."""
    operation: Literal["get_residential_proxy"] = Field("get_residential_proxy", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class Ip2ProxyPX11Config(_Lookup):
    """VPN provider, including lower-package data; 11 credit(s)."""
    operation: Literal["get_proxy_provider"] = Field("get_proxy_provider", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


Ip2ProxyOperation = Annotated[Union[
    Ip2ProxyPX1Config, Ip2ProxyPX2Config, Ip2ProxyPX3Config, Ip2ProxyPX4Config, Ip2ProxyPX5Config, Ip2ProxyPX6Config, Ip2ProxyPX7Config, Ip2ProxyPX8Config, Ip2ProxyPX9Config, Ip2ProxyPX10Config, Ip2ProxyPX11Config
], Field(discriminator="operation")]


PACKAGES = {'get_proxy_status': 'PX1', 'get_proxy_type': 'PX2', 'get_proxy_location': 'PX3', 'get_proxy_isp': 'PX4', 'get_proxy_domain': 'PX5', 'get_proxy_usage': 'PX6', 'get_proxy_asn': 'PX7', 'get_proxy_last_seen': 'PX8', 'get_proxy_threat': 'PX9', 'get_residential_proxy': 'PX10', 'get_proxy_provider': 'PX11'}


class Ip2ProxyConfig(NodeConfig[Ip2ProxyOperation, Ip2ProxyAPIKey]):
    pass


class Ip2ProxyNode(WorkflowNode):
    integration_type = "automation-ip2proxy"
    connection_evidence = ConnectionEvidence(
        noun="proxy lookup", operation="get_proxy_status",
        operation_arguments={"ip": "201.42.237.89"}, proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return Ip2ProxyConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an IP2Proxy API key")
        op = self.config.config
        package = PACKAGES[op.operation]
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get("https://api.ip2proxy.com/", params={
                    "ip": op.ip, "key": credential.api_key, "package": package, "format": "json",
                })
            # Never expose a key-bearing URL from an HTTP exception or redirect.
            if response.status_code != 200:
                return {"status": "error", "http_status": response.status_code, "error": "IP2Proxy lookup failed"}
            if len(response.content) > 1_000_000:
                raise ValueError("Response too large")
            # The published contract serves JSON text as text/html; do not gate on MIME.
            body = response.json()
        except httpx.HTTPError:
            return {"status": "error", "error": "IP2Proxy request could not be completed"}
        except ValueError:
            return {"status": "error", "error": "IP2Proxy returned invalid JSON"}
        if not isinstance(body, dict) or not isinstance(body.get("response"), str) or not body["response"]:
            return {"status": "error", "error": "IP2Proxy returned an unexpected response"}
        if body["response"] != "OK":
            return {"status": "error", "error": body["response"].replace(credential.api_key, "[redacted]")}
        # Preserve package-dependent fields and numeric values without inventing identity.
        # The provider does not echo the queried IP, so it cannot be independently matched.
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]")
            if isinstance(value, dict):
                return {str(k).replace(credential.api_key, "[redacted]"): redact(v) for k, v in value.items()}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value
        return {"status": "success", "package": package, "ip": op.ip, "data": redact(body)}
