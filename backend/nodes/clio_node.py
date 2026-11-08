"""Clio Manage v4 REST actions with regional OAuth credentials."""

import base64
import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.clio_operations import OPERATIONS, Operation
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.scopes.clio import CLIO_SCOPES


API_BASES = {
    "us": "https://app.clio.com/api/v4",
    "eu": "https://eu.app.clio.com/api/v4",
    "ca": "https://ca.app.clio.com/api/v4",
    "au": "https://au.app.clio.com/api/v4",
}


class ClioOAuthCredential(BaseModel):
    credential_type: Literal["clio_oauth"] = Field("clio_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    region: Literal["us"] = Field("us", title="Clio Region")
    model_config = ConfigDict(title="Clio Account", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "clio",
        "x-oauth-scopes": sorted(CLIO_SCOPES.declared_scopes()),
        "x-credential-url": "https://developers.clio.com",
        "x-credential-instructions": "Connect a Clio Manage account in the US region.",
    })


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for field in re.findall(r"\{([^}]+)\}", op.path):
        fields[field] = (str, Field(..., title=field.replace("_", " ").title()))
    fields["query_json"] = (str if op.required_query else Optional[str], Field(
        ... if op.required_query else None,
        title="Query Parameters JSON",
        description="Query parameters as JSON." +
            (" Required: " + ", ".join(op.required_query) + "." if op.required_query else ""),
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    ))
    fields["headers_json"] = (Optional[str], Field(
        None, title="Request Headers JSON",
        description="Optional Clio headers such as If-Match and X-API-VERSION. Authentication is managed by NoClick.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    ))
    if op.has_body:
        fields["body_json"] = (Optional[str], Field(
            None, title="Request Body JSON", description="Clio request body as JSON.",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
        ))
        fields["form_json"] = (Optional[str], Field(
            None, title="Form Fields JSON",
            description="For file uploads or form encoding. A file value uses {base64, filename, content_type}.",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
        ))
        fields["form_encoding"] = (Literal["multipart", "urlencoded"], Field(
            "multipart", title="Form Encoding",
            description="Used only when Form Fields JSON is set.",
        ))
    return create_model(
        "Clio" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], Field(
            name, title=op.label, description=op.description,
            json_schema_extra={"const": name, "ui:hidden": True,
                               "x-category": op.category, "x-is-trigger": False,
                               "x-display-name": op.label},
        )), **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
ClioConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class ClioNodeConfig(NodeConfig[ClioConfig, ClioOAuthCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


class ClioNode(WorkflowNode):
    integration_type = "automation-clio"
    scope_registry = CLIO_SCOPES
    connection_evidence = ConnectionEvidence(operation="user_who_am_i", noun="account")
    edit_examples = [
        "List Clio matters", "Create a Clio contact", "Get Clio documents",
        "Track an activity in Clio",
    ]

    @classmethod
    def get_config_model(cls):
        return ClioNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.clio_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="clio",
        )

    async def _access_token(self, credential: ClioOAuthCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.clio_oauth import refresh_access_token
        return await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credential.model_dump(), refresh=refresh_access_token,
            provider="clio", caller_path="execute",
        )

    @staticmethod
    def _object(raw: Optional[str], label: str) -> dict[str, Any]:
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{label} must be a JSON object")
        return data

    @staticmethod
    def _param(value: Any) -> Any:
        if isinstance(value, list):
            return [ClioNode._param(item) for item in value]
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, dict):
            return json.dumps(value, separators=(",", ":"))
        return str(value)

    @staticmethod
    def _multipart(data: dict[str, Any]) -> list[tuple[str, tuple[Optional[str], bytes | str, str]]]:
        parts = []
        for name, value in data.items():
            for item in (value if isinstance(value, list) else [value]):
                if isinstance(item, dict) and "base64" in item:
                    try:
                        content = base64.b64decode(item["base64"], validate=True)
                    except (ValueError, base64.binascii.Error) as exc:
                        raise ValueError(f"{name} must contain valid Base64") from exc
                    if len(content) > 20 * 1024 * 1024:
                        raise ValueError("Clio upload exceeds the 20 MB workflow limit")
                    parts.append((name, (str(item.get("filename") or name), content,
                                         str(item.get("content_type") or "application/octet-stream"))))
                else:
                    parts.append((name, (None, str(ClioNode._param(item)), "text/plain")))
        return parts

    @staticmethod
    async def _request(method: str, path: str, token: str, region: str,
                       params: dict[str, Any], headers: dict[str, Any], body: Optional[dict[str, Any]],
                       form: Optional[dict[str, Any]], encoding: str) -> Any:
        blocked = {"authorization", "host", "content-length", "apikey"}
        if any(key.lower() in blocked for key in headers):
            raise ValueError("Authentication and transport headers cannot be overridden")
        kwargs: dict[str, Any] = {
            "params": {key: ClioNode._param(value) for key, value in params.items()} or None,
            "headers": {"Authorization": f"Bearer {token}", "Accept": "application/json",
                        **{key: ClioNode._param(value) for key, value in headers.items()}},
        }
        if form is not None:
            if encoding == "urlencoded":
                kwargs["content"] = urlencode({key: ClioNode._param(value) for key, value in form.items()}, doseq=True)
                kwargs["headers"]["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                kwargs["files"] = ClioNode._multipart(form)
        elif body is not None:
            kwargs["json"] = body
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.request(method, API_BASES[region] + path, **kwargs)
        if response.is_error:
            try:
                detail = response.json()
                message = detail.get("error") or detail.get("message")
            except (ValueError, AttributeError):
                message = None
            raise ValueError(f"Clio API error {response.status_code}: {message or 'request failed'}")
        if not response.content:
            return {"ok": True}
        if "json" in response.headers.get("content-type", "") or response.content[:1] in (b"{", b"["):
            return response.json()
        return BinaryOutput(data=response.content,
                            content_type=response.headers.get("content-type", "application/octet-stream"),
                            filename=path.rsplit("/", 1)[-1] or "download")

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ClioNodeConfig):
            raise ValueError("Clio configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Clio account")
        config = self.config.config
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        for field in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        params = self._object(values.pop("query_json", None), "Query Parameters JSON")
        headers = self._object(values.pop("headers_json", None), "Request Headers JSON")
        missing = [field for field in op.required_query if field not in params]
        if missing:
            raise ValueError("Missing required Clio query parameters: " + ", ".join(missing))
        raw_body = values.pop("body_json", None)
        body = self._object(raw_body, "Request Body JSON") if raw_body is not None else None
        raw_form = values.pop("form_json", None)
        form = self._object(raw_form, "Form Fields JSON") if raw_form is not None else None
        if body is not None and form is not None:
            raise ValueError("Provide either JSON body or form fields, not both")
        data = await self._request(op.method, path, await self._access_token(credential),
                                   credential.region, params, headers, body, form,
                                   values.pop("form_encoding", "multipart"))
        return {"status": "success", "operation": config.operation, "data": data}
