"""WoopSocial v1 request models, transcribed from the provider's OpenAPI 1.0.0.

Source: https://api.woopsocial.com/v1/openapi.yaml
"""
from __future__ import annotations
from typing import Annotated, Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import datetime

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class MediaLibraryPostContentMediaInput(Input):
    type: Literal['MEDIA_LIBRARY'] = Field(...)
    mediaId: str = Field(..., description='Media identifier create by calling [`POST /media/upload-sessions`](/api-reference/media/start-media-upload-session) or [`POST /media`](/api-reference/media/upload-media).')


PostContentMediaInput = MediaLibraryPostContentMediaInput


class PostContentItemInput(Input):
    text: Optional[str] = Field(None, description='Text content for this thread item.')
    media: Optional[list[PostContentMediaInput]] = Field(None)

    @model_validator(mode="after")
    def content_present(self):
        if self.text is None and self.media is None:
            raise ValueError("Provide text or media")
        return self


PostContentInput = Annotated[list[PostContentItemInput], Field(min_length=1, max_length=1)]


class DraftPostSchedule(Input):
    type: Literal['DRAFT'] = Field(...)


class PublishNowPostSchedule(Input):
    type: Literal['PUBLISH_NOW'] = Field(...)


class ScheduleForLaterPostSchedule(Input):
    type: Literal['SCHEDULE_FOR_LATER'] = Field(...)
    scheduledFor: str = Field(..., description='UTC time (ISO 8601) when the post should be published. The value must be in the future.')


    @field_validator("scheduledFor")
    @classmethod
    def timestamp(cls, value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ValueError("Use an ISO 8601 timestamp with a timezone") from None
        return value


PostSchedule = Union[DraftPostSchedule, PublishNowPostSchedule, ScheduleForLaterPostSchedule]


class PostRetryPolicy(Input):
    maxRetries: int = Field(..., ge=1, le=5, description='Maximum automatic retries per target, excluding the original attempt.')
    delaySeconds: int = Field(..., ge=60, le=86400, description='Minimum wait after each failure before the retry is published.')


class BlueskyInput(Input):
    platform: Literal['BLUESKY'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)


FacebookPostType = Literal['TEXT_ONLY', 'IMAGE', 'VIDEO', 'REEL', 'STORY']


class FacebookInput(Input):
    platform: Literal['FACEBOOK'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)
    link: Optional[str] = Field(None)
    locationId: Optional[str] = Field(None, description='Facebook place ID to attach to the post.')
    postType: FacebookPostType = Field(...)


InstagramPostType = Literal['POST', 'REEL', 'STORY']


InstagramTrialGraduationStrategy = Literal['MANUAL', 'SS_PERFORMANCE']


class InstagramTrialParams(Input):
    graduationStrategy: InstagramTrialGraduationStrategy = Field(...)


class InstagramInput(Input):
    platform: Literal['INSTAGRAM'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)
    postType: InstagramPostType = Field(...)
    cover: Optional[PostContentMediaInput] = Field(None, description='Optional image media reference to use as the cover image for an Instagram Reel.\n\nThis field applies only to `postType=REEL`.')
    trialParams: Optional[InstagramTrialParams] = Field(None, description='Optional Trial Reel settings. When provided, `postType` must be `REEL`.\n\nOmit this field to publish a regular Reel.')


class LinkedInInput(Input):
    platform: Literal['LINKEDIN'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)
    link: Optional[str] = Field(None, description='URL to publish as a LinkedIn link preview card.')


class LinkedInPagesInput(Input):
    platform: Literal['LINKEDIN_PAGES'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)
    link: Optional[str] = Field(None, description='URL to publish as a LinkedIn link preview card.')


class PinterestInput(Input):
    platform: Literal['PINTEREST'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)
    pinterestBoardId: str = Field(..., description='Identifier of the board to pin to.')
    title: Optional[str] = Field(None)
    link: Optional[str] = Field(None, max_length=2048, description='Destination URL to attach to the Pin.')


class ThreadsInput(Input):
    platform: Literal['THREADS'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)


TikTokPostType = Literal['VIDEO', 'PHOTO']


TikTokPostMode = Literal['DIRECT_POST', 'MEDIA_UPLOAD']


TikTokPrivacyLevel = Literal['PUBLIC_TO_EVERYONE', 'SELF_ONLY', 'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR']


class TikTokInput(Input):
    platform: Literal['TIKTOK'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)
    postType: TikTokPostType = Field(...)
    cover: Optional[PostContentMediaInput] = Field(None, description='Optional image media reference to use as a custom cover for\n`postType=VIDEO`. WoopSocial stitches the image as a single\nframe at the beginning of the video before sending it to TikTok.')
    postMode: TikTokPostMode = Field('DIRECT_POST', description='TikTok posting mode.\n\nDefaults to `DIRECT_POST` when omitted.\n\n`DIRECT_POST` publishes directly to TikTok.\n\n`MEDIA_UPLOAD` uploads the media to TikTok so the creator can\nfinish and publish it in TikTok. Users will receive an inbox notification.\n\nFields not used by the selected mode may be ignored by TikTok.')
    privacyLevel: Optional[TikTokPrivacyLevel] = Field(None, description='Required when `postMode=DIRECT_POST`. Not used for `MEDIA_UPLOAD`.')
    allowComment: bool = Field(..., description='Whether comments should be allowed for this TikTok post.')
    allowDuet: bool = Field(..., description='Whether duets should be allowed for this TikTok post.\n\nThis field applies to `postType=VIDEO`.\n\nWhen `postType=PHOTO`, this field is required by the API contract\nbut is not used by TikTok.')
    allowStitch: bool = Field(..., description='Whether stitches should be allowed for this TikTok post.\n\nThis field applies to `postType=VIDEO`.\n\nWhen `postType=PHOTO`, this field is required by the API contract\nbut is not used by TikTok.')
    isYourBrand: bool = Field(..., description='Whether the post should be disclosed as "Your brand" content on TikTok.')
    isBrandedContent: bool = Field(..., description='Whether the post should be disclosed as branded content on TikTok.')
    isAiGeneratedContent: bool = Field(False, description='Whether the TikTok post contains AI-generated content. This field applies to video posts.')
    autoAddMusic: bool = Field(..., description='Whether TikTok should automatically add music to this post.\n\nThis field applies to `postType=PHOTO`.\n\nWhen `postType=VIDEO`, this field is required by the API contract\nbut is not used by TikTok.')


class WoopTestInput(Input):
    platform: Literal['WOOPTEST'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)
    shouldSucceed: bool = Field(True, description='Whether the simulated delivery should succeed or fail.\n\nDefaults to `true`. Set to `false` to simulate a delivery failure.')


class XInput(Input):
    platform: Literal['X'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)


YouTubePrivacy = Literal['public', 'private', 'unlisted']


class YouTubeInput(Input):
    platform: Literal['YOUTUBE'] = Field(...)
    socialAccountId: str = Field(..., description='Connected social account identifier.')
    contentOverride: Optional[PostContentInput] = Field(None)
    title: str = Field(...)
    privacy: YouTubePrivacy = Field(...)
    category: Optional[str] = Field(None, description='YouTube video category ID, a number sent as a string, such as `22` (People & Blogs) or `24` (Entertainment).\nCategory names such as `Entertainment` are rejected. Leave it out to let YouTube pick the category.\n\nCategories available in every region:\n`1` Film & Animation, `2` Autos & Vehicles, `10` Music, `15` Pets & Animals, `17` Sports,\n`19` Travel & Events, `20` Gaming, `22` People & Blogs, `23` Comedy, `24` Entertainment,\n`25` News & Politics, `26` Howto & Style, `27` Education, `28` Science & Technology.\n`29` Nonprofits & Activism is available only for US channels.')
    tags: Optional[list[str]] = Field(None)
    madeForKids: Optional[bool] = Field(None)


SocialAccountInput = Union[BlueskyInput, FacebookInput, InstagramInput, LinkedInInput, LinkedInPagesInput, PinterestInput, ThreadsInput, TikTokInput, WoopTestInput, XInput, YouTubeInput]


class CreatePostRequest(Input):
    content: PostContentInput = Field(...)
    schedule: PostSchedule = Field(...)
    autoDeleteMediaAfterPublish: bool = Field(False, description='When true, all media referenced by this post is automatically\ndeleted from the media library after all social account deliveries\nfor the post have published successfully.')
    retryPolicy: Optional[PostRetryPolicy] = Field(None, description='Automatic retry policy. Omit to disable automatic retries.')
    socialAccounts: list[SocialAccountInput] = Field(..., min_length=1, description='Social account targets for this post.\n\nAll referenced social accounts must belong to the same project.\nDuplicate `socialAccountId` values are invalid.')


    @model_validator(mode="after")
    def unique_accounts(self):
        ids = [account.socialAccountId for account in self.socialAccounts]
        if len(ids) != len(set(ids)):
            raise ValueError("Choose each social account only once")
        return self


class CreateProjectRequest(Input):
    name: str = Field(..., description='Human-readable project name.')


WebhookEventType = Literal['socialAccountPost.delivery.published', 'socialAccountPost.delivery.failed']


class CreateWebhookEndpointRequest(Input):
    url: str = Field(..., description='The HTTPS URL to POST webhook events to.')
    eventTypes: list[WebhookEventType] = Field(..., min_length=1, description='Webhook event types this endpoint should receive.')



class CreatePostConfig(CreatePostRequest):
    """Creates a (parent) post with one or more social account (child) posts.

All referenced social accounts must belong to the same project.

The request is validated atomically. If any social account fails validation, the post is not created."""
    operation: Literal['create_post'] = Field('create_post', json_schema_extra={"ui:hidden": True})


class ValidatePostConfig(CreatePostRequest):
    """Validates a post without creating one.

This endpoint applies the same validation rules as [`POST /posts`](/api-reference/posts/create-post),
including social account resolution, platform-specific validation, and
media validation for referenced media library items."""
    operation: Literal['validate_post'] = Field('validate_post', json_schema_extra={"ui:hidden": True})


class GetPostConfig(Input):
    """Returns one post with its social account posts inline."""
    operation: Literal['get_post'] = Field('get_post', json_schema_extra={"ui:hidden": True})
    postId: str = Field(..., min_length=1, max_length=512, description='Post identifier.')


class DeletePostConfig(Input):
    """Deletes one scheduled post by post ID.

A post can only be deleted when all of its social account deliveries are
still `NOT_STARTED`."""
    operation: Literal['delete_post'] = Field('delete_post', json_schema_extra={"ui:hidden": True})
    postId: str = Field(..., min_length=1, max_length=512, description='Post identifier.')


SocialPlatform = Literal['PINTEREST', 'LINKEDIN', 'LINKEDIN_PAGES', 'INSTAGRAM', 'FACEBOOK', 'THREADS', 'TIKTOK', 'X', 'YOUTUBE', 'BLUESKY', 'WOOPTEST']


DeliveryStatus = Literal['NOT_STARTED', 'SENDING', 'PUBLISHED', 'FAILED']


class ListSocialAccountPostsConfig(Input):
    """Returns standalone social account posts for the API key's organization.

Each item includes the content, schedule, delivery status and latest stored analytics for a given social account target."""
    operation: Literal['list_social_account_posts'] = Field('list_social_account_posts', json_schema_extra={"ui:hidden": True})
    projectId: Optional[list[str]] = Field(None, description='Filter to one or more projects. Provide a comma-separated list of project IDs.')
    socialAccountId: Optional[list[str]] = Field(None, description='Filter to one or more connected social accounts. Provide a comma-separated list of social account IDs.')
    postId: Optional[list[str]] = Field(None, description='Filter to one or more parent posts. Provide a comma-separated list of post IDs.')
    platform: Optional[list[SocialPlatform]] = Field(None, description='Filter to one or more social platforms. Provide a comma-separated list of platform values.')
    deliveryStatus: Optional[list[DeliveryStatus]] = Field(None, description='Filter to one or more delivery statuses. Provide a comma-separated list of delivery status values.')
    limit: int = Field(50, ge=1, le=100, description='Number of items to return.')
    cursor: Optional[str] = Field(None, description='Opaque cursor for the next page of results.')


class DeleteSocialAccountPostConfig(Input):
    """Deletes one social account post by ID."""
    operation: Literal['delete_social_account_post'] = Field('delete_social_account_post', json_schema_extra={"ui:hidden": True})
    socialAccountPostId: str = Field(..., min_length=1, max_length=512, description='Social account post identifier.')


class CreateProjectConfig(CreateProjectRequest):
    """Creates a project in the API key's organization.

Use projects to isolate social accounts, media, and posts for a
specific user, client, or brand in your application."""
    operation: Literal['create_project'] = Field('create_project', json_schema_extra={"ui:hidden": True})


class ListProjectsConfig(Input):
    """Returns projects that belong to the same organization as the API key. A project corresponds to a "Business Profile" in the UI."""
    operation: Literal['list_projects'] = Field('list_projects', json_schema_extra={"ui:hidden": True})


class DeleteProjectConfig(Input):
    """Permanently deletes one project and its related data, including
connected social accounts, OAuth grants, media references, and posts."""
    operation: Literal['delete_project'] = Field('delete_project', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., min_length=1, max_length=512, description='Project identifier.')


class ListSocialAccountsConfig(Input):
    """Returns social accounts that can currently be used for publishing.

When `projectId` is provided, only social accounts usable within that project are returned."""
    operation: Literal['list_social_accounts'] = Field('list_social_accounts', json_schema_extra={"ui:hidden": True})
    projectId: Optional[str] = Field(None, description='Filter to resources that belong to a specific project.')


class DeleteSocialAccountConfig(Input):
    """Deletes one social account connection by ID.

This removes the associated OAuth grant, including stored access and
refresh tokens, so the account no longer counts toward the
organization's active connected-account allowance."""
    operation: Literal['delete_social_account'] = Field('delete_social_account', json_schema_extra={"ui:hidden": True})
    socialAccountId: str = Field(..., min_length=1, max_length=512, description='Connected social account identifier.')


class GetSocialAccountPlatformInputsConfig(Input):
    """Returns platform-specific input options for a connected social account.

Use this endpoint to discover valid values for flattened post-target
fields such as `pinterestBoardId` and `privacyLevel`."""
    operation: Literal['get_social_account_platform_inputs'] = Field('get_social_account_platform_inputs', json_schema_extra={"ui:hidden": True})
    socialAccountId: str = Field(..., min_length=1, max_length=512, description='Connected social account identifier.')


class ListMediaConfig(Input):
    """Returns media library items that belong to the API key's organization.

When `projectId` is provided, only media in that project is returned."""
    operation: Literal['list_media'] = Field('list_media', json_schema_extra={"ui:hidden": True})
    projectId: Optional[str] = Field(None, description='Filter to resources that belong to a specific project.')
    mediaId: Optional[list[str]] = Field(None, description='Filter to one or more media items. Provide a comma-separated list of media IDs.')
    limit: int = Field(50, ge=1, le=100, description='Number of items to return.')
    cursor: Optional[str] = Field(None, description='Opaque cursor for the next page of results.')


class DeleteMediaConfig(Input):
    """Deletes one media item by ID."""
    operation: Literal['delete_media'] = Field('delete_media', json_schema_extra={"ui:hidden": True})
    mediaId: str = Field(..., min_length=1, max_length=512, description='Media identifier.')


class CreateWebhookConfig(CreateWebhookEndpointRequest):
    """Registers a URL to receive webhook events for the specified event types.

The response includes a `signingSecret` (base64-encoded, 32 bytes) that is
returned **once only**. Use it to verify the `X-Woop-Signature` header on
incoming webhook payloads.

**Signature format:** `t=<unix>,v1=<hmac-sha256-hex>`
**Signed payload:** `<unix>.<json-body>`"""
    operation: Literal['create_webhook'] = Field('create_webhook', json_schema_extra={"ui:hidden": True})


class ListWebhooksConfig(Input):
    """Returns all registered webhook endpoints for the organization. The `signingSecret` field is omitted."""
    operation: Literal['list_webhooks'] = Field('list_webhooks', json_schema_extra={"ui:hidden": True})


class DeleteWebhookConfig(Input):
    """Delete webhook endpoint."""
    operation: Literal['delete_webhook'] = Field('delete_webhook', json_schema_extra={"ui:hidden": True})
    webhookId: str = Field(..., min_length=1, max_length=512, description='Webhook endpoint identifier.')


WoopSocialConfig = Annotated[Union[CreatePostConfig, ValidatePostConfig, GetPostConfig, DeletePostConfig, ListSocialAccountPostsConfig, DeleteSocialAccountPostConfig, CreateProjectConfig, ListProjectsConfig, DeleteProjectConfig, ListSocialAccountsConfig, DeleteSocialAccountConfig, GetSocialAccountPlatformInputsConfig, ListMediaConfig, DeleteMediaConfig, CreateWebhookConfig, ListWebhooksConfig, DeleteWebhookConfig], Field(discriminator="operation")]


ROUTES = {'create_post': ('POST', '/posts', [], 'CreatePostRequest', 201),
 'validate_post': ('POST', '/posts/validate', [], 'CreatePostRequest', 200),
 'get_post': ('GET', '/posts/{postId}', [], None, 200),
 'delete_post': ('DELETE', '/posts/{postId}', [], None, 204),
 'list_social_account_posts': ('GET',
                               '/social-account-posts',
                               ['projectId',
                                'socialAccountId',
                                'postId',
                                'platform',
                                'deliveryStatus',
                                'limit',
                                'cursor'],
                               None,
                               200),
 'delete_social_account_post': ('DELETE', '/social-account-posts/{socialAccountPostId}', [], None, 204),
 'create_project': ('POST', '/projects', [], 'CreateProjectRequest', 201),
 'list_projects': ('GET', '/projects', [], None, 200),
 'delete_project': ('DELETE', '/projects/{projectId}', [], None, 204),
 'list_social_accounts': ('GET', '/social-accounts', ['projectId'], None, 200),
 'delete_social_account': ('DELETE', '/social-accounts/{socialAccountId}', [], None, 204),
 'get_social_account_platform_inputs': ('GET',
                                        '/social-accounts/{socialAccountId}/platform-inputs',
                                        [],
                                        None,
                                        200),
 'list_media': ('GET', '/media', ['projectId', 'mediaId', 'limit', 'cursor'], None, 200),
 'delete_media': ('DELETE', '/media/{mediaId}', [], None, 204),
 'create_webhook': ('POST', '/webhooks', [], 'CreateWebhookEndpointRequest', 201),
 'list_webhooks': ('GET', '/webhooks', [], None, 200),
 'delete_webhook': ('DELETE', '/webhooks/{webhookId}', [], None, 204)}
