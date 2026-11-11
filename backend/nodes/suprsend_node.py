"""SuprSend workspace API-key actions and scheduled new-message detection.

Provider contract: https://docs.suprsend.com/openapi.yaml (1.2.2).
Writes return the provider's acknowledgement, not a delivery confirmation.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.suprsend_operations import OPERATIONS
from utils.ssrf import guarded_async_client

BASE = "https://hub.suprsend.com"


def _own_credential(value):
    credential = value.get("credentials") if isinstance(value, dict) else None
    if isinstance(credential, dict) and credential.get("credential_type") not in {None, "suprsend_api_key"}:
        raise ValueError("Attach a SuprSend API key credential")
    return value


class SuprSendAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="SuprSend API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.suprsend.com/",
        "x-credential-instructions": "In your SuprSend workspace, open Developers → API Keys and paste an API key. Choose a key with the permissions your actions need. NoClick verifies it by reading this workspace's subscriber lists.",
    })
    credential_type: Literal["suprsend_api_key"] = Field("suprsend_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


def _config(name, spec):
    fields = {}
    for key, f in spec["fields"].items():
        kind = f["type"]
        typ = {"integer": int, "boolean": bool}.get(kind, str)
        if f.get("enum"):
            typ = Literal[tuple(f["enum"])]
        default = ... if f["required"] else f.get("default")
        if default is None:
            typ = Optional[typ]
        extra = {"ui:widget": "code_editor", "ui:language": "json"} if kind in {"array", "object"} else {}
        constraints = {}
        if kind == "integer":
            constraints = {"ge": f.get("minimum", 0), "le": f.get("maximum", 1000000)}
        elif kind == "string":
            constraints = {"min_length": 1, "max_length": f.get("maxLength", 4096)}
            if f.get("pattern"):
                constraints["pattern"] = f["pattern"]
        fields[key] = (typ, Field(default, title=key.removesuffix("_json").replace("_", " ").capitalize(),
                                 description=f["description"], json_schema_extra=extra, **constraints))
    return create_model("SuprSend" + name.title().replace("_", "") + "Config", __base__=_Operation,
        operation=(Literal[name], Field(name, title=spec["label"], json_schema_extra={
            "ui:hidden": True, "x-display-name": spec["label"], "x-is-trigger": False,
            "x-category": "Notifications" if name.startswith(("trigger_", "cancel_")) else "Data",
        })), **fields)


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class SuprSendOnNewMessageConfig(PollTriggerConfigBase):
    operation: Literal["on_new_message"] = Field("on_new_message", title="On New Message", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Message"})
    tenant_id: Optional[str] = Field(None, title="Tenant ID")
    workflow_slug: Optional[str] = Field(None, title="Workflow slug")
    channel: Optional[Literal["sms", "email", "androidpush", "iospush", "webpush", "inbox", "whatsapp", "slack", "ms_teams"]] = None
    created_at_gte: Optional[str] = Field(None, title="Created at or after", description="Optional RFC3339 lower bound for this monitored message window.")


SuprSendConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (SuprSendOnNewMessageConfig,)], Field(discriminator="operation")]


class SuprSendNodeConfig(NodeConfig[SuprSendConfig, SuprSendAPIKeyCredential]):
    @model_validator(mode="before")
    @classmethod
    def own_credential(cls, value):
        return _own_credential(value)


class SuprSendNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-suprsend"
    connection_evidence = ConnectionEvidence(operation="list_lists", noun="subscriber lists")

    @classmethod
    def get_config_model(cls):
        return SuprSendNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _own_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _own_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text for the manual-connect verdict, but
            # never echo the supplied credential even if an upstream reflects it.
            raise ValueError(f"SuprSend HTTP {response.status_code}: " + response.text[:2000].replace(api_key, "[redacted]"))
        if path == "/event/" and response.status_code == 202:
            if response.text != "OK":
                raise ValueError("SuprSend event acknowledgement must be OK")
            return {"accepted": True, "delivery_verified": False}
        if not response.content:
            return {}
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("SuprSend returned an unexpected JSON response")
        return data

    @staticmethod
    def _values(config, spec):
        path, params, body = spec["path"], {}, {}
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for name, f in spec["fields"].items():
            if name not in values:
                continue
            value = values[name]
            if f["type"] in {"array", "object"}:
                try:
                    value = json.loads(value)
                except (ValueError, TypeError):
                    raise ValueError(f"{name} must contain valid JSON") from None
                if not isinstance(value, list if f["type"] == "array" else dict):
                    raise ValueError(f"{name} must contain a JSON {f['type']}")
            if f["in"] == "path":
                if value in {".", ".."} or "/" in str(value):
                    raise ValueError(f"{name} must be a single resource identifier")
                path = path.replace("{" + f["wire"] + "}", quote(str(value), safe=""))
            elif f["in"] == "query":
                params[f["wire"]] = value
            elif f["wire"] is None:
                body.update(value)
            else:
                body[f["wire"]] = value
        if config.operation == "cancel_workflow" and not body:
            raise ValueError("Provide at least one workflow cancellation filter")
        if config.operation == "update_tenant_properties" and ("properties" in body) == ("operations" in body):
            raise ValueError("Provide either properties or operations")
        return path, params, body if spec["method"] not in {"GET", "DELETE"} else None

    async def _poll_messages(self, config, api_key):
        params = config.model_dump(exclude_none=True, include={"tenant_id", "workflow_slug", "channel", "created_at_gte"})
        params["limit"] = 1000
        items, cursors = [], set()
        for _ in range(10):
            data = await self._request(api_key, "GET", "/v1/message/", params=params)
            rows, meta = data.get("results"), data.get("meta")
            if not isinstance(rows, list) or not isinstance(meta, dict):
                raise ValueError("SuprSend message page is missing results or pagination metadata")
            if any(not isinstance(row, dict) or not isinstance(row.get("message_id"), str) or not row["message_id"] for row in rows):
                raise ValueError("SuprSend message page has an invalid message ID")
            items.extend(rows)
            if not meta.get("has_next"):
                break
            cursor = meta.get("after")
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("SuprSend message pagination did not advance")
            cursors.add(cursor)
            params["after"] = cursor
        else:
            raise ValueError("More than 10,000 messages in the monitored window; narrow the tenant, workflow, channel or creation date")
        # Retain the newest IDs at the tail of the bounded seen set.
        fresh = await self._filter_unseen(list(reversed(items)), lambda item: item["message_id"])
        return {"messages": fresh, "new_message_count": len(fresh)}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a SuprSend workspace API key")
        config = self.config.config
        if isinstance(config, SuprSendOnNewMessageConfig):
            return await self._poll_messages(config, credential.api_key)
        spec = OPERATIONS[config.operation]
        path, params, body = self._values(config, spec)
        data = await self._request(credential.api_key, spec["method"], path, params=params, body=body)
        if config.operation.startswith("list_") and (not isinstance(data, dict) or not isinstance(data.get("results"), list) or not isinstance(data.get("meta"), dict)):
            raise ValueError("SuprSend list response must include results and pagination metadata")
        return {"data": data}

    @classmethod
    def resolve_agent_event(cls, output):
        messages = output.get("messages") if isinstance(output, dict) else None
        if not isinstance(messages, list) or not messages:
            return None
        lines = []
        for message in messages[:20]:
            recipient = message.get("recipient") or {}
            content = message.get("content") or {}
            workflow = message.get("workflow") or {}
            lines.append(f"- {message.get('channel', 'notification')} message {message.get('message_id')} for "
                f"{recipient.get('distinct_id') or recipient.get('id') or 'recipient'}: {message.get('status', '')}; "
                f"workflow {workflow.get('slug', '')}, tenant {message.get('tenant_id', '')}. "
                f"{content.get('header', '')} {content.get('body', '')}")
        return {"text": f"SuprSend: {len(messages)} new message(s)\n" + "\n".join(lines), "conversation_key": None}
