"""Productboard API v2 workflow actions generated from its official OpenAPI release.

Productboard publishes nine OpenAPI groups in its ``productboard-api-v2-specs``
release. The checked-in catalog preserves all 59 current operations, path and
query parameters, OAuth scopes, and direct reference links.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.productboard_operations import PRODUCTBOARD_OPERATIONS
from nodes.scopes.productboard import PRODUCTBOARD_SCOPES

logger = logging.getLogger(__name__)

PRODUCTBOARD_API_BASE = "https://api.productboard.com/v2"

PRODUCTBOARD_OAUTH_SCOPES = sorted(PRODUCTBOARD_SCOPES.declared_scopes())


class ProductboardOAuthCredential(BaseModel):
    credential_type: Literal["productboard_oauth"] = Field(
        "productboard_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access token")
    refresh_token: Optional[str] = Field(None, title="Refresh token")
    expires_at: Optional[str] = Field(None, title="Token expiry")
    workspace_name: Optional[str] = Field(None, title="Workspace")

    model_config = ConfigDict(
        json_schema_extra={
            "title": "Productboard OAuth",
            "x-credential-type": "oauth",
            "x-oauth-provider": "productboard",
            "x-oauth-scopes": PRODUCTBOARD_OAUTH_SCOPES,
            "x-credential-url": "https://app.productboard.com/oauth2/applications",
        }
    )


class ProductboardApiTokenCredential(BaseModel):
    credential_type: Literal["productboard_api_token"] = Field(
        "productboard_api_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Productboard API token",
        description="Personal access token from Settings → Integrations → Public APIs → Access Token (Pro plan or higher).",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "title": "Productboard API Token",
            "x-credential-url": "https://developer.productboard.com/reference/api-token",
            "x-credential-instructions": "Create a personal access token in Productboard Settings → Integrations → Public APIs → Access Token. API access requires Pro or a higher plan.",
        }
    )


# Productboard's own MCP server: agents get its tools through a person's Productboard sign-in.
ProductboardMcpCredential = mcp_credential("productboard", "https://mcp.productboard.com", app="Productboard")
ProductboardCredential = Union[
    ProductboardOAuthCredential, ProductboardApiTokenCredential, ProductboardMcpCredential
]


def _operation_model(spec: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, Any] = {
        "operation": (
            Literal[spec["operation"]],
            Field(
                spec["operation"],
                title=spec["title"],
                json_schema_extra={
                    "const": spec["operation"],
                    "ui:hidden": True,
                    "x-category": spec["category"],
                    "x-display-name": spec["title"],
                    "x-is-trigger": False,
                },
            ),
        )
    }
    for name in spec["path_parameters"]:
        fields[name] = (
            str,
            Field(
                ...,
                title=name.replace("_", " ").title(),
                json_schema_extra=spec.get("path_parameter_schemas", {}).get(name),
            ),
        )
    for param in spec["query_fields"]:
        if param["type"] == "boolean":
            annotation = bool
        elif param["type"] == "integer":
            annotation = int
        elif param["type"] == "array":
            annotation = list[str]
        else:
            annotation = str
        field_name = param["field"]
        fields[field_name] = (
            annotation if param["required"] else Optional[annotation],
            Field(
                ... if param["required"] else None,
                title=param["name"],
                description=param["description"] or None,
            ),
        )
    fields["query_json"] = (
        Optional[str],
        Field(
            None,
            title="Additional query parameters (JSON)",
            description="Optional JSON object for filters not shown above.",
            json_schema_extra={
                "ui:widget": "textarea",
                "contentMediaType": "application/json",
                "contentSchema": {"type": "object"},
            },
        ),
    )
    if spec["has_body"]:
        fields["body_json"] = (
            str if spec["body_required"] else Optional[str],
            Field(
                ... if spec["body_required"] else None,
                title="Request body (JSON)",
                description="JSON payload documented at " + spec["reference"],
                json_schema_extra={
                    "ui:widget": "textarea",
                    "contentMediaType": "application/json",
                    "contentSchema": spec.get("body_schema", {"type": ["object", "array"]}),
                },
            ),
        )
    return create_model(
        "Productboard"
        + "".join(word.capitalize() for word in spec["operation"].split("_"))
        + "Config",
        __doc__=spec["title"],
        **fields,
    )


PRODUCTBOARD_CONFIGS = {
    name: _operation_model(spec) for name, spec in PRODUCTBOARD_OPERATIONS.items()
}
ProductboardConfig = Annotated[
    Union[tuple(PRODUCTBOARD_CONFIGS.values())], Field(discriminator="operation")
]


class ProductboardNodeConfig(NodeConfig[ProductboardConfig, ProductboardCredential]):
    """Productboard operation and OAuth or API token credential."""


def _parse_json(value: Optional[str], field: str, *, object_only: bool = False) -> Any:
    if value is None or value == "":
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Productboard {field} must be valid JSON") from exc
    if object_only and not isinstance(parsed, dict):
        raise ValueError(f"Productboard {field} must be a JSON object")
    if not object_only and not isinstance(parsed, (dict, list)):
        raise ValueError(f"Productboard {field} must be a JSON object or array")
    return parsed


def _error_message(payload: Any, status_code: int) -> str:
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, dict):
                    message = error.get("detail") or error.get("title")
                    if isinstance(message, str) and message:
                        return message
        for key in ("detail", "message", "text"):
            message = payload.get(key)
            if isinstance(message, str) and message:
                return message
    return f"Productboard request failed (HTTP {status_code})"


class ProductboardNode(WorkflowNode):
    """Execute a documented Productboard REST API v2 operation."""

    integration_type = "automation-productboard"
    scope_registry = PRODUCTBOARD_SCOPES
    credential_provider_labels = {"productboard": "Productboard"}

    edit_examples = [
        "List Productboard notes",
        "Create a feature from customer feedback",
        "Search Productboard entities",
        "List teams and members",
    ]
    connection_evidence = ConnectionEvidence(operation="list_teams", noun="teams")

    @classmethod
    def get_config_model(cls):
        return ProductboardNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.productboard_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="productboard",
        )

    async def _ensure_fresh_token(self, credentials: ProductboardCredential) -> str:
        if not isinstance(credentials, ProductboardOAuthCredential):
            return credentials.access_token
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.productboard_oauth import refresh_access_token

        data = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=data,
            refresh=refresh_access_token,
            provider="productboard",
            caller_path="execute",
        )
        credentials.access_token = data["access_token"]
        credentials.expires_at = data.get("expires_at")
        if data.get("refresh_token"):
            credentials.refresh_token = data["refresh_token"]
        return credentials.access_token

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.monotonic()
        if not isinstance(self.config, ProductboardNodeConfig):
            raise ValueError("Productboard configuration is required")
        credentials = self.config.credentials
        if not credentials or not credentials.access_token:
            raise ValueError("Productboard credential is required")
        operation = self.config.config.operation
        spec = PRODUCTBOARD_OPERATIONS[operation]
        values = self.config.config.model_dump(exclude_none=True)
        path = spec["path"]
        for name in spec["path_parameters"]:
            value = str(values[name])
            if not value:
                raise ValueError(f"Productboard {name} is required")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        if re.search(r"{[^}]+}", path):
            raise ValueError("Productboard path parameter is missing")

        params = _parse_json(values.get("query_json"), "query", object_only=True) or {}
        for param in spec["query_fields"]:
            if param["field"] in values:
                params[param["name"]] = values[param["field"]]
        body = _parse_json(values.get("body_json"), "body")
        if spec["body_required"] and body is None:
            raise ValueError("Productboard request body is required")
        token = await self._ensure_fresh_token(credentials)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(
                    spec["method"],
                    PRODUCTBOARD_API_BASE + path,
                    params=params or None,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )
            try:
                payload = response.json() if response.content else {}
            except ValueError:
                payload = {"text": response.text}
            result = {
                "status": "error" if response.is_error else "success",
                "action": operation,
                "timing_ms": {
                    "api_request": round((time.monotonic() - started) * 1000, 2)
                },
            }
            if response.is_error:
                result.update(
                    status_code=response.status_code,
                    error=_error_message(payload, response.status_code),
                    error_details=payload,
                )
            elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
                result["data"] = {
                    "items": payload["data"],
                    **{key: value for key, value in payload.items() if key != "data"},
                }
            elif isinstance(payload, list):
                result["data"] = {"items": payload}
            else:
                result["data"] = payload
            return result
        except httpx.HTTPError as exc:
            logger.warning("Productboard request failed: %s", type(exc).__name__)
            return {
                "status": "error",
                "action": operation,
                "status_code": 502,
                "error": f"Productboard request failed ({type(exc).__name__})",
                "timing_ms": {
                    "api_request": round((time.monotonic() - started) * 1000, 2)
                },
            }
