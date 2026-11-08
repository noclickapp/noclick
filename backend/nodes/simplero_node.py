"""Simplero v2 contact, marketing and sales operations.

Contract: https://simplero.com/api/v2/docs/openapi.json (v2).
Every operation issues one request; mutations are never automatically retried.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://simplero.com/api/v2"


class SimpleroAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Simplero API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://simplero.com/api/v2/docs",
            "x-credential-instructions": "In Simplero admin, open Settings > Integrations and copy your API key. Paste the key here. NoClick sends it in the X-API-Key header to simplero.com.",
        })
    credential_type: Literal["simplero_api_key"] = Field("simplero_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or an authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; ignored when after is supplied.")
    per_page: int = Field(20, ge=1, le=100, description="Records per page, from 1 to 100.")
    after: int | None = Field(None, ge=0, description="Cursor from pagination.next_after; overrides page.")


class _SearchPage(_Page):
    q: str | None = Field(None, max_length=1000, title="Search")


class _CustomerFields(_Input):
    first_names: str | None = Field(None, max_length=500, title="First Names")
    last_name: str | None = Field(None, max_length=500, title="Last Name")
    phone_number: str | None = Field(None, max_length=100)


class _Email(_Input):
    email: str = Field(..., max_length=254)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Use a valid contact email address")
        return value


class ListCustomers(_SearchPage):
    operation: Literal["list_customers"] = Field("list_customers", title="List Contacts", json_schema_extra={"ui:hidden": True})


class GetCustomer(_Input):
    operation: Literal["get_customer"] = Field("get_customer", title="Get Contact", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title="Contact ID")


class ListTags(_SearchPage):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})


class GetTag(_Input):
    operation: Literal["get_tag"] = Field("get_tag", title="Get Tag", json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(..., ge=1, title="Tag ID")


class ListLists(_SearchPage):
    operation: Literal["list_lists"] = Field("list_lists", title="List Lists", json_schema_extra={"ui:hidden": True})


class GetList(_Input):
    operation: Literal["get_list"] = Field("get_list", title="Get List", json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., ge=1, title="List ID")


class ListProducts(_SearchPage):
    operation: Literal["list_products"] = Field("list_products", title="List Products", json_schema_extra={"ui:hidden": True})


class GetProduct(_Input):
    operation: Literal["get_product"] = Field("get_product", title="Get Product", json_schema_extra={"ui:hidden": True})
    product_id: int = Field(..., ge=1, title="Product ID")


class ListPurchases(_SearchPage):
    customer_id: int | None = Field(None, ge=1, title="Contact ID")
    product_id: int | None = Field(None, ge=1)
    operation: Literal["list_purchases"] = Field("list_purchases", title="List Purchases", json_schema_extra={"ui:hidden": True})


class GetPurchase(_Input):
    operation: Literal["get_purchase"] = Field("get_purchase", title="Get Purchase", json_schema_extra={"ui:hidden": True})
    purchase_id: int = Field(..., ge=1, title="Purchase ID")


class ListAutomations(_SearchPage):
    operation: Literal["list_automations"] = Field("list_automations", title="List Automations", json_schema_extra={"ui:hidden": True})


class GetAutomation(_Input):
    operation: Literal["get_automation"] = Field("get_automation", title="Get Automation", json_schema_extra={"ui:hidden": True})
    automation_id: int = Field(..., ge=1, title="Automation ID")


class ListSubscriptions(_SearchPage):
    list_id: str | None = Field(None, max_length=100, title="List ID")
    operation: Literal["list_subscriptions"] = Field("list_subscriptions", title="List Subscriptions", json_schema_extra={"ui:hidden": True})


class GetSubscription(_Input):
    operation: Literal["get_subscription"] = Field("get_subscription", title="Get List Subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: int = Field(..., ge=1, title="List Subscription ID")


class CreateCustomer(_CustomerFields, _Email):
    operation: Literal["create_customer"] = Field("create_customer", title="Create Contact", json_schema_extra={"ui:hidden": True})
    lead_score: float = Field(..., allow_inf_nan=False, description="Initial lead score, required by the v2 contract.")


class UpdateCustomer(_CustomerFields):
    operation: Literal["update_customer"] = Field("update_customer", title="Update Contact", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title="Contact ID")
    email: str | None = Field(None, max_length=254)
    lead_score: float | None = Field(None, allow_inf_nan=False, description="Replaces the score when supplied.")

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        return _Email.email_address(value) if value is not None else value

    @model_validator(mode="after")
    def changed_fields(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "customer_id"}):
            raise ValueError("Supply at least one contact field to update")
        return self


class CreateList(_Input):
    operation: Literal["create_list"] = Field("create_list", title="Create List", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500, title="Public Name")
    internal_name: str = Field(..., min_length=1, max_length=500)


class UpdateTag(_Input):
    operation: Literal["update_tag"] = Field("update_tag", title="Update Tag", json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    color: str | None = Field(None, max_length=100)


class AddTag(_Input):
    operation: Literal["add_tag"] = Field("add_tag", title="Add Tag for Contact", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title="Contact ID")
    tag_id: int = Field(..., ge=1)


class RemoveTag(_Input):
    operation: Literal["remove_tag"] = Field("remove_tag", title="Remove Tag for Contact", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title="Contact ID")
    tag_id: int = Field(..., ge=1)


class StartAutomation(_Input):
    operation: Literal["start_automation"] = Field("start_automation", title="Start Automation for Contact", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title="Contact ID")
    automation_id: int = Field(..., ge=1)


class StopAutomation(_Input):
    operation: Literal["stop_automation"] = Field("stop_automation", title="Stop Automation for Contact", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title="Contact ID")
    automation_id: int = Field(..., ge=1)


class SubscribeContact(_Input):
    operation: Literal["subscribe_contact"] = Field("subscribe_contact", title="Subscribe Contact to List", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1, title="Contact ID")
    list_id: int = Field(..., ge=1, title="List ID")
    require_double_opt_in: bool = Field(True, description="Require the contact to confirm the subscription.")
    skip_welcome: bool = Field(False, description="Skip the list's welcome message.")
    skip_auto_responses: bool = Field(False, description="Skip the list's automatic responses.")


class Unsubscribe(_Input):
    operation: Literal["unsubscribe"] = Field("unsubscribe", title="Unsubscribe from List", json_schema_extra={"ui:hidden": True})
    subscription_id: int = Field(..., ge=1, title="List Subscription ID")


SimpleroConfig = Annotated[Union[ListCustomers, GetCustomer, ListTags, GetTag, ListLists, GetList, ListProducts, GetProduct, ListPurchases, GetPurchase, ListAutomations, GetAutomation, ListSubscriptions, GetSubscription, CreateCustomer, UpdateCustomer, CreateList, UpdateTag, AddTag, RemoveTag, StartAutomation, StopAutomation, SubscribeContact, Unsubscribe], Field(discriminator="operation")]


class SimpleroFullConfig(NodeConfig[SimpleroConfig, SimpleroAPIKeyCredential]):
    pass


ROUTES = {'list_customers': ('GET', '/customers'),
 'get_customer': ('GET', '/customers/{customer_id}'),
 'list_tags': ('GET', '/tags'),
 'get_tag': ('GET', '/tags/{tag_id}'),
 'list_lists': ('GET', '/lists'),
 'get_list': ('GET', '/lists/{list_id}'),
 'list_products': ('GET', '/products'),
 'get_product': ('GET', '/products/{product_id}'),
 'list_purchases': ('GET', '/purchases'),
 'get_purchase': ('GET', '/purchases/{purchase_id}'),
 'list_automations': ('GET', '/automations'),
 'get_automation': ('GET', '/automations/{automation_id}'),
 'list_subscriptions': ('GET', '/subscriptions'),
 'get_subscription': ('GET', '/subscriptions/{subscription_id}'),
 'create_customer': ('POST', '/customers'),
 'update_customer': ('PATCH', '/customers/{customer_id}'),
 'create_list': ('POST', '/lists'),
 'update_tag': ('PATCH', '/tags/{tag_id}'),
 'add_tag': ('POST', '/customers/{customer_id}/actions/add_tag'),
 'remove_tag': ('POST', '/customers/{customer_id}/actions/remove_tag'),
 'start_automation': ('POST', '/customers/{customer_id}/actions/start_automation'),
 'stop_automation': ('POST', '/customers/{customer_id}/actions/stop_automation'),
 'subscribe_contact': ('POST', '/customers/{customer_id}/actions/list_subscribe'),
 'unsubscribe': ('POST', '/subscriptions/{subscription_id}/actions/unsubscribe')}


class SimpleroNode(WorkflowNode):
    integration_type = "automation-simplero"
    connection_evidence = ConnectionEvidence(noun="lists", operation="list_lists")

    @classmethod
    def get_config_model(cls):
        return SimpleroFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Simplero API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, template = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path_fields = re.findall(r"\{([^}]+)\}", template)
        path = template.format(**{name: values.pop(name) for name in path_fields})
        if method == "GET" and values.get("after") is not None:
            values.pop("page", None)
        request = {"params": values} if method == "GET" else ({"json": values} if values else {})
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers={
                "X-API-Key": key, "Accept": "application/json",
                "User-Agent": "NoClick (support@noclick.com)",
            }, **request)
        # Preserve provider rejection text for the common connection verifier.
        if response.status_code != 200:
            message = response.text[:2000].replace(key, "[redacted]")
            raise ValueError(f"Simplero HTTP {response.status_code}: {message}")
        body = response.json()
        if not isinstance(body, dict) or "errors" in body or "error" in body:
            raise ValueError("Simplero returned an error or an invalid JSON envelope")
        data = body.get("data")
        if op.operation.startswith("list_"):
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Simplero did not return a record list")
        elif not isinstance(data, dict):
            raise ValueError("Simplero did not return a record or action result")
        if isinstance(data, dict) and data.get("success") is False:
            raise ValueError("Simplero action failed: " + str(data.get("message", "No details")).replace(key, "[redacted]"))
        result = {**body, "status": "success"}
        await self.emit(result)
        return result
