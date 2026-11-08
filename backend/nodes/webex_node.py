"""Webex messaging, meeting, invitee, and recording workflow actions."""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.webex import WEBEX_SCOPES
from nodes.webex_operations import WEBEX_CATALOG


_catalog = WEBEX_CATALOG
OPERATIONS: dict[str, dict[str, Any]] = {op["name"]: op for op in _catalog["operations"]}
assert len(OPERATIONS) == len(_catalog["operations"]), "Duplicate Webex operation"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
_BASE_URL = "https://webexapis.com/v1"
WEBEX_OAUTH_SCOPES = WEBEX_SCOPES.declared_scopes()


class WebexOAuthCredential(BaseModel):
    """User delegated Webex token, refreshed by the workflow runtime."""

    credential_type: Literal["webex_oauth"] = Field(
        "webex_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Expiration")
    user_id: Optional[str] = Field(None, title="Webex User ID")
    email: Optional[str] = Field(None, title="Email")

    model_config = ConfigDict(title="Webex Account", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "webex",
        "x-oauth-scopes": WEBEX_OAUTH_SCOPES,
        "x-credential-url": "https://developer.webex.com/my-apps/new/integration",
        "x-credential-instructions": "Connect your Webex account to use spaces, messages, meetings, and recordings.",
    })


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={
                "const": name, "ui:hidden": True,
                "x-category": op["category"], "x-display-name": op["label"],
                "x-is-trigger": False,
            },
        )),
    }
    for raw in op["path_params"]:
        fields[_field_name("path", raw)] = (
            str, Field(..., title=re.sub(r"(?<!^)(?=[A-Z])", " ", raw).title()),
        )
    for raw in op["required_query"]:
        fields[_field_name("query", raw)] = (str, Field(..., title=raw.replace("_", " ").title()))
    fields["query_json"] = (
        Optional[str], Field(None, title="Other Query Parameters (JSON)",
                             description="Optional filters and pagination from the Webex API reference.",
                             json_schema_extra=_JSON_EDITOR),
    )
    if op["body_type"] == "application/json":
        description = "JSON request body from the Webex API reference."
        if op["body_required_fields"]:
            description += " Required keys: " + ", ".join(op["body_required_fields"]) + "."
        required = op["body_required"] or bool(op["body_required_fields"])
        fields["body_json"] = (
            str if required else Optional[str],
            Field(... if required else None, title="Request Body (JSON)",
                  description=description, json_schema_extra=_JSON_EDITOR),
        )
    return create_model(
        "Webex" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
WebexConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class WebexNodeConfig(NodeConfig[WebexConfig, WebexOAuthCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: Optional[str], label: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc


class WebexNode(WorkflowNode):
    """Run one of the supported Webex messaging or meeting actions."""

    integration_type = "automation-webex"
    scope_registry = WEBEX_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_rooms", noun="spaces",
        identity_operation="get_my_own_details",
    )
    edit_examples = [
        "List my Webex spaces", "Post a message to a Webex space",
        "Schedule a Webex meeting", "List my Webex recordings",
    ]

    @classmethod
    def get_config_model(cls):
        return WebexNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data or credential_data.get("credential_type") != "webex_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.webex_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="webex",
        )

    async def _access_token(self, credential: WebexOAuthCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.webex_oauth import refresh_access_token

        data = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=data,
            refresh=refresh_access_token, provider="webex", caller_path="execute",
        )
        credential.access_token = data["access_token"]
        credential.refresh_token = data.get("refresh_token") or credential.refresh_token
        credential.expires_at = data.get("expires_at")
        return credential.access_token

    @staticmethod
    async def _request(token: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
        op = OPERATIONS[name]
        path = op["path"]
        for raw in op["path_params"]:
            value = values.pop(_field_name("path", raw), None)
            if value is None or str(value).strip() in {"", ".", ".."}:
                raise ValueError(f"{raw} is required")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        params = _parse_json(values.pop("query_json", None), "Query Parameters") or {}
        if not isinstance(params, dict):
            raise ValueError("Query Parameters must be a JSON object")
        for raw in op["required_query"]:
            params[raw] = values.pop(_field_name("query", raw))
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        kwargs: dict[str, Any] = {}
        if op["body_type"] == "application/json":
            body = _parse_json(values.pop("body_json", None), "Request Body")
            if op["body_required"] and body is None:
                raise ValueError("Request Body is required")
            missing = [key for key in op["body_required_fields"]
                       if not isinstance(body, dict) or key not in body]
            if missing:
                raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
            if body is not None:
                kwargs["json"] = body
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(op["method"], _BASE_URL + path,
                                            params=params or None, headers=headers, **kwargs)
        if not response.content:
            data: Any = {}
        elif response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
        else:
            try:
                data = response.json()
            except ValueError:
                data = BinaryOutput(
                    data=response.content,
                    content_type=response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip() or "application/octet-stream",
                    filename=f"webex-{name}",
                )
        if response.is_error or response.is_redirect:
            detail = data.get("message") or data.get("error") if isinstance(data, dict) else None
            raise ValueError(f"Webex API error {response.status_code}: {detail or 'request failed'}")
        return {
            "status": "success", "operation": name, "status_code": response.status_code,
            "data": data, "next_page": response.links.get("next", {}).get("url"),
            "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, WebexNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Webex account before running this action")
        credential = self.config.credentials
        token = await self._access_token(credential)
        config = self.config.config
        return await self._request(token, config.operation, config.model_dump(exclude_none=True))
