"""Transloadit API2 operations; published contract version 2.0.0."""
from __future__ import annotations
import json
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.transloadit import TRANSLOADIT_SCOPES
from utils.ssrf import guarded_async_client


class TransloaditTokenCredential(BaseModel):
    model_config = ConfigDict(title="Transloadit Bearer Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://transloadit.com/docs/api/token-post/",
        "x-credential-instructions": "Paste an API2 bearer access token without the Bearer prefix. Create it server-side using your Auth Key and Auth Secret with audience api2. Request assemblies:read, assemblies:write, templates:read, templates:write, template_credentials:read, template_credentials:write and assembly_notifications:write for all operations. Tokens expire (normally after six hours); replace the token when it expires. NoClick does not renew it. Connection checks list your own Templates and require templates:read.",
    })
    credential_type: Literal["transloadit_token"] = Field("transloadit_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Bearer access token", min_length=1, max_length=16384, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="access_token")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, le=9007199254740991)
    pagesize: int = Field(50, ge=1, le=850)
    order: Literal["asc", "desc"] = "desc"


class ListAssemblies(_Page):
    operation: Literal["list_assemblies"] = "list_assemblies"
    pagesize: int = Field(50, ge=1, le=5000)
    type: Literal["all", "canceled", "completed", "executing", "expired", "failed", "fixable", "problematic", "request_aborted", "uploading"] = "all"
    template_id: str | None = None
    fromdate: str | None = None
    todate: str | None = None


class _Assembly(_Input):
    assembly_id: str = Field(..., pattern=r"^[a-z0-9]{32}$", description="Private Assembly ID; grants capability-based status and cancellation access.")


class GetAssembly(_Assembly):
    operation: Literal["get_assembly"] = "get_assembly"


class CancelAssembly(_Assembly):
    operation: Literal["cancel_assembly"] = "cancel_assembly"


class CreateAssembly(_Input):
    operation: Literal["create_assembly"] = "create_assembly"
    template_id: str = Field(..., min_length=1, description="Existing Template to run. Use import Steps in the Template for remote files; no local uploads are sent.")
    fields: dict = Field(default_factory=dict, description="Assembly variables used by the Template.")
    notify_url: str | None = Field(None, description="Webhook destination for completion notifications.")


class ReplayAssembly(_Assembly):
    operation: Literal["replay_assembly"] = "replay_assembly"
    reparse_template: Literal[0, 1] = 0
    fields: dict | None = None
    notify_url: str | None = None


class ListAssemblyNotifications(_Assembly):
    operation: Literal["list_assembly_notifications"] = "list_assembly_notifications"


class ReplayAssemblyNotification(_Assembly):
    operation: Literal["replay_assembly_notification"] = "replay_assembly_notification"
    notify_url: str | None = Field(None, description="Optional replacement webhook destination. Sends a notification.")
    wait: bool = False


class ListTemplates(_Page):
    operation: Literal["list_templates"] = "list_templates"
    include_builtin: Literal["all", "exclusively-all", "exclusively-latest", "latest", "none"] = "none"


class _Template(_Input):
    template_id_or_name: str = Field(..., pattern=r"^[a-z0-9-]+$")


class GetTemplate(_Template):
    operation: Literal["get_template"] = "get_template"


class DeleteTemplate(_Template):
    operation: Literal["delete_template"] = "delete_template"


class CreateTemplate(_Input):
    operation: Literal["create_template"] = "create_template"
    name: str = Field(..., min_length=3, max_length=200)
    template: dict = Field(..., description="Assembly Instructions object including steps.", json_schema_extra={"ui:widget": "json"})


class UpdateTemplate(_Template):
    operation: Literal["update_template"] = "update_template"
    name: str | None = Field(None, min_length=3, max_length=200)
    template: dict | None = Field(None, description="Replacement Assembly Instructions.", json_schema_extra={"ui:widget": "json"})


class ListTemplateCredentials(_Input):
    operation: Literal["list_template_credentials"] = "list_template_credentials"


class ListTemplateCredentialTypes(_Input):
    operation: Literal["list_template_credential_types"] = "list_template_credential_types"


class _TemplateCredential(_Input):
    template_credential_id: str = Field(..., pattern=r"^[0-9a-f]{32}$")


