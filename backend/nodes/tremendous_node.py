"""Tremendous v2 rewards and account operations.

Wire routes and response fixtures follow the pinned Tremendous Postman collection.
Lists return one provider page; callers advance offset explicitly. Writes are never retried.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class TremendousAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tremendous API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developers.tremendous.com/reference/authentication",
        "x-credential-instructions": "Paste your Tremendous API key without the Bearer prefix. Choose the environment that issued the key. Sandbox rewards use test funds; production orders spend real funds and can email or text recipients."})
    credential_type: Literal["tremendous_api_key"] = Field("tremendous_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    environment: Literal["sandbox", "production"] = Field("sandbox", title="Environment")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste an API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class _Offset(_Input):
    offset: int = Field(0, ge=0, le=10000000, description="Return one page starting at this offset. Advance by the number of rows returned.")


class _Limited(_Offset):
    limit: int = Field(10, ge=1, le=10)


class RewardValue(_Input):
    denomination: float = Field(..., gt=0, allow_inf_nan=False)
    currency_code: str = Field("USD", pattern=r"^[A-Z]{3}$")


class Recipient(_Input):
    name: str | None = Field(None, max_length=256)
    email: str | None = Field(None, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    phone: str | None = Field(None, max_length=40)


class Delivery(_Input):
    method: Literal["EMAIL", "PHONE", "LINK"] = "EMAIL"


class CustomField(_Input):
    id: Identifier
    value: str = Field(..., max_length=10000)


class Reward(_Input):
    value: RewardValue
    recipient: Recipient
    delivery: Delivery
    products: list[Identifier] | None = Field(None, min_length=1, max_length=100)
    campaign_id: Identifier | None = None
    custom_fields: list[CustomField] | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def required_details(self):
        if not self.products and not self.campaign_id:
            raise ValueError("Choose products or a campaign")
        if self.delivery.method == "EMAIL" and not self.recipient.email:
            raise ValueError("Email delivery requires a recipient email")
        if self.delivery.method == "PHONE" and not self.recipient.phone:
            raise ValueError("Phone delivery requires a recipient phone")
        return self


class Payment(_Input):
    funding_source_id: Identifier


class ListRewardsConfig(_Offset):
    operation: Literal["list_rewards"] = Field("list_rewards", json_schema_extra={"ui:hidden": True})


class GetRewardConfig(_Input):
    operation: Literal["get_reward"] = Field("get_reward", json_schema_extra={"ui:hidden": True})
    reward_id: Identifier


class ResendRewardConfig(_Input):
    operation: Literal["resend_reward"] = Field("resend_reward", json_schema_extra={"ui:hidden": True})
    reward_id: Identifier


class GenerateRewardLinkConfig(_Input):
    operation: Literal["generate_reward_link"] = Field("generate_reward_link", json_schema_extra={"ui:hidden": True})
    reward_id: Identifier


class ListOrdersConfig(_Input):
    """Return the first order page; this collection publishes no enabled order-list filters."""
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"ui:hidden": True})


class GetOrderConfig(_Input):
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"ui:hidden": True})
    order_id: Identifier


class CreateOrderConfig(_Input):
    operation: Literal["create_order"] = Field("create_order", json_schema_extra={"ui:hidden": True})
    external_id: str = Field(..., min_length=1, max_length=256, description="Stable unique reference for idempotence. Reuse this value when resolving an uncertain result; never create a new reference to retry.")
    payment: Payment
    reward: Reward


class ApproveOrderConfig(_Input):
    operation: Literal["approve_order"] = Field("approve_order", json_schema_extra={"ui:hidden": True})
    order_id: Identifier


class RejectOrderConfig(_Input):
    operation: Literal["reject_order"] = Field("reject_order", json_schema_extra={"ui:hidden": True})
    order_id: Identifier


class ListProductsConfig(_Input):
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})
    country: str | None = Field(None, description="Comma-separated alpha-2 country codes")
    currency: str | None = Field(None, description="Comma-separated currency codes")


class GetProductConfig(_Input):
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})
    product_id: Identifier


class ListCampaignsConfig(_Input):
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})


class GetCampaignConfig(_Input):
    operation: Literal["get_campaign"] = Field("get_campaign", json_schema_extra={"ui:hidden": True})
    campaign_id: Identifier


class ListFundingSourcesConfig(_Input):
    operation: Literal["list_funding_sources"] = Field("list_funding_sources", json_schema_extra={"ui:hidden": True})


class GetFundingSourceConfig(_Input):
    operation: Literal["get_funding_source"] = Field("get_funding_source", json_schema_extra={"ui:hidden": True})
    funding_source_id: Identifier


class ListInvoicesConfig(_Limited):
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})


class GetInvoiceConfig(_Input):
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: Identifier


class CreateInvoiceConfig(_Input):
    operation: Literal["create_invoice"] = Field("create_invoice", json_schema_extra={"ui:hidden": True})
    amount: float = Field(..., gt=0, allow_inf_nan=False)
    po_number: str | None = Field(None, max_length=256)
    orders: list[Identifier] | None = Field(None, max_length=100)


class DeleteInvoiceConfig(_Input):
    operation: Literal["delete_invoice"] = Field("delete_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: Identifier


class ListOrganizationsConfig(_Input):
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})


class GetOrganizationConfig(_Input):
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})
    organization_id: Identifier


class ListFieldsConfig(_Input):
    operation: Literal["list_fields"] = Field("list_fields", json_schema_extra={"ui:hidden": True})


TremendousConfig = Annotated[Union[
    ListRewardsConfig,
    GetRewardConfig,
    ResendRewardConfig,
    GenerateRewardLinkConfig,
    ListOrdersConfig,
    GetOrderConfig,
    CreateOrderConfig,
    ApproveOrderConfig,
    RejectOrderConfig,
    ListProductsConfig,
    GetProductConfig,
    ListCampaignsConfig,
    GetCampaignConfig,
    ListFundingSourcesConfig,
    GetFundingSourceConfig,
    ListInvoicesConfig,
    GetInvoiceConfig,
    CreateInvoiceConfig,
    DeleteInvoiceConfig,
    ListOrganizationsConfig,
    GetOrganizationConfig,
    ListFieldsConfig
], Field(discriminator="operation")]


class TremendousNodeConfig(NodeConfig[TremendousConfig, TremendousAPIKeyCredential]):
    pass


ROUTES = {'list_rewards': ('GET', '/rewards', 'rewards'),
 'get_reward': ('GET', '/rewards/{reward_id}', 'reward'),
 'resend_reward': ('POST', '/rewards/{reward_id}/resend', None),
 'generate_reward_link': ('POST', '/rewards/{reward_id}/generate_link', 'reward'),
 'list_orders': ('GET', '/orders', 'orders'),
 'get_order': ('GET', '/orders/{order_id}', 'order'),
 'create_order': ('POST', '/orders', 'order'),
 'approve_order': ('POST', '/order_approvals/{order_id}/approve', 'order'),
 'reject_order': ('POST', '/order_approvals/{order_id}/reject', 'order'),
 'list_products': ('GET', '/products', 'products'),
 'get_product': ('GET', '/products/{product_id}', 'product'),
 'list_campaigns': ('GET', '/campaigns', 'campaigns'),
 'get_campaign': ('GET', '/campaigns/{campaign_id}', 'campaign'),
 'list_funding_sources': ('GET', '/funding_sources', 'funding_sources'),
 'get_funding_source': ('GET', '/funding_sources/{funding_source_id}', 'funding_source'),
 'list_invoices': ('GET', '/invoices', 'invoices'),
 'get_invoice': ('GET', '/invoices/{invoice_id}', 'invoices'),
 'create_invoice': ('POST', '/invoices', 'invoices'),
 'delete_invoice': ('DELETE', '/invoices/{invoice_id}', 'invoices'),
 'list_organizations': ('GET', '/organizations', 'organizations'),
 'get_organization': ('GET', '/organizations/{organization_id}', 'organization'),
 'list_fields': ('GET', '/fields', 'fields')}


class TremendousNode(WorkflowNode):
    integration_type = "automation-tremendous"
    connection_evidence = ConnectionEvidence(noun="organizations", operation="list_organizations", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return TremendousNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Tremendous API key")
        auth = self.config.credentials
        config = self.config.config
        method, route, envelope = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in tuple(values):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", values.pop(field))
        base = "https://testflight.tremendous.com/api/v2" if auth.environment == "sandbox" else "https://api.tremendous.com/api/v2"
        params, body = None, None
        if method == "GET":
            params = {k.replace("created_at_gte", "created_at[gte]").replace("created_at_lte", "created_at[lte]"): v for k, v in values.items()}
        elif values:
            body = values
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(method, base + route,
                    headers={"Authorization": "Bearer " + auth.api_key, "Accept": "application/json"},
                    params=params, json=body)
        except httpx.TransportError:
            raise ValueError("Tremendous request did not complete; a write may have been applied. Check the existing order before trying again.") from None
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for the connect seam, redacting the key.
            message = response.text[:2000].replace(auth.api_key, "[redacted]")
            result = {"status": "error", "http_status": response.status_code, "error": message}
        else:
            try:
                payload = response.json()
            except (ValueError, UnicodeError):
                raise ValueError("Tremendous returned an unexpected non-JSON response") from None
            if not isinstance(payload, dict) or "errors" in payload or "error" in payload:
                raise ValueError("Tremendous returned an unexpected response envelope")
            if envelope and envelope not in payload:
                raise ValueError("Tremendous response is missing its documented resource")
            # Preserve all provider fields (including asynchronous delivery status).
            payload = json.loads(json.dumps(payload).replace(auth.api_key, "[redacted]"))
            result = {**payload, "status": "success", "http_status": response.status_code}
        await self.emit(result)
        return result
