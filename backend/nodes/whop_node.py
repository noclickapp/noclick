"""Whop Current API operations, pinned to the published v1 contract.

Account API keys are sent only to the production API. Lists return a single
cursor page; pass page_info.end_cursor as after to continue. Writes run once,
without automatic retries (a lost response may have applied the write).
Contract: https://api.whop.com/api/v1/openapi.json
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://api.whop.com/api/v1"

class WhopAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Whop API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://whop.com/dashboard/developer",
        "x-credential-instructions": "Paste a production Account API key from Whop Developer settings, without Bearer. Grant company:balance:read for the account connection check, plus the permissions needed by your operations. Sandbox keys cannot be used here. Whop enforces the key's permissions on each request."})
    credential_type: Literal["whop_api_key"] = Field("whop_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    @field_validator("api_key")
    @classmethod
    def token(cls, v):
        v = v.strip()
        if not v or any(c.isspace() or ord(c)<33 or ord(c)>126 for c in v):
            raise ValueError("Paste the API key without the Bearer prefix")
        return v

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    @field_validator("*", mode="after")
    @classmethod
    def identifier(cls, v, info):
        if info.field_name in {"id", "account_id"} and v is not None:
            if not v or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in v):
                raise ValueError("Use a Whop resource ID")
        return v


class WhopGetAccountConfig(_Input):
    """Retrieve Requesting Account. Permissions: [{'bearerAuth': ['company:balance:read']}]"""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class WhopListProductsConfig(_Input):
    """List Products. Permissions: [{}, {'bearerAuth': ['access_pass:basic:read']}]"""
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})
    account_id: str | None = Field(None ,max_length=1500, description='Account to list products for, prefixed `biz_`. Without the `access_pass:basic:read` permission on it, only the products its store page lists are returned. Omit to search the public marketplace.')
    first: int | None = Field(None ,ge=1, le=100, description='Number of results to return from the start of the range.')
    after: str | None = Field(None ,max_length=8192, description='Return results after this cursor. Use `page_info.end_cursor` from the previous response to fetch the next page.')


class WhopGetProductConfig(_Input):
    """Retrieve Product. Permissions: []"""
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


class WhopListMembershipsConfig(_Input):
    """List Memberships. Permissions: [{'bearerAuth': ['member:basic:read']}]"""
    operation: Literal["list_memberships"] = Field("list_memberships", json_schema_extra={"ui:hidden": True})
    account_id: str | None = Field(None ,max_length=1500, description="Narrow to one account (`biz_` tag). With read access to the account this lists all of its memberships; without, only the caller's own memberships in it.")
    first: int | None = Field(None ,ge=1, le=100, description='Number of results to return from the start of the range.')
    after: str | None = Field(None ,max_length=8192, description='Return results after this cursor. Use `page_info.end_cursor` from the previous response to fetch the next page.')


class WhopGetMembershipConfig(_Input):
    """Retrieve Membership. Permissions: [{'bearerAuth': ['member:basic:read']}]"""
    operation: Literal["get_membership"] = Field("get_membership", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


class WhopListPaymentsConfig(_Input):
    """List Payments. Permissions: [{'bearerAuth': ['payment:basic:read']}]"""
    operation: Literal["list_payments"] = Field("list_payments", json_schema_extra={"ui:hidden": True})
    account_id: str | None = Field(None ,max_length=1500, description='Only payments charged by this account, prefixed `biz_`.')
    first: int | None = Field(None ,ge=1, le=100, description='Number of results to return from the start of the range.')
    after: str | None = Field(None ,max_length=8192, description='Return results after this cursor. Use `page_info.end_cursor` from the previous response to fetch the next page.')


class WhopGetPaymentConfig(_Input):
    """Retrieve Payment. Permissions: [{'bearerAuth': ['payment:basic:read']}]"""
    operation: Literal["get_payment"] = Field("get_payment", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


class WhopListRefundsConfig(_Input):
    """List Refunds. Permissions: [{'bearerAuth': ['payment:basic:read']}]"""
    operation: Literal["list_refunds"] = Field("list_refunds", json_schema_extra={"ui:hidden": True})
    account_id: str | None = Field(None ,max_length=1500, description='Only refunds issued by this account, prefixed `biz_`.')
    first: int | None = Field(None ,ge=1, le=100, description='Number of results to return from the start of the range.')
    after: str | None = Field(None ,max_length=8192, description='Return results after this cursor. Use `page_info.end_cursor` from the previous response to fetch the next page.')


class WhopGetRefundConfig(_Input):
    """Retrieve Refund. Permissions: [{'bearerAuth': ['payment:basic:read']}]"""
    operation: Literal["get_refund"] = Field("get_refund", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


class WhopListPromoCodesConfig(_Input):
    """List Promo Codes. Permissions: [{'bearerAuth': ['promo_code:basic:read']}]"""
    operation: Literal["list_promo_codes"] = Field("list_promo_codes", json_schema_extra={"ui:hidden": True})
    account_id: str = Field(... ,max_length=1500, description='Account whose promo codes are listed (`biz_` tag).')
    first: int | None = Field(None ,ge=1, le=100, description='Number of results to return from the start of the range.')
    after: str | None = Field(None ,max_length=8192, description='Return results after this cursor. Use `page_info.end_cursor` from the previous response to fetch the next page.')


class WhopGetPromoCodeConfig(_Input):
    """Retrieve Promo Code. Permissions: [{'bearerAuth': ['promo_code:basic:read']}]"""
    operation: Literal["get_promo_code"] = Field("get_promo_code", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


class WhopCreateProductConfig(_Input):
    """Create Product. Permissions: [{'bearerAuth': ['access_pass:create']}]"""
    operation: Literal["create_product"] = Field("create_product", json_schema_extra={"ui:hidden": True})
    account_id: str | None = Field(None ,max_length=1500, description='The unique identifier of the account to create this product for.')
    title: str = Field(... ,max_length=80, description='The display name of the product. Maximum 80 characters.')
    description: str | None = Field(None ,max_length=1500, description='A written description displayed on the product page. Maximum 1,500 characters.')
    headline: str | None = Field(None ,max_length=80, description='A short marketing headline for the product page. Maximum 80 characters.')
    visibility: str | None = Field(None ,max_length=1500, description='Whether the product is visible to customers.')
    send_welcome_message: bool | None = Field(None ,description='Whether to send an automated welcome message via support chat when a user joins this product. Defaults to true.')


class WhopUpdateProductConfig(_Input):
    """Update Product. Permissions: [{'bearerAuth': ['access_pass:update']}]"""
    operation: Literal["update_product"] = Field("update_product", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")
    title: str | None = Field(None ,max_length=80, description='The display name of the product. Maximum 80 characters.')
    description: str | None = Field(None ,max_length=1500, description='A written description displayed on the product page. Maximum 1,500 characters.')
    headline: str | None = Field(None ,max_length=80, description='A short marketing headline for the product page. Maximum 80 characters.')
    visibility: str | None = Field(None ,max_length=1500, description='Whether the product is visible to customers.')
    send_welcome_message: bool | None = Field(None ,description='Whether to send an automated welcome message via support chat when a user joins this product.')
    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class WhopDeleteProductConfig(_Input):
    """Delete Product. Permissions: [{'bearerAuth': ['access_pass:delete']}]"""
    operation: Literal["delete_product"] = Field("delete_product", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


class WhopPublishProductConfig(_Input):
    """Publish Product. Permissions: [{'bearerAuth': ['access_pass:update']}]"""
    operation: Literal["publish_product"] = Field("publish_product", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


class WhopUnpublishProductConfig(_Input):
    """Unpublish Product. Permissions: [{'bearerAuth': ['access_pass:update']}]"""
    operation: Literal["unpublish_product"] = Field("unpublish_product", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


class WhopUpdateMembershipConfig(_Input):
    """Update Membership. Permissions: [{'bearerAuth': ['member:manage']}, {'bearerAuth': ['membership:cancel']}, {'bearerAuth': ['member:payment_methods:manage']}]"""
    operation: Literal["update_membership"] = Field("update_membership", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")
    cancel_at_period_end: bool | None = Field(None ,description='`true` cancels at the end of the current billing period (the customer keeps access until then); `false` reverses a pending cancellation.')
    metadata: dict[str, str] | None = Field(None ,description="Key-value pairs to merge into the membership's metadata. Pass an empty object to clear it.")
    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class WhopCancelMembershipConfig(_Input):
    """Cancel Membership. Permissions: [{'bearerAuth': ['membership:cancel']}, {'bearerAuth': ['member:manage']}]"""
    operation: Literal["cancel_membership"] = Field("cancel_membership", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")
    cancel_at_period_end: bool | None = Field(None ,description='`true` stops auto-renewal and keeps access until the current billing period ends. Omit or `false` revokes access immediately.')
    reason: str | None = Field(None ,max_length=1500, description='Free-form note recording why the membership was canceled.')


class WhopRefundPaymentConfig(_Input):
    """Refund Payment. Permissions: [{'bearerAuth': ['payment:manage']}]"""
    operation: Literal["refund_payment"] = Field("refund_payment", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")
    partial_amount: float | None = Field(None ,ge=0, description="The amount to refund, stated in this payment's `currency` like every other amount on it. When the buyer was billed in a different currency, it is converted at the payment's own exchange rate before the refund is issued. An amount that covers everything still refundable refunds the rest of the payment — omit it to refund the rest without having to work out what that is.")
    metadata: dict[str, str] | None = Field(None ,description='Your own key-value data to attach to the refund, returned on it and on its `refund.created` and `refund.updated` webhooks. At most 50 keys; keys up to 100 characters and values up to 500.')


class WhopCreatePromoCodeConfig(_Input):
    """Create Promo Code. Permissions: [{'bearerAuth': ['promo_code:create']}]"""
    operation: Literal["create_promo_code"] = Field("create_promo_code", json_schema_extra={"ui:hidden": True})
    account_id: str = Field(... ,max_length=1500)
    amount_off: float = Field(... ,ge=0)
    base_currency: Literal['usd', 'sgd', 'inr', 'aud', 'brl', 'cad', 'dkk', 'eur', 'nok', 'gbp', 'sek', 'chf', 'hkd', 'huf', 'jpy', 'mxn', 'myr', 'pln', 'czk', 'nzd', 'aed', 'eth', 'ape', 'cop', 'ron', 'thb', 'bgn', 'idr', 'dop', 'php', 'try', 'krw', 'twd', 'vnd', 'pkr', 'clp', 'uyu', 'ars', 'zar', 'dzd', 'tnd', 'mad', 'kes', 'kwd', 'jod', 'all', 'xcd', 'amd', 'bsd', 'bhd', 'bob', 'bam', 'khr', 'crc', 'xof', 'egp', 'etb', 'gmd', 'ghs', 'gtq', 'gyd', 'ils', 'jmd', 'mop', 'mga', 'mur', 'mdl', 'mnt', 'nad', 'ngn', 'mkd', 'omr', 'pyg', 'pen', 'qar', 'rwf', 'sar', 'rsd', 'lkr', 'tzs', 'ttd', 'uzs', 'rub', 'btc', 'cny', 'usdt', 'kzt', 'awg', 'whop_usd', 'xau'] = Field(...)
    code: str = Field(... ,max_length=1500)
    new_users_only: bool = Field(...)
    promo_duration_months: int = Field(... ,ge=0)
    promo_type: Literal['percentage', 'flat_amount'] = Field(...)
    stock: int | None = Field(None ,ge=0)
    unlimited_stock: bool | None = Field(None)
    one_per_customer: bool | None = Field(None)


class WhopActivatePromoCodeConfig(_Input):
    """Activate Promo Code. Permissions: [{'bearerAuth': ['promo_code:update']}]"""
    operation: Literal["activate_promo_code"] = Field("activate_promo_code", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


class WhopDeactivatePromoCodeConfig(_Input):
    """Deactivate Promo Code. Permissions: [{'bearerAuth': ['promo_code:update']}]"""
    operation: Literal["deactivate_promo_code"] = Field("deactivate_promo_code", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200, title="Resource ID")


WhopConfig = Annotated[Union[WhopGetAccountConfig, WhopListProductsConfig, WhopGetProductConfig, WhopListMembershipsConfig, WhopGetMembershipConfig, WhopListPaymentsConfig, WhopGetPaymentConfig, WhopListRefundsConfig, WhopGetRefundConfig, WhopListPromoCodesConfig, WhopGetPromoCodeConfig, WhopCreateProductConfig, WhopUpdateProductConfig, WhopDeleteProductConfig, WhopPublishProductConfig, WhopUnpublishProductConfig, WhopUpdateMembershipConfig, WhopCancelMembershipConfig, WhopRefundPaymentConfig, WhopCreatePromoCodeConfig, WhopActivatePromoCodeConfig, WhopDeactivatePromoCodeConfig], Field(discriminator="operation")]

class WhopFullConfig(NodeConfig[WhopConfig, WhopAPIKeyCredential]):
    pass


ROUTES = {'get_account': ('GET', '/accounts/me'), 'list_products': ('GET', '/products'), 'get_product': ('GET', '/products/{id}'), 'list_memberships': ('GET', '/memberships'), 'get_membership': ('GET', '/memberships/{id}'), 'list_payments': ('GET', '/payments'), 'get_payment': ('GET', '/payments/{id}'), 'list_refunds': ('GET', '/refunds'), 'get_refund': ('GET', '/refunds/{id}'), 'list_promo_codes': ('GET', '/promo_codes'), 'get_promo_code': ('GET', '/promo_codes/{id}'), 'create_product': ('POST', '/products'), 'update_product': ('PATCH', '/products/{id}'), 'delete_product': ('DELETE', '/products/{id}'), 'publish_product': ('POST', '/products/{id}/publish'), 'unpublish_product': ('POST', '/products/{id}/unpublish'), 'update_membership': ('PATCH', '/memberships/{id}'), 'cancel_membership': ('POST', '/memberships/{id}/cancel'), 'refund_payment': ('POST', '/payments/{id}/refund'), 'create_promo_code': ('POST', '/promo_codes'), 'activate_promo_code': ('POST', '/promo_codes/{id}/activate'), 'deactivate_promo_code': ('POST', '/promo_codes/{id}/deactivate')}


class WhopNode(WorkflowNode):
    integration_type = "automation-whop"
    connection_evidence = ConnectionEvidence(noun="Whop account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return WhopFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Whop API key")
        config = self.config.config
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in route:
            route = route.replace("{id}", quote(values.pop("id"), safe=""))
        headers = {"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json", "Api-Version-Date": "2026-11-07"}
        kwargs = {"params": values} if method == "GET" else {"json": values} if method != "DELETE" else {}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + route, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for connect, while redacting the key.
            message = response.text[:2000].replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(f"Whop HTTP {response.status_code}: {message}")
        if response.status_code == 204 or not response.content:
            data = {}
        else:
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("Expected Whop JSON object or array")
        output = {"status": "success", "data": data}
        await self.emit(output)
        return output
