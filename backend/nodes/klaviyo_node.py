"""
Klaviyo (email/SMS marketing) automation node.

Covers the Klaviyo REST API across profiles, subscriptions, lists, segments,
events, metrics, campaigns, flows, templates, catalogs, coupons, tags, images,
accounts, data privacy, and webhook management — plus native push triggers
(one discrete trigger per native ``event:klaviyo.*`` topic, plus a generic
``on_event`` for custom ``event:api.*`` topics) backed by Klaviyo's outbound
webhooks (HMAC-SHA256 signed).

Klaviyo is a JSON:API service: request/response bodies wrap in a ``data`` object
(``{"data": {"type": "...", "attributes": {...}}}``), every request needs a
``revision`` date header, and it uses cursor pagination + a filter DSL. Async
bulk endpoints return 202 + a job resource.

Authentication (two methods):
- **Private API key** (primary): ``Authorization: Klaviyo-API-Key pk_xxx``.
- **OAuth 2.0** (PKCE, for marketplace apps): ``Authorization: Bearer <token>``.

Base URL: https://a.klaviyo.com/api
Docs: https://developers.klaviyo.com/en/reference/api_overview
"""

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, create_model
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.klaviyo import KLAVIYO_SCOPES

logger = logging.getLogger(__name__)

KLAVIYO_API = "https://a.klaviyo.com/api"
# Pinned JSON:API revision. Klaviyo requires this exact date header on every
# request; revisions live ~2 years. Bump deliberately (and re-verify) over time.
KLAVIYO_REVISION = "2025-07-15"
_JSONAPI = "application/vnd.api+json"


# ============================================================================
# Credential Schemas
# ============================================================================


class KlaviyoOAuthCredential(BaseModel):
    """OAuth 2.0 (PKCE) credential for Klaviyo — for marketplace/public apps.

    Access tokens expire ~hourly and are auto-refreshed via the refresh token.
    """

    credential_type: Literal["klaviyo_oauth"] = Field(
        "klaviyo_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="Account Name")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "klaviyo",
            "x-oauth-scopes": [
                "accounts:read",
                "campaigns:read", "campaigns:write",
                "catalogs:read", "catalogs:write",
                "coupons:read", "coupons:write",
                "coupon-codes:read", "coupon-codes:write",
                "data-privacy:write",
                "events:read", "events:write",
                "flows:read", "flows:write",
                "images:read", "images:write",
                "lists:read", "lists:write",
                "metrics:read",
                "profiles:read", "profiles:write",
                "segments:read", "segments:write",
                "subscriptions:read", "subscriptions:write",
                "tags:read", "tags:write",
                "templates:read", "templates:write",
                "webhooks:read", "webhooks:write",
            ],
            "x-oauth-supports-custom-client": True,
            "x-oauth-custom-client-help": (
                "Klaviyo OAuth is for approved marketplace/public apps. Register one in the "
                "Klaviyo developer portal, allowlist NoClick's callback as a redirect URI, and "
                "paste its client ID + secret — or use the Private API Key credential instead."
            ),
            "x-credential-url": "https://developers.klaviyo.com/en/docs/set_up_oauth",
        }
    )


class KlaviyoApiKeyCredential(BaseModel):
    """Private API key credential for Klaviyo (HTTP header auth).

    Create one in Klaviyo: Settings → API keys → Create Private API Key. Grant
    **Full Access** (or a Custom scope covering the operations you'll use) — the
    key's scopes are immutable after creation. Shown once; copy it immediately.
    """

    credential_type: Literal["klaviyo_api_key"] = Field(
        "klaviyo_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="Private API Key",
        description="Klaviyo private API key (starts with pk_). Settings → API keys.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://www.klaviyo.com/settings/account/api-keys",
            "x-credential-instructions": (
                "In Klaviyo, go to Settings → API keys → Create Private API Key. Give it Full "
                "Access (scopes can't be changed later) and paste the pk_ key here."
            ),
        }
    )


# OAuth first (frontend auto-sorts OAuth above API key).
KlaviyoCredential = Union[KlaviyoOAuthCredential, KlaviyoApiKeyCredential]


# ============================================================================
# Operation Configs
# ============================================================================
#
# Shared field helpers ------------------------------------------------------

def _attributes_field(desc: str, *, required: bool = True) -> Any:
    return Field(
        ... if required else None,
        title="Attributes (JSON)",
        description=desc,
        json_schema_extra={"ui:widget": "textarea"},
    )


def _filter_field() -> Any:
    return Field(
        None,
        title="Filter",
        description="Klaviyo filter DSL, e.g. equals(email,\"a@b.com\") or greater-than(created,2026-01-01T00:00:00Z)",
    )


def _list_id_field(required: bool = True) -> Any:
    return Field(
        ... if required else None,
        title="List",
        description="Klaviyo list ID",
        json_schema_extra={"x-resource-type": "klaviyo_list", "x-dynamic-options": {"field_name": "list_id", "searchable": True, "allow_custom": True, "placeholder": "Select a list…"}},
    )


def _metric_id_field(required: bool = True) -> Any:
    return Field(
        ... if required else None,
        title="Metric",
        description="Klaviyo metric ID",
        json_schema_extra={"x-dynamic-options": {"field_name": "metric_id", "searchable": True, "allow_custom": True, "placeholder": "Select a metric…"}},
    )


# --- Profiles ---------------------------------------------------------------

class KlaviyoGetProfileConfig(BaseModel):
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"const": "get_profile", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "Get Profile"}, title="Get Profile")
    profile_id: str = Field(..., title="Profile ID")
    additional_fields: Optional[str] = Field(None, title="Additional Fields", description="e.g. subscriptions,predictive_analytics", json_schema_extra={"enum": ["", "subscriptions", "predictive_analytics", "subscriptions,predictive_analytics"], "x-enum-searchable": True})


class KlaviyoListProfilesConfig(BaseModel):
    operation: Literal["list_profiles"] = Field("list_profiles", json_schema_extra={"const": "list_profiles", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "List Profiles"}, title="List Profiles")
    filter: Optional[str] = _filter_field()
    page_size: Optional[str] = Field(None, title="Page Size", description="Max results per page (default 20, max 100)")
    page_cursor: Optional[str] = Field(None, title="Page Cursor", description="Cursor from a previous response's links.next")


class KlaviyoCreateProfileConfig(BaseModel):
    operation: Literal["create_profile"] = Field("create_profile", json_schema_extra={"const": "create_profile", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "Create Profile"}, title="Create Profile")
    email: Optional[str] = Field(None, title="Email")
    phone_number: Optional[str] = Field(None, title="Phone Number", description="E.164, e.g. +12025550106")
    external_id: Optional[str] = Field(None, title="External ID")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    properties_json: Optional[str] = Field(None, title="Custom Properties (JSON)", json_schema_extra={"ui:widget": "textarea"})


class KlaviyoUpdateProfileConfig(BaseModel):
    operation: Literal["update_profile"] = Field("update_profile", json_schema_extra={"const": "update_profile", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "Update Profile"}, title="Update Profile")
    profile_id: str = Field(..., title="Profile ID")
    attributes_json: str = _attributes_field('Fields to update, e.g. {"first_name":"Ada","properties":{"plan":"pro"}}')


class KlaviyoUpsertProfileConfig(BaseModel):
    operation: Literal["upsert_profile"] = Field("upsert_profile", json_schema_extra={"const": "upsert_profile", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "Create or Update Profile"}, title="Create or Update Profile")
    email: Optional[str] = Field(None, title="Email")
    phone_number: Optional[str] = Field(None, title="Phone Number")
    external_id: Optional[str] = Field(None, title="External ID")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    properties_json: Optional[str] = Field(None, title="Custom Properties (JSON)", json_schema_extra={"ui:widget": "textarea"})


class KlaviyoMergeProfilesConfig(BaseModel):
    operation: Literal["merge_profiles"] = Field("merge_profiles", json_schema_extra={"const": "merge_profiles", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "Merge Profiles"}, title="Merge Profiles")
    destination_id: str = Field(..., title="Destination Profile ID", description="The profile kept (source merged into it)")
    source_id: str = Field(..., title="Source Profile ID", description="The profile merged away")


class KlaviyoGetProfileListsConfig(BaseModel):
    operation: Literal["get_profile_lists"] = Field("get_profile_lists", json_schema_extra={"const": "get_profile_lists", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "Get Profile's Lists"}, title="Get Profile's Lists")
    profile_id: str = Field(..., title="Profile ID")


class KlaviyoGetProfileSegmentsConfig(BaseModel):
    operation: Literal["get_profile_segments"] = Field("get_profile_segments", json_schema_extra={"const": "get_profile_segments", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "Get Profile's Segments"}, title="Get Profile's Segments")
    profile_id: str = Field(..., title="Profile ID")


class KlaviyoSuppressProfilesConfig(BaseModel):
    operation: Literal["suppress_profiles"] = Field("suppress_profiles", json_schema_extra={"const": "suppress_profiles", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "Suppress Profiles"}, title="Suppress Profiles")
    emails: str = Field(..., title="Emails", description="Comma-separated email addresses to suppress")


class KlaviyoUnsuppressProfilesConfig(BaseModel):
    operation: Literal["unsuppress_profiles"] = Field("unsuppress_profiles", json_schema_extra={"const": "unsuppress_profiles", "ui:hidden": True, "x-category": "Profiles", "x-display-name": "Unsuppress Profiles"}, title="Unsuppress Profiles")
    emails: str = Field(..., title="Emails", description="Comma-separated email addresses to unsuppress")


# --- Subscriptions ----------------------------------------------------------

