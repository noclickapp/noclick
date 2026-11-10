"""Just Eat UK Delivery as a Service operations and authenticated delivery notifications.

Routes, fields and TOKEN webhook authentication follow the published JET OpenAPI
1.0.0 at https://uk.api.just-eat.io/docs/openapi.yaml. Tokens are supplied by the
partner; this node does not impersonate a consumer or register an OAuth app.
"""
from __future__ import annotations

import hmac
import json
import secrets
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

DOCS = "https://uk.api.just-eat.io/docs/openapi.yaml"
BASE = "https://api-daas-produk.skipthedishes.com"
EVENTS = ("COURIERJOBSTATUS", "CANCELJOBSTATUS", "COURIERCOLLECTIONTIME", "DELIVERYCREATED",
          "COURIERLOCATION", "DELIVERYREJECTED", "COURIERDELIVERYTIME", "PROOFOFDELIVERY", "PROOFOFDELIVERY_PICTURE")


class JustEatTokenCredential(BaseModel):
    model_config = ConfigDict(title="Just Eat UK Delivery Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.just-eat.com/",
        "x-credential-instructions": "Paste an existing UK Delivery as a Service bearer token issued to your partner account. "
        "NoClick reads your collection points to check the connection. Tokens expire; replace an expired token here. "
        "This is the delivery partner API, not a Just Eat consumer login or JET Connect API key.",
    })
    credential_type: Literal["just_eat_token"] = Field("just_eat_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Delivery API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Delivery API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without the Bearer prefix or whitespace")
        return value


def text(title, *, required=False, description=""):
    return (str if required else Optional[str], Field(... if required else None, title=title, description=description))


def json_text(title, *, required=False, description=""):
    return (str if required else Optional[str], Field(... if required else None, title=title, description=description,
            json_schema_extra={"ui:widget": "textarea"}))


