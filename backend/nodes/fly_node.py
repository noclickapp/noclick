"""Fly Machines API v1: apps, machine lifecycle and persistent volumes.

Contract: https://docs.fly.io/api/machines/openapi.json (version 1.0).
Requests never retry writes or follow redirects. List operations return one page.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class FlyTokenCredential(BaseModel):
    model_config = ConfigDict(title="Fly API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.fly.io/security/tokens",
        "x-credential-instructions": "Paste an app-scoped deploy token for one app, or an organization token for app creation and organization-wide access. Create the narrowest token needed using fly tokens create deploy or fly tokens create org. Read-only tokens support reads only. NoClick sends it as a Bearer token to api.machines.dev."})
    credential_type: Literal["fly_api_token"] = Field("fly_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=16384, title="API token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste only the Fly token without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name in {"app_name", "machine_id", "volume_id", "org_slug"}:
            if not value or value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
                raise ValueError("Use a Fly name or ID, without a URL or path")
        return value


class _App(_Input):
    app_name: str = Field(..., min_length=1, max_length=255, description="Fly app name, for example my-app.")


class _Machine(_App):
    machine_id: str = Field(..., min_length=1, max_length=128, description="Machine ID returned by list or create.")


class _Volume(_App):
    volume_id: str = Field(..., min_length=1, max_length=128, description="Volume ID returned by list or create.")


class _Page(_App):
    limit: int = Field(100, ge=1, le=1000, description="Page size; the provider may return an empty page with a next cursor.")
    cursor: str | None = Field(None, max_length=4096, description="Pass next_cursor from the previous result within 30 minutes.")


# Fly.io's own MCP server: agents get its tools through a person's Fly.io sign-in.
FlyMcpCredential = mcp_credential("fly", "https://mcp.fly.io", app="Fly.io")
FlyCredential = Union[FlyTokenCredential, FlyMcpCredential]


Signal = Literal["SIGHUP", "SIGINT", "SIGQUIT", "SIGKILL", "SIGUSR1", "SIGUSR2", "SIGTERM"]


class FlyGetCurrentTokenConfig(_Input):
    """Get current token."""
    operation: Literal["get_current_token"] = Field("get_current_token", json_schema_extra={"ui:hidden": True})


class FlyListAppsConfig(_Input):
    """List apps."""
    operation: Literal["list_apps"] = Field("list_apps", json_schema_extra={"ui:hidden": True})
    org_slug: str = Field(..., min_length=1, max_length=255, description="Organization slug, or personal.")
    limit: int = Field(100, ge=1, le=5000)
    cursor: str | None = Field(None, max_length=4096)


class FlyCreateAppConfig(_Input):
    """Create app."""
    operation: Literal["create_app"] = Field("create_app", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    org_slug: str = Field(..., min_length=1, max_length=255)
    network: str | None = None
    idempotency_key: str | None = Field(None, description="Reuse for retries of the same create request.")


class FlyGetAppConfig(_App):
    """Get app."""
    operation: Literal["get_app"] = Field("get_app", json_schema_extra={"ui:hidden": True})


class FlyDeleteAppConfig(_App):
    """Delete app."""
    operation: Literal["delete_app"] = Field("delete_app", json_schema_extra={"ui:hidden": True})


class FlyListMachinesConfig(_Page):
    """List machines."""
    operation: Literal["list_machines"] = Field("list_machines", json_schema_extra={"ui:hidden": True})
    region: str | None = None
    include_deleted: bool = False


class FlyCreateMachineConfig(_App):
    """Create machine."""
    operation: Literal["create_machine"] = Field("create_machine", json_schema_extra={"ui:hidden": True})
    machine_config: dict[str, Any] = Field(..., description="Complete Fly Machine config object, including image, env, services, guest and mounts as needed. Updating replaces the configuration; provide all fields to retain.", json_schema_extra={"ui:widget": "json"})
    name: str | None = None
    region: str | None = None
    skip_launch: bool = False


class FlyUpdateMachineConfig(_Machine):
    """Update machine."""
    operation: Literal["update_machine"] = Field("update_machine", json_schema_extra={"ui:hidden": True})
    machine_config: dict[str, Any] = Field(..., description="Complete Fly Machine config object, including image, env, services, guest and mounts as needed. Updating replaces the configuration; provide all fields to retain.", json_schema_extra={"ui:widget": "json"})
    name: str | None = None
    region: str | None = None
    skip_launch: bool = False
    current_version: str | None = Field(None, description="Optimistic concurrency guard from the previous machine response.")


class FlyGetMachineConfig(_Machine):
    """Get machine."""
    operation: Literal["get_machine"] = Field("get_machine", json_schema_extra={"ui:hidden": True})


class FlyDeleteMachineConfig(_Machine):
    """Delete machine."""
    operation: Literal["delete_machine"] = Field("delete_machine", json_schema_extra={"ui:hidden": True})
    force: bool = Field(False, description="Kill a running Machine before deleting it.")


class FlyStartMachineConfig(_Machine):
    """Start machine."""
    operation: Literal["start_machine"] = Field("start_machine", json_schema_extra={"ui:hidden": True})


class FlyStopMachineConfig(_Machine):
    """Stop machine."""
    operation: Literal["stop_machine"] = Field("stop_machine", json_schema_extra={"ui:hidden": True})
    signal: Signal | None = None
    timeout: str | None = Field(None, max_length=64, description="Go duration such as 30s.")


class FlyRestartMachineConfig(_Machine):
    """Restart machine."""
    operation: Literal["restart_machine"] = Field("restart_machine", json_schema_extra={"ui:hidden": True})
    signal: Signal | None = None
    timeout: str | None = Field(None, max_length=64, description="Go duration such as 30s.")


class FlySuspendMachineConfig(_Machine):
    """Suspend machine."""
    operation: Literal["suspend_machine"] = Field("suspend_machine", json_schema_extra={"ui:hidden": True})


class FlyListMachineEventsConfig(_Machine):
    """List machine events."""
    operation: Literal["list_machine_events"] = Field("list_machine_events", json_schema_extra={"ui:hidden": True})
    limit: int = Field(20, ge=1, le=50)


class FlyListVolumesConfig(_Page):
    """List volumes."""
    operation: Literal["list_volumes"] = Field("list_volumes", json_schema_extra={"ui:hidden": True})


class FlyCreateVolumeConfig(_App):
    """Create volume."""
    operation: Literal["create_volume"] = Field("create_volume", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    region: str = Field(..., min_length=1, max_length=32)
    size_gb: int = Field(..., ge=1)
    encrypted: bool = True
    snapshot_id: str | None = None


class FlyGetVolumeConfig(_Volume):
    """Get volume."""
    operation: Literal["get_volume"] = Field("get_volume", json_schema_extra={"ui:hidden": True})


class FlyDeleteVolumeConfig(_Volume):
    """Delete volume."""
    operation: Literal["delete_volume"] = Field("delete_volume", json_schema_extra={"ui:hidden": True})


class FlyExtendVolumeConfig(_Volume):
    """Extend volume."""
    operation: Literal["extend_volume"] = Field("extend_volume", json_schema_extra={"ui:hidden": True})
    size_gb: int = Field(..., ge=1, description="New size in GB; volumes cannot shrink.")


class FlyListVolumeSnapshotsConfig(_Volume):
    """List volume snapshots."""
    operation: Literal["list_volume_snapshots"] = Field("list_volume_snapshots", json_schema_extra={"ui:hidden": True})


class FlyCreateVolumeSnapshotConfig(_Volume):
    """Create volume snapshot."""
    operation: Literal["create_volume_snapshot"] = Field("create_volume_snapshot", json_schema_extra={"ui:hidden": True})


FlyConfig = Annotated[Union[
    FlyGetCurrentTokenConfig,
    FlyListAppsConfig,
    FlyCreateAppConfig,
    FlyGetAppConfig,
    FlyDeleteAppConfig,
    FlyListMachinesConfig,
    FlyCreateMachineConfig,
    FlyUpdateMachineConfig,
    FlyGetMachineConfig,
    FlyDeleteMachineConfig,
    FlyStartMachineConfig,
    FlyStopMachineConfig,
    FlyRestartMachineConfig,
    FlySuspendMachineConfig,
    FlyListMachineEventsConfig,
    FlyListVolumesConfig,
    FlyCreateVolumeConfig,
    FlyGetVolumeConfig,
    FlyDeleteVolumeConfig,
    FlyExtendVolumeConfig,
    FlyListVolumeSnapshotsConfig,
    FlyCreateVolumeSnapshotConfig,
], Field(discriminator="operation")]


class FlyFullConfig(NodeConfig[FlyConfig, FlyCredential]):
    pass


# Each entry maps exactly one operation to one published Machines API endpoint.
ROUTES = {
    'get_current_token': ('GET', '/v1/tokens/current', (), (), 200),
    'list_apps': ('GET', '/v1/apps', ('org_slug', 'limit', 'cursor'), (), 200),
    'create_app': ('POST', '/v1/apps', (), ('name', 'org_slug', 'network', 'idempotency_key'), 201),
    'get_app': ('GET', '/v1/apps/{app_name}', (), (), 200),
    'delete_app': ('DELETE', '/v1/apps/{app_name}', (), (), 202),
    'list_machines': ('GET', '/v1/apps/{app_name}/machines', ('limit', 'cursor', 'region', 'include_deleted'), (), 200),
    'create_machine': ('POST', '/v1/apps/{app_name}/machines', (), ('machine_config', 'name', 'region', 'skip_launch'), 200),
    'update_machine': ('POST', '/v1/apps/{app_name}/machines/{machine_id}', (), ('machine_config', 'name', 'region', 'skip_launch', 'current_version'), 200),
    'get_machine': ('GET', '/v1/apps/{app_name}/machines/{machine_id}', (), (), 200),
    'delete_machine': ('DELETE', '/v1/apps/{app_name}/machines/{machine_id}', ('force',), (), 200),
    'start_machine': ('POST', '/v1/apps/{app_name}/machines/{machine_id}/start', (), (), 200),
    'stop_machine': ('POST', '/v1/apps/{app_name}/machines/{machine_id}/stop', (), ('signal', 'timeout'), 200),
    'restart_machine': ('POST', '/v1/apps/{app_name}/machines/{machine_id}/restart', ('signal', 'timeout'), (), 200),
    'suspend_machine': ('POST', '/v1/apps/{app_name}/machines/{machine_id}/suspend', (), (), 200),
    'list_machine_events': ('GET', '/v1/apps/{app_name}/machines/{machine_id}/events', ('limit',), (), 200),
    'list_volumes': ('GET', '/v1/apps/{app_name}/volumes', ('limit', 'cursor'), (), 200),
    'create_volume': ('POST', '/v1/apps/{app_name}/volumes', (), ('name', 'region', 'size_gb', 'encrypted', 'snapshot_id'), 200),
    'get_volume': ('GET', '/v1/apps/{app_name}/volumes/{volume_id}', (), (), 200),
    'delete_volume': ('DELETE', '/v1/apps/{app_name}/volumes/{volume_id}', (), (), 200),
    'extend_volume': ('PUT', '/v1/apps/{app_name}/volumes/{volume_id}/extend', (), ('size_gb',), 200),
    'list_volume_snapshots': ('GET', '/v1/apps/{app_name}/volumes/{volume_id}/snapshots', (), (), 200),
    'create_volume_snapshot': ('POST', '/v1/apps/{app_name}/volumes/{volume_id}/snapshots', (), (), 200),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class FlyNode(WorkflowNode):
    integration_type = "automation-fly"
    credential_provider_labels = {"fly": "Fly.io Account"}
    connection_evidence = ConnectionEvidence(noun="Fly token", operation="get_current_token", label_keys=("org_slug", "organization", "user", "token_id"))

    @classmethod
    def get_config_model(cls):
        return FlyFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Fly API token")
        token = self.config.credentials.api_token
        op = self.config.config
        method, template, query, body_fields, expected = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        path = template.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params = {key: str(values[key]).lower() if isinstance(values[key], bool) else values[key] for key in query if key in values}
        body = {"config" if key == "machine_config" else key: values[key] for key in body_fields if key in values}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.machines.dev" + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=params, **({"json": body} if body_fields else {}))
        except httpx.RequestError:
            raise ValueError("Fly request failed; a write may have completed. Check Fly before retrying.") from None
        if response.status_code != expected:
            message = "Fly request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("error") or error.get("message") or message
            except ValueError:
                pass
            raise ValueError(_redact(f"{message} (HTTP {response.status_code})", token))
        if expected == 202 or op.operation == "create_volume_snapshot":
            # Snapshot creation is asynchronous and has no response schema.
            result = {"status": "accepted", "http_status": expected, "completed": False}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Fly response exceeded 10 MB")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Fly returned an invalid JSON response") from None
            if not isinstance(data, (dict, list)) or (isinstance(data, dict) and (data.get("error") or data.get("errors"))):
                raise ValueError("Fly returned an unexpected response")
            result = {"status": "success", "data": data, "http_status": expected}
            if op.operation in {"list_machines", "list_volumes", "list_apps"}:
                cursor = data.get("next_cursor") if isinstance(data, dict) else response.headers.get("fly-next-cursor")
                result.update(next_cursor=cursor or None, has_more=bool(cursor))
        result = _redact(result, token)
        await self.emit(result)
        return result
