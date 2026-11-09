"""Estimate Rocket's published v1 client, project and accounting API.

Each operation makes exactly one provider operation request. Writes are never
retried automatically; an interrupted write requires checking Estimate Rocket
before retrying to avoid duplicate invoices, payments or other records.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.converted_da_56088_operations import Operations, ROUTES
from nodes.scopes.converted_da_56088 import ESTIMATE_ROCKET_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://estimate-rocket-api.herokuapp.com"


class EstimateRocketOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Estimate Rocket Account", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "estimaterocket",
            "x-oauth-scopes": sorted(ESTIMATE_ROCKET_SCOPES.declared_scopes()),
            "x-credential-url": "https://estimaterocketapi.com/",
            "x-credential-instructions": "Connect Estimate Rocket with read and write access. The account owner must first enable API access at estimaterocketapi.com. Your NoClick administrator must register an OAuth application with Estimate Rocket and configure its client credentials.",
        })
    credential_type: Literal["estimaterocket_oauth"] = Field("estimaterocket_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = None
    scope: str | None = None
    token_type: str = "Bearer"
    name: str | None = None

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a Bearer prefix")
        return value


class EstimateRocketFullConfig(NodeConfig[Operations, EstimateRocketOAuthCredential]):
    pass


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


class EstimateRocketNode(WorkflowNode):
    integration_type = "automation-converted-da-56088"
    scope_registry = ESTIMATE_ROCKET_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_clients", noun="clients",
        identity_operation="get_current_employee", identity_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return EstimateRocketFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.converted_da_56088_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="estimaterocket")

    async def execute(self, inputs):
        if not isinstance(self.config, EstimateRocketFullConfig) or not self.config.credentials:
            raise ValueError("Connect an Estimate Rocket account")
        config = self.config.config
        credential = self.config.credentials
        self.scope_registry.require(config.operation)
        token = credential.access_token
        if credential.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.converted_da_56088_oauth import refresh_access_token
            data = credential.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                credential=data, refresh=refresh_access_token, provider="estimaterocket", caller_path="execute")
            credential.access_token = data["access_token"]
            credential.refresh_token = data.get("refresh_token")
            credential.expires_at = data.get("expires_at")
        method, template, envelope, query_filter = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        kwargs = {}
        if method == "POST":
            kwargs["json"] = {envelope: values}
        elif query_filter and query_filter in values:
            kwargs["params"] = {"filter[" + query_filter + "]": values[query_filter]}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if len(response.content) > 10_000_000:
            raise ValueError("Estimate Rocket response exceeds the size limit")
        if 300 <= response.status_code < 400:
            raise ValueError("Estimate Rocket redirected the request; reconnect your account")
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected JSON from Estimate Rocket")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Estimate Rocket returned invalid JSON") from None
        secrets = (token, credential.refresh_token)
        if response.status_code >= 400 or isinstance(body, dict) and (body.get("error") or body.get("errors")):
            message = body.get("error_description") or body.get("message") or body.get("error") or body.get("errors") if isinstance(body, dict) else None
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(message or "Estimate Rocket rejected the request", secrets)}
        if response.status_code != 200 or not isinstance(body, dict) or envelope not in body:
            raise ValueError("Estimate Rocket did not confirm this operation")
        result = body[envelope]
        if config.operation.startswith("list_"):
            if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
                raise ValueError("Expected an Estimate Rocket resource collection")
        elif not isinstance(result, dict):
            raise ValueError("Expected an Estimate Rocket resource object")
        output = {"status": "success", "operation": config.operation,
            "http_status": response.status_code, "data": result}
        if config.operation == "get_current_employee":
            output["name"] = result.get("name")
        return _redact(output, secrets)
