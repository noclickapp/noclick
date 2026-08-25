"""
Mock tests for TikTok Open Platform automation node.

Tests all 5 TikTok operations using mocked HTTP responses.
No real API credentials needed — all tests use mocked httpx.AsyncClient.

IMPORTANT: These tests verify not just response handling but also:
- Correct HTTP method (GET vs POST)
- Correct endpoint URL
- Correct request structure (query params vs JSON body)
- Correct auth header
This prevents silent regressions where wrong endpoints/methods pass mock tests
but fail against the real API.

Operations tested:
- get_user_info    GET  /v2/user/info/                        ?fields=
- list_videos      POST /v2/video/list/                       ?fields= + body(max_count)
- query_videos     POST /v2/video/query/                      ?fields= + body(filters.video_ids)
- publish_video    POST /v2/post/publish/inbox/video/init/    body(source_info)
- check_publish_status POST /v2/post/publish/status/fetch/   body(publish_id)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json
from datetime import datetime, timedelta, timezone

from nodes.tiktok_node import (
    TikTokNode,
    TikTokNodeConfig,
    TikTokOAuthCredential,
    TikTokGetUserInfoConfig,
    TikTokListVideosConfig,
    TikTokQueryVideosConfig,
    TikTokPublishVideoConfig,
    TikTokCheckPublishStatusConfig,
    TikTokQueryCreatorInfoConfig,
    TikTokDirectPostVideoConfig,
    TikTokDirectPostPhotoConfig,
    TIKTOK_API_BASE,
)
from nodes.core.media_resolver import ResolvedMedia


# ============================================================================
# Test helpers
# ============================================================================

MOCK_ACCESS_TOKEN = "mock_access_token_tiktok_12345"
MOCK_OPEN_ID = "mock_open_id_abc123"
MOCK_DISPLAY_NAME = "TestUser"


def get_credential(expires_days=30):
    future_expiry = datetime.now(timezone.utc) + timedelta(days=expires_days)
    return TikTokOAuthCredential(
        access_token=MOCK_ACCESS_TOKEN,
        refresh_token="mock_refresh_token",
        expires_at=future_expiry.isoformat(),
        open_id=MOCK_OPEN_ID,
        display_name=MOCK_DISPLAY_NAME,
    )


def mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data)
    resp.raise_for_status = MagicMock()
    resp.text = json.dumps(json_data)
    return resp


def patch_http(response):
    """Patch httpx.AsyncClient; returns (ctx, mock_client)."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.request = AsyncMock(return_value=response)
    return patch("httpx.AsyncClient", return_value=mock_client), mock_client


def build_node(action_config, credential=None):
    if credential is None:
        credential = get_credential()
    full_config = TikTokNodeConfig(config=action_config, credentials=credential)
    return TikTokNode(
        node_id="test_node",
        node_type="automation-tiktok",
        node_data={},
        config=full_config,
    )


def assert_request(mock_client, method, endpoint, *, params=None, json_body=None):
    """Assert the mock HTTP client was called with the correct request details."""
    expected_url = f"{TIKTOK_API_BASE}{endpoint}"
    call_kwargs = mock_client.request.call_args
    assert call_kwargs is not None, "No HTTP request was made"

    kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
    args = call_kwargs.args if call_kwargs.args else ()

    actual_method = kwargs.get("method") or (args[0] if args else None)
    actual_url = kwargs.get("url") or (args[1] if len(args) > 1 else None)

    assert actual_method == method, f"Expected method {method!r}, got {actual_method!r}"
    assert (
        actual_url == expected_url
    ), f"Expected URL {expected_url!r}, got {actual_url!r}"

    actual_headers = kwargs.get("headers", {})
    assert "Authorization" in actual_headers, "Missing Authorization header"
    assert MOCK_ACCESS_TOKEN in actual_headers["Authorization"]

    if params is not None:
        actual_params = kwargs.get("params", {}) or {}
        for key, value in params.items():
            assert key in actual_params, f"Expected query param {key!r} missing"
            assert (
                actual_params[key] == value
            ), f"Param {key!r}: expected {value!r}, got {actual_params[key]!r}"

    if json_body is not None:
        actual_json = kwargs.get("json", {}) or {}
        for key, value in json_body.items():
            assert (
                key in actual_json
            ), f"Expected body key {key!r} missing from {actual_json}"
            assert (
                actual_json[key] == value
            ), f"Body key {key!r}: expected {value!r}, got {actual_json[key]!r}"


