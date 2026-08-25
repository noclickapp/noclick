"""Klaviyo operation → OAuth scope requirements.

Klaviyo grants access with granular ``<resource>:read`` / ``<resource>:write``
scopes (https://developers.klaviyo.com/en/docs/authenticate_#scopes). Two
things shape this table:

- **A scope is per resource, and a call that crosses resources needs every one
  of them.** Reading the profiles on a list is ``lists:read`` AND
  ``profiles:read``; bulk-subscribing is ``lists:write`` + ``profiles:write`` +
  ``subscriptions:write``. Klaviyo publishes the exact set per endpoint as
  ``x-klaviyo-scopes`` in its OpenAPI spec
  (github.com/klaviyo/openapi ``openapi/stable.json``), which is what every
  entry below was derived from — not inferred from the resource name.
- **The same table covers both credentials.** A private API key carries scopes
  chosen at creation time from the same vocabulary, so a key minted without
  ``Full Access`` fails exactly where an OAuth token missing the scope would.

Push triggers are not API operations: each registers an outbound webhook
(``POST /webhooks``) at wire-up and deletes it (``DELETE /webhooks/{id}``) at
teardown, so they all need ``webhooks:write``. ``on_event`` additionally reads
the live topic list for its dropdown (``GET /webhook-topics``).
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


#: Registering and tearing down a trigger's outbound webhook.
_TRIGGER = _s("webhooks:write")

#: One discrete trigger per native ``event:klaviyo.*`` topic. Listed literally
#: rather than imported from the node — the node imports this module.
_DISCRETE_TRIGGERS = (
    "on_email_opened",
    "on_email_clicked",
    "on_email_clicked_to_unsubscribe",
    "on_email_received",
    "on_email_bounced",
    "on_email_dropped",
    "on_email_marked_spam",
    "on_sms_received",
    "on_sms_sent",
    "on_sms_clicked",
    "on_sms_failed",
    "on_sms_auto_response_received",
    "on_sms_auto_response_failed",
    "on_push_opened",
    "on_push_received",
    "on_push_bounced",
    "on_subscribed_email",
    "on_unsubscribed_email",
    "on_subscribed_sms",
    "on_unsubscribed_sms",
    "on_subscribed_to_list",
    "on_updated_email_preferences",
    "on_manually_suppressed_email",
    "on_manually_unsuppressed_email",
    "on_ready_to_review",
    "on_submitted_review",
    "on_submitted_rating",
    "on_social_comment",
    "on_social_dm",
    "on_social_ugc",
    "on_profile_merged",
    "on_skipped_send",
)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- Profiles ---------------------------------------------------------
    "get_profile": _s("profiles:read"),
    "list_profiles": _s("profiles:read"),
    "create_profile": _s("profiles:write"),
    "update_profile": _s("profiles:write"),
    "upsert_profile": _s("profiles:write"),  # POST /profile-import
    "merge_profiles": _s("profiles:write"),  # POST /profile-merge
    "get_profile_lists": _s("lists:read", "profiles:read"),
    "get_profile_segments": _s("profiles:read", "segments:read"),
    # Suppression/subscription jobs are consent writes, hence subscriptions:*.
    # Klaviyo asks for profiles:write on suppress but not on unsuppress.
    "suppress_profiles": _s("profiles:write", "subscriptions:write"),
    "unsuppress_profiles": _s("subscriptions:write"),
    "subscribe_profiles": _s("lists:write", "profiles:write", "subscriptions:write"),
    "unsubscribe_profiles": _s("lists:write", "profiles:write", "subscriptions:write"),
    # -- Lists ------------------------------------------------------------
    "list_lists": _s("lists:read"),
    "get_list": _s("lists:read"),
    "create_list": _s("lists:write"),
    "update_list": _s("lists:write"),
    "delete_list": _s("lists:write"),
    "get_list_profiles": _s("lists:read", "profiles:read"),
    "add_profiles_to_list": _s("lists:write", "profiles:write"),
    "remove_profiles_from_list": _s("lists:write", "profiles:write"),
    # -- Segments ---------------------------------------------------------
    "list_segments": _s("segments:read"),
    "get_segment": _s("segments:read"),
    "create_segment": _s("segments:write"),
    "update_segment": _s("segments:write"),
    "delete_segment": _s("segments:write"),
    "get_segment_profiles": _s("profiles:read", "segments:read"),
    # -- Events / metrics -------------------------------------------------
    "list_events": _s("events:read"),
    "get_event": _s("events:read"),
    "create_event": _s("events:write"),
    "list_metrics": _s("metrics:read"),
    "get_metric": _s("metrics:read"),
    "query_metric_aggregates": _s("metrics:read"),  # POST, but a read
    # -- Campaigns --------------------------------------------------------
    "list_campaigns": _s("campaigns:read"),
    "get_campaign": _s("campaigns:read"),
    "create_campaign": _s("campaigns:write"),
    "update_campaign": _s("campaigns:write"),
    "delete_campaign": _s("campaigns:write"),
    "send_campaign": _s("campaigns:write"),  # POST /campaign-send-jobs
    "clone_campaign": _s("campaigns:write"),  # POST /campaign-clone
    "get_campaign_messages": _s("campaigns:read"),
    # -- Flows ------------------------------------------------------------
    "list_flows": _s("flows:read"),
    "get_flow": _s("flows:read"),
    "update_flow_status": _s("flows:write"),
    "get_flow_actions": _s("flows:read"),
    "get_flow_messages": _s("flows:read"),
    # -- Templates --------------------------------------------------------
    "list_templates": _s("templates:read"),
    "get_template": _s("templates:read"),
    "create_template": _s("templates:write"),
    "update_template": _s("templates:write"),
    "delete_template": _s("templates:write"),
    "render_template": _s("templates:read"),  # POST /template-render
    "clone_template": _s("templates:write"),  # POST /template-clone
    # -- Catalog ----------------------------------------------------------
    "list_catalog_items": _s("catalogs:read"),
    "get_catalog_item": _s("catalogs:read"),
    "create_catalog_item": _s("catalogs:write"),
    "update_catalog_item": _s("catalogs:write"),
    "delete_catalog_item": _s("catalogs:write"),
    # -- Coupons ----------------------------------------------------------
    "list_coupons": _s("coupons:read"),
    "create_coupon": _s("coupons:write"),
    "list_coupon_codes": _s("coupon-codes:read"),
    "create_coupon_code": _s("coupon-codes:write"),
    # -- Tags -------------------------------------------------------------
    "list_tags": _s("tags:read"),
    "list_tag_groups": _s("tags:read"),
    "create_tag": _s("tags:read", "tags:write"),  # tag writes also require read
    # -- Images -----------------------------------------------------------
    "list_images": _s("images:read"),
    "upload_image_from_url": _s("images:write"),
    # -- Account / data privacy -------------------------------------------
    "get_account": _s("accounts:read"),
    "request_profile_deletion": _s("data-privacy:write"),
    # -- Webhook management -----------------------------------------------
    "list_webhooks": _s("webhooks:read"),
    "get_webhook": _s("webhooks:read"),
    "list_webhook_topics": _s("webhooks:read"),
    "create_webhook": _s("webhooks:write"),
    "update_webhook": _s("webhooks:write"),
    "delete_webhook": _s("webhooks:write"),
    # -- Triggers ---------------------------------------------------------
    # The topic dropdown reads GET /webhook-topics; the discrete triggers
    # resolve their topic from the operation and never call it.
    "on_event": _s("webhooks:read", "webhooks:write"),
    **{operation: _TRIGGER for operation in _DISCRETE_TRIGGERS},
}


KLAVIYO_SCOPES = ScopeRegistry(
    provider="klaviyo",
    requirements=_REQUIREMENTS,
)
