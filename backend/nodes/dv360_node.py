"""
Google Display & Video 360 (DV360) automation node.

Provides workflow integration with the DV360 API (v4) plus the Bid Manager
reporting API (v2) for operations including:
- Advertisers: list, get, create, update
- Campaigns: list, get, create, update
- Insertion Orders: list, get, create, update
- Line Items: list, get, create, update, duplicate, delete
- Creatives: list, get, create, update, delete
- Targeting: list / create assigned targeting, search targeting options
- Channels: list, get, create
- Audiences: list first-party, edit Customer Match members
- Reporting (Bid Manager): create/list/get query, run query, get report
- Trigger: on report job completed (poll-based, cursor-deduped)

Authentication (two methods): OAuth 2.0 (Google, user-delegated) and a
service-account JSON key (JWT → access token) for server-to-server automation.
The service account must be linked to a DV360 user profile with access.
API Base URL: https://displayvideo.googleapis.com (v4)
Bid Manager Base URL: https://doubleclickbidmanager.googleapis.com (v2)
Documentation: https://developers.google.com/display-video/api/reference/rest/v4
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx
import jwt
import uuid as uuid_module

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.google_oauth import refresh_access_token
from nodes.scopes.google_cloud import DV360_SCOPES
from utils.google_service_account import require_google_service_account_token_uri
from utils.ssrf import guarded_async_client
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)

logger = logging.getLogger(__name__)

DV360_API_BASE = "https://displayvideo.googleapis.com/v4"
BID_MANAGER_API_BASE = "https://doubleclickbidmanager.googleapis.com/v2"

DV360_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/display-video",
    "https://www.googleapis.com/auth/doubleclickbidmanager",
]


def _parse_service_account_json(value: str) -> Dict[str, Any]:
    """Parse and validate a Google service-account JSON key blob."""
    try:
        data = json.loads(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid Service Account JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("Service Account JSON must be a JSON object")
    required = ["type", "client_email", "private_key", "private_key_id", "token_uri"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        raise ValueError(
            f"Service Account JSON is missing required fields: {', '.join(missing)}"
        )
    if data.get("type") != "service_account":
        raise ValueError("Service Account JSON must have type=service_account")
    return data


async def _mint_service_account_access_token(
    service_account_json: str, scopes: Optional[List[str]] = None
) -> str:
    """Exchange a service-account JWT assertion for an OAuth access token."""
    sa = _parse_service_account_json(service_account_json)
    token_uri = require_google_service_account_token_uri(sa["token_uri"])
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": sa["client_email"],
            "scope": " ".join(scopes or DV360_OAUTH_SCOPES),
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        },
        sa["private_key"],
        algorithm="RS256",
        headers={"kid": sa["private_key_id"]},
    )
    async with guarded_async_client(timeout=30.0) as client:
        response = await client.post(
            token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
    if response.status_code >= 400:
        raise ValueError(
            f"Service account token exchange failed: {response.text[:200]}"
        )
    access_token = response.json().get("access_token")
    if not access_token:
        raise ValueError("Service account token exchange returned no access_token")
    return access_token


async def _resolve_access_token_from_credential_data(
    credential_data: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Resolve a bearer token from raw (pre-freshened) credential data — used by
    dropdown loaders. OAuth data is already refreshed by the handler; a
    service-account key is exchanged for a fresh token here."""
    credential_data = credential_data or {}
    if credential_data.get("credential_type") == "dv360_service_account":
        sa_json = credential_data.get("service_account_json")
        return await _mint_service_account_access_token(sa_json) if sa_json else None
    return credential_data.get("access_token")


# ============================================================================
# Credential Schema
# ============================================================================


class DV360OAuthCredential(BaseModel):
    """OAuth credential for Google Display & Video 360 access."""

    credential_type: Literal["dv360_oauth"] = Field(
        "dv360_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when the access token expires",
    )
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "google",
            "x-credential-url": "https://console.cloud.google.com/apis/credentials",
            "x-oauth-scopes": DV360_OAUTH_SCOPES,
            "x-credential-instructions": (
                "Sign in with a Google account that has Display & Video 360 "
                "access. Grant the Display & Video permission for campaign, "
                "line-item, creative and targeting operations; the Bid Manager "
                "permission is only needed for the report operations, so you can "
                "skip it and still connect."
            ),
        }
    )


class DV360ServiceAccountCredential(BaseModel):
    """Service-account JSON key for server-to-server DV360 access.

    A signed JWT is exchanged for an OAuth access token per run. The service
    account must be linked to a DV360 user profile with the required role.
    """

    credential_type: Literal["dv360_service_account"] = Field(
        "dv360_service_account", json_schema_extra={"ui:hidden": True}
    )
    service_account_json: str = Field(
        ...,
        title="Service Account JSON",
        description="Raw JSON key for a Google Cloud service account with DV360 access",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 12},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.cloud.google.com/iam-admin/serviceaccounts",
            "x-credential-instructions": (
                "Create a JSON key for a service account, then link that service "
                "account's email to a DV360 user profile (Admin → Users) with the "
                "required role. Prefer user OAuth for user-delegated access; use a "
                "service account for server-to-server automation."
            ),
        }
    )


DV360Credential = Union[
    DV360OAuthCredential,
    DV360ServiceAccountCredential,
]


# ============================================================================
# Shared dynamic-options field helpers
# ============================================================================


def _advertiser_field(required: bool = True) -> Any:
    extra: Dict[str, Any] = {
        "x-dynamic-options": {
            "field_name": "advertiser_id",
            "placeholder": "Select an advertiser...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste an advertiser ID",
        }
    }
    return Field(
        ... if required else None,
        title="Advertiser",
        description="DV360 advertiser ID that scopes this operation",
        json_schema_extra=extra,
    )


def _partner_field() -> Any:
    return Field(
        ...,
        title="Partner",
        description="DV360 partner ID to list advertisers for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "partner_id",
                "placeholder": "Select a partner...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a partner ID",
            }
        },
    )


def _advertiser_child_field(field_name: str, title: str, description: str) -> Any:
    """A resource-id field listable under the selected advertiser (depends_on advertiser_id)."""
    return Field(
        ...,
        title=title,
        description=description,
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": field_name,
                "depends_on": "advertiser_id",
                "placeholder": f"Select a {title.lower()}...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste an ID",
            }
        },
    )


# ============================================================================
# Advertiser Operations
# ============================================================================


class DV360ListAdvertisersConfig(BaseModel):
    """List advertisers the authenticated user can access under a partner."""

    operation: Literal["list_advertisers"] = Field(
        "list_advertisers",
        json_schema_extra={
            "const": "list_advertisers",
            "ui:hidden": True,
            "x-category": "Advertisers",
            "x-is-trigger": False,
            "x-display-name": "List Advertisers",
        },
        title="List Advertisers",
    )
    partner_id: str = _partner_field()
    filter: Optional[str] = Field(
        None, title="Filter", description="DV360 filter expression (e.g. entityStatus=\"ENTITY_STATUS_ACTIVE\")"
    )
    page_size: Optional[str] = Field(
        "100", title="Page Size", description="Max advertisers to return (1-200)"
    )


