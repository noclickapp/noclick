"""Typefully v2 request payload models derived from its published 2.0.0 contract.

They keep platform-specific post fields and partial-update omission semantics
in this integration, without introducing shared schemas.
"""
from __future__ import annotations
from typing import Annotated, Any, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class XPost(_Payload):
    text: str = Field(..., max_length=50000, description='The text content of the post.')
    media_ids: list[str] = Field(None, max_length=20, description='Media IDs to attach to the post; obtain them via the media upload endpoint.')
    hide_link_preview: StrictBool | None = Field(None, description='Hide the link-preview card (the URL stays as plain text); when false the last URL gets a preview. Omit or send null to keep the current value (false on create).')
    quote_post_url: Annotated[str, Field(max_length=2048)] | None = Field(None, description="URL of the X post to quote in this post (equivalent to Typefully's 'convert to quote' action). Accepts x.com and twitter.com URLs containing a /status/<id> segment.")
    subscribers_only: StrictBool = Field(False, description='Visible only to paying Subscribers. Requires an X account approved for creator Subscriptions.')
    reply_settings: Literal['following', 'mentionedUsers', 'subscribers', 'verified'] | None = Field(None, description='Who can reply. Null (default) means everyone.')
    paid_partnership: StrictBool = Field(False, description='Whether this post should be labeled as a paid partnership.')
    made_with_ai: StrictBool = Field(False, description='Whether this post should be labeled as made with AI.')


class XSettings(_Payload):
    reply_to_url: Annotated[str, Field(max_length=2048)] | None = Field(None, description='URL of the X post to reply to. When provided, the first post in your thread will be posted as a reply.')
    community_id: Annotated[str, Field(max_length=255)] | None = Field(None, description='ID of the X community to post to. Find the ID in the community URL (e.g., x.com/i/communities/1493446837214187523). You must have permission to post to the community, otherwise publishing will fail.')
    share_with_followers: StrictBool | None = Field(None, description='When posting to a community, whether to also share the post to your timeline/followers. Defaults to true if not specified. Only has an effect when community_id is provided.')


class XPlatform(_Payload):
    enabled: StrictBool = Field(..., description='Required. Set true and include `posts` to publish to this platform; false (no `posts`) leaves it off.')
    posts: list[XPost] = Field(None, max_length=50, description='Posts for this platform. Required when `enabled` is true; omit when false.')
    settings: XSettings | None = Field(None, description='X-specific settings')

    @model_validator(mode="after")
    def enabled_posts(self):
        if self.enabled and not self.posts:
            raise ValueError("Enabled platforms need at least one post")
        return self


class LinkedInPost(_Payload):
    text: str = Field(..., max_length=50000, description='The text content of the post. You can tag companies with mention syntax: @[Company Name](urn:li:organization:123456).')
    media_ids: list[str] = Field(None, max_length=20, description='Media IDs to attach to the post; obtain them via the media upload endpoint.')
    hide_link_preview: StrictBool | None = Field(None, description='Hide the link-preview card (the URL stays as plain text); when false the last URL gets a preview. Omit or send null to keep the current value (false on create).')
    linkedin_reshare_target: Annotated[str, Field(max_length=2048)] | None = Field(None, description='Canonical URN or full LinkedIn post URL to reshare (repost). URLs are normalized to the canonical URN in storage and responses. Use values like urn:li:share:<id>, urn:li:ugcPost:<id>, or urn:li:groupPost:<id>.')


class LinkedInSettings(_Payload):
    first_comment: Annotated[str, Field(max_length=1250)] | None = Field(None, description='Posted as a comment once the post publishes; null or empty removes it.')


class LinkedInPlatform(_Payload):
    enabled: StrictBool = Field(..., description='Required. Set true and include `posts` to publish to this platform; false (no `posts`) leaves it off.')
    posts: list[LinkedInPost] = Field(None, max_length=50, description='Posts for this platform. Required when `enabled` is true; omit when false.')
    settings: LinkedInSettings | None = Field(None, description='LinkedIn-specific settings')

    @model_validator(mode="after")
    def enabled_posts(self):
        if self.enabled and not self.posts:
            raise ValueError("Enabled platforms need at least one post")
        return self


