"""Gorgias REST workflow node generated from the official route definitions."""

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
from nodes.scopes.gorgias import GORGIAS_SCOPES
from utils.ssrf import normalize_provider_subdomain, guarded_async_client
from nodes.gorgias_operations import CATALOG, BODY_COMPONENTS
from jsonschema import Draft202012Validator, ValidationError


_catalog = CATALOG
OPERATIONS: dict[str, dict[str, Any]] = {row["name"]: row for row in _catalog["operations"]}
assert len(OPERATIONS) == len(_catalog["operations"]), "Duplicate Gorgias actions"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class GorgiasOAuthCredential(BaseModel):
    credential_type: Literal["gorgias_oauth"] = Field(
        "gorgias_oauth", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(..., title="Gorgias Subdomain", description="For acme.gorgias.com, enter acme.")
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    email: Optional[str] = Field(None, title="Account Email")
    name: Optional[str] = Field(None, title="Account Name")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "gorgias",
        "title": "Gorgias OAuth",
        "x-oauth-scopes": sorted(GORGIAS_SCOPES.declared_scopes()),
        "x-credential-url": "https://developers.gorgias.com/docs/set-up-oauth2-app-store",
    })


class GorgiasApiKeyCredential(BaseModel):
    credential_type: Literal["gorgias_api_key"] = Field(
        "gorgias_api_key", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(..., title="Gorgias Subdomain", description="For acme.gorgias.com, enter acme.")
    email: str = Field(..., title="Account Email")
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})

    model_config = ConfigDict(json_schema_extra={
        "title": "Gorgias API Key",
        "x-credential-url": "https://docs.gorgias.com/en-US/rest-api-208286",
    })


GorgiasCredential = Union[GorgiasOAuthCredential, GorgiasApiKeyCredential]


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _resolve_schema(schema):
    if "$ref" in schema:
        return _resolve_schema(BODY_COMPONENTS["schemas"][schema["$ref"].split("/")[-1]])
    return schema


