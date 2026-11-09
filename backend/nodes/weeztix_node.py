"""Weeztix dashboard API 3.0.0: fixed, one-request operations.

Contract: https://eventix-docs.s3.eu-west-1.amazonaws.com/dashboard
Authentication: https://docs.weeztix.com/docs/introduction/issue-request/
Lists return the provider's entire collection; this API declares no pagination.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.weeztix import WEEZTIX_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.weeztix.com/3.0.0"
Guid = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", json_schema_extra={"format": "uuid"})]
OrderID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]


class WeeztixOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Weeztix Account", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "weeztix",
            "x-oauth-scopes": sorted(WEEZTIX_SCOPES.declared_scopes()),
            "x-credential-url": "https://dashboard.weeztix.com/",
            "x-credential-instructions": "Sign in to Weeztix and authorize access to your companies. Your Weeztix roles determine which reads and writes are allowed. Access tokens expire and refresh tokens rotate automatically. Weeztix currently does not use OAuth scopes.",
        })
    credential_type: Literal["weeztix_oauth"] = Field("weeztix_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=8192, title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token Expiry")
    scope: str | None = None
    token_type: Literal["Bearer"] = "Bearer"
    name: str | None = None

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste a token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    company_id: Guid | None = Field(None, description="Optional company GUID to restrict access using the Company header. Omit to use the companies authorized at sign-in.")


class _EventID(_Input):
    event_id: Guid = Field(..., title="Event ID")


class _TicketID(_Input):
    ticket_id: Guid = Field(..., title="Ticket Type ID")


class _OrderID(_Input):
    order_id: OrderID = Field(..., title="Order ID")


class _ShopID(_Input):
    shop_id: Guid = Field(..., title="Shop ID")


class ListEvents(_Input):
    """List events visible to the connected companies."""
    operation: Literal["list_events"] = "list_events"
    type: Literal["normal", "trashed", "justtrashed", "past", "upcoming"] = "normal"


class GetEvent(_EventID):
    operation: Literal["get_event"] = "get_event"


class UpdateEvent(_EventID):
    """Update event details and sale status; only supplied fields are sent."""
    operation: Literal["update_event"] = "update_event"
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=65536)
    email_info: str | None = Field(None, max_length=1000)
    status: Literal["disabled", "normal", "sold_out", "refunding", "moving"] | None = None

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, k) is None for k in ("name", "description", "email_info", "status")):
            raise ValueError("Supply at least one event field to update")
        return self


class ListEventDates(_EventID):
    operation: Literal["list_event_dates"] = "list_event_dates"


class GetEventScanningStats(_EventID):
    operation: Literal["get_event_scanning_stats"] = "get_event_scanning_stats"


class ListEventTickets(_EventID):
    operation: Literal["list_event_tickets"] = "list_event_tickets"
    type: Literal["normal", "trashed", "justtrashed"] = "normal"


class ListEventShops(_EventID):
    operation: Literal["list_event_shops"] = "list_event_shops"


class GetTicket(_TicketID):
    operation: Literal["get_ticket"] = "get_ticket"


class UpdateTicket(_TicketID):
    """Update ticket type name, description or order limits."""
    operation: Literal["update_ticket"] = "update_ticket"
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=65536)
    min_orderable_amount_per_order: int | None = Field(None, ge=1)
    max_orderable_amount_per_order: int | None = Field(None, ge=1, le=250)

    @model_validator(mode="after")
    def changed(self):
        fields = ("name", "description", "min_orderable_amount_per_order", "max_orderable_amount_per_order")
        if all(getattr(self, k) is None for k in fields):
            raise ValueError("Supply at least one ticket field to update")
        if self.min_orderable_amount_per_order is not None and self.max_orderable_amount_per_order is not None and self.min_orderable_amount_per_order > self.max_orderable_amount_per_order:
            raise ValueError("Minimum order amount must not exceed maximum")
        return self


class GetOrder(_OrderID):
    operation: Literal["get_order"] = "get_order"


class UpdateOrderReceiver(_OrderID):
    """Update receiver details; Weeztix also rebuilds the tickets."""
    operation: Literal["update_order_receiver"] = "update_order_receiver"
    email: str | None = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", json_schema_extra={"format": "email"})
    firstName: str | None = Field(None, min_length=1, max_length=255, title="First Name")
    lastName: str | None = Field(None, min_length=1, max_length=255, title="Last Name")
    locale: str | None = Field(None, min_length=1, max_length=35)

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, k) is None for k in ("email", "firstName", "lastName", "locale")):
            raise ValueError("Supply at least one receiver field to update")
        return self


class GetOrderDownloadLink(_OrderID):
    operation: Literal["get_order_download_link"] = "get_order_download_link"


class ResendOrderConfirmation(_OrderID):
    """Request a confirmation email resend (admin only); 204 acknowledges the job, not delivery."""
    operation: Literal["resend_order_confirmation"] = Field("resend_order_confirmation", json_schema_extra={"x-operation-kind": "write"})


class ListOrderEmails(_OrderID):
    operation: Literal["list_order_emails"] = "list_order_emails"


class GetShop(_ShopID):
    operation: Literal["get_shop"] = "get_shop"


class ListShopTickets(_ShopID):
    operation: Literal["list_shop_tickets"] = "list_shop_tickets"


class ListShopProducts(_ShopID):
    operation: Literal["list_shop_products"] = "list_shop_products"


class AttachShopTicket(_ShopID):
    operation: Literal["attach_shop_ticket"] = "attach_shop_ticket"
    ticket_id: Guid = Field(..., title="Ticket Type ID")


class DetachShopTicket(_ShopID):
    operation: Literal["detach_shop_ticket"] = "detach_shop_ticket"
    ticket_id: Guid = Field(..., title="Ticket Type ID")


class GetProduct(_Input):
    operation: Literal["get_product"] = "get_product"
    product_id: Guid = Field(..., title="Product Type ID")


class ListLocations(_Input):
    operation: Literal["list_locations"] = "list_locations"
    type: Literal["normal", "trashed", "justtrashed"] = "normal"


class GetLocation(_Input):
    operation: Literal["get_location"] = "get_location"
    location_id: Guid = Field(..., title="Location ID")


Operations = Annotated[Union[
    ListEvents, GetEvent, UpdateEvent, ListEventDates, GetEventScanningStats,
    ListEventTickets, ListEventShops, GetTicket, UpdateTicket, GetOrder,
    UpdateOrderReceiver, GetOrderDownloadLink, ResendOrderConfirmation,
    ListOrderEmails, GetShop, ListShopTickets, ListShopProducts,
    AttachShopTicket, DetachShopTicket, GetProduct, ListLocations, GetLocation,
], Field(discriminator="operation")]


class WeeztixNodeConfig(NodeConfig[Operations, WeeztixOAuthCredential]):
    pass


# One operation always makes exactly one dashboard API request.
ROUTES = {
    "list_events": ("GET", "/event/{type}"),
    "get_event": ("GET", "/event/{event_id}"),
    "update_event": ("PUT", "/event/{event_id}"),
    "list_event_dates": ("GET", "/event/{event_id}/dates"),
    "get_event_scanning_stats": ("GET", "/event/{event_id}/scanningstats"),
    "list_event_tickets": ("GET", "/event/{event_id}/ticket/{type}"),
    "list_event_shops": ("GET", "/event/{event_id}/shops"),
    "get_ticket": ("GET", "/ticket/{ticket_id}"),
    "update_ticket": ("PUT", "/ticket/{ticket_id}"),
    "get_order": ("GET", "/order/{order_id}"),
    "update_order_receiver": ("PUT", "/order/{order_id}"),
    "get_order_download_link": ("GET", "/order/{order_id}/downloadlink"),
    "resend_order_confirmation": ("GET", "/order/{order_id}/resend"),
    "list_order_emails": ("GET", "/order/{order_id}/emails"),
    "get_shop": ("GET", "/shop/{shop_id}"),
    "list_shop_tickets": ("GET", "/shop/{shop_id}/tickets"),
    "list_shop_products": ("GET", "/shop/{shop_id}/products"),
    "attach_shop_ticket": ("POST", "/shop/{shop_id}/tickets/{ticket_id}"),
    "detach_shop_ticket": ("DELETE", "/shop/{shop_id}/tickets/{ticket_id}"),
    "get_product": ("GET", "/product/{product_id}"),
    "list_locations": ("GET", "/location/{type}"),
    "get_location": ("GET", "/location/{location_id}"),
}
BODY_FIELDS = {
    "update_event": ("name", "description", "email_info", "status"),
    "update_ticket": ("name", "description", "min_orderable_amount_per_order", "max_orderable_amount_per_order"),
    "update_order_receiver": ("email", "firstName", "lastName", "locale"),
}
LISTS = {"list_events", "list_event_dates", "get_event_scanning_stats", "list_event_tickets", "list_event_shops", "list_order_emails", "list_shop_tickets", "list_shop_products", "list_locations"}
EMPTY = {"resend_order_confirmation", "attach_shop_ticket", "detach_shop_ticket"}


class WeeztixNode(WorkflowNode):
    integration_type = "automation-weeztix"
    workflow_credential_refresh = True
    scope_registry = WEEZTIX_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_events", noun="events")

    @classmethod
    def get_config_model(cls):
        return WeeztixNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.weeztix_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="weeztix")

    async def run(self, inputs):
        if self.config.credentials is not None:
            data = await self.freshen_credential(self.config.credentials.model_dump(),
                pool=self.node_data.get("_approval_pool"), user_id=self.user_id,
                credential_id=self.node_data.get("credential_id"))
            self.config.credentials = WeeztixOAuthCredential.model_validate(data)
        return await super().run(inputs)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Weeztix account")
        cfg = self.config.config
        method, template = ROUTES[cfg.operation]
        values = cfg.model_dump(exclude_none=True)
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        headers = {"Authorization": "Bearer " + self.config.credentials.access_token,
                   "Accept": "text/plain" if cfg.operation == "get_order_download_link" else "application/json"}
        if cfg.company_id is not None:
            headers["Company"] = cfg.company_id
        kwargs = {}
        if cfg.operation in BODY_FIELDS:
            kwargs["json"] = {k: values[k] for k in BODY_FIELDS[cfg.operation] if k in values}
        async with guarded_async_client(timeout=30.0, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        secrets = (self.config.credentials.access_token, self.config.credentials.refresh_token)
        def redact(value):
            if isinstance(value, str):
                for secret in secrets:
                    if secret:
                        value = value.replace(secret, "[redacted]")
            elif isinstance(value, list):
                value = [redact(v) for v in value]
            elif isinstance(value, dict):
                value = {k: redact(v) for k, v in value.items()}
            return value
        if not 200 <= response.status_code < 300:
            return {"status": "error", "success": False, "http_status": response.status_code,
                    "message": redact(response.text[:4000])}
        if cfg.operation in EMPTY:
            if response.status_code != 204:
                raise ValueError("Weeztix did not return the documented empty acknowledgement")
            result = {"acknowledged": True}
        elif cfg.operation == "get_order_download_link":
            result = {"download_link": response.text}
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Weeztix returned an invalid JSON response") from None
            if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
                return {"status": "error", "success": False, "http_status": response.status_code, "message": redact(str(data))}
            expected = list if cfg.operation in LISTS else dict
            if not isinstance(data, expected):
                raise ValueError("Weeztix returned an unexpected response shape")
            result = {"data": data}
        output = redact({"status": "success", "success": True, "http_status": response.status_code, **result})
        await self.emit(output)
        return output