class DV360GetAdvertiserConfig(BaseModel):
    """Fetch a single advertiser's details."""

    operation: Literal["get_advertiser"] = Field(
        "get_advertiser",
        json_schema_extra={
            "const": "get_advertiser",
            "ui:hidden": True,
            "x-category": "Advertisers",
            "x-is-trigger": False,
            "x-display-name": "Get Advertiser",
        },
        title="Get Advertiser",
    )
    advertiser_id: str = _advertiser_field()


class DV360CreateAdvertiserConfig(BaseModel):
    """Create a new advertiser under a partner."""

    operation: Literal["create_advertiser"] = Field(
        "create_advertiser",
        json_schema_extra={
            "const": "create_advertiser",
            "ui:hidden": True,
            "x-category": "Advertisers",
            "x-is-trigger": False,
            "x-display-name": "Create Advertiser",
        },
        title="Create Advertiser",
    )
    advertiser_body: str = Field(
        ...,
        title="Advertiser JSON",
        description="JSON body for the advertiser resource (partnerId, displayName, generalConfig, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DV360UpdateAdvertiserConfig(BaseModel):
    """Patch fields on an existing advertiser."""

    operation: Literal["update_advertiser"] = Field(
        "update_advertiser",
        json_schema_extra={
            "const": "update_advertiser",
            "ui:hidden": True,
            "x-category": "Advertisers",
            "x-is-trigger": False,
            "x-display-name": "Update Advertiser",
        },
        title="Update Advertiser",
    )
    advertiser_id: str = _advertiser_field()
    update_mask: str = Field(
        ..., title="Update Mask", description="Comma-separated fields to update (e.g. displayName,entityStatus)"
    )
    advertiser_body: str = Field(
        ...,
        title="Advertiser JSON",
        description="JSON body containing the fields named in the update mask",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Campaign Operations
# ============================================================================


class DV360ListCampaignsConfig(BaseModel):
    """List campaigns for an advertiser."""

    operation: Literal["list_campaigns"] = Field(
        "list_campaigns",
        json_schema_extra={
            "const": "list_campaigns",
            "ui:hidden": True,
            "x-category": "Campaigns",
            "x-is-trigger": False,
            "x-display-name": "List Campaigns",
        },
        title="List Campaigns",
    )
    advertiser_id: str = _advertiser_field()
    filter: Optional[str] = Field(None, title="Filter", description="DV360 filter expression")
    page_size: Optional[str] = Field("100", title="Page Size", description="Max campaigns to return (1-200)")


class DV360GetCampaignConfig(BaseModel):
    """Fetch a single campaign."""

    operation: Literal["get_campaign"] = Field(
        "get_campaign",
        json_schema_extra={
            "const": "get_campaign",
            "ui:hidden": True,
            "x-category": "Campaigns",
            "x-is-trigger": False,
            "x-display-name": "Get Campaign",
        },
        title="Get Campaign",
    )
    advertiser_id: str = _advertiser_field()
    campaign_id: str = _advertiser_child_field(
        "campaign_id", "Campaign", "ID of the campaign to fetch"
    )


class DV360CreateCampaignConfig(BaseModel):
    """Create a campaign under an advertiser."""

    operation: Literal["create_campaign"] = Field(
        "create_campaign",
        json_schema_extra={
            "const": "create_campaign",
            "ui:hidden": True,
            "x-category": "Campaigns",
            "x-is-trigger": False,
            "x-display-name": "Create Campaign",
        },
        title="Create Campaign",
    )
    advertiser_id: str = _advertiser_field()
    campaign_body: str = Field(
        ...,
        title="Campaign JSON",
        description="JSON body for the campaign (displayName, entityStatus, campaignGoal, campaignFlight, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DV360UpdateCampaignConfig(BaseModel):
    """Patch fields on a campaign (e.g. status, budget)."""

    operation: Literal["update_campaign"] = Field(
        "update_campaign",
        json_schema_extra={
            "const": "update_campaign",
            "ui:hidden": True,
            "x-category": "Campaigns",
            "x-is-trigger": False,
            "x-display-name": "Update Campaign",
        },
        title="Update Campaign",
    )
    advertiser_id: str = _advertiser_field()
    campaign_id: str = _advertiser_child_field(
        "campaign_id", "Campaign", "ID of the campaign to update"
    )
    update_mask: str = Field(..., title="Update Mask", description="Comma-separated fields to update")
    campaign_body: str = Field(
        ...,
        title="Campaign JSON",
        description="JSON body containing the fields named in the update mask",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Insertion Order Operations
# ============================================================================


class DV360ListInsertionOrdersConfig(BaseModel):
    """List insertion orders for an advertiser."""

    operation: Literal["list_insertion_orders"] = Field(
        "list_insertion_orders",
        json_schema_extra={
            "const": "list_insertion_orders",
            "ui:hidden": True,
            "x-category": "Insertion Orders",
            "x-is-trigger": False,
            "x-display-name": "List Insertion Orders",
        },
        title="List Insertion Orders",
    )
    advertiser_id: str = _advertiser_field()
    filter: Optional[str] = Field(None, title="Filter", description="DV360 filter expression")
    page_size: Optional[str] = Field("100", title="Page Size", description="Max insertion orders to return")


class DV360CreateInsertionOrderConfig(BaseModel):
    """Create an insertion order under a campaign."""

    operation: Literal["create_insertion_order"] = Field(
        "create_insertion_order",
        json_schema_extra={
            "const": "create_insertion_order",
            "ui:hidden": True,
            "x-category": "Insertion Orders",
            "x-is-trigger": False,
            "x-display-name": "Create Insertion Order",
        },
        title="Create Insertion Order",
    )
    advertiser_id: str = _advertiser_field()
    insertion_order_body: str = Field(
        ...,
        title="Insertion Order JSON",
        description="JSON body for the insertion order (campaignId, displayName, pacing, budget, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DV360UpdateInsertionOrderConfig(BaseModel):
    """Patch an insertion order (status, pacing, budget)."""

    operation: Literal["update_insertion_order"] = Field(
        "update_insertion_order",
        json_schema_extra={
            "const": "update_insertion_order",
            "ui:hidden": True,
            "x-category": "Insertion Orders",
            "x-is-trigger": False,
            "x-display-name": "Update Insertion Order",
        },
        title="Update Insertion Order",
    )
    advertiser_id: str = _advertiser_field()
    insertion_order_id: str = _advertiser_child_field(
        "insertion_order_id", "Insertion Order", "ID of the insertion order"
    )
    update_mask: str = Field(..., title="Update Mask", description="Comma-separated fields to update")
    insertion_order_body: str = Field(
        ...,
        title="Insertion Order JSON",
        description="JSON body containing the fields named in the update mask",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Line Item Operations
# ============================================================================


class DV360ListLineItemsConfig(BaseModel):
    """List line items for an advertiser."""

    operation: Literal["list_line_items"] = Field(
        "list_line_items",
        json_schema_extra={
            "const": "list_line_items",
            "ui:hidden": True,
            "x-category": "Line Items",
            "x-is-trigger": False,
            "x-display-name": "List Line Items",
        },
        title="List Line Items",
    )
    advertiser_id: str = _advertiser_field()
    filter: Optional[str] = Field(None, title="Filter", description="DV360 filter expression")
    page_size: Optional[str] = Field("100", title="Page Size", description="Max line items to return")


class DV360GetLineItemConfig(BaseModel):
    """Fetch a single line item."""

    operation: Literal["get_line_item"] = Field(
        "get_line_item",
        json_schema_extra={
            "const": "get_line_item",
            "ui:hidden": True,
            "x-category": "Line Items",
            "x-is-trigger": False,
            "x-display-name": "Get Line Item",
        },
        title="Get Line Item",
    )
    advertiser_id: str = _advertiser_field()
    line_item_id: str = _advertiser_child_field(
        "line_item_id", "Line Item", "ID of the line item to fetch"
    )


class DV360CreateLineItemConfig(BaseModel):
    """Create a line item."""

    operation: Literal["create_line_item"] = Field(
        "create_line_item",
        json_schema_extra={
            "const": "create_line_item",
            "ui:hidden": True,
            "x-category": "Line Items",
            "x-is-trigger": False,
            "x-display-name": "Create Line Item",
        },
        title="Create Line Item",
    )
    advertiser_id: str = _advertiser_field()
    line_item_body: str = Field(
        ...,
        title="Line Item JSON",
        description="JSON body for the line item (insertionOrderId, displayName, lineItemType, flight, budget, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DV360UpdateLineItemConfig(BaseModel):
    """Patch a line item (status/bid/budget); common pause/activate path."""

    operation: Literal["update_line_item"] = Field(
        "update_line_item",
        json_schema_extra={
            "const": "update_line_item",
            "ui:hidden": True,
            "x-category": "Line Items",
            "x-is-trigger": False,
            "x-display-name": "Update Line Item",
        },
        title="Update Line Item",
    )
    advertiser_id: str = _advertiser_field()
    line_item_id: str = _advertiser_child_field(
        "line_item_id", "Line Item", "ID of the line item to update"
    )
    update_mask: str = Field(
        ..., title="Update Mask", description="Comma-separated fields to update (e.g. entityStatus)"
    )
    line_item_body: str = Field(
        ...,
        title="Line Item JSON",
        description="JSON body containing the fields named in the update mask",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DV360DuplicateLineItemConfig(BaseModel):
    """Clone a line item."""

    operation: Literal["duplicate_line_item"] = Field(
        "duplicate_line_item",
        json_schema_extra={
            "const": "duplicate_line_item",
            "ui:hidden": True,
            "x-category": "Line Items",
            "x-is-trigger": False,
            "x-display-name": "Duplicate Line Item",
        },
        title="Duplicate Line Item",
    )
    advertiser_id: str = _advertiser_field()
    line_item_id: str = _advertiser_child_field(
        "line_item_id", "Line Item", "ID of the line item to duplicate"
    )
    target_display_name: Optional[str] = Field(
        None, title="New Display Name", description="Display name for the duplicated line item"
    )


# ============================================================================
# Creative Operations
# ============================================================================


class DV360ListCreativesConfig(BaseModel):
    """List creatives for an advertiser."""

    operation: Literal["list_creatives"] = Field(
        "list_creatives",
        json_schema_extra={
            "const": "list_creatives",
            "ui:hidden": True,
            "x-category": "Creatives",
            "x-is-trigger": False,
            "x-display-name": "List Creatives",
        },
        title="List Creatives",
    )
    advertiser_id: str = _advertiser_field()
    filter: Optional[str] = Field(None, title="Filter", description="DV360 filter expression")
    page_size: Optional[str] = Field("100", title="Page Size", description="Max creatives to return")


class DV360CreateCreativeConfig(BaseModel):
    """Create a creative."""

    operation: Literal["create_creative"] = Field(
        "create_creative",
        json_schema_extra={
            "const": "create_creative",
            "ui:hidden": True,
            "x-category": "Creatives",
            "x-is-trigger": False,
            "x-display-name": "Create Creative",
        },
        title="Create Creative",
    )
    advertiser_id: str = _advertiser_field()
    creative_body: str = Field(
        ...,
        title="Creative JSON",
        description="JSON body for the creative (displayName, creativeType, dimensions, assets, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DV360UpdateCreativeConfig(BaseModel):
    """Patch a creative."""

    operation: Literal["update_creative"] = Field(
        "update_creative",
        json_schema_extra={
            "const": "update_creative",
            "ui:hidden": True,
            "x-category": "Creatives",
            "x-is-trigger": False,
            "x-display-name": "Update Creative",
        },
        title="Update Creative",
    )
    advertiser_id: str = _advertiser_field()
    creative_id: str = _advertiser_child_field(
        "creative_id", "Creative", "ID of the creative to update"
    )
    update_mask: str = Field(..., title="Update Mask", description="Comma-separated fields to update")
    creative_body: str = Field(
        ...,
        title="Creative JSON",
        description="JSON body containing the fields named in the update mask",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Targeting Operations
# ============================================================================


class DV360ListAssignedTargetingConfig(BaseModel):
    """List targeting options assigned to a line item for one targeting type."""

    operation: Literal["list_assigned_targeting"] = Field(
        "list_assigned_targeting",
        json_schema_extra={
            "const": "list_assigned_targeting",
            "ui:hidden": True,
            "x-category": "Targeting",
            "x-is-trigger": False,
            "x-display-name": "List Assigned Targeting",
        },
        title="List Assigned Targeting",
    )
    advertiser_id: str = _advertiser_field()
    line_item_id: str = Field(..., title="Line Item ID", description="ID of the line item")
    targeting_type: str = Field(
        ...,
        title="Targeting Type",
        description="Targeting type (e.g. TARGETING_TYPE_GEO_REGION, TARGETING_TYPE_KEYWORD)",
    )


class DV360CreateAssignedTargetingConfig(BaseModel):
    """Assign a targeting option to a line item."""

    operation: Literal["create_assigned_targeting"] = Field(
        "create_assigned_targeting",
        json_schema_extra={
            "const": "create_assigned_targeting",
            "ui:hidden": True,
            "x-category": "Targeting",
            "x-is-trigger": False,
            "x-display-name": "Create Assigned Targeting",
        },
        title="Create Assigned Targeting",
    )
    advertiser_id: str = _advertiser_field()
    line_item_id: str = Field(..., title="Line Item ID", description="ID of the line item")
    targeting_type: str = Field(..., title="Targeting Type", description="Targeting type to assign")
    targeting_body: str = Field(
        ...,
        title="Assigned Targeting JSON",
        description="JSON body for the assigned targeting option (the *Details field for the type)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DV360SearchTargetingOptionsConfig(BaseModel):
    """Search global targeting options (e.g. geo, keywords) by query."""

    operation: Literal["search_targeting_options"] = Field(
        "search_targeting_options",
        json_schema_extra={
            "const": "search_targeting_options",
            "ui:hidden": True,
            "x-category": "Targeting",
            "x-is-trigger": False,
            "x-display-name": "Search Targeting Options",
        },
        title="Search Targeting Options",
    )
    targeting_type: str = Field(..., title="Targeting Type", description="Targeting type to search within")
    advertiser_id: str = _advertiser_field()
    query: str = Field(..., title="Search Query", description="Search string (e.g. a city name or keyword)")


# ============================================================================
# Channel Operations
# ============================================================================


class DV360ListChannelsConfig(BaseModel):
    """List channels (site/app groupings) for an advertiser."""

    operation: Literal["list_channels"] = Field(
        "list_channels",
        json_schema_extra={
            "const": "list_channels",
            "ui:hidden": True,
            "x-category": "Channels",
            "x-is-trigger": False,
            "x-display-name": "List Channels",
        },
        title="List Channels",
    )
    advertiser_id: str = _advertiser_field()
    page_size: Optional[str] = Field("100", title="Page Size", description="Max channels to return")


class DV360CreateChannelConfig(BaseModel):
    """Create a channel."""

    operation: Literal["create_channel"] = Field(
        "create_channel",
        json_schema_extra={
            "const": "create_channel",
            "ui:hidden": True,
            "x-category": "Channels",
            "x-is-trigger": False,
            "x-display-name": "Create Channel",
        },
        title="Create Channel",
    )
    advertiser_id: str = _advertiser_field()
    display_name: str = Field(..., title="Display Name", description="Name for the new channel")


# ============================================================================
# Audience Operations
# ============================================================================


class DV360ListAudiencesConfig(BaseModel):
    """List first-party and partner audiences."""

    operation: Literal["list_audiences"] = Field(
        "list_audiences",
        json_schema_extra={
            "const": "list_audiences",
            "ui:hidden": True,
            "x-category": "Audiences",
            "x-is-trigger": False,
            "x-display-name": "List Audiences",
        },
        title="List Audiences",
    )
    advertiser_id: str = _advertiser_field()
    page_size: Optional[str] = Field("100", title="Page Size", description="Max audiences to return")


class DV360EditCustomerMatchConfig(BaseModel):
    """Add or remove Customer Match members in a first-party audience."""

    operation: Literal["edit_customer_match_members"] = Field(
        "edit_customer_match_members",
        json_schema_extra={
            "const": "edit_customer_match_members",
            "ui:hidden": True,
            "x-category": "Audiences",
            "x-is-trigger": False,
            "x-display-name": "Edit Customer Match Members",
        },
        title="Edit Customer Match Members",
    )
    advertiser_id: str = _advertiser_field()
    audience_id: str = _advertiser_child_field(
        "audience_id", "Audience", "firstPartyAndPartnerAudienceId to edit"
    )
    edit_body: str = Field(
        ...,
        title="Edit JSON",
        description="JSON body with addedContactInfoList / removedContactInfoList (or mobile device IDs)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Reporting (Bid Manager) Operations
# ============================================================================


class DV360CreateReportQueryConfig(BaseModel):
    """Create a Bid Manager reporting query (dimensions/metrics/filters)."""

    operation: Literal["create_report_query"] = Field(
        "create_report_query",
        json_schema_extra={
            "const": "create_report_query",
            "ui:hidden": True,
            "x-category": "Reporting",
            "x-is-trigger": False,
            "x-display-name": "Create Report Query",
        },
        title="Create Report Query",
    )
    query_body: str = Field(
        ...,
        title="Query JSON",
        description="Bid Manager query JSON (metadata, params with dimensions/metrics/filters, schedule)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DV360RunReportQueryConfig(BaseModel):
    """Run a Bid Manager query to generate a fresh report."""

    operation: Literal["run_report_query"] = Field(
        "run_report_query",
        json_schema_extra={
            "const": "run_report_query",
            "ui:hidden": True,
            "x-category": "Reporting",
            "x-is-trigger": False,
            "x-display-name": "Run Report Query",
        },
        title="Run Report Query",
    )
    query_id: str = Field(..., title="Query ID", description="ID of the Bid Manager query to run")


# ============================================================================
# Trigger (poll-based) Operation
# ============================================================================


class DV360OnJobCompletedConfig(BaseModel):
    """Poll-based trigger: fire when a Bid Manager report run for a query newly
    completes. DV360 has no native webhooks; async report runs are polled until
    done. The node watches a query's report list and emits each newly-finished
    report exactly once (deduped via the last-seen report id cursor)."""

    operation: Literal["on_job_completed"] = Field(
        "on_job_completed",
        title="On Async Job Completed",
        description="Trigger when a report run for a query completes",
        json_schema_extra={
            "const": "on_job_completed",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Async Job Completed",
        },
    )
    query_id: str = Field(
        ...,
        title="Query",
        description="Bid Manager query whose report runs to watch for completion",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "query_id",
                "placeholder": "Select a report query...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a query ID",
            }
        },
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to poll for newly completed report runs",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    page_size: Optional[str] = Field(
        "50",
        title="Max Reports",
        description="Maximum number of report runs to inspect per poll",
        json_schema_extra={"ui:hidden": True},
    )
    # Hidden internal fields for webhook/schedule management
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True, "ui:loadValue": True, "ui:copyable": True},
    )
    schedule_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Check",
        json_schema_extra={"ui:widget": "nextRun"},
    )
    interval_ms: Optional[int] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    # Cursor: highest report id already emitted, so we never re-emit a finished run.
    last_seen_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_active: Optional[bool] = Field(
        default=True, json_schema_extra={"ui:hidden": True}
    )


# ============================================================================
# Operation Configs — additional read/CRUD coverage
# ============================================================================


class DV360GetInsertionOrderConfig(BaseModel):
    """Fetch a single insertion order."""

    operation: Literal["get_insertion_order"] = Field(
        "get_insertion_order",
        json_schema_extra={
            "const": "get_insertion_order",
            "ui:hidden": True,
            "x-category": "Insertion Orders",
            "x-is-trigger": False,
            "x-display-name": "Get Insertion Order",
        },
        title="Get Insertion Order",
    )
    advertiser_id: str = _advertiser_field()
    insertion_order_id: str = _advertiser_child_field(
        "insertion_order_id", "Insertion Order", "ID of the insertion order to fetch"
    )


class DV360GetCreativeConfig(BaseModel):
    """Fetch a single creative."""

    operation: Literal["get_creative"] = Field(
        "get_creative",
        json_schema_extra={
            "const": "get_creative",
            "ui:hidden": True,
            "x-category": "Creatives",
            "x-is-trigger": False,
            "x-display-name": "Get Creative",
        },
        title="Get Creative",
    )
    advertiser_id: str = _advertiser_field()
    creative_id: str = _advertiser_child_field(
        "creative_id", "Creative", "ID of the creative to fetch"
    )


class DV360GetChannelConfig(BaseModel):
    """Fetch a single channel."""

    operation: Literal["get_channel"] = Field(
        "get_channel",
        json_schema_extra={
            "const": "get_channel",
            "ui:hidden": True,
            "x-category": "Channels",
            "x-is-trigger": False,
            "x-display-name": "Get Channel",
        },
        title="Get Channel",
    )
    advertiser_id: str = _advertiser_field()
    channel_id: str = _advertiser_child_field(
        "channel_id", "Channel", "ID of the channel to fetch"
    )


class DV360DeleteLineItemConfig(BaseModel):
    """Delete a (draft) line item."""

    operation: Literal["delete_line_item"] = Field(
        "delete_line_item",
        json_schema_extra={
            "const": "delete_line_item",
            "ui:hidden": True,
            "x-category": "Line Items",
            "x-is-trigger": False,
            "x-display-name": "Delete Line Item",
        },
        title="Delete Line Item",
    )
    advertiser_id: str = _advertiser_field()
    line_item_id: str = _advertiser_child_field(
        "line_item_id", "Line Item", "ID of the line item to delete"
    )


class DV360DeleteCreativeConfig(BaseModel):
    """Delete an unused creative."""

    operation: Literal["delete_creative"] = Field(
        "delete_creative",
        json_schema_extra={
            "const": "delete_creative",
            "ui:hidden": True,
            "x-category": "Creatives",
            "x-is-trigger": False,
            "x-display-name": "Delete Creative",
        },
        title="Delete Creative",
    )
    advertiser_id: str = _advertiser_field()
    creative_id: str = _advertiser_child_field(
        "creative_id", "Creative", "ID of the creative to delete"
    )


class DV360ListReportQueriesConfig(BaseModel):
    """List saved Bid Manager report queries."""

    operation: Literal["list_report_queries"] = Field(
        "list_report_queries",
        json_schema_extra={
            "const": "list_report_queries",
            "ui:hidden": True,
            "x-category": "Reporting",
            "x-is-trigger": False,
            "x-display-name": "List Report Queries",
        },
        title="List Report Queries",
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Maximum number of queries to return"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token for the next page of queries"
    )


class DV360GetReportQueryConfig(BaseModel):
    """Fetch a single Bid Manager report query."""

    operation: Literal["get_report_query"] = Field(
        "get_report_query",
        json_schema_extra={
            "const": "get_report_query",
            "ui:hidden": True,
            "x-category": "Reporting",
            "x-is-trigger": False,
            "x-display-name": "Get Report Query",
        },
        title="Get Report Query",
    )
    query_id: str = Field(
        ..., title="Query ID", description="ID of the Bid Manager query to fetch"
    )


class DV360GetReportConfig(BaseModel):
    """Fetch a single report run (status + download path) of a query."""

    operation: Literal["get_report"] = Field(
        "get_report",
        json_schema_extra={
            "const": "get_report",
            "ui:hidden": True,
            "x-category": "Reporting",
            "x-is-trigger": False,
            "x-display-name": "Get Report",
        },
        title="Get Report",
    )
    query_id: str = Field(
        ..., title="Query ID", description="ID of the Bid Manager query"
    )
    report_id: str = Field(
        ..., title="Report ID", description="ID of the report run to fetch"
    )


# ============================================================================
# Discriminated Union
# ============================================================================


DV360Config = Annotated[
    Union[
        DV360ListAdvertisersConfig,
        DV360GetAdvertiserConfig,
        DV360CreateAdvertiserConfig,
        DV360UpdateAdvertiserConfig,
        DV360ListCampaignsConfig,
        DV360GetCampaignConfig,
        DV360CreateCampaignConfig,
        DV360UpdateCampaignConfig,
        DV360ListInsertionOrdersConfig,
        DV360CreateInsertionOrderConfig,
        DV360UpdateInsertionOrderConfig,
        DV360ListLineItemsConfig,
        DV360GetLineItemConfig,
        DV360CreateLineItemConfig,
        DV360UpdateLineItemConfig,
        DV360DuplicateLineItemConfig,
        DV360ListCreativesConfig,
        DV360CreateCreativeConfig,
        DV360UpdateCreativeConfig,
        DV360ListAssignedTargetingConfig,
        DV360CreateAssignedTargetingConfig,
        DV360SearchTargetingOptionsConfig,
        DV360ListChannelsConfig,
        DV360CreateChannelConfig,
        DV360ListAudiencesConfig,
        DV360EditCustomerMatchConfig,
        DV360CreateReportQueryConfig,
        DV360RunReportQueryConfig,
        DV360GetInsertionOrderConfig,
        DV360GetCreativeConfig,
        DV360GetChannelConfig,
        DV360DeleteLineItemConfig,
        DV360DeleteCreativeConfig,
        DV360ListReportQueriesConfig,
        DV360GetReportQueryConfig,
        DV360GetReportConfig,
        DV360OnJobCompletedConfig,
    ],
    Discriminator("operation"),
]


class DV360NodeConfig(NodeConfig[DV360Config, DV360Credential]):
    """Full configuration for the DV360 node including credentials."""

    pass


# ============================================================================
# Request helper
# ============================================================================


def _parse_json_body(raw: Optional[str], field_label: str) -> Dict[str, Any]:
    """Parse a JSON string field into a dict, raising on malformed input."""
    import json

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{field_label} must be valid JSON: {e}")
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_label} must be a JSON object")
    return parsed


async def _dv360_request(
    access_token: str,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Google DV360 / Bid Manager request and return a structured result."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    error_obj = err.get("error", {})
                    message = (
                        error_obj.get("message")
                        if isinstance(error_obj, dict)
                        else (err.get("message") if isinstance(err, dict) else str(err))
                    )
                    message = message or response.text
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                # DV360/Bid Manager returns cryptic auth errors ("Invalid
                # credential, cannot get profile", "insufficient authentication
                # scopes") when the OAuth token is VALID but the Google account
                # isn't linked to a DV360 user profile / lacks DV360 access.
                # Surface an actionable hint so it doesn't read as a bad token.
                if response.status_code in (401, 403):
                    message = (
                        f"{message} — this usually means the connected Google "
                        "account isn't linked to a Display & Video 360 user "
                        "profile (or lacks the required role). The credential "
                        "itself is valid; add the account's email to a DV360 "
                        "user profile (Admin -> Users) with access to this "
                        "partner/advertiser, or verify the account is "
                        "provisioned for DV360."
                    )
                logger.error(f"[DV360Node] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[DV360Node] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class DV360Node(WorkflowNode):
    """Google Display & Video 360 automation node."""

    scope_registry = DV360_SCOPES
    connection_evidence = ConnectionEvidence(
        field="partner_id",
        noun="partners",
    )

    edit_examples = [
        "List all advertisers under our partner",
        "Pause a line item by setting its entity status to inactive",
        "Create a campaign under an advertiser",
        "List the creatives for an advertiser",
        "Run a Bid Manager report query and fetch results",
    ]

    @classmethod
    def get_config_model(cls):
        return DV360NodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """The DV360 trigger is poll-based: the webhook is a wake-up signal, not
        data. Return None so execute() runs and actually polls the report list."""
        if config.get("operation") == "on_job_completed":
            return None
        return payload

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: uuid_module.UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the webhook + polling schedule for the trigger operation
        (same pattern as the Gmail/Cron trigger nodes)."""
        from utils.webhook_manager import WebhookManager
        from utils.cron_scheduler_client import (
            create_schedule,
            update_schedule,
            is_cron_scheduler_enabled,
        )

        if field_name != "webhook_url":
            return {"value": None}

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool, user_id=user_id, workflow_id=workflow_id, node_id=node_id
        )
        webhook_id = webhook_data.get("webhook_id")
        webhook_url = webhook_data.get("webhook_url")

        schedule = {"frequency": "minutes", "interval": 5}
        if context and context.get("schedule"):
            schedule = context["schedule"]
        cron_expression = schedule_to_cron(schedule)
        logger.info(f"[DV360Node] Trigger schedule {schedule} -> cron: {cron_expression}")

        existing_schedule_id = context.get("schedule_id") if context else None
        schedule_id = existing_schedule_id
        next_run = None

        if is_cron_scheduler_enabled() and webhook_url:
            if existing_schedule_id:
                result = await update_schedule(
                    schedule_id=existing_schedule_id,
                    cron_expression=cron_expression,
                )
                if result.get("success"):
                    next_run = result.get("next_run")
                elif "error" in result:
                    logger.warning(f"[DV360Node] Failed to update schedule: {result['error']}")
                    existing_schedule_id = None

            if not existing_schedule_id:
                result = await create_schedule(
                    user_id=user_id,
                    workflow_id=str(workflow_id),
                    node_id=node_id,
                    cron_expression=cron_expression,
                    webhook_url=webhook_url,
                    payload={"source": "dv360_trigger", "node_id": node_id},
                )
                if "id" in result:
                    schedule_id = result["id"]
                    next_run = result.get("next_run")
                elif "error" in result:
                    logger.warning(f"[DV360Node] Failed to create schedule: {result['error']}")

        return {
            "values": {
                "webhook_id": webhook_id,
                "webhook_url": webhook_url,
                "schedule_id": schedule_id,
                "next_run": next_run,
                "interval_ms": schedule_to_interval_ms(schedule),
                "is_active": True,
            }
        }

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns / triggers)."""
        if (credential_data or {}).get("credential_type") == "dv360_service_account":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="google",
        )

    # ------------------------------------------------------------------
    # Dynamic options
    # ------------------------------------------------------------------
    # field_name -> (id key, display key, advertiser-scoped sub-path or None,
    #                response list key, action name). A None sub-path means the
    #                resource is top-level (partners/advertisers) rather than
    #                nested under an advertiser.
    _LISTABLE_FIELDS: Dict[str, Dict[str, Any]] = {
        "partner_id": {
            "url": f"{DV360_API_BASE}/partners",
            "list_key": "partners",
            "id_key": "partnerId",
            "action": "list_partners",
        },
        "advertiser_id": {
            "url": f"{DV360_API_BASE}/advertisers",
            "list_key": "advertisers",
            "id_key": "advertiserId",
            "action": "list_advertisers",
        },
        "campaign_id": {
            "sub_path": "campaigns",
            "list_key": "campaigns",
            "id_key": "campaignId",
            "action": "list_campaigns",
        },
        "insertion_order_id": {
            "sub_path": "insertionOrders",
            "list_key": "insertionOrders",
            "id_key": "insertionOrderId",
            "action": "list_insertion_orders",
        },
        "line_item_id": {
            "sub_path": "lineItems",
            "list_key": "lineItems",
            "id_key": "lineItemId",
            "action": "list_line_items",
        },
        "creative_id": {
            "sub_path": "creatives",
            "list_key": "creatives",
            "id_key": "creativeId",
            "action": "list_creatives",
        },
        "audience_id": {
            # Top-level resource but filtered by advertiserId query param.
            "url": f"{DV360_API_BASE}/firstPartyAndPartnerAudiences",
            "list_key": "firstPartyAndPartnerAudiences",
            "id_key": "firstPartyAndPartnerAudienceId",
            "action": "list_audiences",
            "advertiser_param": True,
        },
        "query_id": {
            # Bid Manager reporting queries (separate API host).
            "url": f"{BID_MANAGER_API_BASE}/queries",
            "list_key": "queries",
            "id_key": "queryId",
            "action": "list_queries",
        },
    }

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        spec = cls._LISTABLE_FIELDS.get(field_name)
        if spec is None:
            return {"options": [], "next_page_token": None}

        access_token = await cls._token_from_credential_data(credential_data)
        if not access_token:
            raise ValueError("Connect your Google DV360 account to load options.")

        ctx = context or {}
        params: Dict[str, Any] = {"pageSize": 200, "pageToken": page_token}

        # Resolve URL: advertiser-nested sub-resources need the selected advertiser.
        # An unselected parent returns empty (the field depends_on advertiser_id,
        # so the UI already prompts to pick one first) — that's not an error.
        url = spec.get("url")
        if "sub_path" in spec:
            advertiser_id = ctx.get("advertiser_id")
            if not advertiser_id:
                return {"options": [], "next_page_token": None}
            url = f"{DV360_API_BASE}/advertisers/{advertiser_id}/{spec['sub_path']}"

        if spec.get("advertiser_param"):
            advertiser_id = ctx.get("advertiser_id")
            if not advertiser_id:
                return {"options": [], "next_page_token": None}
            params["advertiserId"] = advertiser_id

        if field_name == "partner_id":
            # partners.list has no `filter`; fall back to client-side search.
            pass
        elif field_name == "advertiser_id":
            partner_id = ctx.get("partner_id")
            if not partner_id:
                # advertisers.list REQUIRES a partnerId, but advertiser-scoped
                # operations don't collect a partner — so we can't enumerate.
                # Be honest instead of returning a silently-empty list: the
                # field allows a pasted ID.
                raise ValueError(
                    "Listing advertisers needs a DV360 partner, which this "
                    "operation doesn't provide. Paste the advertiser ID directly, "
                    "or use “List Advertisers” (which takes a partner) to find it."
                )
            params["partnerId"] = partner_id
            if search:
                params["filter"] = f'displayName:"{search}"'

        result = await _dv360_request(
            access_token, "GET", url, params=params, action_name=spec["action"]
        )
        if result.get("status") != "success":
            code = result.get("status_code")
            detail = result.get("error") or "unknown error"
            hint = ""
            if code in (401, 403):
                hint = (
                    " — the connected Google account may not have Display & "
                    "Video 360 access for this resource, or the DV360 API isn't "
                    "enabled for the OAuth app."
                )
            raise ValueError(
                f"Couldn't load {field_name.replace('_', ' ')} from DV360: {detail}{hint}"
            )

        data = result.get("data") or {}
        rows = data.get(spec["list_key"]) or []
        id_key = spec["id_key"]
        options: List[Dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid = row.get(id_key)
            if rid is None:
                continue
            # Bid Manager queries carry their title under metadata.title.
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            name = row.get("displayName") or meta.get("title") or f"{rid}"
            options.append({"label": f"{name} ({rid})", "value": str(rid)})

        if search and field_name != "advertiser_id":
            from nodes.core.dynamic_options import filter_options_by_search

            options = filter_options_by_search(options, search)

        return {"options": options, "next_page_token": data.get("nextPageToken")}

    @classmethod
    async def _token_from_credential_data(cls, credential_data: Dict[str, Any]) -> Optional[str]:
        """Return a usable access token from a decrypted credential dict (OAuth or
        service account) — used by dropdown loaders."""
        return await _resolve_access_token_from_credential_data(credential_data)

    async def _ensure_fresh_token(self, credentials: DV360Credential) -> str:
        """Return a valid Google access token for either supported credential mode."""
        if isinstance(credentials, DV360ServiceAccountCredential):
            return await _mint_service_account_access_token(
                credentials.service_account_json
            )

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token

        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, DV360NodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect your Google DV360 account.")

        access_token = await self._ensure_fresh_token(credentials)

        handlers = {
            "list_advertisers": self._list_advertisers,
            "get_advertiser": self._get_advertiser,
            "create_advertiser": self._create_advertiser,
            "update_advertiser": self._update_advertiser,
            "list_campaigns": self._list_campaigns,
            "get_campaign": self._get_campaign,
            "create_campaign": self._create_campaign,
            "update_campaign": self._update_campaign,
            "list_insertion_orders": self._list_insertion_orders,
            "create_insertion_order": self._create_insertion_order,
            "update_insertion_order": self._update_insertion_order,
            "list_line_items": self._list_line_items,
            "get_line_item": self._get_line_item,
            "create_line_item": self._create_line_item,
            "update_line_item": self._update_line_item,
            "duplicate_line_item": self._duplicate_line_item,
            "list_creatives": self._list_creatives,
            "create_creative": self._create_creative,
            "update_creative": self._update_creative,
            "list_assigned_targeting": self._list_assigned_targeting,
            "create_assigned_targeting": self._create_assigned_targeting,
            "search_targeting_options": self._search_targeting_options,
            "list_channels": self._list_channels,
            "create_channel": self._create_channel,
            "list_audiences": self._list_audiences,
            "edit_customer_match_members": self._edit_customer_match_members,
            "create_report_query": self._create_report_query,
            "run_report_query": self._run_report_query,
            "get_insertion_order": self._get_insertion_order,
            "get_creative": self._get_creative,
            "get_channel": self._get_channel,
            "delete_line_item": self._delete_line_item,
            "delete_creative": self._delete_creative,
            "list_report_queries": self._list_report_queries,
            "get_report_query": self._get_report_query,
            "get_report": self._get_report,
            "on_job_completed": self._on_job_completed,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, access_token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Advertiser handlers
    # ------------------------------------------------------------------
    async def _list_advertisers(self, c: DV360ListAdvertisersConfig, token: str) -> Dict[str, Any]:
        params = {"partnerId": c.partner_id, "filter": c.filter, "pageSize": c.page_size}
        return await _dv360_request(
            token, "GET", f"{DV360_API_BASE}/advertisers", params=params, action_name="list_advertisers"
        )

    async def _get_advertiser(self, c: DV360GetAdvertiserConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token, "GET", f"{DV360_API_BASE}/advertisers/{c.advertiser_id}", action_name="get_advertiser"
        )

    async def _create_advertiser(self, c: DV360CreateAdvertiserConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.advertiser_body, "Advertiser JSON")
        return await _dv360_request(
            token, "POST", f"{DV360_API_BASE}/advertisers", json_body=body, action_name="create_advertiser"
        )

    async def _update_advertiser(self, c: DV360UpdateAdvertiserConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.advertiser_body, "Advertiser JSON")
        return await _dv360_request(
            token,
            "PATCH",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}",
            params={"updateMask": c.update_mask},
            json_body=body,
            action_name="update_advertiser",
        )

    # ------------------------------------------------------------------
    # Campaign handlers
    # ------------------------------------------------------------------
    async def _list_campaigns(self, c: DV360ListCampaignsConfig, token: str) -> Dict[str, Any]:
        params = {"filter": c.filter, "pageSize": c.page_size}
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/campaigns",
            params=params,
            action_name="list_campaigns",
        )

    async def _get_campaign(self, c: DV360GetCampaignConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/campaigns/{c.campaign_id}",
            action_name="get_campaign",
        )

    async def _create_campaign(self, c: DV360CreateCampaignConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.campaign_body, "Campaign JSON")
        return await _dv360_request(
            token,
            "POST",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/campaigns",
            json_body=body,
            action_name="create_campaign",
        )

    async def _update_campaign(self, c: DV360UpdateCampaignConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.campaign_body, "Campaign JSON")
        return await _dv360_request(
            token,
            "PATCH",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/campaigns/{c.campaign_id}",
            params={"updateMask": c.update_mask},
            json_body=body,
            action_name="update_campaign",
        )

    # ------------------------------------------------------------------
    # Insertion order handlers
    # ------------------------------------------------------------------
    async def _list_insertion_orders(self, c: DV360ListInsertionOrdersConfig, token: str) -> Dict[str, Any]:
        params = {"filter": c.filter, "pageSize": c.page_size}
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/insertionOrders",
            params=params,
            action_name="list_insertion_orders",
        )

    async def _create_insertion_order(self, c: DV360CreateInsertionOrderConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.insertion_order_body, "Insertion Order JSON")
        return await _dv360_request(
            token,
            "POST",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/insertionOrders",
            json_body=body,
            action_name="create_insertion_order",
        )

    async def _update_insertion_order(self, c: DV360UpdateInsertionOrderConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.insertion_order_body, "Insertion Order JSON")
        return await _dv360_request(
            token,
            "PATCH",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/insertionOrders/{c.insertion_order_id}",
            params={"updateMask": c.update_mask},
            json_body=body,
            action_name="update_insertion_order",
        )

    # ------------------------------------------------------------------
    # Line item handlers
    # ------------------------------------------------------------------
    async def _list_line_items(self, c: DV360ListLineItemsConfig, token: str) -> Dict[str, Any]:
        params = {"filter": c.filter, "pageSize": c.page_size}
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/lineItems",
            params=params,
            action_name="list_line_items",
        )

    async def _get_line_item(self, c: DV360GetLineItemConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/lineItems/{c.line_item_id}",
            action_name="get_line_item",
        )

    async def _create_line_item(self, c: DV360CreateLineItemConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.line_item_body, "Line Item JSON")
        return await _dv360_request(
            token,
            "POST",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/lineItems",
            json_body=body,
            action_name="create_line_item",
        )

    async def _update_line_item(self, c: DV360UpdateLineItemConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.line_item_body, "Line Item JSON")
        return await _dv360_request(
            token,
            "PATCH",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/lineItems/{c.line_item_id}",
            params={"updateMask": c.update_mask},
            json_body=body,
            action_name="update_line_item",
        )

    async def _duplicate_line_item(self, c: DV360DuplicateLineItemConfig, token: str) -> Dict[str, Any]:
        body = {"targetDisplayName": c.target_display_name} if c.target_display_name else {}
        return await _dv360_request(
            token,
            "POST",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/lineItems/{c.line_item_id}:duplicate",
            json_body=body,
            action_name="duplicate_line_item",
        )

    # ------------------------------------------------------------------
    # Creative handlers
    # ------------------------------------------------------------------
    async def _list_creatives(self, c: DV360ListCreativesConfig, token: str) -> Dict[str, Any]:
        params = {"filter": c.filter, "pageSize": c.page_size}
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/creatives",
            params=params,
            action_name="list_creatives",
        )

    async def _create_creative(self, c: DV360CreateCreativeConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.creative_body, "Creative JSON")
        return await _dv360_request(
            token,
            "POST",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/creatives",
            json_body=body,
            action_name="create_creative",
        )

    async def _update_creative(self, c: DV360UpdateCreativeConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.creative_body, "Creative JSON")
        return await _dv360_request(
            token,
            "PATCH",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/creatives/{c.creative_id}",
            params={"updateMask": c.update_mask},
            json_body=body,
            action_name="update_creative",
        )

    # ------------------------------------------------------------------
    # Targeting handlers
    # ------------------------------------------------------------------
    async def _list_assigned_targeting(self, c: DV360ListAssignedTargetingConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/lineItems/{c.line_item_id}"
            f"/targetingTypes/{c.targeting_type}/assignedTargetingOptions",
            action_name="list_assigned_targeting",
        )

    async def _create_assigned_targeting(self, c: DV360CreateAssignedTargetingConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.targeting_body, "Assigned Targeting JSON")
        return await _dv360_request(
            token,
            "POST",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/lineItems/{c.line_item_id}"
            f"/targetingTypes/{c.targeting_type}/assignedTargetingOptions",
            json_body=body,
            action_name="create_assigned_targeting",
        )

    async def _search_targeting_options(self, c: DV360SearchTargetingOptionsConfig, token: str) -> Dict[str, Any]:
        body = {"advertiserId": c.advertiser_id, "geoRegionSearchTerms": {"geoRegionQuery": c.query}}
        return await _dv360_request(
            token,
            "POST",
            f"{DV360_API_BASE}/targetingTypes/{c.targeting_type}/targetingOptions:search",
            json_body=body,
            action_name="search_targeting_options",
        )

    # ------------------------------------------------------------------
    # Channel handlers
    # ------------------------------------------------------------------
    async def _list_channels(self, c: DV360ListChannelsConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/channels",
            params={"pageSize": c.page_size},
            action_name="list_channels",
        )

    async def _create_channel(self, c: DV360CreateChannelConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "POST",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/channels",
            json_body={"displayName": c.display_name},
            action_name="create_channel",
        )

    # ------------------------------------------------------------------
    # Audience handlers
    # ------------------------------------------------------------------
    async def _list_audiences(self, c: DV360ListAudiencesConfig, token: str) -> Dict[str, Any]:
        params = {"advertiserId": c.advertiser_id, "pageSize": c.page_size}
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/firstPartyAndPartnerAudiences",
            params=params,
            action_name="list_audiences",
        )

    async def _edit_customer_match_members(self, c: DV360EditCustomerMatchConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.edit_body, "Edit JSON")
        body.setdefault("advertiserId", c.advertiser_id)
        return await _dv360_request(
            token,
            "POST",
            f"{DV360_API_BASE}/firstPartyAndPartnerAudiences/{c.audience_id}:editCustomerMatchMembers",
            json_body=body,
            action_name="edit_customer_match_members",
        )

    # ------------------------------------------------------------------
    # Reporting (Bid Manager) handlers
    # ------------------------------------------------------------------
    async def _create_report_query(self, c: DV360CreateReportQueryConfig, token: str) -> Dict[str, Any]:
        body = _parse_json_body(c.query_body, "Query JSON")
        return await _dv360_request(
            token, "POST", f"{BID_MANAGER_API_BASE}/queries", json_body=body, action_name="create_report_query"
        )

    async def _run_report_query(self, c: DV360RunReportQueryConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "POST",
            f"{BID_MANAGER_API_BASE}/queries/{c.query_id}:run",
            json_body={},
            action_name="run_report_query",
        )

    # ------------------------------------------------------------------
    # Additional read/CRUD handlers
    # ------------------------------------------------------------------
    async def _get_insertion_order(
        self, c: DV360GetInsertionOrderConfig, token: str
    ) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/insertionOrders/{c.insertion_order_id}",
            action_name="get_insertion_order",
        )

    async def _get_creative(self, c: DV360GetCreativeConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/creatives/{c.creative_id}",
            action_name="get_creative",
        )

    async def _get_channel(self, c: DV360GetChannelConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "GET",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/channels/{c.channel_id}",
            action_name="get_channel",
        )

    async def _delete_line_item(
        self, c: DV360DeleteLineItemConfig, token: str
    ) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "DELETE",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/lineItems/{c.line_item_id}",
            action_name="delete_line_item",
        )

    async def _delete_creative(
        self, c: DV360DeleteCreativeConfig, token: str
    ) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "DELETE",
            f"{DV360_API_BASE}/advertisers/{c.advertiser_id}/creatives/{c.creative_id}",
            action_name="delete_creative",
        )

    async def _list_report_queries(
        self, c: DV360ListReportQueriesConfig, token: str
    ) -> Dict[str, Any]:
        params = {"pageSize": c.page_size, "pageToken": c.page_token}
        return await _dv360_request(
            token,
            "GET",
            f"{BID_MANAGER_API_BASE}/queries",
            params=params,
            action_name="list_report_queries",
        )

    async def _get_report_query(
        self, c: DV360GetReportQueryConfig, token: str
    ) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "GET",
            f"{BID_MANAGER_API_BASE}/queries/{c.query_id}",
            action_name="get_report_query",
        )

    async def _get_report(self, c: DV360GetReportConfig, token: str) -> Dict[str, Any]:
        return await _dv360_request(
            token,
            "GET",
            f"{BID_MANAGER_API_BASE}/queries/{c.query_id}/reports/{c.report_id}",
            action_name="get_report",
        )

    # ------------------------------------------------------------------
    # Trigger (poll-based) handler
    # ------------------------------------------------------------------
    @staticmethod
    def _report_id(report: Dict[str, Any]) -> Optional[str]:
        """Extract the report id from a Bid Manager report run resource."""
        key = report.get("key") if isinstance(report.get("key"), dict) else {}
        rid = key.get("reportId") or report.get("reportId")
        return str(rid) if rid is not None else None

    @staticmethod
    def _is_done(report: Dict[str, Any]) -> bool:
        """A report run is complete when its metadata.status.state is DONE."""
        meta = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
        status = meta.get("status") if isinstance(meta.get("status"), dict) else {}
        return status.get("state") == "DONE"

    async def _on_job_completed(self, c: DV360OnJobCompletedConfig, token: str) -> Dict[str, Any]:
        """Poll a query's report runs and emit each newly completed (DONE) run.

        Dedup cursor: ``last_seen_id`` holds the highest report id already
        emitted. We emit only DONE reports whose id is greater, then advance the
        cursor to the new maximum so finished runs never re-fire."""
        result = await _dv360_request(
            token,
            "GET",
            f"{BID_MANAGER_API_BASE}/queries/{c.query_id}/reports",
            params={"pageSize": c.page_size},
            action_name="list_query_reports",
        )
        if result.get("status") != "success":
            return result

        reports = (result.get("data") or {}).get("reports") or []

        def _id_sort_key(rid: str) -> tuple:
            # Report ids are numeric strings; sort numerically when possible.
            return (0, int(rid)) if rid.isdigit() else (1, rid)

        last_seen = c.last_seen_id

        new_items: List[Dict[str, Any]] = []
        for report in reports:
            if not isinstance(report, dict) or not self._is_done(report):
                continue
            rid = self._report_id(report)
            if rid is None:
                continue
            if last_seen is not None and _id_sort_key(rid) <= _id_sort_key(last_seen):
                continue
            new_items.append(report)

        new_items.sort(key=lambda r: _id_sort_key(self._report_id(r) or ""))

        new_cursor = last_seen
        for report in new_items:
            rid = self._report_id(report)
            if rid is not None and (
                new_cursor is None or _id_sort_key(rid) > _id_sort_key(new_cursor)
            ):
                new_cursor = rid

        return {
            "status": "success",
            "operation": "on_job_completed",
            "query_id": c.query_id,
            "new_count": len(new_items),
            "items": new_items,
            "last_seen_id": new_cursor,
            "timestamp": time.time(),
        }