class MastodonPost(_Payload):
    text: str = Field(..., max_length=50000, description='The text content of the post.')
    media_ids: list[str] = Field(None, max_length=20, description='Media IDs to attach to the post; obtain them via the media upload endpoint.')
    hide_link_preview: StrictBool | None = Field(None, description='Hide the link-preview card (the URL stays as plain text); when false the last URL gets a preview. Omit or send null to keep the current value (false on create).')
    quote_post_url: Annotated[str, Field(max_length=2048)] | None = Field(None, description='Status URL on any instance to quote; your own server must support quotes and see it.')


class MastodonSettings(_Payload):
    pass


class MastodonPlatform(_Payload):
    enabled: StrictBool = Field(..., description='Required. Set true and include `posts` to publish to this platform; false (no `posts`) leaves it off.')
    posts: list[MastodonPost] = Field(None, max_length=50, description='Posts for this platform. Required when `enabled` is true; omit when false.')
    settings: MastodonSettings | None = Field(None, description='Mastodon-specific settings')

    @model_validator(mode="after")
    def enabled_posts(self):
        if self.enabled and not self.posts:
            raise ValueError("Enabled platforms need at least one post")
        return self


class ThreadsPost(_Payload):
    text: str = Field(..., max_length=50000, description='The text content of the post.')
    media_ids: list[str] = Field(None, max_length=20, description='Media IDs to attach to the post; obtain them via the media upload endpoint.')
    hide_link_preview: StrictBool | None = Field(None, description='Hide the link-preview card (the URL stays as plain text); when false the last URL gets a preview. Omit or send null to keep the current value (false on create).')
    quote_post_url: Annotated[str, Field(max_length=2048)] | None = Field(None, description='threads.net/threads.com post URL to quote: one of your own posts, or a recent post from a public profile once your Threads connection allows looking up public profiles.')


class ThreadsSettings(_Payload):
    pass


class ThreadsPlatform(_Payload):
    enabled: StrictBool = Field(..., description='Required. Set true and include `posts` to publish to this platform; false (no `posts`) leaves it off.')
    posts: list[ThreadsPost] = Field(None, max_length=50, description='Posts for this platform. Required when `enabled` is true; omit when false.')
    settings: ThreadsSettings | None = Field(None, description='Threads-specific settings')

    @model_validator(mode="after")
    def enabled_posts(self):
        if self.enabled and not self.posts:
            raise ValueError("Enabled platforms need at least one post")
        return self


class BlueskyPost(_Payload):
    text: str = Field(..., max_length=50000, description='The text content of the post.')
    media_ids: list[str] = Field(None, max_length=20, description='Media IDs to attach to the post; obtain them via the media upload endpoint.')
    hide_link_preview: StrictBool | None = Field(None, description='Hide the link-preview card (the URL stays as plain text); when false the last URL gets a preview. Omit or send null to keep the current value (false on create).')
    quote_post_url: Annotated[str, Field(max_length=2048)] | None = Field(None, description='bsky.app URL (/profile/<handle>/post/<rkey>) to quote, if its author allows quoting.')


class BlueskySettings(_Payload):
    pass


class BlueskyPlatform(_Payload):
    enabled: StrictBool = Field(..., description='Required. Set true and include `posts` to publish to this platform; false (no `posts`) leaves it off.')
    posts: list[BlueskyPost] = Field(None, max_length=50, description='Posts for this platform. Required when `enabled` is true; omit when false.')
    settings: BlueskySettings | None = Field(None, description='Bluesky-specific settings')

    @model_validator(mode="after")
    def enabled_posts(self):
        if self.enabled and not self.posts:
            raise ValueError("Enabled platforms need at least one post")
        return self


class SubstackPost(_Payload):
    text: str = Field(..., max_length=50000, description='The text content of the post.')
    media_ids: list[str] = Field(None, max_length=20, description='Media IDs to attach to the post; obtain them via the media upload endpoint.')
    hide_link_preview: StrictBool | None = Field(None, description='Hide the link-preview card (the URL stays as plain text); when false the last URL gets a preview. Omit or send null to keep the current value (false on create).')
    quote_post_url: Annotated[str, Field(max_length=2048)] | None = Field(None, description='Substack note (/note/c-<id>) or post (/p/<slug>) URL to restack.')


