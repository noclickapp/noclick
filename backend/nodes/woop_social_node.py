"""Native WoopSocial v1 posts, projects, accounts, media and webhook management.

Contract: https://api.woopsocial.com/v1/openapi.yaml (1.0.0).
Each operation makes one API request; pages retain the provider's nextCursor.
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
from nodes.woop_social_operations import ROUTES, WoopSocialConfig
from utils.ssrf import guarded_async_client

BASE = "https://api.woopsocial.com/v1"


class WoopSocialAPIKey(BaseModel):
    model_config = ConfigDict(title="Woop Social API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.woopsocial.com/api-access",
            "x-credential-instructions": "Copy your API key from the WoopSocial API Access page. Paste the key here. NoClick sends it as a Bearer token to api.woopsocial.com. Your key must have access to the projects and social accounts you automate.",
        })
    credential_type: Literal["woop_social_api_key"] = Field("woop_social_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class WoopSocialFullConfig(NodeConfig[WoopSocialConfig, WoopSocialAPIKey]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class WoopSocialNode(WorkflowNode):
    integration_type = "automation-woop-social"
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects")

    @classmethod
    def get_config_model(cls):
        return WoopSocialFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Woop Social API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, query_fields, body_model, expected_status = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in re.findall(r"{([^}]+)}", path):
            identifier = values.pop(field)
            if identifier in {".", ".."} or any(c in identifier for c in "/\\?#\r\n"):
                raise ValueError("Use a single WoopSocial resource ID")
            path = path.replace("{" + field + "}", quote(identifier, safe=""))
        params = {field: ",".join(values[field]) if isinstance(values[field], list) else values[field]
                  for field in query_fields if field in values}
        kwargs = {"params": params}
        if body_model is not None:
            kwargs["json"] = values
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **kwargs)
            if response.status_code != expected_status:
                try:
                    error = response.json()
                    message = error.get("message", "WoopSocial request failed") if isinstance(error, dict) else "WoopSocial request failed"
                except ValueError:
                    message = "WoopSocial returned a non-JSON error"
                result = {"status": "error", "http_status": response.status_code, "message": message}
            elif expected_status == 204:
                result = {"status": "success", "http_status": 204, "deletion_acknowledged": True}
            else:
                data = response.json()
                self._validate_response(op.operation, data)
                result = {"status": "success", "http_status": response.status_code, "data": data}
                if op.operation in {"list_media", "list_social_account_posts"}:
                    result["next_cursor"] = data.get("nextCursor")
                    result["has_more"] = bool(data.get("nextCursor"))
        except httpx.HTTPError:
            result = {"status": "error", "message": "WoopSocial request could not be completed; inspect writes before retrying"}
        except (ValueError, TypeError, KeyError):
            result = {"status": "error", "message": "WoopSocial returned an unexpected response; inspect writes before retrying"}
        result = _redact(result, key)
        await self.emit(result)
        return result

    @staticmethod
    def _validate_response(operation, data):
        if operation in {"list_projects", "list_social_accounts", "list_webhooks"}:
            if not isinstance(data, list) or not all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in data):
                raise ValueError("Expected a resource list")
        elif operation in {"list_media", "list_social_account_posts"}:
            field = "media" if operation == "list_media" else "socialAccountPosts"
            if not isinstance(data, dict) or not isinstance(data.get(field), list):
                raise ValueError("Expected a paginated resource list")
            if "nextCursor" in data and not isinstance(data["nextCursor"], str):
                raise ValueError("Expected a cursor string")
        elif operation == "validate_post":
            if not isinstance(data, dict) or type(data.get("isValid")) is not bool or not all(isinstance(data.get(k), list) for k in ("errors", "warnings")):
                raise ValueError("Expected a post validation result")
        elif operation == "get_social_account_platform_inputs":
            if not isinstance(data, dict) or "socialAccountId" not in data or "platformSpecificInputs" not in data:
                raise ValueError("Expected account platform inputs")
        elif not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise ValueError("Expected a resource")