# ============================================================================
# User Operations
# ============================================================================


class TestUserOperations:
    @pytest.mark.asyncio
    async def test_get_user_info(self):
        api_resp = {
            "data": {
                "user": {
                    "open_id": MOCK_OPEN_ID,
                    "display_name": MOCK_DISPLAY_NAME,
                    "follower_count": 1000,
                }
            },
            "error": {"code": "ok", "message": ""},
        }
        node = build_node(TikTokGetUserInfoConfig())
        ctx, mock_client = patch_http(mock_response(api_resp))
        with ctx:
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_authenticated_user_info"
        assert result["data"]["data"]["user"]["open_id"] == MOCK_OPEN_ID
        assert "timing_ms" in result

        # GET with fields as query param, no body
        assert_request(mock_client, "GET", "/v2/user/info/")
        call_kwargs = mock_client.request.call_args.kwargs
        assert "fields" in (
            call_kwargs.get("params") or {}
        ), "fields must be a query param"
        assert call_kwargs.get("json") is None, "GET user/info must have no body"


# ============================================================================
# Video Reading Operations
# ============================================================================


class TestVideoReadingOperations:
    @pytest.mark.asyncio
    async def test_list_videos(self):
        api_resp = {
            "data": {
                "videos": [
                    {"id": "v1", "title": "Video 1", "view_count": 100},
                    {"id": "v2", "title": "Video 2", "view_count": 200},
                ],
                "cursor": 20,
                "has_more": False,
            },
            "error": {"code": "ok", "message": ""},
        }
        node = build_node(TikTokListVideosConfig(max_count=20))
        ctx, mock_client = patch_http(mock_response(api_resp))
        with ctx:
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_user_public_videos"
        assert len(result["data"]["data"]["videos"]) == 2
        assert "timing_ms" in result

        # POST with fields as query param, max_count in body
        assert_request(
            mock_client, "POST", "/v2/video/list/", json_body={"max_count": 20}
        )
        call_kwargs = mock_client.request.call_args.kwargs
        assert "fields" in (
            call_kwargs.get("params") or {}
        ), "fields must be a query param"

    @pytest.mark.asyncio
    async def test_query_videos(self):
        api_resp = {
            "data": {"videos": [{"id": "v123", "like_count": 500, "view_count": 5000}]},
            "error": {"code": "ok", "message": ""},
        }
        node = build_node(TikTokQueryVideosConfig(video_ids="v123"))
        ctx, mock_client = patch_http(mock_response(api_resp))
        with ctx:
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "query_video_metrics_by_id"
        assert result["data"]["data"]["videos"][0]["id"] == "v123"
        assert "timing_ms" in result

        # POST with filters.video_ids in body, fields as query param
        assert_request(mock_client, "POST", "/v2/video/query/")
        call_kwargs = mock_client.request.call_args.kwargs
        body = call_kwargs.get("json", {}) or {}
        assert "filters" in body, "Expected 'filters' key in body"
        assert "v123" in body["filters"]["video_ids"]
        assert "fields" in (
            call_kwargs.get("params") or {}
        ), "fields must be a query param"


# ============================================================================
# Publishing Operations
# ============================================================================


