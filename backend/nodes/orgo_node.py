"""Orgo API 1.0.0: one published endpoint per workflow operation.

Contract: https://www.orgo.ai/openapi.json
Lifecycle actions return the provider's response, including asynchronous operation
IDs. Poll with get_computer_operation; mutations are never retried automatically.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://www.orgo.ai"


class OrgoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Orgo API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.orgo.ai/dashboard",
        "x-credential-instructions": "In the Orgo dashboard, create an API key and paste its value without the Bearer prefix. Use an account-wide key with permissions for your workflow. NoClick sends it only to www.orgo.ai. Connecting reads the current account; computer creation and running computers can spend your Orgo credit.",
    })
    credential_type: Literal["orgo_api_key"] = Field("orgo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Computer(_Input):
    computer_id: str = Field(..., min_length=1, description="Computer ID from List Workspaces (desktops) or Create Computer.")

    @field_validator("computer_id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#%") or any(ord(c) < 33 for c in value):
            raise ValueError("Use a single Orgo computer identifier")
        return value


class _Screen(_Computer):
    screen: str | None = Field(None, description="Optional screen selector for computers with multiple displays.")


class _End(_Computer):
    ends_in_hours: int | None = Field(None, ge=1, le=720, description="Delete the computer and everything on it after this many hours. Omit to preserve its end.")
    keep_forever: StrictBool = Field(False, description="Explicitly clear the end by sending ends_at null.")

    @model_validator(mode="after")
    def end_choice(self):
        if self.keep_forever and self.ends_in_hours is not None:
            raise ValueError("Choose ends_in_hours or keep_forever, never both")
        return self


class OrgoGetMeConfig(_Input):
    """Get the current authenticated account."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class OrgoGetAccountCapacityConfig(_Input):
    """Read account compute capacity."""
    operation: Literal["get_account_capacity"] = Field("get_account_capacity", json_schema_extra={"ui:hidden": True})


class OrgoGetAccountLimitsConfig(_Input):
    """Read account workspace and rate limits."""
    operation: Literal["get_account_limits"] = Field("get_account_limits", json_schema_extra={"ui:hidden": True})


class OrgoListWorkspacesConfig(_Input):
    """List workspaces and their computers; Orgo may create a default workspace on the first call."""
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})


class OrgoCreateComputerConfig(_Input):
    """Provision a cloud computer; this can spend Orgo credit."""
    operation: Literal["create_computer"] = Field("create_computer", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=80)
    os: Literal["linux", "windows", "macos", "android", "ios"] | None = None
    ram: Literal[4, 8, 10, 16, 32, 64] | None = Field(None, description="RAM in GB; omit to use the provider or template default.")
    cpu: Literal[0.5, 1, 2, 4, 6, 8, 16] | None = None
    disk_size_gb: int | None = Field(None, ge=1)
    resolution: str | None = Field(None, description="WIDTHxHEIGHTxDEPTH, for example 1280x720x24.")
    ends_in_hours: int | None = Field(None, ge=1, le=720, description="Delete the computer and its contents when the time is up. Omit to keep it.")
    billing_mode: Literal["hourly", "plan", "monthly"] | None = Field(None, description="Omitted: provider selects billing; hourly launches spend account credit.")
    compute_request_id: UUID | None = Field(None, description="Reuse this launch ID when manually retrying to avoid provisioning twice.")
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[ -~]+$", description="Optional Idempotency-Key header for this launch.")
    template_ref: str | None = Field(None, description="Template reference namespace/name@version.")


class OrgoGetComputerConfig(_Computer):
    """Get computer state and connection details."""
    operation: Literal["get_computer"] = Field("get_computer", json_schema_extra={"ui:hidden": True})


class OrgoUpdateComputerConfig(_End):
    """Rename a computer or change when it is deleted."""
    operation: Literal["update_computer"] = Field("update_computer", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=80)


class OrgoDeleteComputerConfig(_Computer):
    """Delete a computer and everything on it."""
    operation: Literal["delete_computer"] = Field("delete_computer", json_schema_extra={"ui:hidden": True})


class OrgoStartComputerConfig(_End):
    """Start a computer; poll an asynchronous operation separately."""
    operation: Literal["start_computer"] = Field("start_computer", json_schema_extra={"ui:hidden": True})
    run_async: StrictBool = Field(True, description="Return immediately with an operation ID to poll.")
    billing_mode: Literal["hourly"] | None = Field(None, description="Explicitly move an eligible older Free computer to hourly billing.")


