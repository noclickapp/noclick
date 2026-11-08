"""Trackdesk tenant API actions using a personal access token.

Each action sends one documented request. List actions return one page with the
provider's pagination unchanged so callers can explicitly request the next page.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

UUIDString = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"), Field(json_schema_extra={"format": "uuid"})]
PublicID = Annotated[str, StringConstraints(min_length=2, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$")]
AccountStatus = Literal["ACCOUNT_STATUS_DISABLED", "ACCOUNT_STATUS_ENABLED", "ACCOUNT_STATUS_PENDING"]
ConversionStatus = Literal["CONVERSION_STATUS_APPROVED", "CONVERSION_STATUS_FRAUD", "CONVERSION_STATUS_NOT_ALLOWED", "CONVERSION_STATUS_BLOCKED", "CONVERSION_STATUS_ON_HOLD", "CONVERSION_STATUS_PENDING", "CONVERSION_STATUS_REFUNDED", "CONVERSION_STATUS_REJECTED", "CONVERSION_STATUS_TEST", "CONVERSION_STATUS_QUALITY_CONTROL"]
CouponStatus = Literal["COUPON_STATUS_ACTIVE", "COUPON_STATUS_INACTIVE", "COUPON_STATUS_REMOVED"]
TagScope = Literal["TAG_SCOPE_ADVERTISERS", "TAG_SCOPE_AFFILIATE_MANAGERS", "TAG_SCOPE_AFFILIATES", "TAG_SCOPE_OFFERS"]


class TrackdeskAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Trackdesk API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.trackdesk.com/",
            "x-credential-instructions": "In your Trackdesk program, open your name → Settings → Integrations → Personal access tokens. Generate an API key and paste it here with your program's tenant subdomain. The key inherits your account permissions.",
        })
    credential_type: Literal["trackdesk_api_key"] = Field("trackdesk_api_key", json_schema_extra={"ui:hidden": True})
    tenant_id: str = Field(..., title="Tenant subdomain", description="The tenant in https://your-program.trackdesk.com; you can also paste that program URL.", min_length=1, max_length=63)
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("tenant_id", mode="before")
    @classmethod
    def tenant(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Trackdesk tenant subdomain or program URL")
        value = value.strip().lower()
        if "://" in value:
            parts = urlsplit(value)
            if (parts.scheme != "https" or parts.username or parts.password or parts.port is not None
                    or parts.query or parts.fragment or parts.path not in {"", "/"}
                    or not parts.netloc.endswith(".trackdesk.com")):
                raise ValueError("Use your HTTPS Trackdesk program URL without a path, port or query")
            value = parts.netloc.removesuffix(".trackdesk.com")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Use a single Trackdesk tenant subdomain")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, populate_by_name=True)


class _Page(_Input):
    limit: int = Field(50, ge=1, le=500, description="Maximum rows in this page.")
    offset: int = Field(0, ge=0, description="Rows to skip; increase by the page size to continue.")


class ListAffiliates(_Page):
    """List affiliates in your program, one page at a time."""
    operation: Literal["list_affiliates"] = "list_affiliates"


class GetAffiliate(_Input):
    """Read an affiliate by its account UUID."""
    operation: Literal["get_affiliate"] = "get_affiliate"
    account_id: UUIDString


class CreateAffiliate(_Input):
    """Register an affiliate; sending the welcome email is an explicit option."""
    operation: Literal["create_affiliate"] = "create_affiliate"
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    status: AccountStatus = "ACCOUNT_STATUS_PENDING"
    public_id: PublicID | None = None
    password: str | None = Field(None, min_length=6, max_length=255, json_schema_extra={"ui:widget": "password"})
    should_send_welcome_email: bool = Field(False, description="Ask Trackdesk to send the new affiliate a welcome email with a login link.")


class SetAffiliateStatus(_Input):
    """Change an affiliate's traffic status using its public ID."""
    operation: Literal["set_affiliate_status"] = "set_affiliate_status"
    public_id: PublicID
    status: AccountStatus


class SetAffiliateTier(_Input):
    """Assign a payout tier to an affiliate by public ID."""
    operation: Literal["set_affiliate_tier"] = "set_affiliate_tier"
    public_id: PublicID
    tier_id: UUIDString


class ListOffers(_Page):
    """List offers including pricing and landing pages."""
    operation: Literal["list_offers"] = "list_offers"
    name: str | None = Field(None, max_length=255, description="Partial case-insensitive offer name.")


class GetOffer(_Input):
    """Read an offer including pricing and landing pages."""
    operation: Literal["get_offer"] = "get_offer"
    offer_id: UUIDString


