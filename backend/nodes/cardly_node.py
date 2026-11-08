"""Cardly API v2.2.0: fixed operations using a pasted organisation API key.

Contract: https://api.card.ly/openapi/en-AU/2.2.0/json
Lists return a single page and preserve Cardly pagination metadata. No request
is retried: order placement is billable and a timeout has an unknown outcome.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.card.ly/v2"


class CardlyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cardly API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.cardly.net/",
            "x-credential-instructions": "In your Cardly organisation portal, copy an API key. Paste a test key to validate requests without changing data, or a live key to make changes and place billable orders. NoClick sends it in the API-Key header to api.card.ly. Connecting reads your organisation's contact lists.",
        })
    credential_type: Literal["cardly_api_key"] = Field("cardly_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str) or not value.isascii():
            raise ValueError("Paste the API key as plain text")
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    limit: int = Field(25, ge=1, le=100, description="Maximum records in this page.")
    offset: int = Field(0, ge=0, description="Records to skip. Use next_offset from the previous page.")


class Resource(Input):
    id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Resource ID")


class ContactListResource(Input):
    list_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", title="Contact list ID")


class ContactResource(ContactListResource, Resource):
    pass


class CustomField(Input):
    name: str = Field(..., min_length=1)
    description: str | None = None
    type: Literal["text", "date", "number", "url"]


class ContactData(Input):
    firstName: str = Field(..., title="First name", min_length=1)
    address: str = Field(..., title="Street address", min_length=1)
    locality: str = Field(..., title="City or suburb", min_length=1)
    region: str = Field(..., title="State or province")
    country: str = Field(..., title="Country code", min_length=2, max_length=2)
    postcode: str = Field(..., title="Postal code")
    externalId: str | None = Field(None, title="External ID")
    lastName: str | None = Field(None, title="Last name")
    email: str | None = None
    company: str | None = None
    address2: str | None = Field(None, title="Address line 2")
    fields: dict[str, str | int | float | bool | None] | None = Field(None, title="Custom field values")


class Address(Input):
    firstName: str = Field(..., min_length=1, title="First name")
    address: str = Field(..., min_length=1, title="Street address")
    city: str = Field(..., min_length=1, title="City or suburb")
    region: str = Field(..., title="State or province")
    postcode: str = Field(..., title="Postal code")
    country: str = Field(..., min_length=2, max_length=2, title="Country code")
    lastName: str | None = Field(None, title="Last name")
    company: str | None = None
    address2: str | None = Field(None, title="Address line 2")


class Sender(Address):
    omitAddress: bool | None = Field(None, title="Omit return address")


class MessagePage(Input):
    page: int = Field(..., ge=1)
    text: str


class Messages(Input):
    pages: list[MessagePage] = Field(..., min_length=1)


class Card(Input):
    artwork: str = Field(..., min_length=1, description="Artwork UUID or slug from your organisation.")
    recipient: Address
    template: str | None = Field(None, description="Optional template UUID or slug.")
    variables: dict[str, str] | None = None
    messages: Messages | None = None
    sender: Sender | None = None
    shippingMethod: Literal["standard", "tracked", "express"] | None = Field(None, title="Shipping method")
    shipToMe: bool | None = Field(None, title="Include blank envelope", description="May incur extra credit cost.")
    requestedArrival: str | None = Field(None, title="Requested arrival date", pattern=r"^\d{4}-\d{2}-\d{2}$")


class OrderLine(Card):
    quantity: int = Field(1, ge=1)


class GetBalance(Input):
    operation: Literal["get_balance"] = Field("get_balance", title="Retrieve Account Balance", description="", json_schema_extra={"ui:hidden": True})


class ListCreditHistory(Page):
    operation: Literal["list_credit_history"] = Field("list_credit_history", title="List Credit History", description="", json_schema_extra={"ui:hidden": True})


class ListGiftCreditHistory(Page):
    operation: Literal["list_gift_credit_history"] = Field("list_gift_credit_history", title="List Gift Credit History", description="", json_schema_extra={"ui:hidden": True})


class ListArtwork(Page):
    operation: Literal["list_artwork"] = Field("list_artwork", title="List Artwork", description="", json_schema_extra={"ui:hidden": True})
    ownOnly: bool | None = Field(None, title="Only own artwork")


class GetArtwork(Resource):
    operation: Literal["get_artwork"] = Field("get_artwork", title="Retrieve Artwork", description="", json_schema_extra={"ui:hidden": True})


class ListContactLists(Page):
    operation: Literal["list_contact_lists"] = Field("list_contact_lists", title="List Contact Lists", description="", json_schema_extra={"ui:hidden": True})


class CreateContactList(Input):
    operation: Literal["create_contact_list"] = Field("create_contact_list", title="Create Contact List", description="", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    description: str | None = None
    fields: list[CustomField] | None = None


class GetContactList(Resource):
    operation: Literal["get_contact_list"] = Field("get_contact_list", title="Retrieve Contact List", description="", json_schema_extra={"ui:hidden": True})


class DeleteContactList(Resource):
    operation: Literal["delete_contact_list"] = Field("delete_contact_list", title="Delete Contact List", description="Deletion disables linked automations.", json_schema_extra={"ui:hidden": True})


class ListContacts(ContactListResource, Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", description="", json_schema_extra={"ui:hidden": True})


class CreateContact(ContactListResource, ContactData):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", description="", json_schema_extra={"ui:hidden": True})


class GetContact(ContactResource):
    operation: Literal["get_contact"] = Field("get_contact", title="Retrieve Contact", description="", json_schema_extra={"ui:hidden": True})


class UpdateContact(ContactResource, ContactData):
    operation: Literal["update_contact"] = Field("update_contact", title="Edit Contact", description="", json_schema_extra={"ui:hidden": True})


class DeleteContact(ContactResource):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", description="", json_schema_extra={"ui:hidden": True})


class SearchContacts(ContactListResource):
    operation: Literal["search_contacts"] = Field("search_contacts", title="Search Contacts", description="", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, description="Email address or external identifier.")


class SyncContact(ContactListResource, ContactData):
    operation: Literal["sync_contact"] = Field("sync_contact", title="Sync Contact", description="", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def identifier(self):
        if not self.externalId and not self.email:
            raise ValueError("Supply an external ID or email for contact sync")
        return self


class ListFonts(Page):
    operation: Literal["list_fonts"] = Field("list_fonts", title="List Fonts", description="", json_schema_extra={"ui:hidden": True})
    organisationOnly: bool | None = Field(None, title="Only organisation fonts")


class ListMedia(Page):
    operation: Literal["list_media"] = Field("list_media", title="List Media", description="", json_schema_extra={"ui:hidden": True})
    organisationOnly: bool | None = Field(None, title="Only organisation media")


class ListOrders(Page):
    operation: Literal["list_orders"] = Field("list_orders", title="List Orders", description="", json_schema_extra={"ui:hidden": True})


class GetOrder(Resource):
    operation: Literal["get_order"] = Field("get_order", title="Retrieve Order", description="", json_schema_extra={"ui:hidden": True})


class PreviewOrder(Card):
    operation: Literal["preview_order"] = Field("preview_order", title="Generate Order Preview", description="", json_schema_extra={"ui:hidden": True})
    purchaseOrderNumber: str | None = Field(None, title="Purchase order number")


class PlaceOrder(Input):
    operation: Literal["place_order"] = Field("place_order", title="Place Order", description="A live key places a billable order; test keys validate without mutations.", json_schema_extra={"ui:hidden": True})
    lines: list[OrderLine] = Field(..., min_length=1, max_length=100, description="A live key places and charges this order. A test key validates without placing it. Do not retry an uncertain result without checking Cardly.")
    purchaseOrderNumber: str | None = Field(None, title="Purchase order number")


class ListTemplates(Page):
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", description="", json_schema_extra={"ui:hidden": True})


class ListWritingStyles(Page):
    operation: Literal["list_writing_styles"] = Field("list_writing_styles", title="List Writing Styles", description="", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetBalance, ListCreditHistory, ListGiftCreditHistory, ListArtwork, GetArtwork, ListContactLists, CreateContactList, GetContactList, DeleteContactList, ListContacts, CreateContact, GetContact, UpdateContact, DeleteContact, SearchContacts, SyncContact, ListFonts, ListMedia, ListOrders, GetOrder, PreviewOrder, PlaceOrder, ListTemplates, ListWritingStyles], Field(discriminator="operation")]


class CardlyConfig(NodeConfig[Operation, CardlyAPIKeyCredential]):
    pass


ROUTES = {'get_balance': ('GET', '/account/balance'), 'list_credit_history': ('GET', '/account/credit-history'), 'list_gift_credit_history': ('GET', '/account/gift-credit-history'), 'list_artwork': ('GET', '/art'), 'get_artwork': ('GET', '/art/{id}'), 'list_contact_lists': ('GET', '/contact-lists'), 'create_contact_list': ('POST', '/contact-lists'), 'get_contact_list': ('GET', '/contact-lists/{id}'), 'delete_contact_list': ('DELETE', '/contact-lists/{id}'), 'list_contacts': ('GET', '/contact-lists/{list_id}/contacts'), 'create_contact': ('POST', '/contact-lists/{list_id}/contacts'), 'get_contact': ('GET', '/contact-lists/{list_id}/contacts/{id}'), 'update_contact': ('POST', '/contact-lists/{list_id}/contacts/{id}'), 'delete_contact': ('DELETE', '/contact-lists/{list_id}/contacts/{id}'), 'search_contacts': ('GET', '/contact-lists/{list_id}/contacts/find'), 'sync_contact': ('POST', '/contact-lists/{list_id}/contacts/sync'), 'list_fonts': ('GET', '/fonts'), 'list_media': ('GET', '/media'), 'list_orders': ('GET', '/orders'), 'get_order': ('GET', '/orders/{id}'), 'preview_order': ('POST', '/orders/preview'), 'place_order': ('POST', '/orders/place'), 'list_templates': ('GET', '/templates'), 'list_writing_styles': ('GET', '/writing-styles')}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class CardlyNode(WorkflowNode):
    integration_type = "automation-cardly"
    connection_evidence = ConnectionEvidence(noun="contact lists", operation="list_contact_lists")

    @classmethod
    def get_config_model(cls):
        return CardlyConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Cardly API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("id", "list_id"):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", quote(values.pop(field), safe=""))
        headers = {"API-Key": key, "Accept": "application/json"}
        kwargs = {"params": values} if method == "GET" else {"json": values} if method == "POST" else {}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, **kwargs)
            if len(response.content) > 10_000_000:
                raise ValueError("Cardly response exceeds the supported size")
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("state"), dict):
                raise ValueError("Cardly returned an unrecognised response")
            state = body["state"]
            messages = state.get("messages", [])
            if not isinstance(messages, list) or any(not isinstance(x, str) for x in messages):
                raise ValueError("Cardly returned unrecognised messages")
            if response.is_error or state.get("status") == "ERROR":
                output = {"status": "error", "success": False, "http_status": response.status_code,
                          "error": "; ".join(messages) or "Cardly rejected the request", "state": state}
            elif not 200 <= response.status_code < 300 or state.get("status") not in {"OK", "WARN"} or "data" not in body:
                raise ValueError("Cardly did not confirm the operation")
            else:
                data = body["data"]
                # Flatten one page for connection evidence while preserving the
                # provider's complete pagination metadata. Never claim all pages.
                pagination = {}
                if op.operation.startswith("list_"):
                    if not isinstance(data, dict) or not isinstance(data.get("results"), list) or not isinstance(data.get("meta"), dict):
                        raise ValueError("Cardly returned an unrecognised list page")
                    meta = data["meta"]
                    last, total, offset, limit = (meta.get(k) for k in ("lastRecord", "totalRecords", "offset", "limit"))
                    has_more = last < total if type(last) is int and type(total) is int else None
                    next_offset = offset + limit if has_more and type(offset) is int and type(limit) is int and limit > 0 else None
                    pagination = {"pagination": meta, "has_more": has_more, "next_offset": next_offset}
                    data = data["results"]
                output = {"status": "success", "success": True, "data": data, "state": state,
                          "test_mode": body.get("testMode", key.startswith("test_")),
                          "http_status": response.status_code, **pagination}
        except (httpx.HTTPError, ValueError):
            output = {"status": "error" if method == "GET" else "unknown", "success": False,
                      "error": "Cardly response could not be confirmed. Check Cardly before retrying a write.",
                      "write_outcome": "unknown" if method != "GET" else None}
        output = _redact(output, key)
        await self.emit(output)
        return output