class GetTemplateCredential(_TemplateCredential):
    operation: Literal["get_template_credential"] = "get_template_credential"


class DeleteTemplateCredential(_TemplateCredential):
    operation: Literal["delete_template_credential"] = "delete_template_credential"


TransloaditConfig = Annotated[Union[
    ListAssemblies, GetAssembly, CreateAssembly, CancelAssembly, ReplayAssembly,
    ListAssemblyNotifications, ReplayAssemblyNotification, ListTemplates,
    GetTemplate, CreateTemplate, UpdateTemplate, DeleteTemplate,
    ListTemplateCredentials, ListTemplateCredentialTypes, GetTemplateCredential,
    DeleteTemplateCredential,
], Field(discriminator="operation")]


class TransloaditFullConfig(NodeConfig[TransloaditConfig, TransloaditTokenCredential]):
    pass


ROUTES = {
    "list_assemblies": ("GET", "/assemblies"),
    "get_assembly": ("GET", "/assemblies/{assembly_id}"),
    "create_assembly": ("POST", "/assemblies"),
    "cancel_assembly": ("DELETE", "/assemblies/{assembly_id}"),
    "replay_assembly": ("POST", "/assemblies/{assembly_id}/replay"),
    "list_assembly_notifications": ("GET", "/assembly_notifications/{assembly_id}"),
    "replay_assembly_notification": ("POST", "/assembly_notifications/{assembly_id}/replay"),
    "list_templates": ("GET", "/templates"),
    "get_template": ("GET", "/templates/{template_id_or_name}"),
    "create_template": ("POST", "/templates"),
    "update_template": ("PUT", "/templates/{template_id_or_name}"),
    "delete_template": ("DELETE", "/templates/{template_id_or_name}"),
    "list_template_credentials": ("GET", "/template_credentials"),
    "list_template_credential_types": ("GET", "/template_credentials/types"),
    "get_template_credential": ("GET", "/template_credentials/{template_credential_id}"),
    "delete_template_credential": ("DELETE", "/template_credentials/{template_credential_id}"),
}
CAPABILITY_OPERATIONS = {"get_assembly", "cancel_assembly", "list_assembly_notifications"}


def _redact(value, token, *, credential_metadata=False):
    if isinstance(value, dict):
        excluded = {"auth", "signature", "access_token", "secret", "stringified"}
        if credential_metadata:
            excluded.add("content")
        return {k: _redact(v, token, credential_metadata=credential_metadata) for k, v in value.items() if k not in excluded}
    if isinstance(value, list):
        return [_redact(v, token, credential_metadata=credential_metadata) for v in value]
    return value.replace(token, "[redacted]") if isinstance(value, str) else value


class TransloaditNode(WorkflowNode):
    integration_type = "automation-transloadit"
    scope_registry = TRANSLOADIT_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_templates", noun="Templates")

    @classmethod
    def get_config_model(cls):
        return TransloaditFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Transloadit bearer token")
        config = self.config.config
        token = self.config.credentials.access_token
        method, route = ROUTES[config.operation]
        params = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("assembly_id", "template_id_or_name", "template_credential_id"):
            if field in params:
                route = route.replace("{" + field + "}", quote(params.pop(field), safe=""))
        headers = {"Accept": "application/json"}
        if config.operation not in CAPABILITY_OPERATIONS:
            headers["Authorization"] = "Bearer " + token
        wire = json.dumps(params, separators=(",", ":"), allow_nan=False)
        kwargs = {}
        if config.operation == "create_assembly":
            kwargs["files"] = {"params": (None, wire, "application/json")}
        elif method == "GET":
            if config.operation not in CAPABILITY_OPERATIONS:
                kwargs["params"] = {"params": wire}
        elif config.operation not in CAPABILITY_OPERATIONS:
            kwargs["data"] = {"params": wire}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api2.transloadit.com" + route, headers=headers, **kwargs)
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            raise ValueError(_redact(body.get("message") or body["error"], token))
        response.raise_for_status()
        if not isinstance(body, (dict, list)):
            raise ValueError("Expected a Transloadit JSON object or array")
        output = {"status": "success", "action": config.operation, "data": _redact(body, token,
            credential_metadata=config.operation in {"get_template_credential", "list_template_credentials"})}
        await self.emit(output)
        return output
