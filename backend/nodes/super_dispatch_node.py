"""Super Dispatch Carrier API v1 operations.

Contract: https://developer.superdispatch.com/specs/superdispatch-carrier-public-api.yaml
Manual Bearer credentials: https://developer.superdispatch.com/carrier/docs/authentication/
Each operation makes one request; list pages and continuation metadata stay explicit.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union

import hmac

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

BASE_URL = "https://carrier.superdispatch.com/v1"


class SuperDispatchAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Super Dispatch API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.superdispatch.com/carrier/docs/authentication/",
            "x-credential-instructions": "Contact Super Dispatch support for a Carrier API key and paste it here without the Bearer prefix. An existing Carrier API access token also works until it expires; replace it when needed. NoClick sends it only to carrier.superdispatch.com. Connecting reads the carriers associated with your application; it does not verify permission for every operation. Shipper and Pricing Insights credentials are separate and are not supported by these operations.",
        })
    credential_type: Literal["super_dispatch_api_key"] = Field("super_dispatch_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="Carrier API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Carrier API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; fetch each page explicitly.")
    per_page: int = Field(20, ge=1, le=100, description="Maximum records per page.")


class Contact(_Input):
    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    phone2: str | None = None
    email: EmailStr | None = None
    company_name: str | None = None


class Venue(_Input):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    notes: str | None = None
    contact: Contact | None = None


class OrderStop(_Input):
    venue: Venue | None = None
    scheduled_at: date | None = None
    completed_at: datetime | None = None
    notes: str | None = None


class Payment(_Input):
    terms: str | None = None
    notes: str | None = None
    payment_method: str | None = None
    payment_terms: str | None = None


class Customer(_Input):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    contact: Contact | None = None


class VehicleInfo(_Input):
    year: int
    make: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    vin: str | None = None
    type: Literal["sedan", "suv", "truck", "van", "motorcycle", "boat", "atv", "rv", "trailer", "other"] | None = None
    color: str | None = None
    lot_number: str | None = None
    is_inoperable: bool = False
    requires_enclosed_trailer: bool = False
    price: float | None = None


class OrderBody(_Input):
    price: float = Field(..., description="Carrier pay amount.")
    pickup: OrderStop
    delivery: OrderStop
    vehicles: list[VehicleInfo] = Field(..., min_length=1, max_length=100)
    number: str | None = None
    buyer_number: str | None = None
    broker_fee: float | None = None
    instructions: str | None = None
    inspection_type: str | None = None
    driver_id: int | None = Field(None, ge=1)
    payment: Payment | None = None
    customer: Customer | None = None


class OrderChanges(_Input):
    """Partial order changes; omitted fields are preserved by the provider."""
    price: float | None = None
    instructions: str | None = None
    number: str | None = None
    buyer_number: str | None = None
    broker_fee: float | None = None
    inspection_type: str | None = None
    pickup: OrderStop | None = None
    delivery: OrderStop | None = None
    vehicles: list[VehicleInfo] | None = Field(None, min_length=1, max_length=100)
    payment: Payment | None = None
    customer: Customer | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one order field to change")
        if "price" in self.model_fields_set and self.price is None:
            raise ValueError("Price cannot be cleared")
        return self


class ListCarriers(_Page):
    """List carriers associated with this application."""
    operation: Literal["list_carriers"] = Field("list_carriers", json_schema_extra={"ui:hidden": True})


class GetCarrier(_Input):
    """Get carrier details."""
    operation: Literal["get_carrier"] = Field("get_carrier", json_schema_extra={"ui:hidden": True})
    carrier_id: int = Field(..., ge=1)


class ListDrivers(_Page):
    """List drivers belonging to a carrier."""
    operation: Literal["list_drivers"] = Field("list_drivers", json_schema_extra={"ui:hidden": True})
    carrier_id: int = Field(..., ge=1)


class GetDriver(_Input):
    """Get driver details."""
    operation: Literal["get_driver"] = Field("get_driver", json_schema_extra={"ui:hidden": True})
    driver_id: int = Field(..., ge=1)


class ListOrders(_Page):
    """List orders, optionally filtered by status."""
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"ui:hidden": True})
    status: Literal["unassigned", "assigned", "picked_up", "in_transit", "delivered", "archived", "billed", "paid"] | None = None


class GetOrder(_Input):
    """Get order details."""
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)


class CreateOrder(_Input):
    """Create an order with pickup, delivery and vehicles."""
    operation: Literal["create_order"] = Field("create_order", json_schema_extra={"ui:hidden": True})
    body: OrderBody


class UpdateOrder(_Input):
    """Partially update order fields; omitted fields stay unchanged."""
    operation: Literal["update_order"] = Field("update_order", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)
    body: OrderChanges


class DeleteOrder(_Input):
    """Permanently delete an order."""
    operation: Literal["delete_order"] = Field("delete_order", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)


class MarkOrderPickedUp(_Input):
    """Mark an order as picked up."""
    operation: Literal["mark_order_picked_up"] = Field("mark_order_picked_up", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)


class MarkOrderDelivered(_Input):
    """Mark an order as delivered."""
    operation: Literal["mark_order_delivered"] = Field("mark_order_delivered", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)


class AssignDriver(_Input):
    """Assign a driver to an order."""
    operation: Literal["assign_driver"] = Field("assign_driver", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)
    driver_id: int = Field(..., ge=1)


class UnassignDriver(_Input):
    """Remove the assigned driver from an order."""
    operation: Literal["unassign_driver"] = Field("unassign_driver", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)


class CancelOrder(_Input):
    """Cancel an order."""
    operation: Literal["cancel_order"] = Field("cancel_order", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)


class GetDriverLocation(_Input):
    """Get the assigned driver location for an order."""
    operation: Literal["get_driver_location"] = Field("get_driver_location", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)


class ListVehicles(_Input):
    """List vehicles in an order."""
    operation: Literal["list_vehicles"] = Field("list_vehicles", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)


class GetVehicle(_Input):
    """Get vehicle details."""
    operation: Literal["get_vehicle"] = Field("get_vehicle", json_schema_extra={"ui:hidden": True})
    vehicle_id: int = Field(..., ge=1)


class CreateVehicle(_Input):
    """Add a vehicle to an order."""
    operation: Literal["create_vehicle"] = Field("create_vehicle", json_schema_extra={"ui:hidden": True})
    order_id: int = Field(..., ge=1)
    body: VehicleInfo


class UpdateVehicle(_Input):
    """Replace vehicle details; provide all required fields."""
    operation: Literal["update_vehicle"] = Field("update_vehicle", json_schema_extra={"ui:hidden": True})
    vehicle_id: int = Field(..., ge=1)
    body: VehicleInfo


class DeleteVehicle(_Input):
    """Delete a vehicle from its order."""
    operation: Literal["delete_vehicle"] = Field("delete_vehicle", json_schema_extra={"ui:hidden": True})
    vehicle_id: int = Field(..., ge=1)


class ListOffers(_Page):
    """List offers for the application carriers."""
    operation: Literal["list_offers"] = Field("list_offers", json_schema_extra={"ui:hidden": True})
    status: Literal["pending", "accepted", "declined", "expired"] | None = None


class GetOffer(_Input):
    """Get offer details."""
    operation: Literal["get_offer"] = Field("get_offer", json_schema_extra={"ui:hidden": True})
    offer_id: int = Field(..., ge=1)


class AcceptOffer(_Input):
    """Accept a pending load offer."""
    operation: Literal["accept_offer"] = Field("accept_offer", json_schema_extra={"ui:hidden": True})
    offer_id: int = Field(..., ge=1)


class DeclineOffer(_Input):
    """Decline a pending load offer."""
    operation: Literal["decline_offer"] = Field("decline_offer", json_schema_extra={"ui:hidden": True})
    offer_id: int = Field(..., ge=1)


ORDER_EVENTS = (
    "order.created", "order.updated", "order.assigned", "order.picked_up",
    "order.delivered", "order.cancelled",
)


class OnOrderEvent(WebhookTriggerConfigBase):
    """Start a workflow or agent when an order changes in Carrier TMS."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_order_event"] = Field("on_order_event", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "On Order Event",
    })
    event_type: Literal[*ORDER_EVENTS] = Field(
        "order.created", title="Order event", description="The order change that starts this workflow.",
        json_schema_extra={"enumNames": ["Order created", "Order updated", "Driver assigned", "Order picked up", "Order delivered", "Order cancelled"]})
    webhook_url: str | None = Field(None, title="Webhook URL",
        description="Registered automatically. Super Dispatch allows one subscription per event per application; use a separate application for another workflow listening to the same event.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


SuperDispatchConfig = Annotated[Union[
    OnOrderEvent, ListCarriers, GetCarrier, ListDrivers, GetDriver, ListOrders, GetOrder, CreateOrder, UpdateOrder, DeleteOrder, MarkOrderPickedUp, MarkOrderDelivered, AssignDriver, UnassignDriver, CancelOrder, GetDriverLocation, ListVehicles, GetVehicle, CreateVehicle, UpdateVehicle, DeleteVehicle, ListOffers, GetOffer, AcceptOffer, DeclineOffer
], Field(discriminator="operation")]


class SuperDispatchFullConfig(NodeConfig[SuperDispatchConfig, SuperDispatchAPIKeyCredential]):
    pass


# One fixed provider operation per discriminator; no arbitrary endpoint escape hatch.
ROUTES = {
    "list_carriers": ("GET", "/carriers/", None),
    "get_carrier": ("GET", "/carriers/{id}/", 'carrier_id'),
    "list_drivers": ("GET", "/carriers/{id}/drivers/", 'carrier_id'),
    "get_driver": ("GET", "/drivers/{id}/", 'driver_id'),
    "list_orders": ("GET", "/orders/", None),
    "get_order": ("GET", "/orders/{id}/", 'order_id'),
    "create_order": ("POST", "/orders/", None),
    "update_order": ("PATCH", "/orders/{id}/", 'order_id'),
    "delete_order": ("DELETE", "/orders/{id}/", 'order_id'),
    "mark_order_picked_up": ("POST", "/orders/{id}/mark-as-picked-up/", 'order_id'),
    "mark_order_delivered": ("POST", "/orders/{id}/mark-as-delivered/", 'order_id'),
    "assign_driver": ("POST", "/orders/{id}/assign-driver/", 'order_id'),
    "unassign_driver": ("POST", "/orders/{id}/unassign-driver/", 'order_id'),
    "cancel_order": ("POST", "/orders/{id}/cancel/", 'order_id'),
    "get_driver_location": ("GET", "/orders/{id}/driver_location/", 'order_id'),
    "list_vehicles": ("GET", "/orders/{id}/vehicles/", 'order_id'),
    "get_vehicle": ("GET", "/vehicles/{id}/", 'vehicle_id'),
    "create_vehicle": ("POST", "/orders/{id}/vehicles/", 'order_id'),
    "update_vehicle": ("PUT", "/vehicles/{id}/", 'vehicle_id'),
    "delete_vehicle": ("DELETE", "/vehicles/{id}/", 'vehicle_id'),
    "list_offers": ("GET", "/offers/", None),
    "get_offer": ("GET", "/offers/{id}/", 'offer_id'),
    "accept_offer": ("POST", "/offers/{id}/accept/", 'offer_id'),
    "decline_offer": ("POST", "/offers/{id}/decline/", 'offer_id'),
}


class SuperDispatchNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-super-dispatch"
    connection_evidence = ConnectionEvidence(noun="carriers", operation="list_carriers")

    @classmethod
    def get_config_model(cls):
        return SuperDispatchFullConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": config.get("event_type", "order.created")}

    @classmethod
    async def _subscription_request(cls, credential, event, method, webhook_url=None):
        if event not in ORDER_EVENTS:
            raise ValueError("Choose a supported Super Dispatch order event")
        key = SuperDispatchAPIKeyCredential.model_validate(credential or {}).api_key
        kwargs = {"headers": {"Authorization": "Bearer " + key, "Accept": "application/json"}}
        if method == "POST":
            kwargs["json"] = {"callback_url": webhook_url}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + f"/webhooks/{event}/subscriptions/", **kwargs)
        except httpx.RequestError:
            raise ValueError("Super Dispatch could not be reached; retry trigger registration") from None
        if method == "DELETE" and response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            # The provider may echo both the API key and the callback URL. Keep errors local.
            raise ValueError(f"Super Dispatch webhook {method} failed (HTTP {response.status_code})")
        if method == "DELETE":
            return None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Super Dispatch returned an invalid webhook subscription") from None
        if not isinstance(payload, dict):
            raise ValueError("Super Dispatch returned an invalid webhook subscription")
        # The current webhook docs show a top-level subscription, including this token.
        # The OpenAPI 1.0.0 response incorrectly omits the token and wraps callback_url in data.
        secret = payload.get("verification_token")
        if not isinstance(secret, str) or not secret:
            raise ValueError("Super Dispatch did not return a webhook verification token")
        return {"external_webhook_id": event, "signing_secret": secret}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        return await cls._subscription_request(
            credential, config.get("event_type", "order.created"), "POST", webhook_url)

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        event = config.get("external_webhook_id")
        if event:
            await cls._subscription_request(credential, event, "DELETE")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        """The provider uses a shared verification token, not a body HMAC.

        https://developer.superdispatch.com/carrier/docs/webhooks/#verifying-webhook-requests
        """
        expected = config.get("signing_secret")
        received = next((v for k, v in headers.items()
                         if k.lower() == "x-super-dispatch-verification-token"), None)
        return bool(isinstance(expected, str) and expected and isinstance(received, str)
                    and hmac.compare_digest(expected.encode(), received.encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        # Use the current provider docs' action field; OpenAPI's event_type is stale.
        return bool(isinstance(payload, dict)
                    and payload.get("action") == config.get("event_type", "order.created")
                    and isinstance(payload.get("data"), dict))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return cls.no_event_output("on_order_event")
        # Do not expose the inbound verification token carried in _webhook headers.
        return {"status": "success", "action": payload["action"],
                "guid": payload.get("guid"), "occurred_at": payload.get("occurred_at"),
                "data": payload["data"]}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("action") not in ORDER_EVENTS:
            return None
        order = output.get("data")
        if not isinstance(order, dict) or not order.get("id"):
            return None
        order_id = order["id"]
        happened = output["action"].removeprefix("order.").replace("_", " ")
        lines = [f"Super Dispatch order {order_id} {happened}."]
        if order.get("status"):
            lines.append(f"Order status: {order['status']}")
        if output.get("occurred_at"):
            lines.append(f"Occurred at: {output['occurred_at']}")
        if output.get("guid"):
            lines.append(f"Delivery ID: {output['guid']}")
        lines.append(f"To act: get_order order_id={order_id}; use update_order or assign_driver with the same order_id.")
        return {"text": "\n".join(lines), "conversation_key": str(order_id),
                "title": f"Super Dispatch order {order_id}"}

    async def execute(self, inputs):
        if isinstance(self.config.config, OnOrderEvent):
            return self.no_event_output("on_order_event", "Waiting for a Super Dispatch order event")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Super Dispatch Carrier API key")
        op = self.config.config
        method, path, id_field = ROUTES[op.operation]
        if id_field:
            path = path.replace("{id}", str(getattr(op, id_field)))
        params = {}
        if isinstance(op, _Page):
            params = {"page": op.page, "per_page": op.per_page}
            if getattr(op, "status", None) is not None:
                params["status"] = op.status
        kwargs = {"params": params, "headers": {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}}
        if hasattr(op, "body"):
            kwargs["json"] = op.body.model_dump(mode="json", exclude_unset=True)
        elif isinstance(op, AssignDriver):
            kwargs["json"] = {"driver_id": op.driver_id}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, **kwargs)
            if not 200 <= response.status_code < 300:
                return self._failure(response, credential.api_key)
            if response.status_code == 204:
                return {"status": "success", "deleted": True}
            if len(response.content) > 10_000_000:
                raise ValueError("Super Dispatch returned an oversized response")
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime != "application/json":
                raise ValueError("Super Dispatch returned a non-JSON response")
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Super Dispatch returned an unexpected response")
            meta = payload.get("meta")
            if isinstance(meta, dict) and isinstance(meta.get("code"), int) and meta["code"] >= 400:
                return self._failure(response, credential.api_key, meta["code"])
            if "errors" in payload or "error" in payload:
                return self._failure(response, credential.api_key)
            data = payload.get("data")
            if op.operation.startswith("list_"):
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError("Super Dispatch returned an unexpected list")
            elif not isinstance(data, dict):
                raise ValueError("Super Dispatch returned an unexpected record")
            result = {"status": "success", "data": data}
            if isinstance(meta, dict):
                result["meta"] = meta
            if "pagination" in payload:
                if not isinstance(payload["pagination"], dict):
                    raise ValueError("Super Dispatch returned invalid pagination")
                # Preserve the provider metadata; never follow URLs from a response.
                result["pagination"] = payload["pagination"]
            return result
        except httpx.RequestError:
            raise ValueError("Super Dispatch could not be reached; retry the operation") from None

    @staticmethod
    def _failure(response, secret, status_code=None):
        message = "Super Dispatch request failed"
        try:
            body = response.json()
            if isinstance(body, dict):
                raw = body.get("message") or body.get("error") or body.get("errors")
                if isinstance(raw, (str, dict, list)):
                    message = str(raw).replace(secret, "[redacted]")[:500]
        except ValueError:
            pass
        return {"status": "error", "error": message, "status_code": status_code or response.status_code}
