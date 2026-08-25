"""Reddit operation → OAuth scope requirements.

Verified against Reddit's own per-endpoint scope badges on
https://www.reddit.com/dev/api/ (cross-checked against the by-scope view at
/dev/api/oauth, which agreed endpoint-for-endpoint) and the live scope
dictionary at /api/v1/scopes.

Two quirks worth knowing before editing this table:

- **One scope per endpoint.** No documented Reddit endpoint carries more than
  one scope badge, and ``read`` is never required *alongside* a write scope.
  The multi-scope entries below are operations whose handler makes two
  different calls, not endpoints needing two scopes.
- **The badge is not always the obvious one.** Hiding a post is ``report``,
  marking your own post NSFW is ``modposts``, subreddit traffic is
  ``modconfig`` (not the ``modtraffic`` scope, which no endpoint uses), and
  ``/api/v1/me/karma`` is ``mysubreddits`` rather than ``identity``.

A handful of operations call endpoints Reddit has since dropped from its docs
entirely; those sit in ``unmapped`` rather than being scoped from the 2017
open-source snapshot.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- Identity and account ------------------------------------------
    "get_authenticated_user_info": _s("identity"),
    "get_authenticated_user_preferences": _s("identity"),
    # /api/v1/me/karma is badged mysubreddits, not identity.
    "get_karma_breakdown": _s("mysubreddits"),
    # Both are URL variants of GET /prefs/{where}, badged read.
    "get_friends_list": _s("read"),
    "get_blocked_users": _s("read"),
    # A self read hits /api/v1/me/trophies (identity); passing a username
    # switches the call to /user/{name}/trophies (read). Either path can run
    # per config, so the operation needs both.
    "get_user_trophies": _s("identity", "read"),
    # -- Users ---------------------------------------------------------
    "get_user_info": _s("read"),
    "get_user_posts": _s("history"),
    "get_user_comments": _s("history"),
    "get_user_saved_posts_and_comments": _s("history"),
    # Reads the target's about page, then POSTs /api/unfriend with
    # type=enemy, which that endpoint's docs put under privatemessages.
    "unblock_user": _s("read", "privatemessages"),
    "report_user": _s("report"),
    # Badged "any" — accessible with any combination of other scopes, so no
    # particular scope is required.
    "check_username_availability": _s(),
    # -- Subreddits ----------------------------------------------------
    # Served entirely from Reddit's public endpoints; no credential is used.
    "get_subreddit_posts": _s(),
    "get_subreddit_info": _s("read"),
    "get_subreddit_rules": _s("read"),
    "get_subreddit_moderators": _s("read"),
    "get_subreddit_comments": _s("read"),
    "search_subreddits": _s("read"),
    "get_popular_subreddits": _s("read"),
    "get_new_subreddits": _s("read"),
    "get_default_subreddits": _s("read"),
    "get_my_subscribed_subreddits": _s("mysubreddits"),
    "subscribe_to_subreddit": _s("subscribe"),
    # Traffic is served under modconfig, NOT the modtraffic scope — which no
    # documented endpoint uses at all.
    "get_subreddit_traffic_stats": _s("modconfig"),
    # -- Posts and comments --------------------------------------------
    "get_post": _s("read"),
    "get_post_comments": _s("read"),
    "get_duplicate_posts": _s("read"),
    "get_info_by_fullname_batch": _s("read"),
    "load_more_comments": _s("read"),
    "get_best_posts": _s("read"),
    "search_reddit": _s("read"),
    "submit_text_post": _s("submit"),
    "submit_link_post": _s("submit"),
    "crosspost_to_subreddit": _s("submit"),
    "submit_comment": _s("submit"),
    "vote_on_post_or_comment": _s("vote"),
    "edit_post_or_comment": _s("edit"),
    "delete_post_or_comment": _s("edit"),
    "save_post_or_comment": _s("save"),
    # /api/hide and /api/unhide sit under report, whose description covers
    # "Hide & show individual submissions".
    "hide_post_from_feed": _s("report"),
    "report_post_or_comment": _s("report"),
    # NSFW/spoiler marking is moderator surface even on your own post.
    "mark_post_as_nsfw": _s("modposts"),
    "mark_post_as_spoiler": _s("modposts"),
    # /api/sendreplies is badged edit, not modposts.
    "toggle_post_inbox_replies": _s("edit"),
    # -- Flair ---------------------------------------------------------
    "get_subreddit_link_flair_options": _s("flair"),
    "get_user_flair_options": _s("flair"),
    "set_post_link_flair": _s("flair"),
    "set_user_flair_in_subreddit": _s("flair"),
    # -- Multireddits --------------------------------------------------
    "get_multireddit": _s("read"),
    "get_my_multireddits": _s("read"),
    "create_multireddit": _s("subscribe"),
    "update_multireddit": _s("subscribe"),
    "delete_multireddit": _s("subscribe"),
    "add_subreddit_to_multireddit": _s("subscribe"),
    "remove_subreddit_from_multireddit": _s("subscribe"),
    # -- Private messages ----------------------------------------------
    "send_private_message": _s("privatemessages"),
    "get_inbox_messages": _s("privatemessages"),
    "mark_messages_as_read": _s("privatemessages"),
    "mark_all_messages_as_read": _s("privatemessages"),
    "delete_message": _s("privatemessages"),
    # Replying to a Message goes through /api/comment, which that endpoint's
    # docs put under privatemessages rather than submit.
    "reply_to_message": _s("privatemessages"),
    # -- Wiki ----------------------------------------------------------
    "list_wiki_pages": _s("wikiread"),
    "get_wiki_page": _s("wikiread"),
    "get_wiki_page_revisions": _s("wikiread"),
    # -- Live threads --------------------------------------------------
    "create_live_thread": _s("submit"),
    "post_live_thread_update": _s("submit"),
    "get_live_thread": _s("read"),
    "get_live_thread_updates": _s("read"),
    "close_live_thread": _s("livemanage"),
    # -- Moderation ----------------------------------------------------
    "approve_post_or_comment": _s("modposts"),
    "remove_post_or_comment": _s("modposts"),
    "distinguish_post_or_comment": _s("modposts"),
    "lock_post_or_comment": _s("modposts"),
    "sticky_or_unsticky_post": _s("modposts"),
    "set_post_contest_mode": _s("modposts"),
    "set_post_suggested_sort": _s("modposts"),
    "ignore_reports_on_content": _s("modposts"),
}

REDDIT_SCOPES = ScopeRegistry(
    provider="reddit",
    requirements=_REQUIREMENTS,
    unmapped=(
        # MISSING SCOPE: account
        # POST /api/block_user is documented under the `account` scope, which
        # the node never requests, so blocking always fails. Reddit further
        # gates it: "Only accessible to approved OAuth applications" — the
        # scope alone may not be sufficient. unblock_user takes a different
        # path (/api/unfriend type=enemy, privatemessages) and IS mapped, which
        # is why unblocking works while blocking cannot.
        "block_user",
        # MISSING SCOPE: creddits
        # POST /api/v1/gold/gild/{fullname} needed the `creddits` scope, never
        # requested. Reddit has since removed the whole gold section from its
        # API docs, so this operation is very likely dead regardless of scope —
        # deleting it is probably better than forcing a re-auth for it.
        "give_award_to_post_or_comment",
        # Absent from Reddit's current API docs. The 2017 open-source snapshot
        # puts these under `read` (requested) and /api/unread_message under
        # `privatemessages` (also requested), but a decade-old archive is not
        # current documentation, so nothing is declared for them.
        "get_gilded_content",
        "get_multireddit_posts",
        "get_random_submission",
        "get_random_subreddit",
        "mark_messages_as_unread",
    ),
)
