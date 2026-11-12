"""Netlify workflow node backed by the vendor's pinned OpenAPI 2.60.0 spec.

Supports OAuth authorization-code and personal access token credentials. The
catalog includes every JSON REST action in the public spec; Netlify's five
binary upload endpoints are deliberately listed as exclusions in the catalog.
"""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.netlify_operations import CATALOG
from nodes.scopes.netlify import NETLIFY_SCOPES

BASE_URL = "https://api.netlify.com/api/v1"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
OPERATIONS = {op["name"]: op for op in CATALOG["operations"]}
assert len(OPERATIONS) == len(CATALOG["operations"])
OPERATIONS["test_connection"] = {
    "name": "test_connection", "label": "Test Connection", "category": "Account",
    "description": "Verify the Netlify credential and return the current user.",
    "method": "GET", "path": "/user", "path_params": [], "query_fields": [],
    "required_query": [], "has_body": False, "body_type": "object",
    "body_required": False, "body_required_fields": [], "body_fields": [],
}


class NetlifyOAuthCredential(BaseModel):
    credential_type: Literal["netlify_oauth"] = Field(
        "netlify_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    user_id: Optional[str] = Field(None, title="User ID")
    email: Optional[str] = Field(None, title="Email")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "netlify",
        "title": "Netlify OAuth",
        "x-oauth-scopes": sorted(NETLIFY_SCOPES.declared_scopes()),
    })


class NetlifyPersonalAccessTokenCredential(BaseModel):
    credential_type: Literal["netlify_pat"] = Field(
        "netlify_pat", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Personal Access Token", json_schema_extra={"ui:widget": "password"}
    )
    model_config = ConfigDict(json_schema_extra={
        "title": "Netlify Personal Access Token",
        "x-credential-url": "https://app.netlify.com/user/applications#personal-access-tokens",
        "x-credential-instructions": "Create a personal access token in Netlify User settings > Applications. OAuth connection is recommended for shared workflows.",
    })


# Netlify's own MCP server: agents get its tools through a person's Netlify sign-in.
NetlifyMcpCredential = mcp_credential("netlify", "https://mcp.netlify.com/mcp", app="Netlify")
NetlifyCredential = Union[NetlifyOAuthCredential, NetlifyPersonalAccessTokenCredential, NetlifyMcpCredential]


def _path_field(raw: str) -> str:
    return "path_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (
            Literal[name],
            Field(name, title=op["label"], description=op["description"], json_schema_extra={
                "const": name, "ui:hidden": True, "x-category": op["category"],
                "x-display-name": op["label"], "x-is-trigger": False,
            }),
        )
    }
    for raw in op["path_params"]:
        fields[_path_field(raw)] = (
            str, Field(..., title=raw.replace("_", " ").title()),
        )
    if op["query_fields"]:
        hint = "Documented Netlify parameters: " + ", ".join(op["query_fields"])
        if op["required_query"]:
            hint += ". Required: " + ", ".join(op["required_query"])
        fields["query_json"] = (
            str if op["required_query"] else Optional[str],
            Field(... if op["required_query"] else None, title="Query Parameters (JSON)", description=hint,
                  json_schema_extra={**JSON_EDITOR, "contentMediaType": "application/json",
                                     "contentSchema": op["query_schema"]}),
        )
    if op["has_body"]:
        hint = f"JSON {op['body_type']} body."
        if op["body_required_fields"]:
            hint += " Required keys: " + ", ".join(op["body_required_fields"]) + "."
        if op["body_fields"]:
            hint += " Documented keys include: " + ", ".join(op["body_fields"][:20]) + "."
        fields["body_json"] = (
            str if op["body_required"] else Optional[str],
            Field(... if op["body_required"] else None, title="Request Body (JSON)", description=hint, json_schema_extra=JSON_EDITOR),
        )
    return create_model(
        "Netlify" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
NetlifyConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class NetlifyNodeConfig(NodeConfig[NetlifyConfig, NetlifyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: str, label: str, expected: str) -> Any:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc
    if expected == "array" and not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array")
    if expected == "object" and not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


class NetlifyNode(WorkflowNode):
    """Execute a documented Netlify REST operation."""

    integration_type = "automation-netlify"
    credential_provider_labels = {"netlify": "Netlify"}
    scope_registry = NETLIFY_SCOPES
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="account")
    edit_examples = [
        "List my Netlify sites", "Get a deploy's status", "List form submissions",
        "Create a build hook", "Read team environment variables",
    ]

    @classmethod
    def get_config_model(cls):
        return NetlifyNodeConfig

    @staticmethod
    async def _request(token: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
        op = OPERATIONS[name]
        path = op["path"]
        for raw in op["path_params"]:
            value = values.get(_path_field(raw))
            if value is None or str(value).strip() in {"", ".", ".."}:
                raise ValueError(f"{raw} is required")
            safe = "/" if raw in {"file_path", "path"} else ""
            path = path.replace("{" + raw + "}", quote(str(value), safe=safe))
        query = _parse_json(values.get("query_json") or "{}", "Query Parameters", "object")
        unknown = set(query) - set(op["query_fields"])
        if unknown:
            raise ValueError("Unknown query parameters: " + ", ".join(sorted(unknown)))
        missing = set(op["required_query"]) - set(query)
        if missing:
            raise ValueError("Missing query parameters: " + ", ".join(sorted(missing)))
        kwargs: dict[str, Any] = {}
        if op["has_body"] and values.get("body_json") is not None:
            body = _parse_json(values["body_json"], "Request Body", op["body_type"])
            if isinstance(body, dict):
                missing_body = set(op["body_required_fields"]) - set(body)
                if missing_body:
                    raise ValueError("Request Body is missing required keys: " + ", ".join(sorted(missing_body)))
            kwargs["json"] = body
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                op["method"], BASE_URL + path, params=query or None,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "NoClick-Netlify-Integration"},
                **kwargs,
            )
        if response.is_error or response.is_redirect:
            detail = response.text[:500].replace(token, "[REDACTED]")
            raise ValueError(f"Netlify API error {response.status_code}: {detail}")
        if not response.content:
            data: Any = {}
        elif "json" in response.headers.get("content-type", ""):
            try:
                data = response.json()
            except ValueError as exc:
                raise ValueError("Netlify returned invalid JSON") from exc
        else:
            data = BinaryOutput(
                data=response.content,
                content_type=response.headers.get("content-type", "application/octet-stream"),
                filename="netlify-response",
            )
        return {
            "status": "success", "operation": name, "status_code": response.status_code,
            "data": data, "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, NetlifyNodeConfig) or not self.config.credentials:
            raise ValueError("Connect Netlify before running this action")
        return await self._request(
            self.config.credentials.access_token,
            self.config.config.operation,
            self.config.config.model_dump(exclude_none=True),
        )
