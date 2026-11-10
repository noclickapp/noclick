"""Taplio v1 actions and scheduled polls, using the published API-key contract."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://api.taplio.com"
DRAFT_ID = r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$"
POST_ID = r"^(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|urn:li:[a-zA-Z]+:\d+|\d+)$"


class TaplioAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Taplio API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.taplio.com/settings",
            "x-credential-instructions": "Paste your per-user API key from Taplio settings. NoClick sends it as a Bearer token to api.taplio.com. Your own posts are read to check access.",
        })
    credential_type: Literal["taplio_api_key"] = Field("taplio_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Page(BaseModel):
    limit: int = Field(30, ge=1, le=100, description="Items per page; Taplio counts posts rather than individual comments when listing unfiltered comments.")
    cursor: Optional[str] = Field(None, description="Use meta.next_cursor from the previous response.")


class _Window(BaseModel):
    from_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", title="From date", description="Inclusive YYYY-MM-DD in UTC.")
    to_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", title="To date", description="Inclusive YYYY-MM-DD in UTC.")


class _DraftID(BaseModel):
    draft_id: str = Field(..., pattern=DRAFT_ID, title="Draft ID")


class _PostBody(BaseModel):
    content: Optional[str] = Field(None, max_length=3000, json_schema_extra={"ui:widget": "textarea"})
    media_ids: Optional[list[str]] = Field(None, description="Existing Taplio media IDs, replacing the draft's media when updating.")
    document_title: Optional[str] = Field(None, min_length=1, max_length=100, description="Title for a PDF attached in this call; cannot rename an existing attachment.")

    @field_validator("media_ids")
    @classmethod
    def media(cls, value):
        if value is not None and any(not item for item in value):
            raise ValueError("Media IDs must be nonempty")
        return value

    @model_validator(mode="after")
    def draft_body(self):
        if self.content is None and self.media_ids is None:
            raise ValueError("Provide content or media IDs")
        return self


class TaplioListPostsConfig(_Page, _Window):
    operation: Literal["list_posts"] = Field("list_posts", title='List Posts', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})
    status: Optional[Literal["scheduled", "sending", "sent"]] = None


class TaplioGetPostConfig(BaseModel):
    operation: Literal["get_post"] = Field("get_post", title='Get Post', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})
    post_id: str = Field(..., pattern=POST_ID, title="Post ID or LinkedIn URN")


class TaplioListPostDraftsConfig(_Page):
    operation: Literal["list_post_drafts"] = Field("list_post_drafts", title='List Post Drafts', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})


class TaplioCreatePostDraftConfig(_PostBody):
    operation: Literal["create_post_draft"] = Field("create_post_draft", title='Create Post Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})

    @model_validator(mode="after")
    def nonempty(self):
        if not self.content and not self.media_ids:
            raise ValueError("A new draft needs text or media")
        return self


class TaplioGetPostDraftConfig(_DraftID):
    operation: Literal["get_post_draft"] = Field("get_post_draft", title='Get Post Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})


class TaplioUpdatePostDraftConfig(_DraftID, _PostBody):
    operation: Literal["update_post_draft"] = Field("update_post_draft", title='Update Post Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})


class TaplioDeletePostDraftConfig(_DraftID):
    operation: Literal["delete_post_draft"] = Field("delete_post_draft", title='Discard Post Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})


class TaplioPublishPostDraftConfig(_DraftID):
    operation: Literal["publish_post_draft"] = Field("publish_post_draft", title='Publish Post Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})


class TaplioSchedulePostDraftConfig(_DraftID):
    operation: Literal["schedule_post_draft"] = Field("schedule_post_draft", title='Schedule Post Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})
    scheduled_for: str = Field(..., min_length=1, description="When to publish, using Taplio scheduled_for syntax, for example an ISO 8601 timestamp.")


class TaplioUnschedulePostDraftConfig(_DraftID):
    operation: Literal["unschedule_post_draft"] = Field("unschedule_post_draft", title='Unschedule Post Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})


class TaplioAttachMediaUrlConfig(_DraftID):
    operation: Literal["attach_media_url"] = Field("attach_media_url", title='Attach Media from URL', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})
    url: str = Field(..., pattern=r"^https://", description="Public HTTPS media URL. Taplio fetches and attaches this file.")
    document_title: Optional[str] = Field(None, min_length=1, max_length=100)


class TaplioListMediaConfig(BaseModel):
    operation: Literal["list_media"] = Field("list_media", title='List Uploaded Media', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})
    query: Optional[str] = Field(None, description="Filename substring")
    limit: int = Field(30, ge=1, le=100)


class TaplioListCommentsConfig(_Page):
    operation: Literal["list_comments"] = Field("list_comments", title='List Posted Comments', json_schema_extra={"ui:hidden": True, "x-category": 'Comments'})
    post_urn: Optional[str] = Field(None, min_length=1)


class TaplioCreateCommentDraftConfig(BaseModel):
    operation: Literal["create_comment_draft"] = Field("create_comment_draft", title='Create Comment Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Comments'})
    post_urn: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=1250, json_schema_extra={"ui:widget": "textarea"})
    comment_id: Optional[str] = Field(None, min_length=1, description="Full LinkedIn comment URN to reply to; bare comment IDs are rejected by Taplio.")


class TaplioGetCommentDraftConfig(_DraftID):
    operation: Literal["get_comment_draft"] = Field("get_comment_draft", title='Get Comment Draft / Delivery Status', json_schema_extra={"ui:hidden": True, "x-category": 'Comments'})


class TaplioUpdateCommentDraftConfig(_DraftID):
    operation: Literal["update_comment_draft"] = Field("update_comment_draft", title='Update Comment Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Comments'})
    content: str = Field(..., min_length=1, max_length=1250, json_schema_extra={"ui:widget": "textarea"})


class TaplioDeleteCommentDraftConfig(_DraftID):
    operation: Literal["delete_comment_draft"] = Field("delete_comment_draft", title='Discard Comment Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Comments'})


class TaplioCommitCommentDraftConfig(_DraftID):
    operation: Literal["commit_comment_draft"] = Field("commit_comment_draft", title='Queue Comment Draft', json_schema_extra={"ui:hidden": True, "x-category": 'Comments'})


class TaplioCancelCommentDraftConfig(_DraftID):
    operation: Literal["cancel_comment_draft"] = Field("cancel_comment_draft", title='Cancel Queued Comment', json_schema_extra={"ui:hidden": True, "x-category": 'Comments'})


class TaplioGetAnalyticsOverviewConfig(_Window):
    operation: Literal["get_analytics_overview"] = Field("get_analytics_overview", title='Get Analytics Overview', json_schema_extra={"ui:hidden": True, "x-category": 'Analytics'})
    granularity: Literal["day"] = "day"
    metrics: Optional[str] = Field(None, description="Comma-separated metrics, for example followers,impressions")


class TaplioGetPostAnalyticsConfig(_Page, _Window):
    operation: Literal["get_post_analytics"] = Field("get_post_analytics", title='Get Post Analytics', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})


class TaplioListEngagementFeedConfig(_Page):
    operation: Literal["list_engagement_feed"] = Field("list_engagement_feed", title='List Engagement Feed', json_schema_extra={"ui:hidden": True, "x-category": 'Engagement'})
    source: Literal["my_posts", "curated_feed", "for_you"] = "my_posts"
    feed: Optional[str] = Field(None, min_length=1, description="Curated feed name; only accepted with source=curated_feed.")

    @model_validator(mode="after")
    def feed_source(self):
        if self.feed is not None and self.source != "curated_feed":
            raise ValueError("A feed name requires source=curated_feed")
        return self


class TaplioLikePostConfig(BaseModel):
    operation: Literal["like_post"] = Field("like_post", title='Queue Like on Post or Comment', json_schema_extra={"ui:hidden": True, "x-category": 'Posts'})
    post_urn: str = Field(..., min_length=1, description="LinkedIn post or comment URN, or a supported post URL. The like is queued, not delivered synchronously.")


class TaplioOnNewPostConfig(PollTriggerConfigBase):
    operation: Literal["on_new_post"] = Field("on_new_post", title='On New Published Post', json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True})
    limit: int = Field(100, ge=1, le=100, description="Poll one page per tick. Schedule frequently enough that new activity fits in this page. For comments, this counts posts unless a post URN is set.")
    from_date: Optional[str] = Field(None, title="Created since", description="Only posts on or after this date, based on Taplio creation time (or LinkedIn publication time for external posts).")


class TaplioOnNewCommentConfig(PollTriggerConfigBase):
    operation: Literal["on_new_comment"] = Field("on_new_comment", title='On New Posted Comment', json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True})
    limit: int = Field(100, ge=1, le=100, description="Poll one page per tick. Schedule frequently enough that new activity fits in this page. For comments, this counts posts unless a post URN is set.")
    post_urn: Optional[str] = Field(None, min_length=1, description="Optionally watch only comments on this post.")


TaplioConfig = Annotated[Union[
    TaplioListPostsConfig,
    TaplioGetPostConfig,
    TaplioListPostDraftsConfig,
    TaplioCreatePostDraftConfig,
    TaplioGetPostDraftConfig,
    TaplioUpdatePostDraftConfig,
    TaplioDeletePostDraftConfig,
    TaplioPublishPostDraftConfig,
    TaplioSchedulePostDraftConfig,
    TaplioUnschedulePostDraftConfig,
    TaplioAttachMediaUrlConfig,
    TaplioListMediaConfig,
    TaplioListCommentsConfig,
    TaplioCreateCommentDraftConfig,
    TaplioGetCommentDraftConfig,
    TaplioUpdateCommentDraftConfig,
    TaplioDeleteCommentDraftConfig,
    TaplioCommitCommentDraftConfig,
    TaplioCancelCommentDraftConfig,
    TaplioGetAnalyticsOverviewConfig,
    TaplioGetPostAnalyticsConfig,
    TaplioListEngagementFeedConfig,
    TaplioLikePostConfig,
    TaplioOnNewPostConfig,
    TaplioOnNewCommentConfig
], Field(discriminator="operation")]


class TaplioNodeConfig(NodeConfig[TaplioConfig, TaplioAPIKeyCredential]):
    pass


# Each action maps to one published contract operation.
OPERATIONS = {
    'list_posts': ('GET', '/v1/posts', ()),
    'get_post': ('GET', '/v1/posts/{post_id}', ()),
    'list_post_drafts': ('GET', '/v1/posts/drafts', ()),
    'create_post_draft': ('POST', '/v1/posts/drafts', ('content', 'media_ids', 'document_title')),
    'get_post_draft': ('GET', '/v1/posts/drafts/{draft_id}', ()),
    'update_post_draft': ('PATCH', '/v1/posts/drafts/{draft_id}', ('content', 'media_ids', 'document_title')),
    'delete_post_draft': ('DELETE', '/v1/posts/drafts/{draft_id}', ()),
    'publish_post_draft': ('POST', '/v1/posts/drafts/{draft_id}/commit', ()),
    'schedule_post_draft': ('POST', '/v1/posts/drafts/{draft_id}/schedule', ('scheduled_for',)),
    'unschedule_post_draft': ('POST', '/v1/posts/drafts/{draft_id}/unschedule', ()),
    'attach_media_url': ('POST', '/v1/posts/drafts/{draft_id}/upload-url', ('url', 'document_title')),
    'list_media': ('GET', '/v1/posts/media', ()),
    'list_comments': ('GET', '/v1/comments', ()),
    'create_comment_draft': ('POST', '/v1/comments/drafts', ('post_urn', 'content', 'comment_id')),
    'get_comment_draft': ('GET', '/v1/comments/drafts/{draft_id}', ()),
    'update_comment_draft': ('PATCH', '/v1/comments/drafts/{draft_id}', ('content',)),
    'delete_comment_draft': ('DELETE', '/v1/comments/drafts/{draft_id}', ()),
    'commit_comment_draft': ('POST', '/v1/comments/drafts/{draft_id}/commit', ()),
    'cancel_comment_draft': ('POST', '/v1/comments/drafts/{draft_id}/cancel', ()),
    'get_analytics_overview': ('GET', '/v1/analytics/overview', ()),
    'get_post_analytics': ('GET', '/v1/analytics/posts', ()),
    'list_engagement_feed': ('GET', '/v1/engagement/feed', ()),
    'like_post': ('POST', '/v1/likes', ('post_urn',)),
}


class TaplioNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-taplio"
    connection_evidence = ConnectionEvidence(
        noun="your Taplio posts", operation="list_posts", label_keys=("content", "id"),
    )
    edit_examples = ["Create a LinkedIn post draft", "Schedule this Taplio draft", "Watch for new published posts", "Queue a reply to this comment"]

    @classmethod
    def get_config_model(cls):
        return TaplioNodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None):
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers,
                                            params=params, json=body)
        if not 200 <= response.status_code < 300:
            try:
                error = response.json().get("error", {})
                message = error.get("message") if isinstance(error, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
            except (ValueError, AttributeError):
                message = code = None
            detail = message or "Taplio request failed"
            if code:
                detail += f" ({code})"
            detail = detail.replace(api_key, "[redacted]")
            raise ValueError(f"Taplio HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            return {"deleted": True}
        data = response.json()
        if not isinstance(data, dict) or "error" in data:
            raise ValueError("Taplio returned an unexpected response")
        return data

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Taplio API key")
        config = self.config.config
        key = self.config.credentials.api_key
        name = config.operation
        if name in {"on_new_post", "on_new_comment"}:
            return await self._poll(key, config)
        method, path, body_fields = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("draft_id", "post_id"):
            if field in values:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        values = {({"from_date": "from", "to_date": "to"}.get(k, k)): v for k, v in values.items()}
        body = {k: values.pop(k) for k in body_fields if k in values}
        return await self._request(key, method, path,
                                   params=values if method == "GET" else None,
                                   body=body if body_fields else None)

    async def _poll(self, key, config):
        is_post = config.operation == "on_new_post"
        params = {"limit": config.limit}
        if is_post:
            params["status"] = "sent"
            if config.from_date is not None:
                params["from"] = config.from_date
        elif config.post_urn is not None:
            params["post_urn"] = config.post_urn
        page = await self._request(key, "GET", "/v1/posts" if is_post else "/v1/comments", params=params)
        rows = page.get("data")
        meta = page.get("meta")
        if not isinstance(rows, list) or not isinstance(meta, dict):
            raise ValueError("Taplio returned an invalid activity page")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("content"), str):
                raise ValueError("Taplio returned an invalid activity item")
            if is_post:
                if not isinstance(row.get("id"), str) or not row["id"]:
                    raise ValueError("Taplio post ID is missing")
            elif not all(isinstance(row.get(k), str) and row[k] for k in ("post_urn", "posted_at")):
                raise ValueError("Taplio comment identity is missing")
        # Use required fields so enrichment with an optional comment_urn never re-emits a comment.
        fresh = await self._filter_unseen(rows, lambda row: row["id"] if is_post else
            (row["post_urn"] + ":" + row["posted_at"]))
        return {"event": "new_post" if is_post else "new_comment", "data": fresh,
                "new_count": len(fresh), "meta": meta}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_post", "on_new_comment"}:
            return bool(output.get("new_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        event = output.get("event")
        if event not in {"new_post", "new_comment"}:
            return super().resolve_agent_event(output)
        rows = output.get("data")
        if not isinstance(rows, list) or not rows:
            return None
        noun = "published post" if event == "new_post" else "posted comment"
        lines = []
        for row in rows[:10]:
            if event == "new_post":
                context = f"post ID {row.get('id')}; {row.get('url') or ''}"
            else:
                context = f"post {row.get('post_urn')}; comment {row.get('comment_urn') or ''}; posted {row.get('posted_at')}"
            lines.append(f"- {context}\n  {row.get('content', '')[:1500]}")
        return {"text": f"Taplio: {len(rows)} new {noun}(s) from your connected account on LinkedIn:\n" + "\n".join(lines),
                "conversation_key": None}
