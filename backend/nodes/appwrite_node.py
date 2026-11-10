"""Appwrite 2.3.0 project automation.

API keys: https://appwrite.io/docs/advanced/platform/api-keys
Webhook registration/signing: https://appwrite.io/docs/apis/webhooks
Event payloads mirror API models: https://appwrite.io/docs/apis/events
"""
import base64
import fnmatch
import hashlib
import hmac
import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator

from nodes.appwrite_operations import OPERATIONS, TRIGGERS
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.appwrite import APPWRITE_SCOPES
from utils.ssrf import guarded_async_client


class AppwriteAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Appwrite API Key", json_schema_extra={
        "x-credential-url": "https://cloud.appwrite.io/console",
        "x-credential-instructions": "In your project's Settings → API keys, create a key with databases.read for connection verification and the scopes needed by your actions. Triggers need webhooks.write. Paste the project ID, API endpoint (including /v1), and key. Self-hosted endpoints must be publicly reachable HTTPS URLs.",
    })
    credential_type: Literal["appwrite_api_key"] = Field("appwrite_api_key", json_schema_extra={"ui:hidden": True})
    endpoint: str = Field("https://cloud.appwrite.io/v1", title="API Endpoint", description="Copy your project's endpoint, for example https://fra.cloud.appwrite.io/v1")
    project_id: str = Field(..., title="Project ID", min_length=1, max_length=36)
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("endpoint")
    @classmethod
    def endpoint_url(cls, value):
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or parts.path != "/v1" or parts.port not in (None, 443)):
            raise ValueError("Use the HTTPS API endpoint ending in /v1")
        return value

    @field_validator("project_id")
    @classmethod
    def project(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,35}", value):
            raise ValueError("Copy the project ID from Appwrite Settings")
        return value


def _field(name, wire, location, kind, required, description):
    json_value = kind in {"array", "object"}
    typ = str if json_value or kind == "string" else bool if kind == "boolean" else int
    extra = {"ui:widget": "textarea"} if json_value else {}
    if name == "password":
        extra = {"ui:widget": "password", "writeOnly": True}
    title = name.replace("_", " ").title() + (" JSON" if json_value else "")
    return (typ if required else Optional[typ], Field(
        ... if required else None, title=title, description=description, json_schema_extra=extra))


CONFIG_MODELS = {}
for _name, _spec in OPERATIONS.items():
    _fields = {name: _field(name, *values) for name, values in _spec["fields"].items()}
    _fields["operation"] = (Literal[_name], Field(_name, json_schema_extra={
        "ui:hidden": True, "x-display-name": _spec["label"], "x-category": _spec["category"].title(),
    }))
    CONFIG_MODELS[_name] = create_model("Appwrite" + _name.title().replace("_", "") + "Config", **_fields)


class _WebhookConfig(WebhookTriggerConfigBase):
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


for _name in TRIGGERS:
    CONFIG_MODELS[_name] = create_model("Appwrite" + _name.title().replace("_", "") + "Config", __base__=_WebhookConfig,
        operation=(Literal[_name], Field(_name, json_schema_extra={
            "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
            "x-display-name": _name.replace("_", " ").title(),
        })))
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
AppwriteConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class AppwriteNodeConfig(NodeConfig[AppwriteConfig, AppwriteAPIKeyCredential]):
    pass


def _safe_data(value):
    """Users API models can include password hashes; never propagate them."""
    if isinstance(value, dict):
        return {k: _safe_data(v) for k, v in value.items() if k not in {"password", "hash", "hashOptions", "secret", "_webhook"}}
    if isinstance(value, list):
        return [_safe_data(v) for v in value]
    return value


class AppwriteNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-appwrite"
    connection_evidence = ConnectionEvidence(operation="list_databases", noun="databases", label_keys=("name", "$id"))
    scope_registry = APPWRITE_SCOPES
    edit_examples = ["Create an Appwrite row", "Find Appwrite users", "Run an Appwrite function", "React when an Appwrite file finishes uploading"]

    @classmethod
    def get_config_model(cls):
        return AppwriteNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None, success=None):
        cred = AppwriteAPIKeyCredential.model_validate(credential)
        async with guarded_async_client(timeout=45, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, cred.endpoint + path, params=params, json=body,
                headers={"X-Appwrite-Project": cred.project_id, "X-Appwrite-Key": cred.api_key, "Accept": "application/json"})
        if response.is_error:
            try:
                message = response.json().get("message", "Request failed")
            except (ValueError, AttributeError):
                message = "Request failed"
            message = str(message).replace(cred.api_key, "[redacted]")[:1500]
            raise ValueError(f"Appwrite API error {response.status_code}: {message}")
        if success and response.status_code not in success:
            raise ValueError("Appwrite returned an unexpected response status")
        if not response.content:
            return {}
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Appwrite returned an invalid JSON object")
        return result

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Appwrite project API key")
        op = self.config.config
        name = op.operation
        if name in TRIGGERS:
            payload = (self.node_data.get("config") or {}).get("_triggerPayload")
            if not isinstance(payload, dict):
                return {"status": "success", "operation": name, "no_event": True}
            return self.resolve_trigger_payload(payload, op.model_dump())
        spec = OPERATIONS[name]
        path, params, body = spec["path"], [], {}
        for field, (wire, location, kind, required, _) in spec["fields"].items():
            value = getattr(op, field)
            if value is None:
                continue
            if kind in {"array", "object"}:
                try:
                    value = json.loads(value)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"{field} must be valid JSON") from exc
                if not isinstance(value, list if kind == "array" else dict):
                    raise ValueError(f"{field} must be a JSON {kind}")
                if kind == "array" and any(not isinstance(item, str) for item in value):
                    raise ValueError(f"{field} must contain strings")
            if location == "path":
                path = path.replace("{" + wire + "}", quote(str(value), safe=""))
            elif location == "query":
                if kind == "array":
                    params.extend((wire + "[]", item) for item in value)
                else:
                    params.append((wire, value))
            else:
                body[wire] = value
        data = await self._request(self.config.credentials.model_dump(), spec["method"], path,
            params=params, body=body if spec["method"] in {"POST", "PATCH", "PUT"} else None, success=spec["success"])
        return {"status": "success", "operation": name, "data": _safe_data(data)}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        name = config.get("operation")
        if name not in TRIGGERS:
            raise ValueError("Choose an Appwrite trigger")
        data = await cls._request(credential, "POST", "/webhooks", body={
            "webhookId": "unique()", "url": webhook_url, "name": f"NoClick {node_id}"[:128],
            "events": [TRIGGERS[name]], "enabled": True, "tls": True}, success=[201])
        if not data.get("$id") or not data.get("secret"):
            raise ValueError("Appwrite did not return a webhook ID and signing secret")
        return {"external_webhook_id": data["$id"], "signing_secret": data["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = config.get("external_webhook_id")
        if credential and identifier:
            await cls._request(credential, "DELETE", "/webhooks/" + quote(str(identifier), safe=""), success=[204])

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret, url = config.get("signing_secret"), config.get("webhook_url")
        if not secret or not url:
            return False
        supplied = next((v for k, v in headers.items() if k.lower() == "x-appwrite-webhook-signature"), "")
        digest = hmac.new(secret.encode(), url.encode() + body, hashlib.sha1).digest()
        return hmac.compare_digest(base64.b64encode(digest).decode(), supplied)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        metadata = payload.get("_webhook", {})
        headers = {k.lower(): v for k, v in metadata.get("headers", {}).items()}
        events = headers.get("x-appwrite-webhook-events", "").split(",")
        selected = TRIGGERS.get(config.get("operation"))
        if not selected or not any(fnmatch.fnmatchcase(event.strip(), selected) for event in events):
            return False
        if config.get("operation") == "on_file_uploaded":
            return (isinstance(payload.get("chunksTotal"), int) and payload["chunksTotal"] > 0
                    and payload.get("chunksUploaded") == payload["chunksTotal"])
        return True

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return {"status": "success", "no_event": True}
        headers = {k.lower(): v for k, v in payload.get("_webhook", {}).get("headers", {}).items()}
        return {"status": "success", "operation": config["operation"], "event": TRIGGERS[config["operation"]],
                "actor_id": headers.get("x-appwrite-webhook-user-id", ""),
                "project_id": headers.get("x-appwrite-webhook-project-id", ""), "data": _safe_data(payload)}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("no_event"):
            return None
        if output.get("operation") not in TRIGGERS:
            return super().resolve_agent_event(output)
        data = output.get("data", {})
        identifier = data.get("$id")
        if not identifier:
            return None
        action = output["operation"].removeprefix("on_").replace("_", " ")
        actor = output.get("actor_id") or "an API key or guest (Appwrite supplies no actor ID)"
        text = f"Appwrite {action} in project {output.get('project_id') or 'the connected project'}, by {actor}.\n"
        operation = output["operation"]
        if operation.startswith("on_row_"):
            text += f"Database {data.get('$databaseId')}, table {data.get('$tableId')}, row {identifier}.\n"
        elif operation == "on_user_created":
            text += f"User {data.get('name') or identifier}, email {data.get('email') or 'not supplied'}, user ID {identifier}.\n"
        else:
            text += f"File {data.get('name') or identifier} in bucket {data.get('bucketId')}, file ID {identifier}.\n"
        text += "Resource content:\n" + json.dumps(data, ensure_ascii=False, default=str)[:12000]
        return {"text": text, "title": f"Appwrite {action}: {identifier}", "conversation_key": str(identifier)}
