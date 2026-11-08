"""IP2WHOIS v2 domain lookup. Contract: https://www.ip2whois.com/developers-api."""
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class Ip2WhoisAPIKey(BaseModel):
    model_config = ConfigDict(
        title="IP2WHOIS API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.ip2whois.com/developers-api",
            "x-credential-instructions": "Paste your WHOIS lookup API license key from your IP2Location.io account. Connecting makes one WHOIS lookup for locaproxy.com and uses your lookup quota. This verifies API access, not account identity.",
        },
    )
    credential_type: Literal["ip2whois_api_key"] = Field("ip2whois_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key")


class Ip2WhoisLookupConfig(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    operation: Literal["lookup_domain"] = Field("lookup_domain", title="Operation", json_schema_extra={"enumNames": ["Lookup Domain"], "x-operation-kind": "read"})
    domain: str = Field(..., min_length=1, description="Domain name, for example locaproxy.com; use punycode for international domain names.")

    @field_validator("domain")
    @classmethod
    def domain_name(cls, value):
        value = value.strip()
        if not value or any(c.isspace() for c in value) or any(c in value for c in "/?#:@"):
            raise ValueError("Enter a domain name without a URL, path or port")
        return value


class Ip2WhoisFullConfig(NodeConfig[Ip2WhoisLookupConfig, Ip2WhoisAPIKey]):
    pass


class Ip2WhoisNode(WorkflowNode):
    integration_type = "automation-ip2whois"
    connection_evidence = ConnectionEvidence(
        noun="WHOIS lookup", operation="lookup_domain",
        operation_arguments={"domain": "locaproxy.com"}, proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return Ip2WhoisFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an IP2WHOIS API key")
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get("https://api.ip2whois.com/v2/", params={
                    "key": credential.api_key, "domain": self.config.config.domain, "format": "json",
                })
            # HTTP errors can contain the key-bearing request URL; never expose it.
            if not 200 <= response.status_code < 300:
                return {"status": "error", "http_status": response.status_code, "error": "IP2WHOIS lookup failed"}
            body = response.json()
        except httpx.HTTPError:
            return {"status": "error", "error": "IP2WHOIS request could not be completed"}
        except ValueError:
            return {"status": "error", "error": "IP2WHOIS returned invalid JSON"}
        if not isinstance(body, dict):
            return {"status": "error", "error": "IP2WHOIS returned an unexpected response"}
        error = body.get("error")
        if isinstance(error, dict):
            message = str(error.get("error_message") or "IP2WHOIS rejected the lookup")
            return {"status": "error", "error": message.replace(credential.api_key, "[redacted]"), "error_code": error.get("error_code")}
        if body.get("error_code") not in (None, "", 0, "0"):
            message = str(body.get("error_message") or "IP2WHOIS rejected the lookup")
            return {"status": "error", "error": message.replace(credential.api_key, "[redacted]"), "error_code": body["error_code"]}
        if not isinstance(body.get("domain"), str) or not body["domain"]:
            return {"status": "error", "error": "IP2WHOIS response has no domain record"}
        return {"status": "success", "data": body}
