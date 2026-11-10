"""Hetzner Cloud project resources, pinned to the published Cloud OpenAPI contract."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.hetzner.cloud/v1"
ID = Annotated[int, Field(ge=1, le=9007199254740991)]


class HetznerAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Hetzner Cloud API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.hetzner.com/",
            "x-credential-instructions": "In your Hetzner Console project, open Security → API tokens and generate a token. Paste it here. Read-only tokens support reads and polling; choose Read & Write for changes. Tokens are scoped to one project.",
        })
    credential_type: Literal["hetzner_api_token"] = Field("hetzner_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without an Authorization header")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Config):
    page: int = Field(1, ge=1, description="Page number; use meta.pagination.next_page from the response.")
    per_page: int = Field(25, ge=1, le=50)


class _FilteredPage(_Page):
    name: Optional[str] = None
    label_selector: Optional[str] = Field(None, description="Hetzner label selector, for example environment=prod.")


class ListServers(_FilteredPage):
    operation: Literal["list_servers"] = Field("list_servers", title="List Servers", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    sort: Literal["id:asc", "id:desc", "name:asc", "name:desc", "created:asc", "created:desc"] = "id:asc"


class GetServer(_Config):
    operation: Literal["get_server"] = Field("get_server", title="Get Server", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    server_id: ID


class CreateServer(_Config):
    operation: Literal["create_server"] = Field("create_server", title="Create Server", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    name: str = Field(..., min_length=1, max_length=253, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$", examples=["my-server"])
    server_type: str = Field(..., min_length=1, examples=["cpx22"])
    image: str = Field(..., min_length=1, examples=["ubuntu-24.04"])
    location: Optional[str] = Field(None, examples=["nbg1"])
    ssh_keys: Optional[list[str]] = Field(None, description="Existing SSH key names or IDs as strings. Without SSH keys Hetzner returns a root password.")
    labels: Optional[dict[str, str]] = None
    user_data: Optional[str] = Field(None, max_length=32768, description="Cloud-init data. Do not put secrets in user data; Hetzner stores it.")
    start_after_create: bool = True


class UpdateServer(_Config):
    operation: Literal["update_server"] = Field("update_server", title="Update Server", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    server_id: ID
    name: Optional[str] = Field(None, min_length=1, examples=["my-server"])
    labels: Optional[dict[str, str]] = Field(None, description="Replaces all existing labels; an empty object clears them.")

    @model_validator(mode="after")
    def changed(self):
        if self.name is None and self.labels is None:
            raise ValueError("Supply a name or the complete replacement labels")
        return self


class DeleteServer(_Config):
    operation: Literal["delete_server"] = Field("delete_server", title="Delete Server", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    server_id: ID = Field(..., description="Permanently deletes this server and its disks.")


class PowerOnServer(_Config):
    operation: Literal["poweron_server"] = Field("poweron_server", title="Power On Server", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    server_id: ID


class ShutdownServer(_Config):
    operation: Literal["shutdown_server"] = Field("shutdown_server", title="Shutdown Server", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    server_id: ID = Field(..., description="Requests a graceful shutdown through ACPI.")


class PowerOffServer(_Config):
    operation: Literal["poweroff_server"] = Field("poweroff_server", title="Power Off Server", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    server_id: ID = Field(..., description="Immediately cuts power; may cause data loss.")


class RebootServer(_Config):
    operation: Literal["reboot_server"] = Field("reboot_server", title="Reboot Server", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    server_id: ID


class CreateServerImage(_Config):
    operation: Literal["create_server_image"] = Field("create_server_image", title="Create Server Image", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    server_id: ID
    description: Optional[str] = None
    type: Literal["snapshot", "backup"] = "snapshot"
    labels: Optional[dict[str, str]] = None


class ListImages(_Page):
    operation: Literal["list_images"] = Field("list_images", title="List Images", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    type: Optional[Literal["system", "snapshot", "backup", "app"]] = None
    label_selector: Optional[str] = None


class GetImage(_Config):
    operation: Literal["get_image"] = Field("get_image", title="Get Image", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    image_id: ID


class ListServerTypes(_Page):
    operation: Literal["list_server_types"] = Field("list_server_types", title="List Server Types", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class ListSSHKeys(_FilteredPage):
    operation: Literal["list_ssh_keys"] = Field("list_ssh_keys", title="List SSH Keys", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class CreateSSHKey(_Config):
    operation: Literal["create_ssh_key"] = Field("create_ssh_key", title="Create SSH Key", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    name: str = Field(..., min_length=1, examples=["My ssh key"])
    public_key: str = Field(..., min_length=1, description="The complete OpenSSH public key, never a private key.")
    labels: Optional[dict[str, str]] = None

    @field_validator("public_key")
    @classmethod
    def public_only(cls, value):
        if "PRIVATE KEY" in value:
            raise ValueError("Use a public SSH key")
        return value


class DeleteSSHKey(_Config):
    operation: Literal["delete_ssh_key"] = Field("delete_ssh_key", title="Delete SSH Key", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    ssh_key_id: ID


class ListVolumes(_FilteredPage):
    operation: Literal["list_volumes"] = Field("list_volumes", title="List Volumes", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class CreateVolume(_Config):
    operation: Literal["create_volume"] = Field("create_volume", title="Create Volume", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    name: str = Field(..., min_length=1, examples=["test-database"])
    size: int = Field(..., ge=10, le=10240, description="Size in GB.", examples=[42])
    location: str = Field(..., min_length=1, examples=["nbg1"])
    format: Optional[Literal["xfs", "ext4"]] = None
    labels: Optional[dict[str, str]] = None


class AttachVolume(_Config):
    operation: Literal["attach_volume"] = Field("attach_volume", title="Attach Volume", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    volume_id: ID
    server_id: ID
    automount: bool = False


class DetachVolume(_Config):
    operation: Literal["detach_volume"] = Field("detach_volume", title="Detach Volume", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    volume_id: ID


class ResizeVolume(_Config):
    operation: Literal["resize_volume"] = Field("resize_volume", title="Resize Volume", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    volume_id: ID
    size: int = Field(..., ge=10, le=10240, description="New size in GB; must exceed the current size.", examples=[50])


class DeleteVolume(_Config):
    operation: Literal["delete_volume"] = Field("delete_volume", title="Delete Volume", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    volume_id: ID = Field(..., description="Permanently deletes the volume and its data.")


class ListFirewalls(_FilteredPage):
    operation: Literal["list_firewalls"] = Field("list_firewalls", title="List Firewalls", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetServerAction(_Config):
    operation: Literal["get_server_action"] = Field("get_server_action", title="Get Server Action", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    server_id: ID
    action_id: ID = Field(..., description="Action ID returned by the server operation. Acknowledged actions may still be running.")


class OnNewServer(PollTriggerConfigBase):
    operation: Literal["on_new_server"] = Field("on_new_server", json_schema_extra={
        "x-is-trigger": True, "x-display-name": "On New Server", "x-category": "Triggers"})
    label_selector: Optional[str] = Field(None, description="Only watch servers matching this label selector. Existing servers form the baseline when armed.")


HetznerConfig = Annotated[Union[ListServers, GetServer, CreateServer, UpdateServer,
    DeleteServer, PowerOnServer, ShutdownServer, PowerOffServer, RebootServer,
    CreateServerImage, ListImages, GetImage, ListServerTypes, ListSSHKeys,
    CreateSSHKey, DeleteSSHKey, ListVolumes, CreateVolume, AttachVolume,
    DetachVolume, ResizeVolume, DeleteVolume, ListFirewalls, GetServerAction,
    OnNewServer], Field(discriminator="operation")]


class HetznerFullConfig(NodeConfig[HetznerConfig, HetznerAPITokenCredential]):
    pass


# Every entry maps to one operation in https://docs.hetzner.cloud/cloud.spec.json.
ROUTES = {
    "list_servers": ("GET", "/servers"),
    "get_server": ("GET", "/servers/{server_id}"),
    "create_server": ("POST", "/servers"),
    "update_server": ("PUT", "/servers/{server_id}"),
    "delete_server": ("DELETE", "/servers/{server_id}"),
    "poweron_server": ("POST", "/servers/{server_id}/actions/poweron"),
    "shutdown_server": ("POST", "/servers/{server_id}/actions/shutdown"),
    "poweroff_server": ("POST", "/servers/{server_id}/actions/poweroff"),
    "reboot_server": ("POST", "/servers/{server_id}/actions/reboot"),
    "create_server_image": ("POST", "/servers/{server_id}/actions/create_image"),
    "list_images": ("GET", "/images"),
    "get_image": ("GET", "/images/{image_id}"),
    "list_server_types": ("GET", "/server_types"),
    "list_ssh_keys": ("GET", "/ssh_keys"),
    "create_ssh_key": ("POST", "/ssh_keys"),
    "delete_ssh_key": ("DELETE", "/ssh_keys/{ssh_key_id}"),
    "list_volumes": ("GET", "/volumes"),
    "create_volume": ("POST", "/volumes"),
    "attach_volume": ("POST", "/volumes/{volume_id}/actions/attach"),
    "detach_volume": ("POST", "/volumes/{volume_id}/actions/detach"),
    "resize_volume": ("POST", "/volumes/{volume_id}/actions/resize"),
    "delete_volume": ("DELETE", "/volumes/{volume_id}"),
    "list_firewalls": ("GET", "/firewalls"),
    "get_server_action": ("GET", "/servers/{server_id}/actions/{action_id}"),
}


class HetznerNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-hetzner"
    connection_evidence = ConnectionEvidence(operation="list_servers", noun="servers")

    @classmethod
    def get_config_model(cls):
        return HetznerFullConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Hetzner Cloud project API token")
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    params=params, json=body)
        except httpx.HTTPError:
            raise ValueError("Hetzner Cloud request could not be completed; inspect the resource before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = "Request rejected"
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                pass
            message = str(message).replace(credential.api_token, "[redacted]")[:500]
            raise ValueError(f"Hetzner Cloud HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Hetzner Cloud returned an unexpected response")
        return data

    async def _new_servers(self, config):
        servers, page, seen_pages = [], 1, set()
        for _ in range(100):
            params = {"page": page, "per_page": 50, "sort": "created:desc"}
            if config.label_selector is not None:
                params["label_selector"] = config.label_selector
            data = await self._request("GET", "/servers", params=params)
            rows = data["servers"]
            if not isinstance(rows, list):
                raise ValueError("Hetzner Cloud returned an invalid server list")
            servers.extend(rows)
            following = data["meta"]["pagination"]["next_page"]
            if following is None:
                break
            if type(following) is not int or following <= page or following in seen_pages:
                raise ValueError("Hetzner Cloud pagination did not advance")
            seen_pages.add(page)
            page = following
        else:
            raise ValueError("More than 5000 servers in this scope; narrow the label selector")
        # Offset pages can overlap when servers are created during the scan.
        unique = list({row["id"]: row for row in servers}.values())
        fresh = await self._filter_unseen(unique, lambda row: str(row["id"]))
        return {"servers": fresh, "new_server_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_server":
            return bool(output.get("new_server_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if "new_server_count" not in output:
            return super().resolve_agent_event(output)
        servers = output.get("servers", [])
        if not servers:
            return None
        lines = [f"- {row['name']} (server {row['id']}), status {row['status']}, created {row['created']}" for row in servers[:10]]
        return {"text": f"Hetzner Cloud: {len(servers)} new server(s) in your project.\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        if self.config.credentials is None:
            raise ValueError("Connect a Hetzner Cloud project API token")
        if isinstance(config, OnNewServer):
            return await self._new_servers(config)
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in tuple(values):
            marker = "{" + field + "}"
            if marker in path:
                path = path.replace(marker, str(values.pop(field)))
        if isinstance(config, AttachVolume):
            values["assignee"] = {"id": values.pop("server_id"), "type": "server"}
        data = await self._request(method, path, params=values if method == "GET" else None,
            body=values if method in {"POST", "PUT"} else None)
        return {"status": "success", "operation": config.operation, "data": data}
