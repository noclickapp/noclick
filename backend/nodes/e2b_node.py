"""E2B sandbox control-plane API, pinned to the publisher's OpenAPI 0.1.0.

Each operation performs one request. Lists return a single page and the provider's
X-Next-Token cursor. Code execution and filesystem APIs use a separate sandbox
contract and are intentionally outside this control-plane integration.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence

API_ROOT = "https://api.e2b.app"


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class E2BAPIKeyCredential(Closed):
    model_config = ConfigDict(title="E2B API Key", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://console.e2b.dev/keys",
                           "x-credential-instructions": "Copy an API key from your E2B dashboard and paste it here."})
    credential_type: Literal["e2b_api_key"] = Field("e2b_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1,
        description="Paste your E2B API key. It is sent in the X-API-Key header.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key_is_header(cls, value):
        value = value.strip()
        if not value or not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste a single API key without whitespace")
        return value


class Page(Closed):
    limit: int = Field(100, ge=1, le=100, strict=True, description="Maximum records in this page")
    next_token: str | None = Field(None, description="X-Next-Token returned by the preceding page")


class Sandbox(Closed):
    sandbox_id: str = Field(..., min_length=1, description="E2B sandbox ID")


class Template(Closed):
    template_id: str = Field(..., min_length=1, description="E2B template ID")


class TemplatePage(Template, Page):
    pass


class Events(Closed):
    offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(10, ge=1, le=100, strict=True)
    order_asc: bool = False
    types: list[str] | None = Field(None, description="Repeatable event-type filter")


class SandboxEvents(Sandbox, Events):
    pass


class Webhook(Closed):
    webhook_id: str = Field(..., description="Webhook UUID", json_schema_extra={"format": "uuid"})

    @field_validator("webhook_id")
    @classmethod
    def canonical_uuid(cls, value):
        return str(UUID(value))


class ListSandboxes(Page):
    operation: Literal["list_sandboxes"] = Field("list_sandboxes", title="List Sandboxes", json_schema_extra={"ui:hidden": True})
    metadata: str | None = Field(None, description="URL-encoded metadata filter, e.g. user=abc&app=prod")
    state: list[Literal["running", "paused"]] | None = None
    order: Literal["asc", "desc"] = "desc"
    template: str | None = None


class CreateSandbox(Closed):
    operation: Literal["create_sandbox"] = Field("create_sandbox", title="Create Sandbox", json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., min_length=1, description="Template ID or alias, for example base")
    timeout: int = Field(300, ge=0, strict=True, description="Lifetime in seconds")
    auto_pause: bool = False
    metadata: dict[str, str] | None = None
    env_vars: dict[str, str] | None = None
    allow_internet_access: bool = True


class GetSandbox(Sandbox):
    operation: Literal["get_sandbox"] = Field("get_sandbox", title="Get Sandbox", json_schema_extra={"ui:hidden": True})


class KillSandbox(Sandbox):
    operation: Literal["kill_sandbox"] = Field("kill_sandbox", title="Kill Sandbox", json_schema_extra={"ui:hidden": True})


class PauseSandbox(Sandbox):
    operation: Literal["pause_sandbox"] = Field("pause_sandbox", title="Pause Sandbox", json_schema_extra={"ui:hidden": True})
    memory: bool = Field(True, description="Persist memory as well as disk; false loses running processes on resume")
    require_healthy_guest: bool = False


class ConnectSandbox(Sandbox):
    operation: Literal["connect_sandbox"] = Field("connect_sandbox", title="Connect Sandbox", json_schema_extra={"ui:hidden": True})
    timeout: int = Field(300, ge=0, strict=True, description="Lifetime in seconds; resumes a paused sandbox")
    memory: bool = True


class SetSandboxTimeout(Sandbox):
    operation: Literal["set_sandbox_timeout"] = Field("set_sandbox_timeout", title="Set Sandbox Timeout", json_schema_extra={"ui:hidden": True})
    timeout: int = Field(..., ge=0, strict=True, description="Seconds from this request until expiry")


class GetSandboxMetrics(Sandbox):
    operation: Literal["get_sandbox_metrics"] = Field("get_sandbox_metrics", title="Get Sandbox Metrics", json_schema_extra={"ui:hidden": True})
    start: int | None = Field(None, ge=0, description="Unix seconds")
    end: int | None = Field(None, ge=0, description="Unix seconds")


class CreateSnapshot(Sandbox):
    operation: Literal["create_snapshot"] = Field("create_snapshot", title="Create Snapshot", json_schema_extra={"ui:hidden": True})
    name: str | None = None
    memory: bool = Field(True, description="Capture memory; false persists only the filesystem")


class ListSnapshots(Page):
    operation: Literal["list_snapshots"] = Field("list_snapshots", title="List Snapshots", json_schema_extra={"ui:hidden": True})
    sandbox_id: str | None = None
    name: str | None = None


class ListTemplates(Page):
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", json_schema_extra={"ui:hidden": True})


class ListTemplateBuilds(TemplatePage):
    operation: Literal["list_template_builds"] = Field("list_template_builds", title="List Template Builds", json_schema_extra={"ui:hidden": True})


class DeleteTemplate(Template):
    operation: Literal["delete_template"] = Field("delete_template", title="Delete Template", json_schema_extra={"ui:hidden": True})


class UpdateTemplate(Template):
    operation: Literal["update_template"] = Field("update_template", title="Update Template", json_schema_extra={"ui:hidden": True})
    public: bool = Field(..., description="Whether other teams may access the template")


class GetBuildStatus(Template):
    operation: Literal["get_build_status"] = Field("get_build_status", title="Get Build Status", json_schema_extra={"ui:hidden": True})
    build_id: str = Field(..., min_length=1)
    logs_offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(100, ge=0, le=100, strict=True)
    level: Literal["debug", "info", "warn", "error"] | None = None


class ListTeamEvents(Events):
    operation: Literal["list_team_events"] = Field("list_team_events", title="List Team Events", json_schema_extra={"ui:hidden": True})


class ListSandboxEvents(SandboxEvents):
    operation: Literal["list_sandbox_events"] = Field("list_sandbox_events", title="List Sandbox Events", json_schema_extra={"ui:hidden": True})


class ListWebhooks(Closed):
    operation: Literal["list_webhooks"] = Field("list_webhooks", title="List Webhooks", json_schema_extra={"ui:hidden": True})


class GetWebhook(Webhook):
    operation: Literal["get_webhook"] = Field("get_webhook", title="Get Webhook", json_schema_extra={"ui:hidden": True})


class CreateWebhook(Closed):
    operation: Literal["create_webhook"] = Field("create_webhook", title="Create Webhook", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    url: str = Field(..., json_schema_extra={"format": "uri"})
    events: list[str] = Field(..., min_length=1)
    signature_secret: str = Field(..., min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    enabled: bool = True


class UpdateWebhook(Webhook):
    operation: Literal["update_webhook"] = Field("update_webhook", title="Update Webhook", json_schema_extra={"ui:hidden": True})
    enabled: bool | None = None
    name: str | None = None
    url: str | None = Field(None, json_schema_extra={"format": "uri"})
    events: list[str] | None = None
    signature_secret: str | None = Field(None, repr=False, json_schema_extra={"ui:widget": "password"})


class DeleteWebhook(Webhook):
    operation: Literal["delete_webhook"] = Field("delete_webhook", title="Delete Webhook", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListSandboxes, CreateSandbox, GetSandbox, KillSandbox, PauseSandbox, ConnectSandbox, SetSandboxTimeout, GetSandboxMetrics, CreateSnapshot, ListSnapshots, ListTemplates, ListTemplateBuilds, DeleteTemplate, UpdateTemplate, GetBuildStatus, ListTeamEvents, ListSandboxEvents, ListWebhooks, GetWebhook, CreateWebhook, UpdateWebhook, DeleteWebhook], Field(discriminator="operation")]


class E2BNodeConfig(NodeConfig[Operation, E2BAPIKeyCredential]):
    pass


ROUTES = {'list_sandboxes': {'method': 'GET', 'path': '/v2/sandboxes', 'fields': {}, 'responses': {200: 'array'}},
 'create_sandbox': {'method': 'POST',
                    'path': '/sandboxes',
                    'fields': {'template_id': 'templateID',
                               'auto_pause': 'autoPause',
                               'env_vars': 'envVars'},
                    'responses': {201: 'object'}},
 'get_sandbox': {'method': 'GET',
                 'path': '/sandboxes/{sandbox_id}',
                 'fields': {},
                 'responses': {200: 'object'}},
 'kill_sandbox': {'method': 'DELETE',
                  'path': '/sandboxes/{sandbox_id}',
                  'fields': {},
                  'responses': {204: None}},
 'pause_sandbox': {'method': 'POST',
                   'path': '/sandboxes/{sandbox_id}/pause',
                   'fields': {'require_healthy_guest': 'requireHealthyGuest'},
                   'responses': {204: None}},
 'connect_sandbox': {'method': 'POST',
                     'path': '/sandboxes/{sandbox_id}/connect',
                     'fields': {},
                     'responses': {200: 'object', 201: 'object'}},
 'set_sandbox_timeout': {'method': 'POST',
                         'path': '/sandboxes/{sandbox_id}/timeout',
                         'fields': {},
                         'responses': {204: None}},
 'get_sandbox_metrics': {'method': 'GET',
                         'path': '/sandboxes/{sandbox_id}/metrics',
                         'fields': {},
                         'responses': {200: 'array'}},
 'create_snapshot': {'method': 'POST',
                     'path': '/sandboxes/{sandbox_id}/snapshots',
                     'fields': {},
                     'responses': {201: 'object'}},
 'list_snapshots': {'method': 'GET',
                    'path': '/snapshots',
                    'fields': {'sandbox_id': 'sandboxID'},
                    'responses': {200: 'array'}},
 'list_templates': {'method': 'GET', 'path': '/v2/templates', 'fields': {}, 'responses': {200: 'array'}},
 'list_template_builds': {'method': 'GET',
                          'path': '/templates/{template_id}',
                          'fields': {},
                          'responses': {200: 'object'}},
 'delete_template': {'method': 'DELETE',
                     'path': '/templates/{template_id}',
                     'fields': {},
                     'responses': {204: None}},
 'update_template': {'method': 'PATCH',
                     'path': '/v2/templates/{template_id}',
                     'fields': {},
                     'responses': {200: 'object'}},
 'get_build_status': {'method': 'GET',
                      'path': '/templates/{template_id}/builds/{build_id}/status',
                      'fields': {'logs_offset': 'logsOffset'},
                      'responses': {200: 'object'}},
 'list_team_events': {'method': 'GET',
                      'path': '/events/sandboxes',
                      'fields': {},
                      'responses': {200: 'array'}},
 'list_sandbox_events': {'method': 'GET',
                         'path': '/events/sandboxes/{sandbox_id}',
                         'fields': {},
                         'responses': {200: 'array'}},
 'list_webhooks': {'method': 'GET',
                   'path': '/events/webhooks',
                   'fields': {},
                   'responses': {200: 'array'}},
 'get_webhook': {'method': 'GET',
                 'path': '/events/webhooks/{webhook_id}',
                 'fields': {},
                 'responses': {200: 'object'}},
 'create_webhook': {'method': 'POST',
                    'path': '/events/webhooks',
                    'fields': {'signature_secret': 'signatureSecret'},
                    'responses': {201: 'object'}},
 'update_webhook': {'method': 'PATCH',
                    'path': '/events/webhooks/{webhook_id}',
                    'fields': {'signature_secret': 'signatureSecret'},
                    'responses': {200: 'object'}},
 'delete_webhook': {'method': 'DELETE',
                    'path': '/events/webhooks/{webhook_id}',
                    'fields': {},
                    'responses': {200: None}}}


def _segment(value):
    if not isinstance(value, str) or not value or value in {".", ".."} or any(ord(c) < 32 for c in value):
        raise ValueError("A nonempty E2B resource identifier is required")
    return quote(value, safe="")


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(x, secrets) for x in value]
    if isinstance(value, dict):
        return {_redact(k, secrets): _redact(v, secrets) for k, v in value.items()}
    return value


class E2BNode(WorkflowNode):
    integration_type = "automation-e2b"
    connection_evidence = ConnectionEvidence(noun="templates", operation="list_templates", label_keys=("name", "templateID"))
    edit_examples = ["Create a sandbox from the base template", "Pause this sandbox", "List my sandbox events"]

    @classmethod
    def get_config_model(cls):
        return E2BNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        return TypeAdapter(E2BNodeConfig).validate_python(runtime_config_view(config_data, E2BNodeConfig))

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an E2B API key")
        op = self.config.config
        spec = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        values.pop("operation")
        path = spec["path"]
        for field in re.findall(r"{(\w+)}", path):
            path = path.replace("{" + field + "}", _segment(values.pop(field)))
        aliases = {"next_token": "nextToken", "order_asc": "orderAsc", **spec["fields"]}
        payload = {aliases.get(k, k): v for k, v in values.items()}
        secrets = [self.config.credentials.api_key, getattr(op, "signature_secret", None)]
        method = spec["method"]
        kwargs = {}
        if method == "GET":
            # OpenAPI form/explode=false for state, explode=true for event types.
            kwargs["params"] = [(k, str(item).lower() if isinstance(item, bool) else item)
                for k, value in payload.items()
                for item in ([",".join(value)] if k == "state" else value if isinstance(value, list) else [value])]
        elif payload:
            kwargs["json"] = payload
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, API_ROOT + path,
                    headers={"X-API-Key": self.config.credentials.api_key, "Accept": "application/json"}, **kwargs)
            code = response.status_code
            if code not in spec["responses"]:
                message = "E2B returned HTTP " + str(code)
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"]
                except ValueError:
                    pass
                output = {"status": "error", "success": False, "http_status": code, "message": message}
            else:
                kind = spec["responses"][code]
                data = None
                if kind:
                    data = response.json()
                    if not isinstance(data, list if kind == "array" else dict):
                        raise ValueError("E2B returned an unexpected JSON shape")
                    if isinstance(data, dict) and (data.get("error") or data.get("error_code")):
                        raise ValueError("E2B returned an error envelope")
                output = {"status": "success", "success": True, "http_status": code, "data": data,
                          "next_page_token": response.headers.get("X-Next-Token")}
                if method == "GET" and isinstance(data, list):
                    output["has_more"] = bool(output["next_page_token"]) if "next_token" in type(op).model_fields else None
        except (httpx.HTTPError, ValueError):
            output = {"status": "error", "success": False,
                      "message": "E2B request or response could not be verified; inspect the resource before retrying a write"}
        output = _redact(output, secrets)
        await self.emit(output)
        return output