REQUEST_ID = {"request_id": text("Request ID", required=True, description="Use the requestId returned by Estimate Delivery; estimates expire after five minutes.")}
COLLECT_ID = {"collect_point_id": text("Collection point ID", required=True)}
NOTIFICATIONS = {
    "email": text("Notification contact email", required=True),
    "endpoint": text("HTTPS delivery endpoint", required=True),
    "secret": (str, Field(..., title="Delivery authentication token", json_schema_extra={"ui:widget": "password"})),
    "subscriptions_json": json_text("Event subscriptions (JSON)", description="JSON array of documented event names. Omit for all events; [] unsubscribes from all."),
}
# Each entry is exactly one published operation. Body names preserve provider casing.
OPERATIONS = {
    "estimate_delivery": ("Estimate Delivery", "POST", "/v1/delivery/estimate", {
        **COLLECT_ID, "delivery_json": json_text("Delivery address (JSON)", required=True,
            description="Object with name, emailAddress, phoneNumber, address and city; optional province, postalCode and geolocation."),
        "delivery_details_json": json_text("Delivery details (JSON)"),
        "delivery_options_json": json_text("Delivery options (JSON)"),
        "item_list_json": json_text("Items (JSON array)"),
        "target_deliver_time": (Optional[datetime], Field(None, title="Target delivery time")),
        "target_collect_time": (Optional[datetime], Field(None, title="Target collection time")),
    }),
    "create_delivery": ("Create Delivery", "POST", "/v1/delivery", {
        **REQUEST_ID, "special_instructions": (Optional[str], Field(None, max_length=255)),
        "target_collect_time": (Optional[datetime], Field(None, title="Target collection time", description="Required unless the estimate specified a target delivery time.")),
        "tip": (Optional[int], Field(None, ge=0, description="Courier tip in minor currency units.")),
        "order_value": (Optional[int], Field(None, ge=0, description="Order value in minor currency units.")),
        "vendor_order_id": text("Your order ID"),
        "payment_type": (Optional[Literal["PREPAID"]], Field(None, title="Payment type", description="Cash on delivery is not supported in the UK.")),
        "metadata_json": json_text("Custom identifiers (JSON)"),
    }),
    "get_delivery_status": ("Get Delivery Status", "GET", "/v1/delivery/status/{request_id}", REQUEST_ID),
    "cancel_delivery": ("Cancel Delivery", "PUT", "/v1/delivery/cancellation-request", REQUEST_ID),
    "list_collect_points": ("List Collection Points", "GET", "/v1/delivery/collect-points", {
        "limit": (int, Field(100, ge=1, le=100)), "offset": (int, Field(0, ge=0)),
    }),
    "request_assistance": ("Request Delivery Assistance", "POST", "/v1/delivery/request-assistance", {
        **REQUEST_ID, **COLLECT_ID,
        "reason": (Literal["COLLECTION_TIME_UPDATE", "REPORT_COURIER_DELAY", "REPORT_BAD_COURIER_BEHAVIOUR", "OTHER_CUSTOMER_CONCERNS", "SPECIAL_INSTRUCTIONS_INQUIRY", "OTHER_ORDER_ISSUES"], Field(..., title="Reason")),
    }),
    "get_notification_config": ("Get Notification Configuration", "GET", "/v1/delivery/notification-config", {}),
    "create_notification_config": ("Create Notification Configuration", "POST", "/v1/delivery/notification-config", NOTIFICATIONS),
    "update_notification_config": ("Update Notification Configuration", "PATCH", "/v1/delivery/notification-config", {
        "email": text("Notification contact email"), "endpoint": text("HTTPS delivery endpoint"),
        "secret": (Optional[str], Field(None, title="Delivery authentication token", json_schema_extra={"ui:widget": "password"})),
        "subscriptions_json": json_text("Event subscriptions (JSON)"),
    }),
    "delete_notification_config": ("Delete Notification Configuration", "DELETE", "/v1/delivery/notification-config", {}),
    "simulate_delivery": ("Simulate Delivery", "POST", "/v1/delivery/simulate", {
        **REQUEST_ID,
        "delivery_step": (Optional[Literal["ASSIGNED", "IN_TRANSIT_TO_COLLECT", "ARRIVED_TO_COLLECT", "COLLECTED", "IN_TRANSIT_TO_DELIVER", "ARRIVED_TO_DELIVER", "DELIVERED", "CANCELLED", "RETURN_INITIATED", "IN_TRANSIT_TO_RETURN", "RETURNED"]], Field(None, title="Delivery step")),
        "step_wait_duration": (Optional[int], Field(None, title="Step wait duration", description="Milliseconds between simulation steps.")),
    }),
}
WIRE_NAMES = {"request_id": "requestId", "special_instructions": "specialInstructions", "target_collect_time": "targetCollectTime",
    "target_deliver_time": "targetDeliverTime", "order_value": "orderValue", "vendor_order_id": "vendorOrderId",
    "payment_type": "paymentType", "delivery_step": "deliveryStep", "step_wait_duration": "stepWaitDuration",
    "delivery_details_json": "deliveryDetails", "delivery_options_json": "deliveryOptions", "item_list_json": "itemList"}


class _OperationConfig(BaseModel):
    @model_validator(mode="after")
    def check_dates_and_endpoint(self):
        if getattr(self, "target_deliver_time", None) and getattr(self, "target_collect_time", None):
            raise ValueError("Specify only one target collection or delivery time")
        if getattr(self, "endpoint", None) and not self.endpoint.startswith("https://"):
            raise ValueError("Notification endpoint must use HTTPS")
        return self


CONFIG_MODELS = {}
for name, (label, method, path, fields) in OPERATIONS.items():
    model = create_model("JustEat" + "".join(w.title() for w in name.split("_")) + "Config", __base__=_OperationConfig,
        __module__=__name__, operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "ui:hidden": True, "x-display-name": label, "x-category": "Delivery", "x-is-trigger": False})), **fields)
    CONFIG_MODELS[name] = model
    globals()[model.__name__] = model


class JustEatOnDeliveryEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_delivery_event"] = Field("on_delivery_event", title="On Delivery Event", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On Delivery Event", "x-is-trigger": True, "x-category": "Triggers"})
    email: str = Field(..., title="Notification contact email")
    replace_existing_configuration: Literal[True] = Field(..., title="Use this account's notification destination",
        description="Just Eat allows one configuration per client credential. Enabling this trigger replaces that destination. Use a dedicated partner credential for this workflow.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


JustEatConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (JustEatOnDeliveryEventConfig,)], Discriminator("operation")]


class JustEatNodeConfig(NodeConfig[JustEatConfig, JustEatTokenCredential]):
    pass