class KlaviyoSubscribeProfilesConfig(BaseModel):
    operation: Literal["subscribe_profiles"] = Field("subscribe_profiles", json_schema_extra={"const": "subscribe_profiles", "ui:hidden": True, "x-category": "Subscriptions", "x-display-name": "Subscribe Profiles"}, title="Subscribe Profiles")
    list_id: str = _list_id_field()
    emails: str = Field(..., title="Emails", description="Comma-separated emails to subscribe (marketing consent)")
    custom_source: Optional[str] = Field("NoClick workflow", title="Consent Source")


class KlaviyoUnsubscribeProfilesConfig(BaseModel):
    operation: Literal["unsubscribe_profiles"] = Field("unsubscribe_profiles", json_schema_extra={"const": "unsubscribe_profiles", "ui:hidden": True, "x-category": "Subscriptions", "x-display-name": "Unsubscribe Profiles"}, title="Unsubscribe Profiles")
    list_id: str = _list_id_field()
    emails: str = Field(..., title="Emails", description="Comma-separated emails to unsubscribe")


# --- Lists ------------------------------------------------------------------

class KlaviyoListListsConfig(BaseModel):
    operation: Literal["list_lists"] = Field("list_lists", json_schema_extra={"const": "list_lists", "ui:hidden": True, "x-category": "Lists", "x-display-name": "Get Lists"}, title="Get Lists")
    filter: Optional[str] = _filter_field()


class KlaviyoGetListConfig(BaseModel):
    operation: Literal["get_list"] = Field("get_list", json_schema_extra={"const": "get_list", "ui:hidden": True, "x-category": "Lists", "x-display-name": "Get List"}, title="Get List")
    list_id: str = _list_id_field()


class KlaviyoCreateListConfig(BaseModel):
    operation: Literal["create_list"] = Field("create_list", json_schema_extra={"const": "create_list", "x-creates-resource": True, "x-resource-type": "klaviyo_list", "x-resource-id-path": "data.data.id", "ui:hidden": True, "x-category": "Lists", "x-display-name": "Create List"}, title="Create List")
    name: str = Field(..., title="List Name")


class KlaviyoUpdateListConfig(BaseModel):
    operation: Literal["update_list"] = Field("update_list", json_schema_extra={"const": "update_list", "ui:hidden": True, "x-category": "Lists", "x-display-name": "Update List"}, title="Update List")
    list_id: str = _list_id_field()
    name: str = Field(..., title="New Name")


class KlaviyoDeleteListConfig(BaseModel):
    operation: Literal["delete_list"] = Field("delete_list", json_schema_extra={"const": "delete_list", "ui:hidden": True, "x-category": "Lists", "x-display-name": "Delete List"}, title="Delete List")
    list_id: str = _list_id_field()


class KlaviyoGetListProfilesConfig(BaseModel):
    operation: Literal["get_list_profiles"] = Field("get_list_profiles", json_schema_extra={"const": "get_list_profiles", "ui:hidden": True, "x-category": "Lists", "x-display-name": "Get List Profiles"}, title="Get List Profiles")
    list_id: str = _list_id_field()
    page_cursor: Optional[str] = Field(None, title="Page Cursor")


class KlaviyoAddToListConfig(BaseModel):
    operation: Literal["add_profiles_to_list"] = Field("add_profiles_to_list", json_schema_extra={"const": "add_profiles_to_list", "ui:hidden": True, "x-category": "Lists", "x-display-name": "Add Profiles to List"}, title="Add Profiles to List")
    list_id: str = _list_id_field()
    profile_ids: str = Field(..., title="Profile IDs", description="Comma-separated profile IDs")


class KlaviyoRemoveFromListConfig(BaseModel):
    operation: Literal["remove_profiles_from_list"] = Field("remove_profiles_from_list", json_schema_extra={"const": "remove_profiles_from_list", "ui:hidden": True, "x-category": "Lists", "x-display-name": "Remove Profiles from List"}, title="Remove Profiles from List")
    list_id: str = _list_id_field()
    profile_ids: str = Field(..., title="Profile IDs", description="Comma-separated profile IDs")


# --- Segments ---------------------------------------------------------------

class KlaviyoListSegmentsConfig(BaseModel):
    operation: Literal["list_segments"] = Field("list_segments", json_schema_extra={"const": "list_segments", "ui:hidden": True, "x-category": "Segments", "x-display-name": "Get Segments"}, title="Get Segments")
    filter: Optional[str] = _filter_field()


class KlaviyoGetSegmentConfig(BaseModel):
    operation: Literal["get_segment"] = Field("get_segment", json_schema_extra={"const": "get_segment", "ui:hidden": True, "x-category": "Segments", "x-display-name": "Get Segment"}, title="Get Segment")
    segment_id: str = Field(..., title="Segment ID", json_schema_extra={"x-resource-type": "klaviyo_segment", "x-dynamic-options": {"field_name": "segment_id", "searchable": True, "allow_custom": True, "placeholder": "Select a segment…"}})


class KlaviyoCreateSegmentConfig(BaseModel):
    operation: Literal["create_segment"] = Field("create_segment", json_schema_extra={"const": "create_segment", "x-creates-resource": True, "x-resource-type": "klaviyo_segment", "x-resource-id-path": "data.data.id", "ui:hidden": True, "x-category": "Segments", "x-display-name": "Create Segment"}, title="Create Segment")
    name: str = Field(..., title="Segment Name")
    definition_json: str = _attributes_field("Segment definition (condition_groups), as JSON")


class KlaviyoUpdateSegmentConfig(BaseModel):
    operation: Literal["update_segment"] = Field("update_segment", json_schema_extra={"const": "update_segment", "ui:hidden": True, "x-category": "Segments", "x-display-name": "Update Segment"}, title="Update Segment")
    segment_id: str = Field(..., title="Segment ID")
    attributes_json: str = _attributes_field('e.g. {"name":"VIPs"} or {"definition":{...}}')


class KlaviyoDeleteSegmentConfig(BaseModel):
    operation: Literal["delete_segment"] = Field("delete_segment", json_schema_extra={"const": "delete_segment", "ui:hidden": True, "x-category": "Segments", "x-display-name": "Delete Segment"}, title="Delete Segment")
    segment_id: str = Field(..., title="Segment ID")


class KlaviyoGetSegmentProfilesConfig(BaseModel):
    operation: Literal["get_segment_profiles"] = Field("get_segment_profiles", json_schema_extra={"const": "get_segment_profiles", "ui:hidden": True, "x-category": "Segments", "x-display-name": "Get Segment Profiles"}, title="Get Segment Profiles")
    segment_id: str = Field(..., title="Segment ID")
    page_cursor: Optional[str] = Field(None, title="Page Cursor")


# --- Events -----------------------------------------------------------------

class KlaviyoListEventsConfig(BaseModel):
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"const": "list_events", "ui:hidden": True, "x-category": "Events", "x-display-name": "Get Events"}, title="Get Events")
    filter: Optional[str] = _filter_field()
    page_cursor: Optional[str] = Field(None, title="Page Cursor")


class KlaviyoGetEventConfig(BaseModel):
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"const": "get_event", "ui:hidden": True, "x-category": "Events", "x-display-name": "Get Event"}, title="Get Event")
    event_id: str = Field(..., title="Event ID")


class KlaviyoCreateEventConfig(BaseModel):
    operation: Literal["create_event"] = Field("create_event", json_schema_extra={"const": "create_event", "ui:hidden": True, "x-category": "Events", "x-display-name": "Track Event"}, title="Track Event")
    metric_name: str = Field(..., title="Metric Name", description="The event/metric name, e.g. 'Placed Order'")
    email: Optional[str] = Field(None, title="Profile Email")
    phone_number: Optional[str] = Field(None, title="Profile Phone")
    external_id: Optional[str] = Field(None, title="Profile External ID")
    properties_json: Optional[str] = Field(None, title="Event Properties (JSON)", json_schema_extra={"ui:widget": "textarea"})
    value: Optional[str] = Field(None, title="Value", description="Numeric value (e.g. order total)")


# --- Metrics ----------------------------------------------------------------

class KlaviyoListMetricsConfig(BaseModel):
    operation: Literal["list_metrics"] = Field("list_metrics", json_schema_extra={"const": "list_metrics", "ui:hidden": True, "x-category": "Metrics", "x-display-name": "Get Metrics"}, title="Get Metrics")


class KlaviyoGetMetricConfig(BaseModel):
    operation: Literal["get_metric"] = Field("get_metric", json_schema_extra={"const": "get_metric", "ui:hidden": True, "x-category": "Metrics", "x-display-name": "Get Metric"}, title="Get Metric")
    metric_id: str = _metric_id_field()


class KlaviyoQueryMetricAggregatesConfig(BaseModel):
    operation: Literal["query_metric_aggregates"] = Field("query_metric_aggregates", json_schema_extra={"const": "query_metric_aggregates", "ui:hidden": True, "x-category": "Metrics", "x-display-name": "Query Metric Aggregates"}, title="Query Metric Aggregates")
    attributes_json: str = _attributes_field('e.g. {"metric_id":"abc","measurements":["count"],"interval":"day","filter":["greater-or-equal(datetime,2026-01-01T00:00:00)","less-than(datetime,2026-02-01T00:00:00)"]}')


# --- Campaigns --------------------------------------------------------------

class KlaviyoListCampaignsConfig(BaseModel):
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"const": "list_campaigns", "ui:hidden": True, "x-category": "Campaigns", "x-display-name": "Get Campaigns"}, title="Get Campaigns")
    channel: str = Field("email", title="Channel", description="Klaviyo requires a channel filter", json_schema_extra={"enum": ["email", "sms", "mobile_push"], "x-enum-searchable": True})


