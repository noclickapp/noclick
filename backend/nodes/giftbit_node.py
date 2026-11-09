"""Giftbit v1 reward and account operations.

Contract: https://docs.giftbit.com/api-reference (Giftbit's published OpenAPI v1).
Every operation issues one request; order creation is an acknowledgement, not
proof of delivery. Writes are never automatically retried.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
BASES = {
    "testbed": "https://api-testbed.giftbit.com/papi/v1",
    "production": "https://api.giftbit.com/papi/v1",
}


class GiftbitAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Giftbit API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.giftbit.com/guides/authentication",
            "x-credential-instructions": "In your Giftbit account, open Account → API keys and generate an API token. Paste the token without the Bearer prefix and select its environment. Testbed and Production use separate tokens. NoClick checks the connected account with Giftbit's read-only ping endpoint.",
        })
    credential_type: Literal["giftbit_api_token"] = Field("giftbit_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})
    environment: Literal["testbed", "production"] = Field("testbed", title="Environment",
        description="Use the environment where this token was created. Production orders spend real funds.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetAccount(_Input):
    """Check authentication and retrieve the connected username and display name."""
    operation: Literal["get_account"] = "get_account"


class _Page(_Input):
    limit: int = Field(20, ge=1, le=1000, description="Maximum results in this page.")
    offset: int = Field(0, ge=0, description="Result offset. Use next_offset to request the next page.")


class ListBrands(_Page):
    """List reward brands and their required disclaimer text."""
    operation: Literal["list_brands"] = "list_brands"
    region: int | None = None
    max_price_in_cents: int | None = Field(None, ge=0)
    min_price_in_cents: int | None = Field(None, ge=0)
    currencyisocode: Literal["CAD", "USD", "AUD"] | None = None
    search: str | None = None
    embeddable: bool | None = None


class GetBrand(_Input):
    """Retrieve a brand's regions, allowed values and in-app availability."""
    operation: Literal["get_brand"] = "get_brand"
    brand_code: str = Field(..., min_length=1, max_length=256)


class ListRegions(_Input):
    """List regions available for reward selection."""
    operation: Literal["list_regions"] = "list_regions"


class Contact(_Input):
    email: str = Field(..., min_length=3)
    firstname: str | None = None
    lastname: str | None = None

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if "@" not in value or any(c.isspace() for c in value):
            raise ValueError("Use a recipient email address")
        return value


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


def _array(value, label):
    try:
        result = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a JSON array") from None
    if not isinstance(result, list):
        raise ValueError(f"{label} must be a JSON array")
    return result


class _Order(_Input):
    id: str = Field(..., min_length=1, max_length=512, description="Unique client-assigned order ID. Keep the same ID when reconciling or retrying this order.")
    price_in_cents: int = Field(..., gt=0)
    brand_codes: str | None = Field(None, description='JSON array of brand codes, e.g. ["itunesus", "amazonus"]. Omit when choosing a full catalog region.', json_schema_extra=JSON_EDITOR)
    region: str | None = Field(None, min_length=1, description="Full Catalog region, such as USA or Canada. Omit when specifying brand codes.")
    expiry: str | None = Field(None, description="Claim-before date, YYYY-MM-dd. Provider enforces the one-year maximum.")

    @field_validator("brand_codes")
    @classmethod
    def brands(cls, value):
        if value is not None:
            rows = _array(value, "Brand codes")
            if not rows or any(not isinstance(v, str) or not v.strip() for v in rows):
                raise ValueError("Brand codes must contain nonempty strings")
        return value

    @field_validator("expiry")
    @classmethod
    def date(cls, value):
        if value is not None:
            try:
                if datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") != value:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use a date in YYYY-MM-dd format") from None
        return value


