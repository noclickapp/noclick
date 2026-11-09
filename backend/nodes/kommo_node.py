"""Kommo CRM workflow node for the documented JSON API v4 endpoints.

The operation catalog records each official reference page. Kommo writes are
usually bulk arrays, while single-record updates use objects; the JSON body
field accepts either and is sent without transformation.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, parse_qsl

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import (
    ExternalWebhookTriggerMixin,
    WebhookTriggerConfigBase,
)
from utils.ssrf import guarded_async_client, normalize_provider_subdomain
from nodes.kommo_operations import KOMMO_OPERATIONS
from nodes.scopes.kommo import KOMMO_SCOPES
from nodes.oauth.kommo_oauth import OAUTH_PROVIDER

logger = logging.getLogger(__name__)

_ENTITY_TYPES = {"leads", "contacts", "companies"}


class KommoOAuthCredential(BaseModel):
    credential_type: Literal["kommo_oauth"] = Field(
        "kommo_oauth", json_schema_extra={"ui:hidden": True}
    )
    referer: str = Field(
        ..., title="Kommo account host", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access token")
    refresh_token: str = Field(..., title="Refresh token")
    expires_at: str = Field(..., title="Token expiry")

    model_config = ConfigDict(
        json_schema_extra={
            "title": "Kommo OAuth",
            "x-credential-type": "oauth",
            "x-oauth-scopes": KOMMO_SCOPES.declared_scopes(),
            "x-oauth-provider": "kommo",
            "x-credential-url": "https://developers.kommo.com/docs/oauth-20",
        }
    )


class KommoLongLivedTokenCredential(BaseModel):
    credential_type: Literal["kommo_long_lived_token"] = Field(
        "kommo_long_lived_token", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(
        ..., title="Kommo account subdomain", description="The part before .kommo.com"
    )
    token: str = Field(
        ..., title="Long-lived token", json_schema_extra={"ui:widget": "password"}
    )

    model_config = ConfigDict(
        json_schema_extra={
            "title": "Kommo Long-lived Token",
            "x-credential-url": "https://developers.kommo.com/docs/long-lived-token",
            "x-credential-instructions": "Create a private integration in Kommo Settings > Integrations and copy its long-lived token.",
        }
    )


KommoCredential = Union[KommoOAuthCredential, KommoLongLivedTokenCredential]


def _operation_model(spec: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, Any] = {
        "operation": (
            Literal[spec["operation"]],
            Field(
                spec["operation"],
                title=spec["title"],
                json_schema_extra={
                    "const": spec["operation"],
                    "ui:hidden": True,
                    "x-category": spec["category"],
                    "x-display-name": spec["title"],
                },
            ),
        )
    }
    for name in spec["path_parameters"]:
        if name == "entity_type":
            fields[name] = (
                Literal["leads", "contacts", "companies"],
                Field(..., title="Entity type"),
            )
        else:
            fields[name] = (str, Field(..., title=name.replace("_", " ").title()))
    fields["query"] = (
        Optional[str],
        Field(
            None,
            title="Query parameters (JSON)",
            description='Optional JSON object; use literal Kommo filter keys such as {"filter[is_completed]": 1}.',
            json_schema_extra={
                "ui:widget": "textarea",
                "contentMediaType": "application/json",
                "contentSchema": {"type": "object"},
            },
        ),
    )
    if spec["has_body"]:
        fields["body"] = (
            str,
            Field(
                ...,
                title="JSON body",
                description="JSON object or array matching the linked Kommo API reference.",
                json_schema_extra={
                    "ui:widget": "textarea",
                    "contentMediaType": "application/json",
                    "contentSchema": {"type": ["object", "array"]},
                },
            ),
        )
    return create_model(
        "Kommo"
        + "".join(word.capitalize() for word in spec["operation"].split("_"))
        + "Config",
        __doc__=spec["title"],
        **fields,
    )


# CRM event names and wire shapes: https://developers.kommo.com/reference/webhook-events
# https://developers.kommo.com/docs/webhooks-general (these differ from Chats API webhooks).
KOMMO_WEBHOOK_EVENTS = {
    "add_lead": ("leads", "add", "Lead added"),
    "update_lead": ("leads", "update", "Lead updated"),
    "status_lead": ("leads", "status", "Lead stage changed"),
    "add_contact": ("contacts", "add", "Contact added"),
    "add_task": ("task", "add", "Task added"),
    "add_message": (None, "add", "Incoming message received"),
}


class KommoOnEventConfig(WebhookTriggerConfigBase):
    """Start a workflow from a Kommo CRM webhook (Advanced plan or higher)."""

    operation: Literal["on_event"] = Field(
        "on_event",
        title="On Kommo Event",
        json_schema_extra={
            "const": "on_event",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Kommo Event",
        },
    )
    event_type: Literal[*KOMMO_WEBHOOK_EVENTS] = Field(
        "update_lead",
        title="Event",
        description="Kommo event that starts the workflow. Requires an account administrator and an Advanced, Pro or Enterprise plan.",
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Registered with Kommo automatically.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )


def _webhook_payload(payload):
    """Decode PHP bracket form keys locally; the relay wraps non-JSON bodies as raw."""
    if "raw" not in payload:
        return payload
    raw = payload["raw"]
    if not isinstance(raw, str):
        return payload
    result = {}
    for key, value in parse_qsl(raw, keep_blank_values=True, max_num_fields=10000):
        parts = re.findall(r"[^\[\]]+", key)
        if not parts or len(parts) > 20:
            continue
        target = result
        for part in parts[:-1]:
            if not isinstance(target.get(part), dict):
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value
    return result


def _event_records(payload, event_type):
    entity, action, _ = KOMMO_WEBHOOK_EVENTS[event_type]
    data = _webhook_payload(payload)
    group = data if entity is None else data.get(entity, {})
    records = group.get(action, []) if isinstance(group, dict) else []
    if isinstance(records, dict):
        records = list(records.values())
    return (
        [item for item in records if isinstance(item, dict)]
        if isinstance(records, list)
        else []
    )


KOMMO_CONFIGS = {
    name: _operation_model(spec) for name, spec in KOMMO_OPERATIONS.items()
}
KommoConfig = Annotated[
    Union[tuple(KOMMO_CONFIGS.values()) + (KommoOnEventConfig,)],
    Field(discriminator="operation"),
]


class KommoNodeConfig(NodeConfig[KommoConfig, KommoCredential]):
    """Kommo operation and account credential."""


def _parse_json(raw: Optional[str], field: str, *, object_only: bool = False) -> Any:
    if raw is None or raw == "":
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Kommo {field} must be valid JSON") from exc
    if object_only and not isinstance(value, dict):
        raise ValueError(f"Kommo {field} must be a JSON object")
    if not object_only and not isinstance(value, (dict, list)):
        raise ValueError(f"Kommo {field} must be a JSON object or array")
    return value


class KommoNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Run Kommo CRM actions against one verified account host."""

    integration_type = "automation-kommo"
    webhook_signing_secret_not_issued = True
    webhook_replace_stale_endpoint = True
    scope_registry = KOMMO_SCOPES
    credential_provider_labels = {"kommo": "Kommo Account"}

    edit_examples = [
        "List new Kommo leads",
        "Add a contact to Kommo",
        "Move a lead to another pipeline stage",
        "Create a follow-up task in Kommo",
        "Start a workflow when a Kommo lead changes stage",
    ]
    connection_evidence = ConnectionEvidence(operation="get_account", noun="account")

    @classmethod
    async def _webhook_request(cls, credential, method, body):
        credential = await cls.freshen_credential(dict(credential))
        parsed = (
            KommoOAuthCredential.model_validate(credential)
            if credential.get("credential_type") == "kommo_oauth"
            else KommoLongLivedTokenCredential.model_validate(credential)
        )
        if isinstance(parsed, KommoOAuthCredential):
            host = OAUTH_PROVIDER.validate_context({"referer": parsed.referer})[
                "referer"
            ]
            token = parsed.access_token
        else:
            host = (
                normalize_provider_subdomain(
                    parsed.subdomain, "kommo.com", field_name="Kommo subdomain"
                )
                + ".kommo.com"
            )
            token = parsed.token
        async with guarded_async_client(timeout=30) as client:
            response = await client.request(
                method,
                f"https://{host}/api/v4/webhooks",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/hal+json",
                },
            )
        response.raise_for_status()

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ):
        event_type = config.get("event_type", "update_lead")
        if event_type not in KOMMO_WEBHOOK_EVENTS:
            raise ValueError("Choose a supported Kommo event")
        # Kommo deletes subscriptions by destination, not by the numeric response ID.
        # https://developers.kommo.com/reference/add-webhooks and /delete-webhook
        await cls._webhook_request(
            credential, "POST", {"destination": webhook_url, "settings": [event_type]}
        )
        return {"external_webhook_id": webhook_url}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        destination = config.get("external_webhook_id")
        if not destination:
            return
        if not credential:
            raise ValueError("Kommo credentials are required to remove the webhook")
        try:
            await cls._webhook_request(
                credential, "DELETE", {"destination": destination}
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": config.get("event_type", "update_lead")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # The CRM webhook registration/delivery contract has no signing secret or
        # signature header. The NoClick-minted callback URL is the capability.
        # https://developers.kommo.com/docs/webhooks-general
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event_type = config.get("event_type", "update_lead")
        return event_type in KOMMO_WEBHOOK_EVENTS and bool(
            _event_records(payload, event_type)
        )

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        event_type = config.get("event_type", "update_lead")
        return {
            "status": "success",
            "action": "on_event",
            "event_type": event_type,
            "data": {"records": _event_records(payload, event_type)},
        }

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("action") != "on_event":
            return super().resolve_agent_event(output)
        event_type = output.get("event_type")
        if event_type not in KOMMO_WEBHOOK_EVENTS:
            return None
        records = output.get("data", {}).get("records", [])
        if not records:
            return None
        label = KOMMO_WEBHOOK_EVENTS[event_type][2]
        lines = [f"Kommo: {label}"]
        for record in records:
            # Each event has its own documented fields; don't assume lead fields
            # exist on contacts, tasks or messages.
            lines.append(f"Record ID: {record['id']}")
            if event_type in {"add_lead", "update_lead", "status_lead"}:
                lines.append(
                    f"Lead: {record.get('name', '')} (account {record.get('account_id', '')}, pipeline {record.get('pipeline_id', '')})"
                )
                lines.append(
                    f"Stage: {record.get('status_id', '')}; value: {record.get('price', '')}"
                )
                if event_type != "add_lead" and record.get("old_status_id"):
                    lines.append(f"Previous stage: {record['old_status_id']}")
                lines.append(
                    f"Changed by user {record.get('modified_user_id', '')}; responsible user {record.get('responsible_user_id', '')}"
                )
                lines.append(
                    f"To act: get_lead or update_lead with lead_id={record['id']}"
                )
            elif event_type == "add_contact":
                lines.append(
                    f"Contact: {record.get('name', '')} (account {record.get('account_id', '')})"
                )
                lines.append(
                    f"Created by user {record.get('created_user_id', '')}; responsible user {record.get('responsible_user_id', '')}"
                )
                lines.append(
                    f"To act: get_contact or update_contact with contact_id={record['id']}"
                )
            elif event_type == "add_task":
                lines.append(
                    f"Task: {record['text']} (account {record.get('account_id', '')})"
                )
                lines.append(
                    f"Created by user {record.get('created_user_id', '')}; responsible user {record.get('responsible_user_id', '')}; due {record.get('complete_before', '')}"
                )
                lines.append(
                    f"Linked entity: {record.get('element_type', '')} / {record.get('element_id', '')}"
                )
                lines.append(
                    f"To act: get_task or update_task with task_id={record['id']}"
                )
            else:
                lines.append(
                    f"Message from {record['author']['type']} {record['author']['id']} via {record['origin']}: {record['text']}"
                )
                lines.append(
                    f"Chat {record['chat_id']}; talk {record['talk_id']}; contact {record['contact_id']}; {record['entity_type']} {record['entity_id']}"
                )
        first = records[0]
        key = first["chat_id"] if event_type == "add_message" else first["id"]
        return {"text": "\n".join(lines), "conversation_key": str(key), "title": label}

    @classmethod
    def get_config_model(cls):
        return KommoNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        if credential_data.get("credential_type") != "kommo_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="kommo",
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.monotonic()
        if not self.config or not isinstance(self.config, KommoNodeConfig):
            raise ValueError("Kommo configuration is required")
        if self.config.config.operation == "on_event":
            return self.no_event_output("on_event")
        credentials = self.config.credentials
        if not credentials:
            raise ValueError("Kommo credentials are required")
        if isinstance(credentials, KommoOAuthCredential):
            host = OAUTH_PROVIDER.validate_context({"referer": credentials.referer})[
                "referer"
            ]
        else:
            subdomain = normalize_provider_subdomain(
                credentials.subdomain, "kommo.com", field_name="Kommo subdomain"
            )
            host = f"{subdomain}.kommo.com"
        spec = KOMMO_OPERATIONS[self.config.config.operation]
        values = self.config.config.model_dump(exclude_none=True)
        path = spec["path"]
        for name in spec["path_parameters"]:
            value = str(values[name])
            if name == "entity_type" and value not in _ENTITY_TYPES:
                raise ValueError("Kommo entity type is unsupported")
            if not value:
                raise ValueError(f"Kommo {name} is required")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        if re.search(r"{[^}]+}", path):
            raise ValueError("A Kommo path parameter is missing")
        query = _parse_json(values.get("query"), "query", object_only=True)
        body = _parse_json(values.get("body"), "body")
        if spec["has_body"] and body is None:
            raise ValueError("Kommo JSON body is required")
        if isinstance(credentials, KommoOAuthCredential):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token

            cred_dict = credentials.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=OAUTH_PROVIDER.bind_refresh(cred_dict),
                additional_token_fields=OAUTH_PROVIDER.credential_fields,
                provider="kommo",
                caller_path="execute",
            )
            credentials.access_token = cred_dict["access_token"]
            credentials.expires_at = cred_dict.get("expires_at")
            if cred_dict.get("refresh_token"):
                credentials.refresh_token = cred_dict["refresh_token"]
        else:
            token = credentials.token
        url = f"https://{host}/api/v4{path}"
        try:
            async with guarded_async_client(timeout=30) as client:
                response = await client.request(
                    spec["method"],
                    url,
                    params=query,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/hal+json",
                    },
                )
            try:
                payload = response.json() if response.content else {}
            except ValueError:
                payload = {"text": response.text}
            result = {
                "status": "error" if response.is_error else "success",
                "action": self.config.config.operation,
                "timing_ms": {
                    "api_request": round((time.monotonic() - started) * 1000, 2)
                },
            }
            if response.is_error:
                result.update(status_code=response.status_code, error=payload)
            else:
                result["data"] = payload
            return result
        except httpx.HTTPError:
            logger.warning("Kommo request failed for %s", self.config.config.operation)
            return {
                "status": "error",
                "action": self.config.config.operation,
                "status_code": 502,
                "error": "Kommo request failed",
                "timing_ms": {
                    "api_request": round((time.monotonic() - started) * 1000, 2)
                },
            }
