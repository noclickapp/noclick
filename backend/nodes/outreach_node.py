"""Outreach REST API v2 workflow node with OAuth 2.0 authentication."""

import hashlib
import hmac
import json
import secrets
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.outreach import OUTREACH_SCOPES
from nodes.outreach_operations import OPERATIONS, Operation

API_BASE = "https://api.outreach.io/api/v2"
API_MEDIA_TYPE = "application/vnd.api+json"


class OutreachOAuthCredential(BaseModel):
    credential_type: Literal["outreach_oauth"] = Field("outreach_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    scope: Optional[str] = Field(None, title="Granted Scopes", json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(title="Outreach Account", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "outreach",
        "x-oauth-scopes": OUTREACH_SCOPES.declared_scopes(),
        "x-credential-url": "https://developers.outreach.io/api/oauth",
    })


# Outreach's own MCP server: agents get its tools through a person's Outreach sign-in.
OutreachMcpCredential = mcp_credential("outreach", "https://api.outreach.io/mcp", app="Outreach")
OutreachCredential = Union[OutreachOAuthCredential, OutreachMcpCredential]


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for field in re.findall(r"\{([^}]+)\}", op.path):
        title = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", field).replace("_", " ").title()
        fields[field] = (str, Field(..., title=title))
    fields["query_json"] = (Optional[str], Field(
        None, title="Query Parameters JSON",
        description="Outreach API filters, sorting, pagination, action parameters, or includes as a JSON object",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    if op.body_type != "none":
        required = op.body_type == "required"
        fields["body_json"] = ((str if required else Optional[str]), Field(
            ... if required else None, title="Request JSON:API Body",
            description="Outreach JSON:API document, for example {\"data\":{\"type\":\"prospect\",\"attributes\":{...}}}",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    return create_model(
        "Outreach" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], Field(name, title=op.label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-category": op.category,
            "x-is-trigger": False, "x-display-name": op.label,
        })),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
# Resource/action pairs documented at https://developers.outreach.io/api/webhooks.
OUTREACH_WEBHOOK_EVENTS = (
    "task.completed", "prospect.created", "prospect.updated", "mailing.replied",
    "opportunity.updated", "sequenceState.finished",
)


class OutreachOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Outreach Event", json_schema_extra={
        "const": "on_event", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On Outreach Event",
    })
    event_type: Literal[*OUTREACH_WEBHOOK_EVENTS] = Field(
        "task.completed", title="Event Type",
        description="Completed tasks, new or updated prospects, replies, opportunity updates, or finished sequences")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True,
    })


OutreachConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (OutreachOnEventConfig,)], Discriminator("operation")]


