"""Audienceful v2 contact, consent and email automation.

The public API routes and signed event examples are documented at
https://www.audienceful.com/help/api; the published OpenAPI uses internal /api paths.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.audienceful.com/v2"
DOCS = "https://www.audienceful.com/help/api/"


class AudiencefulAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Audienceful API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": DOCS + "authentication",
        "x-credential-instructions": "In Audienceful Settings, generate a workspace API key and paste it here. Grant people:read for connection verification, plus the read/write scopes for your chosen actions. Triggers need webhooks:write. Write scopes do not include read scopes.",
    })
    credential_type: Literal["audienceful_api_key"] = Field("audienceful_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


def text(title, required=False, **kwargs):
    return (str if required else str | None, Field(... if required else None, title=title, min_length=1, **kwargs))


def json_text(title, kind, required=False):
    return text(title, required, description="JSON " + kind + ". Only supplied values are sent.",
                json_schema_extra={"ui:widget": "textarea", "x-audienceful-json-kind": kind})


PAGE = {"cursor": text("Next Cursor"), "page_size": (int, Field(100, ge=1, le=100, title="Page Size"))}
PERSON = {"person_id": text("Contact ID", True, description="The opaque contact ID returned by Audienceful.")}
EMAIL = {"email": text("Email Address", True, json_schema_extra={"format": "email"})}
IDENTIFIER = {"email": text("Contact Email", True, json_schema_extra={"format": "email"})}
PERSON_FIELDS = {
    "notes": text("Notes"), "phone_number": text("Phone Number", max_length=32),
    "extra_data_json": json_text("Custom Fields", "object"), "tags_json": json_text("Tags to Add", "array"),
    "publications_json": json_text("Publications to Add", "array"),
    "double_opt_in": (Literal["not_required", "required", "pending", "complete"] | None, Field(None, title="Double Opt In")),
}
PUB_ID = {"publication_id": text("Publication ID", True)}
FIELD_ID = {"field_id": text("Field ID", True)}
PUB_FIELDS = {"description": text("Description"), "emoji": text("Emoji", max_length=16),
              **{k: (bool | None, Field(None, title=k.replace("_", " ").title())) for k in
                 ("default_subscribed", "auto_subscribe_new", "visible_on_preferences")}}
FIELD_FIELDS = {"name": text("Field Name", True, max_length=128), "data_name": text("Data Name", True, max_length=256),
                "type": (Literal["boolean", "string", "tag", "number", "datetime", "phone"], Field(..., title="Field Type")),
                "required": (bool, Field(False, title="Required"))}


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    contract_operation: str
    fields: dict
    query: tuple = ()


OPERATIONS = {
    "list_people": Operation("List Contacts", "Contacts", "GET", "/people", "people_list", PAGE, ("cursor", "page_size")),
    "get_person": Operation("Get Contact", "Contacts", "GET", "/people/{person_id}", "people_retrieve", PERSON),
    "upsert_person": Operation("Create or Update Contact", "Contacts", "POST", "/people", "people_create", {**EMAIL, **PERSON_FIELDS}),
    "update_person": Operation("Update Contact by ID", "Contacts", "PATCH", "/people/{person_id}", "people_partial_update", {**PERSON, **PERSON_FIELDS}),
    "delete_person": Operation("Delete Contact", "Contacts", "POST", "/people/delete", "people_delete_create", IDENTIFIER),
    "unsubscribe_person": Operation("Unsubscribe Contact", "Consent", "POST", "/people/unsubscribe", "people_unsubscribe_create", IDENTIFIER),
    "confirm_person_opt_in": Operation("Confirm Contact Opt In", "Consent", "POST", "/people/opt-in", "people_opt_in_create", IDENTIFIER),
    "person_publications": Operation("Read or Update Contact Consent", "Consent", "POST", "/people/publications", "people_publications_create", {
        **IDENTIFIER, "publications_json": json_text("Publication Consent Map", "object")}),
    "list_audiences": Operation("List Audiences", "Audiences", "GET", "/audiences", "audiences_retrieve", {}),
    "list_audience_members": Operation("List Audience Members", "Audiences", "GET", "/audiences/{audience_id}/members", "audiences_members_list", {
        "audience_id": text("Audience ID", True, description="An audience ID, or all for active subscribers."), **PAGE}, ("cursor", "page_size")),
    "list_fields": Operation("List Custom Fields", "Fields", "GET", "/fields", "fields_list", PAGE, ("cursor", "page_size")),
    "create_field": Operation("Create Custom Field", "Fields", "POST", "/fields", "fields_create", FIELD_FIELDS),
    "update_field": Operation("Update Custom Field", "Fields", "PATCH", "/fields/{field_id}", "fields_partial_update", {**FIELD_ID,
        **{k: (t | None, Field(None, title=f.title)) for k, (t, f) in FIELD_FIELDS.items()}}),
    "delete_field": Operation("Delete Custom Field", "Fields", "DELETE", "/fields/{field_id}", "fields_destroy", FIELD_ID),
    "list_publications": Operation("List Publications", "Publications", "GET", "/publications", "publications_list", PAGE, ("cursor", "page_size")),
    "get_publication": Operation("Get Publication", "Publications", "GET", "/publications/{publication_id}", "publications_retrieve", PUB_ID),
    "create_publication": Operation("Create Publication", "Publications", "POST", "/publications", "publications_create", {
        "name": text("Publication Name", True, max_length=256), **PUB_FIELDS}),
    "update_publication": Operation("Update Publication", "Publications", "PATCH", "/publications/{publication_id}", "publications_partial_update", {
        **PUB_ID, "name": text("Publication Name", max_length=256), **PUB_FIELDS}),
    "list_publication_subscribers": Operation("List Publication Subscribers", "Publications", "GET", "/publications/{publication_id}/subscribers", "publications_subscribers_list", {**PUB_ID, **PAGE}, ("cursor", "page_size")),
    "list_automation_events": Operation("List Automation Events", "Automations", "GET", "/automations/events", "automations_events_list", PAGE, ("cursor", "page_size")),
    "trigger_automation_event": Operation("Trigger Automation Event", "Automations", "POST", "/automations/event", "automations_event_create", {
        **EMAIL, "event": text("Event Name", True), "event_properties_json": json_text("Event Properties", "object"),
        "fields_json": json_text("Contact Field Updates", "object"), "add_person": (bool, Field(False, title="Add Contact If Missing")),
        "idempotency_key": text("Idempotency Key", description="Reuse the same key when retrying this event.")}),
    "send_transactional_email": Operation("Send Transactional Email", "Email", "POST", "/transactional", "transactional_create", {
        **EMAIL, "draft": text("Draft ID or Slug", True), "subject": text("Subject Override"), "preheader": text("Preheader"),
        "event_properties_json": json_text("Event Properties", "object"), "fields_json": json_text("Contact Field Updates", "object"),
        "add_contact": (bool, Field(False, title="Add Contact to Subscriber List")),
        "idempotency_key": text("Idempotency Key", True, description="Reuse the same key when retrying this send to prevent duplicates.")}),
    "get_operation": Operation("Get Async Operation", "Operations", "GET", "/operations/{operation_id}", "operations_retrieve", {"operation_id": text("Operation ID", True)}),
    "list_send_reports": Operation("List Send Reports", "Reports", "GET", "/reports", "reports_list", {**PAGE, "search": text("Search")}, ("cursor", "page_size", "search")),
}


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def json_values(self):
        for name in ("person_id", "audience_id", "publication_id", "field_id", "operation_id"):
            value = getattr(self, name, None)
            if value is not None and (value in {".", ".."} or "/" in value or any(c.isspace() for c in value)):
                raise ValueError(f"{name} must be a single opaque ID")
        for name, field in type(self).model_fields.items():
            value = getattr(self, name)
            kind = (field.json_schema_extra or {}).get("x-audienceful-json-kind")
            if value is not None and kind:
                try:
                    parsed = json.loads(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{field.title} must be valid JSON") from None
                if not isinstance(parsed, dict if kind == "object" else list):
                    raise ValueError(f"{field.title} must be a JSON {kind}")
                if name in {"tags_json", "publications_json"}:
                    expected = bool if kind == "object" else str
                    values = parsed.values() if isinstance(parsed, dict) else parsed
                    if any(not isinstance(item, expected) for item in values):
                        raise ValueError(f"{field.title} has invalid values")
        return self


def _model(name, spec):
    return create_model("Audienceful" + "".join(p.title() for p in name.split("_")) + "Config", __base__=_Action, __module__=__name__,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "ui:hidden": True, "x-display-name": spec.label, "x-category": spec.category, "x-is-trigger": False})), **spec.fields)


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
EVENTS = ("person.created", "person.updated", "person.unsubscribed", "person.deleted",
          "audience.member_added", "audience.member_removed", "bulk_email.sent")


class AudiencefulOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Audienceful Event", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On Audienceful Event", "x-category": "Triggers", "x-is-trigger": True})
    event_type: Literal[*EVENTS] = Field("person.created", title="Event Type")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


AudiencefulOperation = Annotated[Union[tuple(CONFIG_MODELS.values()) + (AudiencefulOnEventConfig,)], Field(discriminator="operation")]


class AudiencefulNodeConfig(NodeConfig[AudiencefulOperation, AudiencefulAPIKeyCredential]):
    pass


class AudiencefulNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-audienceful"
    connection_evidence = ConnectionEvidence(operation="list_people", noun="contacts", label_keys=("email", "id"))
    edit_examples = ["Sync a contact to Audienceful", "Unsubscribe a contact", "Send a transactional email", "When an Audienceful contact changes"]

    @classmethod
    def get_config_model(cls):
        return AudiencefulNodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None, idempotency_key=None):
        headers = {"X-Api-Key": api_key, "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body, headers=headers)
        if response.is_error:
            try:
                message = response.json().get("error", {}).get("message") or "Request failed"
            except (ValueError, AttributeError):
                message = "Request failed"
            raise ValueError(f"Audienceful API {response.status_code}: {str(message).replace(api_key, '[redacted]')}")
        if response.status_code in range(300, 400):
            raise ValueError("Audienceful returned an unexpected redirect")
        return response.json() if response.content else {"ok": True}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Audienceful API key")
        config = self.config.config
        if isinstance(config, AudiencefulOnEventConfig):
            return self.no_event_output(config.operation)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        idempotency_key = values.pop("idempotency_key", None)
        params = {key: values.pop(key) for key in spec.query if key in values}
        body = {key.removesuffix("_json"): json.loads(value) if key.endswith("_json") else value for key, value in values.items()}
        data = await self._request(self.config.credentials.api_key, spec.method, path, params=params or None,
                                   body=body if spec.method in {"POST", "PATCH", "PUT"} else None, idempotency_key=idempotency_key)
        output = {"status": "success", "action": config.operation, "data": data}
        await self.emit(output)
        return output

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = AudiencefulOnEventConfig.model_validate(config or {})
        data = await cls._request(AudiencefulAPIKeyCredential.model_validate(credential).api_key, "POST", "/webhooks",
                                  body={"url": webhook_url, "events": [op.event_type]})
        if not isinstance(data, dict) or not data.get("id") or not data.get("secret"):
            raise ValueError("Audienceful did not return the webhook ID and one-time signing secret")
        return {"external_webhook_id": str(data["id"]), "signing_secret": data["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if credential and identifier:
            await cls._request(AudiencefulAPIKeyCredential.model_validate(credential).api_key, "DELETE", "/webhooks/" + quote(str(identifier), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "person.created")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        header = next((v for k, v in headers.items() if k.lower() == "x-audienceful-signature"), "")
        try:
            parts = dict(part.strip().split("=", 1) for part in header.split(","))
            timestamp = parts["t"]
            if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300 or not secret:
                return False
            expected = hmac.new(str(secret).encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, parts.get("v1", ""))
        except (ValueError, TypeError, KeyError):
            return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return isinstance(payload, dict) and payload.get("event") == (config or {}).get("event_type", "person.created")

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event") not in EVENTS or not isinstance(output.get("data"), dict):
            return None
        event = output["event"]
        data = output["data"]
        if event.startswith("person."):
            who = data.get("email")
            text = f"Audienceful {event}: {who}. Contact details: {json.dumps(data, ensure_ascii=False)}. Use this email to update contact details or manage consent."
            key = who
        elif event.startswith("audience."):
            person = data.get("person") or {}
            audience = data.get("audience") or {}
            who = person.get("email")
            text = f"Audienceful {event}: {who} in audience {audience.get('name')}. Contact ID: {person.get('id')}; audience ID: {audience.get('id')}."
            key = who
        else:
            text = f"Audienceful bulk email sent: {data.get('subject')}. {data.get('recipients')} recipients; sent at {data.get('sent_at')}. Send task ID: {data.get('task_id')}. Details: {json.dumps(data, ensure_ascii=False)}"
            key = data.get("task_id")
        return {"text": text, "conversation_key": str(key) if key else None, "title": "Audienceful " + event}