class OrgoStopComputerConfig(_Computer):
    """Stop a computer while keeping its disk."""
    operation: Literal["stop_computer"] = Field("stop_computer", json_schema_extra={"ui:hidden": True})
    run_async: StrictBool = Field(True, description="Return immediately with an operation ID to poll.")


class OrgoRestartComputerConfig(_Computer):
    """Restart a computer."""
    operation: Literal["restart_computer"] = Field("restart_computer", json_schema_extra={"ui:hidden": True})
    clear_disk: StrictBool = Field(False, description="GPU computers only: clear the disk and restart; Orgo saves a copy of /root first.")


class OrgoSuspendComputerConfig(_Computer):
    """Pause a computer with its memory saved."""
    operation: Literal["suspend_computer"] = Field("suspend_computer", json_schema_extra={"ui:hidden": True})


class OrgoResumeComputerConfig(_End):
    """Resume a paused computer."""
    operation: Literal["resume_computer"] = Field("resume_computer", json_schema_extra={"ui:hidden": True})


class OrgoGetComputerOperationConfig(_Computer):
    """Poll one computer lifecycle operation."""
    operation: Literal["get_computer_operation"] = Field("get_computer_operation", json_schema_extra={"ui:hidden": True})
    operation_id: UUID = Field(..., description="Operation ID returned by an asynchronous lifecycle action.")


class OrgoRunBashConfig(_Screen):
    """Run a shell command on a computer."""
    operation: Literal["run_bash"] = Field("run_bash", json_schema_extra={"ui:hidden": True})
    command: str = Field(..., min_length=1)
    timeout: int | None = Field(None, ge=1, le=300, description="Command timeout in seconds.")


class OrgoClickConfig(_Screen):
    """Click a screen coordinate."""
    operation: Literal["click"] = Field("click", json_schema_extra={"ui:hidden": True})
    x: int
    y: int
    button: Literal["left", "right"] | None = None
    double: StrictBool | None = None


class OrgoTypeTextConfig(_Screen):
    """Type text into the focused application."""
    operation: Literal["type_text"] = Field("type_text", json_schema_extra={"ui:hidden": True})
    text: str


class OrgoPressKeyConfig(_Screen):
    """Press a key or keyboard shortcut."""
    operation: Literal["press_key"] = Field("press_key", json_schema_extra={"ui:hidden": True})
    key: str = Field(..., min_length=1, description="Key or shortcut, for example ctrl+c.")


class OrgoListPublicUrlsConfig(_Computer):
    """List the public URLs on a computer."""
    operation: Literal["list_public_urls"] = Field("list_public_urls", json_schema_extra={"ui:hidden": True})


class OrgoCreatePublicUrlConfig(_Computer):
    """Expose a computer port through a public URL."""
    operation: Literal["create_public_url"] = Field("create_public_url", json_schema_extra={"ui:hidden": True})
    port: int = Field(..., ge=1, le=65535)
    name: str | None = Field(None, min_length=2, max_length=16, description="Name prefix; Orgo adds four characters.")


class OrgoUpdatePublicUrlConfig(_Computer):
    """Change a public URL port or password."""
    operation: Literal["update_public_url"] = Field("update_public_url", json_schema_extra={"ui:hidden": True})
    url_id: UUID
    port: int | None = Field(None, ge=1, le=65535)
    password: str | None = Field(None, min_length=4, max_length=64, pattern=r"^[!-~]([ -~]*[!-~])?$", json_schema_extra={"ui:widget": "password"})
    remove_password: StrictBool = Field(False, description="Make the URL open by sending password null.")


class OrgoDeletePublicUrlConfig(_Computer):
    """Remove a public URL; the application keeps running."""
    operation: Literal["delete_public_url"] = Field("delete_public_url", json_schema_extra={"ui:hidden": True})
    url_id: UUID


class OrgoListComputerAppsConfig(_Computer):
    """List apps saved on a computer."""
    operation: Literal["list_computer_apps"] = Field("list_computer_apps", json_schema_extra={"ui:hidden": True})


