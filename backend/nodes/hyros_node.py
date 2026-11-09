"""Hyros account data and asynchronous writes using the published REST API 1.46."""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.hyros_operations import HyrosOperation, ROUTES
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.hyros.com"


class HyrosAPIKey(BaseModel):
    model_config = ConfigDict(title="Hyros API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.hyros.com/settings/api",
        "x-credential-instructions": "Paste a Hyros REST API key from https://app.hyros.com/settings/api. Enable Get User Information for connection verification and the roles required by your operations. NoClick sends the key in the API-Key header to api.hyros.com. Writes are asynchronous; poll the returned request_id instead of resending a pending write.",
    })
    credential_type: Literal["hyros_api_key"] = Field("hyros_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class HyrosConfig(NodeConfig[HyrosOperation, HyrosAPIKey]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class HyrosNode(WorkflowNode):
    integration_type = "automation-hyros"
    connection_evidence = ConnectionEvidence(noun="Hyros account", identity_operation="get_user_info")

    @classmethod
    def get_config_model(cls):
        return HyrosConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Hyros API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, route, query_keys = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, mode="json")
        for key in ("id", "request_id"):
            if "{" + key + "}" in route:
                identifier = values[key]
                if not identifier or identifier in {".", ".."}:
                    raise ValueError("Supply a resource identifier")
                route = route.replace("{" + key + "}", quote(identifier, safe=""))
        params = {key: values[key] for key in query_keys if key in values}
        request = {"params": params, "headers": {"API-Key": secret, "Accept": "application/json"}}
        if "body" in values:
            request["json"] = values["body"]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, **request)
        except httpx.HTTPError:
            output = {"status": "error", "error": "Hyros request did not complete. " + ("Write outcome is unknown; do not resend without checking Hyros." if method != "GET" else "Try the read again.")}
        else:
            try:
                body = response.json()
            except (ValueError, UnicodeError):
                body = None
            if response.status_code != 200:
                detail = body.get("message") if isinstance(body, dict) else None
                output = {"status": "error", "status_code": response.status_code, "error": detail or f"Hyros returned HTTP {response.status_code}"}
            elif not isinstance(body, dict) or "result" not in body:
                output = {"status": "error", "error": "Hyros returned an unexpected JSON response"}
            elif isinstance(body["result"], str) and body["result"].upper() in {"ERROR", "FAIL", "FAILED"}:
                output = {"status": "error", "error": body.get("message") or "Hyros rejected the request"}
            else:
                # Preserve cursors and asynchronous ids without an unsafe automatic write retry.
                output = {**body, "status": "success"}
                if method != "GET":
                    output["write_status"] = "accepted"
        output = _redact(output, secret)
        await self.emit(output)
        return output
