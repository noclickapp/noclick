"""Nextcloud Files OCS actions and Webhook Listeners file events.

Contracts: nextcloud/server apps/{files,webhook_listeners}/openapi.json.
Webhook payloads: docs.nextcloud.com/server/stable/admin_manual/webhook_listeners/.
"""
from __future__ import annotations

import base64
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

FILES = "/ocs/v2.php/apps/files/api/v1"
WEBHOOKS = "/ocs/v2.php/apps/webhook_listeners/api/v1/webhooks"
EVENT_PREFIX = "OCP\\Files\\Events\\Node\\"
EVENTS = tuple(EVENT_PREFIX + name for name in (
    "NodeCreatedEvent", "NodeWrittenEvent", "NodeDeletedEvent", "NodeRenamedEvent", "NodeRestoredEvent"))


class NextcloudAppPasswordCredential(BaseModel):
    model_config = ConfigDict(title="Nextcloud App Password", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.nextcloud.com/server/stable/user_manual/en/session_management.html",
        "x-credential-instructions": "Enter your public HTTPS Nextcloud installation URL, username and an app password from Personal settings → Security → Devices & sessions. File triggers require the Webhook Listeners app and administrator or delegated Webhooks privileges. The app password is sent using HTTP Basic authentication."})
    credential_type: Literal["nextcloud_app_password"] = Field("nextcloud_app_password", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Nextcloud Server URL", description="Installation root, for example https://cloud.example.com/nextcloud. Public HTTPS only.")
    username: str = Field(..., min_length=1, max_length=255, title="Username")
    app_password: str = Field(..., min_length=1, max_length=4096, title="App Password", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url", mode="before")
    @classmethod
    def installation(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter the HTTPS installation root")
        value = value.strip().rstrip("/")
        try:
            p = urlsplit(value)
            if (p.scheme != "https" or not p.hostname or p.username is not None or p.password is not None
                    or p.port not in (None, 443) or p.query or p.fragment
                    or not re.fullmatch(r"[A-Za-z0-9.-]+", p.hostname)
                    or not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", p.path)
                    or any(c.isspace() for c in value)):
                raise ValueError()
        except ValueError:
            raise ValueError("Use a public HTTPS installation root without credentials, query or fragment") from None
        return "https://" + p.hostname.lower() + p.path

    @field_validator("username")
    @classmethod
    def user(cls, value):
        if ":" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Username cannot contain a colon or controls")
        return value

    @field_validator("app_password", mode="before")
    @classmethod
    def password(cls, value):
        value = clean_secret(value, field_name="App password")
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("App password cannot contain controls")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class TemplateField(_Input):
    index: str
    type: str
    alias: str | None
    tag: str | None
    id: int | None
    content: str | None = None
    checked: bool | None = None


def text(title, *, required=False, default=None):
    return (str if required or default is not None else str | None,
            Field(... if required else default, title=title, min_length=1 if required else None))


def number(title, *, required=True, default=None, minimum=None):
    return (int if required or default is not None else int | None,
            Field(... if required else default, title=title, ge=minimum))


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    fields: dict[str, tuple[Any, Any]]
    query: tuple[str, ...] = ()


OPERATIONS = {
    "list_folders": Operation("List Folder Tree", "GET", FILES + "/folder-tree", {
        "path": text("Folder Path", default="/"), "depth": number("Depth", required=False, default=1, minimum=0),
        "withParents": (bool, Field(False, title="Include Parent Folders"))}, ("path", "depth", "withParents")),
    "list_templates": Operation("List File Templates", "GET", FILES + "/templates", {}),
    "get_template_fields": Operation("Get Template Fields", "GET", FILES + "/templates/fields/{fileId}", {
        "fileId": number("Template File ID")}),
    "create_from_template": Operation("Create File from Template", "POST", FILES + "/templates/create", {
        "filePath": text("New File Path", required=True), "templatePath": text("Template Path", default=""),
        "templateType": text("Template Type", default="user"),
        "templateFields": (list[TemplateField], Field(default_factory=list, title="Template Fields"))}),
    "initialize_templates": Operation("Initialize Template Directory", "POST", FILES + "/templates/path", {
        "templatePath": text("Template Directory", default=""),
        "copySystemTemplates": (bool, Field(False, title="Copy System Templates"))}),
    "get_editing_capabilities": Operation("Get Direct Editing Capabilities", "GET", FILES + "/directEditing", {}),
    "list_editor_templates": Operation("List Editor Templates", "GET", FILES + "/directEditing/templates/{editorId}/{creatorId}", {
        "editorId": text("Editor ID", required=True), "creatorId": text("Creator ID", required=True)}),
    "open_editor": Operation("Open File for Editing", "POST", FILES + "/directEditing/open", {
        "path": text("File Path", required=True), "editorId": text("Editor ID"), "fileId": number("File ID", required=False)}),
    "create_for_editing": Operation("Create File for Editing", "POST", FILES + "/directEditing/create", {
        "path": text("New File Path", required=True), "editorId": text("Editor ID", required=True),
        "creatorId": text("Creator ID", required=True), "templateId": text("Template ID")}),
    "convert_file": Operation("Convert File", "POST", FILES + "/convert", {
        "fileId": number("File ID"), "targetMimeType": text("Target MIME Type", required=True),
        "destination": text("Destination Path")}),
    "transfer_ownership": Operation("Request Ownership Transfer", "POST", FILES + "/transferownership", {
        "recipient": text("Recipient Username", required=True), "path": text("File or Folder Path", required=True)}),
    "accept_transfer": Operation("Accept Ownership Transfer", "POST", FILES + "/transferownership/{id}", {
        "id": number("Transfer ID", minimum=1)}),
    "reject_transfer": Operation("Reject Ownership Transfer", "DELETE", FILES + "/transferownership/{id}", {
        "id": number("Transfer ID", minimum=1)}),
    "create_local_editor": Operation("Create Local Editor Session", "POST", FILES + "/openlocaleditor", {
        "path": text("File Path", required=True)}),
    "validate_local_editor": Operation("Validate Local Editor Session", "POST", FILES + "/openlocaleditor/{token}", {
        "token": text("Local Editor Token", required=True), "path": text("File Path", required=True)}),
}


def _model(name, spec):
    return create_model("Nextcloud" + "".join(w.title() for w in name.split("_")) + "Config", __base__=_Input,
        __module__=__name__, operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "ui:hidden": True, "x-is-trigger": False, "x-display-name": spec.label})), **spec.fields)