class KlaviyoGetCampaignConfig(BaseModel):
    operation: Literal["get_campaign"] = Field("get_campaign", json_schema_extra={"const": "get_campaign", "ui:hidden": True, "x-category": "Campaigns", "x-display-name": "Get Campaign"}, title="Get Campaign")
    campaign_id: str = Field(..., title="Campaign ID")


class KlaviyoCreateCampaignConfig(BaseModel):
    operation: Literal["create_campaign"] = Field("create_campaign", json_schema_extra={"const": "create_campaign", "ui:hidden": True, "x-category": "Campaigns", "x-display-name": "Create Campaign"}, title="Create Campaign")
    attributes_json: str = _attributes_field('Campaign attributes (name, audiences, send_strategy, campaign-messages), as JSON')


class KlaviyoUpdateCampaignConfig(BaseModel):
    operation: Literal["update_campaign"] = Field("update_campaign", json_schema_extra={"const": "update_campaign", "ui:hidden": True, "x-category": "Campaigns", "x-display-name": "Update Campaign"}, title="Update Campaign")
    campaign_id: str = Field(..., title="Campaign ID")
    attributes_json: str = _attributes_field('e.g. {"name":"Summer Sale"}')


class KlaviyoDeleteCampaignConfig(BaseModel):
    operation: Literal["delete_campaign"] = Field("delete_campaign", json_schema_extra={"const": "delete_campaign", "ui:hidden": True, "x-category": "Campaigns", "x-display-name": "Delete Campaign"}, title="Delete Campaign")
    campaign_id: str = Field(..., title="Campaign ID")


class KlaviyoSendCampaignConfig(BaseModel):
    operation: Literal["send_campaign"] = Field("send_campaign", json_schema_extra={"const": "send_campaign", "ui:hidden": True, "x-category": "Campaigns", "x-display-name": "Send Campaign"}, title="Send Campaign")
    campaign_id: str = Field(..., title="Campaign ID", description="Creates a send job for this campaign")


class KlaviyoCloneCampaignConfig(BaseModel):
    operation: Literal["clone_campaign"] = Field("clone_campaign", json_schema_extra={"const": "clone_campaign", "ui:hidden": True, "x-category": "Campaigns", "x-display-name": "Clone Campaign"}, title="Clone Campaign")
    campaign_id: str = Field(..., title="Campaign ID")
    new_name: str = Field(..., title="New Campaign Name")


class KlaviyoGetCampaignMessagesConfig(BaseModel):
    operation: Literal["get_campaign_messages"] = Field("get_campaign_messages", json_schema_extra={"const": "get_campaign_messages", "ui:hidden": True, "x-category": "Campaigns", "x-display-name": "Get Campaign Messages"}, title="Get Campaign Messages")
    campaign_id: str = Field(..., title="Campaign ID")


# --- Flows ------------------------------------------------------------------

class KlaviyoListFlowsConfig(BaseModel):
    operation: Literal["list_flows"] = Field("list_flows", json_schema_extra={"const": "list_flows", "ui:hidden": True, "x-category": "Flows", "x-display-name": "Get Flows"}, title="Get Flows")
    filter: Optional[str] = _filter_field()


class KlaviyoGetFlowConfig(BaseModel):
    operation: Literal["get_flow"] = Field("get_flow", json_schema_extra={"const": "get_flow", "ui:hidden": True, "x-category": "Flows", "x-display-name": "Get Flow"}, title="Get Flow")
    flow_id: str = Field(..., title="Flow ID", json_schema_extra={"x-dynamic-options": {"field_name": "flow_id", "searchable": True, "allow_custom": True, "placeholder": "Select a flow…"}})


class KlaviyoUpdateFlowStatusConfig(BaseModel):
    operation: Literal["update_flow_status"] = Field("update_flow_status", json_schema_extra={"const": "update_flow_status", "ui:hidden": True, "x-category": "Flows", "x-display-name": "Update Flow Status"}, title="Update Flow Status")
    flow_id: str = Field(..., title="Flow ID")
    status: str = Field(..., title="Status", json_schema_extra={"enum": ["draft", "manual", "live"], "x-enum-searchable": True})


class KlaviyoGetFlowActionsConfig(BaseModel):
    operation: Literal["get_flow_actions"] = Field("get_flow_actions", json_schema_extra={"const": "get_flow_actions", "ui:hidden": True, "x-category": "Flows", "x-display-name": "Get Flow Actions"}, title="Get Flow Actions")
    flow_id: str = Field(..., title="Flow ID")


class KlaviyoGetFlowMessagesConfig(BaseModel):
    operation: Literal["get_flow_messages"] = Field("get_flow_messages", json_schema_extra={"const": "get_flow_messages", "ui:hidden": True, "x-category": "Flows", "x-display-name": "Get Flow Messages"}, title="Get Flow Messages")
    flow_action_id: str = Field(..., title="Flow Action ID", description="Messages hang off flow actions, not flows")


# --- Templates --------------------------------------------------------------

class KlaviyoListTemplatesConfig(BaseModel):
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"const": "list_templates", "ui:hidden": True, "x-category": "Templates", "x-display-name": "Get Templates"}, title="Get Templates")


class KlaviyoGetTemplateConfig(BaseModel):
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"const": "get_template", "ui:hidden": True, "x-category": "Templates", "x-display-name": "Get Template"}, title="Get Template")
    template_id: str = Field(..., title="Template ID", json_schema_extra={"x-resource-type": "klaviyo_template", "x-dynamic-options": {"field_name": "template_id", "searchable": True, "allow_custom": True, "placeholder": "Select a template…"}})


class KlaviyoCreateTemplateConfig(BaseModel):
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"const": "create_template", "x-creates-resource": True, "x-resource-type": "klaviyo_template", "x-resource-id-path": "data.data.id", "ui:hidden": True, "x-category": "Templates", "x-display-name": "Create Template"}, title="Create Template")
    name: str = Field(..., title="Template Name")
    html: str = Field(..., title="HTML", json_schema_extra={"ui:widget": "textarea"})
    editor_type: str = Field("CODE", title="Editor Type", json_schema_extra={"enum": ["CODE", "USER_DRAGGABLE", "SYSTEM_DRAGGABLE"], "x-enum-searchable": True})


class KlaviyoUpdateTemplateConfig(BaseModel):
    operation: Literal["update_template"] = Field("update_template", json_schema_extra={"const": "update_template", "ui:hidden": True, "x-category": "Templates", "x-display-name": "Update Template"}, title="Update Template")
    template_id: str = Field(..., title="Template ID")
    attributes_json: str = _attributes_field('e.g. {"name":"Welcome","html":"<html>…</html>"}')


class KlaviyoDeleteTemplateConfig(BaseModel):
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"const": "delete_template", "ui:hidden": True, "x-category": "Templates", "x-display-name": "Delete Template"}, title="Delete Template")
    template_id: str = Field(..., title="Template ID")


class KlaviyoRenderTemplateConfig(BaseModel):
    operation: Literal["render_template"] = Field("render_template", json_schema_extra={"const": "render_template", "ui:hidden": True, "x-category": "Templates", "x-display-name": "Render Template"}, title="Render Template")
    template_id: str = Field(..., title="Template ID")
    context_json: str = Field(..., title="Context (JSON)", description='Template variables, e.g. {"first_name":"Ada"}', json_schema_extra={"ui:widget": "textarea"})


class KlaviyoCloneTemplateConfig(BaseModel):
    operation: Literal["clone_template"] = Field("clone_template", json_schema_extra={"const": "clone_template", "ui:hidden": True, "x-category": "Templates", "x-display-name": "Clone Template"}, title="Clone Template")
    template_id: str = Field(..., title="Template ID")
    new_name: str = Field(..., title="New Template Name")


# --- Catalog items ----------------------------------------------------------

class KlaviyoListCatalogItemsConfig(BaseModel):
    operation: Literal["list_catalog_items"] = Field("list_catalog_items", json_schema_extra={"const": "list_catalog_items", "ui:hidden": True, "x-category": "Catalog", "x-display-name": "Get Catalog Items"}, title="Get Catalog Items")
    filter: Optional[str] = _filter_field()


class KlaviyoGetCatalogItemConfig(BaseModel):
    operation: Literal["get_catalog_item"] = Field("get_catalog_item", json_schema_extra={"const": "get_catalog_item", "ui:hidden": True, "x-category": "Catalog", "x-display-name": "Get Catalog Item"}, title="Get Catalog Item")
    item_id: str = Field(..., title="Catalog Item ID", description="Compound id, e.g. $custom:::$default:::SKU123")


class KlaviyoCreateCatalogItemConfig(BaseModel):
    operation: Literal["create_catalog_item"] = Field("create_catalog_item", json_schema_extra={"const": "create_catalog_item", "ui:hidden": True, "x-category": "Catalog", "x-display-name": "Create Catalog Item"}, title="Create Catalog Item")
    attributes_json: str = _attributes_field('e.g. {"external_id":"SKU123","title":"Shirt","description":"…","url":"https://…","price":19.99}')


class KlaviyoUpdateCatalogItemConfig(BaseModel):
    operation: Literal["update_catalog_item"] = Field("update_catalog_item", json_schema_extra={"const": "update_catalog_item", "ui:hidden": True, "x-category": "Catalog", "x-display-name": "Update Catalog Item"}, title="Update Catalog Item")
    item_id: str = Field(..., title="Catalog Item ID")
    attributes_json: str = _attributes_field('e.g. {"title":"New Title","price":24.99}')


