"""Kit (formerly ConvertKit) V4 workflow operations.

Routes and request shapes are from https://developers.kit.com/api-reference/.
The declarative operation table keeps the workflow form and HTTP dispatch in sync.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.kit import KIT_SCOPES
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    fields: dict[str, tuple[Any, Any]]
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    json_fields: tuple[str, ...] = ()
    creates: Optional[str] = None


def text_field(title: str, *, required: bool = False, description: str = "", multiline: bool = False):
    return (str if required else Optional[str], Field(
        ... if required else None, title=title, description=description,
        json_schema_extra={"ui:widget": "textarea"} if multiline else None))


def int_field(title: str, *, required: bool = False):
    return (int if required else Optional[int], Field(... if required else None, title=title))


def bool_field(title: str):
    return (Optional[bool], Field(None, title=title))


PAGINATION = {"after": text_field("After Cursor"), "per_page": int_field("Page Size")}
SUBSCRIBER_ID = {"subscriber_id": int_field("Subscriber ID", required=True)}
TAG_ID = {"tag_id": int_field("Tag ID", required=True)}
FORM_ID = {"form_id": int_field("Form ID", required=True)}
SEQUENCE_ID = {"sequence_id": int_field("Sequence ID", required=True)}
BROADCAST_ID = {"broadcast_id": int_field("Broadcast ID", required=True)}
FIELD_ID = {"field_id": int_field("Custom Field ID", required=True)}
WEBHOOK_ID = {"webhook_id": int_field("Webhook Endpoint ID", required=True)}


OPERATIONS: dict[str, Operation] = {
    "get_account": Operation("Get Current Account", "Account", "GET", "/account", {}),
    "get_creator_profile": Operation("Get Creator Profile", "Account", "GET", "/account/creator_profile", {}),
    "get_email_stats": Operation("Get Email Stats", "Account", "GET", "/account/email_stats", {}),
    "get_growth_stats": Operation("Get Growth Stats", "Account", "GET", "/account/growth_stats", {
        "starting": text_field("Start Date"), "ending": text_field("End Date")}, query=("starting", "ending")),
    "list_subscribers": Operation("List Subscribers", "Subscribers", "GET", "/subscribers", {
        **PAGINATION, "email_address": text_field("Exact Email Address"),
        "status": text_field("Status", description="active, inactive, bounced, complained, cancelled, or all")},
        query=("after", "per_page", "email_address", "status")),
    "get_subscriber": Operation("Get Subscriber", "Subscribers", "GET", "/subscribers/{subscriber_id}", SUBSCRIBER_ID),
    "create_subscriber": Operation("Create Subscriber", "Subscribers", "POST", "/subscribers", {
        "email_address": text_field("Email Address", required=True), "first_name": text_field("First Name"),
        "state": text_field("State"), "fields_json": text_field("Custom Fields JSON", multiline=True)},
        body=("email_address", "first_name", "state", "fields_json"), json_fields=("fields_json",), creates="kit_subscriber"),
    "update_subscriber": Operation("Update Subscriber", "Subscribers", "PUT", "/subscribers/{subscriber_id}", {
        **SUBSCRIBER_ID, "email_address": text_field("Email Address", required=True),
        "first_name": text_field("First Name"), "fields_json": text_field("Custom Fields JSON", multiline=True)},
        body=("email_address", "first_name", "fields_json"), json_fields=("fields_json",)),
    "unsubscribe_subscriber": Operation("Unsubscribe Subscriber", "Subscribers", "POST", "/subscribers/{subscriber_id}/unsubscribe", SUBSCRIBER_ID),
    "get_subscriber_stats": Operation("Get Subscriber Stats", "Subscribers", "GET", "/subscribers/{subscriber_id}/stats", SUBSCRIBER_ID),
    "list_subscriber_tags": Operation("List Subscriber Tags", "Subscribers", "GET", "/subscribers/{subscriber_id}/tags", {
        **SUBSCRIBER_ID, **PAGINATION}, query=("after", "per_page")),
    "list_tags": Operation("List Tags", "Tags", "GET", "/tags", PAGINATION, query=("after", "per_page")),
    "create_tag": Operation("Create Tag", "Tags", "POST", "/tags", {
        "name": text_field("Tag Name", required=True)}, body=("name",), creates="kit_tag"),
    "update_tag": Operation("Rename Tag", "Tags", "PUT", "/tags/{tag_id}", {
        **TAG_ID, "name": text_field("New Tag Name", required=True)}, body=("name",)),
    "list_tag_subscribers": Operation("List Tag Subscribers", "Tags", "GET", "/tags/{tag_id}/subscribers", {
        **TAG_ID, **PAGINATION, "status": text_field("Status")}, query=("after", "per_page", "status")),
    "tag_subscriber": Operation("Tag Subscriber", "Tags", "POST", "/tags/{tag_id}/subscribers/{subscriber_id}", {
        **TAG_ID, **SUBSCRIBER_ID}),
    "untag_subscriber": Operation("Remove Subscriber Tag", "Tags", "DELETE", "/tags/{tag_id}/subscribers/{subscriber_id}", {
        **TAG_ID, **SUBSCRIBER_ID}),
    "tag_subscriber_by_email": Operation("Tag Subscriber by Email", "Tags", "POST", "/tags/{tag_id}/subscribers", {
        **TAG_ID, "email_address": text_field("Email Address", required=True)}, body=("email_address",)),
    "list_forms": Operation("List Forms", "Forms", "GET", "/forms", {
        **PAGINATION, "status": text_field("Status"), "type": text_field("Type", description="embed or hosted")},
        query=("after", "per_page", "status", "type")),
    "list_form_subscribers": Operation("List Form Subscribers", "Forms", "GET", "/forms/{form_id}/subscribers", {
        **FORM_ID, **PAGINATION, "status": text_field("Status")}, query=("after", "per_page", "status")),
    "add_subscriber_to_form": Operation("Add Subscriber to Form", "Forms", "POST", "/forms/{form_id}/subscribers/{subscriber_id}", {
        **FORM_ID, **SUBSCRIBER_ID, "referrer": text_field("Referrer URL", required=True)}, body=("referrer",)),
    "add_email_to_form": Operation("Add Email to Form", "Forms", "POST", "/forms/{form_id}/subscribers", {
        **FORM_ID, "email_address": text_field("Email Address", required=True)}, body=("email_address",)),
    "list_sequences": Operation("List Sequences", "Sequences", "GET", "/sequences", PAGINATION, query=("after", "per_page")),
    "create_sequence": Operation("Create Sequence", "Sequences", "POST", "/sequences", {
        "name": text_field("Sequence Name", required=True)}, body=("name",), creates="kit_sequence"),
    "get_sequence": Operation("Get Sequence", "Sequences", "GET", "/sequences/{sequence_id}", SEQUENCE_ID),
    "update_sequence": Operation("Update Sequence", "Sequences", "PUT", "/sequences/{sequence_id}", {
        **SEQUENCE_ID, "name": text_field("Name"), "active": bool_field("Active"),
        "repeat": bool_field("Allow Reentry"), "hold": bool_field("Keep Subscribers Active")},
        body=("name", "active", "repeat", "hold")),
    "delete_sequence": Operation("Delete Sequence", "Sequences", "DELETE", "/sequences/{sequence_id}", SEQUENCE_ID),
    "list_sequence_subscribers": Operation("List Sequence Subscribers", "Sequences", "GET", "/sequences/{sequence_id}/subscribers", {
        **SEQUENCE_ID, **PAGINATION, "status": text_field("Status")}, query=("after", "per_page", "status")),
    "add_subscriber_to_sequence": Operation("Add Subscriber to Sequence", "Sequences", "POST", "/sequences/{sequence_id}/subscribers/{subscriber_id}", {
        **SEQUENCE_ID, **SUBSCRIBER_ID}),
    "add_email_to_sequence": Operation("Add Email to Sequence", "Sequences", "POST", "/sequences/{sequence_id}/subscribers", {
        **SEQUENCE_ID, "email_address": text_field("Email Address", required=True)}, body=("email_address",)),
    "list_sequence_emails": Operation("List Sequence Emails", "Sequences", "GET", "/sequences/{sequence_id}/emails", SEQUENCE_ID),
    "create_sequence_email": Operation("Create Sequence Email", "Sequences", "POST", "/sequences/{sequence_id}/emails", {
        **SEQUENCE_ID, "subject": text_field("Subject", required=True), "content": text_field("HTML Content", multiline=True),
        "delay_value": int_field("Delay", required=True), "delay_unit": text_field("Delay Unit", required=True),
        "published": bool_field("Published")},
        body=("subject", "content", "delay_value", "delay_unit", "published"), creates="kit_sequence_email"),
    "get_sequence_email": Operation("Get Sequence Email", "Sequences", "GET", "/sequences/{sequence_id}/emails/{email_id}", {
        **SEQUENCE_ID, "email_id": int_field("Sequence Email ID", required=True)}),
    "list_broadcasts": Operation("List Broadcasts", "Broadcasts", "GET", "/broadcasts", {
        **PAGINATION, "status": text_field("Status")}, query=("after", "per_page", "status")),
    "get_broadcast": Operation("Get Broadcast", "Broadcasts", "GET", "/broadcasts/{broadcast_id}", BROADCAST_ID),
    "create_broadcast_draft": Operation("Create Broadcast Draft", "Broadcasts", "POST", "/broadcasts", {
        "subject": text_field("Subject", required=True), "content": text_field("HTML Content", required=True, multiline=True),
        "published_at": text_field("Published Timestamp", required=True,
                                   description="Display timestamp in ISO8601 format; the broadcast remains a draft"),
        "description": text_field("Internal Description"), "preview_text": text_field("Preview Text"),
        "subscriber_filter_json": text_field("Subscriber Filter JSON", multiline=True)},
        body=("subject", "content", "published_at", "description", "preview_text", "subscriber_filter_json"),
        json_fields=("subscriber_filter_json",), creates="kit_broadcast"),
    "get_broadcast_stats": Operation("Get Broadcast Stats", "Broadcasts", "GET", "/broadcasts/{broadcast_id}/stats", BROADCAST_ID),
    "get_broadcast_clicks": Operation("Get Broadcast Link Clicks", "Broadcasts", "GET", "/broadcasts/{broadcast_id}/clicks", BROADCAST_ID),
    "delete_broadcast": Operation("Delete Broadcast", "Broadcasts", "DELETE", "/broadcasts/{broadcast_id}", BROADCAST_ID),
    "list_custom_fields": Operation("List Custom Fields", "Custom Fields", "GET", "/custom_fields", PAGINATION, query=("after", "per_page")),
    "create_custom_field": Operation("Create Custom Field", "Custom Fields", "POST", "/custom_fields", {
        "label": text_field("Field Label", required=True)}, body=("label",), creates="kit_custom_field"),
    "update_custom_field": Operation("Rename Custom Field", "Custom Fields", "PUT", "/custom_fields/{field_id}", {
        **FIELD_ID, "label": text_field("New Label", required=True)}, body=("label",)),
    "delete_custom_field": Operation("Delete Custom Field", "Custom Fields", "DELETE", "/custom_fields/{field_id}", FIELD_ID),
    "list_webhooks": Operation("List Webhook Endpoints", "Webhooks", "GET", "/webhook_endpoints", {
        **PAGINATION, "status": text_field("Status")}, query=("after", "per_page", "status")),
    "get_webhook": Operation("Get Webhook Endpoint", "Webhooks", "GET", "/webhook_endpoints/{webhook_id}", WEBHOOK_ID),
    "create_webhook": Operation("Create Webhook Endpoint", "Webhooks", "POST", "/webhook_endpoints", {
        "url": text_field("Delivery URL", required=True),
        "events": text_field("Events", required=True, description="Comma-separated Kit event names"),
        "name": text_field("Name"), "description": text_field("Description")},
        body=("url", "events", "name", "description"), creates="kit_webhook_endpoint"),
    "update_webhook": Operation("Update Webhook Endpoint", "Webhooks", "PATCH", "/webhook_endpoints/{webhook_id}", {
        **WEBHOOK_ID, "url": text_field("Delivery URL"), "events": text_field("Events", description="Comma-separated Kit event names"),
        "name": text_field("Name"), "description": text_field("Description"), "status": text_field("Status")},
        body=("url", "events", "name", "description", "status")),
    "delete_webhook": Operation("Delete Webhook Endpoint", "Webhooks", "DELETE", "/webhook_endpoints/{webhook_id}", WEBHOOK_ID),
}

class KitOAuthCredential(BaseModel):
    credential_type: Literal["kit_oauth"] = Field("kit_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    account_id: Optional[int] = Field(None, title="Account ID")
    model_config = ConfigDict(json_schema_extra={
        "title": "Kit Account", "x-credential-type": "oauth", "x-oauth-provider": "kit",
        "x-oauth-scopes": KIT_SCOPES.declared_scopes(),
        "x-credential-url": "https://app.kit.com/apps",
    })


class KitAPIKeyCredential(BaseModel):
    credential_type: Literal["kit_api_key"] = Field("kit_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="V4 API Key", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(json_schema_extra={"title": "Kit API Key", "x-credential-url": "https://app.kit.com/account_settings/developer_settings"})


KitCredential = Union[KitOAuthCredential, KitAPIKeyCredential]


def _make_config(name: str, operation: Operation) -> type[BaseModel]:
    model_name = "Kit" + "".join(word.title() for word in name.split("_")) + "Config"
    extra: dict[str, Any] = {
        "const": name, "ui:hidden": True, "x-category": operation.category,
        "x-is-trigger": False, "x-display-name": operation.label,
    }
    if operation.creates:
        extra.update({"x-creates-resource": True, "x-resource-type": operation.creates,
                      "x-resource-id-path": "data." + operation.creates.removeprefix("kit_") + ".id"})
    return create_model(
        model_name, __module__=__name__,
        operation=(Literal[name], Field(name, title=operation.label, json_schema_extra=extra)),
        **operation.fields,
    )


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


KIT_WEBHOOK_EVENTS = (
    "subscriber.created", "subscriber.activated", "subscriber.unsubscribed",
    "subscriber.bounced", "subscriber.complained", "subscriber.subscribed_to_form",
    "subscriber.added_to_sequence", "subscriber.sequence_completed",
    "subscriber.tag_added", "subscriber.tag_removed", "subscriber.custom_field_value_updated",
    "tag.created", "tag.deleted", "custom_field.created", "custom_field.deleted",
    "sequence.created", "sequence.deleted", "sequence.published", "sequence.disabled",
    "broadcast.created", "broadcast.sent", "broadcast.deleted", "post.published",
)


class KitOnEventConfig(WebhookTriggerConfigBase):
    """Receive a signed Kit V4 webhook event."""

    operation: Literal["on_event"] = Field("on_event", title="On Kit Event", json_schema_extra={
        "const": "on_event", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On Kit Event",
    })
    event_type: Literal[*KIT_WEBHOOK_EVENTS] = Field(
        "subscriber.created", title="Event Type", description="The Kit event that starts this workflow")
    webhook_url: Optional[str] = Field(
        None, title="Webhook URL", description="Registered with Kit automatically",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


KitConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (KitOnEventConfig,)], Discriminator("operation")]


class KitNodeConfig(NodeConfig[KitConfig, KitCredential]):
    pass


class KitNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-kit"
    credential_provider_labels = {"kit": "Kit Account"}
    connection_evidence = ConnectionEvidence(operation="get_account", noun="account", identity_operation="get_account")
    scope_registry = KIT_SCOPES
    edit_examples = [
        "Create a Kit subscriber", "Add a subscriber to a Kit form", "Tag a Kit subscriber",
        "Create a broadcast draft", "List Kit sequences", "Register a Kit webhook",
    ]

    @classmethod
    def get_config_model(cls):
        return KitNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.kit_oauth import refresh_access_token
        if not credential_data.get("refresh_token"):
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="kit")

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event_type = (config or {}).get("event_type") or "subscriber.created"
        if event_type not in KIT_WEBHOOK_EVENTS:
            raise ValueError("Choose a supported Kit webhook event")
        api_key = not bool(credential.get("access_token"))
        token = credential.get("api_key") if api_key else credential.get("access_token")
        if not token:
            raise ValueError("Connect Kit before activating this trigger")
        data = await cls._request(
            token, "POST", "/webhook_endpoints", api_key=api_key,
            body={"url": webhook_url, "events": [event_type], "name": f"NoClick {node_id}"})
        endpoint = data.get("webhook_endpoint") or {}
        endpoint_id = endpoint.get("id")
        secret = endpoint.get("secret")
        if not endpoint_id or not secret:
            raise ValueError("Kit did not return a webhook endpoint ID and signing secret")
        return {"external_webhook_id": str(endpoint_id), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = (config or {}).get("external_webhook_id")
        if not endpoint_id or not credential:
            return
        api_key = not bool(credential.get("access_token"))
        token = credential.get("api_key") if api_key else credential.get("access_token")
        if token:
            await cls._request(token, "DELETE", f"/webhook_endpoints/{quote(str(endpoint_id), safe='')}", api_key=api_key)

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type")}

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        header = next((value for key, value in headers.items() if key.lower() == "x-kit-signature"), "")
        parts = [part.strip() for part in header.split(",")]
        timestamp = next((part[2:] for part in parts if part.startswith("t=")), None)
        if not timestamp or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = hmac.new(str(secret).encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(part[3:], expected) for part in parts if part.startswith("v1="))

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None, api_key=False) -> Any:
        headers = {"Accept": "application/json"}
        headers["X-Kit-Api-Key" if api_key else "Authorization"] = token if api_key else f"Bearer {token}"
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(method, f"https://api.kit.com/v4{path}", params=params, json=body, headers=headers)
        if response.is_error:
            try:
                detail = response.json().get("errors") or response.json().get("error") or response.json().get("message")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Kit API error {response.status_code}: {detail or 'request failed'}")
        return response.json() if response.content else {"ok": True}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, KitNodeConfig):
            raise ValueError("Kit configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Kit account")
        op = self.config.config
        name = op.operation
        self.scope_registry.require(name)
        if isinstance(op, KitOnEventConfig):
            return {"status": "success", "operation": name, "event_type": op.event_type, "data": inputs}
        spec = OPERATIONS[name]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = {key: values[key] for key in spec.query if key in values}
        body = {key: values[key] for key in spec.body if key in values}
        for field in spec.json_fields:
            if field in body:
                raw = body.pop(field)
                try:
                    body[field.removesuffix("_json")] = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{field} must contain valid JSON") from exc
        if "events" in body:
            body["events"] = [event.strip() for event in body["events"].split(",") if event.strip()]
        if name == "create_broadcast_draft":
            body.update({"public": False, "send_at": None})
            body.setdefault("description", "")
            body.setdefault("preview_text", "")
            body.setdefault("subscriber_filter", [])
        if spec.method in ("POST", "PUT", "PATCH") and body is None:
            body = {}
        if isinstance(credential, KitOAuthCredential):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.kit_oauth import refresh_access_token
            credential_data = credential.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                credential=credential_data, refresh=refresh_access_token,
                provider="kit", caller_path="execute")
            credential.access_token = credential_data["access_token"]
            credential.refresh_token = credential_data["refresh_token"]
            credential.expires_at = credential_data.get("expires_at")
        else:
            token = credential.api_key
        data = await self._request(token, spec.method, path, params=params or None,
                                   body=body if spec.body or spec.method == "POST" else None,
                                   api_key=isinstance(credential, KitAPIKeyCredential))
        return {"status": "success", "operation": name, "data": data}
