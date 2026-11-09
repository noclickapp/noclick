"""Smol Machines hosted API, pinned to the provider's 0.1.0 OpenAPI contract.

Each operation makes one request. Lifecycle and job acknowledgements are returned
as received; callers must inspect readiness, job state and exit codes separately.
Writes are never retried because an interrupted exec may already have run.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.smolmachines.com"


class SmolMachinesAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Smol Machines API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://smolmachines.com/console/keys",
            "x-credential-instructions": "Create an API key in the Smol Machines console and paste it here. Enable machine:read for reads, machine:create for lifecycle and resize, machine:exec for commands and jobs, machine:delete for deletion, and group:write for scaling groups. The identity check accepts any valid key and does not prove these operation permissions.",
        },
    )
    credential_type: Literal["smol_machines_api_key"] = Field("smol_machines_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Operation(_Input):
    # Saved canvas metadata (label, disabled, _settings) accompanies operation
    # fields. Only declared fields enter model_dump and the HTTP request.
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Machine(_Operation):
    machine_id: str = Field(..., min_length=1, max_length=256, description="Machine ID returned by Smol Machines.")

    @field_validator("machine_id", mode="before")
    @classmethod
    def identifier(cls, value):
        return _segment(value)


def _segment(value):
    if not isinstance(value, str) or not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
        raise ValueError("Use a single Smol Machines resource ID or name")
    return value


class GetIdentity(_Operation):
    """Get the API key's subject, tenant and granted scopes."""
    operation: Literal["get_identity"] = "get_identity"


class ListMachines(_Operation):
    """List every machine in this tenant, optionally matching all labels."""
    operation: Literal["list_machines"] = "list_machines"
    label: list[str] | None = Field(None, description="Repeated key=value label filters; all must match.")


class GetMachine(_Machine):
    operation: Literal["get_machine"] = "get_machine"


class MachineSource(_Input):
    type: Literal["image", "smolmachine"] = Field(..., description="OCI image or packed .smolmachine artifact.")
    reference: str = Field(..., min_length=1, description="For example alpine for an OCI image.")
    arch: Literal["arm64", "amd64"] | None = None


class MachineResources(_Input):
    cpus: int | None = Field(None, ge=1)
    memoryMb: int | None = Field(None, ge=1, title="Memory (MiB)")
    diskGb: int | None = Field(None, ge=1, title="Disk (GiB)")


class MachineNetwork(_Input):
    mode: Literal["open", "blocked", "allowCidrs"]
    cidrs: list[str] | None = None
    hosts: list[str] | None = None

    @model_validator(mode="after")
    def policy(self):
        if self.mode != "allowCidrs" and (self.cidrs is not None or self.hosts is not None):
            raise ValueError("CIDRs and hosts apply only to allowCidrs mode")
        return self


class CreateMachine(_Operation):
    """Create a machine. Inspect ready before using its guest workload."""
    operation: Literal["create_machine"] = "create_machine"
    source: MachineSource
    name: str | None = None
    resources: MachineResources | None = None
    network: MachineNetwork | None = Field(None, description="Omitted uses the provider's open outbound policy.")
    env: dict[str, str] | None = None
    labels: dict[str, str] | None = None
    command: list[str] | None = None
    workdir: str | None = None
    ephemeral: bool | None = None
    branchable: bool | None = None
    autoStopSeconds: int | None = Field(None, ge=0)
    ttlSeconds: int | None = Field(None, ge=0)

    @field_validator("labels")
    @classmethod
    def label_map(cls, value):
        if value is not None and (len(value) > 32 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9._/-]{0,61}[a-z0-9])?", k) or len(v) > 255 for k, v in value.items())):
            raise ValueError("Use at most 32 labels with documented lowercase keys and values up to 255 characters")
        return value


class DeleteMachine(_Machine):
    """Delete this machine and its ephemeral state."""
    operation: Literal["delete_machine"] = "delete_machine"


class StartMachine(_Machine):
    operation: Literal["start_machine"] = "start_machine"


class StopMachine(_Machine):
    operation: Literal["stop_machine"] = "stop_machine"


class PauseMachine(_Machine):
    """Save memory and disk durably and pause the machine."""
    operation: Literal["pause_machine"] = "pause_machine"


class ResumeMachine(_Machine):
    operation: Literal["resume_machine"] = "resume_machine"


class ResizeMachine(_Machine):
    """Resize a running machine. RAM and disk only grow."""
    operation: Literal["resize_machine"] = "resize_machine"
    cpus: int | None = Field(None, ge=1)
    memoryMb: int | None = Field(None, ge=1)
    diskGb: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def changes(self):
        if all(v is None for v in (self.cpus, self.memoryMb, self.diskGb)):
            raise ValueError("Provide at least one resource size")
        return self


class _Command(_Machine):
    command: str | list[str] = Field(..., description="Shell command string, or an argv array.")
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeoutSeconds: int | None = Field(None, ge=0)
    user: str | None = None


class ExecuteCommand(_Command):
    """Run a buffered command; a nonzero exitCode is preserved in data."""
    operation: Literal["execute_command"] = "execute_command"
    stdin: str | None = None
    background: bool | None = None


class ExecuteCode(_Machine):
    """Run a code snippet using the guest's matching interpreter."""
    operation: Literal["execute_code"] = "execute_code"
    language: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "code_editor"})
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeoutSeconds: int | None = Field(None, ge=0)
    user: str | None = None


class ListMachineEvents(_Machine):
    operation: Literal["list_machine_events"] = "list_machine_events"


class GetMachineUsage(_Machine):
    operation: Literal["get_machine_usage"] = "get_machine_usage"


