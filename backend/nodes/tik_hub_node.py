"""Tik Hub social-data API, pinned to the provider's V5.3.2 contract.

Each operation makes one request. Pagination values remain in the provider
response; pass them back explicitly to retrieve the next page. Batch extraction
POSTs submit URL arrays, and do not publish or modify social-media content.
"""
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.tikhub.io"


class TikHubCredential(BaseModel):
    model_config = ConfigDict(
        title="Tik Hub API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://user.tikhub.io",
            "x-credential-instructions": "In TikHub's user center, open API Tokens and create a token. Paste the token here without Bearer. Allow the account-info endpoint and the social-data endpoints you plan to use. API requests may incur TikHub charges.",
        },
    )
    credential_type: Literal["tik_hub_api_token"] = Field("tik_hub_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API token, without Bearer or spaces")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class GetAccountConfig(_Config):
    """Get TikHub user info."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class GetDailyUsageConfig(_Config):
    """Get user daily usage."""
    operation: Literal["get_daily_usage"] = Field("get_daily_usage", json_schema_extra={"ui:hidden": True})


class GetTiktokProfileConfig(_Config):
    """Get user profile."""
    operation: Literal["get_tiktok_profile"] = Field("get_tiktok_profile", json_schema_extra={"ui:hidden": True})
    uniqueId: str = Field(..., min_length=1, max_length=4096, description='User uniqueId')


class GetTiktokVideoConfig(_Config):
    """Get single video data."""
    operation: Literal["get_tiktok_video"] = Field("get_tiktok_video", json_schema_extra={"ui:hidden": True})
    itemId: str = Field(..., min_length=1, max_length=4096, description='Video id')
    region: str = Field('US', max_length=4096, description='Region code, for example US, GB, JP or ID.')


class ListTiktokPostsConfig(_Config):
    """Get user posts."""
    operation: Literal["list_tiktok_posts"] = Field("list_tiktok_posts", json_schema_extra={"ui:hidden": True})
    secUid: str = Field(..., min_length=1, max_length=4096, description='User secUid')
    cursor: int = Field(0, ge=0, description='Page cursor')
    count: int = Field(15, ge=1, le=15, description='Number per page, max 15')
    coverFormat: int = Field(2, ge=0, description='Cover format')
    post_item_list_request_type: int = Field(0, ge=0, description='Sort type (deprecated, no longer effective)')


class ListTiktokRepostsConfig(_Config):
    """Get user reposts."""
    operation: Literal["list_tiktok_reposts"] = Field("list_tiktok_reposts", json_schema_extra={"ui:hidden": True})
    secUid: str = Field(..., min_length=1, max_length=4096, description='User secUid')
    cursor: int = Field(0, ge=0, description='Page cursor')
    count: int = Field(20, ge=1, le=100, description='Number per page')
    coverFormat: int = Field(2, ge=0, description='Cover format')


class ListTiktokCommentsConfig(_Config):
    """Get video comments."""
    operation: Literal["list_tiktok_comments"] = Field("list_tiktok_comments", json_schema_extra={"ui:hidden": True})
    aweme_id: str = Field(..., min_length=1, max_length=4096, description='Video id')
    cursor: int = Field(0, ge=0, description='Page cursor')
    count: int = Field(20, ge=1, le=100, description='Number per page')
    current_region: str = Field('', max_length=4096, description='Current region')


class ListTiktokCommentRepliesConfig(_Config):
    """Get video comment replies."""
    operation: Literal["list_tiktok_comment_replies"] = Field("list_tiktok_comment_replies", json_schema_extra={"ui:hidden": True})
    item_id: str = Field(..., min_length=1, max_length=4096, description='Video id')
    comment_id: str = Field(..., min_length=1, max_length=4096, description='Comment id')
    cursor: int = Field(0, ge=0, description='Page cursor')
    count: int = Field(20, ge=1, le=100, description='Number per page')
    current_region: str = Field('', max_length=4096, description='Current region')


class ListTiktokFollowersConfig(_Config):
    """Get user followers."""
    operation: Literal["list_tiktok_followers"] = Field("list_tiktok_followers", json_schema_extra={"ui:hidden": True})
    secUid: str = Field(..., min_length=1, max_length=4096, description='User secUid')
    count: int = Field(30, ge=1, le=100, description='Number per page')
    maxCursor: int = Field(0, ge=0, description='Max cursor')
    minCursor: int = Field(0, ge=0, description='Min cursor')


class ListTiktokFollowingConfig(_Config):
    """Get user followings."""
    operation: Literal["list_tiktok_following"] = Field("list_tiktok_following", json_schema_extra={"ui:hidden": True})
    secUid: str = Field(..., min_length=1, max_length=4096, description='User secUid')
    count: int = Field(30, ge=1, le=100, description='Number per page')
    maxCursor: int = Field(0, ge=0, description='Max cursor')
    minCursor: int = Field(0, ge=0, description='Min cursor')


class SearchTiktokVideosConfig(_Config):
    """Search video."""
    operation: Literal["search_tiktok_videos"] = Field("search_tiktok_videos", json_schema_extra={"ui:hidden": True})
    keyword: str = Field(..., min_length=1, max_length=4096, description='Search keyword')
    count: int = Field(20, ge=1, le=100, description='Number per page')
    offset: int = Field(0, ge=0, description='Page cursor')
    search_id: str = Field('', max_length=4096, description='Search id, need to provide when paging')


class SearchTiktokUsersConfig(_Config):
    """Search user."""
    operation: Literal["search_tiktok_users"] = Field("search_tiktok_users", json_schema_extra={"ui:hidden": True})
    keyword: str = Field(..., min_length=1, max_length=4096, description='Search keyword')
    cursor: int = Field(0, ge=0, description='Page cursor')
    search_id: str = Field('', max_length=4096, description='Search id, need to provide when paging')


class GetTiktokTrendingKeywordsConfig(_Config):
    """Get daily trending search words."""
    operation: Literal["get_tiktok_trending_keywords"] = Field("get_tiktok_trending_keywords", json_schema_extra={"ui:hidden": True})


class GetTiktokHashtagConfig(_Config):
    """Tag Detail."""
    operation: Literal["get_tiktok_hashtag"] = Field("get_tiktok_hashtag", json_schema_extra={"ui:hidden": True})
    tag_name: str = Field(..., min_length=1, max_length=4096, description='Tag name')


class ListTiktokHashtagPostsConfig(_Config):
    """Tag Post."""
    operation: Literal["list_tiktok_hashtag_posts"] = Field("list_tiktok_hashtag_posts", json_schema_extra={"ui:hidden": True})
    challengeID: str = Field(..., min_length=1, max_length=4096, description='Tag ID')
    count: int = Field(30, ge=1, le=100, description='Number per page')
    cursor: int = Field(0, ge=0, description='Page cursor')


class GetTiktokLiveConfig(_Config):
    """Get user live details."""
    operation: Literal["get_tiktok_live"] = Field("get_tiktok_live", json_schema_extra={"ui:hidden": True})
    uniqueId: str = Field(..., min_length=1, max_length=4096, description='User uniqueId')


class GetInstagramProfileConfig(_Config):
    """Get user info."""
    operation: Literal["get_instagram_profile"] = Field("get_instagram_profile", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=4096, description='Username')


class ListInstagramPostsConfig(_Config):
    """Get user posts."""
    operation: Literal["list_instagram_posts"] = Field("list_instagram_posts", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=4096, description='Username')
    pagination_token: str | None = Field(None, max_length=4096, description='Pagination token')


class GetInstagramPostConfig(_Config):
    """Get post info."""
    operation: Literal["get_instagram_post"] = Field("get_instagram_post", json_schema_extra={"ui:hidden": True})
    code_or_url: str = Field(..., min_length=1, max_length=4096, description='Post shortcode or URL')


class SearchYoutubeVideosConfig(_Config):
    """Search video."""
    operation: Literal["search_youtube_videos"] = Field("search_youtube_videos", json_schema_extra={"ui:hidden": True})
    search_query: str = Field(..., min_length=1, max_length=4096, description='Search keyword')
    language_code: str = Field('en', max_length=4096, description='Language code')
    order_by: str = Field('this_month', max_length=4096, description='Order by')
    country_code: str = Field('us', max_length=4096, description='Country code')
    continuation_token: str | None = Field(None, max_length=4096, description='Pagination token')


class ExtractTiktokVideoIdsConfig(_Config):
    """Extract list video id."""
    operation: Literal["extract_tiktok_video_ids"] = Field("extract_tiktok_video_ids", json_schema_extra={"ui:hidden": True})
    urls: list[str] = Field(..., min_length=1, max_length=20, description="TikTok URLs to extract; returns IDs or original URLs for unsuccessful extractions.")


class ExtractTiktokUserIdsConfig(_Config):
    """Extract list user sec_user_id."""
    operation: Literal["extract_tiktok_user_ids"] = Field("extract_tiktok_user_ids", json_schema_extra={"ui:hidden": True})
    urls: list[str] = Field(..., min_length=1, max_length=10, description="TikTok URLs to extract; returns IDs or original URLs for unsuccessful extractions.")


class ExtractTiktokUsernamesConfig(_Config):
    """Get list unique_id."""
    operation: Literal["extract_tiktok_usernames"] = Field("extract_tiktok_usernames", json_schema_extra={"ui:hidden": True})
    urls: list[str] = Field(..., min_length=1, max_length=20, description="TikTok URLs to extract; returns IDs or original URLs for unsuccessful extractions.")


TikHubConfig = Annotated[Union[
    GetAccountConfig,
    GetDailyUsageConfig,
    GetTiktokProfileConfig,
    GetTiktokVideoConfig,
    ListTiktokPostsConfig,
    ListTiktokRepostsConfig,
    ListTiktokCommentsConfig,
    ListTiktokCommentRepliesConfig,
    ListTiktokFollowersConfig,
    ListTiktokFollowingConfig,
    SearchTiktokVideosConfig,
    SearchTiktokUsersConfig,
    GetTiktokTrendingKeywordsConfig,
    GetTiktokHashtagConfig,
    ListTiktokHashtagPostsConfig,
    GetTiktokLiveConfig,
    GetInstagramProfileConfig,
    ListInstagramPostsConfig,
    GetInstagramPostConfig,
    SearchYoutubeVideosConfig,
    ExtractTiktokVideoIdsConfig,
    ExtractTiktokUserIdsConfig,
    ExtractTiktokUsernamesConfig
], Field(discriminator="operation")]


class TikHubFullConfig(NodeConfig[TikHubConfig, TikHubCredential]):
    pass


OPERATIONS = {'get_account': ('GET', '/api/v1/tikhub/user/get_user_info'),
 'get_daily_usage': ('GET', '/api/v1/tikhub/user/get_user_daily_usage'),
 'get_tiktok_profile': ('GET', '/api/v1/tiktok/web/fetch_user_profile'),
 'get_tiktok_video': ('GET', '/api/v1/tiktok/web/fetch_post_detail'),
 'list_tiktok_posts': ('GET', '/api/v1/tiktok/web/fetch_user_post'),
 'list_tiktok_reposts': ('GET', '/api/v1/tiktok/web/fetch_user_repost'),
 'list_tiktok_comments': ('GET', '/api/v1/tiktok/web/fetch_post_comment'),
 'list_tiktok_comment_replies': ('GET', '/api/v1/tiktok/web/fetch_post_comment_reply'),
 'list_tiktok_followers': ('GET', '/api/v1/tiktok/web/fetch_user_fans'),
 'list_tiktok_following': ('GET', '/api/v1/tiktok/web/fetch_user_follow'),
 'search_tiktok_videos': ('GET', '/api/v1/tiktok/web/fetch_search_video'),
 'search_tiktok_users': ('GET', '/api/v1/tiktok/web/fetch_search_user'),
 'get_tiktok_trending_keywords': ('GET', '/api/v1/tiktok/web/fetch_trending_searchwords'),
 'get_tiktok_hashtag': ('GET', '/api/v1/tiktok/web/fetch_tag_detail'),
 'list_tiktok_hashtag_posts': ('GET', '/api/v1/tiktok/web/fetch_tag_post'),
 'get_tiktok_live': ('GET', '/api/v1/tiktok/web/fetch_user_live_detail'),
 'get_instagram_profile': ('GET', '/api/v1/instagram/v2/fetch_user_info'),
 'list_instagram_posts': ('GET', '/api/v1/instagram/v2/fetch_user_posts'),
 'get_instagram_post': ('GET', '/api/v1/instagram/v2/fetch_post_info'),
 'search_youtube_videos': ('GET', '/api/v1/youtube/web/search_video'),
 'extract_tiktok_video_ids': ('POST', '/api/v1/tiktok/web/get_all_aweme_id'),
 'extract_tiktok_user_ids': ('POST', '/api/v1/tiktok/web/get_all_sec_user_id'),
 'extract_tiktok_usernames': ('POST', '/api/v1/tiktok/web/get_all_unique_id')}


class TikHubNode(WorkflowNode):
    integration_type = "automation-tik-hub"
    connection_evidence = ConnectionEvidence(noun="Tik Hub account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return TikHubFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Tik Hub API token")
        method, path = OPERATIONS[config.operation]
        params = {key: value for key, value in config.model_dump(exclude={"operation"}, exclude_none=True).items() if value != ""}
        kwargs = {"json": params["urls"]} if method == "POST" else {"params": params}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected a Tik Hub response object")
        if payload.get("code", 200) != 200:
            message = str(payload.get("message", "Tik Hub rejected the request"))
            raise ValueError(message.replace(credential.api_token, "[redacted]"))
        if config.operation == "get_account":
            user = payload.get("user_data")
            if not isinstance(user, dict) or not isinstance(user.get("email"), str) or not user["email"]:
                raise ValueError("Tik Hub did not return an account email")
            return {"status": "success", "name": user["email"], "data": user}
        # Preserve the response envelope, including provider pagination cursors.
        return {"status": "success", "data": payload}
