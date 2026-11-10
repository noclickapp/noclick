"""Google Chat workflow actions from the official, pinned discovery document."""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.google_chat import CHAT_SCOPES, OPERATIONS


API_BASE = "https://chat.googleapis.com/"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class GoogleChatOAuthCredential(BaseModel):
    """User-delegated Google OAuth credential with automatic token refresh."""

    credential_type: Literal["google_oauth"] = Field(
        "google_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    email: str = Field(..., title="Google Account")
    scope: Optional[str] = Field(None, title="Granted Scopes", json_schema_extra={"ui:hidden": True})
    client_id: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    client_secret: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})

    model_config = ConfigDict(title="Google Chat Account", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "google",
        "x-oauth-scopes": CHAT_SCOPES.declared_scopes(),
        "x-credential-url": "https://console.cloud.google.com/apis/credentials",
    })


def _field_name(prefix: str, raw: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def _required(param: dict[str, Any]) -> bool:
    # Discovery marks some required query parameters only in their descriptions.
    return param["required"] or param["description"].startswith("Required.")


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={"const": name, "ui:hidden": True,
                               "x-category": op["category"],
                               "x-display-name": op["label"], "x-is-trigger": False},
        )),
    }
    for prefix, params in (("path", op["path_params"]), ("query", op["query_params"])):
        for param in params:
            required = _required(param)
            fields[_field_name(prefix, param["name"])] = (
                str if required else Optional[str],
                Field(... if required else None, min_length=1 if required else None,
                      title=param["name"].replace("_", " ").title(),
                      description=param["description"]),
            )
    if op["body_json"]:
        description = "JSON request body for this Google Chat method."
        if op["body_required_fields"]:
            description += " Required keys: " + ", ".join(op["body_required_fields"]) + "."
        fields["body_json"] = (
            str, Field(..., title="Request Body (JSON)", description=description,
                       json_schema_extra=_JSON_EDITOR),
        )
    return create_model(
        "GoogleChat" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
GoogleChatConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class GoogleChatNodeConfig(NodeConfig[GoogleChatConfig, GoogleChatOAuthCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _resource_path(raw: str) -> str:
    """Keep resource-name slashes while encoding query/fragment and traversal."""
    value = raw.strip("/")
    if not value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("Invalid Google Chat resource name")
    return quote(value, safe="/")


def _body(raw: Optional[str], required_fields: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError) as exc:
        raise ValueError("Request Body must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Request Body must be a JSON object")
    missing = [key for key in required_fields if key not in value]
    if missing:
        raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
    return value


class GoogleChatNode(WorkflowNode):
    """Manage spaces, messages, members, reactions, pins, and events in Chat."""

    integration_type = "automation-google-chat"
    borrowed_credential_types = frozenset({"google_oauth"})
    scope_registry = CHAT_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_spaces", noun="spaces")
    edit_examples = [
        "List my Google Chat spaces", "Send a message to a space",
        "Search messages in a Google Chat space", "Add a member to a space",
    ]

    @classmethod
    def get_config_model(cls):
        return GoogleChatNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None,
                                 credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="google",
        )

    async def _ensure_token(self, credential: GoogleChatOAuthCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token

        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=data, refresh=refresh_access_token,
            provider="google", caller_path="execute",
        )
        credential.access_token = data["access_token"]
        credential.expires_at = data.get("expires_at")
        if data.get("refresh_token"):
            credential.refresh_token = data["refresh_token"]
        return token

    @staticmethod
    async def _request(token: str, operation: str, values: dict[str, Any]) -> dict[str, Any]:
        spec = OPERATIONS[operation]
        path = spec["path"]
        for param in spec["path_params"]:
            name = param["name"]
            value = values.pop(_field_name("path", name), None)
            if value is None:
                raise ValueError(f"{name} is required")
            path = path.replace("{+" + name + "}", _resource_path(value))
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        params = {}
        for param in spec["query_params"]:
            name = param["name"]
            value = values.pop(_field_name("query", name), None)
            if _required(param) and (value is None or value == ""):
                raise ValueError(f"{name} is required")
            if value is not None and value != "":
                params[name] = value
        options: dict[str, Any] = {}
        if spec["body_json"]:
            options["json"] = _body(values.pop("body_json", None), spec["body_required_fields"])
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(
                spec["method"], API_BASE + path,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params=params or None, **options,
            )
        try:
            data: Any = response.json() if response.content else {}
        except ValueError:
            data = {"text": response.text[:2000]}
        if response.is_error or response.is_redirect:
            error = data.get("error") if isinstance(data, dict) else None
            message = (error.get("message") if isinstance(error, dict) else None) or (
                data.get("message") if isinstance(data, dict) else None)
            raise ValueError(f"Google Chat API error {response.status_code}: {message or 'request failed'}")
        return {"status": "success", "operation": operation, "status_code": response.status_code,
                "data": data, "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)}}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, GoogleChatNodeConfig) or not self.config.credentials:
            raise ValueError("Connect Google Chat with OAuth before running this node")
        credential = self.config.credentials
        token = await self._ensure_token(credential)
        config = self.config.config
        return await self._request(
            token, config.operation, config.model_dump(exclude={"operation"}, exclude_none=True),
        )
