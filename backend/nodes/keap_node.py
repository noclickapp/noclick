"""Keap CRM, marketing, commerce, and automation API v2 actions."""

from __future__ import annotations

import base64
import binascii
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
from nodes.keap_operations import OPERATIONS
from nodes.scopes.keap import KEAP_SCOPES


API_BASE = "https://api.keap.com/crm"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class KeapOAuthCredential(BaseModel):
    """Keap account connected with a confidential OAuth app."""

    credential_type: Literal["keap_oauth"] = Field(
        "keap_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Expiration")

    model_config = ConfigDict(
        title="Keap Account",
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "keap",
            "x-oauth-scopes": sorted(KEAP_SCOPES.declared_scopes()),
        }
    )


class KeapPersonalTokenCredential(BaseModel):
    """Keap personal access token or service-account key."""

    credential_type: Literal["keap_pat"] = Field(
        "keap_pat", json_schema_extra={"ui:hidden": True}
    )
    personal_access_token: str = Field(
        ...,
        title="Personal Access Token or Service Account Key",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Keap Personal Access Token",
        json_schema_extra={
            "x-credential-url": "https://developer.keap.com/pat-and-sak/"
        }
    )


KeapCredential = Union[KeapOAuthCredential, KeapPersonalTokenCredential]


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(operation: dict[str, Any]) -> type[BaseModel]:
    name = operation["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (
            Literal[name],
            Field(
                name,
                title=operation["label"],
                description=f"{operation['method']} {operation['path']}",
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": operation["category"],
                    "x-display-name": operation["label"],
                    "x-is-trigger": False,
                },
            ),
        ),
    }
    for raw in operation["path_params"]:
        fields[_field_name("path", raw)] = (
            str,
            Field(..., title=raw.replace("_", " ").title()),
        )
    for raw in operation["required_query"]:
        fields[_field_name("query", raw)] = (
            str,
            Field(..., title=raw.replace("_", " ").title()),
        )
    fields["query_json"] = (
        Optional[str],
        Field(
            None,
            title="Other Query Parameters (JSON)",
            description="Optional filters and pagination documented by Keap.",
            json_schema_extra=_JSON_EDITOR,
        ),
    )
    if operation["body_type"] == "json":
        fields["body_json"] = (
            str if operation["body_required"] else Optional[str],
            Field(
                ... if operation["body_required"] else None,
                title="Request Body (JSON)",
                description="JSON request body from the Keap API reference.",
                json_schema_extra=_JSON_EDITOR,
            ),
        )
    elif operation["body_type"] == "multipart":
        # Keap documents multipart fields individually, rather than a JSON body:
        # https://github.com/infusionsoft/keap-sdk-php/blob/66039324bec4af130eb676a58702272e939e4519/docs/Api/FilesApi.md#createfile
        for form_field in operation["form_fields"]:
            if form_field["name"] == "file":
                continue
            required = form_field["required"]
            fields["form_" + form_field["name"]] = (
                str if required else Optional[str],
                Field(
                    ... if required else None,
                    title=form_field["name"].replace("_", " ").title(),
                    min_length=1,
                    **({"examples": ["CONTACT"]} if form_field["name"] == "file_association" else {}),
                ),
            )
        fields["file_base64"] = (
            str
            if any(
                p["required"] and p["name"] == "file" for p in operation["form_fields"]
            )
            else Optional[str],
            Field(
                ...
                if any(
                    p["required"] and p["name"] == "file"
                    for p in operation["form_fields"]
                )
                else None,
                title="File Contents (base64)",
                description=(
                    "Base64-encoded image file (image/png)."
                    if name in {"create_image_file", "create_product_image"}
                    else "Base64-encoded binary file (application/octet-stream)."
                ),
                json_schema_extra={"contentEncoding": "base64"},
            ),
        )
        fields["filename"] = (
            Optional[str],
            Field(None, title="Upload Filename"),
        )
    return create_model(
        "Keap" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__,
        **fields,
    )


