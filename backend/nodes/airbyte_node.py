"""Airbyte's pinned, RPC-style Configuration API for self-hosted deployments.

Each action sends one documented POST. The scheduled trigger watches the
creation-ordered job list, using the shared poll baseline and deduplication.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

CONTRACT = "https://raw.githubusercontent.com/airbytehq/airbyte/efe60f76503d3a052c9797b9d1a0dbdfce185a25/airbyte-api/src/main/openapi/config.yaml"


class AirbyteBasicCredential(BaseModel):
    model_config = ConfigDict(title="Airbyte Basic Auth", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": CONTRACT,
            "x-credential-instructions": "Enter your self-hosted Airbyte server origin and its Configuration API username and password. Use HTTPS for a remote server. This connects the Configuration API, not the Airbyte Cloud public API. Hosted NoClick can reach public servers; private servers require a self-hosted NoClick deployment with private outbound access configured.",
        })
    credential_type: Literal["airbyte_basic"] = Field("airbyte_basic", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Server URL", description="Server origin, for example https://airbyte.example.com. NoClick adds /api/v1.")
    username: str = Field(..., min_length=1, max_length=256, title="Username")
    password: str = Field(..., min_length=1, max_length=4096, title="Password", json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url", mode="before")
    @classmethod
    def origin(cls, value):
        origin = https_origin(value, field_name="Airbyte server URL")
        if not origin:
            raise ValueError("Enter the Airbyte server URL")
        return origin

    @field_validator("username")
    @classmethod
    def user(cls, value):
        value = value.strip()
        if not value or ":" in value or any(ord(c) < 32 for c in value):
            raise ValueError("Enter the Basic authentication username without a colon or control characters")
        return value

    @field_validator("password", mode="before")
    @classmethod
    def secret(cls, value):
        return clean_secret(value, field_name="Password")


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def _id(title):
    return (UUID, Field(..., title=title))


NAME = (str, Field(..., min_length=1, max_length=1024, title="Name"))
CONFIGURATION = (str, Field(..., title="Connection configuration JSON",
    description="Complete connector-specific configuration matching this connector's specification. Updates replace the complete configuration.",
    json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
WORKSPACE = {"workspace_id": _id("Workspace ID")}
SOURCE = {"source_id": _id("Source ID")}
DESTINATION = {"destination_id": _id("Destination ID")}
CONNECTION = {"connection_id": _id("Connection ID")}
JOB = {"job_id": (int, Field(..., ge=0, title="Job ID"))}
PAGE = {"page_size": (int, Field(100, ge=1, le=1000)), "row_offset": (int, Field(0, ge=0))}

# API usage priority: run and inspect syncs, inspect resources, then provision
# and maintain connectors/connections. Route and payload mapping are explicit.
OPERATIONS = {
    "sync_connection": ("/connections/sync", CONNECTION),
    "get_job": ("/jobs/get", JOB),
    "list_jobs": ("/jobs/list", {**CONNECTION, **PAGE}),
    "cancel_job": ("/jobs/cancel", JOB),
    "list_workspaces": ("/workspaces/list", {}),
    "get_workspace": ("/workspaces/get", WORKSPACE),
    "list_connections": ("/connections/list", WORKSPACE),
    "get_connection": ("/connections/get", CONNECTION),
    "list_sources": ("/sources/list", WORKSPACE),
    "get_source": ("/sources/get", SOURCE),
    "list_destinations": ("/destinations/list", WORKSPACE),
    "get_destination": ("/destinations/get", DESTINATION),
    "check_source": ("/sources/check_connection", SOURCE),
    "check_destination": ("/destinations/check_connection", DESTINATION),
    "discover_source_schema": ("/sources/discover_schema", SOURCE),
    "create_source": ("/sources/create", {**WORKSPACE, "source_definition_id": _id("Source definition ID"), "name": NAME, "connection_configuration_json": CONFIGURATION}),
    "update_source": ("/sources/update", {**SOURCE, "name": NAME, "connection_configuration_json": CONFIGURATION}),
    "delete_source": ("/sources/delete", SOURCE),
    "create_destination": ("/destinations/create", {**WORKSPACE, "destination_definition_id": _id("Destination definition ID"), "name": NAME, "connection_configuration_json": CONFIGURATION}),
    "update_destination": ("/destinations/update", {**DESTINATION, "name": NAME, "connection_configuration_json": CONFIGURATION}),
    "delete_destination": ("/destinations/delete", DESTINATION),
    "create_connection": ("/connections/create", {**SOURCE, **DESTINATION, "name": NAME,
        "connection_status": (Literal["active", "inactive", "deprecated"], Field(..., title="Connection status"))}),
    "update_connection": ("/connections/update", {**CONNECTION, "name": NAME,
        "connection_status": (Literal["active", "inactive", "deprecated"], Field(..., title="Connection status"))}),
    "delete_connection": ("/connections/delete", CONNECTION),
}

MODELS = {}
for _operation, (_path, _fields) in OPERATIONS.items():
    _label = _operation.replace("_", " ").title()
    MODELS[_operation] = create_model("Airbyte" + _label.replace(" ", "") + "Config", __base__=_Action,
        operation=(Literal[_operation], Field(_operation, title=_label, json_schema_extra={"ui:hidden": True, "x-display-name": _label})), **_fields)


class AirbyteOnNewSyncJobConfig(PollTriggerConfigBase):
    operation: Literal["on_new_sync_job"] = Field("on_new_sync_job", title="On New Sync Job",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Sync Job"})
    connection_id: UUID = Field(..., title="Connection ID")
    page_size: int = Field(100, ge=1, le=1000, description="Watch the most recent jobs, descending by creation time. Increase this window if more jobs can be created between polls.")


AirbyteConfig = Annotated[Union[tuple(MODELS.values()) + (AirbyteOnNewSyncJobConfig,)], Field(discriminator="operation")]


class AirbyteNodeConfig(NodeConfig[AirbyteConfig, AirbyteBasicCredential]):
    pass


API_FIELDS = {"workspace_id": "workspaceId", "source_id": "sourceId", "destination_id": "destinationId",
    "connection_id": "connectionId", "source_definition_id": "sourceDefinitionId", "destination_definition_id": "destinationDefinitionId",
    "connection_status": "status", "job_id": "id", "name": "name"}
LIST_KEYS = {"list_workspaces": "workspaces", "list_sources": "sources", "list_destinations": "destinations", "list_connections": "connections", "list_jobs": "jobs"}
SENSITIVE = {"connectionConfiguration", "password", "authToken", "access_token", "refresh_token", "secretId"}


def _public(value):
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if key not in SENSITIVE}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


class _AirbyteHTTPError(Exception):
    def __init__(self, status, message=None):
        self.status = status
        super().__init__(message or f"Airbyte returned HTTP {status}")


class AirbyteNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-airbyte"
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_workspaces", label_keys=("name", "workspaceId"))

    @classmethod
    def get_config_model(cls):
        return AirbyteNodeConfig

    async def _request(self, path, body):
        credential = self.config.credentials
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            try:
                response = await client.post(credential.server_url + "/api/v1" + path,
                    auth=httpx.BasicAuth(credential.username, credential.password),
                    headers={"Accept": "application/json"}, json=body)
            except httpx.HTTPError:
                raise ValueError("Airbyte request could not be confirmed; inspect the server before retrying a write") from None
        if not 200 <= response.status_code < 300:
            # Keep the provider's diagnostic, but not a credential echoed in it.
            message = None
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except ValueError:
                pass
            if message:
                auth_header = response.request.headers.get("authorization", "")
                secrets = [credential.password, auth_header, auth_header.removeprefix("Basic ")]
                def secret_values(value):
                    if isinstance(value, dict):
                        for item in value.values():
                            yield from secret_values(item)
                    elif isinstance(value, list):
                        for item in value:
                            yield from secret_values(item)
                    elif isinstance(value, str) and value:
                        yield value
                secrets.extend(secret_values(body.get("connectionConfiguration", {})))
                for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
                    message = message.replace(secret, "[redacted]")
                message = message[:2000]
            raise _AirbyteHTTPError(response.status_code, message)
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Airbyte returned an unexpected response") from None
        if not isinstance(payload, dict):
            raise ValueError("Airbyte returned an unexpected response shape")
        return payload

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Airbyte Configuration API server")
        config = self.config.config
        action = config.operation
        poll = isinstance(config, AirbyteOnNewSyncJobConfig)
        if action == "list_jobs" or poll:
            path = "/jobs/list"
            body = {"configId": str(config.connection_id), "configTypes": ["sync"],
                "pagination": {"pageSize": config.page_size, "rowOffset": 0 if poll else config.row_offset}}
        else:
            path = OPERATIONS[action][0]
            fields = config.model_dump(mode="json", exclude={"operation"})
            body = {API_FIELDS[key]: value for key, value in fields.items() if key in API_FIELDS}
            if "connection_configuration_json" in fields:
                try:
                    settings = json.loads(fields["connection_configuration_json"])
                except ValueError:
                    raise ValueError("Enter valid connection configuration JSON") from None
                if not isinstance(settings, dict):
                    raise ValueError("Connection configuration must be a JSON object")
                body["connectionConfiguration"] = settings
        try:
            payload = await self._request(path, body)
        except _AirbyteHTTPError as exc:
            result = {"status": "error", "http_status": exc.status, "message": str(exc)}
            await self.emit(result)
            return result
        if poll:
            rows = payload.get("jobs")
            if not isinstance(rows, list):
                raise ValueError("Airbyte job list is missing")
            jobs = []
            for row in rows:
                job = row.get("job") if isinstance(row, dict) else None
                if not isinstance(job, dict) or not all(k in job for k in ("id", "configId", "configType", "createdAt", "status")):
                    raise ValueError("Airbyte job list contains an incomplete job")
                jobs.append(job)
            fresh = await self._filter_unseen(jobs, lambda job: str(job["id"]))
            result = {"status": "success", "jobs": _public(fresh), "new_job_count": len(fresh)}
        else:
            data = _public(payload)
            result = {"status": "success", "data": data}
            if action in LIST_KEYS:
                rows = data.get(LIST_KEYS[action])
                if not isinstance(rows, list):
                    raise ValueError("Airbyte list response is missing its resource array")
                result["items"] = rows
        await self.emit(result)
        return result

    @classmethod
    def resolve_agent_event(cls, output):
        jobs = output.get("jobs") if isinstance(output, dict) else None
        if not isinstance(jobs, list) or not jobs:
            return None
        lines = [f"Airbyte created sync job {job['id']} for connection {job['configId']}; status {job['status']}, created at Unix time {job['createdAt']}." for job in jobs]
        return {"text": "\n".join(lines), "conversation_key": None}