class TestPublishingOperations:
    @pytest.mark.asyncio
    async def test_publish_video(self):
        api_resp = {
            "data": {"publish_id": "pub_abc123"},
            "error": {"code": "ok", "message": ""},
        }
        node = build_node(
            TikTokPublishVideoConfig(
                video_url="https://example.com/video.mp4",
                title="Test video",
            )
        )
        ctx, mock_client = patch_http(mock_response(api_resp))
        with ctx:
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upload_video_to_creator_inbox"
        assert result["data"]["data"]["publish_id"] == "pub_abc123"
        assert "timing_ms" in result

        # POST to inbox endpoint with source_info.PULL_FROM_URL in body
        assert_request(mock_client, "POST", "/v2/post/publish/inbox/video/init/")
        call_kwargs = mock_client.request.call_args.kwargs
        body = call_kwargs.get("json", {}) or {}
        assert body["source_info"]["source"] == "PULL_FROM_URL"
        assert body["source_info"]["video_url"] == "https://example.com/video.mp4"
        assert body["post_info"]["title"] == "Test video"

    @pytest.mark.asyncio
    async def test_check_publish_status(self):
        api_resp = {
            "data": {"status": "PUBLISH_COMPLETE", "video_id": "vid_xyz"},
            "error": {"code": "ok", "message": ""},
        }
        node = build_node(TikTokCheckPublishStatusConfig(publish_id="pub_abc123"))
        ctx, mock_client = patch_http(mock_response(api_resp))
        with ctx:
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "check_video_publish_status"
        assert result["data"]["data"]["status"] == "PUBLISH_COMPLETE"
        assert "timing_ms" in result

        assert_request(
            mock_client,
            "POST",
            "/v2/post/publish/status/fetch/",
            json_body={"publish_id": "pub_abc123"},
        )


# ============================================================================
# Error Handling
# ============================================================================


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_api_401_error(self):
        error_resp = {
            "error": {
                "code": "access_token_invalid",
                "message": "Access token is invalid.",
            }
        }
        node = build_node(TikTokGetUserInfoConfig())
        ctx, _ = patch_http(mock_response(error_resp, status_code=401))
        with ctx:
            result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 401
        assert "timing_ms" in result

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        full_config = TikTokNodeConfig(
            config=TikTokGetUserInfoConfig(), credentials=None
        )
        node = TikTokNode(
            node_id="test_node",
            node_type="automation-tiktok",
            node_data={},
            config=full_config,
        )
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_timing_ms_present(self):
        api_resp = {
            "data": {"user": {"open_id": MOCK_OPEN_ID}},
            "error": {"code": "ok", "message": ""},
        }
        node = build_node(TikTokGetUserInfoConfig())
        ctx, _ = patch_http(mock_response(api_resp))
        with ctx:
            result = await node.execute({})

        assert "timing_ms" in result
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["total"] >= 0


# ============================================================================
# Direct Posting Operations (Content Posting API)
# ============================================================================


