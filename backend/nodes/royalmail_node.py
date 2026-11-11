"""ChannelShipper & Royal Mail Public API, pinned OpenAPI v1.0.0.

Contract: https://api.parcel.royalmail.com/doc/v1/click-and-drop-api-v1.yaml
Bearer tokens are pasted from the account's API integration settings. No request
is automatically retried: order/return creation and manifesting can have effects.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.royalmail_operations import RMCreateOrderRequest, RMUpdateOrderStatusRequest, RMServiceCode, RMShipment
from utils.ssrf import guarded_async_client

BASE = "https://api.parcel.royalmail.com/api/v1"


class RoyalMailAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Royal Mail API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://api.parcel.royalmail.com/",
        "x-credential-instructions": "In ChannelShipper or Royal Mail Click & Drop, open Settings → Integrations → Royal Mail API and copy the API token. Paste only the token, without Bearer. Account features determine whether ChannelShipper details, OBA labels/returns or OLP services are available.",
    })
    credential_type: Literal["royalmail_api_token"] = Field("royalmail_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API Token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without Bearer or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListOrders(Input):
    operation: Literal["list_orders"] = Field("list_orders", title="List Orders", json_schema_extra={"ui:hidden": True})
    pageSize: int = Field(25, ge=1, le=100)
    startDateTime: datetime | None = None
    endDateTime: datetime | None = None
    continuationToken: str | None = None


class ListOrderDetails(ListOrders):
    """ChannelShipper accounts only."""
    operation: Literal["list_order_details"] = Field("list_order_details", title="List Order Details (ChannelShipper)", json_schema_extra={"ui:hidden": True})


class SelectedOrders(Input):
    orderIdentifiers: str = Field(..., min_length=1, description='Up to 100 IDs or quoted order references, separated by semicolons. Example: 1001;"my-reference". Do not percent-encode; NoClick encodes references.')

    @field_validator("orderIdentifiers")
    @classmethod
    def identifiers(cls, value):
        # Quoted references may themselves contain semicolons; scan rather than split.
        import re
        parts = re.findall(r'"[^"\r\n]+"|[0-9]+', value)
        if not parts or len(parts) > 100 or ';'.join(parts) != value:
            raise ValueError('Use numeric IDs or double-quoted references separated by semicolons')
        return value


class GetOrders(SelectedOrders):
    operation: Literal["get_orders"] = Field("get_orders", title="Get Specific Orders", json_schema_extra={"ui:hidden": True})


class GetOrderDetails(SelectedOrders):
    operation: Literal["get_order_details"] = Field("get_order_details", title="Get Specific Order Details (ChannelShipper)", json_schema_extra={"ui:hidden": True})


class DeleteOrders(SelectedOrders):
    operation: Literal["delete_orders"] = Field("delete_orders", title="Delete Orders", description="Permanently delete the selected orders.", json_schema_extra={"ui:hidden": True})


class CreateOrders(Input):
    operation: Literal["create_orders"] = Field("create_orders", title="Create Orders", json_schema_extra={"ui:hidden": True})
    items: list[RMCreateOrderRequest] = Field(..., min_length=1, max_length=100, description="Orders with recipient, orderDate, subtotal, shippingCostCharged and total. Providing addressBookReference or product SKU plus details can update the account's address book or product catalogue.")


class UpdateOrderStatus(Input):
    operation: Literal["update_order_status"] = Field("update_order_status", title="Set Order Status", json_schema_extra={"ui:hidden": True})
    items: list[RMUpdateOrderStatusRequest] = Field(..., min_length=1, max_length=100, description="Exactly one orderIdentifier or orderReference per item. Resetting to new cancels existing labels: destroy them and generate replacements before shipping.")

    @model_validator(mode="after")
    def valid_items(self):
        for item in self.items:
            if (item.orderIdentifier is None) == (item.orderReference is None) or item.status is None:
                raise ValueError("Each update needs a status and exactly one orderIdentifier or orderReference")
            if item.status == "despatchedByOtherCourier" and item.trackingNumber and not all((item.despatchDate, item.shippingCarrier, item.shippingService)):
                raise ValueError("Tracking another courier requires despatchDate, shippingCarrier and shippingService")
        return self


class ListCarriers(Input):
    operation: Literal["list_carriers"] = Field("list_carriers", title="List Account Carriers", json_schema_extra={"ui:hidden": True})


class ListServices(Input):
    operation: Literal["list_services"] = Field("list_services", title="List Shipping Services", json_schema_extra={"ui:hidden": True})
    destinationCountryCode: str | None = None
    destinationPostcode: str | None = None
    packagingFormat: Literal["Letter", "LargeLetter", "SmallParcel", "MediumParcel", "Parcel", "Documents"] | None = None
    packageWeight: int | None = None
    carrierGuid: str | None = Field(None, json_schema_extra={"format": "uuid"})
    shippingAccountName: str | None = Field(None, max_length=50)

    @model_validator(mode="after")
    def destination(self):
        if any(v is not None for v in (self.destinationPostcode, self.packagingFormat, self.packageWeight)) and not self.destinationCountryCode:
            raise ValueError("Destination filters require destinationCountryCode")
        if self.destinationCountryCode == "GBR" and not (self.destinationPostcode or "").strip():
            raise ValueError("GBR requires destinationPostcode")
        return self


class GetLabels(SelectedOrders):
    operation: Literal["get_labels"] = Field("get_labels", title="Get Labels or Documents (OBA)", json_schema_extra={"ui:hidden": True})
    documentType: Literal["postageLabel", "despatchNote", "CN22", "CN23", "commercialInvoice"] = "postageLabel"
    includeReturnsLabel: bool = False
    includeCN: bool | None = None
    includeCommercialInvoice: bool | None = None


class ManifestOrders(Input):
    operation: Literal["manifest_orders"] = Field("manifest_orders", title="Manifest Eligible Orders", json_schema_extra={"ui:hidden": True})
    shippingAccountName: str | None = Field(None, max_length=50, description="Required when the account has multiple shipping accounts. Manifests all eligible orders in Label Generated and Despatched statuses.")


class GetManifest(Input):
    operation: Literal["get_manifest"] = Field("get_manifest", title="Get Manifest", json_schema_extra={"ui:hidden": True})
    manifestIdentifier: int = Field(..., description="Manifest number returned by Manifest Eligible Orders.")


class RetryManifest(GetManifest):
    operation: Literal["retry_manifest"] = Field("retry_manifest", title="Retry Manifest", json_schema_extra={"ui:hidden": True})


class ListReturnServices(Input):
    operation: Literal["list_return_services"] = Field("list_return_services", title="List Return Services (OBA)", json_schema_extra={"ui:hidden": True})


class CreateReturn(Input):
    operation: Literal["create_return"] = Field("create_return", title="Create Return Shipment (OBA)", json_schema_extra={"ui:hidden": True})
    service: RMServiceCode
    shipment: RMShipment


class ListOLPServices(Input):
    operation: Literal["list_olp_services"] = Field("list_olp_services", title="List Royal Mail OLP Services", json_schema_extra={"ui:hidden": True})
    country: str = Field(..., min_length=3, max_length=3, description="ISO 3166-1 alpha-3 destination, for example GBR.")
    weight: int | None = None
    postcode: str | None = None
    packageFormat: Literal["Letter", "LargeLetter", "SmallParcel", "MediumParcel", "LargeParcel"] | None = None


class OnNewOrder(PollTriggerConfigBase):
    operation: Literal["on_new_order"] = Field("on_new_order", title="On New Order", json_schema_extra={"x-is-trigger": True, "x-category": "Triggers", "ui:hidden": True})
    startDateTime: datetime | None = Field(None, description="Optional lower bound for order filtering. The first complete poll establishes a baseline without emitting historical orders.")


RoyalMailOperation = Annotated[Union[ListOrders, ListOrderDetails, GetOrders, GetOrderDetails, DeleteOrders, CreateOrders, UpdateOrderStatus, ListCarriers, ListServices, GetLabels, ManifestOrders, GetManifest, RetryManifest, ListReturnServices, CreateReturn, ListOLPServices, OnNewOrder], Field(discriminator="operation")]


class RoyalMailConfig(NodeConfig[RoyalMailOperation, RoyalMailAPITokenCredential]):
    pass


ROUTES = {
    "list_orders": ("GET", "/orders"), "list_order_details": ("GET", "/orders/full"),
    "get_orders": ("GET", "/orders/{orderIdentifiers}"), "get_order_details": ("GET", "/orders/{orderIdentifiers}/full"),
    "delete_orders": ("DELETE", "/orders/{orderIdentifiers}"), "create_orders": ("POST", "/orders"),
    "update_order_status": ("PUT", "/orders/status"), "list_carriers": ("GET", "/carriers"),
    "list_services": ("GET", "/services"), "get_labels": ("GET", "/orders/{orderIdentifiers}/label"),
    "manifest_orders": ("POST", "/manifests"), "get_manifest": ("GET", "/manifests/{manifestIdentifier}"),
    "retry_manifest": ("POST", "/manifests/retry/{manifestIdentifier}"), "list_return_services": ("GET", "/returns/services"),
    "create_return": ("POST", "/returns"), "list_olp_services": ("GET", "/services/olp"),
}


class RoyalMailNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-royalmail"
    connection_evidence = ConnectionEvidence(operation="list_carriers", noun="account carriers", label_keys=("shippingAccountName", "carrierGuid"))

    @classmethod
    def get_config_model(cls):
        return RoyalMailConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Royal Mail API token")
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json, application/pdf"}
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection so manual connection can show its reason.
            detail = response.text[:2000].replace(credential.api_token, "[redacted]")
            raise ValueError(f"Royal Mail API {response.status_code}: {detail}")
        if "application/pdf" in response.headers.get("content-type", ""):
            return {"content_type": "application/pdf", "pdf_base64": base64.b64encode(response.content).decode("ascii")}
        if not response.content:
            return {"http_status": response.status_code}
        data = response.json()
        if isinstance(data, dict) and data.get("errors") and not any(k in data for k in ("createdOrders", "failedOrders")):
            raise ValueError("Royal Mail reported errors: " + str(data["errors"])[:2000])
        return data

    async def _poll_orders(self, config):
        params = {"pageSize": 100}
        if config.startDateTime is not None:
            params["startDateTime"] = config.startDateTime.isoformat()
        orders, seen_tokens = [], set()
        for _ in range(100):
            data = await self._request("GET", "/orders", params=params)
            if not isinstance(data, dict) or not isinstance(data.get("orders"), list):
                raise ValueError("Royal Mail did not return an order list")
            orders.extend(data["orders"])
            cursor = data.get("continuationToken")
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in seen_tokens:
                raise ValueError("Royal Mail repeated an order continuation token")
            seen_tokens.add(cursor)
            params["continuationToken"] = cursor
            # The provider publishes a maximum of five calls per second.
            await asyncio.sleep(0.21)
        else:
            raise ValueError("More than 100 pages of orders; choose a later startDateTime")
        if any(not isinstance(row, dict) or row.get("orderIdentifier") is None for row in orders):
            raise ValueError("Royal Mail order identifier missing")
        fresh = await self._filter_unseen(orders, lambda row: str(row["orderIdentifier"]))
        return {"orders": fresh, "new_order_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_order_count")) if config.get("operation") == "on_new_order" else True

    @classmethod
    def resolve_agent_event(cls, output):
        orders = output.get("orders")
        if not isinstance(orders, list):
            return super().resolve_agent_event(output)
        if not orders:
            return None
        lines = [f"- Order {row.get('orderReference') or row['orderIdentifier']} (ID {row['orderIdentifier']}), created {row.get('createdOn', 'unknown')}" for row in orders[:20]]
        return {"text": "New Royal Mail / ChannelShipper orders:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, OnNewOrder):
            return await self._poll_orders(config)
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in ("orderIdentifiers", "manifestIdentifier"):
            if "{" + key + "}" in path:
                value = str(values.pop(key))
                if key == "orderIdentifiers":
                    import re
                    parts = re.findall(r'"[^"\r\n]+"|[0-9]+', value)
                    value = ';'.join('"' + quote(part[1:-1], safe='') + '"' if part.startswith('"') else part for part in parts)
                else:
                    value = quote(value, safe="")
                path = path.replace("{" + key + "}", value)
        result = await self._request(method, path, params=values if method == "GET" else None,
                                     body=values if config.operation in {"create_orders", "update_order_status", "manifest_orders", "create_return"} else None)
        return result if isinstance(result, dict) else {"items": result}
