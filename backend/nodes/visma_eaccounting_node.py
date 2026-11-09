"""Visma eAccounting v2: one documented request per operation, no write retries.

PUT operations replace records; supply every value you want to retain.
Lists return one page, with provider metadata and an explicit next page number.
"""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.visma_eaccounting import VISMA_EACCOUNTING_SCOPES
from nodes.visma_eaccounting_operations import VISMA_OPERATIONS

BASE = "https://eaccountingapi.vismaonline.com/v2"


class VismaEAccountingOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Visma eAccounting OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "visma-eaccounting",
        "x-oauth-scopes": sorted(VISMA_EACCOUNTING_SCOPES.declared_scopes()),
        "x-credential-url": "https://selfservice.developer.vismaonline.com/",
        "x-credential-instructions": "Connect Visma eAccounting and select the company to automate. Sales and purchase access are required. You can also paste an existing access token by hand.",
    })
    credential_type: Literal["visma_eaccounting_oauth"] = Field("visma_eaccounting_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = None
    scope: str | None = None

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def clean_token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


def _annotation(schema, name):
    kind = schema.get("type")
    if "enum" in schema:
        annotation = Literal[tuple(schema["enum"])]
    elif kind == "object":
        annotation = _object_model(schema, name)
    elif kind == "array":
        annotation = list[_annotation(schema["items"], name + "Row")]
    elif schema.get("format") == "uuid":
        annotation = UUID
    elif schema.get("format") == "date-time":
        annotation = datetime
    else:
        annotation = {"integer": int, "number": float, "boolean": bool, "string": str}[kind]
    constraints = {target: schema[key] for key, target in (
        ("minimum", "ge"), ("maximum", "le"), ("minLength", "min_length"), ("maxLength", "max_length"),
    ) if key in schema}
    annotation = Annotated[annotation, Field(**constraints)]
    return annotation | None if schema.get("nullable") else annotation


def _object_model(schema, name):
    return create_model(name, __base__=_Input, **{
        key: (_annotation(value, name + key), Field(... if key in schema.get("required", []) else None,
            description=value.get("description", "Documented request field.")))
        for key, value in schema.get("properties", {}).items()
    })


def _operation_model(name, spec):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={
        "ui:hidden": True, "x-display-name": name.replace("_", " ").title(),
        "x-category": "Accounting", "x-is-trigger": False,
    }))}
    for param in spec["parameters"]:
        key = param.get("field", param["name"])
        fields[key] = (_annotation(param["schema"], name + key), Field(
            ... if param.get("required") else param["schema"].get("default"),
            description=param.get("description", "One page per request; use next_page from the preceding result.")))
    for key, schema in spec.get("body", {}).get("properties", {}).items():
        annotation = _annotation(schema, name + key)
        extra = {}
        if schema["type"] in ("array", "object"):
            annotation = Json[annotation]
            extra = {"ui:widget": "code_editor", "x-code-language": "json"}
        fields[key] = (annotation, Field(... if key in spec["body"].get("required", []) else None,
            description=schema.get("description", "Documented request body field.") +
                (" PUT replaces the record; include values to retain." if spec["method"] == "PUT" else ""),
            json_schema_extra=extra))
    return create_model("Visma" + name.title().replace("_", "") + "Config", __base__=_Input, **fields)


_MODELS = tuple(_operation_model(name, spec) for name, spec in VISMA_OPERATIONS.items())
VismaEAccountingConfig = Annotated[Union[_MODELS], Field(discriminator="operation")]


class VismaEAccountingFullConfig(NodeConfig[VismaEAccountingConfig, VismaEAccountingOAuthCredential]):
    pass


class VismaEAccountingNode(WorkflowNode):
    integration_type = "automation-visma-eaccounting"
    scope_registry = VISMA_EACCOUNTING_SCOPES
    connection_evidence = ConnectionEvidence(noun="company", identity_operation="get_company_settings", identity_keys=("Name", "name"))

    @classmethod
    def get_config_model(cls):
        return VismaEAccountingFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.visma_eaccounting_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="visma-eaccounting")

    async def _token(self, credential):
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.visma_eaccounting_oauth import refresh_access_token
        data = credential.model_dump()
        await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=data, refresh=refresh_access_token,
            provider="visma-eaccounting", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in data:
                setattr(credential, key, data[key])
        return credential.access_token

    async def execute(self, inputs):
        if not isinstance(self.config, VismaEAccountingFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Visma eAccounting account")
        config, credential = self.config.config, self.config.credentials
        spec = VISMA_OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_unset=True)
        path, params = spec["path"], {}
        for param in spec["parameters"]:
            key = param.get("field", param["name"])
            value = values.get(key, param["schema"].get("default"))
            if value is None:
                continue
            if param["in"] == "path":
                path = path.replace("{" + param["name"] + "}", str(value))
            else:
                params[param["name"]] = value
        body = {key: values[key] for key in spec.get("body", {}).get("properties", {}) if key in values}
        token = await self._token(credential)
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(spec["method"], BASE + path, params=params or None,
                    json=body if "body" in spec else None,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        except httpx.HTTPError:
            return {"status": "error", "error": "Visma eAccounting request failed; check the result before retrying a write."}
        if len(response.content) > 8_000_000:
            raise ValueError("Visma eAccounting response exceeds the JSON size limit")
        if not 200 <= response.status_code < 300:
            message = ""
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("Message") or error.get("ErrorMessage") or "")
            except ValueError:
                pass
            for secret in (token, credential.refresh_token):
                if secret:
                    message = message.replace(secret, "[redacted]")
            return {"status": "error", "status_code": response.status_code,
                "error": message[:2000] or f"Visma eAccounting rejected the request (HTTP {response.status_code})."}
        if spec["response"] == "empty":
            return {"status": "success", "deleted": True}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Visma eAccounting returned invalid JSON") from None
        if not isinstance(payload, dict) or any(key in payload for key in ("error", "errors", "ErrorCode")):
            raise ValueError("Visma eAccounting returned an unexpected response")
        if spec["response"] == "page":
            if not isinstance(payload.get("Data"), list) or not isinstance(payload.get("Meta"), dict):
                raise ValueError("Visma eAccounting returned an incomplete page")
            meta = payload["Meta"]
            page, total = meta.get("CurrentPage"), meta.get("TotalNumberOfPages")
            if type(page) is not int or type(total) is not int or page < 1 or total < 0:
                raise ValueError("Visma eAccounting returned invalid pagination")
            return {"status": "success", "items": payload["Data"], "meta": meta,
                "next_page": page + 1 if page < total else None, "has_more": page < total}
        if config.operation == "get_company_settings" and (not isinstance(payload.get("Name"), str) or not payload["Name"].strip()):
            raise ValueError("Visma eAccounting returned no company identity")
        return {"status": "success", "data": payload}
