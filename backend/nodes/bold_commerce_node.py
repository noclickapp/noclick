"""Bold Subscriptions actions and signed webhook triggers for Bold Commerce.

Routes and payloads follow the published Subscriptions 1.0 OpenAPI contract;
private API access tokens use the Bearer header shown in Bold's quick start.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.boldcommerce.com/subscriptions/v1/shops"
DOCS = "https://developer.boldcommerce.com/guides/subscriptions-v2/quick-start"
ShopIdentifier = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=128)]
ResourceID = Annotated[int, Field(ge=1)]
DateTime = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$", json_schema_extra={"format": "date-time"})]


class BoldCommerceTokenCredential(BaseModel):
    model_config = ConfigDict(title="Bold Commerce API Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://account.boldcommerce.com/",
        "x-credential-instructions": "In Bold Account Center, open API access tokens and create a private token with the Subscriptions, Customers, Orders, Shops and Subscription Groups permissions needed by your workflows. Paste the token and your shop identifier. Find the identifier with GET https://api.boldcommerce.com/shops/v1/info, as described in Bold's Making API Calls guide. NoClick checks your shop information before saving.",
        "x-help-url": DOCS,
    })
    credential_type: Literal["bold_commerce_token"] = Field("bold_commerce_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Access Token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    shop_identifier: ShopIdentifier = Field(..., title="Shop Identifier", description="Your Bold shop identifier, without a URL or path.")

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if not value or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API access token without a Bearer prefix")
        return value


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    fields: dict[str, tuple[Any, Any]]
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    envelope: str | None = None


def optional_text(title):
    return (str | None, Field(None, title=title))


def resource(name):
    return {name: (ResourceID, Field(..., title=name.replace("_", " ").title()))}


SUB = resource("subscription_id")
CUSTOMER = resource("customer_id")
PAGE = {"page": (int, Field(1, ge=1, title="Page")), "limit": (int, Field(50, ge=1, le=100, title="Page Size"))}
OPERATIONS = {
    "get_shop": Operation("Get Shop Information", "GET", "/shop", {}),
    "list_customers": Operation("List Customers", "GET", "/customers", {
        **PAGE, "search": optional_text("Search"), "status": (Literal["all", "active", "inactive"], Field("all", title="Status"))},
        query=("page", "limit", "search", "status")),
    "get_customer": Operation("Get Customer", "GET", "/customers/{customer_id}", CUSTOMER),
    "update_customer": Operation("Update Customer", "PUT", "/customers/{customer_id}", {
        **CUSTOMER, **{key: (str, Field(..., title=key.replace("_", " ").title())) for key in ("first_name", "last_name", "email", "phone", "notes")}},
        body=("first_name", "last_name", "email", "phone", "notes"), envelope="customer"),
    "list_customer_addresses": Operation("List Customer Addresses", "GET", "/customers/{customer_id}/addresses", CUSTOMER),
    "list_customer_subscriptions": Operation("List Customer Subscriptions", "GET", "/customers/{customer_id}/subscriptions", CUSTOMER),
    "list_subscriptions": Operation("List Subscriptions", "GET", "/subscriptions", {
        "limit": (int, Field(50, ge=1, le=100, title="Page Size")), "cursor": optional_text("Cursor"),
        "subscription_status": (Literal["active", "inactive", "processing", "scheduled", "paused"] | None, Field(None, title="Subscription Status")),
        "bold_platform_customer_id": optional_text("Bold Platform Customer ID"),
        "expand": (Literal["customer"] | None, Field(None, title="Expand")),
        "filter": optional_text("Filter")}, query=("limit", "cursor", "subscription_status", "bold_platform_customer_id", "expand", "filter")),
    "get_subscription": Operation("Get Subscription", "GET", "/subscriptions/{subscription_id}", SUB),
    "update_discount_code": Operation("Apply Discount Code", "PUT", "/subscriptions/{subscription_id}/discount_code", {
        **SUB, "discount_code": (str, Field(..., min_length=1, title="Discount Code"))}, body=("discount_code",)),
    "remove_discount_code": Operation("Remove Discount Code", "DELETE", "/subscriptions/{subscription_id}/discount_code", SUB),
    "update_next_order_datetime": Operation("Change Next Order Date", "PUT", "/subscriptions/{subscription_id}/next_order_datetime", {
        **SUB, "nextDate": (DateTime, Field(..., title="Next Order Date")),
        "includeFutureOrders": (bool, Field(False, title="Adjust Future Orders Too"))}, body=("nextDate", "includeFutureOrders")),
    "skip_order": Operation("Skip Subscription Order", "PUT", "/subscriptions/{subscription_id}/skip", {
        **SUB, "date": (DateTime, Field(..., title="Order Date"))}, body=("date",)),
    "recover_order": Operation("Unskip Subscription Order", "PUT", "/subscriptions/{subscription_id}/recover", {
        **SUB, "date": (DateTime, Field(..., title="Skipped Order Date"))}, body=("date",)),
    "cancel_subscription": Operation("Cancel Subscription", "POST", "/subscriptions/{subscription_id}/cancel", SUB),
    "pause_subscription": Operation("Pause Subscription", "POST", "/subscriptions/{subscription_id}/pause", SUB),
    "reactivate_subscription": Operation("Reactivate Subscription", "POST", "/subscriptions/{subscription_id}/activate", SUB),
    "list_orders": Operation("List Subscription Orders", "GET", "/subscriptions/{subscription_id}/orders", {**SUB, **PAGE}, query=("page", "limit")),
    "get_order": Operation("Get Subscription Order", "GET", "/subscriptions/{subscription_id}/orders/{order_id}", {**SUB, **resource("order_id")}),
    "list_future_orders": Operation("List Future Subscription Orders", "GET", "/subscriptions/{subscription_id}/future_orders", SUB),
    "list_payment_methods": Operation("List Subscription Payment Methods", "GET", "/subscriptions/{subscription_id}/payment_methods", SUB),
    "list_subscription_groups": Operation("List Subscription Groups", "GET", "/subscription_groups", {}),
    "get_subscription_group": Operation("Get Subscription Group", "GET", "/subscription_groups/{group_id}", resource("group_id")),
}

CONFIG_MODELS = {}
for _name, _spec in OPERATIONS.items():
    CONFIG_MODELS[_name] = create_model(
        "BoldCommerce" + "".join(p.title() for p in _name.split("_")) + "Config",
        operation=(Literal[_name], Field(_name, title=_spec.label, json_schema_extra={
            "ui:hidden": True, "x-display-name": _spec.label,
            "x-category": "Customers" if "customer" in _name else "Subscriptions"})),
        **_spec.fields,
    )

SUBSCRIPTION_EVENTS = ("subscription_created", "subscription_updated", "subscription_cancelled", "subscription_paused", "subscription_payment_failed")
CUSTOMER_EVENTS = ("customer_created", "customer_updated")
ORDER_EVENTS = ("subscription_order_created",)
TRIGGER_EVENTS = {"on_subscription_event": SUBSCRIPTION_EVENTS, "on_customer_event": CUSTOMER_EVENTS, "on_order_created": ORDER_EVENTS}


class _Trigger(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered with Bold automatically.", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


for _name, _events in TRIGGER_EVENTS.items():
    _label = {"on_subscription_event": "On Subscription Event", "on_customer_event": "On Customer Event", "on_order_created": "On Subscription Order Created"}[_name]
    CONFIG_MODELS[_name] = create_model(
        "BoldCommerce" + "".join(p.title() for p in _name.split("_")) + "Config", __base__=_Trigger,
        operation=(Literal[_name], Field(_name, title=_label, json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": _label})),
        event_type=(Literal[*_events], Field(_events[0], title="Event Type")),
    )

BoldCommerceConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class BoldCommerceNodeConfig(NodeConfig[BoldCommerceConfig, BoldCommerceTokenCredential]):
    pass


class BoldCommerceNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-bold-commerce"
    connection_evidence = ConnectionEvidence(
        noun="shop", identity_operation="get_shop",
        identity_keys=("shop_domain", "shop_owner", "admin_email"),
    )

    @classmethod
    def get_config_model(cls):
        return BoldCommerceNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        cred = credential if isinstance(credential, BoldCommerceTokenCredential) else BoldCommerceTokenCredential.model_validate(credential)
        url = f"{BASE}/{quote(cred.shop_identifier, safe='')}{path}"
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, url, params=params, **({"json": body} if body is not None else {}), headers={
                "Authorization": f"Bearer {cred.api_token}", "Accept": "application/json", "Bold-API-Version-Date": "2022-05-01"})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                error = response.json()
                message = error.get("message") if isinstance(error, dict) else None
            except ValueError:
                message = None
            if isinstance(message, str) and message:
                raise httpx.HTTPStatusError(
                    f"Bold Commerce API {response.status_code}: {message}",
                    request=response.request, response=response,
                ) from None
            raise exc
        return response.json() if response.content else {}

    async def execute(self, inputs):
        if not isinstance(self.config, BoldCommerceNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Bold Commerce account")
        config = self.config.config
        if config.operation in TRIGGER_EVENTS:
            return self.resolve_trigger_payload(inputs, config.model_dump())
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in spec.query if key in values}
        body = {key: values[key] for key in spec.body if key in values} if spec.body else None
        if spec.envelope:
            body = {spec.envelope: body}
        result = await self._request(self.config.credentials, spec.method, path, params=params, body=body)
        return {"status": "success", "operation": config.operation, "data": result}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        operation = config.get("operation")
        event = config.get("event_type") or TRIGGER_EVENTS.get(operation, (None,))[0]
        if event not in TRIGGER_EVENTS.get(operation, ()):
            raise ValueError("Choose a supported Bold event")
        topics = await cls._request(credential, "GET", "/webhooks/topics")
        topic_id = next((t["id"] for t in topics["webhook_topics"] if t["topic_name"] == event), None)
        if topic_id is None:
            raise ValueError("This Bold shop does not offer the selected webhook topic")
        secret = secrets.token_hex(32)
        result = await cls._request(credential, "POST", "/webhooks/subscriptions", body={"webhook_subscription": {
            "webhook_topic_id": topic_id, "callback_url": webhook_url, "shared_secret": secret}})
        endpoint_id = result["webhook_subscription"].get("id")
        if endpoint_id is None:
            raise ValueError("Bold did not return a webhook subscription ID")
        return {"external_webhook_id": str(endpoint_id), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = config.get("external_webhook_id")
        if endpoint_id is not None and credential:
            if not re.fullmatch(r"[0-9]+", str(endpoint_id)):
                raise ValueError("Invalid Bold webhook subscription ID")
            await cls._request(credential, "DELETE", f"/webhooks/subscriptions/{endpoint_id}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": config.get("event_type")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Bold Subscriptions: SHA-256 HMAC of the original payload, shared_secret
        # and x-bold-signature, per /guides/subscriptions-v2/webhooks.
        secret = config.get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-bold-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        headers = payload.get("_webhook", {}).get("headers", {})
        event = next((v for k, v in headers.items() if k.lower() == "event-identifier"), None)
        expected = config.get("event_type") or TRIGGER_EVENTS.get(config.get("operation"), (None,))[0]
        return event is not None and event == expected

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": config.get("operation"), "event_type": config.get("event_type") or TRIGGER_EVENTS.get(config.get("operation"), (None,))[0], "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output.get("data", {})
        event = output.get("event_type", "")
        if event in CUSTOMER_EVENTS:
            identifier = payload.get("id")
            who = " ".join(str(payload.get(k) or "") for k in ("first_name", "last_name")).strip()
            text = f"Bold Commerce {event}: {who} ({payload.get('email', '')}), customer ID {identifier}."
            text += f"\nPhone: {payload.get('phone', '')}\nNotes: {payload.get('notes', '')}"
        elif event in ORDER_EVENTS:
            identifier = payload.get("id")
            text = f"Bold Commerce subscription order created: order ID {identifier}, subscription ID {payload.get('subscription_id')}, shop ID {payload.get('shop_id')}."
            order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
            text += f"\nCreated: {payload.get('created_at')}\nPlatform customer ID: {order.get('platform_customer_id')}"
            text += f"\nOrder number: {order.get('order_number')}\nTotal: {order.get('total')} {order.get('currency')} (provider monetary units)"
            text += f"\nFulfillment: {order.get('fulfillment_status')}\nURL: {order.get('url')}"
            text += f"\nTo act, use get_order with subscription_id={payload.get('subscription_id')} and order_id={identifier}."
        else:
            identifier = payload.get("id")
            text = f"Bold Commerce {event}: subscription ID {identifier}, customer ID {payload.get('customer_id')}, shop ID {payload.get('shop_id')}."
            text += f"\nStatus: {payload.get('subscription_status')}\nNext order: {payload.get('next_order_datetime')}\nNote: {payload.get('note')}\nOrder note: {payload.get('order_note')}"
            text += f"\nTo act, use get_subscription or update_next_order_datetime with subscription_id={identifier}."
        entity = "customer" if event in CUSTOMER_EVENTS else "order" if event in ORDER_EVENTS else "subscription"
        return {"text": text, "conversation_key": f"bold:{entity}:{identifier}", "title": f"Bold Commerce {event.replace('_', ' ')}"}
