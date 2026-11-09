"""Bubbles personal-token API operations and signed meeting-ready deliveries.

Routes and request fields follow the published v2.137.0 OpenAPI contract;
the webhook envelope and replay protection follow the provider's webhook guide.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.usebubbles.com"
EVENTS = ("bubble.ready", "meeting_recording.ready", "screen_recording.ready")
Event = Literal["bubble.ready", "meeting_recording.ready", "screen_recording.ready"]


class BubblesTokenCredential(BaseModel):
    model_config = ConfigDict(title="Bubbles Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.usebubbles.com/?settings=apikeys",
            "x-credential-instructions": "In Bubbles, open Settings → Personal → API keys, create a key, and paste it here. Creating a key and using webhooks require a paid workspace. Personal access tokens include the API scopes automatically.",
        })
    credential_type: Literal["bubbles_token"] = Field("bubbles_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="Personal access token",
        json_schema_extra={"ui:widget": "password", "ui:placeholder": "bbls_pat_…"})


def text(title, *, required=False, description=None):
    return (str if required else str | None, Field(... if required else None, title=title,
        min_length=1, description=description))


PAGING = {
    "limit": (int, Field(25, ge=1, le=100, title="Page size")),
    "cursor": text("Page cursor", description="Use next_cursor from the previous response; leave empty for the first page."),
}
FILTERS = {
    "team_id": text("Team ID"), "space_id": text("Space ID"),
    "type": (Literal["meeting_recording", "screen_recording", "custom_image"] | None, Field(None, title="Bubble type")),
    "created_after": text("Created after", description="Exclusive ISO-8601 timestamp."),
    "created_before": text("Created before", description="Exclusive ISO-8601 timestamp."),
}
BUBBLE_ID = {"bubble_id": text("Bubble ID", required=True)}
WEBHOOK_ID = {"webhook_id": text("Subscription ID", required=True)}
WEBHOOK_URL = (str, Field(..., title="Receiver URL", pattern=r"^https://[^\s]+$"))

# Each non-trigger operation maps to one published method/path, including paging.
OPERATIONS = {
    "get_me": ("Get My Account", "Account", "GET", "/v1/me", {}),
    "list_teams": ("List Teams and Spaces", "Account", "GET", "/v1/teams", {}),
    "list_bubbles": ("List Bubbles", "Bubbles", "GET", "/v1/bubbles", {**FILTERS, **PAGING}),
    "search_bubbles": ("Search Bubbles", "Bubbles", "GET", "/v1/bubbles/search", {
        **FILTERS, **PAGING, "q": (str, Field(..., min_length=1, max_length=256, title="Search query"))}),
    "get_bubble": ("Get Bubble, Summary and Action Items", "Bubbles", "GET", "/v1/bubbles/{bubble_id}", BUBBLE_ID),
    "get_transcript": ("Get Transcript", "Bubbles", "GET", "/v1/bubbles/{bubble_id}/transcript", {
        **BUBBLE_ID, "format": (Literal["json", "text"], Field("json", title="Transcript format"))}),
    "list_comments": ("List Bubble Comments", "Bubbles", "GET", "/v1/bubbles/{bubble_id}/comments", {**BUBBLE_ID, **PAGING}),
    "join_meeting": ("Send Notetaker to Meeting", "Meetings", "POST", "/v1/meetings/join", {
        "meeting_url": text("Meeting URL", required=True, description="A Google Meet, Microsoft Teams, Zoom, Webex or GoTo meeting link. Sends a recording bot to the meeting."),
        "team_id": text("Team ID", required=True)}),
    "get_meeting_join": ("Get Notetaker Status", "Meetings", "GET", "/v1/meetings/join/{join_id}", {"join_id": text("Meeting join ID", required=True)}),
    "list_webhooks": ("List Webhook Subscriptions", "Webhooks", "GET", "/v1/webhooks", {}),
    "get_webhook": ("Get Webhook Subscription", "Webhooks", "GET", "/v1/webhooks/{webhook_id}", WEBHOOK_ID),
    "create_webhook": ("Create Webhook Subscription", "Webhooks", "POST", "/v1/webhooks", {
        "url": WEBHOOK_URL, "event_type": (Event, Field("meeting_recording.ready", title="Event")),
        "team_id": text("Team ID"), "space_id": text("Space ID")}),
    "update_webhook": ("Update Webhook Subscription", "Webhooks", "PATCH", "/v1/webhooks/{webhook_id}", {
        **WEBHOOK_ID, "url": (str | None, Field(None, title="Receiver URL", pattern=r"^https://[^\s]+$")),
        "event_type": (Event | None, Field(None, title="Replace event")),
        "status": (Literal["active"] | None, Field(None, title="Re-enable subscription"))}),
    "delete_webhook": ("Delete Webhook Subscription", "Webhooks", "DELETE", "/v1/webhooks/{webhook_id}", WEBHOOK_ID),
    "test_webhook": ("Send Test Webhook", "Webhooks", "POST", "/v1/webhooks/{webhook_id}/test", WEBHOOK_ID),
}


def _config(name, spec):
    label, category, _, _, fields = spec
    return create_model("Bubbles" + "".join(p.title() for p in name.split("_")) + "Config",
        __module__=__name__, __config__=ConfigDict(extra="forbid"),
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})),
        **fields)


CONFIGS = tuple(_config(name, spec) for name, spec in OPERATIONS.items())
globals().update({model.__name__: model for model in CONFIGS})


class BubblesOnMeetingReadyConfig(WebhookTriggerConfigBase):
    operation: Literal["on_meeting_ready"] = Field("on_meeting_ready", title="On Meeting Recording Ready",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
            "x-display-name": "On Meeting Recording Ready"})
    team_id: str | None = Field(None, title="Team ID", description="Leave empty for all your teams.")
    space_id: str | None = Field(None, title="Space ID", description="Leave empty for all visible spaces.")
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with Bubbles automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


BubblesOperation = Annotated[Union[CONFIGS + (BubblesOnMeetingReadyConfig,)], Field(discriminator="operation")]


class BubblesNodeConfig(NodeConfig[BubblesOperation, BubblesTokenCredential]):
    pass


class BubblesNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-bubbles"
    connection_evidence = ConnectionEvidence(noun="teams", operation="list_teams", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return BubblesNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            detail = "Request failed"
            try:
                detail = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                pass
            raise ValueError(f"Bubbles API {response.status_code}: {str(detail).replace(token, '[redacted]')}")
        if response.status_code == 204:
            return {"deleted": True}
        if response.status_code == 202:
            return {"queued": True}
        data = response.json()
        if not isinstance(data, dict) or "error" in data:
            raise ValueError("Unexpected Bubbles response")
        return data

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        body = {"url": webhook_url, "events": ["meeting_recording.ready"]}
        body.update({k: config[k] for k in ("team_id", "space_id") if config.get(k)})
        result = await cls._request(credential["api_token"], "POST", "/v1/webhooks", body=body)
        if not result.get("id") or not result.get("secret"):
            raise ValueError("Bubbles did not return the subscription ID and signing secret")
        return {"external_webhook_id": result["id"], "signing_secret": result["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if config.get("external_webhook_id"):
            await cls._request(credential["api_token"], "DELETE",
                "/v1/webhooks/" + quote(str(config["external_webhook_id"]), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {k: config.get(k) for k in ("team_id", "space_id")}

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        secret = config.get("signing_secret")
        header = next((v for k, v in headers.items() if k.lower() == "x-bubbles-signature"), "")
        parts = dict(p.strip().split("=", 1) for p in header.split(",") if "=" in p)
        timestamp, signature = parts.get("t", ""), parts.get("v1", "")
        if not secret or not re.fullmatch(r"[0-9]{1,12}", timestamp) or abs(int(time.time()) - int(timestamp)) > 300:
            return False
        if not re.fullmatch(r"[a-fA-F0-9]{64}", signature):
            return False
        expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.lower())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("type") == "meeting_recording.ready"

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        event = output["data"] if "operation" in output and output["operation"] == "on_meeting_ready" else output
        if not isinstance(event, dict) or event.get("type") != "meeting_recording.ready":
            return None
        bubble = event.get("data", {}).get("bubble", {})
        if not bubble.get("id"):
            return None
        title = bubble.get("title") or "Meeting recording"
        text = (f"Bubbles meeting recording ready: {title}\n"
            f"Recorded meeting: {bubble.get('url', '')}\n"
            f"At: {event.get('created_at', '')}; event ID: {event.get('id', '')}\n"
            f"Bubble ID: {bubble['id']}. Use get_bubble for the full summary, action items and participants, "
            f"or get_transcript and list_comments with bubble_id={bubble['id']}.")
        return {"text": text[:4000], "conversation_key": str(bubble["id"]), "title": str(title)[:200]}

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Bubbles personal access token")
        config = self.config.config
        name = config.operation
        if name == "on_meeting_ready":
            return self.no_event_output(name)
        _, _, method, path, _ = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        if "event_type" in values:
            values["events"] = [values.pop("event_type")]
        data = await self._request(self.config.credentials.api_token, method, path,
            params=values if method == "GET" else None,
            body=values if method in ("POST", "PATCH") else None)
        return {"status": "success", "operation": name, "data": data}
