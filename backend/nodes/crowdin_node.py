"""Crowdin API v2 workflow actions from the official file-based OpenAPI catalog."""

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


from nodes.crowdin_operations import OPERATIONS
from nodes.scopes.crowdin import CROWDIN_SCOPES
from nodes.core.binary_output import BinaryOutput


_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
_ORG_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")


class CrowdinOAuthCredential(BaseModel):
    """Button-connected Crowdin or Crowdin Enterprise account."""

    credential_type: Literal["crowdin_oauth"] = Field(
        "crowdin_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Expiration")
    organization_domain: Optional[str] = Field(
        None, title="Enterprise Organization Domain"
    )

    model_config = ConfigDict(
        title="Crowdin OAuth",
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "crowdin",
            "x-oauth-scopes": sorted(CROWDIN_SCOPES.declared_scopes()),
        }
    )


class CrowdinPersonalTokenCredential(BaseModel):
    """Crowdin personal access token, optionally scoped to an Enterprise org."""

    credential_type: Literal["crowdin_pat"] = Field(
        "crowdin_pat", json_schema_extra={"ui:hidden": True}
    )
    personal_access_token: str = Field(
        ...,
        title="Personal Access Token",
        json_schema_extra={"ui:widget": "password"},
    )
    organization_domain: Optional[str] = Field(
        None,
        title="Enterprise Organization Domain",
        description="Only for Crowdin Enterprise. Enter the organization subdomain.",
    )

    model_config = ConfigDict(
        title="Crowdin Personal Access Token",
        json_schema_extra={
            "x-credential-url": "https://crowdin.com/settings#api-key",
        }
    )


CrowdinCredential = Union[CrowdinOAuthCredential, CrowdinPersonalTokenCredential]


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
                description=operation["description"],
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
        extra = {}
        if raw == "projectId":
            extra = {
                "x-dynamic-options": {
                    "field_name": "path_projectid",
                    "placeholder": "Select a project...",
                    "searchable": True,
                    "allow_custom": True,
                }
            }
        fields[_field_name("path", raw)] = (
            str,
            Field(..., title=raw.replace("_", " ").title(), json_schema_extra=extra),
        )
    for raw in operation["required_query"]:
        fields[_field_name("query", raw)] = (
            str,
            Field(..., title=raw.replace("_", " ").title()),
        )
    for raw in operation["required_headers"]:
        fields[_field_name("header", raw)] = (
            str,
            Field(..., title=raw.replace("-", " ").title()),
        )
    fields["query_json"] = (
        Optional[str],
        Field(
            None,
            title="Other Query Parameters (JSON)",
            description="Optional filters and pagination from the Crowdin API reference.",
            json_schema_extra=_JSON_EDITOR,
        ),
    )
    if operation["body_type"] == "json":
        description = "JSON request body from the Crowdin API reference."
        if operation["body_required_fields"]:
            description += (
                " Required keys: " + ", ".join(operation["body_required_fields"]) + "."
            )
        fields["body_json"] = (
            str if operation["body_required"] else Optional[str],
            Field(
                ... if operation["body_required"] else None,
                title="Request Body (JSON)",
                description=description,
                json_schema_extra=_JSON_EDITOR,
            ),
        )
    elif operation["body_type"] == "binary":
        fields["body_base64"] = (
            str if operation["body_required"] else Optional[str],
            Field(
                ... if operation["body_required"] else None,
                title="File Contents (base64)",
                description="Base64-encoded file contents for Crowdin storage.",
            ),
        )
    elif operation["body_type"] == "text":
        fields["body_text"] = (
            str if operation["body_required"] else Optional[str],
            Field(
                ... if operation["body_required"] else None,
                title="Request Text",
                json_schema_extra={"ui:widget": "textarea"},
            ),
        )
    return create_model(
        "Crowdin" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__,
        **fields,
    )


CONFIG_MODELS = {
    name: _make_config(operation) for name, operation in OPERATIONS.items()
}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
CrowdinConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")
]