class CreateOrder(_Order):
    """Create email or shortlink rewards. Acknowledges order creation, not delivery."""
    operation: Literal["create_order"] = "create_order"
    message: str | None = None
    subject: str | None = None
    gift_template: str | None = Field(None, min_length=1)
    contacts: str | None = Field(None, description="JSON array of recipients with email, and optional firstname and lastname. Required for email delivery.", json_schema_extra=JSON_EDITOR)
    delivery_type: Literal["GIFTBIT_EMAIL", "SHORTLINK"] = "GIFTBIT_EMAIL"
    link_count: int | None = Field(None, gt=0)

    @field_validator("contacts")
    @classmethod
    def recipients(cls, value):
        if value is not None:
            rows = _array(value, "Contacts")
            if not rows:
                raise ValueError("Provide at least one recipient")
            for row in rows:
                Contact.model_validate(row)
        return value

    @model_validator(mode="after")
    def delivery(self):
        if not self.gift_template and not (self.message and self.subject):
            raise ValueError("Supply a gift template or both message and subject")
        if self.delivery_type == "GIFTBIT_EMAIL" and self.contacts is None:
            raise ValueError("Email orders require contacts")
        if self.delivery_type == "SHORTLINK" and self.link_count is None:
            raise ValueError("Shortlink orders require link_count")
        if not self.gift_template and not (self.brand_codes or self.region):
            raise ValueError("Choose brand codes or a full catalog region")
        return self


class GetOrder(_Input):
    """Retrieve an order using its client-assigned ID or Giftbit UUID."""
    operation: Literal["get_order"] = "get_order"
    id: str = Field(..., min_length=1, max_length=512)


class GetLinks(_Input):
    """Retrieve shortlink or direct-link URLs; generation may still be pending."""
    operation: Literal["get_links"] = "get_links"
    id: str = Field(..., min_length=1, max_length=512, description="Client-assigned order ID. If pending, call again after five minutes.")


class CreateDirectLinkOrder(_Order):
    """Order direct reward links with minimal branding."""
    operation: Literal["create_direct_link_order"] = "create_direct_link_order"
    link_count: int | None = Field(None, gt=0)

    @model_validator(mode="after")
    def choice(self):
        if not (self.brand_codes or self.region):
            raise ValueError("Choose brand codes or a full catalog region")
        return self


class CreateEmbeddedReward(_Input):
    """Create a single immediately claimed in-app reward; it cannot be cancelled."""
    operation: Literal["create_embedded_reward"] = "create_embedded_reward"
    id: str = Field(..., min_length=1, max_length=512)
    price_in_cents: int = Field(..., gt=0)
    brand_code: str = Field(..., min_length=1, max_length=256)


class GetFunds(_Input):
    """Read available, pending and reserved balances by currency."""
    operation: Literal["get_funds"] = "get_funds"


class AddFunds(_Input):
    """Charge the card on file to add funds. Requires a card saved in Giftbit."""
    operation: Literal["add_funds"] = "add_funds"
    currencyisocode: Literal["CAD", "USD"]
    fund_amount_in_cents: int = Field(..., gt=0, description="Funding amount in cents, subject to Giftbit's minimum and maximum.")
    id: str = Field(..., min_length=1, max_length=512, description="Unique client-assigned funding event ID.")


class ListRewards(_Page):
    """List one page of rewards with the provider's filters and sorting."""
    operation: Literal["list_rewards"] = "list_rewards"
    uuid: str | None = None
    campaign_uuid: str | None = None
    campaign_id: str | None = None
    price_in_cents_greater_than: int | None = None
    price_in_cents_less_than: int | None = None
    recipient_name: str | None = None
    recipient_email: str | None = None
    delivery_status: Literal["UNSENT", "DELIVERED", "UNDELIVERABLE", "TEMPORARILY_UNDELIVERABLE", "UNSUBSCRIBED", "COMPLAINT"] | None = None
    status: Literal["SENT_AND_REDEEMABLE", "REDEEMED", "TO_CHARITY", "GIVER_CANCELLED", "EXPIRED"] | None = None
    created_date_greater_than: str | None = None
    created_date_less_than: str | None = None
    delivery_date_greater_than: str | None = None
    delivery_date_less_than: str | None = None
    redelivery_count_greater_than: int | None = None
    redelivery_count_less_than: int | None = None
    redeemed_date_greater_than: str | None = None
    redeemed_date_less_than: str | None = None
    sort: Literal["campaign_id", "price_in_cents", "recipient_name", "recipient_email", "delivery_status", "status"] | None = None
    order: Literal["asc", "desc"] = "desc"

    @field_validator("created_date_greater_than", "created_date_less_than", "delivery_date_greater_than", "delivery_date_less_than", "redeemed_date_greater_than", "redeemed_date_less_than")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                if datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S") != value:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use yyyy-MM-dd HH:mm:ss") from None
        return value


