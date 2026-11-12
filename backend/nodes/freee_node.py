"""freee Accounting v1 single-request operations against its official OpenAPI.

Lists return one page; use offset/limit explicitly. Writes are never retried.
Updating deal details replaces all lines: include every line to retain with ID.
"""
from __future__ import annotations
from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.freee_operations import FREEE_OPERATIONS
from nodes.scopes.freee import FREEE_SCOPES


class FreeeOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Freee OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "freee",
        "x-oauth-scopes": sorted(FREEE_SCOPES.declared_scopes()),
        "x-credential-url": "https://app.secure.freee.co.jp/developers",
    })
    credential_type: Literal["freee_oauth"] = Field("freee_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = None
    scope: Optional[str] = None

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if any(c.isspace() for c in value):
            raise ValueError("Use a token without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


# Freee's own MCP server: agents get its tools through a person's Freee sign-in.
FreeeMcpCredential = mcp_credential("freee", "https://mcp.freee.co.jp/mcp", app="Freee")
FreeeCredential = Union[FreeeOAuthCredential, FreeeMcpCredential]


def _annotation(schema, name):
    kind = schema.get("type")
    if "enum" in schema:
        annotation = Literal[tuple(schema["enum"])]
    elif kind == "object":
        annotation = _object_model(schema, name)
    elif kind == "array":
        annotation = list[_annotation(schema["items"], name + "Item")]
    else:
        annotation = {"integer": int, "number": float, "boolean": bool, "string": str}[kind]
    constraints = {target: schema[key] for key, target in (
        ("minimum", "ge"), ("maximum", "le"), ("minLength", "min_length"),
        ("maxLength", "max_length"), ("minItems", "min_length"),
        ("maxItems", "max_length"), ("pattern", "pattern"),
    ) if key in schema}
    annotation = Annotated[annotation, Field(**constraints)]
    return Optional[annotation] if schema.get("nullable") else annotation


def _object_model(schema, name):
    required = schema.get("required", [])
    return create_model(name, __base__=_Input, **{
        key: (_annotation(value, name + key.title()), Field(
            ... if key in required else None, json_schema_extra={"examples": value.get("examples", [])}
        )) for key, value in schema.get("properties", {}).items()
    })


def _operation_model(name, spec):
    fields = {"operation": (Literal[name], Field(name, title=name.replace("_", " ").title(), json_schema_extra={
        "ui:hidden": True, "x-display-name": name.replace("_", " ").title(),
        "x-category": "Accounting", "x-is-trigger": False,
    }))}
    for parameter in spec["parameters"]:
        key = parameter["name"]
        fields[key] = (_annotation(parameter["schema"], name + key.title()), Field(
            ... if parameter["required"] else None,
            description="Freee resource ID." if parameter["in"] == "path" else "Documented query parameter; lists return one page.",
            json_schema_extra={"examples": parameter["schema"].get("examples", [])},
        ))
    body = spec.get("body", {})
    for key, schema in body.get("properties", {}).items():
        annotation = _annotation(schema, name + key.title())
        extra = {"examples": schema.get("examples", [])}
        if schema.get("type") in {"object", "array"}:
            annotation = Json[annotation]
            extra.update({"ui:widget": "code_editor", "x-code-language": "json"})
        description = "Documented request body field."
        if key == "details" and name == "update_deal":
            description = "JSON array replacing ALL deal lines. Include existing line IDs for every line to retain."
        fields[key] = (annotation, Field(... if key in body.get("required", []) else None,
            description=description, json_schema_extra=extra))
    return create_model("Freee" + name.title().replace("_", "") + "Config", __base__=_Input, **fields)


_MODELS = tuple(_operation_model(name, spec) for name, spec in FREEE_OPERATIONS.items())
FreeeConfig = Annotated[Union[_MODELS], Field(discriminator="operation")]


class FreeeFullConfig(NodeConfig[FreeeConfig, FreeeCredential]):
    pass


class FreeeNode(WorkflowNode):
    integration_type = "automation-freee"
    credential_provider_labels = {"freee": "Freee Account"}
    scope_registry = FREEE_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="companies", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return FreeeFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.freee_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="freee")

    async def _token(self, credential):
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.freee_oauth import refresh_access_token
        data = credential.model_dump()
        await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=data, refresh=refresh_access_token,
            provider="freee", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in data:
                setattr(credential, key, data[key])
        return credential.access_token

    async def execute(self, inputs):
        if not isinstance(self.config, FreeeFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Freee account")
        config = self.config.config
        spec = FREEE_OPERATIONS[config.operation]
        values = config.model_dump(exclude_unset=True)
        path, params = spec["path"], {}
        for parameter in spec["parameters"]:
            key = parameter["name"]
            value = values.get(key)
            if value is None:
                continue
            if parameter["in"] == "path":
                path = path.replace("{" + key + "}", str(value))
            else:
                params[key] = value
        body = {key: values[key] for key in spec.get("body", {}).get("properties", {}) if key in values}
        token = await self._token(self.config.credentials)
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(spec["method"], "https://api.freee.co.jp" + path,
                    params=params or None, json=body if "body" in spec else None,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        except httpx.HTTPError:
            return {"status": "error", "error": "Freee request failed; check connection before retrying a write."}
        if len(response.content) > 8_000_000:
            raise ValueError("Freee response exceeds the JSON size limit")
        if not 200 <= response.status_code < 300:
            messages = []
            try:
                error = response.json()
                if isinstance(error, dict):
                    for key in ("message", "messages"):
                        value = error.get(key)
                        messages.extend([value] if isinstance(value, str) else value if isinstance(value, list) else [])
                    if isinstance(error.get("errors"), list):
                        for item in error["errors"]:
                            if isinstance(item, dict) and isinstance(item.get("messages"), list):
                                messages.extend(item["messages"])
            except ValueError:
                pass
            message = "; ".join(value for value in messages if isinstance(value, str))
            for secret in (token, self.config.credentials.refresh_token):
                if secret:
                    message = message.replace(secret, "[redacted]")
            return {"status": "error", "status_code": response.status_code,
                "error": message[:2000] or "Freee rejected the request (HTTP " + str(response.status_code) + ")."}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Freee returned invalid JSON") from None
        if not isinstance(payload, dict) or "errors" in payload or "error" in payload:
            raise ValueError("Freee returned an unexpected response")
        key = spec["response_key"]
        expected = {"array": list, "object": dict}.get(spec["response_type"])
        if key not in payload or (expected and not isinstance(payload[key], expected)):
            raise ValueError("Freee returned an unexpected resource envelope")
        result = {**payload, "status": "success"}
        if spec["response_type"] == "array":
            result["items"] = payload[key]
            result["count"] = len(payload[key])
        return result
