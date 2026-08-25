"""YouTube operation → Google OAuth scope requirements.

Verified against Google's per-method Authorization sections and the matching
API Discovery documents for the three APIs this node spans: YouTube Data v3,
YouTube Analytics v2, and YouTube Reporting v1.

Google lists several *alternative* scopes per method, any one of which
authorizes the call. A ``ScopeRequirement`` is an AND, so each entry below
names the single narrowest scope the node already requests:

- ``youtube.force-ssl`` covers the entire Data API surface here — every method
  except the two membership reads accepts it, including the ones ``youtube``
  itself does not (captions, comments, commentThreads).
- ``youtube.upload`` for the two upload methods. force-ssl would also work;
  the narrower purpose-built scope is what the node asks for, so that is what
  is declared.
- ``youtube.channel-memberships.creator`` is the ONLY scope ``members.list``
  and ``membershipsLevels.list`` accept — force-ssl does not authorize them.
- ``yt-analytics.readonly`` for Analytics and Reporting reads, escalating to
  ``yt-analytics-monetary.readonly`` for revenue metrics (that scope is a
  superset, but only it grants estimated revenue / ad performance).

``videoCategories.list``, ``i18nLanguages.list`` and ``i18nRegions.list``
return static public reference data and have no Authorization section at all —
they are API-key callable, so they declare no scope even though the node still
sends the OAuth token it has.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

_FORCE_SSL = "https://www.googleapis.com/auth/youtube.force-ssl"
_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
_MEMBERSHIPS = (
    "https://www.googleapis.com/auth/youtube.channel-memberships.creator"
)
_ANALYTICS = "https://www.googleapis.com/auth/yt-analytics.readonly"
_ANALYTICS_MONETARY = (
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
)


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- Videos --------------------------------------------------------
    "list_videos_by_id": _s(_FORCE_SSL),
    "list_region_popular_videos": _s(_FORCE_SSL),
    "list_authenticated_user_rated_videos": _s(_FORCE_SSL),
    "get_video": _s(_FORCE_SSL),
    "update_video_metadata": _s(_FORCE_SSL),
    "delete_video": _s(_FORCE_SSL),
    "rate_video": _s(_FORCE_SSL),
    "get_user_video_ratings": _s(_FORCE_SSL),
    # videos.insert and thumbnails.set both accept force-ssl too; the narrower
    # upload scope is the one the node requests for them.
    "upload_video_from_url": _s(_UPLOAD),
    "set_video_thumbnail": _s(_UPLOAD),
    # -- Channels ------------------------------------------------------
    "list_channels_by_id": _s(_FORCE_SSL),
    "get_authenticated_user_channel": _s(_FORCE_SSL),
    "update_channel_branding": _s(_FORCE_SSL),
    # -- Playlists -----------------------------------------------------
    "list_authenticated_user_playlists": _s(_FORCE_SSL),
    "list_playlists_by_id": _s(_FORCE_SSL),
    "list_channel_playlists": _s(_FORCE_SSL),
    "get_playlist": _s(_FORCE_SSL),
    "create_playlist": _s(_FORCE_SSL),
    "update_playlist": _s(_FORCE_SSL),
    "delete_playlist": _s(_FORCE_SSL),
    "list_playlist_items": _s(_FORCE_SSL),
    "add_video_to_playlist": _s(_FORCE_SSL),
    "update_playlist_item_position": _s(_FORCE_SSL),
    "remove_item_from_playlist": _s(_FORCE_SSL),
    # -- Search --------------------------------------------------------
    "search_youtube": _s(_FORCE_SSL),
    # -- Comments (force-ssl is the ONLY scope these accept) ------------
    "list_comment_replies": _s(_FORCE_SSL),
    "list_comments_by_id": _s(_FORCE_SSL),
    "list_video_comments": _s(_FORCE_SSL),
    "list_channel_video_comments": _s(_FORCE_SSL),
    "create_comment_reply": _s(_FORCE_SSL),
    "create_video_comment": _s(_FORCE_SSL),
    "create_channel_discussion_comment": _s(_FORCE_SSL),
    "update_comment": _s(_FORCE_SSL),
    "delete_comment": _s(_FORCE_SSL),
    "set_comment_moderation_status": _s(_FORCE_SSL),
    # -- Subscriptions -------------------------------------------------
    "list_subscriptions": _s(_FORCE_SSL),
    "subscribe_to_channel": _s(_FORCE_SSL),
    "unsubscribe_from_channel": _s(_FORCE_SSL),
    # -- Captions (force-ssl or youtubepartner only; plain `youtube` is not
    # accepted for any captions method) --------------------------------
    "list_video_captions": _s(_FORCE_SSL),
    "download_caption_track": _s(_FORCE_SSL),
    # -- Activities ----------------------------------------------------
    "list_authenticated_user_activities": _s(_FORCE_SSL),
    "list_channel_activities": _s(_FORCE_SSL),
    # -- Static reference data (no Authorization section; API-key callable)
    "list_video_categories": _s(),
    "list_supported_languages": _s(),
    "list_supported_regions": _s(),
    # -- Channel sections ----------------------------------------------
    "list_authenticated_user_channel_sections": _s(_FORCE_SSL),
    "list_channel_sections": _s(_FORCE_SSL),
    # -- Memberships (force-ssl does NOT authorize these) --------------
    "list_channel_members": _s(_MEMBERSHIPS),
    "list_membership_levels": _s(_MEMBERSHIPS),
    # -- Analytics API v2 ----------------------------------------------
    "get_channel_analytics": _s(_ANALYTICS),
    "get_video_analytics": _s(_ANALYTICS),
    "get_top_performing_videos": _s(_ANALYTICS),
    "get_viewer_demographics": _s(_ANALYTICS),
    "get_channel_traffic_sources": _s(_ANALYTICS),
    # Estimated revenue / ad performance metrics need the monetary scope
    # specifically; yt-analytics.readonly does not cover them.
    "get_channel_revenue_analytics": _s(_ANALYTICS_MONETARY),
    # -- Reporting API v1 (accepts only the two yt-analytics scopes) ----
    "list_bulk_reporting_types": _s(_ANALYTICS),
    "create_reporting_job": _s(_ANALYTICS),
    "list_reporting_jobs": _s(_ANALYTICS),
    "get_reporting_job": _s(_ANALYTICS),
    "delete_reporting_job": _s(_ANALYTICS),
    "list_reporting_job_reports": _s(_ANALYTICS),
    # -- Live broadcasts -----------------------------------------------
    "list_live_broadcasts": _s(_FORCE_SSL),
    "create_live_broadcast": _s(_FORCE_SSL),
    "update_live_broadcast": _s(_FORCE_SSL),
    "delete_live_broadcast": _s(_FORCE_SSL),
    "transition_broadcast_status": _s(_FORCE_SSL),
    "bind_broadcast_to_stream": _s(_FORCE_SSL),
    # -- Live streams --------------------------------------------------
    "list_live_streams": _s(_FORCE_SSL),
    "create_live_stream": _s(_FORCE_SSL),
    "update_live_stream": _s(_FORCE_SSL),
    "delete_live_stream": _s(_FORCE_SSL),
    # -- Live chat -----------------------------------------------------
    "list_live_chat_messages": _s(_FORCE_SSL),
    "send_live_chat_message": _s(_FORCE_SSL),
    "delete_live_chat_message": _s(_FORCE_SSL),
    "list_live_chat_moderators": _s(_FORCE_SSL),
    "add_live_chat_moderator": _s(_FORCE_SSL),
    "remove_live_chat_moderator": _s(_FORCE_SSL),
    "ban_live_chat_user": _s(_FORCE_SSL),
    "unban_live_chat_user": _s(_FORCE_SSL),
    "list_super_chat_events": _s(_FORCE_SSL),
}

YOUTUBE_SCOPES = ScopeRegistry(
    provider="youtube",
    requirements=_REQUIREMENTS,
)
