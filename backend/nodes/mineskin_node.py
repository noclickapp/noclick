"""MineSkin v2 skin generation and account reads.

Contract: https://api.mineskin.org/v2/openapi.json (2.0.0).
Each operation makes one request; queue submission never implies completion.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://api.mineskin.org"


class MineSkinAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="MineSkin API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://account.mineskin.org/keys",
        "x-credential-instructions": "Paste your MineSkin API key without the Bearer prefix. NoClick checks the user associated with this key. Generation may consume your MineSkin allowance; batch generation requires the Pro+ batch_generation grant.",
    })
    credential_type: Literal["mineskin_api_key"] = Field("mineskin_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GenerateRequest(_Input):
    url: str | None = Field(None, min_length=1, description="PNG image URL or base64 data URL. MineSkin fetches it; NoClick does not download it.")
    user: str | None = Field(None, min_length=32, max_length=36, description="Minecraft player UUID. Supply either URL or player UUID.")
    variant: Literal["classic", "slim", "unknown"] | None = None
    name: str | None = Field(None, max_length=48)
    visibility: Literal["public", "unlisted", "private"] | None = Field(None, description="MineSkin defaults to public. Private skins require the corresponding grant.")
    cape: str | None = Field(None, description="Cape UUID; availability depends on account grants and ownership.")

    @field_validator("user", "cape")
    @classmethod
    def uuid_value(cls, value):
        if value is not None:
            UUID(value)
        return value

    @model_validator(mode="after")
    def one_source(self):
        if (self.url is None) == (self.user is None):
            raise ValueError("Supply exactly one of URL or player UUID")
        return self


class GenerateSkin(GenerateRequest):
    operation: Literal["generate_skin"] = Field("generate_skin", title="Generate Skin", description="Wait for skin generation. Queue Skin is recommended for asynchronous workflows.", json_schema_extra={"ui:hidden": True})


class QueueSkin(GenerateRequest):
    operation: Literal["queue_skin"] = Field("queue_skin", title="Queue Skin Generation", json_schema_extra={"ui:hidden": True})


class QueueBatch(_Input):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-tier": "batch_generation", "x-tier-label": "Pro+"})
    operation: Literal["queue_batch"] = Field("queue_batch", title="Queue Batch Generation", json_schema_extra={"ui:hidden": True})
    batch: list[GenerateRequest] = Field(..., min_length=1, max_length=24, description="One to 24 URL or player requests; each result can fail independently. Counts against your rate allowance.")


class ListJobs(_Input):
    operation: Literal["list_jobs"] = Field("list_jobs", title="List Recent Queue Jobs", json_schema_extra={"ui:hidden": True})


class GetJob(_Input):
    operation: Literal["get_job"] = Field("get_job", title="Get Job Status", json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", description="Job ID returned by submission. Check at most once per second. Job IDs need not be UUIDs.")


class GetSkin(_Input):
    operation: Literal["get_skin"] = Field("get_skin", title="Get Skin", json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description="Skin UUID, with or without hyphens.")

    @field_validator("uuid")
    @classmethod
    def skin_uuid(cls, value):
        UUID(value)
        return value


class ListSkins(_Input):
    operation: Literal["list_skins"] = Field("list_skins", title="List Skins", json_schema_extra={"ui:hidden": True})
    after: str | None = Field(None, max_length=1000, description="Reference of the last skin on the previous page. Returns one page and provider pagination links.")


class ListCapes(_Input):
    operation: Literal["list_capes"] = Field("list_capes", title="List Known Capes", json_schema_extra={"ui:hidden": True})


class GetUser(_Input):
    operation: Literal["get_user"] = Field("get_user", title="Get Current User", json_schema_extra={"ui:hidden": True})


class ListUserCapes(_Input):
    operation: Literal["list_user_capes"] = Field("list_user_capes", title="List My Capes", json_schema_extra={"ui:hidden": True})


class GetAPIKey(_Input):
    operation: Literal["get_api_key"] = Field("get_api_key", title="Get API Key Details", json_schema_extra={"ui:hidden": True})


class GetClient(_Input):
    operation: Literal["get_client"] = Field("get_client", title="Get Current Client", json_schema_extra={"ui:hidden": True})


MineSkinOperation = Annotated[Union[GenerateSkin, QueueSkin, QueueBatch, ListJobs, GetJob, GetSkin, ListSkins, ListCapes, GetUser, ListUserCapes, GetAPIKey, GetClient], Field(discriminator="operation")]


class MineSkinConfig(NodeConfig[MineSkinOperation, MineSkinAPIKeyCredential]):
    pass


ROUTES = {
    "generate_skin": ("POST", "/v2/generate"),
    "queue_skin": ("POST", "/v2/queue"),
    "queue_batch": ("POST", "/v2/queue/batch"),
    "list_jobs": ("GET", "/v2/queue"),
    "get_job": ("GET", "/v2/queue/{job_id}"),
    "get_skin": ("GET", "/v2/skins/{uuid}"),
    "list_skins": ("GET", "/v2/skins"),
    "list_capes": ("GET", "/v2/capes"),
    "get_user": ("GET", "/v2/me"),
    "list_user_capes": ("GET", "/v2/me/capes"),
    "get_api_key": ("GET", "/v2/me/apikey"),
    "get_client": ("GET", "/v2/me/client"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class MineSkinNode(WorkflowNode):
    integration_type = "automation-mineskin"
    connection_evidence = ConnectionEvidence(noun="MineSkin account", identity_operation="get_user", identity_keys=("user",))

    @classmethod
    def get_config_model(cls):
        return MineSkinConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a MineSkin API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        for name in ("job_id", "uuid"):
            if name in values:
                path = path.replace("{" + name + "}", str(UUID(values.pop(name))) if name == "uuid" else values.pop(name))
        headers = {"Authorization": "Bearer " + key, "User-Agent": "NoClick/1.0 (+https://noclick.com)", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers, **({"json": values} if method == "POST" else {"params": values}))
            try:
                body = response.json()
            except ValueError:
                raise ValueError("MineSkin returned a non-JSON response") from None
            if not isinstance(body, dict):
                raise ValueError("MineSkin returned an unexpected response shape")
            if not response.is_success or body.get("success") is False:
                result = {"status": "error", "http_status": response.status_code, "data": body, "error": body.get("errors") or "MineSkin rejected the request"}
            else:
                result = {"status": "success", "http_status": response.status_code, "data": body}
                if op.operation == "get_user":
                    if not isinstance(body.get("user"), str) or not body["user"]:
                        raise ValueError("MineSkin did not return the current user")
                    result["user"] = body["user"]
        except httpx.HTTPError:
            result = {"status": "error", "error": "MineSkin request did not complete; inspect queue jobs before retrying generation"}
        result = _redact(result, key)
        await self.emit(result)
        return result
