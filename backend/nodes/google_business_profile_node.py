"""
Google Business Profile (GBP) workflow node — full API coverage.

Operations:
  Location:      list_business_profile_locations, get_location, update_location,
                 get_location_attributes, update_location_attributes
  Reviews:       list_location_reviews, get_review, reply_to_review, delete_review_reply
  Local Posts:   list_local_posts, get_local_post, create_local_post, update_local_post,
                 delete_local_post, get_local_post_insights
  Media:         list_media, get_media, create_media, delete_media, list_customer_media
  Analytics:     fetch_location_performance_metrics, fetch_location_search_keywords
  Place Actions: list_place_action_links, create_place_action_link,
                 update_place_action_link, delete_place_action_link
"""

import json
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple, Type, Union, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import load_paginated_options, require_credential_token
from nodes.scopes.google_cloud import GOOGLE_BUSINESS_PROFILE_SCOPES

logger = logging.getLogger(__name__)

GBP_BUSINESS_INFO_API = "https://mybusinessbusinessinformation.googleapis.com/v1"
GBP_ACCOUNT_MGMT_API = "https://mybusinessaccountmanagement.googleapis.com/v1"
GBP_PERFORMANCE_API = "https://businessprofileperformance.googleapis.com/v1"
GBP_MY_BUSINESS_API = "https://mybusiness.googleapis.com/v4"
GBP_PLACE_ACTIONS_API = "https://mybusinessplaceactions.googleapis.com/v1"


# ============================================================================
# Helpers
# ============================================================================


def _gbp_int(value: Any) -> int:
    """Parse int64 counts returned as JSON strings by the Performance API."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _norm_account(account_id: str) -> str:
    return account_id if account_id.startswith("accounts/") else f"accounts/{account_id}"


def _norm_location(location_id: str) -> str:
    return location_id if location_id.startswith("locations/") else f"locations/{location_id}"


def _account_location(account_id: str, location_id: str) -> str:
    """Build 'accounts/X/locations/Y' path."""
    return f"{_norm_account(account_id)}/{_norm_location(location_id)}"


def _parse_json_field(value: str, field_name: str) -> Any:
    if not value or not value.strip():
        return None
    try:
        return json.loads(value.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"'{field_name}' is not valid JSON: {exc}") from exc


# ============================================================================
# Credential
# ============================================================================


class GoogleBusinessProfileOAuthCredential(BaseModel):
    """OAuth credential for Google Business Profile access."""

    credential_type: Literal["google_business_profile_oauth"] = Field(
        "google_business_profile_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    email: str = Field(..., title="Google Account")
    # Stored from BYOO OAuth connect — used for token refresh
    client_id: Optional[str] = Field(None, title="Client ID", json_schema_extra={"ui:hidden": True})
    client_secret: Optional[str] = Field(None, title="Client Secret", json_schema_extra={"ui:hidden": True})

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "google",
        "x-oauth-scopes": ["https://www.googleapis.com/auth/business.manage"],
        "x-oauth-requires-custom-client": True,
        "x-oauth-redirect-uri": "/api/auth/google/callback",
        "x-oauth-validates-api-access": True,
        "x-credential-url": "https://console.cloud.google.com/apis/credentials",
        "x-credential-instructions": (
            "Google Business Profile API requires your own Google Cloud project. "
            "Create an OAuth 2.0 Web Application client at "
            "console.cloud.google.com → APIs & Services → Credentials, "
            "enable the My Business Account Management API and My Business Business Information API, "
            "then add this app's callback URL as an Authorised Redirect URI."
        ),
    })


# ============================================================================
# Shared field snippets (as dicts for DRY Field definitions)
# ============================================================================

_ACCOUNT_FIELD = dict(
    title="Account",
    description="Google Business Profile account",
    json_schema_extra={
        "x-dynamic-options": {
            "field_name": "account_id",
            "placeholder": "Select an account...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or enter account ID (accounts/xxxxx)",
        },
        "x-resource-type": "google_business_profile_account",
    },
)

_LOCATION_FIELD = dict(
    title="Location",
    description="Business location",
    json_schema_extra={
        "x-dynamic-options": {
            "field_name": "location_id",
            "placeholder": "Select a location...",
            "searchable": True,
            "depends_on": "account_id",
            "allow_custom": True,
            "custom_placeholder": "Or enter location resource name (locations/xxxxx)",
        },
        "x-resource-type": "google_business_profile_location",
    },
)

_LOCATION_FIELD_NO_DEP = dict(
    title="Location",
    description="Business location resource name (e.g. locations/xxxxx)",
    json_schema_extra={
        "x-dynamic-options": {
            "field_name": "location_id",
            "placeholder": "Select a location...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or enter location resource name",
        },
        "x-resource-type": "google_business_profile_location",
    },
)


# ============================================================================
# Config models — Location
# ============================================================================


class GBPListLocationsConfig(BaseModel):
    """List all locations/businesses for a Google Business Profile account."""

    operation: Literal["list_business_profile_locations"] = Field(
        "list_business_profile_locations",
        title="List Business Profile Locations",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_business_profile_locations",
            "x-category": "Location",
            "x-display-name": "List Business Profile Locations",
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)


class GBPGetLocationConfig(BaseModel):
    """Get full details for a single location."""

    operation: Literal["get_location"] = Field(
        "get_location",
        title="Get Location",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_location",
            "x-category": "Location",
            "x-display-name": "Get Location",
            "x-keywords": ["get location", "location details", "fetch location", "read location"],
        },
    )
    location_id: str = Field(..., **_LOCATION_FIELD_NO_DEP)


class GBPUpdateLocationConfig(BaseModel):
    """Update a location's core fields (name, phone, website, description)."""

    operation: Literal["update_location"] = Field(
        "update_location",
        title="Update Location",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_location",
            "x-category": "Location",
            "x-display-name": "Update Location",
            "x-keywords": ["update location", "edit location", "patch location", "modify business"],
        },
    )
    location_id: str = Field(..., **_LOCATION_FIELD_NO_DEP)
    title: str = Field(
        "",
        title="Business Name",
        description="New business name. Leave blank to keep current.",
        json_schema_extra={"ui:placeholder": "e.g. Acme Bakery Downtown"},
    )
    primary_phone: str = Field(
        "",
        title="Primary Phone",
        description="Phone number in E.164 format. Leave blank to keep current.",
        json_schema_extra={"ui:placeholder": "+14155551234"},
    )
    website_uri: str = Field(
        "",
        title="Website URL",
        description="Business website URL. Leave blank to keep current.",
        json_schema_extra={"ui:placeholder": "https://example.com"},
    )
    description: str = Field(
        "",
        title="Business Description",
        description="Short business description (max 750 chars). Leave blank to keep current.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GBPGetLocationAttributesConfig(BaseModel):
    """Get all attributes (amenities, accessibility, payments, etc.) for a location."""

    operation: Literal["get_location_attributes"] = Field(
        "get_location_attributes",
        title="Get Location Attributes",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_location_attributes",
            "x-category": "Location",
            "x-display-name": "Get Location Attributes",
            "x-keywords": ["attributes", "amenities", "accessibility", "location features"],
        },
    )
    location_id: str = Field(..., **_LOCATION_FIELD_NO_DEP)


