"""Nango environment API: integrations, connection metadata, records and functions.

Each operation makes one documented request. Pagination is explicit; sync/action
acknowledgements are returned without claiming downstream execution completed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.nango.dev"


class NangoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Nango API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.nango.dev",
            "x-credential-instructions": "Paste an environment API key from Nango's Environment settings → API Keys. Select permissions for the operations you use, including listing integrations for the connection check. NoClick sends it as a Bearer token to api.nango.dev."})
    credential_type: Literal["nango_api_key"] = Field("nango_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Environment API key", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Environment API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def no_controls(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a value without control characters")
        return value


class ListIntegrationsConfig(_Input):
    """List the integrations configured in this Nango environment."""
    operation: Literal["list_integrations"] = "list_integrations"


class _Integration(_Input):
    unique_key: str = Field(..., min_length=1, max_length=255, description="Nango integration ID (unique key).")


class GetIntegrationConfig(_Integration):
    """Read integration details, without requesting credentials or webhook secrets."""
    operation: Literal["get_integration"] = "get_integration"


class CreateIntegrationConfig(_Integration):
    """Create an integration without developer-app credentials; configure those in Nango."""
    operation: Literal["create_integration"] = "create_integration"
    provider: str = Field(..., min_length=1, max_length=255, description="Nango provider name, for example github.")
    display_name: str | None = Field(None, max_length=255)
    forward_webhooks: StrictBool | None = None


class UpdateIntegrationConfig(_Integration):
    """Update the display name and webhook forwarding preference."""
    operation: Literal["update_integration"] = "update_integration"
    display_name: str = Field(..., min_length=1, max_length=255)
    forward_webhooks: StrictBool | None = None


class DeleteIntegrationConfig(_Integration):
    """Delete the selected integration from Nango."""
    operation: Literal["delete_integration"] = "delete_integration"


class ListFunctionsConfig(_Integration):
    """List one page of integration functions. Requires environment:functions:list."""
    operation: Literal["list_functions"] = "list_functions"
    type: Literal["sync", "action", "on-event", "tool"] | None = None
    search: str | None = Field(None, min_length=1, max_length=255)
    page: int = Field(0, ge=0)
    limit: int = Field(20, ge=1, le=100)


class ListConnectionsConfig(_Input):
    """List one page of connections, without connection credentials."""
    operation: Literal["list_connections"] = "list_connections"
    connection_id: str | None = Field(None, min_length=1, max_length=255, description="Exact connection ID filter, across integrations.")
    page: int = Field(1, ge=1)
    limit: int = Field(100, ge=1, le=100)


class _Connection(_Input):
    provider_config_key: str = Field(..., min_length=1, max_length=255, description="Nango integration ID.")
    connection_id: str = Field(..., min_length=1, max_length=255)


class GetConnectionConfig(_Connection):
    """Read connection details. Credentials returned by Nango are removed from output."""
    operation: Literal["get_connection"] = "get_connection"


class UpdateConnectionConfig(_Connection):
    """Update connection tags; keys are normalized to lowercase by Nango."""
    operation: Literal["update_connection"] = "update_connection"
    tags: dict[str, str] = Field(..., max_length=10, description="Up to ten string tags, each value at most 255 characters.")

    @field_validator("tags")
    @classmethod
    def tag_values(cls, value):
        if any(len(v) > 255 for v in value.values()):
            raise ValueError("Tag values must be at most 255 characters")
        return value


class DeleteConnectionConfig(_Connection):
    """Delete the connection within the selected integration."""
    operation: Literal["delete_connection"] = "delete_connection"


class SetConnectionMetadataConfig(_Connection):
    """Replace metadata on a single connection."""
    operation: Literal["set_connection_metadata"] = "set_connection_metadata"
    metadata: dict = Field(..., description="Full replacement metadata object.")


class UpdateConnectionMetadataConfig(_Connection):
    """Merge supplied metadata fields into a single connection's metadata."""
    operation: Literal["update_connection_metadata"] = "update_connection_metadata"
    metadata: dict = Field(..., description="Metadata fields to merge.")


class GetRecordsConfig(_Connection):
    """Fetch one page of synced records. Continue with next_cursor until null."""
    operation: Literal["get_records"] = "get_records"
    model: str = Field(..., min_length=1, max_length=255)
    cursor: str | None = Field(None, max_length=4096)
    limit: int = Field(100, ge=1, le=1000)
    filter: Literal["added", "updated", "deleted"] | None = None
    modified_after: AwareDatetime | None = Field(None, description="ISO 8601 date-time.")
    variant: str | None = Field(None, max_length=255)


class _Sync(_Connection):
    syncs: list[str] = Field(..., min_length=1, max_length=100, description="Explicit sync names. This node targets one connection.")


class TriggerSyncConfig(_Sync):
    """Trigger syncs for one connection. The acknowledgement does not prove completion."""
    operation: Literal["trigger_sync"] = "trigger_sync"


class StartSyncConfig(_Sync):
    """Start scheduled syncs for one connection."""
    operation: Literal["start_sync"] = "start_sync"


class PauseSyncConfig(_Sync):
    """Pause scheduled syncs for one connection."""
    operation: Literal["pause_sync"] = "pause_sync"


class GetSyncStatusConfig(_Connection):
    """Read sync status for one connection."""
    operation: Literal["get_sync_status"] = "get_sync_status"
    syncs: str = Field("*", max_length=4096, description="Comma-separated sync names, name::variant, or * for all.")


