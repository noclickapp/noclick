"""Webex actions and signed message, meeting, and recording event triggers."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.webex import WEBEX_SCOPES
from nodes.webex_operations import WEBEX_CATALOG


_catalog = WEBEX_CATALOG
OPERATIONS: dict[str, dict[str, Any]] = {op["name"]: op for op in _catalog["operations"]}
assert len(OPERATIONS) == len(_catalog["operations"]), "Duplicate Webex operation"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
_BASE_URL = "https://webexapis.com/v1"
WEBEX_OAUTH_SCOPES = WEBEX_SCOPES.declared_scopes()


class WebexOAuthCredential(BaseModel):
    """User delegated Webex token, refreshed by the workflow runtime."""

    credential_type: Literal["webex_oauth"] = Field(
        "webex_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Expiration")
    user_id: Optional[str] = Field(None, title="Webex User ID")
    email: Optional[str] = Field(None, title="Email")

    model_config = ConfigDict(title="Webex Account", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "webex",
        "x-oauth-scopes": WEBEX_OAUTH_SCOPES,
        "x-credential-url": "https://developer.webex.com/my-apps/new/integration",
        "x-credential-instructions": "Connect your Webex account to use spaces, messages, meetings, and recordings.",
    })


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={
                "const": name, "ui:hidden": True,
                "x-category": op["category"], "x-display-name": op["label"],
                "x-is-trigger": False,
            },
        )),
    }
    for raw in op["path_params"]:
        fields[_field_name("path", raw)] = (
            str, Field(..., title=re.sub(r"(?<!^)(?=[A-Z])", " ", raw).title()),
        )
    for raw in op["required_query"]:
        fields[_field_name("query", raw)] = (str, Field(..., title=raw.replace("_", " ").title()))
    fields["query_json"] = (
        Optional[str], Field(None, title="Other Query Parameters (JSON)",
                             description="Optional filters and pagination from the Webex API reference.",
                             json_schema_extra=_JSON_EDITOR),
    )
    if op["body_type"] == "application/json":
        description = "JSON request body from the Webex API reference."
        if op["body_required_fields"]:
            description += " Required keys: " + ", ".join(op["body_required_fields"]) + "."
        required = op["body_required"] or bool(op["body_required_fields"])
        fields["body_json"] = (
            str if required else Optional[str],
            Field(... if required else None, title="Request Body (JSON)",
                  description=description, json_schema_extra=_JSON_EDITOR),
        )
    return create_model(
        "Webex" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})

# Registration: the pinned Webex Messaging OpenAPI's POST /webhooks.
# Event bodies: https://developer.webex.com/docs/receive-and-verify-webhooks,
# https://developer.webex.com/meeting/docs/api/guides/access-meeting-resources-guide,
# https://developer.webex.com/blog/webex-rest-api-adds-compliance-officer-webhooks.
TRIGGER_EVENTS = {
    "on_new_message": ("messages", "created"),
    "on_meeting_ended": ("meetings", "ended"),
    "on_new_recording": ("recordings", "created"),
}


class WebexWebhookConfig(WebhookTriggerConfigBase):
    webhook_url: Optional[str] = Field(
        None, title="Webhook URL", description="Registered with Webex automatically",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class WebexOnNewMessageConfig(WebexWebhookConfig):
    operation: Literal["on_new_message"] = Field("on_new_message", title="On New Message", json_schema_extra={
        "const": "on_new_message", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Message",
    })
    room_id: Optional[str] = Field(None, title="Space ID", description="Watch one space, or leave blank for all accessible spaces")


class WebexOnMeetingEndedConfig(WebexWebhookConfig):
    operation: Literal["on_meeting_ended"] = Field("on_meeting_ended", title="On Meeting Ended", json_schema_extra={
        "const": "on_meeting_ended", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On Meeting Ended",
    })


class WebexOnNewRecordingConfig(WebexWebhookConfig):
    operation: Literal["on_new_recording"] = Field("on_new_recording", title="On New Recording", json_schema_extra={
        "const": "on_new_recording", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Recording",
    })
    meeting_id: Optional[str] = Field(None, title="Meeting ID", description="Watch recordings for one meeting, or leave blank for all your recordings")


TRIGGER_CONFIGS = (WebexOnNewMessageConfig, WebexOnMeetingEndedConfig, WebexOnNewRecordingConfig)
WebexConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + TRIGGER_CONFIGS], Discriminator("operation")]


class WebexNodeConfig(NodeConfig[WebexConfig, WebexOAuthCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: Optional[str], label: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc


class WebexNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Run Webex actions or subscribe workflows and agents to Webex events."""

    integration_type = "automation-webex"
    scope_registry = WEBEX_SCOPES
    webhook_replace_stale_endpoint = True
    connection_evidence = ConnectionEvidence(
        operation="list_rooms", noun="spaces",
        identity_operation="get_my_own_details",
    )
    edit_examples = [
        "List my Webex spaces", "Post a message to a Webex space",
        "Schedule a Webex meeting", "List my Webex recordings",
        "Start an agent when a Webex message arrives", "Follow up after a Webex meeting ends",
    ]

    @classmethod
    def get_config_model(cls):
        return WebexNodeConfig

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = TRIGGER_EVENTS.get(config.get("operation"))
        if event is None:
            raise ValueError("Choose a Webex trigger before registering a webhook")
        if not credential or not credential.get("access_token"):
            raise ValueError("Connect Webex before activating this trigger")
        secret = secrets.token_hex(32)
        body = {"name": f"NoClick {node_id}", "targetUrl": webhook_url,
                "resource": event[0], "event": event[1], "secret": secret}
        filters = cls.registration_fingerprint_fields(config)
        if filters.get("room_id"):
            body["filter"] = "roomId=" + str(filters["room_id"])
        if filters.get("meeting_id"):
            body["filter"] = "meetingId=" + str(filters["meeting_id"])
        result = await cls._request(credential["access_token"], "webhooks_create_a_webhook", {"body_json": json.dumps(body)})
        endpoint_id = result["data"].get("id")
        if not endpoint_id:
            raise ValueError("Webex did not return a webhook ID")
        return {"external_webhook_id": str(endpoint_id), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = config.get("external_webhook_id")
        if not endpoint_id:
            return
        if not credential or not credential.get("access_token"):
            raise ValueError("Connect Webex to remove its webhook")
        try:
            await cls._request(credential["access_token"], "webhooks_delete_a_webhook", {"path_webhookid": endpoint_id})
        except ValueError as exc:
            if not str(exc).startswith("Webex API error 404:"):
                raise

    @classmethod
    def registration_fingerprint_fields(cls, config):
        if config.get("operation") == "on_new_message":
            return {"room_id": config.get("room_id") or None}
        if config.get("operation") == "on_new_recording":
            return {"meeting_id": config.get("meeting_id") or None}
        return {}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # https://developer.webex.com/docs/receive-and-verify-webhooks#authenticating-requests
        secret = config.get("signing_secret")
        if not secret:
            return False
        headers = {key.lower(): value for key, value in headers.items()}
        if "x-webex-signature" in headers:
            for pair in headers["x-webex-signature"].split(","):
                algorithm, sep, received = pair.strip().partition("=")
                digest = {"SHA-256": hashlib.sha256, "SHA-512": hashlib.sha512}.get(algorithm)
                if (sep and digest and re.fullmatch(r"[0-9a-f]+", received)
                        and hmac.compare_digest(hmac.new(secret.encode(), body, digest).hexdigest(), received)):
                    return True
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
        received = headers.get("x-spark-signature", "")
        return bool(re.fullmatch(r"[0-9a-f]{40}", received)) and hmac.compare_digest(expected, received)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = TRIGGER_EVENTS.get(config.get("operation"))
        if event is None or (payload.get("resource"), payload.get("event")) != event:
            return False
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            return False
        if event[0] == "messages" and config.get("room_id"):
            return data.get("roomId") == config["room_id"]
        if event[0] == "recordings" and config.get("meeting_id"):
            return data.get("meetingId") == config["meeting_id"]
        return True

    @classmethod
    async def transform_trigger_payload(cls, payload, config, *, pool, workflow_id, node_id):
        # Enrich before either workflows or platform agents receive the event.
        # A failed read leaves the metadata usable via the family's fallback.
        if config.get("operation") != "on_new_message" or not workflow_id:
            return None
        from utils.inbound_media import resolve_delivery_credential

        credential, owner_id = await resolve_delivery_credential(pool, config, str(workflow_id), "webex_oauth")
        if not credential:
            return None
        credential = await cls.freshen_credential(
            credential, pool=pool, user_id=owner_id,
            credential_id=(config.get("credentialIds") or {}).get("webex_oauth"),
        )
        result = await cls._request(credential["access_token"], "messages_get_message_details",
                                    {"path_messageid": payload["data"]["id"]})
        return {**payload, "_message": result["data"]}

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        # Keep delivery headers out of the wrapped output and carry enriched
        # message content once, beside the provider's unchanged event fields.
        envelope = {key: value for key, value in payload.items() if key not in {"_webhook", "_message"}}
        return {"status": "success", "operation": config.get("operation"), "data": envelope,
                "message": payload.get("_message")}

    @classmethod
    def resolve_agent_event(cls, output):
        if isinstance(output, dict) and output.get("status") == "no_event":
            return None
        if not isinstance(output, dict) or output.get("operation") not in TRIGGER_EVENTS:
            return super().resolve_agent_event(output)
        envelope = output.get("data") or {}
        data = envelope.get("data") or {}
        if not isinstance(data, dict) or not data.get("id"):
            return None
        item_id = data["id"]
        operation = output["operation"]
        if operation == "on_new_message":
            message = output.get("message") or {}
            who = data.get("personEmail") or data.get("personId")
            room = data.get("roomId")
            lines = [f"New Webex message from {who} in space {room}",
                     str(message.get("text") or "Message content is unavailable; retrieve it using the message ID."),
                     f"Message ID: {item_id}", f"Space ID: {room}", f"Sent: {data.get('created')}",
                     f"To reply: messages_create_a_message with body_json containing roomId={room} and text."]
            key, title = room or item_id, f"Webex message from {who}"
        elif operation == "on_meeting_ended":
            lines = [f"Webex meeting ended, hosted by {data.get('hostEmail')} at {data.get('siteUrl')}",
                     f"Started: {data.get('start')}; ended: {data.get('end')}", f"Meeting ID: {item_id}",
                     f"To find recordings: recordings_listrecordings with query_json containing meetingId={item_id}."]
            key, title = item_id, "Webex meeting ended"
        else:
            meeting = data.get("meetingId")
            lines = [f"New Webex recording at {data.get('siteUrl')}, hosted by user {data.get('hostUserId')}",
                     f"Recording ID: {item_id}", f"Meeting ID: {meeting}",
                     f"Created: {data.get('createTime')}; format: {data.get('format')}; duration: {data.get('durationSeconds')} seconds",
                     f"To retrieve it: recordings_getrecordbyrecordid path_recordingid={item_id}."]
            key, title = meeting or item_id, "New Webex recording"
        return {"text": "\n".join(lines), "conversation_key": str(key), "title": title}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data or credential_data.get("credential_type") != "webex_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.webex_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="webex",
        )

    async def _access_token(self, credential: WebexOAuthCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.webex_oauth import refresh_access_token

        data = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=data,
            refresh=refresh_access_token, provider="webex", caller_path="execute",
        )
        credential.access_token = data["access_token"]
        credential.refresh_token = data.get("refresh_token") or credential.refresh_token
        credential.expires_at = data.get("expires_at")
        return credential.access_token

    @staticmethod
    async def _request(token: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
        op = OPERATIONS[name]
        path = op["path"]
        for raw in op["path_params"]:
            value = values.pop(_field_name("path", raw), None)
            if value is None or str(value).strip() in {"", ".", ".."}:
                raise ValueError(f"{raw} is required")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        params = _parse_json(values.pop("query_json", None), "Query Parameters") or {}
        if not isinstance(params, dict):
            raise ValueError("Query Parameters must be a JSON object")
        for raw in op["required_query"]:
            params[raw] = values.pop(_field_name("query", raw))
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        kwargs: dict[str, Any] = {}
        if op["body_type"] == "application/json":
            body = _parse_json(values.pop("body_json", None), "Request Body")
            if op["body_required"] and body is None:
                raise ValueError("Request Body is required")
            missing = [key for key in op["body_required_fields"]
                       if not isinstance(body, dict) or key not in body]
            if missing:
                raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
            if body is not None:
                kwargs["json"] = body
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(op["method"], _BASE_URL + path,
                                            params=params or None, headers=headers, **kwargs)
        if not response.content:
            data: Any = {}
        elif response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
        else:
            try:
                data = response.json()
            except ValueError:
                data = BinaryOutput(
                    data=response.content,
                    content_type=response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip() or "application/octet-stream",
                    filename=f"webex-{name}",
                )
        if response.is_error or response.is_redirect:
            detail = data.get("message") or data.get("error") if isinstance(data, dict) else None
            raise ValueError(f"Webex API error {response.status_code}: {detail or 'request failed'}")
        return {
            "status": "success", "operation": name, "status_code": response.status_code,
            "data": data, "next_page": response.links.get("next", {}).get("url"),
            "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, WebexNodeConfig):
            raise ValueError("Webex configuration required")
        config = self.config.config
        if config.operation in TRIGGER_EVENTS:
            return self.no_event_output(config.operation)
        if not isinstance(self.config, WebexNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Webex account before running this action")
        credential = self.config.credentials
        token = await self._access_token(credential)
        config = self.config.config
        return await self._request(token, config.operation, config.model_dump(exclude_none=True))
