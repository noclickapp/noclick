"""SchoolMaker API v1: one provider request per operation, using a pasted API key.

Contract: https://docs.schoolmaker.com/api-reference/openapi.json (1.0.0).
Authentication: https://docs.schoolmaker.com/quickstart.
Lists return one page, preserving provider pagination. Writes are never retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://schoolmaker.co/api/v1"


class SchoolMakerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="SchoolMaker API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.schoolmaker.com/quickstart",
            "x-credential-instructions": "In SchoolMaker, open Settings → Integration & API and copy the API key. API access requires a Pro or Business plan. Paste the key alone; NoClick sends it as a bearer token."})
    credential_type: Literal["schoolmaker_api_key"] = Field("schoolmaker_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def nonblank(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("Use nonblank text")
        return value


class SchoolMakerListMembersConfig(_Input):
    """List Members or Get a Member. One request to the published API operation."""
    operation: Literal["list_members"] = Field("list_members", json_schema_extra={"ui:hidden": True})
    product_id: Optional[str] = Field(None, max_length=10000)
    offer_id: Optional[str] = Field(None, max_length=10000)
    page: Optional[int] = Field(1)
    id: Optional[str] = Field(None, max_length=10000, description='If provided, returns the member with this ID instead of a list.')
    email: Optional[str] = Field(None, max_length=10000, description='If provided (and id not given), returns the member with this email instead of a list.')
    min_points: Optional[float] = Field(None, ge=0, description='Minimum all-time points, inclusive. Members without points count as zero. Requires leaderboards to be enabled. Omit or leave blank for no minimum.')
    max_points: Optional[float] = Field(None, ge=0, description='Maximum all-time points, inclusive. Requires leaderboards to be enabled. Omit or leave blank for no maximum.')
    min_level: Optional[float] = Field(None, ge=0, description='Minimum current level, inclusive. Members without level history count as level 1. Requires levels to be enabled. Omit or leave blank for no minimum.')
    max_level: Optional[float] = Field(None, ge=0, description='Maximum current level, inclusive. Requires levels to be enabled. Omit or leave blank for no maximum.')
    min_coaching_used: Optional[float] = Field(None, ge=0, description='Minimum coaching usage, inclusive. Requires coaching_type_id. Measured in hours for timed coaching or sessions otherwise, including future published appointments. No appointments count as zero. Omit or leave blank for no minimum.')
    max_coaching_used: Optional[float] = Field(None, ge=0, description='Maximum coaching usage, inclusive. Requires coaching_type_id. Measured in hours for timed coaching or sessions otherwise, including future published appointments. No appointments count as zero. Omit or leave blank for no maximum.')
    consultation_category_id: Optional[str] = Field(None, max_length=10000, description='Filter by current offer access to this consultation category. Excludes expired, inactive or deleted accesses and deleted offers. Subscriptions must be active or trialing. Omit or leave blank for no filter.')
    live_category_id: Optional[str] = Field(None, max_length=10000, description='Filter by current offer access to this live category. Excludes expired, inactive or deleted accesses and deleted offers. Subscriptions must be active or trialing. Omit or leave blank for no filter.')
    coaching_type_id: Optional[str] = Field(None, max_length=10000, description='Filter by current offer access to this coaching type. Excludes expired, inactive or deleted accesses and deleted offers. Subscriptions must be active or trialing. Omit or leave blank for no filter.')
    ai_assistant_id: Optional[str] = Field(None, max_length=10000, description='Filter by current offer access to this AI coach. Excludes expired, inactive or deleted accesses and deleted offers. Subscriptions must be active or trialing. Omit or leave blank for no filter.')

class SchoolMakerSetMemberSuspendConfig(_Input):
    """Set Member Suspend Status. One request to the published API operation."""
    operation: Literal["set_member_suspend"] = Field("set_member_suspend", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., max_length=10000, min_length=1)
    suspend: Literal["true", "false"] = Field(..., max_length=10000)

class SchoolMakerSetMemberBanConfig(_Input):
    """Set Member Ban Status. One request to the published API operation."""
    operation: Literal["set_member_ban"] = Field("set_member_ban", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., max_length=10000, min_length=1)
    ban: Literal["true", "false"] = Field(..., max_length=10000)

class SchoolMakerGetMemberAccessesConfig(_Input):
    """Get Member Accesses. One request to the published API operation."""
    operation: Literal["get_member_accesses"] = Field("get_member_accesses", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., max_length=10000, min_length=1)

class SchoolMakerListProgramsConfig(_Input):
    """List Programs. One request to the published API operation."""
    operation: Literal["list_programs"] = Field("list_programs", json_schema_extra={"ui:hidden": True})
    member_id: Optional[str] = Field(None, max_length=10000, description='Filter to programs accessible by this member and include progression.')
    member_email: Optional[str] = Field(None, max_length=10000, description='Filter to programs accessible by this member email and include progression.')

class SchoolMakerGetProgramConfig(_Input):
    """Get Program Details. One request to the published API operation."""
    operation: Literal["get_program"] = Field("get_program", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., max_length=10000, min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")
    member_id: Optional[str] = Field(None, max_length=10000, description='Filter to programs accessible by this member and include progression.')
    member_email: Optional[str] = Field(None, max_length=10000, description='Filter to programs accessible by this member email and include progression.')

class SchoolMakerCreateProgramConfig(_Input):
    """Create a Program. One request to the published API operation."""
    operation: Literal["create_program"] = Field("create_program", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255, description='Program title. Required on creation and cannot be blank. Maximum 255 characters.')
    description: Optional[str] = Field(None, max_length=210, description='Short program summary. Maximum 210 characters.')
    is_published: bool = Field(..., description='Whether the program is published. Required on creation. Published programs count toward your plan limit. Drafts do not.')
    settings_is_certificate_enabled: Optional[bool] = Field(None, description='Give members a certificate when they complete all steps in the program. Off by default. Send true or false to update it. An existing value cannot be cleared with null.')
    is_secret: Optional[bool] = Field(None, description='Only members with access to a "secret program" can see it on the home page.')

class SchoolMakerUpdateProgramConfig(_Input):
    """Set Program Details. One request to the published API operation."""
    operation: Literal["update_program"] = Field("update_program", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., max_length=10000, min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")
    name: Optional[str] = Field(None, min_length=1, max_length=255, description='Program title. Required on creation and cannot be blank. Maximum 255 characters.')
    description: Optional[str] = Field(None, max_length=210, description='Short program summary. Maximum 210 characters.')
    is_published: Optional[bool] = Field(None, description='Whether the program is published. Required on creation. Published programs count toward your plan limit. Drafts do not.')
    settings_is_certificate_enabled: Optional[bool] = Field(None, description='Give members a certificate when they complete all steps in the program. Off by default. Send true or false to update it. An existing value cannot be cleared with null.')
    is_secret: Optional[bool] = Field(None, description='Only members with access to a "secret program" can see it on the home page.')

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, k) is not None for k in ['name', 'description', 'is_published', 'settings_is_certificate_enabled', 'is_secret']):
            raise ValueError("Supply at least one field to update")
        return self

class SchoolMakerDeleteProgramConfig(_Input):
    """Delete a Program. One request to the published API operation."""
    operation: Literal["delete_program"] = Field("delete_program", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., max_length=10000, min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")

class SchoolMakerListOffersConfig(_Input):
    """List Offers. One request to the published API operation."""
    operation: Literal["list_offers"] = Field("list_offers", json_schema_extra={"ui:hidden": True})
    published: Optional[bool] = Field(None)

class SchoolMakerGetOfferConfig(_Input):
    """Get Offer Details. One request to the published API operation."""
    operation: Literal["get_offer"] = Field("get_offer", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., max_length=10000, min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")

class SchoolMakerCreateOfferConfig(_Input):
    """Create an Offer. One request to the published API operation."""
    operation: Literal["create_offer"] = Field("create_offer", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255, description='Offer name. Required when creating and cannot be blank.')
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=200000)
    is_published: Optional[bool] = Field(None, description='Whether the offer and payment pages are published. Unpublishing keeps member accesses. Deleting the offer removes them.')

class SchoolMakerUpdateOfferConfig(_Input):
    """Set Offer Details. One request to the published API operation."""
    operation: Literal["update_offer"] = Field("update_offer", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., max_length=10000, min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")
    name: Optional[str] = Field(None, min_length=1, max_length=255, description='Offer name. Required when creating and cannot be blank.')
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=200000)
    is_published: Optional[bool] = Field(None, description='Whether the offer and payment pages are published. Unpublishing keeps member accesses. Deleting the offer removes them.')

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, k) is not None for k in ['name', 'title', 'description', 'is_published']):
            raise ValueError("Supply at least one field to update")
        return self

class SchoolMakerDeleteOfferConfig(_Input):
    """Delete an Offer. One request to the published API operation."""
    operation: Literal["delete_offer"] = Field("delete_offer", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., max_length=10000, min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")

class SchoolMakerSetOfferAccessConfig(_Input):
    """Set Offer Access for a Member / Add a Member. One request to the published API operation."""
    operation: Literal["set_offer_access"] = Field("set_offer_access", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., max_length=10000, min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")
    member_email: str = Field(..., max_length=10000, min_length=1)
    status: bool = Field(...)
    first_name: Optional[str] = Field(None, max_length=10000)
    last_name: Optional[str] = Field(None, max_length=10000)

class SchoolMakerListCoachingTypesConfig(_Input):
    """List Coaching Types. One request to the published API operation."""
    operation: Literal["list_coaching_types"] = Field("list_coaching_types", json_schema_extra={"ui:hidden": True})

class SchoolMakerCreateCoachingAppointmentConfig(_Input):
    """Create a Coaching Appointment. One request to the published API operation."""
    operation: Literal["create_coaching_appointment"] = Field("create_coaching_appointment", json_schema_extra={"ui:hidden": True})
    type_id: str = Field(..., max_length=10000, min_length=1)
    date: str = Field(..., max_length=10000, min_length=1)
    duration_hours: int = Field(...)
    duration_minutes: int = Field(...)
    name: str = Field(..., max_length=10000, min_length=1)
    description: str = Field(..., max_length=10000, min_length=1)
    is_published: bool = Field(...)
    member_emails: list[str] = Field(...)
    user_emails: list[str] = Field(...)

class SchoolMakerListConversationGroupsConfig(_Input):
    """List Conversation Groups. One request to the published API operation."""
    operation: Literal["list_conversation_groups"] = Field("list_conversation_groups", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, max_length=255, description='Required ID of the user whose conversation history to retrieve. The user must belong to your school.')
    page: Optional[int] = Field(1, ge=1, le=10000, description='Page number. Follow next_page until null.')
    per_page: Optional[int] = Field(30, ge=1, le=30, description='Maximum number of results per page.')
    search: Optional[str] = Field(None, max_length=10000, description='Search title, non-deleted message content, or participant name/email.')
    member_id: Optional[str] = Field(None, min_length=1, max_length=255, description="Filter the selected user's conversations by a participating member ID.")
    participant_user_id: Optional[str] = Field(None, min_length=1, max_length=255, description="Filter the selected user's conversations by another participating user ID.")
    email: Optional[str] = Field(None, max_length=10000, description="Filter by a participant's email, ignoring case and surrounding spaces. No match returns no conversations. When several participant filters are supplied, any match is included.")
    filter: Optional[Literal['unread', 'followed', 'pending_step_validation', 'validated_steps', 'archived']] = Field(None, max_length=10000, description="Filter the selected user's conversations by unread, followed or archived status, or by step completion.")
    archived: Optional[bool] = Field(False, description='Use true for archived conversations only or false to exclude them. Can be combined with another filter. filter=archived takes precedence.')
    sort: Optional[Literal['last_activity_at', 'created_at_desc', 'created_at_asc']] = Field('last_activity_at', max_length=10000, description='Sort by latest activity by default. Matching activity dates are ordered by conversation ID.')

class SchoolMakerCreateConversationGroupConfig(_Input):
    """Create a Conversation Group. One request to the published API operation."""
    operation: Literal["create_conversation_group"] = Field("create_conversation_group", json_schema_extra={"ui:hidden": True})
    title: Optional[str] = Field(None, max_length=10000, description='The title is optional, by default it will just be the names of the participants')
    message: str = Field(..., max_length=10000, min_length=1, description='The message to send. Accepts plain text or supported Markdown. Markdown is rendered as rich text in SchoolMaker. Existing plain-text messages remain supported.')
    sender_id: Optional[str] = Field(None, max_length=10000, description='The ID of the admin or moderator sender. Default is the school owner.')
    member_participants: list[str] = Field(...)
    user_participants: Optional[list[str]] = Field(None)

class SchoolMakerListConversationMessagesConfig(_Input):
    """List Conversation Messages. One request to the published API operation."""
    operation: Literal["list_conversation_messages"] = Field("list_conversation_messages", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")
    user_id: str = Field(..., min_length=1, max_length=255, description='Required ID of the user whose conversation history to retrieve. The user must belong to your school.')
    page: Optional[int] = Field(1, ge=1, le=10000, description='Page number. Follow next_page until null.')
    per_page: Optional[int] = Field(10, ge=1, le=30, description='Number of messages per page, defaulting to 10. Accepts 1 to 30 but returns at most 10.')
    search: Optional[str] = Field(None, max_length=10000, description='Search non-deleted message content. Deleted message bodies are excluded.')

class SchoolMakerSendConversationMessageConfig(_Input):
    """Send a Conversation Message. One request to the published API operation."""
    operation: Literal["send_conversation_message"] = Field("send_conversation_message", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., max_length=10000, min_length=1, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")
    user_id: str = Field(..., max_length=10000, min_length=1, description='The ID of the admin or moderator sending the message')
    message: str = Field(..., max_length=10000, min_length=1, description='The message to send. Accepts plain text or supported Markdown. Markdown is rendered as rich text in SchoolMaker. Existing plain-text messages remain supported.')

class SchoolMakerListCommunityPostsConfig(_Input):
    """List Community Posts. One request to the published API operation."""
    operation: Literal["list_community_posts"] = Field("list_community_posts", json_schema_extra={"ui:hidden": True})
    page: Optional[int] = Field(1, ge=1, le=10000, description='Page number.')
    per_page: Optional[int] = Field(30, ge=1, le=30, description='Number of results per page. Maximum 30.')
    category_id: Optional[str] = Field(None, min_length=1, max_length=255, description='Filter by a published category in your school.')
    solved: Optional[bool] = Field(None, description='true for solved, false for unsolved. Omit or send an empty query value for both. Other values are rejected.')
    query: Optional[str] = Field(None, max_length=10000, description='Search post titles, post bodies and comment bodies, ignoring case. Omit or leave empty for all posts.')

class SchoolMakerCreateCommunityPostConfig(_Input):
    """Create a Community Post. One request to the published API operation."""
    operation: Literal["create_community_post"] = Field("create_community_post", json_schema_extra={"ui:hidden": True})
    category_id: str = Field(..., min_length=1, max_length=255)
    title: str = Field(..., max_length=10000, min_length=1, description='Required nonblank title.')
    body: str = Field(..., max_length=200000, min_length=1, description='Required comment or post content. Embedded attachments and scripts are not supported.')
    body_format: Optional[Literal['html', 'markdown']] = Field('html', max_length=10000, description='HTML or Markdown input, returned as HTML. For blockquotes, use HTML markup.')

class SchoolMakerListCommunityCommentsConfig(_Input):
    """List Community Comments. One request to the published API operation."""
    operation: Literal["list_community_comments"] = Field("list_community_comments", json_schema_extra={"ui:hidden": True})
    post_id: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")
    page: Optional[int] = Field(1, ge=1, le=10000, description='Page number.')
    per_page: Optional[int] = Field(30, ge=1, le=30, description='Number of results per page. Maximum 30.')
    parent_comment_id: Optional[str] = Field(None, min_length=1, max_length=255, description='Optional top-level comment ID from this post, to list its replies.')
    sort: Optional[Literal['oldest', 'newest', 'most_popular', 'latest_activity']] = Field('oldest', max_length=10000, description='Comment order. Most popular uses reactions and replies. Latest activity uses recent activity. Replies remain oldest first for those two options.')

class SchoolMakerCreateCommunityCommentConfig(_Input):
    """Create a Community Comment. One request to the published API operation."""
    operation: Literal["create_community_comment"] = Field("create_community_comment", json_schema_extra={"ui:hidden": True})
    post_id: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", description="SchoolMaker resource ID; copy it from its settings or URL.")
    body: str = Field(..., max_length=200000, min_length=1, description='Required comment or post content. Embedded attachments and scripts are not supported.')
    body_format: Optional[Literal['html', 'markdown']] = Field('html', max_length=10000, description='HTML or Markdown input, returned as HTML. For blockquotes, use HTML markup.')
    parent_comment_id: Optional[str] = Field(None, min_length=1, max_length=255, description='Optional top-level comment of this post. Omit to add a top-level comment.')
    mention_member_ids: Optional[list[str]] = Field(None, max_length=20, description="IDs of up to 20 active members to mention. Duplicate IDs are ignored. Notifications depend on each member's access and preferences.")

SchoolMakerConfig = Annotated[Union[
    SchoolMakerListMembersConfig,
    SchoolMakerSetMemberSuspendConfig,
    SchoolMakerSetMemberBanConfig,
    SchoolMakerGetMemberAccessesConfig,
    SchoolMakerListProgramsConfig,
    SchoolMakerGetProgramConfig,
    SchoolMakerCreateProgramConfig,
    SchoolMakerUpdateProgramConfig,
    SchoolMakerDeleteProgramConfig,
    SchoolMakerListOffersConfig,
    SchoolMakerGetOfferConfig,
    SchoolMakerCreateOfferConfig,
    SchoolMakerUpdateOfferConfig,
    SchoolMakerDeleteOfferConfig,
    SchoolMakerSetOfferAccessConfig,
    SchoolMakerListCoachingTypesConfig,
    SchoolMakerCreateCoachingAppointmentConfig,
    SchoolMakerListConversationGroupsConfig,
    SchoolMakerCreateConversationGroupConfig,
    SchoolMakerListConversationMessagesConfig,
    SchoolMakerSendConversationMessageConfig,
    SchoolMakerListCommunityPostsConfig,
    SchoolMakerCreateCommunityPostConfig,
    SchoolMakerListCommunityCommentsConfig,
    SchoolMakerCreateCommunityCommentConfig
], Field(discriminator="operation")]


class SchoolMakerFullConfig(NodeConfig[SchoolMakerConfig, SchoolMakerAPIKeyCredential]):
    pass


OPERATIONS = {'list_members': {'method': 'GET',
                  'path': '/members',
                  'path_fields': {},
                  'query_fields': {'product_id': 'product_id',
                                   'offer_id': 'offer_id',
                                   'page': 'page',
                                   'id': 'id',
                                   'email': 'email',
                                   'min_points': 'min_points',
                                   'max_points': 'max_points',
                                   'min_level': 'min_level',
                                   'max_level': 'max_level',
                                   'min_coaching_used': 'min_coaching_used',
                                   'max_coaching_used': 'max_coaching_used',
                                   'consultation_category_id': 'consultation_category_id',
                                   'live_category_id': 'live_category_id',
                                   'coaching_type_id': 'coaching_type_id',
                                   'ai_assistant_id': 'ai_assistant_id'},
                  'body_fields': {}},
 'set_member_suspend': {'method': 'POST',
                        'path': '/members/set_suspend',
                        'path_fields': {},
                        'query_fields': {'email': 'email', 'suspend': 'suspend'},
                        'body_fields': {}},
 'set_member_ban': {'method': 'POST',
                    'path': '/members/set_ban',
                    'path_fields': {},
                    'query_fields': {'email': 'email', 'ban': 'ban'},
                    'body_fields': {}},
 'get_member_accesses': {'method': 'GET',
                         'path': '/members/accesses',
                         'path_fields': {},
                         'query_fields': {'email': 'email'},
                         'body_fields': {}},
 'list_programs': {'method': 'GET',
                   'path': '/products',
                   'path_fields': {},
                   'query_fields': {'member_id': 'member_id', 'member_email': 'member_email'},
                   'body_fields': {}},
 'get_program': {'method': 'GET',
                 'path': '/products/{id}',
                 'path_fields': {'id': 'id'},
                 'query_fields': {'member_id': 'member_id', 'member_email': 'member_email'},
                 'body_fields': {}},
 'create_program': {'method': 'POST',
                    'path': '/products',
                    'path_fields': {},
                    'query_fields': {},
                    'body_fields': {'name': 'name',
                                    'description': 'description',
                                    'is_published': 'is_published',
                                    'settings_is_certificate_enabled': 'settings_is_certificate_enabled',
                                    'is_secret': 'is_secret'}},
 'update_program': {'method': 'PATCH',
                    'path': '/products/{id}',
                    'path_fields': {'id': 'id'},
                    'query_fields': {},
                    'body_fields': {'name': 'name',
                                    'description': 'description',
                                    'is_published': 'is_published',
                                    'settings_is_certificate_enabled': 'settings_is_certificate_enabled',
                                    'is_secret': 'is_secret'}},
 'delete_program': {'method': 'DELETE',
                    'path': '/products/{id}',
                    'path_fields': {'id': 'id'},
                    'query_fields': {},
                    'body_fields': {}},
 'list_offers': {'method': 'GET',
                 'path': '/offers',
                 'path_fields': {},
                 'query_fields': {'filters[is_published]': 'published'},
                 'body_fields': {}},
 'get_offer': {'method': 'GET',
               'path': '/offers/{id}',
               'path_fields': {'id': 'id'},
               'query_fields': {},
               'body_fields': {}},
 'create_offer': {'method': 'POST',
                  'path': '/offers',
                  'path_fields': {},
                  'query_fields': {},
                  'body_fields': {'name': 'name',
                                  'title': 'title',
                                  'description': 'description',
                                  'is_published': 'is_published'}},
 'update_offer': {'method': 'PATCH',
                  'path': '/offers/{id}',
                  'path_fields': {'id': 'id'},
                  'query_fields': {},
                  'body_fields': {'name': 'name',
                                  'title': 'title',
                                  'description': 'description',
                                  'is_published': 'is_published'}},
 'delete_offer': {'method': 'DELETE',
                  'path': '/offers/{id}',
                  'path_fields': {'id': 'id'},
                  'query_fields': {},
                  'body_fields': {}},
 'set_offer_access': {'method': 'POST',
                      'path': '/offers/{id}/accesses',
                      'path_fields': {'id': 'id'},
                      'query_fields': {},
                      'body_fields': {'member_email': 'member_email',
                                      'status': 'status',
                                      'first_name': 'first_name',
                                      'last_name': 'last_name'}},
 'list_coaching_types': {'method': 'GET',
                         'path': '/coachings/types',
                         'path_fields': {},
                         'query_fields': {},
                         'body_fields': {}},
 'create_coaching_appointment': {'method': 'POST',
                                 'path': '/coachings/appointments',
                                 'path_fields': {},
                                 'query_fields': {},
                                 'body_fields': {'type_id': 'type_id',
                                                 'date': 'date',
                                                 'duration_hours': 'duration_hours',
                                                 'duration_minutes': 'duration_minutes',
                                                 'name': 'name',
                                                 'description': 'description',
                                                 'is_published': 'is_published',
                                                 'member_emails': 'member_emails',
                                                 'user_emails': 'user_emails'}},
 'list_conversation_groups': {'method': 'GET',
                              'path': '/conversations/groups',
                              'path_fields': {},
                              'query_fields': {'user_id': 'user_id',
                                               'page': 'page',
                                               'per_page': 'per_page',
                                               'search': 'search',
                                               'member_id': 'member_id',
                                               'participant_user_id': 'participant_user_id',
                                               'email': 'email',
                                               'filter': 'filter',
                                               'archived': 'archived',
                                               'sort': 'sort'},
                              'body_fields': {}},
 'create_conversation_group': {'method': 'POST',
                               'path': '/conversations/groups',
                               'path_fields': {},
                               'query_fields': {},
                               'body_fields': {'title': 'title',
                                               'message': 'message',
                                               'sender_id': 'sender_id',
                                               'member_participants': 'member_participants',
                                               'user_participants': 'user_participants'}},
 'list_conversation_messages': {'method': 'GET',
                                'path': '/conversations/groups/{id}/messages',
                                'path_fields': {'id': 'id'},
                                'query_fields': {'user_id': 'user_id',
                                                 'page': 'page',
                                                 'per_page': 'per_page',
                                                 'search': 'search'},
                                'body_fields': {}},
 'send_conversation_message': {'method': 'POST',
                               'path': '/conversations/groups/{id}/messages',
                               'path_fields': {'id': 'id'},
                               'query_fields': {},
                               'body_fields': {'user_id': 'user_id', 'message': 'message'}},
 'list_community_posts': {'method': 'GET',
                          'path': '/community/posts',
                          'path_fields': {},
                          'query_fields': {'page': 'page',
                                           'per_page': 'per_page',
                                           'category_id': 'category_id',
                                           'solved': 'solved',
                                           'query': 'query'},
                          'body_fields': {}},
 'create_community_post': {'method': 'POST',
                           'path': '/community/posts',
                           'path_fields': {},
                           'query_fields': {},
                           'body_fields': {'category_id': 'category_id',
                                           'title': 'title',
                                           'body': 'body',
                                           'body_format': 'body_format'}},
 'list_community_comments': {'method': 'GET',
                             'path': '/community/posts/{post_id}/comments',
                             'path_fields': {'post_id': 'post_id'},
                             'query_fields': {'page': 'page',
                                              'per_page': 'per_page',
                                              'parent_comment_id': 'parent_comment_id',
                                              'sort': 'sort'},
                             'body_fields': {}},
 'create_community_comment': {'method': 'POST',
                              'path': '/community/posts/{post_id}/comments',
                              'path_fields': {'post_id': 'post_id'},
                              'query_fields': {},
                              'body_fields': {'body': 'body',
                                              'body_format': 'body_format',
                                              'parent_comment_id': 'parent_comment_id',
                                              'mention_member_ids': 'mention_member_ids'}}}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items()}
    return value


class SchoolMakerNode(WorkflowNode):
    integration_type = "automation-schoolmaker"
    connection_evidence = ConnectionEvidence(operation="list_programs", noun="programs")

    @classmethod
    def get_config_model(cls):
        return SchoolMakerFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a SchoolMaker API key")
        config = self.config.config
        operation = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = operation["path"]
        for wire, field in operation["path_fields"].items():
            path = path.replace("{" + wire + "}", quote(values[field], safe=""))
        params = {wire: str(values[field]).lower() if isinstance(values[field], bool) else values[field]
                  for wire, field in operation["query_fields"].items() if field in values}
        body = {wire: values[field] for wire, field in operation["body_fields"].items() if field in values}
        kwargs = {"params": params, "headers": {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}}
        if operation["body_fields"]:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(operation["method"], BASE_URL + path, **kwargs)
        except httpx.RequestError:
            return {"status": "error", "error": "SchoolMaker request could not be completed. Check the resource before retrying a write."}
        if not 200 <= response.status_code < 300:
            message = response.text[:2000]
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("error") or error.get("message") or error.get("errors") or message
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, credential.api_key)}
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "data": None}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "error": "SchoolMaker returned an invalid JSON response"}
        if not isinstance(data, (dict, list)):
            return {"status": "error", "error": "SchoolMaker returned an unexpected response shape"}
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            return {"status": "error", "error": _redact(data.get("error") or data["errors"], credential.api_key)}
        data = _redact(data, credential.api_key)
        # Expose provider envelopes intact, including next_page/pagination.
        # The common data key also makes the account's program names usable as evidence.
        return {"status": "success", "http_status": response.status_code,
                "data": data, **({"items": data["products"]} if config.operation == "list_programs" and isinstance(data, dict) and isinstance(data.get("products"), list) else {})}
