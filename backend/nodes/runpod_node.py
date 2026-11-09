"""Runpod REST v1 resource automation (published OpenAPI 0.1.0).

Each operation makes one request. Lifecycle acknowledgements do not claim that
an asynchronous transition has finished. Writes are never automatically retried.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://rest.runpod.io/v1"


class RunpodAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Runpod API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.runpod.io/user/settings",
            "x-credential-instructions": "Paste a Runpod API key from the console Credentials page. Give it read access to Pods for connection verification and read/write access to the resources your workflow uses. NoClick sends it only to rest.runpod.io as a bearer token.",
        })
    credential_type: Literal["runpod_api_key"] = Field("runpod_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _PodID(_Input):
    pod_id: str = Field(..., title="Pod ID", min_length=1, max_length=191, pattern=r"^[A-Za-z0-9_-]+$")


class _EndpointID(_Input):
    endpoint_id: str = Field(..., title="Endpoint ID", min_length=1, max_length=191, pattern=r"^[A-Za-z0-9_-]+$")


class _TemplateID(_Input):
    template_id: str = Field(..., title="Template ID", min_length=1, max_length=191, pattern=r"^[A-Za-z0-9_-]+$")


class _VolumeID(_Input):
    network_volume_id: str = Field(..., title="Network Volume ID", min_length=1, max_length=191, pattern=r"^[A-Za-z0-9_-]+$")


class _PodFields(_Input):
    name: str | None = Field(None, max_length=191, title="Name")
    image_name: str | None = Field(None, title="Container Image", min_length=1)
    container_disk_in_gb: int | None = Field(None, ge=0, strict=True, title="Container Disk (GB)")
    volume_in_gb: int | None = Field(None, ge=0, strict=True, title="Volume (GB)")
    volume_mount_path: str | None = Field(None, title="Volume Mount Path")
    docker_entrypoint: list[str] | None = Field(None, title="Docker Entrypoint")
    docker_start_cmd: list[str] | None = Field(None, title="Docker Start Command")
    env: dict[str, str] | None = Field(None, title="Environment Variables")
    ports: list[str] | None = Field(None, title="Exposed Ports", description="Runpod port strings, for example 8888/http and 22/tcp.")
    locked: bool | None = Field(None, strict=True, title="Locked")


class _EndpointFields(_Input):
    name: str | None = Field(None, max_length=191, title="Name")
    template_id: str | None = Field(None, title="Template ID", min_length=1)
    gpu_type_ids: list[str] | None = Field(None, title="GPU Types", min_length=1)
    gpu_count: int | None = Field(None, ge=1, strict=True, title="GPU Count")
    workers_min: int | None = Field(None, ge=0, strict=True, title="Minimum Workers")
    workers_max: int | None = Field(None, ge=0, strict=True, title="Maximum Workers")
    idle_timeout: int | None = Field(None, ge=1, le=3600, strict=True, title="Idle Timeout (seconds)")
    execution_timeout_ms: int | None = Field(None, strict=True, title="Execution Timeout (ms)")
    scaler_type: Literal["QUEUE_DELAY", "REQUEST_COUNT"] | None = Field(None, title="Scaler Type")
    scaler_value: int | None = Field(None, ge=1, strict=True, title="Scaler Value")
    flashboot: bool | None = Field(None, strict=True, title="Flashboot")
    network_volume_id: str | None = Field(None, title="Network Volume ID", min_length=1)

    @model_validator(mode="after")
    def worker_order(self):
        if self.workers_min is not None and self.workers_max is not None and self.workers_min > self.workers_max:
            raise ValueError("Minimum workers cannot exceed maximum workers")
        return self


class _TemplateFields(_Input):
    name: str | None = Field(None, title="Name", min_length=1)
    image_name: str | None = Field(None, title="Container Image", min_length=1)
    container_disk_in_gb: int | None = Field(None, ge=0, strict=True, title="Container Disk (GB)")
    volume_in_gb: int | None = Field(None, ge=0, strict=True, title="Volume (GB)")
    volume_mount_path: str | None = Field(None, title="Volume Mount Path")
    docker_entrypoint: list[str] | None = Field(None, title="Docker Entrypoint")
    docker_start_cmd: list[str] | None = Field(None, title="Docker Start Command")
    env: dict[str, str] | None = Field(None, title="Environment Variables")
    ports: list[str] | None = Field(None, title="Exposed Ports")
    readme: str | None = Field(None, title="Readme")
    is_public: bool | None = Field(None, strict=True, title="Public Template", description="True makes the template public.")


class _VolumeFields(_Input):
    name: str | None = Field(None, title="Name", min_length=1)
    size: int | None = Field(None, ge=0, le=4000, strict=True, title="Size (GB)")


class ListPods(_Input):
    operation: Literal["list_pods"] = Field("list_pods", title="List Pods", json_schema_extra={"ui:hidden": True})
    compute_type: Literal["GPU", "CPU"] | None = Field(None, title="Compute Type")
    desired_status: Literal["RUNNING", "EXITED", "TERMINATED"] | None = Field(None, title="Desired Status")
    name: str | None = Field(None, max_length=191, title="Name")
    include_workers: bool | None = Field(None, strict=True, title="Include Serverless Workers")


class GetPod(_PodID):
    operation: Literal["get_pod"] = Field("get_pod", title="Get Pod", json_schema_extra={"ui:hidden": True})


class CreatePod(_PodFields):
    operation: Literal["create_pod"] = Field("create_pod", title="Create Pod", json_schema_extra={"ui:hidden": True})
    image_name: str = Field(..., title="Container Image", min_length=1)
    compute_type: Literal["GPU", "CPU"] = Field("GPU", title="Compute Type")
    gpu_type_ids: list[str] | None = Field(None, min_length=1, title="GPU Types")
    cpu_flavor_ids: list[str] | None = Field(None, min_length=1, title="CPU Flavors")
    gpu_count: int | None = Field(None, ge=1, strict=True, title="GPU Count")
    vcpu_count: int | None = Field(None, ge=1, strict=True, title="vCPU Count")
    cloud_type: Literal["SECURE", "COMMUNITY"] = Field("SECURE", title="Cloud Type")
    data_center_ids: list[str] | None = Field(None, min_length=1, title="Data Centers")
    network_volume_id: str | None = Field(None, title="Network Volume ID")

    @model_validator(mode="after")
    def hardware(self):
        if self.compute_type == "GPU" and not self.gpu_type_ids:
            raise ValueError("Choose at least one GPU type")
        if self.compute_type == "CPU" and not self.cpu_flavor_ids:
            raise ValueError("Choose at least one CPU flavor")
        return self


class UpdatePod(_PodFields, _PodID):
    operation: Literal["update_pod"] = Field("update_pod", title="Update Pod", json_schema_extra={"ui:hidden": True})


class DeletePod(_PodID):
    operation: Literal["delete_pod"] = Field("delete_pod", title="Delete Pod", json_schema_extra={"ui:hidden": True})


class StartPod(_PodID):
    operation: Literal["start_pod"] = Field("start_pod", title="Start Pod", json_schema_extra={"ui:hidden": True})


class StopPod(_PodID):
    operation: Literal["stop_pod"] = Field("stop_pod", title="Stop Pod", json_schema_extra={"ui:hidden": True})


class ResetPod(_PodID):
    operation: Literal["reset_pod"] = Field("reset_pod", title="Reset Pod", json_schema_extra={"ui:hidden": True})


class ListEndpoints(_Input):
    operation: Literal["list_endpoints"] = Field("list_endpoints", title="List Endpoints", json_schema_extra={"ui:hidden": True})


class GetEndpoint(_EndpointID):
    operation: Literal["get_endpoint"] = Field("get_endpoint", title="Get Endpoint", json_schema_extra={"ui:hidden": True})


class CreateEndpoint(_EndpointFields):
    operation: Literal["create_endpoint"] = Field("create_endpoint", title="Create Endpoint", json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., title="Template ID", min_length=1)


class UpdateEndpoint(_EndpointFields, _EndpointID):
    operation: Literal["update_endpoint"] = Field("update_endpoint", title="Update Endpoint", json_schema_extra={"ui:hidden": True})


class DeleteEndpoint(_EndpointID):
    operation: Literal["delete_endpoint"] = Field("delete_endpoint", title="Delete Endpoint", json_schema_extra={"ui:hidden": True})


class ListTemplates(_Input):
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", json_schema_extra={"ui:hidden": True})


class GetTemplate(_TemplateID):
    operation: Literal["get_template"] = Field("get_template", title="Get Template", json_schema_extra={"ui:hidden": True})


class CreateTemplate(_TemplateFields):
    operation: Literal["create_template"] = Field("create_template", title="Create Template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title="Name", min_length=1)
    image_name: str = Field(..., title="Container Image", min_length=1)
    is_serverless: bool = Field(False, strict=True, title="Serverless Template")


class UpdateTemplate(_TemplateFields, _TemplateID):
    operation: Literal["update_template"] = Field("update_template", title="Update Template", json_schema_extra={"ui:hidden": True})


class DeleteTemplate(_TemplateID):
    operation: Literal["delete_template"] = Field("delete_template", title="Delete Template", json_schema_extra={"ui:hidden": True})


class ListNetworkVolumes(_Input):
    operation: Literal["list_network_volumes"] = Field("list_network_volumes", title="List Network Volumes", json_schema_extra={"ui:hidden": True})


class GetNetworkVolume(_VolumeID):
    operation: Literal["get_network_volume"] = Field("get_network_volume", title="Get Network Volume", json_schema_extra={"ui:hidden": True})


class CreateNetworkVolume(_VolumeFields):
    operation: Literal["create_network_volume"] = Field("create_network_volume", title="Create Network Volume", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title="Name", min_length=1)
    size: int = Field(..., ge=0, le=4000, strict=True, title="Size (GB)")
    data_center_id: str = Field(..., title="Data Center ID", min_length=1)


class UpdateNetworkVolume(_VolumeFields, _VolumeID):
    operation: Literal["update_network_volume"] = Field("update_network_volume", title="Update Network Volume", json_schema_extra={"ui:hidden": True})


class DeleteNetworkVolume(_VolumeID):
    operation: Literal["delete_network_volume"] = Field("delete_network_volume", title="Delete Network Volume", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListPods, GetPod, CreatePod, UpdatePod, DeletePod, StartPod, StopPod, ResetPod, ListEndpoints, GetEndpoint, CreateEndpoint, UpdateEndpoint, DeleteEndpoint, ListTemplates, GetTemplate, CreateTemplate, UpdateTemplate, DeleteTemplate, ListNetworkVolumes, GetNetworkVolume, CreateNetworkVolume, UpdateNetworkVolume, DeleteNetworkVolume], Field(discriminator="operation")]


class RunpodNodeConfig(NodeConfig[Operation, RunpodAPIKeyCredential]):
    pass


# method, contract path, output shape, successful HTTP status
ROUTES = {'list_pods': ('GET', '/pods', 'items', 200),
 'get_pod': ('GET', '/pods/{pod_id}', 'item', 200),
 'create_pod': ('POST', '/pods', 'item', 201),
 'update_pod': ('PATCH', '/pods/{pod_id}', 'item', 200),
 'delete_pod': ('DELETE', '/pods/{pod_id}', 'ack', 204),
 'start_pod': ('POST', '/pods/{pod_id}/start', 'ack', 200),
 'stop_pod': ('POST', '/pods/{pod_id}/stop', 'ack', 200),
 'reset_pod': ('POST', '/pods/{pod_id}/reset', 'ack', 200),
 'list_endpoints': ('GET', '/endpoints', 'items', 200),
 'get_endpoint': ('GET', '/endpoints/{endpoint_id}', 'item', 200),
 'create_endpoint': ('POST', '/endpoints', 'item', 200),
 'update_endpoint': ('PATCH', '/endpoints/{endpoint_id}', 'item', 200),
 'delete_endpoint': ('DELETE', '/endpoints/{endpoint_id}', 'ack', 204),
 'list_templates': ('GET', '/templates', 'items', 200),
 'get_template': ('GET', '/templates/{template_id}', 'item', 200),
 'create_template': ('POST', '/templates', 'item', 200),
 'update_template': ('PATCH', '/templates/{template_id}', 'item', 200),
 'delete_template': ('DELETE', '/templates/{template_id}', 'ack', 204),
 'list_network_volumes': ('GET', '/networkvolumes', 'items', 200),
 'get_network_volume': ('GET', '/networkvolumes/{network_volume_id}', 'item', 200),
 'create_network_volume': ('POST', '/networkvolumes', 'item', 200),
 'update_network_volume': ('PATCH', '/networkvolumes/{network_volume_id}', 'item', 200),
 'delete_network_volume': ('DELETE', '/networkvolumes/{network_volume_id}', 'ack', 204)}


def _wire_name(name):
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value.replace(token, "[redacted]") if isinstance(value, str) else value


class RunpodNode(WorkflowNode):
    integration_type = "automation-runpod"
    connection_evidence = ConnectionEvidence(operation="list_pods", noun="Pods", label_keys=("name", "id"))
    edit_examples = ["Start my GPU Pod", "Scale a Serverless endpoint", "Create a network volume"]

    @classmethod
    def get_config_model(cls):
        return RunpodNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        data = config_data.get("credentials")
        if isinstance(data, dict) and data.get("credential_type", "runpod_api_key") != "runpod_api_key":
            raise ValueError("Connect a Runpod API key")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Runpod API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, template, kind, expected = ROUTES[op.operation]
        fields = op.model_dump(exclude_none=True, exclude={"operation"})
        path_fields = set(re.findall(r"{([^}]+)}", template))
        path = template.format(**{key: fields.pop(key) for key in path_fields})
        payload = {_wire_name(key): value for key, value in fields.items()}
        if method == "PATCH" and not payload:
            raise ValueError("Provide at least one field to update")
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if method == "GET":
            kwargs = {"params": {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in payload.items()
            }}
        elif kind != "ack":
            kwargs = {"json": payload}
        else:
            kwargs = {}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
            if response.status_code != expected:
                message = "Runpod request was rejected" if response.status_code < 500 else "Runpod service error"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("error", error.get("message")), str):
                        message = error.get("error", error.get("message"))[:2000]
                except ValueError:
                    pass
                result = {"status": "error", "http_status": response.status_code, "message": message}
            elif kind == "ack":
                result = {"status": "success", "accepted": True, "operation": op.operation}
            else:
                body = response.json()
                if kind == "items":
                    if not isinstance(body, list) or any(not isinstance(row, dict) for row in body):
                        raise ValueError("Expected a Runpod resource list")
                elif not isinstance(body, dict) or "error" in body:
                    raise ValueError("Expected a Runpod resource")
                result = {"status": "success", kind: body}
        except (httpx.HTTPError, OSError):
            result = {"status": "error", "message": "Runpod request did not complete; inspect the resource before retrying a write"}
        except ValueError:
            result = {"status": "error", "message": "Runpod returned an unexpected response"}
        result = _redact(result, token)
        await self.emit(result)
        return result
