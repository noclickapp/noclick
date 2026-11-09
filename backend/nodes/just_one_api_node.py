"""Just One API data collection and image conversion, pinned to the published v0 API.

Contract: https://docs.justoneapi.com/openapi.json
Authentication and business errors: https://docs.justoneapi.com/en/usage
Each operation makes one request. Pagination fields are explicit provider state;
results preserve data and continuation fields without claiming a complete crawl.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://api.justoneapi.com"
CREDENTIAL_TYPE = "just_one_api_token"


class JustOneApiTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Just One API Token",
        extra="ignore",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.justoneapi.com/",
            "x-credential-instructions": "Paste your Just One API access token from the dashboard. Requests use your API balance. Connecting reads Weibo hot search to check token reachability; it does not identify your account.",
        },
    )
    credential_type: Literal["just_one_api_token"] = Field(
        "just_one_api_token", json_schema_extra={"ui:hidden": True}
    )
    token: str = Field(
        ...,
        title="API token",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={
            "ui:widget": "password",
            "ui:help": "Paste only the token, without a URL or header prefix.",
        },
    )

    @field_validator("token", mode="before")
    @classmethod
    def clean_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("Paste the token without whitespace or a header prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def bounded_text(cls, value):
        if isinstance(value, str) and (
            len(value) > 16384 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
        ):
            raise ValueError("Use a bounded single-line value")
        return value


class GetWeiboHotSearchConfig(_Operation):
    "Retrieves the current Weibo hot-search ranking. Use it to identify trending topics for newsroom monitoring, content planning, or timely topic discovery."
    operation: Literal["get_weibo_hot_search"] = Field(
        "get_weibo_hot_search",
        title="Get Weibo Hot Search",
        json_schema_extra={"ui:hidden": True},
    )


class SearchDouyinVideosConfig(_Operation):
    "Searches Douyin (TikTok China) videos by keyword with sort, publish-time, duration, and page filters; later pages require the previous search ID. Use it to support content discovery and trend research."
    operation: Literal["search_douyin_videos"] = Field(
        "search_douyin_videos",
        title="Search Douyin Videos",
        json_schema_extra={"ui:hidden": True},
    )
    keyword: str = Field(..., description="The search keyword.", min_length=1)
    sort_type: Literal["_0", "_1", "_2"] = Field(
        "_0",
        description="Sorting criteria for search results.\n\nAvailable Values:\n- `_0`: General\n- `_1`: More likes\n- `_2`: Newest",
    )
    publish_time: Literal["_0", "_1", "_7", "_180"] = Field(
        "_0",
        description="Filter by video publish time range.\n\nAvailable Values:\n- `_0`: No Limit\n- `_1`: Last 24 Hours\n- `_7`: Last 7 Days\n- `_180`: Last 6 Months",
    )
    duration: Literal["_0", "_1", "_2", "_3"] = Field(
        "_0",
        description="Filter by video duration.\n\nAvailable Values:\n- `_0`: No Limit\n- `_1`: Under 1 Minute\n- `_2`: 1-5 Minutes\n- `_3`: Over 5 Minutes",
    )
    page: int = Field(1, description="Page number (starting from 1).", ge=1, le=1000000)
    search_id: str | None = Field(
        None,
        description="Search ID; required for pages > 1. Use data.business_config.next_page.search_id from the previous response, and stop paging when data.business_config.has_more is 0.",
    )

    @model_validator(mode="after")
    def pagination_state(self):
        if self.page > 1 and not self.search_id:
            raise ValueError(
                "Copy search_id from the previous response for pages after the first"
            )
        return self


class GetDouyinVideoConfig(_Operation):
    "Retrieves details for a Douyin (TikTok China) video by video ID. Use it to look up a known video before content review, archiving, or related analysis."
    operation: Literal["get_douyin_video"] = Field(
        "get_douyin_video",
        title="Get Douyin Video",
        json_schema_extra={"ui:hidden": True},
    )
    video_id: str = Field(
        ...,
        description="The unique video identifier (aweme_id or model_id).",
        min_length=1,
    )


class GetDouyinUserConfig(_Operation):
    "Retrieves a Douyin (TikTok China) user profile by secUid. Use it to review a known creator or account before monitoring related content or conducting account research."
    operation: Literal["get_douyin_user"] = Field(
        "get_douyin_user",
        title="Get Douyin User",
        json_schema_extra={"ui:hidden": True},
    )
    sec_uid: str = Field(
        ..., description="The unique user ID (sec_uid) on Douyin.", min_length=1
    )


class SearchRednoteNotesConfig(_Operation):
    "Searches Xiaohongshu (RedNote) notes through the mobile-app search flow with pagination, sorting, note-type, and time filters. Use it to support iterative topic research and filtered content discovery."
    operation: Literal["search_rednote_notes"] = Field(
        "search_rednote_notes",
        title="Search Rednote Notes",
        json_schema_extra={"ui:hidden": True},
    )
    keyword: str = Field(..., description="Search keyword.", min_length=1)
    page: int = Field(1, description="Page number for pagination.", ge=1, le=1000000)
    sort_type: Literal[
        "general",
        "popularity_descending",
        "time_descending",
        "comment_descending",
        "collect_descending",
    ] = Field(
        "general",
        description="Sort order for the result set.\n\nAvailable Values:\n- `general`: General\n- `popularity_descending`: Popularity Descending\n- `time_descending`: Time Descending\n- `comment_descending`: Comment Descending\n- `collect_descending`: Collect Descending",
    )
    note_type: Literal["ALL", "VIDEO_NOTE", "NORMAL_NOTE"] = Field(
        "ALL",
        description="Note type filter.\n\nAvailable Values:\n- `ALL`: No Limit\n- `VIDEO_NOTE`: Video Note\n- `NORMAL_NOTE`: Normal Note",
    )
    time_filter: Literal["ALL", "ONE_DAY", "ONE_WEEK", "HALF_YEAR"] = Field(
        "ALL",
        description="Publish time filter.\n\nAvailable Values:\n- `ALL`: No Limit\n- `ONE_DAY`: Within one day\n- `ONE_WEEK`: Within one week\n- `HALF_YEAR`: Within half a year",
    )


class GetRednoteNoteConfig(_Operation):
    "Retrieves Xiaohongshu (RedNote) video-note details by note ID. Use it to look up and process a known video note."
    operation: Literal["get_rednote_note"] = Field(
        "get_rednote_note",
        title="Get Rednote Note",
        json_schema_extra={"ui:hidden": True},
    )
    note_id: str = Field(
        ..., description="Unique note identifier on Xiaohongshu.", min_length=1
    )


class GetWeiboPostConfig(_Operation):
    "Retrieves details for a Weibo post identified by its post ID. Use it to look up a known post for content review, archiving, or related engagement analysis."
    operation: Literal["get_weibo_post"] = Field(
        "get_weibo_post", title="Get Weibo Post", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., description="Weibo post ID.", min_length=1)


class SearchTaobaoProductsConfig(_Operation):
    "Searches Taobao and Tmall products by keyword with page-based pagination and returns results sorted by sales. Use it to discover popular products for ecommerce research, catalog analysis, or product selection."
    operation: Literal["search_taobao_products"] = Field(
        "search_taobao_products",
        title="Search Taobao Products",
        json_schema_extra={"ui:hidden": True},
    )
    keyword: str = Field(..., description="Search keyword.", min_length=1)
    page: int = Field(
        1, description="Page number for pagination, starting from 1.", ge=1, le=1000000
    )


class GetTaobaoProductConfig(_Operation):
    "Retrieves Taobao or Tmall product details by item ID through the V9 endpoint. Use it to perform direct product lookup for catalog research, product monitoring, or ecommerce analysis."
    operation: Literal["get_taobao_product"] = Field(
        "get_taobao_product",
        title="Get Taobao Product",
        json_schema_extra={"ui:hidden": True},
    )
    item_id: str = Field(
        ...,
        description="Unique product identifier on Taobao/Tmall (item ID).",
        min_length=1,
    )


class GetJdProductConfig(_Operation):
    "Retrieve JD.com product details by item ID. Use it to review product information and images for catalog research or ecommerce analysis."
    operation: Literal["get_jd_product"] = Field(
        "get_jd_product", title="Get Jd Product", json_schema_extra={"ui:hidden": True}
    )
    item_id: str = Field(
        ...,
        description="A unique product identifier on JD.com (item ID).",
        min_length=1,
    )


class Search1688ProductsConfig(_Operation):
    "Searches 1688 products by keyword with pagination, sorting, price ranges and optional sourcing filters. Use it to discover products during procurement and market research."
    operation: Literal["search_1688_products"] = Field(
        "search_1688_products",
        title="Search 1688 Products",
        json_schema_extra={"ui:hidden": True},
    )
    keyword: str = Field(..., description="Search keyword.", min_length=1)
    page: int = Field(1, description="Page number, starting at 1.", ge=1, le=1000000)
    page_size: int = Field(
        20,
        description="Number of items requested per page. The returned count may differ.",
        ge=1,
        le=100,
    )
    sort: Literal["default", "sales", "price_up", "price_down"] = Field(
        "default",
        description="Product sort order.\n\nAvailable Values:\n- `default`: Default order\n- `sales`: Sales order\n- `price_up`: Price ascending\n- `price_down`: Price descending",
    )
    moq: int | None = Field(
        None, description="Minimum order quantity filter.", ge=1, le=1000000
    )
    price_start: str | None = Field(None, description="Minimum price filter in CNY.")
    price_end: str | None = Field(None, description="Maximum price filter in CNY.")
    new_arrival: bool | None = Field(None, description="Filter for new products.")
    support_dropshipping: bool | None = Field(
        None, description="Filter for support for dropshipping."
    )
    free_shipping: bool | None = Field(None, description="Filter for free shipping.")
    is_super_factory: bool | None = Field(
        None, description="Optional super-factory filter."
    )


class Convert1688ImageConfig(_Operation):
    "Converts an image URL or JPEG Base64 input into an image reference for a selected 1688 image search endpoint. Use it to prepare external images for visual product sourcing."
    operation: Literal["convert_1688_image"] = Field(
        "convert_1688_image",
        title="Convert 1688 Image",
        json_schema_extra={"ui:hidden": True},
    )
    url: str = Field(
        ...,
        description="HTTPS image URL to convert to a sourcing image reference.",
        min_length=1,
        json_schema_extra={"format": "uri", "pattern": "^https://[^ ]+$"},
    )
    search_api_endpoint: Literal[
        "standard", "cross_border_v1", "cross_border_v2"
    ] = Field(
        "standard", description="Image search target for the converted reference."
    )

    @field_validator("url")
    @classmethod
    def image_url(cls, value):
        if not value.startswith("https://"):
            raise ValueError("Provide an HTTPS image URL")
        return value


class SearchWechatArticlesConfig(_Operation):
    "Searches WeChat Official Account articles by keyword within a selected category such as followed accounts, latest, recently read, or hot, with continuation pagination. Use it to focus article discovery on a particular result stream."
    operation: Literal["search_wechat_articles"] = Field(
        "search_wechat_articles",
        title="Search Wechat Articles",
        json_schema_extra={"ui:hidden": True},
    )
    keyword: str = Field(
        ...,
        description="Search keyword for categorized WeChat Official Account article web search.",
        min_length=1,
    )
    sub_search_type: Literal["ALL", "FOLLOWED", "LATEST", "RECENT_READ", "HOT"] = Field(
        "ALL",
        description="Subcategory filter for categorized WeChat Official Account article web search.\n\nAvailable Values:\n- `ALL`: All\n- `FOLLOWED`: Followed accounts\n- `LATEST`: Latest\n- `RECENT_READ`: Recently read\n- `HOT`: Hot",
    )
    current_page: int = Field(
        1,
        description="Current page number starting from 1 for WeChat web search pagination.",
        ge=1,
        le=1000000,
    )
    offset: int = Field(
        0,
        description="Search result offset returned by the previous response. Use 0 for the first page.",
        ge=0,
        le=1000000,
    )
    cookies_buffer: str = Field(
        "",
        description="Opaque pagination state returned by the previous WeChat web search response. Leave it empty for the first page. For this POST endpoint, send it in an application/x-www-form-urlencoded form body.",
    )


class GetWechatArticleConfig(_Operation):
    "Retrieves lightweight information for a WeChat Official Account article by URL. Use it to perform a quick article lookup before deeper content, metric, or comment retrieval."
    operation: Literal["get_wechat_article"] = Field(
        "get_wechat_article",
        title="Get Wechat Article",
        json_schema_extra={"ui:hidden": True},
    )
    article_url: str = Field(
        ...,
        description="WeChat Official Account article URL used to fetch lightweight article metadata and status information.",
        min_length=1,
    )


class SearchYoutubeConfig(_Operation):
    "Search YouTube videos by keyword with optional language, upload-date, duration, and sort filters, or continue with a pagination token. Use it to discover public videos or browse additional result pages."
    operation: Literal["search_youtube"] = Field(
        "search_youtube", title="Search Youtube", json_schema_extra={"ui:hidden": True}
    )
    keyword: str = Field(
        "",
        description="Search term. Required for the first page; leave empty when using nextToken.",
    )
    lang: str | None = Field(
        None,
        description="Optional IETF language tag for localized results, such as en-US. Leave empty to use the default language.",
    )
    upload_date: Literal[
        "all", "lastHour", "today", "thisWeek", "thisMonth", "thisYear"
    ] = Field(
        "all",
        description="Upload-date filter.\n\nAvailable Values:\n- `all`: No upload-date limit\n- `lastHour`: Uploaded within the last hour\n- `today`: Uploaded today\n- `thisWeek`: Uploaded this week\n- `thisMonth`: Uploaded this month\n- `thisYear`: Uploaded this year",
    )
    duration: Literal["all", "short", "medium", "long"] = Field(
        "all",
        description="Video-duration filter.\n\nAvailable Values:\n- `all`: No duration limit\n- `short`: Short videos under 4 minutes\n- `medium`: Medium videos from 4 to 20 minutes\n- `long`: Long videos over 20 minutes",
    )
    sort_by: Literal["relevance", "uploadDate", "viewCount", "rating"] = Field(
        "relevance",
        description="Sort order for search results.\n\nAvailable Values:\n- `relevance`: Sort by relevance\n- `uploadDate`: Sort by upload date\n- `viewCount`: Sort by view count\n- `rating`: Sort by rating",
    )
    next_token: str | None = Field(
        None,
        description="Pagination token returned by the previous response. When provided, the keyword and filter parameters are ignored; very long tokens may exceed GET URL limits.",
    )

    @model_validator(mode="after")
    def search_or_continuation(self):
        if not self.keyword and not self.next_token:
            raise ValueError("Provide a keyword or the previous response's next_token")
        return self


class GetYoutubeVideoConfig(_Operation):
    "Retrieve public details for a YouTube video identified by video ID. Use it to inspect a known video before further content or comment analysis."
    operation: Literal["get_youtube_video"] = Field(
        "get_youtube_video",
        title="Get Youtube Video",
        json_schema_extra={"ui:hidden": True},
    )
    video_id: str = Field(
        ..., description="The unique identifier for a YouTube video.", min_length=1
    )
    lang: str | None = Field(
        None,
        description="Optional IETF language tag for localized video details, such as en-US. Leave empty to use the default language.",
    )


class GetYoutubeCaptionsConfig(_Operation):
    "Retrieve available caption tracks for a YouTube video or request captions in SRT, XML, JSON3, or plain-text format. Use it to support transcription, accessibility, localization, or text analysis."
    operation: Literal["get_youtube_captions"] = Field(
        "get_youtube_captions",
        title="Get Youtube Captions",
        json_schema_extra={"ui:hidden": True},
    )
    video_id: str = Field(
        ..., description="The unique identifier for a YouTube video.", min_length=1
    )
    language_code: str = Field(
        "",
        description="Caption language code, such as en, zh-Hans, or a.en. Leave it empty to retrieve available caption tracks.",
    )
    format: Literal["srt", "xml", "json3", "txt"] = Field(
        "srt",
        description="Caption output format.\n\nAvailable Values:\n- `srt`: SubRip caption format with timeline cues\n- `xml`: Original XML caption format\n- `json3`: YouTube original JSON caption structure\n- `txt`: Plain text without timeline cues",
    )


class GetInstagramUserConfig(_Operation):
    "Retrieves an Instagram user profile by username. Use it to review a known account before creator research, brand monitoring, or related post analysis."
    operation: Literal["get_instagram_user"] = Field(
        "get_instagram_user",
        title="Get Instagram User",
        json_schema_extra={"ui:hidden": True},
    )
    username: str = Field(
        ...,
        description="The Instagram username whose profile details are to be retrieved.",
        min_length=1,
    )


class GetInstagramPostConfig(_Operation):
    "Retrieves an Instagram post by its shortcode. Use it to look up a known post before content review, archiving, comment analysis, or related workflows."
    operation: Literal["get_instagram_post"] = Field(
        "get_instagram_post",
        title="Get Instagram Post",
        json_schema_extra={"ui:hidden": True},
    )
    code: str = Field(
        ...,
        description="The unique shortcode from the Instagram post URL.",
        min_length=1,
    )


class SearchRedditConfig(_Operation):
    "Searches Reddit posts by keyword with an optional continuation token. Use it to discover topic-related discussions or continue through additional search-result pages."
    operation: Literal["search_reddit"] = Field(
        "search_reddit", title="Search Reddit", json_schema_extra={"ui:hidden": True}
    )
    keyword: str = Field(..., description="Search query keywords.", min_length=1)
    after: str = Field(
        "", description="Pagination token to retrieve the next set of results."
    )


JustOneApiOperation = Annotated[
    Union[
        GetWeiboHotSearchConfig,
        SearchDouyinVideosConfig,
        GetDouyinVideoConfig,
        GetDouyinUserConfig,
        SearchRednoteNotesConfig,
        GetRednoteNoteConfig,
        GetWeiboPostConfig,
        SearchTaobaoProductsConfig,
        GetTaobaoProductConfig,
        GetJdProductConfig,
        Search1688ProductsConfig,
        Convert1688ImageConfig,
        SearchWechatArticlesConfig,
        GetWechatArticleConfig,
        SearchYoutubeConfig,
        GetYoutubeVideoConfig,
        GetYoutubeCaptionsConfig,
        GetInstagramUserConfig,
        GetInstagramPostConfig,
        SearchRedditConfig,
    ],
    Field(discriminator="operation"),
]


class JustOneApiFullConfig(NodeConfig[JustOneApiOperation, JustOneApiTokenCredential]):
    pass


# Fixed published routes and explicit wire parameter names; no arbitrary endpoint input.
ROUTES = {
    "get_weibo_hot_search": ("GET", "/api/weibo/hot-search/v1", "query", {}),
    "search_douyin_videos": (
        "GET",
        "/api/douyin/search-video/v4",
        "query",
        {
            "keyword": "keyword",
            "sort_type": "sortType",
            "publish_time": "publishTime",
            "duration": "duration",
            "page": "page",
            "search_id": "searchId",
        },
    ),
    "get_douyin_video": (
        "GET",
        "/api/douyin/get-video-detail/v2",
        "query",
        {"video_id": "videoId"},
    ),
    "get_douyin_user": (
        "GET",
        "/api/douyin/get-user-detail/v3",
        "query",
        {"sec_uid": "secUid"},
    ),
    "search_rednote_notes": (
        "GET",
        "/api/xiaohongshu/search-note/v4",
        "query",
        {
            "keyword": "keyword",
            "page": "page",
            "sort_type": "sortType",
            "note_type": "noteType",
            "time_filter": "timeFilter",
        },
    ),
    "get_rednote_note": (
        "GET",
        "/api/xiaohongshu/get-note-detail/v6",
        "query",
        {"note_id": "noteId"},
    ),
    "get_weibo_post": ("GET", "/api/weibo/get-weibo-detail/v1", "query", {"id": "id"}),
    "search_taobao_products": (
        "GET",
        "/api/taobao/search-item-list/v2",
        "query",
        {"keyword": "keyword", "page": "page"},
    ),
    "get_taobao_product": (
        "GET",
        "/api/taobao/get-item-detail/v9",
        "query",
        {"item_id": "itemId"},
    ),
    "get_jd_product": (
        "GET",
        "/api/jd/get-item-detail/v4",
        "query",
        {"item_id": "itemId"},
    ),
    "search_1688_products": (
        "GET",
        "/api/1688/search-item-list/v2",
        "query",
        {
            "keyword": "keyword",
            "page": "page",
            "page_size": "pageSize",
            "sort": "sort",
            "moq": "moq",
            "price_start": "priceStart",
            "price_end": "priceEnd",
            "new_arrival": "newArrival",
            "support_dropshipping": "supportDropshipping",
            "free_shipping": "freeShipping",
            "is_super_factory": "isSuperFactory",
        },
    ),
    "convert_1688_image": (
        "POST",
        "/api/1688/convert-image/v1",
        "json",
        {"url": "url", "search_api_endpoint": "searchApiEndpoint"},
    ),
    "search_wechat_articles": (
        "POST",
        "/api/weixin/search-article/v2",
        "form",
        {
            "keyword": "keyword",
            "sub_search_type": "subSearchType",
            "current_page": "currentPage",
            "offset": "offset",
            "cookies_buffer": "cookies_buffer",
        },
    ),
    "get_wechat_article": (
        "GET",
        "/api/weixin/get-article-detail/v5",
        "query",
        {"article_url": "articleUrl"},
    ),
    "search_youtube": (
        "GET",
        "/api/youtube/search/v1",
        "query",
        {
            "keyword": "keyword",
            "lang": "lang",
            "upload_date": "uploadDate",
            "duration": "duration",
            "sort_by": "sortBy",
            "next_token": "nextToken",
        },
    ),
    "get_youtube_video": (
        "GET",
        "/api/youtube/get-video-detail/v1",
        "query",
        {"video_id": "videoId", "lang": "lang"},
    ),
    "get_youtube_captions": (
        "GET",
        "/api/youtube/get-video-captions/v1",
        "query",
        {"video_id": "videoId", "language_code": "languageCode", "format": "format"},
    ),
    "get_instagram_user": (
        "GET",
        "/api/instagram/get-user-detail/v2",
        "query",
        {"username": "username"},
    ),
    "get_instagram_post": (
        "GET",
        "/api/instagram/get-post-detail/v1",
        "query",
        {"code": "code"},
    ),
    "search_reddit": (
        "GET",
        "/api/reddit/search/v1",
        "query",
        {"keyword": "keyword", "after": "after"},
    ),
}


def _redact(value, token):
    if isinstance(value, str):
        # Providers may echo a query in a message or nested data string.
        return value.replace(token, "[redacted]").replace(
            quote(token, safe=""), "[redacted]"
        )
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact(item, token)
            for key, item in value.items()
            if key.lower()
            not in {"token", "access_token", "requestparams", "authorization"}
        }
    return value


class JustOneApiNode(WorkflowNode):
    integration_type = "automation-just-one-api"
    connection_evidence = ConnectionEvidence(
        operation="get_weibo_hot_search", noun="Weibo hot search", proves="reachability"
    )

    @classmethod
    def get_config_model(cls):
        return JustOneApiFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Just One API token")
        method, path, mode, fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        payload = {
            fields[key]: value
            for key, value in values.items()
            if value != "" or mode == "form"
        }
        # The WeChat contract places token in the form; all other selected routes
        # place it in the query, including the JSON image-conversion endpoint.
        query = {} if mode == "form" else {"token": credential.token}
        kwargs = {}
        if mode == "query":
            query.update(payload)
        elif mode == "form":
            kwargs["data"] = {"token": credential.token, **payload}
        else:
            kwargs["json"] = payload
        output = {"operation": config.operation}
        try:
            async with guarded_async_client(
                timeout=120, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + path,
                    params=query,
                    headers={"Accept": "application/json"},
                    **kwargs,
                )
            status = response.status_code
            mime = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if len(response.content) > 10_000_000 or mime != "application/json":
                return {
                    **output,
                    "status": "error",
                    "status_code": status,
                    "error": "Just One API returned an unexpected response; expected bounded JSON",
                }
            body = response.json()
            if not isinstance(body, dict) or type(body.get("code")) is not int:
                return {
                    **output,
                    "status": "error",
                    "status_code": status,
                    "error": "Just One API returned an invalid business response",
                }
            code = body["code"]
            if not 200 <= status < 300 or code != 0:
                message = body.get("message")
                return {
                    **output,
                    "status": "error",
                    "code": code,
                    "status_code": {100: 401, 600: 403, 302: 429, 303: 429}.get(
                        code, status
                    ),
                    "error": _redact(message, credential.token)
                    if isinstance(message, str) and message
                    else "Just One API did not confirm the request",
                }
            if "data" not in body:
                return {
                    **output,
                    "status": "error",
                    "error": "Just One API success response is missing data",
                }
            # Retain provider-specific pagination within data. Never return the
            # top-level requestParams echo, which contains the credential.
            return {
                **output,
                "status": "success",
                "code": 0,
                "status_code": status,
                "data": _redact(body["data"], credential.token),
                "message": _redact(body.get("message"), credential.token),
                "record_time": _redact(body.get("recordTime"), credential.token),
                "request_id": _redact(body.get("requestId"), credential.token),
            }
        except (httpx.HTTPError, SSRFError):
            return {
                **output,
                "status": "error",
                "error": "Just One API request could not be completed; inspect usage before retrying",
            }
        except (ValueError, RecursionError):
            return {
                **output,
                "status": "error",
                "error": "Just One API returned invalid JSON",
            }