def _query_type(schema):
    schema = _resolve_schema(schema)
    if schema.get("enum"):
        return Literal[tuple(schema["enum"])]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    if kind == "array":
        return list[_query_type(schema.get("items", {}))]
    return {"integer": int, "number": float, "boolean": bool}.get(kind, str)


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={
                "const": name, "ui:hidden": True, "x-category": op["category"],
                "x-display-name": op["label"], "x-is-trigger": False,
            },
        )),
    }
    for param in op["path_params"]:
        raw = param["name"]
        fields[_field_name("path", raw)] = (
            str, Field(..., title=raw.replace("_", " ").title(), description=param["description"]),
        )
    for param in op["query_params"]:
        raw = param["name"]
        fields[_field_name("query", raw)] = (
            _query_type(param.get("schema", {})) if param["required"] else Optional[_query_type(param.get("schema", {}))],
            Field(... if param["required"] else None,
                  title=raw.replace("_", " ").title(), description=param["description"] +
                  (" Supply a JSON object." if _resolve_schema(param.get("schema", {})).get("type") == "object" else "")),
        )
    for param in op["header_params"]:
        raw = param["name"]
        fields[_field_name("header", raw)] = (
            str if param["required"] else Optional[str],
            Field(... if param["required"] else None,
                  title=raw.replace("-", " ").title(), description=param["description"]),
        )
    if op["body_json"]:
        required = op["body_required_fields"]
        description = "JSON value matching the Gorgias API reference (object, array or scalar as documented)."
        if required:
            description += " Required top-level keys: " + ", ".join(required) + "."
        description += " See " + op["docs_url"]
        fields["body_json"] = (
            str if op["body_required"] else Optional[str],
            Field(... if op["body_required"] else None, title="Request Body (JSON)",
                  description=description, json_schema_extra=_JSON_EDITOR),
        )
    if op["body_multipart"]:
        fields["file_base64"] = (
            str, Field(..., title="File Data (Base64)",
                       description="Base64-encoded file bytes to upload to Gorgias."),
        )
        fields["filename"] = (
            str, Field(..., title="Filename", description="Name to use for the uploaded file."),
        )
        fields["content_type"] = (
            Optional[str], Field(None, title="Content Type", description="MIME type of the uploaded file, for example image/png (PNG image)."),
        )
    return create_model(
        "Gorgias" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
GorgiasConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class GorgiasNodeConfig(NodeConfig[GorgiasConfig, GorgiasCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Request Body must contain valid JSON") from exc
    return value


class GorgiasNode(WorkflowNode):
    """Run Gorgias REST actions with OAuth or a private app API key."""

    integration_type = "automation-gorgias"
    credential_provider_labels = {"gorgias": "Gorgias Account"}

    connection_evidence = ConnectionEvidence(operation="get_account", noun="account")
    scope_registry = GORGIAS_SCOPES
    edit_examples = [
        "List Gorgias tickets", "Reply to a Gorgias ticket",
        "Create a Gorgias customer", "Add tags to a ticket",
    ]

    @classmethod
    def get_config_model(cls):
        return GorgiasNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.gorgias_oauth import OAUTH_PROVIDER

        if not credential_data or not credential_data.get("refresh_token"):
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data), provider="gorgias",
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
        )

    async def _ensure_fresh_token(self, credentials: GorgiasCredential) -> None:
        if not isinstance(credentials, GorgiasOAuthCredential):
            return
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.gorgias_oauth import OAUTH_PROVIDER

        credential = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=credential, refresh=OAUTH_PROVIDER.bind_refresh(credential),
            provider="gorgias", additional_token_fields=OAUTH_PROVIDER.credential_fields,
        )
        credentials.access_token = credential["access_token"]
        credentials.expires_at = credential.get("expires_at")
        if credential.get("refresh_token"):
            credentials.refresh_token = credential["refresh_token"]

    @staticmethod
    async def _request(credentials: GorgiasCredential, name: str, values: dict[str, Any]) -> dict[str, Any]:
        op = OPERATIONS[name]
        subdomain = normalize_provider_subdomain(
            credentials.subdomain, "gorgias.com", field_name="Gorgias subdomain"
        )
        path = op["path"]
        for param in op["path_params"]:
            raw = param["name"]
            value = values.pop(_field_name("path", raw), None)
            if value is None or str(value).strip() in {"", ".", ".."}:
                raise ValueError(f"{raw} is required")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        params = {}
        for param in op["query_params"]:
            raw = param["name"]
            value = values.pop(_field_name("query", raw), None)
            if value is not None and value != "":
                schema = _resolve_schema(param.get("schema", {}))
                if schema.get("type") == "object":
                    value = _parse_json(value) if isinstance(value, str) else value
                    if not isinstance(value, dict):
                        raise ValueError(f"{raw} must be a JSON object")
                    if param.get("style") == "deepObject":
                        params.update({f"{raw}[{key}]": item for key, item in value.items()})
                    else:
                        params[raw] = ",".join(str(part) for pair in value.items() for part in pair)
                elif isinstance(value, list) and not param.get("explode", True):
                    params[raw] = ",".join(map(str, value))
                else:
                    params[raw] = value
        headers = {"Accept": "application/json"}
        for param in op["header_params"]:
            raw = param["name"]
            value = values.pop(_field_name("header", raw), None)
            if value is not None and value != "":
                headers[raw] = value
        auth = None
        if isinstance(credentials, GorgiasOAuthCredential):
            GORGIAS_SCOPES.require(name)
            headers["Authorization"] = f"Bearer {credentials.access_token}"
        else:
            auth = httpx.BasicAuth(credentials.email, credentials.api_key)
        options: dict[str, Any] = {}
        if op["body_json"]:
            body = _parse_json(values.pop("body_json", None))
            if op["body_required"] and body is None:
                raise ValueError("Request Body is required")
            missing = [key for key in op["body_required_fields"] if body is not None and (not isinstance(body, dict) or key not in body)]
            if missing:
                raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
            if body is not None:
                schema = {**op.get("body_schema", {}), "components": BODY_COMPONENTS}
                try:
                    Draft202012Validator(schema).validate(body)
                except ValidationError as exc:
                    raise ValueError("Request Body does not match the documented Gorgias schema at " + ".".join(map(str, exc.path))) from None
                options["json"] = body
        if op["body_multipart"]:
            filename = values.pop("filename", "")
            raw = values.pop("file_base64", "")
            if not filename or not raw or "/" in filename or "\\" in filename:
                raise ValueError("A filename and Base64 file data are required")
            try:
                content = base64.b64decode(raw, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("File Data must be valid Base64") from exc
            if not content:
                raise ValueError("File Data is empty")
            options["files"] = {filename: (
                filename, content, values.pop("content_type", None) or "application/octet-stream"
            )}
        started = time.monotonic()
        async with guarded_async_client(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                op["method"], f"https://{subdomain}.gorgias.com" + path,
                auth=auth, headers=headers, params=params or None, **options,
            )
        try:
            data: Any = response.json() if response.content else {}
        except ValueError:
            data = {"text": response.text[:2000]}
        if name == "download_file" and response.status_code == 307:
            return {"status": "success", "operation": name, "status_code": 307,
                    "download_url": response.headers.get("location")}
        if response.is_error or response.is_redirect:
            message = (data.get("message") or data.get("detail") or data.get("error")) if isinstance(data, dict) else None
            raise ValueError(f"Gorgias API error {response.status_code}: {message or 'request failed'}")
        if name == "download_legacy_statistic":
            data = BinaryOutput(data=response.content, content_type=response.headers.get("content-type", "text/csv"), filename="gorgias-statistic.csv")
        return {
            "status": "success", "operation": name, "status_code": response.status_code,
            "data": data, "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, GorgiasNodeConfig) or not self.config.credentials:
            raise ValueError("Connect Gorgias with OAuth or an API key before running this action")
        credentials = self.config.credentials
        await self._ensure_fresh_token(credentials)
        config = self.config.config
        return await self._request(
            credentials, config.operation,
            config.model_dump(exclude={"operation"}, exclude_none=True),
        )
