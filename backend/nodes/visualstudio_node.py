"""VSOnline v1 environment automation: https://online.visualstudio.com/api/v1/swagger.

The environment list supports name, planId and deleted filters only; no
provider webhook registration or created/updated-time query is documented.
"""
from __future__ import annotations
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

BASE = "https://online.visualstudio.com"


class VisualstudioTokenCredential(BaseModel):
    model_config = ConfigDict(title="VSOnline Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": BASE + "/api/v1/swagger",
        "x-credential-instructions": "Paste an existing VSOnline user JWT access token, without the Bearer prefix. The published API accepts bearer tokens; this connection does not create or refresh them. NoClick sends it only to online.visualstudio.com. Use a token authorized for the environments you want to manage.",
    })
    credential_type: Literal["visualstudio_token"] = Field("visualstudio_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=16384, title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
            raise ValueError("Paste the access token without the Bearer prefix or whitespace")
        return value


class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def update_has_changes(self):
        if self.operation == "update_environment" and not any(getattr(self, f) is not None for f in ("friendly_name", "sku_name", "auto_shutdown_delay_minutes", "plan_id")):
            raise ValueError("Set at least one environment change")
        return self


# Exactly one published operation per entry; no GenevaActions/admin APIs.
OPERATIONS = {
    "list_environments": ("GET", "/api/v1/Environments", ("name", "plan_id", "deleted"), ()),
    "get_environment": ("GET", "/api/v1/Environments/{environment_id}", ("deleted",), ()),
    "create_environment": ("POST", "/api/v1/Environments", (), ("environment_type", "friendly_name", "container_image", "sku_name", "plan_id", "auto_shutdown_delay_minutes", "dev_container_path", "working_directory")),
    "update_environment": ("PATCH", "/api/v1/Environments/{environment_id}", (), ("friendly_name", "sku_name", "plan_id", "auto_shutdown_delay_minutes")),
    "delete_environment": ("DELETE", "/api/v1/Environments/{environment_id}", (), ()),
    "start_environment": ("POST", "/api/v1/Environments/{environment_id}/start", (), ()),
    "shutdown_environment": ("POST", "/api/v1/Environments/{environment_id}/shutdown", (), ()),
    "archive_environment": ("POST", "/api/v1/Environments/{environment_id}/archive", (), ()),
    "get_environment_archive": ("GET", "/api/v1/Environments/{environment_id}/archive", (), ()),
    "export_environment": ("POST", "/api/v1/Environments/{environment_id}/export", (), ()),
    "restore_environment": ("PATCH", "/api/v1/Environments/{environment_id}/restore", (), ()),
    "update_recent_folders": ("PATCH", "/api/v1/Environments/{environment_id}/folder", (), ("recent_folder_paths",)),
    "get_environment_state": ("GET", "/api/v1/Environments/{environment_id}/state", (), ()),
    "get_billing": ("GET", "/api/v1/Billing", (), ()),
    "list_locations": ("GET", "/api/v1/Locations", (), ()),
    "get_location": ("GET", "/api/v1/Locations/{location}", ("plan_id",), ()),
    "get_agent": ("GET", "/api/v1/Agents/{family}", (), ()),
    "get_port_info": ("GET", "/api/v1/Tunnel/{environment_id}/portInfo", ("port_number",), ()),
}
WIRE_NAMES = {"plan_id": "planId", "environment_type": "type", "friendly_name": "friendlyName", "container_image": "containerImage", "sku_name": "skuName", "auto_shutdown_delay_minutes": "autoShutdownDelayMinutes", "dev_container_path": "devContainerPath", "working_directory": "workingDirectory", "recent_folder_paths": "recentFolderPaths", "port_number": "portNumber"}
FIELDS = {
    "environment_id": (UUID, Field(..., title="Environment ID")),
    "name": (Optional[str], Field(None, title="Environment Name Filter")),
    "plan_id": (Optional[str], Field(None, title="Plan ID")),
    "deleted": (bool, Field(False, title="Include Deleted Environments")),
    "environment_type": (str, Field(..., min_length=1, title="Environment Type", description="Provider environment type.")),
    "friendly_name": (str, Field(..., min_length=1, title="Environment Name")),
    "container_image": (Optional[str], Field(None, title="Container Image")),
    "sku_name": (Optional[str], Field(None, title="SKU Name")),
    "auto_shutdown_delay_minutes": (Optional[int], Field(None, ge=0, le=2147483647, title="Auto Shutdown Delay (Minutes)")),
    "dev_container_path": (Optional[str], Field(None, title="Dev Container Path")),
    "working_directory": (Optional[str], Field(None, title="Working Directory")),
    "recent_folder_paths": (list[str], Field(..., title="Recent Folder Paths", description="Replaces the list; an empty list clears it.")),
    "location": (str, Field(..., min_length=1, title="Location")),
    "family": (str, Field(..., min_length=1, title="Agent Family")),
    "port_number": (Optional[int], Field(None, ge=1, le=65535, title="Port Number")),
}


def _config(name, spec):
    method, path, query, body = spec
    fields = {key: definition for key, definition in FIELDS.items() if key in query or key in body or "{" + key + "}" in path}
    if name == "update_environment":
        fields["friendly_name"] = (Optional[str], Field(None, min_length=1, title="Environment Name"))
    fields["operation"] = (Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": name.replace("_", " ").title(), "x-method-kind": "read" if method == "GET" else "write"}))
    return create_model("Visualstudio" + "".join(x.title() for x in name.split("_")) + "Config", __base__=OperationConfig, **fields)


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items() if not name.startswith("on_")}


VisualstudioConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class VisualstudioNodeConfig(NodeConfig[VisualstudioConfig, VisualstudioTokenCredential]):
    model_config = ConfigDict(title="VSOnline Node Configuration")


class VisualstudioNode(WorkflowNode):
    integration_type = "automation-visualstudio"
    connection_evidence = ConnectionEvidence(operation="list_environments", noun="environments", label_keys=("friendlyName", "id"))
    edit_examples = ["Start my development environment", "Create a VSOnline environment", "Shut down an idle environment"]

    @classmethod
    def get_config_model(cls):
        return VisualstudioNodeConfig

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a VSOnline access token")
        method, path, query_fields, body_fields = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {WIRE_NAMES.get(k, k): values[k] for k in query_fields if k in values}
        body = {WIRE_NAMES.get(k, k): values[k] for k in body_fields if k in values} if body_fields else None
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body, headers={"Authorization": f"Bearer {credential.access_token}", "Accept": "application/json"})
        if response.status_code >= 300:
            message = response.text.replace(credential.access_token, "[redacted]")[:2000]
            raise ValueError(f"VSOnline API error {response.status_code}: {message}")
        data = response.json() if response.content else None
        return {"data": data, "http_status": response.status_code}
