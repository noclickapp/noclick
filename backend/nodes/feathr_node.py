"""Feathr account, audience and marketing operations using a pasted API key."""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.feathr_operations import FeathrOperation, OPERATIONS
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.feathr.co"


class FeathrAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Feathr API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.feathr.co/getting-started",
            "x-credential-instructions": "Create an API key in the Feathr app and paste the secret shown at creation. Grant only the resource scopes needed by your operations (for example persons:read and persons:write). NoClick checks the key with GET /me; that confirms the account, not permission for every operation.",
        },
    )
    credential_type: Literal["feathr_api_key"] = Field("feathr_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        description="Paste your Feathr API key without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste an API key without whitespace or the Bearer prefix")
        return value


class FeathrNodeConfig(NodeConfig[FeathrOperation, FeathrAPIKeyCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key.replace(secret, "[redacted]"): _redact(item, secret) for key, item in value.items()}
    return value


class FeathrNode(WorkflowNode):
    integration_type = "automation-feathr"
    connection_evidence = ConnectionEvidence(
        noun="Feathr account", identity_operation="get_account", identity_keys=("account_id",),
    )

    @classmethod
    def get_config_model(cls):
        return FeathrNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Feathr API key")
        config = self.config.config
        spec = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        # Omitted partial-update fields stay omitted; explicit nulls clear values.
        body_values = config.model_dump(mode="json", exclude_unset=True)
        path = spec["path"]
        for key in spec["path_fields"]:
            value = values[key]
            if value in {".", ".."} or any(ord(c) < 32 for c in value):
                raise ValueError("Use a Feathr resource ID")
            path = path.replace("{" + key + "}", quote(value, safe=""))
        params = {wire: values[key] for key, wire in spec["query"].items() if key in values}
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        secret = self.config.credentials.api_key
        headers = {"Authorization": "Bearer " + secret, "Accept": "application/json"}
        headers.update({wire: values[key] for key, wire in spec["headers"].items() if key in values})
        body = {key: body_values[key] for key in spec["body"] if key in body_values}
        kwargs = {"params": params, "headers": headers}
        if spec["body"]:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(spec["method"], BASE_URL + path, **kwargs)
        except httpx.RequestError:
            return {"status": "error", "error": "Feathr request could not be completed"}
        if response.status_code != spec["status"]:
            detail = "Feathr returned an unexpected HTTP status"
            try:
                problem = response.json()
                if isinstance(problem, dict):
                    detail = problem.get("detail") or problem.get("title") or detail
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": _redact(detail, secret)}
        if spec["status"] == 204:
            return {"status": "success", "completed": True}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "error": "Feathr returned invalid JSON"}
        if not isinstance(data, dict) or "error" in data or (isinstance(data.get("status"), int) and data["status"] >= 400):
            return {"status": "error", "error": "Feathr returned an unexpected response"}
        data = _redact(data, secret)
        if config.operation.startswith("list_"):
            if not isinstance(data.get("items"), list) or any(type(data.get(k)) is not int for k in ("page", "size", "total")):
                return {"status": "error", "error": "Feathr returned an invalid page"}
            if data["page"] < 1 or data["size"] < 1 or data["total"] < 0:
                return {"status": "error", "error": "Feathr returned invalid pagination"}
            has_more = data["page"] * data["size"] < data["total"]
            return {"status": "success", **data, "has_more": has_more, "next_page": data["page"] + 1 if has_more else None}
        if config.operation == "get_account" and not isinstance(data.get("account_id"), str):
            return {"status": "error", "error": "Feathr returned no account identity"}
        return {"status": "success", "data": data}