def _body(config):
    result = {}
    for field, value in config.model_dump(mode="json", exclude_none=True, exclude={"operation"}).items():
        if field == "collect_point_id":
            result["collect"] = {"id": value}
            continue
        if field.endswith("_json"):
            try:
                value = json.loads(value)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{field} must contain valid JSON") from exc
            expected = list if field in {"item_list_json", "subscriptions_json"} else dict
            if not isinstance(value, expected):
                raise ValueError(f"{field} must contain a JSON {expected.__name__}")
            if field == "subscriptions_json" and any(e not in set(EVENTS) - {"DELIVERYCREATED"} | {"ALL"} for e in value):
                raise ValueError("Choose documented notification subscription names")
        result[WIRE_NAMES.get(field, field.removesuffix("_json"))] = value
    if config.operation == "create_notification_config":
        result["type"] = "TOKEN"
    return result


class JustEatNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-just-eat"
    connection_evidence = ConnectionEvidence(operation="list_collect_points", noun="collection points")

    @classmethod
    def get_config_model(cls):
        return JustEatNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = JustEatTokenCredential.model_validate(credential)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": f"Bearer {credential.access_token}", "Accept": "application/json", "User-Agent": "NoClick/1.0"})
        if response.is_error:
            # Preserve the provider's rejection text, but never repeat a credential.
            detail = response.text.replace(credential.access_token, "[redacted]")[:1500]
            raise ValueError(f"Just Eat API {response.status_code}: {detail}")
        return response.json() if response.content else {"ok": True}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, JustEatNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Just Eat UK Delivery Token")
        op = self.config.config
        if isinstance(op, JustEatOnDeliveryEventConfig):
            payload = (self.node_data or {}).get("config", {}).get("_triggerPayload")
            return payload if isinstance(payload, dict) else {"status": "waiting", "operation": op.operation}
        _, method, path, _ = OPERATIONS[op.operation]
        params, body = None, None
        if op.operation == "get_delivery_status":
            path = path.replace("{request_id}", quote(op.request_id, safe=""))
        elif op.operation == "list_collect_points":
            params = {"limit": op.limit, "offset": op.offset}
        elif method in {"POST", "PUT", "PATCH"}:
            body = _body(op)
        result = await self._request(self.config.credentials.model_dump(), method, path, params=params, body=body)
        return {"status": "success", "operation": op.operation, "data": result}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        parsed = JustEatOnDeliveryEventConfig.model_validate({**config, "webhook_url": webhook_url})
        secret = secrets.token_urlsafe(32)
        await cls._request(credential, "POST", "/v1/delivery/notification-config", body={
            "email": parsed.email, "endpoint": webhook_url, "secret": secret, "type": "TOKEN"})
        return {"external_webhook_id": webhook_url, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not credential or not config.get("external_webhook_id"):
            return
        current = await cls._request(credential, "GET", "/v1/delivery/notification-config")
        # One destination per client credential: never delete another workflow's replacement.
        if current.get("endpoint") == config["external_webhook_id"]:
            await cls._request(credential, "DELETE", "/v1/delivery/notification-config")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: (config or {}).get(key) for key in ("email", "replace_existing_configuration")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        token = next((v for k, v in headers.items() if k.lower() == "x-api-key"), "")
        return bool(secret and token and hmac.compare_digest(str(secret).encode(), str(token).encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return isinstance(payload, dict) and payload.get("type") in EVENTS

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return payload

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("type") not in EVENTS:
            return None
        event_id, kind, timestamp = output.get("id"), output.get("type"), output.get("timestamp")
        data = output.get("data")
        request_id = data.get("requestId") if isinstance(data, dict) else None
        lines = [f"Just Eat UK delivery notification: {kind} at {timestamp}. Event ID: {event_id}."]
        if kind == "COURIERJOBSTATUS" and isinstance(data, dict):
            courier = data.get("courier") or {}
            lines.append(f"Courier {courier.get('name') or 'unassigned'}: {data.get('status')}. Order: {data.get('orderId')}.")
            if data.get("orderTrackerURL"):
                lines.append(f"Track delivery: {data['orderTrackerURL']}")
        return {"text": "\n".join(lines) + "\n"
            "Delivery details (requestId identifies the delivery for status, cancellation or assistance; orderId identifies the order):\n"
            + json.dumps(data, ensure_ascii=False, default=str), "title": f"Just Eat UK {kind}",
            "conversation_key": str(request_id or event_id)}
