"""Cvent events, contacts, attendees and sessions against the public EA contract.

Lists return one provider page, including paging.nextToken for continuation.
Bulk contact/attendee writes preserve the provider's per-item results.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.cvent_operations import CVENT_OPERATIONS
from nodes.scopes.cvent import CVENT_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://api-platform.cvent.com/ea"
DOCS = "https://developers.cvent.com/docs/rest-api/tutorials/developer-quickstart"


class CventClientCredential(BaseModel):
    model_config = ConfigDict(title="Cvent Client", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "Create a Cvent application in the developer portal, associate the required API scopes, and paste its client ID and client secret. NoClick obtains a short-lived access token using the client credentials grant. This method uses the North America API region."})
    credential_type: Literal["cvent_client_credentials"] = Field("cvent_client_credentials", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, title="Client ID")
    client_secret: str = Field(..., min_length=1, title="Client Secret", repr=False, json_schema_extra={"ui:widget": "password"})


class CventOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Cvent OAuth", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "cvent",
            "x-oauth-scopes": CVENT_SCOPES.declared_scopes(), "x-credential-url": DOCS,
            "x-credential-instructions": "Sign in as a Cvent planner administrator with a North America account. Developer users must use client credentials. The registered application must have the requested scopes, including account users read for the connection label. A manually supplied access token works until it expires; supply a refresh token and expiry to refresh it."})
    credential_type: Literal["cvent_oauth"] = Field("cvent_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token Expiry")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("payload", mode="before", check_fields=False)
    @classmethod
    def json_text(cls, value):
        return json.dumps(value) if isinstance(value, (dict, list)) else value

    @field_validator("expand", mode="before", check_fields=False)
    @classmethod
    def expansion_text(cls, value):
        return ','.join(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def payload_shape(self):
        if hasattr(self, "payload"):
            try:
                body = json.loads(self.payload)
            except ValueError:
                raise ValueError("Request JSON must be valid JSON") from None
            expected = CVENT_OPERATIONS[self.operation]["body_type"]
            if expected == "array":
                if not isinstance(body, list) or not body or not all(isinstance(row, dict) for row in body):
                    raise ValueError("Request JSON must be a nonempty array of records")
            elif not isinstance(body, dict):
                raise ValueError("Request JSON must be an object")
        if getattr(self, "expand", None):
            if not set(value.strip() for value in self.expand.split(',')) <= {"answers.question", "registrationType"}:
                raise ValueError("Expand accepts answers.question and registrationType")
        return self

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name in {"id", "attendeeId"} and (value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)):
            raise ValueError("Use a single Cvent resource ID")
        return value


def _operation_model(name, spec):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": spec["title"], "x-category": spec["path"].split('/')[1].title()}))}
    for param in spec["parameters"]:
        schema = param.get("schema", {})
        annotation = {"integer": int, "boolean": bool, "array": str}.get(schema.get("type"), str)
        if "enum" in schema:
            annotation = Literal[tuple(schema["enum"])]
        required = param.get("required", False)
        extra = {}
        if annotation is int:
            extra = {k: schema[v] for k, v in (("ge", "minimum"), ("le", "maximum")) if v in schema}
        if schema.get("type") == "array":
            extra["description"] = "Comma-separated expansions: answers.question, registrationType."
        fields[param["name"]] = (annotation if required else annotation | None, Field(... if required else None, title=param["name"], **extra))
    if spec.get("body_type"):
        fields["payload"] = (str,
            Field(..., title="Request JSON", json_schema_extra={"ui:widget": "textarea"}, description=spec["body_description"] + " See the Cvent REST API reference for all fields. Send the complete intended record for updates."))
    return create_model("Cvent" + ''.join(x.title() for x in name.split('_')) + "Config", __base__=_Input, __doc__=spec["title"], **fields)


CVENT_CONFIGS = {name: _operation_model(name, spec) for name, spec in CVENT_OPERATIONS.items()}
CventConfig = Annotated[Union[tuple(CVENT_CONFIGS.values())], Field(discriminator="operation")]
CventCredential = Union[CventClientCredential, CventOAuthCredential]


class CventFullConfig(NodeConfig[CventConfig, CventCredential]):
    pass


def _checked(response, secrets=()):
    if response.is_error:
        message = response.text[:2000]
        for secret in sorted((value for value in secrets if value), key=len, reverse=True):
            message = message.replace(secret, "[redacted]")
        raise httpx.HTTPStatusError(f"Cvent HTTP {response.status_code}: {message}",
            request=response.request, response=response)
    response.raise_for_status()
    if response.is_redirect:
        raise ValueError("Cvent redirected the API request")
    if not response.content:
        return None
    return response.json()


class CventNode(WorkflowNode):
    integration_type = "automation-cvent"
    scope_registry = CVENT_SCOPES
    credential_provider_labels = {"cvent": "Cvent"}
    connection_evidence = ConnectionEvidence(operation="list_events", noun="events")

    @classmethod
    def get_config_model(cls):
        return CventFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if credential_data.get("credential_type") != "cvent_oauth" or not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.cvent_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="cvent")

    async def execute(self, inputs):
        if not isinstance(self.config, CventFullConfig) or not self.config.credentials:
            raise ValueError("Connect Cvent credentials")
        config, credential = self.config.config, self.config.credentials
        self.scope_registry.require(config.operation)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            if isinstance(credential, CventClientCredential):
                response = await client.post(BASE_URL + "/oauth2/token",
                    auth=httpx.BasicAuth(credential.client_id, credential.client_secret),
                    data={"grant_type": "client_credentials", "client_id": credential.client_id,
                        "scope": ' '.join(CVENT_SCOPES.declared_scopes())})
                token = _checked(response, (credential.client_id, credential.client_secret))["access_token"]
            else:
                token = credential.access_token
                if credential.refresh_token:
                    from nodes.core.oauth_refresh import ensure_fresh_oauth_token
                    from nodes.oauth.cvent_oauth import refresh_access_token
                    data = credential.model_dump()
                    token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
                        user_id=self.user_id, credential=data, refresh=refresh_access_token,
                        provider="cvent", caller_path="execute")
                    for key in ("access_token", "refresh_token", "expires_at"):
                        setattr(credential, key, data.get(key))
            spec = CVENT_OPERATIONS[config.operation]
            values = config.model_dump(mode="json", exclude_none=True)
            path, params = spec["path"], {}
            for param in spec["parameters"]:
                name = param["name"]
                if name not in values:
                    continue
                if param["in"] == "path":
                    path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
                else:
                    value = values[name]
                    if param.get("schema", {}).get("type") == "array":
                        value = [part.strip() for part in value.split(',')]
                    params[name] = str(value).lower() if isinstance(value, bool) else value
            kwargs = {"json": json.loads(values["payload"])} if "payload" in values else {}
            response = await client.request(spec["method"], BASE_URL + path, params=params,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
            payload = _checked(response, (token,))
        return {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": payload}