class SubstackSettings(_Payload):
    pass


class SubstackPlatform(_Payload):
    enabled: StrictBool = Field(..., description='Required. Set true and include `posts` to publish to this platform; false (no `posts`) leaves it off.')
    posts: list[SubstackPost] = Field(None, max_length=1, description='Single note for this platform. Required when `enabled` is true; omit when false.')
    settings: SubstackSettings | None = Field(None, description='Substack-specific settings')

    @model_validator(mode="after")
    def enabled_posts(self):
        if self.enabled and not self.posts:
            raise ValueError("Enabled platforms need at least one post")
        return self


class XArticlePlatform(_Payload):
    content_markdown: Annotated[str, Field(max_length=50000)] | None = Field(None, description='X Article Markdown. The first non-empty block must be `# Title`; remaining blocks are body. Supports paragraphs, blockquotes, lists, `#`/`##` headings, bold, italic, strikethrough, links, fenced code with an optional single-token language, and standalone `---`/`***` dividers (`GET` returns `---`). Code interiors stay literal. Escape delimiter-only prose such as `\\---`. Embeds must be alone on a line: `<typ:media media_id="..." />`, `<typ:x-post url="https://x.com/user/status/123" />`. Preserve comment-thread marker tags from `GET` when PATCHing. `GET` returns canonical Markdown, not submitted bytes. Required when creating an X Article draft; optional on PATCH when only changing `cover_media_id`.')
    cover_media_id: str | None = Field(None, description='Optional media ID for the X Article cover image. Must reference an uploaded, ready, account-owned static image. Omit on PATCH to keep the current cover; send null to remove it.')


class Platforms(_Payload):
    x: XPlatform | None = Field(None, description='X (Twitter) configuration')
    linkedin: LinkedInPlatform | None = Field(None, description='LinkedIn configuration')
    mastodon: MastodonPlatform | None = Field(None, description='Mastodon configuration')
    threads: ThreadsPlatform | None = Field(None, description='Threads configuration')
    bluesky: BlueskyPlatform | None = Field(None, description='Bluesky configuration')
    substack: SubstackPlatform | None = Field(None, description='Substack Notes configuration')
    x_article: XArticlePlatform | None = Field(None, description='X Article configuration. This platform is standalone: do not combine it with other platforms.')


class DraftCreateRequest(_Payload):
    platforms: Platforms = Field(..., description='Platform configurations for each social media platform')
    draft_title: Annotated[str, Field(max_length=512)] | None = Field(None, description='Draft title, for internal organization only; not posted to social media.')
    scratchpad_text: str | None = Field(None, description='Plain text scratchpad notes for the draft. Formatting is stripped.')
    tags: list[str] = Field(None, max_length=10, description='Tag slugs (not names). Tags must already exist in the social set - list them via /tags.')
    share: StrictBool = Field(False, description='Whether to generate a public share URL for this draft. When true, anyone with the URL can view the draft content.')
    publish_at: AwareDatetime | Literal['now', 'next-free-slot'] | None = Field(None, description='When to publish: "now" (immediate), "next-free-slot" (next available posting slot), or a future ISO 8601 datetime with timezone. Omit to save as a draft. Mutually exclusive with `plan_at`. "now" is asynchronous: the response returns `publish_state`="in_progress" while `status` stays "draft" and published URLs are null - success, not failure; poll GET /drafts/{id} until `publish_state`="finished", then read `status` and the published URLs.')
    plan_at: AwareDatetime | Literal['next-free-slot'] | None = Field(None, description='When to plan the draft. A planned draft is dated but inert: it shows on the queue and calendar at its date but never auto-publishes until confirmed by later setting `publish_at`. Accepts "next-free-slot" or a future ISO 8601 datetime with timezone ("now" is not valid). Mutually exclusive with `publish_at`. Omit to save as a plain draft.')

    @model_validator(mode="after")
    def scheduling(self):
        if self.publish_at is not None and self.plan_at is not None:
            raise ValueError("Use either publish_at or plan_at")
        return self