class KlaviyoDeleteCatalogItemConfig(BaseModel):
    operation: Literal["delete_catalog_item"] = Field("delete_catalog_item", json_schema_extra={"const": "delete_catalog_item", "ui:hidden": True, "x-category": "Catalog", "x-display-name": "Delete Catalog Item"}, title="Delete Catalog Item")
    item_id: str = Field(..., title="Catalog Item ID")


# --- Coupons ----------------------------------------------------------------

class KlaviyoListCouponsConfig(BaseModel):
    operation: Literal["list_coupons"] = Field("list_coupons", json_schema_extra={"const": "list_coupons", "ui:hidden": True, "x-category": "Coupons", "x-display-name": "Get Coupons"}, title="Get Coupons")


class KlaviyoCreateCouponConfig(BaseModel):
    operation: Literal["create_coupon"] = Field("create_coupon", json_schema_extra={"const": "create_coupon", "ui:hidden": True, "x-category": "Coupons", "x-display-name": "Create Coupon"}, title="Create Coupon")
    external_id: str = Field(..., title="External ID", description="Unique coupon identifier (letters, digits, underscores only — no hyphens/spaces)")
    description: Optional[str] = Field(None, title="Description")


class KlaviyoListCouponCodesConfig(BaseModel):
    operation: Literal["list_coupon_codes"] = Field("list_coupon_codes", json_schema_extra={"const": "list_coupon_codes", "ui:hidden": True, "x-category": "Coupons", "x-display-name": "Get Coupon Codes"}, title="Get Coupon Codes")
    filter: str = Field(..., title="Filter", description="Required: filter by coupon or profile, e.g. any(coupon.id,[\"SUMMER\"]) or equals(profile.id,\"01H…\")")


class KlaviyoCreateCouponCodeConfig(BaseModel):
    operation: Literal["create_coupon_code"] = Field("create_coupon_code", json_schema_extra={"const": "create_coupon_code", "ui:hidden": True, "x-category": "Coupons", "x-display-name": "Create Coupon Code"}, title="Create Coupon Code")
    coupon_id: str = Field(..., title="Coupon ID", description="The parent coupon's id")
    code: str = Field(..., title="Code", description="The unique coupon code value")
    expires_at: Optional[str] = Field(None, title="Expires At", description="ISO 8601 datetime")


# --- Tags -------------------------------------------------------------------

class KlaviyoListTagsConfig(BaseModel):
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"const": "list_tags", "ui:hidden": True, "x-category": "Tags", "x-display-name": "Get Tags"}, title="Get Tags")


class KlaviyoCreateTagConfig(BaseModel):
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"const": "create_tag", "ui:hidden": True, "x-category": "Tags", "x-display-name": "Create Tag"}, title="Create Tag")
    name: str = Field(..., title="Tag Name")
    tag_group_id: Optional[str] = Field(None, title="Tag Group ID", description="Optional; defaults to the default tag group")


class KlaviyoListTagGroupsConfig(BaseModel):
    operation: Literal["list_tag_groups"] = Field("list_tag_groups", json_schema_extra={"const": "list_tag_groups", "ui:hidden": True, "x-category": "Tags", "x-display-name": "Get Tag Groups"}, title="Get Tag Groups")


# --- Images -----------------------------------------------------------------

class KlaviyoListImagesConfig(BaseModel):
    operation: Literal["list_images"] = Field("list_images", json_schema_extra={"const": "list_images", "ui:hidden": True, "x-category": "Images", "x-display-name": "Get Images"}, title="Get Images")


class KlaviyoUploadImageUrlConfig(BaseModel):
    operation: Literal["upload_image_from_url"] = Field("upload_image_from_url", json_schema_extra={"const": "upload_image_from_url", "ui:hidden": True, "x-category": "Images", "x-display-name": "Upload Image from URL"}, title="Upload Image from URL")
    import_from_url: str = Field(..., title="Image URL", description="Public URL to import the image from")
    name: Optional[str] = Field(None, title="Name")


# --- Accounts / Data privacy ------------------------------------------------

class KlaviyoGetAccountConfig(BaseModel):
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"const": "get_account", "ui:hidden": True, "x-category": "Account", "x-display-name": "Get Account"}, title="Get Account")


class KlaviyoRequestDeletionConfig(BaseModel):
    operation: Literal["request_profile_deletion"] = Field("request_profile_deletion", json_schema_extra={"const": "request_profile_deletion", "ui:hidden": True, "x-category": "Account", "x-display-name": "Request Profile Deletion"}, title="Request Profile Deletion")
    email: str = Field(..., title="Email", description="Email of the profile to delete (GDPR/CCPA; irreversible)")


# --- Webhook management -----------------------------------------------------

