"""Postiz REST integration. Primary API contract: https://docs.postiz.com/public-api.

Requests only run when an operation is explicitly executed. No automatic retries.
"""
from __future__ import annotations

import base64
import binascii
import time
from datetime import datetime
from typing import Any, Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

class PostizApiKeyCredential(BaseModel):
    credential_type: Literal["postiz_api_key"] = Field("postiz_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", json_schema_extra={"ui:widget": "password"})
    base_url: str = Field("https://api.postiz.com/public/v1", title="API Base URL", description="Postiz Cloud, or the full public/v1 base URL of your self-hosted instance.")
    model_config = ConfigDict(title="Postiz API Key", json_schema_extra={"x-credential-url": "https://platform.postiz.com", "x-credential-instructions": "Copy the API key from Postiz Settings. For self-hosted Postiz, enter your instance's public/v1 API base URL."})

class PostizAccessTokenCredential(BaseModel):
    credential_type: Literal["postiz_access_token"] = Field("postiz_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="OAuth Access Token", description="An existing non-expiring Postiz OAuth access token. Paste the token itself, without Bearer. This credential does not initiate browser OAuth.", json_schema_extra={"ui:widget": "password"})
    base_url: str = Field("https://api.postiz.com/public/v1", title="API Base URL")
    model_config = ConfigDict(title="Postiz Access Token", json_schema_extra={"x-credential-url": "https://docs.postiz.com/oauth", "x-credential-instructions": "Use an OAuth access token issued by your existing Postiz OAuth app. Browser authorization and app registration are separate from this manual-token credential."})

PostizCredential = Union[PostizApiKeyCredential, PostizAccessTokenCredential]


class PostizTag(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    value: str = Field(..., title='Value')
    label: str = Field(..., title='Label')

class PostizPostItemIntegration(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    id: str = Field(..., title='Id', description='Integration ID')

class PostizMedia(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    id: str = Field(..., title='Id')
    path: str = Field(..., title='Path')
    thumbnailTimestamp: float | None = Field(None, title='Thumbnailtimestamp', description='Milliseconds into the video to use as the cover/thumbnail frame. Supported by Instagram, Instagram Standalone, TikTok Business, and TikTok (Direct Post only, not the UPLOAD/inbox flow); other providers ignore it. For TikTok, in our testing the cover was applied only to public posts (privacy_level PUBLIC_TO_EVERYONE).')

class PostizPostContent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    content: str = Field(..., title='Content', description='Post text content')
    id: str | None = Field(None, title='Id', description='Post ID (for updates)')
    image: list[PostizMedia] | None = Field(None, title='Image')

class PostizXSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['x'] = Field(..., title='  Type', description="Must be 'x'", alias='__type')
    who_can_reply_post: Literal['everyone', 'following', 'mentionedUsers', 'subscribers', 'verified'] = Field(..., title='Who Can Reply Post', description='Who can reply to the post')
    community: str | None = Field(None, title='Community', description='X Community URL (format: https://x.com/i/communities/123)')

class PostizLinkedInSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['linkedin', 'linkedin-page'] = Field(..., title='  Type', description="Use 'linkedin' for profiles, 'linkedin-page' for company pages", alias='__type')
    post_as_images_carousel: bool | None = Field(None, title='Post As Images Carousel', description='Display multiple images as a carousel')
    carousel_name: str | None = Field(None, title='Carousel Name', description='Name for the carousel document')

class PostizInstagramSettingsCollaboratorsItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    label: str | None = Field(None, title='Label', description='Collaborator username')

class PostizInstagramSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['instagram', 'instagram-standalone'] = Field(..., title='  Type', description="Use 'instagram' for FB-linked, 'instagram-standalone' for standalone", alias='__type')
    post_type: Literal['post', 'story'] = Field(..., title='Post Type', description='Type of Instagram post')
    is_trial_reel: bool | None = Field(None, title='Is Trial Reel', description='Whether to post as a trial reel')
    graduation_strategy: Literal['MANUAL', 'SS_PERFORMANCE'] | None = Field(None, title='Graduation Strategy', description='Graduation strategy for trial reels')
    collaborators: list[PostizInstagramSettingsCollaboratorsItem] | None = Field(None, title='Collaborators')

class PostizFacebookSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['facebook'] = Field(..., title='  Type', alias='__type')
    url: str | None = Field(None, title='Url', description='Optional link URL to include in the post')

class PostizYouTubeSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['youtube'] = Field(..., title='  Type', alias='__type')
    title: str = Field(..., title='Title', description='Video title', min_length=2, max_length=100)
    type: Literal['public', 'private', 'unlisted'] = Field(..., title='Type', description='Video visibility')
    selfDeclaredMadeForKids: Literal['yes', 'no'] | None = Field(None, title='Selfdeclaredmadeforkids', description='Made for kids declaration')
    thumbnail: PostizMedia | None = Field(None, title='Thumbnail', description='Custom thumbnail')
    tags: list[PostizTag] | None = Field(None, title='Tags')

class PostizTikTokSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['tiktok'] = Field(..., title='  Type', alias='__type')
    title: str | None = Field(None, title='Title', description='Used as the title of the post. The only setting TikTok keeps when content_posting_method=UPLOAD.', max_length=90)
    privacy_level: Literal['PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY'] = Field(..., title='Privacy Level', description='Applied only when content_posting_method=DIRECT_POST. Ignored by TikTok on UPLOAD.')
    duet: bool = Field(..., title='Duet', description='Video posts only, and only when content_posting_method=DIRECT_POST. TikTok has no duet setting for photo posts.')
    stitch: bool = Field(..., title='Stitch', description='Video posts only, and only when content_posting_method=DIRECT_POST. TikTok has no stitch setting for photo posts.')
    comment: bool = Field(..., title='Comment', description='Applied only when content_posting_method=DIRECT_POST. Ignored by TikTok on UPLOAD.')
    autoAddMusic: Literal['yes', 'no'] = Field(..., title='Autoaddmusic', description='Photo posts only, and only when content_posting_method=DIRECT_POST. Ignored by TikTok on UPLOAD.')
    brand_content_toggle: bool = Field(..., title='Brand Content Toggle', description='Applied only when content_posting_method=DIRECT_POST. Ignored by TikTok on UPLOAD.')
    brand_organic_toggle: bool = Field(..., title='Brand Organic Toggle', description='Applied only when content_posting_method=DIRECT_POST. Ignored by TikTok on UPLOAD.')
    video_made_with_ai: bool | None = Field(None, title='Video Made With Ai', description='Labels the post as AI generated. Video posts only, and only when content_posting_method=DIRECT_POST. TikTok has no AI-generated label for photo posts, and discards it on UPLOAD.')
    content_posting_method: Literal['DIRECT_POST', 'UPLOAD'] = Field(..., title='Content Posting Method', description='Required. Use "DIRECT_POST" to actually publish the post to TikTok. "UPLOAD" does NOT publish: it only sends the media to the user\'s TikTok app inbox, where they must manually finish and publish it within 24 hours or it is discarded. Only use "UPLOAD" when the user explicitly asks to review or edit the post inside the TikTok app before publishing. "UPLOAD" also makes TikTok ignore every other setting in this object except the title.')

class PostizRedditSettingsSubredditItemValueFlair(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    id: str | None = Field(None, title='Id')
    name: str | None = Field(None, title='Name')

class PostizRedditSettingsSubredditItemValue(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    subreddit: str = Field(..., title='Subreddit', description='Subreddit name without r/', min_length=2)
    title: str = Field(..., title='Title', description='Post title', min_length=2)
    type: Literal['self', 'link', 'image', 'video'] = Field(..., title='Type', description='Post type')
    url: str | None = Field(None, title='Url', description='URL for link posts')
    is_flair_required: bool = Field(..., title='Is Flair Required')
    flair: PostizRedditSettingsSubredditItemValueFlair | None = Field(None, title='Flair', json_schema_extra={'ui:widget': 'json'})

class PostizRedditSettingsSubredditItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    value: PostizRedditSettingsSubredditItemValue | None = Field(None, title='Value', json_schema_extra={'ui:widget': 'json'})

class PostizRedditSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['reddit'] = Field(..., title='  Type', alias='__type')
    subreddit: list[PostizRedditSettingsSubredditItem] = Field(..., title='Subreddit', min_length=1)

class PostizLemmySettingsSubredditItemValue(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    subreddit: str = Field(..., title='Subreddit', description='Community name', min_length=2)
    id: str = Field(..., title='Id', description='Community ID')
    title: str = Field(..., title='Title', description='Post title', min_length=2)
    url: str | None = Field(None, title='Url', description='Optional URL')

class PostizLemmySettingsSubredditItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    value: PostizLemmySettingsSubredditItemValue | None = Field(None, title='Value', json_schema_extra={'ui:widget': 'json'})

class PostizLemmySettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['lemmy'] = Field(..., title='  Type', alias='__type')
    subreddit: list[PostizLemmySettingsSubredditItem] = Field(..., title='Subreddit', min_length=1)

class PostizPinterestSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['pinterest'] = Field(..., title='  Type', alias='__type')
    board: str = Field(..., title='Board', description='Board ID', min_length=1)
    title: str | None = Field(None, title='Title', max_length=100)
    link: str | None = Field(None, title='Link')
    dominant_color: str | None = Field(None, title='Dominant Color')

class PostizDiscordSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['discord'] = Field(..., title='  Type', alias='__type')
    channel: str = Field(..., title='Channel', description='Discord channel ID', min_length=1)

class PostizSlackSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['slack'] = Field(..., title='  Type', alias='__type')
    channel: str = Field(..., title='Channel', description='Slack channel ID', min_length=1)

class PostizTwitchSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['twitch'] = Field(..., title='  Type', alias='__type')
    messageType: Literal['message', 'announcement'] | None = Field(None, title='Messagetype', description='Message type')
    announcementColor: Literal['primary', 'blue', 'green', 'orange', 'purple'] | None = Field(None, title='Announcementcolor', description='Announcement color (only for announcement type)')

class PostizDribbbleSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['dribbble'] = Field(..., title='  Type', alias='__type')
    title: str = Field(..., title='Title', description='Shot title', min_length=1)
    team: str | None = Field(None, title='Team', description='Team URL')

class PostizMediumSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['medium'] = Field(..., title='  Type', alias='__type')
    title: str = Field(..., title='Title', description='Article title', min_length=2)
    subtitle: str = Field(..., title='Subtitle', description='Article subtitle', min_length=2)
    canonical: str | None = Field(None, title='Canonical', description='Original URL for SEO')
    publication: str | None = Field(None, title='Publication', description='Publication ID to post to')
    tags: list[PostizTag] | None = Field(None, title='Tags', max_length=4)

class PostizDevToSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['devto'] = Field(..., title='  Type', alias='__type')
    title: str = Field(..., title='Title', description='Article title', min_length=2)
    main_image: PostizMedia | None = Field(None, title='Main Image', description='Cover image')
    canonical: str | None = Field(None, title='Canonical', description='Original URL for SEO')
    organization: str | None = Field(None, title='Organization', description='Organization ID')
    tags: list[PostizTag] | None = Field(None, title='Tags', max_length=4)

class PostizHashnodeSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['hashnode'] = Field(..., title='  Type', alias='__type')
    title: str = Field(..., title='Title', description='Article title', min_length=6)
    subtitle: str | None = Field(None, title='Subtitle', description='Article subtitle', min_length=2)
    main_image: PostizMedia | None = Field(None, title='Main Image', description='Cover image')
    canonical: str | None = Field(None, title='Canonical', description='Original URL for SEO')
    publication: str | None = Field(None, title='Publication', description='Publication ID (required)')
    tags: list[PostizTag] = Field(..., title='Tags', min_length=1)

class PostizWordpressSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['wordpress'] = Field(..., title='  Type', alias='__type')
    title: str = Field(..., title='Title', description='Post title', min_length=2)
    main_image: PostizMedia | None = Field(None, title='Main Image', description='Featured image')
    type: str = Field(..., title='Type', description='Post type (depends on WordPress setup)')

class PostizListmonkSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['listmonk'] = Field(..., title='  Type', alias='__type')
    subject: str = Field(..., title='Subject', description='Email subject line', min_length=1)
    preview: str = Field(..., title='Preview', description='Email preview text')
    list: str = Field(..., title='List', description='List ID to send to')
    template: str | None = Field(None, title='Template', description='Template ID (optional)')

class PostizGmbSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['gmb'] = Field(..., title='  Type', alias='__type')
    topicType: Literal['STANDARD', 'EVENT', 'OFFER'] | None = Field(None, title='Topictype', description='Post type')
    callToActionType: Literal['NONE', 'BOOK', 'ORDER', 'SHOP', 'LEARN_MORE', 'SIGN_UP', 'GET_OFFER', 'CALL'] | None = Field(None, title='Calltoactiontype', description='Call-to-action button')
    callToActionUrl: str | None = Field(None, title='Calltoactionurl', description='URL for CTA (required if callToActionType is set)')
    eventTitle: str | None = Field(None, title='Eventtitle', description='Event title (required for EVENT type)')
    eventStartDate: str | None = Field(None, title='Eventstartdate', description='Event start date')
    eventEndDate: str | None = Field(None, title='Eventenddate', description='Event end date')
    eventStartTime: str | None = Field(None, title='Eventstarttime', description='Event start time')
    eventEndTime: str | None = Field(None, title='Eventendtime', description='Event end time')
    offerCouponCode: str | None = Field(None, title='Offercouponcode', description='Coupon code (for OFFER type)')
    offerRedeemUrl: str | None = Field(None, title='Offerredeemurl', description='Redemption URL')
    offerTerms: str | None = Field(None, title='Offerterms', description='Offer terms and conditions')

class PostizWarpcastSettingsSubredditItemValue(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    id: str = Field(..., title='Id', description='Channel ID')

class PostizWarpcastSettingsSubredditItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    value: PostizWarpcastSettingsSubredditItemValue | None = Field(None, title='Value', json_schema_extra={'ui:widget': 'json'})

class PostizWarpcastSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['warpcast'] = Field(..., title='  Type', alias='__type')
    subreddit: list[PostizWarpcastSettingsSubredditItem] | None = Field(None, title='Subreddit', description='Farcaster channels to post to')

class PostizMoltbookSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['moltbook'] = Field(..., title='  Type', alias='__type')
    submolt: str = Field(..., title='Submolt', description='Submolt (community) ID', min_length=1)

class PostizSkoolSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['skool'] = Field(..., title='  Type', alias='__type')
    group: str = Field(..., title='Group', description='Group ID', min_length=1)
    label: str = Field(..., title='Label', description='Label/category ID', min_length=1)
    title: str = Field(..., title='Title', description='Post title', min_length=1)

class PostizWhopSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['whop'] = Field(..., title='  Type', alias='__type')
    company: str = Field(..., title='Company', description='Company ID', min_length=1)
    experience: str = Field(..., title='Experience', description='Experience/forum ID', min_length=1)
    title: str | None = Field(None, title='Title', description='Post title')

class PostizEmptySettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: Literal['threads', 'mastodon', 'bluesky', 'telegram', 'nostr', 'vk', 'kick'] = Field(..., title='  Type', description='Platform identifier', alias='__type')

class PostizPostItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    integration: PostizPostItemIntegration = Field(..., title='Integration', json_schema_extra={'ui:widget': 'json'})
    value: list[PostizPostContent] = Field(..., title='Value')
    group: str | None = Field(None, title='Group', description='Group ID for related posts')
    settings: Union[PostizXSettings, PostizLinkedInSettings, PostizInstagramSettings, PostizFacebookSettings, PostizYouTubeSettings, PostizTikTokSettings, PostizRedditSettings, PostizLemmySettings, PostizPinterestSettings, PostizDiscordSettings, PostizSlackSettings, PostizTwitchSettings, PostizDribbbleSettings, PostizMediumSettings, PostizDevToSettings, PostizHashnodeSettings, PostizWordpressSettings, PostizListmonkSettings, PostizGmbSettings, PostizWarpcastSettings, PostizMoltbookSettings, PostizSkoolSettings, PostizWhopSettings, PostizEmptySettings] | None = Field(None, title='Settings', description='Provider-specific settings')

class PostizGenerateVideoCustomParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    voice: str | None = Field(None, title='Voice', description='ElevenLabs voice ID (for image-text-slides)')
    prompt: str | None = Field(None, title='Prompt', description='Description/script for the video')
    images: list[PostizMedia] | None = Field(None, title='Images', description='Reference images (for veo3, max 3)', max_length=3)

class PostizGetAnalyticsConfig(BaseModel):
    'Get platform analytics'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_analytics'] = Field('get_analytics', json_schema_extra={'const': 'get_analytics', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'Get Analytics'})
    integration: str = Field(..., title='Integration', description='Integration ID', min_length=1)
    date: str = Field(..., title='Date', description='Number of days to look back for analytics data (e.g. 7, 30, 90)')

class PostizGetPostAnalyticsConfig(BaseModel):
    'Get post analytics'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_post_analytics'] = Field('get_post_analytics', json_schema_extra={'const': 'get_post_analytics', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'Get Post Analytics'})
    postId: str = Field(..., title='Post Id', description='Post ID', min_length=1)
    date: str = Field(..., title='Date', description='Number of days to look back for analytics data (e.g. 7, 30, 90)')

class PostizStartClippingConfig(BaseModel):
    'Start a clipping'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['start_clipping'] = Field('start_clipping', json_schema_extra={'const': 'start_clipping', 'ui:hidden': True, 'x-category': 'Media', 'x-operation-name': 'Start Clipping'})
    url: str = Field(..., title='Url', description='URL of the YouTube video (`youtube.com` or `youtu.be`)')
    integrations: list[str] | None = Field(None, title='Integrations', description='IDs of the integrations to create a draft post for, one draft per clip per integration. Without any, the clips only land in the media library', max_length=20)
    clips: int | None = Field(5, title='Clips', description='Maximum number of clips', ge=1, le=10)
    fit: Literal['blur', 'crop'] | None = Field('blur', title='Fit', description='How the horizontal video fills the vertical clip. `blur` keeps the whole picture over a blurred copy of itself. `crop` fills the clip with the middle of the picture and cuts the sides away; there is no face tracking')

class PostizGetClippingConfig(BaseModel):
    'Get a clipping'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_clipping'] = Field('get_clipping', json_schema_extra={'const': 'get_clipping', 'ui:hidden': True, 'x-category': 'Media', 'x-operation-name': 'Get Clipping'})
    id: str = Field(..., title='Id', description='ID of the clipping', min_length=1)

class PostizListClippingsConfig(BaseModel):
    'List clippings'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_clippings'] = Field('list_clippings', json_schema_extra={'const': 'list_clippings', 'ui:hidden': True, 'x-category': 'Media', 'x-operation-name': 'List Clippings'})
    page: int | None = Field(1, title='Page', description='Page number (1-indexed). Defaults to 1.', ge=1)

class PostizGetIntegrationUrlConfig(BaseModel):
    'Get OAuth URL for a channel'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_integration_url'] = Field('get_integration_url', json_schema_extra={'const': 'get_integration_url', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'Get Integration Url'})
    integration: str = Field(..., title='Integration', description='The integration identifier (e.g. x, linkedin, facebook, instagram, youtube, tiktok, reddit, etc.)', min_length=1)
    refresh: str | None = Field(None, title='Refresh', description='Pass an existing integration ID to refresh its OAuth token instead of creating a new connection')

class PostizDeleteChannelConfig(BaseModel):
    'Delete a channel'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['delete_channel'] = Field('delete_channel', json_schema_extra={'const': 'delete_channel', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'Delete Channel'})
    id: str = Field(..., title='Id', description='Integration ID of the channel to delete', min_length=1)

class PostizFindSlotConfig(BaseModel):
    'Find next available slot'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['find_slot'] = Field('find_slot', json_schema_extra={'const': 'find_slot', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'Find Slot'})
    id: str = Field(..., title='Id', description='Integration ID', min_length=1)

class PostizListGroupsConfig(BaseModel):
    'List all groups (customers)'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_groups'] = Field('list_groups', json_schema_extra={'const': 'list_groups', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'List Groups'})

class PostizIsConnectedConfig(BaseModel):
    'Check connection status'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['is_connected'] = Field('is_connected', json_schema_extra={'const': 'is_connected', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'Is Connected'})

class PostizListIntegrationsConfig(BaseModel):
    'List all integrations'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_integrations'] = Field('list_integrations', json_schema_extra={'const': 'list_integrations', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'List Integrations'})
    group: str | None = Field(None, title='Group', description='Filter integrations by customer (group) ID. Returns only channels assigned to the given group.')

class PostizGetMeConfig(BaseModel):
    'Get connected account'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_me'] = Field('get_me', json_schema_extra={'const': 'get_me', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'Get Me'})

class PostizGetIntegrationSettingsConfig(BaseModel):
    'Get integration settings and tools'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_integration_settings'] = Field('get_integration_settings', json_schema_extra={'const': 'get_integration_settings', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'Get Integration Settings'})
    id: str = Field(..., title='Id', description='The integration ID', min_length=1)

class PostizTriggerIntegrationToolConfig(BaseModel):
    'Trigger an integration tool'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['trigger_integration_tool'] = Field('trigger_integration_tool', json_schema_extra={'const': 'trigger_integration_tool', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'Trigger Integration Tool'})
    methodName: str = Field(..., title='Methodname', description='The tool method name, as returned by the integration settings endpoint')
    data: dict[str, str] | None = Field(None, title='Data', description='Key-value parameters for the tool', json_schema_extra={'ui:widget': 'json'})
    id: str = Field(..., title='Id', description='The integration ID', min_length=1)

class PostizListNotificationsConfig(BaseModel):
    'List notifications'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_notifications'] = Field('list_notifications', json_schema_extra={'const': 'list_notifications', 'ui:hidden': True, 'x-category': 'Channels', 'x-operation-name': 'List Notifications'})
    page: int | None = Field(0, title='Page', description='Page number (0-indexed). Defaults to 0.', ge=0)

class PostizChangePostStatusConfig(BaseModel):
    'Change post status'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['change_post_status'] = Field('change_post_status', json_schema_extra={'const': 'change_post_status', 'ui:hidden': True, 'x-category': 'Posts', 'x-operation-name': 'Change Post Status'})
    status: Literal['draft', 'schedule'] = Field(..., title='Status', description='New status for the post')
    id: str = Field(..., title='Id', description='Post ID', min_length=1)

class PostizCreatePostConfig(BaseModel):
    'Create a post'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['create_post'] = Field('create_post', json_schema_extra={'const': 'create_post', 'ui:hidden': True, 'x-category': 'Posts', 'x-operation-name': 'Create Post'})
    type: Literal['draft', 'schedule', 'now'] = Field(..., title='Type', description='Post type')
    date: datetime = Field(..., title='Date', description='Publish date in UTC ISO format', json_schema_extra={'ui:widget': 'datetime'})
    shortLink: bool = Field(..., title='Shortlink', description='Whether to use short links')
    order: str | None = Field(None, title='Order', description='Order of posts')
    inter: float | None = Field(None, title='Inter', description='Interval between posts')
    tags: list[PostizTag] = Field(..., title='Tags')
    posts: list[PostizPostItem] | None = Field(None, title='Posts', description="Required if type is not 'draft'")

    @model_validator(mode="after")
    def require_scheduled_content(self):
        if self.type != "draft" and not self.posts:
            raise ValueError("Scheduled and immediate posts require at least one post.")
        if self.date.tzinfo is None:
            raise ValueError("Publish date must include its UTC offset.")
        return self

class PostizDeletePostByGroupConfig(BaseModel):
    'Delete a post by group'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['delete_post_by_group'] = Field('delete_post_by_group', json_schema_extra={'const': 'delete_post_by_group', 'ui:hidden': True, 'x-category': 'Posts', 'x-operation-name': 'Delete Post By Group'})
    group: str = Field(..., title='Group', description='Group identifier to delete', min_length=1)

class PostizDeletePostConfig(BaseModel):
    'Delete a post by ID'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['delete_post'] = Field('delete_post', json_schema_extra={'const': 'delete_post', 'ui:hidden': True, 'x-category': 'Posts', 'x-operation-name': 'Delete Post'})
    id: str = Field(..., title='Id', description='Post ID to delete', min_length=1)

class PostizListPostsConfig(BaseModel):
    'List posts'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_posts'] = Field('list_posts', json_schema_extra={'const': 'list_posts', 'ui:hidden': True, 'x-category': 'Posts', 'x-operation-name': 'List Posts'})
    startDate: datetime = Field(..., title='Startdate', description='Start date in UTC ISO format', json_schema_extra={'ui:widget': 'datetime'})
    endDate: datetime = Field(..., title='Enddate', description='End date in UTC ISO format', json_schema_extra={'ui:widget': 'datetime'})
    customer: str | None = Field(None, title='Customer', description='Filter by customer ID')

class PostizGetMissingContentConfig(BaseModel):
    'Get missing content'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['get_missing_content'] = Field('get_missing_content', json_schema_extra={'const': 'get_missing_content', 'ui:hidden': True, 'x-category': 'Posts', 'x-operation-name': 'Get Missing Content'})
    id: str = Field(..., title='Id', description='Post ID', min_length=1)

class PostizUpdatePostSettingsConfig(BaseModel):
    'Update post settings'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['update_post_settings'] = Field('update_post_settings', json_schema_extra={'const': 'update_post_settings', 'ui:hidden': True, 'x-category': 'Posts', 'x-operation-name': 'Update Post Settings'})
    settings: dict[str, Any] = Field(..., title='Settings', description="Provider settings to merge into the post's existing settings. Only the keys you pass are changed; everything else stays. Keys depend on the channel's platform.", json_schema_extra={'ui:widget': 'json'})
    id: str = Field(..., title='Id', description='Post ID', min_length=1)

class PostizUpdateReleaseIdConfig(BaseModel):
    'Update release ID'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['update_release_id'] = Field('update_release_id', json_schema_extra={'const': 'update_release_id', 'ui:hidden': True, 'x-category': 'Posts', 'x-operation-name': 'Update Release Id'})
    releaseId: str = Field(..., title='Release Id', description='The platform-specific content ID to connect to this post')
    id: str = Field(..., title='Id', description='Post ID', min_length=1)

class PostizListMediaConfig(BaseModel):
    'List media'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['list_media'] = Field('list_media', json_schema_extra={'const': 'list_media', 'ui:hidden': True, 'x-category': 'Media', 'x-operation-name': 'List Media'})
    page: int | None = Field(1, title='Page', description='Page number (1-indexed). Defaults to 1.', ge=1)
    search: str | None = Field(None, title='Search', description='Case-insensitive filter on the original file name.')

class PostizUploadFileConfig(BaseModel):
    'Upload a file'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['upload_file'] = Field('upload_file', json_schema_extra={'const': 'upload_file', 'ui:hidden': True, 'x-category': 'Media', 'x-operation-name': 'Upload File'})
    file_base64: str = Field(
        ..., min_length=4,
        pattern=r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$",
        title='File Base64', description='Base64-encoded file bytes from a previous node. No local filesystem paths are accepted.',
    )
    filename: str = Field(..., title='Filename', min_length=1)
    content_type: str | None = Field('application/octet-stream', title='Content Type')

    @field_validator("filename")
    @classmethod
    def plain_filename(cls, value):
        if "/" in value or "\\" in value or any(ord(c) < 32 for c in value):
            raise ValueError("Use a filename without path separators or control characters.")
        return value

class PostizUploadFromUrlConfig(BaseModel):
    'Upload from URL'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['upload_from_url'] = Field('upload_from_url', json_schema_extra={'const': 'upload_from_url', 'ui:hidden': True, 'x-category': 'Media', 'x-operation-name': 'Upload From Url'})
    url: str = Field(..., title='Url', description='URL of the file to upload')

class PostizVideoFunctionConfig(BaseModel):
    'Video function'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['video_function'] = Field('video_function', json_schema_extra={'const': 'video_function', 'ui:hidden': True, 'x-category': 'Media', 'x-operation-name': 'Video Function'})
    functionName: str = Field(..., title='Functionname', description='Function to execute')
    identifier: str = Field(..., title='Identifier', description='Video type identifier')
    params: dict[str, Any] | None = Field(None, title='Params', description='Additional parameters', json_schema_extra={'ui:widget': 'json'})

class PostizGenerateVideoConfig(BaseModel):
    'Generate a video'
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation: Literal['generate_video'] = Field('generate_video', json_schema_extra={'const': 'generate_video', 'ui:hidden': True, 'x-category': 'Media', 'x-operation-name': 'Generate Video'})
    type: Literal['image-text-slides', 'veo3'] = Field(..., title='Type', description='Video generation type')
    output: Literal['vertical', 'horizontal'] = Field(..., title='Output', description='Video orientation')
    customParams: PostizGenerateVideoCustomParams = Field(..., title='Customparams', json_schema_extra={'ui:widget': 'json'})

PostizConfig = Annotated[Union[PostizGetAnalyticsConfig, PostizGetPostAnalyticsConfig, PostizStartClippingConfig, PostizGetClippingConfig, PostizListClippingsConfig, PostizGetIntegrationUrlConfig, PostizDeleteChannelConfig, PostizFindSlotConfig, PostizListGroupsConfig, PostizIsConnectedConfig, PostizListIntegrationsConfig, PostizGetMeConfig, PostizGetIntegrationSettingsConfig, PostizTriggerIntegrationToolConfig, PostizListNotificationsConfig, PostizChangePostStatusConfig, PostizCreatePostConfig, PostizDeletePostByGroupConfig, PostizDeletePostConfig, PostizListPostsConfig, PostizGetMissingContentConfig, PostizUpdatePostSettingsConfig, PostizUpdateReleaseIdConfig, PostizListMediaConfig, PostizUploadFileConfig, PostizUploadFromUrlConfig, PostizVideoFunctionConfig, PostizGenerateVideoConfig], Field(discriminator="operation")]

class PostizNodeConfig(NodeConfig[PostizConfig, PostizCredential]):
    pass

ROUTES = {'get_analytics': ('GET', '/analytics/{integration}', ['integration'], ['date'], []), 'get_post_analytics': ('GET', '/analytics/post/{postId}', ['postId'], ['date'], []), 'start_clipping': ('POST', '/clipping', [], [], ['url', 'integrations', 'clips', 'fit']), 'get_clipping': ('GET', '/clipping/{id}', ['id'], [], []), 'list_clippings': ('GET', '/clipping', [], ['page'], []), 'get_integration_url': ('GET', '/social/{integration}', ['integration'], ['refresh'], []), 'delete_channel': ('DELETE', '/integrations/{id}', ['id'], [], []), 'find_slot': ('GET', '/find-slot/{id}', ['id'], [], []), 'list_groups': ('GET', '/groups', [], [], []), 'is_connected': ('GET', '/is-connected', [], [], []), 'list_integrations': ('GET', '/integrations', [], ['group'], []), 'get_me': ('GET', '/me', [], [], []), 'get_integration_settings': ('GET', '/integration-settings/{id}', ['id'], [], []), 'trigger_integration_tool': ('POST', '/integration-trigger/{id}', ['id'], [], ['methodName', 'data']), 'list_notifications': ('GET', '/notifications', [], ['page'], []), 'change_post_status': ('PUT', '/posts/{id}/status', ['id'], [], ['status']), 'create_post': ('POST', '/posts', [], [], ['type', 'date', 'shortLink', 'order', 'inter', 'tags', 'posts']), 'delete_post_by_group': ('DELETE', '/posts/group/{group}', ['group'], [], []), 'delete_post': ('DELETE', '/posts/{id}', ['id'], [], []), 'list_posts': ('GET', '/posts', [], ['startDate', 'endDate', 'customer'], []), 'get_missing_content': ('GET', '/posts/{id}/missing', ['id'], [], []), 'update_post_settings': ('PUT', '/posts/{id}/settings', ['id'], [], ['settings']), 'update_release_id': ('PUT', '/posts/{id}/release-id', ['id'], [], ['releaseId']), 'list_media': ('GET', '/media', [], ['page', 'search'], []), 'upload_file': ('POST', '/upload', [], [], ['file_base64', 'filename', 'content_type']), 'upload_from_url': ('POST', '/upload-from-url', [], [], ['url']), 'video_function': ('POST', '/video/function', [], [], ['functionName', 'identifier', 'params']), 'generate_video': ('POST', '/generate-video', [], [], ['type', 'output', 'customParams'])}

PROVIDER = "Postiz"
AUTH_PREFIX = ""  # Postiz requires the raw API key or OAuth token, without Bearer.

def _auth(credential):
    base = credential.get("base_url", "https://api.postiz.com/public/v1").rstrip("/")
    parts = urlsplit(base)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Enter an HTTP(S) Postiz API base URL without embedded credentials, query, or fragment.")
    token = (credential.get("api_key") or credential.get("access_token") or "").strip()
    if not token:
        raise ValueError("Postiz API key or OAuth access token is required.")
    return base, token

async def _request(credential: dict[str, Any], method: str, path: str,
                   *, params=None, body=None, files=None, action: str) -> dict[str, Any]:
    """One bounded request. Error responses never echo credentials or request bodies."""
    base, token = _auth(credential)
    started = time.monotonic()
    headers = {"Authorization": AUTH_PREFIX + token, "Accept": "application/json"}
    kwargs = {"params": params, "headers": headers}
    if files is not None:
        kwargs["files"] = files
    elif body is not None:
        kwargs["json"] = body
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            response = await client.request(method, base + path, **kwargs)
        timing = {"api_request": round((time.monotonic() - started) * 1000, 2)}
        if not 200 <= response.status_code < 300:
            # Provider error text can echo sensitive inputs. Keep HTTP status and retry guidance.
            return {"status": "error", "action": action,
                    "error": f"{PROVIDER} returned HTTP {response.status_code}.",
                    "status_code": response.status_code,
                    "retry_after": response.headers.get("Retry-After"), "timing_ms": timing}
        if response.status_code == 204 or not response.content:
            data = {"success": True}
        else:
            try:
                data = response.json()
            except ValueError:
                return {"status": "error", "action": action,
                        "error": f"{PROVIDER} returned a non-JSON response.",
                        "status_code": response.status_code, "timing_ms": timing}
        # Preserve pagination and provider envelopes; arrays stay arrays for downstream tables.
        return {"status": "success", "action": action, "data": data,
                "status_code": response.status_code, "timing_ms": timing}
    except httpx.TimeoutException:
        return {"status": "error", "action": action, "error": "Request timed out.",
                "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)}}
    except httpx.RequestError:
        return {"status": "error", "action": action, "error": "Could not reach the provider.",
                "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)}}


def _request_parts(config: BaseModel):
    route = ROUTES[config.operation]
    values = config.model_dump(mode="json", by_alias=True, exclude_none=True)
    path = route[1]
    for key in route[2]:
        path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
    params = {key: values[key] for key in route[3] if key in values}
    body = {key: values[key] for key in route[4] if key in values}
    return route[0], path, params, body or None


class PostizNode(WorkflowNode):
    """Postiz workflow operations from the official REST API."""
    integration_type = "automation-postiz"
    credential_provider_labels = {"postiz": "Postiz Account"}
    connection_evidence = ConnectionEvidence(operation="list_integrations", identity_operation="get_me", noun="social channels")
    edit_examples = ['Get platform analytics', 'Get post analytics', 'Start a clipping']

    @classmethod
    def get_config_model(cls):
        return PostizNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        if not isinstance(self.config, PostizNodeConfig):
            raise ValueError("Valid Postiz configuration is required.")
        op = self.config.config
        if op.operation == "upload_file":
            if self.config.credentials is None:
                raise ValueError("Add a Postiz credential to upload a file.")
            try:
                data = base64.b64decode(op.file_base64, validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("File content must be valid base64.") from None
            if not data:
                raise ValueError("The upload file cannot be empty.")
            result = await _request(self.config.credentials.model_dump(), "POST", "/upload", files={"file": (op.filename, data, op.content_type)}, action=op.operation)
            result.setdefault("timing_ms", {})["total"] = round((time.monotonic() - started) * 1000, 2)
            return result
        if self.config.credentials is None:
            raise ValueError("Add a Postiz credential to run this operation.")
        credential = self.config.credentials.model_dump()
        method, path, params, body = _request_parts(op)
        result = await _request(credential, method, path, params=params, body=body, action=op.operation)
        result.setdefault("timing_ms", {})["total"] = round((time.monotonic() - started) * 1000, 2)
        return result

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in ("integration", "id", "group"):
            return {"options": [], "next_page_token": None}
        operation = (context or {}).get("operation", "")
        if field_name == "id" and operation not in ("find_slot", "delete_channel", "get_integration_settings", "trigger_integration_tool"):
            return {"options": [], "next_page_token": None}
        # get_integration_url takes a platform identifier, unlike analytics which takes a channel ID.
        if operation == "get_integration_url":
            return {"options": [], "next_page_token": None}
        path = "/groups" if field_name == "group" else "/integrations"
        result = await _request(credential_data, "GET", path, action="list_groups" if field_name == "group" else "list_integrations")
        if result["status"] != "success":
            raise ValueError(result["error"])
        rows = result["data"]
        if isinstance(rows, dict):
            rows = rows.get("integrations", rows.get("groups", []))
        options = [{"label": str(row.get("name") or row.get("identifier") or row["id"]), "value": row["id"]} for row in rows if isinstance(row, dict) and row.get("id")]
        if search:
            options = [o for o in options if search.casefold() in o["label"].casefold()]
        return {"options": options, "next_page_token": None}
