"""Attentive private-app API key integration, with one request per operation.

Authentication: https://docs.attentive.com/docs/authentication
Contracts: https://docs.attentive.com/openapi/attentive-api-bundled-v2.yaml
and https://docs.attentive.com/openapi/attentive-api-bundled.yaml.
"""
from __future__ import annotations

from typing import Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.attentive_operations import AttentiveConfig, REQUESTS
from nodes.scopes.attentive import ATTENTIVE_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://api.attentivemobile.com"


class AttentiveAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Attentive API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://ui.attentivemobile.com/integrations",
            "x-credential-instructions": "Create a private custom app in Attentive, enable the permissions for your operations, and paste its API key. NoClick verifies the key by reading your account details. Subscribe and unsubscribe operations can send confirmation messages; use a sign-up unit with the required legal disclosure.",
        },
    )
    credential_type: Literal["attentive_api_key"] = Field("attentive_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


# Attentive's own MCP server: agents get its tools through a person's Attentive sign-in.
AttentiveMcpCredential = mcp_credential("attentive", "https://attentive-ui-mcp.attentivemobile.com/mcp?readOnly=false", app="Attentive")
AttentiveCredential = Union[AttentiveAPIKeyCredential, AttentiveMcpCredential]


class AttentiveFullConfig(NodeConfig[AttentiveConfig, AttentiveCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(secret, "[redacted]"): _redact(item, secret) for key, item in value.items()}
    return value


class AttentiveNode(WorkflowNode):
    integration_type = "automation-attentive"
    credential_provider_labels = {"attentive": "Attentive Account"}
    scope_registry = ATTENTIVE_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="Attentive account", identity_operation="get_me",
        identity_keys=("companyName", "attentiveDomainName", "companyId"),
    )

    @classmethod
    def get_config_model(cls):
        return AttentiveFullConfig

    async def execute(self, inputs):
        config = self.config
        if not isinstance(config, AttentiveFullConfig) or not config.credentials:
            raise ValueError("Connect an Attentive API key")
        secret = config.credentials.api_key
        op = config.config
        spec = REQUESTS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path = spec["path"]
        for key in spec["path_fields"]:
            value = values[key]
            if value in {".", ".."}:
                raise ValueError("Use a segment external ID, not a path component")
            path = path.replace("{" + key + "}", quote(value, safe=""))
        query = {key: values[key] for key in spec["query"] if key in values}
        body = {key: values[key] for key in spec["body"] if key in values}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(
                    spec["method"], BASE + path,
                    params=query,
                    headers={"Authorization": "Bearer " + secret, "Accept": "application/json"},
                    **({"json": body} if spec["body"] else {}),
                )
        except httpx.RequestError:
            return {"status": "error", "error": "Attentive request could not be completed; verify state before retrying a write"}
        if response.status_code not in spec["success"]:
            message = "Attentive rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("message") or error.get("error") or error.get("detail")
                    if isinstance(detail, str):
                        message = detail[:2000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, secret)}
        expects_json = op.operation in {
            "get_me", "list_segments", "create_segment", "get_segment", "update_segment",
            "get_custom_attributes", "get_subscriptions", "subscribe_user", "unsubscribe_user",
        }
        if not response.content and expects_json:
            return {"status": "error", "http_status": response.status_code, "error": "Attentive returned an empty response where account or operation data was expected"}
        if response.status_code == 204 or not response.content:
            return {"status": "success", "http_status": response.status_code, "accepted": True, "data": None}
        try:
            if len(response.content) > 10_000_000:
                raise ValueError("Response exceeds 10 MB")
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("Expected a JSON object or array")
            if isinstance(data, dict) and (data.get("success") is False or data.get("error") or data.get("errors")):
                raise ValueError("Attentive returned an error envelope")
            if op.operation == "get_me" and not any(isinstance(data.get(k), str) and data[k].strip() for k in ("companyName", "companyId", "attentiveDomainName")):
                raise ValueError("Attentive did not return an account identity")
            if op.operation == "list_segments" and (not isinstance(data, dict) or not isinstance(data.get("segments"), list)):
                raise ValueError("Attentive did not return a segment page")
        except (ValueError, AttributeError):
            return {"status": "error", "http_status": response.status_code, "error": "Attentive returned an unexpected response; verify state before retrying a write"}
        return {
            "status": "success", "http_status": response.status_code,
            "accepted": True, "data": _redact(data, secret),
        }
