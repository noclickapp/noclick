"""Omnisend contacts, campaigns, products, events, and automation actions."""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.omnisend_operations import CATALOG
from nodes.scopes.omnisend import OMNISEND_SCOPES
from nodes.oauth.omnisend_oauth import refresh_access_token
from nodes.core.oauth_refresh import ensure_fresh_oauth_token, freshen_oauth_credential


_catalog = CATALOG
OPERATIONS: dict[str, dict[str, Any]] = {op["name"]: op for op in _catalog["operations"]}
assert len(OPERATIONS) == len(_catalog["operations"]), "Duplicate Omnisend operation"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
_BASE_URL = "https://api.omnisend.com/api"
_API_VERSION = "2026-03-15"


class OmnisendApiKeyCredential(BaseModel):
    """Omnisend API key with resource permissions selected in Omnisend."""

    credential_type: Literal["omnisend_api_key"] = Field(
        "omnisend_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="Omnisend API Key",
        description="Paste an API key with permissions for the operations this workflow uses.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(title="Omnisend API Key", json_schema_extra={
        "x-credential-url": "https://app.omnisend.com/integrations/api-keys",
        "x-credential-instructions": (
            "Sign in to Omnisend, open Integrations > API keys, create an API key, "
            "select permissions for the operations this workflow uses, and copy it immediately."
        ),
    })


class OmnisendOAuthCredential(BaseModel):
    credential_type: Literal["omnisend_oauth"] = Field(
        "omnisend_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    scope: Optional[str] = Field(None, title="Granted Scopes")
    name: Optional[str] = Field(None, title="Brand Name")

    model_config = ConfigDict(
        title="Omnisend OAuth",
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "omnisend",
            "x-oauth-scopes": sorted(OMNISEND_SCOPES.declared_scopes()),
        },
    )


OmnisendCredential = Union[OmnisendApiKeyCredential, OmnisendOAuthCredential]


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
                             description="Optional filters and pagination from the Omnisend API reference.",
                             json_schema_extra=_JSON_EDITOR),
    )
    if op["body_type"] == "application/json":
        description = "JSON request body from the Omnisend API reference."
        if op["body_required_fields"]:
            description += " Required keys: " + ", ".join(op["body_required_fields"]) + "."
        required = op["body_required"] or bool(op["body_required_fields"])
        fields["body_json"] = (
            str if required else Optional[str],
            Field(... if required else None, title="Request Body (JSON)",
                  description=description, json_schema_extra=_JSON_EDITOR),
        )
    elif op["body_type"] == "multipart/form-data":
        fields["file_base64"] = (
            str, Field(..., title="Image (Base64)",
                       description="Base64-encoded JPEG, PNG, GIF, or WebP image, maximum 5 MB."),
        )
        fields["file_name"] = (
            str, Field(..., title="File Name", description="Image filename, such as product.png."),
        )
        fields["image_name"] = (Optional[str], Field(None, title="Image Name"))
    return create_model(
        "Omnisend" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
OmnisendConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class OmnisendNodeConfig(NodeConfig[OmnisendConfig, OmnisendCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: Optional[str], label: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc


class OmnisendNode(WorkflowNode):
    """Run an Omnisend API action."""

    integration_type = "automation-omnisend"
    scope_registry = OMNISEND_SCOPES
    credential_provider_labels = {"omnisend": "Omnisend Account"}

    connection_evidence = ConnectionEvidence(operation="list_contacts", noun="contacts")
    edit_examples = [
        "List Omnisend contacts", "Create or update a contact",
        "Send an email campaign", "Look up segment statistics",
    ]

    @classmethod
    def get_config_model(cls):
        return OmnisendNodeConfig

    @staticmethod
    async def _request(token: str, name: str, values: dict[str, Any], *, oauth: bool = False) -> dict[str, Any]:
        op = OPERATIONS[name]
        if name == "post_brands_current" and not oauth:
            raise ValueError("Connect brand requires an Omnisend OAuth account")
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
        headers = {
            "Authorization": f"Bearer {token}" if oauth else f"Omnisend-API-Key {token}", "Accept": "application/json",
            "Omnisend-Version": _API_VERSION,
        }
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
        elif op["body_type"] == "multipart/form-data":
            raw = values.pop("file_base64", "")
            try:
                content = base64.b64decode(raw, validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise ValueError("Image must contain valid Base64") from exc
            if not content or len(content) > 5 * 1024 * 1024:
                raise ValueError("Image must be between 1 byte and 5 MB")
            filename = values.pop("file_name", "")
            if not filename or "/" in filename or "\\" in filename:
                raise ValueError("File Name must be a plain filename")
            kwargs["files"] = {"file": (filename, content)}
            if values.get("image_name"):
                kwargs["data"] = {"name": values["image_name"]}
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(op["method"], _BASE_URL + path,
                                            params=params or None, headers=headers, **kwargs)
        if not response.content:
            data: Any = {}
        elif "json" in response.headers.get("content-type", ""):
            data = response.json()
        else:
            try:
                data = response.json()
            except ValueError:
                data = BinaryOutput(
                    data=response.content,
                    content_type=response.headers.get("content-type") or "application/octet-stream",
                    filename=f"omnisend-{name}",
                )
        if response.is_error or response.is_redirect:
            detail = (data.get("detail") or data.get("message") or data.get("error") or data.get("title")) if isinstance(data, dict) else None
            raise ValueError(f"Omnisend API error {response.status_code}: {detail or 'request failed'}")
        paging = data.get("paging") or {} if isinstance(data, dict) else {}
        cursors = paging.get("cursors") or {} if isinstance(paging, dict) else {}
        return {
            "status": "success", "operation": name, "status_code": response.status_code,
            "data": data, "next_cursor": cursors.get("after"),
            "has_more": paging.get("hasMore"),
            "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        if credential_data.get("credential_type") != "omnisend_oauth":
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="omnisend",
        )

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, OmnisendNodeConfig) or not self.config.credentials:
            raise ValueError("Connect an Omnisend account before running this action")
        config = self.config.config
        credential = self.config.credentials
        oauth = isinstance(credential, OmnisendOAuthCredential)
        if oauth:
            current = credential.model_dump()
            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id, credential=current,
                refresh=refresh_access_token, provider="omnisend",
            )
            credential.access_token = current["access_token"]
            credential.refresh_token = current.get("refresh_token")
            credential.expires_at = current.get("expires_at")
        return await self._request(
            credential.access_token if oauth else credential.api_key,
            config.operation, config.model_dump(exclude_none=True), oauth=oauth,
        )
