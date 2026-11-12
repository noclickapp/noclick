"""Supadata v1.3.0: fixed one-request operations for media and web content.

Job creation returns the provider job ID; use its corresponding status operation
in a later step. No automatic retry of a billable request is performed.
Contract: https://supadata.ai/api/v1/openapi.json
"""
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class SupadataAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Supadata API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dash.supadata.ai",
            "x-credential-instructions": "Copy an API key from your Supadata dashboard. NoClick sends it in the x-api-key header to api.supadata.ai. Content extraction and job creation consume your Supadata credits."})
    credential_type: Literal["supadata_api_key"] = Field("supadata_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class SupadataInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GetYoutubeVideoConfig(SupadataInput):
    """Get metadata for a YouTube video."""
    operation: Literal["get_youtube_video"] = Field("get_youtube_video", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='YouTube video URL or ID. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')

class GetYoutubePlaylistConfig(SupadataInput):
    """Get metadata for a YouTube playlist."""
    operation: Literal["get_youtube_playlist"] = Field("get_youtube_playlist", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='YouTube playlist URL or ID. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')

class ListYoutubePlaylistVideosConfig(SupadataInput):
    """Get video IDs from a YouTube playlist."""
    operation: Literal["list_youtube_playlist_videos"] = Field("list_youtube_playlist_videos", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='YouTube playlist URL or ID. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')
    limit: float | None = Field(None, ge=1, le=5000, description='Maximum number of video IDs to return')

class GetYoutubeChannelConfig(SupadataInput):
    """Get metadata for a YouTube channel."""
    operation: Literal["get_youtube_channel"] = Field("get_youtube_channel", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='YouTube channel URL, handle or ID. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')

class ListYoutubeChannelVideosConfig(SupadataInput):
    """Get video IDs from a YouTube channel."""
    operation: Literal["list_youtube_channel_videos"] = Field("list_youtube_channel_videos", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='YouTube channel URL, handle or ID. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')
    limit: float | None = Field(None, ge=1, le=5000, description='Maximum number of video IDs to return. If type = all, regular (landscape) videos are filled first, then Shorts, then live streams.')
    type: Literal['all', 'video', 'short', 'live'] | None = Field(None, min_length=1, description='Type of videos to return.')

class GetYoutubeTranscriptConfig(SupadataInput):
    """Get transcript from YouTube video in various formats and languages. If the `lang` parameter is not provided or the transcript is not available in the requested language, the API defaults to the first available language."""
    operation: Literal["get_youtube_transcript"] = Field("get_youtube_transcript", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description='YouTube video URL. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')
    text: bool | None = Field(None, description='When true, returns plain text transcript.')
    chunkSize: float | None = Field(None, ge=50, le=10000, description='Maximum characters per transcript chunk (only when text=false)')
    lang: str | None = Field(None, min_length=1, description='Preferred language code of the transcript (ISO 639-1). If not provided, the first available language will be returned. If the requested language is unavailable, the API defaults to the first available language. See [Languages](https://docs.supadata.ai/youtube/supported-language-codes).')

class TranslateYoutubeTranscriptConfig(SupadataInput):
    """Translate YouTube video transcript into different languages."""
    operation: Literal["translate_youtube_transcript"] = Field("translate_youtube_transcript", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description='YouTube video URL. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')
    text: bool | None = Field(None, description='When true, returns plain text transcript.')
    chunkSize: float | None = Field(None, ge=50, le=10000, description='Maximum characters per transcript chunk (only when text=false)')
    lang: str = Field(..., min_length=1, description='Language code for translation (ISO 639-1). See [Languages](https://docs.supadata.ai/youtube/supported-language-codes).')

class CreateTranscriptBatchConfig(SupadataInput):
    """Create a batch job to get transcripts of multiple YouTube videos. Batches created from a playlist or channel include regular videos only (Shorts and live streams are skipped)."""
    operation: Literal["create_transcript_batch"] = Field("create_transcript_batch", json_schema_extra={"ui:hidden": True})
    videoIds: list[str] | None = Field(None, description='Array of YouTube video IDs or URLs')
    playlistId: str | None = Field(None, min_length=1, description='YouTube playlist URL or ID. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')
    channelId: str | None = Field(None, min_length=1, description='YouTube channel URL, handle or ID. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')
    limit: float | None = Field(None, ge=1, le=5000, description='Maximum number of videos to process (when using playlistId or channelId)')
    lang: str | None = Field(None, min_length=1, description='Preferred language code of the transcript (ISO 639-1). If not provided, the first available language will be returned. If the requested language is unavailable, the API defaults to the first available language. See [Languages](https://docs.supadata.ai/youtube/supported-language-codes).')
    text: bool | None = Field(None, description='When true, returns plain text transcript.')

    @model_validator(mode="after")
    def source(self):
        if sum(v is not None for v in (self.videoIds, self.playlistId, self.channelId)) != 1:
            raise ValueError("Provide exactly one of videoIds, playlistId or channelId")
        if self.videoIds == []:
            raise ValueError("Provide at least one video")
        return self

class CreateVideoBatchConfig(SupadataInput):
    """Create a batch job to fetch metadata of multiple YouTube videos. Batches created from a playlist or channel include regular videos only (Shorts and live streams are skipped)."""
    operation: Literal["create_video_batch"] = Field("create_video_batch", json_schema_extra={"ui:hidden": True})
    videoIds: list[str] | None = Field(None, description='Array of YouTube video IDs or URLs')
    playlistId: str | None = Field(None, min_length=1, description='YouTube playlist URL or ID. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')
    channelId: str | None = Field(None, min_length=1, description='YouTube channel URL, handle or ID. See [supported URL formats](https://docs.supadata.ai/youtube/supported-url-formats).')
    limit: float | None = Field(None, ge=1, le=5000, description='Maximum number of videos to process (when using playlistId or channelId)')

    @model_validator(mode="after")
    def source(self):
        if sum(v is not None for v in (self.videoIds, self.playlistId, self.channelId)) != 1:
            raise ValueError("Provide exactly one of videoIds, playlistId or channelId")
        if self.videoIds == []:
            raise ValueError("Provide at least one video")
        return self

class GetYoutubeBatchConfig(SupadataInput):
    """Get the status and results of a YouTube batch job."""
    operation: Literal["get_youtube_batch"] = Field("get_youtube_batch", json_schema_extra={"ui:hidden": True})
    jobId: str = Field(..., min_length=1)
    limit: int | None = Field(None, ge=1, le=500)
    offset: int | None = Field(None, ge=0)

class SearchYoutubeConfig(SupadataInput):
    """Search YouTube for videos, channels, and playlists with advanced filters."""
    operation: Literal["search_youtube"] = Field("search_youtube", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, description='Search query string')
    uploadDate: Literal['all', 'hour', 'today', 'week', 'month', 'year'] | None = Field(None, min_length=1, description='Filter by upload date (eg. last month). Note: works only for videos and movies.')
    type: Literal['all', 'video', 'channel', 'playlist', 'movie'] | None = Field(None, min_length=1, description='Filter by content type')
    duration: Literal['all', 'short', 'medium', 'long'] | None = Field(None, min_length=1, description='Filter by video duration: short (<4min), medium (4-20min), long (>20min). Note: works only for videos and movies.')
    sortBy: Literal['relevance', 'rating', 'date', 'views'] | None = Field(None, min_length=1, description='Sort order of search results.')
    features: list[Literal['hd', 'subtitles', 'creative-commons', '3d', 'live', '4k', '360', 'location', 'hdr', 'vr180']] | None = Field(None, description='Array of special features to filter by (repeat the parameter for several: `features=hd&features=subtitles`). Note: works only for videos and movies.')
    limit: float | None = Field(None, ge=1, le=5000, description='Maximum number of results to return. When provided, the API will automatically paginate to fetch up to this many results. When omitted, returns a single page with `nextPageToken` for manual pagination.')
    nextPageToken: str | None = Field(None, min_length=1, description='Token for fetching the next page of results. When provided, other filter parameters are ignored.')

class ScrapeWebConfig(SupadataInput):
    """Extract content from any web page to Markdown format."""
    operation: Literal["scrape_web"] = Field("scrape_web", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description='URL of the webpage')
    noLinks: bool | None = Field(None, description='When true, Markdown links are stripped from the content.')
    lang: str | None = Field(None, min_length=1, description='Preferred language for the scraped content (ISO 639-1 code). Sets Accept-Language header to influence website language selection.')

class MapWebConfig(SupadataInput):
    """Extract all links found on a whole website."""
    operation: Literal["map_web"] = Field("map_web", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description='URL of the webpage')

class CreateWebCrawlConfig(SupadataInput):
    """Create a crawl job to extract content from all pages on a website."""
    operation: Literal["create_web_crawl"] = Field("create_web_crawl", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description='URL of the website to crawl')
    limit: float | None = Field(None, ge=1, le=5000, description='Maximum number of pages to crawl')

class GetWebCrawlConfig(SupadataInput):
    """Get the status and results of a crawl by job ID."""
    operation: Literal["get_web_crawl"] = Field("get_web_crawl", json_schema_extra={"ui:hidden": True})
    jobId: str = Field(..., min_length=1)
    skip: float | None = Field(None, ge=0)

class GetTranscriptConfig(SupadataInput):
    """Get transcript from a supported video platform (YouTube, TikTok, Twitter, Instagram, Facebook) or file URL. If the video is too large to return transcript immediately, request returns a job ID. Use the `/transcript/:jobId` endpoint to get job results."""
    operation: Literal["get_transcript"] = Field("get_transcript", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description='Video URL from any supported platform (YouTube, TikTok, Twitter, Instagram, Facebook) or a direct media file URL.')
    lang: str | None = Field(None, min_length=1, description='Preferred language code of the transcript (ISO 639-1). If not provided, the first available language will be returned. If the requested language is unavailable, the API defaults to the first available language. See [Languages](https://docs.supadata.ai/youtube/supported-language-codes).')
    text: bool | None = Field(None, description='When true, returns plain text transcript.')
    chunkSize: float | None = Field(None, ge=50, le=10000, description='Maximum characters per transcript chunk (only when text=false)')
    mode: Literal['native', 'auto', 'generate'] | None = Field(None, min_length=1, description='Transcript mode: `native` (only fetch existing transcript), `generate` (always generate transcript using AI), or `auto` (try native, fallback to generate if unavailable). If url is a file URL, mode is always `generate`.')

class GetTranscriptJobConfig(SupadataInput):
    """Get results for a transcript job by job ID."""
    operation: Literal["get_transcript_job"] = Field("get_transcript_job", json_schema_extra={"ui:hidden": True})
    jobId: str = Field(..., min_length=1)

class GetMetadataConfig(SupadataInput):
    """Fetch metadata from any supported internet media including YouTube, TikTok, Instagram, Twitter/X and Facebook posts. Returns unified metadata with a predictable structure across all platforms."""
    operation: Literal["get_metadata"] = Field("get_metadata", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description='URL to any supported internet media. Supports YouTube videos, TikTok videos, Instagram reels/posts, Twitter/X posts, Facebook videos, and more.')

class CreateExtractConfig(SupadataInput):
    """Use AI to analyze video content and extract structured data. Provide either a prompt describing what to extract, a JSON Schema for the output format, or both. Supports YouTube, TikTok, Instagram, Twitter/X, and Facebook videos, or a direct video file URL. Videos up to 3 hours (180 minutes) and files up to 2 GB are supported; the whole video is analyzed (1 frame per second up to 80 minutes, a lower evenly-spaced frame rate beyond). Over-limit YouTube and file URLs are rejected with 400 before a job is created. Returns a job ID for asynchronous processing. Use the `/extract/:jobId` endpoint to poll for results."""
    operation: Literal["create_extract"] = Field("create_extract", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description='URL to any supported video media. Supports YouTube, TikTok, Instagram, Twitter/X, and Facebook videos, or a direct media file URL.')
    prompt: str | None = Field(None, min_length=1, description='Natural language description of what data to extract from the video. Required if schema is not provided. Do not include JSON structure definitions here — use the "schema" field instead.')
    extraction_schema: dict[str, Any] | None = Field(None, description='JSON Schema defining the structure of data to extract. Required if prompt is not provided. Checked before the job is created: a schema the AI model cannot use (most often large `maxItems`/`maxLength` bounds) is rejected with `400 invalid-request` explaining what to change. See the schema rules at https://docs.supadata.ai/get-extract#schema-rules.', alias='schema')

    @model_validator(mode="after")
    def instructions(self):
        if not self.prompt and not self.extraction_schema:
            raise ValueError("Provide a prompt or extraction schema")
        return self

class GetExtractJobConfig(SupadataInput):
    """Get results for an extract job by job ID."""
    operation: Literal["get_extract_job"] = Field("get_extract_job", json_schema_extra={"ui:hidden": True})
    jobId: str = Field(..., min_length=1)

class GetAccountConfig(SupadataInput):
    """Retrieve organization details, plan information, and credit usage."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})

# Supadata's own MCP server: agents get its tools through a person's Supadata sign-in.
SupadataMcpCredential = mcp_credential("supadata", "https://api.supadata.ai/mcp", app="Supadata")
SupadataCredential = Union[SupadataAPIKeyCredential, SupadataMcpCredential]


SupadataConfig = Annotated[Union[GetYoutubeVideoConfig, GetYoutubePlaylistConfig, ListYoutubePlaylistVideosConfig, GetYoutubeChannelConfig, ListYoutubeChannelVideosConfig, GetYoutubeTranscriptConfig, TranslateYoutubeTranscriptConfig, CreateTranscriptBatchConfig, CreateVideoBatchConfig, GetYoutubeBatchConfig, SearchYoutubeConfig, ScrapeWebConfig, MapWebConfig, CreateWebCrawlConfig, GetWebCrawlConfig, GetTranscriptConfig, GetTranscriptJobConfig, GetMetadataConfig, CreateExtractConfig, GetExtractJobConfig, GetAccountConfig], Field(discriminator="operation")]

class SupadataFullConfig(NodeConfig[SupadataConfig, SupadataCredential]):
    pass

ROUTES = {'get_youtube_video': ('GET', '/youtube/video'), 'get_youtube_playlist': ('GET', '/youtube/playlist'), 'list_youtube_playlist_videos': ('GET', '/youtube/playlist/videos'), 'get_youtube_channel': ('GET', '/youtube/channel'), 'list_youtube_channel_videos': ('GET', '/youtube/channel/videos'), 'get_youtube_transcript': ('GET', '/youtube/transcript'), 'translate_youtube_transcript': ('GET', '/youtube/transcript/translate'), 'create_transcript_batch': ('POST', '/youtube/transcript/batch'), 'create_video_batch': ('POST', '/youtube/video/batch'), 'get_youtube_batch': ('GET', '/youtube/batch/{jobId}'), 'search_youtube': ('GET', '/youtube/search'), 'scrape_web': ('GET', '/web/scrape'), 'map_web': ('GET', '/web/map'), 'create_web_crawl': ('POST', '/web/crawl'), 'get_web_crawl': ('GET', '/web/crawl/{jobId}'), 'get_transcript': ('GET', '/transcript'), 'get_transcript_job': ('GET', '/transcript/{jobId}'), 'get_metadata': ('GET', '/metadata'), 'create_extract': ('POST', '/extract'), 'get_extract_job': ('GET', '/extract/{jobId}'), 'get_account': ('GET', '/me')}


class SupadataNode(WorkflowNode):
    integration_type = "automation-supadata"
    credential_provider_labels = {"supadata": "Supadata Account"}
    connection_evidence = ConnectionEvidence(noun="Supadata account", operation="get_account")

    @classmethod
    def get_config_model(cls):
        return SupadataFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Supadata API key")
        key = self.config.credentials.api_key
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(by_alias=True, exclude_none=True, exclude={"operation"})
        if "jobId" in values:
            path = path.replace("{jobId}", quote(values.pop("jobId"), safe=""))
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.supadata.ai/v1" + path,
                headers={"x-api-key": key, "Accept": "application/json"},
                **({"json": values} if method == "POST" else {"params": values}))
        if len(response.content) > 20_000_000:
            raise ValueError("Supadata response exceeds the content limit")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Supadata returned a non-JSON response") from None
        def redact(value):
            if isinstance(value, str): return value.replace(key, "[redacted]")
            if isinstance(value, list): return [redact(v) for v in value]
            if isinstance(value, dict): return {k: redact(v) for k, v in value.items()}
            return value
        body = redact(body)
        if not isinstance(body, dict):
            raise ValueError("Supadata returned an unexpected JSON envelope")
        if op.operation == "get_account" and response.status_code == 200 and not body.get("error"):
            if not isinstance(body.get("organizationId"), str) or not body["organizationId"]:
                raise ValueError("Supadata account response is missing its organization ID")
        failed = response.status_code not in {200, 202} or (isinstance(body, dict) and bool(body.get("error")))
        output = {"status": "error" if failed else "success", "http_status": response.status_code,
                  "data": body, **({"error": body} if failed else {})}
        await self.emit(output)
        return output