class ListCoupons(_Page):
    """List coupons, optionally filtering by affiliate or offer."""
    operation: Literal["list_coupons"] = "list_coupons"
    source_id: UUIDString | None = None
    offer_id: UUIDString | None = None


class CreateCoupon(_Input):
    """Create a coupon for one affiliate traffic source and offer."""
    operation: Literal["create_coupon"] = "create_coupon"
    source_id: UUIDString
    offer_id: UUIDString
    code: str = Field(..., min_length=2, max_length=255)
    status: CouponStatus = "COUPON_STATUS_ACTIVE"


class DeleteCoupon(_Input):
    """Delete a coupon by its UUID."""
    operation: Literal["delete_coupon"] = "delete_coupon"
    coupon_id: UUIDString


class CreateConversion(_Input):
    """Record a click-attributed conversion with an external ID for deduplication."""
    operation: Literal["create_conversion"] = "create_conversion"
    cid: UUIDString = Field(..., description="Trackdesk click identification UUID.")
    conversion_type_code: str = Field(..., min_length=1, max_length=20)
    amount: str = Field(..., pattern=r"^-?[0-9]+(\.[0-9]+)?$", description="Decimal revenue amount, sent without floating-point conversion.")
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    external_id: str = Field(..., min_length=1, max_length=255, description="Your unique transaction ID. Trackdesk deduplicates within the conversion type (and revenue origin for network accounts).")
    status: Literal["CONVERSION_STATUS_APPROVED", "CONVERSION_STATUS_PENDING", "CONVERSION_STATUS_ON_HOLD"] = "CONVERSION_STATUS_PENDING"


class SetConversionStatus(_Input):
    """Change the status of an existing conversion."""
    operation: Literal["set_conversion_status"] = "set_conversion_status"
    conversion_id: UUIDString
    status: ConversionStatus


class ListAccountNotes(_Input):
    """List the notes attached to one affiliate account."""
    operation: Literal["list_account_notes"] = "list_account_notes"
    account_id: UUIDString


class CreateAccountNote(_Input):
    """Add a note to an affiliate account."""
    operation: Literal["create_account_note"] = "create_account_note"
    account_id: UUIDString
    note: str = Field(..., min_length=1, max_length=255)


class DeleteAccountNote(_Input):
    """Delete a single affiliate account note."""
    operation: Literal["delete_account_note"] = "delete_account_note"
    note_id: UUIDString


class ListTags(_Input):
    """List your program's tags; also used to verify the connection."""
    operation: Literal["list_tags"] = "list_tags"


class GetTag(_Input):
    """Read a tag by its UUID."""
    operation: Literal["get_tag"] = "get_tag"
    tag_id: UUIDString


class CreateTag(_Input):
    """Create a colored tag for the selected resource scope."""
    operation: Literal["create_tag"] = "create_tag"
    name: str = Field(..., min_length=1, max_length=50, pattern=r"\S")
    hex_color_code: str = Field(..., pattern=r"^#[0-9A-F]{6}$")
    tag_scope: TagScope


class ListTiers(_Input):
    """List your program's affiliate payout tiers."""
    operation: Literal["list_tiers"] = "list_tiers"


class GetTier(_Input):
    """Read an affiliate tier and its payout rates."""
    operation: Literal["get_tier"] = "get_tier"
    tier_id: UUIDString


class BuildTrackingLink(_Input):
    """Build a direct tracking link to an offer's landing page."""
    operation: Literal["build_tracking_link"] = "build_tracking_link"
    source_id: UUIDString
    offer_id: UUIDString
    landing_page_id: UUIDString


TrackdeskOperation = Annotated[Union[ListAffiliates, GetAffiliate, CreateAffiliate, SetAffiliateStatus, SetAffiliateTier,
    ListOffers, GetOffer, ListCoupons, CreateCoupon, DeleteCoupon, CreateConversion, SetConversionStatus,
    ListAccountNotes, CreateAccountNote, DeleteAccountNote, ListTags, GetTag, CreateTag,
    ListTiers, GetTier, BuildTrackingLink], Field(discriminator="operation")]


class TrackdeskConfig(NodeConfig[TrackdeskOperation, TrackdeskAPIKeyCredential]):
    pass


