"""Peaka project catalogs, tables and SQL through the published Gateway API."""
from typing import Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.peaka_operations import PeakaConfig, ROUTES, PATH_FIELDS
from utils.ssrf import guarded_async_client


class PeakaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Peaka API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.peaka.com/api-reference/authentication",
            "x-credential-instructions": "Paste a Project API Key (or Partner API Key), the project ID it can access, and its region. NoClick sends Bearer authentication to Peaka's regional Gateway API. Connection verification lists this project's catalogs."})
    credential_type: Literal["peaka_api_key"] = Field("peaka_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    project_id: str = Field(..., title="Project ID", min_length=1, max_length=256)
    region: Literal["us", "eu"] = Field("us", title="Region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value

    @field_validator("project_id")
    @classmethod
    def project(cls, value):
        if value in {".", ".."} or not value.isascii() or any(not (c.isalnum() or c in "_-") for c in value):
            raise ValueError("Paste the project ID, without a URL")
        return value


# Peaka's own MCP server: agents get its tools through a person's Peaka sign-in.
PeakaMcpCredential = mcp_credential("peaka", "https://mcp.peaka.studio/mcp", app="Peaka")
PeakaCredential = Union[PeakaAPIKeyCredential, PeakaMcpCredential]


class PeakaFullConfig(NodeConfig[PeakaConfig, PeakaCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class PeakaNode(WorkflowNode):
    integration_type = "automation-peaka"
    credential_provider_labels = {"peaka": "Peaka Account"}
    connection_evidence = ConnectionEvidence(noun="catalogs", operation="list_catalogs", label_keys=("displayName", "name", "id"))

    @classmethod
    def get_config_model(cls):
        return PeakaFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Peaka API key and project ID")
        credential = self.config.credentials
        op = self.config.config
        method, path = ROUTES[op.operation]
        path = path.replace("{projectId}", quote(credential.project_id, safe=""))
        for wire, field in PATH_FIELDS.items():
            if "{" + wire + "}" in path:
                path = path.replace("{" + wire + "}", quote(getattr(op, field), safe=""))
        base = {"us": "https://partner.peaka.studio/api/v1", "eu": "https://partner.eu.peaka.studio/api/v1"}[credential.region]
        params, body = {}, None
        if op.operation == "create_catalog":
            body = {"name": op.name, "connectionId": op.connection_id}
            if op.extra_parameters is not None:
                body["extraParameters"] = op.extra_parameters
        elif op.operation in {"create_query", "update_query"}:
            params["checkSchemaExists"] = str(op.check_schema_exists).lower()
            body = {"displayName": op.display_name, "inputQuery": op.input_query, "queryType": "PLAIN"}
            if op.path is not None:
                body["path"] = op.path
        elif op.operation == "execute_query":
            params["format"] = op.format
            body = {"statement": op.statement}
            for field in ("bindings", "timeout"):
                if getattr(op, field) is not None:
                    body[field] = getattr(op, field)
        # Each operation performs exactly one contract operation, without retries.
        try:
            async with guarded_async_client(timeout=330 if op.operation == "execute_query" else 30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, base + path, params=params,
                    headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Peaka request did not complete; inspect write outcome before retrying") from None
        if not 200 <= response.status_code < 300:
            message = _redact(response.text[:4000], credential.api_key)
            return {"status": "error", "http_status": response.status_code, "error": message or "Peaka rejected the request"}
        if method == "DELETE":
            return {"status": "success", "operation": op.operation, "acknowledged": True, "http_status": response.status_code}
        if len(response.content) > 10_000_000:
            raise ValueError("Peaka response exceeds the 10 MB output limit")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Peaka returned an invalid JSON response") from None
        if not isinstance(data, (dict, list)):
            raise ValueError("Peaka returned an unexpected response shape")
        if isinstance(data, dict) and (data.get("errorCode") is not None or data.get("error")):
            return {"status": "error", "error": _redact(data, credential.api_key)}
        # Keep Peaka's documented envelopes and all three query result formats intact.
        return {"status": "success", "operation": op.operation, "data": _redact(data, credential.api_key), "http_status": response.status_code}
