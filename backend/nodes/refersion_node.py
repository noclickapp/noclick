"""Refersion REST v2026-08: explicit operations against the published 3.0.0 contract.

Contract: https://refersion.dev/openapi/api-public.resolved.json
Authentication: https://refersion.dev/docs/api-reference/authentication/
Tokens are supplied by the person connecting; no token issuance or sign-in occurs.
Lists return one provider page and preserve its pagination metadata.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.refersion.com/v2026-08"


class RefersionAccessTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Refersion Access Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://refersion.dev/docs/api-reference/authentication/",
            "x-credential-instructions": "In Refersion, open Settings → Integrations → Refersion API Keys and generate an OAuth client. Follow the linked guide to exchange its Client ID and Client Secret for an access token, using token_type=long_lived for a 90-day token. Paste only the returned access_token here. Replace it when it expires; issuing another token of the same lifetime immediately revokes the previous token. NoClick does not issue or refresh tokens.",
        },
    )
    credential_type: Literal["refersion_access_token"] = Field(
        "refersion_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access token",
        min_length=1,
        max_length=8192,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("access_token", mode="before")
    @classmethod
    def clean_token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError("Paste only the access token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, hide_input_in_errors=True
    )


class RefersionListAffiliatesConfig(_Input):
    'List Affiliates. Retrieves a paginated list of affiliates for the authenticated merchant.\nIncludes affiliate profile information, offer details, and performance metrics.\n\nSupports filtering by status, search term, performance metrics, and offer IDs.\nThe `status=approved` filter returns both regular APPROVED and locked-APPROVED\naffiliates; check the `locked` field on each record to distinguish them.\nThe `status=denied` filter returns both DENIED and BANNED affiliates; banned\nrecords expose `status: "BANNED"` so they can be distinguished per row.'
    operation: Literal["list_affiliates"] = Field(
        "list_affiliates", json_schema_extra={"ui:hidden": True}
    )
    status: list[Literal["pending", "approved", "denied"]] | None = Field(None)
    search: str | None = Field(None, max_length=255)
    has_pending_conversions: bool | None = Field(None)
    last_conversion_days_ago: int | None = Field(None, ge=0)
    offer_ids: list[int] | None = Field(None)
    page: int | None = Field(None, ge=1, description="Provider page boundary")
    limit: int | None = Field(None, ge=1, le=100, description="Provider page boundary")


class RefersionGetAffiliateCountsConfig(_Input):
    "Get Affiliate Counts. Returns the count of affiliates grouped by status (pending, approved, denied)\nfor the authenticated merchant. The deniedCount includes BANNED affiliates —\nbanned affiliates are counted within the denied bucket. When called without\nfilter parameters, results are cached for 1 minute.\n\nSupports the same filter parameters as GET /affiliates. When filters are supplied,\nthe cache is bypassed and counts reflect the filtered result set. Performance-specific\nfilters (the 34-parameter matrix across the pending, 30-day, and total buckets,\nplus hasPendingConversions and lastConversionDaysAgo) narrow only the approvedCount;\npendingCount and deniedCount are not affected by those filters."
    operation: Literal["get_affiliate_counts"] = Field(
        "get_affiliate_counts", json_schema_extra={"ui:hidden": True}
    )
    search: str | None = Field(None, max_length=255)
    has_pending_conversions: bool | None = Field(None)
    last_conversion_days_ago: int | None = Field(None, ge=0)
    offer_ids: list[int] | None = Field(None)


class RefersionGetAffiliateActivityConfig(_Input):
    "Get Affiliate Activity. Retrieves weekly conversion, payment, and click activity for a specific affiliate\nmerged into a single timeline ordered by `date` descending and capped at 10 entries.\nEach source (conversion, payment, click) is independently bounded to the rolling\nlast 10 weeks and capped at 5 entries before the merge.\n\nThe response shape is polymorphic on `type`. Conversion entries include\n`conversionCount`, `total`, and `currency`; payment entries include\n`paidConversionCount`, `total`, and `currency`; click entries include `clickCount`\n(no `total` or `currency`)."
    operation: Literal["get_affiliate_activity"] = Field(
        "get_affiliate_activity", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., description="The unique identifier of the affiliate", ge=1)


class UrlBody(_Input):
    path: str | None = Field(
        None,
        description="The custom URL path (default subfolder) for the affiliate. Accepts the\n{macro} tokens the referral-link Lambda resolves per affiliate at link\ngeneration time: {affiliate_id}, {affiliate_code}, {affiliate_first_name},\n{affiliate_last_name}, {company_name}, {offer_id}.",
        examples=["shop/{affiliate_code}"],
    )
    additional_parameters: str | None = Field(
        None,
        alias="additionalParameters",
        description="Additional query parameters for the affiliate URL",
        examples=["utm_source=affiliate&utm_medium=link"],
    )


class CustomfieldsitemBody(_Input):
    id: int = Field(..., description="The custom field ID", examples=[1])
    value: str = Field(
        ..., description="The custom field value", examples=["My answer"]
    )


class UpdateAffiliateRequest(_Input):
    id: int = Field(..., description="The affiliate ID to update", examples=[12345])
    status: str | None = Field(
        None,
        description="The new status for the affiliate (PENDING, APPROVED, or DENIED). To lock or\nunlock an APPROVED affiliate, use the `locked` field instead of this one.",
        examples=["APPROVED"],
    )
    locked: bool | None = Field(
        None,
        description="Whether to lock the affiliate. true sets the affiliate's lock state ON;\nfalse unlocks it. Only accepted when the affiliate's current status is\nAPPROVED. Cannot be combined with the `status` field in the same request.",
        examples=[True],
    )
    offer_id: int | None = Field(
        None,
        alias="offerId",
        description="The offer ID to assign to the affiliate",
        examples=[42],
    )
    unique_merchant_id: str | None = Field(
        None,
        alias="uniqueMerchantId",
        description="The merchant-assigned external identifier for the affiliate",
        examples=["MERCH-12345"],
    )
    parent_affiliate_id: int | None = Field(
        None,
        alias="parentAffiliateId",
        description="The id of another affiliate to set as this affiliate's MLM parent. Pass null to clear.",
        examples=[12345],
    )
    send_email_notifications: bool | None = Field(
        None,
        alias="sendEmailNotifications",
        description="Whether to send email notifications for the status change",
        examples=[False],
    )
    email: str | None = Field(
        None,
        description="The affiliate's email address. Must be unique within the merchant's affiliates,\nignoring the affiliate being updated.",
        examples=["affiliate@example.com"],
    )
    first_name: str | None = Field(
        None,
        alias="firstName",
        description="The affiliate's first name. Cannot be cleared.",
        examples=["Jane"],
    )
    last_name: str | None = Field(
        None,
        alias="lastName",
        description="The affiliate's last name. Cannot be cleared.",
        examples=["Doe"],
    )
    company: str | None = Field(
        None,
        description="The affiliate's company name. Pass null to clear.",
        examples=["Acme Inc"],
    )
    address1: str | None = Field(
        None,
        description="The affiliate's primary street address. Pass null to clear.",
        examples=["123 Main St"],
    )
    address2: str | None = Field(
        None,
        description="The affiliate's secondary street address (apartment, suite, etc). Pass null to clear.",
        examples=["Suite 100"],
    )
    city: str | None = Field(
        None,
        description="The affiliate's city. Pass null to clear.",
        examples=["New York"],
    )
    state: str | None = Field(
        None,
        description="The affiliate's state or subdivision code. Must belong to the country in scope\n(the new `country` value if provided, otherwise the affiliate's stored country).",
        examples=["NY"],
    )
    zip: str | None = Field(
        None,
        description="The affiliate's postal code. Pass null to clear.",
        examples=["10001"],
    )
    phone: str | None = Field(
        None,
        description="The affiliate's phone number in E.164 format. Pass null to clear.",
        examples=["+14155552671"],
    )
    country: str | None = Field(
        None,
        description="The affiliate's country as an active ISO 3166-1 alpha-2 code. Pass null to clear.",
        examples=["US"],
    )
    url: UrlBody | None = Field(
        None,
        description="URL configuration object",
        examples=[
            {"path": "my-custom-path", "additionalParameters": "utm_source=affiliate"}
        ],
    )
    custom_fields: list[CustomfieldsitemBody] | None = Field(
        None,
        alias="customFields",
        description="Array of custom field updates with id and value pairs, up to 100 entries",
        examples=[
            [{"id": 1, "value": "My answer"}, {"id": 2, "value": "Another answer"}]
        ],
    )


class RefersionUpdateAffiliateConfig(_Input):
    "Update Affiliate. Updates an affiliate's details including status, lock state, offer assignment,\ncustom fields, URL configuration, merchant-assigned external identifier, and\nparent affiliate assignment. Supports partial updates - only the fields provided\nin the request body will be updated.\n\nAny transition between the valid public statuses (APPROVED, PENDING, DENIED) is permitted.\nTransitioning from APPROVED to DENIED is blocked if the affiliate has pending or unpaid conversions.\nSetting status to DELETED or DISABLED is not allowed via this endpoint — DISABLED is an\ninternal flag managed via the `locked` field, and deletion uses the DELETE endpoint.\n\nThe `locked` field abstracts the internal DISABLED state: `locked: true` locks an APPROVED\naffiliate, and `locked: false` unlocks it. `locked` is only accepted when the affiliate's\ncurrent status is APPROVED, and it cannot be combined with `status` in the same request.\n\nThe `parentAffiliateId` field accepts another affiliate ID owned by the authenticated\nclient. Passing `null` clears the existing parent relationship."
    operation: Literal["update_affiliate"] = Field(
        "update_affiliate", json_schema_extra={"ui:hidden": True}
    )
    affiliate_id: int = Field(..., ge=1)
    body: UpdateAffiliateRequest = Field(
        ...,
        description="Documented JSON request body; omitted optional fields remain unchanged, explicit null clears nullable fields.",
    )


class RefersionGetAffiliateLinkConfig(_Input):
    "Generate Affiliate Tracking Link. Generates an affiliate tracking link for the specified affiliate.\n\nWhen the affiliate ID is set to 0, the endpoint uses the default test affiliate for the account.\n\nOptional parameters allow for test link generation, custom URLs, and marketing asset association."
    operation: Literal["get_affiliate_link"] = Field(
        "get_affiliate_link", json_schema_extra={"ui:hidden": True}
    )
    affiliate_id: int = Field(..., ge=1)
    test: bool | None = Field(
        None, description="Generate a test link for test orders", examples=[True]
    )
    url: str | None = Field(
        None,
        description="Custom URL to use for the tracking link",
        examples=["https://www.example.com"],
    )
    marketing_asset_id: int | None = Field(
        None,
        description="Marketing asset ID (creative ID) for the link",
        examples=[789],
    )
    amazon_product_id: int | None = Field(
        None,
        description="Amazon product ID. When provided, the endpoint generates a refer.as redirect\nlink bound to the (affiliate, Amazon product) pair instead of the affiliate's\ndefault referral URL. Only valid when the client has the Amazon integration enabled.",
        examples=[12345],
    )


class RefersionListAffiliateCustomFieldsConfig(_Input):
    "Get Affiliate Custom Fields. Retrieves all custom registration fields configured by the merchant for a given affiliate,\nalong with the affiliate's corresponding values."
    operation: Literal["list_affiliate_custom_fields"] = Field(
        "list_affiliate_custom_fields", json_schema_extra={"ui:hidden": True}
    )
    affiliate_id: int = Field(..., ge=1)


class PatchAffiliateCustomFieldRequest(_Input):
    affiliate_id: int = Field(
        ...,
        alias="affiliateId",
        description="The affiliate ID to update the custom field for",
        examples=[12345],
    )
    custom_field_id: int = Field(
        ...,
        alias="customFieldId",
        description="The custom field ID to update",
        examples=[42],
    )
    value: str = Field(
        ...,
        description="The new value for the custom field",
        examples=["My new answer"],
    )


class RefersionUpdateAffiliateCustomFieldConfig(_Input):
    "Update Affiliate Custom Field Value. Updates an affiliate's value for a specific custom registration field\nby modifying the affiliate's custom_fields JSON column."
    operation: Literal["update_affiliate_custom_field"] = Field(
        "update_affiliate_custom_field", json_schema_extra={"ui:hidden": True}
    )
    affiliate_id: int = Field(..., ge=1)
    custom_field_id: int = Field(..., ge=1)
    body: PatchAffiliateCustomFieldRequest = Field(
        ...,
        description="Documented JSON request body; omitted optional fields remain unchanged, explicit null clears nullable fields.",
    )


class RefersionDeleteAffiliateCustomFieldConfig(_Input):
    "Delete Affiliate Custom Field Value. Clears an affiliate's value for a specific custom registration field by removing\nthe entry from the affiliate's custom_fields JSON data. The custom field definition\nitself is not modified or deleted. This operation is idempotent."
    operation: Literal["delete_affiliate_custom_field"] = Field(
        "delete_affiliate_custom_field", json_schema_extra={"ui:hidden": True}
    )
    affiliate_id: int = Field(..., description="The affiliate ID", ge=1)
    custom_field_id: int = Field(..., description="The custom field ID to clear", ge=1)


class RefersionListClicksConfig(_Input):
    "Get Click Data. Retrieves click tracking data based on supplied query parameters. Returns click information\nincluding affiliate details, timestamps, IP addresses, user agents, and referral data.\nSupports pagination and filtering by date range and affiliate ID."
    operation: Literal["list_clicks"] = Field(
        "list_clicks", json_schema_extra={"ui:hidden": True}
    )
    created_at_min: str = Field(
        ...,
        description="Minimum creation timestamp (inclusive) in ISO 8601 format",
        examples=["2025-09-25T00:00:00Z"],
    )
    created_at_max: str = Field(
        ...,
        description="Maximum creation timestamp (inclusive) in ISO 8601 format",
        examples=["2025-09-25T23:59:59Z"],
    )
    affiliate_id: int | None = Field(
        None, description="Filter clicks by affiliate ID", examples=[456]
    )
    page: int | None = Field(
        None, description="Page number for pagination", examples=[1], ge=1
    )
    limit: int | None = Field(
        None, description="Items per page for pagination", examples=[50], ge=1, le=100
    )


class CreateManualCreditRequest(_Input):
    affiliate_id: int = Field(
        ...,
        alias="affiliateId",
        description="The affiliate ID receiving the manual credit.",
        examples=[123456],
    )
    commission_total: float = Field(
        ...,
        alias="commissionTotal",
        description="The commission amount for the manual credit. Allows negative values.",
        examples=[19.99],
    )
    currency: str = Field(
        ...,
        description="The ISO 4217 currency code for the commission.",
        examples=["USD"],
    )
    approval_status: str = Field(
        ...,
        alias="approvalStatus",
        description="The approval status for the manual credit.",
        examples=["APPROVED"],
    )
    notes: str | None = Field(
        None,
        description="Optional notes for the manual credit conversion.",
        examples=["Manual credit for Q4 bonus"],
    )


class RefersionCreateManualCreditConfig(_Input):
    "Create Manual Credit. Creates a manual credit conversion for an affiliate. Supports PENDING, APPROVED, and DENIED\nstatuses. For APPROVED and DENIED statuses, a notification is dispatched and a conversion_info\nrecord is created."
    operation: Literal["create_manual_credit"] = Field(
        "create_manual_credit", json_schema_extra={"ui:hidden": True}
    )
    body: CreateManualCreditRequest = Field(
        ...,
        description="Documented JSON request body; omitted optional fields remain unchanged, explicit null clears nullable fields.",
    )


class CreditOrderIdRequest(_Input):
    conversion_queue_id: int = Field(
        ...,
        alias="conversionQueueId",
        description="The conversion queue record ID to credit.",
        examples=[456789],
    )
    affiliate_id: int = Field(
        ...,
        alias="affiliateId",
        description="The affiliate ID to credit the order to.",
        examples=[123456],
    )
    approval_status: str = Field(
        ...,
        alias="approvalStatus",
        description="The approval status for the credited order.",
        examples=["APPROVED"],
    )
    notes: str | None = Field(
        None,
        description="Optional notes for the credited order.",
        examples=["Manual credit for order fulfillment"],
    )


class RefersionCreditOrderConfig(_Input):
    "Credit Order to Affiliate. Credits an existing order from the conversion queue to a specified affiliate.\nThe order is queued for processing and will be converted asynchronously."
    operation: Literal["credit_order"] = Field(
        "credit_order", json_schema_extra={"ui:hidden": True}
    )
    body: CreditOrderIdRequest = Field(
        ...,
        description="Documented JSON request body; omitted optional fields remain unchanged, explicit null clears nullable fields.",
    )


class RefersionGetConversionCountsConfig(_Input):
    "Get Conversion Counts. Returns counts of conversions grouped by status (pending, approved, paid, denied,\nunqualified) for the authenticated merchant. Supports the same filters as the\nconversions list endpoint, excluding status, page, limit, sortBy, and sortOrder.\nUnfiltered requests are cached for 1 minute per client; filtered requests bypass\nthe cache."
    operation: Literal["get_conversion_counts"] = Field(
        "get_conversion_counts", json_schema_extra={"ui:hidden": True}
    )
    search: str | None = Field(
        None,
        description="Search by order ID, conversion ID, or subscription ID. Minimum 3\ncharacters — leading-wildcard LIKE on `merchant_unique_id` and\n`merchant_subscription_id` cannot use an index, so short prefixes\ntrigger a full per-client substring scan that is too costly to\nserve as a typeahead.",
        examples=["ORD-9001"],
    )
    order_id: str | None = Field(
        None,
        description="Prefix filter against `merchant_unique_id` — returns counts for conversions whose order ID starts with this value. Mirrors the list endpoint's `orderId` filter exactly.",
        examples=["ORD-9001"],
    )
    affiliate_ids: list[int] | None = Field(
        None, description="Individual affiliate ID.", examples=[789]
    )
    offer_ids: list[int] | None = Field(
        None, description="Individual offer ID.", examples=[987]
    )
    created_at_min: str | None = Field(
        None,
        description="Minimum creation timestamp in ISO 8601 format (inclusive). A date-only value expands to the start of that day in the client timezone.",
        examples=["2026-03-01T00:00:00Z"],
    )
    created_at_max: str | None = Field(
        None,
        description="Maximum creation timestamp in ISO 8601 format (inclusive). A date-only value expands to the end of that day in the client timezone, and must resolve to an instant after the normalized createdAtMin.",
        examples=["2026-03-31T23:59:59Z"],
    )


class RefersionListConversionsConfig(_Input):
    "List Conversions. Retrieves a paginated list of conversions for the authenticated merchant.\nSupports filtering by status, order ID, affiliate, date range, offer, and platform.\nSupports sorting by order ID, affiliate, type, revenue, commission, date, source, and status."
    operation: Literal["list_conversions"] = Field(
        "list_conversions", json_schema_extra={"ui:hidden": True}
    )
    status: str | None = Field(
        None, description="Filter by conversion status tab", examples=["PENDING"]
    )
    page: int | None = Field(
        None, description="Page number for pagination", examples=[1], ge=1
    )
    limit: int | None = Field(
        None, description="Number of items per page", examples=[50], ge=1, le=100
    )
    sort_by: str | None = Field(
        None,
        description="Column to sort by. The affiliate option orders by displayed affiliate name:\ncompany when present, otherwise first and last name.",
        examples=["date"],
    )
    sort_order: str | None = Field(
        None, description="Sort direction", examples=["desc"]
    )
    order_id: str | None = Field(
        None,
        description="Filter by order ID prefix — returns conversions whose order ID starts with this value (prefix match, not substring)",
        examples=["ORD-12345"],
    )
    affiliate_ids: list[int] | None = Field(
        None, description="Individual affiliate ID", examples=[100]
    )
    created_at_min: str | None = Field(
        None,
        description="Filter by creation date minimum in ISO 8601 format (inclusive). A date-only value expands to the start of that day in the client timezone.",
        examples=["2026-01-01"],
    )
    created_at_max: str | None = Field(
        None,
        description="Filter by creation date maximum in ISO 8601 format (inclusive). A date-only value expands to the end of that day in the client timezone, and must resolve to an instant after the normalized createdAtMin.",
        examples=["2026-12-31"],
    )
    offer_ids: list[int] | None = Field(
        None, description="Individual offer ID", examples=[1]
    )
    platform: list[str] | None = Field(
        None, description="Individual platform name", examples=["Shopify"]
    )


class RefersionGetConversionConfig(_Input):
    "Get Conversion Detail. Retrieves the full detail view for a single conversion owned by the authenticated\nclient. The response includes affiliate info, offer info, click details, payment\nmethod, autoPay status, VIP status, and Amazon approval eligibility. Returns 404\nfor conversions that do not exist, are not owned by the authenticated client, or\nhave HIDDEN status."
    operation: Literal["get_conversion"] = Field(
        "get_conversion", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., description="The unique identifier of the conversion", ge=1)


class UpdateConversionStatusRequest(_Input):
    status: str = Field(
        ..., description="The new status for the conversion.", examples=["APPROVED"]
    )


class RefersionUpdateConversionStatusConfig(_Input):
    "Update Conversion Status. Updates the status of a single conversion. Supports transitions between\nPENDING, APPROVED, DENIED, and UNQUALIFIED statuses based on a defined\ntransition matrix. Creates an audit trail and dispatches webhook notifications\nfor APPROVED and DENIED transitions."
    operation: Literal["update_conversion_status"] = Field(
        "update_conversion_status", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., ge=1)
    body: UpdateConversionStatusRequest = Field(
        ...,
        description="Documented JSON request body; omitted optional fields remain unchanged, explicit null clears nullable fields.",
    )


class RefersionListOffersConfig(_Input):
    "List Offers. Retrieves a paginated list of offers for the authenticated client. Returns offer information\nincluding commission settings, attribution window, and various configuration options.\nSupports pagination, optional search filtering by offer name or ID, filtering by offer\ntype (multi-value, OR semantics), and performance-range filtering across 17 metrics\n(Min/Max bounds for the pending, 30-day, and total buckets)."
    operation: Literal["list_offers"] = Field(
        "list_offers", json_schema_extra={"ui:hidden": True}
    )
    type: list[str] | None = Field(
        None,
        description="Individual type value within the type array.",
        examples=["FLAT_RATE"],
    )
    search: str | None = Field(
        None,
        description="Search string to filter offers by name or ID",
        examples=["My Offer"],
    )
    page: int | None = Field(
        None, description="Page number for pagination (1-indexed)", examples=[1], ge=1
    )
    limit: int | None = Field(
        None, description="Number of items per page", examples=[50], ge=1, le=100
    )


class UpdateOfferRequest(_Input):
    name: str | None = Field(
        None,
        description="The display name for the offer",
        examples=["Summer Sale Offer"],
    )
    is_default: bool | None = Field(
        None,
        alias="isDefault",
        description="Whether this is the default offer for the client",
        examples=[True],
    )
    attribution_window: int | None = Field(
        None,
        alias="attributionWindow",
        description="Attribution window in days",
        examples=[30],
    )
    is_private: bool | None = Field(
        None,
        alias="isPrivate",
        description="Whether the offer is private",
        examples=[False],
    )
    commission: int | None = Field(
        None, description="The commission percentage or flat rate amount", examples=[10]
    )


class RefersionUpdateOfferConfig(_Input):
    "Update Offer. Updates an existing offer. Allows partial updates of one or more fields including\nname, default status, attribution window, private status, and commission.\nIf offerId is 0, the client's default offer will be updated."
    operation: Literal["update_offer"] = Field(
        "update_offer", json_schema_extra={"ui:hidden": True}
    )
    offer_id: int = Field(..., ge=0)
    body: UpdateOfferRequest = Field(
        ...,
        description="Documented JSON request body; omitted optional fields remain unchanged, explicit null clears nullable fields.",
    )


class RefersionDuplicateOfferConfig(_Input):
    "Duplicate Offer. Duplicates an offer owned by the authenticated client. Returns the new offer ID."
    operation: Literal["duplicate_offer"] = Field(
        "duplicate_offer", json_schema_extra={"ui:hidden": True}
    )
    offer_id: int = Field(..., ge=0)


class RefersionDeleteOfferConfig(_Input):
    "Delete Offer. Soft-deletes an offer owned by the authenticated client. The default offer\nand offers with assigned affiliates cannot be deleted. Refersion attempts to move a\nMarketplace listing that uses the deleted offer to the active default offer; with no active\ndefault offer, it attempts to turn the listing off."
    operation: Literal["delete_offer"] = Field(
        "delete_offer", json_schema_extra={"ui:hidden": True}
    )
    offer_id: int = Field(..., ge=0)


class RefersionSearchOrdersConfig(_Input):
    "Search Orders. Searches for orders by order ID and determines if an affiliate can be credited.\nReturns available orders and any other affiliates that already have conversions\nfor the same order."
    operation: Literal["search_orders"] = Field(
        "search_orders", json_schema_extra={"ui:hidden": True}
    )
    search: str = Field(
        ..., description="The order ID to search for.", examples=["ORD-12345"]
    )
    affiliate_id: int = Field(
        ...,
        description="The affiliate ID to check conversions against.",
        examples=[123456],
    )


class RefersionListWebhookEndpointsConfig(_Input):
    "List Webhook Endpoints. Lists the webhook endpoints for the authenticated Refersion user.\nCursor-paginated. Some users may receive a 402 if their plan doesn't\ninclude webhook access. The user's webhook configuration is\nauto-provisioned on first call — no endpoints yet just means an empty\nlist, not an error. Each row has the endpoint's id, url, subscribed\ntopics, and `isSubscribedToAllTopics` (true means `topics` is empty but\nevery event type is delivered)."
    operation: Literal["list_webhook_endpoints"] = Field(
        "list_webhook_endpoints", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(
        None,
        description="Maximum number of webhook endpoints to return (defaults to 100).",
        examples=[100],
        ge=1,
        le=100,
    )
    cursor: str | None = Field(
        None,
        description="Opaque cursor returned as `meta.nextCursor` by the previous page.",
        examples=["cursor_page_2"],
    )


class _WebhookInput(_Input):
    @model_validator(mode="after")
    def check_webhook(self):
        url = self.url
        if url is not None:
            from urllib.parse import urlsplit

            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Use an absolute HTTPS webhook delivery URL")
        topics = self.topics
        if topics is not None and (not topics or len(set(topics)) != len(topics)):
            raise ValueError("Select at least one distinct webhook topic")
        if url is None and topics is None:
            raise ValueError("Provide a webhook URL or replacement topics")
        return self


class CreateWebhookEndpointRequest(_WebhookInput):
    url: str = Field(
        ...,
        description="The absolute HTTPS URL webhook messages will be delivered to.",
        examples=["https://merchant.example.com/hooks/refersion"],
    )
    topics: list[str] = Field(
        ...,
        description="The event types this endpoint subscribes to. Must be a JSON array\n(not an object) containing at least one type and no duplicates.",
        examples=[["conversion.created", "payout.created"]],
    )


class RefersionCreateWebhookEndpointConfig(_Input):
    "Create Webhook Endpoint. Registers a webhook endpoint for the authenticated Refersion user —\nlets an account subscribe programmatically instead of only through the\nwebhook settings portal. Some users can only subscribe to a limited set\nof event types — anything else returns 422. Some users may receive a\n402 if their plan doesn't include webhook access. The user's webhook\nconfiguration is auto-provisioned on first call. The 201 response's id\nis also what `DELETE /v3/webhooks/endpoints/{endpointId}` accepts."
    operation: Literal["create_webhook_endpoint"] = Field(
        "create_webhook_endpoint", json_schema_extra={"ui:hidden": True}
    )
    body: CreateWebhookEndpointRequest = Field(
        ...,
        description="Documented JSON request body; omitted optional fields remain unchanged, explicit null clears nullable fields.",
    )


class UpdateWebhookEndpointRequest(_WebhookInput):
    url: str | None = Field(
        None,
        description="HTTPS delivery URL. Omit to leave unchanged.",
        examples=["https://merchant.example.com/hooks/refersion"],
    )
    topics: list[str] | None = Field(
        None,
        description="Event types to subscribe to (JSON array, min 1, no duplicates).\nREPLACES the current subscription; omit to leave unchanged.",
        examples=[["conversion.created", "payout.created"]],
    )


class RefersionUpdateWebhookEndpointConfig(_Input):
    "Update Webhook Endpoint. Updates the delivery URL, subscribed event types, or both, for one\nwebhook endpoint belonging to the authenticated Refersion user.\n`endpointId` is always resolved within the user's own webhook\nconfiguration, so another user's id returns the same 404 as an unknown\none.\n\nOmitted fields are left unchanged; `topics` REPLACES the subscription\nrather than merging into it. Some users can only use a limited set of\nevent types — anything else returns 422. Some users may receive a 402\nif their plan doesn't include webhook access. Like delete, this never\nauto-provisions a configuration — a user with none gets 404."
    operation: Literal["update_webhook_endpoint"] = Field(
        "update_webhook_endpoint", json_schema_extra={"ui:hidden": True}
    )
    endpoint_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r"^ep_[A-Za-z0-9]+$",
        description="The webhook endpoint id (`ep_…`) to update",
    )
    body: UpdateWebhookEndpointRequest = Field(
        ...,
        description="Documented JSON request body; omitted optional fields remain unchanged, explicit null clears nullable fields.",
    )


class RefersionDeleteWebhookEndpointConfig(_Input):
    "Delete Webhook Endpoint. Removes one webhook endpoint belonging to the authenticated Refersion\nuser. `endpointId` is always resolved within the user's own webhook\nconfiguration, so another user's id returns the same 404 as an unknown\none.\n\nDeleting the same endpoint twice returns 404 on the second call (not\nidempotent-204 by design), and this operation never auto-provisions a\nconfiguration — a user with none simply gets 404."
    operation: Literal["delete_webhook_endpoint"] = Field(
        "delete_webhook_endpoint", json_schema_extra={"ui:hidden": True}
    )
    endpoint_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r"^ep_[A-Za-z0-9]+$",
        description="The webhook endpoint id (`ep_…`) to delete",
    )


RefersionConfig = Annotated[
    Union[
        RefersionListAffiliatesConfig,
        RefersionGetAffiliateCountsConfig,
        RefersionGetAffiliateActivityConfig,
        RefersionUpdateAffiliateConfig,
        RefersionGetAffiliateLinkConfig,
        RefersionListAffiliateCustomFieldsConfig,
        RefersionUpdateAffiliateCustomFieldConfig,
        RefersionDeleteAffiliateCustomFieldConfig,
        RefersionListClicksConfig,
        RefersionCreateManualCreditConfig,
        RefersionCreditOrderConfig,
        RefersionGetConversionCountsConfig,
        RefersionListConversionsConfig,
        RefersionGetConversionConfig,
        RefersionUpdateConversionStatusConfig,
        RefersionListOffersConfig,
        RefersionUpdateOfferConfig,
        RefersionDuplicateOfferConfig,
        RefersionDeleteOfferConfig,
        RefersionSearchOrdersConfig,
        RefersionListWebhookEndpointsConfig,
        RefersionCreateWebhookEndpointConfig,
        RefersionUpdateWebhookEndpointConfig,
        RefersionDeleteWebhookEndpointConfig,
    ],
    Field(discriminator="operation"),
]


class RefersionFullConfig(NodeConfig[RefersionConfig, RefersionAccessTokenCredential]):
    pass


# Exactly one published operation per exposed action. No generic URL or method input.
ROUTES = {
    "list_affiliates": (
        "GET",
        "/affiliates",
        [
            ("status", "status[]"),
            ("search", "search"),
            ("has_pending_conversions", "hasPendingConversions"),
            ("last_conversion_days_ago", "lastConversionDaysAgo"),
            ("offer_ids", "offerIds[]"),
            ("page", "page"),
            ("limit", "limit"),
        ],
        False,
    ),
    "get_affiliate_counts": (
        "GET",
        "/affiliates/count",
        [
            ("search", "search"),
            ("has_pending_conversions", "hasPendingConversions"),
            ("last_conversion_days_ago", "lastConversionDaysAgo"),
            ("offer_ids", "offerIds[]"),
        ],
        False,
    ),
    "get_affiliate_activity": ("GET", "/affiliates/{id}/activity", [], False),
    "update_affiliate": ("PATCH", "/affiliates/{affiliateId}", [], True),
    "get_affiliate_link": (
        "GET",
        "/affiliates/{affiliateId}/link",
        [
            ("affiliate_id", "affiliateId"),
            ("test", "test"),
            ("url", "url"),
            ("marketing_asset_id", "marketingAssetId"),
            ("amazon_product_id", "amazonProductId"),
        ],
        False,
    ),
    "list_affiliate_custom_fields": (
        "GET",
        "/affiliates/{affiliateId}/custom-fields",
        [],
        False,
    ),
    "update_affiliate_custom_field": (
        "PATCH",
        "/affiliates/{affiliateId}/custom-fields/{customFieldId}",
        [],
        True,
    ),
    "delete_affiliate_custom_field": (
        "DELETE",
        "/affiliates/{affiliateId}/custom-fields/{customFieldId}",
        [],
        False,
    ),
    "list_clicks": (
        "GET",
        "/clicks",
        [
            ("created_at_min", "createdAtMin"),
            ("created_at_max", "createdAtMax"),
            ("affiliate_id", "affiliateId"),
            ("page", "page"),
            ("limit", "limit"),
        ],
        False,
    ),
    "create_manual_credit": ("POST", "/conversions/manual-credit", [], True),
    "credit_order": ("POST", "/conversions/credit-order-id", [], True),
    "get_conversion_counts": (
        "GET",
        "/conversions/count",
        [
            ("search", "search"),
            ("order_id", "orderId"),
            ("affiliate_ids", "affiliateIds[]"),
            ("offer_ids", "offerIds[]"),
            ("created_at_min", "createdAtMin"),
            ("created_at_max", "createdAtMax"),
        ],
        False,
    ),
    "list_conversions": (
        "GET",
        "/conversions",
        [
            ("status", "status"),
            ("page", "page"),
            ("limit", "limit"),
            ("sort_by", "sortBy"),
            ("sort_order", "sortOrder"),
            ("order_id", "orderId"),
            ("affiliate_ids", "affiliateIds[]"),
            ("created_at_min", "createdAtMin"),
            ("created_at_max", "createdAtMax"),
            ("offer_ids", "offerIds[]"),
            ("platform", "platform[]"),
        ],
        False,
    ),
    "get_conversion": ("GET", "/conversions/{id}", [], False),
    "update_conversion_status": ("PATCH", "/conversions/{id}", [], True),
    "list_offers": (
        "GET",
        "/offers",
        [
            ("type", "type[]"),
            ("search", "search"),
            ("page", "page"),
            ("limit", "limit"),
        ],
        False,
    ),
    "update_offer": ("PATCH", "/offers/{offerId}", [], True),
    "duplicate_offer": ("POST", "/offers/{offerId}/duplicate", [], False),
    "delete_offer": ("DELETE", "/offers/{offerId}", [], False),
    "search_orders": (
        "GET",
        "/orders",
        [("search", "search"), ("affiliate_id", "affiliateId")],
        False,
    ),
    "list_webhook_endpoints": (
        "GET",
        "/webhooks/endpoints",
        [("limit", "limit"), ("cursor", "cursor")],
        False,
    ),
    "create_webhook_endpoint": ("POST", "/webhooks/endpoints", [], True),
    "update_webhook_endpoint": ("PATCH", "/webhooks/endpoints/{endpointId}", [], True),
    "delete_webhook_endpoint": (
        "DELETE",
        "/webhooks/endpoints/{endpointId}",
        [],
        False,
    ),
}


# The API distinguishes clearing nullable fields from omitting other optional
# fields. UI empty values must not become invalid nulls on the wire.
_NULLABLE_BODY_FIELDS = frozenset(
    {
        "uniqueMerchantId",
        "parentAffiliateId",
        "company",
        "address1",
        "address2",
        "city",
        "state",
        "zip",
        "phone",
        "country",
        "notes",
    }
)


def _request_body(value):
    if isinstance(value, dict):
        return {
            key: _request_body(item)
            for key, item in value.items()
            if item is not None or key in _NULLABLE_BODY_FIELDS
        }
    if isinstance(value, list):
        return [_request_body(item) for item in value]
    return value


class RefersionNode(WorkflowNode):
    integration_type = "automation-refersion"
    connection_evidence = ConnectionEvidence(
        operation="list_offers", noun="Refersion offers", label_keys=("name", "id")
    )

    @classmethod
    def get_config_model(cls):
        return RefersionFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Refersion access token")
        config = self.config.config
        method, path, query_fields, has_body = ROUTES[config.operation]
        for name in ("id", "affiliateId", "customFieldId", "offerId", "endpointId"):
            if "{" + name + "}" in path:
                field = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
                path = path.replace(
                    "{" + name + "}", quote(str(getattr(config, field)), safe="")
                )
        params = []
        for field, wire in query_fields:
            value = getattr(config, field)
            if value is None:
                continue
            for item in value if isinstance(value, list) else [value]:
                params.append(
                    (
                        wire,
                        "true"
                        if item is True
                        else "false"
                        if item is False
                        else str(item),
                    )
                )
        body = (
            _request_body(config.body.model_dump(by_alias=True, exclude_unset=True))
            if has_body
            else None
        )
        if config.operation == "update_affiliate" and body["id"] != config.affiliate_id:
            raise ValueError("Body id must match the selected affiliate")
        if config.operation == "update_affiliate_custom_field" and (
            body["affiliateId"] != config.affiliate_id
            or body["customFieldId"] != config.custom_field_id
        ):
            raise ValueError(
                "Body affiliateId and customFieldId must match the selected resource"
            )
        async with guarded_async_client(
            timeout=30, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                params=params,
                headers={
                    "Authorization": "Bearer " + credential.access_token,
                    "Accept": "application/json",
                },
                **({"json": body} if has_body else {}),
            )
        if not 200 <= response.status_code < 300:
            # Preserve the provider's error for connection rejection and API diagnostics.
            # Never return response headers (or a possibly echoed credential).
            text = response.text[:2000].replace(credential.access_token, "[redacted]")
            return {
                "status": "error",
                "status_code": response.status_code,
                "error": text,
                "retry_after": response.headers.get("Retry-After"),
            }
        if response.status_code == 204 or not response.content:
            return {
                "status": "success",
                "data": None,
                "status_code": response.status_code,
            }
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Expected a Refersion JSON object or array")
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            return {
                "status": "error",
                "error": str(data).replace(credential.access_token, "[redacted]"),
            }
        # Preserve provider data and pagination without following links or inventing completion.
        return {"status": "success", "data": data, "status_code": response.status_code}