class KlaviyoListWebhooksConfig(BaseModel):
    operation: Literal["list_webhooks"] = Field("list_webhooks", json_schema_extra={"const": "list_webhooks", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Get Webhooks"}, title="Get Webhooks")


class KlaviyoGetWebhookConfig(BaseModel):
    operation: Literal["get_webhook"] = Field("get_webhook", json_schema_extra={"const": "get_webhook", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Get Webhook"}, title="Get Webhook")
    webhook_id: str = Field(..., title="Webhook ID")


class KlaviyoCreateWebhookConfig(BaseModel):
    operation: Literal["create_webhook"] = Field("create_webhook", json_schema_extra={"const": "create_webhook", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Create Webhook"}, title="Create Webhook")
    attributes_json: str = _attributes_field('e.g. {"name":"…","endpoint_url":"https://…","secret_key":"…","topics":["event:klaviyo.opened_email"]} — topics become a webhook-topics relationship; enabled is not settable on create')


class KlaviyoUpdateWebhookConfig(BaseModel):
    operation: Literal["update_webhook"] = Field("update_webhook", json_schema_extra={"const": "update_webhook", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Update Webhook"}, title="Update Webhook")
    webhook_id: str = Field(..., title="Webhook ID")
    attributes_json: str = _attributes_field('e.g. {"enabled":false}')


class KlaviyoDeleteWebhookConfig(BaseModel):
    operation: Literal["delete_webhook"] = Field("delete_webhook", json_schema_extra={"const": "delete_webhook", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Delete Webhook"}, title="Delete Webhook")
    webhook_id: str = Field(..., title="Webhook ID")


class KlaviyoListWebhookTopicsConfig(BaseModel):
    operation: Literal["list_webhook_topics"] = Field("list_webhook_topics", json_schema_extra={"const": "list_webhook_topics", "ui:hidden": True, "x-category": "Webhooks", "x-display-name": "Get Webhook Topics"}, title="Get Webhook Topics")


# --- Triggers: native Klaviyo events (push webhooks, HMAC-signed) ------------
#
# Every Klaviyo trigger registers an outbound webhook pointing at the NoClick
# webhook URL and verifies each delivery's ``Klaviyo-Signature`` (HMAC-SHA256
# over the raw body + the ``Klaviyo-Timestamp``, keyed by the secret set at
# registration). Decomposed into one discrete trigger per native
# ``event:klaviyo.*`` topic (so each event is directly discoverable in the
# operation picker and selectable by the AI builder), plus a generic
# ``on_event`` for custom / integration ``event:api.*`` topics that are
# account-specific and only surfaced by the live Get Webhook Topics dropdown.


class _KlaviyoTriggerBase(WebhookTriggerConfigBase):
    """Shared base for Klaviyo push triggers — carries the visible webhook URL.

    Topic subscription is resolved per-operation (see ``_TRIGGER_TOPIC_BY_OP``);
    discrete triggers don't render a topics field, only the generic ``on_event``
    does.
    """

    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description="NoClick auto-generates this and registers it with Klaviyo",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class KlaviyoOnEventConfig(_KlaviyoTriggerBase):
    """Fire on a custom / account-specific Klaviyo topic (choose from the live list)."""

    operation: Literal["on_event"] = Field(
        "on_event",
        json_schema_extra={"const": "on_event", "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Event (custom topic)"},
        title="On Event (custom topic)",
    )
    topics: str = Field(
        "event:klaviyo.opened_email",
        title="Topics",
        description="Comma-separated Klaviyo webhook topic IDs (see Get Webhook Topics), e.g. event:api.your_custom_metric",
        json_schema_extra={"x-dynamic-options": {"field_name": "topics", "searchable": True, "allow_custom": True, "placeholder": "Select topics…"}},
    )


# (operation, topic_id, display_name) — one discrete trigger per native topic.
# Grouped only for readability; all share the "Triggers" operation-picker category.
_TRIGGER_SPECS: List[tuple] = [
    # Email
    ("on_email_opened", "event:klaviyo.opened_email", "Email Opened"),
    ("on_email_clicked", "event:klaviyo.clicked_email", "Email Clicked"),
    ("on_email_clicked_to_unsubscribe", "event:klaviyo.clicked_email_to_unsubscribe", "Email Clicked to Unsubscribe"),
    ("on_email_received", "event:klaviyo.received_email", "Email Received"),
    ("on_email_bounced", "event:klaviyo.bounced_email", "Email Bounced"),
    ("on_email_dropped", "event:klaviyo.dropped_email", "Email Dropped"),
    ("on_email_marked_spam", "event:klaviyo.marked_email_as_spam", "Email Marked as Spam"),
    # SMS
    ("on_sms_received", "event:klaviyo.received_sms", "SMS Received"),
    ("on_sms_sent", "event:klaviyo.sent_sms", "SMS Sent"),
    ("on_sms_clicked", "event:klaviyo.clicked_sms", "SMS Clicked"),
    ("on_sms_failed", "event:klaviyo.failed_to_deliver_sms", "SMS Failed to Deliver"),
    ("on_sms_auto_response_received", "event:klaviyo.received_automated_response_sms", "SMS Automated Response Received"),
    ("on_sms_auto_response_failed", "event:klaviyo.failed_to_deliver_automated_response_sms", "SMS Automated Response Failed"),
    # Push
    ("on_push_opened", "event:klaviyo.opened_push", "Push Opened"),
    ("on_push_received", "event:klaviyo.received_push", "Push Received"),
    ("on_push_bounced", "event:klaviyo.bounced_push", "Push Bounced"),
    # Consent / subscription
    ("on_subscribed_email", "event:klaviyo.subscribed_to_email_marketing", "Subscribed to Email Marketing"),
    ("on_unsubscribed_email", "event:klaviyo.unsubscribed_from_email_marketing", "Unsubscribed from Email Marketing"),
    ("on_subscribed_sms", "event:klaviyo.subscribed_to_sms_marketing", "Subscribed to SMS Marketing"),
    ("on_unsubscribed_sms", "event:klaviyo.unsubscribed_from_sms_marketing", "Unsubscribed from SMS Marketing"),
    ("on_subscribed_to_list", "event:klaviyo.subscribed_to_list", "Subscribed to List"),
    ("on_updated_email_preferences", "event:klaviyo.updated_email_preferences", "Updated Email Preferences"),
    ("on_manually_suppressed_email", "event:klaviyo.manually_suppressed_from_email_marketing", "Manually Suppressed from Email Marketing"),
    ("on_manually_unsuppressed_email", "event:klaviyo.manually_unsuppressed_from_email_marketing", "Manually Unsuppressed from Email Marketing"),
    # Reviews / ratings
    ("on_ready_to_review", "event:klaviyo.ready_to_review", "Ready to Review"),
    ("on_submitted_review", "event:klaviyo.submitted_review", "Submitted Review"),
    ("on_submitted_rating", "event:klaviyo.submitted_rating", "Submitted Rating"),
    # Social
    ("on_social_comment", "event:klaviyo.social_comment", "Social Comment"),
    ("on_social_dm", "event:klaviyo.social_dm", "Social DM"),
    ("on_social_ugc", "event:klaviyo.social_ugc", "Social UGC"),
    # Profile / lifecycle
    ("on_profile_merged", "event:klaviyo.merged_profile", "Profile Merged"),
    ("on_skipped_send", "event:klaviyo.skipped_send", "Skipped Send"),
]

_TRIGGER_TOPIC_BY_OP: Dict[str, str] = {op: topic for op, topic, _ in _TRIGGER_SPECS}


def _make_trigger_config(operation: str, display: str):
    """Build a discrete trigger config model (one native topic) from the spec."""
    return create_model(
        f"Klaviyo{''.join(p.capitalize() for p in operation.split('_'))}Config",
        __base__=_KlaviyoTriggerBase,
        __module__=__name__,
        operation=(
            Literal[operation],
            Field(operation, title=display, json_schema_extra={
                "const": operation, "ui:hidden": True, "x-category": "Triggers",
                "x-is-trigger": True, "x-display-name": display,
            }),
        ),
    )


# Generate + expose each discrete trigger model as a module-level class.
_DISCRETE_TRIGGER_CONFIGS = []
for _op, _topic, _display in _TRIGGER_SPECS:
    _model = _make_trigger_config(_op, _display)
    globals()[_model.__name__] = _model
    _DISCRETE_TRIGGER_CONFIGS.append(_model)


KlaviyoConfig = Annotated[
    Union[(
        KlaviyoGetProfileConfig, KlaviyoListProfilesConfig, KlaviyoCreateProfileConfig,
        KlaviyoUpdateProfileConfig, KlaviyoUpsertProfileConfig, KlaviyoMergeProfilesConfig,
        KlaviyoGetProfileListsConfig, KlaviyoGetProfileSegmentsConfig,
        KlaviyoSuppressProfilesConfig, KlaviyoUnsuppressProfilesConfig,
        KlaviyoSubscribeProfilesConfig, KlaviyoUnsubscribeProfilesConfig,
        KlaviyoListListsConfig, KlaviyoGetListConfig, KlaviyoCreateListConfig,
        KlaviyoUpdateListConfig, KlaviyoDeleteListConfig, KlaviyoGetListProfilesConfig,
        KlaviyoAddToListConfig, KlaviyoRemoveFromListConfig,
        KlaviyoListSegmentsConfig, KlaviyoGetSegmentConfig, KlaviyoCreateSegmentConfig,
        KlaviyoUpdateSegmentConfig, KlaviyoDeleteSegmentConfig, KlaviyoGetSegmentProfilesConfig,
        KlaviyoListEventsConfig, KlaviyoGetEventConfig, KlaviyoCreateEventConfig,
        KlaviyoListMetricsConfig, KlaviyoGetMetricConfig, KlaviyoQueryMetricAggregatesConfig,
        KlaviyoListCampaignsConfig, KlaviyoGetCampaignConfig, KlaviyoCreateCampaignConfig,
        KlaviyoUpdateCampaignConfig, KlaviyoDeleteCampaignConfig, KlaviyoSendCampaignConfig,
        KlaviyoCloneCampaignConfig, KlaviyoGetCampaignMessagesConfig,
        KlaviyoListFlowsConfig, KlaviyoGetFlowConfig, KlaviyoUpdateFlowStatusConfig,
        KlaviyoGetFlowActionsConfig, KlaviyoGetFlowMessagesConfig,
        KlaviyoListTemplatesConfig, KlaviyoGetTemplateConfig, KlaviyoCreateTemplateConfig,
        KlaviyoUpdateTemplateConfig, KlaviyoDeleteTemplateConfig, KlaviyoRenderTemplateConfig,
        KlaviyoCloneTemplateConfig,
        KlaviyoListCatalogItemsConfig, KlaviyoGetCatalogItemConfig, KlaviyoCreateCatalogItemConfig,
        KlaviyoUpdateCatalogItemConfig, KlaviyoDeleteCatalogItemConfig,
        KlaviyoListCouponsConfig, KlaviyoCreateCouponConfig, KlaviyoListCouponCodesConfig,
        KlaviyoCreateCouponCodeConfig,
        KlaviyoListTagsConfig, KlaviyoCreateTagConfig, KlaviyoListTagGroupsConfig,
        KlaviyoListImagesConfig, KlaviyoUploadImageUrlConfig,
        KlaviyoGetAccountConfig, KlaviyoRequestDeletionConfig,
        KlaviyoListWebhooksConfig, KlaviyoGetWebhookConfig, KlaviyoCreateWebhookConfig,
        KlaviyoUpdateWebhookConfig, KlaviyoDeleteWebhookConfig, KlaviyoListWebhookTopicsConfig,
        # Triggers: generic custom-topic + one discrete config per native event:klaviyo.* topic
        KlaviyoOnEventConfig,
        *_DISCRETE_TRIGGER_CONFIGS,
    )],
    Discriminator("operation"),
]


class KlaviyoNodeConfig(NodeConfig[KlaviyoConfig, KlaviyoCredential]):
    """Full Klaviyo node configuration including credentials."""

    pass


# ============================================================================
# HTTP request helper (JSON:API)
# ============================================================================


def _auth_header(*, api_key: Optional[str] = None, access_token: Optional[str] = None) -> str:
    if access_token:
        return f"Bearer {access_token}"
    return f"Klaviyo-API-Key {api_key}"


def _resolve_auth(credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not credential:
        return None
    if credential.get("access_token"):
        return {"access_token": credential["access_token"]}
    if credential.get("api_key"):
        return {"api_key": credential["api_key"]}
    return None


def _data(type_: str, attributes: Optional[Dict[str, Any]] = None, id_: Optional[str] = None,
          relationships: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a JSON:API ``data`` object."""
    d: Dict[str, Any] = {"type": type_}
    if id_ is not None:
        d["id"] = id_
    if attributes is not None:
        d["attributes"] = attributes
    if relationships is not None:
        d["relationships"] = relationships
    return {"data": d}


def _prune(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, "")}


def _next_cursor(links: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract Klaviyo's cursor from a ``links.next`` URL (``?page[cursor]=…``)."""
    from urllib.parse import urlparse, parse_qs
    nxt = (links or {}).get("next")
    if not nxt:
        return None
    vals = parse_qs(urlparse(nxt).query).get("page[cursor]")
    return vals[0] if vals else None


async def _load_all_pages(auth: Dict[str, Any], path: str, page_size: Optional[int], *,
                          action_name: str, max_items: int = 500) -> List[Dict[str, Any]]:
    """Cursor-paginate a Klaviyo collection into a flat item list (for dropdowns)."""
    items: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    for _ in range(20):  # hard cap; max_items also bounds it
        params = _prune({"page[size]": page_size, "page[cursor]": cursor})
        result = await _klaviyo_request(auth, "GET", path, params=params or None, action_name=action_name)
        if result.get("status") != "success":
            break
        data = result.get("data") or {}
        items.extend(data.get("data", []))
        cursor = _next_cursor(data.get("links"))
        if not cursor or len(items) >= max_items:
            break
    return items


def _webhook_topics_relationship(topics: Any) -> Optional[Dict[str, Any]]:
    """Build the JSON:API ``webhook-topics`` relationship from a list or CSV of topic IDs.

    Klaviyo's Create/Update Webhook rejects ``topics`` as an attribute — topic
    subscriptions are a relationship of ``webhook-topic`` resource identifiers.
    """
    if not topics:
        return None
    ids = topics if isinstance(topics, list) else [t.strip() for t in str(topics).split(",") if t.strip()]
    ids = [t for t in ids if t]
    if not ids:
        return None
    return {"webhook-topics": {"data": [{"type": "webhook-topic", "id": t} for t in ids]}}


async def _klaviyo_request(
    auth: Dict[str, Any],
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    files: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Klaviyo JSON:API request and return a structured result."""
    url = f"{KLAVIYO_API}{path}"
    headers = {
        "Authorization": _auth_header(api_key=auth.get("api_key"), access_token=auth.get("access_token")),
        "revision": KLAVIYO_REVISION,
        "Accept": _JSONAPI,
    }
    if json_body is not None and files is None:
        headers["Content-Type"] = _JSONAPI
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body, files=files,
            )
            api_ms = round((time.time() - start) * 1000, 2)

            if response.status_code >= 400:
                message = _extract_error(response)
                logger.error(f"[KlaviyoNode] API error ({action_name}): {message}")
                return {
                    "status": "error", "action": action_name, "error": message,
                    "status_code": response.status_code, "timing_ms": {"api_request": api_ms},
                }

            if response.status_code == 204 or not response.content:
                # 202 (async job) with no body, or 204: surface the Location if present.
                data_out: Any = {"success": True}
                loc = response.headers.get("Location") or response.headers.get("location")
                if loc:
                    data_out["location"] = loc
            else:
                try:
                    data_out = response.json()
                except Exception:
                    data_out = {"raw": response.text}

            return {
                "status": "success", "action": action_name, "data": data_out,
                "status_code": response.status_code, "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timed out", "status_code": 408}
        except Exception as e:  # noqa: BLE001
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[KlaviyoNode] Request failed ({action_name}): {msg}")
            return {"status": "error", "action": action_name, "error": msg, "status_code": 500}


async def _klaviyo_request_retrying(auth, method, path, *, action_name, retries=3, **kw):
    """Like ``_klaviyo_request`` but retries transient 429s (Klaviyo throttles
    webhook writes ~1/sec). Used by webhook register/deregister so a throttle
    doesn't leave a trigger unregistered or a webhook orphaned."""
    result = None
    for attempt in range(retries):
        result = await _klaviyo_request(auth, method, path, action_name=action_name, **kw)
        if result.get("status_code") != 429:
            return result
        await asyncio.sleep(1.2 * (attempt + 1))
    return result


def _extract_error(response: "httpx.Response") -> str:
    """Klaviyo returns JSON:API errors: {"errors":[{"detail":"…","code":"…"}]}."""
    try:
        body = response.json()
    except Exception:
        return response.text or f"HTTP {response.status_code}"
    errs = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errs, list) and errs:
        return "; ".join(str(e.get("detail") or e.get("title") or e.get("code") or e) for e in errs)[:400]
    return str(body)[:400]


def _parse_json_field(raw: Optional[str], field: str) -> Any:
    import json as _json
    if not raw:
        return {}
    try:
        return _json.loads(raw)
    except Exception as e:
        raise ValueError(f"{field} must be valid JSON: {e}")


def _emails(csv: str) -> List[str]:
    return [e.strip() for e in (csv or "").split(",") if e.strip()]


def _ids(csv: str) -> List[str]:
    return [i.strip() for i in (csv or "").split(",") if i.strip()]


# ============================================================================
# Node Implementation
# ============================================================================


class KlaviyoNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Klaviyo (email/SMS marketing) automation node."""

    edit_examples = [
        "Create or update a Klaviyo profile when a form is submitted",
        "Subscribe an email to a Klaviyo list",
        "Track a 'Placed Order' event in Klaviyo",
        "Send a Klaviyo campaign",
        "Trigger a workflow when someone opens a Klaviyo email",
    ]

    scope_registry = KLAVIYO_SCOPES
    connection_evidence = ConnectionEvidence(
        field="list_id",
        noun="lists",
    )

    @classmethod
    def get_config_model(cls):
        return KlaviyoNodeConfig

    # ------------------------------------------------------------------
    # OAuth token refresh (OAuth credential only; API key needs none)
    # ------------------------------------------------------------------
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not (credential_data or {}).get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.klaviyo_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="klaviyo",
        )

    async def _resolve_fresh_auth(self, credentials) -> Dict[str, Any]:
        cred_dict = credentials.model_dump()
        if cred_dict.get("refresh_token"):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.klaviyo_oauth import refresh_access_token

            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id, credential=cred_dict,
                refresh=refresh_access_token, provider="klaviyo", caller_path="execute",
            )
        auth = _resolve_auth(cred_dict)
        if not auth:
            raise ValueError("Klaviyo credential is missing an API key / access token.")
        return auth

    # ------------------------------------------------------------------
    # Dynamic dropdowns
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None, page_token: Optional[str] = None, search: Optional[str] = None,
    ) -> Dict[str, Any]:
        auth = _resolve_auth(credential_data or {})
        if not auth:
            return {"options": []}

        # Per-resource page[size] CAPS differ (Klaviyo rejects over-limit / unsupported
        # page[size]): lists/segments/templates max 10, flows max 50, metrics take no
        # page[size]. Paginate via links.next so the dropdown isn't capped at one page.
        simple = {
            "list_id": ("/lists/", "name", 10),
            "segment_id": ("/segments/", "name", 10),
            "metric_id": ("/metrics/", "name", None),
            "flow_id": ("/flows/", "name", 50),
            "template_id": ("/templates/", "name", 10),
        }
        if field_name in simple:
            path, label_attr, page_size = simple[field_name]
            items = await _load_all_pages(auth, path, page_size, action_name=f"load_{field_name}")
            return {"options": [
                {"value": str(it.get("id")), "label": (it.get("attributes") or {}).get(label_attr) or str(it.get("id"))}
                for it in items if isinstance(it, dict) and it.get("id")
            ]}

        if field_name == "topics":
            result = await _klaviyo_request(auth, "GET", "/webhook-topics/", action_name="load_topics")
            items = (result.get("data") or {}).get("data", []) if result.get("status") == "success" else []
            return {"options": [{"value": str(it.get("id")), "label": str(it.get("id"))} for it in items if isinstance(it, dict) and it.get("id")]}

        return {"options": []}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, KlaviyoNodeConfig):
            raise ValueError("Valid configuration is required")

        op = config.config
        if isinstance(op, _KlaviyoTriggerBase):
            # Manual runs / trigger passthrough — the fired event arrives via inputs.
            return {"type": "klaviyo", "operation": op.operation, "status": "success",
                    "data": {**inputs, "webhook_url": op.webhook_url}}

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect a Klaviyo private API key or OAuth account.")
        auth = await self._resolve_fresh_auth(credentials)

        handler = self._HANDLERS.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")
        result = await handler(self, op, auth)
        if isinstance(result, dict):
            result.setdefault("timing_ms", {})
            result["timing_ms"]["total"] = round((time.time() - start_time) * 1000, 2)
        return result

    # -- Profiles ---------------------------------------------------------
    def _profile_attrs(self, c) -> Dict[str, Any]:
        attrs = _prune({
            "email": getattr(c, "email", None), "phone_number": getattr(c, "phone_number", None),
            "external_id": getattr(c, "external_id", None), "first_name": getattr(c, "first_name", None),
            "last_name": getattr(c, "last_name", None),
        })
        if getattr(c, "properties_json", None):
            attrs["properties"] = _parse_json_field(c.properties_json, "Custom Properties")
        return attrs

    async def _get_profile(self, c, auth):
        params = {"additional-fields[profile]": c.additional_fields} if c.additional_fields else None
        return await _klaviyo_request(auth, "GET", f"/profiles/{c.profile_id}/", params=params, action_name="get_profile")

    async def _list_profiles(self, c, auth):
        params = _prune({"filter": c.filter, "page[size]": c.page_size, "page[cursor]": c.page_cursor})
        return await _klaviyo_request(auth, "GET", "/profiles/", params=params, action_name="list_profiles")

    async def _create_profile(self, c, auth):
        return await _klaviyo_request(auth, "POST", "/profiles/", json_body=_data("profile", self._profile_attrs(c)), action_name="create_profile")

    async def _update_profile(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        return await _klaviyo_request(auth, "PATCH", f"/profiles/{c.profile_id}/", json_body=_data("profile", attrs, id_=c.profile_id), action_name="update_profile")

    async def _upsert_profile(self, c, auth):
        return await _klaviyo_request(auth, "POST", "/profile-import/", json_body=_data("profile", self._profile_attrs(c)), action_name="upsert_profile")

    async def _merge_profiles(self, c, auth):
        body = _data("profile-merge", id_=c.destination_id, relationships={"profiles": {"data": [{"type": "profile", "id": c.source_id}]}})
        return await _klaviyo_request(auth, "POST", "/profile-merge/", json_body=body, action_name="merge_profiles")

    async def _get_profile_lists(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/profiles/{c.profile_id}/lists/", action_name="get_profile_lists")

    async def _get_profile_segments(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/profiles/{c.profile_id}/segments/", action_name="get_profile_segments")

    async def _suppress_profiles(self, c, auth):
        profiles = [{"type": "profile", "attributes": {"email": e}} for e in _emails(c.emails)]
        body = _data("profile-suppression-bulk-create-job", {"profiles": {"data": profiles}})
        return await _klaviyo_request(auth, "POST", "/profile-suppression-bulk-create-jobs/", json_body=body, action_name="suppress_profiles")

    async def _unsuppress_profiles(self, c, auth):
        profiles = [{"type": "profile", "attributes": {"email": e}} for e in _emails(c.emails)]
        body = _data("profile-suppression-bulk-delete-job", {"profiles": {"data": profiles}})
        return await _klaviyo_request(auth, "POST", "/profile-suppression-bulk-delete-jobs/", json_body=body, action_name="unsuppress_profiles")

    # -- Subscriptions ----------------------------------------------------
    async def _subscribe_profiles(self, c, auth):
        profiles = [{"type": "profile", "attributes": {"email": e, "subscriptions": {"email": {"marketing": {"consent": "SUBSCRIBED"}}}}} for e in _emails(c.emails)]
        body = {"data": {"type": "profile-subscription-bulk-create-job", "attributes": {"custom_source": c.custom_source, "profiles": {"data": profiles}},
                         "relationships": {"list": {"data": {"type": "list", "id": c.list_id}}}}}
        return await _klaviyo_request(auth, "POST", "/profile-subscription-bulk-create-jobs/", json_body=body, action_name="subscribe_profiles")

    async def _unsubscribe_profiles(self, c, auth):
        profiles = [{"type": "profile", "attributes": {"email": e, "subscriptions": {"email": {"marketing": {"consent": "UNSUBSCRIBED"}}}}} for e in _emails(c.emails)]
        body = {"data": {"type": "profile-subscription-bulk-delete-job", "attributes": {"profiles": {"data": profiles}},
                         "relationships": {"list": {"data": {"type": "list", "id": c.list_id}}}}}
        return await _klaviyo_request(auth, "POST", "/profile-subscription-bulk-delete-jobs/", json_body=body, action_name="unsubscribe_profiles")

    # -- Lists ------------------------------------------------------------
    async def _list_lists(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/lists/", params=_prune({"filter": c.filter}), action_name="list_lists")

    async def _get_list(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/lists/{c.list_id}/", action_name="get_list")

    async def _create_list(self, c, auth):
        return await _klaviyo_request(auth, "POST", "/lists/", json_body=_data("list", {"name": c.name}), action_name="create_list")

    async def _update_list(self, c, auth):
        return await _klaviyo_request(auth, "PATCH", f"/lists/{c.list_id}/", json_body=_data("list", {"name": c.name}, id_=c.list_id), action_name="update_list")

    async def _delete_list(self, c, auth):
        return await _klaviyo_request(auth, "DELETE", f"/lists/{c.list_id}/", action_name="delete_list")

    async def _get_list_profiles(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/lists/{c.list_id}/profiles/", params=_prune({"page[cursor]": c.page_cursor}), action_name="get_list_profiles")

    async def _add_to_list(self, c, auth):
        data = [{"type": "profile", "id": i} for i in _ids(c.profile_ids)]
        return await _klaviyo_request(auth, "POST", f"/lists/{c.list_id}/relationships/profiles/", json_body={"data": data}, action_name="add_profiles_to_list")

    async def _remove_from_list(self, c, auth):
        data = [{"type": "profile", "id": i} for i in _ids(c.profile_ids)]
        return await _klaviyo_request(auth, "DELETE", f"/lists/{c.list_id}/relationships/profiles/", json_body={"data": data}, action_name="remove_profiles_from_list")

    # -- Segments ---------------------------------------------------------
    async def _list_segments(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/segments/", params=_prune({"filter": c.filter}), action_name="list_segments")

    async def _get_segment(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/segments/{c.segment_id}/", action_name="get_segment")

    async def _create_segment(self, c, auth):
        attrs = {"name": c.name, "definition": _parse_json_field(c.definition_json, "Definition")}
        return await _klaviyo_request(auth, "POST", "/segments/", json_body=_data("segment", attrs), action_name="create_segment")

    async def _update_segment(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        return await _klaviyo_request(auth, "PATCH", f"/segments/{c.segment_id}/", json_body=_data("segment", attrs, id_=c.segment_id), action_name="update_segment")

    async def _delete_segment(self, c, auth):
        return await _klaviyo_request(auth, "DELETE", f"/segments/{c.segment_id}/", action_name="delete_segment")

    async def _get_segment_profiles(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/segments/{c.segment_id}/profiles/", params=_prune({"page[cursor]": c.page_cursor}), action_name="get_segment_profiles")

    # -- Events -----------------------------------------------------------
    async def _list_events(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/events/", params=_prune({"filter": c.filter, "page[cursor]": c.page_cursor, "sort": "-datetime"}), action_name="list_events")

    async def _get_event(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/events/{c.event_id}/", action_name="get_event")

    async def _create_event(self, c, auth):
        profile_attrs = _prune({"email": c.email, "phone_number": c.phone_number, "external_id": c.external_id})
        props = _parse_json_field(c.properties_json, "Event Properties") if c.properties_json else {}
        attrs: Dict[str, Any] = {
            "properties": props,
            "metric": {"data": {"type": "metric", "attributes": {"name": c.metric_name}}},
            "profile": {"data": {"type": "profile", "attributes": profile_attrs}},
        }
        if c.value:
            try:
                attrs["value"] = float(c.value)
            except ValueError:
                attrs["value"] = c.value
        return await _klaviyo_request(auth, "POST", "/events/", json_body=_data("event", attrs), action_name="create_event")

    # -- Metrics ----------------------------------------------------------
    async def _list_metrics(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/metrics/", action_name="list_metrics")

    async def _get_metric(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/metrics/{c.metric_id}/", action_name="get_metric")

    async def _query_metric_aggregates(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        return await _klaviyo_request(auth, "POST", "/metric-aggregates/", json_body=_data("metric-aggregate", attrs), action_name="query_metric_aggregates")

    # -- Campaigns --------------------------------------------------------
    async def _list_campaigns(self, c, auth):
        params = {"filter": f"equals(messages.channel,'{c.channel}')"}
        return await _klaviyo_request(auth, "GET", "/campaigns/", params=params, action_name="list_campaigns")

    async def _get_campaign(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/campaigns/{c.campaign_id}/", action_name="get_campaign")

    async def _create_campaign(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        return await _klaviyo_request(auth, "POST", "/campaigns/", json_body=_data("campaign", attrs), action_name="create_campaign")

    async def _update_campaign(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        return await _klaviyo_request(auth, "PATCH", f"/campaigns/{c.campaign_id}/", json_body=_data("campaign", attrs, id_=c.campaign_id), action_name="update_campaign")

    async def _delete_campaign(self, c, auth):
        return await _klaviyo_request(auth, "DELETE", f"/campaigns/{c.campaign_id}/", action_name="delete_campaign")

    async def _send_campaign(self, c, auth):
        # The campaign-send-job resource IS keyed by the campaign id (no relationship).
        body = _data("campaign-send-job", id_=c.campaign_id)
        return await _klaviyo_request(auth, "POST", "/campaign-send-jobs/", json_body=body, action_name="send_campaign")

    async def _clone_campaign(self, c, auth):
        body = _data("campaign", {"new_name": c.new_name}, id_=c.campaign_id)
        return await _klaviyo_request(auth, "POST", "/campaign-clone/", json_body=body, action_name="clone_campaign")

    async def _get_campaign_messages(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/campaigns/{c.campaign_id}/campaign-messages/", action_name="get_campaign_messages")

    # -- Flows ------------------------------------------------------------
    async def _list_flows(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/flows/", params=_prune({"filter": c.filter}), action_name="list_flows")

    async def _get_flow(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/flows/{c.flow_id}/", action_name="get_flow")

    async def _update_flow_status(self, c, auth):
        return await _klaviyo_request(auth, "PATCH", f"/flows/{c.flow_id}/", json_body=_data("flow", {"status": c.status}, id_=c.flow_id), action_name="update_flow_status")

    async def _get_flow_actions(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/flows/{c.flow_id}/flow-actions/", action_name="get_flow_actions")

    async def _get_flow_messages(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/flow-actions/{c.flow_action_id}/flow-messages/", action_name="get_flow_messages")

    # -- Templates --------------------------------------------------------
    async def _list_templates(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/templates/", action_name="list_templates")

    async def _get_template(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/templates/{c.template_id}/", action_name="get_template")

    async def _create_template(self, c, auth):
        attrs = {"name": c.name, "editor_type": c.editor_type, "html": c.html}
        return await _klaviyo_request(auth, "POST", "/templates/", json_body=_data("template", attrs), action_name="create_template")

    async def _update_template(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        return await _klaviyo_request(auth, "PATCH", f"/templates/{c.template_id}/", json_body=_data("template", attrs, id_=c.template_id), action_name="update_template")

    async def _delete_template(self, c, auth):
        return await _klaviyo_request(auth, "DELETE", f"/templates/{c.template_id}/", action_name="delete_template")

    async def _render_template(self, c, auth):
        attrs = {"context": _parse_json_field(c.context_json, "Context")}
        return await _klaviyo_request(auth, "POST", "/template-render/", json_body=_data("template", attrs, id_=c.template_id), action_name="render_template")

    async def _clone_template(self, c, auth):
        return await _klaviyo_request(auth, "POST", "/template-clone/", json_body=_data("template", {"name": c.new_name}, id_=c.template_id), action_name="clone_template")

    # -- Catalog ----------------------------------------------------------
    async def _list_catalog_items(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/catalog-items/", params=_prune({"filter": c.filter}), action_name="list_catalog_items")

    async def _get_catalog_item(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/catalog-items/{c.item_id}/", action_name="get_catalog_item")

    async def _create_catalog_item(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        return await _klaviyo_request(auth, "POST", "/catalog-items/", json_body=_data("catalog-item", attrs), action_name="create_catalog_item")

    async def _update_catalog_item(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        return await _klaviyo_request(auth, "PATCH", f"/catalog-items/{c.item_id}/", json_body=_data("catalog-item", attrs, id_=c.item_id), action_name="update_catalog_item")

    async def _delete_catalog_item(self, c, auth):
        return await _klaviyo_request(auth, "DELETE", f"/catalog-items/{c.item_id}/", action_name="delete_catalog_item")

    # -- Coupons ----------------------------------------------------------
    async def _list_coupons(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/coupons/", action_name="list_coupons")

    async def _create_coupon(self, c, auth):
        attrs = _prune({"external_id": c.external_id, "description": c.description})
        return await _klaviyo_request(auth, "POST", "/coupons/", json_body=_data("coupon", attrs), action_name="create_coupon")

    async def _list_coupon_codes(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/coupon-codes/", params=_prune({"filter": c.filter}), action_name="list_coupon_codes")

    async def _create_coupon_code(self, c, auth):
        attrs = _prune({"unique_code": c.code, "expires_at": c.expires_at})
        body = _data("coupon-code", attrs, relationships={"coupon": {"data": {"type": "coupon", "id": c.coupon_id}}})
        return await _klaviyo_request(auth, "POST", "/coupon-codes/", json_body=body, action_name="create_coupon_code")

    # -- Tags -------------------------------------------------------------
    async def _list_tags(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/tags/", action_name="list_tags")

    async def _create_tag(self, c, auth):
        rels = {"tag-group": {"data": {"type": "tag-group", "id": c.tag_group_id}}} if c.tag_group_id else None
        return await _klaviyo_request(auth, "POST", "/tags/", json_body=_data("tag", {"name": c.name}, relationships=rels), action_name="create_tag")

    async def _list_tag_groups(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/tag-groups/", action_name="list_tag_groups")

    # -- Images -----------------------------------------------------------
    async def _list_images(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/images/", action_name="list_images")

    async def _upload_image_url(self, c, auth):
        attrs = _prune({"import_from_url": c.import_from_url, "name": c.name})
        return await _klaviyo_request(auth, "POST", "/images/", json_body=_data("image", attrs), action_name="upload_image_from_url")

    # -- Accounts / privacy ----------------------------------------------
    async def _get_account(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/accounts/", action_name="get_account")

    async def _request_deletion(self, c, auth):
        # data-privacy uses profile attributes inline; build explicitly.
        body = {"data": {"type": "data-privacy-deletion-job", "attributes": {"profile": {"data": {"type": "profile", "attributes": {"email": c.email}}}}}}
        return await _klaviyo_request(auth, "POST", "/data-privacy-deletion-jobs/", json_body=body, action_name="request_profile_deletion")

    # -- Webhook management ----------------------------------------------
    async def _list_webhooks(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/webhooks/", action_name="list_webhooks")

    async def _get_webhook(self, c, auth):
        return await _klaviyo_request(auth, "GET", f"/webhooks/{c.webhook_id}/", action_name="get_webhook")

    async def _create_webhook(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        rels = _webhook_topics_relationship(attrs.pop("topics", None))
        attrs.pop("enabled", None)  # not settable on create (defaults true)
        return await _klaviyo_request(auth, "POST", "/webhooks/", json_body=_data("webhook", attrs, relationships=rels), action_name="create_webhook")

    async def _update_webhook(self, c, auth):
        attrs = _parse_json_field(c.attributes_json, "Attributes")
        rels = _webhook_topics_relationship(attrs.pop("topics", None))
        return await _klaviyo_request(auth, "PATCH", f"/webhooks/{c.webhook_id}/", json_body=_data("webhook", attrs, id_=c.webhook_id, relationships=rels), action_name="update_webhook")

    async def _delete_webhook(self, c, auth):
        return await _klaviyo_request(auth, "DELETE", f"/webhooks/{c.webhook_id}/", action_name="delete_webhook")

    async def _list_webhook_topics(self, c, auth):
        return await _klaviyo_request(auth, "GET", "/webhook-topics/", action_name="list_webhook_topics")

    # ------------------------------------------------------------------
    # Push trigger — Klaviyo outbound webhook (HMAC-signed)
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "topics": (config or {}).get("topics"),
        }

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        import secrets as _secrets
        auth = _resolve_auth(credential or {})
        if not auth:
            raise ValueError("A connected Klaviyo account is required to register the trigger")
        cfg = config or {}
        # Generic on_event carries an explicit topics field; discrete triggers resolve
        # their single native topic from the operation.
        topics = [t.strip() for t in (cfg.get("topics") or "").split(",") if t.strip()]
        if not topics:
            mapped = _TRIGGER_TOPIC_BY_OP.get(cfg.get("operation"))
            topics = [mapped] if mapped else ["event:klaviyo.opened_email"]
        secret = _secrets.token_hex(24)  # >=16 chars; used for HMAC verification
        attrs = {
            "name": f"NoClick trigger {node_id}"[:64],
            "endpoint_url": webhook_url,
            "secret_key": secret,
        }
        body = _data("webhook", attrs, relationships=_webhook_topics_relationship(topics))
        result = await _klaviyo_request_retrying(auth, "POST", "/webhooks/", json_body=body, action_name="register_webhook")
        if result.get("status") != "success":
            raise ValueError(f"Failed to register Klaviyo webhook: {result.get('error')}")
        wid = ((result.get("data") or {}).get("data") or {}).get("id")
        if not wid:
            raise ValueError("Klaviyo webhook registration returned no id")
        return {"external_webhook_id": str(wid), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        auth = _resolve_auth(credential or {})
        external_id = (config or {}).get("external_webhook_id")
        if not auth or not external_id:
            return
        result = await _klaviyo_request_retrying(auth, "DELETE", f"/webhooks/{external_id}/", action_name="unregister_webhook")
        # 204 = deleted; 404 = already gone (idempotent). Any other failure must
        # RAISE so the lifecycle choke point keeps the row as a record of a
        # possibly-live endpoint instead of silently orphaning it.
        if result.get("status") == "success" or result.get("status_code") == 404:
            return
        raise ValueError(f"Failed to delete Klaviyo webhook {external_id}: {result.get('error')}")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        """Verify ``Klaviyo-Signature`` = HMAC-SHA256(rawBody + timestamp, secret_key), hex."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — don't hard-block
        sig = headers.get("klaviyo-signature") or headers.get("Klaviyo-Signature")
        ts = headers.get("klaviyo-timestamp") or headers.get("Klaviyo-Timestamp")
        if not sig or not ts:
            return False
        mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
        mac.update(ts.encode("utf-8"))  # timestamp appended AFTER the raw body
        return hmac.compare_digest(mac.hexdigest(), sig)

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Dict[str, Any]:
        import json as _json
        data = output.get("data", output) if isinstance(output, dict) else output
        return {"text": _json.dumps(data, default=str), "conversation_key": None}

    _HANDLERS = {
        "get_profile": _get_profile, "list_profiles": _list_profiles, "create_profile": _create_profile,
        "update_profile": _update_profile, "upsert_profile": _upsert_profile, "merge_profiles": _merge_profiles,
        "get_profile_lists": _get_profile_lists, "get_profile_segments": _get_profile_segments,
        "suppress_profiles": _suppress_profiles, "unsuppress_profiles": _unsuppress_profiles,
        "subscribe_profiles": _subscribe_profiles, "unsubscribe_profiles": _unsubscribe_profiles,
        "list_lists": _list_lists, "get_list": _get_list, "create_list": _create_list,
        "update_list": _update_list, "delete_list": _delete_list, "get_list_profiles": _get_list_profiles,
        "add_profiles_to_list": _add_to_list, "remove_profiles_from_list": _remove_from_list,
        "list_segments": _list_segments, "get_segment": _get_segment, "create_segment": _create_segment,
        "update_segment": _update_segment, "delete_segment": _delete_segment, "get_segment_profiles": _get_segment_profiles,
        "list_events": _list_events, "get_event": _get_event, "create_event": _create_event,
        "list_metrics": _list_metrics, "get_metric": _get_metric, "query_metric_aggregates": _query_metric_aggregates,
        "list_campaigns": _list_campaigns, "get_campaign": _get_campaign, "create_campaign": _create_campaign,
        "update_campaign": _update_campaign, "delete_campaign": _delete_campaign, "send_campaign": _send_campaign,
        "clone_campaign": _clone_campaign, "get_campaign_messages": _get_campaign_messages,
        "list_flows": _list_flows, "get_flow": _get_flow, "update_flow_status": _update_flow_status,
        "get_flow_actions": _get_flow_actions, "get_flow_messages": _get_flow_messages,
        "list_templates": _list_templates, "get_template": _get_template, "create_template": _create_template,
        "update_template": _update_template, "delete_template": _delete_template, "render_template": _render_template,
        "clone_template": _clone_template,
        "list_catalog_items": _list_catalog_items, "get_catalog_item": _get_catalog_item,
        "create_catalog_item": _create_catalog_item, "update_catalog_item": _update_catalog_item,
        "delete_catalog_item": _delete_catalog_item,
        "list_coupons": _list_coupons, "create_coupon": _create_coupon,
        "list_coupon_codes": _list_coupon_codes, "create_coupon_code": _create_coupon_code,
        "list_tags": _list_tags, "create_tag": _create_tag, "list_tag_groups": _list_tag_groups,
        "list_images": _list_images, "upload_image_from_url": _upload_image_url,
        "get_account": _get_account, "request_profile_deletion": _request_deletion,
        "list_webhooks": _list_webhooks, "get_webhook": _get_webhook, "create_webhook": _create_webhook,
        "update_webhook": _update_webhook, "delete_webhook": _delete_webhook, "list_webhook_topics": _list_webhook_topics,
    }
