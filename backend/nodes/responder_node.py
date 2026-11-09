"""Responder (רב מסר) list and subscriber automation against the V2.0 contract.

Use an existing account access token as a bearer credential. One operation makes
one request, with no automatic write retries or undocumented pagination fields.
"""
from __future__ import annotations

import json
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.responder_operations import Operation, ROUTES
from utils.ssrf import guarded_async_client

BASE_URL = "https://graph.responder.live/v2"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ResponderAccessTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Responder Access Token", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.swaggerhub.com/apis/Responder/responder/V2.0",
            "x-credential-instructions": "Paste an existing Responder V2 account access token, without Bearer. The API documentation describes obtaining access_token through /oauth/token using a support-issued API client and your user_token from Settings > External connections (API). A user_token alone is not an access token. NoClick uses the supplied access token and does not create or refresh it. Replace it here if Responder expires or revokes it.",
        },
    )
    credential_type: Literal["responder_access_token"] = Field(
        "responder_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., min_length=1, max_length=8192, title="Access Token", repr=False,
        description="Account access_token returned by the Responder V2 token endpoint. Omit Bearer.",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the access token, without Bearer or whitespace")
        return value


class ResponderNodeConfig(NodeConfig[Operation, ResponderAccessTokenCredential]):
    pass


def _redact(value, token):
    if isinstance(value, dict):
        return {
            k: _redact(v, token) for k, v in value.items()
            if k.lower() not in {"password", "hashed", "token", "access_token", "refresh_token", "user_token", "client_secret", "mfa_secret", "mfa_expiration"}
        }
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class ResponderNode(WorkflowNode):
    integration_type = "automation-responder"
    connection_evidence = ConnectionEvidence(noun="mailing lists", operation="list_lists")
    edit_examples = [
        "Add a subscriber to my Responder mailing lists",
        "Search Responder subscribers by email",
        "Create a subscriber tag in רב מסר",
    ]

    @classmethod
    def get_config_model(cls):
        return ResponderNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials") if isinstance(config_data, dict) else None
        if isinstance(raw, dict) and raw.get("credential_type", "responder_access_token") != "responder_access_token":
            raise ValueError("Connect a Responder access token")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Responder access token")
        config = self.config.config
        token = self.config.credentials.access_token
        route = ROUTES[config.operation]
        path = route["path"].format(**{
            wire: quote(str(getattr(config, field)), safe="")
            for wire, field in route["path_fields"].items()
        })
        params = {k: getattr(config, k) for k in route["query_fields"]}
        wire = config.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        body = {k: v for k, v in wire.items() if k in route["body_fields"]}
        method = route["method"]
        write = method != "GET" and config.operation != "search_subscribers"
        http_status = None
        try:
            async with guarded_async_client(timeout=httpx.Timeout(30), follow_redirects=False, trust_env=False) as client:
                async with client.stream(
                    method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=params, **({"json": body} if route["body_fields"] else {}),
                ) as response:
                    http_status = response.status_code
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise ValueError("Responder response exceeds the supported size")
                    if http_status != 200:
                        message = "Responder returned HTTP " + str(http_status)
                        try:
                            error = json.loads(raw)
                            candidate = error.get("message") or error.get("error") if isinstance(error, dict) else None
                            if isinstance(candidate, str):
                                message += ": " + candidate.replace(token, "[redacted]")[:2000]
                        except (ValueError, UnicodeError):
                            pass
                        output = {"status": "error", "success": False, "error": message}
                    else:
                        payload = json.loads(raw)
                        if not isinstance(payload, dict):
                            raise ValueError("Responder returned an unexpected JSON representation")
                        if payload.get("status") is False or str(payload.get("status", "")).lower() == "false" or payload.get("error") or payload.get("errors"):
                            message = payload.get("message") or payload.get("error") or "Responder returned an error envelope"
                            output = {"status": "error", "success": False, "error": str(message).replace(token, "[redacted]")[:2000]}
                        else:
                            output = {"status": "success", "success": True, "data": payload}
                            if config.operation.startswith("list_") and isinstance(payload.get("data"), list):
                                output["items"] = payload["data"]
        except (httpx.HTTPError, OSError, ValueError):
            output = {"status": "error", "success": False, "error": "Responder request did not return a verifiable response"}
        if write and not output["success"]:
            output["write_outcome"] = "unknown" if http_status is None or http_status < 400 or http_status >= 500 else "rejected"
        output = _redact({"operation": config.operation, "http_status": http_status, **output}, token)
        await self.emit(output)
        return output
