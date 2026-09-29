"""Connecteam workforce automation from the official API reference.

The operation catalog is a compact snapshot of the published OpenAPI endpoint
definitions at https://developer.connecteam.com/llms.txt. It intentionally
excludes incoming webhook event payloads and the OAuth token endpoint.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

logger = logging.getLogger(__name__)

_BASE_URLS = {
    "global": "https://api.connecteam.com",
    "australia": "https://api-au.connecteam.com",
}
_CATALOG = json.loads(
    Path(__file__).with_name("connecteam_operations.json").read_text()
)
CONNECTEAM_OPERATIONS = {item["operation"]: item for item in _CATALOG}
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


class ConnecteamApiKeyCredential(BaseModel):
    """A Connecteam API key from Settings > API Keys."""

    credential_type: Literal["connecteam_api_key"] = Field(
        "connecteam_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API key", json_schema_extra={"ui:widget": "password"}
    )
    region: Literal["global", "australia"] = Field(
        "global",
        title="Account region",
        description="Choose Australia if you sign in at app-au.connecteam.com.",
    )
    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developer.connecteam.com/docs/authentication-1"
        }
    )


class ConnecteamOAuthClientCredential(BaseModel):
    """Account-owned OAuth 2.0 client credentials (server-to-server grant)."""

    credential_type: Literal["connecteam_oauth_client"] = Field(
        "connecteam_oauth_client", json_schema_extra={"ui:hidden": True}
    )
    client_id: str = Field(..., title="Client ID")
    client_secret: str = Field(
        ..., title="Client secret", json_schema_extra={"ui:widget": "password"}
    )
    region: Literal["global", "australia"] = Field(
        "global",
        title="Account region",
        description="Choose Australia if you sign in at app-au.connecteam.com.",
    )
    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developer.connecteam.com/docs/oauth-20"
        }
    )


ConnecteamCredential = Union[
    ConnecteamApiKeyCredential, ConnecteamOAuthClientCredential
]


def _parameter_field(parameter: dict[str, Any]) -> tuple[Any, Field]:
    kind = parameter["type"]
    annotation: Any = {
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list[str],
    }.get(kind, str)
    required = parameter["required"]
    if not required:
        annotation = Optional[annotation]
    return annotation, Field(
        ... if required else None,
        title=parameter["name"],
        description=parameter["description"] or f"{parameter['in'].title()} parameter",
    )


def _operation_model(spec: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, Any] = {
        "operation": (
            Literal[spec["operation"]],
            Field(
                spec["operation"],
                title=spec["title"],
                description=spec["description"],
                json_schema_extra={
                    "const": spec["operation"],
                    "ui:hidden": True,
                    "x-category": spec["category"],
                    "x-display-name": spec["title"],
                },
            ),
        )
    }
    for parameter in spec["parameters"]:
        fields[parameter["name"]] = _parameter_field(parameter)
    if (
        spec["body_required"]
        or spec["method"] in ("POST", "PUT", "DELETE")
        and spec["body_description"]
    ):
        fields["body"] = (
            str if spec["body_required"] else Optional[str],
            Field(
                ... if spec["body_required"] else None,
                title="JSON body",
                description=spec["body_description"]
                or "JSON request body, including all required fields.",
                json_schema_extra={"ui:widget": "textarea"},
            ),
        )
    return create_model(
        "Connecteam"
        + "".join(part.capitalize() for part in spec["operation"].split("_"))
        + "Config",
        __doc__=spec["description"] or spec["title"],
        **fields,
    )


CONNECTEAM_CONFIGS = {
    name: _operation_model(spec) for name, spec in CONNECTEAM_OPERATIONS.items()
}
ConnecteamConfig = Annotated[
    Union[tuple(CONNECTEAM_CONFIGS.values())], Field(discriminator="operation")
]


class ConnecteamNodeConfig(NodeConfig[ConnecteamConfig, ConnecteamCredential]):
    """Complete Connecteam node config and account credentials."""


def _response_payload(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {"text": response.text}


class ConnecteamNode(WorkflowNode):
    """Connecteam users, schedules, tasks, time clocks, forms, and more."""

    edit_examples = [
        "List all Connecteam users",
        "Create a quick task in Connecteam",
        "Get employee time activities for payroll",
        "List upcoming Connecteam shifts",
    ]
    connection_evidence = ConnectionEvidence(
        operation="get_account_information_me_get", noun="account information"
    )

    @classmethod
    def get_config_model(cls):
        return ConnecteamNodeConfig

    @staticmethod
    async def _auth_headers(
        credentials: ConnecteamCredential, base_url: str
    ) -> dict[str, str]:
        if isinstance(credentials, ConnecteamApiKeyCredential):
            return {"X-API-KEY": credentials.api_key}

        cache_key = hashlib.sha256(
            f"{base_url}\0{credentials.client_id}\0{credentials.client_secret}".encode()
        ).hexdigest()
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > time.monotonic() + 60:
            return {"Authorization": f"Bearer {cached[0]}"}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{base_url}/oauth/v1/token",
                auth=(credentials.client_id, credentials.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
        response.raise_for_status()
        payload = response.json()
        token = payload["access_token"]
        expires_in = max(0, int(payload.get("expires_in", 0)))
        _TOKEN_CACHE[cache_key] = (token, time.monotonic() + expires_in)
        return {"Authorization": f"Bearer {token}"}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.monotonic()
        if not self.config or not isinstance(self.config, ConnecteamNodeConfig):
            raise ValueError("Connecteam configuration is required")
        credentials = self.config.credentials
        if not credentials:
            raise ValueError("Connecteam credentials are required")
        config = self.config.config
        spec = CONNECTEAM_OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec["path"]
        query: dict[str, Any] = {}
        for parameter in spec["parameters"]:
            name = parameter["name"]
            if name not in values:
                continue
            value = values[name]
            if parameter["in"] == "path":
                path = path.replace("{" + name + "}", quote(str(value), safe=""))
            elif parameter["in"] == "query":
                query[name] = value
        if re.search(r"{[^}]+}", path):
            raise ValueError("A required Connecteam path parameter is missing")
        body = None
        if values.get("body") is not None:
            try:
                body = json.loads(values["body"])
            except (TypeError, ValueError) as exc:
                raise ValueError("Connecteam request body must be valid JSON") from exc
        base_url = _BASE_URLS[credentials.region]
        try:
            headers = await self._auth_headers(credentials, base_url)
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(
                    spec["method"],
                    base_url + path,
                    params=query,
                    json=body,
                    headers={"Accept": "application/json", **headers},
                )
            payload = _response_payload(response)
            elapsed = round((time.monotonic() - started) * 1000, 2)
            if response.is_error:
                return {
                    "status": "error",
                    "action": config.operation,
                    "status_code": response.status_code,
                    "error": payload,
                    "timing_ms": {"api_request": elapsed},
                }
            return {
                "status": "success",
                "action": config.operation,
                "data": payload,
                "timing_ms": {"api_request": elapsed},
            }
        except httpx.HTTPStatusError as exc:
            return {
                "status": "error",
                "action": config.operation,
                "status_code": exc.response.status_code,
                "error": _response_payload(exc.response),
                "timing_ms": {
                    "api_request": round((time.monotonic() - started) * 1000, 2)
                },
            }
        except httpx.HTTPError as exc:
            logger.warning(
                "Connecteam request failed for %s: %s", config.operation, exc
            )
            return {
                "status": "error",
                "action": config.operation,
                "error": str(exc),
                "status_code": 502,
                "timing_ms": {
                    "api_request": round((time.monotonic() - started) * 1000, 2)
                },
            }
