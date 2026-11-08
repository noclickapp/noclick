"""Gong V2 workflow actions with account OAuth or Basic access keys."""

import base64
import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from utils.ssrf import assert_exact_url_origin, guarded_async_client
from nodes.scopes.gong import GONG_SCOPES
from nodes.gong_operations import OPERATIONS, Operation
from nodes.oauth.gong_oauth import validate_api_base_url


class GongOAuthCredential(BaseModel):
    credential_type: Literal["gong_oauth"] = Field("gong_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field(..., title="Token Expiry")
    api_base_url_for_customer: str = Field(..., title="Customer API URL")
    scope: Optional[str] = Field(None, title="Granted Scopes", json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(json_schema_extra={
        "title": "Gong OAuth", "x-credential-type": "oauth", "x-oauth-provider": "gong",
        "x-oauth-scopes": GONG_SCOPES.declared_scopes(),
        "x-credential-url": "https://app.gong.io/",
    })


class GongAccessKeyCredential(BaseModel):
    credential_type: Literal["gong_access_key"] = Field("gong_access_key", json_schema_extra={"ui:hidden": True})
    access_key: str = Field(..., title="Access Key", json_schema_extra={"ui:widget": "password"})
    access_key_secret: str = Field(..., title="Access Key Secret", json_schema_extra={"ui:widget": "password"})
    api_base_url_for_customer: str = Field(..., title="Customer API URL",
                                          description="Your tenant URL, e.g. https://company-17.api.gong.io")
    model_config = ConfigDict(json_schema_extra={
        "title": "Gong Access Key", "x-credential-url": "https://app.gong.io/",
    })


GongCredential = Union[GongOAuthCredential, GongAccessKeyCredential]


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for param, location, required, description in op.params:
        if location not in ("path", "query"):
            continue
        title = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", param).replace("-", " ").title()
        key = param.replace("-", "_")
        fields[key] = (
            str if required else Optional[str],
            Field(... if required else None, title=title, description=description,
                  alias=param if key != param else None),
        )
    fields["query_json"] = (Optional[str], Field(
        None, title="Additional Query Parameters JSON",
        description="Optional Gong query parameters as a JSON object",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    if op.body == "json":
        fields["body_json"] = (str, Field(
            ..., title="Request Body JSON", description="Gong request body as a JSON object",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    elif op.body == "multipart":
        fields["file_base64"] = (str, Field(..., title="File (Base64)",
                                              description="Base64 encoded file, up to 20 MB",
                                              json_schema_extra={"contentEncoding": "base64", **(
                                                  {"ui:accept": "audio/wav,audio/mpeg,video/mp4,video/x-matroska,audio/flac"}
                                                  if name == "add_call_recording" else
                                                  {"contentMediaType": "application/x-ndjson"})}))
        fields["file_name"] = (str, Field(..., title="File Name"))
        fields["file_content_type"] = (Optional[str], Field(None, title="Content Type"))
    return create_model(
        "Gong" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__, __config__=ConfigDict(populate_by_name=True),
        operation=(Literal[name], Field(name, title=op.label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-category": op.category,
            "x-is-trigger": False, "x-display-name": op.label,
        })),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
GongConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class GongNodeConfig(NodeConfig[GongConfig, GongCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


class GongNode(WorkflowNode):
    integration_type = "automation-gong"
    credential_provider_labels = {"gong": "Gong Account"}
    scope_registry = GONG_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_workspaces", noun="workspaces")
    edit_examples = [
        "List Gong calls", "Retrieve Gong call transcripts", "List Gong users",
        "Find Gong library folders", "List Gong Engage flows",
    ]

    @classmethod
    def get_config_model(cls):
        return GongNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.gong_oauth import OAUTH_PROVIDER
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="gong")

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
    def _serialize_param(value: Any) -> Any:
        if isinstance(value, list):
            return [GongNode._serialize_param(item) for item in value]
        if isinstance(value, (dict, bool)):
            return json.dumps(value, separators=(",", ":"))
        return "" if value is None else str(value)

    async def _auth(self, credential: GongCredential) -> tuple[str, str]:
        if isinstance(credential, GongAccessKeyCredential):
            basic = base64.b64encode(
                f"{credential.access_key}:{credential.access_key_secret}".encode()).decode()
            return f"Basic {basic}", validate_api_base_url(credential.api_base_url_for_customer)
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.gong_oauth import OAUTH_PROVIDER
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=data, refresh=OAUTH_PROVIDER.bind_refresh(data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="gong", caller_path="execute")
        for field in ("access_token", "refresh_token", "expires_at", "scope", "api_base_url_for_customer"):
            if field in data:
                setattr(credential, field, data[field])
        return f"Bearer {token}", validate_api_base_url(data["api_base_url_for_customer"])

    @staticmethod
    async def _request(method: str, base_url: str, path: str, authorization: str,
                       params: dict[str, Any], body: Optional[Any],
                       file: Optional[tuple[str, bytes, str, str]]) -> Any:
        kwargs: dict[str, Any] = {"params": params or None,
                                  "headers": {"Authorization": authorization,
                                              "Accept": "application/json"}}
        if file:
            field, content, name, content_type = file
            kwargs["files"] = {field: (name, content, content_type)}
        elif body is not None:
            kwargs["json"] = body
        base_url = validate_api_base_url(base_url)
        url = base_url + path
        assert_exact_url_origin(url, base_url)
        async with guarded_async_client(timeout=90, follow_redirects=False) as client:
            response = await client.request(method, url, **kwargs)
        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") or payload.get("errors")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Gong API error {response.status_code}: {detail or 'request failed'}")
        if not response.content:
            return {"ok": True}
        if "json" in response.headers.get("content-type", "") or response.content[:1] in (b"{", b"["):
            try:
                return response.json()
            except ValueError as exc:
                raise ValueError(f"Gong returned invalid JSON ({response.status_code})") from exc
        return BinaryOutput(data=response.content,
                            content_type=response.headers.get("content-type", "application/octet-stream"),
                            filename="gong-download")

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, GongNodeConfig):
            raise ValueError("Gong configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Gong account")
        config = self.config.config
        self.scope_registry.require(config.operation)
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"}, by_alias=True)
        path = op.path
        params: dict[str, Any] = {}
        for field, location, _, _ in op.params:
            if field not in values:
                continue
            if location == "path":
                path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
            elif location == "query":
                params[field] = self._serialize_param(values.pop(field))
        params.update({key: self._serialize_param(value) for key, value in
                       self._parse_object(values.pop("query_json", None), "Query Parameters JSON").items()})
        body = None
        file = None
        if op.body == "json":
            raw_body = values.pop("body_json", None)
            body = self._parse_object(raw_body, "Request Body JSON") if raw_body else None
        elif op.body == "multipart":
            try:
                content = base64.b64decode(values.pop("file_base64"), validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise ValueError("File must be valid Base64") from exc
            if len(content) > 20 * 1024 * 1024:
                raise ValueError("Gong file upload exceeds the 20 MB workflow limit")
            file = (op.file_field, content, values.pop("file_name"),
                    values.pop("file_content_type", None) or "application/octet-stream")
        if config.operation == "get_crm_objects":
            # Gong's OpenAPI incorrectly tags this as a query parameter; its
            # endpoint prose and example explicitly require a GET JSON array body.
            raw_ids = params.pop("objectsCrmIds")
            try:
                body = json.loads(raw_ids)
            except json.JSONDecodeError as exc:
                raise ValueError("Objects CRM IDs must be a JSON array") from exc
            if not isinstance(body, list) or not all(isinstance(item, str) for item in body):
                raise ValueError("Objects CRM IDs must be a JSON array of strings")
        authorization, base_url = await self._auth(credential)
        data = await self._request(op.method, base_url, path, authorization, params, body, file)
        return {"status": "success", "operation": config.operation, "data": data}