class TriggerActionConfig(_Connection):
    """Trigger an action once; async acknowledgements return an ID for polling."""
    operation: Literal["trigger_action"] = "trigger_action"
    action_name: str = Field(..., min_length=1, max_length=255)
    input: dict = Field(default_factory=dict)
    asynchronous: StrictBool = Field(False, description="Return an action ID instead of waiting for the result.")


class GetActionResultConfig(_Input):
    """Read an asynchronous action result by its ID. A 404 can mean it is still running."""
    operation: Literal["get_action_result"] = "get_action_result"
    action_id: str = Field(..., min_length=1, max_length=255)


NangoConfig = Annotated[Union[ListIntegrationsConfig, GetIntegrationConfig,
    CreateIntegrationConfig, UpdateIntegrationConfig, DeleteIntegrationConfig,
    ListFunctionsConfig, ListConnectionsConfig, GetConnectionConfig,
    UpdateConnectionConfig, DeleteConnectionConfig, SetConnectionMetadataConfig,
    UpdateConnectionMetadataConfig, GetRecordsConfig, TriggerSyncConfig,
    StartSyncConfig, PauseSyncConfig, GetSyncStatusConfig, TriggerActionConfig,
    GetActionResultConfig], Field(discriminator="operation")]


class NangoFullConfig(NodeConfig[NangoConfig, NangoAPIKeyCredential]):
    pass


def _segment(value):
    if value in {".", ".."}:
        raise ValueError("Use a Nango resource ID")
    return quote(value, safe="")


def _without_secrets(value, token):
    if isinstance(value, dict):
        return {k: _without_secrets(v, token) for k, v in value.items()
                if k.lower() not in {"credentials", "access_token", "refresh_token", "api_key", "client_secret", "oauth_client_secret", "webhook_url"}}
    if isinstance(value, list):
        return [_without_secrets(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class NangoNode(WorkflowNode):
    integration_type = "automation-nango"
    connection_evidence = ConnectionEvidence(noun="integrations", operation="list_integrations",
        label_keys=("display_name", "unique_key"))

    @classmethod
    def get_config_model(cls):
        return NangoFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Nango environment API key")
        op = config.operation
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        method, path, params, body = "GET", "", {}, None
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        if op == "list_integrations":
            path = "/integrations"
        elif op in {"get_integration", "update_integration", "delete_integration"}:
            path = "/integrations/" + _segment(values.pop("unique_key"))
            method = {"get_integration": "GET", "update_integration": "PATCH", "delete_integration": "DELETE"}[op]
            if method == "PATCH": body = values
        elif op == "create_integration":
            method, path, body = "POST", "/integrations", values
        elif op == "list_functions":
            path = "/integrations/" + _segment(values.pop("unique_key")) + "/functions"
            params = values
        elif op == "list_connections":
            path, params = "/connections", values
            if "connection_id" in params: params["connectionId"] = params.pop("connection_id")
        elif op in {"get_connection", "update_connection", "delete_connection"}:
            path = "/connections/" + _segment(values.pop("connection_id"))
            params = {"provider_config_key": values.pop("provider_config_key")}
            method = {"get_connection": "GET", "update_connection": "PATCH", "delete_connection": "DELETE"}[op]
            if method == "PATCH": body = values
        elif op in {"set_connection_metadata", "update_connection_metadata"}:
            path, body = "/connections/metadata", values
            method = "POST" if op == "set_connection_metadata" else "PATCH"
        elif op in {"get_records", "trigger_action"}:
            headers["Connection-Id"] = values.pop("connection_id")
            headers["Provider-Config-Key"] = values.pop("provider_config_key")
            if op == "get_records": path, params = "/records", values
            else:
                headers["X-Async"] = "true" if values.pop("asynchronous") else "false"
                method, path, body = "POST", "/action/trigger", values
        elif op in {"trigger_sync", "start_sync", "pause_sync"}:
            method, path, body = "POST", "/sync/" + op.removesuffix("_sync"), values
        elif op == "get_sync_status":
            path, params = "/sync/status", values
        elif op == "get_action_result":
            path = "/action/" + _segment(values["action_id"])
        else:
            raise ValueError("Unknown Nango operation")
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body, headers=headers)
        if not 200 <= response.status_code < 300:
            detail = response.text[:1000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Nango HTTP {response.status_code}: {detail}")
        if "application/json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Nango returned a non-JSON response")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Nango returned an unexpected response shape")
        if payload.get("error") or payload.get("success") is False:
            raise ValueError("Nango rejected the request: " + str(_without_secrets(payload, credential.api_key))[:1000])
        expected = {
            "list_integrations": ("data", list), "list_functions": ("data", list),
            "get_integration": ("data", dict), "create_integration": ("data", dict),
            "update_integration": ("data", dict), "list_connections": ("connections", list),
            "get_records": ("records", list), "get_sync_status": ("syncs", list),
            "delete_integration": ("success", bool), "update_connection": ("success", bool),
            "delete_connection": ("success", bool), "trigger_sync": ("success", bool),
            "start_sync": ("success", bool), "pause_sync": ("success", bool),
        }.get(op)
        if expected and not isinstance(payload.get(expected[0]), expected[1]):
            raise ValueError("Nango returned an unexpected response shape")
        return _without_secrets(payload, credential.api_key)
