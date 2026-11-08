"""Extrovert Client API v2: one documented request per workflow operation.

Contract: https://api.goextrovert.com/client/v2/docs-json (version 1.0).
List operations return one page, including provider pagination, without silently
following links. Writes never retry: an interrupted send may have taken effect.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.goextrovert.com"


def _uuid(value: str) -> str:
    return str(UUID(value))


Identifier = Annotated[
    str, AfterValidator(_uuid), Field(json_schema_extra={"format": "uuid"})
]


class ExtrovertApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Extrovert API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.goextrovert.com/",
            "x-credential-instructions": "Paste your Extrovert API key. NoClick sends it in the X-API-Key header to the Extrovert Client API.",
        },
    )
    credential_type: Literal["extrovert_api_key"] = Field(
        "extrovert_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        min_length=1,
        repr=False,
        description="Your Extrovert API key, without a header name or prefix.",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste a nonempty API key without whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListTeamMembers(_Operation):
    operation: Literal["list_team_members"] = Field(
        "list_team_members",
        title="List Team Members",
        description="Returns all users visible to the current user inside their selected team. Optionally narrow the result by `registrationType` — e.g. to show only invited members or only managed accounts.",
        json_schema_extra={"ui:hidden": True},
    )
    registration_type: Literal[
        "NEW_USER_SIGNUP", "NEW_USER_WORKSPACE_INVITE_CONFIRM", "SUB_USER"
    ] | None = Field(
        None,
        title="Registration Type",
        description="Optional filter by how the user entered the system. `NEW_USER_SIGNUP` — self-signup; `NEW_USER_WORKSPACE_INVITE_CONFIRM` — accepted a team invite; `SUB_USER` — managed account created by another user.",
    )


class ListCampaigns(_Operation):
    operation: Literal["list_campaigns"] = Field(
        "list_campaigns",
        title="List Campaigns",
        description="Returns all campaigns visible to the current user (both types: `TARGET_USER` and `KEYWORD` — user-facing 'Prospects campaign' and 'Topic campaign' respectively).",
        json_schema_extra={"ui:hidden": True},
    )


class GetCampaign(_Operation):
    operation: Literal["get_campaign"] = Field(
        "get_campaign",
        title="Get Campaign",
        description="Loads full details of a single campaign, including the linked Voice, the whole `commenting` policy, and the full outreach settings (warm up, connection requests, direct messages).",
        json_schema_extra={"ui:hidden": True},
    )
    campaign_id: str = Field(
        ..., title="Campaign Id", description="id", min_length=1, max_length=256
    )


class CreateCampaign(_Operation):
    operation: Literal["create_campaign"] = Field(
        "create_campaign",
        title="Create Campaign",
        description="Creates a new campaign. The campaign owner must already have a Voice.\n\nTwo types (backend values `TARGET_USER` and `KEYWORD` correspond to user-facing 'Prospects campaign' and 'Topic campaign' respectively):\n- `TARGET_USER`: engages with a specific list of LinkedIn profiles.\n- `KEYWORD`: discovers posts by topic bindings.\n\nThe engagement-automation fields `skipTeammatesLeads` and `outreach` apply to `TARGET_USER` (Prospects) campaigns only. For `KEYWORD` (Topic) campaigns they do not apply — omit them (or leave them off).",
        json_schema_extra={"ui:hidden": True},
    )
    owner_id: Identifier = Field(
        ...,
        title="Owner Id",
        description="User ID of the campaign owner. Creating for anyone other than the caller requires the workspace permission to create campaigns for another owner (ADMIN/MANAGER). When creating for a non-managed owner, the acting user is also added as an explicit grantee.",
    )
    name: str = Field(
        ..., title="Name", description="Display name for the campaign.", min_length=1
    )
    type: Literal["TARGET_USER", "KEYWORD"] = Field(
        ...,
        title="Type",
        description="`TARGET_USER` = Prospects campaign; `KEYWORD` = Topic campaign. Creating a Topic campaign requires `CAN_USE_TOPIC_CAMPAIGNS`.",
    )
    voice_id: Identifier = Field(
        ...,
        title="Voice Id",
        description="Voice ID owned by `ownerId`. A foreign or missing Voice is rejected.",
    )
    skip_teammates_leads: bool = Field(
        ...,
        title="Skip Teammates Leads",
        description="If `true`, skip prospects that are already in teammates' campaigns in the same team — avoids double outreach to the same person. Applies to `TARGET_USER` (Prospects) campaigns only (recommended `true` there); for `KEYWORD` (Topic) campaigns it does not apply — leave it `false`.",
    )


class UpdateCampaign(_Operation):
    operation: Literal["update_campaign"] = Field(
        "update_campaign",
        title="Update Campaign",
        description="Updates the editable fields of an existing campaign. `id`, `name`, `voiceId` and `skipTeammatesLeads` are required (full replace). Backend types `TARGET_USER` and `KEYWORD` correspond to user-facing 'Prospects campaign' and 'Topic campaign' respectively.\n\n**`KEYWORD` campaigns: only `name` and the comment policy are editable.** The backend rejects with a 409 state-conflict whenever `skipTeammatesLeads`, an explicitly passed `outreach.connectionRequests.enabled`, or an explicitly passed `outreach.directMessages.enabled` differs from the current value. Omitting the optional `outreach` and `commenting` objects means \"no change\" and is always safe.",
        json_schema_extra={"ui:hidden": True},
    )
    campaign_id: Identifier = Field(
        ..., title="Campaign Id", description="Campaign id to update."
    )
    name: str = Field(
        ..., title="Name", description="Updated display name.", min_length=1
    )
    voice_id: Identifier = Field(
        ...,
        title="Voice Id",
        description="Voice id the campaign should use after the update. Always required: detaching a Voice is intentionally not possible through this API (internally an omitted field would mean 'remove'), so pass the current `voice.id` to keep it or another valid id to switch.",
    )
    skip_teammates_leads: bool = Field(
        ...,
        title="Skip Teammates Leads",
        description="Prospects campaigns: skip profiles already present in teammates' campaigns. Enabling is rejected if duplicate prospects already exist; resolve those duplicates first. Keep the stored value for Topic campaigns.",
    )


class StartCampaign(_Operation):
    operation: Literal["start_campaign"] = Field(
        "start_campaign",
        title="Start Campaign",
        description="Activates a campaign (sets `isActive` to `true`): the post feed resumes updating, DM drafts are suggested again, and connection requests start being sent per the campaign's settings. The campaign must be properly configured first (a Voice, and either a ProspectList for `TARGET_USER` — user-facing 'Prospects campaign' — or Monitored Topics bound to the campaign for `KEYWORD` — user-facing 'Topic campaign').",
        json_schema_extra={"ui:hidden": True},
    )
    campaign_id: str = Field(
        ..., title="Campaign Id", description="id", min_length=1, max_length=256
    )


class StopCampaign(_Operation):
    operation: Literal["stop_campaign"] = Field(
        "stop_campaign",
        title="Stop Campaign",
        description="Pauses a campaign (sets `isActive` to `false`): the post feed stops updating, no DM drafts are suggested, and no connection requests are sent until the campaign is started again. Existing posts in the approval queue are preserved.",
        json_schema_extra={"ui:hidden": True},
    )
    campaign_id: str = Field(
        ..., title="Campaign Id", description="id", min_length=1, max_length=256
    )


class CreateProspectList(_Operation):
    operation: Literal["create_prospect_list"] = Field(
        "create_prospect_list",
        title="Create Prospect List",
        description="Creates a new prospect list inside the given campaign and seeds it with the provided LinkedIn profile URLs. The backend validates URLs and may reject some as invalid, duplicates, or out-of-limit. The response describes which URLs were submitted, rejected, or already existed elsewhere. Profile existence is verified asynchronously after this call: a URL can be accepted into `submittedUrls` and still be dropped later — check Get Prospect List for the final prospect count before reporting how many were actually added.",
        json_schema_extra={"ui:hidden": True},
    )
    list_name: str = Field(
        ..., title="List Name", description="Human-readable list name.", min_length=1
    )
    campaign_id: Identifier = Field(
        ...,
        title="Campaign Id",
        description="Use a non-deleted Prospects campaign as the destination. Capacity is normally workspace-wide, but a trial pool with a non-null `perOwnerCeiling` is measured for this campaign owner. An active plan is required; a new list also needs a free prospect-list slot in that campaign.",
    )
    user_urls: list[Annotated[str, Field(min_length=1)]] = Field(
        ...,
        title="User Urls",
        description="LinkedIn profile URLs to seed the list with.",
        max_length=1000,
        min_length=1,
    )
    move_own_duplicated: bool = Field(
        ...,
        title="Move Own Duplicated",
        description="For an active duplicate owned by the destination campaign owner, `true` moves the existing prospect record into this list and `false` skips it into `existedUrlsMap`. Same-list duplicates are skipped silently; deleted same-owner records are reactivated. Teammate duplicates are searched and skipped only when the destination campaign has `skipTeammatesLeads` enabled; this is not global team-wide deduplication.",
    )
    should_be_deleted_if_inactive: bool = Field(
        ...,
        title="Should Be Deleted If Inactive",
        description="If `true`, auto-remove prospects who have no posts on LinkedIn within the last 30 days (checked once, when the backend first pulls their posts). If `false`, keep them regardless of recent posting activity. Useful for pruning low-signal prospects on create.",
    )


class GetProspectList(_Operation):
    operation: Literal["get_prospect_list"] = Field(
        "get_prospect_list",
        title="Get Prospect List",
        description="Loads a single prospect list by id, including counters and the parent campaign id.",
        json_schema_extra={"ui:hidden": True},
    )
    list_id: str = Field(
        ..., title="List Id", description="id", min_length=1, max_length=256
    )


class AddProspectsToList(_Operation):
    operation: Literal["add_prospects_to_list"] = Field(
        "add_prospects_to_list",
        title="Add Prospects To List",
        description="Adds LinkedIn profile URLs to an existing prospect list. Same validation and duplicate rules as create-list. The response describes which URLs were accepted, rejected, or skipped as duplicates.",
        json_schema_extra={"ui:hidden": True},
    )
    list_id: Identifier = Field(
        ..., title="List Id", description="Prospect list id to add URLs to."
    )
    user_urls: list[Annotated[str, Field(min_length=1)]] = Field(
        ...,
        title="User Urls",
        description="LinkedIn profile URLs to add.",
        max_length=1000,
        min_length=1,
    )
    move_own_duplicated: bool = Field(
        ...,
        title="Move Own Duplicated",
        description="For an active duplicate owned by the destination campaign owner, `true` moves the existing prospect record into this list and `false` skips it into `existedUrlsMap`. Same-list duplicates are skipped silently; deleted same-owner records are reactivated. Teammate duplicates are searched and skipped only when the destination campaign has `skipTeammatesLeads` enabled; this is not global team-wide deduplication.",
    )
    should_be_deleted_if_inactive: bool = Field(
        ...,
        title="Should Be Deleted If Inactive",
        description="If `true`, auto-remove prospects who have no posts on LinkedIn within the last 30 days (checked once, when the backend first pulls their posts). If `false`, keep them regardless of recent posting activity.",
    )


class ListProspects(_Operation):
    operation: Literal["list_prospects"] = Field(
        "list_prospects",
        title="List Prospects",
        description="Returns visible prospects with their campaign/list bindings and optional pagination information. Use `listId` to scope to a single list, or pass broader filter arrays for campaign-wide prospect management. This endpoint returns existing prospects only — it does not add them. To add new LinkedIn profiles, add their URLs to a prospect list (`create-list` or `add-users-to-list`).",
        json_schema_extra={"ui:hidden": True},
    )
    list_id: Identifier | None = Field(
        None,
        title="List Id",
        description="Optional single-list shortcut. When present, it replaces `listsIds` with `[listId]`; it does not override `campaignsIds`, `search`, importance, frequency, or touch-point filters.",
    )
    campaigns_ids: list[Identifier] | None = Field(
        None,
        title="Campaigns Ids",
        description="Campaign IDs to filter within the accessible Prospects scope. Omit or pass `[]` for no campaign restriction; non-empty campaign and list filters intersect with the other active filters.",
        max_length=1000,
    )
    is_important: bool | None = Field(
        None,
        title="Is Important",
        description="Optional filter to only show important or non-important prospects.",
    )
    post_frequency: Literal[
        "MORE_THAN_TWICE_PER_WEEK",
        "ONE_TO_TWO_TIMES_PER_WEEK",
        "ONE_TO_THREE_TIMES_PER_MONTH",
        "LESS_THAN_ONCE_PER_MONTH",
    ] | None = Field(
        None,
        title="Post Frequency",
        description="Filter the stored direct-post weekly frequency estimate: `MORE_THAN_TWICE_PER_WEEK` >2; `ONE_TO_TWO_TIMES_PER_WEEK` 1–2 inclusive; `ONE_TO_THREE_TIMES_PER_MONTH` 0.25–0.99 inclusive; `LESS_THAN_ONCE_PER_MONTH` <0.25. This is based on fetched activity, not a live or calendar-month LinkedIn count.",
    )
    lists_ids: list[Identifier] | None = Field(
        None,
        title="Lists Ids",
        description="List IDs to filter by; omit or pass `[]` for no list restriction. If `listId` is supplied, it replaces this array with `[listId]`, rather than intersecting with it. Other active filters still apply.",
        max_length=1000,
    )
    sort_by: Literal[
        "prospectName",
        "campaignName",
        "postFrequency",
        "totalComments",
        "lastComment",
        "lastPostCheck",
    ] | None = Field(
        None,
        title="Sort By",
        description="Sort field: `prospectName` = stored LinkedIn full name; `campaignName` = campaign name; `postFrequency` = direct weekly post frequency; `totalComments` = published direct comments only; `lastComment` = stored direct comment timestamp (may include `POSTING`); `lastPostCheck` = last successful post-fetch finish. Omit for name ascending.",
    )
    sort_order: Literal["ASC", "DESC"] | None = Field(
        None,
        title="Sort Order",
        description="`ASC` sorts the chosen field ascending; `DESC` sorts it descending. If omitted, `lastComment` and `lastPostCheck` default to `DESC` and other explicit fields to `ASC`. If `sortBy` is omitted, the backend uses name `ASC` even if `sortOrder` is supplied.",
    )
    search: str | None = Field(
        None,
        title="Search",
        description="Case-insensitive stored LinkedIn full-name search after whitespace normalization; `%` and `_` remain SQL LIKE wildcards. Does not search headline, company or profile URL. An empty normalized term adds no search restriction. A non-empty term currently replaces the default successful-enrichment predicate.",
    )
    number_of_touch_points: list[
        Literal[
            "NOT_COMMENTED",
            "COMMENTED_1_TIME",
            "COMMENTED_2_TIMES",
            "COMMENTED_3_TIMES",
            "COMMENTED_4_TIMES",
            "COMMENTED_5_TIMES",
            "COMMENTED_6_AND_MORE_TIMES",
        ]
    ] | None = Field(
        None,
        title="Number Of Touch Points",
        description="OR-filter on published or already `POSTING` direct-plus-indirect comments, not likes, DMs or connection requests. Omitting it or passing `[]` disables this filter. `COMMENTED_1_TIME` through `COMMENTED_5_TIMES` mean exactly 1 through 5; `COMMENTED_6_AND_MORE_TIMES` means 6 or more.",
    )
    limit: int | None = Field(
        None,
        title="Limit",
        description="Optional positive integer page size, at most 1000; omitted uses the backend default of 5. This is pagination, not a total-results cap. Pass it explicitly and use the returned pagination to read further pages.",
        le=1000,
        gt=0,
    )
    offset: int | None = Field(
        None,
        title="Offset",
        description="Optional zero-based offset in the same filtered result; omitted starts at 0. Keep the same filters and ordering when advancing pages. The public maximum is 2147483647.",
        ge=0,
        le=2147483647,
    )


class GetProspect(_Operation):
    operation: Literal["get_prospect"] = Field(
        "get_prospect",
        title="Get Prospect",
        description="Loads one prospect by id with the current campaign/list bindings, flags, connection data, and lightweight statistics.",
        json_schema_extra={"ui:hidden": True},
    )
    prospect_id: str = Field(
        ..., title="Prospect Id", description="id", min_length=1, max_length=256
    )


class ReplaceProspectNotes(_Operation):
    operation: Literal["replace_prospect_notes"] = Field(
        "replace_prospect_notes",
        title="Replace Prospect Notes",
        description="Replaces the relationship note on a real LEAD prospect. Empty text clears it. Existing campaign permissions apply; drafts and automation state are unchanged. Notes add context for comment and DM generation. Generation already receives relevant post and message-history context, so repeating it in Notes is usually unnecessary. Focus on additional relationship context.",
        json_schema_extra={"ui:hidden": True},
    )
    prospect_id: str = Field(
        ..., title="Prospect Id", description="id", min_length=1, max_length=256
    )
    notes: str = Field(
        ...,
        title="Notes",
        description="Exact manual note text; empty clears. Maximum 2000 characters.",
        max_length=2000,
    )


class MarkProspectImportant(_Operation):
    operation: Literal["mark_prospect_important"] = Field(
        "mark_prospect_important",
        title="Mark Prospect Important",
        description="Single-prospect operation: updates the important flag for one prospect.",
        json_schema_extra={"ui:hidden": True},
    )
    prospect_id: Identifier = Field(
        ..., title="Prospect Id", description="Prospect id to update."
    )
    is_important: bool = Field(
        ...,
        title="Is Important",
        description="Whether the prospect should be marked as important.",
    )


class ListComments(_Operation):
    operation: Literal["list_comments"] = Field(
        "list_comments",
        title="List Comments",
        description="Lists one campaign's comment feed for an owner and review state. Results include the post, author, effective prospect context, current draft, state, and only actions valid now. `plannedAt` fills only when the campaign spaces approved comments with a posting interval — null means posting starts right after approval. This action does not change feed state. After a mutation — approving or skipping a comment — restart paging from `offset = 0`, because a page taken at a stale offset can skip or repeat records; this matters most in `Need approval`, which is re-ranked on every request, while the other views are ordered by lifecycle transition time and do not reorder.",
        json_schema_extra={"ui:hidden": True},
    )
    owner_id: Identifier = Field(
        ...,
        title="Owner Id",
        description="LinkedIn account owner whose campaign feed is being read. Often a managed account rather than the authenticated user — use List Team Members first and pick the owner whose LinkedIn profile runs the campaign.",
    )
    campaign_id: Identifier = Field(
        ...,
        title="Campaign Id",
        description="Campaign that scopes this feed. Aggregated cross-campaign feed is not part of this action.",
    )
    view: Literal["Need approval", "Pending", "Error", "Posted", "Skipped"] = Field(
        ...,
        title="View",
        description="Feed view, not an exact item-state filter. Need approval may include manual generation; Pending includes accepted generation or posting. Inspect each item’s state and `allowedActions`.",
    )
    prospect_list_id: Identifier | None = Field(
        None,
        title="Prospect List Id",
        description="Optional Prospect List filter. Cannot be combined with keywordId.",
    )
    keyword_id: Identifier | None = Field(
        None,
        title="Keyword Id",
        description="Optional Keyword filter. Cannot be combined with prospectListId.",
    )
    limit: int = Field(
        10,
        title="Limit",
        description="Number of records requested for this page.",
        ge=1,
        le=50,
    )
    offset: int = Field(
        0,
        title="Offset",
        description="Offset from the start of the filtered result set.",
        ge=0,
        le=2147483647,
    )


class GetComment(_Operation):
    operation: Literal["get_comment"] = Field(
        "get_comment",
        title="Get Comment",
        description="Returns the current owner-global comment by postId and ownerId across every state. The read is non-destructive and is the recovery check after an ambiguous write. `plannedAt` fills only when the campaign spaces approved comments with a posting interval — null means posting starts right after approval.",
        json_schema_extra={"ui:hidden": True},
    )
    post_id: Identifier = Field(..., title="Post Id", description="Post to read.")
    owner_id: Identifier = Field(
        ...,
        title="Owner Id",
        description="LinkedIn account owner whose comment state is returned.",
    )


class SetCommentDraft(_Operation):
    operation: Literal["set_comment_draft"] = Field(
        "set_comment_draft",
        title="Set Comment Draft",
        description="Sets the exact comment text for later review and approval. It creates an ordinary draft when none exists and never calls Extrovert generation. If the text includes the post author's full LinkedIn name or a leading part of it, Extrovert automatically tags the author once when publishing, preferring the most complete matching name. Match a literal leading part of the LinkedIn name, preserving all leading emoji and the exact spelling. A matching name must contain at least two letters; emoji-only prefixes are skipped. It does not post the comment. The comment identity is postId + ownerId and the change is owner-global: it also applies to sibling campaign activities of the same owner, even when the feed context came from one campaign.",
        json_schema_extra={"ui:hidden": True},
    )
    post_id: Identifier = Field(
        ..., title="Post Id", description="LinkedIn post identity inside Extrovert."
    )
    owner_id: Identifier = Field(
        ...,
        title="Owner Id",
        description="LinkedIn account owner whose comment is addressed. Often a managed account rather than the authenticated user — use List Team Members first and pick the owner whose LinkedIn profile runs the campaign.",
    )
    text: str = Field(
        ...,
        title="Text",
        description="Replacement draft text; surrounding whitespace is trimmed. Empty text cannot clear it. This does not generate or post.",
        min_length=1,
        max_length=1250,
    )


class ApproveComment(_Operation):
    operation: Literal["approve_comment"] = Field(
        "approve_comment",
        title="Approve Comment",
        description="Approves the current owner-global comment/reaction and queues the consequential LinkedIn action. Success means the command was accepted for the existing Pending/publication lifecycle, not that the comment is already live. Use Get comment when current state is needed. The comment identity is postId + ownerId and the change is owner-global: it also applies to sibling campaign activities of the same owner, even when the feed context came from one campaign.",
        json_schema_extra={"ui:hidden": True},
    )
    post_id: Identifier = Field(
        ..., title="Post Id", description="LinkedIn post identity inside Extrovert."
    )
    owner_id: Identifier = Field(
        ...,
        title="Owner Id",
        description="LinkedIn account owner whose comment is addressed. Often a managed account rather than the authenticated user — use List Team Members first and pick the owner whose LinkedIn profile runs the campaign.",
    )


class SkipComment(_Operation):
    operation: Literal["skip_comment"] = Field(
        "skip_comment",
        title="Skip Comment",
        description="Moves the owner-global comment out of the active review flow without posting a comment or reaction. Use unskip to restore a Skipped comment to review. The comment identity is postId + ownerId and the change is owner-global: it also applies to sibling campaign activities of the same owner, even when the feed context came from one campaign.",
        json_schema_extra={"ui:hidden": True},
    )
    post_id: Identifier = Field(
        ..., title="Post Id", description="LinkedIn post identity inside Extrovert."
    )
    owner_id: Identifier = Field(
        ...,
        title="Owner Id",
        description="LinkedIn account owner whose comment is addressed. Often a managed account rather than the authenticated user — use List Team Members first and pick the owner whose LinkedIn profile runs the campaign.",
    )


class ListConversations(_Operation):
    operation: Literal["list_conversations"] = Field(
        "list_conversations",
        title="List Conversations",
        description="Lists an owner's LinkedIn conversations in the required inbox view: needs-reply, for-review (For Review), auto, unread, all, snoozed or ended. It returns preview, unread count, active workflow state, and valid next actions without marking anything read.",
        json_schema_extra={"ui:hidden": True},
    )
    owner_id: Identifier = Field(
        ...,
        title="Owner Id",
        description="LinkedIn account owner whose inbox is being read. Often a managed account rather than the authenticated user — use List Team Members first and pick the owner whose LinkedIn profile holds the conversations.",
    )
    view: Literal[
        "unread", "all", "needs-reply", "for-review", "auto", "snoozed", "ended"
    ] = Field(
        ...,
        title="View",
        description="Required lowercase inbox view. for-review is the For Review tab. Suggested is not accepted.",
    )
    campaign_id: Identifier | None = Field(
        None,
        title="Campaign Id",
        description="Optional campaign filter. When omitted, the list covers all campaigns of the owner that the caller can access — never conversations outside those campaigns.",
    )
    prospect_list_id: Identifier | None = Field(
        None, title="Prospect List Id", description="Optional Prospect List filter."
    )
    search: str | None = Field(
        None,
        title="Search",
        description="Case-insensitive LinkedIn display-name search, not message text. SQL LIKE wildcards `%` and `_` remain active. Omit for no search; null and blank text are invalid.",
        min_length=1,
    )
    limit: int = Field(
        20,
        title="Limit",
        description="Number of records requested for this page.",
        ge=1,
        le=50,
    )
    offset: int = Field(
        0,
        title="Offset",
        description="Offset from the start of the filtered result set.",
        ge=0,
        le=2147483647,
    )


class GetConversation(_Operation):
    operation: Literal["get_conversation"] = Field(
        "get_conversation",
        title="Get Conversation",
        description="Returns one LinkedIn conversation, its unique active reply, and a bounded delivered-message page. Reading does not clear unread state unless markAsRead is true. Use offset 0 for the latest page and increase it to load older messages.",
        json_schema_extra={"ui:hidden": True},
    )
    connection_id: Identifier = Field(
        ...,
        title="Connection Id",
        description="Conversation (connection) ID the action addresses.",
    )
    mark_as_read: bool = Field(
        False,
        title="Mark As Read",
        description="When true, request that Extrovert and LinkedIn mark the conversation read. Provider synchronization may finish after this response.",
    )
    message_limit: int = Field(
        30,
        title="Message Limit",
        description="Number of delivered history messages requested for this page.",
        ge=1,
        le=30,
    )
    message_offset: int = Field(
        0,
        title="Message Offset",
        description="Offset from the newest delivered message. 0 returns the latest page; larger offsets load older messages.",
        ge=0,
        le=2147483647,
    )


class PrepareReply(_Operation):
    operation: Literal["prepare_reply"] = Field(
        "prepare_reply",
        title="Prepare Reply",
        description='Prepares one reviewable reply for a conversation from the exact supplied text, without Extrovert generation. It returns the exact dmId required for Send reply and never sends in the same call. Text that repeats a message the owner sent in this conversation in the last 24 hours (ignoring extra whitespace) is rejected with a conflict whose message starts with "Duplicate reply:", and nothing is prepared.',
        json_schema_extra={"ui:hidden": True},
    )
    connection_id: Identifier = Field(
        ...,
        title="Connection Id",
        description="Conversation (connection) ID the action addresses.",
    )
    text: str = Field(
        ...,
        title="Text",
        description="Reply text to prepare, trimmed to 1–1250 characters. A queued suggestion may be promoted; an existing reviewable reply must be edited instead.",
        min_length=1,
        max_length=1250,
    )


class EditReply(_Operation):
    operation: Literal["edit_reply"] = Field(
        "edit_reply",
        title="Edit Reply",
        description="Sets the exact effective text of an existing reviewable reply. It does not send the message.",
        json_schema_extra={"ui:hidden": True},
    )
    dm_id: Identifier = Field(
        ...,
        title="Dm Id",
        description="Exact reply ID obtained from Prepare reply or Get conversation.",
    )
    text: str = Field(
        ...,
        title="Text",
        description="Replacement reply text, trimmed to 1–1250 characters. Empty text cannot clear a reply; this call does not send.",
        min_length=1,
        max_length=1250,
    )


class SendReply(_Operation):
    operation: Literal["send_reply"] = Field(
        "send_reply",
        title="Send Reply",
        description='Sends the exact prepared dmId to the LinkedIn prospect. Queued (the default) accepts the reply for the owner\'s normal scheduler interval and returns its process ID, not provider confirmation. Immediate waits for explicit provider acceptance, not a read receipt. An uncertain immediate outcome may already have sent the reply. History changed leaves the stale reply unsent and refreshes the conversation. A reply whose text repeats a message the owner sent in this conversation in the last 24 hours (ignoring extra whitespace) is never sent: the call fails with a conflict whose message starts with "Duplicate reply:", or a queued send ends as History changed with error code duplicate-reply.',
        json_schema_extra={"ui:hidden": True},
    )
    dm_id: Identifier = Field(
        ...,
        title="Dm Id",
        description="Exact reply ID obtained from Prepare reply or Get conversation.",
    )
    mode: Literal["queued", "immediate"] = Field(
        "queued",
        title="Mode",
        description="Queued (default): Extrovert schedules the send within the owner's interval, daily limits and working hours. Immediate: sends now and waits for LinkedIn to accept it.",
    )


class SnoozeConversation(_Operation):
    operation: Literal["snooze_conversation"] = Field(
        "snooze_conversation",
        title="Snooze Conversation",
        description="Postpones a conversation until the start of an exact calendar day in the owner's timezone. Until then it is Snoozed: Extrovert recommends and sends nothing in it, and a current attention reason is cleared. Works whether or not the conversation has a recommendation. Does not send or generate a message.",
        json_schema_extra={"ui:hidden": True},
    )
    connection_id: Identifier = Field(
        ...,
        title="Connection Id",
        description="Conversation (connection) ID the action addresses.",
    )
    until_date: date = Field(
        ...,
        title="Until Date",
        description="Calendar day the conversation returns on, YYYY-MM-DD, in the owner's timezone.",
    )


Operation = Annotated[
    Union[
        ListTeamMembers,
        ListCampaigns,
        GetCampaign,
        CreateCampaign,
        UpdateCampaign,
        StartCampaign,
        StopCampaign,
        CreateProspectList,
        GetProspectList,
        AddProspectsToList,
        ListProspects,
        GetProspect,
        ReplaceProspectNotes,
        MarkProspectImportant,
        ListComments,
        GetComment,
        SetCommentDraft,
        ApproveComment,
        SkipComment,
        ListConversations,
        GetConversation,
        PrepareReply,
        EditReply,
        SendReply,
        SnoozeConversation,
    ],
    Field(discriminator="operation"),
]


class ExtrovertNodeConfig(NodeConfig[Operation, ExtrovertApiKeyCredential]):
    pass


ROUTES = {
    "list_team_members": {
        "method": "GET",
        "path": "/client/v2/user/team-members",
        "path_fields": {},
        "query": {"registrationType": "registration_type"},
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "list_campaigns": {
        "method": "GET",
        "path": "/client/v2/campaign",
        "path_fields": {},
        "query": {},
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "get_campaign": {
        "method": "GET",
        "path": "/client/v2/campaign/{id}",
        "path_fields": {"id": "campaign_id"},
        "query": {},
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "create_campaign": {
        "method": "POST",
        "path": "/client/v2/campaign",
        "path_fields": {},
        "query": {},
        "body": {
            "ownerId": "owner_id",
            "name": "name",
            "type": "type",
            "voiceId": "voice_id",
            "skipTeammatesLeads": "skip_teammates_leads",
        },
        "has_body": True,
        "success": [201],
    },
    "update_campaign": {
        "method": "PATCH",
        "path": "/client/v2/campaign/{id}",
        "path_fields": {"id": "campaign_id"},
        "query": {},
        "body": {
            "id": "campaign_id",
            "name": "name",
            "voiceId": "voice_id",
            "skipTeammatesLeads": "skip_teammates_leads",
        },
        "has_body": True,
        "success": [200],
    },
    "start_campaign": {
        "method": "POST",
        "path": "/client/v2/campaign/{id}/start",
        "path_fields": {"id": "campaign_id"},
        "query": {},
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "stop_campaign": {
        "method": "POST",
        "path": "/client/v2/campaign/{id}/stop",
        "path_fields": {"id": "campaign_id"},
        "query": {},
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "create_prospect_list": {
        "method": "POST",
        "path": "/client/v2/prospect-list",
        "path_fields": {},
        "query": {},
        "body": {
            "listName": "list_name",
            "campaignId": "campaign_id",
            "userUrls": "user_urls",
            "moveOwnDuplicated": "move_own_duplicated",
            "shouldBeDeletedIfInactive": "should_be_deleted_if_inactive",
        },
        "has_body": True,
        "success": [201],
    },
    "get_prospect_list": {
        "method": "GET",
        "path": "/client/v2/prospect-list/{id}",
        "path_fields": {"id": "list_id"},
        "query": {},
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "add_prospects_to_list": {
        "method": "POST",
        "path": "/client/v2/prospect-list/{id}/add-users-to-list",
        "path_fields": {"id": "list_id"},
        "query": {},
        "body": {
            "listId": "list_id",
            "userUrls": "user_urls",
            "moveOwnDuplicated": "move_own_duplicated",
            "shouldBeDeletedIfInactive": "should_be_deleted_if_inactive",
        },
        "has_body": True,
        "success": [200],
    },
    "list_prospects": {
        "method": "GET",
        "path": "/client/v2/prospects",
        "path_fields": {},
        "query": {
            "listId": "list_id",
            "campaignsIds": "campaigns_ids",
            "isImportant": "is_important",
            "postFrequency": "post_frequency",
            "listsIds": "lists_ids",
            "sortBy": "sort_by",
            "sortOrder": "sort_order",
            "search": "search",
            "numberOfTouchPoints": "number_of_touch_points",
            "limit": "limit",
            "offset": "offset",
        },
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "get_prospect": {
        "method": "GET",
        "path": "/client/v2/prospects/{id}",
        "path_fields": {"id": "prospect_id"},
        "query": {},
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "replace_prospect_notes": {
        "method": "POST",
        "path": "/client/v2/prospects/{id}/replace-notes",
        "path_fields": {"id": "prospect_id"},
        "query": {},
        "body": {"notes": "notes"},
        "has_body": True,
        "success": [200],
    },
    "mark_prospect_important": {
        "method": "POST",
        "path": "/client/v2/prospects/{id}/mark-important",
        "path_fields": {"id": "prospect_id"},
        "query": {},
        "body": {"prospectId": "prospect_id", "isImportant": "is_important"},
        "has_body": True,
        "success": [200],
    },
    "list_comments": {
        "method": "GET",
        "path": "/client/v2/comments",
        "path_fields": {},
        "query": {
            "ownerId": "owner_id",
            "campaignId": "campaign_id",
            "view": "view",
            "prospectListId": "prospect_list_id",
            "keywordId": "keyword_id",
            "limit": "limit",
            "offset": "offset",
        },
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "get_comment": {
        "method": "GET",
        "path": "/client/v2/comments/{postId}",
        "path_fields": {"postId": "post_id"},
        "query": {"ownerId": "owner_id"},
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "set_comment_draft": {
        "method": "PATCH",
        "path": "/client/v2/comments/{postId}/draft",
        "path_fields": {"postId": "post_id"},
        "query": {},
        "body": {"postId": "post_id", "ownerId": "owner_id", "text": "text"},
        "has_body": True,
        "success": [200],
    },
    "approve_comment": {
        "method": "POST",
        "path": "/client/v2/comments/{postId}/approve",
        "path_fields": {"postId": "post_id"},
        "query": {},
        "body": {"postId": "post_id", "ownerId": "owner_id"},
        "has_body": True,
        "success": [202],
    },
    "skip_comment": {
        "method": "POST",
        "path": "/client/v2/comments/{postId}/skip",
        "path_fields": {"postId": "post_id"},
        "query": {},
        "body": {"postId": "post_id", "ownerId": "owner_id"},
        "has_body": True,
        "success": [200],
    },
    "list_conversations": {
        "method": "GET",
        "path": "/client/v2/dm-conversations",
        "path_fields": {},
        "query": {
            "ownerId": "owner_id",
            "view": "view",
            "campaignId": "campaign_id",
            "prospectListId": "prospect_list_id",
            "search": "search",
            "limit": "limit",
            "offset": "offset",
        },
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "get_conversation": {
        "method": "GET",
        "path": "/client/v2/dm-conversations/{connectionId}",
        "path_fields": {"connectionId": "connection_id"},
        "query": {
            "markAsRead": "mark_as_read",
            "messageLimit": "message_limit",
            "messageOffset": "message_offset",
        },
        "body": {},
        "has_body": False,
        "success": [200],
    },
    "prepare_reply": {
        "method": "POST",
        "path": "/client/v2/dm-conversations/{connectionId}/replies",
        "path_fields": {"connectionId": "connection_id"},
        "query": {},
        "body": {"connectionId": "connection_id", "text": "text"},
        "has_body": True,
        "success": [200, 201],
    },
    "edit_reply": {
        "method": "PATCH",
        "path": "/client/v2/dm-replies/{dmId}",
        "path_fields": {"dmId": "dm_id"},
        "query": {},
        "body": {"dmId": "dm_id", "text": "text"},
        "has_body": True,
        "success": [200],
    },
    "send_reply": {
        "method": "POST",
        "path": "/client/v2/dm-replies/{dmId}/send",
        "path_fields": {"dmId": "dm_id"},
        "query": {},
        "body": {"dmId": "dm_id", "mode": "mode"},
        "has_body": True,
        "success": [200],
    },
    "snooze_conversation": {
        "method": "POST",
        "path": "/client/v2/dm-conversations/{connectionId}/snooze",
        "path_fields": {"connectionId": "connection_id"},
        "query": {},
        "body": {"connectionId": "connection_id", "untilDate": "until_date"},
        "has_body": True,
        "success": [200],
    },
}


class ExtrovertNode(WorkflowNode):
    integration_type = "automation-extrovert"
    connection_evidence = ConnectionEvidence(
        operation="list_team_members", noun="team members"
    )

    @classmethod
    def get_config_model(cls):
        return ExtrovertNodeConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Extrovert API key")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = route["path"]
        for wire, field in route["path_fields"].items():
            path = path.replace("{" + wire + "}", quote(values[field], safe=""))
        query = []
        for wire, field in route["query"].items():
            if field not in values:
                continue
            value = values[field]
            for item in value if isinstance(value, list) else [value]:
                query.append(
                    (wire, str(item).lower() if isinstance(item, bool) else item)
                )
        body = {
            wire: values[field]
            for wire, field in route["body"].items()
            if field in values
        }
        key = self.config.credentials.api_key
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                route["method"],
                BASE_URL + path,
                params=query,
                headers={"X-API-Key": key, "Accept": "application/json"},
                **({"json": body} if route["has_body"] else {}),
            )
        if response.status_code not in route["success"]:
            message = "Extrovert request failed"
            try:
                candidate = response.json().get("message")
                if isinstance(candidate, str):
                    message = candidate.replace(key, "[redacted]")
            except (ValueError, AttributeError):
                pass
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": message,
                "operation": config.operation,
            }
        payload = response.json()
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "success"
            or "data" not in payload
        ):
            raise ValueError("Extrovert returned an unexpected response envelope")
        # Preserve nested action states (queued/sent, process IDs, allowedActions)
        # and pagination exactly as the provider reports them.
        return {
            **payload,
            "operation": config.operation,
            "http_status": response.status_code,
        }
