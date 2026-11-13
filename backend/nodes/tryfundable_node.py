"""Tryfundable company, funding, investor, people and saved-alert operations.

Uses a pasted API key against the provider's fixed API origin. Each operation
makes exactly one request, preserving pagination and credit metadata; contact
unlocks have account-persistent effects and are never retried automatically.
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
from nodes.tryfundable_operations import ROUTES, TryfundableConfig
from utils.ssrf import guarded_async_client

BASE_URL = "https://www.tryfundable.ai/api/v1"


class TryfundableAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Tryfundable API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.tryfundable.ai/api-access/",
            "x-credential-instructions": "Paste your Fundable API key from API Access. Requests use Authorization: Bearer. Connection testing reads your own alert configurations without spending credits and requires a Pro+ or Enterprise plan; other keys may be saved as unverified. Discovery and contact unlocks consume credits according to your plan.",
        },
    )
    credential_type: Literal["tryfundable_api_key"] = Field(
        "tryfundable_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix or whitespace")
        return value


# Fundable's own MCP server: agents get its tools through a person's Fundable sign-in.
TryfundableMcpCredential = mcp_credential("tryfundable", "https://mcp.tryfundable.ai/", app="Fundable")
TryfundableCredential = Union[TryfundableAPIKeyCredential, TryfundableMcpCredential]


class TryfundableFullConfig(NodeConfig[TryfundableConfig, TryfundableCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class TryfundableNode(WorkflowNode):
    integration_type = "automation-tryfundable"
    credential_provider_labels = {"tryfundable": "Fundable Account"}
    connection_evidence = ConnectionEvidence(
        noun="saved funding alert configurations", operation="list_alert_configurations",
        label_keys=("name", "description", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return TryfundableFullConfig

    async def execute(self, input_data):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Tryfundable API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", quote(values.pop("id"), safe=""))
        kwargs = {"json": values} if method == "POST" else {"params": values}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, headers={
                    "Authorization": "Bearer " + secret, "Accept": "application/json",
                }, **kwargs)
        except httpx.RequestError:
            raise ValueError("Tryfundable request could not be confirmed; inspect before retrying a contact unlock") from None
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if response.status_code != 200:
            message = f"Tryfundable HTTP {response.status_code}"
            if mime == "application/json" and len(response.content) <= 2_000_000:
                try:
                    error = response.json().get("error")
                    detail = error.get("message") if isinstance(error, dict) else error
                    if isinstance(detail, str):
                        message = detail[:1000]
                except (ValueError, AttributeError):
                    pass
            output = {"status": "error", "success": False, "http_status": response.status_code,
                "error": _redact(message, secret)}
            # A 401 definitively rejects the key. A plan restriction does not:
            # the account-only alert probe may be unavailable to a valid key.
            if response.status_code == 401:
                output["status_code"] = 401
        else:
            if mime != "application/json" or len(response.content) > 10_000_000:
                raise ValueError("Expected bounded JSON from Tryfundable")
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Tryfundable returned invalid JSON") from None
            if not isinstance(body, dict) or body.get("success") is not True or not isinstance(body.get("data"), dict) or not isinstance(body.get("meta"), dict):
                raise ValueError("Tryfundable response was not a successful data envelope")
            output = {**_redact(body, secret), "status": "success", "http_status": 200}
            if config.operation == "list_alert_configurations":
                items = body["data"].get("configurations")
                if not isinstance(items, list):
                    raise ValueError("Tryfundable did not return alert configurations")
                output["items"] = _redact(items, secret)
        await self.emit(output)
        return output