class DraftUpdateRequest(_Payload):
    platforms: Platforms | None = Field(None, description='Platform configurations. Only provided platforms will be updated; omitted platforms remain unchanged.')
    draft_title: Annotated[str, Field(max_length=512)] | None = Field(None, description='Draft title, for internal organization only; not posted to social media. Omit to keep unchanged.')
    scratchpad_text: str | None = Field(None, description='Plain text scratchpad notes for the draft. Formatting is stripped. Omit to keep unchanged.')
    tags: Annotated[list[str], Field(max_length=10)] | None = Field(None, description='Tag slugs (not names). Tags must already exist in the social set - list them via /tags. Omit to keep unchanged.')
    share: StrictBool | None = Field(None, description='Whether to generate a public share URL. Omit to keep unchanged.')
    publish_at: AwareDatetime | Literal['now', 'next-free-slot'] | None = Field(None, description='When to publish: "now" (immediate), "next-free-slot", or a future ISO 8601 datetime with timezone. On a planned draft, a datetime or "next-free-slot" confirms it into a real schedule (echo its `scheduled_date` to keep the date); "now" publishes it immediately. Explicit null returns it to plain draft status. Mutually exclusive with `plan_at`. Omit to keep unchanged. "now" is asynchronous: the response returns `publish_state`="in_progress" (success, not failure); poll GET /drafts/{id} until "finished".')
    plan_at: AwareDatetime | Literal['next-free-slot'] | None = Field(None, description='When to plan. A planned draft is dated but inert: on the queue and calendar but never auto-publishing until confirmed via `publish_at`. A future datetime with timezone or "next-free-slot" plans a plain draft, replans a planned one, or unschedules a scheduled one into a plan (requires publish access; "now" invalid). Explicit null returns a planned or scheduled draft to plain draft status. Mutually exclusive with `publish_at`. Omit to keep unchanged.')
    force_overwrite_comments: StrictBool = Field(False, description='Comment-thread anchor preservation toggle. When false (the default), submitting `posts[*].text` or X Article `content_markdown` whose `<typ:comment-thread>` markers don\'t match the draft\'s stored comment threads is rejected with `409 COMMENTS_MARKER_MISMATCH`; re-include the missing markers and retry. When true, missing markers are accepted: their comment threads are resolved server-side and their anchors stripped; submitted markers still validate normally. Only JSON `true`/`false` (not `"true"` strings).')

    @model_validator(mode="after")
    def scheduling(self):
        if self.publish_at is not None and self.plan_at is not None:
            raise ValueError("Use either publish_at or plan_at")
        return self


class MediaUploadRequest(_Payload):
    file_name: str = Field(..., max_length=255, pattern='^[a-zA-Z0-9_.()\\-]+\\.([jJ][pP][gG]|[jJ][pP][eE][gG]|[pP][nN][gG]|[wW][eE][bB][pP]|[gG][iI][fF]|[mM][pP]4|[mM][oO][vV]|[pP][dD][fF])$', description="Original filename with extension (e.g., 'image.jpg', 'video.mp4'). Used for MIME type detection and display. Allowed characters: letters, numbers, hyphens, underscores, periods, parentheses. Allowed extensions: .jpg, .jpeg, .png, .webp, .gif, .mp4, .mov, .pdf")
    alt_text: Annotated[str, Field(max_length=1000)] | None = Field(None, description='Accessibility description for the media, used as alt text when publishing. Can also be set later with PATCH /media/{media_id}. Platform-specific character limits are validated when the media is attached to a draft.')


class MediaUpdateRequest(_Payload):
    alt_text: Annotated[str, Field(max_length=1000)] | None = Field(None, description='Accessibility description for the media, used as alt text when publishing. Pass null to clear it. If omitted, the current value is kept.')


class TagCreateRequest(_Payload):
    name: str = Field(..., min_length=1, max_length=32, description='Display name for the tag. The slug will be auto-generated from this name.')


class QueueScheduleRuleSchema(_Payload):
    h: int = Field(..., ge=0, le=23, description='Hour in 24h clock (0-23)')
    m: int = Field(..., ge=0, le=59, description='Minute (0-59)')
    days: list[Literal['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']] = Field(..., min_length=1, description='Days of week this rule applies to')


class QueueScheduleUpdateRequest(_Payload):
    rules: list[QueueScheduleRuleSchema] = Field(..., description='New schedule rules (full replacement).')