class OutreachNodeConfig(NodeConfig[OutreachConfig, OutreachCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


class OutreachNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-outreach"
    credential_provider_labels = {"outreach": "Outreach Account"}
    webhook_replace_stale_endpoint = True
    scope_registry = OUTREACH_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_prospects", noun="account")
    edit_examples = [
        "List Outreach prospects", "Create an Outreach account",
        "Get Outreach sequences", "Update an Outreach opportunity", "List Outreach tasks",
    ]

    @classmethod
    def get_config_model(cls):
        return OutreachNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.outreach_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="outreach")

    @staticmethod
    def _parse_object(raw: Optional[str], label: str) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _serialize_param(value: Any) -> Any:
        if isinstance(value, list):
            return [OutreachNode._serialize_param(item) for item in value]
        if isinstance(value, (dict, bool)):
            return json.dumps(value, separators=(",", ":"))
        return "" if value is None else str(value)

    async def _authorization(self, credential: OutreachOAuthCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.outreach_oauth import refresh_access_token
        credential_data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credential_data, refresh=refresh_access_token,
            provider="outreach", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            setattr(credential, key, credential_data[key])
        return token

    @staticmethod
    async def _request(method: str, path: str, token: str,
                       params: dict[str, Any], body: Optional[dict[str, Any]]) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method, f"{API_BASE}{path}", params=params or None, json=body,
                headers={"Authorization": f"Bearer {token}",
                         "Accept": API_MEDIA_TYPE, "Content-Type": API_MEDIA_TYPE})
        if response.is_error:
            try:
                payload = response.json()
                errors = payload.get("errors", []) if isinstance(payload, dict) else []
                detail = "; ".join(str(e.get("detail") or e.get("title")) for e in errors if isinstance(e, dict))
            except ValueError:
                detail = ""
            raise ValueError(f"Outreach API error {response.status_code}: {detail or 'request failed'}")
        if not response.content:
            return {"ok": True}
        if "json" in response.headers.get("content-type", "") or response.content[:1] in (b"{", b"["):
            try:
                return response.json()
            except ValueError as exc:
                raise ValueError(f"Outreach returned invalid JSON ({response.status_code})") from exc
        return BinaryOutput(
            data=response.content,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            filename="outreach-download",
        )

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, OutreachNodeConfig):
            raise ValueError("Outreach configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Outreach account")
        config = self.config.config
        self.scope_registry.require(config.operation)
        if isinstance(config, OutreachOnEventConfig):
            payload = (self.node_data or {}).get("config", {}).get("_triggerPayload") or inputs
            if not self.filter_trigger_payload(payload, config.model_dump()):
                raise ValueError("Waiting for a matching Outreach webhook event")
            return self.resolve_trigger_payload(payload, config.model_dump())
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        for field in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        params = {key: self._serialize_param(value) for key, value in
                  self._parse_object(values.pop("query_json", None), "Query Parameters JSON").items()}
        raw_body = values.pop("body_json", None) if op.body_type != "none" else None
        body = self._parse_object(raw_body, "Request JSON:API Body") if raw_body is not None else None
        token = await self._authorization(credential)
        data = await self._request(op.method, path, token, params, body)
        return {"status": "success", "operation": config.operation, "data": data}


    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "task.completed")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event_type = (config or {}).get("event_type", "task.completed")
        if event_type not in OUTREACH_WEBHOOK_EVENTS:
            raise ValueError("Choose a supported Outreach event")
        token = credential.get("access_token")
        if not token:
            raise ValueError("Connect Outreach before activating this trigger")
        cls.scope_registry.require("on_event")
        resource, action = event_type.split(".", 1)
        secret = secrets.token_urlsafe(32)
        document = await cls._request("POST", "/webhooks", token, {}, {
            "data": {"type": "webhook", "attributes": {
                "action": action, "resource": resource, "url": webhook_url, "secret": secret,
            }},
        })
        record = document.get("data") if isinstance(document, dict) else None
        endpoint_id = record.get("id") if isinstance(record, dict) else None
        if not endpoint_id:
            raise ValueError("Outreach did not return a webhook ID")
        return {"external_webhook_id": str(endpoint_id), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if not endpoint_id:
            return
        if not credential or not credential.get("access_token"):
            raise ValueError("Connect Outreach to remove its webhook")
        try:
            await cls._request("DELETE", "/webhooks/" + quote(str(endpoint_id), safe=""),
                               credential["access_token"], {}, None)
        except ValueError as exc:
            if not str(exc).startswith("Outreach API error 404:"):
                raise

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        supplied = next((v for k, v in headers.items() if k.lower() == "outreach-webhook-signature"), "")
        if not secret or not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied):
            return False
        expected = hmac.new(str(secret).encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        if not isinstance(payload, dict):
            return False
        record, meta = payload.get("data"), payload.get("meta")
        if not isinstance(record, dict) or not isinstance(meta, dict):
            return False
        event_type = (config or {}).get("event_type", "task.completed")
        return (event_type in OUTREACH_WEBHOOK_EVENTS
                and meta.get("eventName") == event_type
                and record.get("type") == event_type.split(".", 1)[0]
                and isinstance(record.get("id"), (int, str)) and bool(record["id"]))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": "on_event",
                "data": payload["data"], "meta": payload["meta"]}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") != "on_event":
            return super().resolve_agent_event(output)
        record, meta = output.get("data"), output.get("meta")
        if not isinstance(record, dict) or not isinstance(meta, dict):
            return None
        resource, record_id = record.get("type"), record.get("id")
        event_type = meta.get("eventName")
        if not resource or record_id is None or event_type not in OUTREACH_WEBHOOK_EVENTS:
            return None
        # Only changed attributes are delivered. The event need not include an
        # actor, owner or subject; preserve the provider's content without
        # guessing one or reading fields absent from the delivery contract.
        attributes = record.get("attributes", {})
        text = (f"Outreach {event_type}: {resource} {record_id}\n"
                f"Delivered at: {meta.get('deliveredAt', '')}\n"
                f"Changed attributes: {json.dumps(attributes, ensure_ascii=False)}\n"
                f"To act: use the Outreach {resource} operations with id={record_id}.")
        return {"text": text, "conversation_key": f"{resource}:{record_id}",
                "title": f"Outreach {event_type} · {record_id}"}
