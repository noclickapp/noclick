"""TikTok operation → OAuth scope requirements.

TikTok splits its surface across two products with disjoint scope vocabularies:
the **Display API** (``user.info.*``, ``video.list``) reads the authenticated
creator's profile and public videos, and the **Content Posting API**
(``video.upload``, ``video.publish``) writes.

Two quirks shape this table:

- **The user-info scopes are per-FIELD, not per-endpoint.** ``/v2/user/info/``
  is one endpoint whose ``fields`` parameter decides which scopes it needs:
  identity fields need ``user.info.basic``, profile fields
  (``bio_description``/``username``/``is_verified``) need ``user.info.profile``,
  and counts need ``user.info.stats``. The node's default field list spans all
  three, so the requirement is their union.
- **Upload vs direct post are separate grants.** ``video.upload`` drops a draft
  in the creator's inbox for them to publish by hand; ``video.publish`` posts
  straight to the profile. Neither implies the other, and the status endpoint
  accepts either (recorded in ``note`` — a requirement tuple is an AND, so the
  OR is documented rather than encoded).
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str, note: str = "") -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes, note=note)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # Display API — GET /v2/user/info/. The node's default `fields` spans
    # identity, profile and stats fields, each gated by its own scope.
    "get_authenticated_user_info": _s(
        "user.info.basic",
        "user.info.profile",
        "user.info.stats",
        note=(
            "user.info.basic covers open_id/union_id/avatar_url/display_name; "
            "user.info.profile covers bio_description/username/is_verified; "
            "user.info.stats covers the follower/following/likes/video counts."
        ),
    ),
    # Display API — POST /v2/video/list/ and /v2/video/query/.
    "list_user_public_videos": _s("video.list"),
    "query_video_metrics_by_id": _s("video.list"),
    # Content Posting API — inbox upload (creator publishes by hand).
    "upload_video_to_creator_inbox": _s("video.upload"),
    # Content Posting API — direct post to the profile.
    "query_creator_info": _s("video.publish"),
    "direct_post_video": _s("video.publish"),
    "direct_post_photo": _s("video.publish"),
    # POST /v2/post/publish/status/fetch/ accepts EITHER posting scope; the
    # tuple is an AND, so the alternative lives in the note.
    "check_video_publish_status": _s(
        "video.upload",
        note="video.publish also satisfies this endpoint.",
    ),
}

TIKTOK_SCOPES = ScopeRegistry(
    provider="tiktok",
    requirements=_REQUIREMENTS,
)