OrgoConfig = Annotated[Union[
    OrgoGetMeConfig,
    OrgoGetAccountCapacityConfig,
    OrgoGetAccountLimitsConfig,
    OrgoListWorkspacesConfig,
    OrgoCreateComputerConfig,
    OrgoGetComputerConfig,
    OrgoUpdateComputerConfig,
    OrgoDeleteComputerConfig,
    OrgoStartComputerConfig,
    OrgoStopComputerConfig,
    OrgoRestartComputerConfig,
    OrgoSuspendComputerConfig,
    OrgoResumeComputerConfig,
    OrgoGetComputerOperationConfig,
    OrgoRunBashConfig,
    OrgoClickConfig,
    OrgoTypeTextConfig,
    OrgoPressKeyConfig,
    OrgoListPublicUrlsConfig,
    OrgoCreatePublicUrlConfig,
    OrgoUpdatePublicUrlConfig,
    OrgoDeletePublicUrlConfig,
    OrgoListComputerAppsConfig
], Field(discriminator="operation")]


ROUTES = {'get_me': {'method': 'GET', 'path': '/api/me', 'path_fields': [], 'query_fields': [], 'body_fields': []},
 'get_account_capacity': {'method': 'GET',
                          'path': '/api/account/capacity',
                          'path_fields': [],
                          'query_fields': [],
                          'body_fields': []},
 'get_account_limits': {'method': 'GET',
                        'path': '/api/account/limits',
                        'path_fields': [],
                        'query_fields': [],
                        'body_fields': []},
 'list_workspaces': {'method': 'GET',
                     'path': '/api/workspaces',
                     'path_fields': [],
                     'query_fields': [],
                     'body_fields': []},
 'create_computer': {'method': 'POST',
                     'path': '/api/computers',
                     'path_fields': [],
                     'query_fields': [],
                     'body_fields': ['workspace_id',
                                     'name',
                                     'os',
                                     'ram',
                                     'cpu',
                                     'disk_size_gb',
                                     'resolution',
                                     'ends_in_hours',
                                     'billing_mode',
                                     'compute_request_id',
                                     'template_ref']},
 'get_computer': {'method': 'GET',
                  'path': '/api/computers/{computer_id}',
                  'path_fields': ['computer_id'],
                  'query_fields': [],
                  'body_fields': []},
 'update_computer': {'method': 'PATCH',
                     'path': '/api/computers/{computer_id}',
                     'path_fields': ['computer_id'],
                     'query_fields': [],
                     'body_fields': ['name', 'ends_in_hours']},
 'delete_computer': {'method': 'DELETE',
                     'path': '/api/computers/{computer_id}',
                     'path_fields': ['computer_id'],
                     'query_fields': [],
                     'body_fields': []},
 'start_computer': {'method': 'POST',
                    'path': '/api/computers/{computer_id}/start',
                    'path_fields': ['computer_id'],
                    'query_fields': [],
                    'body_fields': ['ends_in_hours', 'billing_mode']},
 'stop_computer': {'method': 'POST',
                   'path': '/api/computers/{computer_id}/stop',
                   'path_fields': ['computer_id'],
                   'query_fields': [],
                   'body_fields': []},
 'restart_computer': {'method': 'POST',
                      'path': '/api/computers/{computer_id}/restart',
                      'path_fields': ['computer_id'],
                      'query_fields': [],
                      'body_fields': ['clear_disk']},
 'suspend_computer': {'method': 'POST',
                      'path': '/api/computers/{computer_id}/suspend',
                      'path_fields': ['computer_id'],
                      'query_fields': [],
                      'body_fields': []},
 'resume_computer': {'method': 'POST',
                     'path': '/api/computers/{computer_id}/resume',
                     'path_fields': ['computer_id'],
                     'query_fields': [],
                     'body_fields': ['ends_in_hours']},
 'get_computer_operation': {'method': 'GET',
                            'path': '/api/computers/{computer_id}/operations/{operation_id}',
                            'path_fields': ['computer_id', 'operation_id'],
                            'query_fields': [],
                            'body_fields': []},
 'run_bash': {'method': 'POST',
              'path': '/api/computers/{computer_id}/bash',
              'path_fields': ['computer_id'],
              'query_fields': ['screen'],
              'body_fields': ['command', 'timeout']},
 'click': {'method': 'POST',
           'path': '/api/computers/{computer_id}/click',
           'path_fields': ['computer_id'],
           'query_fields': ['screen'],
           'body_fields': ['x', 'y', 'button', 'double']},
 'type_text': {'method': 'POST',
               'path': '/api/computers/{computer_id}/type',
               'path_fields': ['computer_id'],
               'query_fields': ['screen'],
               'body_fields': ['text']},
 'press_key': {'method': 'POST',
               'path': '/api/computers/{computer_id}/key',
               'path_fields': ['computer_id'],
               'query_fields': ['screen'],
               'body_fields': ['key']},
 'list_public_urls': {'method': 'GET',
                      'path': '/api/computers/{computer_id}/public-urls',
                      'path_fields': ['computer_id'],
                      'query_fields': [],
                      'body_fields': []},
 'create_public_url': {'method': 'POST',
                       'path': '/api/computers/{computer_id}/public-urls',
                       'path_fields': ['computer_id'],
                       'query_fields': [],
                       'body_fields': ['port', 'name']},
 'update_public_url': {'method': 'PATCH',
                       'path': '/api/computers/{computer_id}/public-urls/{url_id}',
                       'path_fields': ['computer_id', 'url_id'],
                       'query_fields': [],
                       'body_fields': ['port', 'password']},
 'delete_public_url': {'method': 'DELETE',
                       'path': '/api/computers/{computer_id}/public-urls/{url_id}',
                       'path_fields': ['computer_id', 'url_id'],
                       'query_fields': [],
                       'body_fields': []},
 'list_computer_apps': {'method': 'GET',
                        'path': '/api/computers/{computer_id}/apps',
                        'path_fields': ['computer_id'],
                        'query_fields': [],
                        'body_fields': []}}