# Method, path and the config field interpolated into the path, if any.
ROUTES = {
    "list_affiliates": ("POST", "/api/node/affiliates/v1", None),
    "get_affiliate": ("GET", "/api/node/affiliates/v1/{id}", "account_id"),
    "create_affiliate": ("POST", "/api/node/affiliates/v1/register-with-user", None),
    "set_affiliate_status": ("PUT", "/api/node/affiliates/v1/{id}/status", "public_id"),
    "set_affiliate_tier": ("PUT", "/api/node/affiliates/v1/{id}/tier", "public_id"),
    "list_offers": ("POST", "/api/node/offers/v1/list", None),
    "get_offer": ("GET", "/api/node/offers/v1/{id}", "offer_id"),
    "list_coupons": ("POST", "/api/node/coupons/v1/list", None),
    "create_coupon": ("POST", "/api/node/coupons/v1", None),
    "delete_coupon": ("DELETE", "/api/node/coupons/v1/{id}", "coupon_id"),
    "create_conversion": ("POST", "/tracking/conversion/v1", None),
    "set_conversion_status": ("PUT", "/api/node/conversions/v1/{id}/status", "conversion_id"),
    "list_account_notes": ("GET", "/api/node/account-notes/v1/account/{id}", "account_id"),
    "create_account_note": ("POST", "/api/node/account-notes/v1", None),
    "delete_account_note": ("DELETE", "/api/node/account-notes/v1/{id}", "note_id"),
    "list_tags": ("GET", "/api/node/tags/v1", None),
    "get_tag": ("GET", "/api/node/tags/v1/{id}", "tag_id"),
    "create_tag": ("POST", "/api/node/tags/v1", None),
    "list_tiers": ("GET", "/api/node/tiers/v1", None),
    "get_tier": ("GET", "/api/node/tiers/v1/{id}", "tier_id"),
    "build_tracking_link": ("POST", "/api/node/tracking-links/v1/build", None),
}


def request_parts(config):
    method, path, path_field = ROUTES[config.operation]
    if path_field:
        path = path.format(id=getattr(config, path_field))
    body = config.model_dump(exclude_none=True, exclude={"operation", path_field} if path_field else {"operation"})
    if isinstance(config, _Page):
        body["pagination"] = {"limit": body.pop("limit"), "offset": body.pop("offset")}
    if isinstance(config, ListCoupons):
        body = {"pagination": body["pagination"], **({"sourceIds": [config.source_id]} if config.source_id else {}), **({"offerIds": [config.offer_id]} if config.offer_id else {})}
    elif isinstance(config, CreateAffiliate):
        body = {"email": str(config.email), "name": config.name, "status": config.status,
            "shouldSendWelcomeEmail": config.should_send_welcome_email,
            **({"password": config.password} if config.password is not None else {}),
            **({"publicId": {"value": config.public_id}} if config.public_id else {})}
    elif isinstance(config, SetAffiliateTier):
        body = {"tierId": config.tier_id}
    elif isinstance(config, CreateCoupon):
        body = {"source": {"id": config.source_id}, "offerId": config.offer_id, "code": config.code, "status": config.status}
    elif isinstance(config, CreateConversion):
        body = {"cid": config.cid, "conversionTypeCode": config.conversion_type_code, "amount": {"value": config.amount}, "externalId": config.external_id, "status": config.status, **({"currency": {"code": config.currency}} if config.currency else {})}
    elif isinstance(config, CreateAccountNote):
        body = {"accountId": config.account_id, "note": config.note}
    elif isinstance(config, CreateTag):
        body = {"name": config.name, "hexColorCode": config.hex_color_code, "scopes": [config.tag_scope]}
    elif isinstance(config, BuildTrackingLink):
        body = {"sourceId": config.source_id, "offerId": config.offer_id, "target": {"direct": {"landingPageId": config.landing_page_id}}}
    return method, path, body if method in {"POST", "PUT", "PATCH"} else None


class TrackdeskNode(WorkflowNode):
    integration_type = "automation-trackdesk"
    connection_evidence = ConnectionEvidence(operation="list_tags", noun="tags")

    @classmethod
    def get_config_model(cls):
        return TrackdeskConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Trackdesk API key")
        method, path, body = request_parts(self.config.config)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, f"https://{credential.tenant_id}.trackdesk.com{path}",
                headers={"X-Api-Key": credential.api_key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection for the manual-connect verdict,
            # while keeping an echoed credential out of workflow output.
            message = response.text[:2000].replace(credential.api_key, "[redacted]")
            return {"status": "error", "error": message, "http_status": response.status_code}
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Trackdesk returned an unexpected JSON response")
        if isinstance(self.config.config, ListTags):
            tags = result.get("tags")
            if not isinstance(tags, list) or any(not isinstance(tag, dict) or not isinstance(tag.get("name"), str) or not isinstance(tag.get("id"), str) for tag in tags):
                raise ValueError("Trackdesk returned an unexpected tag list")
        return {"status": "success", "data": result}