CONFIGS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({m.__name__: m for m in CONFIGS.values()})


class NextcloudOnFileEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_file_event"] = Field("on_file_event", title="On File Event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On File Created, Updated, Deleted, Renamed or Restored"})
    event_type: Literal[*EVENTS] = Field(EVENTS[0], title="File Event")
    user_id: str = Field(..., min_length=1, title="Acting User ID", description="Only events caused by this Nextcloud user. Use the account's internal user ID, which may differ from its login name.")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


NextcloudConfig = Annotated[Union[tuple(CONFIGS.values()) + (NextcloudOnFileEventConfig,)], Field(discriminator="operation")]


class NextcloudNodeConfig(NodeConfig[NextcloudConfig, NextcloudAppPasswordCredential]):
    pass


class NextcloudNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-nextcloud"
    connection_evidence = ConnectionEvidence(operation="list_folders", noun="folders", label_keys=("basename", "displayName", "id"))

    @classmethod
    def get_config_model(cls):
        return NextcloudNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = NextcloudAppPasswordCredential.model_validate(credential)
        auth = base64.b64encode((credential.username + ":" + credential.app_password).encode()).decode()
        headers = {"Authorization": "Basic " + auth, "Accept": "application/json", "OCS-APIRequest": "true"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.server_url + path, headers=headers, params=params,
                                            **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Nextcloud API rejected the request (HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Nextcloud returned invalid JSON; check the installation URL") from None
        if path == FILES + "/folder-tree":
            if not isinstance(data, list):
                raise ValueError("Nextcloud returned an invalid folder tree")
            return data
        if not isinstance(data, dict) or not isinstance(data.get("ocs"), dict):
            raise ValueError("Nextcloud returned an invalid OCS response")
        ocs = data["ocs"]
        meta = ocs.get("meta")
        if not isinstance(meta, dict) or not isinstance(meta.get("status"), str) or type(meta.get("statuscode")) is not int:
            raise ValueError("Nextcloud returned invalid OCS metadata")
        # OCS v2 maps errors to HTTP status; also reject explicit OCS failures.
        if meta["status"].lower() in ("failure", "error") or meta["statuscode"] >= 400:
            raise ValueError("Nextcloud OCS request was not successful")
        if "data" not in ocs:
            raise ValueError("Nextcloud response is missing OCS data")
        return ocs["data"]

    async def execute(self, inputs):
        op = self.config.config
        if op.operation == "on_file_event":
            return self.resolve_trigger_payload(inputs, op.model_dump()) or {"status": "no_event"}
        if self.config.credentials is None:
            raise ValueError("Connect a Nextcloud app password")
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        if "templateFields" in values:
            values["templateFields"] = [field.model_dump(exclude_none=True) |
                {key: getattr(field, key) for key in ("alias", "tag", "id")} for field in op.templateFields]
        for key in tuple(values):
            if "{" + key + "}" in path:
                value = str(values.pop(key))
                if value in (".", ".."):
                    raise ValueError("Use a resource ID, not a relative path")
                path = path.replace("{" + key + "}", quote(value, safe=""))
        params = {key: str(values.pop(key)).lower() if isinstance(values[key], bool) else values.pop(key)
                  for key in spec.query}
        data = await self._request(self.config.credentials.model_dump(), spec.method, path,
                                   params=params or None, body=values if spec.method == "POST" and values else None)
        return {"status": "success", "operation": op.operation, "data": data}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: config.get(key) for key in ("event_type", "user_id")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = NextcloudOnFileEventConfig.model_validate(config)
        secret = secrets.token_urlsafe(32)
        data = await cls._request(credential, "POST", WEBHOOKS, body={
            "httpMethod": "POST", "uri": webhook_url, "event": op.event_type,
            "userIdFilter": op.user_id, "authMethod": "none", "headers": {"X-NoClick-Webhook-Secret": secret}})
        if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"]:
            raise ValueError("Nextcloud did not return a webhook registration ID")
        return {"external_webhook_id": data["id"], "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = config.get("external_webhook_id")
        if identifier is None:
            return
        if not credential:
            raise ValueError("Connect Nextcloud to remove the webhook")
        deleted = await cls._request(credential, "DELETE", WEBHOOKS + "/" + quote(str(identifier), safe=""))
        # deleteById returns false when the row is already absent (idempotent cleanup).
        # nextcloud/server apps/webhook_listeners/lib/Db/WebhookListenerMapper.php
        if type(deleted) is not bool:
            raise ValueError("Nextcloud did not confirm webhook deletion")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        supplied = next((v for k, v in headers.items() if k.lower() == "x-noclick-webhook-secret"), "")
        return bool(isinstance(secret, str) and secret and isinstance(supplied, str)
                    and hmac.compare_digest(secret.encode(), supplied.encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = payload.get("event")
        user = payload.get("user")
        return (isinstance(event, dict) and event.get("class") in EVENTS
                and event.get("class") == config.get("event_type")
                and isinstance(user, dict) and user.get("uid") == config.get("user_id"))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        return {"status": "success", "data": {k: payload[k] for k in ("event", "user", "time") if k in payload}}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or not isinstance(output.get("data"), dict):
            return super().resolve_agent_event(output)
        data = output["data"]
        event = data.get("event")
        if not isinstance(event, dict):
            return super().resolve_agent_event(output)
        user = data.get("user") or {}
        if not isinstance(user, dict):
            return super().resolve_agent_event(output)
        node = event["target"] if "target" in event else event["node"] if "node" in event else {}
        if not isinstance(node, dict):
            return super().resolve_agent_event(output)
        path = node.get("path")
        if not path:
            return super().resolve_agent_event(output)
        action = {
            EVENTS[0]: "file or folder created", EVENTS[1]: "file or folder updated",
            EVENTS[2]: "file or folder deleted", EVENTS[3]: "file or folder renamed",
            EVENTS[4]: "file or folder restored",
        }.get(event.get("class"), "file event")
        text = f"Nextcloud {action}: {path}\nBy {user.get('displayName') or user.get('uid') or 'system'}"
        text += f" (user ID: {user.get('uid')}); at {data.get('time')}."
        if "source" in event and isinstance(event["source"], dict):
            text += f"\nFrom: {event['source'].get('path')}"
        if "id" in node and node["id"] is not None:
            text += f"\nFile ID: {node['id']}. Use convert_file with fileId, or open_editor with path."
        return {"text": text, "conversation_key": str(node["id"] if "id" in node else path), "title": f"Nextcloud: {path}"}
