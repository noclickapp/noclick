"""Soundee Producer API v1 operations, authenticated by a dashboard API key."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.soundee.com/me"


class SoundeeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Soundee API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://soundee.readme.io/reference/authentication",
            "x-credential-instructions": "Copy your API key from the Soundee Dashboard and paste it here. NoClick sends it in the X-API-KEY header to Soundee. Connecting reads your account details.",
        },
    )
    credential_type: Literal["soundee_api_key"] = Field("soundee_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _List(_Operation):
    q: str | None = Field(None, title="Search", max_length=1000)
    offset: int = Field(0, ge=0, title="Offset", description="Records to skip. Pagination is documented at https://soundee.readme.io/reference/pagination.")
    limit: int = Field(30, ge=1, le=100, title="Limit", description="Maximum records on this page. This operation returns one page.")


class GetAccount(_Operation):
    """Read the account associated with this API key."""
    operation: Literal["get_account"] = "get_account"


class ListCoupons(_List):
    """List or search coupon codes."""
    operation: Literal["list_coupons"] = "list_coupons"
    list_type: Literal["active", "expired", "scheduled", "unactive"] | None = Field(None, title="Coupon State")


class GetCoupon(_Operation):
    """Get one coupon by its numeric ID."""
    operation: Literal["get_coupon"] = "get_coupon"
    id: int = Field(..., title="Coupon ID", ge=1)


class CreateCoupon(_Operation):
    """Create a coupon with Soundee's defaults; use Update Coupon to set its fields."""
    operation: Literal["create_coupon"] = "create_coupon"


class CouponCondition(_Operation):
    exclude: bool | None = Field(None, description="Soundee's documented condition flag; see the update endpoint for inclusion semantics.")
    list: List[int] | None = Field(None, title="IDs")


class CouponConditions(_Operation):
    stores: CouponCondition | None = None
    entityTypes: CouponCondition | None = Field(None, title="Entity Types")
    entities: CouponCondition | None = None
    licenses: CouponCondition | None = None


class UpdateCoupon(_Operation):
    """Update only the supplied coupon fields; omitted fields are not sent."""
    operation: Literal["update_coupon"] = "update_coupon"
    id: int = Field(..., title="Coupon ID", ge=1)
    name: str | None = Field(None, title="Coupon Code")
    amount: float | None = Field(None, allow_inf_nan=False, description="Percentage for rate discounts; price for fixed discounts.")
    upgrades: Literal["0", "1", "2"] | None = Field(None, description="0: no upgrades; 1: upgrades included; 2: upgrades only.")
    active: bool | None = None
    maxUsage: int | None = Field(None, title="Maximum Uses", ge=0)
    type: Literal["rate", "fixed"] | None = Field(None, title="Discount Type")
    minCartItems: int | None = Field(None, title="Minimum Cart Items", ge=0)
    minCartAmount: float | None = Field(None, title="Minimum Cart Amount", ge=0, allow_inf_nan=False)
    stopBulkDiscounts: bool | None = Field(None, title="Stop Further Bulk Discounts")
    startDate: datetime | None = Field(None, title="Start Date")
    endDate: datetime | None = Field(None, title="End Date")
    neverEnd: bool | None = Field(None, title="Never Expire")
    conditions: CouponConditions | None = None


class ListEmailCaptures(_List):
    """List captured emails from downloads, transactions and store opt-ins."""
    operation: Literal["list_email_captures"] = "list_email_captures"
    list_type: Literal["download", "transaction", "store-email-opt-in", "exit-intent-opt-in"] | None = Field(None, title="Capture Source")


class ListCartAbandonments(_List):
    """List abandoned carts by state or customer search."""
    operation: Literal["list_cart_abandonments"] = "list_cart_abandonments"
    list_type: Literal["all", "recoverable", "ghost", "recovered", "converted"] = Field("all", title="Cart State")


class _StringID(_Operation):
    @field_validator("*", mode="after")
    @classmethod
    def single_segment(cls, value, info):
        if info.field_name in {"id", "id_or_token"}:
            if not value or value in {".", ".."} or len(value) > 512 or any(c in value for c in "/\\?#") or any(ord(c) < 33 or ord(c) == 127 for c in value):
                raise ValueError("Enter a single Soundee ID or token, without a URL")
        return value


class GetCartAbandonment(_StringID):
    """Get an abandoned cart by ID or token."""
    operation: Literal["get_cart_abandonment"] = "get_cart_abandonment"
    id_or_token: str = Field(..., title="Cart ID or Token")


class ListTransactions(_List):
    """List sales or refunds and search transaction details."""
    operation: Literal["list_transactions"] = "list_transactions"
    list_type: Literal["new-sale", "refund"] | None = Field(None, title="Transaction Type")


class GetTransaction(_StringID):
    """Get one transaction by its ID."""
    operation: Literal["get_transaction"] = "get_transaction"
    id: str = Field(..., title="Transaction ID")


SoundeeOperation = Annotated[Union[
    GetAccount, ListCoupons, GetCoupon, CreateCoupon, UpdateCoupon,
    ListEmailCaptures, ListCartAbandonments, GetCartAbandonment,
    ListTransactions, GetTransaction,
], Field(discriminator="operation")]


class SoundeeConfig(NodeConfig[SoundeeOperation, SoundeeAPIKeyCredential]):
    pass


ROUTES = {
    "get_account": ("GET", "/"),
    "list_coupons": ("GET", "/coupons"),
    "get_coupon": ("GET", "/coupons/{id}"),
    "create_coupon": ("POST", "/coupons"),
    "update_coupon": ("PUT", "/coupons/{id}"),
    "list_email_captures": ("GET", "/email-captures"),
    "list_cart_abandonments": ("GET", "/cart-abandonments"),
    "get_cart_abandonment": ("GET", "/cart-abandonments/{id_or_token}"),
    "list_transactions": ("GET", "/transactions"),
    "get_transaction": ("GET", "/transactions/{id}"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class SoundeeNode(WorkflowNode):
    integration_type = "automation-soundee"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return SoundeeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Soundee API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        for name in ("id", "id_or_token"):
            if hasattr(op, name):
                path = path.replace("{" + name + "}", quote(str(getattr(op, name)), safe=""))
        params = op.model_dump(exclude={"operation"}, exclude_none=True) if isinstance(op, _List) else None
        body = op.model_dump(mode="json", exclude={"operation", "id"}, exclude_none=True) if isinstance(op, UpdateCoupon) else None
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"X-API-KEY": secret, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Soundee returned a non-JSON response") from None
            if response.status_code != 200:
                result = {"status": "error", "status_code": response.status_code, "message": (data.get("message") or data) if isinstance(data, dict) and data else data or f"Soundee HTTP {response.status_code}",
                          "write_outcome": "unknown" if method != "GET" and response.status_code >= 500 else None}
            elif isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
                result = {"status": "error", "status_code": 200, "message": data}
            else:
                result = {"status": "success", "data": data}
        except httpx.RequestError:
            result = {"status": "error", "message": "Soundee request did not complete",
                      "write_outcome": "unknown" if method != "GET" else None}
        result = _redact(result, secret)
        await self.emit(result)
        return result