class CrowdinNodeConfig(NodeConfig[CrowdinConfig, CrowdinCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _base_url(organization_domain: Optional[str]) -> str:
    if not organization_domain:
        return "https://api.crowdin.com/api/v2"
    if not _ORG_RE.fullmatch(organization_domain):
        raise ValueError("Enterprise organization domain must be a Crowdin subdomain")
    return f"https://{organization_domain}.api.crowdin.com/api/v2"


def _parse_json(raw: Optional[str], label: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc


class CrowdinNode(WorkflowNode):
    """Run Crowdin's file-based API v2 operations."""

    integration_type = "automation-crowdin"
    credential_provider_labels = {"crowdin": "Crowdin Account"}
    scope_registry = CROWDIN_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_current_user", noun="user")
    edit_examples = [
        "List Crowdin projects",
        "List project files",
        "Add a source string",
        "Build project translations",
        "List translation tasks",
    ]

    @classmethod
    def get_config_model(cls):
        return CrowdinNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[dict[str, str]]:
        if field_name != "path_projectid":
            return []
        token = credential_data.get("access_token") or credential_data.get(
            "personal_access_token"
        )
        if not token:
            return []
        params = {"limit": 100}
        if page_token:
            params["offset"] = page_token
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.get(
                _base_url(credential_data.get("organization_domain")) + "/projects",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                params=params,
            )
        response.raise_for_status()
        options = [
            {"value": str(item["data"]["id"]), "label": item["data"]["name"]}
            for item in response.json().get("data", [])
            if isinstance(item, dict) and isinstance(item.get("data"), dict)
        ]
        if search:
            needle = search.casefold()
            options = [
                option for option in options
                if needle in option["label"].casefold()
                or needle in option["value"]
            ]
        return options

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if credential_data.get("credential_type") != "crowdin_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.crowdin_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="crowdin",
        )

    async def _access_token(self, credential: CrowdinCredential) -> str:
        if isinstance(credential, CrowdinPersonalTokenCredential):
            return credential.personal_access_token
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.crowdin_oauth import refresh_access_token

        data = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=data,
            refresh=refresh_access_token,
            provider="crowdin",
            caller_path="execute",
        )
        credential.access_token = data["access_token"]
        credential.refresh_token = data.get("refresh_token") or credential.refresh_token
        credential.expires_at = data.get("expires_at")
        return credential.access_token

    @staticmethod
    async def _request(
        token: str,
        organization_domain: Optional[str],
        name: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        operation = OPERATIONS[name]
        CrowdinNode.scope_registry.require(name)
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
        for raw in operation["required_headers"]:
            headers[raw] = values.pop(_field_name("header", raw))
        kwargs: dict[str, Any] = {}
        if operation["body_type"] == "json":
            body = _parse_json(values.pop("body_json", None), "Request Body")
            if operation["body_required"] and body is None:
                raise ValueError("Request Body is required")
            missing = [
                key
                for key in operation["body_required_fields"]
                if not isinstance(body, dict) or key not in body
            ]
            if missing:
                raise ValueError(
                    "Request Body is missing required keys: " + ", ".join(missing)
                )
            if body is not None:
                kwargs["json"] = body
        elif operation["body_type"] == "binary":
            raw = values.pop("body_base64", None)
            if operation["body_required"] and not raw:
                raise ValueError("File Contents are required")
            if raw:
                try:
                    kwargs["content"] = base64.b64decode(raw, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ValueError("File Contents must be valid base64") from exc
                headers["Content-Type"] = "application/octet-stream"
        elif operation["body_type"] == "text":
            raw = values.pop("body_text", None)
            if operation["body_required"] and raw is None:
                raise ValueError("Request Text is required")
            if raw is not None:
                kwargs["content"] = raw.encode()
                headers["Content-Type"] = "text/plain"
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                operation["method"],
                _base_url(organization_domain) + path,
                params=params or None,
                headers=headers,
                **kwargs,
            )
        if not response.content:
            data: Any = {}
        elif response.headers.get("content-type", "").startswith(
            "application/octet-stream"
        ):
            data = BinaryOutput(data=response.content, content_type=response.headers["content-type"], filename="crowdin-download")
        else:
            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text}
        if response.is_error or response.is_redirect:
            detail = (
                data.get("error") or data.get("message")
                if isinstance(data, dict)
                else None
            )
            raise ValueError(
                f"Crowdin API error {response.status_code}: {detail or 'request failed'}"
            )
        return {
            "status": "success",
            "operation": name,
            "status_code": response.status_code,
            "data": data,
            "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(self.config, CrowdinNodeConfig)
            or not self.config.credentials
        ):
            raise ValueError(
                "Connect a Crowdin account or personal token before running this action"
            )
        credential = self.config.credentials
        token = await self._access_token(credential)
        config = self.config.config
        return await self._request(
            token,
            credential.organization_domain,
            config.operation,
            config.model_dump(exclude_none=True),
        )
