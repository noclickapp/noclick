"""Shipmondo v3 shipping, order and inventory automation.

Contract: https://app.shipmondo.com/api/public/v3/openapi.json
Webhooks: https://shipmondo.dev/docs/webhooks/requirements-and-structure
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import (
    ExternalWebhookTriggerMixin,
    WebhookTriggerConfigBase,
)
from nodes.shipmondo_operations import CONFIG_MODELS, OPERATIONS

BASE_URL = "https://app.shipmondo.com/api/public/v3"
WEBHOOK_EVENTS = (
    "Shipments.create",
    "Shipments.cancel",
    "Orders.create",
    "Orders.status_update",
    "Orders.create_fulfillment",
    "Orders.create_shipment",
    "Orders.payment_captured",
    "Orders.payment_refunded",
    "Orders.payment_voided",
    "Orders.delete",
    "Drafts.create",
    "Drafts.create_shipment",
    "Drafts.delete",
    "Shipment Monitor.latest",
    "Shipment Monitor.delivered",
)


class ShipmondoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Shipmondo API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.shipmondo.com/main/app/#/setting/api",
            "x-credential-instructions": "Copy your API user and API key from Shipmondo Settings → Integrations → API. Use production credentials. NoClick sends them with HTTP Basic authentication to app.shipmondo.com.",
        },
    )
    credential_type: Literal["shipmondo_api_key"] = Field(
        "shipmondo_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_username: str = Field(
        ..., title="API user", min_length=1, json_schema_extra={"ui:widget": "password"}
    )
    api_key: str = Field(
        ..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"}
    )

    @field_validator("api_username", "api_key", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value) or ":" in value:
            raise ValueError(
                "Paste the API credential without a Basic header, spaces or colon"
            )
        return value


class ShipmondoOnEventConfig(WebhookTriggerConfigBase):
    """Receive shipment, order, draft or tracking changes in real time."""

    operation: Literal["on_event"] = Field(
        "on_event",
        title="On Shipmondo Event",
        json_schema_extra={
            "const": "on_event",
            "ui:hidden": True,
            "x-is-trigger": True,
            "x-category": "Triggers",
            "x-display-name": "On Shipmondo Event",
        },
    )
    event_type: Literal[WEBHOOK_EVENTS] = Field("Shipments.create", title="Event")
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="Registered in Shipmondo automatically",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )


ShipmondoConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values()) + (ShipmondoOnEventConfig,)],
    Field(discriminator="operation"),
]


class ShipmondoNodeConfig(NodeConfig[ShipmondoConfig, ShipmondoAPIKeyCredential]):
    pass


def _decode_jwt(token: str, secret: str) -> dict:
    """Verify the HS256 JWT before decoding. Shipmondo's JWT payload can itself
    be a JSON string (its documented encoded-body prefix uses that form)."""
    if not isinstance(token, str) or not isinstance(secret, str) or not secret:
        raise ValueError("Missing Shipmondo webhook token or key")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid Shipmondo JWT")

    def decode(part):
        return base64.b64decode(
            part + "=" * (-len(part) % 4), altchars=b"-_", validate=True
        )

    header = json.loads(decode(parts[0]))
    if (
        not isinstance(header, dict)
        or header.get("alg") != "HS256"
        or header.get("crit")
    ):
        raise ValueError("Shipmondo webhooks require HS256")
    expected = hmac.new(
        secret.encode(), (parts[0] + "." + parts[1]).encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, decode(parts[2])):
        raise ValueError("Invalid Shipmondo webhook signature")
    payload = json.loads(decode(parts[1]))
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("Invalid Shipmondo webhook payload")
    return payload


class ShipmondoNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-shipmondo"
    webhook_replace_stale_endpoint = True
    connection_evidence = ConnectionEvidence(
        operation="get_account", identity_operation="get_account", noun="account"
    )

    @classmethod
    def get_config_model(cls):
        return ShipmondoNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = ShipmondoAPIKeyCredential.model_validate(credential)
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                auth=httpx.BasicAuth(credential.api_username, credential.api_key),
                headers={"Accept": "application/json"},
                params=params,
                json=body,
            )
        if response.is_error or response.is_redirect:
            # Preserve the provider's rejection text for manual-connect evidence,
            # but never echo either credential if an upstream response contains it.
            detail = response.text[:2000]
            for secret in (credential.api_username, credential.api_key):
                detail = detail.replace(secret, "[redacted]")
            raise ValueError(f"Shipmondo API error {response.status_code}: {detail}")
        return response.json() if response.content else None

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ShipmondoNodeConfig):
            raise ValueError("Shipmondo configuration required")
        op = self.config.config
        if isinstance(op, ShipmondoOnEventConfig):
            return self.no_event_output(op.operation)
        if self.config.credentials is None:
            raise ValueError("Connect a Shipmondo API key")
        spec = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec["path"]
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        params = {k: values[k] for k in spec["query"] if k in values}
        # HTTP query booleans are lower case; request JSON retains real booleans.
        params = {
            k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()
        }
        body = (
            json.loads(values["payload"])
            if spec["json_body"]
            else {k: values[k] for k in spec["body"] if k in values}
        )
        result = await self._request(
            self.config.credentials.model_dump(),
            spec["method"],
            path,
            params=params or None,
            body=body if spec["json_body"] or spec["body"] else None,
        )
        output = {"status": "success", "operation": op.operation, "data": result}
        await self.emit(output)
        return output

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ):
        event = ShipmondoOnEventConfig.model_validate(config).event_type
        resource, action = event.rsplit(".", 1)
        key = secrets.token_urlsafe(32)
        result = await cls._request(
            credential,
            "POST",
            "/webhooks",
            body={
                "name": f"NoClick {node_id}",
                "endpoint": webhook_url,
                "key": key,
                "resource_name": resource,
                "action": action,
            },
        )
        # v3 specifies an array response for webhook creation.
        if (
            not isinstance(result, list)
            or len(result) != 1
            or not isinstance(result[0], dict)
            or not result[0].get("id")
        ):
            raise ValueError("Shipmondo did not return the created webhook ID")
        return {"external_webhook_id": str(result[0]["id"]), "signing_secret": key}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if not identifier:
            return
        if not credential:
            raise ValueError("Connect Shipmondo to unregister the webhook")
        if not str(identifier).isdigit():
            raise ValueError("Invalid Shipmondo webhook ID")
        await cls._request(credential, "DELETE", f"/webhooks/{int(identifier)}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "Shipments.create")}

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: dict[str, str], config: dict[str, Any]
    ) -> bool:
        try:
            _decode_jwt(json.loads(body)["data"], config.get("signing_secret"))
            return True
        except (ValueError, TypeError, KeyError, UnicodeError):
            return False

    @classmethod
    async def transform_trigger_payload(
        cls, payload, config, *, pool=None, workflow_id=None, node_id=None
    ):
        # Runtime calls this only after verify_webhook_signature. The object
        # form also permits processing the provider's documented decoded events.
        metadata = payload.get("_webhook", {})
        decoded = (
            _decode_jwt(payload["data"], config.get("signing_secret"))
            if isinstance(payload.get("data"), str)
            else payload
        )
        return {**decoded, "_webhook": metadata}

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        record = payload.get("data")
        if not isinstance(record, dict) or record.get("id") is None:
            raise ValueError("Shipmondo event has no resource ID")
        metadata = payload.get("_webhook", {})
        headers = {k.lower(): v for k, v in metadata.get("headers", {}).items()}
        return {
            "status": "success",
            "event_type": config.get("event_type", "Shipments.create"),
            "actor": headers.get("smd-user"),
            "payload_id": headers.get("smd-payload-id"),
            "webhook": payload.get("webhook"),
            "data": record,
        }

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("status") == "no_event":
            return None
        record = output.get("data")
        if not isinstance(record, dict) or record.get("id") is None:
            return None
        event = output.get("event_type", "Shipmondo event")
        identifier = str(record["id"])
        lines = [f"Shipmondo {event}: resource {identifier}"]
        if output.get("actor"):
            lines.append(f"By: {output['actor']}")
        # Resources have different schemas; only inspect fields present in this
        # record. Shipment Monitor's shipment_id differs from its own id.
        for key in (
            "order_id",
            "order_status",
            "fulfillment_status",
            "payment_status",
            "reference",
            "shipment_id",
            "carrier_code",
            "pkg_no",
            "carrier_track_id",
            "current_status",
            "current_state",
            "current_status_text",
            "current_status_registered_at",
            "city",
            "country_code",
        ):
            if key in record and record[key] is not None:
                lines.append(f"{key.replace('_', ' ').capitalize()}: {record[key]}")
        for key in ("receiver", "ship_to"):
            if key in record and isinstance(record[key], dict):
                recipient = record[key]
                lines.append(
                    "Recipient: "
                    + ", ".join(
                        str(recipient[k])
                        for k in ("name", "email", "city", "country_code")
                        if k in recipient and recipient[k]
                    )
                )
        action_id = (
            str(record["shipment_id"]) if "shipment_id" in record else identifier
        )
        if event.startswith("Shipment"):
            lines.append(f"To act: get_shipment id={action_id}.")
        elif event.startswith("Orders"):
            lines.append(f"To act: get_sales_order id={identifier}.")
        lines.append("Record: " + json.dumps(record, ensure_ascii=False, default=str))
        return {
            "text": "\n".join(lines),
            "title": f"Shipmondo {event} · {identifier}",
            "conversation_key": f"shipmondo:{event.split('.')[0]}:{action_id}",
        }
