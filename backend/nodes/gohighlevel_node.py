"""
GoHighLevel (LeadConnector) API v2 automation node.

Full coverage of the stable HighLevel REST API v2 across ~40 resource groups
(contacts, conversations, opportunities, calendars, invoices, payments,
products, funnels, forms, social posting, blogs, custom objects, locations,
users, and more), generated from HighLevel's official OpenAPI specs
(github.com/GoHighLevel/highlevel-api-docs).

Authentication: **Private Integration Token (PIT)** — a self-serve Bearer token
created in the agency/sub-account settings (Settings → Private Integrations). No
marketplace app or OAuth approval is required. Every request carries
`Authorization: Bearer <token>` + a `Version` header (default 2021-07-28).

Base URL: https://services.leadconnectorhq.com
Docs: https://marketplace.gohighlevel.com/docs
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, create_model
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

GHL_BASE_URL = "https://services.leadconnectorhq.com"
GHL_DEFAULT_VERSION = "2021-07-28"


# ============================================================================
# Coercion helpers (shared by the generated control-plane handlers)
# ============================================================================


def _ghl_bool(v):
    """Optional string-enum ('true'/'false') -> bool, or None if unset."""
    return None if v in (None, "") else str(v).lower() == "true"


def _ghl_int(v):
    """Optional string -> int, or None if unset / non-numeric."""
    return int(v) if v not in (None, "") and str(v).lstrip("-").isdigit() else None


def _ghl_num(v):
    """Optional string -> int or float, or None if unset / non-numeric."""
    if v in (None, ""):
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def _ghl_json(v):
    """Optional JSON-string field -> parsed value, or None if unset. Raises a
    clean ValueError on malformed JSON so a bad input surfaces as a node error."""
    if v in (None, ""):
        return None
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"Invalid JSON in field: {e}")


def _ghl_csv(v):
    """Optional comma-separated string -> list of trimmed values, or None."""
    if v in (None, ""):
        return None
    return [s.strip() for s in str(v).split(",") if s.strip()]


# ============================================================================
# Credential Schema
# ============================================================================


class GoHighLevelPitCredential(BaseModel):
    """Private Integration Token credential for GoHighLevel (LeadConnector).

    A PIT is created in the agency or sub-account under
    Settings → Private Integrations. It is a static Bearer token (no OAuth flow,
    no refresh) whose scopes are chosen at creation. A location-level PIT is
    bound to one sub-account; an agency-level PIT can act across sub-accounts
    (pass the target `locationId` on each operation).
    """

    credential_type: Literal["gohighlevel_pit"] = Field(
        "gohighlevel_pit", json_schema_extra={"ui:hidden": True}
    )
    token: str = Field(
        ...,
        title="Private Integration Token",
        description=(
            "A Private Integration Token from Settings → Private Integrations "
            "in your GoHighLevel agency or sub-account. Grant the scopes the "
            "operations you use require."
        ),
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://help.leadconnectorhq.com/support/solutions/articles/155000002774-private-integrations-everything-you-need-to-know",
            "x-credential-instructions": (
                "In GoHighLevel go to Settings → Private Integrations → Create "
                "new Integration, choose the scopes you need, and copy the token."
            ),
        }
    )


GoHighLevelCredential = GoHighLevelPitCredential


# ============================================================================
# HTTP Request Helper
# ============================================================================


async def _ghl_request(
    token: str,
    method: str,
    endpoint: str,
    version: str = GHL_DEFAULT_VERSION,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
    files: Optional[Any] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make an authenticated GoHighLevel REST API v2 request.

    HighLevel returns 200/201 with a JSON body on success and 204 for some
    deletes. Errors are NestJS-shaped: {statusCode, message, error} (message may
    be a string or a list). The `Version` header is required on every call.
    """
    url = f"{GHL_BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": version,
        "Accept": "application/json",
        "User-Agent": "NoClick-Workflow/1.0",
    }
    if files is None and data is None:
        headers["Content-Type"] = "application/json"
    if isinstance(json_body, dict):
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params,
                json=json_body if (files is None and data is None) else None,
                files=files, data=data,
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("message") or err.get("error") or str(err)
                    if isinstance(message, list):
                        message = "; ".join(str(m) for m in message)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[GoHighLevelNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204 or not response.content:
                data_out: Any = {"success": True}
            else:
                try:
                    data_out = response.json()
                except Exception:
                    data_out = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data_out,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error", "action": action_name, "error": "Request timed out",
                "status_code": 408, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[GoHighLevelNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error", "action": action_name, "error": msg,
                "status_code": 500, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Generated operation registry (full HighLevel REST API v2)
# ============================================================================
# Each block below (one per resource group, generated from the official OpenAPI
# spec) defines Pydantic config classes + module-level handlers
# `async def _fn(node, c, token)` and registers them into these two collections;
# the discriminated union and execute() dispatch pick them up automatically. Op
# names are globally unique.
GHL_OPERATION_CONFIGS: List[type] = []
GHL_OPERATION_HANDLERS: Dict[str, Any] = {}

# Generated control-plane operations (full HighLevel REST API v2), one block per
# resource group. Each appends config classes to GHL_OPERATION_CONFIGS and
# module-level handlers to GHL_OPERATION_HANDLERS.
# ---- ad_manager.py ----
class GHLFbGetReportingConfig(BaseModel):
    """Get reporting data"""

    operation: Literal["fb_get_reporting"] = Field(
        "fb_get_reporting",
        json_schema_extra={
            "const": "fb_get_reporting", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get reporting data",
        },
        title="Get reporting data",
    )
    location_id: str = Field(..., title="Location Id")
    group_by: str = Field(..., title="Group By", json_schema_extra={"enum": ["day", "week", "month"], "x-enum-searchable": True})
    start_date: str = Field(..., title="Start Date")
    end_date: str = Field(..., title="End Date")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["AD_MANAGER", "INTEGRATION"], "x-enum-searchable": True})
    fields: str = Field(..., title="Fields")


class GHLFbGetCampaignReportingConfig(BaseModel):
    """Get campaign reporting"""

    operation: Literal["fb_get_campaign_reporting"] = Field(
        "fb_get_campaign_reporting",
        json_schema_extra={
            "const": "fb_get_campaign_reporting", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get campaign reporting",
        },
        title="Get campaign reporting",
    )
    campaign_id: str = Field(..., title="Campaign Id")
    location_id: str = Field(..., title="Location Id")
    start_date: str = Field(..., title="Start Date")
    end_date: str = Field(..., title="End Date")


class GHLFbGetReportingListConfig(BaseModel):
    """Get reporting list"""

    operation: Literal["fb_get_reporting_list"] = Field(
        "fb_get_reporting_list",
        json_schema_extra={
            "const": "fb_get_reporting_list", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get reporting list",
        },
        title="Get reporting list",
    )
    location_id: str = Field(..., title="Location Id")
    list_type: str = Field(..., title="List Type")
    start_date: str = Field(..., title="Start Date")
    end_date: str = Field(..., title="End Date")
    campaign_id: str = Field(..., title="Campaign Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["AD_MANAGER", "INTEGRATION"], "x-enum-searchable": True})


class GHLFbGetCurrentUserConfig(BaseModel):
    """Get current Facebook user"""

    operation: Literal["fb_get_current_user"] = Field(
        "fb_get_current_user",
        json_schema_extra={
            "const": "fb_get_current_user", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get current Facebook user",
        },
        title="Get current Facebook user",
    )
    location_id: str = Field(..., title="Location Id")


class GHLFbGetPagesConfig(BaseModel):
    """Get Facebook pages"""

    operation: Literal["fb_get_pages"] = Field(
        "fb_get_pages",
        json_schema_extra={
            "const": "fb_get_pages", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get Facebook pages",
        },
        title="Get Facebook pages",
    )
    location_id: str = Field(..., title="Location Id")
    fetch_existing: Optional[str] = Field(None, title="Fetch Existing")


class GHLFbGetInstagramAccountsConfig(BaseModel):
    """Get Instagram accounts for page"""

    operation: Literal["fb_get_instagram_accounts"] = Field(
        "fb_get_instagram_accounts",
        json_schema_extra={
            "const": "fb_get_instagram_accounts", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get Instagram accounts for page",
        },
        title="Get Instagram accounts for page",
    )
    page_id: str = Field(..., title="Page Id")
    location_id: str = Field(..., title="Location Id")
    type: Optional[str] = Field(None, title="Type", json_schema_extra={"enum": ["INTEGRATION", "AD_MANAGER"], "x-enum-searchable": True})


class GHLFbGetPageLeadFormsConfig(BaseModel):
    """Get page lead forms"""

    operation: Literal["fb_get_page_lead_forms"] = Field(
        "fb_get_page_lead_forms",
        json_schema_extra={
            "const": "fb_get_page_lead_forms", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get page lead forms",
        },
        title="Get page lead forms",
    )
    page_id: str = Field(..., title="Page Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbCreatePageLeadFormConfig(BaseModel):
    """Create page lead form"""

    operation: Literal["fb_create_page_lead_form"] = Field(
        "fb_create_page_lead_form",
        json_schema_extra={
            "const": "fb_create_page_lead_form", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Create page lead form",
        },
        title="Create page lead form",
    )
    page_id: str = Field(..., title="Page Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["MORE_VOLUME", "HIGHER_INTENT"], "x-enum-searchable": True})
    name: str = Field(..., title="Name")
    location_id: str = Field(..., title="Location Id")
    greeting_card: Optional[str] = Field(None, title="Greeting Card", description="JSON")
    questions: Optional[str] = Field(None, title="Questions", description="JSON")
    question_page_headline: Optional[str] = Field(None, title="Question Page Headline")
    privacy_policy_link: str = Field(..., title="Privacy Policy Link")
    privacy_policy_text: Optional[str] = Field(None, title="Privacy Policy Text")
    custom_disclaimer: Optional[str] = Field(None, title="Custom Disclaimer", description="JSON")
    thank_you_page: Optional[str] = Field(None, title="Thank You Page", description="JSON")


class GHLFbGetAdAccountsConfig(BaseModel):
    """Get ad accounts"""

    operation: Literal["fb_get_ad_accounts"] = Field(
        "fb_get_ad_accounts",
        json_schema_extra={
            "const": "fb_get_ad_accounts", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get ad accounts",
        },
        title="Get ad accounts",
    )
    location_id: str = Field(..., title="Location Id")
    type: Optional[str] = Field(None, title="Type")
    next: Optional[str] = Field(None, title="Next")
    fetch_all: Optional[str] = Field(None, title="Fetch All")
    limit: Optional[str] = Field(None, title="Limit")


class GHLFbGetAdAccountConfig(BaseModel):
    """Get ad account details"""

    operation: Literal["fb_get_ad_account"] = Field(
        "fb_get_ad_account",
        json_schema_extra={
            "const": "fb_get_ad_account", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get ad account details",
        },
        title="Get ad account details",
    )
    ad_account_id: str = Field(..., title="Ad Account Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbDeleteAdAccountConfig(BaseModel):
    """Delete ad account"""

    operation: Literal["fb_delete_ad_account"] = Field(
        "fb_delete_ad_account",
        json_schema_extra={
            "const": "fb_delete_ad_account", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete ad account",
        },
        title="Delete ad account",
    )
    ad_account_id: str = Field(..., title="Ad Account Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbGetConversationFormsConfig(BaseModel):
    """Get conversation forms"""

    operation: Literal["fb_get_conversation_forms"] = Field(
        "fb_get_conversation_forms",
        json_schema_extra={
            "const": "fb_get_conversation_forms", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get conversation forms",
        },
        title="Get conversation forms",
    )
    location_id: str = Field(..., title="Location Id")


class GHLFbCreateConversationFormConfig(BaseModel):
    """Create conversation form"""

    operation: Literal["fb_create_conversation_form"] = Field(
        "fb_create_conversation_form",
        json_schema_extra={
            "const": "fb_create_conversation_form", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Create conversation form",
        },
        title="Create conversation form",
    )
    location_id: str = Field(..., title="Location Id")
    name: str = Field(..., title="Name")
    text: str = Field(..., title="Text")
    questions: Optional[str] = Field(None, title="Questions", description="JSON")


class GHLFbCreateIntegrationConfig(BaseModel):
    """Create Facebook integration"""

    operation: Literal["fb_create_integration"] = Field(
        "fb_create_integration",
        json_schema_extra={
            "const": "fb_create_integration", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Create Facebook integration",
        },
        title="Create Facebook integration",
    )
    location_id: str = Field(..., title="Location Id")
    page_id: str = Field(..., title="Page Id")
    ad_account_id: Optional[str] = Field(None, title="Ad Account Id")


class GHLFbGetIntegrationConfig(BaseModel):
    """Get Facebook integration"""

    operation: Literal["fb_get_integration"] = Field(
        "fb_get_integration",
        json_schema_extra={
            "const": "fb_get_integration", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get Facebook integration",
        },
        title="Get Facebook integration",
    )
    location_id: str = Field(..., title="Location Id")


class GHLFbDeleteIntegrationConfig(BaseModel):
    """Delete Facebook integration"""

    operation: Literal["fb_delete_integration"] = Field(
        "fb_delete_integration",
        json_schema_extra={
            "const": "fb_delete_integration", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete Facebook integration",
        },
        title="Delete Facebook integration",
    )
    location_id: str = Field(..., title="Location Id")


class GHLFbSearchTargetingConfig(BaseModel):
    """Search targeting options"""

    operation: Literal["fb_search_targeting"] = Field(
        "fb_search_targeting",
        json_schema_extra={
            "const": "fb_search_targeting", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Search targeting options",
        },
        title="Search targeting options",
    )
    type: str = Field(..., title="Type")
    query: str = Field(..., title="Query")
    search_type: Optional[str] = Field(None, title="Search Type")


class GHLFbPublishCampaignConfig(BaseModel):
    """Publish campaign"""

    operation: Literal["fb_publish_campaign"] = Field(
        "fb_publish_campaign",
        json_schema_extra={
            "const": "fb_publish_campaign", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Publish campaign",
        },
        title="Publish campaign",
    )
    campaign_id: str = Field(..., title="Campaign Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbDeletePageConfig(BaseModel):
    """Delete page connection"""

    operation: Literal["fb_delete_page"] = Field(
        "fb_delete_page",
        json_schema_extra={
            "const": "fb_delete_page", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete page connection",
        },
        title="Delete page connection",
    )
    location_id: str = Field(..., title="Location Id")
    page_id: str = Field(..., title="Page Id")


class GHLFbGetPixelsConfig(BaseModel):
    """Get conversion pixels"""

    operation: Literal["fb_get_pixels"] = Field(
        "fb_get_pixels",
        json_schema_extra={
            "const": "fb_get_pixels", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get conversion pixels",
        },
        title="Get conversion pixels",
    )
    location_id: str = Field(..., title="Location Id")
    channel: Optional[str] = Field(None, title="Channel")
    page_id: Optional[str] = Field(None, title="Page Id")
    ig_user_id: Optional[str] = Field(None, title="Ig User Id")


class GHLFbUpsertPixelConfig(BaseModel):
    """Upsert conversion pixel"""

    operation: Literal["fb_upsert_pixel"] = Field(
        "fb_upsert_pixel",
        json_schema_extra={
            "const": "fb_upsert_pixel", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert conversion pixel",
        },
        title="Upsert conversion pixel",
    )
    location_id: str = Field(..., title="Location Id")
    conversion_pixel_id: Optional[str] = Field(None, title="Conversion Pixel Id")
    name: Optional[str] = Field(None, title="Name")
    ig_user_id: Optional[str] = Field(None, title="Ig User Id")
    type: str = Field(..., title="Type")


class GHLFbGetCustomAudiencesConfig(BaseModel):
    """Get custom audiences"""

    operation: Literal["fb_get_custom_audiences"] = Field(
        "fb_get_custom_audiences",
        json_schema_extra={
            "const": "fb_get_custom_audiences", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get custom audiences",
        },
        title="Get custom audiences",
    )
    location_id: str = Field(..., title="Location Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["lookalike", "custom", "all"], "x-enum-searchable": True})
    source: Optional[str] = Field(None, title="Source", json_schema_extra={"enum": ["ad_manager", "integration"], "x-enum-searchable": True})
    ad_account_id: str = Field(..., title="Ad Account Id")


class GHLFbDeleteCustomAudienceConfig(BaseModel):
    """Delete custom audience"""

    operation: Literal["fb_delete_custom_audience"] = Field(
        "fb_delete_custom_audience",
        json_schema_extra={
            "const": "fb_delete_custom_audience", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete custom audience",
        },
        title="Delete custom audience",
    )
    audience_id: str = Field(..., title="Audience Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbUpdateCustomAudienceConfig(BaseModel):
    """Update custom audience"""

    operation: Literal["fb_update_custom_audience"] = Field(
        "fb_update_custom_audience",
        json_schema_extra={
            "const": "fb_update_custom_audience", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Update custom audience",
        },
        title="Update custom audience",
    )
    audience_id: str = Field(..., title="Audience Id")
    location_id: str = Field(..., title="Location Id")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")


class GHLFbGetCustomAudienceByIdConfig(BaseModel):
    """Get custom audience by ID"""

    operation: Literal["fb_get_custom_audience_by_id"] = Field(
        "fb_get_custom_audience_by_id",
        json_schema_extra={
            "const": "fb_get_custom_audience_by_id", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get custom audience by ID",
        },
        title="Get custom audience by ID",
    )
    audience_id: str = Field(..., title="Audience Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbAddCustomAudienceMemberConfig(BaseModel):
    """Add custom audience member"""

    operation: Literal["fb_add_custom_audience_member"] = Field(
        "fb_add_custom_audience_member",
        json_schema_extra={
            "const": "fb_add_custom_audience_member", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Add custom audience member",
        },
        title="Add custom audience member",
    )
    audience_id: str = Field(..., title="Audience Id")
    location_id: str = Field(..., title="Location Id")
    contact_id: str = Field(..., title="Contact Id")
    fb_ad_account_id: Optional[str] = Field(None, title="Fb Ad Account Id")


class GHLFbRemoveCustomAudienceMemberConfig(BaseModel):
    """Remove custom audience member"""

    operation: Literal["fb_remove_custom_audience_member"] = Field(
        "fb_remove_custom_audience_member",
        json_schema_extra={
            "const": "fb_remove_custom_audience_member", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Remove custom audience member",
        },
        title="Remove custom audience member",
    )
    audience_id: str = Field(..., title="Audience Id")
    location_id: str = Field(..., title="Location Id")
    contact_id: str = Field(..., title="Contact Id")
    fb_ad_account_id: Optional[str] = Field(None, title="Fb Ad Account Id")


class GHLFbBatchUpdateAudienceMembersConfig(BaseModel):
    """Batch update audience members"""

    operation: Literal["fb_batch_update_audience_members"] = Field(
        "fb_batch_update_audience_members",
        json_schema_extra={
            "const": "fb_batch_update_audience_members", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Batch update audience members",
        },
        title="Batch update audience members",
    )
    audience_id: str = Field(..., title="Audience Id")
    location_id: str = Field(..., title="Location Id")
    csv_path: Optional[str] = Field(None, title="Csv Path")
    operation_type: str = Field(..., title="Operation Type")
    smartlist_ids: Optional[str] = Field(None, title="Smartlist Ids", description="Comma-separated list")
    dynamic_audience: Optional[str] = Field(None, title="Dynamic Audience")


class GHLFbSetDefaultPageConfig(BaseModel):
    """Set default page"""

    operation: Literal["fb_set_default_page"] = Field(
        "fb_set_default_page",
        json_schema_extra={
            "const": "fb_set_default_page", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Set default page",
        },
        title="Set default page",
    )
    location_id: str = Field(..., title="Location Id")
    page_id: str = Field(..., title="Page Id")


class GHLFbGetLeadFormConfig(BaseModel):
    """Get lead form by ID"""

    operation: Literal["fb_get_lead_form"] = Field(
        "fb_get_lead_form",
        json_schema_extra={
            "const": "fb_get_lead_form", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get lead form by ID",
        },
        title="Get lead form by ID",
    )
    lead_form_id: str = Field(..., title="Lead Form Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbGetCampaignConfig(BaseModel):
    """Get campaign with linked entities"""

    operation: Literal["fb_get_campaign"] = Field(
        "fb_get_campaign",
        json_schema_extra={
            "const": "fb_get_campaign", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get campaign with linked entities",
        },
        title="Get campaign with linked entities",
    )
    campaign_id: str = Field(..., title="Campaign Id")
    location_id: str = Field(..., title="Location Id")
    fields: Optional[str] = Field(None, title="Fields")
    source: Optional[str] = Field(None, title="Source")


class GHLFbGetEntityConfig(BaseModel):
    """Get entities"""

    operation: Literal["fb_get_entity"] = Field(
        "fb_get_entity",
        json_schema_extra={
            "const": "fb_get_entity", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get entities",
        },
        title="Get entities",
    )
    location_id: str = Field(..., title="Location Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["AD_MANAGER", "INTEGRATION"], "x-enum-searchable": True})
    next: Optional[str] = Field(None, title="Next")
    fetch_all: Optional[str] = Field(None, title="Fetch All")
    campaign_id: Optional[str] = Field(None, title="Campaign Id")
    ad_set_id: Optional[str] = Field(None, title="Ad Set Id")
    entity_type: str = Field(..., title="Entity Type", json_schema_extra={"enum": ["CAMPAIGN", "ADSET", "AD"], "x-enum-searchable": True})
    search_id: Optional[str] = Field(None, title="Search Id")
    selected_ad_account_id: Optional[str] = Field(None, title="Selected Ad Account Id")


class GHLFbUpsertCampaignConfig(BaseModel):
    """Upsert campaign"""

    operation: Literal["fb_upsert_campaign"] = Field(
        "fb_upsert_campaign",
        json_schema_extra={
            "const": "fb_upsert_campaign", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert campaign",
        },
        title="Upsert campaign",
    )
    id: Optional[str] = Field(None, title="Id")
    location_id: str = Field(..., title="Location Id")
    name: Optional[str] = Field(None, title="Name")
    objective: Optional[str] = Field(None, title="Objective", json_schema_extra={"enum": ["OUTCOME_LEADS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT", "OUTCOME_SALES"], "x-enum-searchable": True})
    special_ad_categories: Optional[str] = Field(None, title="Special Ad Categories", json_schema_extra={"enum": ["EMPLOYMENT", "CREDIT", "FINANCIAL_PRODUCTS_SERVICES", "HOUSING", "ISSUES_ELECTIONS_POLITICS", "ONLINE_GAMBLING_AND_GAMING", "NONE"], "x-enum-searchable": True})
    source: Optional[str] = Field(None, title="Source")


class GHLFbUpsertAdsetConfig(BaseModel):
    """Upsert adset"""

    operation: Literal["fb_upsert_adset"] = Field(
        "fb_upsert_adset",
        json_schema_extra={
            "const": "fb_upsert_adset", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert adset",
        },
        title="Upsert adset",
    )
    id: Optional[str] = Field(None, title="Id")
    location_id: str = Field(..., title="Location Id")
    name: Optional[str] = Field(None, title="Name")
    page_id: Optional[str] = Field(None, title="Page Id")
    instagram_actor_id: Optional[str] = Field(None, title="Instagram Actor Id")
    messaging_platforms: Optional[str] = Field(None, title="Messaging Platforms", json_schema_extra={"enum": ["WHATSAPP", "MESSENGER", "INSTAGRAM_DIRECT"], "x-enum-searchable": True})
    whatsapp_number: Optional[str] = Field(None, title="Whatsapp Number")
    audience: Optional[str] = Field(None, title="Audience", description="JSON")
    budget: Optional[str] = Field(None, title="Budget", description="JSON")
    conversion_location: Optional[str] = Field(None, title="Conversion Location")
    custom_event_type: Optional[str] = Field(None, title="Custom Event Type")
    pixel_id: Optional[str] = Field(None, title="Pixel Id")
    campaign_id: str = Field(..., title="Campaign Id")


class GHLFbUpsertAdConfig(BaseModel):
    """Upsert ad"""

    operation: Literal["fb_upsert_ad"] = Field(
        "fb_upsert_ad",
        json_schema_extra={
            "const": "fb_upsert_ad", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert ad",
        },
        title="Upsert ad",
    )
    id: Optional[str] = Field(None, title="Id")
    location_id: str = Field(..., title="Location Id")
    name: Optional[str] = Field(None, title="Name")
    primary_text: Optional[str] = Field(None, title="Primary Text")
    headline: Optional[str] = Field(None, title="Headline")
    description: Optional[str] = Field(None, title="Description")
    image_url: Optional[str] = Field(None, title="Image Url")
    media_type: Optional[str] = Field(None, title="Media Type", json_schema_extra={"enum": ["SINGLE", "CAROUSEL"], "x-enum-searchable": True})
    media: Optional[str] = Field(None, title="Media", description="JSON")
    multi_advertiser_ads: Optional[str] = Field(None, title="Multi Advertiser Ads", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    campaign_id: str = Field(..., title="Campaign Id")
    adset_id: str = Field(..., title="Adset Id")
    cta: Optional[str] = Field(None, title="Cta")
    conversation_form_id: Optional[str] = Field(None, title="Conversation Form Id")
    destination_link: Optional[str] = Field(None, title="Destination Link")
    destination_form_id: Optional[str] = Field(None, title="Destination Form Id")


class GHLFbPauseCampaignConfig(BaseModel):
    """Pause campaign"""

    operation: Literal["fb_pause_campaign"] = Field(
        "fb_pause_campaign",
        json_schema_extra={
            "const": "fb_pause_campaign", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Pause campaign",
        },
        title="Pause campaign",
    )
    campaign_id: str = Field(..., title="Campaign Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbResumeCampaignConfig(BaseModel):
    """Resume campaign"""

    operation: Literal["fb_resume_campaign"] = Field(
        "fb_resume_campaign",
        json_schema_extra={
            "const": "fb_resume_campaign", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Resume campaign",
        },
        title="Resume campaign",
    )
    campaign_id: str = Field(..., title="Campaign Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbDuplicateCampaignConfig(BaseModel):
    """Duplicate campaign"""

    operation: Literal["fb_duplicate_campaign"] = Field(
        "fb_duplicate_campaign",
        json_schema_extra={
            "const": "fb_duplicate_campaign", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Duplicate campaign",
        },
        title="Duplicate campaign",
    )
    campaign_id: str = Field(..., title="Campaign Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbDeleteCampaignConfig(BaseModel):
    """Delete campaign"""

    operation: Literal["fb_delete_campaign"] = Field(
        "fb_delete_campaign",
        json_schema_extra={
            "const": "fb_delete_campaign", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete campaign",
        },
        title="Delete campaign",
    )
    campaign_id: str = Field(..., title="Campaign Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbPauseAdsetConfig(BaseModel):
    """Pause ad set"""

    operation: Literal["fb_pause_adset"] = Field(
        "fb_pause_adset",
        json_schema_extra={
            "const": "fb_pause_adset", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Pause ad set",
        },
        title="Pause ad set",
    )
    adset_id: str = Field(..., title="Adset Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbResumeAdsetConfig(BaseModel):
    """Resume ad set"""

    operation: Literal["fb_resume_adset"] = Field(
        "fb_resume_adset",
        json_schema_extra={
            "const": "fb_resume_adset", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Resume ad set",
        },
        title="Resume ad set",
    )
    adset_id: str = Field(..., title="Adset Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbDuplicateAdsetConfig(BaseModel):
    """Duplicate ad set"""

    operation: Literal["fb_duplicate_adset"] = Field(
        "fb_duplicate_adset",
        json_schema_extra={
            "const": "fb_duplicate_adset", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Duplicate ad set",
        },
        title="Duplicate ad set",
    )
    adset_id: str = Field(..., title="Adset Id")


class GHLFbDeleteAdsetConfig(BaseModel):
    """Delete ad set"""

    operation: Literal["fb_delete_adset"] = Field(
        "fb_delete_adset",
        json_schema_extra={
            "const": "fb_delete_adset", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete ad set",
        },
        title="Delete ad set",
    )
    adset_id: str = Field(..., title="Adset Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbPauseAdConfig(BaseModel):
    """Pause ad"""

    operation: Literal["fb_pause_ad"] = Field(
        "fb_pause_ad",
        json_schema_extra={
            "const": "fb_pause_ad", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Pause ad",
        },
        title="Pause ad",
    )
    ad_id: str = Field(..., title="Ad Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbResumeAdConfig(BaseModel):
    """Resume ad"""

    operation: Literal["fb_resume_ad"] = Field(
        "fb_resume_ad",
        json_schema_extra={
            "const": "fb_resume_ad", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Resume ad",
        },
        title="Resume ad",
    )
    ad_id: str = Field(..., title="Ad Id")
    location_id: str = Field(..., title="Location Id")


class GHLFbDuplicateAdConfig(BaseModel):
    """Duplicate ad"""

    operation: Literal["fb_duplicate_ad"] = Field(
        "fb_duplicate_ad",
        json_schema_extra={
            "const": "fb_duplicate_ad", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Duplicate ad",
        },
        title="Duplicate ad",
    )
    ad_id: str = Field(..., title="Ad Id")


class GHLFbDeleteAdConfig(BaseModel):
    """Delete ad"""

    operation: Literal["fb_delete_ad"] = Field(
        "fb_delete_ad",
        json_schema_extra={
            "const": "fb_delete_ad", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete ad",
        },
        title="Delete ad",
    )
    ad_id: str = Field(..., title="Ad Id")
    location_id: str = Field(..., title="Location Id")


class GHLGoogleGetReportingConfig(BaseModel):
    """Get reporting data"""

    operation: Literal["google_get_reporting"] = Field(
        "google_get_reporting",
        json_schema_extra={
            "const": "google_get_reporting", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get reporting data",
        },
        title="Get reporting data",
    )
    location_id: str = Field(..., title="Location Id")
    group_by: Optional[str] = Field(None, title="Group By", json_schema_extra={"enum": ["date", "week", "month"], "x-enum-searchable": True})
    start_date: str = Field(..., title="Start Date")
    end_date: str = Field(..., title="End Date")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["AD_MANAGER", "INTEGRATION"], "x-enum-searchable": True})
    fields: str = Field(..., title="Fields")


class GHLGoogleGetReportingListConfig(BaseModel):
    """Get reporting list"""

    operation: Literal["google_get_reporting_list"] = Field(
        "google_get_reporting_list",
        json_schema_extra={
            "const": "google_get_reporting_list", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get reporting list",
        },
        title="Get reporting list",
    )
    location_id: str = Field(..., title="Location Id")
    list_type: str = Field(..., title="List Type")
    start_date: str = Field(..., title="Start Date")
    end_date: str = Field(..., title="End Date")
    campaign_id: Optional[str] = Field(None, title="Campaign Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["AD_MANAGER", "INTEGRATION"], "x-enum-searchable": True})


class GHLGoogleGetCampaignReportingConfig(BaseModel):
    """Get campaign reporting"""

    operation: Literal["google_get_campaign_reporting"] = Field(
        "google_get_campaign_reporting",
        json_schema_extra={
            "const": "google_get_campaign_reporting", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get campaign reporting",
        },
        title="Get campaign reporting",
    )
    campaign_id: str = Field(..., title="Campaign Id")
    location_id: str = Field(..., title="Location Id")
    start_date: str = Field(..., title="Start Date")
    end_date: str = Field(..., title="End Date")


class GHLGoogleGetConversionsConfig(BaseModel):
    """Get conversions"""

    operation: Literal["google_get_conversions"] = Field(
        "google_get_conversions",
        json_schema_extra={
            "const": "google_get_conversions", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get conversions",
        },
        title="Get conversions",
    )
    location_id: str = Field(..., title="Location Id")
    type: Optional[str] = Field(None, title="Type", json_schema_extra={"enum": ["AD_MANAGER", "AD_WORDS"], "x-enum-searchable": True})
    conversion_type: Optional[str] = Field(None, title="Conversion Type")
    category: Optional[str] = Field(None, title="Category")
    start_date: Optional[str] = Field(None, title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")


class GHLGoogleUpsertConversionConfig(BaseModel):
    """Upsert conversion"""

    operation: Literal["google_upsert_conversion"] = Field(
        "google_upsert_conversion",
        json_schema_extra={
            "const": "google_upsert_conversion", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert conversion",
        },
        title="Upsert conversion",
    )
    location_id: str = Field(..., title="Location Id")
    conversion_id: Optional[str] = Field(None, title="Conversion Id")
    name: str = Field(..., title="Name")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["UPLOAD_CLICKS", "UPLOAD_CALLS", "WEBPAGE", "LEAD_FORM_SUBMIT"], "x-enum-searchable": True})
    category: str = Field(..., title="Category")
    value_settings: Optional[str] = Field(None, title="Value Settings", description="JSON")
    counting_type: str = Field(..., title="Counting Type", json_schema_extra={"enum": ["ONE_PER_CLICK", "MANY_PER_CLICK"], "x-enum-searchable": True})
    attribution_model: str = Field(..., title="Attribution Model", json_schema_extra={"enum": ["GOOGLE_SEARCH_ATTRIBUTION_DATA_DRIVEN", "GOOGLE_ADS_LAST_CLICK"], "x-enum-searchable": True})
    click_through_window: Optional[str] = Field(None, title="Click Through Window")


class GHLGoogleGetConversionByIdConfig(BaseModel):
    """Get conversion by ID"""

    operation: Literal["google_get_conversion_by_id"] = Field(
        "google_get_conversion_by_id",
        json_schema_extra={
            "const": "google_get_conversion_by_id", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get conversion by ID",
        },
        title="Get conversion by ID",
    )
    conversion_id: str = Field(..., title="Conversion Id")
    location_id: str = Field(..., title="Location Id")


class GHLGoogleDeleteConversionConfig(BaseModel):
    """Delete conversion"""

    operation: Literal["google_delete_conversion"] = Field(
        "google_delete_conversion",
        json_schema_extra={
            "const": "google_delete_conversion", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete conversion",
        },
        title="Delete conversion",
    )
    conversion_id: str = Field(..., title="Conversion Id")
    location_id: str = Field(..., title="Location Id")


class GHLGoogleGetIntegrationConfig(BaseModel):
    """Get Google integration"""

    operation: Literal["google_get_integration"] = Field(
        "google_get_integration",
        json_schema_extra={
            "const": "google_get_integration", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get Google integration",
        },
        title="Get Google integration",
    )
    location_id: str = Field(..., title="Location Id")


class GHLGoogleCreateIntegrationConfig(BaseModel):
    """Create Google integration"""

    operation: Literal["google_create_integration"] = Field(
        "google_create_integration",
        json_schema_extra={
            "const": "google_create_integration", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Create Google integration",
        },
        title="Create Google integration",
    )
    location_id: str = Field(..., title="Location Id")
    ad_account_id: str = Field(..., title="Ad Account Id")
    mcc_id: str = Field(..., title="Mcc Id")


class GHLGoogleGetCurrentUserConfig(BaseModel):
    """Get current Google user"""

    operation: Literal["google_get_current_user"] = Field(
        "google_get_current_user",
        json_schema_extra={
            "const": "google_get_current_user", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get current Google user",
        },
        title="Get current Google user",
    )
    location_id: str = Field(..., title="Location Id")


class GHLGoogleGetAdAccountsConfig(BaseModel):
    """Get Google ad accounts"""

    operation: Literal["google_get_ad_accounts"] = Field(
        "google_get_ad_accounts",
        json_schema_extra={
            "const": "google_get_ad_accounts", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get Google ad accounts",
        },
        title="Get Google ad accounts",
    )
    location_id: str = Field(..., title="Location Id")
    type: Optional[str] = Field(None, title="Type", json_schema_extra={"enum": ["INTEGRATION", "AD_MANAGER"], "x-enum-searchable": True})


class GHLGoogleGetAdAccountDetailsConfig(BaseModel):
    """Get ad account details"""

    operation: Literal["google_get_ad_account_details"] = Field(
        "google_get_ad_account_details",
        json_schema_extra={
            "const": "google_get_ad_account_details", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get ad account details",
        },
        title="Get ad account details",
    )
    ad_account_id: str = Field(..., title="Ad Account Id")
    location_id: str = Field(..., title="Location Id")


class GHLGoogleDeleteAdAccountConfig(BaseModel):
    """Delete ad account"""

    operation: Literal["google_delete_ad_account"] = Field(
        "google_delete_ad_account",
        json_schema_extra={
            "const": "google_delete_ad_account", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete ad account",
        },
        title="Delete ad account",
    )
    ad_account_id: str = Field(..., title="Ad Account Id")
    location_id: str = Field(..., title="Location Id")


class GHLGooglePublishAdConfig(BaseModel):
    """Publish ad"""

    operation: Literal["google_publish_ad"] = Field(
        "google_publish_ad",
        json_schema_extra={
            "const": "google_publish_ad", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Publish ad",
        },
        title="Publish ad",
    )
    ad_id: str = Field(..., title="Ad Id")


class GHLGoogleSearchTargetingConfig(BaseModel):
    """Search targeting options"""

    operation: Literal["google_search_targeting"] = Field(
        "google_search_targeting",
        json_schema_extra={
            "const": "google_search_targeting", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Search targeting options",
        },
        title="Search targeting options",
    )
    type: str = Field(..., title="Type")
    query: Optional[str] = Field(None, title="Query")
    location_id: str = Field(..., title="Location Id")


class GHLGoogleGetKeywordIdeasConfig(BaseModel):
    """Get keyword ideas"""

    operation: Literal["google_get_keyword_ideas"] = Field(
        "google_get_keyword_ideas",
        json_schema_extra={
            "const": "google_get_keyword_ideas", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get keyword ideas",
        },
        title="Get keyword ideas",
    )
    location_id: str = Field(..., title="Location Id")
    url: str = Field(..., title="Url")
    language_code: Optional[str] = Field(None, title="Language Code")
    locations: Optional[str] = Field(None, title="Locations", description="Comma-separated list")
    keywords: Optional[str] = Field(None, title="Keywords", description="Comma-separated list")


class GHLGoogleGetAssetsConfig(BaseModel):
    """Get assets"""

    operation: Literal["google_get_assets"] = Field(
        "google_get_assets",
        json_schema_extra={
            "const": "google_get_assets", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get assets",
        },
        title="Get assets",
    )
    location_id: str = Field(..., title="Location Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["CALL", "SITELINK", "LEAD_FORM", "IMAGE", "TEXT"], "x-enum-searchable": True})
    id: Optional[str] = Field(None, title="Id")
    advertiser_only: Optional[str] = Field(None, title="Advertiser Only")


class GHLGoogleUpsertAssetsConfig(BaseModel):
    """Upsert assets"""

    operation: Literal["google_upsert_assets"] = Field(
        "google_upsert_assets",
        json_schema_extra={
            "const": "google_upsert_assets", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert assets",
        },
        title="Upsert assets",
    )
    location_id: str = Field(..., title="Location Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["CALL", "SITELINK", "LEAD_FORM"], "x-enum-searchable": True})
    payload: Optional[str] = Field(None, title="Payload", description="JSON")


class GHLGoogleGetEntityConfig(BaseModel):
    """Get entities"""

    operation: Literal["google_get_entity"] = Field(
        "google_get_entity",
        json_schema_extra={
            "const": "google_get_entity", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get entities",
        },
        title="Get entities",
    )
    location_id: str = Field(..., title="Location Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["AD_MANAGER", "INTEGRATION"], "x-enum-searchable": True})
    campaign_id: Optional[str] = Field(None, title="Campaign Id")
    ad_group_id: Optional[str] = Field(None, title="Ad Group Id")
    entity_type: str = Field(..., title="Entity Type", json_schema_extra={"enum": ["CAMPAIGN", "ADGROUP", "AD"], "x-enum-searchable": True})
    search_id: Optional[str] = Field(None, title="Search Id")
    start_date: Optional[str] = Field(None, title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")
    selected_ad_account_id: Optional[str] = Field(None, title="Selected Ad Account Id")


class GHLGoogleGetTargetInterestsConfig(BaseModel):
    """Get target interests"""

    operation: Literal["google_get_target_interests"] = Field(
        "google_get_target_interests",
        json_schema_extra={
            "const": "google_get_target_interests", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get target interests",
        },
        title="Get target interests",
    )
    location_id: str = Field(..., title="Location Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["AFFINITY", "IN_MARKET"], "x-enum-searchable": True})
    advertising_channel_type: str = Field(..., title="Advertising Channel Type")


class GHLGoogleGetSegmentsConfig(BaseModel):
    """Get segments"""

    operation: Literal["google_get_segments"] = Field(
        "google_get_segments",
        json_schema_extra={
            "const": "google_get_segments", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get segments",
        },
        title="Get segments",
    )
    location_id: str = Field(..., title="Location Id")
    type: Optional[str] = Field(None, title="Type")


class GHLGoogleUpsertSegmentConfig(BaseModel):
    """Upsert segment"""

    operation: Literal["google_upsert_segment"] = Field(
        "google_upsert_segment",
        json_schema_extra={
            "const": "google_upsert_segment", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert segment",
        },
        title="Upsert segment",
    )
    location_id: str = Field(..., title="Location Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["CUSTOM_SEGMENTS", "WEBSITE_VISITOR", "CUSTOMER_MATCH", "LOOKALIKE"], "x-enum-searchable": True})
    name: str = Field(..., title="Name")
    description: Optional[str] = Field(None, title="Description")
    members: Optional[str] = Field(None, title="Members", description="JSON")
    status: Optional[str] = Field(None, title="Status")
    type_body: Optional[str] = Field(None, title="Type")
    id: Optional[str] = Field(None, title="Id")
    membership_status: Optional[str] = Field(None, title="Membership Status")
    rule_based_user_list: Optional[str] = Field(None, title="Rule Based User List", description="JSON")
    membership_life_span: Optional[str] = Field(None, title="Membership Life Span")
    seed_user_list_ids: Optional[str] = Field(None, title="Seed User List Ids", description="Comma-separated list")
    country_codes: Optional[str] = Field(None, title="Country Codes", description="Comma-separated list")
    expansion_level: Optional[str] = Field(None, title="Expansion Level", json_schema_extra={"enum": ["BALANCED", "BROAD", "NARROW"], "x-enum-searchable": True})


class GHLGoogleDeleteSegmentConfig(BaseModel):
    """Delete segment"""

    operation: Literal["google_delete_segment"] = Field(
        "google_delete_segment",
        json_schema_extra={
            "const": "google_delete_segment", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete segment",
        },
        title="Delete segment",
    )
    segment_id: str = Field(..., title="Segment Id")
    location_id: str = Field(..., title="Location Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["CUSTOM_SEGMENTS", "DATA_SEGMENTS"], "x-enum-searchable": True})


class GHLGoogleGetSegmentByIdConfig(BaseModel):
    """Get segment by ID"""

    operation: Literal["google_get_segment_by_id"] = Field(
        "google_get_segment_by_id",
        json_schema_extra={
            "const": "google_get_segment_by_id", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get segment by ID",
        },
        title="Get segment by ID",
    )
    segment_id: str = Field(..., title="Segment Id")
    location_id: str = Field(..., title="Location Id")
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["CUSTOM_SEGMENTS", "DATA_SEGMENTS"], "x-enum-searchable": True})


class GHLGoogleCreateOfflineUserListJobConfig(BaseModel):
    """Create offline user list job"""

    operation: Literal["google_create_offline_user_list_job"] = Field(
        "google_create_offline_user_list_job",
        json_schema_extra={
            "const": "google_create_offline_user_list_job", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Create offline user list job",
        },
        title="Create offline user list job",
    )
    location_id: str = Field(..., title="Location Id")
    smart_list_ids: Optional[str] = Field(None, title="Smart List Ids", description="Comma-separated list")
    csv_path: Optional[str] = Field(None, title="Csv Path")
    user_list_id: Optional[str] = Field(None, title="User List Id")
    is_dynamic: Optional[str] = Field(None, title="Is Dynamic", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


class GHLGoogleUpsertAudienceConfig(BaseModel):
    """Upsert audience"""

    operation: Literal["google_upsert_audience"] = Field(
        "google_upsert_audience",
        json_schema_extra={
            "const": "google_upsert_audience", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert audience",
        },
        title="Upsert audience",
    )
    location_id: str = Field(..., title="Location Id")
    resource_name: Optional[str] = Field(None, title="Resource Name")
    name: str = Field(..., title="Name")
    dimensions: Optional[str] = Field(None, title="Dimensions", description="JSON")
    exclusion_dimension: Optional[str] = Field(None, title="Exclusion Dimension", description="JSON")


class GHLGoogleGetAudiencesConfig(BaseModel):
    """Get audiences"""

    operation: Literal["google_get_audiences"] = Field(
        "google_get_audiences",
        json_schema_extra={
            "const": "google_get_audiences", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get audiences",
        },
        title="Get audiences",
    )
    location_id: str = Field(..., title="Location Id")


class GHLGoogleGetAudienceByIdConfig(BaseModel):
    """Get audience by ID"""

    operation: Literal["google_get_audience_by_id"] = Field(
        "google_get_audience_by_id",
        json_schema_extra={
            "const": "google_get_audience_by_id", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get audience by ID",
        },
        title="Get audience by ID",
    )
    audience_id: str = Field(..., title="Audience Id")
    location_id: str = Field(..., title="Location Id")


class GHLGoogleUpsertCampaignConfig(BaseModel):
    """Upsert Google campaign"""

    operation: Literal["google_upsert_campaign"] = Field(
        "google_upsert_campaign",
        json_schema_extra={
            "const": "google_upsert_campaign", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert Google campaign",
        },
        title="Upsert Google campaign",
    )
    id: Optional[str] = Field(None, title="Id")
    name: str = Field(..., title="Name")
    location_id: str = Field(..., title="Location Id")
    advertising_channel_type: str = Field(..., title="Advertising Channel Type", json_schema_extra={"enum": ["SEARCH", "DISCOVERY", "DISPLAY", "HOTEL", "LOCAL", "MULTI_CHANNEL", "PERFORMANCE_MAX", "DEMAND_GEN"], "x-enum-searchable": True})
    advertising_channel_sub_type: Optional[str] = Field(None, title="Advertising Channel Sub Type", json_schema_extra={"enum": ["DEMAND_GEN"], "x-enum-searchable": True})
    goal_type: Optional[str] = Field(None, title="Goal Type", json_schema_extra={"enum": ["WEBSITE_TRAFFIC", "LEAD"], "x-enum-searchable": True})
    budget: Optional[str] = Field(None, title="Budget", description="JSON")
    audience: Optional[str] = Field(None, title="Audience", description="JSON")
    network_settings: Optional[str] = Field(None, title="Network Settings", description="JSON")
    bidding_strategy: Optional[str] = Field(None, title="Bidding Strategy", description="JSON")
    assets: Optional[str] = Field(None, title="Assets", description="JSON")
    is_eu_political_ads: Optional[str] = Field(None, title="Is Eu Political Ads", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    ad_groups: Optional[str] = Field(None, title="Ad Groups", description="JSON")
    campaign_goal: Optional[str] = Field(None, title="Campaign Goal", description="JSON")
    ad_schedule: Optional[str] = Field(None, title="Ad Schedule", description="JSON")
    publishing_status: Optional[str] = Field(None, title="Publishing Status", json_schema_extra={"enum": ["DRAFT", "SCHEDULED", "PUBLISHED", "PUBLISHING", "FAILED", "IN_REVIEW", "PAUSED", "ARCHIVED", "WITH_ISSUES", "REJECTED"], "x-enum-searchable": True})
    google_ad_account_id: Optional[str] = Field(None, title="Google Ad Account Id")
    unpublished_changes: Optional[str] = Field(None, title="Unpublished Changes", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    maximum_cpc: Optional[str] = Field(None, title="Maximum Cpc")
    google_campaign_id: Optional[str] = Field(None, title="Google Campaign Id")
    source: Optional[str] = Field(None, title="Source")
    advanced_options: Optional[str] = Field(None, title="Advanced Options", description="JSON")


class GHLGoogleGetCampaignByIdConfig(BaseModel):
    """Get Google campaign by ID"""

    operation: Literal["google_get_campaign_by_id"] = Field(
        "google_get_campaign_by_id",
        json_schema_extra={
            "const": "google_get_campaign_by_id", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get Google campaign by ID",
        },
        title="Get Google campaign by ID",
    )
    ad_id: str = Field(..., title="Ad Id")
    location_id: str = Field(..., title="Location Id")


class GHLGoogleGetConversionGoalsConfig(BaseModel):
    """Get conversion goals"""

    operation: Literal["google_get_conversion_goals"] = Field(
        "google_get_conversion_goals",
        json_schema_extra={
            "const": "google_get_conversion_goals", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get conversion goals",
        },
        title="Get conversion goals",
    )
    location_id: str = Field(..., title="Location Id")


class GHLLiGetIntegrationConfig(BaseModel):
    """Get LinkedIn integration"""

    operation: Literal["li_get_integration"] = Field(
        "li_get_integration",
        json_schema_extra={
            "const": "li_get_integration", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get LinkedIn integration",
        },
        title="Get LinkedIn integration",
    )
    location_id: str = Field(..., title="Location Id")


class GHLLiCreateIntegrationConfig(BaseModel):
    """Create LinkedIn integration"""

    operation: Literal["li_create_integration"] = Field(
        "li_create_integration",
        json_schema_extra={
            "const": "li_create_integration", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Create LinkedIn integration",
        },
        title="Create LinkedIn integration",
    )
    location_id: str = Field(..., title="Location Id")
    ad_account_id: str = Field(..., title="Ad Account Id")
    ad_account_name: str = Field(..., title="Ad Account Name")
    currency_code: str = Field(..., title="Currency Code")
    organization_id: str = Field(..., title="Organization Id")


class GHLLiGetAdAccountsConfig(BaseModel):
    """Get LinkedIn ad accounts"""

    operation: Literal["li_get_ad_accounts"] = Field(
        "li_get_ad_accounts",
        json_schema_extra={
            "const": "li_get_ad_accounts", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get LinkedIn ad accounts",
        },
        title="Get LinkedIn ad accounts",
    )
    location_id: str = Field(..., title="Location Id")


class GHLLiGetAdAccountDetailsConfig(BaseModel):
    """Get ad account details"""

    operation: Literal["li_get_ad_account_details"] = Field(
        "li_get_ad_account_details",
        json_schema_extra={
            "const": "li_get_ad_account_details", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get ad account details",
        },
        title="Get ad account details",
    )
    location_id: str = Field(..., title="Location Id")
    ad_account_id: str = Field(..., title="Ad Account Id")


class GHLLiDeleteAdAccountConfig(BaseModel):
    """Delete ad account"""

    operation: Literal["li_delete_ad_account"] = Field(
        "li_delete_ad_account",
        json_schema_extra={
            "const": "li_delete_ad_account", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Delete ad account",
        },
        title="Delete ad account",
    )
    location_id: str = Field(..., title="Location Id")
    ad_account_id: str = Field(..., title="Ad Account Id")


class GHLLiGetCurrentUserConfig(BaseModel):
    """Get current LinkedIn user"""

    operation: Literal["li_get_current_user"] = Field(
        "li_get_current_user",
        json_schema_extra={
            "const": "li_get_current_user", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get current LinkedIn user",
        },
        title="Get current LinkedIn user",
    )
    location_id: str = Field(..., title="Location Id")


class GHLLiGetCampaignGroupConfig(BaseModel):
    """Get ad campaign group"""

    operation: Literal["li_get_campaign_group"] = Field(
        "li_get_campaign_group",
        json_schema_extra={
            "const": "li_get_campaign_group", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get ad campaign group",
        },
        title="Get ad campaign group",
    )
    ad_id: str = Field(..., title="Ad Id")
    location_id: str = Field(..., title="Location Id")


class GHLLiPublishCampaignGroupConfig(BaseModel):
    """Publish ad campaign group"""

    operation: Literal["li_publish_campaign_group"] = Field(
        "li_publish_campaign_group",
        json_schema_extra={
            "const": "li_publish_campaign_group", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Publish ad campaign group",
        },
        title="Publish ad campaign group",
    )
    ad_id: str = Field(..., title="Ad Id")
    location_id: str = Field(..., title="Location Id")


class GHLLiUpsertCampaignGroupConfig(BaseModel):
    """Upsert ad campaign group"""

    operation: Literal["li_upsert_campaign_group"] = Field(
        "li_upsert_campaign_group",
        json_schema_extra={
            "const": "li_upsert_campaign_group", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Upsert ad campaign group",
        },
        title="Upsert ad campaign group",
    )
    id: Optional[str] = Field(None, title="Id")
    location_id: str = Field(..., title="Location Id")
    budget: Optional[str] = Field(None, title="Budget", description="JSON")
    ad_campaigns: Optional[str] = Field(None, title="Ad Campaigns", description="JSON")
    ad_budget_optimization: Optional[str] = Field(None, title="Ad Budget Optimization", json_schema_extra={"enum": ["MAXIMUM_DELIVERY", "COST_CAP"], "x-enum-searchable": True})
    objective_type: Optional[str] = Field(None, title="Objective Type", json_schema_extra={"enum": ["LEAD_GENERATION", "WEBSITE_VISIT"], "x-enum-searchable": True})
    name: Optional[str] = Field(None, title="Name")
    ad_campaign_group_id: Optional[str] = Field(None, title="Ad Campaign Group Id")
    publishing_status: Optional[str] = Field(None, title="Publishing Status", json_schema_extra={"enum": ["DRAFT", "SCHEDULED", "PUBLISHED", "PUBLISHING", "FAILED", "IN_REVIEW", "PAUSED", "ARCHIVED", "WITH_ISSUES", "REJECTED"], "x-enum-searchable": True})
    linked_in_ad_account_id: Optional[str] = Field(None, title="Linked In Ad Account Id")
    unpublished_changes: Optional[str] = Field(None, title="Unpublished Changes", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    meta: Optional[str] = Field(None, title="Meta", description="JSON")
    linked_in_error: Optional[str] = Field(None, title="Linked In Error")


class GHLLiSearchTargetingConfig(BaseModel):
    """Search targeting options"""

    operation: Literal["li_search_targeting"] = Field(
        "li_search_targeting",
        json_schema_extra={
            "const": "li_search_targeting", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Search targeting options",
        },
        title="Search targeting options",
    )
    location_id: str = Field(..., title="Location Id")
    facet: str = Field(..., title="Facet")
    query: Optional[str] = Field(None, title="Query")
    q: Optional[str] = Field(None, title="Q")


class GHLLiGetLeadFormsConfig(BaseModel):
    """Get lead forms"""

    operation: Literal["li_get_lead_forms"] = Field(
        "li_get_lead_forms",
        json_schema_extra={
            "const": "li_get_lead_forms", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get lead forms",
        },
        title="Get lead forms",
    )
    account_id: str = Field(..., title="Account Id")
    location_id: str = Field(..., title="Location Id")


class GHLLiCreateLeadFormConfig(BaseModel):
    """Create lead form"""

    operation: Literal["li_create_lead_form"] = Field(
        "li_create_lead_form",
        json_schema_extra={
            "const": "li_create_lead_form", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Create lead form",
        },
        title="Create lead form",
    )
    account_id: str = Field(..., title="Account ID", description="LinkedIn ad account id (path param)")
    location_id: str = Field(..., title="Location Id")
    owner: Optional[str] = Field(None, title="Owner", description="JSON")
    creation_locale: Optional[str] = Field(None, title="Creation Locale", description="JSON")
    name: str = Field(..., title="Name")
    state: str = Field(..., title="State", json_schema_extra={"enum": ["PUBLISHED"], "x-enum-searchable": True})
    content: Optional[str] = Field(None, title="Content", description="JSON")
    hidden_fields: Optional[str] = Field(None, title="Hidden Fields", description="JSON")


class GHLLiUpdateAdStatusConfig(BaseModel):
    """Update ad status"""

    operation: Literal["li_update_ad_status"] = Field(
        "li_update_ad_status",
        json_schema_extra={
            "const": "li_update_ad_status", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Update ad status",
        },
        title="Update ad status",
    )
    ad_id: str = Field(..., title="Ad Id")
    location_id: str = Field(..., title="Location Id")
    operation_type: str = Field(..., title="Operation Type", json_schema_extra={"enum": ["PAUSED", "ARCHIVED", "RESUME"], "x-enum-searchable": True})
    type: str = Field(..., title="Type", json_schema_extra={"enum": ["adGroup", "adCampaign", "ad"], "x-enum-searchable": True})


class GHLLiGetAdAnalyticsConfig(BaseModel):
    """Get ad analytics"""

    operation: Literal["li_get_ad_analytics"] = Field(
        "li_get_ad_analytics",
        json_schema_extra={
            "const": "li_get_ad_analytics", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get ad analytics",
        },
        title="Get ad analytics",
    )
    location_id: str = Field(..., title="Location Id")
    pivot: Optional[str] = Field(None, title="Pivot", json_schema_extra={"enum": ["ACCOUNT", "CAMPAIGN", "CAMPAIGN_GROUP", "CREATIVE"], "x-enum-searchable": True})
    group_by: Optional[str] = Field(None, title="Group By", json_schema_extra={"enum": ["day", "month", "year"], "x-enum-searchable": True})
    start_date: str = Field(..., title="Start Date")
    end_date: str = Field(..., title="End Date")
    entity_urns: Optional[str] = Field(None, title="Entity Urns")
    fields: Optional[str] = Field(None, title="Fields")


class GHLLiGetReportingListConfig(BaseModel):
    """Get reporting list"""

    operation: Literal["li_get_reporting_list"] = Field(
        "li_get_reporting_list",
        json_schema_extra={
            "const": "li_get_reporting_list", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get reporting list",
        },
        title="Get reporting list",
    )
    location_id: str = Field(..., title="Location Id")
    list_type: str = Field(..., title="List Type")
    campaign_id: str = Field(..., title="Campaign Id")
    campaign_group_id: str = Field(..., title="Campaign Group Id")
    start_date: str = Field(..., title="Start Date")
    end_date: str = Field(..., title="End Date")
    fields: Optional[str] = Field(None, title="Fields")


class GHLLiGetCampaignGroupReportingConfig(BaseModel):
    """Get campaign group reporting"""

    operation: Literal["li_get_campaign_group_reporting"] = Field(
        "li_get_campaign_group_reporting",
        json_schema_extra={
            "const": "li_get_campaign_group_reporting", "ui:hidden": True,
            "x-category": "Ad Manager", "x-is-trigger": False,
            "x-display-name": "Get campaign group reporting",
        },
        title="Get campaign group reporting",
    )
    campaign_group_id: str = Field(..., title="Campaign Group Id")
    location_id: str = Field(..., title="Location Id")
    start_date: str = Field(..., title="Start Date")
    end_date: str = Field(..., title="End Date")
    fields: Optional[str] = Field(None, title="Fields")
    campaign_group_id_query: Optional[str] = Field(None, title="Campaign Group Id")


async def _fb_get_reporting(node, c, token):
    params = {"locationId": c.location_id, "groupBy": c.group_by, "startDate": c.start_date, "endDate": c.end_date, "type": c.type, "fields": c.fields}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/reporting", params=params, action_name="fb_get_reporting"
    )


async def _fb_get_campaign_reporting(node, c, token):
    params = {"locationId": c.location_id, "startDate": c.start_date, "endDate": c.end_date}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/reporting/campaign/{c.campaign_id}", params=params, action_name="fb_get_campaign_reporting"
    )


async def _fb_get_reporting_list(node, c, token):
    params = {"locationId": c.location_id, "listType": c.list_type, "startDate": c.start_date, "endDate": c.end_date, "campaignId": c.campaign_id, "type": c.type}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/reporting/list", params=params, action_name="fb_get_reporting_list"
    )


async def _fb_get_current_user(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/me", params=params, action_name="fb_get_current_user"
    )


async def _fb_get_pages(node, c, token):
    params = {"locationId": c.location_id, "fetchExisting": c.fetch_existing}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/pages", params=params, action_name="fb_get_pages"
    )


async def _fb_get_instagram_accounts(node, c, token):
    params = {"locationId": c.location_id, "type": c.type}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/page/{c.page_id}/instagram", params=params, action_name="fb_get_instagram_accounts"
    )


async def _fb_get_page_lead_forms(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/page/{c.page_id}/forms", params=params, action_name="fb_get_page_lead_forms"
    )


async def _fb_create_page_lead_form(node, c, token):
    body = {
        "type": c.type, "name": c.name, "locationId": c.location_id,
        "greetingCard": _ghl_json(c.greeting_card), "questions": _ghl_json(c.questions),
        "questionPageHeadline": c.question_page_headline,
        "privacyPolicyLink": c.privacy_policy_link, "privacyPolicyText": c.privacy_policy_text,
        "customDisclaimer": _ghl_json(c.custom_disclaimer),
        "thankYouPage": _ghl_json(c.thank_you_page),
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/page/{c.page_id}/forms", json_body=body, action_name="fb_create_page_lead_form"
    )


async def _fb_get_ad_accounts(node, c, token):
    params = {"locationId": c.location_id, "type": c.type, "next": c.next, "fetchAll": c.fetch_all, "limit": c.limit}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/ad-accounts", params=params, action_name="fb_get_ad_accounts"
    )


async def _fb_get_ad_account(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/ad-accounts/{c.ad_account_id}", params=params, action_name="fb_get_ad_account"
    )


async def _fb_delete_ad_account(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "DELETE", f"/ad-publishing/facebook/ad-accounts/{c.ad_account_id}", json_body=body, action_name="fb_delete_ad_account"
    )


async def _fb_get_conversation_forms(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/conversation-forms", params=params, action_name="fb_get_conversation_forms"
    )


async def _fb_create_conversation_form(node, c, token):
    body = {
        "locationId": c.location_id, "name": c.name, "text": c.text,
        "questions": _ghl_json(c.questions),
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/conversation-forms", json_body=body, action_name="fb_create_conversation_form"
    )


async def _fb_create_integration(node, c, token):
    body = {
        "locationId": c.location_id, "pageId": c.page_id, "adAccountId": c.ad_account_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/integration", json_body=body, action_name="fb_create_integration"
    )


async def _fb_get_integration(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/integration", params=params, action_name="fb_get_integration"
    )


async def _fb_delete_integration(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "DELETE", f"/ad-publishing/facebook/integration", json_body=body, action_name="fb_delete_integration"
    )


async def _fb_search_targeting(node, c, token):
    params = {"type": c.type, "query": c.query, "searchType": c.search_type}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/targeting/search", params=params, action_name="fb_search_targeting"
    )


async def _fb_publish_campaign(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/campaigns/{c.campaign_id}/publish", json_body=body, action_name="fb_publish_campaign"
    )


async def _fb_delete_page(node, c, token):
    params = {"locationId": c.location_id, "pageId": c.page_id}
    return await node._request(
        token, "DELETE", f"/ad-publishing/facebook/page", params=params, action_name="fb_delete_page"
    )


async def _fb_get_pixels(node, c, token):
    params = {"locationId": c.location_id, "channel": c.channel, "pageId": c.page_id, "igUserId": c.ig_user_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/pixels", params=params, action_name="fb_get_pixels"
    )


async def _fb_upsert_pixel(node, c, token):
    body = {
        "locationId": c.location_id, "conversionPixelId": c.conversion_pixel_id, "name": c.name,
        "igUserId": c.ig_user_id, "type": c.type,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/facebook/pixels", json_body=body, action_name="fb_upsert_pixel"
    )


async def _fb_get_custom_audiences(node, c, token):
    params = {"locationId": c.location_id, "type": c.type, "source": c.source, "adAccountId": c.ad_account_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/custom-audience", params=params, action_name="fb_get_custom_audiences"
    )


async def _fb_delete_custom_audience(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "DELETE", f"/ad-publishing/facebook/custom-audience/{c.audience_id}", params=params, action_name="fb_delete_custom_audience"
    )


async def _fb_update_custom_audience(node, c, token):
    body = {
        "locationId": c.location_id, "name": c.name, "description": c.description,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/facebook/custom-audience/{c.audience_id}", json_body=body, action_name="fb_update_custom_audience"
    )


async def _fb_get_custom_audience_by_id(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/custom-audience/{c.audience_id}", params=params, action_name="fb_get_custom_audience_by_id"
    )


async def _fb_add_custom_audience_member(node, c, token):
    body = {
        "locationId": c.location_id, "contactId": c.contact_id,
        "fbAdAccountId": c.fb_ad_account_id,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/facebook/custom-audience/{c.audience_id}/member", json_body=body, action_name="fb_add_custom_audience_member"
    )


async def _fb_remove_custom_audience_member(node, c, token):
    body = {
        "locationId": c.location_id, "contactId": c.contact_id,
        "fbAdAccountId": c.fb_ad_account_id,
    }
    return await node._request(
        token, "DELETE", f"/ad-publishing/facebook/custom-audience/{c.audience_id}/member", json_body=body, action_name="fb_remove_custom_audience_member"
    )


async def _fb_batch_update_audience_members(node, c, token):
    body = {
        "locationId": c.location_id, "csvPath": c.csv_path, "operationType": c.operation_type,
        "smartlistIds": _ghl_csv(c.smartlist_ids), "dynamicAudience": c.dynamic_audience,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/facebook/custom-audience/{c.audience_id}/member/batch", json_body=body, action_name="fb_batch_update_audience_members"
    )


async def _fb_set_default_page(node, c, token):
    params = {"locationId": c.location_id}
    body = {
        "pageId": c.page_id,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/facebook/page/default", params=params, json_body=body, action_name="fb_set_default_page"
    )


async def _fb_get_lead_form(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/lead-form/{c.lead_form_id}", params=params, action_name="fb_get_lead_form"
    )


async def _fb_get_campaign(node, c, token):
    params = {"locationId": c.location_id, "fields": c.fields, "source": c.source}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/campaign/{c.campaign_id}", params=params, action_name="fb_get_campaign"
    )


async def _fb_get_entity(node, c, token):
    params = {"locationId": c.location_id, "type": c.type, "next": c.next, "fetchAll": c.fetch_all, "campaignId": c.campaign_id, "adSetId": c.ad_set_id, "entityType": c.entity_type, "searchId": c.search_id, "selectedAdAccountId": c.selected_ad_account_id}
    return await node._request(
        token, "GET", f"/ad-publishing/facebook/entity", params=params, action_name="fb_get_entity"
    )


async def _fb_upsert_campaign(node, c, token):
    body = {
        "id": c.id, "locationId": c.location_id, "name": c.name, "objective": c.objective,
        "specialAdCategories": c.special_ad_categories, "source": c.source,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/facebook/campaigns", json_body=body, action_name="fb_upsert_campaign"
    )


async def _fb_upsert_adset(node, c, token):
    body = {
        "id": c.id, "locationId": c.location_id, "name": c.name, "pageId": c.page_id,
        "instagramActorId": c.instagram_actor_id, "messagingPlatforms": c.messaging_platforms,
        "whatsappNumber": c.whatsapp_number, "audience": _ghl_json(c.audience),
        "budget": _ghl_json(c.budget), "conversionLocation": c.conversion_location,
        "customEventType": c.custom_event_type, "pixelId": c.pixel_id, "campaignId": c.campaign_id,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/facebook/adsets", json_body=body, action_name="fb_upsert_adset"
    )


async def _fb_upsert_ad(node, c, token):
    body = {
        "id": c.id, "locationId": c.location_id, "name": c.name, "primaryText": c.primary_text,
        "headline": c.headline, "description": c.description, "imageUrl": c.image_url,
        "mediaType": c.media_type, "media": _ghl_json(c.media),
        "multiAdvertiserAds": _ghl_bool(c.multi_advertiser_ads), "campaignId": c.campaign_id,
        "adsetId": c.adset_id, "cta": c.cta, "conversationFormId": c.conversation_form_id,
        "destinationLink": c.destination_link, "destinationFormId": c.destination_form_id,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/facebook/ads-v2", json_body=body, action_name="fb_upsert_ad"
    )


async def _fb_pause_campaign(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/campaigns/{c.campaign_id}/pause", json_body=body, action_name="fb_pause_campaign"
    )


async def _fb_resume_campaign(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/campaigns/{c.campaign_id}/resume", json_body=body, action_name="fb_resume_campaign"
    )


async def _fb_duplicate_campaign(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/campaigns/{c.campaign_id}/duplicate", json_body=body, action_name="fb_duplicate_campaign"
    )


async def _fb_delete_campaign(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "DELETE", f"/ad-publishing/facebook/campaigns/{c.campaign_id}", json_body=body, action_name="fb_delete_campaign"
    )


async def _fb_pause_adset(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/adsets/{c.adset_id}/pause", json_body=body, action_name="fb_pause_adset"
    )


async def _fb_resume_adset(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/adsets/{c.adset_id}/resume", json_body=body, action_name="fb_resume_adset"
    )


async def _fb_duplicate_adset(node, c, token):
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/adsets/{c.adset_id}/duplicate", action_name="fb_duplicate_adset"
    )


async def _fb_delete_adset(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "DELETE", f"/ad-publishing/facebook/adsets/{c.adset_id}", json_body=body, action_name="fb_delete_adset"
    )


async def _fb_pause_ad(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/ads/{c.ad_id}/pause", json_body=body, action_name="fb_pause_ad"
    )


async def _fb_resume_ad(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/ads/{c.ad_id}/resume", json_body=body, action_name="fb_resume_ad"
    )


async def _fb_duplicate_ad(node, c, token):
    return await node._request(
        token, "POST", f"/ad-publishing/facebook/ads/{c.ad_id}/duplicate", action_name="fb_duplicate_ad"
    )


async def _fb_delete_ad(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "DELETE", f"/ad-publishing/facebook/ads/{c.ad_id}", json_body=body, action_name="fb_delete_ad"
    )


async def _google_get_reporting(node, c, token):
    params = {"locationId": c.location_id, "groupBy": c.group_by, "startDate": c.start_date, "endDate": c.end_date, "type": c.type, "fields": c.fields}
    return await node._request(
        token, "GET", f"/ad-publishing/google/reporting", params=params, action_name="google_get_reporting"
    )


async def _google_get_reporting_list(node, c, token):
    params = {"locationId": c.location_id, "listType": c.list_type, "startDate": c.start_date, "endDate": c.end_date, "campaignId": c.campaign_id, "type": c.type}
    return await node._request(
        token, "GET", f"/ad-publishing/google/reporting/list", params=params, action_name="google_get_reporting_list"
    )


async def _google_get_campaign_reporting(node, c, token):
    params = {"locationId": c.location_id, "startDate": c.start_date, "endDate": c.end_date}
    return await node._request(
        token, "GET", f"/ad-publishing/google/reporting/campaign/{c.campaign_id}", params=params, action_name="google_get_campaign_reporting"
    )


async def _google_get_conversions(node, c, token):
    params = {"locationId": c.location_id, "type": c.type, "conversionType": c.conversion_type, "category": c.category, "startDate": c.start_date, "endDate": c.end_date}
    return await node._request(
        token, "GET", f"/ad-publishing/google/conversions", params=params, action_name="google_get_conversions"
    )


async def _google_upsert_conversion(node, c, token):
    body = {
        "locationId": c.location_id, "conversionId": c.conversion_id, "name": c.name,
        "type": c.type, "category": c.category, "valueSettings": _ghl_json(c.value_settings),
        "countingType": c.counting_type, "attributionModel": c.attribution_model,
        "clickThroughWindow": _ghl_num(c.click_through_window),
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/google/conversions", json_body=body, action_name="google_upsert_conversion"
    )


async def _google_get_conversion_by_id(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/conversions/{c.conversion_id}", params=params, action_name="google_get_conversion_by_id"
    )


async def _google_delete_conversion(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "DELETE", f"/ad-publishing/google/conversions/{c.conversion_id}", params=params, action_name="google_delete_conversion"
    )


async def _google_get_integration(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/integration", params=params, action_name="google_get_integration"
    )


async def _google_create_integration(node, c, token):
    body = {
        "locationId": c.location_id, "adAccountId": c.ad_account_id, "mccId": c.mcc_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/google/integration", json_body=body, action_name="google_create_integration"
    )


async def _google_get_current_user(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/me", params=params, action_name="google_get_current_user"
    )


async def _google_get_ad_accounts(node, c, token):
    params = {"locationId": c.location_id, "type": c.type}
    return await node._request(
        token, "GET", f"/ad-publishing/google/ad-accounts", params=params, action_name="google_get_ad_accounts"
    )


async def _google_get_ad_account_details(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/ad-accounts/{c.ad_account_id}", params=params, action_name="google_get_ad_account_details"
    )


async def _google_delete_ad_account(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "DELETE", f"/ad-publishing/google/ad-accounts/{c.ad_account_id}", json_body=body, action_name="google_delete_ad_account"
    )


async def _google_publish_ad(node, c, token):
    return await node._request(
        token, "POST", f"/ad-publishing/google/ads/{c.ad_id}/publish", action_name="google_publish_ad"
    )


async def _google_search_targeting(node, c, token):
    params = {"type": c.type, "query": c.query, "locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/targeting/search", params=params, action_name="google_search_targeting"
    )


async def _google_get_keyword_ideas(node, c, token):
    params = {"locationId": c.location_id}
    body = {
        "url": c.url, "languageCode": c.language_code, "locations": _ghl_csv(c.locations),
        "keywords": _ghl_csv(c.keywords),
    }
    return await node._request(
        token, "POST", f"/ad-publishing/google/keyword-ideas", params=params, json_body=body, action_name="google_get_keyword_ideas"
    )


async def _google_get_assets(node, c, token):
    params = {"locationId": c.location_id, "type": c.type, "id": c.id, "advertiserOnly": c.advertiser_only}
    return await node._request(
        token, "GET", f"/ad-publishing/google/assets", params=params, action_name="google_get_assets"
    )


async def _google_upsert_assets(node, c, token):
    body = {
        "locationId": c.location_id, "type": c.type, "payload": _ghl_json(c.payload),
    }
    return await node._request(
        token, "POST", f"/ad-publishing/google/assets", json_body=body, action_name="google_upsert_assets"
    )


async def _google_get_entity(node, c, token):
    params = {"locationId": c.location_id, "type": c.type, "campaignId": c.campaign_id, "adGroupId": c.ad_group_id, "entityType": c.entity_type, "searchId": c.search_id, "startDate": c.start_date, "endDate": c.end_date, "selectedAdAccountId": c.selected_ad_account_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/entity", params=params, action_name="google_get_entity"
    )


async def _google_get_target_interests(node, c, token):
    params = {"locationId": c.location_id, "type": c.type, "advertisingChannelType": c.advertising_channel_type}
    return await node._request(
        token, "GET", f"/ad-publishing/google/target-interests", params=params, action_name="google_get_target_interests"
    )


async def _google_get_segments(node, c, token):
    params = {"locationId": c.location_id, "type": c.type}
    return await node._request(
        token, "GET", f"/ad-publishing/google/segments", params=params, action_name="google_get_segments"
    )


async def _google_upsert_segment(node, c, token):
    params = {"locationId": c.location_id, "type": c.type}
    body = {
        "name": c.name, "description": c.description, "members": _ghl_json(c.members),
        "status": c.status, "type": c.type_body, "id": c.id,
        "membershipStatus": c.membership_status,
        "ruleBasedUserList": _ghl_json(c.rule_based_user_list),
        "membershipLifeSpan": _ghl_num(c.membership_life_span),
        "seedUserListIds": _ghl_csv(c.seed_user_list_ids),
        "countryCodes": _ghl_csv(c.country_codes), "expansionLevel": c.expansion_level,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/google/segments", params=params, json_body=body, action_name="google_upsert_segment"
    )


async def _google_delete_segment(node, c, token):
    params = {"locationId": c.location_id, "type": c.type}
    return await node._request(
        token, "DELETE", f"/ad-publishing/google/segments/{c.segment_id}", params=params, action_name="google_delete_segment"
    )


async def _google_get_segment_by_id(node, c, token):
    params = {"locationId": c.location_id, "type": c.type}
    return await node._request(
        token, "GET", f"/ad-publishing/google/segments/{c.segment_id}", params=params, action_name="google_get_segment_by_id"
    )


async def _google_create_offline_user_list_job(node, c, token):
    body = {
        "locationId": c.location_id, "smartListIds": _ghl_csv(c.smart_list_ids),
        "csvPath": c.csv_path, "userListId": c.user_list_id, "isDynamic": _ghl_bool(c.is_dynamic),
    }
    return await node._request(
        token, "POST", f"/ad-publishing/google/segments/offline-user-list-job", json_body=body, action_name="google_create_offline_user_list_job"
    )


async def _google_upsert_audience(node, c, token):
    body = {
        "locationId": c.location_id, "resourceName": c.resource_name, "name": c.name,
        "dimensions": _ghl_json(c.dimensions),
        "exclusionDimension": _ghl_json(c.exclusion_dimension),
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/google/audiences", json_body=body, action_name="google_upsert_audience"
    )


async def _google_get_audiences(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/audiences", params=params, action_name="google_get_audiences"
    )


async def _google_get_audience_by_id(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/audiences/{c.audience_id}", params=params, action_name="google_get_audience_by_id"
    )


async def _google_upsert_campaign(node, c, token):
    body = {
        "id": c.id, "name": c.name, "locationId": c.location_id,
        "advertisingChannelType": c.advertising_channel_type,
        "advertisingChannelSubType": c.advertising_channel_sub_type, "goalType": c.goal_type,
        "budget": _ghl_json(c.budget), "audience": _ghl_json(c.audience),
        "networkSettings": _ghl_json(c.network_settings),
        "biddingStrategy": _ghl_json(c.bidding_strategy), "assets": _ghl_json(c.assets),
        "isEuPoliticalAds": _ghl_bool(c.is_eu_political_ads), "adGroups": _ghl_json(c.ad_groups),
        "campaignGoal": _ghl_json(c.campaign_goal), "adSchedule": _ghl_json(c.ad_schedule),
        "publishingStatus": c.publishing_status, "googleAdAccountId": c.google_ad_account_id,
        "unpublishedChanges": _ghl_bool(c.unpublished_changes),
        "maximumCpc": _ghl_num(c.maximum_cpc), "googleCampaignId": c.google_campaign_id,
        "source": c.source, "advancedOptions": _ghl_json(c.advanced_options),
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/google/ads", json_body=body, action_name="google_upsert_campaign"
    )


async def _google_get_campaign_by_id(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/ads/{c.ad_id}", params=params, action_name="google_get_campaign_by_id"
    )


async def _google_get_conversion_goals(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/google/conversion-goals", params=params, action_name="google_get_conversion_goals"
    )


async def _li_get_integration(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/integration", params=params, action_name="li_get_integration"
    )


async def _li_create_integration(node, c, token):
    body = {
        "locationId": c.location_id, "adAccountId": c.ad_account_id,
        "adAccountName": c.ad_account_name, "currencyCode": c.currency_code,
        "organizationId": c.organization_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/linkedin/integration", json_body=body, action_name="li_create_integration"
    )


async def _li_get_ad_accounts(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/ad-accounts", params=params, action_name="li_get_ad_accounts"
    )


async def _li_get_ad_account_details(node, c, token):
    params = {"locationId": c.location_id, "adAccountId": c.ad_account_id}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/ad-account", params=params, action_name="li_get_ad_account_details"
    )


async def _li_delete_ad_account(node, c, token):
    params = {"locationId": c.location_id, "adAccountId": c.ad_account_id}
    return await node._request(
        token, "DELETE", f"/ad-publishing/linkedin/ad-account", params=params, action_name="li_delete_ad_account"
    )


async def _li_get_current_user(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/me", params=params, action_name="li_get_current_user"
    )


async def _li_get_campaign_group(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/ads/{c.ad_id}", params=params, action_name="li_get_campaign_group"
    )


async def _li_publish_campaign_group(node, c, token):
    body = {
        "locationId": c.location_id,
    }
    return await node._request(
        token, "POST", f"/ad-publishing/linkedin/ads/{c.ad_id}/publish", json_body=body, action_name="li_publish_campaign_group"
    )


async def _li_upsert_campaign_group(node, c, token):
    body = {
        "id": c.id, "locationId": c.location_id, "budget": _ghl_json(c.budget),
        "adCampaigns": _ghl_json(c.ad_campaigns), "adBudgetOptimization": c.ad_budget_optimization,
        "objectiveType": c.objective_type, "name": c.name,
        "adCampaignGroupId": c.ad_campaign_group_id, "publishingStatus": c.publishing_status,
        "linkedInAdAccountId": c.linked_in_ad_account_id,
        "unpublishedChanges": _ghl_bool(c.unpublished_changes), "meta": _ghl_json(c.meta),
        "linkedInError": c.linked_in_error,
    }
    return await node._request(
        token, "PUT", f"/ad-publishing/linkedin/ads", json_body=body, action_name="li_upsert_campaign_group"
    )


async def _li_search_targeting(node, c, token):
    params = {"locationId": c.location_id, "facet": c.facet, "query": c.query, "q": c.q}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/targeting/search", params=params, action_name="li_search_targeting"
    )


async def _li_get_lead_forms(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/{c.account_id}/forms", params=params, action_name="li_get_lead_forms"
    )


async def _li_create_lead_form(node, c, token):
    params = {"locationId": c.location_id}
    body = {
        "owner": _ghl_json(c.owner), "creationLocale": _ghl_json(c.creation_locale),
        "name": c.name, "state": c.state, "content": _ghl_json(c.content),
        "hiddenFields": _ghl_json(c.hidden_fields),
    }
    return await node._request(
        token, "POST", f"/ad-publishing/linkedin/{c.account_id}/form", params=params, json_body=body, action_name="li_create_lead_form"
    )


async def _li_update_ad_status(node, c, token):
    params = {"locationId": c.location_id}
    body = {
        "operationType": c.operation_type, "type": c.type,
    }
    return await node._request(
        token, "PATCH", f"/ad-publishing/linkedin/{c.ad_id}/status", params=params, json_body=body, action_name="li_update_ad_status"
    )


async def _li_get_ad_analytics(node, c, token):
    params = {"locationId": c.location_id, "pivot": c.pivot, "groupBy": c.group_by, "startDate": c.start_date, "endDate": c.end_date, "entityUrns": c.entity_urns, "fields": c.fields}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/reporting", params=params, action_name="li_get_ad_analytics"
    )


async def _li_get_reporting_list(node, c, token):
    params = {"locationId": c.location_id, "listType": c.list_type, "campaignId": c.campaign_id, "campaignGroupId": c.campaign_group_id, "startDate": c.start_date, "endDate": c.end_date, "fields": c.fields}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/reporting/list", params=params, action_name="li_get_reporting_list"
    )


async def _li_get_campaign_group_reporting(node, c, token):
    params = {"locationId": c.location_id, "startDate": c.start_date, "endDate": c.end_date, "fields": c.fields, "campaignGroupId": c.campaign_group_id_query}
    return await node._request(
        token, "GET", f"/ad-publishing/linkedin/reporting/campaign-group/{c.campaign_group_id}", params=params, action_name="li_get_campaign_group_reporting"
    )


GHL_OPERATION_CONFIGS += [
    GHLFbGetReportingConfig,
    GHLFbGetCampaignReportingConfig,
    GHLFbGetReportingListConfig,
    GHLFbGetCurrentUserConfig,
    GHLFbGetPagesConfig,
    GHLFbGetInstagramAccountsConfig,
    GHLFbGetPageLeadFormsConfig,
    GHLFbCreatePageLeadFormConfig,
    GHLFbGetAdAccountsConfig,
    GHLFbGetAdAccountConfig,
    GHLFbDeleteAdAccountConfig,
    GHLFbGetConversationFormsConfig,
    GHLFbCreateConversationFormConfig,
    GHLFbCreateIntegrationConfig,
    GHLFbGetIntegrationConfig,
    GHLFbDeleteIntegrationConfig,
    GHLFbSearchTargetingConfig,
    GHLFbPublishCampaignConfig,
    GHLFbDeletePageConfig,
    GHLFbGetPixelsConfig,
    GHLFbUpsertPixelConfig,
    GHLFbGetCustomAudiencesConfig,
    GHLFbDeleteCustomAudienceConfig,
    GHLFbUpdateCustomAudienceConfig,
    GHLFbGetCustomAudienceByIdConfig,
    GHLFbAddCustomAudienceMemberConfig,
    GHLFbRemoveCustomAudienceMemberConfig,
    GHLFbBatchUpdateAudienceMembersConfig,
    GHLFbSetDefaultPageConfig,
    GHLFbGetLeadFormConfig,
    GHLFbGetCampaignConfig,
    GHLFbGetEntityConfig,
    GHLFbUpsertCampaignConfig,
    GHLFbUpsertAdsetConfig,
    GHLFbUpsertAdConfig,
    GHLFbPauseCampaignConfig,
    GHLFbResumeCampaignConfig,
    GHLFbDuplicateCampaignConfig,
    GHLFbDeleteCampaignConfig,
    GHLFbPauseAdsetConfig,
    GHLFbResumeAdsetConfig,
    GHLFbDuplicateAdsetConfig,
    GHLFbDeleteAdsetConfig,
    GHLFbPauseAdConfig,
    GHLFbResumeAdConfig,
    GHLFbDuplicateAdConfig,
    GHLFbDeleteAdConfig,
    GHLGoogleGetReportingConfig,
    GHLGoogleGetReportingListConfig,
    GHLGoogleGetCampaignReportingConfig,
    GHLGoogleGetConversionsConfig,
    GHLGoogleUpsertConversionConfig,
    GHLGoogleGetConversionByIdConfig,
    GHLGoogleDeleteConversionConfig,
    GHLGoogleGetIntegrationConfig,
    GHLGoogleCreateIntegrationConfig,
    GHLGoogleGetCurrentUserConfig,
    GHLGoogleGetAdAccountsConfig,
    GHLGoogleGetAdAccountDetailsConfig,
    GHLGoogleDeleteAdAccountConfig,
    GHLGooglePublishAdConfig,
    GHLGoogleSearchTargetingConfig,
    GHLGoogleGetKeywordIdeasConfig,
    GHLGoogleGetAssetsConfig,
    GHLGoogleUpsertAssetsConfig,
    GHLGoogleGetEntityConfig,
    GHLGoogleGetTargetInterestsConfig,
    GHLGoogleGetSegmentsConfig,
    GHLGoogleUpsertSegmentConfig,
    GHLGoogleDeleteSegmentConfig,
    GHLGoogleGetSegmentByIdConfig,
    GHLGoogleCreateOfflineUserListJobConfig,
    GHLGoogleUpsertAudienceConfig,
    GHLGoogleGetAudiencesConfig,
    GHLGoogleGetAudienceByIdConfig,
    GHLGoogleUpsertCampaignConfig,
    GHLGoogleGetCampaignByIdConfig,
    GHLGoogleGetConversionGoalsConfig,
    GHLLiGetIntegrationConfig,
    GHLLiCreateIntegrationConfig,
    GHLLiGetAdAccountsConfig,
    GHLLiGetAdAccountDetailsConfig,
    GHLLiDeleteAdAccountConfig,
    GHLLiGetCurrentUserConfig,
    GHLLiGetCampaignGroupConfig,
    GHLLiPublishCampaignGroupConfig,
    GHLLiUpsertCampaignGroupConfig,
    GHLLiSearchTargetingConfig,
    GHLLiGetLeadFormsConfig,
    GHLLiCreateLeadFormConfig,
    GHLLiUpdateAdStatusConfig,
    GHLLiGetAdAnalyticsConfig,
    GHLLiGetReportingListConfig,
    GHLLiGetCampaignGroupReportingConfig,
]
GHL_OPERATION_HANDLERS.update({
    "fb_get_reporting": _fb_get_reporting,
    "fb_get_campaign_reporting": _fb_get_campaign_reporting,
    "fb_get_reporting_list": _fb_get_reporting_list,
    "fb_get_current_user": _fb_get_current_user,
    "fb_get_pages": _fb_get_pages,
    "fb_get_instagram_accounts": _fb_get_instagram_accounts,
    "fb_get_page_lead_forms": _fb_get_page_lead_forms,
    "fb_create_page_lead_form": _fb_create_page_lead_form,
    "fb_get_ad_accounts": _fb_get_ad_accounts,
    "fb_get_ad_account": _fb_get_ad_account,
    "fb_delete_ad_account": _fb_delete_ad_account,
    "fb_get_conversation_forms": _fb_get_conversation_forms,
    "fb_create_conversation_form": _fb_create_conversation_form,
    "fb_create_integration": _fb_create_integration,
    "fb_get_integration": _fb_get_integration,
    "fb_delete_integration": _fb_delete_integration,
    "fb_search_targeting": _fb_search_targeting,
    "fb_publish_campaign": _fb_publish_campaign,
    "fb_delete_page": _fb_delete_page,
    "fb_get_pixels": _fb_get_pixels,
    "fb_upsert_pixel": _fb_upsert_pixel,
    "fb_get_custom_audiences": _fb_get_custom_audiences,
    "fb_delete_custom_audience": _fb_delete_custom_audience,
    "fb_update_custom_audience": _fb_update_custom_audience,
    "fb_get_custom_audience_by_id": _fb_get_custom_audience_by_id,
    "fb_add_custom_audience_member": _fb_add_custom_audience_member,
    "fb_remove_custom_audience_member": _fb_remove_custom_audience_member,
    "fb_batch_update_audience_members": _fb_batch_update_audience_members,
    "fb_set_default_page": _fb_set_default_page,
    "fb_get_lead_form": _fb_get_lead_form,
    "fb_get_campaign": _fb_get_campaign,
    "fb_get_entity": _fb_get_entity,
    "fb_upsert_campaign": _fb_upsert_campaign,
    "fb_upsert_adset": _fb_upsert_adset,
    "fb_upsert_ad": _fb_upsert_ad,
    "fb_pause_campaign": _fb_pause_campaign,
    "fb_resume_campaign": _fb_resume_campaign,
    "fb_duplicate_campaign": _fb_duplicate_campaign,
    "fb_delete_campaign": _fb_delete_campaign,
    "fb_pause_adset": _fb_pause_adset,
    "fb_resume_adset": _fb_resume_adset,
    "fb_duplicate_adset": _fb_duplicate_adset,
    "fb_delete_adset": _fb_delete_adset,
    "fb_pause_ad": _fb_pause_ad,
    "fb_resume_ad": _fb_resume_ad,
    "fb_duplicate_ad": _fb_duplicate_ad,
    "fb_delete_ad": _fb_delete_ad,
    "google_get_reporting": _google_get_reporting,
    "google_get_reporting_list": _google_get_reporting_list,
    "google_get_campaign_reporting": _google_get_campaign_reporting,
    "google_get_conversions": _google_get_conversions,
    "google_upsert_conversion": _google_upsert_conversion,
    "google_get_conversion_by_id": _google_get_conversion_by_id,
    "google_delete_conversion": _google_delete_conversion,
    "google_get_integration": _google_get_integration,
    "google_create_integration": _google_create_integration,
    "google_get_current_user": _google_get_current_user,
    "google_get_ad_accounts": _google_get_ad_accounts,
    "google_get_ad_account_details": _google_get_ad_account_details,
    "google_delete_ad_account": _google_delete_ad_account,
    "google_publish_ad": _google_publish_ad,
    "google_search_targeting": _google_search_targeting,
    "google_get_keyword_ideas": _google_get_keyword_ideas,
    "google_get_assets": _google_get_assets,
    "google_upsert_assets": _google_upsert_assets,
    "google_get_entity": _google_get_entity,
    "google_get_target_interests": _google_get_target_interests,
    "google_get_segments": _google_get_segments,
    "google_upsert_segment": _google_upsert_segment,
    "google_delete_segment": _google_delete_segment,
    "google_get_segment_by_id": _google_get_segment_by_id,
    "google_create_offline_user_list_job": _google_create_offline_user_list_job,
    "google_upsert_audience": _google_upsert_audience,
    "google_get_audiences": _google_get_audiences,
    "google_get_audience_by_id": _google_get_audience_by_id,
    "google_upsert_campaign": _google_upsert_campaign,
    "google_get_campaign_by_id": _google_get_campaign_by_id,
    "google_get_conversion_goals": _google_get_conversion_goals,
    "li_get_integration": _li_get_integration,
    "li_create_integration": _li_create_integration,
    "li_get_ad_accounts": _li_get_ad_accounts,
    "li_get_ad_account_details": _li_get_ad_account_details,
    "li_delete_ad_account": _li_delete_ad_account,
    "li_get_current_user": _li_get_current_user,
    "li_get_campaign_group": _li_get_campaign_group,
    "li_publish_campaign_group": _li_publish_campaign_group,
    "li_upsert_campaign_group": _li_upsert_campaign_group,
    "li_search_targeting": _li_search_targeting,
    "li_get_lead_forms": _li_get_lead_forms,
    "li_create_lead_form": _li_create_lead_form,
    "li_update_ad_status": _li_update_ad_status,
    "li_get_ad_analytics": _li_get_ad_analytics,
    "li_get_reporting_list": _li_get_reporting_list,
    "li_get_campaign_group_reporting": _li_get_campaign_group_reporting,
})


# ---- affiliate_manager.py ----
class GHLListAffiliatesConfig(BaseModel):
    """List affiliates for a location (sub-account)."""

    operation: Literal["list_affiliates"] = Field(
        "list_affiliates",
        json_schema_extra={
            "const": "list_affiliates", "ui:hidden": True,
            "x-category": "Affiliate Manager", "x-is-trigger": False,
            "x-display-name": "List Affiliates",
        },
        title="List Affiliates",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    query: Optional[str] = Field(None, title="Query", description="Search query")
    active: Optional[str] = Field(
        None, title="Active", description="Filter by active status",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    campaign_id: Optional[str] = Field(None, title="Campaign ID", description="Filter by campaign id")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    from_date: Optional[str] = Field(None, title="From Date")
    to_date: Optional[str] = Field(None, title="To Date")


class GHLGetAffiliateConfig(BaseModel):
    """Get an affiliate by id."""

    operation: Literal["get_affiliate"] = Field(
        "get_affiliate",
        json_schema_extra={
            "const": "get_affiliate", "ui:hidden": True,
            "x-category": "Affiliate Manager", "x-is-trigger": False,
            "x-display-name": "Get Affiliate",
        },
        title="Get Affiliate",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    affiliate_id: str = Field(..., title="Affiliate ID", description="The affiliate to fetch")


class GHLListPayoutsConfig(BaseModel):
    """List affiliate payouts for a location (sub-account)."""

    operation: Literal["list_payouts"] = Field(
        "list_payouts",
        json_schema_extra={
            "const": "list_payouts", "ui:hidden": True,
            "x-category": "Affiliate Manager", "x-is-trigger": False,
            "x-display-name": "List Payouts",
        },
        title="List Payouts",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    status: Optional[str] = Field(None, title="Status", description="Filter by payout status")
    query: Optional[str] = Field(None, title="Query", description="Search query")
    affiliate_id: Optional[str] = Field(None, title="Affiliate ID", description="Filter by affiliate id")
    campaign_id: Optional[str] = Field(None, title="Campaign ID", description="Filter by campaign id")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    start: Optional[str] = Field(None, title="Start", description="Start date")
    end: Optional[str] = Field(None, title="End", description="End date")


class GHLListCommissionsConfig(BaseModel):
    """List affiliate commissions for a location (sub-account)."""

    operation: Literal["list_commissions"] = Field(
        "list_commissions",
        json_schema_extra={
            "const": "list_commissions", "ui:hidden": True,
            "x-category": "Affiliate Manager", "x-is-trigger": False,
            "x-display-name": "List Commissions",
        },
        title="List Commissions",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    campaign_id: Optional[str] = Field(None, title="Campaign ID", description="Filter by campaign id")
    affiliate_id: Optional[str] = Field(None, title="Affiliate ID", description="Filter by affiliate id")
    status: Optional[str] = Field(None, title="Status", description="Filter by commission status")
    query: Optional[str] = Field(None, title="Query", description="Search query")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    from_date: Optional[str] = Field(None, title="From Date")
    to_date: Optional[str] = Field(None, title="To Date")


async def _list_affiliates(node, c, token):
    params = {
        "query": c.query, "active": _ghl_bool(c.active), "campaignId": c.campaign_id,
        "skip": c.skip, "limit": c.limit, "fromDate": c.from_date, "toDate": c.to_date,
    }
    return await node._request(
        token, "GET", f"/affiliate-manager/{c.location_id}/affiliates",
        params=params, action_name="list_affiliates",
    )


async def _get_affiliate(node, c, token):
    return await node._request(
        token, "GET", f"/affiliate-manager/{c.location_id}/affiliates/{c.affiliate_id}",
        action_name="get_affiliate",
    )


async def _list_payouts(node, c, token):
    params = {
        "status": c.status, "query": c.query, "affiliateId": c.affiliate_id,
        "campaignId": c.campaign_id, "skip": c.skip, "limit": c.limit,
        "start": c.start, "end": c.end,
    }
    return await node._request(
        token, "GET", f"/affiliate-manager/{c.location_id}/payouts",
        params=params, action_name="list_payouts",
    )


async def _list_commissions(node, c, token):
    params = {
        "campaignId": c.campaign_id, "affiliateId": c.affiliate_id, "status": c.status,
        "query": c.query, "skip": c.skip, "limit": c.limit,
        "fromDate": c.from_date, "toDate": c.to_date,
    }
    return await node._request(
        token, "GET", f"/affiliate-manager/{c.location_id}/commissions",
        params=params, action_name="list_commissions",
    )


GHL_OPERATION_CONFIGS += [
    GHLListAffiliatesConfig,
    GHLGetAffiliateConfig,
    GHLListPayoutsConfig,
    GHLListCommissionsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "list_affiliates": _list_affiliates,
    "get_affiliate": _get_affiliate,
    "list_payouts": _list_payouts,
    "list_commissions": _list_commissions,
})


# ---- agent_studio.py ----
class GHLCreateAgentConfig(BaseModel):
    """Create an agent for a location."""

    operation: Literal["create_studio_agent"] = Field(
        "create_studio_agent",
        json_schema_extra={
            "const": "create_studio_agent", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "Create Agent",
        },
        title="Create Agent",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    status: Optional[str] = Field(
        "active", title="Status", description="Agent status",
        json_schema_extra={
            "enum": ["active", "inactive", "archived"],
            "enumNames": ["Active", "Inactive", "Archived"],
            "x-enum-searchable": True,
        },
    )
    version: str = Field(..., title="Version", description="Agent version object (JSON)")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    agency_id: Optional[str] = Field(None, title="Agency ID")
    author_id: Optional[str] = Field(None, title="Author ID")
    author_name: Optional[str] = Field(None, title="Author Name")
    author_email: Optional[str] = Field(None, title="Author Email")
    nodes: Optional[str] = Field(None, title="Nodes", description="JSON array of nodes")
    edges: Optional[str] = Field(None, title="Edges", description="JSON array of edges")
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLGetAgentsConfig(BaseModel):
    """List agents for a location."""

    operation: Literal["get_agents"] = Field(
        "get_agents",
        json_schema_extra={
            "const": "get_agents", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "List Agents",
        },
        title="List Agents",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: str = Field(..., title="Limit", description="Max results to return")
    offset: str = Field(..., title="Offset", description="Number of results to skip (pagination)")
    is_published: Optional[str] = Field(
        None, title="Is Published", description="Filter by published state",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLUpdateAgentVersionConfig(BaseModel):
    """Update an agent version."""

    operation: Literal["update_agent_version"] = Field(
        "update_agent_version",
        json_schema_extra={
            "const": "update_agent_version", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "Update Agent",
        },
        title="Update Agent",
    )
    version_id: str = Field(..., title="Version ID", description="The agent version to update")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    version_name: Optional[str] = Field(None, title="Version Name")
    description: Optional[str] = Field(None, title="Description")
    nodes: Optional[str] = Field(None, title="Nodes", description="JSON array of node objects")
    edges: Optional[str] = Field(None, title="Edges", description="JSON array of edge objects")
    global_variables: Optional[str] = Field(None, title="Global Variables", description="JSON array")
    input_variables: Optional[str] = Field(None, title="Input Variables", description="JSON array")
    runtime_variables: Optional[str] = Field(None, title="Runtime Variables", description="JSON array")
    global_config: Optional[str] = Field(None, title="Global Config", description="JSON object")
    user_id: Optional[str] = Field(None, title="User ID")
    user_name: Optional[str] = Field(None, title="User Name")
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLUpdateAgentMetadataConfig(BaseModel):
    """Update an agent's metadata."""

    operation: Literal["update_agent_metadata"] = Field(
        "update_agent_metadata",
        json_schema_extra={
            "const": "update_agent_metadata", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "Update Agent Metadata",
        },
        title="Update Agent Metadata",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to update")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    status: Optional[str] = Field(
        None, title="Status", description="Agent status",
        json_schema_extra={
            "enum": ["active", "inactive", "archived"],
            "enumNames": ["Active", "Inactive", "Archived"],
            "x-enum-searchable": True,
        },
    )
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLDeleteAgentConfig(BaseModel):
    """Delete an agent."""

    operation: Literal["delete_studio_agent"] = Field(
        "delete_studio_agent",
        json_schema_extra={
            "const": "delete_studio_agent", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "Delete Agent",
        },
        title="Delete Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to delete")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLGetAgentByIdConfig(BaseModel):
    """Get an agent by id."""

    operation: Literal["get_agent_by_id"] = Field(
        "get_agent_by_id",
        json_schema_extra={
            "const": "get_agent_by_id", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "Get Agent",
        },
        title="Get Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to fetch")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLPromoteAndPublishAgentConfig(BaseModel):
    """Promote an agent version to production and publish."""

    operation: Literal["promote_and_publish_agent"] = Field(
        "promote_and_publish_agent",
        json_schema_extra={
            "const": "promote_and_publish_agent", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "Promote to Production",
        },
        title="Promote to Production",
    )
    version_id: str = Field(..., title="Version ID", description="The agent version to promote")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    user_id: Optional[str] = Field(None, title="User ID")
    user_name: Optional[str] = Field(None, title="User Name")
    user_email: Optional[str] = Field(None, title="User Email")
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLExecuteAgentConfig(BaseModel):
    """Execute an agent with a message."""

    operation: Literal["execute_agent"] = Field(
        "execute_agent",
        json_schema_extra={
            "const": "execute_agent", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "Execute Agent",
        },
        title="Execute Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to execute")
    message: str = Field(..., title="Message", description="User message to send to the agent")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    execution_id: Optional[str] = Field(None, title="Execution ID")
    version_id: Optional[str] = Field(None, title="Version ID")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    input_variables: Optional[str] = Field(None, title="Input Variables", description="JSON object")
    attachments: Optional[str] = Field(
        None, title="Attachments",
        description="JSON array of {type, imageUrl} attachment objects",
    )
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLGetAgentsDeprecatedConfig(BaseModel):
    """List agents (deprecated public-api endpoint)."""

    operation: Literal["get_agents_deprecated"] = Field(
        "get_agents_deprecated",
        json_schema_extra={
            "const": "get_agents_deprecated", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "List Agents (Deprecated)",
        },
        title="List Agents (Deprecated)",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: str = Field(..., title="Limit", description="Max results to return")
    offset: str = Field(..., title="Offset", description="Number of results to skip (pagination)")
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLGetAgentByIdDeprecatedConfig(BaseModel):
    """Get an agent by id (deprecated public-api endpoint)."""

    operation: Literal["get_agent_by_id_deprecated"] = Field(
        "get_agent_by_id_deprecated",
        json_schema_extra={
            "const": "get_agent_by_id_deprecated", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "Get Agent (Deprecated)",
        },
        title="Get Agent (Deprecated)",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to fetch")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


class GHLExecuteAgentDeprecatedConfig(BaseModel):
    """Execute an agent (deprecated public-api endpoint)."""

    operation: Literal["execute_agent_deprecated"] = Field(
        "execute_agent_deprecated",
        json_schema_extra={
            "const": "execute_agent_deprecated", "ui:hidden": True,
            "x-category": "Agent Studio", "x-is-trigger": False,
            "x-display-name": "Execute Agent (Deprecated)",
        },
        title="Execute Agent (Deprecated)",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to execute")
    message: str = Field(..., title="Message", description="User message to send to the agent")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    execution_id: Optional[str] = Field(None, title="Execution ID")
    version_id: Optional[str] = Field(None, title="Version ID")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    input_variables: Optional[str] = Field(None, title="Input Variables", description="JSON object")
    attachments: Optional[str] = Field(
        None, title="Attachments",
        description="JSON array of {type, imageUrl} attachment objects",
    )
    source: Optional[str] = Field(None, title="Source", description="Optional source query param")


async def _create_studio_agent(node, c, token):
    params = {"source": c.source}
    body = {
        "locationId": c.location_id, "name": c.name, "description": c.description,
        "agencyId": c.agency_id, "authorId": c.author_id, "authorName": c.author_name,
        "authorEmail": c.author_email, "status": c.status,
        "version": _ghl_json(c.version), "nodes": _ghl_json(c.nodes),
        "edges": _ghl_json(c.edges),
    }
    return await node._request(
        token, "POST", "/agent-studio/agent", version="2021-04-15",
        params=params, json_body=body, action_name="create_studio_agent",
    )


async def _get_agents(node, c, token):
    params = {
        "locationId": c.location_id, "isPublished": _ghl_bool(c.is_published),
        "limit": c.limit, "offset": c.offset, "source": c.source,
    }
    return await node._request(
        token, "GET", "/agent-studio/agent", version="2021-04-15",
        params=params, action_name="get_agents",
    )


async def _update_agent_version(node, c, token):
    params = {"source": c.source}
    body = {
        "locationId": c.location_id, "versionName": c.version_name,
        "description": c.description, "nodes": _ghl_json(c.nodes),
        "edges": _ghl_json(c.edges), "globalVariables": _ghl_json(c.global_variables),
        "inputVariables": _ghl_json(c.input_variables),
        "runtimeVariables": _ghl_json(c.runtime_variables),
        "globalConfig": _ghl_json(c.global_config),
        "userId": c.user_id, "userName": c.user_name,
    }
    return await node._request(
        token, "PATCH", f"/agent-studio/agent/versions/{c.version_id}",
        version="2021-04-15", params=params, json_body=body,
        action_name="update_agent_version",
    )


async def _update_agent_metadata(node, c, token):
    params = {"source": c.source}
    body = {
        "locationId": c.location_id, "name": c.name,
        "description": c.description, "status": c.status,
    }
    return await node._request(
        token, "PATCH", f"/agent-studio/agent/{c.agent_id}",
        version="2021-04-15", params=params, json_body=body,
        action_name="update_agent_metadata",
    )


async def _delete_studio_agent(node, c, token):
    params = {"locationId": c.location_id, "source": c.source}
    return await node._request(
        token, "DELETE", f"/agent-studio/agent/{c.agent_id}",
        version="2021-04-15", params=params, action_name="delete_studio_agent",
    )


async def _get_agent_by_id(node, c, token):
    params = {"locationId": c.location_id, "source": c.source}
    return await node._request(
        token, "GET", f"/agent-studio/agent/{c.agent_id}",
        version="2021-04-15", params=params, action_name="get_agent_by_id",
    )


async def _promote_and_publish_agent(node, c, token):
    params = {"source": c.source}
    body = {
        "locationId": c.location_id, "userId": c.user_id,
        "userName": c.user_name, "userEmail": c.user_email,
    }
    return await node._request(
        token, "POST", f"/agent-studio/agent/versions/{c.version_id}/publish",
        version="2021-04-15", params=params, json_body=body,
        action_name="promote_and_publish_agent",
    )


async def _execute_agent(node, c, token):
    params = {"source": c.source}
    body = {
        "message": c.message, "executionId": c.execution_id,
        "inputVariables": _ghl_json(c.input_variables), "versionId": c.version_id,
        "attachments": _ghl_json(c.attachments), "locationId": c.location_id,
        "contactId": c.contact_id,
    }
    return await node._request(
        token, "POST", f"/agent-studio/agent/{c.agent_id}/execute",
        version="2021-04-15", params=params, json_body=body,
        action_name="execute_agent",
    )


async def _get_agents_deprecated(node, c, token):
    params = {
        "locationId": c.location_id, "limit": c.limit,
        "offset": c.offset, "source": c.source,
    }
    return await node._request(
        token, "GET", "/agent-studio/public-api/agents", version="2021-04-15",
        params=params, action_name="get_agents_deprecated",
    )


async def _get_agent_by_id_deprecated(node, c, token):
    params = {"locationId": c.location_id, "source": c.source}
    return await node._request(
        token, "GET", f"/agent-studio/public-api/agents/{c.agent_id}",
        version="2021-04-15", params=params,
        action_name="get_agent_by_id_deprecated",
    )


async def _execute_agent_deprecated(node, c, token):
    params = {"source": c.source}
    body = {
        "message": c.message, "executionId": c.execution_id,
        "inputVariables": _ghl_json(c.input_variables), "versionId": c.version_id,
        "attachments": _ghl_json(c.attachments), "locationId": c.location_id,
        "contactId": c.contact_id,
    }
    return await node._request(
        token, "POST", f"/agent-studio/public-api/agents/{c.agent_id}/execute",
        version="2021-04-15", params=params, json_body=body,
        action_name="execute_agent_deprecated",
    )


GHL_OPERATION_CONFIGS += [
    GHLCreateAgentConfig,
    GHLGetAgentsConfig,
    GHLUpdateAgentVersionConfig,
    GHLUpdateAgentMetadataConfig,
    GHLDeleteAgentConfig,
    GHLGetAgentByIdConfig,
    GHLPromoteAndPublishAgentConfig,
    GHLExecuteAgentConfig,
    GHLGetAgentsDeprecatedConfig,
    GHLGetAgentByIdDeprecatedConfig,
    GHLExecuteAgentDeprecatedConfig,
]
GHL_OPERATION_HANDLERS.update({
    "create_studio_agent": _create_studio_agent,
    "get_agents": _get_agents,
    "update_agent_version": _update_agent_version,
    "update_agent_metadata": _update_agent_metadata,
    "delete_studio_agent": _delete_studio_agent,
    "get_agent_by_id": _get_agent_by_id,
    "promote_and_publish_agent": _promote_and_publish_agent,
    "execute_agent": _execute_agent,
    "get_agents_deprecated": _get_agents_deprecated,
    "get_agent_by_id_deprecated": _get_agent_by_id_deprecated,
    "execute_agent_deprecated": _execute_agent_deprecated,
})


# ---- associations.py ----
class GHLCreateRelationConfig(BaseModel):
    """Create a relation between two associated records."""

    operation: Literal["create_relation"] = Field(
        "create_relation",
        json_schema_extra={
            "const": "create_relation", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Create Relation",
        },
        title="Create Relation",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    association_id: str = Field(..., title="Association ID", description="The association these records relate through")
    first_record_id: str = Field(..., title="First Record ID", description="Id of the first record")
    second_record_id: str = Field(..., title="Second Record ID", description="Id of the second record")


class GHLGetRelationsByRecordIdConfig(BaseModel):
    """Get all relations by record id."""

    operation: Literal["get_relations_by_record_id"] = Field(
        "get_relations_by_record_id",
        json_schema_extra={
            "const": "get_relations_by_record_id", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Get Relations By Record",
        },
        title="Get Relations By Record",
    )
    record_id: str = Field(..., title="Record ID", description="The record to fetch relations for")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    skip: str = Field(..., title="Skip", description="Number of results to skip (pagination)")
    limit: str = Field(..., title="Limit", description="Max results to return")
    association_ids: Optional[str] = Field(None, title="Association IDs", description="Comma-separated association ids to filter by")


class GHLDeleteRelationConfig(BaseModel):
    """Delete a relation."""

    operation: Literal["delete_relation"] = Field(
        "delete_relation",
        json_schema_extra={
            "const": "delete_relation", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Delete Relation",
        },
        title="Delete Relation",
    )
    relation_id: str = Field(..., title="Relation ID", description="The relation to delete")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLGetAssociationKeyByKeyNameConfig(BaseModel):
    """Get an association by its unique key name."""

    operation: Literal["get_association_key_by_key_name"] = Field(
        "get_association_key_by_key_name",
        json_schema_extra={
            "const": "get_association_key_by_key_name", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Get Association By Key Name",
        },
        title="Get Association By Key Name",
    )
    key_name: str = Field(..., title="Key Name", description="The association's unique key name")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLGetAssociationByObjectKeysConfig(BaseModel):
    """Get an association by object keys."""

    operation: Literal["get_association_by_object_keys"] = Field(
        "get_association_by_object_keys",
        json_schema_extra={
            "const": "get_association_by_object_keys", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Get Association By Object Keys",
        },
        title="Get Association By Object Keys",
    )
    object_key: Optional[str] = Field(None, title="Object Key", description="Object key (e.g. custom_objects.children)")
    location_id: Optional[str] = Field(None, title="Location ID", description="Sub-account (location) id")


class GHLUpdateAssociationConfig(BaseModel):
    """Update an association by id."""

    operation: Literal["update_association"] = Field(
        "update_association",
        json_schema_extra={
            "const": "update_association", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Update Association",
        },
        title="Update Association",
    )
    association_id: str = Field(..., title="Association ID", description="The association to update")
    first_object_label: str = Field(..., title="First Object Label", description="First object's association label (e.g. student)")
    second_object_label: str = Field(..., title="Second Object Label", description="Second object's association label (e.g. tutor)")


class GHLDeleteAssociationConfig(BaseModel):
    """Delete an association."""

    operation: Literal["delete_association"] = Field(
        "delete_association",
        json_schema_extra={
            "const": "delete_association", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Delete Association",
        },
        title="Delete Association",
    )
    association_id: str = Field(..., title="Association ID", description="The association to delete")


class GHLGetAssociationByIdConfig(BaseModel):
    """Get an association by id."""

    operation: Literal["get_association_by_id"] = Field(
        "get_association_by_id",
        json_schema_extra={
            "const": "get_association_by_id", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Get Association By ID",
        },
        title="Get Association By ID",
    )
    association_id: str = Field(..., title="Association ID", description="The association to fetch")


class GHLCreateAssociationConfig(BaseModel):
    """Create an association."""

    operation: Literal["create_association"] = Field(
        "create_association",
        json_schema_extra={
            "const": "create_association", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Create Association",
        },
        title="Create Association",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    key: str = Field(..., title="Key", description="Association's unique key (e.g. student_teacher)")
    first_object_label: str = Field(..., title="First Object Label", description="First object's association label (e.g. student)")
    first_object_key: str = Field(..., title="First Object Key", description="First object's key (e.g. custom_objects.children)")
    second_object_label: str = Field(..., title="Second Object Label", description="Second object's association label (e.g. Teacher)")
    second_object_key: str = Field(..., title="Second Object Key", description="Second object's key (e.g. contact)")


class GHLFindAssociationsConfig(BaseModel):
    """Get all associations for a sub-account / location."""

    operation: Literal["find_associations"] = Field(
        "find_associations",
        json_schema_extra={
            "const": "find_associations", "ui:hidden": True,
            "x-category": "Associations", "x-is-trigger": False,
            "x-display-name": "Find Associations",
        },
        title="Find Associations",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    skip: str = Field(..., title="Skip", description="Number of results to skip (pagination)")
    limit: str = Field(..., title="Limit", description="Max results to return")


async def _create_relation(node, c, token):
    body = {
        "locationId": c.location_id, "associationId": c.association_id,
        "firstRecordId": c.first_record_id, "secondRecordId": c.second_record_id,
    }
    return await node._request(token, "POST", "/associations/relations", json_body=body, action_name="create_relation")


async def _get_relations_by_record_id(node, c, token):
    params = {
        "locationId": c.location_id, "skip": _ghl_num(c.skip), "limit": _ghl_num(c.limit),
        "associationIds": _ghl_csv(c.association_ids),
    }
    return await node._request(token, "GET", f"/associations/relations/{c.record_id}", params=params, action_name="get_relations_by_record_id")


async def _delete_relation(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "DELETE", f"/associations/relations/{c.relation_id}", params=params, action_name="delete_relation")


async def _get_association_key_by_key_name(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", f"/associations/key/{c.key_name}", params=params, action_name="get_association_key_by_key_name")


async def _get_association_by_object_keys(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", f"/associations/objectKey/{c.object_key}", params=params, action_name="get_association_by_object_keys")


async def _update_association(node, c, token):
    body = {"firstObjectLabel": c.first_object_label, "secondObjectLabel": c.second_object_label}
    return await node._request(token, "PUT", f"/associations/{c.association_id}", json_body=body, action_name="update_association")


async def _delete_association(node, c, token):
    return await node._request(token, "DELETE", f"/associations/{c.association_id}", action_name="delete_association")


async def _get_association_by_id(node, c, token):
    return await node._request(token, "GET", f"/associations/{c.association_id}", action_name="get_association_by_id")


async def _create_association(node, c, token):
    body = {
        "locationId": c.location_id, "key": c.key,
        "firstObjectLabel": c.first_object_label, "firstObjectKey": c.first_object_key,
        "secondObjectLabel": c.second_object_label, "secondObjectKey": c.second_object_key,
    }
    return await node._request(token, "POST", "/associations/", json_body=body, action_name="create_association")


async def _find_associations(node, c, token):
    params = {"locationId": c.location_id, "skip": _ghl_num(c.skip), "limit": _ghl_num(c.limit)}
    return await node._request(token, "GET", "/associations/", params=params, action_name="find_associations")


GHL_OPERATION_CONFIGS += [
    GHLCreateRelationConfig,
    GHLGetRelationsByRecordIdConfig,
    GHLDeleteRelationConfig,
    GHLGetAssociationKeyByKeyNameConfig,
    GHLGetAssociationByObjectKeysConfig,
    GHLUpdateAssociationConfig,
    GHLDeleteAssociationConfig,
    GHLGetAssociationByIdConfig,
    GHLCreateAssociationConfig,
    GHLFindAssociationsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "create_relation": _create_relation,
    "get_relations_by_record_id": _get_relations_by_record_id,
    "delete_relation": _delete_relation,
    "get_association_key_by_key_name": _get_association_key_by_key_name,
    "get_association_by_object_keys": _get_association_by_object_keys,
    "update_association": _update_association,
    "delete_association": _delete_association,
    "get_association_by_id": _get_association_by_id,
    "create_association": _create_association,
    "find_associations": _find_associations,
})


# ---- blogs.py ----
class GHLCheckBlogUrlSlugExistsConfig(BaseModel):
    """Check whether a blog post url slug already exists for a location."""

    operation: Literal["check_url_slug_exists"] = Field(
        "check_url_slug_exists",
        json_schema_extra={
            "const": "check_url_slug_exists", "ui:hidden": True,
            "x-category": "Blogs", "x-is-trigger": False,
            "x-display-name": "Check Blog URL Slug",
        },
        title="Check Blog URL Slug",
    )
    url_slug: str = Field(..., title="URL Slug", description="The url slug to check")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    post_id: Optional[str] = Field(None, title="Post ID", description="Exclude this post id from the check")


class GHLUpdateBlogPostConfig(BaseModel):
    """Update a blog post."""

    operation: Literal["update_blog_post"] = Field(
        "update_blog_post",
        json_schema_extra={
            "const": "update_blog_post", "ui:hidden": True,
            "x-category": "Blogs", "x-is-trigger": False,
            "x-display-name": "Update Blog Post",
        },
        title="Update Blog Post",
    )
    post_id: str = Field(..., title="Post ID", description="The blog post to update")
    title: str = Field(..., title="Title", description="Blog post title")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    blog_id: str = Field(..., title="Blog ID", description="The blog (site) this post belongs to")
    image_url: str = Field(..., title="Image URL", description="Cover image url")
    description: str = Field(..., title="Description", description="Meta description")
    raw_html: str = Field(..., title="Raw HTML", description="Post body HTML")
    status: str = Field(
        ..., title="Status",
        json_schema_extra={
            "enum": ["DRAFT", "PUBLISHED", "SCHEDULED", "ARCHIVED"],
            "x-enum-searchable": True,
        },
    )
    image_alt_text: str = Field(..., title="Image Alt Text")
    categories: str = Field(..., title="Categories", description="JSON array of category ids")
    author: str = Field(..., title="Author", description="Author id")
    url_slug: str = Field(..., title="URL Slug")
    published_at: str = Field(..., title="Published At", description="ISO timestamp")
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags")
    canonical_link: Optional[str] = Field(None, title="Canonical Link")


class GHLCreateBlogPostConfig(BaseModel):
    """Create a blog post."""

    operation: Literal["create_blog_post"] = Field(
        "create_blog_post",
        json_schema_extra={
            "const": "create_blog_post", "ui:hidden": True,
            "x-category": "Blogs", "x-is-trigger": False,
            "x-display-name": "Create Blog Post",
        },
        title="Create Blog Post",
    )
    title: str = Field(..., title="Title", description="Blog post title")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    blog_id: str = Field(..., title="Blog ID", description="The blog (site) this post belongs to")
    image_url: str = Field(..., title="Image URL", description="Cover image url")
    description: str = Field(..., title="Description", description="Meta description")
    raw_html: str = Field(..., title="Raw HTML", description="Post body HTML")
    status: str = Field(
        ..., title="Status",
        json_schema_extra={
            "enum": ["DRAFT", "PUBLISHED", "SCHEDULED", "ARCHIVED"],
            "x-enum-searchable": True,
        },
    )
    image_alt_text: str = Field(..., title="Image Alt Text")
    categories: str = Field(..., title="Categories", description="JSON array of category ids")
    author: str = Field(..., title="Author", description="Author id")
    url_slug: str = Field(..., title="URL Slug")
    published_at: str = Field(..., title="Published At", description="ISO timestamp")
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags")
    canonical_link: Optional[str] = Field(None, title="Canonical Link")


class GHLGetAllBlogAuthorsByLocationConfig(BaseModel):
    """List blog authors for a location."""

    operation: Literal["get_all_blog_authors_by_location"] = Field(
        "get_all_blog_authors_by_location",
        json_schema_extra={
            "const": "get_all_blog_authors_by_location", "ui:hidden": True,
            "x-category": "Blogs", "x-is-trigger": False,
            "x-display-name": "List Blog Authors",
        },
        title="List Blog Authors",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: str = Field(..., title="Limit", description="Max results to return")
    offset: str = Field(..., title="Offset", description="Number of results to skip (pagination)")


class GHLGetAllBlogCategoriesByLocationConfig(BaseModel):
    """List blog categories for a location."""

    operation: Literal["get_all_blog_categories_by_location"] = Field(
        "get_all_blog_categories_by_location",
        json_schema_extra={
            "const": "get_all_blog_categories_by_location", "ui:hidden": True,
            "x-category": "Blogs", "x-is-trigger": False,
            "x-display-name": "List Blog Categories",
        },
        title="List Blog Categories",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: str = Field(..., title="Limit", description="Max results to return")
    offset: str = Field(..., title="Offset", description="Number of results to skip (pagination)")


class GHLGetBlogPostsByBlogConfig(BaseModel):
    """Get blog posts by blog id."""

    operation: Literal["get_blog_posts_by_blog"] = Field(
        "get_blog_posts_by_blog",
        json_schema_extra={
            "const": "get_blog_posts_by_blog", "ui:hidden": True,
            "x-category": "Blogs", "x-is-trigger": False,
            "x-display-name": "List Blog Posts",
        },
        title="List Blog Posts",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    blog_id: str = Field(..., title="Blog ID", description="The blog (site) to list posts for")
    limit: str = Field(..., title="Limit", description="Max results to return")
    offset: str = Field(..., title="Offset", description="Number of results to skip (pagination)")
    search_term: Optional[str] = Field(None, title="Search Term")
    status: Optional[str] = Field(
        None, title="Status",
        json_schema_extra={
            "enum": ["PUBLISHED", "SCHEDULED", "ARCHIVED", "DRAFT"],
            "x-enum-searchable": True,
        },
    )


class GHLGetBlogsByLocationConfig(BaseModel):
    """List blogs (sites) for a location."""

    operation: Literal["get_blogs_by_location"] = Field(
        "get_blogs_by_location",
        json_schema_extra={
            "const": "get_blogs_by_location", "ui:hidden": True,
            "x-category": "Blogs", "x-is-trigger": False,
            "x-display-name": "List Blogs",
        },
        title="List Blogs",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    skip: str = Field(..., title="Skip", description="Number of results to skip (pagination)")
    limit: str = Field(..., title="Limit", description="Max results to return")
    search_term: Optional[str] = Field(None, title="Search Term")


async def _check_url_slug_exists(node, c, token):
    params = {"urlSlug": c.url_slug, "locationId": c.location_id, "postId": c.post_id}
    return await node._request(token, "GET", "/blogs/posts/url-slug-exists", params=params, action_name="check_url_slug_exists")


async def _update_blog_post(node, c, token):
    body = {
        "title": c.title, "locationId": c.location_id, "blogId": c.blog_id,
        "imageUrl": c.image_url, "description": c.description, "rawHTML": c.raw_html,
        "status": c.status, "imageAltText": c.image_alt_text,
        "categories": _ghl_json(c.categories), "tags": _ghl_csv(c.tags),
        "author": c.author, "urlSlug": c.url_slug, "canonicalLink": c.canonical_link,
        "publishedAt": c.published_at,
    }
    return await node._request(token, "PUT", f"/blogs/posts/{c.post_id}", json_body=body, action_name="update_blog_post")


async def _create_blog_post(node, c, token):
    body = {
        "title": c.title, "locationId": c.location_id, "blogId": c.blog_id,
        "imageUrl": c.image_url, "description": c.description, "rawHTML": c.raw_html,
        "status": c.status, "imageAltText": c.image_alt_text,
        "categories": _ghl_json(c.categories), "tags": _ghl_csv(c.tags),
        "author": c.author, "urlSlug": c.url_slug, "canonicalLink": c.canonical_link,
        "publishedAt": c.published_at,
    }
    return await node._request(token, "POST", "/blogs/posts", json_body=body, action_name="create_blog_post")


async def _get_all_blog_authors_by_location(node, c, token):
    params = {"locationId": c.location_id, "limit": _ghl_num(c.limit), "offset": _ghl_num(c.offset)}
    return await node._request(token, "GET", "/blogs/authors", params=params, action_name="get_all_blog_authors_by_location")


async def _get_all_blog_categories_by_location(node, c, token):
    params = {"locationId": c.location_id, "limit": _ghl_num(c.limit), "offset": _ghl_num(c.offset)}
    return await node._request(token, "GET", "/blogs/categories", params=params, action_name="get_all_blog_categories_by_location")


async def _get_blog_posts_by_blog(node, c, token):
    params = {
        "locationId": c.location_id, "blogId": c.blog_id,
        "limit": _ghl_num(c.limit), "offset": _ghl_num(c.offset),
        "searchTerm": c.search_term, "status": c.status,
    }
    return await node._request(token, "GET", "/blogs/posts/all", params=params, action_name="get_blog_posts_by_blog")


async def _get_blogs_by_location(node, c, token):
    params = {
        "locationId": c.location_id, "skip": _ghl_num(c.skip),
        "limit": _ghl_num(c.limit), "searchTerm": c.search_term,
    }
    return await node._request(token, "GET", "/blogs/site/all", params=params, action_name="get_blogs_by_location")


GHL_OPERATION_CONFIGS += [
    GHLCheckBlogUrlSlugExistsConfig,
    GHLUpdateBlogPostConfig,
    GHLCreateBlogPostConfig,
    GHLGetAllBlogAuthorsByLocationConfig,
    GHLGetAllBlogCategoriesByLocationConfig,
    GHLGetBlogPostsByBlogConfig,
    GHLGetBlogsByLocationConfig,
]
GHL_OPERATION_HANDLERS.update({
    "check_url_slug_exists": _check_url_slug_exists,
    "update_blog_post": _update_blog_post,
    "create_blog_post": _create_blog_post,
    "get_all_blog_authors_by_location": _get_all_blog_authors_by_location,
    "get_all_blog_categories_by_location": _get_all_blog_categories_by_location,
    "get_blog_posts_by_blog": _get_blog_posts_by_blog,
    "get_blogs_by_location": _get_blogs_by_location,
})


# ---- brand_boards.py ----
class GHLGetBrandBoardsByLocationConfig(BaseModel):
    """List brand boards for a location (sub-account)."""

    operation: Literal["get_brand_boards_by_location"] = Field(
        "get_brand_boards_by_location",
        json_schema_extra={
            "const": "get_brand_boards_by_location", "ui:hidden": True,
            "x-category": "Brand Boards", "x-is-trigger": False,
            "x-display-name": "List Brand Boards",
        },
        title="List Brand Boards",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of results to skip (pagination)")
    search: Optional[str] = Field(None, title="Search", description="Search term to filter brand boards")
    deleted: Optional[str] = Field(
        None, title="Include Deleted", description="Include deleted brand boards",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLGetBrandBoardByIdConfig(BaseModel):
    """Get a brand board by id."""

    operation: Literal["get_brand_board_by_id"] = Field(
        "get_brand_board_by_id",
        json_schema_extra={
            "const": "get_brand_board_by_id", "ui:hidden": True,
            "x-category": "Brand Boards", "x-is-trigger": False,
            "x-display-name": "Get Brand Board",
        },
        title="Get Brand Board",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    brand_board_id: str = Field(..., title="Brand Board ID", description="The brand board to fetch")


class GHLCreateBrandBoardConfig(BaseModel):
    """Create a new brand board."""

    operation: Literal["create_brand_board"] = Field(
        "create_brand_board",
        json_schema_extra={
            "const": "create_brand_board", "ui:hidden": True,
            "x-category": "Brand Boards", "x-is-trigger": False,
            "x-display-name": "Create Brand Board",
        },
        title="Create Brand Board",
    )
    location_id: str = Field(..., title="Location ID", description="Location ID where the brand board will be created")
    name: str = Field(..., title="Name", description="Name of the brand board")
    logos: Optional[str] = Field(None, title="Logos", description="JSON array of logos for the brand board")
    colors: Optional[str] = Field(None, title="Colors", description="JSON array of colors for the brand board")
    fonts: Optional[str] = Field(None, title="Fonts", description="JSON array of fonts for the brand board")
    default: Optional[str] = Field(
        None, title="Default", description="Set as the default brand board for this location",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    brand_board_id: Optional[str] = Field(None, title="Source Brand Board ID", description="Source brand board ID to copy from (creates a new brand board)")
    parent_id: Optional[str] = Field(None, title="Parent Folder ID", description="Parent folder ID in media library for organizing brand boards")
    type: Optional[str] = Field(
        None, title="Source Type", description="Source type indicating how the brand board was created",
        json_schema_extra={
            "enum": ["template", "blank", "snapshot"],
            "x-enum-searchable": True,
        },
    )


class GHLUpdateBrandBoardConfig(BaseModel):
    """Update a brand board."""

    operation: Literal["update_brand_board"] = Field(
        "update_brand_board",
        json_schema_extra={
            "const": "update_brand_board", "ui:hidden": True,
            "x-category": "Brand Boards", "x-is-trigger": False,
            "x-display-name": "Update Brand Board",
        },
        title="Update Brand Board",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    brand_board_id: str = Field(..., title="Brand Board ID", description="The brand board to update")
    name: Optional[str] = Field(None, title="Name", description="Name of the brand board")
    logos: Optional[str] = Field(None, title="Logos", description="JSON array of logos for the brand board")
    colors: Optional[str] = Field(None, title="Colors", description="JSON array of colors for the brand board")
    fonts: Optional[str] = Field(None, title="Fonts", description="JSON array of fonts for the brand board")
    default: Optional[str] = Field(
        None, title="Default", description="Set as the default brand board for this location",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    parent_id: Optional[str] = Field(None, title="Parent Folder ID", description="Parent folder ID in media library (reserved for future use)")


class GHLDeleteBrandBoardConfig(BaseModel):
    """Delete a brand board."""

    operation: Literal["delete_brand_board"] = Field(
        "delete_brand_board",
        json_schema_extra={
            "const": "delete_brand_board", "ui:hidden": True,
            "x-category": "Brand Boards", "x-is-trigger": False,
            "x-display-name": "Delete Brand Board",
        },
        title="Delete Brand Board",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    brand_board_id: str = Field(..., title="Brand Board ID", description="The brand board to delete")


async def _get_brand_boards_by_location(node, c, token):
    params = {
        "limit": c.limit, "offset": c.offset, "search": c.search,
        "deleted": _ghl_bool(c.deleted),
    }
    return await node._request(
        token, "GET", f"/brand-boards/{c.location_id}",
        params=params, action_name="get_brand_boards_by_location",
    )


async def _get_brand_board_by_id(node, c, token):
    return await node._request(
        token, "GET", f"/brand-boards/{c.location_id}/{c.brand_board_id}",
        action_name="get_brand_board_by_id",
    )


async def _create_brand_board(node, c, token):
    body = {
        "locationId": c.location_id, "name": c.name,
        "logos": _ghl_json(c.logos), "colors": _ghl_json(c.colors),
        "fonts": _ghl_json(c.fonts), "default": _ghl_bool(c.default),
        "brandBoardId": c.brand_board_id, "parentId": c.parent_id, "type": c.type,
    }
    return await node._request(
        token, "POST", "/brand-boards/",
        json_body=body, action_name="create_brand_board",
    )


async def _update_brand_board(node, c, token):
    body = {
        "name": c.name, "logos": _ghl_json(c.logos), "colors": _ghl_json(c.colors),
        "fonts": _ghl_json(c.fonts), "default": _ghl_bool(c.default),
        "parentId": c.parent_id,
    }
    return await node._request(
        token, "PATCH", f"/brand-boards/{c.location_id}/{c.brand_board_id}",
        json_body=body, action_name="update_brand_board",
    )


async def _delete_brand_board(node, c, token):
    return await node._request(
        token, "DELETE", f"/brand-boards/{c.location_id}/{c.brand_board_id}",
        action_name="delete_brand_board",
    )


GHL_OPERATION_CONFIGS += [
    GHLGetBrandBoardsByLocationConfig,
    GHLGetBrandBoardByIdConfig,
    GHLCreateBrandBoardConfig,
    GHLUpdateBrandBoardConfig,
    GHLDeleteBrandBoardConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_brand_boards_by_location": _get_brand_boards_by_location,
    "get_brand_board_by_id": _get_brand_board_by_id,
    "create_brand_board": _create_brand_board,
    "update_brand_board": _update_brand_board,
    "delete_brand_board": _delete_brand_board,
})


# ---- businesses.py ----
class GHLGetBusinessesByLocationConfig(BaseModel):
    """List businesses for a location (sub-account)."""

    operation: Literal["get_businesses_by_location"] = Field(
        "get_businesses_by_location",
        json_schema_extra={
            "const": "get_businesses_by_location", "ui:hidden": True,
            "x-category": "Businesses", "x-is-trigger": False,
            "x-display-name": "List Businesses",
        },
        title="List Businesses",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")


class GHLCreateBusinessConfig(BaseModel):
    """Create a business within a location."""

    operation: Literal["create_business"] = Field(
        "create_business",
        json_schema_extra={
            "const": "create_business", "ui:hidden": True,
            "x-category": "Businesses", "x-is-trigger": False,
            "x-display-name": "Create Business",
        },
        title="Create Business",
    )
    name: str = Field(..., title="Name", description="Business name")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    phone: Optional[str] = Field(None, title="Phone")
    email: Optional[str] = Field(None, title="Email")
    website: Optional[str] = Field(None, title="Website")
    address: Optional[str] = Field(None, title="Address")
    city: Optional[str] = Field(None, title="City")
    postal_code: Optional[str] = Field(None, title="Postal Code")
    state: Optional[str] = Field(None, title="State")
    country: Optional[str] = Field(None, title="Country")
    description: Optional[str] = Field(None, title="Description")


class GHLGetBusinessConfig(BaseModel):
    """Get a business by id."""

    operation: Literal["get_business"] = Field(
        "get_business",
        json_schema_extra={
            "const": "get_business", "ui:hidden": True,
            "x-category": "Businesses", "x-is-trigger": False,
            "x-display-name": "Get Business",
        },
        title="Get Business",
    )
    business_id: str = Field(..., title="Business ID", description="The business to fetch")


class GHLUpdateBusinessConfig(BaseModel):
    """Update a business."""

    operation: Literal["update_business"] = Field(
        "update_business",
        json_schema_extra={
            "const": "update_business", "ui:hidden": True,
            "x-category": "Businesses", "x-is-trigger": False,
            "x-display-name": "Update Business",
        },
        title="Update Business",
    )
    business_id: str = Field(..., title="Business ID", description="The business to update")
    name: Optional[str] = Field(None, title="Name")
    phone: Optional[str] = Field(None, title="Phone")
    email: Optional[str] = Field(None, title="Email")
    website: Optional[str] = Field(None, title="Website")
    address: Optional[str] = Field(None, title="Address")
    city: Optional[str] = Field(None, title="City")
    postal_code: Optional[str] = Field(None, title="Postal Code")
    state: Optional[str] = Field(None, title="State")
    country: Optional[str] = Field(None, title="Country")
    description: Optional[str] = Field(None, title="Description")


class GHLDeleteBusinessConfig(BaseModel):
    """Delete a business."""

    operation: Literal["delete_business"] = Field(
        "delete_business",
        json_schema_extra={
            "const": "delete_business", "ui:hidden": True,
            "x-category": "Businesses", "x-is-trigger": False,
            "x-display-name": "Delete Business",
        },
        title="Delete Business",
    )
    business_id: str = Field(..., title="Business ID", description="The business to delete")


async def _get_businesses_by_location(node, c, token):
    params = {"locationId": c.location_id, "limit": c.limit, "skip": c.skip}
    return await node._request(token, "GET", "/businesses/", params=params, action_name="get_businesses_by_location")


async def _create_business(node, c, token):
    body = {
        "name": c.name, "locationId": c.location_id, "phone": c.phone, "email": c.email,
        "website": c.website, "address": c.address, "city": c.city, "postalCode": c.postal_code,
        "state": c.state, "country": c.country, "description": c.description,
    }
    return await node._request(token, "POST", "/businesses/", json_body=body, action_name="create_business")


async def _get_business(node, c, token):
    return await node._request(token, "GET", f"/businesses/{c.business_id}", action_name="get_business")


async def _update_business(node, c, token):
    body = {
        "name": c.name, "phone": c.phone, "email": c.email, "website": c.website,
        "address": c.address, "city": c.city, "postalCode": c.postal_code,
        "state": c.state, "country": c.country, "description": c.description,
    }
    return await node._request(token, "PUT", f"/businesses/{c.business_id}", json_body=body, action_name="update_business")


async def _delete_business(node, c, token):
    return await node._request(token, "DELETE", f"/businesses/{c.business_id}", action_name="delete_business")


GHL_OPERATION_CONFIGS += [
    GHLGetBusinessesByLocationConfig,
    GHLCreateBusinessConfig,
    GHLGetBusinessConfig,
    GHLUpdateBusinessConfig,
    GHLDeleteBusinessConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_businesses_by_location": _get_businesses_by_location,
    "create_business": _create_business,
    "get_business": _get_business,
    "update_business": _update_business,
    "delete_business": _delete_business,
})


# ---- calendars.py ----
_CAL_VERSION = "2021-04-15"


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

class GHLGetCalendarGroupsConfig(BaseModel):
    """List calendar groups for a location."""

    operation: Literal["get_calendar_groups"] = Field(
        "get_calendar_groups",
        json_schema_extra={
            "const": "get_calendar_groups", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "List Calendar Groups",
        },
        title="List Calendar Groups",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateCalendarGroupConfig(BaseModel):
    """Create a calendar group."""

    operation: Literal["create_calendar_group"] = Field(
        "create_calendar_group",
        json_schema_extra={
            "const": "create_calendar_group", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Create Calendar Group",
        },
        title="Create Calendar Group",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name", description="Group name")
    description: str = Field(..., title="Description", description="Group description")
    slug: str = Field(..., title="Slug", description="Group slug")
    is_active: Optional[str] = Field(
        None, title="Is Active",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLValidateCalendarGroupSlugConfig(BaseModel):
    """Validate a calendar group slug is available."""

    operation: Literal["validate_calendar_group_slug"] = Field(
        "validate_calendar_group_slug",
        json_schema_extra={
            "const": "validate_calendar_group_slug", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Validate Group Slug",
        },
        title="Validate Group Slug",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    slug: str = Field(..., title="Slug", description="Slug to validate")


class GHLDeleteCalendarGroupConfig(BaseModel):
    """Delete a calendar group."""

    operation: Literal["delete_calendar_group"] = Field(
        "delete_calendar_group",
        json_schema_extra={
            "const": "delete_calendar_group", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Delete Calendar Group",
        },
        title="Delete Calendar Group",
    )
    group_id: str = Field(..., title="Group ID", description="The group to delete")


class GHLUpdateCalendarGroupConfig(BaseModel):
    """Update a calendar group."""

    operation: Literal["update_calendar_group"] = Field(
        "update_calendar_group",
        json_schema_extra={
            "const": "update_calendar_group", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Update Calendar Group",
        },
        title="Update Calendar Group",
    )
    group_id: str = Field(..., title="Group ID", description="The group to update")
    name: str = Field(..., title="Name", description="Group name")
    description: str = Field(..., title="Description", description="Group description")
    slug: str = Field(..., title="Slug", description="Group slug")


class GHLDisableCalendarGroupConfig(BaseModel):
    """Enable or disable a calendar group."""

    operation: Literal["disable_calendar_group"] = Field(
        "disable_calendar_group",
        json_schema_extra={
            "const": "disable_calendar_group", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Disable/Enable Calendar Group",
        },
        title="Disable/Enable Calendar Group",
    )
    group_id: str = Field(..., title="Group ID", description="The group to update")
    is_active: str = Field(
        ..., title="Is Active", description="Set false to disable the group",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


# ---------------------------------------------------------------------------
# Appointments / Events
# ---------------------------------------------------------------------------

class GHLCreateAppointmentConfig(BaseModel):
    """Create an appointment on a calendar."""

    operation: Literal["create_appointment"] = Field(
        "create_appointment",
        json_schema_extra={
            "const": "create_appointment", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Create Appointment",
        },
        title="Create Appointment",
    )
    calendar_id: str = Field(..., title="Calendar ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    contact_id: str = Field(..., title="Contact ID")
    start_time: str = Field(..., title="Start Time", description="ISO 8601 start time")
    end_time: Optional[str] = Field(None, title="End Time", description="ISO 8601 end time")
    title: Optional[str] = Field(None, title="Title")
    meeting_location_type: Optional[str] = Field(
        None, title="Meeting Location Type",
        json_schema_extra={"enum": ["custom", "zoom", "gmeet", "phone", "address", "ms_teams", "google"], "x-enum-searchable": True},
    )
    meeting_location_id: Optional[str] = Field(None, title="Meeting Location ID")
    override_location_config: Optional[str] = Field(
        None, title="Override Location Config",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    appointment_status: Optional[str] = Field(
        None, title="Appointment Status",
        json_schema_extra={"enum": ["new", "confirmed", "cancelled", "showed", "noshow", "invalid"], "x-enum-searchable": True},
    )
    assigned_user_id: Optional[str] = Field(None, title="Assigned User ID")
    description: Optional[str] = Field(None, title="Description")
    address: Optional[str] = Field(None, title="Address")
    ignore_date_range: Optional[str] = Field(
        None, title="Ignore Date Range",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    to_notify: Optional[str] = Field(
        None, title="To Notify",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    ignore_free_slot_validation: Optional[str] = Field(
        None, title="Ignore Free Slot Validation",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    rrule: Optional[str] = Field(None, title="RRULE", description="Recurrence rule")


class GHLEditAppointmentConfig(BaseModel):
    """Update an existing appointment."""

    operation: Literal["edit_appointment"] = Field(
        "edit_appointment",
        json_schema_extra={
            "const": "edit_appointment", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Update Appointment",
        },
        title="Update Appointment",
    )
    event_id: str = Field(..., title="Event ID", description="The appointment/event to update")
    calendar_id: Optional[str] = Field(None, title="Calendar ID")
    start_time: Optional[str] = Field(None, title="Start Time", description="ISO 8601 start time")
    end_time: Optional[str] = Field(None, title="End Time", description="ISO 8601 end time")
    title: Optional[str] = Field(None, title="Title")
    meeting_location_type: Optional[str] = Field(
        None, title="Meeting Location Type",
        json_schema_extra={"enum": ["custom", "zoom", "gmeet", "phone", "address", "ms_teams", "google"], "x-enum-searchable": True},
    )
    meeting_location_id: Optional[str] = Field(None, title="Meeting Location ID")
    override_location_config: Optional[str] = Field(
        None, title="Override Location Config",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    appointment_status: Optional[str] = Field(
        None, title="Appointment Status",
        json_schema_extra={"enum": ["new", "confirmed", "cancelled", "showed", "noshow", "invalid"], "x-enum-searchable": True},
    )
    assigned_user_id: Optional[str] = Field(None, title="Assigned User ID")
    description: Optional[str] = Field(None, title="Description")
    address: Optional[str] = Field(None, title="Address")
    ignore_date_range: Optional[str] = Field(
        None, title="Ignore Date Range",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    to_notify: Optional[str] = Field(
        None, title="To Notify",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    ignore_free_slot_validation: Optional[str] = Field(
        None, title="Ignore Free Slot Validation",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    rrule: Optional[str] = Field(None, title="RRULE", description="Recurrence rule")


class GHLGetAppointmentConfig(BaseModel):
    """Get an appointment by event id."""

    operation: Literal["get_appointment"] = Field(
        "get_appointment",
        json_schema_extra={
            "const": "get_appointment", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Get Appointment",
        },
        title="Get Appointment",
    )
    event_id: str = Field(..., title="Event ID", description="The appointment/event to fetch")


class GHLGetCalendarEventsConfig(BaseModel):
    """Get calendar events in a time range."""

    operation: Literal["get_calendar_events"] = Field(
        "get_calendar_events",
        json_schema_extra={
            "const": "get_calendar_events", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Get Calendar Events",
        },
        title="Get Calendar Events",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    start_time: str = Field(..., title="Start Time", description="Range start (epoch ms or ISO)")
    end_time: str = Field(..., title="End Time", description="Range end (epoch ms or ISO)")
    user_id: Optional[str] = Field(None, title="User ID")
    calendar_id: Optional[str] = Field(None, title="Calendar ID")
    group_id: Optional[str] = Field(None, title="Group ID")


class GHLGetBlockedSlotsConfig(BaseModel):
    """Get blocked slots in a time range."""

    operation: Literal["get_blocked_slots"] = Field(
        "get_blocked_slots",
        json_schema_extra={
            "const": "get_blocked_slots", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Get Blocked Slots",
        },
        title="Get Blocked Slots",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    start_time: str = Field(..., title="Start Time", description="Range start (epoch ms or ISO)")
    end_time: str = Field(..., title="End Time", description="Range end (epoch ms or ISO)")
    user_id: Optional[str] = Field(None, title="User ID")
    calendar_id: Optional[str] = Field(None, title="Calendar ID")
    group_id: Optional[str] = Field(None, title="Group ID")


class GHLCreateBlockSlotConfig(BaseModel):
    """Create a block slot."""

    operation: Literal["create_block_slot"] = Field(
        "create_block_slot",
        json_schema_extra={
            "const": "create_block_slot", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Create Block Slot",
        },
        title="Create Block Slot",
    )
    calendar_id: str = Field(..., title="Calendar ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    title: Optional[str] = Field(None, title="Title")
    assigned_user_id: Optional[str] = Field(None, title="Assigned User ID")
    start_time: Optional[str] = Field(None, title="Start Time", description="ISO 8601 start time")
    end_time: Optional[str] = Field(None, title="End Time", description="ISO 8601 end time")


class GHLEditBlockSlotConfig(BaseModel):
    """Update a block slot."""

    operation: Literal["edit_block_slot"] = Field(
        "edit_block_slot",
        json_schema_extra={
            "const": "edit_block_slot", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Update Block Slot",
        },
        title="Update Block Slot",
    )
    event_id: str = Field(..., title="Event ID", description="The block slot event to update")
    calendar_id: str = Field(..., title="Calendar ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    title: Optional[str] = Field(None, title="Title")
    assigned_user_id: Optional[str] = Field(None, title="Assigned User ID")
    start_time: Optional[str] = Field(None, title="Start Time", description="ISO 8601 start time")
    end_time: Optional[str] = Field(None, title="End Time", description="ISO 8601 end time")


class GHLDeleteCalendarEventConfig(BaseModel):
    """Delete a calendar event (appointment or block slot)."""

    operation: Literal["delete_calendar_event"] = Field(
        "delete_calendar_event",
        json_schema_extra={
            "const": "delete_calendar_event", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Delete Calendar Event",
        },
        title="Delete Calendar Event",
    )
    event_id: str = Field(..., title="Event ID", description="The event to delete")


# ---------------------------------------------------------------------------
# Free slots
# ---------------------------------------------------------------------------

class GHLGetFreeSlotsConfig(BaseModel):
    """Get free/available slots for a calendar."""

    operation: Literal["get_free_slots"] = Field(
        "get_free_slots",
        json_schema_extra={
            "const": "get_free_slots", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Get Free Slots",
        },
        title="Get Free Slots",
    )
    calendar_id: str = Field(..., title="Calendar ID")
    start_date: str = Field(..., title="Start Date", description="Epoch ms range start")
    end_date: str = Field(..., title="End Date", description="Epoch ms range end")
    timezone: Optional[str] = Field(None, title="Timezone")
    user_id: Optional[str] = Field(None, title="User ID")
    user_ids: Optional[str] = Field(None, title="User IDs", description="Comma-separated user ids")


# ---------------------------------------------------------------------------
# Calendars (CRUD)
# ---------------------------------------------------------------------------

class GHLGetCalendarsConfig(BaseModel):
    """List calendars for a location."""

    operation: Literal["get_calendars"] = Field(
        "get_calendars",
        json_schema_extra={
            "const": "get_calendars", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "List Calendars",
        },
        title="List Calendars",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    group_id: Optional[str] = Field(None, title="Group ID")
    show_drafted: Optional[str] = Field(
        None, title="Show Drafted",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLGetCalendarConfig(BaseModel):
    """Get a calendar by id."""

    operation: Literal["get_calendar"] = Field(
        "get_calendar",
        json_schema_extra={
            "const": "get_calendar", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Get Calendar",
        },
        title="Get Calendar",
    )
    calendar_id: str = Field(..., title="Calendar ID", description="The calendar to fetch")


class GHLDeleteCalendarConfig(BaseModel):
    """Delete a calendar."""

    operation: Literal["delete_calendar"] = Field(
        "delete_calendar",
        json_schema_extra={
            "const": "delete_calendar", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Delete Calendar",
        },
        title="Delete Calendar",
    )
    calendar_id: str = Field(..., title="Calendar ID", description="The calendar to delete")


class GHLCreateCalendarConfig(BaseModel):
    """Create a calendar. Complex nested fields (notifications, teamMembers,
    openHours, availabilities, locationConfigurations, recurring) accept raw
    JSON strings."""

    operation: Literal["create_calendar"] = Field(
        "create_calendar",
        json_schema_extra={
            "const": "create_calendar", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Create Calendar",
        },
        title="Create Calendar",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name", description="Calendar name")
    calendar_type: Optional[str] = Field(
        None, title="Calendar Type",
        json_schema_extra={"enum": ["round_robin", "event", "class_booking", "collective", "service_booking", "personal"], "x-enum-searchable": True},
    )
    group_id: Optional[str] = Field(None, title="Group ID")
    description: Optional[str] = Field(None, title="Description")
    slug: Optional[str] = Field(None, title="Slug")
    widget_slug: Optional[str] = Field(None, title="Widget Slug")
    event_type: Optional[str] = Field(
        None, title="Event Type",
        json_schema_extra={"enum": ["RoundRobin_OptimizeForAvailability", "RoundRobin_OptimizeForEqualDistribution"], "x-enum-searchable": True},
    )
    widget_type: Optional[str] = Field(
        None, title="Widget Type",
        json_schema_extra={"enum": ["default", "classic"], "x-enum-searchable": True},
    )
    event_title: Optional[str] = Field(None, title="Event Title")
    event_color: Optional[str] = Field(None, title="Event Color")
    slot_duration: Optional[str] = Field(None, title="Slot Duration")
    slot_duration_unit: Optional[str] = Field(
        None, title="Slot Duration Unit",
        json_schema_extra={"enum": ["mins", "hours"], "x-enum-searchable": True},
    )
    slot_interval: Optional[str] = Field(None, title="Slot Interval")
    slot_interval_unit: Optional[str] = Field(
        None, title="Slot Interval Unit",
        json_schema_extra={"enum": ["mins", "hours"], "x-enum-searchable": True},
    )
    slot_buffer: Optional[str] = Field(None, title="Slot Buffer")
    slot_buffer_unit: Optional[str] = Field(
        None, title="Slot Buffer Unit",
        json_schema_extra={"enum": ["mins", "hours"], "x-enum-searchable": True},
    )
    pre_buffer: Optional[str] = Field(None, title="Pre Buffer")
    pre_buffer_unit: Optional[str] = Field(
        None, title="Pre Buffer Unit",
        json_schema_extra={"enum": ["mins", "hours"], "x-enum-searchable": True},
    )
    appoinment_per_slot: Optional[str] = Field(None, title="Appointments Per Slot")
    appoinment_per_day: Optional[str] = Field(None, title="Appointments Per Day")
    allow_booking_after: Optional[str] = Field(None, title="Allow Booking After")
    allow_booking_after_unit: Optional[str] = Field(
        None, title="Allow Booking After Unit",
        json_schema_extra={"enum": ["hours", "days", "weeks", "months"], "x-enum-searchable": True},
    )
    allow_booking_for: Optional[str] = Field(None, title="Allow Booking For")
    allow_booking_for_unit: Optional[str] = Field(
        None, title="Allow Booking For Unit",
        json_schema_extra={"enum": ["days", "weeks", "months"], "x-enum-searchable": True},
    )
    availability_type: Optional[str] = Field(
        None, title="Availability Type",
        json_schema_extra={"enum": ["0", "1"], "x-enum-searchable": True},
    )
    guest_type: Optional[str] = Field(
        None, title="Guest Type",
        json_schema_extra={"enum": ["count_only", "collect_detail"], "x-enum-searchable": True},
    )
    form_id: Optional[str] = Field(None, title="Form ID")
    form_submit_type: Optional[str] = Field(
        None, title="Form Submit Type",
        json_schema_extra={"enum": ["RedirectURL", "ThankYouMessage"], "x-enum-searchable": True},
    )
    form_submit_redirect_url: Optional[str] = Field(None, title="Form Submit Redirect URL")
    form_submit_thanks_message: Optional[str] = Field(None, title="Form Submit Thanks Message")
    consent_label: Optional[str] = Field(None, title="Consent Label")
    calendar_cover_image: Optional[str] = Field(None, title="Calendar Cover Image")
    notes: Optional[str] = Field(None, title="Notes")
    pixel_id: Optional[str] = Field(None, title="Pixel ID")
    alert_email: Optional[str] = Field(None, title="Alert Email")
    is_active: Optional[str] = Field(
        None, title="Is Active",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    enable_recurring: Optional[str] = Field(
        None, title="Enable Recurring",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    sticky_contact: Optional[str] = Field(
        None, title="Sticky Contact",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    is_live_payment_mode: Optional[str] = Field(
        None, title="Is Live Payment Mode",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    auto_confirm: Optional[str] = Field(
        None, title="Auto Confirm",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    should_send_alert_emails_to_assigned_member: Optional[str] = Field(
        None, title="Alert Emails To Assigned Member",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    google_invitation_emails: Optional[str] = Field(
        None, title="Google Invitation Emails",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    allow_reschedule: Optional[str] = Field(
        None, title="Allow Reschedule",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    allow_cancellation: Optional[str] = Field(
        None, title="Allow Cancellation",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    should_assign_contact_to_team_member: Optional[str] = Field(
        None, title="Assign Contact To Team Member",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    should_skip_assigning_contact_for_existing: Optional[str] = Field(
        None, title="Skip Assigning Contact For Existing",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    team_members: Optional[str] = Field(None, title="Team Members (JSON)", description="JSON array of team member objects")
    notifications: Optional[str] = Field(None, title="Notifications (JSON)", description="JSON array of notification objects")
    open_hours: Optional[str] = Field(None, title="Open Hours (JSON)", description="JSON array of open hour objects")
    availabilities: Optional[str] = Field(None, title="Availabilities (JSON)", description="JSON array of availability objects")
    location_configurations: Optional[str] = Field(None, title="Location Configurations (JSON)", description="JSON array")
    recurring: Optional[str] = Field(None, title="Recurring (JSON)", description="JSON recurring config object")
    look_busy_config: Optional[str] = Field(None, title="Look Busy Config (JSON)", description="JSON look busy configuration object")


class GHLUpdateCalendarConfig(BaseModel):
    """Update a calendar. Complex nested fields accept raw JSON strings."""

    operation: Literal["update_calendar"] = Field(
        "update_calendar",
        json_schema_extra={
            "const": "update_calendar", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Update Calendar",
        },
        title="Update Calendar",
    )
    calendar_id: str = Field(..., title="Calendar ID", description="The calendar to update")
    group_id: Optional[str] = Field(None, title="Group ID")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    slug: Optional[str] = Field(None, title="Slug")
    widget_slug: Optional[str] = Field(None, title="Widget Slug")
    event_type: Optional[str] = Field(
        None, title="Event Type",
        json_schema_extra={"enum": ["RoundRobin_OptimizeForAvailability", "RoundRobin_OptimizeForEqualDistribution"], "x-enum-searchable": True},
    )
    widget_type: Optional[str] = Field(
        None, title="Widget Type",
        json_schema_extra={"enum": ["default", "classic"], "x-enum-searchable": True},
    )
    event_title: Optional[str] = Field(None, title="Event Title")
    event_color: Optional[str] = Field(None, title="Event Color")
    slot_duration: Optional[str] = Field(None, title="Slot Duration")
    slot_duration_unit: Optional[str] = Field(
        None, title="Slot Duration Unit",
        json_schema_extra={"enum": ["mins", "hours"], "x-enum-searchable": True},
    )
    slot_interval: Optional[str] = Field(None, title="Slot Interval")
    slot_interval_unit: Optional[str] = Field(
        None, title="Slot Interval Unit",
        json_schema_extra={"enum": ["mins", "hours"], "x-enum-searchable": True},
    )
    slot_buffer: Optional[str] = Field(None, title="Slot Buffer")
    pre_buffer: Optional[str] = Field(None, title="Pre Buffer")
    pre_buffer_unit: Optional[str] = Field(
        None, title="Pre Buffer Unit",
        json_schema_extra={"enum": ["mins", "hours"], "x-enum-searchable": True},
    )
    appoinment_per_slot: Optional[str] = Field(None, title="Appointments Per Slot")
    appoinment_per_day: Optional[str] = Field(None, title="Appointments Per Day")
    allow_booking_after: Optional[str] = Field(None, title="Allow Booking After")
    allow_booking_after_unit: Optional[str] = Field(
        None, title="Allow Booking After Unit",
        json_schema_extra={"enum": ["hours", "days", "weeks", "months"], "x-enum-searchable": True},
    )
    allow_booking_for: Optional[str] = Field(None, title="Allow Booking For")
    allow_booking_for_unit: Optional[str] = Field(
        None, title="Allow Booking For Unit",
        json_schema_extra={"enum": ["days", "weeks", "months"], "x-enum-searchable": True},
    )
    availability_type: Optional[str] = Field(
        None, title="Availability Type",
        json_schema_extra={"enum": ["0", "1"], "x-enum-searchable": True},
    )
    guest_type: Optional[str] = Field(
        None, title="Guest Type",
        json_schema_extra={"enum": ["count_only", "collect_detail"], "x-enum-searchable": True},
    )
    form_id: Optional[str] = Field(None, title="Form ID")
    form_submit_type: Optional[str] = Field(
        None, title="Form Submit Type",
        json_schema_extra={"enum": ["RedirectURL", "ThankYouMessage"], "x-enum-searchable": True},
    )
    form_submit_redirect_url: Optional[str] = Field(None, title="Form Submit Redirect URL")
    form_submit_thanks_message: Optional[str] = Field(None, title="Form Submit Thanks Message")
    consent_label: Optional[str] = Field(None, title="Consent Label")
    calendar_cover_image: Optional[str] = Field(None, title="Calendar Cover Image")
    notes: Optional[str] = Field(None, title="Notes")
    pixel_id: Optional[str] = Field(None, title="Pixel ID")
    alert_email: Optional[str] = Field(None, title="Alert Email")
    is_active: Optional[str] = Field(
        None, title="Is Active",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    enable_recurring: Optional[str] = Field(
        None, title="Enable Recurring",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    sticky_contact: Optional[str] = Field(
        None, title="Sticky Contact",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    is_live_payment_mode: Optional[str] = Field(
        None, title="Is Live Payment Mode",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    auto_confirm: Optional[str] = Field(
        None, title="Auto Confirm",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    should_send_alert_emails_to_assigned_member: Optional[str] = Field(
        None, title="Alert Emails To Assigned Member",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    google_invitation_emails: Optional[str] = Field(
        None, title="Google Invitation Emails",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    allow_reschedule: Optional[str] = Field(
        None, title="Allow Reschedule",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    allow_cancellation: Optional[str] = Field(
        None, title="Allow Cancellation",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    should_assign_contact_to_team_member: Optional[str] = Field(
        None, title="Assign Contact To Team Member",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    should_skip_assigning_contact_for_existing: Optional[str] = Field(
        None, title="Skip Assigning Contact For Existing",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    team_members: Optional[str] = Field(None, title="Team Members (JSON)", description="JSON array of team member objects")
    notifications: Optional[str] = Field(None, title="Notifications (JSON)", description="JSON array of notification objects")
    open_hours: Optional[str] = Field(None, title="Open Hours (JSON)", description="JSON array of open hour objects")
    availabilities: Optional[str] = Field(None, title="Availabilities (JSON)", description="JSON array of availability objects")
    location_configurations: Optional[str] = Field(None, title="Location Configurations (JSON)", description="JSON array")
    recurring: Optional[str] = Field(None, title="Recurring (JSON)", description="JSON recurring config object")
    look_busy_config: Optional[str] = Field(None, title="Look Busy Config (JSON)", description="JSON look busy configuration object")


# ---------------------------------------------------------------------------
# Appointment notes
# ---------------------------------------------------------------------------

class GHLGetAppointmentNotesConfig(BaseModel):
    """List notes on an appointment."""

    operation: Literal["get_appointment_notes"] = Field(
        "get_appointment_notes",
        json_schema_extra={
            "const": "get_appointment_notes", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "List Appointment Notes",
        },
        title="List Appointment Notes",
    )
    appointment_id: str = Field(..., title="Appointment ID")
    limit: str = Field(..., title="Limit", description="Max notes to return")
    offset: str = Field(..., title="Offset", description="Pagination offset")


class GHLCreateAppointmentNoteConfig(BaseModel):
    """Create a note on an appointment."""

    operation: Literal["create_appointment_note"] = Field(
        "create_appointment_note",
        json_schema_extra={
            "const": "create_appointment_note", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Create Appointment Note",
        },
        title="Create Appointment Note",
    )
    appointment_id: str = Field(..., title="Appointment ID")
    body: str = Field(..., title="Body", description="Note body text")
    user_id: Optional[str] = Field(None, title="User ID")


class GHLUpdateAppointmentNoteConfig(BaseModel):
    """Update a note on an appointment."""

    operation: Literal["update_appointment_note"] = Field(
        "update_appointment_note",
        json_schema_extra={
            "const": "update_appointment_note", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Update Appointment Note",
        },
        title="Update Appointment Note",
    )
    appointment_id: str = Field(..., title="Appointment ID")
    note_id: str = Field(..., title="Note ID", description="The note to update")
    body: str = Field(..., title="Body", description="Note body text")
    user_id: Optional[str] = Field(None, title="User ID")


class GHLDeleteAppointmentNoteConfig(BaseModel):
    """Delete a note on an appointment."""

    operation: Literal["delete_appointment_note"] = Field(
        "delete_appointment_note",
        json_schema_extra={
            "const": "delete_appointment_note", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Delete Appointment Note",
        },
        title="Delete Appointment Note",
    )
    appointment_id: str = Field(..., title="Appointment ID")
    note_id: str = Field(..., title="Note ID", description="The note to delete")


# ---------------------------------------------------------------------------
# Calendar resources (rooms / equipment)
# ---------------------------------------------------------------------------

class GHLGetCalendarResourceConfig(BaseModel):
    """Get a calendar resource by type and id."""

    operation: Literal["get_calendar_resource"] = Field(
        "get_calendar_resource",
        json_schema_extra={
            "const": "get_calendar_resource", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Get Calendar Resource",
        },
        title="Get Calendar Resource",
    )
    resource_type: str = Field(..., title="Resource Type", description="e.g. rooms or equipments")
    id: str = Field(..., title="Resource ID")


class GHLUpdateCalendarResourceConfig(BaseModel):
    """Update a calendar resource."""

    operation: Literal["update_calendar_resource"] = Field(
        "update_calendar_resource",
        json_schema_extra={
            "const": "update_calendar_resource", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Update Calendar Resource",
        },
        title="Update Calendar Resource",
    )
    resource_type: str = Field(..., title="Resource Type", description="e.g. rooms or equipments")
    id: str = Field(..., title="Resource ID")
    location_id: Optional[str] = Field(None, title="Location ID")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    quantity: Optional[str] = Field(None, title="Quantity")
    out_of_service: Optional[str] = Field(None, title="Out Of Service")
    capacity: Optional[str] = Field(None, title="Capacity")
    calendar_ids: Optional[str] = Field(None, title="Calendar IDs", description="Comma-separated calendar ids")
    is_active: Optional[str] = Field(
        None, title="Is Active",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLDeleteCalendarResourceConfig(BaseModel):
    """Delete a calendar resource."""

    operation: Literal["delete_calendar_resource"] = Field(
        "delete_calendar_resource",
        json_schema_extra={
            "const": "delete_calendar_resource", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Delete Calendar Resource",
        },
        title="Delete Calendar Resource",
    )
    resource_type: str = Field(..., title="Resource Type", description="e.g. rooms or equipments")
    id: str = Field(..., title="Resource ID")


class GHLListCalendarResourcesConfig(BaseModel):
    """List calendar resources of a type."""

    operation: Literal["list_calendar_resources"] = Field(
        "list_calendar_resources",
        json_schema_extra={
            "const": "list_calendar_resources", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "List Calendar Resources",
        },
        title="List Calendar Resources",
    )
    resource_type: str = Field(..., title="Resource Type", description="e.g. rooms or equipments")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: str = Field(..., title="Limit", description="Max results to return")
    skip: str = Field(..., title="Skip", description="Number of results to skip")


class GHLCreateCalendarResourceConfig(BaseModel):
    """Create a calendar resource."""

    operation: Literal["create_calendar_resource"] = Field(
        "create_calendar_resource",
        json_schema_extra={
            "const": "create_calendar_resource", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Create Calendar Resource",
        },
        title="Create Calendar Resource",
    )
    resource_type: str = Field(..., title="Resource Type", description="e.g. rooms or equipments")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    quantity: str = Field(..., title="Quantity")
    out_of_service: str = Field(..., title="Out Of Service")
    capacity: str = Field(..., title="Capacity")
    calendar_ids: str = Field(..., title="Calendar IDs", description="Comma-separated calendar ids")


# ---------------------------------------------------------------------------
# Calendar notifications
# ---------------------------------------------------------------------------

class GHLGetCalendarNotificationsConfig(BaseModel):
    """List notifications configured on a calendar."""

    operation: Literal["get_calendar_notifications"] = Field(
        "get_calendar_notifications",
        json_schema_extra={
            "const": "get_calendar_notifications", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "List Calendar Notifications",
        },
        title="List Calendar Notifications",
    )
    calendar_id: str = Field(..., title="Calendar ID")
    is_active: Optional[str] = Field(
        None, title="Is Active",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    deleted: Optional[str] = Field(
        None, title="Deleted",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    limit: Optional[str] = Field(None, title="Limit")
    skip: Optional[str] = Field(None, title="Skip")


class GHLCreateCalendarNotificationConfig(BaseModel):
    """Create calendar notifications. The API accepts a JSON array of
    notification objects."""

    operation: Literal["create_calendar_notification"] = Field(
        "create_calendar_notification",
        json_schema_extra={
            "const": "create_calendar_notification", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Create Calendar Notification",
        },
        title="Create Calendar Notification",
    )
    calendar_id: str = Field(..., title="Calendar ID")
    notifications: str = Field(
        ..., title="Notifications (JSON)",
        description="JSON array of notification objects (receiverType, channel, notificationType, etc.)",
    )


class GHLFindCalendarNotificationConfig(BaseModel):
    """Get a single calendar notification."""

    operation: Literal["find_calendar_notification"] = Field(
        "find_calendar_notification",
        json_schema_extra={
            "const": "find_calendar_notification", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Get Calendar Notification",
        },
        title="Get Calendar Notification",
    )
    calendar_id: str = Field(..., title="Calendar ID")
    notification_id: str = Field(..., title="Notification ID")


class GHLUpdateCalendarNotificationConfig(BaseModel):
    """Update a calendar notification."""

    operation: Literal["update_calendar_notification"] = Field(
        "update_calendar_notification",
        json_schema_extra={
            "const": "update_calendar_notification", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Update Calendar Notification",
        },
        title="Update Calendar Notification",
    )
    calendar_id: str = Field(..., title="Calendar ID")
    notification_id: str = Field(..., title="Notification ID")
    receiver_type: Optional[str] = Field(
        None, title="Receiver Type",
        json_schema_extra={"enum": ["contact", "guest", "assignedUser", "emails", "phoneNumbers", "business"], "x-enum-searchable": True},
    )
    channel: Optional[str] = Field(
        None, title="Channel",
        json_schema_extra={"enum": ["email", "inApp", "sms", "whatsapp"], "x-enum-searchable": True},
    )
    notification_type: Optional[str] = Field(
        None, title="Notification Type",
        json_schema_extra={"enum": ["booked", "confirmation", "cancellation", "reminder", "followup", "reschedule"], "x-enum-searchable": True},
    )
    is_active: Optional[str] = Field(
        None, title="Is Active",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    deleted: Optional[str] = Field(
        None, title="Deleted",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    template_id: Optional[str] = Field(None, title="Template ID")
    body: Optional[str] = Field(None, title="Body")
    subject: Optional[str] = Field(None, title="Subject")
    from_address: Optional[str] = Field(None, title="From Address")
    from_number: Optional[str] = Field(None, title="From Number")
    from_name: Optional[str] = Field(None, title="From Name")
    additional_email_ids: Optional[str] = Field(None, title="Additional Email IDs", description="Comma-separated emails")
    additional_phone_numbers: Optional[str] = Field(None, title="Additional Phone Numbers", description="Comma-separated numbers")
    selected_users: Optional[str] = Field(None, title="Selected Users", description="Comma-separated user ids")
    after_time: Optional[str] = Field(None, title="After Time (JSON)", description="JSON array of schedule objects")
    before_time: Optional[str] = Field(None, title="Before Time (JSON)", description="JSON array of schedule objects")


class GHLDeleteCalendarNotificationConfig(BaseModel):
    """Delete a calendar notification."""

    operation: Literal["delete_calendar_notification"] = Field(
        "delete_calendar_notification",
        json_schema_extra={
            "const": "delete_calendar_notification", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Delete Calendar Notification",
        },
        title="Delete Calendar Notification",
    )
    calendar_id: str = Field(..., title="Calendar ID")
    notification_id: str = Field(..., title="Notification ID")


# ---------------------------------------------------------------------------
# Availability schedules
# ---------------------------------------------------------------------------

class GHLGetAvailabilitySchedulesConfig(BaseModel):
    """List user availability schedules."""

    operation: Literal["get_availability_schedules"] = Field(
        "get_availability_schedules",
        json_schema_extra={
            "const": "get_availability_schedules", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "List Availability Schedules",
        },
        title="List Availability Schedules",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    user_id: str = Field(..., title="User ID")
    calendar_id: Optional[str] = Field(None, title="Calendar ID")
    skip: Optional[str] = Field(None, title="Skip")
    limit: Optional[str] = Field(None, title="Limit")


class GHLGetAvailabilityScheduleConfig(BaseModel):
    """Get a user availability schedule by id."""

    operation: Literal["get_availability_schedule"] = Field(
        "get_availability_schedule",
        json_schema_extra={
            "const": "get_availability_schedule", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Get Availability Schedule",
        },
        title="Get Availability Schedule",
    )
    id: str = Field(..., title="Schedule ID")


class GHLUpdateAvailabilityScheduleConfig(BaseModel):
    """Update a user availability schedule."""

    operation: Literal["update_availability_schedule"] = Field(
        "update_availability_schedule",
        json_schema_extra={
            "const": "update_availability_schedule", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Update Availability Schedule",
        },
        title="Update Availability Schedule",
    )
    id: str = Field(..., title="Schedule ID")
    name: Optional[str] = Field(None, title="Name")
    timezone: Optional[str] = Field(None, title="Timezone")
    rules: Optional[str] = Field(None, title="Rules (JSON)", description="JSON array of schedule rule objects")


class GHLDeleteAvailabilityScheduleConfig(BaseModel):
    """Delete a user availability schedule."""

    operation: Literal["delete_availability_schedule"] = Field(
        "delete_availability_schedule",
        json_schema_extra={
            "const": "delete_availability_schedule", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Delete Availability Schedule",
        },
        title="Delete Availability Schedule",
    )
    id: str = Field(..., title="Schedule ID")


class GHLCreateAvailabilityScheduleConfig(BaseModel):
    """Create a user availability schedule."""

    operation: Literal["create_availability_schedule"] = Field(
        "create_availability_schedule",
        json_schema_extra={
            "const": "create_availability_schedule", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Create Availability Schedule",
        },
        title="Create Availability Schedule",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name")
    timezone: str = Field(..., title="Timezone")
    user_id: str = Field(..., title="User ID")
    calendar_ids: Optional[str] = Field(None, title="Calendar IDs", description="Comma-separated calendar ids")
    rules: Optional[str] = Field(None, title="Rules (JSON)", description="JSON array of schedule rule objects")


class GHLAddCalendarToScheduleConfig(BaseModel):
    """Apply a user availability schedule to a calendar."""

    operation: Literal["add_calendar_to_schedule"] = Field(
        "add_calendar_to_schedule",
        json_schema_extra={
            "const": "add_calendar_to_schedule", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Add Calendar To Schedule",
        },
        title="Add Calendar To Schedule",
    )
    id: str = Field(..., title="Schedule ID")
    calendar_id: str = Field(..., title="Calendar ID")


class GHLRemoveCalendarFromScheduleConfig(BaseModel):
    """Remove a user availability schedule from a calendar."""

    operation: Literal["remove_calendar_from_schedule"] = Field(
        "remove_calendar_from_schedule",
        json_schema_extra={
            "const": "remove_calendar_from_schedule", "ui:hidden": True,
            "x-category": "Calendars", "x-is-trigger": False,
            "x-display-name": "Remove Calendar From Schedule",
        },
        title="Remove Calendar From Schedule",
    )
    id: str = Field(..., title="Schedule ID")
    calendar_id: str = Field(..., title="Calendar ID")


# ===========================================================================
# Handlers
# ===========================================================================

async def _get_calendar_groups(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", "/calendars/groups", params=params, version=_CAL_VERSION, action_name="get_calendar_groups")


async def _create_calendar_group(node, c, token):
    body = {
        "locationId": c.location_id, "name": c.name, "description": c.description,
        "slug": c.slug, "isActive": _ghl_bool(c.is_active),
    }
    return await node._request(token, "POST", "/calendars/groups", json_body=body, version=_CAL_VERSION, action_name="create_calendar_group")


async def _validate_calendar_group_slug(node, c, token):
    body = {"locationId": c.location_id, "slug": c.slug}
    return await node._request(token, "POST", "/calendars/groups/validate-slug", json_body=body, version=_CAL_VERSION, action_name="validate_calendar_group_slug")


async def _delete_calendar_group(node, c, token):
    return await node._request(token, "DELETE", f"/calendars/groups/{c.group_id}", version=_CAL_VERSION, action_name="delete_calendar_group")


async def _update_calendar_group(node, c, token):
    body = {"name": c.name, "description": c.description, "slug": c.slug}
    return await node._request(token, "PUT", f"/calendars/groups/{c.group_id}", json_body=body, version=_CAL_VERSION, action_name="update_calendar_group")


async def _disable_calendar_group(node, c, token):
    body = {"isActive": _ghl_bool(c.is_active)}
    return await node._request(token, "PUT", f"/calendars/groups/{c.group_id}/status", json_body=body, version=_CAL_VERSION, action_name="disable_calendar_group")


async def _create_appointment(node, c, token):
    body = {
        "calendarId": c.calendar_id, "locationId": c.location_id, "contactId": c.contact_id,
        "startTime": c.start_time, "endTime": c.end_time, "title": c.title,
        "meetingLocationType": c.meeting_location_type, "meetingLocationId": c.meeting_location_id,
        "overrideLocationConfig": _ghl_bool(c.override_location_config),
        "appointmentStatus": c.appointment_status, "assignedUserId": c.assigned_user_id,
        "description": c.description, "address": c.address,
        "ignoreDateRange": _ghl_bool(c.ignore_date_range), "toNotify": _ghl_bool(c.to_notify),
        "ignoreFreeSlotValidation": _ghl_bool(c.ignore_free_slot_validation), "rrule": c.rrule,
    }
    return await node._request(token, "POST", "/calendars/events/appointments", json_body=body, version=_CAL_VERSION, action_name="create_appointment")


async def _edit_appointment(node, c, token):
    body = {
        "calendarId": c.calendar_id, "startTime": c.start_time, "endTime": c.end_time,
        "title": c.title, "meetingLocationType": c.meeting_location_type,
        "meetingLocationId": c.meeting_location_id,
        "overrideLocationConfig": _ghl_bool(c.override_location_config),
        "appointmentStatus": c.appointment_status, "assignedUserId": c.assigned_user_id,
        "description": c.description, "address": c.address,
        "ignoreDateRange": _ghl_bool(c.ignore_date_range), "toNotify": _ghl_bool(c.to_notify),
        "ignoreFreeSlotValidation": _ghl_bool(c.ignore_free_slot_validation), "rrule": c.rrule,
    }
    return await node._request(token, "PUT", f"/calendars/events/appointments/{c.event_id}", json_body=body, version=_CAL_VERSION, action_name="edit_appointment")


async def _get_appointment(node, c, token):
    return await node._request(token, "GET", f"/calendars/events/appointments/{c.event_id}", version=_CAL_VERSION, action_name="get_appointment")


async def _get_calendar_events(node, c, token):
    params = {
        "locationId": c.location_id, "startTime": c.start_time, "endTime": c.end_time,
        "userId": c.user_id, "calendarId": c.calendar_id, "groupId": c.group_id,
    }
    return await node._request(token, "GET", "/calendars/events", params=params, version=_CAL_VERSION, action_name="get_calendar_events")


async def _get_blocked_slots(node, c, token):
    params = {
        "locationId": c.location_id, "startTime": c.start_time, "endTime": c.end_time,
        "userId": c.user_id, "calendarId": c.calendar_id, "groupId": c.group_id,
    }
    return await node._request(token, "GET", "/calendars/blocked-slots", params=params, version=_CAL_VERSION, action_name="get_blocked_slots")


async def _create_block_slot(node, c, token):
    body = {
        "calendarId": c.calendar_id, "locationId": c.location_id, "title": c.title,
        "assignedUserId": c.assigned_user_id, "startTime": c.start_time, "endTime": c.end_time,
    }
    return await node._request(token, "POST", "/calendars/events/block-slots", json_body=body, version=_CAL_VERSION, action_name="create_block_slot")


async def _edit_block_slot(node, c, token):
    body = {
        "calendarId": c.calendar_id, "locationId": c.location_id, "title": c.title,
        "assignedUserId": c.assigned_user_id, "startTime": c.start_time, "endTime": c.end_time,
    }
    return await node._request(token, "PUT", f"/calendars/events/block-slots/{c.event_id}", json_body=body, version=_CAL_VERSION, action_name="edit_block_slot")


async def _delete_calendar_event(node, c, token):
    return await node._request(token, "DELETE", f"/calendars/events/{c.event_id}", version=_CAL_VERSION, action_name="delete_calendar_event")


async def _get_free_slots(node, c, token):
    params = {
        "startDate": _ghl_int(c.start_date), "endDate": _ghl_int(c.end_date),
        "timezone": c.timezone, "userId": c.user_id, "userIds": _ghl_csv(c.user_ids),
    }
    return await node._request(token, "GET", f"/calendars/{c.calendar_id}/free-slots", params=params, version=_CAL_VERSION, action_name="get_free_slots")


async def _get_calendars(node, c, token):
    params = {"locationId": c.location_id, "groupId": c.group_id, "showDrafted": _ghl_bool(c.show_drafted)}
    return await node._request(token, "GET", "/calendars/", params=params, version=_CAL_VERSION, action_name="get_calendars")


async def _get_calendar(node, c, token):
    return await node._request(token, "GET", f"/calendars/{c.calendar_id}", version=_CAL_VERSION, action_name="get_calendar")


async def _delete_calendar(node, c, token):
    return await node._request(token, "DELETE", f"/calendars/{c.calendar_id}", version=_CAL_VERSION, action_name="delete_calendar")


async def _create_calendar(node, c, token):
    body = {
        "locationId": c.location_id, "name": c.name, "calendarType": c.calendar_type,
        "groupId": c.group_id, "description": c.description, "slug": c.slug,
        "widgetSlug": c.widget_slug, "eventType": c.event_type, "widgetType": c.widget_type,
        "eventTitle": c.event_title, "eventColor": c.event_color,
        "slotDuration": _ghl_num(c.slot_duration), "slotDurationUnit": c.slot_duration_unit,
        "slotInterval": _ghl_num(c.slot_interval), "slotIntervalUnit": c.slot_interval_unit,
        "slotBuffer": _ghl_num(c.slot_buffer), "slotBufferUnit": c.slot_buffer_unit,
        "preBuffer": _ghl_num(c.pre_buffer), "preBufferUnit": c.pre_buffer_unit,
        "appoinmentPerSlot": _ghl_num(c.appoinment_per_slot), "appoinmentPerDay": _ghl_num(c.appoinment_per_day),
        "allowBookingAfter": _ghl_num(c.allow_booking_after), "allowBookingAfterUnit": c.allow_booking_after_unit,
        "allowBookingFor": _ghl_num(c.allow_booking_for), "allowBookingForUnit": c.allow_booking_for_unit,
        "availabilityType": _ghl_int(c.availability_type), "guestType": c.guest_type,
        "formId": c.form_id, "formSubmitType": c.form_submit_type,
        "formSubmitRedirectURL": c.form_submit_redirect_url, "formSubmitThanksMessage": c.form_submit_thanks_message,
        "consentLabel": c.consent_label, "calendarCoverImage": c.calendar_cover_image,
        "notes": c.notes, "pixelId": c.pixel_id, "alertEmail": c.alert_email,
        "isActive": _ghl_bool(c.is_active), "enableRecurring": _ghl_bool(c.enable_recurring),
        "stickyContact": _ghl_bool(c.sticky_contact), "isLivePaymentMode": _ghl_bool(c.is_live_payment_mode),
        "autoConfirm": _ghl_bool(c.auto_confirm),
        "shouldSendAlertEmailsToAssignedMember": _ghl_bool(c.should_send_alert_emails_to_assigned_member),
        "googleInvitationEmails": _ghl_bool(c.google_invitation_emails),
        "allowReschedule": _ghl_bool(c.allow_reschedule), "allowCancellation": _ghl_bool(c.allow_cancellation),
        "shouldAssignContactToTeamMember": _ghl_bool(c.should_assign_contact_to_team_member),
        "shouldSkipAssigningContactForExisting": _ghl_bool(c.should_skip_assigning_contact_for_existing),
        "teamMembers": _ghl_json(c.team_members), "notifications": _ghl_json(c.notifications),
        "openHours": _ghl_json(c.open_hours), "availabilities": _ghl_json(c.availabilities),
        "locationConfigurations": _ghl_json(c.location_configurations), "recurring": _ghl_json(c.recurring),
        "lookBusyConfig": _ghl_json(c.look_busy_config),
    }
    return await node._request(token, "POST", "/calendars/", json_body=body, version=_CAL_VERSION, action_name="create_calendar")


async def _update_calendar(node, c, token):
    body = {
        "groupId": c.group_id, "name": c.name, "description": c.description, "slug": c.slug,
        "widgetSlug": c.widget_slug, "eventType": c.event_type, "widgetType": c.widget_type,
        "eventTitle": c.event_title, "eventColor": c.event_color,
        "slotDuration": _ghl_num(c.slot_duration), "slotDurationUnit": c.slot_duration_unit,
        "slotInterval": _ghl_num(c.slot_interval), "slotIntervalUnit": c.slot_interval_unit,
        "slotBuffer": _ghl_num(c.slot_buffer), "preBuffer": _ghl_num(c.pre_buffer),
        "preBufferUnit": c.pre_buffer_unit,
        "appoinmentPerSlot": _ghl_num(c.appoinment_per_slot), "appoinmentPerDay": _ghl_num(c.appoinment_per_day),
        "allowBookingAfter": _ghl_num(c.allow_booking_after), "allowBookingAfterUnit": c.allow_booking_after_unit,
        "allowBookingFor": _ghl_num(c.allow_booking_for), "allowBookingForUnit": c.allow_booking_for_unit,
        "availabilityType": _ghl_int(c.availability_type), "guestType": c.guest_type,
        "formId": c.form_id, "formSubmitType": c.form_submit_type,
        "formSubmitRedirectURL": c.form_submit_redirect_url, "formSubmitThanksMessage": c.form_submit_thanks_message,
        "consentLabel": c.consent_label, "calendarCoverImage": c.calendar_cover_image,
        "notes": c.notes, "pixelId": c.pixel_id, "alertEmail": c.alert_email,
        "isActive": _ghl_bool(c.is_active), "enableRecurring": _ghl_bool(c.enable_recurring),
        "stickyContact": _ghl_bool(c.sticky_contact), "isLivePaymentMode": _ghl_bool(c.is_live_payment_mode),
        "autoConfirm": _ghl_bool(c.auto_confirm),
        "shouldSendAlertEmailsToAssignedMember": _ghl_bool(c.should_send_alert_emails_to_assigned_member),
        "googleInvitationEmails": _ghl_bool(c.google_invitation_emails),
        "allowReschedule": _ghl_bool(c.allow_reschedule), "allowCancellation": _ghl_bool(c.allow_cancellation),
        "shouldAssignContactToTeamMember": _ghl_bool(c.should_assign_contact_to_team_member),
        "shouldSkipAssigningContactForExisting": _ghl_bool(c.should_skip_assigning_contact_for_existing),
        "teamMembers": _ghl_json(c.team_members), "notifications": _ghl_json(c.notifications),
        "openHours": _ghl_json(c.open_hours), "availabilities": _ghl_json(c.availabilities),
        "locationConfigurations": _ghl_json(c.location_configurations), "recurring": _ghl_json(c.recurring),
        "lookBusyConfig": _ghl_json(c.look_busy_config),
    }
    return await node._request(token, "PUT", f"/calendars/{c.calendar_id}", json_body=body, version=_CAL_VERSION, action_name="update_calendar")


async def _get_appointment_notes(node, c, token):
    params = {"limit": _ghl_num(c.limit), "offset": _ghl_num(c.offset)}
    return await node._request(token, "GET", f"/calendars/appointments/{c.appointment_id}/notes", params=params, version=_CAL_VERSION, action_name="get_appointment_notes")


async def _create_appointment_note(node, c, token):
    body = {"userId": c.user_id, "body": c.body}
    return await node._request(token, "POST", f"/calendars/appointments/{c.appointment_id}/notes", json_body=body, version=_CAL_VERSION, action_name="create_appointment_note")


async def _update_appointment_note(node, c, token):
    body = {"userId": c.user_id, "body": c.body}
    return await node._request(token, "PUT", f"/calendars/appointments/{c.appointment_id}/notes/{c.note_id}", json_body=body, version=_CAL_VERSION, action_name="update_appointment_note")


async def _delete_appointment_note(node, c, token):
    return await node._request(token, "DELETE", f"/calendars/appointments/{c.appointment_id}/notes/{c.note_id}", version=_CAL_VERSION, action_name="delete_appointment_note")


async def _get_calendar_resource(node, c, token):
    return await node._request(token, "GET", f"/calendars/resources/{c.resource_type}/{c.id}", version=_CAL_VERSION, action_name="get_calendar_resource")


async def _update_calendar_resource(node, c, token):
    body = {
        "locationId": c.location_id, "name": c.name, "description": c.description,
        "quantity": _ghl_num(c.quantity), "outOfService": _ghl_num(c.out_of_service),
        "capacity": _ghl_num(c.capacity), "calendarIds": _ghl_csv(c.calendar_ids),
        "isActive": _ghl_bool(c.is_active),
    }
    return await node._request(token, "PUT", f"/calendars/resources/{c.resource_type}/{c.id}", json_body=body, version=_CAL_VERSION, action_name="update_calendar_resource")


async def _delete_calendar_resource(node, c, token):
    return await node._request(token, "DELETE", f"/calendars/resources/{c.resource_type}/{c.id}", version=_CAL_VERSION, action_name="delete_calendar_resource")


async def _list_calendar_resources(node, c, token):
    params = {"locationId": c.location_id, "limit": _ghl_num(c.limit), "skip": _ghl_num(c.skip)}
    return await node._request(token, "GET", f"/calendars/resources/{c.resource_type}", params=params, version=_CAL_VERSION, action_name="list_calendar_resources")


async def _create_calendar_resource(node, c, token):
    body = {
        "locationId": c.location_id, "name": c.name, "description": c.description,
        "quantity": _ghl_num(c.quantity), "outOfService": _ghl_num(c.out_of_service),
        "capacity": _ghl_num(c.capacity), "calendarIds": _ghl_csv(c.calendar_ids),
    }
    return await node._request(token, "POST", f"/calendars/resources/{c.resource_type}", json_body=body, version=_CAL_VERSION, action_name="create_calendar_resource")


async def _get_calendar_notifications(node, c, token):
    params = {
        "isActive": _ghl_bool(c.is_active), "deleted": _ghl_bool(c.deleted),
        "limit": _ghl_num(c.limit), "skip": _ghl_num(c.skip),
    }
    return await node._request(token, "GET", f"/calendars/{c.calendar_id}/notifications", params=params, version=_CAL_VERSION, action_name="get_calendar_notifications")


async def _create_calendar_notification(node, c, token):
    body = _ghl_json(c.notifications)
    return await node._request(token, "POST", f"/calendars/{c.calendar_id}/notifications", json_body=body, version=_CAL_VERSION, action_name="create_calendar_notification")


async def _find_calendar_notification(node, c, token):
    return await node._request(token, "GET", f"/calendars/{c.calendar_id}/notifications/{c.notification_id}", version=_CAL_VERSION, action_name="find_calendar_notification")


async def _update_calendar_notification(node, c, token):
    body = {
        "receiverType": c.receiver_type, "channel": c.channel, "notificationType": c.notification_type,
        "isActive": _ghl_bool(c.is_active), "deleted": _ghl_bool(c.deleted),
        "templateId": c.template_id, "body": c.body, "subject": c.subject,
        "fromAddress": c.from_address, "fromNumber": c.from_number, "fromName": c.from_name,
        "additionalEmailIds": _ghl_csv(c.additional_email_ids),
        "additionalPhoneNumbers": _ghl_csv(c.additional_phone_numbers),
        "selectedUsers": _ghl_csv(c.selected_users),
        "afterTime": _ghl_json(c.after_time), "beforeTime": _ghl_json(c.before_time),
    }
    return await node._request(token, "PUT", f"/calendars/{c.calendar_id}/notifications/{c.notification_id}", json_body=body, version=_CAL_VERSION, action_name="update_calendar_notification")


async def _delete_calendar_notification(node, c, token):
    return await node._request(token, "DELETE", f"/calendars/{c.calendar_id}/notifications/{c.notification_id}", version=_CAL_VERSION, action_name="delete_calendar_notification")


async def _get_availability_schedules(node, c, token):
    params = {
        "locationId": c.location_id, "userId": c.user_id, "calendarId": c.calendar_id,
        "skip": _ghl_num(c.skip), "limit": _ghl_num(c.limit),
    }
    return await node._request(token, "GET", "/calendars/schedules/search", params=params, version=_CAL_VERSION, action_name="get_availability_schedules")


async def _get_availability_schedule(node, c, token):
    return await node._request(token, "GET", f"/calendars/schedules/{c.id}", version=_CAL_VERSION, action_name="get_availability_schedule")


async def _update_availability_schedule(node, c, token):
    body = {"name": c.name, "timezone": c.timezone, "rules": _ghl_json(c.rules)}
    return await node._request(token, "PUT", f"/calendars/schedules/{c.id}", json_body=body, version=_CAL_VERSION, action_name="update_availability_schedule")


async def _delete_availability_schedule(node, c, token):
    return await node._request(token, "DELETE", f"/calendars/schedules/{c.id}", version=_CAL_VERSION, action_name="delete_availability_schedule")


async def _create_availability_schedule(node, c, token):
    body = {
        "locationId": c.location_id, "name": c.name, "timezone": c.timezone, "userId": c.user_id,
        "calendarIds": _ghl_csv(c.calendar_ids), "rules": _ghl_json(c.rules),
    }
    return await node._request(token, "POST", "/calendars/schedules", json_body=body, version=_CAL_VERSION, action_name="create_availability_schedule")


async def _add_calendar_to_schedule(node, c, token):
    return await node._request(token, "PUT", f"/calendars/schedules/{c.id}/associations/{c.calendar_id}", version=_CAL_VERSION, action_name="add_calendar_to_schedule")


async def _remove_calendar_from_schedule(node, c, token):
    return await node._request(token, "DELETE", f"/calendars/schedules/{c.id}/associations/{c.calendar_id}", version=_CAL_VERSION, action_name="remove_calendar_from_schedule")


GHL_OPERATION_CONFIGS += [
    GHLGetCalendarGroupsConfig,
    GHLCreateCalendarGroupConfig,
    GHLValidateCalendarGroupSlugConfig,
    GHLDeleteCalendarGroupConfig,
    GHLUpdateCalendarGroupConfig,
    GHLDisableCalendarGroupConfig,
    GHLCreateAppointmentConfig,
    GHLEditAppointmentConfig,
    GHLGetAppointmentConfig,
    GHLGetCalendarEventsConfig,
    GHLGetBlockedSlotsConfig,
    GHLCreateBlockSlotConfig,
    GHLEditBlockSlotConfig,
    GHLDeleteCalendarEventConfig,
    GHLGetFreeSlotsConfig,
    GHLGetCalendarsConfig,
    GHLGetCalendarConfig,
    GHLDeleteCalendarConfig,
    GHLCreateCalendarConfig,
    GHLUpdateCalendarConfig,
    GHLGetAppointmentNotesConfig,
    GHLCreateAppointmentNoteConfig,
    GHLUpdateAppointmentNoteConfig,
    GHLDeleteAppointmentNoteConfig,
    GHLGetCalendarResourceConfig,
    GHLUpdateCalendarResourceConfig,
    GHLDeleteCalendarResourceConfig,
    GHLListCalendarResourcesConfig,
    GHLCreateCalendarResourceConfig,
    GHLGetCalendarNotificationsConfig,
    GHLCreateCalendarNotificationConfig,
    GHLFindCalendarNotificationConfig,
    GHLUpdateCalendarNotificationConfig,
    GHLDeleteCalendarNotificationConfig,
    GHLGetAvailabilitySchedulesConfig,
    GHLGetAvailabilityScheduleConfig,
    GHLUpdateAvailabilityScheduleConfig,
    GHLDeleteAvailabilityScheduleConfig,
    GHLCreateAvailabilityScheduleConfig,
    GHLAddCalendarToScheduleConfig,
    GHLRemoveCalendarFromScheduleConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_calendar_groups": _get_calendar_groups,
    "create_calendar_group": _create_calendar_group,
    "validate_calendar_group_slug": _validate_calendar_group_slug,
    "delete_calendar_group": _delete_calendar_group,
    "update_calendar_group": _update_calendar_group,
    "disable_calendar_group": _disable_calendar_group,
    "create_appointment": _create_appointment,
    "edit_appointment": _edit_appointment,
    "get_appointment": _get_appointment,
    "get_calendar_events": _get_calendar_events,
    "get_blocked_slots": _get_blocked_slots,
    "create_block_slot": _create_block_slot,
    "edit_block_slot": _edit_block_slot,
    "delete_calendar_event": _delete_calendar_event,
    "get_free_slots": _get_free_slots,
    "get_calendars": _get_calendars,
    "get_calendar": _get_calendar,
    "delete_calendar": _delete_calendar,
    "create_calendar": _create_calendar,
    "update_calendar": _update_calendar,
    "get_appointment_notes": _get_appointment_notes,
    "create_appointment_note": _create_appointment_note,
    "update_appointment_note": _update_appointment_note,
    "delete_appointment_note": _delete_appointment_note,
    "get_calendar_resource": _get_calendar_resource,
    "update_calendar_resource": _update_calendar_resource,
    "delete_calendar_resource": _delete_calendar_resource,
    "list_calendar_resources": _list_calendar_resources,
    "create_calendar_resource": _create_calendar_resource,
    "get_calendar_notifications": _get_calendar_notifications,
    "create_calendar_notification": _create_calendar_notification,
    "find_calendar_notification": _find_calendar_notification,
    "update_calendar_notification": _update_calendar_notification,
    "delete_calendar_notification": _delete_calendar_notification,
    "get_availability_schedules": _get_availability_schedules,
    "get_availability_schedule": _get_availability_schedule,
    "update_availability_schedule": _update_availability_schedule,
    "delete_availability_schedule": _delete_availability_schedule,
    "create_availability_schedule": _create_availability_schedule,
    "add_calendar_to_schedule": _add_calendar_to_schedule,
    "remove_calendar_from_schedule": _remove_calendar_from_schedule,
})


# ---- campaigns.py ----
class GHLGetCampaignsConfig(BaseModel):
    """List campaigns for a location (sub-account)."""

    operation: Literal["get_campaigns"] = Field(
        "get_campaigns",
        json_schema_extra={
            "const": "get_campaigns", "ui:hidden": True,
            "x-category": "Campaigns", "x-is-trigger": False,
            "x-display-name": "Get Campaigns",
        },
        title="Get Campaigns",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    status: Optional[str] = Field(None, title="Status", description="Filter by campaign status (e.g. draft, published)")


async def _get_campaigns(node, c, token):
    params = {"locationId": c.location_id, "status": c.status}
    return await node._request(token, "GET", "/campaigns/", params=params, action_name="get_campaigns")


GHL_OPERATION_CONFIGS += [
    GHLGetCampaignsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_campaigns": _get_campaigns,
})


# ---- companies.py ----
class GHLGetCompanyConfig(BaseModel):
    """Get a company (agency) by id."""

    operation: Literal["get_company"] = Field(
        "get_company",
        json_schema_extra={
            "const": "get_company", "ui:hidden": True,
            "x-category": "Companies", "x-is-trigger": False,
            "x-display-name": "Get Company",
        },
        title="Get Company",
    )
    company_id: str = Field(..., title="Company ID", description="The company (agency) to fetch")


async def _get_company(node, c, token):
    return await node._request(token, "GET", f"/companies/{c.company_id}", action_name="get_company")


GHL_OPERATION_CONFIGS += [
    GHLGetCompanyConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_company": _get_company,
})


# ---- contacts.py ----
class GHLSearchContactsAdvancedConfig(BaseModel):
    """Advanced search for contacts (POST /contacts/search)."""

    operation: Literal["search_contacts_advanced"] = Field(
        "search_contacts_advanced",
        json_schema_extra={
            "const": "search_contacts_advanced", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Search Contacts (Advanced)",
        },
        title="Search Contacts (Advanced)",
    )
    body: Optional[str] = Field(
        None, title="Search Body (JSON)",
        description="Full search body as JSON (locationId, page, pageLimit, filters, sort, etc.)",
    )


class GHLGetDuplicateContactConfig(BaseModel):
    """Find a duplicate contact by phone number or email."""

    operation: Literal["get_duplicate_contact"] = Field(
        "get_duplicate_contact",
        json_schema_extra={
            "const": "get_duplicate_contact", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Get Duplicate Contact",
        },
        title="Get Duplicate Contact",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    number: Optional[str] = Field(None, title="Phone Number")
    email: Optional[str] = Field(None, title="Email")


class GHLGetContactTasksConfig(BaseModel):
    """Get all tasks for a contact."""

    operation: Literal["get_contact_tasks"] = Field(
        "get_contact_tasks",
        json_schema_extra={
            "const": "get_contact_tasks", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Get Contact Tasks",
        },
        title="Get Contact Tasks",
    )
    contact_id: str = Field(..., title="Contact ID")


class GHLCreateContactTaskConfig(BaseModel):
    """Create a task for a contact."""

    operation: Literal["create_contact_task"] = Field(
        "create_contact_task",
        json_schema_extra={
            "const": "create_contact_task", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Create Contact Task",
        },
        title="Create Contact Task",
    )
    contact_id: str = Field(..., title="Contact ID")
    title: str = Field(..., title="Title")
    due_date: str = Field(..., title="Due Date", description="ISO date, e.g. 2021-07-28T00:00:00.000Z")
    completed: str = Field(
        "false", title="Completed",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    body: Optional[str] = Field(None, title="Body", description="Task description")
    assigned_to: Optional[str] = Field(None, title="Assigned To", description="User id")


class GHLGetContactTaskConfig(BaseModel):
    """Get a single task for a contact."""

    operation: Literal["get_contact_task"] = Field(
        "get_contact_task",
        json_schema_extra={
            "const": "get_contact_task", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Get Contact Task",
        },
        title="Get Contact Task",
    )
    contact_id: str = Field(..., title="Contact ID")
    task_id: str = Field(..., title="Task ID")


class GHLUpdateContactTaskConfig(BaseModel):
    """Update a contact's task."""

    operation: Literal["update_contact_task"] = Field(
        "update_contact_task",
        json_schema_extra={
            "const": "update_contact_task", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Update Contact Task",
        },
        title="Update Contact Task",
    )
    contact_id: str = Field(..., title="Contact ID")
    task_id: str = Field(..., title="Task ID")
    title: Optional[str] = Field(None, title="Title")
    body: Optional[str] = Field(None, title="Body")
    due_date: Optional[str] = Field(None, title="Due Date")
    completed: Optional[str] = Field(
        None, title="Completed",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    assigned_to: Optional[str] = Field(None, title="Assigned To", description="User id")


class GHLDeleteContactTaskConfig(BaseModel):
    """Delete a contact's task."""

    operation: Literal["delete_contact_task"] = Field(
        "delete_contact_task",
        json_schema_extra={
            "const": "delete_contact_task", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Delete Contact Task",
        },
        title="Delete Contact Task",
    )
    contact_id: str = Field(..., title="Contact ID")
    task_id: str = Field(..., title="Task ID")


class GHLUpdateContactTaskCompletedConfig(BaseModel):
    """Set the completed flag on a contact's task."""

    operation: Literal["update_contact_task_completed"] = Field(
        "update_contact_task_completed",
        json_schema_extra={
            "const": "update_contact_task_completed", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Update Contact Task Completed",
        },
        title="Update Contact Task Completed",
    )
    contact_id: str = Field(..., title="Contact ID")
    task_id: str = Field(..., title="Task ID")
    completed: str = Field(
        "true", title="Completed",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLGetAppointmentsForContactConfig(BaseModel):
    """Get appointments for a contact."""

    operation: Literal["get_appointments_for_contact"] = Field(
        "get_appointments_for_contact",
        json_schema_extra={
            "const": "get_appointments_for_contact", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Get Appointments For Contact",
        },
        title="Get Appointments For Contact",
    )
    contact_id: str = Field(..., title="Contact ID")


class GHLAddContactTagsConfig(BaseModel):
    """Add tags to a contact."""

    operation: Literal["add_contact_tags"] = Field(
        "add_contact_tags",
        json_schema_extra={
            "const": "add_contact_tags", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Add Contact Tags",
        },
        title="Add Contact Tags",
    )
    contact_id: str = Field(..., title="Contact ID")
    tags: str = Field(..., title="Tags", description="Comma-separated tags")


class GHLRemoveContactTagsConfig(BaseModel):
    """Remove tags from a contact."""

    operation: Literal["remove_contact_tags"] = Field(
        "remove_contact_tags",
        json_schema_extra={
            "const": "remove_contact_tags", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Remove Contact Tags",
        },
        title="Remove Contact Tags",
    )
    contact_id: str = Field(..., title="Contact ID")
    tags: str = Field(..., title="Tags", description="Comma-separated tags")


class GHLGetContactNotesConfig(BaseModel):
    """Get all notes for a contact."""

    operation: Literal["get_contact_notes"] = Field(
        "get_contact_notes",
        json_schema_extra={
            "const": "get_contact_notes", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Get Contact Notes",
        },
        title="Get Contact Notes",
    )
    contact_id: str = Field(..., title="Contact ID")


class GHLCreateContactNoteConfig(BaseModel):
    """Create a note for a contact."""

    operation: Literal["create_contact_note"] = Field(
        "create_contact_note",
        json_schema_extra={
            "const": "create_contact_note", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Create Contact Note",
        },
        title="Create Contact Note",
    )
    contact_id: str = Field(..., title="Contact ID")
    body: str = Field(..., title="Body", description="Note content")
    user_id: Optional[str] = Field(None, title="User ID")
    title: Optional[str] = Field(None, title="Title")
    color: Optional[str] = Field(None, title="Color")
    pinned: Optional[str] = Field(
        None, title="Pinned",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLGetContactNoteConfig(BaseModel):
    """Get a single note for a contact."""

    operation: Literal["get_contact_note"] = Field(
        "get_contact_note",
        json_schema_extra={
            "const": "get_contact_note", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Get Contact Note",
        },
        title="Get Contact Note",
    )
    contact_id: str = Field(..., title="Contact ID")
    id: str = Field(..., title="Note ID")


class GHLUpdateContactNoteConfig(BaseModel):
    """Update a contact's note."""

    operation: Literal["update_contact_note"] = Field(
        "update_contact_note",
        json_schema_extra={
            "const": "update_contact_note", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Update Contact Note",
        },
        title="Update Contact Note",
    )
    contact_id: str = Field(..., title="Contact ID")
    id: str = Field(..., title="Note ID")
    body: Optional[str] = Field(None, title="Body")
    user_id: Optional[str] = Field(None, title="User ID")
    title: Optional[str] = Field(None, title="Title")
    color: Optional[str] = Field(None, title="Color")
    pinned: Optional[str] = Field(
        None, title="Pinned",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLDeleteContactNoteConfig(BaseModel):
    """Delete a contact's note."""

    operation: Literal["delete_contact_note"] = Field(
        "delete_contact_note",
        json_schema_extra={
            "const": "delete_contact_note", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Delete Contact Note",
        },
        title="Delete Contact Note",
    )
    contact_id: str = Field(..., title="Contact ID")
    id: str = Field(..., title="Note ID")


class GHLBulkUpdateContactsTagsConfig(BaseModel):
    """Bulk add or remove tags across many contacts."""

    operation: Literal["bulk_update_contacts_tags"] = Field(
        "bulk_update_contacts_tags",
        json_schema_extra={
            "const": "bulk_update_contacts_tags", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Bulk Update Contacts Tags",
        },
        title="Bulk Update Contacts Tags",
    )
    type: str = Field(..., title="Type", description="add or remove", json_schema_extra={
        "enum": ["add", "remove"], "x-enum-searchable": True,
    })
    location_id: str = Field(..., title="Location ID")
    contacts: str = Field(..., title="Contact IDs", description="Comma-separated contact ids")
    tags: str = Field(..., title="Tags", description="Comma-separated tags")
    remove_all_tags: Optional[str] = Field(
        None, title="Remove All Tags",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLBulkUpdateContactsBusinessConfig(BaseModel):
    """Add or remove multiple contacts from a business."""

    operation: Literal["bulk_update_contacts_business"] = Field(
        "bulk_update_contacts_business",
        json_schema_extra={
            "const": "bulk_update_contacts_business", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Bulk Add/Remove Contacts From Business",
        },
        title="Bulk Add/Remove Contacts From Business",
    )
    location_id: str = Field(..., title="Location ID")
    ids: str = Field(..., title="Contact IDs", description="Comma-separated contact ids")
    business_id: str = Field(..., title="Business ID", description="Business id (omit to remove)")


class GHLGetContactConfig(BaseModel):
    """Get a contact by id."""

    operation: Literal["get_contact"] = Field(
        "get_contact",
        json_schema_extra={
            "const": "get_contact", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Get Contact",
        },
        title="Get Contact",
    )
    contact_id: str = Field(..., title="Contact ID")


class GHLUpdateContactConfig(BaseModel):
    """Update a contact."""

    operation: Literal["update_contact"] = Field(
        "update_contact",
        json_schema_extra={
            "const": "update_contact", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Update Contact",
        },
        title="Update Contact",
    )
    contact_id: str = Field(..., title="Contact ID")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    name: Optional[str] = Field(None, title="Name")
    email: Optional[str] = Field(None, title="Email")
    phone: Optional[str] = Field(None, title="Phone")
    address1: Optional[str] = Field(None, title="Address")
    city: Optional[str] = Field(None, title="City")
    state: Optional[str] = Field(None, title="State")
    postal_code: Optional[str] = Field(None, title="Postal Code")
    website: Optional[str] = Field(None, title="Website")
    timezone: Optional[str] = Field(None, title="Timezone")
    dnd: Optional[str] = Field(
        None, title="DND",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    dnd_settings: Optional[str] = Field(None, title="DND Settings (JSON)")
    inbound_dnd_settings: Optional[str] = Field(None, title="Inbound DND Settings (JSON)")
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags")
    custom_fields: Optional[str] = Field(None, title="Custom Fields (JSON)", description="JSON array of {id/key, field_value}")
    source: Optional[str] = Field(None, title="Source")
    date_of_birth: Optional[str] = Field(None, title="Date of Birth")
    country: Optional[str] = Field(None, title="Country")
    assigned_to: Optional[str] = Field(None, title="Assigned To", description="User id")


class GHLDeleteContactConfig(BaseModel):
    """Delete a contact."""

    operation: Literal["delete_contact"] = Field(
        "delete_contact",
        json_schema_extra={
            "const": "delete_contact", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Delete Contact",
        },
        title="Delete Contact",
    )
    contact_id: str = Field(..., title="Contact ID")


class GHLUpsertContactConfig(BaseModel):
    """Create or update a contact (upsert)."""

    operation: Literal["upsert_contact"] = Field(
        "upsert_contact",
        json_schema_extra={
            "const": "upsert_contact", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Upsert Contact",
        },
        title="Upsert Contact",
    )
    location_id: str = Field(..., title="Location ID")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    name: Optional[str] = Field(None, title="Name")
    email: Optional[str] = Field(None, title="Email")
    gender: Optional[str] = Field(None, title="Gender")
    phone: Optional[str] = Field(None, title="Phone")
    address1: Optional[str] = Field(None, title="Address")
    city: Optional[str] = Field(None, title="City")
    state: Optional[str] = Field(None, title="State")
    postal_code: Optional[str] = Field(None, title="Postal Code")
    website: Optional[str] = Field(None, title="Website")
    timezone: Optional[str] = Field(None, title="Timezone")
    dnd: Optional[str] = Field(
        None, title="DND",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    dnd_settings: Optional[str] = Field(None, title="DND Settings (JSON)")
    inbound_dnd_settings: Optional[str] = Field(None, title="Inbound DND Settings (JSON)")
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags")
    custom_fields: Optional[str] = Field(None, title="Custom Fields (JSON)")
    source: Optional[str] = Field(None, title="Source")
    date_of_birth: Optional[str] = Field(None, title="Date of Birth")
    country: Optional[str] = Field(None, title="Country")
    company_name: Optional[str] = Field(None, title="Company Name")
    assigned_to: Optional[str] = Field(None, title="Assigned To", description="User id")
    create_new_if_duplicate_allowed: Optional[str] = Field(
        None, title="Create New If Duplicate Allowed",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLGetContactsByBusinessIdConfig(BaseModel):
    """Get contacts belonging to a business."""

    operation: Literal["get_contacts_by_business_id"] = Field(
        "get_contacts_by_business_id",
        json_schema_extra={
            "const": "get_contacts_by_business_id", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Get Contacts By Business",
        },
        title="Get Contacts By Business",
    )
    business_id: str = Field(..., title="Business ID")
    location_id: str = Field(..., title="Location ID")
    limit: Optional[str] = Field(None, title="Limit")
    skip: Optional[str] = Field(None, title="Skip")
    query: Optional[str] = Field(None, title="Query", description="Search term")


class GHLAddContactFollowersConfig(BaseModel):
    """Add followers to a contact."""

    operation: Literal["add_contact_followers"] = Field(
        "add_contact_followers",
        json_schema_extra={
            "const": "add_contact_followers", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Add Contact Followers",
        },
        title="Add Contact Followers",
    )
    contact_id: str = Field(..., title="Contact ID")
    followers: str = Field(..., title="Followers", description="Comma-separated user ids")


class GHLRemoveContactFollowersConfig(BaseModel):
    """Remove followers from a contact."""

    operation: Literal["remove_contact_followers"] = Field(
        "remove_contact_followers",
        json_schema_extra={
            "const": "remove_contact_followers", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Remove Contact Followers",
        },
        title="Remove Contact Followers",
    )
    contact_id: str = Field(..., title="Contact ID")
    followers: str = Field(..., title="Followers", description="Comma-separated user ids")


class GHLAddContactToCampaignConfig(BaseModel):
    """Add a contact to a campaign."""

    operation: Literal["add_contact_to_campaign"] = Field(
        "add_contact_to_campaign",
        json_schema_extra={
            "const": "add_contact_to_campaign", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Add Contact To Campaign",
        },
        title="Add Contact To Campaign",
    )
    contact_id: str = Field(..., title="Contact ID")
    campaign_id: str = Field(..., title="Campaign ID")


class GHLRemoveContactFromCampaignConfig(BaseModel):
    """Remove a contact from a campaign."""

    operation: Literal["remove_contact_from_campaign"] = Field(
        "remove_contact_from_campaign",
        json_schema_extra={
            "const": "remove_contact_from_campaign", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Remove Contact From Campaign",
        },
        title="Remove Contact From Campaign",
    )
    contact_id: str = Field(..., title="Contact ID")
    campaign_id: str = Field(..., title="Campaign ID")


class GHLRemoveContactFromEveryCampaignConfig(BaseModel):
    """Remove a contact from every campaign."""

    operation: Literal["remove_contact_from_every_campaign"] = Field(
        "remove_contact_from_every_campaign",
        json_schema_extra={
            "const": "remove_contact_from_every_campaign", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Remove Contact From Every Campaign",
        },
        title="Remove Contact From Every Campaign",
    )
    contact_id: str = Field(..., title="Contact ID")


class GHLAddContactToWorkflowConfig(BaseModel):
    """Add a contact to a workflow."""

    operation: Literal["add_contact_to_workflow"] = Field(
        "add_contact_to_workflow",
        json_schema_extra={
            "const": "add_contact_to_workflow", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Add Contact To Workflow",
        },
        title="Add Contact To Workflow",
    )
    contact_id: str = Field(..., title="Contact ID")
    workflow_id: str = Field(..., title="Workflow ID")
    event_start_time: Optional[str] = Field(None, title="Event Start Time", description="ISO datetime")


class GHLRemoveContactFromWorkflowConfig(BaseModel):
    """Remove a contact from a workflow."""

    operation: Literal["remove_contact_from_workflow"] = Field(
        "remove_contact_from_workflow",
        json_schema_extra={
            "const": "remove_contact_from_workflow", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Remove Contact From Workflow",
        },
        title="Remove Contact From Workflow",
    )
    contact_id: str = Field(..., title="Contact ID")
    workflow_id: str = Field(..., title="Workflow ID")
    event_start_time: Optional[str] = Field(None, title="Event Start Time", description="ISO datetime")


class GHLCreateContactConfig(BaseModel):
    """Create a contact."""

    operation: Literal["create_contact"] = Field(
        "create_contact",
        json_schema_extra={
            "const": "create_contact", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "Create Contact",
        },
        title="Create Contact",
    )
    location_id: str = Field(..., title="Location ID")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    name: Optional[str] = Field(None, title="Name")
    email: Optional[str] = Field(None, title="Email")
    gender: Optional[str] = Field(None, title="Gender")
    phone: Optional[str] = Field(None, title="Phone")
    address1: Optional[str] = Field(None, title="Address")
    city: Optional[str] = Field(None, title="City")
    state: Optional[str] = Field(None, title="State")
    postal_code: Optional[str] = Field(None, title="Postal Code")
    website: Optional[str] = Field(None, title="Website")
    timezone: Optional[str] = Field(None, title="Timezone")
    dnd: Optional[str] = Field(
        None, title="DND",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    dnd_settings: Optional[str] = Field(None, title="DND Settings (JSON)")
    inbound_dnd_settings: Optional[str] = Field(None, title="Inbound DND Settings (JSON)")
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags")
    custom_fields: Optional[str] = Field(None, title="Custom Fields (JSON)")
    source: Optional[str] = Field(None, title="Source")
    date_of_birth: Optional[str] = Field(None, title="Date of Birth")
    country: Optional[str] = Field(None, title="Country")
    company_name: Optional[str] = Field(None, title="Company Name")
    assigned_to: Optional[str] = Field(None, title="Assigned To", description="User id")


class GHLGetContactsConfig(BaseModel):
    """List contacts for a location."""

    operation: Literal["get_contacts"] = Field(
        "get_contacts",
        json_schema_extra={
            "const": "get_contacts", "ui:hidden": True,
            "x-category": "Contacts", "x-is-trigger": False,
            "x-display-name": "List Contacts",
        },
        title="List Contacts",
    )
    location_id: str = Field(..., title="Location ID")
    start_after_id: Optional[str] = Field(None, title="Start After ID", description="Pagination cursor id")
    start_after: Optional[str] = Field(None, title="Start After", description="Pagination cursor timestamp")
    query: Optional[str] = Field(None, title="Query", description="Search term")
    limit: Optional[str] = Field(None, title="Limit")


async def _search_contacts_advanced(node, c, token):
    return await node._request(token, "POST", "/contacts/search", json_body=_ghl_json(c.body), action_name="search_contacts_advanced")


async def _get_duplicate_contact(node, c, token):
    params = {"locationId": c.location_id, "number": c.number, "email": c.email}
    return await node._request(token, "GET", "/contacts/search/duplicate", params=params, action_name="get_duplicate_contact")


async def _get_contact_tasks(node, c, token):
    return await node._request(token, "GET", f"/contacts/{c.contact_id}/tasks", action_name="get_contact_tasks")


async def _create_contact_task(node, c, token):
    body = {
        "title": c.title, "body": c.body, "dueDate": c.due_date,
        "completed": _ghl_bool(c.completed), "assignedTo": c.assigned_to,
    }
    return await node._request(token, "POST", f"/contacts/{c.contact_id}/tasks", json_body=body, action_name="create_contact_task")


async def _get_contact_task(node, c, token):
    return await node._request(token, "GET", f"/contacts/{c.contact_id}/tasks/{c.task_id}", action_name="get_contact_task")


async def _update_contact_task(node, c, token):
    body = {
        "title": c.title, "body": c.body, "dueDate": c.due_date,
        "completed": _ghl_bool(c.completed), "assignedTo": c.assigned_to,
    }
    return await node._request(token, "PUT", f"/contacts/{c.contact_id}/tasks/{c.task_id}", json_body=body, action_name="update_contact_task")


async def _delete_contact_task(node, c, token):
    return await node._request(token, "DELETE", f"/contacts/{c.contact_id}/tasks/{c.task_id}", action_name="delete_contact_task")


async def _update_contact_task_completed(node, c, token):
    body = {"completed": _ghl_bool(c.completed)}
    return await node._request(token, "PUT", f"/contacts/{c.contact_id}/tasks/{c.task_id}/completed", json_body=body, action_name="update_contact_task_completed")


async def _get_appointments_for_contact(node, c, token):
    return await node._request(token, "GET", f"/contacts/{c.contact_id}/appointments", action_name="get_appointments_for_contact")


async def _add_contact_tags(node, c, token):
    body = {"tags": _ghl_csv(c.tags)}
    return await node._request(token, "POST", f"/contacts/{c.contact_id}/tags", json_body=body, action_name="add_contact_tags")


async def _remove_contact_tags(node, c, token):
    body = {"tags": _ghl_csv(c.tags)}
    return await node._request(token, "DELETE", f"/contacts/{c.contact_id}/tags", json_body=body, action_name="remove_contact_tags")


async def _get_contact_notes(node, c, token):
    return await node._request(token, "GET", f"/contacts/{c.contact_id}/notes", action_name="get_contact_notes")


async def _create_contact_note(node, c, token):
    body = {
        "userId": c.user_id, "body": c.body, "title": c.title,
        "color": c.color, "pinned": _ghl_bool(c.pinned),
    }
    return await node._request(token, "POST", f"/contacts/{c.contact_id}/notes", json_body=body, action_name="create_contact_note")


async def _get_contact_note(node, c, token):
    return await node._request(token, "GET", f"/contacts/{c.contact_id}/notes/{c.id}", action_name="get_contact_note")


async def _update_contact_note(node, c, token):
    body = {
        "userId": c.user_id, "body": c.body, "title": c.title,
        "color": c.color, "pinned": _ghl_bool(c.pinned),
    }
    return await node._request(token, "PUT", f"/contacts/{c.contact_id}/notes/{c.id}", json_body=body, action_name="update_contact_note")


async def _delete_contact_note(node, c, token):
    return await node._request(token, "DELETE", f"/contacts/{c.contact_id}/notes/{c.id}", action_name="delete_contact_note")


async def _bulk_update_contacts_tags(node, c, token):
    body = {
        "contacts": _ghl_csv(c.contacts), "tags": _ghl_csv(c.tags),
        "locationId": c.location_id, "removeAllTags": _ghl_bool(c.remove_all_tags),
    }
    return await node._request(token, "POST", f"/contacts/bulk/tags/update/{c.type}", json_body=body, action_name="bulk_update_contacts_tags")


async def _bulk_update_contacts_business(node, c, token):
    body = {"locationId": c.location_id, "ids": _ghl_csv(c.ids), "businessId": c.business_id}
    return await node._request(token, "POST", "/contacts/bulk/business", json_body=body, action_name="bulk_update_contacts_business")


async def _get_contact(node, c, token):
    return await node._request(token, "GET", f"/contacts/{c.contact_id}", action_name="get_contact")


async def _update_contact(node, c, token):
    body = {
        "firstName": c.first_name, "lastName": c.last_name, "name": c.name,
        "email": c.email, "phone": c.phone, "address1": c.address1, "city": c.city,
        "state": c.state, "postalCode": c.postal_code, "website": c.website,
        "timezone": c.timezone, "dnd": _ghl_bool(c.dnd),
        "dndSettings": _ghl_json(c.dnd_settings), "inboundDndSettings": _ghl_json(c.inbound_dnd_settings),
        "tags": _ghl_csv(c.tags), "customFields": _ghl_json(c.custom_fields),
        "source": c.source, "dateOfBirth": c.date_of_birth, "country": c.country,
        "assignedTo": c.assigned_to,
    }
    return await node._request(token, "PUT", f"/contacts/{c.contact_id}", json_body=body, action_name="update_contact")


async def _delete_contact(node, c, token):
    return await node._request(token, "DELETE", f"/contacts/{c.contact_id}", action_name="delete_contact")


async def _upsert_contact(node, c, token):
    body = {
        "firstName": c.first_name, "lastName": c.last_name, "name": c.name,
        "email": c.email, "locationId": c.location_id, "gender": c.gender,
        "phone": c.phone, "address1": c.address1, "city": c.city, "state": c.state,
        "postalCode": c.postal_code, "website": c.website, "timezone": c.timezone,
        "dnd": _ghl_bool(c.dnd), "dndSettings": _ghl_json(c.dnd_settings),
        "inboundDndSettings": _ghl_json(c.inbound_dnd_settings), "tags": _ghl_csv(c.tags),
        "customFields": _ghl_json(c.custom_fields), "source": c.source,
        "dateOfBirth": c.date_of_birth, "country": c.country, "companyName": c.company_name,
        "assignedTo": c.assigned_to,
        "createNewIfDuplicateAllowed": _ghl_bool(c.create_new_if_duplicate_allowed),
    }
    return await node._request(token, "POST", "/contacts/upsert", json_body=body, action_name="upsert_contact")


async def _get_contacts_by_business_id(node, c, token):
    params = {"locationId": c.location_id, "limit": c.limit, "skip": c.skip, "query": c.query}
    return await node._request(token, "GET", f"/contacts/business/{c.business_id}", params=params, action_name="get_contacts_by_business_id")


async def _add_contact_followers(node, c, token):
    body = {"followers": _ghl_csv(c.followers)}
    return await node._request(token, "POST", f"/contacts/{c.contact_id}/followers", json_body=body, action_name="add_contact_followers")


async def _remove_contact_followers(node, c, token):
    body = {"followers": _ghl_csv(c.followers)}
    return await node._request(token, "DELETE", f"/contacts/{c.contact_id}/followers", json_body=body, action_name="remove_contact_followers")


async def _add_contact_to_campaign(node, c, token):
    return await node._request(token, "POST", f"/contacts/{c.contact_id}/campaigns/{c.campaign_id}", json_body={}, action_name="add_contact_to_campaign")


async def _remove_contact_from_campaign(node, c, token):
    return await node._request(token, "DELETE", f"/contacts/{c.contact_id}/campaigns/{c.campaign_id}", action_name="remove_contact_from_campaign")


async def _remove_contact_from_every_campaign(node, c, token):
    return await node._request(token, "DELETE", f"/contacts/{c.contact_id}/campaigns/removeAll", action_name="remove_contact_from_every_campaign")


async def _add_contact_to_workflow(node, c, token):
    body = {"eventStartTime": c.event_start_time}
    return await node._request(token, "POST", f"/contacts/{c.contact_id}/workflow/{c.workflow_id}", json_body=body, action_name="add_contact_to_workflow")


async def _remove_contact_from_workflow(node, c, token):
    body = {"eventStartTime": c.event_start_time}
    return await node._request(token, "DELETE", f"/contacts/{c.contact_id}/workflow/{c.workflow_id}", json_body=body, action_name="remove_contact_from_workflow")


async def _create_contact(node, c, token):
    body = {
        "firstName": c.first_name, "lastName": c.last_name, "name": c.name,
        "email": c.email, "locationId": c.location_id, "gender": c.gender,
        "phone": c.phone, "address1": c.address1, "city": c.city, "state": c.state,
        "postalCode": c.postal_code, "website": c.website, "timezone": c.timezone,
        "dnd": _ghl_bool(c.dnd), "dndSettings": _ghl_json(c.dnd_settings),
        "inboundDndSettings": _ghl_json(c.inbound_dnd_settings), "tags": _ghl_csv(c.tags),
        "customFields": _ghl_json(c.custom_fields), "source": c.source,
        "dateOfBirth": c.date_of_birth, "country": c.country, "companyName": c.company_name,
        "assignedTo": c.assigned_to,
    }
    return await node._request(token, "POST", "/contacts/", json_body=body, action_name="create_contact")


async def _get_contacts(node, c, token):
    params = {
        "locationId": c.location_id, "startAfterId": c.start_after_id,
        "startAfter": c.start_after, "query": c.query, "limit": c.limit,
    }
    return await node._request(token, "GET", "/contacts/", params=params, action_name="get_contacts")


GHL_OPERATION_CONFIGS += [
    GHLSearchContactsAdvancedConfig,
    GHLGetDuplicateContactConfig,
    GHLGetContactTasksConfig,
    GHLCreateContactTaskConfig,
    GHLGetContactTaskConfig,
    GHLUpdateContactTaskConfig,
    GHLDeleteContactTaskConfig,
    GHLUpdateContactTaskCompletedConfig,
    GHLGetAppointmentsForContactConfig,
    GHLAddContactTagsConfig,
    GHLRemoveContactTagsConfig,
    GHLGetContactNotesConfig,
    GHLCreateContactNoteConfig,
    GHLGetContactNoteConfig,
    GHLUpdateContactNoteConfig,
    GHLDeleteContactNoteConfig,
    GHLBulkUpdateContactsTagsConfig,
    GHLBulkUpdateContactsBusinessConfig,
    GHLGetContactConfig,
    GHLUpdateContactConfig,
    GHLDeleteContactConfig,
    GHLUpsertContactConfig,
    GHLGetContactsByBusinessIdConfig,
    GHLAddContactFollowersConfig,
    GHLRemoveContactFollowersConfig,
    GHLAddContactToCampaignConfig,
    GHLRemoveContactFromCampaignConfig,
    GHLRemoveContactFromEveryCampaignConfig,
    GHLAddContactToWorkflowConfig,
    GHLRemoveContactFromWorkflowConfig,
    GHLCreateContactConfig,
    GHLGetContactsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "search_contacts_advanced": _search_contacts_advanced,
    "get_duplicate_contact": _get_duplicate_contact,
    "get_contact_tasks": _get_contact_tasks,
    "create_contact_task": _create_contact_task,
    "get_contact_task": _get_contact_task,
    "update_contact_task": _update_contact_task,
    "delete_contact_task": _delete_contact_task,
    "update_contact_task_completed": _update_contact_task_completed,
    "get_appointments_for_contact": _get_appointments_for_contact,
    "add_contact_tags": _add_contact_tags,
    "remove_contact_tags": _remove_contact_tags,
    "get_contact_notes": _get_contact_notes,
    "create_contact_note": _create_contact_note,
    "get_contact_note": _get_contact_note,
    "update_contact_note": _update_contact_note,
    "delete_contact_note": _delete_contact_note,
    "bulk_update_contacts_tags": _bulk_update_contacts_tags,
    "bulk_update_contacts_business": _bulk_update_contacts_business,
    "get_contact": _get_contact,
    "update_contact": _update_contact,
    "delete_contact": _delete_contact,
    "upsert_contact": _upsert_contact,
    "get_contacts_by_business_id": _get_contacts_by_business_id,
    "add_contact_followers": _add_contact_followers,
    "remove_contact_followers": _remove_contact_followers,
    "add_contact_to_campaign": _add_contact_to_campaign,
    "remove_contact_from_campaign": _remove_contact_from_campaign,
    "remove_contact_from_every_campaign": _remove_contact_from_every_campaign,
    "add_contact_to_workflow": _add_contact_to_workflow,
    "remove_contact_from_workflow": _remove_contact_from_workflow,
    "create_contact": _create_contact,
    "get_contacts": _get_contacts,
})


# ---- conversation_ai.py ----
_CONV_AI_VERSION = "2021-04-15"


class GHLCreateAgentActionConfig(BaseModel):
    """Attach an action to a Conversation AI agent."""

    operation: Literal["create_agent_action"] = Field(
        "create_agent_action",
        json_schema_extra={
            "const": "create_agent_action", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Create Agent Action",
        },
        title="Create Agent Action",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to attach the action to")
    type: str = Field(
        ..., title="Type", description="Action type",
        json_schema_extra={
            "enum": [
                "triggerWorkflow", "updateContactField", "appointmentBooking",
                "stopBot", "humanHandOver", "advancedFollowup", "transferBot",
            ],
            "x-enum-searchable": True,
        },
    )
    name: str = Field(..., title="Name", description="Action name")
    details: str = Field(
        ..., title="Details (JSON)",
        description="Action-type-specific details as a JSON object",
    )


class GHLListAgentActionsConfig(BaseModel):
    """List the actions attached to an agent."""

    operation: Literal["list_agent_actions"] = Field(
        "list_agent_actions",
        json_schema_extra={
            "const": "list_agent_actions", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "List Agent Actions",
        },
        title="List Agent Actions",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent whose actions to list")


class GHLGetAgentActionByIdConfig(BaseModel):
    """Get a single agent action by id."""

    operation: Literal["get_agent_action_by_id"] = Field(
        "get_agent_action_by_id",
        json_schema_extra={
            "const": "get_agent_action_by_id", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Get Agent Action",
        },
        title="Get Agent Action",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent the action belongs to")
    action_id: str = Field(..., title="Action ID", description="The action to fetch")


class GHLUpdateAgentActionConfig(BaseModel):
    """Update an agent action."""

    operation: Literal["update_agent_action"] = Field(
        "update_agent_action",
        json_schema_extra={
            "const": "update_agent_action", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Update Agent Action",
        },
        title="Update Agent Action",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent the action belongs to")
    action_id: str = Field(..., title="Action ID", description="The action to update")
    type: str = Field(
        ..., title="Type", description="Action type",
        json_schema_extra={
            "enum": [
                "triggerWorkflow", "updateContactField", "appointmentBooking",
                "stopBot", "humanHandOver", "advancedFollowup", "transferBot",
            ],
            "x-enum-searchable": True,
        },
    )
    name: str = Field(..., title="Name", description="Action name")
    details: str = Field(
        ..., title="Details (JSON)",
        description="Action-type-specific details as a JSON object",
    )


class GHLDeleteAgentActionConfig(BaseModel):
    """Remove an action from an agent."""

    operation: Literal["delete_agent_action"] = Field(
        "delete_agent_action",
        json_schema_extra={
            "const": "delete_agent_action", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Delete Agent Action",
        },
        title="Delete Agent Action",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent the action belongs to")
    action_id: str = Field(..., title="Action ID", description="The action to delete")


class GHLUpdateAgentFollowupSettingsConfig(BaseModel):
    """Update an agent's advanced follow-up settings."""

    operation: Literal["update_agent_followup_settings"] = Field(
        "update_agent_followup_settings",
        json_schema_extra={
            "const": "update_agent_followup_settings", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Update Agent Followup Settings",
        },
        title="Update Agent Followup Settings",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to configure")
    action_ids: str = Field(
        ..., title="Action IDs", description="Comma-separated list of action ids",
    )
    followup_settings: str = Field(
        ..., title="Followup Settings (JSON)",
        description=(
            "Followup settings object as JSON. Keys: dynamicChannelSwitching (bool, "
            "required), followUpHours (bool), workingHours (array of "
            "{dayOfTheWeek, intervals:[{startHour,startMinute,endHour,endMinute}]}), "
            "timezoneToUse ('contact'|'business')"
        ),
    )


class GHLCreateConversationAiAgentConfig(BaseModel):
    """Create a Conversation AI agent (employee)."""

    operation: Literal["create_conversation_ai_agent"] = Field(
        "create_conversation_ai_agent",
        json_schema_extra={
            "const": "create_conversation_ai_agent", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Create Agent",
        },
        title="Create Agent",
    )
    name: str = Field(..., title="Name", description="Agent name")
    personality: str = Field(..., title="Personality", description="Agent personality")
    goal: str = Field(..., title="Goal", description="Agent goal")
    instructions: str = Field(..., title="Instructions", description="Agent instructions")
    business_name: Optional[str] = Field(None, title="Business Name")
    mode: Optional[str] = Field(
        None, title="Mode",
        json_schema_extra={
            "enum": ["off", "suggestive", "auto-pilot"], "x-enum-searchable": True,
        },
    )
    channels: Optional[str] = Field(
        None, title="Channels", description="Comma-separated list of channels",
    )
    is_primary: Optional[str] = Field(
        None, title="Is Primary",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    wait_time: Optional[str] = Field(None, title="Wait Time")
    wait_time_unit: Optional[str] = Field(
        None, title="Wait Time Unit",
        json_schema_extra={
            "enum": ["minutes", "seconds"], "x-enum-searchable": True,
        },
    )
    sleep_enabled: Optional[str] = Field(
        None, title="Sleep Enabled",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    sleep_time: Optional[str] = Field(None, title="Sleep Time")
    sleep_time_unit: Optional[str] = Field(
        None, title="Sleep Time Unit",
        json_schema_extra={
            "enum": ["hours", "minutes", "seconds"], "x-enum-searchable": True,
        },
    )
    auto_pilot_max_messages: Optional[str] = Field(None, title="Auto Pilot Max Messages")
    knowledge_base_ids: Optional[str] = Field(
        None, title="Knowledge Base IDs", description="Comma-separated list of knowledge base ids",
    )
    respond_to_images: Optional[str] = Field(
        None, title="Respond To Images",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    respond_to_audio: Optional[str] = Field(
        None, title="Respond To Audio",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    sleep_on_manual_message: Optional[str] = Field(
        None, title="Sleep On Manual Message",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    sleep_on_workflow_message: Optional[str] = Field(
        None, title="Sleep On Workflow Message",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLSearchAgentConfig(BaseModel):
    """Search Conversation AI agents."""

    operation: Literal["search_conversation_ai_agents"] = Field(
        "search_conversation_ai_agents",
        json_schema_extra={
            "const": "search_conversation_ai_agents", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Search Agents",
        },
        title="Search Agents",
    )
    start_after: Optional[str] = Field(None, title="Start After", description="Pagination cursor")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    query: Optional[str] = Field(None, title="Query", description="Search query")


class GHLUpdateAgentConfig(BaseModel):
    """Update a Conversation AI agent."""

    operation: Literal["update_conversation_ai_agent"] = Field(
        "update_conversation_ai_agent",
        json_schema_extra={
            "const": "update_conversation_ai_agent", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Update Agent",
        },
        title="Update Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to update")
    auto_pilot_max_messages: str = Field(
        ..., title="Auto Pilot Max Messages",
        description="Max messages in auto-pilot mode (required)",
    )
    name: Optional[str] = Field(None, title="Name")
    personality: Optional[str] = Field(None, title="Personality")
    goal: Optional[str] = Field(None, title="Goal")
    instructions: Optional[str] = Field(None, title="Instructions")
    business_name: Optional[str] = Field(None, title="Business Name")
    mode: Optional[str] = Field(
        None, title="Mode",
        json_schema_extra={
            "enum": ["off", "suggestive", "auto-pilot"], "x-enum-searchable": True,
        },
    )
    channels: Optional[str] = Field(
        None, title="Channels", description="Comma-separated list of channels",
    )
    is_primary: Optional[str] = Field(
        None, title="Is Primary",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    wait_time: Optional[str] = Field(None, title="Wait Time")
    wait_time_unit: Optional[str] = Field(
        None, title="Wait Time Unit",
        json_schema_extra={
            "enum": ["minutes", "seconds"], "x-enum-searchable": True,
        },
    )
    sleep_enabled: Optional[str] = Field(
        None, title="Sleep Enabled",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    sleep_time: Optional[str] = Field(None, title="Sleep Time")
    sleep_time_unit: Optional[str] = Field(
        None, title="Sleep Time Unit",
        json_schema_extra={
            "enum": ["hours", "minutes", "seconds"], "x-enum-searchable": True,
        },
    )
    knowledge_base_ids: Optional[str] = Field(
        None, title="Knowledge Base IDs", description="Comma-separated list of knowledge base ids",
    )
    respond_to_images: Optional[str] = Field(
        None, title="Respond To Images",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    respond_to_audio: Optional[str] = Field(
        None, title="Respond To Audio",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    sleep_on_manual_message: Optional[str] = Field(
        None, title="Sleep On Manual Message",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    sleep_on_workflow_message: Optional[str] = Field(
        None, title="Sleep On Workflow Message",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLGetAgentConfig(BaseModel):
    """Get a Conversation AI agent by id."""

    operation: Literal["get_conversation_ai_agent"] = Field(
        "get_conversation_ai_agent",
        json_schema_extra={
            "const": "get_conversation_ai_agent", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Get Agent",
        },
        title="Get Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to fetch")


class GHLDeleteConversationAiAgentConfig(BaseModel):
    """Delete a Conversation AI agent."""

    operation: Literal["delete_conversation_ai_agent"] = Field(
        "delete_conversation_ai_agent",
        json_schema_extra={
            "const": "delete_conversation_ai_agent", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Delete Agent",
        },
        title="Delete Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to delete")


class GHLGetGenerationDetailsConfig(BaseModel):
    """Get generation details for a message."""

    operation: Literal["get_generation_details"] = Field(
        "get_generation_details",
        json_schema_extra={
            "const": "get_generation_details", "ui:hidden": True,
            "x-category": "Conversation AI", "x-is-trigger": False,
            "x-display-name": "Get Generation Details",
        },
        title="Get Generation Details",
    )
    message_id: str = Field(..., title="Message ID", description="The message to inspect")
    source: str = Field(
        ..., title="Source", description="Generation source",
        json_schema_extra={
            "enum": ["conversation", "workflow"], "x-enum-searchable": True,
        },
    )


async def _create_agent_action(node, c, token):
    body = {"type": c.type, "name": c.name, "details": _ghl_json(c.details)}
    return await node._request(
        token, "POST", f"/conversation-ai/agents/{c.agent_id}/actions",
        json_body=body, version=_CONV_AI_VERSION, action_name="create_agent_action",
    )


async def _list_agent_actions(node, c, token):
    return await node._request(
        token, "GET", f"/conversation-ai/agents/{c.agent_id}/actions/list",
        version=_CONV_AI_VERSION, action_name="list_agent_actions",
    )


async def _get_agent_action_by_id(node, c, token):
    return await node._request(
        token, "GET", f"/conversation-ai/agents/{c.agent_id}/actions/{c.action_id}",
        version=_CONV_AI_VERSION, action_name="get_agent_action_by_id",
    )


async def _update_agent_action(node, c, token):
    body = {"type": c.type, "name": c.name, "details": _ghl_json(c.details)}
    return await node._request(
        token, "PUT", f"/conversation-ai/agents/{c.agent_id}/actions/{c.action_id}",
        json_body=body, version=_CONV_AI_VERSION, action_name="update_agent_action",
    )


async def _delete_agent_action(node, c, token):
    return await node._request(
        token, "DELETE", f"/conversation-ai/agents/{c.agent_id}/actions/{c.action_id}",
        version=_CONV_AI_VERSION, action_name="delete_agent_action",
    )


async def _update_agent_followup_settings(node, c, token):
    body = {
        "actionIds": _ghl_csv(c.action_ids),
        "followupSettings": _ghl_json(c.followup_settings),
    }
    return await node._request(
        token, "PATCH", f"/conversation-ai/agents/{c.agent_id}/followup-settings",
        json_body=body, version=_CONV_AI_VERSION, action_name="update_agent_followup_settings",
    )


async def _create_conversation_ai_agent(node, c, token):
    body = {
        "name": c.name, "businessName": c.business_name, "mode": c.mode,
        "channels": _ghl_csv(c.channels), "isPrimary": _ghl_bool(c.is_primary),
        "waitTime": _ghl_num(c.wait_time), "waitTimeUnit": c.wait_time_unit,
        "sleepEnabled": _ghl_bool(c.sleep_enabled), "sleepTime": _ghl_num(c.sleep_time),
        "sleepTimeUnit": c.sleep_time_unit, "personality": c.personality,
        "goal": c.goal, "instructions": c.instructions,
        "autoPilotMaxMessages": _ghl_num(c.auto_pilot_max_messages),
        "knowledgeBaseIds": _ghl_csv(c.knowledge_base_ids),
        "respondToImages": _ghl_bool(c.respond_to_images),
        "respondToAudio": _ghl_bool(c.respond_to_audio),
        "sleepOnManualMessage": _ghl_bool(c.sleep_on_manual_message),
        "sleepOnWorkflowMessage": _ghl_bool(c.sleep_on_workflow_message),
    }
    return await node._request(
        token, "POST", "/conversation-ai/agents",
        json_body=body, version=_CONV_AI_VERSION, action_name="create_conversation_ai_agent",
    )


async def _search_conversation_ai_agents(node, c, token):
    params = {"startAfter": c.start_after, "limit": _ghl_num(c.limit), "query": c.query}
    return await node._request(
        token, "GET", "/conversation-ai/agents/search",
        params=params, version=_CONV_AI_VERSION, action_name="search_conversation_ai_agents",
    )


async def _update_conversation_ai_agent(node, c, token):
    body = {
        "name": c.name, "businessName": c.business_name, "mode": c.mode,
        "channels": _ghl_csv(c.channels), "isPrimary": _ghl_bool(c.is_primary),
        "waitTime": _ghl_num(c.wait_time), "waitTimeUnit": c.wait_time_unit,
        "sleepEnabled": _ghl_bool(c.sleep_enabled), "sleepTime": _ghl_num(c.sleep_time),
        "sleepTimeUnit": c.sleep_time_unit, "personality": c.personality,
        "goal": c.goal, "instructions": c.instructions,
        "autoPilotMaxMessages": _ghl_num(c.auto_pilot_max_messages),
        "knowledgeBaseIds": _ghl_csv(c.knowledge_base_ids),
        "respondToImages": _ghl_bool(c.respond_to_images),
        "respondToAudio": _ghl_bool(c.respond_to_audio),
        "sleepOnManualMessage": _ghl_bool(c.sleep_on_manual_message),
        "sleepOnWorkflowMessage": _ghl_bool(c.sleep_on_workflow_message),
    }
    return await node._request(
        token, "PUT", f"/conversation-ai/agents/{c.agent_id}",
        json_body=body, version=_CONV_AI_VERSION, action_name="update_conversation_ai_agent",
    )


async def _get_conversation_ai_agent(node, c, token):
    return await node._request(
        token, "GET", f"/conversation-ai/agents/{c.agent_id}",
        version=_CONV_AI_VERSION, action_name="get_conversation_ai_agent",
    )


async def _delete_conversation_ai_agent(node, c, token):
    return await node._request(
        token, "DELETE", f"/conversation-ai/agents/{c.agent_id}",
        version=_CONV_AI_VERSION, action_name="delete_conversation_ai_agent",
    )


async def _get_generation_details(node, c, token):
    params = {"messageId": c.message_id, "source": c.source}
    return await node._request(
        token, "GET", "/conversation-ai/generations",
        params=params, version=_CONV_AI_VERSION, action_name="get_generation_details",
    )


GHL_OPERATION_CONFIGS += [
    GHLCreateAgentActionConfig,
    GHLListAgentActionsConfig,
    GHLGetAgentActionByIdConfig,
    GHLUpdateAgentActionConfig,
    GHLDeleteAgentActionConfig,
    GHLUpdateAgentFollowupSettingsConfig,
    GHLCreateConversationAiAgentConfig,
    GHLSearchAgentConfig,
    GHLUpdateAgentConfig,
    GHLGetAgentConfig,
    GHLDeleteConversationAiAgentConfig,
    GHLGetGenerationDetailsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "create_agent_action": _create_agent_action,
    "list_agent_actions": _list_agent_actions,
    "get_agent_action_by_id": _get_agent_action_by_id,
    "update_agent_action": _update_agent_action,
    "delete_agent_action": _delete_agent_action,
    "update_agent_followup_settings": _update_agent_followup_settings,
    "create_conversation_ai_agent": _create_conversation_ai_agent,
    "search_conversation_ai_agents": _search_conversation_ai_agents,
    "update_conversation_ai_agent": _update_conversation_ai_agent,
    "get_conversation_ai_agent": _get_conversation_ai_agent,
    "delete_conversation_ai_agent": _delete_conversation_ai_agent,
    "get_generation_details": _get_generation_details,
})


# ---- conversations.py ----
class GHLSearchConversationConfig(BaseModel):
    """Search conversations within a location."""

    operation: Literal["search_conversation"] = Field(
        "search_conversation",
        json_schema_extra={
            "const": "search_conversation", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Search Conversations",
        },
        title="Search Conversations",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    assigned_to: Optional[str] = Field(None, title="Assigned To")
    followers: Optional[str] = Field(None, title="Followers")
    mentions: Optional[str] = Field(None, title="Mentions")
    query: Optional[str] = Field(None, title="Query")
    sort: Optional[str] = Field(None, title="Sort", json_schema_extra={
        "enum": ["asc", "desc"], "x-enum-searchable": True,
    })
    start_after_date: Optional[str] = Field(None, title="Start After Date")
    id: Optional[str] = Field(None, title="ID")
    limit: Optional[str] = Field(None, title="Limit")
    last_message_type: Optional[str] = Field(None, title="Last Message Type")
    last_message_action: Optional[str] = Field(None, title="Last Message Action", json_schema_extra={
        "enum": ["automated", "manual"], "x-enum-searchable": True,
    })
    last_message_direction: Optional[str] = Field(None, title="Last Message Direction", json_schema_extra={
        "enum": ["inbound", "outbound"], "x-enum-searchable": True,
    })
    status: Optional[str] = Field(None, title="Status", json_schema_extra={
        "enum": ["all", "read", "unread", "starred", "recents"], "x-enum-searchable": True,
    })
    sort_by: Optional[str] = Field(None, title="Sort By", json_schema_extra={
        "enum": ["last_manual_message_date", "last_message_date", "score_profile", "overdue_at", "due_at"],
        "x-enum-searchable": True,
    })
    sort_score_profile: Optional[str] = Field(None, title="Sort Score Profile")
    score_profile: Optional[str] = Field(None, title="Score Profile")
    score_profile_min: Optional[str] = Field(None, title="Score Profile Min")
    score_profile_max: Optional[str] = Field(None, title="Score Profile Max")
    start_date: Optional[str] = Field(None, title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")


class GHLGetConversationConfig(BaseModel):
    """Get a conversation by id."""

    operation: Literal["get_conversation"] = Field(
        "get_conversation",
        json_schema_extra={
            "const": "get_conversation", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Get Conversation",
        },
        title="Get Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation to fetch")


class GHLUpdateConversationConfig(BaseModel):
    """Update a conversation."""

    operation: Literal["update_conversation"] = Field(
        "update_conversation",
        json_schema_extra={
            "const": "update_conversation", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Update Conversation",
        },
        title="Update Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation to update")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    unread_count: Optional[str] = Field(None, title="Unread Count", description="Integer")
    starred: Optional[str] = Field(None, title="Starred", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })
    feedback: Optional[str] = Field(None, title="Feedback", description="JSON object")


class GHLDeleteConversationConfig(BaseModel):
    """Delete a conversation."""

    operation: Literal["delete_conversation"] = Field(
        "delete_conversation",
        json_schema_extra={
            "const": "delete_conversation", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Delete Conversation",
        },
        title="Delete Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID", description="The conversation to delete")


class GHLCreateConversationConfig(BaseModel):
    """Create a conversation."""

    operation: Literal["create_conversation"] = Field(
        "create_conversation",
        json_schema_extra={
            "const": "create_conversation", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Create Conversation",
        },
        title="Create Conversation",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    contact_id: str = Field(..., title="Contact ID", description="Contact to open the conversation with")


class GHLGetAllCustomSubtypesConfig(BaseModel):
    """List all custom message subtypes for a location."""

    operation: Literal["get_all_custom_subtypes"] = Field(
        "get_all_custom_subtypes",
        json_schema_extra={
            "const": "get_all_custom_subtypes", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Get All Custom Subtypes",
        },
        title="Get All Custom Subtypes",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateCustomSubtypeConfig(BaseModel):
    """Create a custom message subtype."""

    operation: Literal["create_custom_subtype"] = Field(
        "create_custom_subtype",
        json_schema_extra={
            "const": "create_custom_subtype", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Create Custom Subtype",
        },
        title="Create Custom Subtype",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name")
    channel: str = Field(..., title="Channel", json_schema_extra={
        "enum": ["email", "sms"], "x-enum-searchable": True,
    })
    language: str = Field(..., title="Language")
    description: Optional[str] = Field(None, title="Description")


class GHLUpdateCustomSubtypeConfig(BaseModel):
    """Update a custom message subtype."""

    operation: Literal["update_custom_subtype"] = Field(
        "update_custom_subtype",
        json_schema_extra={
            "const": "update_custom_subtype", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Update Custom Subtype",
        },
        title="Update Custom Subtype",
    )
    id: str = Field(..., title="Subtype ID", description="The custom subtype to update")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    archived: Optional[str] = Field(None, title="Archived", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })
    resubscription_legal_form_id: Optional[str] = Field(None, title="Resubscription Legal Form ID")


class GHLGetContactUnsubscriptionStatusConfig(BaseModel):
    """Get a contact's unsubscription status."""

    operation: Literal["get_contact_unsubscription_status"] = Field(
        "get_contact_unsubscription_status",
        json_schema_extra={
            "const": "get_contact_unsubscription_status", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Get Contact Unsubscription Status",
        },
        title="Get Contact Unsubscription Status",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    contact_id: str = Field(..., title="Contact ID")
    email: Optional[str] = Field(None, title="Email")


class GHLUserSubscriptionChangeConfig(BaseModel):
    """Change a user's subscription (subscribe/unsubscribe)."""

    operation: Literal["user_subscription_change"] = Field(
        "user_subscription_change",
        json_schema_extra={
            "const": "user_subscription_change", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "User Subscription Change",
        },
        title="User Subscription Change",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    contact_id: str = Field(..., title="Contact ID")
    email: str = Field(..., title="Email")
    subscription_action: str = Field(..., title="Subscription Action")
    legal_reason: Optional[str] = Field(None, title="Legal Reason")
    legal_description: Optional[str] = Field(None, title="Legal Description")


class GHLGetEmailByIdConfig(BaseModel):
    """Get an email message by id."""

    operation: Literal["get_email_by_id"] = Field(
        "get_email_by_id",
        json_schema_extra={
            "const": "get_email_by_id", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Get Email By ID",
        },
        title="Get Email By ID",
    )
    id: str = Field(..., title="Email Message ID", description="The email message to fetch")


class GHLCancelScheduledEmailMessageConfig(BaseModel):
    """Cancel a scheduled email message."""

    operation: Literal["cancel_scheduled_email_message"] = Field(
        "cancel_scheduled_email_message",
        json_schema_extra={
            "const": "cancel_scheduled_email_message", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Cancel Scheduled Email Message",
        },
        title="Cancel Scheduled Email Message",
    )
    email_message_id: str = Field(..., title="Email Message ID", description="The scheduled email message to cancel")


class GHLExportMessagesByLocationConfig(BaseModel):
    """Export messages for a location."""

    operation: Literal["export_messages_by_location"] = Field(
        "export_messages_by_location",
        json_schema_extra={
            "const": "export_messages_by_location", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Export Messages By Location",
        },
        title="Export Messages By Location",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: Optional[str] = Field(None, title="Limit")
    cursor: Optional[str] = Field(None, title="Cursor")
    sort_by: Optional[str] = Field(None, title="Sort By", json_schema_extra={
        "enum": ["createdAt", "updatedAt"], "x-enum-searchable": True,
    })
    sort_order: Optional[str] = Field(None, title="Sort Order", json_schema_extra={
        "enum": ["asc", "desc"], "x-enum-searchable": True,
    })
    conversation_id: Optional[str] = Field(None, title="Conversation ID")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    channel: Optional[str] = Field(None, title="Channel", json_schema_extra={
        "enum": ["Call", "SMS", "Email", "WhatsApp", "Instagram", "Facebook"], "x-enum-searchable": True,
    })
    start_date: Optional[str] = Field(None, title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")


class GHLGetMessageConfig(BaseModel):
    """Get a message by id."""

    operation: Literal["get_message"] = Field(
        "get_message",
        json_schema_extra={
            "const": "get_message", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Get Message",
        },
        title="Get Message",
    )
    id: str = Field(..., title="Message ID", description="The message to fetch")


class GHLGetMessagesConfig(BaseModel):
    """Get messages for a conversation."""

    operation: Literal["get_messages"] = Field(
        "get_messages",
        json_schema_extra={
            "const": "get_messages", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Get Messages",
        },
        title="Get Messages",
    )
    conversation_id: str = Field(..., title="Conversation ID", description="Conversation whose messages to fetch")
    last_message_id: Optional[str] = Field(None, title="Last Message ID")
    limit: Optional[str] = Field(None, title="Limit")
    type: Optional[str] = Field(None, title="Type", description="Message type filter (e.g. TYPE_SMS, TYPE_EMAIL)")


class GHLSendANewMessageConfig(BaseModel):
    """Send a new message."""

    operation: Literal["send_a_new_message"] = Field(
        "send_a_new_message",
        json_schema_extra={
            "const": "send_a_new_message", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Send A New Message",
        },
        title="Send A New Message",
    )
    type: str = Field(..., title="Type", json_schema_extra={
        "enum": ["SMS", "RCS", "Email", "WhatsApp", "IG", "FB", "Custom", "Live_Chat", "TIKTOK"],
        "x-enum-searchable": True,
    })
    contact_id: str = Field(..., title="Contact ID")
    status: str = Field(..., title="Status", json_schema_extra={
        "enum": ["delivered", "failed", "pending", "read"], "x-enum-searchable": True,
    })
    sub_type: Optional[str] = Field(None, title="Sub Type", description="JSON object")
    appointment_id: Optional[str] = Field(None, title="Appointment ID")
    attachments: Optional[str] = Field(None, title="Attachments", description="Comma-separated attachment URLs")
    email_from: Optional[str] = Field(None, title="Email From")
    email_cc: Optional[str] = Field(None, title="Email CC", description="Comma-separated emails")
    email_bcc: Optional[str] = Field(None, title="Email BCC", description="Comma-separated emails")
    html: Optional[str] = Field(None, title="HTML")
    message: Optional[str] = Field(None, title="Message")
    subject: Optional[str] = Field(None, title="Subject")
    reply_message_id: Optional[str] = Field(None, title="Reply Message ID")
    template_id: Optional[str] = Field(None, title="Template ID")
    thread_id: Optional[str] = Field(None, title="Thread ID")
    scheduled_timestamp: Optional[str] = Field(None, title="Scheduled Timestamp", description="Number (epoch)")
    conversation_provider_id: Optional[str] = Field(None, title="Conversation Provider ID")
    email_to: Optional[str] = Field(None, title="Email To")
    custom_subtype_id: Optional[str] = Field(None, title="Custom Subtype ID")
    email_reply_mode: Optional[str] = Field(None, title="Email Reply Mode", json_schema_extra={
        "enum": ["reply", "reply_all"], "x-enum-searchable": True,
    })
    from_number: Optional[str] = Field(None, title="From Number")
    to_number: Optional[str] = Field(None, title="To Number")
    forward: Optional[str] = Field(None, title="Forward")
    uses_native_scheduling_ai: Optional[str] = Field(None, title="Uses Native Scheduling AI", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })
    optimization_period: Optional[str] = Field(None, title="Optimization Period", json_schema_extra={
        "enum": ["24h", "48h", "72h"], "x-enum-searchable": True,
    })


class GHLAddAnInboundMessageConfig(BaseModel):
    """Add an inbound message to a conversation."""

    operation: Literal["add_an_inbound_message"] = Field(
        "add_an_inbound_message",
        json_schema_extra={
            "const": "add_an_inbound_message", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Add An Inbound Message",
        },
        title="Add An Inbound Message",
    )
    type: str = Field(..., title="Type", json_schema_extra={
        "enum": ["SMS", "RCS", "Email", "WhatsApp", "GMB", "IG", "FB", "Custom", "WebChat",
                 "Live_Chat", "Call", "IVR_Call", "Campaign_Call", "Campaign_VoiceMail",
                 "TIKTOK", "ALL_IN_ONE_CHAT", "FORM_SUBMISSION"],
        "x-enum-searchable": True,
    })
    conversation_id: str = Field(..., title="Conversation ID")
    contact_id: str = Field(..., title="Contact ID")
    conversation_provider_id: str = Field(..., title="Conversation Provider ID")
    attachments: Optional[str] = Field(None, title="Attachments", description="Comma-separated attachment URLs")
    message: Optional[str] = Field(None, title="Message")
    html: Optional[str] = Field(None, title="HTML")
    subject: Optional[str] = Field(None, title="Subject")
    email_from: Optional[str] = Field(None, title="Email From")
    email_to: Optional[str] = Field(None, title="Email To")
    email_cc: Optional[str] = Field(None, title="Email CC", description="Comma-separated emails")
    email_bcc: Optional[str] = Field(None, title="Email BCC", description="Comma-separated emails")
    email_message_id: Optional[str] = Field(None, title="Email Message ID")
    alt_id: Optional[str] = Field(None, title="Alt ID")
    direction: Optional[str] = Field(None, title="Direction", description="JSON object")
    date: Optional[str] = Field(None, title="Date")
    call: Optional[str] = Field(None, title="Call", description="JSON object")


class GHLAddAnOutboundMessageConfig(BaseModel):
    """Add an external outbound call message."""

    operation: Literal["add_an_outbound_message"] = Field(
        "add_an_outbound_message",
        json_schema_extra={
            "const": "add_an_outbound_message", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Add An Outbound Message",
        },
        title="Add An Outbound Message",
    )
    type: str = Field(..., title="Type", json_schema_extra={
        "enum": ["Call"], "x-enum-searchable": True,
    })
    conversation_id: str = Field(..., title="Conversation ID")
    conversation_provider_id: str = Field(..., title="Conversation Provider ID")
    attachments: Optional[str] = Field(None, title="Attachments", description="Comma-separated attachment URLs")
    alt_id: Optional[str] = Field(None, title="Alt ID")
    date: Optional[str] = Field(None, title="Date")
    call: Optional[str] = Field(None, title="Call", description="JSON object")


class GHLSendReviewReplyConfig(BaseModel):
    """Send a review reply to Google My Business."""

    operation: Literal["send_review_reply"] = Field(
        "send_review_reply",
        json_schema_extra={
            "const": "send_review_reply", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Send Review Reply",
        },
        title="Send Review Reply",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    message: str = Field(..., title="Message")


class GHLCancelScheduledMessageConfig(BaseModel):
    """Cancel a scheduled message."""

    operation: Literal["cancel_scheduled_message"] = Field(
        "cancel_scheduled_message",
        json_schema_extra={
            "const": "cancel_scheduled_message", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Cancel Scheduled Message",
        },
        title="Cancel Scheduled Message",
    )
    message_id: str = Field(..., title="Message ID", description="The scheduled message to cancel")


class GHLUploadFileAttachmentsConfig(BaseModel):
    """Upload file attachments (from attachment URLs) to a conversation."""

    operation: Literal["upload_file_attachments"] = Field(
        "upload_file_attachments",
        json_schema_extra={
            "const": "upload_file_attachments", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Upload File Attachments",
        },
        title="Upload File Attachments",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    contact_id: str = Field(..., title="Contact ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    attachment_urls: str = Field(..., title="Attachment URLs", description="Comma-separated attachment URLs")
    chat_service_sid: Optional[str] = Field(None, title="Chat Service SID")
    is_group_sms: Optional[str] = Field(None, title="Is Group SMS")


class GHLInitiateFileUploadConfig(BaseModel):
    """Initiate a file upload to GCS."""

    operation: Literal["initiate_file_upload"] = Field(
        "initiate_file_upload",
        json_schema_extra={
            "const": "initiate_file_upload", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Initiate File Upload",
        },
        title="Initiate File Upload",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    conversation_id: str = Field(..., title="Conversation ID")
    filename: str = Field(..., title="Filename")
    content_type: str = Field(..., title="Content Type")
    channel: str = Field(..., title="Channel")
    file_size: Optional[str] = Field(None, title="File Size", description="Number (bytes)")


class GHLCompleteFileUploadConfig(BaseModel):
    """Complete a file upload."""

    operation: Literal["complete_file_upload"] = Field(
        "complete_file_upload",
        json_schema_extra={
            "const": "complete_file_upload", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Complete File Upload",
        },
        title="Complete File Upload",
    )
    upload_id: str = Field(..., title="Upload ID")
    file_path: str = Field(..., title="File Path")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    conversation_id: str = Field(..., title="Conversation ID")
    filename: str = Field(..., title="Filename")


class GHLUpdateMessageStatusConfig(BaseModel):
    """Update a message's delivery status."""

    operation: Literal["update_message_status"] = Field(
        "update_message_status",
        json_schema_extra={
            "const": "update_message_status", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Update Message Status",
        },
        title="Update Message Status",
    )
    message_id: str = Field(..., title="Message ID", description="The message to update")
    status: str = Field(..., title="Status", json_schema_extra={
        "enum": ["delivered", "failed", "pending", "read"], "x-enum-searchable": True,
    })
    error: Optional[str] = Field(None, title="Error", description="JSON object")
    email_message_id: Optional[str] = Field(None, title="Email Message ID")
    recipients: Optional[str] = Field(None, title="Recipients", description="Comma-separated recipients")


class GHLAddMessageAttachmentsConfig(BaseModel):
    """Add attachments to an existing message."""

    operation: Literal["add_message_attachments"] = Field(
        "add_message_attachments",
        json_schema_extra={
            "const": "add_message_attachments", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Add Message Attachments",
        },
        title="Add Message Attachments",
    )
    message_id: str = Field(..., title="Message ID", description="The message to add attachments to")
    attachments: str = Field(..., title="Attachments", description="Comma-separated attachment URLs")


class GHLGetMessageRecordingConfig(BaseModel):
    """Get a call recording by message id."""

    operation: Literal["get_message_recording"] = Field(
        "get_message_recording",
        json_schema_extra={
            "const": "get_message_recording", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Get Message Recording",
        },
        title="Get Message Recording",
    )
    message_id: str = Field(..., title="Message ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLGetMessageTranscriptionConfig(BaseModel):
    """Get a call transcription by message id."""

    operation: Literal["get_message_transcription"] = Field(
        "get_message_transcription",
        json_schema_extra={
            "const": "get_message_transcription", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Get Message Transcription",
        },
        title="Get Message Transcription",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    message_id: str = Field(..., title="Message ID")


class GHLDownloadMessageTranscriptionConfig(BaseModel):
    """Download a call transcription by message id."""

    operation: Literal["download_message_transcription"] = Field(
        "download_message_transcription",
        json_schema_extra={
            "const": "download_message_transcription", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Download Message Transcription",
        },
        title="Download Message Transcription",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    message_id: str = Field(..., title="Message ID")


class GHLLiveChatAgentTypingConfig(BaseModel):
    """Send a live-chat agent typing indicator."""

    operation: Literal["live_chat_agent_typing"] = Field(
        "live_chat_agent_typing",
        json_schema_extra={
            "const": "live_chat_agent_typing", "ui:hidden": True,
            "x-category": "Conversations", "x-is-trigger": False,
            "x-display-name": "Live Chat Agent Typing",
        },
        title="Live Chat Agent Typing",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    is_typing: str = Field(..., title="Is Typing")
    visitor_id: str = Field(..., title="Visitor ID")
    conversation_id: str = Field(..., title="Conversation ID")


_CONV_V = "2021-04-15"


async def _search_conversation(node, c, token):
    params = {
        "locationId": c.location_id, "contactId": c.contact_id, "assignedTo": c.assigned_to,
        "followers": c.followers, "mentions": c.mentions, "query": c.query, "sort": c.sort,
        "startAfterDate": c.start_after_date, "id": c.id, "limit": _ghl_num(c.limit),
        "lastMessageType": c.last_message_type, "lastMessageAction": c.last_message_action,
        "lastMessageDirection": c.last_message_direction, "status": c.status, "sortBy": c.sort_by,
        "sortScoreProfile": c.sort_score_profile, "scoreProfile": c.score_profile,
        "scoreProfileMin": _ghl_num(c.score_profile_min), "scoreProfileMax": _ghl_num(c.score_profile_max),
        "startDate": _ghl_num(c.start_date), "endDate": _ghl_num(c.end_date),
    }
    return await node._request(token, "GET", "/conversations/search", params=params, version=_CONV_V, action_name="search_conversation")


async def _get_conversation(node, c, token):
    return await node._request(token, "GET", f"/conversations/{c.conversation_id}", version=_CONV_V, action_name="get_conversation")


async def _update_conversation(node, c, token):
    body = {
        "locationId": c.location_id, "unreadCount": _ghl_num(c.unread_count),
        "starred": _ghl_bool(c.starred), "feedback": _ghl_json(c.feedback),
    }
    return await node._request(token, "PUT", f"/conversations/{c.conversation_id}", json_body=body, version=_CONV_V, action_name="update_conversation")


async def _delete_conversation(node, c, token):
    return await node._request(token, "DELETE", f"/conversations/{c.conversation_id}", version=_CONV_V, action_name="delete_conversation")


async def _create_conversation(node, c, token):
    body = {"locationId": c.location_id, "contactId": c.contact_id}
    return await node._request(token, "POST", "/conversations/", json_body=body, version=_CONV_V, action_name="create_conversation")


async def _get_all_custom_subtypes(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", "/conversations/preferences/custom-subtypes", params=params, version=_CONV_V, action_name="get_all_custom_subtypes")


async def _create_custom_subtype(node, c, token):
    params = {"locationId": c.location_id}
    body = {"name": c.name, "description": c.description, "channel": c.channel, "language": c.language}
    return await node._request(token, "POST", "/conversations/preferences/custom-subtypes", params=params, json_body=body, version=_CONV_V, action_name="create_custom_subtype")


async def _update_custom_subtype(node, c, token):
    params = {"locationId": c.location_id}
    body = {
        "name": c.name, "description": c.description, "archived": _ghl_bool(c.archived),
        "resubscription_legal_form_id": c.resubscription_legal_form_id,
    }
    return await node._request(token, "PUT", f"/conversations/preferences/custom-subtypes/{c.id}", params=params, json_body=body, version=_CONV_V, action_name="update_custom_subtype")


async def _get_contact_unsubscription_status(node, c, token):
    params = {"locationId": c.location_id, "contactId": c.contact_id, "email": c.email}
    return await node._request(token, "GET", "/conversations/preferences/unsubscriptions/status", params=params, version=_CONV_V, action_name="get_contact_unsubscription_status")


async def _user_subscription_change(node, c, token):
    body = {
        "locationId": c.location_id, "contactId": c.contact_id, "email": c.email,
        "subscription_action": c.subscription_action, "legal_reason": c.legal_reason,
        "legal_description": c.legal_description,
    }
    return await node._request(token, "POST", "/conversations/preferences/unsubscriptions/user-change", json_body=body, version=_CONV_V, action_name="user_subscription_change")


async def _get_email_by_id(node, c, token):
    return await node._request(token, "GET", f"/conversations/messages/email/{c.id}", version=_CONV_V, action_name="get_email_by_id")


async def _cancel_scheduled_email_message(node, c, token):
    return await node._request(token, "DELETE", f"/conversations/messages/email/{c.email_message_id}/schedule", version=_CONV_V, action_name="cancel_scheduled_email_message")


async def _export_messages_by_location(node, c, token):
    params = {
        "locationId": c.location_id, "limit": _ghl_num(c.limit), "cursor": c.cursor,
        "sortBy": c.sort_by, "sortOrder": c.sort_order, "conversationId": c.conversation_id,
        "contactId": c.contact_id, "channel": c.channel, "startDate": c.start_date, "endDate": c.end_date,
    }
    return await node._request(token, "GET", "/conversations/messages/export", params=params, version=_CONV_V, action_name="export_messages_by_location")


async def _get_message(node, c, token):
    return await node._request(token, "GET", f"/conversations/messages/{c.id}", version=_CONV_V, action_name="get_message")


async def _get_messages(node, c, token):
    params = {"lastMessageId": c.last_message_id, "limit": _ghl_num(c.limit), "type": c.type}
    return await node._request(token, "GET", f"/conversations/{c.conversation_id}/messages", params=params, version=_CONV_V, action_name="get_messages")


async def _send_a_new_message(node, c, token):
    body = {
        "type": c.type, "subType": _ghl_json(c.sub_type), "contactId": c.contact_id,
        "appointmentId": c.appointment_id, "attachments": _ghl_csv(c.attachments),
        "emailFrom": c.email_from, "emailCc": _ghl_csv(c.email_cc), "emailBcc": _ghl_csv(c.email_bcc),
        "html": c.html, "message": c.message, "subject": c.subject, "replyMessageId": c.reply_message_id,
        "templateId": c.template_id, "threadId": c.thread_id,
        "scheduledTimestamp": _ghl_num(c.scheduled_timestamp),
        "conversationProviderId": c.conversation_provider_id, "emailTo": c.email_to,
        "customSubtypeId": c.custom_subtype_id, "emailReplyMode": c.email_reply_mode,
        "fromNumber": c.from_number, "toNumber": c.to_number, "forward": c.forward,
        "status": c.status, "usesNativeSchedulingAi": _ghl_bool(c.uses_native_scheduling_ai),
        "optimizationPeriod": c.optimization_period,
    }
    return await node._request(token, "POST", "/conversations/messages", json_body=body, version=_CONV_V, action_name="send_a_new_message")


async def _add_an_inbound_message(node, c, token):
    body = {
        "type": c.type, "attachments": _ghl_csv(c.attachments), "message": c.message,
        "conversationId": c.conversation_id, "contactId": c.contact_id,
        "conversationProviderId": c.conversation_provider_id, "html": c.html, "subject": c.subject,
        "emailFrom": c.email_from, "emailTo": c.email_to, "emailCc": _ghl_csv(c.email_cc),
        "emailBcc": _ghl_csv(c.email_bcc), "emailMessageId": c.email_message_id, "altId": c.alt_id,
        "direction": _ghl_json(c.direction), "date": c.date, "call": _ghl_json(c.call),
    }
    return await node._request(token, "POST", "/conversations/messages/inbound", json_body=body, version=_CONV_V, action_name="add_an_inbound_message")


async def _add_an_outbound_message(node, c, token):
    body = {
        "type": c.type, "attachments": _ghl_csv(c.attachments), "conversationId": c.conversation_id,
        "conversationProviderId": c.conversation_provider_id, "altId": c.alt_id, "date": c.date,
        "call": _ghl_json(c.call),
    }
    return await node._request(token, "POST", "/conversations/messages/outbound", json_body=body, version=_CONV_V, action_name="add_an_outbound_message")


async def _send_review_reply(node, c, token):
    body = {"conversationId": c.conversation_id, "locationId": c.location_id, "message": c.message}
    return await node._request(token, "POST", "/conversations/messages/review-reply", json_body=body, version=_CONV_V, action_name="send_review_reply")


async def _cancel_scheduled_message(node, c, token):
    return await node._request(token, "DELETE", f"/conversations/messages/{c.message_id}/schedule", version=_CONV_V, action_name="cancel_scheduled_message")


async def _upload_file_attachments(node, c, token):
    # multipart/form-data: attachmentUrls[] plus scalar form fields.
    data = {
        "conversationId": c.conversation_id, "contactId": c.contact_id, "locationId": c.location_id,
        "attachmentUrls": _ghl_csv(c.attachment_urls), "chatServiceSid": c.chat_service_sid,
        "isGroupSms": c.is_group_sms,
    }
    data = {k: v for k, v in data.items() if v is not None}
    return await node._request(token, "POST", "/conversations/messages/upload", data=data, version=_CONV_V, action_name="upload_file_attachments")


async def _initiate_file_upload(node, c, token):
    body = {
        "locationId": c.location_id, "conversationId": c.conversation_id, "filename": c.filename,
        "contentType": c.content_type, "fileSize": _ghl_num(c.file_size), "channel": c.channel,
    }
    return await node._request(token, "POST", "/conversations/messages/upload/initiate", json_body=body, version=_CONV_V, action_name="initiate_file_upload")


async def _complete_file_upload(node, c, token):
    body = {
        "uploadId": c.upload_id, "filePath": c.file_path, "locationId": c.location_id,
        "conversationId": c.conversation_id, "filename": c.filename,
    }
    return await node._request(token, "POST", "/conversations/messages/upload/complete", json_body=body, version=_CONV_V, action_name="complete_file_upload")


async def _update_message_status(node, c, token):
    body = {
        "status": c.status, "error": _ghl_json(c.error), "emailMessageId": c.email_message_id,
        "recipients": _ghl_csv(c.recipients),
    }
    return await node._request(token, "PUT", f"/conversations/messages/{c.message_id}/status", json_body=body, version=_CONV_V, action_name="update_message_status")


async def _add_message_attachments(node, c, token):
    body = {"attachments": _ghl_csv(c.attachments)}
    return await node._request(token, "PUT", f"/conversations/messages/{c.message_id}/attachments", json_body=body, version=_CONV_V, action_name="add_message_attachments")


async def _get_message_recording(node, c, token):
    return await node._request(token, "GET", f"/conversations/messages/{c.message_id}/locations/{c.location_id}/recording", version=_CONV_V, action_name="get_message_recording")


async def _get_message_transcription(node, c, token):
    return await node._request(token, "GET", f"/conversations/locations/{c.location_id}/messages/{c.message_id}/transcription", version=_CONV_V, action_name="get_message_transcription")


async def _download_message_transcription(node, c, token):
    return await node._request(token, "GET", f"/conversations/locations/{c.location_id}/messages/{c.message_id}/transcription/download", version=_CONV_V, action_name="download_message_transcription")


async def _live_chat_agent_typing(node, c, token):
    body = {
        "locationId": c.location_id, "isTyping": c.is_typing, "visitorId": c.visitor_id,
        "conversationId": c.conversation_id,
    }
    return await node._request(token, "POST", "/conversations/providers/live-chat/typing", json_body=body, version=_CONV_V, action_name="live_chat_agent_typing")


GHL_OPERATION_CONFIGS += [
    GHLSearchConversationConfig,
    GHLGetConversationConfig,
    GHLUpdateConversationConfig,
    GHLDeleteConversationConfig,
    GHLCreateConversationConfig,
    GHLGetAllCustomSubtypesConfig,
    GHLCreateCustomSubtypeConfig,
    GHLUpdateCustomSubtypeConfig,
    GHLGetContactUnsubscriptionStatusConfig,
    GHLUserSubscriptionChangeConfig,
    GHLGetEmailByIdConfig,
    GHLCancelScheduledEmailMessageConfig,
    GHLExportMessagesByLocationConfig,
    GHLGetMessageConfig,
    GHLGetMessagesConfig,
    GHLSendANewMessageConfig,
    GHLAddAnInboundMessageConfig,
    GHLAddAnOutboundMessageConfig,
    GHLSendReviewReplyConfig,
    GHLCancelScheduledMessageConfig,
    GHLUploadFileAttachmentsConfig,
    GHLInitiateFileUploadConfig,
    GHLCompleteFileUploadConfig,
    GHLUpdateMessageStatusConfig,
    GHLAddMessageAttachmentsConfig,
    GHLGetMessageRecordingConfig,
    GHLGetMessageTranscriptionConfig,
    GHLDownloadMessageTranscriptionConfig,
    GHLLiveChatAgentTypingConfig,
]
GHL_OPERATION_HANDLERS.update({
    "search_conversation": _search_conversation,
    "get_conversation": _get_conversation,
    "update_conversation": _update_conversation,
    "delete_conversation": _delete_conversation,
    "create_conversation": _create_conversation,
    "get_all_custom_subtypes": _get_all_custom_subtypes,
    "create_custom_subtype": _create_custom_subtype,
    "update_custom_subtype": _update_custom_subtype,
    "get_contact_unsubscription_status": _get_contact_unsubscription_status,
    "user_subscription_change": _user_subscription_change,
    "get_email_by_id": _get_email_by_id,
    "cancel_scheduled_email_message": _cancel_scheduled_email_message,
    "export_messages_by_location": _export_messages_by_location,
    "get_message": _get_message,
    "get_messages": _get_messages,
    "send_a_new_message": _send_a_new_message,
    "add_an_inbound_message": _add_an_inbound_message,
    "add_an_outbound_message": _add_an_outbound_message,
    "send_review_reply": _send_review_reply,
    "cancel_scheduled_message": _cancel_scheduled_message,
    "upload_file_attachments": _upload_file_attachments,
    "initiate_file_upload": _initiate_file_upload,
    "complete_file_upload": _complete_file_upload,
    "update_message_status": _update_message_status,
    "add_message_attachments": _add_message_attachments,
    "get_message_recording": _get_message_recording,
    "get_message_transcription": _get_message_transcription,
    "download_message_transcription": _download_message_transcription,
    "live_chat_agent_typing": _live_chat_agent_typing,
})


# ---- courses.py ----
class GHLImportCoursesConfig(BaseModel):
    """Import courses (products) into a location via the courses exporter."""

    operation: Literal["import_courses"] = Field(
        "import_courses",
        json_schema_extra={
            "const": "import_courses", "ui:hidden": True,
            "x-category": "Courses", "x-is-trigger": False,
            "x-display-name": "Import Courses",
        },
        title="Import Courses",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id to import courses into")
    products: str = Field(..., title="Products", description="JSON array of ProductInterface objects to import")
    user_id: Optional[str] = Field(None, title="User ID", description="User id to attribute the import to")


async def _import_courses(node, c, token):
    body = {
        "locationId": c.location_id,
        "products": _ghl_json(c.products),
        "userId": c.user_id,
    }
    return await node._request(
        token, "POST", "/courses/courses-exporter/public/import",
        json_body=body, action_name="import_courses",
    )


GHL_OPERATION_CONFIGS += [
    GHLImportCoursesConfig,
]
GHL_OPERATION_HANDLERS.update({
    "import_courses": _import_courses,
})


# ---- custom_fields.py ----
class GHLGetCustomFieldByIdConfig(BaseModel):
    """Get a custom field or folder by id."""

    operation: Literal["get_custom_field_by_id"] = Field(
        "get_custom_field_by_id",
        json_schema_extra={
            "const": "get_custom_field_by_id", "ui:hidden": True,
            "x-category": "Custom Fields", "x-is-trigger": False,
            "x-display-name": "Get Custom Field / Folder By ID",
        },
        title="Get Custom Field / Folder By ID",
    )
    id: str = Field(..., title="ID", description="The custom field or folder id")


class GHLUpdateCustomFieldV2Config(BaseModel):
    """Update a custom field by id."""

    operation: Literal["update_custom_field_v2"] = Field(
        "update_custom_field_v2",
        json_schema_extra={
            "const": "update_custom_field_v2", "ui:hidden": True,
            "x-category": "Custom Fields", "x-is-trigger": False,
            "x-display-name": "Update Custom Field",
        },
        title="Update Custom Field",
    )
    id: str = Field(..., title="ID", description="The custom field to update")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    show_in_forms: Optional[str] = Field(
        "true", title="Show In Forms",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    placeholder: Optional[str] = Field(None, title="Placeholder")
    options: Optional[str] = Field(
        None, title="Options", description="JSON array of options for choice-type fields",
    )
    accepted_formats: Optional[str] = Field(
        None, title="Accepted Formats",
        description="Allowed upload formats (for FILE_UPLOAD)",
        json_schema_extra={
            "enum": [
                ".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png",
                ".gif", ".csv", ".xlsx", ".xls", "all",
            ],
            "x-enum-searchable": True,
        },
    )
    max_file_limit: Optional[str] = Field(
        None, title="Max File Limit", description="Maximum number of files (for FILE_UPLOAD)",
    )


class GHLDeleteCustomFieldV2Config(BaseModel):
    """Delete a custom field by id."""

    operation: Literal["delete_custom_field_v2"] = Field(
        "delete_custom_field_v2",
        json_schema_extra={
            "const": "delete_custom_field_v2", "ui:hidden": True,
            "x-category": "Custom Fields", "x-is-trigger": False,
            "x-display-name": "Delete Custom Field",
        },
        title="Delete Custom Field",
    )
    id: str = Field(..., title="ID", description="The custom field to delete")


class GHLGetCustomFieldsByObjectKeyConfig(BaseModel):
    """List custom fields for an object key."""

    operation: Literal["get_custom_fields_by_object_key"] = Field(
        "get_custom_fields_by_object_key",
        json_schema_extra={
            "const": "get_custom_fields_by_object_key", "ui:hidden": True,
            "x-category": "Custom Fields", "x-is-trigger": False,
            "x-display-name": "Get Custom Fields By Object Key",
        },
        title="Get Custom Fields By Object Key",
    )
    object_key: str = Field(..., title="Object Key", description="The object key (e.g. contact, opportunity)")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateCustomFieldFolderConfig(BaseModel):
    """Create a custom field folder."""

    operation: Literal["create_custom_field_folder"] = Field(
        "create_custom_field_folder",
        json_schema_extra={
            "const": "create_custom_field_folder", "ui:hidden": True,
            "x-category": "Custom Fields", "x-is-trigger": False,
            "x-display-name": "Create Custom Field Folder",
        },
        title="Create Custom Field Folder",
    )
    object_key: str = Field(..., title="Object Key", description="The object key the folder belongs to")
    name: str = Field(..., title="Name", description="Folder name")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLUpdateCustomFieldFolderConfig(BaseModel):
    """Update a custom field folder name."""

    operation: Literal["update_custom_field_folder"] = Field(
        "update_custom_field_folder",
        json_schema_extra={
            "const": "update_custom_field_folder", "ui:hidden": True,
            "x-category": "Custom Fields", "x-is-trigger": False,
            "x-display-name": "Update Custom Field Folder",
        },
        title="Update Custom Field Folder",
    )
    id: str = Field(..., title="ID", description="The folder to update")
    name: str = Field(..., title="Name", description="New folder name")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLDeleteCustomFieldFolderConfig(BaseModel):
    """Delete a custom field folder."""

    operation: Literal["delete_custom_field_folder"] = Field(
        "delete_custom_field_folder",
        json_schema_extra={
            "const": "delete_custom_field_folder", "ui:hidden": True,
            "x-category": "Custom Fields", "x-is-trigger": False,
            "x-display-name": "Delete Custom Field Folder",
        },
        title="Delete Custom Field Folder",
    )
    id: str = Field(..., title="ID", description="The folder to delete")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateCustomFieldV2Config(BaseModel):
    """Create a custom field."""

    operation: Literal["create_custom_field_v2"] = Field(
        "create_custom_field_v2",
        json_schema_extra={
            "const": "create_custom_field_v2", "ui:hidden": True,
            "x-category": "Custom Fields", "x-is-trigger": False,
            "x-display-name": "Create Custom Field",
        },
        title="Create Custom Field",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    data_type: str = Field(
        ..., title="Data Type",
        json_schema_extra={
            "enum": [
                "TEXT", "LARGE_TEXT", "NUMERICAL", "PHONE", "MONETORY", "CHECKBOX",
                "SINGLE_OPTIONS", "MULTIPLE_OPTIONS", "DATE", "TEXTBOX_LIST",
                "FILE_UPLOAD", "RADIO", "EMAIL",
            ],
            "x-enum-searchable": True,
        },
    )
    field_key: str = Field(..., title="Field Key", description="Unique field key (e.g. contact.my_field)")
    object_key: str = Field(..., title="Object Key", description="The object key the field belongs to")
    parent_id: str = Field(..., title="Parent ID", description="Parent folder id")
    show_in_forms: Optional[str] = Field(
        "true", title="Show In Forms",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")
    placeholder: Optional[str] = Field(None, title="Placeholder")
    options: Optional[str] = Field(
        None, title="Options", description="JSON array of options for choice-type fields",
    )
    accepted_formats: Optional[str] = Field(
        None, title="Accepted Formats",
        description="Allowed upload formats (for FILE_UPLOAD)",
        json_schema_extra={
            "enum": [
                ".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png",
                ".gif", ".csv", ".xlsx", ".xls", "all",
            ],
            "x-enum-searchable": True,
        },
    )
    max_file_limit: Optional[str] = Field(
        None, title="Max File Limit", description="Maximum number of files (for FILE_UPLOAD)",
    )
    allow_custom_option: Optional[str] = Field(
        None, title="Allow Custom Option",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


async def _get_custom_field_by_id(node, c, token):
    return await node._request(
        token, "GET", f"/custom-fields/{c.id}", action_name="get_custom_field_by_id",
    )


async def _update_custom_field_v2(node, c, token):
    body = {
        "locationId": c.location_id,
        "name": c.name,
        "description": c.description,
        "placeholder": c.placeholder,
        "showInForms": _ghl_bool(c.show_in_forms),
        "options": _ghl_json(c.options),
        "acceptedFormats": c.accepted_formats,
        "maxFileLimit": _ghl_num(c.max_file_limit),
    }
    return await node._request(
        token, "PUT", f"/custom-fields/{c.id}", json_body=body, action_name="update_custom_field_v2",
    )


async def _delete_custom_field_v2(node, c, token):
    return await node._request(
        token, "DELETE", f"/custom-fields/{c.id}", action_name="delete_custom_field_v2",
    )


async def _get_custom_fields_by_object_key(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", f"/custom-fields/object-key/{c.object_key}", params=params,
        action_name="get_custom_fields_by_object_key",
    )


async def _create_custom_field_folder(node, c, token):
    body = {"objectKey": c.object_key, "name": c.name, "locationId": c.location_id}
    return await node._request(
        token, "POST", "/custom-fields/folder", json_body=body,
        action_name="create_custom_field_folder",
    )


async def _update_custom_field_folder(node, c, token):
    body = {"name": c.name, "locationId": c.location_id}
    return await node._request(
        token, "PUT", f"/custom-fields/folder/{c.id}", json_body=body,
        action_name="update_custom_field_folder",
    )


async def _delete_custom_field_folder(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "DELETE", f"/custom-fields/folder/{c.id}", params=params,
        action_name="delete_custom_field_folder",
    )


async def _create_custom_field_v2(node, c, token):
    body = {
        "locationId": c.location_id,
        "dataType": c.data_type,
        "fieldKey": c.field_key,
        "objectKey": c.object_key,
        "parentId": c.parent_id,
        "showInForms": _ghl_bool(c.show_in_forms),
        "name": c.name,
        "description": c.description,
        "placeholder": c.placeholder,
        "options": _ghl_json(c.options),
        "acceptedFormats": c.accepted_formats,
        "maxFileLimit": _ghl_num(c.max_file_limit),
        "allowCustomOption": _ghl_bool(c.allow_custom_option),
    }
    return await node._request(
        token, "POST", "/custom-fields/", json_body=body, action_name="create_custom_field_v2",
    )


GHL_OPERATION_CONFIGS += [
    GHLGetCustomFieldByIdConfig,
    GHLUpdateCustomFieldV2Config,
    GHLDeleteCustomFieldV2Config,
    GHLGetCustomFieldsByObjectKeyConfig,
    GHLCreateCustomFieldFolderConfig,
    GHLUpdateCustomFieldFolderConfig,
    GHLDeleteCustomFieldFolderConfig,
    GHLCreateCustomFieldV2Config,
]
GHL_OPERATION_HANDLERS.update({
    "get_custom_field_by_id": _get_custom_field_by_id,
    "update_custom_field_v2": _update_custom_field_v2,
    "delete_custom_field_v2": _delete_custom_field_v2,
    "get_custom_fields_by_object_key": _get_custom_fields_by_object_key,
    "create_custom_field_folder": _create_custom_field_folder,
    "update_custom_field_folder": _update_custom_field_folder,
    "delete_custom_field_folder": _delete_custom_field_folder,
    "create_custom_field_v2": _create_custom_field_v2,
})


# ---- custom_menus.py ----
class GHLGetCustomMenuByIdConfig(BaseModel):
    """Fetch a single custom menu link by id."""

    operation: Literal["get_custom_menu_by_id"] = Field(
        "get_custom_menu_by_id",
        json_schema_extra={
            "const": "get_custom_menu_by_id", "ui:hidden": True,
            "x-category": "Custom Menus", "x-is-trigger": False,
            "x-display-name": "Get Custom Menu Link",
        },
        title="Get Custom Menu Link",
    )
    custom_menu_id: str = Field(..., title="Custom Menu ID", description="Unique identifier of the custom menu")


class GHLDeleteCustomMenuConfig(BaseModel):
    """Delete a custom menu link."""

    operation: Literal["delete_custom_menu"] = Field(
        "delete_custom_menu",
        json_schema_extra={
            "const": "delete_custom_menu", "ui:hidden": True,
            "x-category": "Custom Menus", "x-is-trigger": False,
            "x-display-name": "Delete Custom Menu Link",
        },
        title="Delete Custom Menu Link",
    )
    custom_menu_id: str = Field(..., title="Custom Menu ID", description="ID of the custom menu to delete")


class GHLUpdateCustomMenuConfig(BaseModel):
    """Update an existing custom menu link."""

    operation: Literal["update_custom_menu"] = Field(
        "update_custom_menu",
        json_schema_extra={
            "const": "update_custom_menu", "ui:hidden": True,
            "x-category": "Custom Menus", "x-is-trigger": False,
            "x-display-name": "Update Custom Menu Link",
        },
        title="Update Custom Menu Link",
    )
    custom_menu_id: str = Field(..., title="Custom Menu ID", description="ID of the custom menu to update")
    title: Optional[str] = Field(None, title="Title", description="Title of the custom menu")
    url: Optional[str] = Field(None, title="URL", description="URL of the custom menu")
    icon: Optional[str] = Field(
        None, title="Icon",
        description='Icon object JSON, e.g. {"name": "yin-yang", "fontFamily": "fab"}',
    )
    show_on_company: Optional[str] = Field(
        None, title="Show On Company",
        description="Whether the menu must be displayed on the agency's level",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    show_on_location: Optional[str] = Field(
        None, title="Show On Location",
        description="Whether the menu must be displayed for sub-accounts level",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    show_to_all_locations: Optional[str] = Field(
        None, title="Show To All Locations",
        description="Whether the menu must be displayed to all sub-accounts",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    open_mode: Optional[str] = Field(
        None, title="Open Mode", description="Mode for opening the menu link",
        json_schema_extra={
            "enum": ["iframe", "new_tab", "current_tab"], "x-enum-searchable": True,
        },
    )
    locations: Optional[str] = Field(
        None, title="Locations",
        description="Comma-separated sub-account IDs where the menu should be shown",
    )
    user_role: Optional[str] = Field(
        None, title="User Role", description="Which user-roles should the menu be accessible to?",
        json_schema_extra={
            "enum": ["all", "admin", "user"], "x-enum-searchable": True,
        },
    )
    allow_camera: Optional[str] = Field(
        None, title="Allow Camera",
        description="Whether to allow camera access (only for iframe mode)",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    allow_microphone: Optional[str] = Field(
        None, title="Allow Microphone",
        description="Whether to allow microphone access (only for iframe mode)",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )


class GHLGetCustomMenusConfig(BaseModel):
    """List custom menu links."""

    operation: Literal["get_custom_menus"] = Field(
        "get_custom_menus",
        json_schema_extra={
            "const": "get_custom_menus", "ui:hidden": True,
            "x-category": "Custom Menus", "x-is-trigger": False,
            "x-display-name": "List Custom Menu Links",
        },
        title="List Custom Menu Links",
    )
    location_id: Optional[str] = Field(None, title="Location ID", description="Unique identifier of the location")
    skip: Optional[str] = Field(None, title="Skip", description="Number of items to skip for pagination")
    limit: Optional[str] = Field(None, title="Limit", description="Maximum number of items to return")
    query: Optional[str] = Field(None, title="Query", description="Search query to filter custom menus by name")
    show_on_company: Optional[str] = Field(
        None, title="Show On Company",
        description="Filter to show only agency-level menu links",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )


class GHLCreateCustomMenuConfig(BaseModel):
    """Create a new custom menu link."""

    operation: Literal["create_custom_menu"] = Field(
        "create_custom_menu",
        json_schema_extra={
            "const": "create_custom_menu", "ui:hidden": True,
            "x-category": "Custom Menus", "x-is-trigger": False,
            "x-display-name": "Create Custom Menu Link",
        },
        title="Create Custom Menu Link",
    )
    title: str = Field(..., title="Title", description="Title of the custom menu")
    url: str = Field(..., title="URL", description="URL of the custom menu")
    icon: str = Field(
        ..., title="Icon",
        description='Icon object JSON, e.g. {"name": "yin-yang", "fontFamily": "fab"}',
    )
    show_on_company: str = Field(
        "true", title="Show On Company",
        description="Whether the menu must be displayed on the agency's level",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    show_on_location: str = Field(
        "true", title="Show On Location",
        description="Whether the menu must be displayed for sub-accounts level",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    show_to_all_locations: str = Field(
        "true", title="Show To All Locations",
        description="Whether the menu must be displayed to all sub-accounts",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    open_mode: str = Field(
        ..., title="Open Mode", description="Mode for opening the menu link",
        json_schema_extra={
            "enum": ["iframe", "new_tab", "current_tab"], "x-enum-searchable": True,
        },
    )
    locations: str = Field(
        ..., title="Locations",
        description="Comma-separated sub-account IDs where the menu should be shown",
    )
    user_role: str = Field(
        ..., title="User Role", description="Which user-roles should the menu be accessible to?",
        json_schema_extra={
            "enum": ["all", "admin", "user"], "x-enum-searchable": True,
        },
    )
    allow_camera: Optional[str] = Field(
        None, title="Allow Camera",
        description="Whether to allow camera access (only for iframe mode)",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    allow_microphone: Optional[str] = Field(
        None, title="Allow Microphone",
        description="Whether to allow microphone access (only for iframe mode)",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )


async def _get_custom_menu_by_id(node, c, token):
    return await node._request(
        token, "GET", f"/custom-menus/{c.custom_menu_id}", action_name="get_custom_menu_by_id",
    )


async def _delete_custom_menu(node, c, token):
    return await node._request(
        token, "DELETE", f"/custom-menus/{c.custom_menu_id}", action_name="delete_custom_menu",
    )


async def _update_custom_menu(node, c, token):
    body = {
        "title": c.title, "url": c.url, "icon": _ghl_json(c.icon),
        "showOnCompany": _ghl_bool(c.show_on_company),
        "showOnLocation": _ghl_bool(c.show_on_location),
        "showToAllLocations": _ghl_bool(c.show_to_all_locations),
        "openMode": c.open_mode, "locations": _ghl_csv(c.locations),
        "userRole": c.user_role,
        "allowCamera": _ghl_bool(c.allow_camera),
        "allowMicrophone": _ghl_bool(c.allow_microphone),
    }
    return await node._request(
        token, "PUT", f"/custom-menus/{c.custom_menu_id}", json_body=body, action_name="update_custom_menu",
    )


async def _get_custom_menus(node, c, token):
    params = {
        "locationId": c.location_id, "skip": _ghl_int(c.skip), "limit": _ghl_int(c.limit),
        "query": c.query, "showOnCompany": _ghl_bool(c.show_on_company),
    }
    return await node._request(token, "GET", "/custom-menus/", params=params, action_name="get_custom_menus")


async def _create_custom_menu(node, c, token):
    body = {
        "title": c.title, "url": c.url, "icon": _ghl_json(c.icon),
        "showOnCompany": _ghl_bool(c.show_on_company),
        "showOnLocation": _ghl_bool(c.show_on_location),
        "showToAllLocations": _ghl_bool(c.show_to_all_locations),
        "openMode": c.open_mode, "locations": _ghl_csv(c.locations),
        "userRole": c.user_role,
        "allowCamera": _ghl_bool(c.allow_camera),
        "allowMicrophone": _ghl_bool(c.allow_microphone),
    }
    return await node._request(token, "POST", "/custom-menus/", json_body=body, action_name="create_custom_menu")


GHL_OPERATION_CONFIGS += [
    GHLGetCustomMenuByIdConfig,
    GHLDeleteCustomMenuConfig,
    GHLUpdateCustomMenuConfig,
    GHLGetCustomMenusConfig,
    GHLCreateCustomMenuConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_custom_menu_by_id": _get_custom_menu_by_id,
    "delete_custom_menu": _delete_custom_menu,
    "update_custom_menu": _update_custom_menu,
    "get_custom_menus": _get_custom_menus,
    "create_custom_menu": _create_custom_menu,
})


# ---- email_isv.py ----
class GHLVerifyEmailConfig(BaseModel):
    """Verify an email address or a contact's email deliverability."""

    operation: Literal["verify_email"] = Field(
        "verify_email",
        json_schema_extra={
            "const": "verify_email", "ui:hidden": True,
            "x-category": "Email Verification", "x-is-trigger": False,
            "x-display-name": "Verify Email",
        },
        title="Verify Email",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    type: str = Field(
        ..., title="Type", description="Email verification type",
        json_schema_extra={
            "enum": ["email", "contact"],
            "enumNames": ["Email", "Contact"],
            "x-enum-searchable": True,
        },
    )
    verify: str = Field(..., title="Verify", description="Email address or contactId to verify")


async def _verify_email(node, c, token):
    params = {"locationId": c.location_id}
    body = {"type": c.type, "verify": c.verify}
    return await node._request(token, "POST", "/email/verify", params=params, json_body=body, action_name="verify_email")


GHL_OPERATION_CONFIGS += [
    GHLVerifyEmailConfig,
]
GHL_OPERATION_HANDLERS.update({
    "verify_email": _verify_email,
})


# ---- emails.py ----
class GHLFetchEmailCampaignsConfig(BaseModel):
    """Get email campaigns/schedules for a location."""

    operation: Literal["fetch_email_campaigns"] = Field(
        "fetch_email_campaigns",
        json_schema_extra={
            "const": "fetch_email_campaigns", "ui:hidden": True,
            "x-category": "Email Builder", "x-is-trigger": False,
            "x-display-name": "Get Email Campaigns",
        },
        title="Get Email Campaigns",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of results to skip (pagination)")
    status: Optional[str] = Field(
        None, title="Status",
        json_schema_extra={
            "enum": ["active", "pause", "complete", "cancelled", "retry", "draft", "resend-scheduled"],
            "x-enum-searchable": True,
        },
    )
    email_status: Optional[str] = Field(
        None, title="Email Status",
        json_schema_extra={
            "enum": [
                "all", "not-started", "paused", "cancelled", "processing", "resumed",
                "next-drip", "complete", "success", "error", "waiting", "queued",
                "queueing", "reading", "scheduled",
            ],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(None, title="Name", description="Filter by campaign name")
    parent_id: Optional[str] = Field(None, title="Parent ID", description="Filter by parent folder id")
    limited_fields: Optional[str] = Field(
        None, title="Limited Fields",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    archived: Optional[str] = Field(
        None, title="Archived",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    campaigns_only: Optional[str] = Field(
        None, title="Campaigns Only",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    show_stats: Optional[str] = Field(
        None, title="Show Stats",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLCreateEmailTemplateConfig(BaseModel):
    """Create a new email template."""

    operation: Literal["create_email_template"] = Field(
        "create_email_template",
        json_schema_extra={
            "const": "create_email_template", "ui:hidden": True,
            "x-category": "Email Builder", "x-is-trigger": False,
            "x-display-name": "Create Email Template",
        },
        title="Create Email Template",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    type: str = Field(
        ..., title="Type",
        json_schema_extra={
            "enum": ["html", "folder", "import", "builder", "blank"],
            "x-enum-searchable": True,
        },
    )
    import_provider: str = Field(
        ..., title="Import Provider",
        description="Provider to import from (required by the API)",
        json_schema_extra={
            "enum": ["mailchimp", "active_campaign", "kajabi"],
            "x-enum-searchable": True,
        },
    )
    title: Optional[str] = Field(None, title="Title")
    updated_by: Optional[str] = Field(None, title="Updated By")
    builder_version: Optional[str] = Field(
        None, title="Builder Version",
        json_schema_extra={"enum": ["1", "2"], "x-enum-searchable": True},
    )
    name: Optional[str] = Field(None, title="Name")
    parent_id: Optional[str] = Field(None, title="Parent ID")
    template_data_url: Optional[str] = Field(None, title="Template Data URL")
    import_url: Optional[str] = Field(None, title="Import URL")
    template_source: Optional[str] = Field(None, title="Template Source")
    is_plain_text: Optional[str] = Field(
        None, title="Is Plain Text",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLFetchEmailTemplatesConfig(BaseModel):
    """Fetch email templates for a location."""

    operation: Literal["fetch_email_templates"] = Field(
        "fetch_email_templates",
        json_schema_extra={
            "const": "fetch_email_templates", "ui:hidden": True,
            "x-category": "Email Builder", "x-is-trigger": False,
            "x-display-name": "Fetch Email Templates",
        },
        title="Fetch Email Templates",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of results to skip (pagination)")
    search: Optional[str] = Field(None, title="Search", description="Search query")
    sort_by_date: Optional[str] = Field(None, title="Sort By Date")
    archived: Optional[str] = Field(None, title="Archived")
    builder_version: Optional[str] = Field(
        None, title="Builder Version",
        json_schema_extra={"enum": ["1", "2"], "x-enum-searchable": True},
    )
    name: Optional[str] = Field(None, title="Name")
    parent_id: Optional[str] = Field(None, title="Parent ID")
    origin_id: Optional[str] = Field(None, title="Origin ID")
    templates_only: Optional[str] = Field(None, title="Templates Only")


class GHLDeleteEmailTemplateConfig(BaseModel):
    """Delete an email template."""

    operation: Literal["delete_email_template"] = Field(
        "delete_email_template",
        json_schema_extra={
            "const": "delete_email_template", "ui:hidden": True,
            "x-category": "Email Builder", "x-is-trigger": False,
            "x-display-name": "Delete Email Template",
        },
        title="Delete Email Template",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    template_id: str = Field(..., title="Template ID", description="The template to delete")


class GHLUpdateEmailTemplateConfig(BaseModel):
    """Update an email template (save builder data)."""

    operation: Literal["update_email_template"] = Field(
        "update_email_template",
        json_schema_extra={
            "const": "update_email_template", "ui:hidden": True,
            "x-category": "Email Builder", "x-is-trigger": False,
            "x-display-name": "Update Email Template",
        },
        title="Update Email Template",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    template_id: str = Field(..., title="Template ID", description="The template to update")
    updated_by: str = Field(..., title="Updated By")
    dnd: str = Field(..., title="DnD JSON", description="Drag-and-drop editor data as a JSON object")
    html: str = Field(..., title="HTML", description="Template HTML content")
    editor_type: str = Field(
        ..., title="Editor Type",
        json_schema_extra={"enum": ["html", "builder"], "x-enum-searchable": True},
    )
    preview_text: Optional[str] = Field(None, title="Preview Text")
    is_plain_text: Optional[str] = Field(
        None, title="Is Plain Text",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _fetch_email_campaigns(node, c, token):
    params = {
        "locationId": c.location_id,
        "limit": _ghl_num(c.limit),
        "offset": _ghl_num(c.offset),
        "status": c.status,
        "emailStatus": c.email_status,
        "name": c.name,
        "parentId": c.parent_id,
        "limitedFields": _ghl_bool(c.limited_fields),
        "archived": _ghl_bool(c.archived),
        "campaignsOnly": _ghl_bool(c.campaigns_only),
        "showStats": _ghl_bool(c.show_stats),
    }
    return await node._request(token, "GET", "/emails/schedule", params=params, action_name="fetch_email_campaigns")


async def _create_email_template(node, c, token):
    body = {
        "locationId": c.location_id,
        "type": c.type,
        "importProvider": c.import_provider,
        "title": c.title,
        "updatedBy": c.updated_by,
        "builderVersion": c.builder_version,
        "name": c.name,
        "parentId": c.parent_id,
        "templateDataUrl": c.template_data_url,
        "importURL": c.import_url,
        "templateSource": c.template_source,
        "isPlainText": _ghl_bool(c.is_plain_text),
    }
    return await node._request(token, "POST", "/emails/builder", json_body=body, action_name="create_email_template")


async def _fetch_email_templates(node, c, token):
    params = {
        "locationId": c.location_id,
        "limit": c.limit,
        "offset": c.offset,
        "search": c.search,
        "sortByDate": c.sort_by_date,
        "archived": c.archived,
        "builderVersion": c.builder_version,
        "name": c.name,
        "parentId": c.parent_id,
        "originId": c.origin_id,
        "templatesOnly": c.templates_only,
    }
    return await node._request(token, "GET", "/emails/builder", params=params, action_name="fetch_email_templates")


async def _delete_email_template(node, c, token):
    return await node._request(
        token, "DELETE", f"/emails/builder/{c.location_id}/{c.template_id}",
        action_name="delete_email_template",
    )


async def _update_email_template(node, c, token):
    body = {
        "locationId": c.location_id,
        "templateId": c.template_id,
        "updatedBy": c.updated_by,
        "dnd": _ghl_json(c.dnd),
        "html": c.html,
        "editorType": c.editor_type,
        "previewText": c.preview_text,
        "isPlainText": _ghl_bool(c.is_plain_text),
    }
    return await node._request(token, "POST", "/emails/builder/data", json_body=body, action_name="update_email_template")


GHL_OPERATION_CONFIGS += [
    GHLFetchEmailCampaignsConfig,
    GHLCreateEmailTemplateConfig,
    GHLFetchEmailTemplatesConfig,
    GHLDeleteEmailTemplateConfig,
    GHLUpdateEmailTemplateConfig,
]
GHL_OPERATION_HANDLERS.update({
    "fetch_email_campaigns": _fetch_email_campaigns,
    "create_email_template": _create_email_template,
    "fetch_email_templates": _fetch_email_templates,
    "delete_email_template": _delete_email_template,
    "update_email_template": _update_email_template,
})


# ---- forms.py ----
class GHLGetFormsSubmissionsConfig(BaseModel):
    """Get form submissions for a location."""

    operation: Literal["get_forms_submissions"] = Field(
        "get_forms_submissions",
        json_schema_extra={
            "const": "get_forms_submissions", "ui:hidden": True,
            "x-category": "Forms", "x-is-trigger": False,
            "x-display-name": "Get Form Submissions",
        },
        title="Get Form Submissions",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    page: Optional[str] = Field(None, title="Page", description="Page number (default 1)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results per page (default 20)")
    form_id: Optional[str] = Field(None, title="Form ID", description="Filter by a specific form id")
    q: Optional[str] = Field(None, title="Query", description="Search query (name, email, etc.)")
    start_at: Optional[str] = Field(None, title="Start At", description="Start date filter (YYYY-MM-DD)")
    end_at: Optional[str] = Field(None, title="End At", description="End date filter (YYYY-MM-DD)")


class GHLUploadToCustomFieldsConfig(BaseModel):
    """Upload files to custom fields on a contact.

    This is a multipart/form-data endpoint. The form fields are dynamic (keyed by
    custom-field id / field key), so files are supplied as a JSON object mapping
    the form field name to a file resource. Provide `files` as JSON where each
    value describes the uploaded file.
    """

    operation: Literal["upload_to_custom_fields"] = Field(
        "upload_to_custom_fields",
        json_schema_extra={
            "const": "upload_to_custom_fields", "ui:hidden": True,
            "x-category": "Forms", "x-is-trigger": False,
            "x-display-name": "Upload Files to Custom Fields",
        },
        title="Upload Files to Custom Fields",
    )
    contact_id: str = Field(..., title="Contact ID", description="Contact to attach files to")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    files: Optional[str] = Field(
        None, title="Files",
        description="JSON object mapping custom-field form key -> file content for the multipart upload",
    )


class GHLGetFormsConfig(BaseModel):
    """Get forms for a location."""

    operation: Literal["get_forms"] = Field(
        "get_forms",
        json_schema_extra={
            "const": "get_forms", "ui:hidden": True,
            "x-category": "Forms", "x-is-trigger": False,
            "x-display-name": "Get Forms",
        },
        title="Get Forms",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return (default 10)")
    type: Optional[str] = Field(None, title="Type", description="Filter by form type")


async def _get_forms_submissions(node, c, token):
    params = {
        "locationId": c.location_id, "page": _ghl_int(c.page), "limit": _ghl_int(c.limit),
        "formId": c.form_id, "q": c.q, "startAt": c.start_at, "endAt": c.end_at,
    }
    return await node._request(token, "GET", "/forms/submissions", params=params, action_name="get_forms_submissions")


async def _upload_to_custom_fields(node, c, token):
    params = {"contactId": c.contact_id, "locationId": c.location_id}
    files = _ghl_json(c.files)
    return await node._request(
        token, "POST", "/forms/upload-custom-files",
        params=params, files=files, action_name="upload_to_custom_fields",
    )


async def _get_forms(node, c, token):
    params = {"locationId": c.location_id, "skip": _ghl_int(c.skip), "limit": _ghl_int(c.limit), "type": c.type}
    return await node._request(token, "GET", "/forms/", params=params, action_name="get_forms")


GHL_OPERATION_CONFIGS += [
    GHLGetFormsSubmissionsConfig,
    GHLUploadToCustomFieldsConfig,
    GHLGetFormsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_forms_submissions": _get_forms_submissions,
    "upload_to_custom_fields": _upload_to_custom_fields,
    "get_forms": _get_forms,
})


# ---- funnels.py ----
class GHLCreateFunnelRedirectConfig(BaseModel):
    """Create a funnel redirect."""

    operation: Literal["create_funnel_redirect"] = Field(
        "create_funnel_redirect",
        json_schema_extra={
            "const": "create_funnel_redirect", "ui:hidden": True,
            "x-category": "Funnels", "x-is-trigger": False,
            "x-display-name": "Create Redirect",
        },
        title="Create Redirect",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    domain: str = Field(..., title="Domain", description="Domain the redirect applies to")
    path: str = Field(..., title="Path", description="Source path to redirect from")
    target: str = Field(..., title="Target", description="Destination the path redirects to")
    action: str = Field(
        ..., title="Action", description="Redirect action type",
        json_schema_extra={
            "enum": ["funnel", "website", "url", "all"],
            "x-enum-searchable": True,
        },
    )


class GHLUpdateFunnelRedirectConfig(BaseModel):
    """Update a funnel redirect by id."""

    operation: Literal["update_funnel_redirect"] = Field(
        "update_funnel_redirect",
        json_schema_extra={
            "const": "update_funnel_redirect", "ui:hidden": True,
            "x-category": "Funnels", "x-is-trigger": False,
            "x-display-name": "Update Redirect",
        },
        title="Update Redirect",
    )
    id: str = Field(..., title="Redirect ID", description="The redirect to update")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    target: str = Field(..., title="Target", description="Destination the path redirects to")
    action: str = Field(
        ..., title="Action", description="Redirect action type",
        json_schema_extra={
            "enum": ["funnel", "website", "url", "all"],
            "x-enum-searchable": True,
        },
    )


class GHLDeleteFunnelRedirectConfig(BaseModel):
    """Delete a funnel redirect by id."""

    operation: Literal["delete_funnel_redirect"] = Field(
        "delete_funnel_redirect",
        json_schema_extra={
            "const": "delete_funnel_redirect", "ui:hidden": True,
            "x-category": "Funnels", "x-is-trigger": False,
            "x-display-name": "Delete Redirect",
        },
        title="Delete Redirect",
    )
    id: str = Field(..., title="Redirect ID", description="The redirect to delete")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLFetchFunnelRedirectsListConfig(BaseModel):
    """Fetch the list of funnel redirects."""

    operation: Literal["fetch_funnel_redirects_list"] = Field(
        "fetch_funnel_redirects_list",
        json_schema_extra={
            "const": "fetch_funnel_redirects_list", "ui:hidden": True,
            "x-category": "Funnels", "x-is-trigger": False,
            "x-display-name": "List Redirects",
        },
        title="List Redirects",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: str = Field(..., title="Limit", description="Max results to return")
    offset: str = Field(..., title="Offset", description="Number of results to skip (pagination)")
    search: Optional[str] = Field(None, title="Search", description="Filter redirects by search text")


class GHLGetFunnelsConfig(BaseModel):
    """Fetch the list of funnels."""

    operation: Literal["get_funnels"] = Field(
        "get_funnels",
        json_schema_extra={
            "const": "get_funnels", "ui:hidden": True,
            "x-category": "Funnels", "x-is-trigger": False,
            "x-display-name": "List Funnels",
        },
        title="List Funnels",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    type: Optional[str] = Field(None, title="Type", description="Filter by funnel type")
    category: Optional[str] = Field(None, title="Category", description="Filter by funnel category")
    offset: Optional[str] = Field(None, title="Offset", description="Number of results to skip (pagination)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    parent_id: Optional[str] = Field(None, title="Parent ID", description="Filter by parent funnel id")
    name: Optional[str] = Field(None, title="Name", description="Filter by funnel name")


class GHLGetFunnelPagesConfig(BaseModel):
    """Fetch the list of funnel pages for a funnel."""

    operation: Literal["get_funnel_pages"] = Field(
        "get_funnel_pages",
        json_schema_extra={
            "const": "get_funnel_pages", "ui:hidden": True,
            "x-category": "Funnels", "x-is-trigger": False,
            "x-display-name": "List Funnel Pages",
        },
        title="List Funnel Pages",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    funnel_id: str = Field(..., title="Funnel ID", description="The funnel to list pages for")
    limit: str = Field(..., title="Limit", description="Max results to return")
    offset: str = Field(..., title="Offset", description="Number of results to skip (pagination)")
    name: Optional[str] = Field(None, title="Name", description="Filter pages by name")


class GHLGetFunnelPagesCountConfig(BaseModel):
    """Fetch the count of funnel pages for a funnel."""

    operation: Literal["get_funnel_pages_count"] = Field(
        "get_funnel_pages_count",
        json_schema_extra={
            "const": "get_funnel_pages_count", "ui:hidden": True,
            "x-category": "Funnels", "x-is-trigger": False,
            "x-display-name": "Count Funnel Pages",
        },
        title="Count Funnel Pages",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    funnel_id: str = Field(..., title="Funnel ID", description="The funnel to count pages for")
    name: Optional[str] = Field(None, title="Name", description="Filter pages by name")


async def _create_funnel_redirect(node, c, token):
    body = {
        "locationId": c.location_id, "domain": c.domain, "path": c.path,
        "target": c.target, "action": c.action,
    }
    return await node._request(token, "POST", "/funnels/lookup/redirect", json_body=body, action_name="create_funnel_redirect")


async def _update_funnel_redirect(node, c, token):
    body = {"target": c.target, "action": c.action, "locationId": c.location_id}
    return await node._request(token, "PATCH", f"/funnels/lookup/redirect/{c.id}", json_body=body, action_name="update_funnel_redirect")


async def _delete_funnel_redirect(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "DELETE", f"/funnels/lookup/redirect/{c.id}", params=params, action_name="delete_funnel_redirect")


async def _fetch_funnel_redirects_list(node, c, token):
    params = {
        "locationId": c.location_id, "limit": c.limit,
        "offset": c.offset, "search": c.search,
    }
    return await node._request(token, "GET", "/funnels/lookup/redirect/list", params=params, action_name="fetch_funnel_redirects_list")


async def _get_funnels(node, c, token):
    params = {
        "locationId": c.location_id, "type": c.type, "category": c.category,
        "offset": c.offset, "limit": c.limit, "parentId": c.parent_id, "name": c.name,
    }
    return await node._request(token, "GET", "/funnels/funnel/list", params=params, action_name="get_funnels")


async def _get_funnel_pages(node, c, token):
    params = {
        "locationId": c.location_id, "funnelId": c.funnel_id,
        "name": c.name, "limit": c.limit, "offset": c.offset,
    }
    return await node._request(token, "GET", "/funnels/page", params=params, action_name="get_funnel_pages")


async def _get_funnel_pages_count(node, c, token):
    params = {"locationId": c.location_id, "funnelId": c.funnel_id, "name": c.name}
    return await node._request(token, "GET", "/funnels/page/count", params=params, action_name="get_funnel_pages_count")


GHL_OPERATION_CONFIGS += [
    GHLCreateFunnelRedirectConfig,
    GHLUpdateFunnelRedirectConfig,
    GHLDeleteFunnelRedirectConfig,
    GHLFetchFunnelRedirectsListConfig,
    GHLGetFunnelsConfig,
    GHLGetFunnelPagesConfig,
    GHLGetFunnelPagesCountConfig,
]
GHL_OPERATION_HANDLERS.update({
    "create_funnel_redirect": _create_funnel_redirect,
    "update_funnel_redirect": _update_funnel_redirect,
    "delete_funnel_redirect": _delete_funnel_redirect,
    "fetch_funnel_redirects_list": _fetch_funnel_redirects_list,
    "get_funnels": _get_funnels,
    "get_funnel_pages": _get_funnel_pages,
    "get_funnel_pages_count": _get_funnel_pages_count,
})


# ---- invoices.py ----
class GHLCreateInvoiceTemplateConfig(BaseModel):
    """Create an invoice template."""

    operation: Literal["create_invoice_template"] = Field(
        "create_invoice_template",
        json_schema_extra={
            "const": "create_invoice_template", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Create Invoice Template",
        },
        title="Create Invoice Template",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    name: str = Field(..., title="Name", description="Name of the template")
    business_details: str = Field(..., title="Business Details (JSON)", description="Business details object as JSON")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)", description="Array of items as JSON")
    internal: Optional[str] = Field(None, title="Internal", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    automatic_taxes_enabled: Optional[str] = Field(None, title="Automatic Taxes Enabled", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    discount: Optional[str] = Field(None, title="Discount (JSON)", description="Discount object as JSON")
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    invoice_title: Optional[str] = Field(None, title="Title", description="Template title")
    tips_configuration: Optional[str] = Field(None, title="Tips Configuration (JSON)")
    late_fees_configuration: Optional[str] = Field(None, title="Late Fees Configuration (JSON)")
    invoice_number_prefix: Optional[str] = Field(None, title="Invoice Number Prefix")
    payment_methods: Optional[str] = Field(None, title="Payment Methods (JSON)")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)", description="Array of attachments as JSON")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")


class GHLListInvoiceTemplatesConfig(BaseModel):
    """List invoice templates."""

    operation: Literal["list_invoice_templates"] = Field(
        "list_invoice_templates",
        json_schema_extra={
            "const": "list_invoice_templates", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "List Invoice Templates",
        },
        title="List Invoice Templates",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    limit: str = Field(..., title="Limit")
    offset: str = Field(..., title="Offset")
    status: Optional[str] = Field(None, title="Status")
    start_at: Optional[str] = Field(None, title="Start At")
    end_at: Optional[str] = Field(None, title="End At")
    search: Optional[str] = Field(None, title="Search")
    payment_mode: Optional[str] = Field(None, title="Payment Mode")


class GHLGetInvoiceTemplateConfig(BaseModel):
    """Get an invoice template by id."""

    operation: Literal["get_invoice_template"] = Field(
        "get_invoice_template",
        json_schema_extra={
            "const": "get_invoice_template", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Get Invoice Template",
        },
        title="Get Invoice Template",
    )
    template_id: str = Field(..., title="Template ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLUpdateInvoiceTemplateConfig(BaseModel):
    """Update an invoice template."""

    operation: Literal["update_invoice_template"] = Field(
        "update_invoice_template",
        json_schema_extra={
            "const": "update_invoice_template", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Invoice Template",
        },
        title="Update Invoice Template",
    )
    template_id: str = Field(..., title="Template ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    name: str = Field(..., title="Name", description="Name of the template")
    business_details: str = Field(..., title="Business Details (JSON)")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)")
    internal: Optional[str] = Field(None, title="Internal", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    discount: Optional[str] = Field(None, title="Discount (JSON)")
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    invoice_title: Optional[str] = Field(None, title="Title", description="Template title")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")


class GHLDeleteInvoiceTemplateConfig(BaseModel):
    """Delete an invoice template."""

    operation: Literal["delete_invoice_template"] = Field(
        "delete_invoice_template",
        json_schema_extra={
            "const": "delete_invoice_template", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Delete Invoice Template",
        },
        title="Delete Invoice Template",
    )
    template_id: str = Field(..., title="Template ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLUpdateInvoiceTemplateLateFeesConfigurationConfig(BaseModel):
    """Update late-fees configuration for an invoice template."""

    operation: Literal["update_invoice_template_late_fees_configuration"] = Field(
        "update_invoice_template_late_fees_configuration",
        json_schema_extra={
            "const": "update_invoice_template_late_fees_configuration", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Template Late Fees Config",
        },
        title="Update Template Late Fees Config",
    )
    template_id: str = Field(..., title="Template ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    late_fees_configuration: str = Field(..., title="Late Fees Configuration (JSON)")


class GHLUpdateInvoicePaymentMethodsConfigurationConfig(BaseModel):
    """Update payment-methods configuration for an invoice template."""

    operation: Literal["update_invoice_payment_methods_configuration"] = Field(
        "update_invoice_payment_methods_configuration",
        json_schema_extra={
            "const": "update_invoice_payment_methods_configuration", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Template Payment Methods Config",
        },
        title="Update Template Payment Methods Config",
    )
    template_id: str = Field(..., title="Template ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    payment_methods: Optional[str] = Field(None, title="Payment Methods (JSON)")


class GHLCreateInvoiceScheduleConfig(BaseModel):
    """Create an invoice schedule (recurring invoice)."""

    operation: Literal["create_invoice_schedule"] = Field(
        "create_invoice_schedule",
        json_schema_extra={
            "const": "create_invoice_schedule", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Create Invoice Schedule",
        },
        title="Create Invoice Schedule",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    name: str = Field(..., title="Name")
    contact_details: str = Field(..., title="Contact Details (JSON)")
    schedule: str = Field(..., title="Schedule (JSON)")
    live_mode: str = Field(..., title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    business_details: str = Field(..., title="Business Details (JSON)")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)")
    discount: str = Field(..., title="Discount (JSON)")
    automatic_taxes_enabled: Optional[str] = Field(None, title="Automatic Taxes Enabled", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    invoice_title: Optional[str] = Field(None, title="Title")
    tips_configuration: Optional[str] = Field(None, title="Tips Configuration (JSON)")
    late_fees_configuration: Optional[str] = Field(None, title="Late Fees Configuration (JSON)")
    invoice_number_prefix: Optional[str] = Field(None, title="Invoice Number Prefix")
    payment_methods: Optional[str] = Field(None, title="Payment Methods (JSON)")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")


class GHLListInvoiceSchedulesConfig(BaseModel):
    """List invoice schedules."""

    operation: Literal["list_invoice_schedules"] = Field(
        "list_invoice_schedules",
        json_schema_extra={
            "const": "list_invoice_schedules", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "List Invoice Schedules",
        },
        title="List Invoice Schedules",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    limit: str = Field(..., title="Limit")
    offset: str = Field(..., title="Offset")
    status: Optional[str] = Field(None, title="Status")
    start_at: Optional[str] = Field(None, title="Start At")
    end_at: Optional[str] = Field(None, title="End At")
    search: Optional[str] = Field(None, title="Search")
    payment_mode: Optional[str] = Field(None, title="Payment Mode")


class GHLGetInvoiceScheduleConfig(BaseModel):
    """Get an invoice schedule by id."""

    operation: Literal["get_invoice_schedule"] = Field(
        "get_invoice_schedule",
        json_schema_extra={
            "const": "get_invoice_schedule", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Get Invoice Schedule",
        },
        title="Get Invoice Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLUpdateInvoiceScheduleConfig(BaseModel):
    """Update an invoice schedule."""

    operation: Literal["update_invoice_schedule"] = Field(
        "update_invoice_schedule",
        json_schema_extra={
            "const": "update_invoice_schedule", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Invoice Schedule",
        },
        title="Update Invoice Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    name: str = Field(..., title="Name")
    contact_details: str = Field(..., title="Contact Details (JSON)")
    schedule: str = Field(..., title="Schedule (JSON)")
    live_mode: str = Field(..., title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    business_details: str = Field(..., title="Business Details (JSON)")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)")
    discount: str = Field(..., title="Discount (JSON)")
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    invoice_title: Optional[str] = Field(None, title="Title")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")


class GHLDeleteInvoiceScheduleConfig(BaseModel):
    """Delete an invoice schedule."""

    operation: Literal["delete_invoice_schedule"] = Field(
        "delete_invoice_schedule",
        json_schema_extra={
            "const": "delete_invoice_schedule", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Delete Invoice Schedule",
        },
        title="Delete Invoice Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLUpdateAndScheduleInvoiceScheduleConfig(BaseModel):
    """Update and schedule an invoice schedule."""

    operation: Literal["update_and_schedule_invoice_schedule"] = Field(
        "update_and_schedule_invoice_schedule",
        json_schema_extra={
            "const": "update_and_schedule_invoice_schedule", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update And Schedule Invoice Schedule",
        },
        title="Update And Schedule Invoice Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID")


class GHLScheduleInvoiceScheduleConfig(BaseModel):
    """Schedule an invoice schedule."""

    operation: Literal["schedule_invoice_schedule"] = Field(
        "schedule_invoice_schedule",
        json_schema_extra={
            "const": "schedule_invoice_schedule", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Schedule Invoice Schedule",
        },
        title="Schedule Invoice Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    live_mode: str = Field(..., title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    auto_payment: Optional[str] = Field(None, title="Auto Payment (JSON)")


class GHLAutoPaymentInvoiceScheduleConfig(BaseModel):
    """Manage auto-payment for an invoice schedule."""

    operation: Literal["auto_payment_invoice_schedule"] = Field(
        "auto_payment_invoice_schedule",
        json_schema_extra={
            "const": "auto_payment_invoice_schedule", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Auto Payment Invoice Schedule",
        },
        title="Auto Payment Invoice Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    id: str = Field(..., title="ID")
    auto_payment: str = Field(..., title="Auto Payment (JSON)")


class GHLCancelInvoiceScheduleConfig(BaseModel):
    """Cancel an invoice schedule."""

    operation: Literal["cancel_invoice_schedule"] = Field(
        "cancel_invoice_schedule",
        json_schema_extra={
            "const": "cancel_invoice_schedule", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Cancel Invoice Schedule",
        },
        title="Cancel Invoice Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLText2PayInvoiceConfig(BaseModel):
    """Create & send a text2pay invoice."""

    operation: Literal["text2pay_invoice"] = Field(
        "text2pay_invoice",
        json_schema_extra={
            "const": "text2pay_invoice", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Text2Pay Invoice",
        },
        title="Text2Pay Invoice",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    name: str = Field(..., title="Name", description="Invoice Name")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)")
    contact_details: str = Field(..., title="Contact Details (JSON)")
    issue_date: str = Field(..., title="Issue Date", description="YYYY-MM-DD")
    sent_to: str = Field(..., title="Sent To (JSON)")
    live_mode: str = Field(..., title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    action: str = Field(..., title="Action", description="create draft or send mode")
    user_id: str = Field(..., title="User ID", description="Id of user generating invoice")
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    invoice_title: Optional[str] = Field(None, title="Title")
    invoice_number: Optional[str] = Field(None, title="Invoice Number")
    due_date: Optional[str] = Field(None, title="Due Date", description="YYYY-MM-DD")
    automatic_taxes_enabled: Optional[str] = Field(None, title="Automatic Taxes Enabled", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    payment_schedule: Optional[str] = Field(None, title="Payment Schedule (JSON)")
    late_fees_configuration: Optional[str] = Field(None, title="Late Fees Configuration (JSON)")
    tips_configuration: Optional[str] = Field(None, title="Tips Configuration (JSON)")
    invoice_number_prefix: Optional[str] = Field(None, title="Invoice Number Prefix")
    payment_methods: Optional[str] = Field(None, title="Payment Methods (JSON)")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")
    id: Optional[str] = Field(None, title="Invoice ID", description="Id of invoice to update; if skipped a new one is created")
    include_terms_note: Optional[str] = Field(None, title="Include Terms Note", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    discount: Optional[str] = Field(None, title="Discount (JSON)")
    business_details: Optional[str] = Field(None, title="Business Details (JSON)")


class GHLGenerateInvoiceNumberConfig(BaseModel):
    """Generate the next invoice number."""

    operation: Literal["generate_invoice_number"] = Field(
        "generate_invoice_number",
        json_schema_extra={
            "const": "generate_invoice_number", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Generate Invoice Number",
        },
        title="Generate Invoice Number",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLGetInvoiceSettingsConfig(BaseModel):
    """Get invoice settings for a location."""

    operation: Literal["get_invoice_settings"] = Field(
        "get_invoice_settings",
        json_schema_extra={
            "const": "get_invoice_settings", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Get Invoice Settings",
        },
        title="Get Invoice Settings",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLGetInvoiceConfig(BaseModel):
    """Get an invoice by id."""

    operation: Literal["get_invoice"] = Field(
        "get_invoice",
        json_schema_extra={
            "const": "get_invoice", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Get Invoice",
        },
        title="Get Invoice",
    )
    invoice_id: str = Field(..., title="Invoice ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLUpdateInvoiceConfig(BaseModel):
    """Update an invoice."""

    operation: Literal["update_invoice"] = Field(
        "update_invoice",
        json_schema_extra={
            "const": "update_invoice", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Invoice",
        },
        title="Update Invoice",
    )
    invoice_id: str = Field(..., title="Invoice ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    name: str = Field(..., title="Name")
    currency: str = Field(..., title="Currency")
    invoice_items: str = Field(..., title="Invoice Items (JSON)")
    issue_date: str = Field(..., title="Issue Date", description="YYYY-MM-DD")
    due_date: str = Field(..., title="Due Date", description="YYYY-MM-DD")
    invoice_title: Optional[str] = Field(None, title="Title")
    description: Optional[str] = Field(None, title="Description")
    business_details: Optional[str] = Field(None, title="Business Details (JSON)")
    invoice_number: Optional[str] = Field(None, title="Invoice Number")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    contact_details: Optional[str] = Field(None, title="Contact Details (JSON)")
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    discount: Optional[str] = Field(None, title="Discount (JSON)")
    automatic_taxes_enabled: Optional[str] = Field(None, title="Automatic Taxes Enabled", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    live_mode: Optional[str] = Field(None, title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    payment_schedule: Optional[str] = Field(None, title="Payment Schedule (JSON)")
    tips_configuration: Optional[str] = Field(None, title="Tips Configuration (JSON)")
    xero_details: Optional[str] = Field(None, title="Xero Details (JSON)")
    invoice_number_prefix: Optional[str] = Field(None, title="Invoice Number Prefix")
    payment_methods: Optional[str] = Field(None, title="Payment Methods (JSON)")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")


class GHLDeleteInvoiceConfig(BaseModel):
    """Delete an invoice."""

    operation: Literal["delete_invoice"] = Field(
        "delete_invoice",
        json_schema_extra={
            "const": "delete_invoice", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Delete Invoice",
        },
        title="Delete Invoice",
    )
    invoice_id: str = Field(..., title="Invoice ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLUpdateInvoiceLateFeesConfigurationConfig(BaseModel):
    """Update late-fees configuration for an invoice."""

    operation: Literal["update_invoice_late_fees_configuration"] = Field(
        "update_invoice_late_fees_configuration",
        json_schema_extra={
            "const": "update_invoice_late_fees_configuration", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Invoice Late Fees Config",
        },
        title="Update Invoice Late Fees Config",
    )
    invoice_id: str = Field(..., title="Invoice ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    late_fees_configuration: str = Field(..., title="Late Fees Configuration (JSON)")


class GHLVoidInvoiceConfig(BaseModel):
    """Void an invoice."""

    operation: Literal["void_invoice"] = Field(
        "void_invoice",
        json_schema_extra={
            "const": "void_invoice", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Void Invoice",
        },
        title="Void Invoice",
    )
    invoice_id: str = Field(..., title="Invoice ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")


class GHLSendInvoiceConfig(BaseModel):
    """Send an invoice."""

    operation: Literal["send_invoice"] = Field(
        "send_invoice",
        json_schema_extra={
            "const": "send_invoice", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Send Invoice",
        },
        title="Send Invoice",
    )
    invoice_id: str = Field(..., title="Invoice ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    user_id: str = Field(..., title="User ID")
    action: str = Field(..., title="Action")
    live_mode: str = Field(..., title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    sent_from: Optional[str] = Field(None, title="Sent From (JSON)")
    auto_payment: Optional[str] = Field(None, title="Auto Payment (JSON)")


class GHLRecordInvoiceConfig(BaseModel):
    """Record a manual payment against an invoice."""

    operation: Literal["record_invoice"] = Field(
        "record_invoice",
        json_schema_extra={
            "const": "record_invoice", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Record Invoice Payment",
        },
        title="Record Invoice Payment",
    )
    invoice_id: str = Field(..., title="Invoice ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    mode: str = Field(..., title="Mode", description="Manual payment method")
    card: str = Field(..., title="Card (JSON)")
    cheque: str = Field(..., title="Cheque (JSON)")
    notes: str = Field(..., title="Notes")
    amount: Optional[str] = Field(None, title="Amount")
    meta: Optional[str] = Field(None, title="Meta (JSON)")
    payment_schedule_ids: Optional[str] = Field(None, title="Payment Schedule IDs", description="Comma-separated list of ids")
    fulfilled_at: Optional[str] = Field(None, title="Fulfilled At")


class GHLUpdateInvoiceLastVisitedAtConfig(BaseModel):
    """Update the last-visited-at stat for an invoice."""

    operation: Literal["update_invoice_last_visited_at"] = Field(
        "update_invoice_last_visited_at",
        json_schema_extra={
            "const": "update_invoice_last_visited_at", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Invoice Last Visited At",
        },
        title="Update Invoice Last Visited At",
    )
    invoice_id: str = Field(..., title="Invoice ID")


class GHLCreateNewEstimateConfig(BaseModel):
    """Create a new estimate."""

    operation: Literal["create_new_estimate"] = Field(
        "create_new_estimate",
        json_schema_extra={
            "const": "create_new_estimate", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Create Estimate",
        },
        title="Create Estimate",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")
    name: str = Field(..., title="Name", description="Estimate Name")
    business_details: str = Field(..., title="Business Details (JSON)")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)")
    discount: str = Field(..., title="Discount (JSON)")
    contact_details: str = Field(..., title="Contact Details (JSON)")
    frequency_settings: str = Field(..., title="Frequency Settings (JSON)")
    live_mode: Optional[str] = Field(None, title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    estimate_title: Optional[str] = Field(None, title="Title")
    estimate_number: Optional[str] = Field(None, title="Estimate Number")
    issue_date: Optional[str] = Field(None, title="Issue Date")
    expiry_date: Optional[str] = Field(None, title="Expiry Date")
    sent_to: Optional[str] = Field(None, title="Sent To (JSON)")
    automatic_taxes_enabled: Optional[str] = Field(None, title="Automatic Taxes Enabled", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    meta: Optional[str] = Field(None, title="Meta (JSON)")
    send_estimate_details: Optional[str] = Field(None, title="Send Estimate Details (JSON)")
    estimate_number_prefix: Optional[str] = Field(None, title="Estimate Number Prefix")
    user_id: Optional[str] = Field(None, title="User ID")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)")
    auto_invoice: Optional[str] = Field(None, title="Auto Invoice (JSON)")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")
    payment_schedule_config: Optional[str] = Field(None, title="Payment Schedule Config (JSON)")


class GHLUpdateEstimateConfig(BaseModel):
    """Update an estimate."""

    operation: Literal["update_estimate"] = Field(
        "update_estimate",
        json_schema_extra={
            "const": "update_estimate", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Estimate",
        },
        title="Update Estimate",
    )
    estimate_id: str = Field(..., title="Estimate ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")
    name: str = Field(..., title="Name", description="Estimate Name")
    business_details: str = Field(..., title="Business Details (JSON)")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)")
    discount: str = Field(..., title="Discount (JSON)")
    contact_details: str = Field(..., title="Contact Details (JSON)")
    frequency_settings: str = Field(..., title="Frequency Settings (JSON)")
    live_mode: Optional[str] = Field(None, title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    estimate_title: Optional[str] = Field(None, title="Title")
    estimate_number: Optional[str] = Field(None, title="Estimate Number")
    issue_date: Optional[str] = Field(None, title="Issue Date")
    expiry_date: Optional[str] = Field(None, title="Expiry Date")
    sent_to: Optional[str] = Field(None, title="Sent To (JSON)")
    automatic_taxes_enabled: Optional[str] = Field(None, title="Automatic Taxes Enabled", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    meta: Optional[str] = Field(None, title="Meta (JSON)")
    send_estimate_details: Optional[str] = Field(None, title="Send Estimate Details (JSON)")
    estimate_number_prefix: Optional[str] = Field(None, title="Estimate Number Prefix")
    user_id: Optional[str] = Field(None, title="User ID")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)")
    auto_invoice: Optional[str] = Field(None, title="Auto Invoice (JSON)")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")
    payment_schedule_config: Optional[str] = Field(None, title="Payment Schedule Config (JSON)")
    estimate_status: Optional[str] = Field(None, title="Estimate Status")


class GHLDeleteEstimateConfig(BaseModel):
    """Delete an estimate."""

    operation: Literal["delete_estimate"] = Field(
        "delete_estimate",
        json_schema_extra={
            "const": "delete_estimate", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Delete Estimate",
        },
        title="Delete Estimate",
    )
    estimate_id: str = Field(..., title="Estimate ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")


class GHLGenerateEstimateNumberConfig(BaseModel):
    """Generate the next estimate number."""

    operation: Literal["generate_estimate_number"] = Field(
        "generate_estimate_number",
        json_schema_extra={
            "const": "generate_estimate_number", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Generate Estimate Number",
        },
        title="Generate Estimate Number",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")


class GHLSendEstimateConfig(BaseModel):
    """Send an estimate."""

    operation: Literal["send_estimate"] = Field(
        "send_estimate",
        json_schema_extra={
            "const": "send_estimate", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Send Estimate",
        },
        title="Send Estimate",
    )
    estimate_id: str = Field(..., title="Estimate ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")
    action: str = Field(..., title="Action")
    live_mode: str = Field(..., title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    user_id: str = Field(..., title="User ID")
    sent_from: Optional[str] = Field(None, title="Sent From (JSON)")
    estimate_name: Optional[str] = Field(None, title="Estimate Name")


class GHLCreateInvoiceFromEstimateConfig(BaseModel):
    """Create an invoice from an estimate."""

    operation: Literal["create_invoice_from_estimate"] = Field(
        "create_invoice_from_estimate",
        json_schema_extra={
            "const": "create_invoice_from_estimate", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Create Invoice From Estimate",
        },
        title="Create Invoice From Estimate",
    )
    estimate_id: str = Field(..., title="Estimate ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")
    mark_as_invoiced: str = Field(..., title="Mark As Invoiced", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    version: Optional[str] = Field(None, title="Version", description="Version of the update request")


class GHLListEstimatesConfig(BaseModel):
    """List estimates."""

    operation: Literal["list_estimates"] = Field(
        "list_estimates",
        json_schema_extra={
            "const": "list_estimates", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "List Estimates",
        },
        title="List Estimates",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")
    limit: str = Field(..., title="Limit")
    offset: str = Field(..., title="Offset")
    start_at: Optional[str] = Field(None, title="Start At")
    end_at: Optional[str] = Field(None, title="End At")
    search: Optional[str] = Field(None, title="Search")
    status: Optional[str] = Field(None, title="Status")
    contact_id: Optional[str] = Field(None, title="Contact ID")


class GHLUpdateEstimateLastVisitedAtConfig(BaseModel):
    """Update the last-visited-at stat for an estimate."""

    operation: Literal["update_estimate_last_visited_at"] = Field(
        "update_estimate_last_visited_at",
        json_schema_extra={
            "const": "update_estimate_last_visited_at", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Estimate Last Visited At",
        },
        title="Update Estimate Last Visited At",
    )
    estimate_id: str = Field(..., title="Estimate ID")


class GHLListEstimateTemplatesConfig(BaseModel):
    """List estimate templates."""

    operation: Literal["list_estimate_templates"] = Field(
        "list_estimate_templates",
        json_schema_extra={
            "const": "list_estimate_templates", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "List Estimate Templates",
        },
        title="List Estimate Templates",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")
    limit: str = Field(..., title="Limit")
    offset: str = Field(..., title="Offset")
    search: Optional[str] = Field(None, title="Search")


class GHLCreateEstimateTemplateConfig(BaseModel):
    """Create an estimate template."""

    operation: Literal["create_estimate_template"] = Field(
        "create_estimate_template",
        json_schema_extra={
            "const": "create_estimate_template", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Create Estimate Template",
        },
        title="Create Estimate Template",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")
    name: str = Field(..., title="Name", description="Estimate Name")
    business_details: str = Field(..., title="Business Details (JSON)")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)")
    discount: str = Field(..., title="Discount (JSON)")
    live_mode: Optional[str] = Field(None, title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    estimate_title: Optional[str] = Field(None, title="Title")
    automatic_taxes_enabled: Optional[str] = Field(None, title="Automatic Taxes Enabled", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    meta: Optional[str] = Field(None, title="Meta (JSON)")
    send_estimate_details: Optional[str] = Field(None, title="Send Estimate Details (JSON)")
    estimate_number_prefix: Optional[str] = Field(None, title="Estimate Number Prefix")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")


class GHLUpdateEstimateTemplateConfig(BaseModel):
    """Update an estimate template."""

    operation: Literal["update_estimate_template"] = Field(
        "update_estimate_template",
        json_schema_extra={
            "const": "update_estimate_template", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Update Estimate Template",
        },
        title="Update Estimate Template",
    )
    template_id: str = Field(..., title="Template ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")
    name: str = Field(..., title="Name", description="Estimate Name")
    business_details: str = Field(..., title="Business Details (JSON)")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)")
    discount: str = Field(..., title="Discount (JSON)")
    live_mode: Optional[str] = Field(None, title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    estimate_title: Optional[str] = Field(None, title="Title")
    automatic_taxes_enabled: Optional[str] = Field(None, title="Automatic Taxes Enabled", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    meta: Optional[str] = Field(None, title="Meta (JSON)")
    send_estimate_details: Optional[str] = Field(None, title="Send Estimate Details (JSON)")
    estimate_number_prefix: Optional[str] = Field(None, title="Estimate Number Prefix")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")


class GHLDeleteEstimateTemplateConfig(BaseModel):
    """Delete an estimate template."""

    operation: Literal["delete_estimate_template"] = Field(
        "delete_estimate_template",
        json_schema_extra={
            "const": "delete_estimate_template", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Delete Estimate Template",
        },
        title="Delete Estimate Template",
    )
    template_id: str = Field(..., title="Template ID")
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")


class GHLPreviewEstimateTemplateConfig(BaseModel):
    """Preview an estimate template."""

    operation: Literal["preview_estimate_template"] = Field(
        "preview_estimate_template",
        json_schema_extra={
            "const": "preview_estimate_template", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Preview Estimate Template",
        },
        title="Preview Estimate Template",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id or Agency Id")
    alt_type: str = Field(..., title="Alt Type")
    template_id: str = Field(..., title="Template ID")


class GHLCreateInvoiceConfig(BaseModel):
    """Create an invoice."""

    operation: Literal["create_invoice"] = Field(
        "create_invoice",
        json_schema_extra={
            "const": "create_invoice", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "Create Invoice",
        },
        title="Create Invoice",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    name: str = Field(..., title="Name", description="Invoice Name")
    business_details: str = Field(..., title="Business Details (JSON)")
    currency: str = Field(..., title="Currency")
    items: str = Field(..., title="Items (JSON)")
    discount: str = Field(..., title="Discount (JSON)")
    contact_details: str = Field(..., title="Contact Details (JSON)")
    issue_date: str = Field(..., title="Issue Date", description="YYYY-MM-DD")
    sent_to: str = Field(..., title="Sent To (JSON)")
    live_mode: str = Field(..., title="Live Mode", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    terms_notes: Optional[str] = Field(None, title="Terms Notes")
    invoice_title: Optional[str] = Field(None, title="Title")
    invoice_number: Optional[str] = Field(None, title="Invoice Number")
    due_date: Optional[str] = Field(None, title="Due Date", description="YYYY-MM-DD")
    automatic_taxes_enabled: Optional[str] = Field(None, title="Automatic Taxes Enabled", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    payment_schedule: Optional[str] = Field(None, title="Payment Schedule (JSON)")
    late_fees_configuration: Optional[str] = Field(None, title="Late Fees Configuration (JSON)")
    tips_configuration: Optional[str] = Field(None, title="Tips Configuration (JSON)")
    invoice_number_prefix: Optional[str] = Field(None, title="Invoice Number Prefix")
    payment_methods: Optional[str] = Field(None, title="Payment Methods (JSON)")
    attachments: Optional[str] = Field(None, title="Attachments (JSON)")
    miscellaneous_charges: Optional[str] = Field(None, title="Miscellaneous Charges (JSON)")


class GHLListInvoicesConfig(BaseModel):
    """List invoices."""

    operation: Literal["list_invoices"] = Field(
        "list_invoices",
        json_schema_extra={
            "const": "list_invoices", "ui:hidden": True,
            "x-category": "Invoices", "x-is-trigger": False,
            "x-display-name": "List Invoices",
        },
        title="List Invoices",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id / Company Id based on altType")
    alt_type: str = Field(..., title="Alt Type", description="e.g. location")
    limit: str = Field(..., title="Limit")
    offset: str = Field(..., title="Offset")
    status: Optional[str] = Field(None, title="Status")
    start_at: Optional[str] = Field(None, title="Start At")
    end_at: Optional[str] = Field(None, title="End At")
    search: Optional[str] = Field(None, title="Search")
    payment_mode: Optional[str] = Field(None, title="Payment Mode")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    sort_field: Optional[str] = Field(None, title="Sort Field")
    sort_order: Optional[str] = Field(None, title="Sort Order")


async def _create_invoice_template(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "businessDetails": _ghl_json(c.business_details), "currency": c.currency,
        "items": _ghl_json(c.items), "internal": _ghl_bool(c.internal),
        "automaticTaxesEnabled": _ghl_bool(c.automatic_taxes_enabled),
        "discount": _ghl_json(c.discount), "termsNotes": c.terms_notes, "title": c.invoice_title,
        "tipsConfiguration": _ghl_json(c.tips_configuration),
        "lateFeesConfiguration": _ghl_json(c.late_fees_configuration),
        "invoiceNumberPrefix": c.invoice_number_prefix,
        "paymentMethods": _ghl_json(c.payment_methods), "attachments": _ghl_json(c.attachments),
        "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
    }
    return await node._request(token, "POST", "/invoices/template", json_body=body, action_name="create_invoice_template")


async def _list_invoice_templates(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "status": c.status, "startAt": c.start_at,
        "endAt": c.end_at, "search": c.search, "paymentMode": c.payment_mode,
        "limit": c.limit, "offset": c.offset,
    }
    return await node._request(token, "GET", "/invoices/template", params=params, action_name="list_invoice_templates")


async def _get_invoice_template(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", f"/invoices/template/{c.template_id}", params=params, action_name="get_invoice_template")


async def _update_invoice_template(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "businessDetails": _ghl_json(c.business_details), "currency": c.currency,
        "items": _ghl_json(c.items), "internal": _ghl_bool(c.internal),
        "discount": _ghl_json(c.discount), "termsNotes": c.terms_notes, "title": c.invoice_title,
        "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
    }
    return await node._request(token, "PUT", f"/invoices/template/{c.template_id}", json_body=body, action_name="update_invoice_template")


async def _delete_invoice_template(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "DELETE", f"/invoices/template/{c.template_id}", params=params, action_name="delete_invoice_template")


async def _update_invoice_template_late_fees_configuration(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type, "lateFeesConfiguration": _ghl_json(c.late_fees_configuration)}
    return await node._request(token, "PATCH", f"/invoices/template/{c.template_id}/late-fees-configuration", json_body=body, action_name="update_invoice_template_late_fees_configuration")


async def _update_invoice_payment_methods_configuration(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type, "paymentMethods": _ghl_json(c.payment_methods)}
    return await node._request(token, "PATCH", f"/invoices/template/{c.template_id}/payment-methods-configuration", json_body=body, action_name="update_invoice_payment_methods_configuration")


async def _create_invoice_schedule(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "contactDetails": _ghl_json(c.contact_details), "schedule": _ghl_json(c.schedule),
        "liveMode": _ghl_bool(c.live_mode), "businessDetails": _ghl_json(c.business_details),
        "currency": c.currency, "items": _ghl_json(c.items),
        "automaticTaxesEnabled": _ghl_bool(c.automatic_taxes_enabled), "discount": _ghl_json(c.discount),
        "termsNotes": c.terms_notes, "title": c.invoice_title,
        "tipsConfiguration": _ghl_json(c.tips_configuration),
        "lateFeesConfiguration": _ghl_json(c.late_fees_configuration),
        "invoiceNumberPrefix": c.invoice_number_prefix, "paymentMethods": _ghl_json(c.payment_methods),
        "attachments": _ghl_json(c.attachments), "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
    }
    return await node._request(token, "POST", "/invoices/schedule", json_body=body, action_name="create_invoice_schedule")


async def _list_invoice_schedules(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "status": c.status, "startAt": c.start_at,
        "endAt": c.end_at, "search": c.search, "paymentMode": c.payment_mode,
        "limit": c.limit, "offset": c.offset,
    }
    return await node._request(token, "GET", "/invoices/schedule", params=params, action_name="list_invoice_schedules")


async def _get_invoice_schedule(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", f"/invoices/schedule/{c.schedule_id}", params=params, action_name="get_invoice_schedule")


async def _update_invoice_schedule(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "contactDetails": _ghl_json(c.contact_details), "schedule": _ghl_json(c.schedule),
        "liveMode": _ghl_bool(c.live_mode), "businessDetails": _ghl_json(c.business_details),
        "currency": c.currency, "items": _ghl_json(c.items), "discount": _ghl_json(c.discount),
        "termsNotes": c.terms_notes, "title": c.invoice_title, "attachments": _ghl_json(c.attachments),
        "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
    }
    return await node._request(token, "PUT", f"/invoices/schedule/{c.schedule_id}", json_body=body, action_name="update_invoice_schedule")


async def _delete_invoice_schedule(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "DELETE", f"/invoices/schedule/{c.schedule_id}", params=params, action_name="delete_invoice_schedule")


async def _update_and_schedule_invoice_schedule(node, c, token):
    return await node._request(token, "POST", f"/invoices/schedule/{c.schedule_id}/updateAndSchedule", action_name="update_and_schedule_invoice_schedule")


async def _schedule_invoice_schedule(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "liveMode": _ghl_bool(c.live_mode),
        "autoPayment": _ghl_json(c.auto_payment),
    }
    return await node._request(token, "POST", f"/invoices/schedule/{c.schedule_id}/schedule", json_body=body, action_name="schedule_invoice_schedule")


async def _auto_payment_invoice_schedule(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "id": c.id,
        "autoPayment": _ghl_json(c.auto_payment),
    }
    return await node._request(token, "POST", f"/invoices/schedule/{c.schedule_id}/auto-payment", json_body=body, action_name="auto_payment_invoice_schedule")


async def _cancel_invoice_schedule(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "POST", f"/invoices/schedule/{c.schedule_id}/cancel", json_body=body, action_name="cancel_invoice_schedule")


async def _text2pay_invoice(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name, "currency": c.currency,
        "items": _ghl_json(c.items), "termsNotes": c.terms_notes, "title": c.invoice_title,
        "contactDetails": _ghl_json(c.contact_details), "invoiceNumber": c.invoice_number,
        "issueDate": c.issue_date, "dueDate": c.due_date, "sentTo": _ghl_json(c.sent_to),
        "liveMode": _ghl_bool(c.live_mode),
        "automaticTaxesEnabled": _ghl_bool(c.automatic_taxes_enabled),
        "paymentSchedule": _ghl_json(c.payment_schedule),
        "lateFeesConfiguration": _ghl_json(c.late_fees_configuration),
        "tipsConfiguration": _ghl_json(c.tips_configuration),
        "invoiceNumberPrefix": c.invoice_number_prefix, "paymentMethods": _ghl_json(c.payment_methods),
        "attachments": _ghl_json(c.attachments), "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
        "id": c.id, "includeTermsNote": _ghl_bool(c.include_terms_note), "action": c.action,
        "userId": c.user_id, "discount": _ghl_json(c.discount), "businessDetails": _ghl_json(c.business_details),
    }
    return await node._request(token, "POST", "/invoices/text2pay", json_body=body, action_name="text2pay_invoice")


async def _generate_invoice_number(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", "/invoices/generate-invoice-number", params=params, action_name="generate_invoice_number")


async def _get_invoice_settings(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", "/invoices/settings", params=params, action_name="get_invoice_settings")


async def _get_invoice(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", f"/invoices/{c.invoice_id}", params=params, action_name="get_invoice")


async def _update_invoice(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name, "title": c.invoice_title,
        "currency": c.currency, "description": c.description,
        "businessDetails": _ghl_json(c.business_details), "invoiceNumber": c.invoice_number,
        "contactId": c.contact_id, "contactDetails": _ghl_json(c.contact_details),
        "termsNotes": c.terms_notes, "discount": _ghl_json(c.discount),
        "invoiceItems": _ghl_json(c.invoice_items),
        "automaticTaxesEnabled": _ghl_bool(c.automatic_taxes_enabled), "liveMode": _ghl_bool(c.live_mode),
        "issueDate": c.issue_date, "dueDate": c.due_date,
        "paymentSchedule": _ghl_json(c.payment_schedule),
        "tipsConfiguration": _ghl_json(c.tips_configuration), "xeroDetails": _ghl_json(c.xero_details),
        "invoiceNumberPrefix": c.invoice_number_prefix, "paymentMethods": _ghl_json(c.payment_methods),
        "attachments": _ghl_json(c.attachments), "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
    }
    return await node._request(token, "PUT", f"/invoices/{c.invoice_id}", json_body=body, action_name="update_invoice")


async def _delete_invoice(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "DELETE", f"/invoices/{c.invoice_id}", params=params, action_name="delete_invoice")


async def _update_invoice_late_fees_configuration(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type, "lateFeesConfiguration": _ghl_json(c.late_fees_configuration)}
    return await node._request(token, "PATCH", f"/invoices/{c.invoice_id}/late-fees-configuration", json_body=body, action_name="update_invoice_late_fees_configuration")


async def _void_invoice(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "POST", f"/invoices/{c.invoice_id}/void", json_body=body, action_name="void_invoice")


async def _send_invoice(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "userId": c.user_id, "action": c.action,
        "liveMode": _ghl_bool(c.live_mode), "sentFrom": _ghl_json(c.sent_from),
        "autoPayment": _ghl_json(c.auto_payment),
    }
    return await node._request(token, "POST", f"/invoices/{c.invoice_id}/send", json_body=body, action_name="send_invoice")


async def _record_invoice(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "mode": c.mode, "card": _ghl_json(c.card),
        "cheque": _ghl_json(c.cheque), "notes": c.notes, "amount": _ghl_num(c.amount),
        "meta": _ghl_json(c.meta), "paymentScheduleIds": _ghl_csv(c.payment_schedule_ids),
        "fulfilledAt": c.fulfilled_at,
    }
    return await node._request(token, "POST", f"/invoices/{c.invoice_id}/record-payment", json_body=body, action_name="record_invoice")


async def _update_invoice_last_visited_at(node, c, token):
    body = {"invoiceId": c.invoice_id}
    return await node._request(token, "PATCH", "/invoices/stats/last-visited-at", json_body=body, action_name="update_invoice_last_visited_at")


async def _create_new_estimate(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "businessDetails": _ghl_json(c.business_details), "currency": c.currency,
        "items": _ghl_json(c.items), "liveMode": _ghl_bool(c.live_mode), "discount": _ghl_json(c.discount),
        "termsNotes": c.terms_notes, "title": c.estimate_title,
        "contactDetails": _ghl_json(c.contact_details), "estimateNumber": _ghl_num(c.estimate_number),
        "issueDate": c.issue_date, "expiryDate": c.expiry_date, "sentTo": _ghl_json(c.sent_to),
        "automaticTaxesEnabled": _ghl_bool(c.automatic_taxes_enabled), "meta": _ghl_json(c.meta),
        "sendEstimateDetails": _ghl_json(c.send_estimate_details),
        "frequencySettings": _ghl_json(c.frequency_settings), "estimateNumberPrefix": c.estimate_number_prefix,
        "userId": c.user_id, "attachments": _ghl_json(c.attachments), "autoInvoice": _ghl_json(c.auto_invoice),
        "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
        "paymentScheduleConfig": _ghl_json(c.payment_schedule_config),
    }
    return await node._request(token, "POST", "/invoices/estimate", json_body=body, action_name="create_new_estimate")


async def _update_estimate(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "businessDetails": _ghl_json(c.business_details), "currency": c.currency,
        "items": _ghl_json(c.items), "liveMode": _ghl_bool(c.live_mode), "discount": _ghl_json(c.discount),
        "termsNotes": c.terms_notes, "title": c.estimate_title,
        "contactDetails": _ghl_json(c.contact_details), "estimateNumber": _ghl_num(c.estimate_number),
        "issueDate": c.issue_date, "expiryDate": c.expiry_date, "sentTo": _ghl_json(c.sent_to),
        "automaticTaxesEnabled": _ghl_bool(c.automatic_taxes_enabled), "meta": _ghl_json(c.meta),
        "sendEstimateDetails": _ghl_json(c.send_estimate_details),
        "frequencySettings": _ghl_json(c.frequency_settings), "estimateNumberPrefix": c.estimate_number_prefix,
        "userId": c.user_id, "attachments": _ghl_json(c.attachments), "autoInvoice": _ghl_json(c.auto_invoice),
        "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
        "paymentScheduleConfig": _ghl_json(c.payment_schedule_config), "estimateStatus": c.estimate_status,
    }
    return await node._request(token, "PUT", f"/invoices/estimate/{c.estimate_id}", json_body=body, action_name="update_estimate")


async def _delete_estimate(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "DELETE", f"/invoices/estimate/{c.estimate_id}", json_body=body, action_name="delete_estimate")


async def _generate_estimate_number(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", "/invoices/estimate/number/generate", params=params, action_name="generate_estimate_number")


async def _send_estimate(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "action": c.action, "liveMode": _ghl_bool(c.live_mode),
        "userId": c.user_id, "sentFrom": _ghl_json(c.sent_from), "estimateName": c.estimate_name,
    }
    return await node._request(token, "POST", f"/invoices/estimate/{c.estimate_id}/send", json_body=body, action_name="send_estimate")


async def _create_invoice_from_estimate(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "markAsInvoiced": _ghl_bool(c.mark_as_invoiced),
        "version": c.version,
    }
    return await node._request(token, "POST", f"/invoices/estimate/{c.estimate_id}/invoice", json_body=body, action_name="create_invoice_from_estimate")


async def _list_estimates(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "startAt": c.start_at, "endAt": c.end_at,
        "search": c.search, "status": c.status, "contactId": c.contact_id,
        "limit": c.limit, "offset": c.offset,
    }
    return await node._request(token, "GET", "/invoices/estimate/list", params=params, action_name="list_estimates")


async def _update_estimate_last_visited_at(node, c, token):
    body = {"estimateId": c.estimate_id}
    return await node._request(token, "PATCH", "/invoices/estimate/stats/last-visited-at", json_body=body, action_name="update_estimate_last_visited_at")


async def _list_estimate_templates(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "search": c.search,
        "limit": c.limit, "offset": c.offset,
    }
    return await node._request(token, "GET", "/invoices/estimate/template", params=params, action_name="list_estimate_templates")


async def _create_estimate_template(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "businessDetails": _ghl_json(c.business_details), "currency": c.currency,
        "items": _ghl_json(c.items), "liveMode": _ghl_bool(c.live_mode), "discount": _ghl_json(c.discount),
        "termsNotes": c.terms_notes, "title": c.estimate_title,
        "automaticTaxesEnabled": _ghl_bool(c.automatic_taxes_enabled), "meta": _ghl_json(c.meta),
        "sendEstimateDetails": _ghl_json(c.send_estimate_details),
        "estimateNumberPrefix": c.estimate_number_prefix, "attachments": _ghl_json(c.attachments),
        "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
    }
    return await node._request(token, "POST", "/invoices/estimate/template", json_body=body, action_name="create_estimate_template")


async def _update_estimate_template(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "businessDetails": _ghl_json(c.business_details), "currency": c.currency,
        "items": _ghl_json(c.items), "liveMode": _ghl_bool(c.live_mode), "discount": _ghl_json(c.discount),
        "termsNotes": c.terms_notes, "title": c.estimate_title,
        "automaticTaxesEnabled": _ghl_bool(c.automatic_taxes_enabled), "meta": _ghl_json(c.meta),
        "sendEstimateDetails": _ghl_json(c.send_estimate_details),
        "estimateNumberPrefix": c.estimate_number_prefix, "attachments": _ghl_json(c.attachments),
        "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
    }
    return await node._request(token, "PUT", f"/invoices/estimate/template/{c.template_id}", json_body=body, action_name="update_estimate_template")


async def _delete_estimate_template(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "DELETE", f"/invoices/estimate/template/{c.template_id}", json_body=body, action_name="delete_estimate_template")


async def _preview_estimate_template(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type, "templateId": c.template_id}
    return await node._request(token, "GET", "/invoices/estimate/template/preview", params=params, action_name="preview_estimate_template")


async def _create_invoice(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "businessDetails": _ghl_json(c.business_details), "currency": c.currency,
        "items": _ghl_json(c.items), "discount": _ghl_json(c.discount), "termsNotes": c.terms_notes,
        "title": c.invoice_title, "contactDetails": _ghl_json(c.contact_details),
        "invoiceNumber": c.invoice_number, "issueDate": c.issue_date, "dueDate": c.due_date,
        "sentTo": _ghl_json(c.sent_to), "liveMode": _ghl_bool(c.live_mode),
        "automaticTaxesEnabled": _ghl_bool(c.automatic_taxes_enabled),
        "paymentSchedule": _ghl_json(c.payment_schedule),
        "lateFeesConfiguration": _ghl_json(c.late_fees_configuration),
        "tipsConfiguration": _ghl_json(c.tips_configuration),
        "invoiceNumberPrefix": c.invoice_number_prefix, "paymentMethods": _ghl_json(c.payment_methods),
        "attachments": _ghl_json(c.attachments), "miscellaneousCharges": _ghl_json(c.miscellaneous_charges),
    }
    return await node._request(token, "POST", "/invoices/", json_body=body, action_name="create_invoice")


async def _list_invoices(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "status": c.status, "startAt": c.start_at,
        "endAt": c.end_at, "search": c.search, "paymentMode": c.payment_mode, "contactId": c.contact_id,
        "limit": c.limit, "offset": c.offset, "sortField": c.sort_field, "sortOrder": c.sort_order,
    }
    return await node._request(token, "GET", "/invoices/", params=params, action_name="list_invoices")


GHL_OPERATION_CONFIGS += [
    GHLCreateInvoiceTemplateConfig,
    GHLListInvoiceTemplatesConfig,
    GHLGetInvoiceTemplateConfig,
    GHLUpdateInvoiceTemplateConfig,
    GHLDeleteInvoiceTemplateConfig,
    GHLUpdateInvoiceTemplateLateFeesConfigurationConfig,
    GHLUpdateInvoicePaymentMethodsConfigurationConfig,
    GHLCreateInvoiceScheduleConfig,
    GHLListInvoiceSchedulesConfig,
    GHLGetInvoiceScheduleConfig,
    GHLUpdateInvoiceScheduleConfig,
    GHLDeleteInvoiceScheduleConfig,
    GHLUpdateAndScheduleInvoiceScheduleConfig,
    GHLScheduleInvoiceScheduleConfig,
    GHLAutoPaymentInvoiceScheduleConfig,
    GHLCancelInvoiceScheduleConfig,
    GHLText2PayInvoiceConfig,
    GHLGenerateInvoiceNumberConfig,
    GHLGetInvoiceSettingsConfig,
    GHLGetInvoiceConfig,
    GHLUpdateInvoiceConfig,
    GHLDeleteInvoiceConfig,
    GHLUpdateInvoiceLateFeesConfigurationConfig,
    GHLVoidInvoiceConfig,
    GHLSendInvoiceConfig,
    GHLRecordInvoiceConfig,
    GHLUpdateInvoiceLastVisitedAtConfig,
    GHLCreateNewEstimateConfig,
    GHLUpdateEstimateConfig,
    GHLDeleteEstimateConfig,
    GHLGenerateEstimateNumberConfig,
    GHLSendEstimateConfig,
    GHLCreateInvoiceFromEstimateConfig,
    GHLListEstimatesConfig,
    GHLUpdateEstimateLastVisitedAtConfig,
    GHLListEstimateTemplatesConfig,
    GHLCreateEstimateTemplateConfig,
    GHLUpdateEstimateTemplateConfig,
    GHLDeleteEstimateTemplateConfig,
    GHLPreviewEstimateTemplateConfig,
    GHLCreateInvoiceConfig,
    GHLListInvoicesConfig,
]
GHL_OPERATION_HANDLERS.update({
    "create_invoice_template": _create_invoice_template,
    "list_invoice_templates": _list_invoice_templates,
    "get_invoice_template": _get_invoice_template,
    "update_invoice_template": _update_invoice_template,
    "delete_invoice_template": _delete_invoice_template,
    "update_invoice_template_late_fees_configuration": _update_invoice_template_late_fees_configuration,
    "update_invoice_payment_methods_configuration": _update_invoice_payment_methods_configuration,
    "create_invoice_schedule": _create_invoice_schedule,
    "list_invoice_schedules": _list_invoice_schedules,
    "get_invoice_schedule": _get_invoice_schedule,
    "update_invoice_schedule": _update_invoice_schedule,
    "delete_invoice_schedule": _delete_invoice_schedule,
    "update_and_schedule_invoice_schedule": _update_and_schedule_invoice_schedule,
    "schedule_invoice_schedule": _schedule_invoice_schedule,
    "auto_payment_invoice_schedule": _auto_payment_invoice_schedule,
    "cancel_invoice_schedule": _cancel_invoice_schedule,
    "text2pay_invoice": _text2pay_invoice,
    "generate_invoice_number": _generate_invoice_number,
    "get_invoice_settings": _get_invoice_settings,
    "get_invoice": _get_invoice,
    "update_invoice": _update_invoice,
    "delete_invoice": _delete_invoice,
    "update_invoice_late_fees_configuration": _update_invoice_late_fees_configuration,
    "void_invoice": _void_invoice,
    "send_invoice": _send_invoice,
    "record_invoice": _record_invoice,
    "update_invoice_last_visited_at": _update_invoice_last_visited_at,
    "create_new_estimate": _create_new_estimate,
    "update_estimate": _update_estimate,
    "delete_estimate": _delete_estimate,
    "generate_estimate_number": _generate_estimate_number,
    "send_estimate": _send_estimate,
    "create_invoice_from_estimate": _create_invoice_from_estimate,
    "list_estimates": _list_estimates,
    "update_estimate_last_visited_at": _update_estimate_last_visited_at,
    "list_estimate_templates": _list_estimate_templates,
    "create_estimate_template": _create_estimate_template,
    "update_estimate_template": _update_estimate_template,
    "delete_estimate_template": _delete_estimate_template,
    "preview_estimate_template": _preview_estimate_template,
    "create_invoice": _create_invoice,
    "list_invoices": _list_invoices,
})


# ---- knowledge_base.py ----
_KB_VERSION = "2021-04-15"


class GHLListKnowledgeBaseFaqsConfig(BaseModel):
    """Get all FAQs by knowledge base with pagination support."""

    operation: Literal["list_knowledge_base_faqs"] = Field(
        "list_knowledge_base_faqs",
        json_schema_extra={
            "const": "list_knowledge_base_faqs", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "List Knowledge Base FAQs",
        },
        title="List Knowledge Base FAQs",
    )
    knowledge_base_id: str = Field(..., title="Knowledge Base ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    last_faq_id: Optional[str] = Field(None, title="Last FAQ ID", description="Cursor for pagination")


class GHLCreateKnowledgeBaseFaqConfig(BaseModel):
    """Create a new FAQ inside knowledge base."""

    operation: Literal["create_knowledge_base_faq"] = Field(
        "create_knowledge_base_faq",
        json_schema_extra={
            "const": "create_knowledge_base_faq", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Create Knowledge Base FAQ",
        },
        title="Create Knowledge Base FAQ",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    question: str = Field(..., title="Question")
    answer: str = Field(..., title="Answer")
    knowledge_base_id: str = Field(..., title="Knowledge Base ID")


class GHLUpdateKnowledgeBaseFaqConfig(BaseModel):
    """Update an existing knowledge base FAQ."""

    operation: Literal["update_knowledge_base_faq"] = Field(
        "update_knowledge_base_faq",
        json_schema_extra={
            "const": "update_knowledge_base_faq", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Update Knowledge Base FAQ",
        },
        title="Update Knowledge Base FAQ",
    )
    id: str = Field(..., title="FAQ ID", description="The FAQ to update")
    question: str = Field(..., title="Question")
    answer: str = Field(..., title="Answer")


class GHLDeleteKnowledgeBaseFaqConfig(BaseModel):
    """Delete an existing knowledge base FAQ."""

    operation: Literal["delete_knowledge_base_faq"] = Field(
        "delete_knowledge_base_faq",
        json_schema_extra={
            "const": "delete_knowledge_base_faq", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Delete Knowledge Base FAQ",
        },
        title="Delete Knowledge Base FAQ",
    )
    id: str = Field(..., title="FAQ ID", description="The FAQ to delete")


class GHLGetAllWebsiteUrlsDataByKnowledgeBaseConfig(BaseModel):
    """Get all trained page links by knowledge base."""

    operation: Literal["get_all_website_urls_data_by_knowledge_base"] = Field(
        "get_all_website_urls_data_by_knowledge_base",
        json_schema_extra={
            "const": "get_all_website_urls_data_by_knowledge_base", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "List Trained Website URLs",
        },
        title="List Trained Website URLs",
    )
    knowledge_base_id: str = Field(..., title="Knowledge Base ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    page: Optional[str] = Field(None, title="Page", description="Page number (pagination)")
    page_length: Optional[str] = Field(None, title="Page Length", description="Results per page")
    query: Optional[str] = Field(None, title="Query", description="Search filter")


class GHLDiscoverWebsiteConfig(BaseModel):
    """Start crawling and discover pages for training."""

    operation: Literal["discover_website"] = Field(
        "discover_website",
        json_schema_extra={
            "const": "discover_website", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Discover Website Pages",
        },
        title="Discover Website Pages",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    url: str = Field(..., title="URL", description="Website URL to crawl")
    option: str = Field(
        ..., title="Crawl Scope",
        json_schema_extra={
            "enum": ["Exact", "Path", "Domain"],
            "x-enum-searchable": True,
        },
    )
    knowledge_base_id: str = Field(..., title="Knowledge Base ID")


class GHLDeleteTrainedUrlsForKnowledgeBaseConfig(BaseModel):
    """Delete trained pages."""

    operation: Literal["delete_trained_urls_for_knowledge_base"] = Field(
        "delete_trained_urls_for_knowledge_base",
        json_schema_extra={
            "const": "delete_trained_urls_for_knowledge_base", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Delete Trained Website URLs",
        },
        title="Delete Trained Website URLs",
    )
    knowledge_base_id: str = Field(..., title="Knowledge Base ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    url_ids: str = Field(
        ..., title="URL IDs",
        description="Comma-separated list of trained URL ids to delete",
    )


class GHLGetCrawlingStatusForLatestOperationConfig(BaseModel):
    """Get crawling status for the latest operation."""

    operation: Literal["get_crawling_status_for_latest_operation"] = Field(
        "get_crawling_status_for_latest_operation",
        json_schema_extra={
            "const": "get_crawling_status_for_latest_operation", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Get Crawling Status",
        },
        title="Get Crawling Status",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    operation_id: str = Field(..., title="Operation ID", description="The crawl operation id")
    knowledge_base_id: str = Field(..., title="Knowledge Base ID")


class GHLTrainDiscoveredUrlsConfig(BaseModel):
    """Train discovered website pages and ingest into the knowledge base."""

    operation: Literal["train_discovered_urls"] = Field(
        "train_discovered_urls",
        json_schema_extra={
            "const": "train_discovered_urls", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Train Discovered URLs",
        },
        title="Train Discovered URLs",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    url_ids: str = Field(
        ..., title="URL IDs",
        description="Comma-separated list of discovered URL ids to train",
    )
    knowledge_base_id: str = Field(..., title="Knowledge Base ID")
    operation_id: str = Field(..., title="Operation ID", description="The discover operation id")


class GHLGetKnowledgeBaseByIdConfig(BaseModel):
    """Get knowledge base by ID."""

    operation: Literal["get_knowledge_base_by_id"] = Field(
        "get_knowledge_base_by_id",
        json_schema_extra={
            "const": "get_knowledge_base_by_id", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Get Knowledge Base",
        },
        title="Get Knowledge Base",
    )
    knowledge_base_id: str = Field(..., title="Knowledge Base ID", description="The knowledge base to fetch")


class GHLDeleteKnowledgeBaseConfig(BaseModel):
    """Delete a knowledge base."""

    operation: Literal["delete_knowledge_base"] = Field(
        "delete_knowledge_base",
        json_schema_extra={
            "const": "delete_knowledge_base", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Delete Knowledge Base",
        },
        title="Delete Knowledge Base",
    )
    knowledge_base_id: str = Field(..., title="Knowledge Base ID", description="The knowledge base to delete")


class GHLUpdateKnowledgeBaseConfig(BaseModel):
    """Update a knowledge base."""

    operation: Literal["update_knowledge_base"] = Field(
        "update_knowledge_base",
        json_schema_extra={
            "const": "update_knowledge_base", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Update Knowledge Base",
        },
        title="Update Knowledge Base",
    )
    id: str = Field(..., title="Knowledge Base ID", description="The knowledge base to update")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(None, title="Description")


class GHLListAllKnowledgeBasesPaginatedConfig(BaseModel):
    """Get all knowledge bases for a location by location Id (paginated)."""

    operation: Literal["list_all_knowledge_bases_paginated"] = Field(
        "list_all_knowledge_bases_paginated",
        json_schema_extra={
            "const": "list_all_knowledge_bases_paginated", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "List Knowledge Bases",
        },
        title="List Knowledge Bases",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    query: Optional[str] = Field(None, title="Query", description="Search filter")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    last_knowledge_base_id: Optional[str] = Field(
        None, title="Last Knowledge Base ID", description="Cursor for pagination",
    )


class GHLCreateKnowledgeBaseConfig(BaseModel):
    """Create a new knowledge base (max 15 knowledge bases per location)."""

    operation: Literal["create_knowledge_base"] = Field(
        "create_knowledge_base",
        json_schema_extra={
            "const": "create_knowledge_base", "ui:hidden": True,
            "x-category": "Knowledge Base", "x-is-trigger": False,
            "x-display-name": "Create Knowledge Base",
        },
        title="Create Knowledge Base",
    )
    name: str = Field(..., title="Name")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    description: Optional[str] = Field(None, title="Description")


async def _list_knowledge_base_faqs(node, c, token):
    params = {
        "knowledgeBaseId": c.knowledge_base_id, "locationId": c.location_id,
        "limit": c.limit, "lastFaqId": c.last_faq_id,
    }
    return await node._request(
        token, "GET", "/knowledge-bases/faqs", params=params,
        version=_KB_VERSION, action_name="list_knowledge_base_faqs",
    )


async def _create_knowledge_base_faq(node, c, token):
    body = {
        "locationId": c.location_id, "question": c.question,
        "answer": c.answer, "knowledgeBaseId": c.knowledge_base_id,
    }
    return await node._request(
        token, "POST", "/knowledge-bases/faqs", json_body=body,
        version=_KB_VERSION, action_name="create_knowledge_base_faq",
    )


async def _update_knowledge_base_faq(node, c, token):
    body = {"question": c.question, "answer": c.answer}
    return await node._request(
        token, "PUT", f"/knowledge-bases/faqs/{c.id}", json_body=body,
        version=_KB_VERSION, action_name="update_knowledge_base_faq",
    )


async def _delete_knowledge_base_faq(node, c, token):
    return await node._request(
        token, "DELETE", f"/knowledge-bases/faqs/{c.id}",
        version=_KB_VERSION, action_name="delete_knowledge_base_faq",
    )


async def _get_all_website_urls_data_by_knowledge_base(node, c, token):
    params = {
        "knowledgeBaseId": c.knowledge_base_id, "locationId": c.location_id,
        "page": _ghl_int(c.page), "pageLength": _ghl_int(c.page_length), "query": c.query,
    }
    return await node._request(
        token, "GET", "/knowledge-bases/crawler", params=params,
        version=_KB_VERSION, action_name="get_all_website_urls_data_by_knowledge_base",
    )


async def _discover_website(node, c, token):
    body = {
        "locationId": c.location_id, "url": c.url,
        "option": c.option, "knowledgeBaseId": c.knowledge_base_id,
    }
    return await node._request(
        token, "POST", "/knowledge-bases/crawler", json_body=body,
        version=_KB_VERSION, action_name="discover_website",
    )


async def _delete_trained_urls_for_knowledge_base(node, c, token):
    body = {
        "knowledgeBaseId": c.knowledge_base_id, "locationId": c.location_id,
        "urlIds": _ghl_csv(c.url_ids),
    }
    return await node._request(
        token, "DELETE", "/knowledge-bases/crawler", json_body=body,
        version=_KB_VERSION, action_name="delete_trained_urls_for_knowledge_base",
    )


async def _get_crawling_status_for_latest_operation(node, c, token):
    params = {
        "locationId": c.location_id, "operationId": c.operation_id,
        "knowledgeBaseId": c.knowledge_base_id,
    }
    return await node._request(
        token, "GET", "/knowledge-bases/crawler/status", params=params,
        version=_KB_VERSION, action_name="get_crawling_status_for_latest_operation",
    )


async def _train_discovered_urls(node, c, token):
    body = {
        "locationId": c.location_id, "urlIds": _ghl_csv(c.url_ids),
        "knowledgeBaseId": c.knowledge_base_id, "operationId": c.operation_id,
    }
    return await node._request(
        token, "POST", "/knowledge-bases/crawler/train", json_body=body,
        version=_KB_VERSION, action_name="train_discovered_urls",
    )


async def _get_knowledge_base_by_id(node, c, token):
    return await node._request(
        token, "GET", f"/knowledge-bases/{c.knowledge_base_id}",
        version=_KB_VERSION, action_name="get_knowledge_base_by_id",
    )


async def _delete_knowledge_base(node, c, token):
    return await node._request(
        token, "DELETE", f"/knowledge-bases/{c.knowledge_base_id}",
        version=_KB_VERSION, action_name="delete_knowledge_base",
    )


async def _update_knowledge_base(node, c, token):
    body = {"name": c.name, "description": c.description}
    return await node._request(
        token, "PUT", f"/knowledge-bases/{c.id}", json_body=body,
        version=_KB_VERSION, action_name="update_knowledge_base",
    )


async def _list_all_knowledge_bases_paginated(node, c, token):
    params = {
        "locationId": c.location_id, "query": c.query,
        "limit": c.limit, "lastKnowledgeBaseId": c.last_knowledge_base_id,
    }
    return await node._request(
        token, "GET", "/knowledge-bases/", params=params,
        version=_KB_VERSION, action_name="list_all_knowledge_bases_paginated",
    )


async def _create_knowledge_base(node, c, token):
    body = {"name": c.name, "description": c.description, "locationId": c.location_id}
    return await node._request(
        token, "POST", "/knowledge-bases/", json_body=body,
        version=_KB_VERSION, action_name="create_knowledge_base",
    )


GHL_OPERATION_CONFIGS += [
    GHLListKnowledgeBaseFaqsConfig,
    GHLCreateKnowledgeBaseFaqConfig,
    GHLUpdateKnowledgeBaseFaqConfig,
    GHLDeleteKnowledgeBaseFaqConfig,
    GHLGetAllWebsiteUrlsDataByKnowledgeBaseConfig,
    GHLDiscoverWebsiteConfig,
    GHLDeleteTrainedUrlsForKnowledgeBaseConfig,
    GHLGetCrawlingStatusForLatestOperationConfig,
    GHLTrainDiscoveredUrlsConfig,
    GHLGetKnowledgeBaseByIdConfig,
    GHLDeleteKnowledgeBaseConfig,
    GHLUpdateKnowledgeBaseConfig,
    GHLListAllKnowledgeBasesPaginatedConfig,
    GHLCreateKnowledgeBaseConfig,
]
GHL_OPERATION_HANDLERS.update({
    "list_knowledge_base_faqs": _list_knowledge_base_faqs,
    "create_knowledge_base_faq": _create_knowledge_base_faq,
    "update_knowledge_base_faq": _update_knowledge_base_faq,
    "delete_knowledge_base_faq": _delete_knowledge_base_faq,
    "get_all_website_urls_data_by_knowledge_base": _get_all_website_urls_data_by_knowledge_base,
    "discover_website": _discover_website,
    "delete_trained_urls_for_knowledge_base": _delete_trained_urls_for_knowledge_base,
    "get_crawling_status_for_latest_operation": _get_crawling_status_for_latest_operation,
    "train_discovered_urls": _train_discovered_urls,
    "get_knowledge_base_by_id": _get_knowledge_base_by_id,
    "delete_knowledge_base": _delete_knowledge_base,
    "update_knowledge_base": _update_knowledge_base,
    "list_all_knowledge_bases_paginated": _list_all_knowledge_bases_paginated,
    "create_knowledge_base": _create_knowledge_base,
})


# ---- links.py ----
class GHLGetLinkByIdConfig(BaseModel):
    """Get a trigger link by id."""

    operation: Literal["get_link_by_id"] = Field(
        "get_link_by_id",
        json_schema_extra={
            "const": "get_link_by_id", "ui:hidden": True,
            "x-category": "Trigger Links", "x-is-trigger": False,
            "x-display-name": "Get Link by ID",
        },
        title="Get Link by ID",
    )
    link_id: str = Field(..., title="Link ID", description="The trigger link to fetch")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLUpdateLinkConfig(BaseModel):
    """Update a trigger link."""

    operation: Literal["update_link"] = Field(
        "update_link",
        json_schema_extra={
            "const": "update_link", "ui:hidden": True,
            "x-category": "Trigger Links", "x-is-trigger": False,
            "x-display-name": "Update Link",
        },
        title="Update Link",
    )
    link_id: str = Field(..., title="Link ID", description="The trigger link to update")
    name: str = Field(..., title="Name", description="Link name")
    redirect_to: str = Field(..., title="Redirect To", description="Destination URL the link redirects to")


class GHLDeleteLinkConfig(BaseModel):
    """Delete a trigger link."""

    operation: Literal["delete_link"] = Field(
        "delete_link",
        json_schema_extra={
            "const": "delete_link", "ui:hidden": True,
            "x-category": "Trigger Links", "x-is-trigger": False,
            "x-display-name": "Delete Link",
        },
        title="Delete Link",
    )
    link_id: str = Field(..., title="Link ID", description="The trigger link to delete")


class GHLSearchTriggerLinksConfig(BaseModel):
    """Search trigger links for a location."""

    operation: Literal["search_trigger_links"] = Field(
        "search_trigger_links",
        json_schema_extra={
            "const": "search_trigger_links", "ui:hidden": True,
            "x-category": "Trigger Links", "x-is-trigger": False,
            "x-display-name": "Search Trigger Links",
        },
        title="Search Trigger Links",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    query: Optional[str] = Field(None, title="Query", description="Search query string")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")


class GHLGetLinksConfig(BaseModel):
    """List trigger links for a location."""

    operation: Literal["get_links"] = Field(
        "get_links",
        json_schema_extra={
            "const": "get_links", "ui:hidden": True,
            "x-category": "Trigger Links", "x-is-trigger": False,
            "x-display-name": "List Links",
        },
        title="List Links",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateLinkConfig(BaseModel):
    """Create a trigger link within a location."""

    operation: Literal["create_link"] = Field(
        "create_link",
        json_schema_extra={
            "const": "create_link", "ui:hidden": True,
            "x-category": "Trigger Links", "x-is-trigger": False,
            "x-display-name": "Create Link",
        },
        title="Create Link",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name", description="Link name")
    redirect_to: str = Field(..., title="Redirect To", description="Destination URL the link redirects to")


async def _get_link_by_id(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", f"/links/id/{c.link_id}", params=params, action_name="get_link_by_id")


async def _update_link(node, c, token):
    body = {"name": c.name, "redirectTo": c.redirect_to}
    return await node._request(token, "PUT", f"/links/{c.link_id}", json_body=body, action_name="update_link")


async def _delete_link(node, c, token):
    return await node._request(token, "DELETE", f"/links/{c.link_id}", action_name="delete_link")


async def _search_trigger_links(node, c, token):
    params = {"locationId": c.location_id, "query": c.query, "skip": c.skip, "limit": c.limit}
    return await node._request(
        token, "GET", "/links/search", params=params,
        version="2021-04-15", action_name="search_trigger_links",
    )


async def _get_links(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", "/links/", params=params, action_name="get_links")


async def _create_link(node, c, token):
    body = {"locationId": c.location_id, "name": c.name, "redirectTo": c.redirect_to}
    return await node._request(token, "POST", "/links/", json_body=body, action_name="create_link")


GHL_OPERATION_CONFIGS += [
    GHLGetLinkByIdConfig,
    GHLUpdateLinkConfig,
    GHLDeleteLinkConfig,
    GHLSearchTriggerLinksConfig,
    GHLGetLinksConfig,
    GHLCreateLinkConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_link_by_id": _get_link_by_id,
    "update_link": _update_link,
    "delete_link": _delete_link,
    "search_trigger_links": _search_trigger_links,
    "get_links": _get_links,
    "create_link": _create_link,
})


# ---- locations.py ----
class GHLSearchLocationsConfig(BaseModel):
    """Search sub-accounts (locations)."""

    operation: Literal["search_locations"] = Field(
        "search_locations",
        json_schema_extra={
            "const": "search_locations", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Search Sub-Accounts",
        },
        title="Search Sub-Accounts",
    )
    company_id: Optional[str] = Field(None, title="Company ID")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    order: Optional[str] = Field(None, title="Order")
    email: Optional[str] = Field(None, title="Email")


class GHLGetLocationConfig(BaseModel):
    """Get a sub-account (location) by id."""

    operation: Literal["get_location"] = Field(
        "get_location",
        json_schema_extra={
            "const": "get_location", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Sub-Account",
        },
        title="Get Sub-Account",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateLocationConfig(BaseModel):
    """Create a sub-account (location)."""

    operation: Literal["create_location"] = Field(
        "create_location",
        json_schema_extra={
            "const": "create_location", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Create Sub-Account",
        },
        title="Create Sub-Account",
    )
    name: str = Field(..., title="Name")
    company_id: str = Field(..., title="Company ID")
    phone: Optional[str] = Field(None, title="Phone")
    address: Optional[str] = Field(None, title="Address")
    city: Optional[str] = Field(None, title="City")
    state: Optional[str] = Field(None, title="State")
    country: Optional[str] = Field(None, title="Country", description="ISO 3166-1 alpha-2 country code")
    postal_code: Optional[str] = Field(None, title="Postal Code")
    website: Optional[str] = Field(None, title="Website")
    timezone: Optional[str] = Field(None, title="Timezone")
    prospect_info: Optional[str] = Field(None, title="Prospect Info (JSON)")
    settings: Optional[str] = Field(None, title="Settings (JSON)")
    social: Optional[str] = Field(None, title="Social (JSON)")
    twilio: Optional[str] = Field(None, title="Twilio (JSON)")
    mailgun: Optional[str] = Field(None, title="Mailgun (JSON)")
    snapshot_id: Optional[str] = Field(None, title="Snapshot ID")


class GHLPutLocationConfig(BaseModel):
    """Update a sub-account (location)."""

    operation: Literal["put_location"] = Field(
        "put_location",
        json_schema_extra={
            "const": "put_location", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Update Sub-Account",
        },
        title="Update Sub-Account",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    company_id: str = Field(..., title="Company ID")
    name: Optional[str] = Field(None, title="Name")
    phone: Optional[str] = Field(None, title="Phone")
    address: Optional[str] = Field(None, title="Address")
    city: Optional[str] = Field(None, title="City")
    state: Optional[str] = Field(None, title="State")
    country: Optional[str] = Field(None, title="Country", description="ISO 3166-1 alpha-2 country code")
    postal_code: Optional[str] = Field(None, title="Postal Code")
    website: Optional[str] = Field(None, title="Website")
    timezone: Optional[str] = Field(None, title="Timezone")
    prospect_info: Optional[str] = Field(None, title="Prospect Info (JSON)")
    settings: Optional[str] = Field(None, title="Settings (JSON)")
    social: Optional[str] = Field(None, title="Social (JSON)")
    twilio: Optional[str] = Field(None, title="Twilio (JSON)")
    mailgun: Optional[str] = Field(None, title="Mailgun (JSON)")
    snapshot: Optional[str] = Field(None, title="Snapshot (JSON)")


class GHLDeleteLocationConfig(BaseModel):
    """Delete a sub-account (location)."""

    operation: Literal["delete_location"] = Field(
        "delete_location",
        json_schema_extra={
            "const": "delete_location", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Delete Sub-Account",
        },
        title="Delete Sub-Account",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    delete_twilio_account: str = Field(
        ..., title="Delete Twilio Account",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLGetLocationTagsConfig(BaseModel):
    """Get tags for a sub-account (location)."""

    operation: Literal["get_location_tags"] = Field(
        "get_location_tags",
        json_schema_extra={
            "const": "get_location_tags", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Location Tags",
        },
        title="Get Location Tags",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateLocationTagConfig(BaseModel):
    """Create a tag in a sub-account (location)."""

    operation: Literal["create_location_tag"] = Field(
        "create_location_tag",
        json_schema_extra={
            "const": "create_location_tag", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Create Location Tag",
        },
        title="Create Location Tag",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name", description="Tag name")


class GHLGetLocationTagByIdConfig(BaseModel):
    """Get a location tag by id."""

    operation: Literal["get_location_tag_by_id"] = Field(
        "get_location_tag_by_id",
        json_schema_extra={
            "const": "get_location_tag_by_id", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Location Tag By ID",
        },
        title="Get Location Tag By ID",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    tag_id: str = Field(..., title="Tag ID")


class GHLUpdateLocationTagConfig(BaseModel):
    """Update a location tag."""

    operation: Literal["update_location_tag"] = Field(
        "update_location_tag",
        json_schema_extra={
            "const": "update_location_tag", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Update Location Tag",
        },
        title="Update Location Tag",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    tag_id: str = Field(..., title="Tag ID")
    name: str = Field(..., title="Name", description="Tag name")


class GHLDeleteLocationTagConfig(BaseModel):
    """Delete a location tag."""

    operation: Literal["delete_location_tag"] = Field(
        "delete_location_tag",
        json_schema_extra={
            "const": "delete_location_tag", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Delete Location Tag",
        },
        title="Delete Location Tag",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    tag_id: str = Field(..., title="Tag ID")


class GHLLocationTaskSearchConfig(BaseModel):
    """Search tasks within a sub-account (location)."""

    operation: Literal["location_task_search"] = Field(
        "location_task_search",
        json_schema_extra={
            "const": "location_task_search", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Search Location Tasks",
        },
        title="Search Location Tasks",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    contact_id: Optional[str] = Field(None, title="Contact IDs (JSON array)")
    completed: Optional[str] = Field(
        None, title="Completed",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    assigned_to: Optional[str] = Field(None, title="Assigned To (JSON array)")
    query: Optional[str] = Field(None, title="Query")
    limit: Optional[str] = Field(None, title="Limit")
    skip: Optional[str] = Field(None, title="Skip")
    business_id: Optional[str] = Field(None, title="Business ID")


class GHLCreateRecurringTaskConfig(BaseModel):
    """Create a recurring task within a sub-account (location)."""

    operation: Literal["create_recurring_task"] = Field(
        "create_recurring_task",
        json_schema_extra={
            "const": "create_recurring_task", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Create Recurring Task",
        },
        title="Create Recurring Task",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    title: str = Field(..., title="Title")
    rrule_options: str = Field(..., title="Recurrence Options (JSON)", description="rruleOptions object")
    description: Optional[str] = Field(None, title="Description")
    contact_ids: Optional[str] = Field(None, title="Contact IDs (JSON array)")
    owners: Optional[str] = Field(None, title="Owners (JSON array)")
    ignore_task_creation: Optional[str] = Field(
        None, title="Ignore Task Creation",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLGetRecurringTaskByIdConfig(BaseModel):
    """Get a recurring task by id."""

    operation: Literal["get_recurring_task_by_id"] = Field(
        "get_recurring_task_by_id",
        json_schema_extra={
            "const": "get_recurring_task_by_id", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Recurring Task By ID",
        },
        title="Get Recurring Task By ID",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Recurring Task ID")


class GHLUpdateRecurringTaskConfig(BaseModel):
    """Update a recurring task."""

    operation: Literal["update_recurring_task"] = Field(
        "update_recurring_task",
        json_schema_extra={
            "const": "update_recurring_task", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Update Recurring Task",
        },
        title="Update Recurring Task",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Recurring Task ID")
    title: Optional[str] = Field(None, title="Title")
    description: Optional[str] = Field(None, title="Description")
    contact_ids: Optional[str] = Field(None, title="Contact IDs (JSON array)")
    owners: Optional[str] = Field(None, title="Owners (JSON array)")
    rrule_options: Optional[str] = Field(None, title="Recurrence Options (JSON)", description="rruleOptions object")
    ignore_task_creation: Optional[str] = Field(
        None, title="Ignore Task Creation",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLDeleteRecurringTaskConfig(BaseModel):
    """Delete a recurring task."""

    operation: Literal["delete_recurring_task"] = Field(
        "delete_recurring_task",
        json_schema_extra={
            "const": "delete_recurring_task", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Delete Recurring Task",
        },
        title="Delete Recurring Task",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Recurring Task ID")


class GHLGetCustomFieldsConfig(BaseModel):
    """Get custom fields for a sub-account (location)."""

    operation: Literal["get_custom_fields"] = Field(
        "get_custom_fields",
        json_schema_extra={
            "const": "get_custom_fields", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Custom Fields",
        },
        title="Get Custom Fields",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    model: Optional[str] = Field(None, title="Model")


class GHLCreateCustomFieldConfig(BaseModel):
    """Create a custom field in a sub-account (location)."""

    operation: Literal["create_custom_field"] = Field(
        "create_custom_field",
        json_schema_extra={
            "const": "create_custom_field", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Create Custom Field",
        },
        title="Create Custom Field",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name")
    data_type: str = Field(..., title="Data Type")
    placeholder: Optional[str] = Field(None, title="Placeholder")
    accepted_format: Optional[str] = Field(None, title="Accepted Format (comma-separated)")
    is_multiple_file: Optional[str] = Field(
        None, title="Is Multiple File",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    max_number_of_files: Optional[str] = Field(None, title="Max Number Of Files")
    text_box_list_options: Optional[str] = Field(None, title="Text Box List Options (JSON array)")
    position: Optional[str] = Field(None, title="Position")
    model: Optional[str] = Field(
        None, title="Model",
        json_schema_extra={
            "enum": ["contact", "opportunity"],
            "x-enum-searchable": True,
        },
    )


class GHLGetCustomFieldConfig(BaseModel):
    """Get a custom field by id."""

    operation: Literal["get_custom_field"] = Field(
        "get_custom_field",
        json_schema_extra={
            "const": "get_custom_field", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Custom Field",
        },
        title="Get Custom Field",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Custom Field ID")


class GHLUpdateCustomFieldConfig(BaseModel):
    """Update a custom field."""

    operation: Literal["update_custom_field"] = Field(
        "update_custom_field",
        json_schema_extra={
            "const": "update_custom_field", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Update Custom Field",
        },
        title="Update Custom Field",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Custom Field ID")
    name: str = Field(..., title="Name")
    placeholder: Optional[str] = Field(None, title="Placeholder")
    accepted_format: Optional[str] = Field(None, title="Accepted Format (comma-separated)")
    is_multiple_file: Optional[str] = Field(
        None, title="Is Multiple File",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    max_number_of_files: Optional[str] = Field(None, title="Max Number Of Files")
    text_box_list_options: Optional[str] = Field(None, title="Text Box List Options (JSON array)")
    position: Optional[str] = Field(None, title="Position")
    model: Optional[str] = Field(
        None, title="Model",
        json_schema_extra={
            "enum": ["contact", "opportunity"],
            "x-enum-searchable": True,
        },
    )


class GHLDeleteCustomFieldConfig(BaseModel):
    """Delete a custom field."""

    operation: Literal["delete_custom_field"] = Field(
        "delete_custom_field",
        json_schema_extra={
            "const": "delete_custom_field", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Delete Custom Field",
        },
        title="Delete Custom Field",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Custom Field ID")


class GHLUploadCustomFieldsFileConfig(BaseModel):
    """Upload a file to custom fields (multipart/form-data)."""

    operation: Literal["upload_custom_fields_file"] = Field(
        "upload_custom_fields_file",
        json_schema_extra={
            "const": "upload_custom_fields_file", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Upload Custom Fields File",
        },
        title="Upload Custom Fields File",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: Optional[str] = Field(None, title="ID", description="Associated custom field/contact id")
    max_files: Optional[str] = Field(None, title="Max Files")
    # File upload endpoint: model documented form fields only; binary file uploads
    # are not trivially expressible as a single config field.


class GHLGetCustomValuesConfig(BaseModel):
    """Get custom values for a sub-account (location)."""

    operation: Literal["get_custom_values"] = Field(
        "get_custom_values",
        json_schema_extra={
            "const": "get_custom_values", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Custom Values",
        },
        title="Get Custom Values",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateCustomValueConfig(BaseModel):
    """Create a custom value in a sub-account (location)."""

    operation: Literal["create_custom_value"] = Field(
        "create_custom_value",
        json_schema_extra={
            "const": "create_custom_value", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Create Custom Value",
        },
        title="Create Custom Value",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name")
    value: str = Field(..., title="Value")


class GHLGetCustomValueConfig(BaseModel):
    """Get a custom value by id."""

    operation: Literal["get_custom_value"] = Field(
        "get_custom_value",
        json_schema_extra={
            "const": "get_custom_value", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Custom Value",
        },
        title="Get Custom Value",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Custom Value ID")


class GHLUpdateCustomValueConfig(BaseModel):
    """Update a custom value."""

    operation: Literal["update_custom_value"] = Field(
        "update_custom_value",
        json_schema_extra={
            "const": "update_custom_value", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Update Custom Value",
        },
        title="Update Custom Value",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Custom Value ID")
    name: str = Field(..., title="Name")
    value: str = Field(..., title="Value")


class GHLDeleteCustomValueConfig(BaseModel):
    """Delete a custom value."""

    operation: Literal["delete_custom_value"] = Field(
        "delete_custom_value",
        json_schema_extra={
            "const": "delete_custom_value", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Delete Custom Value",
        },
        title="Delete Custom Value",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Custom Value ID")


class GHLGetLocationTimezonesConfig(BaseModel):
    """Fetch available timezones for a sub-account (location)."""

    operation: Literal["get_location_timezones"] = Field(
        "get_location_timezones",
        json_schema_extra={
            "const": "get_location_timezones", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Timezones",
        },
        title="Get Timezones",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLGetLocationTemplatesConfig(BaseModel):
    """Get all or email/SMS templates for a sub-account (location)."""

    operation: Literal["get_location_templates"] = Field(
        "get_location_templates",
        json_schema_extra={
            "const": "get_location_templates", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Get Templates",
        },
        title="Get Templates",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    origin_id: str = Field(..., title="Origin ID")
    deleted: Optional[str] = Field(
        None, title="Deleted",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    skip: Optional[str] = Field(None, title="Skip")
    limit: Optional[str] = Field(None, title="Limit")
    type: Optional[str] = Field(None, title="Type")


class GHLDeleteLocationTemplateConfig(BaseModel):
    """Delete an email/SMS template."""

    operation: Literal["delete_location_template"] = Field(
        "delete_location_template",
        json_schema_extra={
            "const": "delete_location_template", "ui:hidden": True,
            "x-category": "Locations", "x-is-trigger": False,
            "x-display-name": "Delete Template",
        },
        title="Delete Template",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Template ID")


async def _search_locations(node, c, token):
    params = {
        "companyId": c.company_id, "skip": c.skip, "limit": c.limit,
        "order": c.order, "email": c.email,
    }
    return await node._request(token, "GET", "/locations/search", params=params, action_name="search_locations")


async def _get_location(node, c, token):
    return await node._request(token, "GET", f"/locations/{c.location_id}", action_name="get_location")


async def _create_location(node, c, token):
    body = {
        "name": c.name, "companyId": c.company_id, "phone": c.phone, "address": c.address,
        "city": c.city, "state": c.state, "country": c.country, "postalCode": c.postal_code,
        "website": c.website, "timezone": c.timezone,
        "prospectInfo": _ghl_json(c.prospect_info), "settings": _ghl_json(c.settings),
        "social": _ghl_json(c.social), "twilio": _ghl_json(c.twilio),
        "mailgun": _ghl_json(c.mailgun), "snapshotId": c.snapshot_id,
    }
    return await node._request(token, "POST", "/locations/", json_body=body, action_name="create_location")


async def _put_location(node, c, token):
    body = {
        "companyId": c.company_id, "name": c.name, "phone": c.phone, "address": c.address,
        "city": c.city, "state": c.state, "country": c.country, "postalCode": c.postal_code,
        "website": c.website, "timezone": c.timezone,
        "prospectInfo": _ghl_json(c.prospect_info), "settings": _ghl_json(c.settings),
        "social": _ghl_json(c.social), "twilio": _ghl_json(c.twilio),
        "mailgun": _ghl_json(c.mailgun), "snapshot": _ghl_json(c.snapshot),
    }
    return await node._request(token, "PUT", f"/locations/{c.location_id}", json_body=body, action_name="put_location")


async def _delete_location(node, c, token):
    params = {"deleteTwilioAccount": _ghl_bool(c.delete_twilio_account)}
    return await node._request(token, "DELETE", f"/locations/{c.location_id}", params=params, action_name="delete_location")


async def _get_location_tags(node, c, token):
    return await node._request(token, "GET", f"/locations/{c.location_id}/tags", action_name="get_location_tags")


async def _create_location_tag(node, c, token):
    body = {"name": c.name}
    return await node._request(token, "POST", f"/locations/{c.location_id}/tags", json_body=body, action_name="create_location_tag")


async def _get_location_tag_by_id(node, c, token):
    return await node._request(token, "GET", f"/locations/{c.location_id}/tags/{c.tag_id}", action_name="get_location_tag_by_id")


async def _update_location_tag(node, c, token):
    body = {"name": c.name}
    return await node._request(token, "PUT", f"/locations/{c.location_id}/tags/{c.tag_id}", json_body=body, action_name="update_location_tag")


async def _delete_location_tag(node, c, token):
    return await node._request(token, "DELETE", f"/locations/{c.location_id}/tags/{c.tag_id}", action_name="delete_location_tag")


async def _location_task_search(node, c, token):
    body = {
        "contactId": _ghl_json(c.contact_id), "completed": _ghl_bool(c.completed),
        "assignedTo": _ghl_json(c.assigned_to), "query": c.query,
        "limit": _ghl_num(c.limit), "skip": _ghl_num(c.skip), "businessId": c.business_id,
    }
    return await node._request(token, "POST", f"/locations/{c.location_id}/tasks/search", json_body=body, action_name="location_task_search")


async def _create_recurring_task(node, c, token):
    body = {
        "title": c.title, "rruleOptions": _ghl_json(c.rrule_options),
        "description": c.description, "contactIds": _ghl_json(c.contact_ids),
        "owners": _ghl_json(c.owners), "ignoreTaskCreation": _ghl_bool(c.ignore_task_creation),
    }
    return await node._request(token, "POST", f"/locations/{c.location_id}/recurring-tasks", json_body=body, action_name="create_recurring_task")


async def _get_recurring_task_by_id(node, c, token):
    return await node._request(token, "GET", f"/locations/{c.location_id}/recurring-tasks/{c.id}", action_name="get_recurring_task_by_id")


async def _update_recurring_task(node, c, token):
    body = {
        "title": c.title, "description": c.description,
        "contactIds": _ghl_json(c.contact_ids), "owners": _ghl_json(c.owners),
        "rruleOptions": _ghl_json(c.rrule_options), "ignoreTaskCreation": _ghl_bool(c.ignore_task_creation),
    }
    return await node._request(token, "PUT", f"/locations/{c.location_id}/recurring-tasks/{c.id}", json_body=body, action_name="update_recurring_task")


async def _delete_recurring_task(node, c, token):
    return await node._request(token, "DELETE", f"/locations/{c.location_id}/recurring-tasks/{c.id}", action_name="delete_recurring_task")


async def _get_custom_fields(node, c, token):
    params = {"model": c.model}
    return await node._request(token, "GET", f"/locations/{c.location_id}/customFields", params=params, action_name="get_custom_fields")


async def _create_custom_field(node, c, token):
    body = {
        "name": c.name, "dataType": c.data_type, "placeholder": c.placeholder,
        "acceptedFormat": _ghl_csv(c.accepted_format), "isMultipleFile": _ghl_bool(c.is_multiple_file),
        "maxNumberOfFiles": _ghl_num(c.max_number_of_files),
        "textBoxListOptions": _ghl_json(c.text_box_list_options),
        "position": _ghl_num(c.position), "model": c.model,
    }
    return await node._request(token, "POST", f"/locations/{c.location_id}/customFields", json_body=body, action_name="create_custom_field")


async def _get_custom_field(node, c, token):
    return await node._request(token, "GET", f"/locations/{c.location_id}/customFields/{c.id}", action_name="get_custom_field")


async def _update_custom_field(node, c, token):
    body = {
        "name": c.name, "placeholder": c.placeholder,
        "acceptedFormat": _ghl_csv(c.accepted_format), "isMultipleFile": _ghl_bool(c.is_multiple_file),
        "maxNumberOfFiles": _ghl_num(c.max_number_of_files),
        "textBoxListOptions": _ghl_json(c.text_box_list_options),
        "position": _ghl_num(c.position), "model": c.model,
    }
    return await node._request(token, "PUT", f"/locations/{c.location_id}/customFields/{c.id}", json_body=body, action_name="update_custom_field")


async def _delete_custom_field(node, c, token):
    return await node._request(token, "DELETE", f"/locations/{c.location_id}/customFields/{c.id}", action_name="delete_custom_field")


async def _upload_custom_fields_file(node, c, token):
    data = {"id": c.id, "maxFiles": c.max_files}
    return await node._request(token, "POST", f"/locations/{c.location_id}/customFields/upload", data=data, action_name="upload_custom_fields_file")


async def _get_custom_values(node, c, token):
    return await node._request(token, "GET", f"/locations/{c.location_id}/customValues", action_name="get_custom_values")


async def _create_custom_value(node, c, token):
    body = {"name": c.name, "value": c.value}
    return await node._request(token, "POST", f"/locations/{c.location_id}/customValues", json_body=body, action_name="create_custom_value")


async def _get_custom_value(node, c, token):
    return await node._request(token, "GET", f"/locations/{c.location_id}/customValues/{c.id}", action_name="get_custom_value")


async def _update_custom_value(node, c, token):
    body = {"name": c.name, "value": c.value}
    return await node._request(token, "PUT", f"/locations/{c.location_id}/customValues/{c.id}", json_body=body, action_name="update_custom_value")


async def _delete_custom_value(node, c, token):
    return await node._request(token, "DELETE", f"/locations/{c.location_id}/customValues/{c.id}", action_name="delete_custom_value")


async def _get_location_timezones(node, c, token):
    return await node._request(token, "GET", f"/locations/{c.location_id}/timezones", action_name="get_location_timezones")


async def _get_location_templates(node, c, token):
    params = {
        "originId": c.origin_id, "deleted": _ghl_bool(c.deleted),
        "skip": c.skip, "limit": c.limit, "type": c.type,
    }
    return await node._request(token, "GET", f"/locations/{c.location_id}/templates", params=params, action_name="get_location_templates")


async def _delete_location_template(node, c, token):
    return await node._request(token, "DELETE", f"/locations/{c.location_id}/templates/{c.id}", action_name="delete_location_template")


GHL_OPERATION_CONFIGS += [
    GHLSearchLocationsConfig,
    GHLGetLocationConfig,
    GHLCreateLocationConfig,
    GHLPutLocationConfig,
    GHLDeleteLocationConfig,
    GHLGetLocationTagsConfig,
    GHLCreateLocationTagConfig,
    GHLGetLocationTagByIdConfig,
    GHLUpdateLocationTagConfig,
    GHLDeleteLocationTagConfig,
    GHLLocationTaskSearchConfig,
    GHLCreateRecurringTaskConfig,
    GHLGetRecurringTaskByIdConfig,
    GHLUpdateRecurringTaskConfig,
    GHLDeleteRecurringTaskConfig,
    GHLGetCustomFieldsConfig,
    GHLCreateCustomFieldConfig,
    GHLGetCustomFieldConfig,
    GHLUpdateCustomFieldConfig,
    GHLDeleteCustomFieldConfig,
    GHLUploadCustomFieldsFileConfig,
    GHLGetCustomValuesConfig,
    GHLCreateCustomValueConfig,
    GHLGetCustomValueConfig,
    GHLUpdateCustomValueConfig,
    GHLDeleteCustomValueConfig,
    GHLGetLocationTimezonesConfig,
    GHLGetLocationTemplatesConfig,
    GHLDeleteLocationTemplateConfig,
]
GHL_OPERATION_HANDLERS.update({
    "search_locations": _search_locations,
    "get_location": _get_location,
    "create_location": _create_location,
    "put_location": _put_location,
    "delete_location": _delete_location,
    "get_location_tags": _get_location_tags,
    "create_location_tag": _create_location_tag,
    "get_location_tag_by_id": _get_location_tag_by_id,
    "update_location_tag": _update_location_tag,
    "delete_location_tag": _delete_location_tag,
    "location_task_search": _location_task_search,
    "create_recurring_task": _create_recurring_task,
    "get_recurring_task_by_id": _get_recurring_task_by_id,
    "update_recurring_task": _update_recurring_task,
    "delete_recurring_task": _delete_recurring_task,
    "get_custom_fields": _get_custom_fields,
    "create_custom_field": _create_custom_field,
    "get_custom_field": _get_custom_field,
    "update_custom_field": _update_custom_field,
    "delete_custom_field": _delete_custom_field,
    "upload_custom_fields_file": _upload_custom_fields_file,
    "get_custom_values": _get_custom_values,
    "create_custom_value": _create_custom_value,
    "get_custom_value": _get_custom_value,
    "update_custom_value": _update_custom_value,
    "delete_custom_value": _delete_custom_value,
    "get_location_timezones": _get_location_timezones,
    "get_location_templates": _get_location_templates,
    "delete_location_template": _delete_location_template,
})


# ---- marketplace.py ----
class GHLCreateMarketplaceChargeConfig(BaseModel):
    """Raise a usage-based (metered) charge for an app installation."""

    operation: Literal["create_marketplace_charge"] = Field(
        "create_marketplace_charge",
        json_schema_extra={
            "const": "create_marketplace_charge", "ui:hidden": True,
            "x-category": "Marketplace", "x-is-trigger": False,
            "x-display-name": "Raise Charge",
        },
        title="Raise Charge",
    )
    app_id: str = Field(..., title="App ID", description="Marketplace app id")
    meter_id: str = Field(..., title="Meter ID", description="Meter id for the metered price")
    event_id: str = Field(..., title="Event ID", description="Unique event id (idempotency)")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    company_id: str = Field(..., title="Company ID", description="Agency (company) id")
    description: str = Field(..., title="Description", description="Charge description")
    units: str = Field(..., title="Units", description="Number of units to charge")
    user_id: Optional[str] = Field(None, title="User ID")
    price: Optional[str] = Field(None, title="Price", description="Per-unit price")
    event_time: Optional[str] = Field(None, title="Event Time", description="ISO timestamp of the event")


class GHLGetMarketplaceChargesConfig(BaseModel):
    """List raised charges, optionally filtered by meter/event/user/date."""

    operation: Literal["get_marketplace_charges"] = Field(
        "get_marketplace_charges",
        json_schema_extra={
            "const": "get_marketplace_charges", "ui:hidden": True,
            "x-category": "Marketplace", "x-is-trigger": False,
            "x-display-name": "List Charges",
        },
        title="List Charges",
    )
    meter_id: Optional[str] = Field(None, title="Meter ID")
    event_id: Optional[str] = Field(None, title="Event ID")
    user_id: Optional[str] = Field(None, title="User ID")
    start_date: Optional[str] = Field(None, title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")


class GHLDeleteMarketplaceChargeConfig(BaseModel):
    """Delete a previously raised charge by id."""

    operation: Literal["delete_marketplace_charge"] = Field(
        "delete_marketplace_charge",
        json_schema_extra={
            "const": "delete_marketplace_charge", "ui:hidden": True,
            "x-category": "Marketplace", "x-is-trigger": False,
            "x-display-name": "Delete Charge",
        },
        title="Delete Charge",
    )
    charge_id: str = Field(..., title="Charge ID", description="The charge to delete")


class GHLGetSpecificMarketplaceChargeConfig(BaseModel):
    """Get a single charge by id."""

    operation: Literal["get_specific_marketplace_charge"] = Field(
        "get_specific_marketplace_charge",
        json_schema_extra={
            "const": "get_specific_marketplace_charge", "ui:hidden": True,
            "x-category": "Marketplace", "x-is-trigger": False,
            "x-display-name": "Get Charge",
        },
        title="Get Charge",
    )
    charge_id: str = Field(..., title="Charge ID", description="The charge to fetch")


class GHLMarketplaceHasFundsConfig(BaseModel):
    """Check whether the installation has funds available for charging."""

    operation: Literal["marketplace_has_funds"] = Field(
        "marketplace_has_funds",
        json_schema_extra={
            "const": "marketplace_has_funds", "ui:hidden": True,
            "x-category": "Marketplace", "x-is-trigger": False,
            "x-display-name": "Has Funds",
        },
        title="Has Funds",
    )


class GHLUninstallApplicationConfig(BaseModel):
    """Uninstall a marketplace app from a company or location."""

    operation: Literal["uninstall_application"] = Field(
        "uninstall_application",
        json_schema_extra={
            "const": "uninstall_application", "ui:hidden": True,
            "x-category": "Marketplace", "x-is-trigger": False,
            "x-display-name": "Uninstall Application",
        },
        title="Uninstall Application",
    )
    app_id: str = Field(..., title="App ID", description="Marketplace app id")
    company_id: Optional[str] = Field(None, title="Company ID")
    location_id: Optional[str] = Field(None, title="Location ID")
    reason: Optional[str] = Field(None, title="Reason", description="Reason for uninstalling")


class GHLGetInstallerDetailsConfig(BaseModel):
    """Get installation/installer details for a marketplace app."""

    operation: Literal["get_installer_details"] = Field(
        "get_installer_details",
        json_schema_extra={
            "const": "get_installer_details", "ui:hidden": True,
            "x-category": "Marketplace", "x-is-trigger": False,
            "x-display-name": "Get Installer Details",
        },
        title="Get Installer Details",
    )
    app_id: str = Field(..., title="App ID", description="Marketplace app id")


class GHLGetRebillingConfigForAppConfig(BaseModel):
    """Get the rebilling configuration for an app in a location."""

    operation: Literal["get_rebilling_config_for_app"] = Field(
        "get_rebilling_config_for_app",
        json_schema_extra={
            "const": "get_rebilling_config_for_app", "ui:hidden": True,
            "x-category": "Marketplace", "x-is-trigger": False,
            "x-display-name": "Get Rebilling Config For App",
        },
        title="Get Rebilling Config For App",
    )
    app_id: str = Field(..., title="App ID", description="Marketplace app id")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLMigrateConnectionConfig(BaseModel):
    """Migrate an external auth connection into a marketplace app installation."""

    operation: Literal["migrate_connection"] = Field(
        "migrate_connection",
        json_schema_extra={
            "const": "migrate_connection", "ui:hidden": True,
            "x-category": "Marketplace", "x-is-trigger": False,
            "x-display-name": "Migrate Connection",
        },
        title="Migrate Connection",
    )
    type: str = Field(
        ..., title="Type", description="Connection type",
        json_schema_extra={
            "enum": ["oauth2", "basic"], "enumNames": ["OAuth2", "Basic"],
            "x-enum-searchable": True,
        },
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    app_id: str = Field(..., title="App ID", description="Marketplace app id")
    app_version_id: str = Field(..., title="App Version ID")
    account_id: str = Field(..., title="Account ID", description="External account id")
    api_key: Optional[str] = Field(None, title="API Key")
    basic_credentials: Optional[str] = Field(
        None, title="Basic Credentials", description="JSON object of basic-auth credentials",
    )
    access_token: Optional[str] = Field(None, title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expiry_in: Optional[str] = Field(None, title="Expiry In", description="Seconds until expiry")
    expiry_at: Optional[str] = Field(None, title="Expiry At", description="Epoch expiry timestamp")
    scopes: Optional[str] = Field(None, title="Scopes", description="Comma-separated scopes")
    display_name: Optional[str] = Field(None, title="Display Name")
    is_default: Optional[str] = Field(
        None, title="Is Default",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


async def _create_marketplace_charge(node, c, token):
    body = {
        "appId": c.app_id, "meterId": c.meter_id, "eventId": c.event_id,
        "userId": c.user_id, "locationId": c.location_id, "companyId": c.company_id,
        "description": c.description, "price": _ghl_num(c.price), "units": _ghl_num(c.units),
        "eventTime": c.event_time,
    }
    return await node._request(token, "POST", "/marketplace/billing/charges", json_body=body, action_name="create_marketplace_charge")


async def _get_marketplace_charges(node, c, token):
    params = {
        "meterId": c.meter_id, "eventId": c.event_id, "userId": c.user_id,
        "startDate": c.start_date, "endDate": c.end_date,
        "skip": _ghl_num(c.skip), "limit": _ghl_num(c.limit),
    }
    return await node._request(token, "GET", "/marketplace/billing/charges", params=params, action_name="get_marketplace_charges")


async def _delete_marketplace_charge(node, c, token):
    return await node._request(token, "DELETE", f"/marketplace/billing/charges/{c.charge_id}", action_name="delete_marketplace_charge")


async def _get_specific_marketplace_charge(node, c, token):
    return await node._request(token, "GET", f"/marketplace/billing/charges/{c.charge_id}", action_name="get_specific_marketplace_charge")


async def _marketplace_has_funds(node, c, token):
    return await node._request(token, "GET", "/marketplace/billing/charges/has-funds", action_name="marketplace_has_funds")


async def _uninstall_application(node, c, token):
    body = {"companyId": c.company_id, "locationId": c.location_id, "reason": c.reason}
    return await node._request(token, "DELETE", f"/marketplace/app/{c.app_id}/installations", json_body=body, action_name="uninstall_application")


async def _get_installer_details(node, c, token):
    return await node._request(token, "GET", f"/marketplace/app/{c.app_id}/installations", action_name="get_installer_details")


async def _get_rebilling_config_for_app(node, c, token):
    return await node._request(token, "GET", f"/marketplace/app/{c.app_id}/rebilling-config/location/{c.location_id}", action_name="get_rebilling_config_for_app")


async def _migrate_connection(node, c, token):
    body = {
        "type": c.type, "locationId": c.location_id, "appId": c.app_id,
        "appVersionId": c.app_version_id, "accountId": c.account_id, "apiKey": c.api_key,
        "basicCredentials": _ghl_json(c.basic_credentials), "accessToken": c.access_token,
        "refreshToken": c.refresh_token, "expiryIn": _ghl_num(c.expiry_in),
        "expiryAt": _ghl_num(c.expiry_at), "scopes": _ghl_csv(c.scopes),
        "displayName": c.display_name, "isDefault": _ghl_bool(c.is_default),
    }
    return await node._request(token, "POST", "/marketplace/external-auth/migration", json_body=body, action_name="migrate_connection")


GHL_OPERATION_CONFIGS += [
    GHLCreateMarketplaceChargeConfig,
    GHLGetMarketplaceChargesConfig,
    GHLDeleteMarketplaceChargeConfig,
    GHLGetSpecificMarketplaceChargeConfig,
    GHLMarketplaceHasFundsConfig,
    GHLUninstallApplicationConfig,
    GHLGetInstallerDetailsConfig,
    GHLGetRebillingConfigForAppConfig,
    GHLMigrateConnectionConfig,
]
GHL_OPERATION_HANDLERS.update({
    "create_marketplace_charge": _create_marketplace_charge,
    "get_marketplace_charges": _get_marketplace_charges,
    "delete_marketplace_charge": _delete_marketplace_charge,
    "get_specific_marketplace_charge": _get_specific_marketplace_charge,
    "marketplace_has_funds": _marketplace_has_funds,
    "uninstall_application": _uninstall_application,
    "get_installer_details": _get_installer_details,
    "get_rebilling_config_for_app": _get_rebilling_config_for_app,
    "migrate_connection": _migrate_connection,
})


# ---- medias.py ----
class GHLFetchMediaContentConfig(BaseModel):
    """Get list of files and folders from the media storage."""

    operation: Literal["fetch_media_content"] = Field(
        "fetch_media_content",
        json_schema_extra={
            "const": "fetch_media_content", "ui:hidden": True,
            "x-category": "Media Library", "x-is-trigger": False,
            "x-display-name": "List Files/Folders",
        },
        title="List Files/Folders",
    )
    sort_by: str = Field(..., title="Sort By", description="Field to sort the file listing by (e.g. createdAt)")
    sort_order: str = Field(..., title="Sort Order", description="Direction to sort (asc/desc)")
    type: str = Field(..., title="Type", description="Type to filter by (e.g. file)")
    alt_type: str = Field("location", title="Alt Type", description="AltType (location)")
    alt_id: str = Field(..., title="Alt ID", description="Location Id")
    offset: Optional[str] = Field(None, title="Offset", description="Number of files to skip in listing")
    limit: Optional[str] = Field(None, title="Limit", description="Number of files to show in the listing")
    query: Optional[str] = Field(None, title="Query", description="Query text")
    parent_id: Optional[str] = Field(None, title="Parent ID", description="Parent id or folder id")
    fetch_all: Optional[str] = Field(
        None, title="Fetch All", description="Fetch all files or folders",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLUploadMediaContentConfig(BaseModel):
    """Upload a file into media storage. If hosted is true, fileUrl is required; else file is required (max 25 MB)."""

    operation: Literal["upload_media_content"] = Field(
        "upload_media_content",
        json_schema_extra={
            "const": "upload_media_content", "ui:hidden": True,
            "x-category": "Media Library", "x-is-trigger": False,
            "x-display-name": "Upload File",
        },
        title="Upload File",
    )
    hosted: Optional[str] = Field(
        None, title="Hosted", description="If true, upload from a remote fileUrl instead of a binary file",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    file_url: Optional[str] = Field(None, title="File URL", description="Remote file URL (required when hosted is true)")
    name: Optional[str] = Field(None, title="Name", description="Name of the file")
    parent_id: Optional[str] = Field(None, title="Parent ID", description="Parent folder id")


class GHLDeleteMediaContentConfig(BaseModel):
    """Delete a specific file or folder from media storage."""

    operation: Literal["delete_media_content"] = Field(
        "delete_media_content",
        json_schema_extra={
            "const": "delete_media_content", "ui:hidden": True,
            "x-category": "Media Library", "x-is-trigger": False,
            "x-display-name": "Delete File/Folder",
        },
        title="Delete File/Folder",
    )
    id: str = Field(..., title="ID", description="Id of the file or folder to delete")
    alt_type: str = Field("location", title="Alt Type", description="AltType (location)")
    alt_id: str = Field(..., title="Alt ID", description="Location Id")


class GHLUpdateMediaObjectConfig(BaseModel):
    """Update a single file or folder by id."""

    operation: Literal["update_media_object"] = Field(
        "update_media_object",
        json_schema_extra={
            "const": "update_media_object", "ui:hidden": True,
            "x-category": "Media Library", "x-is-trigger": False,
            "x-display-name": "Update File/Folder",
        },
        title="Update File/Folder",
    )
    id: str = Field(..., title="ID", description="Unique identifier of the file or folder to update")
    name: str = Field(..., title="Name", description="New name for the file or folder")
    alt_type: str = Field("location", title="Alt Type", description="Type of entity that owns the file or folder (location)")
    alt_id: str = Field(..., title="Alt ID", description="Location identifier that owns the file or folder")


class GHLCreateMediaFolderConfig(BaseModel):
    """Create a new folder in the media storage."""

    operation: Literal["create_media_folder"] = Field(
        "create_media_folder",
        json_schema_extra={
            "const": "create_media_folder", "ui:hidden": True,
            "x-category": "Media Library", "x-is-trigger": False,
            "x-display-name": "Create Folder",
        },
        title="Create Folder",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location Id")
    alt_type: str = Field("location", title="Alt Type", description="Type of entity (location)")
    name: str = Field(..., title="Name", description="Name of the folder to be created")
    parent_id: Optional[str] = Field(None, title="Parent ID", description="ID of the parent folder (optional)")


class GHLBulkUpdateMediaObjectsConfig(BaseModel):
    """Bulk update metadata or status of multiple files and folders."""

    operation: Literal["bulk_update_media_objects"] = Field(
        "bulk_update_media_objects",
        json_schema_extra={
            "const": "bulk_update_media_objects", "ui:hidden": True,
            "x-category": "Media Library", "x-is-trigger": False,
            "x-display-name": "Bulk Update Files/Folders",
        },
        title="Bulk Update Files/Folders",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location identifier")
    alt_type: str = Field("location", title="Alt Type", description="Type of entity that owns the files (location)")
    files_to_be_updated: str = Field(
        ..., title="Files To Be Updated",
        description='JSON array of file objects to update, e.g. [{"id": "...", "name": "New Name.pdf"}]',
    )


class GHLBulkDeleteMediaObjectsConfig(BaseModel):
    """Bulk soft-delete or trash multiple files and folders."""

    operation: Literal["bulk_delete_media_objects"] = Field(
        "bulk_delete_media_objects",
        json_schema_extra={
            "const": "bulk_delete_media_objects", "ui:hidden": True,
            "x-category": "Media Library", "x-is-trigger": False,
            "x-display-name": "Bulk Delete/Trash Files/Folders",
        },
        title="Bulk Delete/Trash Files/Folders",
    )
    files_to_be_deleted: str = Field(
        ..., title="Files To Be Deleted",
        description='JSON array of file objects to delete, e.g. [{"_id": "..."}]',
    )
    alt_type: str = Field("location", title="Alt Type", description="Type of entity that owns the files (location)")
    alt_id: str = Field(..., title="Alt ID", description="Location identifier")
    status: str = Field(
        ..., title="Status", description="Status to set for the files (deleted or trashed)",
        json_schema_extra={
            "enum": ["deleted", "trashed"], "x-enum-searchable": True,
        },
    )


async def _fetch_media_content(node, c, token):
    params = {
        "sortBy": c.sort_by, "sortOrder": c.sort_order, "type": c.type,
        "altType": c.alt_type, "altId": c.alt_id, "offset": c.offset,
        "limit": c.limit, "query": c.query, "parentId": c.parent_id,
        "fetchAll": _ghl_bool(c.fetch_all),
    }
    return await node._request(token, "GET", "/medias/files", params=params, action_name="fetch_media_content")


async def _upload_media_content(node, c, token):
    data = {
        "hosted": _ghl_bool(c.hosted), "fileUrl": c.file_url,
        "name": c.name, "parentId": c.parent_id,
    }
    return await node._request(token, "POST", "/medias/upload-file", data=data, action_name="upload_media_content")


async def _delete_media_content(node, c, token):
    params = {"altType": c.alt_type, "altId": c.alt_id}
    return await node._request(token, "DELETE", f"/medias/{c.id}", params=params, action_name="delete_media_content")


async def _update_media_object(node, c, token):
    body = {"name": c.name, "altType": c.alt_type, "altId": c.alt_id}
    return await node._request(token, "POST", f"/medias/{c.id}", json_body=body, action_name="update_media_object")


async def _create_media_folder(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type, "name": c.name, "parentId": c.parent_id}
    return await node._request(token, "POST", "/medias/folder", json_body=body, action_name="create_media_folder")


async def _bulk_update_media_objects(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type,
        "filesToBeUpdated": _ghl_json(c.files_to_be_updated),
    }
    return await node._request(token, "PUT", "/medias/update-files", json_body=body, action_name="bulk_update_media_objects")


async def _bulk_delete_media_objects(node, c, token):
    body = {
        "filesToBeDeleted": _ghl_json(c.files_to_be_deleted),
        "altType": c.alt_type, "altId": c.alt_id, "status": c.status,
    }
    return await node._request(token, "PUT", "/medias/delete-files", json_body=body, action_name="bulk_delete_media_objects")


GHL_OPERATION_CONFIGS += [
    GHLFetchMediaContentConfig,
    GHLUploadMediaContentConfig,
    GHLDeleteMediaContentConfig,
    GHLUpdateMediaObjectConfig,
    GHLCreateMediaFolderConfig,
    GHLBulkUpdateMediaObjectsConfig,
    GHLBulkDeleteMediaObjectsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "fetch_media_content": _fetch_media_content,
    "upload_media_content": _upload_media_content,
    "delete_media_content": _delete_media_content,
    "update_media_object": _update_media_object,
    "create_media_folder": _create_media_folder,
    "bulk_update_media_objects": _bulk_update_media_objects,
    "bulk_delete_media_objects": _bulk_delete_media_objects,
})


# ---- objects.py ----
class GHLGetObjectSchemaByKeyConfig(BaseModel):
    """Get an object schema by key / id."""

    operation: Literal["get_object_schema_by_key"] = Field(
        "get_object_schema_by_key",
        json_schema_extra={
            "const": "get_object_schema_by_key", "ui:hidden": True,
            "x-category": "Custom Objects", "x-is-trigger": False,
            "x-display-name": "Get Object Schema",
        },
        title="Get Object Schema",
    )
    key: str = Field(..., title="Object Key", description="Object key or id (e.g. custom_objects.pet)")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    fetch_properties: Optional[str] = Field(
        None, title="Fetch Properties",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
        description="Whether to include the object's properties/fields in the response",
    )


class GHLUpdateCustomObjectConfig(BaseModel):
    """Update an object schema by key / id."""

    operation: Literal["update_custom_object"] = Field(
        "update_custom_object",
        json_schema_extra={
            "const": "update_custom_object", "ui:hidden": True,
            "x-category": "Custom Objects", "x-is-trigger": False,
            "x-display-name": "Update Object Schema",
        },
        title="Update Object Schema",
    )
    key: str = Field(..., title="Object Key", description="Object key or id to update")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    searchable_properties: str = Field(
        ..., title="Searchable Properties",
        description="JSON array of field keys to make searchable, format custom_objects.<object>.<field_key>",
    )
    labels: Optional[str] = Field(
        None, title="Labels",
        description='JSON object with singular/plural display names, e.g. {"singular":"Pet","plural":"Pets"}',
    )
    description: Optional[str] = Field(None, title="Description", description="Object description")


class GHLGetObjectRecordByIdConfig(BaseModel):
    """Get an object record by id."""

    operation: Literal["get_object_record_by_id"] = Field(
        "get_object_record_by_id",
        json_schema_extra={
            "const": "get_object_record_by_id", "ui:hidden": True,
            "x-category": "Custom Objects", "x-is-trigger": False,
            "x-display-name": "Get Record",
        },
        title="Get Record",
    )
    schema_key: str = Field(..., title="Schema Key", description="Object schema key (e.g. custom_objects.pet)")
    record_id: str = Field(..., title="Record ID", description="The record to fetch")


class GHLUpdateObjectRecordConfig(BaseModel):
    """Update an object record."""

    operation: Literal["update_object_record"] = Field(
        "update_object_record",
        json_schema_extra={
            "const": "update_object_record", "ui:hidden": True,
            "x-category": "Custom Objects", "x-is-trigger": False,
            "x-display-name": "Update Record",
        },
        title="Update Record",
    )
    schema_key: str = Field(..., title="Schema Key", description="Object schema key (e.g. custom_objects.pet)")
    record_id: str = Field(..., title="Record ID", description="The record to update")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    properties: Optional[str] = Field(
        None, title="Properties",
        description='JSON object of field key -> value for the record, e.g. {"name":"Rex","age":3}',
    )
    owner: Optional[str] = Field(None, title="Owner", description="JSON array of owner user ids")
    followers: Optional[str] = Field(None, title="Followers", description="JSON array of follower user ids")


class GHLDeleteObjectRecordConfig(BaseModel):
    """Delete an object record."""

    operation: Literal["delete_object_record"] = Field(
        "delete_object_record",
        json_schema_extra={
            "const": "delete_object_record", "ui:hidden": True,
            "x-category": "Custom Objects", "x-is-trigger": False,
            "x-display-name": "Delete Record",
        },
        title="Delete Record",
    )
    schema_key: str = Field(..., title="Schema Key", description="Object schema key (e.g. custom_objects.pet)")
    record_id: str = Field(..., title="Record ID", description="The record to delete")


class GHLCreateObjectRecordConfig(BaseModel):
    """Create an object record."""

    operation: Literal["create_object_record"] = Field(
        "create_object_record",
        json_schema_extra={
            "const": "create_object_record", "ui:hidden": True,
            "x-category": "Custom Objects", "x-is-trigger": False,
            "x-display-name": "Create Record",
        },
        title="Create Record",
    )
    schema_key: str = Field(..., title="Schema Key", description="Object schema key (e.g. custom_objects.pet)")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    properties: Optional[str] = Field(
        None, title="Properties",
        description='JSON object of field key -> value for the record, e.g. {"name":"Rex","age":3}',
    )
    owner: Optional[str] = Field(None, title="Owner", description="JSON array of owner user ids")
    followers: Optional[str] = Field(None, title="Followers", description="JSON array of follower user ids")


class GHLSearchObjectRecordsConfig(BaseModel):
    """Search object records."""

    operation: Literal["search_object_records"] = Field(
        "search_object_records",
        json_schema_extra={
            "const": "search_object_records", "ui:hidden": True,
            "x-category": "Custom Objects", "x-is-trigger": False,
            "x-display-name": "Search Records",
        },
        title="Search Records",
    )
    schema_key: str = Field(..., title="Schema Key", description="Object schema key (e.g. custom_objects.pet)")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    query: str = Field(..., title="Query", description="Search query string")
    page: str = Field(..., title="Page", description="Page number (1-based)")
    page_limit: str = Field(..., title="Page Limit", description="Number of records per page")
    search_after: Optional[str] = Field(
        None, title="Search After",
        description="JSON array of cursor values for pagination (from a previous response)",
    )


class GHLGetObjectByLocationIdConfig(BaseModel):
    """Get all objects for a location."""

    operation: Literal["get_object_by_location_id"] = Field(
        "get_object_by_location_id",
        json_schema_extra={
            "const": "get_object_by_location_id", "ui:hidden": True,
            "x-category": "Custom Objects", "x-is-trigger": False,
            "x-display-name": "List Objects",
        },
        title="List Objects",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateCustomObjectSchemaConfig(BaseModel):
    """Create a custom object schema."""

    operation: Literal["create_custom_object_schema"] = Field(
        "create_custom_object_schema",
        json_schema_extra={
            "const": "create_custom_object_schema", "ui:hidden": True,
            "x-category": "Custom Objects", "x-is-trigger": False,
            "x-display-name": "Create Custom Object",
        },
        title="Create Custom Object",
    )
    key: str = Field(..., title="Object Key", description="Internal key, lowercase + underscore (custom_objects. prefix added by default)")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    labels: str = Field(
        ..., title="Labels",
        description='JSON object with singular/plural display names, e.g. {"singular":"Pet","plural":"Pets"}',
    )
    primary_display_property_details: str = Field(
        ..., title="Primary Display Property",
        description='JSON object with key/name/dataType for the primary property, e.g. {"key":"custom_objects.pet.name","name":"Pet name","dataType":"TEXT"}',
    )
    description: Optional[str] = Field(None, title="Description", description="Object description")


async def _get_object_schema_by_key(node, c, token):
    params = {"locationId": c.location_id, "fetchProperties": _ghl_bool(c.fetch_properties)}
    return await node._request(token, "GET", f"/objects/{c.key}", params=params, action_name="get_object_schema_by_key")


async def _update_custom_object(node, c, token):
    body = {
        "locationId": c.location_id,
        "searchableProperties": _ghl_json(c.searchable_properties),
        "labels": _ghl_json(c.labels),
        "description": c.description,
    }
    return await node._request(token, "PUT", f"/objects/{c.key}", json_body=body, action_name="update_custom_object")


async def _get_object_record_by_id(node, c, token):
    return await node._request(token, "GET", f"/objects/{c.schema_key}/records/{c.record_id}", action_name="get_object_record_by_id")


async def _update_object_record(node, c, token):
    params = {"locationId": c.location_id}
    body = {
        "properties": _ghl_json(c.properties),
        "owner": _ghl_json(c.owner),
        "followers": _ghl_json(c.followers),
    }
    return await node._request(token, "PUT", f"/objects/{c.schema_key}/records/{c.record_id}", params=params, json_body=body, action_name="update_object_record")


async def _delete_object_record(node, c, token):
    return await node._request(token, "DELETE", f"/objects/{c.schema_key}/records/{c.record_id}", action_name="delete_object_record")


async def _create_object_record(node, c, token):
    body = {
        "locationId": c.location_id,
        "properties": _ghl_json(c.properties),
        "owner": _ghl_json(c.owner),
        "followers": _ghl_json(c.followers),
    }
    return await node._request(token, "POST", f"/objects/{c.schema_key}/records", json_body=body, action_name="create_object_record")


async def _search_object_records(node, c, token):
    body = {
        "locationId": c.location_id,
        "page": _ghl_num(c.page),
        "pageLimit": _ghl_num(c.page_limit),
        "query": c.query,
        "searchAfter": _ghl_json(c.search_after),
    }
    return await node._request(token, "POST", f"/objects/{c.schema_key}/records/search", json_body=body, action_name="search_object_records")


async def _get_object_by_location_id(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", "/objects/", params=params, action_name="get_object_by_location_id")


async def _create_custom_object_schema(node, c, token):
    body = {
        "key": c.key,
        "locationId": c.location_id,
        "labels": _ghl_json(c.labels),
        "primaryDisplayPropertyDetails": _ghl_json(c.primary_display_property_details),
        "description": c.description,
    }
    return await node._request(token, "POST", "/objects/", json_body=body, action_name="create_custom_object_schema")


GHL_OPERATION_CONFIGS += [
    GHLGetObjectSchemaByKeyConfig,
    GHLUpdateCustomObjectConfig,
    GHLGetObjectRecordByIdConfig,
    GHLUpdateObjectRecordConfig,
    GHLDeleteObjectRecordConfig,
    GHLCreateObjectRecordConfig,
    GHLSearchObjectRecordsConfig,
    GHLGetObjectByLocationIdConfig,
    GHLCreateCustomObjectSchemaConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_object_schema_by_key": _get_object_schema_by_key,
    "update_custom_object": _update_custom_object,
    "get_object_record_by_id": _get_object_record_by_id,
    "update_object_record": _update_object_record,
    "delete_object_record": _delete_object_record,
    "create_object_record": _create_object_record,
    "search_object_records": _search_object_records,
    "get_object_by_location_id": _get_object_by_location_id,
    "create_custom_object_schema": _create_custom_object_schema,
})


# ---- opportunities.py ----
class GHLGetOpportunityLostReasonConfig(BaseModel):
    """Get lost reasons for a location."""

    operation: Literal["get_opportunity_lost_reason"] = Field(
        "get_opportunity_lost_reason",
        json_schema_extra={
            "const": "get_opportunity_lost_reason", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Get Lost Reasons",
        },
        title="Get Lost Reasons",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: Optional[str] = Field(None, title="Name")
    deleted: Optional[str] = Field(None, title="Deleted", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })
    query: Optional[str] = Field(None, title="Query")
    skip: Optional[str] = Field(None, title="Skip")
    limit: Optional[str] = Field(None, title="Limit")
    get_count: Optional[str] = Field(None, title="Get Count", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })


class GHLSearchOpportunityConfig(BaseModel):
    """Search opportunities (GET query-param based)."""

    operation: Literal["search_opportunity"] = Field(
        "search_opportunity",
        json_schema_extra={
            "const": "search_opportunity", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Search Opportunities",
        },
        title="Search Opportunities",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    q: Optional[str] = Field(None, title="Query Text")
    pipeline_id: Optional[str] = Field(None, title="Pipeline ID")
    pipeline_stage_id: Optional[str] = Field(None, title="Pipeline Stage ID")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    status: Optional[str] = Field(None, title="Status")
    assigned_to: Optional[str] = Field(None, title="Assigned To")
    campaign_id: Optional[str] = Field(None, title="Campaign ID")
    id: Optional[str] = Field(None, title="Opportunity ID")
    order: Optional[str] = Field(None, title="Order")
    end_date: Optional[str] = Field(None, title="End Date")
    start_after: Optional[str] = Field(None, title="Start After")
    start_after_id: Optional[str] = Field(None, title="Start After ID")
    date: Optional[str] = Field(None, title="Date")
    country: Optional[str] = Field(None, title="Country")
    page: Optional[str] = Field(None, title="Page")
    limit: Optional[str] = Field(None, title="Limit")
    get_tasks: Optional[str] = Field(None, title="Get Tasks", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })
    get_notes: Optional[str] = Field(None, title="Get Notes", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })
    get_calendar_events: Optional[str] = Field(None, title="Get Calendar Events", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })


class GHLSearchOpportunitiesAdvancedConfig(BaseModel):
    """Search opportunities (POST body based, advanced)."""

    operation: Literal["search_opportunities_advanced"] = Field(
        "search_opportunities_advanced",
        json_schema_extra={
            "const": "search_opportunities_advanced", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Search Opportunities (Advanced)",
        },
        title="Search Opportunities (Advanced)",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    query: str = Field(..., title="Query")
    limit: str = Field(..., title="Limit")
    page: str = Field(..., title="Page")
    search_after: Optional[str] = Field(None, title="Search After", description="JSON array of cursor values")
    additional_details: Optional[str] = Field(None, title="Additional Details", description="JSON object: {notes, tasks, calendarEvents, unReadConversations}")


class GHLGetOpportunityPipelinesConfig(BaseModel):
    """Get pipelines for a location."""

    operation: Literal["get_opportunity_pipelines"] = Field(
        "get_opportunity_pipelines",
        json_schema_extra={
            "const": "get_opportunity_pipelines", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Get Pipelines",
        },
        title="Get Pipelines",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLGetOpportunityConfig(BaseModel):
    """Get an opportunity by id."""

    operation: Literal["get_opportunity"] = Field(
        "get_opportunity",
        json_schema_extra={
            "const": "get_opportunity", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Get Opportunity",
        },
        title="Get Opportunity",
    )
    opportunity_id: str = Field(..., title="Opportunity ID", description="The opportunity to fetch")


class GHLDeleteOpportunityConfig(BaseModel):
    """Delete an opportunity."""

    operation: Literal["delete_opportunity"] = Field(
        "delete_opportunity",
        json_schema_extra={
            "const": "delete_opportunity", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Delete Opportunity",
        },
        title="Delete Opportunity",
    )
    opportunity_id: str = Field(..., title="Opportunity ID", description="The opportunity to delete")


class GHLUpdateOpportunityConfig(BaseModel):
    """Update an opportunity."""

    operation: Literal["update_opportunity"] = Field(
        "update_opportunity",
        json_schema_extra={
            "const": "update_opportunity", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Update Opportunity",
        },
        title="Update Opportunity",
    )
    opportunity_id: str = Field(..., title="Opportunity ID", description="The opportunity to update")
    pipeline_id: Optional[str] = Field(None, title="Pipeline ID")
    name: Optional[str] = Field(None, title="Name")
    pipeline_stage_id: Optional[str] = Field(None, title="Pipeline Stage ID")
    status: Optional[str] = Field(None, title="Status")
    monetary_value: Optional[str] = Field(None, title="Monetary Value")
    assigned_to: Optional[str] = Field(None, title="Assigned To")
    custom_fields: Optional[str] = Field(None, title="Custom Fields", description="JSON array of custom field objects")


class GHLUpdateOpportunityStatusConfig(BaseModel):
    """Update an opportunity's status."""

    operation: Literal["update_opportunity_status"] = Field(
        "update_opportunity_status",
        json_schema_extra={
            "const": "update_opportunity_status", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Update Opportunity Status",
        },
        title="Update Opportunity Status",
    )
    opportunity_id: str = Field(..., title="Opportunity ID", description="The opportunity to update")
    status: str = Field(..., title="Status")
    lost_reason_id: Optional[str] = Field(None, title="Lost Reason ID")


class GHLUpsertOpportunityConfig(BaseModel):
    """Upsert (create or update) an opportunity."""

    operation: Literal["upsert_opportunity"] = Field(
        "upsert_opportunity",
        json_schema_extra={
            "const": "upsert_opportunity", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Upsert Opportunity",
        },
        title="Upsert Opportunity",
    )
    pipeline_id: str = Field(..., title="Pipeline ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: Optional[str] = Field(None, title="Opportunity ID", description="Existing opportunity id to update")
    followers: Optional[str] = Field(None, title="Followers", description="Comma-separated user ids")
    is_remove_all_followers: Optional[str] = Field(None, title="Remove All Followers", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })
    followers_action_type: Optional[str] = Field(None, title="Followers Action Type")
    name: Optional[str] = Field(None, title="Name")
    status: Optional[str] = Field(None, title="Status")
    pipeline_stage_id: Optional[str] = Field(None, title="Pipeline Stage ID")
    monetary_value: Optional[str] = Field(None, title="Monetary Value")
    assigned_to: Optional[str] = Field(None, title="Assigned To")
    lost_reason_id: Optional[str] = Field(None, title="Lost Reason ID")


class GHLAddFollowersOpportunityConfig(BaseModel):
    """Add followers to an opportunity."""

    operation: Literal["add_followers_opportunity"] = Field(
        "add_followers_opportunity",
        json_schema_extra={
            "const": "add_followers_opportunity", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Add Followers",
        },
        title="Add Followers",
    )
    opportunity_id: str = Field(..., title="Opportunity ID", description="The opportunity")
    followers: str = Field(..., title="Followers", description="Comma-separated user ids")


class GHLRemoveFollowersOpportunityConfig(BaseModel):
    """Remove followers from an opportunity."""

    operation: Literal["remove_followers_opportunity"] = Field(
        "remove_followers_opportunity",
        json_schema_extra={
            "const": "remove_followers_opportunity", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Remove Followers",
        },
        title="Remove Followers",
    )
    opportunity_id: str = Field(..., title="Opportunity ID", description="The opportunity")
    followers: str = Field(..., title="Followers", description="Comma-separated user ids")
    is_remove_all_followers: Optional[str] = Field(None, title="Remove All Followers", json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
    })


class GHLCreateOpportunityConfig(BaseModel):
    """Create an opportunity."""

    operation: Literal["create_opportunity"] = Field(
        "create_opportunity",
        json_schema_extra={
            "const": "create_opportunity", "ui:hidden": True,
            "x-category": "Opportunities", "x-is-trigger": False,
            "x-display-name": "Create Opportunity",
        },
        title="Create Opportunity",
    )
    pipeline_id: str = Field(..., title="Pipeline ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    name: str = Field(..., title="Name")
    status: str = Field(..., title="Status")
    contact_id: str = Field(..., title="Contact ID")
    pipeline_stage_id: Optional[str] = Field(None, title="Pipeline Stage ID")
    monetary_value: Optional[str] = Field(None, title="Monetary Value")
    assigned_to: Optional[str] = Field(None, title="Assigned To")
    custom_fields: Optional[str] = Field(None, title="Custom Fields", description="JSON array of custom field objects")


async def _get_opportunity_lost_reason(node, c, token):
    params = {
        "locationId": c.location_id, "name": c.name, "deleted": _ghl_bool(c.deleted),
        "query": c.query, "skip": _ghl_num(c.skip), "limit": _ghl_num(c.limit),
        "getCount": _ghl_bool(c.get_count),
    }
    return await node._request(token, "GET", "/opportunities/lost-reason", params=params, action_name="get_opportunity_lost_reason")


async def _search_opportunity(node, c, token):
    params = {
        "q": c.q, "location_id": c.location_id, "pipeline_id": c.pipeline_id,
        "pipeline_stage_id": c.pipeline_stage_id, "contact_id": c.contact_id, "status": c.status,
        "assigned_to": c.assigned_to, "campaignId": c.campaign_id, "id": c.id, "order": c.order,
        "endDate": c.end_date, "startAfter": c.start_after, "startAfterId": c.start_after_id,
        "date": c.date, "country": c.country, "page": _ghl_num(c.page), "limit": _ghl_num(c.limit),
        "getTasks": _ghl_bool(c.get_tasks), "getNotes": _ghl_bool(c.get_notes),
        "getCalendarEvents": _ghl_bool(c.get_calendar_events),
    }
    return await node._request(token, "GET", "/opportunities/search", params=params, action_name="search_opportunity")


async def _search_opportunities_advanced(node, c, token):
    body = {
        "locationId": c.location_id, "query": c.query, "limit": _ghl_num(c.limit),
        "page": _ghl_num(c.page), "searchAfter": _ghl_json(c.search_after),
        "additionalDetails": _ghl_json(c.additional_details),
    }
    return await node._request(token, "POST", "/opportunities/search", json_body=body, action_name="search_opportunities_advanced")


async def _get_opportunity_pipelines(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", "/opportunities/pipelines", params=params, action_name="get_opportunity_pipelines")


async def _get_opportunity(node, c, token):
    return await node._request(token, "GET", f"/opportunities/{c.opportunity_id}", action_name="get_opportunity")


async def _delete_opportunity(node, c, token):
    return await node._request(token, "DELETE", f"/opportunities/{c.opportunity_id}", action_name="delete_opportunity")


async def _update_opportunity(node, c, token):
    body = {
        "pipelineId": c.pipeline_id, "name": c.name, "pipelineStageId": c.pipeline_stage_id,
        "status": c.status, "monetaryValue": _ghl_num(c.monetary_value), "assignedTo": c.assigned_to,
        "customFields": _ghl_json(c.custom_fields),
    }
    return await node._request(token, "PUT", f"/opportunities/{c.opportunity_id}", json_body=body, action_name="update_opportunity")


async def _update_opportunity_status(node, c, token):
    body = {"status": c.status, "lostReasonId": c.lost_reason_id}
    return await node._request(token, "PUT", f"/opportunities/{c.opportunity_id}/status", json_body=body, action_name="update_opportunity_status")


async def _upsert_opportunity(node, c, token):
    body = {
        "pipelineId": c.pipeline_id, "locationId": c.location_id, "id": c.id,
        "followers": _ghl_csv(c.followers), "isRemoveAllFollowers": _ghl_bool(c.is_remove_all_followers),
        "followersActionType": c.followers_action_type, "name": c.name, "status": c.status,
        "pipelineStageId": c.pipeline_stage_id, "monetaryValue": _ghl_num(c.monetary_value),
        "assignedTo": c.assigned_to, "lostReasonId": c.lost_reason_id,
    }
    return await node._request(token, "POST", "/opportunities/upsert", json_body=body, action_name="upsert_opportunity")


async def _add_followers_opportunity(node, c, token):
    body = {"followers": _ghl_csv(c.followers)}
    return await node._request(token, "POST", f"/opportunities/{c.opportunity_id}/followers", json_body=body, action_name="add_followers_opportunity")


async def _remove_followers_opportunity(node, c, token):
    params = {"isRemoveAllFollowers": _ghl_bool(c.is_remove_all_followers)}
    body = {"followers": _ghl_csv(c.followers)}
    return await node._request(token, "DELETE", f"/opportunities/{c.opportunity_id}/followers", params=params, json_body=body, action_name="remove_followers_opportunity")


async def _create_opportunity(node, c, token):
    body = {
        "pipelineId": c.pipeline_id, "locationId": c.location_id, "name": c.name,
        "pipelineStageId": c.pipeline_stage_id, "status": c.status, "contactId": c.contact_id,
        "monetaryValue": _ghl_num(c.monetary_value), "assignedTo": c.assigned_to,
        "customFields": _ghl_json(c.custom_fields),
    }
    return await node._request(token, "POST", "/opportunities/", json_body=body, action_name="create_opportunity")


GHL_OPERATION_CONFIGS += [
    GHLGetOpportunityLostReasonConfig,
    GHLSearchOpportunityConfig,
    GHLSearchOpportunitiesAdvancedConfig,
    GHLGetOpportunityPipelinesConfig,
    GHLGetOpportunityConfig,
    GHLDeleteOpportunityConfig,
    GHLUpdateOpportunityConfig,
    GHLUpdateOpportunityStatusConfig,
    GHLUpsertOpportunityConfig,
    GHLAddFollowersOpportunityConfig,
    GHLRemoveFollowersOpportunityConfig,
    GHLCreateOpportunityConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_opportunity_lost_reason": _get_opportunity_lost_reason,
    "search_opportunity": _search_opportunity,
    "search_opportunities_advanced": _search_opportunities_advanced,
    "get_opportunity_pipelines": _get_opportunity_pipelines,
    "get_opportunity": _get_opportunity,
    "delete_opportunity": _delete_opportunity,
    "update_opportunity": _update_opportunity,
    "update_opportunity_status": _update_opportunity_status,
    "upsert_opportunity": _upsert_opportunity,
    "add_followers_opportunity": _add_followers_opportunity,
    "remove_followers_opportunity": _remove_followers_opportunity,
    "create_opportunity": _create_opportunity,
})


# ---- payments.py ----
class GHLCreateWhitelabelIntegrationProviderConfig(BaseModel):
    """Create a white-label payment integration provider."""

    operation: Literal["create_whitelabel_integration_provider"] = Field(
        "create_whitelabel_integration_provider",
        json_schema_extra={
            "const": "create_whitelabel_integration_provider", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Create White-label Integration Provider",
        },
        title="Create White-label Integration Provider",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    unique_name: str = Field(..., title="Unique Name", description="Unique provider name")
    title: str = Field(..., title="Title")
    provider: Optional[str] = Field(
        None, title="Provider",
        json_schema_extra={"enum": ["authorize-net", "nmi"], "x-enum-searchable": True},
    )
    description: str = Field(..., title="Description")
    image_url: str = Field(..., title="Image URL")


class GHLListWhitelabelIntegrationProvidersConfig(BaseModel):
    """List white-label payment integration providers."""

    operation: Literal["list_whitelabel_integration_providers"] = Field(
        "list_whitelabel_integration_providers",
        json_schema_extra={
            "const": "list_whitelabel_integration_providers", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "List White-label Integration Providers",
        },
        title="List White-label Integration Providers",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    limit: Optional[str] = Field(None, title="Limit")
    offset: Optional[str] = Field(None, title="Offset")


class GHLListOrdersConfig(BaseModel):
    """List orders."""

    operation: Literal["list_orders"] = Field(
        "list_orders",
        json_schema_extra={
            "const": "list_orders", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "List Orders",
        },
        title="List Orders",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location or agency id")
    location_id: Optional[str] = Field(None, title="Location ID")
    status: Optional[str] = Field(None, title="Status")
    payment_status: Optional[str] = Field(
        None, title="Payment Status",
        json_schema_extra={
            "enum": ["paid", "unpaid", "refunded", "partially_paid"],
            "x-enum-searchable": True,
        },
    )
    payment_mode: Optional[str] = Field(None, title="Payment Mode")
    start_at: Optional[str] = Field(None, title="Start At")
    end_at: Optional[str] = Field(None, title="End At")
    search: Optional[str] = Field(None, title="Search")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    funnel_product_ids: Optional[str] = Field(None, title="Funnel Product IDs")
    source_id: Optional[str] = Field(None, title="Source ID")
    limit: Optional[str] = Field(None, title="Limit")
    offset: Optional[str] = Field(None, title="Offset")


class GHLGetOrderByIdConfig(BaseModel):
    """Get an order by id."""

    operation: Literal["get_order_by_id"] = Field(
        "get_order_by_id",
        json_schema_extra={
            "const": "get_order_by_id", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Get Order",
        },
        title="Get Order",
    )
    order_id: str = Field(..., title="Order ID")
    alt_id: str = Field(..., title="Alt ID", description="Location or agency id")
    location_id: Optional[str] = Field(None, title="Location ID")


class GHLRecordOrderPaymentConfig(BaseModel):
    """Record a manual payment against an order."""

    operation: Literal["record_order_payment"] = Field(
        "record_order_payment",
        json_schema_extra={
            "const": "record_order_payment", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Record Order Payment",
        },
        title="Record Order Payment",
    )
    order_id: str = Field(..., title="Order ID")
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    mode: Optional[str] = Field(
        None, title="Mode",
        json_schema_extra={
            "enum": ["cash", "card", "cheque", "bank_transfer", "other"],
            "x-enum-searchable": True,
        },
    )
    card: Optional[str] = Field(None, title="Card", description="Card details (JSON object)")
    cheque: Optional[str] = Field(None, title="Cheque", description="Cheque details (JSON object)")
    notes: Optional[str] = Field(None, title="Notes")
    amount: Optional[str] = Field(None, title="Amount")
    meta: Optional[str] = Field(None, title="Meta", description="Metadata (JSON object)")
    is_partial_payment: Optional[str] = Field(
        None, title="Is Partial Payment",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLCreateOrderFulfillmentConfig(BaseModel):
    """Create a fulfillment for an order."""

    operation: Literal["create_order_fulfillment"] = Field(
        "create_order_fulfillment",
        json_schema_extra={
            "const": "create_order_fulfillment", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Create Order Fulfillment",
        },
        title="Create Order Fulfillment",
    )
    order_id: str = Field(..., title="Order ID")
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    trackings: Optional[str] = Field(
        None, title="Trackings",
        description="Array of tracking objects (JSON: [{trackingNumber, shippingCarrier, trackingUrl}])",
    )
    items: Optional[str] = Field(
        None, title="Items",
        description="Array of fulfillment items (JSON: [{priceId, qty}])",
    )
    notify_customer: Optional[str] = Field(
        None, title="Notify Customer",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLListOrderFulfillmentConfig(BaseModel):
    """List fulfillments for an order."""

    operation: Literal["list_order_fulfillment"] = Field(
        "list_order_fulfillment",
        json_schema_extra={
            "const": "list_order_fulfillment", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "List Order Fulfillments",
        },
        title="List Order Fulfillments",
    )
    order_id: str = Field(..., title="Order ID")
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )


class GHLListOrderNotesConfig(BaseModel):
    """List notes for an order."""

    operation: Literal["list_order_notes"] = Field(
        "list_order_notes",
        json_schema_extra={
            "const": "list_order_notes", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "List Order Notes",
        },
        title="List Order Notes",
    )
    order_id: str = Field(..., title="Order ID")
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )


class GHLListTransactionsConfig(BaseModel):
    """List transactions."""

    operation: Literal["list_transactions"] = Field(
        "list_transactions",
        json_schema_extra={
            "const": "list_transactions", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "List Transactions",
        },
        title="List Transactions",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location or agency id")
    alt_type: Optional[str] = Field(None, title="Alt Type")
    location_id: Optional[str] = Field(None, title="Location ID")
    payment_mode: Optional[str] = Field(None, title="Payment Mode")
    start_at: Optional[str] = Field(None, title="Start At")
    end_at: Optional[str] = Field(None, title="End At")
    entity_source_type: Optional[str] = Field(None, title="Entity Source Type")
    entity_source_sub_type: Optional[str] = Field(None, title="Entity Source Sub Type")
    search: Optional[str] = Field(None, title="Search")
    subscription_id: Optional[str] = Field(None, title="Subscription ID")
    entity_id: Optional[str] = Field(None, title="Entity ID")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    limit: Optional[str] = Field(None, title="Limit")
    offset: Optional[str] = Field(None, title="Offset")


class GHLGetTransactionByIdConfig(BaseModel):
    """Get a transaction by id."""

    operation: Literal["get_transaction_by_id"] = Field(
        "get_transaction_by_id",
        json_schema_extra={
            "const": "get_transaction_by_id", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Get Transaction",
        },
        title="Get Transaction",
    )
    transaction_id: str = Field(..., title="Transaction ID")
    alt_id: str = Field(..., title="Alt ID", description="Location or agency id")
    alt_type: Optional[str] = Field(None, title="Alt Type")
    location_id: Optional[str] = Field(None, title="Location ID")


class GHLListSubscriptionsConfig(BaseModel):
    """List subscriptions."""

    operation: Literal["list_subscriptions"] = Field(
        "list_subscriptions",
        json_schema_extra={
            "const": "list_subscriptions", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "List Subscriptions",
        },
        title="List Subscriptions",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    entity_id: Optional[str] = Field(None, title="Entity ID")
    payment_mode: Optional[str] = Field(None, title="Payment Mode")
    start_at: Optional[str] = Field(None, title="Start At")
    end_at: Optional[str] = Field(None, title="End At")
    entity_source_type: Optional[str] = Field(None, title="Entity Source Type")
    search: Optional[str] = Field(None, title="Search")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    id: Optional[str] = Field(None, title="ID")
    limit: Optional[str] = Field(None, title="Limit")
    offset: Optional[str] = Field(None, title="Offset")
    get_payments_collected_count: Optional[str] = Field(
        None, title="Get Payments Collected Count",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLGetSubscriptionByIdConfig(BaseModel):
    """Get a subscription by id."""

    operation: Literal["get_subscription_by_id"] = Field(
        "get_subscription_by_id",
        json_schema_extra={
            "const": "get_subscription_by_id", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Get Subscription",
        },
        title="Get Subscription",
    )
    subscription_id: str = Field(..., title="Subscription ID")
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )


class GHLListCouponsConfig(BaseModel):
    """List coupons."""

    operation: Literal["list_coupons"] = Field(
        "list_coupons",
        json_schema_extra={
            "const": "list_coupons", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "List Coupons",
        },
        title="List Coupons",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    limit: Optional[str] = Field(None, title="Limit")
    offset: Optional[str] = Field(None, title="Offset")
    status: Optional[str] = Field(
        None, title="Status",
        json_schema_extra={
            "enum": ["scheduled", "active", "expired"], "x-enum-searchable": True,
        },
    )
    search: Optional[str] = Field(None, title="Search")


class GHLCreateCouponConfig(BaseModel):
    """Create a coupon."""

    operation: Literal["create_coupon"] = Field(
        "create_coupon",
        json_schema_extra={
            "const": "create_coupon", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Create Coupon",
        },
        title="Create Coupon",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    name: str = Field(..., title="Name")
    code: str = Field(..., title="Code")
    discount_type: Optional[str] = Field(
        None, title="Discount Type",
        json_schema_extra={
            "enum": ["percentage", "amount"], "x-enum-searchable": True,
        },
    )
    discount_value: Optional[str] = Field(None, title="Discount Value")
    start_date: str = Field(..., title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")
    usage_limit: Optional[str] = Field(None, title="Usage Limit")
    product_ids: Optional[str] = Field(
        None, title="Product IDs", description="Comma-separated product ids",
    )
    apply_to_future_payments: Optional[str] = Field(
        None, title="Apply To Future Payments",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    apply_to_future_payments_config: Optional[str] = Field(
        None, title="Apply To Future Payments Config",
        description="Config object (JSON)",
    )
    limit_per_customer: Optional[str] = Field(
        None, title="Limit Per Customer",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLUpdateCouponConfig(BaseModel):
    """Update a coupon."""

    operation: Literal["update_coupon"] = Field(
        "update_coupon",
        json_schema_extra={
            "const": "update_coupon", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Update Coupon",
        },
        title="Update Coupon",
    )
    id: str = Field(..., title="Coupon ID")
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    name: str = Field(..., title="Name")
    code: str = Field(..., title="Code")
    discount_type: Optional[str] = Field(
        None, title="Discount Type",
        json_schema_extra={
            "enum": ["percentage", "amount"], "x-enum-searchable": True,
        },
    )
    discount_value: Optional[str] = Field(None, title="Discount Value")
    start_date: str = Field(..., title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")
    usage_limit: Optional[str] = Field(None, title="Usage Limit")
    product_ids: Optional[str] = Field(
        None, title="Product IDs", description="Comma-separated product ids",
    )
    apply_to_future_payments: Optional[str] = Field(
        None, title="Apply To Future Payments",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    apply_to_future_payments_config: Optional[str] = Field(
        None, title="Apply To Future Payments Config",
        description="Config object (JSON)",
    )
    limit_per_customer: Optional[str] = Field(
        None, title="Limit Per Customer",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLDeleteCouponConfig(BaseModel):
    """Delete a coupon."""

    operation: Literal["delete_coupon"] = Field(
        "delete_coupon",
        json_schema_extra={
            "const": "delete_coupon", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Delete Coupon",
        },
        title="Delete Coupon",
    )
    id: str = Field(..., title="Coupon ID")
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )


class GHLGetCouponConfig(BaseModel):
    """Get a coupon by id or code."""

    operation: Literal["get_coupon"] = Field(
        "get_coupon",
        json_schema_extra={
            "const": "get_coupon", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Get Coupon",
        },
        title="Get Coupon",
    )
    alt_id: str = Field(..., title="Alt ID", description="Location id (sub-account)")
    alt_type: Optional[str] = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    id: str = Field(..., title="Coupon ID")
    code: str = Field(..., title="Code")


class GHLCreateCustomProviderIntegrationConfig(BaseModel):
    """Create a custom payment provider integration."""

    operation: Literal["create_custom_provider_integration"] = Field(
        "create_custom_provider_integration",
        json_schema_extra={
            "const": "create_custom_provider_integration", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Create Custom Provider Integration",
        },
        title="Create Custom Provider Integration",
    )
    location_id: str = Field(..., title="Location ID")
    name: str = Field(..., title="Name")
    description: str = Field(..., title="Description")
    payments_url: str = Field(..., title="Payments URL")
    query_url: str = Field(..., title="Query URL")
    image_url: str = Field(..., title="Image URL")
    supports_subscription_schedule: Optional[str] = Field(
        None, title="Supports Subscription Schedule",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLDeleteCustomProviderIntegrationConfig(BaseModel):
    """Delete a custom payment provider integration."""

    operation: Literal["delete_custom_provider_integration"] = Field(
        "delete_custom_provider_integration",
        json_schema_extra={
            "const": "delete_custom_provider_integration", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Delete Custom Provider Integration",
        },
        title="Delete Custom Provider Integration",
    )
    location_id: str = Field(..., title="Location ID")


class GHLFetchCustomProviderConfigConfig(BaseModel):
    """Fetch a custom payment provider's connect config."""

    operation: Literal["fetch_custom_provider_config"] = Field(
        "fetch_custom_provider_config",
        json_schema_extra={
            "const": "fetch_custom_provider_config", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Fetch Custom Provider Config",
        },
        title="Fetch Custom Provider Config",
    )
    location_id: str = Field(..., title="Location ID")


class GHLCreateCustomProviderConfigConfig(BaseModel):
    """Create a custom payment provider's connect config (live/test keys)."""

    operation: Literal["create_custom_provider_config"] = Field(
        "create_custom_provider_config",
        json_schema_extra={
            "const": "create_custom_provider_config", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Create Custom Provider Config",
        },
        title="Create Custom Provider Config",
    )
    location_id: str = Field(..., title="Location ID")
    live: str = Field(
        ..., title="Live Config",
        description="Live-mode config object (JSON: {apiKey, publishableKey})",
    )
    test: str = Field(
        ..., title="Test Config",
        description="Test-mode config object (JSON: {apiKey, publishableKey})",
    )


class GHLDisconnectCustomProviderConfigConfig(BaseModel):
    """Disconnect a custom payment provider's connect config."""

    operation: Literal["disconnect_custom_provider_config"] = Field(
        "disconnect_custom_provider_config",
        json_schema_extra={
            "const": "disconnect_custom_provider_config", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Disconnect Custom Provider Config",
        },
        title="Disconnect Custom Provider Config",
    )
    location_id: str = Field(..., title="Location ID")
    live_mode: Optional[str] = Field(
        None, title="Live Mode",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class GHLUpdateCustomProviderCapabilitiesConfig(BaseModel):
    """Update a custom payment provider marketplace app's capabilities."""

    operation: Literal["update_custom_provider_capabilities"] = Field(
        "update_custom_provider_capabilities",
        json_schema_extra={
            "const": "update_custom_provider_capabilities", "ui:hidden": True,
            "x-category": "Payments", "x-is-trigger": False,
            "x-display-name": "Update Custom Provider Capabilities",
        },
        title="Update Custom Provider Capabilities",
    )
    supports_subscription_schedules: Optional[str] = Field(
        None, title="Supports Subscription Schedules",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    company_id: Optional[str] = Field(None, title="Company ID")
    location_id: Optional[str] = Field(None, title="Location ID")


async def _create_whitelabel_integration_provider(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "uniqueName": c.unique_name,
        "title": c.title, "provider": c.provider, "description": c.description,
        "imageUrl": c.image_url,
    }
    return await node._request(
        token, "POST", "/payments/integrations/provider/whitelabel",
        json_body=body, action_name="create_whitelabel_integration_provider",
    )


async def _list_whitelabel_integration_providers(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "limit": c.limit, "offset": c.offset,
    }
    return await node._request(
        token, "GET", "/payments/integrations/provider/whitelabel",
        params=params, action_name="list_whitelabel_integration_providers",
    )


async def _list_orders(node, c, token):
    params = {
        "altId": c.alt_id, "locationId": c.location_id, "status": c.status,
        "paymentStatus": c.payment_status, "paymentMode": c.payment_mode,
        "startAt": c.start_at, "endAt": c.end_at, "search": c.search,
        "contactId": c.contact_id, "funnelProductIds": c.funnel_product_ids,
        "sourceId": c.source_id, "limit": c.limit, "offset": c.offset,
    }
    return await node._request(
        token, "GET", "/payments/orders", params=params, action_name="list_orders",
    )


async def _get_order_by_id(node, c, token):
    params = {"altId": c.alt_id, "locationId": c.location_id}
    return await node._request(
        token, "GET", f"/payments/orders/{c.order_id}",
        params=params, action_name="get_order_by_id",
    )


async def _record_order_payment(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "mode": c.mode,
        "card": _ghl_json(c.card), "cheque": _ghl_json(c.cheque), "notes": c.notes,
        "amount": _ghl_num(c.amount), "meta": _ghl_json(c.meta),
        "isPartialPayment": _ghl_bool(c.is_partial_payment),
    }
    return await node._request(
        token, "POST", f"/payments/orders/{c.order_id}/record-payment",
        json_body=body, action_name="record_order_payment",
    )


async def _create_order_fulfillment(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type,
        "trackings": _ghl_json(c.trackings), "items": _ghl_json(c.items),
        "notifyCustomer": _ghl_bool(c.notify_customer),
    }
    return await node._request(
        token, "POST", f"/payments/orders/{c.order_id}/fulfillments",
        json_body=body, action_name="create_order_fulfillment",
    )


async def _list_order_fulfillment(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(
        token, "GET", f"/payments/orders/{c.order_id}/fulfillments",
        params=params, action_name="list_order_fulfillment",
    )


async def _list_order_notes(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(
        token, "GET", f"/payments/orders/{c.order_id}/notes",
        params=params, action_name="list_order_notes",
    )


async def _list_transactions(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "locationId": c.location_id,
        "paymentMode": c.payment_mode, "startAt": c.start_at, "endAt": c.end_at,
        "entitySourceType": c.entity_source_type,
        "entitySourceSubType": c.entity_source_sub_type, "search": c.search,
        "subscriptionId": c.subscription_id, "entityId": c.entity_id,
        "contactId": c.contact_id, "limit": c.limit, "offset": c.offset,
    }
    return await node._request(
        token, "GET", "/payments/transactions",
        params=params, action_name="list_transactions",
    )


async def _get_transaction_by_id(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type, "locationId": c.location_id}
    return await node._request(
        token, "GET", f"/payments/transactions/{c.transaction_id}",
        params=params, action_name="get_transaction_by_id",
    )


async def _list_subscriptions(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "entityId": c.entity_id,
        "paymentMode": c.payment_mode, "startAt": c.start_at, "endAt": c.end_at,
        "entitySourceType": c.entity_source_type, "search": c.search,
        "contactId": c.contact_id, "id": c.id, "limit": c.limit, "offset": c.offset,
        "getPaymentsCollectedCount": _ghl_bool(c.get_payments_collected_count),
    }
    return await node._request(
        token, "GET", "/payments/subscriptions",
        params=params, action_name="list_subscriptions",
    )


async def _get_subscription_by_id(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(
        token, "GET", f"/payments/subscriptions/{c.subscription_id}",
        params=params, action_name="get_subscription_by_id",
    )


async def _list_coupons(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "limit": c.limit,
        "offset": c.offset, "status": c.status, "search": c.search,
    }
    return await node._request(
        token, "GET", "/payments/coupon/list",
        params=params, action_name="list_coupons",
    )


async def _create_coupon(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name, "code": c.code,
        "discountType": c.discount_type, "discountValue": _ghl_num(c.discount_value),
        "startDate": c.start_date, "endDate": c.end_date,
        "usageLimit": _ghl_num(c.usage_limit), "productIds": _ghl_csv(c.product_ids),
        "applyToFuturePayments": _ghl_bool(c.apply_to_future_payments),
        "applyToFuturePaymentsConfig": _ghl_json(c.apply_to_future_payments_config),
        "limitPerCustomer": _ghl_bool(c.limit_per_customer),
    }
    return await node._request(
        token, "POST", "/payments/coupon", json_body=body, action_name="create_coupon",
    )


async def _update_coupon(node, c, token):
    body = {
        "id": c.id, "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "code": c.code, "discountType": c.discount_type,
        "discountValue": _ghl_num(c.discount_value), "startDate": c.start_date,
        "endDate": c.end_date, "usageLimit": _ghl_num(c.usage_limit),
        "productIds": _ghl_csv(c.product_ids),
        "applyToFuturePayments": _ghl_bool(c.apply_to_future_payments),
        "applyToFuturePaymentsConfig": _ghl_json(c.apply_to_future_payments_config),
        "limitPerCustomer": _ghl_bool(c.limit_per_customer),
    }
    return await node._request(
        token, "PUT", "/payments/coupon", json_body=body, action_name="update_coupon",
    )


async def _delete_coupon(node, c, token):
    body = {"id": c.id, "altId": c.alt_id, "altType": c.alt_type}
    return await node._request(
        token, "DELETE", "/payments/coupon", json_body=body, action_name="delete_coupon",
    )


async def _get_coupon(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type, "id": c.id, "code": c.code}
    return await node._request(
        token, "GET", "/payments/coupon", params=params, action_name="get_coupon",
    )


async def _create_custom_provider_integration(node, c, token):
    params = {"locationId": c.location_id}
    body = {
        "name": c.name, "description": c.description, "paymentsUrl": c.payments_url,
        "queryUrl": c.query_url, "imageUrl": c.image_url,
        "supportsSubscriptionSchedule": _ghl_bool(c.supports_subscription_schedule),
    }
    return await node._request(
        token, "POST", "/payments/custom-provider/provider",
        params=params, json_body=body, action_name="create_custom_provider_integration",
    )


async def _delete_custom_provider_integration(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "DELETE", "/payments/custom-provider/provider",
        params=params, action_name="delete_custom_provider_integration",
    )


async def _fetch_custom_provider_config(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(
        token, "GET", "/payments/custom-provider/connect",
        params=params, action_name="fetch_custom_provider_config",
    )


async def _create_custom_provider_config(node, c, token):
    params = {"locationId": c.location_id}
    body = {"live": _ghl_json(c.live), "test": _ghl_json(c.test)}
    return await node._request(
        token, "POST", "/payments/custom-provider/connect",
        params=params, json_body=body, action_name="create_custom_provider_config",
    )


async def _disconnect_custom_provider_config(node, c, token):
    params = {"locationId": c.location_id}
    body = {"liveMode": _ghl_bool(c.live_mode)}
    return await node._request(
        token, "POST", "/payments/custom-provider/disconnect",
        params=params, json_body=body, action_name="disconnect_custom_provider_config",
    )


async def _update_custom_provider_capabilities(node, c, token):
    body = {
        "supportsSubscriptionSchedules": _ghl_bool(c.supports_subscription_schedules),
        "companyId": c.company_id, "locationId": c.location_id,
    }
    return await node._request(
        token, "PUT", "/payments/custom-provider/capabilities",
        json_body=body, action_name="update_custom_provider_capabilities",
    )


GHL_OPERATION_CONFIGS += [
    GHLCreateWhitelabelIntegrationProviderConfig,
    GHLListWhitelabelIntegrationProvidersConfig,
    GHLListOrdersConfig,
    GHLGetOrderByIdConfig,
    GHLRecordOrderPaymentConfig,
    GHLCreateOrderFulfillmentConfig,
    GHLListOrderFulfillmentConfig,
    GHLListOrderNotesConfig,
    GHLListTransactionsConfig,
    GHLGetTransactionByIdConfig,
    GHLListSubscriptionsConfig,
    GHLGetSubscriptionByIdConfig,
    GHLListCouponsConfig,
    GHLCreateCouponConfig,
    GHLUpdateCouponConfig,
    GHLDeleteCouponConfig,
    GHLGetCouponConfig,
    GHLCreateCustomProviderIntegrationConfig,
    GHLDeleteCustomProviderIntegrationConfig,
    GHLFetchCustomProviderConfigConfig,
    GHLCreateCustomProviderConfigConfig,
    GHLDisconnectCustomProviderConfigConfig,
    GHLUpdateCustomProviderCapabilitiesConfig,
]
GHL_OPERATION_HANDLERS.update({
    "create_whitelabel_integration_provider": _create_whitelabel_integration_provider,
    "list_whitelabel_integration_providers": _list_whitelabel_integration_providers,
    "list_orders": _list_orders,
    "get_order_by_id": _get_order_by_id,
    "record_order_payment": _record_order_payment,
    "create_order_fulfillment": _create_order_fulfillment,
    "list_order_fulfillment": _list_order_fulfillment,
    "list_order_notes": _list_order_notes,
    "list_transactions": _list_transactions,
    "get_transaction_by_id": _get_transaction_by_id,
    "list_subscriptions": _list_subscriptions,
    "get_subscription_by_id": _get_subscription_by_id,
    "list_coupons": _list_coupons,
    "create_coupon": _create_coupon,
    "update_coupon": _update_coupon,
    "delete_coupon": _delete_coupon,
    "get_coupon": _get_coupon,
    "create_custom_provider_integration": _create_custom_provider_integration,
    "delete_custom_provider_integration": _delete_custom_provider_integration,
    "fetch_custom_provider_config": _fetch_custom_provider_config,
    "create_custom_provider_config": _create_custom_provider_config,
    "disconnect_custom_provider_config": _disconnect_custom_provider_config,
    "update_custom_provider_capabilities": _update_custom_provider_capabilities,
})


# ---- phone_system.py ----
class GHLGetNumberPoolListConfig(BaseModel):
    """List phone number pools for a location."""

    operation: Literal["get_number_pool_list"] = Field(
        "get_number_pool_list",
        json_schema_extra={
            "const": "get_number_pool_list", "ui:hidden": True,
            "x-category": "Phone System", "x-is-trigger": False,
            "x-display-name": "List Number Pools",
        },
        title="List Number Pools",
    )
    location_id: Optional[str] = Field(None, title="Location ID", description="Sub-account (location) id")


class GHLListAvailableNumbersConfig(BaseModel):
    """List available phone numbers to purchase for a location."""

    operation: Literal["list_available_numbers"] = Field(
        "list_available_numbers",
        json_schema_extra={
            "const": "list_available_numbers", "ui:hidden": True,
            "x-category": "Phone System", "x-is-trigger": False,
            "x-display-name": "List Available Numbers",
        },
        title="List Available Numbers",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    country_code: str = Field(..., title="Country Code", description="ISO 3166-1 alpha-2 country code")
    number_types: Optional[str] = Field(None, title="Number Types", description="Type(s) of phone number")
    first_part: Optional[str] = Field(None, title="First Part", description="Match the beginning of the number")
    last_part: Optional[str] = Field(None, title="Last Part", description="Match the end of the number")
    anywhere: Optional[str] = Field(None, title="Anywhere", description="Match anywhere in the number")
    sms_enabled: Optional[str] = Field(
        None, title="SMS Enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    mms_enabled: Optional[str] = Field(
        None, title="MMS Enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    voice_enabled: Optional[str] = Field(
        None, title="Voice Enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLPurchasePhoneNumberConfig(BaseModel):
    """Purchase a phone number for a location."""

    operation: Literal["purchase_phone_number"] = Field(
        "purchase_phone_number",
        json_schema_extra={
            "const": "purchase_phone_number", "ui:hidden": True,
            "x-category": "Phone System", "x-is-trigger": False,
            "x-display-name": "Purchase Phone Number",
        },
        title="Purchase Phone Number",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    phone_number: str = Field(..., title="Phone Number", description="The phone number to purchase")
    country_code: Optional[str] = Field(None, title="Country Code", description="ISO 3166-1 alpha-2 country code")
    number_type: Optional[str] = Field(
        None, title="Number Type", description="Type of phone number",
        json_schema_extra={
            "enum": ["local", "tollFree", "mobile"],
            "enumNames": ["Local", "Toll Free", "Mobile"], "x-enum-searchable": True,
        },
    )
    address_sid: Optional[str] = Field(None, title="Address SID", description="Twilio address SID for compliance")
    bundle_sid: Optional[str] = Field(None, title="Bundle SID", description="Twilio bundle SID for regulatory compliance")
    locality: Optional[str] = Field(None, title="Locality", description="Locality where the number is being purchased")
    region: Optional[str] = Field(None, title="Region", description="Region where the number is being purchased")
    fingerprint_id: Optional[str] = Field(None, title="Fingerprint ID", description="Unique request ID for idempotency")
    skip_location_kyc: Optional[str] = Field(
        None, title="Skip Location KYC", description="Skip location-level KYC verification if applicable",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLListActiveNumbersConfig(BaseModel):
    """List active phone numbers for a location."""

    operation: Literal["list_active_numbers"] = Field(
        "list_active_numbers",
        json_schema_extra={
            "const": "list_active_numbers", "ui:hidden": True,
            "x-category": "Phone System", "x-is-trigger": False,
            "x-display-name": "List Active Numbers",
        },
        title="List Active Numbers",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    page_size: Optional[str] = Field(None, title="Page Size", description="Number of results per page")
    page: Optional[str] = Field(None, title="Page", description="Page number (pagination)")
    search_filter: Optional[str] = Field(None, title="Search Filter", description="Filter numbers by search term")
    skip_number_pool: Optional[str] = Field(
        None, title="Skip Number Pool", description="Exclude number-pool numbers",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


async def _get_number_pool_list(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", "/phone-system/number-pools", params=params, action_name="get_number_pool_list")


async def _list_available_numbers(node, c, token):
    params = {
        "countryCode": c.country_code, "numberTypes": c.number_types, "firstPart": c.first_part,
        "lastPart": c.last_part, "anywhere": c.anywhere, "smsEnabled": _ghl_bool(c.sms_enabled),
        "mmsEnabled": _ghl_bool(c.mms_enabled), "voiceEnabled": _ghl_bool(c.voice_enabled),
    }
    return await node._request(
        token, "GET", f"/phone-system/numbers/location/{c.location_id}/available",
        params=params, action_name="list_available_numbers",
    )


async def _purchase_phone_number(node, c, token):
    body = {
        "phoneNumber": c.phone_number, "countryCode": c.country_code, "numberType": c.number_type,
        "addressSid": c.address_sid, "bundleSid": c.bundle_sid, "locality": c.locality,
        "region": c.region, "fingerprintId": c.fingerprint_id,
        "skipLocationKYC": _ghl_bool(c.skip_location_kyc),
    }
    return await node._request(
        token, "POST", f"/phone-system/numbers/location/{c.location_id}/purchase",
        json_body=body, action_name="purchase_phone_number",
    )


async def _list_active_numbers(node, c, token):
    params = {
        "pageSize": _ghl_num(c.page_size), "page": _ghl_num(c.page),
        "searchFilter": c.search_filter, "skipNumberPool": _ghl_bool(c.skip_number_pool),
    }
    return await node._request(
        token, "GET", f"/phone-system/numbers/location/{c.location_id}",
        params=params, action_name="list_active_numbers",
    )


GHL_OPERATION_CONFIGS += [
    GHLGetNumberPoolListConfig,
    GHLListAvailableNumbersConfig,
    GHLPurchasePhoneNumberConfig,
    GHLListActiveNumbersConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_number_pool_list": _get_number_pool_list,
    "list_available_numbers": _list_available_numbers,
    "purchase_phone_number": _purchase_phone_number,
    "list_active_numbers": _list_active_numbers,
})


# ---- products.py ----
class GHLListProductsConfig(BaseModel):
    """List products for a location (sub-account)."""

    operation: Literal["list_products"] = Field(
        "list_products",
        json_schema_extra={
            "const": "list_products", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "List Products",
        },
        title="List Products",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Pagination offset")
    search: Optional[str] = Field(None, title="Search", description="Search term")
    collection_ids: Optional[str] = Field(None, title="Collection IDs", description="Comma-separated collection ids")
    collection_slug: Optional[str] = Field(None, title="Collection Slug")
    expand: Optional[str] = Field(None, title="Expand", description="Comma-separated list of fields to expand")
    product_ids: Optional[str] = Field(None, title="Product IDs", description="Comma-separated product ids")
    store_id: Optional[str] = Field(None, title="Store ID")
    included_in_store: Optional[str] = Field(
        None, title="Included In Store",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    available_in_store: Optional[str] = Field(
        None, title="Available In Store",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    sort_order: Optional[str] = Field(
        None, title="Sort Order",
        json_schema_extra={"enum": ["asc", "desc"], "x-enum-searchable": True},
    )


class GHLCreateProductConfig(BaseModel):
    """Create a product."""

    operation: Literal["create_product"] = Field(
        "create_product",
        json_schema_extra={
            "const": "create_product", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Create Product",
        },
        title="Create Product",
    )
    name: str = Field(..., title="Name", description="Product name")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    product_type: str = Field(
        ..., title="Product Type",
        json_schema_extra={"enum": ["DIGITAL", "PHYSICAL", "SERVICE", "PHYSICAL/DIGITAL"], "x-enum-searchable": True},
    )
    description: Optional[str] = Field(None, title="Description")
    image: Optional[str] = Field(None, title="Image", description="Image URL")
    statement_descriptor: Optional[str] = Field(None, title="Statement Descriptor")
    available_in_store: Optional[str] = Field(
        None, title="Available In Store",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    medias: Optional[str] = Field(None, title="Medias", description="JSON array of media objects")
    variants: Optional[str] = Field(None, title="Variants", description="JSON array of variant objects")
    collection_ids: Optional[str] = Field(None, title="Collection IDs", description="Comma-separated collection ids")
    is_taxes_enabled: Optional[str] = Field(
        None, title="Taxes Enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    taxes: Optional[str] = Field(None, title="Taxes", description="Comma-separated tax ids")
    automatic_tax_category_id: Optional[str] = Field(None, title="Automatic Tax Category ID")
    is_label_enabled: Optional[str] = Field(
        None, title="Label Enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    label: Optional[str] = Field(None, title="Label", description="JSON label object")
    slug: Optional[str] = Field(None, title="Slug")
    seo: Optional[str] = Field(None, title="SEO", description="JSON SEO object")
    tax_inclusive: Optional[str] = Field(
        None, title="Tax Inclusive",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLGetProductConfig(BaseModel):
    """Get a product by id."""

    operation: Literal["get_product"] = Field(
        "get_product",
        json_schema_extra={
            "const": "get_product", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Get Product",
        },
        title="Get Product",
    )
    product_id: str = Field(..., title="Product ID", description="The product to fetch")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    send_wishlist_status: Optional[str] = Field(
        None, title="Send Wishlist Status",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLUpdateProductConfig(BaseModel):
    """Update a product by id."""

    operation: Literal["update_product"] = Field(
        "update_product",
        json_schema_extra={
            "const": "update_product", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Update Product",
        },
        title="Update Product",
    )
    product_id: str = Field(..., title="Product ID", description="The product to update")
    name: str = Field(..., title="Name", description="Product name")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    product_type: str = Field(
        ..., title="Product Type",
        json_schema_extra={"enum": ["DIGITAL", "PHYSICAL", "SERVICE", "PHYSICAL/DIGITAL"], "x-enum-searchable": True},
    )
    description: Optional[str] = Field(None, title="Description")
    image: Optional[str] = Field(None, title="Image", description="Image URL")
    statement_descriptor: Optional[str] = Field(None, title="Statement Descriptor")
    available_in_store: Optional[str] = Field(
        None, title="Available In Store",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    medias: Optional[str] = Field(None, title="Medias", description="JSON array of media objects")
    variants: Optional[str] = Field(None, title="Variants", description="JSON array of variant objects")
    collection_ids: Optional[str] = Field(None, title="Collection IDs", description="Comma-separated collection ids")
    is_taxes_enabled: Optional[str] = Field(
        None, title="Taxes Enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    taxes: Optional[str] = Field(None, title="Taxes", description="Comma-separated tax ids")
    automatic_tax_category_id: Optional[str] = Field(None, title="Automatic Tax Category ID")
    is_label_enabled: Optional[str] = Field(
        None, title="Label Enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    label: Optional[str] = Field(None, title="Label", description="JSON label object")
    slug: Optional[str] = Field(None, title="Slug")
    seo: Optional[str] = Field(None, title="SEO", description="JSON SEO object")
    tax_inclusive: Optional[str] = Field(
        None, title="Tax Inclusive",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    prices: Optional[str] = Field(None, title="Prices", description="Comma-separated price ids")


class GHLDeleteProductConfig(BaseModel):
    """Delete a product by id."""

    operation: Literal["delete_product"] = Field(
        "delete_product",
        json_schema_extra={
            "const": "delete_product", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Delete Product",
        },
        title="Delete Product",
    )
    product_id: str = Field(..., title="Product ID", description="The product to delete")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    send_wishlist_status: Optional[str] = Field(
        None, title="Send Wishlist Status",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLBulkUpdateProductsConfig(BaseModel):
    """Bulk update products (price/availability/collection/currency/delete)."""

    operation: Literal["bulk_update_products"] = Field(
        "bulk_update_products",
        json_schema_extra={
            "const": "bulk_update_products", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Bulk Update Products",
        },
        title="Bulk Update Products",
    )
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    type: str = Field(
        ..., title="Type",
        json_schema_extra={
            "enum": [
                "bulk-update-price", "bulk-update-availability",
                "bulk-update-product-collection", "bulk-delete-products", "bulk-update-currency",
            ],
            "x-enum-searchable": True,
        },
    )
    product_ids: str = Field(..., title="Product IDs", description="Comma-separated product ids")
    filters: Optional[str] = Field(None, title="Filters", description="JSON filters object")
    price: Optional[str] = Field(None, title="Price", description="JSON price object")
    compare_at_price: Optional[str] = Field(None, title="Compare At Price", description="JSON compareAtPrice object")
    availability: Optional[str] = Field(
        None, title="Availability",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    collection_ids: Optional[str] = Field(None, title="Collection IDs", description="Comma-separated collection ids")
    currency: Optional[str] = Field(None, title="Currency")


class GHLBulkEditProductsConfig(BaseModel):
    """Bulk edit products (upsert list of product objects)."""

    operation: Literal["bulk_edit_products"] = Field(
        "bulk_edit_products",
        json_schema_extra={
            "const": "bulk_edit_products", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Bulk Edit Products",
        },
        title="Bulk Edit Products",
    )
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    products: str = Field(..., title="Products", description="JSON array of product objects")


class GHLCreatePriceForProductConfig(BaseModel):
    """Create a price for a product."""

    operation: Literal["create_price_for_product"] = Field(
        "create_price_for_product",
        json_schema_extra={
            "const": "create_price_for_product", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Create Price For Product",
        },
        title="Create Price For Product",
    )
    product_id: str = Field(..., title="Product ID", description="The product to add a price to")
    name: str = Field(..., title="Name", description="Price name")
    type: str = Field(
        ..., title="Type",
        json_schema_extra={"enum": ["one_time", "recurring"], "x-enum-searchable": True},
    )
    currency: str = Field(..., title="Currency")
    amount: str = Field(..., title="Amount", description="Price amount (number)")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    recurring: Optional[str] = Field(None, title="Recurring", description="JSON recurring object")
    description: Optional[str] = Field(None, title="Description")
    membership_offers: Optional[str] = Field(None, title="Membership Offers", description="JSON array of membership offers")
    trial_period: Optional[str] = Field(None, title="Trial Period", description="Trial period (number)")
    total_cycles: Optional[str] = Field(None, title="Total Cycles", description="Total cycles (number)")
    setup_fee: Optional[str] = Field(None, title="Setup Fee", description="Setup fee (number)")
    variant_option_ids: Optional[str] = Field(None, title="Variant Option IDs", description="Comma-separated variant option ids")
    compare_at_price: Optional[str] = Field(None, title="Compare At Price", description="Compare-at price (number)")
    user_id: Optional[str] = Field(None, title="User ID")
    meta: Optional[str] = Field(None, title="Meta", description="JSON meta object")
    track_inventory: Optional[str] = Field(
        None, title="Track Inventory",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    available_quantity: Optional[str] = Field(None, title="Available Quantity", description="Available quantity (number)")
    allow_out_of_stock_purchases: Optional[str] = Field(
        None, title="Allow Out Of Stock Purchases",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    sku: Optional[str] = Field(None, title="SKU")
    shipping_options: Optional[str] = Field(None, title="Shipping Options", description="JSON shipping options object")
    is_digital_product: Optional[str] = Field(
        None, title="Is Digital Product",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    digital_delivery: Optional[str] = Field(None, title="Digital Delivery", description="Comma-separated digital delivery entries")


class GHLListPricesForProductConfig(BaseModel):
    """List prices for a product."""

    operation: Literal["list_prices_for_product"] = Field(
        "list_prices_for_product",
        json_schema_extra={
            "const": "list_prices_for_product", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "List Prices For Product",
        },
        title="List Prices For Product",
    )
    product_id: str = Field(..., title="Product ID", description="The product whose prices to list")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    limit: Optional[str] = Field(None, title="Limit")
    offset: Optional[str] = Field(None, title="Offset")
    ids: Optional[str] = Field(None, title="IDs", description="Comma-separated price ids")


class GHLGetPriceForProductConfig(BaseModel):
    """Get a price by id for a product."""

    operation: Literal["get_price_for_product"] = Field(
        "get_price_for_product",
        json_schema_extra={
            "const": "get_price_for_product", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Get Price For Product",
        },
        title="Get Price For Product",
    )
    product_id: str = Field(..., title="Product ID")
    price_id: str = Field(..., title="Price ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLUpdatePriceForProductConfig(BaseModel):
    """Update a price by id for a product."""

    operation: Literal["update_price_for_product"] = Field(
        "update_price_for_product",
        json_schema_extra={
            "const": "update_price_for_product", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Update Price For Product",
        },
        title="Update Price For Product",
    )
    product_id: str = Field(..., title="Product ID")
    price_id: str = Field(..., title="Price ID")
    name: str = Field(..., title="Name", description="Price name")
    type: str = Field(
        ..., title="Type",
        json_schema_extra={"enum": ["one_time", "recurring"], "x-enum-searchable": True},
    )
    currency: str = Field(..., title="Currency")
    amount: str = Field(..., title="Amount", description="Price amount (number)")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    recurring: Optional[str] = Field(None, title="Recurring", description="JSON recurring object")
    description: Optional[str] = Field(None, title="Description")
    membership_offers: Optional[str] = Field(None, title="Membership Offers", description="JSON array of membership offers")
    trial_period: Optional[str] = Field(None, title="Trial Period", description="Trial period (number)")
    total_cycles: Optional[str] = Field(None, title="Total Cycles", description="Total cycles (number)")
    setup_fee: Optional[str] = Field(None, title="Setup Fee", description="Setup fee (number)")
    variant_option_ids: Optional[str] = Field(None, title="Variant Option IDs", description="Comma-separated variant option ids")
    compare_at_price: Optional[str] = Field(None, title="Compare At Price", description="Compare-at price (number)")
    user_id: Optional[str] = Field(None, title="User ID")
    meta: Optional[str] = Field(None, title="Meta", description="JSON meta object")
    track_inventory: Optional[str] = Field(
        None, title="Track Inventory",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    available_quantity: Optional[str] = Field(None, title="Available Quantity", description="Available quantity (number)")
    allow_out_of_stock_purchases: Optional[str] = Field(
        None, title="Allow Out Of Stock Purchases",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    sku: Optional[str] = Field(None, title="SKU")
    shipping_options: Optional[str] = Field(None, title="Shipping Options", description="JSON shipping options object")
    is_digital_product: Optional[str] = Field(
        None, title="Is Digital Product",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    digital_delivery: Optional[str] = Field(None, title="Digital Delivery", description="Comma-separated digital delivery entries")


class GHLDeletePriceForProductConfig(BaseModel):
    """Delete a price by id for a product."""

    operation: Literal["delete_price_for_product"] = Field(
        "delete_price_for_product",
        json_schema_extra={
            "const": "delete_price_for_product", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Delete Price For Product",
        },
        title="Delete Price For Product",
    )
    product_id: str = Field(..., title="Product ID")
    price_id: str = Field(..., title="Price ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLGetProductInventoryConfig(BaseModel):
    """List product inventory."""

    operation: Literal["get_product_inventory"] = Field(
        "get_product_inventory",
        json_schema_extra={
            "const": "get_product_inventory", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Get Product Inventory",
        },
        title="Get Product Inventory",
    )
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    limit: Optional[str] = Field(None, title="Limit")
    offset: Optional[str] = Field(None, title="Offset")
    search: Optional[str] = Field(None, title="Search")


class GHLUpdateProductInventoryConfig(BaseModel):
    """Update product inventory (list of items)."""

    operation: Literal["update_product_inventory"] = Field(
        "update_product_inventory",
        json_schema_extra={
            "const": "update_product_inventory", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Update Product Inventory",
        },
        title="Update Product Inventory",
    )
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    items: str = Field(..., title="Items", description="JSON array of inventory item objects")


class GHLGetProductStoreStatsConfig(BaseModel):
    """Get product store stats."""

    operation: Literal["get_product_store_stats"] = Field(
        "get_product_store_stats",
        json_schema_extra={
            "const": "get_product_store_stats", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Get Product Store Stats",
        },
        title="Get Product Store Stats",
    )
    store_id: str = Field(..., title="Store ID")
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    search: Optional[str] = Field(None, title="Search")
    collection_ids: Optional[str] = Field(None, title="Collection IDs", description="Comma-separated collection ids")


class GHLUpdateProductStoreStatusConfig(BaseModel):
    """Update store status for products (include/exclude)."""

    operation: Literal["update_product_store_status"] = Field(
        "update_product_store_status",
        json_schema_extra={
            "const": "update_product_store_status", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Update Product Store Status",
        },
        title="Update Product Store Status",
    )
    store_id: str = Field(..., title="Store ID")
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    action: str = Field(
        ..., title="Action",
        json_schema_extra={"enum": ["include", "exclude"], "x-enum-searchable": True},
    )
    product_ids: str = Field(..., title="Product IDs", description="Comma-separated product ids")


class GHLUpdateProductDisplayPriorityConfig(BaseModel):
    """Update product display priority within a store."""

    operation: Literal["update_product_display_priority"] = Field(
        "update_product_display_priority",
        json_schema_extra={
            "const": "update_product_display_priority", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Update Product Display Priority",
        },
        title="Update Product Display Priority",
    )
    store_id: str = Field(..., title="Store ID")
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    products: str = Field(..., title="Products", description="JSON array of [productId, priority] pairs")


class GHLListProductCollectionsConfig(BaseModel):
    """List product collections."""

    operation: Literal["list_product_collections"] = Field(
        "list_product_collections",
        json_schema_extra={
            "const": "list_product_collections", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "List Product Collections",
        },
        title="List Product Collections",
    )
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    limit: Optional[str] = Field(None, title="Limit")
    offset: Optional[str] = Field(None, title="Offset")
    collection_ids: Optional[str] = Field(None, title="Collection IDs", description="Comma-separated collection ids")
    name: Optional[str] = Field(None, title="Name")


class GHLCreateProductCollectionConfig(BaseModel):
    """Create a product collection."""

    operation: Literal["create_product_collection"] = Field(
        "create_product_collection",
        json_schema_extra={
            "const": "create_product_collection", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Create Product Collection",
        },
        title="Create Product Collection",
    )
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    name: str = Field(..., title="Name")
    slug: str = Field(..., title="Slug")
    collection_id: Optional[str] = Field(None, title="Collection ID")
    image: Optional[str] = Field(None, title="Image", description="Image URL")
    seo: Optional[str] = Field(None, title="SEO", description="JSON SEO object")


class GHLGetProductCollectionConfig(BaseModel):
    """Get a product collection by id."""

    operation: Literal["get_product_collection"] = Field(
        "get_product_collection",
        json_schema_extra={
            "const": "get_product_collection", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Get Product Collection",
        },
        title="Get Product Collection",
    )
    collection_id: str = Field(..., title="Collection ID", description="The collection to fetch")
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")


class GHLUpdateProductCollectionConfig(BaseModel):
    """Update a product collection."""

    operation: Literal["update_product_collection"] = Field(
        "update_product_collection",
        json_schema_extra={
            "const": "update_product_collection", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Update Product Collection",
        },
        title="Update Product Collection",
    )
    collection_id: str = Field(..., title="Collection ID", description="The collection to update")
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    name: Optional[str] = Field(None, title="Name")
    slug: Optional[str] = Field(None, title="Slug")
    image: Optional[str] = Field(None, title="Image", description="Image URL")
    seo: Optional[str] = Field(None, title="SEO", description="JSON SEO object")


class GHLDeleteProductCollectionConfig(BaseModel):
    """Delete a product collection."""

    operation: Literal["delete_product_collection"] = Field(
        "delete_product_collection",
        json_schema_extra={
            "const": "delete_product_collection", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Delete Product Collection",
        },
        title="Delete Product Collection",
    )
    collection_id: str = Field(..., title="Collection ID", description="The collection to delete")
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )


class GHLListProductReviewsConfig(BaseModel):
    """List product reviews."""

    operation: Literal["list_product_reviews"] = Field(
        "list_product_reviews",
        json_schema_extra={
            "const": "list_product_reviews", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "List Product Reviews",
        },
        title="List Product Reviews",
    )
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    limit: Optional[str] = Field(None, title="Limit")
    offset: Optional[str] = Field(None, title="Offset")
    sort_field: Optional[str] = Field(
        None, title="Sort Field",
        json_schema_extra={"enum": ["createdAt", "rating"], "x-enum-searchable": True},
    )
    sort_order: Optional[str] = Field(
        None, title="Sort Order",
        json_schema_extra={"enum": ["asc", "desc"], "x-enum-searchable": True},
    )
    rating: Optional[str] = Field(None, title="Rating", description="Rating (number)")
    start_date: Optional[str] = Field(None, title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")
    product_id: Optional[str] = Field(None, title="Product ID")
    store_id: Optional[str] = Field(None, title="Store ID")


class GHLGetProductReviewsCountConfig(BaseModel):
    """Get product reviews count."""

    operation: Literal["get_product_reviews_count"] = Field(
        "get_product_reviews_count",
        json_schema_extra={
            "const": "get_product_reviews_count", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Get Product Reviews Count",
        },
        title="Get Product Reviews Count",
    )
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    rating: Optional[str] = Field(None, title="Rating", description="Rating (number)")
    start_date: Optional[str] = Field(None, title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")
    product_id: Optional[str] = Field(None, title="Product ID")
    store_id: Optional[str] = Field(None, title="Store ID")


class GHLUpdateProductReviewConfig(BaseModel):
    """Update a product review."""

    operation: Literal["update_product_review"] = Field(
        "update_product_review",
        json_schema_extra={
            "const": "update_product_review", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Update Product Review",
        },
        title="Update Product Review",
    )
    review_id: str = Field(..., title="Review ID", description="The review to update")
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    product_id: str = Field(..., title="Product ID")
    status: str = Field(..., title="Status")
    reply: Optional[str] = Field(None, title="Reply", description="JSON array of reply objects")
    rating: Optional[str] = Field(None, title="Rating", description="Rating (number)")
    headline: Optional[str] = Field(None, title="Headline")
    detail: Optional[str] = Field(None, title="Detail")


class GHLDeleteProductReviewConfig(BaseModel):
    """Delete a product review."""

    operation: Literal["delete_product_review"] = Field(
        "delete_product_review",
        json_schema_extra={
            "const": "delete_product_review", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Delete Product Review",
        },
        title="Delete Product Review",
    )
    review_id: str = Field(..., title="Review ID", description="The review to delete")
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    product_id: str = Field(..., title="Product ID")


class GHLBulkUpdateProductReviewsConfig(BaseModel):
    """Bulk update product reviews."""

    operation: Literal["bulk_update_product_reviews"] = Field(
        "bulk_update_product_reviews",
        json_schema_extra={
            "const": "bulk_update_product_reviews", "ui:hidden": True,
            "x-category": "Products", "x-is-trigger": False,
            "x-display-name": "Bulk Update Product Reviews",
        },
        title="Bulk Update Product Reviews",
    )
    alt_id: str = Field(..., title="Location ID", description="Sub-account (location) id (altId)")
    alt_type: str = Field(
        "location", title="Alt Type",
        json_schema_extra={"enum": ["location"], "x-enum-searchable": True},
    )
    reviews: str = Field(..., title="Reviews", description="JSON array of review reference objects")
    status: str = Field(..., title="Status", description="JSON status object")


async def _list_products(node, c, token):
    params = {
        "locationId": c.location_id, "limit": c.limit, "offset": c.offset,
        "search": c.search, "collectionIds": c.collection_ids, "collectionSlug": c.collection_slug,
        "expand": _ghl_csv(c.expand), "productIds": _ghl_csv(c.product_ids), "storeId": c.store_id,
        "includedInStore": _ghl_bool(c.included_in_store), "availableInStore": _ghl_bool(c.available_in_store),
        "sortOrder": c.sort_order,
    }
    return await node._request(token, "GET", "/products/", params=params, action_name="list_products")


async def _create_product(node, c, token):
    body = {
        "name": c.name, "locationId": c.location_id, "productType": c.product_type,
        "description": c.description, "image": c.image, "statementDescriptor": c.statement_descriptor,
        "availableInStore": _ghl_bool(c.available_in_store), "medias": _ghl_json(c.medias),
        "variants": _ghl_json(c.variants), "collectionIds": _ghl_csv(c.collection_ids),
        "isTaxesEnabled": _ghl_bool(c.is_taxes_enabled), "taxes": _ghl_csv(c.taxes),
        "automaticTaxCategoryId": c.automatic_tax_category_id, "isLabelEnabled": _ghl_bool(c.is_label_enabled),
        "label": _ghl_json(c.label), "slug": c.slug, "seo": _ghl_json(c.seo),
        "taxInclusive": _ghl_bool(c.tax_inclusive),
    }
    return await node._request(token, "POST", "/products/", json_body=body, action_name="create_product")


async def _get_product(node, c, token):
    params = {"locationId": c.location_id, "sendWishlistStatus": _ghl_bool(c.send_wishlist_status)}
    return await node._request(token, "GET", f"/products/{c.product_id}", params=params, action_name="get_product")


async def _update_product(node, c, token):
    body = {
        "name": c.name, "locationId": c.location_id, "productType": c.product_type,
        "description": c.description, "image": c.image, "statementDescriptor": c.statement_descriptor,
        "availableInStore": _ghl_bool(c.available_in_store), "medias": _ghl_json(c.medias),
        "variants": _ghl_json(c.variants), "collectionIds": _ghl_csv(c.collection_ids),
        "isTaxesEnabled": _ghl_bool(c.is_taxes_enabled), "taxes": _ghl_csv(c.taxes),
        "automaticTaxCategoryId": c.automatic_tax_category_id, "isLabelEnabled": _ghl_bool(c.is_label_enabled),
        "label": _ghl_json(c.label), "slug": c.slug, "seo": _ghl_json(c.seo),
        "taxInclusive": _ghl_bool(c.tax_inclusive), "prices": _ghl_csv(c.prices),
    }
    return await node._request(token, "PUT", f"/products/{c.product_id}", json_body=body, action_name="update_product")


async def _delete_product(node, c, token):
    params = {"locationId": c.location_id, "sendWishlistStatus": _ghl_bool(c.send_wishlist_status)}
    return await node._request(token, "DELETE", f"/products/{c.product_id}", params=params, action_name="delete_product")


async def _bulk_update_products(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "type": c.type,
        "productIds": _ghl_csv(c.product_ids), "filters": _ghl_json(c.filters),
        "price": _ghl_json(c.price), "compareAtPrice": _ghl_json(c.compare_at_price),
        "availability": _ghl_bool(c.availability), "collectionIds": _ghl_csv(c.collection_ids),
        "currency": c.currency,
    }
    return await node._request(token, "POST", "/products/bulk-update", json_body=body, action_name="bulk_update_products")


async def _bulk_edit_products(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type, "products": _ghl_json(c.products)}
    return await node._request(token, "POST", "/products/bulk-update/edit", json_body=body, action_name="bulk_edit_products")


async def _create_price_for_product(node, c, token):
    body = {
        "name": c.name, "type": c.type, "currency": c.currency, "amount": _ghl_num(c.amount),
        "locationId": c.location_id, "recurring": _ghl_json(c.recurring), "description": c.description,
        "membershipOffers": _ghl_json(c.membership_offers), "trialPeriod": _ghl_num(c.trial_period),
        "totalCycles": _ghl_num(c.total_cycles), "setupFee": _ghl_num(c.setup_fee),
        "variantOptionIds": _ghl_csv(c.variant_option_ids), "compareAtPrice": _ghl_num(c.compare_at_price),
        "userId": c.user_id, "meta": _ghl_json(c.meta), "trackInventory": _ghl_bool(c.track_inventory),
        "availableQuantity": _ghl_num(c.available_quantity),
        "allowOutOfStockPurchases": _ghl_bool(c.allow_out_of_stock_purchases), "sku": c.sku,
        "shippingOptions": _ghl_json(c.shipping_options), "isDigitalProduct": _ghl_bool(c.is_digital_product),
        "digitalDelivery": _ghl_csv(c.digital_delivery),
    }
    return await node._request(token, "POST", f"/products/{c.product_id}/price", json_body=body, action_name="create_price_for_product")


async def _list_prices_for_product(node, c, token):
    params = {"limit": c.limit, "offset": c.offset, "locationId": c.location_id, "ids": c.ids}
    return await node._request(token, "GET", f"/products/{c.product_id}/price", params=params, action_name="list_prices_for_product")


async def _get_price_for_product(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", f"/products/{c.product_id}/price/{c.price_id}", params=params, action_name="get_price_for_product")


async def _update_price_for_product(node, c, token):
    body = {
        "name": c.name, "type": c.type, "currency": c.currency, "amount": _ghl_num(c.amount),
        "locationId": c.location_id, "recurring": _ghl_json(c.recurring), "description": c.description,
        "membershipOffers": _ghl_json(c.membership_offers), "trialPeriod": _ghl_num(c.trial_period),
        "totalCycles": _ghl_num(c.total_cycles), "setupFee": _ghl_num(c.setup_fee),
        "variantOptionIds": _ghl_csv(c.variant_option_ids), "compareAtPrice": _ghl_num(c.compare_at_price),
        "userId": c.user_id, "meta": _ghl_json(c.meta), "trackInventory": _ghl_bool(c.track_inventory),
        "availableQuantity": _ghl_num(c.available_quantity),
        "allowOutOfStockPurchases": _ghl_bool(c.allow_out_of_stock_purchases), "sku": c.sku,
        "shippingOptions": _ghl_json(c.shipping_options), "isDigitalProduct": _ghl_bool(c.is_digital_product),
        "digitalDelivery": _ghl_csv(c.digital_delivery),
    }
    return await node._request(token, "PUT", f"/products/{c.product_id}/price/{c.price_id}", json_body=body, action_name="update_price_for_product")


async def _delete_price_for_product(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "DELETE", f"/products/{c.product_id}/price/{c.price_id}", params=params, action_name="delete_price_for_product")


async def _get_product_inventory(node, c, token):
    params = {"limit": c.limit, "offset": c.offset, "altId": c.alt_id, "altType": c.alt_type, "search": c.search}
    return await node._request(token, "GET", "/products/inventory", params=params, action_name="get_product_inventory")


async def _update_product_inventory(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type, "items": _ghl_json(c.items)}
    return await node._request(token, "POST", "/products/inventory", json_body=body, action_name="update_product_inventory")


async def _get_product_store_stats(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type, "search": c.search, "collectionIds": c.collection_ids}
    return await node._request(token, "GET", f"/products/store/{c.store_id}/stats", params=params, action_name="get_product_store_stats")


async def _update_product_store_status(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type, "action": c.action, "productIds": _ghl_csv(c.product_ids)}
    return await node._request(token, "POST", f"/products/store/{c.store_id}", json_body=body, action_name="update_product_store_status")


async def _update_product_display_priority(node, c, token):
    body = {"altId": c.alt_id, "altType": c.alt_type, "products": _ghl_json(c.products)}
    return await node._request(token, "POST", f"/products/store/{c.store_id}/priority", json_body=body, action_name="update_product_display_priority")


async def _list_product_collections(node, c, token):
    params = {
        "limit": c.limit, "offset": c.offset, "altId": c.alt_id, "altType": c.alt_type,
        "collectionIds": c.collection_ids, "name": c.name,
    }
    return await node._request(token, "GET", "/products/collections", params=params, action_name="list_product_collections")


async def _create_product_collection(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "collectionId": c.collection_id,
        "name": c.name, "slug": c.slug, "image": c.image, "seo": _ghl_json(c.seo),
    }
    return await node._request(token, "POST", "/products/collections", json_body=body, action_name="create_product_collection")


async def _get_product_collection(node, c, token):
    params = {"altId": c.alt_id}
    return await node._request(token, "GET", f"/products/collections/{c.collection_id}", params=params, action_name="get_product_collection")


async def _update_product_collection(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name, "slug": c.slug,
        "image": c.image, "seo": _ghl_json(c.seo),
    }
    return await node._request(token, "PUT", f"/products/collections/{c.collection_id}", json_body=body, action_name="update_product_collection")


async def _delete_product_collection(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "DELETE", f"/products/collections/{c.collection_id}", params=params, action_name="delete_product_collection")


async def _list_product_reviews(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "limit": c.limit, "offset": c.offset,
        "sortField": c.sort_field, "sortOrder": c.sort_order, "rating": _ghl_num(c.rating),
        "startDate": c.start_date, "endDate": c.end_date, "productId": c.product_id, "storeId": c.store_id,
    }
    return await node._request(token, "GET", "/products/reviews", params=params, action_name="list_product_reviews")


async def _get_product_reviews_count(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "rating": _ghl_num(c.rating),
        "startDate": c.start_date, "endDate": c.end_date, "productId": c.product_id, "storeId": c.store_id,
    }
    return await node._request(token, "GET", "/products/reviews/count", params=params, action_name="get_product_reviews_count")


async def _update_product_review(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "productId": c.product_id, "status": c.status,
        "reply": _ghl_json(c.reply), "rating": _ghl_num(c.rating), "headline": c.headline, "detail": c.detail,
    }
    return await node._request(token, "PUT", f"/products/reviews/{c.review_id}", json_body=body, action_name="update_product_review")


async def _delete_product_review(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type, "productId": c.product_id}
    return await node._request(token, "DELETE", f"/products/reviews/{c.review_id}", params=params, action_name="delete_product_review")


async def _bulk_update_product_reviews(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "reviews": _ghl_json(c.reviews), "status": _ghl_json(c.status),
    }
    return await node._request(token, "POST", "/products/reviews/bulk-update", json_body=body, action_name="bulk_update_product_reviews")


GHL_OPERATION_CONFIGS += [
    GHLListProductsConfig,
    GHLCreateProductConfig,
    GHLGetProductConfig,
    GHLUpdateProductConfig,
    GHLDeleteProductConfig,
    GHLBulkUpdateProductsConfig,
    GHLBulkEditProductsConfig,
    GHLCreatePriceForProductConfig,
    GHLListPricesForProductConfig,
    GHLGetPriceForProductConfig,
    GHLUpdatePriceForProductConfig,
    GHLDeletePriceForProductConfig,
    GHLGetProductInventoryConfig,
    GHLUpdateProductInventoryConfig,
    GHLGetProductStoreStatsConfig,
    GHLUpdateProductStoreStatusConfig,
    GHLUpdateProductDisplayPriorityConfig,
    GHLListProductCollectionsConfig,
    GHLCreateProductCollectionConfig,
    GHLGetProductCollectionConfig,
    GHLUpdateProductCollectionConfig,
    GHLDeleteProductCollectionConfig,
    GHLListProductReviewsConfig,
    GHLGetProductReviewsCountConfig,
    GHLUpdateProductReviewConfig,
    GHLDeleteProductReviewConfig,
    GHLBulkUpdateProductReviewsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "list_products": _list_products,
    "create_product": _create_product,
    "get_product": _get_product,
    "update_product": _update_product,
    "delete_product": _delete_product,
    "bulk_update_products": _bulk_update_products,
    "bulk_edit_products": _bulk_edit_products,
    "create_price_for_product": _create_price_for_product,
    "list_prices_for_product": _list_prices_for_product,
    "get_price_for_product": _get_price_for_product,
    "update_price_for_product": _update_price_for_product,
    "delete_price_for_product": _delete_price_for_product,
    "get_product_inventory": _get_product_inventory,
    "update_product_inventory": _update_product_inventory,
    "get_product_store_stats": _get_product_store_stats,
    "update_product_store_status": _update_product_store_status,
    "update_product_display_priority": _update_product_display_priority,
    "list_product_collections": _list_product_collections,
    "create_product_collection": _create_product_collection,
    "get_product_collection": _get_product_collection,
    "update_product_collection": _update_product_collection,
    "delete_product_collection": _delete_product_collection,
    "list_product_reviews": _list_product_reviews,
    "get_product_reviews_count": _get_product_reviews_count,
    "update_product_review": _update_product_review,
    "delete_product_review": _delete_product_review,
    "bulk_update_product_reviews": _bulk_update_product_reviews,
})


# ---- proposals.py ----
class GHLListProposalDocumentsConfig(BaseModel):
    """List proposal/estimate documents & contracts for a location."""

    operation: Literal["list_proposal_documents"] = Field(
        "list_proposal_documents",
        json_schema_extra={
            "const": "list_proposal_documents", "ui:hidden": True,
            "x-category": "Proposals", "x-is-trigger": False,
            "x-display-name": "List Documents",
        },
        title="List Documents",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    status: Optional[str] = Field(
        None, title="Status",
        json_schema_extra={
            "enum": ["draft", "sent", "viewed", "completed", "accepted"],
            "x-enum-searchable": True,
        },
    )
    payment_status: Optional[str] = Field(
        None, title="Payment Status",
        json_schema_extra={
            "enum": ["waiting_for_payment", "paid", "no_payment"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")
    query: Optional[str] = Field(None, title="Query", description="Free-text search")
    date_from: Optional[str] = Field(None, title="Date From", description="ISO 8601 start date")
    date_to: Optional[str] = Field(None, title="Date To", description="ISO 8601 end date")


class GHLSendProposalDocumentConfig(BaseModel):
    """Send an existing proposal/contract document."""

    operation: Literal["send_proposal_document"] = Field(
        "send_proposal_document",
        json_schema_extra={
            "const": "send_proposal_document", "ui:hidden": True,
            "x-category": "Proposals", "x-is-trigger": False,
            "x-display-name": "Send Document",
        },
        title="Send Document",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    document_id: str = Field(..., title="Document ID", description="The document to send")
    sent_by: str = Field(..., title="Sent By", description="User id sending the document")
    document_name: Optional[str] = Field(None, title="Document Name")
    medium: Optional[str] = Field(
        None, title="Medium",
        json_schema_extra={"enum": ["link", "email"], "x-enum-searchable": True},
    )
    cc_recipients: Optional[str] = Field(
        None, title="CC Recipients",
        description='JSON array of CC recipient objects (id, email, contactName, firstName, lastName, imageUrl)',
    )
    notification_settings: Optional[str] = Field(
        None, title="Notification Settings",
        description='JSON object with sender {fromName, fromEmail} and receive {subject, templateId}',
    )


class GHLListProposalTemplatesConfig(BaseModel):
    """List proposal/estimate templates for a location."""

    operation: Literal["list_proposal_templates"] = Field(
        "list_proposal_templates",
        json_schema_extra={
            "const": "list_proposal_templates", "ui:hidden": True,
            "x-category": "Proposals", "x-is-trigger": False,
            "x-display-name": "List Templates",
        },
        title="List Templates",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    date_from: Optional[str] = Field(None, title="Date From", description="ISO 8601 start date")
    date_to: Optional[str] = Field(None, title="Date To", description="ISO 8601 end date")
    type: Optional[str] = Field(None, title="Type", description="Comma-separated types, e.g. proposal,estimate")
    name: Optional[str] = Field(None, title="Name", description="Filter by template name")
    is_public_document: Optional[str] = Field(
        None, title="Public Document Only",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    user_id: Optional[str] = Field(None, title="User ID", description="Filter by owner user id")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")


class GHLSendProposalTemplateConfig(BaseModel):
    """Create & optionally send a document from a proposal template."""

    operation: Literal["send_proposal_template"] = Field(
        "send_proposal_template",
        json_schema_extra={
            "const": "send_proposal_template", "ui:hidden": True,
            "x-category": "Proposals", "x-is-trigger": False,
            "x-display-name": "Send Template",
        },
        title="Send Template",
    )
    template_id: str = Field(..., title="Template ID", description="The template to send")
    user_id: str = Field(..., title="User ID", description="User id sending the document")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    contact_id: str = Field(..., title="Contact ID", description="Recipient contact id")
    send_document: Optional[str] = Field(
        None, title="Send Document",
        description="Whether to send the document (else just create it)",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    opportunity_id: Optional[str] = Field(None, title="Opportunity ID", description="Associated opportunity id")


async def _list_proposal_documents(node, c, token):
    params = {
        "locationId": c.location_id, "status": c.status, "paymentStatus": c.payment_status,
        "limit": c.limit, "skip": c.skip, "query": c.query,
        "dateFrom": c.date_from, "dateTo": c.date_to,
    }
    return await node._request(token, "GET", "/proposals/document", params=params, action_name="list_proposal_documents")


async def _send_proposal_document(node, c, token):
    body = {
        "locationId": c.location_id, "documentId": c.document_id, "sentBy": c.sent_by,
        "documentName": c.document_name, "medium": c.medium,
        "ccRecipients": _ghl_json(c.cc_recipients),
        "notificationSettings": _ghl_json(c.notification_settings),
    }
    return await node._request(token, "POST", "/proposals/document/send", json_body=body, action_name="send_proposal_document")


async def _list_proposal_templates(node, c, token):
    params = {
        "locationId": c.location_id, "dateFrom": c.date_from, "dateTo": c.date_to,
        "type": c.type, "name": c.name, "isPublicDocument": _ghl_bool(c.is_public_document),
        "userId": c.user_id, "limit": c.limit, "skip": c.skip,
    }
    return await node._request(token, "GET", "/proposals/templates", params=params, action_name="list_proposal_templates")


async def _send_proposal_template(node, c, token):
    body = {
        "templateId": c.template_id, "userId": c.user_id, "locationId": c.location_id,
        "contactId": c.contact_id, "sendDocument": _ghl_bool(c.send_document),
        "opportunityId": c.opportunity_id,
    }
    return await node._request(token, "POST", "/proposals/templates/send", json_body=body, action_name="send_proposal_template")


GHL_OPERATION_CONFIGS += [
    GHLListProposalDocumentsConfig,
    GHLSendProposalDocumentConfig,
    GHLListProposalTemplatesConfig,
    GHLSendProposalTemplateConfig,
]
GHL_OPERATION_HANDLERS.update({
    "list_proposal_documents": _list_proposal_documents,
    "send_proposal_document": _send_proposal_document,
    "list_proposal_templates": _list_proposal_templates,
    "send_proposal_template": _send_proposal_template,
})


# ---- saas_api.py ----
class GHLGetAgencyPlansConfig(BaseModel):
    """Get agency (SaaS) plans for a company."""

    operation: Literal["get_agency_plans"] = Field(
        "get_agency_plans",
        json_schema_extra={
            "const": "get_agency_plans", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get Agency Plans",
        },
        title="Get Agency Plans",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to get agency plans for")


class GHLBulkDisableSaasConfig(BaseModel):
    """Disable SaaS for a list of locations."""

    operation: Literal["bulk_disable_saas"] = Field(
        "bulk_disable_saas",
        json_schema_extra={
            "const": "bulk_disable_saas", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Disable SaaS For Locations",
        },
        title="Disable SaaS For Locations",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to disable SaaS for")
    location_ids: str = Field(..., title="Location IDs", description="Comma-separated location IDs")


class GHLBulkEnableSaasConfig(BaseModel):
    """Bulk enable SaaS for a list of locations."""

    operation: Literal["bulk_enable_saas"] = Field(
        "bulk_enable_saas",
        json_schema_extra={
            "const": "bulk_enable_saas", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Bulk Enable SaaS",
        },
        title="Bulk Enable SaaS",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to enable SaaS for")
    location_ids: str = Field(..., title="Location IDs", description="Comma-separated location IDs to enable SaaS for")
    is_saas_v2: str = Field(
        ..., title="Is SaaS V2", description="Indicates if the SaaS is V2",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    action_payload: str = Field(..., title="Action Payload", description="JSON object: action payload for the bulk enable SaaS operation")


class GHLEnableSaasLocationConfig(BaseModel):
    """Enable SaaS for a sub-account (location)."""

    operation: Literal["enable_saas_location"] = Field(
        "enable_saas_location",
        json_schema_extra={
            "const": "enable_saas_location", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Enable SaaS For Sub-Account",
        },
        title="Enable SaaS For Sub-Account",
    )
    location_id: str = Field(..., title="Location ID", description="Location ID to enable SaaS for")
    company_id: str = Field(..., title="Company ID")
    is_saas_v2: str = Field(
        ..., title="Is SaaS V2", description="Denotes if it is a SaaS v2 or v1 sub-account",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    stripe_account_id: Optional[str] = Field(None, title="Stripe Account ID", description="Stripe account id (Required only for SaaS V1)")
    name: Optional[str] = Field(None, title="Name", description="Name of the stripe customer (Required only for SaaS V1)")
    email: Optional[str] = Field(None, title="Email", description="Email of the stripe customer (Required only for SaaS V1)")
    stripe_customer_id: Optional[str] = Field(None, title="Stripe Customer ID", description="Stripe customer id if exists (Required only for SaaS V1)")
    contact_id: Optional[str] = Field(None, title="Contact ID", description="Agency subaccount used for payment provider integration")
    provider_location_id: Optional[str] = Field(None, title="Provider Location ID", description="Agency Subaccount ID")
    description: Optional[str] = Field(None, title="Description")
    saas_plan_id: Optional[str] = Field(None, title="SaaS Plan ID", description="Required only while pre-configuring saas subscription")
    price_id: Optional[str] = Field(None, title="Price ID", description="Required only while pre-configuring saas subscription")


class GHLGetLocationSubscriptionConfig(BaseModel):
    """Get SaaS subscription details for a location."""

    operation: Literal["get_location_subscription"] = Field(
        "get_location_subscription",
        json_schema_extra={
            "const": "get_location_subscription", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get Location Subscription Details",
        },
        title="Get Location Subscription Details",
    )
    location_id: str = Field(..., title="Location ID", description="Location ID to get subscription details for")
    company_id: str = Field(..., title="Company ID", description="Company ID to filter subscription details")


class GHLLocationsConfig(BaseModel):
    """Get locations by stripe id with company id."""

    operation: Literal["locations"] = Field(
        "locations",
        json_schema_extra={
            "const": "locations", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get Locations By Stripe ID",
        },
        title="Get Locations By Stripe ID",
    )
    customer_id: str = Field(..., title="Customer ID", description="Stripe customer ID to find locations for")
    subscription_id: str = Field(..., title="Subscription ID", description="Stripe subscription ID to find locations for")
    company_id: str = Field(..., title="Company ID", description="Company ID to filter locations")


class GHLPauseLocationConfig(BaseModel):
    """Pause or unpause a location."""

    operation: Literal["pause_location"] = Field(
        "pause_location",
        json_schema_extra={
            "const": "pause_location", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Pause Location",
        },
        title="Pause Location",
    )
    location_id: str = Field(..., title="Location ID", description="Location ID to pause/unpause")
    company_id: str = Field(..., title="Company ID", description="Company ID")
    paused: str = Field(
        ..., title="Paused", description="Whether the location is paused",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )


class GHLGetSaasLocationsConfig(BaseModel):
    """Get SaaS locations for a company."""

    operation: Literal["get_saas_locations"] = Field(
        "get_saas_locations",
        json_schema_extra={
            "const": "get_saas_locations", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get SaaS Locations",
        },
        title="Get SaaS Locations",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to get SaaS locations for")
    page: str = Field(..., title="Page", description="Page number for pagination")


class GHLGetSaasPlanConfig(BaseModel):
    """Get a SaaS plan by id."""

    operation: Literal["get_saas_plan"] = Field(
        "get_saas_plan",
        json_schema_extra={
            "const": "get_saas_plan", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get SaaS Plan",
        },
        title="Get SaaS Plan",
    )
    plan_id: str = Field(..., title="Plan ID", description="Plan ID to get SaaS plan details for")
    company_id: str = Field(..., title="Company ID", description="Company ID to filter SaaS plan")


class GHLUpdateRebillingConfig(BaseModel):
    """Update rebilling settings for a company's locations."""

    operation: Literal["update_rebilling"] = Field(
        "update_rebilling",
        json_schema_extra={
            "const": "update_rebilling", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Update Rebilling",
        },
        title="Update Rebilling",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to update rebilling for")
    product: str = Field(..., title="Product", description="The product to update rebilling for")
    location_ids: str = Field(..., title="Location IDs", description="Comma-separated location IDs to update rebilling for")
    config: str = Field(..., title="Config", description="JSON object: configuration for rebilling settings")


class GHLGeneratePaymentLinkConfig(BaseModel):
    """Update SaaS subscription (generate payment link)."""

    operation: Literal["generate_payment_link"] = Field(
        "generate_payment_link",
        json_schema_extra={
            "const": "generate_payment_link", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Update SaaS Subscription",
        },
        title="Update SaaS Subscription",
    )
    location_id: str = Field(..., title="Location ID", description="Location ID to update subscription for")
    subscription_id: str = Field(..., title="Subscription ID", description="Subscription ID")
    customer_id: str = Field(..., title="Customer ID", description="Customer ID")
    company_id: str = Field(..., title="Company ID", description="Company ID")


# --- Deprecated (/saas-api/public-api/...) operations ------------------------

class GHLGetAgencyPlansDeprecatedConfig(BaseModel):
    """[Deprecated] Get agency (SaaS) plans for a company."""

    operation: Literal["get_agency_plans_deprecated"] = Field(
        "get_agency_plans_deprecated",
        json_schema_extra={
            "const": "get_agency_plans_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get Agency Plans (Deprecated)",
        },
        title="Get Agency Plans (Deprecated)",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to get agency plans for")


class GHLBulkDisableSaasDeprecatedConfig(BaseModel):
    """[Deprecated] Disable SaaS for a list of locations."""

    operation: Literal["bulk_disable_saas_deprecated"] = Field(
        "bulk_disable_saas_deprecated",
        json_schema_extra={
            "const": "bulk_disable_saas_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Disable SaaS For Locations (Deprecated)",
        },
        title="Disable SaaS For Locations (Deprecated)",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to disable SaaS for")
    location_ids: str = Field(..., title="Location IDs", description="Comma-separated location IDs")


class GHLBulkEnableSaasDeprecatedConfig(BaseModel):
    """[Deprecated] Bulk enable SaaS for a list of locations."""

    operation: Literal["bulk_enable_saas_deprecated"] = Field(
        "bulk_enable_saas_deprecated",
        json_schema_extra={
            "const": "bulk_enable_saas_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Bulk Enable SaaS (Deprecated)",
        },
        title="Bulk Enable SaaS (Deprecated)",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to enable SaaS for")
    location_ids: str = Field(..., title="Location IDs", description="Comma-separated location IDs to enable SaaS for")
    is_saas_v2: str = Field(
        ..., title="Is SaaS V2", description="Indicates if the SaaS is V2",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    action_payload: str = Field(..., title="Action Payload", description="JSON object: action payload for the bulk enable SaaS operation")


class GHLEnableSaasLocationDeprecatedConfig(BaseModel):
    """[Deprecated] Enable SaaS for a sub-account (location)."""

    operation: Literal["enable_saas_location_deprecated"] = Field(
        "enable_saas_location_deprecated",
        json_schema_extra={
            "const": "enable_saas_location_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Enable SaaS For Sub-Account (Deprecated)",
        },
        title="Enable SaaS For Sub-Account (Deprecated)",
    )
    location_id: str = Field(..., title="Location ID", description="Location ID to enable SaaS for")
    company_id: str = Field(..., title="Company ID")
    is_saas_v2: str = Field(
        ..., title="Is SaaS V2", description="Denotes if it is a SaaS v2 or v1 sub-account",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )
    stripe_account_id: Optional[str] = Field(None, title="Stripe Account ID", description="Stripe account id (Required only for SaaS V1)")
    name: Optional[str] = Field(None, title="Name", description="Name of the stripe customer (Required only for SaaS V1)")
    email: Optional[str] = Field(None, title="Email", description="Email of the stripe customer (Required only for SaaS V1)")
    stripe_customer_id: Optional[str] = Field(None, title="Stripe Customer ID", description="Stripe customer id if exists (Required only for SaaS V1)")
    contact_id: Optional[str] = Field(None, title="Contact ID", description="Agency subaccount used for payment provider integration")
    provider_location_id: Optional[str] = Field(None, title="Provider Location ID", description="Agency Subaccount ID")
    description: Optional[str] = Field(None, title="Description")
    saas_plan_id: Optional[str] = Field(None, title="SaaS Plan ID", description="Required only while pre-configuring saas subscription")
    price_id: Optional[str] = Field(None, title="Price ID", description="Required only while pre-configuring saas subscription")


class GHLGetLocationSubscriptionDeprecatedConfig(BaseModel):
    """[Deprecated] Get SaaS subscription details for a location."""

    operation: Literal["get_location_subscription_deprecated"] = Field(
        "get_location_subscription_deprecated",
        json_schema_extra={
            "const": "get_location_subscription_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get Location Subscription Details (Deprecated)",
        },
        title="Get Location Subscription Details (Deprecated)",
    )
    location_id: str = Field(..., title="Location ID", description="Location ID to get subscription details for")
    company_id: str = Field(..., title="Company ID", description="Company ID to filter subscription details")


class GHLLocationsDeprecatedConfig(BaseModel):
    """[Deprecated] Get locations by stripe id with company id."""

    operation: Literal["locations_deprecated"] = Field(
        "locations_deprecated",
        json_schema_extra={
            "const": "locations_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get Locations By Stripe ID (Deprecated)",
        },
        title="Get Locations By Stripe ID (Deprecated)",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to filter locations")
    customer_id: Optional[str] = Field(None, title="Customer ID", description="Stripe customer ID to find locations for")
    subscription_id: Optional[str] = Field(None, title="Subscription ID", description="Stripe subscription ID to find locations for")


class GHLPauseLocationDeprecatedConfig(BaseModel):
    """[Deprecated] Pause or unpause a location."""

    operation: Literal["pause_location_deprecated"] = Field(
        "pause_location_deprecated",
        json_schema_extra={
            "const": "pause_location_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Pause Location (Deprecated)",
        },
        title="Pause Location (Deprecated)",
    )
    location_id: str = Field(..., title="Location ID", description="Location ID to pause/unpause")
    company_id: str = Field(..., title="Company ID", description="Company ID")
    paused: str = Field(
        ..., title="Paused", description="Whether the location is paused",
        json_schema_extra={
            "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True,
        },
    )


class GHLGetSaasLocationsDeprecatedConfig(BaseModel):
    """[Deprecated] Get SaaS locations for a company."""

    operation: Literal["get_saas_locations_deprecated"] = Field(
        "get_saas_locations_deprecated",
        json_schema_extra={
            "const": "get_saas_locations_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get SaaS Locations (Deprecated)",
        },
        title="Get SaaS Locations (Deprecated)",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to get SaaS locations for")
    page: Optional[str] = Field(None, title="Page", description="Page number for pagination")


class GHLGetSaasPlanDeprecatedConfig(BaseModel):
    """[Deprecated] Get a SaaS plan by id."""

    operation: Literal["get_saas_plan_deprecated"] = Field(
        "get_saas_plan_deprecated",
        json_schema_extra={
            "const": "get_saas_plan_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Get SaaS Plan (Deprecated)",
        },
        title="Get SaaS Plan (Deprecated)",
    )
    plan_id: str = Field(..., title="Plan ID", description="Plan ID to get SaaS plan details for")
    company_id: str = Field(..., title="Company ID", description="Company ID to filter SaaS plan")


class GHLUpdateRebillingDeprecatedConfig(BaseModel):
    """[Deprecated] Update rebilling settings for a company's locations."""

    operation: Literal["update_rebilling_deprecated"] = Field(
        "update_rebilling_deprecated",
        json_schema_extra={
            "const": "update_rebilling_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Update Rebilling (Deprecated)",
        },
        title="Update Rebilling (Deprecated)",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to update rebilling for")
    product: str = Field(..., title="Product", description="The product to update rebilling for")
    location_ids: str = Field(..., title="Location IDs", description="Comma-separated location IDs to update rebilling for")
    config: str = Field(..., title="Config", description="JSON object: configuration for rebilling settings")


class GHLUpdateSaasSubscriptionDeprecatedConfig(BaseModel):
    """[Deprecated] Update SaaS subscription."""

    operation: Literal["update_saas_subscription_deprecated"] = Field(
        "update_saas_subscription_deprecated",
        json_schema_extra={
            "const": "update_saas_subscription_deprecated", "ui:hidden": True,
            "x-category": "SaaS", "x-is-trigger": False,
            "x-display-name": "Update SaaS Subscription (Deprecated)",
        },
        title="Update SaaS Subscription (Deprecated)",
    )
    location_id: str = Field(..., title="Location ID", description="Location ID to update subscription for")
    subscription_id: str = Field(..., title="Subscription ID", description="Subscription ID")
    customer_id: str = Field(..., title="Customer ID", description="Customer ID")
    company_id: str = Field(..., title="Company ID", description="Company ID")


# --- Handlers ---------------------------------------------------------------

async def _get_agency_plans(node, c, token):
    return await node._request(token, "GET", f"/saas/agency-plans/{c.company_id}", version="2021-04-15", action_name="get_agency_plans")


async def _bulk_disable_saas(node, c, token):
    body = {"locationIds": _ghl_csv(c.location_ids)}
    return await node._request(token, "POST", f"/saas/bulk-disable-saas/{c.company_id}", json_body=body, version="2021-04-15", action_name="bulk_disable_saas")


async def _bulk_enable_saas(node, c, token):
    body = {
        "locationIds": _ghl_csv(c.location_ids),
        "isSaaSV2": _ghl_bool(c.is_saas_v2),
        "actionPayload": _ghl_json(c.action_payload),
    }
    return await node._request(token, "POST", f"/saas/bulk-enable-saas/{c.company_id}", json_body=body, version="2021-04-15", action_name="bulk_enable_saas")


async def _enable_saas_location(node, c, token):
    body = {
        "companyId": c.company_id, "isSaaSV2": _ghl_bool(c.is_saas_v2),
        "stripeAccountId": c.stripe_account_id, "name": c.name, "email": c.email,
        "stripeCustomerId": c.stripe_customer_id, "contactId": c.contact_id,
        "providerLocationId": c.provider_location_id, "description": c.description,
        "saasPlanId": c.saas_plan_id, "priceId": c.price_id,
    }
    return await node._request(token, "POST", f"/saas/enable-saas/{c.location_id}", json_body=body, version="2021-04-15", action_name="enable_saas_location")


async def _get_location_subscription(node, c, token):
    params = {"companyId": c.company_id}
    return await node._request(token, "GET", f"/saas/get-saas-subscription/{c.location_id}", params=params, version="2021-04-15", action_name="get_location_subscription")


async def _locations(node, c, token):
    params = {"customerId": c.customer_id, "subscriptionId": c.subscription_id, "companyId": c.company_id}
    return await node._request(token, "GET", "/saas/locations", params=params, version="2021-04-15", action_name="locations")


async def _pause_location(node, c, token):
    body = {"paused": _ghl_bool(c.paused), "companyId": c.company_id}
    return await node._request(token, "POST", f"/saas/pause/{c.location_id}", json_body=body, version="2021-04-15", action_name="pause_location")


async def _get_saas_locations(node, c, token):
    params = {"page": _ghl_num(c.page)}
    return await node._request(token, "GET", f"/saas/saas-locations/{c.company_id}", params=params, version="2021-04-15", action_name="get_saas_locations")


async def _get_saas_plan(node, c, token):
    params = {"companyId": c.company_id}
    return await node._request(token, "GET", f"/saas/saas-plan/{c.plan_id}", params=params, version="2021-04-15", action_name="get_saas_plan")


async def _update_rebilling(node, c, token):
    body = {
        "product": c.product,
        "locationIds": _ghl_csv(c.location_ids),
        "config": _ghl_json(c.config),
    }
    return await node._request(token, "POST", f"/saas/update-rebilling/{c.company_id}", json_body=body, version="2021-04-15", action_name="update_rebilling")


async def _generate_payment_link(node, c, token):
    body = {"subscriptionId": c.subscription_id, "customerId": c.customer_id, "companyId": c.company_id}
    return await node._request(token, "PUT", f"/saas/update-saas-subscription/{c.location_id}", json_body=body, version="2021-04-15", action_name="generate_payment_link")


async def _get_agency_plans_deprecated(node, c, token):
    return await node._request(token, "GET", f"/saas-api/public-api/agency-plans/{c.company_id}", version="2021-04-15", action_name="get_agency_plans_deprecated")


async def _bulk_disable_saas_deprecated(node, c, token):
    body = {"locationIds": _ghl_csv(c.location_ids)}
    return await node._request(token, "POST", f"/saas-api/public-api/bulk-disable-saas/{c.company_id}", json_body=body, version="2021-04-15", action_name="bulk_disable_saas_deprecated")


async def _bulk_enable_saas_deprecated(node, c, token):
    body = {
        "locationIds": _ghl_csv(c.location_ids),
        "isSaaSV2": _ghl_bool(c.is_saas_v2),
        "actionPayload": _ghl_json(c.action_payload),
    }
    return await node._request(token, "POST", f"/saas-api/public-api/bulk-enable-saas/{c.company_id}", json_body=body, version="2021-04-15", action_name="bulk_enable_saas_deprecated")


async def _enable_saas_location_deprecated(node, c, token):
    body = {
        "companyId": c.company_id, "isSaaSV2": _ghl_bool(c.is_saas_v2),
        "stripeAccountId": c.stripe_account_id, "name": c.name, "email": c.email,
        "stripeCustomerId": c.stripe_customer_id, "contactId": c.contact_id,
        "providerLocationId": c.provider_location_id, "description": c.description,
        "saasPlanId": c.saas_plan_id, "priceId": c.price_id,
    }
    return await node._request(token, "POST", f"/saas-api/public-api/enable-saas/{c.location_id}", json_body=body, version="2021-04-15", action_name="enable_saas_location_deprecated")


async def _get_location_subscription_deprecated(node, c, token):
    params = {"companyId": c.company_id}
    return await node._request(token, "GET", f"/saas-api/public-api/get-saas-subscription/{c.location_id}", params=params, version="2021-04-15", action_name="get_location_subscription_deprecated")


async def _locations_deprecated(node, c, token):
    params = {"customerId": c.customer_id, "subscriptionId": c.subscription_id, "companyId": c.company_id}
    return await node._request(token, "GET", "/saas-api/public-api/locations", params=params, version="2021-04-15", action_name="locations_deprecated")


async def _pause_location_deprecated(node, c, token):
    body = {"paused": _ghl_bool(c.paused), "companyId": c.company_id}
    return await node._request(token, "POST", f"/saas-api/public-api/pause/{c.location_id}", json_body=body, version="2021-04-15", action_name="pause_location_deprecated")


async def _get_saas_locations_deprecated(node, c, token):
    params = {"page": _ghl_num(c.page)}
    return await node._request(token, "GET", f"/saas-api/public-api/saas-locations/{c.company_id}", params=params, version="2021-04-15", action_name="get_saas_locations_deprecated")


async def _get_saas_plan_deprecated(node, c, token):
    params = {"companyId": c.company_id}
    return await node._request(token, "GET", f"/saas-api/public-api/saas-plan/{c.plan_id}", params=params, version="2021-04-15", action_name="get_saas_plan_deprecated")


async def _update_rebilling_deprecated(node, c, token):
    body = {
        "product": c.product,
        "locationIds": _ghl_csv(c.location_ids),
        "config": _ghl_json(c.config),
    }
    return await node._request(token, "POST", f"/saas-api/public-api/update-rebilling/{c.company_id}", json_body=body, version="2021-04-15", action_name="update_rebilling_deprecated")


async def _update_saas_subscription_deprecated(node, c, token):
    body = {"subscriptionId": c.subscription_id, "customerId": c.customer_id, "companyId": c.company_id}
    return await node._request(token, "PUT", f"/saas-api/public-api/update-saas-subscription/{c.location_id}", json_body=body, version="2021-04-15", action_name="update_saas_subscription_deprecated")


GHL_OPERATION_CONFIGS += [
    GHLGetAgencyPlansConfig,
    GHLBulkDisableSaasConfig,
    GHLBulkEnableSaasConfig,
    GHLEnableSaasLocationConfig,
    GHLGetLocationSubscriptionConfig,
    GHLLocationsConfig,
    GHLPauseLocationConfig,
    GHLGetSaasLocationsConfig,
    GHLGetSaasPlanConfig,
    GHLUpdateRebillingConfig,
    GHLGeneratePaymentLinkConfig,
    GHLGetAgencyPlansDeprecatedConfig,
    GHLBulkDisableSaasDeprecatedConfig,
    GHLBulkEnableSaasDeprecatedConfig,
    GHLEnableSaasLocationDeprecatedConfig,
    GHLGetLocationSubscriptionDeprecatedConfig,
    GHLLocationsDeprecatedConfig,
    GHLPauseLocationDeprecatedConfig,
    GHLGetSaasLocationsDeprecatedConfig,
    GHLGetSaasPlanDeprecatedConfig,
    GHLUpdateRebillingDeprecatedConfig,
    GHLUpdateSaasSubscriptionDeprecatedConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_agency_plans": _get_agency_plans,
    "bulk_disable_saas": _bulk_disable_saas,
    "bulk_enable_saas": _bulk_enable_saas,
    "enable_saas_location": _enable_saas_location,
    "get_location_subscription": _get_location_subscription,
    "locations": _locations,
    "pause_location": _pause_location,
    "get_saas_locations": _get_saas_locations,
    "get_saas_plan": _get_saas_plan,
    "update_rebilling": _update_rebilling,
    "generate_payment_link": _generate_payment_link,
    "get_agency_plans_deprecated": _get_agency_plans_deprecated,
    "bulk_disable_saas_deprecated": _bulk_disable_saas_deprecated,
    "bulk_enable_saas_deprecated": _bulk_enable_saas_deprecated,
    "enable_saas_location_deprecated": _enable_saas_location_deprecated,
    "get_location_subscription_deprecated": _get_location_subscription_deprecated,
    "locations_deprecated": _locations_deprecated,
    "pause_location_deprecated": _pause_location_deprecated,
    "get_saas_locations_deprecated": _get_saas_locations_deprecated,
    "get_saas_plan_deprecated": _get_saas_plan_deprecated,
    "update_rebilling_deprecated": _update_rebilling_deprecated,
    "update_saas_subscription_deprecated": _update_saas_subscription_deprecated,
})


# ---- snapshots.py ----
class GHLGetSnapshotsConfig(BaseModel):
    """List snapshots for an agency (company)."""

    operation: Literal["get_snapshots"] = Field(
        "get_snapshots",
        json_schema_extra={
            "const": "get_snapshots", "ui:hidden": True,
            "x-category": "Snapshots", "x-is-trigger": False,
            "x-display-name": "List Snapshots",
        },
        title="List Snapshots",
    )
    company_id: str = Field(..., title="Company ID", description="Agency (company) id")


class GHLCreateSnapshotShareLinkConfig(BaseModel):
    """Create a share link for a snapshot."""

    operation: Literal["create_snapshot_share_link"] = Field(
        "create_snapshot_share_link",
        json_schema_extra={
            "const": "create_snapshot_share_link", "ui:hidden": True,
            "x-category": "Snapshots", "x-is-trigger": False,
            "x-display-name": "Create Snapshot Share Link",
        },
        title="Create Snapshot Share Link",
    )
    company_id: str = Field(..., title="Company ID", description="Agency (company) id")
    snapshot_id: str = Field(..., title="Snapshot ID", description="The snapshot to share")
    share_type: str = Field(
        ..., title="Share Type",
        json_schema_extra={
            "enum": ["link", "permanent_link", "agency_link", "location_link"],
            "x-enum-searchable": True,
        },
    )
    relationship_number: Optional[str] = Field(None, title="Relationship Number")
    share_location_id: Optional[str] = Field(None, title="Share Location ID")


class GHLGetSnapshotPushConfig(BaseModel):
    """Get snapshot push status between two dates."""

    operation: Literal["get_snapshot_push"] = Field(
        "get_snapshot_push",
        json_schema_extra={
            "const": "get_snapshot_push", "ui:hidden": True,
            "x-category": "Snapshots", "x-is-trigger": False,
            "x-display-name": "Get Snapshot Push Between Dates",
        },
        title="Get Snapshot Push Between Dates",
    )
    snapshot_id: str = Field(..., title="Snapshot ID", description="The snapshot id")
    company_id: str = Field(..., title="Company ID", description="Agency (company) id")
    from_date: str = Field(..., title="From", description="Start date (epoch/ISO)")
    to_date: str = Field(..., title="To", description="End date (epoch/ISO)")
    last_doc: str = Field(..., title="Last Doc", description="Cursor for pagination")
    limit: str = Field(..., title="Limit", description="Max results to return")


class GHLGetLatestSnapshotPushConfig(BaseModel):
    """Get the last snapshot push for a location."""

    operation: Literal["get_latest_snapshot_push"] = Field(
        "get_latest_snapshot_push",
        json_schema_extra={
            "const": "get_latest_snapshot_push", "ui:hidden": True,
            "x-category": "Snapshots", "x-is-trigger": False,
            "x-display-name": "Get Last Snapshot Push",
        },
        title="Get Last Snapshot Push",
    )
    snapshot_id: str = Field(..., title="Snapshot ID", description="The snapshot id")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    company_id: str = Field(..., title="Company ID", description="Agency (company) id")


async def _get_snapshots(node, c, token):
    params = {"companyId": c.company_id}
    return await node._request(token, "GET", "/snapshots/", params=params, action_name="get_snapshots")


async def _create_snapshot_share_link(node, c, token):
    params = {"companyId": c.company_id}
    body = {
        "snapshot_id": c.snapshot_id, "share_type": c.share_type,
        "relationship_number": c.relationship_number, "share_location_id": c.share_location_id,
    }
    return await node._request(
        token, "POST", "/snapshots/share/link", params=params, json_body=body,
        action_name="create_snapshot_share_link",
    )


async def _get_snapshot_push(node, c, token):
    params = {
        "companyId": c.company_id, "from": c.from_date, "to": c.to_date,
        "lastDoc": c.last_doc, "limit": c.limit,
    }
    return await node._request(
        token, "GET", f"/snapshots/snapshot-status/{c.snapshot_id}", params=params,
        action_name="get_snapshot_push",
    )


async def _get_latest_snapshot_push(node, c, token):
    params = {"companyId": c.company_id}
    return await node._request(
        token, "GET",
        f"/snapshots/snapshot-status/{c.snapshot_id}/location/{c.location_id}",
        params=params, action_name="get_latest_snapshot_push",
    )


GHL_OPERATION_CONFIGS += [
    GHLGetSnapshotsConfig,
    GHLCreateSnapshotShareLinkConfig,
    GHLGetSnapshotPushConfig,
    GHLGetLatestSnapshotPushConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_snapshots": _get_snapshots,
    "create_snapshot_share_link": _create_snapshot_share_link,
    "get_snapshot_push": _get_snapshot_push,
    "get_latest_snapshot_push": _get_latest_snapshot_push,
})


# ---- social_media_posting.py ----
class GHLStartFacebookOAuthConfig(BaseModel):
    """Start the Facebook OAuth connection flow for social planner."""

    operation: Literal["start_facebook_oauth"] = Field(
        "start_facebook_oauth",
        json_schema_extra={
            "const": "start_facebook_oauth", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Start Facebook OAuth",
        },
        title="Start Facebook OAuth",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    user_id: str = Field(..., title="User ID")
    page: Optional[str] = Field(None, title="Page")
    reconnect: Optional[str] = Field(
        None, title="Reconnect",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLStartGoogleOAuthConfig(BaseModel):
    """Start the Google (GMB) OAuth connection flow for social planner."""

    operation: Literal["start_google_oauth"] = Field(
        "start_google_oauth",
        json_schema_extra={
            "const": "start_google_oauth", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Start Google OAuth",
        },
        title="Start Google OAuth",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    user_id: str = Field(..., title="User ID")
    page: Optional[str] = Field(None, title="Page")
    reconnect: Optional[str] = Field(
        None, title="Reconnect",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLStartInstagramOAuthConfig(BaseModel):
    """Start the Instagram OAuth connection flow for social planner."""

    operation: Literal["start_instagram_oauth"] = Field(
        "start_instagram_oauth",
        json_schema_extra={
            "const": "start_instagram_oauth", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Start Instagram OAuth",
        },
        title="Start Instagram OAuth",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    user_id: str = Field(..., title="User ID")
    page: Optional[str] = Field(None, title="Page")
    reconnect: Optional[str] = Field(
        None, title="Reconnect",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLStartLinkedinOAuthConfig(BaseModel):
    """Start the LinkedIn OAuth connection flow for social planner."""

    operation: Literal["start_linkedin_oauth"] = Field(
        "start_linkedin_oauth",
        json_schema_extra={
            "const": "start_linkedin_oauth", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Start LinkedIn OAuth",
        },
        title="Start LinkedIn OAuth",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    user_id: str = Field(..., title="User ID")
    page: Optional[str] = Field(None, title="Page")
    reconnect: Optional[str] = Field(
        None, title="Reconnect",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLStartTiktokBusinessOAuthConfig(BaseModel):
    """Start the TikTok Business OAuth connection flow for social planner."""

    operation: Literal["start_tiktok_business_oauth"] = Field(
        "start_tiktok_business_oauth",
        json_schema_extra={
            "const": "start_tiktok_business_oauth", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Start TikTok Business OAuth",
        },
        title="Start TikTok Business OAuth",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    user_id: str = Field(..., title="User ID")
    page: Optional[str] = Field(None, title="Page")
    reconnect: Optional[str] = Field(
        None, title="Reconnect",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLStartTiktokOAuthConfig(BaseModel):
    """Start the TikTok OAuth connection flow for social planner."""

    operation: Literal["start_tiktok_oauth"] = Field(
        "start_tiktok_oauth",
        json_schema_extra={
            "const": "start_tiktok_oauth", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Start TikTok OAuth",
        },
        title="Start TikTok OAuth",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    user_id: str = Field(..., title="User ID")
    page: Optional[str] = Field(None, title="Page")
    reconnect: Optional[str] = Field(
        None, title="Reconnect",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLStartTwitterOAuthConfig(BaseModel):
    """Start the Twitter/X OAuth connection flow for social planner."""

    operation: Literal["start_twitter_oauth"] = Field(
        "start_twitter_oauth",
        json_schema_extra={
            "const": "start_twitter_oauth", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Start Twitter OAuth",
        },
        title="Start Twitter OAuth",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    user_id: str = Field(..., title="User ID")
    page: Optional[str] = Field(None, title="Page")
    reconnect: Optional[str] = Field(
        None, title="Reconnect",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLGetFacebookPageGroupConfig(BaseModel):
    """Get Facebook pages/groups for an OAuth account."""

    operation: Literal["get_facebook_page_group"] = Field(
        "get_facebook_page_group",
        json_schema_extra={
            "const": "get_facebook_page_group", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get Facebook Pages",
        },
        title="Get Facebook Pages",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")


class GHLAttachFacebookPageGroupConfig(BaseModel):
    """Attach a Facebook page/group to the social planner account."""

    operation: Literal["attach_facebook_page_group"] = Field(
        "attach_facebook_page_group",
        json_schema_extra={
            "const": "attach_facebook_page_group", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Attach Facebook Page",
        },
        title="Attach Facebook Page",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")
    type: Optional[str] = Field(None, title="Type")
    origin_id: Optional[str] = Field(None, title="Origin ID")
    name: Optional[str] = Field(None, title="Name")
    avatar: Optional[str] = Field(None, title="Avatar")
    company_id: Optional[str] = Field(None, title="Company ID")


class GHLGetGoogleLocationsConfig(BaseModel):
    """Get Google (GMB) locations for an OAuth account."""

    operation: Literal["get_google_locations"] = Field(
        "get_google_locations",
        json_schema_extra={
            "const": "get_google_locations", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get Google Locations",
        },
        title="Get Google Locations",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")


class GHLSetGoogleLocationsConfig(BaseModel):
    """Attach a Google (GMB) location to the social planner account."""

    operation: Literal["set_google_locations"] = Field(
        "set_google_locations",
        json_schema_extra={
            "const": "set_google_locations", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Set Google Location",
        },
        title="Set Google Location",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")
    location: Optional[str] = Field(None, title="Location", description="JSON object of the GMB location")
    account: Optional[str] = Field(None, title="Account", description="JSON object of the GMB account")
    company_id: Optional[str] = Field(None, title="Company ID")


class GHLGetInstagramPageGroupConfig(BaseModel):
    """Get Instagram accounts for an OAuth account."""

    operation: Literal["get_instagram_page_group"] = Field(
        "get_instagram_page_group",
        json_schema_extra={
            "const": "get_instagram_page_group", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get Instagram Accounts",
        },
        title="Get Instagram Accounts",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")


class GHLAttachInstagramPageGroupConfig(BaseModel):
    """Attach an Instagram account to the social planner account."""

    operation: Literal["attach_instagram_page_group"] = Field(
        "attach_instagram_page_group",
        json_schema_extra={
            "const": "attach_instagram_page_group", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Attach Instagram Account",
        },
        title="Attach Instagram Account",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")
    page_id: str = Field(..., title="Page ID")
    origin_id: Optional[str] = Field(None, title="Origin ID")
    name: Optional[str] = Field(None, title="Name")
    avatar: Optional[str] = Field(None, title="Avatar")
    company_id: Optional[str] = Field(None, title="Company ID")


class GHLGetLinkedinPageProfileConfig(BaseModel):
    """Get LinkedIn pages/profiles for an OAuth account."""

    operation: Literal["get_linkedin_page_profile"] = Field(
        "get_linkedin_page_profile",
        json_schema_extra={
            "const": "get_linkedin_page_profile", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get LinkedIn Pages",
        },
        title="Get LinkedIn Pages",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")


class GHLAttachLinkedinPageProfileConfig(BaseModel):
    """Attach a LinkedIn page/profile to the social planner account."""

    operation: Literal["attach_linkedin_page_profile"] = Field(
        "attach_linkedin_page_profile",
        json_schema_extra={
            "const": "attach_linkedin_page_profile", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Attach LinkedIn Page",
        },
        title="Attach LinkedIn Page",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")
    type: Optional[str] = Field(None, title="Type")
    origin_id: Optional[str] = Field(None, title="Origin ID")
    name: Optional[str] = Field(None, title="Name")
    avatar: Optional[str] = Field(None, title="Avatar")
    urn: Optional[str] = Field(None, title="URN")
    company_id: Optional[str] = Field(None, title="Company ID")


class GHLGetTiktokBusinessProfileConfig(BaseModel):
    """Get TikTok Business profiles for an OAuth account."""

    operation: Literal["get_tiktok_business_profile"] = Field(
        "get_tiktok_business_profile",
        json_schema_extra={
            "const": "get_tiktok_business_profile", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get TikTok Business Profiles",
        },
        title="Get TikTok Business Profiles",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")


class GHLGetTiktokProfileConfig(BaseModel):
    """Get TikTok profiles for an OAuth account."""

    operation: Literal["get_tiktok_profile"] = Field(
        "get_tiktok_profile",
        json_schema_extra={
            "const": "get_tiktok_profile", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get TikTok Profiles",
        },
        title="Get TikTok Profiles",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")


class GHLAttachTiktokProfileConfig(BaseModel):
    """Attach a TikTok profile to the social planner account."""

    operation: Literal["attach_tiktok_profile"] = Field(
        "attach_tiktok_profile",
        json_schema_extra={
            "const": "attach_tiktok_profile", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Attach TikTok Profile",
        },
        title="Attach TikTok Profile",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")
    type: Optional[str] = Field(None, title="Type")
    origin_id: Optional[str] = Field(None, title="Origin ID")
    name: Optional[str] = Field(None, title="Name")
    avatar: Optional[str] = Field(None, title="Avatar")
    verified: Optional[str] = Field(
        None, title="Verified",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    username: Optional[str] = Field(None, title="Username")
    company_id: Optional[str] = Field(None, title="Company ID")


class GHLGetTwitterProfileConfig(BaseModel):
    """Get Twitter/X profiles for an OAuth account."""

    operation: Literal["get_twitter_profile"] = Field(
        "get_twitter_profile",
        json_schema_extra={
            "const": "get_twitter_profile", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get Twitter Profiles",
        },
        title="Get Twitter Profiles",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")


class GHLAttachTwitterProfileConfig(BaseModel):
    """Attach a Twitter/X profile to the social planner account."""

    operation: Literal["attach_twitter_profile"] = Field(
        "attach_twitter_profile",
        json_schema_extra={
            "const": "attach_twitter_profile", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Attach Twitter Profile",
        },
        title="Attach Twitter Profile",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_id: str = Field(..., title="Account ID")
    origin_id: Optional[str] = Field(None, title="Origin ID")
    name: Optional[str] = Field(None, title="Name")
    username: Optional[str] = Field(None, title="Username")
    avatar: Optional[str] = Field(None, title="Avatar")
    protected: Optional[str] = Field(
        None, title="Protected",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    verified: Optional[str] = Field(
        None, title="Verified",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    company_id: Optional[str] = Field(None, title="Company ID")


class GHLGetSocialMediaStatisticsConfig(BaseModel):
    """Get social media posting statistics for the given profiles."""

    operation: Literal["get_social_media_statistics"] = Field(
        "get_social_media_statistics",
        json_schema_extra={
            "const": "get_social_media_statistics", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get Social Media Statistics",
        },
        title="Get Social Media Statistics",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    profile_ids: str = Field(..., title="Profile IDs", description="Comma-separated profile ids")
    platforms: Optional[str] = Field(None, title="Platforms", description="Comma-separated platform names")


class GHLGetSocialAccountConfig(BaseModel):
    """List connected social planner accounts and groups for a location."""

    operation: Literal["get_social_account"] = Field(
        "get_social_account",
        json_schema_extra={
            "const": "get_social_account", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "List Social Accounts",
        },
        title="List Social Accounts",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLDeleteSocialAccountConfig(BaseModel):
    """Delete a connected social planner account."""

    operation: Literal["delete_social_account"] = Field(
        "delete_social_account",
        json_schema_extra={
            "const": "delete_social_account", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Delete Social Account",
        },
        title="Delete Social Account",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Account ID", description="The social account to delete")
    company_id: Optional[str] = Field(None, title="Company ID")
    user_id: Optional[str] = Field(None, title="User ID")


class GHLGetSocialCategoriesConfig(BaseModel):
    """List social planner categories for a location."""

    operation: Literal["get_social_categories"] = Field(
        "get_social_categories",
        json_schema_extra={
            "const": "get_social_categories", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "List Social Categories",
        },
        title="List Social Categories",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    search_text: Optional[str] = Field(None, title="Search Text")
    limit: Optional[str] = Field(None, title="Limit")
    skip: Optional[str] = Field(None, title="Skip")


class GHLGetSocialCategoryConfig(BaseModel):
    """Get a social planner category by id."""

    operation: Literal["get_social_category"] = Field(
        "get_social_category",
        json_schema_extra={
            "const": "get_social_category", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get Social Category",
        },
        title="Get Social Category",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Category ID", description="The category to fetch")


class GHLUploadSocialCSVConfig(BaseModel):
    """Upload a CSV of posts for bulk scheduling (multipart file upload)."""

    operation: Literal["upload_social_csv"] = Field(
        "upload_social_csv",
        json_schema_extra={
            "const": "upload_social_csv", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Upload Social CSV",
        },
        title="Upload Social CSV",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    file: str = Field(..., title="File", description="The CSV file content/reference to upload (multipart 'file' field)")


class GHLGetSocialCSVUploadStatusConfig(BaseModel):
    """List CSV upload statuses for a location."""

    operation: Literal["get_social_csv_upload_status"] = Field(
        "get_social_csv_upload_status",
        json_schema_extra={
            "const": "get_social_csv_upload_status", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "List CSV Upload Status",
        },
        title="List CSV Upload Status",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    skip: Optional[str] = Field(None, title="Skip")
    limit: Optional[str] = Field(None, title="Limit")
    include_users: Optional[str] = Field(
        None, title="Include Users",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    user_id: Optional[str] = Field(None, title="User ID")


class GHLDeleteSocialCSVPostConfig(BaseModel):
    """Delete a single post from a CSV upload."""

    operation: Literal["delete_social_csv_post"] = Field(
        "delete_social_csv_post",
        json_schema_extra={
            "const": "delete_social_csv_post", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Delete CSV Post",
        },
        title="Delete CSV Post",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    csv_id: str = Field(..., title="CSV ID")
    post_id: str = Field(..., title="Post ID")


class GHLGetSocialCSVPostConfig(BaseModel):
    """Get the posts contained in a CSV upload."""

    operation: Literal["get_social_csv_post"] = Field(
        "get_social_csv_post",
        json_schema_extra={
            "const": "get_social_csv_post", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get CSV Posts",
        },
        title="Get CSV Posts",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="CSV ID")
    skip: Optional[str] = Field(None, title="Skip")
    limit: Optional[str] = Field(None, title="Limit")


class GHLStartSocialCSVFinalizeConfig(BaseModel):
    """Start finalizing (scheduling) a CSV upload's posts."""

    operation: Literal["start_social_csv_finalize"] = Field(
        "start_social_csv_finalize",
        json_schema_extra={
            "const": "start_social_csv_finalize", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Finalize CSV Upload",
        },
        title="Finalize CSV Upload",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="CSV ID")
    user_id: Optional[str] = Field(None, title="User ID")


class GHLDeleteSocialCSVConfig(BaseModel):
    """Delete a CSV upload and all its posts."""

    operation: Literal["delete_social_csv"] = Field(
        "delete_social_csv",
        json_schema_extra={
            "const": "delete_social_csv", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Delete CSV Upload",
        },
        title="Delete CSV Upload",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="CSV ID")


class GHLCreateSocialPostConfig(BaseModel):
    """Create a social planner post."""

    operation: Literal["create_social_post"] = Field(
        "create_social_post",
        json_schema_extra={
            "const": "create_social_post", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Create Social Post",
        },
        title="Create Social Post",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_ids: str = Field(..., title="Account IDs", description="Comma-separated social account ids")
    type: str = Field(..., title="Type", description="JSON object describing the post type")
    user_id: str = Field(..., title="User ID")
    summary: Optional[str] = Field(None, title="Summary", description="Post caption/body text")
    media: Optional[str] = Field(None, title="Media", description="JSON array of media objects")
    status: Optional[str] = Field(None, title="Status", description="JSON object of post status")
    schedule_date: Optional[str] = Field(None, title="Schedule Date")
    created_by: Optional[str] = Field(None, title="Created By")
    follow_up_comment: Optional[str] = Field(None, title="Follow Up Comment")
    og_tags_details: Optional[str] = Field(None, title="OG Tags Details", description="JSON object")
    post_approval_details: Optional[str] = Field(None, title="Post Approval Details", description="JSON object")
    schedule_time_updated: Optional[str] = Field(
        None, title="Schedule Time Updated",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags")
    category_id: Optional[str] = Field(None, title="Category ID")
    tiktok_post_details: Optional[str] = Field(None, title="TikTok Post Details", description="JSON object")
    gmb_post_details: Optional[str] = Field(None, title="GMB Post Details", description="JSON object")


class GHLBulkDeleteSocialPlannerPostsConfig(BaseModel):
    """Bulk delete social planner posts by ids."""

    operation: Literal["bulk_delete_social_planner_posts"] = Field(
        "bulk_delete_social_planner_posts",
        json_schema_extra={
            "const": "bulk_delete_social_planner_posts", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Bulk Delete Social Posts",
        },
        title="Bulk Delete Social Posts",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    post_ids: Optional[str] = Field(None, title="Post IDs", description="Comma-separated post ids")


class GHLGetSocialPostsConfig(BaseModel):
    """Search/list social planner posts."""

    operation: Literal["get_social_posts"] = Field(
        "get_social_posts",
        json_schema_extra={
            "const": "get_social_posts", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "List Social Posts",
        },
        title="List Social Posts",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    skip: str = Field(..., title="Skip")
    limit: str = Field(..., title="Limit")
    from_date: str = Field(..., title="From Date")
    to_date: str = Field(..., title="To Date")
    include_users: str = Field(..., title="Include Users")
    type: Optional[str] = Field(None, title="Type")
    accounts: Optional[str] = Field(None, title="Accounts")
    post_type: Optional[str] = Field(None, title="Post Type", description="JSON object of post type filter")


class GHLGetSocialPostConfig(BaseModel):
    """Get a social planner post by id."""

    operation: Literal["get_social_post"] = Field(
        "get_social_post",
        json_schema_extra={
            "const": "get_social_post", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get Social Post",
        },
        title="Get Social Post",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Post ID", description="The post to fetch")


class GHLEditSocialPostConfig(BaseModel):
    """Edit an existing social planner post."""

    operation: Literal["edit_social_post"] = Field(
        "edit_social_post",
        json_schema_extra={
            "const": "edit_social_post", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Edit Social Post",
        },
        title="Edit Social Post",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Post ID", description="The post to edit")
    type: str = Field(..., title="Type", description="JSON object describing the post type")
    account_ids: Optional[str] = Field(None, title="Account IDs", description="Comma-separated social account ids")
    summary: Optional[str] = Field(None, title="Summary", description="Post caption/body text")
    media: Optional[str] = Field(None, title="Media", description="JSON array of media objects")
    status: Optional[str] = Field(None, title="Status", description="JSON object of post status")
    schedule_date: Optional[str] = Field(None, title="Schedule Date")
    created_by: Optional[str] = Field(None, title="Created By")
    follow_up_comment: Optional[str] = Field(None, title="Follow Up Comment")
    og_tags_details: Optional[str] = Field(None, title="OG Tags Details", description="JSON object")
    post_approval_details: Optional[str] = Field(None, title="Post Approval Details", description="JSON object")
    schedule_time_updated: Optional[str] = Field(
        None, title="Schedule Time Updated",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    tags: Optional[str] = Field(None, title="Tags", description="Comma-separated tags")
    category_id: Optional[str] = Field(None, title="Category ID")
    tiktok_post_details: Optional[str] = Field(None, title="TikTok Post Details", description="JSON object")
    gmb_post_details: Optional[str] = Field(None, title="GMB Post Details", description="JSON object")
    user_id: Optional[str] = Field(None, title="User ID")


class GHLDeleteSocialPostConfig(BaseModel):
    """Delete a social planner post by id."""

    operation: Literal["delete_social_post"] = Field(
        "delete_social_post",
        json_schema_extra={
            "const": "delete_social_post", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Delete Social Post",
        },
        title="Delete Social Post",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    id: str = Field(..., title="Post ID", description="The post to delete")


class GHLSetSocialAccountsConfig(BaseModel):
    """Set accounts for a bulk CSV import."""

    operation: Literal["set_social_accounts"] = Field(
        "set_social_accounts",
        json_schema_extra={
            "const": "set_social_accounts", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Set Social Accounts",
        },
        title="Set Social Accounts",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    account_ids: str = Field(..., title="Account IDs", description="Comma-separated social account ids")
    file_path: str = Field(..., title="File Path")
    rows_count: str = Field(..., title="Rows Count")
    file_name: str = Field(..., title="File Name")
    approver: Optional[str] = Field(None, title="Approver")
    user_id: Optional[str] = Field(None, title="User ID")


class GHLGetSocialTagsConfig(BaseModel):
    """List social planner tags for a location."""

    operation: Literal["get_social_tags"] = Field(
        "get_social_tags",
        json_schema_extra={
            "const": "get_social_tags", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "List Social Tags",
        },
        title="List Social Tags",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    search_text: Optional[str] = Field(None, title="Search Text")
    limit: Optional[str] = Field(None, title="Limit")
    skip: Optional[str] = Field(None, title="Skip")


class GHLGetSocialTagsByIdsConfig(BaseModel):
    """Get social planner tags by their ids."""

    operation: Literal["get_social_tags_by_ids"] = Field(
        "get_social_tags_by_ids",
        json_schema_extra={
            "const": "get_social_tags_by_ids", "ui:hidden": True,
            "x-category": "Social Posting", "x-is-trigger": False,
            "x-display-name": "Get Social Tags By IDs",
        },
        title="Get Social Tags By IDs",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    tag_ids: str = Field(..., title="Tag IDs", description="Comma-separated tag ids")


async def _start_facebook_oauth(node, c, token):
    params = {"locationId": c.location_id, "userId": c.user_id, "page": c.page, "reconnect": _ghl_bool(c.reconnect)}
    return await node._request(token, "GET", "/social-media-posting/oauth/facebook/start", params=params, action_name="start_facebook_oauth")


async def _start_google_oauth(node, c, token):
    params = {"locationId": c.location_id, "userId": c.user_id, "page": c.page, "reconnect": _ghl_bool(c.reconnect)}
    return await node._request(token, "GET", "/social-media-posting/oauth/google/start", params=params, action_name="start_google_oauth")


async def _start_instagram_oauth(node, c, token):
    params = {"locationId": c.location_id, "userId": c.user_id, "page": c.page, "reconnect": _ghl_bool(c.reconnect)}
    return await node._request(token, "GET", "/social-media-posting/oauth/instagram/start", params=params, action_name="start_instagram_oauth")


async def _start_linkedin_oauth(node, c, token):
    params = {"locationId": c.location_id, "userId": c.user_id, "page": c.page, "reconnect": _ghl_bool(c.reconnect)}
    return await node._request(token, "GET", "/social-media-posting/oauth/linkedin/start", params=params, action_name="start_linkedin_oauth")


async def _start_tiktok_business_oauth(node, c, token):
    params = {"locationId": c.location_id, "userId": c.user_id, "page": c.page, "reconnect": _ghl_bool(c.reconnect)}
    return await node._request(token, "GET", "/social-media-posting/oauth/tiktok-business/start", params=params, action_name="start_tiktok_business_oauth")


async def _start_tiktok_oauth(node, c, token):
    params = {"locationId": c.location_id, "userId": c.user_id, "page": c.page, "reconnect": _ghl_bool(c.reconnect)}
    return await node._request(token, "GET", "/social-media-posting/oauth/tiktok/start", params=params, action_name="start_tiktok_oauth")


async def _start_twitter_oauth(node, c, token):
    params = {"locationId": c.location_id, "userId": c.user_id, "page": c.page, "reconnect": _ghl_bool(c.reconnect)}
    return await node._request(token, "GET", "/social-media-posting/oauth/twitter/start", params=params, action_name="start_twitter_oauth")


async def _get_facebook_page_group(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/oauth/{c.location_id}/facebook/accounts/{c.account_id}", action_name="get_facebook_page_group")


async def _attach_facebook_page_group(node, c, token):
    body = {"type": c.type, "originId": c.origin_id, "name": c.name, "avatar": c.avatar, "companyId": c.company_id}
    return await node._request(token, "POST", f"/social-media-posting/oauth/{c.location_id}/facebook/accounts/{c.account_id}", json_body=body, action_name="attach_facebook_page_group")


async def _get_google_locations(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/oauth/{c.location_id}/google/locations/{c.account_id}", action_name="get_google_locations")


async def _set_google_locations(node, c, token):
    body = {"location": _ghl_json(c.location), "account": _ghl_json(c.account), "companyId": c.company_id}
    return await node._request(token, "POST", f"/social-media-posting/oauth/{c.location_id}/google/locations/{c.account_id}", json_body=body, action_name="set_google_locations")


async def _get_instagram_page_group(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/oauth/{c.location_id}/instagram/accounts/{c.account_id}", action_name="get_instagram_page_group")


async def _attach_instagram_page_group(node, c, token):
    body = {"originId": c.origin_id, "name": c.name, "avatar": c.avatar, "pageId": c.page_id, "companyId": c.company_id}
    return await node._request(token, "POST", f"/social-media-posting/oauth/{c.location_id}/instagram/accounts/{c.account_id}", json_body=body, action_name="attach_instagram_page_group")


async def _get_linkedin_page_profile(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/oauth/{c.location_id}/linkedin/accounts/{c.account_id}", action_name="get_linkedin_page_profile")


async def _attach_linkedin_page_profile(node, c, token):
    body = {"type": c.type, "originId": c.origin_id, "name": c.name, "avatar": c.avatar, "urn": c.urn, "companyId": c.company_id}
    return await node._request(token, "POST", f"/social-media-posting/oauth/{c.location_id}/linkedin/accounts/{c.account_id}", json_body=body, action_name="attach_linkedin_page_profile")


async def _get_tiktok_business_profile(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/oauth/{c.location_id}/tiktok-business/accounts/{c.account_id}", action_name="get_tiktok_business_profile")


async def _get_tiktok_profile(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/oauth/{c.location_id}/tiktok/accounts/{c.account_id}", action_name="get_tiktok_profile")


async def _attach_tiktok_profile(node, c, token):
    body = {
        "type": c.type, "originId": c.origin_id, "name": c.name, "avatar": c.avatar,
        "verified": _ghl_bool(c.verified), "username": c.username, "companyId": c.company_id,
    }
    return await node._request(token, "POST", f"/social-media-posting/oauth/{c.location_id}/tiktok/accounts/{c.account_id}", json_body=body, action_name="attach_tiktok_profile")


async def _get_twitter_profile(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/oauth/{c.location_id}/twitter/accounts/{c.account_id}", action_name="get_twitter_profile")


async def _attach_twitter_profile(node, c, token):
    body = {
        "originId": c.origin_id, "name": c.name, "username": c.username, "avatar": c.avatar,
        "protected": _ghl_bool(c.protected), "verified": _ghl_bool(c.verified), "companyId": c.company_id,
    }
    return await node._request(token, "POST", f"/social-media-posting/oauth/{c.location_id}/twitter/accounts/{c.account_id}", json_body=body, action_name="attach_twitter_profile")


async def _get_social_media_statistics(node, c, token):
    params = {"locationId": c.location_id}
    body = {"profileIds": _ghl_csv(c.profile_ids), "platforms": _ghl_csv(c.platforms)}
    return await node._request(token, "POST", "/social-media-posting/statistics", params=params, json_body=body, action_name="get_social_media_statistics")


async def _get_social_account(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/{c.location_id}/accounts", action_name="get_social_account")


async def _delete_social_account(node, c, token):
    params = {"companyId": c.company_id, "userId": c.user_id}
    return await node._request(token, "DELETE", f"/social-media-posting/{c.location_id}/accounts/{c.id}", params=params, action_name="delete_social_account")


async def _get_social_categories(node, c, token):
    params = {"searchText": c.search_text, "limit": c.limit, "skip": c.skip}
    return await node._request(token, "GET", f"/social-media-posting/{c.location_id}/categories", params=params, action_name="get_social_categories")


async def _get_social_category(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/{c.location_id}/categories/{c.id}", action_name="get_social_category")


async def _upload_social_csv(node, c, token):
    # Multipart CSV upload: the documented body field 'file' is passed as a form field.
    data = {"file": c.file}
    return await node._request(token, "POST", f"/social-media-posting/{c.location_id}/csv", data=data, action_name="upload_social_csv")


async def _get_social_csv_upload_status(node, c, token):
    params = {"skip": c.skip, "limit": c.limit, "includeUsers": _ghl_bool(c.include_users), "userId": c.user_id}
    return await node._request(token, "GET", f"/social-media-posting/{c.location_id}/csv", params=params, action_name="get_social_csv_upload_status")


async def _delete_social_csv_post(node, c, token):
    return await node._request(token, "DELETE", f"/social-media-posting/{c.location_id}/csv/{c.csv_id}/post/{c.post_id}", action_name="delete_social_csv_post")


async def _get_social_csv_post(node, c, token):
    params = {"skip": c.skip, "limit": c.limit}
    return await node._request(token, "GET", f"/social-media-posting/{c.location_id}/csv/{c.id}", params=params, action_name="get_social_csv_post")


async def _start_social_csv_finalize(node, c, token):
    body = {"userId": c.user_id}
    return await node._request(token, "PATCH", f"/social-media-posting/{c.location_id}/csv/{c.id}", json_body=body, action_name="start_social_csv_finalize")


async def _delete_social_csv(node, c, token):
    return await node._request(token, "DELETE", f"/social-media-posting/{c.location_id}/csv/{c.id}", action_name="delete_social_csv")


async def _create_social_post(node, c, token):
    body = {
        "accountIds": _ghl_csv(c.account_ids), "summary": c.summary, "media": _ghl_json(c.media),
        "status": _ghl_json(c.status), "scheduleDate": c.schedule_date, "createdBy": c.created_by,
        "followUpComment": c.follow_up_comment, "ogTagsDetails": _ghl_json(c.og_tags_details),
        "type": _ghl_json(c.type), "postApprovalDetails": _ghl_json(c.post_approval_details),
        "scheduleTimeUpdated": _ghl_bool(c.schedule_time_updated), "tags": _ghl_csv(c.tags),
        "categoryId": c.category_id, "tiktokPostDetails": _ghl_json(c.tiktok_post_details),
        "gmbPostDetails": _ghl_json(c.gmb_post_details), "userId": c.user_id,
    }
    return await node._request(token, "POST", f"/social-media-posting/{c.location_id}/posts", json_body=body, action_name="create_social_post")


async def _bulk_delete_social_planner_posts(node, c, token):
    body = {"postIds": _ghl_csv(c.post_ids)}
    return await node._request(token, "POST", f"/social-media-posting/{c.location_id}/posts/bulk-delete", json_body=body, action_name="bulk_delete_social_planner_posts")


async def _get_social_posts(node, c, token):
    body = {
        "type": c.type, "accounts": c.accounts, "skip": c.skip, "limit": c.limit,
        "fromDate": c.from_date, "toDate": c.to_date, "includeUsers": c.include_users,
        "postType": _ghl_json(c.post_type),
    }
    return await node._request(token, "POST", f"/social-media-posting/{c.location_id}/posts/list", json_body=body, action_name="get_social_posts")


async def _get_social_post(node, c, token):
    return await node._request(token, "GET", f"/social-media-posting/{c.location_id}/posts/{c.id}", action_name="get_social_post")


async def _edit_social_post(node, c, token):
    body = {
        "accountIds": _ghl_csv(c.account_ids), "summary": c.summary, "media": _ghl_json(c.media),
        "status": _ghl_json(c.status), "scheduleDate": c.schedule_date, "createdBy": c.created_by,
        "followUpComment": c.follow_up_comment, "ogTagsDetails": _ghl_json(c.og_tags_details),
        "type": _ghl_json(c.type), "postApprovalDetails": _ghl_json(c.post_approval_details),
        "scheduleTimeUpdated": _ghl_bool(c.schedule_time_updated), "tags": _ghl_csv(c.tags),
        "categoryId": c.category_id, "tiktokPostDetails": _ghl_json(c.tiktok_post_details),
        "gmbPostDetails": _ghl_json(c.gmb_post_details), "userId": c.user_id,
    }
    return await node._request(token, "PUT", f"/social-media-posting/{c.location_id}/posts/{c.id}", json_body=body, action_name="edit_social_post")


async def _delete_social_post(node, c, token):
    return await node._request(token, "DELETE", f"/social-media-posting/{c.location_id}/posts/{c.id}", action_name="delete_social_post")


async def _set_social_accounts(node, c, token):
    body = {
        "accountIds": _ghl_csv(c.account_ids), "filePath": c.file_path, "rowsCount": _ghl_num(c.rows_count),
        "fileName": c.file_name, "approver": c.approver, "userId": c.user_id,
    }
    return await node._request(token, "POST", f"/social-media-posting/{c.location_id}/set-accounts", json_body=body, action_name="set_social_accounts")


async def _get_social_tags(node, c, token):
    params = {"searchText": c.search_text, "limit": c.limit, "skip": c.skip}
    return await node._request(token, "GET", f"/social-media-posting/{c.location_id}/tags", params=params, action_name="get_social_tags")


async def _get_social_tags_by_ids(node, c, token):
    body = {"tagIds": _ghl_csv(c.tag_ids)}
    return await node._request(token, "POST", f"/social-media-posting/{c.location_id}/tags/details", json_body=body, action_name="get_social_tags_by_ids")


GHL_OPERATION_CONFIGS += [
    GHLStartFacebookOAuthConfig,
    GHLStartGoogleOAuthConfig,
    GHLStartInstagramOAuthConfig,
    GHLStartLinkedinOAuthConfig,
    GHLStartTiktokBusinessOAuthConfig,
    GHLStartTiktokOAuthConfig,
    GHLStartTwitterOAuthConfig,
    GHLGetFacebookPageGroupConfig,
    GHLAttachFacebookPageGroupConfig,
    GHLGetGoogleLocationsConfig,
    GHLSetGoogleLocationsConfig,
    GHLGetInstagramPageGroupConfig,
    GHLAttachInstagramPageGroupConfig,
    GHLGetLinkedinPageProfileConfig,
    GHLAttachLinkedinPageProfileConfig,
    GHLGetTiktokBusinessProfileConfig,
    GHLGetTiktokProfileConfig,
    GHLAttachTiktokProfileConfig,
    GHLGetTwitterProfileConfig,
    GHLAttachTwitterProfileConfig,
    GHLGetSocialMediaStatisticsConfig,
    GHLGetSocialAccountConfig,
    GHLDeleteSocialAccountConfig,
    GHLGetSocialCategoriesConfig,
    GHLGetSocialCategoryConfig,
    GHLUploadSocialCSVConfig,
    GHLGetSocialCSVUploadStatusConfig,
    GHLDeleteSocialCSVPostConfig,
    GHLGetSocialCSVPostConfig,
    GHLStartSocialCSVFinalizeConfig,
    GHLDeleteSocialCSVConfig,
    GHLCreateSocialPostConfig,
    GHLBulkDeleteSocialPlannerPostsConfig,
    GHLGetSocialPostsConfig,
    GHLGetSocialPostConfig,
    GHLEditSocialPostConfig,
    GHLDeleteSocialPostConfig,
    GHLSetSocialAccountsConfig,
    GHLGetSocialTagsConfig,
    GHLGetSocialTagsByIdsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "start_facebook_oauth": _start_facebook_oauth,
    "start_google_oauth": _start_google_oauth,
    "start_instagram_oauth": _start_instagram_oauth,
    "start_linkedin_oauth": _start_linkedin_oauth,
    "start_tiktok_business_oauth": _start_tiktok_business_oauth,
    "start_tiktok_oauth": _start_tiktok_oauth,
    "start_twitter_oauth": _start_twitter_oauth,
    "get_facebook_page_group": _get_facebook_page_group,
    "attach_facebook_page_group": _attach_facebook_page_group,
    "get_google_locations": _get_google_locations,
    "set_google_locations": _set_google_locations,
    "get_instagram_page_group": _get_instagram_page_group,
    "attach_instagram_page_group": _attach_instagram_page_group,
    "get_linkedin_page_profile": _get_linkedin_page_profile,
    "attach_linkedin_page_profile": _attach_linkedin_page_profile,
    "get_tiktok_business_profile": _get_tiktok_business_profile,
    "get_tiktok_profile": _get_tiktok_profile,
    "attach_tiktok_profile": _attach_tiktok_profile,
    "get_twitter_profile": _get_twitter_profile,
    "attach_twitter_profile": _attach_twitter_profile,
    "get_social_media_statistics": _get_social_media_statistics,
    "get_social_account": _get_social_account,
    "delete_social_account": _delete_social_account,
    "get_social_categories": _get_social_categories,
    "get_social_category": _get_social_category,
    "upload_social_csv": _upload_social_csv,
    "get_social_csv_upload_status": _get_social_csv_upload_status,
    "delete_social_csv_post": _delete_social_csv_post,
    "get_social_csv_post": _get_social_csv_post,
    "start_social_csv_finalize": _start_social_csv_finalize,
    "delete_social_csv": _delete_social_csv,
    "create_social_post": _create_social_post,
    "bulk_delete_social_planner_posts": _bulk_delete_social_planner_posts,
    "get_social_posts": _get_social_posts,
    "get_social_post": _get_social_post,
    "edit_social_post": _edit_social_post,
    "delete_social_post": _delete_social_post,
    "set_social_accounts": _set_social_accounts,
    "get_social_tags": _get_social_tags,
    "get_social_tags_by_ids": _get_social_tags_by_ids,
})


# ---- store.py ----
class GHLCreateShippingZoneConfig(BaseModel):
    """Create a shipping zone for a location."""

    operation: Literal["create_shipping_zone"] = Field(
        "create_shipping_zone",
        json_schema_extra={
            "const": "create_shipping_zone", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Create Shipping Zone",
        },
        title="Create Shipping Zone",
    )
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")
    name: str = Field(..., title="Name", description="Shipping zone name")
    countries: str = Field(..., title="Countries", description="JSON array of country objects covered by the zone")


class GHLListShippingZonesConfig(BaseModel):
    """List shipping zones for a location."""

    operation: Literal["list_shipping_zones"] = Field(
        "list_shipping_zones",
        json_schema_extra={
            "const": "list_shipping_zones", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "List Shipping Zones",
        },
        title="List Shipping Zones",
    )
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of results to skip (pagination)")
    with_shipping_rate: Optional[str] = Field(
        None, title="With Shipping Rate", description="Include shipping rates in the response",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLGetShippingZoneConfig(BaseModel):
    """Get a shipping zone by id."""

    operation: Literal["get_shipping_zone"] = Field(
        "get_shipping_zone",
        json_schema_extra={
            "const": "get_shipping_zone", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Get Shipping Zone",
        },
        title="Get Shipping Zone",
    )
    shipping_zone_id: str = Field(..., title="Shipping Zone ID", description="The shipping zone to fetch")
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")
    with_shipping_rate: Optional[str] = Field(
        None, title="With Shipping Rate", description="Include shipping rates in the response",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLUpdateShippingZoneConfig(BaseModel):
    """Update a shipping zone."""

    operation: Literal["update_shipping_zone"] = Field(
        "update_shipping_zone",
        json_schema_extra={
            "const": "update_shipping_zone", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Update Shipping Zone",
        },
        title="Update Shipping Zone",
    )
    shipping_zone_id: str = Field(..., title="Shipping Zone ID", description="The shipping zone to update")
    alt_id: Optional[str] = Field(None, title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: Optional[str] = Field(None, title="Alt Type", description="Type of altId (e.g. location)")
    name: Optional[str] = Field(None, title="Name", description="Shipping zone name")
    countries: Optional[str] = Field(None, title="Countries", description="JSON array of country objects covered by the zone")


class GHLDeleteShippingZoneConfig(BaseModel):
    """Delete a shipping zone."""

    operation: Literal["delete_shipping_zone"] = Field(
        "delete_shipping_zone",
        json_schema_extra={
            "const": "delete_shipping_zone", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Delete Shipping Zone",
        },
        title="Delete Shipping Zone",
    )
    shipping_zone_id: str = Field(..., title="Shipping Zone ID", description="The shipping zone to delete")
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")


class GHLGetAvailableShippingRatesConfig(BaseModel):
    """Get available shipping rates for a cart / order."""

    operation: Literal["get_available_shipping_rates"] = Field(
        "get_available_shipping_rates",
        json_schema_extra={
            "const": "get_available_shipping_rates", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Get Available Shipping Rates",
        },
        title="Get Available Shipping Rates",
    )
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")
    country: str = Field(..., title="Country", description="Country code of the customer (e.g. US)")
    total_order_amount: str = Field(..., title="Total Order Amount", description="Total order amount")
    total_order_weight: str = Field(..., title="Total Order Weight", description="Total order weight")
    source: str = Field(..., title="Source", description="JSON object describing the rate source")
    products: str = Field(..., title="Products", description="JSON array of products in the order")
    address: Optional[str] = Field(None, title="Address", description="JSON object with the customer address")
    amount_available: Optional[str] = Field(
        None, title="Amount Available", description="Whether amount-based rates are available",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    weight_available: Optional[str] = Field(
        None, title="Weight Available", description="Whether weight-based rates are available",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    coupon_code: Optional[str] = Field(None, title="Coupon Code", description="Coupon code applied to the order")


class GHLCreateShippingRateConfig(BaseModel):
    """Create a shipping rate within a shipping zone."""

    operation: Literal["create_shipping_rate"] = Field(
        "create_shipping_rate",
        json_schema_extra={
            "const": "create_shipping_rate", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Create Shipping Rate",
        },
        title="Create Shipping Rate",
    )
    shipping_zone_id: str = Field(..., title="Shipping Zone ID", description="Parent shipping zone id")
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")
    name: str = Field(..., title="Name", description="Shipping rate name")
    currency: str = Field(..., title="Currency", description="Currency code")
    amount: str = Field(..., title="Amount", description="Rate amount")
    condition_type: str = Field(..., title="Condition Type", description="Condition type (e.g. by weight/price)")
    min_condition: str = Field(..., title="Min Condition", description="Minimum condition value")
    max_condition: str = Field(..., title="Max Condition", description="Maximum condition value")
    shipping_carrier_id: str = Field(..., title="Shipping Carrier ID", description="Associated shipping carrier id")
    description: Optional[str] = Field(None, title="Description")
    is_carrier_rate: Optional[str] = Field(
        None, title="Is Carrier Rate", description="Whether this is a carrier-provided rate",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    percentage_of_rate_fee: Optional[str] = Field(None, title="Percentage Of Rate Fee", description="Percentage-of-rate fee")
    shipping_carrier_services: Optional[str] = Field(
        None, title="Shipping Carrier Services", description="JSON array of carrier service objects")


class GHLListShippingRatesConfig(BaseModel):
    """List shipping rates within a shipping zone."""

    operation: Literal["list_shipping_rates"] = Field(
        "list_shipping_rates",
        json_schema_extra={
            "const": "list_shipping_rates", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "List Shipping Rates",
        },
        title="List Shipping Rates",
    )
    shipping_zone_id: str = Field(..., title="Shipping Zone ID", description="Parent shipping zone id")
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")
    limit: Optional[str] = Field(None, title="Limit", description="Max results to return")
    offset: Optional[str] = Field(None, title="Offset", description="Number of results to skip (pagination)")


class GHLGetShippingRateConfig(BaseModel):
    """Get a shipping rate by id."""

    operation: Literal["get_shipping_rate"] = Field(
        "get_shipping_rate",
        json_schema_extra={
            "const": "get_shipping_rate", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Get Shipping Rate",
        },
        title="Get Shipping Rate",
    )
    shipping_zone_id: str = Field(..., title="Shipping Zone ID", description="Parent shipping zone id")
    shipping_rate_id: str = Field(..., title="Shipping Rate ID", description="The shipping rate to fetch")
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")


class GHLUpdateShippingRateConfig(BaseModel):
    """Update a shipping rate."""

    operation: Literal["update_shipping_rate"] = Field(
        "update_shipping_rate",
        json_schema_extra={
            "const": "update_shipping_rate", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Update Shipping Rate",
        },
        title="Update Shipping Rate",
    )
    shipping_zone_id: str = Field(..., title="Shipping Zone ID", description="Parent shipping zone id")
    shipping_rate_id: str = Field(..., title="Shipping Rate ID", description="The shipping rate to update")
    alt_id: Optional[str] = Field(None, title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: Optional[str] = Field(None, title="Alt Type", description="Type of altId (e.g. location)")
    name: Optional[str] = Field(None, title="Name", description="Shipping rate name")
    currency: Optional[str] = Field(None, title="Currency", description="Currency code")
    amount: Optional[str] = Field(None, title="Amount", description="Rate amount")
    condition_type: Optional[str] = Field(None, title="Condition Type", description="Condition type (e.g. by weight/price)")
    min_condition: Optional[str] = Field(None, title="Min Condition", description="Minimum condition value")
    max_condition: Optional[str] = Field(None, title="Max Condition", description="Maximum condition value")
    shipping_carrier_id: Optional[str] = Field(None, title="Shipping Carrier ID", description="Associated shipping carrier id")
    description: Optional[str] = Field(None, title="Description")
    is_carrier_rate: Optional[str] = Field(
        None, title="Is Carrier Rate", description="Whether this is a carrier-provided rate",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    percentage_of_rate_fee: Optional[str] = Field(None, title="Percentage Of Rate Fee", description="Percentage-of-rate fee")
    shipping_carrier_services: Optional[str] = Field(
        None, title="Shipping Carrier Services", description="JSON array of carrier service objects")


class GHLDeleteShippingRateConfig(BaseModel):
    """Delete a shipping rate."""

    operation: Literal["delete_shipping_rate"] = Field(
        "delete_shipping_rate",
        json_schema_extra={
            "const": "delete_shipping_rate", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Delete Shipping Rate",
        },
        title="Delete Shipping Rate",
    )
    shipping_zone_id: str = Field(..., title="Shipping Zone ID", description="Parent shipping zone id")
    shipping_rate_id: str = Field(..., title="Shipping Rate ID", description="The shipping rate to delete")
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")


class GHLCreateShippingCarrierConfig(BaseModel):
    """Create a shipping carrier for a location."""

    operation: Literal["create_shipping_carrier"] = Field(
        "create_shipping_carrier",
        json_schema_extra={
            "const": "create_shipping_carrier", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Create Shipping Carrier",
        },
        title="Create Shipping Carrier",
    )
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")
    name: str = Field(..., title="Name", description="Shipping carrier name")
    callback_url: str = Field(..., title="Callback URL", description="Carrier callback URL")
    services: Optional[str] = Field(None, title="Services", description="JSON array of carrier service objects")
    allows_multiple_service_selection: Optional[str] = Field(
        None, title="Allows Multiple Service Selection", description="Allow selecting multiple carrier services",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLListShippingCarriersConfig(BaseModel):
    """List shipping carriers for a location."""

    operation: Literal["list_shipping_carriers"] = Field(
        "list_shipping_carriers",
        json_schema_extra={
            "const": "list_shipping_carriers", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "List Shipping Carriers",
        },
        title="List Shipping Carriers",
    )
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")


class GHLGetShippingCarrierConfig(BaseModel):
    """Get a shipping carrier by id."""

    operation: Literal["get_shipping_carrier"] = Field(
        "get_shipping_carrier",
        json_schema_extra={
            "const": "get_shipping_carrier", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Get Shipping Carrier",
        },
        title="Get Shipping Carrier",
    )
    shipping_carrier_id: str = Field(..., title="Shipping Carrier ID", description="The shipping carrier to fetch")
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")


class GHLUpdateShippingCarrierConfig(BaseModel):
    """Update a shipping carrier."""

    operation: Literal["update_shipping_carrier"] = Field(
        "update_shipping_carrier",
        json_schema_extra={
            "const": "update_shipping_carrier", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Update Shipping Carrier",
        },
        title="Update Shipping Carrier",
    )
    shipping_carrier_id: str = Field(..., title="Shipping Carrier ID", description="The shipping carrier to update")
    alt_id: Optional[str] = Field(None, title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: Optional[str] = Field(None, title="Alt Type", description="Type of altId (e.g. location)")
    name: Optional[str] = Field(None, title="Name", description="Shipping carrier name")
    callback_url: Optional[str] = Field(None, title="Callback URL", description="Carrier callback URL")
    services: Optional[str] = Field(None, title="Services", description="JSON array of carrier service objects")
    allows_multiple_service_selection: Optional[str] = Field(
        None, title="Allows Multiple Service Selection", description="Allow selecting multiple carrier services",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLDeleteShippingCarrierConfig(BaseModel):
    """Delete a shipping carrier."""

    operation: Literal["delete_shipping_carrier"] = Field(
        "delete_shipping_carrier",
        json_schema_extra={
            "const": "delete_shipping_carrier", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Delete Shipping Carrier",
        },
        title="Delete Shipping Carrier",
    )
    shipping_carrier_id: str = Field(..., title="Shipping Carrier ID", description="The shipping carrier to delete")
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")


class GHLCreateStoreSettingConfig(BaseModel):
    """Create or update store settings for a location."""

    operation: Literal["create_store_setting"] = Field(
        "create_store_setting",
        json_schema_extra={
            "const": "create_store_setting", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Create/Update Store Settings",
        },
        title="Create/Update Store Settings",
    )
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")
    shipping_origin: str = Field(..., title="Shipping Origin", description="JSON object with the shipping origin address")
    store_order_notification: Optional[str] = Field(
        None, title="Store Order Notification", description="JSON object with the store order notification email settings")
    store_order_fulfillment_notification: Optional[str] = Field(
        None, title="Store Order Fulfillment Notification",
        description="JSON object with the store order fulfillment notification email settings")


class GHLGetStoreSettingsConfig(BaseModel):
    """Get store settings for a location."""

    operation: Literal["get_store_settings"] = Field(
        "get_store_settings",
        json_schema_extra={
            "const": "get_store_settings", "ui:hidden": True,
            "x-category": "Store", "x-is-trigger": False,
            "x-display-name": "Get Store Settings",
        },
        title="Get Store Settings",
    )
    alt_id: str = Field(..., title="Location ID", description="Location Id or Agency Id (altId)")
    alt_type: str = Field("location", title="Alt Type", description="Type of altId (e.g. location)")


async def _create_shipping_zone(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "countries": _ghl_json(c.countries),
    }
    return await node._request(token, "POST", "/store/shipping-zone", json_body=body, action_name="create_shipping_zone")


async def _list_shipping_zones(node, c, token):
    params = {
        "altId": c.alt_id, "altType": c.alt_type, "limit": _ghl_num(c.limit),
        "offset": _ghl_num(c.offset), "withShippingRate": _ghl_bool(c.with_shipping_rate),
    }
    return await node._request(token, "GET", "/store/shipping-zone", params=params, action_name="list_shipping_zones")


async def _get_shipping_zone(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type, "withShippingRate": _ghl_bool(c.with_shipping_rate)}
    return await node._request(token, "GET", f"/store/shipping-zone/{c.shipping_zone_id}", params=params, action_name="get_shipping_zone")


async def _update_shipping_zone(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name,
        "countries": _ghl_json(c.countries),
    }
    return await node._request(token, "PUT", f"/store/shipping-zone/{c.shipping_zone_id}", json_body=body, action_name="update_shipping_zone")


async def _delete_shipping_zone(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "DELETE", f"/store/shipping-zone/{c.shipping_zone_id}", params=params, action_name="delete_shipping_zone")


async def _get_available_shipping_rates(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "country": c.country,
        "address": _ghl_json(c.address), "amountAvailable": _ghl_bool(c.amount_available),
        "totalOrderAmount": _ghl_num(c.total_order_amount), "weightAvailable": _ghl_bool(c.weight_available),
        "totalOrderWeight": _ghl_num(c.total_order_weight), "source": _ghl_json(c.source),
        "products": _ghl_json(c.products), "couponCode": c.coupon_code,
    }
    return await node._request(token, "POST", "/store/shipping-zone/shipping-rates", json_body=body, action_name="get_available_shipping_rates")


async def _create_shipping_rate(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name, "description": c.description,
        "currency": c.currency, "amount": _ghl_num(c.amount), "conditionType": c.condition_type,
        "minCondition": _ghl_num(c.min_condition), "maxCondition": _ghl_num(c.max_condition),
        "isCarrierRate": _ghl_bool(c.is_carrier_rate), "shippingCarrierId": c.shipping_carrier_id,
        "percentageOfRateFee": _ghl_num(c.percentage_of_rate_fee),
        "shippingCarrierServices": _ghl_json(c.shipping_carrier_services),
    }
    return await node._request(token, "POST", f"/store/shipping-zone/{c.shipping_zone_id}/shipping-rate", json_body=body, action_name="create_shipping_rate")


async def _list_shipping_rates(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type, "limit": _ghl_num(c.limit), "offset": _ghl_num(c.offset)}
    return await node._request(token, "GET", f"/store/shipping-zone/{c.shipping_zone_id}/shipping-rate", params=params, action_name="list_shipping_rates")


async def _get_shipping_rate(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", f"/store/shipping-zone/{c.shipping_zone_id}/shipping-rate/{c.shipping_rate_id}", params=params, action_name="get_shipping_rate")


async def _update_shipping_rate(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name, "description": c.description,
        "currency": c.currency, "amount": _ghl_num(c.amount), "conditionType": c.condition_type,
        "minCondition": _ghl_num(c.min_condition), "maxCondition": _ghl_num(c.max_condition),
        "isCarrierRate": _ghl_bool(c.is_carrier_rate), "shippingCarrierId": c.shipping_carrier_id,
        "percentageOfRateFee": _ghl_num(c.percentage_of_rate_fee),
        "shippingCarrierServices": _ghl_json(c.shipping_carrier_services),
    }
    return await node._request(token, "PUT", f"/store/shipping-zone/{c.shipping_zone_id}/shipping-rate/{c.shipping_rate_id}", json_body=body, action_name="update_shipping_rate")


async def _delete_shipping_rate(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "DELETE", f"/store/shipping-zone/{c.shipping_zone_id}/shipping-rate/{c.shipping_rate_id}", params=params, action_name="delete_shipping_rate")


async def _create_shipping_carrier(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name, "callbackUrl": c.callback_url,
        "services": _ghl_json(c.services),
        "allowsMultipleServiceSelection": _ghl_bool(c.allows_multiple_service_selection),
    }
    return await node._request(token, "POST", "/store/shipping-carrier", json_body=body, action_name="create_shipping_carrier")


async def _list_shipping_carriers(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", "/store/shipping-carrier", params=params, action_name="list_shipping_carriers")


async def _get_shipping_carrier(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", f"/store/shipping-carrier/{c.shipping_carrier_id}", params=params, action_name="get_shipping_carrier")


async def _update_shipping_carrier(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "name": c.name, "callbackUrl": c.callback_url,
        "services": _ghl_json(c.services),
        "allowsMultipleServiceSelection": _ghl_bool(c.allows_multiple_service_selection),
    }
    return await node._request(token, "PUT", f"/store/shipping-carrier/{c.shipping_carrier_id}", json_body=body, action_name="update_shipping_carrier")


async def _delete_shipping_carrier(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "DELETE", f"/store/shipping-carrier/{c.shipping_carrier_id}", params=params, action_name="delete_shipping_carrier")


async def _create_store_setting(node, c, token):
    body = {
        "altId": c.alt_id, "altType": c.alt_type, "shippingOrigin": _ghl_json(c.shipping_origin),
        "storeOrderNotification": _ghl_json(c.store_order_notification),
        "storeOrderFulfillmentNotification": _ghl_json(c.store_order_fulfillment_notification),
    }
    return await node._request(token, "POST", "/store/store-setting", json_body=body, action_name="create_store_setting")


async def _get_store_settings(node, c, token):
    params = {"altId": c.alt_id, "altType": c.alt_type}
    return await node._request(token, "GET", "/store/store-setting", params=params, action_name="get_store_settings")


GHL_OPERATION_CONFIGS += [
    GHLCreateShippingZoneConfig,
    GHLListShippingZonesConfig,
    GHLGetShippingZoneConfig,
    GHLUpdateShippingZoneConfig,
    GHLDeleteShippingZoneConfig,
    GHLGetAvailableShippingRatesConfig,
    GHLCreateShippingRateConfig,
    GHLListShippingRatesConfig,
    GHLGetShippingRateConfig,
    GHLUpdateShippingRateConfig,
    GHLDeleteShippingRateConfig,
    GHLCreateShippingCarrierConfig,
    GHLListShippingCarriersConfig,
    GHLGetShippingCarrierConfig,
    GHLUpdateShippingCarrierConfig,
    GHLDeleteShippingCarrierConfig,
    GHLCreateStoreSettingConfig,
    GHLGetStoreSettingsConfig,
]
GHL_OPERATION_HANDLERS.update({
    "create_shipping_zone": _create_shipping_zone,
    "list_shipping_zones": _list_shipping_zones,
    "get_shipping_zone": _get_shipping_zone,
    "update_shipping_zone": _update_shipping_zone,
    "delete_shipping_zone": _delete_shipping_zone,
    "get_available_shipping_rates": _get_available_shipping_rates,
    "create_shipping_rate": _create_shipping_rate,
    "list_shipping_rates": _list_shipping_rates,
    "get_shipping_rate": _get_shipping_rate,
    "update_shipping_rate": _update_shipping_rate,
    "delete_shipping_rate": _delete_shipping_rate,
    "create_shipping_carrier": _create_shipping_carrier,
    "list_shipping_carriers": _list_shipping_carriers,
    "get_shipping_carrier": _get_shipping_carrier,
    "update_shipping_carrier": _update_shipping_carrier,
    "delete_shipping_carrier": _delete_shipping_carrier,
    "create_store_setting": _create_store_setting,
    "get_store_settings": _get_store_settings,
})


# ---- surveys.py ----
class GHLGetSurveysSubmissionsConfig(BaseModel):
    """Get survey submissions for a location."""

    operation: Literal["get_surveys_submissions"] = Field(
        "get_surveys_submissions",
        json_schema_extra={
            "const": "get_surveys_submissions", "ui:hidden": True,
            "x-category": "Surveys", "x-is-trigger": False,
            "x-display-name": "Get Survey Submissions",
        },
        title="Get Survey Submissions",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    page: Optional[str] = Field(None, title="Page", description="Page number (default 1)")
    limit: Optional[str] = Field(None, title="Limit", description="Records per page (max 100, default 20)")
    survey_id: Optional[str] = Field(None, title="Survey ID", description="Filter submissions by survey id")
    q: Optional[str] = Field(None, title="Query", description="Filter by contactId, name, email or phone")
    start_at: Optional[str] = Field(None, title="Start Date", description="Filter from this date (YYYY-MM-DD)")
    end_at: Optional[str] = Field(None, title="End Date", description="Filter to this date (YYYY-MM-DD)")


class GHLGetSurveysConfig(BaseModel):
    """List surveys for a location."""

    operation: Literal["get_surveys"] = Field(
        "get_surveys",
        json_schema_extra={
            "const": "get_surveys", "ui:hidden": True,
            "x-category": "Surveys", "x-is-trigger": False,
            "x-display-name": "Get Surveys",
        },
        title="Get Surveys",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip (pagination)")
    limit: Optional[str] = Field(None, title="Limit", description="Records per page (max 50, default 10)")
    type: Optional[str] = Field(None, title="Type", description="Filter by type (e.g. folder)")


async def _get_surveys_submissions(node, c, token):
    params = {
        "locationId": c.location_id, "page": _ghl_int(c.page), "limit": _ghl_int(c.limit),
        "surveyId": c.survey_id, "q": c.q, "startAt": c.start_at, "endAt": c.end_at,
    }
    return await node._request(token, "GET", "/surveys/submissions", params=params, action_name="get_surveys_submissions")


async def _get_surveys(node, c, token):
    params = {
        "locationId": c.location_id, "skip": _ghl_int(c.skip),
        "limit": _ghl_int(c.limit), "type": c.type,
    }
    return await node._request(token, "GET", "/surveys/", params=params, action_name="get_surveys")


GHL_OPERATION_CONFIGS += [
    GHLGetSurveysSubmissionsConfig,
    GHLGetSurveysConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_surveys_submissions": _get_surveys_submissions,
    "get_surveys": _get_surveys,
})


# ---- users.py ----
class GHLSearchUsersConfig(BaseModel):
    """Search users within a company."""

    operation: Literal["search_users"] = Field(
        "search_users",
        json_schema_extra={
            "const": "search_users", "ui:hidden": True,
            "x-category": "Users", "x-is-trigger": False,
            "x-display-name": "Search Users",
        },
        title="Search Users",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID in which the search needs to be performed")
    query: Optional[str] = Field(None, title="Query", description="Search term matched against user fields")
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip before returning")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of results to return")
    location_id: Optional[str] = Field(None, title="Location ID", description="Location ID to scope the search")
    type: Optional[str] = Field(None, title="Type", description="Type of users to filter by")
    role: Optional[str] = Field(None, title="Role", description="Role of users to filter by")
    ids: Optional[str] = Field(None, title="IDs", description="List of user IDs to filter by")
    sort: Optional[str] = Field(None, title="Sort", description="Field to sort by")
    sort_direction: Optional[str] = Field(None, title="Sort Direction", description="Sort direction")
    enabled2way_sync: Optional[str] = Field(
        None, title="Enabled 2-Way Sync",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class GHLFilterUsersByEmailConfig(BaseModel):
    """Filter users by a list of emails."""

    operation: Literal["filter_users_by_email"] = Field(
        "filter_users_by_email",
        json_schema_extra={
            "const": "filter_users_by_email", "ui:hidden": True,
            "x-category": "Users", "x-is-trigger": False,
            "x-display-name": "Filter Users by Email",
        },
        title="Filter Users by Email",
    )
    company_id: str = Field(..., title="Company ID", description="Company ID to scope the filter")
    emails: str = Field(..., title="Emails", description="Comma-separated list of emails to filter by")
    deleted: Optional[str] = Field(
        None, title="Deleted",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    skip: Optional[str] = Field(None, title="Skip", description="Number of results to skip before returning")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of results to return")
    projection: Optional[str] = Field(None, title="Projection", description="Fields projection")


class GHLGetUserConfig(BaseModel):
    """Get a user by id."""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user", "ui:hidden": True,
            "x-category": "Users", "x-is-trigger": False,
            "x-display-name": "Get User",
        },
        title="Get User",
    )
    user_id: str = Field(..., title="User ID", description="The user to fetch")


class GHLUpdateUserConfig(BaseModel):
    """Update a user."""

    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={
            "const": "update_user", "ui:hidden": True,
            "x-category": "Users", "x-is-trigger": False,
            "x-display-name": "Update User",
        },
        title="Update User",
    )
    user_id: str = Field(..., title="User ID", description="The user to update")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    email: Optional[str] = Field(None, title="Email")
    password: Optional[str] = Field(None, title="Password")
    phone: Optional[str] = Field(None, title="Phone")
    type: Optional[str] = Field(None, title="Type", description="Account type (e.g. account, agency)")
    role: Optional[str] = Field(None, title="Role", description="User role (e.g. admin, user)")
    company_id: Optional[str] = Field(None, title="Company ID")
    location_ids: Optional[str] = Field(None, title="Location IDs", description="Comma-separated list of location IDs")
    permissions: Optional[str] = Field(None, title="Permissions", description="Permissions object as JSON")
    scopes: Optional[str] = Field(None, title="Scopes", description="Comma-separated list of scopes")
    scopes_assigned_to_only: Optional[str] = Field(
        None, title="Scopes Assigned To Only", description="Comma-separated list of assigned-only scopes")
    profile_photo: Optional[str] = Field(None, title="Profile Photo")
    twilio_phone: Optional[str] = Field(None, title="Twilio Phone", description="Twilio phone object as JSON")
    platform_language: Optional[str] = Field(
        None, title="Platform Language",
        json_schema_extra={
            "enum": ["en_US", "es", "fr_CA", "fr_FR", "nl", "de", "pt_PT", "pt_BR", "it", "sv", "da", "fi", "no"],
            "x-enum-searchable": True,
        },
    )


class GHLDeleteUserConfig(BaseModel):
    """Delete a user."""

    operation: Literal["delete_user"] = Field(
        "delete_user",
        json_schema_extra={
            "const": "delete_user", "ui:hidden": True,
            "x-category": "Users", "x-is-trigger": False,
            "x-display-name": "Delete User",
        },
        title="Delete User",
    )
    user_id: str = Field(..., title="User ID", description="The user to delete")


class GHLGetUserByLocationConfig(BaseModel):
    """List users for a location (sub-account)."""

    operation: Literal["get_user_by_location"] = Field(
        "get_user_by_location",
        json_schema_extra={
            "const": "get_user_by_location", "ui:hidden": True,
            "x-category": "Users", "x-is-trigger": False,
            "x-display-name": "List Users by Location",
        },
        title="List Users by Location",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateUserConfig(BaseModel):
    """Create a user."""

    operation: Literal["create_user"] = Field(
        "create_user",
        json_schema_extra={
            "const": "create_user", "ui:hidden": True,
            "x-category": "Users", "x-is-trigger": False,
            "x-display-name": "Create User",
        },
        title="Create User",
    )
    company_id: str = Field(..., title="Company ID")
    first_name: str = Field(..., title="First Name")
    last_name: str = Field(..., title="Last Name")
    email: str = Field(..., title="Email")
    password: str = Field(..., title="Password")
    type: str = Field(..., title="Type", description="Account type (e.g. account, agency)")
    role: str = Field(..., title="Role", description="User role (e.g. admin, user)")
    location_ids: str = Field(..., title="Location IDs", description="Comma-separated list of location IDs")
    phone: Optional[str] = Field(None, title="Phone")
    permissions: Optional[str] = Field(None, title="Permissions", description="Permissions object as JSON")
    scopes: Optional[str] = Field(None, title="Scopes", description="Comma-separated list of scopes")
    scopes_assigned_to_only: Optional[str] = Field(
        None, title="Scopes Assigned To Only", description="Comma-separated list of assigned-only scopes")
    profile_photo: Optional[str] = Field(None, title="Profile Photo")
    twilio_phone: Optional[str] = Field(None, title="Twilio Phone", description="Twilio phone object as JSON")
    platform_language: Optional[str] = Field(
        None, title="Platform Language",
        json_schema_extra={
            "enum": ["en_US", "es", "fr_CA", "fr_FR", "nl", "de", "pt_PT", "pt_BR", "it", "sv", "da", "fi", "no"],
            "x-enum-searchable": True,
        },
    )


async def _search_users(node, c, token):
    params = {
        "companyId": c.company_id, "query": c.query, "skip": c.skip, "limit": c.limit,
        "locationId": c.location_id, "type": c.type, "role": c.role, "ids": c.ids,
        "sort": c.sort, "sortDirection": c.sort_direction, "enabled2waySync": _ghl_bool(c.enabled2way_sync),
    }
    return await node._request(token, "GET", "/users/search", params=params, action_name="search_users")


async def _filter_users_by_email(node, c, token):
    body = {
        "companyId": c.company_id, "emails": c.emails, "deleted": _ghl_bool(c.deleted),
        "skip": c.skip, "limit": c.limit, "projection": c.projection,
    }
    return await node._request(token, "POST", "/users/search/filter-by-email", json_body=body, action_name="filter_users_by_email")


async def _get_user(node, c, token):
    return await node._request(token, "GET", f"/users/{c.user_id}", action_name="get_user")


async def _update_user(node, c, token):
    body = {
        "firstName": c.first_name, "lastName": c.last_name, "email": c.email, "password": c.password,
        "phone": c.phone, "type": c.type, "role": c.role, "companyId": c.company_id,
        "locationIds": _ghl_csv(c.location_ids), "permissions": _ghl_json(c.permissions),
        "scopes": _ghl_csv(c.scopes), "scopesAssignedToOnly": _ghl_csv(c.scopes_assigned_to_only),
        "profilePhoto": c.profile_photo, "twilioPhone": _ghl_json(c.twilio_phone),
        "platformLanguage": c.platform_language,
    }
    return await node._request(token, "PUT", f"/users/{c.user_id}", json_body=body, action_name="update_user")


async def _delete_user(node, c, token):
    return await node._request(token, "DELETE", f"/users/{c.user_id}", action_name="delete_user")


async def _get_user_by_location(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", "/users/", params=params, action_name="get_user_by_location")


async def _create_user(node, c, token):
    body = {
        "companyId": c.company_id, "firstName": c.first_name, "lastName": c.last_name,
        "email": c.email, "password": c.password, "phone": c.phone, "type": c.type, "role": c.role,
        "locationIds": _ghl_csv(c.location_ids), "permissions": _ghl_json(c.permissions),
        "scopes": _ghl_csv(c.scopes), "scopesAssignedToOnly": _ghl_csv(c.scopes_assigned_to_only),
        "profilePhoto": c.profile_photo, "twilioPhone": _ghl_json(c.twilio_phone),
        "platformLanguage": c.platform_language,
    }
    return await node._request(token, "POST", "/users/", json_body=body, action_name="create_user")


GHL_OPERATION_CONFIGS += [
    GHLSearchUsersConfig,
    GHLFilterUsersByEmailConfig,
    GHLGetUserConfig,
    GHLUpdateUserConfig,
    GHLDeleteUserConfig,
    GHLGetUserByLocationConfig,
    GHLCreateUserConfig,
]
GHL_OPERATION_HANDLERS.update({
    "search_users": _search_users,
    "filter_users_by_email": _filter_users_by_email,
    "get_user": _get_user,
    "update_user": _update_user,
    "delete_user": _delete_user,
    "get_user_by_location": _get_user_by_location,
    "create_user": _create_user,
})


# ---- voice_ai.py ----
_VOICE_AI_VERSION = "2021-04-15"


class GHLCreateVoiceAiAgentConfig(BaseModel):
    """Create a Voice AI agent."""

    operation: Literal["create_voice_ai_agent"] = Field(
        "create_voice_ai_agent",
        json_schema_extra={
            "const": "create_voice_ai_agent", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "Create Voice AI Agent",
        },
        title="Create Voice AI Agent",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    agent_name: Optional[str] = Field(None, title="Agent Name")
    business_name: Optional[str] = Field(None, title="Business Name")
    welcome_message: Optional[str] = Field(None, title="Welcome Message")
    agent_prompt: Optional[str] = Field(None, title="Agent Prompt")
    voice_id: Optional[str] = Field(None, title="Voice ID")
    language: Optional[str] = Field(
        None, title="Language",
        json_schema_extra={"enum": ["en-US", "pt-BR", "es", "fr", "de", "it", "nl-NL", "multi"], "x-enum-searchable": True},
    )
    patience_level: Optional[str] = Field(
        None, title="Patience Level",
        json_schema_extra={"enum": ["low", "medium", "high"], "x-enum-searchable": True},
    )
    max_call_duration: Optional[str] = Field(None, title="Max Call Duration", description="Seconds")
    send_user_idle_reminders: Optional[str] = Field(
        None, title="Send User Idle Reminders",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    reminder_after_idle_time_seconds: Optional[str] = Field(None, title="Reminder After Idle Time (Seconds)")
    inbound_number: Optional[str] = Field(None, title="Inbound Number")
    number_pool_id: Optional[str] = Field(None, title="Number Pool ID")
    call_end_workflow_ids: Optional[str] = Field(None, title="Call End Workflow IDs", description="Comma-separated workflow ids")
    send_post_call_notification_to: Optional[str] = Field(None, title="Send Post-Call Notification To", description="JSON object of notification recipients")
    agent_working_hours: Optional[str] = Field(None, title="Agent Working Hours", description="JSON array of working-hours configs")
    timezone: Optional[str] = Field(None, title="Timezone")
    is_agent_as_backup_disabled: Optional[str] = Field(
        None, title="Is Agent As Backup Disabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    translation: Optional[str] = Field(None, title="Translation", description="JSON object with enabled + language")


class GHLGetVoiceAiAgentsConfig(BaseModel):
    """List Voice AI agents for a location."""

    operation: Literal["get_voice_ai_agents"] = Field(
        "get_voice_ai_agents",
        json_schema_extra={
            "const": "get_voice_ai_agents", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "List Voice AI Agents",
        },
        title="List Voice AI Agents",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    page: Optional[str] = Field(None, title="Page")
    page_size: Optional[str] = Field(None, title="Page Size")
    query: Optional[str] = Field(None, title="Query", description="Search query")


class GHLPatchVoiceAiAgentConfig(BaseModel):
    """Patch (update) a Voice AI agent."""

    operation: Literal["patch_voice_ai_agent"] = Field(
        "patch_voice_ai_agent",
        json_schema_extra={
            "const": "patch_voice_ai_agent", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "Patch Voice AI Agent",
        },
        title="Patch Voice AI Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to update")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    agent_name: Optional[str] = Field(None, title="Agent Name")
    business_name: Optional[str] = Field(None, title="Business Name")
    welcome_message: Optional[str] = Field(None, title="Welcome Message")
    agent_prompt: Optional[str] = Field(None, title="Agent Prompt")
    voice_id: Optional[str] = Field(None, title="Voice ID")
    language: Optional[str] = Field(
        None, title="Language",
        json_schema_extra={"enum": ["en-US", "pt-BR", "es", "fr", "de", "it", "nl-NL", "multi"], "x-enum-searchable": True},
    )
    patience_level: Optional[str] = Field(
        None, title="Patience Level",
        json_schema_extra={"enum": ["low", "medium", "high"], "x-enum-searchable": True},
    )
    max_call_duration: Optional[str] = Field(None, title="Max Call Duration", description="Seconds")
    send_user_idle_reminders: Optional[str] = Field(
        None, title="Send User Idle Reminders",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    reminder_after_idle_time_seconds: Optional[str] = Field(None, title="Reminder After Idle Time (Seconds)")
    inbound_number: Optional[str] = Field(None, title="Inbound Number")
    number_pool_id: Optional[str] = Field(None, title="Number Pool ID")
    call_end_workflow_ids: Optional[str] = Field(None, title="Call End Workflow IDs", description="Comma-separated workflow ids")
    send_post_call_notification_to: Optional[str] = Field(None, title="Send Post-Call Notification To", description="JSON object of notification recipients")
    agent_working_hours: Optional[str] = Field(None, title="Agent Working Hours", description="JSON array of working-hours configs")
    timezone: Optional[str] = Field(None, title="Timezone")
    is_agent_as_backup_disabled: Optional[str] = Field(
        None, title="Is Agent As Backup Disabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    translation: Optional[str] = Field(None, title="Translation", description="JSON object with enabled + language")


class GHLGetVoiceAiAgentConfig(BaseModel):
    """Get a Voice AI agent by id."""

    operation: Literal["get_voice_ai_agent"] = Field(
        "get_voice_ai_agent",
        json_schema_extra={
            "const": "get_voice_ai_agent", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "Get Voice AI Agent",
        },
        title="Get Voice AI Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to fetch")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLDeleteVoiceAiAgentConfig(BaseModel):
    """Delete a Voice AI agent."""

    operation: Literal["delete_voice_ai_agent"] = Field(
        "delete_voice_ai_agent",
        json_schema_extra={
            "const": "delete_voice_ai_agent", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "Delete Voice AI Agent",
        },
        title="Delete Voice AI Agent",
    )
    agent_id: str = Field(..., title="Agent ID", description="The agent to delete")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLGetVoiceAiCallLogsConfig(BaseModel):
    """List Voice AI call logs."""

    operation: Literal["get_voice_ai_call_logs"] = Field(
        "get_voice_ai_call_logs",
        json_schema_extra={
            "const": "get_voice_ai_call_logs", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "List Voice AI Call Logs",
        },
        title="List Voice AI Call Logs",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    agent_id: Optional[str] = Field(None, title="Agent ID")
    contact_id: Optional[str] = Field(None, title="Contact ID")
    call_type: Optional[str] = Field(
        None, title="Call Type",
        json_schema_extra={"enum": ["LIVE", "TRIAL"], "x-enum-searchable": True},
    )
    start_date: Optional[str] = Field(None, title="Start Date")
    end_date: Optional[str] = Field(None, title="End Date")
    action_type: Optional[str] = Field(
        None, title="Action Type",
        json_schema_extra={
            "enum": ["CALL_TRANSFER", "DATA_EXTRACTION", "IN_CALL_DATA_EXTRACTION", "WORKFLOW_TRIGGER", "SMS", "APPOINTMENT_BOOKING", "CUSTOM_ACTION", "KNOWLEDGE_BASE"],
            "x-enum-searchable": True,
        },
    )
    sort_by: Optional[str] = Field(
        None, title="Sort By",
        json_schema_extra={"enum": ["duration", "createdAt"], "x-enum-searchable": True},
    )
    sort: Optional[str] = Field(
        None, title="Sort",
        json_schema_extra={"enum": ["ascend", "descend"], "x-enum-searchable": True},
    )
    page: Optional[str] = Field(None, title="Page")
    page_size: Optional[str] = Field(None, title="Page Size")


class GHLGetVoiceAiCallLogConfig(BaseModel):
    """Get a Voice AI call log by id."""

    operation: Literal["get_voice_ai_call_log"] = Field(
        "get_voice_ai_call_log",
        json_schema_extra={
            "const": "get_voice_ai_call_log", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "Get Voice AI Call Log",
        },
        title="Get Voice AI Call Log",
    )
    call_id: str = Field(..., title="Call ID", description="The call log to fetch")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLCreateVoiceAiActionConfig(BaseModel):
    """Create a Voice AI agent action."""

    operation: Literal["create_voice_ai_action"] = Field(
        "create_voice_ai_action",
        json_schema_extra={
            "const": "create_voice_ai_action", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "Create Voice AI Action",
        },
        title="Create Voice AI Action",
    )
    agent_id: str = Field(..., title="Agent ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    action_type: str = Field(
        ..., title="Action Type",
        json_schema_extra={
            "enum": ["CALL_TRANSFER", "DATA_EXTRACTION", "IN_CALL_DATA_EXTRACTION", "WORKFLOW_TRIGGER", "SMS", "APPOINTMENT_BOOKING", "CUSTOM_ACTION", "KNOWLEDGE_BASE"],
            "x-enum-searchable": True,
        },
    )
    name: str = Field(..., title="Name")
    action_parameters: str = Field(..., title="Action Parameters", description="JSON object of action-type-specific parameters")


class GHLUpdateVoiceAiActionConfig(BaseModel):
    """Update a Voice AI agent action."""

    operation: Literal["update_voice_ai_action"] = Field(
        "update_voice_ai_action",
        json_schema_extra={
            "const": "update_voice_ai_action", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "Update Voice AI Action",
        },
        title="Update Voice AI Action",
    )
    action_id: str = Field(..., title="Action ID", description="The action to update")
    agent_id: str = Field(..., title="Agent ID")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    action_type: str = Field(
        ..., title="Action Type",
        json_schema_extra={
            "enum": ["CALL_TRANSFER", "DATA_EXTRACTION", "IN_CALL_DATA_EXTRACTION", "WORKFLOW_TRIGGER", "SMS", "APPOINTMENT_BOOKING", "CUSTOM_ACTION", "KNOWLEDGE_BASE"],
            "x-enum-searchable": True,
        },
    )
    name: str = Field(..., title="Name")
    action_parameters: str = Field(..., title="Action Parameters", description="JSON object of action-type-specific parameters")


class GHLGetVoiceAiActionConfig(BaseModel):
    """Get a Voice AI agent action by id."""

    operation: Literal["get_voice_ai_action"] = Field(
        "get_voice_ai_action",
        json_schema_extra={
            "const": "get_voice_ai_action", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "Get Voice AI Action",
        },
        title="Get Voice AI Action",
    )
    action_id: str = Field(..., title="Action ID", description="The action to fetch")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


class GHLDeleteVoiceAiActionConfig(BaseModel):
    """Delete a Voice AI agent action."""

    operation: Literal["delete_voice_ai_action"] = Field(
        "delete_voice_ai_action",
        json_schema_extra={
            "const": "delete_voice_ai_action", "ui:hidden": True,
            "x-category": "Voice AI", "x-is-trigger": False,
            "x-display-name": "Delete Voice AI Action",
        },
        title="Delete Voice AI Action",
    )
    action_id: str = Field(..., title="Action ID", description="The action to delete")
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")
    agent_id: str = Field(..., title="Agent ID")


def _voice_ai_agent_body(c):
    return {
        "agentName": c.agent_name,
        "businessName": c.business_name,
        "welcomeMessage": c.welcome_message,
        "agentPrompt": c.agent_prompt,
        "voiceId": c.voice_id,
        "language": c.language,
        "patienceLevel": c.patience_level,
        "maxCallDuration": _ghl_num(c.max_call_duration),
        "sendUserIdleReminders": _ghl_bool(c.send_user_idle_reminders),
        "reminderAfterIdleTimeSeconds": _ghl_num(c.reminder_after_idle_time_seconds),
        "inboundNumber": c.inbound_number,
        "numberPoolId": c.number_pool_id,
        "callEndWorkflowIds": _ghl_csv(c.call_end_workflow_ids),
        "sendPostCallNotificationTo": _ghl_json(c.send_post_call_notification_to),
        "agentWorkingHours": _ghl_json(c.agent_working_hours),
        "timezone": c.timezone,
        "isAgentAsBackupDisabled": _ghl_bool(c.is_agent_as_backup_disabled),
        "translation": _ghl_json(c.translation),
    }


async def _create_voice_ai_agent(node, c, token):
    body = {"locationId": c.location_id, **_voice_ai_agent_body(c)}
    return await node._request(token, "POST", "/voice-ai/agents", json_body=body, version=_VOICE_AI_VERSION, action_name="create_voice_ai_agent")


async def _get_voice_ai_agents(node, c, token):
    params = {"locationId": c.location_id, "page": _ghl_int(c.page), "pageSize": _ghl_int(c.page_size), "query": c.query}
    return await node._request(token, "GET", "/voice-ai/agents", params=params, version=_VOICE_AI_VERSION, action_name="get_voice_ai_agents")


async def _patch_voice_ai_agent(node, c, token):
    params = {"locationId": c.location_id}
    body = _voice_ai_agent_body(c)
    return await node._request(token, "PATCH", f"/voice-ai/agents/{c.agent_id}", params=params, json_body=body, version=_VOICE_AI_VERSION, action_name="patch_voice_ai_agent")


async def _get_voice_ai_agent(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", f"/voice-ai/agents/{c.agent_id}", params=params, version=_VOICE_AI_VERSION, action_name="get_voice_ai_agent")


async def _delete_voice_ai_agent(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "DELETE", f"/voice-ai/agents/{c.agent_id}", params=params, version=_VOICE_AI_VERSION, action_name="delete_voice_ai_agent")


async def _get_voice_ai_call_logs(node, c, token):
    params = {
        "locationId": c.location_id, "agentId": c.agent_id, "contactId": c.contact_id,
        "callType": c.call_type, "startDate": c.start_date, "endDate": c.end_date,
        "actionType": c.action_type, "sortBy": c.sort_by, "sort": c.sort,
        "page": _ghl_int(c.page), "pageSize": _ghl_int(c.page_size),
    }
    return await node._request(token, "GET", "/voice-ai/dashboard/call-logs", params=params, version=_VOICE_AI_VERSION, action_name="get_voice_ai_call_logs")


async def _get_voice_ai_call_log(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", f"/voice-ai/dashboard/call-logs/{c.call_id}", params=params, version=_VOICE_AI_VERSION, action_name="get_voice_ai_call_log")


async def _create_voice_ai_action(node, c, token):
    body = {
        "agentId": c.agent_id, "locationId": c.location_id, "actionType": c.action_type,
        "name": c.name, "actionParameters": _ghl_json(c.action_parameters),
    }
    return await node._request(token, "POST", "/voice-ai/actions", json_body=body, version=_VOICE_AI_VERSION, action_name="create_voice_ai_action")


async def _update_voice_ai_action(node, c, token):
    body = {
        "agentId": c.agent_id, "locationId": c.location_id, "actionType": c.action_type,
        "name": c.name, "actionParameters": _ghl_json(c.action_parameters),
    }
    return await node._request(token, "PUT", f"/voice-ai/actions/{c.action_id}", json_body=body, version=_VOICE_AI_VERSION, action_name="update_voice_ai_action")


async def _get_voice_ai_action(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", f"/voice-ai/actions/{c.action_id}", params=params, version=_VOICE_AI_VERSION, action_name="get_voice_ai_action")


async def _delete_voice_ai_action(node, c, token):
    params = {"locationId": c.location_id, "agentId": c.agent_id}
    return await node._request(token, "DELETE", f"/voice-ai/actions/{c.action_id}", params=params, version=_VOICE_AI_VERSION, action_name="delete_voice_ai_action")


GHL_OPERATION_CONFIGS += [
    GHLCreateVoiceAiAgentConfig,
    GHLGetVoiceAiAgentsConfig,
    GHLPatchVoiceAiAgentConfig,
    GHLGetVoiceAiAgentConfig,
    GHLDeleteVoiceAiAgentConfig,
    GHLGetVoiceAiCallLogsConfig,
    GHLGetVoiceAiCallLogConfig,
    GHLCreateVoiceAiActionConfig,
    GHLUpdateVoiceAiActionConfig,
    GHLGetVoiceAiActionConfig,
    GHLDeleteVoiceAiActionConfig,
]
GHL_OPERATION_HANDLERS.update({
    "create_voice_ai_agent": _create_voice_ai_agent,
    "get_voice_ai_agents": _get_voice_ai_agents,
    "patch_voice_ai_agent": _patch_voice_ai_agent,
    "get_voice_ai_agent": _get_voice_ai_agent,
    "delete_voice_ai_agent": _delete_voice_ai_agent,
    "get_voice_ai_call_logs": _get_voice_ai_call_logs,
    "get_voice_ai_call_log": _get_voice_ai_call_log,
    "create_voice_ai_action": _create_voice_ai_action,
    "update_voice_ai_action": _update_voice_ai_action,
    "get_voice_ai_action": _get_voice_ai_action,
    "delete_voice_ai_action": _delete_voice_ai_action,
})


# ---- workflows.py ----
class GHLGetWorkflowConfig(BaseModel):
    """List workflows for a location (sub-account)."""

    operation: Literal["get_workflow"] = Field(
        "get_workflow",
        json_schema_extra={
            "const": "get_workflow", "ui:hidden": True,
            "x-category": "Workflows", "x-is-trigger": False,
            "x-display-name": "List Workflows",
        },
        title="List Workflows",
    )
    location_id: str = Field(..., title="Location ID", description="Sub-account (location) id")


async def _get_workflow(node, c, token):
    params = {"locationId": c.location_id}
    return await node._request(token, "GET", "/workflows/", params=params, action_name="get_workflow")


GHL_OPERATION_CONFIGS += [
    GHLGetWorkflowConfig,
]
GHL_OPERATION_HANDLERS.update({
    "get_workflow": _get_workflow,
})


# ============================================================================
# Webhook Triggers (one per HighLevel webhook event type)
# ============================================================================
# HighLevel has no PIT-registerable webhooks, so each trigger is a passive
# inbound receiver: the user adds a "Webhook" action to a HighLevel Workflow
# (whose trigger is the matching event) pointing at this trigger's minted URL —
# the endpoint identity is the event. Marketplace-app webhooks additionally carry
# a top-level `type` field, so when it's present we ALSO filter by it (a payload
# whose `type` doesn't match this trigger's event is dropped). Deliveries are
# unsigned (workflow webhooks) — the unguessable URL is the shared secret.

# op_name -> (HighLevel event `type` string, display name)
_GHL_WEBHOOK_EVENTS = {
    # Contacts
    "on_contact_create": ("ContactCreate", "On Contact Created"),
    "on_contact_update": ("ContactUpdate", "On Contact Updated"),
    "on_contact_delete": ("ContactDelete", "On Contact Deleted"),
    "on_contact_dnd_update": ("ContactDndUpdate", "On Contact DND Updated"),
    "on_contact_tag_update": ("ContactTagUpdate", "On Contact Tags Updated"),
    # Conversations / messaging
    "on_inbound_message": ("InboundMessage", "On Inbound Message"),
    "on_outbound_message": ("OutboundMessage", "On Outbound Message"),
    "on_conversation_unread": ("ConversationUnreadWebhook", "On Conversation Unread Change"),
    "on_conversation_update": ("ConversationUpdate", "On Conversation Updated"),
    "on_provider_outbound_message": ("ProviderOutboundMessage", "On Provider Outbound Message"),
    "on_email_stats": ("LCEmailStats", "On Email Stats (delivered/opened/clicked)"),
    # Opportunities
    "on_opportunity_create": ("OpportunityCreate", "On Opportunity Created"),
    "on_opportunity_update": ("OpportunityUpdate", "On Opportunity Updated"),
    "on_opportunity_delete": ("OpportunityDelete", "On Opportunity Deleted"),
    "on_opportunity_status_update": ("OpportunityStatusUpdate", "On Opportunity Status Changed"),
    "on_opportunity_stage_update": ("OpportunityStageUpdate", "On Opportunity Stage Changed"),
    "on_opportunity_monetary_value_update": ("OpportunityMonetaryValueUpdate", "On Opportunity Value Changed"),
    "on_opportunity_assigned_to_update": ("OpportunityAssignedToUpdate", "On Opportunity Assignee Changed"),
    # Appointments
    "on_appointment_create": ("AppointmentCreate", "On Appointment Created"),
    "on_appointment_update": ("AppointmentUpdate", "On Appointment Updated"),
    "on_appointment_delete": ("AppointmentDelete", "On Appointment Deleted"),
    # Notes
    "on_note_create": ("NoteCreate", "On Note Created"),
    "on_note_update": ("NoteUpdate", "On Note Updated"),
    "on_note_delete": ("NoteDelete", "On Note Deleted"),
    # Tasks
    "on_task_create": ("TaskCreate", "On Task Created"),
    "on_task_complete": ("TaskComplete", "On Task Completed"),
    "on_task_delete": ("TaskDelete", "On Task Deleted"),
    # Campaigns / Locations / Users
    "on_campaign_status_update": ("CampaignStatusUpdate", "On Campaign Status Changed"),
    "on_location_create": ("LocationCreate", "On Sub-Account Created"),
    "on_location_update": ("LocationUpdate", "On Sub-Account Updated"),
    "on_user_create": ("UserCreate", "On User Created"),
    "on_user_update": ("UserUpdate", "On User Updated"),
    "on_user_delete": ("UserDelete", "On User Deleted"),
    # Invoices
    "on_invoice_create": ("InvoiceCreate", "On Invoice Created"),
    "on_invoice_update": ("InvoiceUpdate", "On Invoice Updated"),
    "on_invoice_delete": ("InvoiceDelete", "On Invoice Deleted"),
    "on_invoice_sent": ("InvoiceSent", "On Invoice Sent"),
    "on_invoice_paid": ("InvoicePaid", "On Invoice Paid"),
    "on_invoice_partially_paid": ("InvoicePartiallyPaid", "On Invoice Partially Paid"),
    "on_invoice_void": ("InvoiceVoid", "On Invoice Voided"),
    # Orders / Products / Prices
    "on_order_create": ("OrderCreate", "On Order Created"),
    "on_order_status_update": ("OrderStatusUpdate", "On Order Status Changed"),
    "on_product_create": ("ProductCreate", "On Product Created"),
    "on_product_update": ("ProductUpdate", "On Product Updated"),
    "on_product_delete": ("ProductDelete", "On Product Deleted"),
    "on_price_create": ("PriceCreate", "On Price Created"),
    "on_price_update": ("PriceUpdate", "On Price Updated"),
    "on_price_delete": ("PriceDelete", "On Price Deleted"),
    # Custom objects: records / schemas / associations / relations
    "on_record_create": ("RecordCreate", "On Record Created"),
    "on_record_update": ("RecordUpdate", "On Record Updated"),
    "on_record_delete": ("RecordDelete", "On Record Deleted"),
    "on_object_schema_create": ("ObjectSchemaCreate", "On Object Schema Created"),
    "on_object_schema_update": ("ObjectSchemaUpdate", "On Object Schema Updated"),
    "on_association_create": ("AssociationCreate", "On Association Created"),
    "on_association_update": ("AssociationUpdate", "On Association Updated"),
    "on_association_delete": ("AssociationDelete", "On Association Deleted"),
    "on_relation_create": ("RelationCreate", "On Relation Created"),
    "on_relation_delete": ("RelationDelete", "On Relation Deleted"),
    # App lifecycle / SaaS / external / voice AI
    "on_app_install": ("AppInstall", "On App Installed"),
    "on_app_uninstall": ("AppUninstall", "On App Uninstalled"),
    "on_app_update": ("AppUpdate", "On App Updated"),
    "on_plan_change": ("PlanChange", "On SaaS Plan Changed"),
    "on_saas_plan_create": ("SaaSPlanCreate", "On SaaS Plan Created"),
    "on_external_auth_connected": ("ExternalAuthConnected", "On External Auth Connected"),
    "on_voice_ai_call_end": ("VoiceAiCallEnd", "On Voice AI Call Ended"),
    # Knowledge base
    "on_knowledge_base_create": ("KnowledgeBaseCreate", "On Knowledge Base Created"),
    "on_knowledge_base_update": ("KnowledgeBaseUpdate", "On Knowledge Base Updated"),
    "on_knowledge_base_delete": ("KnowledgeBaseDelete", "On Knowledge Base Deleted"),
    "on_knowledge_base_file_change": ("KnowledgeBaseFileChange", "On Knowledge Base File Changed"),
    "on_knowledge_base_faq_change": ("KnowledgeBaseFaqChange", "On Knowledge Base FAQ Changed"),
    "on_knowledge_base_rich_text_change": ("KnowledgeBaseRichTextChange", "On Knowledge Base Text Changed"),
    "on_knowledge_base_table_file_change": ("KnowledgeBaseTableFileChange", "On Knowledge Base Table Changed"),
    "on_knowledge_base_trained_url_change": ("KnowledgeBaseTrainedUrlChange", "On Knowledge Base URL Trained"),
}
_GHL_TRIGGER_EVENT_BY_OP = {op: ev for op, (ev, _d) in _GHL_WEBHOOK_EVENTS.items()}


def _ghl_webhook_url_field(event: str) -> Any:
    return Field(
        default=None,
        title="Webhook URL",
        description=(
            f"Add a 'Webhook' action to a HighLevel Workflow whose trigger is the "
            f"{event} event and point it at this URL. (If a marketplace-app webhook "
            f"is used instead, only {event} payloads are delivered.)"
        ),
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class _GHLWebhookTriggerBase(BaseModel):
    """Shared hidden webhook-lifecycle fields for the per-event triggers."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


def _make_ghl_trigger(op_name: str, event: str, display: str) -> type:
    cls_name = "GHL" + "".join(w.capitalize() for w in op_name.split("_")) + "Config"
    return create_model(
        cls_name,
        __base__=_GHLWebhookTriggerBase,
        operation=(
            Literal[op_name],
            Field(op_name, title=display, json_schema_extra={
                "const": op_name, "ui:hidden": True, "x-category": None,
                "x-is-trigger": True, "x-display-name": display,
            }),
        ),
        webhook_url=(Optional[str], _ghl_webhook_url_field(event)),
    )


GHL_TRIGGER_CONFIGS = [
    _make_ghl_trigger(op, ev, disp) for op, (ev, disp) in _GHL_WEBHOOK_EVENTS.items()
]


class GHLOnWebhookConfig(_GHLWebhookTriggerBase):
    """Catch-all: fire on ANY HighLevel webhook POSTed to this URL (no event
    filter). Useful with a marketplace-app single-URL subscription or when you
    want one endpoint for all of a workflow's events."""

    operation: Literal["on_webhook"] = Field(
        "on_webhook",
        json_schema_extra={
            "const": "on_webhook",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Any Webhook Event",
        },
        title="On Any Webhook Event",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description=(
            "Add a 'Webhook' action to a HighLevel Workflow and point it at this "
            "URL. Every event the workflow fires is delivered here."
        ),
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


GoHighLevelConfig = Annotated[
    Union[tuple([GHLOnWebhookConfig] + GHL_TRIGGER_CONFIGS + GHL_OPERATION_CONFIGS)],
    Discriminator("operation"),
]


class GoHighLevelNodeConfig(NodeConfig[GoHighLevelConfig, GoHighLevelCredential]):
    """Full configuration for the GoHighLevel node including credentials."""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class GoHighLevelNode(WorkflowNode):
    """GoHighLevel (LeadConnector) automation node."""

    edit_examples = [
        "Create a contact in GoHighLevel",
        "Search contacts by tag or query",
        "Create an opportunity in a pipeline",
        "Send an SMS to a contact",
        "Book an appointment on a calendar",
    ]

    @classmethod
    def get_config_model(cls):
        return GoHighLevelNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Filter inbound webhooks for the per-event triggers. Marketplace-app
        webhooks carry a top-level `type`; when present, drop deliveries whose
        `type` doesn't match this trigger's event. Workflow-action webhooks have
        no `type` (endpoint identity is the event) so they always pass. The
        catch-all `on_webhook` never filters. Non-trigger ops pass through."""
        op = config.get("operation")
        expected = _GHL_TRIGGER_EVENT_BY_OP.get(op)
        if expected is None:
            return payload
        event_type = payload.get("type") if isinstance(payload, dict) else None
        if event_type and event_type != expected:
            return None
        return payload

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Inbound HighLevel conversation message → the agent's user turn +
        the conversation id as key (one thread per GHL conversation). The
        send_a_new_message tool addresses replies by contact_id + channel type,
        so surface those VERBATIM. Outbound echoes and non-message payloads
        fall through to the raw-JSON default."""
        if not isinstance(output, dict):
            return super().resolve_agent_event(output)
        direction = str(output.get("direction") or "").strip().lower()
        if direction and direction != "inbound":
            return super().resolve_agent_event(output)  # never reply to our own outbound
        body = output.get("body") or output.get("message")
        conversation_id = str(output.get("conversationId") or "").strip()
        contact_id = str(output.get("contactId") or "").strip()
        if not body or not (conversation_id or contact_id):
            return super().resolve_agent_event(output)
        channel = str(output.get("messageType") or "").strip()  # top-level `type` is the event name, not the channel
        if contact_id:
            reply_hint = (
                f"To reply, use the GoHighLevel send message tool with contact_id={contact_id}"
                + (f" and type={channel}" if channel else "")
                + " (pass these exactly)."
            )
        else:
            reply_hint = (
                f"To reply, use the GoHighLevel send message tool — it needs the contact_id "
                f"for conversation {conversation_id}."
            )
        header = f"GoHighLevel {channel or 'inbound'} message from contact {contact_id or 'unknown'}:"
        return {
            "text": f"{header}\n{body}\n\n{reply_hint}",
            "conversation_key": conversation_id or contact_id,
        }

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the internal inbound webhook URL for the on_webhook trigger.
        HighLevel-side wiring is manual (a Workflow 'Webhook' action), so we only
        mint the URL the user pastes there."""
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool, user_id=user_id, workflow_id=workflow_id, node_id=node_id,
        )
        return {
            "values": {
                "webhook_id": webhook_data.get("webhook_id"),
                "webhook_url": webhook_data.get("webhook_url"),
                "relay_connected": webhook_data.get("relay_connected"),
                "is_production": webhook_data.get("is_production"),
            }
        }

    async def _request(
        self,
        token: str,
        method: str,
        endpoint: str,
        version: str = GHL_DEFAULT_VERSION,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
        files: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await _ghl_request(
            token, method, endpoint, version=version, params=params,
            json_body=json_body, action_name=action_name, files=files, data=data,
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, GoHighLevelNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        # Webhook trigger — passive receiver; the push path filters/passes via
        # resolve_trigger_payload, this handles manual runs.
        if isinstance(op, _GHLWebhookTriggerBase):
            return {
                "status": "success",
                "action": op.operation,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your GoHighLevel Private Integration Token."
            )
        token = credentials.token

        handler = GHL_OPERATION_HANDLERS.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(self, op, token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result