class OrgoFullConfig(NodeConfig[OrgoConfig, OrgoAPIKeyCredential]):
    pass


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {name: _redact(item, key) for name, item in value.items()}
    return value


class OrgoNode(WorkflowNode):
    integration_type = "automation-orgo"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return OrgoFullConfig

    async def execute(self, input_data):
        if not self.config.credentials:
            raise ValueError("Attach an Orgo API key")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = route["path"]
        for name in route["path_fields"]:
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {name: values[name] for name in route["query_fields"] if name in values}
        body = {name: values[name] for name in route["body_fields"] if name in values}
        if values.get("keep_forever"):
            body["ends_at"] = None
        if "run_async" in values:
            body["async"] = values["run_async"]
        if config.operation == "update_public_url":
            if config.remove_password:
                if config.password is not None:
                    raise ValueError("Choose password or remove_password, never both")
                body["password"] = None
            if not body:
                raise ValueError("Provide a port, password or remove_password")
        if config.operation == "update_computer" and not body:
            raise ValueError("Provide a name, ends_in_hours or keep_forever")
        key = self.config.credentials.api_key
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        if config.operation == "create_computer" and config.idempotency_key:
            headers["Idempotency-Key"] = config.idempotency_key
        try:
            async with guarded_async_client(timeout=330, trust_env=False, follow_redirects=False) as client:
                response = await client.request(route["method"], BASE + path, params=params, headers=headers,
                    **({"json": body} if route["method"] in {"POST", "PATCH"} else {}))
            if not 200 <= response.status_code < 300:
                message = "Orgo request failed"
                error = None
                try:
                    error = _redact(response.json(), key)
                    if isinstance(error, dict):
                        detail = error.get("error") or error.get("message")
                        if isinstance(detail, str):
                            message = detail[:1000]
                except ValueError:
                    pass
                return {"status": "error", "http_status": response.status_code, "message": message,
                    "data": error, "retry_after": response.headers.get("Retry-After")}
            if response.status_code == 204:
                return {"status": "success", "http_status": 204, "data": None}
            if len(response.content) > 10_000_000:
                raise ValueError("Orgo response exceeded the JSON size limit")
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError("Expected an Orgo JSON object or array")
            payload = _redact(payload, key)
            if isinstance(payload, dict) and (payload.get("success") is False or payload.get("error")):
                detail = payload.get("error")
                return {"status": "error", "http_status": response.status_code, "data": payload,
                    "message": detail[:1000] if isinstance(detail, str) else "Orgo reported an unsuccessful action"}
            return {"status": "success", "http_status": response.status_code, "data": payload}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "message": "Orgo request could not be confirmed; inspect mutations before retrying"}
