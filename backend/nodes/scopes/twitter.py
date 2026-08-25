"""X (Twitter) operation → OAuth 2.0 scope requirements.

Verified against X's live OpenAPI spec (``https://api.x.com/2/openapi.json``),
which is the document each docs.x.com endpoint reference is rendered from. The
``security`` array per path is an AND: every scope listed is required together,
so most user-context reads carry ``tweet.read`` + ``users.read`` on top of
their feature scope.

Two things this table deliberately does NOT encode:

- **Access tiers.** The ``x-requires-tier`` markers on the operation configs
  (Basic ⭐ / Pro ⭐⭐) are X's paid-plan gating and are a different axis from
  scopes entirely — a correct scope set can still 403 on the wrong plan. They
  stay where they are; nothing here mirrors them.
- **App-Only endpoints.** Search-all, tweet counts, every stream, compliance
  jobs, connections, webhooks and the trends/usage lookups have no OAuth 2.0
  user-context path at all. They are declared with no scopes and pinned to the
  Bearer-token credential, because no amount of scope on the OAuth credential
  makes them reachable.

``offline.access`` never appears below: it is not an endpoint scope, it is what
mints a refresh token.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: App-Only endpoints reject user-context OAuth 2.0 outright, so they can only
#: run on the node's Bearer Token credential.
_APP_ONLY_NOTE = (
    "This endpoint has no OAuth 2.0 user-context path. Connect a Bearer Token "
    "(App-Only) credential from your X developer app to use it."
)


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


def _app_only() -> ScopeRequirement:
    return ScopeRequirement(
        credential_types=("twitter_bearer_token",), note=_APP_ONLY_NOTE
    )


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- OAuth 2.0 user context ----------------------------------------
    "add_member_to_list": _s("list.write", "tweet.read", "users.read"),
    "add_tweet_to_bookmarks": _s("bookmark.write", "tweet.read", "users.read"),
    "create_community_note_on_tweet": _s("tweet.write"),
    "create_list": _s("list.read", "list.write", "tweet.read", "users.read"),
    "create_tweet": _s("tweet.read", "tweet.write", "users.read"),
    "delete_community_note": _s("tweet.write"),
    "delete_list": _s("list.write", "tweet.read", "users.read"),
    "delete_tweet": _s("tweet.read", "tweet.write", "users.read"),
    "evaluate_community_note": _s("tweet.write"),
    "follow_list": _s("list.write", "tweet.read", "users.read"),
    "follow_user": _s("follows.write", "tweet.read", "users.read"),
    "get_authenticated_user": _s("tweet.read", "users.read"),
    "get_blocked_users": _s("block.read", "tweet.read", "users.read"),
    "get_bookmark_folders": _s("bookmark.read", "users.read"),
    "get_bookmarked_tweets": _s("bookmark.read", "tweet.read", "users.read"),
    "get_community_by_id": _s("list.read", "tweet.read", "users.read"),
    "get_community_notes_written": _s("tweet.read"),
    "get_home_timeline": _s("tweet.read", "users.read"),
    "get_list_by_id": _s("list.read", "tweet.read", "users.read"),
    "get_list_followers": _s("list.read", "tweet.read", "users.read"),
    "get_list_members": _s("list.read", "tweet.read", "users.read"),
    "get_lists_followed_by_user": _s("list.read", "tweet.read", "users.read"),
    "get_media_analytics": _s("tweet.read"),
    "get_muted_users": _s("mute.read", "tweet.read", "users.read"),
    "get_news_article_by_id": _s("tweet.read", "users.read"),
    "get_personalized_trending_topics": _s("tweet.read", "users.read"),
    "get_posts_eligible_for_community_notes": _s("tweet.read"),
    "get_tweet_analytics": _s("tweet.read", "users.read"),
    "get_tweet_by_id": _s("tweet.read", "users.read"),
    "get_tweet_retweeters": _s("tweet.read", "users.read"),
    "get_tweet_retweets": _s("tweet.read", "users.read"),
    "get_tweets_by_ids": _s("tweet.read", "users.read"),
    "get_tweets_from_list": _s("list.read", "tweet.read", "users.read"),
    "get_tweets_mentioning_user": _s("tweet.read", "users.read"),
    "get_tweets_posted_by_user": _s("tweet.read", "users.read"),
    "get_tweets_quoting_tweet": _s("tweet.read", "users.read"),
    "get_user_by_id": _s("tweet.read", "users.read"),
    "get_user_by_username": _s("tweet.read", "users.read"),
    "get_user_followers": _s("follows.read", "tweet.read", "users.read"),
    "get_user_liked_tweets": _s("like.read", "tweet.read", "users.read"),
    "get_user_list_memberships": _s("list.read", "tweet.read", "users.read"),
    "get_user_owned_lists": _s("list.read", "tweet.read", "users.read"),
    "get_user_pinned_lists": _s("list.read", "tweet.read", "users.read"),
    "get_users_by_ids": _s("tweet.read", "users.read"),
    "get_users_by_usernames": _s("tweet.read", "users.read"),
    "get_users_followed_by_user": _s("follows.read", "tweet.read", "users.read"),
    "get_users_who_liked_tweet": _s("like.read", "tweet.read", "users.read"),
    "like_tweet": _s("like.write", "tweet.read", "users.read"),
    "mute_user": _s("mute.write", "tweet.read", "users.read"),
    "pin_list": _s("list.write", "tweet.read", "users.read"),
    "remove_member_from_list": _s("list.write", "tweet.read", "users.read"),
    "remove_tweet_from_bookmarks": _s("bookmark.write", "tweet.read", "users.read"),
    "retweet_tweet": _s("tweet.read", "tweet.write", "users.read"),
    "search_communities": _s("tweet.read", "users.read"),
    "search_news_articles": _s("tweet.read", "users.read"),
    "search_recent_tweets": _s("tweet.read", "users.read"),
    "search_users": _s("tweet.read", "users.read"),
    "undo_retweet": _s("tweet.read", "tweet.write", "users.read"),
    "unfollow_list": _s("list.write", "tweet.read", "users.read"),
    "unfollow_user": _s("follows.write", "tweet.read", "users.read"),
    "unlike_tweet": _s("like.write", "tweet.read", "users.read"),
    "unmute_user": _s("mute.write", "tweet.read", "users.read"),
    "unpin_list": _s("list.write", "tweet.read", "users.read"),
    "update_list_metadata": _s("list.write", "tweet.read", "users.read"),

    # -- App-Only (Bearer token) ---------------------------------------
    "add_stream_filter_rules": _app_only(),
    "collect_10_percent_sampled_stream_tweets": _app_only(),
    "collect_filtered_stream_tweets": _app_only(),
    "collect_sampled_stream_tweets": _app_only(),
    "create_compliance_job": _app_only(),
    "create_webhook": _app_only(),
    "delete_stream_filter_rules": _app_only(),
    "delete_webhook": _app_only(),
    "get_account_activity_subscription_count": _app_only(),
    "get_all_streaming_connections": _app_only(),
    "get_api_usage": _app_only(),
    "get_compliance_job_by_id": _app_only(),
    "get_stream_filter_rules": _app_only(),
    "get_stream_rule_counts": _app_only(),
    "get_trending_topics_by_woeid": _app_only(),
    "get_tweet_counts_full_archive": _app_only(),
    "get_tweet_counts_recent": _app_only(),
    "list_compliance_jobs": _app_only(),
    "search_all_tweets_full_archive": _app_only(),
    "terminate_all_streaming_connections": _app_only(),
    "terminate_streaming_connection": _app_only(),
}

TWITTER_SCOPES = ScopeRegistry(
    provider="twitter",
    requirements=_REQUIREMENTS,
    unmapped=(
        # MISSING SCOPE: dm.read, dm.write
        # Every /2/dm_* endpoint is OAuth 2.0 user-context only (no App-Only)
        # and requires dm.read for reads / dm.write for writes. Both scopes are
        # commented out of x-oauth-scopes, so all ten DM operations 401 today.
        # Adding them forces every connected user to re-authorize.
        "block_user_dms",
        "create_group_direct_message_conversation",
        "delete_direct_message_event",
        "get_all_direct_message_events",
        "get_direct_message_conversation_with_user",
        "get_direct_message_event_by_id",
        "get_direct_message_events_for_conversation",
        "send_direct_message",
        "send_direct_message_to_conversation",
        "unblock_user_dms",

        # MISSING SCOPE: space.read
        # All six /2/spaces endpoints require space.read on top of
        # tweet.read + users.read. space.read is commented out of
        # x-oauth-scopes, so the whole Spaces surface is unreachable.
        "get_space_by_id",
        "get_space_ticket_holders",
        "get_spaces_by_creator_user_ids",
        "get_spaces_by_ids",
        "get_tweets_from_space",
        "search_spaces",

        # MISSING SCOPE: media.write
        # The /2/media upload, metadata and subtitle endpoints take exactly one
        # scope, media.write, which the node never requests. (get_media_analytics
        # is the exception — it needs tweet.read and IS mapped above.)
        # get_media_upload_status additionally calls GET /2/media/upload/status,
        # a path absent from X's OpenAPI spec — status is GET /2/media/upload
        # with command=STATUS.
        "create_media_metadata",
        "create_media_subtitles",
        "delete_media_subtitles",
        "get_media_upload_status",
        "upload_media",
        "upload_media_chunked",

        # MISSING SCOPE: tweet.moderate.write
        # PUT /2/tweets/{id}/hidden requires tweet.moderate.write in addition to
        # tweet.read + users.read. The node never requests it, so hiding and
        # unhiding replies both fail.
        "hide_reply_to_tweet",
        "unhide_reply_to_tweet",

        # The v2 block WRITE endpoints (POST /2/users/{id}/blocking and its
        # DELETE) are absent from X's OpenAPI spec — withdrawn from the public
        # v2 surface. block.write is still offered at authorize (and is
        # requested) but no documented endpoint consumes it, so there is nothing
        # to declare. Reads are mapped above via block.read.
        "block_user",
        "unblock_user",

        # These webhook paths are not in X's OpenAPI spec: validation is
        # PUT /2/webhooks/{id} (not POST .../validate), replay is
        # POST /2/webhooks/replay (not per-webhook), there is no
        # GET /2/webhooks/{id}, and stream links do not exist at all. The
        # documented /2/webhooks family takes App-Only or OAuth 1.0a and never
        # OAuth 2.0 user context, so no scope would apply either way.
        "create_webhook_replay",
        "create_webhook_stream_link",
        "delete_webhook_stream_link",
        "get_webhook_by_id",
        "get_webhook_stream_links",
        "validate_webhook",

        # MISSING SCOPE: dm.read, dm.write (create/validate subscription)
        # The node calls /2/account_activity/subscriptions*, but the documented
        # paths are /2/account_activity/webhooks/{webhook_id}/subscriptions/all.
        # Of the documented equivalents, create and validate need OAuth 2.0 user
        # context with dm.read + dm.write (neither requested); list and delete
        # are App-Only; and there is no documented replay endpoint. Because the
        # paths differ from the spec, nothing here is mapped.
        "create_account_activity_subscription",
        "create_account_activity_subscription_replay",
        "delete_account_activity_subscription",
        "get_account_activity_subscriptions",
        "validate_account_activity_subscription",

        # DELETE /2/connections/by/endpoint is not in the spec; the by-endpoint
        # form is DELETE /2/connections/{endpoint_id}, which the node exposes
        # separately as terminate_streaming_connection.
        "terminate_streaming_connections_by_endpoint_type",
    ),
)
