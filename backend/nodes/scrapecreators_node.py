"""Scrapecreators public social-data reads and account usage (OpenAPI 1.0.0).

Each operation fetches one provider page. Preserve the provider's cursors and
response fields; no media downloads, automatic pagination or social mutations.
"""
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE_URL = "https://api.scrapecreators.com"


class ScrapecreatorsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Scrapecreators API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.scrapecreators.com/",
            "x-credential-instructions": "Copy your API key from the Scrapecreators dashboard. NoClick sends it as x-api-key to api.scrapecreators.com. Scraping requests may consume credits; connection checks read your account credit balance.",
        })
    credential_type: Literal["scrapecreators_api_key"] = Field("scrapecreators_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def require_identifier(self):
        alternatives = {
            "get_tiktok_profile": ("handle", "user_id"),
            "get_youtube_channel": ("handle", "channelId", "url"),
            "get_youtube_videos": ("handle", "channelId"),
        }.get(self.operation)
        if alternatives and not any(getattr(self, key) for key in alternatives):
            raise ValueError("Provide one of: " + ", ".join(alternatives))
        return self


class GetCreditBalanceConfig(_Input):
    """Get credit balance (Scrape Creators). Returns one page of provider JSON in data."""
    operation: Literal["get_credit_balance"] = Field("get_credit_balance", json_schema_extra={"ui:hidden": True})

class GetRequestHistoryConfig(_Input):
    """Get request history (Scrape Creators). Returns one page of provider JSON in data."""
    operation: Literal["get_request_history"] = Field("get_request_history", json_schema_extra={"ui:hidden": True})
    endpoint: str | None = Field(None, description='Filter by endpoint name (partial match)', min_length=1)
    statusCode: str | None = Field(None, description='Filter by HTTP status code', min_length=1)
    page: str | None = Field(None, description='Page number for pagination (max 100)', min_length=1)

class GetDailyUsageConfig(_Input):
    """Get daily usage (Scrape Creators). Returns one page of provider JSON in data."""
    operation: Literal["get_daily_usage"] = Field("get_daily_usage", json_schema_extra={"ui:hidden": True})

class GetMostUsedRoutesConfig(_Input):
    """Get most used routes (Scrape Creators). Returns one page of provider JSON in data."""
    operation: Literal["get_most_used_routes"] = Field("get_most_used_routes", json_schema_extra={"ui:hidden": True})
    start_time: str | None = Field(None, description='Start of time range (ISO 8601 format)', min_length=1)
    end_time: str | None = Field(None, description='End of time range (ISO 8601 format)', min_length=1)

class GetTiktokProfileConfig(_Input):
    """Profile (TikTok). Returns one page of provider JSON in data."""
    operation: Literal["get_tiktok_profile"] = Field("get_tiktok_profile", json_schema_extra={"ui:hidden": True})
    handle: str | None = Field(None, description='TikTok handle. You can pass handle or user_id.', min_length=1)
    user_id: str | None = Field(None, description='TikTok user id.', min_length=1)
    cache_max_age: Literal['1d', '3d', '7d', '14d', '30d'] | None = Field(None, description='If we have a response in the cache that is this many days old or newer, return the cached response (0 credits, with "cached": true and a "cached_at" timestamp). Otherwise, scrape a live result (1 credit). [See the Caching page for details.](https://docs.scrapecreators.com/caching)')

class GetTiktokVideosConfig(_Input):
    """Read one TikTok video-feed page. Feeds may omit posts; absence does not prove deletion. Keep region, sort_by and include_pinned unchanged while paginating."""
    operation: Literal["get_tiktok_videos"] = Field("get_tiktok_videos", json_schema_extra={"ui:hidden": True})
    handle: str = Field(..., description='TikTok handle', min_length=1)
    user_id: str | None = Field(None, description='TikTok user id. Use this for faster responses.', min_length=1)
    sort_by: Literal['latest', 'popular'] | None = Field(None, description='What to sort by')
    region: str | None = Field(None, description='Country code passed to the profile-feed source. Defaults to US. If a profile should have videos but returns none, try another relevant two-letter country code. Changing this value does not guarantee that region-restricted posts will appear.', min_length=1)
    include_pinned: bool | None = Field(None, description='Whether to include pinned posts. Defaults to true. Set to false to exclude posts marked as pinned, including with trim=true. Keep this value unchanged while paginating. Filtering can produce shorter or empty pages; follow has_more and max_cursor. Successful pages still cost 1 credit, including empty results.')
    trim: bool | None = Field(None, description='Set to true for a trimmed down version of the response')
    max_cursor: str | None = Field(None, description="Cursor to get more videos. Get 'max_cursor' from previous response.", min_length=1)

class GetTiktokVideoConfig(_Input):
    """Video Info (TikTok). Returns one page of provider JSON in data."""
    operation: Literal["get_tiktok_video"] = Field("get_tiktok_video", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='TikTok video or photo/slideshow URL', min_length=1)
    region: str | None = Field(None, description="Two-letter country code passed to the primary post source. Defaults to US. Try the creator's country if a post is unavailable. This does not guarantee a matching browser/proxy country or complete retrieval; the fallback source does not receive this parameter.", min_length=1)
    get_transcript: bool | None = Field(None, description='Native captions are opt-in via get_transcript=true and are included in the existing base endpoint price. This detail endpoint does not use AI transcription or an AI fallback; missing captions return no transcript. For AI fallback, use /v1/tiktok/video/transcript.')
    trim: bool | None = Field(None, description='Set to true to get a trimmed response')
    download_media: bool | None = Field(None, description='Set to true to download the video/images and get back permanent Supabase URLs. Costs 10 credits if media is found, 1 credit otherwise.')
    cache_max_age: Literal['1d', '3d', '7d', '14d', '30d'] | None = Field(None, description='If we have a response in the cache that is this many days old or newer, return the cached response (0 credits, with "cached": true and a "cached_at" timestamp). Otherwise, scrape a live result (1 credit). [See the Caching page for details.](https://docs.scrapecreators.com/caching)')

class GetTiktokTranscriptConfig(_Input):
    """Transcript (TikTok). Returns one page of provider JSON in data."""
    operation: Literal["get_tiktok_transcript"] = Field("get_tiktok_transcript", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='TikTok video URL', min_length=1)
    language: str | None = Field(None, description="Language of the transcript. 2 letter language code, ie 'en', 'es', 'fr', 'de', 'it', 'ja', 'ko', 'zh'", min_length=1)
    allow_long_transcription: bool | None = Field(None, description="Paid opt-in, enabled only by the literal query value 'true' (allow_long_transcription=true). Defaults to false when omitted; other values do not enable paid mode. By default, successful AI transcription of videos up to 120 seconds (two minutes, inclusive) costs a flat 1 credit per request. Over 120 seconds, videos cannot be AI-transcribed by default. Set allow_long_transcription=true to opt into paid AI with no fixed duration cap: ALL successful AI transcriptions in this mode cost 10 credits per started minute, including short videos: 10 * ceil(duration_seconds / 60). For example, 177 seconds costs 30 credits and an opted-in 60 seconds costs 10 credits. Empty AI results and errors cost 0 credits for AI transcription. This flag does not force AI and does not enable transcription or AI fallback by itself. Keep get_transcript=true or use_ai_as_fallback=true where required by the endpoint. Returned native captions still cost 1 credit on dedicated transcript routes, even for long videos with this flag; on detail routes they leave the base price unchanged. These routes remain synchronous. Allow at least 30 seconds on your client. Paid long transcription can exceed resource limits or timeouts, so successful transcription of long videos is not guaranteed.")
    use_ai_as_fallback: str | None = Field(None, description="Set to 'true' to use paid AI only when existing captions are unavailable. Defaults to false. By default, successful AI transcription of videos up to 120 seconds (two minutes, inclusive) costs a flat 1 credit per request. Over 120 seconds, videos cannot be AI-transcribed by default. Set allow_long_transcription=true to opt into paid AI with no fixed duration cap: ALL successful AI transcriptions in this mode cost 10 credits per started minute, including short videos: 10 * ceil(duration_seconds / 60). For example, 177 seconds costs 30 credits and an opted-in 60 seconds costs 10 credits. Empty AI results and errors cost 0 credits for AI transcription. These routes remain synchronous. Allow at least 30 seconds on your client. Paid long transcription can exceed resource limits or timeouts, so successful transcription of long videos is not guaranteed.", min_length=1)

class GetTiktokCommentsConfig(_Input):
    """Comments (TikTok). Returns one page of provider JSON in data."""
    operation: Literal["get_tiktok_comments"] = Field("get_tiktok_comments", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='TikTok video URL', min_length=1)
    trim: bool | None = Field(None, description='Set to true to get a trimmed response')
    cursor: float | None = Field(None, description="Cursor to get more comments. Get 'cursor' from previous response.")

class SearchTiktokVideosConfig(_Input):
    """Search by Keyword (TikTok). Returns one page of provider JSON in data."""
    operation: Literal["search_tiktok_videos"] = Field("search_tiktok_videos", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description='Keyword to search for', min_length=1)
    date_posted: Literal['yesterday', 'this-week', 'this-month', 'last-3-months', 'last-6-months', 'all-time'] | None = Field(None, description='Time Frame')
    sort_by: Literal['relevance', 'most-liked', 'date-posted'] | None = Field(None, description='Sort by')
    region: str | None = Field(None, description="Note, this doesn't filter the tiktoks only in a specfic region, it puts the proxy there. Use it in case you want to scrape posts only available for some country. Use 2 letter country codes like US, GB, FR, etc", min_length=1)
    trim: bool | None = Field(None, description='Set to true to get a trimmed response')
    cursor: float | None = Field(None, description="Cursor to get more videos. Get 'cursor' from previous response.")

class GetInstagramProfileConfig(_Input):
    """Profile (Instagram). Returns one page of provider JSON in data."""
    operation: Literal["get_instagram_profile"] = Field("get_instagram_profile", json_schema_extra={"ui:hidden": True})
    handle: str = Field(..., description='Instagram handle', min_length=1)
    trim: bool | None = Field(None, description='Set to true to get a trimmed response')
    cache_max_age: Literal['1d', '3d', '7d', '14d', '30d'] | None = Field(None, description='If we have a response in the cache that is this many days old or newer, return the cached response (0 credits, with "cached": true and a "cached_at" timestamp). Otherwise, scrape a live result (1 credit). [See the Caching page for details.](https://docs.scrapecreators.com/caching)')

class GetInstagramPostsConfig(_Input):
    """Posts (Instagram). Returns one page of provider JSON in data."""
    operation: Literal["get_instagram_posts"] = Field("get_instagram_posts", json_schema_extra={"ui:hidden": True})
    handle: str = Field(..., description='Instagram handle', min_length=1)
    require_play_counts: bool | None = Field(None, description="Only the literal query value 'true' enables this check. It requires play_count on each returned video post; a real 0 is valid. It does not require ig_play_count or view counts, or counts on photos. If a required play_count is missing or null, the request returns an error without charging credits instead of a paid partial success. With the default false, counts remain best-effort: usable posts are still billable even with missing play counts. Retrying does not guarantee that Instagram will return the missing counts. [Why counts can be missing](https://scrapecreators.com/blog/instagram-play-counts-missing).")
    trim: bool | None = Field(None, description='Set to true to get a trimmed response')
    next_max_id: str | None = Field(None, description='Cursor to get next page of results.', min_length=1)

class GetInstagramPostConfig(_Input):
    """Post/Reel Info (Instagram). Returns one page of provider JSON in data."""
    operation: Literal["get_instagram_post"] = Field("get_instagram_post", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='Instagram post or reel URL', min_length=1)
    region: str | None = Field(None, description='2 letter country code to set the proxy in', min_length=1)
    trim: bool | None = Field(None, description='Set to true to get a trimmed response')
    download_media: bool | None = Field(None, description='Set to true to download the video/images and get back permanent Supabase URLs. Costs 10 credits if media is found, 1 credit otherwise.')
    include_play_count: bool | None = Field(None, description='Set to false to omit `video_play_count` and skip its additional fetch for a faster response. Defaults to true.')
    cache_max_age: Literal['1d', '3d', '7d', '14d', '30d'] | None = Field(None, description='If we have a response in the cache that is this many days old or newer, return the cached response (0 credits, with "cached": true and a "cached_at" timestamp). Otherwise, scrape a live result (1 credit). [See the Caching page for details.](https://docs.scrapecreators.com/caching)')

class GetInstagramCommentsConfig(_Input):
    """Comments (Instagram). Returns one page of provider JSON in data."""
    operation: Literal["get_instagram_comments"] = Field("get_instagram_comments", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='The URL of the post or reel to get comments from', min_length=1)
    include_replies: bool | None = Field(None, description='Set to true to include replies for every returned comment. Costs 15 credits when comments are returned, even if no replies are found; successful pages with no comments cost 0 credits. This is much slower and may time out at 29 seconds.')
    cursor: str | None = Field(None, description="The cursor to get more comments. Get 'cursor' from previous response.", min_length=1)

class SearchInstagramProfilesConfig(_Input):
    """Search Instagram Profiles (Instagram). Returns one page of provider JSON in data."""
    operation: Literal["search_instagram_profiles"] = Field("search_instagram_profiles", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description='The profile name or username to search for.', min_length=1)

class GetYoutubeChannelConfig(_Input):
    """Channel Details (YouTube). Returns one page of provider JSON in data."""
    operation: Literal["get_youtube_channel"] = Field("get_youtube_channel", json_schema_extra={"ui:hidden": True})
    channelId: str | None = Field(None, description='YouTube channel ID. Can pass a channelId, handle or url', min_length=1)
    handle: str | None = Field(None, description='YouTube channel handle. Can pass a channelId, handle or url', min_length=1)
    url: str | None = Field(None, description='YouTube channel URL. Can pass a channelId, handle or url', min_length=1)
    cache_max_age: Literal['1d', '3d', '7d', '14d', '30d'] | None = Field(None, description='If we have a response in the cache that is this many days old or newer, return the cached response (0 credits, with "cached": true and a "cached_at" timestamp). Otherwise, scrape a live result (1 credit). [See the Caching page for details.](https://docs.scrapecreators.com/caching)')

class GetYoutubeVideosConfig(_Input):
    """Channel Videos (YouTube). Returns one page of provider JSON in data."""
    operation: Literal["get_youtube_videos"] = Field("get_youtube_videos", json_schema_extra={"ui:hidden": True})
    channelId: str | None = Field(None, description='YouTube channel ID', min_length=1)
    handle: str | None = Field(None, description='YouTube channel handle', min_length=1)
    sort: Literal['latest', 'popular'] | None = Field(None, description='Sort by latest or popular')
    includeExtras: str | None = Field(None, description='This will get you the like + comment count and the description. To get the full details of the video, use the /v1/youtube/video endpoint. Honestly, if you use this param, the error rate is higher. We might deprecate this param in the future.', min_length=1)
    continuationToken: str | None = Field(None, description="Continuation token to get more videos. Get 'continuationToken' from previous response.", min_length=1)

class GetYoutubeVideoConfig(_Input):
    """Video/Short Details (YouTube). Returns one page of provider JSON in data."""
    operation: Literal["get_youtube_video"] = Field("get_youtube_video", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='YouTube video or short URL', min_length=1)
    language: str | None = Field(None, description="Preferred response language (mapped to Accept-Language header; not guaranteed due to YouTube localization behavior). 2 letter language code, ie 'en', 'es', 'fr' etc.", min_length=1)
    cache_max_age: Literal['1d', '3d', '7d', '14d', '30d'] | None = Field(None, description='If we have a response in the cache that is this many days old or newer, return the cached response (0 credits, with "cached": true and a "cached_at" timestamp). Otherwise, scrape a live result (1 credit). [See the Caching page for details.](https://docs.scrapecreators.com/caching)')

class GetYoutubeTranscriptConfig(_Input):
    """Transcript (YouTube). Returns one page of provider JSON in data."""
    operation: Literal["get_youtube_transcript"] = Field("get_youtube_transcript", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='YouTube video or short URL', min_length=1)
    language: str | None = Field(None, description="Language code, ie 'en', 'es', 'fr' or 'en-US'. Overrides the default track selection unless original_audio=true. If omitted, prefers captions matching the original spoken language when YouTube identifies the original audio. If that metadata is unavailable or ambiguous, prefers an auto-generated caption, otherwise the first caption track. If the requested or identified original language has no matching captions, the transcript will be null and no credits are charged.", min_length=1)
    original_audio: bool | None = Field(None, description='Set to true to return captions only in the original spoken language identified by YouTube. Takes precedence over language. If the original audio cannot be reliably identified or has no matching captions, transcript, transcript_only_text, and language are null and no credits are charged. No extra lookup or credit cost; a returned transcript costs the usual 1 credit. Omit or set to false for the existing default selection.')
    cache_max_age: Literal['1d', '3d', '7d', '14d', '30d'] | None = Field(None, description='If we have a response in the cache that is this many days old or newer, return the cached response (0 credits, with "cached": true and a "cached_at" timestamp). Otherwise, scrape a live result (1 credit). [See the Caching page for details.](https://docs.scrapecreators.com/caching)')

class SearchYoutubeConfig(_Input):
    """Search (YouTube). Returns one page of provider JSON in data."""
    operation: Literal["search_youtube"] = Field("search_youtube", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description='Search query. For stricter title matching, use YouTube\'s intitle: operator, for example intitle:"Foursquare Swarm". Quoted queries by themselves may still be broadened by YouTube when no fresh exact matches are available.', min_length=1)
    uploadDate: Literal['today', 'this_week', 'this_month', 'this_year'] | None = Field(None, description='Upload date')
    sortBy: Literal['relevance', 'popular'] | None = Field(None, description='Sort by')
    type: Literal['videos', 'shorts', 'channels', 'playlists'] | None = Field(None, description='Type of content to search for')
    duration: Literal['under_3_min', 'between_3_and_20_min', 'over_20_min'] | None = Field(None, description='Duration of the video. Only applies to videos (not shorts).')
    region: str | None = Field(None, description='2 letter country code of the country to put the proxy in.', min_length=1)
    includeExtras: str | None = Field(None, description='This will get you the like + comment count and the description. To get the full details of the video, use the /v1/youtube/video endpoint. *This will slow down the response slightly.*', min_length=1)
    continuationToken: str | None = Field(None, description="Continuation token to get more videos. Get 'continuationToken' from previous response.", min_length=1)

class GetLinkedinProfileConfig(_Input):
    """Person's Profile (LinkedIn). Returns one page of provider JSON in data."""
    operation: Literal["get_linkedin_profile"] = Field("get_linkedin_profile", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='The URL of the LinkedIn profile to get', min_length=1)

class GetLinkedinCompanyConfig(_Input):
    """Company Page (LinkedIn). Returns one page of provider JSON in data."""
    operation: Literal["get_linkedin_company"] = Field("get_linkedin_company", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., description='The URL of the LinkedIn company page to get', min_length=1)

class SearchTwitterPostsConfig(_Input):
    """Search Posts (Twitter). Returns one page of provider JSON in data."""
    operation: Literal["search_twitter_posts"] = Field("search_twitter_posts", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description='Keyword or phrase to search for in Google-indexed public X/Twitter posts', min_length=1)
    cursor: str | None = Field(None, description='Pass the cursor returned by the previous response. Supported page cursors are 1 through 11. A null response cursor means there are no more pages.', min_length=1)

class SearchRedditConfig(_Input):
    """Search (Reddit). Returns one page of provider JSON in data."""
    operation: Literal["search_reddit"] = Field("search_reddit", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description='Search query', min_length=1)
    filter: Literal['posts', 'comments'] | None = Field(None, description='Search posts or comments')
    sort: Literal['relevance', 'new', 'top', 'comment_count'] | None = Field(None, description='Sort by. Comment search supports relevance, new, and top; comment_count is for post search only.')
    timeframe: Literal['all', 'day', 'week', 'month', 'year'] | None = Field(None, description='Post search timeframe')
    trim: bool | None = Field(None, description='Set to true for a trimmed down version of the response')
    after: str | None = Field(None, description='Used to paginate to next page', min_length=1)


ScrapecreatorsConfig = Annotated[Union[
    GetCreditBalanceConfig,
    GetRequestHistoryConfig,
    GetDailyUsageConfig,
    GetMostUsedRoutesConfig,
    GetTiktokProfileConfig,
    GetTiktokVideosConfig,
    GetTiktokVideoConfig,
    GetTiktokTranscriptConfig,
    GetTiktokCommentsConfig,
    SearchTiktokVideosConfig,
    GetInstagramProfileConfig,
    GetInstagramPostsConfig,
    GetInstagramPostConfig,
    GetInstagramCommentsConfig,
    SearchInstagramProfilesConfig,
    GetYoutubeChannelConfig,
    GetYoutubeVideosConfig,
    GetYoutubeVideoConfig,
    GetYoutubeTranscriptConfig,
    SearchYoutubeConfig,
    GetLinkedinProfileConfig,
    GetLinkedinCompanyConfig,
    SearchTwitterPostsConfig,
    SearchRedditConfig
], Field(discriminator="operation")]


class ScrapecreatorsFullConfig(NodeConfig[ScrapecreatorsConfig, ScrapecreatorsAPIKeyCredential]):
    pass


ROUTES = {'get_credit_balance': '/v1/account/credit-balance',
 'get_request_history': '/v1/account/get-api-usage',
 'get_daily_usage': '/v1/account/get-daily-usage-count',
 'get_most_used_routes': '/v1/account/get-most-used-routes',
 'get_tiktok_profile': '/v1/tiktok/profile',
 'get_tiktok_videos': '/v3/tiktok/profile/videos',
 'get_tiktok_video': '/v2/tiktok/video',
 'get_tiktok_transcript': '/v1/tiktok/video/transcript',
 'get_tiktok_comments': '/v1/tiktok/video/comments',
 'search_tiktok_videos': '/v1/tiktok/search/keyword',
 'get_instagram_profile': '/v1/instagram/profile',
 'get_instagram_posts': '/v2/instagram/user/posts',
 'get_instagram_post': '/v1/instagram/post',
 'get_instagram_comments': '/v2/instagram/post/comments',
 'search_instagram_profiles': '/v1/instagram/search/profiles',
 'get_youtube_channel': '/v1/youtube/channel',
 'get_youtube_videos': '/v1/youtube/channel-videos',
 'get_youtube_video': '/v1/youtube/video',
 'get_youtube_transcript': '/v1/youtube/video/transcript',
 'search_youtube': '/v1/youtube/search',
 'get_linkedin_profile': '/v1/linkedin/profile',
 'get_linkedin_company': '/v1/linkedin/company',
 'search_twitter_posts': '/v1/twitter/search/posts',
 'search_reddit': '/v1/reddit/search'}


class ScrapecreatorsNode(WorkflowNode):
    integration_type = "automation-scrapecreators"
    connection_evidence = ConnectionEvidence(
        noun="API credit balance", operation="get_credit_balance",
    )

    @classmethod
    def get_config_model(cls):
        return ScrapecreatorsFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Scrapecreators API key")
        config = self.config.config
        api_key = self.config.credentials.api_key
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        # Query booleans are lowercase in the published wire examples.
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        try:
            async with guarded_async_client(timeout=90, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", BASE_URL + ROUTES[config.operation],
                    params=params, headers={"x-api-key": api_key, "Accept": "application/json"})
            if response.status_code != 200:
                message = "Scrapecreators request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        value = error.get("message") or error.get("error")
                        if isinstance(value, str):
                            message = value.replace(api_key, "[redacted]")[:2000]
                except ValueError:
                    pass
                return {"status": "error", "error": f"{message} (HTTP {response.status_code})", "http_status": response.status_code}
            body = response.json()
            if not isinstance(body, (dict, list)):
                raise ValueError("Expected a Scrapecreators JSON object or array")
            if isinstance(body, dict) and (body.get("success") is False or body.get("error")):
                message = body.get("message") or body.get("error") or "Scrapecreators reported failure"
                return {"status": "error", "error": str(message).replace(api_key, "[redacted]")[:2000]}
            if config.operation == "get_credit_balance":
                if not isinstance(body, dict) or type(body.get("creditCount")) not in (int, float):
                    raise ValueError("Scrapecreators credit balance is missing")
                return {"status": "success", "data": body,
                    "items": [{"name": f"{body['creditCount']} API credits"}]}
            return {"status": "success", "data": body}
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "Scrapecreators could not be reached"}
        except ValueError as exc:
            return {"status": "error", "error": str(exc).replace(api_key, "[redacted]")}