class GBPUpdateLocationAttributesConfig(BaseModel):
    """Update location attributes (e.g. wheelchair access, Wi-Fi, payment methods)."""

    operation: Literal["update_location_attributes"] = Field(
        "update_location_attributes",
        title="Update Location Attributes",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_location_attributes",
            "x-category": "Location",
            "x-display-name": "Update Location Attributes",
            "x-keywords": ["update attributes", "set amenities", "edit features"],
        },
    )
    location_id: str = Field(..., **_LOCATION_FIELD_NO_DEP)
    attributes: str = Field(
        ...,
        title="Attributes (JSON)",
        description=(
            'JSON array of attribute objects. Example: '
            '[{"name":"attributes/has_wheelchair_accessible_entrance","valueType":"BOOL","values":[true]}]'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Config models — Reviews
# ============================================================================


class GBPListReviewsConfig(BaseModel):
    """List reviews for a specific location."""

    operation: Literal["list_location_reviews"] = Field(
        "list_location_reviews",
        title="List Location Reviews",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_location_reviews",
            "x-category": "Reviews",
            "x-display-name": "List Location Reviews",
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    page_size: str = Field("50", title="Page Size", description="Reviews per page (max 50)")
    order_by: str = Field(
        "update_time desc",
        title="Sort Order",
        json_schema_extra={
            "enum": ["update_time desc", "update_time asc", "rating desc", "rating asc"],
            "enumNames": ["Newest First", "Oldest First", "Highest Rating", "Lowest Rating"],
            "x-enum-searchable": True,
        },
    )


class GBPGetReviewConfig(BaseModel):
    """Get a single review by its resource name."""

    operation: Literal["get_review"] = Field(
        "get_review",
        title="Get Review",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_review",
            "x-category": "Reviews",
            "x-display-name": "Get Review",
            "x-keywords": ["get review", "fetch review", "single review"],
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    review_id: str = Field(
        ...,
        title="Review ID",
        description="Review resource name from List Reviews, e.g. accounts/X/locations/Y/reviews/Z",
        json_schema_extra={"ui:placeholder": "accounts/.../locations/.../reviews/..."},
    )


class GBPReplyToReviewConfig(BaseModel):
    """Create or update the owner reply to a review."""

    operation: Literal["reply_to_review"] = Field(
        "reply_to_review",
        title="Reply to Review",
        json_schema_extra={
            "ui:hidden": True,
            "const": "reply_to_review",
            "x-category": "Reviews",
            "x-display-name": "Reply to Review",
            "x-keywords": ["reply review", "respond review", "review response", "reply to customer"],
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    review_id: str = Field(
        ...,
        title="Review ID",
        description="Review resource name, e.g. accounts/X/locations/Y/reviews/Z",
        json_schema_extra={"ui:placeholder": "accounts/.../locations/.../reviews/..."},
    )
    reply_text: str = Field(
        ...,
        title="Reply Text",
        description="Owner reply text (max 4096 characters)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GBPDeleteReviewReplyConfig(BaseModel):
    """Delete the owner reply from a review."""

    operation: Literal["delete_review_reply"] = Field(
        "delete_review_reply",
        title="Delete Review Reply",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_review_reply",
            "x-category": "Reviews",
            "x-display-name": "Delete Review Reply",
            "x-keywords": ["delete reply", "remove reply", "delete review response"],
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    review_id: str = Field(
        ...,
        title="Review ID",
        description="Review resource name, e.g. accounts/X/locations/Y/reviews/Z",
        json_schema_extra={"ui:placeholder": "accounts/.../locations/.../reviews/..."},
    )


# ============================================================================
# Config models — Local Posts
# ============================================================================


class GBPListLocalPostsConfig(BaseModel):
    """List local posts for a location."""

    operation: Literal["list_local_posts"] = Field(
        "list_local_posts",
        title="List Local Posts",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_local_posts",
            "x-category": "Local Posts",
            "x-display-name": "List Local Posts",
            "x-keywords": ["list posts", "list local posts", "google posts", "marketing posts"],
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    page_size: str = Field("20", title="Page Size", description="Posts per page (max 100)")


class GBPGetLocalPostConfig(BaseModel):
    """Get a single local post."""

    operation: Literal["get_local_post"] = Field(
        "get_local_post",
        title="Get Local Post",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_local_post",
            "x-category": "Local Posts",
            "x-display-name": "Get Local Post",
        },
    )
    local_post_name: str = Field(
        ...,
        title="Local Post Name",
        description="Full resource name from List Local Posts, e.g. accounts/X/locations/Y/localPosts/Z",
        json_schema_extra={"ui:placeholder": "accounts/.../locations/.../localPosts/..."},
    )


class GBPCreateLocalPostConfig(BaseModel):
    """Create a new local post (Standard, Event, Offer, or Alert)."""

    operation: Literal["create_local_post"] = Field(
        "create_local_post",
        title="Create Local Post",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_local_post",
            "x-category": "Local Posts",
            "x-display-name": "Create Local Post",
            "x-keywords": ["create post", "publish post", "new post", "google post", "offer", "event post"],
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    topic_type: str = Field(
        "STANDARD",
        title="Post Type",
        json_schema_extra={
            "enum": ["STANDARD", "EVENT", "OFFER", "ALERT"],
            "enumNames": ["Standard", "Event", "Offer", "Alert"],
            "x-enum-searchable": True,
        },
    )
    summary: str = Field(
        ...,
        title="Post Text",
        description="Main content of the post (max 1500 characters for Standard/Alert, 500 for Event/Offer)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    language_code: str = Field(
        "en-US",
        title="Language Code",
        description="BCP-47 language code for the post content",
        json_schema_extra={"ui:placeholder": "en-US"},
    )
    call_to_action_type: str = Field(
        "",
        title="Call-to-Action Button",
        description="CTA button shown on the post. Leave blank for no button.",
        json_schema_extra={
            "enum": ["", "BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "CALL"],
            "enumNames": ["None", "Book", "Order Online", "Buy", "Learn More", "Sign Up", "Call Now"],
            "x-enum-searchable": True,
        },
    )
    call_to_action_url: str = Field(
        "",
        title="Call-to-Action URL",
        description="URL for the CTA button (required if CTA type is set)",
        json_schema_extra={"ui:placeholder": "https://example.com/book"},
    )
    media_source_url: str = Field(
        "",
        title="Photo/Video URL",
        description="Public URL of a photo or video to attach to the post",
        json_schema_extra={"ui:placeholder": "https://example.com/photo.jpg"},
    )
    # EVENT fields
    event_title: str = Field(
        "",
        title="Event Title",
        description="Required for EVENT posts",
        json_schema_extra={"ui:placeholder": "Grand Opening"},
    )
    event_start: str = Field(
        "",
        title="Event Start",
        description="Event start date in YYYY-MM-DD format",
        json_schema_extra={"ui:placeholder": "2026-08-01"},
    )
    event_end: str = Field(
        "",
        title="Event End",
        description="Event end date in YYYY-MM-DD format",
        json_schema_extra={"ui:placeholder": "2026-08-03"},
    )
    # OFFER fields
    offer_coupon_code: str = Field(
        "",
        title="Coupon Code",
        description="For OFFER posts: redemption coupon code",
        json_schema_extra={"ui:placeholder": "SAVE20"},
    )
    offer_redeem_url: str = Field(
        "",
        title="Redeem URL",
        description="For OFFER posts: URL to redeem the offer",
        json_schema_extra={"ui:placeholder": "https://example.com/offer"},
    )
    offer_terms: str = Field(
        "",
        title="Offer Terms",
        description="For OFFER posts: terms and conditions",
        json_schema_extra={"ui:widget": "textarea"},
    )


class GBPUpdateLocalPostConfig(BaseModel):
    """Update an existing local post."""

    operation: Literal["update_local_post"] = Field(
        "update_local_post",
        title="Update Local Post",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_local_post",
            "x-category": "Local Posts",
            "x-display-name": "Update Local Post",
        },
    )
    local_post_name: str = Field(
        ...,
        title="Local Post Name",
        description="Full resource name, e.g. accounts/X/locations/Y/localPosts/Z",
    )
    summary: str = Field(
        "",
        title="Post Text",
        description="Updated post content. Leave blank to keep current.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    call_to_action_type: str = Field(
        "",
        title="Call-to-Action Button",
        json_schema_extra={
            "enum": ["", "BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "CALL"],
            "enumNames": ["No change", "Book", "Order Online", "Buy", "Learn More", "Sign Up", "Call Now"],
            "x-enum-searchable": True,
        },
    )
    call_to_action_url: str = Field(
        "",
        title="Call-to-Action URL",
        json_schema_extra={"ui:placeholder": "https://example.com"},
    )
    media_source_url: str = Field(
        "",
        title="Photo/Video URL",
        description="Replace post media with this public URL. Leave blank to keep current.",
    )


class GBPDeleteLocalPostConfig(BaseModel):
    """Delete a local post."""

    operation: Literal["delete_local_post"] = Field(
        "delete_local_post",
        title="Delete Local Post",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_local_post",
            "x-category": "Local Posts",
            "x-display-name": "Delete Local Post",
        },
    )
    local_post_name: str = Field(
        ...,
        title="Local Post Name",
        description="Full resource name, e.g. accounts/X/locations/Y/localPosts/Z",
    )


class GBPGetLocalPostInsightsConfig(BaseModel):
    """Get view and click insights for one or more local posts."""

    operation: Literal["get_local_post_insights"] = Field(
        "get_local_post_insights",
        title="Get Local Post Insights",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_local_post_insights",
            "x-category": "Local Posts",
            "x-display-name": "Get Local Post Insights",
            "x-keywords": ["post insights", "post performance", "post views", "post clicks"],
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    local_post_names: str = Field(
        ...,
        title="Local Post Names",
        description=(
            "Comma-separated full post resource names, "
            "e.g. accounts/X/locations/Y/localPosts/Z"
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    start_date: str = Field(
        "",
        title="Start Date",
        description="YYYY-MM-DD. Defaults to 30 days ago.",
        json_schema_extra={"ui:placeholder": "2026-06-01"},
    )
    end_date: str = Field(
        "",
        title="End Date",
        description="YYYY-MM-DD. Defaults to today.",
        json_schema_extra={"ui:placeholder": "2026-07-01"},
    )


# ============================================================================
# Config models — Media
# ============================================================================


class GBPListMediaConfig(BaseModel):
    """List media items (photos/videos) for a location."""

    operation: Literal["list_media"] = Field(
        "list_media",
        title="List Media",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_media",
            "x-category": "Media",
            "x-display-name": "List Media",
            "x-keywords": ["list photos", "list media", "list images", "business photos"],
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    page_size: str = Field("100", title="Page Size", description="Items per page (max 100)")


class GBPGetMediaConfig(BaseModel):
    """Get a single media item."""

    operation: Literal["get_media"] = Field(
        "get_media",
        title="Get Media Item",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_media",
            "x-category": "Media",
            "x-display-name": "Get Media Item",
        },
    )
    media_item_name: str = Field(
        ...,
        title="Media Item Name",
        description="Full resource name from List Media, e.g. accounts/X/locations/Y/media/Z",
        json_schema_extra={"ui:placeholder": "accounts/.../locations/.../media/..."},
    )


class GBPCreateMediaConfig(BaseModel):
    """Upload a photo or video to a location via public URL."""

    operation: Literal["create_media"] = Field(
        "create_media",
        title="Upload Media",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_media",
            "x-category": "Media",
            "x-display-name": "Upload Media",
            "x-keywords": ["upload photo", "add photo", "upload image", "add media", "photo upload"],
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    source_url: str = Field(
        ...,
        title="Source URL",
        description="Publicly accessible URL of the photo or video to upload",
        json_schema_extra={"ui:placeholder": "https://example.com/photo.jpg"},
    )
    media_format: str = Field(
        "PHOTO",
        title="Media Format",
        json_schema_extra={
            "enum": ["PHOTO", "VIDEO"],
            "enumNames": ["Photo", "Video"],
            "x-enum-searchable": True,
        },
    )
    category: str = Field(
        "ADDITIONAL",
        title="Photo Category",
        description="Where this photo will appear on the business listing",
        json_schema_extra={
            "enum": [
                "COVER", "PROFILE", "LOGO", "EXTERIOR", "INTERIOR",
                "PRODUCT", "AT_WORK", "FOOD_AND_DRINK", "MENU",
                "COMMON_AREA", "ROOMS", "TEAMS", "ADDITIONAL",
            ],
            "enumNames": [
                "Cover", "Profile", "Logo", "Exterior", "Interior",
                "Product", "At Work", "Food & Drink", "Menu",
                "Common Area", "Rooms", "Team", "Additional",
            ],
            "x-enum-searchable": True,
        },
    )


class GBPDeleteMediaConfig(BaseModel):
    """Delete a media item from a location."""

    operation: Literal["delete_media"] = Field(
        "delete_media",
        title="Delete Media Item",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_media",
            "x-category": "Media",
            "x-display-name": "Delete Media Item",
            "x-keywords": ["delete photo", "remove photo", "delete image"],
        },
    )
    media_item_name: str = Field(
        ...,
        title="Media Item Name",
        description="Full resource name, e.g. accounts/X/locations/Y/media/Z",
    )


class GBPListCustomerMediaConfig(BaseModel):
    """List customer-contributed photos for a location."""

    operation: Literal["list_customer_media"] = Field(
        "list_customer_media",
        title="List Customer Media",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_customer_media",
            "x-category": "Media",
            "x-display-name": "List Customer Media",
            "x-keywords": ["customer photos", "user photos", "customer images", "customer media"],
        },
    )
    account_id: str = Field(..., **_ACCOUNT_FIELD)
    location_id: str = Field(..., **_LOCATION_FIELD)
    page_size: str = Field("100", title="Page Size", description="Items per page (max 100)")


# ============================================================================
# Config models — Analytics
# ============================================================================


class GBPGetPerformanceConfig(BaseModel):
    """Get daily performance metrics for a location over a date range."""

    operation: Literal["fetch_location_performance_metrics"] = Field(
        "fetch_location_performance_metrics",
        title="Fetch Location Performance Metrics",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_location_performance_metrics",
            "x-category": "Analytics",
            "x-display-name": "Fetch Location Performance Metrics",
        },
    )
    location_id: str = Field(..., **_LOCATION_FIELD_NO_DEP)
    start_date: str = Field(
        "", title="Start Date",
        description="YYYY-MM-DD (defaults to 30 days ago)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    end_date: str = Field(
        "", title="End Date",
        description="YYYY-MM-DD (defaults to today)",
        json_schema_extra={"placeholder": "YYYY-MM-DD (optional)"},
    )
    daily_metrics: str = Field(
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS,BUSINESS_IMPRESSIONS_MOBILE_MAPS,"
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH,BUSINESS_IMPRESSIONS_MOBILE_SEARCH,"
        "BUSINESS_DIRECTION_REQUESTS,CALL_CLICKS,WEBSITE_CLICKS",
        title="Metrics",
        description="Comma-separated metrics to fetch",
        json_schema_extra={
            "ui:help": (
                "Available: BUSINESS_IMPRESSIONS_DESKTOP_MAPS, BUSINESS_IMPRESSIONS_MOBILE_MAPS, "
                "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH, BUSINESS_IMPRESSIONS_MOBILE_SEARCH, "
                "BUSINESS_DIRECTION_REQUESTS, CALL_CLICKS, WEBSITE_CLICKS, "
                "BUSINESS_BOOKINGS, BUSINESS_FOOD_ORDERS, BUSINESS_CONVERSATIONS"
            ),
        },
    )


class GBPGetSearchKeywordsConfig(BaseModel):
    """Get search keywords that led customers to discover the business profile."""

    operation: Literal["fetch_location_search_keywords"] = Field(
        "fetch_location_search_keywords",
        title="Fetch Location Search Keywords",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_location_search_keywords",
            "x-category": "Analytics",
            "x-display-name": "Fetch Location Search Keywords",
        },
    )
    location_id: str = Field(..., **_LOCATION_FIELD_NO_DEP)
    year: str = Field("", title="Year", description="YYYY. Defaults to current year.",
                      json_schema_extra={"placeholder": "2026 (optional)"})
    month: str = Field("", title="Month", description="1-12. Defaults to previous month.",
                       json_schema_extra={"placeholder": "1-12 (optional)"})


# ============================================================================
# Config models — Place Action Links
# ============================================================================


class GBPListPlaceActionLinksConfig(BaseModel):
    """List booking/reservation/ordering links for a location."""

    operation: Literal["list_place_action_links"] = Field(
        "list_place_action_links",
        title="List Place Action Links",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_place_action_links",
            "x-category": "Place Actions",
            "x-display-name": "List Place Action Links",
            "x-keywords": ["booking links", "reservation links", "action links", "place actions"],
        },
    )
    location_id: str = Field(..., **_LOCATION_FIELD_NO_DEP)
    filter: str = Field(
        "",
        title="Filter",
        description="Optional filter, e.g. place_action_type=APPOINTMENT",
        json_schema_extra={"ui:placeholder": "place_action_type=APPOINTMENT"},
    )


_PLACE_ACTION_TYPES = [
    "APPOINTMENT", "ONLINE_APPOINTMENT", "DINING_RESERVATION",
    "FOOD_ORDERING_DELIVERY", "FOOD_ORDERING_TAKEOUT", "FOOD_ORDERING",
    "SHOPPING_DELIVERY", "SHOPPING_CURBSIDE", "SHOPPING_IN_STORE", "ORDER_ONLINE",
]


class GBPCreatePlaceActionLinkConfig(BaseModel):
    """Create a new booking/reservation/ordering link for a location."""

    operation: Literal["create_place_action_link"] = Field(
        "create_place_action_link",
        title="Create Place Action Link",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_place_action_link",
            "x-category": "Place Actions",
            "x-display-name": "Create Place Action Link",
            "x-keywords": ["create booking link", "add reservation link", "create action link"],
        },
    )
    location_id: str = Field(..., **_LOCATION_FIELD_NO_DEP)
    uri: str = Field(
        ...,
        title="URL",
        description="URL for the action (booking page, ordering page, etc.)",
        json_schema_extra={"ui:placeholder": "https://book.example.com"},
    )
    place_action_type: str = Field(
        "APPOINTMENT",
        title="Action Type",
        json_schema_extra={
            "enum": _PLACE_ACTION_TYPES,
            "enumNames": [
                "Appointment", "Online Appointment", "Dining Reservation",
                "Food Delivery", "Food Takeout", "Food Ordering",
                "Shopping Delivery", "Shopping Curbside", "Shopping In-Store", "Order Online",
            ],
            "x-enum-searchable": True,
        },
    )
    is_preferred: str = Field(
        "true",
        title="Set as Preferred",
        description="Mark this as the preferred link for this action type",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GBPUpdatePlaceActionLinkConfig(BaseModel):
    """Update an existing place action link."""

    operation: Literal["update_place_action_link"] = Field(
        "update_place_action_link",
        title="Update Place Action Link",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_place_action_link",
            "x-category": "Place Actions",
            "x-display-name": "Update Place Action Link",
        },
    )
    place_action_link_name: str = Field(
        ...,
        title="Place Action Link Name",
        description="Full resource name from List Place Action Links",
        json_schema_extra={"ui:placeholder": "locations/.../placeActionLinks/..."},
    )
    uri: str = Field(
        "",
        title="New URL",
        description="Updated URL. Leave blank to keep current.",
    )
    is_preferred: str = Field(
        "",
        title="Set as Preferred",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GBPDeletePlaceActionLinkConfig(BaseModel):
    """Delete a place action link."""

    operation: Literal["delete_place_action_link"] = Field(
        "delete_place_action_link",
        title="Delete Place Action Link",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_place_action_link",
            "x-category": "Place Actions",
            "x-display-name": "Delete Place Action Link",
        },
    )
    place_action_link_name: str = Field(
        ...,
        title="Place Action Link Name",
        description="Full resource name, e.g. locations/X/placeActionLinks/Y",
    )


# ============================================================================
# Discriminated union + NodeConfig
# ============================================================================

GoogleBusinessProfileConfig = Annotated[
    Union[
        GBPListLocationsConfig,
        GBPGetLocationConfig,
        GBPUpdateLocationConfig,
        GBPGetLocationAttributesConfig,
        GBPUpdateLocationAttributesConfig,
        GBPListReviewsConfig,
        GBPGetReviewConfig,
        GBPReplyToReviewConfig,
        GBPDeleteReviewReplyConfig,
        GBPListLocalPostsConfig,
        GBPGetLocalPostConfig,
        GBPCreateLocalPostConfig,
        GBPUpdateLocalPostConfig,
        GBPDeleteLocalPostConfig,
        GBPGetLocalPostInsightsConfig,
        GBPListMediaConfig,
        GBPGetMediaConfig,
        GBPCreateMediaConfig,
        GBPDeleteMediaConfig,
        GBPListCustomerMediaConfig,
        GBPGetPerformanceConfig,
        GBPGetSearchKeywordsConfig,
        GBPListPlaceActionLinksConfig,
        GBPCreatePlaceActionLinkConfig,
        GBPUpdatePlaceActionLinkConfig,
        GBPDeletePlaceActionLinkConfig,
    ],
    Discriminator("operation"),
]


class GoogleBusinessProfileNodeConfig(
    NodeConfig[GoogleBusinessProfileConfig, GoogleBusinessProfileOAuthCredential]
):
    pass


# ============================================================================
# Node
# ============================================================================


class GoogleBusinessProfileNode(WorkflowNode):
    edit_examples = [
        "List all business locations and their performance metrics",
        "Reply to all unanswered 1-star reviews",
        "Create a weekly special offer post on Google",
        "Upload exterior photos to the business listing",
        "Update the business phone number and website",
        "Get the top 20 search keywords that drove impressions last month",
        "Add a booking link to the location",
    ]

    scope_registry = GOOGLE_BUSINESS_PROFILE_SCOPES
    connection_evidence = ConnectionEvidence(
        field="account_id",
        noun="business accounts",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        return GoogleBusinessProfileNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name == "account_id":
            return await cls._list_accounts(credential_data, page_token, search=search)
        if field_name == "location_id":
            account_id = (context or {}).get("account_id")
            return await cls._list_locations_options(credential_data, account_id, page_token, search=search)
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _get_access_token(cls, credential_data: Dict[str, Any]) -> str:
        return require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google Business Profile account to load options",
        )

    @classmethod
    async def _list_accounts(
        cls, credential_data: Dict[str, Any], page_token: Optional[str] = None, search: Optional[str] = None
    ) -> Dict[str, Any]:
        access_token = await cls._get_access_token(credential_data)

        async def fetch_page(cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            params: Dict[str, Any] = {"pageSize": 20}
            if cursor:
                params["pageToken"] = cursor
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GBP_ACCOUNT_MGMT_API}/accounts",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            options = [
                {"label": a.get("accountName", a.get("name", "")), "value": a.get("name", "")}
                for a in (data.get("accounts") or [])
            ]
            return options, data.get("nextPageToken")

        return await load_paginated_options(
            fetch_page, page_token=page_token, search=search, log_label="GoogleBusinessProfileNode._list_accounts"
        )

    @classmethod
    async def _list_locations_options(
        cls,
        credential_data: Dict[str, Any],
        account_id: Optional[str],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not account_id:
            return {"options": [], "next_page_token": None}
        access_token = await cls._get_access_token(credential_data)
        params: Dict[str, Any] = {"pageSize": 100, "readMask": "name,title,storefrontAddress"}
        if page_token:
            params["pageToken"] = page_token
        if search:
            params["filter"] = search
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GBP_BUSINESS_INFO_API}/{account_id}/locations",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        options = []
        for location in data.get("locations", []):
            loc_name = location.get("name", "")
            title = location.get("title", loc_name)
            address = location.get("storefrontAddress", {})
            locality = address.get("locality", "")
            region = address.get("administrativeArea", "")
            suffix = f" — {locality}, {region}" if locality else ""
            options.append({"label": f"{title}{suffix}", "value": loc_name})
        return {"options": options, "next_page_token": data.get("nextPageToken")}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token
        client_id = credential_data.get("client_id")
        client_secret = credential_data.get("client_secret")
        async def _refresh(token):
            return await refresh_access_token(token, custom_client_id=client_id, custom_client_secret=client_secret)
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=_refresh, provider="google",
        )

    @classmethod
    async def validate_credential_access(cls, credential_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check if the GCP project has GBP API quota enabled."""
        from nodes.oauth.google_oauth import refresh_access_token
        try:
            client_id = credential_data.get("client_id")
            client_secret = credential_data.get("client_secret")
            tokens = await refresh_access_token(
                credential_data["refresh_token"],
                custom_client_id=client_id,
                custom_client_secret=client_secret,
            )
            access_token = tokens.access_token
        except Exception as e:
            return {"valid": False, "error": f"Token refresh failed: {e}"}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GBP_ACCOUNT_MGMT_API}/accounts",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=15,
                )
            if resp.status_code == 429:
                # quota_limit_value: "0" means API not approved
                return {
                    "valid": False,
                    "error": (
                        "Your Google Cloud project doesn't have access to the Google Business Profile API. "
                        "You need to apply for API access — Google approves these requests for verified businesses."
                    ),
                    "help_url": "https://developers.google.com/my-business/content/prereqs",
                }
            if resp.status_code == 403:
                body = resp.json()
                msg = (body.get("error") or {}).get("message", "")
                return {
                    "valid": False,
                    "error": f"Google Business Profile API is not enabled in your project: {msg}",
                    "help_url": "https://console.cloud.google.com/apis/library/mybusinessaccountmanagement.googleapis.com",
                }
            # 200 or any other 2xx = access OK; 404 = API reachable but no accounts (also fine)
            return {"valid": True}
        except Exception as e:
            return {"valid": False, "error": f"Could not validate API access: {e}"}

    async def _ensure_fresh_token(self, credentials) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token
        cred_dict = credentials.model_dump()
        client_id = cred_dict.get("client_id")
        client_secret = cred_dict.get("client_secret")
        async def _refresh(token):
            return await refresh_access_token(token, custom_client_id=client_id, custom_client_secret=client_secret)
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=_refresh,
            provider="google",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        node_config = self.config
        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            return {"error": "No Google Business Profile credentials configured"}

        access_token = await self._ensure_fresh_token(credentials)
        headers = {"Authorization": f"Bearer {access_token}"}

        op = config.operation
        if op == "list_business_profile_locations":
            return await self._list_locations(config, headers)
        if op == "get_location":
            return await self._get_location(config, headers)
        if op == "update_location":
            return await self._update_location(config, headers)
        if op == "get_location_attributes":
            return await self._get_location_attributes(config, headers)
        if op == "update_location_attributes":
            return await self._update_location_attributes(config, headers)
        if op == "list_location_reviews":
            return await self._list_reviews(config, headers)
        if op == "get_review":
            return await self._get_review(config, headers)
        if op == "reply_to_review":
            return await self._reply_to_review(config, headers)
        if op == "delete_review_reply":
            return await self._delete_review_reply(config, headers)
        if op == "list_local_posts":
            return await self._list_local_posts(config, headers)
        if op == "get_local_post":
            return await self._get_local_post(config, headers)
        if op == "create_local_post":
            return await self._create_local_post(config, headers)
        if op == "update_local_post":
            return await self._update_local_post(config, headers)
        if op == "delete_local_post":
            return await self._delete_local_post(config, headers)
        if op == "get_local_post_insights":
            return await self._get_local_post_insights(config, headers)
        if op == "list_media":
            return await self._list_media(config, headers)
        if op == "get_media":
            return await self._get_media(config, headers)
        if op == "create_media":
            return await self._create_media(config, headers)
        if op == "delete_media":
            return await self._delete_media(config, headers)
        if op == "list_customer_media":
            return await self._list_customer_media(config, headers)
        if op == "fetch_location_performance_metrics":
            return await self._get_performance(config, headers)
        if op == "fetch_location_search_keywords":
            return await self._get_search_keywords(config, headers)
        if op == "list_place_action_links":
            return await self._list_place_action_links(config, headers)
        if op == "create_place_action_link":
            return await self._create_place_action_link(config, headers)
        if op == "update_place_action_link":
            return await self._update_place_action_link(config, headers)
        if op == "delete_place_action_link":
            return await self._delete_place_action_link(config, headers)
        return {"error": f"Unknown operation: {op}"}

    # -------------------------------------------------------------------------
    # Location
    # -------------------------------------------------------------------------

    async def _list_locations(self, config: GBPListLocationsConfig, headers: Dict) -> Dict:
        locations = []
        page_token = None
        async with httpx.AsyncClient() as client:
            while True:
                params: Dict[str, Any] = {
                    "pageSize": 100,
                    "readMask": "name,title,storefrontAddress,websiteUri,phoneNumbers,regularHours,metadata",
                }
                if page_token:
                    params["pageToken"] = page_token
                resp = await client.get(
                    f"{GBP_BUSINESS_INFO_API}/{config.account_id}/locations",
                    headers=headers, params=params, timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                for loc in data.get("locations", []):
                    address = loc.get("storefrontAddress", {})
                    locations.append({
                        "location_id": loc.get("name", ""),
                        "title": loc.get("title", ""),
                        "address": ", ".join(filter(None, [
                            " ".join(address.get("addressLines", [])),
                            address.get("locality", ""),
                            address.get("administrativeArea", ""),
                            address.get("postalCode", ""),
                        ])),
                        "website": loc.get("websiteUri", ""),
                        "phone": (loc.get("phoneNumbers") or {}).get("primaryPhone", ""),
                    })
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return {"locations": locations, "count": len(locations)}

    async def _get_location(self, config: GBPGetLocationConfig, headers: Dict) -> Dict:
        loc = _norm_location(config.location_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GBP_BUSINESS_INFO_API}/{loc}",
                headers=headers,
                params={"readMask": "name,title,storefrontAddress,websiteUri,phoneNumbers,regularHours,specialHours,profile,categories,metadata"},
                timeout=30,
            )
            resp.raise_for_status()
        return resp.json()

    async def _update_location(self, config: GBPUpdateLocationConfig, headers: Dict) -> Dict:
        loc = _norm_location(config.location_id)
        body: Dict[str, Any] = {}
        mask_fields: List[str] = []

        if config.title:
            body["title"] = config.title
            mask_fields.append("title")
        if config.website_uri:
            body["websiteUri"] = config.website_uri
            mask_fields.append("websiteUri")
        if config.primary_phone:
            body["phoneNumbers"] = {"primaryPhone": config.primary_phone}
            mask_fields.append("phoneNumbers.primaryPhone")
        if config.description:
            body.setdefault("profile", {})["description"] = config.description
            mask_fields.append("profile.description")

        if not mask_fields:
            raise ValueError("At least one field (name, phone, website, description) must be provided")

        update_mask = ",".join(mask_fields)
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{GBP_BUSINESS_INFO_API}/{loc}",
                headers={**headers, "Content-Type": "application/json"},
                params={"updateMask": update_mask},
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
        return {"status": "updated", "location": resp.json(), "updated_fields": mask_fields}

    async def _get_location_attributes(self, config: GBPGetLocationAttributesConfig, headers: Dict) -> Dict:
        loc = _norm_location(config.location_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GBP_BUSINESS_INFO_API}/{loc}/attributes",
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
        return resp.json()

    async def _update_location_attributes(self, config: GBPUpdateLocationAttributesConfig, headers: Dict) -> Dict:
        loc = _norm_location(config.location_id)
        attributes = _parse_json_field(config.attributes, "attributes")
        body = {"name": f"{loc}/attributes", "attributes": attributes}
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{GBP_BUSINESS_INFO_API}/{loc}/attributes",
                headers={**headers, "Content-Type": "application/json"},
                params={"updateMask": "attributes"},
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
        return {"status": "updated", "result": resp.json()}

    # -------------------------------------------------------------------------
    # Reviews
    # -------------------------------------------------------------------------

    def _review_base_url(self, account_id: str, location_id: str) -> str:
        return f"{GBP_MY_BUSINESS_API}/{_account_location(account_id, location_id)}/reviews"

    async def _list_reviews(self, config: GBPListReviewsConfig, headers: Dict) -> Dict:
        params: Dict[str, Any] = {
            "pageSize": int(config.page_size) if config.page_size else 50,
            "orderBy": config.order_by,
        }
        url = self._review_base_url(config.account_id, config.location_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        reviews = []
        for review in data.get("reviews", []):
            reviewer = review.get("reviewer", {})
            reviews.append({
                "review_id": review.get("name", ""),
                "reviewer_name": reviewer.get("displayName", "Anonymous"),
                "star_rating": review.get("starRating", ""),
                "comment": review.get("comment", ""),
                "create_time": review.get("createTime", ""),
                "update_time": review.get("updateTime", ""),
                "reply": (review.get("reviewReply") or {}).get("comment", ""),
            })
        return {
            "reviews": reviews,
            "count": len(reviews),
            "total_review_count": data.get("totalReviewCount", 0),
            "average_rating": data.get("averageRating", 0),
        }

    async def _get_review(self, config: GBPGetReviewConfig, headers: Dict) -> Dict:
        # Use the full review resource name if provided, otherwise build it
        review_name = config.review_id.strip()
        if review_name.startswith("accounts/"):
            url = f"{GBP_MY_BUSINESS_API}/{review_name}"
        else:
            url = f"{self._review_base_url(config.account_id, config.location_id)}/{review_name}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
        return resp.json()

    async def _reply_to_review(self, config: GBPReplyToReviewConfig, headers: Dict) -> Dict:
        review_name = config.review_id.strip()
        if review_name.startswith("accounts/"):
            base = f"{GBP_MY_BUSINESS_API}/{review_name}"
        else:
            base = f"{self._review_base_url(config.account_id, config.location_id)}/{review_name}"
        url = f"{base}/reply"
        body = {"comment": config.reply_text}
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                url,
                headers={**headers, "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
        return {"status": "replied", "result": resp.json()}

    async def _delete_review_reply(self, config: GBPDeleteReviewReplyConfig, headers: Dict) -> Dict:
        review_name = config.review_id.strip()
        if review_name.startswith("accounts/"):
            base = f"{GBP_MY_BUSINESS_API}/{review_name}"
        else:
            base = f"{self._review_base_url(config.account_id, config.location_id)}/{review_name}"
        url = f"{base}/reply"
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=headers, timeout=30)
            resp.raise_for_status()
        return {"status": "deleted", "review_id": config.review_id}

    # -------------------------------------------------------------------------
    # Local Posts
    # -------------------------------------------------------------------------

    def _posts_base_url(self, account_id: str, location_id: str) -> str:
        return f"{GBP_MY_BUSINESS_API}/{_account_location(account_id, location_id)}/localPosts"

    async def _list_local_posts(self, config: GBPListLocalPostsConfig, headers: Dict) -> Dict:
        params: Dict[str, Any] = {"pageSize": int(config.page_size) if config.page_size else 20}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self._posts_base_url(config.account_id, config.location_id),
                headers=headers, params=params, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        posts = data.get("localPosts", [])
        return {"posts": posts, "count": len(posts), "next_page_token": data.get("nextPageToken")}

    async def _get_local_post(self, config: GBPGetLocalPostConfig, headers: Dict) -> Dict:
        url = f"{GBP_MY_BUSINESS_API}/{config.local_post_name}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
        return resp.json()

    async def _create_local_post(self, config: GBPCreateLocalPostConfig, headers: Dict) -> Dict:
        body: Dict[str, Any] = {
            "languageCode": config.language_code or "en-US",
            "summary": config.summary,
            "topicType": config.topic_type,
        }
        if config.call_to_action_type:
            body["callToAction"] = {"actionType": config.call_to_action_type}
            if config.call_to_action_url:
                body["callToAction"]["url"] = config.call_to_action_url
        if config.media_source_url:
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": config.media_source_url}]
        if config.topic_type == "EVENT":
            event: Dict[str, Any] = {"title": config.event_title or "Event"}
            if config.event_start:
                parts = config.event_start.split("-")
                event["schedule"] = {
                    "startDate": {"year": int(parts[0]), "month": int(parts[1]), "day": int(parts[2])},
                    "startTime": {"hours": 0, "minutes": 0, "seconds": 0},
                }
            if config.event_end:
                parts = config.event_end.split("-")
                event.setdefault("schedule", {})["endDate"] = {
                    "year": int(parts[0]), "month": int(parts[1]), "day": int(parts[2])
                }
                event["schedule"].setdefault("endTime", {"hours": 23, "minutes": 59, "seconds": 0})
            body["event"] = event
        if config.topic_type == "OFFER":
            offer: Dict[str, Any] = {}
            if config.offer_coupon_code:
                offer["couponCode"] = config.offer_coupon_code
            if config.offer_redeem_url:
                offer["redeemOnlineUrl"] = config.offer_redeem_url
            if config.offer_terms:
                offer["termsConditions"] = config.offer_terms
            body["offer"] = offer
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._posts_base_url(config.account_id, config.location_id),
                headers={**headers, "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
        return {"status": "created", "post": resp.json()}

    async def _update_local_post(self, config: GBPUpdateLocalPostConfig, headers: Dict) -> Dict:
        url = f"{GBP_MY_BUSINESS_API}/{config.local_post_name}"
        body: Dict[str, Any] = {}
        mask_fields: List[str] = []
        if config.summary:
            body["summary"] = config.summary
            mask_fields.append("summary")
        if config.call_to_action_type:
            body["callToAction"] = {"actionType": config.call_to_action_type}
            if config.call_to_action_url:
                body["callToAction"]["url"] = config.call_to_action_url
            mask_fields.append("callToAction")
        if config.media_source_url:
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": config.media_source_url}]
            mask_fields.append("media")
        if not mask_fields:
            raise ValueError("At least one field (summary, callToAction, media) must be provided")
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                url,
                headers={**headers, "Content-Type": "application/json"},
                params={"updateMask": ",".join(mask_fields)},
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
        return {"status": "updated", "post": resp.json()}

    async def _delete_local_post(self, config: GBPDeleteLocalPostConfig, headers: Dict) -> Dict:
        url = f"{GBP_MY_BUSINESS_API}/{config.local_post_name}"
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=headers, timeout=30)
            resp.raise_for_status()
        return {"status": "deleted", "local_post_name": config.local_post_name}

    async def _get_local_post_insights(self, config: GBPGetLocalPostInsightsConfig, headers: Dict) -> Dict:
        from datetime import date, timedelta
        post_names = [n.strip() for n in config.local_post_names.split(",") if n.strip()]
        if not post_names:
            raise ValueError("At least one local post name is required")
        start = config.start_date or (date.today() - timedelta(days=30)).isoformat()
        end = config.end_date or date.today().isoformat()
        body = {
            "localPostNames": post_names,
            "basicRequest": {
                "metricRequests": [
                    {"metric": "LOCAL_POST_VIEWS_SEARCH"},
                    {"metric": "LOCAL_POST_ACTIONS_CALL_TO_ACTION"},
                ],
                "timeRange": {
                    "startTime": f"{start}T00:00:00Z",
                    "endTime": f"{end}T23:59:59Z",
                },
            },
        }
        parent = f"{_account_location(config.account_id, config.location_id)}"
        url = f"{GBP_MY_BUSINESS_API}/{parent}/localPosts:reportInsights"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={**headers, "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
        return resp.json()

    # -------------------------------------------------------------------------
    # Media
    # -------------------------------------------------------------------------

    def _media_base_url(self, account_id: str, location_id: str) -> str:
        return f"{GBP_MY_BUSINESS_API}/{_account_location(account_id, location_id)}/media"

    async def _list_media(self, config: GBPListMediaConfig, headers: Dict) -> Dict:
        params: Dict[str, Any] = {"pageSize": int(config.page_size) if config.page_size else 100}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self._media_base_url(config.account_id, config.location_id),
                headers=headers, params=params, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        items = data.get("mediaItems", [])
        return {"media_items": items, "count": len(items), "next_page_token": data.get("nextPageToken")}

    async def _get_media(self, config: GBPGetMediaConfig, headers: Dict) -> Dict:
        url = f"{GBP_MY_BUSINESS_API}/{config.media_item_name}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
        return resp.json()

    async def _create_media(self, config: GBPCreateMediaConfig, headers: Dict) -> Dict:
        body: Dict[str, Any] = {
            "mediaFormat": config.media_format,
            "locationAssociation": {"category": config.category},
            "sourceUrl": config.source_url,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._media_base_url(config.account_id, config.location_id),
                headers={**headers, "Content-Type": "application/json"},
                json=body,
                timeout=60,
            )
            resp.raise_for_status()
        return {"status": "created", "media_item": resp.json()}

    async def _delete_media(self, config: GBPDeleteMediaConfig, headers: Dict) -> Dict:
        url = f"{GBP_MY_BUSINESS_API}/{config.media_item_name}"
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=headers, timeout=30)
            resp.raise_for_status()
        return {"status": "deleted", "media_item_name": config.media_item_name}

    async def _list_customer_media(self, config: GBPListCustomerMediaConfig, headers: Dict) -> Dict:
        params: Dict[str, Any] = {"pageSize": int(config.page_size) if config.page_size else 100}
        url = f"{self._media_base_url(config.account_id, config.location_id)}/customers"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        items = data.get("mediaItems", [])
        return {"media_items": items, "count": len(items), "next_page_token": data.get("nextPageToken")}

    # -------------------------------------------------------------------------
    # Analytics
    # -------------------------------------------------------------------------

    async def _get_performance(self, config: GBPGetPerformanceConfig, headers: Dict) -> Dict:
        from datetime import date, timedelta
        start = config.start_date or (date.today() - timedelta(days=30)).isoformat()
        end = config.end_date or date.today().isoformat()
        metrics_list = [m.strip() for m in config.daily_metrics.split(",") if m.strip()]
        start_parts = start.split("-")
        end_parts = end.split("-")
        params: Dict[str, Any] = {
            "dailyRange.startDate.year": start_parts[0],
            "dailyRange.startDate.month": start_parts[1].lstrip("0"),
            "dailyRange.startDate.day": start_parts[2].lstrip("0"),
            "dailyRange.endDate.year": end_parts[0],
            "dailyRange.endDate.month": end_parts[1].lstrip("0"),
            "dailyRange.endDate.day": end_parts[2].lstrip("0"),
            "dailyMetrics": metrics_list,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GBP_PERFORMANCE_API}/{config.location_id}:fetchMultiDailyMetricsTimeSeries",
                headers=headers, params=params, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        date_map: Dict[str, Dict[str, Any]] = {}
        for ts in data.get("multiDailyMetricTimeSeries", []):
            metric_name = ts.get("dailyMetric", "unknown")
            for series in (ts.get("dailyMetricTimeSeries", {}).get("timeSeries", {}).get("datedValues", [])):
                d = series.get("date", {})
                date_str = f"{d.get('year', '')}-{str(d.get('month', '')).zfill(2)}-{str(d.get('day', '')).zfill(2)}"
                if date_str not in date_map:
                    date_map[date_str] = {"date": date_str}
                date_map[date_str][metric_name] = _gbp_int(series.get("value", 0))
        rows = sorted(date_map.values(), key=lambda r: r["date"])
        return {"rows": rows, "row_count": len(rows), "metrics": metrics_list, "date_range": {"start": start, "end": end}}

    async def _get_search_keywords(self, config: GBPGetSearchKeywordsConfig, headers: Dict) -> Dict:
        from datetime import date
        year = int(config.year) if config.year else date.today().year
        month = int(config.month) if config.month else (date.today().month - 1 or 12)
        if not config.month and month == 12 and not config.year:
            year -= 1
        keywords = []
        page_token = None
        async with httpx.AsyncClient() as client:
            while True:
                params: Dict[str, Any] = {
                    "monthlyRange.startMonth.year": year,
                    "monthlyRange.startMonth.month": month,
                    "monthlyRange.endMonth.year": year,
                    "monthlyRange.endMonth.month": month,
                    "pageSize": 300,
                }
                if page_token:
                    params["pageToken"] = page_token
                resp = await client.get(
                    f"{GBP_PERFORMANCE_API}/{config.location_id}/searchkeywords/impressions/monthly",
                    headers=headers, params=params, timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                for kw in data.get("searchKeywordsCounts", []):
                    ins = kw.get("insightsValue", {})
                    keywords.append({
                        "keyword": kw.get("searchKeyword", ""),
                        "impressions": _gbp_int(ins.get("value", ins.get("threshold", 0))),
                    })
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        keywords.sort(key=lambda k: k.get("impressions", 0), reverse=True)
        return {"keywords": keywords, "count": len(keywords), "period": f"{year}-{str(month).zfill(2)}"}

    # -------------------------------------------------------------------------
    # Place Action Links
    # -------------------------------------------------------------------------

    async def _list_place_action_links(self, config: GBPListPlaceActionLinksConfig, headers: Dict) -> Dict:
        loc = _norm_location(config.location_id)
        params: Dict[str, Any] = {}
        if config.filter:
            params["filter"] = config.filter
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GBP_PLACE_ACTIONS_API}/{loc}/placeActionLinks",
                headers=headers, params=params, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        links = data.get("placeActionLinks", [])
        return {"place_action_links": links, "count": len(links)}

    async def _create_place_action_link(self, config: GBPCreatePlaceActionLinkConfig, headers: Dict) -> Dict:
        loc = _norm_location(config.location_id)
        body = {
            "uri": config.uri,
            "placeActionType": config.place_action_type,
            "isPreferred": config.is_preferred == "true",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GBP_PLACE_ACTIONS_API}/{loc}/placeActionLinks",
                headers={**headers, "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
        return {"status": "created", "place_action_link": resp.json()}

    async def _update_place_action_link(self, config: GBPUpdatePlaceActionLinkConfig, headers: Dict) -> Dict:
        link_name = config.place_action_link_name.strip()
        body: Dict[str, Any] = {}
        mask_fields: List[str] = []
        if config.uri:
            body["uri"] = config.uri
            mask_fields.append("uri")
        if config.is_preferred:
            body["isPreferred"] = config.is_preferred == "true"
            mask_fields.append("isPreferred")
        if not mask_fields:
            raise ValueError("At least one field (uri, is_preferred) must be provided")
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{GBP_PLACE_ACTIONS_API}/{link_name}",
                headers={**headers, "Content-Type": "application/json"},
                params={"updateMask": ",".join(mask_fields)},
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
        return {"status": "updated", "place_action_link": resp.json()}

    async def _delete_place_action_link(self, config: GBPDeletePlaceActionLinkConfig, headers: Dict) -> Dict:
        link_name = config.place_action_link_name.strip()
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{GBP_PLACE_ACTIONS_API}/{link_name}",
                headers=headers, timeout=30,
            )
            resp.raise_for_status()
        return {"status": "deleted", "place_action_link_name": link_name}
