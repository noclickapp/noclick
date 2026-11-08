"""IPLocate IP intelligence, using the five operations in OpenAPI 1.0.0.

Contract: https://www.iplocate.io/openapi.yaml
Authentication: https://www.iplocate.io/docs/getting-started/authentication
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

BASE = "https://iplocate.io/api"
FIELD_PATTERN = r"^[a-z_]+(?:\.[a-z_]+)*$"


class IplocateAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="IPLocate API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.iplocate.io/account",
            "x-credential-instructions": "Paste your IPLocate API key from your account. The connection check reads the NoClick server's IP intelligence; it proves API reachability, not account identity. Batch lookups require a paid plan or credits.",
        },
    )
    credential_type: Literal["iplocate_api_key"] = Field("iplocate_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Include(_Input):
    include: str | None = Field(None, max_length=2000, description="Optional comma-separated fields, such as asn.asn,privacy.is_vpn. Always returns JSON.")

    @field_validator("include")
    @classmethod
    def fields(cls, value):
        if value is not None and not all(re.fullmatch(FIELD_PATTERN, field) for field in value.split(",")):
            raise ValueError("Use comma-separated field paths")
        return value


class _IP(_Input):
    ip: str = Field(..., min_length=2, max_length=45, description="IPv4 or IPv6 address, for example 8.8.8.8 or 2001:4860:4860::8888.")

    @field_validator("ip")
    @classmethod
    def address(cls, value):
        if "%" in value:
            raise ValueError("Use an IPv4 or IPv6 address without a zone identifier")
        try:
            ip_address(value)
        except ValueError:
            raise ValueError("Use an IPv4 or IPv6 address") from None
        return value


class _Filter(_Input):
    filter: str = Field(..., pattern=FIELD_PATTERN, max_length=200, description="One field path, such as ip, asn or privacy.is_vpn. Scalar fields return plain text; objects return JSON.")


class LookupSelf(_Include):
    """Look up the NoClick server's public IP, not the user's device IP."""
    operation: Literal["lookup_self"] = Field("lookup_self", json_schema_extra={"ui:hidden": True})


class LookupSelfFiltered(_Filter):
    """Read one field or object for the NoClick server's public IP."""
    operation: Literal["lookup_self_filtered"] = Field("lookup_self_filtered", json_schema_extra={"ui:hidden": True})


class Lookup(_IP, _Include):
    """Look up geolocation, ASN, privacy, hosting, company and abuse data."""
    operation: Literal["lookup"] = Field("lookup", json_schema_extra={"ui:hidden": True})


class LookupFiltered(_IP, _Filter):
    """Read one field or object for a specified IP address."""
    operation: Literal["lookup_filtered"] = Field("lookup_filtered", json_schema_extra={"ui:hidden": True})


class BatchLookup(_Input):
    """Look up up to 1,000 IPs; each successful lookup consumes quota."""
    operation: Literal["batch_lookup"] = Field("batch_lookup", json_schema_extra={"ui:hidden": True})
    ips: list[str] = Field(..., min_length=1, max_length=1000, description="IPv4 or IPv6 addresses. Requires a paid plan or credits. Results can contain per-address errors.")

    @field_validator("ips")
    @classmethod
    def addresses(cls, value):
        for address in value:
            _IP(ip=address)
        return value


IplocateOperation = Annotated[Union[LookupSelf, LookupSelfFiltered, Lookup, LookupFiltered, BatchLookup], Field(discriminator="operation")]


class IplocateFullConfig(NodeConfig[IplocateOperation, IplocateAPIKeyCredential]):
    pass


class IplocateNode(WorkflowNode):
    integration_type = "automation-iplocate"
    connection_evidence = ConnectionEvidence(noun="IP intelligence API", operation="lookup_self", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return IplocateFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            return {"status": "error", "error": "Connect an IPLocate API key"}
        op = self.config.config
        key = self.config.credentials.api_key
        path, method = "/lookup/", "GET"
        params = {"apikey": key}
        kwargs = {}
        if isinstance(op, BatchLookup):
            path, method = "/batch", "POST"
            kwargs["json"] = op.ips
        else:
            if isinstance(op, (Lookup, LookupFiltered)):
                path += quote(op.ip, safe="")
            if isinstance(op, (LookupFiltered, LookupSelfFiltered)):
                if not path.endswith("/"):
                    path += "/"
                path += quote(op.filter, safe="")
            if isinstance(op, _Include) and op.include is not None:
                params["include"] = op.include
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params, headers={"Accept": "application/json, text/plain"}, **kwargs)
            if response.status_code != 200:
                message = "IPLocate request failed"
                try:
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get("error"), str):
                        message = body["error"][:1000].replace(key, "[redacted]")
                except ValueError:
                    pass
                return {"status": "error", "error": message, "http_status": response.status_code}
            if len(response.content) > 10_000_000:
                return {"status": "error", "error": "IPLocate response exceeded the size limit"}
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime == "text/plain" and isinstance(op, (LookupFiltered, LookupSelfFiltered)):
                data = response.text
            elif mime == "application/json":
                data = response.json()
                if not isinstance(data, dict) or "error" in data:
                    return {"status": "error", "error": "IPLocate returned an unexpected response"}
            else:
                return {"status": "error", "error": "IPLocate returned an unexpected content type"}
            # Never echo credentials, including in upstream error strings or batch results.
            def redact(value):
                if isinstance(value, str):
                    return value.replace(key, "[redacted]")
                if isinstance(value, dict):
                    return {redact(k): redact(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [redact(v) for v in value]
                return value
            return {"status": "success", "data": redact(data)}
        except (httpx.HTTPError, ValueError):
            # HTTP errors may embed the request URL, which carries the API key.
            return {"status": "error", "error": "IPLocate request could not be completed"}
