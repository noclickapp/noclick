"""IP2Location.io's pinned geolocation API: one read, no mutation endpoints."""
from ipaddress import ip_address
from typing import Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class Ip2LocationIoCredential(BaseModel):
    model_config = ConfigDict(title="IP2Location.io API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.ip2location.io/ip2location-documentation",
            "x-credential-instructions": "Paste your IP2Location.io API key. NoClick sends it to api.ip2location.io for IP geolocation. Connecting performs one lookup of 8.8.8.8 and consumes a lookup credit. This establishes reachability, not account identity.",
        })
    credential_type: Literal["ip2location_io_api_key"] = Field("ip2location_io_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})


class Ip2LocationIoLookupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["get_ip_geolocation"] = Field("get_ip_geolocation", json_schema_extra={"ui:hidden": True})
    ip: str = Field(..., title="IP address", description="IPv4 or IPv6 address to geolocate, for example 8.8.8.8.")
    lang: Optional[Literal["ar", "cs", "da", "de", "en", "es", "et", "fi", "fr", "ga", "it", "ja", "ko", "ms", "nl", "pt", "ru", "sv", "tr", "vi", "zh-cn", "zh-tw"]] = Field(None, title="Translation language", description="Optional translated location names; requires a Plus or Security plan.")

    @field_validator("ip")
    @classmethod
    def valid_ip(cls, value):
        ip_address(value)
        if "%" in value:
            raise ValueError("Use an IPv4 or IPv6 address without a zone identifier")
        return value


class Ip2LocationIoConfig(NodeConfig[Ip2LocationIoLookupConfig, Ip2LocationIoCredential]):
    pass


class Ip2LocationIoNode(WorkflowNode):
    integration_type = "automation-ip2location-io"
    connection_evidence = ConnectionEvidence(
        noun="IP geolocation", operation="get_ip_geolocation",
        operation_arguments={"ip": "8.8.8.8"}, proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return Ip2LocationIoConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an IP2Location.io API key")
        op = self.config.config
        params = {"key": credential.api_key, "ip": op.ip, "format": "json"}
        if op.lang is not None:
            params["lang"] = op.lang
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get("https://api.ip2location.io/", params=params)
            if response.status_code != 200:
                return {"status": "error", "error": f"IP2Location.io returned HTTP {response.status_code}"}
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Invalid response")
            if "error" in body:
                error = body["error"]
                message = error.get("error_message", "Request rejected") if isinstance(error, dict) else "Request rejected"
                return {"status": "error", "error": str(message).replace(credential.api_key, "[redacted]")}
            if not isinstance(body.get("ip"), str) or ip_address(body["ip"]) != ip_address(op.ip):
                raise ValueError("Response IP does not match the requested address")
            return {"status": "success", "data": body}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "IP2Location.io lookup could not be confirmed"}
