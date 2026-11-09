"""Leadsforge prospect discovery and enrichment with a user-supplied API key."""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.leadsforge_operations import LeadsforgeConfig, OPERATIONS
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.leadsforge.ai/public/v1"


class LeadsforgeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Leadsforge API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.salesforge.ai/blog/leadsforge-api",
            "x-credential-instructions": "In Leadsforge, open Usage → API & MCP and create an API key. Paste the key without the Bearer prefix. NoClick reads your enrichment jobs to check access. Search and enrichment can consume account credits; job creation returns immediately, so use the job status and results operations to poll later.",
        },
    )
    credential_type: Literal["leadsforge_api_key"] = Field("leadsforge_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value or len(value) > 8192 or not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header, prefix or whitespace")
        return value


class LeadsforgeFullConfig(NodeConfig[LeadsforgeConfig, LeadsforgeAPIKeyCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class LeadsforgeNode(WorkflowNode):
    integration_type = "automation-leadsforge"
    connection_evidence = ConnectionEvidence(operation="list_enrichment_jobs", noun="enrichment jobs")

    @classmethod
    def get_config_model(cls):
        return LeadsforgeFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Leadsforge API key")
        op = self.config.config
        credential = self.config.credentials
        route = OPERATIONS[op.operation]
        values = op.model_dump(by_alias=True, exclude_none=True)
        path = route["path"]
        if "{jobID}" in path:
            path = path.replace("{jobID}", quote(values["jobID"], safe=""))
        params = {key: values[key] for key in route["query"] if key in values}
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        if route["idempotency"] and values.get("idempotency_key"):
            headers["Idempotency-Key"] = values["idempotency_key"]
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            try:
                response = await client.request(
                    route["method"], BASE_URL + path, headers=headers, params=params,
                    **({"json": values["request"]} if route["body"] else {}),
                )
            except httpx.HTTPError:
                raise ValueError("Leadsforge request failed; check job status before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Leadsforge returned a non-JSON response") from None
        data = _redact(data, credential.api_key)
        if not 200 <= response.status_code < 300:
            message = (data.get("message") or data.get("error")) if isinstance(data, dict) else None
            result = {"status": "error", "status_code": response.status_code, "message": str(message or "Leadsforge request was rejected")}
        else:
            if not isinstance(data, dict):
                raise ValueError("Leadsforge returned an unexpected response shape")
            result = {"status": "success", "data": data}
            if op.operation == "list_enrichment_jobs":
                if not isinstance(data.get("jobs"), list):
                    raise ValueError("Leadsforge returned an unexpected jobs response")
                result["items"] = data["jobs"]
        await self.emit(result)
        return result
