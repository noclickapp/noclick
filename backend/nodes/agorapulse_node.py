"""Agorapulse organization, publishing, inbox and listening operations.

Fixed endpoints follow the provider's OpenAPI 1.0 contract. Scheduled inbox
and listening polls baseline existing items and emit newly encountered IDs.
"""
from __future__ import annotations
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class AgorapulseAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Agorapulse API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://api.agorapulse.com/docs/",
            "x-credential-instructions": "Paste your Agorapulse API key. NoClick sends it in X-API-KEY to api.agorapulse.com. Your organizations provide connection evidence."})
    credential_type: Literal["agorapulse_api_key"] = Field("agorapulse_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgorapulseListOrganizationsConfig(_Input):
    """Get manager organizations."""
    operation: Literal['list_organizations'] = Field('list_organizations', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get manager organizations', "x-method-kind": 'read'})
    v: str | None = Field(None, title='V', description='API version')

class AgorapulseListWorkspacesConfig(_Input):
    """Get organization workspaces."""
    operation: Literal['list_workspaces'] = Field('list_workspaces', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get organization workspaces', "x-method-kind": 'read'})
    organizationId: str = Field(..., title='Organization Id', description='Organization id')
    v: str | None = Field(None, title='V', description='API version')

class AgorapulseListGroupsConfig(_Input):
    """List workspace menu groups."""
    operation: Literal['list_groups'] = Field('list_groups', json_schema_extra={"ui:hidden": True, "x-display-name": 'List workspace menu groups', "x-method-kind": 'read'})
    organizationId: str = Field(..., title='Organization Id', description='Organization id')
    workspaceId: str = Field(..., title='Workspace Id', description='Workspace id')
    v: str | None = Field(None, title='V', description='API version')

class AgorapulseListProfilesConfig(_Input):
    """Get workspace profiles."""
    operation: Literal['list_profiles'] = Field('list_profiles', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get workspace profiles', "x-method-kind": 'read'})
    organizationId: str = Field(..., title='Organization Id', description='Organization id')
    workspaceId: str = Field(..., title='Workspace Id', description='Workspace id')
    v: str | None = Field(None, title='V', description='API version')



class AgorapulseListCalendarNotesConfig(_Input):
    """Search calendar notes."""
    operation: Literal['list_calendar_notes'] = Field('list_calendar_notes', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search calendar notes', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization identifier')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace identifier')
    since: str | None = Field(None, title='Since', description='Filter notes after this date (ISO date)', json_schema_extra={"format": 'date'})
    until: str | None = Field(None, title='Until', description='Filter notes before this date (ISO date)', json_schema_extra={"format": 'date'})
    profileUids: list[str] | None = Field(None, title='Profile Uids', description='Filter by profile UIDs')

class AgorapulseCreateCalendarNoteConfig(_Input):
    """Create a new calendar note."""
    operation: Literal['create_calendar_note'] = Field('create_calendar_note', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create a new calendar note', "x-method-kind": 'write'})
    organizationId: int = Field(..., title='Organization Id', description='Organization identifier')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace identifier')
    title: str = Field(..., title='Title', description='Note title', min_length=1)
    body: str | None = Field(None, title='Body', description='Note body content')
    color: Literal['BLUE', 'RED', 'YELLOW', 'GREEN', 'PURPLE', 'PINK', 'ORANGE', 'MINT', 'CYAN', 'GREY'] = Field(..., title='Color')
    startDate: str = Field(..., title='Start Date', description='Note start date', json_schema_extra={"format": 'date'})
    endDate: str = Field(..., title='End Date', description='Note end date', json_schema_extra={"format": 'date'})
    profileUids: list[str] | None = Field(None, title='Profile Uids', description='List of profile UIDs associated with the note. Optional on create, where omitting it attaches the note to no profile. Required on update, where [] detaches the note from every profile')

class AgorapulseUpdateCalendarNoteConfig(_Input):
    """Update a calendar note."""
    operation: Literal['update_calendar_note'] = Field('update_calendar_note', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update a calendar note', "x-method-kind": 'write'})
    organizationId: int = Field(..., title='Organization Id', description='Organization identifier')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace identifier')
    uid: str = Field(..., title='Uid', description='Calendar note unique identifier')
    title: str = Field(..., title='Title', description='Note title', min_length=1)
    body: str | None = Field(None, title='Body', description='Note body content')
    color: Literal['BLUE', 'RED', 'YELLOW', 'GREEN', 'PURPLE', 'PINK', 'ORANGE', 'MINT', 'CYAN', 'GREY'] = Field(..., title='Color')
    startDate: str = Field(..., title='Start Date', description='Note start date', json_schema_extra={"format": 'date'})
    endDate: str = Field(..., title='End Date', description='Note end date', json_schema_extra={"format": 'date'})
    profileUids: list[str] = Field(..., title='Profile Uids', description='List of profile UIDs associated with the note. Optional on create, where omitting it attaches the note to no profile. Required on update, where [] detaches the note from every profile')

class AgorapulseDeleteCalendarNoteConfig(_Input):
    """Delete a calendar note."""
    operation: Literal['delete_calendar_note'] = Field('delete_calendar_note', json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete a calendar note', "x-method-kind": 'write'})
    organizationId: int = Field(..., title='Organization Id', description='Organization identifier')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace identifier')
    uid: str = Field(..., title='Uid', description='Calendar note unique identifier')


class AgorapulseListInboxItemsConfig(_Input):
    """Find items."""
    operation: Literal['list_inbox_items'] = Field('list_inbox_items', json_schema_extra={"ui:hidden": True, "x-display-name": 'Find items', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')
    profileUids: list[str] | None = Field(None, title='Profile Uids', description='Set of profile UIDs to filter items, at least one is required. Only items from these profiles will be returned.')
    accountUids: list[str] | None = Field(None, title='Account Uids', description='Deprecated: use profileUids instead, which takes precedence when both are provided.')
    toReview: bool | None = Field(None, title='To Review', description='Filter items in the To review state: not yet marked reviewed by a team member. Unrelated to approval workflows.')
    labels: list[str] | None = Field(None, title='Labels', description='Filter items by labels. Only items with these labels will be returned.')
    sentiments: list[Literal['POSITIVE', 'NEGATIVE', 'NEUTRAL']] | None = Field(None, title='Sentiments', description='Filter items by sentiment.')
    types: list[Literal['ADS_COMMENT', 'ORGANIC_COMMENT', 'CONVERSATION', 'MENTION', 'RATING', 'REEL_COMMENT', 'STORY_MENTION_CONVERSATION', 'PROFILE_COMMENT', 'PROFILE_MESSAGE']] | None = Field(None, title='Types', description='Filter items by type/source. Specify the types of items to retrieve (e.g., organicComment, adsComment, conversation, ...). profileComment and profileMessage return what the profile itself replied, every other value returns incoming items; several values are combined as a union.')
    parentIds: list[str] | None = Field(None, title='Parent Ids', description='Filter items by parent, taking the id of an item returned by this endpoint. Returns the children of these items: the comments of a post, the replies of a comment, the messages of a conversation.')
    since: str | None = Field(None, title='Since', description='Filter items created after this date (inclusive). ISO 8601 format.', json_schema_extra={"format": 'date-time'})
    until: str | None = Field(None, title='Until', description='Filter items created before this date (inclusive). ISO 8601 format.', json_schema_extra={"format": 'date-time'})
    offset: str | None = Field(None, title='Offset', description='Offset for pagination')
    limit: int | None = Field(None, title='Limit', description='Maximum number of items to return per page. Must be between 1 and 25.', ge=1, le=25)
    order: Literal['ASC', 'DESC'] | None = Field(None, title='Order', description='Sort order for the results. ASC for ascending (oldest first), DESC for descending (newest first).')

class AgorapulseListConversationMessagesConfig(_Input):
    """Get conversation messages."""
    operation: Literal['list_conversation_messages'] = Field('list_conversation_messages', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get conversation messages', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')
    profileUid: str = Field(..., title='Profile Uid', description='Profile uid, as returned by the profiles endpoint')
    conversationId: str = Field(..., title='Conversation Id', description='Conversation id')
    since: str | None = Field(None, title='Since', description='Filter messages created after this date (inclusive). ISO 8601 format.', json_schema_extra={"format": 'date-time'})
    until: str | None = Field(None, title='Until', description='Filter messages created before this date (inclusive). ISO 8601 format.', json_schema_extra={"format": 'date-time'})
    offset: str | None = Field(None, title='Offset', description='Offset for pagination')
    limit: int | None = Field(None, title='Limit', description='Maximum number of messages to return per page. Must be between 1 and 25.', ge=1, le=25)
    order: Literal['ASC', 'DESC'] | None = Field(None, title='Order', description='Sort order for the results. ASC for ascending (oldest first), DESC for descending (newest first).')

class AgorapulseGetInboxItemConfig(_Input):
    """Get item."""
    operation: Literal['get_inbox_item'] = Field('get_inbox_item', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get item', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')
    profileUid: str = Field(..., title='Profile Uid', description='Profile uid, as returned by the profiles endpoint')
    itemId: str = Field(..., title='Item Id', description='Item id, as returned by the items endpoint. It also resolves the parentId and postId of an item, and the id an history event carries.')

class AgorapulseReplyToItemConfig(_Input):
    """Reply to an item."""
    operation: Literal['reply_to_item'] = Field('reply_to_item', json_schema_extra={"ui:hidden": True, "x-display-name": 'Reply to an item', "x-method-kind": 'write'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')
    profileUid: str = Field(..., title='Profile Uid', description='Profile uid, as returned by the profiles endpoint')
    itemId: str = Field(..., title='Item Id', description='The ID of the inbox item to reply to', min_length=1)
    message: str = Field(..., title='Message', description='The content of the reply message', min_length=1)
    privateReply: bool | None = Field(None, title='Private Reply', description='When true, sends a private message to the user instead of replying publicly to a public item (e.g., comment). The reply will be sent as a direct/private message. Supported by Facebook, Instagram, and Twitter.')
    excludedUsers: list[str] | None = Field(None, title='Excluded Users', description='List of user IDs to exclude from mentions (Twitter-specific)')

class AgorapulseListListeningSearchesConfig(_Input):
    """List searches."""
    operation: Literal['list_listening_searches'] = Field('list_listening_searches', json_schema_extra={"ui:hidden": True, "x-display-name": 'List searches', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')

class AgorapulseGetListeningEngagementConfig(_Input):
    """Get the search engagement."""
    operation: Literal['get_listening_engagement'] = Field('get_listening_engagement', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get the search engagement', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')
    searchId: str = Field(..., title='Search Id', description='Id of the listening search the metric is computed on')
    since: str | None = Field(None, title='Since', description='Take into account the items published after this date (inclusive), ISO 8601. Defaults to the start of the day six days ago, so an unbounded request covers the last seven days.', json_schema_extra={"format": 'date-time'})
    until: str | None = Field(None, title='Until', description='Take into account the items published before this date (inclusive), ISO 8601. Defaults to the end of the current day.', json_schema_extra={"format": 'date-time'})
    networks: list[Literal['FACEBOOK', 'INSTAGRAM', 'TWITTER', 'LINKEDIN', 'TIKTOK', 'YOUTUBE', 'REDDIT', 'WEB_NEWS', 'WEB_BLOG', 'WEB_FORUM']] | None = Field(None, title='Networks', description='Take into account the items from these social networks only')
    sentiments: list[Literal['POSITIVE', 'NEGATIVE', 'NEUTRAL']] | None = Field(None, title='Sentiments', description='Take into account the items with these sentiments only')
    keyword: str | None = Field(None, title='Keyword', description='Take into account the items whose extracted keywords include this one only, matched exactly and case-insensitively against the values the keywords endpoint returns. An unknown keyword returns an empty result. Items whose keyword extraction found no text or failed carry no keyword and are never counted.')
    competitors: list[str] | None = Field(None, title='Competitors', description='Take into account the items that matched these competitors of a competitive search only. The names are the ones the searches endpoint returns; an unknown name, or a search that is not competitive, is rejected. An item matching two competitors is counted for both.')
    groupBy: Literal['DATE', 'NETWORK', 'COMPETITOR'] | None = Field(None, title='Group By', description='Dimension to break the metric down along. Omit it for the overall figure. DATE returns one group per period step and echoes the granularity, NETWORK one per social network, COMPETITOR one per competitor of a competitive search — and no total, since an item matching two competitors counts in both groups.')

class AgorapulseListListeningItemsConfig(_Input):
    """Find items."""
    operation: Literal['list_listening_items'] = Field('list_listening_items', json_schema_extra={"ui:hidden": True, "x-display-name": 'Find items', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')
    searchId: str = Field(..., title='Search Id', description='Id of the listening search whose items are returned')
    since: str | None = Field(None, title='Since', description='Return items published after this date (inclusive), ISO 8601. Defaults to the start of the day six days ago, so an unbounded request covers the last seven days.', json_schema_extra={"format": 'date-time'})
    until: str | None = Field(None, title='Until', description='Return items published before this date (inclusive), ISO 8601. Defaults to the end of the current day.', json_schema_extra={"format": 'date-time'})
    networks: list[Literal['FACEBOOK', 'INSTAGRAM', 'TWITTER', 'LINKEDIN', 'TIKTOK', 'YOUTUBE', 'REDDIT', 'WEB_NEWS', 'WEB_BLOG', 'WEB_FORUM']] | None = Field(None, title='Networks', description='Return items from these social networks only')
    sentiments: list[Literal['POSITIVE', 'NEGATIVE', 'NEUTRAL']] | None = Field(None, title='Sentiments', description='Return items with these sentiments only')
    keyword: str | None = Field(None, title='Keyword', description='Return the items whose extracted keywords include this one only, matched exactly and case-insensitively against the values the keywords endpoint returns. An unknown keyword returns an empty result. Items whose keyword extraction found no text or failed carry no keyword and are never returned.')
    competitors: list[str] | None = Field(None, title='Competitors', description='Return the items that matched these competitors of a competitive search only. The names are the ones the searches endpoint returns; an unknown name, or a search that is not competitive, is rejected. An item matching two competitors is returned for both.')
    offset: str | None = Field(None, title='Offset', description='Offset returned by the previous response, to read the next page')
    limit: int | None = Field(None, title='Limit', description='Maximum number of items to return per page. Must be between 1 and 25.', ge=1, le=25)
    orderBy: Literal['DATE', 'ENGAGEMENT'] | None = Field(None, title='Order By', description='Field the items are sorted on. DATE for the publication date, ENGAGEMENT for the interactions the item collected.')
    order: Literal['ASC', 'DESC'] | None = Field(None, title='Order', description='Sort direction. DESC for the highest value first — the newest items, or the most engaging ones — ASC for the lowest.')

class AgorapulseListListeningKeywordsConfig(_Input):
    """Get the search keywords."""
    operation: Literal['list_listening_keywords'] = Field('list_listening_keywords', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get the search keywords', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')
    searchId: str = Field(..., title='Search Id', description='Id of the listening search whose keywords are returned')
    since: str | None = Field(None, title='Since', description='Take into account the items published after this date (inclusive), ISO 8601. Defaults to the start of the day six days ago, so an unbounded request covers the last seven days.', json_schema_extra={"format": 'date-time'})
    until: str | None = Field(None, title='Until', description='Take into account the items published before this date (inclusive), ISO 8601. Defaults to the end of the current day.', json_schema_extra={"format": 'date-time'})
    networks: list[Literal['FACEBOOK', 'INSTAGRAM', 'TWITTER', 'LINKEDIN', 'TIKTOK', 'YOUTUBE', 'REDDIT', 'WEB_NEWS', 'WEB_BLOG', 'WEB_FORUM']] | None = Field(None, title='Networks', description='Take into account the items from these social networks only')
    sentiments: list[Literal['POSITIVE', 'NEGATIVE', 'NEUTRAL']] | None = Field(None, title='Sentiments', description='Take into account the items with these sentiments only, which is how to read what a search is complained about')
    keyword: str | None = Field(None, title='Keyword', description='Take into account the items whose extracted keywords include this one only, matched exactly and case-insensitively. The keywords returned are then the ones mentioned alongside it.')
    competitors: list[str] | None = Field(None, title='Competitors', description='Take into account the items that matched these competitors of a competitive search only. The names are the ones the searches endpoint returns; an unknown name, or a search that is not competitive, is rejected.')
    size: int | None = Field(None, title='Size', description='Number of keywords to return. Must be between 1 and 100.', ge=1, le=100)

class AgorapulseGetListeningSentimentConfig(_Input):
    """Get the search sentiment."""
    operation: Literal['get_listening_sentiment'] = Field('get_listening_sentiment', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get the search sentiment', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')
    searchId: str = Field(..., title='Search Id', description='Id of the listening search the metric is computed on')
    since: str | None = Field(None, title='Since', description='Take into account the items published after this date (inclusive), ISO 8601. Defaults to the start of the day six days ago, so an unbounded request covers the last seven days.', json_schema_extra={"format": 'date-time'})
    until: str | None = Field(None, title='Until', description='Take into account the items published before this date (inclusive), ISO 8601. Defaults to the end of the current day.', json_schema_extra={"format": 'date-time'})
    networks: list[Literal['FACEBOOK', 'INSTAGRAM', 'TWITTER', 'LINKEDIN', 'TIKTOK', 'YOUTUBE', 'REDDIT', 'WEB_NEWS', 'WEB_BLOG', 'WEB_FORUM']] | None = Field(None, title='Networks', description='Take into account the items from these social networks only')
    sentiments: list[Literal['POSITIVE', 'NEGATIVE', 'NEUTRAL']] | None = Field(None, title='Sentiments', description='Take into account the items with these sentiments only')
    keyword: str | None = Field(None, title='Keyword', description='Take into account the items whose extracted keywords include this one only, matched exactly and case-insensitively against the values the keywords endpoint returns. An unknown keyword returns an empty result. Items whose keyword extraction found no text or failed carry no keyword and are never counted.')
    competitors: list[str] | None = Field(None, title='Competitors', description='Take into account the items that matched these competitors of a competitive search only. The names are the ones the searches endpoint returns; an unknown name, or a search that is not competitive, is rejected. An item matching two competitors is counted for both.')
    groupBy: Literal['DATE', 'NETWORK', 'COMPETITOR'] | None = Field(None, title='Group By', description='Dimension to break the metric down along. Omit it for the overall figure. DATE returns one group per period step and echoes the granularity, NETWORK one per social network, COMPETITOR one per competitor of a competitive search — and no total, since an item matching two competitors counts in both groups.')

class AgorapulseGetListeningVolumeConfig(_Input):
    """Get the search volume."""
    operation: Literal['get_listening_volume'] = Field('get_listening_volume', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get the search volume', "x-method-kind": 'read'})
    organizationId: int = Field(..., title='Organization Id', description='Organization id')
    workspaceId: int = Field(..., title='Workspace Id', description='Workspace id')
    searchId: str = Field(..., title='Search Id', description='Id of the listening search the metric is computed on')
    since: str | None = Field(None, title='Since', description='Take into account the items published after this date (inclusive), ISO 8601. Defaults to the start of the day six days ago, so an unbounded request covers the last seven days.', json_schema_extra={"format": 'date-time'})
    until: str | None = Field(None, title='Until', description='Take into account the items published before this date (inclusive), ISO 8601. Defaults to the end of the current day.', json_schema_extra={"format": 'date-time'})
    networks: list[Literal['FACEBOOK', 'INSTAGRAM', 'TWITTER', 'LINKEDIN', 'TIKTOK', 'YOUTUBE', 'REDDIT', 'WEB_NEWS', 'WEB_BLOG', 'WEB_FORUM']] | None = Field(None, title='Networks', description='Take into account the items from these social networks only')
    sentiments: list[Literal['POSITIVE', 'NEGATIVE', 'NEUTRAL']] | None = Field(None, title='Sentiments', description='Take into account the items with these sentiments only')
    keyword: str | None = Field(None, title='Keyword', description='Take into account the items whose extracted keywords include this one only, matched exactly and case-insensitively against the values the keywords endpoint returns. An unknown keyword returns an empty result. Items whose keyword extraction found no text or failed carry no keyword and are never counted.')
    competitors: list[str] | None = Field(None, title='Competitors', description='Take into account the items that matched these competitors of a competitive search only. The names are the ones the searches endpoint returns; an unknown name, or a search that is not competitive, is rejected. An item matching two competitors is counted for both.')
    groupBy: Literal['DATE', 'NETWORK', 'COMPETITOR'] | None = Field(None, title='Group By', description='Dimension to break the metric down along. Omit it for the overall figure. DATE returns one group per period step and echoes the granularity, NETWORK one per social network, COMPETITOR one per competitor of a competitive search — and no total, since an item matching two competitors counts in both groups.')

class AgorapulseOnNewInboxItemConfig(PollTriggerConfigBase):
    """Watch the newest 25 items per tick. Use a shorter schedule or narrower scope for busy feeds; existing items are baselined on activation."""
    operation: Literal['on_new_inbox_item'] = Field('on_new_inbox_item', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": 'On New Inbox Item'})
    organizationId: int = Field(..., title="Organization ID")
    workspaceId: int = Field(..., title="Workspace ID")
    profileUids: list[str] | None = Field(None, title="Profile IDs")
    since: str | None = Field(None, title="Published Since", description="Optional ISO 8601 publication-time lower bound.", json_schema_extra={"format": "date-time"})

class AgorapulseOnNewListeningItemConfig(PollTriggerConfigBase):
    """Watch the newest 25 items per tick. Use a shorter schedule or narrower scope for busy feeds; existing items are baselined on activation."""
    operation: Literal['on_new_listening_item'] = Field('on_new_listening_item', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": 'On New Listening Item'})
    organizationId: int = Field(..., title="Organization ID")
    workspaceId: int = Field(..., title="Workspace ID")
    searchId: str = Field(..., min_length=1, title="Listening Search ID")
    since: str | None = Field(None, title="Published Since", description="Optional ISO 8601 publication-time lower bound.", json_schema_extra={"format": "date-time"})

# Fixed routes and field placement from Agorapulse OpenAPI 1.0.
OPERATIONS = {'list_organizations': {'method': 'GET',
                        'path': '/v1.0/core/organizations',
                        'query': ['v'],
                        'body': []},
 'list_workspaces': {'method': 'GET',
                     'path': '/v1.0/core/organizations/{organizationId}/workspaces',
                     'query': ['v'],
                     'body': []},
 'list_groups': {'method': 'GET',
                 'path': '/v1.0/core/organizations/{organizationId}/workspaces/{workspaceId}/menugroups',
                 'query': ['v'],
                 'body': []},
 'list_profiles': {'method': 'GET',
                   'path': '/v1.0/core/organizations/{organizationId}/workspaces/{workspaceId}/profiles',
                   'query': ['v'],
                   'body': []},
 'list_calendar_notes': {'method': 'GET',
                         'path': '/v1.0/publishing/organizations/{organizationId}/workspaces/{workspaceId}/notes',
                         'query': ['since', 'until', 'profileUids'],
                         'body': []},
 'create_calendar_note': {'method': 'POST',
                          'path': '/v1.0/publishing/organizations/{organizationId}/workspaces/{workspaceId}/notes',
                          'query': [],
                          'body': ['title',
                                   'body',
                                   'color',
                                   'startDate',
                                   'endDate',
                                   'profileUids']},
 'update_calendar_note': {'method': 'PUT',
                          'path': '/v1.0/publishing/organizations/{organizationId}/workspaces/{workspaceId}/notes/{uid}',
                          'query': [],
                          'body': ['title',
                                   'body',
                                   'color',
                                   'startDate',
                                   'endDate',
                                   'profileUids']},
 'delete_calendar_note': {'method': 'DELETE',
                          'path': '/v1.0/publishing/organizations/{organizationId}/workspaces/{workspaceId}/notes/{uid}',
                          'query': [],
                          'body': []},
 'list_inbox_items': {'method': 'GET',
                      'path': '/v1.0/inbox/organizations/{organizationId}/workspaces/{workspaceId}/items',
                      'query': ['profileUids',
                                'accountUids',
                                'toReview',
                                'labels',
                                'sentiments',
                                'types',
                                'parentIds',
                                'since',
                                'until',
                                'offset',
                                'limit',
                                'order'],
                      'body': []},
 'list_conversation_messages': {'method': 'GET',
                                'path': '/v1.0/inbox/organizations/{organizationId}/workspaces/{workspaceId}/profiles/{profileUid}/conversations/{conversationId}/messages',
                                'query': ['since', 'until', 'offset', 'limit', 'order'],
                                'body': []},
 'get_inbox_item': {'method': 'GET',
                    'path': '/v1.0/inbox/organizations/{organizationId}/workspaces/{workspaceId}/profiles/{profileUid}/items/{itemId}',
                    'query': [],
                    'body': []},
 'reply_to_item': {'method': 'POST',
                   'path': '/v1.0/inbox/organizations/{organizationId}/workspaces/{workspaceId}/profiles/{profileUid}/reply',
                   'query': [],
                   'body': ['itemId', 'message', 'privateReply', 'excludedUsers']},
 'list_listening_searches': {'method': 'GET',
                             'path': '/v1.0/listening/organizations/{organizationId}/workspaces/{workspaceId}/searches',
                             'query': [],
                             'body': []},
 'get_listening_engagement': {'method': 'GET',
                              'path': '/v1.0/listening/organizations/{organizationId}/workspaces/{workspaceId}/searches/{searchId}/engagements',
                              'query': ['since',
                                        'until',
                                        'networks',
                                        'sentiments',
                                        'keyword',
                                        'competitors',
                                        'groupBy'],
                              'body': []},
 'list_listening_items': {'method': 'GET',
                          'path': '/v1.0/listening/organizations/{organizationId}/workspaces/{workspaceId}/searches/{searchId}/items',
                          'query': ['since',
                                    'until',
                                    'networks',
                                    'sentiments',
                                    'keyword',
                                    'competitors',
                                    'offset',
                                    'limit',
                                    'orderBy',
                                    'order'],
                          'body': []},
 'list_listening_keywords': {'method': 'GET',
                             'path': '/v1.0/listening/organizations/{organizationId}/workspaces/{workspaceId}/searches/{searchId}/keywords',
                             'query': ['since',
                                       'until',
                                       'networks',
                                       'sentiments',
                                       'keyword',
                                       'competitors',
                                       'size'],
                             'body': []},
 'get_listening_sentiment': {'method': 'GET',
                             'path': '/v1.0/listening/organizations/{organizationId}/workspaces/{workspaceId}/searches/{searchId}/sentiments',
                             'query': ['since',
                                       'until',
                                       'networks',
                                       'sentiments',
                                       'keyword',
                                       'competitors',
                                       'groupBy'],
                             'body': []},
 'get_listening_volume': {'method': 'GET',
                          'path': '/v1.0/listening/organizations/{organizationId}/workspaces/{workspaceId}/searches/{searchId}/volumes',
                          'query': ['since',
                                    'until',
                                    'networks',
                                    'sentiments',
                                    'keyword',
                                    'competitors',
                                    'groupBy'],
                          'body': []}}

AgorapulseConfig = Annotated[Union[AgorapulseListOrganizationsConfig, AgorapulseListWorkspacesConfig, AgorapulseListGroupsConfig, AgorapulseListProfilesConfig, AgorapulseListCalendarNotesConfig, AgorapulseCreateCalendarNoteConfig, AgorapulseUpdateCalendarNoteConfig, AgorapulseDeleteCalendarNoteConfig, AgorapulseListInboxItemsConfig, AgorapulseListConversationMessagesConfig, AgorapulseGetInboxItemConfig, AgorapulseReplyToItemConfig, AgorapulseListListeningSearchesConfig, AgorapulseGetListeningEngagementConfig, AgorapulseListListeningItemsConfig, AgorapulseListListeningKeywordsConfig, AgorapulseGetListeningSentimentConfig, AgorapulseGetListeningVolumeConfig, AgorapulseOnNewInboxItemConfig, AgorapulseOnNewListeningItemConfig], Field(discriminator="operation")]

class AgorapulseFullConfig(NodeConfig[AgorapulseConfig, AgorapulseAPIKeyCredential]):
    pass


class AgorapulseNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-agorapulse"
    connection_evidence = ConnectionEvidence(
        noun="Agorapulse organizations", operation="list_organizations", label_keys=("organizationName",))

    @classmethod
    def get_config_model(cls):
        return AgorapulseFullConfig

    @classmethod
    def resolve_agent_event(cls, output):
        items = output.get("items", [])
        if not items:
            return None
        lines = [f"Agorapulse: {len(items)} new social item(s)"]
        for item in items[:25]:
            creator = item.get("creator") or {}
            lines.append(f"From {creator.get('name', 'Unknown author')} (author ID {creator.get('id', '')}): {item.get('text', '')}")
            lines.append(f"Item ID: {item.get('id', '')}; published: {item.get('creationDate', '')}; URL: {item.get('networkLink', '')}")
        return {"text": "\n".join(lines)[:12000], "conversation_key": None,
                "title": "New Agorapulse social items"}

    async def _request(self, spec, values):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Agorapulse API key")
        path = spec["path"]
        for key, value in values.items():
            if "{" + key + "}" not in path:
                continue
            segment = str(value)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", segment):
                raise ValueError("Use a single Agorapulse resource ID")
            path = path.replace("{" + key + "}", quote(segment, safe=""))
        params = {key: values[key] for key in spec["query"] if key in values}
        body = {key: values[key] for key in spec["body"] if key in values}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(spec["method"], "https://api.agorapulse.com" + path,
                headers={"X-API-KEY": credential.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if spec["body"] else {}))
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {"success": True}
        return response.json()

    async def execute(self, inputs):
        config = self.config.config
        operation = config.operation
        if operation.startswith("on_new_"):
            source = "list_inbox_items" if operation == "on_new_inbox_item" else "list_listening_items"
            values = config.model_dump(exclude_none=True, exclude=set(PollTriggerConfigBase.model_fields) | {"operation"})
            values.update(limit=25, order="DESC")
            if source == "list_listening_items":
                values["orderBy"] = "DATE"
            # Watch the newest 25 items per tick. The provider caps each list
            # page at 25; users can narrow the scope or shorten the schedule.
            data = await self._request(OPERATIONS[source], values)
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ValueError("Agorapulse returned an invalid item list")
            items = data["items"]
            fresh = await self._filter_unseen(items, lambda item: str(item["id"]) if item.get("id") else None)
            return {"items": fresh, "new_item_count": len(fresh)}
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        return await self._request(OPERATIONS[operation], values)
