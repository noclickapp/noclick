"""Meta-family operation → Graph API permission requirements.

One module, four registries — the Meta ads node, Facebook Pages/Messenger,
Instagram and Threads all speak Graph API and share a permission vocabulary
(``pages_*`` spans three of them), so the shared constants stay shared.

Facts that shape every table here:

- **Documentation quality is inverted from API importance.** Threads publishes a
  clean scope-per-endpoint table; Instagram documents permissions on most
  reference pages; Facebook Pages on many; the **Marketing API on almost none** —
  campaign/adset/ad/creative CRUD, targeting and pixel pages carry no Permissions
  section at all. Where an endpoint page is silent, entries below fall back to a
  requirement Meta documents somewhere else (the permission's own Allowed Usage,
  or a product guide) and say so in ``note``. Where nothing documents it, the
  operation is ``unmapped`` rather than guessed.
- **Access level, not the scope string, is what usually bites.** Every permission
  is granted at Standard Access (app roles only) without review;
  ``ads_management``, ``ads_read``, ``business_management``,
  ``catalog_management``, ``leads_retrieval``, ``pages_messaging`` and
  ``pages_manage_ads`` need **Advanced Access = App Review + Business
  Verification** before they work for anyone but the app's own testers. An
  unapproved permission is indistinguishable from a missing one at runtime, so a
  green coverage test here does NOT mean an operation works.
- **Some gates are FEATURES, which have no scope string** and therefore cannot
  appear in this table: ``Instagram Public Content Access`` (hashtag search),
  ``Page Public Content Access`` (public Page reads), ``Business Asset User
  Profile Access`` (Messenger user profiles).
- **Business-Manager page roles add a rider.** Most Instagram endpoints add "if
  the token is from a User whose Page role was granted via Business Manager,
  ``ads_management`` or ``ads_read`` is also required" — a conditional on the
  USER, not the operation, so it is noted rather than encoded.

Threads is the odd one out: its own ``threads_*`` vocabulary, its own token, and
an unusually clean model — ``threads_basic`` on every endpoint plus one
capability scope per surface, including per-topic webhook permissions (the only
Meta product that documents those).
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str, note: str = "") -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes, note=note)


def _each(*operations: str, scopes: tuple[str, ...], note: str = "") -> dict:
    return {op: ScopeRequirement(scopes=scopes, note=note) for op in operations}


# Where an endpoint page carries no Permissions section, these say which
# document the requirement was taken from instead.
_ALLOWED_USAGE = (
    "The endpoint reference documents no permission; this is the permission's "
    "own Allowed Usage in Meta's permissions reference."
)
_MARKETING_BLANKET = (
    "Marketing API reference pages document no per-endpoint permission. Meta's "
    "Authorization guide states standard access to ads_read and ads_management "
    "is sufficient for managing your own ad account, advanced access for "
    "someone else's."
)
_BM_RIDER = (
    "If the app user's Page role was granted via Business Manager, "
    "ads_management or ads_read is additionally required."
)


# ---------------------------------------------------------------------------
# Meta (Marketing API / Business Manager / catalogs / lead ads)
# ---------------------------------------------------------------------------

_META_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- ad objects: reads -------------------------------------------------
    **_each(
        "list_ad_accounts",
        "get_ad_account",
        "list_campaigns",
        "get_campaign",
        "list_adsets",
        "get_adset",
        "list_ads",
        "get_ad",
        "list_creatives",
        "get_creative",
        "preview_ad",
        "list_images",
        "list_videos",
        "get_video",
        "list_custom_audiences",
        "get_custom_audience",
        "list_saved_audiences",
        "get_saved_audience",
        "list_pixels",
        "get_pixel",
        "get_pixel_stats",
        "search_targeting",
        "browse_targeting",
        "validate_targeting",
        "targeting_suggestions",
        "reach_estimate",
        "delivery_estimate",
        scopes=("ads_read",),
        note=_MARKETING_BLANKET,
    ),
    # -- ad objects: writes ------------------------------------------------
    **_each(
        "update_ad_account",
        "create_campaign",
        "update_campaign",
        "delete_campaign",
        "create_adset",
        "update_adset",
        "delete_adset",
        "create_ad",
        "update_ad",
        "delete_ad",
        "create_creative",
        "update_creative",
        "delete_creative",
        "upload_image",
        "upload_video",
        "delete_video",
        "create_saved_audience",
        "update_saved_audience",
        "delete_saved_audience",
        "create_pixel",
        "update_pixel",
        scopes=("ads_management",),
        note=_MARKETING_BLANKET,
    ),
    # -- insights (the one Marketing API area with a stated permission) -----
    **_each(
        "get_insights",
        "create_insights_report",
        "get_insights_report",
        "fetch_insights_report",
        scopes=("ads_read",),
        note=(
            'Insights guide: "You will need: The ads_read permission." The '
            "async report job is a POST but reads only."
        ),
    ),
    # -- custom audiences --------------------------------------------------
    **_each(
        "create_custom_audience",
        "update_custom_audience",
        "delete_custom_audience",
        "create_lookalike_audience",
        "add_audience_users",
        "remove_audience_users",
        scopes=("ads_management",),
        note=(
            'Audiences Overview: "The ads_management permission is required to '
            'create and update custom audiences." Also requires accepting the '
            "Custom Audience Terms of Service."
        ),
    ),
    # -- Business Manager ---------------------------------------------------
    **_each(
        "list_businesses",
        "get_business",
        "list_owned_pages",
        "list_owned_ad_accounts",
        "list_client_ad_accounts",
        "list_system_users",
        "list_business_users",
        "list_assigned_users",
        scopes=("business_management",),
        note=(
            'Business Manager guide: "access_token of user with '
            'business_management permission or an admin user".'
        ),
    ),
    # These four document a ROLE (admin user / admin system user) rather than a
    # scope; business_management is the permission whose Allowed Usage is
    # "Read and write with the Business Manager API".
    **_each(
        "create_system_user",
        "install_app_to_system_user",
        "generate_system_user_token",
        "assign_asset_user",
        scopes=("business_management",),
        note=(
            "Meta documents a role requirement (admin user, admin system user, "
            "or another system user) and no scope; " + _ALLOWED_USAGE
        ),
    ),
    # -- catalogs -----------------------------------------------------------
    # catalog_management lists business_management as a dependency, and the
    # catalog collection hangs off the Business node.
    **_each(
        "list_catalogs",
        "create_catalog",
        scopes=("business_management", "catalog_management"),
        note='Catalog Get Started: "business_management — Required to update your catalog."',
    ),
    **_each(
        "get_catalog",
        "update_catalog",
        "delete_catalog",
        "list_products",
        "create_product",
        "items_batch",
        "list_product_sets",
        "create_product_set",
        scopes=("catalog_management",),
        note="catalog_management declares business_management as a dependency.",
    ),
    # -- Conversions API: documented as needing NO permission ---------------
    **_each(
        "send_conversion_events",
        "send_offline_events",
        scopes=(),
        note=(
            'Conversions API Get Started: "Your app does not need to go through '
            'App Review. You do not need to request any permissions." It uses a '
            "system-user token minted in Events Manager."
        ),
    ),
    # -- page webhook subscription -------------------------------------------
    "subscribe_page_webhooks": _s(
        "pages_manage_metadata", "pages_show_list", "pages_read_engagement",
        note=(
            "POST /{page_id}/subscribed_apps requires pages_manage_metadata "
            "(subscribe the app to a Page's webhook fields, e.g. leadgen), plus "
            "pages_show_list/pages_read_engagement to resolve the Page token."
        ),
    ),
    # -- ad-account webhooks -------------------------------------------------
    **_each(
        "on_ad_in_process",
        "on_ad_issues",
        "on_ad_recommendations",
        "on_async_ad_creation",
        "on_creative_fatigue",
        "on_product_set_issue",
        scopes=("ads_management",),
        note=(
            "Meta documents no per-FIELD permission for ad_account webhooks, "
            'only the object-level rule: "The app should also have '
            'ads_management permission."'
        ),
    ),
}

META_SCOPES = ScopeRegistry(
    provider="meta",
    requirements=_META_REQUIREMENTS,
    unmapped=(
        # MISSING SCOPE: pages_manage_ads. Meta's Retrieving Leads guide lists,
        # for all lead data, ads_management + leads_retrieval + pages_show_list
        # + pages_read_engagement + pages_manage_ads. The node requests every
        # one of those except pages_manage_ads, so lead reads fail on it.
        "list_leads",
        "get_lead",
        "list_ad_leads",
        # MISSING SCOPE: pages_manage_ads. Same guide. Note additionally that
        # Meta documents GET /{page_id}/leadgen_forms as not supported.
        "list_leadgen_forms",
        "create_leadgen_form",
        # Lead-form and test-lead reference pages 404; nothing documents these.
        "get_leadgen_form",
        "archive_leadgen_form",
        "create_test_lead",
        "list_test_leads",
        # MISSING SCOPE: pages_manage_ads AND pages_manage_metadata. The leadgen
        # webhook (a Page-object subscription) needs leads_retrieval,
        # pages_manage_ads/pages_manage_metadata, pages_show_list,
        # pages_read_engagement and ads_management; the node requests only the
        # last three.
        "on_leadgen",
        # Subscribes to every field, so the requirement is the union of whatever
        # is configured in the App Dashboard.
        "on_any_meta_event",
        # Meta's share-custom-audiences guide names no scope, only a role:
        # "You need Business Manager admin permission to request a relationship
        # to share an audience."
        "share_audience",
        # POST /{pixel_id}/shared_accounts documents no permission.
        "share_pixel",
        # The caller supplies the node/edge, so the permission is whatever the
        # target object needs.
        "get_object",
        "graph_request",
    ),
)


# ---------------------------------------------------------------------------
# Facebook (Pages + Messenger)
# ---------------------------------------------------------------------------

#: Meta lists all three together for reading a Page and its content.
_PAGE_VIEW = ("pages_read_engagement", "pages_read_user_content", "pages_show_list")
_PAGE_USER_CONTENT = ("pages_read_engagement", "pages_read_user_content")
_MESSAGING = ("pages_messaging",)
_MESSENGER_NOTE = (
    "pages_messaging needs Advanced Access unless the app only messages its "
    "own Page. business_management is a documented dependency of it."
)

_FACEBOOK_REQUIREMENTS: dict[str, ScopeRequirement] = {
    "get_me": _s("public_profile"),
    "list_pages": _s(
        "pages_show_list",
        note='pages_show_list Allowed Usage: "Show a person the list of Pages they manage."',
    ),
    # -- page + content reads ----------------------------------------------
    **_each(
        "get_page",
        "read_feed",
        "list_posts",
        scopes=_PAGE_VIEW,
        note="Public Pages the user does not manage need the Page Public "
        "Content Access feature instead.",
    ),
    "get_post": _s(
        "pages_read_engagement",
        note="A Page token reads all of that Page's posts; public posts need "
        "the Page Public Content Access feature.",
    ),
    **_each(
        "read_comments",
        scopes=_PAGE_USER_CONTENT,
        note='object/comments: "The same permissions required to view the parent object."',
    ),
    "get_ratings": _s("pages_read_user_content"),
    "get_tagged": _s("pages_read_user_content", "pages_show_list"),
    "get_reactions": _s(
        "pages_show_list",
        note="Page-management apps need pages_show_list; marketing apps need "
        "ads_management + pages_read_engagement + pages_show_list.",
    ),
    # -- content writes ------------------------------------------------------
    **_each(
        "publish_post",
        "upload_photo",
        "upload_video",
        scopes=("pages_manage_posts", "pages_read_engagement", "pages_show_list"),
        note="Unpublished/ads-only videos need pages_manage_ads instead.",
    ),
    **_each(
        "update_post",
        "delete_post",
        scopes=("pages_manage_posts",),
        note=_ALLOWED_USAGE,
    ),
    "create_comment": _s("pages_manage_engagement"),
    **_each(
        "update_comment",
        "delete_comment",
        "hide_comment",
        scopes=("pages_manage_engagement",),
        note=_ALLOWED_USAGE,
    ),
    **_each("like_object", "unlike_object", scopes=("pages_manage_engagement",)),
    # -- page settings + webhook subscriptions --------------------------------
    **_each(
        "subscribe_page_webhooks",
        "list_page_subscriptions",
        scopes=("pages_manage_metadata", "pages_show_list"),
    ),
    "unsubscribe_page_webhooks": _s(
        "pages_manage_metadata",
        note="Meta documents the DELETE as taking an App Access Token and "
        "names no page-level permission.",
    ),
    # -- insights -------------------------------------------------------------
    "page_insights": _s("read_insights", "pages_read_engagement"),
    "post_insights": _s(
        "read_insights",
        note="The post/insights reference documents no permission; " + _ALLOWED_USAGE,
    ),
    # -- Messenger ------------------------------------------------------------
    **_each(
        "send_message",
        "private_reply",
        "send_attachment",
        "send_sender_action",
        "upload_message_attachment",
        "set_messenger_profile",
        "get_messenger_profile",
        scopes=_MESSAGING,
        note=_MESSENGER_NOTE,
    ),
    "get_conversations": _s(
        "pages_manage_metadata",
        "pages_read_engagement",
        "pages_messaging",
        note=_MESSENGER_NOTE,
    ),
    # -- triggers --------------------------------------------------------------
    **_each(
        "on_feed",
        "on_mention",
        "on_ratings",
        scopes=("pages_manage_metadata",),
        note=(
            "Meta documents no per-field permission for Page webhooks, only the "
            'object-level rule: "a page admin with MODERATE privileges must '
            'grant the app the pages_manage_metadata permission."'
        ),
    ),
    **_each(
        "on_messages",
        "on_messaging_postbacks",
        "on_messaging_referrals",
        "on_message_deliveries",
        "on_message_reads",
        "on_message_reactions",
        "on_standby",
        scopes=("pages_manage_metadata", "pages_messaging"),
        note=(
            "Messenger webhooks doc: a Page token from someone who can perform "
            "the MODERATE task, plus pages_messaging and pages_manage_metadata."
        ),
    ),
}

FACEBOOK_SCOPES = ScopeRegistry(
    provider="facebook",
    requirements=_FACEBOOK_REQUIREMENTS,
    unmapped=(
        # locale/timezone need pages_user_locale/pages_user_timezone and the
        # name/picture fields need the Business Asset User Profile Access FEATURE
        # — none of which are login-dialog scopes (they're granted at the app
        # level via App Review / the Messenger use case), so this op's access
        # cannot be satisfied by anything in the requested OAuth scope list.
        "get_user_profile",
        # Meta documents POST /{page_id} as "only available to select
        # developers" and names no general permission (only the `cover` field,
        # which needs the EDIT_PROFILE task plus business_management).
        "update_page",
        # Meta's Page reference documents no permission for these edges, and
        # their reference pages 404 or carry only an error-code list.
        "get_roles",
        "get_settings",
        "get_events",
        "get_blocked",
        "list_live_videos",
        "list_albums",
        "list_videos",
        "get_post_attachments",
        # Handover Protocol: works with a Page token (pass_thread_control to a
        # secondary receiver app); Meta documents no scope string for it.
        "thread_control",
        # Subscribes to every Page field at once, so the requirement is the
        # union of whatever is configured in the App Dashboard.
        "on_any_facebook_event",
        # The caller supplies the node/edge.
        "read_object",
        "graph_request",
    ),
)


# ---------------------------------------------------------------------------
# Instagram (Instagram API with Facebook Login)
# ---------------------------------------------------------------------------

_IG_BASE = ("instagram_basic", "pages_read_engagement")
_IG_COMMENTS = ("instagram_basic", "instagram_manage_comments", "pages_read_engagement")

_INSTAGRAM_REQUIREMENTS: dict[str, ScopeRequirement] = {
    **_each(
        "get_user_profile",
        "list_user_media",
        "get_media_details",
        scopes=_IG_BASE,
        note=_BM_RIDER,
    ),
    **_each(
        "publish_photo_post",
        "publish_video_reel",
        "publish_carousel_post",
        "publish_photo_story",
        "publish_video_story",
        scopes=("instagram_basic", "instagram_content_publish", "pages_read_engagement"),
        note=(
            "A container carrying product tags additionally needs "
            "catalog_management + instagram_shopping_tag_products and a "
            "Business Manager admin role. " + _BM_RIDER
        ),
    ),
    **_each(
        "list_media_comments",
        "create_media_comment",
        "reply_to_comment",
        "get_mentioned_media",
        "get_mentioned_comments",
        scopes=_IG_COMMENTS,
        note=_BM_RIDER,
    ),
    **_each(
        "hide_or_unhide_comment",
        "delete_comment",
        scopes=_IG_COMMENTS,
        note=(
            "The IG Comment reference names only a token requirement ('a user "
            "access token from the user who owns the media object' / 'who "
            "created the comment'); the comment-moderation overview places both "
            "in the instagram_manage_comments surface."
        ),
    ),
    **_each(
        "search_hashtag_id",
        "get_hashtag_media",
        scopes=_IG_BASE,
        note=(
            "Also requires the Instagram Public Content Access FEATURE, which "
            "has no scope string. " + _BM_RIDER
        ),
    ),
    # Apify-backed scraping; no Instagram credential is used.
    **_each(
        "scrape_profile_metadata",
        "scrape_profile_posts",
        "scrape_individual_post",
        "scrape_hashtag_posts",
        "scrape_profile_reels",
        "scrape_post_comments",
        scopes=(),
        note="Runs an Apify actor with NoClick's server-side token.",
    ),
}

INSTAGRAM_SCOPES = ScopeRegistry(
    provider="instagram",
    requirements=_INSTAGRAM_REQUIREMENTS,
    unmapped=(
        # MISSING SCOPE: instagram_manage_insights. Both insights endpoints
        # document "instagram_basic, instagram_manage_insights,
        # pages_read_engagement"; the node requests the first and third only,
        # so every insights call fails.
        "get_media_insights",
        "get_account_insights",
        # MISSING SCOPE: instagram_manage_insights. business_discovery documents
        # the same three permissions as insights.
        "discover_business_account",
        # MISSING SCOPE: instagram_shopping_tag_products AND catalog_management.
        # The product_tags endpoints document "instagram_basic,
        # instagram_shopping_tag_products, catalog_management" and require the
        # app to be tied to a verified business. The node requests neither
        # shopping permission.
        "tag_products_in_media",
        "get_media_product_tags",
        # As above, and Meta documents no DELETE on product_tags at all.
        "delete_product_tags_from_media",
    ),
)


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------

#: "Required for making any calls to all Threads API endpoints."
_TH = "threads_basic"
_TH_TABLE = (
    "The endpoint reference carries no Permissions section; this is from the "
    "scope table in Threads Get Started."
)

_THREADS_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # Reads of the authenticated account's own profile and posts.
    **_each(
        "get_me",
        "get_post",
        "list_posts",
        "list_ghost_posts",
        scopes=(_TH,),
    ),
    # Publishing endpoints.
    **_each(
        "create_post",
        "publish_post",
        "get_container_status",
        scopes=(_TH, "threads_content_publish"),
        note=_TH_TABLE,
    ),
    "get_publishing_limit": _s(
        _TH,
        note=(
            "Only threads_basic is confirmed: no source states an additional "
            "permission for threads_publishing_limit, and threads_basic is "
            "required for every Threads endpoint."
        ),
    ),
    "delete_post": _s(
        _TH,
        "threads_delete",
        note="Limited to 100 deletes per day per account.",
    ),
    # GET calls to reply endpoints.
    **_each(
        "get_replies",
        "get_conversation",
        "list_my_replies",
        "get_pending_replies",
        scopes=(_TH, "threads_read_replies"),
        note=_TH_TABLE,
    ),
    # POST calls to reply endpoints.
    **_each(
        "hide_reply",
        "manage_pending_reply",
        scopes=(_TH, "threads_manage_replies"),
        note=_TH_TABLE,
    ),
    # GET calls to insights endpoints.
    **_each("post_insights", "account_insights", scopes=(_TH, "threads_manage_insights")),
    "keyword_search": _s(
        _TH,
        "threads_keyword_search",
        note=(
            "Without approval for threads_keyword_search the search runs only "
            "over the authenticated user's own posts."
        ),
    ),
    "get_mentions": _s(
        _TH,
        "threads_manage_mentions",
        note=(
            "Without Advanced Access only mentions by the app's Threads testers "
            "are returned."
        ),
    ),
    "location_search": _s(_TH, "threads_location_tagging"),
    "get_location": _s(
        _TH,
        "threads_location_tagging",
        note="GET /{location_id} is not separately documented; it belongs to "
        "the location-tagging surface.",
    ),
    **_each(
        "lookup_profile",
        "list_public_posts",
        scopes=(_TH, "threads_profile_discovery"),
        note=(
            "threads_profile_discovery is required for all Threads Profile "
            "Discovery endpoints. At standard access only @meta, @threads, "
            "@instagram and @facebook can be looked up."
        ),
    ),
    # Threads is the only Meta product documenting per-topic webhook permissions.
    "on_publish": _s(_TH),
    "on_delete": _s(_TH, "threads_delete"),
    "on_replies": _s(_TH, "threads_read_replies"),
    "on_mentions": _s(
        _TH,
        "threads_manage_mentions",
        note="threads_read_replies is optionally required for reply mentions.",
    ),
    # Subscribes to every topic, so it is the union of all four.
    "on_any_threads_event": _s(
        _TH,
        "threads_delete",
        "threads_read_replies",
        "threads_manage_mentions",
    ),
}

THREADS_SCOPES = ScopeRegistry(
    provider="threads",
    requirements=_THREADS_REQUIREMENTS,
    unmapped=(
        # The caller supplies the endpoint path, so the permission is whatever
        # that endpoint needs.
        "threads_request",
    ),
)
