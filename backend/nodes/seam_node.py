"""Seam workspace API: one published HTTP operation per workflow operation.

Contract: https://connect.getseam.com/openapi.json (1.0.0).
Actions return Seam's action_attempt; acceptance does not prove device completion.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
from uuid import UUID
from datetime import datetime
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://connect.getseam.com"
NODE_TYPE = "automation-seam"

class SeamAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Seam API Key", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://console.seam.co/",
            "x-credential-instructions": "Create an API key in your Seam workspace in Seam Console and paste it here. Use a sandbox workspace key for testing. NoClick sends it only to connect.getseam.com and reads the workspace to verify the connection."})
    credential_type: Literal["seam_api_key"] = Field("seam_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or value.lower().startswith("bearer"):
            raise ValueError("Paste only the Seam API key, without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class _Page(_Input):
    limit: int = Field(100, ge=1, le=1000, description="Maximum records on this page.")
    page_cursor: str | None = Field(None, min_length=1, max_length=4096, description="Use pagination.next_page_cursor from the previous response; only one page is returned.")

class _Device(_Input):
    device_id: UUID = Field(..., description="Seam device ID, from List Devices.")

class _AccessCode(_Input):
    access_code_id: UUID = Field(..., description="Seam access code ID, from List Access Codes.")

class _ConnectedAccount(_Input):
    connected_account_id: UUID = Field(..., description="Seam connected account ID.")

class _CodeFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=500)
    code: str | None = Field(None, min_length=4, max_length=12, pattern=r"^[0-9]+$", description="Numeric access code; omit on creation to let Seam generate it.")
    starts_at: str | None = Field(None, description="ISO 8601 timestamp including timezone.")
    ends_at: str | None = Field(None, description="ISO 8601 timestamp including timezone, after starts_at.")

    @field_validator("starts_at", "ends_at")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None: raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO 8601 timestamp with a timezone") from None
        return value

    @model_validator(mode="after")
    def order(self):
        if self.starts_at and self.ends_at and datetime.fromisoformat(self.starts_at.replace("Z", "+00:00")) >= datetime.fromisoformat(self.ends_at.replace("Z", "+00:00")):
            raise ValueError("ends_at must follow starts_at")
        return self

class GetWorkspace(_Input):
    """Read the workspace associated with your API key."""
    operation: Literal["get_workspace"] = Field("get_workspace", json_schema_extra={"ui:hidden": True})


class ListDevices(_Page):
    """Return one page of devices, with optional account and text filters."""
    operation: Literal["list_devices"] = Field("list_devices", json_schema_extra={"ui:hidden": True})
    connected_account_id: UUID | None = None
    search: str | None = Field(None, min_length=1, max_length=500)


class GetDevice(_Device):
    """Read a device by its Seam device ID."""
    operation: Literal["get_device"] = Field("get_device", json_schema_extra={"ui:hidden": True})


class UpdateDevice(_Device):
    """Change the name of a device."""
    operation: Literal["update_device"] = Field("update_device", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500, description="New device name.")


class ListLocks(_Input):
    """List locks, optionally restricted to a connected account."""
    operation: Literal["list_locks"] = Field("list_locks", json_schema_extra={"ui:hidden": True})
    connected_account_id: UUID | None = None


class GetLock(_Device):
    """Read the current properties of one lock."""
    operation: Literal["get_lock"] = Field("get_lock", json_schema_extra={"ui:hidden": True})


class LockDoor(_Device):
    """Request that a lock close; inspect the returned action attempt for completion."""
    operation: Literal["lock_door"] = Field("lock_door", json_schema_extra={"ui:hidden": True})


class UnlockDoor(_Device):
    """Request that a lock open; inspect the returned action attempt for completion."""
    operation: Literal["unlock_door"] = Field("unlock_door", json_schema_extra={"ui:hidden": True})


class ListAccessCodes(_Page):
    """Return one page of access codes, optionally restricted to a device."""
    operation: Literal["list_access_codes"] = Field("list_access_codes", json_schema_extra={"ui:hidden": True})
    device_id: UUID | None = None


class GetAccessCode(_AccessCode):
    """Read an access code by its Seam access code ID."""
    operation: Literal["get_access_code"] = Field("get_access_code", json_schema_extra={"ui:hidden": True})


class CreateAccessCode(_Device, _CodeFields):
    """Create an ongoing or scheduled access code for a device."""
    operation: Literal["create_access_code"] = Field("create_access_code", json_schema_extra={"ui:hidden": True})


class UpdateAccessCode(_AccessCode, _CodeFields):
    """Change an access code name, code, or schedule."""
    operation: Literal["update_access_code"] = Field("update_access_code", json_schema_extra={"ui:hidden": True})
    @model_validator(mode="after")
    def changed(self):
        if not any(getattr(self, k) is not None for k in ("name", "code", "starts_at", "ends_at")):
            raise ValueError("Supply at least one access code field to update")
        return self


class DeleteAccessCode(_AccessCode):
    """Request removal of an access code and return its action attempt."""
    operation: Literal["delete_access_code"] = Field("delete_access_code", json_schema_extra={"ui:hidden": True})


class ListConnectedAccounts(_Page):
    """Return one page of connected device-provider accounts."""
    operation: Literal["list_connected_accounts"] = Field("list_connected_accounts", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, min_length=1, max_length=500)


class GetConnectedAccount(_ConnectedAccount):
    """Read a connected device-provider account."""
    operation: Literal["get_connected_account"] = Field("get_connected_account", json_schema_extra={"ui:hidden": True})


class SyncConnectedAccount(_ConnectedAccount):
    """Request synchronization of a connected device-provider account."""
    operation: Literal["sync_connected_account"] = Field("sync_connected_account", json_schema_extra={"ui:hidden": True})


class GetActionAttempt(_Input):
    """Read an action attempt to check whether a device action completed or failed."""
    operation: Literal["get_action_attempt"] = Field("get_action_attempt", json_schema_extra={"ui:hidden": True})
    action_attempt_id: UUID


Operation = Annotated[Union[GetWorkspace, ListDevices, GetDevice, UpdateDevice, ListLocks, GetLock, LockDoor, UnlockDoor, ListAccessCodes, GetAccessCode, CreateAccessCode, UpdateAccessCode, DeleteAccessCode, ListConnectedAccounts, GetConnectedAccount, SyncConnectedAccount, GetActionAttempt], Field(discriminator="operation")]

class SeamFullConfig(NodeConfig[Operation, SeamAPIKeyCredential]):
    pass

ROUTES = {'get_workspace': ('GET', '/workspaces/get', 'workspace'),
 'list_devices': ('GET', '/devices/list', 'devices'),
 'get_device': ('GET', '/devices/get', 'device'),
 'update_device': ('PATCH', '/devices/update', None),
 'list_locks': ('GET', '/locks/list', 'locks'),
 'get_lock': ('GET', '/locks/get', 'lock'),
 'lock_door': ('POST', '/locks/lock_door', 'action_attempt'),
 'unlock_door': ('POST', '/locks/unlock_door', 'action_attempt'),
 'list_access_codes': ('GET', '/access_codes/list', 'access_codes'),
 'get_access_code': ('GET', '/access_codes/get', 'access_code'),
 'create_access_code': ('POST', '/access_codes/create', 'access_code'),
 'update_access_code': ('PATCH', '/access_codes/update', 'action_attempt'),
 'delete_access_code': ('DELETE', '/access_codes/delete', 'action_attempt'),
 'list_connected_accounts': ('GET', '/connected_accounts/list', 'connected_accounts'),
 'get_connected_account': ('GET', '/connected_accounts/get', 'connected_account'),
 'sync_connected_account': ('POST', '/connected_accounts/sync', None),
 'get_action_attempt': ('GET', '/action_attempts/get', 'action_attempt')}

class SeamNode(WorkflowNode):
    integration_type = "automation-seam"
    connection_evidence = ConnectionEvidence(noun="workspace", identity_operation="get_workspace", identity_keys=("name", "workspace_id"))

    @classmethod
    def get_config_model(cls):
        return SeamFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Seam API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path, result_key = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        # Only scalar query parameters are exposed: no ambiguous array/object encoding.
        kwargs = {"params": values} if method in {"GET", "DELETE"} else {"json": values}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **kwargs)
        if len(response.content) > 5_000_000:
            raise ValueError("Seam response exceeds the supported size")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Seam returned a non-JSON response") from None
        if not isinstance(body, dict):
            raise ValueError("Seam returned an invalid response")
        if response.status_code != 200 or body.get("ok") is not True or body.get("error"):
            error = body.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            return {"status": "error", "http_status": response.status_code,
                "error": message.replace(key, "[redacted]") if isinstance(message, str) else "Seam did not confirm this request"}
        if result_key:
            expected = list if result_key in {"devices", "locks", "access_codes", "connected_accounts"} else dict
            if not isinstance(body.get(result_key), expected):
                raise ValueError("Seam response is missing the expected resource")
        if config.operation == "get_workspace":
            workspace = body["workspace"]
            try:
                UUID(workspace.get("workspace_id", ""))
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Seam returned an invalid workspace identity") from None
            if not isinstance(workspace.get("name"), str) or not workspace["name"].strip():
                raise ValueError("Seam returned no workspace name")
        # Keep pagination and asynchronous action state exactly as Seam returns them.
        # No retries or polling: callers inspect action_attempt using Get Action Attempt.
        return {**body, "status": "success"}
