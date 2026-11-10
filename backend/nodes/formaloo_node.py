"""Formaloo v3.0 operations, pinned to the provider's published OpenAPI.

Delivery examples and the shared X-Formaloo-Token authentication are documented
at https://help.formaloo.com/en/articles/8568748-how-formaloo-webhook-works.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
from datetime import datetime
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

BASE = "https://api.formaloo.me/v3.0"
DOCS = "https://help.formaloo.com/en/articles/8568748-how-formaloo-webhook-works"
EVENTS = {"form_submit": "form_submit_events", "row_update": "row_update_events", "row_payment": "row_payment_events"}


class FormalooCredential(BaseModel):
    model_config = ConfigDict(title="Formaloo API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dash.formaloo.net/u",
        "x-credential-instructions": "Open your profile menu in Formaloo and choose API Key & Token. Paste your API key and an existing authorization token. To obtain a token, follow the direct API access instructions at https://docs.formaloo.com. Paste only the values, without header prefixes. An optional workspace identifier selects a workspace you can access."})
    credential_type: Literal["formaloo_api_token"] = Field("formaloo_api_token", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})
    authorization_token: str = Field(..., title="Authorization token", min_length=1, json_schema_extra={"ui:widget": "password"})
    workspace: Optional[str] = Field(None, title="Workspace identifier", description="Optional business_identifier, sent as x-workspace.")

    @field_validator("api_key", "authorization_token", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the value without a header prefix or whitespace")
        return value

    @field_validator("workspace")
    @classmethod
    def workspace_value(cls, value):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value):
            raise ValueError("Use the workspace business_identifier")
        return value


def text(title, *, required=False, limit=255):
    return (str if required else Optional[str], Field(... if required else None, title=title, min_length=1, max_length=limit))


def identifier(title):
    return (str, Field(..., title=title, min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$"))


PAGE = {"page": (int, Field(1, ge=1)), "page_size": (int, Field(50, ge=1, le=100)), "search": text("Search")}
FORM = {"form_slug": identifier("Form slug")}
ROW = {"row_slug": identifier("Submission slug")}
FOLDER = {"folder_slug": identifier("Folder slug")}
TAG = {**FORM, "tag_slug": identifier("Tag slug")}
TITLE = {"title": text("Title", required=True)}
ROW_VALUES = {"values_json": (str, Field(..., title="Field values JSON", description="JSON object mapping field slugs to submitted values.", json_schema_extra={"ui:widget": "textarea"}))}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    fields: dict
    query: tuple = ()
    body: tuple = ()


OPERATIONS = {
    "get_profile": Operation("GET", "/profile/", {}),
    "list_forms": Operation("GET", "/forms/", {**PAGE, "sort_by": text("Sort fields")}, (*PAGE, "sort_by")),
    "get_form": Operation("GET", "/forms/{form_slug}/", FORM),
    "create_form": Operation("POST", "/forms/", {**TITLE, "description": text("Description", limit=10000), "folder": text("Folder slug")}, body=("title", "description", "folder")),
    "update_form": Operation("PATCH", "/forms/{form_slug}/", {**FORM, **TITLE, "description": text("Description", limit=10000)}, body=("title", "description")),
    "delete_form": Operation("DELETE", "/forms/{form_slug}/", FORM),
    "get_form_fields": Operation("GET", "/form-fields/{form_slug}/", FORM),
    "get_form_stats": Operation("GET", "/forms/{form_slug}/stats/", FORM),
    "list_submissions": Operation("GET", "/forms/{form_slug}/rows/", {**FORM, **PAGE, "sort_by": text("Sort fields"), "updated_at_gte": (Optional[datetime], Field(None, title="Updated since"))}, (*PAGE, "sort_by", "updated_at_gte")),
    "get_submission": Operation("GET", "/rows/{row_slug}/", ROW),
    "create_submission": Operation("POST", "/forms/{form_slug}/rows/", {**FORM, **ROW_VALUES}),
    "update_submission": Operation("PATCH", "/rows/{row_slug}/", {**ROW, **ROW_VALUES}),
    "delete_submission": Operation("DELETE", "/rows/{row_slug}/", ROW),
    "list_folders": Operation("GET", "/folders/", PAGE, tuple(PAGE)),
    "get_folder": Operation("GET", "/folders/{folder_slug}/", FOLDER),
    "create_folder": Operation("POST", "/folders/", {**TITLE, "parent_folder": text("Parent folder slug")}, body=("title", "parent_folder")),
    "update_folder": Operation("PATCH", "/folders/{folder_slug}/", {**FOLDER, **TITLE}, body=("title",)),
    "list_row_tags": Operation("GET", "/forms/{form_slug}/row-tags/", {**FORM, **PAGE}, tuple(PAGE)),
    "create_row_tag": Operation("POST", "/forms/{form_slug}/row-tags/", {**FORM, **TITLE, "color": text("Color", limit=63)}, body=("title", "color")),
    "update_row_tag": Operation("PATCH", "/forms/{form_slug}/row-tags/{tag_slug}/", {**TAG, **TITLE}, body=("title",)),
    "delete_row_tag": Operation("DELETE", "/forms/{form_slug}/row-tags/{tag_slug}/", TAG),
    "get_field": Operation("GET", "/fields/{field_slug}/", {"field_slug": identifier("Field slug")}),
    "list_field_choices": Operation("GET", "/fields/{field_slug}/choices/", {"field_slug": identifier("Field slug")}),
}


class FormalooInput(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def json_object(cls, value, info):
        if info.field_name == "values_json":
            try:
                body = json.loads(value)
            except (ValueError, TypeError):
                raise ValueError("Use a JSON object of field slugs and values") from None
            if not isinstance(body, dict) or not body:
                raise ValueError("Provide at least one field value")
        return value


def make_config(name, spec):
    label = name.replace("_", " ").title()
    return create_model("Formaloo" + name.title().replace("_", "") + "Config", __base__=FormalooInput, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-is-trigger": False})), **spec.fields)


CONFIG_MODELS = {name: make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class FormalooOnSubmissionEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_submission_event"] = Field("on_submission_event", json_schema_extra={"ui:hidden": True, "x-display-name": "On Submission Event", "x-is-trigger": True})
    form_slug: str = Field(..., title="Form slug", min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    event_type: Literal["form_submit", "row_update", "row_payment"] = Field("form_submit", title="Event type")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})


FormalooConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (FormalooOnSubmissionEventConfig,)], Field(discriminator="operation")]


class FormalooNodeConfig(NodeConfig[FormalooConfig, FormalooCredential]):
    pass


def redact(value, credential):
    for secret in (credential.api_key, credential.authorization_token):
        if isinstance(value, str):
            value = value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {k: redact(v, credential) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, credential) for v in value]
    return value


class FormalooNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-formaloo"
    connection_evidence = ConnectionEvidence(operation="get_profile", identity_operation="get_profile", noun="profile", label_keys=("username", "email", "first_name"))

    @classmethod
    def get_config_model(cls):
        return FormalooNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = FormalooCredential.model_validate(credential) if isinstance(credential, dict) else credential
        headers = {"x-api-key": credential.api_key, "Authorization": "JWT " + credential.authorization_token, "Accept": "application/json"}
        if credential.workspace:
            headers["x-workspace"] = credential.workspace
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params, json=body)
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Formaloo returned a non-JSON response (HTTP {response.status_code})") from None
        if response.is_error or not isinstance(payload, dict) or payload.get("status", 500) >= 400:
            raise ValueError(redact(f"Formaloo HTTP {response.status_code}: {payload}", credential))
        errors = payload.get("errors") or {}
        if errors.get("general_errors") or errors.get("form_errors"):
            raise ValueError(redact(f"Formaloo rejected the request: {errors}", credential))
        if "data" not in payload or not isinstance(payload["data"], dict):
            raise ValueError("Formaloo response is missing its data object")
        return redact(payload["data"], credential)

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, FormalooOnSubmissionEventConfig):
            payload = {k: v for k, v in inputs.items() if k != "_webhook"}
            if payload.get("event_type") != op.event_type:
                return {"status": "success", "no_event": True}
            result = {"status": "success", "data": payload, "form_slug": op.form_slug}
        else:
            if self.config.credentials is None:
                raise ValueError("Connect a Formaloo API token")
            spec = OPERATIONS[op.operation]
            values = op.model_dump(exclude_none=True, mode="json")
            path = spec.path
            for key, value in values.items():
                path = path.replace("{" + key + "}", quote(str(value), safe=""))
            body = {k: values[k] for k in spec.body if k in values}
            if "values_json" in values:
                body = json.loads(values["values_json"])
            data = await self._request(self.config.credentials, spec.method, path,
                params={k: values[k] for k in spec.query if k in values}, body=body if spec.method in {"POST", "PATCH"} else None)
            result = {"status": "success", "data": data}
        await self.emit(result)
        return result

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = FormalooOnSubmissionEventConfig.model_validate(config)
        secret = secrets.token_urlsafe(32)
        body = {"url": webhook_url, "secret": secret, "title": "NoClick " + node_id,
            "active": True, "send_raw_data": True, "send_rendered_data": True,
            **{field: event == op.event_type for event, field in EVENTS.items()}}
        data = await cls._request(credential, "POST", f"/forms/{quote(op.form_slug, safe='')}/webhooks/", body=body)
        slug = data.get("webhook", {}).get("slug")
        if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
            raise ValueError("Formaloo did not return a webhook slug")
        return {"external_webhook_id": slug, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not config.get("external_webhook_id"):
            return
        form = quote(config["form_slug"], safe="")
        slug = quote(str(config["external_webhook_id"]), safe="")
        await cls._request(credential, "DELETE", f"/forms/{form}/webhooks/{slug}/")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {k: config.get(k) for k in ("form_slug", "event_type")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        expected = config.get("signing_secret")
        actual = next((v for k, v in headers.items() if k.lower() == "x-formaloo-token"), None)
        return bool(isinstance(expected, str) and expected and isinstance(actual, str) and hmac.compare_digest(expected.encode(), actual.encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("event_type") == config.get("event_type", "form_submit")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "data": payload, "form_slug": config.get("form_slug")}

    @classmethod
    def resolve_agent_event(cls, output):
        data = output.get("data") if output.get("status") == "success" else output
        if not isinstance(data, dict) or data.get("event_type") not in EVENTS or not data.get("slug"):
            return super().resolve_agent_event(output)
        slug = data["slug"]
        fields = data.get("readable_data") or data.get("data") or {}
        text = f"Formaloo {data['event_type']} for submission {slug}"
        if output.get("form_slug"):
            text += f" in form {output['form_slug']}"
        text += "\n" + json.dumps(fields, ensure_ascii=False)
        text += f"\nEvent ID: {data.get('event_id', '')}. Submission slug for get_submission or update_submission: {slug}."
        return {"text": text, "title": f"Formaloo {data['event_type']}", "conversation_key": str(slug)}
