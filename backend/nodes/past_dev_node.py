"""past.dev project memory using a manually supplied project API key.

Reference: https://past.dev/openapi.json (1.0.0). Writes return the provider's
receipt; asynchronous acceptance does not imply completed indexing/deletion.
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
from nodes.past_dev_operations import Operation, OPERATIONS
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.past.dev"


class PastDevAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Past Dev Project API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.past.dev",
            "x-credential-instructions": "In the past.dev console, select your project and create a key on the API keys screen. Paste the project key (past_sk_) without the Bearer prefix. The key selects the project for every operation. NoClick reads the project's identity directory to check the connection.",
        },
    )
    credential_type: Literal["past_dev_api_key"] = Field("past_dev_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Project API Key", min_length=1, max_length=4096, repr=False,
        description="Paste your project's API key without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Project API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without whitespace or the Bearer prefix")
        return value


# past.dev's own MCP server: agents get its tools through a person's past.dev sign-in.
PastDevMcpCredential = mcp_credential("past_dev", "https://app.past.dev/mcp", app="past.dev")
PastDevCredential = Union[PastDevAPIKeyCredential, PastDevMcpCredential]


class PastDevNodeConfig(NodeConfig[Operation, PastDevCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key.replace(secret, "[redacted]"): _redact(item, secret) for key, item in value.items()}
    return value


class PastDevNode(WorkflowNode):
    integration_type = "automation-past-dev"
    credential_provider_labels = {"past_dev": "past.dev Account"}
    connection_evidence = ConnectionEvidence(
        noun="project identities", operation="list_identities", label_keys=("identity",),
    )

    @classmethod
    def get_config_model(cls):
        return PastDevNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a past.dev project API key")
        config = self.config.config
        spec = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        # Preserve explicit null metadata and null trait values. Unset body
        # fields remain omitted so a patch never clears an unsupplied trait.
        supplied = config.model_dump(mode="json", exclude_unset=True)
        path = spec["path"]
        for key, wire in spec["path_fields"].items():
            value = str(values[key])
            if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use a valid past.dev resource identifier")
            path = path.replace("{" + wire + "}", quote(value, safe=""))
        secret = self.config.credentials.api_key
        kwargs = {
            "headers": {"Authorization": "Bearer " + secret, "Accept": "application/json"},
            "params": {wire: values[key] for key, wire in spec["query"].items() if key in values},
        }
        if spec["body"]:
            body = {key: supplied[key] for key in spec["body"]
                    if key in supplied and (supplied[key] is not None or key == "metadata")}
            if config.operation == "ingest_batch":
                body["items"] = [
                    {key: value for key, value in item.items() if value is not None or key == "metadata"}
                    for item in body["items"]
                ]
            kwargs["json"] = supplied["identities"] if spec["array_body"] else body
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(spec["method"], BASE_URL + path, **kwargs)
        except httpx.RequestError:
            return {"status": "error", "error": "past.dev request did not complete; inspect writes before retrying"}
        if response.status_code not in spec["statuses"]:
            detail = "past.dev returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("debugMessage") or error.get("code") or detail
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": _redact(str(detail), secret)}
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "completed": True}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "error": "past.dev returned invalid JSON"}
        if not isinstance(data, dict) or "code" in data or "error" in data:
            return {"status": "error", "error": "past.dev returned an unexpected response"}
        data = _redact(data, secret)
        result = {"status": "success", "http_status": response.status_code, "data": data}
        if config.operation == "list_identities":
            rows, more, cursor = data.get("identities"), data.get("hasMore"), data.get("endCursor")
            if (not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("identity"), str) for row in rows)
                    or type(more) is not bool or (more and (not isinstance(cursor, str) or not cursor))):
                return {"status": "error", "error": "past.dev returned an invalid identity page"}
            result.update(items=rows, has_more=more, next_page_token=cursor if more else None)
        elif config.operation == "list_audiences":
            if not isinstance(data.get("audiences"), list):
                return {"status": "error", "error": "past.dev returned an invalid audience list"}
            result["items"] = data["audiences"]
        return result
