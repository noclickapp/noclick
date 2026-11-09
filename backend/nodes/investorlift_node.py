"""InvestorLift property underwriting and data requests using a pasted API key.

Contract: https://docs.investorliftdata.com/openapi.json (1.0.0).
Calls can spend the provider account's balance. Never retry automatically;
pass a stable idempotency key to eligible endpoints when retrying deliberately.
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.investorlift_operations import InvestorLiftConfig, ROUTES
from utils.ssrf import guarded_async_client

BASE = "https://api.investorliftdata.com"


class InvestorLiftAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        hide_input_in_errors=True,
        title="InvestorLift API Key",
        json_schema_extra={
            "x-credential-url": "https://docs.investorliftdata.com/api-keys",
            "x-credential-instructions": "Create an API key in the InvestorLift Data Services portal and paste it here. NoClick sends it as a Bearer token to api.investorliftdata.com. The free coverage read checks key acceptance; it does not identify your account. Valuation and most data requests spend your InvestorLift balance.",
        },
    )
    credential_type: Literal["investorlift_api_key"] = Field(
        "investorlift_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API key",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or value.lower().startswith("bearer"):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class InvestorLiftFullConfig(
    NodeConfig[InvestorLiftConfig, InvestorLiftAPIKeyCredential]
):
    """The selected request and a manually connected InvestorLift key."""

    model_config = ConfigDict(hide_input_in_errors=True)


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class InvestorLiftNode(WorkflowNode):
    integration_type = "automation-investorlift"
    connection_evidence = ConnectionEvidence(
        noun="InvestorLift data coverage",
        operation="get_coverage",
        proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return InvestorLiftFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an InvestorLift API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path, query_fields = ROUTES[op.operation]
        values = op.model_dump(
            mode="json", by_alias=True, exclude_none=True, exclude={"operation"}
        )
        headers = {"Authorization": "Bearer " + secret, "Accept": "application/json"}
        for field, header in (
            ("idempotency_key", "Idempotency-Key"),
            ("customer_reference", "X-Customer-Reference"),
        ):
            if field in values:
                value = values.pop(field)
                if any(ord(c) < 32 or ord(c) == 127 for c in value):
                    raise ValueError("Header values cannot contain control characters")
                headers[header] = value
        # Values only replace fixed path placeholders, never a host or route.
        for field in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        params = []
        if method == "GET":
            for field in query_fields:
                if field not in values:
                    continue
                value = values[field]
                for item in value if isinstance(value, list) else [value]:
                    params.append(
                        (
                            field,
                            str(item).lower() if isinstance(item, bool) else str(item),
                        )
                    )
        try:
            async with guarded_async_client(
                timeout=60, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE + path,
                    headers=headers,
                    params=params if method == "GET" else None,
                    **({"json": values} if method == "POST" else {}),
                )
            trace = response.headers.get("trace-id")
            if response.status_code != 200:
                problem = None
                message = "InvestorLift did not confirm the request"
                if (
                    response.headers.get("content-type", "").split(";", 1)[0]
                    == "application/problem+json"
                ):
                    try:
                        detail = response.json()
                        if isinstance(detail, dict):
                            problem = detail.get("type")
                            message = (
                                detail.get("detail") or detail.get("title") or message
                            )
                    except ValueError:
                        pass
                result = {
                    "status": "error",
                    "http_status": response.status_code,
                    "error": message,
                    "problem_type": problem,
                    "trace_id": trace,
                    "retry_after": response.headers.get("retry-after"),
                }
            else:
                if (
                    len(response.content) > 20_000_000
                    or response.headers.get("content-type", "").split(";", 1)[0]
                    != "application/json"
                ):
                    raise ValueError("Expected a bounded InvestorLift JSON response")
                body = response.json()
                if (
                    not isinstance(body, dict)
                    or "error" in body
                    or "errors" in body
                    or "type" in body
                ):
                    raise ValueError("InvestorLift response is not a successful object")
                # Preserve documented nulls, record facts, and provider pagination without interpreting them.
                result = {"status": "success", "data": body, "trace_id": trace}
        except (httpx.HTTPError, ValueError):
            result = {
                "status": "error",
                "error": "InvestorLift request could not be confirmed; no automatic retry was made",
            }
        result = _redact(result, secret)
        await self.emit(result)
        return result