class GetReward(_Input):
    """Retrieve an individual reward, distinct from its parent order."""
    operation: Literal["get_reward"] = "get_reward"
    uuid: str = Field(..., min_length=1, max_length=256)


class ResendReward(_Input):
    """Request another email delivery attempt. Embedded rewards are ineligible."""
    operation: Literal["resend_reward"] = "resend_reward"
    uuid: str = Field(..., min_length=1, max_length=256)


class CancelReward(_Input):
    """Cancel an unclaimed reward. Embedded or already claimed rewards are ineligible."""
    operation: Literal["cancel_reward"] = "cancel_reward"
    uuid: str = Field(..., min_length=1, max_length=256)


GiftbitConfig = Annotated[Union[GetAccount, ListBrands, GetBrand, ListRegions,
    CreateOrder, GetOrder, GetLinks, CreateDirectLinkOrder, CreateEmbeddedReward,
    GetFunds, AddFunds, ListRewards, GetReward, ResendReward, CancelReward], Field(discriminator="operation")]


class GiftbitNodeConfig(NodeConfig[GiftbitConfig, GiftbitAPITokenCredential]):
    pass


# Exact operation-to-contract mapping; path values are encoded as one segment.
ROUTES = {
    "get_account": ("GET", "/ping"),
    "list_brands": ("GET", "/brands"),
    "get_brand": ("GET", "/brands/{brand_code}"),
    "list_regions": ("GET", "/regions"),
    "create_order": ("POST", "/campaign"),
    "get_order": ("GET", "/campaign/{id}"),
    "get_links": ("GET", "/links/{id}"),
    "create_direct_link_order": ("POST", "/direct_links"),
    "create_embedded_reward": ("POST", "/embedded"),
    "get_funds": ("GET", "/funds"),
    "add_funds": ("POST", "/funds"),
    "list_rewards": ("GET", "/gifts"),
    "get_reward": ("GET", "/gifts/{uuid}"),
    "resend_reward": ("PUT", "/gifts/{uuid}"),
    "cancel_reward": ("DELETE", "/gifts/{uuid}"),
}


class GiftbitNode(WorkflowNode):
    integration_type = "automation-giftbit"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account", identity_keys=("displayname", "username"))

    @classmethod
    def get_config_model(cls):
        return GiftbitNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Giftbit API token")
        credential = self.config.credentials
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for key in ("brand_code", "id", "uuid"):
            if "{" + key + "}" in path:
                value = values.pop(key)
                if value in {".", ".."} or any(ord(c) < 32 for c in value):
                    raise ValueError("Use a Giftbit resource identifier")
                path = path.replace("{" + key + "}", quote(value, safe=""))
        if config.operation in {"create_order", "create_direct_link_order"}:
            for key in ("contacts", "brand_codes"):
                if key in values:
                    values[key] = json.loads(values[key])
        if config.operation == "resend_reward":
            values = {"resend": True}
        kwargs = {"params": values} if method == "GET" else {"json": values} if method != "DELETE" else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASES[credential.environment] + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}, **kwargs)
        except httpx.RequestError:
            raise ValueError("Giftbit request could not be completed. A write may have been accepted; inspect the order or funding event before retrying.") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Giftbit returned a non-JSON response (HTTP {response.status_code})") from None
        if response.status_code != 200 or not isinstance(payload, dict) or payload.get("error"):
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            message = error.get("message") if isinstance(error, dict) else None
            message = str(message or f"Giftbit request failed (HTTP {response.status_code})").replace(credential.api_token, "[redacted]")
            raise ValueError(message)
        # Keep the provider envelope (including its order status and link readiness)
        # so callers can distinguish acceptance, pending generation and delivery.
        output = _redact(payload, credential.api_token)
        if config.operation == "get_account" and not any(isinstance(output.get(k), str) and output[k] for k in ("username", "displayname")):
            raise ValueError("Giftbit did not return a recognizable account")
        if config.operation in {"list_brands", "list_rewards"}:
            rows = output.get("brands" if config.operation == "list_brands" else "gifts")
            if not isinstance(rows, list):
                raise ValueError("Giftbit did not return the requested result page")
            offset = output.get("offset", config.offset)
            total = output.get("total_count")
            output["next_offset"] = offset + len(rows) if type(offset) is int and type(total) is int and rows and offset + len(rows) < total else None
        await self.emit(output)
        return output