class ListJobs(_Machine):
    operation: Literal["list_jobs"] = "list_jobs"


class CreateJob(_Command):
    """Start a detached command and return its job; poll for completion."""
    operation: Literal["create_job"] = "create_job"


class _Job(_Machine):
    job_id: str = Field(..., min_length=1, max_length=256)

    @field_validator("job_id", mode="before")
    @classmethod
    def job(cls, value):
        return _segment(value)


class GetJob(_Job):
    operation: Literal["get_job"] = "get_job"


class CancelJob(_Job):
    operation: Literal["cancel_job"] = "cancel_job"


class GetJobOutput(_Job):
    """Read an output slice. Continue at nextOffset until eof."""
    operation: Literal["get_job_output"] = "get_job_output"
    stream: Literal["stdout", "stderr"] = "stdout"
    offset: int = Field(0, ge=0)
    limit: int = Field(262144, ge=1, le=1048576)


class ListGroups(_Operation):
    operation: Literal["list_groups"] = "list_groups"


class _Group(_Operation):
    group_name: str = Field(..., min_length=1, max_length=256)

    @field_validator("group_name", mode="before")
    @classmethod
    def group(cls, value):
        return _segment(value)


class GetGroup(_Group):
    operation: Literal["get_group"] = "get_group"


class ScaleGroup(_Group):
    """Scale a deployment group to the requested instance count."""
    operation: Literal["scale_group"] = "scale_group"
    count: int = Field(..., ge=0)


SmolMachinesConfig = Annotated[Union[
    GetIdentity, ListMachines, GetMachine, CreateMachine, DeleteMachine,
    StartMachine, StopMachine, PauseMachine, ResumeMachine, ResizeMachine,
    ExecuteCommand, ExecuteCode, ListMachineEvents, GetMachineUsage,
    ListJobs, CreateJob, GetJob, CancelJob, GetJobOutput,
    ListGroups, GetGroup, ScaleGroup,
], Field(discriminator="operation")]


class SmolMachinesNodeConfig(NodeConfig[SmolMachinesConfig, SmolMachinesAPIKeyCredential]):
    pass


# One entry corresponds to exactly one operation in the published contract.
ROUTES = {
    "get_identity": ("GET", "/v1/me"),
    "list_machines": ("GET", "/v1/machines"),
    "create_machine": ("POST", "/v1/machines"),
    "get_machine": ("GET", "/v1/machines/{machine_id}"),
    "delete_machine": ("DELETE", "/v1/machines/{machine_id}"),
    "start_machine": ("POST", "/v1/machines/{machine_id}/start"),
    "stop_machine": ("POST", "/v1/machines/{machine_id}/stop"),
    "pause_machine": ("POST", "/v1/machines/{machine_id}/pause"),
    "resume_machine": ("POST", "/v1/machines/{machine_id}/resume"),
    "resize_machine": ("POST", "/v1/machines/{machine_id}/resize"),
    "execute_command": ("POST", "/v1/machines/{machine_id}/exec"),
    "execute_code": ("POST", "/v1/machines/{machine_id}/code"),
    "list_machine_events": ("GET", "/v1/machines/{machine_id}/events"),
    "get_machine_usage": ("GET", "/v1/machines/{machine_id}/usage"),
    "list_jobs": ("GET", "/v1/machines/{machine_id}/jobs"),
    "create_job": ("POST", "/v1/machines/{machine_id}/jobs"),
    "get_job": ("GET", "/v1/machines/{machine_id}/jobs/{job_id}"),
    "cancel_job": ("POST", "/v1/machines/{machine_id}/jobs/{job_id}/cancel"),
    "get_job_output": ("GET", "/v1/machines/{machine_id}/jobs/{job_id}/output"),
    "list_groups": ("GET", "/v1/groups"),
    "get_group": ("GET", "/v1/groups/{group_name}"),
    "scale_group": ("POST", "/v1/groups/{group_name}/scale"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class SmolMachinesNode(WorkflowNode):
    integration_type = "automation-smol-machines"
    connection_evidence = ConnectionEvidence(
        noun="account", identity_operation="get_identity",
        identity_keys=("tenantName", "tenantId", "subject"),
    )

    @classmethod
    def get_config_model(cls):
        return SmolMachinesNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Smol Machines API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, route = ROUTES[op.operation]
        fields = op.model_dump(exclude_none=True)
        path = route.format(**{k: quote(fields[k], safe="") for k in ("machine_id", "job_id", "group_name") if k in fields})
        values = {k: v for k, v in fields.items() if k not in {"operation", "machine_id", "job_id", "group_name"}}
        params = values if method == "GET" else None
        body = values if method == "POST" and values else None
        async with guarded_async_client(timeout=300.0, follow_redirects=False) as client:
            response = await client.request(
                method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}),
            )
        if not 200 <= response.status_code < 300:
            # Preserve provider problem details and status for the connect seam.
            detail = _redact(response.text[:4096], token)
            raise ValueError(f"Smol Machines HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Smol Machines returned invalid JSON") from None
            expects_list = op.operation in {"list_machines", "list_machine_events", "list_groups"}
            if not isinstance(data, list if expects_list else dict):
                raise ValueError("Smol Machines returned an unexpected response shape")
            if op.operation == "list_jobs" and not isinstance(data.get("jobs"), list):
                raise ValueError("Smol Machines returned an invalid jobs envelope")
            if op.operation == "get_identity" and (not isinstance(data.get("subject"), str) or not data["subject"] or not isinstance(data.get("scopes"), list)):
                raise ValueError("Smol Machines returned an invalid identity")
        output = _redact({"data": data, "http_status": response.status_code}, token)
        await self.emit(output)
        return output
