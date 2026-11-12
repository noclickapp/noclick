"""Mercury banking API: one documented request per operation, API-token auth."""
from __future__ import annotations

import json
import re
from typing import Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.mercury_operations import Operation, ROUTES
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.mercury.com/api/v1"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class MercuryAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Mercury API Token", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.mercury.com/settings/tokens",
            "x-credential-instructions": "Create an API token in Mercury Settings > API. Paste the entire token, including secret-token: when present. Choose read-only access for reads or the permissions needed for payments and other writes. Read-write tokens require Mercury's IP allowlist.",
        },
    )
    credential_type: Literal["mercury_api_token"] = Field(
        "mercury_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ..., title="API Token", repr=False,
        description="Your Mercury API token, including its secret-token: prefix. Omit the Bearer prefix.",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if "://" in value or not 1 <= len(value) <= 4096 or not re.fullmatch(r"[A-Za-z0-9._~:+/=-]+", value):
            raise ValueError("Paste the complete Mercury API token without spaces or the Bearer prefix")
        return value


# Mercury's own MCP server: agents get its tools through a person's Mercury sign-in.
MercuryMcpCredential = mcp_credential("mercury", "https://mcp.mercury.com/mcp", app="Mercury")
MercuryCredential = Union[MercuryAPITokenCredential, MercuryMcpCredential]


class MercuryNodeConfig(NodeConfig[Operation, MercuryCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class MercuryNode(WorkflowNode):
    integration_type = "automation-mercury"
    credential_provider_labels = {"mercury": "Mercury Account"}
    connection_evidence = ConnectionEvidence(
        noun="bank accounts", operation="list_accounts",
        label_keys=("nickname", "name", "id"),
        identity_operation="get_organization", identity_keys=("legalBusinessName", "name"),
    )
    edit_examples = [
        "List my Mercury accounts and balances",
        "Find Mercury transactions for this month",
        "Create a customer and an invoice in Mercury",
    ]

    @classmethod
    def get_config_model(cls):
        return MercuryNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        # Keep foreign credential tags from being reinterpreted by legacy aliases.
        raw = config_data.get("credentials") if isinstance(config_data, dict) else None
        if isinstance(raw, dict) and raw.get("credential_type", "mercury_api_token") != "mercury_api_token":
            raise ValueError("Connect a Mercury API token")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Mercury API token")
        config = self.config.config
        token = self.config.credentials.api_token
        route = ROUTES[config.operation]
        wire = config.model_dump(mode="json", exclude_unset=True)
        path = route["path"].format(**{
            k: str(getattr(config, k)) for k in route["path_fields"]
        })
        params = {k: getattr(config, k) for k in route["query_fields"] if getattr(config, k) is not None}
        params = {k: [str(v) for v in value] if isinstance(value, list) else str(value) for k, value in params.items()}
        body = {k: v for k, v in wire.items() if k in route["body_fields"]}
        if config.operation == "create_invoice":
            # Mercury defaults to emailing immediately; make that choice visible.
            body["sendEmailOption"] = config.sendEmailOption
        method = route["method"]
        try:
            async with guarded_async_client(
                timeout=httpx.Timeout(30.0), follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=params,
                    **({"json": body} if route["body_fields"] else {}),
                ) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise ValueError("Mercury response exceeds the supported size")
                    status = response.status_code
                    if status not in route["statuses"]:
                        message = "Mercury returned HTTP " + str(status)
                        try:
                            error = json.loads(raw)
                            candidate = error.get("message") or error.get("error") if isinstance(error, dict) else None
                            if isinstance(candidate, str):
                                message += ": " + candidate[:2000]
                        except (ValueError, UnicodeError):
                            pass
                        output = {
                            "status": "error", "success": False, "http_status": status,
                            "error": message,
                            "write_outcome": "unknown" if method != "GET" and (status < 400 or status >= 500) else None,
                        }
                    else:
                        payload = json.loads(raw) if raw.strip() else None
                        if config.operation not in {"delete_customer", "cancel_invoice", "delete_recipient"} and not isinstance(payload, (dict, list)):
                            raise ValueError("Mercury returned an unexpected JSON representation")
                        if isinstance(payload, dict) and (payload.get("error") or payload.get("errors")):
                            raise ValueError("Mercury returned an error envelope")
                        if config.operation.startswith("list_"):
                            key = {"list_accounts": "accounts", "list_recipients": "recipients", "list_customers": "customers", "list_invoices": "invoices", "list_account_statements": "statements"}.get(config.operation, "transactions")
                            if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
                                raise ValueError("Mercury returned an unexpected list representation")
                        output = {"status": "success", "success": True, "http_status": status, "data": payload}
                        if config.operation.startswith("list_"):
                            output["items"] = payload[key]
        except (httpx.HTTPError, OSError, ValueError):
            # A timeout after a write cannot prove whether Mercury accepted it.
            # Leave idempotency keys with the caller and never retry silently.
            output = {
                "status": "error", "success": False,
                "error": "Mercury request did not return a verifiable response",
                "write_outcome": "unknown" if method != "GET" else None,
            }
        output = _redact({"operation": config.operation, **output}, token)
        await self.emit(output)
        return output
