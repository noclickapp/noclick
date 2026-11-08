"""Salesloft V2 actions with OAuth and API-key authentication."""

import base64
import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.scopes.salesloft import SALESLOFT_SCOPES
from nodes.salesloft_operations import OPERATIONS, Operation

API_BASE = "https://api.salesloft.com"


class SalesloftOAuthCredential(BaseModel):
    credential_type: Literal["salesloft_oauth"] = Field("salesloft_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field(..., title="Token Expiry")
    scope: Optional[str] = Field(None, title="Granted Scopes", json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(title="Salesloft OAuth", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "salesloft",
        "x-oauth-scopes": SALESLOFT_SCOPES.declared_scopes(),
        "x-credential-url": "https://accounts.salesloft.com/oauth/applications",
    })


class SalesloftApiKeyCredential(BaseModel):
    credential_type: Literal["salesloft_api_key"] = Field("salesloft_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Salesloft API Key", json_schema_extra={
        "x-credential-instructions": "Create an API key in Salesloft Account → Your Applications → API Keys.",
        "x-credential-url": "https://accounts.salesloft.com/",
    })


SalesloftCredential = Union[SalesloftOAuthCredential, SalesloftApiKeyCredential]


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for field in re.findall(r"\{([^}]+)\}", op.path):
        fields[field] = (str, Field(..., title=field.replace("_", " ").title()))
    fields["query_json"] = (Optional[str], Field(
        None, title="Query Parameters JSON",
        description="Salesloft filters, pagination, sorting, or endpoint query parameters as a JSON object",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    if op.body_type == "application/json":
        fields["body_json"] = ((str if op.body_required else Optional[str]), Field(
            ... if op.body_required else None, title="Request Body JSON",
            description=op.description or "Salesloft JSON request body",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    elif op.body_type == "multipart/form-data":
        fields["form_json"] = ((str if op.body_required else Optional[str]), Field(
            ... if op.body_required else None, title="Form Fields JSON",
            description=("Object of Salesloft form fields. For a file, pass an object with "
                         "base64, filename, and optional content_type."),
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    return create_model(
        "Salesloft" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], Field(name, title=op.label, description=op.description,
            json_schema_extra={
            "const": name, "ui:hidden": True, "x-category": op.category,
            "x-is-trigger": False, "x-display-name": op.label,
        })),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
SalesloftConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class SalesloftNodeConfig(NodeConfig[SalesloftConfig, SalesloftCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


class SalesloftNode(WorkflowNode):
    integration_type = "automation-salesloft"
    credential_provider_labels = {"salesloft": "Salesloft Account"}
    scope_registry = SALESLOFT_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_me", noun="account")
    edit_examples = [
        "List Salesloft people", "Create a Salesloft account", "List Salesloft cadences",
        "Find Salesloft tasks", "Get Salesloft call recordings",
    ]

    @classmethod
    def get_config_model(cls):
        return SalesloftNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.salesloft_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="salesloft")

    @staticmethod
    def _parse_object(raw: Optional[str], label: str) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _param(value: Any) -> Any:
        if isinstance(value, list):
            return [SalesloftNode._param(v) for v in value]
        return json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, bool)) else str(value)

    async def _token(self, credential: SalesloftCredential) -> str:
        if isinstance(credential, SalesloftApiKeyCredential):
            return credential.api_key
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.salesloft_oauth import refresh_access_token
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=data, refresh=refresh_access_token,
            provider="salesloft", caller_path="execute")
        for field in ("access_token", "refresh_token", "expires_at", "scope"):
            setattr(credential, field, data[field])
        return token

    @staticmethod
    def _form_parts(data: dict[str, Any]) -> list[tuple[str, tuple[Optional[str], bytes | str, str]]]:
        parts = []
        for name, value in data.items():
            if isinstance(value, dict) and "base64" in value:
                try:
                    content = base64.b64decode(value["base64"], validate=True)
                except (ValueError, base64.binascii.Error) as exc:
                    raise ValueError(f"{name} must contain valid Base64") from exc
                if len(content) > 20 * 1024 * 1024:
                    raise ValueError("Salesloft upload exceeds the 20 MB workflow limit")
                parts.append((name, (str(value.get("filename") or name), content,
                                     str(value.get("content_type") or "application/octet-stream"))))
            else:
                items = value if isinstance(value, list) else [value]
                for item in items:
                    text = SalesloftNode._param(item)
                    parts.append((name, (None, text, "text/plain")))
        return parts

    @staticmethod
    async def _request(method: str, path: str, token: str, params: dict[str, Any],
                       body: Optional[dict[str, Any]], form: Optional[dict[str, Any]]) -> Any:
        kwargs: dict[str, Any] = {"params": params or None,
                                  "headers": {"Authorization": f"Bearer {token}",
                                              "Accept": "application/json"}}
        if form is not None:
            kwargs["files"] = SalesloftNode._form_parts(form)
        elif body is not None:
            kwargs["json"] = body
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.request(method, API_BASE + path, **kwargs)
        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") or payload.get("errors")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Salesloft API error {response.status_code}: {detail or 'request failed'}")
        if not response.content:
            return {"ok": True}
        if "json" in response.headers.get("content-type", "") or response.content[:1] in (b"{", b"["):
            return response.json()
        return BinaryOutput(
            data=response.content,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            filename=path.rsplit("/", 1)[-1] or "salesloft-download",
        )

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, SalesloftNodeConfig):
            raise ValueError("Salesloft configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Salesloft account")
        config = self.config.config
        self.scope_registry.require(config.operation)
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        for field in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        params = {key: self._param(value) for key, value in
                  self._parse_object(values.pop("query_json", None), "Query Parameters JSON").items()}
        body = (self._parse_object(values.pop("body_json", None), "Request Body JSON")
                if op.body_type == "application/json" else None)
        form = (self._parse_object(values.pop("form_json", None), "Form Fields JSON")
                if op.body_type == "multipart/form-data" else None)
        token = await self._token(credential)
        data = await self._request(op.method, path, token, params, body, form)
        return {"status": "success", "operation": config.operation, "data": data}