CONFIG_MODELS = {
    name: _make_config(operation) for name, operation in OPERATIONS.items()
}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
KeapConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class KeapNodeConfig(NodeConfig[KeapConfig, KeapCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: Optional[str], label: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc


class KeapNode(WorkflowNode):
    """Run Keap's published REST v2 actions."""

    integration_type = "automation-keap"
    credential_provider_labels = {"keap": "Keap Account"}
    scope_registry = KEAP_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_user_info", noun="user")
    edit_examples = [
        "List Keap contacts",
        "Create a contact",
        "List opportunities",
        "Add a tag to a contact",
        "List automation campaigns",
    ]

    @classmethod
    def get_config_model(cls):
        return KeapNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.keap_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="keap",
        )

    async def _access_token(self, credential: KeapCredential) -> str:
        if isinstance(credential, KeapPersonalTokenCredential):
            return credential.personal_access_token
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.keap_oauth import refresh_access_token

        data = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=data,
            refresh=refresh_access_token,
            provider="keap",
        )
        credential.access_token = data["access_token"]
        credential.refresh_token = data.get("refresh_token") or credential.refresh_token
        credential.expires_at = data.get("expires_at")
        return credential.access_token

    @staticmethod
    async def _request(token: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
        operation = OPERATIONS[name]
        KeapNode.scope_registry.require(name)
        path = operation["path"]
        for raw in operation["path_params"]:
            value = values.pop(_field_name("path", raw), None)
            if not value or str(value).strip() in {".", ".."}:
                raise ValueError(f"{raw} is required")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        params = _parse_json(values.pop("query_json", None), "Query Parameters") or {}
        if not isinstance(params, dict):
            raise ValueError("Query Parameters must be a JSON object")
        for raw in operation["required_query"]:
            params[raw] = values.pop(_field_name("query", raw))
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        kwargs: dict[str, Any] = {}
        if operation["body_type"] == "json":
            body = _parse_json(values.pop("body_json", None), "Request Body")
            if operation["body_required"] and body is None:
                raise ValueError("Request Body is required")
            if body is not None:
                kwargs["json"] = body
        elif operation["body_type"] == "multipart":
            form = {
                field["name"]: values.pop("form_" + field["name"])
                for field in operation["form_fields"]
                if field["name"] != "file" and values.get("form_" + field["name"]) is not None
            }
            required = [
                field["name"] for field in operation["form_fields"]
                if field["required"] and field["name"] != "file" and field["name"] not in form
            ]
            if required:
                raise ValueError("Missing required form fields: " + ", ".join(required))
            file_base64 = values.pop("file_base64", None)
            if not file_base64 and any(
                p["required"] and p["name"] == "file" for p in operation["form_fields"]
            ):
                raise ValueError("File Contents are required")
            if file_base64:
                try:
                    content = base64.b64decode(file_base64, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ValueError("File Contents must be valid base64") from exc
                filename = (
                    values.pop("filename", None)
                    or form.get("file_name")
                    or "upload.bin"
                )
                kwargs["files"] = {"file": (str(filename), content)}
            kwargs["data"] = {
                key: str(value).lower() if isinstance(value, bool) else str(value)
                for key, value in form.items()
            }
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                operation["method"],
                API_BASE + path,
                params=params or None,
                headers=headers,
                **kwargs,
            )
        content_type = response.headers.get("content-type", "")
        if not response.content:
            data: Any = {}
        elif "json" in content_type:
            data = response.json()
        elif content_type.startswith("text/"):
            data = {"text": response.text}
        else:
            data = BinaryOutput(
                data=response.content,
                content_type=content_type or "application/octet-stream",
                filename="keap-download",
            )
        if response.is_error or response.is_redirect:
            detail = (
                data.get("message") or data.get("error")
                if isinstance(data, dict)
                else None
            )
            raise ValueError(
                f"Keap API error {response.status_code}: {detail or 'request failed'}"
            )
        return {
            "status": "success",
            "operation": name,
            "status_code": response.status_code,
            "data": data,
            "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, KeapNodeConfig) or not self.config.credentials:
            raise ValueError(
                "Connect a Keap account or personal token before running this action"
            )
        token = await self._access_token(self.config.credentials)
        config = self.config.config
        return await self._request(
            token, config.operation, config.model_dump(exclude_none=True)
        )