class TestDirectPostingOperations:
    @pytest.mark.asyncio
    async def test_query_creator_info(self):
        config = TikTokQueryCreatorInfoConfig()
        node = build_node(config)
        api_resp = {
            "data": {
                "creator_nickname": "Test",
                "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
                "max_video_post_duration_sec": 300,
            },
            "error": {"code": "ok"},
        }
        ctx, mock_client = patch_http(mock_response(api_resp))
        with ctx:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "query_creator_info"
        assert_request(mock_client, "POST", "/v2/post/publish/creator_info/query/")
        assert result["data"]["data"]["max_video_post_duration_sec"] == 300

    @pytest.mark.asyncio
    async def test_direct_post_video_file_upload(self):
        config = TikTokDirectPostVideoConfig(
            video_url="https://example.com/v.mp4",
            title="hello",
            privacy_level="SELF_ONLY",
            disable_comment="true",
        )
        node = build_node(config)

        init_resp = mock_response(
            {
                "data": {"publish_id": "pub_123", "upload_url": "https://upload.tiktok/abc"},
                "error": {"code": "ok"},
            }
        )
        put_resp = mock_response({}, status_code=201)
        resolved = ResolvedMedia(data=b"x" * 100, mime_type="video/mp4", filename="v.mp4")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.request = AsyncMock(return_value=init_resp)
        mock_client.put = AsyncMock(return_value=put_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "nodes.tiktok_node.assert_url_allowed", new_callable=AsyncMock
        ), patch(
            "nodes.core.media_resolver.resolve_media_input",
            new=AsyncMock(return_value=resolved),
        ):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "direct_post_video"
        assert result["publish_id"] == "pub_123"

        # init request shape
        init_body = mock_client.request.call_args.kwargs["json"]
        assert mock_client.request.call_args.kwargs["url"].endswith(
            "/v2/post/publish/video/init/"
        )
        assert init_body["source_info"]["source"] == "FILE_UPLOAD"
        assert init_body["source_info"]["video_size"] == 100
        assert init_body["source_info"]["chunk_size"] == 100
        assert init_body["source_info"]["total_chunk_count"] == 1
        assert init_body["post_info"]["privacy_level"] == "SELF_ONLY"
        assert init_body["post_info"]["disable_comment"] is True
        assert init_body["post_info"]["title"] == "hello"

        # chunk upload: whole file in one PUT with the right Content-Range
        put_kwargs = mock_client.put.call_args.kwargs
        assert put_kwargs["headers"]["Content-Range"] == "bytes 0-99/100"
        assert put_kwargs["content"] == b"x" * 100

    @pytest.mark.asyncio
    async def test_direct_post_video_rejects_private_upload_url(self):
        node = build_node(
            TikTokDirectPostVideoConfig(
                video_url="https://example.com/v.mp4",
                privacy_level="SELF_ONLY",
            )
        )
        init_resp = mock_response(
            {
                "data": {
                    "publish_id": "pub_123",
                    "upload_url": "http://169.254.169.254/latest/meta-data",
                },
                "error": {"code": "ok"},
            }
        )
        resolved = ResolvedMedia(
            data=b"x" * 100, mime_type="video/mp4", filename="v.mp4"
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.request = AsyncMock(return_value=init_resp)
        mock_client.put = AsyncMock()

        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "nodes.core.media_resolver.resolve_media_input",
            new=AsyncMock(return_value=resolved),
        ):
            with pytest.raises(ValueError, match="non-public address"):
                await node.execute({})
        mock_client.put.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_direct_post_video_init_failure_skips_upload(self):
        config = TikTokDirectPostVideoConfig(
            video_url="https://example.com/v.mp4", privacy_level="SELF_ONLY"
        )
        node = build_node(config)
        resolved = ResolvedMedia(data=b"x" * 10, mime_type="video/mp4", filename="v.mp4")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.request = AsyncMock(
            return_value=mock_response({"error": {"message": "denied"}}, status_code=403)
        )
        mock_client.put = AsyncMock()

        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "nodes.core.media_resolver.resolve_media_input",
            new=AsyncMock(return_value=resolved),
        ):
            result = await node.execute({})

        assert result["status"] == "error"
        mock_client.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_direct_post_photo(self):
        config = TikTokDirectPostPhotoConfig(
            photo_urls="https://a.com/1.jpg, https://a.com/2.jpg",
            title="t",
            description="d",
            privacy_level="SELF_ONLY",
            photo_cover_index=1,
        )
        node = build_node(config)
        api_resp = {"data": {"publish_id": "pub_9"}, "error": {"code": "ok"}}
        ctx, mock_client = patch_http(mock_response(api_resp))
        with ctx:
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "direct_post_photo"
        assert_request(mock_client, "POST", "/v2/post/publish/content/init/")
        body = mock_client.request.call_args.kwargs["json"]
        assert body["media_type"] == "PHOTO"
        assert body["post_mode"] == "DIRECT_POST"
        assert body["source_info"]["photo_images"] == [
            "https://a.com/1.jpg",
            "https://a.com/2.jpg",
        ]
        assert body["source_info"]["photo_cover_index"] == 1


class TestPrivacyOptions:
    def test_all_privacy_levels_available_and_public_default(self):
        # Audited app: every privacy level is selectable and the default is public.
        cfg = TikTokDirectPostVideoConfig(video_url="https://x/v.mp4")
        assert cfg.privacy_level == "PUBLIC_TO_EVERYONE"

        schema = TikTokDirectPostVideoConfig.model_json_schema()
        enum = schema["properties"]["privacy_level"]["enum"]
        assert set(enum) == {
            "PUBLIC_TO_EVERYONE",
            "MUTUAL_FOLLOW_FRIENDS",
            "FOLLOWER_OF_CREATOR",
            "SELF_ONLY",
        }

    def test_photo_privacy_default_public(self):
        cfg = TikTokDirectPostPhotoConfig(photo_urls="https://x/1.jpg")
        assert cfg.privacy_level == "PUBLIC_TO_EVERYONE"
